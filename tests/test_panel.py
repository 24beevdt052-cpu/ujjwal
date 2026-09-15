"""Phase 0 integration: the canonical market panel, its provenance table and the generated Phase 0 docs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from desk import WINDOW_END, WINDOW_START, config
from desk.data import build_panel, dictionary, mcx
from desk.paths import PROCESSED_DIR

PANEL_CSV = PROCESSED_DIR / "market_daily.csv"
PROV_CSV = PROCESSED_DIR / "series_provenance.csv"
LME_CSV = PROCESSED_DIR / "lme_daily.csv"
FX_CSV = PROCESSED_DIR / "fx_rates_daily.csv"
FREIGHT_CSV = PROCESSED_DIR / "freight_weekly.csv"

# Typed out independently of build_panel.PANEL_COLUMNS so a silent rename in the module fails here (CONTRACTS §4.5).
CONTRACT_COLUMNS = [
    "date", "in_window",
    "lme_cash_usd_t", "lme_3m_usd_t", "lme_cash_3m_spread_usd_t", "lme_stock_mt",
    "usdinr", "usdinr_filled", "usdinr_src", "rbi_repo_pa", "fed_funds_upper_pa", "inr_rate_3m_pa", "usd_rate_3m_pa",
    "usd_rate_3m_filled", "rates_src", "fwd_premium_3m_pa", "usdinr_fwd_1m", "usdinr_fwd_3m",
    "mcx_al_spot_inr_kg", "mcx_al_m1_inr_kg", "mcx_al_m2_inr_kg", "mcx_m1_expiry", "mcx_m2_expiry", "mcx_src",
    "freight_jea_nsa_usd_t", "freight_usec_mun_usd_t", "freight_filled", "freight_src",
]


def _need(*paths):
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"run `run_all.py --only P0` first; missing {missing}")


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    _need(PANEL_CSV)
    return pd.read_csv(PANEL_CSV, parse_dates=["date"])


@pytest.fixture(scope="module")
def prov() -> pd.DataFrame:
    _need(PROV_CSV)
    return pd.read_csv(PROV_CSV)


@pytest.fixture(scope="module")
def win(panel) -> pd.DataFrame:
    return panel[panel["in_window"]]


# ------------------------------------------------------------------------------------------------ shape & calendar
def test_exact_contract_columns(panel):
    assert list(panel.columns) == CONTRACT_COLUMNS
    assert build_panel.PANEL_COLUMNS == CONTRACT_COLUMNS


def test_dates_unique_sorted_and_equal_lme_calendar(panel):
    _need(LME_CSV)
    lme = pd.read_csv(LME_CSV, parse_dates=["date"])
    assert panel["date"].is_unique and panel["date"].is_monotonic_increasing
    assert panel["date"].iloc[0] == pd.Timestamp("2018-01-02")
    assert panel["date"].iloc[-1] == pd.Timestamp("2022-12-30")
    assert panel["date"].tolist() == lme["date"].tolist()
    assert (panel["date"].dt.dayofweek < 5).all()


def test_window_flag_and_row_count(panel, win):
    expected = (panel["date"] >= pd.Timestamp(WINDOW_START)) & (panel["date"] <= pd.Timestamp(WINDOW_END))
    assert (panel["in_window"] == expected).all()
    assert 120 <= len(win) <= 135
    assert win["date"].iloc[0] == pd.Timestamp("2022-03-01")
    assert win["date"].iloc[-1] == pd.Timestamp("2022-08-31")


def test_no_nan_in_window_for_any_column(win):
    assert not win[CONTRACT_COLUMNS].isna().any().any(), win.isna().sum()[lambda s: s > 0].to_dict()


def test_no_nan_outside_freight_columns(panel):
    core = [c for c in CONTRACT_COLUMNS if c not in build_panel.FREIGHT_COLUMNS]
    assert not panel[core].isna().any().any()


def test_anchor_values_survive_the_join(panel):
    row = panel.set_index("date").loc["2022-03-07"]
    assert row["lme_cash_usd_t"] == 3984.5 and row["lme_3m_usd_t"] == 3968.0
    assert row["lme_cash_3m_spread_usd_t"] == pytest.approx(16.5)
    assert panel["lme_cash_usd_t"].idxmax() == panel.index[panel["date"] == "2022-03-07"][0]


# ------------------------------------------------------------------------------------------------ fill flags
def test_usd_rate_filled_flags_treasury_carries(panel):
    _need(FX_CSV)
    fx = pd.read_csv(FX_CSV, parse_dates=["date"])
    assert fx["usd_rate_3m_filled"].dtype == bool and panel["usd_rate_3m_filled"].dtype == bool
    win = panel[panel["in_window"]].set_index("date")
    # US holidays inside the window with an ECB/LME fixing but no Treasury print (Memorial Day, Juneteenth obs., July 4)
    for d in ("2022-05-30", "2022-06-20", "2022-07-04"):
        assert win.loc[d, "usd_rate_3m_filled"]
    assert (panel["usd_rate_3m_filled"] | ~panel["usdinr_filled"]).all()


def test_usdinr_filled_marks_exactly_the_days_missing_from_ecb(panel):
    _need(FX_CSV)
    fx = pd.read_csv(FX_CSV, parse_dates=["date"])
    not_in_ecb = ~panel["date"].isin(fx["date"])
    assert (panel["usdinr_filled"] == not_in_ecb).all()
    assert panel["usdinr_filled"].sum() <= 20  # TARGET-only holidays (1 May); many more means a calendar bug
    obs = panel[~panel["usdinr_filled"]].set_index("date")
    f = fx.set_index("date").loc[obs.index]
    for col in ("usdinr", "inr_rate_3m_pa", "usd_rate_3m_pa", "usdinr_fwd_1m", "usdinr_fwd_3m"):
        np.testing.assert_allclose(obs[col], f[col])


def test_filled_fx_days_carry_the_previous_ecb_row(panel):
    _need(FX_CSV)
    fx = pd.read_csv(FX_CSV, parse_dates=["date"]).set_index("date")
    for d, row in panel[panel["usdinr_filled"]].set_index("date").iterrows():
        prev = fx.loc[:d].iloc[-1]
        assert np.busday_count(prev.name.date(), d.date()) <= build_panel.MAX_FILL_BDAYS
        assert row["usdinr"] == pytest.approx(prev["usdinr"])


def test_freight_flags_and_nans_are_consistent(panel):
    _need(FREIGHT_CSV)
    fr = pd.read_csv(FREIGHT_CSV, parse_dates=["week_end"])
    no_data = panel["freight_src"] == build_panel.NO_FREIGHT
    lanes = ["freight_jea_nsa_usd_t", "freight_usec_mun_usd_t"]
    assert panel.loc[no_data, lanes].isna().all().all()
    assert panel.loc[~no_data, lanes].notna().all().all()
    first_assessed = fr["week_end"].iloc[0] - pd.Timedelta(days=1)
    assert (panel.loc[no_data, "date"] < first_assessed).all()
    assert not panel.loc[no_data, "freight_filled"].any()
    assert panel["freight_filled"].dtype == bool


def test_freight_is_point_in_time_never_from_a_later_assessment(panel):
    """CONTRACTS §3: every day carries the latest week already assessed (Thursday = week_end − 1) on or before it."""
    _need(FREIGHT_CSV)
    fr = pd.read_csv(FREIGHT_CSV, parse_dates=["week_end"]).assign(assessed=lambda d: d["week_end"] - pd.Timedelta(days=1))
    p = panel[panel["freight_src"] != build_panel.NO_FREIGHT]
    m = pd.merge_asof(p[["date"]], fr[["assessed", "freight_usec_mun_usd_t", "freight_jea_nsa_usd_t"]],
                      left_on="date", right_on="assessed", direction="backward")
    np.testing.assert_allclose(p["freight_usec_mun_usd_t"], m["freight_usec_mun_usd_t"])
    np.testing.assert_allclose(p["freight_jea_nsa_usd_t"], m["freight_jea_nsa_usd_t"])
    assert (m["assessed"] <= p["date"].to_numpy()).all()
    assert (p["freight_filled"].to_numpy() == (m["assessed"] != p["date"].to_numpy()).to_numpy()).all()
    # Monday 7-Mar-2022 must see the week ending 4-Mar (assessed Thu 3-Mar), not the coming Thursday's 10-Mar value.
    mon = panel.set_index("date").loc["2022-03-07", "freight_usec_mun_usd_t"]
    assert mon == pytest.approx(fr.set_index("week_end").loc["2022-03-04", "freight_usec_mun_usd_t"])


def test_freight_mapping_unit_behaviour():
    """Thursday assessment is available from Thursday; Mon–Wed carry the previous week (flagged); a hole raises."""
    dates = pd.Series(pd.to_datetime(["2022-03-07", "2022-03-10", "2022-03-11", "2022-03-14", "2022-03-18"]))
    fr = pd.DataFrame({"week_end": pd.to_datetime(["2022-03-04", "2022-03-11", "2022-03-18"]),
                       "freight_jea_nsa_usd_t": [10.0, 11.0, 12.0], "freight_usec_mun_usd_t": [50.0, 55.0, 60.0],
                       "freight_src": ["A", "B", "C"]})
    out = build_panel.align_freight(dates, fr)
    assert out["freight_usec_mun_usd_t"].tolist() == [50.0, 55.0, 55.0, 55.0, 60.0]
    assert out["freight_filled"].tolist() == [True, False, True, True, True]
    early = build_panel.align_freight(pd.Series(pd.to_datetime(["2022-03-02"])), fr)
    assert early["freight_src"].tolist() == [build_panel.NO_FREIGHT] and early["freight_usec_mun_usd_t"].isna().all()
    hole = fr[fr["week_end"] != pd.Timestamp("2022-03-11")]
    with pytest.raises(ValueError, match="Freight gap"):
        build_panel.align_freight(pd.Series(pd.to_datetime(["2022-03-07", "2022-03-16"])), hole)


def test_fx_alignment_raises_on_long_gap():
    dates = pd.Series(pd.to_datetime(["2022-03-01", "2022-03-15"]))
    fx = pd.DataFrame({"date": pd.to_datetime(["2022-03-01"]), **{c: [1.0] for c in build_panel.fetch_fx.COLUMNS[1:]}})
    with pytest.raises(ValueError, match="FX gap"):
        build_panel.align_fx(dates, fx)


# ------------------------------------------------------------------------------------------------ MCX & units
def test_mcx_units_against_lme_times_usdinr(panel, win):
    parity = win["mcx_al_spot_inr_kg"] / (win["lme_cash_usd_t"] * win["usdinr"] / 1000.0)
    assert parity.between(0.9, 1.25).all()  # duty-paid parity ~1.08; outside this band is a ₹/kg vs ₹/t slip
    assert win["mcx_al_m1_inr_kg"].between(150, 400).all()
    if (panel["mcx_src"] == mcx.SRC_PROXY).all():
        duty = 1 + config.value("bcd_primary_al_hs7601") * (1 + config.value("sws_rate_on_bcd"))
        expected = win["lme_cash_usd_t"] * win["usdinr"] / 1000.0 * duty + config.value("mcx_domestic_premium_inr_kg")
        np.testing.assert_allclose(win["mcx_al_spot_inr_kg"], expected, atol=1e-3)
        assert (win["mcx_al_m2_inr_kg"] >= win["mcx_al_m1_inr_kg"]).all()


def test_mcx_expiries_are_ordered_and_close_to_mcx_calendar(panel):
    m1, m2 = pd.to_datetime(panel["mcx_m1_expiry"]), pd.to_datetime(panel["mcx_m2_expiry"])
    assert (m1 >= panel["date"]).all() and (m2 > m1).all()
    real = pd.to_datetime(pd.Series(config.value("mcx_al_expiry_dates_2022")))
    proxy = set(m1[panel["date"].dt.year == 2022])
    # The proxy rule ignores MCX holidays, so allow one calendar day of difference (30 vs 31 Aug 2022).
    for r in real:
        assert min(abs((p - r).days) for p in proxy) <= 1, r


def test_mcx_proxy_tracks_observed_mirror_within_sane_band(panel, win):
    obs = mcx.load_thirdparty()
    if obs is None:
        pytest.skip("third-party MCX mirror extract not present")
    j = win.set_index("date")[["mcx_al_m1_inr_kg"]].join(obs["m1_close_inr_kg"], how="inner").dropna()
    assert len(j) > 100
    ratio = j["m1_close_inr_kg"] / j["mcx_al_m1_inr_kg"]
    assert ratio.between(0.8, 1.2).all()
    assert abs(ratio.mean() - 1) < 0.03


# ------------------------------------------------------------------------------------------------ provenance
def test_provenance_covers_every_column_once(prov):
    assert list(prov.columns) == ["column", "flag", "source", "transformation", "unit"]
    assert prov["column"].tolist() == CONTRACT_COLUMNS
    assert set(prov["flag"]) <= set(config.VALID_FLAGS)
    assert prov[["source", "transformation", "unit"]].notna().all().all()


def test_provenance_flags_are_honest(panel, prov):
    flag = prov.set_index("column")["flag"]
    for col in ("lme_cash_usd_t", "lme_3m_usd_t", "lme_cash_3m_spread_usd_t", "lme_stock_mt"):
        assert flag[col] == "DIRECT"
    if (panel["usdinr_src"] != "MANUAL_RBI").any():
        assert flag["usdinr"] == "PROXY"
    if (panel["mcx_src"] == mcx.SRC_PROXY).any():
        assert flag[["mcx_al_spot_inr_kg", "mcx_al_m1_inr_kg", "mcx_al_m2_inr_kg"]].eq("PROXY").all()
    assert flag["freight_jea_nsa_usd_t"] == "ASSUMPTION"
    assert flag["freight_usec_mun_usd_t"] == "ASSUMPTION"  # level calibration is a judgement (CONTRACTS §4.3)
    assert flag["rbi_repo_pa"] == config.get("rbi_repo_rate_pa").flag == "DIRECT"  # CONTRACTS §4.2 (amended)
    fallback = panel["rates_src"].str.contains("FALLBACK").any()
    for col in ("inr_rate_3m_pa", "usd_rate_3m_pa", "fwd_premium_3m_pa", "usdinr_fwd_3m"):
        assert flag[col] == ("ASSUMPTION" if fallback else "PROXY")


def test_provenance_downgrades_rates_when_a_fallback_fed_the_panel(panel):
    fake = panel.copy()
    fake.loc[fake.index[:3], "rates_src"] = "USD:FALLBACK_FEDFUNDS_SPREAD|INR:OECD_IR3TIB"
    prov = build_panel.build_provenance(fake).set_index("column")
    assert prov.loc["usd_rate_3m_pa", "flag"] == "ASSUMPTION"
    assert prov.loc["usd_rate_3m_pa", "source"].startswith("FALLBACK USED")
    assert prov.loc["lme_cash_usd_t", "flag"] == "DIRECT"


def test_provenance_counts_manual_ffill_separately_and_only_promotes_without_proxy_days(panel):
    fake = panel.copy()
    fake["mcx_src"] = mcx.SRC_MANUAL
    fake.loc[fake.index[:2], "mcx_src"] = mcx.SRC_MANUAL_FFILL
    prov = build_panel.build_provenance(fake).set_index("column")
    assert prov.loc["mcx_al_m1_inr_kg", "flag"] == "DIRECT"
    assert f"{mcx.SRC_MANUAL_FFILL}=2" in prov.loc["mcx_al_m1_inr_kg", "transformation"]
    fake.loc[fake.index[5], "mcx_src"] = mcx.SRC_PROXY
    assert build_panel.build_provenance(fake).set_index("column").loc["mcx_al_m1_inr_kg", "flag"] == "PROXY"


# ------------------------------------------------------------------------------------------------ reproducibility
def test_rebuild_matches_file(panel):
    _need(LME_CSV, FX_CSV, FREIGHT_CSV)
    fresh = build_panel.build()
    on_disk = pd.read_csv(PANEL_CSV)
    pd.testing.assert_frame_equal(fresh.reset_index(drop=True), on_disk, check_dtype=False)


def test_generated_docs_match_inputs(panel, prov):
    text = dictionary.render_dictionary()
    for col in CONTRACT_COLUMNS:
        assert f"`{col}`" in text
    assert "FAIL" not in text.split("## Cross-file reconciliation")[1].split("## `data/processed")[0]
    log = dictionary.render_assumptions_log()
    frame = config.params_frame()
    for key in frame["key"]:
        assert f"### `{key}`" in log
    n_pending = sum(dictionary.split_verify(v)[0] == "PENDING" for v in frame["verify"])
    assert f"## Open items: PENDING ({n_pending})" in log
    assert dictionary.render_dictionary() == text  # deterministic


def test_split_verify_parses_status_words():
    assert dictionary.split_verify("PENDING — call the bank") == ("PENDING", "call the bank")
    assert dictionary.split_verify("VERIFIED 2026-09-16 via x") == ("VERIFIED", "2026-09-16 via x")
    assert dictionary.split_verify("N/A — assumption")[0] == "N/A"
    assert dictionary.split_verify("looks fine")[0] == "UNSPECIFIED"
