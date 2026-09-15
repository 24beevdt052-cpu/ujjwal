"""Phase 0 documentation generator -> docs/00_data_dictionary.md and docs/00_assumptions_log.md (CONTRACTS §4.6).

Both documents are rendered from the files and the parameter register themselves (never hand-edited), so they cannot
drift from the data: every processed file and column with meaning, unit, provenance flag, source, transformation,
gaps / fill counts and headline-window statistics; every YAML parameter with value, flag, source, verify status and
justification. Output is deterministic (no run timestamps) so `run_all.py` reproduces it byte-for-byte; the only date
is the data-retrieval note, read from data/raw/_download_manifest.json.

What this does and doesn't tell you: the dictionary tells a reader where each number came from and how complete it
is. It does not re-verify sources — a VERIFIED/PARTIAL/PENDING status is what the Phase 0 researcher recorded in the
YAML `verify` field, and the PENDING list is the honest to-do list before anything is presented as checked.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from desk import HISTORY_START, SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.data import build_panel, fetch_freight, fetch_fx, fetch_lme, mcx
from desk.data._http import MANIFEST_PATH, retrieval_note
from desk.data.build_panel import ECB, NO_FREIGHT, PANEL_META, ColumnMeta, UpstreamMissingError
from desk.paths import DOCS_DIR, PROCESSED_DIR, RAW_DIR



def retrieved_note() -> str:
    """Retrieval dates of every cached download, from the manifest written by desk.data._http (never a literal)."""
    files = [f for f in RAW_DIR.rglob("*") if f.is_file() and not f.name.startswith(".") and f != MANIFEST_PATH]
    return f"Data {retrieval_note(files)} (cached under data/raw/; rebuilt offline with DESK_OFFLINE=1)."


DICT_PATH = DOCS_DIR / "00_data_dictionary.md"
LOG_PATH = DOCS_DIR / "00_assumptions_log.md"
FLAGS = ("DIRECT", "PROXY", "ASSUMPTION")
STATUSES = ("VERIFIED", "PARTIAL", "PENDING", "N/A")
_STATUS_RE = re.compile(r"^(VERIFIED|PARTIAL|PENDING|N/A)\b[\s—–:\-]*(.*)$", re.S)
WEEK_WINDOW_START = pd.Timestamp(WINDOW_START) + pd.Timedelta(days=(4 - pd.Timestamp(WINDOW_START).dayofweek) % 7)
WEEK_WINDOW_END = pd.Timestamp(WINDOW_END) + pd.Timedelta(days=(4 - pd.Timestamp(WINDOW_END).dayofweek) % 7)
YAML_OWNERS = {
    "rates.yaml": "P0 market-data", "market_proxy.yaml": "P0 market-data", "logistics.yaml": "P0 freight/logistics",
    "regulatory.yaml": "P0 regulatory/contract research", "exchange.yaml": "P0 regulatory/contract research",
    "scrap_grades.yaml": "P0 regulatory/contract research", "commercial.yaml": "P0 regulatory/contract research",
    "parity.yaml": "P1 parity", "risk.yaml": "P4/P5 risk",
}
FX_DATE_NOTE = "ECB TARGET publication days (plus MANUAL_RBI dates if supplied)"


# --------------------------------------------------------------------------------------------- file specs
@dataclass(frozen=True)
class FileSpec:
    name: str
    producer: str
    contract: str
    grain: str
    date_col: str | None
    weekly: bool
    columns: dict[str, ColumnMeta]


def _upstream(col: str, **changes) -> ColumnMeta:
    return replace(PANEL_META[col], align="", **changes)


def file_specs() -> list[FileSpec]:
    lme_cols = {c: _upstream(c) for c in fetch_lme.COLUMNS}
    fx_cols = {"date": ColumnMeta("ECB reference-rate publication day", "date_yyyy_mm_dd", "DIRECT", ECB,
                                  f"{FX_DATE_NOTE}; starts Dec 2017 so every panel day has a prior fixing.")}
    fx_cols |= {c: _upstream(c) for c in fetch_fx.COLUMNS[1:]}
    fx_cols["usdinr_src"] = _upstream("usdinr_src", transformation=(
        "ECB_CROSS unless data/manual/rbi_reference_rate.csv covers the date (MANUAL_RBI)."))
    fx_cols["rbi_repo_pa"] = _upstream("rbi_repo_pa", transformation="Step path from rates.yaml on each ECB date.")
    fx_cols["usd_rate_3m_filled"] = _upstream("usd_rate_3m_filled", meaning=(
        "True when the ECB date had no same-day US Treasury bill print and the last print was carried"),
        transformation=f"Treasury print date < ECB date (carry <= {build_panel.MAX_FILL_BDAYS} rows).")
    freight_cols = {
        "week_end": ColumnMeta(
            "Friday ending the week (CONTRACTS §3 W-FRI); the WCI assessment is the Thursday before", "date_yyyy_mm_dd",
            "ASSUMPTION", "CONTRACTS §3 week convention", "Thursday Drewry assessment date + 1 day."),
        "freight_jea_nsa_usd_t": _upstream("freight_jea_nsa_usd_t"),
        "freight_usec_mun_usd_t": _upstream("freight_usec_mun_usd_t"),
        "index_name": ColumnMeta("Name of the shape index", "text", "PROXY", "desk.data.fetch_freight",
                                 f"Constant {fetch_freight.INDEX_NAME}."),
        "index_value": ColumnMeta(
            "Drewry WCI composite for that week's Thursday", "usd_per_40ft_box", "PROXY",
            f"Internet Archive snapshots of {fetch_freight.DREWRY_WCI_URL} (points in data/interim/freight/points_wci.csv)"
            "; AJOT republications for two weeks",
            "WCI_REPORTED weeks are values as published (DIRECT observations); WCI_DERIVED weeks are back-filled from "
            "the next week's published % change; WCI_INTERPOLATED weeks are linear. Column flag = weakest (PROXY)."),
        "freight_src": _upstream("freight_src", transformation=(
            "<shape: WCI_REPORTED|WCI_DERIVED|WCI_INTERPOLATED>|USEC:<ANCHORED|SIBLING|EXTRAP_PRE|EXTRAP_POST>|"
            "JEA:ASSUMPTION.")),
        "note": ColumnMeta("Per-week build note (anchor ratio k, USD/box levels, derivation)", "text", "ASSUMPTION",
                           "desk.data.fetch_freight", "Free text generated by the builder; flagged like the weakest "
                           "series it describes."),
    }
    news_cols = {
        "week_end": ColumnMeta("Friday ending the week the headline was published in (UTC)", "date_yyyy_mm_dd",
                               "ASSUMPTION", "CONTRACTS §3 week convention",
                               "Items kept only if published Saturday 00:00 to Friday 23:59:59 UTC of that week."),
        "published_utc": ColumnMeta("Publication timestamp as returned by Google News RSS", "iso8601_utc", "DIRECT",
                                    "Google News RSS search (news.google.com/rss/search, after:/before: operators)",
                                    "Stored as returned; mostly date-only precision (see caveats)."),
        "source": ColumnMeta("Publisher name", "text", "DIRECT", "Google News RSS <source> tag",
                             "As returned; the trailing ' - Publisher' suffix was moved out of the title."),
        "title": ColumnMeta("Headline text, never paraphrased", "text", "DIRECT", "Google News RSS <title>",
                            "Publisher suffix removed; de-duplicated on a normalised title across queries/weeks."),
        "link": ColumnMeta("Google News article redirect URL", "url", "DIRECT", "Google News RSS <link>", "As returned."),
        "query": ColumnMeta("Edition and query string that first retrieved the headline", "text", "ASSUMPTION",
                            "desk.sentiment.fetch_news CORE_QUERIES / EXTRA_QUERIES",
                            "'<edition>:<query>'. The query list is a judgement; which headlines form a week's news "
                            "flow depends on it and on Google's ranking (PROXY for news flow)."),
    }
    prov_cols = {
        "column": ColumnMeta("Name of a market_daily.csv column", "text", "n/a (metadata)", "desk.data.build_panel",
                             "One row per panel column, in panel order."),
        "flag": ColumnMeta("Provenance flag of that column: DIRECT, PROXY or ASSUMPTION", "text", "n/a (metadata)",
                           "desk.data.build_panel.PANEL_META + source counts",
                           "usdinr* and MCX flags are recomputed from the sources actually used; indicator/label "
                           "columns carry the weakest flag of the series they qualify."),
        "source": ColumnMeta("Named public source or register key", "text", "n/a (metadata)", "desk.data.build_panel",
                             "—"),
        "transformation": ColumnMeta("Every step from source to panel value", "text", "n/a (metadata)",
                                     "desk.data.build_panel", "Includes the calendar-alignment rule."),
        "unit": ColumnMeta("Unit of the column (desk.units conventions)", "text", "n/a (metadata)",
                           "desk.data.build_panel", "—"),
    }
    return [
        FileSpec("market_daily.csv", "desk.data.build_panel", "CONTRACTS §4.5",
                 "one row per LME trading day, 2018-01-02 → 2022-12-30", "date", False, {}),
        FileSpec("series_provenance.csv", "desk.data.build_panel", "CONTRACTS §4.5",
                 "one row per market_daily.csv column", None, False, prov_cols),
        FileSpec("lme_daily.csv", "desk.data.fetch_lme", "CONTRACTS §4.1",
                 "one row per LME trading day (defines the panel calendar)", "date", False, lme_cols),
        FileSpec("fx_rates_daily.csv", "desk.data.fetch_fx", "CONTRACTS §4.2",
                 "one row per ECB reference-rate day, 2017-12-01 → 2022-12-30", "date", False, fx_cols),
        FileSpec("freight_weekly.csv", "desk.data.fetch_freight", "CONTRACTS §4.3",
                 "one row per week ending Friday, 2020-12-25 → 2022-12-30", "week_end", True, freight_cols),
        FileSpec("headlines_weekly.csv", "desk.sentiment.fetch_news", "CONTRACTS §4.4",
                 "one row per kept headline, weeks ending 2022-02-25 → 2022-09-02", "week_end", True, news_cols),
    ]


# --------------------------------------------------------------------------------------------- formatting
def md(text) -> str:
    """Make arbitrary text safe inside a markdown table cell."""
    return str(text).replace("\n", " ").replace("|", "\\|").strip()


def table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(md(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def fmt(x, unit: str = "") -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    if unit == "rate_pa":
        return f"{x * 100:.2f}%"
    if unit in ("usd_per_mt", "usd_per_40ft_box"):
        return f"{x:,.1f}" if abs(x) >= 100 else f"{x:,.2f}"
    if unit == "inr_per_usd":
        return f"{x:.4f}"
    if unit == "inr_per_kg":
        return f"{x:,.2f}"
    if unit == "mt":
        return f"{x:,.0f}"
    return f"{x:,.4g}"


def _date(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------------------------- data access
def _read_processed(name: str, date_col: str | None) -> pd.DataFrame:
    path = PROCESSED_DIR / name
    if not path.exists():
        raise UpstreamMissingError(f"{path} is missing — run the Phase 0 stage that owns it before the dictionary.")
    df = pd.read_csv(path, keep_default_na=True)
    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], format="%Y-%m-%d")
    return df


def window_mask(df: pd.DataFrame, spec: FileSpec) -> pd.Series:
    if spec.date_col is None:
        return pd.Series(True, index=df.index)
    d = df[spec.date_col]
    if spec.weekly:
        return (d >= WEEK_WINDOW_START) & (d <= WEEK_WINDOW_END)
    return (d >= pd.Timestamp(WINDOW_START)) & (d <= pd.Timestamp(WINDOW_END))


def _is_bool(s: pd.Series) -> bool:
    return s.dtype == bool


def window_summary(df: pd.DataFrame, col: str, unit: str, spec: FileSpec, win: pd.Series) -> str:
    s = df.loc[win, col]
    dates = df.loc[win, spec.date_col] if spec.date_col else None
    if s.empty:
        return "no rows in window"
    if _is_bool(s):
        return f"n={len(s)}; True on {int(s.astype(bool).sum())}"
    if unit.startswith("date") or col == spec.date_col:
        v = pd.to_datetime(s, format="%Y-%m-%d")
        return f"n={len(s)}; {_date(v.min())} → {_date(v.max())}; {v.nunique()} distinct"
    if pd.api.types.is_numeric_dtype(s):
        v = s.dropna()
        if v.empty:
            return f"n={len(s)}; all missing"
        parts = [f"n={len(v)}"]
        lo, hi = v.idxmin(), v.idxmax()
        where = (lambda i: f" ({_date(dates[i])})") if dates is not None else (lambda i: "")
        parts.append(f"min {fmt(v[lo], unit)}{where(lo)}")
        parts.append(f"mean {fmt(v.mean(), unit)}")
        parts.append(f"max {fmt(v[hi], unit)}{where(hi)}")
        first, last = v.iloc[0], v.iloc[-1]
        # % change only makes sense for strictly positive level series (not spreads or rates).
        change = f" ({(last / first - 1) * 100:+.1f}%)" if unit != "rate_pa" and (v > 0).all() else ""
        parts.append(f"first {fmt(first, unit)} → last {fmt(last, unit)}{change}")
        return "; ".join(parts)
    counts = s.fillna("<missing>").astype(str).value_counts()
    if col in ("title", "link", "note"):
        return f"n={len(s)}; {counts.size} distinct"
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:4]
    more = f"; +{counts.size - 4} more" if counts.size > 4 else ""
    return f"n={len(s)}; {counts.size} distinct: " + ", ".join(f"{k} ({v})" for k, v in top) + more


def completeness(df: pd.DataFrame, col: str) -> str:
    s = df[col]
    if s.dtype == object:
        missing = int(s.isna().sum() + (s == NO_FREIGHT).sum()) if col == "freight_src" else int(s.isna().sum())
    else:
        missing = int(s.isna().sum())
    return f"{len(s) - missing:,} / {missing:,}"


# --------------------------------------------------------------------------------------------- gaps & checks
def panel_caveats(panel: pd.DataFrame, prov: pd.DataFrame) -> list[str]:
    d = panel["date"]
    out = []
    filled = panel.loc[panel["usdinr_filled"], "date"]
    out.append(f"`usdinr_filled`: {len(filled)} LME days had no ECB fixing and carry the previous ECB row "
               f"({', '.join(_date(x) for x in filled[:12])}{' …' if len(filled) > 12 else ''}).")
    nf = panel["freight_src"] == NO_FREIGHT
    if nf.any():
        out.append(f"Freight: {int(nf.sum())} days ({_date(d[nf].min())} → {_date(d[nf].max())}) precede the freight "
                   f"series and are left empty (`freight_src = {NO_FREIGHT}`); the headline window is fully covered.")
    out.append(f"`freight_filled`: {int(panel['freight_filled'].sum())} days carry a freight value assessed on an earlier "
               "day (point-in-time forward-fill from the Thursday WCI assessment; CONTRACTS §3).")
    out.append(f"`usd_rate_3m_filled`: {int(panel['usd_rate_3m_filled'].sum())} days carry a Treasury bill print from an "
               "earlier day (US holiday) or the whole FX row. `rates_src` on panel days: " +
               ", ".join(f"{k} {v}" for k, v in sorted(panel['rates_src'].value_counts().items())) + ".")
    src = panel["mcx_src"].value_counts()
    mcx_note = "MCX: " + ", ".join(f"`{k}` on {v} days" for k, v in sorted(src.items())) + "."
    if src.get(mcx.SRC_PROXY, 0) == len(panel):
        mcx_note += (" No `data/manual/mcx_aluminium_*.csv` bhavcopy extract exists (mcxindia.com returned HTTP 403 to "
                     "scripted requests, docs/research/market_data_notes.md §6.1), so every MCX price is the duty-paid "
                     "LME import-parity PROXY. A third-party mirror is used only to calibrate/check it.")
    out.append(mcx_note)
    real = pd.to_datetime(pd.Series(config.value("mcx_al_expiry_dates_2022")))
    months = real.dt.to_period("M")
    proxy_exp = pd.to_datetime(panel["mcx_m1_expiry"]).groupby(pd.to_datetime(panel["mcx_m1_expiry"]).dt.to_period("M"))
    proxy_by_month = {m: g.iloc[0] for m, g in proxy_exp}
    mism = [(r, proxy_by_month.get(m)) for r, m in zip(real, months) if proxy_by_month.get(m) != r]
    if mism:
        out.append("MCX expiries: the proxy rule (last calendar day → previous LME day) differs from the MCX-published "
                   "2022 expiries (exchange.yaml `mcx_al_expiry_dates_2022`) on " +
                   ", ".join(f"{_date(r)} (proxy {_date(p) if p is not None else 'n/a'})" for r, p in mism) +
                   "; days-to-expiry carry is off by that many days around those expiries.")
    else:
        out.append("MCX expiries: the proxy rule matches every MCX-published 2022 expiry in exchange.yaml.")
    usec = panel.loc[panel["in_window"], "freight_src"].str.extract(r"USEC:(\w+)")[0].value_counts()
    out.append("Freight levels in window: USEC_MUN " + ", ".join(f"{k} {v} days" for k, v in sorted(usec.items())) +
               "; JEA_NSA level is an ASSUMPTION on every day (no citable 2022 Jebel Ali → Nhava Sheva quote).")
    out.append("Freight alignment has no look-ahead (a day sees only assessments made on or before it), but the weekly "
               "freight LEVELS are hindsight-calibrated: the anchors behind Mar–Jun 2022 weeks were published Aug–Sep "
               "2022 (up to ~7 months later; `available_from` in data/interim/freight/points_india_inbound_anchors.csv "
               "and the weekly `note`). Do not treat freight as information available on the trade date.")
    out.append("MCX proxy regime bias: unbiased over the window but above the third-party mirror on every March-2022 "
               "Friday (+5 to +11 ₹/kg) and mostly below it May–July (−1 to −8 ₹/kg), which widens the parity swing "
               "between the spike and the trough (market_proxy.yaml).")
    out.append("`inr_rate_3m_pa` uses the same month's OECD average (≤ 1 month look-ahead); forwards are CIP-derived, "
               "not observed FBIL/RBI forward premia (PENDING in docs/research/market_data_notes.md).")
    flags = prov["flag"].value_counts()
    out.append("Column flags: " + ", ".join(f"{f} {int(flags.get(f, 0))}" for f in FLAGS) + f" (of {len(prov)}).")
    return out


def reconciliation(panel: pd.DataFrame, lme: pd.DataFrame, fx: pd.DataFrame, fr: pd.DataFrame) -> list[list[str]]:
    rows = []
    p = panel.set_index("date")
    ok = p.index.equals(pd.DatetimeIndex(lme["date"])) and np.allclose(
        p[fetch_lme.COLUMNS[1:]].to_numpy(float), lme[fetch_lme.COLUMNS[1:]].to_numpy(float))
    rows.append(["LME columns identical to lme_daily.csv on every panel day", "PASS" if ok else "FAIL"])
    obs = p[~p["usdinr_filled"]]
    f = fx.set_index("date").reindex(obs.index)
    ok = f["usdinr"].notna().all() and np.allclose(obs["usdinr"], f["usdinr"]) and np.allclose(
        obs["usdinr_fwd_3m"], f["usdinr_fwd_3m"])
    rows.append([f"usdinr / usdinr_fwd_3m equal fx_rates_daily.csv on the {len(obs)} non-filled days",
                 "PASS" if ok else "FAIL"])
    fri = p.index.intersection(pd.DatetimeIndex(fr["week_end"]))
    w = fr.set_index("week_end").reindex(fri)
    ok = np.allclose(p.loc[fri, "freight_usec_mun_usd_t"], w["freight_usec_mun_usd_t"]) and np.allclose(
        p.loc[fri, "freight_jea_nsa_usd_t"], w["freight_jea_nsa_usd_t"])
    rows.append([f"Freight on the {len(fri)} panel Fridays equals freight_weekly.csv", "PASS" if ok else "FAIL"])
    parity = (p["mcx_al_spot_inr_kg"] / (p["lme_cash_usd_t"] * p["usdinr"] / 1000.0)).where(
        p["mcx_src"] == mcx.SRC_PROXY)
    duty = 1 + config.value("bcd_primary_al_hs7601") * (1 + config.value("sws_rate_on_bcd"))
    prem = config.value("mcx_domestic_premium_inr_kg")
    ok = bool(parity.dropna().empty) or (prem == 0 and np.allclose(parity.dropna(), duty, atol=1e-4))
    rows.append([f"Proxy MCX spot = LME cash × USDINR / 1000 × {duty:.4f} (units check, premium {prem})",
                 "PASS" if ok else "FAIL (or non-zero premium)"])
    return rows


def window_glance(panel: pd.DataFrame) -> list[list[str]]:
    w = panel[panel["in_window"]].set_index("date")

    def first_last(col, unit):
        s = w[col]
        return [fmt(s.iloc[0], unit), fmt(s.iloc[-1], unit), f"{fmt(s.min(), unit)} ({_date(s.idxmin())})",
                f"{fmt(s.max(), unit)} ({_date(s.idxmax())})"]

    rows = [
        ["LME cash (USD/MT) [DIRECT]", *first_last("lme_cash_usd_t", "usd_per_mt")],
        ["LME 3M (USD/MT) [DIRECT]", *first_last("lme_3m_usd_t", "usd_per_mt")],
        ["Cash–3M spread (USD/MT) [DIRECT]", *first_last("lme_cash_3m_spread_usd_t", "usd_per_mt")],
        ["LME stocks (MT) [DIRECT]", *first_last("lme_stock_mt", "mt")],
        ["USD/INR (INR per USD) [PROXY]", *first_last("usdinr", "inr_per_usd")],
        ["3M forward premium (p.a.) [PROXY]", *first_last("fwd_premium_3m_pa", "rate_pa")],
        ["RBI repo (p.a.) [DIRECT]", *first_last("rbi_repo_pa", "rate_pa")],
        ["MCX Al M1 (INR/kg) [PROXY]", *first_last("mcx_al_m1_inr_kg", "inr_per_kg")],
        ["Freight USEC→MUN (USD/MT) [ASSUMPTION level, WCI shape]", *first_last("freight_usec_mun_usd_t", "usd_per_mt")],
        ["Freight JEA→NSA (USD/MT) [ASSUMPTION level]", *first_last("freight_jea_nsa_usd_t", "usd_per_mt")],
    ]
    return rows


# --------------------------------------------------------------------------------------------- data dictionary
def render_dictionary() -> str:
    specs = file_specs()
    panel = _read_processed("market_daily.csv", "date")
    prov = _read_processed("series_provenance.csv", None)
    lme = _read_processed("lme_daily.csv", "date")
    fx = _read_processed("fx_rates_daily.csv", "date")
    fr = _read_processed("freight_weekly.csv", "week_end")
    news = _read_processed("headlines_weekly.csv", "week_end")
    frames = {"market_daily.csv": panel, "series_provenance.csv": prov, "lme_daily.csv": lme,
              "fx_rates_daily.csv": fx, "freight_weekly.csv": fr, "headlines_weekly.csv": news}
    if list(prov["column"]) != list(panel.columns):
        raise ValueError("series_provenance.csv does not list the market_daily.csv columns in order")
    panel_cols = {r.column: ColumnMeta(PANEL_META[r.column].meaning, r.unit, r.flag, r.source, r.transformation)
                  for r in prov.itertuples()}
    specs[0] = replace(specs[0], columns=panel_cols)
    known = {s.name for s in specs}
    extra_files = sorted(p.name for p in PROCESSED_DIR.glob("*.csv") if p.name not in known)

    L: list[str] = []
    L.append("# Phase 0 data dictionary")
    L.append("")
    L.append(f"{SIM_LABEL}.")
    L.append("")
    L.append("Generated by `desk.data.dictionary` from the files in `data/processed/` — do not hand-edit; re-run "
             "`.venv/bin/python run_all.py --only P0`. " + retrieved_note())
    L.append("")
    L.append(f"Headline window: **{WINDOW_START} → {WINDOW_END}** (daily files); weekly files use weeks ending "
             f"{_date(WEEK_WINDOW_START)} → {_date(WEEK_WINDOW_END)}. Panel history starts {HISTORY_START}.")
    L.append("")
    L.append("Flags (CONTRACTS §1.2): **DIRECT** = observed from a named public source; **PROXY** = a real "
             "observable standing in for the thing we need, or a transformation of real data; **ASSUMPTION** = a "
             "judgement with a stated justification. Indicator and label columns (`*_filled`, `*_src`, notes) carry "
             "the weakest flag of the series they qualify, so filtering by flag never promotes a proxy.")
    L.append("")
    L.append("## Files")
    L.append("")
    rows = []
    for s in specs:
        df = frames[s.name]
        rows.append([f"`{s.name}`", s.grain, f"{len(df):,} × {df.shape[1]}", f"`{s.producer}`", s.contract])
    L.append(table(["File", "Grain", "Rows × cols", "Producer", "Contract"], rows))
    if extra_files:
        L.append("")
        L.append("Other processed files present but not documented here (add a FileSpec): " +
                 ", ".join(f"`{x}`" for x in extra_files))
    L.append("")
    L.append("## Headline window at a glance (market_daily.csv)")
    L.append("")
    L.append(table(["Series", f"First ({WINDOW_START})", f"Last ({WINDOW_END})", "Window min (date)",
                    "Window max (date)"], window_glance(panel)))
    w = panel[panel["in_window"]]
    sp = w["lme_cash_3m_spread_usd_t"]
    L.append("")
    L.append(f"Window trading days: **{len(w)}**. Cash–3M: backwardation on {int((sp > 0).sum())} days, contango on "
             f"{int((sp < 0).sum())}, flat on {int((sp == 0).sum())}; mean {sp.mean():+.2f} USD/MT. LME cash window "
             f"high to window low: {(w['lme_cash_usd_t'].min() / w['lme_cash_usd_t'].max() - 1) * 100:+.1f}%. USD/INR "
             f"first to last: {(w['usdinr'].iloc[-1] / w['usdinr'].iloc[0] - 1) * 100:+.2f}%.")
    L.append("")
    L.append("## Cross-file reconciliation")
    L.append("")
    L.append(table(["Check", "Result"], reconciliation(panel, lme, fx, fr)))

    caveats = {
        "market_daily.csv": panel_caveats(panel, prov),
        "series_provenance.csv": ["Rewritten by `build_panel` on every run; the flags for `usdinr*`, MCX and rate columns "
                                  "change automatically when manual RBI / MCX bhavcopy files are dropped in or a rate fallback is used."],
        "lme_daily.csv": lme_caveats(lme),
        "fx_rates_daily.csv": fx_caveats(fx, lme),
        "freight_weekly.csv": freight_caveats(fr),
        "headlines_weekly.csv": news_caveats(news),
    }
    for s in specs:
        df = frames[s.name]
        win = window_mask(df, s)
        L.append("")
        L.append(f"## `data/processed/{s.name}`")
        L.append("")
        L.append(f"Producer `{s.producer}` · {s.contract} · {s.grain} · {len(df):,} rows"
                 + (f" · window rows {int(win.sum())}" if s.date_col else "") + ".")
        missing_meta = [c for c in df.columns if c not in s.columns]
        if missing_meta:
            raise ValueError(f"{s.name}: undocumented columns {missing_meta} (update desk.data.dictionary)")
        L.append("")
        L.append("**Definitions**")
        L.append("")
        L.append(table(["Column", "Meaning", "Unit", "Flag"],
                       [[f"`{c}`", s.columns[c].meaning, s.columns[c].unit, s.columns[c].flag] for c in df.columns]))
        L.append("")
        L.append("**Lineage**")
        L.append("")
        L.append(table(["Column", "Source", "Transformation"],
                       [[f"`{c}`", s.columns[c].source, s.columns[c].transformation] for c in df.columns]))
        if s.date_col:
            L.append("")
            L.append("**Completeness and window statistics**")
            L.append("")
            L.append(table(["Column", "Present / missing (whole file)", "Headline window"],
                           [[f"`{c}`", completeness(df, c), window_summary(df, c, s.columns[c].unit, s, win)]
                            for c in df.columns]))
        L.append("")
        L.append("**Known gaps and caveats**")
        L.append("")
        L.extend(f"- {c}" for c in caveats[s.name])
    L.append("")
    return "\n".join(L)


def lme_caveats(lme: pd.DataFrame) -> list[str]:
    per_year = lme.groupby(lme["date"].dt.year).size()
    out = ["Rows per year: " + ", ".join(f"{y} {n}" for y, n in per_year.items()) + "; no missing values."]
    peak = lme.loc[lme["lme_cash_usd_t"].idxmax()]
    out.append(f"Highest cash in file: {fmt(peak['lme_cash_usd_t'], 'usd_per_mt')} on {_date(peak['date'])} "
               f"(3M {fmt(peak['lme_3m_usd_t'], 'usd_per_mt')}). The file only starts in 2018, so 'all-time high' "
               "rests on the spec, not on this file.")
    out.append("Westmetall republishes LME official prices; an LME-own spot check of the Cash–3M series is PARTIAL "
               "(docs/verification_log.md).")
    return out


def fx_caveats(fx: pd.DataFrame, lme: pd.DataFrame) -> list[str]:
    lme_days, fx_days = set(lme["date"]), set(fx["date"])
    not_lme = sorted(d for d in fx_days if d >= pd.Timestamp(HISTORY_START) and d not in lme_days)
    not_fx = sorted(d for d in lme_days if d not in fx_days)
    out = [f"Starts {_date(fx['date'].min())} ({int((fx['date'] < pd.Timestamp(HISTORY_START)).sum())} rows before "
           "the panel) so the first panel day has rates.",
           f"{len(not_fx)} LME days have no ECB row ({', '.join(_date(x) for x in not_fx[:12])}); the panel carries the "
           f"previous ECB row there. {len(not_lme)} ECB days from {HISTORY_START} are not LME days (UK holidays) and "
           "are dropped in the panel.",
           "usdinr_src: " + ", ".join(f"{k} {v}" for k, v in sorted(fx["usdinr_src"].value_counts().items())) +
           ". `data/manual/rbi_reference_rate.csv` (RBI reference rate) has not been supplied.",
           "No observed USD/INR forward premia were found for Mar–Aug 2022; the CIP forwards use the 3M rates for "
           "the 1M tenor as well (flat short curve)."]
    return out


def freight_caveats(fr: pd.DataFrame) -> list[str]:
    shape = fr["freight_src"].str.split("|").str[0]
    win = (fr["week_end"] >= WEEK_WINDOW_START) & (fr["week_end"] <= WEEK_WINDOW_END)
    gaps = fr["week_end"].diff().dt.days.dropna()
    out = [f"{len(fr)} consecutive Friday weeks {_date(fr['week_end'].min())} → {_date(fr['week_end'].max())}; "
           f"{int((gaps != 7).sum())} breaks in the weekly sequence; nothing before 2020-12-25.",
           "WCI shape, whole file: " + ", ".join(f"{k} {v}" for k, v in sorted(shape.value_counts().items())) +
           "; window weeks: " + ", ".join(f"{k} {v}" for k, v in sorted(shape[win].value_counts().items())) + ".",
           "Levels are hindsight-calibrated: each week's `note` gives the date its level inputs became public "
           "(Mar–Apr 2022 weeks: 30-Sep-2022).",
           "USEC_MUN levels outside the Container News anchors (EXTRAP_PRE/EXTRAP_POST: "
           f"{int(fr['freight_src'].str.contains('EXTRAP').sum())} weeks) hold the lane/index ratio flat and are "
           "indicative only.",
           "JEA_NSA level is an ASSUMPTION (logistics.yaml `freight_jea_nsa_usd_box_ref`); each ±100 USD/box moves "
           f"it by ±{100 / config.value('container_payload_mt_20ft'):.0f} USD/MT.",
           "Pinning to monthly anchors smooths weekly volatility; do not read it as observed freight volatility. "
           "Freight excludes THC/CFS/haulage (logistics.yaml `port_cf_charges_*`)."]
    return out


def news_caveats(news: pd.DataFrame) -> list[str]:
    per_week = news.groupby("week_end").size()
    t = news["published_utc"].str[11:19].value_counts()
    top = news["source"].value_counts()
    top5 = sorted(top.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return [f"{len(news)} headlines in {per_week.size} weeks ({_date(per_week.index.min())} → "
            f"{_date(per_week.index.max())}); per week min {per_week.min()}, median {int(per_week.median())}, "
            f"max {per_week.max()}. The first week (ending 2022-02-25) is a lead-in before the window.",
            f"Timestamp precision: {int(t.get('07:00:00', 0))} at 07:00:00Z and {int(t.get('08:00:00', 0))} at "
            "08:00:00Z, i.e. mostly date-only; items near a week boundary may sit one day off their Indian "
            "publication date.",
            "Top publishers: " + ", ".join(f"{k} ({v})" for k, v in top5) + ".",
            "Weekly counts follow Google's archive and the query list as much as events; score average tone per "
            "week, not volume. Filter audit trail: data/interim/news/_audit_headlines.csv (not a processed file)."]


# --------------------------------------------------------------------------------------------- assumptions log
def split_verify(verify: str) -> tuple[str, str]:
    m = _STATUS_RE.match(verify.strip())
    if not m:
        return "UNSPECIFIED", verify.strip()
    return m.group(1), m.group(2).strip()


def render_value(p: config.Param, short: bool = False) -> str:
    if p.is_path:
        text = f"{p.interp} path, {len(p.path)} points: " + "; ".join(f"{d}: {v}" for d, v in p.path)
    elif isinstance(p.value, (list, dict)):
        text = json.dumps(p.value, ensure_ascii=False, default=str)
    else:
        text = str(p.value)
    text = " ".join(text.split())
    if short and len(text) > 70:
        text = text[:67] + "..."
    return text


def path_window_note(p: config.Param) -> str:
    if not p.is_path or not all(isinstance(v, (int, float)) for _, v in p.path):
        return ""
    days = pd.date_range(WINDOW_START, WINDOW_END, freq="D")
    s = p.series(days).astype(float)
    return (f"In window: {WINDOW_START} {s.iloc[0]:g} → {WINDOW_END} {s.iloc[-1]:g}; min {s.min():g}, "
            f"max {s.max():g}.")


def render_assumptions_log() -> str:
    config.reload()
    params = config.load_params()
    frame = config.params_frame()
    frame["status"] = [split_verify(v)[0] for v in frame["verify"]]
    files = list(dict.fromkeys(frame["file"]))

    L: list[str] = []
    L.append("# Phase 0 assumptions log")
    L.append("")
    L.append(f"{SIM_LABEL}.")
    L.append("")
    L.append("Rendered by `desk.data.dictionary` from `desk.config.params_frame()` (the YAML register in "
             "`config/params/`) — do not hand-edit; change the YAML and re-run `.venv/bin/python run_all.py --only P0`. "
             + retrieved_note())
    L.append("")
    L.append("Flags: **DIRECT** = observed from a named public source; **PROXY** = real observable standing in or a "
             "transformation of real data; **ASSUMPTION** = judgement with justification. Verify status (first word "
             "of each `verify` field): **VERIFIED** = primary/official source read for the 2022 value; **PARTIAL** = "
             "supported with a named gap; **PENDING** = not yet verified (the text gives the next step); **N/A** = "
             "assumption with nothing to verify against. Statuses are as recorded by the Phase 0 researchers; "
             "details in `docs/verification_log.md`.")
    L.append("")
    L.append("## Summary")
    L.append("")
    rows = []
    for f in files + ["**Total**"]:
        sub = frame if f == "**Total**" else frame[frame["file"] == f]
        fc, sc = sub["flag"].value_counts(), sub["status"].value_counts()
        rows.append([f if f == "**Total**" else f"`{f}`", YAML_OWNERS.get(f, "" if f == "**Total**" else "unassigned"),
                     len(sub), *[int(fc.get(x, 0)) for x in FLAGS], *[int(sc.get(x, 0)) for x in STATUSES]])
    L.append(table(["YAML file", "Owner", "Params", *FLAGS, *STATUSES], rows))
    unspecified = frame[frame["status"] == "UNSPECIFIED"]
    if not unspecified.empty:
        L.append("")
        L.append("Parameters whose `verify` field does not start with a status word: " +
                 ", ".join(f"`{k}`" for k in unspecified["key"]))

    pending = frame[frame["status"] == "PENDING"]
    L.append("")
    L.append(f"## Open items: PENDING ({len(pending)})")
    L.append("")
    L.append("Nothing below may be presented as checked. Each row's last column is the recorded next step.")
    L.append("")
    L.append(table(["Key", "File", "Flag", "Value used", "Next step"],
                   [[f"**`{r.key}`**", r.file, r.flag, render_value(params[r.key], short=True),
                     split_verify(r.verify)[1]] for r in pending.itertuples()]))
    risky = frame[(frame["flag"] == "DIRECT") & frame["status"].isin(["PENDING", "PARTIAL"])]
    L.append("")
    L.append(f"## DIRECT parameters not fully verified ({len(risky)})")
    L.append("")
    L.append("Labelled DIRECT because a named source states the value, but verification is incomplete — re-check "
             "before quoting them as verified.")
    L.append("")
    L.append(table(["Key", "File", "Status", "Gap / next step"],
                   [[f"`{r.key}`", r.file, r.status, split_verify(r.verify)[1]] for r in risky.itertuples()]))
    partial = frame[frame["status"] == "PARTIAL"]
    L.append("")
    L.append(f"## PARTIAL items ({len(partial)})")
    L.append("")
    L.append(table(["Key", "File", "Flag", "Gap / next step"],
                   [[f"`{r.key}`", r.file, r.flag, split_verify(r.verify)[1]] for r in partial.itertuples()]))
    L.append("")
    L.append("## Pipeline assumptions that are not YAML parameters")
    L.append("")
    L.extend([
        "- Panel calendar = LME trading days (Westmetall). MCX holidays are not modelled: MCX proxy prices sit on "
        "the LME calendar and proxy expiries use the LME calendar (CONTRACTS §3).",
        f"- FX/rates carried forward onto LME days without an ECB fixing, at most {build_panel.MAX_FILL_BDAYS} "
        "business days (longer gaps raise).",
        "- Weekly freight aligned point-in-time: each LME day takes the latest week already assessed (Thursday = "
        "week_end − 1) on or before it (`freight_filled` on carried days); no freight before 2020-12-24. The weekly "
        "levels themselves are hindsight-calibrated (CONTRACTS §4.3).",
        "- Grade factors are a CFR-India basis shared by both lanes (CONTRACTS §5 CFR parity); their lag-2 DGCIS mix "
        "is a hindsight reconstruction (point-in-time and lag-1/lag-3 paths are sensitivities in scrap_grades.yaml).",
        "- MCX proxy: duty-paid LME cash import parity, futures carried at `inr_rate_3m_pa` to the proxy expiry "
        "(CONTRACTS §4.5).",
        "- USD/INR = ECB cross (PROXY for the RBI reference rate); forwards by covered interest parity with the 3M "
        "rates for both tenors.",
    ])
    for f in files:
        sub = frame[frame["file"] == f]
        fc = sub["flag"].value_counts()
        L.append("")
        L.append(f"## `config/params/{f}`")
        L.append("")
        L.append(f"Owner: {YAML_OWNERS.get(f, 'unassigned')} · {len(sub)} parameters · " +
                 ", ".join(f"{x} {int(fc.get(x, 0))}" for x in FLAGS) + ".")
        L.append("")
        L.append(table(["Key", "Value", "Unit", "Flag", "Verify"],
                       [[f"`{r.key}`", render_value(params[r.key], short=True), r.unit, r.flag,
                         f"**{r.status}**" if r.status == "PENDING" else r.status] for r in sub.itertuples()]))
        for r in sub.itertuples():
            p = params[r.key]
            status, rest = split_verify(p.verify)
            L.append("")
            L.append(f"### `{p.key}`" + ("  — **PENDING**" if status == "PENDING" else ""))
            L.append("")
            L.append(f"- **Value:** {render_value(p)}")
            if note := path_window_note(p):
                L.append(f"- {note}")
            L.append(f"- **Unit:** {p.unit} · **Flag:** {p.flag}")
            L.append(f"- **Source:** {' '.join(p.source.split())}")
            verify_text = f"**{status}**" + (f" — {' '.join(rest.split())}" if rest else "")
            L.append(f"- **Verify:** {verify_text}")
            L.append(f"- **Justification:** {' '.join(p.note.split())}")
    L.append("")
    return "\n".join(L)


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    DICT_PATH.write_text(render_dictionary(), encoding="utf-8")
    LOG_PATH.write_text(render_assumptions_log(), encoding="utf-8")
    frame = config.params_frame()
    status = pd.Series([split_verify(v)[0] for v in frame["verify"]]).value_counts().to_dict()
    print(f"[dictionary] {DICT_PATH.name}, {LOG_PATH.name}: {len(frame)} params flags="
          f"{frame['flag'].value_counts().to_dict()} verify={status}")


if __name__ == "__main__":
    main()
