"""Trade finder (parity): weekly import parity, the open/closed window, the ex-ante trade rule and the sensitivities.

MASTER_SPEC Table 3 rows 1.1–1.7, read from the Phase 1 tables: parity_weekly.csv (every CONTRACTS §5 line item and the
§5a flags), parity_reference_cases.csv, parity_sensitivity_{summary,cases,lme_fx,freight_duty}[_wide].csv,
term_structure_{weekly,roll_monthly}.csv, parity_quality_scenarios.csv and parity_anchor_correlation.csv. The page
counts, filters and pivots those tables; the landed-cost waterfall adds up the published line items and says how
closely they reconcile to the published landed cost and net arb. Formulas are quoted from docs/10_parity_model.md §3.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.lib import charts, components, data, docs_text  # noqa: E402
from app.lib.components import Kpi  # noqa: E402
from desk import SIM_LABEL  # noqa: E402
from desk.reporting.interview_pack import GRADE_NAMES, LANE_NAMES, inr  # noqa: E402
from desk.reporting.style import PALETTE  # noqa: E402

M = 1e6
PW = data.table_rel("parity_weekly")
REFS = data.table_rel("parity_reference_cases")
SUMMARY = data.table_rel("parity_sensitivity_summary")
CASES = data.table_rel("parity_sensitivity_cases")
LME_FX, LME_FX_WIDE = data.table_rel("parity_sensitivity_lme_fx"), data.table_rel("parity_sensitivity_lme_fx_wide")
FD, FD_WIDE = data.table_rel("parity_sensitivity_freight_duty"), data.table_rel("parity_sensitivity_freight_duty_wide")
TSW, ROLL = data.table_rel("term_structure_weekly"), data.table_rel("term_structure_roll_monthly")
QUALITY = data.table_rel("parity_quality_scenarios")
CORR = data.table_rel("parity_anchor_correlation")
DOC = f"{data.DOCS}/10_parity_model.md"
ELIGIBLE_GREEN = "#2e7d32"

SCREENS = {  # flag column -> (label, the net arb that screen tests)
    "trade_eligible": ("Trade-eligible (§5a: all three open)", "net_arb_inr_t"),
    "open_base": ("Case 1 · base screen", "net_arb_inr_t"),
    "open_pit_mix": ("Case 2 · point-in-time grade mix", "net_arb_pit_mix_inr_t"),
    "open_conv18k": ("Case 3 · conversion ₹18k/t ingot", "net_arb_conv18k_inr_t"),
    "trade_eligible_pit": ("No-hindsight gate (PIT mix on both legs)", "net_arb_pit_conv18k_inr_t"),
}
BAND_LINES = {"mix_pit": ("#8064a2", "point-in-time mix"), "anchor_sticky_trailing": (PALETTE["mcx"], "sticky anchor"),
              "anchor_mirror_m1": (PALETTE["fx"], "mirror MCX M1 anchor")}

spec = components.PAGE["parity"]
components.sim_banner()
components.page_header(spec.title, spec.blurb, spec.spec_rows)


def pflag(key: str, default: str = "ASSUMPTION") -> str:
    return data.param_flag(key) or default


sflags = data.series_flags()


def week(d) -> str:
    return pd.Timestamp(d).strftime("%d-%b-%Y")


def rupee(x: float) -> str:
    """₹ with thousands separators and a true minus sign, as the reports print it."""
    return inr(x)


def watermark_above(fig: go.Figure) -> go.Figure:
    """Move the SIM watermark from inside the plot (where it would cover heatmap cells or bars) to just above it."""
    for a in fig.layout.annotations:
        if a.text == SIM_LABEL:
            a.update(y=1, yanchor="bottom", yshift=2)
    return fig


def runs(dates: list[str]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Consecutive week_ends (7 days apart) merged into (start of first week, last week_end) spans."""
    out: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for d in sorted(pd.Timestamp(x) for x in dates):
        if out and (d - out[-1][1]).days == 7:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d - pd.Timedelta(days=7), d))
    return out


def formula_table() -> dict[str, tuple[str, str, str]]:
    """docs/10_parity_model.md §3 as {line item: (formula, unit, value flag)}; {} if the doc is not in this copy."""
    sec = docs_text.section(DOC, "Formula table")
    out: dict[str, tuple[str, str, str]] = {}
    for line in (sec.body.splitlines() if sec else []):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0].startswith("`"):
            out[cells[0].strip("`")] = (cells[1], cells[2], cells[4].strip("*"))
    return out


def quote(heading: str, marker: str, label: str, after: str | None = None) -> None:
    """Expander quoting one paragraph of docs/10_parity_model.md verbatim: the first containing `marker` (after the
    first paragraph containing `after`, when given)."""
    sec = docs_text.section(DOC, heading)
    paras = sec.body.split("\n\n") if sec else []
    if after is not None:
        first = next((i for i, p in enumerate(paras) if after in p), None)
        paras = [] if first is None else paras[first + 1:]
    paras = [p for p in paras if marker in p]
    if not paras:
        if not data.exists(DOC):
            components.missing_data(DOC)
        else:
            st.info(f"`{DOC}` no longer has the passage “{marker}”.", icon=":material/info:")
        return
    with st.expander(label, icon=":material/menu_book:"):
        st.markdown(docs_text.for_streamlit(paras[0], DOC))
        st.caption(f"Quoted from `{DOC}` §{sec.number}, not rewritten for the app.")


# ------------------------------------------------------------------------------------------------ takeaway
pw = data.parity_weekly()
win = pw[pw["in_window"]] if pw is not None else None
if win is not None and not win.empty:
    n, n_el, n_base = len(win), int(win["trade_eligible"].sum()), int(win["open_base"].sum())
    n_pit_gate, n_pit_open = int(win["trade_eligible_pit"].sum()), int(win["open_pit_mix"].sum())
    reduces = bool((win["trade_eligible"] == win["open_conv18k"]).all())
    threshold = float(win["margin_threshold_inr_t"].iloc[0])
    st.markdown(
        f"**{n_el} of {n} in-window week × grade × lane cases were trade-eligible under the rule declared before any "
        f"parity result existed ({n_base} were open on the base screen alone).** The rule is unbendable, not "
        "point-in-time: "
        + (f"on this panel `trade_eligible` equals the conversion-₹18k screen on every in-window row (the "
           f"point-in-time grade-mix screen is open in {n_pit_open} of {n} and never binds), and that screen reads "
           "the lag-2 grade mix, a hindsight reconstruction. " if reduces else
           "two of its three screens read the lag-2 grade mix, a hindsight reconstruction. ")
        + f"The no-hindsight gate published beside it would have opened {n_pit_gate} of {n}.")
    components.kpi_row([
        Kpi("Trade-eligible", f"{n_el} of {n}", "in-window week × grade × lane cases open on all three §5a screens"),
        Kpi("Base screen open", f"{n_base} of {n}", "net arb above the hurdle with every input as registered"),
        Kpi("No-hindsight gate", f"{n_pit_gate} of {n}", "`trade_eligible_pit`: the point-in-time grade mix on both "
                                                        "the base and the conversion-₹18k legs (disclosure only)"),
        Kpi("Hurdle", f"{rupee(threshold)}/MT", f"`margin_threshold_inr_t` ({pflag('margin_threshold_inr_t')}), "
                                                       "per MT of scrap"),
        Kpi("Case grid", f"{win['week_end'].nunique()} × {win['grade'].nunique()} × {win['lane'].nunique()}",
            "weeks × grades × lanes: W-FRI weeks overlapping 1-Mar to 31-Aug-2022"),
    ])
    components.source_caption([PW], {"every net arb (weakest input)": "ASSUMPTION", "LME 3M": "DIRECT",
                                     "MCX anchor": sflags.get("mcx_al_m1_inr_kg", "PROXY"),
                                     "lag-2 grade mix": pflag("grade_factor_mix", "PROXY"),
                                     "point-in-time mix": pflag("grade_factor_mix_pit")},
                              note="counts of the published flags over in-window rows")
else:
    components.missing_data(PW)

# ------------------------------------------------------------------------------------------------ selectors
s1, s2 = st.columns(2, gap="large")
grade = s1.selectbox("Grade", list(GRADE_NAMES), format_func=lambda g: GRADE_NAMES[g], key="parity_grade")
lane = s2.selectbox("Lane", list(LANE_NAMES), format_func=lambda x: f"{LANE_NAMES[x]} ({x})", key="parity_lane")
label_gl = f"{GRADE_NAMES[grade]} · {LANE_NAMES[lane]}"
sel = (pw[(pw["grade"] == grade) & (pw["lane"] == lane)].sort_values("week_end").reset_index(drop=True)
       if pw is not None else None)

tabs = st.tabs(["Net arb", "Eligibility", "Waterfall", "Grids", "Band", "Term structure", "Quality", "Anchor study"])

# ------------------------------------------------------------------------------------------------ 1.4 net arb
with tabs[0]:
    if sel is None or sel.empty:
        components.missing_data(PW)
    else:
        sw = sel[sel["in_window"]]
        best, worst = sw.loc[sw["net_arb_inr_t"].idxmax()], sw.loc[sw["net_arb_inr_t"].idxmin()]
        components.kpi_row([
            Kpi("Trade-eligible weeks", f"{int(sw['trade_eligible'].sum())} of {len(sw)}", label_gl),
            Kpi("Base screen weeks", f"{int(sw['open_base'].sum())} of {len(sw)}"),
            Kpi("Best base net arb", f"{rupee(best['net_arb_inr_t'])}/MT", f"week ending {week(best['week_end'])}"),
            Kpi("Worst base net arb", f"{rupee(worst['net_arb_inr_t'])}/MT", f"week ending {week(worst['week_end'])}"),
        ])
        gate = st.toggle("Add the no-hindsight gate's conversion leg (point-in-time mix + ₹18k conversion)",
                         value=False, key="parity_pit_leg")
        series = {"net_arb_inr_t": "Net arb, base (§5)", "net_arb_pit_mix_inr_t": "Point-in-time grade mix (§5a case 2)",
                  "net_arb_conv18k_inr_t": "Conversion ₹18k/t ingot (§5a case 3)"}
        if gate:
            series["net_arb_pit_conv18k_inr_t"] = "No-hindsight gate: PIT mix + conversion ₹18k"
        fig = charts.line_chart(sel, "week_end", series, colors={"net_arb_inr_t": PALETTE["pnl"],
                                                                 "net_arb_pit_mix_inr_t": "#8064a2",
                                                                 "net_arb_conv18k_inr_t": PALETTE["mcx"],
                                                                 "net_arb_pit_conv18k_inr_t": PALETTE["neutral"]},
                                dashes={"net_arb_pit_mix_inr_t": "dash", "net_arb_conv18k_inr_t": "dot",
                                        "net_arb_pit_conv18k_inr_t": "dashdot"},
                                y_title="₹ per MT of scrap", height=440, hover_format=",.0f",
                                events=data.event_markers())
        fig.update_traces(mode="lines+markers", marker=dict(size=4), selector=dict(name=series["net_arb_inr_t"]))
        for x0, x1 in runs(list(sw.loc[sw["trade_eligible"], "week_end"])):
            fig.add_vrect(x0=x0, x1=x1, fillcolor=ELIGIBLE_GREEN, opacity=0.2, line_width=0, layer="below")
        thr = float(sel["margin_threshold_inr_t"].iloc[0])
        fig.add_hline(y=thr, line=dict(color=PALETTE["loss"], width=1.2, dash="dashdot"),
                      annotation_text=f"hurdle {rupee(thr)}/MT", annotation_position="bottom right",
                      annotation_font=dict(size=11, color=PALETTE["loss"]))
        charts.show(fig, key="parity_net_arb")
        components.source_caption(
            [PW], {"net arb": "ASSUMPTION", "lag-2 grade mix (base, case 3)": pflag("grade_factor_mix", "PROXY"),
                   "point-in-time mix (case 2)": pflag("grade_factor_mix_pit"),
                   "conversion grid": pflag("conversion_cost_sensitivity_inr_t_ingot")},
            note="green bands = trade-eligible in-window weeks (each band covers the week ending on its right edge); "
                 "blue shading = the Mar–Aug window")
        only_win = st.checkbox("In-window weeks only", value=True, key="parity_flags_window")
        t = (sw if only_win else sel)[["week_end", "in_window", "net_arb_inr_t", "net_arb_pit_mix_inr_t",
                                       "net_arb_conv18k_inr_t", "open_base", "open_pit_mix", "open_conv18k",
                                       "trade_eligible", "trade_eligible_pit"]].round(0)
        st.dataframe(t, hide_index=True, width="stretch", column_config={
            "week_end": "Week ending", "in_window": "In window",
            "net_arb_inr_t": st.column_config.NumberColumn("Base net arb ₹/MT", format="localized"),
            "net_arb_pit_mix_inr_t": st.column_config.NumberColumn("PIT mix ₹/MT", format="localized"),
            "net_arb_conv18k_inr_t": st.column_config.NumberColumn("Conv 18k ₹/MT", format="localized"),
            "open_base": "Case 1 base", "open_pit_mix": "Case 2 PIT mix", "open_conv18k": "Case 3 conv 18k",
            "trade_eligible": "Trade-eligible", "trade_eligible_pit": "No-hindsight gate"})
        components.source_caption([PW], {"flags": "ASSUMPTION"},
                                  note="rows as published; `trade_eligible` = base ∧ PIT mix ∧ conv 18k (CONTRACTS §5a)")

# ------------------------------------------------------------------------------------------------ 1.4 heatmap
with tabs[1]:
    if pw is None:
        components.missing_data(PW)
    else:
        h1, h2 = st.columns([2.2, 1], gap="large")
        screen = h1.radio("Screen", list(SCREENS), format_func=lambda k: SCREENS[k][0], horizontal=True,
                          key="parity_screen")
        hm_win = h2.toggle("In-window weeks only", value=True, key="parity_heat_window")
        src = win if hm_win else pw
        weeks = sorted(src["week_end"].unique())
        rows, labels, hover = [], [], []
        col_arb = SCREENS[screen][1]
        for g in GRADE_NAMES:
            for ln in LANE_NAMES:
                s = src[(src["grade"] == g) & (src["lane"] == ln)].set_index("week_end").reindex(weeks)
                rows.append(s[screen].astype(float).tolist())
                labels.append(f"{GRADE_NAMES[g]} · {ln}")
                hover.append([f"{'open' if o == 1 else 'closed'} · {SCREENS[screen][0]} net arb {rupee(v)}/MT"
                              if pd.notna(v) else "" for o, v in zip(s[screen].astype(float), s[col_arb])])
        fig = go.Figure(go.Heatmap(
            z=rows, x=[pd.Timestamp(w).strftime("%d-%b-%y") for w in weeks], y=labels, customdata=hover, zmin=0, zmax=1,
            colorscale=[[0, "#eef1f5"], [0.5, "#eef1f5"], [0.5, ELIGIBLE_GREEN if screen.startswith("trade") else
                                                            "#9dc3e6"], [1, ELIGIBLE_GREEN if screen.startswith("trade")
                                                                         else "#9dc3e6"]],
            showscale=False, xgap=1, ygap=2, hovertemplate="%{y}<br>week ending %{x}<br>%{customdata}<extra></extra>"))
        watermark_above(charts.finish(fig, height=330, legend=False))
        fig.update_layout(hovermode="closest", margin=dict(t=30))
        fig.update_xaxes(type="category", tickangle=-60, showgrid=False, tickfont=dict(size=10))
        fig.update_yaxes(type="category", autorange="reversed", showgrid=False)
        charts.show(fig, key="parity_heatmap")
        components.source_caption([PW], {"screen": "ASSUMPTION"},
                                  note=f"coloured = open on “{SCREENS[screen][0]}”, grey = closed; hover for the net "
                                       "arb that screen tests")
        counts = win.groupby(["grade", "lane"], sort=False)[list(SCREENS)].sum().astype(int).reset_index()
        counts.insert(2, "weeks", win.groupby(["grade", "lane"], sort=False).size().to_numpy())
        counts["grade"] = counts["grade"].map(GRADE_NAMES)
        counts.loc[len(counts)] = ["All", "", int(counts["weeks"].sum()), *counts[list(SCREENS)].sum().astype(int)]
        st.dataframe(counts.rename(columns={k: v[0] for k, v in SCREENS.items()}), hide_index=True, width="stretch")
        components.source_caption([PW], note="open in-window weeks per grade × lane, counted from the published flags")
        quote("Results (base, §5a flags", "How to read it.", "How to read the eligibility calendar (docs §6)")

# ------------------------------------------------------------------------------------------------ 1.2 waterfall
with tabs[2]:
    if sel is None or sel.empty:
        components.missing_data(PW)
    else:
        refs = data.parity_extra("reference_cases")
        default_week = None
        if refs is not None:
            hit = refs[(refs["grade"] == grade) & (refs["lane"] == lane)]
            default_week = hit["week_end"].iloc[0] if not hit.empty else None
        elig = sel.loc[sel["in_window"] & sel["trade_eligible"], "week_end"]
        default_week = default_week or (elig.iloc[0] if not elig.empty else sel.loc[sel["in_window"], "week_end"].iloc[0])
        options = list(sel["week_end"])
        tags = dict(zip(sel["week_end"], sel.apply(lambda r: ("eligible" if r["trade_eligible"] else "not eligible")
                                                   + ("" if r["in_window"] else ", context week"), axis=1)))
        wk = st.selectbox("Week ending", options, index=options.index(default_week), key="parity_week",
                          format_func=lambda w: f"{week(w)} · {tags[w]}")
        row = sel[sel["week_end"] == wk].iloc[0]
        fx = float(row["usdinr_goods"])
        lme_inr, cfr_inr, ins_inr = row["lme_3m_usd_t"] * fx, row["cfr_usd_t"] * fx, row["insurance_usd_t"] * fx
        duties = row["bcd_inr_t"] + row["sws_inr_t"]
        fin = row["finance_inr_t"] + row["igst_finance_inr_t"]
        built = row["goods_inr_t"] + duties + row["port_inr_t"] + fin
        igst_in_landed = row["landed_inr_t"] - built
        steps = [("LME 3M × FX", lme_inr, "absolute"), ("grade factor", cfr_inr - lme_inr, "relative"),
                 ("CFR", None, "total"), ("insurance", ins_inr, "relative"), ("CIF", None, "total"),
                 ("BCD + SWS", duties, "relative"), ("port, C&F, PSIC", row["port_inr_t"], "relative"),
                 ("finance", fin, "relative")]
        if abs(igst_in_landed) > 1.0:        # IGST is in landed cost only when input credit is not available
            steps.append(("IGST (no input credit)", igst_in_landed, "relative"))
        steps.append(("Landed", None, "total"))
        totals = {"CFR": cfr_inr, "CIF": cfr_inr + ins_inr, "Landed": row["landed_inr_t"]}
        text = [components.num(totals[s[0]]) if s[2] == "total" else
                (components.num(s[1]) if s[2] == "absolute" else ("+" if s[1] >= 0 else "") + components.num(s[1]))
                for s in steps]
        realisation = row["anchor_inr_t"] * row["recovery_frac"]
        net_steps = [("anchor × recovery", realisation, "absolute"), ("by-product", row["byproduct_inr_t"], "relative"),
                     ("conversion", -row["conversion_inr_t"], "relative"), ("Net realisation", None, "total"),
                     ("landed cost", -row["landed_inr_t"], "relative"), ("Net arb", None, "total")]
        net_text = [components.num(realisation), "+" + components.num(row["byproduct_inr_t"]),
                    components.num(-row["conversion_inr_t"]),
                    components.num(realisation + row["byproduct_inr_t"] - row["conversion_inr_t"]),
                    components.num(-row["landed_inr_t"]), components.num(row["net_arb_inr_t"])]

        k = st.columns(4)
        k[0].metric("Landed cost", f"{rupee(row['landed_inr_t'])}/MT", border=True)
        k[1].metric("Net realisation", f"{rupee(realisation + row['byproduct_inr_t'] - row['conversion_inr_t'])}/MT",
                    border=True)
        k[2].metric("Net arb", f"{rupee(row['net_arb_inr_t'])}/MT",
                    f"{rupee(row['net_arb_inr_t'] - row['margin_threshold_inr_t'])} vs hurdle", border=True)
        k[3].metric("Window / §5a", f"{'open' if row['window_open'] else 'closed'} / "
                                    f"{'eligible' if row['trade_eligible'] else 'not eligible'}", border=True,
                    help=f"USD memo: {components.num(row['net_arb_usd_t'], 2)} USD/MT")

        def waterfall(items, labels_text, title, cost_side: bool) -> go.Figure:
            up, down = (PALETTE["loss"], PALETTE["gain"]) if cost_side else (PALETTE["gain"], PALETTE["loss"])
            fig = go.Figure(go.Waterfall(
                x=[s[0] for s in items], y=[s[1] or 0 for s in items], measure=[s[2] for s in items],
                text=labels_text, textposition="outside", cliponaxis=False,
                connector=dict(line=dict(color="#c9ced6", width=1)),
                increasing=dict(marker=dict(color=up)), decreasing=dict(marker=dict(color=down)),
                totals=dict(marker=dict(color=PALETTE["lme"] if cost_side else PALETTE["mcx"])),
                hovertemplate="%{x}: %{text} ₹/MT<extra></extra>"))
            watermark_above(charts.finish(fig, title=title, height=430, y_title="₹ per MT of scrap", legend=False))
            fig.update_layout(hovermode="closest")
            fig.update_xaxes(tickangle=-30)
            return fig

        w1, w2 = st.columns([1.35, 1], gap="large")
        with w1:
            fig = waterfall(steps, text, "Landed cost build-up (y-axis truncated)", cost_side=True)
            low = min(row["landed_inr_t"], cfr_inr, lme_inr)
            fig.update_yaxes(range=[low * 0.9, max(lme_inr, row["landed_inr_t"]) * 1.04])
            charts.show(fig, key="parity_waterfall_landed")
        with w2:
            fig = waterfall(net_steps, net_text, "Realisation → net arb", cost_side=False)
            charts.show(fig, key="parity_waterfall_net")
        gap_landed = (cfr_inr + ins_inr + duties + row["port_inr_t"] + fin
                      + (igst_in_landed if abs(igst_in_landed) > 1.0 else 0.0)) - row["landed_inr_t"]
        gap_net = (realisation + row["byproduct_inr_t"] - row["conversion_inr_t"] - row["landed_inr_t"]
                   - row["net_arb_inr_t"])
        line_flags = {"LME 3M": sflags.get("lme_3m_usd_t", "DIRECT"),
                      "goods FX (1M forward)": sflags.get("usdinr_fwd_1m", "PROXY"),
                      "grade factor": pflag(f"grade_factor_{grade}"),
                      "freight": sflags.get(f"freight_{lane.lower()}_usd_t", "ASSUMPTION"),
                      "MCX anchor": sflags.get("mcx_al_m1_inr_kg", "PROXY"), "every line item": "ASSUMPTION"}
        components.source_caption(
            [PW], line_flags,
            note=f"bars add the published line items for {label_gl}, week ending {week(wk)}; the landed bars reconcile to "
                 f"`landed_inr_t` within ₹{abs(gap_landed):,.2f}/MT and the net-arb bars to `net_arb_inr_t` within "
                 f"₹{abs(gap_net):,.2f}/MT (rounding of the published 2-dp values). Goods at the 1M forward "
                 f"{fx:.4f}; duties on the customs rate {row['customs_usdinr_import']:.2f} ({row['customs_fx_src']}); "
                 f"anchor = MCX {row['mcx_contract']} proxy + premium")

        formulas = formula_table()
        items = ["cfr_usd_t", "payload_scale", "freight_usd_t", "fob_usd_t", "insurance_usd_t", "cif_usd_t",
                 "av_customs_inr_t", "goods_inr_t", "bcd_inr_t", "sws_inr_t", "igst_inr_t", "port_inr_t",
                 "finance_inr_t", "igst_finance_inr_t", "landed_inr_t", "recovery_frac", "anchor_inr_t",
                 "byproduct_inr_t", "conversion_inr_t", "net_arb_inr_t"]
        def unit_of(c: str) -> str:
            if c in formulas and formulas[c][1]:
                return formulas[c][1]
            return "USD/MT" if c.endswith("_usd_t") else "INR/MT" if c.endswith("_inr_t") else "frac"

        table = pd.DataFrame([{
            "Line item": c, "Value": components.num(row[c], 4 if c.endswith(("usd_t", "frac")) or c == "payload_scale"
                                                    else 2),
            "Unit": unit_of(c), "Formula (docs §3)": formulas.get(c, ("", "", ""))[0],
            "Value flag": formulas.get(c, ("", "", ""))[2]} for c in items])
        with st.expander("Every §5 line item for this week, with its formula and unit"):
            st.dataframe(table, hide_index=True, width="stretch",
                         column_config={"Formula (docs §3)": st.column_config.TextColumn(width="large")})
            inputs = pd.DataFrame([
                ("lme_3m_usd_t", row["lme_3m_usd_t"], "USD/MT", sflags.get("lme_3m_usd_t", "DIRECT")),
                ("usdinr (spot)", row["usdinr"], "₹ per USD", sflags.get("usdinr", "PROXY")),
                ("usdinr_goods (1M forward)", row["usdinr_goods"], "₹ per USD", sflags.get("usdinr_fwd_1m", "PROXY")),
                ("customs_usdinr_import", row["customs_usdinr_import"], "₹ per USD", row["customs_fx_src"]),
                ("grade_factor", row["grade_factor"], "fraction of LME 3M", pflag(f"grade_factor_{grade}")),
                ("freight_base_usd_t", row["freight_base_usd_t"], "USD/MT", row["freight_src"]),
                (f"mcx_anchor_inr_kg ({row['mcx_contract']})", row["mcx_anchor_inr_kg"], "₹/kg",
                 sflags.get("mcx_al_m1_inr_kg", "PROXY")),
                ("margin_threshold_inr_t", row["margin_threshold_inr_t"], "₹/MT", pflag("margin_threshold_inr_t")),
            ], columns=["Input", "Value", "Unit", "Flag or source label"])
            inputs["Value"] = inputs["Value"].map(lambda v: components.num(v, 4))
            st.dataframe(inputs, hide_index=True, width="stretch")
            components.source_caption([PW, DOC], note="formulas, units and value flags quoted from the doc's §3 table")

# ------------------------------------------------------------------------------------------------ 1.5 grids
with tabs[3]:
    refs = data.parity_extra("reference_cases")
    if refs is None:
        components.missing_data(REFS)
    else:
        g1, g2 = st.columns([1.2, 1.4], gap="large")
        ref = g1.selectbox("Reference case", list(refs["ref_case"]), key="parity_ref",
                           format_func=lambda r: (lambda x: f"{r} · {week(x['week_end'])} · {GRADE_NAMES[x['grade']]} · "
                                                            f"{x['lane']}")(refs.set_index("ref_case").loc[r]))
        grid = g2.radio("Grid", ["lme_fx", "fob", "cfr"], horizontal=True, key="parity_grid", format_func={
            "lme_fx": "LME × USD/INR", "fob": "Freight × BCD, FOB terms", "cfr": "Freight × BCD, CFR terms"}.get)
        r = refs.set_index("ref_case").loc[ref]
        st.caption(f"Selection rule: {r['rule']}.")
        if grid == "lme_fx":
            wide, long = data.parity_sensitivity("lme_fx", wide=True), data.parity_sensitivity("lme_fx")
            if wide is None:
                components.missing_data(LME_FX_WIDE)
            else:
                w = wide[wide["ref_case"] == ref].dropna(axis=1, how="all")
                fx_cols = [c for c in w.columns if c.startswith("usdinr_")]

                def fx_of(c: str) -> float:
                    return float(c.split("_")[-1])

                fx_cols.sort(key=fx_of)
                names = [f"{fx_of(c):.2f} (base)" if "_base_" in c else f"{fx_of(c):g}" for c in fx_cols]
                z = w.set_index("lme_shock_pct")[fx_cols].sort_index(ascending=False) / M
                z.columns, z.index = names, [f"{v:+g} %" for v in z.index]
                fig = charts.heatmap(z, x_title="USD/INR, ₹ per USD", y_title="LME 3M shock",
                                     colorbar_title="₹ mn", text_format=",.2f",
                                     title=f"Margin change on 1,000 MT, ₹ mn · {ref}")
                charts.show(watermark_above(fig), key="parity_grid_lme_fx")
                note = "P&L impact = (net arb shocked − net arb base) × 1,000 MT; purchase and sale both re-price"
                if long is not None:
                    lr = long[long["ref_case"] == ref]
                    note += (f"; base net arb {rupee(lr['net_arb_base_inr_t'].iloc[0])}/MT; window open in "
                             f"{int(lr['window_open_shocked'].sum())} of {len(lr)} cells")
                components.source_caption([LME_FX_WIDE, LME_FX], {"shocks": "HYPOTHETICAL", "impact": "SENSITIVITY"},
                                          note=note)
        else:
            wide, long = data.parity_sensitivity("freight_duty", wide=True), data.parity_sensitivity("freight_duty")
            if wide is None:
                components.missing_data(FD_WIDE)
            else:
                terms = "FOB_desk_books_freight" if grid == "fob" else "CFR_seller_books_freight"
                w = wide[(wide["ref_case"] == ref) & (wide["freight_terms"] == terms)]
                bcd_cols = [c for c in w.columns if c.startswith("bcd_")]
                base_bcd = data.params_register()
                base_rate = None
                if base_bcd is not None:
                    hit = base_bcd.loc[base_bcd["key"] == "bcd_scrap_hs7602", "value"]
                    base_rate = float(hit.iloc[0]) * 100 if not hit.empty else None
                names = []
                for c in bcd_cols:
                    rate = float(c.removeprefix("bcd_").removesuffix("pct"))
                    names.append(f"{rate:g} %" + (" (base)" if base_rate is not None and abs(rate - base_rate) < 1e-9
                                                  else ""))
                z = w.set_index("freight_shock_pct")[bcd_cols].sort_index(ascending=False) / M
                z.columns, z.index = names, [f"{v:+g} %" for v in z.index]
                fig = charts.heatmap(z, x_title="Basic customs duty on scrap (HS 7602)", y_title="Freight shock",
                                     colorbar_title="₹ mn", text_format=",.2f",
                                     title=f"Margin change on 1,000 MT, ₹ mn · {ref} · {grid.upper()}")
                charts.show(watermark_above(fig), key="parity_grid_freight_duty")
                note = ("under CFR terms the seller books freight, so every freight row equals the 0 % row" if grid == "cfr"
                        else "under FOB terms the desk books freight, so a freight shock moves its landed cost")
                if long is not None:
                    lr = long[(long["ref_case"] == ref) & (long["freight_terms"] == terms)]
                    base_fr = lr.loc[lr["freight_shock_pct"] == 0, "freight_shocked_usd_t"]
                    if not base_fr.empty:
                        note += f"; base freight {components.num(base_fr.iloc[0], 2)} USD/MT"
                    note += f"; window open in {int(lr['window_open_shocked'].sum())} of {len(lr)} cells"
                components.source_caption([FD_WIDE, FD], {"freight and duty shocks": "HYPOTHETICAL",
                                                          "impact": "SENSITIVITY",
                                                          "freight level": sflags.get("freight_jea_nsa_usd_t",
                                                                                      "ASSUMPTION")}, note=note)
        if grid == "lme_fx":
            quote("Table 1.5", "The margin is long LME and long USD", f"What this grid says for {ref} (docs §8)",
                  after=f"— `{ref}`")
        else:
            quote("Table 1.5", "Freight matters little", "Freight against duty on the two lanes (docs §8)")

# ------------------------------------------------------------------------------------------------ 1.5 band
with tabs[4]:
    summary = data.parity_sensitivity("summary")
    if summary is None:
        components.missing_data(SUMMARY)
    else:
        b1, b2 = st.columns([1, 2.2], gap="large")
        req_only = b1.toggle("Required cases only", value=False, key="parity_required")
        groups = sorted(summary["case_group"].unique())
        picked = b2.multiselect("Case groups", groups, default=groups, key="parity_groups")
        s = summary[(summary["grade"] == grade) & (summary["lane"] == lane) & summary["case_group"].isin(picked)]
        if req_only:
            s = s[s["required"]]
        st.dataframe(s.drop(columns=["grade", "lane"]).round(0), hide_index=True, width="stretch", column_config={
            "net_arb_min_inr_t": st.column_config.NumberColumn("min net arb ₹/MT", format="localized"),
            "net_arb_median_inr_t": st.column_config.NumberColumn("median ₹/MT", format="localized"),
            "net_arb_max_inr_t": st.column_config.NumberColumn("max ₹/MT", format="localized")})
        components.source_caption([SUMMARY], {"every case": "SENSITIVITY"},
                                  note=f"{label_gl}: open in-window weeks (of {int(summary['n_weeks_in_window'].max())}) "
                                       "and flips vs base per case; `trade_eligible_5a` is the rule itself")
    cases = data.parity_sensitivity("cases", usecols=["week_end", "grade", "lane", "in_window", "case", "required",
                                                      "net_arb_inr_t"])
    if cases is None:
        components.missing_data(CASES)
    else:
        c = cases[(cases["grade"] == grade) & (cases["lane"] == lane) & cases["in_window"] & cases["required"]]
        env = c.groupby("week_end")["net_arb_inr_t"].agg(["min", "max", lambda x: x.quantile(0.25),
                                                          lambda x: x.quantile(0.75)])
        env.columns = ["min", "max", "q25", "q75"]
        env = env.reset_index()
        xs = pd.to_datetime(env["week_end"])
        fig = go.Figure()
        for lo, hi, color, name in (("min", "max", PALETTE["band"], "min–max across required cases"),
                                    ("q25", "q75", "#9dc3e6", "inter-quartile across cases")):
            fig.add_trace(go.Scatter(x=xs, y=env[hi], mode="lines", line=dict(width=0), showlegend=False,
                                     hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=xs, y=env[lo], mode="lines", line=dict(width=0), fill="tonexty",
                                     fillcolor=color, name=name, hoverinfo="skip"))
        base = c[c["case"] == "base"].sort_values("week_end")
        fig.add_trace(go.Scatter(x=pd.to_datetime(base["week_end"]), y=base["net_arb_inr_t"], name="base",
                                 mode="lines+markers", line=dict(color=PALETTE["pnl"], width=2), marker=dict(size=4),
                                 hovertemplate="%{y:,.0f}<extra>base</extra>"))
        for case, (color, lab) in BAND_LINES.items():
            cc = c[c["case"] == case].sort_values("week_end")
            fig.add_trace(go.Scatter(x=pd.to_datetime(cc["week_end"]), y=cc["net_arb_inr_t"], name=lab, mode="lines",
                                     line=dict(color=color, width=1.2, dash="dash"),
                                     hovertemplate=f"%{{y:,.0f}}<extra>{lab}</extra>"))
        if pw is not None:
            thr = float(pw["margin_threshold_inr_t"].iloc[0])
            fig.add_hline(y=thr, line=dict(color=PALETTE["loss"], width=1.2, dash="dashdot"),
                          annotation_text=f"hurdle {rupee(thr)}/MT", annotation_position="bottom right",
                          annotation_font=dict(size=11, color=PALETTE["loss"]))
        charts.finish(fig, title=f"Net-arb sensitivity band, in-window weeks · {label_gl}", height=420,
                      y_title="₹ per MT of scrap")
        charts.show(fig, key="parity_band")
        components.source_caption([CASES, PW], {"every case": "SENSITIVITY", "anchor premium grid":
                                                pflag("domestic_anchor_premium_inr_t")},
                                  note=f"envelope over the {c['case'].nunique()} required cases each week (min, max and "
                                       "quartiles of the published net arbs)")
        quote("Sensitivity band", "The grade-mix lag and the anchor model decide",
              "Findings: what decides the shape and the width of the window (docs §7)")

# ------------------------------------------------------------------------------------------------ 1.7 term structure
with tabs[5]:
    tsw = data.term_structure("weekly")
    if tsw is None:
        components.missing_data(TSW)
    else:
        xs = pd.to_datetime(tsw["week_end"])
        spread = tsw["lme_cash_3m_spread_usd_t"]
        fig = go.Figure(go.Bar(x=xs, y=spread, marker_color=[PALETTE["loss"] if v > 0 else PALETTE["gain"] for v in spread],
                               customdata=tsw["structure"], hovertemplate="%{y:,.1f} USD/MT · %{customdata}<extra></extra>"))
        charts.shade_window(fig)
        charts.finish(fig, title="LME Cash − 3M on the parity value date (red = backwardation, green = contango)",
                      height=300, y_title="USD/MT", legend=False)
        fig.update_layout(hovermode="closest")
        charts.show(fig, key="parity_ts_spread")
        tw = tsw[tsw["in_window"]]
        components.source_caption([TSW], {"LME cash and 3M": sflags.get("lme_cash_usd_t", "DIRECT")},
                                  note=f"in-window weeks: {int((tw['structure'] == 'CONTANGO').sum())} contango, "
                                       f"{int((tw['structure'] == 'BACKWARDATION').sum())} backwardation")

        st.subheader("M+1 pricing basis: implied at decision vs realised")
        fig = charts.line_chart(tsw, "week_end", {
            "lme_3m_usd_t": "LME 3M at decision (what the parity uses)",
            "mplus1_implied_avg_cash_usd_t": "Implied M+1 average cash (known at decision)",
            "hindsight_realised_mplus1_avg_cash_usd_t": "HINDSIGHT: realised M+1 average cash (not known at decision)"},
            colors={"lme_3m_usd_t": PALETTE["lme"], "mplus1_implied_avg_cash_usd_t": PALETTE["fx"],
                    "hindsight_realised_mplus1_avg_cash_usd_t": PALETTE["loss"]},
            dashes={"mplus1_implied_avg_cash_usd_t": "dot", "hindsight_realised_mplus1_avg_cash_usd_t": "dash"},
            y_title="USD/MT", height=360, events=data.event_markers())
        charts.show(fig, key="parity_ts_mplus1")
        components.source_caption([TSW], {"LME official": "DIRECT", "implied curve (linear in days)": "ASSUMPTION",
                                          "realised average": "HINDSIGHT"},
                                  note="the realised M+1 average is never an input to a flag")
        effect = tsw[["week_end", "in_window", "structure", "lme_cash_3m_spread_usd_t", "mplus1_month",
                      "structure_effect_buyer_usd_t", "structure_effect_buyer_1000mt_inr",
                      "hindsight_realised_mplus1_avg_cash_usd_t", "hindsight_price_move_vs_implied_usd_t",
                      "hindsight_effect_buyer_vs_3m_1000mt_inr"]]
        st.dataframe(effect, hide_index=True, width="stretch", column_config={
            "week_end": "Week ending", "in_window": "In window", "lme_cash_3m_spread_usd_t": "Cash − 3M USD/MT",
            "mplus1_month": "M+1 month", "structure_effect_buyer_usd_t": "Ex ante: 3M − implied M+1, USD/MT",
            "structure_effect_buyer_1000mt_inr": st.column_config.NumberColumn("Ex ante ₹ per 1,000 MT",
                                                                               format="localized"),
            "hindsight_realised_mplus1_avg_cash_usd_t": "HINDSIGHT · realised M+1 avg USD/MT",
            "hindsight_price_move_vs_implied_usd_t": "HINDSIGHT · price move vs implied USD/MT",
            "hindsight_effect_buyer_vs_3m_1000mt_inr": st.column_config.NumberColumn(
                "HINDSIGHT · 3M − realised, ₹ per 1,000 MT", format="localized")})
        components.source_caption([TSW], {"hindsight columns": "HINDSIGHT"},
                                  note="+ = a buyer priced on the M+1 average of LME Official Cash pays less than 3M")

    roll = data.term_structure("roll_monthly")
    st.subheader("Roll yield on a 1,000 MT short MCX hedge")
    if roll is None:
        components.missing_data(ROLL)
    else:
        st.warning("The MCX proxy is always in contango by construction: its M2 − M1 is INR interest carry on "
                   "duty-paid parity, not metal term structure. Earning it only offsets the desk's own financing of "
                   "the physical.", icon=":material/warning:")
        xl = [f"{m}{' ·' if w else ''}" for m, w in zip(roll["contract_month"], roll["in_window"])]
        fig = go.Figure()
        for col, name, color in (("short_hedge_roll_yield_1000mt_inr", "MCX panel proxy (INR carry only)", PALETTE["mcx"]),
                                 ("mirror_short_hedge_roll_yield_1000mt_inr",
                                  "MCX third-party mirror (PROXY, 2M partly stale)", "#f4b183"),
                                 ("lme_equiv_short_roll_yield_1000mt_inr", "LME-equivalent carry (Cash–3M pro-rated)",
                                  PALETTE["lme"])):
            fig.add_trace(go.Bar(x=xl, y=roll[col] / M, name=name, marker_color=color,
                                 hovertemplate=f"%{{y:,.2f}} ₹ mn<extra>{name}</extra>"))
        charts.finish(fig, height=340, y_title="₹ million per 1,000 MT (+ = earned by the short)")
        fig.update_layout(barmode="group", hovermode="x unified")
        fig.update_xaxes(type="category")
        charts.show(fig, key="parity_roll")
        mismatch = roll[roll["expiry_matches_published"].astype(str) == "False"]["contract_month"].tolist()
        components.source_caption(
            [ROLL], {"MCX proxy": sflags.get("mcx_al_m2_inr_kg", "PROXY"), "mirror": "PROXY", "LME": "DIRECT"},
            note="rolled M1 → M2 before expiry, 200 lots of 5 MT; months marked · are in the window"
                 + (f"; the panel's rule-based expiry differs from MCX's published date in {', '.join(mismatch)}"
                    if mismatch else ""))
        quote("Table 1.7", "Read carefully", "Roll yield: proxy contango is INR carry (docs §10)")

# ------------------------------------------------------------------------------------------------ 1.6 quality
with tabs[6]:
    q = data.parity_extra("quality_scenarios")
    if q is None:
        components.missing_data(QUALITY)
    else:
        qg = q[q["grade"] == grade]
        q_lanes, q_weeks = sorted(qg["lane"].unique()), sorted(qg["week_end"].unique())
        if lane not in q_lanes:
            st.info(f"Quality scenarios are published for {', '.join(q_lanes)} in the week ending "
                    f"{', '.join(week(w) for w in q_weeks)} only; showing that lane for {GRADE_NAMES[grade]}.",
                    icon=":material/info:")
        yields = qg.drop_duplicates("metal_yield_case").set_index("metal_yield_case")["metal_yield_frac"]
        yc = st.radio("Metal yield", list(yields.index), index=list(yields.index).index("base") if "base" in yields else 0,
                      horizontal=True, key="parity_yield", format_func=lambda c: f"{c} ({components.num(yields[c], 2)})")
        qy = qg[qg["metal_yield_case"] == yc]
        z = qy.pivot_table(index="moisture_frac", columns="contamination_frac", values="net_arb_impact_inr_t")
        z.index = [f"{v:.3f}" for v in z.index]
        z.columns = [f"{v:.3f}" for v in z.columns]
        fig = charts.heatmap(z, x_title="contamination delivered (fraction)", y_title="moisture delivered (fraction)",
                             colorbar_title="₹/MT", text_format=",.0f",
                             title=f"Net-arb impact, ₹/MT vs base quality · {GRADE_NAMES[grade]} · yield {yc}")
        charts.show(watermark_above(fig), key="parity_quality")
        components.source_caption([QUALITY], {"moisture, contamination, yield, SPA schedule": "ASSUMPTION"},
                                  note=f"week ending {', '.join(week(w) for w in q_weeks)}, {', '.join(q_lanes)}; "
                                       "impact = net arb with the SPA settlement − base net arb")
        cols = ["moisture_frac", "contamination_frac", "outcome", "payable_frac", "discount_frac", "recovery_frac",
                "landed_per_t_recovered_inr_t", "net_arb_inr_t", "net_arb_impact_inr_t", "net_arb_no_spa_clauses_inr_t",
                "spa_clause_value_inr_t", "window_open"]
        rupee_cols = [c for c in cols if c.endswith("_inr_t")]
        st.dataframe(qy[cols].round({c: 0 for c in rupee_cols}), hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(c, format="localized") for c in rupee_cols})
        components.source_caption([QUALITY], {"settlement rules": pflag("rejection_penalty_schedule")},
                                  note="REJECTABLE = the buyer may reject the lot; `spa_clause_value_inr_t` is what the "
                                       "weight deduction and discount give back")
        quote("Table 1.6", "Findings.", "Findings: wet or dirty cargo, and yield (docs §9)")

# ------------------------------------------------------------------------------------------------ 1.3 correlation
with tabs[7]:
    corr = data.parity_extra("anchor_correlation")
    if corr is None:
        components.missing_data(CORR)
    else:
        samples = [s for s in corr["sample"].unique() if not s.startswith("adc12")]
        smp = st.radio("Sample", samples, horizontal=True, key="parity_corr_sample",
                       format_func=lambda s: s.replace("_", " ").replace("window", "Mar–Aug window:")
                       .replace("panel", "full panel:"))
        mcx = corr[corr["sample"] == smp]
        metrics = ["n_common_days", "level_corr", "daily_logret_corr", "weekly_logret_corr", "basis_mean_inr_t",
                   "basis_mean_inr_kg", "basis_std_inr_kg"]
        piv = mcx.pivot_table(index="pair", columns="metric", values="value", sort=False)
        piv = piv[[m for m in metrics if m in piv.columns]]
        meta = mcx.drop_duplicates("pair").set_index("pair")[["series_a", "series_b", "flag", "note"]]
        table = meta.join(piv).reset_index()
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "note": st.column_config.TextColumn(width="large"),
            **{m: st.column_config.NumberColumn(m, format="%.3f") for m in
               ("level_corr", "daily_logret_corr", "weekly_logret_corr")},
            **{m: st.column_config.NumberColumn(m, format="localized") for m in ("basis_mean_inr_t",)}})
        components.source_caption([CORR], {"MCX proxy": "PROXY", "third-party mirror (provenance unverified)": "PROXY"},
                                  note="proxy vs duty-paid parity is mechanical (the proxy is that parity); the mirror "
                                       "pairs are the informative ones")
        adc = corr[corr["sample"].str.startswith("adc12")]
        if not adc.empty:
            st.markdown(f"**Secondary-ingot evidence** · {adc['series_a'].iloc[0]} against {adc['series_b'].iloc[0]} "
                        f"({adc['sample'].iloc[0].split('_', 1)[1].replace('_', ' to ')}, not 2022)")
            st.dataframe(adc[["metric", "value"]], hide_index=True, width="stretch",
                         column_config={"value": st.column_config.NumberColumn(format="localized")})
            components.source_caption([CORR], {"ADC12 prints": adc["flag"].iloc[0],
                                               "anchor premium": pflag("domestic_anchor_premium_inr_t")},
                                      note=str(adc["note"].iloc[0]))

components.what_it_tells(DOC, heading="What the §5a rule actually screens on")
components.what_it_tells(DOC)
