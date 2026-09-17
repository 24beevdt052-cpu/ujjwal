"""Widget-level tests for the Risk pack page (app/views/risk.py, MASTER_SPEC Table 6 rows 4.1–4.6).

tests/test_app_pages.py already runs every page once with its defaults. These check that what the risk page states
is what the published tables say, and drive its filters through AppTest:

* default view: the lead/lag verdicts are the ones var_lead_lag.csv implies (sign and size of the GARCH lead), the
  Kupiec low-power note quotes kupiec.csv, the credit tab carries the SYNTHETIC banner, every hypothetical stress is
  labelled HYPOTHETICAL, the headline P&L appears only with its band, and each tab quotes its doc section;
* VaR: more methods and the horizon sample change the exception list to the file's; the 95th-percentile reading
  shows the file's lead; the constant-position backtest, the GARCH refit and the MCX-beta path controls rerun;
* Monte Carlo: another snapshot, the memo stresses and another covariance span show that snapshot's rows;
* credit: another counterparty shows its own flag-day counts and events;
* liquidity: another line size and the other fortnight show the grid's and the summary's numbers;
* memo: the limit filters narrow the table to the file's rows;
* missing data: with every file missing, on the public export's file set, and without two of the page's tables, the
  page raises nothing and says what is not in this copy.

Run on its own on a small machine: `.venv/bin/python -m pytest -q tests/test_app_page_risk.py`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.lib import data  # noqa: E402
from app.lib.components import inr_m, num  # noqa: E402
from desk import SIM_LABEL  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RISK = ROOT / "app" / "views" / "risk.py"
TIMEOUT = 180
T = data.table_rel

RISK_TABLES = ("var_daily", "var_lead_lag", "var_backtest_exceptions", "kupiec", "var_summary", "var_mcx_beta",
               "mc_snapshots", "mc_summary", "mc_stress_scenarios", "mc_pnl_distribution", "mc_covariance",
               "credit_scores", "credit_tracker", "credit_band_policy", "margin_liquidity",
               "margin_liquidity_summary", "margin_liquidity_limit_grid", "margin_liquidity_fortnight",
               "margin_liquidity_policy_limits")
needs_tables = pytest.mark.skipif(not all(data.exists(T(n)) for n in RISK_TABLES),
                                  reason="risk tables not in this copy")


def _run() -> AppTest:
    return AppTest.from_file(str(RISK), default_timeout=TIMEOUT).run()


def _ok(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]


def _markdown(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def _captions(at: AppTest) -> str:
    return "\n".join(c.value for c in at.caption)


def _metrics(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def _frame(at: AppTest, column: str, contains: str | None = None) -> pd.DataFrame:
    """The first dataframe with `column` (and, if given, a cell of that column containing `contains`)."""
    for d in at.dataframe:
        df = d.value
        if column in df.columns and (contains is None or df[column].astype(str).str.contains(contains, regex=False).any()):
            return df
    raise AssertionError(f"no dataframe with column {column!r}" + (f" containing {contains!r}" if contains else ""))


def _infos(at: AppTest) -> list[str]:
    return [i.value for i in at.info]


def _lead(series: str, episode: str, pctl: float, method: str = "hist250") -> float:
    ll = data.var_table("lead_lag")
    row = ll[(ll["series"] == series) & (ll["episode"] == episode) & np.isclose(ll["percentile"], pctl)
             & (ll["method"] == method)]
    return float(row["garch_lead_trading_days"].iloc[0])


def _base_pctl() -> float:
    ll = data.var_table("lead_lag")
    return float(ll.loc[ll["base_percentile"], "percentile"].iloc[0])


def _mirror(tmp: Path, skip: set[str]) -> Path:
    """A symlinked copy of the repository's data, docs and outputs without the repo-relative files in `skip`."""
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


@pytest.fixture(scope="module")
def default_at() -> AppTest:
    return _run()


# ------------------------------------------------------------------------------------------------ default view
@needs_tables
def test_default_view_states_what_the_tables_say(default_at):
    at = default_at
    _ok(at)
    md = _markdown(at)
    assert SIM_LABEL in md
    assert at.title[0].value == "Risk pack"
    assert [tab.label for tab in at.tabs][:5] == ["VaR: GARCH vs history", "Monte Carlo stresses",
                                                   "Credit (illustrative)", "Liquidity & margin", "Risk policy memo"]
    assert "**The takeaway:**" in md

    # lead/lag verdicts follow the sign and size of garch_lead_trading_days in var_lead_lag.csv (declared percentile)
    base = _base_pctl()
    lines = {ln.split("**")[1]: ln for ln in md.splitlines() if ln.startswith("- **Into")}
    for label, episode in (("Into the March spike", "LME_MARCH_SPIKE"), ("Into the May–July crash", "LME_MAY_JULY_CRASH")):
        lead = _lead("lme", episode, base)
        line = lines[label]
        if lead < 0:
            assert "GARCH did not lead: the 250-day window" in line and f"{int(abs(lead))} trading days before GARCH" in line
        elif lead > 0:
            assert f"GARCH led the 250-day window by {int(lead)} trading days" in line
    if _lead("lme", "LME_MARCH_SPIKE", base) < 0 and _lead("lme", "LME_MAY_JULY_CRASH", base) < 0:
        assert "GARCH did not lead the 250-day window into the March spike or the May–July crash" in md

    # the Kupiec low-power note quotes the book sample's acceptance region
    kp = data.kupiec().set_index(["sample", "method"]).loc[("book_window", "garch")]
    note = " ".join(_infos(at))
    assert f"from {int(kp['kupiec_accept_min'])} to {int(kp['kupiec_accept_max'])} exceptions" in note

    # credit is labelled illustrative / synthetic
    assert any("SYNTHETIC" in w.value and "ILLUSTRATIVE" in w.value for w in at.warning)

    # every hypothetical stress carries the label
    stresses = _frame(at, "Stress")
    scen = data.mc_table("stress_scenarios")
    first = scen[(scen["snapshot_id"] == scen["snapshot_id"].iloc[0]) & (scen["role"] == "SCENARIO")]
    assert len(stresses) == len(first)
    hypo = stresses[stresses["Stress"].str.contains("Freight|BIS-QCO", regex=True)]
    assert len(hypo) == 2 and hypo["Stress"].str.contains("HYPOTHETICAL").all()

    # the headline P&L only with its band and the sign-robustness statement
    facts = data.headline_facts()
    m = _metrics(at)
    head = [v for k, v in m.items() if k.startswith("Book P&L")]
    assert head == [facts.text["book_pnl"]]
    assert m["Anchor-premium band"] == f"{facts.text['band_lo']} to {facts.text['band_hi']}"
    statement = " ".join(w.value for w in at.warning) + " ".join(s.value for s in at.success)
    assert ("Not sign-robust" in statement) != facts.flags["band_sign_robust"]

    # sources named under the charts and tables, and each tab quotes its doc
    caps = _captions(at)
    for name in RISK_TABLES:
        assert f"{T(name)}" in caps, name
    for doc in ("40_var_garch", "41_monte_carlo", "50_credit_scoring", "51_margin_liquidity"):
        assert f"Quoted from `docs/{doc}.md`" in caps, doc
    assert "outputs/reports/risk_policy_memo.md" in caps
    assert any(b.label.startswith("Risk policy memo (PDF)") for b in at.download_button) or \
        any("risk_policy_memo.pdf" in i for i in _infos(at))


# ------------------------------------------------------------------------------------------------ VaR
@needs_tables
def test_var_methods_period_and_percentile_filters():
    at = _run()
    at.multiselect(key="risk_var_methods").select("hist60")
    at.radio(key="risk_var_period").set_value("horizon")
    at.selectbox(key="risk_ll_pctl").select(0.95)
    at.run()
    _ok(at)

    exc = data.var_table("backtest_exceptions")
    want = exc[(exc["sample"] == "book_to_horizon_memo") & exc["method"].isin(["garch", "hist250", "hist60"])]
    assert len(_frame(at, "Loss ÷ VaR")) == len(want) > 0

    vd = data.var_table("daily", usecols=["position_held", "exception_hist60"])
    n60 = int(vd.loc[vd["position_held"], "exception_hist60"].sum())
    assert f"60-day history {n60}" in _captions(at)

    table = _frame(at, "GARCH lead, trading days")
    lead = _lead("lme", "LME_MARCH_SPIKE", 0.95)
    row = table[(table["Episode"] == "Into the March spike") & (table["Method"] == "250-day history")]
    assert row["GARCH lead, trading days"].iloc[0] == num(lead)
    md = _markdown(at)
    assert "at the 95th percentile (a robustness reading, not the declared rule)" in md
    if lead > 0:
        assert f"GARCH led the 250-day window by {int(lead)} trading days" in md


@needs_tables
def test_backtest_garch_and_beta_controls():
    at = _run()
    at.radio(key="risk_unit_series").set_value("unit_usd_long_1m")
    at.run()
    at.selectbox(key="risk_unit_period").select("2021")
    at.radio(key="risk_garch_series").set_value("fx")
    at.radio(key="risk_garch_dist").set_value("t")
    at.toggle(key="risk_beta_paths").set_value(True)
    at.toggle(key="risk_vol_t").set_value(True)
    at.run()
    _ok(at)

    unit = _frame(at, "Sample", contains="USD 1 m long (USD/INR), 2021")
    kp = data.kupiec()
    want = kp[kp["sample"] == "unit_usd_long_1m_2021"]
    assert unit["Verdict"].tolist() == want["verdict"].tolist()
    assert unit["Exceptions"].tolist() == [num(x) for x in want["exceptions"]]
    assert "beta paths" in _captions(at)
    beta = _frame(at, "Beta (s.e.)")
    assert len(beta) == len(data.var_table("mcx_beta"))


# ------------------------------------------------------------------------------------------------ Monte Carlo
@needs_tables
def test_monte_carlo_snapshot_memo_stresses_and_covariance():
    snap = "PEAK_BUYER_CONTRACTED"
    at = _run()
    at.selectbox(key="risk_mc_snapshot").select(snap)
    at.toggle(key="risk_mc_memo").set_value(True)
    at.selectbox(key="risk_mc_cov_id").select(f"pit_{snap}")
    at.radio(key="risk_mc_cov_kind").set_value("cov_horizon")
    at.run()
    _ok(at)

    scen = data.mc_table("stress_scenarios")
    rows = scen[scen["snapshot_id"] == snap]
    stresses = _frame(at, "Stress")
    assert len(stresses) == len(rows)
    hypo_ids = rows["scenario_id"].str.startswith(("freight_plus", "qco_"))
    assert stresses.loc[hypo_ids.to_numpy(), "Stress"].str.contains("HYPOTHETICAL").all()
    assert stresses["10-day P&L"].tolist() == [inr_m(v, sign=True) for v in rows["pnl_inr"]]

    beyond = rows[(rows["role"] == "SCENARIO") & rows["beyond_every_mc_path"]]
    md = _markdown(at)
    for r in beyond.itertuples():
        assert inr_m(r.pnl_inr, sign=True) in md

    summ = data.mc_table("summary")
    base = summ[(summ["snapshot_id"] == snap) & (summ["role"] == "BASE")].iloc[0]
    variants = _frame(at, "99 % VaR [MC 95 % interval]")
    dp = 2 if abs(base["var99_inr"]) < 10e6 else 1          # the reports' convention: ₹1.00 m, ₹23.0 m
    assert variants.iloc[0]["99 % VaR [MC 95 % interval]"].startswith(inr_m(base["var99_inr"], dp))

    snaps = data.mc_table("snapshots").set_index("snapshot_id")
    assert _metrics(at)["Net LME delta, MT"] == num(snaps.loc[snap, "lme_delta_mt"])
    cov = data.mc_table("covariance")
    span = cov[cov["covariance_id"] == f"pit_{snap}"].iloc[0]
    assert pd.Timestamp(span["span_start"]).strftime("%-d-%b-%Y") in _frame(at, "Span")["Span"].iloc[0]


# ------------------------------------------------------------------------------------------------ credit
@needs_tables
def test_credit_tracker_counterparty_selector():
    cp = "BUY_MUN_01"
    at = _run()
    at.selectbox(key="risk_credit_cp").select(cp)
    at.multiselect(key="risk_credit_measures").select("receivable_inr")
    at.run()
    _ok(at)

    tr = data.credit_table("tracker", usecols=["cp_id", "breach_hard", "flag_soft_utilisation",
                                               "flag_performance_advance_p14", "flag_past_due", "band_final",
                                               "date", "events"])
    one = tr[tr["cp_id"] == cp].sort_values("date")
    m = _metrics(at)
    assert m["Hard breach days"] == str(int(one["breach_hard"].sum()))
    assert m["Soft line days"] == str(int(one["flag_soft_utilisation"].sum()))
    assert m["Performance days"] == str(int(one["flag_performance_advance_p14"].sum()))
    assert m["Past due days"] == str(int(one["flag_past_due"].sum()))
    assert m["Band (final), last day"] == str(one["band_final"].iloc[-1])
    assert len(_frame(at, "Events")) == int(one["events"].notna().sum())
    ranking = _frame(at, "Buyer (SIM)")
    assert ranking["Buyer (SIM)"].tolist() == data.credit_table("scores").sort_values("rank_riskiest_first")["cp_id"].tolist()


# ------------------------------------------------------------------------------------------------ liquidity
@needs_tables
def test_liquidity_line_size_and_fortnight():
    size = 1_250_000_000.0
    at = _run()
    at.radio(key="risk_liq_line").set_value("lc")
    at.toggle(key="risk_liq_margin_fn").set_value(True)
    at.select_slider(key="risk_liq_grid").set_value(size)
    at.radio(key="risk_liq_fortnight").set_value("MARGIN_FORTNIGHT")
    at.radio(key="risk_liq_stress_measure").set_value("vm")
    at.multiselect(key="risk_liq_margin_series").select("cum_vm_inr")
    at.run()
    _ok(at)

    grid = data.margin_liquidity("limit_grid").set_index(["facility", "limit_inr"])
    m = _metrics(at)
    assert m["WC line: days over the line"] == num(grid.loc[("FUND_BASED_WC", size), "days_limit_breach"])
    assert m["WC line: buffer-breach days"] == num(grid.loc[("FUND_BASED_WC", size), "days_buffer_breach"])
    assert m["LC line: days over the line"] == num(grid.loc[("NON_FUND_LC", size), "days_limit_breach"])

    s = data.table("margin_liquidity_summary", dtype_str=True)
    fn = s[s["scope"] == "MARGIN_FORTNIGHT"]
    fn = dict(zip(fn["metric"], fn["value"]))
    assert m["Extra margin cash out"] == inr_m(float(fn["extra_margin_cash_out_stressed_im_inr_max"]))
    book = s[s["scope"] == "book"]
    book = dict(zip(book["metric"], book["value"]))
    memo_days = int(float(book["memo_days_lc_limit_breach_ex_tolerance"]))
    assert f"{memo_days} days over" in _markdown(at)


# ------------------------------------------------------------------------------------------------ memo
@needs_tables
def test_memo_limit_filters():
    at = _run()
    at.multiselect(key="risk_memo_areas").set_value(["liquidity"])
    at.toggle(key="risk_memo_breached").set_value(True)
    at.run()
    _ok(at)
    pl = data.margin_liquidity("policy_limits")
    want = pl[(pl["area"] == "liquidity") & (pl["book_verdict"] != "WITHIN")]
    shown = _frame(at, "Remediation")
    assert shown["Limit"].tolist() == want["limit_id"].tolist()
    memo = data.doc_markdown(f"{data.REPORTS}/risk_policy_memo.md")
    title = memo.splitlines()[0].lstrip("# ").strip()
    assert any(title in m.value for m in at.markdown)


# ------------------------------------------------------------------------------------------------ missing data
def test_every_file_missing_shows_info_not_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", tmp_path)
    at = _run()
    _ok(at)
    assert SIM_LABEL in _markdown(at)
    infos = _infos(at)
    assert infos and all("Not in this copy" in i or "Not computed" in i for i in infos)
    joined = " ".join(infos)
    for rel in (T("var_daily"), T("mc_snapshots"), T("credit_tracker"), T("margin_liquidity"),
                f"{data.REPORTS}/risk_policy_memo.md", f"{data.DOCS}/40_var_garch.md"):
        assert rel in joined, rel
    assert not [m for m in at.metric if m.label.startswith("Book P&L")]
    assert not at.dataframe


@needs_tables
def test_public_export_copy_keeps_every_risk_table(monkeypatch, tmp_path, default_at):
    monkeypatch.setattr(data, "ROOT", _mirror(tmp_path, set(data.PUBLIC_EXPORT_OMITS)))
    at = _run()
    _ok(at)
    assert len(at.dataframe) == len(default_at.dataframe)
    assert not [i for i in _infos(at) if "outputs/tables/" in i]
    assert [m.value for m in at.metric if m.label.startswith("Book P&L")] == [data.compute_facts().text["book_pnl"]]


@needs_tables
def test_two_tables_missing_degrade_only_their_blocks(monkeypatch, tmp_path):
    gone = {T("mc_pnl_distribution"), T("credit_tracker")}
    monkeypatch.setattr(data, "ROOT", _mirror(tmp_path, gone))
    at = _run()
    _ok(at)
    joined = " ".join(_infos(at))
    assert all(g in joined for g in gone) and "--only P4" in joined and "--only P5" in joined
    _frame(at, "Kupiec accepts")            # the VaR tab still renders
    _frame(at, "Band")                      # so does the band policy
    assert "Soft line days" not in _metrics(at)
