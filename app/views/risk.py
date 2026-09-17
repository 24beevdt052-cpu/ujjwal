"""Risk pack (MASTER_SPEC Table 6, rows 4.1–4.6): VaR and its backtests, Monte Carlo stresses, credit scoring and the
credit tracker, margin and liquidity through the crash fortnight, and the risk policy memo.

Every number is read from the Phase 4 / Phase 5 tables as published (`var_*.csv`, `kupiec.csv`, `mc_*.csv`,
`credit_*.csv`, `margin_liquidity*.csv`, `outputs/reports/risk_policy_memo.*`). The page-level takeaway quotes the
one-pager's own formatted facts (`data.headline_facts()`), and the headline book P&L appears only through
`components.pnl_headline` (in the memo tab, because the memo opens with it). The lead/lag verdicts are composed from
`var_lead_lag.csv` rows, never typed in. Light arithmetic only: VaR drawn as a negative number, ₹ scaled to millions,
flag days counted from the tracker's published boolean columns.

Page-local helpers (not in app/lib): `Metrics` (a metric/value/note summary table as a lookup), `_lead_verdict`,
`_alert_phrase` and `_lead_lines` (the lead/lag reading from var_lead_lag.csv), `_stress_label` (appends HYPOTHETICAL
where a stress is one), `_symmetric` (pair rows -> square matrix), `_shade_fortnights`, and small formatters that
return "—" for a missing value.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

from app.lib import charts, components, data, docs_text  # noqa: E402
from app.lib.components import Kpi, day, inr_m, num, pct  # noqa: E402
from desk import SIM_LABEL  # noqa: E402
from desk.reporting.style import PALETTE  # noqa: E402

M = 1e6
T = data.table_rel
DOC40, DOC41 = f"{data.DOCS}/40_var_garch.md", f"{data.DOCS}/41_monte_carlo.md"
DOC50, DOC51 = f"{data.DOCS}/50_credit_scoring.md", f"{data.DOCS}/51_margin_liquidity.md"
MEMO_MD, MEMO_PDF = f"{data.REPORTS}/risk_policy_memo.md", f"{data.REPORTS}/risk_policy_memo.pdf"

METHODS = {"garch": "GARCH(1,1)", "hist250": "250-day history", "hist60": "60-day history",
           "garch_t": "Student-t GARCH (sensitivity)"}
METHOD_COLOR = {"garch": PALETTE["garch"], "hist250": PALETTE["hist"], "hist60": PALETTE["hist"],
                "garch_t": PALETTE["neutral"]}
METHOD_DASH = {"garch": None, "hist250": None, "hist60": "dash", "garch_t": "dot"}
METHOD_SYMBOL = {"garch": "triangle-down", "hist250": "circle-open", "hist60": "square-open"}
SERIES = {"lme": "LME cash", "fx": "USD/INR"}
EPISODES = {"LME_MARCH_SPIKE": "Into the March spike", "LME_MAY_JULY_CRASH": "Into the May–July crash"}
ALERT_TYPES = {"UP_CROSSING": "up-crossing", "ABOVE_WHEN_WINDOW_OPENED": "already above when the search opened",
               "NO_ALERT": "no alert"}
BOOK_SAMPLES = {
    "book_window": "Book, Mar–Aug window",
    "book_to_horizon_memo": "Book to the horizon",
    "book_window_broad_memo": "Book, broad P&L and VaR incl. cash–3M spread",
    "book_window_ex_mcx_exit_roll_days_memo": "Book, days after an MCX exit/roll dropped",
}
UNIT_SAMPLES = {"unit_lme_long_1000mt": "1,000 MT LME long", "unit_usd_long_1m": "USD 1 m long (USD/INR)"}
SNAPSHOTS = {"ATH_PLUS_1": "day after the LME record close", "PEAK_GROSS_LME": "peak gross LME position",
             "PEAK_BUYER_CONTRACTED": "peak buyer contracted exposure"}
VARIANTS = {
    "normal_window": "Normal, window covariance (base)",
    "student_t_window": "Student-t, window covariance",
    "bootstrap_window": "Bootstrap of window days",
    "normal_pit": "Normal, point-in-time covariance",
    "normal_window_mcx_basis": "Base + MCX basis factor (PROXY)",
    "normal_window_to_settlement": "Static to settlement (memo, not a risk number)",
}
FACTORS = {"lme": "LME cash", "fx": "USD/INR", "freight": "Freight", "mcx_basis": "MCX basis"}
STRESS_COLORS = {"market": PALETTE["freight"], "credit": PALETTE["mcx"], "policy": "#7030a0"}
FORTNIGHTS = {"CRASH_FORTNIGHT": ("Crash fortnight", "#f4cccc"),
              "MARGIN_FORTNIGHT": ("Worst margin fortnight", "#fde9d9")}


# ------------------------------------------------------------------------------------------------ helpers
def _ok(x) -> bool:
    try:
        return x is not None and not pd.isna(x)
    except (TypeError, ValueError):
        return True


def _m(x, dp: int = 1, sign: bool = False) -> str:
    return inr_m(float(x), dp, sign) if _ok(x) else "—"


def _mv(x) -> str:
    """A VaR or ES amount as the reports quote it: two decimals below ₹10 m (₹1.00 m), one above (₹23.0 m)."""
    return _m(x, 2 if _ok(x) and abs(float(x)) < 10 * M else 1)


def _p(x, dp: int = 1, sign: bool = False) -> str:
    return pct(float(x), dp, sign) if _ok(x) else "—"


def _d(x, year: bool = False) -> str:
    """A date as the reports write it; a cell that is not a plain date (e.g. "T04@2022-05-10") is shown as written."""
    if not _ok(x) or not str(x).strip():
        return "—"
    try:
        return day(x, year)
    except (ValueError, TypeError):
        return str(x)


def _n(x, dp: int = 0) -> str:
    return num(float(x), dp) if _ok(x) else "—"


def _yes(x) -> str:
    return "yes" if bool(x) else "no"


def _on(note) -> str:
    """'on 2022-07-20; …' -> '20-Jul-2022' ('' when the note names no date)."""
    hit = re.search(r"\d{4}-\d{2}-\d{2}", str(note)) if _ok(note) else None
    return day(hit.group(0), True) if hit else ""


def _table(df: pd.DataFrame, key: str | None = None) -> None:
    st.dataframe(df, hide_index=True, width="stretch", key=key)


def _flags() -> dict[str, str]:
    """Provenance flags of the market inputs every risk number rests on (series_provenance.csv)."""
    f = data.series_flags()
    return {"LME cash": f.get("lme_cash_usd_t", "DIRECT"), "USD/INR": f.get("usdinr", "PROXY"),
            "MCX (unit beta to LME × USD/INR)": f.get("mcx_al_m1_inr_kg", "PROXY"),
            "freight": f.get("freight_jea_nsa_usd_t", "ASSUMPTION")}


def _param_value(key: str):
    reg = data.params_register()
    if reg is None:
        return None
    hit = reg.loc[reg["key"] == key, "value"]
    return None if hit.empty else hit.iloc[0]


class Metrics:
    """A metric/scope/value/unit/note summary table (var_summary.csv, margin_liquidity_summary.csv) as a lookup."""

    def __init__(self, df: pd.DataFrame, scope: str | None = None):
        if scope is not None and "scope" in df:
            df = df[df["scope"] == scope]
        self.values = dict(zip(df["metric"], df["value"]))
        self.notes = dict(zip(df["metric"], df["note"])) if "note" in df else {}

    def has(self, *keys: str) -> bool:
        return all(k in self.values and _ok(self.values[k]) for k in keys)

    def f(self, key: str) -> float:
        return float(self.values[key])

    def s(self, key: str) -> str:
        return str(self.values[key])

    def note(self, key: str) -> str:
        n = self.notes.get(key)
        return str(n) if _ok(n) else ""


def _summary(name: str, scope: str | None = None) -> Metrics | None:
    df = data.table(name, dtype_str=True)
    return None if df is None else Metrics(df, scope)


# lead/lag (var_lead_lag.csv)
def _base_percentile(ll: pd.DataFrame) -> float | None:
    base = ll.loc[ll["base_percentile"].astype(str).str.lower() == "true", "percentile"]
    return float(base.iloc[0]) if len(base) else None


def _pctl(p: float) -> str:
    return f"{p * 100:.0f}th"


def _alert_phrase(r: pd.Series) -> str:
    kind = r["alert_type"]
    if kind == "UP_CROSSING":
        return f"crossed its threshold on {_d(r['alert_date'], True)}"
    if kind == "ABOVE_WHEN_WINDOW_OPENED":
        out = f"was already above its threshold (since {_d(r['alert_date'], True)})"
        below = r["days_below_threshold_in_window"]
        if _ok(below) and int(below) > 0 and _ok(r["first_upcrossing_in_window"]):
            out += (f", dipped below on {int(below)} day{'s' if int(below) != 1 else ''} and re-alerted on "
                    f"{_d(r['first_upcrossing_in_window'], True)}")
        return out
    return "never crossed its threshold"


def _lead_verdict(g: pd.Series, h: pd.Series) -> tuple[str, float | None]:
    """GARCH against the 250-day window on one episode and percentile; positive lead = GARCH first (file convention)."""
    if g["alert_type"] == "NO_ALERT":
        return ("no method alerted" if h["alert_type"] == "NO_ALERT" else "GARCH gave no alert"), None
    lead = h["garch_lead_trading_days"]
    if not _ok(lead):
        return "only GARCH alerted", None
    n = int(abs(float(lead)))
    days = f"{n} trading day{'s' if n != 1 else ''}"
    if lead > 0:
        return f"GARCH led the 250-day window by {days}", float(lead)
    if lead < 0:
        verb = "crossed" if g["alert_type"] == h["alert_type"] == "UP_CROSSING" else "was above its threshold"
        return f"GARCH did not lead: the 250-day window {verb} {days} before GARCH", float(lead)
    return "GARCH and the 250-day window alerted on the same day", 0.0


def _episode_rows(ll: pd.DataFrame, series: str, p: float) -> list[tuple[str, pd.DataFrame]]:
    rows = ll[(ll["series"] == series) & np.isclose(ll["percentile"].astype(float), p)]
    out = []
    for ep in rows["episode"].drop_duplicates():
        by = rows[rows["episode"] == ep].set_index("method")
        if {"garch", "hist250"} <= set(by.index):
            out.append((ep, by))
    return out


def _lead_lines(ll: pd.DataFrame, series: str, p: float) -> list[str]:
    lines = []
    for ep, by in _episode_rows(ll, series, p):
        g, h = by.loc["garch"], by.loc["hist250"]
        verdict, _ = _lead_verdict(g, h)
        parts = [f"GARCH {_alert_phrase(g)}", f"the 250-day window {_alert_phrase(h)}"]
        if "hist60" in by.index:
            parts.append(f"the 60-day window {_alert_phrase(by.loc['hist60'])}")
        lines.append(f"- **{EPISODES.get(ep, ep.replace('_', ' ').title())}** (search {_d(g['search_start'])} → "
                     f"{_d(g['search_end'], True)}): {'; '.join(parts)}. **{verdict[0].upper() + verdict[1:]}.**")
    return lines


def _lead_summary(ll: pd.DataFrame | None) -> str | None:
    """One sentence for the takeaway: did GARCH lead the 250-day window on the declared rule, episode by episode."""
    if ll is None:
        return None
    p = _base_percentile(ll)
    if p is None:
        return None
    eps = [(EPISODES.get(ep, ep).removeprefix("Into "), _lead_verdict(by.loc["garch"], by.loc["hist250"])[1])
           for ep, by in _episode_rows(ll, "lme", p)]
    if not eps:
        return None
    led = [name for name, lead in eps if lead is not None and lead > 0]
    not_led = [name for name, lead in eps if not (lead is not None and lead > 0)]
    rule = f"on the declared {_pctl(p)}-percentile alert rule"
    if not led:
        return f"GARCH did not lead the 250-day window into {' or '.join(not_led)} {rule}"
    if not not_led:
        return f"GARCH led the 250-day window into {' and '.join(led)} {rule}"
    return f"GARCH led the 250-day window into {' and '.join(led)} but not into {' or '.join(not_led)} {rule}"


# Monte Carlo
def _stress_label(r) -> str:
    label = str(r.scenario_label)
    hypothetical = "HYPOTHETICAL" in label.upper() or str(r.scenario_id).startswith(("freight_plus", "qco_"))
    if hypothetical and "HYPOTHETICAL" not in label.upper():
        label += " (HYPOTHETICAL)"
    return label


def _symmetric(pairs: pd.DataFrame, col: str) -> pd.DataFrame:
    factors = list(dict.fromkeys([*pairs["factor_i"], *pairs["factor_j"]]))
    mat = pd.DataFrame(np.nan, index=factors, columns=factors)
    for r in pairs.itertuples():
        mat.loc[r.factor_i, r.factor_j] = mat.loc[r.factor_j, r.factor_i] = getattr(r, col)
    names = [FACTORS.get(f, f) for f in factors]
    mat.index, mat.columns = names, names
    return mat


# liquidity
def _shade_fortnights(fig: go.Figure, windows: pd.DataFrame | None, which: set[str]) -> None:
    if windows is None:
        return
    for w in windows.itertuples():
        if w.window not in which:
            continue
        label, color = FORTNIGHTS.get(w.window, (w.window.replace("_", " ").lower(), "#eeeeee"))
        fig.add_vrect(x0=pd.Timestamp(w.start), x1=pd.Timestamp(w.end), fillcolor=color, opacity=0.6, line_width=0,
                      layer="below", annotation_text=label.lower(), annotation_position="top left",
                      annotation_font=dict(size=10, color=charts.MUTED))


# ------------------------------------------------------------------------------------------------ header
spec = components.PAGE["risk"]
components.sim_banner()
components.page_header(spec.title, spec.blurb, spec.spec_rows)

facts = data.headline_facts()
t = facts.t
ll_all = data.var_table("lead_lag")
lead_sentence = _lead_summary(ll_all)
TAKEAWAY_KEYS = ("var_mean_g", "var_mean_h", "var_n", "beta_w", "var_beta_w", "exc_g", "exc_h", "kmin", "kmax",
                 "beyond", "funding_peak", "funding_date", "wc_limit")
if facts.has(*TAKEAWAY_KEYS):
    st.markdown(docs_text.escape_streamlit(
        f"**The takeaway:** once hedged, the book's measured market risk was small (mean one-day 95 % VaR "
        f"{t('var_mean_g')} on GARCH(1,1), {t('var_mean_h')} on the 250-day window, over {t('var_n')} position days), "
        f"and that small number rests on a unit-beta MCX proxy hedge: at the mirror's weekly beta ({t('beta_w')}) mean "
        f"GARCH VaR is {t('var_beta_w')}. "
        + (f"{lead_sentence[0].upper() + lead_sentence[1:]}, and " if lead_sentence else "")
        + f"Kupiec cannot rank the methods ({t('exc_g')} against {t('exc_h')} exceptions; it accepts "
          f"{t('kmin')} to {t('kmax')}). The risks that mattered were jumps and cash, not price moves: beyond every "
          f"Monte Carlo path, {t('beyond')}; and funding peaked at {t('funding_peak')} on {t('funding_date')} against "
          f"a {t('wc_limit')} line."))
    kpis = [Kpi("Mean 1-day 95 % VaR, GARCH(1,1)", t("var_mean_g"),
                f"over {t('var_n')} position days in the window; {t('var_mean_h')} on the 250-day window"),
            Kpi("Mean 1-day 95 % VaR, 250-day window", t("var_mean_h"),
                f"over {t('var_n')} position days in the window; {t('var_mean_g')} on GARCH(1,1)")]
    if facts.has("exc_exp"):
        kpis.append(Kpi("Book exceptions, GARCH / 250-day", f"{t('exc_g')} / {t('exc_h')}",
                        f"{t('exc_exp')} expected; Kupiec accepts {t('kmin')} to {t('kmax')} at this sample size"))
    if facts.has("mc_apr", "apr_date", "mc_apr_basis"):
        kpis.append(Kpi(f"MC 99 % 10-day VaR, {t('apr_date')}", t("mc_apr"),
                        f"{t('mc_apr_basis')} with an MCX basis factor (PROXY, sensitivity)"))
    if facts.has("credit", "rjk"):
        kpis.append(Kpi("Riskiest buyer (illustrative model)", t("rjk"),
                        docs_text.escape_streamlit(t("credit").replace("**", "")) + "; fitted on SYNTHETIC data"))
    kpis.append(Kpi("Peak funding need", t("funding_peak"), f"on {t('funding_date')} against a {t('wc_limit')} line"))
    for i in range(0, len(kpis), 3):
        components.kpi_row(kpis[i:i + 3])
    components.source_caption(["var_summary", "var_lead_lag", "kupiec", "var_mcx_beta", "mc_summary",
                               "mc_stress_scenarios", "credit_scores", "margin_liquidity_summary"],
                              {"MCX hedge": _flags()["MCX (unit beta to LME × USD/INR)"],
                               "BIS-QCO stress": "HYPOTHETICAL", "credit model": "SYNTHETIC", "buyers": "SIM",
                               "bank lines": data.param_flag("liq_fb_wc_limit_inr") or "ASSUMPTION"},
                              note="figures formatted by desk.reporting.one_pager, the code that writes one_pager.pdf; "
                                   "the lead/lag clause is read from var_lead_lag.csv")
else:
    st.info("Not computed in this copy: the page takeaway needs the headline facts (one_pager's inputs). The tabs "
            "below read their own tables.", icon=":material/info:")

tab_var, tab_mc, tab_credit, tab_liq, tab_memo = st.tabs(
    ["VaR: GARCH vs history", "Monte Carlo stresses", "Credit (illustrative)", "Liquidity & margin",
     "Risk policy memo"])

# ================================================================================================ 4.1 VaR
with tab_var:
    flags = _flags()

    # ---------------------------------------------------------------------------- VaR paths
    st.subheader("Book VaR against realised market P&L")
    c1, c2 = st.columns([1.3, 1])
    methods = c1.multiselect("VaR methods", list(METHODS)[:3], default=["garch", "hist250"], format_func=METHODS.get,
                             key="risk_var_methods")
    period = c2.radio("Days", ["window", "horizon"], horizontal=True, key="risk_var_period",
                      format_func={"window": "Mar–Aug window (Kupiec base)", "horizon": "to the horizon (memo)"}.get)
    cols = ["date", "in_window", "position_held", "pnl_market_inr"] + [f"var_{m}_inr" for m in METHODS if m != "garch_t"] \
        + [f"exception_{m}" for m in METHODS if m != "garch_t"]
    vd = data.var_table("daily", usecols=cols)
    if vd is None:
        components.missing_data(T("var_daily"))
    else:
        v = vd[vd["position_held"] & (vd["in_window"] if period == "window" else True)].sort_values("date")
        x = pd.to_datetime(v["date"])
        pnl = v["pnl_market_inr"] / M
        fig = go.Figure(go.Bar(x=x, y=pnl, name="Realised market P&L",
                               marker_color=np.where(pnl < 0, "#e6a0a0", "#a8c8a0").tolist(),
                               hovertemplate="%{y:,.2f}<extra>market P&L</extra>"))
        for m in methods:
            fig.add_trace(go.Scatter(x=x, y=-v[f"var_{m}_inr"] / M, mode="lines", name=f"−VaR, {METHODS[m]}",
                                     line=dict(color=METHOD_COLOR[m], width=1.8 if m != "hist60" else 1.2,
                                               dash=METHOD_DASH[m]),
                                     hovertemplate=f"%{{y:,.2f}}<extra>−VaR {METHODS[m]}</extra>"))
        for m in methods:
            ex = v[v[f"exception_{m}"]]
            fig.add_trace(go.Scatter(x=pd.to_datetime(ex["date"]), y=ex["pnl_market_inr"] / M, mode="markers",
                                     name=f"exception vs {METHODS[m]}",
                                     marker=dict(symbol=METHOD_SYMBOL[m], size=11, color=METHOD_COLOR[m],
                                                 line=dict(width=1.5, color=METHOD_COLOR[m])),
                                     hovertemplate=f"%{{y:,.2f}}<extra>exception vs {METHODS[m]}</extra>"))
        charts.shade_window(fig)
        charts.mark_events(fig, data.event_markers())
        charts.show(charts.finish(fig, y_title="₹ million per day", height=440), key="risk_var_paths")
        counts = ", ".join(f"{METHODS[m]} {int(v[f'exception_{m}'].sum())}" for m in methods)
        kp = data.kupiec(usecols=["sample", "method", "n", "expected", "kupiec_accept_min", "kupiec_accept_max"])
        sample = "book_window" if period == "window" else "book_to_horizon_memo"
        exp = "" if kp is None else next(
            (f" against {r.expected:.2f} expected over {int(r.n)} days (Kupiec accepts {int(r.kupiec_accept_min)} to "
             f"{int(r.kupiec_accept_max)})" for r in kp[(kp["sample"] == sample) & (kp["method"] == "garch")].itertuples()),
            "")
        components.source_caption(
            ["var_daily"] + (["kupiec"] if kp is not None else []), flags,
            note=f"VaR is drawn below zero as the one-day loss it allows at 95 %; an exception is a position day whose "
                 f"market P&L (LME, basis, freight, FX buckets) fell below it. Exceptions shown: {counts or 'none'}{exp}. "
                 "Market P&L is not the book P&L (no deal margin, grade spread or carry).")
        with st.expander("Exception days, one row per method"):
            exc = data.var_table("backtest_exceptions",
                                 usecols=["sample", "method", "date", "var_inr", "pnl_inr", "shortfall_inr",
                                          "loss_to_var_frac", "largest_loss_bucket"])
            if exc is None:
                components.missing_data(T("var_backtest_exceptions"))
            else:
                e = exc[(exc["sample"] == sample) & exc["method"].isin(methods)].sort_values(["date", "method"])
                _table(pd.DataFrame({
                    "Date": e["date"].map(lambda d: _d(d, True)), "Method": e["method"].map(METHODS.get),
                    "VaR": e["var_inr"].map(lambda z: _m(z, 2)), "Market P&L": e["pnl_inr"].map(lambda z: _m(z, 2)),
                    "Shortfall": e["shortfall_inr"].map(lambda z: _m(z, 2)),
                    "Loss ÷ VaR": e["loss_to_var_frac"].map(lambda z: f"{z:.2f}×" if _ok(z) else "—"),
                    "Largest loss bucket": e["largest_loss_bucket"]}), key="risk_var_exc_table")
                components.source_caption(["var_backtest_exceptions"], flags, note=f"sample `{sample}`")

    # ---------------------------------------------------------------------------- LME price panel
    st.subheader("LME aluminium cash price, 2022")
    lme = data.var_table("unit_backtest_daily", usecols=["date", "lme_cash_usd_t"])
    if lme is None:
        components.missing_data(T("var_unit_backtest_daily"))
    else:
        end = "2022-08-31" if period == "window" else "2022-10-31"
        px = lme[(lme["date"] >= "2022-01-01") & (lme["date"] <= end)]
        charts.show(charts.line_chart(px, "date", {"lme_cash_usd_t": "LME aluminium cash"}, y_title="USD/t",
                                      colors={"lme_cash_usd_t": PALETTE["lme"]}, events=data.event_markers(),
                                      height=260, hover_format=",.0f"), key="risk_var_lme")
        components.source_caption(["var_unit_backtest_daily"], {"LME cash": flags["LME cash"]},
                                  note="the price the unit backtest revalues; from 1-Jan so the February build-up "
                                       "behind the lead/lag test is visible")

    # ---------------------------------------------------------------------------- lead/lag + vol
    st.subheader("Did GARCH flag rising risk earlier?")
    if ll_all is None:
        components.missing_data(T("var_lead_lag"))
    else:
        base = _base_percentile(ll_all)
        if base is not None:
            st.markdown(f"On the declared rule, each method's own **{_pctl(base)} percentile** of its 2019–2021 "
                        "forecasts (LME cash):")
            st.markdown(docs_text.escape_streamlit("\n".join(_lead_lines(ll_all, "lme", base))))
        c1, c2 = st.columns(2)
        series = c1.radio("Series", list(SERIES), format_func=SERIES.get, horizontal=True, key="risk_ll_series")
        pcts = sorted(ll_all["percentile"].astype(float).unique())
        p_sel = c2.selectbox("Alert percentile", pcts, index=pcts.index(base) if base in pcts else 0,
                             format_func=lambda q: _pctl(q) + (" (declared rule)" if base is not None
                                                               and np.isclose(q, base) else " (robustness)"),
                             key="risk_ll_pctl")
        if not (series == "lme" and base is not None and np.isclose(p_sel, base)):
            lines = _lead_lines(ll_all, series, p_sel)
            st.markdown(f"**{SERIES[series]} at the {_pctl(p_sel)} percentile"
                        f"{'' if base is not None and np.isclose(p_sel, base) else ' (a robustness reading, not the declared rule)'}:**")
            st.markdown(docs_text.escape_streamlit("\n".join(lines)) if lines else "No episode rows for this choice.")
        sel = ll_all[(ll_all["series"] == series) & np.isclose(ll_all["percentile"].astype(float), p_sel)]
        _table(pd.DataFrame({
            "Episode": sel["episode"].map(lambda e: EPISODES.get(e, e)), "Method": sel["method"].map(METHODS.get),
            "Threshold σ": sel["threshold_sigma_frac"].map(lambda z: _p(z, 2)),
            "Alert": sel["alert_date"].map(lambda d: _d(d, True)),
            "Alert type": sel["alert_type"].map(lambda a: ALERT_TYPES.get(a, a)),
            "Fresh up-crossing in search": sel["first_upcrossing_in_window"].map(lambda d: _d(d, True)),
            "Days below in search": sel["days_below_threshold_in_window"].map(_n),
            "Peak σ in search": [f"{_p(s_, 2)} ({_d(d_)})" for s_, d_ in
                                 zip(sel["peak_sigma_in_window_frac"], sel["peak_date_in_window"])],
            "GARCH lead, trading days": sel["garch_lead_trading_days"].map(lambda z: _n(z) if _ok(z) else "—"),
        }), key="risk_ll_table")
        note = str(sel["note"].iloc[0]) if len(sel) and _ok(sel["note"].iloc[0]) else ""
        components.source_caption(["var_lead_lag"], {SERIES[series]: flags["LME cash" if series == "lme" else "USD/INR"],
                                                     "alert percentiles": data.param_flag("var_vol_alert_percentiles")
                                                     or "ASSUMPTION"}, note=note)

        st.markdown("**Conditional (GARCH) against rolling-window volatility**")
        c1, c2, c3 = st.columns(3)
        rng = c1.radio("Dates", ["2022", "2019–2022"], horizontal=True, key="risk_vol_range")
        show_t = c2.toggle("Add Student-t GARCH (sensitivity)", value=False, key="risk_vol_t")
        show_thr = c3.toggle(f"Draw the {_pctl(p_sel)}-percentile thresholds", value=True, key="risk_vol_thr")
        vcols = ["date", f"{series}_ret"] + [f"sigma_{series}_{m}_frac" for m in METHODS]
        vf = data.var_table("vol_forecasts", usecols=vcols)
        if vf is None:
            components.missing_data(T("var_vol_forecasts"))
        else:
            if rng == "2022":
                vf = vf[vf["date"] >= "2022-01-01"]
            xv = pd.to_datetime(vf["date"])
            fig = go.Figure(go.Bar(x=xv, y=vf[f"{series}_ret"].abs() * 100, name="|daily log return|",
                                   marker_color="#d9d9d9", hovertemplate="%{y:.2f} %<extra>|return|</extra>"))
            for m in METHODS:
                if m == "garch_t" and not show_t:
                    continue
                fig.add_trace(go.Scatter(x=xv, y=vf[f"sigma_{series}_{m}_frac"] * 100, mode="lines",
                                         name=f"{METHODS[m]} σ forecast",
                                         line=dict(color=METHOD_COLOR[m], dash=METHOD_DASH[m],
                                                   width=1.8 if m in ("garch", "hist250") else 1.2),
                                         hovertemplate=f"%{{y:.2f}} %<extra>{METHODS[m]}</extra>"))
            if show_thr:
                for r in sel.drop_duplicates("method").itertuples():
                    if r.method not in METHOD_COLOR:
                        continue
                    fig.add_trace(go.Scatter(x=[xv.min(), xv.max()], y=[r.threshold_sigma_frac * 100] * 2, mode="lines",
                                             name=f"{METHODS[r.method]} {_pctl(p_sel)}-pct threshold",
                                             line=dict(color=METHOD_COLOR[r.method], width=1, dash="dot"),
                                             hoverinfo="skip"))
            charts.shade_window(fig)
            charts.mark_events(fig, data.event_markers())
            fig = charts.finish(fig, y_title="daily σ, %", height=400)
            fig.update_yaxes(rangemode="tozero")
            charts.show(fig, key="risk_vol_chart")
            components.source_caption(["var_vol_forecasts", "var_lead_lag"],
                                      {SERIES[series]: flags["LME cash" if series == "lme" else "USD/INR"]},
                                      note="each forecast is FOR the date shown, made at the previous close; bars "
                                           "are the absolute daily log return the forecast is judged against")
        vs = _summary("var_summary", "LME")
        if series == "lme" and vs is not None:
            with st.expander("LME σ forecasts on the dates the finding turns on"):
                tags: dict[str, dict[str, str]] = {}
                for k in vs.values:
                    hit = re.fullmatch(r"sigma_lme_(garch|hist250|hist60)_on_(.+)", k)
                    if hit and vs.has(k):
                        tags.setdefault(hit.group(2), {"Point": hit.group(2).replace("_", " ").replace("ath", "ATH"),
                                                       "Forecast for": _on(vs.note(k)) or "—"}
                                        )[METHODS[hit.group(1)]] = _p(vs.f(k), 2)
                rows = sorted(tags.values(), key=lambda r: pd.Timestamp(r["Forecast for"])
                              if r["Forecast for"] != "—" else pd.Timestamp.max)
                _table(pd.DataFrame(rows), key="risk_vol_dates")
                components.source_caption(["var_summary"], {"LME cash": flags["LME cash"]},
                                          note="forecast FOR the date, made at the previous close")

    # ---------------------------------------------------------------------------- backtests
    st.subheader("Backtests: Kupiec coverage and Christoffersen independence")
    kup = data.kupiec()
    if kup is None:
        components.missing_data(T("kupiec"))
    else:
        def _kupiec_frame(df: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
            return pd.DataFrame({
                "Sample": df["sample"].map(lambda s: names.get(s, s)),
                "Method": df["method"].map(lambda m: METHODS.get(m, m)),
                "Days": df["n"].map(_n), "Exceptions": df["exceptions"].map(_n),
                "Expected": df["expected"].map(lambda z: _n(z, 2)),
                "Kupiec accepts": [f"{int(a)} to {int(b)}" for a, b in zip(df["kupiec_accept_min"],
                                                                        df["kupiec_accept_max"])],
                "Kupiec p": df["kupiec_pvalue"].map(lambda z: f"{z:.3f}" if _ok(z) else "—"),
                "Verdict": df["verdict"], "Christoffersen (independence)": df["christoffersen_verdict_ind"],
                "Dates": [f"{_d(a)} → {_d(b, True)}" for a, b in zip(df["start"], df["end"])],
                "Role": df["role"]})

        book = kup[kup["sample"].str.startswith("book")]
        st.markdown("**The book** (market P&L against each method's VaR)")
        _table(_kupiec_frame(book, BOOK_SAMPLES), key="risk_kupiec_book")
        bw = book[book["sample"] == "book_window"].set_index("method")
        if {"garch", "hist250"} <= set(bw.index):
            g = bw.loc["garch"]
            got = ", ".join(f"{int(bw.loc[m, 'exceptions'])} ({METHODS[m]})" for m in ("garch", "hist250", "hist60")
                            if m in bw.index)
            st.info(f"**Low power.** At n = {int(g['n'])} position days with {g['expected']:.1f} exceptions expected, "
                    f"Kupiec does not reject anything from {int(g['kupiec_accept_min'])} to "
                    f"{int(g['kupiec_accept_max'])} exceptions. The book's {got} all pass, so the test cannot rank "
                    "the methods; the constant-position backtest below has the sample size to try.",
                    icon=":material/science:")
        components.source_caption(["kupiec"], flags, note="MEMO rows re-cut the sample; BASE is the declared test")

        st.markdown("**A constant position, 2019–2022** (the power check)")
        c1, c2 = st.columns(2)
        unit = c1.radio("Position", list(UNIT_SAMPLES), format_func=UNIT_SAMPLES.get, horizontal=True,
                        key="risk_unit_series")
        years = sorted({s.rsplit("_", 1)[1] for s in kup["sample"] if re.fullmatch(rf"{unit}_\d{{4}}", s)})
        period_u = c2.selectbox("Period", ["all"] + years, format_func=lambda y: "2019–2022 (base)" if y == "all" else y,
                                key="risk_unit_period")
        smp = unit if period_u == "all" else f"{unit}_{period_u}"
        ur = kup[kup["sample"] == smp]
        _table(_kupiec_frame(ur, {smp: UNIT_SAMPLES[unit] + ("" if period_u == "all" else f", {period_u}")}),
               key="risk_kupiec_unit")
        unit_series = "LME cash" if "lme" in unit else "USD/INR"
        if len(ur):
            r0 = ur.iloc[0]
            components.source_caption(
                ["kupiec"], {unit_series: flags[unit_series]},
                note=f"n = {int(r0['n']):,}: Kupiec accepts {int(r0['kupiec_accept_min'])} to "
                     f"{int(r0['kupiec_accept_max'])} exceptions against {r0['expected']:.2f} expected. {r0['role']}.")
        else:
            components.source_caption(["kupiec"], None, note=f"no rows for sample {smp} in this copy")
        with st.expander("Chart: the constant-position backtest"):
            leg = "lme" if "lme" in unit else "fx"
            ucols = ["date", f"unit_{leg}_pnl_inr"] + [f"unit_{leg}_var_{m}_inr" for m in ("garch", "hist250")] \
                + [f"unit_{leg}_exception_{m}" for m in ("garch", "hist250")]
            ub = data.var_table("unit_backtest_daily", usecols=ucols)
            if ub is None:
                components.missing_data(T("var_unit_backtest_daily"))
            else:
                if period_u != "all":
                    ub = ub[ub["date"].str.startswith(period_u)]
                xu = pd.to_datetime(ub["date"])
                fig = go.Figure(go.Scatter(x=xu, y=ub[f"unit_{leg}_pnl_inr"] / M, mode="markers", name="daily P&L",
                                           marker=dict(size=3, color="#9aa1ab")))
                for m in ("garch", "hist250"):
                    fig.add_trace(go.Scatter(x=xu, y=-ub[f"unit_{leg}_var_{m}_inr"] / M, mode="lines",
                                             name=f"−VaR, {METHODS[m]}", line=dict(color=METHOD_COLOR[m], width=1.3)))
                    ex = ub[ub[f"unit_{leg}_exception_{m}"]]
                    fig.add_trace(go.Scatter(x=pd.to_datetime(ex["date"]), y=ex[f"unit_{leg}_pnl_inr"] / M,
                                             mode="markers", name=f"exception vs {METHODS[m]}",
                                             marker=dict(symbol=METHOD_SYMBOL[m], size=8, color=METHOD_COLOR[m])))
                charts.shade_window(fig, label=None)
                fig = charts.finish(fig, y_title="₹ million per day", height=360)
                fig.update_layout(hovermode="closest")
                charts.show(fig, key="risk_unit_chart")
                components.source_caption(["var_unit_backtest_daily"],
                                          {SERIES[leg]: flags["LME cash" if leg == "lme" else "USD/INR"]})

    # ---------------------------------------------------------------------------- GARCH params
    st.subheader("GARCH(1,1) parameters")
    vsum = data.table("var_summary", dtype_str=True)
    if vsum is None:
        components.missing_data(T("var_summary"))
    else:
        mt = Metrics(vsum)
        labels = {"omega_pct2": ("ω (%²)", lambda z: f"{z:.4f}"), "alpha": ("α", lambda z: f"{z:.3f}"),
                  "beta": ("β", lambda z: f"{z:.3f}"), "persistence": ("α + β", lambda z: f"{z:.3f}"),
                  "half_life_days": ("half-life, days", lambda z: f"{z:.1f}"),
                  "uncond_vol_daily_frac": ("unconditional daily σ", lambda z: _p(z, 2))}
        fits = {"first_window_fit": "fit used into the window", "last_fit": "last weekly refit"}
        rows = []
        for key, (label, fmt) in labels.items():
            row = {"Parameter": label}
            for s_ in ("lme", "fx"):
                for fit, fit_label in fits.items():
                    k = f"garch_{s_}_{fit}_{key}"
                    row[f"{SERIES[s_]}, {fit_label}"] = fmt(mt.f(k)) if mt.has(k) else "—"
            rows.append(row)
        est = {"Parameter": "estimated on"}
        for s_ in ("lme", "fx"):
            for fit, fit_label in fits.items():
                est[f"{SERIES[s_]}, {fit_label}"] = mt.note(f"garch_{s_}_{fit}_alpha").removeprefix("estimated on ")
        rows.append(est)
        _table(pd.DataFrame(rows), key="risk_garch_table")
        bits = []
        for s_ in ("lme", "fx"):
            if mt.has(f"garch_{s_}_boundary_fits"):
                bits.append(f"{SERIES[s_]}: {int(mt.f(f'garch_{s_}_boundary_fits'))} boundary fits "
                            f"({mt.note(f'garch_{s_}_boundary_fits')})")
            if mt.has(f"garch_t_{s_}_first_window_fit_nu"):
                bits.append(f"Student-t ν {mt.f(f'garch_t_{s_}_first_window_fit_nu'):.1f}")
        components.source_caption(["var_summary"], None, note="; ".join(bits) if bits else None)

        c1, c2 = st.columns(2)
        gs = c1.radio("Refits of", list(SERIES), format_func=SERIES.get, horizontal=True, key="risk_garch_series")
        gd = c2.radio("Distribution", ["normal", "t"], horizontal=True, key="risk_garch_dist",
                      format_func={"normal": "Normal (base)", "t": "Student-t (sensitivity)"}.get)
        gp = data.var_table("garch_params", usecols=["series", "dist", "sample_end", "alpha", "beta", "persistence",
                                                     "boundary_fit"])
        if gp is None:
            components.missing_data(T("var_garch_params"))
        else:
            g_ = gp[(gp["series"] == gs) & (gp["dist"] == gd)].sort_values("sample_end")
            fig = charts.line_chart(g_, "sample_end", {"alpha": "α", "beta": "β", "persistence": "α + β"},
                                    colors={"alpha": PALETTE["mcx"], "beta": PALETTE["lme"],
                                            "persistence": PALETTE["loss"]},
                                    y_title="estimate", height=320, hover_format=".3f")
            nb = g_[g_["boundary_fit"]]
            if len(nb):
                fig.add_trace(go.Scatter(x=pd.to_datetime(nb["sample_end"]), y=nb["persistence"], mode="markers",
                                         name="boundary fit", marker=dict(symbol="x", size=7, color="#000000")))
            charts.show(fig, key="risk_garch_refits")
            components.source_caption(["var_garch_params"], {SERIES[gs]: flags["LME cash" if gs == "lme" else "USD/INR"]},
                                      note=f"{len(g_)} weekly refits, each on the returns to its sample end (no "
                                           "look-ahead); x = sample end")

    # ---------------------------------------------------------------------------- MCX beta
    st.subheader("MCX beta: how much the proxy hedge flatters VaR")
    beta = data.var_table("mcx_beta")
    if beta is None:
        components.missing_data(T("var_mcx_beta"))
    else:
        st.markdown(f"{components.flag_badge('SENSITIVITY')} {components.flag_badge('PROXY')} The engine prices MCX at "
                    "unit beta to LME × USD/INR with zero basis, so the hedge offsets the metal exactly. Re-measuring a "
                    "third-party MCX mirror gives a range, not a better number:")
        _table(pd.DataFrame({
            "Sampling": beta["sampling"].str.replace("_", " "),
            "Beta (s.e.)": [f"{b:.2f}" + (f" ({se:.2f})" if _ok(se) else "") for b, se in
                            zip(beta["beta"], beta["beta_se"])],
            "t against 1": beta["t_vs_one"].map(lambda z: _n(z, 1)),
            "R²": beta["r2"].map(lambda z: f"{z:.2f}" if _ok(z) else "—"),
            "Observations": [f"{_n(n_)} {u}" if _ok(n_) else str(u) for n_, u in zip(beta["n_obs"], beta["obs_unit"])],
            "Unhedged share of a parity move": beta["unhedged_frac_of_parity_move"].map(lambda z: _p(z, 0)),
            "Mean GARCH VaR": beta["var_mean_garch_inr"].map(lambda z: _m(z, 2) if _ok(z) else "not run"),
            "Mean 250-day VaR": beta["var_mean_hist250_inr"].map(lambda z: _m(z, 2) if _ok(z) else "not run"),
            "Reading": beta["reading"], "Flag": beta["flag"]}), key="risk_beta_table")
        run = beta[beta["var_mean_garch_inr"].notna()].sort_values("var_mean_garch_inr")
        if len(run):
            fig = charts.bar_chart(run["sampling"].str.replace("_", " ").tolist(),
                                   (run["var_mean_garch_inr"] / M).tolist(),
                                   colors=[PALETTE["neutral"] if s_ == "engine_unit_beta" else PALETTE["mcx"]
                                           for s_ in run["sampling"]],
                                   value_title="mean book GARCH VaR, ₹ million",
                                   text=[_m(z, 2) for z in run["var_mean_garch_inr"]])
            charts.show(fig, key="risk_beta_bars")
        label = str(beta["label"].iloc[0]) if "label" in beta and len(beta) else ""
        components.source_caption(["var_mcx_beta"], {"MCX mirror": "PROXY", "beta variants": "SENSITIVITY"},
                                  note=label)
        if st.toggle("Show the book VaR path at each beta", value=False, key="risk_beta_paths"):
            bp = data.var_table("daily", usecols=["date", "in_window", "position_held", "var_garch_inr",
                                                  "var_garch_mcx_beta_weekly_sensitivity_inr",
                                                  "var_garch_mcx_beta_sensitivity_inr"])
            if bp is None:
                components.missing_data(T("var_daily"))
            else:
                b_ = bp[bp["position_held"] & bp["in_window"]].copy()
                for c_ in ("var_garch_inr", "var_garch_mcx_beta_weekly_sensitivity_inr",
                           "var_garch_mcx_beta_sensitivity_inr"):
                    b_[c_] = b_[c_] / M
                charts.show(charts.line_chart(
                    b_, "date", {"var_garch_inr": "unit beta (base)",
                                 "var_garch_mcx_beta_weekly_sensitivity_inr": "weekly beta (central)",
                                 "var_garch_mcx_beta_sensitivity_inr": "daily beta (pessimistic)"},
                    colors={"var_garch_inr": PALETTE["neutral"],
                            "var_garch_mcx_beta_weekly_sensitivity_inr": PALETTE["mcx"],
                            "var_garch_mcx_beta_sensitivity_inr": PALETTE["loss"]},
                    dashes={"var_garch_mcx_beta_sensitivity_inr": "dash"}, y_title="GARCH VaR, ₹ million",
                    events=data.event_markers(), height=340, hover_format=",.2f"), key="risk_beta_path_chart")
                components.source_caption(["var_daily"], {"MCX mirror betas": "PROXY", "beta paths": "SENSITIVITY"})

    components.what_it_tells(DOC40)

# ================================================================================================ 4.2 Monte Carlo
with tab_mc:
    snaps = data.mc_table("snapshots", usecols=["snapshot_id", "snapshot_date", "rule", "trades_on_book", "lme_delta_mt",
                                                "lme_delta_physical_mt", "lme_delta_mcx_mt", "mcx_lots_open",
                                                "unsold_mt"])
    summ = data.mc_table("summary")
    scen = data.mc_table("stress_scenarios")
    if snaps is None:
        components.missing_data(T("mc_snapshots"))
    else:
        ids = snaps["snapshot_id"].tolist()
        sdate = dict(zip(snaps["snapshot_id"], snaps["snapshot_date"]))
        snap = st.selectbox("Snapshot date (each fixed by a rule declared before any result)", ids,
                            format_func=lambda s: f"{_d(sdate[s], True)} — {SNAPSHOTS.get(s, s)} ({s})",
                            key="risk_mc_snapshot")
        row = snaps.set_index("snapshot_id").loc[snap]
        st.caption(docs_text.escape_streamlit(f"Rule: {row['rule']}."))
        components.kpi_row([
            Kpi("Tickets on the book", str(len(str(row["trades_on_book"]).split())), str(row["trades_on_book"])),
            Kpi("LME physical, MT", _n(row["lme_delta_physical_mt"])),
            Kpi("MCX hedge, MT", _n(row["lme_delta_mcx_mt"])),
            Kpi("Net LME delta, MT", _n(row["lme_delta_mt"])),
            Kpi("Open MCX lots", _n(row["mcx_lots_open"])),
        ])
        components.source_caption(["mc_snapshots"], ["SIM"], note="the book as it stood at that close")

        st.subheader("10-day P&L distribution, with VaR, ES and the five stresses")
        show_memo = st.toggle("Add the memo stress variants (unhedged, recoveries, combinations)", value=False,
                              key="risk_mc_memo")
        dist = data.mc_table("pnl_distribution", usecols=["snapshot_id", "variant", "pnl_inr"])
        if not components.available(T("mc_pnl_distribution"), T("mc_summary"), T("mc_stress_scenarios")):
            pass
        else:
            d_ = dist[(dist["snapshot_id"] == snap) & (dist["variant"] == "normal_window")]["pnl_inr"] / M
            b_ = summ[(summ["snapshot_id"] == snap) & (summ["role"] == "BASE")]
            s_ = scen[(scen["snapshot_id"] == snap) & (scen["role"].isin(["SCENARIO", "MEMO"] if show_memo
                                                                          else ["SCENARIO"]))]
            if b_.empty or d_.empty:
                st.info("Not computed in this copy: no base paths for this snapshot.", icon=":material/info:")
            else:
                b0 = b_.iloc[0]
                markers = [(-b0["var95_inr"] / M, f"95 % VaR {_mv(b0['var95_inr'])}", PALETTE["mcx"]),
                           (-b0["es95_inr"] / M, f"95 % ES {_mv(b0['es95_inr'])}", "#8a3b00"),
                           (-b0["var99_inr"] / M, f"99 % VaR {_mv(b0['var99_inr'])}", PALETTE["loss"]),
                           (-b0["es99_inr"] / M, f"99 % ES {_mv(b0['es99_inr'])}", "#7a0000")]
                fig = charts.histogram(d_, markers=markers, x_title="10-day book P&L, ₹ million", height=480,
                                       nbins=90, color="#b9c7d8")
                fig.update_layout(yaxis2=dict(overlaying="y", range=[0, 1], visible=False, fixedrange=True))
                for i, r in enumerate(s_.sort_values(["role", "pnl_inr"], ascending=[False, True]).itertuples()):
                    lab = _stress_label(r) + (" · memo" if r.role == "MEMO" else "")
                    col = STRESS_COLORS.get(r.kind, PALETTE["neutral"])
                    y = 0.64 - 0.058 * i
                    fig.add_trace(go.Scatter(
                        x=[r.pnl_inr / M], y=[y], yaxis="y2", mode="markers",
                        marker=dict(symbol="diamond" if r.role == "SCENARIO" else "diamond-open", size=11, color=col),
                        hovertemplate=f"{lab}<br>%{{x:,.1f}} ₹ m<extra></extra>", showlegend=False))
                    fig.add_annotation(x=r.pnl_inr / M, y=y, xref="x", yref="paper", showarrow=False,
                                       text=f"{lab}: {_m(r.pnl_inr, sign=True)}",
                                       xanchor="left" if r.pnl_inr <= 0 else "right", xshift=9 if r.pnl_inr <= 0 else -9,
                                       font=dict(size=10, color=col), bgcolor="rgba(255,255,255,0.85)")
                charts.show(fig, key="risk_mc_hist")
                beyond = s_[s_["beyond_every_mc_path"] & (s_["role"] == "SCENARIO")]
                if len(beyond):
                    st.markdown(docs_text.escape_streamlit(
                        f"**Beyond every one of the {int(b0['n_paths']):,} paths on {_d(sdate[snap], True)}:** "
                        + "; ".join(f"{_stress_label(r)} {_m(r.pnl_inr, sign=True)} ({r.loss_over_mc_var99:.1f}× the "
                                    f"99 % VaR of {_mv(b0['var99_inr'])})" for r in beyond.itertuples())
                        + ". These are jumps, not factor moves, so no path of the simulation can produce them."))
                else:
                    st.markdown(f"No stress falls beyond every path on {_d(sdate[snap], True)}.")
                components.source_caption(
                    ["mc_pnl_distribution", "mc_summary", "mc_stress_scenarios"],
                    {"freight +40 % and BIS-QCO hold": "HYPOTHETICAL", "buyer default": "SIM",
                     "MCX (unit beta)": _flags()["MCX (unit beta to LME × USD/INR)"]},
                    note=f"base variant, {int(b0['horizon_bdays'])} business days; inputs: {b0['input_flags']}")

                st.markdown("**The stresses on this date**")
                _table(pd.DataFrame({
                    "Stress": [_stress_label(r) for r in s_.itertuples()], "Kind": s_["kind"], "Role": s_["role"],
                    "10-day P&L": s_["pnl_inr"].map(lambda z: _m(z, sign=True)),
                    "Share of paths at or below": s_["mc_percentile_frac"].map(lambda z: _p(z, 2)),
                    "Beyond 99 % VaR": s_["beyond_mc_var99"].map(_yes),
                    "Beyond every path": s_["beyond_every_mc_path"].map(_yes),
                    "Loss ÷ 99 % VaR": s_["loss_over_mc_var99"].map(lambda z: f"{z:.2f}×" if _ok(z) and z > 0 else "—"),
                    "Factor move, 10-day σ": s_["factor_move_sigma_horizon"].map(
                        lambda z: f"{z:+.2f}" if _ok(z) else "n/a"),
                    "Note": s_["note"]}), key="risk_mc_stress_table")
                components.source_caption(["mc_stress_scenarios", "mc_stress_details"],
                                          {"freight +40 % (freight fell in 2022)": "HYPOTHETICAL",
                                           "BIS-QCO hold (no QCO applied to scrap in 2022)": "HYPOTHETICAL",
                                           "BUY_RJK_01": "SIM"})

        st.subheader("Every variant on this date")
        if summ is None:
            components.missing_data(T("mc_summary"))
        else:
            v_ = summ[summ["snapshot_id"] == snap]
            _table(pd.DataFrame({
                "Variant": v_["variant"].map(lambda z: VARIANTS.get(z, z)), "Role": v_["role"],
                "Factors": v_["factors"], "Paths": v_["n_paths"].map(_n),
                "95 % VaR": v_["var95_inr"].map(_mv), "95 % ES": v_["es95_inr"].map(_mv),
                "99 % VaR [MC 95 % interval]": [
                    f"{_mv(a)} [{_n(lo / M, 2 if abs(a) < 10 * M else 1)}, {_n(hi / M, 2 if abs(a) < 10 * M else 1)}]"
                    for a, lo, hi in zip(v_["var99_inr"], v_["var99_ci95_low_inr"], v_["var99_ci95_high_inr"])],
                "99 % ES": v_["es99_inr"].map(_mv), "P(loss)": v_["prob_loss_frac"].map(lambda z: _p(z, 1)),
                "Description": v_["description"]}), key="risk_mc_variants")
            components.source_caption(["mc_summary"], {"MCX basis factor": "PROXY", "variants": "SENSITIVITY"},
                                      note="VaR and ES are positive loss amounts; the static-to-settlement row is a "
                                           "memo, not a risk number")

            st.subheader("The MCX basis factor: what unit beta hides")
            bb = summ[summ["variant"].isin(["normal_window", "normal_window_mcx_basis"])]
            wide = bb.pivot_table(index=["snapshot_id", "snapshot_date"], columns="variant", values="var99_inr",
                                  aggfunc="first").reset_index().sort_values("snapshot_date")
            if {"normal_window", "normal_window_mcx_basis"} <= set(wide.columns):
                xl = [f"{_d(d)} · {SNAPSHOTS.get(s, s)}" for s, d in zip(wide["snapshot_id"], wide["snapshot_date"])]
                fig = go.Figure([
                    go.Bar(x=xl, y=wide["normal_window"] / M, name="base (unit beta, no basis)",
                           marker_color=PALETTE["neutral"], text=[_mv(z) for z in wide["normal_window"]],
                           textposition="outside", cliponaxis=False),
                    go.Bar(x=xl, y=wide["normal_window_mcx_basis"] / M, name="with the MCX basis factor (PROXY)",
                           marker_color=PALETTE["mcx"], text=[_mv(z) for z in wide["normal_window_mcx_basis"]],
                           textposition="outside", cliponaxis=False)])
                fig = charts.finish(fig, y_title="99 % 10-day VaR, ₹ million", height=340)
                fig.update_layout(barmode="group", hovermode="closest")
                charts.show(fig, key="risk_mc_basis")
                st.markdown(docs_text.escape_streamlit("; ".join(
                    f"{_d(d)}: {_mv(a)} → {_mv(b)} (×{b / a:.2f})" if a else f"{_d(d)}: {_mv(a)} → {_mv(b)}"
                    for d, a, b in zip(wide["snapshot_date"], wide["normal_window"],
                                       wide["normal_window_mcx_basis"])) + "."))
                components.source_caption(["mc_summary"], {"MCX basis (third-party mirror)": "PROXY",
                                                           "basis variant": "SENSITIVITY"},
                                          note="a hedged book's residual risk is mostly basis, which the base "
                                               "simulation cannot see")

        st.subheader("Covariance and correlation of the factors")
        cov = data.mc_table("covariance")
        if cov is None:
            components.missing_data(T("mc_covariance"))
        else:
            c1, c2 = st.columns(2)
            cids = cov["covariance_id"].drop_duplicates().tolist()
            cid = c1.selectbox("Estimation span", cids, index=cids.index("window") if "window" in cids else 0,
                               key="risk_mc_cov_id",
                               format_func=lambda c: {"window": "window (base)",
                                                      "window_mcx_basis": "window + MCX basis (PROXY)"}.get(
                                   c, c.replace("pit_", "point-in-time to ")))
            kind = c2.radio("Show", ["corr", "cov_horizon"], horizontal=True, key="risk_mc_cov_kind",
                            format_func={"corr": "correlation", "cov_horizon": "covariance, 10-day"}.get)
            pairs = cov[cov["covariance_id"] == cid]
            mat = _symmetric(pairs, kind)
            fig = charts.heatmap(mat, colorscale="RdBu", zmid=0.0, text_format=".2f" if kind == "corr" else ".2e",
                                 colorbar_title="ρ" if kind == "corr" else "cov", height=320)
            if kind == "corr":
                fig.update_traces(zmin=-1, zmax=1)
            charts.show(fig, key="risk_mc_cov_heat")
            diag = pairs[pairs["factor_i"] == pairs["factor_j"]]
            _table(pd.DataFrame({
                "Factor": diag["factor_i"].map(lambda f: FACTORS.get(f, f)), "Unit": diag["unit_i"],
                "σ daily": diag["sd_i_daily"].map(lambda z: f"{z:.4g}"),
                "σ 10-day": diag["sd_i_horizon"].map(lambda z: f"{z:.4g}"),
                "Observations": diag["n_obs"].map(_n),
                "Span": [f"{_d(a, True)} → {_d(b, True)}" for a, b in zip(diag["span_start"], diag["span_end"])],
                "PSD-adjusted": diag["psd_adjusted"].map(_yes)}), key="risk_mc_cov_sd")
            fstats = data.mc_table("factor_stats", usecols=["factor", "frequency", "flag"])
            fflags = {} if fstats is None else {FACTORS.get(f, f): fl for f, fl in
                                                 zip(fstats["factor"], fstats["flag"])}
            components.source_caption(["mc_covariance"] + (["mc_factor_stats"] if fflags else []), fflags or None,
                                      note="log returns, except the MCX basis in ₹/kg absolute changes")

        with st.expander("Are the factors normal? (factor statistics)"):
            fs = data.mc_table("factor_stats")
            if fs is None:
                components.missing_data(T("mc_factor_stats"))
            else:
                _table(pd.DataFrame({
                    "Factor": fs["factor"].map(lambda f: FACTORS.get(f, f)), "Frequency": fs["frequency"],
                    "Role": fs["role"], "Unit": fs["unit"], "Observations": fs["n_obs"].map(_n),
                    "σ": fs["stdev"].map(lambda z: f"{z:.4g}"), "Skew": fs["skew"].map(lambda z: f"{z:+.2f}"),
                    "Excess kurtosis": fs["excess_kurtosis"].map(lambda z: f"{z:+.2f}"),
                    "Jarque–Bera p": fs["jarque_bera_p"].map(lambda z: f"{z:.3f}"), "Flag": fs["flag"]}),
                    key="risk_mc_fstats")
                components.source_caption(["mc_factor_stats"], None)
        with st.expander("What drives the tail on this date (99 % ES contributions by ticket)"):
            esc = data.mc_table("es_contributions")
            if esc is None:
                components.missing_data(T("mc_es_contributions"))
            else:
                e_ = esc[esc["snapshot_id"] == snap]
                _table(pd.DataFrame({
                    "Ticket (SIM)": e_["trade_id"], "Share of 99 % ES": e_["es99_share_frac"].map(lambda z: _p(z, 1)),
                    "ES contribution": e_["es99_contribution_inr"].map(_m),
                    "Stand-alone 99 % VaR": e_["standalone_var99_inr"].map(_m),
                    "Stand-alone 99 % ES": e_["standalone_es99_inr"].map(_m)}), key="risk_mc_es")
                components.source_caption(["mc_es_contributions"], ["SIM"],
                                          note="a negative share is a ticket that hedges the rest of the book in the tail")

    components.what_it_tells(DOC41)

# ================================================================================================ 4.3–4.4 credit
with tab_credit:
    synth_label = "ILLUSTRATIVE SYNTHETIC DATA — fictional buyer population, not real counterparties"
    cal = data.credit_table("model_calibration", usecols=["label"])
    if cal is not None and len(cal):
        synth_label = str(cal["label"].iloc[0])
    synth = data.credit_table("synthetic_training_data", usecols=["obs_id"])
    fit = data.credit_table("model_fit", usecols=["split", "metric", "value"])
    auc = None if fit is None else fit[(fit["split"] == "test") & (fit["metric"] == "auc_fitted")]["value"]
    st.warning(
        f"{components.flag_badge('SYNTHETIC')} {components.flag_badge('SIM')} **ILLUSTRATIVE model on synthetic data.** "
        f"The logistic PD model is fitted on {'' if synth is None else f'{len(synth):,} '}synthetic buyer-quarters "
        "drawn from a process with exactly its four features"
        + (f" (test AUC {float(auc.iloc[0]):.2f} says it recovered its own generator, nothing more)"
           if auc is not None and len(auc) else "")
        + ". The three buyers are fictional, and their profiles were written by the book's author, so the ranking is "
          f"largely by construction. {docs_text.escape_streamlit(synth_label)}.", icon=":material/science:")

    st.subheader("Buyer ranking, riskiest first")
    scores = data.credit_table("scores")
    coef = data.credit_table("model_coefficients")
    term_label = {} if coef is None else dict(zip(coef["term"], coef["label"]))
    if scores is None:
        components.missing_data(T("credit_scores"))
    else:
        sc = scores.sort_values("rank_riskiest_first")
        _table(pd.DataFrame({
            "Rank": sc["rank_riskiest_first"].map(_n), "Buyer (SIM)": sc["cp_id"], "Name": sc["cp_name"],
            "Model PD, annual": sc["pd_model_annual_frac"].map(lambda z: _p(z, 1)),
            "Band (model)": sc["band_model"], "Advance overlay, notches": sc["overlay_notches"].map(_n),
            "Band (final)": sc["band_final"], "Limit": sc["credit_limit_inr"].map(lambda z: _m(z, 0)),
            "Recommended limit": sc["recommended_limit_inr"].map(lambda z: _m(z, 0)),
            "Limit action": sc["limit_action"], "Top risk driver": sc["top_risk_driver"],
            "Peak advance reliance (91 d)": sc["advance_reliance_peak_91d_multiple"].map(lambda z: f"{z:.2f}×"),
            "Peak contracted utilisation": sc["contracted_utilisation_peak_to_date_frac"].map(lambda z: f"{z:.2f}×"),
        }), key="risk_credit_rank")
        components.source_caption(["credit_scores"], {"model": "SYNTHETIC", "buyers": "SIM"},
                                  note=f"as of {_d(sc['as_of_date'].iloc[0], True)}; point-in-time features from the "
                                       "simulated book's own exposure files")
        contrib = [c_ for c_ in sc.columns if c_.startswith("logodds_contrib_")]
        if contrib:
            palette = [PALETTE["lme"], PALETTE["mcx"], PALETTE["fx"], PALETTE["freight"]]
            fig = go.Figure([go.Bar(y=sc["cp_id"], x=sc[c_], orientation="h",
                                    name=term_label.get(c_.removeprefix("logodds_contrib_"),
                                                        c_.removeprefix("logodds_contrib_")),
                                    marker_color=palette[i % len(palette)],
                                    hovertemplate="%{x:+.2f}<extra></extra>") for i, c_ in enumerate(contrib)])
            fig = charts.finish(fig, x_title="contribution to log-odds of default (vs the training mean)", height=300)
            fig.update_layout(barmode="relative", hovermode="closest")
            fig.update_yaxes(autorange="reversed")
            charts.show(fig, key="risk_credit_contrib")
            components.source_caption(["credit_scores", "credit_model_coefficients"],
                                      {"model": "SYNTHETIC", "buyers": "SIM"})

    st.subheader("The model: coefficients and odds ratios")
    if coef is None:
        components.missing_data(T("credit_model_coefficients"))
    else:
        cf = coef[coef["term"] != "intercept"]
        _table(pd.DataFrame({
            "Feature": coef["label"], "Per": coef["increment"].map(lambda z: f"{z:g}" if _ok(z) else "—"),
            "β (raw)": coef["beta_raw_fitted"].map(lambda z: f"{z:+.4f}"),
            "β (per 1 sd)": coef["beta_std_fitted"].map(lambda z: f"{z:+.3f}"),
            "Odds ratio, fitted": coef["odds_ratio_per_increment_fitted"].map(lambda z: f"{z:.3f}" if _ok(z) else "—"),
            "Bootstrap 95 %": [f"{a:.2f} to {b:.2f}" if _ok(a) else "—" for a, b in
                               zip(coef["odds_ratio_per_increment_boot_p2_5"],
                                   coef["odds_ratio_per_increment_boot_p97_5"])],
            "Odds ratio, generator (true)": coef["odds_ratio_per_increment_true"].map(
                lambda z: f"{z:.2f}" if _ok(z) else "—"),
            "Sign recovered": coef["sign_match"].map(_yes),
            "Bootstrap sign agreement": coef["boot_sign_match_share"].map(lambda z: _p(z, 1)),
        }), key="risk_credit_coef")
        fig = go.Figure([
            go.Scatter(x=cf["odds_ratio_per_increment_fitted"], y=cf["label"], mode="markers", name="fitted, bootstrap 95 %",
                       marker=dict(size=10, color=PALETTE["lme"]),
                       error_x=dict(type="data", symmetric=False,
                                    array=cf["odds_ratio_per_increment_boot_p97_5"] - cf["odds_ratio_per_increment_fitted"],
                                    arrayminus=cf["odds_ratio_per_increment_fitted"] - cf["odds_ratio_per_increment_boot_p2_5"],
                                    color=PALETTE["lme"])),
            go.Scatter(x=cf["odds_ratio_per_increment_true"], y=cf["label"], mode="markers",
                       name="synthetic generator (true)", marker=dict(symbol="x", size=10, color=PALETTE["loss"]))])
        fig.add_vline(x=1, line_color="#9aa1ab", line_width=1)
        fig = charts.finish(fig, x_title="odds ratio per increment (log scale)", height=300)
        fig.update_xaxes(type="log")
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(hovermode="closest")
        charts.show(fig, key="risk_credit_or")
        components.source_caption(["credit_model_coefficients"], {"training data": "SYNTHETIC"},
                                  note="'true' is the synthetic generator's registered odds ratio, which a real "
                                       "portfolio would not have")
        with st.expander("Fit to its own synthetic process (not evidence of predictive power)"):
            fm = data.credit_table("model_fit")
            if fm is None:
                components.missing_data(T("credit_model_fit"))
            else:
                wide = fm.pivot_table(index="metric", columns="split", values="value", aggfunc="first")
                order = [m_ for m_ in fm["metric"].drop_duplicates()]
                wide = wide.reindex(order).reset_index()
                shown_fit = pd.DataFrame({"Metric": wide["metric"]})
                for c_ in ("train", "test"):
                    if c_ in wide:
                        shown_fit[c_] = wide[c_].map(lambda z: f"{z:,.4g}" if _ok(z) else "—")
                _table(shown_fit, key="risk_credit_fit")
                components.source_caption(["credit_model_fit"], {"training data": "SYNTHETIC"},
                                          note=str(fm["note"].iloc[0]) if "note" in fm and len(fm) else None)

    st.subheader("The credit tracker")
    tcols = ["date", "cp_id", "cp_name", "role", "credit_limit_inr", "limit_basis", "receivable_inr", "contracted_inr",
             "advance_pending_inr", "credit_exposure_inr", "band_final", "recommended_limit_inr", "breach_hard",
             "flag_soft_utilisation", "flag_performance_advance_p14", "flag_past_due", "events"]
    tr = data.credit_table("tracker", usecols=tcols)
    if tr is None:
        components.missing_data(T("credit_tracker"))
    else:
        cps = tr[["cp_id", "cp_name", "role"]].drop_duplicates("cp_id").sort_values(["role", "cp_id"])
        names = dict(zip(cps["cp_id"], cps["cp_name"]))
        roles = dict(zip(cps["cp_id"], cps["role"]))
        options = cps["cp_id"].tolist()
        default = str(_param_value("mc_buyer_default_buyer_id") or "")
        if scores is not None and len(scores):
            default = str(scores.sort_values("rank_riskiest_first")["cp_id"].iloc[0])
        c1, c2 = st.columns([1, 1.3])
        cp = c1.selectbox("Counterparty (SIM)", options, index=options.index(default) if default in options else 0,
                          format_func=lambda c: f"{c} · {roles[c].lower()} · {names[c]}", key="risk_credit_cp")
        measures = {"credit_exposure_inr": "credit exposure (desk limit definition)", "receivable_inr": "receivable",
                    "contracted_inr": "contracted (memo)", "advance_pending_inr": "advances owed (performance)"}
        picked = c2.multiselect("Measures", list(measures), format_func=measures.get,
                                default=["credit_exposure_inr", "contracted_inr", "advance_pending_inr"],
                                key="risk_credit_measures")
        one = tr[tr["cp_id"] == cp].sort_values("date")
        soft = _param_value("credit_soft_utilisation_frac")
        flag_rows = {"breach_hard": "Hard breach (exposure > limit)",
                     "flag_soft_utilisation": "Soft line" + (f" (≥ {_p(soft, 0)} used)" if _ok(soft) else ""),
                     "flag_performance_advance_p14": "Performance (advances > P14 cap)",
                     "flag_past_due": "Past due"}
        components.kpi_row([Kpi(f"{label.split(' (')[0]} days", str(int(one[k].sum())),
                                "panel days flagged, Mar–Oct") for k, label in flag_rows.items()]
                           + [Kpi("Band (final), last day", str(one["band_final"].iloc[-1]) if len(one) else "—")])
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.74, 0.26], vertical_spacing=0.05)
        xs = pd.to_datetime(one["date"])
        for i, k in enumerate(picked):
            if one[k].notna().any():
                fig.add_trace(go.Scatter(x=xs, y=one[k] / M, mode="lines", name=measures[k],
                                         line=dict(width=2, color=[PALETTE["lme"], PALETTE["fx"], PALETTE["mcx"],
                                                                   PALETTE["freight"]][list(measures).index(k)]),
                                         hovertemplate="%{y:,.1f}<extra>" + measures[k] + "</extra>"), row=1, col=1)
        fig.add_trace(go.Scatter(x=xs, y=one["credit_limit_inr"] / M, mode="lines", name="credit limit",
                                 line=dict(color="#000000", width=1.4, dash="dash", shape="hv")), row=1, col=1)
        if one["recommended_limit_inr"].notna().any() and roles.get(cp) == "BUYER":
            fig.add_trace(go.Scatter(x=xs, y=one["recommended_limit_inr"] / M, mode="lines",
                                     name="model's recommended limit", line=dict(color=PALETTE["loss"], width=1.2,
                                                                                 dash="dot", shape="hv")), row=1, col=1)
        for k, label in flag_rows.items():
            on = one[one[k]]
            fig.add_trace(go.Scatter(x=pd.to_datetime(on["date"]), y=[label] * len(on), mode="markers",
                                     name=label, showlegend=False,
                                     marker=dict(symbol="line-ns-open", size=12, color=PALETTE["loss"]
                                                 if k in ("breach_hard", "flag_past_due") else PALETTE["mcx"]),
                                     hovertemplate="%{x|%d-%b}<extra>" + label + "</extra>"), row=2, col=1)
        if len(one):
            fig.add_trace(go.Scatter(x=[xs.iloc[0]] * len(flag_rows), y=list(flag_rows.values()), mode="markers",
                                     marker=dict(opacity=0), hoverinfo="skip", showlegend=False), row=2, col=1)
        fig.update_yaxes(type="category", categoryorder="array", categoryarray=list(flag_rows.values())[::-1],
                         row=2, col=1)
        charts.shade_window(fig, label=None)
        fig = charts.finish(fig, height=500, watermark=False)
        fig.add_annotation(text=SIM_LABEL, xref="paper", yref="paper", x=1, y=0.3, xanchor="right", yanchor="bottom",
                           xshift=-4, yshift=4, showarrow=False, font=dict(size=10, color=charts.MUTED),
                           bgcolor="rgba(255,255,255,0.7)")      # above the flag strip, not over its ticks
        fig.update_yaxes(title_text="₹ million", row=1, col=1)
        charts.show(fig, key="risk_credit_tracker")
        basis = str(one["limit_basis"].iloc[0]) if len(one) else ""
        components.source_caption(["credit_tracker"],
                                  {"counterparty": "SIM", "PD and band": "SYNTHETIC"}
                                  | ({"USD/INR on the supplier claims limit": _flags()["USD/INR"]}
                                     if roles.get(cp) == "SUPPLIER" else {}),
                                  note=f"limit basis: {basis}; flag strip below: one tick per panel day raised")
        with st.expander("Dated events for this counterparty"):
            ev = one[one["events"].notna()]
            _table(pd.DataFrame({"Date": ev["date"].map(lambda d: _d(d, True)), "Events": ev["events"]}),
                   key="risk_credit_events")
            components.source_caption(["credit_tracker"], ["SIM"])

    st.subheader("Band → limit policy")
    bands = data.credit_table("band_policy")
    if bands is None:
        components.missing_data(T("credit_band_policy"))
    else:
        _table(pd.DataFrame({
            "Band": bands["band"],
            "Model PD, annual": [f"{_p(a, 0)} to {_p(b, 0)}" for a, b in zip(bands["pd_lower_frac"], bands["pd_upper_frac"])],
            "Max credit utilisation": bands["band_max_credit_utilisation_frac"].map(lambda z: _p(z, 0)),
            "Max advance reliance": bands["band_max_advance_reliance_multiple"].map(lambda z: f"{z:.1f}× limit"),
            "Limit multiplier": bands["band_limit_multiplier"].map(lambda z: f"{z:.2f}×"),
            "Max credit days": bands["band_max_credit_days"].map(_n),
            "Review every (days)": bands["band_review_frequency_days"].map(_n),
            "Limit action": bands["limit_action"]}), key="risk_credit_bands")
        components.source_caption(["credit_band_policy"],
                                  {"band cut-offs and caps": data.param_flag("credit_soft_utilisation_frac")
                                   or "ASSUMPTION"}, note="bands are absolute PD cut-offs, so the assumed population "
                                                          "default rate moves bands, not the ranking")
    with st.expander("Would the band policy have objected? Each sale booking, checked the day before it was signed"):
        bk = data.credit_table("tracker_bookings")
        if bk is None:
            components.missing_data(T("credit_tracker_bookings"))
        else:
            outside = int((bk["band_policy_verdict"] == "OUTSIDE_BAND_POLICY").sum())
            st.markdown(f"**{outside} of {len(bk)} sale bookings** were outside the band policy on the previous close.")
            _table(pd.DataFrame({
                "Contract date": bk["contract_date"].map(lambda d: _d(d, True)), "Ticket": bk["trade_id"],
                "Buyer (SIM)": bk["cp_id"], "Invoice": bk["invoice_value_inr"].map(_m),
                "Advance reliance": bk["advance_reliance_multiple"].map(lambda z: f"{z:.2f}×"),
                "Band, previous close": bk["band_final_prev_close"], "Verdict": bk["band_policy_verdict"],
                "Why": bk["band_policy_reasons"].fillna("")}), key="risk_credit_bookings")
            components.source_caption(["credit_tracker_bookings"], {"bookings": "SIM", "bands": "SYNTHETIC"})

    components.what_it_tells(DOC50)

# ================================================================================================ 4.5 liquidity & margin
with tab_liq:
    ls = _summary("margin_liquidity_summary", "book")
    lf = _summary("margin_liquidity_summary", "facility")
    windows = data.margin_liquidity("windows")
    bank_flag = data.param_flag("liq_fb_wc_limit_inr") or "ASSUMPTION"
    if ls is not None and ls.has("funding_need_total_inr_max", "days_fb_limit_breach", "days_buffer_breach",
                                 "lc_outstanding_inr_max", "days_lc_limit_breach", "mcx_im_inr_max"):
        components.kpi_row([
            Kpi("Peak funding need", _m(ls.f("funding_need_total_inr_max")), _on(ls.note("funding_need_total_inr_max"))),
            Kpi("Days over the WC line", _n(ls.f("days_fb_limit_breach")), ls.note("days_fb_limit_breach")),
            Kpi("Buffer-breach days", _n(ls.f("days_buffer_breach")), ls.note("days_buffer_breach")),
            Kpi("Peak LC outstanding", _m(ls.f("lc_outstanding_inr_max")),
                f"{_on(ls.note('lc_outstanding_inr_max'))}; {_n(ls.f('days_lc_limit_breach'))} days over the LC line"),
            Kpi("Peak MCX initial margin", _m(ls.f("mcx_im_inr_max")), _on(ls.note("mcx_im_inr_max"))),
        ])
        components.source_caption(["margin_liquidity_summary"], {"bank lines and buffer": bank_flag,
                                                                  "MCX margin (proxy prices)": "PROXY"})
    else:
        components.available(T("margin_liquidity_summary"))

    ml = data.margin_liquidity(usecols=[
        "date", "funding_need_total_inr", "fb_limit_inr", "min_cash_buffer_inr", "flag_buffer_breach",
        "flag_fb_limit_breach", "lc_outstanding_inr", "memo_lc_outstanding_ex_tolerance_inr", "lc_limit_inr",
        "flag_lc_limit_breach", "mcx_im_inr", "mcx_im_stress_015_inr", "cum_vm_inr", "margin_cash_deployed_inr",
        "mar_99_stressed_im_inr"])
    st.subheader("Funding need against the bank lines")
    if ml is None:
        components.missing_data(T("margin_liquidity"))
    else:
        c1, c2 = st.columns([1.4, 1])
        line = c1.radio("Line", ["fb", "lc"], horizontal=True, key="risk_liq_line",
                        format_func={"fb": "fund-based working-capital line", "lc": "non-fund LC line"}.get)
        also = c2.toggle("Also shade the worst margin fortnight", value=False, key="risk_liq_margin_fn")
        x = pd.to_datetime(ml["date"])
        fig = go.Figure()
        if line == "fb":
            fig.add_trace(go.Scatter(x=x, y=ml["funding_need_total_inr"] / M, name="funding need", mode="lines",
                                     line=dict(color=PALETTE["lme"], width=2)))
            fig.add_trace(go.Scatter(x=x, y=ml["fb_limit_inr"] / M, name="working-capital line", mode="lines",
                                     line=dict(color="#000000", width=1.4, dash="dash")))
            fig.add_trace(go.Scatter(x=x, y=(ml["fb_limit_inr"] - ml["min_cash_buffer_inr"]) / M,
                                     name="line less the undrawn buffer", mode="lines",
                                     line=dict(color=PALETTE["mcx"], width=1.2, dash="dot")))
            for flag, name, sym, col in (("flag_buffer_breach", "buffer-breach day", "circle-open", PALETTE["mcx"]),
                                         ("flag_fb_limit_breach", "day over the line", "x", PALETTE["loss"])):
                on = ml[ml[flag]]
                fig.add_trace(go.Scatter(x=pd.to_datetime(on["date"]), y=on["funding_need_total_inr"] / M, mode="markers",
                                         name=f"{name} ({len(on)})", marker=dict(symbol=sym, size=8, color=col)))
        else:
            fig.add_trace(go.Scatter(x=x, y=ml["lc_outstanding_inr"] / M, name="LC outstanding, face + tolerance",
                                     mode="lines", line=dict(color=PALETTE["lme"], width=2)))
            fig.add_trace(go.Scatter(x=x, y=ml["memo_lc_outstanding_ex_tolerance_inr"] / M,
                                     name="memo: without the tolerance", mode="lines",
                                     line=dict(color=PALETTE["lme"], width=1.2, dash="dot")))
            fig.add_trace(go.Scatter(x=x, y=ml["lc_limit_inr"] / M, name="LC line", mode="lines",
                                     line=dict(color="#000000", width=1.4, dash="dash")))
            on = ml[ml["flag_lc_limit_breach"]]
            fig.add_trace(go.Scatter(x=pd.to_datetime(on["date"]), y=on["lc_outstanding_inr"] / M, mode="markers",
                                     name=f"day over the LC line ({len(on)})",
                                     marker=dict(symbol="x", size=8, color=PALETTE["loss"])))
        _shade_fortnights(fig, windows, {"CRASH_FORTNIGHT"} | ({"MARGIN_FORTNIGHT"} if also else set()))
        charts.shade_window(fig)
        charts.show(charts.finish(fig, y_title="₹ million", height=420), key="risk_liq_funding")
        components.source_caption(["margin_liquidity"] + (["margin_liquidity_windows"] if windows is not None else []),
                                  {"line sizes and buffer": bank_flag, "USD/INR on LCs": _flags()["USD/INR"]},
                                  note="funding need = settled cash plus accrued interest drawn on the line; the "
                                       "fortnights are reporting-only windows drawn after the fact")

        st.subheader("Margin through the window")
        mseries = {"mcx_im_inr": "initial margin posted", "mcx_im_stress_015_inr": "initial margin at a stressed 15 %",
                   "cum_vm_inr": "cumulative variation margin (+ = received)",
                   "margin_cash_deployed_inr": "margin cash deployed (+ = paid out)",
                   "mar_99_stressed_im_inr": "99 % 10-day margin-at-risk (IM at 15 %)"}
        msel = st.multiselect("Series", list(mseries), format_func=mseries.get, key="risk_liq_margin_series",
                              default=["mcx_im_inr", "margin_cash_deployed_inr", "mar_99_stressed_im_inr"])
        mcol = [PALETTE["lme"], PALETTE["neutral"], PALETTE["fx"], PALETTE["mcx"], PALETTE["loss"]]
        fig = go.Figure()
        for k in msel:
            fig.add_trace(go.Scatter(x=x, y=ml[k] / M, name=mseries[k], mode="lines",
                                     line=dict(color=mcol[list(mseries).index(k)], width=1.8,
                                               dash="dot" if k in ("mcx_im_stress_015_inr",) else None)))
        fig.add_trace(go.Scatter(x=x, y=ml["min_cash_buffer_inr"] / M, name="undrawn buffer", mode="lines",
                                 line=dict(color="#000000", width=1, dash="dash")))
        _shade_fortnights(fig, windows, {"CRASH_FORTNIGHT", "MARGIN_FORTNIGHT"})
        charts.shade_window(fig, label=None)
        charts.show(charts.finish(fig, y_title="₹ million", height=380), key="risk_liq_margin")
        components.source_caption(["margin_liquidity", "mcx_variation_margin"],
                                  {"MCX prices": _flags()["MCX (unit beta to LME × USD/INR)"],
                                   "margin rates": data.param_flag("mcx_al_margin_used_frac") or "ASSUMPTION"},
                                  note="initial margin is a stock; VM and margin cash are cumulative flows")

    st.subheader("Read the breach with its two conventions")
    grid = data.margin_liquidity("limit_grid")
    fac = _summary("margin_liquidity_facility")
    lots = data.margin_liquidity("lc_lots", usecols=["lc_amount_tolerance_frac"])
    if not components.available(T("margin_liquidity_limit_grid"), T("margin_liquidity_facility"),
                                T("margin_liquidity_summary")):
        pass
    else:
        step = _param_value("liq_facility_rounding_inr")
        step_txt = f"₹{float(step) / 1e7:,.0f} crore" if _ok(step) else "a round"
        fb = grid[grid["facility"] == "FUND_BASED_WC"].sort_values("limit_inr")
        lcg = grid[grid["facility"] == "NON_FUND_LC"].sort_values("limit_inr")
        reg = fb[fb["registered"]]
        c1, c2 = st.columns(2, gap="large")
        with c1, st.container(border=True):
            st.markdown("**1. The line is sanctioned on the plan's *average* balance**")
            if len(reg) and fac.has("plan_avg_funded_balance_inr", "plan_throughput_mt_pa", "fb_limit_rule_inr"):
                r = reg.iloc[0]
                nxt = fb[fb["limit_inr"] > r["limit_inr"]].head(1)
                nlc = lcg[lcg["limit_inr"].isin(nxt["limit_inr"])]
                mins = grid[grid["facility"].str.endswith("_MIN_NO_BREACH")].set_index("facility")["limit_inr"]
                text = (f"Sized before the window on the {_d(fac.s('plan_value_date'), True)} plan "
                        f"({_n(fac.f('plan_throughput_mt_pa'))} MT a year): average funded balance "
                        f"{_m(fac.f('plan_avg_funded_balance_inr'))}, rounded up to the next {step_txt} step = "
                        f"{_m(fac.f('fb_limit_rule_inr'), 0)}. On it the book is over the line on "
                        f"**{int(r['days_limit_breach'])} days** and breaks the {_m(r['buffer_inr'], 0)} buffer on "
                        f"{int(r['days_buffer_breach'])}.")
                if len(nxt):
                    n0 = nxt.iloc[0]
                    text += (f" **One step higher ({_m(n0['limit_inr'], 0)}): {int(n0['days_limit_breach'])} days over "
                             f"the line**, {int(n0['days_buffer_breach'])} buffer days"
                             + (f"; the LC line at that size is still over on {int(nlc.iloc[0]['days_limit_breach'])} "
                                "days" if len(nlc) else "") + ".")
                if "FUND_BASED_WC_MIN_NO_BREACH" in mins:
                    text += f" A no-breach line would have been {_m(mins['FUND_BASED_WC_MIN_NO_BREACH'], 0)} with its buffer."
                st.markdown(docs_text.escape_streamlit(text))
            else:
                st.info("Not computed in this copy: no registered line in the grid.", icon=":material/info:")
            components.source_caption(["margin_liquidity_facility", "margin_liquidity_limit_grid"],
                                      {"plan and rounding convention": bank_flag})
        with c2, st.container(border=True):
            st.markdown("**2. LC use is counted at planned face *plus* the amount tolerance**")
            if ls is not None and ls.has("lc_outstanding_inr_max", "days_lc_limit_breach",
                                         "memo_lc_outstanding_ex_tolerance_inr_max",
                                         "memo_days_lc_limit_breach_ex_tolerance"):
                tol = "" if lots is None or lots.empty else (
                    f" ({_p(lots['lc_amount_tolerance_frac'].min(), 0)}–{_p(lots['lc_amount_tolerance_frac'].max(), 0)})")
                memo_days = int(ls.f("memo_days_lc_limit_breach_ex_tolerance"))
                lc_lim = _m(lf.f("lc_limit_inr"), 0) if lf is not None and lf.has("lc_limit_inr") else "the line"
                st.markdown(docs_text.escape_streamlit(
                    f"Each credit is counted at its planned face plus the LC amount tolerance{tol} until its principal "
                    f"is paid, which overstates an accepted usance bill. On that conservative reading LCs peak at "
                    f"{_m(ls.f('lc_outstanding_inr_max'))} ({_on(ls.note('lc_outstanding_inr_max'))}), "
                    f"**{int(ls.f('days_lc_limit_breach'))} days** over the {lc_lim} line. **Without the tolerance "
                    f"(memo): {_m(ls.f('memo_lc_outstanding_ex_tolerance_inr_max'))}, {memo_days} days over**"
                    + (" — still breached." if memo_days > 0 else " — no breach.")))
            else:
                st.info("Not computed in this copy: the LC memo metrics are missing.", icon=":material/info:")
            components.source_caption(["margin_liquidity_summary"] + (["margin_liquidity_lc_lots"] if lots is not None
                                                                       else []),
                                      {"LC tolerance and tenor": data.param_flag("liq_nfb_lc_limit_inr") or "ASSUMPTION",
                                       "USD/INR": _flags()["USD/INR"]})

        st.markdown("**Try another line size**")
        sizes = sorted(set(fb["limit_inr"]) | set(lcg["limit_inr"]))
        reg_size = float(reg.iloc[0]["limit_inr"]) if len(reg) else sizes[0]
        size = st.select_slider("Line size (both lines)", sizes, value=reg_size, format_func=lambda z: _m(z, 0),
                                key="risk_liq_grid")
        f_row = fb[fb["limit_inr"] == size]
        l_row = lcg[lcg["limit_inr"] == size]
        kp_ = []
        if len(f_row):
            f0 = f_row.iloc[0]
            kp_ += [Kpi("WC line: days over the line", _n(f0["days_limit_breach"]),
                        f"{_d(f0['first_limit_breach'])} → {_d(f0['last_limit_breach'], True)}"
                        if _ok(f0["first_limit_breach"]) else "none"),
                    Kpi("WC line: buffer-breach days", _n(f0["days_buffer_breach"]), f"buffer {_m(f0['buffer_inr'], 1)}"),
                    Kpi("WC line: worst excess", _m(f0["worst_shortfall_vs_limit_inr"]))]
        if len(l_row):
            l0 = l_row.iloc[0]
            kp_ += [Kpi("LC line: days over the line", _n(l0["days_limit_breach"]),
                        f"{_d(l0['first_limit_breach'])} → {_d(l0['last_limit_breach'], True)}"
                        if _ok(l0["first_limit_breach"]) else "none"),
                    Kpi("LC line: worst excess", _m(l0["worst_shortfall_vs_limit_inr"]))]
        if kp_:
            components.kpi_row(kp_)
        components.source_caption(["margin_liquidity_limit_grid"], {"line sizes": bank_flag},
                                  note=f"registered size {_m(reg_size, 0)}; the grid re-runs the same book against "
                                       "each size, it does not re-plan the book")

    st.subheader("Stress: LME against the hedges in a fortnight")
    fn = data.margin_liquidity("fortnight")
    if fn is None:
        components.missing_data(T("margin_liquidity_fortnight"))
    else:
        wins = fn["window"].drop_duplicates().tolist()
        c1, c2 = st.columns(2)
        win = c1.radio("Fortnight", wins, horizontal=True, key="risk_liq_fortnight",
                       format_func=lambda w: FORTNIGHTS.get(w, (w,))[0])
        measure = c2.radio("Show", ["headroom", "vm", "lme"], horizontal=True, key="risk_liq_stress_measure",
                           format_func={"headroom": "headroom", "vm": "cumulative VM", "lme": "LME path"}.get)
        wm = _summary("margin_liquidity_summary", win)
        if wm is not None and wm.has("stress_move_frac", "extra_margin_cash_out_stressed_im_inr_max",
                                     "headroom_actual_inr_min", "headroom_stressed_im_inr_min",
                                     "days_buffer_breach_stressed_im", "days_fb_limit_breach_stressed_im",
                                     "lme_cash_return_frac"):
            direction = wm.s("stress_direction").replace("_", " ").lower() if wm.has("stress_direction") else ""
            fortnight_kpis = [
                Kpi("LME cash, actual", _p(wm.f("lme_cash_return_frac"), 1, sign=True),
                    f"{_d(wm.s('window_start'))} → {_d(wm.s('window_end'), True)}" if wm.has("window_start") else None),
                Kpi("Stress move, 99 % 10-day", _p(wm.f("stress_move_frac"), 1, sign=True),
                    f"{direction}; {wm.note('stress_move_logret')}"),
                Kpi("Extra margin cash out", _m(wm.f("extra_margin_cash_out_stressed_im_inr_max")),
                    f"with IM re-struck at 15 %; {_m(wm.f('extra_margin_cash_out_inr_max'))} at 10 %"
                    if wm.has("extra_margin_cash_out_inr_max") else "with IM re-struck at 15 %"),
                Kpi("Worst headroom, actual", _m(wm.f("headroom_actual_inr_min"), sign=True),
                    _on(wm.note("headroom_actual_inr_min"))),
                Kpi("Worst headroom, stressed", _m(wm.f("headroom_stressed_im_inr_min"), sign=True),
                    f"IM re-struck at 15 %; {_on(wm.note('headroom_stressed_im_inr_min'))}"),
                Kpi("Stressed breach days, buffer / line", f"{_n(wm.f('days_buffer_breach_stressed_im'))} / "
                                                           f"{_n(wm.f('days_fb_limit_breach_stressed_im'))}",
                    "undrawn-buffer breach days / days over the working-capital line, IM re-struck at 15 %"),
            ]
            components.kpi_row(fortnight_kpis[:3])
            components.kpi_row(fortnight_kpis[3:])
        f_ = fn[fn["window"] == win].sort_values("date")
        xs = pd.to_datetime(f_["date"])
        series_map = {
            "headroom": ({"headroom_actual_inr": "actual", "headroom_stressed_inr": "stressed (IM at 10 %)",
                          "headroom_stressed_im_inr": "stressed, IM re-struck at 15 %"}, "headroom, ₹ million", M),
            "vm": ({"cum_vm_actual_inr": "actual", "cum_vm_stressed_inr": "stressed"},
                   "cumulative variation margin, ₹ million", M),
            "lme": ({"lme_cash_actual_usd_t": "actual", "lme_cash_stressed_usd_t": "stressed"}, "LME cash, USD/t", 1.0),
        }
        smap, ytitle, scale = series_map[measure]
        fig = go.Figure()
        for (k, name), col in zip(smap.items(), [PALETTE["lme"], PALETTE["mcx"], PALETTE["loss"]]):
            fig.add_trace(go.Scatter(x=xs, y=f_[k] / scale, name=name, mode="lines+markers",
                                     line=dict(color=col, width=2, dash=None if name == "actual" else "dash"),
                                     marker=dict(size=5)))
        if measure == "headroom":
            fig.add_hline(y=0, line_color="#000000", line_width=1)
        charts.show(charts.finish(fig, y_title=ytitle, height=340), key="risk_liq_stress_chart")
        if wm is not None:
            bits = []
            if wm.has("memo_physical_mtm_gain_end_inr"):
                bits.append(f"memo: the cargo gains about {_m(wm.f('memo_physical_mtm_gain_end_inr'))} of mark from the "
                            "same move, a mark and not cash")
            if wm.has("sens_garch_stress_move_frac", "sens_garch_extra_margin_cash_out_stressed_im_inr_max",
                      "sens_garch_days_buffer_breach_stressed_im", "sens_garch_days_fb_limit_breach_stressed_im"):
                bits.append(f"sensitivity on the GARCH reading alone ({_p(wm.f('sens_garch_stress_move_frac'), 1, True)}): "
                            f"{_m(wm.f('sens_garch_extra_margin_cash_out_stressed_im_inr_max'))} extra cash, "
                            f"{_n(wm.f('sens_garch_days_buffer_breach_stressed_im'))} buffer / "
                            f"{_n(wm.f('sens_garch_days_fb_limit_breach_stressed_im'))} line days")
            if bits:
                st.markdown(docs_text.escape_streamlit("; ".join(b[0].upper() + b[1:] if i == 0 else b
                                                                 for i, b in enumerate(bits)) + "."))
        components.source_caption(["margin_liquidity_fortnight", "margin_liquidity_summary"],
                                  {"stressed path (LME against the hedge, not what happened)": "HYPOTHETICAL",
                                   "MCX margin": "PROXY"},
                                  note="the stress re-marks the MCX lines on a counterfactual LME path at the 99 % "
                                       "10-day move known at the start close; contracts, exits, FX and commercial "
                                       "cash are held at what happened")

    components.what_it_tells(DOC51)

# ================================================================================================ 4.6 memo
with tab_memo:
    st.markdown("The one-page memo turns the findings into limits for the next book. It opens with the book P&L, which "
                "this app shows only with its band:")
    components.pnl_headline(facts)
    d1, d2 = st.columns(2)
    with d1:
        components.download_button(MEMO_PDF, "Risk policy memo (PDF)", key="risk_memo_pdf")
    with d2:
        components.download_button(MEMO_MD, "Risk policy memo (Markdown)", key="risk_memo_md")
    memo = data.doc_markdown(MEMO_MD)
    if memo is None:
        components.missing_data(MEMO_MD)
    else:
        demoted = re.sub(r"^(#{1,4})\s", lambda m_: "#" * (len(m_.group(1)) + 2) + " ", memo, flags=re.M)
        with st.container(border=True):
            st.markdown(docs_text.for_streamlit(demoted, MEMO_MD))
        components.source_caption([MEMO_MD], {"counterparties and desk": "SIM", "credit bands": "SYNTHETIC"},
                                  note="rendered as generated by desk.risk.policy_memo; the PDF is the same memo")

    st.subheader("Every limit, checked against the 2022 book")
    pl = data.margin_liquidity("policy_limits", usecols=None)
    if pl is None:
        components.missing_data(T("margin_liquidity_policy_limits"))
    else:
        areas = pl["area"].drop_duplicates().tolist()
        chosen = st.multiselect("Areas", areas, default=areas, key="risk_memo_areas")
        only = st.toggle("Only limits the book breached", value=False, key="risk_memo_breached")
        shown = pl[pl["area"].isin(chosen) & ((pl["book_verdict"] != "WITHIN") if only else True)]

        def _limit_value(v, unit) -> str:
            if not _ok(v):
                return "—"
            try:
                z = float(v)
            except (TypeError, ValueError):
                return f"{v} {unit}" if _ok(unit) else str(v)
            if unit == "inr":
                return _m(z, 0)
            if unit == "usd":
                return f"USD {z / M:,.1f} m"
            if unit == "frac":
                return _p(z, 0)
            return f"{num(z, 0 if z == int(z) else 2)} {str(unit).replace('_', ' ')}"

        def _flag_of(keys) -> str:
            got = {data.param_flag(k.strip()) for k in str(keys).split(";")} - {None}
            return ", ".join(sorted(got)) if got else "—"

        _table(pd.DataFrame({
            "Limit": shown["limit_id"], "Area": shown["area"],
            "Limit value": [_limit_value(v_, u_) for v_, u_ in zip(shown["limit_value"], shown["unit"])],
            "Register flag": shown["param_key"].map(_flag_of), "Evidence": shown["evidence"],
            "Days checked": shown["days_checked"].map(_n), "Days breached": shown["days_breached"].map(_n),
            "First → last breach": [f"{_d(a)} → {_d(b, True)}" if _ok(a) else "—" for a, b in
                                    zip(shown["first_breach"], shown["last_breach"])],
            "Verdict": shown["book_verdict"], "Remediation": shown["remediation"].fillna("")}),
            key="risk_memo_limits")
        n_b = int((pl["book_verdict"] != "WITHIN").sum())
        components.source_caption(["margin_liquidity_policy_limits"],
                                  {"limits": "ASSUMPTION", "book": "SIM"},
                                  note=f"{n_b} of {len(pl)} limits breached by the book; limits set with the 2022 "
                                       "book in view are illustration, not evidence")

    components.what_it_tells(DOC51, heading="The risk policy memo (Table 6 row 4.6)")
