# Market data (Phase 0): LME, USD/INR, rates & forwards, MCX Aluminium

Owner modules: `desk/data/fetch_lme.py`, `desk/data/fetch_fx.py`, `desk/data/mcx.py` · Params:
`config/params/rates.yaml`, `config/params/market_proxy.yaml` · Tests: `tests/test_data_market.py` (18 tests) ·
Retrieval date for every download below: **2026-09-16**.

## 1. Output files and provenance flags

| File / column(s) | Flag | Source | Transformation |
|---|---|---|---|
| `lme_daily.csv`: `lme_cash_usd_t`, `lme_3m_usd_t`, `lme_stock_mt` | DIRECT | Westmetall yearly tables (republish LME official cash/3M settlement prices and LME stocks) | HTML parse; thousands separators removed; 2018-01-02 → 2022-12-30 |
| `lme_daily.csv`: `lme_cash_3m_spread_usd_t` | DIRECT (derived) | same | cash − 3M; **positive = backwardation, negative = contango** |
| `fx_rates_daily.csv`: `usdinr` | PROXY (`usdinr_src = ECB_CROSS`) | ECB reference rates EUR/INR and EUR/USD | EURINR ÷ EURUSD, 4 dp; `MANUAL_RBI` override supported |
| `rbi_repo_pa`, `fed_funds_upper_pa` | DIRECT | RBI MPC resolutions; Federal Reserve open-market table | step paths in `rates.yaml`, every step VERIFIED |
| `usd_rate_3m_pa` | PROXY | US Treasury daily 13-week bill rate (coupon equivalent) | × 360/365 → ACT/360 money-market yield; ffill ≤ 5 days onto ECB calendar |
| `inr_rate_3m_pa` | PROXY | OECD MEI "short-term interest rates" (IR3TIB), India, monthly | `repo(d) + [OECD(month) − mean calendar-month repo]` |
| `fwd_premium_3m_pa`, `usdinr_fwd_1m`, `usdinr_fwd_3m` | PROXY | CIP (`desk.units.fx_forward`) on the columns above | 3M rates used for both tenors; premium = (F3m/S − 1) × 365/days |
| MCX `mcx_al_*` (built by `build_panel` via `mcx.load_or_proxy_mcx`) | PROXY (`PROXY_IMPORT_PARITY`) | LME cash × USDINR × duty factor + premium | see §6; no bhavcopy extract exists, so no row is DIRECT |

## 2. Sources, exact URLs, caches

| Series | URL retrieved | Cache (SHA-256 prefix) |
|---|---|---|
| LME Al 2018–2022 | `https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Al_cash&year=<year>` | `data/raw/westmetall_lme_al_<year>.html` (2018 `9dabad4b`, 2019 `f96ae582`, 2020 `83a178b7`, 2021 `f4ccbe39`, 2022 `ce377d0f`) |
| EUR/INR | `https://data-api.ecb.europa.eu/service/data/EXR/D.INR.EUR.SP00.A?startPeriod=2017-12-01&endPeriod=2022-12-31&format=csvdata` | `data/raw/ecb_exr_eurinr_2017-12-01_2022-12-31.csv` (`50e0664b`) |
| EUR/USD | same with `D.USD.EUR.SP00.A` | `data/raw/ecb_exr_eurusd_2017-12-01_2022-12-31.csv` (`9932ecc7`) |
| UST bills | `https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/<year>/all?type=daily_treasury_bill_rates&field_tdr_date_value=<year>&page&_format=csv` (2017–2022) | `data/raw/rates/ust_daily_bill_rates_<year>.csv` |
| India 3M | `https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0/IND.M.IR3TIB.PA.....?startPeriod=2017-12&endPeriod=2022-12&dimensionAtObservation=AllDimensions` (header `Accept: application/vnd.sdmx.data+csv`) | `data/raw/rates/oecd_finmark_ind_ir3tib_2017-12_2022-12.csv` (`845f754d`) |
| RBI repo steps | `https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=<id>` (ids in §4) | not cached (verification only) |
| Fed funds steps | `https://www.federalreserve.gov/monetarypolicy/openmarket.htm` | not cached (verification only) |
| 1Y fwd premium datapoints | `https://www.business-standard.com/article/finance/as-rbi-spreads-out-fx-interventions-forward-premium-hits-11-year-lows-122101700968_1.html` | not cached (comparison only) |
| MCX mirror (not used as DIRECT) | `https://commoditieschart.net/metals/aluminium/mcx-aluminium-futures-prices`, `.../mcx-aluminium-2m-futures-prices`, `.../lme-aluminium-usd-prices` | `data/raw/mcx_thirdparty/commoditieschart_{mcx_aluminium_nearest,mcx_aluminium_2m,lme_aluminium}_raw.html` (fetched via `desk.data.fetch_mcx_mirror`) (`cf93c923`, `929507b0`, `b75ce336`); extract `data/interim/mcx_thirdparty_commoditieschart_2017_2022.csv` |

The partial ECB caches from the scaffold (`ecb_exr_eur{inr,usd}_2021-06_2022-09.csv`) are kept untouched; the new
full-range downloads match them exactly on all 347 overlapping dates (max abs difference 0.0).

## 3. Validation results

**LME (hard checks in `fetch_lme.validate`, all pass):** 1,264 rows; per year 2018: 253, 2019: 253, 2020: 254,
2021: 253, 2022: 251 (band 245–256); dates unique and sorted; all prices positive; zero blank cells; no daily cash
move beyond ±15 % (largest in the window −12.95 % log on 2022-03-08, the day after the all-time high); anchor
**2022-03-07 cash 3,984.5 / 3M 3,968.0** exact; every page's dates belong to the requested year (guards against the
site silently serving the current year). The 2021 and 2022 caches pre-dated this stage; both were re-downloaded live
into scratch and parse to identical rows (253 and 251).

**FX / rates (`fetch_fx.validate`, all pass):** 1,301 ECB days 2017-12-01 → 2022-12-30; ECB INR and USD calendars
identical; no NaNs; USDINR inside 60–90 (2022 inside 70–84, tested); rates inside −1 %…12 %; forward above spot on
exactly the days INR 3M / 365 > USD 3M / 360; no daily USDINR log move > 4 %. Only 3 LME days in 2018–2022 lack an
ECB fixing (max gap 1 calendar day), none in the Mar–Aug 2022 window.

**Determinism / offline:** both fetchers were run with network, then with `DESK_OFFLINE=1`; outputs are
byte-identical (`lme_daily.csv` SHA-256 `7ab82547…`, `fx_rates_daily.csv` `24f8ea6d…`). The offline test
monkeypatches `requests.Session.get` to fail, so the rebuild provably uses only the cache.

## 4. Policy-rate verification (rates.yaml — VERIFIED)

RBI repo, each step read from the RBI press release text ("…policy repo rate under the LAF by X bps to Y per cent"):

| Effective | Repo | prid | | Effective | Repo | prid |
|---|---|---|---|---|---|---|
| 2017-08-02 | 6.00 % | 41256 | | 2020-03-27 | 4.40 % | 49581 |
| 2018-06-06 | 6.25 % | 44125 | | 2020-05-22 | 4.00 % | 49843 |
| 2018-08-01 | 6.50 % | 44636 | | 2022-05-04 | 4.40 % | 53652 (off-cycle) |
| 2019-02-07 | 6.25 % | 46235 | | 2022-06-08 | 4.90 % | 53832 |
| 2019-04-04 | 6.00 % | 46722 | | 2022-08-05 | 5.40 % | 54148 |
| 2019-06-06 | 5.75 % | 47225 | | 2022-09-30 | 5.90 % | 54541 (MPC minutes) |
| 2019-08-07 | 5.40 % | 47818 | | 2022-12-07 | 6.25 % | 54818 |
| 2019-10-04 | 5.15 % | 48319 | | | | |

Fed funds target upper bound (effective dates from the Fed table): 2017-06-15 1.25; 2017-12-14 1.50; 2018-03-22
1.75; 2018-06-14 2.00; 2018-09-27 2.25; 2018-12-20 2.50; 2019-08-01 2.25; 2019-09-19 2.00; 2019-10-31 1.75;
2020-03-04 1.25; 2020-03-16 0.25; 2022-03-17 0.50; 2022-05-05 1.00; 2022-06-16 1.75; 2022-07-28 2.50; 2022-09-22
3.25; 2022-11-03 4.00; 2022-12-15 4.50 (%). The seed's 2022 dates were already right; history before 2022 was added.

## 5. Rates and forwards — method notes and "what this does and doesn't tell you"

- **Review fixes (2026-09-16).** (1) A missing or invalid rate cache under `DESK_OFFLINE=1` now raises; the first build
  silently swapped the whole Treasury series for the fed-funds fallback and exited 0 (reproduced: max 92 bp change on
  every panel row). Online, fallbacks apply per missing year (Treasury) or month (OECD), and are labelled per row in
  `rates_src`; `build_panel` downgrades the rate/forward columns to ASSUMPTION if any panel day used one. (2) Treasury
  holiday carries (43 ECB days; 3 in the window: 30-May, 20-Jun, 4-Jul-2022) are flagged `usd_rate_3m_filled`, capped
  at 5 business days. (3) `usdinr` vs the RBI/FBIL reference rate: the first docs said "within a few paise"; that was
  never measured and the ECB cross itself moved a median 12 paise/day (max 63) in the window — now stated as PENDING.

- **USD 3M.** T-bill coupon-equivalent (a 365-day bond-equivalent yield) × 360/365 = ACT/360 money-market yield,
  matching `fx_forward`'s USD day count. Bills vs Fed upper bound: mean −7 bp over 2017-12..2022-12, quarterly means
  from −31 bp (Q3-2019) to +31 bp (Q3-2022) — hence the fallback spread in `rates.yaml` is a poor substitute.
- **INR 3M.** No daily Indian 3M series was retrievable without a CAPTCHA (FBIL's site loads Google reCAPTCHA; the
  CCIL FBIL T-bill page returned Akamai 403; FRED timed out from this machine). OECD IR3TIB is labelled "Short-term
  interest rates" in the OECD code list; the underlying Indian instrument (91-day T-bill vs 3M interbank) was
  **not verified** — verify: PENDING — read the OECD MEI India source note or compare to RBI 91-day T-bill cut-offs.
  Monthly spread vs repo: mean −12 bp (std 45 bp), from −94 bp (Nov-2020) to +56 bp (Nov-2022). In 2022 the
  spread turned positive from May (+33 bp) as hikes were priced.
- **What the forward columns tell you:** a CIP-consistent onshore forward that moves with the real INR–USD 3M rate
  differential, good enough to value the desk's USD/INR hedges and to show *why* hedging cost fell through 2022
  (Fed hiking faster than RBI). **What they don't:** actual traded onshore forward points, which also reflect RBI
  forward-book intervention, dollar liquidity and exporter/importer flow; the 1M tenor reuses 3M rates (flat curve);
  spot-lag (T+2) is ignored; the INR leg carries ≤ 1 month look-ahead from the monthly average.

**Forward premium path (proxy, month-end values):**

| Month-end 2022 | USDINR | Repo | Fed upper | INR 3M | USD 3M | 3M fwd | 3M premium p.a. |
|---|---|---|---|---|---|---|---|
| 1 Mar (window start) | 75.7046 | 4.00 % | 0.25 % | 3.78 % | 0.32 % | 76.3643 | 3.46 % |
| 31 Mar | 75.7896 | 4.00 % | 0.50 % | 3.78 % | 0.51 % | 76.4047 | 3.26 % |
| 29 Apr | 76.5066 | 4.00 % | 0.50 % | 3.93 % | 0.83 % | 77.0939 | 3.08 % |
| 31 May | 77.6916 | 4.40 % | 1.00 % | 4.73 % | 1.13 % | 78.3915 | 3.57 % |
| 30 Jun | 79.0536 | 4.90 % | 1.75 % | 5.14 % | 1.67 % | 79.7383 | 3.44 % |
| 29 Jul | 79.3116 | 4.90 % | 2.50 % | 5.31 % | 2.36 % | 79.8923 | 2.90 % |
| 31 Aug | 79.5465 | 5.40 % | 2.50 % | 5.64 % | 2.89 % | 80.0806 | 2.69 % |

Window range of the proxy premium: 2.60 % (2022-08-01) to 3.88 % (2022-05-05), mean 3.26 %.

**Comparison with published real forward premia** (only data points actually retrieved; the article quotes the
**1-year** tenor, our proxy is **3-month** — not like-for-like, shown for direction/level only):

| Date | Published 1Y annualised premium (Business Standard, 17-Oct-2022, URL in §2) | Proxy 3M premium |
|---|---|---|
| 2021-12-31 | 4.65 % | 3.52 % |
| 2022-09-30 | 2.83 % | 2.98 % |
| 2022-10-17 | 2.50 % close (2.47 % intraday low, "lowest since October 2011") | 2.35 % |

Both fall by ~1.2–2.2 pp from end-2021 to mid-October 2022; the article attributes part of the compression to RBI
buy-sell swaps, which CIP on T-bill-type rates cannot capture. No 3M or 1M published premia for Mar–Aug 2022 were
found (searched Business Standard and general web; several Indian financial sites block automated fetching).
verify: PENDING — pull RBI Bulletin "Forward Premia of US$" (1-, 3-, 6-month monthly averages) for Mar–Aug 2022
from rbi.org.in / DBIE and add them to this table.

## 6. MCX Aluminium

### 6.1 Real-data attempt log (bounded)

| # | Target | Outcome |
|---|---|---|
| 1 | `https://www.mcxindia.com/` (requests.Session, browser UA) | HTTP 403 Access Denied, server AkamaiGHost, no cookies issued |
| 2 | `https://www.mcxindia.com/market-data/bhavcopy` | HTTP 403 (Akamai) |
| 3 | POST `https://www.mcxindia.com/backpage.aspx/GetDateWiseBhavCopy` `{"Date":"20220307","InstrumentName":"ALL"}` and `"FUTCOM"` | HTTP 403 (Akamai). Not pursued further: getting past bot protection is out of bounds |
| 4 | `https://www.moneycontrol.com/commodity/aluminium-price.html` | HTTP 403 (Akamai) |
| 5 | `https://in.investing.com/commodities/aluminium-mini-historical-data` | HTTP 403 Cloudflare challenge |
| 6 | `priceapi.moneycontrol.com/techCharts/commodity/history` with symbols `ALUMINIUM_<expiry>_MCX` | Format `ALUMINIUM_YYYY-MM-DD_MCX` works for the live contract (2026-08-31: 43 bars), but every expired contract tried (2022-03-31, 2022-08-31, 2023-12-29, 2024-12-31, 2025-12-31) returns `no_data` — history not retained |
| 7 | `https://www.indiainfoline.com/commodity/mcxfut/aluminium/31-mar-2022` and `31-aug-2022` | HTTP 200 but page template only, no price data |
| 8 | `https://www.ccilindia.com/...FBIL-T-Bills-Curve_BK.aspx` (for INR rates) | HTTP 403 (Akamai) |
| 9 | `https://commoditieschart.net/metals/aluminium/mcx-aluminium-futures-prices` (+ `-2m-`, `lme-aluminium-usd-prices`) | **HTTP 200; daily series embedded in page** (`{d:"YYYY-MM-DD",v:<₹/kg>}`): nearest contract 2004-04-24 → 2026-04-02 (5,593 points), 2M contract (5,428 points), unit INR/kg |
| 10 | News spot-checks of 2022 MCX levels (web search, Business Standard/Outlook) | No 2022 article with an MCX Aluminium ₹/kg level found; search-engine summaries offered numbers that were not in any retrieved page, so none are used |

### 6.2 What the mirror is, and why it is not promoted to DIRECT

Evidence it is genuine MCX data: (a) its 2018–2022 calendar skips exactly the full-day MCX closures that LME
trades through — 26 Jan (Republic Day), 15 Aug (Independence Day) and 2 Oct (Gandhi Jayanti) whenever they fall on a weekday,
2019-04-29, 2020-04-02/06/14 (13 LME days absent in total) — and includes UK bank holidays when LME is shut (2022-04-18, 05-02, 06-02, 06-03, 08-29);
(b) observed M1 ≈ duty-paid LME parity × carry (implied premium ≈ 0, §6.3); (c) weekly return correlation 0.94 with
the proxy in the window. Its own "LME aluminium" series is *not* the LME official cash price (only 14 % of 758
common 2020–2022 days match Westmetall cash exactly; mean abs difference $4.85/t, $9.67/t in 2022), so it is a different snapshot/feed.

Not DIRECT because: (1) provenance cannot be checked against MCX's own bhavcopy (403 above) and the site names no
data source; (2) it is a continuous "nearest contract" series with an undocumented roll rule — a month-end
event study of M1 day-changes showed no detectable roll jump, so contract expiries cannot be assigned reliably, and
the panel contract needs `mcx_m1_expiry`/`mcx_m2_expiry`; (3) the 2M series looks stale on some days (M2 − M1 ranges
−12.5 to +25.3 ₹/kg in the window, e.g. +7.15 on 2022-07-05 then +0.55 the next day). It is therefore stored in
`data/raw/mcx_thirdparty/` (raw pages, fetched by `desk.data.fetch_mcx_mirror`) with its extract in `data/interim/` —
moved out of `data/manual/` after review, because that folder is reserved for drop-in DIRECT files — and is used only
to calibrate the proxy premium and for Table 1.3 below. Upgrade path: drop real bhavcopy extracts as
`data/manual/mcx_aluminium_<period>.csv` (`date,contract_expiry,close_inr_kg,source`, with `source` naming the MCX
bhavcopy file or mcxindia.com URL on every row — files without it are rejected; format in `desk/data/mcx.py`) and the
panel switches those rows to `mcx_src = MANUAL`. A missing MCX day is carried (`MANUAL_FFILL`) only inside the manual
coverage; after the last manual date the panel returns to the proxy instead of extending a stale close.

**Regime bias of the proxy (review).** Friday proxy M1 − mirror M1: +10.79 (04-Mar), +5.17 to +8.34 through March, then
−3.20 (06-May), −7.52 (13-May), −5.87 (17-Jun), −6.55 (01-Jul), −4.96 (08-Jul) ₹/kg. Unbiased over the window, but too
high in the spike and too low in the trough, which widens the parity swing (market_proxy.yaml note).

### 6.3 Proxy definition and premium calibration

`spot = lme_cash_usd_t × usdinr / 1000 × (1 + 0.075 × (1 + 0.10)) + mcx_domestic_premium_inr_kg`;
`m1/m2 = spot × (1 + inr_rate_3m_pa × days_to_expiry / 365)`; expiry = last calendar day of month, rolled back to
the previous panel day (previous weekday beyond 2022-12-30). BCD/SWS come from `regulatory.yaml` (owned by the
regulatory agent, still `PENDING` there) — if they change, recompute the premium.

Implied premium = observed M1 ÷ carry − duty-paid parity: Mar–Aug 2022 mean −0.33, median +1.46, std 6.27 ₹/kg
(n = 125); full 2018–2022 mean −1.03, median −0.02, std 7.71; monthly means Mar −9.85, Apr −0.35, May +3.29,
Jun +3.48, Jul +1.43, Aug +1.13. **Set to 0.0 ₹/kg** (flag PROXY, verify PARTIAL): indistinguishable from zero and
consistent with MCX being a duty-paid Indian delivery contract.

### 6.4 Table 1.3 — proxy M1 vs observed (third-party mirror) nearest-contract close

| Statistic | Mar–Aug 2022 | 2018–2022 |
|---|---|---|
| Common days | 125 | 1,250 |
| Level correlation | 0.988 | 0.983 |
| Daily log-return correlation | 0.563 | 0.499 |
| … with proxy lagged 1 day | 0.099 | 0.042 |
| Weekly (W-FRI) return correlation | 0.937 | 0.845 |
| Basis observed − proxy: mean | −0.33 ₹/kg | −1.03 ₹/kg |
| Basis: std | 6.29 ₹/kg | 7.73 ₹/kg |
| Daily vol observed / proxy | 2.00 % / 2.31 % | 1.39 % / 1.54 % |

M2 (window): level corr 0.986, daily return corr 0.41, basis mean +1.63, std 6.28 ₹/kg; observed M2 − M1 mean
+2.88 (std 4.57) vs proxy +0.92 (std 0.05) ₹/kg.

Spot comparisons (M1, ₹/kg; observed = mirror): 01-Mar proxy 287.35 / obs 281.95; **07-Mar 332.63 / 300.95
(−31.7)**; 08-Mar 292.66 / 279.90; 13-Apr 264.94 / 268.40; 16-Jun 211.74 / 215.80; 14-Jul 202.22 / 204.15;
15-Jul 200.97 / 204.70; 31-Aug 203.95 / 206.25. Window highs: proxy 332.63 (07-Mar), observed 308.35 (04-Mar);
lows: proxy 200.97 (15-Jul), observed 204.15 (14-Jul).

**What the MCX proxy does and doesn't tell you.** It captures the level (±~3 %) and the weekly direction of Indian
aluminium prices, because MCX is anchored to duty-paid LME parity. It does **not** capture the day-to-day
cross-exchange basis: daily return correlation is only ~0.5–0.56, largely a timing mismatch (LME official prices
settle around London midday; MCX's evening session closes ~23:30 IST, so fast LME moves land on different dates —
lagging the proxy by a day does not fix it, so part is genuine basis noise). On the most extreme day, 7 Mar 2022,
the proxy overstates the observed MCX close by ~₹32/kg (~10 %). The proxy's M2−M1 is a smooth carry curve; real
far-month MCX prices are noisier. P3's "LME–MCX basis" factor should be read with this in mind.

## 7. Key statistics for the headline window (2022-03-01 → 2022-08-31)

| Metric | Value |
|---|---|
| LME cash, first / last | $3,495.5 (01-Mar) → $2,368.5 (31-Aug): −32.2 % |
| LME cash high | **$3,984.5 on 2022-03-07** (also the 2018–2022 high; 3M high $3,968.0 same day) |
| LME cash low | **$2,320.5 on 2022-07-15** (3M low $2,336.0 same day) |
| Peak → window low | −41.8 % |
| Peak → August low | $2,368.5 on 2022-08-31: −40.6 % |
| Daily log-return vol | 2.32 % (36.9 % annualised); worst day −12.95 % (08-Mar), best +3.99 % (21-Mar) |
| Cash − 3M | min −$42.0 (09-May, contango), max +$35.0 (02-Mar, backwardation), mean −$11.92, median −$14.75; 33 backwardation / 91 contango / 2 flat days; monthly means Mar −5.1, Apr −19.5, May −28.4, Jun −22.1, Jul −6.4, Aug +7.2 |
| LME stocks | 814,275 t (01-Mar) → 277,050 t (31-Aug); low 271,450 t (23-Aug) |
| USDINR (ECB cross) first / last | 75.7046 (01-Mar) → 79.5465 (31-Aug): **+5.07 % (INR depreciation)** |
| USDINR range | low 75.3350 (05-Apr), high 80.0352 (14-Jul): +6.24 % low→high |
| 3M forward premium (proxy) | 3.46 % → 2.69 %; range 2.60–3.88 %, mean 3.26 % |

2018–2022 context: LME cash low $1,421.5 (2020-04-08); Cash−3M extremes +$74.0 (2022-02-14) and −$48.5 (2022-12-14).

## 8. Open issues

1. MCX: no MCX-published data; proxy stays PROXY. Next step: obtain bhavcopy extracts from a browser session
   (or a colleague with MCX access) for Mar–Aug 2022 and save as `data/manual/mcx_aluminium_2022.csv`; spot-check the
   mirror on 5 dates first.
2. `usdinr` is the ECB cross, not the RBI reference rate, and the gap is unmeasured. Next step: fill
   `data/manual/rbi_reference_rate.csv` (`date,usdinr,source`, `source` naming RBI/FBIL) from RBI/FBIL daily
   reference-rate releases for ≥ 10 window dates and record the difference.
3. INR 3M instrument behind OECD IR3TIB unverified; 1M forward uses 3M rates; no Mar–Aug 2022 real 3M premium points.
4. MCX premium calibration depends on `bcd_primary_al_hs7601` / `sws_rate_on_bcd`, which are PENDING in
   `regulatory.yaml`.
5. `build_panel` accepts `mcx_src` values `MANUAL_FFILL` (MCX non-trading day inside manual coverage) in addition to
   `MANUAL` / `PROXY_IMPORT_PARITY`, and counts them separately in `series_provenance.csv`; this value only appears
   once real bhavcopy files exist.
