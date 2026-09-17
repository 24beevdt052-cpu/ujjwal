"""Tests for the read-only Streamlit dashboard (app/, docs/80_frontend.md).

* every page under app/views/ runs standalone under AppTest without an exception and shows the SIM banner;
* the entrypoint runs (navigation + sidebar footer + the default page);
* the headline facts the app shows are the one-pager's: the partial path used when the public export leaves out
  market_daily.csv / freight_weekly.csv produces the same formatted facts as the canonical computation;
* a missing file becomes an st.info ("Not in this copy"), never an exception: with every file missing, with the
  public export's omissions, and with the band table missing (then the headline P&L is not shown at all).

Run one page at a time on a small machine: `.venv/bin/python -m pytest -q tests/test_app_pages.py -k market`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.lib import components, data, docs_text  # noqa: E402
from desk import SIM_LABEL  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAGES = sorted((ROOT / "app" / "views").glob("*.py"))
ENTRYPOINT = ROOT / "app" / "streamlit_app.py"
OVERVIEW = ROOT / "app" / "views" / "overview.py"
TIMEOUT = 120


def _run(path: Path) -> AppTest:
    return AppTest.from_file(str(path), default_timeout=TIMEOUT).run()


def _no_exception(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]


def _sim_banner_shown(at: AppTest) -> bool:
    return any(SIM_LABEL in m.value for m in at.markdown)


def _infos(at: AppTest) -> list[str]:
    return [i.value for i in at.info]


# ------------------------------------------------------------------------------------------------ pages
def test_every_page_file_is_registered_in_navigation():
    assert {p.name for p in PAGES} == {s.file for s in components.PAGES}
    assert [s.key for s in components.PAGES][0] == "overview"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_page_runs_standalone(page):
    at = _run(page)
    _no_exception(at)
    assert _sim_banner_shown(at)
    assert at.title, "every page has a title"


def test_entrypoint_runs_with_navigation_and_footer():
    at = _run(ENTRYPOINT)
    _no_exception(at)
    assert _sim_banner_shown(at)                                   # the default page (Overview) ran
    footer = " ".join(c.value for c in at.sidebar.caption)
    assert SIM_LABEL in footer and "Excel reconciliation" in footer and "Commit `" in footer


def test_overview_shows_the_headline_only_with_its_band():
    at = _run(OVERVIEW)
    _no_exception(at)
    facts = data.headline_facts()
    labels = {m.label: m.value for m in at.metric}
    head = next(v for k, v in labels.items() if k.startswith("Book P&L"))
    assert head == facts.text["book_pnl"]
    assert labels["Anchor-premium band"] == f"{facts.text['band_lo']} to {facts.text['band_hi']}"
    robust = facts.flags["band_sign_robust"]
    statement = " ".join(w.value for w in at.warning) + " ".join(s.value for s in at.success)
    assert ("Not sign-robust" in statement) != robust
    assert any("pnl_sensitivity_sign_robustness.csv" in c.value for c in at.caption)


# ------------------------------------------------------------------------------------------------ facts
@pytest.mark.skipif(not all(data.exists(r) for r in data.FACT_INPUTS[:-3]),
                    reason="canonical inputs not in this copy (public export)")
def test_partial_facts_equal_the_canonical_facts():
    full = data.compute_facts()
    part = data.compute_facts(absent=data.PUBLIC_EXPORT_OMITS)
    assert full.complete and not full.failed_claims
    assert not part.complete and not part.problems and part.claims_checked
    assert set(part.missing) == {"data/processed/market_daily.csv", "data/processed/freight_weekly.csv"}
    assert {k: v for k, v in part.text.items() if full.text[k] != v} == {}
    assert set(full.text) - set(part.text) == {"day_after_ath"}   # needs the market panel's calendar
    assert part.num == full.num and part.flags == full.flags and part.buckets == full.buckets


def test_headline_text_fallback_formats_like_the_one_pager():
    full = data.compute_facts()
    raw = dict(full.num) | {"n_trades": float(full.text["n_trades"]),
                            "book_boxes": float(full.text["book_boxes"].replace(",", ""))}
    fallback = data._headline_text(raw)
    for k in ("book_pnl", "book_pnl_mt", "book_pnl_we", "band_lo", "band_hi", "band_be", "horizon_end", "book_mt"):
        assert fallback[k] == full.text[k], k


# ------------------------------------------------------------------------------------------------ missing data
def _mirror(tmp: Path, skip: set[str]) -> Path:
    """A copy of the repository made of symlinks, leaving out the repo-relative files in `skip`."""
    for top in ("outputs", "data/processed", "docs", "config"):
        for src in (ROOT / top).rglob("*"):
            rel = src.relative_to(ROOT).as_posix()
            if src.is_dir() or rel in skip or "/raw/" in rel:
                continue
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(src)
    for name in ("README.md", "CONTRACTS.md"):
        (tmp / name).symlink_to(ROOT / name)
    return tmp


def test_overview_with_every_file_missing_shows_info_not_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    at = _run(OVERVIEW)
    _no_exception(at)
    assert _sim_banner_shown(at)
    infos = _infos(at)
    assert infos and all("Not in this copy" in i or "Not computed" in i for i in infos)
    assert any("attribution_daily.csv" in i for i in infos)
    assert not [m for m in at.metric if m.label.startswith("Book P&L")]


def test_overview_on_the_public_export_keeps_the_headline(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", _mirror(tmp_path, set(data.PUBLIC_EXPORT_OMITS)))
    at = _run(OVERVIEW)
    _no_exception(at)
    infos = " ".join(_infos(at))
    assert "market_daily.csv" in infos and "run_all.py --only P0" in infos
    facts = data.compute_facts()
    assert not facts.complete
    assert [m.value for m in at.metric if m.label.startswith("Book P&L")] == [facts.text["book_pnl"]]


def test_headline_is_withheld_when_its_band_table_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", _mirror(tmp_path, {components.BAND_TABLE}))
    at = _run(OVERVIEW)
    _no_exception(at)
    assert not [m for m in at.metric if m.label.startswith("Book P&L")]
    assert any("pnl_sensitivity_sign_robustness.csv" in i for i in _infos(at))


def test_loaders_return_none_and_hints_name_the_stage(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    assert data.var_table("daily") is None and data.market_daily(["date"]) is None and data.params_register() is None
    assert data.report_files() == [] and data.spec_index() == {} and data.series_flags() == {}
    assert data.recon_status().status == "NOT_RUN"
    with pytest.raises(data.MissingData):
        data.require(data.kupiec(), data.table_rel("kupiec"))
    assert "--only P4" in data.rebuild_hint("outputs/tables/var_daily.csv")
    assert "--only P3" in data.rebuild_hint("outputs/tables/trade_cashflows.csv")
    assert "--only P2" in data.rebuild_hint("outputs/tables/trade_book.csv")
    assert "online" in data.rebuild_hint("data/processed/market_daily.csv")


# ------------------------------------------------------------------------------------------------ docs text
def test_what_it_tells_sections_exist_for_every_model_doc():
    for doc in ("10_parity_model", "20_trade_book", "30_mtm_attribution", "31_adverse_events", "35_excel_workbook",
                "40_var_garch", "41_monte_carlo", "50_credit_scoring", "51_margin_liquidity", "70_sentiment_overlay"):
        sec = docs_text.section(f"docs/{doc}.md")
        assert sec is not None and sec.number and len(sec.body) > 200, doc
        assert not sec.body.lstrip().startswith("#")


def test_links_are_rewritten_to_repo_paths_and_specials_escaped():
    md = ("See [`parity_weekly.csv`](../outputs/tables/parity_weekly.csv), [CONTRACTS §5a](../CONTRACTS.md), "
          "[§4](#4-x) and ![eq](../outputs/charts/p3_equity_curve.png); costs $5 and ~10 days, `a~b$`.")
    out = docs_text.for_streamlit(md, "docs/10_parity_model.md")
    assert "`outputs/tables/parity_weekly.csv`" in out and "CONTRACTS §5a (`CONTRACTS.md`)" in out
    assert "§4" in out and "(#4-x)" not in out and "`outputs/charts/p3_equity_curve.png`" in out
    assert r"\$5" in out and r"\~10" in out and "`a~b$`" in out


def test_spec_index_parses_every_row_with_gap_notes():
    index = data.spec_index()
    for s in components.PAGES:
        assert all(r in index for r in s.spec_rows), s.key
    assert index["4.1"].gaps and "PARTIAL" in index["8.4"].status


# ------------------------------------------------------------------------------------------------ charts
def test_chart_helpers_build_valid_figures():
    import pandas as pd

    from app.lib import charts
    from desk.reporting.style import PNL_BUCKETS

    ts = pd.DataFrame({"date": ["2022-03-01", "2022-03-08", "2022-04-22"], "a": [1.0, 3.0, 2.0], "b": [0.5, -1, 0]})
    line = charts.line_chart(ts, "date", {"a": "A", "b": "B"}, dashes={"b": "dot"}, events=data.event_markers())
    charts.band_marker(line, "2022-10-31", -105.4, 334.3, point=192.1, text_lo="lo", text_hi="hi", text_point="pt")
    figs = [
        line,
        charts.bar_chart(["x", "y"], [1.0, -2.0], text=["+1", "−2"]),
        charts.bar_chart(["x", "y"], [1.0, -2.0], orientation="v", text=["+1", "−2"]),
        charts.waterfall([("a", 2.0), ("b", -1.0)]),
        charts.bucket_waterfall({b: 1e6 for b in PNL_BUCKETS}),
        charts.heatmap(pd.DataFrame([[1.0, -1.0], [0.0, 2.0]], index=["r1", "r2"], columns=[74, 75])),
        charts.histogram([0.0, 1.0, 1.5, 3.0], markers=[(1.2, "VaR"), (2.0, "ES", "#000000")]),
    ]
    for fig in figs:
        assert fig.to_json()
        assert any(a.text == SIM_LABEL for a in fig.layout.annotations)
