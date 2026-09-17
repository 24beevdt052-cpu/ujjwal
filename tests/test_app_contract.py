"""Cross-page contract checks for the read-only dashboard (docs/80_frontend.md §2 and §6).

* no page imports a pipeline stage, writes a file or opens a network connection (source scan of app/);
* the page scripts do not live in a directory named `pages/`: Streamlit would auto-discover it and serve the first
  direct-link request on a fresh server through its legacy multipage mode (no navigation, no wide layout);
* every page, and the entrypoint, runs on a copy without data/processed/market_daily.csv and headlines_weekly.csv
  (the public export's omissions) with no exception, the SIM banner, and any note about those files saying how to
  rebuild them online;
* the headline book P&L is a metric only inside `components.pnl_headline` (paired with its band), and any other text
  that states it also states the band; the P&L page's BOOK view carries the band note;
* every chart, table and image sits next to a caption naming its source;
* ten-plus numbers shown on the pages equal the published tables and outputs/reports/one_pager.md.

Run on its own on a small machine: `.venv/bin/python -m pytest -q tests/test_app_contract.py`.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.lib import components, data  # noqa: E402
from desk import HORIZON_END, SIM_LABEL  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
VIEWS = sorted((APP / "views").glob("*.py"))
ENTRYPOINT = APP / "streamlit_app.py"
TIMEOUT = 180
GONE = {"data/processed/market_daily.csv", "data/processed/headlines_weekly.csv"}


def _view(stem: str) -> Path:
    return APP / "views" / f"{stem}.py"


def _run(path: Path) -> AppTest:
    return AppTest.from_file(str(path), default_timeout=TIMEOUT).run()


def _ok(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]


def _plain(s: str) -> str:
    return str(s).replace(" ", " ").replace("−", "-")


def _number(s: str) -> float:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", re.sub(r"₹|USD\s*", "", _plain(s)))     # "−₹105.4 m" -> -105.4
    assert m, s
    return float(m.group(0).replace(",", ""))


def _metrics(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


# ------------------------------------------------------------------------------------------------ source scan
_FORBIDDEN_CALLS = re.compile(r"\.(to_csv|to_excel|to_parquet|to_pickle|write_text|write_bytes|savefig|write_image|"
                              r"write_html|mkdir|unlink|rmdir|touch|symlink_to)\(")
_FORBIDDEN_MODULES = ("requests", "httpx", "urllib.request", "http.client", "socket", "aiohttp", "yfinance", "shutil")
_ALLOWED_DESK = {"desk", "desk.config", "desk.paths", "desk.reporting.style", "desk.reporting.interview_pack",
                 "desk.reporting.one_pager", "desk.excel.reconciliation_status"}
_ALLOWED_TOOLS = {"tools.export_public"}          # its classifier only (Data & assumptions); nothing is exported


def _imports(path: Path) -> set[str]:
    """Every module a file imports; `from pkg import mod` counts as `pkg.mod` when mod is a module file."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            pkg = ROOT / node.module.replace(".", "/")
            out |= {f"{node.module}.{a.name}" for a in node.names if (pkg / f"{a.name}.py").exists()}
    return out


def test_app_source_has_no_writes_network_or_stage_imports():
    files = [ENTRYPOINT, *sorted((APP / "lib").glob("*.py")), *VIEWS]
    problems = []
    for f in files:
        src = f.read_text(encoding="utf-8")
        rel = f.relative_to(ROOT).as_posix()
        problems += [f"{rel}: {m.group(0)}" for m in _FORBIDDEN_CALLS.finditer(src)]
        problems += [f"{rel}: open() for writing" for _ in re.finditer(r"open\([^)]*['\"][wax]b?\+?['\"]", src)]
        mods = _imports(f)
        problems += [f"{rel}: imports {m}" for m in mods
                     if any(m == x or m.startswith(x + ".") for x in _FORBIDDEN_MODULES)]
        desk_ok = _ALLOWED_DESK | {"desk.reporting", "desk.excel"}
        problems += [f"{rel}: imports pipeline module {m}" for m in mods
                     if (m == "desk" or m.startswith("desk.")) and m not in desk_ok]
        problems += [f"{rel}: imports {m}" for m in mods
                     if m.startswith("tools") and m not in _ALLOWED_TOOLS | {"tools"}]
        if "subprocess" in mods and rel != "app/lib/data.py":
            problems.append(f"{rel}: subprocess outside the read-only git lookup")
    assert problems == []
    assert re.findall(r"subprocess\.run\(\[([^\]]*)\]", (APP / "lib" / "data.py").read_text(encoding="utf-8")) == [
        '"git", "rev-parse", "--short", "HEAD"']


def test_page_scripts_are_not_in_a_streamlit_pages_directory():
    assert not (APP / "pages").exists()
    assert {s.path.parent for s in components.PAGES} == {APP / "views"}
    assert {p.name for p in VIEWS} == {s.file for s in components.PAGES}


# ------------------------------------------------------------------------------------------------ public export
def _mirror(tmp: Path, skip: set[str]) -> Path:
    from tests.test_app_pages import _mirror as mirror

    return mirror(tmp, skip)


@pytest.mark.parametrize("page", [*VIEWS, ENTRYPOINT], ids=lambda p: p.stem)
def test_runs_without_market_panel_and_headlines(page, monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", _mirror(tmp_path, GONE))
    at = _run(page)
    _ok(at)
    assert any(SIM_LABEL in m.value for m in at.markdown)
    for note in (i.value for i in at.info):
        if any(g.rsplit("/", 1)[-1] in note for g in GONE) and "Not in this copy" in note:
            assert "online" in note or "run_all.py" in note, note
    heads = [m for m in at.metric if m.label.startswith("Book P&L")]
    assert len(heads) <= 1
    if heads:
        assert "Anchor-premium band" in _metrics(at)


# ------------------------------------------------------------------------------------------------ headline P&L
@pytest.fixture(scope="module")
def facts() -> data.Facts:
    f = data.headline_facts()
    if not components.headline_band_ok(f):
        pytest.skip("headline band not computable in this copy")
    return f


def _texts(at: AppTest) -> list[str]:
    out = []
    for kind in ("markdown", "caption", "info", "warning", "success", "error"):
        out += [str(e.value) for e in getattr(at, kind)]
    return out


@pytest.mark.parametrize("page", VIEWS, ids=lambda p: p.stem)
def test_headline_pnl_only_with_its_band(page, facts):
    at = _run(page)
    _ok(at)
    m = _metrics(at)
    heads = [k for k in m if k.startswith("Book P&L")]
    assert len(heads) <= 1
    if heads:
        assert m[heads[0]] == facts.text["book_pnl"]
        assert m["Anchor-premium band"] == f"{facts.text['band_lo']} to {facts.text['band_hi']}"
        statement = " ".join(w.value for w in at.warning) + " ".join(s.value for s in at.success)
        assert ("Not sign-robust" in statement) != facts.flags["band_sign_robust"]
    # Text the app or the reports generate uses the reports' formatter (a no-break space before "m"); any such text
    # that states the headline also states the band. Prose quoted verbatim from docs/*.md is not re-checked here.
    for text in _texts(at):
        if facts.text["book_pnl"] in text:
            assert facts.text["band_lo"] in text and facts.text["band_hi"] in text, text[:300]


def test_pnl_book_view_carries_the_band_note(facts):
    at = _run(_view("pnl"))
    at.selectbox(key="pnl_trade").select("BOOK").run()
    at.radio(key="pnl_asof").set_value("Horizon").run()
    _ok(at)
    notes = [m.value for m in at.markdown if "read only with the headline's band" in m.value]
    assert notes and all(facts.text["band_lo"] in n and facts.text["band_hi"] in n for n in notes)
    assert ("Not sign-robust" in notes[0]) != facts.flags["band_sign_robust"]


def test_pnl_book_view_is_withheld_without_the_band(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", _mirror(tmp_path, {components.BAND_TABLE}))
    at = _run(_view("pnl"))
    _ok(at)
    options = at.selectbox(key="pnl_trade").options                 # display labels (format_func applied)
    assert options and not any(o == "BOOK" or o.startswith("Book (") for o in options)
    assert not [m for m in at.metric if m.label.startswith("Book P&L")]


# ------------------------------------------------------------------------------------------------ captions
_VISUAL = {"plotly_chart", "dataframe", "table", "image", "imgs", "arrow_data_frame", "vega_lite_chart", "pyplot"}
_LAYOUT = {"flex_container", "column", "vertical", "horizontal"}      # st.columns / st.container: may be climbed out of
_LOOKAHEAD = 6


def _children(node) -> list:
    kids = getattr(node, "children", None)
    return [kids[k] for k in sorted(kids)] if isinstance(kids, dict) else []


def _is_source(el) -> bool:
    if getattr(el, "type", "") not in ("caption", "markdown"):
        return False
    v = str(getattr(el, "value", ""))
    return "Source" in v or "Quoted from" in v or bool(re.search(r"`(outputs|data|docs|config)/", v))


def _has_source(node, depth: int = 0) -> bool:
    if _is_source(node):
        return True
    if depth >= 3 or getattr(node, "type", "") not in _LAYOUT:
        return False
    return any(_has_source(c, depth + 1) for c in _children(node))


_BLOCK_END = {"title", "header", "subheader", "divider", "expander", "status", "tab_container", "popover"}


def _captioned_after(sibs: list) -> bool | None:
    """True: a source caption follows before the block ends (a chart and its data table may share one caption);
    False: a heading, expander or tab set comes first; None: the container ends first."""
    for s in sibs[:_LOOKAHEAD]:
        if _has_source(s):
            return True
        if getattr(s, "type", "") in _BLOCK_END:
            return False
    return None


def _uncaptioned(at: AppTest) -> list[str]:
    """Charts, tables and images with no source caption after them, before the next chart or table. The caption may sit
    outside the st.columns / st.container holding the element, but not outside its expander, tab or popover."""
    bad: list[str] = []

    def walk(node, chain):
        for i, ch in enumerate(_children(node)):
            here = [*chain, (node, i)]
            if getattr(ch, "type", None) in _VISUAL:
                found = None
                for parent, idx in reversed(here):
                    sibs = _children(parent)
                    if sibs and all(getattr(s, "type", "") == "column" for s in sibs):
                        continue                                  # side-by-side columns are not "after" each other
                    found = _captioned_after(sibs[idx + 1:])
                    if found is not None or getattr(parent, "type", "") not in _LAYOUT:
                        break
                if not found:
                    bad.append(f"{ch.type} under {'/'.join(getattr(p, 'type', '?') for p, _ in here[-3:])}")
            walk(ch, here)

    walk(at.main, [])
    return bad


@pytest.mark.parametrize("page", VIEWS, ids=lambda p: p.stem)
def test_every_chart_table_and_image_has_a_source_caption(page):
    at = _run(page)
    _ok(at)
    assert _uncaptioned(at) == []


# ------------------------------------------------------------------------------------------------ numbers
def _table(name: str, **kw) -> pd.DataFrame:
    df = data.table(name, **kw)
    if df is None:
        pytest.skip(f"{name}.csv not in this copy")
    return df


def _one_pager() -> str:
    text = data.read_text(f"{data.REPORTS}/one_pager.md")
    if text is None:
        pytest.skip("one_pager.md not in this copy")
    return _plain(text)


def test_overview_numbers_match_the_tables_and_the_one_pager(facts):
    at = _run(_view("overview"))
    _ok(at)
    m = _metrics(at)
    one = _one_pager()

    att = _table("attribution_daily", usecols=["date", "trade_id", "cum_pnl_inr"])
    book_total = att[att["trade_id"] == "BOOK"].sort_values("date")["cum_pnl_inr"].iloc[-1]
    head = next(v for k, v in m.items() if k.startswith("Book P&L"))
    assert _number(head) == round(book_total / 1e6, 1)                                        # 1
    assert f"**{_plain(head)}**" in one

    rob = _table("pnl_sensitivity_sign_robustness").set_index("family").loc["anchor_premium"]
    lo, hi = (_number(x) for x in _plain(m["Anchor-premium band"]).split(" to "))
    assert (lo, hi) == (round(rob["pnl_min_inr"] / 1e6, 1), round(rob["pnl_max_inr"] / 1e6, 1))  # 2
    assert _plain(m["Anchor-premium band"]) in one
    assert _number(m["Break-even anchor premium"]) == round(rob["breakeven_value"])             # 3
    assert bool(rob["sign_robust_within_band"]) == facts.flags["band_sign_robust"]

    book = _table("trade_book", usecols=["trade_id", "quantity_mt", "boxes"])
    assert int(m["Tickets"]) == len(book)                                                        # 4
    assert _number(m["Tonnes"]) == book["quantity_mt"].sum()                                     # 5
    assert _number(m["Containers"]) == book["boxes"].sum()                                       # 6

    pw = _table("parity_weekly", usecols=["in_window", "trade_eligible"])
    win = pw[pw["in_window"]]
    assert m["Eligible cases"] == f"{int(win['trade_eligible'].sum())} of {len(win)}"             # 7
    assert f"{int(win['trade_eligible'].sum())} of {len(win)} weekly cases passed" in one


def test_market_and_pnl_numbers_match_the_tables():
    ev = _table("adverse_event_windows").set_index("event").loc["E1_LME_CRASH"]
    at = _run(_view("market"))
    _ok(at)
    m = _metrics(at)
    assert _number(m["LME cash record close"]) == ev["start_value"]                               # 8
    assert _number(m["Peak to crash low"]) == round(ev["change_frac"] * 100, 1)

    att = _table("attribution_daily", usecols=["date", "trade_id", "cum_pnl_inr"])
    at = _run(_view("pnl"))
    _ok(at)
    at.selectbox(key="pnl_trade").select("T01").run()
    at.radio(key="pnl_asof").set_value("Horizon").run()
    t01 = att[att["trade_id"] == "T01"].sort_values("date")["cum_pnl_inr"].iloc[-1]
    label = f"P&L to {components.day(HORIZON_END, True)}"
    assert _number(_metrics(at)[label]) == round(t01 / 1e6, 1)                                   # 9
    assert f"+₹{t01 / 1e6:.2f} m" in _one_pager()


def test_risk_sentiment_data_and_reports_numbers_match_the_tables():
    var = _table("var_summary", dtype_str=True)
    var = var[var["scope"] == "book_window"].set_index("metric")["value"].astype(float)
    kup = _table("kupiec", usecols=["sample", "method", "exceptions"])
    kup = kup[kup["sample"] == "book_window"].set_index("method")["exceptions"]
    liq = _table("margin_liquidity_summary", dtype_str=True)
    liq = liq[liq["scope"] == "book"].set_index("metric")["value"]
    at = _run(_view("risk"))
    _ok(at)
    m = _metrics(at)
    assert _number(m["Mean 1-day 95 % VaR, GARCH(1,1)"]) == round(var["var_mean_garch"] / 1e6, 2)   # 10
    g, h = (int(x) for x in m["Book exceptions, GARCH / 250-day"].split(" / "))
    hist250 = [meth for meth in kup.index if "250" in meth]
    assert g == int(kup["garch"]) and len(hist250) == 1 and h == int(kup[hist250[0]])                 # 11
    assert _number(m["Peak funding need"]) == round(float(liq["funding_need_total_inr_max"]) / 1e6, 1)  # 12

    sent = _table("sentiment_summary", dtype_str=True).set_index("metric")["value"]
    at = _run(_view("sentiment"))
    _ok(at)
    assert int(_metrics(at)["Headlines"]) == int(float(sent["n_headlines"]))                    # 13
    assert int(_metrics(at)["Weeks"]) == int(float(sent["n_weeks"]))

    from desk import config

    reg = config.params_frame()
    at = _run(_view("data_assumptions"))
    _ok(at)
    m = _metrics(at)
    assert int(m["Parameters"]) == len(reg)                                                     # 14
    for flag in ("DIRECT", "PROXY", "ASSUMPTION"):
        assert int(m[flag]) == int((reg["flag"] == flag).sum()), flag

    recon = data.read_text(data.RECON_JSON)
    at = _run(_view("reports"))
    _ok(at)
    m = _metrics(at)
    if recon is not None and m.get("Excel reconciliation") == "VERIFIED":
        cells = _number(m["Formula cells recalculated"])
        assert f"{int(cells):,} formula cells recalculated" in _one_pager()                     # 15
        assert str(int(cells)) in json.dumps(json.loads(recon))
