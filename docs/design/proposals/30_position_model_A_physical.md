# 30 — Position & valuation model — Proposal A (physical trader / trade-operations angle)

> **ACADEMIC SIMULATION — not actual trades.** Every counterparty, vessel, forwarder, bank and operational outcome in
> this document is fictional and labelled (SIM). Example prices are test fixtures, not calibrated Phase 2 terms.
>
> Status: design proposal for the synthesizer (target `docs/design/30_position_model.md`). No code. Binding upstream:
> CONTRACTS.md §1, §3, §5, §5a, §6, §7; MASTER_SPEC_V3 Tables 4–6; Phase 0 register; Phase 1 helpers
> (`desk.parity.model.eligible_on`, `desk.parity.term_structure.prompts/forward_price`,
> `desk.parity.quality.settle_weight_and_penalty`, `config/params/parity.yaml`).

---

## 0. Decisions at a glance

| # | Decision | Why |
|---|---|---|
| D1 | **One ticket = one purchase SPA** with 1–3 container **lots** (one B/L each) inside a shipment period (the container "laycan") that sits in **one calendar month**. Sales cover whole lots. | Mirrors how a 1,000–5,000 MT container contract actually ships (several sailings); one-month laycan makes the M+1 quotational period (QP) known on the contract date. |
| D2 | **Cumulative P&L = realised cash + undiscounted MTM of remaining projected cashflows** of *booked* legs. A flow's amount is taken from history once its fix date ≤ valuation date, otherwise projected from the market state. | CONTRACTS §7.3; one code path produces the deal sheet, the MTM, the ledger and the Monte Carlo revaluation. |
| D3 | **Funding = explicit daily interest at `wc_rate_inr_pa` on the trade's actual signed cash balance** (incl. MCX initial margin). Realised daily; the future part is projected inside MTM at the rate in force. The engine **never reads `finance_days_*`**. | Real CC-line economics; buyer credit, usance, IGST lag, demurrage delay and margin calls are financed exactly once because they are dated flows, not a day-count shortcut. |
| D4 | **Unsold scrap is marked at landed replacement value** (CFR market = `grade_factor_<g>` × LME 3M, market FX, duty, port, PSIC) — never at the smelter netback (anchor). | Risk-manager rule: mark to the nearest observable market; the arb margin is booked when the scrap is **sold**. Keeps the weakest assumption (anchor premium) out of MTM. |
| D5 | **MCX = duty-paid LME parity + contract basis β.** β is backed out of the MCX series each day. Under the panel proxy β ≈ 0, so factor (b) is ≈ 0 by construction; with the mirror / bhavcopy series β is the real LME–MCX basis. | Hedges never show fake basis: an MCX move explained by LME goes to (a), by USD/INR to (e), by carry/spread to (g), the rest to (b). |
| D6 | **Seven market blocks swapped sequentially in `FACTOR_ORDER`**; (f) is the *operational information set*; (g) is Cash–3M spread + INR/USD rates + WC rate + **calendar** (fixings, settlements, time decay). `new_deal` = value of bookings made on day t **at the day-t market**; ROLL bookings go to (g). | Zero residual by telescoping; bookings valued at yesterday's prices would book the day's market move as deal margin. |
| D7 | **Operational outcomes are revealed without hindsight**: until an event happens (or a dated notice announces it) the engine uses the planned schedule; an overdue milestone rolls forward one panel day at a time. | Demurrage accrues day by day; a late buyer payment costs one more day of funding each day it is late. |
| D8 | **FX:** physical USD flows convert at spot (realised) or CIP forward (projected) ± `fx_forward_bank_margin_inr`; USD/INR forwards are struck at the mid CIP forward and valued/settled as cash-settled equivalents of deliverable forwards. | Bank margin paid once; forward-book offset is a clean leg-level number for adverse event #2. |
| D9 | **Freight:** only **unbooked FOB freight** is a live exposure (factor d). A booked fixture is a fixed payable; fixture-vs-index is a daily **memo** and a counterfactual (event #3). | Under CONTRACTS §5 CFR parity the cargo's value does not depend on freight; a CFR buyer has no freight price risk. |
| D10 | **Exposures by central bump-and-revalue of the same valuation function**; Monte Carlo passes numpy arrays through the same API. | Risk numbers can never disagree with P&L. |
| D11 | **Adverse-event windows are computed from data rules**; impacts = window sums of attribution buckets + counterfactual books (hedges removed / SIM events removed / freight floating). | Table 5 rows 3.4–3.6 with isolated, reproducible numbers. |
| D12 | **The engine never trades.** Every hedge, fixture, sale and mitigation is a dated booking in the ticket; rule-based decisions (freight stop-loss, MCX roll deadline) are re-derived point-in-time by the validator. | No hindsight in decisions (Table 4 row 2.9, CONTRACTS §5a). |

---

## 1. How these deals actually run (trader's primer — every field below exists because of this)

**1.1 The SPA.** A Gulf trader (Jebel Ali) or US yard/processor (Savannah/NY) offers e.g. "1,040 MT Zorba 95/5, ISRI
2022 spec, 40×20ft, shipment 1–15 April, CFR Nhava Sheva, USD 2,330/t, LC at sight". Clauses that move money:
ISRI grade and non-metallic limit; moisture franchise (desk template 1%, oven-dry joint survey, 1:1 weight deduction
above it); non-metallic excess → 1.5× price discount up to 3 points, rejectable beyond; radioactivity/explosives →
outright rejection, all costs for seller, tied to the DGFT certificate or PSIC regime (UAE origin needs a PSIC; US
origin into Mundra does not — `regulatory.yaml`); quantity tolerance (MOLSO ±5%); pricing (fixed USD, or % of LME
official cash averaged over the month after the B/L month, with provisional invoice on B/L and final invoice after
the QP); payment instrument.

**1.2 LC mechanics.** The importer's AD bank opens an irrevocable LC (UCP 600) a few days after signing, sized on
provisional value + tolerance; the SBI card (w.e.f. 01-Apr-2022, DIRECT) charges 0.08% per month-or-part of validity
on issuance, 0.07% per month on usance, 0.12% commission on retirement. US yards often demand confirmation (priced
here at a BBB-band 0.50% p.a., PROXY). *Sight:* seller presents B/L, invoice, weight list, PSIC/radiation certificate
~a week after B/L; bank pays after document examination; the desk's INR is debited. *Usance 60–90d from B/L:* bank
accepts the draft, releases documents, pays at maturity; the importer pays usance interest (benchmark + spread,
capped by RBI's trade-credit all-in ceiling) and the usance commission.

**1.3 Shipment and M+1 pricing.** Containers are stuffed and sail across the shipment period, usually on 2–3
sailings (our lots). The B/L date drives everything: LC presentation, usance maturity, the QP month (M+1), insurance
attachment. With a calendar-month shipment period the QP is fixed on the contract date. The seller invoices
provisionally (e.g. 90% of factor × LME cash on B/L date) under the LC; after the QP the final invoice (factor ×
QP average + premium, on out-turn weight less quality claims) is settled by TT — often a refund in a falling
market, which is itself a supplier credit exposure.

**1.4 Discharge.** Arrival → radiation portal → CFS de-stuffing → joint survey (weight, moisture, non-metallics).
Rejected boxes (radiation, wrong grade) are excluded from the Bill of Entry and re-exported for seller's account.
Claims are netted into the final invoice (LME-priced) or settled by supplier credit note (fixed price).

**1.5 Port and tax.** BoE filed after documents are released and the vessel has arrived; BCD 2.5% + SWS 10% of BCD on
assessable value at the CBIC notified rate for the BoE date; IGST 18% paid with the BoE and recovered as ITC through
GSTR-3B (~45 days later, `igst_credit_lag_days`). Price-linked imports are provisionally assessed and the differential
duty paid on finalisation. Out-of-charge → CFS delivery → truck to buyer. Carrier detention + CFS ground rent start
after free time (14 days negotiated) at ~USD 35/box/day first slab; July-2022 void calls at Nhava Sheva/Mundra
(Container News 27-Jul-2022, freight_notes S4) are exactly the kind of disruption that burns free time.

**1.6 Domestic sale.** Rajkot/JNPT-belt smelters and foundries buy either at a fixed ₹/t ("FOR works") or at MCX
near-month average over an agreed window × a recovery-type factor + premium; weak names pay advance, established
names get 30 days (spec). MSMED Act s.15 caps agreed credit at 45 days where the *supplier* is a registered
micro/small enterprise — not binding on a mid-size desk selling to MSMEs, but kept as a policy cap.

**1.7 Hedging reality in 2022.** Offshore LME hedging by a resident SME importer was not a practical route (RBI's
dedicated master direction on hedging commodity price risk overseas came into force only on 12-Dec-2022 — search
summaries, regulatory_contract_notes §6), so the desk hedges on **MCX Aluminium** (5 MT lots, compulsory delivery,
roll before the 5-day tender period). What drives hedge design:
- *Pricing-period mismatch.* Purchase priced on LME cash M+1 average, sale priced on MCX over a later window: the
  desk is exposed only while one leg is priced and the other is not. The hedge is sold as purchase days fix and
  bought back as sale days fix (or sold at contract for a fixed-price purchase, lifted when the sale prices).
- *MCX ≈ LME cash × USD/INR × 1.0825.* A short MCX position is short LME **and short USD**. MCX locks the rupee value
  of metal; the USD payable then needs its own USD/INR forward. Conversely an unpriced MCX-linked sale is a natural
  long-USD offset to the USD payable. The FX hedge must be sized **net of the MCX position** — the exposures table
  (§6) does this arithmetic.
- *Floating-price back-to-back still carries metal risk:* sale factor × 1.0825 (≈0.99 for Tense at 0.917) exceeds the
  purchase factor (≈0.70), so the margin itself is LME-linked (~0.3 MT-eq per MT of scrap).
- *Freight:* CFR = seller books and bears freight cost; FOB = desk (via NVOCC) books and bears it. No India-lane
  freight derivative was accessible, so the "freight hedge" is an early fixed-rate booking, or float with a stop-loss.

---

## 2. Ticket schema — `config/trades.yaml` and `config/counterparties.yaml` (P2 owns both files)

### 2.1 Conventions
- Dates: ISO `YYYY-MM-DD`. **Decision dates** (`trade_date`, `lc_open_date`, hedge open/close, sale `booking_date`,
  freight `booking_date`, forward booking/cancel, mitigation dates) must be panel (LME) days. **Derived cashflow dates**
  roll *following* to the next panel day (CONTRACTS §3 LME calendar; MCX holidays not modelled).
- Amounts in the unit named by the key suffix (`_usd_t`, `_inr_t`, `_inr_kg`, `_mt`, `_usd`, `_inr`, `_frac`, `_pa`).
  `_pts` never used (fractions only, matching `parity.yaml`).
- Names of counterparties, vessels, forwarders, banks end in `(SIM)`; no real carrier/bank brand names.
- `null` or absent optional field → the default rule stated in the table. Unknown keys raise.
- Ids: `trade_id` `^T\d{2}$`; `lot_id` `^L\d$`; `sale_id` `^S\d$`; `tranche_id` `^H\d[a-z]?$`; `fwd_id` `^F\d$`.

### 2.2 Ticket — top level

| Field | Type | Unit | Req | Allowed / default | Validation / notes |
|---|---|---|---|---|---|
| `trade_id` | str | — | Y | unique | |
| `status` | enum | — | Y | `EXECUTED` \| `DRAFT` | only EXECUTED enters the book |
| `trade_date` | date | — | Y | panel day in `[WINDOW_START, WINDOW_END]` | §5a: `eligible_on(trade_date, grade, lane)` must be True |
| `lane` | enum | — | Y | `JEA_NSA` \| `USEC_MUN` | fixes box type (20ft/40ft), ports, transit, PSIC |
| `grade` | enum | — | Y | `zorba` \| `taint_tabor` \| `tense` | Zorba = Zorba 95/5 |
| `quantity_mt` | float | MT | Y | 1,000–5,000 (spec 2.1) | = Σ `lots[].bl_weight_mt` (±0.001) |
| `purchase` | map | | Y | §2.3 | |
| `shipment` | map | | Y | §2.4 | |
| `freight` | map | | FOB only | §2.5 | must be absent for CFR |
| `sales` | list | | Y | §2.6 | every lot covered exactly once |
| `hedges` | map | | Y | §2.7 (may be empty lists + `unhedged_reason`) | |
| `ops` | map | | Y | §2.8 (SIM outcomes) | |
| `rationale` | map | | Y | §2.9 | |

### 2.3 `purchase` (SPA terms — spec 2.2–2.6)

| Field | Type | Unit | Req | Allowed / default | Validation / notes |
|---|---|---|---|---|---|
| `supplier_id` | str | — | Y | key in counterparties, role SUPPLIER | lane ∈ supplier `lanes` |
| `spa_ref` | str | — | Y | e.g. `"SPA/USEC/2205-03 (SIM)"` | |
| `incoterm` | enum | — | Y | `CFR` \| `FOB` | CFR: seller books + bears freight cost; desk bears transit risk from loading (insures). FOB: desk books + bears freight cost and transit risk. |
| `named_place` | str | — | Y | CFR → discharge port; FOB → load port | |
| `grade_spec.isri_name` | str | — | Y | `"Zorba 95/5"` \| `"Taint/Tabor"` \| `"Tense"` | |
| `grade_spec.spec_ref` | str | — | Y | `"ISRI Scrap Specifications Circular 2022"` | |
| `grade_spec.contamination_limit_frac` | float | frac | N | default `contamination_frac_<grade>` | P1 `settle_weight_and_penalty` limit |
| `moisture_franchise_frac` | float | frac | N | default `standard_moisture_franchise_frac` | |
| `quality_schedule` | enum | — | N | `DESK_STANDARD` | = `spa_moisture_deduction_ratio`, `spa_contamination_discount_multiple`, `spa_contamination_rejection_excess_frac` (parity.yaml) |
| `radioactivity_clause` | enum | — | N | `STANDARD` | text = `commercial.yaml radioactivity_clause` |
| `psic_required` | bool | — | N | derived: `JEA_NSA`→true, `USEC_MUN`→false | validator recomputes from `psic_required_*` |
| `quantity_tolerance_frac` | float | frac | N | 0.05 | informational; not exercised (§9) |
| `pricing.type` | enum | — | Y | `FIXED` \| `LME_AVG` \| `LME_ON_DATE` | |
| `pricing.price_usd_t` | float | USD/t | FIXED | > 0 | basis = incoterm |
| `pricing.lme_reference` | enum | — | LME_* | `CASH` (official settlement) \| `3M` (official 3M) | base book uses CASH (exchange.yaml) |
| `pricing.qp_rule` | enum | — | LME_AVG | `M_PLUS_1_OF_BL` \| `EXPLICIT` | M+1: QP = month after laycan month |
| `pricing.qp_start`, `qp_end` | date | — | LME_AVG | M+1 → first/last calendar day of that month | QP start > `trade_date` (no priced-in-past); averaging days = panel LME days in [start,end] |
| `pricing.pricing_date` | date | — | LME_ON_DATE | ≥ `trade_date` | |
| `pricing.factor_frac` | float | frac of LME ref | LME_* | 0.4–1.0 | |
| `pricing.premium_usd_t` | float | USD/t | LME_* | default 0 (may be negative) | |
| `pricing.provisional_rule` | enum | — | LME_* | `LME_CASH_ON_BL` | P_prov = factor × cash(B/L date) + premium |
| `pricing.provisional_payment_frac` | float | frac | LME_* | default `provisional_payment_frac_default` (proposed 0.90) | |
| `pricing.terms_basis_note` | str | — | Y | how price/factor was set with info ≤ `trade_date` (e.g. PIT factor) | reviewed, not parsed |
| `payment.instrument` | enum | — | Y | `LC_SIGHT` \| `LC_USANCE` | |
| `payment.usance_days` | int | days | USANCE | 60–90, counted from B/L date | spec 2.6 |
| `payment.lc_open_date` | date | — | Y | `trade_date` ≤ d ≤ `laycan_start` − 3 | |
| `payment.lc_issuing_bank` | str | — | Y | `"Indian AD Cat-I bank (SIM)"` | |
| `payment.lc_confirmed` | bool | — | N | default: supplier `lc_confirmation_required` | |
| `payment.confirmation_charges_for` | enum | — | if confirmed | `APPLICANT` \| `BENEFICIARY` | only APPLICANT creates a desk flow |

### 2.4 `shipment` (spec 2.1, 2.8)

| Field | Type | Unit | Req | Allowed / default | Validation / notes |
|---|---|---|---|---|---|
| `laycan_start`, `laycan_end` | date | — | Y | same calendar month; span ≤ `typical_laycan_days` + 1 | `laycan_start` ≥ `trade_date` + 7 (PSIC/stuffing lead) |
| `load_port` | str | — | Y | JEA_NSA → `"Jebel Ali, UAE"`; USEC_MUN → `"Savannah, USA"` \| `"New York, USA"` | |
| `discharge_port` | enum | — | Y | `NHAVA_SHEVA` (JEA_NSA) \| `MUNDRA` (USEC_MUN) | |
| `lots[].lot_id` | str | — | Y | L1..L3 | |
| `lots[].boxes` | int | boxes | Y | ≥ 1 | |
| `lots[].bl_weight_mt` | float | MT | N | default `boxes × container_payload_mt_<box>_<grade>` | |
| `lots[].bl_date_planned` | date | — | Y | within laycan | |
| `lots[].vessel`, `voyage` | str | — | Y | `(SIM)` suffix | |

### 2.5 `freight` (FOB only — spec 2.3, 2.7d, 2.8)

| Field | Type | Unit | Req | Allowed / default | Validation / notes |
|---|---|---|---|---|---|
| `booked_by` | enum | — | Y | `DESK_NVOCC` | |
| `forwarder` | str | — | Y | `(SIM)` | |
| `payment_terms` | enum | — | Y | `PREPAID` (paid at B/L release) \| `COLLECT` (paid at arrival before DO) | |
| `risk_layer` | enum | — | Y | `FIXED_AT_TRADE` \| `FLOAT_STOP_LOSS` | |
| `booking_date` | date | — | Y | FIXED_AT_TRADE: = `trade_date`. FLOAT: validator recomputes = first panel day d ∈ [trade_date, latest_booking_date] with `freight_<lane>_usd_t(d) × container_payload_mt_<box>` ≥ `stop_ref_usd_per_box × (1 + stop_loss_frac)`, else `latest_booking_date` | point-in-time freight column (already PIT-aligned; level is a hindsight reconstruction) |
| `rate_usd_per_box` | float | USD/box | FIXED | fixture; FLOAT → engine sets = index on booking_date | |
| `index_usd_per_box_at_booking` | float | USD/box | derived | `freight_<lane>_usd_t(booking) × container_payload_mt_<box>` | written to trade_hedges.csv, not typed |
| `stop_ref_usd_per_box` | float | USD/box | FLOAT | derived = index on `trade_date` | |
| `stop_loss_frac` | float | frac | FLOAT | default `freight_stop_loss_frac` (proposed 0.15) | |
| `latest_booking_date` | date | — | FLOAT | default `min(bl_date_planned) − freight_booking_days_before_bl` | |
| `unhedged_note` | str | — | FLOAT | one line: why float, stop-loss level | spec 2.7d |

### 2.6 `sales[]` (domestic sale — spec 2.5–2.6, Table 5)

| Field | Type | Unit | Req | Allowed / default | Validation / notes |
|---|---|---|---|---|---|
| `sale_id` | str | — | Y | | |
| `buyer_id` | str | — | Y | role BUYER; `lanes` ∋ lane | credit limit check at booking (warning, P5 flags) |
| `booking_date` | date | — | Y | `trade_date` ≤ d ≤ planned arrival of each covered lot | no short sales; sale must exist before cargo lands |
| `lot_ids` | list | — | Y | whole lots, disjoint across sales | |
| `delivery_basis` | str | — | Y | e.g. `"FOR buyer's works, Rajkot (SIM)"` | port/haulage already in `port_cf_charges_*` |
| `pricing.type` | enum | — | Y | `FIXED` \| `MCX_AVG` | |
| `pricing.price_inr_t` | float | ₹/t scrap | FIXED | > 0 | |
| `pricing.mcx_series` | enum | — | MCX_AVG | `NEAR_MONTH_CLOSE` | M1 close each panel day |
| `pricing.qp_by_lot` | map lot→[start,end] | dates | MCX_AVG | start ≥ `booking_date`; end ≤ planned delivery of that lot | price known at invoice |
| `pricing.mcx_factor_frac` | float | frac | MCX_AVG | typically `recovery_frac_g` | "recovery/scrap discount basis" |
| `pricing.premium_inr_t` | float | ₹/t | MCX_AVG | may be negative | |
| `pricing.terms_basis_note` | str | — | Y | derivation with data ≤ booking_date (recommended helper §2.11) | |
| `payment.terms` | enum | — | Y | `CREDIT` \| `ADVANCE` | ADVANCE only with FIXED pricing |
| `payment.credit_days` | int | days | CREDIT | default `domestic_buyer_credit_days`; ≤ `msme_max_payment_days` (policy cap) | from delivery (invoice) date |
| `payment.advance_days_before_delivery` | int | days | ADVANCE | default `advance_days_before_delivery` (proposed 2) | never before `booking_date` |
| `mitigation[]` | list | — | N | `{date, action: CREDIT_HOLD \| SWITCH_TO_ADVANCE, lot_ids, note}` | `date` ≥ the `known_date` of the triggering notice; used by event #3 |

### 2.7 `hedges` (spec 2.7 a–c)

**MCX tranches** — one row per (contract, direction, lot count) with its own open and close:

| Field | Type | Unit | Req | Allowed / default | Validation / notes |
|---|---|---|---|---|---|
| `mcx[].tranche_id` | str | — | Y | | |
| `mcx[].contract_month` | `YYYY-MM` | — | Y | listed month | |
| `mcx[].direction` | enum | — | Y | `SELL` (short) \| `BUY` (long) | |
| `mcx[].lots` | int | lots (5 MT) | Y | ≥ 1; Σ open ≤ `mcx_al_position_limit_client_mt`/5 | |
| `mcx[].open_date`, `close_date` | date | — | Y | open ≥ `trade_date`; close ≤ DIRECT expiry (`mcx_al_expiry_dates_2022`) minus `mcx_roll_days_before_expiry` panel days | never in tender period |
| `mcx[].open_purpose`, `close_purpose` | enum | — | Y | `HEDGE` \| `ROLL` | ROLL pairs: a close and an open on the same date, same direction, next contract, Σ lots equal |
| `hedge_ratio_target` | float | frac | Y | e.g. 1.0 | actual = −(MCX LME-eq delta)/(physical LME-eq delta) at each booking (§6); |target − actual| ≤ 1 lot-equivalent or warning |
| `exposure_basis` | enum | — | Y | `NET_LME_EQ_DELTA` | |
| `basis_risk_note` | str | — | Y | spec 2.7c: primary-ingot MCX vs scrap/alloy; LME official (London midday) vs MCX evening close; duty-parity assumption; FY22-23 MCX hedge efficiency 55.67% (exchange.yaml) | |
| `unhedged_reason` | str | — | if no MCX | | |

Fill prices are **never typed**: engine fill = MCX close of that contract on the date, ∓ `mcx_slippage_ticks × mcx_al_tick_inr_kg` against the desk.

**USD/INR forwards:**

| Field | Type | Unit | Req | Allowed / default | Validation / notes |
|---|---|---|---|---|---|
| `fx_forwards[].fwd_id` | str | — | Y | | |
| `booking_date` | date | — | Y | ≥ `trade_date` | contracted exposure exists (RBI regime) |
| `direction` | enum | — | Y | `BUY_USD` (importer) \| `SELL_USD` | |
| `notional_usd` | float | USD | Y | > 0 | Σ ≤ `fx_hedge_no_documentation_limit_usd` warning |
| `value_date` | date | — | Y | ≥ booking + 2 | should equal expected linked payment date at booking (warning otherwise) |
| `linked_flow` | str | — | Y | e.g. `"PURCHASE:L2 usance maturity"` | |
| `hedge_pct_target` | float | frac | Y | of linked USD at booking | actual written to trade_hedges.csv |
| `cancel_date` | date | — | N | booking < cancel < value_date | RBI free cancellation/rebooking |

Strike is never typed: `K = desk.units.fx_forward(usdinr, inr_rate_3m_pa, usd_rate_3m_pa, days)` on booking date (mid).

### 2.8 `ops` — SIM operational outcomes (every value is a simulated outcome, labelled SIM in outputs)

| Field | Type | Req | Default (planned rule, §3.1) | Notes |
|---|---|---|---|---|
| `lots.<id>.bl_date` | date | N | `bl_date_planned` | must stay inside laycan (late shipment not modelled) |
| `lots.<id>.arrival_date` | date | N | rule | |
| `lots.<id>.boe_date` | date | N | rule | |
| `lots.<id>.survey.date` | date | N | rule | outcome known on this date |
| `lots.<id>.survey.moisture_frac` | float | N | franchise-free expectation: `moisture_frac_<grade>` | |
| `lots.<id>.survey.contamination_frac` | float | N | `contamination_frac_<grade>` (= limit → no discount) | |
| `lots.<id>.survey.rejected_boxes` | int | N | 0 | |
| `lots.<id>.survey.rejection_reason` | enum | if rejected | `RADIOACTIVITY` \| `WRONG_GRADE` | |
| `lots.<id>.survey.rejectable_decision` | enum | if contamination excess > `spa_contamination_rejection_excess_frac` | `ACCEPT_RENEGOTIATED` + `renegotiated_discount_frac` \| `REJECT_LOT` | |
| `lots.<id>.survey.claim_recovery_frac` | float | N | 1.0 | supplier pays this share of claims |
| `lots.<id>.delivery_date` | date | N | rule | gate-out = end of port dwell |
| `lots.<id>.buyer_claim` | `{date, discount_frac}` | N | none | date ≥ delivery |
| `lots.<id>.receipt_date` | date | N | due date | ≤ `HORIZON_END` |
| `notices[]` | `{lot_id, field, known_date, eta \| null, tag, source_ref}` | N | — | `eta: null` = rolling; tag `VOID_CALLS_JUL2022` requires `known_date ≥ 2022-07-27` (freight_notes S4) |

### 2.9 `rationale` (spec 2.9)

| Field | Type | Req | Notes |
|---|---|---|---|
| `text` | str (one paragraph) | Y | trader voice; may cite only data dated ≤ `trade_date` |
| `parity_week_end` | date | Y | must equal `eligible_on(...)` week (latest `week_end ≤ trade_date`) |
| `cited_columns` | list | Y | parity_weekly columns cited (e.g. `net_arb_inr_t`, `net_arb_pit_mix_inr_t`, `net_arb_conv18k_inr_t`); **values are injected by `desk.book.run` into trade_book.csv, never typed** |

### 2.10 Annotated example — EX-B (US lane, FOB, LME M+1, usance, MCX-linked sale, roll, delays)

```yaml
# config/trades.yaml (excerpt) — ACADEMIC SIMULATION — not actual trades. Test fixture, not a Phase 2 trade.
schema_version: 1
trades:
  - trade_id: T90                      # fixtures use T9x
    status: EXECUTED
    trade_date: 2022-05-20             # USEC_MUN × tense eligible in parity week 2022-05-20
    lane: USEC_MUN
    grade: tense
    quantity_mt: 2520.0                # 120 × 40ft × 21 MT
    purchase:
      supplier_id: SUP-USEC-01
      spa_ref: "SPA/USEC/2205-90 (SIM)"
      incoterm: FOB
      named_place: "Savannah, GA, USA (FOB)"
      grade_spec: {isri_name: "Tense", spec_ref: "ISRI Scrap Specifications Circular 2022"}
      pricing:
        type: LME_AVG
        lme_reference: CASH
        qp_rule: M_PLUS_1_OF_BL        # June laycan -> July QP
        qp_start: 2022-07-01
        qp_end: 2022-07-31
        factor_frac: 0.695
        premium_usd_t: 0.0
        provisional_rule: LME_CASH_ON_BL
        provisional_payment_frac: 0.90
        terms_basis_note: "PIT mix 0.760 (grade_factor_mix_pit, 20-May) + Tense diff -0.07 = 0.690; +0.005 to win cargo; FOB/CFR gap absorbed by seller in a soft freight market"
      payment:
        instrument: LC_USANCE
        usance_days: 90
        lc_open_date: 2022-05-25
        lc_issuing_bank: "Western India Commercial Bank (SIM)"
        lc_confirmed: true
        confirmation_charges_for: APPLICANT
    shipment:
      laycan_start: 2022-06-01
      laycan_end: 2022-06-15
      load_port: "Savannah, USA"
      discharge_port: MUNDRA
      lots:
        - {lot_id: L1, boxes: 60, bl_date_planned: 2022-06-06, vessel: "MV Savannah Trader (SIM)", voyage: "022E (SIM)"}
        - {lot_id: L2, boxes: 60, bl_date_planned: 2022-06-14, vessel: "MV Coastal Meridian (SIM)", voyage: "114E (SIM)"}
    freight:
      booked_by: DESK_NVOCC
      forwarder: "Westline Cargo NVOCC (SIM)"
      payment_terms: COLLECT
      risk_layer: FIXED_AT_TRADE
      booking_date: 2022-05-20
      rate_usd_per_box: 1950.0         # index 89.95 USD/t x 21 = 1,888.95/FEU on 20-May (derived, not typed)
    sales:
      - sale_id: S1
        buyer_id: BUY-RJK-01
        booking_date: 2022-05-20       # back-to-back
        lot_ids: [L1, L2]
        delivery_basis: "FOR buyer's works, Rajkot (SIM)"
        pricing:
          type: MCX_AVG
          mcx_series: NEAR_MONTH_CLOSE
          qp_by_lot: {L1: [2022-07-11, 2022-07-22], L2: [2022-07-22, 2022-08-03]}
          mcx_factor_frac: 0.917        # recovery_frac_tense
          premium_inr_t: -22300         # (anchor premium - conversion) x recovery - buyer margin, frozen 20-May
          terms_basis_note: "helper §2.11 on 2022-05-20"
        payment: {terms: CREDIT, credit_days: 30}
    hedges:
      hedge_ratio_target: 1.0
      exposure_basis: NET_LME_EQ_DELTA   # ~750 MT-eq long at booking: 2,520 x (0.917 x 1.0825 - 0.695)
      basis_risk_note: "Primary-ingot MCX vs Tense scrap bought on LME cash and sold on MCX M1; LME official vs MCX evening close; duty parity may break (Mar-2022)."
      mcx:
        - {tranche_id: H1a, contract_month: 2022-06, direction: SELL, lots: 138, open_date: 2022-05-20, open_purpose: HEDGE, close_date: 2022-06-21, close_purpose: ROLL}
        - {tranche_id: H1b, contract_month: 2022-07, direction: SELL, lots: 70,  open_date: 2022-06-21, open_purpose: ROLL,  close_date: 2022-07-12, close_purpose: HEDGE}
        - {tranche_id: H1c, contract_month: 2022-07, direction: SELL, lots: 68,  open_date: 2022-06-21, open_purpose: ROLL,  close_date: 2022-07-20, close_purpose: HEDGE}
      fx_forwards:
        - {fwd_id: F1, booking_date: 2022-06-06, direction: BUY_USD, notional_usd: 2161000, value_date: 2022-09-05, linked_flow: "PURCHASE:L1 usance maturity", hedge_pct_target: 1.0}
        - {fwd_id: F2, booking_date: 2022-06-14, direction: BUY_USD, notional_usd: 2040000, value_date: 2022-09-12, linked_flow: "PURCHASE:L2 usance maturity", hedge_pct_target: 1.0}
    ops:                                # SIM outcomes
      lots:
        L1:
          survey: {moisture_frac: 0.012, contamination_frac: 0.02, rejected_boxes: 0}
        L2:
          arrival_date: 2022-08-02
          delivery_date: 2022-08-26
          survey: {moisture_frac: 0.005, contamination_frac: 0.035, rejected_boxes: 0}   # 1.5% excess -> 2.25% discount
          receipt_date: 2022-10-24
      notices:
        - {lot_id: L2, field: arrival_date, known_date: 2022-07-27, eta: 2022-08-02, tag: VOID_CALLS_JUL2022, source_ref: "docs/research/freight_notes.md S4"}
        - {lot_id: L2, field: delivery_date, known_date: 2022-08-12, eta: null, tag: CFS_CONGESTION_SIM, source_ref: "SIM"}
        - {lot_id: L2, field: receipt_date, known_date: 2022-09-26, eta: null, tag: BUYER_DELAY_SIM, source_ref: "SIM"}
    rationale:
      text: >-
        (one paragraph, trader voice, only data <= 2022-05-20)
      parity_week_end: 2022-05-20
      cited_columns: [net_arb_inr_t, net_arb_pit_mix_inr_t, net_arb_conv18k_inr_t, grade_factor, mcx_anchor_inr_kg]
```

### 2.11 Recommended sale-terms helper (P2) — keeps sale prices hindsight-free and tied to §5
On booking date `d` with data ≤ `d` (anchor contract per lane as §5):
`netback_inr_t(d) = anchor_inr_t(d) × recovery_frac_g + byproduct_inr_t(d) − conversion_cost_inr_t × recovery_frac_g`.
FIXED: `price_inr_t = round(netback − buyer_margin_inr_t, −2)`. MCX_AVG: `mcx_factor_frac = recovery_frac_g`,
`premium_inr_t = round((domestic_anchor_premium_inr_t − conversion_cost_inr_t) × recovery_frac_g + byproduct_inr_t(d) − buyer_margin_inr_t, −2)`
(byproduct frozen at `d`). `buyer_margin_inr_t` = the smelter's retained margin (proposed ASSUMPTION, §2.14).

### 2.12 `config/counterparties.yaml`

| Field | Type | Unit | Req | Allowed | Used by |
|---|---|---|---|---|---|
| `id` | str | — | Y | `SUP-<LANE>-nn` / `BUY-<LOC>-nn` | all |
| `name` | str | — | Y | ends `(SIM)` | reports |
| `role` | enum | — | Y | `SUPPLIER` \| `BUYER` | |
| `type` | enum | — | Y | `SCRAP_YARD` \| `PROCESSOR` \| `TRADER` (suppliers); `SECONDARY_SMELTER` \| `FOUNDRY` \| `TRADER` (buyers) | P5 feature (segment) |
| `country`, `location` | str | — | Y | ISO-2; `"Rajkot, Gujarat (SIM)"` | |
| `lanes`, `grades` | list | — | Y | | validation |
| `credit_limit_inr` | float | ₹ | BUYER | ≥ 0 (0 = advance only) | P5 tracker, event #3 |
| `claims_exposure_limit_usd` | float | USD | SUPPLIER | outstanding claims/refunds cap | supplier credit check |
| `payment_terms_default` | enum | — | BUYER | `CREDIT` \| `ADVANCE` | |
| `credit_days_default` | int | days | BUYER | ≤ `msme_max_payment_days` | |
| `lc_confirmation_required` | bool | — | SUPPLIER | | LC fees |
| `safe_origin_for_psic` | bool | — | SUPPLIER | | PSIC validation |
| `udyam_category` | enum | — | N | `MICRO` \| `SMALL` \| `MEDIUM` \| `NONE` | informational (MSMED note) |
| `profile.years_trading_with_desk` | float | years | Y | ≥ 0 | P5 "payment-history length" |
| `profile.years_in_business` | int | years | Y | | P5 |
| `profile.annual_turnover_inr` | float | ₹ | Y | | P5 (exposure scaling) |
| `profile.prior_invoices_count` | int | — | Y | | P5 synthetic history seed |
| `profile.prior_avg_dpd_days` | float | days | BUYER | ≥ 0 | P5 DPD prior |
| `profile.prior_max_dpd_days` | int | days | BUYER | | P5 |
| `profile.prior_disputed_claims_count` | int | — | Y | | P5 / supplier quality |
| `profile.gst_returns_regular` | bool | — | BUYER | | P5 |
| `profile.security` | enum | — | BUYER | `NONE` \| `PDC` \| `BANK_GUARANTEE` | P5 LGD note |
| `profile.security_amount_inr` | float | ₹ | N | | |
| `profile.external_rating_sim` | str | — | N | e.g. `"BB (SIM)"` | P5 band mapping |
| `flag` | const | — | Y | `SIM` | |

Computed (never typed; in P5 outputs): exposure vs limit, current DPD, order concentration (share of desk sales).

### 2.13 Validation rules (desk.book.validate — errors unless marked W)
V01 schema/enum/unit; unknown keys. V02 `(SIM)` names. V03 `trade_date` panel day in window and `eligible_on` True
(CONTRACTS §5a). V04 laycan in one month; planned and actual B/L inside laycan. V05 QP rule consistent; QP start >
trade_date. V06 Σ lot weights = quantity; 1,000–5,000 MT. V07 lane ↔ ports ↔ box type; PSIC flag. V08 every lot
sold exactly once; sale booking ≤ planned arrival; MCX_AVG QP end ≤ planned delivery; ADVANCE ⇒ FIXED. V09
credit_days ≤ `msme_max_payment_days`. V10 MCX close ≤ DIRECT expiry − roll days; ROLL pairs balanced; no open
lots after last close; W if open/close day has |Δ proxy M1| > `mcx_al_dpl_max_frac` (limit-locked in reality).
V11 freight FLOAT booking date equals the recomputed stop-loss rule; FIXED booking = trade_date; CFR has no freight
block. V12 forwards: booking ≥ trade_date, value_date ≤ HORIZON_END; W if value_date ≠ expected linked flow date at
booking. V13 notices/ops dates ordered (bl ≤ arrival ≤ boe ≤ delivery ≤ receipt); `known_date ≤` the date it
changes; VOID_CALLS_JUL2022 known ≥ 2022-07-27; mitigation date ≥ trigger `known_date`. V14 **every derived cashflow
≤ `HORIZON_END`** (CONTRACTS §7.1). V15 rationale week = `eligible_on` week. V16 counterparties: buyer limit present;
W if contracted sale value at booking > available limit. V17 no decision field references a value that the
validator cannot recompute from data ≤ its date (fills, strikes, index at booking are derived, never typed).

### 2.14 New parameter keys proposed (new file `config/params/book.yaml`, P2-owned; nothing in Phase 0 files changes)

| Key | Value | Unit | Flag | Source / justification | Verify |
|---|---|---|---|---|---|
| `lc_sight_payment_days_after_bl` | 7 | days | ASSUMPTION | `finance_days_*` construction notes ("sight LC paid on document presentation ~day 7") | N/A |
| `lc_presentation_period_days` | 21 | days | ASSUMPTION | UCP 600 Art. 14(c) 21-day presentation default (not re-read in this phase) | PENDING — read ICC UCP 600 Art. 14(c) |
| `lc_amount_tolerance_frac` | 0.10 | frac | ASSUMPTION | LC "about" tolerance (UCP 600 Art. 30) used to size LC value | PENDING — Art. 30 text |
| `boe_days_after_arrival` | 1 | days | ASSUMPTION | `finance_days_usec_mun` note ("arrival day 40, BoE ~day 41") | N/A |
| `discharge_survey_days_after_arrival` | 3 | days | ASSUMPTION | CFS de-stuffing + joint survey | N/A |
| `final_invoice_days_after_qp` | 5 | days | ASSUMPTION | seller computes QP average, issues final invoice | N/A |
| `claim_settlement_days_after_survey` | 30 | days | ASSUMPTION | survey report + seller acceptance + credit note | N/A |
| `provisional_payment_frac_default` | 0.90 | frac | ASSUMPTION | common 90–95% provisional under LME-linked scrap SPAs | N/A |
| `advance_days_before_delivery` | 2 | days | ASSUMPTION | advance before truck release | N/A |
| `freight_booking_days_before_bl` | 10 | days | ASSUMPTION | NVOCC space confirmation lead time | N/A |
| `freight_stop_loss_frac` | 0.15 | frac | ASSUMPTION | freight risk policy (P5 memo may override) | N/A |
| `mcx_slippage_ticks` | 2 | ticks | ASSUMPTION | execution vs close on a thin contract | N/A |
| `mcx_brokerage_exchange_frac` | 0.0002 | frac of value | ASSUMPTION | brokerage + exchange transaction charges | PENDING — MCX charge circular |
| `mcx_ctt_frac_sell` | 0.0001 | frac of sell value | ASSUMPTION | Commodity Transaction Tax on non-agricultural futures, sell side (Finance Act 2013) — stated from memory, hence not DIRECT | PENDING — Finance Act 2013 Ch. VII |
| `buyer_margin_inr_t` | 3000 | ₹/t scrap | ASSUMPTION | smelter's retained share of the netback (sale-terms helper only) | N/A |
| `overdue_interest_collected_frac` | 0.0 | frac | ASSUMPTION | penal interest on late foundry payments is rarely collected | N/A |

Existing keys reused (not duplicated): `spa_moisture_deduction_ratio`, `spa_contamination_discount_multiple`,
`spa_contamination_rejection_excess_frac`, `lme_cash_prompt_bdays` (parity.yaml); every §5 key; LC fee keys;
`fx_forward_bank_margin_inr` (applied also to spot TT conversion — see §12).

---

## 3. Lifecycle and cashflow schedule

### 3.1 Date chain per lot (planned rule → actual override → when revealed)

`R(x)` = roll following to a panel day. All offsets are calendar days.

| Date | Planned rule | Actual source | Revealed |
|---|---|---|---|
| `bl` | `bl_date_planned` | `ops.bl_date` | on the date |
| `docs` (sight payment / usance acceptance) | `R(bl + lc_sight_payment_days_after_bl)` | derived | with `bl` |
| `maturity` (usance) | `R(bl + usance_days)` | derived | with `bl` |
| `arrival` | `R(bl + transit_days_<lane>)` | `ops.arrival_date` | rule D7 |
| `boe` | `R(max(arrival + boe_days_after_arrival, docs + 1))` | `ops.boe_date` | rule D7 |
| `survey` | `R(arrival + discharge_survey_days_after_arrival)` | `ops.survey.date` | outcome known on survey date |
| `delivery` | `R(arrival + clearance_delivery_days)` | `ops.delivery_date` | rule D7 |
| `igst_credit` | `R(boe + igst_credit_lag_days)` | derived | with `boe` |
| `final_invoice` (LME-linked) | `R(max(qp_end + final_invoice_days_after_qp, survey + claim_settlement_days_after_survey))` | derived | |
| `claim_settle` (FIXED purchase) | `R(survey + claim_settlement_days_after_survey)` | derived | |
| `sale_due` | CREDIT: `R(delivery + credit_days)`; ADVANCE: `max(booking, R(delivery_planned − advance_days_before_delivery))` | `ops.receipt_date` | rule D7 |
| `freight_pay` (FOB) | PREPAID `bl`; COLLECT `arrival` | derived | |

**Revelation rule (D7).** For a milestone with planned date `p` (computed from *expected* upstream dates), actual
`a`, notices `N`, and information date `i`:
```
expected(p, a, N, i) =
    a                                  if a <= i                        # it has happened
    max(eta_n, next_panel_day(i))      if a > i and some notice n in N has known_date <= i and eta_n not null
                                       (latest such notice)
    next_panel_day(i)                  if a > i and p <= i              # overdue, not yet happened: rolling
    p                                  otherwise                        # nothing known yet
```
Survey outcomes, rejections and buyer claims default to "no claim" until their own date. Downstream dates are always
recomputed from expected upstream dates, so a delayed arrival shifts BoE, IGST credit, delivery and the sale receipt.

### 3.2 Quantities (P1 helper `settle_weight_and_penalty` supplies the SPA arithmetic)
```
n, n_rej, n_acc = boxes, rejected_boxes, boxes − rejected_boxes
Q_bl  = bl_weight_mt ;  Q_acc = Q_bl × n_acc / n
e_m   = max(0, moisture − franchise) ;  Q_fin = Q_acc × (1 − spa_moisture_deduction_ratio × e_m)   # purchase final weight = sale delivered weight
e_c   = max(0, contamination − limit) ; δ = spa_contamination_discount_multiple × e_c  (or renegotiated_discount_frac)
ρ     = claim_recovery_frac ; i_ins = insurance_rate × insured_value_uplift
b_box = container_payload_mt_<20ft|40ft>  (BASE payload: panel freight and port charges are per base box)
```

### 3.3 Prices
```
FIXED purchase:   P_fin = P_prov = price_usd_t
LME_AVG:          P_fin  = factor × mean_{d ∈ LME days in QP} REF(d) + premium          REF = official cash (or 3M)
                  P_prov = factor × cash(bl) + premium
LME_ON_DATE:      P_fin  = factor × REF(pricing_date) + premium ; P_prov = P_fin if pricing_date <= bl else as LME_AVG
CFR price basis per MT for customs/insurance:  c = P (CFR)   |  c = P + F_usd/Q_bl (FOB, F_usd = freight paid)
FIXED sale:       P_s = price_inr_t
MCX_AVG sale:     P_s = mcx_factor_frac × 1000 × mean_{d ∈ panel days in lot QP} MCX_M1(d) + premium_inr_t
```

### 3.4 Cashflow catalogue (sign: + = cash in to the desk; `X(d)` = panel `usdinr` mid; `m` = `fx_forward_bank_margin_inr`)

USD→INR rule: USD **paid** converts at `X(d) + m`, USD **received** at `X(d) − m`; USD-denominated *fees* at `X(d)`.
Projected (d > valuation date): replace `X(d)` by the CIP forward `F_X(S, cal, d)` (§4.4).

| CF | Leg (`leg_type`) | Date | Ccy | Amount (native) | Class | Fixes on |
|---|---|---|---|---|---|---|
| CF-01 | LC_FEES (LC opening) | `lc_open_date` | INR | `− lc_opening_fee_frac_per_month × ceil(v/30) × LCV × X`; `LCV = Σ Q_bl × P_lc × (1 + lc_amount_tolerance_frac)`, `P_lc` = fixed price or `factor × 3M(lc_open) + premium`; `v = laycan_end + lc_presentation_period_days − lc_open_date` | PNL | lc_open |
| CF-02 | LC_FEES (confirmation, if APPLICANT) | `lc_open_date` | INR | `− lc_confirmation_fee_pa × (v + usance_days) / 360 × LCV × X` (usance 0 for sight) | PNL | lc_open |
| CF-03 | INSURANCE | `bl` | INR | `− i_ins × Q_bl × c_prov × X(bl)` (c_prov uses P_prov) | PNL | bl |
| CF-04 | PSIC (JEA_NSA) | `bl` | INR | `− psic_cost_usd_per_box × n × X(bl)` | PNL | bl |
| CF-05 | FREIGHT (FOB) | `freight_pay` | USD | `− n × R_box`; `R_box` = fixture, or `S.freight_l × b_box` while unbooked | PNL | booking_date |
| CF-06 | PURCHASE (sight LC) | `docs` | USD | FIXED `− Q_bl × P`; LME `− φ × Q_bl × P_prov` | PNL | bl |
| CF-07 | PURCHASE (usance LC) | `maturity` | USD | same bill value `BV` as CF-06 | PNL | bl |
| CF-08 | LC_FEES (usance commission) | `docs` | INR | `− lc_usance_fee_frac_per_month × ceil(usance_days/30) × BV × X(docs)` | PNL | bl |
| CF-09 | USANCE_INTEREST | `maturity` | USD | `− BV × (usd_rate_3m_pa(docs) + usance_interest_spread_pa) × usance_days / 360` | PNL | docs |
| CF-10 | LC_FEES (bill commission) | `docs` (sight) / `maturity` (usance) | INR | `− import_bill_commission_frac × BV × X` | PNL | bl |
| CF-11 | PURCHASE (final balance, LME-linked, TT) | `final_invoice` | USD | `− (Q_bl × P_fin − adj − φ × Q_bl × P_prov)`; can be positive (refund) | PNL | final_invoice |
| CF-12 | SUPPLIER_CLAIM (FIXED purchase) | `claim_settle` | USD | `+ adj` | PNL | survey |
| — | where `adj` | | USD | `ρ × [ P_fin × ((Q_bl − Q_acc) + Q_acc × ratio × e_m + Q_fin × δ) + n_rej × R_box·[FOB] ]` (rejected tonnes + moisture weight + discount + freight on rejected boxes) | | survey |
| CF-13 | CUSTOMS_DUTY (BCD+SWS) | `boe` | INR | `− AV × bcd_scrap_hs7602 × (1 + sws_rate_on_bcd)`; `AV = Q_acc × c_prov × (1 + i_ins) × customs_usdinr_import(boe)` (`landing_charges_frac` = 0) | PNL | boe |
| CF-14 | IGST (paid) | `boe` | INR | `− (AV + CF13) × igst_rate_hs7602` | TAX | boe |
| CF-15 | IGST (credit) | `igst_credit` | INR | `+ CF-14 amount` if `igst_itc_available` else 0 | TAX | boe |
| CF-16 | CUSTOMS_DUTY / IGST differential (LME-linked) | `final_invoice` (credit at `+ igst_credit_lag_days`) | INR | `ΔAV = Q_acc × (P_fin − P_prov) × (1+i_ins) × customs_usdinr_import(boe)`; duty and IGST as CF-13/14 on ΔAV; mirror credit | PNL / TAX | final_invoice |
| CF-17 | PORT (THC, CFS, DO, CHA, examination, haulage) | `delivery` | INR | `− port_cf_charges_inr_t_<nsa\|mun> × b_box × n_acc` | PNL | delivery |
| CF-18 | DEMURRAGE (detention + ground rent) | `delivery` | INR | `− n_acc × max(0, (delivery − arrival) − detention_free_days) × demurrage_usd_per_box_day × X(delivery)` | PNL | delivery |
| CF-19 | SALE (CREDIT) | `sale_due` | INR | `+ Q_fin × P_s × (1 − δ_buyer)` | PNL | delivery (qty), QP end (price) |
| CF-20 | SALE (ADVANCE) | `sale_due`; true-up at `delivery`; buyer-claim refund at claim date | INR | `+ Q_bl × P_s`; `+ (Q_fin − Q_bl) × P_s`; `− Q_fin × P_s × δ_buyer` | PNL | booking / delivery / claim |
| CF-21 | MARK (unsold lot, §4.6) | `R(delivery + domestic_buyer_credit_days)` | INR | `+ MARK(S, cal)` — exists only while no sale covers the lot | PNL | never (removed at sale booking) |
| CF-22 | MCX (variation margin) | every panel day open ≤ d ≤ close | INR | open day `dir × L × 5000 × (M(d) − fill_o)`; middle `dir × L × 5000 × (M(d) − M(d−))`; close day `dir × L × 5000 × (fill_c − M(d−))`; `dir` = +1 BUY / −1 SELL; `fill_o = M(open) + dir × slip`, `fill_c = M(close) − dir × slip`, `slip = mcx_slippage_ticks × mcx_al_tick_inr_kg` | PNL | daily |
| CF-23 | MCX (transaction costs) | open, close | INR | `− L × 5000 × fill × (mcx_brokerage_exchange_frac + mcx_ctt_frac_sell·[sell side])` | PNL | fill date |
| CF-24 | MCX (initial margin) | daily | INR | `− Δ(IM)`, `IM(d) = L × 5000 × M(d) × mcx_al_margin_used_frac` for open ≤ d < close, else 0 | COLLATERAL | daily |
| CF-25 | FX_FORWARD | `value_date` (or `cancel_date`) | INR | `dir × N × (X(T) − K)`; cancel: `dir × N × (F_X(S(k), k, T) − K)` | PNL | value/cancel date |
| CF-26 | FUNDING | every panel day `d_k` in (first flow, last non-funding flow] | INR | `B(d_{k−1}) × wc_rate_inr_pa(d_{k−1}) × (d_k − d_{k−1}) / 365`, `B` = Σ all PNL+TAX+COLLATERAL flows dated ≤ `d_{k−1}` (simple interest, B<0 ⇒ cost) | FUNDING | daily |

Not modelled as flows (documented, §9): output GST on domestic sales (pass-through; its net timing effect is
covered by the IGST lag), TDS/TCS, bank charge minimums, customs bond for provisional assessment, re-export costs
(seller's account), storage (sale must be booked before arrival).

### 3.5 Funding model and the no-double-count argument
- **What is financed:** exactly the trade's signed cash balance `B(d)` — every PNL, TAX and COLLATERAL flow up to `d`.
  Buyer credit is financed because the receipt is dated `delivery + credit_days`; usance defers the goods outflow to
  maturity (and CF-09 charges the USD usance interest explicitly); IGST is financed from BoE to credit; MCX initial
  margin and variation-margin calls are financed while posted; demurrage delay is financed via the later receipt.
- **Rate:** `wc_rate_inr_pa` (ASSUMPTION path, step) in force on each accrual day. A positive balance earns the same
  rate (it reduces CC-line drawings); accrual stops after the trade's last non-funding flow.
- **In MTM:** realised interest to date is in R; the projected interest on the projected balance path (all projected
  flows, rate = value in force at the valuation date, flat) is a projected FUNDING flow in V. So `new_deal` at
  inception is a *deal-sheet margin net of expected carry*, and later days show only changes in expected carry.
- **No double count with Phase 1.** P1's `finance_inr_t = (goods + duty) × finance_days_l/365 × wc_rate` is a
  *per-tonne parity approximation* whose `finance_days_*` already include buyer credit (P1 uses a 1M forward for goods,
  so its finance covers payment → receipt). The engine reads **none** of `finance_days_*`, `finance_inr_t`,
  `igst_finance_inr_t`, `lc_opening_fee_frac`; it replaces them with dated flows. The only shared inputs are
  `wc_rate_inr_pa`, `igst_credit_lag_days`, transit and clearance days — used as *date rules*, never as day-count
  multipliers. Because simple interest is linear in balances, trade-level funding sums exactly to desk-level funding.
- **Reconciliation (P2 output, informative):** at `trade_date`, `trade_book.csv` shows parity line items (§5, per MT)
  beside the planned-schedule equivalents (goods, duty, port+PSIC, funding, plus items §5 does not carry: LC fees,
  usance interest, bill commission, confirmation, MCX costs, buyer margin). Differences are explained, not forced.

### 3.6 Example planned timelines (from the rules above; rolled to panel days)
- **EX-A (JEA_NSA Zorba, CFR fixed, sight):** trade 18-Mar → LC open 23-Mar → B/L 08-Apr (PSIC, insurance) → arrival
  13-Apr → LC payment 15-Apr→**19-Apr** (Good Friday/Easter Monday not LME days) → BoE 16-Apr→19-Apr → survey 19-Apr →
  delivery 23-Apr→25-Apr → supplier claim 19-May → receipt 25-May → IGST credit 03-Jun→06-Jun.
- **EX-B (USEC_MUN Tense, FOB, usance 90d), lot L2:** B/L 14-Jun → acceptance 21-Jun → planned arrival 25-Jul
  (void-call notice 27-Jul, actual 02-Aug) → BoE 03-Aug → survey 05-Aug → planned delivery 12-Aug (rolling until actual
  26-Aug: 10 chargeable days × 60 FEU × USD 35 = USD 21,000) → final invoice 05-Sep → usance maturity 12-Sep → IGST
  credit 19-Sep → due 26-Sep → actual receipt 24-Oct (SIM delay) — all ≤ `HORIZON_END`.

---

## 4. Valuation at date t from market state

### 4.1 `MarketState` — the only door for dated inputs

| Field | Source (panel column / register key) | Flag | Block (factor) |
|---|---|---|---|
| `lme_3m` | `lme_3m_usd_t` | DIRECT | A `lme_flat` |
| `beta[c]` (₹/kg, per MCX contract month) | `mcx_al_m1/m2_inr_kg` − parity (§4.3) | PROXY (panel) / PROXY (mirror) / DIRECT (bhavcopy) | B `cross_exchange_basis` |
| `mcx_prem` | `mcx_domestic_premium_inr_kg` | PROXY | B |
| `grade[g]` | `grade_factor_<g>` (BASE) or `grade_factor_mix_pit + grade_factor_diff_<g>` (PIT variant) | ASSUMPTION (lag-2 mix = hindsight) | C `grade_spread` |
| `freight[l]` | `freight_jea_nsa_usd_t`, `freight_usec_mun_usd_t` | ASSUMPTION (level) / PROXY (shape) | D `freight` |
| `usdinr` | `usdinr` | PROXY (ECB cross) | E `fx` |
| `customs_fx` | `customs_usdinr_import` in force on the state date (P1 fallback rule outside coverage) | DIRECT | E |
| `info_date` | operational information set I(date) | SIM | F `demurrage_penalty` |
| `lme_spread` | `lme_cash_usd_t − lme_3m_usd_t` | DIRECT | G `roll_term_structure` |
| `r_inr`, `r_usd` | `inr_rate_3m_pa`, `usd_rate_3m_pa` | PROXY | G |
| `wc` | `wc_rate_inr_pa` | ASSUMPTION | G |
| `cal` | valuation calendar date | — | G |

`lme_cash(S) = S.lme_3m + S.lme_spread`. `History` = the panel (and register paths) for dates ≤ `cal`: official
fixings, realised FX, MCX settlements, customs rates, rates at acceptance, WC path. **Purity rule:** valuation code may
call `desk.config.value(key)` only for undated scalars; every dated number comes from `MarketState` or `History(≤ cal)`.
(Any register path added later that valuation needs must be placed in a block; unassigned dated inputs default to G.)

**Fix rule.** A component with fix date `f` uses History if `f ≤ cal`, else the state `S`. Cashflows dated `≤ cal`
are realised (R); later ones are projected (V).

### 4.2 LME curve and partially fixed averages (reuses P1 `desk.parity.term_structure`)
```
p_cash(cal) = cal + lme_cash_prompt_bdays business days ;  p_3m(cal) = next weekday(cal + 3 calendar months)
F_L(S, cal, p) = cash + (3M − cash) × (p − p_cash) / (p_3m − p_cash)        # P1 forward_price, linear, extrapolates
E_cal[official cash on day d] = F_L(S, cal, d + lme_cash_prompt_bdays bdays)
E_cal[official 3M on day d]   = F_L(S, cal, p_3m(d))
QP average at cal:  Ā = ( Σ_{d ∈ QP, d <= cal} cash_hist(d) + Σ_{d ∈ QP, d > cal} E_cal[cash(d)] ) / N_QP
```
`N_QP` and the day set = panel LME trading days in the QP (the future LME calendar is public in advance, so this is
not hindsight; P1's weekday approximation differs by holidays only). Extrapolation is allowed to `p − p_cash ≤ 200`
days (named constant `LME_MAX_EXTRAP_DAYS`), else raise. Provisional price before B/L uses `E_cal[cash(bl)]`.

### 4.3 MCX curve — parity + basis
```
D        = 1 + bcd_primary_al_hs7601 × (1 + sws_rate_on_bcd)                          # 1.0825
E_c      = pricing expiry of contract month c = desk.data.mcx.month_expiry rule (the rule that generated the panel)
Par_c(S, cal) = (lme_cash(S) × S.usdinr / 1000 × D + S.mcx_prem) × (1 + S.r_inr × (E_c − cal)/365)
M_c(S, cal)   = Par_c(S, cal) + S.beta[c]
beta_c(t) (history) = panel price of c on t − Par_c(S(t), t)    for c ∈ {M1(t), M2(t)};  beta_c(t) = beta_M2(t)(t) for later months
E_cal[M1 close on day d] = M_{c(d)}(S, cal),   c(d) = contract that is M1 on d
```
Under `mcx_src = PROXY_IMPORT_PARITY`, β is only the panel's 4-dp rounding (|β| ≤ 0.00005 ₹/kg, so |Δβ| moves a lot by
≤ ₹0.5 a day).
With the mirror (`data/interim/mcx_thirdparty_…csv`, CONTRACTS §7.5) or bhavcopy, β is the observed basis
(window std ≈ ₹6.3/kg). Roll deadlines use DIRECT `mcx_al_expiry_dates_2022`; pricing uses `E_c` so β stays ≈ 0 in
base (see §12 on the 30/31-Aug-2022 mismatch).

### 4.4 FX forwards, payables and receivables
```
F_X(S, cal, d) = desk.units.fx_forward(S.usdinr, S.r_inr, S.r_usd, max(0, d − cal))    # INR ACT/365, USD ACT/360, flat 3M curve
USD flow projected INR  = usd × (F_X ± m)       realised: usd × (X(d) ± m)
Forward leg projected V = dir × N × (F_X(S, cal, T) − K)        realised at T: dir × N × (X(T) − K)
Customs AV projected    = USD basis × S.customs_fx               realised: × customs_usdinr_import(boe)
```

### 4.5 Freight
Unbooked FOB freight: `− n × S.freight_l × b_box` converted with `F_X`. Booked: fixed `rate_usd_per_box`. Memo column
every day: `freight_fixture_vs_market_inr = − n × (rate_usd_per_box − S.freight_l × b_box) × X` (negative = fixture above
index). CFR lots have no freight leg.

### 4.6 Unsold-inventory mark (landed replacement value) — CF-21
For each lot not covered by a booked sale:
```
cfr_mkt  = S.lme_3m × S.grade[g]                                   # CONTRACTS §5 CFR parity, same for both lanes
MARK     = Q_exp × cfr_mkt × (1 + i_ins) × [ (F_X(S, cal, T_goods) + m) + S.customs_fx × bcd_scrap_hs7602 × (1 + sws_rate_on_bcd) ]
         + port_cf_charges_inr_t_<port> × b_box × n_acc_exp + [JEA_NSA] psic_cost_usd_per_box × n × S.usdinr
Q_exp    = expected Q_fin (Q_bl before survey) ;  T_goods = expected goods payment date (docs or maturity)
dated    = R(expected delivery + domestic_buyer_credit_days)
```
A purchase at market terms therefore shows `new_deal ≈ −(LC fees + usance interest + expected funding)`; the margin
appears as `new_deal` on the sale booking day (= sale receipts − MARK at that day's market).

### 4.7 Leg valuation summary

| Leg | Realised part (history, dates ≤ cal) | Projected part (S, dates > cal) | Blocks it responds to |
|---|---|---|---|
| PURCHASE | CF-06/07/11 at actual prices & FX | LME forward averages, F_X | A, E, G (+F via claims in adj) |
| SUPPLIER_CLAIM | CF-12 | adj × F_X | F, E (and A for LME-linked) |
| FREIGHT | CF-05 | unbooked: S.freight; F_X | D, E, G |
| INSURANCE, PSIC | CF-03/04 | price estimate × F_X | A, E, G |
| LC_FEES, USANCE_INTEREST | CF-01/02/08/09/10 | estimates | A, E, G |
| CUSTOMS_DUTY, IGST | CF-13..16 | S.customs_fx, estimates | A, E, F, G |
| PORT, DEMURRAGE | CF-17/18 | expected dwell (info set) | F, E |
| SALE | CF-19/20 | MCX parity averages or fixed; expected qty/dates | A, B, E, F, G |
| BUYER_CLAIM | inside CF-19/20 | — | F |
| MARK | never realised | §4.6 | A, C, E, F, G |
| MCX | CF-22/23 | unsettled `dir × L × 5000 × (M_c(S,cal) − M_c_hist(cal))` (0 when S = S(cal)) | A, B, E, G |
| FX_FORWARD | CF-25 | `dir × N × (F_X − K)` | E, G |
| FUNDING | CF-26 | projected balance × S.wc | all (via balances), G (rate, time) |
| MCX initial margin | CF-24 → funding only | IM(S) → funding only | (through FUNDING) |

---

## 5. P&L attribution (CONTRACTS §7.2–7.4)

### 5.1 Identity
For trade k and panel day t, with `legs(t)` = legs whose bookings are dated ≤ t:
```
Π(L, S, cal, info) = R(L, cal) + V(L, S, cal, info)        # R: PNL+TAX+FUNDING flows dated <= cal ; V: projected, undiscounted
CumPnL(t) = Π(legs(t), S(t), t, t) ;   DailyPnL(t) = CumPnL(t) − CumPnL(t−1) ;   CumPnL(before trade_date) = 0
```
COLLATERAL (MCX initial margin) is excluded from R and V (P&L-neutral) and enters only the funding balance.

### 5.2 Blocks swapped, in `FACTOR_ORDER`

| Step | Bucket | Swapped from t−1 to t | Note |
|---|---|---|---|
| a | `lme_flat` | `lme_3m` (spread held ⇒ parallel shift of cash and 3M) | MCX parity moves with it |
| b | `cross_exchange_basis` | `beta[c]` for all contracts, `mcx_prem` | ≈ 0 in base |
| c | `grade_spread` | `grade[g]` | only unsold lots (MARK) respond |
| d | `freight` | `freight[l]` | only unbooked FOB freight |
| e | `fx` | `usdinr`, `customs_fx` | physical, MCX parity, forwards, duty base |
| f | `demurrage_penalty` | information date `I(t−1) → I(t)` | surveys, rejections, claims, delays, notices, demurrage accrual, buyer delays (and their funding) |
| g | `roll_term_structure` | `lme_spread`, `r_inr`, `r_usd`, `wc`, **and `cal: t−1 → t`** | fixings, settlements, forward-point and MCX-carry decay, contango/backwardation roll-down, funding accrual, realisation of day-t flows |
| — | `new_deal` | bookings dated t (trade, sale, hedge open/close, forward booking/cancel, freight booking) valued at S(t), cal t, info t | ROLL-purpose bookings are added to `roll_term_structure` instead |

### 5.3 Algorithm (per trade; legs aggregated after)
```python
X_prev = 0.0                                                    # CumPnL(t−1); 0 before trade_date
for t in panel_days[trade_date : HORIZON_END]:
    tm1 = prev_panel_day(t); S0, St = state(tm1), state(t)
    L_old, L_all = legs(tm1), legs(t)                           # legs(d) = legs built from all bookings dated <= d
    L_noroll = legs(bookings dated <= tm1  +  bookings dated t with purpose != ROLL)   # a ROLL close+open pair is left out together
    X = Π(L_old, S0, tm1, tm1)                                  # assert |X − X_prev| < 1e-6 (purity check)
    S, info, cal = S0, tm1, tm1
    for f in FACTOR_ORDER:
        if f == "demurrage_penalty": info = t
        else:                        S = S.swap(block(f), St)
        if f == "roll_term_structure": cal = t
        Xf = Π(L_old, S, cal, info); bucket[f] = Xf − X; X = Xf
    X_nr  = Π(L_noroll, St, t, t)
    X_new = Π(L_all,    St, t, t)
    bucket["new_deal"] = X_nr − X
    bucket["roll_term_structure"] += X_new − X_nr
    total = X_new − X_prev ; residual = total − sum(bucket.values()) ; X_prev = X_new
```
`Π` returns per-leg values, so the same loop yields leg-level buckets (a leg absent from a set has value 0).
Booking semantics inside `legs(d)`: a tranche whose close is dated after d is open; a sale dated after d does not
exist (its lots carry MARK); a forward cancelled after d is live. On `trade_date` `L_old` is empty, so every bucket
except `new_deal` is 0 and `new_deal = CumPnL(trade_date)`.

### 5.4 Where things land

| Item | Bucket | Mechanism |
|---|---|---|
| LME level move on unpriced purchase days, MCX hedge, MCX-linked sale, MARK | a | step a |
| Day-t official cash fixing | g (≈0) | at cal t−1 it was valued at the 1-day forward under S(t); step g fixes it at `cash(t)` = `3M(t)+spread(t)` exactly |
| Cash–3M spread change | g | step g |
| MCX move explained by LME | a | parity with new `lme_3m` |
| MCX move explained by USD/INR | e | parity with new `usdinr` |
| MCX carry decay (days to expiry), INR rate change | g | calendar, `r_inr` |
| MCX residual (observed − parity) | b | β |
| MCX roll (spread crossing, slippage, costs) | g | ROLL bookings |
| MCX hedge open/close slippage and costs | new_deal | booking |
| Grade factor drift on unsold scrap | c | step c |
| Unbooked freight vs index | d | step d |
| USD payables/receivables, forwards (spot part), customs FX | e | step e |
| Forward points roll-down, rate changes | g | calendar, rates |
| Survey claims, rejection, buyer claim, demurrage accrual, arrival/delivery/receipt delays and their funding | f | information set |
| Funding accrual (realised vs projected) and WC rate path | g | calendar, `wc` |
| Changes in projected funding caused by a price move | the moving factor | cross-term lands in the step that moves |
| Deal margin at inception; sale booked against MARK; forward booked at mid (0) | new_deal | booking |

### 5.5 LME → MCX consistency (why hedges show no fake basis) — real panel illustration
Short 100 lots MCX Apr-2022 on 8-Mar-2022 (panel PROXY): LME cash 3,984.5 → 3,500.5, 3M 3,968 → 3,516, USD/INR
76.9275 → 77.0510. Sequential parity decomposition of the VM: (a) **+₹189.23 lakh** (3M −452 at old spread, old FX),
(b) **≈ ₹0** (β rounding only), (e) **−₹2.37 lakh** (INR weakened: short MCX is short USD), (g) **+₹13.57 lakh**
(spread flipped +16.5 → −15.5, cash fell 32 more than 3M, plus one day of carry), total **+₹200.43 lakh** = actual
VM. The long physical position it hedges sees the same (a) through its LME/MCX references, so a well-sized hedge nets
(a) instead of parking offsetting amounts in (a) and (b).

### 5.6 Zero-residual proof sketch
1. `Π` is a pure function of `(legs, S, cal, info)` (purity rule §4.1); hence `Π(L_old, S0, tm1, tm1) = CumPnL(t−1)`.
2. The seven steps telescope: `Σ_f bucket_f(pre-booking) = Π(L_old, St, t, t) − CumPnL(t−1)` because after step g every
   block, the info date and the calendar equal day t's.
3. `new_deal + roll addition = Π(L_all, St, t, t) − Π(L_old, St, t, t)`.
4. Sum: `Σ buckets = Π(L_all, St, t, t) − CumPnL(t−1) = DailyPnL(t)` ⇒ residual = 0 up to floating point
   (expected < 1e-6 ₹; contract bound ₹1). Cross-terms cannot reach `residual` because no step is skipped and nothing is
   evaluated outside `Π`. Requirements: `S0 == state(tm1)` exactly (swap copies fields), and `lme_cash = lme_3m +
   lme_spread` is recomputed, never stored.

### 5.7 Realised cash
- A flow's amount is frozen from History on its fix date; its INR is frozen on its pay date. On the pay date the
  flow moves from V to R at step g; the only difference is calendar-driven (e.g. 1-day forward vs spot), so it lands
  in g. Nothing is ever "re-realised".
- `mtm_daily.csv` reports per leg `realised_cum_inr` (R) and `mtm_inr` (V); at `HORIZON_END` V = 0 for every leg and
  `CumPnL = Σ trade_cashflows(REALISED, classes PNL+TAX+FUNDING)` (test T06). `WINDOW_END` reporting shows the same split
  (realised vs unrealised) without any special logic.

---

## 6. Exposures for Phase 4 (VaR / Monte Carlo)

### 6.1 `book_exposures_daily.csv` — central bump-and-revalue of `Π(legs(t), S(t), t, t)` (rows per trade and `BOOK`)

| Column | Definition (h = bump) | Unit | Sign |
|---|---|---|---|
| `phys_purchased_mt`, `phys_sold_mt`, `unsold_mt` | Σ lot Q (booked purchases / lots under a booked sale / MARK lots) | MT | + |
| `purchase_priced_mt`, `sale_priced_mt`, `net_priced_mt` | Σ Q × fixed share of QP (FIXED = 1); net = purchase − sale | MT | + = long priced metal |
| `lme_delta_mt_eq` (+ `_physical`, `_mcx`) | `[Π(3M+h) − Π(3M−h)]/(2h) / usdinr`, h = 1 USD/t, spread held | MT LME-eq | + = gains if LME rises |
| `lme_delta_usd` | `lme_delta_mt_eq × lme_3m` | USD | |
| `lme_spread_delta_inr_per_usd_t` | ∂Π/∂spread, h = 1 USD/t | ₹ per USD/t | + = gains in backwardation |
| `mcx_open_lots`, `mcx_open_mt` | signed open lots | lots / MT | − = short |
| `mcx_basis_delta_inr_per_inr_kg` | ∂Π/∂β (all contracts), h = 1 ₹/kg | ₹ per ₹/kg | |
| `usdinr_delta_usd` (+ `_physical`, `_fx_forwards`, `_mcx`) | `[Π(X+h) − Π(X−h)]/(2h)`, h = 0.10 ₹ | USD | + = long USD (gains if INR weakens) |
| `freight_open_mt_<lane>`, `freight_open_boxes_<lane>` | unbooked FOB freight | MT / boxes | − = short freight |
| `freight_delta_inr_per_usd_t_<lane>` | ∂Π/∂freight, h = 1 USD/t | ₹ per USD/t | |
| `grade_delta_inr_per_pt_<grade>` | `Π(grade+0.005) − Π(grade−0.005)` (per 0.01) | ₹ per 0.01 factor | |
| `inr_rate_dv01_inr`, `usd_rate_dv01_inr`, `wc_rate_dv01_inr` | +1 bp minus −1 bp, /2 | ₹ per bp | |
| `mcx_im_inr` | Σ IM(t) | ₹ | |
| `cash_balance_inr` | B(t) incl. collateral | ₹ | − = drawn |
| `buyer_receivable_inr`, `buyer_contracted_undelivered_inr` | delivered-unpaid; booked-undelivered at projected receipt | ₹ | P5 credit tracker |
| `supplier_claims_receivable_usd` | agreed, unsettled `adj` | USD | |
| `usd_payable_usd`, `fx_forward_notional_usd` | memo | USD | |

Hedge sizing helper (P2, using exposures computed with data ≤ booking date): MCX lots for a physical LME-eq delta Δ:
`lots = round(Δ / (5 × D × carry_c))`, `carry_c = 1 + r_inr × (E_c − d)/365`. FX forward notional =
`− usdinr_delta_usd` measured *after* the MCX tranches are booked — each short lot is itself short
`≈ 5 × D × lme_cash × carry_c` USD (≈ USD 13k per lot at USD 2,400/t), which is why MCX-hedged inventory needs a
USD-buying forward on its payable and an unpriced MCX-linked sale needs less.

### 6.2 Monte Carlo full revaluation API (P4 calls; never re-implements pricing)
```python
from desk.mtm.market import MarketState, History
from desk.mtm.valuation import load_book, value_book     # value_book(book, state, cal, info, legs_asof, overrides=None)
book  = load_book()                                        # tickets + static schedules (cached)
base  = MarketState.from_panel(t)                          # scalars
paths = base.shock(lme_log_ret=r_l, fx_log_ret=r_x,        # numpy arrays (n_paths,)
                   freight_log_ret={"JEA_NSA": r_f, "USEC_MUN": r_f},
                   grade_abs=None, beta_abs=None)          # LME shock multiplies cash and 3M (spread scales); MCX via parity, beta held
pnl = value_book(book, paths, cal=t, info=t, legs_asof=t) - value_book(book, base, cal=t, info=t, legs_asof=t)   # (n_paths,) per trade + BOOK
```
All valuation arithmetic broadcasts over arrays (funding projection is `(n_paths, n_days)`); the calendar and info
set are held (instantaneous shock — VaR must not mix in carry). Stress overlays via `overrides`: `{"buyer_default":
{"buyer_id", "recovery_frac"}}`, `{"port_delay_days": qco_stress_delay_days, "rejection_frac": qco_stress_rejection_frac,
"rejected_loss_frac": qco_stress_rejected_loss_frac}`, `{"freight_shock_frac": freight_stress_shock_frac}` — injected
as synthetic info-set events dated t. Performance target: 10,000 paths × book in < 30 s (vectorised, no pandas inside).

---

## 7. Adverse events (Table 5 rows 3.4–3.6)

### 7.1 Windows (computed by rule in `desk.mtm.events`, written to `adverse_event_windows.csv`)

| Event | Rule (named constants in code) | 2022 result from panel |
|---|---|---|
| E1 LME crash — full | argmax of `lme_cash_usd_t` in window → argmin after it | 07-Mar ($3,984.5) → 15-Jul ($2,320.5), −41.8% |
| E1 crash fortnight | 10-LME-day window with the most negative cash return in window (`EVENT_FORTNIGHT_DAYS = 10`) | 22-Apr ($3,244.0) → 09-May ($2,708.0), −16.5% |
| E2 INR depreciation | argmin `usdinr` in window → argmax after it (also reported: window start → end) | 05-Apr (75.3350) → 14-Jul (80.0352), +6.24% (start→end +5.07%) |
| E3 logistics + credit | start = first real-evidence date for the disruption, `2022-07-27` (Container News void calls, freight_notes S4); end = last cashflow of any lot/sale carrying an E3-tagged notice | per book |

### 7.2 Method (all trades × window; trade live-days only)
- **Isolated impact** = Σ over window of the relevant bucket(s), by leg group: E1 → (a) split physical / MCX /
  funding, with (b) and (g) alongside; E2 → (e) split physical USD flows / forwards / MCX / customs duty.
- **Counterfactual books** (same trades and decisions, only the named component removed, full engine re-run):
  `NO_MCX` (all MCX tranches removed), `NO_FX_FWD`, `NO_E3_EVENTS` (E3-tagged ops/notices reset to planned),
  `FLOAT_FREIGHT` (FIXED_AT_TRADE fixtures replaced by floating to the latest booking date), `NO_MITIGATION`.
  Hedge benefit = total window P&L(book) − total window P&L(counterfactual).
- **Hedge effectiveness** (E1) = −Σ(a)_MCX / Σ(a)_physical over the window; **forward-book offset** (E2) =
  −Σ(e)_forwards / Σ(e)_physical_USD.
- **MCX variation-margin schedule** (E1): daily book VM, cumulative VM, IM required at `mcx_al_margin_used_frac` and at
  a stress 0.15 (note in exchange.yaml: 0.12–0.15 in the crash fortnight), net margin cash, cumulative, funding cost of
  margin, peak outflow date. Reality check shown in the table header: on 8-Mar-2022 a 100-lot position moved ±₹2.0 cr in
  one day on the proxy (real MCX would have hit the 4→6→9% limit slabs, `mcx_al_dpl_*`).
- **Event #3 honest framing (CONTRACTS §7.6):** (i) buyer payment delay (SIM) → Σ(f) funding of the overdue receivable,
  DPD, exposure vs `credit_limit_inr`, breach days, and the mitigation effect (`NO_MITIGATION` counterfactual: peak
  exposure and P&L difference); (ii) July-2022 void calls (real evidence, SIM magnitudes) → Σ(f) demurrage + delay
  funding; (iii) real freight effect of fixtures above a falling market = `FLOAT_FREIGHT` counterfactual difference and
  the change in `freight_fixture_vs_market_inr` memo (e.g. USEC_MUN index 106.4 → 70.0 USD/t from 3-Mar to 26-Aug);
  (iv) a **hypothetical** freight spike = `freight_stress_shock_frac` (+40%) applied instantaneously to unbooked freight on
  the E3 start date via the MC API, in a separate file labelled HYPOTHETICAL STRESS — never as a 2022 event.

---

## 8. Outputs, module layout, tests

### 8.1 Output tables (all deterministic; sort keys given; INR 2 dp, prices 4–6 dp; every file header row carries a
`sim_label`-bearing companion in docs, and every row a `provenance` string where noted)

**`trade_cashflows.csv`** (P2) — sort `scenario, trade_id, flow_date, cf_id, leg_id`:
`scenario` (PLANNED_AT_TRADE_DATE | REALISED), `trade_id, lot_id, leg_id, leg_type, cf_id, flow_type, counterparty_id,
flow_date, fix_date, ccy, amount_ccy, fx_rate, fx_rule` (SPOT_MID | SPOT_PLUS_MARGIN | CIP_FORWARD | CUSTOMS | FIXED_STRIKE | NA),
`amount_inr, cash_class` (PNL | TAX | COLLATERAL | FUNDING), `qty_basis_mt, price_basis, price_basis_unit, formula, provenance`.

**`trade_book.csv`** (P2): `trade_id, trade_date, parity_week_end, lane, grade, supplier_id, buyer_ids, quantity_mt, boxes,
incoterm, purchase_pricing, factor_frac, qp_start, qp_end, lc_instrument, usance_days, sale_pricing, sale_payment_terms,
trade_eligible, net_arb_inr_t, net_arb_pit_mix_inr_t, net_arb_conv18k_inr_t, deal_sheet_margin_inr, deal_sheet_margin_inr_t,
recon_goods_inr_t, recon_duty_inr_t, recon_port_inr_t, recon_funding_vs_finance_inr_t, recon_not_in_parity_inr_t, rationale`.

**`trade_hedges.csv`** (P2): `hedge_id, trade_id, instrument` (MCX_AL_FUT | USDINR_FWD | FREIGHT_FIXTURE), `booking_date,
purpose, contract_month, pricing_expiry, direct_expiry, roll_deadline, direction, lots, qty_mt, notional_usd, value_date,
fill_price_inr_kg, close_inr_kg, slippage_inr, txn_cost_inr, strike_usdinr, index_usd_per_box, fixture_usd_per_box,
hedge_ratio_target, hedge_ratio_actual, exposure_at_booking_mt_eq, basis_risk_note`.

**`mtm_daily.csv`** (P3; date × trade × leg) — sort `date, trade_id, leg_id`:
`date, trade_id, leg_id, leg_type, lot_id, counterparty_id, status` (LIVE | SETTLED), `qty_mt, priced_frac, price_native,
price_unit, market_ref, market_ref_unit, realised_cum_inr, mtm_inr, cum_pnl_inr, daily_pnl_inr, collateral_inr,
freight_fixture_vs_market_inr, mcx_series` (PANEL_PROXY | MIRROR | BHAVCOPY), `grade_variant` (BASE | PIT), `in_window, provenance`.

**`attribution_daily.csv`** (P3; date × trade incl. `BOOK`) — sort `date, trade_id`:
`date, trade_id, new_deal, lme_flat, cross_exchange_basis, grade_spread, freight, fx, demurrage_penalty,
roll_term_structure, residual, total_pnl_inr, cum_pnl_inr, cum_pnl_usd_memo, in_window` (bucket columns exactly
`PNL_BUCKETS`; `BOOK` = Σ trades). **`attribution_leg_daily.csv`**: same plus `leg_id, leg_type` (needed for hedge
effectiveness and forward-book offset).

**`book_exposures_daily.csv`**: §6.1 columns, plus `date, trade_id`.

**`mcx_variation_margin.csv`** — sort `date, trade_id, tranche_id` (+ BOOK rows):
`date, trade_id, tranche_id, contract_month, pricing_expiry, direction, lots, event` (OPEN | HOLD | CLOSE | ROLL_OPEN |
ROLL_CLOSE), `fill_price_inr_kg, settle_inr_kg, prev_settle_inr_kg, vm_inr, cum_vm_inr, txn_cost_inr,
contract_value_inr, im_required_inr, im_stress_inr, im_change_inr, net_margin_cash_inr, cum_net_margin_cash_inr, mcx_series`.

**Adverse events:** `adverse_event_windows.csv` (`event_id, name, start_date, end_date, rule, driver, driver_start,
driver_end, driver_change_frac, flag, note`); `adverse_event_1_lme_crash.csv` (`window, trade_id, live_days,
lme_flat_physical_inr, lme_flat_mcx_inr, lme_flat_funding_inr, basis_inr, roll_term_inr, total_window_pnl_inr,
nomcx_total_window_pnl_inr, hedge_benefit_inr, hedge_effectiveness_frac, cum_vm_inr, peak_vm_outflow_inr,
peak_im_required_inr, margin_funding_cost_inr`); `adverse_event_1_mcx_vm_schedule.csv` (daily BOOK VM/IM over both
E1 windows); `adverse_event_2_inr_depreciation.csv` (`trade_id, live_days, usd_payable_at_start_usd,
fx_physical_inr, fx_forwards_inr, fx_mcx_inr, fx_customs_inr, fx_total_inr, nofwd_fx_total_inr,
forward_offset_frac, total_window_pnl_inr`); `adverse_event_3_logistics_credit.csv` (`trade_id, lot_id, buyer_id,
component` (BUYER_DELAY | VOID_CALL_DEMURRAGE | VOID_CALL_DELAY_FUNDING | FREIGHT_FIXTURE_VS_FLOAT), `impact_inr,
counterfactual, peak_exposure_inr, credit_limit_inr, peak_utilisation_frac, breach_days, max_dpd_days,
mitigation_action, exposure_avoided_inr, evidence_ref, flag`); `adverse_event_3_freight_stress_hypothetical.csv`
(`scenario_label` = "HYPOTHETICAL STRESS — not a 2022 event", `shock_date, shock_frac, trade_id, lane,
freight_open_boxes, pnl_inr`). Sensitivity runs write the same files with suffix `_mcx_mirror` and `_grade_pit`.

### 8.2 Module / API layout
```
desk/book/                           (P2)
  schema.py      dataclasses Counterparty, TradeTicket, Lot, Purchase, Pricing, LcTerms, Freight, Sale, McxTranche,
                 FxForward, OpsLot, Notice; load_counterparties(path), load_trades(path)
  calendar.py    PanelCalendar: roll_following, next_day, prev_day, lme_days(start,end), mcx_pricing_expiry(month),
                 mcx_direct_expiry(month), mcx_roll_deadline(month), m1_contract_on(day)
  dates.py       planned_dates(ticket, lot), expected_dates(ticket, lot, info_date)      # §3.1 + D7
  cashflows.py   Flow dataclass; trade_flows(ticket, state, cal, info, hist) -> list[Flow]   # CF-01..CF-26
  validate.py    validate_book(trades, counterparties, panel, parity) -> list[Issue]; raises on errors
  run.py         main(): validate; write trade_book.csv, trade_hedges.csv, trade_cashflows.csv (PLANNED + REALISED)
desk/mtm/                            (P3)
  market.py      MarketState (frozen; blocks; swap(block, other); shock(...); from_panel(date, variant, mcx_series));
                 History(panel, mcx_series); lme_forward(), mcx_price(), fx_forward() — array-safe
  valuation.py   load_book(); value_trade(ticket, legs_asof, state, cal, info, hist) -> dict[leg_id, LegValue];
                 value_book(...)
  attribution.py attribute(book, dates, hist) -> (mtm_daily, attribution_daily, attribution_leg_daily)
  exposures.py   exposures(book, date, hist) -> DataFrame rows
  events.py      event_windows(panel), counterfactual(book, kind), event_tables(...)
  run.py         main(): base + MIRROR + PIT runs, exposures, VM, events
```
Dependency direction: `desk.mtm.market` ← `desk.book.cashflows` ← `desk.mtm.valuation` (no cycle). Excel (P3 workbook)
reproduces EX-A's daily MTM and its eight attribution columns with closed-form per-leg formulas (the funding leg is a
running sum), which is why every leg formula above is closed form.

### 8.3 Example tickets (fixtures `tests/fixtures/trades_examples.yaml`; together they exercise every leg type)

| Leg / feature | EX-A T91 | EX-B T90 | EX-C T92 |
|---|---|---|---|
| Lane, grade, qty | JEA_NSA, zorba, 1,040 MT (40×20ft) | USEC_MUN, tense, 2,520 MT (120×40ft, 2 lots) | JEA_NSA, tense, 1,000 MT (40×20ft) |
| Trade date (eligible week) | 2022-03-18 | 2022-05-20 | 2022-06-10 |
| Laycan / B/L | 01–15 Apr / 08-Apr | 01–15 Jun / 06-Jun, 14-Jun | 01–15 Jul / 08-Jul |
| Incoterm / freight | CFR (none) | FOB, FIXED_AT_TRADE, COLLECT | FOB, FLOAT_STOP_LOSS (ref = index 10-Jun, latest booking 28-Jun), PREPAID |
| Purchase pricing | FIXED USD 2,330/t | LME_AVG Jul cash × 0.695, prov 90% | LME_AVG Aug cash × 0.63, prov 90% |
| LC | sight | usance 90d, confirmed (applicant) | sight |
| PSIC | yes | no | yes |
| Customs / IGST / credit / differential | ✓ / ✓ / ✓ / – | ✓ / ✓ / ✓ / ✓ | ✓ / ✓ / ✓ / ✓ |
| Quality | moisture 1.8% (deduction) + contamination +1 pt (discount), supplier claim CF-12; buyer claim 0.5% | L1 moisture 1.2%; L2 contamination +1.5 pts in final invoice | 2 boxes rejected (RADIOACTIVITY) refunded via final invoice |
| Sale | FIXED ₹2,38,000/t, CREDIT 30d, **booked 01-Apr** (MARK 18-Mar→01-Apr) | MCX_AVG × 0.917 − ₹22,300, CREDIT 30d, booked at trade | FIXED ₹1,65,000/t, **ADVANCE**, booked 11-Jul (MARK 10-Jun→11-Jul) |
| MCX | SELL 136 lots Apr-22 on 18-Mar, closed 01-Apr at sale | SELL 138 Jun-22, ROLL 21-Jun to Jul (70 + 68), closes 12-Jul / 20-Jul | BUY 118 Aug-22 on 11-Jul (short metal: fixed sale vs unpriced Aug QP), SELL 59 on 10-Aug and 59 on 18-Aug (DIRECT roll deadline) |
| MCX beyond M2 | – | sale QP estimate for Aug contract on 20-May (M4) | – |
| FX forward | BUY USD 100% at trade date to LC payment date | BUY USD on each B/L to usance maturity | BUY USD 50% at trade date |
| Ops events | – | void-call notice (27-Jul), CFS congestion demurrage, buyer delay to 24-Oct | – |
| Buckets exercised | new_deal, a, c, e, f, g | new_deal, a, (b≈0), d (memo), e, f, g | new_deal, a, c, d, e, f, g |

(Forward cancellation, `LME_ON_DATE`, `SWITCH_TO_ADVANCE` mitigation and `REJECT_LOT` are covered by small synthetic unit
tickets in the tests rather than the three narrative fixtures.)

### 8.4 Test strategy (`tests/test_book.py`, `tests/test_mtm.py`)
Synthetic panel builder `tests/fixtures/synthetic_panel.py` (constant or step-shocked columns, MCX via the proxy
formula, register paths overridable through `MarketState` injection).
- **T01 schema/validation:** fixtures load; one mutated copy per rule V01–V17 raises (e.g. laycan spanning months,
  QP not M+1, sale after arrival, close inside tender period, credit 60d, name without (SIM), notice before 27-Jul,
  receipt after HORIZON_END, typed fill price).
- **T02 constant market** (flat curve, `r_inr = r_usd × 365/360`, constant WC): buckets a–e and g are exactly 0 every
  day; P&L = new_deal + f only.
- **T03 single-block shocks:** one-day +10% `lme_3m` → only a (and cross-term-free); +1% `usdinr` → only e; grade step →
  only c and only on MARK days; freight step → only d and only while unbooked; β shock (mirror-like) → only b.
- **T04 hedge consistency:** on the real panel base run, |b| per trade-day is rounding-only (bound: ₹0.5 × (open lots +
  unpriced MCX-linked sale MT / 5)); EX-A over the
  18-Mar→01-Apr hedge period: |Σ(a)_physical + Σ(a)_MCX| ≤ one-lot rounding + grade-factor/duty-ratio effects (printed).
- **T05 zero residual:** fixtures and `config/trades.yaml` on the real panel: max |residual| ≤ ₹1 (expect < 1e-4);
  `X` recomputation equals previous `X_new` (< 1e-6).
- **T06 terminal identity:** at HORIZON_END, V = 0 for all legs; CumPnL = Σ REALISED flows (PNL+TAX+FUNDING) ± ₹0.01;
  Σ COLLATERAL = 0; Σ TAX = 0 when ITC available.
- **T07 M+1:** EX-B `P_fin` = 0.695 × mean(official cash over July-2022 LME days) computed independently with pandas.
- **T08 LC/usance/duty arithmetic:** hand-computed CF-01, 02, 08, 09, 10, 13, 14, 16 for EX-B L1.
- **T09 MCX:** Σ VM = dir × lots × 5000 × (fill_c − fill_o) per tranche; IM back to 0 after the last close; ROLL costs
  land in g.
- **T10 FX:** EX-A Σ(e) over (PURCHASE + FX_FORWARD) from 18-Mar to payment = 0 ± rounding; cancellation unit ticket.
- **T11 no look-ahead:** for 20 sampled (trade, t), `Π(legs(t), S(t), t, t)` is unchanged when every panel row after t is
  replaced by NaN and ops outcomes after t are replaced by planned values (proves valuation and revelation are PIT).
- **T12 determinism:** `desk.book.run.main()` and `desk.mtm.run.main()` twice → identical SHA-256 of every CSV.
- **T13 exposures:** delta × small bump ≈ revaluation (rel. error < 1e-3); MC API on 5 paths equals a scalar loop.
- **T14 events:** window rules reproduce 07-Mar/15-Jul, 22-Apr/09-May, 05-Apr/14-Jul on the real panel.
- **T15 counterfactuals:** `NO_MCX` P&L difference = Σ MCX-leg P&L + funding difference on VM/IM (reported split).
- **T16 revelation:** EX-B L2 expected demurrage grows by exactly 60 × 35 USD per calendar day of expected dwell beyond
  14 days (first chargeable day = dwell day 15), booked in f; each overdue calendar day of the buyer receipt adds that
  day's funding on the receivable, booked in f; nothing about L2's delay is visible before 25-Jul (planned arrival).

---

## 9. Edge cases, simplifications and what not to model

### 9.1 Edge cases the engine must handle
- Cashflow date on a non-LME day → roll following (Indian holidays are priced; UK holidays such as 15/18-Apr, 02-May,
  02/03-Jun and 29-Aug-2022 push flows a day or two).
- QP days after `cal` but the contract beyond the panel's M2 → parity extrapolation with β of M2.
- Final invoice balance negative (refund in a falling market) → inflow; shown as supplier exposure.
- 100% rejection of a lot → sale quantity 0; over-hedge visible in exposures; no automatic hedge change.
- Sale booked on trade date → MARK never exists; sale booked on arrival date → allowed (V08 boundary).
- Overdue milestones with no notice → rolling expectation; notices with `eta` earlier than `next_panel_day(info)` are
  floored.
- Positive trade cash balance before costs (ADVANCE sale) → earns WC rate until the last flow.
- MIRROR MCX gaps > `MAX_FILL_BDAYS` → raise (no silent fill).
- Forward value date ≠ actual payment date → residual FX exposure shown, no automatic rollover.
- Trades whose flows would pass `HORIZON_END` → validation error (not truncation).

### 9.2 Simplifications (and why acceptable for an interview-grade desk)
1. Laycan in one calendar month; B/L never slips outside it (removes QP uncertainty; late-shipment default is a separate risk).
2. MOLSO tolerance not exercised; B/L weight = plan (claims capture the realistic weight story).
3. One CFR market price per grade for both lanes (CONTRACTS §5), so freight risk is only unbooked FOB freight.
4. Forward curves: linear LME Cash–3M (P1's curve), flat 3M money-market curve for all FX tenors, MCX carry at INR 3M.
5. IM at a flat `mcx_al_margin_used_frac` with a stress column; no SPAN, no DPL lock-limits, no delivery.
6. Output GST, TDS/TCS, bank charge minimums, customs bonds, re-export costs ignored (small or seller's account).
7. Funding at one WC rate, simple interest, symmetric; no compounding; no desk overhead or capital charge.
8. Demurrage one blended first-slab rate (no escalation slabs); detention and ground rent combined.
9. Supplier claims settle at `claim_recovery_frac`; no supplier default in base.
10. Grade-factor marks use the register's lag-2 reconstruction (labelled hindsight; PIT variant run in parallel).
11. MCX on the LME calendar with LME-cash-based proxy (CONTRACTS §3, §4.5).

### 9.3 What NOT to model
LME futures/TAPO/MASP hedges (not accessible to the desk in 2022; mention as an interview talking point only); options;
discounting of MTM (CONTRACTS §7.3); bulk vessels, charter parties and laytime; storage and inventory carry after
arrival; stochastic operations inside the base book; buyer default in the base book (P4 stress); hedge accounting;
tax on profits; price-prediction of any kind; intraday prices; real counterparties or vessel names.

---

## 10. What this does and doesn't tell you

**Does:** it turns each trade ticket into a dated, rupee-reconciled ledger and a daily mark that respects how an
Indian scrap import desk actually gets paid and pays — LC timing, M+1 averaging, provisional and final invoices,
out-turn claims, BoE duty and IGST credit, demurrage, buyer credit and the cost of financing all of it. It splits every
day's P&L into LME level, LME–MCX basis, scrap grade spread, freight, USD/INR, operational penalties and carry with no
unexplained residual, and it shows hedge effectiveness and forward-book offsets in the same numbers the risk pack uses.

**Doesn't:** it is not evidence of what a 2022 desk earned. Trades, counterparties and every operational outcome are
simulated. MCX is a duty-parity proxy, so in the base run the LME–MCX basis bucket is empty by construction — the real
basis appears only in the mirror sensitivity, which itself is third-party data. Scrap grade marks rest on a lag-2 unit
value ratio published months later (hindsight) and freight levels are hindsight-calibrated reconstructions, so
buckets (c) and (d) are reconstructions, not observed market moves. Forward curves are linear/flat approximations. A
zero residual proves the arithmetic is closed, not that the model is right; the attribution order (a → g) is a
convention and cross-terms depend on it.

---

## 11. Provenance of position-model inputs

| Input | Flag | Where it bites |
|---|---|---|
| LME official cash & 3M (Westmetall) | DIRECT | fixings, curve, parity |
| USD/INR ECB cross; INR/USD 3M rates; CIP forwards | PROXY | all FX, forwards, MCX parity, usance benchmark |
| CBIC customs rate path | DIRECT | duty base |
| MCX panel series | PROXY (import parity) | hedges, MCX-linked sales, factor b ≈ 0 |
| MCX mirror | PROXY (third-party) | basis sensitivity only |
| Grade factors (lag-2 mix + differentials) | ASSUMPTION (hindsight) | MARK, factor c |
| Freight levels | ASSUMPTION (level) / PROXY (shape) | unbooked FOB freight, factor d, fixture memo |
| Duty rates, IGST, MCX contract specs, SBI card LC fees, MSMED cap | DIRECT | flows, validation |
| Transit/clearance/free days, demurrage rate, port charges, payloads, WC spread, usance spread, confirmation fee | ASSUMPTION / PROXY | dates, flows, funding |
| Proposed `book.yaml` keys (§2.14) | ASSUMPTION (two PENDING verification) | dates, costs |
| Ops outcomes, notices' magnitudes, counterparties, trades | SIM | factor f, event #3 |
| Void-call disruption date (27-Jul-2022) | DIRECT (Container News via freight_notes S4) | E3 start / notice floor |

---

## 12. Open issues and Phase 0/1 findings to report (not fixed here)

1. **MCX Aug-2022 expiry mismatch (Phase 0):** the panel's contract calendar uses the last-calendar-day rule, so M1 on
   31-Aug-2022 is the August contract with expiry 31-Aug, while `mcx_al_expiry_dates_2022` (DIRECT) says 30-Aug. The
   proxy prices an already-expired contract for one day. Engine: pricing expiry = panel rule (keeps β ≈ 0), roll
   deadlines = DIRECT dates. Suggest P0 use the DIRECT list for 2022 in `desk.data.mcx.contract_calendar`.
2. **FX bank margin on spot conversions:** `fx_forward_bank_margin_inr` is defined for forwards; the engine also applies
   it to spot TT conversions of physical USD flows. A separate `fx_spot_bank_margin_inr` (or a note widening the key)
   would be cleaner.
3. **§5 omits trade-finance charges:** LC issuance, confirmation, usance commission/interest and bill commission
   (~0.3–0.6% of cargo value, ≈ ₹700–1,400/t) are not in `landed_inr_t`, and `margin_threshold_inr_t`'s note does not
   list them. P2's deal-sheet reconciliation will show this gap explicitly.
4. **MCX proxy ignores daily price limits:** e.g. −12% proxy move on 08-Mar-2022 vs the 9% maximum slab; V10 only warns.
5. **Grade and freight marks carry hindsight** (register notes): PIT grade variant is a mandatory parallel run; freight
   has no PIT level for Mar–Apr 2022.
6. **PENDING verifications** for proposed keys: UCP 600 Art. 14(c)/30, MCX transaction charges, CTT rate.
7. **MCX calendar = LME calendar:** VM bunches around UK holidays (e.g. 29-Aug-2022) and Indian holidays are priced.
8. **Attribution-convention interpretations of CONTRACTS §7.4** that the synthesizer should confirm in the contract
   text: (i) `new_deal` is evaluated at the day-t market after the seven steps (listing it first in `PNL_BUCKETS` is a
   column order, not a step order); (ii) factor (f)'s "block" is the operational information set, not a market price;
   (iii) the calendar roll (fixings, settlement, carry, funding accrual) is part of (g), and ROLL bookings' value goes to (g).
