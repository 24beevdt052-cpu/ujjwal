"""Phase 2 — trade-ticket and counterparty schema (`desk.book.schema`) and the checked-in example fixtures.

Two things are under test. First that the grammar is *closed*: a ticket carrying an unknown field, a derived number
or a wrong enum fails loudly and names the path, because a silently-ignored field is how hindsight and
inconsistency get into a book that three phases have to agree on. Second that the example tickets in
`config/*.example.yaml` are actually valid — they are the fixture every later stage tests against, and an invalid
fixture would send Phase 3 chasing its own tail.

The mutation table is the real content: one deliberately broken copy of the fixture per rule, asserting the rule
fires and nothing else has to. Rules that need the market panel or Phase 1 parity (LME trading days, §5a
eligibility) are exercised here with the real Phase 0 outputs when they exist, and skipped otherwise.
"""

from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path

import pytest
import yaml

from desk import HORIZON_END, WINDOW_END, WINDOW_START, config
from desk.book import schema
from desk.paths import CONFIG_DIR, PROCESSED_DIR, TABLES_DIR

TRADES_EXAMPLE = CONFIG_DIR / "trades.example.yaml"
CPS_EXAMPLE = CONFIG_DIR / "counterparties.example.yaml"
PANEL_CSV = PROCESSED_DIR / "market_daily.csv"
PARITY_CSV = TABLES_DIR / "parity_weekly.csv"
EXAMPLE_LABEL = "EXAMPLE — engine test fixture (SIM)"

# Proposed `config/params/book.yaml` lag, stated here as a literal so the test does not depend on a file Phase 2
# has not written yet (design §2.5). Only used for the horizon arithmetic below.
BOE_LAG_DAYS = 1


# ---------------------------------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def counterparties() -> list[schema.Counterparty]:
    return schema.load_counterparties(CPS_EXAMPLE)


@pytest.fixture(scope="module")
def trades() -> list[schema.Ticket]:
    return schema.load_trades(TRADES_EXAMPLE)


@pytest.fixture(scope="module")
def book(trades, counterparties) -> schema.Book:
    return schema.Book(trades=tuple(trades), counterparties=tuple(counterparties),
                       trades_path=str(TRADES_EXAMPLE), counterparties_path=str(CPS_EXAMPLE))


@pytest.fixture(scope="module")
def panel_days() -> set[dt.date] | None:
    if not PANEL_CSV.exists():
        return None
    import pandas as pd

    return {d.date() for d in pd.read_csv(PANEL_CSV, parse_dates=["date"])["date"]}


@pytest.fixture(scope="module")
def raw_trades() -> dict:
    return yaml.safe_load(TRADES_EXAMPLE.read_text())


def _write(tmp_path: Path, doc: dict, name: str = "trades.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc, sort_keys=False))
    return p


def _codes(issues) -> set[str]:
    return {i.code for i in issues if i.severity == "ERROR"}


def _issues_for(doc: dict, tmp_path: Path, counterparties, **kw) -> list[schema.Issue]:
    tickets = schema.load_trades(_write(tmp_path, doc))
    return schema.validate_trades(tickets, counterparties, **kw)


# ------------------------------------------------------------------------------------- the fixtures are valid
def test_example_files_are_labelled_as_fixtures():
    """A reader must never mistake the fixture for the book (CONTRACTS §1.1)."""
    for p in (TRADES_EXAMPLE, CPS_EXAMPLE):
        head = p.read_text()[:400]
        assert EXAMPLE_LABEL in head, f"{p.name} must carry '{EXAMPLE_LABEL}' at the top"
        assert "ACADEMIC SIMULATION" in p.read_text()


def test_example_book_loads_and_has_no_issues(book, panel_days):
    issues = schema.validate_book(book, panel_days=panel_days)
    assert issues == [], "\n".join(i.format() for i in issues)


def test_load_book_strict_returns_a_book(panel_days):
    b = schema.load_book(TRADES_EXAMPLE, CPS_EXAMPLE, strict=True, panel_days=panel_days)
    assert [t.trade_id for t in b.trades] == ["T91", "T92", "T93"]
    assert len(b.counterparties) == 5
    assert b.counterparty("BUY_MUN_01").role is schema.Role.BUYER
    assert b.trade("T92").purchase.incoterm is schema.Incoterm.CFR


def test_loading_is_deterministic():
    """Frozen dataclasses: two loads of the same file must compare equal, so a re-run cannot drift."""
    assert schema.load_trades(TRADES_EXAMPLE) == schema.load_trades(TRADES_EXAMPLE)
    assert schema.load_counterparties(CPS_EXAMPLE) == schema.load_counterparties(CPS_EXAMPLE)


def test_quantities_are_whole_containers(trades):
    """Containers ship whole: quantity_mt must be boxes × the grade's payload for that box size."""
    for t in trades:
        assert t.boxes * t.payload_mt_per_box == pytest.approx(t.quantity_mt, abs=schema.BOX_TONNAGE_TOL_MT)
        assert schema.MIN_TRADE_MT <= t.quantity_mt <= schema.MAX_TRADE_MT


def test_trade_dates_are_in_window_and_eligible(trades):
    """CONTRACTS §5a: a fixture that bypassed the eligibility gate would not exercise it."""
    if not PARITY_CSV.exists():
        pytest.skip("Phase 1 parity_weekly.csv missing")
    from desk.parity import model

    for t in trades:
        assert WINDOW_START <= t.trade_date <= WINDOW_END
        eligible, week_end, row = model.eligible_on(t.trade_date, t.grade.value, t.lane.value)
        assert eligible, f"{t.trade_id}: {t.grade}/{t.lane} is not trade_eligible on {t.trade_date}"
        assert week_end.date() == t.rationale.parity_week_end
        assert row["net_arb_conv18k_inr_t"] > 0


def test_every_dated_decision_settles_inside_the_horizon(trades):
    """CONTRACTS §7.1: every cashflow a ticket implies must land on or before HORIZON_END."""
    transit = {schema.Lane.JEA_NSA: int(config.value("transit_days_jea_nsa")),
               schema.Lane.USEC_MUN: int(config.value("transit_days_usec_mun"))}
    clearance = int(config.value("clearance_delivery_days"))
    igst_lag = int(config.value("igst_credit_lag_days"))
    for t in trades:
        last_bl = max(lot.bl_date for lot in t.shipment.lots)
        dwell = sum(e.extra_dwell_days for e in t.events.logistics)
        arrival = last_bl + dt.timedelta(days=transit[t.lane] + max(
            (e.arrival_delay_days for e in t.events.logistics), default=0))
        latest = [arrival + dt.timedelta(days=BOE_LAG_DAYS + igst_lag)]
        if t.purchase.payment.usance_days:
            latest.append(last_bl + dt.timedelta(days=t.purchase.payment.usance_days))
        release = arrival + dt.timedelta(days=clearance + dwell)
        for s in t.sales:
            delay = sum(e.delay_days for e in t.events.buyer_payment_delay if e.sale_id == s.sale_id)
            if s.payment.credit_days:
                anchor = max(release, s.pricing.window_end or release)
                latest.append(anchor + dt.timedelta(days=s.payment.credit_days + delay))
        for fx in t.hedges.fx_forwards.lines:
            latest.append(fx.value_date)
        assert max(latest) <= HORIZON_END, f"{t.trade_id}: last flow {max(latest)} is after {HORIZON_END}"


def test_examples_cover_every_leg_type(trades):
    """The three tickets are the engine's coverage matrix; if one stops covering a leg the fixture is worth less."""
    by_id = {t.trade_id: t for t in trades}
    pricing = {t.purchase.pricing.type for t in trades}
    assert pricing == {schema.PurchasePricingType.FIXED, schema.PurchasePricingType.LME_M1_AVG}
    assert {t.purchase.incoterm for t in trades} == {schema.Incoterm.FOB, schema.Incoterm.CFR}
    assert {t.purchase.payment.instrument for t in trades} == {schema.PaymentInstrument.LC_SIGHT,
                                                               schema.PaymentInstrument.LC_USANCE}
    assert any(t.purchase.payment.confirmed for t in trades)                      # confirmation fee
    assert {s.pricing.type for t in trades for s in t.sales} == {schema.SalePricingType.FIXED,
                                                                 schema.SalePricingType.MCX_AVG}
    assert {s.payment.terms for t in trades for s in t.sales} == {schema.SalePaymentTerms.ADVANCE,
                                                                  schema.SalePaymentTerms.CREDIT}
    directions = {tr.direction for t in trades for tr in t.hedges.mcx.tranches}
    assert directions == {schema.HedgeDirection.SELL, schema.HedgeDirection.BUY}
    reasons = {tr.exit_reason for t in trades for tr in t.hedges.mcx.tranches}
    assert reasons == {schema.HedgeExitReason.ROLL, schema.HedgeExitReason.UNWIND, schema.HedgeExitReason.TRANCHE}
    assert any(fx.cancel_date is not None for t in trades for fx in t.hedges.fx_forwards.lines)
    assert by_id["T91"].freight is not None and by_id["T91"].freight.stop_loss is not None
    assert by_id["T93"].events.quality and by_id["T93"].events.quality[0].rejected_boxes == 1
    assert by_id["T93"].events.logistics and by_id["T93"].events.buyer_payment_delay
    # T91 and T93 are unsold for a stretch (replacement-value mark); T92 is back-to-back on the trade date.
    assert by_id["T91"].sales[0].contract_date > by_id["T91"].trade_date
    assert by_id["T93"].sales[0].contract_date > by_id["T93"].trade_date
    assert by_id["T92"].sales[0].contract_date == by_id["T92"].trade_date


def test_counterparties_span_the_credit_range(counterparties):
    buyers = [c for c in counterparties if c.role is schema.Role.BUYER]
    suppliers = [c for c in counterparties if c.role is schema.Role.SUPPLIER]
    assert 2 <= len(suppliers) <= 3 and 2 <= len(buyers) <= 3       # MASTER_SPEC Table 4 row 2.5
    assert any(b.credit_limit_inr == 0 for b in buyers), "one advance-only name keeps the tracker honest"
    assert all(c.name.endswith(schema.SIM_SUFFIX) for c in counterparties)
    assert {c.lc_confirmation_required for c in suppliers} == {True, False}


# ------------------------------------------------------------------------------------------- parse-time errors
def test_unknown_field_names_the_path_and_the_alternatives(raw_trades, tmp_path):
    doc = copy.deepcopy(raw_trades)
    doc["trades"][0]["purchase"]["incoterms"] = "FOB"
    with pytest.raises(schema.SchemaError) as exc:
        schema.load_trades(_write(tmp_path, doc))
    msg = str(exc.value)
    assert "purchase.incoterms" in msg and "unknown field" in msg and "incoterm" in msg


def test_derived_field_may_not_be_typed(raw_trades, tmp_path):
    """Typing a derived number is how hindsight gets in; the loader rejects it by name."""
    for path, key, value in [(("trades", 0), "boxes", 100),
                             (("trades", 1, "purchase", "pricing"), "qp_start", "2022-07-01"),
                             (("trades", 1, "hedges", "mcx", "tranches", 0), "entry_price_inr_kg", 235.5),
                             (("trades", 2, "hedges", "fx_forwards", "lines", 0), "rate_inr", 78.5)]:
        doc = copy.deepcopy(raw_trades)
        node = doc
        for step in path:
            node = node[step]
        node[key] = value
        with pytest.raises(schema.SchemaError, match="derived field must not be typed"):
            schema.load_trades(_write(tmp_path, doc))


def test_extra_mapping_is_the_one_escape_hatch(raw_trades, tmp_path):
    doc = copy.deepcopy(raw_trades)
    doc["trades"][0]["extra"] = {"desk_note": "carried through, never read by the engine"}
    doc["trades"][0]["purchase"]["extra"] = {"broker": "n/a"}
    tickets = schema.load_trades(_write(tmp_path, doc))
    assert tickets[0].extra["desk_note"].startswith("carried through")
    assert tickets[0].purchase.extra == {"broker": "n/a"}


def test_extra_must_be_a_mapping(raw_trades, tmp_path):
    doc = copy.deepcopy(raw_trades)
    doc["trades"][0]["extra"] = ["not", "a", "mapping"]
    with pytest.raises(schema.SchemaError, match=r"extra: expected a mapping"):
        schema.load_trades(_write(tmp_path, doc))


def test_bad_enum_lists_the_allowed_values(raw_trades, tmp_path):
    doc = copy.deepcopy(raw_trades)
    doc["trades"][0]["lane"] = "JEA_MUN"
    with pytest.raises(schema.SchemaError) as exc:
        schema.load_trades(_write(tmp_path, doc))
    assert "JEA_NSA" in str(exc.value) and "USEC_MUN" in str(exc.value)


def test_missing_required_field(raw_trades, tmp_path):
    doc = copy.deepcopy(raw_trades)
    del doc["trades"][0]["quantity_mt"]
    with pytest.raises(schema.SchemaError, match=r"quantity_mt: required field is missing"):
        schema.load_trades(_write(tmp_path, doc))


def test_bad_date_is_rejected(raw_trades, tmp_path):
    doc = copy.deepcopy(raw_trades)
    doc["trades"][0]["trade_date"] = "11-04-2022"
    with pytest.raises(schema.SchemaError, match="is not an ISO date"):
        schema.load_trades(_write(tmp_path, doc))


def test_wrong_schema_version_and_top_level_keys(raw_trades, tmp_path):
    doc = copy.deepcopy(raw_trades)
    doc["schema_version"] = 2
    with pytest.raises(schema.SchemaError, match="schema_version"):
        schema.load_trades(_write(tmp_path, doc))
    doc = copy.deepcopy(raw_trades)
    doc["notes"] = "hello"
    with pytest.raises(schema.SchemaError, match="unknown top-level keys"):
        schema.load_trades(_write(tmp_path, doc))


# --------------------------------------------------------------------------------------- validation rule table
def _m_duplicate_id(d):
    d["trades"][1]["trade_id"] = "T91"


def _m_vessel_not_sim(d):
    d["trades"][0]["shipment"]["lots"][0]["vessel"] = "MV Ever Given"


def _m_trade_date_outside_window(d):
    d["trades"][0]["trade_date"] = dt.date(2022, 1, 10)
    d["trades"][0]["rationale"]["parity_week_end"] = dt.date(2022, 1, 7)


def _m_parity_week_after_trade(d):
    d["trades"][0]["rationale"]["parity_week_end"] = dt.date(2022, 4, 22)


def _m_quantity_not_whole_boxes(d):
    d["trades"][0]["quantity_mt"] = 2080.0


def _m_quantity_below_band(d):
    d["trades"][2]["quantity_mt"] = 630.0
    d["trades"][2]["shipment"]["lots"][0]["boxes"] = 30


def _m_cfr_with_freight_block(d):
    d["trades"][1]["freight"] = copy.deepcopy(d["trades"][0]["freight"])


def _m_fob_without_freight_block(d):
    del d["trades"][0]["freight"]


def _m_m1_laycan_crosses_months(d):
    d["trades"][1]["shipment"]["laycan_end"] = dt.date(2022, 7, 5)


def _m_bl_outside_laycan(d):
    d["trades"][1]["shipment"]["lots"][1]["bl_date"] = dt.date(2022, 6, 17)


def _m_credit_over_msme_cap(d):
    d["trades"][1]["sales"][0]["payment"]["credit_days"] = 60


def _m_fixed_pricing_with_factor(d):
    d["trades"][0]["purchase"]["pricing"]["factor_frac"] = 0.736


def _m_m1_pricing_without_reference(d):
    del d["trades"][1]["purchase"]["pricing"]["lme_reference"]


def _m_usance_days_on_sight_lc(d):
    d["trades"][0]["purchase"]["payment"]["usance_days"] = 90


def _m_usance_out_of_band(d):
    d["trades"][1]["purchase"]["payment"]["usance_days"] = 120


def _m_lc_opened_after_laycan(d):
    d["trades"][2]["purchase"]["payment"]["lc_open_date"] = dt.date(2022, 6, 24)


def _m_confirmed_without_charges_party(d):
    del d["trades"][0]["purchase"]["payment"]["confirmation_charges_for"]


def _m_fixture_without_rate(d):
    del d["trades"][0]["freight"]["rate_usd_box"]


def _m_stop_loss_after_bl(d):
    d["trades"][0]["freight"]["stop_loss"]["latest_fixture_date"] = dt.date(2022, 5, 6)


def _m_hypothetical_swap_in_base_book(d):
    f = d["trades"][0]["freight"]
    f["risk_layer"] = "PROXY_SWAP_HYPOTHETICAL"
    del f["stop_loss"]
    f["swap"] = {"swap_id": "T91-FRT-1", "boxes": 100, "strike_usd_box": 1990.0,
                 "start_date": dt.date(2022, 4, 11), "settle_date": dt.date(2022, 5, 5)}


def _m_lot_sold_twice(d):
    d["trades"][0]["sales"][0]["lot_ids"] = ["L1", "L1"]


def _m_lot_never_sold(d):
    d["trades"][0]["sales"][0]["lot_ids"] = ["L1"]


def _m_sale_before_trade(d):
    d["trades"][2]["sales"][0]["contract_date"] = dt.date(2022, 6, 3)


def _m_mcx_window_before_contract(d):
    d["trades"][1]["sales"][0]["pricing"]["window_start"] = dt.date(2022, 5, 10)


def _m_advance_frac_not_one(d):
    d["trades"][0]["sales"][0]["payment"]["advance_frac"] = 0.5


def _m_unknown_supplier(d):
    d["trades"][0]["purchase"]["supplier_id"] = "SUP_XXX_01"


def _m_supplier_wrong_lane(d):
    d["trades"][1]["purchase"]["supplier_id"] = "SUP_USEC_01"


def _m_roll_entry_mismatch(d):
    d["trades"][2]["hedges"]["mcx"]["tranches"][1]["entry_date"] = dt.date(2022, 6, 22)


def _m_roll_changes_size(d):
    d["trades"][2]["hedges"]["mcx"]["tranches"][1]["lots"] = 100


def _m_contract_month_not_listed(d):
    d["trades"][2]["hedges"]["mcx"]["tranches"][0]["contract_month"] = "2022-13"


def _m_hedge_exit_before_entry(d):
    d["trades"][0]["hedges"]["mcx"]["tranches"][0]["exit_date"] = dt.date(2022, 4, 8)


def _m_no_basis_risk_note(d):
    d["trades"][0]["hedges"]["mcx"]["basis_risk_note"] = ""


def _m_fx_cancel_after_value(d):
    d["trades"][1]["hedges"]["fx_forwards"]["lines"][2]["cancel_date"] = dt.date(2022, 8, 12)


def _m_fx_value_after_horizon(d):
    d["trades"][1]["hedges"]["fx_forwards"]["lines"][0]["value_date"] = dt.date(2022, 11, 7)


def _m_fx_negative_notional(d):
    d["trades"][2]["hedges"]["fx_forwards"]["lines"][0]["notional_usd"] = -1340000.0


def _m_void_call_known_too_early(d):
    d["trades"][2]["events"]["logistics"][0]["known_date"] = dt.date(2022, 7, 20)


def _m_rejected_more_than_shipped(d):
    d["trades"][2]["events"]["quality"][0]["rejected_boxes"] = 61


def _m_rejection_without_reason(d):
    del d["trades"][2]["events"]["quality"][0]["rejection_reason"]


def _m_delay_on_unknown_sale(d):
    d["trades"][2]["events"]["buyer_payment_delay"][0]["sale_id"] = "S7"


def _m_event_flagged_direct(d):
    d["trades"][2]["events"]["logistics"][0]["flag"] = "DIRECT"


MUTATIONS = [
    ("duplicate trade_id", _m_duplicate_id, "V01"),
    ("vessel name not (SIM)", _m_vessel_not_sim, "V02"),
    ("trade date outside the window", _m_trade_date_outside_window, "V05"),
    ("parity week after the trade date", _m_parity_week_after_trade, "V05"),
    ("tonnage not a whole number of boxes", _m_quantity_not_whole_boxes, "V06"),
    ("tonnage below the Table 4 band", _m_quantity_below_band, "V06"),
    ("CFR carrying a freight block", _m_cfr_with_freight_block, "V07"),
    ("FOB without a freight block", _m_fob_without_freight_block, "V07"),
    ("M+1 laycan crossing two months", _m_m1_laycan_crosses_months, "V08"),
    ("B/L outside the laycan", _m_bl_outside_laycan, "V08"),
    ("buyer credit beyond the MSME cap", _m_credit_over_msme_cap, "V09"),
    ("fixed price plus a grade factor", _m_fixed_pricing_with_factor, "V10"),
    ("M+1 pricing with no LME reference", _m_m1_pricing_without_reference, "V10"),
    ("usance tenor on a sight LC", _m_usance_days_on_sight_lc, "V11"),
    ("usance outside 60-90 days", _m_usance_out_of_band, "V11"),
    ("LC opened after the laycan starts", _m_lc_opened_after_laycan, "V11"),
    ("confirmed LC with no charges party", _m_confirmed_without_charges_party, "V11"),
    ("fixture date without a rate", _m_fixture_without_rate, "V12"),
    ("space booked after the boxes sail", _m_stop_loss_after_bl, "V12"),
    ("hypothetical freight swap in the base book", _m_hypothetical_swap_in_base_book, "V12"),
    ("one lot sold twice", _m_lot_sold_twice, "V13"),
    ("a lot left unsold", _m_lot_never_sold, "V13"),
    ("sale contracted before the purchase", _m_sale_before_trade, "V13"),
    ("MCX averaging starts before the sale", _m_mcx_window_before_contract, "V14"),
    ("ADVANCE that is not 100%", _m_advance_frac_not_one, "V15"),
    ("supplier not in the counterparty file", _m_unknown_supplier, "V16"),
    ("supplier does not load that lane", _m_supplier_wrong_lane, "V16"),
    ("roll target entering on another day", _m_roll_entry_mismatch, "V17"),
    ("roll changing the position size", _m_roll_changes_size, "V17"),
    ("unlisted MCX contract month", _m_contract_month_not_listed, "V17"),
    ("hedge exit before entry", _m_hedge_exit_before_entry, "V17"),
    ("hedge with no basis-risk note", _m_no_basis_risk_note, "V17"),
    ("forward cancelled after value date", _m_fx_cancel_after_value, "V18"),
    ("forward settling after HORIZON_END", _m_fx_value_after_horizon, "V19"),
    ("negative forward notional", _m_fx_negative_notional, "V18"),
    ("void calls known before the report", _m_void_call_known_too_early, "V20"),
    ("more boxes rejected than shipped", _m_rejected_more_than_shipped, "V20"),
    ("rejection with no reason", _m_rejection_without_reason, "V20"),
    ("payment delay on an unknown sale", _m_delay_on_unknown_sale, "V20"),
    ("simulated event flagged DIRECT", _m_event_flagged_direct, "V20"),
]


@pytest.mark.parametrize("label,mutate,code", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_each_rule_catches_its_own_break(label, mutate, code, raw_trades, counterparties, tmp_path):
    doc = copy.deepcopy(raw_trades)
    mutate(doc)
    issues = _issues_for(doc, tmp_path, counterparties)
    assert code in _codes(issues), (
        f"{label}: expected rule {code} to fire, got {sorted(_codes(issues)) or 'no errors'}")


def test_non_trading_decision_date_is_rejected(raw_trades, counterparties, panel_days, tmp_path):
    """Decision dates are taken by a trader on a trading day; only derived cashflow dates are rolled."""
    if panel_days is None:
        pytest.skip("Phase 0 market_daily.csv missing")
    doc = copy.deepcopy(raw_trades)
    doc["trades"][2]["purchase"]["payment"]["lc_open_date"] = dt.date(2022, 6, 11)   # a Saturday
    issues = _issues_for(doc, tmp_path, counterparties, panel_days=panel_days)
    assert "V04" in _codes(issues)


def test_hypothetical_freight_swap_is_allowed_only_in_a_labelled_run(raw_trades, counterparties, tmp_path):
    doc = copy.deepcopy(raw_trades)
    _m_hypothetical_swap_in_base_book(doc)
    assert "V12" in _codes(_issues_for(doc, tmp_path, counterparties))
    assert "V12" not in _codes(_issues_for(doc, tmp_path, counterparties, allow_hypothetical=True))


def test_sale_after_the_cargo_lands_is_a_warning_not_an_error(raw_trades, counterparties, tmp_path):
    """The desk does not warehouse: selling after the planned release is flagged, and Phase 2 hardens it."""
    doc = copy.deepcopy(raw_trades)
    doc["trades"][2]["sales"][0]["contract_date"] = dt.date(2022, 8, 22)
    issues = _issues_for(doc, tmp_path, counterparties)
    assert "V13" not in _codes(issues)
    assert any(i.severity == "WARNING" and i.code == "V13" for i in issues)


def test_load_book_raises_with_every_error_listed(raw_trades, tmp_path):
    doc = copy.deepcopy(raw_trades)
    _m_duplicate_id(doc)
    _m_vessel_not_sim(doc)
    path = _write(tmp_path, doc)
    with pytest.raises(schema.ValidationError) as exc:
        schema.load_book(path, CPS_EXAMPLE, strict=True)
    assert {i.code for i in exc.value.issues} >= {"V01", "V02"}
    assert "trades(T91)" in str(exc.value)


# ------------------------------------------------------------------------------------- counterparty-side rules
def test_counterparty_rules(counterparties, tmp_path):
    raw = yaml.safe_load(CPS_EXAMPLE.read_text())

    def issues_after(mutate):
        doc = copy.deepcopy(raw)
        mutate(doc)
        p = tmp_path / "cps.yaml"
        p.write_text(yaml.safe_dump(doc, sort_keys=False))
        return _codes(schema.validate_counterparties(schema.load_counterparties(p)))

    assert "V02" in issues_after(lambda d: d["counterparties"][0].__setitem__("name", "Real Metals Ltd"))
    assert "V03" in issues_after(lambda d: d["counterparties"][3].pop("credit_limit_inr"))
    assert "V03" in issues_after(lambda d: d["counterparties"][0].__setitem__("credit_limit_inr", 1.0))
    assert "V03" in issues_after(lambda d: d["counterparties"][0].__setitem__("type", "FOUNDRY"))
    assert "V09" in issues_after(lambda d: d["counterparties"][3].__setitem__("credit_days_default", 90))
    assert "V01" in issues_after(lambda d: d["counterparties"][1].__setitem__("cp_id", "SUP_USEC_01"))
    assert "V01" in issues_after(lambda d: d["counterparties"][1].__setitem__("cp_id", "supplier-2"))


def test_issue_formatting_names_the_path():
    i = schema.Issue("ERROR", "V06", "trades(T91).quantity_mt", "does not match the box count")
    assert i.format() == "ERROR V06 trades(T91).quantity_mt: does not match the box count"
