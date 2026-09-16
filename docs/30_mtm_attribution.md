# 30 — Daily MTM & P&L attribution engine (methods)

> **ACADEMIC SIMULATION — not actual trades.** Every counterparty, vessel, forwarder, bank and operational outcome
> behind these numbers is fictional and labelled (SIM). This page documents *how the engine works*; the numbers it
> quotes come from the checked-in book and are reproducible with the command in §1.

Component 3 of `docs/spec/MASTER_SPEC_V3.md` (Table 5). Implements `docs/design/30_position_model.md` against
`CONTRACTS.md` §7 and §7a. Deviations from the design are listed and justified in §11.

**The results are in §13**, on the real nine-ticket book. The adverse events have their own page,
`docs/31_adverse_events.md`. The one-line answer: the book makes **₹197.9 m over 14,350 MT (₹13,792/MT)**, of which
₹168.5 m is deal margin booked at inception and ₹29.4 m is what the market then did to it.

---

## 1. How to run it

```sh
cd /path/to/ujjwal
DESK_OFFLINE=1 .venv/bin/python -m desk.mtm.run                 # the real book (config/trades.yaml)
DESK_TRADES_FILE=config/trades.example.yaml \
DESK_COUNTERPARTIES_FILE=config/counterparties.example.yaml \
DESK_OFFLINE=1 .venv/bin/python -m desk.mtm.run                 # the checked-in fixtures
```

`main()` raises `ControlFailure` if any row of `outputs/tables/pnl_controls.csv` fails. The full 9-trade book takes
about 20 s including the four counterfactual re-runs, both sensitivity variants and the charts; a re-run is
byte-identical.

**Module map** (all of it inside `desk/mtm/`, see §11.1):

| Module | What it owns |
|---|---|
| `constants.py` | tolerances, bump sizes, and the temporary bridge to the design §14 `book.yaml` keys |
| `calendar.py` | panel-day arithmetic, following-roll, MCX contract months and roll deadlines |
| `state.py` | `MarketState` and the seven attribution blocks |
| `history.py` | `MarketHistory`: point-in-time-guarded panel reader, basis extraction, MCX/grade source switches |
| `curves.py` | LME forward curve, M+1 averages, CIP FX, MCX parity, replacement value |
| `lifecycle.py` | ticket → dated `Flow` schedule (design §4) |
| `valuation.py` | `trade_value`, the cash ledger and funding, `revalue_book` (the Phase 4 API) |
| `attribution.py` | the eight-step block-swap chain |
| `exposures.py` | central bump-and-revalue deltas |
| `events.py` | derived event windows, counterfactual books, event tables |
| `engine.py` | the daily driver and every output frame |
| `charts.py`, `run.py` | figures and the stage entry point |

---

## 2. The state vector

`desk.mtm.state.MarketState` is the **only** door through which a dated market input reaches the valuation. Every
field belongs to exactly one bucket of `desk.reporting.style.FACTOR_ORDER`, and the module raises at import time if
a field is ever added without being assigned to a block — which is what makes the attribution exhaustive rather
than merely plausible.

| Field | Unit | Block | Flag |
|---|---|---|---|
| `lme_cash_usd_t` | USD/MT | (a) `lme_flat` | DIRECT |
| `mcx_basis_inr_kg` (per contract month), `mcx_domestic_premium_inr_kg` | ₹/kg | (b) `cross_exchange_basis` | PROXY |
| `grade_factor_frac` (per grade) | frac of LME 3M, CFR basis | (c) `grade_spread` | ASSUMPTION |
| `freight_usd_t` (per lane, base payload) | USD/MT | (d) `freight` | ASSUMPTION / PROXY |
| `usdinr`, `customs_usdinr_import` | ₹/USD | (e) `fx` | PROXY / DIRECT |
| — (the events-as-of date) | — | (f) `demurrage_penalty` | SIM |
| `lme_spread_usd_t`, `inr_rate_3m_pa`, `usd_rate_3m_pa`, `wc_rate_inr_pa` (+ **the clock**) | USD/MT, p.a. | (g) `roll_term_structure` | DIRECT / PROXY / ASSUMPTION |

`MarketHistory.view(tau)` wraps the panel so that **any** accessor called with a date beyond the clock raises
`LookaheadError`. A rule that is only written down gets broken; a rule that raises does not.

### 2.1 Where the MCX basis comes from

`F(M, tau, month) = [cash x usdinr / 1000 x (1 + BCD_primary x (1 + SWS)) + domestic_premium] x (1 + r_inr x dte/365)
+ b[month]`, with `dte` measured to the **panel's** expiry slot for that contract month.

On a `PROXY_IMPORT_PARITY` day the panel MCX column *is* that formula, so `b ≡ 0` **by construction**, and the
builder asserts the replication before it says so: the worst gap over the whole panel is **5.0e-5 ₹/kg**, which is
the 4-decimal rounding of the CSV. On a MANUAL (bhavcopy) or MIRROR day, `b = observed − theo` is a real residual.

This is the point of D4: an LME move must reach an MCX hedge through (a), an FX move through (e) and carry through
(g). Only a true residual belongs in (b). Without it, a proxy series manufactures fake basis on every hedged day.

**Consequence you must read with every base run:** bucket (b) is **empty by construction**. The LME–MCX basis is
visible only in the `_mcx_mirror` sensitivity, and those files are never base P&L.

---

## 3. Lifecycle and cashflows

`desk.mtm.lifecycle.expand(ticket, book, C, E, H)` turns one purchase SPA carrying 1–3 bills of lading into dated
`Flow` objects. `C` is contracts-as-of, `E` is events-as-of; a term exists only from its own contract / entry /
booking / fixture date, and an event bites only from its known date. **Before the trade date the schedule is
empty**, which is what makes a ticket's whole first-day value land in `new_deal` with no special case.

### 3.1 Dates (design §4.1), per bill of lading `b`

`roll(x)` = the first LME panel day on or after `x`. Every milestone rolls **following** and **independently**;
dwell for demurrage is counted in calendar days.

| Milestone | Rule |
|---|---|
| documents presented; sight payment / usance acceptance | `roll(b + lc_sight_payment_lag_days)` |
| usance maturity | `roll(b + usance_days)` |
| arrival | `roll(b + transit_days_<lane> + Σ arrival_delay_days)` |
| joint survey (quality known) | `roll(arrival_cal + survey_lag_days)` |
| Bill of Entry (duty, IGST paid) | `roll(arrival_cal + boe_lag_days)` |
| release, port charges, demurrage | `roll(arrival_cal + clearance_delivery_days + Σ extra_dwell_days)` |
| IGST credit | `roll(boe_cal + igst_credit_lag_days)` |
| final invoice (M+1) | `max(pricing_end + final_invoice_lag_bdays panel days, roll(survey_cal))` — see §11.3 |
| quality claim settled | `roll(survey_cal + claim_settle_lag_days)` |
| sale invoice | `roll(max(release_cal, MCX window_end))` |
| sale due | `roll(sale_invoice + credit_days + Σ delay_days)` |
| MCX roll deadline | `mcx_roll_days_before_expiry` panel days before the **DIRECT** expiry for that month |

### 3.2 Quantities (design §4.2)

`q_bl = boxes x container_payload_mt_<box>_<grade>`; rejected boxes leave the Bill of Entry, the port charges and
the sale; `q_acc = (q_bl − q_rej) x (1 − spa_moisture_deduction_ratio x moisture excess)`; the contamination
discount is `spa_contamination_discount_multiple x excess`. When the ticket uses the registered SPA template the
engine **asserts** that `desk.parity.quality.settle_weight_and_penalty` returns the same numbers, so Phase 1 and
Phase 3 can never drift.

### 3.3 Leg valuation

Each flow carries a `contract_date`, a `settle_date`, an optional `fixing_date` and a closed-form
`amount(M, tau, HV)`.

```
value_ccy = frozen amount evaluated at the fixing date        if fixing_date < tau
          = amount(M, tau, HV)                                otherwise
value_inr = value_ccy x X(M, tau, settle_date)                for USD flows
X(M, tau, T) = H.usdinr(T)                    if T < tau      (the rate that actually fixed)
             = M.usdinr                       if T == tau
             = CIP forward to T               if T > tau      (CONTRACTS §7a.1 clause 4)
```

Valuing a future USD flow at the CIP forward **to its own settle date** is what makes a 100 % forward hedge exactly
flat in (e) and (g). The engine asserts at build time that no flow's `fixing_date` is after its `settle_date`: an
amount that fixes after it has settled would make the realised ledger and the mark diverge (and it did — §11.3).

### 3.4 Cashflow catalogue

Implemented in full: `PURCHASE_INVOICE` (fixed), `PURCHASE_PROVISIONAL` / `PURCHASE_FINAL` (M+1 official-cash
average of the month after the B/L month), `QUALITY_CLAIM`, `FREIGHT` (FOB), `INSURANCE`, `PSIC`,
`LC_OPENING_FEE`, `LC_CONFIRMATION_FEE`, `LC_USANCE_FEE`, `IMPORT_BILL_COMMISSION`, `USANCE_INTEREST`,
`CUSTOMS_DUTY`, `CUSTOMS_DUTY_DIFFERENTIAL`, `IGST_IMPORT` / `IGST_CREDIT`, `PORT_CHARGES`, `DEMURRAGE`,
`SALE_ADVANCE`, `SALE_BALANCE`, `MCX_VARIATION_MARGIN`, `MCX_SLIPPAGE`, `MCX_TRANSACTION_COST`,
`MCX_INITIAL_MARGIN`, `FX_FORWARD`, `INVENTORY_MARK`, `FUNDING`, and `FREIGHT_SWAP_HYPOTHETICAL` (barred from the
base book; every row it produces is labelled).

`pnl_class` separates **PNL** from **BS**: the IGST pair and MCX initial margin move cash — and therefore funding —
but never P&L, and their undiscounted lifetime sum per trade is asserted to be zero.

### 3.5 Unsold cargo: the replacement-value mark (design D5)

```
cfr   = (cash − cash-3M spread) x grade_factor[g]
cif   = cfr x (1 + insurance_rate x insured_value_uplift)
goods = cif x X(M, tau, tau + 1 month)
duty  = cif x customs_usdinr_import x bcd_scrap_hs7602 x (1 + sws_rate_on_bcd)
port  = port_cf_charges_inr_t_<nsa|mun> x payload_scale [+ JEA_NSA: psic_cost x usdinr / payload_20ft_g]
R     = goods + duty + port                                  # NO finance, NO IGST financing
```

Marking at the MCX-anchored smelter netback instead would book the whole parity margin on day one on
`domestic_anchor_premium_inr_t`, an ASSUMPTION whose own evidence spans −52k…+13k ₹/t. Sale margin is recognised in
`new_deal` when the sale is contracted: `new_deal = q x (P_contract − R)`.

**Cross-phase control.** On every parity `value_date`, `R` must equal Phase 1's
`goods_inr_t + bcd_inr_t + sws_inr_t + port_inr_t`. Measured: **1.2e-10 ₹/MT** on the panel 1-month forward basis
Phase 1 itself uses, and **0.23 ₹/MT** when `R` recomputes the forward from covered interest parity (the panel
rounds `usdinr_fwd_1m` to 4 dp). Both are in `pnl_controls.csv`; §11.2 records why there are two.

### 3.6 Funding — the only finance cost in Phase 3

```
B(s)           = Σ amount_inr over ALL flows (PNL and BS) with settle <= s
acc(t)         = B(t-) x wc_rate_inr_pa(t-) x (t − t-).days / 365
overdue(t-)    = Σ receivables whose CONTRACTUAL due (before delay events) <= t- < settle
acc_overdue(t) = −overdue(t-) x wc_rate_inr_pa(t-) x (t − t-).days / 365     -> bucket (f)
acc_carry(t)   = acc(t) − acc_overdue(t)                                     -> bucket (g)
```

The rate is symmetric — one always-drawn cash-credit line — so trade-level funding adds exactly to desk-level
funding. Phase 3 reads **none** of `finance_days_*`, `finance_inr_t`, `igst_finance_inr_t` or `lc_opening_fee_frac`:
buyer credit is funded because the receipt is dated late, a usance LC because no cash leaves until maturity, IGST
through the BS pair, and margin through IM and VM. Nothing is counted twice.

---

## 4. Attribution

### 4.1 The chain

Per trade, per panel day, with `t-` the previous panel day:

| Step | Bucket | Block swapped `t- → t` |
|---|---|---|
| 0 | — | `V0 = Π_val(C(t-), E(t-), M(t-), tau = t-)` |
| 1 | `lme_flat` (a) | `lme_cash_usd_t` — the spread is held, so the whole curve shifts in parallel |
| 2 | `cross_exchange_basis` (b) | MCX basis (all months) and the domestic premium |
| 3 | `grade_spread` (c) | grade factors (all grades) |
| 4 | `freight` (d) | both lane freight levels |
| 5 | `fx` (e) | `usdinr`, `customs_usdinr_import` |
| 6 | `demurrage_penalty` (f) | events-as-of `E`, **plus** `acc_overdue(t)` |
| 7 | `roll_term_structure` (g) | cash-3M, the three rates, **the clock**, **plus** `acc_carry(t)`, **plus** the value of `ROLL`-purpose bookings dated `t` |
| 8 | `new_deal` | contracts-as-of `C` — every other booking dated `t`, valued at the day's close |

Each step is evaluated **per leg**, so `attribution_leg_daily.csv` sums to `attribution_daily.csv` exactly.
`new_deal` is computed last and reported first, so a new contract is valued at the day's closing market with no
factor cross-terms. Every cross-term lands in the factor swapped **later** — that is a convention, not a fact, and
it is the single biggest judgement in the split.

### 4.2 Where the non-obvious items land

| Item | Bucket | Why |
|---|---|---|
| a new M+1 fixing | (a) for the level, (g) for the estimate→fixing switch | the level is already in the day's state; the clock at step 7 removes the one-day curve interpolation |
| an MCX move | (a) via cash parity, (e) via `usdinr`, (g) via carry and days-to-expiry; (b) only the true residual | the hedge price is **recomputed** from the partially swapped state at every step, never read from the panel |
| MCX roll | (g) — execution cost only | exit and entry at the same settle are value-neutral; carry convergence is already booked daily in (g) |
| hedge entry/exit at settle | `new_deal` — slippage and charges only | |
| FX forward booked | `new_deal = −notional x fx_forward_bank_margin_inr` | the bank margin is the whole day-one value of a forward struck at the mid (asserted in the tests) |
| freight fixture | `new_deal = boxes x (index − fixture) x usdinr` | paying above the index is value given up on day one |
| sale contracted | `new_deal = q x (P_contract − R)` | D5: the margin-recognition point |
| survey outcome, rejection, demurrage provision | (f) | the events block |
| buyer payment delay | (f), through `acc_overdue` only | undiscounted MTM does not change when a dated receipt moves; only its funding does |
| settlement of a flow on its own settle day | 0 | the estimate at `(M_t, tau = t)` equals the realised value; the one-day tenor difference goes to (g) |

### 4.3 The residual is a control

`Σ buckets` comes from the chain. The day's **total** is computed independently from the cash ledger:
`Δ[realised P&L + funding + Σ mtm]`, where the realised amounts are accumulated day by day at each flow's own
settle date and the mtm terms come from a pure state. `residual = total − Σ buckets`, and `|residual| ≤ ₹1` per
trade-day.

The two paths agree only if the valuation has no hidden input. `tests/test_mtm_synthetic.py` plants one — a flow
that keeps marking after it has settled — and asserts the residual catches it. On the real 9-trade book the worst
residual is **1.9e-7 ₹** (float64 noise at ₹10⁸ magnitudes), and the control **has already earned its keep**: it
caught two real defects the first time the engine met the Phase 2 book (§11.3).

---

## 5. Exposures

`book_exposures_daily.csv` is central bump-and-revalue of the *same* `Π`, with the clock, the contracts and the
events held: `(Π(M+) − Π(M−)) / (2 x bump)`. Nothing re-implements pricing, so a risk number can never disagree
with a P&L number. Bump sizes are named constants in `desk/mtm/constants.py` (LME ±1 USD/t, FX ±0.01 ₹,
freight ±1 USD/t, grade factor ±0.001, spread ±1 USD/t, MCX basis ±1 ₹/kg, rates ±1 bp).

Signs are from the desk's point of view: `+ lme_delta_mt` = long metal, `+ fx_delta_usd` = long USD (gains when the
rupee weakens), `+ freight_open_boxes` = short freight. One MCX lot is
`lot_mt x duty uplift x carry ≈ 5.4–5.5 MT` of LME-equivalent metal, which is why hedge sizing is quoted in
LME-equivalent tonnes rather than physical tonnes.

Two definitions worth knowing before reading the columns:

* **`wc_rate_delta_inr_per_bp`** is today's funding accrual per basis point on the trade's actual dated cash
  balance — not the present value of the remaining funding. The working-capital rate touches funding only, and
  funding is a history-only accrual.
* **The physical group includes the replacement-value mark.** Unsold cargo marked at import replacement value is
  **long USD** (the goods leg of `R` is a USD price converted at the 1-month forward), so it partly offsets the
  USD payables. A 100 % forward hedge of the payable therefore leaves the book net long USD while the cargo is
  unsold. That is a real consequence of D5, not an error, and the event-2 table reports the offset ratio against
  both the USD cash legs and the net physical so the reader can see it.

### 5.1 The Phase 4 API

```python
desk.mtm.valuation.revalue_book(book, H, t, shocks=None, extra_events=(), mcx_hold_basis=True) -> np.ndarray
```

Instantaneous full revaluation at clock `t` (contracts and events as of `t`); shape `(n_trades, n_paths)`. `shocks`
takes scalars or equal-length numpy arrays: `lme_cash_logret`, `usdinr_logret`, `freight_logret` or
`freight_<lane>_logret`, and optionally `lme_spread_abs`, `grade_factor_abs`, `mcx_basis_abs`. MCX is recomputed
from the shocked cash and FX with the basis **held**, so a hedge moves consistently with the physical it hedges.
The clock is held: advancing it would need history beyond `t`.

The five Table 6 row 4.2 stresses map onto the same call — LME −15 %, INR −5 %, freight +40 % as shocks, and
`buyer_default` / `qco_hold` as `StressEvent` objects. **Stress event types are accepted only through this API and
are never read from `trades.yaml`.**

---

## 6. Adverse events

> **The results are in `docs/31_adverse_events.md`** — real market facts with dates and sources, each event's
> isolated impact against its counterfactual, the margin-cash schedule through the crash, the forward-book offset,
> the credit-limit mitigation, and the charts. This section is the method only.

Windows are **reporting** windows, derived mechanically from real data after the fact. They were never inputs to a
trade, and `desk.book.validate` never sees them (it does not import `desk.mtm` at all). On the current panel:

| Event | Rule | Result |
|---|---|---|
| E1 LME crash | argmax cash → argmin after it | 2022-03-07 ($3,984.5) → 2022-07-15 ($2,320.5), **−41.8 %** |
| E1 crash fortnight | the **10-trading-day return** window (11 observations) with the most negative cash return | 2022-04-22 ($3,244.0) → 2022-05-09 ($2,708.0), **−16.5 %** |
| — memo, 9 returns | the 10-*observation* reading | 2022-03-07 → 2022-03-18, −15.2 % |
| E2 INR depreciation | the pair `i < j` maximising `usdinr_j / usdinr_i` | 2022-04-05 (75.3350) → 2022-07-14 (80.0352), **+6.24 %** (first-to-last memo +5.07 %) |
| E3 logistics + credit | earliest E3 effective known date → last affected settle | per book; the cited void-call trigger is dated 2022-07-27 |

The off-by-one is pinned deliberately: "10 panel days" must mean 10 *returns*. Both readings are defensible; the
contract is the 10-return one and the other is published as a memo so the convention is visible.

**Method.** Isolated impact = the sum of the relevant buckets over the window's *returns* (days in `(start, end]`),
split by leg group, **plus** counterfactual re-runs of the same book with one component removed: `without mcx`,
`without fx_forward`, `without the simulated events`, `with the freight fixture undone`, and — because event 3 has
three separable causes — `without the dwell`, `without the payment delay` and `without the quality claims`
individually. A hedge benefit is therefore the difference between two runs of one engine — margin-funding
difference included — not a comparison of two models. The three event-3 components are additive to within
₹11,378 of interaction, and that interaction is reported rather than allocated.

**Event 3 is framed honestly** (CONTRACTS §7.6). Freight **fell** through the window: −35.6 % on JEA_NSA and
−35.6 % on USEC_MUN from the first to the last window day. There was no 2022 container spike on these lanes, so
event 3 is (i) a simulated buyer payment delay measured through the (f) overdue-funding accrual, days past due and
credit-limit utilisation, (ii) the **real, dated** July-2022 void calls at Nhava Sheva / Mundra with simulated
dwell, and (iii) the cost of fixtures locked above a falling market, measured as a counterfactual. Any freight
**spike** lives in `adverse_event_3_freight_stress_hypothetical.csv`, with every row labelled
`HYPOTHETICAL STRESS — not a 2022 event`.

---

## 7. Outputs

| File | Grain |
|---|---|
| `trade_cashflows.csv` | trade × leg × cashflow, two scenarios (`PLANNED_AT_TRADE_DATE`, `REALISED`) |
| `mtm_daily.csv` | date × trade × leg (funding is a leg with `mtm_inr = 0`) |
| `attribution_daily.csv` | date × trade (+ a `BOOK` row): `PNL_BUCKETS` + `residual` + totals |
| `attribution_leg_daily.csv` | date × trade × leg, same buckets (sparse: a leg that moved nothing has no row) |
| `book_exposures_daily.csv` | date × scope (`trade` / `book`) |
| `mcx_variation_margin.csv` | date × hedge line |
| `adverse_event_windows.csv` | one row per derived window |
| `adverse_event_1_lme_crash{,_daily}.csv` | E1 summary and daily |
| `adverse_event_2_usdinr{,_daily}.csv` | E2 summary and daily |
| `adverse_event_3_logistics_credit.csv` | E3 summary |
| `adverse_event_3_freight_stress_hypothetical.csv` | labelled stress, date × trade |
| `adverse_events_summary.csv` | the three event tables in one scan |
| `pnl_controls.csv` | date × check: value, tolerance, status |

Charts (all through `desk.reporting.style.save_fig`, so every one carries the SIM label):
`p3_equity_curve`, `p3_attribution_waterfall_{T01…T09,book}`, `p3_adverse_events`, `p3_mcx_vm_schedule`,
`p3_event1_hedged_vs_unhedged`, `p3_event2_fx_offset`.

`adverse_event_2_inr_depreciation.csv` and `adverse_event_3_payment_delay_demurrage.csv` are **aliases** with
identical content, written because the Phase 3 brief names the files that way and CONTRACTS §7a.3 names them the
other way. Sensitivity runs write `_mcx_mirror` and `_grade_pit` variants of `attribution_daily`,
`attribution_leg_daily`, `book_exposures_daily` and `adverse_event_1_*`. **They are never base P&L.**

---

## 8. Controls

`desk.mtm.run.main()` raises if any of these fails.

| Check | Tolerance | On the 9-trade book |
|---|---|---|
| `residual_max_abs` (per trade-day) | ₹1 | 1.9e-7 |
| `ledger_identity_max_abs` (valuation vs cash ledger, per trade) | ₹0.01 | 1.8e-7 |
| `final_pnl_vs_cashflows` (cum P&L at horizon vs Σ P&L cashflows + funding accrual, per trade) | ₹0.01 | 1.5e-7 |
| `proxy_basis_max_abs` (panel MCX vs parity theo) | 1e-3 ₹/kg | 5.0e-5 |
| `bs_flows_lifetime_sum` (per trade) | ₹0.01 | 0.0 |
| `terminal_mtm_abs` (per trade at `HORIZON_END`) | ₹0.01 | 0.0 |
| `replacement_vs_p1_panelfx_max_abs` | ₹0.01/MT | 1.2e-10 |
| `replacement_vs_p1_max_abs` (CIP forward) | ₹0.50/MT | 0.23 |
| `cashflow_reconciliation_vs_p2` | ₹0.01 when it applies | INFO: P3 owns the file (§11.5) |
| `book_param_fallback` | — | INFO rows, one per design §14 key served from code (§11.4) |

`final_pnl_vs_cashflows` states CONTRACTS §7.3 as an **independent** sum: it re-adds every P&L flow straight off
the schedule plus the funding accrual and lands on the trade's final cumulative P&L, bypassing the daily ledger
that `ledger_identity_max_abs` walks. Together the two close both paths.

`cashflow_reconciliation_vs_p2` is now a row in the file rather than a console line, so a missing check cannot be
mistaken for a passing one. It carries `INFO` while Phase 3 owns `trade_cashflows.csv` (§11.5); if Phase 2 ever
publishes its own, the row becomes a PASS/FAIL on the maximum per-trade realised-INR gap.

---

## 9. Provenance of everything the engine reads

| Input | Flag | Where it bites |
|---|---|---|
| LME official cash and 3M (Westmetall) | **DIRECT** | fixings, curve, MCX parity, M+1 averages |
| CBIC notified customs rate; BCD / SWS / IGST; MCX contract specs, expiries and position limit; SBI LC fee card; MSMED cap; FX no-documentation limit | **DIRECT** | duty base, flows, validation |
| USD/INR (ECB cross); INR and USD 3M rates; CIP forwards; the usance benchmark | **PROXY** | all FX, forwards, MCX parity, usance interest |
| MCX panel series (import-parity proxy) | **PROXY** | hedges and MCX-linked sales; factor (b) ≡ 0 by construction |
| MCX third-party mirror | **PROXY** | the basis sensitivity only, never base P&L |
| Grade factors (lag-2 mix + differentials) | **ASSUMPTION** (hindsight) | contract factors, the replacement mark, factor (c) |
| Freight levels / shape | **ASSUMPTION / PROXY** | unbooked FOB freight, factor (d), the fixture memo |
| Payloads, transit and clearance days, free days, demurrage rate, port charges, PSIC, WC rate path, usance spread, confirmation fee, margin used | **ASSUMPTION / PROXY** | dates, flows, funding, margin |
| The fifteen `book.yaml` keys of design §14 | **ASSUMPTION** (three PENDING verification) | dates and costs |
| Counterparties, vessels, survey outcomes, delay magnitudes, payment slippage | **SIM** | factor (f), event 3, Phase 5 features |
| July-2022 void calls at Nhava Sheva / Mundra, 27-Jul-2022 | **DIRECT** (Container News via `docs/research/freight_notes.md` S4) | the earliest permissible E3 known date |

---

## 10. What this does and doesn't tell you

**Does.** For each simulated trade the engine turns the ticket into a dated, rupee-reconciled ledger and a daily
mark that respects how an Indian scrap import desk actually pays and gets paid: LC timing, M+1 averaging,
provisional and final invoices, out-turn claims, Bill of Entry duty and the IGST credit lag, demurrage, buyer
credit, and the cost of financing all of it. It splits every day's P&L into LME level, LME–MCX basis, scrap grade
spread, freight, USD/INR, operational penalties and carry, with no unexplained residual, and it produces hedge
effectiveness and forward-book offsets from the same numbers the risk pack consumes. Exposures are exact
first-order sensitivities of that same valuation, so risk and P&L cannot disagree.

**Doesn't.** It is **not evidence of what a 2022 desk earned.** Trades, counterparties and every operational
outcome are simulated. Specifically:

* **Bucket (b) is empty by construction.** MCX is a duty-parity proxy in base runs; the real LME–MCX basis appears
  only in the mirror sensitivity, whose own provenance cannot be checked against MCX's bhavcopy.
* **Bucket (c) is the largest market bucket in this book and it is a reconstruction.** Grade factors rest on a
  lag-2 DGCIS unit-value ratio published months after the fact; on the 9-trade book the grade-spread bucket is
  **+₹103.3 m** against an LME-flat bucket of **−₹29.9 m**. What that does **not** mean is that most of the profit
  is the reconstruction: re-running on the point-in-time mix moves ₹140 m between (0) and (c) and changes the
  book's P&L by **zero rupees** at the window end and at the horizon (§13.6), because the grade factor enters only
  the replacement-value mark, never a contracted price. It is the **attribution split** that is a reconstruction,
  not the result — so read `attribution_daily_grade_pit.csv` beside the base file whenever you quote (0) or (c),
  and note that the grade factor *does* bind Phase 1's eligibility and Phase 2's purchase prices, where it is a
  real exposure.
* **Bucket (d) is a hindsight-calibrated reconstruction** of freight levels, and once a fixture is booked a CFR
  cargo carries no freight price risk at all (design D12), so the book's freight sensitivity is small *by design*.
* **A zero residual proves the arithmetic is closed, not that the model is right.** The split between factors
  depends on the documented swap order: cross-effects sit in the factor that moves later.
* **Forward curves are linear cash→3M and flat beyond**, MTM is undiscounted, and MCX settles at the proxy close
  with no SPAN, no daily price-limit locks and no MCX-vs-LME close-time gap. The near-month proxy moved −12.0 % on
  08-Mar-2022 against a 9 % maximum slab: a real position would have been limit-locked.
* **The adverse-event windows were drawn after the fact** to report what the book went through. They describe this
  simulated book's behaviour, not a realised 2022 loss.

---

## 11. Deviations from the design, and why

### 11.1 The shared library lives in `desk/mtm/`, not `desk/book/`

Design §9.2 puts the pure valuation library inside `desk/book/`, and CONTRACTS §7a.4 names
`desk.book.valuation.revalue_book` as the Phase 4 entry point. Phase 2 and Phase 3 were built **concurrently** by
different owners, and `desk/book/` belongs to Phase 2. Putting the engine there would have meant two owners writing
one package. Everything therefore lives in `desk/mtm/`, and the Phase 4 API is
**`desk.mtm.valuation.revalue_book(book, H, t, shocks, extra_events, mcx_hold_basis)`** with the signature the
design specifies. `desk/book/schema.py` (the ticket grammar) is imported, not duplicated.

### 11.2 The Phase 1 reconciliation is run against recomputed parity, and has two tolerances

Design §5.3 asks for `R` to equal Phase 1's components to ₹0.01. Two things stand in the way and both are
published rather than absorbed:

1. `parity_weekly.csv` rounds every INR column to 2 dp, so four rounded components cannot reconcile to a paisa.
   The control therefore **recomputes** Phase 1 in-process (`parity_model.compute(parity_model.build_inputs())`),
   which compares the two *formulas* on the same register and the same panel — the tie the design actually claims.
2. The panel rounds `usdinr_fwd_1m` to 4 dp, so `R` computed from a live CIP forward differs from Phase 1 by up to
   about 0.25 ₹/MT on a $2,500 cargo. The engine uses the CIP forward (it keeps the block decomposition clean and
   makes FX bumps exact) and publishes **two** controls: the exact one on the panel column
   (`replacement_vs_p1_panelfx_max_abs`, 1.2e-10 ₹/MT) and the CIP one with a stated 0.50 ₹/MT tolerance.

### 11.3 Two design gaps the controls caught on the real book

Both were found by `ledger_identity_max_abs` the first time the engine ran against Phase 2's book, and both are
fixed in `lifecycle.py`:

1. **The final invoice cannot precede the joint survey.** Design §4.1 dates it `roll_bd(pricing_end, lag)` while
   §4.3 fixes the amount at `max(pricing_end, survey known)`. On T08 (40-day USEC transit, June B/L) the survey
   lands 2022-08-09 and the M+1 final invoice 2022-08-05, so the amount fixed **after** it settled and the mark
   and the ledger stopped agreeing by ₹4.1 m. The final invoice now settles at `max(pricing_end + lag, survey)`: a
   seller cannot invoice a final *weight* before the out-turn is agreed.
2. **An event is known no later than the day it bites.** T07 dates a buyer payment delay `known_date`
   2022-09-26 against a contractual due date of 2022-09-15. Taken literally the engine showed the receivable as
   collected for eleven days and then un-collected it — an ₹89.6 m ledger break. The effective known date is now
   `min(known_date, the milestone the event moves)`: a desk learns a payment has not arrived on the day it was
   due. The same rule applies to dwell events against the release date.

A build-time assertion now rejects **any** flow whose `fixing_date` is after its `settle_date`, so this class of
defect cannot recur silently.

### 11.4 The design §14 parameters are served from code until `config/params/book.yaml` exists

`config/params/book.yaml` is Phase 2's file (design §14) and was not present when this engine was built.
`desk.mtm.constants.param(key, date)` reads the register first and falls back to the §14 table — value, unit, flag,
justification and verification status copied verbatim — only when the key is absent. Every fallback actually used is
recorded and written into `pnl_controls.csv` as an `INFO` row naming the key, the value and the source, so a code
default can never be mistaken for a registered assumption. When `book.yaml` lands the register wins automatically
and the INFO rows disappear, with no code change. Nine keys are currently served this way:
`lc_sight_payment_lag_days`, `lc_presentation_period_days`, `lc_amount_tolerance_frac`, `survey_lag_days`,
`boe_lag_days`, `final_invoice_lag_bdays`, `claim_settle_lag_days`, `mcx_slippage_ticks`, `mcx_txn_cost_frac`.

### 11.5 `trade_cashflows.csv` ownership

Design §9.1 assigns this file to Phase 2 with Phase 3 reconciling; the Phase 3 brief assigns it to Phase 3. The
engine writes it with a `written_by = P3` column. If a file already exists at that path **without** that marker it
is treated as Phase 2's: the engine writes `trade_cashflows_p3.csv` beside it and prints the
`cashflow_reconciliation_vs_p2` gap instead of overwriting.

### 11.6 Smaller calls

* **MCX slippage is its own flow.** The design's catalogue folds execution slippage into the fill price used for
  the transaction charge, which would make slippage free. Variation margin runs settle-to-settle (so
  `Σ VM = lots x lot_kg x (F_exit − F_entry)`, asserted in the tests) and `MCX_SLIPPAGE` carries the execution cost
  explicitly, routed to `new_deal` or, for a roll, to (g).
* **Day one of a tranche is margined against the entry settle**, exactly as design §4.3 says. Its value is zero by
  construction, but because the reference is a historical constant its *derivative* is the position's full delta —
  which is what makes `lme_delta_mcx_mt` and `hedge_ratio_lme_frac` correct on the entry day rather than from the
  day after.
* **The engine's observed MCX price is `theo + basis`, not the rounded panel column.** On a proxy day those are
  the same formula and differ only by the CSV's 4 dp; carrying that rounding into daily variation margin would
  have left a few rupees of un-telescoped initial margin per trade and broken the balance-sheet lifetime-sum
  control.
* **No IGST differential on the final invoice.** The catalogue lists a customs-duty differential only. The IGST
  differential would be a balance-sheet pair netting to zero, so omitting it changes no P&L.
* **Buyer credit-limit utilisation is rebuilt per counterparty** in `events.buyer_exposure`, because
  `book_exposures_daily.csv` is at trade grain and a ticket may sell to two buyers. The limit is checked against
  the **receivable** (invoiced, unpaid), with pre-settlement reported beside it rather than against the line —
  see §13.8. Phase 5 owns the tracker.
* **Both hedge ratios are blanked, not clipped, when their denominator is negligible** (§13.8). The floors are
  named constants sized to the smallest position the desk could trade — one MCX lot, USD 100k.
* **`_diff` sorts its keys.** Set iteration order over strings depends on `PYTHONHASHSEED`, which changed the order
  floats were summed and flipped `0.0` to `-0.0` in the CSV between runs. CONTRACTS §1.5 asks for byte-identical
  re-runs, so the sort is load-bearing.

---

## 12. Tests

`tests/test_mtm_curves.py`, `test_mtm_engine.py`, `test_mtm_synthetic.py`, `test_mtm_events.py`.

* **Curves and calendar** — following-roll over the 02/03-Jun and 29-Aug LME holidays; the contract-month
  resolution of the 31-Aug panel slot versus the DIRECT 30-Aug expiry; flat extrapolation beyond 3M; `fx_x` equals
  the panel's own CIP column; the MCX theo replicates the panel on every 2022 day; the proxy basis is identically
  zero; one lot is 5.3–5.6 LME-equivalent tonnes; `R` reconciles to Phase 1 and excludes finance; the
  point-in-time guard raises.
* **Engine (example book)** — residual ≤ ₹1; buckets + residual = daily P&L; legs sum to the trade row; `BOOK` rows
  sum the trades; `cum P&L = realised + funding + Σ mtm` every day on **both** paths; daily P&L is the first
  difference; final cumulative P&L is the sum of all cashflows; BS flows net to zero; day one is entirely
  `new_deal`; (b) is zero; every cashflow settles inside the horizon; VM telescopes to the settle difference and IM
  returns at exit; `mtm_daily` legs reconcile; exposure deltas predict a small revaluation; two independent runs
  are byte-identical; the full run fits the 60 s budget; `trade_cashflows` reconciles to the ledger.
* **Synthetic market** — zero-move day leaves only carry; a 100 % forward on the payable's own value date is flat
  in (e) and (g) and costs exactly `notional × K`; `new_deal` on a forward is exactly the bank margin; an MCX short
  sized on the LME-equivalent delta nets out in (a); every bucket is linear in size; **a planted hidden input is
  caught by the ₹1 residual**; `revalue_book` broadcasts over Monte Carlo paths; stress events only enter through
  the API; a CFR cargo has no freight exposure.
* **Events** — the three windows are pinned to the dates in §6, including the 10-return versus 9-return
  off-by-one; the E3 window cannot start before the void-call report; freight fell on both lanes; every
  hypothetical-stress row is labelled; removing the forwards costs exactly the forward legs plus their funding;
  a block that did not move contributes nothing; the mirror produces a non-zero basis and the PIT grade variant
  still reconciles.
* **Integration on the real book** (`tests/test_mtm_integration.py`, 26 tests) — the engine's controller checks run
  against `config/trades.yaml` rather than the fixtures: every ticket still eligible; residual, identity, legs and
  book rows; **final P&L = Σ cashflows + funding**, summed from the published cashflow table rather than from the
  daily ledger; MCX leg P&L = Σ variation margin + charges, per trade; variation margin telescopes and initial
  margin comes back; every forward settles inside the horizon and its P&L equals its settlement cash; exposures
  additive and signed as CONTRACTS §7a.4 declares; the net MCX book never long; funding counted exactly once;
  buyer limits checked against the receivable so Phase 2 and Phase 3 agree; the published `pnl_controls.csv` names
  every required check and none fails.

---

## 13. Results — the real book

Nine tickets, **14,350 MT in 656 containers**, first trade 2022-03-08, last cashflow 2022-10-24, horizon
2022-10-31. Every number below comes from `outputs/tables/attribution_daily.csv` and is reproducible with the
command in §1. ₹1 crore = ₹10 m.

### 13.1 Book P&L

| | ₹ crore | ₹ | ₹/MT |
|---|---|---|---|
| cumulative P&L at `WINDOW_END` (2022-08-31) | **20.02** | 200,172,812 | 13,950 |
| … of which still **unrealised** at the window end | 32.99 | 329,903,051 | — |
| cumulative P&L at `HORIZON_END` (2022-10-31), all positions closed | **19.79** | **197,910,352** | **13,792** |

The window-end figure is *higher* than the final one because three tickets were still open on 31 August and the
last ₹2.3 m of the book's life (September–October) is net carry and the buyer's late payment. The unrealised
₹330.0 m at the window end is T08 (₹266.5 m), T07 (₹89.6 m) and T09 (−₹26.3 m) — receivables and an unfixed
MCX-average sale, not open metal: **`terminal_mtm_abs` is 0.00 for every trade at the horizon.**

### 13.2 Attribution by factor

Lifetime, book level. Buckets are exactly `desk.reporting.style.PNL_BUCKETS`, they sum to the total, and the
residual is **0.00** on every trade-day (control tolerance ₹1; the worst in-memory value is 1.9e-7).

| Bucket | Lifetime ₹ crore | In-window (≤ 2022-08-31) ₹ crore | Share of gross |
|---|---|---|---|
| (0) `new_deal` — deal margin at inception | **+16.85** | +16.85 | the book |
| (a) `lme_flat` | −2.99 | −2.99 | |
| (b) `cross_exchange_basis` | **0.00** | 0.00 | zero **by construction** (§13.6) |
| (c) `grade_spread` | **+10.33** | +10.33 | the largest market bucket (§13.5) |
| (d) `freight` | +0.12 | +0.12 | small **by design** (D12) |
| (e) `fx` | +1.17 | +1.18 | |
| (f) `demurrage_penalty` | +0.15 | +0.21 | |
| (g) `roll_term_structure` | −5.84 | −5.68 | funding −3.06 of it |
| `residual` | 0.00 | 0.00 | |
| **total** | **+19.79** | **+20.02** | |

Chart: `outputs/charts/p3_attribution_waterfall_book.png`, and one per trade.

Reading it: **85 % of the result is `new_deal`** — margin the desk locked when it signed each purchase and sale,
not market direction. The market added ₹2.94 crore net, and did it by nearly cancelling a −₹2.99 crore flat-price
loss and a −₹5.84 crore carry cost against a +₹10.33 crore grade-spread gain. Bucket (g) is dominated by the
funding accrual: **−₹3.06 crore of the −₹5.84 crore is interest on the desk's own dated cash balance** at
`wc_rate_inr_pa`, on a book whose cash balance reached **−₹116.4 crore on 2022-07-20**.

### 13.3 Per trade

| Trade | Grade / lane | Trade date | MT | Cum P&L at window end ₹cr | of which unrealised ₹cr | **Final P&L ₹cr** | **₹/MT** |
|---|---|---|---|---|---|---|---|
| T01 | zorba / USEC_MUN | 2022-03-08 | 2,520 | 5.70 | 0.00 | 5.70 | 22,627 |
| **T02** | tense / JEA_NSA | 2022-03-11 | 1,200 | 5.05 | 0.00 | **5.05** | **42,122** |
| T03 | taint_tabor / JEA_NSA | 2022-03-23 | 1,200 | 2.82 | 0.00 | 2.82 | 23,493 |
| T04 | taint_tabor / USEC_MUN | 2022-04-06 | 1,260 | 0.92 | 0.00 | 0.92 | 7,339 |
| T05 | tense / USEC_MUN | 2022-04-21 | 2,100 | 3.42 | 0.00 | 3.42 | 16,284 |
| T06 | zorba / JEA_NSA | 2022-05-10 | 1,300 | 0.87 | 0.00 | 0.87 | 6,656 |
| T07 | tense / USEC_MUN | 2022-05-25 | 1,890 | 0.66 | 8.96 | 0.56 | 2,954 |
| **T08** | tense / USEC_MUN | 2022-06-08 | 1,680 | −0.50 | 26.65 | **−0.68** | **−4,054** |
| T09 | tense / JEA_NSA | 2022-08-03 | 1,200 | 1.07 | −2.63 | 1.13 | 9,401 |
| **BOOK** | | | **14,350** | **20.02** | **32.99** | **19.79** | **13,792** |

Bucket split per trade, lifetime, ₹ crore:

| Trade | new_deal | lme_flat | basis | grade_spread | freight | fx | demurrage | roll/carry | total |
|---|---|---|---|---|---|---|---|---|---|
| T01 | 2.33 | −1.18 | 0.00 | 4.79 | 0.10 | −0.11 | 0.00 | −0.23 | 5.70 |
| T02 | 3.80 | 0.65 | 0.00 | 0.00 | 0.00 | 0.33 | 0.00 | 0.28 | 5.05 |
| T03 | 1.31 | −0.58 | 0.00 | 2.13 | 0.00 | 0.03 | 0.00 | −0.07 | 2.82 |
| T04 | 0.41 | −2.15 | 0.00 | 2.67 | −0.00 | 0.29 | 0.00 | −0.30 | 0.92 |
| T05 | 4.55 | −0.13 | 0.00 | 0.00 | 0.00 | 0.16 | 0.00 | −1.16 | 3.42 |
| T06 | 0.40 | −0.56 | 0.00 | 1.01 | 0.00 | −0.05 | 0.00 | 0.06 | 0.87 |
| T07 | 1.18 | 0.89 | 0.00 | 0.74 | 0.02 | 0.06 | 0.07 | −2.41 | 0.56 |
| T08 | 1.91 | −0.86 | 0.00 | −1.09 | 0.00 | 0.44 | 0.07 | −1.15 | −0.68 |
| T09 | 0.97 | 0.92 | 0.00 | 0.07 | 0.00 | 0.02 | 0.00 | −0.86 | 1.13 |

**Best trade — T02, +₹42,122/MT.** A CFR Jebel Ali tense ticket bought on 2022-03-11 on an LME cash average at
0.638 and sold on an MCX average, i.e. **floating in and floating out**, with a 1.00 hedge ratio on the residual.
It carries no grade-spread exposure at all (both legs are formula-priced) and no flat-price risk to speak of; its
₹3.80 crore of `new_deal` is almost the whole result, and the +₹0.65 crore of (a) and +₹0.28 crore of (g) come from
the gap between the purchase and sale pricing windows. It is the cleanest structure on the book and it earned the
most per tonne — which is the point worth making in an interview: **the money was in the structure, not the view.**

**Worst trade — T08, −₹4,054/MT.** Bought 2022-06-08 on an LME cash average at 0.782 (so the purchase price fell
with the market, but the desk's *cost* fell only as fast as the formula), sold on an MCX average whose window had
to be pushed to 10–22 August because the buyer's line was full until T05 settled. The result: −₹1.09 crore of
grade spread (the only negative on the book — the modelled scrap discount *widened* over this ticket's life),
−₹0.86 crore of flat price, and −₹1.15 crore of carry on a 40-day USEC lane with a late sale. It is the trade the
credit constraint made late, and the lateness cost roughly what the ticket earned at inception.

### 13.4 Equity curve

`outputs/charts/p3_equity_curve.png` — cumulative book P&L split into realised cash (including funding) and the
unrealised mark, with the Mar–Aug window shaded and the derived event windows annotated.

| Landmark | Date | ₹ crore |
|---|---|---|
| first day | 2022-03-08 | +0.11 |
| minimum | 2022-03-10 | **−0.34** |
| end March | 2022-03-31 | +5.74 |
| end April | 2022-04-29 | +17.70 |
| **peak** | **2022-06-09** | **+21.97** |
| end July | 2022-07-29 | +18.82 |
| window end | 2022-08-31 | +20.02 |
| horizon | 2022-10-31 | +19.79 |
| best single day | 2022-04-21 | +5.18 (T05 contracted) |
| worst single day | 2022-03-14 | −0.83 |
| maximum drawdown | trough 2022-08-08 | **−4.40** |

The curve is a staircase, not a trend: it steps up when a ticket is contracted and drifts between. That is what a
physical book should look like, and it is the visual argument that this is a margin business rather than a
directional one.

### 13.5 Does the P&L make sense against Phase 1?

Phase 1's `net_arb_inr_t` is the *whole* theoretical arbitrage in an open week. The desk's sale rule deliberately
takes about half of it (`replacement + 0.50 × (netback − replacement)`), because the arb is dominated by
`domestic_anchor_premium_inr_t`, an ASSUMPTION with an evidence range of −52k to +13k. So the right comparison is
against **half** the Phase 1 arb, and the gap after that is market movement between contracting the purchase and
contracting the sale:

| Trade | P1 net arb ₹/MT | × MT, half of it ₹cr | `new_deal` booked ₹cr | `new_deal` ₹/MT | market after inception ₹cr |
|---|---|---|---|---|---|
| T01 | 49,904 | 6.29 | 2.33 | 9,242 | +3.37 |
| T02 | 63,523 | 3.81 | 3.80 | 31,648 | +1.26 |
| T03 | 43,205 | 2.59 | 1.31 | 10,903 | +1.51 |
| T04 | 36,623 | 2.31 | 0.41 | 3,225 | +0.52 |
| T05 | 42,670 | 4.48 | 4.55 | 21,658 | −1.13 |
| T06 | 12,842 | 0.83 | 0.40 | 3,076 | +0.47 |
| T07 | 22,935 | 2.17 | 1.18 | 6,247 | −0.62 |
| T08 | 14,383 | 1.21 | 1.91 | 11,348 | −2.59 |
| T09 | 15,206 | 0.91 | 0.97 | 8,111 | +0.15 |
| **book** | | **24.60** | **16.85** | **11,742** | **+2.94** |

The pattern is entirely explained by **how long each ticket stayed unsold**:

| Trade | days from purchase to first sale | LME cash over that gap | `new_deal` as a share of half the arb |
|---|---|---|---|
| T02, T05 | 0 | 0.0 % | 100 %, 102 % |
| T09 | 23 | +3.8 % | 107 % |
| T06 | 22 | +0.9 % | 48 % |
| T03 | 34 | −12.9 % | 50 % |
| T01, T04 | 48 | −11.7 %, −16.3 % | 37 %, 18 % |
| T07, T08 | 62 | −13.9 %, −10.0 % | 54 %, 158 % |

Every ticket contracted on both sides the same day books essentially the whole half-arb. Every ticket that carried
unsold cargo into the crash books less, and the difference reappears in (a) and (c) rather than going missing.
**The book is short a lag, not short a model.** T08 is the exception in the other direction — its `new_deal` is
158 % of half the arb because its purchase was a floating LME average struck after the market had already fallen —
and it is also the only losing trade, which is the same fact seen twice. Nothing in this table is evidence of a
modelling gap; it is the cost of the desk's own sale timing, visible because `new_deal` is dated at the contract
rather than spread over the trade.

### 13.6 Sensitivities, clearly labelled

Neither of these is base P&L (CONTRACTS §7.5, design D13).

**MCX mirror — the basis the base run cannot see.** Base runs value MCX at the panel's import-parity proxy, so
bucket (b) is **identically zero by construction**. Re-running the whole book on the third-party mirror series
(`data/interim`, itself a PROXY) sizes what a real basis might be worth:

| Lifetime, book, ₹ crore | base (panel proxy) | MCX mirror | difference |
|---|---|---|---|
| (b) `cross_exchange_basis` | **0.00** | **−1.17** | −1.17 |
| (g) `roll_term_structure` | −5.84 | −2.78 | +3.06 |
| (0) `new_deal` | 16.85 | 16.80 | −0.05 |
| every other bucket | | unchanged to the rupee | 0.00 |
| **total** | **19.79** | **21.63** | **+1.84** |

Per trade the basis ranges from **−₹1.84 crore (T01)** to **+₹1.79 crore (T05)**: the book-level −₹1.17 crore is a
large amount of netting, and a reader should treat the per-trade figures, not the total, as the measure of basis
risk. The offsetting +₹3.06 crore in (g) is the mirror's different carry shape, not a second source of profit.
**This does not validate the proxy.** The mirror's provenance cannot be checked against MCX's bhavcopy and its
second-month series is partly stale; it is one PROXY measured against another.

**Point-in-time grade mix — and the result that matters most for honesty.** Grade factors are a lag-2 DGCIS
unit-value reconstruction published months after the fact, and bucket (c) is the largest market bucket in the book.
Re-running with `grade_factor_mix_pit` (the mix a 2022 desk could actually have known):

| Lifetime, book, ₹ crore | base (lag-2 mix) | PIT mix | difference |
|---|---|---|---|
| (0) `new_deal` | 16.85 | 29.67 | **+12.82** |
| (c) `grade_spread` | **+10.33** | **−3.68** | **−14.01** |
| (a) `lme_flat` | −2.99 | −1.55 | +1.44 |
| (e) `fx` | 1.17 | 0.74 | −0.43 |
| (g) `roll_term_structure` | −5.84 | −5.69 | +0.15 |
| **total** | **19.79** | **19.79** | **0.00** |

**The grade-factor reconstruction moves ₹140 m between two buckets and changes the book's P&L by zero rupees** —
at the horizon and at the window end, to the rupee, on every trade. That is not a coincidence: the grade factor
enters only the *replacement-value mark* on unsold cargo (design D5), while every purchase price is either fixed in
the ticket or an LME-average formula, and every sale is fixed in rupees or an MCX average. It therefore changes
*when* the engine says the money was made, not *how much*. Intra-life the two runs do diverge — up to **₹122.5 m**
of cumulative P&L on 2022-06-15, when the book was carrying the most unsold cargo.

The correct conclusion is narrower and stronger than "most of the profit is a reconstruction": the *attribution
split* between (0) and (c) is a reconstruction and should be read with `attribution_daily_grade_pit.csv` beside it;
the *result* is not. What the grade factor does bind is Phase 2's purchase prices and eligibility — that is a
Phase 1/Phase 2 exposure, documented there.

### 13.7 Controls on this book

`desk.mtm.run.main()` raises unless every row of `outputs/tables/pnl_controls.csv` passes. On the real book:

| Check | Tolerance | Worst value |
|---|---|---|
| `residual_max_abs` (per trade-day) | ₹1 | 1.9e-7 |
| `ledger_identity_max_abs` (valuation vs cash ledger, per trade) | ₹0.01 | 1.8e-7 |
| `final_pnl_vs_cashflows` (cum P&L at horizon vs Σ P&L cashflows + funding, per trade) | ₹0.01 | 1.5e-7 |
| `bs_flows_lifetime_sum` (per trade) | ₹0.01 | 0.00 |
| `terminal_mtm_abs` (per trade at `HORIZON_END`) | ₹0.01 | 0.00 |
| `proxy_basis_max_abs` | 1e-3 ₹/kg | 5.0e-5 |
| `replacement_vs_p1_panelfx_max_abs` | ₹0.01/MT | 1.2e-10 |
| `replacement_vs_p1_max_abs` (CIP forward) | ₹0.50/MT | 0.23 |
| `cashflow_reconciliation_vs_p2` | — | INFO: P3 owns the file (§11.5) |
| `book_param_fallback` | — | 9 INFO rows, one per design §14 key served from code (§11.4) |

Two further ties a product controller would want, checked in `tests/test_mtm_integration.py` rather than in the
controls file because they are cross-table:

* **hedge P&L = margin cash.** The MCX legs' lifetime P&L is **+₹165,971,097**; the variation margin those same
  hedges posted is **+₹172,402,091**, less **₹6,430,995** of transaction charges and slippage. The two tie to
  **₹0.08 across the whole book** (CSV rounding at 2 dp on ~350 rows).
* **forward P&L = settlement cash.** The FX legs' lifetime P&L equals the realised settlement of the 25 forward
  lines, **+₹13,970,390**, per trade.

**Funding is counted once.** There is exactly one `FUNDING` leg per trade, worth **−₹31,283,768** over the book
(−₹651,323 of it routed to (f) as interest on an overdue receivable, the rest to (g)); it appears in no cashflow
row, and `funding_on_margin_inr` in `mcx_variation_margin.csv` is a **memo column** on the margin table, not a
second accrual — the margin cash is already inside the trade's dated cash balance that the one accrual runs on.

### 13.8 Two reporting calls made during integration

1. **Buyer credit is measured against the receivable, not against everything contracted.** The first version summed
   receivable *and* pre-settlement against `credit_limit_inr` and reported a 2.58× breach over 46 days — which
   counted a ₹220.3 m advance the buyer had **not yet paid** as credit the desk had extended. CONTRACTS §7a.4
   already separates the two; the limit check now uses `buyer_receivable_inr` and agrees with Phase 2's P04 rule
   (peak **83.4 %**, **no breach on any day**). The contracted measure is still published beside it. Full story in
   `docs/31_adverse_events.md` §3.4.
2. **`hedge_ratio_fx_frac` is unstable for this book, and is disclosed rather than smoothed.** Design D5 marks
   unsold cargo at import replacement value, which is **long USD**, against a USD payable that is short USD, so the
   net physical USD delta oscillates through zero while a full forward hedge sits on top of it. Unguarded, the
   published ratio printed values from **−10,716 to +434**. The engine now blanks both hedge ratios when the
   denominator is below the smallest position the desk could trade (one MCX lot of metal, USD 100k of currency —
   `HEDGE_RATIO_MIN_PHYSICAL_MT` / `_USD`), but the guard only stops a division by nearly zero: on 37 of 164 book
   days the ratio is still above 5 in absolute value, because the measure itself is not meaningful here. **Read
   `fx_delta_forwards_usd` against `fx_delta_physical_usd` directly**, and the two offset ratios in
   `adverse_event_2_usdinr.csv`. The metal ratio has no such problem: median **0.903**, against the desk's stated
   0.90 naked-long ratio.
