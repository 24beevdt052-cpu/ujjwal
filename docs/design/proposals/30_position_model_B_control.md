# 30 — Position & valuation model — Proposal B (product-control angle)

ACADEMIC SIMULATION — not actual trades. All counterparties, vessels and events named here are fictional (SIM).

Status: design proposal for the synthesizer. No code, no data files. It is written to be implemented by one engineer
without guessing, and it is built on CONTRACTS §1–§7, `MASTER_SPEC_V3` Tables 4–6 and the Phase 0 register as it
stands today. Section 11 lists the contract amendments this design needs.

Angle: a product controller signs off daily P&L. So the design starts from the P&L identity and works back to the
trade ticket. The model has five parts: one explicit state vector, pure valuation functions, sequential
revaluation that adds up exactly, a clean realised/unrealised split, and exposures computed with the same functions
that value the book. The operational model is only as detailed as the P&L needs.

---

## 0. Key decisions at a glance

| # | Decision | Why |
|---|---|---|
| D1 | **One pure function** `Π(trade; C, E, M, τ)` = cumulative P&L of a trade given contracts-as-of `C`, events-as-of `E`, market state `M` and clock `τ`. MTM, daily P&L, attribution, exposures, counterfactuals and Monte Carlo all call it. | Only one code path can be wrong. Attribution sums to total by construction, and the residual becomes a real control: a non-zero residual means Π has hidden inputs, not rounding. |
| D2 | **State vector** grouped into the 7 factor blocks plus an events block and a contracts block. Attribution swaps the blocks in `FACTOR_ORDER`; **new_deal is swapped last** (it is still reported first). | New contracts are valued at the day's closing market, with no cross-terms. |
| D3 | LME is a curve: **flat = official cash** (parallel shift, block a), **term structure = cash − 3M spread** (block g). Future fixings for M+1 averages are linearly interpolated in calendar days between cash and 3M, and flat beyond 3M. | Physical SPAs and the MCX parity both settle on cash (exchange.yaml `lme_pricing_reference`), so cash is the flat-price factor P4's GARCH should fit. |
| D4 | **MCX = LME parity + basis.** `F = spot_theo(cash, usdinr) × (1 + r_inr × dte/365) + b`. The basis `b` is state block (b). On `PROXY_IMPORT_PARITY` days `b ≡ 0` (the panel's own formula is replicated to ≤ 1e-3 ₹/kg). | An LME move reaches MCX in step (a), FX in (e), carry and time in (g), and only the true residual in (b). Proxy runs show zero fake basis. |
| D5 | **Unsold cargo is marked at import replacement value** (§5 goods + BCD + SWS + port/PSIC at today's market, **excluding finance**), not at the MCX-anchored smelter netback. Sale margin is recognised in `new_deal` when the sale is contracted. | Conservative Level-3 policy. The domestic anchor premium is an unobservable ASSUMPTION that moves by ±₹50k/t across regimes, so no day-one P&L is booked on it. It also makes grade factor (c) a live factor for open inventory. |
| D6 | **All future USD flows valued at the CIP forward to their settle date** (spot once settled). FX forwards are marked the same way. | A 100% forward hedge is then exactly flat in (e) and (g). Forward points roll to (g). |
| D7 | **Funding** = daily realised accrual at `wc_rate_inr_pa` (ACT/365, symmetric) on each trade's **actual dated cash balance** (P&L flows + IGST + MCX initial and variation margin). No `finance_days_*`, `finance_inr_t` or `igst_finance_inr_t` enters P3. Overdue-receivable funding goes to (f); all other funding goes to (g). | Buyer credit, usance deferral, IGST lag and margin are each counted once, from dates. The §5 approximation is a parity-screen shortcut and is never a cashflow. |
| D8 | Every date rolls **following** to the panel (LME) calendar. Every time-pathed parameter is read at the **clock**, never at a future event date. | Removes weekend misattribution and hindsight in marks. A truncated-history test proves the second point (§8.4). |
| D9 | `trades.yaml` carries **explicit executed numbers** (lots, notionals, fixture rate, forward rate). Conditional rules (stop-loss, rolls) are resolved by P2 into dated actions, each with a `decision_date` whose inputs are dated on or before it. | Deterministic, auditable, no hindsight. P3 re-derives each number and asserts equality. |
| D10 | A shared pure library `desk/position/` (schema, calendar, state, curves, legs, valuation, exposures) is imported by P2 (`desk.book`), P3 (`desk.mtm`) and P4 (`desk.risk`). | Stages still talk through files, and the formulas exist once. Needs a CONTRACTS §2 amendment. |

---

## 1. Conventions and invariants

- **Sign.** Every amount is from the desk's point of view. `+` is a cash inflow or a gain, `−` is an outflow or a cost. Base
  currency is INR. USD amounts are memo only.
- **Clock.** `τ` is a panel (LME trading) day. `t⁻` is the previous panel day. Calendar-day intervals (weekends)
  enter only through day counts.
- **Undiscounted.** Per CONTRACTS §7.3, MTM of a leg = the INR value of its not-yet-settled cashflows, with no discounting.
- **Identity** (per trade, per day): `cum_pnl(τ) = realised_pnl_cash(≤τ) + funding_accrued(≤τ) + Σ_legs mtm(τ)` and
  `daily_pnl(τ) = cum_pnl(τ) − cum_pnl(τ⁻)`.
- **Balance-sheet flows** (IGST paid and credited, MCX initial margin posted and returned) move cash and funding but are
  **not P&L**. Their undiscounted sum over life is zero, and a test asserts this.
- **Point-in-time.** A decision or derived ticket number dated `d` uses `history.state_at(≤ d)` only. Marks at `τ` use
  panel rows ≤ τ and parameter paths evaluated at τ.
- **Determinism.** No randomness in P2/P3. CSVs are sorted by (date, trade_id, leg_id) and written with fixed float
  formats (INR/USD 2 dp, ₹/kg and USD/t 4 dp, rates and fractions 6 dp), so re-runs are byte-identical.
- **Named constants** (code, `desk/position/constants.py`): `RESIDUAL_TOL_INR = 1.0`,
  `MCX_PROXY_REPLICATION_TOL_INR_KG = 1e-3`, `LME_CURVE_EXTRAPOLATION = "flat_beyond_3m"`, bump sizes (§6),
  `MIN_DELTA_FOR_HEDGE_RATIO_MT = 1.0`, `FX_FORWARD_CANCEL_SETTLES_ON = "cancel_date"`.

---

## 2. Trade ticket and counterparty schemas

### 2.1 `config/trades.yaml`

The top level is `schema_version: 1` and `trades: [ ... ]`. Types: `date` = ISO date; `panel_date` = a date that must
be in the panel calendar (the loader raises otherwise). `R` = required, `O` = optional (default shown), `D` = derived
by the loader/P2 and written to `trade_book.csv` (it must NOT be typed in the YAML; the loader raises if it is).

#### 2.1.1 Header and discipline (Table 4 rows 2.1, 2.9)

| Field | Type / unit | Req | Allowed / rule |
|---|---|---|---|
| `trade_id` | str | R | `^T\d{2}$`, unique |
| `trade_date` | panel_date | R | Purchase SPA signature date. `WINDOW_START ≤ trade_date ≤ WINDOW_END`. |
| `grade` | enum | R | `zorba` \| `taint_tabor` \| `tense` |
| `lane` | enum | R | `JEA_NSA` \| `USEC_MUN`. Container box is derived: 20ft for JEA_NSA, 40ft for USEC_MUN. |
| `parity_ref.week_end` | date | R | Must equal the latest `parity_weekly.csv` week_end ≤ trade_date (§5a). The row (week_end, grade, lane) must have `trade_eligible = True`. |
| `rationale` | str ≤ 1,500 chars | R | One paragraph. It may cite only information published ≤ trade_date. |
| `rationale_refs` | list[str] | O `[]` | E.g. `parity_weekly.csv@2022-05-06`, `headlines_weekly.csv@2022-05-06#3`. The validator checks every date ≤ trade_date. |
| `quantity.contract_mt` | float, MT | R | 1,000 ≤ x ≤ 5,000 |
| `quantity.tolerance_frac` | float | O `0.0` | 0–0.10. Used only for LC value; loaded weight = contract_mt in base. |
| `quantity.payload_mt_per_box` | float | D | `container_payload_mt_<box>_<grade>` (logistics.yaml) |
| `quantity.boxes` | int | D | `ceil(contract_mt / payload_mt_per_box)` |

#### 2.1.2 Purchase / SPA (rows 2.2–2.4, 2.6)

| Field | Type / unit | Req | Allowed / rule |
|---|---|---|---|
| `purchase.supplier_id` | str | R | Exists in counterparties.yaml with `type: supplier`, and `lanes` contains `lane`. |
| `purchase.incoterm` | enum | R | `FOB` \| `CFR` |
| `purchase.freight_booked_by` / `purchase.freight_risk_bearer` | enum | D | FOB → `buyer` (the desk books freight and bears the freight-rate risk from contract to fixture). CFR → `seller` (freight is embedded in the price; the desk bears only arrival-delay consequences). |
| `purchase.spa.isri_grade_spec` | str | O | Default text from regulatory_contract_notes §7 for the grade |
| `purchase.spa.moisture_franchise_frac` | float | O | Default `standard_moisture_franchise_frac` |
| `purchase.spa.non_metallic_limit_frac` | float | O | Default: 0.05 zorba, 0.01 taint_tabor (oil and grease), 0.02 tense (ISRI limits, notes §7) |
| `purchase.spa.discount_multiplier` | float | O `1.5` | From `rejection_penalty_schedule` |
| `purchase.spa.rejection_threshold_pts` | float | O `3.0` | Above this excess, the quality event must be a rejection |
| `purchase.spa.radioactivity_clause_key` | str | O `radioactivity_clause` | Register key (text), not free text |
| `purchase.spa.penalty_schedule_key` | str | O `rejection_penalty_schedule` | Register key |
| `purchase.pricing.type` | enum | R | `fixed` \| `lme_m1_avg` |
| `purchase.pricing.price_usd_t` | float USD/t | R if fixed | On the incoterm basis (FOB or CFR) |
| `purchase.pricing.lme_reference` | enum | R if lme_m1_avg | `cash` only: LME official cash settlement (exchange.yaml `lme_m1_pricing_rule`) |
| `purchase.pricing.factor_frac` | float | R if lme_m1_avg | Grade factor on the incoterm basis, 0.40–1.00 |
| `purchase.pricing.premium_usd_t` | float USD/t | O `0.0` | Additive premium (signed) |
| `purchase.pricing.provisional_frac` | float | O `provisional_invoice_frac` | Share of provisional value paid under the LC |
| `purchase.pricing.pricing_month` / `pricing_start` / `pricing_end` / `pricing_days` | D | | Month after the B/L month. First/last panel day of that month; N panel days. |
| `purchase.laycan.start` / `.end` | date | R | `trade_date ≤ start ≤ end`, `end − start ≤ 31 d`. **For lme_m1_avg, start and end are in the same calendar month**, so the pricing month is known on the trade date. |
| `purchase.vessel` | str | R | Ends with `(SIM)`. For containers this is the mainline or feeder vessel/service name. |
| `purchase.bl_date` | panel_date | R | Planned (SIM) B/L date, `laycan.start ≤ bl_date ≤ laycan.end` |
| `purchase.payment.instrument` | enum | R | `lc_sight` \| `lc_usance` |
| `purchase.payment.usance_days` | int, days from B/L | R if usance | 60 ≤ x ≤ 90 |
| `purchase.payment.lc_open_date` | panel_date | R | `trade_date ≤ x ≤ laycan.start` |
| `purchase.payment.lc_confirmed` | bool | O | Default true for USEC_MUN, false for JEA_NSA (`lc_confirmation_fee_pa` note) |
| `purchase.payment.issuing_bank` | str | O | `(SIM)` |

#### 2.1.3 Freight layer (rows 2.3, 2.7d, 2.8)

This block is required for FOB and must be absent for CFR (the validator raises otherwise).

| Field | Type / unit | Req | Allowed / rule |
|---|---|---|---|
| `freight.fixture_date` | panel_date \| null | R | `trade_date ≤ x ≤ bl_date`. null means book at market on `bl_date` (spot booking at loading). |
| `freight.rate_usd_box` | float USD/box | R if fixture_date | Executed rate (incl. BAF, excl. THC) |
| `freight.carrier` | str | O | `(SIM)` |
| `freight.payment` | enum | O `collect_at_arrival` | or `prepaid_at_bl` |
| `freight.index_usd_box_at_fixture` | D | | `freight_<lane>_usd_t(fixture_date) × container_payload_mt_<box>` (base payload, panel) |
| `freight.fixture_vs_index_frac` | D | | `rate / index − 1`. This is the Table 4 row 2.8 "freight rate vs proxy index". |
| `freight.risk_layer.type` | enum | R | `unhedged_stop_loss` \| `proxy_swap` |
| `freight.risk_layer.stop_loss_usd_box` | float | R if unhedged_stop_loss | Rule: on the first panel day before fixture on which the index box rate is ≥ stop, P2 inserts a forced fixture on the **next** panel day at that day's index rate. The resolved action is written to `freight.stop_loss_resolution` (D). |
| `freight.risk_layer.swap` | map | R if proxy_swap | `{swap_id, boxes (int), strike_usd_box, start_date (panel), settle_date (panel ≤ bl_date)}`. The desk is long freight. The swap is **hypothetical** (no liquid India-lane container derivative is assumed), is labelled so in every output, and settles against the panel lane series. |

#### 2.1.4 Logistics dates (Table 5 needs). Planned, derived by rule, events can shift them.

The derived dates are `arrival_cal = bl_date + transit_days_<lane>`,
`survey_cal = arrival_cal + survey_lag_days`, `boe_cal = arrival_cal + boe_lag_days`,
`release_cal = arrival_cal + clearance_delivery_days (+ event extra dwell)`, and
`lc_pay_date = roll(bl_date + lc_sight_payment_lag_days)` for sight LCs,
or `acceptance_date = roll(bl_date + lc_sight_payment_lag_days)` with
`usance_maturity = roll(bl_date + usance_days)` for usance LCs.
Every `*_cal` date has a settlement twin `roll_following(*_cal)` on the panel calendar. Demurrage dwell uses the
calendar dates. The optional override `logistics.overrides: {arrival_cal, release_cal}` is allowed only with a
`rationale` and is still validated against events.

#### 2.1.5 Sale (Table 4 rows 2.5–2.6, Table 5 needs)

| Field | Type / unit | Req | Allowed / rule |
|---|---|---|---|
| `sale.buyer_id` | str | R | `type: buyer` |
| `sale.contract_date` | panel_date | R | `trade_date ≤ x ≤ planned delivery (release_settle)`. **Before it, the sale leg is valued at replacement value (D5).** |
| `sale.basis` | enum | O `delivered_buyer_works` | Port cost in replacement value covers haulage to the buyer (port_cf_charges note) |
| `sale.pricing.type` | enum | R | `fixed` \| `mcx_avg` |
| `sale.pricing.price_inr_t` | float ₹/t scrap, ex-GST | R if fixed | |
| `sale.pricing.mcx_contract` | enum | R if mcx_avg | `M1` (the M1 contract on each averaging day) |
| `sale.pricing.window_start` / `window_end` | panel_date | R if mcx_avg | `contract_date ≤ start ≤ end ≤ HORIZON_END` |
| `sale.pricing.factor_frac` | float | R if mcx_avg | Recovery / scrap-discount basis applied to MCX ₹/t, 0.40–1.00 |
| `sale.pricing.premium_inr_t` | float ₹/t | O `0` | Signed |
| `sale.quality_passthrough` | bool | O `true` | If true, the buyer pays accepted weight at the same % discount as the SPA (back-to-back quality) |
| `sale.payment.terms` | enum | R | `credit` \| `advance` \| `advance_plus_credit` |
| `sale.payment.credit_days` | int | R if credit or mixed | 1 ≤ x ≤ `msme_max_payment_days` (45, applied as desk policy cap) |
| `sale.payment.advance_frac` | float | R if advance or mixed | (0, 1]; exactly 1.0 for `advance` |
| `sale.payment.advance_date` | panel_date | R if advance or mixed | `contract_date ≤ x ≤ planned release_settle` |
| `sale.due_date` | D | | `roll(release_cal + credit_days)`, shifted by payment-delay events |
| `sale.credit_check` | D | | Buyer exposure + this sale ≤ `credit_limit_inr` at contract_date (information ≤ that date), else validation error unless `terms = advance` |

#### 2.1.6 Hedge stack (row 2.7 a–c)

```yaml
hedges:
  mcx:
    hedge_ratio_frac: 0.80        # R if lines present; intent, measured vs physical LME-cash delta (§6) on entry date
    basis_risk_note: >            # R: row 2.7c, e.g. primary-ingot futures vs scrap; MCX proxy = LME parity
    lines:                        # each line = one position in one contract
      - hedge_id: T01-MCX-1       # R, unique
        contract_expiry: 2022-05-31   # R, must equal panel mcx_m1_expiry or mcx_m2_expiry on entry_date
        lots: -241                # R, int, signed (− short), lot = mcx_al_lot_mt
        entry_date: 2022-05-12    # R, panel_date ≥ trade_date
        exit_date: 2022-05-20     # R, panel_date ≤ roll_date(contract_expiry)  (§3.4)
        exit_reason: roll         # R: roll | unwind | tranche
        roll_to: T01-MCX-2        # R if exit_reason = roll; target line entry_date == exit_date, same lots
        decision_date: 2022-05-12 # D = entry_date; sizing inputs ≤ this date
        sizing_basis: D           # text written by P2, e.g. "0.80 × 1,626 LME-eq MT / 5.40 LME-eq MT per lot"
  fx_forwards:
    hedge_frac: 1.0               # R if lines present; intent vs matched USD flow estimated on booking_date
    lines:
      - fwd_id: T01-FX-1          # R
        booking_date: 2022-05-12  # R, panel_date ≥ trade_date
        notional_usd: 4280000     # R, > 0 = desk buys USD (import hedge); < 0 allowed (sells USD, e.g. refund)
        maturity_date: 2022-06-17 # R, panel_date; must equal settle_date of matched_leg at booking (warn if later moved)
        matched_leg: purchase_invoice   # R: purchase_invoice|purchase_provisional|purchase_final|freight|usance_interest|demurrage
        cancel_date: null         # O, panel_date in (booking_date, maturity_date)
        forward_mid_inr: D        # X(M_booking, booking_date, maturity) via desk.units.fx_forward
        bank_margin_inr: D        # fx_forward_bank_margin_inr (sign: + when buying USD)
        rate_inr: D               # K = forward_mid + sign(notional) × bank_margin
```

#### 2.1.7 Events (Table 5 rows 3.4–3.6 inputs). Every event is SIM unless its trigger is a cited real fact.

```yaml
events:
  quality:                        # O; absent ⇒ nominal quality (no deductions)
    known_date: D                 # = roll(survey_cal)
    moisture_actual_frac: 0.018   # R
    non_metallic_excess_pts: 1.0  # R, 0 ≤ x ≤ rejection_threshold_pts
    rejected_boxes: 0             # R, int ≥ 0 (grade failure / radioactivity ⇒ rejection)
    rejection_reason: null        # R if rejected_boxes > 0: non_metallic | wrong_grade | radioactivity
    flag: ASSUMPTION              # R, always ASSUMPTION (SIM survey)
  logistics_delay:                # O list
    - event_id: T02-LOG-1
      known_date: 2022-07-01      # R, panel_date ≤ pre-event date of first affected flow
      arrival_delay_days: 0       # R, ≥ 0 (void call / blank sailing)
      extra_dwell_days: 12        # R, ≥ 0 (port / CFS congestion after discharge)
      real_trigger_ref: "container-news.com 27-Jul-2022 (S4, freight_notes.md): void calls at Nhava Sheva/Mundra, Jul-2022"
      flag: ASSUMPTION            # delay days are SIM; the trigger is DIRECT
  buyer_payment_delay:            # O list
    - event_id: T02-PAY-1
      known_date: 2022-08-12      # R, ≤ contractual due date
      delay_days: 21              # R, > 0
      reason: "(SIM) buyer cash squeeze after LME fall"
      flag: ASSUMPTION
```

The engine accepts **stress-only** event types (`buyer_default {recovery_frac}`, `qco_hold {extra_dwell_days,
rejected_frac, rejected_loss_frac}`) only through the API (P4). They are never read from `trades.yaml`.

### 2.2 `config/counterparties.yaml`

```yaml
schema_version: 1
counterparties:
  - cp_id: BUY_RJK_1                          # R unique
    name: "Saurashtra Alloy Castings Pvt Ltd (SIM)"   # R, must end "(SIM)"
    type: buyer                               # R: supplier | buyer
    country: IN                               # R ISO-2
    location: "Rajkot, Gujarat"               # R
    lanes: [USEC_MUN]                         # R for suppliers; O for buyers (delivery region)
    credit_limit_inr: 250000000               # R. buyer: max (delivered receivable + pre-settlement MTM);
                                              #    supplier: max (refunds/claims receivable + LC exposure)
    default_payment_terms: credit_30          # R: lc_sight | lc_usance_60 | lc_usance_90 | credit_30 | credit_45 | advance
    msme_registered: true                     # R (MSMED s.15 relevance)
    profile:                                  # R — static SIM features for P5 logistic scoring (all ASSUMPTION)
      relationship_start: 2019-06-01          # → payment-history length (months) at any date
      prior_invoices_n: 18
      prior_dpd_mean_days: 4.0
      prior_dpd_max_days: 21
      prior_defaults_n: 0
      annual_turnover_inr: 1200000000
      internal_rating: B                      # A | B | C | D (SIM)
      group_concentration_frac: 0.35          # share of this buyer's purchases from the desk (SIM)
    flag: ASSUMPTION
    note: "fictional; numbers chosen to span the score range for P5 illustration"
```

The P5 features the engine supplies dynamically are (book_exposures_daily): exposure vs limit, days past due, order
concentration (share of desk sales volume to date), plus `profile` for the payment-history length.

### 2.3 New parameter keys (a new `config/params/book.yaml`, owned by P2; CONTRACTS §2 amendment)

| key | value | unit | flag | justification |
|---|---|---|---|---|
| `lc_sight_payment_lag_days` | 7 | days after B/L | ASSUMPTION | Document presentation and payment timeline in `finance_days_jea_nsa` note ("supplier paid ~day 7") |
| `lc_presentation_period_days` | 21 | days after shipment | ASSUMPTION (verify PENDING: UCP 600 Art. 14(c)) | LC validity for the opening fee |
| `survey_lag_days` | 1 | days after arrival | ASSUMPTION | Joint survey at CFS before BoE filing (simplification, §9) |
| `boe_lag_days` | 1 | days after arrival | ASSUMPTION | `igst_credit_lag_days` note: BoE ~1 day after arrival |
| `provisional_invoice_frac` | 0.95 | frac | ASSUMPTION | Common 90–100% provisional payment on LME-linked scrap SPAs. Range 0.90–1.00. |
| `final_invoice_lag_bdays` | 5 | panel days after pricing_end | ASSUMPTION | Final invoice by T/T after the M+1 average publishes |
| `claim_settle_lag_days` | 30 | days after survey | ASSUMPTION | Quality claim / debit note settlement (fixed-price SPAs) |

P3 needs **no** new keys. Every other number comes from the existing register.

---

## 3. Lifecycle and cashflow schedule

### 3.1 Notation for quantities (state-dependent through events `E`)

```
q_c      = quantity.contract_mt                     payload_g = quantity.payload_mt_per_box    n_box = quantity.boxes
n_rej    = E.quality.rejected_boxes (0 before known)          q_rej = n_rej × q_c / n_box
m_ex     = max(0, E.quality.moisture_actual_frac − spa.moisture_franchise_frac)   (0 before known)
disc     = spa.discount_multiplier × E.quality.non_metallic_excess_pts / 100      (0 before known)
q_clr    = q_c − q_rej                               # cleared through customs (rejected boxes re-exported, seller's account)
q_acc    = q_clr × (1 − m_ex)                        # invoice / sale weight
disc_s   = disc if sale.quality_passthrough else 0
box_l    = 20ft (JEA_NSA) | 40ft (USEC_MUN);   base_payload_l = container_payload_mt_<box_l>
roll(x)  = first panel day ≥ x                       ;   roll_bd(x, k) = k-th panel day after x
```

### 3.2 Market functions used by the legs (full definitions in §4)

`cash_at(s)` is the LME cash fixing or forward estimate. `A_P` is the M+1 average estimate. `X(T)` is the USD→INR rate for a flow settling at T
(CIP forward before T, spot on T). `F_X` is the MCX price of the contract expiring X. `box_mkt_l` is the market freight in USD per box.
`R_g,l` is the replacement value in ₹ per MT (§4.6).

### 3.3 Leg and cashflow table

"Fixed at" is the date from which the amount no longer depends on state (history is used from then on). Before that,
the amount is re-estimated from `M` at the clock. Every INR conversion of a USD amount at a date T uses `X(T)`.

| leg_type (cf_type) | Ccy | Amount (desk sign) | Settle date | Fixed at | Class |
|---|---|---|---|---|---|
| `purchase_invoice` (fixed pricing) | USD | `−q_c × price_usd_t` | sight: `lc_pay_date`; usance: `usance_maturity` | trade_date | P&L |
| `quality_claim` (fixed pricing) | USD | `+price × (q_c − q_acc × (1 − disc)) + [FOB] n_rej × rate_box` | `roll(survey_cal + claim_settle_lag_days)` | survey known_date | P&L |
| `purchase_provisional` (lme_m1_avg) | USD | `−prov_frac × q_c × p_prov`, `p_prov = factor × cash_at(bl_date) + premium` | as purchase_invoice | bl_date | P&L |
| `purchase_final` (lme_m1_avg) | USD | `−[q_acc × (factor × A_P + premium) × (1 − disc) − prov_frac × q_c × p_prov] + [FOB] n_rej × rate_box`. **May be positive (supplier refund).** | `roll_bd(pricing_end, final_invoice_lag_bdays)` | max(pricing_end, survey known_date) | P&L |
| `freight` (FOB only) | USD | `−n_box × rate_box`. `rate_box` = fixture rate if contracts-as-of ≥ fixture_date, else `box_mkt_l(M)`. If there is no fixture it is auto-fixed at `bl_date` at market. | collect: `roll(arrival_cal)`; prepaid: `bl_date` | fixture_date (or bl_date) | P&L |
| `freight_swap` (proxy_swap) | USD | `+swap.boxes × (box_mkt_l − strike_usd_box)` | `swap.settle_date` | settle_date | P&L (hypothetical) |
| `insurance` | INR | `−insurance_rate × insured_value_uplift × cfr_usd × X(bl_date)`, `cfr_usd = q_c × price_ref + [FOB] n_box × rate_box`, `price_ref` = price_usd_t or `p_prov` | `bl_date` | bl_date | P&L |
| `psic` (JEA_NSA only, `psic_required_uae_origin`) | INR | `−psic_cost_usd_per_box × n_box × X(bl_date)` | `bl_date` | bl_date | P&L |
| `lc_opening_fee` | INR | `−lc_opening_fee_frac_per_month × ceil(validity_days/30) × lc_value_usd × X(open)`; `lc_value_usd = q_c × (1 + tol) × price_ref(open)`; `validity_days = laycan.end + lc_presentation_period_days − lc_open_date` | `lc_open_date` | lc_open_date | P&L |
| `lc_confirmation_fee` (if confirmed) | INR | `−lc_confirmation_fee_pa × lc_value_usd × validity_days/360 × X(open)` | `lc_open_date` | lc_open_date | P&L |
| `lc_usance_fee` (usance) | INR | `−lc_usance_fee_frac_per_month × ceil(usance_days/30) × bill_usd × X(acceptance)`; `bill_usd` = abs(purchase_invoice or provisional USD) | `acceptance_date` | acceptance_date | P&L |
| `import_bill_commission` | INR | `−import_bill_commission_frac × bill_usd × X(pay)` | LC payment date | LC payment date | P&L |
| `usance_interest` (usance) | USD | `−bill_usd × (usd_rate_3m_pa@acceptance + usance_interest_spread_pa) × usance_days/360` | `usance_maturity` | acceptance_date | P&L |
| `customs_duty` | INR | `−cif_duty_usd × customs_usdinr_import@boe × bcd_scrap_hs7602 × (1 + sws_rate_on_bcd)`; `cif_duty_usd = (q_clr × price_ref + [FOB] (n_box − n_rej) × rate_box) × (1 + insurance_rate × insured_value_uplift)` | `roll(boe_cal)` | boe | P&L |
| `igst_import` | INR | `−(cif_duty_usd × customs_rate@boe + duty) × igst_rate_hs7602` | `roll(boe_cal)` | boe | **BS** (P&L if `igst_itc_available` is false) |
| `igst_credit` | INR | `+` same amount | `roll(boe_cal + igst_credit_lag_days)` | boe | **BS** (absent if no ITC) |
| `port_charges` | INR | `−port_cf_charges_inr_t_<nsa/mun> × base_payload_l × (n_box − n_rej)` | `roll(release_cal)` | trade_date (scalar params) | P&L |
| `demurrage` | USD | `−(n_box − n_rej) × max(0, (release_cal − arrival_cal).days − detention_free_days) × demurrage_usd_per_box_day` | `roll(release_cal)` | release | P&L. **Provisioned in full from the event known_date.** |
| `sale_advance` | INR | `+advance_frac × q_plan × P_sale(advance_date)` with `q_plan = q_acc` as known then | `advance_date` | advance_date | P&L |
| `sale_balance` | INR | `+q_acc × P_sale × (1 − disc_s) − sale_advance` | `roll(release_cal + credit_days) + delay` (advance-only: `advance_date`, amount = true-up, settled at `roll(release_cal)`) | max(window_end or contract_date, survey) | P&L |
| `mcx_future` (per line) | INR | VM each panel day: `lots × lot_mt × 1000 × (F_X(s) − F_X(s⁻))`, first day vs entry settle | each day in (entry, exit] | daily | P&L (realised daily) |
| `mcx_initial_margin` (per line) | INR | `IM(s) = abs(lots) × lot_mt × 1000 × F_X(s) × mcx_al_margin_used_frac`. Flows: `−IM(entry)`, `−(IM(s) − IM(s⁻))`, `+IM(exit⁻)` at exit. | daily | daily | **BS** |
| `fx_forward` (per line) | INR | `notional_usd × (usdinr(T) − K)` at maturity T, or `notional_usd × (X(cancel→T) − K)` at cancel_date | maturity or cancel_date | maturity or cancel | P&L |
| `funding` | INR | daily accrual (§3.5) | each panel day | daily | P&L |

`P_sale` (₹/t scrap): if contracts-as-of ≥ `sale.contract_date`, it is `price_inr_t` for fixed pricing, or
`factor × A_MCX × 1000 + premium` for mcx_avg (see §4.4). Before that it is `R_g,l(M)` (replacement value, D5), with the planned payment terms.

### 3.4 Date rules summary (planned, from B/L day b)

| Milestone | JEA_NSA (sight LC, FOB/CFR) | USEC_MUN (usance 90, CFR) | Rule |
|---|---|---|---|
| LC opened | ≥ trade_date, ≤ laycan start | same | ticket |
| PSIC and insurance | b | b (insurance only) | bl_date |
| LC doc acceptance / sight payment | b+7 | b+7 (acceptance, usance fee) | `lc_sight_payment_lag_days` |
| Arrival (freight collect) | b+5 | b+40 | `transit_days_<lane>` |
| Survey, BoE, duty, IGST | b+6 | b+41 | `survey_lag_days`, `boe_lag_days` |
| Release, delivery, port charges | b+15 | b+50 | `clearance_delivery_days` |
| Buyer due (credit 30) | b+45 | b+80 | `credit_days` |
| IGST credit | b+51 | b+86 | `igst_credit_lag_days` |
| Usance maturity (goods + interest + bill commission) | — | b+90 | `usance_days` |
| M+1 final invoice | pricing_end + 5 panel days | same | `final_invoice_lag_bdays` |
| MCX roll | 7th panel day before `min(actual expiry from mcx_al_expiry_dates_2022, panel expiry)` | same | `mcx_roll_days_before_expiry`. Using the minimum handles 30-Aug vs 31-Aug-2022. |

Each date is rolled independently to the panel calendar (D8). Validation: every settle date ≤ `HORIZON_END`.

### 3.5 Funding: the only finance cost in P3 (no double count)

```
B(s)  = Σ_{flows f of the trade with settle(f) ≤ s} amount_inr(f)          # P&L flows incl. daily VM, plus BS flows (IGST, IM)
                                                                           # accrued funding is NOT in B (simple interest)
acc(t)          = B(t⁻) × wc_rate_inr_pa(t⁻) × (t − t⁻).days / DAY_COUNT_INR        for first_flow_date < t ≤ close_date
overdue(t⁻)     = Σ_{sale receivables r: contractual_due(r) ≤ t⁻ < settle(r)} amount(r)    # contractual due = roll(release_cal incl. logistics events + credit_days), BEFORE payment-delay events
acc_overdue(t)  = −overdue(t⁻) × wc_rate_inr_pa(t⁻) × (t − t⁻).days / 365          → bucket demurrage_penalty (f)
acc_carry(t)    = acc(t) − acc_overdue(t)                                           → bucket roll_term_structure (g)
close_date      = max settle date over all flows of the trade (incl. IGST credit, IM return, forwards)
```

- The rate is symmetric: positive balances earn `wc_rate_inr_pa`, because the desk runs one cash-credit line that is always
  drawn. Trade-level funding therefore adds up exactly to desk-level funding.
- **Why nothing is double counted.** P1's `finance_inr_t = (goods + duty) × finance_days_l/365 × wc` bundles supplier
  cash-out → buyer receipt, **including** the 30-day buyer credit, into one approximation. P3 never reads
  `finance_days_*`, `finance_inr_t` or `igst_finance_inr_t`. Instead:
  - Buyer credit is funded because the sale receipt is late in `B`.
  - A usance LC is funded because no cash leaves until maturity, and the explicit `usance_interest` flow carries its cost.
  - IGST is funded through the BS pair.
  - MCX margins are funded through IM and VM flows. P1 omits this cost entirely.

  The replacement value `R` (§4.6) also excludes finance, so the finance cost appears exactly once.
- Diagnostic (not a control): `trade_book.csv` carries `p1_finance_memo_inr = (finance_inr_t + igst_finance_inr_t) × q_c`
  from the parity week and `p3_funding_inr` (lifetime Σ acc). The gap explains usance, advances and margin.

### 3.6 Realised vs unrealised

`realised_pnl_cash(τ)` = Σ P&L-class flows settled ≤ τ (incl. VM) + Σ acc ≤ τ. `mtm(τ)` = Σ P&L-class flows with settle > τ, valued at `M_τ`. A leg's `status`:

- `floating`: some amount driver not yet fixed.
- `partially_fixed`: M+1 or MCX averaging in progress, with `fixed_frac` = fixed days / N.
- `fixed_unsettled`
- `settled`

`mtm_daily.csv` reports `mtm_fixed_inr` and `mtm_floating_inr` separately, so a reader sees how much of the unrealised P&L is still at risk.

---

## 4. Valuation at date t

### 4.1 Market state (the state vector's market part)

```python
@dataclass(frozen=True)
class MarketState:                      # every float field may be a numpy array (broadcast) for Monte Carlo
    # (a) lme_flat
    lme_cash_usd_t: float
    # (b) cross_exchange_basis
    mcx_basis_inr_kg: Mapping[date, float]      # keyed by contract expiry (listed M1, M2)
    # (c) grade_spread
    grade_factor_frac: Mapping[str, float]      # zorba / taint_tabor / tense  ← grade_factor_<g> path at the state date
    # (d) freight
    freight_usd_t: Mapping[str, float]          # JEA_NSA / USEC_MUN, panel columns (base payload)
    # (e) fx
    usdinr: float
    customs_usdinr_import: float                # param path at the state date (CBIC notified rate in force)
    # (g) roll_term_structure
    lme_spread_usd_t: float                     # cash − 3M (panel sign: + backwardation)
    inr_rate_3m_pa: float
    usd_rate_3m_pa: float
    asof: date                                  # date the state was built from (memo; valuation never reads it)
```

`MarketHistory` wraps `market_daily.csv` plus a `ParamProvider` (default `desk.config.value`; tests inject overrides)
and exposes `state_at(d)`, `cash(d)`, `usdinr(d)`, `mcx_price(d, expiry)`, `freight_box(d, lane)`, `wc_rate(d)`, and
`panel_days`. `state_at(d)` is the only constructor used by P2 and P3.

Basis extraction in `state_at(d)`: for slot k ∈ {m1, m2}, `X = mcx_<k>_expiry(d)`. If `mcx_src(d)` is
`PROXY_IMPORT_PARITY`, then `b[X] = 0.0` and the builder asserts `abs(panel − F_theo) ≤ 1e-3`. Otherwise
`b[X] = mcx_obs_k(d) − F_theo(state, d, X)`. The alternative MCX source (third-party mirror, CONTRACTS §7.5) is an
adapter that yields the same (m1, m2) columns aligned to the LME calendar (point-in-time ffill ≤ `MAX_FILL_BDAYS`). It is
selected by `MarketHistory(mcx_source="mirror")`, and its outputs carry the suffix `_mcx_mirror`.

Measured on the real panel: replicating the proxy formula over Feb–Oct 2022 gives max abs 5.0e-5 ₹/kg (the 4-dp CSV rounding). Using
panel prices directly would put up to ₹25/day of fake (b) on a 100-lot line, which is why `b := 0` on proxy days.

### 4.2 LME curve and M+1 averages

```
lme_3m(M)          = M.lme_cash_usd_t − M.lme_spread_usd_t
d3m(τ)             = τ + DateOffset(months=3)
w(τ, s)            = clip((s − τ).days / (d3m(τ) − τ).days, 0, 1)            # flat beyond 3M (LME_CURVE_EXTRAPOLATION)
cash_fwd(M, τ, s)  = M.lme_cash_usd_t − M.lme_spread_usd_t × w(τ, s)          # = cash + (3M − cash)·w
cash_at(s; M, τ)   = H.cash(s) if s ≤ τ else cash_fwd(M, τ, s)                 # "fixing known at EOD of its own day"
A_P(M, τ)          = (1/N_P) × Σ_{s ∈ panel days of pricing month P} cash_at(s; M, τ)
```

The parallel cash shift is block (a). The spread and the clock (w and the fixed/unfixed split) are block (g). The 2-business-day cash prompt is
ignored. Example (DIRECT LME): a March-2022 B/L with provisional price at cash 3,583 (25-Mar) against the April average of 3,256.58
(19 days) produces a supplier refund on `purchase_final` of about −$326/t × factor. This is the 2022 crash seen through M+1.

### 4.3 FX

```
X(M, τ, T) = desk.units.fx_forward(M.usdinr, M.inr_rate_3m_pa, M.usd_rate_3m_pa, (T − τ).days)   if T > τ
           = M.usdinr                                                                            if T == τ
           = H.usdinr(T)                                                                         if T < τ (settled)
fx_forward leg value (τ < T, not cancelled) = N × (X(M, τ, T) − K)
```

The same flat 3M rates are used at every tenor, as in the panel's `usdinr_fwd_1m/3m` (PROXY). The bank margin is applied only in `K`, so
`new_deal` on booking = `−abs(N) × fx_forward_bank_margin_inr`.

### 4.4 MCX

```
uplift            = 1 + bcd_primary_al_hs7601 × (1 + sws_rate_on_bcd)                          # 1.0825
spot_theo(M)      = M.lme_cash_usd_t × M.usdinr / 1000 × uplift + mcx_domestic_premium_inr_kg
F_theo(M, τ, X)   = spot_theo(M) × (1 + M.inr_rate_3m_pa × max(0, (X − τ).days) / 365)
b(M, X)           = M.mcx_basis_inr_kg[X] if X listed else M.mcx_basis_inr_kg[max listed expiry]
F(M, τ, X)        = F_theo(M, τ, X) + b(M, X)
mcx_future value  = lots × lot_mt × 1000 × (F(M, τ, X) − F_entry)      while open; frozen at H.F(exit) after exit
A_MCX(window; M, τ) = (1/N_w) × Σ_{s ∈ window} [ H.F(s, X_M1(s)) if s ≤ τ else F(M, τ, X_M1(s)) ]   (₹/kg)
```

`X_M1(s)` = the panel M1 expiry on day s (a calendar rule, so it is known ahead). A futures price estimates its own future settle
(martingale), so unfixed days use today's price of *that* contract.

### 4.5 Freight

`box_mkt_l(M) = M.freight_usd_t[l] × container_payload_mt_<box_l>`. The panel USD/t is at base payload, so the box conversion
is exact. Memo `fixture_vs_market_inr = n_box × (rate_box − box_mkt_l(M)) × X(settle)` for fixed FOB freight. This is **not
P&L** (see §7.3).

### 4.6 Replacement value of unsold scrap (D5) — `R_g,l(M)` ₹ per MT, the §5 landed stack at today's market minus finance

```
cfr   = lme_3m(M) × M.grade_factor_frac[g]
cif   = cfr × (1 + insurance_rate × insured_value_uplift)
goods = cif × X(M, τ, τ + 1 month)           # same FX basis as P1 (parity.yaml parity_goods_fx_basis = usdinr_fwd_1m);
                                              # if P1 switches to spot, R follows the key (tenor 0)
duty  = cif × M.customs_usdinr_import × bcd_scrap_hs7602 × (1 + sws_rate_on_bcd)
port  = port_cf_charges_inr_t_<nsa|mun> × payload_scale_l_g  [+ JEA_NSA: psic_cost_usd_per_box × M.usdinr / container_payload_mt_20ft_<g>]
igst  = (cif × M.customs_usdinr_import + duty) × igst_rate_hs7602   only if igst_itc_available is false
R     = goods + duty + port + igst                          # NO finance_inr_t, NO igst_finance_inr_t
```

Cross-phase control: on each parity `value_date`, `R` equals P1's `goods_inr_t + bcd_inr_t + sws_inr_t + port_inr_t` from
`parity_weekly.csv` to ₹0.01. **Why the 1-month forward, not spot:** the desk's own USD payables are valued at the forward
(D6). A spot-based `R` would make an at-market, unsold, back-to-back cargo show a day-one loss equal to the forward premium
(~₹340–610/t in the window, per P1's doc). That is the artefact P1's `parity_goods_fx_basis` was chosen to avoid.
`(e)` moves `R` through spot and `(g)` through the forward points.

**Why not the MCX-anchored smelter netback?** (1) It would book the whole parity margin as day-one P&L on
`domestic_anchor_premium_inr_t`, an ASSUMPTION whose own evidence spans −52k…+13k ₹/t. A controller would reserve that
margin in full. (2) Grade factor (c) would be dead: nothing in the netback reacts to scrap discounts. (3) India is
scrap-deficit, so the marginal tonne is imported and import parity is the defensible domestic scrap mark. The netback
stays in P1 as the *screen*, and sale prices are negotiated inside [R, netback].

### 4.7 The valuation function

```python
def trade_value(t: Ticket, C: date, E: date, M: MarketState, tau: date, H: MarketHistory) -> TradeValue:
    """Π and per-leg breakdown. C = contracts-as-of date, E = events-as-of date, tau = clock.
    Legs: settled flows (settle ≤ tau) valued from H at their fixing/settle dates; unsettled from M at clock tau.
    Contract terms active iff their contract/entry/booking/fixture date ≤ C; events active iff known_date ≤ E.
    Returns Π = Π_val + Fund(tau): Π_val = settled P&L flows + MTM of unsettled flows (depends on C, E, M, tau);
    Fund(tau) = Σ acc over (first_flow, min(tau, close)] from the ACTUAL book path (history only, §3.5)."""
```

- Pure: it does not read files, does not call `desk.config` directly (only through `H.params`) and takes no wall-clock input.
- It is vectorised over any array-valued field of `M`. All branching is on dates or terms, never on market values, except
  `max(0, ·)` in demurrage, which depends only on dates.
- **PIT rule (enforced):** `H` raises `LookaheadError` if any accessor is called with a date > tau.

---

## 5. P&L attribution

### 5.1 State vector and chain

`S(t) = (C_t, E_t, M_t, τ_t)`, where C and E are "as-of" dates and M_t = `H.state_at(t)`. For each trade and each panel day t:

| Step k | Bucket | Block swapped t⁻ → t | Everything else held at |
|---|---|---|---|
| 0 | — | start `V0 = Π_val(C_{t⁻}, E_{t⁻}, M_{t⁻}, τ=t⁻)` (yesterday's cum P&L minus `Fund(t⁻)`) | |
| 1 | `lme_flat` (a) | `lme_cash_usd_t` | spread held ⇒ whole LME curve shifts in parallel |
| 2 | `cross_exchange_basis` (b) | `mcx_basis_inr_kg` (all expiries) | |
| 3 | `grade_spread` (c) | `grade_factor_frac` (all grades) | |
| 4 | `freight` (d) | `freight_usd_t` (both lanes) | |
| 5 | `fx` (e) | `usdinr`, `customs_usdinr_import` | |
| 6 | `demurrage_penalty` (f) | events-as-of `E` ; **+ `acc_overdue(t)`** | clock still t⁻ |
| 7 | `roll_term_structure` (g) | `lme_spread_usd_t`, `inr_rate_3m_pa`, `usd_rate_3m_pa`, **clock τ** ; **+ `acc_carry(t)`** | contracts still t⁻ |
| 8 | `new_deal` | contracts-as-of `C` | `V8 = Π_val(C_t, E_t, M_t, τ=t)` = today's cum P&L minus `Fund(t)` |

`bucket_k = V_k − V_{k−1}`. The chain runs on `Π_val` (no funding inside the swaps). The day's funding accrual `acc(t) = Fund(t) − Fund(t⁻)` is added to (f) and (g) as explicit amounts rather than through a swap, because
it is realised cash that exists only when the clock moves. `new_deal` is **reported first** (`PNL_BUCKETS` order) but
**computed last**, so new contracts are valued at the day's closing market with no factor cross-terms. A trade whose
`trade_date = t` has `Π = 0` for steps 0–7, so all of its first-day value is `new_deal` (CONTRACTS §7.2).

**What lands where (non-obvious items):**

| Item | Bucket | Mechanism |
|---|---|---|
| New fixing of an M+1 day | (a) for the price level; the estimate→fixing switch in (g) | Day t is already estimated from `M_t` in step 1. At step 7 the clock makes it a fixing, removing the 1-day curve interpolation. |
| MCX move | (a) via cash parity, (e) via usdinr, (g) via carry, rate, dte; (b) only true basis | D4. Worked example in §5.4. |
| MCX roll (exit M1, enter M2 at settle) | none | Exit and entry at settle are value-neutral contract events (new_deal = 0). "Roll yield" is the carry convergence booked daily in (g). |
| Hedge entry at settle | new_deal = 0 | |
| FX forward booking | new_deal = `−abs(N) × bank_margin` | |
| Freight fixture | new_deal = `n_box × (box_mkt − rate_box) × X` | Paying above the index is day-one value lost. Table 4 row 2.8. |
| Sale contracted | new_deal = `q × (P_contract − R)` | D5: margin recognition point. The pre-contract sale leg already used the ticket's planned payment terms, so only the price changes. |
| Quality survey outcome, demurrage provision, rejection | (f) | Events block |
| Buyer payment delay | (f) only through `acc_overdue` (no MTM change: undiscounted) | |
| Spread (cash–3M) change | (g) | Moves `R` (3M-based), unfixed M+1 days, and MCX via cash parity |
| Forward-points roll-down, rate changes | (g) | |
| Settlement of a flow on its settle day | 0 (identity) | Estimated at `M_t` with τ=t equals the realised value from `H(t)`, because `M_t = H.state_at(t)`. The 1-day tenor difference at the clock step goes to (g). |
| Weekend/holiday days | (g) carry | Calendar-day accruals and roll-down only |
| Cross-terms (e.g. ΔLME × ΔFX) | the factor swapped later, i.e. (e) | CONTRACTS §7.4 |

### 5.2 How MCX hedges stay consistent (no fake basis)

In steps 1–5 the MCX price is *recomputed* from the partially swapped state, not read from the panel. An LME cash move in
step 1 therefore changes both the physical legs and the hedge by the same parity sensitivity, and step 2 moves only `b`. In proxy
mode `b_t = b_{t⁻} = 0`, so `cross_exchange_basis ≡ 0` for every trade on every day (asserted in a test). With
`mcx_source="mirror"`, (b) carries the observed MCX-vs-parity residual. That is the CONTRACTS §7.5 basis-risk sensitivity.

The remaining physical-vs-hedge mismatches are real, and each shows in its own bucket:

- (c) scrap factor vs primary metal
- (g) cash–3M and MCX carry vs the physical's forward estimate
- (e) duty base on the notified customs rate vs MCX's market-rate uplift
- the `R` duty/insurance scaling (≈ 1.029) vs `uplift` 1.0825

### 5.3 Residual = 0: proof sketch and why it is still a real control

Telescoping gives `Σ_{k=1..8} (V_k − V_{k−1}) + acc_overdue(t) + acc_carry(t) = Π_val,t − Π_val,t⁻ + Fund(t) − Fund(t⁻) = Π_t − Π_{t⁻}`. The reported total is computed
**independently from the ledger**:
`total_t = Δ[realised_pnl_cash + funding_accrued + Σ_legs mtm]`, where `mtm` comes from `mtm_daily.csv` (pure states only)
and realised amounts come from the cash ledger built day by day. Then `residual = total_t − Σ buckets`.

The two paths agree only if `Π` has no hidden inputs:

- config paths read at a date other than the state date or clock,
- history read beyond the clock,
- event or contract logic reading the wall calendar,
- a realised amount computed with a rate other than the one the estimate converges to at settlement.

Any such bug makes `V0(t) ≠ V8(t⁻)` and shows as a non-zero residual, so `abs(residual) ≤ RESIDUAL_TOL_INR` (₹1) per
trade-day is a genuine sign-off control. Float64 error on ₹10⁸ magnitudes is ~1e-8. Rounding happens only when CSVs are written.

### 5.4 Worked example on the real panel (07→08-Mar-2022; LME DIRECT, FX and MCX PROXY)

A short of 100 lots in the MCX 31-Mar-2022 contract. Cash 3,984.5 → 3,500.5; usdinr 76.9275 → 77.0510; inr 3M 3.7798%; dte 24 → 23:

| Step | ₹ |
|---|---|
| (a) cash swap | +20,202,398 |
| (b) basis | 0 |
| (e) usdinr swap | −234,570 |
| (g) rate and clock | +15,118 |
| **Σ** | **+19,982,945** (panel-price VM +19,982,950; the ₹5 gap is panel 4-dp rounding, eliminated by D4) |

Initial margin at 10% on 07-Mar: ₹16,631,500.

A USD 1,000,000 payable due 15-Apr-2022 hedged by a forward booked 07-Mar (K = 77.3060, incl. ₹0.10 margin) gives:

| Line | Payable | Forward | Sum |
|---|---|---|---|
| new_deal | — | −100,000 | −100,000 |
| (e) | −123,947 | +123,947 | 0 |
| (g) | +5,534 | −5,534 | 0 |

The hedge nets to zero in (e) and (g), which is the hedge-perfect property (§8.4).

---

## 6. Exposures for Phase 4

### 6.1 Method

Central bump-and-revalue of `Π` with clock, contracts and events held at t. Bump sizes are named constants:

| Constant | Size |
|---|---|
| `BUMP_LME_CASH_USD_T` | 1.0 |
| `BUMP_USDINR` | 0.01 |
| `BUMP_FREIGHT_USD_T` | 1.0 |
| `BUMP_GRADE_FACTOR` | 0.001 |
| `BUMP_SPREAD_USD_T` | 1.0 |
| `BUMP_MCX_BASIS_INR_KG` | 1.0 |
| `BUMP_RATE_PA` | 0.0001 |

Legs are linear or bilinear in the factors, so central differences are exact up to float error. Physical vs hedge splits bump the relevant leg subsets.

### 6.2 `book_exposures_daily.csv` (one row per date × scope, scope ∈ {trade, book}; book rows have `trade_id = BOOK`)

| Column | Unit | Sign / definition |
|---|---|---|
| `date, scope, trade_id, in_window` | | |
| `mtm_inr, cum_pnl_inr, cash_balance_inr, mcx_im_inr` | ₹ | balance < 0 = funded by the WC line |
| `lme_delta_inr_per_usd_t` | ₹ per $1/t | dΠ/dcash (parallel curve). + = gains if LME rises. |
| `lme_delta_mt` | MT LME-cash-equivalent | `lme_delta_inr_per_usd_t / usdinr`. + long. |
| `lme_delta_usd` | USD | `lme_delta_mt × lme_cash_usd_t` |
| `lme_delta_physical_mt`, `lme_delta_mcx_mt` | MT | Physical legs vs MCX lines. One MCX lot ≈ `lot_mt × uplift × (1 + r × dte/365)` ≈ 5.44 MT LME-eq. |
| `hedge_ratio_lme_frac` | frac | `−lme_delta_mcx_mt / lme_delta_physical_mt` (NaN if abs(physical) < 1 MT) |
| `mcx_lots_open` | lots | signed sum of open lines |
| `mcx_basis_delta_inr_per_inr_kg` | ₹ per ₹1/kg | dΠ/db, all expiries in parallel |
| `fx_delta_usd` | USD | dΠ/d(usdinr): the net USD position. + = long USD (gains when INR weakens). Customs rate held. |
| `fx_delta_physical_usd`, `fx_delta_forwards_usd`, `fx_delta_mcx_usd` | USD | subsets |
| `hedge_ratio_fx_frac` | frac | `−fx_delta_forwards_usd / fx_delta_physical_usd` |
| `customs_fx_delta_usd` | USD | dΠ/d(customs rate) (duty base) |
| `freight_delta_inr_per_usd_t_jea_nsa`, `_usec_mun` | ₹ per $1/t | dΠ/dfreight. Non-zero only for unfixed FOB freight and proxy swaps (D5/§7.3). |
| `freight_open_mt_jea_nsa`, `_usec_mun`, `freight_open_boxes` | MT (base payload), boxes | `−freight_delta / usdinr`. + = short freight (hurt by rises). |
| `grade_delta_inr_per_0p01_<grade>` | ₹ per 0.01 of factor | dΠ/dgf × 0.01: unsold inventory before sale contract |
| `grade_exposure_mt_<grade>` | MT scrap | `dΠ/dgf / (lme_3m × usdinr)` |
| `spread_delta_inr_per_usd_t` | ₹ per $1/t | dΠ/d(cash − 3M) |
| `inr_rate_delta_inr_per_bp`, `usd_rate_delta_inr_per_bp` | ₹ | |
| `lme_fx_cross_inr` | ₹ per ($1/t × ₹0.01) | 4-point cross bump, for delta-gamma checks |
| `buyer_receivable_inr` | ₹ | delivered, unpaid sale balance (trade scope; P5 aggregates by `buyer_id`) |
| `buyer_presettlement_inr` | ₹ | `max(0, q × (P_contract − R))` before delivery (replacement risk) |
| `supplier_exposure_inr` | ₹ | Unsettled amounts due FROM the supplier: positive `purchase_final` (refund) and `quality_claim` receivables. LC-backed payables create no supplier credit exposure. |
| `days_past_due` | days | vs contractual due date |
| `buyer_id, supplier_id` | | for P5 group-bys |

### 6.3 Monte Carlo and scenario API (P4 imports; pure, vectorised)

```python
def revalue_book(book: Book, H: MarketHistory, t: date,
                 shocks: Mapping[str, np.ndarray] | None = None,
                 extra_events: Sequence[StressEvent] = (),
                 mcx_hold_basis: bool = True) -> np.ndarray:            # shape (n_trades, n_paths) of Π; P&L = Π_shocked − Π_base
    """Instantaneous full revaluation at clock t (contracts/events as of t).
    shocks: 'lme_cash_logret', 'usdinr_logret', 'freight_logret' (both lanes) or 'freight_<lane>_logret',
            optional 'lme_spread_abs', 'grade_factor_abs', 'mcx_basis_abs'.
    Shocked state: cash·e^r, usdinr·e^r, freight·e^r; MCX recomputed from shocked cash/FX with basis held (hedges move
    consistently); customs rate, grade factor, rates held unless shocked; clock held (no time decay — a 1-day carry is
    deterministic, and advancing the clock would need H beyond t = look-ahead)."""
```

Stress scenarios (Table 6 row 4.2) map onto the same API: `LME −15%` (cash × 0.85), `INR −5%` (usdinr ÷ 0.95,
documented choice), `freight +40%` (× (1 + freight_stress_shock_frac)), `buyer default` (StressEvent
`buyer_default{buyer_id, recovery_frac}` writes off the receivable and presettlement value), and `BIS-QCO + demurrage`
(StressEvent `qco_hold{qco_stress_delay_days, qco_stress_rejection_frac, qco_stress_rejected_loss_frac}`). A book of ~10 trades
with ~20 legs over 10,000 paths is ~2M element-wise array ops, well under a second.

Honest note for P4: the book's freight sensitivity is small by design once freight is fixed (D5). A +40% freight shock
hits unfixed FOB freight, proxy swaps and **future** parity (pipeline), not fixed cargo. P4 should say so next to the
overlay rather than inflate it.

---

## 7. Adverse events (Table 5 rows 3.4–3.6)

Event windows are **reporting windows defined mechanically from real data** in `desk/mtm/events.py`. They are chosen after
the fact and are never used in trade decisions or rationales. A regression test pins the resulting dates for the current panel.

### 7.1 Event #1 — LME crash (real)

- **Window rule:** start = argmax `lme_cash_usd_t` in [WINDOW_START, WINDOW_END]; end = argmin on [start, WINDOW_END].
  Current panel: **2022-03-07 (3,984.5) → 2022-07-15 (2,320.5), −41.8%** (DIRECT).
- **Crash-fortnight rule** (for margin): the 10-panel-day interval inside the window with the most negative cash return.
  Current panel: **2022-04-22 (3,244) → 2022-05-09 (2,708), −16.5%**. The worst single day is 08-Mar-2022 (−13.0% log).
- **Isolated impact**, per trade and for the book:
  1. Σ over window days of `lme_flat`, split into physical legs and MCX legs from `attribution_leg_daily.csv`.
  2. The same for `grade_spread`, because scrap stickiness offsets part of the fall (`grade_falling_market_logic`).
  3. **Unhedged counterfactual:** re-run the engine on `book.without(instruments={"mcx"})` and take
     Δcum P&L over the window and to HORIZON_END. The difference includes VM/IM funding.
  4. `hedge_offset_frac = −Σ lme_flat_mcx / Σ lme_flat_physical`.
- **MCX variation-margin schedule:** daily VM, cumulative VM, IM, net margin cash and its funding from
  `mcx_variation_margin.csv` over [WINDOW_START, end]. It starts before the peak, because shorts pay VM in the 01–07 March spike and
  receive it in the crash. Report the peak cumulative outflow and its date, the max IM, and the crash-fortnight VM. Stress IM
  at 0.12 and 0.15 (the `mcx_al_margin_used_frac` note) as memo columns.

### 7.2 Event #2 — USD/INR depreciation (real, PROXY series)

- **Window rule:** the pair i < j in the window maximising `usdinr_j / usdinr_i`. Current panel: **2022-04-05 (75.3350)
  → 2022-07-14 (80.0352), +6.24%**. Memo: first-to-last window +5.07%.
- **Isolated impact:** Σ `fx` over the window by leg class: physical USD legs, `fx_forward` legs (the **forward-book
  offset**), MCX legs (a short MCX loses when INR weakens, because duty-paid parity rises in ₹) and INR-only legs (0).
  - `forward_offset_frac = −fx_forwards / fx_physical`.
  - Counterfactual `book.without(instruments={"fx_forward"})` gives the forward-book benefit.
  - The forward cost memo is Σ(new_deal margin + (g) on the forward legs).
  - Daily USD position (`fx_delta_physical_usd` vs `fx_delta_forwards_usd`) from `book_exposures_daily.csv`.

### 7.3 Event #3 — logistics disruption + buyer payment delay (CONTRACTS §7.6 framing)

- **Components:**
  1. **Buyer payment delay** (SIM; `buyer_payment_delay` events) is the headline.
  2. **Void calls at Nhava Sheva/Mundra**, a real Jul-2022 disruption per S4 (Container News 27-Jul-2022). It appears as
     `logistics_delay` events whose delay days are SIM, driving demurrage.
  3. **The real freight effect of fixtures locked above a falling market.** Freight fell ~34% on both lanes, 03-Mar → 26-Aug.
- **Window:** [min known_date of #3 events, max affected settle date]. The events' known_dates should fall in Jul–Aug 2022.
  A trader action that *cites* the article must be dated ≥ 27-Jul-2022.
- **Isolated impact:** `Π(book) − Π(book.without(events={"buyer_payment_delay","logistics_delay"}))` at HORIZON_END,
  decomposed into:
  - demurrage (f)
  - overdue funding (f)
  - extra carry funding from later receipts (g)
  - FX on USD demurrage (e)
  - any FX-forward mismatch where a forward was matched to a date the event moved (e)/(g)
- **Credit-limit mitigation:** from `book_exposures_daily`, per buyer: exposure/limit utilisation, days past due, peak utilisation,
  and the date a breach or DPD trigger fired. If P2's policy acted (e.g. later sales to that buyer switched to advance, dated
  after the delay's known_date), report the exposure reduction: peak utilisation with the actual book vs with that sale left on credit
  (counterfactual ticket). This is exposure, not P&L.
- **Freight, honestly:**
  - (i) `freight` bucket P&L exists only on unfixed FOB freight and proxy swaps.
  - (ii) The *fixture decision* impact is the counterfactual `book.with_fixtures_at_bl()` (fixture moved to spot booking at B/L), a
    real P&L difference between strategies.
  - (iii) The `fixture_vs_market_inr` memo is a **competitiveness** cost versus later importers. It is not a loss on the cargo, because
    §5's CFR grade factor does not fall when freight falls.
  - (iv) Any freight *spike* is `adverse_event_3_freight_stress_hypothetical.csv` (+40%, `freight_stress_shock_frac`),
    labelled HYPOTHETICAL STRESS in every row.

---

## 8. Outputs, module layout, tests

### 8.1 Tables (`outputs/tables/`)

| File | Grain | Columns |
|---|---|---|
| `trade_book.csv` (P2) | trade | `trade_id, trade_date, parity_week_end, trade_eligible, grade, lane, container, boxes, payload_mt_per_box, contract_mt, supplier_id, buyer_id, incoterm, freight_booked_by, freight_risk_bearer, purchase_pricing_type, price_usd_t, factor_frac, premium_usd_t, pricing_month, pricing_start, pricing_end, pricing_days, laycan_start, laycan_end, vessel, bl_date, arrival_date, survey_date, boe_date, release_date, import_payment, usance_days, lc_open_date, lc_pay_date, usance_maturity, lc_confirmed, fixture_date, fixture_usd_box, index_usd_box_at_fixture, fixture_vs_index_frac, freight_risk_layer, stop_loss_usd_box, stop_loss_resolution, sale_contract_date, sale_pricing_type, sale_price_inr_t, sale_factor_frac, sale_premium_inr_t, sale_window_start, sale_window_end, sale_terms, credit_days, advance_frac, advance_date, sale_due_date, credit_check_utilisation_frac, mcx_hedge_ratio_frac, fx_hedge_frac, replacement_inr_t_at_trade_date, day_one_value_inr, p1_finance_memo_inr, p3_funding_inr, close_date, rationale` |
| `trade_hedges.csv` (P2) | hedge line | `hedge_id, trade_id, instrument (MCX_AL/USDINR_FWD/FREIGHT_SWAP_HYPOTHETICAL), contract_expiry, roll_date_limit, lots, lot_mt, entry_date, entry_price_inr_kg, exit_date, exit_price_inr_kg, exit_reason, roll_to, booking_date, notional_usd, maturity_date, forward_mid_inr, bank_margin_inr, rate_inr, cancel_date, matched_leg, boxes, strike_usd_box, settle_date, decision_date, sizing_basis` |
| `trade_cashflows.csv` (P2 builds, P3 reconciles) | trade × leg × cashflow | `trade_id, leg_id, leg_type, cf_type, pnl_class (pnl/balance_sheet), currency, contract_date, fixing_date, due_date_contractual, settle_date, amount_ccy, fx_rate_used, amount_inr, amount_inr_est_at_trade_date, date_rule, weakest_input_flag, event_ids` |
| `mtm_daily.csv` | date × trade × leg | `date, in_window, trade_id, leg_id, leg_type, instrument, currency, status, fixed_frac, pnl_class, qty_mt, lots, notional_usd, px_usd_t, px_inr_t, px_inr_kg, fx_rate_used, settle_date, mtm_ccy, mtm_inr, mtm_fixed_inr, mtm_floating_inr, realised_cum_inr, leg_cum_pnl_inr, leg_daily_pnl_inr, fixture_vs_market_inr, weakest_input_flag`. Funding is a leg (`leg_type = funding`, mtm 0). |
| `attribution_daily.csv` | date × trade | `date, in_window, trade_id, daily_pnl_inr, new_deal, lme_flat, cross_exchange_basis, grade_spread, freight, fx, demurrage_penalty, roll_term_structure, residual, cum_pnl_inr` (bucket columns are INR, names exactly `PNL_BUCKETS`) |
| `attribution_leg_daily.csv` | date × trade × leg | `date, trade_id, leg_id, leg_type, <PNL_BUCKETS>, leg_daily_pnl_inr` (Σ legs = trade buckets exactly; funding leg carries the (f)/(g) accruals) |
| `book_exposures_daily.csv` | date × scope | §6.2 |
| `mcx_variation_margin.csv` | date × hedge line | `date, trade_id, hedge_id, contract_expiry, lots, lot_mt, action (entry/hold/roll_out/roll_in/exit), settle_inr_kg, prev_settle_inr_kg, vm_inr, cum_vm_inr, im_required_inr, im_change_inr, im_stress_012_inr, im_stress_015_inr, net_margin_cash_inr, cum_margin_cash_inr, funding_on_margin_inr` |
| `adverse_event_1_lme_crash.csv` | scope (trade/book) | `event_id, window_start, window_end, lme_cash_start_usd_t, lme_cash_end_usd_t, lme_change_frac, scope, trade_id, total_pnl_inr, lme_flat_inr, lme_flat_physical_inr, lme_flat_mcx_inr, grade_spread_inr, cross_exchange_basis_inr, fx_inr, roll_term_structure_inr, other_inr, unhedged_total_pnl_inr, hedge_benefit_inr, hedge_offset_frac, fortnight_start, fortnight_end, fortnight_pnl_inr, fortnight_vm_inr, vm_peak_cum_outflow_inr, vm_peak_outflow_date, im_max_inr, im_max_date, margin_funding_inr` |
| `adverse_event_1_lme_crash_daily.csv` | date | `date, lme_cash_usd_t, mcx_m1_inr_kg, book_cum_pnl_inr, book_cum_pnl_unhedged_inr, cum_lme_flat_physical_inr, cum_lme_flat_mcx_inr, vm_inr, cum_vm_inr, im_inr, net_margin_cash_inr, cum_margin_cash_inr` |
| `adverse_event_2_usdinr.csv` | scope | `event_id, window_start, window_end, usdinr_start, usdinr_end, usdinr_change_frac, first_to_last_change_frac, scope, trade_id, fx_physical_inr, fx_forwards_inr, fx_mcx_inr, fx_total_inr, forward_offset_frac, unhedged_total_pnl_inr, forward_book_benefit_inr, forward_cost_inr, usd_position_start_usd, usd_position_max_usd` (+ `_daily.csv`: `date, usdinr, fx_delta_physical_usd, fx_delta_forwards_usd, cum_fx_physical_inr, cum_fx_forwards_inr`) |
| `adverse_event_3_logistics_credit.csv` | event × trade | `event_id, trade_id, buyer_id, event_type, known_date, sim_flag, real_trigger_ref, arrival_delay_days, extra_dwell_days, delay_days, demurrage_inr, overdue_funding_inr, extra_carry_funding_inr, fx_effect_inr, isolated_impact_inr, peak_receivable_inr, credit_limit_inr, peak_utilisation_frac, max_days_past_due, mitigation_action, mitigation_date, peak_utilisation_without_mitigation_frac, fixture_vs_market_memo_inr, fixture_decision_pnl_inr` |
| `adverse_event_3_freight_stress_hypothetical.csv` | date × scope | `date, scope, trade_id, label (= "HYPOTHETICAL STRESS"), shock_frac, pnl_inr` |
| `pnl_controls.csv` | date × check | `date, check (residual_max_abs, ledger_identity_max_abs, proxy_basis_max_abs, bs_flows_lifetime_sum, cashflow_reconciliation_vs_p2), value, tolerance, status` |

`*_mcx_mirror.csv` variants of `attribution_daily`, `book_exposures_daily` and `adverse_event_1_*` are sensitivity outputs
(CONTRACTS §7.5). Their docs state they are never base P&L.

### 8.2 Module and API layout

```
desk/position/                  # pure library, no main(), no file writes (CONTRACTS §2 amendment)
  constants.py                  # named model-structure constants (§1)
  schema.py                     # frozen dataclasses: Book, Ticket, Purchase, Pricing, Freight, Sale, McxLine, FxForward,
                                #   FreightSwap, Events; load_trades(path), load_counterparties(path); Book.without(...),
                                #   Book.with_fixtures_at_bl(), Book.subset(trade_ids)
  calendar.py                   # roll_following, roll_bd, panel_days_in_month, roll_date(expiry) (§3.4)
  history.py                    # MarketHistory (PIT-guarded accessors, ParamProvider, mcx_source adapters), state_at
  state.py                      # MarketState, BLOCKS = {factor: fields}, swap(state_a, state_b, block)
  curves.py                     # cash_fwd, cash_at, lme_avg, fx_x, mcx_theo, mcx_price, mcx_avg, box_mkt, replacement_value
  schedule.py                   # expand(ticket, C, E, H) -> list[FlowSpec] (dates + amount closures)  (§3.3 table)
  legs.py                       # value_flow(FlowSpec, M, tau, H), realised_flow(...), mcx/fx/swap line values
  valuation.py                  # trade_value(...), book_value(...), revalue_book(...) (§6.3), funding_path(...)
  exposures.py                  # bump deltas (§6)
desk/book/                      # P2 stage
  validate.py                   # eligibility (§5a), PIT checks per decision_date, credit limits, lots/K/fixture re-derivation
  run.py                        # main(): trade_book.csv, trade_hedges.csv, trade_cashflows.csv
desk/mtm/                       # P3 stage
  attribution.py                # attribute_day(ticket, t_prev, t, H) -> dict[bucket, float] per leg (§5.1)
  ledger.py                     # realised cash ledger, VM/IM ledger, funding split, reconciliation vs trade_cashflows.csv
  events.py                     # window rules, counterfactual runs, event tables (§7)
  charts.py                     # equity curve + per-trade waterfalls via save_fig
  run.py                        # main(): all P3 tables + pnl_controls.csv; raises if any control fails
```

### 8.3 Synthetic example tickets that exercise every leg type (test fixtures only, not the base book)

These live in `tests/fixtures/trades_synthetic.yaml` (with a matching `counterparties_synthetic.yaml`), marked
`# SYNTHETIC TEST FIXTURE — not the trade book`. They are validated with `eligibility_check=False`. Every date is a real panel day.

```yaml
schema_version: 1
trades:
  - trade_id: T91          # Gulf FOB fixed price, sight LC, fixture + stop-loss, unsold period, short MCX with roll, FX fwd, quality deduction
    trade_date: 2022-05-12
    grade: zorba
    lane: JEA_NSA
    parity_ref: {week_end: 2022-05-06}
    rationale: "SYNTHETIC FIXTURE"
    quantity: {contract_mt: 2000}                         # 26 MT/box → 77 boxes
    purchase:
      supplier_id: SUP_GULF_X (SIM)
      incoterm: FOB
      pricing: {type: fixed, price_usd_t: 2140.0}
      laycan: {start: 2022-06-01, end: 2022-06-15}
      vessel: "MV Test Feeder (SIM)"
      bl_date: 2022-06-10
      payment: {instrument: lc_sight, lc_open_date: 2022-05-16, lc_confirmed: false}
    freight:
      fixture_date: 2022-05-13
      rate_usd_box: 515.0
      payment: collect_at_arrival
      risk_layer: {type: unhedged_stop_loss, stop_loss_usd_box: 750.0}
    sale:
      buyer_id: BUY_X1 (SIM)
      contract_date: 2022-06-17                           # unsold 12-May → 17-Jun: replacement-value mark, grade (c) live
      pricing: {type: fixed, price_inr_t: 185000}
      payment: {terms: credit, credit_days: 30}
    hedges:
      mcx:
        hedge_ratio_frac: 0.80
        basis_risk_note: "primary-ingot futures vs Zorba scrap; proxy MCX = LME cash parity"
        lines:
          - {hedge_id: T91-MCX-1, contract_expiry: 2022-05-31, lots: -241, entry_date: 2022-05-12, exit_date: 2022-05-20, exit_reason: roll, roll_to: T91-MCX-2}
          - {hedge_id: T91-MCX-2, contract_expiry: 2022-06-30, lots: -241, entry_date: 2022-05-20, exit_date: 2022-06-17, exit_reason: unwind}
      fx_forwards:
        hedge_frac: 1.0
        lines:
          - {fwd_id: T91-FX-1, booking_date: 2022-05-12, notional_usd: 4280000, maturity_date: 2022-06-17, matched_leg: purchase_invoice}
    events:
      quality: {moisture_actual_frac: 0.018, non_metallic_excess_pts: 1.0, rejected_boxes: 0, flag: ASSUMPTION}

  - trade_id: T92          # US CFR M+1 average, usance 90 confirmed, MCX-average sale with advance, two MCX rolls + tranches,
                           # FX fwd held + cancelled, rejection, demurrage (void calls), buyer payment delay
    trade_date: 2022-04-08
    grade: taint_tabor
    lane: USEC_MUN
    parity_ref: {week_end: 2022-04-08}
    rationale: "SYNTHETIC FIXTURE"
    quantity: {contract_mt: 1050}                         # 21 MT/box → 50 boxes
    purchase:
      supplier_id: SUP_US_X (SIM)
      incoterm: CFR
      pricing: {type: lme_m1_avg, lme_reference: cash, factor_frac: 0.72, premium_usd_t: 0.0}   # pricing month = Jun-2022
      laycan: {start: 2022-05-02, end: 2022-05-16}
      vessel: "MV Test Mainliner (SIM)"
      bl_date: 2022-05-12
      payment: {instrument: lc_usance, usance_days: 90, lc_open_date: 2022-04-13, lc_confirmed: true}
    sale:
      buyer_id: BUY_X2 (SIM)
      contract_date: 2022-04-20
      pricing: {type: mcx_avg, mcx_contract: M1, window_start: 2022-06-20, window_end: 2022-07-01, factor_frac: 0.76, premium_inr_t: -3000}
      payment: {terms: advance_plus_credit, advance_frac: 0.20, advance_date: 2022-06-24, credit_days: 30}
    hedges:
      mcx:
        hedge_ratio_frac: 1.0
        basis_risk_note: "net long ~108 LME-eq MT: MCX-linked sale vs LME-cash M+1 purchase"
        lines:
          - {hedge_id: T92-MCX-1, contract_expiry: 2022-05-31, lots: -20, entry_date: 2022-04-20, exit_date: 2022-05-20, exit_reason: roll, roll_to: T92-MCX-2}
          - {hedge_id: T92-MCX-2, contract_expiry: 2022-06-30, lots: -20, entry_date: 2022-05-20, exit_date: 2022-06-21, exit_reason: roll, roll_to: T92-MCX-3}
          - {hedge_id: T92-MCX-3, contract_expiry: 2022-07-29, lots: -10, entry_date: 2022-06-21, exit_date: 2022-06-27, exit_reason: tranche}
          - {hedge_id: T92-MCX-4, contract_expiry: 2022-07-29, lots: -10, entry_date: 2022-06-21, exit_date: 2022-07-01, exit_reason: tranche}
      fx_forwards:
        hedge_frac: 1.0
        lines:
          - {fwd_id: T92-FX-1, booking_date: 2022-04-08, notional_usd: 2270000, maturity_date: 2022-08-10, matched_leg: purchase_provisional}
          - {fwd_id: T92-FX-2, booking_date: 2022-04-08, notional_usd: 300000, maturity_date: 2022-07-07, matched_leg: purchase_final, cancel_date: 2022-06-30}
    events:
      quality: {moisture_actual_frac: 0.004, non_metallic_excess_pts: 0.0, rejected_boxes: 1, rejection_reason: non_metallic, flag: ASSUMPTION}
      logistics_delay:
        - {event_id: T92-LOG-1, known_date: 2022-07-01, arrival_delay_days: 0, extra_dwell_days: 12, real_trigger_ref: "S4 Container News 27-Jul-2022 void calls", flag: ASSUMPTION}
      buyer_payment_delay:
        - {event_id: T92-PAY-1, known_date: 2022-08-12, delay_days: 21, reason: "(SIM) buyer cash squeeze", flag: ASSUMPTION}

  - trade_id: T93          # Gulf FOB M+1 average, unfixed freight auto-fixed at B/L + hypothetical proxy swap, fixed sale 100% advance,
                           # LONG MCX (fixed sale vs floating purchase) with tranche exits + roll on the 30-Aug expiry, clean quality
    trade_date: 2022-07-06
    grade: tense
    lane: JEA_NSA
    parity_ref: {week_end: 2022-07-01}
    rationale: "SYNTHETIC FIXTURE"
    quantity: {contract_mt: 1000}                         # 25 MT/box → 40 boxes
    purchase:
      supplier_id: SUP_GULF_X (SIM)
      incoterm: FOB
      pricing: {type: lme_m1_avg, lme_reference: cash, factor_frac: 0.79, premium_usd_t: 0.0}   # pricing month = Aug-2022
      laycan: {start: 2022-07-18, end: 2022-07-29}
      vessel: "MV Test Feeder II (SIM)"
      bl_date: 2022-07-25
      payment: {instrument: lc_sight, lc_open_date: 2022-07-08}
    freight:
      fixture_date: null                                   # booked at market on bl_date
      payment: collect_at_arrival
      risk_layer: {type: proxy_swap, swap: {swap_id: T93-FRT-1, boxes: 40, strike_usd_box: 441.5, start_date: 2022-07-06, settle_date: 2022-07-25}}
    sale:
      buyer_id: BUY_X1 (SIM)
      contract_date: 2022-07-06
      pricing: {type: fixed, price_inr_t: 166000}
      payment: {terms: advance, advance_frac: 1.0, advance_date: 2022-08-01}
    hedges:
      mcx:
        hedge_ratio_frac: 0.90
        basis_risk_note: "desk short LME via floating Aug purchase vs fixed INR sale; long MCX unwound through pricing month"
        lines:
          - {hedge_id: T93-MCX-1, contract_expiry: 2022-08-30, lots: 44, entry_date: 2022-07-06, exit_date: 2022-08-08, exit_reason: tranche}
          - {hedge_id: T93-MCX-2, contract_expiry: 2022-08-30, lots: 44, entry_date: 2022-07-06, exit_date: 2022-08-15, exit_reason: tranche}
          - {hedge_id: T93-MCX-3, contract_expiry: 2022-08-30, lots: 43, entry_date: 2022-07-06, exit_date: 2022-08-18, exit_reason: roll, roll_to: T93-MCX-4}
          - {hedge_id: T93-MCX-4, contract_expiry: 2022-09-30, lots: 43, entry_date: 2022-08-18, exit_date: 2022-08-31, exit_reason: unwind}
      fx_forwards:
        hedge_frac: 1.0
        lines:
          - {fwd_id: T93-FX-1, booking_date: 2022-07-06, notional_usd: 1780000, maturity_date: 2022-08-01, matched_leg: purchase_provisional}
```

**Fixture caveat for the implementer.** On 2022-07-06 the panel lists M1 = 29-Jul and M2 = 31-Aug. The **31-Aug** proxy expiry maps to the real
contract expiring 30-Aug. The validator must accept a `contract_expiry` equal to the *actual* expiry when the panel slot
differs by the known holiday shift, and look up prices via the panel slot. Otherwise T93 fails. This deliberately tests
that edge case.

**Coverage matrix.**

| Leg type | Covered by |
|---|---|
| purchase fixed + quality_claim | T91 |
| purchase provisional/final | T92, T93 |
| freight fixture | T91 |
| freight auto-fix at B/L | T93 |
| freight_swap | T93 |
| insurance | all |
| psic | T91, T93 |
| lc_opening_fee | all |
| lc_confirmation_fee, lc_usance_fee, usance_interest | T92 |
| import_bill_commission | all |
| customs_duty, igst (BS) | all |
| port_charges | all |
| demurrage | T92 |
| sale fixed | T91, T93 |
| sale MCX-average | T92 |
| advance / credit / mixed | T93 / T91 / T92 |
| overdue funding | T92 |
| MCX short / long | T91, T92 / T93 |
| MCX roll | T91, T92, T93 |
| MCX tranches | T92, T93 |
| FX forward held / cancelled | all / T92 |
| rejection | T92 |
| moisture + discount | T91 |
| unsold replacement mark | T91 |
| back-to-back day one | T93 |

### 8.4 Test strategy (`tests/test_position.py`, `tests/test_book.py`, `tests/test_mtm.py`)

**A synthetic market fixture.** `tests/fixtures/synthetic_market.py` builds a `market_daily`-shaped frame on the real LME
calendar (Feb–Oct 2022) with controllable paths, plus a `ParamProvider` override. The defaults are constants: cash
2,500, spread −10, usdinr 78, customs 79, rates 5%/2%, freight 20/80, gf 0.80, wc 10%. Scheduled single-block shocks are
injectable. The tests are:

1. **Curves (unit, hand-computed):**
   - `cash_fwd` at w = 0, ½, 1 and beyond 3M.
   - `lme_avg` with k of N days fixed.
   - `F_theo` replicates the real panel M1/M2 within 1e-3 ₹/kg on every 2022 day.
   - `fx_x` equals the panel `usdinr_fwd_3m` at the panel's 3M day count.
   - `R` equals the §5 components computed by hand.
2. **Schedule (unit):** every date in §3.4 for T91–T93, including following-roll over the 02/03-Jun and 29-Aug LME holidays, usance
   maturity, the laycan-month rule (raises when crossing months for M+1), the roll_date limit on 30-Aug, and settle ≤ HORIZON_END.
3. **Telescoping (property):** for 200 seeded random (ticket from fixtures × day × random state perturbations), assert
   Σ buckets (which include the acc_overdue/acc_carry split) == ΔΠ within 1e-6 ₹, and V0(t) == V8(t⁻) within 1e-6 ₹.
4. **Ledger identity (property):** `Π(S_t) == realised_pnl_cash + funding + Σ mtm` within 1e-6 ₹, every day, every fixture.
5. **Residual control on the real panel:** run P3 on the fixture book; assert abs(residual) ≤ ₹1 on every trade-day, and plant a
   deliberate hidden-input bug (config read at the settle date) to show the residual catches it.
6. **Single-block isolation:** hold the clock (a test-only `attribute(S_prev, S_curr)` with equal τ), move one block; assert
   only that bucket is non-zero.
7. **Hedge-perfect FX:** a fixed-USD purchase + 100% forward on the same date and notional ⇒ Σ legs (e) = 0 and (g) = 0 every day;
   lifetime INR cost = N × K.
8. **Hedge-perfect metal (synthetic, fractional lots allowed):** gf, spread, rates constant and customs = usdinr; an unsold fixed-USD
   cargo plus MCX short sized to `−lme_delta_physical_mt / lot_lme_eq` ⇒ Σ(a) = 0.
9. **Hedge-perfect freight:** T93-style unfixed freight + proxy swap of the same boxes and window ⇒ Σ(d) = 0 until settle.
10. **Proxy basis:** `cross_exchange_basis ≡ 0` for every trade-day on the real panel.
11. **Zero-move day:** M_t = M_{t⁻}, no events or contracts ⇒ (a)–(f) and new_deal = 0; (g) = roll-down + carry only.
12. **Terminal:**
    - At HORIZON_END every leg is `settled`, Σ mtm = 0, and the lifetime Σ of BS flows = 0 per trade (IGST, IM).
    - Cum P&L = Σ P&L flows + funding.
    - Σ VM per line = lots × lot_kg × (F_exit − F_entry).
13. **Cross-phase reconciliation:**
    - P3 realised ledger == `trade_cashflows.csv` (₹0.01).
    - P3 re-derived `rate_inr`, entry/exit prices and `index_usd_box_at_fixture` == `trade_hedges.csv` / `trade_book.csv`.
    - `R` == P1 components on parity week_ends.
14. **No look-ahead:** `MarketHistory` truncated at t gives identical `Π` and exposures at t, and the PIT guard raises if an accessor asks
    for a date > τ.
15. **Linearity:** doubling `contract_mt`, lots and notionals doubles every bucket (excluding the ceil on boxes, which is fixed in the fixture).
16. **Counterfactual consistency:** `Π(book) − Π(book.without({"fx_forward"}))` == Σ forward-leg Π + the funding difference, reconciled.
17. **Determinism:** run P3 twice and assert sha256 equality of every output CSV.
18. **Event windows:** the rules return 2022-03-07/2022-07-15, 2022-04-22/2022-05-09 and 2022-04-05/2022-07-14 on the current panel.

---

## 9. Edge cases, simplifications and what not to model

### 9.1 Edge cases handled

| Case | Treatment |
|---|---|
| Date on a non-panel day | Roll following, independently per milestone. Dwell counted in calendar days. |
| M+1 laycan spanning two months | Validation error (pricing month must be known at trade date) |
| Future fixing beyond the 3M date | Flat extrapolation of the spread weight (w = 1) |
| MCX contract not M1/M2 today (MCX-average sale months ahead) | Theo price + basis of the furthest listed contract |
| Panel expiry ≠ actual expiry (31 vs 30-Aug-2022) | Roll limit uses the earlier date; prices via panel slot; validator maps actual ↔ slot |
| Final M+1 invoice negative | Supplier refund receivable; counts in `supplier_exposure_inr` |
| Rejected boxes | Removed from duty, port and sale; supplier refunds invoice and FOB freight via claim/final; demurrage on rejected boxes not charged to desk |
| Arrival/dwell delay moves a date an FX forward was matched to | Forward still settles at its maturity; the mismatch shows in (e)/(g); `trade_hedges.csv` flags `matched_leg_date_moved` |
| FX forward cancelled | Settled on cancel date at `N × (X(cancel, T) − K)` (simplification: banks usually settle at maturity or pay a discounted value) |
| Trade/hedge/booking date not a panel day | Validation error (no silent roll on decision dates) |
| Customs rate path ends 2022-09-16 and clamps after | BoE after the next unrecorded notification uses a stale rate. Flagged in §11. |
| Grade-factor paths clamp after 2022-09-15 | Constant marks for unsold cargo in Sep–Oct (unlikely in a book trading Mar–Aug) |
| Sale contracted after delivery | Validation error (desk does not warehouse) |
| Stop-loss trigger | P2 resolves to a dated forced fixture using index values ≤ trigger day; with 2022's falling freight it will not fire (stated) |
| Zero-balance or post-close funding | No accrual after `close_date` |

### 9.2 Simplifications accepted (why they are fine for an interview-grade desk)

1. **Undiscounted, flat 3M rates for all FX tenors.** Horizon ≤ 8 months; discounting would move values by < 3%. CONTRACTS §7.3 already rules it.
2. **Linear cash→3M interpolation for M+1 estimates.** Only cash and 3M are DIRECT; the error is a small (g) timing effect that
   vanishes as days fix.
3. **Replacement-value mark for unsold scrap** (D5). This is a policy choice, and the conservative one.
4. **Duty on the provisional value**, with no customs final assessment. The error is ~2.75% × (final − provisional) ≈ ₹1–2k per trade.
5. **Survey before BoE.** It lets rejected boxes be kept out of duty cleanly. In practice examination follows BoE, and rejected cargo
   would need re-export with duty drawback.
6. **Symmetric funding rate on one WC line.** Trade-level funding becomes additive and simple to explain.
7. **MCX settle = proxy close.** DPL limit-lock days, the MCX-vs-LME close-time gap and brokerage are not modelled. Basis
   noise from the mirror sensitivity covers the order of magnitude (`mcx_basis_std_inr_kg` 4.44).
8. **Deterministic events from YAML.** Probabilistic default belongs to P4/P5 stress.
9. **Payment dates of LC fees and insurance at a single rule date**, ignoring bank minimum charges (₹2,000) against lakh-sized fees.

### 9.3 Do NOT model

- Output GST collection and remittance.
- Profit taxes, TDS, stamp duty.
- ECL/CVA provisions in base P&L.
- LME futures, TAPOs or MAF hedges: no LME membership, and RBI's overseas commodity-hedging direction only arrived in Dec-2022 (notes §6).
- MCX physical delivery and tender period: positions are rolled 7 days before.
- Bulk parcels.
- Partial shipments across months.
- Quantity tolerance on B/L weight.
- Insurance claims.
- Demurrage slab escalation.
- Warehouse inventory.
- Intraday prices.
- Freight pass-through into the CFR grade factor. Recorded as a model assumption; see §11 for a possible P4 sensitivity.

---

## 10. "What this does and doesn't tell you" (draft text for the P3 methodology doc)

**MTM and attribution.** For each simulated trade, the engine shows how much P&L came from signing the deal and how much
each market factor added or took away afterwards, down to the rupee. Every number is revalued from one set of formulas, and the
factors sum exactly to the total. It does **not** show what a 2022 desk would have earned. Freight levels and grade
factors are hindsight reconstructions (ASSUMPTION). MCX is an import-parity proxy, so LME–MCX basis is zero by
construction in base runs, and the mirror sensitivity is the only basis evidence. Unsold cargo is marked at import
replacement cost, so trading margin appears only when a sale is contracted. The split between factors depends on the
documented swap order: cross-effects sit in the later factor.

**Exposures.** These are the first-order sensitivities of the same valuation (MT of LME-equivalent metal, USD, open freight
boxes) that VaR and Monte Carlo consume. They are exact for this model's linear legs. They are not a forecast of how
scrap discounts, domestic premiums or MCX basis behave under stress. Those are held fixed unless a scenario shocks them.

**Adverse events.** Event windows are drawn after the fact from real LME and FX data to *report* what the book went
through. They were never inputs to trading. Isolated impacts combine factor sums over the window with re-runs of the
same book without hedges or without the simulated delays. They describe this simulated book's behaviour, not a
realised 2022 loss. Event #3's delays and payment slippage are simulated, anchored to a real July-2022 port disruption, and
any freight spike is labelled a hypothetical stress because freight fell in 2022.

---

## 11. Open issues, Phase 0 findings and required contract changes

### 11.1 CONTRACTS amendments this design needs (for the synthesizer)

1. §2: add the `desk/position/` shared pure library, `config/params/book.yaml` (P2 owner, 7 keys in §2.3),
   `tests/fixtures/`.
2. §6: add `attribution_leg_daily.csv`, `adverse_event_*_daily.csv`,
   `adverse_event_3_freight_stress_hypothetical.csv`, `pnl_controls.csv`, and the `*_mcx_mirror.csv` sensitivity names.
3. §7.2/§7.4: state that `new_deal` is computed last (contracts block) while reported first, and that daily funding
   accrual is split (f) overdue / (g) carry.
4. §7: record D5 (replacement-value mark for unsold scrap) and D6 (USD flows valued at the CIP forward).

### 11.2 Phase 0 values to report (not modified)

1. `customs_usdinr_import` ends at 2022-09-16 and clamps after. Any Bill of Entry after the next CBIC notification (~early Oct 2022)
   uses a stale rate. Extend the path to 31-Oct-2022, or P2 must keep BoE dates ≤ 2022-10-06.
2. The `finance_days_jea_nsa` note has BoE on ~day 8 (arrival + 3), while `igst_credit_lag_days` and the USEC note put BoE at
   arrival + 1. P3 uses `boe_lag_days = 1` (new key). Harmonise the note.
3. `usance_interest_spread_pa` is quoted over a 6-month ARR benchmark, but the panel only has the US 13-week bill
   (`usd_rate_3m_pa`). P3 uses it as a PROXY benchmark, so the tenor mismatch is a few bp.
4. `lc_opening_fee_frac` (PROXY, 3-month validity) duplicates `lc_opening_fee_frac_per_month` (DIRECT). P3 uses the per-month key
   × actual validity months. The PROXY key should be marked memo-only.
5. No `lc_presentation_period_days` exists (UCP 600 Art. 14(c), 21 days), so it is added in `book.yaml` with verify PENDING.
6. The panel's MCX expiry rule gives 31-Aug-2022 against the real 30-Aug (known). The design handles it (§8.3 caveat); no change needed.

### 11.3 Decisions left open (need a call)

1. **Contract grade factor vs mark.** Contract factors should be set from the base `grade_factor_<g>` at trade date. That path
   is our proxy for the contemporaneous supplier quote a 2022 desk would have seen; §5a separately forces selection to pass the PIT
   factor. If the synthesizer instead requires contract factors from `grade_factor_mix_pit`, the base mark would produce day-one
   losses as large as −0.12 × LME × q in March-2022. That would be a data artefact, not a trading result.
2. **Freight pass-through.** Under §5 the CFR grade factor does not respond to freight, so fixed freight carries no P&L risk. If the
   synthesizer wants freight in the cargo mark, add `freight_passthrough_to_cfr_frac` (ASSUMPTION, default 0, P4 sensitivity only) with
   an explicit reference-freight definition. I recommend leaving it out of base.
3. **Sale-price discipline.** P2 should set contracted sale prices inside [R, smelter netback] at the sale date, using information
   ≤ that date, and write both bounds into `trade_book.csv`. Otherwise `new_deal` at sale is not interpretable.
4. **Provisional invoice %** (0.95) and **final-invoice lag** are judgement calls that noticeably change supplier refund
   exposure in the crash months. P5 should show them as a sensitivity.
