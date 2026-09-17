"""Market data: LME, USD/INR and rates, the MCX proxy and freight through 2022, each series with its provenance flag.

Reads data/processed/market_daily.csv (the Phase 0 panel), fx_rates_daily.csv, freight_weekly.csv,
series_provenance.csv and the third-party MCX mirror extract in data/interim/. The public export leaves out the panel,
lme_daily.csv, freight_weekly.csv and the mirror; the page then says so and, where a published output table carries
the same series on the weekly parity dates (term_structure_weekly.csv, parity_weekly.csv), shows that instead, labelled
as the weekly fallback. The key window facts come from adverse_event_windows.csv (the pipeline's own event
definitions); the "at a glance" table is first / last / min / max of the panel columns over the chosen dates.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import datetime as dt  # noqa: E402

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.lib import charts, components, data, docs_text  # noqa: E402
from app.lib.components import Kpi  # noqa: E402
from desk import HISTORY_START, PANEL_END, WINDOW_END, WINDOW_START  # noqa: E402
from desk.reporting.style import PALETTE  # noqa: E402

MKT = data.processed_rel("market_daily")
LME = data.processed_rel("lme_daily")
FX = data.processed_rel("fx_rates_daily")
FREIGHT = data.processed_rel("freight_weekly")
PROV = data.processed_rel("series_provenance")
MIRROR = "data/interim/mcx_thirdparty_commoditieschart_2017_2022.csv"
EVENTS = data.table_rel("adverse_event_windows")
TS_WEEKLY = data.table_rel("term_structure_weekly")
PARITY = data.table_rel("parity_weekly")
NOTES = f"{data.DOCS}/research/market_data_notes.md"
FREIGHT_NOTES = f"{data.DOCS}/research/freight_notes.md"
DICTIONARY = f"{data.DOCS}/00_data_dictionary.md"
PARITY_DOC = f"{data.DOCS}/10_parity_model.md"

MIRROR_HINT = ("The public export leaves it out because it republishes third-party MCX closes. Rebuild it by running "
               "the Phase 0 fetchers online: `.venv/bin/python run_all.py --only P0` (without `DESK_OFFLINE`; the "
               "stage `desk.data.fetch_mcx_mirror` writes it).")
UNITS = {"usd_per_mt": "USD/MT", "mt": "MT", "inr_per_usd": "₹ per USD", "rate_pa": "% p.a.", "inr_per_kg": "₹/kg"}
MKT_COLS = ["date", "lme_cash_usd_t", "lme_3m_usd_t", "lme_cash_3m_spread_usd_t", "lme_stock_mt", "usdinr",
            "fwd_premium_3m_pa", "rbi_repo_pa", "mcx_al_m1_inr_kg", "mcx_al_m2_inr_kg", "freight_jea_nsa_usd_t",
            "freight_usec_mun_usd_t"]
FX_COLS = ["date", "usdinr", "usdinr_fwd_3m", "rbi_repo_pa", "fed_funds_upper_pa", "inr_rate_3m_pa", "usd_rate_3m_pa",
           "fwd_premium_3m_pa"]
LABELS = {
    "lme_cash_usd_t": "LME cash", "lme_3m_usd_t": "LME 3M", "lme_cash_3m_spread_usd_t": "Cash–3M spread",
    "lme_stock_mt": "LME stocks", "usdinr": "USD/INR (ECB cross)", "usdinr_fwd_3m": "USD/INR 3M forward",
    "fwd_premium_3m_pa": "3M forward premium", "rbi_repo_pa": "RBI repo", "fed_funds_upper_pa": "Fed funds upper",
    "inr_rate_3m_pa": "INR 3M rate", "usd_rate_3m_pa": "USD 3M rate", "mcx_al_m1_inr_kg": "MCX Al M1 (proxy)",
    "mcx_al_m2_inr_kg": "MCX Al M2 (proxy)", "freight_jea_nsa_usd_t": "Freight Jebel Ali → Nhava Sheva",
    "freight_usec_mun_usd_t": "Freight US East Coast → Mundra",
}
RATE_COLS = {"fwd_premium_3m_pa", "rbi_repo_pa", "fed_funds_upper_pa", "inr_rate_3m_pa", "usd_rate_3m_pa"}

spec = components.PAGE["market"]
components.sim_banner()
components.page_header(spec.title, spec.blurb, spec.spec_rows)

prov = data.series_provenance()
flags = data.series_flags()


def flag(col: str, default: str = "PROXY") -> str:
    return flags.get(col, default)


def unit(col: str) -> str:
    if prov is not None:
        hit = prov.loc[prov["column"] == col, "unit"]
        if not hit.empty:
            return UNITS.get(str(hit.iloc[0]), str(hit.iloc[0]))
    return ""


def quote(doc_rel: str, heading: str, marker: str, label: str, mode: str = "paragraph") -> None:
    """Expander quoting one paragraph, list item or trailing block of a doc section verbatim.

    mode "paragraph": the lines from the one containing `marker` to the next blank line; "item": one list item;
    "rest": from the marker to the end of the section.
    """
    sec = docs_text.section(doc_rel, heading)
    lines = sec.body.splitlines() if sec else []
    start = next((i for i, line in enumerate(lines) if marker in line), None)
    if start is None:
        if not data.exists(doc_rel):
            components.missing_data(doc_rel)
        else:
            st.info(f"`{doc_rel}` no longer has the passage “{marker}”.", icon=":material/info:")
        return
    block = [lines[start]]
    for line in lines[start + 1:]:
        if mode != "rest" and (not line.strip() or (mode == "item" and line.lstrip().startswith(("- ", "* ")))):
            break
        block.append(line)
    with st.expander(label, icon=":material/menu_book:"):
        st.markdown(docs_text.for_streamlit("\n".join(block).strip(), doc_rel))
        where = f" §{sec.number}" if sec.number else f" “{sec.title}”"
        st.caption(f"Quoted from `{doc_rel}`{where}, not rewritten for the app.")


def in_range(df: pd.DataFrame, col: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    s = df[col].astype(str).str[:10]
    return df[(s >= start.isoformat()) & (s <= end.isoformat())].reset_index(drop=True)


def frame(fig: go.Figure, start: dt.date, end: dt.date) -> go.Figure:
    """Fix the x-axis to the chosen dates (window shading and markers must not stretch it)."""
    return fig.update_xaxes(range=[pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(hours=12)])


def events_in(start: dt.date, end: dt.date) -> list[tuple[str, str]]:
    return [(d, lab) for d, lab in data.event_markers() if start.isoformat() <= d[:10] <= end.isoformat()]


# ------------------------------------------------------------------------------------------------ takeaway + key facts
ev = data.adverse_event_windows()
mkt = data.market_daily(MKT_COLS)


def event(name: str) -> pd.Series | None:
    if ev is None:
        return None
    hit = ev[ev["event"] == name]
    return None if hit.empty else hit.iloc[0]


crash, fortnight, inr_slide = event("E1_LME_CRASH"), event("E1_CRASH_FORTNIGHT"), event("E2_INR_DEPRECIATION")
if crash is not None and inr_slide is not None:
    counts = prov["flag"].value_counts() if prov is not None else None
    split = (f" Of the panel's {len(prov)} columns, {counts.get('DIRECT', 0)} are DIRECT, {counts.get('PROXY', 0)} "
             f"PROXY and {counts.get('ASSUMPTION', 0)} ASSUMPTION." if counts is not None else "")
    panel_high = ""
    if mkt is not None and float(mkt["lme_cash_usd_t"].max()) == float(crash["start_value"]):
        panel_high = f" (also the {HISTORY_START.year}–{PANEL_END.year} panel high)"
    st.markdown(
        f"**LME cash made its record close of USD {components.num(crash['start_value'], 1)}/t on "
        f"{components.day(crash['start'], True)}{panel_high} and fell {components.pct(-crash['change_frac'])} to USD "
        f"{components.num(crash['end_value'], 1)}/t by {components.day(crash['end'], True)}, while the rupee weakened "
        f"{components.pct(inr_slide['change_frac'])} ({components.num(inr_slide['start_value'], 4)} → "
        f"{components.num(inr_slide['end_value'], 4)} per USD, {components.day(inr_slide['start'])} to "
        f"{components.day(inr_slide['end'], True)}).** Only the LME series are DIRECT observations; USD/INR "
        f"and the MCX price are proxies and freight levels are assumptions, and every chart below says which.{split}")
    kpis = [
        Kpi("LME cash record close", f"USD {components.num(crash['start_value'], 1)}/t",
            f"{components.day(crash['start'], True)}; {crash['rule']} ({flag('lme_cash_usd_t', 'DIRECT')})"),
        Kpi("Peak to crash low", components.pct(crash["change_frac"]),
            f"USD {components.num(crash['end_value'], 1)}/t on {components.day(crash['end'], True)}; "
            f"{int(crash['n_panel_days'])} panel days"),
    ]
    if fortnight is not None:
        kpis.append(Kpi("Worst crash fortnight", components.pct(fortnight["change_frac"]),
                        f"{components.day(fortnight['start'])} to {components.day(fortnight['end'], True)}: "
                        f"{fortnight['rule']}"))
    kpis.append(Kpi("USD/INR low to high", components.pct(inr_slide["change_frac"], sign=True),
                    f"{components.num(inr_slide['start_value'], 4)} on {components.day(inr_slide['start'])} to "
                    f"{components.num(inr_slide['end_value'], 4)} on {components.day(inr_slide['end'], True)}; "
                    f"ECB cross ({flag('usdinr')}). {inr_slide['note']}"))
    components.kpi_row(kpis)
    components.source_caption([EVENTS], {"LME cash": flag("lme_cash_usd_t", "DIRECT"), "USD/INR": flag("usdinr")},
                              note="event dates are the pipeline's own rule-based definitions (column `rule`)")
else:
    components.available(EVENTS)

# ------------------------------------------------------------------------------------------------ date range
PRESETS = {
    "2022 (the trading year)": (dt.date(WINDOW_START.year, 1, 1), PANEL_END),
    "Mar–Aug 2022 window": (WINDOW_START, WINDOW_END),
    f"{HISTORY_START.year}–{PANEL_END.year} panel": (HISTORY_START, PANEL_END),
    "Custom": None,
}
c1, c2 = st.columns([1.6, 1], gap="large")
with c1:
    preset = st.radio("Dates shown", list(PRESETS), index=0, horizontal=True, key="market_range",
                      help="The Mar–Aug 2022 headline window is shaded on every chart.")
with c2:
    if PRESETS[preset] is None:
        picked = st.date_input("From – to", value=(WINDOW_START, WINDOW_END), min_value=HISTORY_START,
                               max_value=PANEL_END, key="market_dates", format="YYYY-MM-DD")
        start, end = (picked if isinstance(picked, tuple) and len(picked) == 2 else (WINDOW_START, WINDOW_END))
    else:
        start, end = PRESETS[preset]
        st.caption(f"Showing {components.day(start, True)} to {components.day(end, True)}.")

tab_lme, tab_fx, tab_mcx, tab_freight, tab_glance, tab_prov = st.tabs(
    ["LME", "USD/INR & rates", "MCX (proxy)", "Freight", "At a glance", "Provenance"])

# ------------------------------------------------------------------------------------------------ LME
with tab_lme:
    lme_src = MKT if mkt is not None else LME
    lme = mkt if mkt is not None else data.lme_daily(["date", "lme_cash_usd_t", "lme_3m_usd_t",
                                                       "lme_cash_3m_spread_usd_t", "lme_stock_mt"])
    weekly = False
    if lme is None:
        components.missing_data(MKT)
        ts = data.term_structure("weekly", ["value_date", "lme_cash_usd_t", "lme_3m_usd_t", "lme_cash_3m_spread_usd_t"])
        if ts is None:
            components.missing_data(TS_WEEKLY)
        else:
            st.caption("Weekly fallback: the LME official prices on the parity value dates, from the published "
                       "term-structure table (no stocks in this copy).")
            lme, lme_src, weekly = ts.rename(columns={"value_date": "date"}), TS_WEEKLY, True
    if lme is not None:
        d = in_range(lme, "date", start, end)
        if d.empty:
            st.info("No LME rows in the chosen dates.", icon=":material/info:")
        else:
            lme_flag = {"LME official cash, 3M": flag("lme_cash_usd_t", "DIRECT")}
            st.subheader("Official cash and 3-month")
            fig = charts.line_chart(d, "date", {"lme_cash_usd_t": "Cash (official)", "lme_3m_usd_t": "3M (official)"},
                                    colors={"lme_cash_usd_t": PALETTE["lme"], "lme_3m_usd_t": PALETTE["mcx"]},
                                    dashes={"lme_3m_usd_t": "dot"}, y_title=unit("lme_cash_usd_t") or "USD/MT",
                                    events=events_in(start, end), height=380, hover_format=",.1f")
            charts.show(frame(fig, start, end), key="market_lme_px")
            components.source_caption([lme_src], lme_flag, note="Westmetall republication of LME official prices"
                                      + ("; weekly parity value dates" if weekly else ""))

            st.subheader("Cash–3M spread: backwardation and contango")
            spread = d["lme_cash_3m_spread_usd_t"]
            xs = pd.to_datetime(d["date"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=xs, y=spread.clip(lower=0), name="backwardation (cash above 3M)", mode="lines",
                                     line=dict(width=0.6, color=PALETTE["loss"]), fill="tozeroy",
                                     hovertemplate="%{y:,.1f}<extra>backwardation</extra>"))
            fig.add_trace(go.Scatter(x=xs, y=spread.clip(upper=0), name="contango (cash below 3M)", mode="lines",
                                     line=dict(width=0.6, color=PALETTE["gain"]), fill="tozeroy",
                                     hovertemplate="%{y:,.1f}<extra>contango</extra>"))
            charts.shade_window(fig)
            charts.finish(fig, height=280, y_title=f"Cash − 3M, {unit('lme_cash_3m_spread_usd_t') or 'USD/MT'}")
            charts.show(frame(fig, start, end), key="market_lme_spread")
            n_b, n_c = int((spread > 0).sum()), int((spread < 0).sum())
            n_f = len(spread) - n_b - n_c
            period = "weeks" if weekly else "days"
            components.source_caption(
                [lme_src], {"spread": flag("lme_cash_3m_spread_usd_t", "DIRECT")},
                note=f"in the chosen dates: backwardation on {n_b} {period}, contango on {n_c}, flat on {n_f}; mean "
                     f"{components.num(spread.mean(), 2)} USD/MT (positive = backwardation)")

            if "lme_stock_mt" in d:
                st.subheader("LME stocks")
                fig = charts.line_chart(d, "date", {"lme_stock_mt": "LME aluminium stocks"},
                                        colors={"lme_stock_mt": PALETTE["neutral"]}, y_title=unit("lme_stock_mt") or "MT",
                                        height=260, hover_format=",.0f")
                fig.update_layout(showlegend=False)
                charts.show(frame(fig, start, end), key="market_lme_stocks")
                components.source_caption([lme_src], {"stocks": flag("lme_stock_mt", "DIRECT")})

# ------------------------------------------------------------------------------------------------ USD/INR and rates
with tab_fx:
    fx = data.fx_rates_daily(FX_COLS)
    if fx is None:
        components.missing_data(FX)
    else:
        d = in_range(fx, "date", start, end)
        if d.empty:
            st.info("No USD/INR rows in the chosen dates.", icon=":material/info:")
        else:
            st.subheader("USD/INR spot and 3-month forward")
            fig = charts.line_chart(d, "date", {"usdinr": "Spot: ECB EUR/INR ÷ EUR/USD",
                                                "usdinr_fwd_3m": "3M forward (covered interest parity)"},
                                    colors={"usdinr": PALETTE["fx"], "usdinr_fwd_3m": PALETTE["neutral"]},
                                    dashes={"usdinr_fwd_3m": "dot"}, y_title=unit("usdinr") or "₹ per USD",
                                    events=[e for e in events_in(start, end) if "INR" in e[1]], height=360,
                                    hover_format=",.4f")
            charts.show(frame(fig, start, end), key="market_fx")
            components.source_caption([FX], {"spot (stands in for the RBI reference rate)": flag("usdinr"),
                                             "3M forward": flag("usdinr_fwd_3m")},
                                      note="ECB reference-rate calendar; the panel carries it onto LME days")

            st.subheader("Policy rates and the forward premium")
            show_mm = st.toggle("Add the 3M money-market rates behind the premium (PROXY)", value=False,
                                key="market_mm_rates")
            r = d.assign(**{c: d[c] * 100 for c in RATE_COLS})
            series = {"rbi_repo_pa": "RBI repo (step path)", "fed_funds_upper_pa": "Fed funds upper bound (step path)",
                      "fwd_premium_3m_pa": "USD/INR 3M forward premium"}
            if show_mm:
                series |= {"inr_rate_3m_pa": "INR 3M rate", "usd_rate_3m_pa": "USD 3M rate (T-bill)"}
            fig = charts.line_chart(r, "date", series, colors={"rbi_repo_pa": PALETTE["fx"],
                                                               "fed_funds_upper_pa": PALETTE["lme"],
                                                               "fwd_premium_3m_pa": PALETTE["mcx"],
                                                               "inr_rate_3m_pa": PALETTE["fx"],
                                                               "usd_rate_3m_pa": PALETTE["lme"]},
                                    dashes={"inr_rate_3m_pa": "dot", "usd_rate_3m_pa": "dot"}, y_title="% p.a.",
                                    height=360, hover_format=".2f")
            fig.update_traces(line_shape="hv", selector=dict(name=series["rbi_repo_pa"]))
            fig.update_traces(line_shape="hv", selector=dict(name=series["fed_funds_upper_pa"]))
            charts.show(frame(fig, start, end), key="market_rates")
            rate_flags = {"RBI repo": flag("rbi_repo_pa", "DIRECT"), "Fed upper": flag("fed_funds_upper_pa", "DIRECT"),
                          "forward premium": flag("fwd_premium_3m_pa")}
            if show_mm:
                rate_flags |= {"INR / USD 3M rates": flag("inr_rate_3m_pa")}
            components.source_caption([FX, f"{data.PARAMS}/rates.yaml"], rate_flags,
                                      note="policy steps are the register's dated paths, effective on the announcement "
                                           "(RBI) or effective date (Fed)")
            quote(NOTES, "Rates and forwards", "What the forward columns tell you",
                  "What the forward columns do and don't tell you", mode="item")

# ------------------------------------------------------------------------------------------------ MCX
with tab_mcx:
    st.caption("MCX Aluminium could not be downloaded (every MCX page returned HTTP 403), so the panel carries an "
               "import-parity PROXY: duty-paid LME cash × USD/INR, plus INR carry to each contract's expiry. A "
               "third-party mirror of MCX closes is shown only as a labelled comparison.")
    mirror = data.read_csv(MIRROR)
    if mkt is not None:
        d = in_range(mkt, "date", start, end)
        mcx_src, weekly = MKT, False
    else:
        components.missing_data(MKT)
        pw = data.parity_weekly(["week_end", "value_date", "grade", "lane", "mcx_contract", "mcx_anchor_inr_kg"])
        d = None
        if pw is None:
            components.missing_data(PARITY)
        else:
            one = pw[pw["grade"] == pw["grade"].iloc[0]]
            wide = one.pivot_table(index="value_date", columns="mcx_contract", values="mcx_anchor_inr_kg").reset_index()
            wide = wide.rename(columns={"value_date": "date", "M1": "mcx_al_m1_inr_kg", "M2": "mcx_al_m2_inr_kg"})
            d = in_range(wide, "date", start, end)
            mcx_src, weekly = PARITY, True
            st.caption("Weekly fallback: the MCX proxy on the parity value dates, from the published parity table "
                       "(M1 anchors Jebel Ali → Nhava Sheva, M2 US East Coast → Mundra).")
    if d is not None and d.empty:
        st.info("No MCX rows in the chosen dates.", icon=":material/info:")
    elif d is not None:
        overlay = False
        if mirror is None:
            components.missing_data(MIRROR, MIRROR_HINT)
        else:
            overlay = st.toggle("Overlay the third-party MCX mirror (comparison only, PROXY)", value=True,
                                key="market_mirror")
        plot = d[["date", "mcx_al_m1_inr_kg", "mcx_al_m2_inr_kg"]].copy()
        series = {"mcx_al_m1_inr_kg": "Proxy M1 (near month)", "mcx_al_m2_inr_kg": "Proxy M2 (next month)"}
        if overlay:
            mir = in_range(mirror, "date", start, end)
            plot = plot.merge(mir, on="date", how="outer").sort_values("date")
            series |= {"m1_close_inr_kg": "Mirror M1 close (third-party)", "m2_close_inr_kg": "Mirror 2M close (third-party)"}
        fig = charts.line_chart(plot, "date", series,
                                colors={"mcx_al_m1_inr_kg": PALETTE["mcx"], "mcx_al_m2_inr_kg": "#f4b183",
                                        "m1_close_inr_kg": PALETTE["neutral"], "m2_close_inr_kg": "#b7b7b7"},
                                dashes={"m1_close_inr_kg": "dot", "m2_close_inr_kg": "dot"},
                                y_title=unit("mcx_al_m1_inr_kg") or "₹/kg", events=events_in(start, end), height=380,
                                hover_format=",.2f")
        fig.update_traces(connectgaps=True)
        fig.update_layout(margin=dict(t=56))       # four legend entries above the stacked event labels
        charts.show(frame(fig, start, end), key="market_mcx")
        cap_flags = {"MCX proxy": flag("mcx_al_m1_inr_kg")}
        files = [mcx_src]
        if overlay:
            cap_flags |= {"third-party mirror (provenance unverified)": "PROXY"}
            files.append(MIRROR)
        components.source_caption(files, cap_flags,
                                  note="the mirror is never an input to the parity or the book; see the correlation "
                                       "study on the Trade finder page" + ("; weekly parity value dates" if weekly else ""))

        if crash is not None and overlay and not weekly:
            on = plot[plot["date"] == str(crash["start"])[:10]]
            if not on.empty and pd.notna(on["m1_close_inr_kg"].iloc[0]):
                p, m = float(on["mcx_al_m1_inr_kg"].iloc[0]), float(on["m1_close_inr_kg"].iloc[0])
                st.markdown(f"On the LME record close ({components.day(crash['start'], True)}) the proxy M1 was "
                            f"₹{components.num(p, 2)}/kg against the mirror's ₹{components.num(m, 2)}/kg "
                            f"({components.pct(p / m - 1, sign=True)}): the proxy follows LME one-for-one, so it "
                            "overshoots in a spike.")

        st.subheader("M2 − M1: proxy carry against the mirror")
        sp = plot.assign(proxy_spread=plot["mcx_al_m2_inr_kg"] - plot["mcx_al_m1_inr_kg"])
        series = {"proxy_spread": "Proxy M2 − M1"}
        if overlay:
            sp = sp.assign(mirror_spread=sp["m2_close_inr_kg"] - sp["m1_close_inr_kg"])
            series |= {"mirror_spread": "Mirror 2M − M1"}
        fig = charts.line_chart(sp, "date", series, colors={"proxy_spread": PALETTE["mcx"],
                                                            "mirror_spread": PALETTE["neutral"]},
                                dashes={"mirror_spread": "dot"}, y_title="₹/kg", height=280, hover_format=",.2f")
        fig.update_traces(connectgaps=True)
        charts.show(frame(fig, start, end), key="market_mcx_spread")
        components.source_caption(files, cap_flags, note="M2 − M1 is the difference of the two columns plotted above, "
                                  "computed in the app; the proxy's is INR interest carry by construction")
    quote(NOTES, "Table 1.3 — proxy M1 vs observed", "What the MCX proxy does and",
          "What the MCX proxy does and doesn't tell you")

# ------------------------------------------------------------------------------------------------ freight
with tab_freight:
    fw = data.freight_weekly(["week_end", "freight_jea_nsa_usd_t", "freight_usec_mun_usd_t", "index_value",
                              "freight_src"])
    fr_src, fallback = FREIGHT, False
    if fw is None:
        components.missing_data(FREIGHT)
        pw = data.parity_weekly(["week_end", "grade", "lane", "freight_base_usd_t"])
        if pw is None:
            components.missing_data(PARITY)
        else:
            one = pw[pw["grade"] == pw["grade"].iloc[0]]
            fw = one.pivot_table(index="week_end", columns="lane", values="freight_base_usd_t").reset_index()
            fw = fw.rename(columns={"JEA_NSA": "freight_jea_nsa_usd_t", "USEC_MUN": "freight_usec_mun_usd_t"})
            fr_src, fallback = PARITY, True
            st.caption("Weekly fallback: the lane freight each parity week used, from the published parity table "
                       "(Jan–Oct 2022 only; no index shape or source labels in this copy).")
    if fw is not None:
        d = in_range(fw, "week_end", start, end)
        st.warning("Freight levels are hindsight reconstructions, not quotes: the weekly shape is borrowed from the "
                   "Drewry WCI composite (PROXY), the Gulf lane's level is a judgement and the US lane's level is "
                   "calibrated to trade-press anchors published months later (ASSUMPTION).",
                   icon=":material/history:")
        if d.empty:
            st.info("No freight weeks in the chosen dates (the series starts 25-Dec-2020).", icon=":material/info:")
        else:
            fig = charts.line_chart(d, "week_end", {"freight_usec_mun_usd_t": LABELS["freight_usec_mun_usd_t"] + " (40ft)",
                                                    "freight_jea_nsa_usd_t": LABELS["freight_jea_nsa_usd_t"] + " (20ft)"},
                                    colors={"freight_usec_mun_usd_t": PALETTE["freight"],
                                            "freight_jea_nsa_usd_t": "#bf9000"},
                                    y_title=f"{unit('freight_usec_mun_usd_t') or 'USD/MT'} of scrap", height=340,
                                    hover_format=",.2f")
            fig.update_traces(mode="lines+markers", marker=dict(size=3))
            charts.show(frame(fig, start, end), key="market_freight")
            components.source_caption([fr_src], {"lane levels": flag("freight_usec_mun_usd_t", "ASSUMPTION"),
                                                 "weekly shape (WCI)": "PROXY"},
                                      note="week ending Friday; the WCI assessment is the Thursday before")
            win = in_range(fw, "week_end", WINDOW_START, WINDOW_END + dt.timedelta(days=2))
            stress = data.adverse_event("3_freight_stress_hypothetical", ["freight_shock_frac"])
            shock = (components.pct(float(stress["freight_shock_frac"].iloc[0]), 0, sign=True)
                     if stress is not None and not stress.empty else "hypothetical")
            if len(win) >= 2:
                moves = {lane: win[col].iloc[-1] / win[col].iloc[0] - 1 for lane, col in
                         (("Jebel Ali → Nhava Sheva", "freight_jea_nsa_usd_t"),
                          ("US East Coast → Mundra", "freight_usec_mun_usd_t"))}
                st.caption(f"{components.flag_badge('HYPOTHETICAL')} The {shock} freight shock in the adverse events "
                           "and Monte Carlo stresses is hypothetical: on this series freight fell over the window ("
                           + "; ".join(f"{k} {components.pct(v, sign=True)}" for k, v in moves.items())
                           + f", {components.day(win['week_end'].iloc[0])} to "
                             f"{components.day(win['week_end'].iloc[-1], True)}).")
            if not fallback:
                c1, c2 = st.columns([1.3, 1], gap="large")
                with c1:
                    fig = charts.line_chart(d, "week_end", {"index_value": "Drewry WCI composite"},
                                            colors={"index_value": PALETTE["neutral"]}, y_title="USD per 40ft box",
                                            height=280, hover_format=",.0f")
                    fig.update_layout(showlegend=False)
                    charts.show(frame(fig, start, end), key="market_wci")
                    components.source_caption([FREIGHT], {"WCI composite (shape only)": "PROXY"})
                with c2:
                    parts = d["freight_src"].str.split("|", expand=True)
                    mix = (pd.DataFrame({"WCI shape": parts[0], "USEC level": parts[1].str.removeprefix("USEC:"),
                                         "JEA level": parts[2].str.removeprefix("JEA:")})
                           .value_counts().rename("weeks").reset_index())
                    st.dataframe(mix, hide_index=True, width="stretch")
                    components.source_caption([FREIGHT], {"labels": "ASSUMPTION"},
                                              note="how each week was built: <WCI shape>|USEC:<level>|JEA:ASSUMPTION; "
                                                   "USEC:ANCHORED weeks are the best-supported level")
    quote(DICTIONARY, "data/processed/freight_weekly.csv", "**Known gaps and caveats**",
          "Known gaps and caveats of the freight series", mode="rest")
    components.what_it_tells(FREIGHT_NOTES)

# ------------------------------------------------------------------------------------------------ at a glance
with tab_glance:
    st.subheader(f"{components.day(start, True)} to {components.day(end, True)} at a glance")
    src, cols = (MKT, MKT_COLS[1:]) if mkt is not None else (FX, ["usdinr", "fwd_premium_3m_pa", "rbi_repo_pa"])
    base = mkt if mkt is not None else data.fx_rates_daily(FX_COLS)
    if mkt is None:
        components.missing_data(MKT)
    if base is not None:
        d = in_range(base, "date", start, end)
        decimals = {"usdinr": 4, "lme_stock_mt": 0, "lme_cash_usd_t": 1, "lme_3m_usd_t": 1}
        rows = []
        for col in cols:
            s = d[["date", col]].dropna().reset_index(drop=True)
            if s.empty:
                continue
            scale = 100 if col in RATE_COLS else 1
            dp = decimals.get(col, 2)

            def cell(i: int) -> str:
                return f"{components.num(s[col].iloc[i] * scale, dp)} ({components.day(s['date'].iloc[i], True)})"

            move = (components.pct(s[col].iloc[-1] / s[col].iloc[0] - 1, sign=True)
                    if col not in RATE_COLS and col != "lme_cash_3m_spread_usd_t" and s[col].iloc[0] else "—")
            rows.append({"Series": LABELS.get(col, col), "Flag": flag(col, "n/a"), "Unit": unit(col),
                         "First": cell(0), "Last": cell(len(s) - 1), "Low": cell(int(s[col].idxmin())),
                         "High": cell(int(s[col].idxmax())), "First → last": move})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            components.source_caption([src, PROV], ["DIRECT", "PROXY", "ASSUMPTION"],
                                      note="first, last, low and high of each column over the chosen dates (rates in "
                                           "% p.a.); the Flag column is the series' own flag")
        else:
            st.info("No rows in the chosen dates.", icon=":material/info:")

# ------------------------------------------------------------------------------------------------ provenance
with tab_prov:
    if prov is None:
        components.missing_data(PROV)
    else:
        counts = prov["flag"].value_counts()
        st.markdown(" ".join(f"{components.flag_badge(f)} {counts.get(f, 0)} columns" for f in
                             ("DIRECT", "PROXY", "ASSUMPTION")))
        chosen = st.multiselect("Flags", ["DIRECT", "PROXY", "ASSUMPTION"], default=["DIRECT", "PROXY", "ASSUMPTION"],
                                key="market_prov_flags")
        shown = prov[prov["flag"].isin(chosen)].reset_index(drop=True)
        tint = {"DIRECT": "background-color:#e3f1e4", "PROXY": "background-color:#fbe9dc",
                "ASSUMPTION": "background-color:#ece4f3"}
        st.dataframe(shown.style.map(lambda v: tint.get(v, ""), subset=["flag"]), hide_index=True, width="stretch",
                     column_config={"column": st.column_config.TextColumn(width="medium"),
                                    "source": st.column_config.TextColumn(width="large"),
                                    "transformation": st.column_config.TextColumn(width="large")})
        components.source_caption([PROV], note=f"{len(shown)} of {len(prov)} market_daily.csv columns; every step "
                                               "from source to panel value is in `transformation`")
        quote(DICTIONARY, "Phase 0 data dictionary", "Flags (CONTRACTS §1.2)", "What the three flags mean")

quote(PARITY_DOC, "Hindsight and provenance disclosure", "**Freight levels are hindsight", "Hindsight and provenance "
      "disclosure (what a 2022 desk could not have known)", mode="rest")
