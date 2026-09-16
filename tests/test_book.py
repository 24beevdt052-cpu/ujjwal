"""Phase 2 — the mock trading book (`config/trades.yaml`, `desk.book.validate`, `desk.book.run`).

`tests/test_book_schema.py` already proves the grammar is closed and that each rule V01–V20 fires on its own
break. This module tests the other half: that the *book* — the nine real tickets, not the fixture — obeys the
rules that need the market panel and the Phase 1 parity model, and that each of those rules would catch its own
break if the book ever drifted.

The mutation table is again the substance. A validation that has never been shown to fail is not a control, so
every P-code below has a deliberately broken copy of the real book asserting the code fires and the message
names the thing that is wrong.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib

import pandas as pd
import pytest
import yaml

from desk import HORIZON_END, WINDOW_END, WINDOW_START, config
from desk.book import run as book_run
from desk.book import schema
from desk.book import validate as V
from desk.paths import CONFIG_DIR, PROCESSED_DIR, TABLES_DIR

TRADES = CONFIG_DIR / "trades.yaml"
CPS = CONFIG_DIR / "counterparties.yaml"
PARITY_CSV = TABLES_DIR / "parity_weekly.csv"
PANEL_CSV = PROCESSED_DIR / "market_daily.csv"

pytestmark = pytest.mark.skipif(not PANEL_CSV.exists() or not PARITY_CSV.exists(),
                                reason="Phase 0 panel / Phase 1 parity outputs missing")


# ------------------------------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def panel_days() -> set[dt.date]:
    return set(V.panel_days())


@pytest.fixture(scope="module")
def book(panel_days) -> schema.Book:
    return schema.load_book(TRADES, CPS, strict=False, panel_days=panel_days)


@pytest.fixture(scope="module")
def issues(book) -> list[schema.Issue]:
    return V.validate(book)


@pytest.fixture(scope="module")
def raw() -> dict:
    return yaml.safe_load(TRADES.read_text())


@pytest.fixture(scope="module")
def raw_cps() -> dict:
    return yaml.safe_load(CPS.read_text())


def _mutated(raw_doc: dict, tmp_path, panel_days, raw_cps_doc: dict | None = None,
             strict_schema: bool = False) -> list[schema.Issue]:
    """Load a mutated copy of the book and return only the panel/parity issues (P-codes)."""
    tp = tmp_path / "trades.yaml"
    tp.write_text(yaml.safe_dump(raw_doc, sort_keys=False))
    cp = tmp_path / "counterparties.yaml"
    cp.write_text(yaml.safe_dump(raw_cps_doc, sort_keys=False) if raw_cps_doc else CPS.read_text())
    b = schema.load_book(tp, cp, strict=False, panel_days=panel_days)
    return V.validate(b, strict_schema=strict_schema)


def _codes(items) -> set[str]:
    return {i.code for i in items if i.severity == "ERROR"}


def _ticket(raw_doc: dict, trade_id: str) -> dict:
    return next(t for t in raw_doc["trades"] if t["trade_id"] == trade_id)


# ------------------------------------------------------------------------------------- the book itself is valid
def test_book_is_labelled_a_simulation():
    head = TRADES.read_text()[:600]
    assert "ACADEMIC SIMULATION" in head
    assert "ACADEMIC SIMULATION" in CPS.read_text()[:600]


def test_book_loads_and_validates_clean(issues):
    errors = [i for i in issues if i.severity == "ERROR"]
    assert errors == [], "\n".join(i.format() for i in errors)


def test_book_has_eight_to_ten_trades(book):
    """MASTER_SPEC Table 4: 8–10 trades. Fewer would be allowed only if §5a left no eligible cases."""
    assert 8 <= len(book.trades) <= 10
    assert [t.trade_id for t in book.trades] == [f"T0{i}" for i in range(1, 10)]


def test_every_trade_is_eligible_under_all_three_screens(book):
    """CONTRACTS §5a is the whole trade-discipline rule: base AND point-in-time mix AND conversion at ₹18k."""
    frame = V.eligibility_frame(book).set_index("trade_id")
    for t in book.trades:
        r = frame.loc[t.trade_id]
        assert WINDOW_START <= t.trade_date <= WINDOW_END
        assert r["open_base"] and r["open_pit_mix"] and r["open_conv18k"], t.trade_id
        assert r["trade_eligible"] and r["status"] == "PASS"
        assert r["week_matches_ticket"], f"{t.trade_id} cites the wrong parity week"
        assert r["net_arb_conv18k_inr_t"] > 0


def test_eligibility_table_carries_the_parity_numbers(book):
    frame = V.eligibility_frame(book)
    for col in ("net_arb_inr_t", "net_arb_pit_mix_inr_t", "net_arb_conv18k_inr_t", "margin_threshold_inr_t",
                "parity_lme_3m_usd_t", "parity_grade_factor", "parity_mcx_anchor_inr_kg"):
        assert frame[col].notna().all(), col
    parity = pd.read_csv(PARITY_CSV, parse_dates=["week_end"])
    for _, r in frame.iterrows():
        want = parity[(parity["week_end"] == pd.Timestamp(r["parity_week_end_used"]))
                      & (parity["grade"] == r["grade"]) & (parity["lane"] == r["lane"])].iloc[0]
        assert r["net_arb_inr_t"] == pytest.approx(float(want["net_arb_inr_t"]), abs=0.01)
        assert r["net_arb_conv18k_inr_t"] == pytest.approx(float(want["net_arb_conv18k_inr_t"]), abs=0.01)


# ------------------------------------------------------------------------------------------ Table 4 coverage
def test_quantities_and_container_arithmetic(book):
    """Table 4 row 2.1: 1,000–5,000 MT, and containers ship whole at the grade's payload."""
    for t in book.trades:
        assert schema.MIN_TRADE_MT <= t.quantity_mt <= schema.MAX_TRADE_MT
        payload = float(config.value(f"container_payload_mt_{t.box}_{t.grade.value}", t.trade_date))
        assert t.boxes * payload == pytest.approx(t.quantity_mt, abs=1e-9)
        assert sum(l.boxes for l in t.shipment.lots) == t.boxes


def test_incoterm_and_freight_responsibility_mix(book):
    """Table 4 row 2.3: a mix, and the freight block says who books and bears it."""
    terms = [t.purchase.incoterm for t in book.trades]
    assert terms.count(schema.Incoterm.FOB) >= 2 and terms.count(schema.Incoterm.CFR) >= 2
    for t in book.trades:
        if t.purchase.incoterm is schema.Incoterm.FOB:
            assert t.freight is not None and t.freight.booked_by and t.freight.risk_layer is not None
        else:
            assert t.freight is None


def test_pricing_formula_mix_and_stated_periods(book):
    """Table 4 row 2.4: fixed AND LME M+1 average with an explicit period and reference, tied to Table 1.7."""
    types = [t.purchase.pricing.type for t in book.trades]
    assert types.count(schema.PurchasePricingType.FIXED) >= 2
    assert types.count(schema.PurchasePricingType.LME_M1_AVG) >= 2
    for t in book.trades:
        if t.purchase.pricing.type is schema.PurchasePricingType.LME_M1_AVG:
            sched = V.ticket_schedule(t)
            assert t.purchase.pricing.lme_reference is schema.LmeReference.CASH
            assert sched.qp_month is not None and sched.pricing_start < sched.pricing_end
            # the quotational period is the month AFTER the B/L month, and is known on the trade date
            bl_month = (t.shipment.laycan_start.year, t.shipment.laycan_start.month)
            qp = (sched.pricing_start.year, sched.pricing_start.month)
            assert qp == ((bl_month[0], bl_month[1] + 1) if bl_month[1] < 12 else (bl_month[0] + 1, 1))
            assert sched.pricing_start > t.trade_date
    sale_types = [s.pricing.type for t in book.trades for s in t.sales]
    assert schema.SalePricingType.FIXED in sale_types and schema.SalePricingType.MCX_AVG in sale_types
    for t in book.trades:
        for s in t.sales:
            if s.pricing.type is schema.SalePricingType.MCX_AVG:
                assert s.pricing.mcx_series is schema.McxSeries.M1
                assert s.contract_date <= s.pricing.window_start < s.pricing.window_end <= HORIZON_END


def test_counterparties_and_credit_limits(book):
    """Table 4 row 2.5: 2–3 suppliers and 2–3 buyers, each with a ₹ credit limit that feeds Phase 5."""
    suppliers = [c for c in book.counterparties if c.role is schema.Role.SUPPLIER]
    buyers = [c for c in book.counterparties if c.role is schema.Role.BUYER]
    assert 2 <= len(suppliers) <= 3 and 2 <= len(buyers) <= 3
    assert all(b.credit_limit_inr and b.credit_limit_inr > 0 for b in buyers)
    assert all(s.claims_exposure_limit_usd and s.claims_exposure_limit_usd > 0 for s in suppliers)
    assert {c.country for c in suppliers} == {"AE", "US"}, "a Jebel Ali trader and US east-coast sellers"
    assert all(c.country == "IN" for c in buyers)
    assert any("Rajkot" in b.location for b in buyers), "the Rajkot cluster takes the Mundra cargo"
    assert any(b.lanes == (schema.Lane.JEA_NSA,) for b in buyers), "a JNPT-belt buyer for the Gulf lane"
    used_suppliers = {t.purchase.supplier_id for t in book.trades}
    used_buyers = {s.buyer_id for t in book.trades for s in t.sales}
    assert used_suppliers == {c.cp_id for c in suppliers}
    assert used_buyers == {c.cp_id for c in buyers}


def test_payment_terms_mix(book):
    """Table 4 row 2.6: LC sight and 60–90d usance on imports; advance and <= 45d credit on domestic sales."""
    instruments = [t.purchase.payment.instrument for t in book.trades]
    assert schema.PaymentInstrument.LC_SIGHT in instruments
    usance = [t.purchase.payment.usance_days for t in book.trades if t.purchase.payment.usance_days]
    assert usance and all(60 <= u <= 90 for u in usance)
    assert len(set(usance)) >= 2, "more than one usance tenor in the book"
    terms = [s.payment.terms for t in book.trades for s in t.sales]
    assert schema.SalePaymentTerms.ADVANCE in terms
    assert schema.SalePaymentTerms.CREDIT in terms
    assert schema.SalePaymentTerms.ADVANCE_PLUS_CREDIT in terms
    cap = int(config.value("msme_max_payment_days"))
    credits = [s.payment.credit_days for t in book.trades for s in t.sales if s.payment.credit_days]
    assert credits and max(credits) <= cap and max(credits) == cap, "the book uses the policy cap at least once"


def test_hedge_stack_is_complete_per_trade(book):
    """Table 4 row 2.7: MCX with a ratio and roll dates, USD/INR forwards, a basis note, a freight layer."""
    for t in book.trades:
        assert t.hedges.mcx.tranches, f"{t.trade_id} has no MCX hedge"
        assert t.hedges.mcx.hedge_ratio_target is not None
        assert len(t.hedges.mcx.basis_risk_note.split()) > 40, f"{t.trade_id}: row 2.7(c) needs a real note"
        assert t.hedges.fx_forwards.lines and t.hedges.fx_forwards.hedge_frac_target is not None
        if t.freight is not None:
            assert t.freight.risk_layer is schema.FreightRiskLayer.UNHEDGED_STOP_LOSS
            assert t.freight.stop_loss is not None and t.freight.stop_loss.note.strip()
    directions = {tr.direction for t in book.trades for tr in t.hedges.mcx.tranches}
    assert directions == {schema.HedgeDirection.SELL, schema.HedgeDirection.BUY}
    rolls = [tr for t in book.trades for tr in t.hedges.mcx.tranches
             if tr.exit_reason is schema.HedgeExitReason.ROLL]
    assert len(rolls) >= 6, "a six-month book on a 40-day lane rolls many times"
    assert any(x.cancel_date for t in book.trades for x in t.hedges.fx_forwards.lines)


def test_no_hypothetical_freight_swap_in_the_base_book(book):
    """design D12b: the proxy freight swap is a labelled stress instrument, never part of the book."""
    assert all(t.freight is None or t.freight.swap is None for t in book.trades)
    assert V.validate(book, strict_schema=True) == V.validate(book, strict_schema=True)


def test_book_carries_a_deliberate_partial_hedge_with_a_reason(book):
    """The brief asks for at least one deliberately part-hedged ticket, reasoned on the trade date."""
    partial_mcx = [t for t in book.trades if t.hedges.mcx.hedge_ratio_target < 0.75]
    partial_fx = [t for t in book.trades if t.hedges.fx_forwards.hedge_frac_target < 0.9]
    assert partial_mcx and partial_fx
    for t in partial_mcx:
        assert "0.50" in t.hedges.mcx.basis_risk_note or "half" in t.hedges.mcx.basis_risk_note.lower()
        assert "margin" in t.hedges.mcx.basis_risk_note.lower()
    for t in partial_fx:
        assert "cover" in t.rationale.text.lower()


def test_vessels_forwarders_and_banks_are_simulated(book):
    for t in book.trades:
        for lot in t.shipment.lots:
            assert lot.vessel.endswith(schema.SIM_SUFFIX)
            assert lot.voyage.endswith(schema.SIM_SUFFIX)
        assert t.purchase.payment.issuing_bank.endswith(schema.SIM_SUFFIX)
        if t.freight is not None:
            assert t.freight.forwarder.endswith(schema.SIM_SUFFIX)
    assert all(c.name.endswith(schema.SIM_SUFFIX) and c.flag is schema.Flag.SIM for c in book.counterparties)


def test_laycans_are_consistent_with_transit_and_horizon(book):
    """Table 4 row 2.8 and CONTRACTS §7.1: a laycan the lane can actually serve inside the horizon."""
    for t in book.trades:
        sched = V.ticket_schedule(t)
        span = (t.shipment.laycan_end - t.shipment.laycan_start).days
        assert 0 < span <= schema.MAX_LAYCAN_SPAN_DAYS
        assert t.shipment.laycan_start >= t.trade_date
        transit = int(config.value(V.LANE_SPEC[t.lane]["transit_key"], t.trade_date))
        for l in sched.lots:
            assert l.arrival >= l.bl_date + dt.timedelta(days=transit) - dt.timedelta(days=1)
            assert l.release >= l.arrival
        assert sched.last_cashflow <= HORIZON_END, t.trade_id


def test_freight_fixture_is_priced_against_the_index_of_its_own_day(book):
    """Table 4 row 2.8: the fixture rate vs the proxy index at the fixture date, and the spread is ASSUMPTION."""
    hedges = book_run.trade_hedge_rows(book)
    fix = hedges[hedges["instrument"] == "FREIGHT_FIXTURE"]
    assert len(fix) == sum(1 for t in book.trades if t.freight is not None)
    for _, r in fix.iterrows():
        assert 0.0 <= r["fixture_vs_index_frac"] <= 0.05
        assert r["weakest_input_flag"] == "ASSUMPTION"
        index = V._freight_index_usd_box(dt.date.fromisoformat(r["booking_date"]),
                                         schema.Lane(book.trade(r["trade_id"]).lane.value))
        assert r["index_usd_box_at_fixture"] == pytest.approx(index, abs=0.01)


# ---------------------------------------------------------------------------- operational events (Table 5 3.6)
def test_operational_events_for_adverse_event_three(book):
    """CONTRACTS §7.6: a simulated buyer payment delay, demurrage anchored to the real July-2022 void calls,
    and at least one quality outcome outside the SPA franchise."""
    delays = [b for t in book.trades for b in t.events.buyer_payment_delay]
    assert delays, "event #3 needs a buyer payment delay"
    assert all(b.flag is schema.Flag.SIM and b.delay_days > 0 for b in delays)

    logistics = [(t, g) for t in book.trades for g in t.events.logistics]
    assert logistics
    for t, g in logistics:
        assert g.known_date >= schema.VOID_CALL_EVIDENCE_DATE
        assert any(m in g.real_trigger_ref.lower() for m in schema.VOID_CALL_MARKERS)
        assert "freight_notes" in g.real_trigger_ref
        assert g.flag is schema.Flag.SIM
        # the lot it delays must actually be in port in July 2022, or the trigger is not its trigger
        lot = V.ticket_schedule(t).lots
        arrival = next(l.arrival for l in lot if l.lot_id == g.lot_id)
        assert dt.date(2022, 7, 1) <= arrival <= dt.date(2022, 8, 15), f"{g.event_id} arrival {arrival}"

    free_days = int(config.value("detention_free_days"))
    chargeable = [l for t in book.trades for l in V.ticket_schedule(t).lots if l.chargeable_dwell_days > 0]
    assert chargeable, "the void-call dwell must actually run past the free days"
    assert all(l.dwell_days > free_days for l in chargeable)

    franchise_breaches = []
    for t in book.trades:
        for q in t.events.quality:
            limit = float(t.purchase.spa.contamination_limit_frac
                          or config.value(f"contamination_frac_{t.grade.value}", t.trade_date))
            franchise = float(t.purchase.spa.moisture_franchise_frac
                              or config.value("standard_moisture_franchise_frac", t.trade_date))
            if q.contamination_actual_frac > limit or q.moisture_actual_frac > franchise:
                franchise_breaches.append((t.trade_id, q.lot_id))
            assert q.flag is schema.Flag.SIM
    assert franchise_breaches, "at least one quality outcome must fall outside the franchise"
    rejections = [q for t in book.trades for q in t.events.quality if q.rejected_boxes > 0]
    assert rejections and all(q.rejection_reason is not None for q in rejections)


def test_the_book_carries_exposure_through_the_crash_and_the_inr_slide(book):
    """The book must actually be in the market for the two real adverse events, not around them."""
    panel = V.panel()
    crash_start, crash_end = dt.date(2022, 3, 7), dt.date(2022, 7, 15)
    live = [t for t in book.trades
            if t.trade_date <= crash_end and V.ticket_schedule(t).last_cashflow >= crash_start]
    assert len(live) >= 7, "most of the book must span the LME crash"
    # a ticket is exposed if it owns unpriced or unsold cargo on the crash's worst day
    exposed = [t for t in book.trades
               if t.trade_date <= crash_end
               and abs(V.hedge_exposure_inr_per_usd_t(t, max(t.trade_date, dt.date(2022, 5, 9)),
                                                      V.ticket_schedule(t))[0]) > 0]
    assert len(exposed) >= 4
    # USD payables run through the ~5 % INR slide; not all of them are covered
    fx_open = [t for t in book.trades if (t.hedges.fx_forwards.hedge_frac_target or 0) < 1.0]
    assert fx_open, "a fully covered book would show nothing in the FX bucket"
    assert float(panel.loc["2022-08-31", "usdinr"]) / float(panel.loc["2022-03-01", "usdinr"]) - 1 > 0.04


# --------------------------------------------------------------------------------------------- credit control
def test_every_sale_is_booked_inside_the_buyer_limit(book):
    frame = V.credit_exposure_frame(book)
    assert len(frame) == sum(len(t.sales) for t in book.trades)
    assert frame["within_limit"].all(), frame[~frame["within_limit"]].to_string()
    assert frame["utilisation_frac"].max() > 0.5, "a book that never approaches a limit is not using its lines"
    assert frame["utilisation_frac"].max() <= 1.0


def test_credit_exposure_ignores_the_delay_event(book):
    """A limit at booking may only use contractual terms: a delay that has not happened cannot justify a line."""
    frame = V.credit_exposure_frame(book).set_index(["trade_id", "sale_id"])
    t07 = book.trade("T07")
    sched = V.ticket_schedule(t07)
    delay = sum(b.delay_days for b in t07.events.buyer_payment_delay)
    assert delay > 0
    assert frame.loc[("T07", "S1"), "due_date"] == sched.sale_due_contractual["S1"].isoformat()
    assert sched.sale_due["S1"] > sched.sale_due_contractual["S1"]


# ------------------------------------------------------------------------------- helpers used by the checks
def test_roll_following_skips_lme_holidays():
    assert V.roll_following(dt.date(2022, 4, 15)) == dt.date(2022, 4, 19)   # Good Friday + Easter Monday
    assert V.roll_following(dt.date(2022, 6, 2)) == dt.date(2022, 6, 6)     # Platinum Jubilee
    assert V.roll_following(dt.date(2022, 8, 29)) == dt.date(2022, 8, 30)   # summer bank holiday
    assert V.roll_following(dt.date(2022, 5, 10)) == dt.date(2022, 5, 10)


def test_mcx_roll_deadline_uses_the_direct_expiry_list():
    """design D4b: the roll deadline comes from the DIRECT expiry, not the panel's last-calendar-day slot."""
    assert V.mcx_expiries()["2022-08"] == dt.date(2022, 8, 30)
    assert V.mcx_roll_deadline("2022-08") == dt.date(2022, 8, 18)
    assert V.mcx_roll_deadline("2022-03") == dt.date(2022, 3, 22)
    n = int(config.value("mcx_roll_days_before_expiry"))
    for month in ("2022-03", "2022-04", "2022-05", "2022-06", "2022-07", "2022-08", "2022-09"):
        prior = [d for d in V.panel_days() if d < V.mcx_expiries()[month]]
        assert V.mcx_roll_deadline(month) == prior[-n]


def test_panel_slot_and_direct_expiry_are_one_contract(book):
    """The 31-Aug panel slot and the 30-Aug DIRECT expiry must resolve to the same contract month."""
    px, src, slot = book_run.mcx_price_inr_kg(dt.date(2022, 8, 3), "2022-08")
    assert src == "PANEL_M1" and slot == dt.date(2022, 8, 31)
    assert V.mcx_expiries()["2022-08"] == dt.date(2022, 8, 30)
    assert px == pytest.approx(float(V.panel_row(dt.date(2022, 8, 3))["mcx_al_m1_inr_kg"]))


def test_averaging_midpoint_is_the_ceiling_of_half_the_window():
    assert V.averaging_midpoint(dt.date(2022, 4, 19), dt.date(2022, 4, 29)) == dt.date(2022, 4, 25)   # 9 days
    assert V.averaging_midpoint(dt.date(2022, 6, 29), dt.date(2022, 7, 8)) == dt.date(2022, 7, 4)     # 8 days
    assert V.averaging_midpoint(dt.date(2022, 7, 1), dt.date(2022, 7, 29)) == dt.date(2022, 7, 15)    # 21 days


def test_market_reference_reproduces_phase_one_exactly():
    """P11: Phase 2 re-evaluates CONTRACTS §5 on arbitrary days; if it drifts, every price here quotes a
    different model from the one that selected the trades."""
    assert V.cross_phase_control() == []
    from desk.parity import model

    inputs = model.build_inputs()
    p1 = pd.concat([inputs[model.KEY_COLUMNS], model.compute(inputs).drop(columns=model.KEY_COLUMNS)], axis=1)
    row = p1[p1["in_window"].astype(bool)].iloc[0]
    ref = V.market_reference(pd.Timestamp(row["value_date"]).date(), row["grade"], row["lane"])
    assert ref["net_arb_inr_t"] == pytest.approx(float(row["net_arb_inr_t"]), abs=1e-6)
    assert ref["replacement_inr_t"] == pytest.approx(
        float(row["goods_inr_t"] + row["bcd_inr_t"] + row["sws_inr_t"] + row["port_inr_t"]), abs=1e-6)


def test_hedge_sizing_rule_is_reproducible(book):
    """P07: each non-roll entry reproduces round(ratio x net ₹-delta / ₹-delta of one lot) at its entry date."""
    for t in book.trades:
        sched = V.ticket_schedule(t)
        targets = {tr.roll_to for tr in t.hedges.mcx.tranches if tr.roll_to}
        for tr in t.hedges.mcx.tranches:
            if tr.hedge_id in targets:
                continue
            net, _ = V.hedge_exposure_inr_per_usd_t(t, tr.entry_date, sched)
            per_lot = V.mcx_delta_inr_per_lot(tr.entry_date, tr.contract_month)
            want = round(t.hedges.mcx.hedge_ratio_target * net / per_lot)
            assert abs(V.open_lots(t, tr.entry_date) - want) <= V.MCX_LOT_TOL, f"{tr.hedge_id}"


def test_mcx_positions_are_whole_lots_within_the_direct_client_limit(book):
    lot_mt = float(config.value("mcx_al_lot_mt"))
    limit = float(config.value("mcx_al_position_limit_client_mt"))
    for t in book.trades:
        for tr in t.hedges.mcx.tranches:
            assert isinstance(tr.lots, int) and tr.lots >= 1
            assert tr.lots * lot_mt <= limit
    days = sorted({d for t in book.trades for tr in t.hedges.mcx.tranches
                   for d in (tr.entry_date, tr.exit_date)})
    peak = max(abs(sum(V.open_lots(t, d) for t in book.trades)) for d in days)
    assert peak * lot_mt <= limit, f"the desk-level position peaks at {peak} lots"


def test_hindsight_scanner_behaviour():
    """P08 in isolation: a future market date is a hit, a declared contract date is not, the past is not."""
    asof = dt.date(2022, 3, 8)
    assert V.rationale_hindsight_hits("LME closed at 3,500 on 08-Mar-2022", asof, (), ()) == []
    assert V.rationale_hindsight_hits("the low came on 15-Jul-2022", asof, (), ()) == ["15-Jul-2022"]
    assert V.rationale_hindsight_hits("the low came on 2022-07-15", asof, (), ()) == ["2022-07-15"]
    assert V.rationale_hindsight_hits("averaged over July 2022", asof, ("july",), ()) == []
    assert V.rationale_hindsight_hits("averaged over July 2022", asof, (), ()) == ["July 2022"]
    assert V.rationale_hindsight_hits("priced on the July average", asof, ("july",), ()) == []
    assert V.rationale_hindsight_hits("priced on the July average", asof, (), ()) == ["July"]
    assert V.rationale_hindsight_hits("ships by 29-Apr-2022", asof, (), (dt.date(2022, 4, 29),)) == []
    # a full date must not also be counted as its own month-year
    assert V.rationale_hindsight_hits("window ends 29-Apr-2022", asof, (), ()) == ["29-Apr-2022"]
    # a day-month with no year means the year the prose is written in
    assert V.rationale_hindsight_hits("the high was 07-Mar", asof, (), ()) == []
    assert V.rationale_hindsight_hits("the boxes book by 25-Mar", asof, (), ()) == ["25-Mar"]
    assert V.rationale_hindsight_hits("the boxes book by 18-Mar", asof, (), (dt.date(2022, 3, 18),)) == []
    # and a full date must not be double-counted as a bare day-month either
    assert V.rationale_hindsight_hits("the low came on 15-Jul-2022", asof, (), ()) == ["15-Jul-2022"]


def test_basis_risk_notes_and_terms_notes_are_scanned_too(book):
    """P08 covers every piece of desk prose that could smuggle a later observation in, not just the rationale."""
    for t in book.trades:
        sched = V.ticket_schedule(t)
        months, dates = V.declared_future_months(t, sched), V.declared_dates(t, sched)
        for text, asof in ([(t.rationale.text, t.trade_date),
                            (t.purchase.pricing.terms_basis_note, t.trade_date),
                            (t.hedges.mcx.basis_risk_note, t.trade_date)]
                           + [(s.pricing.terms_basis_note, s.contract_date) for s in t.sales]):
            assert V.rationale_hindsight_hits(text, asof, months, dates) == [], f"{t.trade_id}: {text[:60]}"


def test_no_rationale_mentions_a_date_after_its_trade_date(book):
    for t in book.trades:
        sched = V.ticket_schedule(t)
        hits = V.rationale_hindsight_hits(t.rationale.text, t.trade_date,
                                          V.declared_future_months(t, sched), V.declared_dates(t, sched))
        assert hits == [], f"{t.trade_id}: {hits}"
        assert len(t.rationale.text.split()) >= 80, f"{t.trade_id}: row 2.9 wants a real paragraph"


def test_sale_prices_sit_between_replacement_value_and_netback(book):
    for t in book.trades:
        for s in t.sales:
            ref = V.market_reference(s.contract_date, t.grade.value, t.lane.value)
            price = book_run._sale_price_at(t, s, s.contract_date)
            assert ref["replacement_inr_t"] <= price <= ref["netback_inr_t"], f"{t.trade_id}/{s.sale_id}"
            want = ref["replacement_inr_t"] + V.DESK_ARB_SHARE_FRAC * (ref["netback_inr_t"]
                                                                       - ref["replacement_inr_t"])
            assert abs(price - want) <= V.SALE_PRICE_BAND_INR_T


# ------------------------------------------------------------------------------------------ mutation table
def test_p01_fires_when_a_trade_moves_to_an_ineligible_week(raw, tmp_path, panel_days):
    doc = copy.deepcopy(raw)
    t = _ticket(doc, "T06")                      # zorba JEA_NSA closes after the 06-May week
    t["trade_date"] = dt.date(2022, 6, 8)
    t["rationale"]["parity_week_end"] = dt.date(2022, 6, 3)
    issues = _mutated(doc, tmp_path, panel_days)
    assert "P01" in _codes(issues)
    assert any("not trade_eligible" in i.message for i in issues if i.code == "P01")


def test_p01_fires_when_the_ticket_cites_the_wrong_parity_week(raw, tmp_path, panel_days):
    doc = copy.deepcopy(raw)
    _ticket(doc, "T03")["rationale"]["parity_week_end"] = dt.date(2022, 3, 11)
    assert "P01" in _codes(_mutated(doc, tmp_path, panel_days))


def test_p02_fires_when_boxes_stop_matching_the_tonnage(raw, tmp_path, panel_days):
    doc = copy.deepcopy(raw)
    _ticket(doc, "T02")["shipment"]["lots"][0]["boxes"] = 25
    assert "P02" in _codes(_mutated(doc, tmp_path, panel_days))


def test_p03_fires_when_a_cashflow_falls_outside_the_horizon(raw, tmp_path, panel_days):
    doc = copy.deepcopy(raw)
    t = _ticket(doc, "T09")
    t["sales"][0]["payment"]["credit_days"] = 45
    t["shipment"]["laycan_end"] = dt.date(2022, 9, 14)
    t["shipment"]["lots"][1]["bl_date"] = dt.date(2022, 9, 14)
    issues = _mutated(doc, tmp_path, panel_days)
    assert "P03" in _codes(issues)
    assert any("HORIZON_END" in i.message for i in issues if i.code == "P03")


def test_p04_fires_when_a_sale_breaches_the_buyer_limit(raw, raw_cps, tmp_path, panel_days):
    cps = copy.deepcopy(raw_cps)
    for c in cps["counterparties"]:
        if c["cp_id"] == "BUY_JNPT_01":
            c["credit_limit_inr"] = 100000000.0
    issues = _mutated(copy.deepcopy(raw), tmp_path, panel_days, cps)
    assert "P04" in _codes(issues)
    assert any("against a limit of" in i.message for i in issues if i.code == "P04")


def test_p05_fires_when_the_fixture_is_priced_off_market(raw, tmp_path, panel_days):
    doc = copy.deepcopy(raw)
    _ticket(doc, "T01")["freight"]["rate_usd_box"] = 3200.0
    issues = _mutated(doc, tmp_path, panel_days)
    assert "P05" in _codes(issues)
    assert any("lane index" in i.message for i in issues if i.code == "P05")


def test_p05_fires_when_the_stop_loss_is_not_the_policy_stop(raw, tmp_path, panel_days):
    doc = copy.deepcopy(raw)
    _ticket(doc, "T04")["freight"]["stop_loss"]["stop_loss_usd_box"] = 3000.0
    assert "P05" in _codes(_mutated(doc, tmp_path, panel_days))


def test_p05_fires_when_a_triggered_stop_was_ignored(raw, tmp_path, panel_days):
    """The index never reached the stop in 2022; lower the stop under the market and the rule must bite."""
    doc = copy.deepcopy(raw)
    f = _ticket(doc, "T07")["freight"]
    index = V._freight_index_usd_box(dt.date(2022, 5, 25), schema.Lane.USEC_MUN)
    f["stop_loss"]["stop_loss_usd_box"] = round(index * (1 + V.FREIGHT_STOP_LOSS_FRAC), 2)
    f["fixture_date"] = dt.date(2022, 5, 27)
    # move the stop to just under the prevailing index: it was "touched" on the trade date itself
    f["stop_loss"]["stop_loss_usd_box"] = round(index * 0.99, 2)
    issues = _mutated(doc, tmp_path, panel_days)
    assert "P05" in _codes(issues)


def test_p06_fires_when_a_roll_is_late(raw, tmp_path, panel_days):
    doc = copy.deepcopy(raw)
    t = _ticket(doc, "T03")
    t["hedges"]["mcx"]["tranches"][0]["exit_date"] = dt.date(2022, 4, 26)
    t["hedges"]["mcx"]["tranches"][1]["entry_date"] = dt.date(2022, 4, 26)
    issues = _mutated(doc, tmp_path, panel_days)
    assert "P06" in _codes(issues)
    assert any("roll deadline" in i.message for i in issues if i.code == "P06")


def test_p07_fires_when_a_hedge_is_sized_off_policy(raw, tmp_path, panel_days):
    doc = copy.deepcopy(raw)
    _ticket(doc, "T06")["hedges"]["mcx"]["tranches"][0]["lots"] = 60
    issues = _mutated(doc, tmp_path, panel_days)
    assert "P07" in _codes(issues)
    assert any("hedge ratio" in i.message for i in issues if i.code == "P07")


def test_p08_fires_on_a_forward_dated_rationale(raw, tmp_path, panel_days):
    doc = copy.deepcopy(raw)
    t = _ticket(doc, "T01")
    t["rationale"]["text"] = t["rationale"]["text"] + " The low finally came on 15-Jul-2022."
    issues = _mutated(doc, tmp_path, panel_days)
    assert "P08" in _codes(issues)
    assert any("15-Jul-2022" in i.message for i in issues if i.code == "P08")


def test_p09_fires_when_a_sale_is_priced_above_the_netback(raw, tmp_path, panel_days):
    doc = copy.deepcopy(raw)
    _ticket(doc, "T03")["sales"][0]["pricing"]["price_inr_t"] = 260000.0
    issues = _mutated(doc, tmp_path, panel_days)
    assert "P09" in _codes(issues)
    assert any("netback" in i.message for i in issues if i.code == "P09")


def test_p10_fires_when_the_desk_pays_over_parity(raw, tmp_path, panel_days):
    doc = copy.deepcopy(raw)
    _ticket(doc, "T09")["purchase"]["pricing"]["price_usd_t"] = 1900.0
    issues = _mutated(doc, tmp_path, panel_days)
    assert "P10" in _codes(issues)
    assert any("parity" in i.message for i in issues if i.code == "P10")


def test_p10_fires_when_a_formula_factor_is_above_the_trade_date_factor(raw, tmp_path, panel_days):
    doc = copy.deepcopy(raw)
    _ticket(doc, "T05")["purchase"]["pricing"]["factor_frac"] = 0.72
    assert "P10" in _codes(_mutated(doc, tmp_path, panel_days))


def test_p12_warns_on_a_limit_locked_session(raw, tmp_path, panel_days):
    """08-Mar-2022: the near-month proxy moved 12.0 % against a 9 % slab. The real book hedges the next day."""
    doc = copy.deepcopy(raw)
    for tr in _ticket(doc, "T01")["hedges"]["mcx"]["tranches"][:2]:
        tr["entry_date"] = dt.date(2022, 3, 8)
    issues = _mutated(doc, tmp_path, panel_days)
    assert "P12" in {i.code for i in issues if i.severity == "WARNING"}
    assert V._dpl_move(dt.date(2022, 3, 8)) < -float(config.value("mcx_al_dpl_max_frac"))


# ------------------------------------------------------------------------------------------------- outputs
def test_run_writes_three_tables_and_is_deterministic(tmp_path):
    book, first, _ = book_run.build(strict=True)
    assert set(first) == {"trade_book.csv", "trade_hedges.csv", "trade_eligibility_check.csv"}
    _, second, _ = book_run.build(strict=True)
    for name, df in first.items():
        a = df.to_csv(index=False, lineterminator="\n").encode()
        b = second[name].to_csv(index=False, lineterminator="\n").encode()
        assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest(), name


def test_trade_book_table_shape(book):
    elig = V.eligibility_frame(book)
    df = book_run.trade_book_rows(book, elig)
    assert len(df) == len(book.trades)
    assert df["trade_eligible"].all() and df["settles_inside_horizon"].all()
    assert df["in_window"].all()
    assert (df["sim_label"] == "ACADEMIC SIMULATION — not actual trades").all()
    for col in ("isri_grade_spec", "moisture_franchise_frac", "contamination_limit_frac", "discount_multiple",
                "rejection_excess_frac", "radioactivity_clause_key", "penalty_schedule_key",
                "purchase_pricing_type", "payment_instrument", "sale_payment_terms", "laycan_start",
                "vessels", "freight_risk_borne_by", "rationale"):
        assert df[col].notna().all(), col
    assert df["rationale"].str.len().min() > 400
    assert df["quantity_mt"].sum() == pytest.approx(sum(t.quantity_mt for t in book.trades))


def test_methods_doc_is_generated_and_complete(book):
    """docs/20_trade_book.md is rendered from the same frames as the CSVs, so the two cannot disagree."""
    elig = V.eligibility_frame(book)
    tables = {"trade_book.csv": book_run.trade_book_rows(book, elig),
              "trade_hedges.csv": book_run.trade_hedge_rows(book),
              "trade_eligibility_check.csv": elig}
    md = book_run.render_doc(book, tables, V.credit_exposure_frame(book), V.validate(book))
    assert md == book_run.render_doc(book, tables, V.credit_exposure_frame(book), V.validate(book))
    assert "ACADEMIC SIMULATION — not actual trades" in md.split("\n", 6)[2]
    for heading in ("## 1. The book at a glance", "## 2. Counterparties and credit limits",
                    "## 3. Trade discipline", "## 4. The desk policy this book was written to",
                    "## 5. Ticket cards", "## 6. The hedge stack",
                    "### 6.2 Cross-exchange basis risk", "### 6.4 The freight risk layer",
                    "## 7. Operational events", "## 8. Provenance",
                    "## 9. What this book is checked against",
                    "## 10. What this does and doesn't tell you",
                    "## 11. Changes during integration with Phase 3"):
        assert heading in md, heading
    for t in book.trades:
        assert f"### {t.trade_id} —" in md
        assert f"**Trader's rationale, {t.trade_date}.**" in md
    for field in ("Quantity (2.1)", "SPA (2.2)", "Incoterm (2.3)", "Purchase price (2.4)",
                  "Import payment (2.6)", "Laycan and vessels (2.8)", "Freight layer (2.7d)",
                  "Hedge stack (2.7)", "§5a evidence (2.9)"):
        assert md.count(f"| {field} |") == len(book.trades), field
    # no markdown table row may carry an unescaped pipe inside a cell
    for line in md.splitlines():
        if line.startswith("| ") and not set(line) <= set("|- "):
            cells = [c for c in line.split("|")[1:-1]]
            assert all("\\" not in c or "\\|" in line for c in cells)
    assert "(SIM)" in md
    # the integration log is the last thing on the page, and it says whether any ticket had to change
    assert md.rstrip().endswith("§11.3.")
    assert "**No ticket was changed.**" in md


def test_trade_hedges_table_covers_every_instrument(book):
    df = book_run.trade_hedge_rows(book)
    n_mcx = sum(len(t.hedges.mcx.tranches) for t in book.trades)
    n_fx = sum(len(t.hedges.fx_forwards.lines) for t in book.trades)
    n_frt = sum(1 for t in book.trades if t.freight is not None and t.freight.fixture_date is not None)
    assert len(df) == n_mcx + n_fx + n_frt
    mcx = df[df["instrument"] == "MCX_ALUMINIUM_FUTURE"]
    assert mcx["entry_price_src"].isin(["PANEL_M1", "PANEL_M2"]).all(), "no month needed extrapolation"
    assert (mcx["roll_deadline"] >= mcx["exit_date"]).all()
    assert mcx["basis_risk_note"].str.len().min() > 200
    fx = df[df["instrument"] == "USDINR_FORWARD"]
    assert (fx["rate_inr"] - fx["forward_mid_inr"]).abs().round(6).eq(
        float(config.value("fx_forward_bank_margin_inr"))).all()
    assert fx["value_date"].max() <= HORIZON_END.isoformat()
