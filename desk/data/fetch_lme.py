"""LME Aluminium official Cash / 3-month prices and LME warehouse stocks -> data/processed/lme_daily.csv (DIRECT).

Source: Westmetall GmbH yearly data tables, which republish the LME official settlement (cash) and 3-month prices
and daily LME aluminium stocks. lme.com itself sits behind a login for history, so Westmetall is the most
reproducible public mirror. One HTML page per calendar year is cached under data/raw/ and parsed with the standard
library only (no lxml dependency), because the table markup is simple and stable:

    <tr><td>07. March 2022</td><td>3,984.50</td><td>3,968.00</td><td class="last">712,150</td></tr>

with a repeated <th> header row at every month boundary.

Contract (CONTRACTS.md §4.1): `date, lme_cash_usd_t, lme_3m_usd_t, lme_cash_3m_spread_usd_t, lme_stock_mt`, spread =
cash − 3M (positive = backwardation, negative = contango). The file defines the panel calendar for every later phase,
so validation is deliberately strict and fails loudly rather than writing a silently wrong calendar.
"""

from __future__ import annotations

import datetime as dt
import html
import re

import pandas as pd

from desk import HISTORY_START, PANEL_END
from desk.data._http import fetch_cached
from desk.paths import PROCESSED_DIR, RAW_DIR

YEARS = (2018, 2019, 2020, 2021, 2022)
HISTORY_END = PANEL_END
URL_TEMPLATE = "https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Al_cash&year={year}"
OUT_PATH = PROCESSED_DIR / "lme_daily.csv"
COLUMNS = ["date", "lme_cash_usd_t", "lme_3m_usd_t", "lme_cash_3m_spread_usd_t", "lme_stock_mt"]

# Hard anchors: the LME aluminium all-time high official prices (7 Mar 2022), cross-checked against the cached page.
ANCHORS = {dt.date(2022, 3, 7): {"lme_cash_usd_t": 3984.5, "lme_3m_usd_t": 3968.0}}
# LME trades ~252 days a year; a count outside this band means a truncated page or a parser regression.
MIN_ROWS_PER_YEAR = 245
MAX_ROWS_PER_YEAR = 256

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def raw_path(year: int):
    return RAW_DIR / f"westmetall_lme_al_{year}.html"


def fetch_year(year: int, refresh: bool = False) -> str:
    """Raw HTML for one year (cache first; DESK_OFFLINE=1 never touches the network)."""
    body = fetch_cached(URL_TEMPLATE.format(year=year), raw_path(year), refresh=refresh, min_bytes=5_000)
    return body.decode("utf-8", errors="replace")


def _cell_text(cell: str) -> str:
    return html.unescape(_TAG_RE.sub("", cell)).replace("\xa0", " ").strip()


def _to_number(text: str) -> float:
    """'3,984.50' -> 3984.5; blank / '-' / non-numeric -> NaN (Westmetall leaves stocks blank on some days)."""
    cleaned = text.replace(",", "").strip()
    if cleaned in ("", "-", "–", "n/a"):
        return float("nan")
    try:
        return float(cleaned)
    except ValueError:
        return float("nan")


def parse_westmetall_html(page: str) -> pd.DataFrame:
    """Parse one Westmetall yearly table. Header rows (<th>) are skipped because they carry no <td> cells."""
    rows = []
    for row_html in _ROW_RE.findall(page):
        cells = [_cell_text(c) for c in _TD_RE.findall(row_html)]
        if len(cells) < 4:
            continue
        try:
            date = dt.datetime.strptime(cells[0], "%d. %B %Y").date()
        except ValueError:
            continue
        rows.append(
            {
                "date": date,
                "lme_cash_usd_t": _to_number(cells[1]),
                "lme_3m_usd_t": _to_number(cells[2]),
                "lme_stock_mt": _to_number(cells[3]),
            }
        )
    return pd.DataFrame(rows, columns=["date", "lme_cash_usd_t", "lme_3m_usd_t", "lme_stock_mt"])


def _check_year(df: pd.DataFrame, year: int) -> None:
    """Guard against Westmetall silently serving a different year (e.g. the current one) for a bad `year=`."""
    if df.empty:
        raise ValueError(f"Westmetall {year}: parsed zero rows")
    years = {d.year for d in df["date"]}
    if years != {year}:
        raise ValueError(f"Westmetall page for {year} contains dates from years {sorted(years)}")


def build(refresh: bool = False) -> pd.DataFrame:
    frames = []
    for year in YEARS:
        df = parse_westmetall_html(fetch_year(year, refresh=refresh))
        _check_year(df, year)
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    # Rows without both official prices are not usable trading days for any valuation; report and drop them.
    missing_px = out["lme_cash_usd_t"].isna() | out["lme_3m_usd_t"].isna()
    if missing_px.any():
        print(f"[fetch_lme] dropping {int(missing_px.sum())} rows lacking a cash or 3M price: "
              f"{[str(d) for d in out.loc[missing_px, 'date']]}")
        out = out.loc[~missing_px]
    out = out[(out["date"] >= HISTORY_START) & (out["date"] <= HISTORY_END)]
    out = out.sort_values("date").reset_index(drop=True)
    out["lme_cash_3m_spread_usd_t"] = (out["lme_cash_usd_t"] - out["lme_3m_usd_t"]).round(2)
    out["lme_stock_mt"] = out["lme_stock_mt"].astype("Int64")
    return out[COLUMNS]


def validate(df: pd.DataFrame) -> dict[int, int]:
    """Hard checks on the calendar-defining series. Returns per-year row counts for logging."""
    if not df["date"].is_unique:
        dups = df.loc[df["date"].duplicated(), "date"].tolist()
        raise ValueError(f"Duplicate LME dates: {dups[:10]}")
    if not df["date"].is_monotonic_increasing:
        raise ValueError("LME dates are not sorted")
    if (df[["lme_cash_usd_t", "lme_3m_usd_t"]] <= 0).any().any():
        raise ValueError("Non-positive LME price found")
    if df["date"].iloc[0] != HISTORY_START or df["date"].iloc[-1] != HISTORY_END:
        raise ValueError(f"LME range {df['date'].iloc[0]}..{df['date'].iloc[-1]} != {HISTORY_START}..{HISTORY_END}")
    by_date = df.set_index("date")
    for day, expected in ANCHORS.items():
        if day not in by_date.index:
            raise ValueError(f"Anchor date {day} missing")
        for col, val in expected.items():
            got = float(by_date.at[day, col])
            if abs(got - val) > 1e-9:
                raise ValueError(f"Anchor {day} {col}: expected {val}, got {got}")
    counts = df.groupby(df["date"].map(lambda d: d.year)).size().to_dict()
    for year, n in counts.items():
        if not MIN_ROWS_PER_YEAR <= n <= MAX_ROWS_PER_YEAR:
            raise ValueError(f"LME {year}: {n} rows outside [{MIN_ROWS_PER_YEAR}, {MAX_ROWS_PER_YEAR}]")
    # A day-on-day cash move beyond ±15 % would be a parsing error, not a market move (max 2018–22 was ~±7 %).
    ret = df["lme_cash_usd_t"].pct_change().abs()
    if (ret > 0.15).any():
        raise ValueError(f"Implausible LME daily move on {df.loc[ret > 0.15, 'date'].tolist()}")
    return {int(k): int(v) for k, v in counts.items()}


def write(df: pd.DataFrame) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out.to_csv(OUT_PATH, index=False, lineterminator="\n")


def main() -> None:
    df = build()
    counts = validate(df)
    write(df)
    stock_gaps = int(df["lme_stock_mt"].isna().sum())
    print(f"[fetch_lme] {len(df)} rows {df['date'].iloc[0]}..{df['date'].iloc[-1]} -> {OUT_PATH}")
    print(f"[fetch_lme] rows per year: {counts}; blank stock cells: {stock_gaps}")


if __name__ == "__main__":
    main()
