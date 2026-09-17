"""AppTest interactions for the Market data and Trade finder (parity) pages (app/views/market.py, parity.py).

Beyond tests/test_app_pages.py (every page runs, banner, title), these exercise the filters and check that what the
pages show is the pipeline's own numbers:

* Market: the key window facts equal adverse_event_windows.csv; the date-range presets and the custom range change the
  "at a glance" table; the provenance flag filter and the mirror toggle work; with every file missing, and on a copy
  without the files the public export leaves out, the page shows "Not in this copy" notes and weekly fallbacks.
* Parity: the headline counts equal parity_weekly.csv; grade × lane, reference case, grid, screen, yield and sample
  selectors run and change the numbers shown; the landed-cost waterfall reconciles to the published line items.

Run on its own on a small machine: `.venv/bin/python -m pytest -q tests/test_app_page_market_parity.py`.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.lib import components, data  # noqa: E402
from desk import SIM_LABEL  # noqa: E402
from desk.reporting.interview_pack import inr  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "app" / "views" / "market.py"
PARITY = ROOT / "app" / "views" / "parity.py"
MIRROR = "data/interim/mcx_thirdparty_commoditieschart_2017_2022.csv"
TIMEOUT = 180


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


def _table(at: AppTest, column: str) -> pd.DataFrame:
    hits = [d.value for d in at.dataframe if column in d.value.columns]
    assert hits, f"no table with column {column!r}"
    return hits[0]


def _public_copy(tmp: Path, extra_skip: tuple[str, ...] = ()) -> Path:
    """A copy of the repository as the strict public export would have it: outputs, docs and config linked whole;
    data/processed without the omitted files; no data/interim (the MCX mirror is not exported)."""
    for top in ("outputs", "docs", "config"):
        (tmp / top).symlink_to(ROOT / top, target_is_directory=True)
    skip = set(data.PUBLIC_EXPORT_OMITS) | set(extra_skip)
    (tmp / data.PROCESSED).mkdir(parents=True)
    for src in (ROOT / data.PROCESSED).iterdir():
        rel = f"{data.PROCESSED}/{src.name}"
        if src.is_file() and rel not in skip:
            (tmp / rel).symlink_to(src)
    return tmp


needs_panel = pytest.mark.skipif(not data.exists(data.processed_rel("market_daily")),
                                 reason="market_daily.csv not in this copy (public export)")


# ------------------------------------------------------------------------------------------------ market
def test_market_key_facts_are_the_event_table():
    at = _ok(_run(MARKET))
    ev = pd.read_csv(ROOT / data.table_rel("adverse_event_windows")).set_index("event")
    crash, slide = ev.loc["E1_LME_CRASH"], ev.loc["E2_INR_DEPRECIATION"]
    m = _metrics(at)
    assert m["LME cash record close"] == f"USD {components.num(crash['start_value'], 1)}/t"
    assert m["Peak to crash low"] == components.pct(crash["change_frac"])
    assert m["USD/INR low to high"] == components.pct(slide["change_frac"], sign=True)
    lead = next(x.value for x in at.markdown if x.value.startswith("**LME cash made its record close"))
    assert components.day(crash["start"], True) in lead and "DIRECT" in lead
    caps = _captions(at)
    assert "adverse_event_windows.csv" in caps and "fx_rates_daily.csv" in caps and "series_provenance.csv" in caps
    assert "HYPOTHETICAL" in caps                                   # the +40 % freight stress is labelled


@needs_panel
def test_market_range_presets_change_the_glance_table():
    at = _ok(_run(MARKET))
    default = _table(at, "Series").set_index("Series")
    at.radio(key="market_range").set_value("Mar–Aug 2022 window").run()
    _ok(at)
    assert any(s.value == "1-Mar-2022 to 31-Aug-2022 at a glance" for s in at.subheader)
    window = _table(at, "Series").set_index("Series")
    panel = pd.read_csv(ROOT / data.processed_rel("market_daily"), usecols=["date", "in_window", "lme_cash_usd_t"])
    w = panel[panel["in_window"]]
    top = w.loc[w["lme_cash_usd_t"].idxmax()]
    assert window.loc["LME cash", "High"] == f"{components.num(top['lme_cash_usd_t'], 1)} ({components.day(top['date'], True)})"
    assert window.loc["LME cash", "First"] != default.loc["LME cash", "First"]

    at.radio(key="market_range").set_value("Custom").run()
    at.date_input(key="market_dates").set_value((dt.date(2022, 7, 1), dt.date(2022, 7, 29))).run()
    _ok(at)
    assert any(s.value == "1-Jul-2022 to 29-Jul-2022 at a glance" for s in at.subheader)
    july = _table(at, "Series").set_index("Series")
    j = panel[(panel["date"] >= "2022-07-01") & (panel["date"] <= "2022-07-29")]
    low = j.loc[j["lme_cash_usd_t"].idxmin()]
    assert july.loc["LME cash", "Low"] == f"{components.num(low['lme_cash_usd_t'], 1)} ({components.day(low['date'], True)})"


def test_market_provenance_filter_and_toggles():
    at = _ok(_run(MARKET))
    prov = pd.read_csv(ROOT / data.processed_rel("series_provenance"))
    at.multiselect(key="market_prov_flags").set_value(["PROXY"]).run()
    _ok(at)
    shown = _table(at, "transformation")
    assert set(shown["flag"]) == {"PROXY"} and len(shown) == int((prov["flag"] == "PROXY").sum())
    assert f"{len(shown)} of {len(prov)} market_daily.csv columns" in _captions(at)

    at.toggle(key="market_mm_rates").set_value(True).run()
    _ok(at)
    assert "INR / USD 3M rates" in _captions(at)
    if data.exists(MIRROR):
        assert MIRROR in _captions(at)
        at.toggle(key="market_mirror").set_value(False).run()
        _ok(at)
        assert MIRROR not in _captions(at)


def test_market_with_every_file_missing_shows_info_not_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    at = _ok(_run(MARKET))
    infos = [i.value for i in at.info]
    assert infos and all("Not in this copy" in i or "no longer has" in i for i in infos)
    assert any("adverse_event_windows.csv" in i for i in infos) and any("fx_rates_daily.csv" in i for i in infos)
    assert not at.metric


def test_market_on_the_public_export_falls_back_to_weekly_tables(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", _public_copy(tmp_path))
    at = _ok(_run(MARKET))
    infos = " ".join(i.value for i in at.info)
    assert "market_daily.csv" in infos and "freight_weekly.csv" in infos and MIRROR in infos
    assert "run_all.py --only P0" in infos and "online" in infos
    caps = _captions(at)
    assert "Weekly fallback" in caps and "term_structure_weekly.csv" in caps and "parity_weekly.csv" in caps
    assert "fx_rates_daily.csv" in caps                              # the ECB file is in the public copy
    assert "LME cash record close" in _metrics(at)                  # facts come from the published event table


# ------------------------------------------------------------------------------------------------ parity
@pytest.fixture(scope="module")
def pw() -> pd.DataFrame:
    return pd.read_csv(ROOT / data.table_rel("parity_weekly"))


def test_parity_headline_counts_are_the_published_flags(pw):
    at = _ok(_run(PARITY))
    win = pw[pw["in_window"]]
    m = _metrics(at)
    assert m["Trade-eligible"] == f"{int(win['trade_eligible'].sum())} of {len(win)}"
    assert m["Base screen open"] == f"{int(win['open_base'].sum())} of {len(win)}"
    assert m["No-hindsight gate"] == f"{int(win['trade_eligible_pit'].sum())} of {len(win)}"
    lead = next(x.value for x in at.markdown if "in-window week × grade × lane cases were trade-eligible" in x.value)
    assert "not point-in-time" in lead
    counts = _table(at, "weeks")
    assert int(counts.iloc[-1]["weeks"]) == len(win)


def test_parity_grade_lane_selection_changes_the_numbers(pw):
    at = _ok(_run(PARITY))
    at.selectbox(key="parity_grade").set_value("tense").run()
    at.selectbox(key="parity_lane").set_value("USEC_MUN").run()
    _ok(at)
    s = pw[(pw["grade"] == "tense") & (pw["lane"] == "USEC_MUN") & pw["in_window"]]
    m = _metrics(at)
    assert m["Trade-eligible weeks"] == f"{int(s['trade_eligible'].sum())} of {len(s)}"
    assert m["Best base net arb"] == f"{inr(s['net_arb_inr_t'].max())}/MT"
    flags = _table(at, "trade_eligible_pit")
    assert len(flags) == len(s)
    at.checkbox(key="parity_flags_window").set_value(False).run()
    _ok(at)
    assert len(_table(at, "trade_eligible_pit")) == int(((pw["grade"] == "tense") & (pw["lane"] == "USEC_MUN")).sum())


def test_parity_waterfall_reconciles_to_the_published_line_items(pw):
    at = _ok(_run(PARITY))
    wk = sorted(pw.loc[(pw["grade"] == "zorba") & (pw["lane"] == "JEA_NSA") & pw["in_window"], "week_end"])[-1]
    at.selectbox(key="parity_week").set_value(wk).run()
    _ok(at)
    row = pw[(pw["grade"] == "zorba") & (pw["lane"] == "JEA_NSA") & (pw["week_end"] == wk)].iloc[0]
    m = _metrics(at)
    assert m["Net arb"] == f"{inr(row['net_arb_inr_t'])}/MT" and m["Landed cost"] == f"{inr(row['landed_inr_t'])}/MT"
    cap = next(c.value for c in at.caption if "reconcile to" in c.value)
    gaps = [float(g.replace(",", "")) for g in re.findall(r"within ₹([\d,.]+)/MT", cap)]
    assert len(gaps) == 2 and max(gaps) < 1.0, cap


def test_parity_grids_screens_and_other_selectors_run(pw):
    at = _ok(_run(PARITY))
    long = pd.read_csv(ROOT / data.table_rel("parity_sensitivity_freight_duty"))
    at.selectbox(key="parity_ref").set_value("june_trough").run()
    at.radio(key="parity_grid").set_value("fob").run()
    _ok(at)
    lr = long[(long["ref_case"] == "june_trough") & (long["freight_terms"] == "FOB_desk_books_freight")]
    caps = _captions(at)
    assert f"window open in {int(lr['window_open_shocked'].sum())} of {len(lr)} cells" in caps
    assert "HYPOTHETICAL" in caps and "SENSITIVITY" in caps

    at.radio(key="parity_screen").set_value("trade_eligible_pit").run()
    at.toggle(key="parity_required").set_value(True).run()
    at.radio(key="parity_yield").set_value("low").run()
    samples = [o for o in at.radio(key="parity_corr_sample").options]
    at.radio(key="parity_corr_sample").set_value(pd.read_csv(ROOT / data.table_rel("parity_anchor_correlation"))
                                                 ["sample"].unique()[1]).run()
    at.toggle(key="parity_pit_leg").set_value(True).run()
    _ok(at)
    assert len(samples) == 2
    band = _table(at, "flips_vs_base")
    assert band["required"].all()


def test_parity_with_every_file_missing_shows_info_not_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    at = _ok(_run(PARITY))
    infos = [i.value for i in at.info]
    assert infos and all("Not in this copy" in i for i in infos)
    assert any("parity_weekly.csv" in i for i in infos) and any("term_structure_weekly.csv" in i for i in infos)


def test_parity_on_the_public_export_is_complete(monkeypatch, tmp_path, pw):
    monkeypatch.setattr(data, "ROOT", _public_copy(tmp_path))
    at = _ok(_run(PARITY))
    assert not [i.value for i in at.info if "Not in this copy" in i.value]
    win = pw[pw["in_window"]]
    assert _metrics(at)["Trade-eligible"] == f"{int(win['trade_eligible'].sum())} of {len(win)}"
