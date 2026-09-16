# 30 — Position & valuation model (FINAL)

> **ACADEMIC SIMULATION — not actual trades.** Every counterparty, vessel, forwarder, bank and operational outcome
> named in this document or in the example tickets is fictional and labelled (SIM).

This is the single reference for Phases 2–5. It fixes the trade-ticket grammar, the cashflow catalogue, the daily
valuation function, the attribution method, the exposure set and the adverse-event definitions. It is a synthesis of
two independent proposals, judged in §0 and merged with the calls recorded in §1.

Binding upstream: `CONTRACTS.md` §1 (ground rules), §3 (calendar), §5 (desk economics), §5a (trade eligibility),
§6 (output contracts), §7 (position-model decisions) and the new §7a; `docs/spec/MASTER_SPEC_V3.md` Tables 4–6;
the Phase 0 register and panel; Phase 1 helpers (`desk.parity.model.eligible_on`,
`desk.parity.term_structure.prompts` / `forward_price`, `desk.parity.quality.settle_weight_and_penalty`).

Executable companions, already written and tested: `desk/book/schema.py` (the ticket grammar and its validation
rules), `config/trades.example.yaml` and `config/counterparties.example.yaml` (three fixtures covering every leg
type), `tests/test_book_schema.py`.

---

## 0. Judgement — how the two proposals were scored and what was taken from each

Both proposals are complete and neither is wrong. They differ in where they start: **A** starts from how the cargo
actually moves and gets paid, **B** starts from the P&L identity a product controller signs. Scored 1–5 against the
five criteria the synthesiser was given:

| Criterion | A (physical) | B (control) | Why |
|---|---|---|---|
| **Spec coverage** (Tables 4–5, CONTRACTS §7) | **5** | 4 | A covers Table 4 more completely — multi-lot laycans and vessels (2.1, 2.8), provisional/final invoicing (2.4), the full LC fee stack (2.6), MOLSO and rejection clauses (2.2). B covers CONTRACTS §7 more precisely and is the only one to propose `pnl_controls.csv`. |
| **Physical realism** | **5** | 3.5 | A's tickets ship on 2–3 bills of lading, price per B/L, survey per lot and settle claims separately. B's one-ticket-one-B/L collapses a 2,500 MT container contract into a single sailing, which no physical trader would recognise. |
| **Exact additivity of attribution** | 4 | **5** | Both telescope. B is materially better on *why*: one pure `Π(C, E, M, τ)` with contracts-as-of and events-as-of as explicit arguments, a total computed **independently** from the cash ledger, and a planted-bug test proving the ₹1 residual is a control rather than a formality. A's `L_noroll` device for `new_deal` and its routing of roll bookings to (g) are less clean, and A leaves the day's funding accrual implicit. |
| **Exposures for Phase 4** | 4 | **5** | Both bump-and-revalue the same valuation. B's set is better specified — hedge-ratio columns, physical/hedge/forward subsets, a cross bump for delta-gamma, pre-settlement buyer exposure — and its `revalue_book` signature states exactly what is held (clock, contracts, events) and why. |
| **Simplicity / implementability** | 2.5 | **4** | A is 26 cashflow types, 17 rules, a rolling-revelation rule with dated notices and per-lot expected-date recomputation. That is a lot of machinery for one engineer. B's `known_date` event model gets ~90% of the behaviour for a fifth of the code. |
| **Total** | 20.5 | 21.5 | |

**Decision. B is the backbone; A is grafted onto it.** The two criteria B wins are the ones that decide whether the
engine can be signed off at all; the two A wins are the ones that decide whether a physical trader believes the
book. Taking B's spine and A's physical layer gets both, and the pieces compose cleanly because B's state vector is
indifferent to how many legs a ticket has.

**Taken from B (backbone):** one pure valuation function with explicit contracts-as-of / events-as-of / clock
(D2); the seven-block state vector and block-swap chain with `new_deal` computed last (D8); the residual as a
genuine control, with the total built independently from the cash ledger (D9); the point-in-time guard that raises
rather than silently reads ahead (D10); the replacement-value mark including the 1-month forward FX basis and the
cross-phase reconciliation to Phase 1 (D5); the explicit (f)/(g) split of the daily funding accrual (D6); the
`known_date` event model (D7); the exposure table and the Monte Carlo API (§7).

**Taken from A (physical layer):** one ticket = one purchase SPA with 1–3 shipment lots, each its own bill of
lading, priced and surveyed separately (D1); the provisional/final invoice pair and the standalone supplier quality
claim; the full trade-finance stack (opening, confirmation, usance commission, bill commission, usance interest);
PSIC, rejection at the radiation portal, demurrage on chargeable dwell; the "unbooked FOB freight is the only live
freight exposure, a fixture is a memo plus a counterfactual" framing (D12); the adverse-event counterfactual books;
the lot-level `attribution_leg_daily.csv` grain.

**Neither, decided here:** rolls are value-neutral at settle and contribute only execution cost, routed to (g) by
booking purpose (D8c) — A booked the roll spread as a lump in (g), which double-counts against the daily carry that
is already there; B made rolls contribute nothing at all, which loses the execution cost. MCX positions are keyed
by **contract month**, not by expiry date (D4b), which removes the 30-vs-31 August trap both proposals had to work
around. The hypothetical freight swap is barred from the base book (D12b). Pricing types are cut to two per side.

---

## 1. Decisions at a glance

| # | Decision | Why |
|---|---|---|
| **D1** | **One ticket = one purchase SPA carrying 1–3 lots**, each lot one bill of lading with its own B/L date, vessel and box count. Quantity is `Σ boxes × container_payload_mt_<box>_<grade>` — containers ship whole. Sales cover whole lots. | A 1,000–5,000 MT container contract sails 2–3 times. Per-lot B/L dates drive LC presentation, usance maturity, arrival, survey and demurrage; collapsing them loses the whole operational story. |
| **D2** | **One pure function** `Π(ticket; C, E, M, τ)` = cumulative P&L, where `C` = contracts-as-of date, `E` = events-as-of date, `M` = market state, `τ` = clock. Daily MTM, attribution, exposures, counterfactuals, stresses and Monte Carlo all call it. It reads no files, takes no wall clock, and is vectorised over array-valued `M`. | Only one code path can be wrong. Risk numbers can never disagree with P&L, and attribution adds up by construction. |
| **D3** | **Two pricing formulas per side.** Purchase: `FIXED` USD/t on the incoterm basis, or `LME_M1_AVG` = factor × the arithmetic average of LME **official cash** over the calendar month after the B/L month, provisional on B/L, final after the quotational period. Sale: `FIXED` ₹/MT or `MCX_AVG` = factor × the MCX near-month average over a stated window. An `LME_M1_AVG` laycan must sit inside one calendar month. | Table 4 row 2.4 asks for a mix of fixed and M+1 average; two types per side cover it. The one-month laycan makes the quotational period known on the trade date, so there is no hindsight in the pricing period. |
| **D4** | **MCX = duty-paid LME parity + basis.** `F(M, τ, X) = [cash × usdinr / 1000 × (1 + bcd_primary × (1 + sws)) + mcx_domestic_premium] × (1 + r_inr × dte/365) + b[X]`. On `PROXY_IMPORT_PARITY` days `b ≡ 0` by construction (the panel formula replicates to 5.0e-5 ₹/kg over Jan–Oct 2022, i.e. the 4-dp CSV rounding). **(D4b)** A position names its **contract month**, never an expiry date: prices come from the panel's M1/M2 slot for that month, the roll deadline from the DIRECT `mcx_al_expiry_dates_2022` date. | An LME move must reach the hedge through (a), FX through (e), carry through (g) — only a true residual belongs in (b). Otherwise a proxy series manufactures fake basis on every hedged day. Keying by month makes the panel's 31-Aug slot and the real 30-Aug expiry two views of one contract instead of a validation failure. |
| **D5** | **Unsold cargo is marked at import replacement value**, not at the MCX-anchored smelter netback: `R = goods + BCD + SWS + port/PSIC` at today's market, **excluding finance**, with goods converted at the same 1-month forward Phase 1 uses (`parity_goods_fx_basis`). Sale margin is recognised in `new_deal` when the sale is contracted. | Marking at the netback books the whole parity margin on day one on `domestic_anchor_premium_inr_t`, an ASSUMPTION whose own evidence spans −52k…+13k ₹/t. It also keeps grade factor (c) a live factor for open inventory. Using the 1-month forward is both the right tenor for a *replacement* cargo and what makes `R` reconcile to Phase 1 to ₹0.01. |
| **D6** | **Funding is a daily accrual** at `wc_rate_inr_pa` (ACT/365, symmetric) on each trade's actual dated cash balance — P&L flows including variation margin, plus the balance-sheet flows (IGST paid/credited, MCX initial margin). The accrual is **split**: interest on an overdue receivable goes to (f), everything else to (g). P3 never reads `finance_days_*`, `finance_inr_t` or `igst_finance_inr_t`. | Buyer credit, usance deferral, the IGST lag and margin are each financed exactly once, from their dates. Phase 1's per-tonne finance term is a parity screen shortcut, not a cashflow; reading both would double-count. |
| **D7** | **Events are dated facts, not rolling expectations.** A `quality`, `logistics_delay` or `buyer_payment_delay` event carries a `known_date`; from that day the engine provisions its full effect (undiscounted MTM of a dated future cost). A delay that unfolds in stages is two events, not new machinery. | A controller provisions a known delay in full the day it is known. This gets A's behaviour without A's per-day expected-date recomputation. |
| **D8** | **Attribution swaps the seven blocks in `FACTOR_ORDER`, then the contracts block.** `new_deal` is **computed last, reported first**. **(D8b)** The day's funding accrual is added explicitly to (f)/(g) per D6, not through a swap. **(D8c)** The contracts step is evaluated per leg: legs booked with purpose `ROLL` route their value change to (g) `roll_term_structure`; every other booking routes to `new_deal`. | New contracts are then valued at the day's closing market with no factor cross-terms. A roll at settle is value-neutral, so (g) receives exactly the roll's execution cost — which is what "roll yield" means in Table 5 row 3.2(g) — while the carry convergence stays where it already is, in (g), booked daily. |
| **D9** | **Residual is a control, not a formality.** `total_t` comes independently from the ledger (`Δ[realised cash + funding + Σ mtm]`); `residual = total_t − Σ buckets`, and `|residual| ≤ ₹1` per trade-day. A test plants a hidden input (a parameter read at a settle date instead of the clock) and asserts the residual catches it. | The two paths agree only if `Π` has no hidden inputs. That makes the ₹1 check a real sign-off, not arithmetic hygiene. |
| **D10** | **Point-in-time is enforced, not documented.** `MarketHistory` raises `LookaheadError` when any accessor is called with a date beyond the clock. Time-pathed parameters are read at the clock, never at a future event date. Decision dates must be LME trading days and are never silently rolled; derived cashflow dates roll **following**. | CONTRACTS §1.2 and §5a. A rule that is only written down gets broken; a rule that raises does not. |
| **D11** | **Derived numbers never appear in a ticket.** Fill prices, forward strikes, the freight index at fixture, box counts, quotational-period dates, invoice values and cashflow dates are recomputed point-in-time and written to `outputs/tables/`. The loader rejects them by name. Executed *decisions* (lots, notionals, the fixture rate the desk actually paid, dates) are typed. | A typed derived number is hindsight with a plausible face. The distinction — market observables are derived, negotiated outcomes are typed — is the line the loader enforces. |
| **D12** | **Freight:** only **unbooked FOB freight** is a live exposure (factor d). A booked fixture is a fixed payable; `fixture_vs_market_inr` is a daily memo and the fixture *decision* is a counterfactual. **(D12b)** The proxy freight swap is HYPOTHETICAL, labelled in every row, and barred from the base book. | Under CONTRACTS §5 the CFR grade factor does not move with freight, so a CFR cargo carries no freight price risk. No liquid India-lane container derivative existed in 2022; putting one in the base book would present a fiction as a hedge. |
| **D13** | **Grade factors: base path everywhere, PIT variant everywhere.** Contract factors are set from `grade_factor_<g>` at the trade date (plus a stated negotiation delta recorded in `terms_basis_note`); the PIT sensitivity run recomputes **both** contract factors and marks from `grade_factor_mix_pit + grade_factor_diff_<g>`. | Mixing a base mark with a PIT contract would book a day-one loss of up to −0.12 × LME × quantity in March 2022 — a pure artefact of two reconstructions disagreeing. §5a already forces the PIT screen on *selection*, which is where it belongs. |
| **D14** | **The engine never trades.** Rule-based decisions (the freight stop-loss, MCX roll deadlines) are resolved by P2 into dated actions with a `decision_date`, and P3 re-derives each one from data dated on or before it. | Table 4 row 2.9 and CONTRACTS §5a: no hindsight in decisions. |

---

## 2. Conventions and invariants

- **Sign.** Every amount is from the desk's point of view: `+` is cash in or a gain. Base currency INR; USD is memo.
- **Clock.** `τ` is a panel (LME trading) day. `t⁻` is the previous panel day. Calendar intervals (weekends,
  holidays) enter only through day counts.
- **Undiscounted** (CONTRACTS §7.3). MTM of a leg is the INR value of its unsettled cashflows with no discounting;
  finance is an explicit accrual, never a discount factor.
- **Identity** (per trade, per day): `cum_pnl(τ) = realised_pnl_cash(≤τ) + funding_accrued(≤τ) + Σ_legs mtm(τ)`, and
  `daily_pnl(τ) = cum_pnl(τ) − cum_pnl(t⁻)`. Before the trade date, `cum_pnl = 0`.
- **Balance-sheet flows** (IGST paid and credited; MCX initial margin posted and returned) move cash and therefore
  funding, but are not P&L. Their undiscounted lifetime sum is zero per trade, and a test asserts it.
- **Determinism.** No randomness in P2/P3. Rows sort by `(date, trade_id, leg_id)`; fixed float formats (INR/USD
  2 dp, ₹/kg and USD/t 4 dp, rates and fractions 6 dp) so re-runs are byte-identical.
- **Named constants** live in `desk/book/constants.py`: `RESIDUAL_TOL_INR = 1.0`,
  `MCX_PROXY_REPLICATION_TOL_INR_KG = 1e-3`, `LME_CURVE_EXTRAPOLATION = "flat_beyond_3m"`,
  `LEDGER_TOL_INR = 0.01`, `CRASH_FORTNIGHT_RETURN_DAYS = 10`, and the bump sizes in §7. Parameters come from the
  register (CONTRACTS §1.6); model-structure constants from MASTER_SPEC Table 4 live in `desk/book/schema.py`.
- **Units** via `desk.units` and the column suffixes of CONTRACTS §1.3, without exception.

---

## 3. Ticket and counterparty schema

`desk/book/schema.py` is the executable specification: frozen dataclasses, enums, `load_trades(path)`,
`load_counterparties(path)`, `load_book(...)`, and `validate_counterparties` / `validate_trades` / `validate_book`
returning `Issue(severity, code, where, message)`. The grammar is **closed** — a field that is not listed is an
error naming the path and the alternatives; anything the engine must not read goes under an explicit `extra`
mapping at that node. `config/trades.example.yaml` and `config/counterparties.example.yaml` are the worked shape.

### 3.1 Ticket structure

```
Ticket   trade_id, status, trade_date, lane, grade, quantity_mt, rationale{text, parity_week_end, cited_columns}
  purchase   supplier_id, spa_ref, incoterm, named_place
             spa{isri_grade_spec, moisture_franchise_frac?, contamination_limit_frac?, discount_multiple?,
                 rejection_excess_frac?, radioactivity_clause_key, penalty_schedule_key, quantity_tolerance_frac}
             pricing{type: FIXED|LME_M1_AVG, price_usd_t | (lme_reference=CASH, factor_frac, premium_usd_t,
                     provisional_frac), terms_basis_note}
             payment{instrument: LC_SIGHT|LC_USANCE, usance_days?, lc_open_date, issuing_bank, confirmed,
                     confirmation_charges_for?}
  shipment   laycan_start, laycan_end, load_port, discharge_port, lots[1..3]{lot_id, boxes, bl_date, vessel, voyage}
  freight    (FOB only) booked_by, forwarder, payment_terms, risk_layer, fixture_date?, rate_usd_box?,
             stop_loss{stop_loss_usd_box, latest_fixture_date, note} | swap{...hypothetical}
  sales[]    sale_id, buyer_id, contract_date, lot_ids, delivery_basis, quality_passthrough,
             pricing{type: FIXED|MCX_AVG, price_inr_t | (mcx_series=M1, window_start, window_end, factor_frac,
                     premium_inr_t), terms_basis_note}
             payment{terms: CREDIT|ADVANCE|ADVANCE_PLUS_CREDIT, credit_days?, advance_frac?, advance_date?}
  hedges     mcx{hedge_ratio_target, exposure_basis, basis_risk_note, unhedged_reason,
                 tranches[]{hedge_id, contract_month, direction, lots, entry_date, exit_date,
                            exit_reason: UNWIND|ROLL|TRANCHE, roll_to?}}
             fx_forwards{hedge_frac_target, lines[]{fwd_id, booking_date, direction, notional_usd, value_date,
                                                    matched_leg, cancel_date?}}
  events     quality[]{lot_id, moisture_actual_frac, contamination_actual_frac, rejected_boxes, rejection_reason?,
                       claim_recovery_frac, flag}
             logistics[]{event_id, lot_id, known_date, arrival_delay_days, extra_dwell_days, real_trigger_ref, flag}
             buyer_payment_delay[]{event_id, sale_id, known_date, delay_days, reason, flag}
```

Counterparties carry `cp_id, name, role, type, country, location, lanes, grades, credit_limit_inr` (buyers) /
`claims_exposure_limit_usd` (suppliers), `default_payment_terms, credit_days_default, lc_confirmation_required,
safe_origin_for_psic, msme_registered, flag` and a static `profile` block that feeds the Phase 5 logistic model
(relationship start, prior invoices, prior DPD mean/max, defaults, disputed claims, turnover, rating, security).
Dynamic features — exposure vs limit, days past due, order concentration — are computed by the engine into
`book_exposures_daily.csv`, never typed.

### 3.2 Validation rules

Enforced in `desk/book/schema.py` (structural, register-aware, no panel needed); each has a code and a test:

| Code | Rule |
|---|---|
| V01 | Unique and well-formed ids (`T\d{2}`, `L\d`, `S\d`, `<TRADE>-MCX-\d+`, `<TRADE>-FX-\d+`, `(SUP\|BUY)_[A-Z0-9]+_\d{2}`). |
| V02 | Every counterparty, vessel, forwarder and bank name ends `(SIM)`; counterparty `flag = SIM`. |
| V03 | Counterparty role/type consistency; buyers carry a credit limit (0 = advance-only), suppliers a claims limit. |
| V04 | Every **decision** date is an LME trading day (when `panel_days` is supplied). |
| V05 | `trade_date` inside the window; `parity_week_end` is the latest week ≤ trade date; rationale present. |
| V06 | 1,000 ≤ `quantity_mt` ≤ 5,000; 1–3 lots; `quantity_mt = Σ boxes × payload` to ±0.5 MT. |
| V07 | Lane ↔ discharge port; FOB requires a freight block, CFR forbids one. |
| V08 | Laycan ordered, ≤ 31 days, not before the trade date; every B/L inside it; an `LME_M1_AVG` laycan inside one calendar month. |
| V09 | Buyer credit ≤ `msme_max_payment_days` (45, applied as desk policy). |
| V10 | Purchase pricing fields match the type; factor in 0.40–1.00; `provisional_frac` in (0.5, 1.0]. |
| V11 | `LC_USANCE` ⇒ 60–90 days; `LC_SIGHT` ⇒ none. `lc_open_date ∈ [trade_date, laycan_start]`. Confirmed LCs name the charges party. |
| V12 | Freight: fixture date and rate together or neither; fixture ≤ first B/L; stop-loss present and bookable before the boxes sail; the hypothetical swap only under `allow_hypothetical`. |
| V13 | Every lot sold exactly once; no sale before the purchase; (warning) no sale after the planned release. |
| V14 | Sale pricing fields match the type; MCX averaging starts on or after the contract date and ends ≤ `HORIZON_END`. |
| V15 | Payment terms internally consistent (`ADVANCE` ⇒ 100% with a date; `CREDIT` ⇒ no advance; mixed ⇒ both). |
| V16 | Supplier and buyer exist, have the right role, and the supplier loads that lane and grade. |
| V17 | MCX: whole lots within the DIRECT client position limit; listed contract month; exit after entry; a `ROLL` names a target entering the same day, same direction, same size, later month; a hedged ticket carries the row-2.7(c) basis-risk note, an unhedged one a stated reason. |
| V18 | Forwards: positive notional, value date after booking, cancel strictly inside; (warning) gross notional above `fx_hedge_no_documentation_limit_usd`. |
| V19 | Every ticket-dated cashflow (forward value dates) ≤ `HORIZON_END`. |
| V20 | Events: lot/sale cross-references; rejected boxes ≤ shipped; reason exactly when rejected; a cited void-call trigger cannot be known before 2022-07-27; simulated magnitudes flagged SIM. |

Deferred to `desk/book/validate.py` (they need the panel or Phase 1): `eligible_on(trade_date, grade, lane)` is
True (§5a); every **derived** cashflow date ≤ `HORIZON_END` after rolling; the stop-loss resolution reproduces from
the freight column; the fixture index and `fixture_vs_index_frac`; the buyer credit check at the contract date; a
warning when the MCX proxy moved beyond `mcx_al_dpl_max_frac` on an entry or exit day (a real limit-lock day).

---

## 4. Lifecycle, dates and cashflows

### 4.1 Date rules (per lot, from the B/L day `b`; `roll(x)` = first panel day ≥ x)

| Milestone | Rule | Register / new key |
|---|---|---|
| LC opened | ticket | — |
| PSIC, insurance attach | `b` | — |
| Documents presented; sight payment, or usance acceptance | `roll(b + lc_sight_payment_lag_days)` | new, 7 |
| Usance maturity (goods, usance interest, bill commission) | `roll(b + usance_days)` | ticket |
| Arrival | `roll(b + transit_days_<lane> + Σ arrival_delay_days)` | 5 / 40 |
| Joint survey (quality known) | `roll(arrival_cal + survey_lag_days)` | new, 1 |
| Bill of Entry: duty, IGST paid | `roll(arrival_cal + boe_lag_days)` | new, 1 |
| Release, delivery, port charges, demurrage | `roll(arrival_cal + clearance_delivery_days + Σ extra_dwell_days)` | 10 |
| IGST credit | `roll(boe_cal + igst_credit_lag_days)` | 45 |
| Final invoice (M+1) and its duty/IGST differential | `roll_bd(pricing_end, final_invoice_lag_bdays)` | new, 5 |
| Quality claim settled (fixed-price SPA) | `roll(survey_cal + claim_settle_lag_days)` | new, 30 |
| Sale invoice | `roll(max(release_cal, MCX window_end))` | — |
| Sale due | `roll(sale_invoice + credit_days + Σ delay_days)` | 30 |
| Freight paid (FOB) | prepaid `b`, collect `roll(arrival_cal)` | — |
| MCX roll deadline | `mcx_roll_days_before_expiry` panel days before the **DIRECT** expiry for that contract month | 7 |

Dwell for demurrage is counted in **calendar** days; each milestone rolls independently.

### 4.2 Quantities (Phase 1 `settle_weight_and_penalty` supplies the SPA arithmetic)

```
n_box   = Σ lot boxes                         payload  = container_payload_mt_<box>_<grade>
q_bl    = n_box × payload                     base_payload = container_payload_mt_<box>   (panel freight / port basis)
n_rej   = rejected_boxes (0 before the survey known_date)        q_rej = n_rej × payload
m_ex    = max(0, moisture_actual − moisture_franchise)           q_clr = q_bl − q_rej
disc    = discount_multiple × max(0, contamination_actual − contamination_limit)
q_acc   = q_clr × (1 − spa_moisture_deduction_ratio × m_ex)      # invoice and sale weight
```

Rejected boxes leave the Bill of Entry, the port charges and the sale, and are re-exported for the seller's
account. `disc` passes through to the sale when `quality_passthrough` is true.

### 4.3 Cashflow catalogue

`pnl_class`: **PNL** (P&L) or **BS** (balance-sheet: moves cash and funding, never P&L; lifetime sum zero).
"Fixed at" is the date from which the amount stops depending on the market state.

| leg_type | Ccy | Amount (desk sign) | Settle | Fixed at | Class |
|---|---|---|---|---|---|
| `PURCHASE_INVOICE` (FIXED) | USD | `−q_bl × price_usd_t` | sight `lc_pay`; usance `maturity` | trade_date | PNL |
| `PURCHASE_PROVISIONAL` (M+1) | USD | `−provisional_frac × q_bl × p_prov`, `p_prov = factor × cash(b) + premium` | as above | `b` | PNL |
| `PURCHASE_FINAL` (M+1) | USD | `−[q_acc × (factor × A_P + premium) × (1 − disc) − provisional_frac × q_bl × p_prov]` — **may be positive** (supplier refund) | `final_invoice` | max(`pricing_end`, survey known) | PNL |
| `QUALITY_CLAIM` (FIXED SPA) | USD | `+claim_recovery_frac × price × [q_rej + q_clr × ratio × m_ex + q_acc × disc]` | `claim_settle` | survey known | PNL |
| `FREIGHT` (FOB) | USD | `−n_box × rate_box`; `rate_box` = the fixture once `C ≥ fixture_date`, else `box_mkt(M)` | prepaid `b` / collect `arrival` | fixture_date (or `b`) | PNL |
| `FREIGHT_SWAP_HYPOTHETICAL` | USD | `+boxes × (box_mkt(M) − strike)` | `settle_date` | settle | PNL (labelled) |
| `INSURANCE` | INR | `−insurance_rate × insured_value_uplift × cif_usd × X(b)` | `b` | `b` | PNL |
| `PSIC` (JEA_NSA) | INR | `−psic_cost_usd_per_box × n_box × X(b)` | `b` | `b` | PNL |
| `LC_OPENING_FEE` | INR | `−lc_opening_fee_frac_per_month × ceil(validity/30) × lc_value_usd × X(open)`; `validity = laycan_end + lc_presentation_period_days − lc_open_date` | `lc_open` | `lc_open` | PNL |
| `LC_CONFIRMATION_FEE` (applicant) | INR | `−lc_confirmation_fee_pa × lc_value_usd × (validity + usance_days)/360 × X(open)` | `lc_open` | `lc_open` | PNL |
| `LC_USANCE_FEE` | INR | `−lc_usance_fee_frac_per_month × ceil(usance_days/30) × bill_usd × X(acceptance)` | `acceptance` | `acceptance` | PNL |
| `IMPORT_BILL_COMMISSION` | INR | `−import_bill_commission_frac × bill_usd × X(pay)` | LC payment | LC payment | PNL |
| `USANCE_INTEREST` | USD | `−bill_usd × (usd_rate_3m_pa@acceptance + usance_interest_spread_pa) × usance_days/360` | `maturity` | `acceptance` | PNL |
| `CUSTOMS_DUTY` | INR | `−cif_duty_usd × customs_usdinr_import@boe × bcd_scrap_hs7602 × (1 + sws_rate_on_bcd)`, `landing_charges_frac = 0` | `boe` | `boe` | PNL |
| `CUSTOMS_DUTY_DIFFERENTIAL` (M+1) | INR | same on `ΔAV = q_acc × (P_fin − P_prov) × (1 + i_ins) × customs_usdinr_import@boe` | `final_invoice` | `final_invoice` | PNL |
| `IGST_IMPORT` / `IGST_CREDIT` | INR | `∓(assessable + duty) × igst_rate_hs7602`, credit at `+igst_credit_lag_days` | `boe` / `igst_credit` | `boe` | **BS** (PNL if `igst_itc_available` is false) |
| `PORT_CHARGES` | INR | `−port_cf_charges_inr_t_<nsa\|mun> × base_payload × (n_box − n_rej)` | `release` | trade_date | PNL |
| `DEMURRAGE` | USD | `−(n_box − n_rej) × max(0, dwell_days − detention_free_days) × demurrage_usd_per_box_day` | `release` | event `known_date` | PNL |
| `SALE_ADVANCE` | INR | `+advance_frac × q_plan × P_sale` | `advance_date` | `advance_date` | PNL |
| `SALE_BALANCE` | INR | `+q_acc × P_sale × (1 − disc_passthrough) − advance` | `sale_due` | max(window_end, survey) | PNL |
| `MCX_VARIATION_MARGIN` | INR | per panel day `dir × lots × lot_mt × 1000 × (F(s) − F(s⁻))`; first day against the entry settle | daily | daily | PNL |
| `MCX_TRANSACTION_COST` | INR | `−lots × lot_mt × 1000 × fill × mcx_txn_cost_frac`; fill = settle ∓ `mcx_slippage_ticks × mcx_al_tick_inr_kg` against the desk | entry, exit | fill date | PNL |
| `MCX_INITIAL_MARGIN` | INR | `−Δ IM`, `IM(s) = lots × lot_mt × 1000 × F(s) × mcx_al_margin_used_frac`; returned at exit | daily | daily | **BS** |
| `FX_FORWARD` | INR | `sign × notional × (usdinr(T) − K)` at `T`, or `sign × notional × (X(M, cancel, T) − K)` at `cancel_date` | value / cancel | value / cancel | PNL |
| `INVENTORY_MARK` | INR | `+q_exp × R_{g,l}(M)` while no contracted sale covers the lot (D5); removed at the sale booking | n/a (mark) | never | PNL |
| `FUNDING` | INR | §4.4 | daily | daily | PNL |

**Not modelled** (documented in §11): output GST on domestic sales, TDS/TCS, profit tax, bank charge minimums,
customs bonds for provisional assessment, re-export cost of rejected boxes (seller's account), warehouse storage,
insurance claims, demurrage slab escalation.

### 4.4 Funding and the no-double-count argument

```
B(s)           = Σ amount_inr over flows (PNL and BS) with settle ≤ s          # accrued interest is not in B
acc(t)         = B(t⁻) × wc_rate_inr_pa(t⁻) × (t − t⁻).days / 365              for first_flow < t ≤ close_date
overdue(t⁻)    = Σ receivables whose contractual due (before delay events) ≤ t⁻ < settle
acc_overdue(t) = −overdue(t⁻) × wc_rate_inr_pa(t⁻) × (t − t⁻).days / 365       → bucket (f)
acc_carry(t)   = acc(t) − acc_overdue(t)                                        → bucket (g)
```

The rate is symmetric: the desk runs one cash-credit line that is always drawn, so a positive balance reduces
drawings at the same rate. Trade-level funding therefore adds exactly to desk-level funding.

Nothing is double-counted with Phase 1. `finance_inr_t = (goods + duty) × finance_days_l/365 × wc` bundles supplier
cash-out to buyer receipt — including the 30-day buyer credit — into one per-tonne approximation. P3 reads none of
`finance_days_*`, `finance_inr_t`, `igst_finance_inr_t` or `lc_opening_fee_frac`. Instead: buyer credit is funded
because the receipt is dated late in `B`; a usance LC is funded because no cash leaves until maturity, with
`USANCE_INTEREST` as an explicit flow; IGST is funded through the BS pair; MCX margin is funded through IM and VM.
The replacement value `R` also excludes finance, so the cost appears exactly once. `trade_book.csv` carries
`p1_finance_memo_inr` and `p3_funding_inr` side by side as a **diagnostic** — the gap is the usance, the advance and
the margin that Phase 1 never sees — not as a control.

---

## 5. Valuation at date t

### 5.1 Market state — the only door for dated market inputs

```python
@dataclass(frozen=True)
class MarketState:                      # every float may be a numpy array (broadcast) for Monte Carlo
    lme_cash_usd_t: float                            # (a) lme_flat
    mcx_basis_inr_kg: Mapping[str, float]            # (b) cross_exchange_basis, keyed by contract month "YYYY-MM"
    mcx_domestic_premium_inr_kg: float               # (b)
    grade_factor_frac: Mapping[str, float]           # (c) grade_spread
    freight_usd_t: Mapping[str, float]               # (d) freight, both lanes, base payload
    usdinr: float                                    # (e) fx
    customs_usdinr_import: float                     # (e) CBIC notified rate in force
    lme_spread_usd_t: float                          # (g) cash − 3M (panel sign: + = backwardation)
    inr_rate_3m_pa: float                            # (g)
    usd_rate_3m_pa: float                            # (g)
    wc_rate_inr_pa: float                            # (g)
    asof: date                                       # memo only; valuation never reads it
```

`MarketHistory` wraps `market_daily.csv` plus a `ParamProvider` (default `desk.config.value`; tests inject
overrides) and exposes `state_at(d)`, `cash(d)`, `usdinr(d)`, `mcx_price(d, month)`, `freight_box(d, lane)`,
`wc_rate(d)` and `panel_days`, each guarded: an accessor called with a date beyond the clock raises
`LookaheadError` (D10). Any dated input a later phase adds must be assigned to a block; unassigned dated inputs
default to (g).

Basis extraction in `state_at(d)`: for slot k ∈ {m1, m2} with contract month `Xk`, if `mcx_src(d)` is
`PROXY_IMPORT_PARITY` then `b[Xk] = 0.0` and the builder asserts `|panel − F_theo| ≤ MCX_PROXY_REPLICATION_TOL`;
otherwise `b[Xk] = panel_k − F_theo`. The third-party mirror (CONTRACTS §7.5) is an adapter yielding the same two
columns on the LME calendar (point-in-time ffill ≤ `MAX_FILL_BDAYS`, longer gaps raise), selected by
`MarketHistory(mcx_source="mirror")`; its outputs carry the `_mcx_mirror` suffix and are never base P&L.

### 5.2 Curves

```
lme_3m(M)          = M.lme_cash_usd_t − M.lme_spread_usd_t
w(τ, s)            = clip((s − τ).days / ((τ + 3 months) − τ).days, 0, 1)         # flat beyond 3M
cash_fwd(M, τ, s)  = M.lme_cash_usd_t − M.lme_spread_usd_t × w(τ, s)
cash_at(s; M, τ)   = H.cash(s) if s ≤ τ else cash_fwd(M, τ, s)                   # a fixing is known at EOD of its day
A_P(M, τ)          = mean over the panel days of pricing month P of cash_at(s; M, τ)

X(M, τ, T)         = desk.units.fx_forward(M.usdinr, M.inr_rate_3m_pa, M.usd_rate_3m_pa, (T − τ).days)  if T > τ
                   = M.usdinr if T == τ ;  H.usdinr(T) if T < τ
fx_forward value   = sign × notional × (X(M, τ, T) − K),  K = mid forward at booking + sign × fx_forward_bank_margin_inr

uplift             = 1 + bcd_primary_al_hs7601 × (1 + sws_rate_on_bcd)            # 1.0825
F(M, τ, month)     = [M.lme_cash_usd_t × M.usdinr / 1000 × uplift + M.mcx_domestic_premium_inr_kg]
                     × (1 + M.inr_rate_3m_pa × max(0, dte)/365) + M.mcx_basis_inr_kg[month]
A_MCX(window)      = mean over window days of (H.F(s, M1 month on s) if s ≤ τ else F(M, τ, M1 month on s))
box_mkt(M, lane)   = M.freight_usd_t[lane] × container_payload_mt_<box>           # panel USD/t is at base payload
```

The M+1 average uses the panel LME trading days of the pricing month. The future LME calendar is published in
advance, so this is not hindsight. `lme_cash_prompt_bdays` (the 2-day cash prompt) is ignored in the curve, as in
Phase 1's `forward_price`; the resulting error is a small (g) timing effect that vanishes as days fix.

### 5.3 Replacement value of unsold cargo (D5) — `R_{g,l}(M)`, ₹ per MT

```
cfr   = lme_3m(M) × M.grade_factor_frac[g]
cif   = cfr × (1 + insurance_rate × insured_value_uplift)
goods = cif × X(M, τ, τ + 1 month)                              # same basis as parity.yaml parity_goods_fx_basis
duty  = cif × M.customs_usdinr_import × bcd_scrap_hs7602 × (1 + sws_rate_on_bcd)
port  = port_cf_charges_inr_t_<nsa|mun> × payload_scale_l_g [+ JEA_NSA: psic_cost_usd_per_box × M.usdinr / payload_20ft_g]
igst  = (cif × M.customs_usdinr_import + duty) × igst_rate_hs7602     only when igst_itc_available is false
R     = goods + duty + port + igst                              # NO finance, NO igst finance
```

**Cross-phase control.** On every parity `value_date`, `R` must equal Phase 1's
`goods_inr_t + bcd_inr_t + sws_inr_t + port_inr_t` from `parity_weekly.csv` to ₹0.01. This is written to
`pnl_controls.csv` and is the strongest tie between the two phases.

**Why the 1-month forward, not spot.** `R` is what it would cost to *replace* this cargo today: a replacement
cargo is paid for at a sight LC about a month out. Using spot would make an at-market unsold cargo show a day-one
loss equal to the forward premium (₹340–610/t in the window) — exactly the artefact `parity_goods_fx_basis` was
chosen to avoid. The desk's own payable is separately valued at its own tenor; the small difference sits in (g).

### 5.4 The valuation function

```python
def trade_value(t: Ticket, C: date, E: date, M: MarketState, tau: date, H: MarketHistory) -> TradeValue:
    """Cumulative P&L and the per-leg breakdown.

    C = contracts-as-of (a term is active iff its contract / entry / booking / fixture date <= C)
    E = events-as-of    (an event is active iff its known_date <= E)
    tau = the clock. Settled flows (settle <= tau) are valued from H at their fixing and settle dates;
    unsettled flows from M at the clock. Returns Pi = Pi_val + Fund(tau), where Fund comes from the ACTUAL
    dated cash path (history only, §4.4) and Pi_val is everything else.
    """
```

It is pure (no files, no `desk.config` except through `H.params`, no wall clock), vectorised over any
array-valued field of `M`, and branches only on dates and contract terms — never on market values, except
`max(0, ·)` in demurrage, which depends only on dates.

---

## 6. P&L attribution

### 6.1 The chain

State `S(t) = (C_t, E_t, M_t, τ_t)` with `M_t = H.state_at(t)`. Per trade, per panel day:

| Step | Bucket | Block swapped `t⁻ → t` |
|---|---|---|
| 0 | — | `V0 = Π_val(C_{t⁻}, E_{t⁻}, M_{t⁻}, τ=t⁻)` |
| 1 | `lme_flat` (a) | `lme_cash_usd_t` — spread held, so the whole LME curve shifts in parallel |
| 2 | `cross_exchange_basis` (b) | `mcx_basis_inr_kg` (all months), `mcx_domestic_premium_inr_kg` |
| 3 | `grade_spread` (c) | `grade_factor_frac` (all grades) |
| 4 | `freight` (d) | `freight_usd_t` (both lanes) |
| 5 | `fx` (e) | `usdinr`, `customs_usdinr_import` |
| 6 | `demurrage_penalty` (f) | events-as-of `E`, **plus `acc_overdue(t)`** |
| 7 | `roll_term_structure` (g) | `lme_spread_usd_t`, `inr_rate_3m_pa`, `usd_rate_3m_pa`, `wc_rate_inr_pa`, **clock τ**, **plus `acc_carry(t)`**, **plus the value of `ROLL`-purpose bookings dated t** |
| 8 | `new_deal` | contracts-as-of `C` — every other booking dated t, valued at the day's close |

`bucket_k = V_k − V_{k−1}`, evaluated per leg so `attribution_leg_daily.csv` sums exactly to the trade row. The
funding accrual and the split of step 8 by booking purpose (D8b, D8c) are added as explicit per-leg amounts rather
than through a swap: they are realised amounts that exist only when the clock moves, and a roll's two legs are one
decision. A trade whose `trade_date = t` has `Π = 0` through step 7, so its whole first-day value is `new_deal`
(CONTRACTS §7.2).

### 6.2 Where the non-obvious items land

| Item | Bucket | Mechanism |
|---|---|---|
| A new M+1 fixing | (a) for the level; the estimate→fixing switch in (g) | Day t is already estimated from `M_t` at step 1; the clock at step 7 removes the one-day curve interpolation. |
| An MCX move | (a) via cash parity, (e) via usdinr, (g) via carry/rate/dte; (b) only the true residual | The hedge price is *recomputed* from the partially swapped state at every step, never read from the panel. |
| MCX roll | (g) — execution cost only | Exit and entry at the same settle are value-neutral; the roll's slippage and charges are the roll's real cost. Carry convergence is already in (g), booked daily. |
| Hedge entry/exit at settle | `new_deal` — slippage and charges only | |
| FX forward booked | `new_deal = −notional × fx_forward_bank_margin_inr` | The bank margin is the whole day-one value of a forward struck at the mid. |
| Freight fixture | `new_deal = n_box × (box_mkt − rate_box) × X` | Paying above the index is value given up on day one (Table 4 row 2.8). |
| Sale contracted | `new_deal = q × (P_contract − R)` | D5: the margin-recognition point. The pre-contract leg already used the ticket's planned payment terms, so only the price changes. |
| Survey outcome, rejection, demurrage provision | (f) | Events block |
| Buyer payment delay | (f), through `acc_overdue` only | Undiscounted MTM does not change when a dated receipt moves; only its funding does. |
| Cash–3M spread change | (g) | Moves `R` (3M-based), unfixed M+1 days, and MCX through cash parity |
| Forward-point roll-down, rate changes, weekends | (g) | Calendar-day carry and roll-down |
| Settlement of a flow on its own settle day | 0 | The estimate at `M_t, τ=t` equals the realised value from `H(t)`; the one-day tenor difference goes to (g). |
| Cross-terms (ΔLME × ΔFX, …) | the factor swapped later, i.e. (e) | CONTRACTS §7.4 |

### 6.3 Why hedges show no fake basis, with the real panel

Short 100 lots of MCX Aluminium, 07→08-Mar-2022 (LME DIRECT; USD/INR and MCX PROXY). Cash 3,984.5 → 3,500.5;
usdinr 76.9275 → 77.0510; `inr_rate_3m_pa` 3.7798%; days to the 31-Mar contract 24 → 23:

| Step | ₹ |
|---|---|
| (a) cash | **+20,202,398** |
| (b) basis | 0 |
| (c) grade, (d) freight, (f) events | 0 |
| (e) usdinr | **−234,570** (a short MCX is short USD: duty-paid parity rises in ₹ when INR weakens) |
| (g) rates and clock | **+15,118** |
| **Σ** | **+19,982,945** |

Against the panel prices directly the variation margin is +19,982,950; the ₹5 gap is the panel's 4-dp rounding,
eliminated by D4. Initial margin at `mcx_al_margin_used_frac` = 10% on 07-Mar is ₹16,631,500. The physical length
this hedges sees the same (a) through its own LME references, so a correctly sized hedge nets in (a) instead of
parking offsetting amounts in (a) and (b).

The mismatches that remain are real, and each shows in its own bucket: (c) the scrap factor versus primary metal,
(g) cash–3M and MCX carry versus the physical's forward estimate, (e) the duty base on the CBIC notified rate
versus MCX's market-rate uplift, and the `R` duty/insurance scaling (≈1.029) versus the primary uplift 1.0825.

A worked FX case, USD 1,000,000 payable due 15-Apr-2022 hedged with a forward booked 07-Mar at K = 77.3060
(including the ₹0.10 bank margin): `new_deal` −₹100,000 on the forward; (e) −₹123,947 on the payable and
+₹123,947 on the forward; (g) +₹5,534 and −₹5,534. The hedge nets to zero in (e) and (g) — the hedge-perfect
property asserted in §10.

### 6.4 Residual as a control

Telescoping gives `Σ_{k=1..8} (V_k − V_{k−1}) + acc_overdue(t) + acc_carry(t) = Π_t − Π_{t⁻}`. The reported total
is computed **independently**: `total_t = Δ[realised_pnl_cash + funding_accrued + Σ_legs mtm]`, where the mtm terms
come from pure states and the realised amounts from a cash ledger built day by day. `residual = total_t − Σ buckets`.

The two paths agree only if `Π` has no hidden inputs: a parameter read at a date other than the clock or the state
date, history read beyond the clock, contract or event logic touching the wall calendar, or a realised amount
computed with a rate the estimate does not converge to at settlement. Any of those makes `V0(t) ≠ V8(t⁻)` and shows
up as a non-zero residual. `|residual| ≤ ₹1` per trade-day is therefore a genuine sign-off control, and §10 plants a
bug to prove it. Float64 error at ₹10⁸ magnitudes is ~1e-8; rounding happens only when CSVs are written.

---

## 7. Exposures and the Phase 4 API

Central bump-and-revalue of the same `Π`, with clock, contracts and events held at `t`. Legs are linear or bilinear
in the factors, so central differences are exact up to float error. Bump sizes are named constants:
`BUMP_LME_CASH_USD_T = 1.0`, `BUMP_USDINR = 0.01`, `BUMP_FREIGHT_USD_T = 1.0`, `BUMP_GRADE_FACTOR = 0.001`,
`BUMP_SPREAD_USD_T = 1.0`, `BUMP_MCX_BASIS_INR_KG = 1.0`, `BUMP_RATE_PA = 0.0001`.

`book_exposures_daily.csv` — one row per date × scope (`trade_id`, plus `BOOK` rows):

```
date, scope, trade_id, in_window, buyer_id, supplier_id
mtm_inr, cum_pnl_inr, cash_balance_inr, mcx_im_inr
lme_delta_inr_per_usd_t, lme_delta_mt, lme_delta_usd, lme_delta_physical_mt, lme_delta_mcx_mt, hedge_ratio_lme_frac
mcx_lots_open, mcx_basis_delta_inr_per_inr_kg
fx_delta_usd, fx_delta_physical_usd, fx_delta_forwards_usd, fx_delta_mcx_usd, hedge_ratio_fx_frac, customs_fx_delta_usd
freight_delta_inr_per_usd_t_jea_nsa, freight_delta_inr_per_usd_t_usec_mun, freight_open_mt_<lane>, freight_open_boxes
grade_delta_inr_per_0p01_<grade>, grade_exposure_mt_<grade>
spread_delta_inr_per_usd_t, inr_rate_delta_inr_per_bp, usd_rate_delta_inr_per_bp, wc_rate_delta_inr_per_bp
lme_fx_cross_inr
phys_purchased_mt, phys_sold_mt, unsold_mt, purchase_priced_frac, sale_priced_frac
buyer_receivable_inr, buyer_presettlement_inr, supplier_exposure_inr, days_past_due
```

Signs: `+ lme_delta_mt` = long metal (gains if LME rises); `+ fx_delta_usd` = long USD (gains if INR weakens);
`+ freight_open_boxes` on an unfixed FOB cargo means the desk is short freight. One MCX lot is
`lot_mt × uplift × (1 + r × dte/365)` ≈ **5.44 MT of LME-equivalent metal**, which is why hedge sizing is done in
LME-equivalent tonnes rather than in physical tonnes.

**Hedge sizing helper** (P2, using only data dated ≤ the decision date): `lots = round(hedge_ratio × Δ_LME_eq /
lot_lme_eq)`. Because a short MCX lot is also short ≈ `lot_mt × uplift × cash` USD (≈ USD 13k per lot at
$2,400/t), the FX forward notional is measured **after** the MCX tranches are booked — the exposure table does that
arithmetic.

**Monte Carlo and scenarios** (P4 imports this; it never re-implements pricing):

```python
def revalue_book(book, H, t, shocks=None, extra_events=(), mcx_hold_basis=True) -> np.ndarray:
    """Instantaneous full revaluation at clock t (contracts and events as of t); shape (n_trades, n_paths).
    shocks: 'lme_cash_logret', 'usdinr_logret', 'freight_logret' or 'freight_<lane>_logret',
            optional 'lme_spread_abs', 'grade_factor_abs', 'mcx_basis_abs'.
    MCX is recomputed from the shocked cash and FX with the basis held, so hedges move consistently.
    The clock is held: a one-day carry is deterministic, and advancing it would need H beyond t (look-ahead)."""
```

The five Table 6 row 4.2 stresses map onto the same API: LME −15% (`cash × 0.85`), INR −5% (`usdinr ÷ 0.95`,
documented choice), freight +40% (`× (1 + freight_stress_shock_frac)`), buyer default (`StressEvent
buyer_default{buyer_id, recovery_frac}` writing off the receivable and pre-settlement value) and BIS-QCO +
demurrage (`qco_hold{qco_stress_delay_days, qco_stress_rejection_frac, qco_stress_rejected_loss_frac}`). Stress
event types are accepted **only** through this API and never read from `trades.yaml`.

**Honest note for P4, to be printed next to the freight overlay.** Once freight is fixed, the book's freight
sensitivity is small by design (D12): a +40% shock hits unfixed FOB freight and the forward pipeline, not cargo
already fixed. P4 must say so rather than let the reader infer a bigger number than the book carries.

---

## 8. Adverse events (Table 5 rows 3.4–3.6)

Windows are **reporting** windows, derived mechanically from real data in `desk/mtm/events.py`, written to
`adverse_event_windows.csv`, and never inputs to a trading decision. A regression test pins the dates below.

| Event | Rule | Current panel |
|---|---|---|
| **E1 LME crash** | start = argmax `lme_cash_usd_t` in the window; end = argmin on [start, WINDOW_END] | 2022-03-07 ($3,984.5) → 2022-07-15 ($2,320.5), **−41.8%** |
| **E1 crash fortnight** | the **10-trading-day return window** (11 observations, `CRASH_FORTNIGHT_RETURN_DAYS = 10`) with the most negative cash return | 2022-04-22 ($3,244.0) → 2022-05-09 ($2,708.0), **−16.5%** |
| **E2 INR depreciation** | the pair i < j in the window maximising `usdinr_j / usdinr_i` | 2022-04-05 (75.3350) → 2022-07-14 (80.0352), **+6.24%**; memo first-to-last **+5.07%** |
| **E3 logistics + credit** | start = the earliest `known_date` of an E3-tagged event; end = the last affected settle date | per book; the cited void-call trigger is 2022-07-27 |

> **Off-by-one warning, pinned here because both proposals hit it.** "10 panel days" must mean 10 *returns*, i.e.
> `c[i+10]/c[i]`. The 10-*observation* reading (9 returns) selects 2022-03-07 → 2022-03-18, −15.2% instead. Both
> windows are defensible; the contract is the 10-return one, and the March window is reported as a memo.

**Method.** Isolated impact = the sum of the relevant buckets over the window from `attribution_leg_daily.csv`,
split by leg group, **plus** counterfactual re-runs of the same book with one component removed:
`without(instruments={"mcx"})`, `without(instruments={"fx_forward"})`,
`without(events={"logistics_delay","buyer_payment_delay"})`, `with_fixtures_at_bl()` (the freight-timing decision),
`without(mitigation)`. Hedge benefit = window P&L(book) − window P&L(counterfactual), which includes the VM/IM
funding difference.

- **E1:** Σ(a) split physical / MCX, with (c) alongside (scrap stickiness offsets part of the fall —
  `grade_falling_market_logic`), (b) and (g) reported beside them. `hedge_offset_frac = −Σ(a)_mcx / Σ(a)_physical`.
  The **MCX variation-margin schedule** runs from WINDOW_START, because an importer's *short* pays margin in the
  01–07 March spike and receives it in the crash — the cash strain is on the way up, and the report must say so.
  Peak cumulative outflow and its date, max IM, crash-fortnight VM, and IM stressed at 0.12 and 0.15 (the
  `mcx_al_margin_used_frac` note) as memo columns. Header reality check: on 08-Mar-2022 the proxy near-month moved
  −12.0% in a day, beyond the 9% maximum slab — a real MCX would have been limit-locked (`mcx_al_dpl_*`).
- **E2:** Σ(e) by leg class — physical USD legs, forwards (the **forward-book offset**), MCX legs (a short MCX
  loses when INR weakens), customs duty base. `forward_offset_frac = −Σ(e)_forwards / Σ(e)_physical`; forward cost
  memo = Σ(`new_deal` bank margin + (g) on the forward legs); daily USD position from the exposures table.
- **E3, framed honestly** (CONTRACTS §7.6). Freight **fell** through the window — JEA_NSA −35.6% and USEC_MUN
  −35.6% from 01-Mar to 31-Aug-2022 — so there was no 2022 freight spike. The three real components are: (i) a
  simulated buyer payment delay → Σ(f) overdue funding, DPD, exposure vs `credit_limit_inr`, breach days and the
  mitigation counterfactual; (ii) the **real, dated** July-2022 void calls at Nhava Sheva / Mundra (Container News,
  27-Jul-2022, `docs/research/freight_notes.md` S4) with simulated dwell → Σ(f) demurrage plus (g) carry on the
  later receipt; (iii) the real cost of fixtures locked above a falling market, as the `with_fixtures_at_bl()`
  counterfactual and the `fixture_vs_market_inr` memo. Any freight **spike** is a separate file,
  `adverse_event_3_freight_stress_hypothetical.csv`, every row labelled `HYPOTHETICAL STRESS — not a 2022 event`.
  The `fixture_vs_market_inr` memo is a *competitiveness* cost against later importers, not a loss on the cargo,
  because §5's CFR grade factor does not fall when freight falls.

---

## 9. Outputs and module layout

### 9.1 Tables (`outputs/tables/`)

| File | Grain | Notes |
|---|---|---|
| `trade_book.csv` (P2) | trade | Ticket terms, every derived date, `trade_eligible` and the three §5a net-arb columns, `replacement_inr_t_at_trade_date`, `netback_inr_t_at_sale`, `day_one_value_inr`, `p1_finance_memo_inr`, `p3_funding_inr`, `close_date`, `rationale`. |
| `trade_hedges.csv` (P2) | hedge line | MCX tranches and forwards with every derived number beside the typed decision: `entry_price_inr_kg`, `exit_price_inr_kg`, `roll_deadline`, `forward_mid_inr`, `bank_margin_inr`, `rate_inr`, `index_usd_box_at_fixture`, `fixture_vs_index_frac`, `hedge_ratio_actual`, `sizing_basis`, `decision_date`, `basis_risk_note`. |
| `trade_cashflows.csv` (P2 writes, P3 reconciles) | trade × leg × cashflow | `leg_type, cf_type, pnl_class, currency, contract_date, fixing_date, due_date_contractual, settle_date, amount_ccy, fx_rate_used, fx_rule, amount_inr, amount_inr_est_at_trade_date, date_rule, weakest_input_flag, event_ids, formula`. Two scenarios: `PLANNED_AT_TRADE_DATE` and `REALISED`. |
| `mtm_daily.csv` (P3) | date × trade × leg | `status` ∈ floating / partially_fixed / fixed_unsettled / settled, `fixed_frac`, `mtm_fixed_inr`, `mtm_floating_inr`, `realised_cum_inr`, `leg_cum_pnl_inr`, `leg_daily_pnl_inr`, `fixture_vs_market_inr`, `weakest_input_flag`. Funding is a leg with `mtm = 0`. |
| `attribution_daily.csv` (P3) | date × trade (+`BOOK`) | Exactly `desk.reporting.style.PNL_BUCKETS`, plus `residual`, `daily_pnl_inr`, `cum_pnl_inr`, `in_window`. |
| `attribution_leg_daily.csv` (P3) | date × trade × leg | Same buckets; Σ legs = the trade row exactly. Needed for hedge effectiveness and the forward-book offset. |
| `book_exposures_daily.csv` (P3) | date × scope | §7. |
| `mcx_variation_margin.csv` (P3) | date × hedge line | `action` ∈ entry/hold/roll_out/roll_in/exit, settles, VM, cumulative VM, IM required and returned, IM stressed at 0.12/0.15, net and cumulative margin cash, funding on margin. |
| `adverse_event_windows.csv`, `adverse_event_1_lme_crash{,_daily}.csv`, `adverse_event_2_usdinr{,_daily}.csv`, `adverse_event_3_logistics_credit.csv`, `adverse_event_3_freight_stress_hypothetical.csv` | §8 | |
| `pnl_controls.csv` (P3) | date × check | `residual_max_abs`, `ledger_identity_max_abs`, `proxy_basis_max_abs`, `bs_flows_lifetime_sum`, `replacement_vs_p1_max_abs`, `cashflow_reconciliation_vs_p2`, each with value, tolerance and status. `desk.mtm.run.main()` raises if any control fails. |

Sensitivity runs write `*_mcx_mirror.csv` (CONTRACTS §7.5) and `*_grade_pit.csv` (D13) variants of
`attribution_daily`, `book_exposures_daily` and `adverse_event_1_*`. Their docs state they are never base P&L.

### 9.2 Modules

The shared, pure library lives **inside `desk/book/`** rather than in a new top-level package, so CONTRACTS §2
needs no amendment and ownership stays with P2:

```
desk/book/            constants.py   named model-structure constants (§2)
                      schema.py      tickets, counterparties, load_*, validate_*        [WRITTEN]
                      calendar.py    roll_following, roll_bd, panel_days_in_month, mcx_roll_deadline(month),
                                     mcx_slot(month), m1_month_on(day)
                      history.py     MarketHistory (PIT-guarded, ParamProvider, mcx_source adapters), state_at
                      state.py       MarketState, BLOCKS = {factor: fields}, swap(a, b, block)
                      curves.py      cash_fwd, cash_at, lme_avg, fx_x, mcx_theo, mcx_price, mcx_avg, box_mkt,
                                     replacement_value
                      schedule.py    expand(ticket, C, E, H) -> list[FlowSpec]           (§4.3)
                      legs.py        value_flow / realised_flow / mcx / fx / swap line values
                      valuation.py   trade_value, book_value, revalue_book, funding_path
                      exposures.py   bump deltas (§7)
                      validate.py    panel- and parity-dependent rules (§3.2, deferred list)
                      run.py         main(): trade_book.csv, trade_hedges.csv, trade_cashflows.csv
desk/mtm/             attribution.py attribute_day(ticket, t_prev, t, H) -> per-leg buckets (§6.1)
                      ledger.py      realised cash ledger, VM/IM ledger, funding split, reconciliation vs P2
                      events.py      window rules, counterfactual books, event tables (§8)
                      charts.py      equity curve + per-trade waterfalls via desk.reporting.style.save_fig
                      run.py         main(): every P3 table + pnl_controls.csv; raises if a control fails
```

Stages still talk through files (CONTRACTS §1.7); `desk.mtm` and `desk.risk` import the formulas from `desk.book`
so they exist exactly once. Every leg formula in §4.3 is closed form (funding is a running sum), which is what lets
the Component 1–3 Excel workbook reproduce one trade's daily MTM and its eight attribution columns.

---

## 10. Tests

`tests/test_book_schema.py` is written and green (63 tests): the fixtures load and validate clean against the real
panel, all three trade dates pass `eligible_on`, every ticket settles inside `HORIZON_END`, the coverage matrix
holds, and a 40-row mutation table asserts each rule V01–V20 catches its own break with a precise message.

Still to write for P2/P3, on a `tests/fixtures/synthetic_market.py` frame built on the real LME calendar with
controllable constant paths (cash 2,500, spread −10, usdinr 78, customs 79, rates 5%/2%, freight 20/80, factor
0.80, wc 10%) plus injectable single-block shocks:

1. **Curves:** `cash_fwd` at w = 0, ½, 1 and beyond 3M; `lme_avg` with k of N days fixed; `F_theo` replicates the
   real panel M1/M2 within `MCX_PROXY_REPLICATION_TOL` on every 2022 day; `fx_x` equals the panel `usdinr_fwd_3m`;
   `R` equals the §5.3 components by hand.
2. **Schedule:** every §4.1 date for the three fixtures, including the following-roll over the 02/03-Jun and 29-Aug
   LME holidays, the usance maturity, the one-month laycan rule, the roll deadline on the DIRECT 30-Aug expiry.
3. **Telescoping (property):** 200 seeded (ticket × day × perturbed state) cases — Σ buckets == ΔΠ within 1e-6 ₹,
   and `V0(t) == V8(t⁻)` within 1e-6 ₹.
4. **Ledger identity (property):** `Π == realised + funding + Σ mtm` every day, every fixture.
5. **Residual control on the real panel**, plus a **planted hidden-input bug** (a parameter read at the settle date
   instead of the clock) that the ₹1 residual must catch. This test is the point of D9.
6. **Single-block isolation:** with the clock held, moving one block moves only its bucket.
7. **Hedge-perfect FX:** a fixed-USD purchase plus a 100% forward on the same date and notional ⇒ Σ(e) = Σ(g) = 0
   every day; lifetime INR cost = notional × K.
8. **Hedge-perfect metal:** constants and `customs = usdinr`; an unsold fixed-price cargo plus an MCX short sized
   to `−lme_delta_physical_mt / lot_lme_eq` ⇒ Σ(a) = 0.
9. **Proxy basis:** `cross_exchange_basis ≡ 0` for every trade-day of a base run on the real panel.
10. **Zero-move day:** `M_t = M_{t⁻}`, no events, no bookings ⇒ (a)–(f) and `new_deal` are 0; (g) is carry and
    roll-down only.
11. **Terminal:** at `HORIZON_END` every leg is settled, Σ mtm = 0, lifetime Σ of BS flows = 0 per trade, cum P&L =
    Σ P&L flows + funding, and Σ VM per line = `lots × lot_kg × (F_exit − F_entry)`.
12. **Cross-phase:** P3's realised ledger == `trade_cashflows.csv` to ₹0.01; re-derived strikes, entry/exit prices
    and the fixture index == `trade_hedges.csv`; `R` == Phase 1 components on parity week-ends.
13. **No look-ahead:** `MarketHistory` truncated at `t` gives an identical `Π` and identical exposures at `t`, and
    the PIT guard raises when an accessor asks for a date beyond the clock.
14. **Linearity:** doubling tonnage, lots and notionals doubles every bucket.
15. **Counterfactual consistency:** `Π(book) − Π(book.without({"fx_forward"}))` == Σ forward-leg Π + the funding
    difference.
16. **Determinism:** run P2 and P3 twice; assert sha256 equality of every output CSV.
17. **Event windows:** the §8 rules return 2022-03-07/2022-07-15, 2022-04-22/2022-05-09 and 2022-04-05/2022-07-14
    on the current panel, and the 10-return convention is asserted explicitly.

---

## 11. Edge cases, simplifications, and what not to model

**Handled.** Non-panel dates roll following, independently per milestone (dwell in calendar days). An M+1 laycan
crossing two months is a validation error. Fixings beyond 3M use flat extrapolation. An MCX-average sale months
ahead prices off the furthest listed contract's theo plus that contract's basis. The panel's 31-Aug slot and the
DIRECT 30-Aug expiry are two views of contract month `2022-08` (D4b). A negative M+1 final invoice is a supplier
refund and counts in `supplier_exposure_inr`. Rejected boxes leave duty, port and the sale, and their demurrage is
not the desk's. If a delay moves the date a forward was matched to, the forward still settles at its maturity and
the mismatch shows in (e)/(g), with `matched_leg_date_moved` flagged. A cancelled forward settles on the cancel
date at `N × (X(cancel, T) − K)`. A positive cash balance (advance sale) earns the WC rate. A mirror gap beyond
`MAX_FILL_BDAYS` raises rather than fills. Selling after the planned release is a warning in the schema and an
error in P2 against rolled dates. No accrual after `close_date`.

**Simplifications, and why they are acceptable.** (1) Undiscounted with flat 3M rates at every FX tenor — the
horizon is ≤ 8 months and CONTRACTS §7.3 already rules it. (2) Linear cash→3M interpolation for M+1 estimates —
only cash and 3M are DIRECT; the error is a small (g) timing effect that vanishes as days fix. (3) The
replacement-value mark is a policy choice, and the conservative one. (4) Duty on the provisional value with no
customs final assessment — the error is ~2.75% of (final − provisional). (5) Survey before the Bill of Entry, so
rejected boxes stay cleanly out of duty; in practice examination follows the BoE and rejected cargo needs
re-export with drawback. (6) A symmetric funding rate on one WC line, which makes trade-level funding additive.
(7) MCX settles at the proxy close: no SPAN, no daily price-limit locks, no MCX-vs-LME close-time gap; the mirror
sensitivity carries the order of magnitude (`mcx_basis_std_inr_kg` 4.44). (8) Deterministic events from YAML;
probabilistic default belongs to P4/P5. (9) One blended demurrage rate with no slab escalation; detention and
ground rent combined. (10) Laycan inside one calendar month and no B/L slippage outside it. (11) No quantity
tolerance on the B/L weight. (12) Grade-factor marks use the register's lag-2 reconstruction, with the PIT variant
run in parallel (D13). (13) MCX runs on the LME calendar (CONTRACTS §3), so margin flows bunch around UK holidays.

**Do not model.** LME futures, TAPOs or MASP hedges — the desk has no LME membership, and RBI's direction on
hedging commodity price risk overseas only came into force on 12-Dec-2022 (`regulatory_contract_notes` §6); keep
it as an interview talking point. Options. Discounting of MTM. Bulk parcels, charter parties and laytime. Partial
shipments across months. Warehouse inventory after arrival. Output GST, TDS/TCS, stamp duty, profit tax. ECL/CVA
provisions in base P&L. MCX physical delivery and the tender period (positions roll 7 days before). Insurance
claims. Stochastic operations inside the base book. Buyer default in the base book (it is a P4 stress). Hedge
accounting. Intraday prices. Price prediction of any kind. Real counterparty, vessel, carrier or bank names.

---

## 12. What this does and doesn't tell you

**MTM and attribution — does.** For each simulated trade it turns the ticket into a dated, rupee-reconciled ledger
and a daily mark that respects how an Indian scrap import desk actually pays and gets paid: LC timing, M+1
averaging, provisional and final invoices, out-turn claims, Bill of Entry duty and the IGST credit lag, demurrage,
buyer credit, and the cost of financing all of it. It splits every day's P&L into LME level, LME–MCX basis, scrap
grade spread, freight, USD/INR, operational penalties and carry, with no unexplained residual, and it produces
hedge effectiveness and forward-book offsets from the same numbers the risk pack consumes.

**Doesn't.** It is not evidence of what a 2022 desk earned. Trades, counterparties and every operational outcome
are simulated. MCX is a duty-parity proxy, so in base runs the LME–MCX basis bucket is empty *by construction* —
the real basis appears only in the third-party mirror sensitivity. Scrap grade marks rest on a lag-2 unit-value
ratio published months after the fact, and freight levels are hindsight-calibrated reconstructions, so buckets (c)
and (d) are reconstructions, not observed market moves. Forward curves are linear and flat approximations. A zero
residual proves the arithmetic is closed, not that the model is right, and the split between factors depends on the
documented swap order: cross-effects sit in the factor that moves later.

**Exposures.** These are first-order sensitivities of the same valuation — LME-equivalent tonnes, USD, open
freight boxes — and they are exact for this model's linear legs. They are not a forecast of how scrap discounts,
domestic premiums or MCX basis behave under stress; those are held fixed unless a scenario shocks them.

**Adverse events.** The windows are drawn after the fact from real LME and FX data to *report* what the book went
through; they were never inputs to a trade. Isolated impacts combine bucket sums over the window with re-runs of
the same book without the hedges or without the simulated delays. They describe this simulated book's behaviour,
not a realised 2022 loss. Event #3's delays and payment slippage are simulated and anchored to a real, dated July
2022 port disruption, and any freight spike is labelled a hypothetical stress because freight fell in 2022.

---

## 13. Provenance of position-model inputs

| Input | Flag | Where it bites |
|---|---|---|
| LME official cash and 3M (Westmetall) | DIRECT | fixings, curve, MCX parity, M+1 averages |
| CBIC notified customs rate path; BCD / SWS / IGST rates; MCX contract specs and expiries; SBI LC fee card; MSMED 45-day cap; client position limit; FX no-documentation limit | DIRECT | duty base, flows, validation |
| USD/INR (ECB cross); INR and USD 3M rates; CIP forwards; the USD rate used as the usance benchmark | PROXY | all FX, forwards, MCX parity, usance interest |
| MCX panel series (import-parity proxy) | PROXY | hedges, MCX-linked sales; factor (b) ≡ 0 by construction |
| MCX third-party mirror | PROXY | basis sensitivity only, never base P&L |
| Grade factors (lag-2 mix + differentials) | ASSUMPTION (hindsight) | contract factors, replacement mark, factor (c) |
| Freight levels / shape | ASSUMPTION / PROXY | unbooked FOB freight, factor (d), fixture memo |
| Payloads, transit and clearance days, free days, demurrage rate, port charges, PSIC cost, WC rate path, usance spread, confirmation fee, margin used | ASSUMPTION / PROXY | dates, flows, funding, margin |
| Proposed `config/params/book.yaml` keys (§14) | ASSUMPTION (three PENDING verification) | dates and costs |
| Counterparties, trades, survey outcomes, delay magnitudes, payment slippage | SIM | factor (f), event #3, P5 features |
| July-2022 void calls at Nhava Sheva / Mundra, 27-Jul-2022 | DIRECT (Container News via `freight_notes.md` S4) | event #3 start and the earliest permissible `known_date` |

---

## 14. New parameter keys — `config/params/book.yaml` (P2 creates and owns it; no Phase 0 file changes)

| Key | Value | Unit | Flag | Justification | Verify |
|---|---|---|---|---|---|
| `lc_sight_payment_lag_days` | 7 | days after B/L | ASSUMPTION | the document-presentation and payment timeline in the `finance_days_jea_nsa` note ("supplier paid ~day 7") | N/A |
| `lc_presentation_period_days` | 21 | days after shipment | ASSUMPTION | UCP 600 Art. 14(c) default presentation period; sets LC validity for the opening fee | **PENDING** — read the ICC UCP 600 text |
| `lc_amount_tolerance_frac` | 0.10 | frac | ASSUMPTION | the "about" tolerance used to size the LC value | **PENDING** — UCP 600 Art. 30 |
| `survey_lag_days` | 1 | days after arrival | ASSUMPTION | joint survey at the CFS before the BoE is filed (simplification §11) | N/A |
| `boe_lag_days` | 1 | days after arrival | ASSUMPTION | the `igst_credit_lag_days` note puts the BoE ~1 day after arrival | N/A |
| `provisional_invoice_frac` | 0.95 | frac | ASSUMPTION | 90–100% provisional payment is common on LME-linked scrap SPAs; P5 shows 0.90–1.00 as a sensitivity | N/A |
| `final_invoice_lag_bdays` | 5 | panel days after `pricing_end` | ASSUMPTION | the seller computes the M+1 average and invoices by T/T | N/A |
| `claim_settle_lag_days` | 30 | days after survey | ASSUMPTION | survey report, seller acceptance, credit note | N/A |
| `advance_days_before_delivery` | 2 | days | ASSUMPTION | advance received before truck release | N/A |
| `freight_booking_days_before_bl` | 10 | days | ASSUMPTION | NVOCC space-confirmation lead time; sets the default `latest_fixture_date` | N/A |
| `freight_stop_loss_frac` | 0.15 | frac | ASSUMPTION | the desk's freight-risk policy; the P5 memo may override it | N/A |
| `mcx_slippage_ticks` | 2 | ticks | ASSUMPTION | execution against the settle on a thin contract | N/A |
| `mcx_txn_cost_frac` | 0.0003 | frac of contract value | ASSUMPTION | one combined charge for brokerage, exchange transaction charges, GST on them and the Commodity Transaction Tax on the sell side. **Deliberately a single un-decomposed assumption:** neither the MCX charge circular nor the CTT rate was re-read for this phase, and stating a rate from memory would breach CONTRACTS §1.2 | **PENDING** — MCX transaction-charge circular and Finance Act 2013 Ch. VII |
| `buyer_margin_inr_t` | 6450 | ₹/t scrap | ASSUMPTION | the smelter's retained share of the netback; used only by the sale-terms helper that keeps sale prices inside [R, netback] | N/A |
| `overdue_interest_collected_frac` | 0.0 | frac | ASSUMPTION | penal interest on late foundry payments is rarely collected, so the delay is a pure funding cost | N/A |

**Existing keys reused, never duplicated:** every CONTRACTS §5 key; `spa_moisture_deduction_ratio`,
`spa_contamination_discount_multiple`, `spa_contamination_rejection_excess_frac`, `lme_cash_prompt_bdays`,
`mplus1_bl_month_offset_months`, `parity_goods_fx_basis` (parity.yaml); the LC fee card, `usance_interest_spread_pa`,
`domestic_buyer_credit_days`, `msme_max_payment_days`, `conversion_cost_inr_t`, `domestic_anchor_premium_inr_t`
(commercial.yaml); the MCX and FX-hedge block (exchange.yaml); `detention_free_days`, `demurrage_usd_per_box_day`,
`transit_days_*`, `clearance_delivery_days`, `typical_laycan_days`, the payload family, `port_cf_charges_inr_t_*`,
`insurance_rate`, `insured_value_uplift`, `freight_stress_shock_frac` (logistics.yaml); the duty, IGST, PSIC and QCO
block (regulatory.yaml); `wc_rate_inr_pa` (rates.yaml).

`fx_forward_bank_margin_inr` is defined for forwards; this design also applies it to spot TT conversions of
physical USD flows (see §15.2).

---

## 15. Open issues, Phase 0 findings and calls made

### 15.1 Calls the synthesiser made that a reader may want to challenge

1. **Contract grade factors come from the base path, not the PIT mix** (D13). The alternative books a day-one loss
   up to −0.12 × LME × quantity in March 2022 that is an artefact of two reconstructions, not a trading result.
   §5a already puts the PIT screen where it belongs, on selection.
2. **Freight does not pass through into the CFR cargo mark** (D12). Consequence: a fixed-freight book shows little
   freight risk, and §7 requires P4 to say so beside the +40% stress rather than let the number mislead. If a
   pass-through is ever wanted, add `freight_passthrough_to_cfr_frac` (ASSUMPTION, default 0) as a P4 sensitivity
   only, with an explicit reference-freight definition.
3. **Sale prices are set inside [replacement value, smelter netback]** at the sale date, on information dated on or
   before it, with both bounds written into `trade_book.csv`. Otherwise `new_deal` at the sale is uninterpretable.
   All three example tickets do this and record the arithmetic in `terms_basis_note`.
4. **Roll costs go to (g), not to `new_deal`** (D8c). The bucket is named "roll yield / term structure" in Table 5
   row 3.2(g), so the roll's execution cost belongs there; its carry convergence is already booked daily in (g).
5. **`provisional_invoice_frac = 0.95` and `final_invoice_lag_bdays = 5`** noticeably change supplier refund
   exposure in the crash months. P5 should run them as a sensitivity.
6. **The hypothetical freight swap is barred from the base book.** Table 4 row 2.7(d) offers "proxy instrument or
   stop-loss"; no accessible India-lane container derivative existed, so the base book takes the stop-loss and the
   swap survives only as a labelled stress instrument.

### 15.2 Phase 0 findings to report (nothing in Phase 0 was changed)

1. **`customs_usdinr_import` ends 2022-09-16 and clamps after it.** A Bill of Entry after the next unrecorded CBIC
   notification (early October 2022) would use a stale rate. Either extend the path to 2022-10-31, or P2 keeps
   every BoE date on or before 2022-10-06. All three example tickets clear customs well before that.
2. **MCX expiry mismatch.** The panel's contract calendar uses a last-calendar-day rule, so the August-2022 slot is
   31-Aug while the DIRECT `mcx_al_expiry_dates_2022` says 30-Aug — the proxy prices an expired contract for one
   day. This design sidesteps it by keying positions on the contract **month** (D4b): prices from the panel slot,
   roll deadlines from the DIRECT list. Suggest Phase 0 adopt the DIRECT list in `desk.data.mcx.contract_calendar`.
3. **`finance_days_jea_nsa`'s note puts the Bill of Entry at arrival + 3**, while `igst_credit_lag_days` and the
   USEC note put it at arrival + 1. This design uses `boe_lag_days = 1`. Harmonise the note.
4. **`usance_interest_spread_pa` is quoted over a 6-month benchmark**, but only the US 13-week bill
   (`usd_rate_3m_pa`) exists in the panel. It is used as a PROXY benchmark; the tenor mismatch is a few basis
   points and is recorded here rather than silently absorbed.
5. **`lc_opening_fee_frac` (PROXY, 3-month validity) duplicates `lc_opening_fee_frac_per_month` (DIRECT).** This
   design uses the per-month key × actual validity months; the PROXY key should be marked memo-only.
6. **CONTRACTS §5's landed cost omits trade-finance charges** — LC issuance, confirmation, usance commission and
   interest, bill commission: roughly 0.3–0.6% of cargo value, about ₹700–1,400/t — and the
   `margin_threshold_inr_t` note does not list them. The §4.4 diagnostic in `trade_book.csv` surfaces this gap
   explicitly rather than hiding it.
7. **The MCX proxy ignores daily price limits.** The near-month proxy moved −12.0% on 08-Mar-2022 against a 9% maximum slab
   (`mcx_al_dpl_max_frac`); a real position would have been limit-locked. P2's validator warns on entry and exit
   days beyond the slab, and the E1 margin table prints the caveat.
8. **No `lc_presentation_period_days` exists** in the register (UCP 600 Art. 14(c), 21 days); added in `book.yaml`
   with verify PENDING (§14).

### 15.3 CONTRACTS changes this design needs

Only one, and it is additive: a new **§7a "Trade ticket & engine interface"** summarising the ticket schema, the
Phase 3 output tables and the `book_exposures_daily.csv` columns, and recording the four §7 clarifications —
`new_deal` computed last and reported first, the (f)/(g) funding split, the replacement-value mark, and USD flows
valued at the CIP forward. No other section changes: the shared library lives inside `desk/book/` (§9.2), and
`config/params/book.yaml` is a P2-owned file consistent with §2's one-owner-per-file rule.
