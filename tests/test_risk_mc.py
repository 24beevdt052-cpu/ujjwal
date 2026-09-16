"""Phase 4.2 — Monte Carlo stress testing (docs/41_monte_carlo.md).

The claims these tests stand behind:

* **determinism** — every random number comes from `desk.RNG_SEED`; the published paths are re-simulated from the
  published covariance and re-revalued to the paisa;
* **the simulator reproduces its covariance** (normal and Student-t on a large sample; the bootstrap scales with the
  horizon), and the mixed daily/weekly estimator does what the doc says, with no hindsight in the point-in-time span;
* **a zero shock is the base value** and the per-path loop is exactly `revalue_book` (checked against the API's own
  vectorised call where that call works);
* **scenario signs make sense** — LME −15 % on the hedged book is a fraction of the unhedged loss; a buyer default
  loses money and loses more with lower recovery or a simultaneous LME fall; the freight stress equals Phase 3's;
* **the published tables are internally consistent** — VaR/ES recompute from the published paths, percentiles from
  the distribution, snapshot dates from the registered rules.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from desk import RNG_SEED, WINDOW_END, WINDOW_START
from desk.mtm import history
from desk.mtm import run as mtm_run
from desk.mtm import valuation as val
from desk.paths import PROCESSED_DIR, TABLES_DIR
from desk.risk import monte_carlo as mc

COV3 = np.array([[5.4e-4, -1.0e-6, -2.0e-5],
                 [-1.0e-6, 7.9e-6, -1.0e-6],
                 [-2.0e-5, -1.0e-6, 5.8e-5]])
PEAK_GROSS = dt.date(2022, 4, 21)
PEAK_BUYER = dt.date(2022, 7, 27)
ATH_PLUS_1 = dt.date(2022, 3, 8)


# ------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def engine():
    if not (TABLES_DIR / "book_exposures_daily.csv").exists():
        pytest.skip("Phase 3 outputs missing (run desk.mtm.run)")
    book = mtm_run.load()
    H = history.MarketHistory()
    return {"book": book, "H": H, "cache": val.ScheduleCache(book, H),
            "unhedged": val.ScheduleCache(book, H, drop_instruments=frozenset({"mcx"}))}


def _need(*names):
    missing = [n for n in names if not (TABLES_DIR / n).exists()]
    if missing:
        pytest.skip(f"published Phase 4.2 outputs missing: {missing} (run desk.risk.run_mc)")


def _corr(cov):
    d = np.sqrt(np.diag(cov))
    return cov / np.outer(d, d)


# ---------------------------------------------------------------------------------------------- simulation
def test_draws_are_deterministic_from_rng_seed():
    a = mc.standard_draws(500, 4, 10, 5.0)
    b = mc.standard_draws(500, 4, 10, 5.0, seed=RNG_SEED)
    c = mc.standard_draws(500, 4, 10, 5.0, seed=RNG_SEED + 1)
    for f in ("z", "chi2", "u_boot"):
        assert np.array_equal(getattr(a, f), getattr(b, f))
    assert not np.array_equal(a.z, c.z)


def test_normal_simulation_reproduces_the_covariance_on_a_large_sample():
    draws = mc.standard_draws(200_000, 3, 10, 5.0)
    cov_h = COV3 * 10
    x = mc.simulate_normal(draws, cov_h)
    got = np.cov(x, rowvar=False)
    assert np.allclose(np.diag(got), np.diag(cov_h), rtol=0.015)
    assert np.allclose(_corr(got), _corr(cov_h), atol=0.01)
    assert np.allclose(x.mean(axis=0), 0.0, atol=3 * np.sqrt(np.diag(cov_h) / 200_000))


def test_student_t_keeps_the_covariance_and_fattens_the_tail():
    draws = mc.standard_draws(200_000, 3, 10, 5.0)
    cov_h = COV3 * 10
    xt = mc.simulate_student_t(draws, cov_h)
    xn = mc.simulate_normal(draws, cov_h)
    got = np.cov(xt, rowvar=False)
    assert np.allclose(np.diag(got), np.diag(cov_h), rtol=0.06)   # t variance converges slowly at nu = 5
    assert np.allclose(_corr(got), _corr(cov_h), atol=0.02)
    z = xt[:, 0] / math.sqrt(cov_h[0, 0])
    assert np.quantile(z, 0.001) < np.quantile(xn[:, 0] / math.sqrt(cov_h[0, 0]), 0.001) - 0.8
    with pytest.raises(ValueError):
        mc.simulate_student_t(mc.standard_draws(10, 3, 10, 2.0), cov_h)


def test_bootstrap_is_demeaned_and_scales_variance_with_the_horizon():
    rng = np.random.default_rng(7)
    daily = rng.standard_normal((126, 3)) * [0.02, 0.003, 0.01] + [-0.003, 0.0004, -0.002]
    draws = mc.standard_draws(100_000, 3, 10, 5.0)
    x = mc.simulate_bootstrap(draws, daily)
    demeaned = daily - daily.mean(axis=0)
    target = 10 * (demeaned ** 2).mean(axis=0)              # population variance of the resampled days
    assert np.allclose(x.var(axis=0), target, rtol=0.03)
    assert np.allclose(x.mean(axis=0), 0.0, atol=3 * np.sqrt(target / 100_000))


def test_a_factor_appended_last_leaves_the_base_paths_unchanged():
    cov4 = np.zeros((4, 4))
    cov4[:3, :3] = COV3
    cov4[3, 3] = 1.0
    cov4[0, 3] = cov4[3, 0] = -0.7 * math.sqrt(COV3[0, 0])
    draws = mc.standard_draws(1_000, 4, 10, 5.0)
    assert np.allclose(mc.simulate_normal(draws, cov4)[:, :3], mc.simulate_normal(draws, COV3), atol=1e-15)


def test_assemble_covariance_mixes_daily_and_weekly_samples():
    rng = np.random.default_rng(11)
    idx = pd.bdate_range("2022-03-01", periods=130)
    daily = pd.DataFrame({"lme": rng.normal(0, 0.02, 130), "fx": rng.normal(0, 0.003, 130),
                          "freight": rng.normal(0, 0.009, 130)}, index=idx)
    widx = pd.date_range("2022-03-04", periods=26, freq="W-FRI")
    wl = rng.normal(0, 0.045, 26)
    weekly = pd.DataFrame({"lme": wl, "fx": rng.normal(0, 0.006, 26),
                           "freight": -0.5 * wl / 0.045 * 0.02 + rng.normal(0, 0.017, 26)}, index=widx)
    cov, pairs = mc.assemble_covariance(daily, weekly, ["lme", "fx", "freight"])
    assert cov.loc["lme", "lme"] == pytest.approx(daily["lme"].var(ddof=1))
    assert cov.loc["freight", "freight"] == pytest.approx(weekly["freight"].var(ddof=1) / 5)
    r_week = np.corrcoef(weekly["lme"], weekly["freight"])[0, 1]
    assert cov.loc["lme", "freight"] == pytest.approx(
        r_week * daily["lme"].std(ddof=1) * weekly["freight"].std(ddof=1) / math.sqrt(5))
    src = pairs.set_index(["factor_i", "factor_j"])["sample"]
    assert src[("lme", "fx")] == "daily" and src[("lme", "freight")] == "weekly"
    assert src[("freight", "freight")] == "weekly"


def test_nearest_psd_repairs_an_indefinite_correlation_matrix():
    bad = np.array([[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]])
    fixed, min_eig = mc.nearest_psd_corr(bad)
    assert min_eig < 0
    assert np.linalg.eigvalsh(fixed).min() > -1e-12
    assert np.allclose(np.diag(fixed), 1.0)
    good = np.array([[1.0, 0.3], [0.3, 1.0]])
    assert mc.nearest_psd_corr(good)[0] is good


def test_var_and_es_are_the_order_statistic_estimators():
    pnl = np.random.default_rng(3).permutation(np.arange(1, 10_001, dtype=float)) - 5_000.5
    v99, e99 = mc.var_es(pnl, 0.99)
    assert mc.tail_count(10_000, 0.99) == 100 and mc.tail_count(10_000, 0.95) == 500
    assert v99 == pytest.approx(5_000.5 - 100)            # the 100th worst path
    assert e99 == pytest.approx(5_000.5 - 50.5)           # mean of the 100 worst
    lo, hi = mc.var_ci(pnl, 0.99)
    assert lo < v99 < hi
    st = mc.risk_stats(pnl)
    assert st["var95_inr"] < st["var99_inr"] < st["es99_inr"]
    assert mc.percentile_in(pnl, -v99) == pytest.approx(0.01)


def test_es_contributions_add_up_to_book_es():
    rng = np.random.default_rng(5)
    by_trade = rng.standard_normal((4, 10_000)) * np.array([[3.0], [1.0], [2.0], [0.5]])
    _, es = mc.var_es(by_trade.sum(axis=0), 0.99)
    assert mc.es_contributions(by_trade, 0.99).sum() == pytest.approx(-es)


def test_point_in_time_span_ignores_everything_after_the_snapshot():
    """No hindsight: rewriting every change dated after t leaves the point-in-time covariance untouched."""
    rng = np.random.default_rng(9)
    idx = pd.bdate_range("2021-06-01", "2022-08-31")
    levels = pd.DataFrame({"lme_cash_usd_t": 3000 * np.exp(np.cumsum(rng.normal(0, 0.02, len(idx)))),
                           "usdinr": 75 * np.exp(np.cumsum(rng.normal(0, 0.003, len(idx)))),
                           "freight_usec_mun_usd_t": 100 * np.exp(np.cumsum(rng.normal(0, 0.005, len(idx))))},
                          index=idx)
    t = pd.Timestamp("2022-04-21")
    pert = levels.copy()
    pert.loc[pert.index > t] *= np.exp(rng.normal(0, 0.2, (int((pert.index > t).sum()), 3)))

    def cov_at(lv):
        d = mc.factor_changes(lv)
        w = mc.factor_changes(mc.weekly_samples(lv))
        span = mc.trailing_span("pit", d.index, t, 126)
        return mc.assemble_covariance(span.daily(d), span.weekly(w), mc.BASE_FACTORS)[0]

    pd.testing.assert_frame_equal(cov_at(levels), cov_at(pert))


# ------------------------------------------------------------------------------------------- the real book
def test_zero_shock_paths_equal_the_base_value(engine):
    b, H, cache = engine["book"], engine["H"], engine["cache"]
    zeros = {k: np.zeros(5) for k in ("lme_cash_logret", "usdinr_logret", "freight_logret")}
    assert np.abs(mc.revalue_paths(b, H, PEAK_GROSS, zeros, cache=cache)).max() == 0.0
    zeros["mcx_basis_abs"] = np.zeros(5)
    assert np.abs(mc.revalue_paths(b, H, PEAK_GROSS, zeros, cache=cache, mcx_hold_basis=False)).max() == 0.0


def test_per_path_loop_is_exactly_the_vectorised_api(engine):
    """Where `revalue_book` vectorises (no freight array), the per-path loop must give the same numbers."""
    b, H, cache = engine["book"], engine["H"], engine["cache"]
    draws = mc.standard_draws(60, 3, 10, 5.0)
    x = mc.simulate_normal(draws, COV3 * 10)
    shocks = {"lme_cash_logret": x[:, 0], "usdinr_logret": x[:, 1]}
    for t in (PEAK_GROSS, PEAK_BUYER):
        loop = mc.revalue_paths(b, H, t, shocks, cache=cache)
        vec = val.revalue_book(b, H, t, shocks=shocks, cache=cache) - val.revalue_book(b, H, t, cache=cache)
        assert np.allclose(loop, vec, atol=1e-4)


def test_lme_minus_15pct_on_the_hedged_book_is_small_against_unhedged(engine):
    b, H = engine["book"], engine["H"]
    sh = {"lme_cash_logret": math.log(0.85)}

    def pnl(t, cache):
        return float(val.revalue_book(b, H, t, shocks=sh, cache=cache).sum() - val.revalue_book(b, H, t, cache=cache).sum())

    for t, max_ratio in ((PEAK_GROSS, 0.25), (PEAK_BUYER, 0.05)):
        hedged, unhedged = pnl(t, engine["cache"]), pnl(t, engine["unhedged"])
        assert unhedged < 0                                   # the physical book is long metal
        assert abs(hedged) < max_ratio * abs(unhedged)
    # on 8-Mar the MCX hedge did not exist yet: hedged == unhedged
    assert pnl(ATH_PLUS_1, engine["cache"]) == pytest.approx(pnl(ATH_PLUS_1, engine["unhedged"]))


def test_freight_stress_reproduces_phase3_hypothetical(engine):
    _need("adverse_event_3_freight_stress_hypothetical.csv")
    b, H, cache = engine["book"], engine["H"], engine["cache"]
    p3 = pd.read_csv(TABLES_DIR / "adverse_event_3_freight_stress_hypothetical.csv", parse_dates=["date"])
    ref = float(p3[(p3.trade_id == "BOOK") & (p3.date == pd.Timestamp(ATH_PLUS_1))]["impact_inr"].iloc[0])
    got = float(val.revalue_book(b, H, ATH_PLUS_1, shocks={"freight_logret": math.log(1.4)}, cache=cache).sum()
                - val.revalue_book(b, H, ATH_PLUS_1, cache=cache).sum())
    assert ref < 0 and got == pytest.approx(ref, abs=1.0)


def test_buyer_default_goes_through_the_api_and_orders_sensibly(engine):
    b, H, cache = engine["book"], engine["H"], engine["cache"]
    kw = dict(resale_discount=0.05, cache=cache)
    v25, adj = mc.buyer_default_pnl(b, H, PEAK_BUYER, "BUY_RJK_01", recovery_unsecured=0.25, **kw)
    assert v25 < 0
    assert np.allclose(adj["api_adjustment_inr"], -adj["loss_inr"], atol=1.0)   # the API reproduces the loss
    assert v25 == pytest.approx(-adj["loss_inr"].sum(), abs=1.0)
    v0, _ = mc.buyer_default_pnl(b, H, PEAK_BUYER, "BUY_RJK_01", recovery_unsecured=0.0, **kw)
    v50, _ = mc.buyer_default_pnl(b, H, PEAK_BUYER, "BUY_RJK_01", recovery_unsecured=0.5, **kw)
    assert v0 <= v25 <= v50
    vw, _ = mc.buyer_default_pnl(b, H, PEAK_BUYER, "BUY_RJK_01", recovery_unsecured=0.25,
                                 shocks={"lme_cash_logret": math.log(0.85)}, **kw)
    assert vw < v25                                                              # wrong-way: retained cargo falls
    none, adj0 = mc.buyer_default_pnl(b, H, PEAK_GROSS, "BUY_RJK_01", recovery_unsecured=0.25, **kw)
    assert none == 0.0 and adj0.empty                                            # no RJK flow on 21-Apr
    worst = mc.buyer_default_adjustments(b, H, PEAK_BUYER, "BUY_RJK_01", recovery_unsecured=0.0,
                                         resale_discount=1.0, cache=cache)
    assert worst["implied_recovery_frac"].between(-1e-9, 1e-9).all()             # nothing recovered, nothing resold


def test_qco_scope_uncleared_is_no_worse_than_all_tickets(engine):
    b, H, cache = engine["book"], engine["H"], engine["cache"]
    ev = val.StressEvent(kind="qco_hold", delay_days=21, rejection_frac=0.10, rejected_loss_frac=0.15)
    scoped, rows = mc.qco_hold_pnl(b, H, PEAK_BUYER, ev, cache=cache, uncleared_only=True)
    everything, rows_all = mc.qco_hold_pnl(b, H, PEAK_BUYER, ev, cache=cache, uncleared_only=False)
    assert everything < scoped < 0
    assert set(rows["trade_id"]) < set(rows_all["trade_id"])
    assert (rows["uncleared_lots"] > 0).all()


# --------------------------------------------------------------------------------------- published outputs
def test_published_summary_shape_and_ordering():
    _need("mc_summary.csv")
    s = pd.read_csv(TABLES_DIR / "mc_summary.csv")
    assert s.groupby("snapshot_id").size().eq(6).all() and s["snapshot_id"].nunique() == 3
    assert (s["n_paths"] == mc.N_PATHS).all()
    assert (s["var95_inr"] <= s["var99_inr"]).all() and (s["var99_inr"] <= s["es99_inr"]).all()
    assert (s["es95_inr"] >= s["var95_inr"]).all()
    assert ((s["var99_ci95_low_inr"] <= s["var99_inr"]) & (s["var99_inr"] <= s["var99_ci95_high_inr"])).all()
    assert set(s.loc[s.variant == "normal_window", "role"]) == {"BASE"}
    assert s["label"].str.contains("ACADEMIC SIMULATION").all()


def test_published_distribution_reproduces_summary_and_the_seeded_shocks():
    _need("mc_pnl_distribution.csv", "mc_summary.csv", "mc_covariance.csv")
    d = pd.read_csv(TABLES_DIR / "mc_pnl_distribution.csv")
    s = pd.read_csv(TABLES_DIR / "mc_summary.csv").query("variant == 'normal_window'").set_index("snapshot_id")
    for sid, g in d.groupby("snapshot_id"):
        v99, e99 = mc.var_es(g["pnl_inr"].to_numpy(), 0.99)
        v95, _ = mc.var_es(g["pnl_inr"].to_numpy(), 0.95)
        assert v99 == pytest.approx(s.loc[sid, "var99_inr"], abs=0.02)
        assert e99 == pytest.approx(s.loc[sid, "es99_inr"], abs=0.02)
        assert v95 == pytest.approx(s.loc[sid, "var95_inr"], abs=0.02)
    c = pd.read_csv(TABLES_DIR / "mc_covariance.csv").query("covariance_id == 'window'")
    names = list(mc.BASE_FACTORS)
    cov = np.zeros((3, 3))
    for r in c.itertuples(index=False):
        i, j = names.index(r.factor_i), names.index(r.factor_j)
        cov[i, j] = cov[j, i] = r.cov_horizon
    x = mc.simulate_normal(mc.standard_draws(mc.N_PATHS, 4, 10, 5.0), cov)
    g = d[d.snapshot_id == d.snapshot_id.iloc[0]]
    assert np.allclose(g[["lme_cash_logret", "usdinr_logret", "freight_logret"]].to_numpy(), x, atol=5e-9)


def test_published_paths_reproduce_by_full_revaluation(engine):
    _need("mc_pnl_distribution.csv")
    d = pd.read_csv(TABLES_DIR / "mc_pnl_distribution.csv", parse_dates=["snapshot_date"])
    b, H, cache = engine["book"], engine["H"], engine["cache"]
    for _, g in d.groupby("snapshot_id"):
        g = g.head(80)
        t = g["snapshot_date"].iloc[0].date()
        shocks = {k: g[k].to_numpy() for k in ("lme_cash_logret", "usdinr_logret", "freight_logret")}
        got = mc.revalue_paths(b, H, t, shocks, cache=cache).sum(axis=0)
        # the stored shocks are rounded to 1e-12: on a ₹5x10^8-per-unit-return position that is under ₹0.001
        assert np.allclose(got, g["pnl_inr"].to_numpy(), atol=0.05)


def test_published_snapshots_follow_the_registered_rules():
    _need("mc_snapshots.csv", "book_exposures_daily.csv", "mcx_variation_margin.csv")
    import desk.risk.run_mc as run_mc
    s = run_mc.settings()
    again = run_mc.select_snapshots(run_mc.load_panel(), run_mc.load_book_exposures(), s)
    pub = pd.read_csv(TABLES_DIR / "mc_snapshots.csv", parse_dates=["snapshot_date"])
    assert list(pub["snapshot_date"]) == list(again["snapshot_date"])
    assert [d.date() for d in pub["snapshot_date"]] == [ATH_PLUS_1, PEAK_GROSS, PEAK_BUYER]
    assert not set(pub["snapshot_date"]) & run_mc.mcx_exit_or_roll_dates()
    assert (pub["reconciliation_diff_inr"].abs() <= 1.0).all()
    assert (pub["lme_delta_ending_same_day_flows_inr_per_usd_t"].abs()
            <= 0.001 * pub["lme_delta_all_flows_inr_per_usd_t"].abs() + 1e-6).all()
    assert (pub["snapshot_date"] >= pd.Timestamp(WINDOW_START)).all()
    assert (pub["snapshot_date"] <= pd.Timestamp(WINDOW_END)).all()


def test_published_scenarios_are_placed_and_labelled_consistently():
    _need("mc_stress_scenarios.csv", "mc_pnl_distribution.csv", "mc_controls.csv")
    sc = pd.read_csv(TABLES_DIR / "mc_stress_scenarios.csv")
    d = pd.read_csv(TABLES_DIR / "mc_pnl_distribution.csv")
    main = sc[sc.role == "SCENARIO"]
    assert main.groupby("snapshot_id").size().eq(5).all()
    for r in sc.itertuples(index=False):
        p = d.loc[d.snapshot_id == r.snapshot_id, "pnl_inr"].to_numpy()
        assert r.mc_percentile_frac == pytest.approx(mc.percentile_in(p, r.pnl_inr), abs=1e-4)
        assert bool(r.beyond_every_mc_path) == bool(r.pnl_inr < p.min())
    hyp = sc[sc.scenario_id.str.startswith(("freight_plus", "qco_hold"))]
    assert hyp["label"].str.startswith("HYPOTHETICAL").all()
    assert (sc.loc[sc.scenario_id == "buyer_default", "pnl_inr"] <= 0).all()
    assert (pd.read_csv(TABLES_DIR / "mc_controls.csv")["status"] == "PASS").all()


def test_published_window_covariance_matches_the_panel():
    _need("mc_covariance.csv")
    p = pd.read_csv(PROCESSED_DIR / "market_daily.csv", usecols=["date", "lme_cash_usd_t", "usdinr"],
                    parse_dates=["date"]).set_index("date")
    r = np.log(p / p.shift(1))
    w = r[(r.index >= pd.Timestamp(WINDOW_START)) & (r.index <= pd.Timestamp(WINDOW_END))]
    c = pd.read_csv(TABLES_DIR / "mc_covariance.csv").query("covariance_id == 'window'").set_index(
        ["factor_i", "factor_j"])
    assert len(w) == int(c.loc[("lme", "lme"), "n_obs"]) == 126
    assert c.loc[("lme", "lme"), "cov_daily"] == pytest.approx(w["lme_cash_usd_t"].var(ddof=1), rel=1e-6)
    assert c.loc[("lme", "fx"), "corr"] == pytest.approx(w.corr().iloc[0, 1], abs=1e-8)
    assert not c["psd_adjusted"].any()
