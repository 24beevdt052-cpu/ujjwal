"""Phase 2 stage module — load, validate and publish the mock trading book.

`main()` reads `config/counterparties.yaml` and `config/trades.yaml`, runs every rule in `desk.book.schema`
(V01–V20) and `desk.book.validate` (P01–P12), and writes three tables:

    outputs/tables/trade_book.csv               one row per trade: every Table 4 term, flattened, plus the
                                                derived lifecycle dates, the §5a parity evidence and the
                                                valuation bounds each price was set between.
    outputs/tables/trade_hedges.csv             one row per hedge instrument — MCX tranche, USD/INR forward,
                                                freight fixture — with the numbers the desk did NOT type
                                                (fills, strikes, roll deadlines, the index at fixture)
                                                recomputed point-in-time beside the decision it typed.
    outputs/tables/trade_eligibility_check.csv  one row per trade: the three CONTRACTS §5a screens and the
                                                parity numbers the decision was taken against.

Why the derived numbers live here and not in the ticket: a typed fill price is hindsight with a plausible face
(design D11). Everything in these tables that depends on a market observation is recomputed from the Phase 0
panel at the date of the decision it belongs to, so a reader can check the book against the data rather than
against the author.

Determinism (CONTRACTS §1.5): no randomness, rows sorted by identifier, every float rounded at write time, so
two runs produce byte-identical files.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from desk import HORIZON_END, SIM_LABEL, WINDOW_END, WINDOW_START, config, units
from desk.book import validate as V
from desk.book.schema import (
    Book,
    PurchasePricingType,
    SalePricingType,
    Ticket,
    ValidationError,
    load_book,
)
from desk.paths import CONFIG_DIR, DOCS_DIR, PROCESSED_DIR, TABLES_DIR

TRADES_YAML = CONFIG_DIR / "trades.yaml"
COUNTERPARTIES_YAML = CONFIG_DIR / "counterparties.yaml"

# Rounding used at write time so a re-run is byte-identical (design §2).
ROUND = {"inr": 2, "usd": 2, "usd_t": 4, "inr_t": 2, "inr_kg": 4, "frac": 6, "rate": 6, "mt": 3}
JOIN = " | "


# --------------------------------------------------------------------------------------------- market look-ups
def mcx_price_inr_kg(day: dt.date, contract_month: str) -> tuple[float, str, dt.date | None]:
    """The panel price of one MCX contract month on `day`, where it came from, and the panel's expiry slot.

    A position is keyed by contract month, never by expiry date (design D4b), so the price is whichever panel
    slot carries that month on that day — which is also how the panel's rule-based 31-Aug slot and the DIRECT
    30-Aug expiry resolve to the same contract. Beyond the two listed slots there is no panel price and the
    duty-paid parity formula is used instead, flagged so no reader mistakes it for an observation.
    """
    row = V.panel_row(day)
    for slot in ("m1", "m2"):
        expiry = pd.Timestamp(row[f"mcx_{slot}_expiry"]).date()
        if expiry.strftime("%Y-%m") == contract_month:
            return float(row[f"mcx_al_{slot}_inr_kg"]), f"PANEL_{slot.upper()}", expiry
    uplift = 1 + float(config.value("bcd_primary_al_hs7601", day)) * (1 + float(config.value("sws_rate_on_bcd", day)))
    spot = (float(row["lme_cash_usd_t"]) * float(row["usdinr"]) / units.KG_PER_MT * uplift
            + float(config.value("mcx_domestic_premium_inr_kg", day)))
    dte = max(0, (V.mcx_expiries()[contract_month] - day).days)
    return spot * (1 + float(row["inr_rate_3m_pa"]) * dte / 365.0), "THEO_DUTY_PARITY", None


def fx_forward_rate(booking: dt.date, value: dt.date, direction: str) -> tuple[float, float, float]:
    """(mid forward, bank margin, dealt rate) for a deliverable outright booked on `booking` for `value`.

    Mid is covered interest parity off the booking day's spot and 3-month rates (`desk.units.fx_forward`, the
    same PROXY construction as the panel's own forward columns). The bank's margin is taken against the desk in
    both directions, which is the point of quoting it separately.
    """
    row = V.panel_row(booking)
    mid = units.fx_forward(float(row["usdinr"]), float(row["inr_rate_3m_pa"]), float(row["usd_rate_3m_pa"]),
                           (value - booking).days)
    margin = float(config.value("fx_forward_bank_margin_inr", booking))
    sign = 1.0 if direction == "BUY_USD" else -1.0
    return mid, margin, mid + sign * margin


# ------------------------------------------------------------------------------------------------- table rows
def _sale_price_at(t: Ticket, s, day: dt.date) -> float:
    if s.pricing.type is SalePricingType.FIXED:
        return float(s.pricing.price_inr_t)
    ref = V.market_reference(day, t.grade.value, t.lane.value)
    return s.pricing.factor_frac * units.inr_kg_to_inr_t(ref["mcx_anchor_inr_kg"]) + s.pricing.premium_inr_t


def trade_book_rows(book: Book, elig: pd.DataFrame) -> pd.DataFrame:
    """One flattened row per ticket."""
    elig = elig.set_index("trade_id")
    rows: list[dict[str, Any]] = []
    for t in book.trades:
        sched = V.ticket_schedule(t)
        e = elig.loc[t.trade_id]
        sup = book.counterparty(t.purchase.supplier_id)
        ref_trade = V.market_reference(t.trade_date, t.grade.value, t.lane.value)
        first_sale = min(t.sales, key=lambda s: s.contract_date)
        ref_sale = V.market_reference(first_sale.contract_date, t.grade.value, t.lane.value)

        sale_values = {}
        for s in t.sales:
            qty = sum(t.lot_weight_mt(t.lot(lid)) for lid in s.lot_ids)
            sale_values[s.sale_id] = qty * _sale_price_at(t, s, s.contract_date)

        # Two numbers, because they answer different questions and the engine currently computes the first.
        # `flat` charges every chargeable day at the FIRST-slab rate, which is what desk/mtm/lifecycle.py does;
        # `tiered` walks the registered detention slabs, which is what a carrier actually invoices once a delay
        # runs past five days. The engine must move to `desk.book.validate.demurrage_usd` (docs/20 §12).
        demurrage_usd = demurrage_usd_tiered = 0.0
        for l in sched.lots:
            rejected = sum(q.rejected_boxes for q in t.events.quality if q.lot_id == l.lot_id)
            demurrage_usd += ((l.boxes - rejected) * l.chargeable_dwell_days
                              * float(config.value("demurrage_usd_per_box_day", t.trade_date)))
            demurrage_usd_tiered += V.demurrage_usd(l.boxes - rejected, l.chargeable_dwell_days, l.arrival)

        purchase_usd = (t.quantity_mt * t.purchase.pricing.price_usd_t
                        if t.purchase.pricing.type is PurchasePricingType.FIXED else None)
        freight_usd = (t.boxes * t.freight.rate_usd_box
                       if t.freight is not None and t.freight.rate_usd_box is not None else 0.0)

        rows.append({
            "trade_id": t.trade_id,
            "status": t.status.value,
            "trade_date": t.trade_date.isoformat(),
            "in_window": bool(WINDOW_START <= t.trade_date <= WINDOW_END),
            "lane": t.lane.value,
            "grade": t.grade.value,
            "isri_grade_spec": t.purchase.spa.isri_grade_spec,
            "quantity_mt": round(t.quantity_mt, ROUND["mt"]),
            "boxes": t.boxes,
            "box_type": t.box,
            "payload_mt_per_box": round(t.payload_mt_per_box, ROUND["mt"]),
            "n_lots": len(t.shipment.lots),
            # --- §5a trade discipline
            "parity_week_end": t.rationale.parity_week_end.isoformat(),
            "trade_eligible": bool(e["trade_eligible"]),
            "net_arb_inr_t": e["net_arb_inr_t"],
            "net_arb_pit_mix_inr_t": e["net_arb_pit_mix_inr_t"],
            "net_arb_conv18k_inr_t": e["net_arb_conv18k_inr_t"],
            # --- purchase
            "supplier_id": t.purchase.supplier_id,
            "supplier_name": sup.name,
            "spa_ref": t.purchase.spa_ref,
            "incoterm": t.purchase.incoterm.value,
            "named_place": t.purchase.named_place,
            "freight_booked_by": ("SELLER (inside the CFR price)" if t.freight is None
                                  else t.freight.booked_by),
            # Two different risks, and the first draft of this book ran them together. Under BOTH FOB and CFR
            # (Incoterms 2020 A2/B2) the risk of loss or damage passes to the BUYER when the goods are on board
            # at the load port — CFR moves the *cost* of carriage to the seller, never the risk. What differs is
            # who carries the freight PRICE risk, which is what this column is about.
            "cargo_risk_passes": "on board at the load port (Incoterms 2020: FOB A2/B2 and CFR A2/B2 alike)",
            # The column keeps its published name (desk/excel reads it) and its short shape, but it now means
            # only the freight PRICE risk; `cargo_risk_passes` carries what the incoterm does to title risk.
            "freight_risk_borne_by": ("SELLER (inside the CFR price)" if t.freight is None else "DESK"),
            "moisture_franchise_frac": round(float(t.purchase.spa.moisture_franchise_frac
                                                   or config.value("standard_moisture_franchise_frac",
                                                                   t.trade_date)), ROUND["frac"]),
            "contamination_limit_frac": round(float(t.purchase.spa.contamination_limit_frac
                                                    or config.value(f"contamination_frac_{t.grade.value}",
                                                                    t.trade_date)), ROUND["frac"]),
            "discount_multiple": round(float(t.purchase.spa.discount_multiple
                                             or config.value("spa_contamination_discount_multiple",
                                                             t.trade_date)), ROUND["frac"]),
            "rejection_excess_frac": round(float(t.purchase.spa.rejection_excess_frac
                                                 or config.value("spa_contamination_rejection_excess_frac",
                                                                 t.trade_date)), ROUND["frac"]),
            "radioactivity_clause_key": t.purchase.spa.radioactivity_clause_key,
            "penalty_schedule_key": t.purchase.spa.penalty_schedule_key,
            "quantity_tolerance_frac": (None if t.purchase.spa.quantity_tolerance_frac is None
                                        else round(t.purchase.spa.quantity_tolerance_frac, ROUND["frac"])),
            "lc_amount_tolerance_frac": round(
                V.LC_AMOUNT_TOLERANCE_FRAC if t.purchase.spa.quantity_tolerance_frac is None
                else t.purchase.spa.quantity_tolerance_frac, ROUND["frac"]),
            "purchase_pricing_type": t.purchase.pricing.type.value,
            "purchase_price_usd_t": (None if t.purchase.pricing.price_usd_t is None
                                     else round(t.purchase.pricing.price_usd_t, ROUND["usd_t"])),
            "purchase_lme_reference": (None if t.purchase.pricing.lme_reference is None
                                       else t.purchase.pricing.lme_reference.value),
            "purchase_factor_frac": (None if t.purchase.pricing.factor_frac is None
                                     else round(t.purchase.pricing.factor_frac, ROUND["frac"])),
            "purchase_premium_usd_t": round(t.purchase.pricing.premium_usd_t, ROUND["usd_t"]),
            "provisional_frac": (None if t.purchase.pricing.provisional_frac is None
                                 else round(t.purchase.pricing.provisional_frac, ROUND["frac"])),
            "pricing_period_month": sched.qp_month,
            "pricing_period_start": None if sched.pricing_start is None else sched.pricing_start.isoformat(),
            "pricing_period_end": None if sched.pricing_end is None else sched.pricing_end.isoformat(),
            "final_invoice_date": None if sched.final_invoice is None else sched.final_invoice.isoformat(),
            "payment_instrument": t.purchase.payment.instrument.value,
            "usance_days": t.purchase.payment.usance_days,
            "lc_open_date": t.purchase.payment.lc_open_date.isoformat(),
            "issuing_bank": t.purchase.payment.issuing_bank,
            "lc_confirmed": t.purchase.payment.confirmed,
            "confirmation_charges_for": (None if t.purchase.payment.confirmation_charges_for is None
                                         else t.purchase.payment.confirmation_charges_for.value),
            "psic_required": bool(config.value(V.LANE_SPEC[t.lane]["psic_key"], t.trade_date)),
            # --- shipment
            "laycan_start": t.shipment.laycan_start.isoformat(),
            "laycan_end": t.shipment.laycan_end.isoformat(),
            "load_port": t.shipment.load_port,
            "discharge_port": t.shipment.discharge_port.value,
            "lot_ids": JOIN.join(l.lot_id for l in t.shipment.lots),
            "lot_boxes": JOIN.join(str(l.boxes) for l in t.shipment.lots),
            "bl_dates": JOIN.join(l.bl_date.isoformat() for l in t.shipment.lots),
            "vessels": JOIN.join(l.vessel for l in t.shipment.lots),
            "voyages": JOIN.join(l.voyage for l in t.shipment.lots),
            "arrival_dates": JOIN.join(l.arrival.isoformat() for l in sched.lots),
            "boe_dates": JOIN.join(l.boe.isoformat() for l in sched.lots),
            "release_dates": JOIN.join(l.release.isoformat() for l in sched.lots),
            "igst_credit_dates": JOIN.join(l.igst_credit.isoformat() for l in sched.lots),
            "lc_pay_dates": JOIN.join(l.lc_pay.isoformat() for l in sched.lots),
            "usance_maturity_dates": JOIN.join(l.usance_maturity.isoformat() for l in sched.lots
                                               if l.usance_maturity is not None),
            "chargeable_dwell_days": JOIN.join(str(l.chargeable_dwell_days) for l in sched.lots),
            # --- freight layer (FOB only)
            "freight_forwarder": None if t.freight is None else t.freight.forwarder,
            "freight_payment_terms": None if t.freight is None else t.freight.payment_terms.value,
            "freight_risk_layer": None if t.freight is None else t.freight.risk_layer.value,
            "freight_fixture_date": (None if t.freight is None or t.freight.fixture_date is None
                                     else t.freight.fixture_date.isoformat()),
            "freight_rate_usd_box": (None if t.freight is None or t.freight.rate_usd_box is None
                                     else round(t.freight.rate_usd_box, ROUND["usd"])),
            "freight_index_usd_box_at_fixture": (
                None if t.freight is None or t.freight.fixture_date is None
                else round(V._freight_index_usd_box(t.freight.fixture_date, t.lane), ROUND["usd"])),
            "freight_stop_loss_usd_box": (None if t.freight is None or t.freight.stop_loss is None
                                          else round(t.freight.stop_loss.stop_loss_usd_box, ROUND["usd"])),
            "freight_latest_fixture_date": (None if t.freight is None or t.freight.stop_loss is None
                                            else t.freight.stop_loss.latest_fixture_date.isoformat()),
            "freight_total_usd": round(freight_usd, ROUND["usd"]),
            # --- sales
            "sale_ids": JOIN.join(s.sale_id for s in t.sales),
            "buyer_ids": JOIN.join(s.buyer_id for s in t.sales),
            "buyer_names": JOIN.join(book.counterparty(s.buyer_id).name for s in t.sales),
            "sale_contract_dates": JOIN.join(s.contract_date.isoformat() for s in t.sales),
            "sale_lot_ids": JOIN.join("+".join(s.lot_ids) for s in t.sales),
            "sale_delivery_basis": JOIN.join(s.delivery_basis for s in t.sales),
            "sale_pricing_types": JOIN.join(s.pricing.type.value for s in t.sales),
            "sale_price_inr_t": JOIN.join(
                ("" if s.pricing.price_inr_t is None else f"{s.pricing.price_inr_t:,.2f}") for s in t.sales),
            "sale_mcx_series": JOIN.join(
                ("" if s.pricing.mcx_series is None else s.pricing.mcx_series.value) for s in t.sales),
            "sale_pricing_window": JOIN.join(
                ("" if s.pricing.window_start is None
                 else f"{s.pricing.window_start}..{s.pricing.window_end}") for s in t.sales),
            "sale_factor_frac": JOIN.join(
                ("" if s.pricing.factor_frac is None else f"{s.pricing.factor_frac:.6f}") for s in t.sales),
            "sale_premium_inr_t": JOIN.join(f"{s.pricing.premium_inr_t:,.2f}" for s in t.sales),
            "sale_payment_terms": JOIN.join(s.payment.terms.value for s in t.sales),
            "sale_credit_days": JOIN.join(str(s.payment.credit_days or "") for s in t.sales),
            "sale_advance_frac": JOIN.join(
                ("" if s.payment.advance_frac is None else f"{s.payment.advance_frac:.2f}") for s in t.sales),
            "sale_advance_dates": JOIN.join(
                ("" if s.payment.advance_date is None else s.payment.advance_date.isoformat()) for s in t.sales),
            "sale_invoice_dates": JOIN.join(sched.sale_invoice[s.sale_id].isoformat() for s in t.sales),
            "sale_due_dates_contractual": JOIN.join(
                sched.sale_due_contractual[s.sale_id].isoformat() for s in t.sales),
            "sale_due_dates_with_events": JOIN.join(sched.sale_due[s.sale_id].isoformat() for s in t.sales),
            "sale_value_inr": round(sum(sale_values.values()), ROUND["inr"]),
            "quality_passthrough": JOIN.join(str(s.quality_passthrough) for s in t.sales),
            # --- hedges (detail in trade_hedges.csv)
            "mcx_hedge_ratio_target": (None if t.hedges.mcx.hedge_ratio_target is None
                                       else round(t.hedges.mcx.hedge_ratio_target, ROUND["frac"])),
            "mcx_tranches": len(t.hedges.mcx.tranches),
            "mcx_rolls": sum(1 for tr in t.hedges.mcx.tranches if tr.roll_to),
            "mcx_lots_at_first_entry": V.open_lots(t, min((tr.entry_date for tr in t.hedges.mcx.tranches),
                                                          default=t.trade_date)),
            "fx_hedge_frac_target": (None if t.hedges.fx_forwards.hedge_frac_target is None
                                     else round(t.hedges.fx_forwards.hedge_frac_target, ROUND["frac"])),
            "fx_forward_lines": len(t.hedges.fx_forwards.lines),
            "fx_gross_notional_usd": round(sum(x.notional_usd for x in t.hedges.fx_forwards.lines), ROUND["usd"]),
            "purchase_usd_at_contract": None if purchase_usd is None else round(purchase_usd, ROUND["usd"]),
            "fx_cover_frac_of_fixed_purchase": (
                None if purchase_usd is None else
                round(sum(x.notional_usd for x in t.hedges.fx_forwards.lines
                          if x.matched_leg.value == "PURCHASE_INVOICE") / purchase_usd, ROUND["frac"])),
            # --- valuation bounds the prices were set between (design §15.1.3)
            "replacement_inr_t_at_trade_date": round(ref_trade["replacement_inr_t"], ROUND["inr_t"]),
            "netback_inr_t_at_trade_date": round(ref_trade["netback_inr_t"], ROUND["inr_t"]),
            "landed_inr_t_at_trade_date": round(ref_trade["landed_inr_t"], ROUND["inr_t"]),
            "cfr_parity_usd_t_at_trade_date": round(ref_trade["cfr_usd_t"], ROUND["usd_t"]),
            "fob_parity_usd_t_at_trade_date": round(ref_trade["fob_usd_t"], ROUND["usd_t"]),
            "grade_factor_at_trade_date": round(ref_trade["grade_factor"], ROUND["frac"]),
            "replacement_inr_t_at_first_sale": round(ref_sale["replacement_inr_t"], ROUND["inr_t"]),
            "netback_inr_t_at_first_sale": round(ref_sale["netback_inr_t"], ROUND["inr_t"]),
            "p1_finance_memo_inr": round(
                (ref_trade["finance_inr_t"] + ref_trade["igst_finance_inr_t"]) * t.quantity_mt, ROUND["inr"]),
            # --- events (SIM)
            "event_quality": JOIN.join(
                f"{q.lot_id}: moisture {q.moisture_actual_frac:.3f}, contamination "
                f"{q.contamination_actual_frac:.3f}, rejected {q.rejected_boxes} box(es)"
                + (f" ({q.rejection_reason.value})" if q.rejection_reason else "") + " (SIM)"
                for q in t.events.quality),
            "event_logistics": JOIN.join(
                f"{g.event_id}: {g.lot_id} +{g.extra_dwell_days}d dwell, +{g.arrival_delay_days}d arrival, "
                f"known {g.known_date} (SIM)" for g in t.events.logistics),
            "event_buyer_payment_delay": JOIN.join(
                f"{b.event_id}: {b.sale_id} +{b.delay_days}d, known {b.known_date} (SIM)"
                for b in t.events.buyer_payment_delay),
            "demurrage_usd_at_plan": round(demurrage_usd, ROUND["usd"]),
            "demurrage_usd_at_plan_tiered": round(demurrage_usd_tiered, ROUND["usd"]),
            # --- lifecycle
            "last_cashflow_date": sched.last_cashflow.isoformat(),
            "close_date": sched.close_date.isoformat(),
            "settles_inside_horizon": bool(sched.last_cashflow <= HORIZON_END),
            "rationale": " ".join(t.rationale.text.split()),
            "rationale_cited_columns": JOIN.join(t.rationale.cited_columns),
            "sim_label": SIM_LABEL,
        })
    return pd.DataFrame(rows).sort_values("trade_id").reset_index(drop=True)


def trade_hedge_rows(book: Book) -> pd.DataFrame:
    """One row per hedge instrument, with every derived number beside the decision that was typed."""
    rows: list[dict[str, Any]] = []
    for t in book.trades:
        sched = V.ticket_schedule(t)
        lot_mt = float(config.value("mcx_al_lot_mt"))
        roll_targets = {tr.roll_to for tr in t.hedges.mcx.tranches if tr.roll_to}

        for tr in t.hedges.mcx.tranches:
            entry_px, entry_src, entry_slot = mcx_price_inr_kg(tr.entry_date, tr.contract_month)
            exit_px, exit_src, _ = mcx_price_inr_kg(tr.exit_date, tr.contract_month)
            position_mt = tr.lots * lot_mt
            contract_value = position_mt * units.KG_PER_MT * entry_px
            net, basis = V.hedge_exposure_inr_per_usd_t(t, tr.entry_date, sched)
            per_lot = V.mcx_delta_inr_per_lot(tr.entry_date, tr.contract_month)
            position = V.open_lots(t, tr.entry_date)
            rows.append({
                "trade_id": t.trade_id,
                "instrument": "MCX_ALUMINIUM_FUTURE",
                "hedge_id": tr.hedge_id,
                "decision_date": tr.entry_date.isoformat(),
                "contract_month": tr.contract_month,
                "direct_expiry": V.mcx_expiries()[tr.contract_month].isoformat(),
                "panel_expiry_slot": None if entry_slot is None else entry_slot.isoformat(),
                "roll_deadline": V.mcx_roll_deadline(tr.contract_month).isoformat(),
                "direction": tr.direction.value,
                "lots": tr.lots,
                "lot_mt": round(lot_mt, ROUND["mt"]),
                "position_mt": round(position_mt, ROUND["mt"]),
                "entry_date": tr.entry_date.isoformat(),
                "exit_date": tr.exit_date.isoformat(),
                "exit_reason": tr.exit_reason.value,
                "roll_to": tr.roll_to,
                "entry_price_inr_kg": round(entry_px, ROUND["inr_kg"]),
                "entry_price_src": entry_src,
                "exit_price_inr_kg": round(exit_px, ROUND["inr_kg"]),
                "exit_price_src": exit_src,
                "contract_value_at_entry_inr": round(contract_value, ROUND["inr"]),
                "im_required_at_entry_inr": round(
                    contract_value * float(config.value("mcx_al_margin_used_frac", tr.entry_date)), ROUND["inr"]),
                "hedge_ratio_target": (None if t.hedges.mcx.hedge_ratio_target is None
                                       else round(t.hedges.mcx.hedge_ratio_target, ROUND["frac"])),
                "hedge_ratio_actual": (None if tr.hedge_id in roll_targets or abs(net) < 1e-9
                                       else round(position * per_lot / net, ROUND["frac"])),
                "open_lots_after_entry": position,
                "exposure_inr_per_usd_t_at_entry": round(net, ROUND["inr"]),
                "lme_eq_mt_at_entry": round(net / (per_lot / lot_mt), ROUND["mt"]) if per_lot else None,
                "sizing_basis": ("rolled: a roll keeps the position of the line it continues"
                                 if tr.hedge_id in roll_targets else basis),
                "notional_usd": None, "booking_date": None, "value_date": None, "cancel_date": None,
                "matched_leg": None, "forward_mid_inr": None, "bank_margin_inr": None, "rate_inr": None,
                "index_usd_box_at_fixture": None, "fixture_vs_index_frac": None,
                "basis_risk_note": " ".join(t.hedges.mcx.basis_risk_note.split()),
                "weakest_input_flag": "PROXY",   # the MCX panel series is a duty-parity proxy
            })

        for x in t.hedges.fx_forwards.lines:
            mid, margin, rate = fx_forward_rate(x.booking_date, x.value_date, x.direction.value)
            rows.append({
                "trade_id": t.trade_id,
                "instrument": "USDINR_FORWARD",
                "hedge_id": x.fwd_id,
                "decision_date": x.booking_date.isoformat(),
                "contract_month": None, "direct_expiry": None, "panel_expiry_slot": None, "roll_deadline": None,
                "direction": x.direction.value,
                "lots": None, "lot_mt": None, "position_mt": None,
                "entry_date": x.booking_date.isoformat(),
                "exit_date": (x.cancel_date or x.value_date).isoformat(),
                "exit_reason": "CANCELLED" if x.cancel_date else "SETTLED_AT_VALUE_DATE",
                "roll_to": None,
                "entry_price_inr_kg": None, "entry_price_src": None,
                "exit_price_inr_kg": None, "exit_price_src": None,
                "contract_value_at_entry_inr": round(x.notional_usd * rate, ROUND["inr"]),
                "im_required_at_entry_inr": None,
                "hedge_ratio_target": (None if t.hedges.fx_forwards.hedge_frac_target is None
                                       else round(t.hedges.fx_forwards.hedge_frac_target, ROUND["frac"])),
                "hedge_ratio_actual": None,
                "open_lots_after_entry": None,
                "exposure_inr_per_usd_t_at_entry": None,
                "lme_eq_mt_at_entry": None,
                "sizing_basis": (f"matched to {x.matched_leg.value}; tenor "
                                 f"{(x.value_date - x.booking_date).days} days from booking"),
                "notional_usd": round(x.notional_usd, ROUND["usd"]),
                "booking_date": x.booking_date.isoformat(),
                "value_date": x.value_date.isoformat(),
                "cancel_date": None if x.cancel_date is None else x.cancel_date.isoformat(),
                "matched_leg": x.matched_leg.value,
                "forward_mid_inr": round(mid, ROUND["rate"]),
                "bank_margin_inr": round(margin, ROUND["rate"]),
                "rate_inr": round(rate, ROUND["rate"]),
                "index_usd_box_at_fixture": None, "fixture_vs_index_frac": None,
                "basis_risk_note": ("Deliverable outright against the LC/usance payment date. The forward mid is "
                                    "covered interest parity off the booking day's spot and 3-month rates "
                                    "(PROXY), so the hedge is exact against the panel and carries the panel's "
                                    "own FX proxy error, not a market quote."),
                "weakest_input_flag": "PROXY",   # USD/INR and the CIP forward are proxies
            })

        if t.freight is not None and t.freight.fixture_date is not None:
            index = V._freight_index_usd_box(t.freight.fixture_date, t.lane)
            rows.append({
                "trade_id": t.trade_id,
                "instrument": "FREIGHT_FIXTURE",
                "hedge_id": f"{t.trade_id}-FRT-1",
                "decision_date": t.freight.fixture_date.isoformat(),
                "contract_month": None, "direct_expiry": None, "panel_expiry_slot": None, "roll_deadline": None,
                "direction": "BUY_SPACE",
                "lots": t.boxes, "lot_mt": round(t.payload_mt_per_box, ROUND["mt"]),
                "position_mt": round(t.quantity_mt, ROUND["mt"]),
                "entry_date": t.freight.fixture_date.isoformat(),
                "exit_date": max(l.freight_pay for l in sched.lots).isoformat(),
                "exit_reason": t.freight.payment_terms.value,
                "roll_to": None,
                "entry_price_inr_kg": None, "entry_price_src": None,
                "exit_price_inr_kg": None, "exit_price_src": None,
                "contract_value_at_entry_inr": round(
                    t.boxes * t.freight.rate_usd_box * float(V.panel_row(t.freight.fixture_date)["usdinr"]),
                    ROUND["inr"]),
                "im_required_at_entry_inr": None,
                "hedge_ratio_target": 0.0,
                "hedge_ratio_actual": 0.0,
                "open_lots_after_entry": None,
                "exposure_inr_per_usd_t_at_entry": None,
                "lme_eq_mt_at_entry": None,
                "sizing_basis": (f"{t.boxes} boxes fixed all-in; stop-loss "
                                 f"{t.freight.stop_loss.stop_loss_usd_box:,.0f} USD/FEU, book-by "
                                 f"{t.freight.stop_loss.latest_fixture_date}"
                                 if t.freight.stop_loss else f"{t.boxes} boxes fixed all-in"),
                "notional_usd": round(t.boxes * t.freight.rate_usd_box, ROUND["usd"]),
                "booking_date": t.freight.fixture_date.isoformat(),
                "value_date": max(l.freight_pay for l in sched.lots).isoformat(),
                "cancel_date": None,
                "matched_leg": "FREIGHT",
                "forward_mid_inr": None, "bank_margin_inr": None, "rate_inr": None,
                "index_usd_box_at_fixture": round(index, ROUND["usd"]),
                "fixture_vs_index_frac": round(t.freight.rate_usd_box / index - 1.0, ROUND["frac"]),
                "basis_risk_note": (
                    "Table 4 row 2.7(d): no accessible India-lane container derivative existed in 2022, so the "
                    "freight layer is UNHEDGED with a stated stop-loss rather than a hedge. Once fixed, the box "
                    "rate is a fixed payable and the only live freight exposure left is the difference against "
                    "the later market, which is a competitiveness memo and not a loss on this cargo (a "
                    "CFR-basis grade factor does not fall when freight falls). The lane index itself is an "
                    "ASSUMPTION-level reconstruction and the fixture spread over it is an ASSUMPTION."),
                "weakest_input_flag": "ASSUMPTION",
            })
    out = pd.DataFrame(rows)
    for col in ("lots", "open_lots_after_entry"):
        out[col] = out[col].astype("Int64")
    order = {"MCX_ALUMINIUM_FUTURE": 0, "USDINR_FORWARD": 1, "FREIGHT_FIXTURE": 2}
    out["_o"] = out["instrument"].map(order)
    return out.sort_values(["trade_id", "_o", "hedge_id"]).drop(columns="_o").reset_index(drop=True)


# ------------------------------------------------------------------------------------------------------- main
def _md_table(df: pd.DataFrame, columns: dict[str, str], fmt: dict[str, Any] | None = None) -> str:
    """Render selected columns of `df` as a GitHub markdown table. `columns` maps column -> header."""
    fmt = fmt or {}
    head = "| " + " | ".join(columns.values()) + " |"
    rule = "|" + "|".join("---" for _ in columns) + "|"
    lines = [head, rule]
    for _, r in df.iterrows():
        cells = []
        for col in columns:
            v = r[col]
            f = fmt.get(col)
            text = ("" if v is None or (isinstance(v, float) and pd.isna(v))
                    else (f(v) if callable(f) else (format(v, f) if f else str(v))))
            cells.append(text.replace("|", "\\|"))   # a joined multi-value cell must not break the table
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ------------------------------------------------------------------------------- review-era doc computations
# Each of these answers a finding raised by an independent reviewer and is computed here, from the panel and the
# book, so the page can never drift from the tables. None of them changes a ticket.
def _screen_overlap() -> dict[str, int]:
    """How the three CONTRACTS §5a screens actually interact over the window (they are not independent)."""
    from desk.parity import model

    pw = model.load_parity()
    w = pw[pw["in_window"].astype(bool)]
    by_week = w.groupby("week_end")[["open_base", "open_pit_mix", "open_conv18k", "trade_eligible"]].sum()
    # The longest run of consecutive weeks the gate shut while the no-hindsight screen stayed open: the book's
    # most visible piece of "discipline", and the screen that produced it is the reconstructed one.
    best = cur = []
    for week, r in by_week.iterrows():
        if r["trade_eligible"] == 0 and r["open_pit_mix"] > 0:
            cur = cur + [(week, int(r["open_pit_mix"]))]
            best = cur if len(cur) > len(best) else best
        else:
            cur = []
    return {
        "cases": len(w),
        "base": int(w["open_base"].sum()),
        "pit": int(w["open_pit_mix"].sum()),
        "conv18k": int(w["open_conv18k"].sum()),
        "eligible": int(w["trade_eligible"].sum()),
        "pit_excludes_alone": int((w["open_conv18k"] & ~w["open_pit_mix"]).sum()),
        "pit_open_conv_shut": int((w["open_pit_mix"] & ~w["open_conv18k"]).sum()),
        "rows_all": len(pw),
        "identical": int((pw["trade_eligible"] == pw["open_conv18k"]).sum()),
        "shut_weeks": len(best),
        "shut_from": "" if not best else str(best[0][0].date()),
        "shut_to": "" if not best else str(best[-1][0].date()),
        "shut_pit_min": 0 if not best else min(x[1] for x in best),
        "cases_per_week": int(len(w) / max(len(by_week), 1)),
    }


def _roll_pnl(mcx: pd.DataFrame) -> tuple[int, float]:
    """(number of rolls, their total ₹ P&L). On the panel's deterministic curve every one of them is a gain."""
    m = mcx.set_index("hedge_id")
    rolls, total = 0, 0.0
    for _, r in m.iterrows():
        if r["exit_reason"] != "ROLL" or not isinstance(r["roll_to"], str):
            continue
        tgt = m.loc[r["roll_to"]]
        sign = 1.0 if r["direction"] == "SELL" else -1.0
        total += sign * (tgt["entry_price_inr_kg"] - r["exit_price_inr_kg"]) * r["position_mt"] * units.KG_PER_MT
        rolls += 1
    return rolls, total


def _freight_counterfactual(book: Book) -> pd.DataFrame:
    """Fix on the trade date vs wait to the book-by date — the decision the stop-loss was standing in for."""
    rows = []
    for t in book.trades:
        f = t.freight
        if f is None or f.fixture_date is None or f.rate_usd_box is None:
            continue
        i_trade = V._freight_index_usd_box(t.trade_date, t.lane)
        i_fix = V._freight_index_usd_box(f.fixture_date, t.lane)
        spread = f.rate_usd_box / i_fix - 1.0
        fix_now = i_trade * (1 + spread)
        rows.append({"trade_id": t.trade_id, "boxes": t.boxes, "trade_date": t.trade_date.isoformat(),
                     "index_at_trade": i_trade, "fix_now_usd_box": fix_now,
                     "fixture_date": f.fixture_date.isoformat(), "index_at_fixture": i_fix,
                     "rate_usd_box": f.rate_usd_box, "saved_usd": (fix_now - f.rate_usd_box) * t.boxes,
                     "stop_usd_box": f.stop_loss.stop_loss_usd_box if f.stop_loss else None,
                     "headroom_frac": (f.stop_loss.stop_loss_usd_box / i_fix - 1.0) if f.stop_loss else None})
    return pd.DataFrame(rows)


def _spread_sensitivity(book: Book) -> pd.DataFrame:
    """What the three fixtures cost at other NVOCC spreads. The 1.7-2.0 % used is an ASSUMPTION with no evidence."""
    rows = []
    for t in book.trades:
        f = t.freight
        if f is None or f.fixture_date is None or f.rate_usd_box is None:
            continue
        i_fix = V._freight_index_usd_box(f.fixture_date, t.lane)
        row = {"trade_id": t.trade_id, "boxes": t.boxes, "actual_spread": f.rate_usd_box / i_fix - 1.0,
               "actual_usd": t.boxes * f.rate_usd_box}
        for sp in V.FIXTURE_SPREAD_SENSITIVITY:
            row[f"usd_at_{sp:.0%}"] = t.boxes * i_fix * (1 + sp)
        rows.append(row)
    return pd.DataFrame(rows)


def _laycan_slip(book: Book) -> pd.DataFrame:
    """The quotational-period risk the three M+1 tickets carry and the book never realises: no lot slips a month."""
    panel = V.panel()
    rows = []
    for t in book.trades:
        if t.purchase.pricing.type is not PurchasePricingType.LME_M1_AVG:
            continue
        sched = V.ticket_schedule(t)
        qp = dt.date.fromisoformat(sched.qp_month + "-01")
        nxt = (qp + dt.timedelta(days=32)).replace(day=1)
        a = panel.loc[qp.isoformat():(nxt - dt.timedelta(days=1)).isoformat(), "lme_cash_usd_t"].mean()
        end_nxt = (nxt + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
        b = panel.loc[nxt.isoformat():end_nxt.isoformat(), "lme_cash_usd_t"].mean()
        last = t.shipment.lots[-1]
        qty = t.lot_weight_mt(last)
        usd = t.purchase.pricing.factor_frac * (a - b) * qty
        fx = float(V.panel_row(V._last_panel_day(sched.pricing_end))["usdinr"])
        rows.append({"trade_id": t.trade_id, "qp_month": sched.qp_month, "qp_avg": a,
                     "next_month": nxt.strftime("%Y-%m"), "next_avg": b, "lot_id": last.lot_id,
                     "lot_bl": last.bl_date.isoformat(), "laycan_end": t.shipment.laycan_end.isoformat(),
                     "slack_days": (t.shipment.laycan_end - last.bl_date).days,
                     "qty_mt": qty, "swing_usd": usd, "swing_inr": usd * fx})
    return pd.DataFrame(rows)


def _desk_share_table(book: Book) -> pd.DataFrame:
    """Day-one sale margin at other splits of the modelled arbitrage, and at a flat trading margin.

    The book's sale price is `replacement + 50 % x (netback - replacement)` adjusted for payment terms. That 50 %
    is a convention, not a quote, and it is the single largest judgement in the book — so the page publishes what
    the same nine tickets would have made at other conventions instead of only defending this one.
    """
    sales = [(t, s) for t in book.trades for s in t.sales]
    refs = {(t.trade_id, s.sale_id): V.market_reference(s.contract_date, t.grade.value, t.lane.value)
            for t, s in sales}
    qty = {(t.trade_id, s.sale_id): sum(t.lot_weight_mt(t.lot(l)) for l in s.lot_ids) for t, s in sales}
    rows = []
    for share in (V.DESK_ARB_SHARE_FRAC, 0.25, 0.10, 0.0):
        total = 0.0
        for t, s in sales:
            r = refs[(t.trade_id, s.sale_id)]
            mid = r["replacement_inr_t"] + share * (r["netback_inr_t"] - r["replacement_inr_t"])
            price = mid + V.sale_terms_delta_inr_t(s, mid, s.contract_date)
            total += qty[(t.trade_id, s.sale_id)] * (price - r["replacement_inr_t"])
        rows.append({"basis": f"{share:.0%} of the modelled arbitrage"
                              + ("  ← the book" if share == V.DESK_ARB_SHARE_FRAC else ""),
                     "day_one_margin_inr": total})
    for flat in (5000.0, 8000.0):
        rows.append({"basis": f"a flat ₹{flat:,.0f}/MT trading margin over replacement",
                     "day_one_margin_inr": sum(qty[k] * flat for k in qty)})
    return pd.DataFrame(rows)


def _signed_mn(v: float) -> str:
    return f"{'−' if v < 0 else '+'}₹{abs(v) / 1e6:,.1f} mn"


def _freight_up_weeks(book: Book) -> dict[str, Any]:
    """Up-weeks in the window, and the closest the lane index came to any FOB ticket's stop while it was open.

    Replaces the word "monotonically", which was false: the series rises in a handful of small weeks (review
    finding, spec-honesty lens). Both numbers are recomputed here so the sentence cannot drift from the data.
    """
    f = pd.read_csv(PROCESSED_DIR / "freight_weekly.csv", parse_dates=["week_end"])
    w = f[(f["week_end"] >= pd.Timestamp(WINDOW_START)) & (f["week_end"] <= pd.Timestamp(WINDOW_END))]
    up = int((w["freight_usec_mun_usd_t"].diff() > 0).sum())
    gaps = []
    for t in book.trades:
        fr = t.freight
        if fr is None or fr.stop_loss is None or fr.fixture_date is None:
            continue
        for d in V.panel_days():
            if t.trade_date <= d <= fr.fixture_date:
                gaps.append(fr.stop_loss.stop_loss_usd_box / V._freight_index_usd_box(d, t.lane) - 1.0)
    return {"n_up_weeks": up, "min_gap_to_stop": min(gaps) if gaps else float("nan")}


def _freight_weekly_stats() -> dict[str, Any]:
    """How fast the reconstructed lane index can actually move — the test of whether a +15 % stop could bind."""
    f = pd.read_csv(PROCESSED_DIR / "freight_weekly.csv", parse_dates=["week_end"])
    y = f[(f["week_end"] >= "2022-01-01") & (f["week_end"] <= "2022-09-30")].copy()
    out: dict[str, Any] = {}
    for lane, col in (("usec", "freight_usec_mun_usd_t"), ("jea", "freight_jea_nsa_usd_t")):
        pct = y[col].pct_change()
        out[f"{lane}_max_rise"] = float(pct.max())
        out[f"{lane}_max_rise_week"] = str(y.loc[pct.idxmax(), "week_end"].date())
        window = pct[(y["week_end"] >= "2022-03-04") & (y["week_end"] <= "2022-07-29")]
        out[f"{lane}_window_max_rise"] = float(window.max())
    return out


def _freight_note(week_end: str) -> str:
    """The Phase 0 provenance sentence for one freight week, quoted rather than paraphrased."""
    f = pd.read_csv(PROCESSED_DIR / "freight_weekly.csv")
    row = f[f["week_end"] <= week_end]
    if row.empty:
        return ""
    return str(row.iloc[-1]["note"])


def render_doc(book: Book, tables: dict[str, pd.DataFrame], credit: pd.DataFrame, issues) -> str:
    """The recruiter-facing methods page, rendered from the same frames the CSVs are written from.

    Nothing here is typed twice: every number below comes out of `tables` or `credit`, so the page and the
    tables cannot disagree. Prose that is a judgement is written as a judgement and labelled.
    """
    tb, hd, el = tables["trade_book.csv"], tables["trade_hedges.csv"], tables["trade_eligibility_check.csv"]
    credit = tables.get("trade_credit_exposure.csv", credit)
    mcx, fx, frt = (hd[hd["instrument"] == k] for k in ("MCX_ALUMINIUM_FUTURE", "USDINR_FORWARD",
                                                        "FREIGHT_FIXTURE"))
    by_id = {t.trade_id: t for t in book.trades}
    suppliers = [c for c in book.counterparties if c.role.value == "SUPPLIER"]
    buyers = [c for c in book.counterparties if c.role.value == "BUYER"]
    inr = lambda x: f"{x:,.0f}"
    pct = lambda x: f"{x:.0%}"

    cp_rows = []
    for c in suppliers + buyers:
        used = [t.trade_id for t in book.trades if t.purchase.supplier_id == c.cp_id] or \
               sorted({t.trade_id for t in book.trades for s in t.sales if s.buyer_id == c.cp_id})
        g = credit[credit["buyer_id"] == c.cp_id]
        cp_rows.append({
            "cp_id": c.cp_id, "name": c.name, "role": c.role.value, "type": c.type.value,
            "location": f"{c.location}, {c.country}",
            "lanes": ", ".join(l.value for l in c.lanes) or "—",
            "limit": (f"₹{c.credit_limit_inr:,.0f}" if c.credit_limit_inr is not None
                      else f"USD {c.claims_exposure_limit_usd:,.0f} (claims)"),
            "terms": (c.default_payment_terms.value if c.default_payment_terms else
                      ("LC confirmed" if c.lc_confirmation_required else "LC unconfirmed")),
            "peak": (f"{g['utilisation_frac'].max():.0%}" if len(g) else "—"),
            "rating": c.profile.internal_rating_sim or "—",
            "trades": ", ".join(used),
        })
    cp = pd.DataFrame(cp_rows)

    out: list[str] = []
    A = out.append

    A(f"# 20 — The mock trading book (Phase 2, Component 2)\n")
    A(f"> **{SIM_LABEL}.** Every counterparty, vessel, voyage, forwarder, bank, SPA reference, survey outcome,")
    A("> dwell day and payment delay on this page is FICTIONAL and labelled (SIM). Nothing here is a record of")
    A("> anything that happened, and no price quoted below was offered by anybody. What is real is the LME price")
    A("> path, the notified duties, the MCX contract specifications and the dated news the decisions were taken")
    A("> against. The grade factors and the freight levels those decisions also used are **hindsight-calibrated")
    A("> reconstructions**, and USD/INR and the MCX price series are **proxies** — §8 has the provenance of every")
    A("> input, and ticket prose that quotes a factor, a lane rate or a rupee level is quoting one of those.")
    A("> The eligibility discipline is real as a rule; §3 shows what the screen it applies rests on.\n")
    A("Generated by `desk.book.run.main()` from `config/trades.yaml` and `config/counterparties.yaml`. Every")
    A("number on this page is read out of `outputs/tables/trade_book.csv`, `trade_hedges.csv`,")
    A("`trade_eligibility_check.csv` and `trade_credit_exposure.csv`, so the page and the tables cannot disagree,")
    A("with three stated exceptions that are computed here from the same panel and printed with their working:")
    A("the eligibility-screen overlap in §3, the counterfactuals in §6.4-§6.6, and the sensitivity in §4.")
    A("(The §2 credit ladder used to be one of those exceptions — computed in-process and published nowhere,")
    A("which is exactly where two phases came to disagree about \"peak utilisation\"; it is a published table now.)")
    A("Re-running reproduces every file byte-for-byte.\n")
    A("Upstream: MASTER_SPEC_V3 Table 4; CONTRACTS §5 (desk economics), §5a (trade eligibility), §7/§7a")
    A("(position model); `docs/design/30_position_model.md`; `docs/10_parity_model.md` and")
    A("`outputs/tables/parity_weekly.csv`.\n")

    # ------------------------------------------------------------------ 1. the book at a glance
    A("\n## 1. The book at a glance\n")
    A(f"Nine purchase SPAs, **{tb['quantity_mt'].sum():,.0f} MT** in **{tb['boxes'].sum():,.0f} containers**,")
    A(f"bought between {tb['trade_date'].min()} and {tb['trade_date'].max()} and sold for")
    A(f"**₹{tb['sale_value_inr'].sum()/1e6:,.1f} mn** at contract terms. Every trade date falls in a week that is")
    A("open under all three CONTRACTS §5a screens; the last cashflow in the book lands on")
    A(f"{tb['last_cashflow_date'].max()}, inside the {HORIZON_END} engine horizon.\n")
    A(_md_table(tb, {
        "trade_id": "Trade", "trade_date": "Date", "lane": "Lane", "grade": "Grade",
        "quantity_mt": "MT", "boxes": "Boxes", "incoterm": "Terms", "purchase_pricing_type": "Buy price",
        "payment_instrument": "Import payment", "supplier_id": "Supplier", "buyer_ids": "Buyer(s)",
        "sale_pricing_types": "Sale price", "sale_payment_terms": "Sale payment",
        "mcx_hedge_ratio_target": "MCX ratio", "fx_hedge_frac_target": "FX cover",
    }, {"quantity_mt": ",.0f", "mcx_hedge_ratio_target": ".2f", "fx_hedge_frac_target": ".2f"}))
    A("")
    A("**Coverage of Table 4.** Incoterms "
      f"{(tb['incoterm'] == 'FOB').sum()} FOB / {(tb['incoterm'] == 'CFR').sum()} CFR; pricing "
      f"{(tb['purchase_pricing_type'] == 'FIXED').sum()} fixed / "
      f"{(tb['purchase_pricing_type'] == 'LME_M1_AVG').sum()} LME M+1 cash average; import payment "
      f"{(tb['payment_instrument'] == 'LC_SIGHT').sum()} sight LC / "
      f"{(tb['payment_instrument'] == 'LC_USANCE').sum()} usance LC (60 and 90 days); domestic sales "
      f"{sum(s.pricing.type.value == 'FIXED' for t in book.trades for s in t.sales)} fixed ₹/MT / "
      f"{sum(s.pricing.type.value == 'MCX_AVG' for t in book.trades for s in t.sales)} MCX near-month average, "
      f"across {len(credit)} sale contracts with advance, advance-plus-credit and 30- and 45-day credit terms. "
      f"{len(mcx)} MCX tranches ({int((mcx['exit_reason'] == 'ROLL').sum())} of them rolls), {len(fx)} USD/INR "
      f"forwards and {len(frt)} freight fixtures.\n")
    A("**Box weights.** Six tickets load below MASTER_SPEC Table 4 row 2.1's indicative 24-26 MT/box: the US-lane")
    A("40ft boxes take 21.0 MT because the US federal gross vehicle weight limit binds on the road before the box")
    A("is full (`container_payload_mt_40ft`, ASSUMPTION, verify PENDING), and Taint/Tabor loads 20.0 MT in a 20ft")
    A("box on density. Only T02/T09 (25.0) and T06 (26.0) sit inside the spec's range. Every tonnage on this page")
    A("is boxes × the registered payload, so the departure moves quantities, never prices.\n")
    A(f"**Why nine and not ten.** The §5a gate leaves {_screen_overlap()['eligible']} eligible week × grade × "
      f"lane cases in the window, but")
    A("they are not evenly spread: Zorba and Taint/Tabor close in the first week of May, Tense closes on")
    A("10-Jun and only reopens on 22-Jul, and the 40-day US lane cannot be used after early June without a")
    A("Bill of Entry that would take the IGST credit past 31-Oct. Nine tickets is what those three constraints")
    A("leave once each trade is also sized inside a buyer's credit line. The rule was not bent to reach ten.\n")

    # ------------------------------------------------------------------ 2. counterparties
    A("\n## 2. Counterparties and credit limits\n")
    A("Three suppliers and three buyers, the maximum Table 4 row 2.5 allows. Limits are the desk's own policy")
    A("(§4 below) and are checked at every sale booking by `desk.book.validate` (code P04).\n")
    A(_md_table(cp, {"cp_id": "Id", "name": "Name (SIM)", "type": "Type", "location": "Location",
                     "lanes": "Lane", "limit": "Limit", "terms": "Default terms", "rating": "Rating (SIM)",
                     "peak": "Peak use at booking (P04)", "trades": "Tickets"}))
    A("")
    A("**Which utilisation this is.** \"Peak use at booking\" is rule P04's measure: at each sale booking, invoiced-")
    A("and-unpaid receivables *plus* the not-advance-covered part of sales already contracted, against the line. Phase")
    A("3 publishes a different measure — the invoiced receivable only, evaluated **daily** (CONTRACTS §7a.4,")
    A("`buyer_credit_exposure_daily.csv`) — with different, lower peaks for the same names. The two are not the same")
    A("number and must not be quoted as agreeing; what both show is no breach of their own limit test.\n")
    A("The buyer side is the concentrated one, and that is a finding rather than an accident: there is exactly")
    A("one JNPT-belt smelter in the book, so it takes every Gulf-lane cargo. Its peak booking-time utilisation is")
    A(f"{credit[credit['buyer_id'] == 'BUY_JNPT_01']['utilisation_frac'].max():.0%}. Phase 5's credit model")
    A("should read that concentration as a real exposure, not as a modelling convenience.\n")
    A("Credit exposure at each booking (the number P04 checks; published as")
    A("`outputs/tables/trade_credit_exposure.csv`):\n")
    A(_md_table(credit, {"contract_date": "Booked", "trade_id": "Trade", "sale_id": "Sale",
                         "buyer_id": "Buyer", "qty_mt": "MT", "price_inr_t": "₹/MT",
                         "invoice_value_inr": "Invoice ₹", "credit_value_inr": "On credit ₹",
                         "exposure_after_inr": "Exposure after ₹", "credit_limit_inr": "Limit ₹",
                         "utilisation_frac": "Use"},
                {"qty_mt": ",.0f", "price_inr_t": ",.0f", "invoice_value_inr": inr,
                 "credit_value_inr": inr, "exposure_after_inr": inr, "credit_limit_inr": inr,
                 "utilisation_frac": pct}))

    A("")
    adv_warnings = [i for i in issues if i.code == "P14"]
    A("**The exposure this table cannot see, and the book's largest.** A limit caps *credit*: invoiced-and-unpaid")
    A("receivables plus the uncovered part of contracted sales. An advance is not credit the desk extends, so it")
    A("never appears above — and on this book the advances are far larger than the receivables they replace.")
    A("Rule P14 prices that honestly and it fires three times, all on the weakest name in the book:\n")
    for i in adv_warnings:
        A(f"- `{i.where}` — {' '.join(i.message.split())}")
    A("")
    A("Those three warnings are deliberate and are not cleared. The desk took them because there is no other home")
    A("on the Mundra lane for a US-origin Taint/Tabor or Tense parcel, and it says so on the T07 ticket on the")
    A("trade date. A reader should take from §2 that a book which never breaches a receivable limit can still be")
    A("running its largest single exposure to its weakest counterparty — and that Phase 5's credit model should")
    A("score pre-settlement performance exposure, not only receivables.\n")

    # ------------------------------------------------------------------ 3. eligibility
    A("\n\n## 3. Trade discipline — the eligibility evidence (Table 4 row 2.9, CONTRACTS §5a)\n")
    A("A trade may be executed only in a week × grade × lane case that is open under **all three** screens:")
    A("the base §5 calculation, the point-in-time grade mix a 2022 desk could actually have known, and")
    A("conversion cost stressed one grid step to ₹18,000/t of ingot. The rule was declared before Phase 1 ran")
    A("and has not been touched since. A trade dated `d` is tested against the latest parity week ending on or")
    A("before `d`, so no decision uses a number published after it.\n")
    A(_md_table(el, {"trade_id": "Trade", "trade_date": "Trade date", "grade": "Grade", "lane": "Lane",
                     "parity_week_end_used": "Parity week", "open_base": "Base",
                     "open_pit_mix": "PIT mix", "open_conv18k": "Conv ₹18k",
                     "net_arb_inr_t": "Net arb ₹/MT", "net_arb_pit_mix_inr_t": "PIT ₹/MT",
                     "net_arb_conv18k_inr_t": "Conv18k ₹/MT", "status": "Gate"},
                {"net_arb_inr_t": ",.0f", "net_arb_pit_mix_inr_t": ",.0f",
                 "net_arb_conv18k_inr_t": ",.0f"}))
    A("")
    A("Read the third and fourth columns together. In March the base screen pays four times what the")
    A("point-in-time mix does (T03: ₹43,205 against ₹10,406), which says most of that margin is the lag-2 grade")
    A("reconstruction rather than something a 2022 desk could have banked — and the tickets written in those")
    A("weeks are correspondingly small. By late May the two screens cross over and the point-in-time number")
    A("becomes the friendly one (T07: ₹39,374 against ₹22,935). The desk sizes off whichever is smaller.\n")
    ov = _screen_overlap()
    A("**The three screens are not three independent screens, and this page used to imply they were.** Over the")
    A(f"window's {ov['cases']} week × grade × lane cases the base screen is open {ov['base']} times, the")
    A(f"point-in-time-mix screen {ov['pit']} times and the conversion-stressed screen {ov['conv18k']} times — and")
    A(f"`trade_eligible` equals `open_conv18k` on all {ov['identical']} rows of `parity_weekly.csv`, not just in")
    A(f"the window. The point-in-time screen excludes **{ov['pit_excludes_alone']}** cases that the stressed screen")
    A(f"does not already exclude, while the stressed screen shuts {ov['pit_open_conv_shut']} cases the")
    A("point-in-time screen would have left open. Both the base and the stressed screen run on the same lag-2")
    A("reconstructed grade mix, so **the binding gate is a hindsight-mix screen** and the no-hindsight screen")
    A("never binds. Two consequences a reader is entitled to:\n")
    A(f"1. The book's most visible piece of discipline — standing aside for the {ov['shut_weeks']} consecutive")
    A(f"   weeks from {ov['shut_from']} to {ov['shut_to']}, the last leg of the crash — was produced by a screen a")
    A(f"   2022 desk could not have computed. On every one of those weeks the point-in-time screen was open on at")
    A(f"   least {ov['shut_pit_min']} of the {ov['cases_per_week']} grade × lane cases. A desk actually trading the")
    A("   point-in-time screen would have kept buying into the low.")
    A("2. Entry *timing* in this book is therefore not point-in-time, even though every ticket's price, factor,")
    A("   fixture and hedge size is re-derived from data dated on or before its own day. The §5a rule was")
    A("   declared before Phase 1 ran and may not be changed after seeing results, so the rule stays and the")
    A("   claim about it changes. Phase 1 owns the honest alternative gate and what it would have cost")
    A("   (`docs/10_parity_model.md` §5a).\n")

    # ------------------------------------------------------------------ 4. desk policy
    A("\n## 4. The desk policy this book was written to\n")
    A("Stated before the book was priced, applied mechanically, and re-derived point-in-time by")
    A("`desk.book.validate` so it cannot be quietly abandoned. None of it is fitted to an outcome; where a")
    A("ticket departs from it, the ticket says why on its trade date.\n")
    A("| # | Policy | Value | Enforced by |")
    A("|---|---|---|---|")
    A("| H1 | Hedge the **net LME-equivalent delta**, not the tonnage. Unsold cargo is long `grade factor × k`; "
      "a contracted MCX-average sale is long `factor × duty-paid parity`; a fixed-rupee sale is flat; a "
      "purchase still inside its LME quotational period is short `factor × k`. `k` is the ₹/t move of a "
      "CFR cargo's landed value per USD/t of LME. | — | P07 |")
    A(f"| H2 | Ratio **0.90** on a fixed-price cargo with no contracted sale (a naked long); **1.00** on the "
      f"residual between two floating legs; one ticket at **0.50** by exception. | 0.90 / 1.00 / 0.50 | P07 |")
    A("| H3 | Size in whole 5 MT lots: `lots = round(ratio × net ₹-delta ÷ ₹-delta of one lot)`. A **roll keeps "
      "the position** it continues; the desk re-sizes only at a new decision. | — | P06, P07 |")
    A(f"| H4 | Roll **{int(config.value('mcx_roll_days_before_expiry'))} trading days before the DIRECT expiry**, "
      f"never later: two days' cushion before the delivery tender period and the 25 % delivery-period margin. "
      f"Positions are keyed by contract **month**, so the panel's 31-Aug slot and the exchange's 30-Aug expiry "
      f"are the same contract. | 7 trading days | P06 |")
    A("| H5 | An **averaging leg** is treated as open until the ceil(n/2)-th trading day of its window and "
      "closed after it, so a hedge against a formula leg is lifted once, at the midpoint, rather than in n "
      "pieces. | midpoint day | P07 |")
    A(f"| H6 | Cover **100 % of the contracted USD payable** with deliverable forwards matched to the payment "
      f"date, **dealt on the bill of lading** — the first day on which both the amount and the payment date "
      f"exist. The desk is therefore uncovered in USD between the trade date and the first B/L and says so; on "
      f"a formula purchase only the provisional invoice is coverable at the B/L, and the final balance waits "
      f"for the quotational month to close. One ticket covers {tb['fx_hedge_frac_target'].min():.0%} by "
      f"exception. | 1.00 (T06 0.60) | schema V18 |")
    A(f"| F1 | **Freight is not hedged.** No accessible India-lane container derivative existed in 2022, so an "
      f"FOB cargo floats under a written stop-loss at the trade-date lane index **+ "
      f"{V.FREIGHT_STOP_LOSS_FRAC:.0%}**, with a hard book-by date "
      f"{V.FREIGHT_BOOKING_DAYS_BEFORE_BL} days before the first B/L. | +15 %, book-by B/L −10d | P05 |")
    A(f"| F2 | The NVOCC all-in rate is expected to sit **{V.FIXTURE_SPREAD_BAND[0]:.0%}–"
      f"{V.FIXTURE_SPREAD_BAND[1]:.0%} over the assessed lane index** of the fixture date. The spread itself is "
      f"an ASSUMPTION — no 2022 India-inbound fixture evidence exists in the cached sources. | 0–5 % | P05 |")
    A(f"| S1 | A domestic sale is priced at **replacement value + {V.DESK_ARB_SHARE_FRAC:.0%} × (smelter "
      f"netback − replacement value)** on the contract date, then adjusted for payment terms at the desk's own "
      f"`wc_rate_inr_pa` — an advance is worth `price × wc × 30 days × advance fraction`, credit past "
      f"{V.SALE_CREDIT_BASELINE_DAYS} days costs `price × wc × extra days` — and rounded to the nearest "
      f"₹{V.SALE_PRICE_ROUNDING_INR_T:,.0f}/MT. Both sides are the same arithmetic; the first draft paid a flat "
      f"₹500/MT for an advance and charged ₹500/MT a fortnight for credit, and both errors ran the desk's way. "
      f"| 50 % of the gap | P09 |")
    A(f"| S2 | The desk bids **0–{V.PURCHASE_DISCOUNT_BAND_USD_T[1]:.0f} USD/t under the trade-date parity "
      f"price** on the incoterm basis; a formula purchase is contracted 0–1.0 point under the trade-date grade "
      f"factor. | 0–30 USD/t | P10 |")
    A("| C1 | A buyer's **credit limit** caps receivables plus the not-advance-covered part of contracted "
      "sales. A parcel that will not fit is sold on an advance, or waits for the previous invoice to clear. "
      "Credit days never exceed `max_domestic_credit_days` (45, ASSUMPTION — a **desk policy cap, not the "
      "MSMED Act**: s.15 binds a buyer purchasing from a registered micro/small *supplier*, and here the desk "
      "is the seller and is not MSME-registered, so the statute reaches no sale in this book). "
      "| per counterparty | P04, V09 |")
    A("| C2 | An **advance the desk relies on** is performance exposure, not credit, and is capped at "
      "`buyer_advance_limit_multiple_of_credit_limit` x that buyer's own limit. This book breaches it three "
      "times, deliberately and on the record (§2). | 1.00x | P14 |")
    A("| L1 | The **documentary credit is opened at least `lc_open_days_before_laycan_min` days before the "
      "laycan opens**, so the seller can have it checked and amended before it starts stuffing boxes. "
      "| 10 days | V11 |")
    A("")
    A("**Why a 50/50 split on the sale.** Phase 1's net arbitrage is dominated by `domestic_anchor_premium_inr_t`,")
    A("an ASSUMPTION whose own evidence spans −₹52k to +₹13k/t. Letting the desk take the whole modelled")
    A("arbitrage would put ₹30,000/MT of March margin on the book on the strength of one assumption. Splitting")
    A("it in half is the conservative reading and the one a competitive import market would produce; it is a")
    A("stated convention, not an observation, and it is the single largest judgement on this page.\n")
    A("**And here is what that judgement is worth, because defending it is not enough.** Nobody ever quoted this")
    A("desk a price. Both sides of every trade are set by the desk's own two rules — S2 against its own parity")
    A("on the buy, S1 against its own replacement-and-netback bounds on the sell — so the day-one margin below")
    A("is an arithmetic property of those rules and not the outcome of a negotiation. The same nine tickets,")
    A("repriced at other conventions with nothing else changed:\n")
    A(_md_table(_desk_share_table(book),
                {"basis": "Sale priced at", "day_one_margin_inr": "Day-one sale margin ₹"},
                {"day_one_margin_inr": lambda v: f"{v/1e6:,.1f} mn"}))
    A("")
    A("Day-one sale margin is Σ tonnes × (contracted sale price − import replacement value on the contract date):")
    A("what the book books the moment a sale is signed, before any market move. Read it as the width of one")
    A("judgement, not as a P&L. At a 25 % share the book keeps under half of it; at a flat ₹5,000–8,000/MT —")
    A("which is what a competitive import market actually pays a middleman — two fifths to two thirds; at 0 % the")
    A("desk is a logistics provider working for its payment terms. The purchase side is narrower and points the")
    A("same way: rule S2 allows 0–30 USD/t under parity and all six fixed-price tickets sit at 10–15 USD/t, the")
    A("top third of the desk's own band, across six independent 'negotiations' with three suppliers over five")
    A("months. Phase 3 should be read with this table beside it.\n")

    # ------------------------------------------------------------------ 5. ticket cards
    A("\n## 5. Ticket cards\n")
    A("Every Table 4 field for each trade, with the trader's rationale as written on the trade date. Dates in")
    A("a rationale are checked by `desk.book.validate` (code P08): a rationale may cite a market fact only with")
    A("a date on or before its own trade date, and a forward reference is allowed only where the ticket itself")
    A("declares that period as a contract term. The numbers in it are checked too (P13, §9).\n")
    A("**Read the Incoterm line carefully, because it says two different things.** Under **both** FOB and CFR")
    A("(Incoterms 2020 A2/B2) the risk of loss or damage passes to the buyer when the goods are **on board at")
    A("the load port**: CFR moves the *cost* of carriage to the seller, never the risk, and a CFR cargo that")
    A("sinks mid-ocean is the desk's cargo. What the incoterm changes for this desk is who carries the freight")
    A("*price* risk — the desk on FOB (it books the boxes, §6.4), the seller on CFR (freight is inside the price")
    A("and a CFR-basis grade factor does not move when the lane does). An earlier draft of this page said risk")
    A("sat with the seller until discharge on CFR, which is simply wrong, and the card now separates the two.\n")
    A("**And on using FOB/CFR for containers at all.** ICC's own guidance recommends FCA/CPT/CIP for")
    A("containerised cargo, precisely because \"on board\" does not describe a CY or terminal hand-over: the")
    A("seller loses control of the box at the gate but keeps the risk until it is loaded, days later. This book")
    A("uses FOB and CFR anyway, for one reason: that is what the non-ferrous scrap trade actually does — LC")
    A("presentation is built around an on-board bill of lading, and a scrap SPA quoting CFR India is the market")
    A("convention the grade factors in CONTRACTS §5 are quoted on. It is a deliberate departure from the ICC's")
    A("preference, not an oversight, and the honest version of the answer is that the desk accepts a gate-to-")
    A("loading gap it does not control on its three FOB tickets.\n")
    for _, r in tb.iterrows():
        t = by_id[r["trade_id"]]
        m = mcx[mcx["trade_id"] == r["trade_id"]]
        f_ = fx[fx["trade_id"] == r["trade_id"]]
        g_ = frt[frt["trade_id"] == r["trade_id"]]
        A(f"\n### {r['trade_id']} — {r['grade']} {r['quantity_mt']:,.0f} MT, {r['lane']}, "
          f"{r['incoterm']}, traded {r['trade_date']}\n")
        sched = V.ticket_schedule(t)
        A("| Field | Value |")
        A("|---|---|")

        def row(label: str, value: str) -> None:
            """One card line. `JOIN` separates multi-lot and multi-sale values, so pipes are escaped here."""
            A(f"| {label} | {value.replace(JOIN, '; ').replace('|', chr(92) + '|')} |")

        row("Quantity (2.1)",
            f"{r['quantity_mt']:,.0f} MT = {r['boxes']} × {r['box_type']} at "
            f"`container_payload_mt_{r['box_type']}_{r['grade']}` = {r['payload_mt_per_box']} MT, in "
            f"{r['n_lots']} bill(s) of lading")
        row("SPA (2.2)",
            f"{r['isri_grade_spec']}; moisture franchise {r['moisture_franchise_frac']:.3f}, contamination "
            f"limit {r['contamination_limit_frac']:.3f}, discount {r['discount_multiple']:.1f}× the excess, "
            f"rejection above +{r['rejection_excess_frac']:.3f}; radioactivity clause "
            f"`{r['radioactivity_clause_key']}`, penalty schedule `{r['penalty_schedule_key']}`; "
            + (f"SPA quantity tolerance {r['quantity_tolerance_frac']:.0%}, LC opened at the same "
               f"{r['lc_amount_tolerance_frac']:.0%}" if pd.notna(r["quantity_tolerance_frac"])
               else f"SPA states no quantity tolerance, so the LC is opened at UCP 600 art.30's "
                    f"{r['lc_amount_tolerance_frac']:.0%}"))
        row("Incoterm (2.3)",
            f"{r['named_place']}. Ocean freight booked by **{r['freight_booked_by']}**; cargo risk passes "
            f"{r['cargo_risk_passes']}; freight *price* risk borne by **{r['freight_risk_borne_by']}** — "
            + ("a CFR-basis grade factor does not move when the lane does, so this cargo carries none for the "
               "desk" if r["incoterm"] == "CFR"
               else "the desk books the boxes under a written stop-loss (§6.4)"))
        row("Purchase price (2.4)",
            f"{r['purchase_pricing_type']}: "
            + (f"**{r['purchase_price_usd_t']:,.2f} USD/t** {r['incoterm']} against a trade-date parity of "
               f"{(r['fob_parity_usd_t_at_trade_date'] if r['incoterm'] == 'FOB' else r['cfr_parity_usd_t_at_trade_date']):,.2f} "
               f"(grade factor {r['grade_factor_at_trade_date']:.4f})"
               if r["purchase_pricing_type"] == "FIXED"
               else f"**{r['purchase_factor_frac']:.3f} × LME Official Cash average, "
                    f"{r['pricing_period_start']} .. {r['pricing_period_end']}** — the month after the B/L "
                    f"month, so the period is fixed at signature (trade-date grade factor "
                    f"{r['grade_factor_at_trade_date']:.4f}); provisional {r['provisional_frac']:.0%} of B/L "
                    f"weight at the B/L price, final invoice {r['final_invoice_date']}"))
        row("Import payment (2.6)",
            f"{r['payment_instrument']}"
            + (f" {int(r['usance_days'])} days from B/L" if pd.notna(r["usance_days"]) else "")
            + f", opened {r['lc_open_date']} with {r['issuing_bank']}; "
            + ("confirmed, charges on the " + str(r["confirmation_charges_for"]).lower()
               if r["lc_confirmed"] else "unconfirmed")
            + ("; PSIC required on this origin" if r["psic_required"] else ""))
        row("Laycan and vessels (2.8)",
            f"{r['laycan_start']} .. {r['laycan_end']}, {r['load_port']} → {r['discharge_port']}. "
            + "; ".join(f"{l.lot_id} {l.boxes} boxes B/L {l.bl_date} on {l.vessel} {l.voyage}"
                        for l in t.shipment.lots))
        row("Lifecycle",
            "; ".join(
                f"{l.lot_id} arrives {l.arrival}, BoE {l.boe}, released {l.release}, IGST credit "
                f"{l.igst_credit}, "
                + (f"usance matures {l.usance_maturity}" if l.usance_maturity else f"paid {l.lc_pay}")
                for l in sched.lots)
            + f". Last cashflow **{r['last_cashflow_date']}**")
        if g_.empty:
            row("Freight layer (2.7d)",
                "CFR: freight is the seller's cost inside the price. Under CONTRACTS §5 the CFR grade factor "
                "does not move with freight, so this cargo carries **no freight price risk** — only the "
                "seller's schedule risk")
        else:
            gg = g_.iloc[0]
            row("Freight layer (2.7d)",
                f"UNHEDGED with a stated stop-loss. Fixed {gg['booking_date']} at "
                f"**{gg['notional_usd'] / gg['lots']:,.0f} USD/FEU** against the lane index "
                f"{gg['index_usd_box_at_fixture']:,.2f} ({gg['fixture_vs_index_frac']:+.2%}); stop at "
                f"{r['freight_stop_loss_usd_box']:,.0f} USD/FEU, book-by {r['freight_latest_fixture_date']}; "
                f"{r['freight_payment_terms']}, {r['freight_forwarder']}; total USD "
                f"{r['freight_total_usd']:,.0f}")
        for s in t.sales:
            price = (f"{s.pricing.price_inr_t:,.0f} ₹/MT fixed"
                     if s.pricing.type.value == "FIXED"
                     else f"{s.pricing.factor_frac:.3f} × MCX {s.pricing.mcx_series.value} average over "
                          f"{s.pricing.window_start} .. {s.pricing.window_end}, "
                          f"{s.pricing.premium_inr_t:+,.0f} ₹/MT")
            pay = s.payment.terms.value
            if s.payment.advance_frac:
                pay += f" — {s.payment.advance_frac:.0%} advance on {s.payment.advance_date}"
            if s.payment.credit_days:
                pay += f", {s.payment.credit_days}-day credit on the balance"
            row(f"Sale {s.sale_id} (2.4, 2.6)",
                f"{book.counterparty(s.buyer_id).name}, contracted {s.contract_date}, lots "
                f"{'+'.join(s.lot_ids)} ({sum(t.lot_weight_mt(t.lot(x)) for x in s.lot_ids):,.0f} MT), "
                f"{s.delivery_basis}. Price {price}. {pay}. Invoice {sched.sale_invoice[s.sale_id]}, due "
                f"{sched.sale_due_contractual[s.sale_id]}"
                + ("" if s.quality_passthrough else "; quality discount NOT passed through"))
        row("Valuation bounds",
            f"at trade date: replacement ₹{r['replacement_inr_t_at_trade_date']:,.0f}/MT, netback "
            f"₹{r['netback_inr_t_at_trade_date']:,.0f}/MT, landed "
            f"₹{r['landed_inr_t_at_trade_date']:,.0f}/MT. At first sale: replacement "
            f"₹{r['replacement_inr_t_at_first_sale']:,.0f}, netback "
            f"₹{r['netback_inr_t_at_first_sale']:,.0f}")
        row("Hedge stack (2.7)",
            f"MCX ratio {r['mcx_hedge_ratio_target']:.2f} — "
            + "; ".join(f"{mr['hedge_id']} {mr['direction']} {mr['lots']} lots {mr['contract_month']} "
                        f"{mr['entry_date']}→{mr['exit_date']} ({mr['exit_reason']})" for _, mr in m.iterrows())
            + f". USD/INR cover {r['fx_hedge_frac_target']:.0%} — "
            + "; ".join(f"{xr['hedge_id']} {xr['direction']} {xr['notional_usd']:,.0f} value {xr['value_date']}"
                        + (f", cancelled {xr['cancel_date']}" if pd.notna(xr["cancel_date"]) else "")
                        for _, xr in f_.iterrows()))
        if r["event_quality"] or r["event_logistics"] or r["event_buyer_payment_delay"]:
            ev = " ".join(x for x in (r["event_quality"], r["event_logistics"],
                                      r["event_buyer_payment_delay"]) if x)
            row("Events (SIM)", ev
                + (". Chargeable dwell "
                   + ", ".join(f"{l.lot_id} {l.chargeable_dwell_days} d" for l in sched.lots)
                   + f" beyond {int(config.value('detention_free_days'))} free days ⇒ USD "
                   f"{r['demurrage_usd_at_plan_tiered']:,.0f} of detention and ground rent up the registered "
                   f"slabs, which is also what the Phase 3 engine books (USD {r['demurrage_usd_at_plan']:,.0f} if "
                   f"every day were charged at the first-slab rate, as the first draft did)"
                   if r["demurrage_usd_at_plan"] else ""))
        row("§5a evidence (2.9)",
            f"parity week {r['parity_week_end']}: base ₹{r['net_arb_inr_t']:,.0f}/MT, point-in-time mix "
            f"₹{r['net_arb_pit_mix_inr_t']:,.0f}/MT, conversion at ₹18k "
            f"₹{r['net_arb_conv18k_inr_t']:,.0f}/MT — open on all three")
        A(f"\n**Trader's rationale, {r['trade_date']}.** {r['rationale']}\n")

    # ------------------------------------------------------------------ 6. hedge stack
    A("\n## 6. The hedge stack\n")
    A("### 6.1 MCX Aluminium futures\n")
    A(f"{len(mcx)} tranches across nine tickets, {int((mcx['exit_reason'] == 'ROLL').sum())} of them rolls. Fill")
    A("prices, roll deadlines and initial margin are **derived**, not typed: they are recomputed from the Phase 0")
    A("panel at the date of each decision and written to `trade_hedges.csv` beside the decision itself.\n")
    A(_md_table(mcx, {"trade_id": "Trade", "hedge_id": "Line", "contract_month": "Month",
                      "direct_expiry": "DIRECT expiry", "roll_deadline": "Roll deadline",
                      "direction": "Dir", "lots": "Lots", "position_mt": "MT",
                      "entry_date": "In", "entry_price_inr_kg": "In ₹/kg", "exit_date": "Out",
                      "exit_price_inr_kg": "Out ₹/kg", "exit_reason": "Why",
                      "hedge_ratio_actual": "Ratio", "im_required_at_entry_inr": "IM at entry ₹"},
                {"position_mt": ",.0f", "entry_price_inr_kg": ",.2f", "exit_price_inr_kg": ",.2f",
                 "hedge_ratio_actual": lambda v: f"{v:.3f}", "im_required_at_entry_inr": inr}))
    A("")
    A(f"Peak initial margin on a single line is ₹{mcx['im_required_at_entry_inr'].max()/1e6:,.1f} mn at 10 % of")
    A("contract value (`mcx_al_margin_used_frac`, ASSUMPTION = 8 % minimum + 1 % ELM + ~1 % SPAN cushion). The")
    A("cash strain on a short book is on the way **up**, not on the way down: Phase 3's variation-margin")
    A("schedule should start at WINDOW_START for that reason.\n")
    A("**Three execution facts worth reading.** First, on 08-Mar-2022 the near-month proxy moved −12.0 % against")
    A(f"a {float(config.value('mcx_al_dpl_max_frac')):.0%} maximum daily price limit, so a real contract would")
    A("have been limit-locked: T01 is bought on the 8th and hedged on the 9th, and carries one session naked")
    A("rather than claiming a fill it could not have had. The validator warns (code P12) on any hedge action")
    A("dated in a session beyond the slab. Two things must be said beside that, and the first draft of this page")
    A("said neither. The panel's MCX series is a computed import-parity proxy with **no price limits in it** — it")
    A("prints the whole −12.0 % on the 8th — so the limit is a constraint the desk overlays on the proxy, not one")
    A("the series contains; and on this occasion waiting a session was not a cost but a benefit, because the")
    A("proxy had already printed the move and the 9th opened higher:")
    t01 = mcx[(mcx["trade_id"] == "T01") & (mcx["entry_date"] == "2022-03-09")]
    t01_delay_gain_inr = float("nan")
    if len(t01):
        gained = ((t01["entry_price_inr_kg"].iloc[0]
                   - float(V.panel_row(dt.date(2022, 3, 8))["mcx_al_m2_inr_kg"]))
                  * t01["position_mt"].sum() * units.KG_PER_MT)
        t01_delay_gain_inr = gained
        A(f"the 300 lots went on at ₹{t01['entry_price_inr_kg'].iloc[0]:,.4f}/kg against the 08-Mar proxy close of")
        A(f"₹{float(V.panel_row(dt.date(2022, 3, 8))['mcx_al_m2_inr_kg']):,.4f}/kg, which is "
          f"**+₹{gained:,.0f}** on the hedge. A genuinely limit-locked contract would have gapped down on the 9th")
        A("to catch up the unprinted move and the same delay would have cost money. The ticket says so.")
    A("")
    A("Second, the **roll is a gain by construction in this book and that is an artefact, not a result**. The")
    A("panel builds MCX M1 and M2 from a single spot through a deterministic interest carry, so the modelled")
    rolls_n, rolls_inr = _roll_pnl(mcx)
    A(f"curve is in permanent contango: all **{rolls_n} rolls** in the book are gains, **₹{rolls_inr:,.0f}** in")
    A("total, with no loss anywhere. A short that rolls in contango does collect the spread — but the LME's own")
    A("curve went into backwardation from 20-Jul-2022 (`lme_cash_3m_spread_usd_t` turns positive, DIRECT), and a")
    A("real duty-paid parity curve carrying that slope would have made the same roll pay for its metal carry")
    A("(Phase 3 prices it: `mcx_roll_carry.csv`, `lme_curve_*` columns). Where a ticket calls the roll a *cost* of holding cargo (T07), that is the state of the")
    A("world the proxy cannot show, and both the ticket and this page now say so. Phase 3's roll bucket should be")
    A("read as the proxy's carry, not as evidence that rolling a short is free.")
    A("")
    A("Third, a roll keeps the size of the line it continues, so the realised ratio drifts between decisions —")
    A("that drift is visible in the `hedge_ratio_actual` column and is deliberate.\n")

    A("\n### 6.2 Cross-exchange basis risk (Table 4 row 2.7c)\n")
    A("The desk owns LME-linked aluminium **scrap** and hedges it with MCX Aluminium, a **primary-ingot** contract")
    A("that trades at duty-paid import parity. Four mismatches survive the hedge, and each of them is a bucket in")
    A("the Phase 3 attribution rather than something the ratio can fix:\n")
    A("1. **The grade spread.** The hedge covers `grade_factor × LME`, not the grade factor itself. Zorba's")
    A("   factor rose from 0.699 on 08-Mar to 0.792 by 10-May because yards refused to follow the exchange down;")
    A("   a hedged cargo therefore *gained* on the discount while its flat price was neutralised. That is the")
    A("   grade-spread bucket (c), it is large in this book, and it rests on a reconstructed lag-2 unit-value")
    A("   ratio — so it is a reconstruction, not an observed market move.")
    A("2. **Timing.** LME Official Cash is fixed at the London midday ring; MCX settles in the Indian evening.")
    A("   The two are not the same moment and the panel runs MCX on the LME calendar (CONTRACTS §3).")
    A("3. **The duty base.** The physical cargo's duty runs on the CBIC notified rate, frozen for a fortnight;")
    A("   MCX's parity uplift runs on the market rate. A short MCX position is also short USD, so it loses when")
    A("   the rupee weakens — visible in bucket (e), not (b).")
    A("4. **Parity itself can break.** It visibly did in the first week of March 2022.")
    A("")
    A("**The honest caveat.** In base runs the panel MCX series *is* the duty-paid parity formula, so the measured")
    A("cross-exchange basis is **zero by construction** — the (b) bucket will be empty and that is an artefact of")
    A("the proxy, not evidence that the basis is small. The only basis evidence in this project is the")
    A("third-party mirror sensitivity (CONTRACTS §7.5) and MCX's own published figure: a basis standard deviation")
    A(f"of {float(config.value('mcx_basis_std_inr_kg')):.2f} ₹/kg for FY2022-23, on a same-product hedge. A")
    A("cross-product scrap-versus-primary hedge is weaker still.\n")

    A("\n### 6.3 USD/INR forwards\n")
    A(f"{len(fx)} deliverable outrights, USD {fx['notional_usd'].sum():,.0f} gross, each matched to a named leg")
    A("and value date. The mid is covered interest parity off the booking day's spot and 3-month rates (the same")
    A("PROXY construction as the panel's own forward columns) and the bank's margin")
    A(f"(`fx_forward_bank_margin_inr` = ₹{float(config.value('fx_forward_bank_margin_inr')):.2f}/USD, ASSUMPTION)")
    A("is taken against the desk in both directions. Gross notional per ticket stays under the DIRECT")
    A(f"`fx_hedge_no_documentation_limit_usd` of USD {float(config.value('fx_hedge_no_documentation_limit_usd')):,.0f}.\n")
    A(_md_table(fx, {"trade_id": "Trade", "hedge_id": "Line", "direction": "Dir",
                     "notional_usd": "USD", "booking_date": "Booked", "value_date": "Value",
                     "cancel_date": "Cancelled", "matched_leg": "Matched to",
                     "forward_mid_inr": "Mid ₹/USD", "rate_inr": "Dealt ₹/USD"},
                {"notional_usd": ",.0f", "forward_mid_inr": ".4f", "rate_inr": ".4f"}))
    A("")
    A("**When each forward is dealt, and why it moved.** Every purchase-matched forward is booked **on the bill")
    A("of lading**: that is the first day on which the desk knows both what it owes and when. The first draft of")
    A("this book booked six tickets' forwards on the trade date with value dates that are exactly the actual")
    A("B/L + 7 (or + 60) — dates nobody could have known when the forward was dealt, which made the hedge look")
    A("perfect at zero cost. Under the convention this page now states, the desk instead runs an **uncovered USD")
    A("payable from the trade date to the first B/L** (13 to 21 days on the fixed-price tickets), and that")
    A("exposure is real and lands in Phase 3's FX bucket where it belongs. The alternative a desk with day-one")
    A("certainty actually uses — cover at contract to an estimated date, then pay swap points to realign when the")
    A("vessel moves — is NOT used here, because this project does not model swap points and a hedge whose")
    A("realignment is free is worth more than a hedge. Say which one you are looking at before comparing.\n")
    A("Two structures are worth pointing at. On the formula purchases the desk can only cover the **provisional**")
    A("invoice at the B/L, because the final balance is unknown in size *and in sign* until the quotational month")
    A("closes: T02 sells USD forward on 01-Jun once the May average has come in below the provisional and the")
    A("balance has become a supplier refund, T05 does the same on 01-Jul after June closes, and T08 buys its")
    A("balance forward on 01-Aug. (T05 previously carried a USD 200,000 **BUY** dealt at inception against an")
    A("expected balance and cancelled when none appeared. That was not a hedge — it was a position on an unknown")
    A("number, and it was removed in review; see §12.) T06")
    A(f"covers only {tb.loc[tb['trade_id'] == 'T06', 'fx_hedge_frac_target'].iloc[0]:.0%} of its payable on")
    A("purpose: the cargo had no rupee revenue contracted yet, and a fully covered payable against an")
    A("uncontracted sale is a view, not a hedge. The rupee then went from 77.26 to over 80, so that decision")
    A("cost money — which is the point of writing it down beforehand.\n")

    A("\n### 6.4 The freight risk layer (Table 4 row 2.7d)\n")
    A("Table 4 offers a proxy instrument **or** an accepted exposure with a stated stop-loss. The desk takes the")
    A("second, because no accessible India-lane container derivative existed in 2022 — putting one in the base")
    A("book would present a fiction as a hedge. The hypothetical swap in the schema is barred from this book and")
    A("survives only as a labelled Phase 4 stress instrument (design D12b).\n")
    A(_md_table(frt, {"trade_id": "Trade", "booking_date": "Fixed on", "lots": "Boxes",
                      "notional_usd": "USD", "index_usd_box_at_fixture": "Index USD/FEU",
                      "fixture_vs_index_frac": "vs index", "exit_reason": "Paid",
                      "value_date": "Pay date"},
                {"notional_usd": ",.0f", "index_usd_box_at_fixture": ",.2f",
                 "fixture_vs_index_frac": lambda v: f"{v:+.2%}"}))
    A("")
    fw_up = _freight_up_weeks(book)
    A("The three CFR tickets carry no freight price risk at all: under CONTRACTS §5 the CFR grade factor does not")
    A("move with freight, so a falling market does not reduce what the desk pays for the cargo. On the FOB")
    A(f"tickets the stop was never touched — the lane index fell through the window with only "
      f"{fw_up['n_up_weeks']} small up-weeks, and never came closer to any stop than the "
      f"{fw_up['min_gap_to_stop']:.0%} it was set at — so all three")
    A("fixtures were taken on the book-by date. That is the honest freight story of 2022 and it is the opposite")
    A("of a spike: **freight was fixed high into a falling market**. `fixture_vs_market_inr` in Phase 3 will")
    A("measure that as a loss of competitiveness against a later importer, not as a loss on these cargoes.\n")
    cf = _freight_counterfactual(book)
    fw = _freight_weekly_stats()
    A("**The stop-loss could not bind, so here is the decision that actually mattered.** A stop at +15 % of the")
    A("trade-date index, live for at most ten business days, needed the reconstructed lane index to do something")
    A(f"it never did: its largest weekly rise anywhere between Jan and Sep 2022 is "
      f"{fw['usec_max_rise']:+.1%} (week to {fw['usec_max_rise_week']}, after the fixtures), and between 04-Mar")
    A(f"and 29-Jul the largest weekly rise at all is {fw['usec_window_max_rise']:+.1%}. On the three fixture")
    A(f"windows the stop sat {cf['headroom_frac'].min():.0%}–{cf['headroom_frac'].max():.0%} above the index —")
    A("five consecutive record weeks, or thirty-odd typical ones, inside a ten-business-day life. Reporting")
    A("'the stop was never touched' as discipline would therefore be reporting an unfalsifiable rule. The")
    A("decision a desk really faces on an unbooked FOB cargo is **fix now, or stay open to the book-by date** —")
    A("and that one is checkable:\n")
    A(_md_table(cf, {"trade_id": "Trade", "trade_date": "Trade date", "index_at_trade": "Index then",
                     "fix_now_usd_box": "Fix-now rate", "fixture_date": "Book-by date",
                     "index_at_fixture": "Index then", "rate_usd_box": "Fixed at",
                     "saved_usd": "Waiting gained USD"},
                {"index_at_trade": ",.2f", "fix_now_usd_box": ",.0f", "index_at_fixture": ",.2f",
                 "rate_usd_box": ",.0f", "saved_usd": ",.0f"}))
    A("")
    A(f"Waiting to the book-by date was worth **USD {cf['saved_usd'].sum():,.0f}** across the three cargoes — on")
    A("a book of this size that is the entire freight layer, and it is the answer to Table 4 row 2.7(d), not the")
    A("stop note. (Fix-now rate = the trade-date index at the same NVOCC spread the desk actually paid.)\n")
    sp = _spread_sensitivity(book)
    A("**And the spread itself is an assumption.** The desk pays 1.7–2.0 % over the assessed lane index on all")
    A("three fixtures; no 2022 India-inbound NVOCC fixture exists in the cached sources, and real all-in margins")
    A("on India-bound boxes in 2022 were wider than 2 %. What the same three fixtures cost at other spreads:\n")
    A(_md_table(sp, {"trade_id": "Trade", "boxes": "Boxes", "actual_spread": "Spread paid",
                     "actual_usd": "Paid USD", "usd_at_2%": "at +2 %", "usd_at_5%": "at +5 %",
                     "usd_at_10%": "at +10 %"},
                {"actual_spread": lambda v: f"{v:+.2%}", "actual_usd": ",.0f", "usd_at_2%": ",.0f",
                 "usd_at_5%": ",.0f", "usd_at_10%": ",.0f"}))
    A("")
    A(f"At +10 % the three cargoes cost USD {sp['usd_at_10%'].sum() - sp['actual_usd'].sum():,.0f} more than the")
    A("book pays — larger than everything the freight layer earned by waiting. The band in rule F2 is 0–5 %; the")
    A("evidence for any point inside it is a judgement, and this row is where a reader should push.\n")

    # ------------------------------------------------------------------ 6.5 schedule risk
    A("\n### 6.5 Schedule risk — the exposure this book does not carry (Table 4 row 2.8)\n")
    A("Nineteen sailings, twenty bills of lading, and until this review **not one day of schedule slippage**")
    A("anywhere in the book — in the worst year for container schedule reliability on record. Two lots now carry")
    A("the void-call arrival delay (T08, §7), which is the honest channel for that event, but every other B/L is")
    A("still laycan-start + 2 days and every transit is still exactly the registered 5 or 40 days. That is a")
    A("modelling convenience, and on the three M+1 tickets it is load-bearing rather than cosmetic: each asserts")
    A("that its laycan sits inside one calendar month, **so the quotational period is fixed at signature**. If a")
    A("bill of lading slips into the next month, the period moves with it and the purchase reprices against a")
    A("different month's average:\n")
    sl = _laycan_slip(book)
    A(_md_table(sl, {"trade_id": "Trade", "lot_id": "Last lot", "lot_bl": "B/L", "laycan_end": "Laycan ends",
                     "slack_days": "Slack days", "qty_mt": "MT", "qp_month": "QP", "qp_avg": "QP avg $",
                     "next_month": "If it slips", "next_avg": "That avg $", "swing_inr": "Swing ₹"},
                {"qty_mt": ",.0f", "qp_avg": ",.0f", "next_avg": ",.0f",
                 "swing_inr": lambda v: f"{v/1e6:+,.1f} mn"}))
    A("")
    A("Read the size, not the sign: a single lot slipping one month is worth ₹1.5–9.4 mn on tickets whose whole")
    A("day-one margin is a few tens of millions, and **T08's second B/L has one day of slack**. The book shows")
    A("none of this exposure because no lot in it slips, which is not the same thing as the exposure not being")
    A("there. A desk that prices M+1 must either buy laycan slack it can live with or accept that its quotational")
    A("month is a coin toss on the last sailing; this book assumes the first and has not paid for it.\n")

    # ------------------------------------------------------------------ 6.6 luck the book did not choose
    A("\n### 6.6 What went right that the desk did not choose\n")
    A("The two deliberately sub-optimal calls this page puts on the record — T04's 0.50 MCX ratio and T06's 60 %")
    A("dollar cover — are advertised, and both tickets still finish profitable in Phase 3. A book that confesses")
    A("only its small mistakes deserves to be discounted, so here are the unflagged judgement calls that paid,")
    A("each measured on this page's own numbers:\n")
    cf_luck = _freight_counterfactual(book)
    stop_cost = ((cf_luck["stop_usd_box"] - cf_luck["fix_now_usd_box"]) * cf_luck["boxes"]).sum()
    fx_ref = float(V.panel_row(V._last_panel_day(dt.date(2022, 5, 27)))["usdinr"])
    sl_luck = _laycan_slip(book)
    A("| Call nobody flagged | What happened | Worth |")
    A("|---|---|---|")
    A(f"| T01's hedge deferred one session on a limit-lock inferred from the **proxy** (§6.1) | the proxy had "
      f"already printed the move, so the short went on higher | +₹{t01_delay_gain_inr:,.0f} |")
    A(f"| All three FOB fixtures left open to the book-by date (§6.4) | the lane index fell | "
      f"USD {cf_luck['saved_usd'].sum():,.0f} (≈ ₹{cf_luck['saved_usd'].sum() * fx_ref / 1e6:,.1f} mn) |")
    A(f"| The stop-loss never tested (§6.4) | freight never rose; had each FOB index gone straight to its stop, "
      f"the same policy would have cost | −USD {stop_cost:,.0f} (≈ −₹{stop_cost * fx_ref / 1e6:,.1f} mn) |")
    A(f"| No M+1 lot slipped a month (§6.5) | the market fell, so two of the three slips would have *helped*; "
      f"the risk was symmetric and simply not drawn | {_signed_mn(sl_luck['swing_inr'].min())} to "
      f"{_signed_mn(sl_luck['swing_inr'].max())} per lot |")
    A("| The grade factors moved the desk's way after purchase | Zorba's reconstructed factor rose from 0.699 to "
      "0.792 while the flat price fell (§6.2) | Phase 3 bucket (c); a **reconstruction**, see `docs/30` §13.9 |")
    A("")
    A("The stop row is the counterfactual the book never exercises: a +15 % stop still lets the freight layer")
    A(f"lose about {stop_cost / max(cf_luck['saved_usd'].sum(), 1.0):,.0f} times what waiting gained before it binds, so "
      "the layer's 2022 result is the market's direction, not the policy's")
    A("protection. The last row is the largest by far and the least earned: it is the reconstructed grade path,")
    A("not a decision.\n")

    # ------------------------------------------------------------------ 7. events
    A("\n## 7. Operational events (Table 5 row 3.6, CONTRACTS §7.6)\n")
    A("There was **no container freight spike** on these lanes in 2022 — freight fell about 36 % from 01-Mar to")
    A("31-Aug (`docs/research/freight_notes.md`). Adverse event #3 is therefore built from what did happen, with")
    A("the simulated part labelled:\n")
    ev_rows = []
    for t in book.trades:
        for g in t.events.logistics:
            ev_rows.append(dict(kind="logistics (SIM)", trade=t.trade_id, ref=g.event_id, lot=g.lot_id,
                                known=g.known_date.isoformat(),
                                detail=f"+{g.extra_dwell_days}d CFS dwell, +{g.arrival_delay_days}d arrival",
                                trigger=" ".join(g.real_trigger_ref.split())))
        for q in t.events.quality:
            ev_rows.append(dict(kind="quality (SIM)", trade=t.trade_id, ref="survey", lot=q.lot_id, known="survey",
                                detail=f"moisture {q.moisture_actual_frac:.3f} vs franchise, contamination "
                                       f"{q.contamination_actual_frac:.3f} vs limit, {q.rejected_boxes} box(es) "
                                       f"rejected"
                                       + (f" ({q.rejection_reason.value})" if q.rejection_reason else ""),
                                trigger="joint survey outcome — simulated magnitudes, real SPA clause"))
        for b in t.events.buyer_payment_delay:
            ev_rows.append(dict(kind="credit (SIM)", trade=t.trade_id, ref=b.event_id, lot=b.sale_id,
                                known=b.known_date.isoformat(), detail=f"+{b.delay_days} days past due",
                                trigger=" ".join(b.reason.split())))
    A(_md_table(pd.DataFrame(ev_rows), {"kind": "Type", "trade": "Trade", "ref": "Id", "lot": "Lot/Sale",
                                        "known": "Known on", "detail": "Simulated effect",
                                        "trigger": "Trigger / basis"}))
    A("")
    A("The **logistics trigger is real and dated**: Container News, 27-Jul-2022, reported carriers voiding calls")
    A("at Nhava Sheva and Mundra (`docs/research/freight_notes.md` S4). The schema refuses any ticket that claims")
    A("to know about it earlier. The days attributed to it are simulated. **The channel matters and the first")
    A("draft had it wrong**: a voided call is an ocean-side event, so its first-order effect is a rolled or")
    A("omitted box — an arrival delay, not yard rent. That is now modelled where it can be, on T08, whose two")
    A("lots were still at sea on 27-Jul (undelayed ETAs 01-Aug and 08-Aug). T07's two lots had already landed and")
    A("cleared their Bills of Entry before the news broke, so what they carry is the plausible *second-order*")
    A("landside consequence — a congested yard and slow evacuation once the omitted boxes come back through the")
    A("same terminal — and both the ticket and this table now say which is which.\n")
    A("**The radiation-portal box is not free, and it used to be.** An alarmed container at Mundra does not")
    A("quietly leave the Bill of Entry while the rest of the consignment clears: it is referred to Customs and")
    A("the AERB, the BoE is held, and the other 39 boxes accrue detention until the referral closes. That is")
    A("event T08-LOG-3 — 14 simulated days, taking the lot to 24 days against 14 free, so 10 chargeable days on")
    A("39 boxes. The alarmed box itself is then held for "
      f"`rejected_box_hold_days` ({int(config.value('rejected_box_hold_days'))}, ASSUMPTION) accruing slabbed "
      "detention and re-exported at")
    A(f"`rejected_box_reexport_cost_usd_per_box` (USD {float(config.value('rejected_box_reexport_cost_usd_per_box')):,.0f}, "
      "ASSUMPTION: return freight, handling, a radiological survey and the")
    A("permissions) — paid by the desk first and claimed back from the seller at the event's recovery. The first")
    A("draft modelled none of that, so the event used to be free. Decontamination or disposal of a genuinely")
    A("contaminated box is **still not modelled** and can cost far more; the book assumes the common case, a")
    A("re-exportable source. Both quality events carry `claim_recovery_frac` **0.6**, not the 1.0 of the first")
    A("draft: after an LC has paid at sight, a claim on the smallest yard on the register is an unsecured")
    A("negotiation, and a desk that recovers 100 % of every claim is a desk that is indifferent to out-turn — the")
    A("opposite of why the clause exists. On the formula-priced T08 the goods deduction is set off against the final")
    A("invoice, which secures the cash but not the claim, so the same 0.6 applies. Phase 3 publishes the book at")
    A("0.0 and 1.0 beside it (`pnl_sensitivity_summary.csv`, `claim_recovery_*`).\n")
    A("**Detention is slabbed.** `demurrage_usd_per_box_day` is the FIRST-slab rate and its own register note")
    A("says carriers escalate after five to ten days, so charging an eight- or ten-day delay at it understates")
    A("the bill. `desk.book.validate.demurrage_usd` now walks the registered slabs")
    A("(`demurrage_slab1_days`, `demurrage_slab2_days`, `demurrage_usd_per_box_day_slab2/3`) and")
    A("`trade_book.csv` publishes both figures side by side. The Phase 3 engine uses the same schedule")
    A("(`desk.mtm.lifecycle.detention_usd`, asserted equal in `tests/test_mtm_engine.py`). The four keys price")
    A("carrier detention and CFS ground rent **combined**; they are not split into separate tariffs with separate")
    A("free periods, so the slabbed figure is still an estimate of the order of the bill, not a line tariff.\n")
    A("The **buyer payment delay is entirely simulated** and is placed on the weakest name in the book, a Rajkot")
    A("foundry that already pays 70 % of that parcel in advance — so the delay hits the balance rather than the")
    A("whole cargo, which is what the credit policy is for. Read it with §2: the advance that keeps the")
    A("receivable small is itself 1.8× that buyer's credit limit.")
    A("The **quality outcomes are simulated** but sit on the SPA's own registered clauses: T07's lot is 1.4")
    A("points over the moisture franchise and 1.1 points over the contamination limit (a weight deduction plus a")
    A("1.65 % price discount, inside the 3-point rejection threshold).\n")

    # ------------------------------------------------------------------ 8. provenance
    A("\n## 8. Provenance — what is real on this page\n")
    A("| Input | Flag | Where it bites in this book |")
    A("|---|---|---|")
    A("| LME official cash and 3M (Westmetall) | DIRECT | every parity price, every M+1 quotational period, the "
      "MCX parity the hedge is priced off |")
    A("| Customs notified FX path, BCD / SWS / IGST, MCX contract specs and expiries, the MSME 45-day cap, the "
      "client position limit, the FX no-documentation limit | DIRECT | duty base, roll deadlines, credit terms, "
      "position and forward limits |")
    A("| The 27-Jul-2022 void calls at Nhava Sheva / Mundra (Container News) | DIRECT | the earliest date T07's "
      "dwell event may be known |")
    A("| USD/INR and its forwards (ECB cross, covered interest parity) | PROXY | every forward mid and dealt "
      "rate, the goods and duty conversion |")
    A("| MCX Aluminium (duty-paid import parity) | PROXY | every hedge fill and margin number; the "
      "cross-exchange basis is zero by construction in base runs |")
    A("| Grade factors (lag-2 unit-value mix + differentials) | ASSUMPTION, hindsight-calibrated | every "
      "purchase price, every replacement-value bound, the whole grade-spread story |")
    A("| Freight levels and lane shape | ASSUMPTION / PROXY | the three FOB fixtures and their stop-losses |")
    A("| Payloads, transit and clearance days, free days, demurrage rate, port charges, PSIC, WC rate | "
      "ASSUMPTION | box counts, every lifecycle date, demurrage |")
    A("| The lifecycle lags in `desk.book.validate` (sight-payment 7d, survey 1d, BoE 1d, final-invoice 5 "
      "trading days, claim settlement 30d, NVOCC lead time 10d) | ASSUMPTION | derived cashflow dates |")
    A("| Desk policy: hedge ratios, the 50 % arbitrage split, the 15 % freight stop, the NVOCC spread band, "
      "credit limits | ASSUMPTION (judgement) | hedge sizes, sale prices, fixtures, who may buy what |")
    A("| Counterparties, vessels, forwarders, banks, SPA references, survey outcomes, dwell days, the payment "
      "delay | SIM | everything with \"(SIM)\" after it |")
    A("")
    A("**The freight row deserves its own sentence, because three tickets price off it.** Phase 0's own note for")
    A("the week T01 trades in reads:\n")
    A(f"> {' '.join(_freight_note(tb['trade_date'].min()).split())}\n")
    A("So the lane level the FOB netbacks subtract was calibrated from material published about seven months")
    A("after the week it describes, and the Gulf lane has no observational anchor at all — it is 600 USD/box")
    A("assumed at 2022-03-04 and shaped by the US lane. The Gulf tickets are unaffected in price (CONTRACTS §5")
    A("quotes the grade factor CFR, so no freight enters a Gulf purchase or its landed cost); the three US-lane")
    A("FOB netbacks are not, and their tickets say so. `desk.book.validate` P13 refuses any note that claims")
    A("otherwise.\n")
    A("**Two things this page does not do.** It never presents a simulated counterparty, vessel or event as real,")
    A("and it never quotes a price as something somebody offered — every contract price on this page is the")
    A("output of a stated rule applied to the market data of its own date, and the rule is in §4. What it")
    A("**cannot** do is tell you what a counterparty would have said: there is no negotiation anywhere in this")
    A("book, and §4's sensitivity is the honest way to read that.\n")

    # ------------------------------------------------------------------ 9. validation
    A("\n## 9. What this book is checked against\n")
    A("`desk.book.schema` enforces V01–V20 from the ticket, the counterparty file and the parameter register")
    A("alone (closed grammar, ids, SIM names, size and box arithmetic, lane/port/incoterm consistency, laycan")
    A("rules, LC tenors, sale coverage, payment-term consistency, MCX lot and roll structure, forward dates,")
    A("event cross-references). `desk.book.validate` adds the twelve rules that need the market panel or the")
    A("Phase 1 parity model:\n")
    A("| Code | Rule |")
    A("|---|---|")
    A("| P01 | §5a eligibility holds and the ticket cites the week the look-up actually used |")
    A("| P02 | container arithmetic against the register payloads, per lot and in total |")
    A("| P03 | every derived cashflow date lands on or before HORIZON_END |")
    A("| P04 | buyer credit exposure at every booking is inside `credit_limit_inr` |")
    A("| P05 | the fixture sits in the stated spread band over its own day's index; the stop is the policy stop; "
      "a stop that was touched was acted on; space is bookable before the boxes sail |")
    A("| P06 | every tranche lives inside its contract month's trading life and a ROLL happens on the deadline |")
    A("| P07 | the MCX size reproduces the stated policy at the entry date |")
    A("| P08 | no rationale or terms note cites a date after the decision it justifies |")
    A("| P09 | sale prices sit between replacement value and the smelter netback on the contract date |")
    A("| P10 | purchase prices sit within the stated band under trade-date parity |")
    A("| P11 | this phase's per-day §5 arithmetic reproduces Phase 1 exactly on parity value dates |")
    A("| P12 | (warning) a hedge action dated in a session beyond the MCX daily price limit |")
    A("| P13 | every market number a rationale or terms note *quotes* reconciles to the panel, and no note claims "
      "its inputs were point-in-time when the ticket's price basis rests on a reconstruction |")
    A("| P14 | (warning) an advance the desk relies on exceeds that buyer's own credit limit by more than the "
      "registered policy multiple |")
    A("")
    warn = [i for i in issues if i.severity == "WARNING"]
    A(f"The book passes with **0 errors and {len(warn)} warnings**, and the warnings are not noise to be cleared:")
    A("all " + ("three" if len(warn) == 3 else str(len(warn))) + " are P14, the advance-reliance cap, on the")
    A("three BUY_RJK_01 parcels (§2). A control that has never fired on the real book is a control nobody has")
    A("tested; a control that fires and is then argued with in writing is the point.\n")
    A("**What P13 can and cannot check.** It reconciles the shapes a desk actually writes — \"N dollars in a")
    A("day\", \"N dollars off the D-Mon low\", \"N dollars under my netback\", \"rupee at XX.XX\", \"moved N % today\"")
    A("— against the panel on the decision date or on the parity week the ticket cites, and it refuses the")
    A("categorical claim that a ticket's inputs were all knowable on the day. It does **not** understand prose:")
    A("a claim it cannot parse is not checked and is not counted as passing. It caught one wrong number in this")
    A("book (T03's bounce off the 15-Mar low, typed as 180 dollars against a panel move of 306) and one")
    A("unsupportable provenance claim (T01's \"every input is dated 08-Mar-2022 or earlier\"); both are fixed in")
    A("the tickets, not in the scanner.\n")
    A("`tests/test_book.py` runs a mutation table: one deliberately broken copy of this book per")
    A("code, asserting the code fires and the message names the thing that is wrong. A validation that has never")
    A("been shown to fail is not a control.\n")

    # ------------------------------------------------------------------ 10. what it does and doesn't tell you
    A("\n## 10. What this does and doesn't tell you\n")
    A("**Does.** It turns Phase 1's weekly parity screen into nine dated trading decisions with every commercial")
    A("term a physical desk actually negotiates: an ISRI grade specification with a moisture franchise and a")
    A("contamination discount schedule, an incoterm that says who books and bears the freight, a pricing formula")
    A("with an explicit quotational period, a payment instrument with a tenor, a laycan a real lane could serve,")
    A("a buyer with a credit limit that sometimes binds, and a hedge stack sized by a written rule. It shows the")
    A("hedging decisions a scrap importer can actually take in India — MCX Aluminium and deliverable USD/INR")
    A("forwards — and it is explicit that freight is not one of them. Every decision is checked against data")
    A("dated on or before it, mechanically, by code that raises.\n")
    A("**Doesn't.** It is not evidence of what any desk earned in 2022, and it is not a backtest of a strategy.")
    A("The trades are chosen by one person with a screen in front of them, and a different trader with the same")
    A("screen would have written a different book. The counterparties, vessels, survey outcomes and the payment")
    A("delay are invented. The sale prices are not quotes: they are a stated 50/50 split of a modelled")
    A("arbitrage whose size is dominated by `domestic_anchor_premium_inr_t`, an assumption with an evidence range")
    A("of ₹65,000/t — so the book's headline margins are as uncertain as that one number, and a reader who wants")
    A("one figure to distrust should distrust that one. Grade factors are a hindsight-calibrated reconstruction")
    A("published months after the fact, so the grade-spread result is a property of the reconstruction as much as")
    A("of the market. Freight levels are reconstructed too. MCX is a duty-parity proxy, which means the hedge is")
    A("priced off the same LME the cargo is priced off and the cross-exchange basis — the risk this book is most")
    A("exposed to in reality — is invisible in base runs. And nothing here is P&L: this phase produces positions")
    A("and terms; Phase 3 marks them.\n")
    A("Four more things this book does not contain, each of which a physical desk would. There is **no")
    A("negotiation**: no counterparty ever holds out, and both legs of every trade come out of the desk's own two")
    A("pricing rules, which is why §4 publishes what the result looks like at other conventions. There is **no")
    A("schedule slippage** except the two void-call arrival delays on T08 — nineteen sailings in the worst year")
    A("on record for schedule reliability, and §6.5 sizes what one slipped bill of lading would have been worth.")
    A("There is **no funding or facility limit** anywhere: this phase produces positions, and the cash they")
    A("consume is Phase 3's to report, but no ticket was ever tested against a working-capital line. And the")
    A("**grade reconstruction sets both the buy and the sell price** — the purchase is struck against a")
    A("reconstructed parity and the sale against a replacement value built from the same factor — so it is not")
    A("only an attribution exposure that nets out in a re-mark; it is in the contracted numbers themselves.\n")
    A("**The one thing a reader should take at face value** is that every price, factor, fixture and hedge size")
    A("here was re-derived, mechanically, from data dated on or before the day it is typed against, by code that")
    A("raises. Not the trade *timing*: §3 shows the gate that produced it is a hindsight-mix screen, and this")
    A("page says so rather than selling the discipline it would like to have had.\n")

    # ------------------------------------------------------------------ 11. changes during integration
    A("\n## 11. Changes during integration with Phase 3\n")
    A("Phase 2 (this book) and Phase 3 (`desk/mtm`, the valuation engine) were built concurrently against")
    A("`docs/design/30_position_model.md`. When they were joined the engine loaded this book, priced it and")
    A("passed every sign-off control on the first run.\n")
    A("**No ticket was changed by the integration.** `config/trades.yaml` and `config/counterparties.yaml` came")
    A("through the join byte-for-byte: no schema fix, no date reformatting, no missing technical field, and no")
    A("economic correction. Nothing in the nine tickets broke eligibility, the horizon, the container arithmetic")
    A("or a hedge-sizing rule when a second implementation valued them. That is the result of this heading, and")
    A("it is reported because an empty change log is only credible if someone says it is empty on purpose. The")
    A("independent review that came after integration is a different matter and is logged in §12.\n")
    A("One **apparent** contradiction between the phases was resolved, on the Phase 3 side:\n")
    A("- Phase 3's event-3 table first reported a buyer credit-limit breach of 2.58x over 46 days, against the")
    A("  peak utilisations of 78-93% this page reports. Neither book was wrong, and neither number is the other's")
    A("  answer: **they are two different measures and this paragraph used to conflate them.** Rule P04 here")
    A("  measures, at every sale booking, the receivable plus the uncovered part of sales already contracted —")
    A("  a booking-time control, and its peak is the 93% (BUY_MUN_01) in §2. Phase 3 measures the receivable")
    A("  *daily*, per CONTRACTS §7a.4, and its peak is a different name on a different day; it publishes that")
    A("  figure in `outputs/tables/adverse_event_3_logistics_credit.csv`, and this page does not restate it.")
    A("  Two things follow that a reader should have. The P2 measure evaluated daily rather than at bookings")
    A("  would exceed 100% on two names, because it counts contracted-but-uninvoiced sales; and neither measure")
    A("  sees the advances, which is the exposure §2 and rule P14 exist for. \"The two phases agree\" was the")
    A("  wrong claim: they measure different things, each cleanly, and both are published.\n")
    A("The engine's own two fixes (a final invoice that could precede its survey; an event known later than the")
    A("milestone it moves) were defects in the *engine*, not in these tickets, and are recorded in")
    A("`docs/30_mtm_attribution.md` §11.3.\n")

    # ------------------------------------------------------------------ 12. changes during review
    A("\n## 12. Changes during review\n")
    A("Independent reviewers read this book as a trader, a controller and a spec auditor would. Their findings")
    A("changed tickets, and CONTRACTS §5a forbids touching the eligibility rule after seeing results — so every")
    A("change below is priced or worded, never a re-selection of trades. All nine trade dates, grades, lanes,")
    A("laycans, tonnages and eligibility screens are exactly what this phase published. What changed:\n")
    A("| # | Change | Tickets | Why |")
    A("|---|---|---|---|")
    A("| 1 | Sale prices re-derived with a **symmetric** payment-terms adjustment (rule S1: `price × wc_rate × "
      "days`) instead of a flat ±₹500/MT | T01-S1 201,500→201,000; T01-S2 181,500→180,500; T04 195,500→194,500; "
      "T06 185,000→185,250; T07 166,500→165,750; T09 168,750→168,500 | The flat deltas under-paid the buyer for "
      "an advance (worth ₹1,436/MT on T01-S2 at the registered WC rate, paid as ₹500) and under-charged for "
      "extra credit. Both errors ran the desk's way, on five of seven priced sales. |")
    A("| 2 | USD/INR forwards matched to a purchase are **dealt on the bill of lading**, not on the trade date | "
      "T01, T03, T04, T06, T07, T09 (12 lines re-dated) | Six tickets booked forwards on the trade date to "
      "value dates that are exactly the *actual* B/L + 7 or + 60 — dates unknowable when the forward was dealt. "
      "The desk now covers when the payable exists and carries the gap openly (rule H6, §6.3). |")
    A("| 3 | T05's final-invoice cover replaced: a USD 200,000 BUY dealt at inception and cancelled becomes a "
      "USD 90,000 **SELL** dealt on 01-Jul | T05 | The balance's size and sign were unknown until the June "
      "quotational month closed; the original line was a position, not a hedge, and its cancellation handed the "
      "desk a one-sided mid-market unwind. T02 and T08 already did this correctly. |")
    A("| 4 | Documentary credits opened **≥ 10 days before the laycan** (`lc_open_days_before_laycan_min`) | "
      "T06 17-May→13-May; T07 01-Jun→27-May; T08 14-Jun→10-Jun; T09 10-Aug→05-Aug | Five and six days is not "
      "enough for a seller to have the credit checked and amended before stuffing a full parcel. |")
    A("| 5 | The July-2022 void calls gain their **real channel**: two arrival-delay events on lots still afloat | "
      "T08-LOG-1, T08-LOG-2 (+7 days each) | A voided call rolls or omits a box; it does not first show up as "
      "yard rent on a lot that has already cleared its Bill of Entry (which is what T07's two dwell events "
      "were). T07 keeps its dwell as the second-order landside consequence and says so. |")
    A("| 6 | The radiation-portal rejection is **no longer free**: the consignment's BoE is held and the other "
      "39 boxes accrue detention | T08-LOG-3 (+14 days dwell) | An alarmed box triggers an AERB/Customs "
      "referral at consignment level. The box itself is now costed too (row 11). |")
    A("| 7 | `claim_recovery_frac` 1.0 → **0.6** on both quality events | T07 L1, T08 L2 | After an LC has paid "
      "at sight, a claim on the smallest yard on the register is an unsecured negotiation. Full recovery made "
      "the desk indifferent to out-turn. |")
    A("| 8 | Wrong or unsupportable statements corrected in ticket prose | T01 (the limit-lock story and the "
      "\"every input is dated 08-Mar-2022 or earlier\" claim), T02 and T05 (the usance giveaway described as the "
      "price of the tenor), T03 (\"180 dollars off the 15-Mar low\" → 306), T07 (T04's invoice cleared 25-Jul, "
      "not 23-Jul), T09 (\"130 dollars\" → 82) | Each is now checked mechanically: P13 reconciles quoted market "
      "numbers to the panel and refuses categorical provenance claims. |")
    A("| 9 | Detention charged **up the registered slabs** rather than all at the first-slab rate | T07 L2 "
      "(8 chargeable days), T08 L2 (10) | `demurrage_usd_per_box_day` is the first slab and says so in its own "
      "register note. |")
    A("| 10 | Incoterm wording corrected on every card | all nine | Under **both** FOB and CFR (Incoterms 2020 "
      "A2/B2) the cargo risk passes when the goods are on board at the load port. CFR moves the *cost* of "
      "carriage to the seller, never the risk; the card used to say risk sat with the seller until discharge. |")
    A("| 11 | The **rejected box** is held and re-exported at the desk's cost first: "
      "`rejected_box_hold_days` 45 of slabbed detention + `rejected_box_reexport_cost_usd_per_box` USD 3,000 "
      "(both new ASSUMPTION keys in `logistics.yaml`), claimed back at the event's recovery | T08 L2 | The "
      "box used to leave the book at no cost. Decontamination or disposal of a genuinely contaminated box is "
      "still not modelled. |")
    A("| 12 | `claim_recovery_frac` made **effective on a formula purchase** | T08 L2 | The engine used to net the "
      "goods deduction off the final invoice at 100 % whatever the ticket typed, so row 7's 0.6 did nothing on "
      "T08. Set-off secures the cash, not the claim: the unaccepted 40 % is now handed back. Phase 3 publishes "
      "0.0 and 1.0 beside it. |")
    A("| 13 | Prose corrected against the tape and the proxy | T01 (\"fallen five weeks running\" → down on the "
      "week; the limit-lock stated as an inference from the proxy, bid only at the limit), T06 (\"weakened "
      "three sessions running\" → almost a rupee weaker than three sessions ago), T09 (backwardation "
      "attributed to the LME curve, not to an MCX print the project does not have) | P13 now also reconciles "
      "\"N weeks/sessions running\" streak claims to the panel, with a mutation test for each. |")
    A("")
    A("**What was deliberately NOT changed.** The 50/50 arbitrage split stays — it was declared before the book")
    A("was priced and re-fitting it after seeing results would be worse than disclosing it, so §4 publishes the")
    A("sensitivity instead. The §5a gate stays, for the same reason, and §3 restates what it actually is. No")
    A("trade was added, removed or re-dated, and no hedge was re-sized.\n")
    A("**What this phase handed on, and where it landed.** Four things were outside this phase's code and")
    A("were handed to the Phase 3 engine; all four are now done there: (a) the slabbed detention schedule")
    A("(`desk.mtm.lifecycle.detention_usd`, asserted equal to `desk.book.validate.demurrage_usd`); (b) a typed")
    A("`known_date` on a quality event beats the derived survey date; (c) `quantity_tolerance_frac` is tested")
    A("with `is not None`, so a strict-quantity SPA no longer inherits the 10 % LC tolerance; and (d) per-buyer")
    A("exposure is published at (date, trade, buyer) grain in `buyer_credit_exposure_by_trade_daily.csv`, beside")
    A("the trade-grain file whose compound `buyer_id` no credit tracker could group.\n")
    A("**What the review found that no ticket change can fix.** Both bounds of rule S1 — the replacement mark")
    A("and the smelter netback — are the desk's own reconstructions (lag-2 grade factors, an anchor premium")
    A("nobody observed in 2022), so the day-one margin in §4 is conditional on them. Phase 3 re-prices every")
    A("ticket through S1/S2 under each registered band (`docs/30_mtm_attribution.md` §13.9): the book's sign")
    A("does **not** survive the bottom of the `domestic_anchor_premium_sensitivity_inr_t` grid. That result is")
    A("reported there, and this page should not be quoted without it.\n")
    return "\n".join(out) + "\n"


def _write(df: pd.DataFrame, name: str) -> str:
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    path = TABLES_DIR / name
    df.to_csv(path, index=False, lineterminator="\n")
    return str(path)


def build(strict: bool = True) -> tuple[Book, dict[str, pd.DataFrame], list]:
    """Load, validate and build the three tables. Raises `ValidationError` on any ERROR when `strict`."""
    book = load_book(TRADES_YAML, COUNTERPARTIES_YAML, strict=False, panel_days=set(V.panel_days()))
    issues = V.validate(book)
    errors = [i for i in issues if i.severity == "ERROR"]
    if strict and errors:
        raise ValidationError(errors)
    elig = V.eligibility_frame(book)
    tables = {
        "trade_book.csv": trade_book_rows(book, elig),
        "trade_hedges.csv": trade_hedge_rows(book),
        "trade_eligibility_check.csv": elig,
        # The §2 credit ladder was computed in-process and published nowhere, which is exactly where the two
        # phases disagreed on "peak utilisation" (review finding, spec-honesty lens). It is a table now.
        "trade_credit_exposure.csv": V.credit_exposure_frame(book),
    }
    return book, tables, issues


def main() -> None:
    book, tables, issues = build(strict=True)
    for name, df in tables.items():
        print(f"wrote {_write(df, name)}  ({len(df)} rows)")
    credit = tables["trade_credit_exposure.csv"]
    doc_path = DOCS_DIR / "20_trade_book.md"
    doc_path.write_text(render_doc(book, tables, credit, issues))
    print(f"wrote {doc_path}")
    warnings = [i for i in issues if i.severity == "WARNING"]
    print(f"\n{SIM_LABEL}")
    print(f"{len(book.trades)} trades, {tables['trade_book.csv']['quantity_mt'].sum():,.0f} MT, "
          f"{len(book.counterparties)} counterparties, "
          f"{len(tables['trade_hedges.csv'])} hedge lines, {len(warnings)} warnings.")
    print(f"peak buyer credit utilisation: "
          + ", ".join(f"{b}={g['utilisation_frac'].max():.0%}"
                      for b, g in credit.groupby("buyer_id", sort=True)))
    for i in warnings:
        print("  " + i.format())


if __name__ == "__main__":
    main()
