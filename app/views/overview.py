"""Overview: the desk, its headline P&L with its band, and the risk findings at a glance.

Every number on this page is a fact from `data.headline_facts()`, i.e. `desk.reporting.one_pager`'s own computation
over the published tables, so the page and outputs/reports/one_pager.pdf cannot disagree. The charts read
attribution_daily.csv and book_exposures_daily.csv directly.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app.lib import charts, components, data, docs_text  # noqa: E402
from app.lib.components import Kpi  # noqa: E402
from desk import HORIZON_END  # noqa: E402
from desk.reporting.style import PALETTE, PNL_BUCKETS  # noqa: E402

M = 1e6
ONE_PAGER_MD = f"{data.REPORTS}/one_pager.md"
ATT = data.table_rel("attribution_daily")
EXPO = data.table_rel("book_exposures_daily")
ANCHOR = "domestic_anchor_premium_inr_t"

spec = components.PAGE["overview"]
components.sim_banner()
components.page_header("Virtual Metals Trading Desk", spec.blurb, spec.spec_rows)

pitch = docs_text.lead_paragraph(ONE_PAGER_MD)
if pitch:
    st.markdown(docs_text.for_streamlit(pitch, ONE_PAGER_MD))
    st.caption(f"From `{ONE_PAGER_MD}`, the generated one-page summary.")
else:
    components.missing_data(ONE_PAGER_MD)

facts = data.headline_facts()
t = facts.t
if not facts.complete and (facts.missing or facts.problems):
    with st.expander(f"Partial copy: {len(facts.missing)} input file(s) missing, {len(facts.problems)} part(s) not "
                     "computed; the figures below use the tables that are present"):
        for rel in facts.missing:
            components.missing_data(rel)
        if facts.problems:
            st.caption("Not computed here: " + "; ".join(p.split(":")[0] for p in facts.problems) + ".")

# ------------------------------------------------------------------------------------------------ headline + desk
components.pnl_headline(facts)

if facts.has("n_trades", "book_mt", "book_boxes"):
    kpis = [
        Kpi("Tickets", t("n_trades"), f"traded {t('first_td')} to {t('last_td')}; "
                                      f"{t('n_suppliers')} suppliers, {t('n_buyers')} buyers (all SIM)"),
        Kpi("Tonnes", f"{t('book_mt')} MT"),
        Kpi("Containers", t("book_boxes")),
        Kpi("Grades · lanes", f"{t('n_grades')} · {t('n_lanes')}", f"{t('grades')}; {t('lanes')}"),
        Kpi("Eligible cases", f"{t('n_elig_cases')} of {t('n_cases')}",
            f"in-window week × grade × lane cases that pass the ex-ante rule (CONTRACTS §5a); {t('n_open_base')} "
            f"open on the base screen alone. {t('elig_pass')} of {t('elig_n')} tickets pass it."),
        Kpi("Window, 2022", "Mar–Aug", f"{t('window_start')} to {t('window_end')}; P&L runs to the horizon "
                                      f"{t('horizon_end')}, when every cashflow has settled"),
    ]
    components.kpi_row(kpis)
    components.source_caption(["trade_book", "parity_weekly", "trade_eligibility_check"], ["SIM"],
                              note="tickets and counterparties are fictional; the rule was declared before any parity "
                                   "result existed")
elif components.available(data.table_rel("trade_book")):
    st.info("Not computed in this copy: the desk's key figures need the headline facts above.", icon=":material/info:")

# ------------------------------------------------------------------------------------------------ charts
left, right = st.columns([1.15, 1], gap="large")
with left:
    st.subheader("Equity curve")
    att = data.attribution_daily(usecols=["date", "trade_id", "cum_pnl_inr"])
    if att is None:
        components.missing_data(ATT)
    else:
        book, _ = data.split_book(att)
        df = book[["date", "cum_pnl_inr"]].copy()
        df["cum_m"] = df["cum_pnl_inr"] / M
        series = {"cum_m": "Cumulative book P&L"}
        split = st.toggle("Split into realised cash and unrealised mark", value=False, key="overview_split",
                          help="Realised P&L + funding swings with purchase and sale cash, so it dwarfs the band.")
        expo = data.book_exposures_daily(["date", "scope", "mtm_inr", "cum_pnl_inr"]) if split else None
        if expo is not None:
            b = expo[expo["scope"] == "book"][["date", "mtm_inr", "cum_pnl_inr"]]
            df = df.merge(b.rename(columns={"cum_pnl_inr": "cum_expo_inr"}), on="date", how="left")
            df["real_m"] = (df["cum_expo_inr"] - df["mtm_inr"]) / M
            df["unreal_m"] = df["mtm_inr"] / M
            series |= {"real_m": "Realised P&L + funding", "unreal_m": "Unrealised mark"}
        fig = charts.line_chart(
            df, "date", series, y_title="₹ million", events=data.event_markers(), height=440,
            colors={"cum_m": PALETTE["pnl"], "real_m": PALETTE["gain"], "unreal_m": PALETTE["neutral"]},
            dashes={"real_m": "dash", "unreal_m": "dot"})
        has_band = {"band_lo", "band_hi", "book_pnl"} <= facts.num.keys() and "band_sign_robust" in facts.flags
        if has_band:
            robust = facts.flags["band_sign_robust"]
            charts.band_marker(fig, HORIZON_END, facts.num["band_lo"] / M, facts.num["band_hi"] / M,
                               point=facts.num["book_pnl"] / M, label=f"anchor-premium band at {t('horizon_end')}",
                               text_lo=t("band_lo"), text_hi=t("band_hi"),
                               text_point=f"headline {t('book_pnl')}" + ("" if robust else " · not sign-robust"))
        charts.show(fig, key="overview_equity")
        notes = ["the red bar is the book re-priced across the registered anchor-premium grid, drawn at the horizon"
                 if has_band else "the anchor-premium band could not be computed in this copy, so it is not drawn"]
        if expo is not None:
            notes.append("realised P&L + funding = cumulative P&L − unrealised mark (the engine's identity)")
        components.source_caption([ATT, components.BAND_TABLE] + ([EXPO] if expo is not None else []),
                                  {"anchor premium": data.param_flag(ANCHOR) or "ASSUMPTION"}, note="; ".join(notes))
        if split and expo is None:
            components.missing_data(EXPO)

with right:
    st.subheader("Where it came from")
    if not facts.buckets:
        components.available(ATT)
    else:
        vals = [facts.buckets.get(k, 0.0) for k in PNL_BUCKETS]
        fig = charts.bar_chart([charts.bucket_label(k, wrap=True) for k in PNL_BUCKETS], [v / M for v in vals],
                               colors=[charts.bucket_color(k) for k in PNL_BUCKETS],
                               value_title="₹ million, lifetime to the horizon",
                               text=[components.inr_m(v, sign=True) for v in vals], height=440)
        charts.show(fig, key="overview_buckets")
        if facts.has("nd_share", "residual"):
            st.caption(f"Deal margin is {t('nd_share')} of the total and comes from the desk's own sale-pricing rule "
                       f"on the anchor premium; residual {t('residual')}.")
        flags = data.series_flags()
        components.source_caption(
            [ATT],
            {"(0) anchor premium": data.param_flag(ANCHOR) or "ASSUMPTION",
             "(b) MCX series, basis zero by construction": flags.get("mcx_al_m1_inr_kg", "PROXY"),
             "(c) grade factors, reconstructed": data.param_flag("grade_factor_mix") or "ASSUMPTION",
             "(d) freight levels": flags.get("freight_jea_nsa_usd_t", "ASSUMPTION")})

# ------------------------------------------------------------------------------------------------ risk in one glance
st.subheader("Risk in one glance")
if facts.failed_claims:
    st.error("These tables no longer support some of the one-pager's claims: " + "; ".join(facts.failed_claims)
             + ". Rebuild P6 (`DESK_OFFLINE=1 .venv/bin/python run_all.py --only P6`) before quoting them.",
             icon=":material/error:")
elif facts.text and not facts.claims_checked:
    st.warning("The one-pager's qualitative claims could not be re-tested in this copy; read the numbers, not the "
               "wording.", icon=":material/warning:")


def card(title: str, keys: tuple[str, ...], metric: tuple[str, str, str | None], body: str, files: list[str],
         flags: dict[str, str] | list[str] | None = None) -> None:
    with st.container(border=True):
        st.markdown(f"**{title}**")
        if not facts.has(*keys):
            absent = [f if "/" in f else data.table_rel(f) for f in files]
            if components.available(*absent):
                st.info("Not computed in this copy.", icon=":material/info:")
            return
        st.metric(metric[0], metric[1], help=metric[2])
        st.markdown(docs_text.escape_streamlit(body))
        components.source_caption(files, flags)


row1 = st.columns(3)
row2 = st.columns(3)
with row1[0]:
    card("Daily 95 % VaR: GARCH(1,1) vs 250-day history",
         ("var_mean_g", "var_mean_h", "var_n", "pctl", "h_cross", "lead", "cf_start", "g_cf", "h_cf", "h60_cf",
          "beta_w", "var_beta_w"),
         (f"Mean book VaR over {t('var_n')} position days", f"{t('var_mean_g')} vs {t('var_mean_h')}",
          "GARCH(1,1) against the 250-day historical window"),
         f"Mixed, not the win the spec expected. On the declared {t('pctl')}-percentile alert rule the 250-day window "
         f"crossed first ({t('h_cross')}, {t('lead')} trading days before GARCH); into the {t('cf_start')} crash "
         f"fortnight GARCH ({t('g_cf')}) sat below both windows ({t('h_cf')} at 250 days, {t('h60_cf')} at 60). "
         f"At the MCX mirror's weekly beta ({t('beta_w')}) mean GARCH VaR is {t('var_beta_w')}.",
         ["var_summary", "var_lead_lag", "var_mcx_beta"], {"MCX series (unit beta by construction)": "PROXY"})
with row1[1]:
    card("Kupiec backtest", ("exc_g", "exc_h", "exc_exp", "kmin", "kmax", "var_n"),
         ("Exceptions: GARCH / 250-day", f"{t('exc_g')} / {t('exc_h')}", f"{t('exc_exp')} expected"),
         f"{t('exc_exp')} exceptions expected over {t('var_n')} days. Neither method is rejected, but the test "
         f"accepts {t('kmin')} to {t('kmax')} here, so it cannot separate them.",
         ["kupiec"])
with row1[2]:
    card("Monte Carlo VaR and stresses",
         ("mc_ath", "ath1_date", "mc_h", "n_paths", "mc_apr", "apr_date", "mc_jul", "jul_date", "mc_apr_basis", "mc_jul_basis",
          "beyond"),
         (f"99 % {t('mc_h')}-day VaR on {t('ath1_date')}", t("mc_ath"),
          f"{t('n_paths')} paths; no MCX hedge on the book yet on that date"),
         f"{t('mc_apr')} on {t('apr_date')}, {t('mc_jul')} on {t('jul_date')}; an MCX basis factor lifts the last two "
         f"to {t('mc_apr_basis')} and {t('mc_jul_basis')}. Beyond every path: {t('beyond')}.",
         ["mc_summary", "mc_stress_scenarios"], {"BIS-QCO hold stress": "HYPOTHETICAL", "buyer default": "SIM"})
with row2[0]:
    card("Credit scoring (logistic)",
         ("credit", "rjk", "rjk_contracted", "rjk_limit", "rjk_new_limit", "n_synth"),
         ("Riskiest buyer", t("rjk"), "ranked by modelled annual PD"),
         f"{t('credit')}. {t('rjk')}'s contracted exposure reached {t('rjk_contracted')} its line, which the model "
         f"cuts from {t('rjk_limit')} to {t('rjk_new_limit')}. Illustrative: fitted on {t('n_synth')} synthetic "
         "buyer-quarters, with profiles written by the book's author.",
         ["credit_scores", "credit_synthetic_training_data"], {"training data": "SYNTHETIC", "buyers": "SIM"})
with row2[1]:
    card("Liquidity and margin",
         ("funding_peak", "funding_date", "wc_limit", "fb_days", "wc_step", "lc_peak", "lc_limit", "lc_days",
          "im_peak", "im_date"),
         ("Peak funding need", t("funding_peak"), f"on {t('funding_date')}"),
         f"The book did not fit its bank lines: {t('funding_peak')} on {t('funding_date')} against a {t('wc_limit')} "
         f"line sized on the plan's average balance, {t('fb_days')} days over (none on a line one {t('wc_step')} "
         f"step higher). LCs peaked at {t('lc_peak')} against {t('lc_limit')} ({t('lc_days')} days over). Peak MCX "
         f"initial margin {t('im_peak')} ({t('im_date')}).",
         ["margin_liquidity_summary", "margin_liquidity_limit_grid"],
         {"bank lines": data.param_flag("liq_fb_wc_limit_inr") or "ASSUMPTION"})
with row2[2]:
    card("Sentiment overlay (VADER)", ("n_sig", "n_lead", "n_headlines", "n_weeks"),
         ("Significant lead tests", f"{t('n_sig')} of {t('n_lead')}", "naive 5 % level"),
         f"{t('n_headlines')} real headlines over {t('n_weeks')} weeks: no evidence that headline tone led LME. The "
         f"March spike could not be tested, and {t('n_weeks')} weeks can only rule out a strong lead.",
         ["sentiment_summary"], {"dated headlines": "DIRECT"})

# ------------------------------------------------------------------------------------------------ where to go
st.subheader("Where to go next")
cols = st.columns(2, gap="large")
for i, p in enumerate(q for q in components.PAGES if q.key != "overview"):
    with cols[i % 2]:
        components.page_link(p.key)
        st.caption(p.blurb)

# ------------------------------------------------------------------------------------------------ downloads
st.subheader("Take it with you")
d1, d2, d3 = st.columns(3, gap="large")
with d1:
    components.download_button(f"{data.REPORTS}/one_pager.pdf", "One-page summary (PDF)")
    st.caption("The desk, the headline with its band and the risk findings on one A4 page.")
with d2:
    components.download_button("README.md", "README (Markdown)")
    st.caption("Method, pipeline, re-run steps, verification checklist and caveats.")
with d3:
    components.download_button(data.WORKBOOK, "Excel workbook (XLSX)")
    recon = data.recon_status()
    detail = (f"{recon.n_recalculated:,} formula cells recalculated outside Excel, {recon.n_check_failures} failed "
              "checks" if recon.status == "VERIFIED" and recon.n_recalculated is not None else recon.reason)
    st.caption(f"Formula-driven parity, book and P&L attribution. Reconciliation {components.recon_badge(recon)}: "
               f"{docs_text.escape_streamlit(detail)}")

components.what_it_tells(f"{data.DOCS}/30_mtm_attribution.md")
