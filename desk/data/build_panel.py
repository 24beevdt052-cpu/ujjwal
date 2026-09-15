"""The canonical daily market panel -> data/processed/market_daily.csv + series_provenance.csv (CONTRACTS §4.5).

Every later phase reads this one file, so it is built strictly from the Phase 0 upstream files and fails loudly
instead of papering over a missing builder:

    lme_daily.csv       (desk.data.fetch_lme)      defines the calendar: one row per LME trading day
    fx_rates_daily.csv  (desk.data.fetch_fx)       ECB publication calendar -> aligned to LME days
    freight_weekly.csv  (desk.data.fetch_freight)  week ending Friday      -> mapped to LME days
    MCX Aluminium       (desk.data.mcx)            manual bhavcopy extracts if present, else import-parity proxy

Alignment rules, and why:
* **FX / rates / forwards.** An LME day without an ECB fixing (e.g. 1 May, a TARGET holiday) takes the latest ECB row
  on or before it (`usdinr_filled = True`). A carry longer than `MAX_FILL_BDAYS` business days means a data hole,
  not a holiday, so the build raises (CONTRACTS §3).
* **Freight.** Point-in-time forward-fill (CONTRACTS §3): each weekly row becomes available on its Thursday WCI
  assessment date (`week_end − 1 day`), and every LME day takes the latest row already available on or before it
  (`merge_asof`, backward). So Mon–Wed carry the PREVIOUS week's assessment, never the coming Thursday's.
  `freight_filled = True` whenever the value was assessed on an earlier day (every non-Thursday). A carry longer than
  `MAX_FILL_BDAYS` business days means a missing week and raises. Days before the first assessment (2020-12-24) stay
  empty with `freight_src = NO_FREIGHT_DATA`: freight is only needed from 2021 and inventing earlier levels would be
  fabrication. The headline window must be fully covered. Caveat that this alignment cannot remove: the weekly
  LEVELS themselves are hindsight-calibrated (see desk.data.fetch_freight, LOOK-AHEAD).
* **MCX.** Delegated to `desk.data.mcx.load_or_proxy_mcx` (bhavcopy files -> DIRECT, else PROXY_IMPORT_PARITY).

What this does and doesn't tell you: the panel is a faithful, calendar-aligned join of observed LME prices with
clearly flagged proxies (ECB-cross USD/INR, CIP forwards, import-parity MCX, index-shaped freight). It does not add
information: a PROXY column stays a proxy after the join, and `series_provenance.csv` says which is which.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from desk import HISTORY_START, MAX_FILL_BDAYS, PANEL_END as _PANEL_END, WINDOW_END, WINDOW_START, config
from desk.data import fetch_freight, fetch_fx, fetch_lme, mcx
from desk.data._http import retrieval_note
from desk.paths import PROCESSED_DIR

LME_PATH = PROCESSED_DIR / "lme_daily.csv"
FX_PATH = PROCESSED_DIR / "fx_rates_daily.csv"
FREIGHT_PATH = PROCESSED_DIR / "freight_weekly.csv"
OUT_PATH = PROCESSED_DIR / "market_daily.csv"
PROVENANCE_PATH = PROCESSED_DIR / "series_provenance.csv"

PANEL_END = pd.Timestamp(_PANEL_END)
NO_FREIGHT = "NO_FREIGHT_DATA"
CHART_NAME = "p0_market_overview"
CHART_START = pd.Timestamp("2021-01-01")

PANEL_COLUMNS = [
    "date", "in_window",
    "lme_cash_usd_t", "lme_3m_usd_t", "lme_cash_3m_spread_usd_t", "lme_stock_mt",
    "usdinr", "usdinr_filled", "usdinr_src", "rbi_repo_pa", "fed_funds_upper_pa", "inr_rate_3m_pa", "usd_rate_3m_pa",
    "usd_rate_3m_filled", "rates_src", "fwd_premium_3m_pa", "usdinr_fwd_1m", "usdinr_fwd_3m",
    "mcx_al_spot_inr_kg", "mcx_al_m1_inr_kg", "mcx_al_m2_inr_kg", "mcx_m1_expiry", "mcx_m2_expiry", "mcx_src",
    "freight_jea_nsa_usd_t", "freight_usec_mun_usd_t", "freight_filled", "freight_src",
]
FX_COLUMNS = PANEL_COLUMNS[PANEL_COLUMNS.index("usdinr"):PANEL_COLUMNS.index("usdinr_fwd_3m") + 1]
RATE_COLUMNS = ["inr_rate_3m_pa", "usd_rate_3m_pa", "usd_rate_3m_filled", "rates_src", "fwd_premium_3m_pa",
                "usdinr_fwd_1m", "usdinr_fwd_3m"]
FREIGHT_COLUMNS = ["freight_jea_nsa_usd_t", "freight_usec_mun_usd_t", "freight_filled", "freight_src"]
PROVENANCE_COLUMNS = ["column", "flag", "source", "transformation", "unit"]
FLAG_ORDER = {"DIRECT": 0, "PROXY": 1, "ASSUMPTION": 2}

WESTMETALL = f"Westmetall LME Aluminium official price tables, {fetch_lme.URL_TEMPLATE.format(year='<2018..2022>')}"
ECB = ("ECB Data Portal EXR reference rates D.INR.EUR.SP00.A and D.USD.EUR.SP00.A "
       "(https://data-api.ecb.europa.eu/service/data/EXR/...)")
FX_ALIGN = (" Panel: latest ECB-calendar row on/before the LME day (usdinr_filled=True when carried; "
            f"> {MAX_FILL_BDAYS} business days raises).")
FREIGHT_ALIGN = (" Panel: latest weekly row already assessed (Thursday = week_end - 1 day) on or before the LME day, "
                 "i.e. point-in-time forward-fill with no look-ahead in the ALIGNMENT (freight_filled=True on every day "
                 f"after the assessment day; a carry > {MAX_FILL_BDAYS} business days raises); empty before the first "
                 f"assessment ({NO_FREIGHT}). The weekly LEVELS are hindsight-calibrated (anchors published up to ~7 "
                 "months later; see freight_weekly.csv note).")


@dataclass(frozen=True)
class ColumnMeta:
    meaning: str
    unit: str
    flag: str
    source: str
    transformation: str
    align: str = ""  # extra step applied only when the column is copied onto the panel calendar


PANEL_META: dict[str, ColumnMeta] = {
    "date": ColumnMeta(
        "LME trading day (panel calendar; one row per day)", "date_yyyy_mm_dd", "DIRECT", WESTMETALL,
        f"Dates listed in the Westmetall yearly tables, {HISTORY_START}..{PANEL_END.date()}."),
    "in_window": ColumnMeta(
        "True inside the headline backtest window", "bool", "ASSUMPTION",
        "MASTER_SPEC_V3 Table 2 scope choice (desk.WINDOW_START / desk.WINDOW_END)",
        f"date between {WINDOW_START} and {WINDOW_END} inclusive. A scope definition, not market data."),
    "lme_cash_usd_t": ColumnMeta(
        "LME Aluminium official cash settlement price", "usd_per_mt", "DIRECT", WESTMETALL,
        "Parsed from cached HTML (data/raw/westmetall_lme_al_<year>.html); thousands separators removed."),
    "lme_3m_usd_t": ColumnMeta(
        "LME Aluminium official 3-month price", "usd_per_mt", "DIRECT", WESTMETALL,
        "Parsed from cached HTML (data/raw/westmetall_lme_al_<year>.html)."),
    "lme_cash_3m_spread_usd_t": ColumnMeta(
        "Cash minus 3-month: positive = backwardation, negative = contango", "usd_per_mt", "DIRECT", WESTMETALL,
        "lme_cash_usd_t - lme_3m_usd_t (arithmetic on two DIRECT prices, same day)."),
    "lme_stock_mt": ColumnMeta(
        "LME Aluminium warehouse stocks", "mt", "DIRECT", WESTMETALL,
        "Parsed from the stock column of the same tables."),
    "usdinr": ColumnMeta(
        "USD/INR spot, INR per 1 USD", "inr_per_usd", "PROXY", ECB + "; optional data/manual/rbi_reference_rate.csv",
        "ECB EUR/INR / ECB EUR/USD (same 14:15 CET fixing) standing in for the RBI 13:30 IST reference rate; "
        "MANUAL_RBI rows override where supplied.", FX_ALIGN),
    "usdinr_filled": ColumnMeta(
        "True when the LME day had no ECB fixing and the whole FX/rate row was carried forward", "bool", "PROXY",
        "ECB publication calendar vs LME calendar",
        "Indicator; flagged like the series it qualifies (usdinr, PROXY).", FX_ALIGN),
    "usdinr_src": ColumnMeta(
        "Origin of usdinr: ECB_CROSS or MANUAL_RBI", "text", "PROXY", "desk.data.fetch_fx",
        "Label carried from fx_rates_daily.csv; flagged like the series it qualifies.", FX_ALIGN),
    "rbi_repo_pa": ColumnMeta(
        "RBI policy repo rate", "rate_pa", config.get("rbi_repo_rate_pa").flag,  # DIRECT per CONTRACTS §4.2 (amended)
        "config/params/rates.yaml rbi_repo_rate_pa (RBI MPC press releases; verify field lists release ids)",
        "Step path evaluated on each ECB date (effective on announcement date).", FX_ALIGN),
    "fed_funds_upper_pa": ColumnMeta(
        "US federal funds target range, upper bound", "rate_pa", config.get("fed_funds_upper_pa").flag,
        "config/params/rates.yaml fed_funds_upper_pa (federalreserve.gov open market operations table)",
        "Step path evaluated on each ECB date (effective dates).", FX_ALIGN),
    "inr_rate_3m_pa": ColumnMeta(
        "INR 3-month money-market rate (ACT/365)", "rate_pa", "PROXY",
        "RBI repo path + OECD MEI India short-term rate IR3TIB (monthly) via sdmx.oecd.org",
        "repo(d) + [OECD month average - calendar-month mean repo]; months without an OECD print use "
        "inr_term_spread_3m_pa. Same-month average => <= 1 month look-ahead.", FX_ALIGN),
    "usd_rate_3m_pa": ColumnMeta(
        "USD 3-month money-market rate (ACT/360)", "rate_pa", "PROXY",
        "US Treasury daily bill rates, 13-week coupon equivalent (home.treasury.gov)",
        f"Bond-equivalent yield x 360/365; <= {MAX_FILL_BDAYS}-row carry over Treasury holidays "
        "(usd_rate_3m_filled); online-only per-year fallback fed funds upper + usd_term_spread_3m_pa, labelled in "
        "rates_src (offline cache misses raise).", FX_ALIGN),
    "usd_rate_3m_filled": ColumnMeta(
        "True when usd_rate_3m_pa is a carried Treasury print (US holiday) or the whole FX row was carried", "bool",
        "PROXY", "US Treasury bill calendar vs ECB / LME calendars",
        "fx_rates_daily.csv usd_rate_3m_filled OR panel usdinr_filled; flagged like the series it qualifies.", FX_ALIGN),
    "rates_src": ColumnMeta(
        "Origin of the 3M rates: USD:<UST13W|FALLBACK_FEDFUNDS_SPREAD>|INR:<OECD_IR3TIB|FALLBACK_REPO_SPREAD>", "text",
        "PROXY", "desk.data.fetch_fx", "Label carried from fx_rates_daily.csv; flagged like the series it qualifies.",
        FX_ALIGN),
    "fwd_premium_3m_pa": ColumnMeta(
        "Annualised 3M USD/INR forward premium", "rate_pa", "PROXY", "Derived (covered interest parity)",
        "(usdinr_fwd_3m / usdinr - 1) x 365 / days_to_3M.", FX_ALIGN),
    "usdinr_fwd_1m": ColumnMeta(
        "1-month USD/INR outright forward", "inr_per_usd", "PROXY", "Derived (covered interest parity)",
        "desk.units.fx_forward(spot, inr_rate_3m_pa, usd_rate_3m_pa, days to same date +1M): flat short curve.",
        FX_ALIGN),
    "usdinr_fwd_3m": ColumnMeta(
        "3-month USD/INR outright forward", "inr_per_usd", "PROXY", "Derived (covered interest parity)",
        "desk.units.fx_forward(spot, inr_rate_3m_pa, usd_rate_3m_pa, days to same date +3M).", FX_ALIGN),
    "mcx_al_spot_inr_kg": ColumnMeta(
        "MCX Aluminium spot-equivalent (duty-paid import parity)", "inr_per_kg", "PROXY",
        "desk.data.mcx (LME cash x usdinr; regulatory.yaml bcd_primary_al_hs7601, sws_rate_on_bcd; "
        "market_proxy.yaml mcx_domestic_premium_inr_kg)",
        "PROXY: lme_cash_usd_t x usdinr / 1000 x (1 + BCD x (1 + SWS)) + premium. MANUAL: M1 close with carry "
        "stripped at inr_rate_3m_pa."),
    "mcx_al_m1_inr_kg": ColumnMeta(
        "MCX Aluminium near-month (M1) futures price", "inr_per_kg", "PROXY", "desk.data.mcx",
        "PROXY: spot x (1 + inr_rate_3m_pa x days_to_m1_expiry / 365). MANUAL: bhavcopy close of nearest "
        "unexpired contract."),
    "mcx_al_m2_inr_kg": ColumnMeta(
        "MCX Aluminium second-month (M2) futures price", "inr_per_kg", "PROXY", "desk.data.mcx",
        "PROXY: spot x (1 + inr_rate_3m_pa x days_to_m2_expiry / 365). MANUAL: bhavcopy close of next contract."),
    "mcx_m1_expiry": ColumnMeta(
        "Expiry date of the M1 contract", "date_yyyy_mm_dd", "ASSUMPTION",
        "Rule from exchange.yaml mcx_al_expiry_rule applied to the LME calendar (CONTRACTS §3: MCX holidays not "
        "modelled)",
        "Last calendar day of month, rolled back to previous panel day. Real 2022 MCX expiries: exchange.yaml "
        "mcx_al_expiry_dates_2022."),
    "mcx_m2_expiry": ColumnMeta(
        "Expiry date of the M2 contract", "date_yyyy_mm_dd", "ASSUMPTION",
        "Same rule as mcx_m1_expiry", "Expiry of the month after M1."),
    "mcx_src": ColumnMeta(
        "Origin of MCX columns: PROXY_IMPORT_PARITY, MANUAL, or MANUAL_FFILL (MCX non-trading day inside manual "
        "coverage; this label is the MCX fill flag)", "text", "PROXY", "desk.data.mcx",
        "Label; flagged like the series it qualifies."),
    "freight_jea_nsa_usd_t": ColumnMeta(
        "Ocean freight Jebel Ali -> Nhava Sheva (20ft), per MT of scrap", "usd_per_mt", "ASSUMPTION",
        "logistics.yaml freight_jea_nsa_usd_box_ref (assumed USD/20ft at freight_jea_nsa_ref_date) x USEC_MUN "
        "weekly shape",
        "USD/box / container_payload_mt_20ft. Level is a judgement (no citable 2022 quote); shape PROXY.",
        FREIGHT_ALIGN),
    "freight_usec_mun_usd_t": ColumnMeta(
        "Ocean freight US East Coast -> Mundra (40ft), per MT of scrap", "usd_per_mt", "ASSUMPTION",
        f"SHAPE (PROXY): Drewry WCI composite via Internet Archive snapshots of {fetch_freight.DREWRY_WCI_URL}. "
        "LEVEL (ASSUMPTION, CONTRACTS §4.3): Container News USEC->West India monthly rates where reported, else a "
        "Europe->West India sibling-lane bridge or a flat extrapolation (logistics.yaml)",
        "WCI x k(t) with k log-linear between Container News anchors (flat outside) / container_payload_mt_40ft. "
        "Column flag = weakest (level). Filter on freight_src (USEC:ANCHORED rows are the best-supported level), "
        "not on this flag.", FREIGHT_ALIGN),
    "freight_filled": ColumnMeta(
        "True when the freight value was assessed on an earlier day than the LME day (point-in-time carry)", "bool",
        "ASSUMPTION", "freight_weekly.csv Thursday assessment calendar vs LME calendar",
        "Indicator; flagged like the weakest series it qualifies (freight levels).", FREIGHT_ALIGN),
    "freight_src": ColumnMeta(
        "Weekly provenance label <WCI shape>|USEC:<level>|JEA:ASSUMPTION, or NO_FREIGHT_DATA", "text",
        "ASSUMPTION", "desk.data.fetch_freight",
        "Label carried from freight_weekly.csv; flagged like the weakest series it qualifies.", FREIGHT_ALIGN),
}


class UpstreamMissingError(RuntimeError):
    """An upstream Phase 0 builder has not produced its file; the panel refuses to guess its contents."""


# --------------------------------------------------------------------------------------------- upstream readers
def _read(path, date_col: str, producer: str) -> pd.DataFrame:
    if not path.exists():
        raise UpstreamMissingError(
            f"{path} is missing — run `{producer}.main()` first. build_panel will not invent data for it.")
    df = pd.read_csv(path)
    df[date_col] = pd.to_datetime(df[date_col], format="%Y-%m-%d")
    if not df[date_col].is_unique or not df[date_col].is_monotonic_increasing:
        raise ValueError(f"{path.name}: {date_col} must be unique and sorted")
    return df


def load_lme() -> pd.DataFrame:
    lme = _read(LME_PATH, "date", "desk.data.fetch_lme")
    if list(lme.columns) != fetch_lme.COLUMNS:
        raise ValueError(f"lme_daily.csv columns {list(lme.columns)} != {fetch_lme.COLUMNS}")
    lme = lme[(lme["date"] >= pd.Timestamp(HISTORY_START)) & (lme["date"] <= PANEL_END)].reset_index(drop=True)
    if lme["date"].iloc[0] != pd.Timestamp(HISTORY_START) or lme["date"].iloc[-1] != PANEL_END:
        raise ValueError(f"LME calendar must span {HISTORY_START}..{PANEL_END.date()}, got "
                         f"{lme['date'].iloc[0].date()}..{lme['date'].iloc[-1].date()}")
    return lme


def load_fx() -> pd.DataFrame:
    fx = _read(FX_PATH, "date", "desk.data.fetch_fx")
    if list(fx.columns) != fetch_fx.COLUMNS:
        raise ValueError(f"fx_rates_daily.csv columns {list(fx.columns)} != {fetch_fx.COLUMNS}")
    return fx


def load_freight() -> pd.DataFrame:
    fr = _read(FREIGHT_PATH, "week_end", "desk.data.fetch_freight")
    if (fr["week_end"].dt.dayofweek != 4).any():
        raise ValueError("freight_weekly.csv week_end must be Fridays")
    return fr


# --------------------------------------------------------------------------------------------- alignment
def _bday_gap(src: pd.Series, dates: pd.Series) -> np.ndarray:
    return np.busday_count(src.to_numpy().astype("datetime64[D]"), dates.to_numpy().astype("datetime64[D]"))


def align_fx(dates: pd.Series, fx: pd.DataFrame) -> pd.DataFrame:
    """FX/rate columns on LME days: latest ECB-calendar row on or before each day."""
    src = fx.rename(columns={"date": "fx_date"}).assign(date=fx["date"])
    m = pd.merge_asof(pd.DataFrame({"date": dates}), src, on="date", direction="backward")
    if m["fx_date"].isna().any():
        raise ValueError(f"No FX row on/before {m.loc[m['fx_date'].isna(), 'date'].dt.date.tolist()[:5]}")
    gap = _bday_gap(m["fx_date"], m["date"])
    if (gap > MAX_FILL_BDAYS).any():
        bad = m.loc[gap > MAX_FILL_BDAYS, "date"].dt.date.tolist()
        raise ValueError(f"FX gap > {MAX_FILL_BDAYS} business days on {bad[:10]}")
    out = m[["date"] + [c for c in fetch_fx.COLUMNS if c != "date"]].copy()
    out["usdinr_filled"] = (m["fx_date"] != m["date"]).to_numpy()
    return out


def align_freight(dates: pd.Series, fr: pd.DataFrame) -> pd.DataFrame:
    """Freight on LME days: the latest weekly row already assessed (Thursday = week_end − 1) on or before the day."""
    lanes = ["freight_jea_nsa_usd_t", "freight_usec_mun_usd_t", "freight_src"]
    src = fr.assign(assessed=fr["week_end"] - pd.Timedelta(days=1)).sort_values("assessed")
    m = pd.merge_asof(pd.DataFrame({"date": dates.to_numpy()}), src.assign(date=src["assessed"]),
                      on="date", direction="backward")
    covered = m["assessed"].notna().to_numpy()
    if covered.any():
        gap = _bday_gap(m.loc[covered, "assessed"], m.loc[covered, "date"])
        if (gap > MAX_FILL_BDAYS).any():
            bad = m.loc[covered, "date"][gap > MAX_FILL_BDAYS].dt.date.tolist()
            raise ValueError(f"Freight gap > {MAX_FILL_BDAYS} business days on {bad[:10]}")
    out = m[lanes].copy()
    out.loc[~covered, "freight_src"] = NO_FREIGHT
    out["freight_filled"] = covered & (m["assessed"] != m["date"]).to_numpy()
    out.index = dates.index
    return out


# --------------------------------------------------------------------------------------------- build
def build() -> pd.DataFrame:
    lme = load_lme()
    fx = load_fx()
    fr = load_freight()
    dates = lme["date"]
    panel = lme.copy()
    panel.insert(1, "in_window", ((dates >= pd.Timestamp(WINDOW_START)) & (dates <= pd.Timestamp(WINDOW_END))))
    fxa = align_fx(dates, fx)
    for col in FX_COLUMNS:
        panel[col] = fxa[col].to_numpy()
    panel["usdinr_filled"] = panel["usdinr_filled"].astype(bool)
    panel["usd_rate_3m_filled"] = panel["usd_rate_3m_filled"].astype(bool) | panel["usdinr_filled"]
    panel = mcx.load_or_proxy_mcx(panel)
    fra = align_freight(dates, fr)
    for col in FREIGHT_COLUMNS:
        panel[col] = fra[col].to_numpy()
    panel["freight_filled"] = panel["freight_filled"].astype(bool)
    panel["usdinr_filled"] = panel["usdinr_filled"].astype(bool)
    panel["in_window"] = panel["in_window"].astype(bool)
    for col in ("freight_jea_nsa_usd_t", "freight_usec_mun_usd_t"):
        panel[col] = panel[col].astype(float)
    panel["date"] = panel["date"].dt.strftime("%Y-%m-%d")
    return panel[PANEL_COLUMNS]


def validate(panel: pd.DataFrame) -> None:
    if list(panel.columns) != PANEL_COLUMNS:
        raise ValueError("panel columns differ from CONTRACTS §4.5")
    if not panel["date"].is_unique or not panel["date"].is_monotonic_increasing:
        raise ValueError("panel dates must be unique and sorted")
    win = panel[panel["in_window"]]
    if win.empty or win[PANEL_COLUMNS].isna().any().any():
        raise ValueError(f"NaNs in window: {win.isna().sum()[lambda s: s > 0].to_dict()}")
    core = [c for c in PANEL_COLUMNS if c not in FREIGHT_COLUMNS]
    if panel[core].isna().any().any():
        raise ValueError(f"NaNs in non-freight columns: {panel[core].isna().sum()[lambda s: s > 0].to_dict()}")
    no_fr = panel["freight_src"] == NO_FREIGHT
    if not (panel.loc[no_fr, ["freight_jea_nsa_usd_t", "freight_usec_mun_usd_t"]].isna().all().all()
            and panel.loc[~no_fr, ["freight_jea_nsa_usd_t", "freight_usec_mun_usd_t"]].notna().all().all()):
        raise ValueError("freight NaNs must coincide exactly with freight_src == NO_FREIGHT_DATA")
    parity = panel["mcx_al_spot_inr_kg"] / (panel["lme_cash_usd_t"] * panel["usdinr"] / 1000.0)
    if not parity.between(0.8, 1.4).all():
        raise ValueError("MCX spot / (LME cash x USDINR / 1000) outside [0.8, 1.4]: units error")
    if not ((panel["mcx_m1_expiry"] >= panel["date"]) & (panel["mcx_m2_expiry"] > panel["mcx_m1_expiry"])).all():
        raise ValueError("MCX expiry ordering broken")


def _counts(s: pd.Series) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(s.astype(str).value_counts().to_dict().items()))


def build_provenance(panel: pd.DataFrame) -> pd.DataFrame:
    """One row per panel column. Flags depend on which sources actually fed the panel (never promoted silently).

    * usdinr*: DIRECT only if every panel day is MANUAL_RBI.
    * MCX: DIRECT only if no panel day is PROXY_IMPORT_PARITY (MANUAL_FFILL days are counted and reported separately).
    * Rate / forward columns: PROXY with the real 3M series; downgraded to ASSUMPTION, with the source text rewritten,
      if any panel day used a policy-rate + term-spread FALLBACK (rates_src).
    * Freight: the window's USEC level tags are reported so readers can see how much of the level is anchored.
    """
    n = len(panel)
    fx_src = panel["usdinr_src"].value_counts().to_dict()
    mcx_src = panel["mcx_src"].value_counts().to_dict()
    usdinr_flag = "DIRECT" if fx_src.get("MANUAL_RBI", 0) == n else "PROXY"
    mcx_flag = "DIRECT" if mcx_src.get(mcx.SRC_PROXY, 0) == 0 else "PROXY"
    usd_fb = int(panel["rates_src"].str.contains(fetch_fx.USD_SRC_FALLBACK).sum())
    inr_fb = int(panel["rates_src"].str.contains(fetch_fx.INR_SRC_FALLBACK).sum())
    win = panel[panel["in_window"]]
    usec_levels = win["freight_src"].str.extract(r"USEC:(\w+)")[0].fillna(NO_FREIGHT)
    rows = []
    for col in PANEL_COLUMNS:
        meta = PANEL_META[col]
        flag, source, extra = meta.flag, meta.source, ""
        if col in ("usdinr", "usdinr_src", "usdinr_filled"):
            flag = usdinr_flag
            extra = f" Sources on panel days: {_counts(panel['usdinr_src'])}."
        elif col in ("mcx_al_spot_inr_kg", "mcx_al_m1_inr_kg", "mcx_al_m2_inr_kg", "mcx_src"):
            flag = mcx_flag
            extra = (f" Sources on panel days: {_counts(panel['mcx_src'])} "
                     f"({mcx.SRC_MANUAL_FFILL} = carried over an MCX non-trading day).")
        elif col in RATE_COLUMNS:
            extra = f" rates_src on panel days: {_counts(panel['rates_src'])}."
            if col == "usd_rate_3m_filled":
                extra += f" Carried days: {int(panel['usd_rate_3m_filled'].sum())}."
            if usd_fb or inr_fb:
                flag = "ASSUMPTION"
                source = (f"FALLBACK USED — USD fed funds upper + usd_term_spread_3m_pa on {usd_fb} days; INR repo + "
                          f"inr_term_spread_3m_pa on {inr_fb} days; real series elsewhere: {meta.source}")
        elif col in ("freight_usec_mun_usd_t", "freight_jea_nsa_usd_t", "freight_filled", "freight_src"):
            extra = f" Window USEC level tags (days): {_counts(usec_levels)}."
        rows.append({"column": col, "flag": flag, "source": source,
                     "transformation": meta.transformation + meta.align + extra, "unit": meta.unit})
    return pd.DataFrame(rows, columns=PROVENANCE_COLUMNS)


# --------------------------------------------------------------------------------------------- chart
def plot_overview(panel: pd.DataFrame) -> str:
    """Four-panel Phase 0 overview (2021-2022 so the window and the run-up are both legible)."""
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    from desk.reporting.style import PALETTE, save_fig

    df = panel.assign(date=pd.to_datetime(panel["date"])).set_index("date")
    df = df[df.index >= CHART_START]
    w0, w1 = pd.Timestamp(WINDOW_START), pd.Timestamp(WINDOW_END)
    peak_day = df["lme_cash_usd_t"].idxmax()
    peak = df.loc[peak_day]

    fig, axes = plt.subplots(4, 1, figsize=(11, 13), sharex=True)
    for ax in axes:
        ax.axvspan(w0, w1, color=PALETTE["band"], alpha=0.6, lw=0, label="_nolegend_")

    ax = axes[0]
    ax.plot(df.index, df["lme_cash_usd_t"], color=PALETTE["lme"], lw=1.2, label="LME cash (official)")
    ax.plot(df.index, df["lme_3m_usd_t"], color=PALETTE["neutral"], lw=1.0, label="LME 3M (official)")
    ax.annotate(f"{peak_day:%d %b %Y}: cash ${peak['lme_cash_usd_t']:,.1f}/t\n(highest in 2018-22 panel)",
                xy=(peak_day, peak["lme_cash_usd_t"]), xytext=(peak_day - pd.Timedelta(days=330),
                                                              peak["lme_cash_usd_t"] - 150),
                arrowprops={"arrowstyle": "->", "color": "#404040"}, fontsize=8.5)
    ax.set_title("LME Aluminium official prices (USD/MT) [DIRECT, Westmetall]")
    ax.set_ylabel("USD/MT")
    ax.legend(loc="center left")
    ax.text(w0 + (w1 - w0) / 2, ax.get_ylim()[0], "headline window\nMar-Aug 2022", ha="center", va="bottom",
            fontsize=8, color="#404040")

    ax = axes[1]
    s = df["lme_cash_3m_spread_usd_t"]
    ax.fill_between(df.index, s, 0, where=s >= 0, color=PALETTE["loss"], alpha=0.45, lw=0,
                    label="backwardation (cash > 3M)")
    ax.fill_between(df.index, s, 0, where=s < 0, color=PALETTE["gain"], alpha=0.45, lw=0,
                    label="contango (cash < 3M)")
    ax.plot(df.index, s, color="#404040", lw=0.6)
    ax.axhline(0, color="#404040", lw=0.6)
    ax.set_title("LME Cash-3M spread (USD/MT) [DIRECT]")
    ax.set_ylabel("USD/MT")
    ax.legend(loc="upper left")

    ax = axes[2]
    ax.plot(df.index, df["usdinr"], color=PALETTE["fx"], lw=1.2, label="USD/INR (ECB cross)")
    ax.set_title("USD/INR spot, INR per USD [PROXY, ECB EUR/INR / EUR/USD]")
    ax.set_ylabel("INR per USD")
    ax.legend(loc="upper left")

    ax = axes[3]
    label = "MCX Aluminium M1 (import-parity proxy)" if (df["mcx_src"] == mcx.SRC_PROXY).all() \
        else "MCX Aluminium M1 (manual bhavcopy / proxy)"
    ax.plot(df.index, df["mcx_al_m1_inr_kg"], color=PALETTE["mcx"], lw=1.2, label=label)
    ax.set_ylabel("INR/kg")
    ax.set_title("MCX Aluminium (INR/kg) [PROXY] and lane freight (USD/MT) [PROXY shape / ASSUMPTION level]")
    ax2 = ax.twinx()
    ax2.plot(df.index, df["freight_usec_mun_usd_t"], color=PALETTE["freight"], lw=1.1,
             label="Freight USEC->Mundra 40ft (ASSUMPTION level, WCI shape)")
    ax2.plot(df.index, df["freight_jea_nsa_usd_t"], color=PALETTE["freight"], lw=1.1, ls="--",
             label="Freight Jebel Ali->Nhava Sheva 20ft (ASSUMPTION level)")
    ax2.set_ylabel("USD per MT of scrap")
    ax2.grid(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    fig.suptitle("Phase 0 market panel, Jan 2021 - Dec 2022 (shaded: headline window 1 Mar - 31 Aug 2022)",
                 fontweight="bold", y=0.995)
    fig.tight_layout(rect=(0, 0.015, 1, 0.99))
    raw = [fetch_lme.raw_path(y) for y in fetch_lme.YEARS] + [fetch_fx.ecb_cache_path(c) for c in ("INR", "USD")]
    note = ("Sources: LME = Westmetall official tables; USD/INR = ECB cross; MCX = duty-paid LME import parity; "
            f"freight = Drewry WCI shape + Container News anchors; LME/ECB data {retrieval_note(raw)}")
    return save_fig(fig, CHART_NAME, source_note=note)


def main() -> None:
    panel = build()
    validate(panel)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUT_PATH, index=False, lineterminator="\n")
    prov = build_provenance(panel)
    prov.to_csv(PROVENANCE_PATH, index=False, lineterminator="\n")
    win = panel[panel["in_window"]]
    flags = prov["flag"].value_counts().to_dict()
    print(f"[build_panel] {panel.shape[0]} rows x {panel.shape[1]} cols {panel['date'].iloc[0]}..{panel['date'].iloc[-1]}"
          f"; window rows={len(win)}; usdinr_filled={int(panel['usdinr_filled'].sum())}; "
          f"usd_rate_3m_filled={int(panel['usd_rate_3m_filled'].sum())}; "
          f"freight_filled={int(panel['freight_filled'].sum())}; no-freight days={int((panel['freight_src'] == NO_FREIGHT).sum())}"
          f"; column flags={flags} -> {OUT_PATH}")
    print(f"[build_panel] chart -> {plot_overview(panel)}")


if __name__ == "__main__":
    main()
