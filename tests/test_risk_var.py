"""Phase 4.1 — GARCH(1,1) vs historical-volatility VaR and its backtests (docs/40_var_garch.md).

The claims these tests stand behind:

* **no look-ahead** — a volatility forecast (GARCH parameters included) or a correlation for day t is unchanged when
  every return dated t or later is rewritten, and the published book VaR uses the PREVIOUS close's exposures;
* **Kupiec is the textbook statistic** — exact closed-form cases and the published non-rejection regions (Jorion,
  *Value at Risk*, table of Kupiec POF regions at 95 % / 99 %);
* **VaR scales the way a delta-normal VaR must** — linear in exposure and volatility, zero for a perfect hedge;
* **the variance recursion is arch's own**, so "our GARCH" and "arch's GARCH" are the same numbers;
* **determinism** — re-running the stage reproduces the published tables.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from arch import arch_model

from desk import RNG_SEED, config
from desk.paths import PROCESSED_DIR, TABLES_DIR
from desk.risk import backtest as bt
from desk.risk import garch_var as gv


# ------------------------------------------------------------------------------------------------ fixtures
def _synthetic_returns(n: int = 420, seed: int = RNG_SEED) -> pd.Series:
    """A GARCH(1,1)-like path on business days, so fits are well identified."""
    rng = np.random.default_rng(seed)
    omega, alpha, beta = 0.05, 0.10, 0.85
    s2, out = omega / (1 - alpha - beta), np.empty(n)
    for i in range(n):
        out[i] = math.sqrt(s2) * rng.standard_normal()
        s2 = omega + alpha * out[i] ** 2 + beta * s2
    idx = pd.bdate_range("2019-01-01", periods=n)
    return pd.Series(out / 100.0, index=idx)


@pytest.fixture(scope="module")
def synth() -> pd.Series:
    return _synthetic_returns()


def _need(*paths):
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"published Phase 4.1 outputs missing: {missing} (run desk.risk.run_var)")


# ---------------------------------------------------------------------------------------------- look-ahead
def test_garch_forecast_for_t_ignores_returns_dated_t_and_later(synth):
    targets = synth.index[300:]
    base, _ = gv.garch_forecasts(synth, targets, series="synth", min_obs=250)
    for t in (targets[7], targets[10], targets[42]):   # mid-week and week-start targets
        pert = synth.copy()
        pert[pert.index >= t] = pert[pert.index >= t] * 7.0 + 0.05
        after, _ = gv.garch_forecasts(pert, targets, series="synth", min_obs=250)
        upto = base.index <= t
        np.testing.assert_array_equal(base.loc[upto, "sigma_frac"].to_numpy(), after.loc[upto, "sigma_frac"].to_numpy())
        later = base.index > t
        assert not np.allclose(base.loc[later, "sigma_frac"], after.loc[later, "sigma_frac"])
    assert (base["sample_end"] < base.index).all()


def test_hist_vol_and_rolling_corr_ignore_the_same_day(synth):
    other = _synthetic_returns(seed=RNG_SEED + 1)
    t = synth.index[320]
    hv, rc = gv.hist_vol(synth, 60), gv.rolling_corr(synth, other, 60)
    pert = synth.copy()
    pert[t] = 0.5
    hv2, rc2 = gv.hist_vol(pert, 60), gv.rolling_corr(pert, other, 60)
    assert hv[t] == hv2[t] and rc[t] == rc2[t]
    nxt = synth.index[321]
    assert hv2[nxt] != hv[nxt] and rc2[nxt] != rc[nxt]
    # and the value really is the RMS of the 60 returns strictly before t
    pos = synth.index.get_loc(t)
    assert hv[t] == pytest.approx(math.sqrt(np.mean(synth.iloc[pos - 60:pos] ** 2)), rel=1e-12)


def test_variance_recursion_reproduces_arch(synth):
    y = synth.to_numpy() * gv.PCT
    res = arch_model(y, mean="Zero", vol="GARCH", p=1, q=1, rescale=False).fit(disp="off")
    p = res.params
    path = gv.garch_variance_path(y, p["omega"], p["alpha[1]"], p["beta[1]"], gv.arch_backcast(y))
    np.testing.assert_allclose(np.sqrt(path[:-1]), res.conditional_volatility, rtol=1e-10)
    assert path[-1] == pytest.approx(res.forecast(horizon=1, reindex=False).variance.to_numpy()[-1, 0], rel=1e-10)


def test_garch_forecasts_are_deterministic(synth):
    targets = synth.index[260:]
    a, fa = gv.garch_forecasts(synth, targets, series="synth", min_obs=250)
    b, fb = gv.garch_forecasts(synth, targets, series="synth", min_obs=250)
    pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_frame_equal(gv.fits_frame(fa), gv.fits_frame(fb))


# ------------------------------------------------------------------------------------------------- Kupiec
def test_kupiec_closed_form_cases():
    lr, pv = bt.kupiec_pof(100, 5, 0.05)            # exactly the expected count
    assert lr == pytest.approx(0.0, abs=1e-12) and pv == pytest.approx(1.0)
    lr, pv = bt.kupiec_pof(250, 0, 0.05)            # no exceptions: LR = -2 n ln(1 - p)
    assert lr == pytest.approx(-2 * 250 * math.log(0.95), rel=1e-12)
    assert lr == pytest.approx(25.6466, abs=1e-4)
    n, x, p = 250, 20, 0.05
    by_hand = (-2 * ((n - x) * math.log(1 - p) + x * math.log(p))
               + 2 * ((n - x) * math.log(1 - x / n) + x * math.log(x / n)))
    lr, pv = bt.kupiec_pof(n, x, p)
    assert lr == pytest.approx(by_hand, rel=1e-12)
    assert pv == pytest.approx(math.erfc(math.sqrt(by_hand / 2)), rel=1e-9)  # chi2(1) survival function
    assert bt.kupiec_pof(10, 10, 0.05)[0] == pytest.approx(-2 * 10 * math.log(0.05), rel=1e-12)


@pytest.mark.parametrize("n,p,region", [(255, 0.05, (7, 20)), (510, 0.05, (17, 35)), (1000, 0.05, (38, 64)),
                                        (510, 0.01, (2, 10)), (1000, 0.01, (5, 16))])
def test_kupiec_nonrejection_regions_match_the_published_table(n, p, region):
    # Jorion's table of Kupiec POF non-rejection regions at a 5 % test size: e.g. T = 255 at 95 % -> 6 < N < 21.
    assert bt.kupiec_acceptance_region(n, p) == region


def test_book_sample_has_low_power():
    assert bt.kupiec_acceptance_region(120, 0.05) == (2, 11)


def test_christoffersen_flags_clustered_exceptions_only():
    spread = np.zeros(250, dtype=bool)
    spread[::20] = True
    clustered = np.zeros(250, dtype=bool)
    clustered[100:113] = True
    assert spread.sum() == clustered.sum() == 13      # same count, so Kupiec cannot tell them apart ...
    assert bt.kupiec_pof(250, 13, 0.05)[1] > 0.05
    assert bt.christoffersen_independence(spread)[1] > 0.05     # ... but the independence test can
    assert bt.christoffersen_independence(clustered)[1] < 0.01


def test_exception_is_a_loss_beyond_var():
    assert bt.exceptions([-10.0, -5.0, 3.0], [5.0, 5.0, 5.0]).tolist() == [True, False, False]


# ---------------------------------------------------------------------------------------------- VaR scaling
def test_parametric_var_scaling():
    assert gv.Z_VAR == pytest.approx(1.6448536269514722)
    e, s, r = np.array([[1e8, 0.0]]), np.array([[0.02, 0.005]]), np.eye(2)
    v = gv.parametric_var(e, s, r)[0]
    assert v == pytest.approx(gv.Z_VAR * 1e8 * 0.02)
    assert gv.parametric_var(2 * e, s, r)[0] == pytest.approx(2 * v)
    assert gv.parametric_var(e, 3 * s, r)[0] == pytest.approx(3 * v)
    assert gv.parametric_var(-e, s, r)[0] == pytest.approx(v)                  # VaR is sign-blind for one factor
    two = gv.parametric_var(np.array([[3.0, 4.0]]), np.array([[1.0, 1.0]]), np.eye(2), z=1.0)[0]
    assert two == pytest.approx(5.0)                                            # independent: root-sum-square
    hedge = gv.parametric_var(np.array([[5.0, -5.0]]), np.array([[0.02, 0.02]]), np.ones((2, 2)))[0]
    assert hedge == pytest.approx(0.0, abs=1e-6)                                # perfect hedge, rho = 1 (sqrt of float noise)
    assert gv.t_var_multiplier(5.0) < gv.Z_VAR < gv.t_var_multiplier(5.0) * 1.1
    assert gv.t_var_multiplier(1e6) == pytest.approx(gv.Z_VAR, rel=1e-4)


# -------------------------------------------------------------------------------------------- alert logic
def test_alert_reports_carried_spells_honestly():
    from desk.risk.run_var import _alert

    idx = pd.bdate_range("2022-01-03", periods=10)
    sig = pd.Series([1, 1, 3, 3, 3, 3, 1, 3, 3, 3], index=idx, dtype=float)
    fresh = _alert(sig, 2.0, idx[1], idx[9])
    assert fresh["alert_type"] == "UP_CROSSING" and fresh["alert_date"] == idx[2]
    carried = _alert(sig, 2.0, idx[3], idx[9])
    assert carried["alert_type"] == "ABOVE_WHEN_WINDOW_OPENED" and carried["alert_date"] == idx[2]
    assert carried["first_upcrossing_in_window"] == idx[7] and carried["days_below_threshold_in_window"] == 1
    assert _alert(sig * 0, 2.0, idx[0], idx[9])["alert_type"] == "NO_ALERT"


# ------------------------------------------------------------------------------------------ published tables
def test_risk_yaml_phase41_section_is_well_formed():
    frame = config.params_frame()
    var = frame[frame["key"].str.startswith("var_")]
    assert len(var) >= 10 and set(var["file"]) == {"risk.yaml"}
    assert set(var["flag"]) == {"ASSUMPTION"}
    assert all(v.startswith("N/A") for v in var["verify"])


@pytest.fixture(scope="module")
def daily() -> pd.DataFrame:
    _need(TABLES_DIR / "var_daily.csv")
    return pd.read_csv(TABLES_DIR / "var_daily.csv", parse_dates=["date", "position_date"])


def test_published_var_uses_previous_close_exposures(daily):
    assert (daily["position_date"] < daily["date"]).all()
    ex = pd.read_csv(TABLES_DIR / "book_exposures_daily.csv", usecols=["date", "scope", "lme_delta_inr_per_usd_t",
                                                                        "fx_delta_usd"], parse_dates=["date"])
    ex = ex[ex["scope"] == "book"].set_index("date")
    panel = pd.read_csv(PROCESSED_DIR / "market_daily.csv", usecols=["date", "lme_cash_usd_t", "usdinr"],
                        parse_dates=["date"]).set_index("date")
    cal = panel.index
    held = daily[daily["position_held"]]
    assert len(held) > 100
    for _, r in held.iloc[::9].iterrows():
        assert cal[cal.get_loc(r["date"]) - 1] == r["position_date"]
        want_lme = ex.at[r["position_date"], "lme_delta_inr_per_usd_t"] * panel.at[r["position_date"], "lme_cash_usd_t"]
        want_fx = ex.at[r["position_date"], "fx_delta_usd"] * panel.at[r["position_date"], "usdinr"]
        assert r["exp_lme_inr"] == pytest.approx(want_lme, rel=1e-6, abs=0.05)
        assert r["exp_fx_inr"] == pytest.approx(want_fx, rel=1e-6, abs=0.05)


def test_published_book_var_rebuilds_from_its_own_columns(daily):
    held = daily[daily["position_held"]]
    for _, r in held.iloc[::11].iterrows():
        e = np.array([[r["exp_lme_inr"], r["exp_fx_inr"], r["exp_freight_inr"]]])
        R = gv.corr_matrix({("lme", "fx"): np.array([r["corr_lme_fx"]]),
                            ("lme", "freight"): np.array([r["corr_lme_freight"]]),
                            ("fx", "freight"): np.array([r["corr_fx_freight"]])}, ["lme", "fx", "freight"], 1)
        for m in ("garch", "hist250", "hist60"):
            s = np.array([[r[f"sigma_lme_{m}_frac"], r[f"sigma_fx_{m}_frac"], r["sigma_freight_hist250_frac"]]])
            assert gv.parametric_var(e, s, R)[0] == pytest.approx(r[f"var_{m}_inr"], rel=1e-5, abs=1.0)


def test_published_backtest_pnl_is_the_market_buckets(daily):
    at = pd.read_csv(TABLES_DIR / "attribution_daily.csv", parse_dates=["date"])
    at = at[at["trade_id"] == "BOOK"].set_index("date")
    d = daily.set_index("date")
    common = d.index.intersection(at.index)
    want = at.loc[common, ["lme_flat", "cross_exchange_basis", "freight", "fx"]].sum(axis=1)
    np.testing.assert_allclose(d.loc[common, "pnl_market_inr"], want, atol=0.02)


def test_published_forecasts_never_look_ahead():
    _need(TABLES_DIR / "var_vol_forecasts.csv")
    v = pd.read_csv(TABLES_DIR / "var_vol_forecasts.csv", parse_dates=["date", "lme_garch_sample_end",
                                                                      "fx_garch_sample_end"])
    for s in ("lme", "fx"):
        ok = v[f"{s}_garch_sample_end"].notna()
        assert ok.sum() > 1000
        assert (v.loc[ok, f"{s}_garch_sample_end"] < v.loc[ok, "date"]).all()


def test_published_kupiec_matches_the_daily_exceptions(daily):
    _need(TABLES_DIR / "kupiec.csv")
    k = pd.read_csv(TABLES_DIR / "kupiec.csv")
    w = daily[daily["position_held"] & daily["in_window"]]
    for m in ("garch", "hist250", "hist60"):
        row = k[(k["sample"] == "book_window") & (k["method"] == m)].iloc[0]
        assert row["n"] == len(w) and row["exceptions"] == int(w[f"exception_{m}"].sum())
        lr, pv = bt.kupiec_pof(int(row["n"]), int(row["exceptions"]), 0.05)
        assert row["kupiec_lr"] == pytest.approx(lr, abs=1e-6) and row["kupiec_pvalue"] == pytest.approx(pv, abs=1e-6)


def test_stage_rerun_reproduces_published_tables(daily):
    """Determinism (CONTRACTS §1.5): re-running the stage (~10 s, ~200 MB, no files written) reproduces the tables."""
    from desk.risk import run_var

    out = run_var.run()
    fresh = out["book"].reset_index()
    for c in ("var_garch_inr", "var_hist250_inr", "var_hist60_inr", "pnl_market_inr"):
        np.testing.assert_allclose(fresh[c].to_numpy(), daily[c].to_numpy(), rtol=0, atol=0.006)
    k = pd.read_csv(TABLES_DIR / "kupiec.csv")
    assert out["kupiec"]["exceptions"].tolist() == k["exceptions"].tolist()


def test_mcx_beta_samplings_rebuild_independently_and_bracket_the_daily_beta():
    """var_mcx_beta.csv: the daily beta is P3's, and the weekly and lead/lag betas recompute from the raw mirror file
    (point-in-time carried onto the LME calendar) and the panel's duty-parity column, not through the module."""
    _need(TABLES_DIR / "var_mcx_beta.csv", TABLES_DIR / "mcx_basis_risk.csv")
    from desk.data import mcx as mcx_data
    from desk import WINDOW_END, WINDOW_START

    tab = pd.read_csv(TABLES_DIR / "var_mcx_beta.csv").set_index("sampling")
    p3 = pd.read_csv(TABLES_DIR / "mcx_basis_risk.csv")
    p3 = p3[p3["scope"] == "BOOK"].set_index("metric")["value"]
    assert tab.at["daily", "beta"] == pytest.approx(p3["unit_beta_beta"], abs=1e-6)
    assert tab.at["daily", "r2"] == pytest.approx(p3["unit_beta_beta_r2"], abs=1e-6)

    panel = pd.read_csv(PROCESSED_DIR / "market_daily.csv", usecols=["date", "mcx_al_m1_inr_kg"],
                        parse_dates=["date"]).set_index("date")["mcx_al_m1_inr_kg"]
    mir = pd.read_csv(mcx_data.THIRDPARTY_CSV, parse_dates=["date"]).set_index("date").sort_index()["m1_close_inr_kg"]
    mir = mir.reindex(panel.index, method="ffill")

    def slope(y, X):
        X = np.column_stack([np.ones(len(X)), X])
        return np.linalg.lstsq(X, y, rcond=None)[0][1:].sum()

    lo, hi = pd.Timestamp(WINDOW_START), pd.Timestamp(WINDOW_END)
    d = pd.DataFrame({"x": panel, "y": mir}).loc[lo:hi]
    wk = d.resample("W-FRI").last().diff().dropna()
    assert tab.at["weekly", "beta"] == pytest.approx(slope(wk["y"].to_numpy(), wk[["x"]].to_numpy()), abs=1e-4)
    dx = panel.diff()
    ll = pd.DataFrame({"y": mir.diff(), "a": dx.shift(1), "b": dx, "c": dx.shift(-1)}).loc[d.index[1:]].dropna()
    assert tab.at["lead_lag", "beta"] == pytest.approx(slope(ll["y"].to_numpy(), ll[["a", "b", "c"]].to_numpy()),
                                                       abs=1e-4)
    # the reading the docs rely on: daily < weekly < lead/lag, VaR falls as beta rises, base VaR is the unit-beta row
    assert tab.at["daily", "beta"] < tab.at["weekly", "beta"] < tab.at["lead_lag", "beta"]
    assert tab.at["daily", "var_mean_garch_inr"] > tab.at["weekly", "var_mean_garch_inr"] > \
        tab.at["engine_unit_beta", "var_mean_garch_inr"]
    s = pd.read_csv(TABLES_DIR / "var_summary.csv").set_index("metric")["value"]
    assert tab.at["engine_unit_beta", "var_mean_garch_inr"] == pytest.approx(float(s["var_mean_garch"]), abs=0.01)
    assert tab.at["weekly", "var_mean_garch_inr"] == pytest.approx(
        float(s["garch_var_mcx_beta_weekly_sensitivity_mean"]), abs=0.01)
