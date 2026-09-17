"""Widget-level tests for the Trade book and P&L & attribution pages (app/views/trade_book.py, app/views/pnl.py).

tests/test_app_pages.py already runs every page once with its defaults. These drive the pages' own filters and
selectors through AppTest and check that what the page shows is the published tables' numbers:

* trade book: the lane filter narrows the summary table; selecting another ticket shows that ticket's rationale from
  config/trades.yaml and its SIM events; the timeline and credit filters rerun cleanly;
* P&L: the headline sits with its band; the per-ticket waterfall at the window end equals that ticket's cumulative
  P&L in attribution_daily.csv with a zero residual; the book option never double-counts the BOOK rows; the
  aggregation, sensitivity-family, basis-measure and buyer selectors rerun cleanly;
* both pages degrade to st.info (never an exception) with every file missing and on the public export's file set.

Run on its own on a small machine: `.venv/bin/python -m pytest -q tests/test_app_page_book_pnl.py`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.lib import components, data  # noqa: E402
from desk import HORIZON_END, SIM_LABEL, WINDOW_END  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TRADE_BOOK = ROOT / "app" / "views" / "trade_book.py"
PNL = ROOT / "app" / "views" / "pnl.py"
TIMEOUT = 180


def _run(path: Path) -> AppTest:
    return AppTest.from_file(str(path), default_timeout=TIMEOUT).run()


def _ok(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]


def _markdown(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def _captions(at: AppTest) -> str:
    return "\n".join(c.value for c in at.caption)


def _metrics(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def _yaml_ticket(tid: str) -> dict:
    return next(t for t in data.trades_yaml()["trades"] if t["trade_id"] == tid)


def _snippet(text: str, n: int = 60) -> str:
    return " ".join(str(text).split())[:n]


needs_book = pytest.mark.skipif(not data.exists(data.table_rel("trade_book")), reason="trade_book.csv not in this copy")
needs_att = pytest.mark.skipif(not data.exists(data.table_rel("attribution_daily")),
                               reason="attribution_daily.csv not in this copy")


# ------------------------------------------------------------------------------------------------ trade book
@pytest.fixture(scope="module")
def book_at() -> AppTest:
    return _run(TRADE_BOOK)


@needs_book
def test_trade_book_default_shows_every_ticket_and_t01_card(book_at):
    at = book_at
    _ok(at)
    assert SIM_LABEL in _markdown(at)
    book = data.trade_book(dtype_str=True)
    assert _metrics(at)["Tickets"] == str(len(book))
    assert f"Showing {len(book)} of {len(book)} tickets" in _captions(at)
    assert _snippet(_yaml_ticket("T01")["rationale"]["text"]) in _markdown(at)
    assert "config/trades.yaml" in _captions(at)
    elig = data.trade_eligibility_check()
    assert _metrics(at)["§5a rule"] == f"{(elig['status'] == 'PASS').sum()} / {len(elig)} pass"


@needs_book
def test_trade_book_lane_filter_narrows_the_summary(book_at):
    at = book_at
    at.multiselect(key="tb_f_lane").set_value(["JEA_NSA"]).run()
    _ok(at)
    book = data.trade_book(dtype_str=True)
    jea = book[book["lane"] == "JEA_NSA"]
    assert f"Showing {len(jea)} of {len(book)} tickets" in _captions(at)
    summary = next(df.value for df in at.dataframe if "Purchase price" in df.value.columns)
    assert sorted(summary["Trade"]) == sorted(jea["trade_id"])
    at.multiselect(key="tb_f_lane").set_value([]).run()             # an empty filter means every lane
    _ok(at)
    assert f"Showing {len(book)} of {len(book)} tickets" in _captions(at)


@needs_book
def test_trade_book_selecting_t08_shows_its_rationale_hedges_and_sim_events(book_at):
    at = book_at
    at.selectbox(key="tb_ticket").select("T08").run()
    _ok(at)
    md = _markdown(at)
    t08 = _yaml_ticket("T08")
    assert _snippet(t08["rationale"]["text"]) in md
    assert _snippet(_yaml_ticket("T01")["rationale"]["text"]) not in md
    for ev in t08["events"]["logistics"]:
        assert ev["event_id"] in md
    assert "RADIOACTIVITY" in md and ":gray-badge[SIM]" in md
    hedges = data.trade_hedges()
    mcx_ids = set(hedges[(hedges["trade_id"] == "T08") & (hedges["instrument"] == "MCX_ALUMINIUM_FUTURE")]["hedge_id"])
    shown = next(df.value for df in at.dataframe if "roll_deadline" in df.value.columns)
    assert set(shown["hedge_id"]) == mcx_ids


@needs_book
def test_trade_book_timeline_and_credit_filters_rerun(book_at):
    at = book_at
    at.multiselect(key="tb_gantt_trades").set_value(["T02", "T05"]).run()
    _ok(at)
    at.selectbox(key="tb_credit_buyer").select("BUY_RJK_01").run()
    _ok(at)
    credit = next(df.value for df in at.dataframe if "exposure_after_inr" in df.value.columns)
    assert set(credit["buyer_id"]) == {"BUY_RJK_01"}
    at.multiselect(key="tb_gantt_trades").set_value([]).run()
    _ok(at)
    assert any("Pick at least one ticket" in i.value for i in at.info)


# ------------------------------------------------------------------------------------------------ P&L
@pytest.fixture(scope="module")
def pnl_at() -> AppTest:
    return _run(PNL)


@needs_att
def test_pnl_headline_only_with_its_band_and_sign_statement(pnl_at):
    at = pnl_at
    _ok(at)
    assert SIM_LABEL in _markdown(at)
    facts = data.headline_facts()
    m = _metrics(at)
    head = [v for k, v in m.items() if k.startswith("Book P&L")]
    assert head == [facts.text["book_pnl"]]
    assert m["Anchor-premium band"] == f"{facts.text['band_lo']} to {facts.text['band_hi']}"
    if not facts.flags["band_sign_robust"]:
        assert any("Not sign-robust" in w.value for w in at.warning)
        assert "is NOT sign-robust" in _markdown(at)
    assert "pnl_sensitivity_sign_robustness.csv" in _captions(at)


@needs_att
def test_pnl_ticket_waterfall_at_window_end_matches_attribution(pnl_at):
    at = pnl_at
    at.selectbox(key="pnl_trade").select("T08").run()
    at.radio(key="pnl_asof").set_value("Window end").run()
    _ok(at)
    att = data.attribution_daily()
    rows = att[(att["trade_id"] == "T08") & (att["date"] <= WINDOW_END.isoformat())].sort_values("date")
    m = _metrics(at)
    label = f"P&L to {components.day(WINDOW_END, True)}"
    assert m[label] == components.inr_m(rows["cum_pnl_inr"].iloc[-1], sign=True)
    assert m["Residual"] == components.inr_m(0.0)
    assert m["Reconciliation gap"] == components.inr_m(0.0)
    assert "T08 rows only; BOOK rows excluded" in _captions(at)

    at.selectbox(key="pnl_trade").select("BOOK").run()
    at.radio(key="pnl_asof").set_value("Horizon").run()
    _ok(at)
    book, trades = data.split_book(att)
    total = book["cum_pnl_inr"].iloc[-1]
    assert _metrics(at)[f"P&L to {components.day(HORIZON_END, True)}"] == components.inr_m(total, sign=True)
    last = trades.groupby("trade_id")["cum_pnl_inr"].last().sum()
    assert abs(last - total) < 1.0                      # BOOK rows are the tickets' sum: showing both would double count


@needs_att
def test_pnl_ticket_table_is_ticket_rows_only(pnl_at):
    at = pnl_at
    table = next(df.value for df in at.dataframe if "P&L to horizon ₹ m" in df.value.columns)
    assert "BOOK" not in set(table["Trade"])
    att = data.attribution_daily()
    _, trades = data.split_book(att)
    expected = trades.groupby("trade_id")["cum_pnl_inr"].last() / 1e6
    got = table.set_index("Trade")["P&L to horizon ₹ m"]
    pd.testing.assert_series_equal(got.sort_index(), expected.sort_index(), check_names=False, atol=1e-9)


@needs_att
def test_pnl_other_selectors_rerun(pnl_at):
    at = pnl_at
    at.radio(key="pnl_agg").set_value("Monthly").run()
    at.radio(key="pnl_time_view").set_value("Cumulative").run()
    at.selectbox(key="pnl_time_scope").select("T02").run()
    _ok(at)
    assert "T02 rows only, summed by monthly period" in _captions(at)
    at.selectbox(key="pnl_sens_family").select("desk_share").run()
    _ok(at)
    at.radio(key="pnl_basis_metric").set_value("(b) + (g) moved jointly").run()
    _ok(at)
    at.selectbox(key="pnl_e3_buyer").select("BUY_JNPT_01").run()
    _ok(at)


@needs_att
def test_pnl_event_numbers_are_the_published_ones(pnl_at):
    at = pnl_at
    e1 = data.read_csv(data.table_rel("adverse_event_1_lme_crash"), dtype_str=True).set_index("metric")["value"]
    e2 = data.read_csv(data.table_rel("adverse_event_2_usdinr"), dtype_str=True).set_index("metric")["value"]
    m = _metrics(at)
    assert m["Hedge benefit"] == components.inr_m(float(e1["hedge_benefit_inr"]), sign=True)
    assert m["Forward-book benefit"] == components.inr_m(float(e2["forward_book_benefit_inr"]), sign=True)
    assert any("Freight fell, it did not spike" in i.value for i in at.info)
    assert "HYPOTHETICAL" in _captions(at)
    assert any("two-sided" in w.value for w in at.warning)


# ------------------------------------------------------------------------------------------------ missing data
@pytest.mark.parametrize("page", [TRADE_BOOK, PNL], ids=lambda p: p.stem)
def test_page_with_every_file_missing_shows_info_not_exception(page, monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    at = _run(page)
    _ok(at)
    assert SIM_LABEL in _markdown(at)
    infos = [i.value for i in at.info]
    assert infos and any("Not in this copy" in i for i in infos)
    assert not [m for m in at.metric if m.label.startswith("Book P&L")]


@pytest.mark.parametrize("page", [TRADE_BOOK, PNL], ids=lambda p: p.stem)
def test_page_on_the_public_export_runs(page, monkeypatch, tmp_path):
    from tests.test_app_pages import _mirror

    monkeypatch.setattr(data, "ROOT", _mirror(tmp_path, set(data.PUBLIC_EXPORT_OMITS)))
    at = _run(page)
    _ok(at)
    assert SIM_LABEL in _markdown(at)
