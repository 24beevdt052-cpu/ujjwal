"""Tests for the P6 reporting runner, the interview pack and the README (MASTER_SPEC Table 7 row 5.4, Table 8 row 6).

What these protect:
* the pack has exactly 17 questions, and the last two are the spec's two questions, verbatim;
* the question and answer templates carry no hand-typed numbers, and every qualitative claim still holds;
* the numbers in the answers are the tables' numbers, recomputed here straight from the CSVs (and the YAML register),
  not through the module;
* the headline P&L never appears without its anchor-premium band, and no answer runs long;
* the Excel reconciliation is quoted (pack and README) only when its record passed and hashes to the workbook on disk;
* the runner calls desk notes → post-mortem → interview pack in that order and fails clearly if a step is missing;
* every link in README.md and docs/INDEX.md resolves, the README's generated number blocks are current, and the index
  names every spec row.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import types

import pandas as pd
import pytest
import yaml

from desk import SIM_LABEL
from desk.paths import DOCS_DIR, EXCEL_DIR, PARAMS_DIR, PROCESSED_DIR, REPORTS_DIR, ROOT, TABLES_DIR
from desk.reporting import interview_pack as ip
from desk.reporting import run_reports as rr
from desk.reporting.pdf import count_pdf_pages

MINUS = "\u2212"
NB = "\u00a0"
MD = REPORTS_DIR / f"{ip.NAME}.md"
PDF = REPORTS_DIR / f"{ip.NAME}.pdf"
README = ROOT / "README.md"
INDEX = DOCS_DIR / "INDEX.md"


# ------------------------------------------------------------------------------------------------ independent formats
def _m(x: float, dp: int = 1, sign: bool = False) -> str:
    """Independent re-implementation of the pack's ₹ m format (a formatting bug must not hide a data bug)."""
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


# ------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def published() -> str:
    if not (MD.exists() and PDF.exists()):
        ip.main()
    return MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def src():
    return ip.load_sources()


@pytest.fixture(scope="module")
def raw(src):
    return ip.compute_raw(src)


def _sections(md: str) -> dict[int, str]:
    """Question number → its heading, answer and sources (the unnumbered footer is excluded)."""
    parts = re.split(r"^## ", md, flags=re.M)
    out = {}
    for part in parts[1:]:
        m = re.match(r"(\d+)\. ", part)
        if m:
            out[int(m.group(1))] = "## " + part
    return out


def _q(md: str, qid: str) -> str:
    n = [q.qid for q in ip.QUESTIONS].index(qid) + 1
    return _sections(md)[n]


def _final_by_trade() -> pd.DataFrame:
    att = pd.read_csv(TABLES_DIR / "attribution_daily.csv")
    return att[att["trade_id"] != "BOOK"].groupby("trade_id")[
        ["new_deal", "lme_flat", "cross_exchange_basis", "grade_spread", "freight", "fx", "demurrage_penalty",
         "roll_term_structure", "daily_pnl_inr"]].sum()


# ------------------------------------------------------------------------------------------------ structure
def test_exactly_17_questions_ending_with_the_two_spec_questions_verbatim(published):
    heads = re.findall(r"^## (\d+)\. (.+)$", published, flags=re.M)
    assert [int(n) for n, _ in heads] == list(range(1, 18))
    assert len(ip.QUESTIONS) == ip.N_QUESTIONS == 17
    assert [h for _, h in heads[-2:]] == list(ip.REQUIRED_QUESTIONS)
    spec = re.sub(r"\s+", " ", (DOCS_DIR / "spec" / "MASTER_SPEC_V3.md").read_text(encoding="utf-8"))
    for q in ip.REQUIRED_QUESTIONS:
        assert f'"{q}"' in spec, f"not verbatim from the spec: {q}"
    assert len({q.qid for q in ip.QUESTIONS}) == 17


def test_pack_says_the_first_fifteen_were_authored_and_carries_the_label(published):
    head = published.split("\n## 1. ")[0]
    assert "Questions 1 to 15 were therefore written for this pack" in head
    assert "Questions 16 and 17 are the spec's, verbatim" in head
    assert SIM_LABEL in head
    assert "What this pack does and doesn't tell you" in published


def test_pdf_is_written_from_the_markdown(published):
    assert PDF.exists() and count_pdf_pages(PDF) >= 1


def test_published_pack_is_the_current_render(published, src):
    md, _ = ip.build_markdown(src)
    assert md == published


# ------------------------------------------------------------------------------------------------ honesty guards
class _Sentinel(dict):
    def __missing__(self, key):
        return "@"


STRUCTURAL = [r"GARCH\(1,1\)", r"\((?:0|[a-g])\)", r"\bHS \d{4}\b", r"\b(?:95|99) ?%", r"\b3M\b", r"\bM\+1\b",
              r"Table \d+", r"\(1 − ", r"\blag-\d\b"]


def test_templates_have_no_hand_typed_numbers():
    texts = [ip.HEADER, ip.FOOTER] + [t for q in ip.QUESTIONS for t in (q.question, q.answer, q.topic)]
    leftovers = []
    for t in texts:
        text = t.format_map(_Sentinel())
        for pat in STRUCTURAL:
            text = re.sub(pat, "", text)
        leftovers += [ln for ln in text.splitlines() if re.search(r"\d", ln)]
    assert not leftovers, f"digits typed into the interview-pack templates: {leftovers}"


def test_every_claim_holds_and_the_guard_bites(raw):
    assert ip.check_claims(raw) == []
    broken = dict(raw, worst_tid="T01", q16_lead=3.0, q13_in_force=True, q17_n_sig=1,
                  q2_negative_grade_ids=["T01", "T08"], q12_cf_vm=-1.0)
    failed = ip.check_claims(broken)
    for needle in ("the worst ticket is still", "crossed before GARCH", "no scrap QCO in 2022",
                   "no lead test significant", "only negative grade spread", "paid the short hedges"):
        assert any(needle in f for f in failed), needle


def test_answers_are_short(src):
    facts = ip.format_facts(ip.compute_raw(src))
    words = {q["qid"]: ip.answer_words(q["answer"]) for q in ip.render_questions(facts)}
    assert max(words.values()) <= ip.MAX_ANSWER_WORDS == 150, words


def test_headline_pnl_never_appears_without_its_band(published):
    att = pd.read_csv(TABLES_DIR / "attribution_daily.csv", usecols=["date", "trade_id", "cum_pnl_inr"])
    head = float(att[(att["trade_id"] == "BOOK") & (att["date"] == "2022-10-31")]["cum_pnl_inr"].iloc[0])
    rob = pd.read_csv(TABLES_DIR / "pnl_sensitivity_sign_robustness.csv")
    anc = rob[rob["param_key"] == "domestic_anchor_premium_inr_t"].iloc[0]
    lo, hi = _m(anc["pnl_min_inr"], sign=True), _m(anc["pnl_max_inr"], sign=True)
    assert (lo, hi) == (f"{MINUS}₹105.4{NB}m", f"+₹334.3{NB}m")
    blocks = list(_sections(published).values()) + [published.split("\n## 1. ")[0]]
    quoting = [b for b in blocks if _m(head) in b]
    assert len(quoting) >= 2
    for b in quoting:
        assert lo in b and hi in b, b[:80]


def test_excel_reconciliation_is_quoted_only_when_verified(published, src):
    """Recomputed independently of desk.excel.reconciliation_status: a pass is quoted only for this exact workbook."""
    recon, workbook = EXCEL_DIR / "reconciliation.json", EXCEL_DIR / "Metals_Desk_Master.xlsx"
    rec = json.loads(recon.read_text(encoding="utf-8")) if recon.exists() else None
    independent = bool(
        rec and workbook.exists() and rec.get("scoreboard") == "PASS" and rec.get("n_check_failures") == 0
        and rec.get("n_errors") == 0 and rec.get("scope") == "full workbook"
        and all(f["status"] == "PASS" for f in rec.get("families", {}).values()) and rec.get("families")
        and rec.get("workbook", {}).get("sha256") == hashlib.sha256(workbook.read_bytes()).hexdigest())
    st = src["recon"]
    assert st.verified == independent, st.reason
    head, q9 = published.split("\n## 1. ")[0], _q(published, "attribution")
    readme = README.read_text(encoding="utf-8")
    if independent:
        assert "Excel reconciliation:" not in head
        assert f"recalculates {_n(rec['n_recalculated'])} cells with {_n(rec['n_check_failures'])} failed checks" in q9
        assert f"- [x] **Excel reconciliation PASS.** {_n(rec['n_recalculated'])} formula cells" in readme
    else:
        assert f"> **Excel reconciliation: {st.status}.**" in head and "DESK_RUN_SLOW=1" in head
        assert "cells with" not in q9
        assert "- [x] **Excel reconciliation" not in readme


def test_sources_exist():
    for q in ip.QUESTIONS:
        for s in q.sources:
            assert (ROOT / s).exists(), (q.qid, s)


# ------------------------------------------------------------------------------------------------ numbers vs CSVs
def test_attribution_and_worst_trade_numbers_match_the_csvs(published):
    ft = _final_by_trade()
    book = pd.read_csv(TABLES_DIR / "trade_book.csv", dtype=str).set_index("trade_id")
    total = ft["daily_pnl_inr"].sum()
    q9 = _q(published, "attribution")
    assert _m(ft["new_deal"].sum(), sign=True) in q9
    assert _p(ft["new_deal"].sum() / total, 0) in q9
    rob = pd.read_csv(TABLES_DIR / "pnl_sensitivity_sign_robustness.csv")
    assert _n(rob.loc[rob["param_key"] == "domestic_anchor_premium_inr_t", "breakeven_value"].iloc[0]) in q9
    nd = pd.read_csv(TABLES_DIR / "new_deal_timing.csv").set_index("trade_id")
    assert _m(nd.loc["BOOK", "new_deal_on_trade_date_inr"]) in q9
    worst = ft["daily_pnl_inr"].idxmin()
    q10 = _q(published, "worst")
    assert worst == "T08" and "worst trade, T08" in q10
    assert _m(ft.loc[worst, "daily_pnl_inr"], sign=True) in q10
    qty = float(book.loc[worst, "quantity_mt"])
    assert f"({_rupees(ft.loc[worst, 'daily_pnl_inr'] / qty)}/MT)" in q10
    assert _m(ft.loc[worst, "grade_spread"], sign=True) in q10
    assert (ft["grade_spread"] < 0).sum() == 1
    q2 = _q(published, "grade")
    s = pd.read_csv(TABLES_DIR / "pnl_sensitivity_summary.csv").set_index("case")
    assert _m(s.loc["grade_mix_pit_repriced", "cum_pnl_horizon_inr"]) in q2
    q15 = _q(published, "differently")
    assert _m(ft.loc["T09", "daily_pnl_inr"], sign=True) in q15


def test_parity_freight_and_funding_numbers_match_the_csvs(published):
    pw = pd.read_csv(TABLES_DIR / "parity_weekly.csv")
    win = pw[pw["in_window"]]
    q1 = _q(published, "parity")
    assert f"{int(win['trade_eligible'].sum())} of {len(win)} in-window cases" in q1
    row = pw[(pw["week_end"] == "2022-03-04") & (pw["grade"] == "zorba") & (pw["lane"] == "USEC_MUN")].iloc[0]
    assert f"{_rupees(row['net_arb_inr_t'])}/MT" in q1 and f"{_rupees(row['landed_inr_t'])}/MT" in q1
    book = pd.read_csv(TABLES_DIR / "trade_book.csv", dtype=str)
    fob = list(book.loc[book["incoterm"] == "FOB", "trade_id"])
    assert f"FOB ({', '.join(fob[:-1])} and {fob[-1]})" in _q(published, "freight")
    grid = pd.read_csv(TABLES_DIR / "margin_liquidity_limit_grid.csv").set_index("facility")
    q4 = _q(published, "funding")
    assert _m(grid.loc["FUND_BASED_WC_MIN_NO_BREACH", "limit_inr"], 0) in q4
    liq = pd.read_csv(TABLES_DIR / "margin_liquidity_summary.csv", dtype=str)
    peak = float(liq[(liq["metric"] == "funding_need_total_inr_max") & (liq["scope"] == "book")]["value"].iloc[0])
    assert _m(peak) in q4 and _m(peak) in _q(published, "margin")
    vm = float(liq[(liq["metric"] == "vm_actual_sum_inr") & (liq["scope"] == "CRASH_FORTNIGHT")]["value"].iloc[0])
    assert _m(vm, sign=True) in _q(published, "margin")


def test_hedge_basis_and_fx_numbers_match_the_csvs(published):
    rolls = pd.read_csv(TABLES_DIR / "mcx_roll_carry.csv")
    q5 = _q(published, "structure")
    assert f"all {len(rolls)} short rolls gained {_m(rolls['roll_pnl_inr'].sum(), 2, sign=True)}" in q5
    basis = pd.read_csv(TABLES_DIR / "mcx_basis_risk.csv")
    beta = float(basis[(basis["metric"] == "unit_beta_beta") & (basis["scope"] == "BOOK")]["value"].iloc[0])
    assert f"the beta is {_n(beta, 2)}" in _q(published, "basis")
    mc = pd.read_csv(TABLES_DIR / "mc_summary.csv")
    apr = mc[mc["snapshot_id"] == "PEAK_GROSS_LME"].set_index("variant")["var99_inr"]
    assert f"from {_m(apr['normal_window'])} to {_m(apr['normal_window_mcx_basis'])}" in _q(published, "basis")
    # the daily beta is never the one to hedge on: the answer gives the weekly and close-matched betas (docs/40 §4.3)
    mb = pd.read_csv(TABLES_DIR / "var_mcx_beta.csv").set_index("sampling")
    q6 = _q(published, "basis")
    assert f"on weekly closes it is {_n(mb.at['weekly', 'beta'], 2)}" in q6
    assert f"{_n(mb.at['lead_lag', 'beta'], 2)} once closes are matched" in q6 and "nobody would hedge on" in q6
    assert mb.at["daily", "beta"] < mb.at["weekly", "beta"] < mb.at["lead_lag", "beta"]
    assert f"size MCX on a weekly-close beta ({_n(mb.at['weekly', 'beta'], 2)})" in _q(published, "differently")
    ev = pd.read_csv(TABLES_DIR / "adverse_events_summary.csv", dtype=str)

    def e(event, metric):
        return float(ev[(ev["event"] == event) & (ev["metric"] == metric)]["value"].iloc[0])

    assert f"{_p(e('E1_LME_CRASH', 'hedge_offset_frac'), 0)} offset" in _q(published, "hedge")
    q8 = _q(published, "fx")
    assert f"from ₹{_n(e('E2_INR_DEPRECIATION', 'usdinr_start'), 2)} to ₹{_n(e('E2_INR_DEPRECIATION', 'usdinr_end'), 2)}" in q8
    assert _m(e("E2_INR_DEPRECIATION", "fx_forwards_inr"), sign=True) in q8


def test_var_credit_policy_and_sentiment_numbers_match_the_csvs(published):
    var = pd.to_numeric(pd.read_csv(TABLES_DIR / "var_summary.csv", dtype=str).set_index("metric")["value"],
                        errors="coerce")
    q16 = _q(published, "garch")
    assert f"forecast {_p(var['sigma_lme_garch_on_day_after_ath'], 2)} a day against " \
           f"{_p(var['sigma_lme_hist250_on_day_after_ath'], 2)}" in q16
    assert f"{_n(var['z_of_2022_03_08_return_garch'], 1)}σ for GARCH" in q16
    kp = pd.read_csv(TABLES_DIR / "kupiec.csv")
    bw = kp[kp["sample"] == "book_window"].set_index("method")
    assert f"broke {int(bw.loc['garch', 'exceptions'])} times in {int(bw.loc['garch', 'n'])} days against the " \
           f"window's {int(bw.loc['hist250', 'exceptions'])}" in q16
    assert f"Kupiec accepts {int(bw.loc['garch', 'kupiec_accept_min'])} to {int(bw.loc['garch', 'kupiec_accept_max'])}" in q16

    cs = pd.read_csv(TABLES_DIR / "credit_scores.csv").set_index("cp_id")
    q11 = _q(published, "credit")
    assert f"{_p(cs.loc['BUY_RJK_01', 'pd_model_annual_frac'])} PD" in q11
    bk = pd.read_csv(TABLES_DIR / "credit_tracker_bookings.csv")
    adv = bk[(bk["cp_id"] == "BUY_RJK_01") & (bk["advance_reliance_multiple"] > 0)].sort_values("contract_date")
    mults = [f"{a:.2f}×" for a in adv["advance_reliance_multiple"]]
    assert f"{', '.join(mults[:-1])} and {mults[-1]} its line" in q11
    st = pd.read_csv(TABLES_DIR / "mc_stress_scenarios.csv")
    d = st[(st["snapshot_id"] == "PEAK_BUYER_CONTRACTED") & (st["scenario_id"] == "buyer_default")]["pnl_inr"].iloc[0]
    assert f"default costs {_m(abs(d))}" in q11
    qco = st[(st["snapshot_id"] == "PEAK_GROSS_LME") & (st["scenario_id"] == "qco_hold_demurrage")]["pnl_inr"].iloc[0]
    q13 = _q(published, "policy")
    reg = yaml.safe_load((PARAMS_DIR / "regulatory.yaml").read_text())
    assert _m(abs(qco)) in q13 and f"box {reg['qco_stress_delay_days']['value']} days" in q13
    assert reg["bis_qco_scrap_in_force_2022"]["value"] is False

    sent = pd.read_csv(TABLES_DIR / "sentiment_summary.csv").set_index("metric")["value"]
    q17 = _q(published, "ml")
    assert f"{int(sent['n_headlines'])} real headlines" in q17
    assert f"{int(sent['n_lead_tests_naive_5pct'])} of {int(sent['n_lead_tests'])} lead tests" in q17
    assert "no evidence of a lead" in q17 and "did not lead" not in published
    assert "log fall" in q16


def test_facility_lesson_states_its_conventions(published):
    """Q4/Q15: the breach is quoted with the average-balance sanction and the one rounding step that removes it."""
    grid = pd.read_csv(TABLES_DIR / "margin_liquidity_limit_grid.csv")
    wc = grid[grid["facility"] == "FUND_BASED_WC"]
    reg = float(wc.loc[wc["registered"], "limit_inr"].iloc[0])
    step = wc[wc["limit_inr"] == reg + float(yaml.safe_load((PARAMS_DIR / "risk.yaml").read_text())[
        "liq_facility_rounding_inr"]["value"])].iloc[0]
    assert int(step["days_limit_breach"]) == 0
    q15 = _q(published, "differently")
    assert "stress the plan's peak, not its average" in q15 and f"({_m(step['limit_inr'], 0)})" in q15
    assert "size bank lines on the book" not in published
    assert "average balance" in _q(published, "funding")


def test_register_counts_match_the_yaml_files(published):
    flags, statuses, n = {}, {}, 0
    for f in sorted(PARAMS_DIR.glob("*.yaml")):
        for spec in (yaml.safe_load(f.read_text()) or {}).values():
            n += 1
            flags[spec["flag"]] = flags.get(spec["flag"], 0) + 1
            st = re.match(r"\s*([A-Z/]+)", str(spec["verify"])).group(1)
            statuses[st] = statuses.get(st, 0) + 1
    q14 = _q(published, "data")
    assert (f"Of {n} registered parameters, {flags['DIRECT']} are DIRECT, {flags['PROXY']} PROXY and "
            f"{flags['ASSUMPTION']} ASSUMPTION; {statuses['VERIFIED']} are VERIFIED and {statuses['PENDING']} still "
            f"PENDING") in q14
    prov = pd.read_csv(PROCESSED_DIR / "series_provenance.csv")
    assert f"{int((prov['flag'] == 'DIRECT').sum())} of {len(prov)} columns are DIRECT" in q14


# ------------------------------------------------------------------------------------------------ runner
def test_runner_steps_are_notes_then_post_mortem_then_pack():
    assert [m for _, m in rr.STEPS] == ["desk.reporting.desk_notes", "desk.reporting.post_mortem",
                                        "desk.reporting.interview_pack"]


def _fake_modules(monkeypatch, names: list[str], calls: list[str]) -> None:
    for name in names:
        mod = types.ModuleType(name)
        mod.main = (lambda n=name: calls.append(n))
        monkeypatch.setitem(sys.modules, name, mod)


def test_runner_runs_every_step_in_order_then_refreshes_the_readme(monkeypatch):
    calls: list[str] = []
    names = ["fake_p6_notes", "fake_p6_post_mortem", "fake_p6_pack"]
    _fake_modules(monkeypatch, names, calls)
    monkeypatch.setattr(rr, "STEPS", tuple((n, n) for n in names))
    monkeypatch.setattr(rr, "refresh_readme", lambda: calls.append("readme") or False)
    rr.main()
    assert calls == names + ["readme"]


def test_runner_fails_clearly_before_running_anything_when_a_step_is_missing(monkeypatch):
    calls: list[str] = []
    _fake_modules(monkeypatch, ["fake_p6_post_mortem"], calls)
    missing = "desk.reporting.no_such_step_for_tests"
    monkeypatch.setattr(rr, "STEPS", (("post-mortem", "fake_p6_post_mortem"), ("notes", missing)))
    monkeypatch.setattr(rr, "refresh_readme", lambda: calls.append("readme") or False)
    with pytest.raises(rr.MissingStageError, match=re.escape(missing)):
        rr.main()
    assert calls == []


def test_a_broken_import_inside_a_step_is_not_reported_as_missing(tmp_path, monkeypatch):
    (tmp_path / "fake_p6_broken_step.py").write_text("import fake_p6_dependency_that_does_not_exist\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ModuleNotFoundError) as exc:
        rr.load_step("fake_p6_broken_step")
    assert not isinstance(exc.value, rr.MissingStageError)
    assert exc.value.name == "fake_p6_dependency_that_does_not_exist"


# ------------------------------------------------------------------------------------------------ README and index
_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")


def _slug(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s", "-", s)


def _broken_links(path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    anchors = {_slug(h) for h in re.findall(r"^#+ (.+)$", text, flags=re.M)}
    bad = []
    for target in _LINK.findall(text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if target.startswith("#"):
            if target[1:] not in anchors:
                bad.append(target)
            continue
        if not (path.parent / target.split("#")[0]).resolve().exists():
            bad.append(target)
    return bad


def test_readme_links_and_images_resolve():
    assert README.exists()
    assert _broken_links(README) == []
    assert len(re.findall(r"!\[[^\]]*\]\(outputs/charts/[^)]+\.png\)", README.read_text(encoding="utf-8"))) >= 6


def test_index_links_resolve():
    assert _broken_links(INDEX) == []


def test_readme_generated_blocks_are_current(src):
    bodies = rr.readme_block_bodies(README.read_text(encoding="utf-8"))
    assert set(bodies) == set(rr.BLOCK_NAMES)
    assert bodies == rr.render_readme_blocks(src)


def test_apply_blocks_refuses_a_readme_without_markers():
    with pytest.raises(ValueError, match="GENERATED block"):
        rr.apply_blocks("# no markers here\n", {"headline": "x"})


def test_readme_has_the_spec_sections_and_the_honesty_labels():
    text = README.read_text(encoding="utf-8")
    heads = re.findall(r"^## (.+)$", text, flags=re.M)
    for h in ("Headline results", "What is real, what is a proxy, what is an assumption", "Key charts",
              "How the desk was built: the data pipeline", "Folder structure", "How to re-run it",
              "Verification checklist", "Why these quant methods and not others", "Deliverables against the spec",
              "Limitations and honest caveats", "Interview preparation"):
        assert h in heads, h
    assert SIM_LABEL in text and "```mermaid" in text
    for needle in ("DESK_OFFLINE=1", "--only", "--from", "DESK_RUN_SLOW=1", "3 GB", "docs/INDEX.md"):
        assert needle in text, needle
    head = text.split("## What is real")[0]
    assert f"{MINUS}₹105.4{NB}m to +₹334.3{NB}m" in head and "not sign-robust" in head
    why = text.split("## Why these quant methods and not others")[1].split("\n## ")[0]
    sentences = re.findall(r"[.!?](?:\s|$)", why.strip())
    assert 3 <= len(sentences) <= 4, len(sentences)
    for word in ("GARCH", "Monte Carlo", "logistic regression", "deliberately excluded"):
        assert word in why, word


SPEC_ROWS = ([f"1.{i}" for i in range(1, 8)] + [f"2.{i}" for i in range(1, 10)] + [f"3.{i}" for i in range(1, 7)]
             + [f"4.{i}" for i in range(1, 7)] + [f"5.{i}" for i in range(1, 5)] + [f"8.{i}" for i in range(1, 7)])


def test_index_maps_every_spec_row_with_a_status():
    text = INDEX.read_text(encoding="utf-8")
    statuses = ("DONE", "PARTIAL", "IN PROGRESS")
    for row in SPEC_ROWS:
        lines = [ln for ln in text.splitlines() if re.match(rf"^\| {re.escape(row)}(?: [★☆])? \|", ln)]
        assert len(lines) >= 1, f"spec row {row} missing from docs/INDEX.md"
        assert any(ln.rstrip(" |").split("|")[-1].strip().startswith(statuses) for ln in lines), row
