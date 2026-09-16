"""Phase 3 result sensitivities: the re-pricing cases, the roll carry split and the basis-risk disclosure.

These are the tests behind three claims a reviewer pushed back on and that `docs/30_mtm_attribution.md` §13.9–§13.11
now make:

* a sensitivity that only **re-marks** the book says nothing about a parameter that never reaches a mark, so the
  registered bands are run as a **re-pricing** through the desk's own S1/S2 rules — and the base case of that
  re-pricing must reproduce the published book to the rupee, or none of the other cases means anything;
* every MCX roll in this book is a gain **by construction**, because the panel proxy is in contango on every day by
  construction; the carry/metal split has to show that, not hide it;
* the MCX-mirror run is a **risk disclosure**, not a better result: it must publish a loss case as well as a gain
  case, and the unit-beta assumption the hedge sizing rests on must be tested rather than asserted.
"""

from __future__ import annotations

import numpy as np
import pytest

from desk import WINDOW_END, WINDOW_START
from desk.book import schema as bs
from desk.mtm import engine, sensitivity as sens
from desk.mtm.history import MarketHistory, panel_days
from desk.paths import CONFIG_DIR

CASES_UNDER_TEST = ("base", "anchor_premium_-52000", "anchor_premium_+13000", "desk_share_0.00",
                    "grade_mix_pit_repriced")


@pytest.fixture(scope="module")
def H() -> MarketHistory:
    return MarketHistory()


@pytest.fixture(scope="module")
def book() -> bs.Book:
    trades, cps = CONFIG_DIR / "trades.yaml", CONFIG_DIR / "counterparties.yaml"
    if not trades.exists() or not cps.exists():
        pytest.skip("config/trades.yaml not published yet")
    return bs.load_book(trades, cps, panel_days=panel_days())


@pytest.fixture(scope="module")
def cases():
    return {c.case: c for c in sens.registered_cases()}


@pytest.fixture(scope="module")
def summary(book, H, cases):
    _per, sm = sens.run_cases(book, H, cases=[cases[c] for c in CASES_UNDER_TEST])
    return sm.set_index("case")


# ------------------------------------------------------------------------------------------------ re-pricing
def test_the_registered_bands_are_all_present(cases):
    """Every band value in the register becomes a case, so the table cannot silently drop one."""
    from desk import config
    for v in config.value("domestic_anchor_premium_sensitivity_inr_t"):
        assert any(c.param_key == "domestic_anchor_premium_inr_t" and c.param_value == float(v)
                   for c in cases.values())
    for v in config.value("conversion_cost_sensitivity_inr_t_ingot"):
        assert any(c.param_key == "conversion_cost_inr_t" and c.param_value == float(v) for c in cases.values())


def test_base_repricing_reproduces_every_typed_price(book, H, cases):
    """Re-deriving the base case through S1/S2 while holding each leg's negotiation delta is the identity."""
    rebuilt = sens.reprice(book, H, H, cases["base"])
    for a, b in zip(book.trades, rebuilt.trades):
        pa, pb = a.purchase.pricing, b.purchase.pricing
        if pa.price_usd_t is not None:
            assert pb.price_usd_t == pytest.approx(pa.price_usd_t, abs=1e-6)
        if pa.factor_frac is not None:
            assert pb.factor_frac == pytest.approx(pa.factor_frac, abs=1e-9)
        for sa, sbx in zip(a.sales, b.sales):
            if sa.pricing.price_inr_t is not None:
                assert sbx.pricing.price_inr_t == pytest.approx(sa.pricing.price_inr_t, abs=1e-6)


def test_base_repricing_reproduces_the_published_book_pnl(book, H, summary):
    published = engine.run_book(book, H, with_detail=False, with_exposures=False)
    att = published.attribution
    end = float(att.loc[att["trade_id"] == engine.BOOK_ID, "cum_pnl_inr"].iloc[-1])
    assert summary.loc["base", "cum_pnl_horizon_inr"] == pytest.approx(end, abs=0.01)


def test_the_anchor_premium_moves_the_book_and_in_the_right_direction(summary):
    """The point of the whole exercise: a re-mark moves this by zero; a re-pricing does not."""
    lo = summary.loc["anchor_premium_-52000", "cum_pnl_horizon_inr"]
    hi = summary.loc["anchor_premium_+13000", "cum_pnl_horizon_inr"]
    base = summary.loc["base", "cum_pnl_horizon_inr"]
    assert lo < base < hi
    assert abs(base - lo) > 1e8, "the registered anchor band must move the book by more than ₹10 crore"
    assert summary.loc[["anchor_premium_-52000", "anchor_premium_+13000"], "mechanism"].eq("REPRICE_SALE").all()


def test_a_smaller_desk_share_of_the_arb_lowers_the_result(summary):
    assert summary.loc["desk_share_0.00", "cum_pnl_horizon_inr"] < summary.loc["base", "cum_pnl_horizon_inr"]


def test_the_point_in_time_grade_mix_repriced_is_not_the_remark(book, H, summary):
    """The published `_grade_pit` variant nets to zero because it only re-marks; the re-priced one does not."""
    assert summary.loc["grade_mix_pit_repriced", "mechanism"] == "REPRICE_BOTH"
    assert summary.loc["grade_mix_pit_repriced", "cum_pnl_horizon_inr"] != pytest.approx(
        summary.loc["base", "cum_pnl_horizon_inr"], abs=1.0)
    pit = engine.run_book(book, MarketHistory(grade_source="pit"), with_detail=False, with_exposures=False)
    att = pit.attribution
    remark = float(att.loc[att["trade_id"] == engine.BOOK_ID, "cum_pnl_inr"].iloc[-1])
    assert remark == pytest.approx(summary.loc["base", "cum_pnl_horizon_inr"], abs=0.01)   # zero by design


def test_every_sensitivity_row_is_labelled(summary):
    assert (summary["label"] == sens.SENSITIVITY_LABEL).all()


# ------------------------------------------------------------------------------------- roll carry vs term structure
def test_the_panel_mcx_proxy_is_in_contango_on_every_window_day(H):
    """`m1/m2 = spot x (1 + r x dte/365)` with dte(M2) > dte(M1), so M2 > M1 always. No curve risk exists here."""
    days = [d for d in H.cal.days if WINDOW_START <= d <= WINDOW_END]
    rows = [H.row(d) for d in days]
    assert all(float(r.mcx_al_m2_inr_kg) > float(r.mcx_al_m1_inr_kg) for r in rows)
    assert len(days) > 100


def test_every_roll_is_pure_inr_carry_on_the_panel_proxy(book, H):
    carry = sens.roll_carry(book, H)
    assert len(carry) > 0
    assert (carry["mcx_series"] == "PANEL_PROXY").all()
    assert carry["metal_inr_kg"].abs().max() < 1e-9          # zero by construction
    assert carry["metal_pnl_inr"].abs().max() < 0.01
    # a short rolling a contango curve earns on every roll: that is arithmetic, not a market view
    shorts = carry[carry["direction"] == "SELL"]
    assert len(shorts) == len(carry)
    assert (shorts["roll_pnl_inr"] > 0).all()
    assert carry["roll_pnl_inr"].sum() == pytest.approx(carry["carry_pnl_inr"].sum(), abs=0.01)


def test_the_mirror_roll_carries_some_real_term_structure(book, H):
    try:
        mirror = MarketHistory(mcx_source="mirror")
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"mirror unavailable: {exc}")
    carry = sens.roll_carry(book, mirror)
    assert carry["metal_pnl_inr"].abs().sum() > 1.0, "on an observed-ish series the split must not be identically 0"
    assert carry["carry_pnl_inr"].sum() == pytest.approx(sens.roll_carry(book, H)["carry_pnl_inr"].sum(), abs=0.01)


def test_the_lme_curve_reference_prices_backwardation_as_a_cost_of_rolling_a_short(book, H):
    """The proxy's roll gain is INR carry by construction; on a parity curve that carries the LME's own cash-3M slope
    a short roll in LME backwardation pays for its metal carry. The columns must show that, sign and all."""
    carry = sens.roll_carry(book, H)
    for col in ("lme_curve_roll_spread_inr_kg", "lme_curve_rate_carry_inr_kg", "lme_curve_metal_carry_inr_kg",
                "lme_curve_roll_pnl_inr", "lme_curve_metal_carry_pnl_inr", "proxy_minus_lme_curve_roll_pnl_inr"):
        assert col in carry.columns
    np.testing.assert_allclose(carry["lme_curve_rate_carry_inr_kg"] + carry["lme_curve_metal_carry_inr_kg"],
                               carry["lme_curve_roll_spread_inr_kg"], atol=1e-9)
    back = carry[carry["lme_backwardation"]]
    cont = carry[~carry["lme_backwardation"]]
    assert len(back) and len(cont)
    assert (back["lme_curve_metal_carry_pnl_inr"] < 0).all()      # a short rolling through backwardation pays
    assert (cont["lme_curve_metal_carry_pnl_inr"] >= 0).all()
    np.testing.assert_allclose(carry["roll_pnl_inr"] - carry["lme_curve_roll_pnl_inr"],
                               carry["proxy_minus_lme_curve_roll_pnl_inr"], atol=0.01)


def test_the_grade_differential_quartiles_are_repricing_cases(cases):
    from desk import config
    for label, q in (("q25", 0), ("q75", 1)):
        c = cases[f"grade_diff_{label}_repriced"]
        assert c.mechanism == sens.REPRICE_BOTH and c.grade_source == "lag2"
        over = dict(c.overrides)
        for g in ("zorba", "taint_tabor", "tense"):
            assert over[f"grade_factor_diff_{g}"] == float(config.value(f"grade_factor_diff_quartiles_{g}")[q])


def test_the_lag2_source_rebuilt_from_mix_plus_differential_is_the_base_grade_path(H):
    lag2 = MarketHistory(panel=H.panel, grade_source="lag2")
    for d in [x for x in H.cal.days if WINDOW_START <= x <= WINDOW_END][::10]:
        for g, v in H.state_at(d).grade_factor_frac.items():
            assert lag2.state_at(d).grade_factor_frac[g] == pytest.approx(v, abs=1e-9)


def test_sign_robustness_reports_a_breakeven_inside_the_band_when_the_sign_flips(book):
    """Synthetic summary: linear P&L in the premium crossing zero inside the grid must be flagged, not averaged."""
    import pandas as pd
    rows = [{"case": "base", "family": "base", "mechanism": sens.REPRICE_SALE, "param_key": "—",
             "param_value": float("nan"), "flag": "—", "cum_pnl_horizon_inr": 100.0}]
    for v in (-55000.0, -52000.0, -9000.0, 13000.0):
        rows.append({"case": f"anchor_premium_{v:+.0f}", "family": "anchor_premium",
                     "mechanism": sens.REPRICE_SALE, "param_key": "domestic_anchor_premium_inr_t",
                     "param_value": v, "flag": "ASSUMPTION", "cum_pnl_horizon_inr": 100.0 + 0.01 * (v + 9000.0)})
    params = lambda k, d=None: {"domestic_anchor_premium_inr_t": -9000.0, "conversion_cost_inr_t": 12000.0}[k]
    out = sens.sign_robustness(pd.DataFrame(rows), book, params=params).set_index("family")
    r = out.loc["anchor_premium"]
    assert r["breakeven_value"] == pytest.approx(-19000.0)
    assert bool(r["breakeven_inside_band"]) and not bool(r["sign_robust_within_band"])
    assert r["linear_max_dev_inr"] < 1e-6
    assert not bool(out.loc["ALL_REGISTERED_BANDS", "sign_robust_within_band"])


# ------------------------------------------------------------------------------------------------- basis risk
def test_the_basis_sensitivity_publishes_a_loss_case_not_only_a_net_gain(book, H):
    try:
        mirror = MarketHistory(mcx_source="mirror")
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"mirror unavailable: {exc}")
    base = engine.run_book(book, H, with_detail=False, with_exposures=False)
    mrun_ = engine.run_book(book, mirror, with_detail=False, with_exposures=False)
    br = sens.basis_risk(base.attribution, mrun_.attribution, H, mirror).set_index(["metric", "scope"])
    worst = float(br.loc[("per_trade_pnl_change_worst_inr", "BOOK"), "value"])
    best = float(br.loc[("per_trade_pnl_change_best_inr", "BOOK"), "value"])
    assert worst < 0 < best, "basis risk must be published two-sided"
    assert float(br.loc[("per_trade_pnl_change_range_inr", "BOOK"), "value"]) == pytest.approx(best - worst)
    assert (br["label"] == sens.SENSITIVITY_LABEL).all()


def test_the_unit_beta_assumption_is_tested_and_rejected(H):
    """The engine holds the MCX basis, i.e. it assumes MCX moves 1:1 with duty-paid parity. On the mirror it does not."""
    # self-consistency: the panel column IS the theo, so beta is 1 up to the CSV's 4-dp rounding of the column
    assert sens.unit_beta_test(H, H)["beta"]["value"] == pytest.approx(1.0, abs=1e-5)
    try:
        mirror = MarketHistory(mcx_source="mirror")
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"mirror unavailable: {exc}")
    res = sens.unit_beta_test(H, mirror)
    beta, t = res["beta"]["value"], res["beta_t_vs_one"]["value"]
    assert 0.0 < beta < 1.0
    assert abs(t) > 2.0, f"unit beta no longer rejected (beta={beta:.3f}, t={t:.2f}) — re-read docs/30 §13.11"
    assert res["unhedged_frac_at_beta"]["value"] == pytest.approx(abs(1.0 - beta))
    assert 0.0 <= res["beta_r2"]["value"] <= 1.0
    assert res["beta_n_days"]["value"] > 100


def test_the_reference_used_for_repricing_matches_phase_2(book, H):
    """`sensitivity.reference` mirrors `desk.book.validate.market_reference`; the two must not drift."""
    import pandas as pd

    from desk.paths import TABLES_DIR
    path = TABLES_DIR / "trade_book.csv"
    if not path.exists():
        pytest.skip("trade_book.csv not published yet")
    tb = pd.read_csv(path).set_index("trade_id")
    for t in book.trades:
        if t.trade_id not in tb.index:
            continue
        r = tb.loc[t.trade_id]
        ref = sens.reference(H, t.trade_date, t.grade.value, t.lane.value)
        # the panel rounds usdinr_fwd_1m to 4 dp, so the replacement mark ties to ~₹0.25/MT (docs/30 §11.2)
        assert ref.replacement_inr_t == pytest.approx(float(r["replacement_inr_t_at_trade_date"]), abs=0.50)
        assert ref.netback_inr_t == pytest.approx(float(r["netback_inr_t_at_trade_date"]), abs=0.50)
        assert ref.cfr_usd_t == pytest.approx(float(r["cfr_parity_usd_t_at_trade_date"]), abs=1e-3)
        assert ref.fob_usd_t == pytest.approx(float(r["fob_parity_usd_t_at_trade_date"]), abs=1e-3)


def test_case_names_are_stable_and_unique(cases):
    assert len(cases) == len(set(cases))
    assert "base" in cases
    assert not any(np.isnan(c.param_value) and c.family not in ("base", "grade_mix", "grade_diff") for c in cases.values())
