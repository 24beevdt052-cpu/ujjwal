"""Sentiment overlay: VADER tone of real dated headlines against LME, the lead–lag tests and a headline explorer.

Reads the Phase 7 tables (outputs/tables/sentiment_*.csv) and quotes docs/70_sentiment_overlay.md. The verdict is the
doc's own sentence (§0), shown next to the test counts from sentiment_summary.csv; if the tables ever stop supporting
it (a lead test turns significant), the page says so instead of repeating the verdict. Nothing is re-estimated here:
the charts plot the published weekly means, standard errors, correlations and intervals.

The public export keeps these tables but leaves out data/processed/headlines_weekly.csv (verbatim titles). If the
scored-headline table is missing too, the explorer falls back to sentiment_week_extremes.csv, then to a note.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

from app.lib import charts, components, data, docs_text  # noqa: E402
from app.lib.components import Kpi  # noqa: E402
from desk.reporting.style import PALETTE  # noqa: E402

DOC = f"{data.DOCS}/70_sentiment_overlay.md"
NEWS_NOTES = f"{data.DOCS}/research/news_notes.md"
HEADLINES_RAW = data.processed_rel("headlines_weekly")
WEEKLY = data.table_rel("sentiment_weekly")
SUMMARY = data.table_rel("sentiment_summary")
LEADLAG = data.table_rel("sentiment_leadlag")
EPISODES = data.table_rel("sentiment_episodes")
SCORED = data.table_rel("sentiment_headlines_scored")
EXTREMES = data.table_rel("sentiment_week_extremes")
LEXICON = data.table_rel("sentiment_lexicon")

SCORED_HINT = ("It is built by Phase 7 from `data/processed/headlines_weekly.csv`, which the public export leaves out "
               "(verbatim headline titles). Rebuild the headlines with the Phase 0 news fetcher online "
               "(`.venv/bin/python run_all.py --only P0`, without `DESK_OFFLINE`), then "
               "`DESK_OFFLINE=1 .venv/bin/python run_all.py --only P7`.")

# weekly score column, its standard error (None: not published) and its z-score, per declared variant
VARIANTS = {
    "vader_all": ("Raw VADER, all headlines (primary)", "mean", "se", "z_score"),
    "adjusted_all": ("Price-direction adjusted, all headlines", "adj_mean", "adj_se", "adj_z_score"),
    "vader_core": ("Raw VADER, aluminium-chain titles only", "core_mean", None, None),
    "adjusted_core": ("Adjusted, aluminium-chain titles only", "core_adj_mean", None, None),
}
VARIANT_COLORS = {"vader_all": PALETTE["lme"], "adjusted_all": PALETTE["mcx"], "vader_core": PALETTE["fx"],
                  "adjusted_core": PALETTE["freight"]}
WEEKLY_COLS = ["week_end", "in_window", "n", "mean", "se", "z_score", "adj_mean", "adj_se", "adj_z_score", "core_n",
               "core_mean", "core_adj_mean", "pos_share", "neg_share", "lme_close_date", "lme_cash_usd_t",
               "lme_cash_logret"]
SCORED_COLS = ["week_end", "published_utc", "source", "title", "core_chain", "cites_later_date", "vader_compound",
               "vader_class", "adj_compound", "adj_class", "lexicon_hits", "lexicon_subject_caveat", "link"]

spec = components.PAGE["sentiment"]
components.sim_banner()
components.page_header(spec.title, spec.blurb, spec.spec_rows)


def text_flags() -> dict[str, str]:
    """Provenance of what this page shows: the doc's own labels (§ header) plus the register flag of the lexicon."""
    lme = data.series_flags().get("lme_cash_usd_t", "DIRECT")
    return {"headline text, publisher, date": "DIRECT", "headline selection (Google News ranking)": "PROXY",
            "LME cash": lme, "price-direction lexicon": data.param_flag("sent_domain_lexicon") or "ASSUMPTION"}


def quote_paragraph(doc_rel: str, heading: str, marker: str, label: str | None = None) -> bool:
    """Render the paragraph of a doc section that contains `marker`, verbatim (inline, or in an expander if `label`)."""
    sec = docs_text.section(doc_rel, heading)
    lines = sec.body.splitlines() if sec else []
    start = next((i for i, line in enumerate(lines) if marker in line), None)
    if start is None:
        return False
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.strip():
            break
        block.append(line)
    body = docs_text.for_streamlit("\n".join(block).strip(), doc_rel)
    where = f"`{doc_rel}` §{sec.number}" if sec.number else f"`{doc_rel}` “{sec.title}”"
    if label:
        with st.expander(label, icon=":material/menu_book:"):
            st.markdown(body)
            st.caption(f"Quoted from {where}, not rewritten for the app.")
    else:
        st.markdown(body)
        st.caption(f"Quoted from {where}, not rewritten for the app.")
    return True


def signed(x: float | None, dp: int = 2) -> str:
    """+0.29 / −0.17 with a true minus sign, as the reports print correlations."""
    if x is None or pd.isna(x):
        return "n/a"
    from desk.reporting.interview_pack import signed as f

    return f(x, dp)


def metric_map(summary: pd.DataFrame | None) -> dict[str, float]:
    if summary is None:
        return {}
    out = {}
    for m, v in zip(summary["metric"], summary["value"]):
        try:
            out[str(m)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def show_png(name: str, label: str, source_note: str) -> None:
    p = data.chart_path(name)
    if p is None:
        return
    with st.expander(label, icon=":material/image:"):
        st.image(str(p), width="stretch")
        components.source_caption([f"{data.CHARTS}/{name}.png"], text_flags(), note=source_note)


# ------------------------------------------------------------------------------------------------ takeaway
summary = data.sentiment_table("summary")
S = metric_map(summary)
leadlag = data.sentiment_table("leadlag")
weekly = data.sentiment_table("weekly", usecols=WEEKLY_COLS)
week_span = (f"Saturday–Friday weeks ending {weekly['week_end'].min()} to {weekly['week_end'].max()}"
             if weekly is not None and len(weekly) else "Saturday–Friday weeks")

st.subheader("The takeaway")
if summary is None:
    components.missing_data(SUMMARY)
else:
    n_lead, n_sig = int(S.get("n_lead_tests", 0)), int(S.get("n_lead_tests_naive_5pct", 0))
    n_bonf, n_boot = int(S.get("n_lead_tests_bonferroni", 0)), int(S.get("n_lead_tests_boot_ci_excludes_zero", 0))
    table_sig = None
    if leadlag is not None:
        leads = leadlag[leadlag["lag_weeks"] > 0]
        table_sig = int(leads["significant_naive_5pct"].astype(str).str.lower().eq("true").sum())
    supported = n_sig == 0 and n_bonf == 0 and n_boot == 0 and table_sig in (None, 0)
    with st.container(border=True):
        if supported:
            if not quote_paragraph(DOC, "The finding on one page", "Plainly"):
                st.markdown(f"**{n_sig} of {n_lead}** lead tests are significant at the naive 5 % level.")
        else:
            st.warning(f"The published tables now show {max(n_sig, table_sig or 0)} of {n_lead} lead tests significant "
                       f"at the naive 5 % level ({n_bonf} after Bonferroni, {n_boot} bootstrap intervals excluding "
                       "zero), so the doc's “no evidence of a lead” verdict is not repeated here. Re-run Phase 7 "
                       "and re-read `docs/70_sentiment_overlay.md` §0.", icon=":material/warning:")
        components.kpi_row([
            Kpi("Headlines", f"{int(S.get('n_headlines', 0)):,}",
                f"median {int(S.get('headlines_per_week_median', 0))} per week "
                f"(min {int(S.get('headlines_per_week_min', 0))}, max {int(S.get('headlines_per_week_max', 0))})"),
            Kpi("Weeks", f"{int(S.get('n_weeks', 0))}", week_span),
            Kpi("Significant leads", f"{n_sig} of {n_lead}",
                f"lead tests significant at the naive 5 % level: lags +1 to +3 weeks × 4 variants; "
                f"{S.get('expected_false_positives_naive_5pct', 0):g} of all {int(S.get('n_tests_total', 0))} tests "
                "would be expected by chance at 5 %"),
            Kpi("Lead CIs excl. zero", f"{n_boot} of {n_lead}",
                f"block-bootstrap 95 % intervals of the lead tests that exclude zero; significant after Bonferroni: "
                f"{n_bonf}"),
            Kpi("Same-week r", signed(S.get("primary_r_same_week")),
                "primary variant (raw VADER, all headlines); naive p = "
                f"{S.get('primary_p_same_week_naive', float('nan')):.2f}; adjusted score r = "
                f"{signed(S.get('adjusted_r_same_week'))}"),
        ])
        components.source_caption([SUMMARY, LEADLAG, DOC], text_flags(),
                                  note="a supporting signal, not a forecasting model: nothing here feeds a trade, "
                                       "VaR or stress number")

tab_weekly, tab_lead, tab_explore, tab_caveats = st.tabs(
    ["Weekly tone vs LME", "Lead / lag tests", "Headline explorer", "Biases & caveats"])

# ------------------------------------------------------------------------------------------------ weekly tone vs LME
with tab_weekly:
    if weekly is None:
        components.missing_data(WEEKLY)
    else:
        c1, c2, c3 = st.columns([1.4, 1.1, 0.9])
        variant = c1.selectbox("Score", list(VARIANTS), format_func=lambda v: VARIANTS[v][0], key="sent_w_variant",
                               help="The four declared variants (docs/70 §2.6); raw VADER on all headlines is primary.")
        overlay = c2.radio("LME overlay", ["Weekly log return", "Cash price"], horizontal=True, key="sent_w_overlay")
        window_only = c3.toggle("Mar–Aug window only", value=False, key="sent_w_window",
                                help=f"The headline sample covers {week_span.lower()}.")
        label, col, se_col, z_col = VARIANTS[variant]
        w = weekly.sort_values("week_end").reset_index(drop=True)
        if window_only:
            w = w[w["in_window"].astype(str).str.lower() == "true"].reset_index(drop=True)
        xs = pd.to_datetime(w["week_end"])
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        colors = [PALETTE["gain"] if v >= 0 else PALETTE["loss"] for v in w[col].fillna(0.0)]
        custom = pd.DataFrame({
            "n": w["core_n"] if variant.endswith("core") else w["n"],
            "z": w[z_col].map(lambda z: "—" if pd.isna(z) else f"{z:+.2f}") if z_col else "not published",
            "se": w[se_col].map(lambda s: f"{s:.3f}") if se_col else "not published"})
        fig.add_trace(go.Bar(
            x=xs, y=w[col], name=f"{label} (weekly mean)", marker_color=colors, opacity=0.85,
            error_y=dict(type="data", array=(1.96 * w[se_col]).tolist(), color="#5b6470", thickness=1, width=3)
            if se_col else None,
            customdata=custom.values,
            hovertemplate="mean %{y:+.3f}<br>headlines %{customdata[0]}<br>s.e. %{customdata[2]}"
                          "<br>past-only z %{customdata[1]}<extra></extra>"), secondary_y=False)
        if overlay == "Weekly log return":
            fig.add_trace(go.Scatter(x=xs, y=w["lme_cash_logret"] * 100, name="LME cash weekly log return",
                                     mode="lines+markers", line=dict(color=PALETTE["lme"], width=2),
                                     marker=dict(size=5), hovertemplate="%{y:+.2f} %<extra>LME log return</extra>"),
                          secondary_y=True)
            y2 = "LME cash, weekly log return (%)"
        else:
            fig.add_trace(go.Scatter(x=xs, y=w["lme_cash_usd_t"], name="LME cash (last close of the week)",
                                     mode="lines+markers", line=dict(color=PALETTE["lme"], width=2),
                                     marker=dict(size=5), hovertemplate="USD %{y:,.1f}/t<extra>LME cash</extra>"),
                          secondary_y=True)
            y2 = "LME cash, USD/MT"
        charts.shade_window(fig)
        charts.mark_events(fig, [(d, lab) for d, lab in data.event_markers()
                                 if str(w["week_end"].min()) <= d[:10] <= str(w["week_end"].max())])
        charts.finish(fig, height=430)
        lo_hi = w[col].abs() + (1.96 * w[se_col] if se_col else 0.0)
        r1 = 1.1 * float(lo_hi.max()) if lo_hi.notna().any() else 1.0
        fig.update_yaxes(title_text="weekly mean compound score" + (" ± 1.96 s.e." if se_col else ""),
                         secondary_y=False, zeroline=True, range=[-r1, r1])
        fig.update_yaxes(title_text=y2, secondary_y=True, showgrid=False, tickmode="auto", zeroline=False)
        if overlay == "Weekly log return":             # zero on both axes at the same height
            r2 = 1.1 * float((w["lme_cash_logret"] * 100).abs().max())
            fig.update_yaxes(range=[-r2, r2], secondary_y=True)
        charts.show(fig, key="sent_weekly_chart")
        components.source_caption(
            [WEEKLY], text_flags(),
            note=("bars are the published weekly means; whiskers are 1.96 × the published standard error"
                  if se_col else "bars are the published weekly means; no standard error is published for the "
                                 "aluminium-chain variants")
                 + "; LME is the last official cash close inside each Saturday–Friday week")
        tag = "adj" if variant.startswith("adjusted") else "vader"
        noise = S.get(f"noise_share_weekly_var_{tag}")
        if noise is not None and not variant.endswith("core"):
            st.caption(f"About {noise:.0%} of this score's week-to-week variance is what re-drawing the week's "
                       f"headlines alone would produce (`noise_share_weekly_var_*` in `{SUMMARY}`). Weeks whose 95 % "
                       f"interval excludes zero: {int(S.get(f'n_weeks_95ci_excludes_zero_{tag}', 0))} "
                       f"of {int(S.get('n_weeks', 0))}.")
        with st.expander("The weekly table", icon=":material/table:"):
            show = w[["week_end", "n", "mean", "se", "z_score", "adj_mean", "adj_se", "adj_z_score", "core_n",
                      "core_mean", "core_adj_mean", "pos_share", "neg_share", "lme_cash_usd_t", "lme_cash_logret"]]
            st.dataframe(show, hide_index=True, width="stretch", column_config={
                "week_end": "week ending", "n": "headlines",
                "mean": st.column_config.NumberColumn("raw mean", format="%+.3f"),
                "se": st.column_config.NumberColumn("raw s.e.", format="%.3f"),
                "z_score": st.column_config.NumberColumn("raw z (past-only)", format="%+.2f"),
                "adj_mean": st.column_config.NumberColumn("adj. mean", format="%+.3f"),
                "adj_se": st.column_config.NumberColumn("adj. s.e.", format="%.3f"),
                "adj_z_score": st.column_config.NumberColumn("adj. z", format="%+.2f"),
                "core_n": "chain headlines",
                "core_mean": st.column_config.NumberColumn("chain raw mean", format="%+.3f"),
                "core_adj_mean": st.column_config.NumberColumn("chain adj. mean", format="%+.3f"),
                "pos_share": st.column_config.NumberColumn("positive share (raw)", format="percent"),
                "neg_share": st.column_config.NumberColumn("negative share (raw)", format="percent"),
                "lme_cash_usd_t": st.column_config.NumberColumn("LME cash USD/MT", format="%,.1f"),
                "lme_cash_logret": st.column_config.NumberColumn("LME log return", format="percent"),
            })
            components.source_caption([WEEKLY], {"LME cash": text_flags()["LME cash"]},
                                      note="z-scores use earlier weeks only and are blank before the fifth week")
        show_png("p7_sentiment_vs_lme", "The published chart (PNG)",
                 "drawn by desk.sentiment.run from the same tables; carries LME price levels")
        quote_paragraph(DOC, "Weekly aggregation and a z-score", "`z_score` compares",
                        label="How the weekly score and its z-score are built")

# ------------------------------------------------------------------------------------------------ lead / lag
with tab_lead:
    if leadlag is None:
        components.missing_data(LEADLAG)
    else:
        labels = dict(zip(leadlag["variant"], leadlag["variant_label"]))
        order = list(dict.fromkeys(leadlag["variant"]))
        is_primary = leadlag.groupby("variant")["is_primary"].first().astype(str).str.lower() == "true"
        primary = [v for v in order if is_primary.get(v, False)]
        c1, c2 = st.columns([1.6, 1])
        chosen = c1.multiselect("Variants", order, default=primary or order[:1], format_func=lambda v: labels[v],
                                key="sent_ll_variants")
        ci = c2.radio("95 % interval", ["Block bootstrap", "Fisher (assumes independent weeks)"], horizontal=False,
                      key="sent_ll_ci")
        chosen = chosen or (primary or order[:1])
        lo_col, hi_col = ("boot_ci_lo", "boot_ci_hi") if ci.startswith("Block") else ("fisher_ci_lo", "fisher_ci_hi")
        fig = go.Figure()
        fig.add_vrect(x0=0.5, x1=3.5, fillcolor=PALETTE["band"], opacity=0.45, line_width=0, layer="below")
        fig.add_annotation(x=2, y=1, xref="x", yref="paper", text="sentiment leads LME (the lead tests)",
                           showarrow=False, yanchor="top", font=dict(size=11, color=charts.MUTED))
        fig.add_annotation(x=-2, y=1, xref="x", yref="paper", text="LME leads sentiment", showarrow=False,
                           yanchor="top", font=dict(size=11, color=charts.MUTED))
        offsets = {v: (i - (len(chosen) - 1) / 2) * 0.14 for i, v in enumerate(chosen)}
        for v in chosen:
            d = leadlag[leadlag["variant"] == v].sort_values("lag_weeks")
            fig.add_trace(go.Scatter(
                x=d["lag_weeks"] + offsets[v], y=d["pearson_r"], mode="markers+lines", name=labels[v],
                line=dict(color=VARIANT_COLORS.get(v), width=1, dash="dot"),
                marker=dict(size=9, color=VARIANT_COLORS.get(v)),
                error_y=dict(type="data", symmetric=False, array=(d[hi_col] - d["pearson_r"]).tolist(),
                             arrayminus=(d["pearson_r"] - d[lo_col]).tolist(), thickness=1.4, width=4),
                customdata=d[["reading", "n_pairs", "pearson_p_naive", lo_col, hi_col]].values,
                hovertemplate="%{customdata[0]}<br>r = %{y:+.2f} (n = %{customdata[1]}, naive p = "
                              "%{customdata[2]:.3f})<br>95 % CI [%{customdata[3]:+.2f}, %{customdata[4]:+.2f}]"
                              "<extra></extra>"))
        fig.add_hline(y=0, line_color="#9aa1ab", line_width=1)
        charts.finish(fig, height=420, x_title="lag k in weeks (sentiment in week t vs LME return in week t + k)",
                      y_title="Pearson r")
        fig.update_xaxes(tickmode="array", tickvals=list(range(-3, 4)), range=[-3.6, 3.6])
        fig.update_layout(hovermode="closest")
        charts.show(fig, key="sent_leadlag_chart")
        components.source_caption([LEADLAG], text_flags(),
                                  note=f"markers are the published Pearson r; whiskers the published {ci.lower()} "
                                       "95 % interval; with 25–28 pairs only |r| above about 0.37–0.40 could pass "
                                       "even the naive test")
        tbl = leadlag[leadlag["variant"].isin(chosen)][
            ["variant", "lag_weeks", "reading", "n_pairs", "pearson_r", "pearson_p_naive", "fisher_ci_lo",
             "fisher_ci_hi", "boot_ci_lo", "boot_ci_hi", "spearman_rho", "significant_naive_5pct",
             "significant_bonferroni_7lags", "boot_ci_excludes_zero"]]
        st.dataframe(tbl, hide_index=True, width="stretch", column_config={
            "variant": "variant", "lag_weeks": "k", "reading": "reading", "n_pairs": "pairs",
            "pearson_r": st.column_config.NumberColumn("r", format="%+.2f"),
            "pearson_p_naive": st.column_config.NumberColumn("naive p", format="%.3f"),
            "fisher_ci_lo": st.column_config.NumberColumn("Fisher lo", format="%+.2f"),
            "fisher_ci_hi": st.column_config.NumberColumn("Fisher hi", format="%+.2f"),
            "boot_ci_lo": st.column_config.NumberColumn("bootstrap lo", format="%+.2f"),
            "boot_ci_hi": st.column_config.NumberColumn("bootstrap hi", format="%+.2f"),
            "spearman_rho": st.column_config.NumberColumn("Spearman ρ", format="%+.2f"),
            "significant_naive_5pct": "sig. naive 5 %", "significant_bonferroni_7lags": "sig. Bonferroni",
            "boot_ci_excludes_zero": "bootstrap CI excludes 0"})
        components.source_caption([LEADLAG], {"LME cash": text_flags()["LME cash"]},
                                  note="naive p-values and Fisher intervals assume independent weeks; the block "
                                       "bootstrap does not, but is itself rough on this sample")
        quote_paragraph(DOC, "Lead/lag statistics", "**Multiple testing.**", label="Why 28 tests need care")
        show_png("p7_sentiment_leadlag", "The published lead/lag chart (PNG)",
                 "drawn by desk.sentiment.run, with the naive and Bonferroni bands")

    st.subheader("Did tone lead the March spike or the May–July reversal?")
    episodes = data.sentiment_table("episodes")
    if episodes is None:
        components.missing_data(EPISODES)
    else:
        if S:
            components.kpi_row([
                Kpi("Signal fired", f"{int(S.get('n_episode_verdicts_signal_fired', 0))}",
                    "see why it does not count as a lead (below)"),
                Kpi("Not testable", f"{int(S.get('n_episode_verdicts_not_testable', 0))}",
                    "no past-only z-score exists before 25-Mar-2022"),
                Kpi("Did not lead", f"{int(S.get('n_episode_verdicts_did_not_lead', 0))}"),
            ])
        ep_variant = st.radio("Variant", list(dict.fromkeys(episodes["variant"])), horizontal=True,
                              format_func=lambda v: VARIANTS.get(v, (v,))[0], key="sent_ep_variant")
        ep = episodes[episodes["variant"] == ep_variant][
            ["anchor", "anchor_date", "direction", "lead_weeks", "lead_z_values", "verdict", "verdict_alt_window",
             "chance_of_hit_in_window_approx_frac", "contrary_hit_weeks", "lme_logret_lead_weeks",
             "lme_logret_next_3_weeks"]]
        st.dataframe(ep, hide_index=True, width="stretch", column_config={
            "anchor_date": "anchor close", "direction": "coming move", "lead_weeks": "lead weeks",
            "lead_z_values": "past-only z in lead weeks", "verdict": "declared verdict",
            "verdict_alt_window": "verdict, alternative window",
            "chance_of_hit_in_window_approx_frac": st.column_config.NumberColumn("chance of ≥1 hit", format="percent"),
            "contrary_hit_weeks": "opposite-way signals",
            "lme_logret_lead_weeks": st.column_config.NumberColumn("LME log ret, lead weeks", format="percent"),
            "lme_logret_next_3_weeks": st.column_config.NumberColumn("LME log ret, next 3 weeks", format="percent")})
        components.source_caption([EPISODES], {"LME cash": text_flags()["LME cash"]},
                                  note="anchors are LME price turns picked with hindsight from the P3 reporting-only "
                                       "event windows; the rule (past-only |z| ≥ 1 the way of the coming move) was "
                                       "declared before the first run")
        quote_paragraph(DOC, "Did sentiment lead the March spike", "**Overall:",
                        label="The doc's reading of the episodes")

# ------------------------------------------------------------------------------------------------ headline explorer
with tab_explore:
    scored = data.sentiment_table("headlines_scored", usecols=SCORED_COLS)
    if not data.exists(HEADLINES_RAW):
        st.caption(f"`{HEADLINES_RAW}` (the Phase 0 headline file) is not in this copy; the explorer reads the "
                   "Phase 7 scored table instead.")
    if scored is None:
        components.missing_data(SCORED, SCORED_HINT)
        extremes = data.sentiment_table("week_extremes")
        if extremes is None:
            components.missing_data(EXTREMES, SCORED_HINT)
        else:
            st.markdown("**Fallback:** the most negative and most positive headlines of each week "
                        f"(`{EXTREMES}`).")
            weeks = sorted(extremes["week_end"].unique())
            wk = st.selectbox("Week ending", weeks, index=len(weeks) - 1, key="sent_ex_week")
            ex = extremes[(extremes["week_end"] == wk) & (extremes["score"] == "vader_compound")]
            st.dataframe(ex[["side", "rank", "vader_compound", "adj_compound", "source", "title", "published_utc"]],
                         hide_index=True, width="stretch")
            components.source_caption([EXTREMES], text_flags(), note="titles verbatim, cut at the source")
    else:
        h = scored.copy()
        h["core_chain"] = h["core_chain"].astype(str).str.lower() == "true"
        c1, c2 = st.columns([1.5, 1])
        query = c1.text_input("Search titles", key="sent_hl_search", placeholder="e.g. nickel, Hindalco, duty")
        weeks = sorted(h["week_end"].unique())
        week = c2.selectbox("Week ending", ["All weeks", *weeks], key="sent_hl_week")
        c3, c4, c5, c6 = st.columns([1.1, 1.2, 1.3, 0.9])
        score = c3.radio("Score", ["Raw VADER", "Adjusted"], horizontal=True, key="sent_hl_score")
        classes = c4.multiselect("Class", ["negative", "neutral", "positive"], key="sent_hl_class",
                                 placeholder="All classes")
        by_count = h["source"].value_counts()
        sources = c5.multiselect("Publisher", list(by_count.index), key="sent_hl_source",
                                 format_func=lambda s: f"{s} ({by_count[s]})", placeholder="All publishers")
        core_only = c6.toggle("Aluminium-chain only", value=False, key="sent_hl_core")
        score_col, class_col = (("vader_compound", "vader_class") if score == "Raw VADER"
                                else ("adj_compound", "adj_class"))
        sort = st.radio("Order", ["Most negative first", "Most positive first", "Newest first"], horizontal=True,
                        key="sent_hl_sort")

        view = h
        if query.strip():
            view = view[view["title"].str.contains(query.strip(), case=False, regex=False, na=False)]
        if week != "All weeks":
            view = view[view["week_end"] == week]
        if classes:
            view = view[view[class_col].isin(classes)]
        if sources:
            view = view[view["source"].isin(sources)]
        if core_only:
            view = view[view["core_chain"]]
        if sort == "Newest first":
            view = view.sort_values("published_utc", ascending=False)
        else:
            view = view.sort_values(score_col, ascending=sort == "Most negative first", kind="stable")

        m1, m2, m3 = st.columns(3)
        m1.metric("Headlines shown", f"{len(view):,} of {len(h):,}", border=True)
        m2.metric(f"Mean score shown ({score})", "—" if view.empty else signed(view[score_col].mean(), 3),
                  help="simple mean of the rows shown; the weekly score is the published weekly mean", border=True)
        m3.metric("Publishers shown", f"{view['source'].nunique():,}", border=True)
        st.dataframe(
            view[["week_end", "published_utc", "source", "title", score_col, class_col, "core_chain", "lexicon_hits",
                  "lexicon_subject_caveat", "cites_later_date", "link"]],
            hide_index=True, width="stretch", height=460, column_config={
                "week_end": "week ending", "published_utc": "published (UTC)", "source": "publisher",
                "title": st.column_config.TextColumn("title (verbatim)", width="large"),
                score_col: st.column_config.NumberColumn("score", format="%+.3f"), class_col: "class",
                "core_chain": "aluminium chain", "lexicon_hits": "overlay words hit",
                "lexicon_subject_caveat": "price verb may not refer to metal",
                "cites_later_date": "cites a later date",
                "link": st.column_config.LinkColumn("link", display_text="open", help="Google News redirect")})
        components.source_caption(
            [SCORED], text_flags(),
            note="titles are the publishers' verbatim text from Google News RSS (feed metadata only, no article "
                 "bodies); the link column points at Google News, the app itself fetches nothing")
        with st.expander("The price-direction overlay lexicon", icon=":material/spellcheck:"):
            lex = data.sentiment_table("lexicon")
            if lex is None:
                components.missing_data(LEXICON)
            else:
                action = st.multiselect("Action", sorted(lex["action"].unique()), key="sent_lex_action",
                                        placeholder="All actions")
                lv = lex[lex["action"].isin(action)] if action else lex
                st.dataframe(lv.sort_values("n_headlines_hit", ascending=False), hide_index=True, width="stretch")
                components.source_caption(
                    [LEXICON], {"lexicon (sent_domain_lexicon)": text_flags()["price-direction lexicon"]},
                    note=f"{int(S.get('n_lexicon_words_added', 0))} words added, "
                         f"{int(S.get('n_lexicon_words_flipped', 0))} flipped, "
                         f"{int(S.get('n_lexicon_words_removed', 0))} removed; they changed the class of "
                         f"{int(S.get('n_headlines_class_changed_by_lexicon', 0))} headlines" if S else None)

# ------------------------------------------------------------------------------------------------ caveats
with tab_caveats:
    components.what_it_tells(DOC, expanded=True)
    components.what_it_tells(DOC, heading="Biases and limitations")
    components.what_it_tells(DOC, heading="Why raw VADER has the wrong sign")
    components.what_it_tells(DOC, heading="Why this page exists, and what it is not")
    if data.exists(NEWS_NOTES):
        st.caption(f"How the headlines were collected (queries, weekly windows, terms-of-use note): `{NEWS_NOTES}`.")
