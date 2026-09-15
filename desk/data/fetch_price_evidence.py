"""Price evidence behind the grade factors (scrap_grades.yaml) and the domestic anchor premium (commercial.yaml).

Part A — grade factors: DGCIS import unit values, LME 3M and dated BigMint India CFR grade quotes.
Part B — domestic anchor: dated BigMint ADC12 (secondary alloy ingot) prices against duty-paid LME CASH parity, the
same basis the panel's MCX proxy uses (CONTRACTS §4.5), with ECB USD/INR on the day before publication.

Why this module exists (Phase 0 review, findings on grade factors): the grade factor is the largest single input to the
landed cost, so every number in it must be reproducible from cached public sources, and the grade differential must be
measured on the SAME base it is later added to.

Construction (all on a CFR/CIF India basis, so freight cancels and both lanes share one price — CONTRACTS §5):

1. MIX RATIO (PROXY). DGCIS TRADESTAT "Import :: Commodity wise all countries", HS 76020010 (ISRI-coded aluminium scrap,
   unit kg), monthly US$ value and quantity, calendar-year pages (each page also carries the previous year's same
   month). Unit value UV(month) = US$ / kg × 1000 is a CIF (customs assessable value) $/t for ALL grades and origins.
       R_lag(m) = UV(m + lag) / mean LME 3M official over contract month m
   with lag = `grade_factor_lag_months` (2). Customs values are booked at the Bill of Entry, ~2 months after the price
   was fixed. Lag 1 and lag 3 are written alongside for sensitivity.
2. GRADE DIFFERENTIALS (evidence PROXY, applied to 2022 as ASSUMPTION). Dated BigMint India CFR/CIF grade prices
   republished by AlCircle (2024–2025; no public 2022 grade quotes exist). For each quote on date d in month m:
       quote_ratio = price / LME 3M official on the last LME trading day BEFORE d (D−1: the price a desk could see
                     when the weekly assessment was compiled; the article's own LME figure is not used)
       clean_ratio = quote_ratio / (1 − stated attachments)   (desk buys ISRI-clean Tense / Taint-Tabor; a buyer pays
                     for aluminium content, so a 6–7% attachment lot is priced ~6.5% below a clean one)
       diff        = clean_ratio − R_lag(m)
   and the grade differential is the median diff over the grade's usable quotes. The DESK Zorba grade is Zorba 95/5
   (the grade the only public Zorba quotes cover; ~95% aluminium, ~5% heavy non-ferrous) — see scrap_grades.yaml.
3. POINT-IN-TIME CAVEAT. UV(m+2) is published months after contract month m, so the 2022 factor path is a hindsight
   reconstruction. `mix_ratio_pit` = UV(m−1) / LME 3M(m−3) is what a desk could have computed in month m assuming a
   ~1-month DGCIS release lag (release lag assumed, not verified) and is written for sensitivity.

Every quote's exact sentence is asserted to appear in the cached article text, so a figure cannot drift from its
source. Outputs go to data/interim/price_evidence/ (derived tables, CONTRACTS §2).

Part B construction: premium = ADC12 (ex-Delhi, excl. GST) − LME cash(D−1) × ECB USD/INR(D−1) × (1 + BCD 7.5% ×
(1 + SWS 10%)). Non-OEM / spot quotes are used as published; OEM-approved quotes are brought to a non-OEM basis by
subtracting the OEM − non-OEM gap observed in the same two December-2024 BigMint articles. The table also reports the
short-run pass-through (OLS slope of ADC12 on parity) and the premium against a trailing-parity reference, because
the evidence shows domestic alloy prices are sticky against LME (see commercial.yaml).

What this does and doesn't tell you: it measures, with public data, how imported scrap prices sat against LME, how
the three grades sat against the all-grade import mix, and where domestic alloy ingot sat against import parity, in
2023–25. It does not observe any 2022 grade or alloy price: applying 2023–25 spreads to 2022 is a judgement, and the
monthly mix and the alloy discount both move with the price regime.
"""

from __future__ import annotations

import datetime as dt
import io
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
import requests

from desk import config
from desk.data import fetch_lme
from desk.data._http import (
    BROWSER_UA,
    PermanentFetchError,
    TransientFetchError,
    cached_download,
    fetch_cached,
    http_get,
)
from desk.data.fetch_freight import html_to_text
from desk.paths import INTERIM_DIR, PROCESSED_DIR, RAW_DIR

HS_CODE = "76020010"
TRADESTAT_URL = "https://tradestat.commerce.gov.in/meidb/commodity_wise_all_countries_import"
TRADESTAT_DIR = RAW_DIR / "regulatory" / "tradestat"
ALCIRCLE_DIR = RAW_DIR / "regulatory" / "alcircle"
OUT_DIR = INTERIM_DIR / "price_evidence"
UV_PAGE_YEARS = {2022: range(1, 13), 2024: range(1, 13), 2025: range(1, 13)}  # 2021/2023 come from prior-year columns
LME_EXTRA_YEARS = (2023, 2024, 2025)
GRADES = ("zorba", "taint_tabor", "tense")
CONTRACT_MONTHS_2022 = pd.period_range("2021-12", "2022-09", freq="M")  # breakpoints of the YAML paths (mid-month)
RV_VALUE, RV_QTY = 1, 2  # TRADESTAT cwacimReportVal: 1 = US$ million, 2 = quantity (kg for HS 76020010)
_TOTAL = re.compile(r"Total \|[ |]*([\d,.]+) \|[ |]*([\d,.]+)")
_ARTICLE_DATE = re.compile(r"(\d{1,2} (?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|"
                           r"DECEMBER) 20\d\d)")


# --------------------------------------------------------------------------------------------- sources
@dataclass(frozen=True)
class Article:
    url: str
    date: str  # publication date printed on the page (asserted)


ARTICLES: dict[str, Article] = {
    "ac_2024-02-14": Article("https://www.alcircle.com/news/imported-aluminium-scrap-prices-in-india-trend-higher-on-increased-demand-and-futures-106903", "2024-02-14"),
    "ac_2024-02-24": Article("https://www.alcircle.com/news/raw-material-costs-propel-india-s-aluminium-adc12-prices-upward-w-o-w-108017", "2024-02-24"),
    "ac_2024-03-13": Article("https://www.alcircle.com/news/india-s-imported-aluminium-scrap-prices-continue-to-rise-109184", "2024-03-13"),
    "ac_2024-03-20": Article("https://www.alcircle.com/news/india-s-imported-aluminium-scrap-prices-maintain-resilience-despite-a-slight-dip-in-lme-prices-110258", "2024-03-20"),
    "ac_2024-07-11": Article("https://www.alcircle.com/news/indias-imported-aluminium-scrap-prices-grow-w-o-w-buoyed-by-increased-buying-activity-in-europe-111398", "2024-07-11"),
    "ac_2024-07-26": Article("https://www.alcircle.com/press-release/h1-2024-india-witnesses-8-decline-in-aluminium-scrap-imports-amid-rising-geopolitical-crisis-111546", "2024-07-26"),
    "ac_2024-07-31": Article("https://www.alcircle.com/news/indias-imported-aluminium-scrap-price-declines-by-4-w-o-w-on-lme-downtrend-111580", "2024-07-31"),
    "ac_2024-08-08": Article("https://www.alcircle.com/news/indias-imported-aluminium-scrap-prices-fall-by-upto-1-6-amidst-stable-lme-prices-111656", "2024-08-08"),
    "ac_2024-11-28": Article("https://www.alcircle.com/press-release/india-imported-aluminium-scrap-prices-remain-largely-stable-w-o-w-amid-declining-lme-levels-112671", "2024-11-28"),
    "ac_2024-12-04": Article("https://www.alcircle.com/news/press-release/india-imported-aluminium-scrap-prices-remain-range-bound-w-o-w-amid-slow-trading-112720", "2024-12-04"),
    "ac_2024-12-05": Article("http://www.alcircle.com/news/press-release/india-adc12-aluminium-alloyed-ingot-prices-remain-rangebound-112726", "2024-12-05"),
    "ac_2024-12-11": Article("https://www.alcircle.com/press-release/india-imported-aluminium-scrap-prices-remain-range-bound-w-o-w-amid-year-end-uncertainty-112773", "2024-12-11"),
    "ac_2024-12-18": Article("https://www.alcircle.com/press-release/india-imported-aluminium-scrap-prices-remain-range-bound-w-o-w-certain-grades-see-tight-supply-112828", "2024-12-18"),
    "ac_2025-01-18": Article("https://www.alcircle.com/press-release/india-imported-aluminium-scrap-prices-rise-w-o-w-even-as-some-grades-witness-tight-supply-113071", "2025-01-18"),
    "ac_2025-02-06": Article("https://www.alcircle.com/press-release/india-imported-aluminium-scrap-prices-rise-w-o-w-following-hike-in-lme-tags-113228", "2025-02-06"),
    "ac_2025-03-19": Article("https://www.alcircle.com/press-release/india-imported-aluminium-scrap-prices-see-divergent-trends-w-o-w-supply-shortage-persists-113566", "2025-03-19"),
    "ac_2025-03-26": Article("https://www.alcircle.com/press-release/india-imported-aluminium-scrap-prices-decline-w-o-w-tracking-lme-movements-113639", "2025-03-26"),
    "ac_2025-08-20": Article("https://www.alcircle.com/press-release/india-imported-aluminium-scrap-prices-soften-w-o-w-amid-weak-lme-festive-lull-115159", "2025-08-20"),
    "ac_2025-08-27": Article("https://www.alcircle.com/press-release/india-imported-aluminium-scrap-prices-decline-w-o-w-despite-gains-in-lme-tags-115243", "2025-08-27"),
    "ac_2025-10-31": Article("https://www.alcircle.com/press-release/india-imported-aluminium-scrap-prices-inch-up-w-o-w-market-expected-to-improve-in-early-nov-25-116029", "2025-10-31"),
    "ac_2025-12-04": Article("https://www.alcircle.com/press-release/india-imported-domestic-aluminium-scrap-prices-witness-weekly-gains-tracking-lme-uptrend-116440", "2025-12-04"),
    "ac_2025-12-10": Article("https://www.alcircle.com/press-release/india-imported-and-domestic-aluminium-scrap-prices-rise-w-o-w-amid-tightening-lme-supply-116525", "2025-12-10"),
    "ac_2025-12-18": Article("https://www.alcircle.com/press-release/india-aluminium-scrap-prices-remain-rangebound-as-year-end-seasonality-slows-buying-116627", "2025-12-18"),
}

# BigMint labels its UAE Tense benchmark "UAE tense (8-9 per cent)" (ac_2024-07-26 H1 review; ac_2025-12-10/18) and its
# US Tense benchmark "US-origin Tense (6-7 per cent)" (ac_2024-02-24, ac_2024-07-11, ac_2025-12-10/18). Weeks whose
# article omits the percentage are the same benchmark series, so the series label is applied (attach_source=SERIES).
UAE_TENSE_ATTACH, US_TENSE_ATTACH, US_TT_HRB_ATTACH = 0.085, 0.065, 0.025


@dataclass(frozen=True)
class Quote:
    article: str
    grade: str
    origin: str
    kind: str  # ASSESSMENT (BigMint benchmark) | DEAL (reported single trade)
    price_usd_t: float
    attach_frac: float
    attach_source: str  # STATED | SERIES (benchmark's label from another week) | NONE (clean / not applicable)
    basis: str
    snippet: str  # exact text asserted to appear in the cached article
    use: bool = True
    exclude_reason: str = ""


Z, TT, T = "zorba", "taint_tabor", "tense"
QUOTES: list[Quote] = [
    # --- 2024 -------------------------------------------------------------------------------------------------------
    Quote("ac_2024-02-14", T, "UAE", "ASSESSMENT", 1720, UAE_TENSE_ATTACH, "SERIES", "CFR India",
          "Tense scrap of Middle East (UAE) origin has experienced a $20/t increase, reaching $1,720/t"),
    Quote("ac_2024-02-24", T, "UAE", "ASSESSMENT", 1695, UAE_TENSE_ATTACH, "SERIES", "CFR India",
          "saw a decrease of $25 per ton, settling at $1,695 per ton"),
    Quote("ac_2024-02-24", T, "USA", "ASSESSMENT", 1775, US_TENSE_ATTACH, "STATED", "CFR India",
          "Tense scrap (6-7%) from the US was reportedly priced at $1,775 per ton"),
    Quote("ac_2024-02-24", Z, "UK", "ASSESSMENT", 2010, 0.0, "NONE", "CFR Nhava Sheva",
          "UK-origin Zorba 95-5 rose to $2,010 per ton CFR Nhava Sheva"),
    Quote("ac_2024-03-13", T, "UAE", "ASSESSMENT", 1825, UAE_TENSE_ATTACH, "SERIES", "CFR Mundra",
          "Tense scrap originating from the UAE witnessed a $35 per metric ton increase, reaching $1,825 per metric ton"),
    Quote("ac_2024-03-13", Z, "UK", "ASSESSMENT", 2040, 0.0, "NONE", "CFR Mundra",
          "zorba 95/5 of UK origin rose by $10 per tonne to $2,040 per tonne CFR (Cost and Freight) Mundra"),
    Quote("ac_2024-03-13", Z, "USA", "DEAL", 2050, 0.0, "NONE", "CIF west coast India",
          "Recent deals for CIF WC India USA-origin Zorba 95/5 was traded at $2,050/t"),
    Quote("ac_2024-03-13", TT, "UAE", "DEAL", 1980, 0.0, "NONE", "CIF west coast India",
          "UAE-origin taint tabor was traded at $1,980/t"),
    Quote("ac_2024-03-13", TT, "USA", "DEAL", 1820, US_TT_HRB_ATTACH, "STATED", "CIF west coast India",
          "USA-origin Taint Tabor (2-3 per cent) was traded at $1,820/t"),
    Quote("ac_2024-03-13", T, "USA", "DEAL", 1870, 0.06, "STATED", "CIF west coast India",
          "USA tense (5-7 per cent) was traded at $1,870/t"),
    Quote("ac_2024-03-13", T, "Europe", "DEAL", 1980, 0.02, "STATED", "CIF west coast India",
          "Europe origin tense (2 per cent) was traded at $1,980/t"),
    Quote("ac_2024-03-20", T, "UAE", "ASSESSMENT", 1835, UAE_TENSE_ATTACH, "SERIES", "CFR Mundra",
          "Tense scrap from the UAE saw a rise of $10 per tonne, reaching $1,835 per tonne"),
    Quote("ac_2024-03-20", Z, "UK", "ASSESSMENT", 2040, 0.0, "NONE", "CFR Mundra",
          "Zorba 95/5 from the UK remained steady at $2,040 per tonne CFR Mundra"),
    Quote("ac_2024-07-11", T, "UAE", "ASSESSMENT", 1830, UAE_TENSE_ATTACH, "SERIES", "CFR India",
          "tension scrap originating from the Middle East, notably the UAE, saw a price hike of $50 per tonne, "
          "settling at $1,830 per tonne"),
    Quote("ac_2024-07-11", Z, "UK", "ASSESSMENT", 2060, 0.0, "NONE", "CFR west coast India",
          "Zorba 95/5 sourced from the UK rose by $5 per tonne to settle at $2,060 per tonne CFR for the west coast"),
    Quote("ac_2024-07-11", TT, "USA", "ASSESSMENT", 2000, US_TT_HRB_ATTACH, "STATED", "CFR Mundra",
          "the price for US taint tabor HRB (2-3 per cent) is $2,000 per tonne CFR Mundra"),
    Quote("ac_2024-07-11", T, "USA", "ASSESSMENT", 1850, US_TENSE_ATTACH, "STATED", "CFR Mundra",
          "The price for US tense (6-7 per cent) was recorded at $1,850 per tonne CFR Mundra"),
    Quote("ac_2024-07-31", T, "UAE", "ASSESSMENT", 1730, UAE_TENSE_ATTACH, "SERIES", "CFR west coast India",
          "decreased by $60 per tonne, settling at $1,730 per tonne"),
    Quote("ac_2024-07-31", Z, "UK", "ASSESSMENT", 1975, 0.0, "NONE", "CFR west coast India",
          "Zorba 95/5 from the UK also decreased by $25/t to $1,975 per tonne CFR West Coast, India"),
    Quote("ac_2024-08-08", T, "UAE", "ASSESSMENT", 1700, UAE_TENSE_ATTACH, "SERIES", "CFR west coast India",
          "Tense scrap from the UAE has decreased by $30 per tonne to settle at $1,700 per tonne"),
    Quote("ac_2024-08-08", Z, "UK", "ASSESSMENT", 1960, 0.0, "NONE", "CFR west coast India",
          "bringing the price to $1,960 per tonne CFR West Coast, India"),
    Quote("ac_2024-11-28", T, "UAE", "ASSESSMENT", 1800, UAE_TENSE_ATTACH, "SERIES", "CFR west coast India",
          "tense scrap originating from the UAE stood at $1,800/tonne (t), firm w-o-w, while zorba 95/5 from the UK "
          "stood at $2,110/t"),
    Quote("ac_2024-11-28", Z, "UK", "ASSESSMENT", 2110, 0.0, "NONE", "CFR west coast India",
          "zorba 95/5 from the UK stood at $2,110/t, stable w-o-w, both prices CFR west coast, India"),
    Quote("ac_2024-12-04", T, "UAE", "ASSESSMENT", 1800, UAE_TENSE_ATTACH, "SERIES", "CFR west coast India",
          "Tense scrap originating from the UAE stood at $1,800/tonne (t), firm w-o-w, while Zorba 95/5 from the UK "
          "stood at $2,100/t, largely stable"),
    Quote("ac_2024-12-04", Z, "UK", "ASSESSMENT", 2100, 0.0, "NONE", "CFR west coast India",
          "Zorba 95/5 from the UK stood at $2,100/t, largely stable w-o-w, both prices CFR west coast, India"),
    Quote("ac_2024-12-11", T, "UAE", "ASSESSMENT", 1800, UAE_TENSE_ATTACH, "SERIES", "CFR west coast India",
          "Tense scrap originating from the UAE stood at $1,800/tonne (t), firm w-o-w, while Zorba 95/5 from the UK "
          "was at $2,110/t, largely stable w-o-w, both CFR west coast"),
    Quote("ac_2024-12-11", Z, "UK", "ASSESSMENT", 2110, 0.0, "NONE", "CFR west coast India",
          "Zorba 95/5 from the UK was at $2,110/t, largely stable w-o-w, both CFR west coast, India"),
    Quote("ac_2024-12-11", TT, "UAE", "DEAL", 2170, 0.0, "NONE", "CFR India",
          "UAE-origin Taint Tabor also increased, with recent transactions recorded at $2,160-2,180/tonne"),
    Quote("ac_2024-12-18", T, "UAE", "ASSESSMENT", 1800, UAE_TENSE_ATTACH, "SERIES", "CFR west coast India",
          "Tense scrap originating from the UAE stood at $1,800/tonne (t), firm w-o-w, while Zorba 95/5 from the UK "
          "was at $2,110/tonne, stable w-o-w"),
    Quote("ac_2024-12-18", Z, "UK", "ASSESSMENT", 2110, 0.0, "NONE", "CFR west coast India",
          "Zorba 95/5 from the UK was at $2,110/tonne, stable w-o-w, both CFR west coast, India"),
    # --- 2025 -------------------------------------------------------------------------------------------------------
    Quote("ac_2025-01-18", T, "USA", "ASSESSMENT", 1830, US_TENSE_ATTACH, "SERIES", "CFR west coast India",
          "Tense scrap originating from the US stood at $1,830/tonne (t)"),
    Quote("ac_2025-02-06", T, "USA", "ASSESSMENT", 1850, US_TENSE_ATTACH, "SERIES", "CFR west coast India",
          "Tense scrap originating from the US was at $1,850/tonne (t)"),
    Quote("ac_2025-02-06", T, "UK", "DEAL", 1860, 0.06, "STATED", "CIF west coast India",
          "UK tense 6 per cent at $1,860/t CIF West coast"),
    Quote("ac_2025-03-19", T, "USA", "ASSESSMENT", 1960, US_TENSE_ATTACH, "SERIES", "CFR west coast India",
          "Tense scrap originating in the US was at $1,960/tonne"),
    Quote("ac_2025-03-26", T, "USA", "ASSESSMENT", 1945, US_TENSE_ATTACH, "SERIES", "CFR west coast India",
          "Tense scrap originating in the US was at USD 1,945/tonne (t)"),
    Quote("ac_2025-08-20", T, "USA", "ASSESSMENT", 2000, US_TENSE_ATTACH, "SERIES", "CFR India",
          "BigMint assessed Tense scrap from the US at USD 2,000 per tonne, down by USD 40 per tonne"),
    Quote("ac_2025-08-20", TT, "USA", "ASSESSMENT", 2175, US_TT_HRB_ATTACH, "STATED", "CFR India",
          "US taint tabor HRB (2-3 per cent) saw a drop of USD 10 per tonne, settling at USD 2,175 per tonne"),
    Quote("ac_2025-08-27", T, "USA", "ASSESSMENT", 1960, US_TENSE_ATTACH, "SERIES", "CFR India",
          "BigMint assessed Tense scrap from the US at USD 1,960 per tonne"),
    Quote("ac_2025-08-27", TT, "USA", "ASSESSMENT", 2145, US_TT_HRB_ATTACH, "STATED", "CFR India",
          "US taint tabor HRB (2-3 per cent) saw a drop of USD 30 per tonne, settling at USD 2,145 per tonne"),
    Quote("ac_2025-10-31", T, "UAE", "ASSESSMENT", 1945, UAE_TENSE_ATTACH, "SERIES", "CFR India",
          "BigMint assessed UAE-origin Tense scrap at USD 1,945 per tonne"),
    Quote("ac_2025-10-31", TT, "UK", "ASSESSMENT", 2250, 0.095, "STATED", "CFR India",
          "UK-origin Taint Tabor C/S (9-10 per cent) stood at USD 2,250 per tonne", use=False,
          exclude_reason="'C/S (9-10 per cent)' sub-grade is not defined in the article; the same series prints "
                         "$2,010 'firm w-o-w' five weeks later, so the level is not reliable"),
    Quote("ac_2025-10-31", Z, "UK", "ASSESSMENT", 2180, 0.0, "NONE", "CFR India",
          "UK-origin Zorba 95/5 remained stable at USD 2,180 per tonne"),
    Quote("ac_2025-12-04", T, "UAE", "ASSESSMENT", 1925, UAE_TENSE_ATTACH, "SERIES", "CFR India",
          "BigMint assessed UAE-origin Tense scrap at USD1,925 per tonne"),
    Quote("ac_2025-12-04", TT, "UK", "ASSESSMENT", 2010, 0.095, "STATED", "CFR India",
          "UK-origin Taint Tabor C/S (9-10 per cent) stood at USD2,010 per tonne", use=False,
          exclude_reason="undefined 'C/S (9-10 per cent)' sub-grade; inconsistent with the $2,250 print of 31-Oct-2025"),
    Quote("ac_2025-12-04", Z, "UK", "ASSESSMENT", 2260, 0.0, "NONE", "CFR India",
          "UK-origin Zorba 95 per 5 stood at USD2,260 per tonne"),
    Quote("ac_2025-12-10", T, "UAE", "ASSESSMENT", 1930, UAE_TENSE_ATTACH, "STATED", "CFR India",
          "BigMint assessed UAE-origin Tense (8-9 per cent) at USD 1,930 per tonne"),
    Quote("ac_2025-12-10", T, "USA", "ASSESSMENT", 2000, US_TENSE_ATTACH, "STATED", "CFR India",
          "US-origin Tense (6-7 per cent) remained unchanged at USD 2,000 per tonne"),
    Quote("ac_2025-12-10", Z, "UK", "ASSESSMENT", 2275, 0.0, "NONE", "CFR India",
          "UK-origin Zorba 95 per 5 was assessed at USD 2,275 per tonne"),
    Quote("ac_2025-12-10", TT, "USA", "ASSESSMENT", 2215, 0.03, "STATED", "CFR India",
          "US-origin Taint Tabor HRB (3 per cent) increased by USD 5 per tonne to USD 2,215 per tonne"),
    Quote("ac_2025-12-18", T, "Middle East", "ASSESSMENT", 1930, UAE_TENSE_ATTACH, "STATED", "CFR India",
          "BigMint assessed Middle East-origin Tense (8-9 per cent) at USD 1,930 per tonne"),
    Quote("ac_2025-12-18", T, "USA", "ASSESSMENT", 2000, US_TENSE_ATTACH, "STATED", "CFR India",
          "US-origin Tense (6-7 per cent) also remained stable at USD 2,000 per tonne"),
    Quote("ac_2025-12-18", Z, "UK", "ASSESSMENT", 2285, 0.0, "NONE", "CFR India",
          "UK-origin Zorba 95/5 edged up by USD 10 per tonne to USD 2,285 per tonne"),
    Quote("ac_2025-12-18", TT, "USA", "ASSESSMENT", 2205, 0.03, "STATED", "CFR India",
          "US-origin Taint Tabor HRB (3 per cent) slipped USD 10 per tonne to USD 2,205 per tonne"),
]
# Label evidence for the SERIES attachment convention (asserted to exist in the cached text as well).
LABEL_SNIPPETS = [
    ("ac_2024-07-26", "UAE tense (8-9 per cent)"),
    ("ac_2025-12-10", "UAE-origin Tense (8-9 per cent)"),
    ("ac_2025-12-10", "US-origin Tense (6-7 per cent)"),
]


# --------------------------------------------------------------------------------------------- Part B sources
ARTICLES.update({
    "ac_2023-04-15": Article("https://www.alcircle.com/news/indias-aluminium-alloy-ingot-adc12-price-remains-stable-w-o-w-93593", "2023-04-15"),
    "ac_2023-12-01": Article("https://www.alcircle.com/news/aluminium-alloy-adc12-ingot-prices-in-india-register-a-sequential-influx-of-inr1000-t-103142", "2023-12-01"),
    "ac_2024-02-29": Article("https://www.alcircle.com/news/indias-aluminium-adc12-price-remains-steady-w-o-w-amidst-increased-raw-material-prices-109058", "2024-02-29"),
    "ac_2024-03-14": Article("https://www.alcircle.com/news/local-tense-scrap-shortages-propel-aluminium-adc12-prices-upward-in-india-110195", "2024-03-14"),
    "ac_2024-03-28": Article("https://www.alcircle.com/news/indias-adc12-aluminium-ingot-prices-move-upward-despite-stable-raw-material-cost-110339", "2024-03-28"),
    "ac_2024-05-09": Article("https://www.alcircle.com/news/indias-aluminium-alloy-adc12-prices-records-w-o-w-decline-of-inr3000-t-110812", "2024-05-09"),
    "ac_2024-05-30": Article("https://www.alcircle.com/news/spot-prices-for-adc12-aluminium-alloy-ingots-close-at-inr216000-t-w-o-w-111037", "2024-05-30"),
    "ac_2024-06-13": Article("https://www.alcircle.com/news/indias-adc12-aluminium-ingot-price-in-delhi-drops-marginally-to-inr215000-t-w-o-w-111163", "2024-06-13"),
    "ac_2024-07-12": Article("https://www.alcircle.com/news/indias-adc12-aluminium-ingot-prices-remain-stable-w-o-w-amid-high-freights-111413", "2024-07-12"),
    "ac_2024-08-01": Article("https://www.alcircle.com/news/indias-adc12-aluminium-ingot-price-declines-w-o-w-owing-to-weakening-raw-material-prices-111591", "2024-08-01"),
    "ac_2024-08-10": Article("https://www.alcircle.com/news/indiaadc12-aluminium-ingot-price-declines-m-o-m-amid-weakening-scrap-market-111670", "2024-08-10"),
    "ac_2024-11-21": Article("https://www.alcircle.com/press-release/india-aluminium-adc12-alloy-ingot-prices-inch-up-w-o-w-on-rising-raw-material-costs-112621", "2024-11-21"),
    "ac_2024-12-11b": Article("https://www.alcircle.com/press-release/india-adc12-aluminium-alloyed-ingot-oem-grade-prices-drop-to-10-month-low-in-south-india-112774", "2024-12-11"),
    "ac_2025-02-07": Article("https://www.alcircle.com/press-release/what-happened-in-india-s-secondary-aluminium-industry-in-jan-25-bigmint-analysis-113241", "2025-02-07"),
    "ac_2025-03-12": Article("https://www.alcircle.com/press-release/india-adc12-aluminium-oem-grade-alloy-ingot-prices-rise-m-o-m-in-mar-25-amid-higher-scrap-tags-113509", "2025-03-12"),
    "ac_2025-12-11": Article("https://www.alcircle.com/press-release/india-adc12-prices-stable-for-dec-25-amid-year-end-slowdown-despite-steady-auto-demand-116544", "2025-12-11"),
})
ECB_EVIDENCE_URL = ("https://data-api.ecb.europa.eu/service/data/EXR/D.{ccy}.EUR.SP00.A"
                    "?startPeriod=2023-01-01&endPeriod=2025-12-31&format=csvdata")
ECB_EVIDENCE_DIR = RAW_DIR / "regulatory" / "ecb"
TRAILING_PARITY_BDAYS = 120  # sticky-anchor sensitivity reference (≈ 6 months of LME days)


@dataclass(frozen=True)
class AlloyQuote:
    article: str
    series: str  # SPOT (automobile-equivalent spot, ex-Delhi) | NON_OEM | OEM (OEM-approved)
    price_inr_t: float
    snippet: str
    use: bool = True
    exclude_reason: str = ""


ALLOY_QUOTES: list[AlloyQuote] = [
    AlloyQuote("ac_2023-04-15", "SPOT", 197000, "remained stable w-o-w at INR 197,000/t", use=False,
               exclude_reason="region and grade basis (spot / OEM, Delhi / Chennai) not stated"),
    AlloyQuote("ac_2023-12-01", "SPOT", 183000, "in the prices of aluminium ADC12 alloy ingots to INR 183,000 per tonne"),
    AlloyQuote("ac_2024-02-24", "SPOT", 204000, "rose by INR 2,000 per tonne W-o-W, reaching INR 204,000 per tonne"),
    AlloyQuote("ac_2024-02-29", "SPOT", 204000, "in Delhi remain steady at INR 204,000 per tonne week-on-week"),
    AlloyQuote("ac_2024-03-14", "SPOT", 207000, "to reach INR 207,000 per tonne week-on-week, excluding GST, in ex-works Delhi"),
    AlloyQuote("ac_2024-03-28", "SPOT", 211000, "reaching INR 211,000 per tonne W-o-W exw Delhi"),
    AlloyQuote("ac_2024-05-09", "SPOT", 216000, "now standing at INR 216,000 per tonne week-on-week exw Delhi NCR"),
    AlloyQuote("ac_2024-05-30", "SPOT", 216000, "reaching INR 216,000 per tonne week-over-week"),
    AlloyQuote("ac_2024-06-13", "SPOT", 215000, "in Delhi NCR, now at INR 215,000 per tonne"),
    AlloyQuote("ac_2024-07-12", "SPOT", 213000, "ADC12 spot prices were evaluated at INR 213,000 per tonne (ex-Delhi)"),
    AlloyQuote("ac_2024-08-01", "SPOT", 209000, "ADC12 spot prices were assessed at INR 209,000 per tonne ex-Delhi"),
    AlloyQuote("ac_2024-08-10", "SPOT", 209000, "ADC12 spot prices were assessed at INR 209,000 per tonne ex-Delhi", use=False,
               exclude_reason="monthly review restating the 01-Aug-2024 weekly assessment"),
    AlloyQuote("ac_2024-11-21", "NON_OEM", 201000, "ADC12 (non-OEM) grade stood at INR 201,000/tonne (t) in Delhi"),
    AlloyQuote("ac_2024-12-05", "NON_OEM", 201000, "ADC12 (non-OEM) grade stood at INR 201,000/t in Delhi"),
    AlloyQuote("ac_2024-12-05", "OEM", 209000, "OEM-approved ADC12 were at INR 209,000/t ex Delhi", use=False,
               exclude_reason="used only to measure the OEM − non-OEM gap (same article has the non-OEM print)"),
    AlloyQuote("ac_2024-12-11b", "NON_OEM", 201000, "non-OEM grade of ADC12 stood at INR 201,000/t in Delhi", use=False,
               exclude_reason="monthly assessment restating the 05-Dec-2024 weekly non-OEM print"),
    AlloyQuote("ac_2024-12-11b", "OEM", 209000, "the OEM-approved grade at INR 209,000/t in Delhi", use=False,
               exclude_reason="used only to measure the OEM − non-OEM gap"),
    AlloyQuote("ac_2025-02-07", "OEM", 208000, "OEM-approved ADC12 in both Delhi and Chennai was priced at INR 208,000/tonne (t)"),
    AlloyQuote("ac_2025-03-12", "OEM", 217000, "the OEM grade of ADC12 stood at INR 217,000 per tonne in Delhi"),
    AlloyQuote("ac_2025-12-11", "OEM", 232000, "Delhi: INR 232,000 per tonne (USD 2,569.11 per tonne), stable M-o-M"),
]


# --------------------------------------------------------------------------------------------- fetchers
def _article_path(key: str):
    slug = ARTICLES[key].url.rstrip("/").split("/")[-1][-90:]
    return ALCIRCLE_DIR / f"{key}_{slug}.html"


def article_text(key: str, refresh: bool = False) -> str:
    raw = fetch_cached(ARTICLES[key].url, _article_path(key), refresh=refresh, min_bytes=20_000,
                       validator=lambda b: b"alcircle" in b.lower()[:5000] or b"AlCircle" in b)
    return html_to_text(raw)


def tradestat_path(year: int, month: int, rv: int):
    return TRADESTAT_DIR / f"meidb_cwac_import_{HS_CODE}_{year}{month:02d}_rv{rv}.html"


def _tradestat_ok(body: bytes) -> bool:
    return HS_CODE.encode() in body and b"S.No" in body and b"Total" in body


def tradestat_page(year: int, month: int, rv: int, refresh: bool = False) -> bytes:
    """Cached POST of the TRADESTAT form (a fresh session + CSRF token per download)."""

    def download() -> bytes:
        sess = requests.Session()
        page = http_get(TRADESTAT_URL, session=sess, timeout_s=60)
        token = re.search(rb'name="_token" value="([^"]+)"', page)
        if token is None:
            raise TransientFetchError("TRADESTAT form token not found")
        r = sess.post(TRADESTAT_URL, timeout=90, headers={"User-Agent": BROWSER_UA, "Referer": TRADESTAT_URL}, data={
            "_token": token.group(1).decode(), "cwacimHSCODE": HS_CODE, "hscode_value": "", "description_value": "",
            "cwacimMonth": str(month), "cwacimYear": str(year), "cwacimReportVal": str(rv), "cwacimReportYear": "2"})
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientFetchError(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise PermanentFetchError(f"HTTP {r.status_code}")
        return r.content

    source = (f"POST {TRADESTAT_URL} cwacimHSCODE={HS_CODE} cwacimMonth={month} cwacimYear={year} "
              f"cwacimReportVal={rv} cwacimReportYear=2")
    return cached_download(tradestat_path(year, month, rv), download, source=source, refresh=refresh,
                           min_bytes=20_000, validator=_tradestat_ok, retries=5, backoff_s=4.0)


def _totals(page: bytes) -> tuple[float, float]:
    """(previous-year month total, current-year month total) from a TRADESTAT all-countries page."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", page.decode("utf-8", "replace")))
    m = _TOTAL.search(text[text.find("S.No"):])
    if m is None:
        raise ValueError("TRADESTAT page has no Total row")
    return float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))


# --------------------------------------------------------------------------------------------- tables
def ecb_usdinr_2023_2025(refresh: bool = False) -> pd.Series:
    s = {}
    for ccy in ("INR", "USD"):
        raw = fetch_cached(ECB_EVIDENCE_URL.format(ccy=ccy), ECB_EVIDENCE_DIR / f"ecb_exr_eur{ccy.lower()}_2023-01-01_2025-12-31.csv",
                           refresh=refresh, min_bytes=10_000, validator=lambda b: b"OBS_VALUE" in b[:3_000])
        df = pd.read_csv(io.BytesIO(raw), usecols=["TIME_PERIOD", "OBS_VALUE"]).dropna()
        s[ccy] = pd.Series(df["OBS_VALUE"].astype(float).to_numpy(), index=pd.to_datetime(df["TIME_PERIOD"]))
    return (s["INR"] / s["USD"]).dropna().sort_index()


def monthly_unit_values() -> pd.DataFrame:
    rows: dict[pd.Period, dict] = {}
    for year, months in UV_PAGE_YEARS.items():
        for month in months:
            v_prev, v_cur = _totals(tradestat_page(year, month, RV_VALUE))
            q_prev, q_cur = _totals(tradestat_page(year, month, RV_QTY))
            for per, v, q, own in ((pd.Period(f"{year - 1}-{month:02d}", "M"), v_prev, q_prev, False),
                                   (pd.Period(f"{year}-{month:02d}", "M"), v_cur, q_cur, True)):
                if per in rows and not own:
                    continue  # the year's own page wins over the next year's prior-year column
                rows[per] = {"month": per, "value_usd_mn": v, "qty_kg": q, "uv_usd_t": v * 1e6 / q * 1000.0,
                             "page": f"{year}-{month:02d}"}
    return pd.DataFrame(sorted(rows.values(), key=lambda r: r["month"])).set_index("month")


def lme_daily_extended(col: str = "lme_3m_usd_t") -> pd.Series:
    """LME official `col` from lme_daily.csv (2018–2022) plus cached Westmetall pages for 2023–2025."""
    lme = pd.read_csv(PROCESSED_DIR / "lme_daily.csv", parse_dates=["date"]).set_index("date")[col]
    extra = []
    for year in LME_EXTRA_YEARS:
        df = fetch_lme.parse_westmetall_html(fetch_lme.fetch_year(year))
        fetch_lme._check_year(df, year)
        extra.append(pd.Series(df[col].to_numpy(float), index=pd.to_datetime(df["date"])))
    s = pd.concat([lme, *extra]).sort_index()
    return s[~s.index.duplicated(keep="first")].dropna()


def lme_3m_daily() -> pd.Series:
    return lme_daily_extended("lme_3m_usd_t")


def mix_ratios(uv: pd.DataFrame, lme3m: pd.Series) -> pd.DataFrame:
    avg = lme3m.groupby(lme3m.index.to_period("M")).mean()
    out = pd.DataFrame({"lme_3m_avg_usd_t": avg})
    out.index.name = "contract_month"
    for lag in (1, 2, 3):
        out[f"uv_m_plus_{lag}_usd_t"] = [uv["uv_usd_t"].get(m + lag, np.nan) for m in out.index]
        out[f"mix_ratio_lag{lag}"] = out[f"uv_m_plus_{lag}_usd_t"] / out["lme_3m_avg_usd_t"]
    out["mix_ratio_pit"] = [uv["uv_usd_t"].get(m - 1, np.nan) / avg.get(m - 3, np.nan) for m in out.index]
    return out


def article_texts() -> dict[str, str]:
    return {k: article_text(k) for k in ARTICLES}


def quotes_table(lme3m: pd.Series, mix: pd.DataFrame, lag: int, texts: dict[str, str]) -> pd.DataFrame:
    for key, art in ARTICLES.items():
        d = _ARTICLE_DATE.search(texts[key])
        if d is None or dt.datetime.strptime(d.group(1).title(), "%d %B %Y").date().isoformat() != art.date:
            raise ValueError(f"{key}: page date {d.group(1) if d else None} != {art.date}")
    for key, snip in LABEL_SNIPPETS:
        if snip not in texts[key]:
            raise ValueError(f"{key}: label snippet not found: {snip!r}")
    rows = []
    for q in QUOTES:
        if q.snippet not in texts[q.article]:
            raise ValueError(f"{q.article}: snippet not found (article changed or cache corrupt): {q.snippet!r}")
        pub = pd.Timestamp(ARTICLES[q.article].date)
        ref = lme3m[lme3m.index < pub]
        ref_day, ref_px = ref.index[-1], float(ref.iloc[-1])
        same_day = lme3m.get(pub, np.nan)
        month = pub.to_period("M")
        ratio = q.price_usd_t / ref_px
        clean = ratio / (1.0 - q.attach_frac)
        mix_r = float(mix.loc[month, f"mix_ratio_lag{lag}"])
        rows.append({
            "article_date": ARTICLES[q.article].date, "grade": q.grade, "origin": q.origin, "kind": q.kind,
            "price_usd_t": q.price_usd_t, "basis": q.basis, "attach_frac": q.attach_frac,
            "attach_source": q.attach_source, "lme_ref_date": ref_day.date().isoformat(), "lme_3m_ref_usd_t": ref_px,
            "quote_ratio": ratio, "clean_ratio": clean, "contract_month": str(month),
            f"mix_ratio_lag{lag}": mix_r, "diff_clean": clean - mix_r, "diff_raw": ratio - mix_r,
            "diff_clean_same_day_lme": (q.price_usd_t / same_day / (1 - q.attach_frac) - mix_r)
            if np.isfinite(same_day) else np.nan,
            "use": q.use, "exclude_reason": q.exclude_reason, "url": ARTICLES[q.article].url, "snippet": q.snippet,
        })
    return pd.DataFrame(rows)


def differentials(quotes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for g in GRADES:
        sub = quotes[(quotes["grade"] == g) & quotes["use"]]
        ass = sub[sub["kind"] == "ASSESSMENT"]
        rows.append({
            "grade": g, "n_quotes": len(sub), "n_assessments": len(ass),
            "median_diff_clean": float(sub["diff_clean"].median()),
            "p25_diff_clean": float(sub["diff_clean"].quantile(0.25)),
            "p75_diff_clean": float(sub["diff_clean"].quantile(0.75)),
            "median_diff_clean_assessments_only": float(ass["diff_clean"].median()),
            "median_diff_raw": float(sub["diff_raw"].median()),
            "median_diff_clean_same_day_lme": float(sub["diff_clean_same_day_lme"].median()),
            "median_clean_ratio": float(sub["clean_ratio"].median()),
        })
    return pd.DataFrame(rows).set_index("grade")


def alloy_table(texts: dict[str, str]) -> pd.DataFrame:
    """ADC12 vs duty-paid LME cash parity on the day before publication (Part B)."""
    cash = lme_daily_extended("lme_cash_usd_t")
    fx = ecb_usdinr_2023_2025()
    duty = 1.0 + config.value("bcd_primary_al_hs7601") * (1.0 + config.value("sws_rate_on_bcd"))
    parity_daily = (cash * fx.reindex(cash.index).ffill()).dropna() * duty
    by_article = {(q.article, q.series): q.price_inr_t for q in ALLOY_QUOTES}
    oem_gaps = [by_article[(a, "OEM")] - by_article[(a, "NON_OEM")] for a in ("ac_2024-12-05", "ac_2024-12-11b")]
    oem_gap = float(np.mean(oem_gaps))
    rows = []
    for q in ALLOY_QUOTES:
        if q.snippet not in texts[q.article]:
            raise ValueError(f"{q.article}: ADC12 snippet not found: {q.snippet!r}")
        pub = pd.Timestamp(ARTICLES[q.article].date)
        prior = parity_daily[parity_daily.index < pub]
        ref_day = prior.index[-1]
        non_oem = q.price_inr_t - (oem_gap if q.series == "OEM" else 0.0)
        rows.append({
            "article_date": ARTICLES[q.article].date, "series": q.series, "adc12_inr_t": q.price_inr_t,
            "adc12_non_oem_basis_inr_t": non_oem, "lme_ref_date": ref_day.date().isoformat(),
            "lme_cash_usd_t": float(cash.loc[ref_day]), "usdinr_ecb": float(fx[fx.index <= ref_day].iloc[-1]),
            "duty_paid_cash_parity_inr_t": float(prior.iloc[-1]),
            "premium_vs_cash_parity_inr_t": non_oem - float(prior.iloc[-1]),
            f"premium_vs_trailing{TRAILING_PARITY_BDAYS}_parity_inr_t": non_oem - float(prior.iloc[-TRAILING_PARITY_BDAYS:].mean()),
            "oem_gap_inr_t": oem_gap, "use": q.use, "exclude_reason": q.exclude_reason,
            "url": ARTICLES[q.article].url, "snippet": q.snippet,
        })
    return pd.DataFrame(rows)


TRAILING_WINDOWS_TESTED = (1, 20, 40, 60, 90, 120, 180, 250)


def trailing_window_dispersion(alloy: pd.DataFrame) -> pd.DataFrame:
    """Premium dispersion against trailing-parity references of different lengths (1 = spot parity)."""
    cash = lme_daily_extended("lme_cash_usd_t")
    fx = ecb_usdinr_2023_2025()
    duty = 1.0 + config.value("bcd_primary_al_hs7601") * (1.0 + config.value("sws_rate_on_bcd"))
    parity = (cash * fx.reindex(cash.index).ffill()).dropna() * duty
    u = alloy[alloy["use"]]
    rows = []
    for n in TRAILING_WINDOWS_TESTED:
        prem = [r.adc12_non_oem_basis_inr_t - parity[parity.index < pd.Timestamp(r.article_date)].iloc[-n:].mean()
                for r in u.itertuples()]
        rows.append({"trailing_lme_days": n, "median_premium_inr_t": float(np.median(prem)),
                     "std_premium_inr_t": float(np.std(prem, ddof=1))})
    return pd.DataFrame(rows)


def alloy_summary(alloy: pd.DataFrame) -> pd.DataFrame:
    u = alloy[alloy["use"]]
    prem = u["premium_vs_cash_parity_inr_t"]
    slope, intercept = np.polyfit(u["duty_paid_cash_parity_inr_t"], u["adc12_non_oem_basis_inr_t"], 1)
    trail = u[f"premium_vs_trailing{TRAILING_PARITY_BDAYS}_parity_inr_t"]
    return pd.DataFrame([{
        "n": len(u), "first": u["article_date"].min(), "last": u["article_date"].max(),
        "median_premium_inr_t": float(prem.median()), "mean_premium_inr_t": float(prem.mean()),
        "min_premium_inr_t": float(prem.min()), "max_premium_inr_t": float(prem.max()),
        "std_premium_inr_t": float(prem.std(ddof=1)),
        "passthrough_slope_adc12_on_parity": float(slope), "passthrough_intercept_inr_t": float(intercept),
        "corr_premium_parity": float(np.corrcoef(prem, u["duty_paid_cash_parity_inr_t"])[0, 1]),
        f"median_premium_vs_trailing{TRAILING_PARITY_BDAYS}_inr_t": float(trail.median()),
        f"std_premium_vs_trailing{TRAILING_PARITY_BDAYS}_inr_t": float(trail.std(ddof=1)),
        "oem_gap_inr_t": float(u["oem_gap_inr_t"].iloc[0]),
    }])


def grade_factor_table(mix: pd.DataFrame, diffs: pd.DataFrame) -> pd.DataFrame:
    """The 2022 paths written to scrap_grades.yaml: mix ratio (lag from the register) + rounded grade differential."""
    out = mix.loc[CONTRACT_MONTHS_2022].copy()
    out.index.name = "contract_month"
    lag = int(config.value("grade_factor_lag_months"))
    out["mix_ratio"] = out[f"mix_ratio_lag{lag}"]
    for g in GRADES:
        out[f"grade_factor_{g}"] = (out["mix_ratio"].round(3) + rounded_diff(diffs.loc[g, "median_diff_clean"])).round(3)
    return out


def rounded_diff(x: float) -> float:
    """Differentials are published to 0.005 of LME: finer precision would overstate what 2024–25 medians can say."""
    return round(round(x / 0.005) * 0.005, 3)


def build() -> dict[str, pd.DataFrame]:
    lag = int(config.value("grade_factor_lag_months"))
    uv = monthly_unit_values()
    lme3m = lme_3m_daily()
    mix = mix_ratios(uv, lme3m)
    texts = article_texts()
    quotes = quotes_table(lme3m, mix, lag, texts)
    diffs = differentials(quotes)
    factors = grade_factor_table(mix, diffs)
    alloy = alloy_table(texts)
    return {"uv": uv, "mix": mix, "quotes": quotes, "diffs": diffs, "factors": factors, "alloy": alloy,
            "alloy_summary": alloy_summary(alloy), "trailing": trailing_window_dispersion(alloy)}


def check_register(tables: dict[str, pd.DataFrame], tol: float = 5e-4) -> list[str]:
    """Differences between the YAML register and this evidence (empty list = consistent)."""
    problems = []
    diffs, factors = tables["diffs"], tables["factors"]
    mix_keys = {"grade_factor_mix": "mix_ratio", "grade_factor_mix_lag1": "mix_ratio_lag1",
                "grade_factor_mix_lag3": "mix_ratio_lag3", "grade_factor_mix_pit": "mix_ratio_pit"}
    for per, row in factors.iterrows():
        d = dt.date(per.year, per.month, 15)
        for key, col in mix_keys.items():
            if abs(config.value(key, d) - round(row[col], 3)) > tol:
                problems.append(f"{key} {d}: YAML {config.value(key, d)} != evidence {row[col]:.3f}")
        for g in GRADES:
            if abs(config.value(f"grade_factor_{g}", d) - row[f"grade_factor_{g}"]) > tol:
                problems.append(f"grade_factor_{g} {d}: YAML {config.value(f'grade_factor_{g}', d)} != "
                                f"{row[f'grade_factor_{g}']:.3f}")
    for g in GRADES:
        want = rounded_diff(diffs.loc[g, "median_diff_clean"])
        if abs(config.value(f"grade_factor_diff_{g}") - want) > tol:
            problems.append(f"grade_factor_diff_{g}: YAML {config.value(f'grade_factor_diff_{g}')} != evidence {want}")
    s = tables["alloy_summary"].iloc[0]
    want_prem = round(s["median_premium_inr_t"] / 1000.0) * 1000.0
    if config.value("domestic_anchor_premium_inr_t") != want_prem:
        problems.append(f"domestic_anchor_premium_inr_t: YAML {config.value('domestic_anchor_premium_inr_t')} != "
                        f"evidence median {want_prem:.0f}")
    want_trail = round(s[f"median_premium_vs_trailing{TRAILING_PARITY_BDAYS}_inr_t"] / 1000.0) * 1000.0
    if config.value("domestic_anchor_premium_trailing_inr_t") != want_trail:
        problems.append(f"domestic_anchor_premium_trailing_inr_t: YAML "
                        f"{config.value('domestic_anchor_premium_trailing_inr_t')} != evidence {want_trail:.0f}")
    if config.value("domestic_anchor_trailing_bdays") != TRAILING_PARITY_BDAYS:
        problems.append("domestic_anchor_trailing_bdays differs from TRAILING_PARITY_BDAYS")
    want_slope = round(s["passthrough_slope_adc12_on_parity"], 2)
    if abs(config.value("domestic_anchor_passthrough_frac") - want_slope) > 1e-9:
        problems.append(f"domestic_anchor_passthrough_frac: YAML {config.value('domestic_anchor_passthrough_frac')} "
                        f"!= evidence {want_slope}")
    return problems


def main() -> None:
    tables = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tables["uv"].reset_index().assign(month=lambda d: d["month"].astype(str)).round(4).to_csv(
        OUT_DIR / "dgcis_hs76020010_monthly_unit_values.csv", index=False, lineterminator="\n")
    tables["mix"].reset_index().assign(contract_month=lambda d: d["contract_month"].astype(str)).round(4).to_csv(
        OUT_DIR / "mix_ratio_by_contract_month.csv", index=False, lineterminator="\n")
    tables["quotes"].round(4).to_csv(OUT_DIR / "grade_quotes_2024_2025.csv", index=False, lineterminator="\n")
    tables["diffs"].reset_index().round(4).to_csv(OUT_DIR / "grade_differentials.csv", index=False,
                                                  lineterminator="\n")
    tables["factors"].reset_index().assign(contract_month=lambda d: d["contract_month"].astype(str)).round(4).to_csv(
        OUT_DIR / "grade_factor_paths_2022.csv", index=False, lineterminator="\n")
    tables["alloy"].round(2).to_csv(OUT_DIR / "adc12_vs_duty_paid_parity.csv", index=False, lineterminator="\n")
    tables["alloy_summary"].round(4).to_csv(OUT_DIR / "adc12_anchor_summary.csv", index=False, lineterminator="\n")
    tables["trailing"].round(1).to_csv(OUT_DIR / "adc12_trailing_parity_dispersion.csv", index=False, lineterminator="\n")
    s = tables["alloy_summary"].iloc[0]
    print(f"[fetch_price_evidence] ADC12 premium vs duty-paid cash parity: median {s['median_premium_inr_t']:,.0f}, "
          f"range {s['min_premium_inr_t']:,.0f}..{s['max_premium_inr_t']:,.0f} INR/t (n={s['n']}); short-run "
          f"pass-through {s['passthrough_slope_adc12_on_parity']:.2f}")
    d = tables["diffs"]
    print("[fetch_price_evidence] differentials (median clean quote ratio − lag-2 DGCIS mix ratio): " +
          "; ".join(f"{g} {d.loc[g, 'median_diff_clean']:+.3f} (n={d.loc[g, 'n_quotes']})" for g in GRADES))
    problems = check_register(tables)
    if problems:
        raise ValueError("register disagrees with the cached evidence:\n  " + "\n  ".join(problems))
    print(f"[fetch_price_evidence] register consistent with evidence -> {OUT_DIR}")


if __name__ == "__main__":
    main()
