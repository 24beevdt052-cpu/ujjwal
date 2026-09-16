"""Phase 5 margin & liquidity (Table 6 row 4.5) and the risk policy memo (row 4.6).

The claims these tests stand behind, as docs/51_margin_liquidity.md makes them:

* margin cash is Phase 3's margin cash: the published daily margin columns rebuild, independently, from the P3 hedge
  line table and from the MCX legs of `trade_cashflows.csv`, and the cash categories add back to P3's cash balance;
* headroom is plain arithmetic on registered facilities — limit − buffer − (commercial + margin + interest) — and
  the registered limits are what their ex-ante plan rule gives, not numbers tuned to the book;
* the margin stress re-marks MCX exactly: with a zero move it reproduces the actual variation margin and IM, and the
  99 % move it uses at a close depends on nothing after that close;
* the memo is one A4 page, carries the simulation label, and every number it quotes is recomputed here from the
  source table it came from.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from desk import HORIZON_END, SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.paths import PROCESSED_DIR, REPORTS_DIR, TABLES_DIR

UPSTREAM = ("mcx_variation_margin.csv", "book_exposures_daily.csv", "trade_cashflows.csv", "mtm_daily.csv",
            "var_vol_forecasts.csv", "var_garch_params.csv", "var_daily.csv", "var_summary.csv",
            "adverse_event_windows.csv", "parity_weekly.csv", "trade_book.csv", "credit_scores.csv",
            "credit_tracker.csv", "credit_tracker_bookings.csv", "credit_band_policy.csv",
            "attribution_daily.csv", "pnl_sensitivity_sign_robustness.csv")
OWN = ("margin_liquidity.csv", "margin_liquidity_fortnight.csv", "margin_liquidity_facility.csv",
       "margin_liquidity_policy_limits.csv", "margin_liquidity_summary.csv", "margin_liquidity_lc_lots.csv",
       "margin_liquidity_controls.csv", "margin_liquidity_limit_grid.csv")
TOL = 1.0
M = 1e6


def _need(files) -> None:
    missing = [f for f in files if not (TABLES_DIR / f).exists()]
    if missing:
        pytest.skip(f"upstream outputs not built yet: {missing}")


@pytest.fixture(scope="module")
def daily() -> pd.DataFrame:
    _need(UPSTREAM + OWN)
    return pd.read_csv(TABLES_DIR / "margin_liquidity.csv")


@pytest.fixture(scope="module")
def vm() -> pd.DataFrame:
    _need(UPSTREAM)
    return pd.read_csv(TABLES_DIR / "mcx_variation_margin.csv")


@pytest.fixture(scope="module")
def built():
    """The stage's in-memory build (no files written), for tests of the functions themselves."""
    _need(UPSTREAM)
    from desk.risk import liquidity as lq
    fac = lq.facility_params()
    inputs = lq.load_inputs(fac)
    d, lots, moves = lq.build_daily(inputs, fac)
    return lq, fac, inputs, d, lots, moves


@pytest.fixture(scope="module")
def memo_md() -> str:
    _need(UPSTREAM + OWN)
    p = REPORTS_DIR / "risk_policy_memo.md"
    if not p.exists():
        pytest.skip("risk_policy_memo.md not built yet")
    return p.read_text(encoding="utf-8")


def _nb(s: str) -> str:
    return s.replace(" ", " ")


# ------------------------------------------------------------------------------------------------ margin cash
def test_margin_cash_reconciles_to_vm_table(daily, vm):
    g = vm.groupby("date")
    ref = pd.DataFrame({"vm": g["vm_inr"].sum(), "txn": g["txn_cost_inr"].sum(),
                        "dim": g["im_change_inr"].sum(), "net": g["net_margin_cash_inr"].sum(),
                        "im": g["im_required_inr"].sum()}).reindex(daily["date"]).fillna(0.0)
    d = daily.set_index("date")
    assert (d["vm_inr"] - ref["vm"]).abs().max() <= TOL
    assert (d["txn_cost_inr"] - ref["txn"]).abs().max() <= TOL
    assert (d["mcx_im_inr"] - ref["im"]).abs().max() <= TOL
    assert (d["cum_margin_cash_inr"] - ref["net"].cumsum()).abs().max() <= TOL
    # a stock and its flows agree: cumulative cash = cumulative VM + charges − IM still posted
    assert (d["cum_vm_inr"] + d["cum_txn_cost_inr"] - d["mcx_im_inr"] - d["cum_margin_cash_inr"]).abs().max() <= TOL
    assert (d["margin_cash_deployed_inr"] + d["cum_margin_cash_inr"]).abs().max() <= TOL
    # the documented peaks (docs/31 §1.4) survive the rebuild
    assert d["margin_cash_deployed_inr"].idxmax() == "2022-03-24"
    assert d["margin_cash_deployed_inr"].max() == pytest.approx(105_707_065.17, abs=TOL)
    assert d["mcx_im_inr"].max() == pytest.approx(95_803_037.76, abs=TOL)


def test_margin_cash_reconciles_to_realised_mcx_cashflows(daily):
    cf = pd.read_csv(TABLES_DIR / "trade_cashflows.csv", usecols=["scenario", "leg_type", "settle_date", "amount_inr"])
    mcx = cf[(cf["scenario"] == "REALISED") & cf["leg_type"].str.startswith("MCX_")]
    by_day = mcx.groupby("settle_date")["amount_inr"].sum()
    cum = by_day.reindex(by_day.index.union(daily["date"])).fillna(0.0).cumsum().reindex(daily["date"])
    d = daily.set_index("date")
    assert (cum - d["cum_margin_cash_inr"]).abs().max() <= TOL
    assert (d["cash_mcx_margin_cum_inr"] - d["cum_margin_cash_inr"]).abs().max() <= TOL


def test_cash_categories_add_back_to_p3_cash_balance(daily):
    ex = pd.read_csv(TABLES_DIR / "book_exposures_daily.csv", usecols=["date", "scope", "cash_balance_inr"])
    book = ex[ex["scope"] == "book"].set_index("date")["cash_balance_inr"]
    d = daily.set_index("date")
    cats = [c for c in d.columns if c.startswith("cash_") and c.endswith("_cum_inr")]
    assert len(cats) == 9
    common = book.index
    assert (d.loc[common, cats].sum(axis=1) - book).abs().max() <= TOL
    assert (d.loc[common, "cash_balance_inr"] - book).abs().max() <= TOL
    assert d.loc[d.index < common.min(), cats].abs().to_numpy().max() == 0.0
    assert book.min() == pytest.approx(-1_159_856_632.73, abs=TOL)  # the P3 fact the brief starts from


def test_published_controls_all_pass():
    _need(OWN)
    c = pd.read_csv(TABLES_DIR / "margin_liquidity_controls.csv")
    assert len(c) >= 10 and (c["status"] == "PASS").all()


# ------------------------------------------------------------------------------------------------ facilities
def test_facility_headroom_arithmetic(daily):
    fb = float(config.value("liq_fb_wc_limit_inr"))
    lc = float(config.value("liq_nfb_lc_limit_inr"))
    buf = fb * float(config.value("liq_min_cash_buffer_frac_of_fb_limit"))
    d = daily
    md = pd.read_csv(TABLES_DIR / "mtm_daily.csv", usecols=["date", "leg_type", "realised_cum_inr"])
    fund = md[md["leg_type"] == "FUNDING"].groupby("date")["realised_cum_inr"].sum().reindex(d["date"]).fillna(0.0)
    need = -(d["cash_balance_inr"] + fund.to_numpy())
    assert np.allclose(d["funding_need_total_inr"], need, atol=TOL)
    assert np.allclose(d["commercial_funding_need_inr"] + d["margin_cash_deployed_inr"] + d["interest_accrued_inr"],
                       d["funding_need_total_inr"], atol=TOL)
    assert (d["fb_limit_inr"] == fb).all() and (d["min_cash_buffer_inr"] == buf).all()
    assert (d["lc_limit_inr"] == lc).all()
    assert np.allclose(d["headroom_inr"], fb - buf - d["funding_need_total_inr"], atol=TOL)
    assert np.allclose(d["undrawn_inr"], fb - d["funding_need_total_inr"], atol=TOL)
    assert np.allclose(d["fb_drawn_inr"], d["funding_need_total_inr"].clip(lower=0), atol=TOL)
    assert (d["flag_buffer_breach"] == (d["headroom_inr"] < 0)).all()
    assert (d["flag_fb_limit_breach"] == (d["funding_need_total_inr"] > fb)).all()
    assert (d["flag_lc_limit_breach"] == (d["lc_outstanding_inr"] > lc)).all()
    # a hard breach is always a buffer breach, never the other way round
    assert not (d["flag_fb_limit_breach"] & ~d["flag_buffer_breach"]).any()
    # the headline: the plan-sized line does not hold the book
    assert d["flag_fb_limit_breach"].sum() > 0 and d["funding_need_total_inr"].max() > fb


def test_registered_limits_equal_their_plan_rule():
    _need(UPSTREAM + OWN)
    wk = str(config.value("liq_plan_parity_week_end"))
    assert wk < str(WINDOW_START)                          # sized before the window: no hindsight in the size
    pw = pd.read_csv(TABLES_DIR / "parity_weekly.csv")
    p = pw[pw["week_end"] == wk]
    assert len(p) == 6
    rate = float(config.value("wc_rate_inr_pa", p["value_date"].iloc[0]))
    q = float(config.value("liq_plan_throughput_mt_pa"))
    rnd = float(config.value("liq_facility_rounding_inr"))
    fb_plan = q * ((p["finance_inr_t"] + p["igst_finance_inr_t"]) / rate).mean()
    lc_plan = q * (p["cif_usd_t"] * p["usdinr"]).mean() * float(config.value("liq_plan_lc_tenor_days")) / 365.0
    assert math.ceil(fb_plan / rnd) * rnd == float(config.value("liq_fb_wc_limit_inr"))
    assert math.ceil(lc_plan / rnd) * rnd == float(config.value("liq_nfb_lc_limit_inr"))
    fac = pd.read_csv(TABLES_DIR / "margin_liquidity_facility.csv").set_index("metric")["value"]
    assert float(fac["plan_avg_funded_balance_inr"]) == pytest.approx(fb_plan, abs=1.0)
    assert fac["fb_limit_matches_rule"] == "True" and fac["lc_limit_matches_rule"] == "True"


def test_liquidity_params_are_flagged_assumptions():
    keys = [k for k in config.load_params() if k.startswith(("liq_", "policy_"))]
    assert len(keys) >= 20
    for k in keys:
        p = config.get(k)
        assert p.file == "risk.yaml" and p.flag == "ASSUMPTION" and len(p.note) > 40, k


def test_limit_grid_is_monotone(daily):
    g = pd.read_csv(TABLES_DIR / "margin_liquidity_limit_grid.csv")
    for fac in ("FUND_BASED_WC", "NON_FUND_LC"):
        s = g[g["facility"] == fac].sort_values("limit_inr")
        assert s["days_limit_breach"].is_monotonic_decreasing
        assert s["registered"].sum() == 1
    no_breach = g.set_index("facility").at["FUND_BASED_WC_MIN_NO_BREACH", "limit_inr"]
    buf = float(config.value("liq_min_cash_buffer_frac_of_fb_limit"))
    assert no_breach * (1 - buf) == pytest.approx(daily["funding_need_total_inr"].max(), abs=1.0)


def test_lc_outstanding_ties_to_lot_table(daily):
    lots = pd.read_csv(TABLES_DIR / "margin_liquidity_lc_lots.csv")
    assert len(lots) == 19                                 # every bill-of-lading lot of the nine tickets
    mkt = pd.read_csv(PROCESSED_DIR / "market_daily.csv", usecols=["date", "usdinr"]).set_index("date")["usdinr"]
    usd = pd.Series(0.0, index=daily["date"])
    for r in lots.itertuples():
        assert r.lc_open_date < r.lc_release_date
        usd[(usd.index >= r.lc_open_date) & (usd.index < r.lc_release_date)] += r.lc_face_usd
    assert np.allclose(daily["lc_outstanding_usd"], usd.to_numpy(), atol=0.01)
    assert np.allclose(daily["lc_outstanding_inr"], usd.to_numpy() * mkt.reindex(daily["date"]).to_numpy(), atol=1.0)
    assert (lots["lc_face_usd"] >= lots["face_planned_usd"]).all()


# ------------------------------------------------------------------------------------------------ stress
def test_remark_on_actual_path_reproduces_actual_margin(built):
    lq, fac, inputs, d, _lots, moves = built
    dd = d.set_index("date")
    for w in (lq.crash_fortnight(inputs), lq.margin_fortnight(d)):
        days = lq.fortnight_days(d, w)
        f = lq.remark_fortnight(inputs, d, days, dd.loc[days, "lme_cash_usd_t"].to_numpy())
        assert len(f) == lq.FORTNIGHT_RETURNS + 1
        assert np.allclose(f["vm_stressed_inr"], f["vm_actual_inr"], atol=TOL)
        assert np.allclose(f["im_stressed_inr"], f["im_actual_inr"], atol=TOL)
        assert np.allclose(f["extra_margin_cash_out_inr"], 0.0, atol=TOL)
        assert np.allclose(f["im_actual_inr"].to_numpy(), dd.loc[days, "mcx_im_inr"].to_numpy(), atol=TOL)
        assert np.allclose(f["vm_actual_inr"].iloc[1:].to_numpy(), dd.loc[f["date"].iloc[1:], "vm_inr"].to_numpy(),
                           atol=TOL)


def test_adverse_stress_calls_cash_and_breaches(built):
    lq, fac, inputs, d, _lots, moves = built
    w = lq.crash_fortnight(inputs)
    f = lq.fortnight_stress(inputs, d, moves, w, fac)
    assert (w.start, w.end) == ("2022-04-22", "2022-05-09")
    assert f["stress_direction"].iloc[0] == "LME_UP"       # the book is net short MCX at the start close
    assert f["extra_margin_cash_out_stressed_im_inr"].iloc[-1] >= f["extra_margin_cash_out_inr"].iloc[-1] > 0
    assert f["lme_cash_stressed_usd_t"].iloc[-1] == pytest.approx(
        f["lme_cash_actual_usd_t"].iloc[0] * math.exp(f["stress_move_logret"].iloc[0]), rel=1e-12)
    # the move is the largest point-in-time reading at the start close
    m = moves.loc[w.start]
    readings = [m["move_normal_garch_logret"], m["move_normal_hist250_logret"], m["move_normal_hist60_logret"],
                m["move_empirical_up_logret"]]
    assert f["stress_move_logret"].iloc[0] == pytest.approx(max(readings))
    assert f["flag_buffer_breach_stressed_im"].sum() > f["flag_buffer_breach_actual"].sum()


def test_stress_move_uses_nothing_after_its_close(built):
    lq, fac, inputs, d, _lots, moves = built
    cut = "2022-04-22"
    import dataclasses
    trunc = dataclasses.replace(inputs, market=inputs.market.loc[:cut])
    dates = pd.Index([x for x in d["date"] if x <= cut], name="date")
    again = lq.stress_moves(trunc, dates, fac)
    pd.testing.assert_frame_equal(again, moves.loc[dates])
    # the GARCH parameters behind the move at a close were estimated on returns up to that close
    vf = inputs.vol.shift(-1).loc[dates]
    assert (vf["lme_garch_sample_end"] <= pd.Series(dates, index=dates)).all()


def test_margin_at_risk_by_hand(built, vm):
    lq, fac, _inputs, d, _lots, moves = built
    day = "2022-04-21"
    lines = vm[(vm["date"] == day) & ~vm["action"].isin(["exit", "roll_out"])]
    x = moves.at[day, "stress_move_up_logret"]
    kg = lines["lots"] * lines["lot_mt"] * 1000.0
    notional = float((kg * lines["settle_inr_kg"]).sum())
    call15 = -notional * (math.exp(x) - 1) + float(lines["im_stress_015_inr"].sum()) * math.exp(x) \
        - float(lines["im_required_inr"].sum())
    row = d.set_index("date").loc[day]
    assert row["mar_99_stressed_im_inr"] == pytest.approx(call15, abs=TOL)
    assert row["mar_direction"] == "LME_UP"


def test_margin_fortnight_is_the_worst_ten_days(daily):
    w = daily[daily["in_window"]].reset_index(drop=True)
    flows = w["net_margin_cash_inr"].to_numpy()
    sums = [flows[i + 1:i + 11].sum() for i in range(len(flows) - 10)]
    i = int(np.argmin(sums))
    win = pd.read_csv(TABLES_DIR / "margin_liquidity_windows.csv").set_index("window")
    assert (win.at["MARGIN_FORTNIGHT", "start"], win.at["MARGIN_FORTNIGHT", "end"]) == (w.at[i, "date"],
                                                                                       w.at[i + 10, "date"])
    ev = pd.read_csv(TABLES_DIR / "adverse_event_windows.csv").set_index("event")
    assert win.at["CRASH_FORTNIGHT", "start"] == ev.at["E1_CRASH_FORTNIGHT", "start"]


def test_build_is_deterministic(built, daily):
    lq, fac, inputs, d, _lots, _moves = built
    d2, _, _ = lq.build_daily(lq.load_inputs(fac), fac)
    pd.testing.assert_frame_equal(d, d2)
    pub = daily.drop(columns=[c for c in daily.columns if c.startswith("in_") and c != "in_window"])
    assert list(pub.columns) == list(d.columns)


# ------------------------------------------------------------------------------------------------ PDF helper
def test_pdf_helper_renders_generic_markdown(tmp_path):
    from desk.reporting.pdf import count_pdf_pages, parse_markdown, render_markdown_pdf
    md = ("# Title ₹ −\n\nPara with **bold**, *italic* and `code` & <angle>.\n\n- one\n- two\n  continued\n\n"
          "> callout\n\n<!-- widths: 0.3, 0.7 -->\n| a | b \\| c |\n|---|--:|\n| 1 | 2 |\n\n---\n1. first\n")
    kinds = [b.kind for b in parse_markdown(md)]
    assert kinds == ["title", "para", "bullets", "callout", "table", "rule", "numbers"]
    table = parse_markdown(md)[4]
    assert table.rows[0] == ["a", "b | c"] and table.align == ["LEFT", "RIGHT"] and table.widths == [0.3, 0.7]
    p1, p2 = tmp_path / "a.pdf", tmp_path / "b.pdf"
    assert render_markdown_pdf(md, p1) == 1 == count_pdf_pages(p1)
    render_markdown_pdf(md, p2)
    assert p1.read_bytes() == p2.read_bytes()                # invariant build: byte-identical
    assert render_markdown_pdf(md * 40, p2) == count_pdf_pages(p2) > 1
    with pytest.raises(ValueError):
        render_markdown_pdf(md, p2, footer_text="no label")


# ------------------------------------------------------------------------------------------------ memo
def test_memo_pdf_is_exactly_one_page(memo_md, tmp_path):
    from desk.reporting.pdf import count_pdf_pages, render_markdown_pdf
    from desk.risk.policy_memo import MEMO_STYLE
    pdf = REPORTS_DIR / "risk_policy_memo.pdf"
    assert count_pdf_pages(pdf) == 1
    assert SIM_LABEL in memo_md
    again = tmp_path / "memo.pdf"
    assert render_markdown_pdf(memo_md, again, title="Risk policy memo — aluminium scrap desk (SIM)",
                               author="Head of Desk (SIM)", style=MEMO_STYLE) == 1
    assert again.read_bytes() == pdf.read_bytes()


def test_memo_is_dated_after_everything_it_quotes(memo_md):
    d = pd.Timestamp(config.value("policy_memo_date"))
    assert d > pd.Timestamp(HORIZON_END)
    assert d.strftime("%-d %B %Y") in memo_md


def test_memo_numbers_match_their_source_tables(memo_md):
    from desk.risk.policy_memo import inr_m, mt, usd_m
    md = _nb(memo_md)
    T = TABLES_DIR

    # headline P&L and its band (pnl_sensitivity_sign_robustness.csv, attribution_daily.csv)
    sr = pd.read_csv(T / "pnl_sensitivity_sign_robustness.csv").set_index("family")
    att = pd.read_csv(T / "attribution_daily.csv", usecols=["date", "trade_id", "cum_pnl_inr"])
    book = att[att["trade_id"] == "BOOK"].set_index("date")["cum_pnl_inr"]
    for s in (inr_m(book.loc[str(HORIZON_END)]), inr_m(sr.at["ALL_REGISTERED_BANDS", "pnl_min_inr"]),
              inr_m(sr.at["ALL_REGISTERED_BANDS", "pnl_max_inr"], sign=True), "−38,702"):
        assert _nb(s) in md, s
    assert "not sign-robust" in md

    # liquidity (margin_liquidity.csv)
    liq = pd.read_csv(T / "margin_liquidity.csv").set_index("date")
    assert _nb(inr_m(liq["funding_need_total_inr"].max())) in md and "20-Jul" in md
    assert _nb(inr_m(liq["lc_outstanding_inr"].max())) in md and "13-Jun" in md
    assert _nb(inr_m(liq["mar_99_stressed_im_inr"].max())) in md
    assert f"breached {int(liq['flag_fb_limit_breach'].sum())} days" in md
    assert f"LC breached {int(liq['flag_lc_limit_breach'].sum())} days" in md
    fort = pd.read_csv(T / "margin_liquidity_fortnight.csv")
    crash = fort[fort["window"] == "CRASH_FORTNIGHT"]
    assert _nb(inr_m(crash["extra_margin_cash_out_stressed_im_inr"].max())) in md
    assert _nb(inr_m(crash["headroom_stressed_im_inr"].min())) in md
    assert _nb(inr_m(crash["vm_actual_inr"].iloc[1:].sum(), sign=True)) in md

    # positions (book_exposures_daily.csv)
    ex = pd.read_csv(T / "book_exposures_daily.csv", usecols=["date", "scope", "lme_delta_physical_mt", "unsold_mt"])
    b = ex[(ex["scope"] == "book") & (ex["date"] <= str(WINDOW_END))]
    assert _nb(mt(b["lme_delta_physical_mt"].max())) in md and _nb(mt(b["unsold_mt"].max())) in md

    # stop-loss (attribution_daily.csv)
    dd = book - book.cummax()
    assert _nb(inr_m(dd.min())) in md
    t08 = att[att["trade_id"] == "T08"].set_index("date")["cum_pnl_inr"]
    assert _nb(inr_m((t08 - t08.cummax()).min())) in md
    assert "T09 bought 3-Aug would have been refused" in md

    # VaR (var_summary.csv)
    vs = pd.read_csv(T / "var_summary.csv").set_index("metric")["value"]
    assert _nb(inr_m(float(vs["var_mean_garch"]), 2)) in md and _nb(inr_m(float(vs["var_max_garch"]))) in md
    # the MCX beta is quoted as a range, weekly first, daily as the pessimistic end (docs/40 §4.3)
    mb = pd.read_csv(T / "var_mcx_beta.csv").set_index("sampling")
    assert f"{mb.at['weekly', 'beta']:.2f} on weekly closes and {mb.at['daily', 'beta']:.2f} on daily data" in md
    assert _nb(inr_m(float(vs["garch_var_mcx_beta_weekly_sensitivity_mean"]))) in md and "pessimistic end" in md
    # what the VaR limit leaves out, and the limits set with the book in view
    vd = pd.read_csv(T / "var_daily.csv")
    vd = vd[vd["in_window"] & vd["position_held"]]
    assert _nb(inr_m(vd["memo_pnl_grade_spread_inr"].std())) in md and "Within by construction" in md

    # credit (credit_scores.csv, credit_tracker.csv, credit_tracker_bookings.csv)
    sc = pd.read_csv(T / "credit_scores.csv").set_index("cp_id")
    tr = pd.read_csv(T / "credit_tracker.csv", usecols=["cp_id", "advance_reliance_multiple",
                                                        "flag_performance_advance_p14"])
    rjk = tr[tr["cp_id"] == "BUY_RJK_01"]
    bk = pd.read_csv(T / "credit_tracker_bookings.csv")
    assert f"band {sc.at['BUY_RJK_01', 'band_final']}" in md
    adv_days, adv_peak = int(rjk["flag_performance_advance_p14"].sum()), rjk["advance_reliance_multiple"].max()
    assert f"{adv_days} days, peak {adv_peak:.2f}x" in md
    assert f"{int((bk['band_policy_verdict'] == 'OUTSIDE_BAND_POLICY').sum())} of {len(bk)} bookings" in md
    assert _nb(inr_m(sc.at["BUY_RJK_01", "recommended_limit_inr"], 0)) in md

    # every limit printed is the registered value
    for key, fmt in (("policy_max_physical_open_mt", mt), ("policy_max_net_unhedged_mt", mt),
                     ("policy_max_physical_open_usd", lambda x: usd_m(x, 0)),
                     ("policy_var_limit_inr", lambda x: inr_m(x, 0)),
                     ("liq_fb_wc_limit_inr", lambda x: inr_m(x, 0))):
        assert _nb(fmt(float(config.value(key)))) in md, key


def test_policy_limit_breaches_recomputed(daily):
    lim = pd.read_csv(TABLES_DIR / "margin_liquidity_policy_limits.csv").set_index("limit_id")
    vd = pd.read_csv(TABLES_DIR / "var_daily.csv")
    vd = vd[vd["in_window"] & vd["position_held"] & ~vd["position_date_mcx_exit_or_roll"]]
    var_breach = vd[vd[["var_garch_inr", "var_hist250_inr"]].max(axis=1) > float(config.value("policy_var_limit_inr"))]
    assert lim.at["VAR", "days_breached"] == len(var_breach) == 1
    assert lim.at["VAR", "first_breach"] == "2022-03-09"
    stale = set(pd.read_csv(TABLES_DIR / "var_daily.csv").query("position_date_mcx_exit_or_roll")["position_date"])
    ex = pd.read_csv(TABLES_DIR / "book_exposures_daily.csv", usecols=["date", "scope", "lme_delta_mt"])
    b = ex[(ex["scope"] == "book") & (ex["date"] >= str(WINDOW_START)) & (ex["date"] <= str(WINDOW_END))
           & ~ex["date"].isin(stale)]
    assert lim.at["NET_UNHEDGED_MT", "days_breached"] == int(
        (b["lme_delta_mt"].abs() > float(config.value("policy_max_net_unhedged_mt"))).sum())
    buf = float(config.value("liq_fb_wc_limit_inr")) * float(config.value("liq_min_cash_buffer_frac_of_fb_limit"))
    rule = daily["funding_need_total_inr"] + np.maximum(buf, daily["mar_99_stressed_im_inr"]) > float(
        config.value("liq_fb_wc_limit_inr"))
    assert lim.at["LIQ_BUFFER_RULE", "days_breached"] == int(rule.sum())
    assert set(lim["book_verdict"]) <= {"WITHIN", "BREACHED"}
    assert (lim.loc[lim["book_verdict"] == "BREACHED", "days_breached"] > 0).all()
