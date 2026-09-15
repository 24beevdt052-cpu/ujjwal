# Phase 0 assumptions log

ACADEMIC SIMULATION — not actual trades.

Rendered by `desk.data.dictionary` from `desk.config.params_frame()` (the YAML register in `config/params/`) — do not hand-edit; change the YAML and re-run `.venv/bin/python run_all.py --only P0`. Data retrieved 2026-09-16 (cached under data/raw/; rebuilt offline with DESK_OFFLINE=1).

Flags: **DIRECT** = observed from a named public source; **PROXY** = real observable standing in or a transformation of real data; **ASSUMPTION** = judgement with justification. Verify status (first word of each `verify` field): **VERIFIED** = primary/official source read for the 2022 value; **PARTIAL** = supported with a named gap; **PENDING** = not yet verified (the text gives the next step); **N/A** = assumption with nothing to verify against. Statuses are as recorded by the Phase 0 researchers; details in `docs/verification_log.md`.

## Summary

| YAML file | Owner | Params | DIRECT | PROXY | ASSUMPTION | VERIFIED | PARTIAL | PENDING | N/A |
|---|---|---|---|---|---|---|---|---|---|
| `commercial.yaml` | P0 regulatory/contract research | 21 | 5 | 4 | 12 | 6 | 3 | 3 | 9 |
| `exchange.yaml` | P0 regulatory/contract research | 32 | 26 | 1 | 5 | 20 | 7 | 2 | 3 |
| `logistics.yaml` | P0 freight/logistics | 26 | 3 | 1 | 22 | 3 | 1 | 20 | 2 |
| `market_proxy.yaml` | P0 market-data | 1 | 0 | 1 | 0 | 0 | 1 | 0 | 0 |
| `rates.yaml` | P0 market-data | 7 | 3 | 2 | 2 | 5 | 0 | 1 | 1 |
| `regulatory.yaml` | P0 regulatory/contract research | 22 | 14 | 2 | 6 | 9 | 6 | 2 | 5 |
| `scrap_grades.yaml` | P0 regulatory/contract research | 25 | 0 | 5 | 20 | 4 | 6 | 7 | 8 |
| **Total** |  | 134 | 51 | 16 | 67 | 47 | 24 | 35 | 28 |

## Open items: PENDING (35)

Nothing below may be presented as checked. Each row's last column is the recorded next step.

| Key | File | Flag | Value used | Next step |
|---|---|---|---|---|
| **`conversion_cost_inr_t`** | commercial.yaml | ASSUMPTION | 12000 | no 2022 Indian secondary-smelter cost disclosure retrieved. Next step: cost-of-production note in a listed Indian secondary aluminium producer's 2022 annual report/DRHP (power + fuel + consumables per tonne). |
| **`domestic_anchor_premium_inr_t`** | commercial.yaml | ASSUMPTION | -9000 | no 2022 ADC12/LM6 India price series was retrievable (AlCircle/BigMint 2022 archives not found in public). Next step: weekly 2022 ADC12 ex-Delhi/Chennai from BigMint or an automaker's 2022 monthly alloy settlement prices, compared with MCX near-month. |
| **`usance_interest_spread_pa`** | commercial.yaml | ASSUMPTION | 0.015 | no 2022 buyer's-credit quote retrieved; check an Indian bank or buyer's-credit arranger's 2022 indicative pricing |
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
| **`freight_jea_nsa_usd_box_ref`** | logistics.yaml | ASSUMPTION | 600 | no citable 2022 Jebel Ali->Nhava Sheva quote found (Platts WCI India-Middle East assessments and Xeneta are paywalled; S&P pages return 403). Next step: a 2022 Wayback copy of a Freightos/SeaRates/iContainers JEA->INNSA rate page, or a BigMint/Fastmarkets 2022 UAE-origin scrap CFR vs FOB spread |
| **`wc_rate_spread_over_mclr_pa`** | rates.yaml | ASSUMPTION | 0.025 | no 2022 sanction letter or published spread for a comparable borrower retrieved. Next step: a listed metals trader's FY2022-23 annual report (borrowing-cost note) to back out its working-capital rate over MCLR. |
| **`psic_cost_usd_per_box`** | regulatory.yaml | ASSUMPTION | 40.0 | obtain an inspection-agency (PSIA) 2022 quote or published fee for radiation + explosives inspection of a 20ft scrap container at Jebel Ali |
| **`nfmims_min_lead_days`** | regulatory.yaml | PROXY | 5 | confirm 60/5-day window and 75-day validity in the DGFT notification text |
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

Owner: P0 regulatory/contract research · 21 parameters · DIRECT 5, PROXY 4, ASSUMPTION 12.

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
- **Justification:** LME official cash moved more than 4% on 10 days between 24-Feb and 31-Aug-2022 in lme_daily.csv (−12.2% on 08-Mar-2022, −5.3% on 15-Mar), so the 4% narrow slab was a live constraint on MCX price discovery in the window; whether MCX actually invoked the 6%/9% relaxations on those days was not checked.

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

Owner: P0 freight/logistics · 26 parameters · DIRECT 3, PROXY 1, ASSUMPTION 22.

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
