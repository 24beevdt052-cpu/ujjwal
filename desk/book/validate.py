"""Phase 2 — the checks on `config/trades.yaml` that need the market panel or the Phase 1 parity model.

`desk.book.schema` decides everything a ticket, the counterparty file and the register can decide on their own
(codes V01–V20). This module is the other half, and it exists because the rules that actually protect the book
from hindsight are the ones that need data: that a trade date really was open under CONTRACTS §5a, that a fixture
rate really was struck against the index of its own day, that a hedge size really was what the stated policy gives
at the entry date, that a rationale cites nothing dated after the trade, and that every cashflow the ticket
implies lands on or before `HORIZON_END`. A rule that is only written down gets broken; these raise.

Codes P01–P12, each with a test in `tests/test_book.py`:

    P01  §5a eligibility: `eligible_on(trade_date, grade, lane)` is True and the ticket's `parity_week_end`
         is the week the look-up actually used.
    P02  container arithmetic against the register payloads, per lot and in total.
    P03  every derived cashflow date (§4.1 of docs/design/30_position_model.md) is <= HORIZON_END.
    P04  buyer credit exposure at every sale booking is within `credit_limit_inr`.
    P05  freight: the fixture rate sits in a stated band over the lane index of the fixture date, the stop-loss
         was never breached before the fixture, and the book-by date is early enough for the boxes to sail.
    P06  MCX: every tranche lives inside its contract month's trading life, a ROLL happens on the registered
         roll deadline, and no position exceeds the DIRECT client limit.
    P07  MCX hedge size reproduces the stated desk policy at the entry date (non-roll entries only).
    P08  no hindsight in a rationale: no dated reference later than the trade date.
    P09  sale prices sit between import replacement value and the smelter netback at the contract date.
    P10  purchase price / factor sits within a stated band of the trade-date parity price.
    P11  cross-phase control: this module's per-day §5 line items reproduce Phase 1 on parity value dates.
    P12  (warning) the MCX proxy moved beyond the exchange's maximum daily price limit on a hedge action day.
    P13  the market numbers a rationale or terms note *quotes* reconcile to the panel, and no note claims its
         inputs were point-in-time when the ticket's own price basis rests on a reconstruction.
    P14  (warning) a contracted advance the desk relies on exceeds that buyer's own credit limit by more than
         the registered policy multiple — performance exposure the receivable-only limit definition cannot see.

Nothing here reads a value dated after the date it is checking against: every look-up goes through
`market_reference(date, ...)` or `panel_row(date)`, both of which take the decision date as their clock.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

import pandas as pd

from desk import HORIZON_END, config, units
from desk.book.schema import (
    Book,
    HedgeDirection,
    HedgeExitReason,
    Incoterm,
    Issue,
    Lane,
    PurchasePricingType,
    Sale,
    SalePricingType,
    Ticket,
    validate_book as validate_schema,
)
from desk.paths import PROCESSED_DIR

# ----------------------------------------------------------------------------- desk policy & lifecycle constants
# These mirror the keys `docs/design/30_position_model.md` §14 proposes for `config/params/book.yaml`. That file
# does not exist yet and is not owned here, so the values are stated as named constants with the same
# justification and the same ASSUMPTION flag, exactly as `tests/test_book_schema.py` already does for
# `boe_lag_days`. When book.yaml lands they move there unchanged. Everything with an existing register key
# (payloads, transit, clearance, free days, the MSME cap, lot size, expiries) is read from `desk.config`.
LC_SIGHT_PAYMENT_LAG_DAYS = 7          # ASSUMPTION — logistics.yaml finance_days_* note: "supplier paid ~day 7"
SURVEY_LAG_DAYS = 1                    # ASSUMPTION — joint survey at the CFS before the Bill of Entry
BOE_LAG_DAYS = 1                       # ASSUMPTION — igst_credit_lag_days note puts the BoE ~1 day after arrival
FINAL_INVOICE_LAG_BDAYS = 5            # ASSUMPTION — seller computes the M+1 average and invoices by T/T
CLAIM_SETTLE_LAG_DAYS = 30             # ASSUMPTION — survey report, seller acceptance, credit note
FREIGHT_BOOKING_DAYS_BEFORE_BL = 10    # ASSUMPTION — NVOCC space-confirmation lead time
LC_AMOUNT_TOLERANCE_FRAC = 0.10        # ASSUMPTION — UCP 600 art.30 'about' tolerance an LC is opened with when
                                       # the SPA states no quantity tolerance of its own (they are different
                                       # concepts: art.30 sizes the credit, the SPA sizes the cargo)

# Desk policy (docs/20_trade_book.md §6). Stated before the book was priced; never fitted to an outcome.
FREIGHT_STOP_LOSS_FRAC = 0.15          # stop = trade-date lane index x (1 + this)
FIXTURE_SPREAD_BAND = (0.0, 0.05)      # an NVOCC all-in rate sits 0-5 % over the assessed lane index
DESK_ARB_SHARE_FRAC = 0.50             # domestic sale price = replacement + this x (netback - replacement)
SALE_PRICE_ROUNDING_INR_T = 250.0      # sale prices are quoted to the nearest 250 ₹/MT
SALE_PRICE_BAND_INR_T = 150.0          # tolerance on the rule once the payment-terms delta is priced explicitly
SALE_CREDIT_BASELINE_DAYS = 30         # the terms the half-the-gap price is quoted on; anything else is priced
PURCHASE_DISCOUNT_BAND_USD_T = (0.0, 30.0)   # the desk bids 0-30 USD/t under trade-date parity
PURCHASE_FACTOR_BAND = (0.0, 0.010)    # a formula purchase is contracted 0-1.0 point under the trade-date factor
HEDGE_RATIO_TOL = 0.06                 # |implied ratio - target| at a non-roll entry
MCX_LOT_TOL = 1                        # lots
FIXTURE_SPREAD_SENSITIVITY = (0.02, 0.05, 0.10)   # NVOCC all-in spread over the index, published as a range
                                       # because the 1.7-2.0 % the book uses is an ASSUMPTION with no 2022
                                       # India-inbound fixture evidence behind it (docs/20 §6.4)

# Tolerances for P13, the reconciliation of prose numbers to the panel. A trader writes round numbers, so the
# check is deliberately loose: it exists to catch a claim that ties to nothing, not to police rounding.
CLAIM_TOL_USD_T = 2.0
CLAIM_TOL_USDINR = 0.01
CLAIM_TOL_PCT_POINTS = 0.3

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
FULL_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY = re.compile(r"\b(\d{1,2})[-/ ](" + "|".join(MONTHS) + r")[a-z]*[-/ ](\d{4})\b", re.I)
_DM = re.compile(r"\b(\d{1,2})[-/ ](" + "|".join(MONTHS) + r")[a-z]*\b", re.I)   # "18-Mar", no year
_MY = re.compile(r"\b(" + "|".join(FULL_MONTHS) + r"|" + "|".join(MONTHS) + r")[-/ ](\d{4})\b", re.I)
_BARE_MONTH = re.compile(r"\b(" + "|".join(FULL_MONTHS) + r")\b", re.I)

LANE_SPEC = {
    Lane.JEA_NSA: dict(box="20ft", port="nsa", freight_col="freight_jea_nsa_usd_t", mcx_col="mcx_al_m1_inr_kg",
                       psic_key="psic_required_uae_origin", finance_key="finance_days_jea_nsa",
                       transit_key="transit_days_jea_nsa"),
    Lane.USEC_MUN: dict(box="40ft", port="mun", freight_col="freight_usec_mun_usd_t", mcx_col="mcx_al_m2_inr_kg",
                        psic_key="psic_required_safe_origin_designated_port", finance_key="finance_days_usec_mun",
                        transit_key="transit_days_usec_mun"),
}


def _err(code: str, where: str, message: str) -> Issue:
    return Issue("ERROR", code, where, message)


def _warn(code: str, where: str, message: str) -> Issue:
    return Issue("WARNING", code, where, message)


# ------------------------------------------------------------------------------------------------ market access
@lru_cache(maxsize=1)
def panel() -> pd.DataFrame:
    """The Phase 0 daily panel, indexed by date. Read once; never mutated."""
    df = pd.read_csv(PROCESSED_DIR / "market_daily.csv", parse_dates=["date"])
    return df.set_index("date")


@lru_cache(maxsize=1)
def panel_days() -> tuple[dt.date, ...]:
    return tuple(d.date() for d in panel().index)


def panel_row(day: dt.date) -> pd.Series:
    return panel().loc[pd.Timestamp(day)]


def roll_following(day: dt.date) -> dt.date:
    """First panel day on or after `day` (CONTRACTS §3: derived cashflow dates roll following)."""
    for d in panel_days():
        if d >= day:
            return d
    raise ValueError(f"{day} is beyond the panel")


def roll_bd(day: dt.date, n: int) -> dt.date:
    """`n` panel days after the first panel day on or after `day`."""
    days = panel_days()
    i = days.index(roll_following(day))
    return days[min(i + n, len(days) - 1)]


def panel_days_in_month(year: int, month: int) -> list[dt.date]:
    return [d for d in panel_days() if (d.year, d.month) == (year, month)]


def averaging_midpoint(start: dt.date, end: dt.date) -> dt.date:
    """The desk's averaging convention: an averaging leg is treated as open until the ceil(n/2)-th day of its
    window and closed after it. Deterministic, stated once, and used to date hedge lifts on formula legs."""
    days = [d for d in panel_days() if start <= d <= end]
    if not days:
        raise ValueError(f"no panel days in {start}..{end}")
    return days[math.ceil(len(days) / 2) - 1]


@lru_cache(maxsize=4096)
def market_reference(day: dt.date, grade: str, lane: str) -> dict:
    """CONTRACTS §5 line items for one calendar day, one grade, one lane.

    Phase 1 evaluates §5 on the last panel day of each week; a trade is decided on the day it is decided, so the
    book needs the same arithmetic on an arbitrary panel day. Every parameter is read at `day` and every market
    value comes from that day's panel row, so the result contains nothing published after it. Check P11 asserts
    this reproduces `desk.parity.model` on the days where both are defined.
    """
    row = panel_row(day)
    spec = LANE_SPEC[Lane(lane)]
    p = lambda key: config.value(key, day)

    lme_3m = float(row["lme_3m_usd_t"])
    lme_cash = float(row["lme_cash_usd_t"])
    usdinr = float(row["usdinr"])
    usdinr_goods = float(row[str(config.value("parity_goods_fx_basis"))])
    customs_fx = float(p("customs_usdinr_import"))
    factor = float(p(f"grade_factor_{grade}"))

    base_payload = float(p(f"container_payload_mt_{spec['box']}"))
    grade_payload = float(p(f"container_payload_mt_{spec['box']}_{grade}"))
    payload_20ft = float(p(f"container_payload_mt_20ft_{grade}"))
    payload_scale = base_payload / grade_payload

    freight_base = float(row[spec["freight_col"]])
    freight = freight_base * payload_scale
    cfr = lme_3m * factor
    insurance = float(p("insurance_rate")) * float(p("insured_value_uplift")) * cfr
    cif = cfr + insurance
    av = units.usd_t_to_inr_t(cif, customs_fx)
    goods = units.usd_t_to_inr_t(cif, usdinr_goods)
    bcd = av * float(p("bcd_scrap_hs7602"))
    sws = bcd * float(p("sws_rate_on_bcd"))
    igst = (av + bcd + sws) * float(p("igst_rate_hs7602"))
    psic = (units.usd_t_to_inr_t(float(p("psic_cost_usd_per_box")), usdinr) / payload_20ft
            if bool(p(spec["psic_key"])) else 0.0)
    port = float(p(f"port_cf_charges_inr_t_{spec['port']}")) * payload_scale + psic
    wc_rate = float(p("wc_rate_inr_pa"))
    finance = units.simple_interest(goods + bcd + sws, wc_rate, float(p(spec["finance_key"])))
    igst_finance = units.simple_interest(igst, wc_rate, float(p("igst_credit_lag_days")))
    landed = goods + bcd + sws + port + finance + igst_finance + (0.0 if bool(p("igst_itc_available")) else igst)

    recovery = ((1 - float(p(f"moisture_frac_{grade}"))) * (1 - float(p(f"contamination_frac_{grade}")))
                * float(p(f"metal_yield_frac_{grade}")))
    mcx_inr_kg = float(row[spec["mcx_col"]])
    anchor = units.inr_kg_to_inr_t(mcx_inr_kg) + float(p("domestic_anchor_premium_inr_t"))
    byproduct = ((1 - float(p(f"moisture_frac_{grade}"))) * float(p(f"heavies_frac_{grade}"))
                 * float(p("heavies_net_value_frac_of_lme_al")) * units.usd_t_to_inr_t(lme_3m, usdinr))
    conversion = float(p("conversion_cost_inr_t")) * recovery
    netback = anchor * recovery + byproduct - conversion

    return dict(
        date=day, grade=grade, lane=lane,
        lme_cash_usd_t=lme_cash, lme_3m_usd_t=lme_3m, usdinr=usdinr, usdinr_goods=usdinr_goods,
        customs_usdinr_import=customs_fx, grade_factor=factor,
        base_payload_mt=base_payload, grade_payload_mt=grade_payload, payload_scale=payload_scale,
        freight_base_usd_t=freight_base, freight_usd_t=freight,
        freight_usd_box=freight_base * base_payload,
        cfr_usd_t=cfr, fob_usd_t=cfr - freight, insurance_usd_t=insurance, cif_usd_t=cif,
        av_customs_inr_t=av, goods_inr_t=goods, bcd_inr_t=bcd, sws_inr_t=sws, igst_inr_t=igst, port_inr_t=port,
        finance_inr_t=finance, igst_finance_inr_t=igst_finance, landed_inr_t=landed,
        replacement_inr_t=goods + bcd + sws + port,
        recovery_frac=recovery, mcx_anchor_inr_kg=mcx_inr_kg, anchor_inr_t=anchor,
        byproduct_inr_t=byproduct, conversion_inr_t=conversion, netback_inr_t=netback,
        net_arb_inr_t=netback - landed, wc_rate_inr_pa=wc_rate,
    )


# ------------------------------------------------------------------------------------------------- MCX helpers
@lru_cache(maxsize=1)
def mcx_expiries() -> dict[str, dt.date]:
    out = {}
    for x in config.value("mcx_al_expiry_dates_2022"):
        d = dt.date.fromisoformat(str(x)[:10])
        out[d.strftime("%Y-%m")] = d
    return out


def mcx_roll_deadline(contract_month: str) -> dt.date:
    """`mcx_roll_days_before_expiry` panel days before the DIRECT expiry of that contract month (design D4b)."""
    n = int(config.value("mcx_roll_days_before_expiry"))
    expiry = mcx_expiries()[contract_month]
    prior = [d for d in panel_days() if d < expiry]
    return prior[-n]


def mcx_delta_inr_per_lot(day: dt.date, contract_month: str) -> float:
    """₹ that one MCX Aluminium lot moves per USD/t move in LME cash, under duty-paid parity (design D4).

    F = [cash x usdinr / 1000 x (1 + bcd_primary x (1 + sws)) + premium] x (1 + r_inr x dte/365) + basis, so
    dF/d(cash) x lot_kg = lot_mt x usdinr x uplift x carry.
    """
    row = panel_row(day)
    lot_mt = float(config.value("mcx_al_lot_mt"))
    uplift = 1 + float(config.value("bcd_primary_al_hs7601", day)) * (1 + float(config.value("sws_rate_on_bcd", day)))
    dte = max(0, (mcx_expiries()[contract_month] - day).days)
    carry = 1 + float(row["inr_rate_3m_pa"]) * dte / 365.0
    return lot_mt * float(row["usdinr"]) * uplift * carry


def cfr_delta_inr_per_usd_t(day: dt.date) -> float:
    """₹/t that a CFR-priced cargo's landed value (goods + duty) moves per 1.00 of grade factor per USD/t of
    LME 3M. This is the `k` in the hedge-sizing rule; §5 is linear in the LME price, so it is exact."""
    row = panel_row(day)
    ins = 1 + float(config.value("insurance_rate", day)) * float(config.value("insured_value_uplift", day))
    duty = float(config.value("bcd_scrap_hs7602", day)) * (1 + float(config.value("sws_rate_on_bcd", day)))
    goods_fx = float(row[str(config.value("parity_goods_fx_basis"))])
    return ins * (goods_fx + float(config.value("customs_usdinr_import", day)) * duty)


# ------------------------------------------------------------------------------------------------- lifecycle
@dataclass(frozen=True)
class LotSchedule:
    lot_id: str
    boxes: int
    weight_mt: float
    bl_date: dt.date
    arrival_cal: dt.date
    arrival: dt.date
    survey: dt.date
    boe: dt.date
    release_cal: dt.date
    release: dt.date
    igst_credit: dt.date
    lc_pay: dt.date
    usance_maturity: dt.date | None
    freight_pay: dt.date | None
    claim_settle: dt.date | None
    dwell_days: int
    chargeable_dwell_days: int
    arrival_delay_days: int


@dataclass(frozen=True)
class TicketSchedule:
    trade_id: str
    lots: tuple[LotSchedule, ...]
    qp_month: str | None
    pricing_start: dt.date | None
    pricing_end: dt.date | None
    final_invoice: dt.date | None
    sale_invoice: dict          # sale_id -> date
    sale_due: dict              # sale_id -> date
    sale_due_contractual: dict  # sale_id -> date before any delay event
    sale_advance: dict          # sale_id -> date | None
    last_cashflow: dt.date
    close_date: dt.date


def ticket_schedule(t: Ticket) -> TicketSchedule:
    """Every derived date a ticket implies (design §4.1). Calendar intervals first, then roll following."""
    spec = LANE_SPEC[t.lane]
    transit = int(config.value(spec["transit_key"], t.trade_date))
    clearance = int(config.value("clearance_delivery_days", t.trade_date))
    free_days = int(config.value("detention_free_days", t.trade_date))
    igst_lag = int(config.value("igst_credit_lag_days", t.trade_date))

    lots: list[LotSchedule] = []
    for lot in t.shipment.lots:
        delay = sum(e.arrival_delay_days for e in t.events.logistics if e.lot_id == lot.lot_id)
        dwell_extra = sum(e.extra_dwell_days for e in t.events.logistics if e.lot_id == lot.lot_id)
        arrival_cal = lot.bl_date + dt.timedelta(days=transit + delay)
        boe_cal = arrival_cal + dt.timedelta(days=BOE_LAG_DAYS)
        survey_cal = arrival_cal + dt.timedelta(days=SURVEY_LAG_DAYS)
        release_cal = arrival_cal + dt.timedelta(days=clearance + dwell_extra)
        dwell = clearance + dwell_extra
        has_claim = any(q.lot_id == lot.lot_id for q in t.events.quality)
        lots.append(LotSchedule(
            lot_id=lot.lot_id, boxes=lot.boxes, weight_mt=t.lot_weight_mt(lot), bl_date=lot.bl_date,
            arrival_cal=arrival_cal, arrival=roll_following(arrival_cal),
            survey=roll_following(survey_cal), boe=roll_following(boe_cal),
            release_cal=release_cal, release=roll_following(release_cal),
            igst_credit=roll_following(boe_cal + dt.timedelta(days=igst_lag)),
            lc_pay=roll_following(lot.bl_date + dt.timedelta(days=LC_SIGHT_PAYMENT_LAG_DAYS)),
            usance_maturity=(roll_following(lot.bl_date + dt.timedelta(days=t.purchase.payment.usance_days))
                             if t.purchase.payment.usance_days else None),
            freight_pay=(None if t.freight is None else
                         (lot.bl_date if t.freight.payment_terms.value == "PREPAID_AT_BL"
                          else roll_following(arrival_cal))),
            claim_settle=(roll_following(survey_cal + dt.timedelta(days=CLAIM_SETTLE_LAG_DAYS))
                          if has_claim else None),
            dwell_days=dwell, chargeable_dwell_days=max(0, dwell - free_days),
            arrival_delay_days=delay,
        ))

    qp_month = pricing_start = pricing_end = final_invoice = None
    if t.purchase.pricing.type is PurchasePricingType.LME_M1_AVG:
        bl_month = t.shipment.laycan_start.replace(day=1)
        nxt = (bl_month + dt.timedelta(days=32)).replace(day=1)
        month_days = panel_days_in_month(nxt.year, nxt.month)
        qp_month, pricing_start, pricing_end = nxt.strftime("%Y-%m"), month_days[0], month_days[-1]
        final_invoice = roll_bd(pricing_end, FINAL_INVOICE_LAG_BDAYS)

    by_lot = {l.lot_id: l for l in lots}
    invoice, due, due_contract, advance = {}, {}, {}, {}
    for s in t.sales:
        covered = [by_lot[lid] for lid in s.lot_ids]
        anchor = max(l.release_cal for l in covered)
        if s.pricing.type is SalePricingType.MCX_AVG and s.pricing.window_end is not None:
            anchor = max(anchor, s.pricing.window_end)
        inv = roll_following(anchor)
        delay = sum(e.delay_days for e in t.events.buyer_payment_delay if e.sale_id == s.sale_id)
        credit = s.payment.credit_days or 0
        invoice[s.sale_id] = inv
        due_contract[s.sale_id] = roll_following(inv + dt.timedelta(days=credit))
        due[s.sale_id] = roll_following(inv + dt.timedelta(days=credit + delay))
        advance[s.sale_id] = s.payment.advance_date

    flows: list[dt.date] = [t.purchase.payment.lc_open_date]
    for l in lots:
        flows += [l.lc_pay, l.boe, l.release, l.igst_credit]
        for d in (l.usance_maturity, l.freight_pay, l.claim_settle):
            if d is not None:
                flows.append(d)
    if final_invoice is not None:
        flows.append(final_invoice)
    flows += list(due.values()) + [d for d in advance.values() if d is not None]
    flows += [x.cancel_date or x.value_date for x in t.hedges.fx_forwards.lines]
    flows += [tr.exit_date for tr in t.hedges.mcx.tranches]

    return TicketSchedule(
        trade_id=t.trade_id, lots=tuple(lots), qp_month=qp_month, pricing_start=pricing_start,
        pricing_end=pricing_end, final_invoice=final_invoice, sale_invoice=invoice, sale_due=due,
        sale_due_contractual=due_contract, sale_advance=advance,
        last_cashflow=max(flows), close_date=max(flows),
    )


# ------------------------------------------------------------------------------------------ hedge-policy sizing
def hedge_exposure_inr_per_usd_t(t: Ticket, day: dt.date, sched: TicketSchedule) -> tuple[float, str]:
    """Net ₹ exposure per USD/t of LME cash on `day`, and the sentence that explains how it was built.

    The desk's sizing rule, stated once and applied mechanically:
      * an unsold cargo is marked at import replacement value, so it is long `grade_factor x k` per tonne;
      * a sale contracted on an MCX average and not yet through its window is long `factor x duty-paid parity`;
      * a sale contracted at a fixed rupee price is flat;
      * a purchase on an LME average and not yet through its quotational period is short `factor x k`;
      * a fixed-price purchase is flat.
    `k` = `cfr_delta_inr_per_usd_t`. Nothing here reads a price: it is a linear sensitivity of §5.
    """
    qty = t.quantity_mt
    k = cfr_delta_inr_per_usd_t(day)
    ref = market_reference(day, t.grade.value, t.lane.value)

    purchase_open = (t.purchase.pricing.type is PurchasePricingType.LME_M1_AVG
                     and sched.pricing_start is not None
                     and day < averaging_midpoint(sched.pricing_start, sched.pricing_end))
    short = (t.purchase.pricing.factor_frac or 0.0) * k if purchase_open else 0.0

    long_side, parts = 0.0, []
    for s in t.sales:
        covered_mt = sum(t.lot_weight_mt(t.lot(lid)) for lid in s.lot_ids)
        if s.contract_date > day:
            continue
        if s.pricing.type is SalePricingType.MCX_AVG:
            mid = averaging_midpoint(s.pricing.window_start, s.pricing.window_end)
            if day < mid:
                per_mt = mcx_delta_inr_per_lot(day, s.pricing.window_start.strftime("%Y-%m")) / float(
                    config.value("mcx_al_lot_mt"))
                long_side += covered_mt * s.pricing.factor_frac * per_mt
                parts.append(f"{s.sale_id} MCX-average leg {covered_mt:,.0f} MT x {s.pricing.factor_frac}")
        qty -= covered_mt
    if qty > 1e-9:
        long_side += qty * ref["grade_factor"] * k
        parts.append(f"unsold {qty:,.0f} MT at replacement value x grade factor {ref['grade_factor']:.6f}")
    if short:
        parts.append(f"purchase leg floating x factor {t.purchase.pricing.factor_frac}")
    net = long_side - short * t.quantity_mt
    basis = ("; ".join(parts) or "no open LME-equivalent delta") + \
            f"; k = {k:.4f} ₹/t per USD/t, one lot = {mcx_delta_inr_per_lot(day, '2022-08'):.2f} ₹ per USD/t"
    return net, basis


def open_lots(t: Ticket, day: dt.date) -> int:
    """Signed MCX lots open on `day` (+ = short futures). A tranche is open from its entry date up to, but not
    including, its exit date, so a roll neither doubles nor gaps the position."""
    total = 0
    for tr in t.hedges.mcx.tranches:
        if tr.entry_date <= day < tr.exit_date:
            total += tr.lots if tr.direction is HedgeDirection.SELL else -tr.lots
    return total


def policy_lots(t: Ticket, day: dt.date, sched: TicketSchedule, ratio: float,
                contract_month: str | None = None) -> tuple[int, str, float, str]:
    """(lots, direction, net ₹-delta, sizing sentence) the desk's rule gives on `day` at `ratio`."""
    net, basis = hedge_exposure_inr_per_usd_t(t, day, sched)
    per_lot = mcx_delta_inr_per_lot(day, contract_month or _month_for(day))
    lots = round(ratio * net / per_lot) if per_lot else 0
    return abs(lots), ("SELL" if lots > 0 else "BUY"), net, basis


def _month_for(day: dt.date) -> str:
    """The near contract month on `day`: the first listed month whose DIRECT expiry is on or after it."""
    for m, e in sorted(mcx_expiries().items()):
        if e >= day:
            return m
    raise ValueError(f"no listed MCX contract month on or after {day}")


# ----------------------------------------------------------------------------------------------- hindsight scan
def rationale_hindsight_hits(text: str, asof: dt.date, allowed_months: Iterable[str],
                             allowed_dates: Iterable[dt.date] = ()) -> list[str]:
    """Dated references in a piece of desk prose that post-date the decision it justifies.

    The rule the book is held to: a rationale or a terms note may cite a *market fact* only with a date on or
    before the date of the decision. Two kinds of forward reference are legitimate and are allowed explicitly,
    never by loosening the scan:

      * a date the ticket itself declares as a term — a laycan, a quotational period, an averaging window, a
        book-by date, a forward value date. These are things the desk is promising, not things it has seen.
      * a bare month name (no year) that names one of those declared periods.

    Everything else dated after `asof` is a hit. Scans are run most-specific first and each match is removed
    from the text before the next pattern runs, so `29-Apr-2022` is not also counted as `Apr-2022`.
    """
    hits: list[str] = []
    months_ok = {m.lower() for m in allowed_months}
    dates_ok = set(allowed_dates)
    rest = text

    def _sweep(pattern: re.Pattern, resolve) -> None:
        nonlocal rest
        found = list(pattern.finditer(rest))
        for m in found:
            day = resolve(m)
            if day is None or day <= asof or day in dates_ok:
                continue
            hits.append(m.group(0))
        rest = pattern.sub(" ", rest)

    _sweep(_ISO_DATE, lambda m: dt.date(int(m[1]), int(m[2]), int(m[3])))
    _sweep(_DMY, lambda m: dt.date(int(m[3]), MONTHS[m[2].lower()[:3]], int(m[1])))
    # "18-Mar" with no year: desk prose always means the year it is written in.
    _sweep(_DM, lambda m: dt.date(asof.year, MONTHS[m[2].lower()[:3]], int(m[1])))

    def _month_year(m):
        name = m[1].lower()
        month = FULL_MONTHS.get(name) or MONTHS.get(name[:3])
        first = dt.date(int(m[2]), month, 1)
        return None if name in months_ok else first

    _sweep(_MY, _month_year)
    for m in _BARE_MONTH.finditer(rest):
        name = m.group(0).lower()
        if dt.date(asof.year, FULL_MONTHS[name], 1) <= asof or name in months_ok:
            continue
        hits.append(m.group(0))
    return hits


# Numbers a desk note may quote, and how each one is reconciled to the panel (P13). Only these shapes are
# checked: the scan is honest about what it cannot parse rather than pretending to understand prose.
_CLAIM_USD_IN_A_DAY = re.compile(r"([\d,]+(?:\.\d+)?)\s*dollars(?:[^.;]{0,40}?)\bin a day\b", re.I)
_CLAIM_USD_OFF_LOW = re.compile(
    r"([\d,]+(?:\.\d+)?)\s*dollars\b[^.;]{0,30}?\b(?:off|since)\s+the\s+(\d{1,2})[-/ ]("
    + "|".join(MONTHS) + r")[a-z]*\s+(low|high)", re.I)
_CLAIM_USD_UNDER = re.compile(
    r"([\d,]+(?:\.\d+)?)\s*(?:dollars|USD/t)\s+under\s+(?:my own |my |the )?(netback|parity)", re.I)
_CLAIM_RUPEE_AT = re.compile(r"rupee[^.;]{0,25}?\bat\s+(\d{2}\.\d{2})\b", re.I)
_CLAIM_PCT_TODAY = re.compile(r"moved\s+(\d{1,2}(?:\.\d+)?)\s*%\s*(?:today|on the trade date)", re.I)
# "fallen five weeks running", "weakened three sessions running": a streak claim, reconciled to the panel (the
# review found two such claims that the tape does not support, T01 and T06, and the first P13 could not see them).
_NUMBER_WORDS = {w: i for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"])}
_CLAIM_STREAK = re.compile(
    r"\b(fallen|fell|dropped|risen|rose|climbed|weakened|strengthened|gained|lost)\s+(?:for\s+)?"
    r"(\d{1,2}|" + "|".join(_NUMBER_WORDS) + r")\s+(weeks?|sessions?|days?)\s+(?:running|in a row|straight)",
    re.I)
_DOWN_WORDS = {"fallen", "fell", "dropped", "lost", "weakened"}
# A note may not claim its own inputs were knowable on the day: two of them never are (CONTRACTS §4.3,
# scrap_grades.yaml). Deleting the claim is the fix; the numbers stay.
_CLAIM_POINT_IN_TIME = re.compile(
    r"every input is dated|all inputs are dated|every input here is dated|no input here is a reconstruction", re.I)
RECONSTRUCTED_INPUTS = ("the grade factor (a lag-2 unit-value reconstruction, scrap_grades.yaml)",
                        "the lane freight level (level inputs published months later, CONTRACTS §4.3)")


def _last_panel_day(d: dt.date) -> dt.date:
    """The last panel day on or before `d` (a parity week_end is a Friday, which need not be a trading day)."""
    days = [x for x in panel_days() if x <= d]
    if not days:
        raise ValueError(f"no panel day on or before {d}")
    return days[-1]


def _panel_prev(d: dt.date) -> dt.date | None:
    days = panel_days()
    i = days.index(d)
    return None if i == 0 else days[i - 1]


def _lme(day: dt.date) -> dict[str, float]:
    row = panel_row(day)
    return {"LME cash": float(row["lme_cash_usd_t"]), "LME 3M": float(row["lme_3m_usd_t"])}


def numeric_claim_hits(t: Ticket, text: str, asof: dt.date) -> list[str]:
    """Market numbers quoted in desk prose that do not reconcile to the panel (P13).

    What it checks — and the list is the honest limit of the control:
      * "N dollars ... in a day"          -> the one-session move in LME cash or 3M on `asof`;
      * "N dollars off/since the D-Mon low/high" -> the move from that day to `asof`, or to the last panel day of
        the parity week the ticket cites (a trader may measure to either, and the ticket declares both);
      * "N dollars / N USD/t under netback|parity" -> the ticket's own P10 discount at the trade date;
      * "rupee ... at XX.XX"              -> `usdinr` on `asof`;
      * "moved N % today|on the trade date" -> the one-session move in the MCX proxy or LME on `asof`.
    Anything else — "106 dollars a tonne", "a thousand dollars", "12 % in a session" as a general statement — is
    NOT checked, and P13 says so rather than implying the whole prose is reconciled.
    """
    hits: list[str] = []
    refs = {"trade date": asof}
    try:
        refs["parity week"] = _last_panel_day(t.rationale.parity_week_end)
    except ValueError:                                          # pragma: no cover - a week before the panel
        pass

    def _fail(claim: str, want: float, candidates: dict[str, float], tol: float, unit: str) -> None:
        if any(abs(want - v) <= tol for v in candidates.values()):
            return
        near = ", ".join(f"{k} {v:,.2f}" for k, v in sorted(candidates.items()))
        hits.append(f"{claim!r} (panel gives {near} {unit})")

    for m in _CLAIM_USD_IN_A_DAY.finditer(text):
        want = float(m[1].replace(",", ""))
        prev = _panel_prev(asof)
        if prev is None:
            continue
        cands = {f"{k} 1-day": abs(v - _lme(prev)[k]) for k, v in _lme(asof).items()}
        _fail(m.group(0), want, cands, CLAIM_TOL_USD_T, "USD/t")

    for m in _CLAIM_USD_OFF_LOW.finditer(text):
        want = float(m[1].replace(",", ""))
        cited = dt.date(asof.year, MONTHS[m[3].lower()[:3]], int(m[2]))
        if cited > asof or cited not in set(panel_days()):
            continue                                            # P08 owns forward dates; a non-panel day is not ours
        cands = {}
        for label, ref in refs.items():
            for k, v in _lme(ref).items():
                cands[f"{k} to {label}"] = abs(v - _lme(cited)[k])
        _fail(m.group(0), want, cands, CLAIM_TOL_USD_T, "USD/t")

    if t.purchase.pricing.type is PurchasePricingType.FIXED and t.purchase.pricing.price_usd_t is not None:
        ref = market_reference(t.trade_date, t.grade.value, t.lane.value)
        parity_px = ref["fob_usd_t"] if t.purchase.incoterm is Incoterm.FOB else ref["cfr_usd_t"]
        for m in _CLAIM_USD_UNDER.finditer(text):
            want = float(m[1].replace(",", ""))
            _fail(m.group(0), want, {f"{t.purchase.incoterm.value} parity less the contract price":
                                     parity_px - t.purchase.pricing.price_usd_t}, CLAIM_TOL_USD_T, "USD/t")

    for m in _CLAIM_RUPEE_AT.finditer(text):
        want = float(m[1])
        cands = {f"usdinr on the {label}": float(panel_row(ref)["usdinr"]) for label, ref in refs.items()}
        _fail(m.group(0), want, cands, CLAIM_TOL_USDINR, "₹/USD")

    for m in _CLAIM_STREAK.finditer(text):
        want = int(m[2]) if m[2].isdigit() else _NUMBER_WORDS[m[2].lower()]
        down = m[1].lower() in _DOWN_WORDS
        before = text[max(0, m.start() - 80):m.start()].lower()
        streak, what = _streak(t, before, asof, down, weekly=m[3].lower().startswith("week"))
        if streak is not None and streak < want:
            hits.append(f"{m.group(0)!r} (panel gives a {streak}-{m[3].lower().rstrip('s')} streak in {what} "
                        f"to {asof})")

    prev = _panel_prev(asof)
    if prev is not None:
        moves = {"MCX M1": "mcx_al_m1_inr_kg", "MCX M2": "mcx_al_m2_inr_kg",
                 "LME cash": "lme_cash_usd_t", "LME 3M": "lme_3m_usd_t"}
        cands = {k: abs(float(panel_row(asof)[c]) / float(panel_row(prev)[c]) - 1.0) * 100.0
                 for k, c in moves.items()}
        for m in _CLAIM_PCT_TODAY.finditer(text):
            _fail(m.group(0), float(m[1]), cands, CLAIM_TOL_PCT_POINTS, "%")
    return hits


def _streak(t: Ticket, before: str, asof: dt.date, down: bool, *, weekly: bool) -> tuple[int | None, str]:
    """Consecutive moves in one direction ending on `asof`, for the series the sentence names (None: not ours).

    The subject is read from the words just before the claim: the rupee (usdinr — a *weakening* rupee is a RISING
    usdinr), a freight index (the ticket's own lane, weekly), or the LME (cash, daily). Anything else is skipped:
    P13 checks the claims it can parse and says so.
    """
    if "rupee" in before:
        s = panel()["usdinr"]
        down = not down                                     # rupee weakens <=> usdinr rises
        what = "usdinr (rupee)"
    elif "index" in before or "freight" in before:
        f = pd.read_csv(PROCESSED_DIR / "freight_weekly.csv", parse_dates=["week_end"]).set_index("week_end")
        col = LANE_SPEC[t.lane]["freight_col"]
        s = f[col]
        what = f"{col} (weekly)"
        weekly = True
    elif "lme" in before or "aluminium" in before or "metal" in before:
        s = panel()["lme_cash_usd_t"]
        what = "LME cash"
    else:
        return None, ""
    s = s[s.index <= pd.Timestamp(asof)].dropna()
    if weekly and what.startswith("usdinr"):
        s = s.resample("W-FRI").last().dropna()
    diffs = s.diff().dropna().to_numpy()[::-1]
    n = 0
    for x in diffs:
        if (x < 0) if down else (x > 0):
            n += 1
        else:
            break
    return n, what


def provenance_claim_hits(text: str) -> list[str]:
    """A categorical point-in-time claim about inputs that are reconstructions (P13). Never true in this book."""
    return [m.group(0) for m in _CLAIM_POINT_IN_TIME.finditer(text)]


def demurrage_usd(boxes: int, chargeable_days: int, day: dt.date) -> float:
    """Detention/ground rent on `boxes` for `chargeable_days` beyond the free days, up the registered slabs.

    Carriers escalate: `demurrage_usd_per_box_day` is the FIRST-slab rate and its own register note says so, so
    charging eight days at it (the July-2022 congestion case) understates the bill. The engine must use this
    same schedule or the two phases publish different demurrage (docs/20_trade_book.md §12).
    """
    if chargeable_days <= 0 or boxes <= 0:
        return 0.0
    n1 = int(config.value("demurrage_slab1_days", day))
    n2 = int(config.value("demurrage_slab2_days", day))
    r1 = float(config.value("demurrage_usd_per_box_day", day))
    r2 = float(config.value("demurrage_usd_per_box_day_slab2", day))
    r3 = float(config.value("demurrage_usd_per_box_day_slab3", day))
    d1 = min(chargeable_days, n1)
    d2 = min(max(chargeable_days - n1, 0), n2)
    d3 = max(chargeable_days - n1 - n2, 0)
    return boxes * (d1 * r1 + d2 * r2 + d3 * r3)


def sale_terms_delta_inr_t(s: Sale, mid_inr_t: float, day: dt.date) -> float:
    """The payment-terms adjustment to the half-the-gap sale price, in ₹/MT (desk rule S1).

    Symmetric by construction, which the first draft of this book was not: it charged a flat ₹500/MT per
    fortnight of extra credit but paid only ₹500/MT for a *full* advance, so both errors ran the desk's way on
    every advance ticket. Both sides are now the same number — the desk's own registered working-capital rate on
    the days the money actually moves — so an advance is worth what it costs the desk to fund, and extra credit
    costs the buyer what it costs the desk to give.
    """
    wc = float(config.value("wc_rate_inr_pa", day))
    adv = s.payment.advance_frac or 0.0
    credit = s.payment.credit_days or 0
    days = (credit - SALE_CREDIT_BASELINE_DAYS) * (1.0 - adv) - SALE_CREDIT_BASELINE_DAYS * adv
    return mid_inr_t * wc * days / units.DAY_COUNT_INR


def declared_future_months(t: Ticket, sched: TicketSchedule) -> set[str]:
    """Month names the ticket declares as contract periods, so a note may use them forward."""
    out: set[str] = set()
    if sched.pricing_start is not None:
        out.add(sched.pricing_start.strftime("%B").lower())
    for s in t.sales:
        if s.pricing.window_start is not None:
            for d in (s.pricing.window_start, s.pricing.window_end):
                out.add(d.strftime("%B").lower())
    for tr in t.hedges.mcx.tranches:
        out.add(dt.date.fromisoformat(tr.contract_month + "-01").strftime("%B").lower())
    for x in t.hedges.fx_forwards.lines:
        out.add(x.value_date.strftime("%B").lower())
    for lot in t.shipment.lots:
        out.add(lot.bl_date.strftime("%B").lower())
    return out


def declared_dates(t: Ticket, sched: TicketSchedule) -> set[dt.date]:
    """Dates the ticket declares as terms; a note may cite these forward because they are promises, not prices."""
    out: set[dt.date] = {t.shipment.laycan_start, t.shipment.laycan_end, t.purchase.payment.lc_open_date}
    out |= {lot.bl_date for lot in t.shipment.lots}
    if t.freight is not None:
        if t.freight.fixture_date is not None:
            out.add(t.freight.fixture_date)
        if t.freight.stop_loss is not None:
            out.add(t.freight.stop_loss.latest_fixture_date)
    for s in t.sales:
        out.add(s.contract_date)
        for d in (s.payment.advance_date, s.pricing.window_start, s.pricing.window_end):
            if d is not None:
                out.add(d)
        out.add(sched.sale_invoice[s.sale_id])
        out.add(sched.sale_due_contractual[s.sale_id])
    for d in (sched.pricing_start, sched.pricing_end, sched.final_invoice):
        if d is not None:
            out.add(d)
    for tr in t.hedges.mcx.tranches:
        out |= {tr.entry_date, tr.exit_date, mcx_expiries()[tr.contract_month]}
        # the panel's rule-based monthly slot for that contract, which a note may name beside the DIRECT expiry
        y, mo = (int(x) for x in tr.contract_month.split("-"))
        out.add((dt.date(y + (mo == 12), (mo % 12) + 1, 1) - dt.timedelta(days=1)))
    for x in t.hedges.fx_forwards.lines:
        out |= {x.booking_date, x.value_date}
        if x.cancel_date is not None:
            out.add(x.cancel_date)
    for l in sched.lots:
        out |= {l.arrival, l.release, l.boe, l.igst_credit, l.lc_pay}
        if l.usance_maturity is not None:
            out.add(l.usance_maturity)
    return out


# ------------------------------------------------------------------------------------------------- the checks
def eligibility_frame(book: Book) -> pd.DataFrame:
    """One row per trade: the §5a screens and the parity numbers the decision was actually taken against."""
    from desk.parity import model

    parity = model.load_parity()
    rows = []
    for t in book.trades:
        eligible, week_end, row = model.eligible_on(t.trade_date, t.grade.value, t.lane.value, parity)
        ref = market_reference(t.trade_date, t.grade.value, t.lane.value)
        rows.append({
            "trade_id": t.trade_id,
            "trade_date": t.trade_date.isoformat(),
            "grade": t.grade.value,
            "lane": t.lane.value,
            "parity_week_end_used": None if week_end is None else week_end.date().isoformat(),
            "parity_week_end_ticket": t.rationale.parity_week_end.isoformat(),
            "parity_value_date": None if row is None else pd.Timestamp(row["value_date"]).date().isoformat(),
            "trade_eligible": bool(eligible),
            "open_base": None if row is None else bool(row["open_base"]),
            "open_pit_mix": None if row is None else bool(row["open_pit_mix"]),
            "open_conv18k": None if row is None else bool(row["open_conv18k"]),
            "net_arb_inr_t": None if row is None else round(float(row["net_arb_inr_t"]), 2),
            "net_arb_pit_mix_inr_t": None if row is None else round(float(row["net_arb_pit_mix_inr_t"]), 2),
            "net_arb_conv18k_inr_t": None if row is None else round(float(row["net_arb_conv18k_inr_t"]), 2),
            "margin_threshold_inr_t": None if row is None else round(float(row["margin_threshold_inr_t"]), 2),
            "parity_lme_3m_usd_t": None if row is None else round(float(row["lme_3m_usd_t"]), 2),
            "parity_grade_factor": None if row is None else round(float(row["grade_factor"]), 6),
            "parity_freight_base_usd_t": None if row is None else round(float(row["freight_base_usd_t"]), 2),
            "parity_mcx_anchor_inr_kg": None if row is None else round(float(row["mcx_anchor_inr_kg"]), 4),
            "trade_date_lme_3m_usd_t": round(ref["lme_3m_usd_t"], 2),
            "trade_date_grade_factor": round(ref["grade_factor"], 6),
            "trade_date_replacement_inr_t": round(ref["replacement_inr_t"], 2),
            "trade_date_netback_inr_t": round(ref["netback_inr_t"], 2),
            "trade_date_net_arb_inr_t": round(ref["net_arb_inr_t"], 2),
            "week_matches_ticket": (week_end is not None
                                    and week_end.date() == t.rationale.parity_week_end),
            "status": "PASS" if eligible else "FAIL",
        })
    return pd.DataFrame(rows).sort_values("trade_id").reset_index(drop=True)


def credit_exposure_frame(book: Book) -> pd.DataFrame:
    """Buyer credit exposure at every sale booking, in booking order.

    Exposure is the desk's CREDIT exposure to that buyer: the part of every sale already contracted and not yet
    collected that the buyer has not paid in advance. A sale settles on its contractual due date (the delay
    events are outcomes, not terms, so they may not be used to justify a limit at booking).
    """
    scheds = {t.trade_id: ticket_schedule(t) for t in book.trades}
    events = []
    for t in book.trades:
        s_ = scheds[t.trade_id]
        for s in t.sales:
            qty = sum(t.lot_weight_mt(t.lot(lid)) for lid in s.lot_ids)
            price = (s.pricing.price_inr_t if s.pricing.type is SalePricingType.FIXED
                     else _mcx_sale_price_at(s, s.contract_date, t))
            value = qty * price
            credit_value = value * (1.0 - (s.payment.advance_frac or 0.0))
            events.append(dict(trade_id=t.trade_id, sale_id=s.sale_id, buyer_id=s.buyer_id,
                               contract_date=s.contract_date, due_date=s_.sale_due_contractual[s.sale_id],
                               qty_mt=qty, price_inr_t=price, invoice_value_inr=value,
                               credit_value_inr=credit_value))
    rows = []
    for e in sorted(events, key=lambda x: (x["contract_date"], x["trade_id"], x["sale_id"])):
        buyer = book.counterparty(e["buyer_id"])
        prior = sum(o["credit_value_inr"] for o in events
                    if o["buyer_id"] == e["buyer_id"]
                    and o["contract_date"] <= e["contract_date"] < o["due_date"]
                    and (o["contract_date"], o["trade_id"], o["sale_id"])
                    < (e["contract_date"], e["trade_id"], e["sale_id"]))
        after = prior + e["credit_value_inr"]
        limit = float(buyer.credit_limit_inr or 0.0)
        rows.append({**{k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in e.items()},
                     "buyer_name": buyer.name,
                     "exposure_before_inr": round(prior, 2),
                     "exposure_after_inr": round(after, 2),
                     "credit_limit_inr": limit,
                     "utilisation_frac": round(after / limit, 6) if limit else None,
                     "within_limit": bool(after <= limit + 1e-6)})
    return pd.DataFrame(rows)


def _mcx_sale_price_at(s: Sale, day: dt.date, t: Ticket) -> float:
    """The rupee price an MCX-average sale implies at `day`'s near-month anchor for the ticket's lane."""
    ref = market_reference(day, t.grade.value, t.lane.value)
    return s.pricing.factor_frac * units.inr_kg_to_inr_t(ref["mcx_anchor_inr_kg"]) + s.pricing.premium_inr_t


def _freight_index_usd_box(day: dt.date, lane: Lane) -> float:
    spec = LANE_SPEC[lane]
    base_payload = float(config.value(f"container_payload_mt_{spec['box']}", day))
    return float(panel_row(day)[spec["freight_col"]]) * base_payload


def validate(book: Book, *, strict_schema: bool = True) -> list[Issue]:
    """Every panel- and parity-dependent rule (P01–P12), on top of the schema rules (V01–V20)."""
    days = set(panel_days())
    issues: list[Issue] = list(validate_schema(book, panel_days=days)) if strict_schema else []
    elig = eligibility_frame(book).set_index("trade_id")
    credit = credit_exposure_frame(book)

    for t in book.trades:
        w = f"trades({t.trade_id})"
        sched = ticket_schedule(t)
        row = elig.loc[t.trade_id]

        # --- P01 trade discipline (CONTRACTS §5a)
        if not row["trade_eligible"]:
            issues.append(_err("P01", f"{w}.trade_date",
                               f"{t.trade_date} {t.grade}/{t.lane} is not trade_eligible in parity week "
                               f"{row['parity_week_end_used']}: base={row['open_base']}, "
                               f"pit={row['open_pit_mix']}, conv18k={row['open_conv18k']}"))
        if not row["week_matches_ticket"]:
            issues.append(_err("P01", f"{w}.rationale.parity_week_end",
                               f"ticket says {t.rationale.parity_week_end}; the §5a look-up on {t.trade_date} "
                               f"uses {row['parity_week_end_used']}"))

        # --- P02 container arithmetic
        payload = t.payload_mt_per_box
        total = 0.0
        for lot in t.shipment.lots:
            total += lot.boxes * payload
        if abs(total - t.quantity_mt) > 1e-6:
            issues.append(_err("P02", f"{w}.quantity_mt",
                               f"{t.quantity_mt:,.1f} MT != {t.boxes} boxes x "
                               f"container_payload_mt_{t.box}_{t.grade.value} {payload} = {total:,.1f} MT"))

        # --- P03 horizon
        if sched.last_cashflow > HORIZON_END:
            issues.append(_err("P03", w, f"last derived cashflow {sched.last_cashflow} is after HORIZON_END "
                                         f"{HORIZON_END}"))

        # --- P05 freight layer
        if t.freight is not None:
            f, fw = t.freight, f"{w}.freight"
            first_bl = min(l.bl_date for l in t.shipment.lots)
            if f.fixture_date is not None and f.rate_usd_box is not None:
                index = _freight_index_usd_box(f.fixture_date, t.lane)
                spread = f.rate_usd_box / index - 1.0
                lo, hi = FIXTURE_SPREAD_BAND
                if not (lo - 1e-9 <= spread <= hi + 1e-9):
                    issues.append(_err("P05", f"{fw}.rate_usd_box",
                                       f"{f.rate_usd_box:,.2f} USD/FEU is {spread:+.2%} against the "
                                       f"{f.fixture_date} lane index {index:,.2f}; the desk's NVOCC all-in "
                                       f"spread band is {lo:.0%}..{hi:.0%}"))
            if f.stop_loss is not None:
                trade_index = _freight_index_usd_box(t.trade_date, t.lane)
                want = trade_index * (1 + FREIGHT_STOP_LOSS_FRAC)
                if abs(f.stop_loss.stop_loss_usd_box - want) > 0.01 * want:
                    issues.append(_err("P05", f"{fw}.stop_loss.stop_loss_usd_box",
                                       f"{f.stop_loss.stop_loss_usd_box:,.0f} is not the policy stop "
                                       f"{want:,.0f} (= {t.trade_date} index {trade_index:,.2f} x "
                                       f"1 + {FREIGHT_STOP_LOSS_FRAC:.0%}) within 1 %"))
                # Re-derive the stop point-in-time: if the index reached the stop before the fixture, the desk
                # was obliged to fix that day.
                window = [d for d in panel_days() if t.trade_date <= d <= f.stop_loss.latest_fixture_date]
                triggered = [d for d in window
                             if _freight_index_usd_box(d, t.lane) >= f.stop_loss.stop_loss_usd_box]
                if triggered and (f.fixture_date is None or f.fixture_date > triggered[0]):
                    issues.append(_err("P05", f"{fw}.fixture_date",
                                       f"the lane index reached the stop on {triggered[0]}; the fixture must "
                                       f"be on or before that day, not {f.fixture_date}"))
                latest_ok = first_bl - dt.timedelta(days=FREIGHT_BOOKING_DAYS_BEFORE_BL)
                if f.stop_loss.latest_fixture_date > roll_following(latest_ok):
                    issues.append(_warn("P05", f"{fw}.stop_loss.latest_fixture_date",
                                        f"{f.stop_loss.latest_fixture_date} leaves less than "
                                        f"{FREIGHT_BOOKING_DAYS_BEFORE_BL} days before the first B/L "
                                        f"{first_bl} for the NVOCC to confirm space"))

        # --- P06 / P07 / P12 MCX stack
        by_id = {tr.hedge_id: tr for tr in t.hedges.mcx.tranches}
        roll_targets = {tr.roll_to for tr in t.hedges.mcx.tranches if tr.roll_to}
        for tr in t.hedges.mcx.tranches:
            tw = f"{w}.hedges.mcx({tr.hedge_id})"
            expiry = mcx_expiries()[tr.contract_month]
            deadline = mcx_roll_deadline(tr.contract_month)
            if tr.exit_date > deadline:
                issues.append(_err("P06", f"{tw}.exit_date",
                                   f"{tr.exit_date} is after the {tr.contract_month} roll deadline {deadline} "
                                   f"(mcx_roll_days_before_expiry before the DIRECT expiry {expiry}): the "
                                   f"position would run into the delivery tender period"))
            if tr.exit_reason is HedgeExitReason.ROLL and tr.exit_date != deadline:
                issues.append(_err("P06", f"{tw}.exit_date",
                                   f"a ROLL is taken on the deadline: {tr.contract_month} rolls on {deadline}, "
                                   f"not {tr.exit_date}"))
            if tr.entry_date > expiry:
                issues.append(_err("P06", f"{tw}.entry_date",
                                   f"{tr.entry_date} is after the {tr.contract_month} expiry {expiry}"))
            for label, day in (("entry", tr.entry_date), ("exit", tr.exit_date)):
                dpl = _dpl_move(day)
                limit = float(config.value("mcx_al_dpl_max_frac", day))
                if dpl is not None and abs(dpl) > limit:
                    issues.append(_warn("P12", f"{tw}.{label}_date",
                                        f"the MCX proxy moved {dpl:+.1%} on {day}, beyond the "
                                        f"mcx_al_dpl_max_frac {limit:.0%} slab: a real contract would have been "
                                        f"limit-locked and this fill could not have been achieved"))
            if tr.hedge_id in roll_targets:
                continue                                    # a roll keeps the size of the line it continues
            target = t.hedges.mcx.hedge_ratio_target
            if target is None:
                continue
            net, _ = hedge_exposure_inr_per_usd_t(t, tr.entry_date, sched)
            # The whole open position on the entry day, not just this tranche: a line the desk means to lift in
            # pieces is booked as several tranches on one day, and a top-up sits on top of what is already on.
            per_lot = mcx_delta_inr_per_lot(tr.entry_date, tr.contract_month)
            position = open_lots(t, tr.entry_date)
            if abs(net) < 1e-9:
                issues.append(_err("P07", f"{tw}.lots",
                                   f"the desk's sizing rule gives no open LME-equivalent delta on "
                                   f"{tr.entry_date}, but {tr.lots} lots are booked"))
                continue
            implied = position * per_lot / net
            if abs(implied - target) > HEDGE_RATIO_TOL:
                issues.append(_err("P07", f"{tw}.lots",
                                   f"{tr.direction} {tr.lots} lots on {tr.entry_date} leaves {position:+d} lots "
                                   f"open, a hedge ratio of {implied:.3f} against the ticket's stated target "
                                   f"{target:.2f}; the desk sizes on round(ratio x net ₹-delta / ₹-delta of one "
                                   f"lot) = {round(target * net / per_lot):+d} lots"))

        # --- P08 hindsight guard
        months_ok, dates_ok = declared_future_months(t, sched), declared_dates(t, sched)
        prose = [(f"{w}.rationale.text", t.rationale.text, t.trade_date),
                 (f"{w}.purchase.pricing.terms_basis_note", t.purchase.pricing.terms_basis_note, t.trade_date)]
        prose += [(f"{w}.sales({s.sale_id}).pricing.terms_basis_note", s.pricing.terms_basis_note,
                   s.contract_date) for s in t.sales]
        prose.append((f"{w}.hedges.mcx.basis_risk_note", t.hedges.mcx.basis_risk_note, t.trade_date))
        if t.hedges.mcx.unhedged_reason:
            prose.append((f"{w}.hedges.mcx.unhedged_reason", t.hedges.mcx.unhedged_reason, t.trade_date))
        if t.freight is not None and t.freight.stop_loss is not None:
            prose.append((f"{w}.freight.stop_loss.note", t.freight.stop_loss.note,
                          t.freight.stop_loss.latest_fixture_date))
        for label, text, asof in prose:
            hits = rationale_hindsight_hits(text, asof, months_ok, dates_ok)
            if hits:
                issues.append(_err("P08", label,
                                   f"cites {sorted(set(hits))}, which post-date the decision on {asof}: a "
                                   f"decision may use only information published on or before it "
                                   f"(CONTRACTS §1.2)"))
            # --- P13 the numbers in the prose, and the provenance it claims for them
            bad = numeric_claim_hits(t, text, asof)
            if bad:
                issues.append(_err("P13", label,
                                   "quotes market numbers that do not reconcile to the panel: "
                                   + "; ".join(bad)))
            claims = provenance_claim_hits(text)
            if claims:
                issues.append(_err("P13", label,
                                   f"claims {sorted(set(claims))}, which cannot be true of this ticket: its "
                                   f"price basis rests on " + " and ".join(RECONSTRUCTED_INPUTS)
                                   + ". State the dates of the inputs that ARE point-in-time and name the ones "
                                     "that are not; do not make the categorical claim."))

        # --- P09 sale prices inside [replacement, netback]
        for s in t.sales:
            ref = market_reference(s.contract_date, t.grade.value, t.lane.value)
            price = (s.pricing.price_inr_t if s.pricing.type is SalePricingType.FIXED
                     else _mcx_sale_price_at(s, s.contract_date, t))
            lo, hi = ref["replacement_inr_t"], ref["netback_inr_t"]
            sw = f"{w}.sales({s.sale_id}).pricing"
            if not (lo <= price <= hi):
                issues.append(_err("P09", sw,
                                   f"{price:,.0f} ₹/MT on {s.contract_date} is outside the defensible range "
                                   f"[replacement {lo:,.0f}, netback {hi:,.0f}]"))
            mid = lo + DESK_ARB_SHARE_FRAC * (hi - lo)
            delta = sale_terms_delta_inr_t(s, mid, s.contract_date)
            want = mid + delta
            if abs(price - want) > SALE_PRICE_BAND_INR_T:
                issues.append(_warn("P09", sw,
                                    f"{price:,.0f} ₹/MT is {price - want:+,.0f} from the desk's rule "
                                    f"({DESK_ARB_SHARE_FRAC:.0%} of the gap = {mid:,.0f}, payment terms "
                                    f"{delta:+,.0f} at wc_rate_inr_pa, = {want:,.0f}); a quoted price may only "
                                    f"differ by the ±{SALE_PRICE_BAND_INR_T:,.0f} rounding tolerance"))

        # --- P10 purchase price against trade-date parity
        ref = market_reference(t.trade_date, t.grade.value, t.lane.value)
        pw = f"{w}.purchase.pricing"
        if t.purchase.pricing.type is PurchasePricingType.FIXED:
            parity_px = ref["fob_usd_t"] if t.purchase.incoterm is Incoterm.FOB else ref["cfr_usd_t"]
            disc = parity_px - t.purchase.pricing.price_usd_t
            lo, hi = PURCHASE_DISCOUNT_BAND_USD_T
            if not (lo - 1e-9 <= disc <= hi + 1e-9):
                issues.append(_err("P10", f"{pw}.price_usd_t",
                                   f"{t.purchase.pricing.price_usd_t:,.2f} is {disc:+,.2f} USD/t against the "
                                   f"{t.trade_date} {t.purchase.incoterm} parity of {parity_px:,.2f}; the desk "
                                   f"bids {lo:,.0f}..{hi:,.0f} USD/t under parity"))
        else:
            give = ref["grade_factor"] - t.purchase.pricing.factor_frac
            lo, hi = PURCHASE_FACTOR_BAND
            if not (lo - 1e-12 <= give <= hi + 1e-12):
                issues.append(_err("P10", f"{pw}.factor_frac",
                                   f"{t.purchase.pricing.factor_frac} is {give:+.4f} against the "
                                   f"{t.trade_date} grade factor {ref['grade_factor']:.6f}; a formula purchase "
                                   f"is contracted {lo:.3f}..{hi:.3f} under it"))

    # --- P04 credit limits
    for _, r in credit.iterrows():
        if not r["within_limit"]:
            issues.append(_err("P04", f"trades({r['trade_id']}).sales({r['sale_id']}).buyer_id",
                               f"booking {r['credit_value_inr']:,.0f} ₹ of credit on {r['contract_date']} takes "
                               f"{r['buyer_id']} to {r['exposure_after_inr']:,.0f} ₹ against a limit of "
                               f"{r['credit_limit_inr']:,.0f} ₹"))

    # --- P14 pre-settlement advance reliance (performance exposure the receivable-only limit cannot see)
    mult = float(config.value("buyer_advance_limit_multiple_of_credit_limit"))
    for t in book.trades:
        for s in t.sales:
            adv = s.payment.advance_frac or 0.0
            if adv <= 0:
                continue
            buyer = book.counterparty(s.buyer_id)
            limit = float(buyer.credit_limit_inr or 0.0)
            qty = sum(t.lot_weight_mt(t.lot(lid)) for lid in s.lot_ids)
            price = (s.pricing.price_inr_t if s.pricing.type is SalePricingType.FIXED
                     else _mcx_sale_price_at(s, s.contract_date, t))
            amount = qty * price * adv
            if limit and amount > limit * mult + 1e-6:
                issues.append(_warn("P14", f"trades({t.trade_id}).sales({s.sale_id}).payment.advance_frac",
                                    f"the desk is relying on a {adv:.0%} advance of {amount:,.0f} ₹ from "
                                    f"{s.buyer_id} on {s.payment.advance_date}, {amount / limit:.2f}x its own "
                                    f"credit limit of {limit:,.0f} ₹ against a policy cap of "
                                    f"{mult:.2f}x (buyer_advance_limit_multiple_of_credit_limit). This is not "
                                    f"credit extended, so P04 cannot see it — it is performance exposure: if "
                                    f"the advance fails the desk owns the cargo unsold with its hedge lifted"))

    issues.extend(cross_phase_control())
    return issues


def _dpl_move(day: dt.date) -> float | None:
    """One-day return of the panel's near-month MCX series, or None on the first panel day."""
    idx = panel().index
    pos = idx.get_loc(pd.Timestamp(day))
    if pos == 0:
        return None
    s = panel()["mcx_al_m1_inr_kg"]
    prev, now = float(s.iloc[pos - 1]), float(s.iloc[pos])
    return None if prev == 0 else now / prev - 1.0


def cross_phase_control() -> list[Issue]:
    """P11: this module's per-day §5 arithmetic must reproduce Phase 1 on the days where both are defined.

    Phase 1 owns CONTRACTS §5; Phase 2 re-evaluates it on arbitrary panel days so trade terms can be set on the
    day they are set. If the two ever drift, every price, bound and hedge size in this book is quoting a
    different model from the one that selected the trades.
    """
    from desk.parity import model

    inputs = model.build_inputs()
    p1 = pd.concat([inputs[model.KEY_COLUMNS], model.compute(inputs).drop(columns=model.KEY_COLUMNS)], axis=1)
    p1 = p1[p1["in_window"].astype(bool)]
    worst, where = 0.0, ""
    for _, r in p1.iterrows():
        ref = market_reference(pd.Timestamp(r["value_date"]).date(), r["grade"], r["lane"])
        p1_repl = float(r["goods_inr_t"] + r["bcd_inr_t"] + r["sws_inr_t"] + r["port_inr_t"])
        for name, a, b in (("net_arb_inr_t", ref["net_arb_inr_t"], float(r["net_arb_inr_t"])),
                           ("landed_inr_t", ref["landed_inr_t"], float(r["landed_inr_t"])),
                           ("replacement_inr_t", ref["replacement_inr_t"], p1_repl)):
            if abs(a - b) > worst:
                worst, where = abs(a - b), f"{r['value_date']} {r['grade']}/{r['lane']} {name}"
    if worst > 0.01:
        return [_err("P11", "desk.book.validate.market_reference",
                     f"drifts from desk.parity.model by ₹{worst:.4f}/t at {where}; the two must agree to ₹0.01")]
    return []


def main() -> None:
    """Load and validate the book; print every issue and raise if any is an ERROR."""
    from desk.book.schema import load_book
    from desk.paths import CONFIG_DIR

    book = load_book(CONFIG_DIR / "trades.yaml", CONFIG_DIR / "counterparties.yaml",
                     strict=False, panel_days=set(panel_days()))
    issues = validate(book)
    for i in issues:
        print(i.format())
    errors = [i for i in issues if i.severity == "ERROR"]
    print(f"{len(book.trades)} trades, {len(book.counterparties)} counterparties: "
          f"{len(errors)} errors, {len(issues) - len(errors)} warnings")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
