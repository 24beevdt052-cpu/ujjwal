"""USD/INR spot, policy rates, 3-month money-market rates and CIP forwards -> data/processed/fx_rates_daily.csv.

Why each piece is built the way it is
-------------------------------------
* **usdinr (PROXY, ECB_CROSS).** The RBI reference rate has no stable bulk-download endpoint, while the ECB data API
  serves clean daily EUR/INR and EUR/USD reference rates. USD/INR = (INR per EUR) / (USD per EUR). Both ECB fixings
  are taken at the same 14:15 CET snapshot, so the cross is internally consistent. It is *expected* to be close to the
  RBI/FBIL 13:30 IST reference rate, but the gap has NOT been measured: no RBI/FBIL data is in the repo, the ECB
  snapshot is ~4–5 hours later, and in Mar–Aug 2022 the cross itself moved a median 12 paise a day (max 63), so a
  "few paise" gap cannot be assumed on volatile days. PENDING: compare >= 10 window dates with FBIL reference rates.
  A drop-in `data/manual/rbi_reference_rate.csv` (format in `load_manual_rbi`) overrides the cross on the dates it
  covers (`usdinr_src = MANUAL_RBI`).
* **rbi_repo_pa / fed_funds_upper_pa (DIRECT).** Step paths in `config/params/rates.yaml`, each step checked against
  the RBI MPC resolution / Federal Reserve open-market page (URLs in the YAML `verify` fields).
* **usd_rate_3m_pa (PROXY).** US Treasury daily 13-week bill rate (coupon-equivalent), converted to an ACT/360
  money-market yield (× 360/365) because `desk.units.fx_forward` treats the USD leg as ACT/360. A T-bill yield is a
  real, daily, public 3-month USD rate; it stands in for the interbank (LIBOR/SOFR-term) rate a bank would use.
  ECB days without a Treasury print (US holidays) carry the last print, at most `MAX_FILL_BDAYS` rows, and are
  flagged `usd_rate_3m_filled = True` (CONTRACTS §3).
* **inr_rate_3m_pa (PROXY).** OECD Main Economic Indicators "short-term interest rate" for India (IR3TIB, monthly
  average, %). It is real but monthly, so the daily path is `repo(d) + spread(month)`, where
  `spread(month) = OECD(month) − mean repo over that calendar month`. That keeps the monthly average on the published
  value while intra-month moves follow the actual RBI policy steps. Caveat: using the same month's average is a
  mild (≤ 1 month) look-ahead, acceptable for a market-data reconstruction, not for a signal.
* **Fallbacks are traceable, never silent.** Under `DESK_OFFLINE=1` a missing or invalid cache file RAISES — an
  offline rebuild must reproduce the cached data or fail, not quietly rewrite whole series. Online, a Treasury year
  that cannot be downloaded falls back to `fed_funds_upper + usd_term_spread_3m_pa` for the dates of that year only,
  and an unavailable OECD file (or a month without an OECD print) falls back to `repo + inr_term_spread_3m_pa`. Every
  row records what was used in `rates_src` = "USD:<UST13W|FALLBACK_FEDFUNDS_SPREAD>|INR:<OECD_IR3TIB|
  FALLBACK_REPO_SPREAD>", and `desk.data.build_panel` downgrades the provenance flag of every rate/forward column
  when any panel day used a fallback.
* **Forwards (PROXY).** Covered interest parity via `desk.units.fx_forward` using the 3M rates for both 1M and 3M
  tenors (flat short curve). `fwd_premium_3m_pa = (F3m / S − 1) × 365 / days` (Indian annualised-premium convention).
  Tenor days are calendar days from the quote date to the same date n months later (spot-lag ignored).

Output is on the ECB publication calendar (plus any extra MANUAL_RBI dates); `desk.data.build_panel` aligns it to
the LME calendar.
"""

from __future__ import annotations

import datetime as dt
import io

import numpy as np
import pandas as pd

from desk import MAX_FILL_BDAYS, config, units
from desk.data._http import FetchError, fetch_cached, offline
from desk.paths import MANUAL_DIR, PROCESSED_DIR, RAW_DIR

START = dt.date(2017, 12, 1)
END = dt.date(2022, 12, 31)
OUT_PATH = PROCESSED_DIR / "fx_rates_daily.csv"
MANUAL_RBI_PATH = MANUAL_DIR / "rbi_reference_rate.csv"
RATES_RAW_DIR = RAW_DIR / "rates"

ECB_URL = (
    "https://data-api.ecb.europa.eu/service/data/EXR/D.{ccy}.EUR.SP00.A"
    "?startPeriod={start}&endPeriod={end}&format=csvdata"
)
UST_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_bill_rates&field_tdr_date_value={year}&page&_format=csv"
)
UST_COLUMN = "13 WEEKS COUPON EQUIVALENT"
OECD_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0/IND.M.IR3TIB.PA....."
    "?startPeriod={start}&endPeriod={end}&dimensionAtObservation=AllDimensions"
)
OECD_HEADERS = {"Accept": "application/vnd.sdmx.data+csv; charset=utf-8"}

COLUMNS = [
    "date", "usdinr", "usdinr_src", "rbi_repo_pa", "fed_funds_upper_pa", "inr_rate_3m_pa", "usd_rate_3m_pa",
    "usd_rate_3m_filled", "rates_src", "fwd_premium_3m_pa", "usdinr_fwd_1m", "usdinr_fwd_3m",
]
USD_SRC_UST = "UST13W"
USD_SRC_FALLBACK = "FALLBACK_FEDFUNDS_SPREAD"
INR_SRC_OECD = "OECD_IR3TIB"
INR_SRC_FALLBACK = "FALLBACK_REPO_SPREAD"
MANUAL_RBI_SOURCE_RE = r"(?i)\b(?:RBI|FBIL|Reserve Bank|Financial Benchmarks India)\b"
# Sanity bands for 2017-12..2022-12: a value outside means a units or parsing error, not a market move.
USDINR_BAND = (60.0, 90.0)
RATE_BAND = (-0.01, 0.12)
# Treasury bill "coupon equivalent" is a 365-day bond-equivalent yield; MMY (ACT/360) = BEY × 360/365.
BEY_TO_MMY = units.DAY_COUNT_USD / units.DAY_COUNT_INR


# --------------------------------------------------------------------------------------------------- ECB spot
def ecb_cache_path(ccy: str):
    return RAW_DIR / f"ecb_exr_eur{ccy.lower()}_{START.isoformat()}_{END.isoformat()}.csv"


def fetch_ecb(ccy: str, refresh: bool = False) -> pd.Series:
    """Daily ECB reference rate `ccy` per 1 EUR, indexed by date."""
    url = ECB_URL.format(ccy=ccy, start=START.isoformat(), end=END.isoformat())
    body = fetch_cached(url, ecb_cache_path(ccy), refresh=refresh, min_bytes=10_000)
    df = pd.read_csv(io.BytesIO(body), usecols=["TIME_PERIOD", "OBS_VALUE"])
    df = df.dropna(subset=["OBS_VALUE"])
    s = pd.Series(df["OBS_VALUE"].astype(float).values, index=pd.to_datetime(df["TIME_PERIOD"]), name=ccy)
    s = s.sort_index()
    if not s.index.is_unique:
        raise ValueError(f"ECB {ccy}: duplicate dates")
    return s


def load_manual_rbi(path=None) -> pd.Series | None:
    """Optional RBI reference-rate override.

    Expected format (UTF-8 CSV, header row required):
        date,usdinr,source
        <YYYY-MM-DD>,<INR per USD>,"<RBI / FBIL press release title or URL>"      (placeholders, not data)
    `date` = ISO YYYY-MM-DD (the RBI publication date), `usdinr` = INR per 1 USD (RBI/FBIL reference rate). `source` is
    REQUIRED on every row and must name RBI or FBIL: a file that turns `usdinr` into a DIRECT series has to say where
    each number came from, otherwise it is rejected. Values must be unique per date and inside USDINR_BAND.
    """
    path = MANUAL_RBI_PATH if path is None else path
    if not path.exists():
        return None
    df = pd.read_csv(path)
    missing = {"date", "usdinr", "source"} - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing columns {sorted(missing)} (source naming RBI/FBIL is required)")
    src = df["source"].fillna("").astype(str)
    if not src.str.contains(MANUAL_RBI_SOURCE_RE, regex=True).all():
        bad = df.loc[~src.str.contains(MANUAL_RBI_SOURCE_RE, regex=True), "date"].tolist()[:5]
        raise ValueError(f"{path}: rows {bad} have a `source` that does not name RBI or FBIL; refusing to label DIRECT")
    s = pd.Series(df["usdinr"].astype(float).values, index=pd.to_datetime(df["date"], format="%Y-%m-%d"))
    if not s.index.is_unique:
        raise ValueError(f"{path}: duplicate dates")
    if ((s < USDINR_BAND[0]) | (s > USDINR_BAND[1])).any():
        raise ValueError(f"{path}: usdinr outside {USDINR_BAND}")
    return s.sort_index()


def build_spot(refresh: bool = False) -> pd.DataFrame:
    inr, usd = fetch_ecb("INR", refresh), fetch_ecb("USD", refresh)
    joined = pd.concat([inr, usd], axis=1, join="outer")
    if joined.isna().any().any():
        bad = joined.index[joined.isna().any(axis=1)]
        raise ValueError(f"ECB INR/USD calendars differ on {list(bad[:10])}")
    spot = pd.DataFrame({"usdinr": joined["INR"] / joined["USD"], "usdinr_src": "ECB_CROSS"})
    manual = load_manual_rbi()
    if manual is not None:
        manual = manual[(manual.index >= pd.Timestamp(START)) & (manual.index <= pd.Timestamp(END))]
        spot = spot.reindex(spot.index.union(manual.index))
        spot.loc[manual.index, "usdinr"] = manual.values
        spot.loc[manual.index, "usdinr_src"] = "MANUAL_RBI"
        print(f"[fetch_fx] MANUAL_RBI override applied on {len(manual)} dates from {MANUAL_RBI_PATH}")
    spot.index.name = "date"
    return spot


# ------------------------------------------------------------------------------------------------- USD 3M rate
def ust_cache_path(year: int):
    return RATES_RAW_DIR / f"ust_daily_bill_rates_{year}.csv"


def _ust_csv_ok(body: bytes) -> bool:
    return UST_COLUMN.encode() in body[:2_000]


def fetch_ust_13w(refresh: bool = False) -> tuple[pd.Series, list[int]]:
    """US Treasury 13-week bill coupon-equivalent yield (decimal p.a., 365-day basis), daily.

    Returns (series, years that could not be fetched). Offline, any cache miss or invalid cache raises instead.
    """
    parts, missing_years = [], []
    for year in range(START.year, END.year + 1):
        try:
            body = fetch_cached(UST_URL.format(year=year), ust_cache_path(year), refresh=refresh, min_bytes=2_000,
                                validator=_ust_csv_ok)
        except FetchError as e:
            if offline():
                raise
            print(f"[fetch_fx] WARNING Treasury {year} unavailable ({e}); that year's dates use the FALLBACK")
            missing_years.append(year)
            continue
        df = pd.read_csv(io.BytesIO(body))
        if UST_COLUMN not in df.columns:
            raise ValueError(f"Treasury {year}: column {UST_COLUMN!r} not in {list(df.columns)}")
        parts.append(pd.Series(df[UST_COLUMN].astype(float).values / 100.0,
                               index=pd.to_datetime(df["Date"], format="%m/%d/%Y")))
    s = pd.concat(parts).dropna().sort_index() if parts else pd.Series(dtype=float)
    return s[~s.index.duplicated(keep="last")], missing_years


# ------------------------------------------------------------------------------------------------- INR 3M rate
def oecd_cache_path():
    return RATES_RAW_DIR / f"oecd_finmark_ind_ir3tib_{START:%Y-%m}_{END:%Y-%m}.csv"


def fetch_oecd_india_3m(refresh: bool = False) -> pd.Series:
    """OECD MEI short-term (3-month) interest rate, India, monthly average (decimal p.a.), indexed by month Period."""
    url = OECD_URL.format(start=f"{START:%Y-%m}", end=f"{END:%Y-%m}")
    body = fetch_cached(url, oecd_cache_path(), refresh=refresh, headers=OECD_HEADERS, min_bytes=500,
                        validator=lambda b: b"OBS_VALUE" in b[:4_000])
    df = pd.read_csv(io.BytesIO(body))
    df = df[(df["REF_AREA"] == "IND") & (df["MEASURE"] == "IR3TIB") & (df["FREQ"] == "M")]
    s = pd.Series(df["OBS_VALUE"].astype(float).values / 100.0,
                  index=pd.PeriodIndex(df["TIME_PERIOD"], freq="M")).sort_index()
    if not s.index.is_unique:
        raise ValueError("OECD India IR3TIB: duplicate months")
    return s


def _policy_path(key: str, index: pd.DatetimeIndex) -> pd.Series:
    return config.get(key).series(index).astype(float)


def inr_3m_from_monthly(monthly: pd.Series, index: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series]:
    """repo(d) + [OECD(month) − calendar-month mean repo]; months without an OECD print use the fallback spread.

    Returns (daily rate, boolean mask of days that used the fallback)."""
    first, last = index.min().to_period("M"), index.max().to_period("M")
    months = pd.period_range(first, last, freq="M")
    cal_days = pd.date_range(months[0].start_time, months[-1].end_time.normalize(), freq="D")
    repo_cal = _policy_path("rbi_repo_rate_pa", cal_days)
    repo_month_mean = repo_cal.groupby(cal_days.to_period("M")).mean()
    spread = (monthly.reindex(months) - repo_month_mean.reindex(months))
    fallback_months = spread.index[spread.isna()]
    spread = spread.fillna(float(config.value("inr_term_spread_3m_pa")))
    day_month = index.to_period("M")
    daily = _policy_path("rbi_repo_rate_pa", index).values + spread.reindex(day_month).values
    used_fallback = pd.Series(day_month.isin(fallback_months), index=index)
    return pd.Series(daily, index=index), used_fallback


def build_rates(index: pd.DatetimeIndex, refresh: bool = False) -> pd.DataFrame:
    out = pd.DataFrame(index=index)
    out["rbi_repo_pa"] = _policy_path("rbi_repo_rate_pa", index)
    out["fed_funds_upper_pa"] = _policy_path("fed_funds_upper_pa", index)

    ust, missing_years = fetch_ust_13w(refresh)
    ust = ust * BEY_TO_MMY
    # Point-in-time carry of the last Treasury print, capped in BUSINESS DAYS (not rows) so a sparse index or a
    # missing year can never drag a stale print forward.
    prints = pd.DataFrame({"print_date": ust.index, "rate": ust.to_numpy()})
    m = pd.merge_asof(pd.DataFrame({"date": index}), prints, left_on="date", right_on="print_date", direction="backward")
    gap = np.full(len(m), np.iinfo(np.int64).max)
    has = m["print_date"].notna().to_numpy()
    gap[has] = np.busday_count(m.loc[has, "print_date"].to_numpy().astype("datetime64[D]"),
                               m.loc[has, "date"].to_numpy().astype("datetime64[D]"))
    carried = pd.Series(np.where(gap <= MAX_FILL_BDAYS, m["rate"].to_numpy(), np.nan), index=index)
    fallback_ok = pd.Series(index.year.isin(missing_years), index=index)
    hole = carried.isna() & ~fallback_ok
    if hole.any():
        raise ValueError(f"Treasury 13w gaps longer than {MAX_FILL_BDAYS} rows on {list(index[hole][:5])}")
    use_fb = carried.isna()
    out["usd_rate_3m_pa"] = carried.where(~use_fb, out["fed_funds_upper_pa"] + float(config.value("usd_term_spread_3m_pa")))
    out["usd_rate_3m_filled"] = (~index.isin(ust.index)) & ~use_fb.to_numpy()
    usd_src = np.where(use_fb, USD_SRC_FALLBACK, USD_SRC_UST)
    print(f"[fetch_fx] usd_rate_3m_pa = US Treasury 13w coupon-equivalent x 360/365 ({len(ust)} obs); "
          f"carried {int(out['usd_rate_3m_filled'].sum())} days; FALLBACK on {int(use_fb.sum())} days")

    try:
        monthly = fetch_oecd_india_3m(refresh)
    except FetchError as e:
        if offline():
            raise
        print(f"[fetch_fx] WARNING OECD India 3M unavailable ({e}); FALLBACK repo + inr_term_spread_3m_pa on all days")
        monthly = pd.Series(dtype=float, index=pd.PeriodIndex([], freq="M"))
    out["inr_rate_3m_pa"], fb = inr_3m_from_monthly(monthly, index)
    if fb.any():
        print(f"[fetch_fx] WARNING OECD India 3M missing for {sorted({str(p) for p in index[fb].to_period('M')})};"
              " those months use repo + inr_term_spread_3m_pa")
    inr_src = np.where(fb.to_numpy(), INR_SRC_FALLBACK, INR_SRC_OECD)
    out["rates_src"] = [f"USD:{u}|INR:{i}" for u, i in zip(usd_src, inr_src)]
    return out


# ------------------------------------------------------------------------------------------------- forwards
def tenor_days(index: pd.DatetimeIndex, months: int) -> np.ndarray:
    return ((index + pd.DateOffset(months=months)) - index).days.to_numpy()


def add_forwards(df: pd.DataFrame) -> pd.DataFrame:
    idx = pd.DatetimeIndex(df.index)
    d1, d3 = tenor_days(idx, 1), tenor_days(idx, 3)
    s, ri, ru = df["usdinr"].to_numpy(), df["inr_rate_3m_pa"].to_numpy(), df["usd_rate_3m_pa"].to_numpy()
    fwd = np.vectorize(units.fx_forward)
    df["usdinr_fwd_1m"] = fwd(s, ri, ru, d1)
    df["usdinr_fwd_3m"] = fwd(s, ri, ru, d3)
    df["fwd_premium_3m_pa"] = (df["usdinr_fwd_3m"] / df["usdinr"] - 1.0) * units.DAY_COUNT_INR / d3
    return df


# ------------------------------------------------------------------------------------------------- pipeline
def build(refresh: bool = False) -> pd.DataFrame:
    spot = build_spot(refresh)
    rates = build_rates(pd.DatetimeIndex(spot.index), refresh)
    df = add_forwards(spot.join(rates))
    df = df.reset_index()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    rounding = {"usdinr": 4, "usdinr_fwd_1m": 4, "usdinr_fwd_3m": 4, "rbi_repo_pa": 6, "fed_funds_upper_pa": 6,
                "inr_rate_3m_pa": 6, "usd_rate_3m_pa": 6, "fwd_premium_3m_pa": 6}
    df["usd_rate_3m_filled"] = df["usd_rate_3m_filled"].astype(bool)
    return df[COLUMNS].round(rounding)


def validate(df: pd.DataFrame) -> None:
    if not df["date"].is_unique or not df["date"].is_monotonic_increasing:
        raise ValueError("fx dates must be unique and sorted")
    if df[COLUMNS].isna().any().any():
        raise ValueError(f"NaNs in fx output: {df[COLUMNS].isna().sum()[lambda s: s > 0].to_dict()}")
    if not df["rates_src"].str.fullmatch(
            rf"USD:({USD_SRC_UST}|{USD_SRC_FALLBACK})\|INR:({INR_SRC_OECD}|{INR_SRC_FALLBACK})").all():
        raise ValueError("rates_src labels malformed")
    if (df["usd_rate_3m_filled"] & df["rates_src"].str.contains(USD_SRC_FALLBACK)).any():
        raise ValueError("a FALLBACK usd_rate_3m_pa row cannot also be a Treasury carry")
    lo, hi = USDINR_BAND
    if not df["usdinr"].between(lo, hi).all():
        raise ValueError("usdinr outside sanity band")
    for col in ("rbi_repo_pa", "fed_funds_upper_pa", "inr_rate_3m_pa", "usd_rate_3m_pa"):
        if not df[col].between(*RATE_BAND).all():
            raise ValueError(f"{col} outside {RATE_BAND}")
    # Covered interest parity: forward above spot exactly when INR 3M rate exceeds the (day-count adjusted) USD rate.
    higher_inr = df["inr_rate_3m_pa"] / units.DAY_COUNT_INR > df["usd_rate_3m_pa"] / units.DAY_COUNT_USD
    if not ((df["usdinr_fwd_3m"] > df["usdinr"]) == higher_inr).all():
        raise ValueError("forward/spot ordering inconsistent with rate differential")
    ret = pd.Series(np.log(df["usdinr"])).diff().abs()
    if (ret > 0.04).any():
        raise ValueError(f"Implausible USDINR daily move on {df.loc[ret > 0.04, 'date'].tolist()}")


def main() -> None:
    df = build()
    validate(df)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False, lineterminator="\n")
    src = df["usdinr_src"].value_counts().to_dict()
    rsrc = df["rates_src"].value_counts().to_dict()
    print(f"[fetch_fx] {len(df)} rows {df['date'].iloc[0]}..{df['date'].iloc[-1]} sources={src} rates={rsrc} -> {OUT_PATH}")


if __name__ == "__main__":
    main()
