# Phase 0 assumptions log

ACADEMIC SIMULATION — not actual trades.

Rendered by `desk.data.dictionary` from `desk.config.params_frame()` (the YAML register in `config/params/`) — do not hand-edit; change the YAML and re-run `.venv/bin/python run_all.py --only P0`. Data retrieved 2026-09-16 (cached under data/raw/; rebuilt offline with DESK_OFFLINE=1).

Flags: **DIRECT** = observed from a named public source; **PROXY** = real observable standing in or a transformation of real data; **ASSUMPTION** = judgement with justification. Verify status (first word of each `verify` field): **VERIFIED** = primary/official source read for the 2022 value; **PARTIAL** = supported with a named gap; **PENDING** = not yet verified (the text gives the next step); **N/A** = assumption with nothing to verify against. Statuses are as recorded by the Phase 0 researchers; details in `docs/verification_log.md`.

## Summary

| YAML file | Owner | Params | DIRECT | PROXY | ASSUMPTION | VERIFIED | PARTIAL | PENDING | N/A |
|---|---|---|---|---|---|---|---|---|---|
| `commercial.yaml` | P0 regulatory/contract research | 24 | 5 | 4 | 15 | 6 | 3 | 4 | 11 |
| `exchange.yaml` | P0 regulatory/contract research | 32 | 26 | 1 | 5 | 20 | 7 | 2 | 3 |
| `logistics.yaml` | P0 freight/logistics | 32 | 3 | 1 | 28 | 3 | 1 | 26 | 2 |
| `market_proxy.yaml` | P0 market-data | 1 | 0 | 1 | 0 | 0 | 1 | 0 | 0 |
| `parity.yaml` | P1 parity | 15 | 0 | 0 | 15 | 0 | 0 | 1 | 14 |
| `rates.yaml` | P0 market-data | 7 | 3 | 2 | 2 | 5 | 0 | 1 | 1 |
| `regulatory.yaml` | P0 regulatory/contract research | 22 | 14 | 2 | 6 | 9 | 6 | 2 | 5 |
| `risk.yaml` | P4/P5 risk | 53 | 0 | 0 | 53 | 0 | 0 | 3 | 50 |
| `risk_credit.yaml` | unassigned | 21 | 0 | 0 | 21 | 0 | 0 | 0 | 21 |
| `scrap_grades.yaml` | P0 regulatory/contract research | 25 | 0 | 5 | 20 | 4 | 6 | 7 | 8 |
| **Total** |  | 232 | 51 | 16 | 165 | 47 | 24 | 46 | 115 |

## Open items: PENDING (46)

Nothing below may be presented as checked. Each row's last column is the recorded next step.

| Key | File | Flag | Value used | Next step |
|---|---|---|---|---|
| **`conversion_cost_inr_t`** | commercial.yaml | ASSUMPTION | 12000 | no 2022 Indian secondary-smelter cost disclosure retrieved. Next step: cost-of-production note in a listed Indian secondary aluminium producer's 2022 annual report/DRHP (power + fuel + consumables per tonne). |
| **`domestic_anchor_premium_inr_t`** | commercial.yaml | ASSUMPTION | -9000 | no 2022 ADC12/LM6 India price series was retrievable (AlCircle/BigMint 2022 archives not found in public). Next step: weekly 2022 ADC12 ex-Delhi/Chennai from BigMint or an automaker's 2022 monthly alloy settlement prices, compared with MCX near-month. |
| **`usance_interest_spread_pa`** | commercial.yaml | ASSUMPTION | 0.015 | no 2022 buyer's-credit quote retrieved; check an Indian bank or buyer's-credit arranger's 2022 indicative pricing |
| **`lc_open_days_before_laycan_min`** | commercial.yaml | ASSUMPTION | 10 | no citable 2022 scrap SPA clause in the cached sources; the 10-15 day convention is trade practice reported in ISRI/BIR member guidance, not a document this project holds |
| **`mcx_al_margin_used_frac`** | exchange.yaml | ASSUMPTION | 0.1 | replace with MCXCCL daily SPAN aluminium margin % for Mar–Aug 2022 if the risk-parameter archive becomes retrievable |
| **`fx_forward_bank_margin_inr`** | exchange.yaml | ASSUMPTION | 0.1 | no 2022 bank rate card for corporate forward margins was retrieved; check RBI FX-Retail platform documentation / RBI speeches on retail FX spreads for an order of magnitude |
| **`container_payload_mt_20ft`** | logistics.yaml | ASSUMPTION | 25.0 | confirm typical Zorba / Taint-Tabor 20ft load weights from a Jebel Ali shipper's packing list or a BigMint/Fastmarkets methodology note |
| **`container_payload_mt_40ft`** | logistics.yaml | ASSUMPTION | 21.0 | the eCFR page redirected to a bot check when fetched; re-check 23 CFR 658.17 on ecfr.gov and a US scrap exporter's 40ft load weights (Recycling Today / ReMA) |
| **`container_payload_mt_20ft_zorba`** | logistics.yaml | ASSUMPTION | 26.0 | packing lists / bills of lading for Zorba 95/5 20ft shipments (review asked for grade-specific payloads) |
| **`container_payload_mt_20ft_taint_tabor`** | logistics.yaml | ASSUMPTION | 20.0 | packing lists for baled Taint/Tabor 20ft shipments |
| **`container_payload_mt_20ft_tense`** | logistics.yaml | ASSUMPTION | 25.0 | packing lists for Tense 20ft shipments |
| **`container_payload_mt_40ft_zorba`** | logistics.yaml | ASSUMPTION | 21.0 | as container_payload_mt_40ft |
| **`container_payload_mt_40ft_taint_tabor`** | logistics.yaml | ASSUMPTION | 21.0 | as container_payload_mt_40ft |
| **`container_payload_mt_40ft_tense`** | logistics.yaml | ASSUMPTION | 21.0 | as container_payload_mt_40ft |
| **`transit_days_jea_nsa`** | logistics.yaml | ASSUMPTION | 5 | pull a 2022 carrier schedule (e.g. Wayback copy of an MSC/Maersk/ESL Jebel Ali->Nhava Sheva point-to-point schedule) for port-to-port days |
| **`transit_days_usec_mun`** | logistics.yaml | ASSUMPTION | 40 | pull a 2022 carrier schedule (Wayback copy of a Hapag-Lloyd/MSC New York or Savannah -> Mundra routing) and record port-to-port days |
| **`clearance_delivery_days`** | logistics.yaml | ASSUMPTION | 10 | compare with CBIC National Time Release Study 2022 (average release time for sea cargo at JNCH Nhava Sheva and Mundra) and add inland trucking days |
| **`finance_days_jea_nsa`** | logistics.yaml | ASSUMPTION | 40 | reconcile with the payment terms P2 assigns in config/trades.yaml (LC sight vs usance; buyer advance vs 30d credit) |
| **`finance_days_usec_mun`** | logistics.yaml | ASSUMPTION | 73 | reconcile with the payment terms P2 assigns in config/trades.yaml (LC sight vs usance; buyer advance vs 30d credit) |
| **`typical_laycan_days`** | logistics.yaml | ASSUMPTION | 15 | check shipment-period wording in a published ISRI/ReMA or BIR model contract for containerised non-ferrous scrap |
| **`port_cf_charges_inr_t_nsa`** | logistics.yaml | ASSUMPTION | 1600 | retrieve 2022 Wayback copies of a carrier's India import THC/DO tariff and a JNPT CFS tariff; get a 2022 short-haul (~200 km) 20ft truck rate out of JNPT |
| **`port_cf_charges_inr_t_mun`** | logistics.yaml | ASSUMPTION | 2650 | retrieve 2022 Wayback copies of a carrier's Mundra import THC/DO tariff and an Adani Mundra CFS tariff; get a 2022 Mundra->Rajkot 40ft trailer rate |
| **`insurance_rate`** | logistics.yaml | ASSUMPTION | 0.001 | obtain an indicative 2022 marine cargo rate for metal scrap from an Indian insurer's published tariff guidance or a broker note |
| **`detention_free_days`** | logistics.yaml | ASSUMPTION | 14 | retrieve a 2022 Wayback copy of a carrier's India import detention tariff (standard free days) and a JNPT/Mundra CFS free-period schedule |
| **`demurrage_usd_per_box_day`** | logistics.yaml | ASSUMPTION | 35 | retrieve 2022 Wayback copies of a carrier's India import detention slabs (USD/day by box size) and a CFS ground-rent tariff (INR/day) |
| **`demurrage_slab1_days`** | logistics.yaml | ASSUMPTION | 5 | same evidence gap as demurrage_usd_per_box_day: retrieve a 2022 Wayback copy of a carrier's India import detention slab table (Maersk/MSC/CMA India local charges) |
| **`demurrage_slab2_days`** | logistics.yaml | ASSUMPTION | 5 | as demurrage_slab1_days |
| **`demurrage_usd_per_box_day_slab2`** | logistics.yaml | ASSUMPTION | 70 | as demurrage_slab1_days |
| **`demurrage_usd_per_box_day_slab3`** | logistics.yaml | ASSUMPTION | 105 | as demurrage_slab1_days |
| **`rejected_box_hold_days`** | logistics.yaml | ASSUMPTION | 45 | no 2022 case record or CBIC/AERB published timeline in the cached sources; the 30-60 day cycle is desk judgement for a referral that involves a second regulator |
| **`rejected_box_reexport_cost_usd_per_box`** | logistics.yaml | ASSUMPTION | 3000 | retrieve a 2022 carrier export THC tariff at Mundra and any published AERB/Customs re-export procedure cost; the component magnitudes are desk estimates, not quotes |
| **`freight_jea_nsa_usd_box_ref`** | logistics.yaml | ASSUMPTION | 600 | no citable 2022 Jebel Ali->Nhava Sheva quote found (Platts WCI India-Middle East assessments and Xeneta are paywalled; S&P pages return 403). Next step: a 2022 Wayback copy of a Freightos/SeaRates/iContainers JEA->INNSA rate page, or a BigMint/Fastmarkets 2022 UAE-origin scrap CFR vs FOB spread |
| **`lme_cash_prompt_bdays`** | parity.yaml | ASSUMPTION | 2 | stated from the standard LME convention, not re-read from the LME contract specification in Phase 1. Next step: LME Aluminium contract specification page (prompt date structure). |
| **`wc_rate_spread_over_mclr_pa`** | rates.yaml | ASSUMPTION | 0.025 | no 2022 sanction letter or published spread for a comparable borrower retrieved. Next step: a listed metals trader's FY2022-23 annual report (borrowing-cost note) to back out its working-capital rate over MCLR. |
| **`psic_cost_usd_per_box`** | regulatory.yaml | ASSUMPTION | 40.0 | obtain an inspection-agency (PSIA) 2022 quote or published fee for radiation + explosives inspection of a 20ft scrap container at Jebel Ali |
| **`nfmims_min_lead_days`** | regulatory.yaml | PROXY | 5 | confirm 60/5-day window and 75-day validity in the DGFT notification text |
| **`mc_buyer_default_recovery_frac`** | risk.yaml | ASSUMPTION | 0.25 | compare with published realisation rates for operational creditors in Indian insolvency resolutions (IBBI quarterly newsletter) |
| **`liq_fb_wc_limit_inr`** | risk.yaml | ASSUMPTION | 1000000000.0 | no 2022 sanction letter for a comparable importer was retrieved. Next step: a listed Indian non-ferrous metals trader's FY2022-23 annual report (sanctioned fund-based working-capital limits against turnover). |
| **`liq_nfb_lc_limit_inr`** | risk.yaml | ASSUMPTION | 1000000000.0 | as liq_fb_wc_limit_inr |
| **`grade_factor_mix_pit`** | scrap_grades.yaml | ASSUMPTION | linear path, 10 points: 2021-12-15: 0.789; 2022-01-15: 0.759; 2022-... | the ~1-month DGCIS release lag behind this construction is assumed, not verified. Next step: check TRADESTAT/DGCIS release calendar for 8-digit monthly import data in 2022. |
| **`contamination_frac_zorba`** | scrap_grades.yaml | ASSUMPTION | 0.06 | the 95/5 composition is trade naming, not an ISRI definition; confirm from a BigMint/Fastmarkets Zorba methodology note or a packing-list assay |
| **`metal_yield_frac_zorba`** | scrap_grades.yaml | ASSUMPTION | 0.93 | no published Indian smelter yield for Zorba retrieved; check a BigMint/Fastmarkets Zorba methodology note or an Indian secondary smelter DRHP |
| **`heavies_frac_zorba`** | scrap_grades.yaml | ASSUMPTION | 0.05 | as contamination_frac_zorba |
| **`heavies_net_value_frac_of_lme_al`** | scrap_grades.yaml | ASSUMPTION | 0.8 | no public 2022 or 2024 India price for Zorba heavies / 'Zebra' was retrieved. Next step: a BigMint or Fastmarkets heavy non-ferrous shred price series, or a US ReMA 'Zebra' quote converted to CFR India. |
| **`metal_yield_frac_taint_tabor`** | scrap_grades.yaml | ASSUMPTION | 0.92 | confirm melt-loss range with an Indian secondary smelter disclosure or an aluminium recycling engineering reference |
| **`metal_yield_frac_tense`** | scrap_grades.yaml | ASSUMPTION | 0.94 | as metal_yield_frac_taint_tabor |

## DIRECT parameters not fully verified (13)

Labelled DIRECT because a named source states the value, but verification is incomplete — re-check before quoting them as verified.

| Key | File | Status | Gap / next step |
|---|---|---|---|
| `trade_credit_aic_ceiling_spread_pa` | commercial.yaml | PARTIAL | law-firm summary read; RBI circular text not fetched. Next step: read the RBI press release/circular of 08-Dec-2021 on rbi.org.in. |
| `mcx_al_delivery_centres` | exchange.yaml | PARTIAL | the exact contract month from which NCR/Chennai/Kolkata became deliverable was not pinned down |
| `lme_al_lot_t` | exchange.yaml | PARTIAL | current page, not a 2022-dated rulebook; the 25 t lot and USD/t quotation are long-standing |
| `lme_pricing_reference` | exchange.yaml | PARTIAL | current methodology page (re-read in a browser 2026-09-16 after review flagged an inconsistency); the official-price definition predates 2022 but a 2022-dated benchmark methodology PDF was not retrieved |
| `lme_official_publication_window_london` | exchange.yaml | PARTIAL | current timetable, not a 2022-dated version; the same page's summary line gives 'When is it published? 12.30-13.25 London time', so the page is internally inconsistent by 10 minutes. Next step: the Benchmark Methodology - LME Official Prices PDF linked from that page. |
| `fx_hedge_regime` | exchange.yaml | PARTIAL | secondary summary read (it states effective 01-Jun-2020; other summaries give 01-Sep-2020 after a COVID deferral); RBI original not fetched. Next step: read the circular on rbi.org.in and confirm it was unchanged through 2022. |
| `fx_hedge_no_documentation_limit_usd` | exchange.yaml | PARTIAL | secondary summary; RBI original not fetched |
| `insured_value_uplift` | logistics.yaml | PARTIAL | 2026-09-16 — wording confirmed via secondary reproduction (tradefinance.training 'UCP comparison Part 4'); the ICC publication itself is paywalled |
| `bcd_primary_al_hs7601` | regulatory.yaml | PARTIAL | 2026-09-16 — chain of evidence is consistent but the 2022 First Schedule page for chapter 76 itself was not retrieved. Next step: download the Customs Tariff chapter 76 as amended by the Finance Act 2022 (CBIC Tax Information Portal > Acts > Customs Tariff Act) and read tariff items 7601 10 10–7601 20 90. |
| `import_policy_hs7602` | regulatory.yaml | PARTIAL | 2026-09-16 — PN 46 content read via two republishers, not the DGFT PDF itself; NFMIMS coverage of 7602 read only from secondary pages. Next step: fetch the DGFT PDFs from https://www.dgft.gov.in/CP/?opt=public-notice and ?opt=notification (JS portal; use a browser) and read the ITC(HS) policy-condition text for 7602. |
| `psic_required_safe_origin_designated_port` | regulatory.yaml | PARTIAL | republisher text read (worldtradescanner, bizsolindia); DGFT original not fetched |
| `psic_required_uae_origin` | regulatory.yaml | PARTIAL | republisher text read; DGFT original not fetched |
| `nfmims_registration_required` | regulatory.yaml | PARTIAL | secondary sources only; whether 7602 00 10/90 are in the 43 covered chapter-76 lines is not confirmed from the DGFT annexure. Next step: read the annexure of Notification 61/2015-2020 on dgft.gov.in. |

## PARTIAL items (24)

| Key | File | Flag | Gap / next step |
|---|---|---|---|
| `lc_opening_fee_frac` | commercial.yaml | PROXY | rate VERIFIED from SBI card; 3-month validity is an assumption |
| `lc_confirmation_fee_pa` | commercial.yaml | PROXY | this is SBI's price for confirming OTHER banks' LCs; the fee a UAE/US bank charges to confirm an Indian bank's LC was not retrieved |
| `trade_credit_aic_ceiling_spread_pa` | commercial.yaml | DIRECT | law-firm summary read; RBI circular text not fetched. Next step: read the RBI press release/circular of 08-Dec-2021 on rbi.org.in. |
| `mcx_al_additional_margin_frac` | exchange.yaml | PROXY | absence inferred from circular titles; an aluminium clause inside a multi-commodity circular would be missed. Next step: open every MCXCCL 'Imposition of Additional Margin' circular Feb–Aug 2022. |
| `mcx_al_delivery_centres` | exchange.yaml | DIRECT | the exact contract month from which NCR/Chennai/Kolkata became deliverable was not pinned down |
| `lme_al_lot_t` | exchange.yaml | DIRECT | current page, not a 2022-dated rulebook; the 25 t lot and USD/t quotation are long-standing |
| `lme_pricing_reference` | exchange.yaml | DIRECT | current methodology page (re-read in a browser 2026-09-16 after review flagged an inconsistency); the official-price definition predates 2022 but a 2022-dated benchmark methodology PDF was not retrieved |
| `lme_official_publication_window_london` | exchange.yaml | DIRECT | current timetable, not a 2022-dated version; the same page's summary line gives 'When is it published? 12.30-13.25 London time', so the page is internally inconsistent by 10 minutes. Next step: the Benchmark Methodology - LME Official Prices PDF linked from that page. |
| `fx_hedge_regime` | exchange.yaml | DIRECT | secondary summary read (it states effective 01-Jun-2020; other summaries give 01-Sep-2020 after a COVID deferral); RBI original not fetched. Next step: read the circular on rbi.org.in and confirm it was unchanged through 2022. |
| `fx_hedge_no_documentation_limit_usd` | exchange.yaml | DIRECT | secondary summary; RBI original not fetched |
| `insured_value_uplift` | logistics.yaml | DIRECT | 2026-09-16 — wording confirmed via secondary reproduction (tradefinance.training 'UCP comparison Part 4'); the ICC publication itself is paywalled |
| `mcx_domestic_premium_inr_kg` | market_proxy.yaml | PROXY | mirror data could not be checked against MCX's own bhavcopy (mcxindia.com returned Akamai HTTP 403 to every request on 2026-09-16). Next step: download MCX bhavcopy for 5 window dates (e.g. 07-Mar, 13-Apr, 16-Jun, 14-Jul, 31-Aug-2022) from a browser, compare ALUMINIUM near-month closes with the mirror, then recompute. |
| `bcd_primary_al_hs7601` | regulatory.yaml | DIRECT | 2026-09-16 — chain of evidence is consistent but the 2022 First Schedule page for chapter 76 itself was not retrieved. Next step: download the Customs Tariff chapter 76 as amended by the Finance Act 2022 (CBIC Tax Information Portal > Acts > Customs Tariff Act) and read tariff items 7601 10 10–7601 20 90. |
| `customs_fx_markup_frac` | regulatory.yaml | PROXY | the customs side is DIRECT; the market side is the ECB-cross PROXY, not the RBI reference rate. |
| `import_policy_hs7602` | regulatory.yaml | DIRECT | 2026-09-16 — PN 46 content read via two republishers, not the DGFT PDF itself; NFMIMS coverage of 7602 read only from secondary pages. Next step: fetch the DGFT PDFs from https://www.dgft.gov.in/CP/?opt=public-notice and ?opt=notification (JS portal; use a browser) and read the ITC(HS) policy-condition text for 7602. |
| `psic_required_safe_origin_designated_port` | regulatory.yaml | DIRECT | republisher text read (worldtradescanner, bizsolindia); DGFT original not fetched |
| `psic_required_uae_origin` | regulatory.yaml | DIRECT | republisher text read; DGFT original not fetched |
| `nfmims_registration_required` | regulatory.yaml | DIRECT | secondary sources only; whether 7602 00 10/90 are in the 43 covered chapter-76 lines is not confirmed from the DGFT annexure. Next step: read the annexure of Notification 61/2015-2020 on dgft.gov.in. |
| `grade_factor_diff_zorba` | scrap_grades.yaml | ASSUMPTION | 2026-09-16 — every quote traced to its cached AlCircle sentence and date-matched Westmetall 3M; no 2022 Zorba quote exists in public. Next step: 2022 Zorba 95/5 CFR India assessments (BigMint/Fastmarkets archive) to replace the cross-period assumption. |
| `grade_factor_diff_taint_tabor` | scrap_grades.yaml | ASSUMPTION | 2026-09-16 — quotes traced to cached sentences; small sample, and the Dec-2025 HRB prints cannot be scored yet (lag-2 unit value for Feb-2026 not used). Next step: 2022 Taint/Tabor CIF India quotes. |
| `grade_factor_diff_tense` | scrap_grades.yaml | ASSUMPTION | 2026-09-16 — quotes traced to cached sentences; where an article omits the benchmark's attachment label the series label from other weeks is applied (attach_source=SERIES in the evidence table). Next step: 2022 Tense CFR India assessments. |
| `grade_factor_zorba` | scrap_grades.yaml | ASSUMPTION | 2026-09-16 — the mix shape is VERIFIED official data; the level depends on a 2024–25 differential applied to 2022. Next step: as grade_factor_diff_zorba. |
| `grade_factor_taint_tabor` | scrap_grades.yaml | ASSUMPTION | 2026-09-16 — as grade_factor_zorba. CONTRADICTS the MASTER_SPEC guide of 88–92% for Taint/Tabor: no retrieved evidence supports it. |
| `grade_factor_tense` | scrap_grades.yaml | ASSUMPTION | 2026-09-16 — as grade_factor_zorba. |

## Pipeline assumptions that are not YAML parameters

- Panel calendar = LME trading days (Westmetall). MCX holidays are not modelled: MCX proxy prices sit on the LME calendar and proxy expiries use the LME calendar (CONTRACTS §3).
- FX/rates carried forward onto LME days without an ECB fixing, at most 5 business days (longer gaps raise).
- Weekly freight aligned point-in-time: each LME day takes the latest week already assessed (Thursday = week_end − 1) on or before it (`freight_filled` on carried days); no freight before 2020-12-24. The weekly levels themselves are hindsight-calibrated (CONTRACTS §4.3).
- Grade factors are a CFR-India basis shared by both lanes (CONTRACTS §5 CFR parity); their lag-2 DGCIS mix is a hindsight reconstruction (point-in-time and lag-1/lag-3 paths are sensitivities in scrap_grades.yaml).
- MCX proxy: duty-paid LME cash import parity, futures carried at `inr_rate_3m_pa` to the proxy expiry (CONTRACTS §4.5).
- USD/INR = ECB cross (PROXY for the RBI reference rate); forwards by covered interest parity with the 3M rates for both tenors.

## `config/params/commercial.yaml`

Owner: P0 regulatory/contract research · 24 parameters · DIRECT 5, PROXY 4, ASSUMPTION 15.

| Key | Value | Unit | Flag | Verify |
|---|---|---|---|---|
| `conversion_cost_inr_t` | 12000 | inr_per_mt_ingot | ASSUMPTION | **PENDING** |
| `conversion_cost_sensitivity_inr_t_ingot` | [8000, 12000, 18000, 30000] | inr_per_mt_ingot | ASSUMPTION | N/A |
| `domestic_anchor_premium_inr_t` | -9000 | inr_per_mt | ASSUMPTION | **PENDING** |
| `domestic_anchor_premium_sensitivity_inr_t` | [-55000, -52000, -9000, 13000] | inr_per_mt | ASSUMPTION | N/A |
| `domestic_anchor_passthrough_frac` | 0.15 | frac | PROXY | VERIFIED |
| `domestic_anchor_trailing_bdays` | 120 | lme_trading_days | ASSUMPTION | N/A |
| `domestic_anchor_premium_trailing_inr_t` | -2000 | inr_per_mt | ASSUMPTION | N/A |
| `margin_threshold_inr_t` | 5000 | inr_per_mt_scrap | ASSUMPTION | N/A |
| `lc_opening_fee_frac_per_month` | 0.0008 | frac_of_lc_value_per_month | DIRECT | VERIFIED |
| `lc_opening_fee_frac` | 0.0024 | frac_of_lc_value | PROXY | PARTIAL |
| `lc_usance_fee_frac_per_month` | 0.0007 | frac_of_bill_value_per_month | DIRECT | VERIFIED |
| `import_bill_commission_frac` | 0.0012 | frac_of_bill_value | DIRECT | VERIFIED |
| `lc_confirmation_fee_pa` | 0.005 | rate_pa | PROXY | PARTIAL |
| `usance_interest_spread_pa` | 0.015 | rate_pa_over_usd_benchmark | ASSUMPTION | **PENDING** |
| `trade_credit_aic_ceiling_spread_pa` | 0.03 | rate_pa_over_benchmark | DIRECT | PARTIAL |
| `standard_moisture_franchise_frac` | 0.01 | frac_of_gross_weight | ASSUMPTION | N/A |
| `rejection_penalty_schedule` | [{"trigger": "moisture above franchise", "measure": "joint survey, ... | list | ASSUMPTION | N/A |
| `radioactivity_clause` | Seller warrants the material is free of radioactive substances abov... | text | ASSUMPTION | N/A |
| `domestic_buyer_credit_days` | 30 | days | ASSUMPTION | N/A |
| `msme_max_payment_days` | 45 | days | DIRECT | VERIFIED |
| `secondary_raw_material_cost_share` | 0.825 | frac_of_total_cost | PROXY | VERIFIED |
| `max_domestic_credit_days` | 45 | days | ASSUMPTION | N/A |
| `lc_open_days_before_laycan_min` | 10 | days | ASSUMPTION | **PENDING** |
| `buyer_advance_limit_multiple_of_credit_limit` | 1.0 | multiple_of_credit_limit_inr | ASSUMPTION | N/A |

### `conversion_cost_inr_t`  — **PENDING**

- **Value:** 12000
- **Unit:** inr_per_mt_ingot · **Flag:** ASSUMPTION
- **Source:** Desk toll-conversion charge per tonne of secondary alloy INGOT produced (fuel, power, flux/salt, alloying top-up, labour, dross handling, overheads and the converter's margin), triangulated from BigMint/AlCircle 24-Feb-2024 (https://www.alcircle.com/news/raw-material-costs-propel-india-s-aluminium-adc12-prices-upward-w-o-w-108017): ADC12 INR 204,000/t vs domestic Tense INR 172,500/t ex-Delhi; 1 t of ingot needs ~1/0.90 = 1.11 t of Tense (INR 191,700), leaving INR ~12,300/t of ingot; the Dec-2024 non-OEM / OEM prints (INR 201,000 / 209,000) give ~INR 9,000–17,000/t of ingot. Range INR 8,000–18,000 per t of INGOT.
- **Verify:** **PENDING** — no 2022 Indian secondary-smelter cost disclosure retrieved. Next step: cost-of-production note in a listed Indian secondary aluminium producer's 2022 annual report/DRHP (power + fuel + consumables per tonne).
- **Justification:** UNIT FIX (review): the evidence is per tonne of ingot, so the unit is inr_per_mt_ingot and CONTRACTS §5 converts it per MT of scrap as conversion_inr_t = conversion_cost_inr_t × recovery_frac_g (e.g. INR 10,760/t of Tense scrap at 0.897 recovery; lower for Zorba, which yields less ingot per tonne). Uniform across grades by design: (i) Zorba's heavies separation cost is netted inside heavies_net_value_frac_of_lme_al; (ii) Taint/Tabor's silicon top-up to ADC12 chemistry costs roughly nothing net, because silicon 553 (~USD 2,030/t CIF Mundra in the same 24-Feb-2024 article) was priced below the alloy it becomes part of; (iii) melt-shop differences are inside the 8–18k range. Cross-check with [CRISIL] (Sept 2021): scrap = 80–85% of total cost incl. taxes and duties, i.e. a 15–20% non-scrap cost base (~INR 30–40k/t of ingot, part non-cash: depreciation, finance, selling) — a broader base than a toll charge; P1 runs it as the upper sensitivity (conversion_cost_sensitivity_inr_t_ingot).

### `conversion_cost_sensitivity_inr_t_ingot`

- **Value:** [8000, 12000, 18000, 30000]
- **Unit:** inr_per_mt_ingot · **Flag:** ASSUMPTION
- **Source:** conversion_cost_inr_t range (8–18k, 2024 spreads) plus a CRISIL-consistent upper case (~15% non-scrap cost on ~INR 200k/t ingot)
- **Verify:** **N/A** — sensitivity grid
- **Justification:** P1 must report window_open for each value (named sensitivity).

### `domestic_anchor_premium_inr_t`  — **PENDING**

- **Value:** -9000
- **Unit:** inr_per_mt · **Flag:** ASSUMPTION
- **Source:** Median of 15 dated BigMint ADC12 ex-Delhi prices (01-Dec-2023 → 11-Dec-2025, republished by AlCircle; OEM-approved prints moved to a non-OEM basis by the INR 8,000 OEM − non-OEM gap in the 05/11-Dec-2024 articles) minus duty-paid LME CASH parity on the day before publication: LME cash (Westmetall) × ECB USD/INR × (1 + 7.5% × 1.10). Median −8,955 → −9,000; mean −16,422; range −52,068 … +12,861 (data/interim/price_evidence/adc12_vs_duty_paid_parity.csv, exact sentences in desk/data/fetch_price_evidence.py).
- **Verify:** **PENDING** — no 2022 ADC12/LM6 India price series was retrievable (AlCircle/BigMint 2022 archives not found in public). Next step: weekly 2022 ADC12 ex-Delhi/Chennai from BigMint or an automaker's 2022 monthly alloy settlement prices, compared with MCX near-month.
- **Justification:** REVIEW FIXES. (1) Basis: recalibrated against duty-paid LME CASH parity — the basis of the panel's MCX proxy that CONTRACTS §5 adds this premium to — instead of 3M (cash–3M basis in the sample: median INR ~4,100/t; M1 carry adds a further 0–1,300/t, not modelled). (2) Evidence: the previous −18,000 was the mean of two points computed with the articles' own LME figures (the 24-Feb-2024 point used 3M $2,247; Westmetall 3M on 23-Feb-2024 was $2,197). (3) Regime dependence is strong: correlation of the premium with parity −0.93; OLS short-run pass-through of parity into ADC12 = 0.15 (domestic_anchor_passthrough_frac). Premiums were +5k…+13k at parity ~191–205k (H1-2024) and −34k…−52k at parity ~235–276k (late 2024–25). The 2022 window's parity ran ~200–330k, so a constant premium overstates the anchor at the March spike and understates it in July–August. P1 must publish window_open as a band over domestic_anchor_premium_sensitivity_inr_t and under the sticky variant (domestic_anchor_trailing_bdays), not as a single flag. (4) CRISIL (Sept 2021, cached CMR PDF) says 'Secondary aluminium continues to be 25-30% cheaper than primary aluminium' with no date, product or price basis; against the dated 2023–25 ADC12 prints (−20% … +7% of parity) it reads as a cost or low-grade-product statement and is kept only as the low-end sensitivity (−55,000 ≈ 25% of the window-mean MCX proxy of INR ~222k/t), not rejected and not used as the base.

### `domestic_anchor_premium_sensitivity_inr_t`

- **Value:** [-55000, -52000, -9000, 13000]
- **Unit:** inr_per_mt · **Flag:** ASSUMPTION
- **Source:** CRISIL-consistent low case (−25% of ~INR 222k), evidence minimum (−52,068), base median, evidence maximum (+12,861), rounded
- **Verify:** **N/A** — sensitivity grid built from the domestic_anchor_premium_inr_t evidence
- **Justification:** P1 publishes the parity window for each value.

### `domestic_anchor_passthrough_frac`

- **Value:** 0.15
- **Unit:** frac · **Flag:** PROXY
- **Source:** OLS slope of ADC12 (non-OEM basis) on duty-paid LME cash parity over the 15 dated 2023–25 observations (desk.data.fetch_price_evidence; intercept INR ~173k/t)
- **Verify:** **VERIFIED** — 2026-09-16 as a statistic of the cached evidence (n=15; one regime, not 2022)
- **Justification:** Evidence of stickiness only: within 2023–25 a INR 1 move in import parity moved secondary alloy ingot by ~INR 0.15. Do not extrapolate the intercept to 2022 (it reflects 2024 scrap costs).

### `domestic_anchor_trailing_bdays`

- **Value:** 120
- **Unit:** lme_trading_days · **Flag:** ASSUMPTION
- **Source:** Sticky-anchor sensitivity: anchor = mean duty-paid cash parity (= MCX spot proxy) over the previous 120 LME days + domestic_anchor_premium_trailing_inr_t
- **Verify:** **N/A** — sensitivity design, not a fit optimum: on the 2023–25 evidence the premium's std falls steadily with window length (INR 24.0k against spot parity, 18.3k at 90, 17.5k at 120, 15.5k at 250 days; data/interim/price_evidence/adc12_trailing_parity_dispersion.csv); 120 LME days (~6 months) is a judgement for scrap inventory plus contract lags
- **Justification:** Economic reading: alloy ingot is priced cost-plus off scrap bought weeks to months earlier, so it tracks a trailing average of import parity. In 2022 this variant shuts the March spike and opens the July–August trough — the opposite of the constant-premium base.

### `domestic_anchor_premium_trailing_inr_t`

- **Value:** -2000
- **Unit:** inr_per_mt · **Flag:** ASSUMPTION
- **Source:** Median of ADC12 (non-OEM basis) minus the 120-LME-day trailing mean of duty-paid cash parity over the same 15 observations: −2,071 → −2,000
- **Verify:** **N/A** — sensitivity; same evidence as domestic_anchor_premium_inr_t
- **Justification:** Used only with domestic_anchor_trailing_bdays.

### `margin_threshold_inr_t`

- **Value:** 5000
- **Unit:** inr_per_mt_scrap · **Flag:** ASSUMPTION
- **Source:** Desk hurdle: minimum expected net margin per MT of scrap before a trade is allowed (Table 3 row 1.4)
- **Verify:** **N/A** — risk-policy assumption
- **Justification:** ≈ 2% of a ~INR 2.3 lakh/MT landed cost. Sized to cover: expected quality/weight claims under the SPA penalty schedule (~0.5–1% of value ≈ INR 1,200–2,300), residual MCX hedge noise over a ~6-week cash cycle (the anchor premium is unhedgeable, see domestic_anchor_premium_inr_t), a few days' demurrage on 25 MT boxes, and leaves ~INR 1,500–2,000 as return on risk capital. Opening a window below this is 'picking up pennies in front of a steamroller' given the LME daily moves of 4–12% seen in Mar-2022.

### `lc_opening_fee_frac_per_month`

- **Value:** 0.0008
- **Unit:** frac_of_lc_value_per_month · **Flag:** DIRECT
- **Source:** [SBI22] Import LC / Revolving LC issuance: revised charge '0.08% per month and part thereof. Minimum Charges Rs. 2,000/-' w.e.f. 01-Apr-2022 (was 0.18% for the first 3 months + 0.08% per additional month)
- **Verify:** **VERIFIED** — 2026-09-16 as SBI's published card rate for the window; a corporate's negotiated rate may be lower
- **Justification:** Charged on LC value for the validity period (shipment window + presentation period).

### `lc_opening_fee_frac`

- **Value:** 0.0024
- **Unit:** frac_of_lc_value · **Flag:** PROXY
- **Source:** [SBI22] 0.08% per month × 3 months' LC validity (desk assumption for a 15-day laycan + sailing + 21-day presentation)
- **Verify:** **PARTIAL** — rate VERIFIED from SBI card; 3-month validity is an assumption
- **Justification:** ≈ USD 5.5/MT on a USD 2,300/MT cargo. Revolving LCs for a supply programme are charged the same per reinstatement.

### `lc_usance_fee_frac_per_month`

- **Value:** 0.0007
- **Unit:** frac_of_bill_value_per_month · **Flag:** DIRECT
- **Source:** [SBI22] Import LC 'Usance Charges': revised '0.07% per month and part thereof', minimum Rs 2,000, w.e.f. 01-Apr-2022
- **Verify:** **VERIFIED** — 2026-09-16 (SBI card rate)
- **Justification:** Commitment charge for the usance period of a usance LC, separate from the interest cost of the credit itself.

### `import_bill_commission_frac`

- **Value:** 0.0012
- **Unit:** frac_of_bill_value · **Flag:** DIRECT
- **Source:** [SBI22] 'Commission on Import Bills Collection (Under LCs or Without LC)': revised 0.12% of bill amount, minimum Rs 500 (+0.10% in lieu of exchange if FX not converted with SBI), w.e.f. 01-Apr-2022
- **Verify:** **VERIFIED** — 2026-09-16 (SBI card rate)
- **Justification:** Charged at bill retirement.

### `lc_confirmation_fee_pa`

- **Value:** 0.005
- **Unit:** rate_pa · **Flag:** PROXY
- **Source:** [SBI22] export-side 'LC Confirmation Charges based on the rating of LC issuing bank': AAA–AA 0.25% p.a.; A–Baa3/BBB 0.50% p.a.; Ba1–B3/BB/B and unrated 0.75% p.a.
- **Verify:** **PARTIAL** — this is SBI's price for confirming OTHER banks' LCs; the fee a UAE/US bank charges to confirm an Indian bank's LC was not retrieved
- **Justification:** Proxy uses the BBB band (Indian banks' sovereign-capped ratings). US yards selling Taint/Tabor often ask for confirmation; Gulf traders frequently accept an unconfirmed LC from a top Indian bank — so apply on USEC_MUN, optional on JEA_NSA.

### `usance_interest_spread_pa`  — **PENDING**

- **Value:** 0.015
- **Unit:** rate_pa_over_usd_benchmark · **Flag:** ASSUMPTION
- **Source:** Desk assumption for supplier's/buyer's credit pricing on a 60–90 day USD usance, over 6-month SOFR-type benchmark; bounded by trade_credit_aic_ceiling_spread_pa
- **Verify:** **PENDING** — no 2022 buyer's-credit quote retrieved; check an Indian bank or buyer's-credit arranger's 2022 indicative pricing
- **Justification:** Usance cost in USD = (benchmark + spread) × days/360 on the bill value; compare with the INR working-capital line (wc_rate_inr_pa, rates.yaml) plus forward premium to choose sight vs usance.

### `trade_credit_aic_ceiling_spread_pa`

- **Value:** 0.03
- **Unit:** rate_pa_over_benchmark · **Flag:** DIRECT
- **Source:** RBI ECB/Trade Credit master direction as amended 08-Dec-2021: LIBOR replaced by 'any widely accepted interbank rate or alternative reference rate (ARR) of 6-month tenor'; all-in-cost ceiling for trade credits raised to benchmark + 300 bps (350 bps for LIBOR-transition cases), as summarised at https://www.argus-p.com/updates/updates/rbi-changes-to-all-in-cost-benchmark-and-ceiling-for-foreign-currency-ecbs-and-trade-credits/
- **Verify:** **PARTIAL** — law-firm summary read; RBI circular text not fetched. Next step: read the RBI press release/circular of 08-Dec-2021 on rbi.org.in.
- **Justification:** Regulatory cap on usance/buyer's credit all-in cost for the window; desk pricing sits well inside it.

### `standard_moisture_franchise_frac`

- **Value:** 0.01
- **Unit:** frac_of_gross_weight · **Flag:** ASSUMPTION
- **Source:** Desk SPA template. ISRI 2022 non-ferrous guidelines set no general moisture franchise (fragmentizer grades must be 'dry'); weight deduction above a small franchise is the common scrap-contract practice
- **Verify:** **N/A** — contract-design assumption
- **Justification:** Moisture above 1% (determined by joint surveyor on arrival, oven-dry method) is deducted 1:1 from invoice weight; below 1% no adjustment.

### `rejection_penalty_schedule`

- **Value:** [{"trigger": "moisture above franchise", "measure": "joint survey, oven-dry", "remedy": "weight deduction 1:1 for the excess"}, {"trigger": "non-metallics / attachments above ISRI grade limit by up to 3 percentage points", "measure": "joint survey, sample sort", "remedy": "price discount of 1.5 × excess % on the whole lot"}, {"trigger": "non-metallics above limit by more than 3 points, or wrong grade", "measure": "joint survey", "remedy": "buyer may reject the lot or renegotiate within 10 days of survey; seller bears re-export or storage costs"}, {"trigger": "free zinc / magnesium / iron above ISRI limit (Zorba, fragmentizer grades)", "measure": "lab analysis of drill/melt sample", "remedy": "discount per agreed schedule, rejection if > 2× limit"}, {"trigger": "radioactivity above natural background or explosive/sealed pressurised items", "measure": "port portal monitor / PSIA certificate / AERB-notified agency", "remedy": "outright rejection; all costs, re-export and liabilities for seller's account"}]
- **Unit:** list · **Flag:** ASSUMPTION
- **Source:** Desk SPA template built on ISRI 2022 grade limits (Taint/Tabor oil & grease ≤1%, Tense ≤2%, fragmentizer non-metallics ≤5%) and DGFT PN 46/2015-20 radiation/explosives conditions
- **Verify:** **N/A** — contract-design assumption (no 2022 executed SPA available)
- **Justification:** Numbers in the schedule are design choices; the 1.5× discount multiplier is intentionally punitive so sellers do not dilute grade.

### `radioactivity_clause`

- **Value:** Seller warrants the material is free of radioactive substances above natural background, explosives, closed or pressurised containers and arms/ammunition; each shipment carries the supplier/scrap-yard certificate required by DGFT HBP para 2.54 (safe-origin, designated port) or a PSIC from a DGFT-recognised inspection agency (all other cases). Any container flagged by the Indian port radiation portal monitor or found non-compliant is rejected; seller bears inspection, isolation, decontamination, re-export and regulatory costs and indemnifies buyer against penalties.
- **Unit:** text · **Flag:** ASSUMPTION
- **Source:** Desk SPA clause drafted from DGFT PN 46/2015-2020 (14-Jan-2022) conditions and ISRI 2022 Zorba spec ('Shall be free of radioactive material')
- **Verify:** **N/A** — contract-design assumption; underlying DGFT condition PARTIAL (see regulatory.yaml import_policy_hs7602)
- **Justification:** Summary text only — not legal advice and not a copy of any real contract.

### `domestic_buyer_credit_days`

- **Value:** 30
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** MASTER_SPEC_V3 Table 4 row 2.6 ('advance vs 30d credit on domestic sales'); consistent with finance_days_* construction in logistics.yaml
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Foundry buyers in the Rajkot cluster (SIM) get 30 days against a credit limit; weak names pay advance. P2/P5 use this for exposure and days-past-due.

### `msme_max_payment_days`

- **Value:** 45
- **Unit:** days · **Flag:** DIRECT
- **Source:** Micro, Small and Medium Enterprises Development Act 2006, s.15 proviso: 'in no case the period agreed upon between the supplier and the buyer in writing shall exceed forty-five days from the day of acceptance or the day of deemed acceptance' (read at https://indiankanoon.org/doc/574789/ on 2026-09-16)
- **Verify:** **VERIFIED** — 2026-09-16 (statute text via Indian Kanoon; not re-checked on India Code)
- **Justification:** Relevant only where the supplier in a domestic sale is a registered micro/small enterprise (e.g. if the SIM desk were one selling to a large buyer): the statute caps agreed credit at 45 days. Interest consequences of late payment (s.16) were not re-read.

### `secondary_raw_material_cost_share`

- **Value:** 0.825
- **Unit:** frac_of_total_cost · **Flag:** PROXY
- **Source:** [CRISIL] Sept 2021: 'Raw material cost (scrap) typically accounts for 80-85% of the total cost (inclusive of all taxes and duties)'; the value is the midpoint of that published range (a transformation, hence PROXY; the DIRECT statement is the range 0.80–0.85)
- **Verify:** **VERIFIED** — 2026-09-16 that CRISIL Research publishes the 80–85% range (cached CMR PDF, industry estimate, not a measured 2022 figure); the midpoint is a convention
- **Justification:** Context for conversion_cost_inr_t and for the interview answer 'why is scrap spread, not LME, the P&L driver for a secondary smelter'. Same report: '85-90% of scrap is imported' (FY2020) and secondary aluminium 'continues to be 25-30% cheaper than primary aluminium'.

### `max_domestic_credit_days`

- **Value:** 45
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk policy (docs/20_trade_book.md rule C1): the longest credit the desk will grant a domestic buyer, set at the same 45 days the MSMED Act would impose if the desk were a registered micro/small supplier — a convenient benchmark, not a statutory obligation on these sales
- **Verify:** **N/A** — desk policy assumption. The statutory context (msme_max_payment_days) is separately VERIFIED
- **Justification:** Enforced by desk.book.schema V09 on every sale's credit_days and on each buyer's credit_days_default. One ticket (T06) uses the full 45 days and pays for them in the sale price (rule S1). The cap exists because a secondary smelter's own receivable cycle is 45-60 days: longer credit is the buyer's working capital, not the desk's, and the desk would rather be paid than be a lender.

### `lc_open_days_before_laycan_min`  — **PENDING**

- **Value:** 10
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk policy: a seller wants the documentary credit checked, amendable and in hand before it starts stuffing containers; scrap SPAs commonly require the LC 10-15 days before the laycan opens
- **Verify:** **PENDING** — no citable 2022 scrap SPA clause in the cached sources; the 10-15 day convention is trade practice reported in ISRI/BIR member guidance, not a document this project holds
- **Justification:** Minimum calendar days between purchase.payment.lc_open_date and shipment.laycan_start, enforced by desk.book.schema V11. Four tickets (T06, T07, T08, T09) were re-dated in the Phase 1-3 review because they opened their credits five or six days before the laycan, which no seller of a full container parcel would have accepted. Range 10-15; the desk uses the lower end because all nine parcels are with counterparties it has dealt with before.

### `buyer_advance_limit_multiple_of_credit_limit`

- **Value:** 1.0
- **Unit:** multiple_of_credit_limit_inr · **Flag:** ASSUMPTION
- **Source:** Desk policy added in the Phase 1-3 review: a pre-settlement advance is not credit the desk extends, but it is performance exposure to the same balance sheet — if the advance does not arrive the desk owns unsold cargo with its hedge already lifted
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Cap on the advance the desk will RELY ON from one buyer, expressed as a multiple of that buyer's own credit_limit_inr. desk.book.validate P14 warns (it does not refuse) when a contracted advance exceeds it, and the three BUY_RJK_01 parcels in this book all do — 1.26x, 1.53x and 1.83x of a Rs 120 mn line. Those warnings are the point: the limit definition in CONTRACTS §7a.4 counts receivables only, so a book that never breaches it can still be running its largest single exposure to its weakest name.

## `config/params/exchange.yaml`

Owner: P0 regulatory/contract research · 32 parameters · DIRECT 26, PROXY 1, ASSUMPTION 5.

| Key | Value | Unit | Flag | Verify |
|---|---|---|---|---|
| `mcx_al_lot_mt` | 5.0 | mt_per_lot | DIRECT | VERIFIED |
| `mcx_al_quote_unit` | INR per kg, ex-warehouse Raipur district, excluding only GST | text | DIRECT | VERIFIED |
| `mcx_al_tick_inr_kg` | 0.05 | inr_per_kg | DIRECT | VERIFIED |
| `mcx_al_max_order_mt` | 150.0 | mt_per_order | DIRECT | VERIFIED |
| `mcx_al_expiry_rule` | Last calendar day of the contract month; if a holiday, the precedin... | text | DIRECT | VERIFIED |
| `mcx_al_expiry_dates_2022` | ["2022-03-31", "2022-04-29", "2022-05-31", "2022-06-30", "2022-07-2... | dates | DIRECT | VERIFIED |
| `mcx_al_trading_hours` | Mon–Fri 09:00 to 23:30 IST (US summer time) / 23:55 IST (US winter ... | text | DIRECT | VERIFIED |
| `mcx_al_dpl_base_frac` | 0.04 | frac_of_prev_close | DIRECT | VERIFIED |
| `mcx_al_dpl_relaxed_frac` | 0.06 | frac_of_prev_close | DIRECT | VERIFIED |
| `mcx_al_dpl_max_frac` | 0.09 | frac_of_prev_close | DIRECT | VERIFIED |
| `mcx_al_initial_margin_frac` | 0.08 | frac_of_contract_value | DIRECT | VERIFIED |
| `mcx_al_elm_frac` | 0.01 | frac_of_contract_value | DIRECT | VERIFIED |
| `mcx_al_additional_margin_frac` | 0.0 | frac_of_contract_value | PROXY | PARTIAL |
| `mcx_al_margin_used_frac` | 0.1 | frac_of_contract_value | ASSUMPTION | **PENDING** |
| `mcx_al_delivery_unit_mt` | 5.0 | mt | DIRECT | VERIFIED |
| `mcx_al_delivery_logic` | Compulsory delivery; staggered delivery tender period = last 5 trad... | text | DIRECT | VERIFIED |
| `mcx_al_delivery_centres` | Primary: Raipur district (Chhattisgarh). Additional: Thane district... | text | DIRECT | PARTIAL |
| `mcx_al_delivery_period_margin_frac` | 0.25 | frac_of_contract_value | DIRECT | VERIFIED |
| `mcx_al_final_settlement_rule` | Due Date Rate = simple average of last polled spot prices on E0, E-... | text | DIRECT | VERIFIED |
| `mcx_al_position_limit_client_mt` | 25000.0 | mt | DIRECT | VERIFIED |
| `mcx_alumini_traded_2022` | False | bool | DIRECT | VERIFIED |
| `mcx_alumini_lot_mt` | 1.0 | mt_per_lot | DIRECT | VERIFIED |
| `mcx_roll_days_before_expiry` | 7 | trading_days | ASSUMPTION | N/A |
| `mcx_basis_std_inr_kg` | 4.44 | inr_per_kg | DIRECT | VERIFIED |
| `lme_al_lot_t` | 25.0 | mt_per_lot | DIRECT | PARTIAL |
| `lme_pricing_reference` | LME Official Settlement Price = LME Aluminium cash offer at the clo... | text | DIRECT | PARTIAL |
| `lme_m1_pricing_rule` | Provisional invoice on B/L; final price = arithmetic average of dai... | text | ASSUMPTION | N/A |
| `lme_official_publication_window_london` | 12:20–13:25 London time (Official and Official Settlement Prices es... | text | DIRECT | PARTIAL |
| `fx_hedge_regime` | RBI Risk Management & Inter-Bank Dealings directions (A.P. (DIR Ser... | text | DIRECT | PARTIAL |
| `fx_hedge_no_documentation_limit_usd` | 10000000.0 | usd | DIRECT | PARTIAL |
| `fx_forward_bank_margin_inr` | 0.1 | inr_per_usd | ASSUMPTION | **PENDING** |
| `fx_forward_settlement` | Deliverable outright forward, settled on the LC/usance payment date... | text | ASSUMPTION | N/A |

### `mcx_al_lot_mt`

- **Value:** 5.0
- **Unit:** mt_per_lot · **Flag:** DIRECT
- **Source:** [C385] and [C617] Annexure 1: 'Trading Unit 5 MT'
- **Verify:** **VERIFIED** — 2026-09-16 (identical in Jun-2021 and Oct-2022 circulars)
- **Justification:** Hedge tonnage is rounded to whole lots via desk.units.mt_to_lots; 1,000 MT scrap ≈ 0.8–0.9 × 1,000 MT metal ≈ 160–180 lots.

### `mcx_al_quote_unit`

- **Value:** INR per kg, ex-warehouse Raipur district, excluding only GST
- **Unit:** text · **Flag:** DIRECT
- **Source:** [C385]/[C617]: 'Quotation/ Base Value 1 Kg'; 'Price Quote Ex-Warehouse Raipur district (excludes only GST)'
- **Verify:** **VERIFIED** — 2026-09-16
- **Justification:** ₹/kg × 1,000 = ₹/MT (desk.units.inr_kg_to_inr_t). Price is ex-warehouse Raipur, i.e. a delivered-India duty-paid price, which is why the import-parity proxy uses 7601 BCD.

### `mcx_al_tick_inr_kg`

- **Value:** 0.05
- **Unit:** inr_per_kg · **Flag:** DIRECT
- **Source:** [C385]/[C617]: 'Tick Size (Minimum Price Movement) 5 paisa per kg'
- **Verify:** **VERIFIED** — 2026-09-16
- **Justification:** = ₹250 per 5 MT lot.

### `mcx_al_max_order_mt`

- **Value:** 150.0
- **Unit:** mt_per_order · **Flag:** DIRECT
- **Source:** [C385]/[C617]: 'Maximum Order Size 150 MT'
- **Verify:** **VERIFIED** — 2026-09-16
- **Justification:** 30 lots per order — a 1,000 MT hedge needs ≥6 child orders; relevant for execution-slippage commentary, not P&L.

### `mcx_al_expiry_rule`

- **Value:** Last calendar day of the contract month; if a holiday, the preceding working day. Trading on expiry day only up to 17:00 IST.
- **Unit:** text · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Last Trading Day' field; the 17:00 cut-off is in the body of [C385]
- **Verify:** **VERIFIED** — 2026-09-16
- **Justification:** CONTRACTS §4.5 approximates expiry as the last calendar day (previous business day if not a panel day); the actual 2022 dates are in mcx_al_expiry_dates_2022.

### `mcx_al_expiry_dates_2022`

- **Value:** ["2022-03-31", "2022-04-29", "2022-05-31", "2022-06-30", "2022-07-29", "2022-08-30", "2022-09-30", "2022-10-31", "2022-11-30"]
- **Unit:** dates · **Flag:** DIRECT
- **Source:** [PR22] Table 10 (contract expiry 31-Mar-2022) and [PR23] Table 10 'Delivery Quantity - Aluminium, Contract Expiry' (29-Apr-2022 … 30-Nov-2022)
- **Verify:** **VERIFIED** — 2026-09-16 (dates as printed by MCX)
- **Justification:** Note 30-Aug-2022, not 31-Aug: consistent with 31-Aug-2022 being an MCX holiday under the 'preceding working day' rule — the holiday list itself was not retrieved. Apr/Jul expiries fall on Friday 29th because the 30th/31st were weekend days. Caution: [PR22] prints two impossible dates for 2021 ('31-Jun-2021', '30-May-2021'), so treat the performance-review tables as good-but-not-perfect.

### `mcx_al_trading_hours`

- **Value:** Mon–Fri 09:00 to 23:30 IST (US summer time) / 23:55 IST (US winter time)
- **Unit:** text · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Trading Session'; MCX/TRD/646/2021 (08-Oct-2021): 09:00–23:55 for internationally referenceable non-agri commodities from 08-Nov-2021 to 11-Mar-2022
- **Verify:** **VERIFIED** — 2026-09-16
- **Justification:** From 14-Mar-2022 (US summer time) MCX aluminium closed 23:30 IST (≈ 18:00 GMT / 19:00 BST), i.e. hours after the LME official prices (12:20–13:25 London) and the LME close — MCX closes embed afternoon LME/COMEX moves that the same-day LME official does not (a timing source of daily LME–MCX basis noise).

### `mcx_al_dpl_base_frac`

- **Value:** 0.04
- **Unit:** frac_of_prev_close · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Daily Price Limits': narrower slab of 4%, relaxed to 6% without cooling-off, then 9% after a 15-minute cooling-off; beyond 9% in steps of 3% when international prices move more
- **Verify:** **VERIFIED** — 2026-09-16 (SEBI circular 27-Sep-2022, attached to MCX/TRD/556/2022, later allowed direct relaxation — after the window)
- **Justification:** LME official cash moved more than 4% on 10 days between 24-Feb and 31-Aug-2022 in lme_daily.csv (−12.1% on 08-Mar-2022, −5.3% on 15-Mar), so the 4% narrow slab was a live constraint on MCX price discovery in the window; whether MCX actually invoked the 6%/9% relaxations on those days was not checked.

### `mcx_al_dpl_relaxed_frac`

- **Value:** 0.06
- **Unit:** frac_of_prev_close · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Daily Price Limits'
- **Verify:** **VERIFIED** — 2026-09-16
- **Justification:** First relaxation, no cooling-off period.

### `mcx_al_dpl_max_frac`

- **Value:** 0.09
- **Unit:** frac_of_prev_close · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Daily Price Limits'
- **Verify:** **VERIFIED** — 2026-09-16
- **Justification:** After a 15-minute cooling-off; further 3% steps allowed if international markets move more.

### `mcx_al_initial_margin_frac`

- **Value:** 0.08
- **Unit:** frac_of_contract_value · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Initial Margin: Minimum 8% or based on SPAN whichever is higher'
- **Verify:** **VERIFIED** — 2026-09-16 as the contract MINIMUM. The actual SPAN-driven margin on 2022 dates was not retrieved (MCXCCL risk-parameter files not fetched).
- **Justification:** Floor only. For cash-buffer modelling use mcx_al_margin_used_frac.

### `mcx_al_elm_frac`

- **Value:** 0.01
- **Unit:** frac_of_contract_value · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Extreme Loss Margin: Minimum 1%'
- **Verify:** **VERIFIED** — 2026-09-16 (minimum)
- **Justification:** Charged on gross open positions on top of initial margin.

### `mcx_al_additional_margin_frac`

- **Value:** 0.0
- **Unit:** frac_of_contract_value · **Flag:** PROXY
- **Source:** MCX circular index (https://www.mcxindia.com/circulars/all-circulars, title search 'Additional Margin', 01-Jun-2021 → 30-Sep-2022): imposition/withdrawal circulars in the window concern gold (MCX/MCXCCL/143/2022, 08-Mar-2022: +2% on gold, withdrawn 22-Mar-2022 by 171/2022), silver (Jun–Jul 2022) and cotton — none names aluminium.
- **Verify:** **PARTIAL** — absence inferred from circular titles; an aluminium clause inside a multi-commodity circular would be missed. Next step: open every MCXCCL 'Imposition of Additional Margin' circular Feb–Aug 2022.
- **Justification:** So the desk's March-2022 margin stress comes from SPAN rising with volatility, not from an exchange-imposed aluminium add-on.

### `mcx_al_margin_used_frac`  — **PENDING**

- **Value:** 0.1
- **Unit:** frac_of_contract_value · **Flag:** ASSUMPTION
- **Source:** Desk assumption = initial margin minimum 8% + ELM 1% + ~1% SPAN/volatility cushion
- **Verify:** **PENDING** — replace with MCXCCL daily SPAN aluminium margin % for Mar–Aug 2022 if the risk-parameter archive becomes retrievable
- **Justification:** Used for margin & liquidity (Table 6 row 4.5) and variation-margin cash planning; stress with 0.12–0.15 in the crash fortnight.

### `mcx_al_delivery_unit_mt`

- **Value:** 5.0
- **Unit:** mt · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Delivery Unit 5 MT with tolerance limit of +/- 10%'
- **Verify:** **VERIFIED** — 2026-09-16
- **Justification:** Deliverable = primary aluminium ingots ≥99.70% of LME-approved brands (sows/T-bars at ₹1/kg discount). Secondary alloy ingot is NOT deliverable — the desk's hedge is a cross-product hedge (grade/basis risk).

### `mcx_al_delivery_logic`

- **Value:** Compulsory delivery; staggered delivery tender period = last 5 trading days incl. expiry; all positions open at expiry marked for delivery
- **Unit:** text · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Delivery Logic', 'Staggered Delivery Tender Period'
- **Verify:** **VERIFIED** — 2026-09-16
- **Justification:** Buyers allocated delivery cannot refuse — hence the desk must roll before the tender period (mcx_roll_days_before_expiry).

### `mcx_al_delivery_centres`

- **Value:** Primary: Raipur district (Chhattisgarh). Additional: Thane district (Maharashtra) in [C385]; Thane, NCR, Chennai, Kolkata in [C617]
- **Unit:** text · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Delivery Centre', 'Additional Delivery Centre(s)'; MCXCCL warehouse-accreditation circulars 30/2022 (17-Jan), 51/2022 (27-Jan), 71/2022 (10-Feb) for additional delivery centres (titles read)
- **Verify:** **PARTIAL** — the exact contract month from which NCR/Chennai/Kolkata became deliverable was not pinned down
- **Justification:** Rajkot/Gujarat buyers are far from Raipur — a physical buyer taking MCX delivery pays inland freight; supports treating MCX as a price reference, not a supply source.

### `mcx_al_delivery_period_margin_frac`

- **Value:** 0.25
- **Unit:** frac_of_contract_value · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Delivery Period Margin: higher of 3% + 5-day 99% VaR of spot price volatility, or 25%'
- **Verify:** **VERIFIED** — 2026-09-16 (floor of 25%)
- **Justification:** Another reason never to hold a hedge into the tender period.

### `mcx_al_final_settlement_rule`

- **Value:** Due Date Rate = simple average of last polled spot prices on E0, E-1, E-2 (fallback rules if unavailable)
- **Unit:** text · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Due Date Rate (Final Settlement Price)'
- **Verify:** **VERIFIED** — 2026-09-16
- **Justification:** MCX polls ex-warehouse spot twice daily ([PR23] §3e).

### `mcx_al_position_limit_client_mt`

- **Value:** 25000.0
- **Unit:** mt · **Flag:** DIRECT
- **Source:** [C385]/[C617] 'Maximum Allowable Open Position: individual client 25,000 MT or 5% of market-wide OI, whichever is higher'
- **Verify:** **VERIFIED** — 2026-09-16
- **Justification:** Far above the desk's 1,000–5,000 MT trades; not binding. (Hedger exemptions exist but are not needed.)

### `mcx_alumini_traded_2022`

- **Value:** False
- **Unit:** bool · **Flag:** DIRECT
- **Source:** MCX/TRD/104/2023 dated 15-Feb-2023 'Launch of Aluminium Mini Futures Contracts' w.e.f. 20-Feb-2023 (read in browser: https://www.mcxindia.com/docs/default-source/circulars/english/2023/february/circular---104-2023gud405b281-9e96-4e04-aaee-4d4820d54730.pdf)
- **Verify:** **VERIFIED** — 2026-09-16 — no ALUMINI contract was available during Mar–Aug 2022 (earlier 1 MT variants of 2019–2020 had lapsed; relaunched Feb-2023)
- **Justification:** Desk hedges in 5 MT ALUMINIUM lots only; odd tonnage (<5 MT) stays unhedged.

### `mcx_alumini_lot_mt`

- **Value:** 1.0
- **Unit:** mt_per_lot · **Flag:** DIRECT
- **Source:** MCX/TRD/104/2023 Annexure 'Contract Specifications of Aluminium Mini': Trading Unit 1 MT (tick 5 paisa/kg, max order 150 MT, same DPL/IM/ELM as ALUMINIUM)
- **Verify:** **VERIFIED** — 2026-09-16 (spec as launched Feb-2023; NOT tradable in the 2022 window)
- **Justification:** Reference only — see mcx_alumini_traded_2022.

### `mcx_roll_days_before_expiry`

- **Value:** 7
- **Unit:** trading_days · **Flag:** ASSUMPTION
- **Source:** Desk rule derived from the 5-trading-day staggered delivery tender period and the 25% delivery-period margin ([C385]/[C617])
- **Verify:** **N/A** — policy assumption
- **Justification:** Roll M1 → M2 on the 7th trading day before expiry: 2 days' cushion before the tender period opens, avoiding delivery allocation and the 25% margin; costs one spread crossing per month.

### `mcx_basis_std_inr_kg`

- **Value:** 4.44
- **Unit:** inr_per_kg · **Flag:** DIRECT
- **Source:** [PR23] §4a 'Basis Risk for F.Y. 2022-23: Aluminium Rs/Kg, Avg Return of Basis 0.83, Standard Deviation 4.44' ([PR22]: 1.03 / 4.37 for FY2021-22)
- **Verify:** **VERIFIED** — 2026-09-16 (as published; MCX defines it as the std-dev of daily return in basis = spot − near-month futures)
- **Justification:** MCX-reported hedge efficiency of near-month futures vs MCX spot was only 14.00% in FY21-22 and 55.67% in FY22-23 — a caution that even a same-exchange hedge leaves large basis noise; the desk's cross-product hedge (scrap/alloy vs primary futures) is weaker still.

### `lme_al_lot_t`

- **Value:** 25.0
- **Unit:** mt_per_lot · **Flag:** DIRECT
- **Source:** LME Aluminium contract specifications page (https://www.lme.com/en/metals/non-ferrous/lme-aluminium/contract-specifications, read in browser 2026-09-16): lot size 25 tonnes, price USD/t, tick $0.50 outright Ring/LMEselect
- **Verify:** **PARTIAL** — current page, not a 2022-dated rulebook; the 25 t lot and USD/t quotation are long-standing
- **Justification:** Reference only; the desk hedges on MCX (INR, 5 MT) and has no LME membership/clearing in the base case.

### `lme_pricing_reference`

- **Value:** LME Official Settlement Price = LME Aluminium cash offer at the close of the second Ring session (established and published within 12:20–13:25 London; see lme_official_publication_window_london)
- **Unit:** text · **Flag:** DIRECT
- **Source:** LME 'LME Official Prices explained' (https://www.lme.com/market-data/lme-reference-prices/lme-official-price, read 2026-09-16): 'the LME Official Settlement Price is the last cash offer price'
- **Verify:** **PARTIAL** — current methodology page (re-read in a browser 2026-09-16 after review flagged an inconsistency); the official-price definition predates 2022 but a 2022-dated benchmark methodology PDF was not retrieved
- **Justification:** Timing wording reconciled with lme_official_publication_window_london (review): the page's summary line says 'When is it published? 12.30-13.25 London time' while its own 'Trading day and price points' table says established and published 12.20 - 13.25; both fields now quote the table's wider window. Physical SPAs price off this official cash settlement (not the 3M). The desk's panel uses Westmetall's republication of LME official cash and 3M (lme_daily.csv). CONTRACTS §5 values FOB off LME 3M × grade factor (the forward the desk can actually hedge against at contract date); M+1 settlement references cash.

### `lme_m1_pricing_rule`

- **Value:** Provisional invoice on B/L; final price = arithmetic average of daily LME Official Cash Settlement Prices over the calendar month following the B/L month (M+1), × grade factor
- **Unit:** text · **Flag:** ASSUMPTION
- **Source:** Desk SPA convention (Table 4 row 2.4). The averaging mechanism mirrors the LME Monthly Average Settlement Price (MASP) — 'the average of the daily LME Official Cash Settlement Prices ... over the number of business days' (LME Aluminium contract specifications page, Monthly Average Futures section, read 2026-09-16)
- **Verify:** **N/A** — contract-design assumption; MASP definition VERIFIED from the LME page
- **Justification:** Choosing M+1 (not B/L-month) average gives the buyer time to arrange a matching sale and lets both sides hedge with LME MAFs/TAPOs. In a contango month the M+1 average of CASH is below today's 3M, so a buyer who hedged by selling 3M earns the carry; in backwardation it is the reverse (Table 3 row 1.7).

### `lme_official_publication_window_london`

- **Value:** 12:20–13:25 London time (Official and Official Settlement Prices established and published)
- **Unit:** text · **Flag:** DIRECT
- **Source:** LME 'LME Official Prices explained' page (https://www.lme.com/market-data/lme-reference-prices/lme-official-price), 'Trading day and price points' table: 'LME Official and Official Settlement Price established 12.20 - 13.25' and 'published 12.20 - 13.25' (re-read in a browser 2026-09-16)
- **Verify:** **PARTIAL** — current timetable, not a 2022-dated version; the same page's summary line gives 'When is it published? 12.30-13.25 London time', so the page is internally inconsistent by 10 minutes. Next step: the Benchmark Methodology - LME Official Prices PDF linked from that page.
- **Justification:** ≈ 17:50–18:55 IST (BST) — MCX aluminium is still trading when the LME official is set. The 12:20 vs 12:30 start does not affect any daily calculation in this project.

### `fx_hedge_regime`

- **Value:** RBI Risk Management & Inter-Bank Dealings directions (A.P. (DIR Series) Circular No. 29, 07-Apr-2020): users hedge contracted or anticipated exposures with AD Cat-I banks; free cancellation and rebooking; notional up to USD 10 mn outstanding without establishing underlying exposure
- **Unit:** text · **Flag:** DIRECT
- **Source:** RBI/2019-20/210 A.P.(DIR Series) Circular No. 29 dated 07-Apr-2020, as summarised at https://taxguru.in/rbi/risk-management-inter-bank-dealings-hedging-foreign-exchange-risk.html (read 2026-09-16)
- **Verify:** **PARTIAL** — secondary summary read (it states effective 01-Jun-2020; other summaries give 01-Sep-2020 after a COVID deferral); RBI original not fetched. Next step: read the circular on rbi.org.in and confirm it was unchanged through 2022.
- **Justification:** An importer with a signed SPA has a contracted exposure and may book deliverable forwards for the full USD value; retail users must be shown the mid-market mark before dealing.

### `fx_hedge_no_documentation_limit_usd`

- **Value:** 10000000.0
- **Unit:** usd · **Flag:** DIRECT
- **Source:** A.P. (DIR Series) Circular No. 29 (07-Apr-2020): 'up to USD 10 million equivalent of notional value (outstanding at any point in time) without the need to establish the existence of underlying exposure' (quoted via taxguru summary)
- **Verify:** **PARTIAL** — secondary summary; RBI original not fetched
- **Justification:** A 1,000 MT Zorba cargo at ~USD 2,300/t is ~USD 2.3 mn, so even a 4-cargo book fits under the limit.

### `fx_forward_bank_margin_inr`  — **PENDING**

- **Value:** 0.1
- **Unit:** inr_per_usd · **Flag:** ASSUMPTION
- **Source:** Desk assumption for a mid-size corporate importer's forward (spot + premium) margin over the interbank mid
- **Verify:** **PENDING** — no 2022 bank rate card for corporate forward margins was retrieved; check RBI FX-Retail platform documentation / RBI speeches on retail FX spreads for an order of magnitude
- **Justification:** 10 paise ≈ 0.13% of notional (≈ ₹230k on a USD 2.3 mn cargo). Range 0.03 (large corporate) to 0.25 (small SME).

### `fx_forward_settlement`

- **Value:** Deliverable outright forward, settled on the LC/usance payment date; tenor matched to finance_days (sight LC) or usance maturity
- **Unit:** text · **Flag:** ASSUMPTION
- **Source:** Desk hedge-policy convention (Table 4 row 2.7b) within the RBI regime in fx_hedge_regime
- **Verify:** **N/A** — policy assumption
- **Justification:** Forward points come from fx_rates_daily.csv (PROXY covered-interest-parity forwards) plus fx_forward_bank_margin_inr.

## `config/params/logistics.yaml`

Owner: P0 freight/logistics · 32 parameters · DIRECT 3, PROXY 1, ASSUMPTION 28.

| Key | Value | Unit | Flag | Verify |
|---|---|---|---|---|
| `container_payload_mt_20ft` | 25.0 | mt_per_box | ASSUMPTION | **PENDING** |
| `container_payload_mt_40ft` | 21.0 | mt_per_box | ASSUMPTION | **PENDING** |
| `container_payload_mt_20ft_zorba` | 26.0 | mt_per_box | ASSUMPTION | **PENDING** |
| `container_payload_mt_20ft_taint_tabor` | 20.0 | mt_per_box | ASSUMPTION | **PENDING** |
| `container_payload_mt_20ft_tense` | 25.0 | mt_per_box | ASSUMPTION | **PENDING** |
| `container_payload_mt_40ft_zorba` | 21.0 | mt_per_box | ASSUMPTION | **PENDING** |
| `container_payload_mt_40ft_taint_tabor` | 21.0 | mt_per_box | ASSUMPTION | **PENDING** |
| `container_payload_mt_40ft_tense` | 21.0 | mt_per_box | ASSUMPTION | **PENDING** |
| `transit_days_jea_nsa` | 5 | days | ASSUMPTION | **PENDING** |
| `transit_days_usec_mun` | 40 | days | ASSUMPTION | **PENDING** |
| `clearance_delivery_days` | 10 | days | ASSUMPTION | **PENDING** |
| `finance_days_jea_nsa` | 40 | days | ASSUMPTION | **PENDING** |
| `finance_days_usec_mun` | 73 | days | ASSUMPTION | **PENDING** |
| `typical_laycan_days` | 15 | days | ASSUMPTION | **PENDING** |
| `port_cf_charges_inr_t_nsa` | 1600 | inr_per_mt | ASSUMPTION | **PENDING** |
| `port_cf_charges_inr_t_mun` | 2650 | inr_per_mt | ASSUMPTION | **PENDING** |
| `insurance_rate` | 0.001 | frac_of_insured_value | ASSUMPTION | **PENDING** |
| `insured_value_uplift` | 1.1 | multiple_of_cif_value | DIRECT | PARTIAL |
| `detention_free_days` | 14 | days | ASSUMPTION | **PENDING** |
| `demurrage_usd_per_box_day` | 35 | usd_per_box_per_day | ASSUMPTION | **PENDING** |
| `demurrage_slab1_days` | 5 | days | ASSUMPTION | **PENDING** |
| `demurrage_slab2_days` | 5 | days | ASSUMPTION | **PENDING** |
| `demurrage_usd_per_box_day_slab2` | 70 | usd_per_box_per_day | ASSUMPTION | **PENDING** |
| `demurrage_usd_per_box_day_slab3` | 105 | usd_per_box_per_day | ASSUMPTION | **PENDING** |
| `rejected_box_hold_days` | 45 | days | ASSUMPTION | **PENDING** |
| `rejected_box_reexport_cost_usd_per_box` | 3000 | usd_per_box | ASSUMPTION | **PENDING** |
| `freight_jea_nsa_usd_box_ref` | 600 | usd_per_20ft_box | ASSUMPTION | **PENDING** |
| `freight_jea_nsa_ref_date` | 2022-03-04 | date_week_ending_friday | ASSUMPTION | N/A |
| `freight_usec_west_india_usd_feu_reported` | step path, 5 points: 2022-08-30: 1450; 2022-09-30: 1434; 2022-11-29... | usd_per_40ft_box | DIRECT | VERIFIED |
| `freight_europe_west_india_usd_feu_reported` | step path, 6 points: 2022-03-31: 2500; 2022-04-29: 2500; 2022-06-30... | usd_per_40ft_box | DIRECT | VERIFIED |
| `freight_usec_jun2022_drop_frac` | 0.125 | frac | PROXY | VERIFIED |
| `freight_stress_shock_frac` | 0.4 | frac_of_base_freight | ASSUMPTION | N/A |

### `container_payload_mt_20ft`  — **PENDING**

- **Value:** 25.0
- **Unit:** mt_per_box · **Flag:** ASSUMPTION
- **Source:** MASTER_SPEC_V3 Table 4 row 2.1 ('containerised ~24-26 MT/box'); 20ft dry box max gross 30,480 kg less ~2,200 kg tare
- **Verify:** **PENDING** — confirm typical Zorba / Taint-Tabor 20ft load weights from a Jebel Ali shipper's packing list or a BigMint/Fastmarkets methodology note
- **Justification:** BASE payload used to convert freight_weekly.csv USD/box into USD/MT. Heavy scrap cubes out by weight, not volume, so the 20ft box is used ex-Gulf and loaded close to the carrier's weight cap. Midpoint of the spec's 24-26 MT. Grade-specific payloads (container_payload_mt_20ft_<grade>) rescale per-box costs in CONTRACTS §5.

### `container_payload_mt_40ft`  — **PENDING**

- **Value:** 21.0
- **Unit:** mt_per_box · **Flag:** ASSUMPTION
- **Source:** US federal gross vehicle weight limit 80,000 lb (23 CFR 658.17) applied to typical tractor (~8 t) + 40ft chassis (~3 t) + container tare (~3.8 t)
- **Verify:** **PENDING** — the eCFR page redirected to a bot check when fetched; re-check 23 CFR 658.17 on ecfr.gov and a US scrap exporter's 40ft load weights (Recycling Today / ReMA)
- **Justification:** US scrap is exported in 40ft boxes (backhaul equipment availability) but road weight limits, not box capacity, cap the payload at roughly 20-22 MT for non-permitted drayage (36.3 t GVW - ~15.3 t tractor, chassis and box). Range 19-26 MT (26 MT only with port-side transloading / overweight permits). This is why the spec's generic 24-26 MT/box is NOT used for the 40ft lane.

### `container_payload_mt_20ft_zorba`  — **PENDING**

- **Value:** 26.0
- **Unit:** mt_per_box · **Flag:** ASSUMPTION
- **Source:** Desk judgement: shredded Zorba is dense (loose bulk ~1.0–1.3 t/m³) and loads to the ~27–28 t 20ft payload cap
- **Verify:** **PENDING** — packing lists / bills of lading for Zorba 95/5 20ft shipments (review asked for grade-specific payloads)
- **Justification:** CONTRACTS §5 scales per-box freight, port and PSIC costs by container_payload_mt_20ft / this value.

### `container_payload_mt_20ft_taint_tabor`  — **PENDING**

- **Value:** 20.0
- **Unit:** mt_per_box · **Flag:** ASSUMPTION
- **Source:** Desk judgement: baled old sheet cubes out before the weight cap in a 33 m³ 20ft box (bales ~0.6 t/m³)
- **Verify:** **PENDING** — packing lists for baled Taint/Tabor 20ft shipments
- **Justification:** Range 16–23 MT; the lower payload raises per-MT freight and port costs by 25% versus the 25 MT base.

### `container_payload_mt_20ft_tense`  — **PENDING**

- **Value:** 25.0
- **Unit:** mt_per_box · **Flag:** ASSUMPTION
- **Source:** Desk judgement: loose castings load to near the weight cap, as the base
- **Verify:** **PENDING** — packing lists for Tense 20ft shipments
- **Justification:** Equal to the base payload.

### `container_payload_mt_40ft_zorba`  — **PENDING**

- **Value:** 21.0
- **Unit:** mt_per_box · **Flag:** ASSUMPTION
- **Source:** US road-weight cap binds before volume for dense Zorba (see container_payload_mt_40ft)
- **Verify:** **PENDING** — as container_payload_mt_40ft
- **Justification:** Equal to the 40ft base.

### `container_payload_mt_40ft_taint_tabor`  — **PENDING**

- **Value:** 21.0
- **Unit:** mt_per_box · **Flag:** ASSUMPTION
- **Source:** Baled sheet at ~0.6 t/m³ needs ~35 m³ for 21 MT, within a 67 m³ 40ft box, so the road-weight cap still binds
- **Verify:** **PENDING** — as container_payload_mt_40ft
- **Justification:** Equal to the 40ft base.

### `container_payload_mt_40ft_tense`  — **PENDING**

- **Value:** 21.0
- **Unit:** mt_per_box · **Flag:** ASSUMPTION
- **Source:** US road-weight cap binds (see container_payload_mt_40ft)
- **Verify:** **PENDING** — as container_payload_mt_40ft
- **Justification:** Equal to the 40ft base.

### `transit_days_jea_nsa`  — **PENDING**

- **Value:** 5
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk assumption: ~1,050 nm short-sea Gulf-West India service, direct weekly mainline/feeder calls
- **Verify:** **PENDING** — pull a 2022 carrier schedule (e.g. Wayback copy of an MSC/Maersk/ESL Jebel Ali->Nhava Sheva point-to-point schedule) for port-to-port days
- **Justification:** Port-to-port sailing ~3-5 days plus berthing delays; range 3-8 days. 2022 schedule reliability was poor, so use the upper half of the range for stress cases.

### `transit_days_usec_mun`  — **PENDING**

- **Value:** 40
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk assumption: US East Coast -> West India via Suez, direct ISC-USEC string or Mediterranean transhipment
- **Verify:** **PENDING** — pull a 2022 carrier schedule (Wayback copy of a Hapag-Lloyd/MSC New York or Savannah -> Mundra routing) and record port-to-port days
- **Justification:** Direct India-USEC services run ~28-35 days one way; transhipment via Med hubs adds 7-15 days. Range 30-55 days. Mundra is typically served via transhipment from USEC.

### `clearance_delivery_days`  — **PENDING**

- **Value:** 10
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk assumption: vessel arrival -> Bill of Entry, duty payment, radiation/PSIC document checks, examination, out-of-charge, CFS delivery and truck to the SIM buyer (Gujarat for Mundra; within ~200 km of JNPT for Nhava Sheva)
- **Verify:** **PENDING** — compare with CBIC National Time Release Study 2022 (average release time for sea cargo at JNCH Nhava Sheva and Mundra) and add inland trucking days
- **Justification:** Scrap is a risk-managed cargo (radiation screening, pre-shipment inspection certificate checks) so release is slower than average containerised imports. Range 7-21 days; the upper end is the BIS/QCO + demurrage stress.

### `finance_days_jea_nsa`  — **PENDING**

- **Value:** 40
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk construction from components: LC-at-sight payment, transit_days_jea_nsa, clearance_delivery_days, 30-day domestic buyer credit
- **Verify:** **PENDING** — reconcile with the payment terms P2 assigns in config/trades.yaml (LC sight vs usance; buyer advance vs 30d credit)
- **Justification:** DEFINITION: days the desk's own INR working capital is tied up per tonne, from the day it pays the supplier to the day it receives the domestic buyer's payment. Timeline from B/L date: supplier paid under a sight LC on document presentation ~day 7 (goods already arrived after 5 days sailing; release by telex/LOI), BoE and duty ~day 8, out-of-charge + delivery ~day 17 (clearance_delivery_days after arrival, discharge queue included), buyer pays 30 days after delivery ~day 47 => 47 - 7 = 40 days. Applied in CONTRACTS §5 to (goods value at market FX + duties) for simplicity, which slightly overstates duty financing (duty is paid ~1 day after cash-out here). P1 must NOT add buyer-credit days again. A 60-90d usance LC would shorten this by the usance period (usance interest is then priced separately).

### `finance_days_usec_mun`  — **PENDING**

- **Value:** 73
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk construction from components: LC-at-sight payment, transit_days_usec_mun, clearance_delivery_days, 30-day domestic buyer credit
- **Verify:** **PENDING** — reconcile with the payment terms P2 assigns in config/trades.yaml (LC sight vs usance; buyer advance vs 30d credit)
- **Justification:** Same DEFINITION as finance_days_jea_nsa. Timeline from B/L date: sight LC paid ~day 7, arrival day 40, BoE and duty ~day 41, delivery ~day 50, buyer pays ~day 80 => 80 - 7 = 73 days. Here duty is paid ~34 days after cash-out, so applying 73 days to duties overstates finance cost on duties by ~34 days' interest (~INR 50/MT at 2.75% effective duty on ~INR 2 lakh/MT assessable value); accepted for formula simplicity and noted for P1.

### `typical_laycan_days`  — **PENDING**

- **Value:** 15
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk assumption: container scrap SPAs specify a shipment window rather than a bulk-style laycan
- **Verify:** **PENDING** — check shipment-period wording in a published ISRI/ReMA or BIR model contract for containerised non-ferrous scrap
- **Justification:** Laycan is a bulk-chartering term; for container cargo the equivalent is the shipment period in which the seller must load (commonly a half-month or calendar-month window). 15 days is used as the SIM "laycan" for Table 4 row 2.8 containers; bulk parcels (if any) should use 5-10 days.

### `port_cf_charges_inr_t_nsa`  — **PENDING**

- **Value:** 1600
- **Unit:** inr_per_mt · **Flag:** ASSUMPTION
- **Source:** Desk build-up per 20ft box / 25 MT base payload; component magnitudes are desk estimates (no 2022 tariff retrieved — carrier THC PDFs returned 403), not quotes
- **Verify:** **PENDING** — retrieve 2022 Wayback copies of a carrier's India import THC/DO tariff and a JNPT CFS tariff; get a 2022 short-haul (~200 km) 20ft truck rate out of JNPT
- **Justification:** Components per 20ft box (INR): destination THC ~9,500; CFS handling + ground rent within free days ~7,500; delivery order + B/L/documentation ~1,000; customs broker (CHA) fees ~3,000; examination, radiation-check and labour ~2,000; inland haulage to the SIM buyer within ~200 km of JNPT ~16,000 (review fix: previously ~52,000 for ~850 km to Rajkot; the short haul is priced above the long haul's per-km rate). Total ~39,000 per box = ~1,560/MT at 25 MT, rounded to 1,600. Range 1,200-2,500/MT. Excludes customs duty, IGST, demurrage and the PSIC fee (psic_cost_usd_per_box, added separately in CONTRACTS §5 for this non-safe-origin lane).

### `port_cf_charges_inr_t_mun`  — **PENDING**

- **Value:** 2650
- **Unit:** inr_per_mt · **Flag:** ASSUMPTION
- **Source:** Desk build-up per 40ft box / 21 MT; component magnitudes are desk estimates (no 2022 tariff retrieved — carrier THC PDFs returned 403), not quotes
- **Verify:** **PENDING** — retrieve 2022 Wayback copies of a carrier's Mundra import THC/DO tariff and an Adani Mundra CFS tariff; get a 2022 Mundra->Rajkot 40ft trailer rate
- **Justification:** Components per 40ft box (INR): destination THC ~14,500; CFS handling + ground rent within free days ~10,000; DO + documentation ~1,000; CHA ~3,500; examination, radiation-check and labour ~2,500; inland haulage Mundra -> Rajkot (~240 km) ~24,000. Total ~55,500 per box = ~2,650/MT at 21 MT. Range 1,800-3,800/MT. The per-tonne port cost is higher than NSA (fewer tonnes per box) but haulage is far shorter.

### `insurance_rate`  — **PENDING**

- **Value:** 0.001
- **Unit:** frac_of_insured_value · **Flag:** ASSUMPTION
- **Source:** Desk assumption: marine cargo open-cover premium for non-ferrous scrap, ICC (A)/(B) clauses
- **Verify:** **PENDING** — obtain an indicative 2022 marine cargo rate for metal scrap from an Indian insurer's published tariff guidance or a broker note
- **Justification:** 0.10% of insured value per shipment; plausible range 0.05%-0.20% (scrap is low-theft but prone to wetting/contamination claims). Immaterial to parity (~USD 2-3/MT). NOTE for the regulatory owner (not verified here): for customs assessable value, the Customs Valuation Rules 2007 (Rule 10(2)) deem insurance at 1.125% of FOB when the actual cost is not ascertainable — a customs-valuation rule, distinct from this commercial premium.

### `insured_value_uplift`

- **Value:** 1.1
- **Unit:** multiple_of_cif_value · **Flag:** DIRECT
- **Source:** ICC Uniform Customs and Practice for Documentary Credits (UCP 600), Article 28(f)(ii): if the credit is silent, insurance cover must be at least 110% of the CIF or CIP value
- **Verify:** **PARTIAL** — 2026-09-16 — wording confirmed via secondary reproduction (tradefinance.training 'UCP comparison Part 4'); the ICC publication itself is paywalled
- **Justification:** Market convention for LC-financed imports; insurance_usd_t = insurance_rate x 1.10 x CFR value per CONTRACTS §5 (CFR = FOB + freight; the grade factor is quoted on a CFR India basis).

### `detention_free_days`  — **PENDING**

- **Value:** 14
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk assumption: destination free time (carrier detention + CFS ground-rent-free period) negotiated by a regular scrap importer
- **Verify:** **PENDING** — retrieve a 2022 Wayback copy of a carrier's India import detention tariff (standard free days) and a JNPT/Mundra CFS free-period schedule
- **Justification:** Standard carrier import free time in India is often 7-10 days; regular importers commonly negotiate 14-21. Range 7-21. Counted from vessel discharge.

### `demurrage_usd_per_box_day`  — **PENDING**

- **Value:** 35
- **Unit:** usd_per_box_per_day · **Flag:** ASSUMPTION
- **Source:** Desk assumption: combined carrier detention + CFS ground rent per box per day beyond detention_free_days (first slab)
- **Verify:** **PENDING** — retrieve 2022 Wayback copies of a carrier's India import detention slabs (USD/day by box size) and a CFS ground-rent tariff (INR/day)
- **Justification:** Blended 20ft/40ft first-slab figure; carriers escalate slabs after 5-10 days, so long delays cost more per day. Range 15-75 USD/box/day. Used by P3 attribution factor (f) and the 'BIS-QCO + demurrage' stress.

### `demurrage_slab1_days`  — **PENDING**

- **Value:** 5
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk assumption: Indian import detention tariffs are slabbed, and the first slab typically runs 5 days (some carriers 7-10) beyond free time before the rate steps up
- **Verify:** **PENDING** — same evidence gap as demurrage_usd_per_box_day: retrieve a 2022 Wayback copy of a carrier's India import detention slab table (Maersk/MSC/CMA India local charges)
- **Justification:** Length of the first chargeable slab, counted from the end of detention_free_days. Added in the Phase 1-3 review: the book previously charged every chargeable day at the first-slab rate, which under-states a long delay — exactly the case the July-2022 congestion creates (T07 L2 runs 8 chargeable days).

### `demurrage_slab2_days`  — **PENDING**

- **Value:** 5
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk assumption: the second detention slab typically runs a further 5 days before the highest slab applies
- **Verify:** **PENDING** — as demurrage_slab1_days
- **Justification:** Length of the second chargeable slab. Days beyond slab 1 + slab 2 are charged at demurrage_usd_per_box_day_slab3.

### `demurrage_usd_per_box_day_slab2`  — **PENDING**

- **Value:** 70
- **Unit:** usd_per_box_per_day · **Flag:** ASSUMPTION
- **Source:** Desk assumption: carriers roughly double the per-day rate on the second detention slab (the 2x step is the common shape of published India import detention tariffs)
- **Verify:** **PENDING** — as demurrage_slab1_days
- **Justification:** 2x demurrage_usd_per_box_day. Range 30-150 USD/box/day. The multiple, not the level, is the assumption being made here; the level inherits the first slab's evidence gap.

### `demurrage_usd_per_box_day_slab3`  — **PENDING**

- **Value:** 105
- **Unit:** usd_per_box_per_day · **Flag:** ASSUMPTION
- **Source:** Desk assumption: the top detention slab runs at roughly 3x the first-slab rate
- **Verify:** **PENDING** — as demurrage_slab1_days
- **Justification:** 3x demurrage_usd_per_box_day, applied to every chargeable day beyond slab 1 + slab 2. Range 45-225. desk.book.validate.demurrage_usd() implements the schedule for Phase 2 and desk.mtm.lifecycle.detention_usd() for Phase 3; tests/test_mtm_engine.py asserts the two agree. All four demurrage keys price the COMBINED carrier detention + CFS ground rent beyond detention_free_days (the port_cf_charges_* build-up already carries ground rent inside the free period); the two are not split into separate tariffs, and the flat single-tier rate the first build used was a floor on the real cost, not an estimate of it.

### `rejected_box_hold_days`  — **PENDING**

- **Value:** 45
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk assumption: calendar days from vessel arrival until a container rejected at the port (radiation-portal alarm or gross non-conformity) has been segregated, surveyed under Customs/AERB supervision, granted re-export permission and shipped out
- **Verify:** **PENDING** — no 2022 case record or CBIC/AERB published timeline in the cached sources; the 30-60 day cycle is desk judgement for a referral that involves a second regulator
- **Justification:** Added in the Phase 1-3 review, when the radiation-portal rejection on T08 was found to cost nothing. Range 30-60. The rejected box accrues slabbed detention (demurrage_usd_per_box_day[_slab2/3]) for every day of the hold beyond detention_free_days, on top of rejected_box_reexport_cost_usd_per_box. The rest of the consignment's hold (its Bill of Entry is held while the referral runs) is a separate, ticketed SIM dwell event.

### `rejected_box_reexport_cost_usd_per_box`  — **PENDING**

- **Value:** 3000
- **Unit:** usd_per_box · **Flag:** ASSUMPTION
- **Source:** Desk build-up per rejected box, no 2022 tariff retrieved: return ocean freight of the order of the book's own USEC_MUN box rate in mid-2022 (1,500-2,300 USD/FEU on freight_weekly.csv levels, itself ASSUMPTION), both-end THC and yard handling, a radiological survey and supervised segregation, and customs/DGFT re-export documentation and CHA
- **Verify:** **PENDING** — retrieve a 2022 carrier export THC tariff at Mundra and any published AERB/Customs re-export procedure cost; the component magnitudes are desk estimates, not quotes
- **Justification:** Range 2,000-6,000 USD per box. Paid by the importer first (the box cannot leave without a consignee paying the line) and claimed back from the seller under the SPA's radioactivity clause at the quality event's claim_recovery_frac. Decontamination or disposal of a genuinely contaminated box — which can cost far more — is NOT modelled: the book assumes the alarm is a re-exportable source, the common case.

### `freight_jea_nsa_usd_box_ref`  — **PENDING**

- **Value:** 600
- **Unit:** usd_per_20ft_box · **Flag:** ASSUMPTION
- **Source:** Desk judgement; bounded by public India-inbound 2022 quotes (Container News) and normal-market Gulf-West India levels (Container News 2023-24) — see docs/research/freight_notes.md
- **Verify:** **PENDING** — no citable 2022 Jebel Ali->Nhava Sheva quote found (Platts WCI India-Middle East assessments and Xeneta are paywalled; S&P pages return 403). Next step: a 2022 Wayback copy of a Freightos/SeaRates/iContainers JEA->INNSA rate page, or a BigMint/Fastmarkets 2022 UAE-origin scrap CFR vs FOB spread
- **Justification:** Ocean freight incl. BAF/usual surcharges, excl. THC. Reasoning: (1) 2022 long-haul India-inbound backhaul rates were USD 2,300/TEU Europe->West India (Mar-Apr 2022) and USD 1,075/TEU USEC->West India (Aug 2022); a ~1,050 nm Gulf feeder lane should sit well below those. (2) India was short of export boxes in 2021-22, so carriers wanted to reposition equipment INTO India, which depresses inbound short-sea rates. (3) In later normal markets the reverse lane West India->Jebel Ali printed USD 75/TEU (Apr 2023) and USD 550/TEU (Sep 2024, Red Sea disruption). Plausible 2022-03-04 range USD 350-1,000/20ft (USD 14-40/MT at 25 MT).

### `freight_jea_nsa_ref_date`

- **Value:** 2022-03-04
- **Unit:** date_week_ending_friday · **Flag:** ASSUMPTION
- **Source:** Desk choice: first week of the headline window
- **Verify:** **N/A** — calibration choice
- **Justification:** Week at which freight_jea_nsa_usd_box_ref applies; the JEA_NSA series moves proportionally with the USEC India-inbound series from here.

### `freight_usec_west_india_usd_feu_reported`

- **Value:** step path, 5 points: 2022-08-30: 1450; 2022-09-30: 1434; 2022-11-29: 1434; 2022-12-30: 1125; 2023-01-30: 1100
- In window: 2022-03-01 1450 → 2022-08-31 1450; min 1450, max 1450.
- **Unit:** usd_per_40ft_box · **Flag:** DIRECT
- **Source:** Container News monthly India rate analyses: 30 Aug 2022, 30 Sep 2022, 30 Jan 2023 (container-news.com) and the 29 Nov 2022 edition republished by Maritime Gateway (maritimegateway.com) — 'USEC ... into West India (Nhava Sheva/Mundra)' average carrier rates
- **Verify:** **VERIFIED** — 2026-09-16 — values regex-extracted from cached article HTML (data/raw/freight/articles/) by desk.data.fetch_freight, which fails if text and YAML disagree; see data/interim/freight/points_india_inbound_anchors.csv for quotes
- **Justification:** Monthly averages of rates offered by leading liners for USEC (New York) -> West India, as reported by a trade publication (not an exchange index). The December value is the 'from US$1,125' prior-month level in the 30 Jan 2023 article. Used as level anchors for USEC_MUN (Mundra is within 'West India').

### `freight_europe_west_india_usd_feu_reported`

- **Value:** step path, 6 points: 2022-03-31: 2500; 2022-04-29: 2500; 2022-06-30: 2050; 2022-07-27: 1950; 2022-08-30: 1900; 2022-09-30: 1700
- In window: 2022-03-01 2500 → 2022-08-31 1900; min 1900, max 2500.
- **Unit:** usd_per_40ft_box · **Flag:** DIRECT
- **Source:** Container News monthly India rate analyses 29 Apr, 27 Jul, 30 Aug, 30 Sep 2022 (container-news.com) — eastbound Felixstowe/Rotterdam -> West India (Nhava Sheva/Mundra)
- **Verify:** **VERIFIED** — 2026-09-16 — values regex-extracted from cached article HTML by desk.data.fetch_freight (fails on mismatch); quotes in data/interim/freight/points_india_inbound_anchors.csv
- **Justification:** Sibling India-inbound backhaul lane. 2022-03-31 is stated in the April article ('same levels as they were at the end of March'); 2022-06-30 is the June level quoted as 'versus' in the July article. Used (i) to carry the USEC_MUN level into Mar/Apr 2022, before Container News reported the USEC leg, via the USEC/Europe ratio observed Jun-Sep 2022, and (ii) as evidence that India-inbound freight eased ~24% from Mar to Aug 2022.

### `freight_usec_jun2022_drop_frac`

- **Value:** 0.125
- **Unit:** frac · **Flag:** PROXY
- **Source:** Container News, 27 Jul 2022: 'On the return leg, rates offered by leading liners have dropped by between 10% and 15%, on average' (US East/West/Gulf coasts -> West India) vs June
- **Verify:** **VERIFIED** — 2026-09-16 — range regex-extracted from cached article; midpoint used
- **Justification:** Midpoint of the reported 10-15% July-vs-June fall for all US coasts into West India, applied to the USEC leg to derive a June 2022 anchor (USD 1,450 / (1 - 0.125) = ~1,657/FEU). Range of resulting June anchor USD 1,611-1,706/FEU.

### `freight_stress_shock_frac`

- **Value:** 0.4
- **Unit:** frac_of_base_freight · **Flag:** ASSUMPTION
- **Source:** MASTER_SPEC_V3 Table 6 row 4.2 stress scenario 'freight +40%'
- **Verify:** **N/A** — spec-defined hypothetical scenario
- **Justification:** Hypothetical instantaneous +40% on ocean freight USD/box for both lanes (not on port_cf_charges). It is a stress, not a replay: India-inbound freight did NOT rise 40% during Mar-Aug 2022 (it fell; see docs/research/freight_notes.md). For context, a +40% move is small next to the 2021 WCI surge (+99% from 7 Jan to 16 Sep 2021) and to the West India->USEC export spike (USD 11,200 -> 13,200/FEU Mar->Apr 2022, +18% in a month).

## `config/params/market_proxy.yaml`

Owner: P0 market-data · 1 parameters · DIRECT 0, PROXY 1, ASSUMPTION 0.

| Key | Value | Unit | Flag | Verify |
|---|---|---|---|---|
| `mcx_domestic_premium_inr_kg` | 0.0 | inr_per_kg | PROXY | PARTIAL |

### `mcx_domestic_premium_inr_kg`

- **Value:** 0.0
- **Unit:** inr_per_kg · **Flag:** PROXY
- **Source:** Calibrated in-repo against observed MCX Aluminium nearest-contract closes from a third-party mirror (https://commoditieschart.net/metals/aluminium/mcx-aluminium-futures-prices, retrieved 2026-09-16, cached in data/raw/mcx_thirdparty/commoditieschart_mcx_aluminium_nearest_raw.html via desk.data.fetch_mcx_mirror): implied premium = observed M1 / carry − duty-paid LME cash parity (BCD 7.5% × (1 + SWS 10%)), Mar–Aug 2022, n = 125 common days: mean −0.33, median +1.46, std 6.27 ₹/kg (full 2018–2022: mean −1.03, median −0.02, std 7.71).
- **Verify:** **PARTIAL** — mirror data could not be checked against MCX's own bhavcopy (mcxindia.com returned Akamai HTTP 403 to every request on 2026-09-16). Next step: download MCX bhavcopy for 5 window dates (e.g. 07-Mar, 13-Apr, 16-Jun, 14-Jul, 31-Aug-2022) from a browser, compare ALUMINIUM near-month closes with the mirror, then recompute.
- **Justification:** Set to 0.0 rather than the −0.33 window mean because the mean is small relative to its dispersion, the median has the opposite sign and monthly means swing from −9.9 (Mar 2022, MCX's 23:30 IST close lagging the LME official spike) to +3.5 (Jun 2022). Economically: MCX Aluminium is delivered duty-paid in India, so it should sit at LME × USDINR × (1 + BCD × (1 + SWS)) with no systematic extra premium. The calibration depends on bcd_primary_al_hs7601 and sws_rate_on_bcd (regulatory.yaml); recompute if those change. REGIME BIAS (review): unbiased over the window but not within it — Friday proxy M1 minus mirror M1 is +5 to +11 INR/kg on every March-2022 Friday (proxy too high in the LME spike; MCX's evening close lagged the LME official) and mostly −1 to −8 INR/kg on May–July Fridays (−7.52 on 13-May; proxy too low in the trough). Because the parity anchor is built on this proxy, it widens the open/closed swing between the spike and the trough. P1 should run the anchor on the mirror M1 as a sensitivity (still PROXY: third-party, unverified provenance) until MCX bhavcopy closes for 5 window dates are obtained.

## `config/params/parity.yaml`

Owner: P1 parity · 15 parameters · DIRECT 0, PROXY 0, ASSUMPTION 15.

| Key | Value | Unit | Flag | Verify |
|---|---|---|---|---|
| `parity_goods_fx_basis` | usdinr_fwd_1m | panel_column_name | ASSUMPTION | N/A |
| `customs_fx_notification_validity_days` | 14 | calendar_days | ASSUMPTION | N/A |
| `grade_factor_diff_quartiles_zorba` | [-0.0442, 0.0066] | signed_diff_of_lme_3m_frac_cfr_india | ASSUMPTION | N/A |
| `grade_factor_diff_quartiles_taint_tabor` | [-0.0583, -0.0093] | signed_diff_of_lme_3m_frac_cfr_india | ASSUMPTION | N/A |
| `grade_factor_diff_quartiles_tense` | [-0.0823, -0.0236] | signed_diff_of_lme_3m_frac_cfr_india | ASSUMPTION | N/A |
| `grade_factor_taint_tabor_spec_uplift` | 0.1 | frac_of_lme_3m | ASSUMPTION | N/A |
| `metal_yield_sensitivity_frac_zorba` | [0.92, 0.94] | frac_of_aluminium_to_ingot | ASSUMPTION | N/A |
| `metal_yield_sensitivity_frac_taint_tabor` | [0.9, 0.94] | frac_of_clean_metal_to_ingot | ASSUMPTION | N/A |
| `metal_yield_sensitivity_frac_tense` | [0.92, 0.95] | frac_of_clean_metal_to_ingot | ASSUMPTION | N/A |
| `heavies_net_value_sensitivity_frac` | [0.4, 1.5] | frac_of_lme_3m_usd_t_per_mt_of_heavies | ASSUMPTION | N/A |
| `spa_moisture_deduction_ratio` | 1.0 | mt_deducted_per_mt_of_excess_moisture | ASSUMPTION | N/A |
| `spa_contamination_discount_multiple` | 1.5 | frac_price_discount_per_frac_of_excess | ASSUMPTION | N/A |
| `spa_contamination_rejection_excess_frac` | 0.03 | frac_of_dry_weight_above_limit | ASSUMPTION | N/A |
| `lme_cash_prompt_bdays` | 2 | business_days_after_trade_date | ASSUMPTION | **PENDING** |
| `mplus1_bl_month_offset_months` | 0 | months_after_parity_week_month | ASSUMPTION | N/A |

### `parity_goods_fx_basis`

- **Value:** usdinr_fwd_1m
- **Unit:** panel_column_name · **Flag:** ASSUMPTION
- **Source:** CONTRACTS §5 goods_inr_t: 'market spot (P1 may use usdinr_fwd_* matched to the LC payment date instead, and must say which)'. Column from data/processed/market_daily.csv (PROXY, covered-interest-parity forward).
- **Verify:** **N/A** — modelling choice; the spot alternative is published as sensitivity case goods_fx_spot
- **Justification:** Goods are paid under a sight LC on document presentation, ~7 days after the B/L (logistics.yaml finance_days_* notes), and the B/L falls inside the 15-day shipment window (typical_laycan_days) after the parity week — so the USD payment is roughly one month after the decision on both lanes. An importer that fixes the rupee cost on the decision date buys USD one month forward; the domestic anchor is also a forward price (the MCX contract matched to the sale date), so both legs are valued at prices lockable on the same day. Pricing goods at spot would book the ~1-month forward premium (≈ INR 340–610/t of scrap in the Mar–Aug 2022 weeks) as margin. finance_inr_t then covers payment → buyer receipt only, so no time period is financed twice.

### `customs_fx_notification_validity_days`

- **Value:** 14
- **Unit:** calendar_days · **Flag:** ASSUMPTION
- **Source:** CBIC fortnightly exchange-rate notifications: consecutive USD-changing breakpoints in customs_usdinr_import (regulatory.yaml) are 14–21 days apart
- **Verify:** **N/A** — coverage rule for dates outside the registered notifications
- **Justification:** The registered notification path runs 18-Feb-2022 → 16-Sep-2022. A parity week whose value date is before the first notification, or more than this many days after the last one, uses customs_fx_markup_frac × market USD/INR (the register's documented fallback) instead of clamping a stale notified rate; parity_weekly.csv labels each row in customs_fx_src. Only out-of-window context weeks (Jan–mid-Feb and October 2022) are affected.

### `grade_factor_diff_quartiles_zorba`

- **Value:** [-0.0442, 0.0066]
- **Unit:** signed_diff_of_lme_3m_frac_cfr_india · **Flag:** ASSUMPTION
- **Source:** scrap_grades.yaml grade_factor_diff_zorba source ('IQR −0.044 … +0.007, n=15'); 4-dp values from data/interim/price_evidence/grade_differentials.csv (p25_diff_clean, p75_diff_clean)
- **Verify:** **N/A** — sensitivity range; tests/test_parity.py asserts equality with the Phase 0 evidence table
- **Justification:** Applied to 2022 exactly like the median differential (hence ASSUMPTION). Cases grade_diff_q25/q75 put the differential at each quartile; grade_diff_minus_iqr/plus_iqr move the registered median by one full IQR width.

### `grade_factor_diff_quartiles_taint_tabor`

- **Value:** [-0.0583, -0.0093]
- **Unit:** signed_diff_of_lme_3m_frac_cfr_india · **Flag:** ASSUMPTION
- **Source:** scrap_grades.yaml grade_factor_diff_taint_tabor source ('IQR −0.058 … −0.009, n=8'); data/interim/price_evidence/grade_differentials.csv
- **Verify:** **N/A** — sensitivity range; tests/test_parity.py asserts equality with the Phase 0 evidence table
- **Justification:** n=8: the widest relative uncertainty of the three grades.

### `grade_factor_diff_quartiles_tense`

- **Value:** [-0.0823, -0.0236]
- **Unit:** signed_diff_of_lme_3m_frac_cfr_india · **Flag:** ASSUMPTION
- **Source:** scrap_grades.yaml grade_factor_diff_tense source ('IQR −0.082 … −0.024, n=28'); data/interim/price_evidence/grade_differentials.csv
- **Verify:** **N/A** — sensitivity range; tests/test_parity.py asserts equality with the Phase 0 evidence table
- **Justification:** Asymmetric around the −0.07 median: the upper quartile is 4.6 points above it, so the high case raises Tense CFR cost by ~USD 130/t.

### `grade_factor_taint_tabor_spec_uplift`

- **Value:** 0.1
- **Unit:** frac_of_lme_3m · **Flag:** ASSUMPTION
- **Source:** MASTER_SPEC_V3 Table 3 row 1.2 guide 'Taint-Tabor ~88–92%' vs the registered clean-TT CFR factor (Mar–Aug mean 0.786); scrap_grades.yaml grade_factor_taint_tabor note ('run a +0.10 sensitivity')
- **Verify:** **N/A** — informational sensitivity; no retrieved evidence supports the spec guide
- **Justification:** Tests the spec's view only; it is not part of the required §5 band or the §5a rule.

### `metal_yield_sensitivity_frac_zorba`

- **Value:** [0.92, 0.94]
- **Unit:** frac_of_aluminium_to_ingot · **Flag:** ASSUMPTION
- **Source:** scrap_grades.yaml metal_yield_frac_zorba source/note ('0.92–0.94'; 'P1 recovery sensitivity: 0.92–0.94')
- **Verify:** **N/A** — sensitivity range from the Phase 0 note
- **Justification:** The note's range brackets the 0.93 melt yield (not the 0.866 recovery), so it is applied to metal_yield_frac_zorba.

### `metal_yield_sensitivity_frac_taint_tabor`

- **Value:** [0.9, 0.94]
- **Unit:** frac_of_clean_metal_to_ingot · **Flag:** ASSUMPTION
- **Source:** scrap_grades.yaml metal_yield_frac_taint_tabor note ('P1 recovery sensitivity: 0.90–0.94')
- **Verify:** **N/A** — sensitivity range from the Phase 0 note
- **Justification:** Brackets the 0.92 melt yield.

### `metal_yield_sensitivity_frac_tense`

- **Value:** [0.92, 0.95]
- **Unit:** frac_of_clean_metal_to_ingot · **Flag:** ASSUMPTION
- **Source:** scrap_grades.yaml metal_yield_frac_tense note ('P1 recovery sensitivity: 0.92–0.95')
- **Verify:** **N/A** — sensitivity range from the Phase 0 note
- **Justification:** Brackets the 0.94 melt yield.

### `heavies_net_value_sensitivity_frac`

- **Value:** [0.4, 1.5]
- **Unit:** frac_of_lme_3m_usd_t_per_mt_of_heavies · **Flag:** ASSUMPTION
- **Source:** scrap_grades.yaml heavies_net_value_frac_of_lme_al note ('P1 sensitivity: 0.4–1.5')
- **Verify:** **N/A** — sensitivity range from the Phase 0 note
- **Justification:** Only Zorba 95/5 carries a heavies fraction, so only Zorba rows move.

### `spa_moisture_deduction_ratio`

- **Value:** 1.0
- **Unit:** mt_deducted_per_mt_of_excess_moisture · **Flag:** ASSUMPTION
- **Source:** commercial.yaml rejection_penalty_schedule row 'moisture above franchise' → 'weight deduction 1:1 for the excess'; franchise = standard_moisture_franchise_frac
- **Verify:** **N/A** — contract-design assumption; tests/test_parity.py checks the schedule text still says 1:1
- **Justification:** Payable weight = contracted weight × (1 − ratio × max(0, moisture − franchise)).

### `spa_contamination_discount_multiple`

- **Value:** 1.5
- **Unit:** frac_price_discount_per_frac_of_excess · **Flag:** ASSUMPTION
- **Source:** commercial.yaml rejection_penalty_schedule row 'non-metallics / attachments above ISRI grade limit by up to 3 percentage points' → 'price discount of 1.5 × excess % on the whole lot'
- **Verify:** **N/A** — contract-design assumption; tests/test_parity.py checks the schedule text
- **Justification:** Intentionally punitive (commercial.yaml note). The contracted limit is the grade's registered contamination_frac_<grade> — the composition the grade factor and recovery already price — which sits inside the ISRI limits quoted in scrap_grades.yaml.

### `spa_contamination_rejection_excess_frac`

- **Value:** 0.03
- **Unit:** frac_of_dry_weight_above_limit · **Flag:** ASSUMPTION
- **Source:** commercial.yaml rejection_penalty_schedule row 'non-metallics above limit by more than 3 points, or wrong grade' → 'buyer may reject the lot or renegotiate'
- **Verify:** **N/A** — contract-design assumption; tests/test_parity.py checks the schedule text
- **Justification:** Above this excess the lot is rejectable: re-export or storage costs are for the seller, the desk loses the margin, not the cash.

### `lme_cash_prompt_bdays`  — **PENDING**

- **Value:** 2
- **Unit:** business_days_after_trade_date · **Flag:** ASSUMPTION
- **Source:** LME market convention: the cash prompt settles two business days after the trade date (T+2); the 3-months prompt is three calendar months after the trade date
- **Verify:** **PENDING** — stated from the standard LME convention, not re-read from the LME contract specification in Phase 1. Next step: LME Aluminium contract specification page (prompt date structure).
- **Justification:** Used only to place the cash price on the day axis when term_structure.py interpolates the forward curve between cash and 3M; a ±2-day error moves the implied M+1 average by < USD 1/t in the window.

### `mplus1_bl_month_offset_months`

- **Value:** 0
- **Unit:** months_after_parity_week_month · **Flag:** ASSUMPTION
- **Source:** Desk convention for Table 1.7(a): a cargo contracted in the parity week loads within the 15-day shipment window (typical_laycan_days), so its B/L month is taken as the parity week's month; the M+1 quotational period is the next calendar month (exchange.yaml lme_m1_pricing_rule)
- **Verify:** **N/A** — convention
- **Justification:** A contract fixed in the last week of a month would often B/L the following month; the term-structure effect then shifts one month later, not in sign.

## `config/params/rates.yaml`

Owner: P0 market-data · 7 parameters · DIRECT 3, PROXY 2, ASSUMPTION 2.

| Key | Value | Unit | Flag | Verify |
|---|---|---|---|---|
| `rbi_repo_rate_pa` | step path, 15 points: 2017-08-02: 0.06; 2018-06-06: 0.0625; 2018-08... | rate_pa | DIRECT | VERIFIED |
| `fed_funds_upper_pa` | step path, 18 points: 2017-06-15: 0.0125; 2017-12-14: 0.015; 2018-0... | rate_pa | DIRECT | VERIFIED |
| `usd_term_spread_3m_pa` | -0.0007 | rate_pa | PROXY | VERIFIED |
| `inr_term_spread_3m_pa` | -0.0012 | rate_pa | PROXY | VERIFIED |
| `sbi_mclr_1y_pa` | step path, 9 points: 2021-12-15: 0.07; 2022-04-15: 0.071; 2022-05-1... | rate_pa | DIRECT | VERIFIED |
| `wc_rate_spread_over_mclr_pa` | 0.025 | rate_pa | ASSUMPTION | **PENDING** |
| `wc_rate_inr_pa` | step path, 9 points: 2021-12-15: 0.095; 2022-04-15: 0.096; 2022-05-... | rate_pa | ASSUMPTION | N/A |

### `rbi_repo_rate_pa`

- **Value:** step path, 15 points: 2017-08-02: 0.06; 2018-06-06: 0.0625; 2018-08-01: 0.065; 2019-02-07: 0.0625; 2019-04-04: 0.06; 2019-06-06: 0.0575; 2019-08-07: 0.054; 2019-10-04: 0.0515; 2020-03-27: 0.044; 2020-05-22: 0.04; 2022-05-04: 0.044; 2022-06-08: 0.049; 2022-08-05: 0.054; 2022-09-30: 0.059; 2022-12-07: 0.0625
- In window: 2022-03-01 0.04 → 2022-08-31 0.054; min 0.04, max 0.054.
- **Unit:** rate_pa · **Flag:** DIRECT
- **Source:** RBI MPC resolutions (policy repo rate under the LAF), 'with immediate effect' on the announcement date
- **Verify:** **VERIFIED** — 2026-09-16 — every step read from rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=<id>: 41256 (02-Aug-2017, 6.25->6.0), 44125 (06-Jun-2018, to 6.25), 44636 (01-Aug-2018, to 6.5), 46235 (07-Feb-2019, 6.5->6.25), 46722 (04-Apr-2019, to 6.0), 47225 (06-Jun-2019, to 5.75), 47818 (07-Aug-2019, 5.75->5.40), 48319 (04-Oct-2019, to 5.15), 49581 (27-Mar-2020, to 4.40 from 5.15), 49843 (22-May-2020, to 4.0 from 4.40), 53652 (04-May-2022, +40bp to 4.40), 53832 (08-Jun-2022, +50bp to 4.90), 54148 (05-Aug-2022, +50bp to 5.40), 54541 (minutes of 28-30 Sep 2022 meeting, +50bp to 5.90), 54818 (07-Dec-2022, +35bp to 6.25). Each release states the size of the move, so the chain has no unrecorded steps between them.
- **Justification:** Step path effective on the announcement date. First breakpoint (Aug 2017) covers the Dec-2017 start of the FX/rates history.

### `fed_funds_upper_pa`

- **Value:** step path, 18 points: 2017-06-15: 0.0125; 2017-12-14: 0.015; 2018-03-22: 0.0175; 2018-06-14: 0.02; 2018-09-27: 0.0225; 2018-12-20: 0.025; 2019-08-01: 0.0225; 2019-09-19: 0.02; 2019-10-31: 0.0175; 2020-03-04: 0.0125; 2020-03-16: 0.0025; 2022-03-17: 0.005; 2022-05-05: 0.01; 2022-06-16: 0.0175; 2022-07-28: 0.025; 2022-09-22: 0.0325; 2022-11-03: 0.04; 2022-12-15: 0.045
- In window: 2022-03-01 0.0025 → 2022-08-31 0.025; min 0.0025, max 0.025.
- **Unit:** rate_pa · **Flag:** DIRECT
- **Source:** Federal Reserve Board, Policy Tools > Open Market Operations, 'federal funds rate target range' change table
- **Verify:** **VERIFIED** — 2026-09-16 via https://www.federalreserve.gov/monetarypolicy/openmarket.htm — table dates (effective dates, i.e. the day after each FOMC decision) and ranges 2017-06-15 1.00-1.25 through 2022-12-15 4.25-4.50 match every breakpoint here; no changes listed for 2021.
- **Justification:** Upper bound of the target range, stepped on the effective date.

### `usd_term_spread_3m_pa`

- **Value:** -0.0007
- **Unit:** rate_pa · **Flag:** PROXY
- **Source:** Calibrated in-repo: mean(US Treasury 13-week bill yield x 360/365 − fed_funds_upper_pa) over ECB days 2017-12-01..2022-12-30 = −0.00072
- **Verify:** **VERIFIED** — 2026-09-16 — recomputed from data/raw/rates/ust_daily_bill_rates_*.csv (see docs/research/market_data_notes.md)
- **Justification:** FALLBACK ONLY: used for usd_rate_3m_pa when the Treasury bill CSVs are neither fetchable nor cached. Bills trade slightly below the top of the Fed range on average; the gap is not constant (quarterly means from −31bp in Q3-2019 to +31bp in Q3-2022, when hikes were being priced in) so the real series is always preferred.

### `inr_term_spread_3m_pa`

- **Value:** -0.0012
- **Unit:** rate_pa · **Flag:** PROXY
- **Source:** Calibrated in-repo: mean(OECD MEI India IR3TIB monthly − calendar-month mean RBI repo), 2017-12..2022-12 = −0.00121 (std 0.0045)
- **Verify:** **VERIFIED** — 2026-09-16 — recomputed from data/raw/rates/oecd_finmark_ind_ir3tib_2017-12_2022-12.csv
- **Justification:** FALLBACK ONLY: used for inr_rate_3m_pa in any month without an OECD print. The monthly spread ranged from −94bp (Nov 2020, surplus liquidity) to +56bp (Nov 2022, hikes priced in), so a constant spread is a weak stand-in.

### `sbi_mclr_1y_pa`

- **Value:** step path, 9 points: 2021-12-15: 0.07; 2022-04-15: 0.071; 2022-05-15: 0.072; 2022-06-15: 0.074; 2022-07-15: 0.075; 2022-08-15: 0.077; 2022-10-15: 0.0795; 2022-11-15: 0.0805; 2022-12-15: 0.083
- In window: 2022-03-01 0.07 → 2022-08-31 0.077; min 0.07, max 0.077.
- **Unit:** rate_pa · **Flag:** DIRECT
- **Source:** State Bank of India 'MCLR Historical Data' table, 1Y column, monthly effective dates (https://sbi.bank.in/web/interest-rates/interest-rates/mclr-historical-data, cached data/raw/rates/sbi_mclr_historical_data.html). Only the dates on which the 1Y rate changed are kept (15-Dec-2021 7.00 unchanged through 15-Mar-2022; 15-Sep-2022 unchanged at 7.70).
- **Verify:** **VERIFIED** — 2026-09-16 — table read from the cached SBI page; the table lists rates by the 15th of each month, so a revision effective on another day of the month appears from the next listed date (actual SBI effective dates not checked against SBI press releases)
- **Justification:** Benchmark for the desk's INR working-capital line; rose 70 bp (7.00% → 7.70%) Mar–Aug 2022 while RBI repo rose 140 bp — partial pass-through, as expected for MCLR.

### `wc_rate_spread_over_mclr_pa`  — **PENDING**

- **Value:** 0.025
- **Unit:** rate_pa · **Flag:** ASSUMPTION
- **Source:** Desk assumption: mid-size unrated metals trader's cash-credit / working-capital line priced at SBI 1Y MCLR + 2.5%
- **Verify:** **PENDING** — no 2022 sanction letter or published spread for a comparable borrower retrieved. Next step: a listed metals trader's FY2022-23 annual report (borrowing-cost note) to back out its working-capital rate over MCLR.
- **Justification:** 2.5% keeps the rate at the previous register's 9.5% at the start of the window (7.00% + 2.5%), so the review fix changes only the path, not the starting level. Sensitivity ±1%.

### `wc_rate_inr_pa`

- **Value:** step path, 9 points: 2021-12-15: 0.095; 2022-04-15: 0.096; 2022-05-15: 0.097; 2022-06-15: 0.099; 2022-07-15: 0.1; 2022-08-15: 0.102; 2022-10-15: 0.1045; 2022-11-15: 0.1055; 2022-12-15: 0.108
- In window: 2022-03-01 0.095 → 2022-08-31 0.102; min 0.095, max 0.102.
- **Unit:** rate_pa · **Flag:** ASSUMPTION
- **Source:** sbi_mclr_1y_pa (DIRECT) + wc_rate_spread_over_mclr_pa (ASSUMPTION); flag = weakest component
- **Verify:** **N/A** — derived path; components verified/assumed as stated (tests assert path = MCLR + spread)
- **Justification:** Review fix: was a flat 9.5% through a window in which repo rose 140 bp; now 9.5% (Mar) → 9.6% (15-Apr) → 9.7% (15-May) → 9.9% (15-Jun) → 10.0% (15-Jul) → 10.2% (15-Aug-2022). Used for finance cost = (goods + duty) × finance_days_l / 365 × rate (CONTRACTS §5), at the rate in force on the parity week.

## `config/params/regulatory.yaml`

Owner: P0 regulatory/contract research · 22 parameters · DIRECT 14, PROXY 2, ASSUMPTION 6.

| Key | Value | Unit | Flag | Verify |
|---|---|---|---|---|
| `bcd_scrap_hs7602` | 0.025 | frac_of_assessable_value | DIRECT | VERIFIED |
| `sws_rate_on_bcd` | 0.1 | frac_of_bcd | DIRECT | VERIFIED |
| `aidc_scrap_hs7602` | 0.0 | frac_of_assessable_value | DIRECT | VERIFIED |
| `igst_rate_hs7602` | 0.18 | frac_of_av_plus_customs_duty | DIRECT | VERIFIED |
| `igst_credit_lag_days` | 45 | days | ASSUMPTION | N/A |
| `igst_itc_available` | True | bool | ASSUMPTION | N/A |
| `bcd_primary_al_hs7601` | 0.075 | frac_of_assessable_value | DIRECT | PARTIAL |
| `landing_charges_frac` | 0.0 | frac_of_cif | DIRECT | VERIFIED |
| `customs_deemed_freight_frac_fob` | 0.2 | frac_of_fob | DIRECT | VERIFIED |
| `customs_deemed_insurance_frac_fob` | 0.01125 | frac_of_fob | DIRECT | VERIFIED |
| `customs_usdinr_import` | step path, 15 points: 2022-02-18: 76.05; 2022-03-04: 76.65; 2022-03... | inr_per_usd | DIRECT | VERIFIED |
| `customs_fx_markup_frac` | 0.011 | frac_of_market_usdinr | PROXY | PARTIAL |
| `import_policy_hs7602` | Free, subject to DGFT HBP para 2.54 conditions (PSIC / designated p... | text | DIRECT | PARTIAL |
| `psic_required_safe_origin_designated_port` | False | bool | DIRECT | PARTIAL |
| `psic_required_uae_origin` | True | bool | DIRECT | PARTIAL |
| `psic_cost_usd_per_box` | 40.0 | usd_per_box | ASSUMPTION | **PENDING** |
| `nfmims_registration_required` | True | bool | DIRECT | PARTIAL |
| `nfmims_min_lead_days` | 5 | days_before_arrival | PROXY | **PENDING** |
| `bis_qco_scrap_in_force_2022` | False | bool | DIRECT | VERIFIED |
| `qco_stress_delay_days` | 21 | days | ASSUMPTION | N/A |
| `qco_stress_rejection_frac` | 0.1 | frac_of_shipment_mt | ASSUMPTION | N/A |
| `qco_stress_rejected_loss_frac` | 0.15 | frac_of_cif_value | ASSUMPTION | N/A |

### `bcd_scrap_hs7602`

- **Value:** 0.025
- **Unit:** frac_of_assessable_value · **Flag:** DIRECT
- **Source:** Notification No. 50/2017-Customs dated 30-Jun-2017 (effective-rate notification), Table S.No. 385: chapter/heading '7602', description 'Aluminium scrap', standard rate '2.5%' (CBIC portal id 1002538; cached data/raw/regulatory/cbic_notifications/cs50-2017_principal.pdf). Budget amendments to 50/2017 checked for any change to S.No. 385 / 7602: 06/2018, 25/2019, 01/2020, 02/2021, 55/2021 (HSN-2022 alignment), 02/2022, 02/2023 — none touches it (cached in the same folder).
- **Verify:** **VERIFIED** — 2026-09-16 (rate in principal notification + no change in the Budget/HSN amendment notifications read). Residual gap: ~40 non-Budget amendments to 50/2017 (2017–2022) were listed but not individually opened; pages read on 2026-09-16 (The Tribune/ANI 08-Jul-2026 on the AAI representation, https://www.tribuneindia.com/news/aluminium-quality/aluminium-association-of-india-urges-centre-to-notify-bis-standards-for-aluminium-scrap, cached data/raw/regulatory/news/tribune_aai_urges_bis_standards_aluminium_scrap.html; AlCircle Apr-2026) still cite 2.5% BCD on aluminium scrap, so an interim change and reversal is very unlikely.
- **Justification:** The seed's claim that 'Budget 2021-22 cut BCD on aluminium scrap to 2.5%' was WRONG — Budget 2021-22 cut copper scrap (7404) to 2.5%; aluminium scrap has been at 2.5% since at least the June-2017 GST-era re-issue of the effective-rate notification. Applies to both 7602 00 10 (ISRI-coded scrap) and 7602 00 90 (other) because S.No. 385 is written at heading level. The 5-percentage-point gap to primary aluminium (bcd_primary_al_hs7601 = 7.5%) is the policy wedge that makes scrap-to-ingot conversion in India an arbitrage (see notes §1).

### `sws_rate_on_bcd`

- **Value:** 0.1
- **Unit:** frac_of_bcd · **Flag:** DIRECT
- **Source:** Finance Act 2018 s.110(3): SWS 'at the rate of ten per cent' on the aggregate of duties, taxes and cesses levied under s.12 Customs Act, excluding safeguard/CVD/anti-dumping duty and SWS itself (text read at https://indiankanoon.org/doc/20129988/). IGST and GST compensation cess are exempted from SWS by Notification 13/2018-Customs (portal title read, truncated after 'from the whole o…'; text not opened). Exemption list Notification 11/2018-Customs (cached cs11-2018_sws_exempt.pdf) and its 2020/2021/2022 amendments 09/2020, 14/2021, 03/2022, 24/2022 contain no chapter-76 entry.
- **Verify:** **VERIFIED** — 2026-09-16 (statute text + exemption notifications read; no aluminium scrap exemption). Not re-checked: amendments to 11/2018 issued outside Budget days.
- **Justification:** With BCD 2.5% and no AIDC, SWS = 0.25% of assessable value, so BCD + SWS = 2.75% of AV on scrap versus 8.25% on primary aluminium.

### `aidc_scrap_hs7602`

- **Value:** 0.0
- **Unit:** frac_of_assessable_value · **Flag:** DIRECT
- **Source:** Notification No. 11/2021-Customs dated 01-Feb-2021 (effective rates of Agriculture Infrastructure and Development Cess; cached cs11-2021_aidc.pdf) lists no chapter-76 goods. 2022 amendments to 11/2021 seen on the CBIC portal (16/2022, 27/2022, 44/2022, 53/2022, 60/2022) concern edible oils, cotton, anthracite, platinum and similar items (titles only).
- **Verify:** **VERIFIED** — 2026-09-16 for the principal notification; the 2022 amendments were checked by title, not opened.
- **Justification:** AIDC was never levied on aluminium scrap in the window, so SWS base = BCD only.

### `igst_rate_hs7602`

- **Value:** 0.18
- **Unit:** frac_of_av_plus_customs_duty · **Flag:** DIRECT
- **Source:** Notification No. 1/2017-Integrated Tax (Rate) dated 28-Jun-2017, Schedule III (18%), S.No. 263: '7602 Aluminium waste and scrap' (CBIC portal id 1001202; cached igst01-2017_rate.pdf). Amendments 14/2021-IT(R) (w.e.f. 01-Jan-2022) and 01/2022-IT(R) (31-Mar-2022) read — neither touches S.No. 263.
- **Verify:** **VERIFIED** — 2026-09-16 (principal schedule + the two amendments in force around the window).
- **Justification:** IGST base = AV + BCD + SWS (Customs Tariff Act s.3 — IGST charged on value plus customs duties; subsection text not re-fetched). Primary aluminium 7601 is in the same Schedule III (S.No. 262), so IGST is neutral between the scrap and primary routes.

### `igst_credit_lag_days`

- **Value:** 45
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk construction: IGST is paid with the Bill of Entry (~1 day after arrival) and recovered as input tax credit when the GSTR-3B for the month of the domestic sale is filed (20th of the following month); for a sale ~10 days after arrival that is ~40–50 days
- **Verify:** **N/A** — cash-cycle assumption (GSTR-3B due date rule stated from CGST Rules r.61, not re-fetched)
- **Justification:** Used ONLY for the IGST financing line in CONTRACTS §5 (igst_finance_inr_t); IGST itself is not a landed cost while igst_itc_available is true. At 18% × ~INR 2.3 lakh × 45/365 × 9.5–10% ≈ INR 500/t.

### `igst_itc_available`

- **Value:** True
- **Unit:** bool · **Flag:** ASSUMPTION
- **Source:** Desk assumption: GST-registered importer re-selling taxable goods claims full ITC on IGST paid on the Bill of Entry
- **Verify:** **N/A** — structural assumption (legal basis: Bill of Entry is an ITC document under CGST Rules r.36(1)(d); rule text not re-fetched)
- **Justification:** When true, import IGST is excluded from landed cost; only its financing from the Bill of Entry to the GSTR-3B offset is kept (igst_credit_lag_days, CONTRACTS §5 igst_finance_inr_t). Real-world caveat: ITC is cash-neutral only after the output invoice; a desk with thin domestic output tax liability can carry a blocked-credit balance — that is a working-capital cost, not a P&L cost.

### `bcd_primary_al_hs7601`

- **Value:** 0.075
- **Unit:** frac_of_assessable_value · **Flag:** DIRECT
- **Source:** Customs Tariff Act 1975, First Schedule tariff rate for heading 7601 = 7.5% (search summaries attribute the 5% -> 7.5% increase to Budget 2016-17; no Budget-2016 document was retrieved). Notification 50/2017-Customs (principal, cached) has no 7601 concession, and the 2018–2023 Budget amendments read (see bcd_scrap_hs7602) contain no 7601 entry, so the tariff rate applied in 2022. AlCircle (Apr-2026, https://www.alcircle.com/news/can-india-sustain-8-25-aluminium-duties-when-55-of-demand-is-imported-118251, read 2026-09-16): 'Primary aluminium under HS 7601 is charged at 8.25 per cent, scrap under HS 7602 at 2.5 per cent' (8.25% = 7.5% BCD × 1.10 SWS).
- **Verify:** **PARTIAL** — 2026-09-16 — chain of evidence is consistent but the 2022 First Schedule page for chapter 76 itself was not retrieved. Next step: download the Customs Tariff chapter 76 as amended by the Finance Act 2022 (CBIC Tax Information Portal > Acts > Customs Tariff Act) and read tariff items 7601 10 10–7601 20 90.
- **Justification:** Used only for the MCX import-parity proxy (MCX Aluminium is priced duty-paid; market_proxy.yaml calibrates mcx_domestic_premium_inr_kg on this rate).

### `landing_charges_frac`

- **Value:** 0.0
- **Unit:** frac_of_cif · **Flag:** DIRECT
- **Source:** Notification No. 91/2017-Customs (N.T.) dated 26-Sep-2017, Customs Valuation (Determination of Value of Imported Goods) Amendment Rules 2017, substituting Rule 10(2) (CBIC portal id 1006196; cached csnt91-2017_valuation_amend.pdf). The substituted rule includes transport, loading, unloading and handling charges 'to the place of importation' at actual and contains no deemed landing-charge percentage.
- **Verify:** **VERIFIED** — 2026-09-16 (amendment text read; in force throughout 2022).
- **Justification:** The pre-2017 Rule 10(2) added a deemed 1% of CIF for landing charges; that addition no longer exists, so AV = CIF (ocean freight and insurance at actual). Destination THC/CFS/DO after arrival are NOT in AV — they sit in port_cf_charges_inr_t_* (logistics.yaml). Fallbacks written into the same rule: freight not ascertainable => 20% of FOB; insurance not ascertainable => 1.125% of FOB (see customs_deemed_* below).

### `customs_deemed_freight_frac_fob`

- **Value:** 0.2
- **Unit:** frac_of_fob · **Flag:** DIRECT
- **Source:** Notification 91/2017-Customs (N.T.), substituted Rule 10(2), first proviso (cached csnt91-2017_valuation_amend.pdf)
- **Verify:** **VERIFIED** — 2026-09-16 (text read)
- **Justification:** Only applies when actual freight is not ascertainable (e.g., an FOB contract with undocumented freight). Not used in the base parity, which uses actual/proxy freight.

### `customs_deemed_insurance_frac_fob`

- **Value:** 0.01125
- **Unit:** frac_of_fob · **Flag:** DIRECT
- **Source:** Notification 91/2017-Customs (N.T.), substituted Rule 10(2), third proviso (cached csnt91-2017_valuation_amend.pdf)
- **Verify:** **VERIFIED** — 2026-09-16 (text read)
- **Justification:** Customs-valuation fallback when the insurance cost is not ascertainable. It is ~10x the commercial premium (insurance_rate, logistics.yaml), so an importer who cannot evidence the actual premium pays duty on a larger AV: ~1.1% × 2.75% ≈ 0.03% of FOB extra duty — immaterial, but a real compliance point.

### `customs_usdinr_import`

- **Value:** step path, 15 points: 2022-02-18: 76.05; 2022-03-04: 76.65; 2022-03-18: 76.9; 2022-04-08: 76.8; 2022-04-22: 77.15; 2022-05-06: 77.05; 2022-05-20: 78.6; 2022-06-03: 78.5; 2022-06-17: 78.95; 2022-07-08: 79.9; 2022-07-22: 80.95; 2022-08-05: 80.25; 2022-08-19: 80.5; 2022-09-02: 80.45; 2022-09-16: 80.4
- In window: 2022-03-01 76.05 → 2022-08-31 80.5; min 76.05, max 80.95.
- **Unit:** inr_per_usd · **Flag:** DIRECT
- **Source:** CBIC exchange-rate notifications under s.14 Customs Act, Schedule I 'US Dollar — (a) For Imported Goods', each effective the day after issue as stated in its text (cached data/raw/regulatory/cbic_exchange_rates_2022/csnt<N>-2022.pdf, listed on https://taxinformation.cbic.gov.in/content-page/explore-notification, Customs > Non Tariff > 2022).
- **Verify:** **VERIFIED** — 2026-09-16 — all 15 USD-changing notifications Feb–Sep 2022 read. The interleaved amendments 16/2022, 36/2022, 38/2022, 42/2022, 53/2022, 54/2022, 83/2022 and 85/2022 were also read: they change only Turkish lira, Norwegian krone, rand, Swiss franc or sterling, never the USD rate.
- **Justification:** Assessable value in INR = CIF USD × the import rate in force on the Bill of Entry date (s.14 read with s.46/s.15 Customs Act; the rate on the date of filing the BoE applies — rule stated from the Act, not re-fetched). Import − export = INR 1.70 in 13 of the 15 notifications and INR 1.75 in 64/2022 (80.95 / 79.20) and 73/2022 (80.45 / 78.70) (corrected after review; all 15 import values re-read from the cached PDFs). Values before 18-Feb-2022 clamp to 76.05 (not in window). CONTRACTS §5 uses this rate ONLY for the duty base (av_customs_inr_t); the goods themselves are paid at the market rate.

### `customs_fx_markup_frac`

- **Value:** 0.011
- **Unit:** frac_of_market_usdinr · **Flag:** PROXY
- **Source:** Computed in-repo 2026-09-16: customs_usdinr_import ÷ market USDINR (data/processed/fx_rates_daily.csv usdinr, ECB cross) on the last business day before each notification, 14 notifications 04-Mar-2022 → 16-Sep-2022: mean +1.11% (range +0.78% to +1.36%); versus the average market rate over each notification's validity period: mean +0.68% (range −0.53% to +1.88%).
- **Verify:** **PARTIAL** — the customs side is DIRECT; the market side is the ECB-cross PROXY, not the RBI reference rate.
- **Justification:** Use only as a fallback when a date falls outside customs_usdinr_import. Economic reading: the customs import rate is set roughly at market + ~₹0.85 and then frozen for a fortnight, so in a depreciating-INR fortnight (e.g. 22-Jul-2022 validity, +1.88%) duty is computed on a stale-but-high rate, and in a sharp INR fall (e.g. 06-May, 16-Sep validity) the importer briefly pays duty on a rate BELOW market.

### `import_policy_hs7602`

- **Value:** Free, subject to DGFT HBP para 2.54 conditions (PSIC / designated ports / radiation checks) and NFMIMS registration
- **Unit:** text · **Flag:** DIRECT
- **Source:** DGFT Public Notice No. 46/2015-2020 dated 14-Jan-2022 amending HBP 2015-20 para 2.54(d)(v)(iv) (text as reproduced at http://worldtradescanner.com/46-PN-14.01.2022.htm and summarised at https://www.bizsolindia.com/dgft-import-consignments-of-metallic-waste-and-scrap-both-shredded-and-unshredded-imported-from-safe-countries-region-i-e-the-usa-the-uk-canada-new-zealand-australia-and-the-eu-will-not-requ/); NFMIMS per DGFT Notification 61/2015-2020 dated 31-Mar-2021 (reported by TaxTMI/TeamLease/Taxscan secondary pages).
- **Verify:** **PARTIAL** — 2026-09-16 — PN 46 content read via two republishers, not the DGFT PDF itself; NFMIMS coverage of 7602 read only from secondary pages. Next step: fetch the DGFT PDFs from https://www.dgft.gov.in/CP/?opt=public-notice and ?opt=notification (JS portal; use a browser) and read the ITC(HS) policy-condition text for 7602.
- **Justification:** Structural input for the compliance narrative and the stress scenario; not a number in the parity formula.

### `psic_required_safe_origin_designated_port`

- **Value:** False
- **Unit:** bool · **Flag:** DIRECT
- **Source:** DGFT Public Notice 46/2015-2020 (14-Jan-2022), para 2.54(d)(v)(iv) as amended (see import_policy_hs7602)
- **Verify:** **PARTIAL** — republisher text read (worldtradescanner, bizsolindia); DGFT original not fetched
- **Justification:** Metallic scrap from USA, UK, Canada, New Zealand, Australia and the EU needs no PSIC when cleared at one of ten ports (Chennai, Tuticorin, Kandla, JNPT, Mumbai, Krishnapatnam, Mundra, Kattupalli, Hazira, Kamarajar), provided it carries a supplier/scrap-yard certificate of no radioactive material/explosives and passes portal-monitor radiation and container-scanner checks at the port. => the USEC_MUN lane (US origin into Mundra) needs no PSIC.

### `psic_required_uae_origin`

- **Value:** True
- **Unit:** bool · **Flag:** DIRECT
- **Source:** DGFT Public Notice 46/2015-2020 (14-Jan-2022): exemption limited to the six named safe origins; other origins remain subject to PSIC
- **Verify:** **PARTIAL** — republisher text read; DGFT original not fetched
- **Justification:** UAE is not a 'safe country', so Jebel Ali cargo into Nhava Sheva (JEA_NSA) needs a Pre-Shipment Inspection Certificate from a DGFT-recognised inspection agency (list at https://www.dgft.gov.in/CP/?opt=psia) even though JNPT is a designated port. Operational consequence: add PSIC cost and lead time to every Gulf fixture.

### `psic_cost_usd_per_box`  — **PENDING**

- **Value:** 40.0
- **Unit:** usd_per_box · **Flag:** ASSUMPTION
- **Source:** Desk assumption — no 2022 PSIA tariff was retrieved
- **Verify:** **PENDING** — obtain an inspection-agency (PSIA) 2022 quote or published fee for radiation + explosives inspection of a 20ft scrap container at Jebel Ali
- **Justification:** ≈ USD 1.6/MT at 25 MT/box — small but now included in CONTRACTS §5 port charges for non-safe origins (JEA_NSA), per review; material to operations (lead time ~2–4 days before stuffing/sailing).

### `nfmims_registration_required`

- **Value:** True
- **Unit:** bool · **Flag:** DIRECT
- **Source:** DGFT Notification 61/2015-2020 dated 31-Mar-2021 (import policy of chapter-76 items changed to 'Free subject to compulsory registration under NFMIMS'); DGFT Policy Circular 42/2015-2020 dated 27-Jul-2022 clarifications (read at https://www.taxscan.in/dgft-clarifies-issues-relating-to-non-ferrous-metal-import-monitoring-system/194908)
- **Verify:** **PARTIAL** — secondary sources only; whether 7602 00 10/90 are in the 43 covered chapter-76 lines is not confirmed from the DGFT annexure. Next step: read the annexure of Notification 61/2015-2020 on dgft.gov.in.
- **Justification:** Registration (automatic URN) must be filed no earlier than 60 days and no later than 5 days before expected arrival (secondary sources); the 27-Jul-2022 circular says one registration can cover multiple consignments within its validity and that NFMIMS does not apply to air freight.

### `nfmims_min_lead_days`  — **PENDING**

- **Value:** 5
- **Unit:** days_before_arrival · **Flag:** PROXY
- **Source:** Secondary descriptions of DGFT Notification 61/2015-2020 (IndiaFilings / TaxTMI summaries retrieved via search 2026-09-16)
- **Verify:** **PENDING** — confirm 60/5-day window and 75-day validity in the DGFT notification text
- **Justification:** A late NFMIMS registration blocks the Bill of Entry — an avoidable demurrage trigger on the JEA_NSA lane where transit is only ~5 days.

### `bis_qco_scrap_in_force_2022`

- **Value:** False
- **Unit:** bool · **Flag:** DIRECT
- **Source:** PIB release (01-Sep-2023, PRID 1954005, https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=1954005, cached data/raw/regulatory/news/pib_prid_1954005_mines_qco_non_ferrous.html): the Mines ministry QCOs notified 31-Aug-2023 'mark the first technical regulations from Ministry of Mines under the BIS Act' and cover aluminium and alloy ingots/castings and EC-grade products, not scrap. Argus 'India scraps BIS norms on some metals' (14-Nov-2025, https://www.argusmedia.com/en/news-and-insights/latest-market-news/2754022-india-scraps-bis-norms-on-some-metals, cached argus_2754022_india_scraps_bis_norms_on_some_metals.html) and ELP Law 'BIS Update - Withdrawal of QCOs for certain metals' (https://elplaw.in/leadership/bis-update-withdrawal-of-qcos-for-certain-metals/, cached) report those QCOs withdrawn (announced 13-Nov-2025). The Tribune / ANI (08-Jul-2026, https://www.tribuneindia.com/news/aluminium-quality/aluminium-association-of-india-urges-centre-to-notify-bis-standards-for-aluminium-scrap, cached tribune_aai_urges_bis_standards_aluminium_scrap.html): the standard 'Aluminium & Aluminium Alloy Scrap - Requirements & Conditions of Delivery' 'has remained pending for more than two years'.
- **Verify:** **VERIFIED** — 2026-09-16 — no BIS QCO applied to aluminium scrap in 2022 (PIB: the first Mines QCOs came in Aug-2023 and did not cover scrap); later status from Argus/ELP (withdrawal) and Tribune/ANI (scrap standard still pending). All four pages re-retrieved and cached on 2026-09-16 after review found two sources without URLs.
- **Justification:** So the 'BIS-QCO + demurrage' scenario (Table 6 row 4.2) is a hypothetical policy shock, not a replay of a 2022 event. It is plausible because (i) the primary industry (AAI) has lobbied since 2022–23 for scrap standards and higher scrap duty, (ii) the Mines ministry did impose QCOs on primary aluminium within ~18 months of the window, and (iii) BIS standard IS 2066 (Part 1):2024 for scrap classification now exists. See notes §4.

### `qco_stress_delay_days`

- **Value:** 21
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk scenario design; anchored on clearance_delivery_days range 7–21 (logistics.yaml) and on the 3-month notification-to-effect lag written into the 2023 Mines QCOs (PIB 01-Sep-2023)
- **Verify:** **N/A** — scenario assumption
- **Justification:** Extra port dwell per container while BIS licence / test-report paperwork is demanded at clearance for cargo already afloat when a scrap QCO bites. Applied on top of clearance_delivery_days and beyond free days, it drives demurrage via demurrage_usd_per_box_day and detention_free_days (logistics.yaml) plus 21 days' extra finance cost. 21 days ≈ one BIS sampling-and-test cycle plus a re-filing — a judgement, not an observation.

### `qco_stress_rejection_frac`

- **Value:** 0.1
- **Unit:** frac_of_shipment_mt · **Flag:** ASSUMPTION
- **Source:** Desk scenario design
- **Verify:** **N/A** — scenario assumption
- **Justification:** Share of affected tonnage refused clearance (non-conforming grade/contamination against a new BIS scrap standard) and re-exported or sold in bond. 10% reflects that ISRI-graded Taint/Tabor and Tense would largely conform while lower Zorba/mixed lots would not; a harsher 25% is a sensible sensitivity.

### `qco_stress_rejected_loss_frac`

- **Value:** 0.15
- **Unit:** frac_of_cif_value · **Flag:** ASSUMPTION
- **Source:** Desk scenario design
- **Verify:** **N/A** — scenario assumption
- **Justification:** Loss on each rejected tonne as a fraction of its CIF value: return/onward freight, re-export documentation, distressed resale discount to a third-country buyer. Combined with rejection 10% this is ~1.5% of cargo value before demurrage — deliberately smaller than the delay/demurrage leg, which is where 2023–2025 QCO frictions actually bit importers.

## `config/params/risk.yaml`

Owner: P4/P5 risk · 53 parameters · DIRECT 0, PROXY 0, ASSUMPTION 53.

| Key | Value | Unit | Flag | Verify |
|---|---|---|---|---|
| `var_garch_refit_frequency` | W-FRI | pandas_period_alias | ASSUMPTION | N/A |
| `var_garch_min_estimation_obs` | 250 | trading_days | ASSUMPTION | N/A |
| `var_hist_window_base_days` | 250 | trading_days | ASSUMPTION | N/A |
| `var_hist_window_fast_days` | 60 | trading_days | ASSUMPTION | N/A |
| `var_corr_window_days` | 250 | trading_days | ASSUMPTION | N/A |
| `var_vol_alert_percentiles` | [0.75, 0.9, 0.95] | frac_percentile | ASSUMPTION | N/A |
| `var_vol_alert_reference_period` | ["2019-01-02", "2021-12-31"] | date_range_inclusive | ASSUMPTION | N/A |
| `var_lead_episodes` | [["LME_MARCH_SPIKE", "2022-01-03", "2022-03-31"], ["LME_MAY_JULY_CR... | name_start_end | ASSUMPTION | N/A |
| `var_unit_backtest_start` | 2019-01-02 | date | ASSUMPTION | N/A |
| `var_unit_lme_mt` | 1000.0 | mt | ASSUMPTION | N/A |
| `var_unit_fx_usd` | 1000000.0 | usd | ASSUMPTION | N/A |
| `mc_horizon_bdays` | 10 | business_days | ASSUMPTION | N/A |
| `mc_pit_lookback_days` | 126 | trading_days | ASSUMPTION | N/A |
| `mc_student_t_dof` | 5 | degrees_of_freedom | ASSUMPTION | N/A |
| `mc_snapshot_rules` | [["ATH_PLUS_1", "first LME panel day after the window's highest LME... | id_rule | ASSUMPTION | N/A |
| `mc_stress_lme_move_frac` | -0.15 | frac_of_lme_cash | ASSUMPTION | N/A |
| `mc_stress_usdinr_move_frac` | 0.05 | frac_of_usdinr | ASSUMPTION | N/A |
| `mc_buyer_default_buyer_id` | BUY_RJK_01 | counterparty_id | ASSUMPTION | N/A |
| `mc_buyer_default_recovery_frac` | 0.25 | frac_of_receivable | ASSUMPTION | **PENDING** |
| `mc_buyer_default_recovery_sensitivity_frac` | [0.0, 0.5] | frac_of_receivable | ASSUMPTION | N/A |
| `mc_buyer_default_resale_discount_frac` | 0.05 | frac_of_replacement_value | ASSUMPTION | N/A |
| `mc_qco_uncleared_only` | True | bool | ASSUMPTION | N/A |
| `liq_plan_parity_week_end` | 2022-02-25 | date | ASSUMPTION | N/A |
| `liq_plan_throughput_mt_pa` | 30000.0 | mt_per_year | ASSUMPTION | N/A |
| `liq_plan_lc_tenor_days` | 60 | days | ASSUMPTION | N/A |
| `liq_facility_rounding_inr` | 250000000.0 | inr | ASSUMPTION | N/A |
| `liq_fb_wc_limit_inr` | 1000000000.0 | inr | ASSUMPTION | **PENDING** |
| `liq_nfb_lc_limit_inr` | 1000000000.0 | inr | ASSUMPTION | **PENDING** |
| `liq_min_cash_buffer_frac_of_fb_limit` | 0.15 | frac_of_fund_based_limit | ASSUMPTION | N/A |
| `liq_stress_confidence_frac` | 0.99 | frac_percentile | ASSUMPTION | N/A |
| `liq_stress_horizon_days` | 10 | trading_days | ASSUMPTION | N/A |
| `policy_memo_date` | 2022-11-07 | date | ASSUMPTION | N/A |
| `policy_max_physical_open_mt` | 5000.0 | mt_lme_equivalent | ASSUMPTION | N/A |
| `policy_max_physical_open_usd` | 15000000.0 | usd | ASSUMPTION | N/A |
| `policy_max_net_unhedged_mt` | 1000.0 | mt_lme_equivalent | ASSUMPTION | N/A |
| `policy_max_net_unhedged_usd` | 3000000.0 | usd | ASSUMPTION | N/A |
| `policy_max_unhedged_frac` | 0.25 | frac_of_physical_lme_exposure | ASSUMPTION | N/A |
| `policy_unhedged_frac_min_physical_mt` | 1000.0 | mt_lme_equivalent | ASSUMPTION | N/A |
| `policy_mcx_hedge_ratio_band_frac` | [0.8, 1.1] | frac_of_lme_equivalent_physical_at_decision | ASSUMPTION | N/A |
| `policy_fx_forward_cover_min_frac` | 0.9 | frac_of_fixed_usd_payable | ASSUMPTION | N/A |
| `policy_stop_ticket_review_inr` | 10000000.0 | inr_drawdown_from_ticket_peak | ASSUMPTION | N/A |
| `policy_stop_ticket_hard_inr` | 20000000.0 | inr_drawdown_from_ticket_peak | ASSUMPTION | N/A |
| `policy_stop_book_drawdown_inr` | 40000000.0 | inr_drawdown_from_book_peak | ASSUMPTION | N/A |
| `policy_var_limit_inr` | 10000000.0 | inr_one_day_95pct_var | ASSUMPTION | N/A |
| `policy_freight_fix_within_bdays` | 10 | trading_days_after_purchase | ASSUMPTION | N/A |
| `policy_freight_stop_max_frac_over_fixture` | 0.2 | frac_above_fixture_rate | ASSUMPTION | N/A |
| `sent_vader_pos_threshold` | 0.05 | vader_compound_score | ASSUMPTION | N/A |
| `sent_vader_neg_threshold` | -0.05 | vader_compound_score | ASSUMPTION | N/A |
| `sent_zscore_min_past_weeks` | 4 | weeks | ASSUMPTION | N/A |
| `sent_signal_z_abs` | 1.0 | z_score_abs | ASSUMPTION | N/A |
| `sent_bootstrap_block_weeks` | 3 | weeks | ASSUMPTION | N/A |
| `sent_domain_valence_abs` | 1.5 | vader_valence_points | ASSUMPTION | N/A |
| `sent_domain_lexicon` | {"up": ["surge", "surges", "surged", "surging", "soar", "soars", "s... | word_lists_price_direction | ASSUMPTION | N/A |

### `var_garch_refit_frequency`

- **Value:** W-FRI
- **Unit:** pandas_period_alias · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice (docs/40_var_garch.md §2.2)
- **Verify:** **N/A** — modelling choice, nothing external to verify against
- **Justification:** GARCH(1,1) parameters are re-estimated once per week (weeks ending Friday, the project calendar convention in CONTRACTS §3) on an expanding sample of every return dated strictly before the first panel day of that week. Inside the week the parameters are held and the variance recursion is filtered daily, so the forecast for day t always uses returns dated t-1 or earlier. Weekly rather than daily refits keep the run light on this 8 GB machine; with 250+ observations one extra week moves the estimates very little, whereas the daily filter carries the information that matters (yesterday's squared return).

### `var_garch_min_estimation_obs`

- **Value:** 250
- **Unit:** trading_days · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice; roughly one year of LME trading days (docs/40_var_garch.md §2.2)
- **Verify:** **N/A** — modelling choice
- **Justification:** No GARCH forecast is produced until the expanding sample holds at least this many daily returns. With the lookback starting at HISTORY_START (2018-01-02) the first forecast falls on the last days of December 2018, so the 2019-2022 unit-exposure backtest starts with every method available. One year is the smallest sample on which a three-parameter GARCH is usually identified; the 2018-only USD/INR fit still hits the alpha = 0 / beta = 1 boundary, which var_garch_params.csv flags on every affected refit.

### `var_hist_window_base_days`

- **Value:** 250
- **Unit:** trading_days · **Flag:** ASSUMPTION
- **Source:** Basel market-risk convention of an (at least) one-year observation period for VaR; desk modelling choice
- **Verify:** **N/A** — declared before any Phase 4 result was computed (2026-09-16)
- **Justification:** The BASE 'simple historical volatility' against which GARCH is compared: the root-mean-square of the last 250 daily returns ending the day before the forecast date (zero mean, like the GARCH). Chosen ex ante as the one-year window a desk or regulator would use, NOT because it lags; var_hist_window_fast_days is published beside it in every table so a reader can see GARCH against a fast window too. Also the window for the freight and LME cash-3M spread volatilities, which are historical in both methods.

### `var_hist_window_fast_days`

- **Value:** 60
- **Unit:** trading_days · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice (about one quarter of trading days)
- **Verify:** **N/A** — declared before any Phase 4 result was computed (2026-09-16)
- **Justification:** The fast historical window reported next to the base in every table, chart and Kupiec row. It is the honest counterpart to the base: a 60-day window reacts much faster than 250 days, so any GARCH lead measured against it is the conservative reading.

### `var_corr_window_days`

- **Value:** 250
- **Unit:** trading_days · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice (docs/40_var_garch.md §2.4)
- **Verify:** **N/A** — modelling choice
- **Justification:** Rolling Pearson correlation of daily factor changes (LME cash log return, USD/INR log return, USEC freight log return, LME cash-3M spread change) over the 250 panel days ending the day before the VaR date. The SAME correlation matrix is used by both vol methods, so the GARCH-vs-historical comparison isolates the volatility forecast. Freight is assessed weekly and carried forward (CONTRACTS §3), so its daily correlations are attenuated; freight is immaterial to this book's VaR (docs/40 §4.2).

### `var_vol_alert_percentiles`

- **Value:** [0.75, 0.9, 0.95]
- **Unit:** frac_percentile · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice for the lead/lag reading (docs/40_var_garch.md §5)
- **Verify:** **N/A** — modelling choice; 0.90 is the base, the others are robustness rows
- **Justification:** A method 'flags rising risk' on the first day its volatility forecast rises above the given percentile of ITS OWN forecasts over var_vol_alert_reference_period (a pre-2022 period, so the thresholds contain no 2022 data). Each method is measured against its own distribution because a 250-day window is smoother than GARCH and would otherwise be judged against a bar it can never reach. 0.90 is the base threshold quoted in the finding.

### `var_vol_alert_reference_period`

- **Value:** ["2019-01-02", "2021-12-31"]
- **Unit:** date_range_inclusive · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice (docs/40_var_garch.md §5)
- **Verify:** **N/A** — modelling choice
- **Justification:** The three calendar years of forecasts that define each method's alert thresholds. Ends before 2022 so no threshold is informed by the February-March 2022 spike, the 7-March-2022 all-time high or the crash it is used to date.

### `var_lead_episodes`

- **Value:** [["LME_MARCH_SPIKE", "2022-01-03", "2022-03-31"], ["LME_MAY_JULY_CRASH", "2022-04-01", "2022-07-15"]]
- **Unit:** name_start_end · **Flag:** ASSUMPTION
- **Source:** Reporting-only search windows around the dated events in outputs/tables/adverse_event_windows.csv
- **Verify:** **N/A** — reporting convention; no VaR or backtest number depends on these windows
- **Justification:** Where the lead/lag table looks for each method's first alert. Episode 1 runs up to and through the 7-Mar-2022 all-time high; episode 2 runs from the start of April to the E1 trough (2022-07-15), which contains the E1 crash fortnight 2022-04-22 -> 2022-05-09. Like the P3 event windows these are drawn after the fact and are REPORTING-ONLY: they select which dates to describe, never an input to a forecast. If a method is already above its threshold when a window opens, the table reports the day that spell began instead of inventing a crossing.

### `var_unit_backtest_start`

- **Value:** 2019-01-02
- **Unit:** date · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice (spec Table 6 row 4.1 asks for a Kupiec test; ~120 book days have low power)
- **Verify:** **N/A** — modelling choice
- **Justification:** First forecast date of the constant-exposure backtests, which run to PANEL_END (2022-12-30). These exist because 120 book days cannot tell a good VaR from a bad one (Kupiec does not reject anything from 2 to 11 exceptions at n = 120); roughly 1,000 days of a fixed exposure narrow that band to 38-64 exceptions against 50.5 expected.

### `var_unit_lme_mt`

- **Value:** 1000.0
- **Unit:** mt · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice: a round long LME position, not a trade
- **Verify:** **N/A** — modelling choice
- **Justification:** Constant long LME aluminium cash position for the unit backtest. P&L on day t = qty x (cash_t - cash_t-1) x usdinr_t (the USD move converted at the day's rate); VaR = 1.645 x sigma_t x qty x cash_t-1 x usdinr_t-1. The size is irrelevant to exception counts; it only sets the rupee scale of the chart.

### `var_unit_fx_usd`

- **Value:** 1000000.0
- **Unit:** usd · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice: a round long-USD position, not a trade
- **Verify:** **N/A** — modelling choice
- **Justification:** Constant long USD position against INR for the USD/INR unit backtest (the second GARCH series used in the book VaR). P&L = notional x (usdinr_t - usdinr_t-1); VaR = 1.645 x sigma_t x notional x usdinr_t-1.

### `mc_horizon_bdays`

- **Value:** 10
- **Unit:** business_days · **Flag:** ASSUMPTION
- **Source:** Basel market-risk convention of a 10-business-day holding period; desk modelling choice (docs/41_monte_carlo.md §2.3)
- **Verify:** **N/A** — declared before any Phase 4.2 result was computed (2026-09-16)
- **Justification:** The base risk horizon: the covariance of daily factor changes is scaled by 10 (square root of time, no autocorrelation) and the book is re-marked instantaneously at the snapshot close with the clock, contracts and events held. Ten business days is roughly the time a physical desk needs to re-hedge or re-sell a cargo-sized position (an MCX hedge can be lifted in a day; a sale to a new smelter takes one to two weeks). A static-position "to settlement" horizon is also published, as a memo only, because the desk did not hold any snapshot position unchanged to settlement.

### `mc_pit_lookback_days`

- **Value:** 126
- **Unit:** trading_days · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice: the number of daily returns in the spec's estimation window (2022-03-01..2022-08-31 has 126 LME days)
- **Verify:** **N/A** — modelling choice
- **Justification:** Length of the POINT-IN-TIME covariance sensitivity: the 126 daily changes dated on or before each snapshot date (and the complete W-FRI weeks inside that span for freight and the MCX basis). The spec's window covariance uses returns after an early snapshot (hindsight); this variant uses only what the desk knew at that close. Same length as the window so the two differ only in dating.

### `mc_student_t_dof`

- **Value:** 5
- **Unit:** degrees_of_freedom · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice (docs/41_monte_carlo.md §2.4); common choice for commodity-return tails
- **Verify:** **N/A** — modelling choice
- **Justification:** Degrees of freedom of the multivariate Student-t sensitivity, scaled to the SAME covariance as the base normal (x = L z sqrt((nu-2)/chi2)). One chi-square per path scales all factors together: a normal whose variance is uncertain over the horizon. At equal variance nu = 5 puts the one-factor 95 % quantile 5 % BELOW the normal's, the 99 % quantile 12 % above it and the 99.9 % quantile 48 % above it.

### `mc_snapshot_rules`

- **Value:** [["ATH_PLUS_1", "first LME panel day after the window's highest LME cash close (the 7-Mar-2022 all-time high)"], ["PEAK_GROSS_LME", "window day with the largest BOOK lme_delta_physical_mt in book_exposures_daily.csv"], ["PEAK_BUYER_CONTRACTED", "first window day on which mc_buyer_default_buyer_id's contracted exposure (receivable + presettlement, buyer_credit_exposure_by_trade_daily.csv) is at its window maximum"]]
- **Unit:** id_rule · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice, declared before any Phase 4.2 result was computed (2026-09-16); docs/41_monte_carlo.md §2.2
- **Verify:** **N/A** — modelling choice
- **Justification:** Three dates on which the book is revalued. Any date a rule selects that is an MCX exit or roll-out day (mcx_variation_margin.csv action exit|roll_out) moves to the next panel day that is not one, because the valuation at such a close still carries the exiting contract (docs/40_var_garch.md open issue 1). ATH_PLUS_1 is the spec's crash narrative (and the book's first day: T01 long, not yet hedged); PEAK_GROSS_LME is the most metal the desk ever carried, where hedge slippage matters most; PEAK_BUYER_CONTRACTED is the day the buyer-default stress has the most to bite on. The rules select dates from exposures and credit tables only, never from P&L.

### `mc_stress_lme_move_frac`

- **Value:** -0.15
- **Unit:** frac_of_lme_cash · **Flag:** ASSUMPTION
- **Source:** MASTER_SPEC_V3 Table 6 row 4.2 stress scenario 'LME -15%'
- **Verify:** **N/A** — spec-defined scenario
- **Justification:** Instantaneous LME cash x 0.85 (log shock ln 0.85), with MCX recomputed from the shocked cash at the held basis (unit beta, docs/30 §5.1). For scale: LME cash fell 12.95 % on 8-Mar-2022 alone.

### `mc_stress_usdinr_move_frac`

- **Value:** 0.05
- **Unit:** frac_of_usdinr · **Flag:** ASSUMPTION
- **Source:** MASTER_SPEC_V3 Table 6 row 4.2 stress scenario 'INR -5%'
- **Verify:** **N/A** — spec-defined scenario
- **Justification:** Convention: 'INR -5 %' is read as the quoted USD/INR rate rising 5 % (rupee depreciation; log shock ln 1.05) — the way an Indian desk quotes the move. Measured as the rupee's own USD value it is a 4.76 % fall; a 5 % fall in that measure would be USD/INR +5.26 %. The CBIC customs rate moves with the market rate (valuation.shock_state).

### `mc_buyer_default_buyer_id`

- **Value:** BUY_RJK_01
- **Unit:** counterparty_id · **Flag:** ASSUMPTION
- **Source:** Phase 1-3 fix log open item 1 (docs/reviews/phase1-3_fix_log.md §3): advance reliance 1.26x/1.53x/1.83x of a ₹120 m limit; contracted exposure peaks at 2.57x
- **Verify:** **N/A** — scenario design
- **Justification:** The buyer defaulted in the Table 6 'buyer default' stress. Chosen for performance exposure relative to its limit (the desk relies on its advances), not for the largest rupee exposure: BUY_MUN_01's contracted exposure peaks higher in rupees (₹750 m on a ₹650 m limit). The stress is run on every snapshot; where this buyer has no open flow the scenario is zero and says so.

### `mc_buyer_default_recovery_frac`  — **PENDING**

- **Value:** 0.25
- **Unit:** frac_of_receivable · **Flag:** ASSUMPTION
- **Source:** Desk judgement: unsecured operational creditor of a defaulted small foundry (SIM)
- **Verify:** **PENDING** — compare with published realisation rates for operational creditors in Indian insolvency resolutions (IBBI quarterly newsletter)
- **Justification:** Recovery on cargo already RELEASED to the buyer when it defaults (an unsecured trade receivable, no retention of title assumed). Operational creditors rank behind secured lenders and typically recover a small fraction, late; 0.25 is a judgement, so mc_buyer_default_recovery_sensitivity_frac publishes the 0 and 0.5 cases beside it.

### `mc_buyer_default_recovery_sensitivity_frac`

- **Value:** [0.0, 0.5]
- **Unit:** frac_of_receivable · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice
- **Verify:** **N/A** — sensitivity grid
- **Justification:** Memo rows of the buyer-default scenario at these recoveries on released cargo (retained cargo is unaffected).

### `mc_buyer_default_resale_discount_frac`

- **Value:** 0.05
- **Unit:** frac_of_replacement_value · **Flag:** ASSUMPTION
- **Source:** Desk judgement: distressed resale of an imported scrap lot to another Gujarat smelter within weeks
- **Verify:** **N/A** — scenario assumption (no public quote for distressed domestic scrap resales)
- **Justification:** Cargo NOT yet released when the buyer defaults stays with the desk and is resold at the unsold-cargo mark (import replacement value, CONTRACTS §7a.1.3) less this discount. The loss is the lost contract receipts minus those resale proceeds, floored at zero (no windfall from a default). Extra storage while re-selling is not modelled.

### `mc_qco_uncleared_only`

- **Value:** True
- **Unit:** bool · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice; a clearance-stage BIS-QCO bites at the Bill of Entry (regulatory.yaml qco_stress_delay_days note)
- **Verify:** **N/A** — modelling choice
- **Justification:** Apply StressEvent('qco_hold') only to tickets on the book with at least one lot not yet released at the snapshot. The API charges extra dwell on every box of a ticket and writes off the rejected fraction of its unsold (or, if all sold, whole) tonnage regardless of lot status; applied to already-cleared tickets that overstates the policy stress, so the all-tickets figure is published only as a memo row.

### `liq_plan_parity_week_end`

- **Value:** 2022-02-25
- **Unit:** date · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice: the last Phase 1 parity week before WINDOW_START (outputs/tables/parity_weekly.csv)
- **Verify:** **N/A** — modelling choice
- **Justification:** The facilities are sized as a bank would size them at sanction — before the window opened, on the prices and cash-cycle economics visible then: the six grade x lane cases of the parity week ending 2022-02-25. Nothing dated after that week enters the sizing. Carried caveat: that week's grade factor and freight level are Phase 1 hindsight reconstructions (CONTRACTS §4.3), so the plan cost per tonne is itself partly reconstructed; margin_liquidity_limit_grid.csv shows the result at other facility sizes.

### `liq_plan_throughput_mt_pa`

- **Value:** 30000.0
- **Unit:** mt_per_year · **Flag:** ASSUMPTION
- **Source:** Desk plan read from MASTER_SPEC_V3 Table 4 (8-10 trades of 1,000-5,000 MT over the six-month window)
- **Verify:** **N/A** — business-plan assumption
- **Justification:** A first-year desk planning at the lower middle of the spec's range (about 9 parcels of ~1,700 MT a half-year) budgets ~15,000 MT per half-year, i.e. 30,000 MT a year (2,500 MT a month). Taken from the spec range, not from the book: the realised book (14,350 MT contracted Mar-Aug, ~2,390 MT a month) came in about 4 % under it, so the facility test is about the book's cash TIMING (usance maturities, IGST, buyer credit bunching), not its volume.

### `liq_plan_lc_tenor_days`

- **Value:** 60
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk construction from lc_open_days_before_laycan_min (commercial.yaml), sight payment ~7 days after B/L, and 60-90 day usance
- **Verify:** **N/A** — plan assumption
- **Justification:** Average days one parcel's import LC sits on the non-fund limit in the plan. A sight LC is outstanding from opening (at least 10 days before the laycan) to document payment about 7 days after the B/L, roughly 25-30 days; a usance LC adds its 60-90 days. A plan that puts about a third of parcels on 90-day usance averages ~60 days. The book used usance on 3 of 9 parcels (T02 90 d, T05 60 d, T09 60 d).

### `liq_facility_rounding_inr`

- **Value:** 250000000.0
- **Unit:** inr · **Flag:** ASSUMPTION
- **Source:** Desk convention: sanctioned limits are round numbers
- **Verify:** **N/A** — convention
- **Justification:** Each plan requirement is rounded UP to the next ₹25 crore (₹250 m) to give the sanctioned limit. Rounding can only add headroom: on the 2022-02-25 plan it adds ₹30.2 m to the fund-based line and ₹126.8 m to the LC line.

### `liq_fb_wc_limit_inr`  — **PENDING**

- **Value:** 1000000000.0
- **Unit:** inr · **Flag:** ASSUMPTION
- **Source:** Desk construction: liq_plan_throughput_mt_pa x mean over the plan week's six parity cases of (finance_inr_t + igst_finance_inr_t) / wc_rate_inr_pa, rounded up by liq_facility_rounding_inr
- **Verify:** **PENDING** — no 2022 sanction letter for a comparable importer was retrieved. Next step: a listed Indian non-ferrous metals trader's FY2022-23 annual report (sanctioned fund-based working-capital limits against turnover).
- **Justification:** Sanctioned fund-based working-capital limit (cash credit / WCDL / import loans on one line) — the line Phase 3's funding accrual already assumes (CONTRACTS §7a.5) but never capped. Rule: 30,000 MT/yr x ₹32,326 of funded rupee-years per tonne (Phase 1's own finance_inr_t + igst_finance_inr_t at the 9.50 % plan rate) = ₹969.8 m average funded balance, rounded up to ₹1,000 m (₹100 crore); margin_liquidity_facility.csv recomputes it and a test asserts the registered value equals the rule. It is a sanction on the plan's AVERAGE balance, as a holding-period assessment would give; a parcel business is lumpy, and the buffer below plus an ad-hoc limit are what a bank expects to carry peaks. It was not set from the book's realised peak funding need.

### `liq_nfb_lc_limit_inr`  — **PENDING**

- **Value:** 1000000000.0
- **Unit:** inr · **Flag:** ASSUMPTION
- **Source:** Desk construction: liq_plan_throughput_mt_pa x mean plan-week CIF value per tonne (cif_usd_t x usdinr) x liq_plan_lc_tenor_days / 365, rounded up by liq_facility_rounding_inr
- **Verify:** **PENDING** — as liq_fb_wc_limit_inr
- **Justification:** Non-fund import LC limit (sight and usance credits outstanding). Rule: 30,000 MT/yr x ₹177,064 CIF per tonne x 60/365 = ₹873.2 m average LC outstanding, rounded up to ₹1,000 m. The book's LC outstanding is valued at the trade-date planned purchase value x (1 + the ticket's LC tolerance), converted at each day's USD/INR (PROXY).

### `liq_min_cash_buffer_frac_of_fb_limit`

- **Value:** 0.15
- **Unit:** frac_of_fund_based_limit · **Flag:** ASSUMPTION
- **Source:** Treasury convention: keep 10-20 % of committed working-capital lines undrawn for margin calls and payment slippage; midpoint
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Minimum undrawn liquidity reserved at all times: headroom = limit − buffer − funding need, so a buffer you can spend is not counted as headroom. ₹150 m on the ₹1,000 m line. Anchor at plan prices: initial margin at mcx_al_margin_used_frac (10 %) on two months of plan throughput (5,000 MT) hedged 1:1 at the 25-Feb-2022 MCX M1 proxy (₹273.24/kg) is ₹136.6 m. The analysis tests this against a daily 99 % margin-at-risk; the memo's buffer rule is set from that test, not from this convention.

### `liq_stress_confidence_frac`

- **Value:** 0.99
- **Unit:** frac_percentile · **Flag:** ASSUMPTION
- **Source:** MASTER_SPEC_V3 Table 6 row 4.2 (the Monte Carlo reports 95 %/99 % losses); desk modelling choice
- **Verify:** **N/A** — modelling choice
- **Justification:** Confidence of the adverse LME move used for margin-at-risk and the crash-fortnight stress. A liquidity buffer is sized for the tail, so 99 % rather than the 95 % of the daily VaR.

### `liq_stress_horizon_days`

- **Value:** 10
- **Unit:** trading_days · **Flag:** ASSUMPTION
- **Source:** CONTRACTS §7a.3 fortnight convention (10 trading-day returns); equals mc_horizon_bdays of the Phase 4.2 Monte Carlo
- **Verify:** **N/A** — modelling choice
- **Justification:** Horizon of the 99 % move: one crash fortnight. Normal readings scale a one-day volatility forecast by sqrt(10) (no mean reversion, no autocorrelation); the empirical reading uses overlapping 10-day LME cash log returns from HISTORY_START to the stress date, so it needs no scaling.

### `policy_memo_date`

- **Value:** 2022-11-07
- **Unit:** date · **Flag:** ASSUMPTION
- **Source:** Desk convention: the first Monday after HORIZON_END (2022-10-31), when every figure the memo quotes is known
- **Verify:** **N/A** — convention
- **Justification:** The memo proposes policy looking back over the whole book (its cash path runs to 31-Oct and the credit scores to 31-Aug), so it is dated after the last input it uses: no figure in it was unknowable on its date.

### `policy_max_physical_open_mt`

- **Value:** 5000.0
- **Unit:** mt_lme_equivalent · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence book_exposures_daily.csv (BOOK lme_delta_physical_mt, unsold_mt)
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Gross physical LME exposure (priced-or-unpriced metal the desk is long before hedges). Set at the spec's maximum parcel (5,000 MT), which is also just above what the book ran (peak 4,450 MT LME-equivalent on 21-Apr; unsold cargo peaked at 4,980 MT on 6-Apr). Not raised above that level because the liquidity analysis shows this level already used the whole working-capital line. Disclosure: the level was chosen with the book's peak in view, so the memo's "within" verdict is true by construction and is not evidence that the limit is right.

### `policy_max_physical_open_usd`

- **Value:** 15000000.0
- **Unit:** usd · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence BOOK lme_delta_physical_mt x lme_cash_usd_t
- **Verify:** **N/A** — desk policy assumption
- **Justification:** The same limit in dollars, so a price rally cannot grow exposure inside a tonnage limit. Book peak USD 14.5 m on 21-Apr-2022 (4,450 MT x LME cash 3,262). Set just above that peak with the book in view (see the MT twin).

### `policy_max_net_unhedged_mt`

- **Value:** 1000.0
- **Unit:** mt_lme_equivalent · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence BOOK lme_delta_mt (net of MCX), excluding the 16 MCX exit/roll position dates flagged in var_daily.csv
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Absolute net LME delta after hedges, long or short. At window LME cash prices (USD 2,320-3,985/t) 1,000 MT is USD 2.3-4.0 m. The book's absolute net had a 95th percentile of 967 MT on clean position days; it exceeded 1,000 MT on 5 of them, the largest the 1,817 MT naked session on 8-Mar before T01's hedge (MCX proxy at its daily limit).

### `policy_max_net_unhedged_usd`

- **Value:** 3000000.0
- **Unit:** usd · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence BOOK lme_delta_usd
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Dollar twin of policy_max_net_unhedged_mt (about 1,000 MT at USD 3,000/t). Book: above USD 3 m on 2 clean days (8-Mar USD 6.36 m; 14-Apr).

### `policy_max_unhedged_frac`

- **Value:** 0.25
- **Unit:** frac_of_physical_lme_exposure · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence BOOK lme_delta_mt / lme_delta_physical_mt
- **Verify:** **N/A** — desk policy assumption
- **Justification:** |net| / gross physical, checked daily when gross physical is at least policy_unhedged_frac_min_physical_mt. Symmetric: over-hedging (net short) counts. The book's median hedge ratio was 0.903, but ratios drift between re-sizing decisions, so the book was outside 25 % on 26 of 99 qualifying clean days. The remedy is a rebalancing rule, not a looser band.

### `policy_unhedged_frac_min_physical_mt`

- **Value:** 1000.0
- **Unit:** mt_lme_equivalent · **Flag:** ASSUMPTION
- **Source:** Desk policy
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Below this gross physical exposure the percentage test is not applied (a 20 % miss on 300 MT is noise; the absolute net limit still binds).

### `policy_mcx_hedge_ratio_band_frac`

- **Value:** [0.8, 1.1]
- **Unit:** frac_of_lme_equivalent_physical_at_decision · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence trade_hedges.csv hedge_ratio_target / hedge_ratio_actual per ticket
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Hedge ratio each ticket must be sized to at every MCX decision (entry, roll, tranche). Eight tickets targeted 0.9 or 1.0 and filled within 0.899-1.002; T04's deliberate 0.50 is outside and would need prior committee approval. The upper bound allows for the MCX lot rounding and the 5.4-5.5 MT LME-equivalent per 5 MT lot.

### `policy_fx_forward_cover_min_frac`

- **Value:** 0.9
- **Unit:** frac_of_fixed_usd_payable · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence trade_book.csv fx_hedge_frac_target, fx_cover_frac_of_fixed_purchase
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Minimum forward cover of each fixed USD payable from the day it is fixed, measured on physical + forwards only (the MCX short's embedded USD must not be netted in: docs/40 §4.2, fix log open item 3). Eight tickets covered 100 %; T06 covered 60 %.

### `policy_stop_ticket_review_inr`

- **Value:** 10000000.0
- **Unit:** inr_drawdown_from_ticket_peak · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence attribution_daily.csv per-ticket cum_pnl_inr drawdowns
- **Verify:** **N/A** — desk policy assumption
- **Justification:** A ticket whose cumulative P&L falls ₹10 m below its own peak goes to a same-day review with the head of desk (about 2.3x the book's mean daily GARCH VaR, ₹4.27 m). Four of nine tickets would have triggered it (T04, T05, T07, T08). Chosen after the drawdowns were known: which tickets trip is illustration, not a test of the level.

### `policy_stop_ticket_hard_inr`

- **Value:** 20000000.0
- **Unit:** inr_drawdown_from_ticket_peak · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence attribution_daily.csv per-ticket drawdowns
- **Verify:** **N/A** — desk policy assumption
- **Justification:** At ₹20 m below peak the ticket is hedged to 1.0 on MCX and forwards and no new exposure in the same grade is added until it closes. Only T08 reached it (−₹22.8 m on 1-Aug, worst −₹26.1 m on 8-Aug, mostly grade spread), and the desk bought T09 in the same grade on 3-Aug. Disclosure: the level sits where only the worst ticket trips, and it was set with the book's drawdowns in view.

### `policy_stop_book_drawdown_inr`

- **Value:** 40000000.0
- **Unit:** inr_drawdown_from_book_peak · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence attribution_daily.csv BOOK cum_pnl_inr
- **Verify:** **N/A** — desk policy assumption
- **Justification:** At ₹40 m below the book's peak (about ten times the mean daily GARCH VaR) no new purchase is contracted until the committee has reviewed the book. The book drew down ₹49.9 m from its 9-Jun peak to 8-Aug, crossing ₹40 m on 1-Aug; T09 was contracted on 3-Aug. Set with that drawdown in view (a disclosure, not a validation).

### `policy_var_limit_inr`

- **Value:** 10000000.0
- **Unit:** inr_one_day_95pct_var · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence var_daily.csv (docs/40_var_garch.md)
- **Verify:** **N/A** — desk policy assumption
- **Justification:** One-day 95 % VaR limit applied to the larger of the GARCH(1,1) VaR and the 250-day historical VaR (the historical number is the floor, because GARCH decayed below both rolling windows into the April-May crash). ₹10 m is 2.3x the mean GARCH VaR (₹4.27 m). On clean position days the book breached it once: ₹43.5 m on 9-Mar, the naked session. Scope: the VaR covers LME, USD/INR and freight only. Grade-spread P&L (daily std ₹2.2 m over the window, not a VaR factor) and the LME cash-3M spread (memo VaR +18 %) sit outside the limit (docs/40 §4.2, §6.1).

### `policy_freight_fix_within_bdays`

- **Value:** 10
- **Unit:** trading_days_after_purchase · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence trade_book.csv trade_date vs freight_fixture_date on the three FOB tickets
- **Verify:** **N/A** — desk policy assumption
- **Justification:** FOB purchases fix freight within 10 trading days of the purchase. T01 fixed after 8, T04 after 6, T07 after 2.

### `policy_freight_stop_max_frac_over_fixture`

- **Value:** 0.2
- **Unit:** frac_above_fixture_rate · **Flag:** ASSUMPTION
- **Source:** Desk policy; evidence trade_book.csv freight_stop_loss_usd_box vs freight_rate_usd_box
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Unhedged freight carries a stated stop no more than 20 % above the fixture (the book's stops were 18.4 %, 12.7 % and 14.2 % above). No proxy hedge: no accessible instrument tracks the India lanes (Table 4 row 2.7(d) note), the two lanes are one factor (JEA_NSA = 0.2255 x USEC_MUN), freight VaR averaged ₹0.05 m, and the hypothetical +40 % spike costs T01 ₹8.55 m (docs/31 §3.5).

### `sent_vader_pos_threshold`

- **Value:** 0.05
- **Unit:** vader_compound_score · **Flag:** ASSUMPTION
- **Source:** vaderSentiment 3.3.2 README (Hutto & Gilbert, ICWSM 2014): the authors' recommended cut-off, compound >= 0.05 = positive
- **Verify:** **N/A** — tool author's convention, adopted unchanged
- **Justification:** A headline counts toward a week's pos_share when its VADER compound score is at least this value. Adopted from the tool's documentation rather than chosen, so the share cannot have been tuned to prices. Applied identically to the raw and the domain-adjusted score.

### `sent_vader_neg_threshold`

- **Value:** -0.05
- **Unit:** vader_compound_score · **Flag:** ASSUMPTION
- **Source:** vaderSentiment 3.3.2 README (Hutto & Gilbert, ICWSM 2014): compound <= -0.05 = negative
- **Verify:** **N/A** — tool author's convention, adopted unchanged
- **Justification:** A headline counts toward a week's neg_share when its compound score is at most this value; scores strictly between the two thresholds are neutral. Most commodity headlines contain no VADER lexicon word at all and score exactly 0, so the neutral share is large and is published alongside.

### `sent_zscore_min_past_weeks`

- **Value:** 4
- **Unit:** weeks · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice (docs/70_sentiment_overlay.md §2.4)
- **Verify:** **N/A** — modelling choice
- **Justification:** A week's z-score compares its mean score with the mean and standard deviation of ALL EARLIER weeks only (expanding window, the week itself excluded from the reference), and is left blank until at least four earlier weeks exist. Four is the smallest reference that gives a standard deviation any stability while leaving 24 of the 28 weeks scored; it means no z-score exists for the weeks around the 7-Mar-2022 high, which the doc states rather than hides. No future week ever enters a z-score.

### `sent_signal_z_abs`

- **Value:** 1.0
- **Unit:** z_score_abs · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice (docs/70_sentiment_overlay.md §2.6)
- **Verify:** **N/A** — modelling choice, declared before any lead test was run
- **Justification:** The episode lead test records SIGNAL FIRED for a price turn if, in one of the three W-FRI weeks ending on or before the last close before the move, the past-only z-score pointed in the direction of the coming move by at least one standard deviation. (Wording corrected after the first run to match the code, which was written before any result; the earlier wording, "the three complete weeks before the week of the turn", is published as verdict_alt_window in sentiment_episodes.csv and gives the same verdicts.) One sigma is deliberately loose (a lenient test gives sentiment every chance); the table therefore also publishes the base rate, i.e. how often the same condition fired in all other weeks, without which a single hit means nothing.

### `sent_bootstrap_block_weeks`

- **Value:** 3
- **Unit:** weeks · **Flag:** ASSUMPTION
- **Source:** Desk modelling choice; moving-block bootstrap (Kunsch 1989) because weekly sentiment and returns are autocorrelated
- **Verify:** **N/A** — modelling choice
- **Justification:** Block length of the moving-block bootstrap behind the lead/lag correlation intervals. Resampling single weeks would treat autocorrelated weekly scores as independent and give intervals that are too narrow; three weeks is roughly n^(1/3) for n = 28 (the usual rate for block length) and matches the +/-3-week lag range.

### `sent_domain_valence_abs`

- **Value:** 1.5
- **Unit:** vader_valence_points · **Flag:** ASSUMPTION
- **Source:** vaderSentiment 3.3.2 vader_lexicon.txt: mean absolute valence of its 7,506 entries is 1.54 (median 1.6)
- **Verify:** **N/A** — computed from the installed lexicon file, rounded down
- **Justification:** The single valence (+1.5 bullish, -1.5 bearish) given to every word in sent_domain_lexicon. One magnitude for all words, set at the lexicon's typical word strength, so no individual weight could be tuned; rounded DOWN so a domain word never outweighs a typical VADER word.

### `sent_domain_lexicon`

- **Value:** {"up": ["surge", "surges", "surged", "surging", "soar", "soars", "soared", "soaring", "jump", "jumps", "jumped", "rally", "rallies", "rallied", "rallying", "rise", "rises", "rose", "rising", "climb", "climbs", "climbed", "climbing", "rebound", "rebounds", "rebounded", "bullish", "deficit", "deficits", "shortage", "shortages", "tight", "tighter", "tightness"], "down": ["slump", "slumps", "slumped", "plunge", "plunges", "plunged", "plunging", "tumble", "tumbles", "tumbled", "fall", "falls", "fell", "slide", "slides", "slid", "decline", "declines", "declined", "declining", "sink", "sinks", "sank", "slip", "slips", "slipped", "dip", "dips", "dipped", "drops", "dropped", "crashes", "crashed", "plummet", "plummets", "plummeted", "bearish", "glut", "gluts", "surplus", "surpluses", "oversupply", "slowdown", "soften", "softens", "softened", "softer"], "neutral": ["demand"]}
- **Unit:** word_lists_price_direction · **Flag:** ASSUMPTION
- **Source:** Desk judgement from standard metals market-report vocabulary; declared 2026-09-16 before any correlation with LME was computed; per-word reasons in docs/70_sentiment_overlay.md §2.3
- **Verify:** **N/A** — judgement; the doc publishes raw VADER next to the adjusted score so the adjustment can be ignored
- **Justification:** A small PRICE-DIRECTION overlay on VADER, which is a general social-media lexicon: it has no entry for surge, soar, rally, rise, plunge, slump, tumble, fall, decline or glut, and scores deficit (-1.7) and shortage (-1.0) as bad news although in a metals headline they are bullish for price. Rules: (1) only words whose price direction is the same in nearly all market-report usage; (2) inflections listed explicitly because VADER does not stem; (3) add a word only if VADER lacks it, or overwrite it only if VADER gives it the wrong sign for price (deficit, shortage, shortages; deficits is simply absent) or a tone that is not a price direction (demand -0.5 -> 0); words VADER already signs the right way (gain, drop, crash, falling, low, lower, weak, strong) are left alone; (4) deliberately NOT added because their price direction is ambiguous: war, sanctions, crisis, cut(s), curbs, halt, closure, hike(s), ease, cool, recovery (also a recycling term), high, record, peak, tightening (monetary). The overlay assumes the subject of the verb is price, so "LME stocks fall" is mis-scored bearish; the doc counts such cases.

## `config/params/risk_credit.yaml`

Owner: unassigned · 21 parameters · DIRECT 0, PROXY 0, ASSUMPTION 21.

| Key | Value | Unit | Flag | Verify |
|---|---|---|---|---|
| `credit_synth_base_default_rate_annual_frac` | 0.04 | frac_of_buyer_quarters_defaulting_within_12_months | ASSUMPTION | N/A |
| `credit_dgp_odds_ratio_utilisation_per_10pp` | 1.25 | odds_ratio_per_0.10_of_peak_credit_utilisation_over_the_quarter | ASSUMPTION | N/A |
| `credit_dgp_odds_ratio_dpd_per_10d` | 1.5 | odds_ratio_per_10_days_of_worst_days_past_due_over_trailing_12_months | ASSUMPTION | N/A |
| `credit_dgp_odds_ratio_history_per_12m` | 0.8 | odds_ratio_per_12_months_of_payment_history_with_the_desk | ASSUMPTION | N/A |
| `credit_dgp_odds_ratio_concentration_per_10pp` | 1.15 | odds_ratio_per_0.10_of_the_buyer's_annual_raw_material_spend_sourced_from_this_desk | ASSUMPTION | N/A |
| `credit_synth_gen_utilisation` | {"mean": 0.5, "weakness_loading": 0.15, "noise_sd": 0.2, "floor": 0... | mapping: peak credit utilisation frac = clip(mean + weakness_loading*w + noise_sd*e, floor, cap); w ~ N(0,1) per buyer, e ~ N(0,1) per quarter | ASSUMPTION | N/A |
| `credit_synth_gen_dpd` | {"p_late_logit_intercept": -0.3, "p_late_weakness_loading": 1.0, "l... | mapping: worst DPD days = 0 with prob 1-sigmoid(a+b*w), else ceil(Exponential(late_mean_days*exp(elasticity*w))) capped | ASSUMPTION | N/A |
| `credit_synth_gen_history` | {"median_months": 30.0, "log_sd": 0.7, "weakness_loading_log": -0.2... | mapping: months of history = clip(exp(log(median)+weakness_loading_log*w+log_sd*e_buyer) + months_per_quarter*quarter_index, floor, cap) | ASSUMPTION | N/A |
| `credit_synth_gen_concentration` | {"logit_intercept": -1.8, "weakness_loading": 0.5, "buyer_sd": 0.8,... | mapping: share of buyer raw-material spend from the desk = sigmoid(intercept + loading*w + buyer_sd*e_buyer + quarter_sd*e_quarter) | ASSUMPTION | N/A |
| `credit_feature_lookback_utilisation_days` | 91 | calendar_days | ASSUMPTION | N/A |
| `credit_feature_lookback_dpd_days` | 365 | calendar_days | ASSUMPTION | N/A |
| `credit_feature_lookback_concentration_days` | 365 | calendar_days | ASSUMPTION | N/A |
| `credit_band_pd_upper_frac` | {"A": 0.02, "B": 0.05, "C": 0.12} | annual_pd_frac_upper_bound_exclusive (D = everything at or above the C bound) | ASSUMPTION | N/A |
| `credit_performance_overlay_notches` | 1 | bands_downgraded | ASSUMPTION | N/A |
| `credit_soft_utilisation_frac` | 0.8 | frac_of_credit_limit_inr | ASSUMPTION | N/A |
| `credit_band_max_credit_utilisation_frac` | {"A": 1.0, "B": 0.9, "C": 0.75, "D": 0.5} | frac_of_credit_limit_inr | ASSUMPTION | N/A |
| `credit_band_max_advance_reliance_multiple` | {"A": 1.0, "B": 1.0, "C": 0.5, "D": 0.0} | multiple_of_credit_limit_inr | ASSUMPTION | N/A |
| `credit_band_limit_multiplier` | {"A": 1.0, "B": 1.0, "C": 1.0, "D": 0.5} | multiple_of_current_credit_limit_inr | ASSUMPTION | N/A |
| `credit_band_max_credit_days` | {"A": 45, "B": 30, "C": 30, "D": 0} | days | ASSUMPTION | N/A |
| `credit_band_review_frequency_days` | {"A": 180, "B": 90, "C": 30, "D": 7} | days_between_credit_reviews | ASSUMPTION | N/A |
| `credit_band_limit_action` | {"A": "MAINTAIN — eligible for a limit increase at the next review"... | text_by_band | ASSUMPTION | N/A |

### `credit_synth_base_default_rate_annual_frac`

- **Value:** 0.04
- **Unit:** frac_of_buyer_quarters_defaulting_within_12_months · **Flag:** ASSUMPTION
- **Source:** Judgement, bracketed by published Indian MSME bank-credit figures that are NOT the same measure: TransUnion CIBIL-SIDBI MSME Pulse (newsroom release 8-Aug-2022) reports an MSME NPA rate of 12.8 % in Mar-2022 (12.0 % Mar-2021), 20.8 % at public sector banks, 9.6 % at NBFCs and 5.6 % at private banks in FY22-Q4, and that ~70 % of 90+ DPD balances pertain to accounts originated up to Mar-2017 (https://newsroom.transunioncibil.com/msme-credit-disbursement-accelerates-while-credit-quality-stays-stable/).
- **Verify:** **N/A** — calibration assumption. The bureau figures quoted in `source` were read on 2026-09-16; no published 2022 annual default (flow) rate for 30-day supplier trade credit to Indian foundries or secondary smelters was found.
- **Justification:** Target mean 12-month default probability of the synthetic buyer-quarter population; the DGP intercept is solved so the population mean equals it. Chosen inside the 2-5 %/yr band the Phase 5 brief states, and deliberately well below the bureau NPA ratios because those are balance-weighted STOCK ratios on multi-year bank loans (dominated by pre-2017 vintages), whereas trade credit is 30-45 days, re-underwritten every parcel and cut off at the first missed payment, so its annual flow default rate should be lower. Bands are absolute PD cut-offs, so this number moves bands: the 2 % and 5 % variants are published in credit_scores_sensitivity.csv.

### `credit_dgp_odds_ratio_utilisation_per_10pp`

- **Value:** 1.25
- **Unit:** odds_ratio_per_0.10_of_peak_credit_utilisation_over_the_quarter · **Flag:** ASSUMPTION
- **Source:** Judgement (synthetic DGP). Direction from standard behavioural-scorecard practice: drawn/limit is among the strongest delinquency predictors.
- **Verify:** **N/A** — synthetic data-generating process, nothing to verify against
- **Justification:** +10 percentage points of peak credit utilisation multiplies default odds by 1.25, so running a line at 90 % rather than 30 % multiplies odds by ~3.8. A buyer that lives near its limit has no headroom when its own customers pay late. Credit utilisation is the desk's own limit definition (config/counterparties.yaml header, docs/20 rule C1): receivable plus the part of contracted-not-invoiced sales an advance does not cover, over the credit limit. It deliberately EXCLUDES advances still owed (see docs/50_credit_scoring.md §3.2 for why advance reliance is an overlay, not part of this feature).

### `credit_dgp_odds_ratio_dpd_per_10d`

- **Value:** 1.5
- **Unit:** odds_ratio_per_10_days_of_worst_days_past_due_over_trailing_12_months · **Flag:** ASSUMPTION
- **Source:** Judgement (synthetic DGP). Past delinquency is the most widely used behavioural default predictor in trade-credit and bureau scorecards.
- **Verify:** **N/A** — synthetic data-generating process, nothing to verify against
- **Justification:** Each 10 days of worst delinquency in the last 12 months multiplies default odds by 1.5 (0 to 37 days: ~x4.5). Set as the strongest per-unit driver because a missed due date is the one feature that is an observed payment failure rather than a circumstance.

### `credit_dgp_odds_ratio_history_per_12m`

- **Value:** 0.8
- **Unit:** odds_ratio_per_12_months_of_payment_history_with_the_desk · **Flag:** ASSUMPTION
- **Source:** Judgement (synthetic DGP). Thin-file / new-relationship names default more often in trade-credit portfolios.
- **Verify:** **N/A** — synthetic data-generating process, nothing to verify against
- **Justification:** Each extra year of payment history with the desk multiplies default odds by 0.8 (12 to 48 months: ~x0.45). Deliberately the weakest effect: a long history is survivorship evidence, not a balance sheet.

### `credit_dgp_odds_ratio_concentration_per_10pp`

- **Value:** 1.15
- **Unit:** odds_ratio_per_0.10_of_the_buyer's_annual_raw_material_spend_sourced_from_this_desk · **Flag:** ASSUMPTION
- **Source:** Judgement (synthetic DGP). A buyer sourcing most of its input from one supplier on credit is using that supplier as a financier and has fewer alternative lines.
- **Verify:** **N/A** — synthetic data-generating process, nothing to verify against
- **Justification:** +10 percentage points of the buyer's raw-material spend coming from the desk multiplies default odds by 1.15 (10 % to 60 %: ~x2.0). Buyer-side dependence, not the desk's own book share: the desk's concentration in one name is an exposure question and is handled by limits, not by the PD.

### `credit_synth_gen_utilisation`

- **Value:** {"mean": 0.5, "weakness_loading": 0.15, "noise_sd": 0.2, "floor": 0.0, "cap": 1.3}
- **Unit:** mapping: peak credit utilisation frac = clip(mean + weakness_loading*w + noise_sd*e, floor, cap); w ~ N(0,1) per buyer, e ~ N(0,1) per quarter · **Flag:** ASSUMPTION
- **Source:** Judgement (synthetic feature generator)
- **Verify:** **N/A** — synthetic data-generating process, nothing to verify against
- **Justification:** Utilisation spread wide enough (1st-99th pct roughly 0-1.03, occasional breaches to 1.3) to cover the SIM buyers' credit-utilisation peaks (0.74-0.89). Weaker buyers (higher latent w) run fuller lines, so features are correlated the way a real portfolio's are; w never enters the default probability directly, so a logistic model on the four features is correctly specified by construction (a real portfolio would not be).

### `credit_synth_gen_dpd`

- **Value:** {"p_late_logit_intercept": -0.3, "p_late_weakness_loading": 1.0, "late_mean_days": 12.0, "late_mean_weakness_elasticity": 0.35, "cap_days": 120}
- **Unit:** mapping: worst DPD days = 0 with prob 1-sigmoid(a+b*w), else ceil(Exponential(late_mean_days*exp(elasticity*w))) capped · **Flag:** ASSUMPTION
- **Source:** Judgement (synthetic feature generator)
- **Verify:** **N/A** — synthetic data-generating process, nothing to verify against
- **Justification:** Zero-inflated: about 45 % of buyer-quarters have some delinquency in the trailing year, mostly under three weeks, with a long tail for weak names (99th percentile ~55 days).

### `credit_synth_gen_history`

- **Value:** {"median_months": 30.0, "log_sd": 0.7, "weakness_loading_log": -0.2, "months_per_quarter": 3.0, "floor_months": 1.0, "cap_months": 180.0}
- **Unit:** mapping: months of history = clip(exp(log(median)+weakness_loading_log*w+log_sd*e_buyer) + months_per_quarter*quarter_index, floor, cap) · **Flag:** ASSUMPTION
- **Source:** Judgement (synthetic feature generator)
- **Verify:** **N/A** — synthetic data-generating process, nothing to verify against
- **Justification:** Relationship length is buyer-level (it grows 3 months per observed quarter) and only mildly related to weakness.

### `credit_synth_gen_concentration`

- **Value:** {"logit_intercept": -1.8, "weakness_loading": 0.5, "buyer_sd": 0.8, "quarter_sd": 0.3}
- **Unit:** mapping: share of buyer raw-material spend from the desk = sigmoid(intercept + loading*w + buyer_sd*e_buyer + quarter_sd*e_quarter) · **Flag:** ASSUMPTION
- **Source:** Judgement (synthetic feature generator)
- **Verify:** **N/A** — synthetic data-generating process, nothing to verify against
- **Justification:** Median ~14 %, 99th percentile ~60 %: most foundries multi-source, a tail of small names depend on one importer.

### `credit_feature_lookback_utilisation_days`

- **Value:** 91
- **Unit:** calendar_days · **Flag:** ASSUMPTION
- **Source:** Model design: matches the synthetic training grain (one observation = one buyer-quarter)
- **Verify:** **N/A** — model design choice
- **Justification:** Peak credit utilisation, and the peak advance-reliance multiple that triggers the performance overlay, are taken over panel days in (d-91, d] using only rows dated on or before the scoring date d.

### `credit_feature_lookback_dpd_days`

- **Value:** 365
- **Unit:** calendar_days · **Flag:** ASSUMPTION
- **Source:** Model design: worst delinquency over the trailing 12 months, a standard bureau/scorecard window
- **Verify:** **N/A** — model design choice
- **Justification:** The book's own days_past_due (P3) is combined with the SIM profile's prior_dpd_max_days from config/counterparties.yaml. ASSUMPTION: that prior worst delinquency is dated inside the 12 months before the book's first day, so it stays in the window through HORIZON_END (the profile carries no dates).

### `credit_feature_lookback_concentration_days`

- **Value:** 365
- **Unit:** calendar_days · **Flag:** ASSUMPTION
- **Source:** Model design: trailing 12 months of contracted desk sales against one year of the buyer's raw-material spend
- **Verify:** **N/A** — model design choice
- **Justification:** order_concentration_frac(d) = booking-time invoice value of desk sales to the buyer contracted in (d-365, d] divided by annual_turnover_inr x secondary_raw_material_cost_share. Pre-book invoices have no recorded values, so early-window concentration is a lower bound. The profile's group_concentration_frac is NOT used: it is undefined in the schema and matches the whole book's final sales, so using it before those sales were contracted would be look-ahead.

### `credit_band_pd_upper_frac`

- **Value:** {"A": 0.02, "B": 0.05, "C": 0.12}
- **Unit:** annual_pd_frac_upper_bound_exclusive (D = everything at or above the C bound) · **Flag:** ASSUMPTION
- **Source:** Desk policy judgement, expressed against the synthetic population base rate (credit_synth_base_default_rate_annual_frac = 4 %)
- **Verify:** **N/A** — desk policy assumption
- **Justification:** A < half the population base rate; B up to 1.25x base; C up to 3x base; D above. Set before scoring. Four bands because a credit committee can act on four (grow, hold, secure, exit/advance-only) and cannot act on a decimal.

### `credit_performance_overlay_notches`

- **Value:** 1
- **Unit:** bands_downgraded · **Flag:** ASSUMPTION
- **Source:** Desk policy judgement, Phase 1-3 open item 1 (docs/reviews/phase1-3_fix_log.md §3): score advance failure as well as receivable default
- **Verify:** **N/A** — desk policy assumption
- **Justification:** If the buyer's advance-reliance multiple (advances contracted and not yet received / credit limit) exceeded buyer_advance_limit_multiple_of_credit_limit (commercial.yaml, 1.0x, rule P14) on any panel day in the utilisation lookback, the model band is downgraded this many notches (floor D). An overlay rather than a model feature: it changes what the desk loses if the name fails, and it lies far outside any support a utilisation feature could be trained on (docs/50_credit_scoring.md §3.2).

### `credit_soft_utilisation_frac`

- **Value:** 0.8
- **Unit:** frac_of_credit_limit_inr · **Flag:** ASSUMPTION
- **Source:** Desk policy judgement: early-warning line on the credit-utilisation measure
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Credit utilisation (receivable plus advance-uncovered contracted sales) at or above 80 % of the line raises a soft flag in the tracker: the next parcel to that name cannot go on open credit without a clearance first.

### `credit_band_max_credit_utilisation_frac`

- **Value:** {"A": 1.0, "B": 0.9, "C": 0.75, "D": 0.5}
- **Unit:** frac_of_credit_limit_inr · **Flag:** ASSUMPTION
- **Source:** Desk policy judgement (band -> limit policy)
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Maximum credit utilisation (the P04 measure: receivable plus advance-uncovered contracted sales, over the limit) a new sale may leave behind, by the buyer's final band at the previous close.

### `credit_band_max_advance_reliance_multiple`

- **Value:** {"A": 1.0, "B": 1.0, "C": 0.5, "D": 0.0}
- **Unit:** multiple_of_credit_limit_inr · **Flag:** ASSUMPTION
- **Source:** Desk policy judgement (band -> limit policy), tightening rule P14 for weaker bands
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Advance the desk may RELY ON before it arrives (cargo allocated, hedge lifted). A and B keep the P14 cap of 1.0x; C halves it; D relies on nothing — the hedge stays on and the cargo stays unallocated until the advance is in the bank.

### `credit_band_limit_multiplier`

- **Value:** {"A": 1.0, "B": 1.0, "C": 1.0, "D": 0.5}
- **Unit:** multiple_of_current_credit_limit_inr · **Flag:** ASSUMPTION
- **Source:** Desk policy judgement (band -> limit policy)
- **Verify:** **N/A** — desk policy assumption
- **Justification:** Recommended limit = current limit x multiplier. C is frozen at the current line (no increase); D is cut in half pending committee review.

### `credit_band_max_credit_days`

- **Value:** {"A": 45, "B": 30, "C": 30, "D": 0}
- **Unit:** days · **Flag:** ASSUMPTION
- **Source:** Desk policy judgement (band -> limit policy), capped by max_domestic_credit_days (commercial.yaml, 45)
- **Verify:** **N/A** — desk policy assumption
- **Justification:** D-band names buy on advance or cash against documents only; C-band credit needs security (post-dated cheques or a bank guarantee) covering the credit balance.

### `credit_band_review_frequency_days`

- **Value:** {"A": 180, "B": 90, "C": 30, "D": 7}
- **Unit:** days_between_credit_reviews · **Flag:** ASSUMPTION
- **Source:** Desk policy judgement (band -> limit policy)
- **Verify:** **N/A** — desk policy assumption
- **Justification:** How often the name comes back to the credit committee.

### `credit_band_limit_action`

- **Value:** {"A": "MAINTAIN — eligible for a limit increase at the next review", "B": "MAINTAIN — watch utilisation; no increase without a clean review", "C": "FREEZE — no increase; security for any credit balance; advance reliance capped at 0.5x limit", "D": "REDUCE — cut the line to 50 %; advance or cash-against-documents only; do not lift the hedge before the advance arrives"}
- **Unit:** text_by_band · **Flag:** ASSUMPTION
- **Source:** Desk policy judgement (band -> limit policy)
- **Verify:** **N/A** — desk policy assumption
- **Justification:** The action text written into credit_scores.csv and credit_tracker.csv, quoted by the risk policy memo.

## `config/params/scrap_grades.yaml`

Owner: P0 regulatory/contract research · 25 parameters · DIRECT 0, PROXY 5, ASSUMPTION 20.

| Key | Value | Unit | Flag | Verify |
|---|---|---|---|---|
| `grade_factor_mix` | linear path, 10 points: 2021-12-15: 0.836; 2022-01-15: 0.767; 2022-... | frac_of_lme_3m_cif_india | PROXY | VERIFIED |
| `grade_factor_mix_lag1` | linear path, 10 points: 2021-12-15: 0.841; 2022-01-15: 0.751; 2022-... | frac_of_lme_3m_cif_india | PROXY | VERIFIED |
| `grade_factor_mix_lag3` | linear path, 10 points: 2021-12-15: 0.855; 2022-01-15: 0.829; 2022-... | frac_of_lme_3m_cif_india | PROXY | VERIFIED |
| `grade_factor_mix_pit` | linear path, 10 points: 2021-12-15: 0.789; 2022-01-15: 0.759; 2022-... | frac_of_lme_3m_cif_india | ASSUMPTION | **PENDING** |
| `grade_factor_lag_months` | 2 | months | PROXY | N/A |
| `grade_factor_diff_zorba` | -0.02 | signed_diff_of_lme_3m_frac_cfr_india | ASSUMPTION | PARTIAL |
| `grade_factor_diff_taint_tabor` | -0.02 | signed_diff_of_lme_3m_frac_cfr_india | ASSUMPTION | PARTIAL |
| `grade_factor_diff_tense` | -0.07 | signed_diff_of_lme_3m_frac_cfr_india | ASSUMPTION | PARTIAL |
| `grade_factor_zorba` | linear path, 10 points: 2021-12-15: 0.816; 2022-01-15: 0.747; 2022-... | frac_of_lme_3m_cfr_india | ASSUMPTION | PARTIAL |
| `grade_factor_taint_tabor` | linear path, 10 points: 2021-12-15: 0.816; 2022-01-15: 0.747; 2022-... | frac_of_lme_3m_cfr_india | ASSUMPTION | PARTIAL |
| `grade_factor_tense` | linear path, 10 points: 2021-12-15: 0.766; 2022-01-15: 0.697; 2022-... | frac_of_lme_3m_cfr_india | ASSUMPTION | PARTIAL |
| `grade_falling_market_logic` | In a sharp LME fall scrap prices lag, so the factor (scrap ÷ LME) R... | text | PROXY | VERIFIED |
| `moisture_frac_zorba` | 0.01 | frac_of_gross_weight | ASSUMPTION | N/A |
| `contamination_frac_zorba` | 0.06 | frac_of_dry_weight | ASSUMPTION | **PENDING** |
| `metal_yield_frac_zorba` | 0.93 | frac_of_aluminium_to_ingot | ASSUMPTION | **PENDING** |
| `heavies_frac_zorba` | 0.05 | frac_of_dry_weight | ASSUMPTION | **PENDING** |
| `heavies_frac_taint_tabor` | 0.0 | frac_of_dry_weight | ASSUMPTION | N/A |
| `heavies_frac_tense` | 0.0 | frac_of_dry_weight | ASSUMPTION | N/A |
| `heavies_net_value_frac_of_lme_al` | 0.8 | frac_of_lme_3m_usd_t_per_mt_of_heavies | ASSUMPTION | **PENDING** |
| `moisture_frac_taint_tabor` | 0.005 | frac_of_gross_weight | ASSUMPTION | N/A |
| `contamination_frac_taint_tabor` | 0.02 | frac_of_dry_weight | ASSUMPTION | N/A |
| `metal_yield_frac_taint_tabor` | 0.92 | frac_of_clean_metal_to_ingot | ASSUMPTION | **PENDING** |
| `moisture_frac_tense` | 0.005 | frac_of_gross_weight | ASSUMPTION | N/A |
| `contamination_frac_tense` | 0.02 | frac_of_dry_weight | ASSUMPTION | N/A |
| `metal_yield_frac_tense` | 0.94 | frac_of_clean_metal_to_ingot | ASSUMPTION | **PENDING** |

### `grade_factor_mix`

- **Value:** linear path, 10 points: 2021-12-15: 0.836; 2022-01-15: 0.767; 2022-02-15: 0.771; 2022-03-15: 0.702; 2022-04-15: 0.764; 2022-05-15: 0.821; 2022-06-15: 0.866; 2022-07-15: 0.875; 2022-08-15: 0.81; 2022-09-15: 0.89
- In window: 2022-03-01 0.7365 → 2022-08-31 0.85129; min 0.702, max 0.875.
- **Unit:** frac_of_lme_3m_cif_india · **Flag:** PROXY
- **Source:** [DGCIS] HS 76020010 all-origin monthly unit value (CIF $/t) in month m+2 ÷ [LME] mean official 3M in contract month m (data/interim/price_evidence/mix_ratio_by_contract_month.csv)
- **Verify:** **VERIFIED** — 2026-09-16 — trade statistics and LME prices read from cached official/republished tables and recomputed by desk.data.fetch_price_evidence (fails on mismatch). The SHAPE is real data; it is an all-grade, all-origin average whose grade mix can change month to month.
- **Justification:** Mar–Aug 2022 contract-month mean 0.806. HINDSIGHT: UV(m+2) is published months after contract month m, so this path uses information a 2022 desk did not have (see grade_factor_mix_pit). Market dynamics in the SHAPE are real data: at the LME spike (Mar-2022 contracts) scrap lagged and the ratio fell to 0.70; through the crash (May–Jul) scrap was sticky and the ratio rose to 0.87–0.88; it eased to 0.81 in August. USGS US scrap/LME ratios move the same way (grade_falling_market_logic).

### `grade_factor_mix_lag1`

- **Value:** linear path, 10 points: 2021-12-15: 0.841; 2022-01-15: 0.751; 2022-02-15: 0.714; 2022-03-15: 0.702; 2022-04-15: 0.759; 2022-05-15: 0.877; 2022-06-15: 0.907; 2022-07-15: 0.93; 2022-08-15: 0.869; 2022-09-15: 0.876
- In window: 2022-03-01 0.708 → 2022-08-31 0.872613; min 0.702, max 0.93.
- **Unit:** frac_of_lme_3m_cif_india · **Flag:** PROXY
- **Source:** As grade_factor_mix with UV month m+1 (data/interim/price_evidence/mix_ratio_by_contract_month.csv)
- **Verify:** **VERIFIED** — 2026-09-16 — recomputed from cached DGCIS/LME tables
- **Justification:** Sensitivity only (Mar–Aug mean 0.841). P1 must show window_open under lag 1 and lag 3 next to the lag-2 base (review finding on regime-driven swings).

### `grade_factor_mix_lag3`

- **Value:** linear path, 10 points: 2021-12-15: 0.855; 2022-01-15: 0.829; 2022-02-15: 0.771; 2022-03-15: 0.706; 2022-04-15: 0.716; 2022-05-15: 0.784; 2022-06-15: 0.815; 2022-07-15: 0.816; 2022-08-15: 0.824; 2022-09-15: 0.773
- In window: 2022-03-01 0.7385 → 2022-08-31 0.797677; min 0.706, max 0.824.
- **Unit:** frac_of_lme_3m_cif_india · **Flag:** PROXY
- **Source:** As grade_factor_mix with UV month m+3
- **Verify:** **VERIFIED** — 2026-09-16 — recomputed from cached DGCIS/LME tables
- **Justification:** Sensitivity only (Mar–Aug mean 0.777).

### `grade_factor_mix_pit`  — **PENDING**

- **Value:** linear path, 10 points: 2021-12-15: 0.789; 2022-01-15: 0.759; 2022-02-15: 0.856; 2022-03-15: 0.836; 2022-04-15: 0.767; 2022-05-15: 0.771; 2022-06-15: 0.702; 2022-07-15: 0.764; 2022-08-15: 0.821; 2022-09-15: 0.866
- In window: 2022-03-01 0.846 → 2022-08-31 0.844226; min 0.702, max 0.846.
- **Unit:** frac_of_lme_3m_cif_india · **Flag:** ASSUMPTION
- **Source:** Point-in-time variant: UV(m−1) ÷ mean LME 3M(m−3), i.e. the latest lag-2 ratio a desk could compute during month m
- **Verify:** **PENDING** — the ~1-month DGCIS release lag behind this construction is assumed, not verified. Next step: check TRADESTAT/DGCIS release calendar for 8-digit monthly import data in 2022.
- **Justification:** Sensitivity only (Mar–Aug mean 0.777). It removes the look-ahead but trades on a 3-month-stale ratio, which in 2022 would have been exactly wrong-footed at both the spike and the crash.

### `grade_factor_lag_months`

- **Value:** 2
- **Unit:** months · **Flag:** PROXY
- **Source:** In-repo fit on [DGCIS] HS 76020010 unit values vs LME 3M monthly means, contract months Jan-2021–Dec-2022 (24): ratio std 0.089 (lag 0), 0.063 (1), 0.043 (2), 0.045 (3) — recomputed by desk.data.fetch_price_evidence
- **Verify:** **N/A** — empirical choice; documented
- **Justification:** Economic reading: contract → loading → sailing (5–40 days) → Bill of Entry. Lags 2 and 3 fit equally well; lag 1 and 3 paths are published as sensitivities.

### `grade_factor_diff_zorba`

- **Value:** -0.02
- **Unit:** signed_diff_of_lme_3m_frac_cfr_india · **Flag:** ASSUMPTION
- **Source:** [BigMint] UK Zorba 95/5 CFR India assessments (14) and one US Zorba 95/5 deal, 24-Feb-2024 → 31-Oct-2025: median(price ÷ LME 3M(D−1) − lag-2 mix) = −0.022 (IQR −0.044 … +0.007, n=15), rounded to 0.005 (data/interim/price_evidence/grade_differentials.csv)
- **Verify:** **PARTIAL** — 2026-09-16 — every quote traced to its cached AlCircle sentence and date-matched Westmetall 3M; no 2022 Zorba quote exists in public. Next step: 2022 Zorba 95/5 CFR India assessments (BigMint/Fastmarkets archive) to replace the cross-period assumption.
- **Justification:** Sensitivities: assessments only −0.031; article-date (D0) LME −0.033. Zorba 95/5 is not adjusted for attachments (the '95/5' name already describes ~95% aluminium / ~5% heavy non-ferrous). Read grade_factor_zorba, do not add this again.

### `grade_factor_diff_taint_tabor`

- **Value:** -0.02
- **Unit:** signed_diff_of_lme_3m_frac_cfr_india · **Flag:** ASSUMPTION
- **Source:** [BigMint] US Taint/Tabor HRB (2–3%) assessments (3) and deals (US HRB 2–3%, UAE Taint/Tabor ×2), 13-Mar-2024 → 27-Aug-2025, adjusted to ISRI-clean by ÷(1 − stated attachments): median diff −0.018 (IQR −0.058 … −0.009, n=8); UK 'Taint Tabor C/S (9–10%)' prints excluded (undefined sub-grade, inconsistent levels)
- **Verify:** **PARTIAL** — 2026-09-16 — quotes traced to cached sentences; small sample, and the Dec-2025 HRB prints cannot be scored yet (lag-2 unit value for Feb-2026 not used). Next step: 2022 Taint/Tabor CIF India quotes.
- **Justification:** Unadjusted median −0.028; assessments only −0.015. Still CONTRADICTS the MASTER_SPEC 88–92% guide: the clean-TT CFR factor averages 0.786 in Mar–Aug 2022 on this construction.

### `grade_factor_diff_tense`

- **Value:** -0.07
- **Unit:** signed_diff_of_lme_3m_frac_cfr_india · **Flag:** ASSUMPTION
- **Source:** [BigMint] UAE Tense (benchmark labelled 8–9% attachments) and US Tense (labelled 6–7%) assessments (25) plus 3 deals (US 5–7%, Europe 2%, UK 6%), 14-Feb-2024 → 31-Oct-2025, adjusted to ISRI-clean ÷(1 − attachments): median diff −0.068 (IQR −0.082 … −0.024, n=28), rounded to 0.005
- **Verify:** **PARTIAL** — 2026-09-16 — quotes traced to cached sentences; where an article omits the benchmark's attachment label the series label from other weeks is applied (attach_source=SERIES in the evidence table). Next step: 2022 Tense CFR India assessments.
- **Justification:** Unadjusted (as-quoted, with attachments) median −0.124. The attachment adjustment assumes a buyer pays for aluminium content only; iron inserts have some value, so the clean-equivalent may be slightly overstated.

### `grade_factor_zorba`

- **Value:** linear path, 10 points: 2021-12-15: 0.816; 2022-01-15: 0.747; 2022-02-15: 0.751; 2022-03-15: 0.682; 2022-04-15: 0.744; 2022-05-15: 0.801; 2022-06-15: 0.846; 2022-07-15: 0.855; 2022-08-15: 0.79; 2022-09-15: 0.87
- In window: 2022-03-01 0.7165 → 2022-08-31 0.83129; min 0.682, max 0.855.
- **Unit:** frac_of_lme_3m_cfr_india · **Flag:** ASSUMPTION
- **Source:** grade_factor_mix (PROXY) + grade_factor_diff_zorba (ASSUMPTION); construction in file header. Desk grade = Zorba 95/5.
- **Verify:** **PARTIAL** — 2026-09-16 — the mix shape is VERIFIED official data; the level depends on a 2024–25 differential applied to 2022. Next step: as grade_factor_diff_zorba.
- **Justification:** Flag = weakest component (review fix: the level, not only the shape, drives fob/cfr, and a ±0.02 shift is ~USD 57/t ≈ INR 4,400/t — the size of margin_threshold_inr_t). Mar–Aug contract-month mean 0.786. P1 must show the ±1 IQR differential sensitivity next to window_open. Grade definition (review fix): the price evidence is for Zorba 95/5, so the desk buys Zorba 95/5 and its recovery and heavies credit below use the same definition.

### `grade_factor_taint_tabor`

- **Value:** linear path, 10 points: 2021-12-15: 0.816; 2022-01-15: 0.747; 2022-02-15: 0.751; 2022-03-15: 0.682; 2022-04-15: 0.744; 2022-05-15: 0.801; 2022-06-15: 0.846; 2022-07-15: 0.855; 2022-08-15: 0.79; 2022-09-15: 0.87
- In window: 2022-03-01 0.7165 → 2022-08-31 0.83129; min 0.682, max 0.855.
- **Unit:** frac_of_lme_3m_cfr_india · **Flag:** ASSUMPTION
- **Source:** grade_factor_mix (PROXY) + grade_factor_diff_taint_tabor (ASSUMPTION); ISRI-clean Taint/Tabor
- **Verify:** **PARTIAL** — 2026-09-16 — as grade_factor_zorba. CONTRADICTS the MASTER_SPEC guide of 88–92% for Taint/Tabor: no retrieved evidence supports it.
- **Justification:** Mar–Aug contract-month mean 0.786 (equal to Zorba 95/5 on the evidence medians: clean-TT and Zorba 95/5 quote ratios were 0.832 vs 0.828 in 2024–25). If P1 wants to test the spec's view, run a +0.10 sensitivity.

### `grade_factor_tense`

- **Value:** linear path, 10 points: 2021-12-15: 0.766; 2022-01-15: 0.697; 2022-02-15: 0.701; 2022-03-15: 0.632; 2022-04-15: 0.694; 2022-05-15: 0.751; 2022-06-15: 0.796; 2022-07-15: 0.805; 2022-08-15: 0.74; 2022-09-15: 0.82
- In window: 2022-03-01 0.6665 → 2022-08-31 0.78129; min 0.632, max 0.805.
- **Unit:** frac_of_lme_3m_cfr_india · **Flag:** ASSUMPTION
- **Source:** grade_factor_mix (PROXY) + grade_factor_diff_tense (ASSUMPTION); ISRI-clean Tense
- **Verify:** **PARTIAL** — 2026-09-16 — as grade_factor_zorba.
- **Justification:** Mar–Aug contract-month mean 0.736. Tense (mixed castings, ISRI oil & grease ≤2%) is the workhorse feed for ADC12/LM6 alloy ingot, so it tracks domestic alloy demand; in Feb-2024 domestic Tense traded at INR 172,500/t ex-Delhi (AlCircle 24-Feb-2024).

### `grade_falling_market_logic`

- **Value:** In a sharp LME fall scrap prices lag, so the factor (scrap ÷ LME) RISES and the absolute USD discount narrows; in a spike the factor FALLS. Buyers' bids then widen discounts once LME stabilises.
- **Unit:** text · **Flag:** PROXY
- **Source:** [DGCIS] lagged unit-value ratio: 0.70 (Mar-2022 contracts, LME 3M avg $3,543) → 0.87 (Jun) → 0.88 (Jul) → 0.81 (Aug). [USGS] Table 7 ÷ Table 6, US old sheet / LME cash: 0.537 (Mar-2022) → 0.606 (Apr) → 0.599 (May–Jun) → 0.561 (Aug); old cast 0.522 → 0.607 (Jun) → 0.568 (Aug); and in the 2021 rally old sheet fell from 0.669 (Mar-2021) to 0.519 (Sep-2021).
- **Verify:** **VERIFIED** — 2026-09-16 as a pattern in two independent public datasets (direction only, not grade-specific levels)
- **Justification:** Trader implication: a desk that buys scrap on a fixed % of LME in a crash is paying away the stickiness to the supplier; the seller prefers fixed-USD offers in a falling market and %-of-LME in a rising one. This is why the desk's M+1 LME-linked SPAs (Table 4 row 2.4) are safer for the buyer than fixed prices when LME is falling fast.

### `moisture_frac_zorba`

- **Value:** 0.01
- **Unit:** frac_of_gross_weight · **Flag:** ASSUMPTION
- **Source:** ISRI 2022 Zorba spec sets metal content by agreement and requires the lot free of radioactive material, dross and ash, but sets no moisture limit; the sister fragmentizer grades require material to be 'dry' (Twitch/Tweak). Level = desk SPA franchise (standard_moisture_franchise_frac)
- **Verify:** **N/A** — assumption; SPA-driven
- **Justification:** Shredded Zorba from wet media separation can arrive at 1–3% moisture; the SPA deducts weight above the 1% franchise, so the desk pays for at most ~1%.

### `contamination_frac_zorba`  — **PENDING**

- **Value:** 0.06
- **Unit:** frac_of_dry_weight · **Flag:** ASSUMPTION
- **Source:** Trade usage of 'Zorba 95/5' (BigMint assessment name): ~95% aluminium and ~5% heavy non-ferrous (Cu, brass, Zn, stainless); ISRI 2022 Zorba: sold by estimated non-ferrous metal content, passed over magnets
- **Verify:** **PENDING** — the 95/5 composition is trade naming, not an ISRI definition; confirm from a BigMint/Fastmarkets Zorba methodology note or a packing-list assay
- **Justification:** Non-aluminium fraction of the dry lot = heavies 0.05 (heavies_frac_zorba, credited separately) + ~0.01 rubber/plastic/dirt/free iron. Review fix: the previous Zorba 90 definition (0.08 contamination, 0.85 yield, no heavies credit) contradicted the Zorba 95/5 price evidence.

### `metal_yield_frac_zorba`  — **PENDING**

- **Value:** 0.93
- **Unit:** frac_of_aluminium_to_ingot · **Flag:** ASSUMPTION
- **Source:** Desk assumption: melt recovery of shredded, eddy-current-separated aluminium (thin gauge, some coatings) 0.92–0.94
- **Verify:** **PENDING** — no published Indian smelter yield for Zorba retrieved; check a BigMint/Fastmarkets Zorba methodology note or an Indian secondary smelter DRHP
- **Justification:** Recovery_zorba = 0.99 × 0.94 × 0.93 = 0.866 (aluminium only). P1 recovery sensitivity: 0.92–0.94.

### `heavies_frac_zorba`  — **PENDING**

- **Value:** 0.05
- **Unit:** frac_of_dry_weight · **Flag:** ASSUMPTION
- **Source:** Grade name 'Zorba 95/5' (~5% heavy non-ferrous metals), see contamination_frac_zorba
- **Verify:** **PENDING** — as contamination_frac_zorba
- **Justification:** Heavies are floated / hand-picked out and sold to heavy-non-ferrous buyers; CONTRACTS §5 credits them (byproduct_inr_t).

### `heavies_frac_taint_tabor`

- **Value:** 0.0
- **Unit:** frac_of_dry_weight · **Flag:** ASSUMPTION
- **Source:** ISRI 2022 Taint/Tabor: aluminium sheet only; attachments are not a saleable heavy fraction
- **Verify:** **N/A** — structural
- **Justification:** No by-product credit.

### `heavies_frac_tense`

- **Value:** 0.0
- **Unit:** frac_of_dry_weight · **Flag:** ASSUMPTION
- **Source:** ISRI 2022 Tense: aluminium castings free of iron and brass
- **Verify:** **N/A** — structural
- **Justification:** No by-product credit.

### `heavies_net_value_frac_of_lme_al`  — **PENDING**

- **Value:** 0.8
- **Unit:** frac_of_lme_3m_usd_t_per_mt_of_heavies · **Flag:** ASSUMPTION
- **Source:** Desk judgement: a mixed Zorba heavies concentrate (copper, brass, zinc, stainless) sells well above aluminium per tonne; valuing it at LME aluminium 3M and deducting ~20% for separation, handling and a buyer's margin is deliberately conservative
- **Verify:** **PENDING** — no public 2022 or 2024 India price for Zorba heavies / 'Zebra' was retrieved. Next step: a BigMint or Fastmarkets heavy non-ferrous shred price series, or a US ReMA 'Zebra' quote converted to CFR India.
- **Justification:** At window-average LME 3M ≈ USD 2,850/t and 0.05 heavies this credit is ≈ USD 114/t ≈ INR 8,900/t of scrap — ignoring it (previous register) was a ₹9k/t omission, larger than the margin hurdle. P1 sensitivity: 0.4–1.5.

### `moisture_frac_taint_tabor`

- **Value:** 0.005
- **Unit:** frac_of_gross_weight · **Flag:** ASSUMPTION
- **Source:** ISRI 2022 Taint/Tabor: clean mixed old alloy sheet, free of dirt and non-metallic items; no numeric moisture limit
- **Verify:** **N/A** — assumption
- **Justification:** Baled/cut sheet sheds water; residual moisture in bale interstices after monsoon-season ocean transit.

### `contamination_frac_taint_tabor`

- **Value:** 0.02
- **Unit:** frac_of_dry_weight · **Flag:** ASSUMPTION
- **Source:** ISRI 2022 Taint/Tabor: 'Oil and grease not to total more than 1%. Up to 10% Tale [painted siding] permitted.'; free of foil, castings, screen, plastic, dirt
- **Verify:** **N/A** — assumption within ISRI limits
- **Justification:** ≤1% oil/grease + paint/coating mass (~0.5–1% on a lot with up to 10% painted siding) + stray attachments.

### `metal_yield_frac_taint_tabor`  — **PENDING**

- **Value:** 0.92
- **Unit:** frac_of_clean_metal_to_ingot · **Flag:** ASSUMPTION
- **Source:** Desk assumption: melt loss of thin, partly painted old sheet 6–10% (coating burn-off and oxidation of high surface-area feed) — no public Indian figure retrieved
- **Verify:** **PENDING** — confirm melt-loss range with an Indian secondary smelter disclosure or an aluminium recycling engineering reference
- **Justification:** Recovery_taint_tabor = 0.995 × 0.98 × 0.92 = 0.897. P1 recovery sensitivity: 0.90–0.94.

### `moisture_frac_tense`

- **Value:** 0.005
- **Unit:** frac_of_gross_weight · **Flag:** ASSUMPTION
- **Source:** ISRI 2022 Tense: clean aluminium castings, free of iron, brass, dirt and other non-metallic items; no numeric moisture limit
- **Verify:** **N/A** — assumption
- **Justification:** Castings hold little water; 0.5% allows for surface moisture and dirt in cavities.

### `contamination_frac_tense`

- **Value:** 0.02
- **Unit:** frac_of_dry_weight · **Flag:** ASSUMPTION
- **Source:** ISRI 2022 Tense: 'Oil and grease not to total more than 2%'; India trade quotes are commonly for Tense with 6–9% attachments (BigMint 'UAE Tense (8-9 per cent)', 'US-origin Tense (6-7 per cent)')
- **Verify:** **N/A** — assumption within ISRI limits
- **Justification:** Desk buys ISRI-clean Tense; grade_factor_diff_tense already converts attachment-bearing quotes to a clean basis.

### `metal_yield_frac_tense`  — **PENDING**

- **Value:** 0.94
- **Unit:** frac_of_clean_metal_to_ingot · **Flag:** ASSUMPTION
- **Source:** Desk assumption: melt loss of mixed auto castings 4–7% (thicker sections, lower surface area than sheet); no insert deduction because ISRI Tense is free of iron
- **Verify:** **PENDING** — as metal_yield_frac_taint_tabor
- **Justification:** Recovery_tense = 0.995 × 0.98 × 0.94 = 0.917; Tense chemistry (Si, Cu) is close to ADC12/LM-series, so little re-alloying is needed. P1 recovery sensitivity: 0.92–0.95.
