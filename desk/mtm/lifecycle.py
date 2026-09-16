"""Ticket → dated cashflow schedule (design §4: date rules, quantities, the cashflow catalogue).

This is the physical layer: it turns one purchase SPA carrying 1–3 bills of lading into the dated flows an importer
actually pays and receives — LC fees and usance interest, duty and the IGST credit lag, port and demurrage, the
supplier claim, the domestic sale and its credit period, MCX margin and USD/INR forwards.

Three invariants make the rest of the engine possible:

* **A flow is a closed-form function of `(MarketState, clock, history)`**, never a number baked in at build time.
  That is what lets the attribution chain revalue the same flow eight times a day under partially swapped states.
* **`expand` takes contracts-as-of `C` and events-as-of `E`.** A term exists only from its own contract / entry /
  booking date; an event bites only from its `known_date` (design D7). Swapping `E` is attribution step 6, swapping
  `C` is step 8 — so an operational surprise lands in (f) and a new booking lands in `new_deal` automatically.
* **Every derived date rolls FOLLOWING and independently** (design §4.1). Dwell for demurrage is counted in
  calendar days; milestones in panel days.

`pnl_class` separates P&L from balance-sheet movements (IGST paid and credited, MCX initial margin): BS flows move
cash — and therefore funding — but never P&L, and their undiscounted lifetime sum per trade is zero.

**Variation margin needs no clock in the schedule.** A VM flow for day `s` is
`dir x lots x lot_kg x (F(s) - F(s-1))`, and `curves.mcx_at` returns today's mark for any day at or beyond the clock.
So every VM day after the clock values to exactly zero, and the whole margin stream can be built once per
(contracts, events) pair without peeking at the valuation date.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from desk import units
from desk.book import schema as bs
from desk.mtm import curves
from desk.parity import quality as p1_quality

PNL = "PNL"
BS = "BS"
USD = "USD"
INR = "INR"
NEW = "NEW"
ROLL = "ROLL"

LANE_BOX = {"JEA_NSA": "20ft", "USEC_MUN": "40ft"}


# ------------------------------------------------------------------------------------------------------- flows
@dataclass(frozen=True)
class Flow:
    """One dated cashflow (or, when `settle_date` is None, a mark that never settles)."""

    trade_id: str
    leg_id: str
    leg_type: str
    pnl_class: str
    currency: str
    contract_date: dt.date                      # the term exists from here (contracts-as-of gate)
    settle_date: dt.date | None
    fixing_date: dt.date | None                 # amount frozen once the clock passes this; None = always from M
    amount: Callable[[Any, dt.date, Any], Any]  # (M, tau, HV) -> amount in `currency`
    purpose: str = NEW                          # NEW | ROLL (design D8c routes ROLL bookings to bucket (g))
    lot_id: str = ""
    sale_id: str = ""
    hedge_id: str = ""
    counterparty_id: str = ""
    qty_mt: float = 0.0
    lots: int = 0
    notional_usd: float = 0.0
    event_ids: tuple[str, ...] = ()
    formula: str = ""
    weakest_input_flag: str = "DIRECT"
    label: str = ""                             # e.g. "HYPOTHETICAL STRESS — not a 2022 event"


@dataclass
class Schedule:
    """The flows of one ticket under a given (contracts-as-of, events-as-of) pair, plus the derived dates."""

    trade_id: str
    flows: tuple[Flow, ...]
    lot_dates: Mapping[str, "LotDates"]
    sale_dates: Mapping[str, "SaleDates"]
    quantities: Mapping[str, "LotQuantities"]
    contracts_asof: dt.date
    events_asof: dt.date
    _frozen: dict[int, Any] = field(default_factory=dict, repr=False)

    @property
    def close_date(self) -> dt.date:
        dates = [f.settle_date for f in self.flows if f.settle_date is not None]
        return max(dates) if dates else self.contracts_asof

    @property
    def first_flow_date(self) -> dt.date:
        dates = [f.settle_date for f in self.flows if f.settle_date is not None]
        return min(dates) if dates else self.contracts_asof

    def frozen_amount(self, i: int, H) -> Any:
        """The amount a flow fixed at, evaluated once at its own fixing date and cached."""
        if i not in self._frozen:
            f = self.flows[i]
            d = f.fixing_date
            self._frozen[i] = f.amount(H.state_at(d), d, H.view(d))
        return self._frozen[i]


# --------------------------------------------------------------------------------------------- derived dates
@dataclass(frozen=True)
class LotDates:
    lot_id: str
    bl: dt.date
    lc_pay: dt.date                # documents presented; sight payment / usance acceptance
    maturity: dt.date | None       # usance maturity (goods, usance interest, bill commission)
    pay: dt.date                   # when the goods cash actually leaves
    arrival_cal: dt.date
    arrival: dt.date
    survey_cal: dt.date
    survey: dt.date
    boe_cal: dt.date
    boe: dt.date
    release_cal: dt.date
    release: dt.date
    igst_credit: dt.date
    pricing_month: str
    pricing_end: dt.date | None
    final_invoice: dt.date | None
    claim_settle: dt.date
    freight_settle: dt.date | None
    dwell_days: int


@dataclass(frozen=True)
class SaleDates:
    sale_id: str
    invoice: dt.date
    due: dt.date
    due_contractual: dt.date       # before buyer-delay events — the clock the (f) overdue accrual runs against
    advance: dt.date | None


@dataclass(frozen=True)
class LotQuantities:
    lot_id: str
    boxes: int
    boxes_rejected: int
    q_bl_mt: float
    q_rej_mt: float
    q_clr_mt: float
    q_acc_mt: float
    moisture_excess_frac: float
    discount_frac: float
    survey_known: bool


def _ceil_months(days: int) -> int:
    return max(1, int(math.ceil(days / 30.0)))


def effective_known_date(known: dt.date, affected: dt.date) -> dt.date:
    """An event is known no later than the day it bites (deviation from design D7, recorded in docs/30).

    A ticket may date a `known_date` after the milestone the event moves — Phase 2's T07 dates a buyer payment
    delay 2022-09-26 against a contractual due date of 2022-09-15. Taken literally, the engine would show the
    receivable as collected for eleven days and then un-collect it, and the **cash ledger and the as-of valuation
    would stop agreeing** — which is exactly what the `ledger_identity` control caught. A desk learns a payment has
    not arrived on the day it was due, so the effective known date is the earlier of the two.
    """
    return min(known, affected)


def _active_logistics(t: bs.Ticket, lot: bs.Lot, E: dt.date, H) -> tuple[bs.LogisticsEvent, ...]:
    if E == dt.date.min:
        return ()
    events = [e for e in t.events.logistics if e.lot_id == lot.lot_id]
    if not events:
        return ()
    base = lot_dates(t, lot, dt.date.min, H)          # the same lot with no events active
    out = []
    for e in events:
        bites = base.arrival if e.arrival_delay_days else base.release
        if effective_known_date(e.known_date, bites) <= E:
            out.append(e)
    return tuple(out)


def _quality_event(t: bs.Ticket, lot_id: str) -> bs.QualityEvent | None:
    for e in t.events.quality:
        if e.lot_id == lot_id:
            return e
    return None


def lot_dates(t: bs.Ticket, lot: bs.Lot, E: dt.date, H) -> LotDates:
    """Design §4.1 applied to one bill of lading. Every milestone rolls following, independently."""
    cal = H.cal
    b = lot.bl_date
    lane = t.lane.value
    logistics = _active_logistics(t, lot, E, H)
    arrival_delay = sum(e.arrival_delay_days for e in logistics)
    extra_dwell = sum(e.extra_dwell_days for e in logistics)

    lc_lag = int(H.param("lc_sight_payment_lag_days", b))
    lc_pay = cal.roll(b + dt.timedelta(days=lc_lag))
    usance = t.purchase.payment.usance_days
    maturity = cal.roll(b + dt.timedelta(days=int(usance))) if usance else None
    pay = maturity if maturity is not None else lc_pay

    transit = int(H.param(f"transit_days_{lane.lower()}", b))
    arrival_cal = b + dt.timedelta(days=transit + arrival_delay)
    survey_cal = arrival_cal + dt.timedelta(days=int(H.param("survey_lag_days", b)))
    boe_cal = arrival_cal + dt.timedelta(days=int(H.param("boe_lag_days", b)))
    clearance = int(H.param("clearance_delivery_days", b))
    release_cal = arrival_cal + dt.timedelta(days=clearance + extra_dwell)
    igst_lag = int(H.param("igst_credit_lag_days", b))

    month = pd.Period(f"{b.year}-{b.month:02d}", freq="M") + 1
    pricing_days = cal.month_days(month)
    pricing_end = pricing_days[-1] if pricing_days else None
    final_lag = int(H.param("final_invoice_lag_bdays", b))
    final_invoice = None
    if pricing_end is not None:
        # the seller computes the M+1 average, but cannot invoice a final WEIGHT before the joint survey
        final_invoice = max(cal.shift(pricing_end, final_lag), cal.roll(survey_cal))

    claim_lag = int(H.param("claim_settle_lag_days", b))
    freight_settle = None
    if t.freight is not None:
        prepaid = t.freight.payment_terms is bs.FreightPaymentTerms.PREPAID_AT_BL
        freight_settle = cal.roll(b) if prepaid else cal.roll(arrival_cal)

    return LotDates(
        lot_id=lot.lot_id, bl=b, lc_pay=lc_pay, maturity=maturity, pay=pay,
        arrival_cal=arrival_cal, arrival=cal.roll(arrival_cal),
        survey_cal=survey_cal, survey=cal.roll(survey_cal),
        boe_cal=boe_cal, boe=cal.roll(boe_cal),
        release_cal=release_cal, release=cal.roll(release_cal),
        igst_credit=cal.roll(boe_cal + dt.timedelta(days=igst_lag)),
        pricing_month=str(month), pricing_end=pricing_end, final_invoice=final_invoice,
        claim_settle=cal.roll(survey_cal + dt.timedelta(days=claim_lag)),
        freight_settle=freight_settle,
        dwell_days=(release_cal - arrival_cal).days,
    )


def lot_quantities(t: bs.Ticket, lot: bs.Lot, dates: LotDates, E: dt.date, H) -> LotQuantities:
    """Design §4.2 — the SPA weight and price adjustments, reusing Phase 1's settlement arithmetic."""
    payload = t.payload_mt_per_box
    q_bl = lot.boxes * payload
    ev = _quality_event(t, lot.lot_id)
    if ev is None or dates.survey > E:
        return LotQuantities(lot.lot_id, lot.boxes, 0, q_bl, 0.0, q_bl, q_bl, 0.0, 0.0, False)

    n_rej = int(ev.rejected_boxes)
    q_rej = n_rej * payload
    q_clr = q_bl - q_rej
    grade = t.grade.value
    d0 = dates.survey
    franchise = t.purchase.spa.moisture_franchise_frac
    if franchise is None:
        franchise = float(H.param("standard_moisture_franchise_frac", d0))
    limit = t.purchase.spa.contamination_limit_frac
    if limit is None:
        limit = float(H.param(f"contamination_frac_{grade}", d0))
    multiple = t.purchase.spa.discount_multiple
    if multiple is None:
        multiple = float(H.param("spa_contamination_discount_multiple", d0))
    ratio = float(H.param("spa_moisture_deduction_ratio", d0))

    m_ex = max(0.0, ev.moisture_actual_frac - franchise)
    disc = multiple * max(0.0, ev.contamination_actual_frac - limit)
    q_acc = q_clr * (1.0 - ratio * m_ex)

    # Control: when the SPA uses the registered template values, Phase 1's own function must return the same numbers.
    p1 = p1_quality.settle_weight_and_penalty(grade, q_clr, ev.moisture_actual_frac, ev.contamination_actual_frac)
    same_template = (abs(p1.moisture_franchise_frac - franchise) < 1e-12
                     and abs(p1.contamination_limit_frac - limit) < 1e-12
                     and abs(multiple - float(H.param("spa_contamination_discount_multiple", d0))) < 1e-12)
    if same_template and (abs(p1.payable_mt - q_acc) > 1e-6 or abs(p1.discount_frac - disc) > 1e-12):
        raise AssertionError(
            f"{t.trade_id}/{lot.lot_id}: SPA settlement disagrees with desk.parity.quality "
            f"({q_acc} vs {p1.payable_mt} MT, {disc} vs {p1.discount_frac})")
    return LotQuantities(lot.lot_id, lot.boxes, n_rej, q_bl, q_rej, q_clr, q_acc, m_ex, disc, True)


def sale_dates(t: bs.Ticket, sale: bs.Sale, lots: Mapping[str, LotDates], E: dt.date, H) -> SaleDates:
    cal = H.cal
    release_cal = max(lots[lid].release_cal for lid in sale.lot_ids)
    if sale.pricing.type is bs.SalePricingType.MCX_AVG:
        release_cal = max(release_cal, sale.pricing.window_end)
    invoice = cal.roll(release_cal)
    credit_days = int(sale.payment.credit_days or 0)
    due_contractual = cal.roll(invoice + dt.timedelta(days=credit_days))
    delay = sum(e.delay_days for e in t.events.buyer_payment_delay
                if e.sale_id == sale.sale_id and effective_known_date(e.known_date, due_contractual) <= E)
    due = cal.roll(invoice + dt.timedelta(days=credit_days + delay))
    return SaleDates(sale.sale_id, invoice, due, due_contractual, sale.payment.advance_date)


# ------------------------------------------------------------------------------------------------ price helpers
def purchase_unit_price(t: bs.Ticket, HV, M, tau: dt.date, dates: LotDates, provisional: bool = True):
    """USD/t on the SPA's own basis: the fixed price, or the provisional / final M+1 average."""
    pr = t.purchase.pricing
    if pr.type is bs.PurchasePricingType.FIXED:
        return pr.price_usd_t
    if provisional:
        return pr.factor_frac * curves.cash_at(HV, M, tau, dates.bl) + pr.premium_usd_t
    avg, _frac = curves.lme_month_avg(HV, M, tau, dates.pricing_month)
    return pr.factor_frac * avg + pr.premium_usd_t


def sale_unit_price(sale: bs.Sale, HV, M, tau: dt.date):
    """₹/MT of scrap on the sale's own formula."""
    pr = sale.pricing
    if pr.type is bs.SalePricingType.FIXED:
        return pr.price_inr_t
    avg, _frac = curves.mcx_avg(HV, M, tau, pr.window_start, pr.window_end)
    return pr.factor_frac * avg * units.KG_PER_MT + pr.premium_inr_t


def freight_rate_box(t: bs.Ticket, HV, M, tau: dt.date, C: dt.date):
    """USD per container: the executed fixture once it is booked, otherwise today's market (design D12)."""
    fr = t.freight
    if fr is not None and fr.fixture_date is not None and fr.fixture_date <= C:
        return fr.rate_usd_box
    return curves.box_mkt(HV, M, tau, t.lane.value, LANE_BOX[t.lane.value])


def cfr_unit_price(t: bs.Ticket, HV, M, tau: dt.date, dates: LotDates, C: dt.date):
    """CFR-basis USD/t used for insurance and the customs assessable value (FOB adds the freight the desk pays)."""
    p = purchase_unit_price(t, HV, M, tau, dates, provisional=True)
    if t.purchase.incoterm is bs.Incoterm.CFR:
        return p
    return p + freight_rate_box(t, HV, M, tau, C) / t.payload_mt_per_box


# --------------------------------------------------------------------------------------------------- expansion
def expand(t: bs.Ticket, book: bs.Book, C: dt.date, E: dt.date, H, *, allow_hypothetical: bool = False) -> Schedule:
    """Every flow of one ticket, given contracts-as-of `C` and events-as-of `E`."""
    cal = H.cal
    lane = t.lane.value
    grade = t.grade.value
    box = LANE_BOX[lane]
    base_payload = float(H.param(f"container_payload_mt_{box}", t.trade_date))
    supplier = t.purchase.supplier_id
    td = t.trade_date
    fixed_price = t.purchase.pricing.type is bs.PurchasePricingType.FIXED
    usance = t.purchase.payment.instrument is bs.PaymentInstrument.LC_USANCE

    dates = {lot.lot_id: lot_dates(t, lot, E, H) for lot in t.shipment.lots}
    qty = {lot.lot_id: lot_quantities(t, lot, dates[lot.lot_id], E, H) for lot in t.shipment.lots}
    sdates = {s.sale_id: sale_dates(t, s, dates, E, H) for s in t.sales}
    sold_lots = {lid for s in t.sales if s.contract_date <= C for lid in s.lot_ids}

    flows: list[Flow] = []
    for lot in t.shipment.lots:
        flows.extend(_lot_flows(t, lot, dates[lot.lot_id], qty[lot.lot_id], C, E, H,
                                lane=lane, grade=grade, box=box, base_payload=base_payload,
                                supplier=supplier, fixed_price=fixed_price, usance=usance,
                                sold=lot.lot_id in sold_lots))
    flows.extend(_lc_flows(t, dates, C, H, usance=usance))
    for sale in t.sales:
        if sale.contract_date <= C:
            flows.extend(_sale_flows(t, sale, sdates[sale.sale_id], dates, qty))
    flows.extend(_mcx_flows(t, C, H))
    flows.extend(_fx_flows(t, C, H))
    flows.extend(_freight_swap_flows(t, lane, box, allow_hypothetical))
    # Contracts-as-of, enforced once and for all: a term exists only from its own contract / entry / booking date.
    # Before the trade date the schedule is therefore empty, which is what makes a ticket's whole first-day value
    # land in `new_deal` (CONTRACTS §7.2) with no special case in the attribution chain.
    flows = [f for f in flows if f.contract_date <= C]
    for f in flows:
        if f.fixing_date is not None and f.settle_date is not None and f.fixing_date > f.settle_date:
            # a flow whose amount fixes after it has settled would make the realised ledger and the mark diverge
            raise AssertionError(f"{t.trade_id}/{f.leg_id}/{f.leg_type}: fixing {f.fixing_date} is after "
                                 f"settlement {f.settle_date}")
    return Schedule(t.trade_id, tuple(flows), dates, sdates, qty, C, E)


def _lot_flows(t: bs.Ticket, lot: bs.Lot, ld: LotDates, lq: LotQuantities, C: dt.date, E: dt.date, H, *,
               lane: str, grade: str, box: str, base_payload: float, supplier: str,
               fixed_price: bool, usance: bool, sold: bool) -> list[Flow]:
    """Every flow that belongs to one bill of lading (design §4.3)."""
    out: list[Flow] = []
    td = t.trade_date
    lid = lot.lot_id
    pr = t.purchase.pricing

    def bill_usd(M, tau, HV):
        """The USD value of the supplier's (provisional) invoice for this lot."""
        p = purchase_unit_price(t, HV, M, tau, ld, provisional=True)
        return lq.q_bl_mt * p if fixed_price else pr.provisional_frac * lq.q_bl_mt * p

    def cfr_usd_t(M, tau, HV):
        return cfr_unit_price(t, HV, M, tau, ld, C)

    ins_rate = float(H.param("insurance_rate", ld.bl))
    ins_uplift = float(H.param("insured_value_uplift", ld.bl))

    def assessable_inr(M, tau, HV):
        """Customs assessable value of the cleared tonnage, at the CBIC notified rate (landing_charges_frac = 0)."""
        cif = cfr_usd_t(M, tau, HV) * (1.0 + ins_rate * ins_uplift)
        return lq.q_clr_mt * cif * M.customs_usdinr_import

    # ------------------------------------------------------------------------------------------ purchase price
    if fixed_price:
        out.append(Flow(t.trade_id, f"PURCHASE:{lid}", "PURCHASE_INVOICE", PNL, USD, td, ld.pay, None,
                        lambda M, tau, HV: -lq.q_bl_mt * pr.price_usd_t,
                        lot_id=lid, counterparty_id=supplier, qty_mt=lq.q_bl_mt,
                        formula="-q_bl x price_usd_t", weakest_input_flag="SIM"))
    else:
        out.append(Flow(t.trade_id, f"PURCHASE:{lid}", "PURCHASE_PROVISIONAL", PNL, USD, td, ld.pay, ld.bl,
                        lambda M, tau, HV: -bill_usd(M, tau, HV),
                        lot_id=lid, counterparty_id=supplier, qty_mt=lq.q_bl_mt,
                        formula="-provisional_frac x q_bl x (factor x cash(bl) + premium)",
                        weakest_input_flag="DIRECT"))

        def final_usd(M, tau, HV):
            p_fin = purchase_unit_price(t, HV, M, tau, ld, provisional=False)
            prov = pr.provisional_frac * lq.q_bl_mt * purchase_unit_price(t, HV, M, tau, ld, provisional=True)
            return -(lq.q_acc_mt * p_fin * (1.0 - lq.discount_frac) - prov)

        out.append(Flow(t.trade_id, f"PURCHASE:{lid}", "PURCHASE_FINAL", PNL, USD, td, ld.final_invoice,
                        max(ld.pricing_end, ld.survey), final_usd, lot_id=lid, counterparty_id=supplier,
                        qty_mt=lq.q_acc_mt,
                        formula="-(q_acc x (factor x A_P + premium) x (1 - disc) - provisional)",
                        weakest_input_flag="DIRECT"))

    # ------------------------------------------------------------------------------------- supplier quality claim
    ev = _quality_event(t, lid)
    if fixed_price and lq.survey_known and ev is not None and (
            lq.q_rej_mt > 0 or lq.moisture_excess_frac > 0 or lq.discount_frac > 0):
        ratio = float(H.param("spa_moisture_deduction_ratio", ld.survey))
        claim_mt = lq.q_rej_mt + lq.q_clr_mt * ratio * lq.moisture_excess_frac + lq.q_acc_mt * lq.discount_frac
        recovery = ev.claim_recovery_frac
        out.append(Flow(t.trade_id, f"CLAIM:{lid}", "QUALITY_CLAIM", PNL, USD, td, ld.claim_settle, ld.survey,
                        lambda M, tau, HV: recovery * pr.price_usd_t * claim_mt,
                        lot_id=lid, counterparty_id=supplier, qty_mt=claim_mt, event_ids=(f"QUALITY:{lid}",),
                        formula="+recovery x price x (q_rej + q_clr x ratio x m_ex + q_acc x disc)",
                        weakest_input_flag="SIM"))

    # --------------------------------------------------------------------------------------------------- freight
    if t.freight is not None:
        out.append(Flow(t.trade_id, f"FREIGHT:{lid}", "FREIGHT", PNL, USD, td, ld.freight_settle,
                        t.freight.fixture_date if t.freight.fixture_date is not None else ld.bl,
                        lambda M, tau, HV: -lot.boxes * freight_rate_box(t, HV, M, tau, C),
                        lot_id=lid, counterparty_id=t.freight.forwarder, qty_mt=lq.q_bl_mt,
                        formula="-boxes x (fixture rate once booked, else market box rate)",
                        weakest_input_flag="ASSUMPTION"))

    out.append(Flow(t.trade_id, f"INSURANCE:{lid}", "INSURANCE", PNL, USD, td, ld.bl, ld.bl,
                    lambda M, tau, HV: -ins_rate * ins_uplift * lq.q_bl_mt * cfr_usd_t(M, tau, HV),
                    lot_id=lid, qty_mt=lq.q_bl_mt,
                    formula="-insurance_rate x insured_value_uplift x cfr_value_usd",
                    weakest_input_flag="ASSUMPTION"))

    if curves.psic_applies(H.view(td), td, lane):
        psic = float(H.param("psic_cost_usd_per_box", ld.bl))
        out.append(Flow(t.trade_id, f"PSIC:{lid}", "PSIC", PNL, USD, td, ld.bl, ld.bl,
                        lambda M, tau, HV: -psic * lot.boxes, lot_id=lid,
                        formula="-psic_cost_usd_per_box x boxes", weakest_input_flag="ASSUMPTION"))

    # --------------------------------------------------------------------------------------------- trade finance
    if usance:
        fee = float(H.param("lc_usance_fee_frac_per_month", ld.lc_pay))
        months = _ceil_months(int(t.purchase.payment.usance_days))
        out.append(Flow(t.trade_id, f"LC_USANCE_FEE:{lid}", "LC_USANCE_FEE", PNL, USD, td, ld.lc_pay, ld.lc_pay,
                        lambda M, tau, HV: -fee * months * bill_usd(M, tau, HV), lot_id=lid,
                        formula="-lc_usance_fee_frac_per_month x ceil(usance/30) x bill_usd",
                        weakest_input_flag="DIRECT"))
        spread = float(H.param("usance_interest_spread_pa", ld.lc_pay))
        udays = int(t.purchase.payment.usance_days)
        out.append(Flow(t.trade_id, f"USANCE_INTEREST:{lid}", "USANCE_INTEREST", PNL, USD, td, ld.maturity, ld.lc_pay,
                        lambda M, tau, HV: -bill_usd(M, tau, HV) * (M.usd_rate_3m_pa + spread) * udays
                        / units.DAY_COUNT_USD, lot_id=lid,
                        formula="-bill_usd x (usd_rate_3m_pa@acceptance + usance_interest_spread_pa) x days/360",
                        weakest_input_flag="PROXY"))

    comm = float(H.param("import_bill_commission_frac", ld.pay))
    out.append(Flow(t.trade_id, f"BILL_COMMISSION:{lid}", "IMPORT_BILL_COMMISSION", PNL, USD, td, ld.pay, ld.pay,
                    lambda M, tau, HV: -comm * bill_usd(M, tau, HV), lot_id=lid,
                    formula="-import_bill_commission_frac x bill_usd", weakest_input_flag="DIRECT"))

    # ---------------------------------------------------------------------------------------------------- customs
    bcd = float(H.param("bcd_scrap_hs7602", ld.boe))
    sws = float(H.param("sws_rate_on_bcd", ld.boe))
    igst_rate = float(H.param("igst_rate_hs7602", ld.boe))
    itc = bool(H.param("igst_itc_available", ld.boe))

    out.append(Flow(t.trade_id, f"DUTY:{lid}", "CUSTOMS_DUTY", PNL, INR, td, ld.boe, ld.boe,
                    lambda M, tau, HV: -assessable_inr(M, tau, HV) * bcd * (1.0 + sws),
                    lot_id=lid, qty_mt=lq.q_clr_mt,
                    formula="-assessable_inr x bcd_scrap_hs7602 x (1 + sws_rate_on_bcd)",
                    weakest_input_flag="DIRECT"))
    out.append(Flow(t.trade_id, f"IGST:{lid}", "IGST_IMPORT", BS if itc else PNL, INR, td, ld.boe, ld.boe,
                    lambda M, tau, HV: -assessable_inr(M, tau, HV) * (1.0 + bcd * (1.0 + sws)) * igst_rate,
                    lot_id=lid, formula="-(assessable + duty) x igst_rate_hs7602", weakest_input_flag="DIRECT"))
    if itc:
        out.append(Flow(t.trade_id, f"IGST:{lid}", "IGST_CREDIT", BS, INR, td, ld.igst_credit, ld.boe,
                        lambda M, tau, HV: assessable_inr(M, tau, HV) * (1.0 + bcd * (1.0 + sws)) * igst_rate,
                        lot_id=lid, formula="+(assessable + duty) x igst_rate at igst_credit_lag_days",
                        weakest_input_flag="DIRECT"))

    if not fixed_price:
        def duty_diff(M, tau, HV):
            p_fin = purchase_unit_price(t, HV, M, tau, ld, provisional=False)
            p_prov = purchase_unit_price(t, HV, M, tau, ld, provisional=True)
            cfx = HV.state_at(ld.boe).customs_usdinr_import if ld.boe < tau else M.customs_usdinr_import
            d_av = lq.q_acc_mt * (p_fin - p_prov) * (1.0 + ins_rate * ins_uplift) * cfx
            return -d_av * bcd * (1.0 + sws)

        out.append(Flow(t.trade_id, f"DUTY:{lid}", "CUSTOMS_DUTY_DIFFERENTIAL", PNL, INR, td, ld.final_invoice,
                        ld.final_invoice, duty_diff, lot_id=lid,
                        formula="-dAV x bcd x (1 + sws) on (P_final - P_provisional)", weakest_input_flag="DIRECT"))

    # ------------------------------------------------------------------------------------------ port and dwell
    port_key = "port_cf_charges_inr_t_nsa" if lane == "JEA_NSA" else "port_cf_charges_inr_t_mun"
    port_rate = float(H.param(port_key, td))
    cleared_boxes = lot.boxes - lq.boxes_rejected
    out.append(Flow(t.trade_id, f"PORT:{lid}", "PORT_CHARGES", PNL, INR, td, ld.release, None,
                    lambda M, tau, HV: -port_rate * base_payload * cleared_boxes, lot_id=lid,
                    formula="-port_cf_charges_inr_t x base_payload x cleared boxes", weakest_input_flag="ASSUMPTION"))

    free_days = int(H.param("detention_free_days", td))
    chargeable = max(0, ld.dwell_days - free_days)
    if chargeable > 0:
        rate = float(H.param("demurrage_usd_per_box_day", td))
        out.append(Flow(t.trade_id, f"DEMURRAGE:{lid}", "DEMURRAGE", PNL, USD, td, ld.release, None,
                        lambda M, tau, HV: -cleared_boxes * chargeable * rate, lot_id=lid,
                        event_ids=tuple(e.event_id for e in _active_logistics(t, lot, E, H)),
                        formula="-cleared boxes x max(0, dwell - detention_free_days) x demurrage_usd_per_box_day",
                        weakest_input_flag="SIM"))

    # ------------------------------------------------------ unsold cargo marks at import replacement value (D5)
    if not sold:
        q_exp = lq.q_acc_mt if lq.survey_known else lq.q_bl_mt
        out.append(Flow(t.trade_id, f"INVENTORY:{lid}", "INVENTORY_MARK", PNL, INR, td, None, None,
                        lambda M, tau, HV: q_exp * curves.replacement_value(HV, M, tau, grade, lane, box),
                        lot_id=lid, qty_mt=q_exp,
                        formula="+q x (goods + BCD + SWS + port/PSIC) at today's market, no finance",
                        weakest_input_flag="ASSUMPTION"))
    return out


def _lc_flows(t: bs.Ticket, dates: Mapping[str, LotDates], C: dt.date, H, *, usance: bool) -> list[Flow]:
    """Letter-of-credit charges: one LC per ticket, sized on the SPA quantity and the presentation period."""
    lc = t.purchase.payment
    if lc.lc_open_date > C:
        return []
    presentation = int(H.param("lc_presentation_period_days", lc.lc_open_date))
    validity_days = (t.shipment.laycan_end + dt.timedelta(days=presentation) - lc.lc_open_date).days
    tol = t.purchase.spa.quantity_tolerance_frac or float(H.param("lc_amount_tolerance_frac", lc.lc_open_date))
    ld0 = dates[t.shipment.lots[0].lot_id]

    def lc_value_usd(M, tau, HV):
        return t.quantity_mt * purchase_unit_price(t, HV, M, tau, ld0, provisional=True) * (1.0 + tol)

    open_fee = float(H.param("lc_opening_fee_frac_per_month", lc.lc_open_date))
    months = _ceil_months(validity_days)
    out = [Flow(t.trade_id, "LC_FEES", "LC_OPENING_FEE", PNL, USD, t.trade_date, lc.lc_open_date, lc.lc_open_date,
                lambda M, tau, HV: -open_fee * months * lc_value_usd(M, tau, HV),
                formula="-lc_opening_fee_frac_per_month x ceil(validity/30) x lc_value_usd",
                weakest_input_flag="DIRECT")]
    if lc.confirmed and lc.confirmation_charges_for is bs.ChargesFor.APPLICANT:
        conf = float(H.param("lc_confirmation_fee_pa", lc.lc_open_date))
        tenor = validity_days + int(lc.usance_days or 0)
        out.append(Flow(t.trade_id, "LC_FEES", "LC_CONFIRMATION_FEE", PNL, USD, t.trade_date, lc.lc_open_date,
                        lc.lc_open_date,
                        lambda M, tau, HV: -conf * lc_value_usd(M, tau, HV) * tenor / units.DAY_COUNT_USD,
                        formula="-lc_confirmation_fee_pa x lc_value_usd x (validity + usance)/360",
                        weakest_input_flag="PROXY"))
    return out


def _sale_flows(t: bs.Ticket, sale: bs.Sale, sd: SaleDates, dates: Mapping[str, LotDates],
                qty: Mapping[str, LotQuantities]) -> list[Flow]:
    lots_q = tuple(qty[lid] for lid in sale.lot_ids)
    q_plan = sum(q.q_bl_mt for q in lots_q)
    advance_frac = sale.payment.advance_frac or 0.0
    passthrough = sale.quality_passthrough
    surveys = max(dates[lid].survey for lid in sale.lot_ids)
    if sale.pricing.type is bs.SalePricingType.MCX_AVG:
        fix_sale = max(sale.pricing.window_end, surveys)
    else:
        fix_sale = max(sale.contract_date, surveys)

    out: list[Flow] = []
    if advance_frac:
        out.append(Flow(t.trade_id, f"SALE:{sale.sale_id}", "SALE_ADVANCE", PNL, INR, sale.contract_date, sd.advance,
                        sd.advance,
                        lambda M, tau, HV: advance_frac * q_plan * sale_unit_price(sale, HV, M, tau),
                        sale_id=sale.sale_id, counterparty_id=sale.buyer_id, qty_mt=q_plan,
                        formula="+advance_frac x q_plan x P_sale", weakest_input_flag="SIM"))

    def balance_inr(M, tau, HV):
        p = sale_unit_price(sale, HV, M, tau)
        gross = sum(q.q_acc_mt * p * (1.0 - (q.discount_frac if passthrough else 0.0)) for q in lots_q)
        return gross - advance_frac * q_plan * p

    out.append(Flow(t.trade_id, f"SALE:{sale.sale_id}", "SALE_BALANCE", PNL, INR, sale.contract_date, sd.due,
                    fix_sale, balance_inr, sale_id=sale.sale_id, counterparty_id=sale.buyer_id,
                    qty_mt=sum(q.q_acc_mt for q in lots_q),
                    event_ids=tuple(e.event_id for e in t.events.buyer_payment_delay if e.sale_id == sale.sale_id),
                    formula="+q_acc x P_sale x (1 - disc passthrough) - advance", weakest_input_flag="SIM"))
    return out


def _mcx_flows(t: bs.Ticket, C: dt.date, H) -> list[Flow]:
    """Variation margin, initial margin, slippage and transaction charges for each hedge tranche (design D4b)."""
    cal = H.cal
    td = t.trade_date
    lot_kg = float(H.param("mcx_al_lot_mt", td)) * units.KG_PER_MT
    slip = float(H.param("mcx_slippage_ticks", td)) * float(H.param("mcx_al_tick_inr_kg", td))
    txn_frac = float(H.param("mcx_txn_cost_frac", td))
    margin_frac = float(H.param("mcx_al_margin_used_frac", td))
    roll_targets = {tr.roll_to for tr in t.hedges.mcx.tranches if tr.roll_to}

    out: list[Flow] = []
    for tr in t.hedges.mcx.tranches:
        if tr.entry_date > C:
            continue
        sign = 1 if tr.direction is bs.HedgeDirection.BUY else -1
        month = tr.contract_month
        leg = f"MCX:{tr.hedge_id}"
        days = cal.between(tr.entry_date, tr.exit_date)

        # Day one is margined against the ENTRY SETTLE (design §4.3), which is a historical constant, not a function
        # of the state. Its value is therefore exactly zero — the position has earned nothing on the day it was
        # entered — while its *derivative* is the position's full delta, so the exposure table shows the hedge from
        # the entry day rather than from the day after.
        entry_settle = H.mcx_settle(tr.entry_date, month)
        out.append(Flow(t.trade_id, leg, "MCX_VARIATION_MARGIN", PNL, INR, tr.entry_date, tr.entry_date,
                        tr.entry_date, _vm_entry_amount(sign, tr.lots, lot_kg, month, entry_settle, tr.entry_date),
                        hedge_id=tr.hedge_id, lots=sign * tr.lots,
                        formula="direction x lots x lot_kg x (F(entry) - entry settle) = 0 by construction",
                        weakest_input_flag="PROXY"))
        for prev_d, d in zip(days, days[1:]):
            out.append(Flow(t.trade_id, leg, "MCX_VARIATION_MARGIN", PNL, INR, tr.entry_date, d, d,
                            _vm_amount(sign, tr.lots, lot_kg, month, prev_d, d),
                            hedge_id=tr.hedge_id, lots=sign * tr.lots,
                            formula="direction x lots x lot_kg x (F(s) - F(s-1))", weakest_input_flag="PROXY"))

        for i, d in enumerate(days):
            out.append(Flow(t.trade_id, leg, "MCX_INITIAL_MARGIN", BS, INR, tr.entry_date, d, d,
                            _im_amount(tr.lots, lot_kg, margin_frac, month, days[i - 1] if i else None, d,
                                       tr.exit_date),
                            hedge_id=tr.hedge_id, lots=sign * tr.lots,
                            formula="-d(lots x lot_kg x F(s) x mcx_al_margin_used_frac)", weakest_input_flag="PROXY"))

        for when, purpose, closing in ((tr.entry_date, ROLL if tr.hedge_id in roll_targets else NEW, False),
                                       (tr.exit_date, ROLL if tr.exit_reason is bs.HedgeExitReason.ROLL else NEW,
                                        True)):
            if when > C:
                continue
            fill_sign = -sign if closing else sign          # closing a short means buying
            out.append(Flow(t.trade_id, leg, "MCX_SLIPPAGE", PNL, INR, when, when, None,
                            _slippage_amount(tr.lots, lot_kg, slip), purpose=purpose, hedge_id=tr.hedge_id,
                            lots=sign * tr.lots, formula="-lots x lot_kg x mcx_slippage_ticks x tick",
                            weakest_input_flag="ASSUMPTION"))
            out.append(Flow(t.trade_id, leg, "MCX_TRANSACTION_COST", PNL, INR, when, when, when,
                            _txn_amount(tr.lots, lot_kg, month, fill_sign, slip, txn_frac), purpose=purpose,
                            hedge_id=tr.hedge_id, lots=sign * tr.lots,
                            formula="-lots x lot_kg x fill x mcx_txn_cost_frac", weakest_input_flag="ASSUMPTION"))
    return out


def _vm_amount(sign: int, lots: int, lot_kg: float, month: str, prev_d: dt.date, d: dt.date):
    def amount(M, tau, HV):
        return sign * lots * lot_kg * (curves.mcx_at(HV, M, tau, d, month) - curves.mcx_at(HV, M, tau, prev_d, month))
    return amount


def _vm_entry_amount(sign: int, lots: int, lot_kg: float, month: str, entry_settle: float, d: dt.date):
    """Day-one variation margin against the entry settle: zero in value, full position delta in derivative."""
    def amount(M, tau, HV):
        return sign * lots * lot_kg * (curves.mcx_at(HV, M, tau, d, month) - entry_settle)
    return amount


def _im_amount(lots: int, lot_kg: float, margin_frac: float, month: str, prev_d: dt.date | None, d: dt.date,
               exit_date: dt.date):
    """Daily change in posted initial margin; the whole posting returns on the exit day."""
    def amount(M, tau, HV):
        cur = 0.0 if d >= exit_date else lots * lot_kg * curves.mcx_at(HV, M, tau, d, month) * margin_frac
        prev = 0.0
        if prev_d is not None and prev_d < exit_date:
            prev = lots * lot_kg * curves.mcx_at(HV, M, tau, prev_d, month) * margin_frac
        return -(cur - prev)
    return amount


def _slippage_amount(lots: int, lot_kg: float, slip_inr_kg: float):
    def amount(M, tau, HV):
        return -lots * lot_kg * slip_inr_kg
    return amount


def _txn_amount(lots: int, lot_kg: float, month: str, fill_sign: int, slip: float, frac: float):
    def amount(M, tau, HV):
        return -lots * lot_kg * (curves.mcx_price(HV, M, tau, month) + fill_sign * slip) * frac
    return amount


def _fx_flows(t: bs.Ticket, C: dt.date, H) -> list[Flow]:
    out: list[Flow] = []
    for fwd in t.hedges.fx_forwards.lines:
        if fwd.booking_date > C:
            continue
        sign = 1 if fwd.direction is bs.FxDirection.BUY_USD else -1
        K = curves.fx_forward_strike(H, fwd.booking_date, fwd.value_date, sign)
        settle = fwd.cancel_date or fwd.value_date
        out.append(Flow(t.trade_id, f"FX:{fwd.fwd_id}", "FX_FORWARD", PNL, INR, fwd.booking_date, settle, settle,
                        _fwd_amount(sign, fwd.notional_usd, fwd.value_date, K),
                        notional_usd=sign * fwd.notional_usd,
                        formula="sign x notional x (X(tau, value_date) - K)", weakest_input_flag="PROXY"))
    return out


def _fwd_amount(sign: int, notional: float, value_date: dt.date, strike: float):
    def amount(M, tau, HV):
        return sign * notional * (curves.fx_x(HV, M, tau, value_date) - strike)
    return amount


def _freight_swap_flows(t: bs.Ticket, lane: str, box: str, allow_hypothetical: bool) -> list[Flow]:
    fr = t.freight
    if fr is None or fr.swap is None:
        return []
    if not allow_hypothetical:
        raise ValueError(f"{t.trade_id}: the freight swap is PROXY_SWAP_HYPOTHETICAL and barred from the base book")
    sw = fr.swap

    def amount(M, tau, HV):
        return sw.boxes * (curves.box_mkt(HV, M, tau, lane, box) - sw.strike_usd_box)

    return [Flow(t.trade_id, f"FREIGHT_SWAP:{sw.swap_id}", "FREIGHT_SWAP_HYPOTHETICAL", PNL, USD, sw.start_date,
                 sw.settle_date, sw.settle_date, amount,
                 formula="+boxes x (market box rate - strike)", weakest_input_flag="ASSUMPTION",
                 label="HYPOTHETICAL STRESS — not a 2022 event")]


def leg_index(flows: Sequence[Flow]) -> dict[str, list[int]]:
    """leg_id → the indices of its flows (attribution and `mtm_daily.csv` are reported at leg grain)."""
    out: dict[str, list[int]] = {}
    for i, f in enumerate(flows):
        out.setdefault(f.leg_id, []).append(i)
    return out
