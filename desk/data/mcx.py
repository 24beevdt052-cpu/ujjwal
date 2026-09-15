"""MCX Aluminium (5 MT lot, ₹/kg) spot / M1 / M2 columns for the daily panel — real bhavcopy data if present, else proxy.

`load_or_proxy_mcx(panel)` is called by `desk.data.build_panel` (CONTRACTS.md §4.5). It never touches the network:
MCX data can only arrive as files a human (or a fetch attempt) placed in `data/manual/`.

1. **DIRECT path — `data/manual/mcx_aluminium_*.csv` (bhavcopy extracts).** Format, one row per trade date × contract:

       date,contract_expiry,close_inr_kg,source[,symbol]
       <YYYY-MM-DD>,<YYYY-MM-DD>,<close ₹/kg>,"<MCX bhavcopy file name / mcxindia.com URL>",ALUMINIUM  (placeholders)

   `date` = trade date (YYYY-MM-DD), `contract_expiry` = that contract's expiry date, `close_inr_kg` = MCX close or
   settlement price in ₹/kg, `source` = REQUIRED on every row and must name an MCX bhavcopy file or an mcxindia.com
   URL — a file that upgrades the panel to DIRECT must say where each price came from, otherwise it is rejected.
   On each panel day M1 = the listed contract with the nearest expiry on/after the date, M2 = the next one; spot (MCX
   publishes no tradable aluminium spot in the bhavcopy) is M1 with its carry stripped at `inr_rate_3m_pa`. A panel
   day with no MCX row carries the previous MCX row forward (`mcx_src = MANUAL_FFILL`, ≤ MAX_FILL_BDAYS business days)
   ONLY when the manual files also have a later trade date — i.e. a genuine MCX non-trading day inside the covered
   range. Days before the first or after the last manual trade date fall back to the proxy, never to a stale close.

2. **PROXY path (`mcx_src = PROXY_IMPORT_PARITY`).** MCX Aluminium trades at duty-paid import parity, so
       spot = lme_cash_usd_t × usdinr / 1000 × (1 + bcd_primary_al_hs7601 × (1 + sws_rate_on_bcd))
              + mcx_domestic_premium_inr_kg
       m_k  = spot × (1 + inr_rate_3m_pa × days_to_expiry_k / 365)
   with MCX expiry = last calendar day of the month, moved back to the previous panel day (previous weekday beyond
   the panel's end) when it is not a trading day.

A third-party mirror of continuous MCX Aluminium closes (commoditieschart.net) is downloaded by
`desk.data.fetch_mcx_mirror` into `data/raw/mcx_thirdparty/` (raw pages) and extracted to
`data/interim/mcx_thirdparty_commoditieschart_2017_2022.csv`. It calibrates `mcx_domestic_premium_inr_kg` and feeds
the proxy-vs-observed study (`proxy_vs_observed`), but is never promoted to DIRECT: its provenance cannot be checked
against MCX's own bhavcopy and its roll convention (hence contract expiries) is undocumented. It lives outside
`data/manual/` so it can never match the DIRECT glob. See docs/research/market_data_notes.md.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from desk import MAX_FILL_BDAYS, config, units
from desk.paths import INTERIM_DIR, MANUAL_DIR, RAW_DIR

MANUAL_GLOB = "mcx_aluminium_*.csv"
SRC_MANUAL = "MANUAL"
SRC_MANUAL_FFILL = "MANUAL_FFILL"
SRC_PROXY = "PROXY_IMPORT_PARITY"
MAX_FFILL_BDAYS = MAX_FILL_BDAYS
MANUAL_SOURCE_RE = r"(?i)(?:bhav|mcxindia\.com|\bMCX\b)"
MCX_COLUMNS = ["mcx_al_spot_inr_kg", "mcx_al_m1_inr_kg", "mcx_al_m2_inr_kg", "mcx_m1_expiry", "mcx_m2_expiry", "mcx_src"]

THIRDPARTY_RAW_DIR = RAW_DIR / "mcx_thirdparty"
THIRDPARTY_NEAREST_HTML = THIRDPARTY_RAW_DIR / "commoditieschart_mcx_aluminium_nearest_raw.html"
THIRDPARTY_2M_HTML = THIRDPARTY_RAW_DIR / "commoditieschart_mcx_aluminium_2m_raw.html"
THIRDPARTY_LME_HTML = THIRDPARTY_RAW_DIR / "commoditieschart_lme_aluminium_raw.html"
THIRDPARTY_CSV = INTERIM_DIR / "mcx_thirdparty_commoditieschart_2017_2022.csv"
THIRDPARTY_URLS = {
    "m1_close_inr_kg": "https://commoditieschart.net/metals/aluminium/mcx-aluminium-futures-prices",
    "m2_close_inr_kg": "https://commoditieschart.net/metals/aluminium/mcx-aluminium-2m-futures-prices",
    "lme_usd_t": "https://commoditieschart.net/metals/aluminium/lme-aluminium-usd-prices",
}
_POINT_RE = re.compile(r'\{d:"(\d{4}-\d{2}-\d{2})",v:(-?[\d.]+)')


# --------------------------------------------------------------------------------------------- contract calendar
def month_expiry(month: pd.Period, panel_days: pd.DatetimeIndex) -> pd.Timestamp:
    """Last calendar day of `month`, rolled back to the previous panel day (or weekday beyond the panel)."""
    day = month.end_time.normalize()
    last_panel = panel_days.max()
    while True:
        if day <= last_panel:
            if day in panel_days:
                return day
        elif day.dayofweek < 5:
            return day
        day -= pd.Timedelta(days=1)


def contract_calendar(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """M1/M2 expiry for each date: M1 is the current month's contract until (and including) its expiry day."""
    dates = pd.DatetimeIndex(dates)
    months = pd.period_range(dates.min().to_period("M"), dates.max().to_period("M") + 2, freq="M")
    expiry = {m: month_expiry(m, dates) for m in months}
    cur = dates.to_period("M")
    m1 = np.where(dates <= pd.DatetimeIndex([expiry[m] for m in cur]), cur, cur + 1)
    m1 = pd.PeriodIndex(m1, freq="M")
    return pd.DataFrame(
        {"mcx_m1_expiry": [expiry[m] for m in m1], "mcx_m2_expiry": [expiry[m + 1] for m in m1]}, index=dates
    )


def _param_series(key: str, dates: pd.DatetimeIndex) -> np.ndarray:
    return config.get(key).series(dates).astype(float).to_numpy()


def duty_factor(dates: pd.DatetimeIndex) -> np.ndarray:
    """(1 + BCD × (1 + SWS)) for primary aluminium; date-aware in case regulatory.yaml turns these into paths."""
    return 1.0 + _param_series("bcd_primary_al_hs7601", dates) * (1.0 + _param_series("sws_rate_on_bcd", dates))


def carry(rate_pa: np.ndarray, days: np.ndarray) -> np.ndarray:
    return 1.0 + rate_pa * days / units.DAY_COUNT_INR


# --------------------------------------------------------------------------------------------- proxy
def proxy_mcx(panel: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DatetimeIndex(pd.to_datetime(panel["date"]))
    cal = contract_calendar(dates)
    spot = (units.usd_t_to_inr_kg(panel["lme_cash_usd_t"].to_numpy(float), panel["usdinr"].to_numpy(float))
            * duty_factor(dates) + _param_series("mcx_domestic_premium_inr_kg", dates))
    rate = panel["inr_rate_3m_pa"].to_numpy(float)
    d1 = (cal["mcx_m1_expiry"].to_numpy() - dates.to_numpy()).astype("timedelta64[D]").astype(float)
    d2 = (cal["mcx_m2_expiry"].to_numpy() - dates.to_numpy()).astype("timedelta64[D]").astype(float)
    return pd.DataFrame(
        {
            "mcx_al_spot_inr_kg": spot,
            "mcx_al_m1_inr_kg": spot * carry(rate, d1),
            "mcx_al_m2_inr_kg": spot * carry(rate, d2),
            "mcx_m1_expiry": cal["mcx_m1_expiry"].to_numpy(),
            "mcx_m2_expiry": cal["mcx_m2_expiry"].to_numpy(),
            "mcx_src": SRC_PROXY,
        },
        index=panel.index,
    )


# --------------------------------------------------------------------------------------------- manual (DIRECT)
def load_manual_files(manual_dir: Path = MANUAL_DIR) -> pd.DataFrame | None:
    files = sorted(Path(manual_dir).glob(MANUAL_GLOB))
    if not files:
        return None
    frames = []
    for f in files:
        df = pd.read_csv(f)
        missing = {"date", "contract_expiry", "close_inr_kg", "source"} - set(df.columns)
        if missing:
            raise ValueError(f"{f.name}: missing columns {sorted(missing)} "
                             "(expected date,contract_expiry,close_inr_kg,source)")
        src = df["source"].fillna("").astype(str)
        named = src.str.contains(MANUAL_SOURCE_RE, regex=True)
        if not named.all():
            raise ValueError(f"{f.name}: rows {df.loc[~named, 'date'].tolist()[:5]} have a `source` that names no MCX "
                             "bhavcopy file or mcxindia.com URL; refusing to label them DIRECT")
        df = df[["date", "contract_expiry", "close_inr_kg"]].copy()
        df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
        df["contract_expiry"] = pd.to_datetime(df["contract_expiry"], format="%Y-%m-%d")
        df["close_inr_kg"] = df["close_inr_kg"].astype(float)
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    if out.duplicated(["date", "contract_expiry"]).any():
        raise ValueError("MCX manual files contain duplicate (date, contract_expiry) rows")
    if (out["close_inr_kg"] <= 0).any():
        raise ValueError("MCX manual files contain non-positive prices")
    if (out["contract_expiry"] < out["date"]).any():
        raise ValueError("MCX manual files contain contracts traded after expiry")
    return out.sort_values(["date", "contract_expiry"]).reset_index(drop=True)


def manual_mcx(panel: pd.DataFrame, manual: pd.DataFrame) -> pd.DataFrame:
    """M1/M2 from bhavcopy rows on each panel date, or carried over an MCX non-trading day; NaN elsewhere.

    A carry is allowed only strictly inside the manual coverage (a later manual trade date exists) and for at most
    MAX_FFILL_BDAYS business days, so a stale close is never extended past the end of the supplied files.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(panel["date"]))
    wide = manual.pivot(index="date", columns="contract_expiry", values="close_inr_kg").sort_index()
    last_mcx_day = pd.Series(wide.index, index=wide.index).reindex(dates, method="ffill")
    last_manual = wide.index.max()
    rows = []
    for d, src_day in zip(dates, last_mcx_day):
        outside = pd.isna(src_day) or (src_day != d and d > last_manual)
        if outside or np.busday_count(src_day.date(), d.date()) > MAX_FFILL_BDAYS:
            rows.append((np.nan, np.nan, pd.NaT, pd.NaT, None))
            continue
        quotes = wide.loc[src_day].dropna()
        live = quotes[quotes.index >= d]
        if len(live) < 2:
            rows.append((np.nan, np.nan, pd.NaT, pd.NaT, None))
            continue
        src = SRC_MANUAL if src_day == d else SRC_MANUAL_FFILL
        rows.append((live.iloc[0], live.iloc[1], live.index[0], live.index[1], src))
    out = pd.DataFrame(rows, columns=["mcx_al_m1_inr_kg", "mcx_al_m2_inr_kg", "mcx_m1_expiry", "mcx_m2_expiry",
                                      "mcx_src"], index=panel.index)
    d1 = (out["mcx_m1_expiry"] - dates.to_series(index=panel.index)).dt.days.to_numpy(float)
    out["mcx_al_spot_inr_kg"] = out["mcx_al_m1_inr_kg"].to_numpy() / carry(panel["inr_rate_3m_pa"].to_numpy(float), d1)
    return out[MCX_COLUMNS]


# --------------------------------------------------------------------------------------------- public API
def load_or_proxy_mcx(panel: pd.DataFrame, manual_dir: Path = MANUAL_DIR) -> pd.DataFrame:
    """Return `panel` with the six CONTRACTS §4.5 MCX columns added (expiries as YYYY-MM-DD strings)."""
    required = {"date", "lme_cash_usd_t", "usdinr", "inr_rate_3m_pa"}
    if missing := required - set(panel.columns):
        raise ValueError(f"panel missing columns {sorted(missing)}")
    mcx = proxy_mcx(panel)
    manual = load_manual_files(manual_dir)
    if manual is not None:
        real = manual_mcx(panel, manual)
        has_real = real["mcx_src"].notna()
        mcx.loc[has_real, MCX_COLUMNS] = real.loc[has_real, MCX_COLUMNS]
        print(f"[mcx] manual MCX rows used on {int(has_real.sum())}/{len(panel)} panel days; proxy elsewhere")
    else:
        print(f"[mcx] no {MANUAL_GLOB} in {manual_dir}; using {SRC_PROXY} on all {len(panel)} days")
    out = panel.drop(columns=[c for c in MCX_COLUMNS if c in panel.columns]).copy()
    for col in MCX_COLUMNS:
        out[col] = mcx[col].to_numpy()
    for col in ("mcx_m1_expiry", "mcx_m2_expiry"):
        out[col] = pd.to_datetime(out[col]).dt.strftime("%Y-%m-%d")
    for col in ("mcx_al_spot_inr_kg", "mcx_al_m1_inr_kg", "mcx_al_m2_inr_kg"):
        out[col] = out[col].astype(float).round(4)
    return out


# --------------------------------------------------------------------------------------------- third-party mirror
def parse_thirdparty_html(path: Path) -> pd.Series:
    """Extract the `{d:"YYYY-MM-DD",v:<price>}` points embedded in a commoditieschart.net page (offline, cached HTML)."""
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    points = _POINT_RE.findall(raw)
    if not points:
        raise ValueError(f"no data points found in {path}")
    s = pd.Series({pd.Timestamp(d): float(v) for d, v in points}).sort_index()
    return s[~s.index.duplicated(keep="last")]


def build_thirdparty_csv(start: str = "2017-12-01", end: str = "2022-12-31") -> pd.DataFrame:
    """Regenerate THIRDPARTY_CSV from the saved raw pages (no network)."""
    m1 = parse_thirdparty_html(THIRDPARTY_NEAREST_HTML).rename("m1_close_inr_kg")
    m2 = parse_thirdparty_html(THIRDPARTY_2M_HTML).rename("m2_close_inr_kg")
    df = pd.concat([m1, m2], axis=1, sort=True).loc[start:end]
    df.index.name = "date"
    df = df.reset_index()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df


def load_thirdparty() -> pd.DataFrame | None:
    if not THIRDPARTY_CSV.exists():
        return None
    return pd.read_csv(THIRDPARTY_CSV, parse_dates=["date"]).set_index("date")


def proxy_vs_observed(panel: pd.DataFrame, observed_m1: pd.Series, start=None, end=None) -> dict[str, float]:
    """Table 1.3 statistics: proxy M1 vs observed nearest-contract closes on common days in [start, end]."""
    proxy = proxy_mcx(panel)
    p = pd.Series(proxy["mcx_al_m1_inr_kg"].to_numpy(), index=pd.to_datetime(panel["date"]))
    j = pd.concat({"proxy": p, "obs": observed_m1}, axis=1, join="inner", sort=True).loc[start:end].dropna()
    r = np.log(j).diff().dropna()
    wk = np.log(j.resample("W-FRI").last()).diff().dropna()
    basis = j["obs"] - j["proxy"]
    return {
        "n_days": int(len(j)),
        "level_corr": float(j["proxy"].corr(j["obs"])),
        "daily_return_corr": float(r["proxy"].corr(r["obs"])),
        "daily_return_corr_proxy_lag1": float(r["proxy"].shift(1).corr(r["obs"])),
        "weekly_return_corr": float(wk["proxy"].corr(wk["obs"])),
        "basis_mean_inr_kg": float(basis.mean()),
        "basis_std_inr_kg": float(basis.std()),
        "basis_mean_pct_of_proxy": float((basis / j["proxy"]).mean()),
        "obs_daily_vol": float(r["obs"].std()),
        "proxy_daily_vol": float(r["proxy"].std()),
    }


def main() -> None:
    """No panel output here (build_panel calls load_or_proxy_mcx); the mirror is refreshed by fetch_mcx_mirror."""
    from desk.data import fetch_mcx_mirror

    fetch_mcx_mirror.main()


if __name__ == "__main__":
    main()
