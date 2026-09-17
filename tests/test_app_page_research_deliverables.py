"""AppTest interactions for the Sentiment overlay, Reports & docs and Data & assumptions pages
(app/views/sentiment.py, reports.py, data_assumptions.py).

Beyond tests/test_app_pages.py (every page runs, banner, title), these exercise the filters and check that what the
pages show is the pipeline's own numbers:

* Sentiment: the lead-test counts equal sentiment_summary.csv and the "no evidence of a lead" verdict is quoted only
  while the tables support it; score, overlay, variant, interval, episode and headline-explorer filters change what
  is shown; without the scored headlines (public copy) the explorer falls back to the week extremes.
* Reports: the headline P&L sits with its band; the inventories equal the files in outputs/reports/; the desk-note,
  interview-pack, docs-browser and spec-coverage selectors work; reconciliation figures appear only when VERIFIED.
* Data & assumptions: the flag and verification counts equal desk.config.params_frame(); register, provenance,
  verification-log, manifest, policy and review filters work.
* With every file missing, each page shows "Not in this copy" notes, never an exception.

Run on its own on a small machine: `.venv/bin/python -m pytest -q tests/test_app_page_research_deliverables.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.lib import data  # noqa: E402
from desk import SIM_LABEL  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SENTIMENT = ROOT / "app" / "views" / "sentiment.py"
REPORTS = ROOT / "app" / "views" / "reports.py"
DATA_PAGE = ROOT / "app" / "views" / "data_assumptions.py"
TIMEOUT = 180
SCORED = data.table_rel("sentiment_headlines_scored")


def _run(path: Path) -> AppTest:
    return AppTest.from_file(str(path), default_timeout=TIMEOUT).run()


def _ok(at: AppTest) -> AppTest:
    assert not at.exception, [e.value for e in at.exception]
    assert any(SIM_LABEL in m.value for m in at.markdown), "SIM banner"
    return at


def _metrics(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def _captions(at: AppTest) -> str:
    return "\n".join(c.value for c in at.caption)


def _markdown(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def _expanders(at: AppTest) -> list[str]:
    """Expander labels; AppTest reports an expander that has an icon as a `status` block."""
    return [e.label for e in at.expander] + [s.label for s in at.status]


def _infos(at: AppTest) -> list[str]:
    return [i.value for i in at.info]


def _table(at: AppTest, *columns: str) -> pd.DataFrame:
    hits = [d.value for d in at.dataframe if set(columns) <= set(d.value.columns)]
    assert hits, f"no table with columns {columns!r}"
    return hits[0]


def _mirror(tmp: Path, skip: set[str]) -> Path:
    """A copy of the repository made of symlinks, leaving out the repo-relative files in `skip` (and data/raw)."""
    for top in ("outputs", "data/processed", "docs", "config"):
        for src in (ROOT / top).rglob("*"):
            rel = src.relative_to(ROOT).as_posix()
            if src.is_dir() or rel in skip:
                continue
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(src)
    for name in ("README.md", "CONTRACTS.md"):
        (tmp / name).symlink_to(ROOT / name)
    return tmp


def _summary() -> dict[str, float]:
    s = pd.read_csv(ROOT / data.table_rel("sentiment_summary"))
    return dict(zip(s["metric"], s["value"].astype(float)))


# ------------------------------------------------------------------------------------------------ sentiment
def test_sentiment_verdict_is_read_from_the_tables():
    at = _ok(_run(SENTIMENT))
    s = _summary()
    m = _metrics(at)
    assert m["Headlines"] == f"{int(s['n_headlines']):,}" and m["Weeks"] == f"{int(s['n_weeks'])}"
    assert m["Significant leads"] == f"{int(s['n_lead_tests_naive_5pct'])} of {int(s['n_lead_tests'])}"
    assert m["Lead CIs excl. zero"] == (
        f"{int(s['n_lead_tests_boot_ci_excludes_zero'])} of {int(s['n_lead_tests'])}")
    no_lead = s["n_lead_tests_naive_5pct"] == 0 and s["n_lead_tests_boot_ci_excludes_zero"] == 0
    assert ("no evidence that headline tone led LME" in _markdown(at)) == no_lead
    assert bool(at.warning) != no_lead
    caps = _captions(at)
    for f in ("sentiment_summary.csv", "sentiment_weekly.csv", "sentiment_leadlag.csv", "sentiment_episodes.csv",
              "sentiment_headlines_scored.csv"):
        assert f in caps, f
    assert "DIRECT" in caps and "PROXY" in caps and "ASSUMPTION" in caps
    assert any("What this does and doesn't tell you" in label for label in _expanders(at))
    assert any("Biases and limitations" in label for label in _expanders(at))


def test_sentiment_weekly_and_leadlag_controls():
    at = _ok(_run(SENTIMENT))
    at.selectbox(key="sent_w_variant").set_value("adjusted_core").run()
    at.radio(key="sent_w_overlay").set_value("Cash price").run()
    at.toggle(key="sent_w_window").set_value(True).run()
    _ok(at)
    assert "no standard error is published for the aluminium-chain variants" in _captions(at)

    ll = pd.read_csv(ROOT / data.table_rel("sentiment_leadlag"))
    variants = list(dict.fromkeys(ll["variant"]))
    at.multiselect(key="sent_ll_variants").set_value(variants).run()
    at.radio(key="sent_ll_ci").set_value("Fisher (assumes independent weeks)").run()
    _ok(at)
    shown = _table(at, "lag_weeks", "pearson_r", "fisher_ci_lo")
    assert len(shown) == len(ll) and set(shown["variant"]) == set(variants)
    assert "fisher (assumes independent weeks) 95 % interval" in _captions(at)

    ep = pd.read_csv(ROOT / data.table_rel("sentiment_episodes"))
    other = [v for v in dict.fromkeys(ep["variant"])][-1]
    at.radio(key="sent_ep_variant").set_value(other).run()
    _ok(at)
    shown = _table(at, "anchor", "verdict", "verdict_alt_window")
    expected = ep[ep["variant"] == other]
    assert list(shown["verdict"]) == list(expected["verdict"])


def test_sentiment_headline_explorer_filters():
    at = _ok(_run(SENTIMENT))
    scored = pd.read_csv(ROOT / SCORED)
    assert _metrics(at)["Headlines shown"] == f"{len(scored):,} of {len(scored):,}"

    at.text_input(key="sent_hl_search").input("nickel").run()
    _ok(at)
    view = _table(at, "title", "link")
    want = scored[scored["title"].str.contains("nickel", case=False, regex=False)]
    assert len(view) == len(want) > 0 and view["title"].str.lower().str.contains("nickel").all()
    assert _metrics(at)["Headlines shown"] == f"{len(want):,} of {len(scored):,}"

    at.text_input(key="sent_hl_search").input("").run()
    week = sorted(scored["week_end"].unique())[5]
    at.selectbox(key="sent_hl_week").set_value(week).run()
    at.radio(key="sent_hl_score").set_value("Adjusted").run()
    at.multiselect(key="sent_hl_class").set_value(["negative"]).run()
    at.toggle(key="sent_hl_core").set_value(True).run()
    at.radio(key="sent_hl_sort").set_value("Most positive first").run()
    _ok(at)
    view = _table(at, "title", "adj_compound")
    want = scored[(scored["week_end"] == week) & (scored["adj_class"] == "negative") & scored["core_chain"]]
    assert len(view) == len(want)
    assert (view["week_end"] == week).all() and (view["adj_class"] == "negative").all()
    assert list(view["adj_compound"]) == sorted(view["adj_compound"], reverse=True)

    at.multiselect(key="sent_lex_action").set_value(["flipped"]).run()
    _ok(at)
    lex = _table(at, "word", "action")
    assert set(lex["action"]) == {"flipped"}


def test_sentiment_without_scored_headlines_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", _mirror(tmp_path, set(data.PUBLIC_EXPORT_OMITS) | {SCORED}))
    at = _ok(_run(SENTIMENT))
    infos = " ".join(_infos(at))
    assert "sentiment_headlines_scored.csv" in infos and "headlines_weekly.csv" in infos
    assert "sentiment_week_extremes.csv" in _markdown(at)
    ex = _table(at, "side", "title")
    assert set(ex["side"]) <= {"most_negative", "most_positive"} and len(ex) > 0
    assert "Headlines" in _metrics(at)                      # the verdict and the tests do not need the titles


def test_sentiment_with_every_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    at = _ok(_run(SENTIMENT))
    infos = _infos(at)
    assert infos and all("Not in this copy" in i or "no section" in i for i in infos)
    assert not at.metric


# ------------------------------------------------------------------------------------------------ reports
def test_reports_headline_band_and_inventories():
    at = _ok(_run(REPORTS))
    facts = data.headline_facts()
    m = _metrics(at)
    head = next(v for k, v in m.items() if k.startswith("Book P&L"))
    assert head == facts.text["book_pnl"]
    assert m["Anchor-premium band"] == f"{facts.text['band_lo']} to {facts.text['band_hi']}"
    reports = sorted((ROOT / data.REPORTS).iterdir())
    notes = [p for p in reports if re.match(r"desk_note_\d+_\d{4}-\d{2}-\d{2}\.md$", p.name)]
    assert m["Weekly desk notes"] == f"{len(notes)}"
    assert m["Reports as PDF"] == f"{sum(p.suffix == '.pdf' for p in reports)}"
    from desk.reporting import interview_pack as ip

    assert m["Interview questions"] == f"{ip.N_QUESTIONS}"
    recon = data.recon_status()
    assert m["Excel reconciliation"] == recon.status
    assert ("Formula cells recalculated" in m) == (recon.status == "VERIFIED")
    if recon.status == "VERIFIED":
        assert m["Formula cells recalculated"] == f"{recon.n_recalculated:,}"
        assert m["Failed checks"] == f"{recon.n_check_failures}"
    assert "pnl_sensitivity_sign_robustness.csv" in _captions(at)


def test_reports_note_and_interview_pack_selectors():
    at = _ok(_run(REPORTS))
    names = sorted(p.stem for p in (ROOT / data.REPORTS).glob("desk_note_*.md"))
    last = names[-1]
    at.selectbox(key="rep_note").set_value(last).run()
    _ok(at)
    n = re.match(r"desk_note_(\d+)_", last).group(1)
    assert f"Desk note {n}" in _markdown(at)
    assert f"outputs/reports/{last}.md" in _captions(at)
    chart = f"outputs/charts/p6_note_{n}_tape.png"
    if (ROOT / chart).exists():
        assert chart in _captions(at)

    at.selectbox(key="rep_pack_q").set_value(next(o for o in at.selectbox(key="rep_pack_q").options
                                                  if o.startswith("Q17."))).run()
    _ok(at)
    assert "machine learning" in _markdown(at).lower() and "named in the spec" in _captions(at)

    at.radio(key="rep_pack_mode").set_value(next(o for o in at.radio(key="rep_pack_mode").options
                                                 if o.startswith("All"))).run()
    at.text_input(key="rep_pack_filter").input("GARCH").run()
    _ok(at)
    pack = (ROOT / data.REPORTS / "interview_pack.md").read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=## \d+\. )", pack)[1:]
    want = sum("garch" in b.split("\n## What this pack")[0].lower() for b in blocks)
    assert f"{want} of 17 questions match." in _captions(at)
    assert sum(label.startswith("Q") for label in _expanders(at)) == want


def test_reports_docs_browser_and_spec_coverage():
    at = _ok(_run(REPORTS))
    at.selectbox(key="rep_doc_folder").set_value("reviews").run()
    _ok(at)
    doc = "docs/reviews/phase4-7_review_log.md"
    at.selectbox(key="rep_doc:reviews").set_value(doc).run()
    at.selectbox(key=f"rep_docs:section:{doc}").set_value("Verdicts").run()
    _ok(at)
    assert f"Rendered from `{doc}`" in _captions(at)
    assert any(m.value.lstrip().startswith("### Verdicts") for m in at.markdown)

    index = data.spec_index()
    partial = [r for r in index.values() if not r.status.upper().startswith("DONE")]
    at.multiselect(key="rep_spec_status").set_value(sorted({r.status for r in partial})).run()
    _ok(at)
    cov = _table(at, "row", "delivered by")
    assert len(cov) == len(partial) and set(cov["row"]) == {r.label for r in partial}
    at.multiselect(key="rep_spec_status").set_value([]).run()
    at.selectbox(key="rep_spec_table").set_value("Table 7").run()
    _ok(at)
    cov = _table(at, "row", "delivered by")
    assert set(cov["row"]) == {r.label for r in index.values() if r.table.startswith("Table 7")}
    assert "Sentiment overlay" in set(cov["dashboard page"])


def test_reports_with_every_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    at = _ok(_run(REPORTS))
    infos = _infos(at)
    assert infos and all("Not in this copy" in i or "Not computed" in i or "no section" in i for i in infos)
    assert not [m for m in at.metric if m.label.startswith("Book P&L")]
    assert any("desk_note_1_2022-03-25.md" in i for i in infos)
    assert _metrics(at)["Excel reconciliation"] == "NOT_RUN"
    assert "No reconciliation figures are quoted" in " ".join(w.value for w in at.warning)


# ------------------------------------------------------------------------------------------------ data & assumptions
def test_data_register_counts_and_filters():
    from desk import config

    reg = config.params_frame()
    status = reg["verify"].str.extract(r"^\s*([A-Z/]+)")[0]
    at = _ok(_run(DATA_PAGE))
    m = _metrics(at)
    assert m["Parameters"] == f"{len(reg)}"
    for flag in ("DIRECT", "PROXY", "ASSUMPTION"):
        assert m[flag] == f"{int((reg['flag'] == flag).sum())}", flag
    assert m["PENDING"] == f"{int((status == 'PENDING').sum())}"
    assert len(_table(at, "key", "verify_status", "note")) == len(reg)

    at.multiselect(key="da_flag").set_value(["PROXY"]).run()
    _ok(at)
    view = _table(at, "key", "verify_status", "note")
    assert set(view["flag"]) == {"PROXY"} and len(view) == int((reg["flag"] == "PROXY").sum())
    assert f"{len(view)} of {len(reg)} parameters match the filters" in _captions(at)

    at.multiselect(key="da_flag").set_value([]).run()
    at.toggle(key="da_pending").set_value(True).run()
    at.text_input(key="da_search").input("anchor").run()
    _ok(at)
    view = _table(at, "key", "verify_status", "note")
    assert (view["verify_status"] == "PENDING").all() and "domestic_anchor_premium_inr_t" in set(view["key"])

    at.toggle(key="da_pending").set_value(False).run()
    at.text_input(key="da_search").input("").run()
    at.multiselect(key="da_file").set_value(["risk.yaml"]).run()
    at.selectbox(key="da_param").set_value("sent_domain_lexicon").run()
    _ok(at)
    assert set(_table(at, "key", "verify_status", "note")["file"]) == {"risk.yaml"}
    assert "**`sent_domain_lexicon`**" in _markdown(at)


def test_data_other_tabs_filters():
    at = _ok(_run(DATA_PAGE))
    prov = pd.read_csv(ROOT / data.processed_rel("series_provenance"))
    at.radio(key="da_prov_flag").set_value("PROXY").run()
    _ok(at)
    shown = _table(at, "column", "transformation")
    assert set(shown["flag"]) == {"PROXY"} and len(shown) == int((prov["flag"] == "PROXY").sum())

    at.multiselect(key="da_ver_status").set_value(["PENDING"]).run()
    _ok(at)
    log = _table(at, "Parameter", "Status")
    assert len(log) > 0 and log["Status"].str.startswith("PENDING").all()
    assert _metrics(at)["PENDING rows"] == f"{len(log)}"

    at.radio(key="da_model_mode").set_value("All models").run()
    _ok(at)
    assert sum("does and doesn't tell you" in label for label in _expanders(at)) >= 11

    manifest = json.loads((ROOT / "data/raw/_download_manifest.json").read_text(encoding="utf-8"))
    assert _metrics(at)["Manifest entries"] == f"{len(manifest):,}"
    folder = max({k.split("/", 1)[0] for k in manifest if "/" in k},
                 key=lambda f: sum(k.startswith(f + "/") for k in manifest))
    at.multiselect(key="da_man_folder").set_value([folder]).run()
    _ok(at)
    assert not any(k in _markdown(at) + _captions(at) for k in list(manifest)[:50] if "/" in k)   # no file names

    at.multiselect(key="da_pol_category").set_value(["B"]).run()
    _ok(at)
    entries = _table(at, "policy id", "pattern (under data/raw/)")
    assert set(entries["category"]) == {"B"}

    at.selectbox(key="da_review").set_value("docs/reviews/release_polish_check.md").run()
    at.multiselect(key="da_find_sev").set_value(["critical"]).run()
    _ok(at)
    assert "Rendered from `docs/reviews/release_polish_check.md`" in _captions(at)
    assert set(_table(at, "severity", "issue")["severity"]) == {"critical"}


def test_reports_and_data_pages_on_the_public_export(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", _mirror(tmp_path, set(data.PUBLIC_EXPORT_OMITS)))
    reports = _ok(_run(REPORTS))
    facts = data.compute_facts()
    assert [m.value for m in reports.metric if m.label.startswith("Book P&L")] == [facts.text["book_pnl"]]
    assert _metrics(reports)["Weekly desk notes"] == f"{len(list((ROOT / data.REPORTS).glob('desk_note_*.md')))}"
    page = _ok(_run(DATA_PAGE))
    infos = " ".join(_infos(page))
    assert "market_daily.csv" in infos and "run_all.py --only P0" in infos
    assert _metrics(page)["Parameters"] and "Manifest entries" not in _metrics(page)     # data/raw is not mirrored


def test_data_page_with_every_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    at = _ok(_run(DATA_PAGE))
    infos = " ".join(_infos(at))
    for rel in ("config/params/", "series_provenance.csv", "verification_log.md", "_download_manifest.json",
                "public_export_policy.yaml"):
        assert rel in infos, rel
    assert not at.metric
