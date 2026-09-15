# CONTRACTS.md — shared build contract for every contributor (human or agent)

Scope source of truth: `docs/spec/MASTER_SPEC_V3.md` (tables 1–9). This file fixes the *interfaces* so phases can
be built independently and still reconcile to the rupee. If you must change a contract, change it here in the same
edit and say why.

> This project is unrelated to the NHAI face-attendance app in `~/Desktop/NHAI_HACKATHON`; ignore that repo's
> CLAUDE.md for anything in this folder.

## 1. Ground rules
1. **Simulation label.** Every chart (`desk.reporting.style.save_fig` does it), report, workbook sheet and PDF
   carries `desk.SIM_LABEL` = "ACADEMIC SIMULATION — not actual trades". All counterparties/vessels end in "(SIM)".
2. **Provenance flags.** Every input series and parameter is `DIRECT` (observed from a named public source),
   `PROXY` (a real observable standing in for the thing we need, or a transformation of real data), or
   `ASSUMPTION` (a judgement, with justification). **Never label reconstructed or remembered numbers DIRECT.**
   Never invent a "real" headline, price or document. If a fetch fails, fall back to a clearly-flagged proxy.
3. **Units** (Table 8.3). Column suffixes per `desk/units.py`: `_usd_t`, `_inr_t`, `_inr_kg`, `_mt`, `_usd`,
   `_inr`, `_pa`, `_frac`; `usdinr` = INR per USD. Convert only through `desk.units`. LME "$/t" ≡ USD/MT.
4. **Base currency INR.** The desk is an Indian importer; P&L is reported in ₹ (USD shown as memo).
5. **Determinism.** Any randomness seeds from `desk.RNG_SEED` via `numpy.random.default_rng`. Re-running
   `run_all.py` must reproduce every output byte-for-byte except timestamps.
6. **No hard-coded magic numbers** in model code: parameters come from `config/params/*.yaml` via
   `desk.config.value(key, date)`. Model-structure constants (e.g. 10,000 MC paths, 95 %) may live in code as
   named constants.
7. **Stages talk through files only.** Each stage module exposes `main() -> None`, reads upstream files, writes its
   own outputs, and is registered in `run_all.py`. Network access only in `fetch_*` modules; every fetcher caches
   to `data/raw/` and honours `DESK_OFFLINE=1` (use cache, never network). Wrap network calls in retries
   (this machine has a flaky TLS path).
8. **Python:** `.venv/bin/python` (3.12; pinned `requirements.txt`). Tests: `.venv/bin/python -m pytest -q`.
   Code style: typed, small functions, docstrings that explain *why*; pandas vectorised where natural.
9. **Every quant model** ships a plain-English "What this does and doesn't tell you" paragraph (Table 8.5).

## 2. Layout & ownership
```
config/params/*.yaml        assumptions register (format: desk/config.py docstring). One owner per file:
  rates.yaml, market_proxy.yaml ........ P0 market-data
  logistics.yaml ....................... P0 freight/logistics
  regulatory.yaml, exchange.yaml,
  scrap_grades.yaml, commercial.yaml ... P0 regulatory/contract research
  parity.yaml .......................... P1 (parity-only thresholds, if any)
  risk.yaml ............................ P4/P5
config/counterparties.yaml  SIM suppliers & buyers, credit limits (P2)
config/trades.yaml          authoritative trade tickets (P2)
data/raw/                   immutable downloads / caches (never hand-edited)
data/manual/                optional drop-in real files that upgrade a PROXY to DIRECT (see §4.5)
data/processed/             clean panels consumed by all later phases
desk/data/                  P0 fetchers + panel builder + dictionary generator
desk/parity/  desk/book/  desk/mtm/  desk/risk/  desk/excel/  desk/sentiment/  desk/reporting/
outputs/tables/*.csv  outputs/charts/*.png  outputs/excel/Metals_Desk_Master.xlsx  outputs/reports/*
docs/                       data dictionary, assumptions log, verification log, methodology notes
tests/                      pytest — one test module per stage (test_<stage>.py)
```

## 3. Calendar
- Panel calendar = LME trading days from the Westmetall LME official price tables, `HISTORY_START` (2018-01-02)
  → 2022-12-30. Headline window `WINDOW_START`–`WINDOW_END` (2022-03-01 → 2022-08-31); engine horizon runs to
  `HORIZON_END` (2022-09-30) so trades can settle.
- Series on other calendars (ECB FX, weekly freight) are aligned to the LME calendar by forward-fill **with a
  `*_filled` boolean column** (max 5 business days; longer gaps raise).
- "Week" = week ending Friday (`W-FRI`); weekly value = last available panel day in that week.
- MCX holidays are not modelled (documented ASSUMPTION): MCX proxy prices are on the LME calendar.

## 4. Phase 0 data contracts

### 4.1 `data/processed/lme_daily.csv` (desk.data.fetch_lme) — DIRECT
`date, lme_cash_usd_t, lme_3m_usd_t, lme_cash_3m_spread_usd_t, lme_stock_t`
- Source: westmetall.com "LME Aluminium Cash-Settlement / 3-month / stock" yearly tables (they republish LME
  official prices). Spread = cash − 3M (**positive = backwardation, negative = contango**).
- Cached raw HTML: `data/raw/westmetall_lme_al_<year>.html` for 2018–2022.

### 4.2 `data/processed/fx_rates_daily.csv` (desk.data.fetch_fx)
`date, usdinr, usdinr_src, rbi_repo_pa, fed_funds_upper_pa, inr_rate_3m_pa, usd_rate_3m_pa, fwd_premium_3m_pa,
usdinr_fwd_1m, usdinr_fwd_3m`
- `usdinr` = ECB EUR/INR ÷ ECB EUR/USD reference rates (PROXY for the RBI reference rate; typically within a few
  paise). `usdinr_src` ∈ {ECB_CROSS, MANUAL_RBI}. If `data/manual/rbi_reference_rate.csv` exists it overrides.
- Rate / forward-premium columns are PROXY (policy-rate paths from `rates.yaml` + documented term spreads);
  forwards via `desk.units.fx_forward` (covered interest parity).

### 4.3 `data/processed/freight_weekly.csv` (desk.data.fetch_freight)
`week_end, freight_jea_nsa_usd_t, freight_usec_mun_usd_t, index_name, index_value, freight_src, note`
- Lanes: **JEA_NSA** = Jebel Ali → Nhava Sheva (20ft containers); **USEC_MUN** = US East Coast → Mundra (40ft).
- USD per MT of scrap = USD per box ÷ payload MT per box (`logistics.yaml`). Level and weekly shape must each be
  flagged: e.g. shape from a real published index (Drewry WCI / SCFI) = PROXY, lane level calibration = ASSUMPTION.

### 4.4 `data/processed/headlines_weekly.csv` (desk.sentiment.fetch_news) — DIRECT (headline text)
`week_end, published_utc, source, title, link, query`
- Google News RSS search with `after:/before:` operators per week (Feb 25 → Sep 2, 2022), aluminium/LME/scrap/
  steel queries; de-duplicated; raw XML cached in `data/raw/news/`. Headlines are real public RSS items — store as
  returned, never paraphrase or invent. Sentiment scoring is P7 (`desk.sentiment.run`).

### 4.5 `data/processed/market_daily.csv` (desk.data.build_panel) — THE panel every later phase reads
One row per LME trading day, 2018-01-02 → 2022-12-30:
```
date, in_window,
lme_cash_usd_t, lme_3m_usd_t, lme_cash_3m_spread_usd_t, lme_stock_t,
usdinr, usdinr_filled, usdinr_src, rbi_repo_pa, fed_funds_upper_pa, inr_rate_3m_pa, usd_rate_3m_pa,
fwd_premium_3m_pa, usdinr_fwd_1m, usdinr_fwd_3m,
mcx_al_spot_inr_kg, mcx_al_m1_inr_kg, mcx_al_m2_inr_kg, mcx_m1_expiry, mcx_m2_expiry, mcx_src,
freight_jea_nsa_usd_t, freight_usec_mun_usd_t, freight_filled, freight_src
```
- **MCX Aluminium (5 MT lot, ₹/kg).** If `data/manual/mcx_aluminium_*.csv` (bhavcopy extracts) exist → DIRECT and
  `mcx_src = MANUAL`. Otherwise PROXY (`mcx_src = PROXY_IMPORT_PARITY`):
  `mcx_al_spot_inr_kg = lme_cash_usd_t × usdinr / 1000 × (1 + bcd_primary_al_hs7601 × (1 + sws_rate_on_bcd)) + mcx_domestic_premium_inr_kg`
  and futures `m1/m2 = spot × (1 + inr_rate_3m_pa × days_to_expiry / 365)` with expiry = last calendar day of the
  month (previous business day if not a panel day). Rationale: MCX Aluminium trades at duty-paid import parity.
  The P0 agent must attempt a real MCX download first and document the outcome.
- `data/processed/series_provenance.csv`: `column, flag, source, transformation, unit` — one row per panel column.

### 4.6 Docs generated in P0
- `docs/00_data_dictionary.md` — every processed file & column: meaning, unit, flag, source, transformation, gaps.
- `docs/00_assumptions_log.md` — rendered from `desk.config.params_frame()` grouped by file, with justification.
- `docs/verification_log.md` — one row per volatile parameter (Table 8.4): value used, authoritative source,
  what was checked, date checked, outcome (VERIFIED / PARTIAL / PENDING + exact next step). Honest statuses only.

## 5. Shared desk economics (P1 implements; Excel must reproduce the same formulas)
Per MT of scrap, week `w`, grade `g`, lane `l`:
```
fob_usd_t        = lme_3m_usd_t × grade_factor_g(w)                    (grade factor = FOB-origin % of LME)
cif_usd_t        = fob_usd_t + freight_l_usd_t + insurance_usd_t
insurance_usd_t  = insurance_rate × insured_value_uplift × (fob_usd_t + freight_l_usd_t)
av_inr_t         = cif_usd_t × customs_usdinr                           (landing charges per regulatory.yaml)
bcd_inr_t        = av_inr_t × bcd_scrap_hs7602
sws_inr_t        = bcd_inr_t × sws_rate_on_bcd
igst_inr_t       = (av_inr_t + bcd_inr_t + sws_inr_t) × igst_rate_hs7602     (memo; in cost only if no ITC)
finance_inr_t    = (av_inr_t + bcd_inr_t + sws_inr_t [+ igst]) × finance_days_l / 365 × wc_rate_inr_pa
landed_inr_t     = av_inr_t + bcd_inr_t + sws_inr_t + port_cf_charges_inr_t + finance_inr_t [+ igst if no ITC]
recovery_frac_g  = (1 − moisture_frac_g) × (1 − contamination_frac_g) × metal_yield_frac_g
anchor_inr_t     = mcx_al_m1_inr_kg × 1000 + domestic_anchor_premium_inr_t   (secondary-ingot buying price)
net_arb_inr_t    = anchor_inr_t × recovery_frac_g − landed_inr_t − conversion_cost_inr_t
window_open      = net_arb_inr_t > margin_threshold_inr_t
```
(This is Table 3.4's "anchor − landed > conversion + margin" expressed per MT of scrap so the Table 1.6 recovery
logic is explicit.) Parameter names above are the canonical YAML keys; P1 may add keys but not rename these.

## 6. Later-phase output contracts (outline — each phase documents final columns in its docs page)
- P1 `outputs/tables/parity_weekly.csv` (one row per week × grade × lane with every §5 line item + `window_open`),
  `parity_sensitivity_lme_fx.csv`, `parity_sensitivity_freight_duty.csv`, `term_structure_weekly.csv`.
- P2 `config/counterparties.yaml`, `config/trades.yaml`, `outputs/tables/trade_book.csv`,
  `trade_hedges.csv`, `trade_cashflows.csv`; validation that each trade date falls in an open parity week.
- P3 `outputs/tables/mtm_daily.csv` (date × trade × leg), `attribution_daily.csv` (date × trade × factor, factors
  exactly `desk.reporting.style.FACTOR_ORDER`, summing to total P&L with residual ≤ ₹1),
  `book_exposures_daily.csv`, `adverse_event_*.csv`, `mcx_variation_margin.csv`.
- P4 `var_daily.csv`, `var_backtest_exceptions.csv`, `kupiec.csv`, `mc_pnl_distribution.csv`, `mc_summary.csv`.
- P5 `credit_scores.csv`, `credit_tracker.csv`, `margin_liquidity.csv`; `outputs/reports/risk_policy_memo.*`.
- P6/P7 `outputs/reports/desk_note_<n>_<week>.{md,pdf}`, `post_mortem.{md,pdf}`, `interview_pack.md`,
  `sentiment_weekly.csv`; root `README.md`.
