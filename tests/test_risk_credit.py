"""Phase 5 credit scoring (Table 6 row 4.3) and credit tracker (row 4.4).

The claims these tests stand behind, as docs/50_credit_scoring.md makes them:

* the synthetic training data is a documented, seeded process — the same seed gives the same rows, and the
  population default rate is the registered assumption, not whatever the draw happened to give;
* the fitted logistic model recovers the *signs* of the process that generated its data (the one thing a credit
  committee must be able to check), and every fit statistic is labelled as fit-to-synthetic, not real power;
* the tracker's exposure numbers are Phase 3's numbers (they tie to the P3 per-buyer file and to P2's booking-time
  advances), so utilisation is arithmetic on published exposures rather than a second valuation;
* a score dated `d` uses nothing dated after `d`: rebuilding the tracker from inputs truncated at `d` reproduces
  every row up to `d` exactly, and the truncation genuinely removes later bookings and receipts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from desk import RNG_SEED, SIM_LABEL, config
from desk.paths import CONFIG_DIR, TABLES_DIR
from desk.risk import credit_scoring as cs

P3_FILES = ("buyer_credit_exposure_by_trade_daily.csv", "buyer_credit_exposure_daily.csv", "book_exposures_daily.csv",
            "trade_credit_exposure.csv", "trade_cashflows.csv", "trade_book.csv")
HINDSIGHT_CUTOFFS = ("2022-05-09", "2022-07-26", "2022-09-20")


def _need_book():
    missing = [f for f in P3_FILES if not (TABLES_DIR / f).exists()]
    if missing or not (CONFIG_DIR / "counterparties.yaml").exists():
        pytest.skip(f"P2/P3 outputs not built yet: {missing}")


# ------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def run() -> cs.ModelRun:
    return cs.build_model(n_boot=0)


@pytest.fixture(scope="module")
def inputs():
    _need_book()
    from desk.risk import credit_tracker as ct
    return ct.load_inputs()


@pytest.fixture(scope="module")
def tracker(run, inputs):
    from desk.risk import credit_tracker as ct
    return ct.build_tracker(inputs, run.model)


@pytest.fixture(scope="module")
def buyers(tracker):
    return tracker[tracker["role"] == "BUYER"]


# ------------------------------------------------------------------------------------------------ generator
def test_generator_is_deterministic_under_the_desk_seed():
    a, b0a = cs.generate_synthetic(seed=RNG_SEED)
    b, b0b = cs.generate_synthetic(seed=RNG_SEED)
    pd.testing.assert_frame_equal(a, b)
    assert b0a == b0b
    c, _ = cs.generate_synthetic(seed=RNG_SEED + 1)
    assert not np.allclose(a["utilisation_frac"], c["utilisation_frac"])


def test_population_default_rate_is_the_registered_assumption(run):
    base = float(config.value("credit_synth_base_default_rate_annual_frac"))
    assert run.data["true_pd_12m_frac"].mean() == pytest.approx(base, abs=1e-9)
    assert len(run.data) == cs.N_SYNTH_BUYERS * cs.N_SYNTH_QUARTERS
    # the realised draw is a Bernoulli sample of that rate, not the rate itself
    n = len(run.data)
    assert abs(run.data["default_12m"].mean() - base) < 4 * np.sqrt(base * (1 - base) / n)


def test_split_is_by_buyer_and_every_row_is_labelled_synthetic(run):
    d = run.data
    per_buyer = d.groupby("buyer_id")["split"].nunique()
    assert (per_buyer == 1).all()
    test_share = d.loc[d["split"] == "test", "buyer_id"].nunique() / d["buyer_id"].nunique()
    assert test_share == pytest.approx(cs.TEST_FRAC_BUYERS, abs=0.005)
    assert (d["label"] == cs.SYNTH_LABEL).all()
    assert "SYNTHETIC" in cs.SYNTH_LABEL and d["buyer_id"].str.startswith("SYN_").all()


def test_dgp_betas_come_from_the_registered_odds_ratios():
    dgp = cs.load_dgp()
    for f, (key, inc) in cs.ODDS_RATIO_KEYS.items():
        assert np.exp(dgp.betas[f] * inc) == pytest.approx(float(config.value(key)))
        assert config.get(key).flag == "ASSUMPTION"


# ------------------------------------------------------------------------------------------------ model
def test_fitted_coefficient_signs_match_the_dgp(run):
    fitted, true = np.sign(run.model.coef_raw), np.sign(run.dgp.beta_vector)
    assert (fitted == true).all(), dict(zip(cs.FEATURES, run.model.coef_raw))
    # risk rises with utilisation, delinquency and dependence on the desk; falls with history
    expected = {"utilisation_frac": 1, "dpd_max_days": 1, "history_months": -1, "order_concentration_frac": 1}
    assert {f: int(s) for f, s in zip(cs.FEATURES, fitted)} == expected


def test_coefficient_table_reports_odds_ratios_and_bootstrap_signs():
    r = cs.build_model(n_boot=100)
    t = cs.coefficient_table(r.model, r.dgp, r.intercept_true, r.boot).set_index("term")
    for f in cs.FEATURES:
        row = t.loc[f]
        assert row["sign_match"]
        assert row["odds_ratio_per_increment_boot_p2_5"] <= row["odds_ratio_per_increment_fitted"] <= \
            row["odds_ratio_per_increment_boot_p97_5"]
        assert 0.0 <= row["boot_sign_match_share"] <= 1.0
    # standardised and raw coefficients describe the same model
    X = r.data[list(cs.FEATURES)].to_numpy(float)
    raw = r.model.intercept_raw + X @ r.model.coef_raw
    assert np.allclose(raw, r.model.logit(X))


def test_fit_statistics_are_labelled_as_fit_to_synthetic_not_real_power(run):
    m = cs.fit_metrics(run.model, run.data)
    assert m["note"].str.contains("NOT evidence of real predictive power").all()
    auc = m.set_index(["split", "metric"])["value"]
    assert 0.5 < auc[("test", "auc_fitted")] <= 1.0
    assert auc[("test", "auc_true_pd_oracle")] > 0.5


def test_bands_and_overlay_notch():
    cut = cs.band_cutoffs()
    assert cut["A"] < cut["B"] < cut["C"]
    got = cs.band_from_pd([cut["A"] - 1e-9, cut["A"], cut["B"] - 1e-9, cut["B"], cut["C"] - 1e-9, cut["C"], 0.9])
    assert list(got) == ["A", "B", "B", "C", "C", "D", "D"]
    assert list(cs.notch(["A", "B", "C", "D"], 1)) == ["B", "C", "D", "D"]
    assert list(cs.notch(["A", "C"], [0, 2])) == ["A", "D"]
    for b in cs.BANDS:
        pol = cs.band_policy(b)
        assert pol["band_max_advance_reliance_multiple"] <= float(
            config.value("buyer_advance_limit_multiple_of_credit_limit"))
        assert pol["band_max_credit_days"] <= int(config.value("max_domestic_credit_days"))


# ------------------------------------------------------------------------------------------------ tracker arithmetic
def test_tracker_exposures_tie_to_the_p3_buyer_files(buyers):
    p3 = pd.read_csv(TABLES_DIR / "buyer_credit_exposure_daily.csv", parse_dates=["date"])
    m = buyers.merge(p3, left_on=["date", "cp_id"], right_on=["date", "buyer_id"], how="left", suffixes=("", "_p3"))
    for col in ("receivable_inr", "presettlement_inr", "contracted_inr"):
        assert (m[col] - m[f"{col}_p3"].fillna(0.0)).abs().max() < 0.01, col
    have = m["utilisation_frac_p3"].notna()
    assert (m.loc[have, "utilisation_receivable_frac"] - m.loc[have, "utilisation_frac_p3"]).abs().max() < 1e-4
    by_trade = pd.read_csv(TABLES_DIR / "buyer_credit_exposure_by_trade_daily.csv", parse_dates=["date"])
    regrouped = by_trade.groupby(["date", "buyer_id"])["receivable_inr"].sum()
    idx = pd.MultiIndex.from_frame(buyers[["date", "cp_id"]])
    assert np.allclose(regrouped.reindex(idx).fillna(0.0).to_numpy(), buyers["receivable_inr"].to_numpy(), atol=0.01)


def test_utilisation_is_arithmetic_on_published_exposures(buyers, inputs):
    limits = {c.cp_id: c.credit_limit_inr for c in inputs.counterparties if c.credit_limit_inr}
    assert limits == {"BUY_MUN_01": 650_000_000.0, "BUY_JNPT_01": 560_000_000.0, "BUY_RJK_01": 120_000_000.0}
    b = buyers
    assert (b["credit_limit_inr"] == b["cp_id"].map(limits)).all()
    lim = b["credit_limit_inr"]
    assert np.allclose(b["utilisation_receivable_frac"], b["receivable_inr"] / lim)
    assert np.allclose(b["utilisation_contracted_frac"], b["contracted_inr"] / lim)
    assert np.allclose(b["advance_reliance_multiple"], b["advance_pending_inr"] / lim)
    p04 = (b["receivable_inr"] + b["presettlement_inr"] - b["advance_pending_inr"]).clip(lower=0.0)
    assert np.allclose(b["credit_exposure_p04_basis_inr"], p04)
    assert np.allclose(b["utilisation_p04_basis_frac"], p04 / lim)
    assert (b["contracted_inr"] + 0.01 >= b["advance_pending_inr"]).all()
    assert (b["breach_hard_receivable"] == (b["receivable_inr"] > lim)).all()


def test_published_phase3_and_p14_figures_are_reproduced(buyers):
    peak = buyers.groupby("cp_id")[["utilisation_receivable_frac", "utilisation_contracted_frac"]].max()
    assert peak.loc["BUY_JNPT_01", "utilisation_receivable_frac"] == pytest.approx(0.8341, abs=5e-5)
    assert peak.loc["BUY_RJK_01", "utilisation_receivable_frac"] == pytest.approx(0.7437, abs=5e-5)
    assert peak.loc["BUY_RJK_01", "utilisation_contracted_frac"] == pytest.approx(2.5711, abs=5e-5)
    rjk = buyers[buyers["cp_id"] == "BUY_RJK_01"].set_index("date")
    for d, mult in (("2022-05-09", 1.2635), ("2022-05-24", 1.5317), ("2022-07-26", 1.8274)):
        assert rjk.loc[pd.Timestamp(d), "advance_reliance_multiple"] == pytest.approx(mult, abs=5e-5)
        assert rjk.loc[pd.Timestamp(d), "flag_performance_advance_p14"]
    # P3 reports no receivable breach on this book (credit_limit_breach_days = 0)
    assert not buyers["breach_hard_receivable"].any()


def test_booking_time_advances_equal_the_realised_advance_legs(inputs):
    m = inputs.bookings.merge(inputs.advance_receipts, on=["trade_id", "sale_id"], how="inner")
    assert len(m) == int((inputs.bookings["advance_value_inr"] > 0).sum()) == 5
    assert (m["advance_value_inr"] - m["realised_advance_inr"]).abs().max() < 1.0


def test_days_past_due_lands_on_the_late_buyer_and_the_profile_prior_is_kept(buyers, inputs):
    dpd = buyers.groupby("cp_id")["days_past_due"].max()
    assert dpd.to_dict() == {"BUY_JNPT_01": 0, "BUY_MUN_01": 0, "BUY_RJK_01": 25}
    prior = {c.cp_id: c.profile.prior_dpd_max_days for c in inputs.counterparties}
    assert (buyers["feat_dpd_max_12m_days"] >= buyers["cp_id"].map(prior)).all()


def test_order_concentration_counts_only_sales_already_contracted(buyers, inputs):
    share = float(config.value("secondary_raw_material_cost_share"))
    rjk = next(c for c in inputs.counterparties if c.cp_id == "BUY_RJK_01")
    spend = rjk.profile.annual_turnover_inr * share
    row = buyers[buyers["cp_id"] == "BUY_RJK_01"].set_index("date")["feat_order_concentration_frac"]
    assert row.loc[pd.Timestamp("2022-05-06")] == 0.0
    assert row.loc[pd.Timestamp("2022-07-25")] == pytest.approx((151_620_000 + 245_070_000) / spend)
    assert row.loc[pd.Timestamp("2022-07-26")] == pytest.approx((151_620_000 + 245_070_000 + 313_267_500) / spend)


def test_overlay_notches_exactly_when_advance_reliance_exceeded_the_p14_cap(buyers):
    cap = float(config.value("buyer_advance_limit_multiple_of_credit_limit"))
    over = buyers["advance_reliance_peak_91d_multiple"] > cap
    assert (buyers.loc[over, "overlay_notches"] == 1).all() and (buyers.loc[~over, "overlay_notches"] == 0).all()
    assert (buyers["band_final"].to_numpy() == cs.notch(buyers["band_model"], buyers["overlay_notches"])).all()
    assert over.any()


# ------------------------------------------------------------------------------------------------ no hindsight
@pytest.mark.parametrize("cutoff", HINDSIGHT_CUTOFFS)
def test_scores_use_no_information_dated_after_the_row(cutoff, run, inputs, tracker):
    from desk.risk import credit_tracker as ct
    c = pd.Timestamp(cutoff)
    past = ct.build_tracker(inputs.truncated(c), run.model)
    full = tracker[tracker["date"] <= c].reset_index(drop=True)
    assert len(past) == len(full) > 0
    pd.testing.assert_frame_equal(past.reset_index(drop=True), full, check_exact=False, rtol=1e-12, atol=1e-9)


def test_truncation_really_removes_the_future(inputs):
    t = inputs.truncated("2022-07-26")
    assert set(t.bookings["trade_id"]) == {"T01", "T02", "T03", "T04", "T05", "T06", "T07"}
    t07 = t.advance_receipts[(t.advance_receipts["trade_id"] == "T07")]
    assert t07["received_date"].isna().all()                    # received 2022-08-12: unknown on 26-Jul
    assert t.calendar.max() == pd.Timestamp("2022-07-26")
    assert inputs.advance_receipts.loc[inputs.advance_receipts["trade_id"] == "T07", "received_date"].notna().all()


def test_booking_checks_use_the_band_at_the_previous_close(run, inputs, tracker):
    from desk.risk import credit_tracker as ct
    bk = ct.booking_checks(inputs, tracker)
    assert len(bk) == len(inputs.bookings)
    assert (bk["band_as_of_date"] < bk["contract_date"]).all()
    b = tracker[tracker["role"] == "BUYER"].set_index(["date", "cp_id"])
    for r in bk.itertuples():
        assert b.loc[(r.band_as_of_date, r.cp_id), "band_final"] == r.band_final_prev_close
    assert bk["label"].str.contains("RETROSPECTIVE").all()


# ------------------------------------------------------------------------------------------------ published files
def test_published_scores_are_ranked_and_labelled():
    path = TABLES_DIR / "credit_scores.csv"
    if not path.exists():
        pytest.skip("run desk.risk.run_credit first")
    s = pd.read_csv(path)
    assert list(s["rank_riskiest_first"]) == list(range(1, len(s) + 1))
    assert s["pd_model_annual_frac"].is_monotonic_decreasing
    assert s["label"].str.contains(SIM_LABEL).all() and s["label"].str.contains("SYNTHETIC").all()
    assert set(s["band_final"]) <= set(cs.BANDS)
    tr = pd.read_csv(TABLES_DIR / "credit_tracker.csv", usecols=["label"])
    assert tr["label"].str.contains(SIM_LABEL).all()
