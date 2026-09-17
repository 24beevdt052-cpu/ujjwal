"""P&L & attribution: the daily MTM result, its split into buckets, its sensitivity band and the three adverse events
(MASTER_SPEC Table 5, rows 3.1–3.6).

Sources, all Phase 3 outputs read as published: `attribution_daily.csv` (BOOK rows and per-ticket rows in one table;
the page never adds the two together), `book_exposures_daily.csv` (the unrealised mark), `pnl_sensitivity_*.csv`,
`adverse_event_*.csv`, `mcx_variation_margin.csv`, `mcx_basis_risk.csv`, `buyer_credit_exposure_daily.csv`. The headline
book P&L appears only through `components.pnl_headline`; every other book-level total on the page sits under it and
names its band. Aggregation here is summing a published daily column by period or by ticket.

Page-local helpers (not in app/lib): `_event_metrics` reads an adverse_event_<n>.csv metric/value/note table,
`_rows_for` selects BOOK or one ticket's rows, `_period_key` buckets dates by day/week/month, `_two_axis` adds a
right-hand axis to a figure.
"""

import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.lib import charts, components, data, docs_text  # noqa: E402
from app.lib.components import Kpi, day, inr_m, num, pct  # noqa: E402
from desk import HORIZON_END, WINDOW_END  # noqa: E402
from desk.reporting.style import PALETTE, PNL_BUCKETS  # noqa: E402

M = 1e6
WE, HZ = WINDOW_END.isoformat(), HORIZON_END.isoformat()
ATT = data.table_rel("attribution_daily")
EXPO = data.table_rel("book_exposures_daily")
BOOK_CSV = data.table_rel("trade_book")
SENS = data.table_rel("pnl_sensitivity_summary")
PRICING = data.table_rel("pnl_sensitivity_pricing")
ROBUST = components.BAND_TABLE
E1, E1D = data.table_rel("adverse_event_1_lme_crash"), data.table_rel("adverse_event_1_lme_crash_daily")
E2, E2D = data.table_rel("adverse_event_2_usdinr"), data.table_rel("adverse_event_2_usdinr_daily")
E3 = data.table_rel("adverse_event_3_logistics_credit")
E3F = data.table_rel("adverse_event_3_freight_stress_hypothetical")
VM = data.table_rel("mcx_variation_margin")
BASIS = data.table_rel("mcx_basis_risk")
BUYERS = data.table_rel("buyer_credit_exposure_daily")
DOC30, DOC31 = f"{data.DOCS}/30_mtm_attribution.md", f"{data.DOCS}/31_adverse_events.md"
ANCHOR = "domestic_anchor_premium_inr_t"


# ------------------------------------------------------------------------------------------------ helpers
class EventMetrics:
    """adverse_event_<n>.csv as metric -> value (float where numeric) and metric -> note."""

    def __init__(self, df: pd.DataFrame):
        self.raw = dict(zip(df["metric"], df["value"]))
        self.notes = {m: n for m, n in zip(df["metric"], df["note"]) if isinstance(n, str) and n.strip()}

    def f(self, key: str) -> float:
        return float(self.raw[key])

    def s(self, key: str) -> str:
        return str(self.raw[key])

    def note(self, key: str) -> str:
        return self.notes.get(key, "")

    def has(self, *keys: str) -> bool:
        return all(k in self.raw for k in keys)


def _event_metrics(rel: str) -> EventMetrics | None:
    df = data.read_csv(rel, dtype_str=True)
    return None if df is None else EventMetrics(df)


def _rows_for(att: pd.DataFrame, who: str) -> pd.DataFrame:
    """BOOK rows or one ticket's rows, never both (the BOOK rows already are the sum of the tickets)."""
    return att[att["trade_id"] == who].sort_values("date")


def _period_key(dates: pd.Series, agg: str) -> pd.Series:
    d = pd.to_datetime(dates)
    if agg == "Weekly":
        return d.dt.to_period("W-FRI").dt.end_time.dt.normalize()
    if agg == "Monthly":
        return d.dt.to_period("M").dt.to_timestamp()
    return d


def _two_axis(fig: go.Figure, title: str) -> None:
    fig.update_layout(yaxis2=dict(title=dict(text=title), overlaying="y", side="right", showgrid=False, zeroline=False,
                                  automargin=True))


def _ends(fig: go.Figure) -> None:
    charts.mark_events(fig, [(WINDOW_END, "window end"), (HORIZON_END, "horizon")], color=charts.MUTED)


def _wrap(label: str, width: int = 15) -> str:
    return "<br>".join(textwrap.wrap(label, width))


def _bucket_steps(totals: pd.Series, residual: float) -> tuple[list[tuple[str, float]], list[str]]:
    steps = [(_wrap(charts.bucket_label(b)), float(totals[b]) / M) for b in PNL_BUCKETS]
    steps.append(("Residual", residual / M))
    colors = [charts.bucket_color(b) for b in PNL_BUCKETS] + [PALETTE["neutral"]]
    return steps, colors


# ------------------------------------------------------------------------------------------------ header
spec = components.PAGE["pnl"]
components.sim_banner()
components.page_header(spec.title, spec.blurb, spec.spec_rows)

facts = data.headline_facts()
t = facts.t
if components.headline_band_ok(facts) and facts.has("horizon_end", "nd_share"):
    st.markdown(
        f"**The takeaway:** {t('nd_share')} of the book's P&L to the {t('horizon_end')} horizon (below, with its band) "
        f"is deal margin at contract dates — the desk's own sale-pricing rule — and the one assumption behind that "
        f"rule, `{ANCHOR}`, is what the band re-prices. The hedges did their job in the crash; the sign of the result "
        "rides on that assumption.")
components.pnl_headline(facts)

att = data.attribution_daily()
flags = data.series_flags()
anchor_flag = data.param_flag(ANCHOR) or "ASSUMPTION"

tab_eq, tab_rob, tab_tkt, tab_time, tab_ev, tab_basis = st.tabs(
    ["Equity curve", "Is it sign-robust?", "Per ticket", "Buckets over time", "Adverse events", "MCX basis risk"])

# ------------------------------------------------------------------------------------------------ equity curve (3.1, 3.3)
with tab_eq:
    st.subheader("Book equity curve")
    if att is None:
        components.missing_data(ATT)
    else:
        book, _ = data.split_book(att)
        df = book[["date", "cum_pnl_inr"]].assign(cum_m=lambda d: d["cum_pnl_inr"] / M)
        fig = charts.line_chart(df, "date", {"cum_m": "Cumulative book P&L"}, y_title="₹ million",
                                events=data.event_markers(), height=440, colors={"cum_m": PALETTE["pnl"]})
        _ends(fig)
        drawn = []
        summ = data.pnl_sensitivity("summary")
        if summ is not None:
            fam = summ[summ["family"] == "anchor_premium"]
            if not fam.empty:
                lo, hi = fam["cum_pnl_window_end_inr"].min(), fam["cum_pnl_window_end_inr"].max()
                charts.band_marker(fig, WINDOW_END, lo / M, hi / M, label=f"anchor-premium band at {day(WE)}",
                                   text_lo=inr_m(lo, sign=True), text_hi=inr_m(hi, sign=True))
                drawn.append(SENS)
        if {"band_lo", "band_hi", "book_pnl"} <= facts.num.keys() and "band_sign_robust" in facts.flags:
            charts.band_marker(fig, HORIZON_END, facts.num["band_lo"] / M, facts.num["band_hi"] / M,
                               point=facts.num["book_pnl"] / M, label=f"anchor-premium band at {t('horizon_end')}",
                               text_lo=t("band_lo"), text_hi=t("band_hi"),
                               text_point=f"headline {t('book_pnl')}"
                                          + ("" if facts.flags["band_sign_robust"] else " · not sign-robust"))
            drawn.append(ROBUST)
        charts.show(fig, key="pnl_equity")
        components.source_caption(
            [ATT, *drawn], {"anchor premium": anchor_flag},
            note="red bars: the same book re-priced across the registered anchor-premium grid, at the window end and at "
                 "the horizon" if drawn else "the anchor-premium band could not be drawn in this copy")

        st.markdown("**Realised cash versus the unrealised mark**")
        expo = data.book_exposures_daily(["date", "scope", "mtm_inr", "cum_pnl_inr"])
        if expo is None:
            components.missing_data(EXPO)
        else:
            b = expo[expo["scope"] == "book"].sort_values("date")
            split = pd.DataFrame({"date": b["date"], "cum_m": b["cum_pnl_inr"] / M,
                                  "real_m": (b["cum_pnl_inr"] - b["mtm_inr"]) / M, "unreal_m": b["mtm_inr"] / M})
            fig = charts.line_chart(split, "date", {"cum_m": "Cumulative P&L", "real_m": "Realised P&L + funding",
                                                    "unreal_m": "Unrealised mark"},
                                    colors={"cum_m": PALETTE["pnl"], "real_m": PALETTE["gain"],
                                            "unreal_m": PALETTE["mcx"]},
                                    dashes={"real_m": "dash", "unreal_m": "dot"}, y_title="₹ million", height=380)
            _ends(fig)
            charts.show(fig, key="pnl_realised_split")
            components.source_caption(
                [EXPO], note="realised P&L + funding = cumulative P&L − unrealised mark (the engine's identity). While "
                             "cargo is bought and unsold, cash paid out sits in 'realised' and the cargo's replacement "
                             "value in the mark; they swing by about a billion rupees and net to the thin line")

# ------------------------------------------------------------------------------------------------ sign robustness (3.3)
with tab_rob:
    st.subheader("The band that decides the sign")
    summ = data.pnl_sensitivity("summary")
    robust = data.pnl_sensitivity("sign_robustness")
    if robust is None or summ is None:
        for rel, df_ in ((ROBUST, robust), (SENS, summ)):
            if df_ is None:
                components.missing_data(rel)
    else:
        ra = robust[robust["family"] == "anchor_premium"]
        fam = summ[summ["family"] == "anchor_premium"].drop_duplicates("param_value").sort_values("param_value")
        if not ra.empty and not fam.empty:
            ra = ra.iloc[0]
            be, base_x = float(ra["breakeven_value"]), float(ra["base_value"])
            lo, hi = float(ra["pnl_min_inr"]) / M, float(ra["pnl_max_inr"]) / M
            ys = fam["cum_pnl_horizon_inr"] / M
            fig = go.Figure()
            fig.add_hrect(y0=lo, y1=hi, fillcolor=PALETTE["loss"], opacity=0.10, line_width=0, layer="below")
            fig.add_hrect(y0=lo, y1=0, fillcolor=PALETTE["loss"], opacity=0.10, line_width=0, layer="below")
            fig.add_vrect(x0=float(ra["band_min_value"]), x1=float(ra["band_max_value"]), fillcolor=PALETTE["band"],
                          opacity=0.45, line_width=0, layer="below")
            fig.add_hline(y=0, line_color="#262730", line_width=1.4)
            fig.add_trace(go.Scatter(
                x=fam["param_value"], y=ys, mode="lines+markers+text", name="book P&L, re-priced (horizon)",
                line=dict(color=PALETTE["pnl"], width=3),
                marker=dict(size=11, color=[PALETTE["loss"] if v < 0 else PALETTE["gain"] for v in ys],
                            line=dict(width=1.5, color="white")),
                text=[inr_m(v * M, sign=True) for v in ys], textfont=dict(size=12),
                textposition=["bottom right" if i == 0 else "top left" for i in range(len(ys))],
                hovertemplate="anchor premium %{x:,.0f} ₹/t: ₹%{y:,.1f} m<extra></extra>"))
            fig.add_trace(go.Scatter(
                x=[base_x], y=[float(ra["base_pnl_inr"]) / M], mode="markers", name=f"published book ({num(base_x)} ₹/t)",
                marker=dict(symbol="star", size=18, color=PALETTE["pnl"], line=dict(width=1, color="white")),
                hovertemplate="published book: ₹%{y:,.1f} m<extra></extra>"))
            inside = "inside" if bool(ra["breakeven_inside_band"]) else "outside"
            fig.add_vline(x=be, line_dash="dash", line_color=PALETTE["loss"], line_width=2)
            fig.add_annotation(x=be, y=hi, text=f"break-even {num(be)} ₹/t<br>({inside} the registered grid)",
                               showarrow=False, xanchor="left", yanchor="top", xshift=6,
                               font=dict(size=12, color=PALETTE["loss"]))
            charts.finish(fig, title=("Book P&L to the horizon across the registered anchor-premium grid: "
                                      f"<span style='color:{PALETTE['loss']}'><b>{inr_m(lo * M, sign=True)} to "
                                      f"{inr_m(hi * M, sign=True)}</b></span>"), height=460,
                          x_title=f"{ANCHOR}, ₹ per tonne", y_title="₹ million")
            fig.update_layout(hovermode="closest")
            charts.show(fig, key="pnl_anchor_band")
            verdict = "is sign-robust" if bool(ra["sign_robust_within_band"]) else "is NOT sign-robust"
            st.markdown(f"The headline **{verdict}** across this band: the whole engine re-run with each registered value "
                        f"gives {inr_m(lo * M, sign=True)} to {inr_m(hi * M, sign=True)}, and the book only makes money if "
                        f"the true 2022 premium was above {num(be)} ₹/t.")
            components.source_caption([ROBUST, SENS], {ANCHOR: anchor_flag, "every case": "SENSITIVITY"},
                                      note=f"verification {data.param_verify_status(ANCHOR) or 'unknown'}; shaded blue: the "
                                           "registered grid; shaded red: the P&L band, darker where it is a loss")

        rr = robust[robust["family"] != "ALL_REGISTERED_BANDS"].reset_index(drop=True)
        labels = [f"{f} · {k}" for f, k in zip(rr["family"], rr["param_key"])]
        mins, maxs = rr["pnl_min_inr"] / M, rr["pnl_max_inr"] / M
        fig = go.Figure(go.Bar(
            y=labels, x=maxs - mins, base=mins, orientation="h",
            marker_color=[PALETTE["neutral"] if bool(s) else PALETTE["loss"] for s in rr["sign_robust_within_band"]],
            customdata=[f"{inr_m(a * M, sign=True)} to {inr_m(b * M, sign=True)}" for a, b in zip(mins, maxs)],
            hovertemplate="%{y}: %{customdata}<extra></extra>"))
        for lab, a, b in zip(labels, mins, maxs):
            fig.add_annotation(x=b, y=lab, text=f"{inr_m(a * M, sign=True)} … {inr_m(b * M, sign=True)}", showarrow=False,
                               xanchor="left", xshift=6, font=dict(size=11))
        fig.add_vline(x=0, line_color="#262730", line_width=1.4)
        if not rr.empty:
            fig.add_vline(x=float(rr["base_pnl_inr"].iloc[0]) / M, line_dash="dot", line_color=PALETTE["pnl"],
                          annotation_text="published book", annotation_position="top")
        charts.finish(fig, title="Every registered band, one at a time (red: the sign flips inside the band)",
                      height=max(320, 44 * len(rr) + 120), x_title="book P&L to the horizon, ₹ million", legend=False)
        fig.update_yaxes(autorange="reversed", showgrid=False)
        fig.update_layout(hovermode="closest", margin=dict(r=150))
        charts.show(fig, key="pnl_band_ranges")
        components.source_caption([ROBUST], {"every band": "SENSITIVITY"},
                                  note="no case moves two bands at once; joint scenarios are not published")

        show = rr.assign(
            **{"P&L min ₹ m": rr["pnl_min_inr"] / M, "P&L max ₹ m": rr["pnl_max_inr"] / M,
               "base P&L ₹ m": rr["base_pnl_inr"] / M})
        st.dataframe(
            show[["family", "param_key", "flag", "n_cases", "band_min_value", "base_value", "band_max_value",
                  "P&L min ₹ m", "base P&L ₹ m", "P&L max ₹ m", "slope_inr_per_unit", "breakeven_value",
                  "breakeven_inside_band", "sign_robust_within_band", "label"]],
            hide_index=True, width="stretch", column_config={
                "P&L min ₹ m": st.column_config.NumberColumn(format="%.1f"),
                "P&L max ₹ m": st.column_config.NumberColumn(format="%.1f"),
                "base P&L ₹ m": st.column_config.NumberColumn(format="%.1f"),
                "slope_inr_per_unit": st.column_config.NumberColumn("slope ₹ per unit", format="localized"),
                "breakeven_value": st.column_config.NumberColumn("break-even", format="%.1f")})
        allb = robust[robust["family"] == "ALL_REGISTERED_BANDS"]
        if not allb.empty:
            a = allb.iloc[0]
            st.caption(f"All {int(a['n_cases'])} registered cases, one at a time: {inr_m(float(a['pnl_min_inr']), sign=True)} "
                       f"to {inr_m(float(a['pnl_max_inr']), sign=True)} · sign-robust: "
                       f"**{'yes' if bool(a['sign_robust_within_band']) else 'no'}**")
        components.source_caption([ROBUST], {"every row": "SENSITIVITY"})

        pricing = data.pnl_sensitivity("pricing")
        if pricing is None:
            components.missing_data(PRICING)
        else:
            st.markdown("**Which tickets carry the sensitivity**")
            fams = [f for f in dict.fromkeys(pricing["family"]) if f != "base"]
            fam_sel = st.selectbox("Registered band", fams, index=fams.index("anchor_premium") if "anchor_premium" in fams
                                   else 0, key="pnl_sens_family")
            p = pricing[(pricing["family"] == fam_sel) & (pricing["trade_id"] != "BOOK")]
            base_rows = pricing[(pricing["case"] == "base") & (pricing["trade_id"] != "BOOK")].set_index("trade_id")
            fig = go.Figure()
            for case in dict.fromkeys(p["case"]):
                sub = p[p["case"] == case].sort_values("trade_id")
                fig.add_trace(go.Bar(x=sub["trade_id"], y=sub["cum_pnl_horizon_inr"] / M, name=case,
                                     hovertemplate="%{x}: ₹%{y:,.2f} m<extra>" + case + "</extra>"))
            fig.add_trace(go.Scatter(x=base_rows.index, y=base_rows["cum_pnl_horizon_inr"] / M, mode="markers",
                                     name="published book", marker=dict(symbol="line-ew", size=26, color="#262730",
                                                                         line=dict(width=3, color="#262730"))))
            fig.update_layout(barmode="group")
            charts.finish(fig, y_title="ticket P&L to the horizon, ₹ million", height=400)
            fig.update_layout(hovermode="closest")
            charts.show(fig, key="pnl_sens_by_ticket")
            components.source_caption([PRICING], {"every row": "SENSITIVITY"},
                                      note="the same decisions re-priced through the desk's own rules; trade dates, lots, "
                                           "hedges and events untouched")
        with st.expander("All 25 re-pricing cases (book level)"):
            st.dataframe(summ[["case", "family", "mechanism", "param_key", "param_value", "flag", "cum_pnl_window_end_inr",
                               "cum_pnl_horizon_inr", "delta_vs_base_inr", "pnl_inr_t", "book_pnl_positive", "note",
                               "label"]],
                         hide_index=True, width="stretch", column_config={
                             c: st.column_config.NumberColumn(format="localized")
                             for c in ("cum_pnl_window_end_inr", "cum_pnl_horizon_inr", "delta_vs_base_inr", "pnl_inr_t")})
            components.source_caption([SENS], {"every row": "SENSITIVITY"})
    sec = docs_text.section(DOC30, "Is the headline P&L sign-robust")
    if sec is not None:
        with st.expander(sec.title, icon=":material/menu_book:"):
            st.markdown(docs_text.for_streamlit(sec.body, DOC30))
            st.caption(f"Quoted from `{DOC30}` §{sec.number}, not rewritten for the app.")

# ------------------------------------------------------------------------------------------------ per ticket (3.2, 3.3)
with tab_tkt:
    st.subheader("One ticket at a time")
    if att is None:
        components.missing_data(ATT)
    else:
        book, trades = data.split_book(att)
        tb = data.trade_book(["trade_id", "grade", "lane", "incoterm", "quantity_mt"])
        info = {} if tb is None else {r.trade_id: r for r in tb.itertuples()}
        ids = sorted(trades["trade_id"].unique())

        def _who(x: str) -> str:
            if x == "BOOK":
                return "Book (all nine tickets)"
            r = info.get(x)
            return x if r is None else f"{x} — {r.grade}, {r.lane}, {r.incoterm}, {num(r.quantity_mt)} MT"

        c1, c2 = st.columns([1.3, 1])
        book_ok = components.headline_band_ok(facts)     # the book total is the headline: no band, no book option
        who = c1.selectbox("Ticket", [*ids, "BOOK"] if book_ok else ids, format_func=_who, key="pnl_trade",
                           help=None if book_ok else "the book option is withheld: its anchor-premium band is not "
                                                     "available in this copy")
        asof = c2.radio("As of", ["Horizon", "Window end"], horizontal=True, key="pnl_asof",
                        format_func=lambda a: f"{a} ({day(HZ if a == 'Horizon' else WE, True)})")
        cut = HZ if asof == "Horizon" else WE
        rows = _rows_for(att, who)
        upto = rows[rows["date"] <= cut]
        totals = upto[PNL_BUCKETS].sum()
        resid = float(upto["residual"].sum())
        cum = float(upto["cum_pnl_inr"].iloc[-1]) if not upto.empty else 0.0
        gap = cum - float(totals.sum()) - resid

        pr = data.pnl_sensitivity("pricing")
        rep = None if pr is None else pr[(pr["trade_id"] == who) & (pr["case"] != "base")]["cum_pnl_horizon_inr"]
        qty = info[who].quantity_mt if who in info else (tb["quantity_mt"].sum() if who == "BOOK" and tb is not None else None)
        kp = [
            Kpi(f"P&L to {day(cut, True)}", inr_m(cum, sign=True),
                "the book total is the headline: read it with the band above" if who == "BOOK" else None),
            Kpi("Per MT", f"₹{num(cum / qty)}" if qty else "n/a"),
            Kpi("Residual", inr_m(resid), "unexplained P&L after the eight buckets (a control)"),
            Kpi("Reconciliation gap", inr_m(gap), "eight buckets + residual − cumulative P&L: reconciles to the rupee"),
        ]
        if rep is not None and not rep.empty:
            kp.append(Kpi("Re-pricing range, ₹ m", f"{num(rep.min() / M, 1)} … {num(rep.max() / M, 1)}",
                          f"SENSITIVITY — not base P&L: worst and best of the {len(rep)} registered re-pricing cases, "
                          "to the horizon"))
        components.kpi_row(kp)
        if who == "BOOK":
            components.pnl_band_note(facts)

        steps, colors = _bucket_steps(totals, resid)
        fig = charts.waterfall(steps, colors=colors, total_label=f"P&L to {day(cut)}", y_title="₹ million",
                               title=f"{_who(who)}: attribution to {day(cut, True)}",
                               text=[inr_m(v * M, sign=True) for _, v in steps] + [inr_m(cum, sign=True)], height=440)
        fig.update_xaxes(tickangle=0)
        charts.show(fig, key="pnl_ticket_waterfall")
        line = rows.assign(cum_m=rows["cum_pnl_inr"] / M)
        fig = charts.line_chart(line, "date", {"cum_m": f"{who} cumulative P&L"}, y_title="₹ million", height=340,
                                colors={"cum_m": PALETTE["pnl"]}, events=data.event_markers())
        _ends(fig)
        if not upto.empty:
            fig.add_trace(go.Scatter(x=[pd.Timestamp(upto["date"].iloc[-1])], y=[cum / M], mode="markers",
                                     name=f"as of {day(cut)}", marker=dict(size=11, color=PALETTE["mcx"])))
        fig.update_xaxes(range=[pd.Timestamp(att["date"].min()) - pd.Timedelta(days=7),
                                pd.Timestamp(HZ) + pd.Timedelta(days=30)])
        charts.show(fig, key="pnl_ticket_curve")
        notes = [f"{'BOOK rows only' if who == 'BOOK' else who + ' rows only; BOOK rows excluded'}, summed to "
                 f"{day(cut, True)}"]
        flags_used = {"(0) anchor premium in the sale rule": anchor_flag,
                      "(b) MCX series, basis zero by construction": flags.get("mcx_al_m1_inr_kg", "PROXY"),
                      "(c) grade factors, reconstructed": data.param_flag("grade_factor_mix") or "ASSUMPTION",
                      "(f) events": "SIM"}
        if who == "BOOK" and facts.has("band_lo", "band_hi"):
            notes.append(f"book total at the horizon is the headline, band {t('band_lo')} to {t('band_hi')}")
        components.source_caption([ATT] + ([PRICING] if rep is not None else []), flags_used, note="; ".join(notes))

        st.markdown("**All nine tickets**")
        if facts.has("best_tid", "best_pnl", "best_floor", "n_reprice", "worst_tid", "worst_pnl", "raw_leader",
                     "raw_leader_pnl", "raw_leader_worst"):
            st.markdown(
                f"Best trade on the post-mortem's metric (worst P&L across {t('n_reprice')} registered re-pricing cases): "
                f"**{t('best_tid')}** {t('best_pnl')}, floor {t('best_floor')}. {t('raw_leader')} makes more in rupees "
                f"({t('raw_leader_pnl')}) but falls to {t('raw_leader_worst')} in its worst case. Worst trade: "
                f"**{t('worst_tid')}** {t('worst_pnl')}.")
        tab = []
        for tid in ids:
            g = trades[trades["trade_id"] == tid]
            we = g[g["date"] <= WE]
            hz_v = float(g["cum_pnl_inr"].iloc[-1])
            row = {"Trade": tid}
            if tid in info:
                r = info[tid]
                row |= {"Grade": r.grade, "Lane": r.lane, "Incoterm": r.incoterm, "MT": r.quantity_mt}
            row |= {"P&L to window end ₹ m": (float(we["cum_pnl_inr"].iloc[-1]) if not we.empty else 0.0) / M,
                    "P&L to horizon ₹ m": hz_v / M}
            if tid in info:
                row["₹/MT"] = round(hz_v / info[tid].quantity_mt)
            row |= {charts.bucket_label(b): float(g[b].sum()) / M for b in PNL_BUCKETS}
            if pr is not None:
                cases = pr[(pr["trade_id"] == tid) & (pr["case"] != "base")]["cum_pnl_horizon_inr"]
                row |= {"re-pricing worst ₹ m": cases.min() / M, "re-pricing best ₹ m": cases.max() / M}
            tab.append(row)
        tdf = pd.DataFrame(tab).sort_values("P&L to horizon ₹ m", ascending=False)
        money = [c for c in tdf.columns if "₹ m" in c or c.startswith("(")]
        st.dataframe(tdf, hide_index=True, width="stretch",
                     column_config={**{c: st.column_config.NumberColumn(format="%.2f") for c in money},
                                    "MT": st.column_config.NumberColumn(format="localized"),
                                    "₹/MT": st.column_config.NumberColumn(format="localized")})
        fig = charts.bar_chart(list(tdf["Trade"]), list(tdf["P&L to horizon ₹ m"]),
                               colors=[PALETTE["gain"] if v >= 0 else PALETTE["loss"] for v in tdf["P&L to horizon ₹ m"]],
                               value_title="P&L to the horizon, ₹ million",
                               text=[inr_m(v * M, sign=True) for v in tdf["P&L to horizon ₹ m"]], height=360)
        charts.show(fig, key="pnl_ticket_bars")
        components.source_caption([ATT, BOOK_CSV] + ([PRICING] if pr is not None else []),
                                  {"tickets": "SIM", "re-pricing columns": "SENSITIVITY"},
                                  note="ticket rows only (BOOK rows excluded), bucket columns lifetime to the horizon")

# ------------------------------------------------------------------------------------------------ buckets over time (3.2)
with tab_time:
    st.subheader("Where each period's P&L came from")
    if att is None:
        components.missing_data(ATT)
    else:
        c1, c2, c3 = st.columns([1, 1.2, 1])
        agg = c1.radio("Aggregate", ["Daily", "Weekly", "Monthly"], index=1, horizontal=True, key="pnl_agg")
        view = c2.radio("View", ["Per period", "Cumulative"], horizontal=True, key="pnl_time_view",
                        help="per-period stacked bars, or each bucket's running total")
        scope = c3.selectbox("Scope", ["BOOK", *sorted(att.loc[att["trade_id"] != "BOOK", "trade_id"].unique())],
                             key="pnl_time_scope")
        rows = _rows_for(att, scope)
        g = rows.groupby(_period_key(rows["date"], agg))[[*PNL_BUCKETS, "residual", "daily_pnl_inr"]].sum() / M
        fig = go.Figure()
        if view == "Per period":
            for b in PNL_BUCKETS:
                fig.add_trace(go.Bar(x=g.index, y=g[b], name=charts.bucket_label(b), marker_color=charts.bucket_color(b),
                                     hovertemplate="%{y:,.2f}<extra>" + charts.bucket_label(b) + "</extra>"))
            fig.add_trace(go.Scatter(x=g.index, y=g["daily_pnl_inr"], name="net P&L", mode="lines+markers",
                                     line=dict(color="#262730", width=1.5), marker=dict(size=4),
                                     hovertemplate="%{y:,.2f}<extra>net</extra>"))
            fig.update_layout(barmode="relative")
        else:
            cg = g.cumsum()
            for b in PNL_BUCKETS:
                fig.add_trace(go.Scatter(x=cg.index, y=cg[b], name=charts.bucket_label(b), mode="lines",
                                         line=dict(color=charts.bucket_color(b), width=2),
                                         hovertemplate="%{y:,.1f}<extra>" + charts.bucket_label(b) + "</extra>"))
            fig.add_trace(go.Scatter(x=cg.index, y=cg["daily_pnl_inr"], name="cumulative P&L", mode="lines",
                                     line=dict(color="#262730", width=3),
                                     hovertemplate="%{y:,.1f}<extra>cumulative</extra>"))
        charts.shade_window(fig)
        _ends(fig)
        charts.finish(fig, y_title=f"₹ million per {'day' if agg == 'Daily' else agg.lower()[:-2]}" if view == "Per period"
                      else "₹ million, cumulative", height=540)
        fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.12, x=0), margin=dict(t=30, b=150))
        charts.show(fig, key="pnl_buckets_time")
        components.source_caption(
            [ATT], {"(b) MCX series": flags.get("mcx_al_m1_inr_kg", "PROXY"),
                    "(c) grade factors": data.param_flag("grade_factor_mix") or "ASSUMPTION"},
            note=f"{scope} rows only, summed by {agg.lower()} period (weeks end Friday); residual over the range "
                 f"{inr_m(float(g['residual'].sum()) * M)}")
        if scope == "BOOK":
            components.pnl_band_note(facts)

# ------------------------------------------------------------------------------------------------ adverse events (3.4–3.6)
with tab_ev:
    e1_tab, e2_tab, e3_tab = st.tabs(["E1 · LME crash", "E2 · INR depreciation", "E3 · logistics and credit"])

    with e1_tab:
        e1 = _event_metrics(E1)
        if e1 is None:
            components.missing_data(E1)
        else:
            st.subheader("The crash from the 7-March all-time high")
            st.markdown(
                f"LME cash fell {pct(e1.f('lme_change_frac'), 1, sign=True)} ({num(e1.f('lme_cash_start_usd_t'), 1)} → "
                f"{num(e1.f('lme_cash_end_usd_t'), 1)} USD/t, {day(e1.s('window_start'))} → {day(e1.s('window_end'), True)}). "
                f"The MCX short offset {num(e1.f('hedge_offset_frac'), 2)} of the physical loss, and against the same "
                f"book with no MCX the hedge was worth {inr_m(e1.f('hedge_benefit_inr'), sign=True)} — **against a mark on "
                f"unsold cargo, not a realised loss**. The cash strain came first: margin outflow peaked at "
                f"{inr_m(e1.f('peak_cumulative_margin_outflow_inr'))} on {day(e1.s('peak_cumulative_margin_outflow_date'), True)}, "
                "before the trough.")
            components.kpi_row([
                Kpi("LME cash move", pct(e1.f("lme_change_frac"), 1, sign=True)),
                Kpi("E1 window P&L", inr_m(e1.f("book_pnl_window_inr"), sign=True),
                    "includes deal margin and grade spread booked inside the window"),
                Kpi("Same book, no MCX", inr_m(e1.f("counterfactual_no_mcx_pnl_inr"), sign=True)),
                Kpi("Hedge benefit", inr_m(e1.f("hedge_benefit_inr"), sign=True), e1.note("hedge_benefit_inr")),
                Kpi("Peak book IM", inr_m(e1.f("max_im_required_inr")),
                    f"{inr_m(e1.f('max_im_stress_012_inr'))} at 12 %, {inr_m(e1.f('max_im_stress_015_inr'))} at 15 %"),
            ])
            left, right = st.columns(2, gap="large")
            with left:
                phys, mark = e1.f("lme_flat_physical_inr"), e1.f("lme_flat_inventory_mark_inr")
                fig = charts.waterfall([("Physical: mark on<br>unsold cargo", mark / M),
                                        ("Physical: other legs", (phys - mark) / M),
                                        ("MCX short", e1.f("lme_flat_mcx_inr") / M)],
                                       total_label="Net bucket (a)", y_title="₹ million",
                                       text=[inr_m(mark, sign=True), inr_m(phys - mark, sign=True),
                                             inr_m(e1.f("lme_flat_mcx_inr"), sign=True),
                                             inr_m(e1.f("bucket_lme_flat_inr"), sign=True)],
                                       title="(a) LME flat price over the window", height=380)
                charts.show(fig, key="pnl_e1_bucket_a")
                components.source_caption([E1], {"MCX series": flags.get("mcx_al_m1_inr_kg", "PROXY")},
                                          note=e1.note("lme_flat_inventory_mark_inr"))
            with right:
                fig = charts.waterfall([("Same book,<br>no MCX", e1.f("counterfactual_no_mcx_pnl_inr") / M),
                                        ("Hedge benefit", e1.f("hedge_benefit_inr") / M)],
                                       total_label="Book as traded", y_title="₹ million",
                                       text=[inr_m(e1.f("counterfactual_no_mcx_pnl_inr"), sign=True),
                                             inr_m(e1.f("hedge_benefit_inr"), sign=True),
                                             inr_m(e1.f("book_pnl_window_inr"), sign=True)],
                                       title="Hedged versus unhedged, over the window", height=380)
                charts.show(fig, key="pnl_e1_hedged")
                components.source_caption([E1], {"MCX series": flags.get("mcx_al_m1_inr_kg", "PROXY"), "book": "SIM"},
                                          note="the counterfactual re-runs the same engine with every MCX leg removed")

            e1d = data.read_csv(E1D, ["date", "daily_pnl_inr", "cum_pnl_inr", "lme_cash_usd_t", "lme_flat"])
            if e1d is None:
                components.missing_data(E1D)
            else:
                e1d = e1d.sort_values("date")
                start = float(e1d["cum_pnl_inr"].iloc[0] - e1d["daily_pnl_inr"].iloc[0])
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=pd.to_datetime(e1d["date"]), y=(e1d["cum_pnl_inr"] - start) / M,
                                         name="book P&L, rebased at the window start", line=dict(color=PALETTE["pnl"], width=2.5),
                                         hovertemplate="₹%{y:,.1f} m<extra>book</extra>"))
                fig.add_trace(go.Scatter(x=pd.to_datetime(e1d["date"]), y=e1d["lme_flat"].cumsum() / M,
                                         name="bucket (a), cumulative", line=dict(color=charts.bucket_color("lme_flat"),
                                                                                   width=1.6, dash="dash"),
                                         hovertemplate="₹%{y:,.1f} m<extra>(a)</extra>"))
                fig.add_trace(go.Scatter(x=pd.to_datetime(e1d["date"]), y=e1d["lme_cash_usd_t"], name="LME cash, USD/t",
                                         yaxis="y2", line=dict(color=PALETTE["neutral"], width=1.2),
                                         hovertemplate="%{y:,.1f} USD/t<extra>LME cash</extra>"))
                cf = (e1.s("crash_fortnight_start"), e1.s("crash_fortnight_end")) if e1.has("crash_fortnight_start") else None
                if cf:
                    fig.add_vrect(x0=pd.Timestamp(cf[0]), x1=pd.Timestamp(cf[1]), fillcolor=PALETTE["loss"], opacity=0.08,
                                  line_width=0, layer="below")
                charts.finish(fig, title="Through the window", y_title="₹ million", height=400)
                _two_axis(fig, "LME cash, USD/t")
                charts.show(fig, key="pnl_e1_path")
                components.source_caption([E1D], {"LME cash": flags.get("lme_cash_usd_t", "DIRECT"),
                                                  "MCX series": flags.get("mcx_al_m1_inr_kg", "PROXY")},
                                          note="shaded: the crash fortnight" if cf else None)

            st.markdown("**MCX variation-margin schedule** — a short pays when the market rises")
            vm = data.mcx_variation_margin(["date", "hedge_id", "vm_inr", "im_required_inr", "net_margin_cash_inr"])
            if vm is None:
                components.missing_data(VM)
            else:
                d = vm.groupby("date", as_index=False)[["vm_inr", "im_required_inr", "net_margin_cash_inr"]].sum()
                d["cum_cash"] = d["net_margin_cash_inr"].cumsum()
                x = pd.to_datetime(d["date"])
                fig = go.Figure()
                fig.add_trace(go.Bar(x=x, y=d["vm_inr"] / M, name="daily variation margin",
                                     marker_color=[PALETTE["gain"] if v >= 0 else PALETTE["loss"] for v in d["vm_inr"]],
                                     hovertemplate="₹%{y:,.1f} m<extra>VM</extra>"))
                fig.add_trace(go.Scatter(x=x, y=d["cum_cash"] / M, name="cumulative margin cash (VM − IM change + charges)",
                                         line=dict(color=PALETTE["pnl"], width=2.5), hovertemplate="₹%{y:,.1f} m<extra>cumulative</extra>"))
                fig.add_trace(go.Scatter(x=x, y=d["im_required_inr"] / M, name="initial margin posted (book)",
                                         line=dict(color=PALETTE["mcx"], width=1.6, dash="dot"),
                                         hovertemplate="₹%{y:,.1f} m<extra>IM</extra>"))
                low = d.loc[d["cum_cash"].idxmin()]
                fig.add_annotation(x=pd.Timestamp(low["date"]), y=low["cum_cash"] / M,
                                   text=f"peak outflow {inr_m(low['cum_cash'])}, {day(low['date'])}", showarrow=True,
                                   arrowhead=2, ax=60, ay=30, font=dict(size=11, color=PALETTE["loss"]))
                if cf:
                    fig.add_vrect(x0=pd.Timestamp(cf[0]), x1=pd.Timestamp(cf[1]), fillcolor=PALETTE["loss"], opacity=0.08,
                                  line_width=0, layer="below")
                charts.finish(fig, y_title="₹ million", height=420)
                charts.show(fig, key="pnl_e1_vm")
                d["month"] = d["date"].str[:7]
                line_peak = vm.assign(month=vm["date"].str[:7]).groupby("month")["im_required_inr"].max()
                monthly = d.groupby("month").agg(vm=("vm_inr", "sum"), net=("net_margin_cash_inr", "sum"),
                                                 cum=("cum_cash", "last"), im_book=("im_required_inr", "max"))
                monthly["im_line"] = line_peak
                monthly = (monthly / M).reset_index().rename(columns={
                    "month": "Month", "vm": "Variation margin ₹ m", "net": "Net margin cash ₹ m",
                    "cum": "Cumulative margin cash ₹ m", "im_line": "Peak IM, one line ₹ m", "im_book": "Peak book IM ₹ m"})
                st.dataframe(monthly[["Month", "Variation margin ₹ m", "Net margin cash ₹ m", "Cumulative margin cash ₹ m",
                                      "Peak IM, one line ₹ m", "Peak book IM ₹ m"]],
                             hide_index=True, width="stretch",
                             column_config={c: st.column_config.NumberColumn(format="%.1f") for c in monthly.columns
                                            if c != "Month"})
                components.source_caption([VM], {"MCX series": flags.get("mcx_al_m1_inr_kg", "PROXY")},
                                          note="all hedge lines summed by day; " + e1.note("mcx_daily_price_limit_caveat"))
            png = data.chart_path("p3_event1_hedged_vs_unhedged")
            if png is not None:
                with st.expander("The published hedged-vs-unhedged chart (daily no-MCX path)"):
                    st.image(str(png), width="stretch")
                    st.caption("Source: `outputs/charts/p3_event1_hedged_vs_unhedged.png` (static; the daily no-MCX path "
                               "is published only as this chart) · " + components.flag_badge("SIM") + " "
                               + components.flag_badge("PROXY") + " MCX series")

    with e2_tab:
        e2 = _event_metrics(E2)
        if e2 is None:
            components.missing_data(E2)
        else:
            st.subheader("The rupee's slide past 80")
            st.markdown(
                f"USD/INR rose {pct(e2.f('usdinr_change_frac'), 2, sign=True)} ({num(e2.f('usdinr_start'), 4)} → "
                f"{num(e2.f('usdinr_end'), 4)}, {day(e2.s('window_start'))} → {day(e2.s('window_end'), True)}). The forwards "
                f"earned {inr_m(e2.f('fx_forwards_inr'), sign=True)}, {num(e2.f('forward_offset_frac_vs_usd_flows'), 2)}× the "
                f"loss on the USD cash legs they were booked against; the forward book was worth "
                f"{inr_m(e2.f('forward_book_benefit_inr'), sign=True)} against the same book with no forwards.")
            components.kpi_row([
                Kpi("USD/INR move", pct(e2.f("usdinr_change_frac"), 2, sign=True)),
                Kpi("E2 window P&L", inr_m(e2.f("book_pnl_window_inr"), sign=True),
                    "the whole book over the window, every bucket"),
                Kpi("Same book, no forwards", inr_m(e2.f("counterfactual_no_forwards_pnl_inr"), sign=True)),
                Kpi("Forward-book benefit", inr_m(e2.f("forward_book_benefit_inr"), sign=True)),
                Kpi("Offset, USD legs", f"{num(e2.f('forward_offset_frac_vs_usd_flows'), 2)}×",
                    e2.note("forward_offset_frac_vs_usd_flows")),
                Kpi("Forward cost", inr_m(e2.f("forward_cost_memo_inr"), sign=True), e2.note("forward_cost_memo_inr")),
            ])
            fig = charts.waterfall([("USD payables<br>and receipts", e2.f("fx_physical_usd_flows_inr") / M),
                                    ("Unsold cargo mark<br>(long USD)", e2.f("fx_inventory_mark_inr") / M),
                                    ("USD/INR forwards", e2.f("fx_forwards_inr") / M),
                                    ("MCX short<br>(short USD)", e2.f("fx_mcx_inr") / M)],
                                   total_label="Net bucket (e)", y_title="₹ million",
                                   text=[inr_m(e2.f(k), sign=True) for k in ("fx_physical_usd_flows_inr",
                                                                              "fx_inventory_mark_inr", "fx_forwards_inr",
                                                                              "fx_mcx_inr", "bucket_fx_inr")],
                                   title="(e) USD/INR over the window, by leg", height=400)
            charts.show(fig, key="pnl_e2_split")
            components.source_caption([E2], {"USD/INR": flags.get("usdinr", "PROXY"), "book": "SIM"},
                                      note=e2.note("fx_inventory_mark_inr"))
            e2d = data.read_csv(E2D, ["date", "fx", "usdinr", "fx_delta_usd", "fx_delta_physical_usd",
                                      "fx_delta_forwards_usd"])
            if e2d is None:
                components.missing_data(E2D)
            else:
                e2d = e2d.sort_values("date")
                x = pd.to_datetime(e2d["date"])
                fig = go.Figure()
                for col, name, color, dash in (("fx_delta_physical_usd", "physical legs (incl. the mark)", PALETTE["lme"], None),
                                               ("fx_delta_forwards_usd", "forward book", PALETTE["fx"], None),
                                               ("fx_delta_usd", "net book", "#262730", "dot")):
                    fig.add_trace(go.Scatter(x=x, y=e2d[col] / M, name=name, line=dict(color=color, width=2, dash=dash),
                                             hovertemplate="USD %{y:,.2f} m<extra>" + name + "</extra>"))
                fig.add_trace(go.Scatter(x=x, y=e2d["usdinr"], name="USD/INR", yaxis="y2",
                                         line=dict(color=PALETTE["neutral"], width=1.2),
                                         hovertemplate="%{y:.4f}<extra>USD/INR</extra>"))
                charts.finish(fig, title="USD delta through the window", y_title="USD million of delta", height=400)
                _two_axis(fig, "USD/INR")
                charts.show(fig, key="pnl_e2_deltas")
                components.source_caption([E2D], {"USD/INR": flags.get("usdinr", "PROXY")},
                                          note=e2.note("customs_fx_note"))

    with e3_tab:
        e3 = _event_metrics(E3)
        if e3 is None:
            components.missing_data(E3)
        else:
            st.subheader("Falling freight, the July void calls and a buyer who paid late")
            fr = [e3.f(k) for k in ("freight_change_window_jea_nsa_frac", "freight_change_window_usec_mun_frac")
                  if k in e3.raw]
            st.info(f"**Freight fell, it did not spike:** container freight moved {pct(fr[0], 1, sign=True)} on Jebel Ali → "
                    f"Nhava Sheva and {pct(fr[1], 1, sign=True)} on US East Coast → Mundra over the event window. "
                    "So event 3 is built from what did happen: the real, dated 27-Jul-2022 void calls at Nhava Sheva and "
                    "Mundra (the dwell and arrival days attributed to them are SIM), SIM quality claims and a SIM buyer "
                    "payment delay. The freight spike the brief anticipated is priced separately below as a labelled "
                    "HYPOTHETICAL stress." if len(fr) == 2 else "Freight levels are not in this table.",
                    icon=":material/sailing:")
            components.kpi_row([
                Kpi("Event cost, life", inr_m(e3.f("event_cost_lifetime_inr"), sign=True), e3.note("event_cost_lifetime_inr")),
                Kpi("In the E3 window", inr_m(e3.f("event_cost_inr"), sign=True), e3.note("event_cost_inr")),
                Kpi("Days past due", f"{num(e3.f('max_days_past_due'))} ({num(e3.f('max_ticketed_payment_delay_days'))} typed)",
                    e3.note("max_days_past_due")),
                Kpi("Breach days", num(e3.f("credit_limit_breach_days")), e3.note("credit_limit_breach_days")),
                Kpi("Early fixture", inr_m(e3.f("fixture_timing_cost_lifetime_inr"), sign=True),
                    "freight fixed early into a falling market, lifetime: " + e3.note("fixture_timing_cost_lifetime_inr")),
            ])
            left, right = st.columns(2, gap="large")
            with left:
                comps = [("Extra dwell<br>(void calls, SIM days)", "event_cost_lifetime_dwell_inr"),
                         ("Buyer payment<br>delay (SIM)", "event_cost_lifetime_payment_delay_inr"),
                         ("Quality claims<br>(SIM)", "event_cost_lifetime_quality_inr")]
                total = e3.f("event_cost_lifetime_inr")
                inter = total - sum(e3.f(k) for _, k in comps)
                fig = charts.waterfall([*[(lab, e3.f(k) / M) for lab, k in comps], ("Interaction", inter / M)],
                                       total_label="Lifetime event cost", y_title="₹ million",
                                       title="The three simulated components, isolated",
                                       text=[inr_m(e3.f(k), sign=True) for _, k in comps]
                                            + [inr_m(inter, dp=2, sign=True), inr_m(total, sign=True)], height=380)
                charts.show(fig, key="pnl_e3_components")
                components.source_caption([E3], {"dwell days, delay, survey outcomes": "SIM",
                                                 "freight levels": flags.get("freight_usec_mun_usd_t", "ASSUMPTION")},
                                          note="each component is the book minus the same book without that event; "
                                               "'interaction' is the total less the three")
            with right:
                stress = data.read_csv(E3F, ["date", "trade_id", "freight_shock_frac", "impact_inr", "label"])
                if stress is None:
                    components.missing_data(E3F)
                else:
                    tk = stress[stress["trade_id"] != "BOOK"]
                    worst = tk.groupby("trade_id")["impact_inr"].min().sort_index()
                    shock = float(stress["freight_shock_frac"].iloc[0])
                    fig = charts.bar_chart(list(worst.index), list(worst / M),
                                           colors=[PALETTE["loss"] if v < 0 else PALETTE["neutral"] for v in worst],
                                           value_title="worst day's impact, ₹ million",
                                           text=[inr_m(v, sign=True) for v in worst],
                                           title=f"HYPOTHETICAL: freight {pct(shock, 0, sign=True)} on every in-window day",
                                           height=380)
                    charts.show(fig, key="pnl_e3_freight_stress")
                    components.source_caption([E3F], ["HYPOTHETICAL"],
                                              note=f"{stress['label'].iloc[0]}; non-zero only while an FOB ticket's freight "
                                                   "is unfixed, so the desk's freight risk is a timing risk, not a price risk")

            st.markdown("**Credit-limit mitigation for the delayed buyer**")
            bce = data.buyer_credit_exposure(usecols=["date", "buyer_id", "credit_limit_inr", "utilisation_frac",
                                                       "utilisation_incl_presettlement_frac"])
            if bce is None:
                components.missing_data(BUYERS)
            else:
                names = sorted(bce["buyer_id"].unique())
                buyer = st.selectbox("Buyer (SIM)", names, index=names.index("BUY_RJK_01") if "BUY_RJK_01" in names else 0,
                                     key="pnl_e3_buyer")
                bb = bce[bce["buyer_id"] == buyer].sort_values("date").assign(
                    rec=lambda z: z["utilisation_frac"] * 100, pre=lambda z: z["utilisation_incl_presettlement_frac"] * 100)
                fig = charts.line_chart(bb, "date", {"rec": "receivable (invoiced, unpaid) vs the limit",
                                                     "pre": "receivable + contracted, not yet invoiced"},
                                        colors={"rec": PALETTE["lme"], "pre": PALETTE["mcx"]}, dashes={"pre": "dash"},
                                        y_title="% of the credit limit", height=360, hover_format=",.0f")
                fig.add_hline(y=100, line_dash="dash", line_color=PALETTE["loss"], annotation_text="credit limit",
                              annotation_position="top left")
                _ends(fig)
                charts.show(fig, key="pnl_e3_credit")
                limit = float(bb["credit_limit_inr"].iloc[0]) if not bb.empty else 0.0
                components.source_caption([BUYERS, E3], ["SIM"],
                                          note=f"limit {inr_m(limit)}. " + e3.note("max_buyer_limit_utilisation_frac") + ". "
                                               + e3.note("max_buyer_contracted_utilisation_frac"))
            png = data.chart_path("p3_adverse_events")
            if png is not None:
                with st.expander("The published three-events chart"):
                    st.image(str(png), width="stretch")
                    st.caption("Source: `outputs/charts/p3_adverse_events.png` (static) · " + components.flag_badge("SIM"))

    components.what_it_tells(DOC31)

# ------------------------------------------------------------------------------------------------ MCX basis (3.4 caveat)
with tab_basis:
    st.subheader("MCX basis: a two-sided risk, not upside")
    basis = data.mcx_table("basis_risk")
    if basis is None:
        components.missing_data(BASIS)
    else:
        bv = {(m, s): float(v) for m, s, v in zip(basis["metric"], basis["scope"], basis["value"])}

        def bget(metric: str, scope: str = "BOOK") -> float | None:
            return bv.get((metric, scope))

        two = bget("basis_plus_roll_change_book_two_sided_inr")
        netted = bget("book_pnl_change_vs_base_inr")
        adverse = bget("book_pnl_change_adverse_image_inr")
        st.warning(
            "Base runs price MCX on a duty-parity proxy, so bucket (b) is zero by construction. Re-running the book on a "
            "third-party MCX mirror (also PROXY) sizes the basis. Its netted book total "
            + (f"({inr_m(netted, sign=True)}) " if netted is not None else "")
            + "is one draw of a two-sided risk: the same path with its sign reversed is "
            + (f"{inr_m(adverse, sign=True)}" if adverse is not None else "equally likely")
            + (f", and (b)+(g) moved jointly are worth ±{inr_m(two)} at book level." if two is not None else "."),
            icon=":material/balance:")
        metrics = {"Whole P&L change vs base": "total_pnl_change_vs_base_inr",
                   "(b) + (g) moved jointly": "basis_plus_roll_change_vs_base_inr",
                   "Bucket (b) on the mirror": "basis_bucket_mirror_inr"}
        pick = st.radio("Measure", list(metrics), horizontal=True, key="pnl_basis_metric")
        per = basis[(basis["metric"] == metrics[pick]) & (basis["scope"] != "BOOK")].sort_values("scope")
        fig = go.Figure()
        if two is not None:
            fig.add_hrect(y0=-two / M, y1=two / M, fillcolor=PALETTE["mcx"], opacity=0.12, line_width=0, layer="below")
            fig.add_annotation(x=1, y=two / M, xref="paper", text=f"book, two-sided: ±{inr_m(two)}", showarrow=False,
                               xanchor="right", yanchor="bottom", font=dict(size=12, color=PALETTE["mcx"]))
        fig.add_trace(go.Bar(x=per["scope"], y=per["value"] / M, marker_color=PALETTE["mcx"],
                             text=[inr_m(v, sign=True) for v in per["value"]], textposition="outside", cliponaxis=False,
                             hovertemplate="%{x}: ₹%{y:,.2f} m<extra></extra>"))
        fig.add_hline(y=0, line_color="#262730", line_width=1.2)
        charts.finish(fig, title=f"Per ticket, lifetime: {pick[0].lower() + pick[1:]}", y_title="₹ million", height=420,
                      legend=False)
        fig.update_layout(hovermode="closest")
        charts.show(fig, key="pnl_basis_tickets")
        components.source_caption([BASIS], {"MCX mirror": "PROXY", "every row": "SENSITIVITY"},
                                  note="read the range across tickets, not the netted book total")
        kp = []
        if bget("per_trade_pnl_change_worst_inr") is not None:
            kp += [Kpi("Worst ticket", inr_m(bget("per_trade_pnl_change_worst_inr"), sign=True), "the loss case"),
                   Kpi("Best ticket", inr_m(bget("per_trade_pnl_change_best_inr"), sign=True), "the gain case"),
                   Kpi("Ticket range", inr_m(bget("per_trade_pnl_change_range_inr")), "best minus worst ticket")]
        if bget("unit_beta_beta") is not None:
            kp += [Kpi("Mirror beta", num(bget("unit_beta_beta"), 3),
                       f"standard error {num(bget('unit_beta_beta_se'), 3)}, R² {num(bget('unit_beta_beta_r2'), 3)}, "
                       f"{num(bget('unit_beta_beta_n_days'))} daily changes"),
                   Kpi("t vs beta = 1", num(bget("unit_beta_beta_t_vs_one"), 2),
                       "daily mirror M1 changes regressed on duty-paid parity: the unit-beta assumption is rejected"),
                   Kpi("Unhedged share", pct(bget("unit_beta_unhedged_frac_at_beta"), 1),
                       "share of a parity move that a beta-1-sized short does not offset")]
        if kp:
            components.kpi_row(kp)
            components.source_caption([BASIS], {"MCX mirror": "PROXY", "every row": "SENSITIVITY"},
                                      note="the base run's hedge benefit is measured on a series whose beta is 1 by "
                                           "construction")
    sec = docs_text.section(DOC31, "The basis sensitivity")
    if sec is not None:
        with st.expander(sec.title, icon=":material/menu_book:"):
            st.markdown(docs_text.for_streamlit(sec.body, DOC31))
            st.caption(f"Quoted from `{DOC31}` §{sec.number}, not rewritten for the app.")

# ------------------------------------------------------------------------------------------------ docs
components.what_it_tells(DOC30)
