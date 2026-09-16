# Regulatory, exchange-contract and physical-scrap research notes (Phase 0)

ACADEMIC SIMULATION — not actual trades. All counterparties are fictional (SIM).

Owner: Phase 0 regulatory/contract research. Parameters live in `config/params/regulatory.yaml`, `exchange.yaml`,
`scrap_grades.yaml`, `commercial.yaml`; the check status of each is in `docs/verification_log.md`. Everything below
was retrieved on 2026-09-16; cached copies are under `data/raw/regulatory/` unless stated otherwise. Flags follow
CONTRACTS §1.2: DIRECT = read in a named source for the 2022 period; PROXY = real observable standing in / transformed;
ASSUMPTION = judgement with reasons.

---

## 1. Why the duty differential creates the trade (trader view)

| Item (Mar–Aug 2022) | Primary aluminium, HS 7601 | Aluminium scrap, HS 7602 | Source / flag |
|---|---|---|---|
| Basic customs duty | 7.5% | 2.5% | 7601: First Schedule, PARTIAL; 7602: Notif. 50/2017-Cus S.No. 385, DIRECT |
| AIDC | — | nil | Notif. 11/2021-Cus has no ch. 76 entry, DIRECT |
| SWS | 10% of BCD → 0.75% of AV | 10% of BCD → 0.25% of AV | Finance Act 2018 s.110(3), DIRECT |
| Customs duty in cost | 8.25% of AV | 2.75% of AV | derived |
| IGST (creditable) | 18% (Sch. III S.No. 262) | 18% (Sch. III S.No. 263) | Notif. 1/2017-IT(R), DIRECT |

MCX Aluminium is delivered ex-warehouse Raipur, duty-paid, so it trades close to LME × USDINR × 1.0825 (the market-data
agent's calibration finds no systematic extra premium, `mcx_domestic_premium_inr_kg` = 0). A scrap importer pays only
2.75% on a base that is ~74–79% of LME. On window averages (LME 3M $2,851/t, USDINR 77.85, Tense CFR factor 0.736,
recovery 0.917 — register values after the Phase 0 review):

- duty embedded in the primary (MCX) price: 2,851 × 77.85 × 0.0825 ≈ **₹18,300 per t of metal**;
- duty actually paid on the scrap route: 2,098 × 77.85 × 0.0275 ≈ ₹4,490 per t of scrap ≈ **₹4,900 per t of metal**;
- tariff wedge ≈ **₹13,400/t of metal ≈ 6.0% of LME value** — before any grade discount.

The wedge (≈ ₹12,300 per t of Tense scrap) is a large, structural part of any margin — much of it is policy, not
skill. The previous illustrative margin (~₹18,000/t on an anchor premium of −₹18,000) is withdrawn: the anchor premium
is now −₹9,000 on a cash basis and strongly regime-dependent, so P1 must publish the weekly split as a band (CONTRACTS
§5 required sensitivities). That is why
the primary producers' association (AAI) keeps asking for higher scrap duty and why recyclers (MRAI) ask for its
removal (Tribune 08-Jul-2026: AAI wants 2.5% held until scrap standards exist, then 7.5% on lower grades;
https://www.tribuneindia.com/news/aluminium-quality/aluminium-association-of-india-urges-centre-to-notify-bis-standards-for-aluminium-scrap,
cached `data/raw/regulatory/news/`). The desk's
interview line: *the arbitrage is structural (tariff wedge + India's scrap deficit) and cyclical (grade discount
stickiness); only the second is a trading edge.*

**ITC.** Import IGST (18%) is paid on AV + BCD + SWS and is creditable for a GST-registered trader (Bill of Entry is an
ITC document), so it is excluded from landed cost (`igst_itc_available: true`, ASSUMPTION) and only its financing
matters: it is financed from the Bill of Entry to the GSTR-3B offset (`igst_credit_lag_days` = 45, ASSUMPTION) —
~18% × ₹2.3 lakh × 45/365 × 9.5–10% ≈ ₹500/t on either lane (CONTRACTS §5 `igst_finance_inr_t`). Primary imports get the same credit, so IGST does
not change the arb — but a desk with little output tax liability would carry a blocked-credit balance (a
working-capital, not P&L, risk).

## 2. Customs valuation and exchange rate

- **No landing charge.** Notification 91/2017-Customs (N.T.) (26-Sep-2017) substituted Valuation Rule 10(2): transport,
  loading, unloading and handling to the place of importation are included at actual; the old deemed 1% landing charge
  is gone → `landing_charges_frac = 0` (DIRECT, VERIFIED). Fallbacks in the same rule: freight not ascertainable → 20% of
  FOB; insurance not ascertainable → 1.125% of FOB (DIRECT). The 1.125% deemed insurance is ~10× the commercial premium
  (`insurance_rate` 0.10%) — a documentation discipline point, worth ~0.03% of FOB in extra duty.
- **Customs exchange rate.** Duty uses CBIC's fortnightly s.14 notification rate for imported goods (rate on the Bill of
  Entry date), not the market rate. All 15 USD-changing notifications Feb–Sep 2022 were read:

| Effective | Notification (2022-Cus (N.T.)) | USD import | USD export |
|---|---|---|---|
| 18-Feb | 10 | 76.05 | 74.35 |
| 04-Mar | 13 | 76.65 | 74.95 |
| 18-Mar | 18 | 76.90 | 75.20 |
| 08-Apr | 32 | 76.80 | 75.10 |
| 22-Apr | 34 | 77.15 | 75.45 |
| 06-May | 40 | 77.05 | 75.35 |
| 20-May | 43 | 78.60 | 76.90 |
| 03-Jun | 49 | 78.50 | 76.80 |
| 17-Jun | 51 | 78.95 | 77.25 |
| 08-Jul | 58 | 79.90 | 78.20 |
| 22-Jul | 64 | 80.95 | 79.20 |
| 05-Aug | 66 | 80.25 | 78.55 |
| 19-Aug | 70 | 80.50 | 78.80 |
| 02-Sep | 73 | 80.45 | 78.70 |
| 16-Sep | 78 | 80.40 | 78.70 |

  Amendments 16, 36, 38, 42, 53, 54, 83 and 85/2022 changed only lira, krone, rand, Swiss franc or sterling.
  Import − export is ₹1.70 in 13 of the 15 notifications and ₹1.75 in 64/2022 (80.95 / 79.20) and 73/2022 (80.45 /
  78.70) (corrected after review; the first version said "always ₹1.70"); versus the ECB-cross market rate on the notification date the import rate carries a
  mean +1.11% (range +0.78% to +1.36%); versus the average market rate over its validity, +0.68% (range −0.53% to
  +1.88%) → `customs_fx_markup_frac = 0.011` (PROXY). Trader implication: in a fast INR slide (e.g. the 06-May and 16-Sep
  validity periods) duty is briefly computed on a rate *below* market; after a rate reset it is computed on a rate
  ~1% above.

## 3. Compliance frictions in the window

1. **PSIC / radiation (DGFT HBP para 2.54).** DGFT Public Notice 46/2015-20 (14-Jan-2022): metallic scrap from the USA,
   UK, Canada, New Zealand, Australia and EU needs no Pre-Shipment Inspection Certificate if cleared at one of ten
   ports (Chennai, Tuticorin, Kandla, JNPT, Mumbai, Krishnapatnam, Mundra, Kattupalli, Hazira, Kamarajar), provided a
   supplier/scrap-yard certificate of no radioactive material/explosives accompanies it and it passes portal-monitor
   and container-scanner checks. Per the notice, imports through the remaining eight designated ports need a PSIC
   whatever the origin, and non-safe origins need one at every port. For the desk: **USEC → Mundra: no PSIC; Jebel Ali → Nhava Sheva: PSIC required**
   (UAE is not a safe origin). Status PARTIAL (read via worldtradescanner and bizsolindia republications, not the DGFT PDF).
2. **NFMIMS.** DGFT Notification 61/2015-20 (31-Mar-2021) made chapter-76 imports "Free subject to compulsory
   registration" on the Non-Ferrous Metal Import Monitoring System; secondary sources describe a 60-to-5-day
   pre-arrival registration window; DGFT Policy Circular 42/2015-20 (27-Jul-2022) clarified that one registration can
   cover multiple consignments and that air freight is outside NFMIMS. Coverage of 7602 lines in the annexure was not
   seen directly (PARTIAL). On a 5-day Gulf voyage, a missed registration is a demurrage trigger.
3. **BIS Quality Control Orders.** No QCO applied to aluminium scrap in 2022 (VERIFIED). The Mines ministry's first BIS
   technical regulations were the QCOs notified 31-Aug-2023 (PIB, 01-Sep-2023) for aluminium ingots/castings, EC-grade
   products, copper and nickel — not scrap — effective three months after notification; Argus (14-Nov-2025,
   https://www.argusmedia.com/en/news-and-insights/latest-market-news/2754022-india-scraps-bis-norms-on-some-metals) and
   ELP Law (https://elplaw.in/leadership/bis-update-withdrawal-of-qcos-for-certain-metals/) report those QCOs withdrawn
   (announced 13-Nov-2025). The scrap standard ("Aluminium & Aluminium Alloy Scrap – Requirements & Conditions of
   Delivery") had "remained pending for more than two years" in July 2026 (The Tribune / ANI, 08-Jul-2026, URL in §1),
   while BIS published IS 2066 (Part 1):2024 for scrap coding (search result, not opened). All four pages (PIB, Argus,
   ELP, Tribune) are cached under `data/raw/regulatory/news/` — the review found the Tribune and Argus sources had
   been cited without URLs.

## 4. The "BIS-QCO + demurrage" stress scenario (Table 6 row 4.2)

Because no scrap QCO existed, the scenario is a **hypothetical policy shock**: a QCO on imported aluminium scrap bites
on cargo already afloat. Inputs (all ASSUMPTION, `regulatory.yaml`):

| Parameter | Value | Reasoning |
|---|---|---|
| `qco_stress_delay_days` | 21 | One BIS sampling/test cycle plus re-filing; sits at the top of the logistics owner's 7–21 day clearance range. Drives demurrage via `demurrage_usd_per_box_day` beyond `detention_free_days` and 21 extra finance days. |
| `qco_stress_rejection_frac` | 0.10 | Clean ISRI Taint/Tabor and Tense likely conform to a grade standard; low-grade Zorba/mixed lots would not. 0.25 as a harsher sensitivity. |
| `qco_stress_rejected_loss_frac` | 0.15 of CIF | Onward freight, re-export paperwork and a distressed third-country sale. |

Why it is plausible for an interviewer: the primary lobby has pushed for scrap standards and higher scrap duty since at
least 2022–23, the ministry *did* impose QCOs on primary aluminium ~18 months after the window, and India imported
~2 Mt of scrap in FY26 (Tribune) — a large, politically visible flow.

## 5. MCX Aluminium contract (hedge instrument)

mcxindia.com returns HTTP 403 to scripted clients and the "April 2022 contracts onwards" spec PDF now serves an HTML
page, so the specification was read from the contract-launch circulars that embed it (browser + pdf.js text
extraction): **MCX/TRD/385/2021 (30-Jun-2021)** and **MCX/TRD/617/2022 (31-Oct-2022)**. Every contract traded in
Mar–Aug 2022 was launched between them and their Aluminium annexures are identical except for delivery centres.

| Field | 2022 value | Flag |
|---|---|---|
| Lot / quote / tick | 5 MT; ₹/kg ex-warehouse Raipur excl. GST; 5 paisa/kg (₹250/lot) | DIRECT |
| Max order | 150 MT | DIRECT |
| Hours | 09:00–23:30 IST (US summer) / 23:55 (US winter; MCX/TRD/646/2021) | DIRECT |
| Last trading day | last calendar day of month, else preceding working day; expiry-day trading to 17:00 | DIRECT |
| 2022 expiries | 31-Mar, 29-Apr, 31-May, 30-Jun, 29-Jul, **30-Aug**, 30-Sep, 31-Oct, 30-Nov (MCX Performance Reviews) | DIRECT |
| Daily price limits | 4% → 6% (no cooling-off) → 9% (15-min cooling-off) → +3% steps if international markets move more | DIRECT |
| Margins | IM minimum 8% or SPAN if higher; ELM minimum 1%; additional/special margin at exchange discretion | DIRECT (minima) |
| Additional margin on aluminium in 2022 | none found (Mar-2022 add-on of 2% was gold only, 08-Mar → 22-Mar) | PROXY/PARTIAL |
| Delivery | compulsory; 5 MT ±10%; staggered tender = last 5 trading days; delivery-period margin ≥ 25% | DIRECT |
| Deliverable | primary ingots ≥ 99.70%, LME-approved brands (sows/T-bars −₹1/kg) | DIRECT |
| Centres | Raipur (primary); additional Thane (2021) → Thane, NCR, Chennai, Kolkata (2022 circular) | DIRECT / PARTIAL on start month |
| FSP | average of polled spot on E0, E-1, E-2 | DIRECT |
| Aluminium Mini | **not tradable in 2022** — relaunched 20-Feb-2023 (MCX/TRD/104/2023), 1 MT | DIRECT |

Trader implications:

- **Roll before the tender period.** Compulsory delivery plus a 25% delivery-period margin means the desk rolls M1→M2 on
  the 7th trading day before expiry (`mcx_roll_days_before_expiry`, ASSUMPTION).
- **Cross-product basis.** The hedge is primary-ingot futures against scrap bought and alloy ingot sold. MCX itself
  reports near-month futures vs MCX spot hedge efficiency of only 14.00% (FY21-22) and 55.67% (FY22-23), basis std
  4.37 and 4.44 ₹/kg; the desk's residual basis is larger (see §9 on the alloy-ingot anchor).
- **DPL mattered.** LME official cash moved >4% on 10 days from 24-Feb to 31-Aug-2022 in the panel (−12.1% on
  08-Mar), so the 4% narrow slab was a live constraint.
- **Timing.** MCX closes at 23:30 IST, hours after the LME official (12:20–13:25 London), so daily MCX closes contain
  afternoon information the same day's LME official does not.

## 6. LME and FX conventions

- **Reference price.** LME Official Settlement Price = last cash offer in the second Ring, published 12:20–13:25 London
  (LME "Official Prices explained", current page — PARTIAL). Physical SPAs price off official cash; the Monthly
  Average Settlement Price (MASP) is the average of daily official cash settlement prices over the month's business
  days (LME Aluminium contract-spec page).
- **Desk pricing rule (ASSUMPTION):** provisional invoice on B/L, final = M+1 average of official cash × grade factor
  (`lme_m1_pricing_rule`). Parity (CONTRACTS §5) values FOB on 3M at contract date because 3M is what can be hedged then.
  Window Cash–3M spread from the panel: mean −$11.9/t (mild contango), monthly means −5.1 (Mar), −19.5 (Apr), −28.4
  (May), −22.1 (Jun), −6.4 (Jul), +7.2 (Aug); range −42 to +35. In contango the M+1 cash average sits below today's
  3M, so a buyer who priced M+1 and sold 3M earns the carry.
- **USD/INR hedging.** RBI A.P. (DIR Series) Circular No. 29 (07-Apr-2020): users hedge contracted/anticipated
  exposures with AD Cat-I banks, may freely cancel and rebook, and may book up to USD 10 mn notional without evidencing
  exposure (PARTIAL — summary read). A signed SPA is a contracted exposure → deliverable forwards for the full USD
  value. Bank margin over interbank is an ASSUMPTION (₹0.10/USD; range 0.03–0.25). The RBI's dedicated master direction
  on hedging commodity price risk in overseas markets came into force only on 12-Dec-2022 (search summaries) — after the
  window — which is one more reason the base case hedges on MCX rather than LME.

## 7. ISRI grade specifications (ISRI Scrap Specifications Circular 2022, effective 07/2022)

| Grade | ISRI description (short) | Numeric limits in the spec | Desk recovery inputs (ASSUMPTION) |
|---|---|---|---|
| **Zorba 95/5** (desk grade) | Shredded non-ferrous scrap, predominantly aluminium, from eddy current/air/flotation separation, passed over magnets; traded in India as "Zorba 95/5" (~95% Al / ~5% heavies — trade naming, not an ISRI definition) | Sold as "Zorba NN" = estimated % non-ferrous metal; free of radioactive material, dross, ash; no moisture number | moisture 0.01, contamination 0.06 (5% heavies + 1% other), melt yield 0.93 → recovery **0.866**; heavies 0.05 credited at 0.8 × LME Al |
| **Taint/Tabor** | Clean mixed old alloy sheet aluminium, two or more alloys, free of foil, blinds, castings, hair/screen wire, food/beverage containers, radiator shells, airplane sheet, bottle caps, plastic, dirt | Oil and grease ≤ 1%; up to 10% painted siding ("Tale") | 0.005, 0.02, 0.92 → **0.897** |
| **Tense** | Mixed aluminium castings (auto and airplane castings, no ingots), free of iron, brass, dirt, non-metallics | Oil and grease ≤ 2% | 0.005, 0.02, 0.94 → **0.917** |

Review fixes (2026-09-16): (1) the first version defined the desk grade as Zorba 90 (recovery 0.774, heavies ignored)
while pricing it off Zorba 95/5 quotes — the grade is now Zorba 95/5 throughout and its heavy-metal fraction is credited
(`heavies_net_value_frac_of_lme_al`, ASSUMPTION, PENDING a heavies price series); (2) melt yields were swapped so that
thin, partly painted sheet (Taint/Tabor) loses more than thicker castings (Tense), and Tense no longer carries an insert
deduction that ISRI's "free of iron" already excludes. Melt-loss figures remain engineering judgement (PENDING).

## 8. Grade factors: evidence, construction and market logic

**What was searched and not found.** Grade-specific 2022 India price quotes (Zorba / Taint-Tabor / Tense CIF Nhava
Sheva or Mundra) are behind Fastmarkets, Argus and BigMint paywalls; Fastmarkets' public CIF India assessments
(MB-AL-0396…0401) only started on 17-Apr-2024. Recycling International, recycleinme, scrapregister, AlCircle and
BigMint searches returned 2023–2026 articles only. **No 2022 grade quote is used anywhere in this register.**

**What was found (real, public):**

1. *Official 2022 import unit values* — Ministry of Commerce TRADESTAT (MEIDB), HS 76020010 ("aluminium scrap covered by
   ISRI code …", unit kg), monthly value (US$ mn) and quantity, Revised Final. Unit value (CIF $/t):

| Month (B/E) | All origins $/t (kt) | UAE $/t (kt) | USA $/t (kt) | UK $/t (kt) |
|---|---|---|---|---|
| 2022-01 | 2,267 (159.7) | 2,424 (14.8) | 2,143 (55.7) | 2,089 (15.3) |
| 2022-02 | 2,252 (129.3) | 2,548 (11.3) | 2,077 (39.5) | 2,074 (11.7) |
| 2022-03 | 2,302 (141.4) | 2,592 (16.0) | 2,103 (42.0) | 2,089 (10.9) |
| 2022-04 | 2,487 (129.6) | 2,799 (13.4) | 2,215 (38.0) | 2,342 (14.6) |
| 2022-05 | 2,486 (134.3) | 2,756 (12.1) | 2,270 (36.6) | 2,315 (16.5) |
| 2022-06 | 2,503 (132.8) | 2,773 (12.7) | 2,356 (35.8) | 2,327 (15.9) |
| 2022-07 | 2,345 (153.7) | 2,532 (13.6) | 2,226 (52.6) | 2,241 (13.6) |
| 2022-08 | 2,239 (154.1) | 2,304 (13.5) | 2,142 (48.7) | 2,144 (14.3) |
| 2022-09 | 2,107 (151.9) | 2,301 (14.7) | 2,012 (39.8) | 1,956 (18.8) |
| 2022-10 | 1,964 (141.2) | 2,240 (11.3) | 1,866 (42.8) | 1,855 (13.1) |
| 2022-11 | 1,996 (155.6) | 2,224 (12.5) | 1,904 (45.5) | 1,859 (16.6) |
| 2022-12 | 1,735 (169.5) | 2,153 (13.0) | 1,868 (40.3) | 815 (32.8) — UK row looks anomalous |

   HS 76020090 ("other") is negligible (near-zero tonnage) and ignored. UAE-origin cargo carries a consistently higher
   unit value and US/UK origins sit ~5–10% below the all-origin mean. The customs code does not split grades, so the
   reason is not observable here; a richer Gulf mix (extrusions, wheels) and Zorba-/HRB-heavy Atlantic mixes are
   plausible explanations, not verified ones.

   *Lag.* Customs values reflect prices fixed before shipment. Ratio of all-origin unit value to monthly LME 3M,
   Jan-2021–Dec-2022: std 0.089 with no lag, 0.064 (1 month), **0.044 (2 months)**, 0.045 (3 months) → 2-month lag
   (`grade_factor_lag_months`).

2. *India CFR grade quotes in 2024* (BigMint/SteelMint via AlCircle/BigMint pages) used only for grade *differentials*:
   24-Feb-2024 (3M $2,247): UK Zorba 95/5 $2,010 CFR Nhava Sheva (0.89), US Tense 6–7% $1,775 (0.79), UAE Tense $1,695
   (0.75); 05-Mar-2024 (3M ~$2,231): UK Zorba 95/5 $2,030 CFR Mundra (0.91), UAE Tense $1,790 CFR Mundra (0.80), deal US
   "TT HRB 3%" $1,800 CIF west coast (0.81); 31-Jul-2024 (3M $2,225): UK Zorba 95/5 $1,975 (0.89), UAE Tense $1,730
   (0.78). → Zorba 95/5 ≈ +10 points over Tense; US TT HRB with 3% attachments ≈ Tense.

3. *US scrap buying prices 2022* (USGS Mineral Industry Surveys, Aluminum, Table 7, source Fastmarkets–AMM) vs LME cash
   (Table 6), used for direction only:

| Month | Old sheet / LME cash | Old cast / LME cash |
|---|---|---|
| 2021-03 | 0.669 | 0.689 |
| 2021-09 | 0.519 | 0.525 |
| 2022-01 | 0.534 | 0.530 |
| 2022-03 | 0.537 | 0.522 |
| 2022-04 | 0.606 | 0.579 |
| 2022-05 | 0.599 | 0.606 |
| 2022-06 | 0.599 | 0.607 |
| 2022-07 | 0.585 | 0.599 |
| 2022-08 | 0.561 | 0.568 |
| 2022-09 | 0.626 | 0.625 |

**Construction (revised after review — one CFR-India base; code: `desk/data/fetch_price_evidence.py`, tables in
`data/interim/price_evidence/`).**
- *Mix ratio (PROXY):* R(m) = all-origin unit value in m+2 ÷ LME 3M mean in contract month m (`grade_factor_mix`).
  No freight is netted out: the unit value is CIF and the grade quotes are CFR, so the grade factor is a CFR-India
  factor shared by both lanes (CONTRACTS §5 CFR parity). Lag-1, lag-3 and point-in-time (UV(m−1)/LME(m−3)) paths are
  published as sensitivities because UV(m+2) is released months after m (hindsight).
- *Differentials (ASSUMPTION, evidence PROXY):* 51 dated BigMint prices from 23 AlCircle articles (14-Feb-2024 →
  18-Dec-2025; exact sentences asserted against the cached pages), each divided by Westmetall LME 3M on the trading day
  before publication, converted to an ISRI-clean basis by ÷(1 − stated attachments) (BigMint labels UAE Tense
  "8-9 per cent", US Tense "6-7 per cent", US Taint/Tabor HRB "2-3 per cent"), minus the lag-2 mix of the quote month.
  Medians: **Zorba 95/5 −0.022** (n=15), **Taint/Tabor −0.018** (n=8; two UK "C/S 9-10%" prints excluded as an
  undefined sub-grade), **Tense −0.068** (n=28); registered rounded to 0.005: −0.02 / −0.02 / −0.07. As-quoted (no
  attachment adjustment) the medians are −0.022 / −0.028 / −0.124.
- Why the first version was wrong: it added +0.02 / 0.00 / −0.03, measured against a "three-grade average" of three
  2024 quotes (using the articles' own LME figures, two of which did not match date-matched Westmetall 3M), to a DGCIS
  all-grade mix net of an unweighted two-lane freight mean — two different bases.

| Contract month m | DGCIS UV m+2 $/t | LME 3M avg m $/t | Mix R(m) | Zorba 95/5 | Taint/Tabor | Tense |
|---|---|---|---|---|---|---|
| 2021-12 | 2,252 | 2,694 | 0.836 | 0.816 | 0.816 | 0.766 |
| 2022-01 | 2,302 | 3,000 | 0.767 | 0.747 | 0.747 | 0.697 |
| 2022-02 | 2,487 | 3,224 | 0.771 | 0.751 | 0.751 | 0.701 |
| 2022-03 | 2,486 | 3,543 | 0.702 | 0.682 | 0.682 | 0.632 |
| 2022-04 | 2,503 | 3,276 | 0.764 | 0.744 | 0.744 | 0.694 |
| 2022-05 | 2,345 | 2,855 | 0.821 | 0.801 | 0.801 | 0.751 |
| 2022-06 | 2,239 | 2,585 | 0.866 | 0.846 | 0.846 | 0.796 |
| 2022-07 | 2,107 | 2,408 | 0.875 | 0.855 | 0.855 | 0.805 |
| 2022-08 | 1,964 | 2,424 | 0.810 | 0.790 | 0.790 | 0.740 |
| 2022-09 | 1,996 | 2,243 | 0.890 | 0.870 | 0.870 | 0.820 |

Window (Mar–Aug contract months) means: mix 0.806; Zorba 95/5 0.786, Taint/Tabor 0.786, Tense 0.736 (CFR India).
Sensitivity means: lag-1 mix 0.841, lag-3 0.777, point-in-time 0.777.

**Lane pricing.** UAE-origin unit values sit well above US/UK ones in every month (table above), but the customs code
does not split grades, so an origin-specific factor would mix grade mix with origin. The desk therefore imposes CFR
parity (one CFR price per grade for both lanes) and lets the lanes differ only by port, PSIC, finance days and actual
freight on FOB-term trades.

**Against the spec's guide.** Zorba ~75–85%: consistent. **Taint/Tabor ~88–92%: not supported** by any retrieved
evidence (2022 official unit values, 2024 India quotes, or 2022 US buying prices at 0.54–0.61 of LME) — flagged in
`scrap_grades.yaml` with a recommended +0.10 sensitivity.

**How discounts move in a falling market (documented direction, two independent datasets).** Scrap prices are sticky:
- LME spike (Mar-2022 contracts, 3M avg $3,543): Indian CIF ratio fell to **0.70**; US old sheet/LME 0.537.
- Crash (May–Jul-2022): Indian ratio rose to **0.82 → 0.87 → 0.88**; US old sheet/LME ~0.60.
- Stabilisation (Aug-2022): Indian ratio eased to **0.81**; US 0.561 — buyers widened discounts once LME stopped falling.
- The 2021 rally showed the mirror image in US data (old sheet/LME 0.669 → 0.519).

So "% of LME" discounts **narrow in a crash and widen in a rally**; absolute USD discounts move the other way less
dramatically. A buyer on %-of-LME terms in a crash pays for that stickiness; sellers prefer fixed USD offers when LME is
falling. The desk's M+1 LME-linked SPA protects the buyer on flat price but not on this ratio.

## 9. Conversion cost and the domestic anchor

- **Anchor premium (ASSUMPTION −₹9,000/t, revised after review).** No 2022 ADC12/LM6 India series was retrievable.
  15 dated BigMint ADC12 ex-Delhi prices (01-Dec-2023 → 11-Dec-2025, AlCircle; OEM-approved prints moved to non-OEM by
  the ₹8,000 gap printed on 05/11-Dec-2024) against duty-paid LME **cash** parity on the day before publication (the
  basis of the panel's MCX proxy): median **−₹8,955**, mean −₹16,422, range −₹52,068 … +₹12,861. The premium is strongly
  regime-dependent (correlation with parity −0.93; short-run pass-through of parity into ADC12 **0.15**): +₹5–13k in
  H1-2024 at parity ~₹191–205k, −₹34–52k in late 2024–25 at ~₹235–276k. The previous −18,000 was the mean of two points
  on a 3M basis with the articles' own LME figures. CRISIL's undated "secondary aluminium 25-30% cheaper than primary"
  has no price basis and is kept only as the low-end sensitivity (−₹55,000). P1 publishes a band
  (`domestic_anchor_premium_sensitivity_inr_t`) and a sticky variant (trailing 120-LME-day parity − ₹2,000).
- **Conversion cost (ASSUMPTION ₹12,000 per t of INGOT, range 8–18k; unit fixed after review).** From the same spreads:
  1 t alloy needs ~1.11 t Tense (₹191.7k at ₹172.5k/t) against an alloy price of ₹201–209k → ₹9–17k per t of ingot.
  CONTRACTS §5 multiplies by recovery (≈ ₹10,760 per t of Tense scrap). CRISIL Research (Sept 2021) puts scrap at
  80–85% of a secondary producer's total cost including taxes and duties — a broader cost base kept as a ₹30,000 upper
  sensitivity. Same report: 85–90% of India's scrap is imported (FY2020).
- **Domestic vs imported scrap (2024 PROXY).** Domestic Tense ₹172,500/t ex-Delhi vs UAE Tense $1,695 CFR landed ≈
  1,695 × 82.90 × 1.0275 + ₹2,650 ≈ ₹147,000/t → imports were the cheaper marginal feed.
- **Margin hurdle (ASSUMPTION ₹5,000/t)** ≈ 2% of landed cost: covers expected SPA quality claims, residual basis over a
  ~6-week cycle and some demurrage.
- **Plausibility check (review, scratch calculation of CONTRACTS §5 with the revised register — not a P1 result).**
  With the constant premium, net arb runs ~+₹44–71k/t in March 2022 and near zero for Zorba/Taint-Tabor in June–July,
  Tense stays open every week; with the sticky (trailing-parity) anchor the pattern inverts (thin or negative in early
  March, +₹40–60k/t in June–August). Neither single path is plausible as a container-scrap margin: the swing comes from
  combining a lagged scrap price (the DGCIS mix) with an anchor whose 2022 stickiness is unobserved. The 2022 import
  volume path (DGCIS HS 76020010 arrivals 141→130→134→133→154→154 kt, Mar–Aug) fits the sticky variant's rising
  May–June margins better, but that is not evidence enough to change the base. P1 must report the band.

## 10. Trade finance and SPA terms

- SBI card rates w.e.f. 01-Apr-2022 (DIRECT, SBI schedule): import LC issuance **0.08% per month** (min ₹2,000; was
  0.18% for 3 months + 0.08%/month); usance charge **0.07% per month**; import bill commission **0.12%** (+0.10% if FX
  not converted with SBI); SBI's own LC-confirmation card 0.25% / 0.50% / 0.75% p.a. by issuing-bank rating (PROXY for
  a foreign bank confirming an Indian LC).
- RBI trade-credit all-in-cost ceiling: benchmark ARR + 300 bps from 08-Dec-2021 (Argus Partners summary, PARTIAL);
  desk usance spread assumed 150 bps.
- SPA template (ASSUMPTION): 1% moisture franchise, deduction 1:1 above; 1.5× discount on non-metallic excess up to 3
  points, rejection beyond; lab-tested free Zn/Mg/Fe limits for Zorba; radioactivity/explosives → outright rejection
  with all costs to seller, tied to the DGFT certificate/PSIC regime. Domestic credit 30 days (spec); MSMED Act s.15
  caps agreed credit at 45 days where the supplier is a registered micro/small enterprise (DIRECT).

## 11. Failed attempts (for the record)

- `cbic.gov.in` is an Angular SPA; legacy PDF paths return 404; `old.cbic.gov.in` does not resolve; ICEGATE's
  exchange-rate lookup needs a CAPTCHA (not attempted) and its notification list starts in 2024. Solved via the CBIC
  Tax Information Portal API.
- CBIC and CMR servers omit TLS intermediates → added the AIA intermediates (Sectigo OV R36, GlobalSign GCC R6 AlphaSSL
  2025) to a CA bundle instead of disabling verification.
- mcxindia.com: Akamai 403 for curl/requests/WebFetch; 2022 spec PDFs retired → browser + circular annexures.
- lme.com: 403 for WebFetch; read in browser (current pages only). Wayback Machine was offline ("Temporarily Offline").
- DGFT portal pages (JS) and the RBI bulletin forward-premia table were not retrieved.
- PIB 403 for WebFetch; read in browser. Business Standard and scrapregister: 403. bbhushan.in: connection refused.
- Paywalled: Fastmarkets, Argus, BigMint 2022 archives (grade quotes); Global Trade Alert (login).

## 12. Open issues (hand-off)

1. Grade differentials (now −0.02 / −0.02 / −0.07 from 2024–25 quotes) and the TT-vs-spec contradiction need 2022 grade
   quotes; the heavies value of Zorba 95/5 needs a price series.
2. `domestic_anchor_premium_inr_t` is regime-dependent (sticky alloy prices, pass-through 0.15 in 2023–25); a 2022
   ADC12 series is the single most valuable missing input. P1 runs the band and the sticky variant.
3. DGFT originals (PN 46/2015-20; Notification 61/2015-20 annexure incl. 7602 lines) not fetched.
4. `bcd_primary_al_hs7601`: read chapter 76 of the First Schedule as amended by the Finance Act 2022.
5. MCX actual SPAN margins and any aluminium clause inside 2022 multi-commodity margin circulars.
6. USD/INR forward premia (RBI Bulletin) and an LME official-price spot check for the Cash–3M series.
7. Melt-loss / yield assumptions and conversion cost lack an Indian 2022 cost disclosure.
