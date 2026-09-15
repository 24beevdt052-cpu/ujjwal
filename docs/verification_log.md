# Verification log — volatile and DIRECT parameters

ACADEMIC SIMULATION — not actual trades.

MASTER_SPEC_V3 Table 8 item 4 requires the volatile parameters (MCX contract specs, HS 7602 duty, QCO status, USD/INR
forward premium, LME Cash–3M spread) to be checked against CBIC / mcxindia.com / RBI before submission. This log
records, for each of those and for every other DIRECT parameter in `config/params/{regulatory,exchange,scrap_grades,commercial}.yaml`,
what was actually checked on **2026-09-16** and with what outcome.

Status rules (honest by construction):

- **VERIFIED** — a primary or official source was fetched and read, and it states the value for (or in force during) Mar–Aug 2022.
- **PARTIAL** — the value is supported, but by a secondary reproduction, a current (not 2022-dated) page, or with a named gap.
- **PENDING** — not verified; the "next step" column says exactly what to do.

Retrieval notes: CBIC notification PDFs were downloaded through the CBIC Tax Information Portal API with TLS
verification kept on (the server omits its Sectigo intermediate; the AIA intermediate was added to the CA bundle).
mcxindia.com blocks scripted clients (Akamai 403); MCX circular PDFs were opened in a browser session and their text
extracted with pdf.js, so there is no byte copy of those PDFs in `data/raw/`. Cached copies of everything else are
under `data/raw/regulatory/`; `data/raw/_download_manifest.json` records the URL, retrieval date and sha256 of every
cached body (files cached before the manifest existed are marked `mtime_backfill`).

**Phase 0 review (2026-09-16).** Independent reviewers re-checked this log. Corrections applied: the customs-FX note
(two notifications have a ₹1.75 import−export gap), the QCO sources (URLs and caches added), the LME publication window
(the LME page itself gives two different times), `secondary_raw_material_cost_share` (a midpoint, now PROXY), and the
grade factors / anchor premium (rebuilt from 2023–25 evidence on consistent bases, section C).

## A. Table 8.4 volatile parameters

| Parameter | Value used | Authoritative source | What was checked | Date checked | Status | Next step |
|---|---|---|---|---|---|---|
| `bcd_scrap_hs7602` (HS 7602 BCD) | 0.025 | Notification 50/2017-Customs, S.No. 385 (CBIC portal id 1002538) | Principal table row read ("7602 Aluminium scrap 2.5%"); Budget/HSN amendments 06/2018, 25/2019, 01/2020, 02/2021, 55/2021, 02/2022, 02/2023 searched for 7602 / S.No. 385 — no change | 2026-09-16 | VERIFIED | Optional: open the ~40 non-Budget amendments to 50/2017 (2017–22) to close the residual gap |
| `sws_rate_on_bcd` | 0.10 | Finance Act 2018 s.110(3); Notif. 11/2018-Cus (exemptions), 13/2018-Cus | s.110 text read (indiankanoon); 11/2018 and amendments 09/2020, 14/2021, 03/2022, 24/2022 contain no chapter-76 exemption | 2026-09-16 | VERIFIED | — |
| `aidc_scrap_hs7602` | 0.0 | Notification 11/2021-Customs (AIDC rates) | Principal table has no chapter-76 goods; 2022 amendments checked by title only | 2026-09-16 | VERIFIED | Open 16/2022, 27/2022, 44/2022 texts if a reviewer asks |
| `igst_rate_hs7602` | 0.18 | Notification 1/2017-Integrated Tax (Rate), Sch. III S.No. 263 | Schedule row read; amendments 14/2021-IT(R) and 01/2022-IT(R) do not touch it | 2026-09-16 | VERIFIED | — |
| `customs_usdinr_import` (customs FX) | step path 76.05 → 80.40 | CBIC exchange-rate notifications 10, 13, 18, 32, 34, 40, 43, 49, 51, 58, 64, 66, 70, 73, 78 of 2022-Customs (N.T.) | Each PDF read: USD import/export rate and effective date; USD-neutral amendments 16, 36, 38, 42, 53, 54, 83, 85/2022 also read. Review re-extraction (PDFKit): all 15 import values match; import − export is ₹1.70 in 13 and ₹1.75 in 64/2022 and 73/2022 (note corrected) | 2026-09-16 | VERIFIED | — |
| `bis_qco_scrap_in_force_2022` (QCO status) | false | PIB release 01-Sep-2023 (PRID 1954005); Argus 14-Nov-2025; ELP Law; The Tribune/ANI 08-Jul-2026 — URLs in regulatory.yaml, all four pages cached in `data/raw/regulatory/news/` | PIB: Mines QCOs of 31-Aug-2023 "mark the first technical regulations from Ministry of Mines under the BIS Act" and cover ingots/castings, not scrap; Argus/ELP: withdrawn (announced 13-Nov-2025); Tribune: scrap standard "pending for more than two years". Review found Tribune and Argus cited without URLs; both re-retrieved | 2026-09-16 | VERIFIED | — |
| `mcx_al_lot_mt`, `mcx_al_tick_inr_kg`, `mcx_al_max_order_mt` | 5 MT, ₹0.05/kg, 150 MT | MCX/TRD/385/2021 (30-Jun-2021) and MCX/TRD/617/2022 (31-Oct-2022), Annexure 1 | Both annexures read; identical values, bracketing every 2022-traded contract | 2026-09-16 | VERIFIED | — |
| `mcx_al_initial_margin_frac`, `mcx_al_elm_frac` | 0.08 min, 0.01 min | Same circulars | Contract minima read ("Minimum 8% or based on SPAN whichever is higher"; "Minimum 1%") | 2026-09-16 | VERIFIED (minimum only) | Actual daily SPAN margin % for Mar–Aug 2022 from MCXCCL risk-parameter files |
| `mcx_al_additional_margin_frac` | 0.0 | MCX circular index, title search "Additional Margin" Jun-2021–Sep-2022 | Titles read; the Mar-2022 imposition (143/2022) and withdrawal (171/2022) texts read — gold only | 2026-09-16 | PARTIAL | Open every MCXCCL additional-margin circular Feb–Aug 2022 to rule out an aluminium clause |
| `mcx_al_expiry_rule`, `mcx_al_expiry_dates_2022` | last calendar day / preceding working day; 31-Mar … 30-Nov-2022 | Circulars above; MCX Aluminium Performance Reviews 2021-22 and 2022-23, Table 10 | Rule read; actual expiry dates read (note 30-Aug-2022) | 2026-09-16 | VERIFIED | Retrieve MCX 2022 holiday list to document why August expired on the 30th |
| `mcx_al_dpl_*` (daily price limits) | 4% → 6% → 9% | Circulars above; SEBI circular 27-Sep-2022 (via MCX/TRD/556/2022) | Slabs read; SEBI change dated after the window | 2026-09-16 | VERIFIED | — |
| `mcx_al_delivery_centres` | Raipur + additional centres | Circulars above; MCXCCL warehouse circulars Jan–Feb 2022 (titles) | Raipur primary in both; additional centres expand from Thane (Jun-2021) to Thane/NCR/Chennai/Kolkata (Oct-2022) | 2026-09-16 | PARTIAL | Pin the first contract month with NCR/Chennai/Kolkata delivery from the MCXCCL circular texts |
| MCX Aluminium price level (`mcx_domestic_premium_inr_kg`, market_proxy.yaml — not owned here) | 0.0 ₹/kg | Third-party MCX mirror (market-data agent) | Not checked by this agent | — | PARTIAL (per owner) | Owner's step: compare 5 window-date closes with MCX bhavcopy |
| USD/INR forward premium (`fwd_premium_3m_pa` in fx_rates_daily.csv — not owned here) | CIP proxy | RBI Bulletin "Forward premia of US$" table / FBIL | Not retrieved — one search did not surface the 2022 table | — | PENDING | Read RBI Monthly Bulletin 2022 Current Statistics (1-, 3-, 6-month forward premia, % p.a.) for Mar–Sep 2022 and compare with the panel's `fwd_premium_3m_pa` |
| LME Cash–3M spread (lme_daily.csv — DIRECT per CONTRACTS §4.1, not owned here) | daily series | LME official prices republished by Westmetall | Window statistics computed from the panel: mean −11.9 $/t (contango), range −42 to +35 $/t, monthly means −5.1 (Mar), −19.5 (Apr), −28.4 (May), −22.1 (Jun), −6.4 (Jul), +7.2 (Aug). Not cross-checked against LME's own archive (login-gated) | 2026-09-16 | PARTIAL | Spot-check 3 dates (07-Mar, 16-Jun, 31-Aug-2022) against an LME/Reuters/Fastmarkets official-price print |

## B. Other DIRECT parameters (this register)

| Parameter | Value used | Authoritative source | What was checked | Date checked | Status | Next step |
|---|---|---|---|---|---|---|
| `bcd_primary_al_hs7601` | 0.075 | Customs Tariff First Schedule 7601; Notif. 50/2017 (no concession) | No 7601 concession in 50/2017 principal or 2018–23 Budget amendments; AlCircle Apr-2026 states HS 7601 at 8.25% (= 7.5% × 1.10) | 2026-09-16 | PARTIAL | Read chapter 76 of the First Schedule as amended by the Finance Act 2022 |
| `landing_charges_frac` | 0.0 | Notification 91/2017-Customs (N.T.), substituted Valuation Rule 10(2) | Text read: loading/unloading/handling to place of importation at actual; no deemed 1% | 2026-09-16 | VERIFIED | — |
| `customs_deemed_freight_frac_fob` | 0.20 | Same | First proviso read | 2026-09-16 | VERIFIED | — |
| `customs_deemed_insurance_frac_fob` | 0.01125 | Same | Third proviso read | 2026-09-16 | VERIFIED | — |
| `import_policy_hs7602` | Free + para 2.54 + NFMIMS | DGFT PN 46/2015-20 (14-Jan-2022); DGFT Notif. 61/2015-20 (31-Mar-2021) | PN 46 text via worldtradescanner and bizsolindia reproductions; NFMIMS via Taxscan / TaxTMI summaries | 2026-09-16 | PARTIAL | Fetch DGFT originals (dgft.gov.in public-notice and notification pages, JS portal) |
| `psic_required_safe_origin_designated_port` | false | DGFT PN 46/2015-20 | As above (six safe origins, ten ports incl. JNPT and Mundra, supplier certificate + portal-monitor checks) | 2026-09-16 | PARTIAL | As above |
| `psic_required_uae_origin` | true | DGFT PN 46/2015-20 | As above | 2026-09-16 | PARTIAL | As above |
| `nfmims_registration_required` | true | DGFT Notif. 61/2015-20; Policy Circular 42/2015-20 (27-Jul-2022) | Secondary summaries only; 7602 coverage not seen in the annexure | 2026-09-16 | PARTIAL | Read the notification annexure line list |
| `mcx_al_quote_unit`, `mcx_al_trading_hours`, `mcx_al_delivery_unit_mt`, `mcx_al_delivery_logic`, `mcx_al_delivery_period_margin_frac`, `mcx_al_final_settlement_rule`, `mcx_al_position_limit_client_mt` | see exchange.yaml | MCX/TRD/385/2021, MCX/TRD/617/2022, MCX/TRD/646/2021 | Annexure fields read in both circulars; trading-hours circular read | 2026-09-16 | VERIFIED | — |
| `mcx_alumini_traded_2022`, `mcx_alumini_lot_mt` | false; 1 MT | MCX/TRD/104/2023 (15-Feb-2023) | Launch circular read (w.e.f. 20-Feb-2023) | 2026-09-16 | VERIFIED | — |
| `mcx_basis_std_inr_kg` | 4.44 | MCX Aluminium Performance Review 2022-23 §4a | Table read (FY21-22: 4.37) | 2026-09-16 | VERIFIED | — |
| `lme_al_lot_t` | 25 t | LME Aluminium contract-specifications page | Current page read in browser | 2026-09-16 | PARTIAL | 2022 LME Rulebook / contract spec archive |
| `lme_pricing_reference`, `lme_official_publication_window_london` | Official Settlement = cash offer, 2nd Ring; 12:20–13:25 London (both fields) | LME "LME Official Prices explained" page | Current page re-read in a browser after review: its summary line says "12.30-13.25 London time", its timetable says established/published "12.20 - 13.25" — the page is internally inconsistent; both fields now quote the timetable | 2026-09-16 | PARTIAL | Benchmark Methodology - LME Official Prices PDF (2022 version) |
| `fx_hedge_regime`, `fx_hedge_no_documentation_limit_usd` | RBI A.P.(DIR) 29/2020; USD 10 mn | RBI A.P. (DIR Series) Circular No. 29, 07-Apr-2020 | Taxguru summary read (effective-date ambiguity: 01-Jun vs 01-Sep-2020) | 2026-09-16 | PARTIAL | Read the circular on rbi.org.in and any 2021–22 amendments |
| `lc_opening_fee_frac_per_month`, `lc_usance_fee_frac_per_month`, `import_bill_commission_frac` | 0.08%/month; 0.07%/month; 0.12% | SBI Forex Service Charges w.e.f. 01-Apr-2022 | PDF read (existing vs revised columns) | 2026-09-16 | VERIFIED (SBI card rate) | — |
| `trade_credit_aic_ceiling_spread_pa` | 0.03 | RBI ECB/TC direction amendment 08-Dec-2021 | Argus Partners summary read | 2026-09-16 | PARTIAL | RBI press release / circular text |
| `msme_max_payment_days` | 45 | MSMED Act 2006 s.15 | Section text read (Indian Kanoon) | 2026-09-16 | VERIFIED | — |
| `secondary_raw_material_cost_share` (now PROXY) | 0.825 (midpoint) | CRISIL Research, Sept 2021 (published by CMR) | Sentence read in cached PDF ("80-85% of the total cost"); the published range is DIRECT, the midpoint is a transformation, so the flag was downgraded to PROXY in review | 2026-09-16 | VERIFIED (range, as a published industry estimate) | — |
| `sbi_mclr_1y_pa` (new) | 7.00% → 7.70% Mar–Aug 2022 (step path) | SBI "MCLR Historical Data" table | 1Y column read from the cached page (`data/raw/rates/sbi_mclr_historical_data.html`); rows are dated the 15th of each month | 2026-09-16 | VERIFIED | Optional: SBI press releases for exact mid-month effective dates |
| `grade_falling_market_logic` (PROXY, listed because it asserts a verified pattern) | text | DGCIS TRADESTAT HS 76020010 unit values; USGS MIS Aluminum Table 7 | Both datasets downloaded and ratios computed | 2026-09-16 | VERIFIED (direction only) | — |

## C. Key PROXY parameters whose inputs were verified

| Parameter | Value used | Inputs checked | Status | Next step |
|---|---|---|---|---|
| `grade_factor_mix` (PROXY) | lag-2 DGCIS/LME path, Mar–Aug mean 0.806 | DGCIS HS 76020010 monthly value & quantity 2021–25 (Revised Final, 72 cached TRADESTAT pages); Westmetall LME 3M 2018–25 | VERIFIED (recomputed by `desk.data.fetch_price_evidence`, which fails on mismatch) | — |
| `grade_factor_zorba` / `_taint_tabor` / `_tense` (now ASSUMPTION = mix + differential) | CFR-India paths, Mar–Aug means 0.786 / 0.786 / 0.736 | Mix above + differentials −0.02 / −0.02 / −0.07 = medians over 51 dated BigMint prices in 23 cached AlCircle articles (2024–25), D−1 Westmetall 3M, attachment-adjusted; each quote's sentence asserted in code. The first version's three quotes (05-Mar-2024 article not re-found; LME figures not date-matched) and freight netting were replaced | PARTIAL | 2022 grade-specific CFR India assessments (Fastmarkets / BigMint archive) — would replace the cross-period ASSUMPTION differentials |
| `domestic_anchor_premium_inr_t` (ASSUMPTION) | −₹9,000/t (cash basis) | 15 dated BigMint ADC12 ex-Delhi prices 2023–25 (AlCircle, cached) vs duty-paid LME cash parity with ECB USD/INR (cached) | PENDING (no 2022 series) | 2022 ADC12 weekly series (BigMint archive / automaker settlement prices) vs MCX near-month |
| `customs_fx_markup_frac` | 0.011 | Customs side DIRECT (CBIC); market side ECB cross | PARTIAL | Recompute against the RBI reference rate if `data/manual/rbi_reference_rate.csv` is added |
| `lc_opening_fee_frac` | 0.0024 | SBI rate VERIFIED; 3-month validity assumed | PARTIAL | — |
| `lc_confirmation_fee_pa` | 0.005 | SBI's own confirmation card (other banks' LCs) | PARTIAL | A foreign confirming bank's 2022 price for Indian-bank LCs |

## D. Seed values corrected during verification

- `bcd_scrap_hs7602`: the seed note said "Budget 2021-22 cut BCD on aluminium scrap to 2.5%". Budget 2021-22 cut **copper**
  scrap (7404) to 2.5%; aluminium scrap was already 2.5% in the June-2017 effective-rate notification. The value was
  right, the provenance was wrong.
- `sws_rate_on_bcd`: value unchanged; the statute actually levies SWS on the aggregate of s.12 customs duties (BCD + AIDC
  where levied), with IGST/compensation cess exempted — equivalent to "on BCD" for 7602 because AIDC is nil.
