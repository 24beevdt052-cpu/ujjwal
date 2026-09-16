"""Tests for the P6 one-page recruiter summary (desk.reporting.one_pager).

What these protect:
* the PDF is exactly one A4 page, labelled, with both charts embedded, and the published Markdown is the current render;
* at least twelve numbers on the page are the tables' numbers — recomputed here straight from the CSVs and the YAML
  register with an independent formatter, not through the module or the interview pack it reads through;
* the headline P&L never appears without its anchor-premium band and the words "not sign-robust";
* the template carries no hand-typed numbers, and every qualitative claim still holds (and the guard bites);
* the Excel reconciliation is quoted from `desk.excel.reconciliation_status`, never asserted;
* the P6 runner builds the one-pager last, and README.md links to it at the very top.
"""

from __future__ import annotations

import re
import sys
import types

import pandas as pd
import pytest
import yaml

from desk import HORIZON_END, SIM_LABEL, WINDOW_END
from desk.excel import reconciliation_status as recon_status
from desk.paths import CHARTS_DIR, PARAMS_DIR, PROCESSED_DIR, REPORTS_DIR, ROOT, TABLES_DIR
from desk.reporting import one_pager as om
from desk.reporting import run_reports as rr
from desk.reporting.pdf import count_pdf_pages

MINUS = "\u2212"
NB = "\u00a0"
MD = REPORTS_DIR / f"{om.NAME}.md"
PDF = REPORTS_DIR / f"{om.NAME}.pdf"
PNGS = [CHARTS_DIR / f"{om.CHART_EQUITY}.png", CHARTS_DIR / f"{om.CHART_VAR}.png"]
ANCHOR = "domestic_anchor_premium_inr_t"
T = TABLES_DIR


# ------------------------------------------------------------------------------------------------ independent formats
def _m(x: float, dp: int = 1, sign: bool = False) -> str:
    """Independent re-implementation of the ₹ m format (a formatting bug must not hide a data bug)."""
    s = f"{abs(x) / 1e6:,.{dp}f}"
    if x < 0 and float(s.replace(",", "")) != 0:
        return f"{MINUS}₹{s}{NB}m"
    return f"+₹{s}{NB}m" if sign and float(s.replace(",", "")) != 0 else f"₹{s}{NB}m"


def _n(x: float, dp: int = 0) -> str:
    s = f"{abs(x):,.{dp}f}"
    return f"{MINUS}{s}" if x < 0 and float(s.replace(",", "")) != 0 else s


def _p(frac: float, dp: int = 1) -> str:
    return f"{_n(frac * 100, dp)}{NB}%"


def _rupees(x: float) -> str:
    s = f"{abs(x):,.0f}"
    return f"{MINUS}₹{s}" if x < 0 and s != "0" else f"₹{s}"


def _day(d) -> str:
    return pd.Timestamp(d).strftime("%-d-%b")


# ------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def published() -> str:
    if not (MD.exists() and PDF.exists() and all(p.exists() for p in PNGS)):
        om.main()
    return MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def src():
    return om.load_sources()


@pytest.fixture(scope="module")
def raw(src):
    return om.compute_raw(src)


def _trade_pnl() -> pd.Series:
    att = pd.read_csv(T / "attribution_daily.csv", usecols=["trade_id", "daily_pnl_inr"])
    return att[att["trade_id"] != "BOOK"].groupby("trade_id")["daily_pnl_inr"].sum()


def _expected_numbers() -> list[tuple[str, str]]:
    """(what, exact text) pairs recomputed from the CSVs and YAML files alone."""
    out: list[tuple[str, str]] = []
    att = pd.read_csv(T / "attribution_daily.csv")
    bk = att[att["trade_id"] == "BOOK"].set_index("date")["cum_pnl_inr"]
    book = pd.read_csv(T / "trade_book.csv", usecols=["trade_id", "quantity_mt", "boxes"])
    mt = book["quantity_mt"].sum()
    horizon, window = float(bk[str(HORIZON_END)]), float(bk[str(WINDOW_END)])
    out += [("book P&L at the horizon", f"**{_m(horizon)}** ({_rupees(horizon / mt)}/MT)"),
            ("book P&L at the window end", f"{_m(window)} at the window end"),
            ("tickets, tonnes, containers", f"| **{len(book)}** | **{_n(mt)}{NB}MT** | **{_n(book['boxes'].sum())}** |")]

    rob = pd.read_csv(T / "pnl_sensitivity_sign_robustness.csv").set_index("param_key").loc[ANCHOR]
    out += [("anchor-premium band", f"**{_m(rob['pnl_min_inr'], sign=True)} to {_m(rob['pnl_max_inr'], sign=True)}**"),
            ("break-even anchor premium", f"break-even {_n(rob['breakeven_value'])}{NB}₹/MT inside the grid")]

    life = att[att["trade_id"] != "BOOK"][["new_deal", "grade_spread", "roll_term_structure", "lme_flat"]].sum()
    out += [("deal margin", f"deal margin at contract dates {_m(life['new_deal'], sign=True)}"),
            ("grade spread", f"grade spread {_m(life['grade_spread'], sign=True)}"),
            ("carry and roll", f"carry, roll and cross-terms {_m(life['roll_term_structure'], sign=True)}")]

    pricing = pd.read_csv(T / "pnl_sensitivity_pricing.csv")
    rep = pricing[(pricing["trade_id"] != "BOOK") & (pricing["case"] != "base")]
    worst_case = rep.groupby("trade_id")["cum_pnl_horizon_inr"].min()
    best = worst_case.idxmax()
    tp = _trade_pnl()
    loser = tp.idxmin()
    out += [("best trade by worst re-pricing", f"**{best}**"),
            ("best trade P&L and floor", f"**{_m(tp[best], 2, True)}**"),
            ("best trade floor", f"its floor is {_m(worst_case[best], 2, True)}"),
            ("worst trade", f"**{loser}**"), ("worst trade P&L", f"**{_m(tp[loser], 2, True)}**")]

    pw = pd.read_csv(T / "parity_weekly.csv", usecols=["in_window", "trade_eligible", "open_base"])
    win = pw[pw["in_window"]]
    out.append(("eligible parity cases", f"{int(win['trade_eligible'].sum())} of {len(win)} weekly cases passed "
                                         f"({int(win['open_base'].sum())} on the base screen alone)"))

    var = pd.to_numeric(pd.read_csv(T / "var_summary.csv", dtype=str).set_index(["metric", "scope"])["value"],
                        errors="coerce")
    vd = pd.read_csv(T / "var_daily.csv", usecols=["date", "var_garch_inr"])
    out += [("peak GARCH VaR", f"book VaR {_m(var[('var_max_garch', 'book_window')])} on "
                               f"{_day(vd.loc[vd['var_garch_inr'].idxmax(), 'date'])}"),
            ("mean VaR", f"{_m(var[('var_mean_garch', 'book_window')], 2)} against "
                         f"{_m(var[('var_mean_hist250', 'book_window')], 2)}")]

    kp = pd.read_csv(T / "kupiec.csv")
    bw = kp[kp["sample"] == "book_window"].set_index("method")
    out.append(("Kupiec exceptions", f"Book: {int(bw.at['garch', 'exceptions'])} GARCH and "
                                     f"{int(bw.at['hist250', 'exceptions'])} window exceptions against "
                                     f"{_n(bw.at['garch', 'expected'])} expected"))

    ll = pd.read_csv(T / "var_lead_lag.csv")
    base = ll[(ll["series"] == "lme") & (ll["episode"] == "LME_MARCH_SPIKE") & ll["base_percentile"]].set_index("method")
    out.append(("declared alert crossing", f"({_day(base.at['hist250', 'alert_date'])}, "
                                           f"{_n(abs(base.at['hist250', 'garch_lead_trading_days']))} trading days "
                                           "before GARCH)"))

    mc = pd.read_csv(T / "mc_summary.csv").set_index(["snapshot_id", "variant"])
    snaps = pd.read_csv(T / "mc_snapshots.csv").set_index("snapshot_id")["snapshot_date"]

    def v99(s: str, v: str = "normal_window") -> float:
        return float(mc.at[(s, v), "var99_inr"])

    out += [("MC VaR on the first snapshot", f"{_m(v99('ATH_PLUS_1'))} on {_day(snaps['ATH_PLUS_1'])}"),
            ("MC VaR on the peak-LME snapshot", f"{_m(v99('PEAK_GROSS_LME'))} on {_day(snaps['PEAK_GROSS_LME'])}"),
            ("MC VaR on the last snapshot",
             f"{_m(v99('PEAK_BUYER_CONTRACTED'), 2)} on {_day(snaps['PEAK_BUYER_CONTRACTED'])}"),
            ("MC VaR with the basis factor", f"{_m(v99('PEAK_GROSS_LME', 'normal_window_mcx_basis'))} and "
                                             f"{_m(v99('PEAK_BUYER_CONTRACTED', 'normal_window_mcx_basis'))}")]
    st = pd.read_csv(T / "mc_stress_scenarios.csv")
    dflt = st[(st["snapshot_id"] == "PEAK_BUYER_CONTRACTED") & (st["scenario_id"] == "buyer_default")].iloc[0]
    out.append(("buyer default stress", f"defaults on {_day(dflt['snapshot_date'])} ({_m(dflt['pnl_inr'])})"))

    cs = pd.read_csv(T / "credit_scores.csv").sort_values("rank_riskiest_first").iloc[0]
    out.append(("riskiest buyer", f"**{cs['cp_id']}** PD {_p(cs['pd_model_annual_frac'])}, band {cs['band_final']}"))

    liq = pd.read_csv(T / "margin_liquidity_summary.csv", dtype=str).set_index(["metric", "scope"])
    peak = liq.loc[("funding_need_total_inr_max", "book")]
    peak_date = re.search(r"\d{4}-\d{2}-\d{2}", peak["note"]).group(0)
    out += [("funding peak", f"{_m(float(peak['value']))} on {_day(peak_date)}"),
            ("days over the line", f"{int(float(liq.loc[('days_fb_limit_breach', 'book'), 'value']))} days over"),
            ("peak MCX initial margin", f"Peak MCX initial margin {_m(float(liq.loc[('mcx_im_inr_max', 'book'), 'value']))}")]

    sent = pd.read_csv(T / "sentiment_summary.csv").set_index("metric")["value"]
    out.append(("headlines and lead tests", f"{_n(sent['n_headlines'])} real headlines over {_n(sent['n_weeks'])} "
                                            f"weeks: {_n(sent['n_lead_tests_naive_5pct'])} of "
                                            f"{_n(sent['n_lead_tests'])} lead tests significant"))

    flags, n = {}, 0
    for f in sorted(PARAMS_DIR.glob("*.yaml")):
        for spec in (yaml.safe_load(f.read_text()) or {}).values():
            n += 1
            flags[spec["flag"]] = flags.get(spec["flag"], 0) + 1
    out.append(("parameter register flags",
                f"| {flags['DIRECT']} | {flags['PROXY']} | {flags['ASSUMPTION']} | {n} |"))
    prov = pd.read_csv(PROCESSED_DIR / "series_provenance.csv", usecols=["flag"])["flag"]
    out.append(("panel column flags", f"| {int((prov == 'DIRECT').sum())} | {int((prov == 'PROXY').sum())} | "
                                      f"{int((prov == 'ASSUMPTION').sum())} | {len(prov)} |"))
    return out


# ------------------------------------------------------------------------------------------------ numbers
def test_at_least_twelve_numbers_match_their_csv_sources(published):
    expected = _expected_numbers()
    assert len(expected) >= 12
    missing = [(what, text) for what, text in expected if text not in published]
    assert not missing, f"numbers on the one-pager that do not match their CSV sources: {missing}"


def test_headline_never_appears_without_its_band(published):
    rob = pd.read_csv(T / "pnl_sensitivity_sign_robustness.csv").set_index("param_key").loc[ANCHOR]
    band = f"{_m(rob['pnl_min_inr'], sign=True)} to {_m(rob['pnl_max_inr'], sign=True)}"
    rows = published.split("## Headline results")[1].split("\n![")[0]
    assert band in rows and "not sign-robust" in rows and ANCHOR in rows
    assert rows.index("Book P&L to the horizon") < rows.index(band)        # the band is the very next row


def test_best_trade_is_the_post_mortems_ticket(raw):
    assert raw["best_tid"] == om.pm.TRADE_OF_RECORD
    assert raw["worst_tid"] == om.ip.WORST_TRADE_OF_RECORD


# ------------------------------------------------------------------------------------------------ outputs
def test_pdf_is_exactly_one_page_labelled_and_carries_both_charts(published):
    assert count_pdf_pages(PDF) == om.MAX_PAGES == 1
    assert SIM_LABEL in published[:1500]
    assert b"/Subject (ACADEMIC SIMULATION" in PDF.read_bytes()
    for p in PNGS:
        assert p.exists() and p.stat().st_size > 10_000
        assert f"../charts/{p.name}" in published
    assert published.count("<!-- columns -->") == published.count("<!-- end-columns -->") == 1


def test_published_markdown_is_the_current_render(published, src):
    md, _ = om.build_markdown(src)
    assert md == published


def test_markdown_links_resolve(published):
    for target in re.findall(r"!?\[[^\]]*\]\(([^)\s]+)\)", published):
        assert (MD.parent / target).resolve().exists(), target


def test_page_guard_sees_an_overflow(tmp_path, published):
    """main()'s one-page assert is only as good as the count it reads: an overflowing render must report > 1."""
    text = "\n".join(ln for ln in published.splitlines() if not ln.startswith("!["))   # tmp_path has no charts
    risk = "## Risk findings" + published.split("## Risk findings")[1].split(om.COLUMNS)[0]
    probe = tmp_path / "overflow.pdf"
    n = om.render_pdf(text + "\n\n" + risk * 2, probe)
    assert n > om.MAX_PAGES
    assert count_pdf_pages(probe) == n


def test_an_unclosed_column_block_is_refused(tmp_path):
    with pytest.raises(ValueError, match="unclosed"):
        om.render_pdf(f"# x\n\n{om.COLUMNS}\nleft\n{om.COLUMN_BREAK}\nright\n", tmp_path / "bad.pdf")


# ------------------------------------------------------------------------------------------------ honesty guards
class _Sentinel(dict):
    def __missing__(self, key):
        return "@"


STRUCTURAL = [r"GARCH\(1,1\)", r"\b(?:95|99) ?%", r"§5a", r"DESK_OFFLINE=1"]


def test_template_has_no_hand_typed_numbers():
    text = om.TEMPLATE.format_map(_Sentinel())
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    for pat in STRUCTURAL:
        text = re.sub(pat, "", text)
    leftovers = [ln for ln in text.splitlines() if re.search(r"\d", ln)]
    assert not leftovers, f"digits typed into the one-pager template: {leftovers}"


def test_every_claim_holds_and_the_guard_bites(raw):
    assert om.check_claims(raw) == []
    broken = dict(raw, best_tid="T01", q16_lead=3.0, band_sign_robust=True, q17_n_sig=1, beyond_groups=[],
                  q15_wc_step_days=4)
    failed = om.check_claims(broken)
    for needle in ("best trade", "crossed the declared alert first", "not sign-robust", "sentiment",
                   "beyond every path", "one step higher"):
        assert any(needle in f for f in failed), needle


def test_excel_reconciliation_is_quoted_from_the_status_helper(published):
    st = recon_status.status()
    where = published.split("Metals_Desk_Master.xlsx")[-1].split("\n")[0]
    assert f"reconciliation **{st.status}**" in where
    if st.verified:
        assert f"{st.n_recalculated:,} formula cells recalculated outside Excel" in where
    else:
        assert "formula cells recalculated" not in published
    not_run = om._recon_clause(recon_status.ReconStatus(recon_status.NOT_RUN, "No record on this build."))
    assert "NOT_RUN" in not_run and not re.search(r"\d", not_run)


# ------------------------------------------------------------------------------------------------ runner and README
def test_runner_builds_the_one_pager_last(monkeypatch):
    assert rr.SUMMARY_STEP[1] == "desk.reporting.one_pager"
    calls: list[str] = []
    names = ["fake_1pg_notes", "fake_1pg_post_mortem", "fake_1pg_pack", "fake_1pg_summary"]
    for name in names:
        mod = types.ModuleType(name)
        mod.main = (lambda n=name: calls.append(n))
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(rr, "STEPS", tuple((n, n) for n in names[:3]))
    monkeypatch.setattr(rr, "SUMMARY_STEP", ("summary", names[3]))
    monkeypatch.setattr(rr, "refresh_readme", lambda: calls.append("readme") or False)
    rr.main()
    assert calls == names[:3] + ["readme", names[3]]


def test_readme_links_to_the_one_pager_at_the_very_top():
    head = (ROOT / "README.md").read_text(encoding="utf-8").split("\n> ")[0]    # before the SIM callout
    assert "(outputs/reports/one_pager.pdf)" in head and "(outputs/reports/one_pager.md)" in head


@pytest.mark.parametrize("state", [recon_status.NOT_RUN, recon_status.STALE, recon_status.FAILED])
def test_page_stays_one_sheet_when_excel_is_not_verified(tmp_path, src, state):
    """A fresh build has no reconciliation record: the page must still fit, or main() stops the whole P6 stage."""
    unverified = {**src, "recon": recon_status.ReconStatus(state, "No record on this build.")}
    md, _ = om.build_markdown(unverified)
    assert f"reconciliation **{state}**" in md and "formula cells recalculated" not in md
    assert ".." not in md.split("Metals_Desk_Master.xlsx")[-1].split("\n")[0].replace("](../", "")
    reports = tmp_path / "reports"
    reports.mkdir()
    (tmp_path / "charts").symlink_to(om.CHARTS_DIR)   # the page embeds ../charts/*.png
    assert om.render_pdf(md, reports / "probe.pdf") == om.MAX_PAGES == 1
