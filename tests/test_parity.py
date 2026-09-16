"""Phase 1 — import parity model (CONTRACTS §5 / §5a), sensitivities, quality settlement, term structure."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from desk import config
from desk.parity import model, quality, sensitivity, term_structure
from desk.paths import INTERIM_DIR, PROCESSED_DIR, TABLES_DIR

PANEL_CSV = PROCESSED_DIR / "market_daily.csv"


def _need(*paths):
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"Phase 0 outputs missing: {missing}")


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    _need(PANEL_CSV)
    return pd.read_csv(PANEL_CSV, parse_dates=["date"])


@pytest.fixture(scope="module")
def market(panel) -> pd.DataFrame:
    return model.weekly_market(panel)


@pytest.fixture(scope="module")
def inputs(market) -> pd.DataFrame:
    return model.build_inputs(market)


@pytest.fixture(scope="module")
def parity(inputs) -> pd.DataFrame:
    return model.build_parity_weekly(inputs)


def _row(df, week, grade, lane):
    sub = df[(df["week_end"] == pd.Timestamp(week)) & (df["grade"] == grade) & (df["lane"] == lane)]
    assert len(sub) == 1
    return sub.iloc[0]


# ------------------------------------------------------------------------------------------------ calendar & shape
def test_weekly_calendar_and_window(market, panel):
    we = pd.DatetimeIndex(market["week_end"])
    assert we[0] == pd.Timestamp("2022-01-07") and we[-1] == pd.Timestamp("2022-10-28")
    assert (we.dayofweek == 4).all() and (np.diff(we.asi8) == 7 * 86400 * 10**9).all()
    days = pd.DatetimeIndex(panel["date"])
    for r in market.itertuples():
        in_week = days[(days > r.week_end - pd.Timedelta(days=7)) & (days <= r.week_end)]
        assert r.value_date == in_week.max()
    win = market[market["in_window"]]
    assert len(win) == 27
    assert win["week_end"].min() == pd.Timestamp("2022-03-04") and win["week_end"].max() == pd.Timestamp("2022-09-02")


def test_output_columns_follow_contract(parity):
    for col in model.KEY_COLUMNS + model.LINE_ITEMS + model.CASE_FLAGS + ["net_arb_usd_t"]:
        assert col in parity.columns, col
    assert len(parity) == 43 * len(model.GRADES) * len(model.LANES)
    assert not parity[model.LINE_ITEMS].isna().any().any()
    allowed = ("_usd_t", "_inr_t", "_inr_kg", "_frac", "_pa", "_mt", "_scale", "_src", "_contract", "usdinr",
               "grade_factor", "week_end", "value_date", "grade", "lane", "in_window", "window_open")
    for col in parity.columns:
        assert col.endswith(allowed) or col.startswith(("open_", "trade_", "usdinr", "customs_usdinr")), col


# ------------------------------------------------------------------------------------------------ hand recompute
def test_hand_recompute_one_full_row(panel):
    """2022-05-13 Taint/Tabor JEA_NSA, typed out from the register and the panel without model helpers."""
    week, grade = pd.Timestamp("2022-05-13"), "taint_tabor"
    p = panel.set_index("date")
    day = p.loc[week - pd.Timedelta(days=6):week].index.max()
    m = p.loc[day]
    v = lambda k: config.value(k, day.date())  # noqa: E731
    gf = v("grade_factor_taint_tabor")
    cfr = m["lme_3m_usd_t"] * gf
    scale = v("container_payload_mt_20ft") / v("container_payload_mt_20ft_taint_tabor")
    freight = m["freight_jea_nsa_usd_t"] * scale
    ins = v("insurance_rate") * v("insured_value_uplift") * cfr
    cif = cfr + ins
    av = cif * v("customs_usdinr_import")
    goods = cif * m["usdinr_fwd_1m"]
    bcd = av * v("bcd_scrap_hs7602")
    sws = bcd * v("sws_rate_on_bcd")
    igst = (av + bcd + sws) * v("igst_rate_hs7602")
    port = v("port_cf_charges_inr_t_nsa") * scale + v("psic_cost_usd_per_box") * m["usdinr"] / v(
        "container_payload_mt_20ft_taint_tabor")
    fin = (goods + bcd + sws) * v("finance_days_jea_nsa") / 365 * v("wc_rate_inr_pa")
    igst_fin = igst * v("igst_credit_lag_days") / 365 * v("wc_rate_inr_pa")
    landed = goods + bcd + sws + port + fin + igst_fin
    rec = (1 - v("moisture_frac_taint_tabor")) * (1 - v("contamination_frac_taint_tabor")) * v(
        "metal_yield_frac_taint_tabor")
    anchor = m["mcx_al_m1_inr_kg"] * 1000 + v("domestic_anchor_premium_inr_t")
    byprod = (1 - v("moisture_frac_taint_tabor")) * v("heavies_frac_taint_tabor") * v(
        "heavies_net_value_frac_of_lme_al") * m["lme_3m_usd_t"] * m["usdinr"]
    conv = v("conversion_cost_inr_t") * rec
    net = anchor * rec + byprod - landed - conv
    expected = {"cfr_usd_t": cfr, "payload_scale": scale, "freight_usd_t": freight, "fob_usd_t": cfr - freight,
                "insurance_usd_t": ins, "cif_usd_t": cif, "av_customs_inr_t": av, "goods_inr_t": goods,
                "bcd_inr_t": bcd, "sws_inr_t": sws, "igst_inr_t": igst, "port_inr_t": port, "finance_inr_t": fin,
                "igst_finance_inr_t": igst_fin, "landed_inr_t": landed, "recovery_frac": rec, "anchor_inr_t": anchor,
                "byproduct_inr_t": byprod, "conversion_inr_t": conv, "net_arb_inr_t": net}
    row = model.parity_row(week, grade, "JEA_NSA")
    for k, val in expected.items():
        assert row[k] == pytest.approx(val, rel=1e-12, abs=1e-9), k
    assert bool(row["window_open"]) == (net > v("margin_threshold_inr_t"))
    assert v("igst_itc_available") is True
    assert row["customs_fx_src"] == "CBIC_NOTIFIED"


def test_usec_row_uses_m2_no_psic_and_lane_finance(parity, panel):
    r = _row(parity, "2022-07-08", "tense", "USEC_MUN")
    m = panel.set_index("date").loc[r["value_date"]]
    assert r["mcx_contract"] == "M2"
    assert r["anchor_inr_t"] == pytest.approx(m["mcx_al_m2_inr_kg"] * 1000 + config.value("domestic_anchor_premium_inr_t"))
    assert r["payload_scale"] == pytest.approx(1.0)
    assert r["port_inr_t"] == pytest.approx(config.value("port_cf_charges_inr_t_mun"))
    fin = (r["goods_inr_t"] + r["bcd_inr_t"] + r["sws_inr_t"]) * config.value("finance_days_usec_mun") / 365 * \
        config.value("wc_rate_inr_pa", r["value_date"].date())
    assert r["finance_inr_t"] == pytest.approx(fin)
    assert r["freight_base_usd_t"] == pytest.approx(m["freight_usec_mun_usd_t"])


def test_customs_fx_fallback_outside_notifications(parity):
    jan = parity[parity["week_end"] == pd.Timestamp("2022-01-14")].iloc[0]
    assert jan["customs_fx_src"] == "MARKUP_FALLBACK"
    assert jan["customs_usdinr_import"] == pytest.approx(jan["usdinr"] * (1 + config.value("customs_fx_markup_frac")))
    win = parity[parity["in_window"]]
    assert (win["customs_fx_src"] == "CBIC_NOTIFIED").all()


def test_units_and_memo(parity):
    assert np.allclose(parity["net_arb_usd_t"] * parity["usdinr"], parity["net_arb_inr_t"])
    assert np.allclose(parity["anchor_inr_t"], parity["mcx_anchor_inr_kg"] * 1000
                       + config.value("domestic_anchor_premium_inr_t"))
    rec = parity.groupby("grade")["recovery_frac"].first()
    assert rec["zorba"] == pytest.approx(0.99 * 0.94 * 0.93)
    assert rec["taint_tabor"] == pytest.approx(0.995 * 0.98 * 0.92)
    assert rec["tense"] == pytest.approx(0.995 * 0.98 * 0.94)
    assert np.allclose(parity["conversion_inr_t"], config.value("conversion_cost_inr_t") * parity["recovery_frac"])
    assert (parity.loc[parity["grade"] != "zorba", "byproduct_inr_t"] == 0).all()


def test_grade_factor_is_mix_plus_differential(inputs):
    mix = config.get("grade_factor_mix")
    for g in model.GRADES:
        sub = inputs[inputs["grade"] == g]
        want = [mix.at(d.date()) + config.value(f"grade_factor_diff_{g}") for d in sub["value_date"]]
        assert np.allclose(sub["grade_factor"], want, atol=1e-9)


# ------------------------------------------------------------------------------------------------ §5a
def test_section_5a_flag_logic(parity, inputs):
    assert (parity["trade_eligible"] == (parity["open_base"] & parity["open_pit_mix"] & parity["open_conv18k"])).all()
    assert (parity["open_base"] == parity["window_open"]).all()
    assert model.conversion_step_above_base() == 18000
    assert np.allclose(parity["net_arb_conv18k_inr_t"],
                       parity["net_arb_inr_t"] - (18000 - config.value("conversion_cost_inr_t")) * parity["recovery_frac"])
    assert (~parity["open_conv18k"] | parity["open_base"]).all()  # stricter cost can only close a window
    pit = model.compute(model.apply_overrides(inputs, model.mix_variant_overrides("grade_factor_mix_pit")))
    assert np.allclose(pit["net_arb_inr_t"], parity["net_arb_pit_mix_inr_t"])
    assert (parity["open_pit_mix"] == (parity["net_arb_pit_mix_inr_t"] > parity["margin_threshold_inr_t"])).all()


def test_no_hindsight_gate_is_published_and_the_5a_rule_is_unchanged(parity, inputs):
    """§6.1: `trade_eligible` is frozen; `trade_eligible_pit` is the disclosure beside it, not a replacement."""
    # the ex-ante rule is untouched by the disclosure column
    assert (parity["trade_eligible"] == (parity["open_base"] & parity["open_pit_mix"] & parity["open_conv18k"])).all()
    # the point-in-time screen never binds on this panel: it closes nothing conv18k does not already close
    win = parity[parity["in_window"]]
    assert int((win["open_base"] & win["open_conv18k"] & ~win["open_pit_mix"]).sum()) == 0
    assert (win["trade_eligible"] == win["open_conv18k"]).all()
    # the honest gate applies the point-in-time mix to BOTH legs and is strictly the both-changes case
    both = model.compute(model.apply_overrides(inputs, model.section_5a_overrides()["open_pit_conv18k"]))
    assert np.allclose(both["net_arb_inr_t"], parity["net_arb_pit_conv18k_inr_t"])
    assert (parity["open_pit_conv18k"] == (parity["net_arb_pit_conv18k_inr_t"]
                                           > parity["margin_threshold_inr_t"])).all()
    assert (parity["trade_eligible_pit"] == (parity["open_pit_mix"] & parity["open_pit_conv18k"])).all()
    # a stricter conversion cost can only close a window, on the point-in-time mix as on the base one
    assert (~parity["open_pit_conv18k"] | parity["open_pit_mix"]).all()
    # and it really does open the weeks the published rule stood aside from, including the June-July trough
    extra = win[win["trade_eligible_pit"] & ~win["trade_eligible"]]
    assert len(extra) > 0
    assert ((extra["week_end"] >= "2022-06-17") & (extra["week_end"] <= "2022-07-15")).any()


def test_eligible_on_uses_latest_week_end_on_or_before(parity):
    ok, we, row = model.eligible_on("2022-03-09", "zorba", "JEA_NSA", parity)
    assert we == pd.Timestamp("2022-03-04") and ok == bool(row["trade_eligible"])
    ok, we, _ = model.eligible_on(dt.date(2022, 3, 11), "zorba", "JEA_NSA", parity)
    assert we == pd.Timestamp("2022-03-11")
    ok, we, _ = model.eligible_on("2022-06-20", "zorba", "JEA_NSA", parity)
    assert we == pd.Timestamp("2022-06-17") and ok is False
    assert model.eligible_on("2022-01-06", "tense", "USEC_MUN", parity) == (False, None, None)
    with pytest.raises(ValueError):
        model.eligible_on("2022-11-10", "tense", "USEC_MUN", parity)
    with pytest.raises(KeyError):
        model.eligible_on("2022-03-09", "zorba90", "JEA_NSA", parity)


def test_csv_on_disk_matches_fresh_build(parity):
    path = TABLES_DIR / "parity_weekly.csv"
    if not path.exists():
        pytest.skip("run desk.parity.run first")
    disk = model.load_parity(path)
    assert list(disk.columns) == list(parity.columns)
    num = [c for c in parity.columns if pd.api.types.is_float_dtype(parity[c])]
    assert np.allclose(disk[num].to_numpy(float), parity[num].to_numpy(float), atol=0.01)
    for c in model.CASE_FLAGS:
        assert (disk[c] == parity[c]).all()


# ------------------------------------------------------------------------------------------------ overrides
def test_overrides_leave_base_unchanged(inputs):
    snapshot = inputs.copy(deep=True)
    base = model.compute(inputs)
    s = pd.Series(300.0, index=pd.DatetimeIndex(inputs["week_end"].unique()))
    over = {"conversion_cost_inr_t": 30000.0, "grade_factor_tense": 0.5, "mcx_anchor_inr_kg": s,
            "usdinr_goods": lambda b: b["usdinr"].to_numpy(float)}
    shocked = model.compute(model.apply_overrides(inputs, over))
    pd.testing.assert_frame_equal(inputs, snapshot)
    pd.testing.assert_frame_equal(model.compute(inputs), base)
    ins2 = model.apply_overrides(inputs, over)
    assert (ins2.loc[ins2["grade"] == "tense", "grade_factor"] == 0.5).all()
    assert (ins2.loc[ins2["grade"] != "tense", "grade_factor"] == inputs.loc[inputs["grade"] != "tense",
                                                                              "grade_factor"]).all()
    assert not np.allclose(shocked["net_arb_inr_t"], base["net_arb_inr_t"])
    # a key feeding two input columns updates both
    ins3 = model.apply_overrides(inputs, {"container_payload_mt_20ft_zorba": 24.0})
    z = (ins3["grade"] == "zorba") & (ins3["lane"] == "JEA_NSA")
    assert (ins3.loc[z, "container_payload_grade_mt"] == 24.0).all()
    assert (ins3.loc[z, "container_payload_20ft_grade_mt"] == 24.0).all()
    assert (ins3.loc[ins3["grade"] == "zorba", "container_payload_20ft_grade_mt"] == 24.0).all()  # lane-free key
    assert (ins3.loc[(ins3["grade"] == "zorba") & (ins3["lane"] == "USEC_MUN"), "container_payload_grade_mt"]
            == 21.0).all()
    assert (ins3.loc[ins3["grade"] != "zorba", "container_payload_20ft_grade_mt"]
            == inputs.loc[inputs["grade"] != "zorba", "container_payload_20ft_grade_mt"]).all()
    with pytest.raises(KeyError):
        model.apply_overrides(inputs, {"not_a_key": 1.0})


def test_market_shock_rederives_dependents(inputs):
    sub = inputs[(inputs["week_end"] == pd.Timestamp("2022-04-08"))].reset_index(drop=True)
    base = model.compute(sub)
    assert model.market_shock_overrides() == {}
    up = model.compute(model.apply_overrides(sub, model.market_shock_overrides(lme_shock_frac=0.10)))
    ins_up = model.apply_overrides(sub, model.market_shock_overrides(lme_shock_frac=0.10))
    assert np.allclose(ins_up["mcx_anchor_inr_kg"], sub["mcx_anchor_inr_kg"] * 1.10)  # premium 0 in the register
    assert np.allclose(up["av_customs_inr_t"], base["av_customs_inr_t"] * 1.10)
    assert np.allclose(up["byproduct_inr_t"], base["byproduct_inr_t"] * 1.10)
    fx = model.apply_overrides(sub, model.market_shock_overrides(usdinr_level=80.0))
    ratio = 80.0 / sub["usdinr"]
    assert np.allclose(fx["usdinr_goods"], sub["usdinr_goods"] * ratio)
    assert np.allclose(fx["customs_usdinr_import"], sub["customs_usdinr_import"] * ratio)
    assert np.allclose(fx["mcx_anchor_inr_kg"], sub["mcx_anchor_inr_kg"] * ratio)
    cfr_terms = model.compute(model.apply_overrides(sub, model.market_shock_overrides(freight_shock_frac=0.6)))
    assert np.allclose(cfr_terms["net_arb_inr_t"], base["net_arb_inr_t"])
    fob_terms = model.compute(model.apply_overrides(
        sub, model.market_shock_overrides(freight_shock_frac=0.6, freight_on_buyer=True)))
    assert np.allclose(fob_terms["fob_usd_t"], base["fob_usd_t"])
    assert np.allclose(fob_terms["cfr_usd_t"] - base["cfr_usd_t"], 0.6 * base["freight_usd_t"])


# ------------------------------------------------------------------------------------------------ sensitivities
@pytest.fixture(scope="module")
def cases(market, panel):
    return sensitivity.build_cases(market, panel, sensitivity.load_mirror())


def test_required_cases_present_and_base_matches(cases, inputs, parity):
    names = {c.name for c in cases}
    for n in ["base", "mix_lag1", "mix_lag3", "mix_pit", "grade_diff_q25", "grade_diff_q75", "anchor_sticky_trailing",
              "anchor_mirror_m1", "metal_yield_low", "metal_yield_high", "heavies_value_0.4", "heavies_value_1.5"]:
        assert n in names
    for prem in config.value("domestic_anchor_premium_sensitivity_inr_t"):
        assert f"anchor_premium_{int(prem):+d}" in names
    for conv in config.value("conversion_cost_sensitivity_inr_t_ingot"):
        assert f"conversion_{int(conv)}" in names
    long = sensitivity.sensitivity_cases_table(inputs, cases)
    b = long[long["case"] == "base"]
    assert np.allclose(b["net_arb_inr_t"].to_numpy(), parity["net_arb_inr_t"].to_numpy())
    pit = long[long["case"] == "mix_pit"]
    assert (pit["window_open"].to_numpy() == parity["open_pit_mix"].to_numpy()).all()
    c18 = long[long["case"] == "conversion_18000"]
    assert (c18["window_open"].to_numpy() == parity["open_conv18k"].to_numpy()).all()
    summary = sensitivity.sensitivity_summary(long, parity)
    assert set(summary["case"]) >= names | {"trade_eligible_5a"}
    assert (summary["n_weeks_in_window"] == 27).all()
    assert (summary.loc[summary["case"] == "base", "flips_vs_base"] == 0).all()


def test_sticky_anchor_is_trailing_mean(market, panel):
    s = sensitivity.sticky_anchor_spot_inr_kg(market, panel)
    d = market["value_date"].iloc[10]
    spot = panel.set_index("date")["mcx_al_spot_inr_kg"].loc[:d]
    assert s.iloc[10] == pytest.approx(spot.iloc[-config.value("domestic_anchor_trailing_bdays"):].mean())


def test_registered_ranges_match_phase0_evidence():
    ev = pd.read_csv(INTERIM_DIR / "price_evidence" / "grade_differentials.csv").set_index("grade")
    for g in model.GRADES:
        lo, hi = config.value(f"grade_factor_diff_quartiles_{g}")
        assert lo == pytest.approx(ev.loc[g, "p25_diff_clean"], abs=1e-4)
        assert hi == pytest.approx(ev.loc[g, "p75_diff_clean"], abs=1e-4)
        ylo, yhi = config.value(f"metal_yield_sensitivity_frac_{g}")
        assert ylo <= config.value(f"metal_yield_frac_{g}") <= yhi
    sched = " ".join(str(x) for x in config.value("rejection_penalty_schedule"))
    assert "1:1" in sched and config.value("spa_moisture_deduction_ratio") == 1.0
    assert f"{config.value('spa_contamination_discount_multiple'):g} ×" in sched
    assert f"{config.value('spa_contamination_rejection_excess_frac') * 100:g} percentage points" in sched


def test_grids_zero_at_base_and_reference_rules(inputs, parity):
    refs = sensitivity.reference_cases(parity)
    first = refs[0]
    elig = parity[parity["in_window"] & parity["trade_eligible"]]
    assert first.week_end == elig["week_end"].min()
    trough = refs[1]
    same = parity[(parity["grade"] == first.grade) & (parity["lane"] == first.lane)
                  & (parity["week_end"].dt.to_period("M") == sensitivity.REFERENCE_TROUGH_MONTH)]
    assert trough.week_end == same.loc[same["net_arb_inr_t"].idxmin(), "week_end"]
    # the third reference case is the long-lane counterpart of the first: same week and grade, other lane, added so
    # the §8 freight-scale figure is published rather than only computed in the doc generator
    long_lane = refs[2]
    assert long_lane.ref == "first_eligible_long_lane"
    assert (long_lane.week_end, long_lane.grade) == (first.week_end, first.grade) and long_lane.lane != first.lane
    n = len(refs)
    lf = sensitivity.lme_fx_grid(inputs, refs)
    base_cells = lf[(lf["lme_shock_pct"] == 0) & lf["usdinr_is_base"]]
    assert len(base_cells) == n and np.allclose(base_cells["pnl_impact_1000mt_inr"], 0.0, atol=1e-6)
    assert len(lf) == n * 9 * 10
    # monotone: a higher LME (same FX) raises this parity margin at every reference case
    at_base_fx = lf[lf["usdinr_is_base"]].sort_values(["ref_case", "lme_shock_pct"])
    assert (at_base_fx.groupby("ref_case")["pnl_impact_1000mt_inr"].diff().dropna() > 0).all()
    fd = sensitivity.freight_duty_grid(inputs, refs)
    zero = fd[(fd["freight_shock_pct"] == 0) & (fd["bcd_rate_pct"] == 2.5)]
    assert len(zero) == 2 * n and np.allclose(zero["pnl_impact_1000mt_inr"], 0.0, atol=1e-6)
    cfr = fd[fd["freight_terms"] == "CFR_seller_books_freight"]
    assert cfr.groupby(["ref_case", "bcd_rate_pct"])["pnl_impact_1000mt_inr"].nunique().max() == 1
    wide = sensitivity.lme_fx_wide(lf)
    assert wide.shape[0] == n * 9


def test_anchor_correlation_reproduces_phase0(panel):
    ac = sensitivity.anchor_correlation(panel, sensitivity.load_mirror())
    g = ac.set_index(["pair", "sample", "metric"])["value"]
    w = "window_2022-03-01_2022-08-31"
    assert g[("mirror_m1_vs_proxy_m1", w, "n_common_days")] == 125
    assert g[("mirror_m1_vs_proxy_m1", w, "level_corr")] == pytest.approx(0.988, abs=5e-4)
    assert g[("mirror_m1_vs_proxy_m1", w, "basis_mean_inr_kg")] == pytest.approx(-0.33, abs=5e-3)
    assert abs(g[("proxy_spot_vs_duty_paid_parity", w, "basis_mean_inr_kg")]) < 1e-3  # panel stored at 4 dp
    assert (ac["flag"] == "PROXY").all()


# ------------------------------------------------------------------------------------------------ quality
def test_settlement_schedule():
    base = quality.settle_weight_and_penalty("tense", 1000, 0.005, 0.02, price_usd_t=2000)
    assert base.payable_mt == 1000 and base.discount_frac == 0 and base.penalty_usd == 0 and not base.rejectable
    wet = quality.settle_weight_and_penalty("zorba", 1000, 0.03, 0.06)
    assert wet.weight_deduction_mt == pytest.approx(20.0) and wet.payable_mt == pytest.approx(980.0)
    dirty = quality.settle_weight_and_penalty("taint_tabor", 1000, 0.005, 0.04, price_usd_t=2000)
    assert dirty.discount_frac == pytest.approx(0.03) and dirty.penalty_usd == pytest.approx(0.03 * 2000 * 1000)
    assert not dirty.rejectable
    assert quality.settle_weight_and_penalty("taint_tabor", 1000, 0.005, 0.0601).rejectable
    hot = quality.settle_weight_and_penalty("tense", 500, 0.005, 0.02, 2000, radioactive=True)
    assert hot.mandatory_rejection and hot.payable_mt == 0 and hot.penalty_usd == 0
    assert quality.recovery_frac(0.01, 0.06, 0.93) == pytest.approx(0.99 * 0.94 * 0.93)


def test_quality_scenarios_zero_at_base(inputs, parity):
    ref = sensitivity.reference_cases(parity)[0]
    t = quality.scenario_table(ref.week_end, ref.lane, inputs)
    base = t[t["is_base_quality"]]
    assert len(base) == 3 and np.allclose(base["net_arb_impact_inr_t"], 0.0, atol=1e-6)
    assert np.allclose(base["spa_clause_value_inr_t"], 0.0, atol=1e-6)
    assert (t.loc[t["contamination_excess_frac"] > 0.03 + 1e-9, "outcome"] == "REJECTABLE").all()
    assert (t["spa_clause_value_inr_t"] >= -1e-6).all()  # the clauses never hurt the buyer


# ------------------------------------------------------------------------------------------------ term structure
def test_forward_curve_interpolation_and_classification():
    vd = pd.Timestamp("2022-06-17")
    p_cash, p_3m = term_structure.prompts(vd)
    assert p_cash == pd.Timestamp("2022-06-21") and p_3m == pd.Timestamp("2022-09-19")
    assert term_structure.forward_price(p_cash, 2474.0, 2502.0, p_cash, p_3m) == pytest.approx(2474.0)
    assert term_structure.forward_price(p_3m, 2474.0, 2502.0, p_cash, p_3m) == pytest.approx(2502.0)
    avg = term_structure.implied_month_average(pd.Period("2022-07", "M"), vd, 2474.0, 2502.0)
    assert 2474.0 < avg < 2502.0
    assert term_structure.classify(5.0) == "BACKWARDATION" and term_structure.classify(-5.0) == "CONTANGO"


def test_term_structure_tables(panel):
    w = term_structure.weekly_table(panel)
    assert len(w) == 43
    contango = w["lme_cash_3m_spread_usd_t"] < 0
    assert (w.loc[contango, "structure_effect_buyer_usd_t"] > 0).all()
    assert (w.loc[w["lme_cash_3m_spread_usd_t"] > 0, "structure_effect_buyer_usd_t"] < 0).all()
    r = term_structure.roll_table(panel, sensitivity.load_mirror())
    assert list(r["contract_month"]) == [f"2022-{m:02d}" for m in range(1, 11)]
    days = pd.DatetimeIndex(panel["date"])
    n = config.value("mcx_roll_days_before_expiry")
    for row in r.itertuples():
        assert days.get_loc(row.m1_expiry) - days.get_loc(row.roll_date) == n
        assert row.short_hedge_roll_yield_inr_t == pytest.approx((row.mcx_al_m2_inr_kg - row.mcx_al_m1_inr_kg) * 1000)
    assert (r["lots_per_1000mt"] == 200).all()


# ------------------------------------------------------------------------------------------------ determinism
def test_tables_are_deterministic():
    from desk.parity import run

    a = run.build()
    b = run.build()
    ta, tb = run.tables(a), run.tables(b)
    assert ta.keys() == tb.keys()
    for name in ta:
        assert run.csv_text(ta[name]) == run.csv_text(tb[name]), name
