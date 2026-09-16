# 30 — Daily MTM & P&L attribution engine (methods)

> **ACADEMIC SIMULATION — not actual trades.** Every counterparty, vessel, forwarder, bank and operational outcome
> behind these numbers is fictional and labelled (SIM). This page documents *how the engine works*; the numbers it
> quotes come from the checked-in book and are reproducible with the command in §1.
>
> **And the decision inputs are weaker than the arithmetic.** The engine's own reconciliation is exact to the
> paisa, but that says nothing about the inputs it reconciles. No price in this book was ever quoted by a
> counterparty: both legs of every ticket are set by the desk's own rules off the desk's own parity model
> (§13.5, §13.9). The freight levels and the grade mix are hindsight reconstructions (`docs/10_parity_model.md`
> §12), the MCX series is a duty-parity proxy with no basis and no curve (§2.1), and the eligibility calendar that
> chose the trade dates rests on the same grade reconstruction (`docs/10_parity_model.md` §6.1). Read §10 and §13.9
> before quoting any number on this page as a result.

Component 3 of `docs/spec/MASTER_SPEC_V3.md` (Table 5). Implements `docs/design/30_position_model.md` against
`CONTRACTS.md` §7 and §7a. Deviations from the design are listed and justified in §11.

**The results are in §13**, on the real nine-ticket book. The adverse events have their own page,
`docs/31_adverse_events.md`. The one-line answer: the book makes **₹192.1 m over 14,350 MT (₹13,384/MT)** at the
2022-10-31 horizon, of which ₹165.2 m is deal margin booked **at contract dates** — ₹94.3 m on the nine purchase
trade dates and ₹70.9 m on later sale, fixture and hedge dates (§13.2) — and ₹26.8 m is what the market then did to
it.

**That number is conditional on one ASSUMPTION, and it is not sign-robust to it.** `new_deal` is not a quote from a
counterparty — it is the desk's own sale rule applied to the desk's own parity model, and the rule is driven by
`domestic_anchor_premium_inr_t` = −9,000 ₹/t (ASSUMPTION, verification PENDING: no 2022 ADC12/LM6 India price
series was retrievable), whose registered grid spans ₹68,000/t (−55,000 … +13,000). Re-priced through that grid the
same nine tickets make anywhere from **−₹10.5 crore to +₹33.4 crore**: the book **loses money at two of the four
registered values** and breaks even at an anchor premium of about **−₹38,700/t** (§13.9,
`pnl_sensitivity_sign_robustness.csv`). Every other registered band leaves the sign positive.

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
about 45 s (peak memory ≈ 0.6 GB) including the seven counterfactual re-runs per variant, both sensitivity variants,
the 24 re-pricing cases of §13.9 and the charts; a re-run is byte-identical.

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
visible only in the `_mcx_mirror` sensitivity, and those files are never base P&L. §13.11 publishes it as a
two-sided per-ticket range with the loss case shown, and tests the unit-beta assumption the hedge sizing rests on.

**A second consequence, in the same formula:** `dte(M2) > dte(M1)` always, so **M2 > M1 on every panel day** and
the proxy curve is in permanent contango. There is no calendar-spread risk in a base run, and every short roll is a
gain by construction. §13.10 splits each executed roll into that INR carry and the (identically zero) term
structure, so the two are never quoted as one number.

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
| joint survey (quality known) | `roll(arrival_cal + survey_lag_days)`, **or a typed `QualityEvent.known_date`** when the ticket states one (clamped to the arrival) |
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

**The two scenarios in `trade_cashflows.csv` answer different questions, and one of them invites a misreading.**
`REALISED` is what actually settled: every flow at its own settle date, USD at the spot that fixed there.
`PLANNED_AT_TRADE_DATE` is the set of flows **already contracted on the trade date**, valued on trade-date CIP
forwards — there is no hindsight in it (none of its USD rows uses a realised spot). It is **not an expected P&L**:
a sale contracted later is simply absent, so summing its `PNL` rows gives a large negative number for every ticket
sold after the trade date — T01 **−₹497.3 m** planned against **+₹70.9 m** realised, T07 −₹334.7 m against +₹7.9 m.
Only T02 and T05 contract both legs on the trade date, and only there is the planned total a meaningful figure —
**+₹38,922,624 and +₹47,622,723, exactly their day-one `new_deal`** — which is precisely what invites the
misreading everywhere else.
Every row now carries a `scenario_note` column saying so.

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

**Two bucket names are narrower than what the buckets hold**, and `desk.reporting.style.FACTOR_LABELS` now says so
on every chart and sheet:

* **(f) is "everything that becomes known today", not "demurrage and penalties".** Step 6 swaps the events-as-of
  date, so it books demurrage and claims *and* the quantity restatement of the inventory mark (row above). It is
  also the **inception** value of those events: an event's later market drift leaves (f) and flows into (a), (e)
  and (g), so **(f) is not the lifetime cost of the events**. For that, read `event_cost_lifetime_*` in
  `adverse_events_summary.csv` — on this book (f) is −₹0.52 crore while the lifetime event cost is −₹0.94 crore,
  and the two answer different questions. (f) also excludes a quality discount passed through to the buyer: that
  is priced into the sale contract and lands in (0) on the sale date, which is why the lifetime counterfactual, not
  (f), is the event's gross cost.
* **(g) is "carry, roll and cross-terms", not "roll yield".** It is the last block swapped, so besides the funding
  accrual (−₹3.26 crore of the −₹5.66 crore by design, CONTRACTS §7a.1.2) and the executed roll spreads it
  absorbs every cross-term the documented order pushes to the end — above all ΔLME × ΔFX on USD-priced physical.
  A reader who takes (g) as a roll P&L gets it backwards: §13.10 shows the executed rolls were worth **+₹0.84
  crore**, all of it the proxy's INR carry, against a (g) of −₹5.66 crore.

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
| the inventory mark restated from B/L weight `q_bl` to accepted weight `q_acc` when a survey lands | (f) | it is part of the same events-as-of swap: step 6 books **everything** that becomes known that day, quantity restatements included |
| buyer payment delay | (f), through `acc_overdue` only | undiscounted MTM does not change when a dated receipt moves; only its funding does |
| settlement of a flow on its own settle day | 0 | the estimate at `(M_t, tau = t)` equals the realised value; the one-day tenor difference goes to (g) |

### 4.3 What the residual is a control *for* — and what it is not

`Σ buckets` comes from the chain. The day's **total** is computed independently from the cash ledger:
`Δ[realised P&L + funding + Σ mtm]`, where the realised amounts are accumulated day by day at each flow's own
settle date and the mtm terms come from a pure state. `residual = total − Σ buckets`, and `|residual| ≤ ₹1` per
trade-day. On the real 9-trade book the worst residual is **1.9e-7 ₹** (float64 noise at ₹10⁸ magnitudes).

**What it proves.** The eight-step chain telescopes by construction — `Σ buckets = V8(t) − V0(t) + accruals`, and
`V0(t) = V8(t−)` — so the residual reduces algebraically to

```
residual(t) == Δ[ ledger realised P&L − the clock-valued realised P&L the chain carries ]
```

i.e. it is exactly the **settled-flow convergence** control: every flow's estimate must equal the amount it
settles for on its own settle date, must stay frozen afterwards, and the funding accrual must be booked once. That
is a real sign-off, it is the class `tests/test_mtm_synthetic.py` plants (a flow that keeps marking after it has
settled), and it **has already earned its keep**: it caught two real defects the first time the engine met the
Phase 2 book (§11.3).

**What it does not prove.** An earlier version of this page claimed the residual catches "any hidden input: a
parameter read at a date other than the clock, history read beyond the clock, contract logic touching the wall
calendar". It does not, and the claim is withdrawn. A dated market number read from `HistoryView` instead of
through `MarketState` never reaches the ledger either, so it telescopes into the chain's last movers — (g), (f)
and (0) — and the residual does not move. Reproduced on this book by monkeypatching a real, dated
`HV.freight_usd_t(tau, lane) × 1000` into `curves.replacement_value`: **+₹106,947,170 moved into `new_deal`,
−₹105,966,563 out of (g), −₹980,608 into (f); factor (d) did not change by one paisa; the book total was
identical to the rupee — and the worst residual stayed at 2.4e-7.** A control that survives that is not a
general-purpose hidden-input detector.

The guards against *that* class are different ones, and they are what a reader should rely on:

| Guard | What it catches |
|---|---|
| the `_UNASSIGNED` assertion in `desk.mtm.state` | a `MarketState` **field** added without a bucket (it raises at import) |
| `MarketHistory.view(tau)` / `LookaheadError` | history read **beyond the clock** |
| `test_freight_bucket_moves_only_with_panel_freight` (§12) | factor (d) moving on a day the panel's freight did not, and factor (d) never moving at all |
| code review | a market number read through `HistoryView` rather than `MarketState` — there is no automatic guard for this, and saying so is the point of this paragraph |

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

**The sign *convention* is not a sign *invariant*, and the difference bites at trade scope.** At `scope = book`
this book is long metal or flat, its MCX book only ever offsets (`lme_delta_physical_mt ≥ 0`,
`lme_delta_mcx_mt ≤ 0`, `mcx_lots_open ≤ 0`) and a regression test asserts it on every day. At `scope = trade`
**any of the three can flip, and does**: T02 buys on a floating `LME_M1_AVG` (May) while its MCX-average sale
prices off between 19 and 29 April, so for a few weeks the desk is net **short** metal on that ticket and
legitimately hedges by **buying** 145 lots. Those rows are economically correct. Phase 4 must **read the sign, not
assume it** — coding to "physical delta ≥ 0" would mis-sign T02 for 26 panel days.

Three definitions worth knowing before reading the columns:

* **`purchase_priced_frac` / `sale_priced_frac` at BOOK scope are tonnage-weighted**, not a mean of tickets: they
  read "share of the book that is priced", and weighting by each ticket's contracted tonnage over the trades on
  the book that day is what makes that true. They are the only pair of columns where the `BOOK` row is not the sum
  of the trade rows. (An unweighted mean, which is what an earlier build published, differed by up to 0.177 —
  0.500 against a tonnage-weighted 0.677 on 2022-03-11.) Within a ticket, `sale_priced_frac` still averages over
  *sales*, not tonnes, because a ticket's sales are of similar size; `purchase_priced_frac` is tonnage-weighted
  over lots.
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
| E1 LME crash | argmax cash → argmin after it, **the argmin bounded at `WINDOW_END`** | 2022-03-07 ($3,984.5) → 2022-07-15 ($2,320.5), **−41.8 %** |
| E1 crash fortnight | the **10-trading-day return** window (11 observations) with the most negative cash return | 2022-04-22 ($3,244.0) → 2022-05-09 ($2,708.0), **−16.5 %** |
| — memo, 9 returns | the 10-*observation* reading | 2022-03-07 → 2022-03-18, −15.2 % |
| E2 INR depreciation | the pair `i < j` maximising `usdinr_j / usdinr_i` | 2022-04-05 (75.3350) → 2022-07-14 (80.0352), **+6.24 %** (first-to-last memo +5.07 %) |
| E3 logistics + credit | earliest E3 effective known date → last affected settle | per book; the cited void-call trigger is dated 2022-07-27 |

The off-by-one is pinned deliberately: "10 panel days" must mean 10 *returns*. Both readings are defensible; the
contract is the 10-return one and the other is published as a memo so the convention is visible.

**One narrowing of the contract, recorded here.** CONTRACTS §7a.3 says "argmax cash → argmin after it" with no
bound; `desk.mtm.events` takes the argmin on `[start, WINDOW_END]`, which is printed in the `rule` column of
`adverse_event_windows.csv`. It matters: cash fell further after the reporting window, to **$2,080.0 on
2022-09-28, −47.8 % from the high**, and that low is inside the engine horizon. E1's −41.8 % is the
reporting-window drawdown (`docs/31_adverse_events.md` §1.1). Either CONTRACTS §7a.3 should record the bound or
the rule should reach `HORIZON_END`; until it is amended, this is a deviation and §11.7 lists it as one.

**Method.** Isolated impact = the sum of the relevant buckets over the window's *returns* (days in `(start, end]`),
split by leg group, **plus** counterfactual re-runs of the same book with one component removed: `without mcx`,
`without fx_forward`, `without the simulated events`, `with the freight fixture undone`, and — because event 3 has
three separable causes — `without the dwell`, `without the payment delay` and `without the quality claims`
individually. A hedge benefit is therefore the difference between two runs of one engine — margin-funding
difference included — not a comparison of two models. The three event-3 components are additive to within
₹5,031 of interaction, and that interaction is reported rather than allocated.

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
| `trade_cashflows.csv` | trade × leg × cashflow, two scenarios (`PLANNED_AT_TRADE_DATE`, `REALISED`). Written by `run._write_cashflows` — an earlier build computed the frame and never wrote it, leaving a stale file; `tests/test_mtm_integration.py` now writes it into a temp directory and ties it out |
| `mtm_daily.csv` | date × trade × leg (funding is a leg with `mtm_inr = 0`) |
| `attribution_daily.csv` | date × trade (+ a `BOOK` row): `PNL_BUCKETS` + `residual` + totals. **Filter `trade_id != "BOOK"` before grouping by date**: the file has no `scope` column (CONTRACTS §7a.3 fixes its columns), and summing without the filter double-counts the book exactly |
| `attribution_leg_daily.csv` | date × trade × leg, same buckets (sparse: a leg that moved nothing has no row) |
| `book_exposures_daily.csv` | date × scope (`trade` / `book`). `buyer_id` is a compound string on a two-buyer ticket (T01): use the next two files for anything per counterparty |
| `buyer_credit_exposure_by_trade_daily.csv` | date × trade × buyer: receivable, pre-settlement and contracted INR against that buyer's limit — one buyer per row |
| `buyer_credit_exposure_daily.csv` | date × buyer: the same summed across trades, the grain the E3 limit test reads (asserted equal to the long table regrouped) |
| `new_deal_timing.csv` | trade (+ `BOOK`): bucket (0) booked on the purchase trade date vs on later contract dates, by leg family (§13.2) |
| `mcx_variation_margin.csv` | date × hedge line |
| `adverse_event_windows.csv` | one row per derived window |
| `adverse_event_1_lme_crash{,_daily}.csv` | E1 summary and daily |
| `adverse_event_2_usdinr{,_daily}.csv` | E2 summary and daily |
| `adverse_event_3_logistics_credit.csv` | E3 summary |
| `adverse_event_3_freight_stress_hypothetical.csv` | labelled stress, date × trade |
| `adverse_events_summary.csv` | the three event tables in one scan |
| `pnl_sensitivity_pricing.csv` | case × trade: the book **re-priced** through the desk's own S1/S2 rules under each registered band value (§13.9) |
| `pnl_sensitivity_summary.csv` | case: the same at book level, with every bucket, the Δ vs base and a sign flag |
| `pnl_sensitivity_sign_robustness.csv` | band: P&L range, slope, linearity check and **break-even value** per registered band, plus an all-bands row (§13.9) |
| `mcx_roll_carry.csv` (+ `_mcx_mirror`) | roll: each executed roll split into the proxy's INR carry and term structure, with the LME cash–3M spread beside it and the same roll re-priced on a parity curve carrying the LME's own slope (`lme_curve_*`: rate carry vs metal carry) (§13.10) |
| `mcx_basis_risk.csv` | metric × scope: the LME–MCX basis as a two-sided per-ticket range, plus the unit-beta test (§13.11) |
| `pnl_controls.csv` | date × check: value, tolerance, status |

**Memo columns — never sum.** Three published columns are daily **stock** memos that sit beside P&L columns and
will produce nonsense if a pivot adds them up:

| Column | File | What it is | What summing it gives |
|---|---|---|---|
| `fixture_vs_market_inr` | `mtm_daily.csv` | what the market would charge today for freight already fixed (design D12). Correctly excluded from `mtm_inr`. | −₹1,264,803,260 over 960 rows — **six times the whole book's P&L** |
| `funding_on_margin_inr` | `mcx_variation_margin.csv` | a memo of the carry on margin cash, already inside the one funding accrual | double-counted funding |
| `im_required_inr` | `mcx_variation_margin.csv` | margin **posted and outstanding**, a stock | a meaningless running total; take the daily `sum` then the `max` |

`fixture_vs_market_inr` carries no in-file marker, because CONTRACTS §7a.3 fixes the column name. Renaming it to
`fixture_vs_market_stock_inr` needs a contract amendment and is listed in §11.7 as a change to make.

Charts (all through `desk.reporting.style.save_fig`, so every one carries the SIM label):
`p3_equity_curve`, `p3_attribution_waterfall_{T01…T09,book}`, `p3_adverse_events`, `p3_mcx_vm_schedule`,
`p3_event1_hedged_vs_unhedged`, `p3_event2_fx_offset`.

**Two presentation traps in `mtm_daily.csv` and `attribution_leg_daily.csv`.** The `FUNDING` leg carries
`status = settled`, `settle_date = HORIZON_END` and its whole accrual inside `realised_cum_inr`, so a reader summing
`realised_cum_inr` picks up ₹32.6 m of "realised cash" that never moved on any date: the identity the engine closes is
**realised + funding accrual + MTM** (CONTRACTS §7.3 states it without the funding term; §11.7 lists the amendment),
and `trade_cashflows.csv` correctly carries no funding row. And `attribution_leg_daily.csv` has no `residual` column
and omits legs on days they moved nothing (483 trade-days have no leg rows, all with zero P&L): the residual is a
trade-grain control, and Σ legs equals the trade row to CSV rounding.

**The workbook.** `outputs/excel/Metals_Desk_Master.xlsx` (built by `desk.excel.build`, stage P3) is the Excel half
of MASTER_SPEC Components 1–3, formula-driven from these same tables; `outputs/excel/reconciliation.json` records its
tie-out to the CSVs.

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
| `final_pnl_vs_cashflows` (cum P&L at horizon vs Σ P&L cashflows + funding accrual, per trade) | ₹0.01 | 1.8e-7 |
| `proxy_basis_max_abs` (panel MCX vs parity theo) | 1e-3 ₹/kg | 5.0e-5 |
| `bs_flows_lifetime_sum` (per trade) | ₹0.01 | 0.0 |
| `terminal_mtm_abs` (per trade at `HORIZON_END`) | ₹0.01 | 0.0 |
| **`replacement_vs_p1_panelfx_max_abs`** — the row that meets CONTRACTS §7a.1.3's ₹0.01 letter | ₹0.01/MT | 1.2e-10 |
| `replacement_vs_p1_max_abs` (CIP forward) — memo, looser by design (§11.2) | ₹0.50/MT | 0.23 |
| `sensitivity_base_repricing_vs_book` | ₹0.01 | 0.00 |
| `roll_carry_metal_component_max_abs` | ₹0.01 | 6.3e-8 |
| `cashflow_reconciliation_vs_p2` | ₹0.01 when it applies | INFO: P3 owns the file (§11.5) |
| `book_param_fallback` | — | INFO rows, one per design §14 key served from code (§11.4) |

`final_pnl_vs_cashflows` states CONTRACTS §7.3 as an **independent** sum: it re-adds every P&L flow straight off
the schedule plus the funding accrual and lands on the trade's final cumulative P&L, bypassing the daily ledger
that `ledger_identity_max_abs` walks. Together the two close both paths.

`sensitivity_base_repricing_vs_book` is what makes §13.9 a sensitivity rather than a second model: re-deriving the
base case through the same S1/S2 rules, holding each leg's negotiation delta, must reproduce the published book's
cumulative P&L to the paisa. `roll_carry_metal_component_max_abs` asserts that on a `PANEL_PROXY` day every rupee
of roll P&L is the INR carry the proxy formula creates, i.e. that §13.10's split has not drifted from the panel.

**Five of the six §7a.3 controls are live; the sixth is structurally inert.**
`cashflow_reconciliation_vs_p2` is a row in the file rather than a console line, so a missing check cannot be
mistaken for a passing one — but while Phase 3 both writes and reads `trade_cashflows.csv` there is nothing
independent to reconcile against, and a control that can never fail is not a control. It carries `INFO` saying so.
Two ways out, neither of them Phase 3's to take: amend CONTRACTS §6 to assign the file to P3 and drop the control,
or have Phase 2 publish a minimal independent cashflow schedule. If a file appears at that path **without**
`written_by = P3`, the engine already writes `trade_cashflows_p3.csv` beside it and the row becomes a PASS/FAIL on
the maximum per-trade realised-INR gap (§11.5).

---

## 9. Provenance of everything the engine reads

| Input | Flag | Where it bites |
|---|---|---|
| LME official cash and 3M (Westmetall) | **DIRECT** | fixings, curve, MCX parity, M+1 averages |
| CBIC notified customs rate; BCD / SWS / IGST; MCX contract specs, expiries and position limit; SBI LC fee card; FX no-documentation limit | **DIRECT** | duty base, flows, validation |
| `max_domestic_credit_days` (45) — a desk policy cap, **not** the MSMED Act, which binds a buyer paying a registered micro/small supplier and so reaches no sale here | **ASSUMPTION** | sale credit terms (validation) |
| USD/INR (ECB cross); INR and USD 3M rates; CIP forwards; the usance benchmark | **PROXY** | all FX, forwards, MCX parity, usance interest |
| MCX panel series (import-parity proxy) | **PROXY** | hedges and MCX-linked sales; factor (b) ≡ 0 by construction |
| MCX third-party mirror | **PROXY** | the basis sensitivity only, never base P&L |
| Grade factors (lag-2 mix + differentials) | **ASSUMPTION** (hindsight) | contract factors, the replacement mark, factor (c) |
| Freight levels / shape | **ASSUMPTION / PROXY** | unbooked FOB freight, factor (d), the fixture memo |
| Payloads, transit and clearance days, free days, the slabbed detention schedule, the rejected-box hold (45 d) and re-export cost (USD 3,000), port charges, PSIC, WC rate path, usance spread, confirmation fee, margin used | **ASSUMPTION / PROXY** | dates, flows, funding, margin, the T08 radiation event |
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

* **Bucket (0) `new_deal` is 86 % of the result, and it is not a traded margin.** It is `q × (P_contract − R)`:
  the desk's *typed* sale price minus the desk's *own* replacement mark. The sale price is not a quote — Phase 2
  sets it by rule at `replacement + 0.50 × (netback − replacement)`, and `netback` is dominated by
  `domestic_anchor_premium_inr_t`, an **ASSUMPTION** (verification PENDING) whose own registered grid spans
  −55,000 to +13,000 ₹/t (`docs/20_trade_book.md` §10). Unlike the grade reconstruction below, **this one does not
  net to zero**: re-pricing the book through that band moves the result from **−₹10.5 crore to +₹33.4 crore**
  (§13.9). **Neither the size nor the sign of the headline survives the band**: the book loses money at −55,000 and
  −52,000 and breaks even at about −38,700 ₹/t. Both bounds of the pricing rule — the replacement mark (lag-2 grade
  factors) and the netback (this premium) — are PENDING-verification reconstructions, and nobody ever quoted this
  desk a price.
* **Bucket (0) is booked at contract dates, not "at inception".** 57 % of it lands on the purchase trade dates and
  43 % on later sale, fixture and hedge dates, at a market that had already moved (§13.2, `new_deal_timing.csv`);
  the chart label now reads "(0) Deal margin at contract dates".
* **Bucket (b) is empty by construction.** MCX is a duty-parity proxy in base runs; the real LME–MCX basis appears
  only in the mirror sensitivity, whose own provenance cannot be checked against MCX's bhavcopy. That sensitivity
  finishes **above** the base book, which is a two-sided risk drawn once, not a better result — read it as the
  per-ticket range, the ±₹1.9 crore of (b)+(g) moved jointly, and the rejected unit-beta test in §13.11.
* **The mirror moves attribution, not risk.** Every delta column of `book_exposures_daily_mcx_mirror.csv` is
  identical to the base file (max |difference| 0.0), because the engine holds the basis as an additive state and
  prices MCX at **unit beta** to LME and USD/INR in both runs — an assumption the mirror rejects (beta 0.45, §13.11).
  Phase 4 must not treat the mirror as a risk sensitivity, and must not build FX VaR on the netted `fx_delta_usd`
  alone: it averages −USD 0.42 m on book days, while the physical-plus-forwards delta averages **+USD 4.19 m**
  (max +USD 13.3 m) against an MCX leg of −USD 4.61 m whose offset is exactly what the unit-beta assumption
  asserts. No beta-≠-1 exposure variant is published; that is an open item for Phase 4.
* **There is no curve risk in a base run.** The MCX proxy is in contango on every panel day by construction, so
  all 13 rolls are gains and the entire ₹0.84 crore of roll P&L is INR carry (§13.10). Re-priced on a parity curve
  that carries the LME's own cash–3M slope and CIP rupee points, the same rolls make ₹0.73 crore — ₹0.59 crore of
  rupee-over-dollar rate carry and ₹0.14 crore of metal contango — and the one roll dealt in LME backwardation (T07,
  20-Jul) loses ₹0.33 crore of metal carry. So the proxy overstates roll P&L by ₹0.11 crore here, and the rate
  differential, not the metal curve, is what keeps a short roll positive. A ticket rationale that frames rolling
  as a cost is describing the metal half of a market this engine cannot represent.
* **Bucket (c) is the largest market bucket in this book and it is a reconstruction — of the result, not only of
  the split.** Grade factors rest on a lag-2 DGCIS unit-value ratio published months after the fact; on the
  9-trade book the grade-spread bucket is **+₹103.3 m** against an LME-flat bucket of **−₹30.0 m**. Re-running with
  the point-in-time mix as a **re-mark** moves ₹140 m between (0) and (c) and changes the book's P&L by zero
  rupees (§13.6) — but that is because a re-mark leaves every typed price alone, and **the same reconstruction set
  those prices**: the purchase bids are trade-date parity (grade factor × LME) less a discount, and the sale
  prices are half the gap between a replacement mark and a netback that both move with it. Re-priced through the
  point-in-time mix on both legs, the book makes **₹9.7 crore instead of ₹19.2 crore** (§13.9); the lag-1 and
  lag-3 publications of the same hindsight mix give ₹18.7 and ₹22.0 crore, and the grade differentials at their
  evidence quartiles ₹13.4–23.1 crore. So the correct statement is the stronger one: the grade reconstruction is a
  **result exposure**, the published `_grade_pit` re-mark understates it, and §13.6's "zero rupees" applies only
  to the attribution split.
* **Bucket (d) is a hindsight-calibrated reconstruction** of freight levels, and once a fixture is booked a CFR
  cargo carries no freight price risk at all (design D12), so the book's freight sensitivity is small *by design*.
  The stop-loss layer on the three FOB tickets is unfalsifiable on this panel (`docs/31_adverse_events.md` §3.5).
* **There is no funding, facility or position constraint anywhere in Phase 3.** The book's own minimum cash
  balance is **−₹1,159,856,633 on 2022-07-20** on top of ₹95.8 m of initial margin, against ₹192.1 m of P&L. That
  is an output, not a limit the book was tested against; Phase 4/5 own `risk.yaml`.
* **A zero residual proves the arithmetic is closed, not that the model is right** — and it proves less than the
  first version of this page claimed. It is a settled-flow convergence control, and a dated market input that
  bypasses `MarketState` telescopes into (g)/(f)/(0) without moving it at all (§4.3). The split between factors
  also depends on the documented swap order: cross-effects sit in the factor that moves later.
* **Two bucket names are narrower than their contents.** (f) holds everything that becomes known that day,
  including quantity restatements, and is the events' **inception** value rather than their lifetime cost; (g)
  holds the funding accrual and every late cross-term, not a roll yield (§4.1).
* **Forward curves are linear cash→3M and flat beyond**, MTM is undiscounted, and MCX settles at the proxy close
  with no SPAN, no daily price-limit locks and no MCX-vs-LME close-time gap. The near-month proxy moved −12.0 % on
  08-Mar-2022 against a 9 % maximum slab: a real contract would have traded only at the limit, if at all.
* **Operational events are costed, but as floors.** Detention is slabbed (carrier detention and CFS ground rent
  combined, not separate tariffs); the rejected T08 box pays 45 days of hold and a USD 3,000 re-export at the
  desk's cost first, recovered at 0.6; decontamination or disposal of a genuinely contaminated box is not modelled.
  At 0.0 and 1.0 recovery the book moves by −₹5.7 m / +₹3.8 m (§13.9). No lot's bill of lading slips a month;
  `docs/20_trade_book.md` §6.5 sizes what that would have been worth.
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
  `book_exposures_daily.csv` is at trade grain and a ticket may sell to two buyers (its `buyer_id` is then a
  compound string no tracker can group). Both grains are now published — `buyer_credit_exposure_by_trade_daily.csv`
  (date × trade × buyer) and `buyer_credit_exposure_daily.csv` (date × buyer) — and a test asserts the first
  regroups exactly to the second. The limit is checked against the **receivable** (invoiced, unpaid), with
  pre-settlement reported beside it rather than against the line — see §13.8. Phase 5 owns the tracker.
* **Both hedge ratios are blanked, not clipped, when their denominator is negligible** (§13.8). The floors are
  named constants sized to the smallest position the desk could trade — one MCX lot, USD 100k.
* **`_diff` sorts its keys.** Set iteration order over strings depends on `PYTHONHASHSEED`, which changed the order
  floats were summed and flipped `0.0` to `-0.0` in the CSV between runs. CONTRACTS §1.5 asks for byte-identical
  re-runs, so the sort is load-bearing.
* **A typed `QualityEvent.known_date` beats the derived survey date** (CONTRACTS §7a.2, added during the review).
  The normal case is `arrival + survey_lag_days` and no ticket in this book types a date, so nothing moves; but a
  late, disputed or re-sampled survey is an executed fact and now has somewhere to live, and the date is
  load-bearing — it sets the claim-settlement date and the window in which a ticket is over-hedged against a
  weight it has not agreed yet. A typed date earlier than the arrival is clamped to the arrival: a survey cannot
  precede the cargo.
* **A cancelled FX forward is closed out at the CIP mid**, to its original value date, with no unwind spread —
  while the same line paid `fx_forward_bank_margin_inr` (₹0.10/USD) on the way in. The spread is therefore
  one-sided in the desk's favour on any cancelled line. The current book contains **no** cancelled line, so this
  costs the published P&L nothing; if one is added, either charge the margin on the unwind too (the conservative
  choice, one line in `lifecycle._fx_flows`) or quote the benefit.
* **The SPA quantity tolerance and the LC amount tolerance are different terms, and now distinguishable.**
  `lifecycle._lc_flows` sizes the credit on `purchase.spa.quantity_tolerance_frac` when a ticket states one (T01,
  T03 at 0.05) and on the registered `lc_amount_tolerance_frac` (UCP 600 art. 30, 0.10) when it states none. The
  schema field is `None` when omitted, and the engine tests `is None` rather than falsiness, so a deliberately
  strict 0.00 SPA now sizes a strict credit instead of silently inheriting 10 % (review fix; no ticket in this book
  types 0.00, so no published fee moved).
* **Detention is charged up the registered slabs** (`lifecycle.detention_usd`, the same schedule as
  `desk.book.validate.demurrage_usd`, asserted equal in `tests/test_mtm_engine.py`). The first build charged every
  chargeable day at the first-slab rate, which understated any long dwell. The four keys price carrier detention and
  CFS ground rent **combined**; they are not separate tariffs with separate free periods.
* **A rejected box is not free.** It pays no duty and no port charges, but it is held for `rejected_box_hold_days`
  (45, ASSUMPTION) accruing slabbed detention and then re-exported at `rejected_box_reexport_cost_usd_per_box`
  (USD 3,000, ASSUMPTION): a `REJECTED_BOX_COST` flow the desk pays first (USD 5,730 on T08's one box), claimed back
  at the event's `claim_recovery_frac`. Decontamination or disposal is not modelled.
* **`claim_recovery_frac` now bites on a formula purchase.** A formula purchase nets the goods deduction off the
  final invoice, so the engine used to give it 100 % recovery whatever the ticket typed. The claim flow now hands
  back the unaccepted `(1 − recovery) × P_final × claim_mt` (and recovers the rejected-box costs at the same
  fraction), so T08's typed 0.6 is effective.

### 11.7 Contract amendments this build needs (not Phase 3's edit to make)

| CONTRACTS clause | What the engine does | Why |
|---|---|---|
| §6 output ownership | `trade_cashflows.csv` carries `written_by = P3` on every row | the Phase 3 brief assigns it to P3; §11.5 handles a P2 file if one appears. Amend §6, or the sixth §7a.3 control can never fire (§8). |
| §7a.4 Phase 4 entry point | `desk.mtm.valuation.revalue_book` | §11.1: `desk/book/` belongs to Phase 2 |
| §7a.1.3 replacement tolerance | ₹0.50/MT on the CIP variant, ₹0.01/MT on `_panelfx` | §11.2: the panel rounds `usdinr_fwd_1m` to 4 dp. Measured worst 0.227 ₹/MT on 14,350 MT ≈ ₹3,300 of book value — immaterial, but it is a deviation from a stated tolerance and is named here rather than absorbed. The alternative is a Phase 0 change (publish the forward at more decimals). |
| §7a.3 E1 window rule | the argmin is bounded at `WINDOW_END` | §6: the post-window low is $2,080.0 on 2022-09-28, −47.8 %, inside the engine horizon |
| §7a.3 `mtm_daily.csv` columns | `fixture_vs_market_inr` is a stock memo with no in-file marker | §7: summing it gives −₹1.26 bn. Renaming it `fixture_vs_market_stock_inr` needs the column list amended. |
| §7.3 ledger identity | the identity closed is `cum P&L = realised + funding accrual + MTM`, and the `FUNDING` leg carries its accrual in `realised_cum_inr` | §7 presentation trap: amend §7.3 to name the funding term, or give the leg its own status and an `accrued_cum_inr` column |
| §7a.3 `attribution_daily.csv` columns | no `scope` column; the `BOOK` row sits beside trade rows | §7: summing without filtering double-counts. Adding `scope` (as `book_exposures_daily.csv` has) needs the column list amended |

---

## 12. Tests

`tests/test_mtm_curves.py`, `test_mtm_engine.py`, `test_mtm_synthetic.py`, `test_mtm_events.py`,
`test_mtm_sensitivity.py`, `test_mtm_integration.py`.

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
* **Result sensitivities** (`test_mtm_sensitivity.py`) — every registered band value becomes a case; re-deriving
  the **base** case through S1/S2 reproduces every typed price and the published book P&L to the paisa; the anchor
  premium moves the book in the right direction and by more than ₹10 crore; a smaller desk share lowers the
  result; the point-in-time grade mix **re-priced** differs from the base while the published `_grade_pit`
  **re-mark** is zero to the paisa; the panel proxy is in contango on every window day and every roll is pure INR
  carry (metal component < 1e-9 ₹/kg) while the mirror's is not; the basis sensitivity publishes a loss case as
  well as a gain case; `unit_beta_test` returns exactly 1 against the panel itself and rejects 1 against the
  mirror; and `sensitivity.reference` still ties to Phase 2's `trade_book.csv` parity columns.
* **Added in the Phase 1–3 review** — `trade_cashflows.csv` is actually written by `run._write_cashflows` and ties
  out to the engine frame, and the published file matches the current engine; the per-counterparty exposure table
  has no compound buyer ids and regroups exactly to the per-buyer table; `new_deal_timing` adds back to bucket (0)
  per trade; the `lme_curve_*` roll columns decompose exactly and price a backwardation roll's metal carry as a cost;
  the grade-differential quartile cases exist and the `lag2` grade source rebuilt as mix + differential reproduces
  the base grade path; `sign_robustness` reports a break-even inside the band on a synthetic sign flip; and
  (`tests/test_book.py`) P13 fires on a streak claim the tape does not show.
* **Integration on the real book** (`tests/test_mtm_integration.py`, 32 tests) — the engine's controller checks run
  against `config/trades.yaml` rather than the fixtures: every ticket still eligible; residual, identity, legs and
  book rows; **final P&L = Σ cashflows + funding**, summed from the published cashflow table rather than from the
  daily ledger; MCX leg P&L = Σ variation margin + charges, per trade; variation margin telescopes and initial
  margin comes back; every forward settles inside the horizon and its P&L equals its settlement cash; exposures
  additive and signed as CONTRACTS §7a.4 declares; the net MCX book never long; funding counted exactly once;
  buyer limits checked against the receivable, and neither phase's own limit test finding a breach (the two phases
  measure different things and publish different peaks, §13.8); the published `pnl_controls.csv` names
  every required check and none fails; **the declared exposure signs are asserted at BOOK scope and asserted to
  flip at trade scope on T02**, so a Phase 4 author who codes to the book-scope claim fails a test rather than
  mis-signing a ticket; and **factor (d) moves when and only when the panel's freight column moves** — the
  complementary control the residual cannot give (§4.3).

---

## 13. Results — the real book

Nine tickets, **14,350 MT in 656 containers**, first trade 2022-03-08, last cashflow 2022-10-24, horizon
2022-10-31. Every number below comes from `outputs/tables/attribution_daily.csv` (and the tables named beside it)
and is reproducible with the command in §1. ₹1 crore = ₹10 m. **Every rupee of it is conditional on the ASSUMPTION
bands in §13.9; read that section before quoting any number here.**

### 13.1 Book P&L

| | ₹ crore | ₹ | ₹/MT |
|---|---|---|---|
| cumulative P&L at `WINDOW_END` (2022-08-31) | **19.59** | 195,936,980 | 13,654 |
| … of which still **unrealised** at the window end | 32.27 | 322,710,795 | — |
| cumulative P&L at `HORIZON_END` (2022-10-31), all positions closed | **19.21** | **192,054,771** | **13,384** |

The window-end figure is *higher* than the final one because three tickets were still open on 31 August and the
last ₹3.9 m of the book's life (September–October) is net carry, the out-turn claims, the rejected T08 box's hold
and re-export, and the buyer's late payment. The unrealised ₹322.7 m at the window end is T08 (₹260.9 m), T07
(₹89.2 m) and T09 (−₹27.4 m) — receivables and an unfixed MCX-average sale, not open metal:
**`terminal_mtm_abs` is 0.00 for every trade at the horizon.**

### 13.2 Attribution by factor

Lifetime, book level. Buckets are exactly `desk.reporting.style.PNL_BUCKETS`, they sum to the total, and the
residual is **0.00** on every trade-day (control tolerance ₹1; the worst in-memory value is 1.9e-7).

| Bucket | Lifetime ₹ crore | In-window (≤ 2022-08-31) ₹ crore | Share of gross |
|---|---|---|---|
| (0) `new_deal` — deal margin **at contract dates** | **+16.52** | +16.52 | 86 % of the result (§13.9) |
| (a) `lme_flat` | −3.00 | −3.00 | |
| (b) `cross_exchange_basis` | **0.00** | 0.00 | zero **by construction** (§13.11) |
| (c) `grade_spread` | **+10.33** | +10.33 | the largest market bucket (§13.6) |
| (d) `freight` | +0.12 | +0.12 | small **by design** (D12) |
| (e) `fx` | +1.41 | +1.42 | |
| (f) `demurrage_penalty` — events known that day | −0.52 | −0.46 | inception value, not lifetime cost (§4.1) |
| (g) `roll_term_structure` — carry, roll and cross-terms | −5.66 | −5.35 | funding −3.20 of it |
| `residual` | 0.00 | 0.00 | |
| **total** | **+19.21** | **+19.59** | |

Chart: `outputs/charts/p3_attribution_waterfall_book.png`, and one per trade.

Reading it: **86 % of the result is `new_deal`** — margin the desk booked when it signed each purchase, sale,
fixture and hedge, not market direction. The market added ₹2.68 crore net, and did it by nearly cancelling a
−₹3.00 crore flat-price loss and a −₹5.66 crore carry cost against a +₹10.33 crore grade-spread gain — the last of
which is a reconstruction (§13.6). Bucket (g) is dominated by the funding accrual: **−₹3.20 crore of the −₹5.66 crore
is interest on the desk's own dated cash balance** at `wc_rate_inr_pa` (the whole accrual is −₹3.26 crore; the
other −₹0.06 crore sits in (f) as interest on an overdue receivable, per CONTRACTS §7a.1.2), on a book whose cash
balance reached **−₹115.99 crore on 2022-07-20**. The executed MCX rolls inside (g) were worth **+₹0.84 crore**,
all of it the proxy's INR carry (§13.10) — (g) is not a roll yield. Bucket (f) is **negative** on this book
(−₹0.52 crore: T07 −₹0.16 crore, T08 −₹0.37 crore); before the review it was +₹0.15 crore, because a rejected box was
free, detention was charged flat and both claims recovered 100 %.

**When bucket (0) was booked** (`new_deal_timing.csv`). The chart label used to say "at inception", and that
overstated how much was locked at signature:

| | ₹ m |
|---|---|
| booked on the nine purchase trade dates | **94.3** (57 %) |
| booked on later contract dates | **70.9** (43 %) |
| … sale contracts, net of the replacement mark they release (2,006.5 − 1,924.2) | 82.3 |
| … MCX execution cost and forward bank margin | −5.5 |
| … LC opening/confirmation fees and other purchase costs dated later | −5.1 |
| … freight fixtures above the index | −0.8 |

Per ticket, T01, T03 and T09 book 92 %, 93 % and 114 % of their `new_deal` after the trade date (T09's day one is
−₹1.3 m: the purchase and its costs came to more than the replacement mark on day one, and the sale three weeks
later made it back), while T02
and T05 — both legs contracted the same day — book all of it on day one. A margin booked on a sale date three to
seven weeks after the purchase was booked at a market that had already moved; it is margin at contract, not margin
locked when the cargo was bought.

### 13.3 Per trade

| Trade | Grade / lane | Trade date | MT | Cum P&L at window end ₹cr | of which unrealised ₹cr | **Final P&L ₹cr** | **₹/MT** |
|---|---|---|---|---|---|---|---|
| T01 | zorba / USEC_MUN | 2022-03-08 | 2,520 | 6.43 | 0.00 | 6.43 | 25,509 |
| **T02** | tense / JEA_NSA | 2022-03-11 | 1,200 | 5.05 | 0.00 | **5.05** | **42,122** |
| T03 | taint_tabor / JEA_NSA | 2022-03-23 | 1,200 | 2.91 | 0.00 | 2.91 | 24,240 |
| T04 | taint_tabor / USEC_MUN | 2022-04-06 | 1,260 | 0.65 | 0.00 | 0.65 | 5,145 |
| T05 | tense / USEC_MUN | 2022-04-21 | 2,100 | 3.37 | 0.00 | 3.37 | 16,025 |
| T06 | zorba / JEA_NSA | 2022-05-10 | 1,300 | 0.86 | 0.00 | 0.86 | 6,630 |
| T07 | tense / USEC_MUN | 2022-05-25 | 1,890 | 0.21 | 8.92 | 0.11 | 561 |
| **T08** | tense / USEC_MUN | 2022-06-08 | 1,680 | −0.83 | 26.09 | **−1.17** | **−6,980** |
| T09 | tense / JEA_NSA | 2022-08-03 | 1,200 | 0.95 | −2.74 | 1.00 | 8,374 |
| **BOOK** | | | **14,350** | **19.59** | **32.27** | **19.21** | **13,384** |

Bucket split per trade, lifetime, ₹ crore:

| Trade | new_deal | lme_flat | basis | grade_spread | freight | fx | events (f) | carry/roll (g) | total |
|---|---|---|---|---|---|---|---|---|---|
| T01 | 2.16 | −1.18 | 0.00 | 4.79 | 0.10 | 0.66 | 0.00 | −0.10 | 6.43 |
| T02 | 3.80 | 0.65 | 0.00 | 0.00 | 0.00 | 0.33 | 0.00 | 0.28 | 5.05 |
| T03 | 1.31 | −0.58 | 0.00 | 2.13 | 0.00 | 0.07 | 0.00 | −0.01 | 2.91 |
| T04 | 0.28 | −2.15 | 0.00 | 2.67 | −0.00 | 0.10 | 0.00 | −0.26 | 0.65 |
| T05 | 4.55 | −0.13 | 0.00 | 0.00 | 0.00 | 0.10 | 0.00 | −1.15 | 3.37 |
| T06 | 0.43 | −0.56 | 0.00 | 1.01 | 0.00 | −0.12 | 0.00 | 0.09 | 0.86 |
| T07 | 1.04 | 0.89 | 0.00 | 0.74 | 0.02 | −0.07 | −0.16 | −2.36 | 0.11 |
| T08 | 2.01 | −0.86 | 0.00 | −1.09 | 0.00 | 0.44 | −0.37 | −1.30 | −1.17 |
| T09 | 0.94 | 0.92 | 0.00 | 0.07 | 0.00 | −0.09 | 0.00 | −0.85 | 1.00 |

**Best trade — T02, +₹42,122/MT.** A CFR Jebel Ali tense ticket bought on 2022-03-11 on an LME cash average at
0.638 and sold on an MCX average, i.e. **floating in and floating out**, with a 1.00 hedge ratio on the residual.
It carries no grade-spread exposure at all (both legs are formula-priced) and no flat-price risk to speak of; its
₹3.80 crore of `new_deal` is almost the whole result, and the +₹0.65 crore of (a) and +₹0.28 crore of (g) come from
the gap between the purchase and sale pricing windows. It is the cleanest structure on the book and it earned the
most per tonne — which is the point worth making in an interview: **the money was in the structure, not the view.**
It is also the most robust ticket in §13.9: positive in every registered case, +₹2.50 crore at the bottom of the
anchor-premium grid.

**Worst trade — T08, −₹6,980/MT.** Bought 2022-06-08 on an LME cash average (so the purchase price fell with the
market, but the desk's *cost* fell only as fast as the formula), sold on an MCX average whose window had to be
pushed to August because the buyer's line was full until T05 settled, and carrying the radiation-portal rejection,
the seven-day void-call arrival delays and a fourteen-day referral dwell on top. The result: −₹1.09 crore of grade
spread (the only negative on the book — the modelled scrap discount *widened* over this ticket's life), −₹0.86 crore
of flat price, −₹0.37 crore of events and −₹1.30 crore of carry on a 40-day USEC lane with a late sale. It is the
trade the credit constraint made late, and the lateness cost more than the ticket earned at contract. T07 is the
other ticket the events hit: +₹0.11 crore, and **negative (−₹0.18 crore) if its quality claim recovers nothing**.

### 13.4 Equity curve

`outputs/charts/p3_equity_curve.png` — cumulative book P&L split into realised cash (including funding) and the
unrealised mark, with the Mar–Aug window shaded and the derived event windows annotated.

| Landmark | Date | ₹ crore |
|---|---|---|
| first day | 2022-03-08 | +0.17 |
| minimum | 2022-03-10 | **+0.16** |
| end March | 2022-03-31 | +6.87 |
| end April | 2022-04-29 | +18.42 |
| **peak** | **2022-06-09** | **+22.49** |
| end July | 2022-07-29 | +18.85 |
| window end | 2022-08-31 | +19.59 |
| horizon | 2022-10-31 | +19.21 |
| best single day | 2022-04-21 | +5.23 (T05 contracted) |
| worst single day | 2022-03-14 | −0.91 |
| maximum drawdown | peak 2022-06-09 → trough 2022-08-08 | **−4.99** |

The curve is a staircase, not a trend: it steps up when a ticket is contracted and drifts between. That is what a
physical book should look like, and it is the visual argument that this is a margin business rather than a
directional one. It is also, read honestly, the shape of a book whose result is set at nine moments by a pricing
rule — which is why §13.9 exists.

### 13.5 Does the P&L make sense against Phase 1?

Phase 1's `net_arb_inr_t` is the *whole* theoretical arbitrage in an open week. The desk's sale rule deliberately
takes about half of it (`replacement + 0.50 × (netback − replacement)`), because the arb is dominated by
`domestic_anchor_premium_inr_t`, an ASSUMPTION with an evidence range of −52k to +13k (grid −55k to +13k). So the
right comparison is against **half** the Phase 1 arb, and the gap after that is market movement between contracting
the purchase and contracting the sale:

| Trade | P1 net arb ₹/MT | × MT, half of it ₹cr | `new_deal` booked ₹cr | `new_deal` ₹/MT | market after contract ₹cr |
|---|---|---|---|---|---|
| T01 | 49,904 | 6.29 | 2.16 | 8,575 | +4.27 |
| T02 | 63,523 | 3.81 | 3.80 | 31,648 | +1.26 |
| T03 | 43,205 | 2.59 | 1.31 | 10,903 | +1.60 |
| T04 | 36,623 | 2.31 | 0.28 | 2,225 | +0.37 |
| T05 | 42,670 | 4.48 | 4.55 | 21,664 | −1.18 |
| T06 | 12,842 | 0.83 | 0.43 | 3,326 | +0.43 |
| T07 | 22,935 | 2.17 | 1.04 | 5,509 | −0.94 |
| T08 | 14,383 | 1.21 | 2.01 | 11,967 | −3.18 |
| T09 | 15,206 | 0.91 | 0.94 | 7,862 | +0.06 |
| **book** | | **24.60** | **16.52** | **11,515** | **+2.68** |

The pattern is largely explained by **how long each ticket stayed unsold**: every ticket contracted on both sides
the same day books essentially the whole half-arb (T02 100 %, T05 102 %, T09 103 %), and every ticket that carried
unsold cargo into the crash books less (T04 12 %, T01 34 %, T07 48 %, T03 50 %, T06 52 %), with the difference
reappearing in (a) and (c) rather than going missing. **The book is short a lag, not short a model.** T08 is the
exception in the other direction — its `new_deal` is 166 % of half the arb because its purchase was a floating LME
average struck after the market had already fallen — and it is also the only losing trade, which is the same fact
seen twice.

What this table does **not** show is that the desk earned half of a real arbitrage. Both bounds of the rule are the
desk's own model: the replacement mark is CONTRACTS §5 arithmetic on a lag-2 grade reconstruction, and the netback
is the same arithmetic plus an anchor premium nobody observed in 2022. Both are PENDING verification. §13.9 prices
that, and finds the sign does not survive.

### 13.6 Sensitivities that re-mark the book

Neither of these is base P&L (CONTRACTS §7.5, design D13). Both are **re-marks**: they change how the engine values
the book, not what the tickets say. §13.9 does the harder thing and changes the prices.

**MCX mirror — the basis the base run cannot see.** Base runs value MCX at the panel's import-parity proxy, so
bucket (b) is **identically zero by construction**. Re-running the whole book on the third-party mirror series
(`data/interim`, itself a PROXY) sizes what a real basis might be worth:

| Lifetime, book, ₹ crore | base (panel proxy) | MCX mirror | difference |
|---|---|---|---|
| (b) `cross_exchange_basis` | **0.00** | **−1.17** | −1.17 |
| (g) carry, roll and cross-terms | −5.66 | −2.59 | +3.07 |
| (0) `new_deal` | 16.52 | 16.47 | −0.05 |
| (f) events | −0.52 | −0.53 | −0.00 (−₹13,966) |
| every other bucket | | unchanged to the rupee | 0.00 |
| **total** | **19.21** | **21.05** | **+1.84** |

The mirror run finishes **above** the base book. **That is not a better result — it is a two-sided risk drawn
once.** The number that moves most is not (b), which the sensitivity exists to expose, but (g): swapping the MCX
series changes the contract-month basis structure the chain holds in (b), and with it the carry and roll terms the
chain assigns to (g) — ₹3.07 crore more in the short book's favour on this draw, of which only ₹0.10 crore is the
executed roll spreads (§13.10). So (b) and (g) have to be read **together**, as a band: §13.11 publishes them jointly per ticket (worst −₹1.92 crore, best +₹1.58 crore) and
at book level as **±₹1.89 crore**, with the adverse mirror image of the favourable draw. **None of this validates
the proxy:** the mirror's provenance cannot be checked against MCX's bhavcopy; it is one PROXY measured against
another.

**Point-in-time grade mix, as a re-mark.** Grade factors are a lag-2 DGCIS unit-value reconstruction published
months after the fact, and bucket (c) is the largest market bucket in the book. Re-running with
`grade_factor_mix_pit` (the mix a 2022 desk could actually have known) while leaving every typed price alone:

| Lifetime, book, ₹ crore | base (lag-2 mix) | PIT mix, re-mark | difference |
|---|---|---|---|
| (0) `new_deal` | 16.52 | 29.35 | **+12.83** |
| (a) `lme_flat` | −3.00 | −1.56 | +1.44 |
| (c) `grade_spread` | **+10.33** | **−3.68** | **−14.01** |
| (d) `freight` | 0.12 | 0.12 | 0.00 |
| (e) `fx` | 1.41 | 0.98 | −0.43 |
| (f) `demurrage_penalty` | −0.52 | −0.50 | +0.03 |
| (g) `roll_term_structure` | −5.66 | −5.51 | +0.15 |
| **total** | **19.21** | **19.21** | **0.00** |

**As a re-mark, the grade reconstruction moves ₹140.1 m out of (c) — ₹128.3 m of it into (0) and the rest into (a)
+₹14.4 m, (g) +₹1.5 m and (f) +₹0.3 m, less (e) −₹4.3 m — and changes the book's P&L by zero rupees**, at the horizon
and at the window end, on every trade. That is not a coincidence: the grade factor enters only the
*replacement-value mark* on unsold cargo (design D5), while every typed price is held fixed. Intra-life the two runs
do diverge — up to **₹122.5 m** of cumulative P&L on 2022-06-15, when the book was carrying the most unsold cargo.

**Do not stop there.** The sentence an earlier version of this page ended on — "it is the attribution split that is
a reconstruction, not the result" — is **wrong as stated**, and it is withdrawn. The same reconstruction that
moves the mark also *set the typed prices*: every fixed purchase is trade-date parity (grade factor × LME 3M) less
a discount, every formula purchase is a grade factor less a giveaway, and every fixed sale is half the gap between
a replacement mark and a netback that both move with it. A re-mark holds all of that constant and therefore
**understates** the exposure. The honest version is a **re-pricing**, and it is §13.9: on the point-in-time mix,
re-derived through the same rules on both legs, the book makes **₹9.73 crore instead of ₹19.21 crore**.

### 13.7 Controls on this book

`desk.mtm.run.main()` raises unless every row of `outputs/tables/pnl_controls.csv` passes. On the real book:

| Check | Tolerance | Worst value |
|---|---|---|
| `residual_max_abs` (per trade-day) | ₹1 | 1.9e-7 |
| `ledger_identity_max_abs` (valuation vs cash ledger, per trade) | ₹0.01 | 1.8e-7 |
| `final_pnl_vs_cashflows` (cum P&L at horizon vs Σ P&L cashflows + funding, per trade) | ₹0.01 | 1.8e-7 |
| `bs_flows_lifetime_sum` (per trade) | ₹0.01 | 0.00 |
| `terminal_mtm_abs` (per trade at `HORIZON_END`) | ₹0.01 | 0.00 |
| `proxy_basis_max_abs` | 1e-3 ₹/kg | 5.0e-5 |
| `replacement_vs_p1_panelfx_max_abs` (CONTRACTS §7a.1.3's ₹0.01) | ₹0.01/MT | 1.2e-10 |
| `replacement_vs_p1_max_abs` (CIP forward, memo) | ₹0.50/MT | 0.23 |
| `sensitivity_base_repricing_vs_book` | ₹0.01 | 0.00 |
| `roll_carry_metal_component_max_abs` | ₹0.01 | 6.3e-8 |
| `cashflow_reconciliation_vs_p2` | — | INFO: P3 owns the file (§8, §11.5) |
| `book_param_fallback` | — | 9 INFO rows, one per design §14 key served from code (§11.4) |

Ties a product controller would want, checked in `tests/test_mtm_integration.py` and re-derived independently from
the published CSVs during the review:

* **cumulative P&L = realised + funding + MTM**, per trade, every day, and **final P&L = Σ P&L cashflows + funding**
  per trade from `trade_cashflows.csv` (the file is now actually written; §7).
* **hedge P&L = margin cash.** The MCX legs' lifetime P&L is **+₹165,971,097**; the variation margin those same
  hedges posted is **+₹172,402,091**, less **₹6,430,995** of transaction charges and slippage. The two tie to
  **₹0.12 across the whole book** — that is the published CSVs at 2 dp over ~350 rows; in memory the tie is exact
  to float noise.
* **forward P&L = settlement cash.** The FX legs' lifetime P&L equals the realised settlement of the 25 forward
  lines, **+₹19,557,673**, per trade, and no forward is open at the horizon.

**Funding is counted once.** There is exactly one `FUNDING` leg per trade, worth **−₹32,627,695** over the book
(−₹648,389 of it routed to (f) as interest on an overdue receivable, the rest to (g)); it appears in no cashflow
row, and `funding_on_margin_inr` in `mcx_variation_margin.csv` is a **memo column** on the margin table, not a
second accrual — the margin cash is already inside the trade's dated cash balance that the one accrual runs on.

### 13.8 Two reporting calls made during integration

1. **Buyer credit is measured against the receivable, not against everything contracted.** The first version summed
   receivable *and* pre-settlement against `credit_limit_inr` and reported a 2.57× breach. That counted a ₹219.3 m
   advance the buyer had **not yet paid** as credit the desk had extended. CONTRACTS §7a.4 already separates the
   two; the limit check now uses `buyer_receivable_inr` (peak **83.4 %**, BUY_JNPT_01, no breach on any day). The
   contracted measure is still published beside it, and it is **not** the same measure Phase 2's P04 rule uses —
   P04 checks receivable plus uncovered contracted sales **at each booking** (peak 93 %, BUY_MUN_01). The two peaks
   are different numbers for different quantities, not an agreement; each page quotes its own denominator
   (`docs/31_adverse_events.md` §3.4), and per-buyer figures can now be reproduced from
   `buyer_credit_exposure_by_trade_daily.csv`.
2. **`hedge_ratio_fx_frac` is unstable for this book, and is disclosed rather than smoothed.** Design D5 marks
   unsold cargo at import replacement value, which is **long USD**, against a USD payable that is short USD, so the
   net physical USD delta oscillates through zero (book range −USD 3.45 m to +USD 9.48 m) while a full forward
   hedge sits on top of it. Unguarded, the published ratio printed values from −10,716 to +434. The engine now
   blanks both hedge ratios when the denominator is below the smallest position the desk could trade (one MCX lot
   of metal, USD 100k of currency — `HEDGE_RATIO_MIN_PHYSICAL_MT` / `_USD`), which blanks 14 of 164 book days. On
   the 150 days that remain the ratio still runs from **−14.3 to +49.5** and is above 5 in absolute value on
   **19** of them. **Not all of that is a small-denominator artefact.** On days like 2022-03-14 (physical
   +USD 1.10 m, forwards +USD 5.91 m, ratio −5.4) the denominator is large and the reading is economics: the unsold
   cargo's mark and the forwards bought against its payable are **both long USD**, so the forwards add to the
   book's dollar length until the payable is struck — a hedge-design finding about D5, not noise. Read
   `fx_delta_forwards_usd` against the contracted USD payable (what the forwards were sized on) and against
   `fx_delta_physical_usd` separately, and use the two offset ratios in `adverse_event_2_usdinr.csv` (1.04× against
   the USD cash legs; −2.29× against the net physical including the D5 mark). The metal ratio has no such problem:
   median **0.903**, against the desk's stated 0.90 naked-long ratio.

### 13.9 Is the headline P&L sign-robust? — the re-pricing sensitivities

`outputs/tables/pnl_sensitivity_summary.csv`, `pnl_sensitivity_pricing.csv` and
`pnl_sensitivity_sign_robustness.csv`. **Every row is labelled `SENSITIVITY — not base P&L`.**

§13.6's re-marks answer "what if the engine valued this book differently". They cannot answer the question a reader
actually has, because the sale and purchase prices are *typed* in `config/trades.yaml`: swapping
`domestic_anchor_premium_inr_t` and re-marking changes the P&L by **exactly zero**, since design D5 keeps the
netback out of the inventory mark. But that parameter **set** every typed sale price, through the desk's own rule.

So these cases re-derive the prices and re-run the whole engine. `desk.mtm.sensitivity` applies the same two rules
`docs/20_trade_book.md` states — sale `= replacement + share × (netback − replacement)`, purchase `= trade-date
parity − discount` — under each registered band value, **holding each leg's own negotiation delta constant**, and
runs `engine.run_book` on the rebuilt tickets. The three MCX-average sales (T02, T05, T08; 4,980 MT) are re-priced
through their premium, which was struck to the same rule — an earlier version held those premiums fixed and
silently exempted a third of the book, overstating the bottom of the anchor band by about ₹10 crore. Trade dates,
lots, hedges, events and §5a eligibility are untouched: this is a revaluation of the same decisions, not a
different book. The control `sensitivity_base_repricing_vs_book` asserts that the base case of this machinery
reproduces the published book to the paisa — without that, none of the rest would mean anything.

| Case | What moves | Book P&L ₹cr | Δ vs base ₹cr | ₹/MT | positive? |
|---|---|---|---|---|---|
| **base** (published book) | — | **19.21** | 0.00 | 13,384 | yes |
| `anchor_premium_-55000` | sale rule | **−10.54** | −29.74 | −7,344 | **no** |
| `anchor_premium_-52000` | sale rule | **−8.60** | −27.80 | −5,992 | **no** |
| `anchor_premium_-9000` (base) | sale rule | 19.21 | 0.00 | 13,384 | yes |
| `anchor_premium_+13000` | sale rule | **33.43** | +14.23 | 23,297 | yes |
| `conversion_8000` | sale rule | 21.79 | +2.59 | 15,186 | yes |
| `conversion_18000` | sale rule | 15.33 | −3.88 | 10,680 | yes |
| `conversion_30000` | sale rule | 7.57 | −11.64 | 5,273 | yes |
| `desk_share_0.25` | sale rule | 10.28 | −8.93 | 7,163 | yes |
| `desk_share_0.10` | sale rule | 4.92 | −14.28 | 3,431 | yes |
| `desk_share_0.00` | sale rule | 1.35 | −17.85 | 943 | yes |
| `desk_margin_5000` | sale rule (flat ₹/MT margin over replacement) | 8.54 | −10.66 | 5,952 | yes |
| `desk_margin_8000` | sale rule (flat ₹/MT margin over replacement) | 12.85 | −6.35 | 8,957 | yes |
| `purchase_discount_0` | purchase bid at parity | 18.27 | −0.93 | 12,734 | yes |
| `purchase_discount_30` | purchase bid 30 USD/t under parity | 20.57 | +1.37 | 14,336 | yes |
| **`grade_mix_pit_repriced`** | **both legs + the mark** | **9.73** | **−9.48** | **6,780** | yes |
| `grade_mix_lag1_repriced` | both legs + the mark (lag-1 publication, as hindsight as lag-2) | 18.70 | −0.51 | 13,031 | yes |
| `grade_mix_lag3_repriced` | both legs + the mark (lag-3 publication) | 22.00 | +2.79 | 15,329 | yes |
| `grade_diff_q25_repriced` | both legs + the mark, every differential at its evidence lower quartile | 23.12 | +3.92 | 16,115 | yes |
| `grade_diff_q75_repriced` | both legs + the mark, every differential at its evidence upper quartile | 13.38 | −5.83 | 9,323 | yes |
| `claim_recovery_0.00` (SIM) | both quality events recover nothing | 18.63 | −0.57 | 12,985 | yes |
| `claim_recovery_1.00` (SIM) | both quality events recover in full | 19.59 | +0.38 | 13,649 | yes |
| `grade_mix_pit_remark_only` | the mark only (the §13.6 run) | 19.21 | 0.00 | 13,384 | yes |

**Sign robustness, band by band** (`pnl_sensitivity_sign_robustness.csv`). Book P&L is linear in every numeric band
(the fitted line reproduces every case to the paisa), so each band has a break-even value:

| Band | Registered range | Book P&L range ₹cr | Slope | Break-even value | Inside the band? | Sign-robust? |
|---|---|---|---|---|---|---|
| `domestic_anchor_premium_inr_t` (ASSUMPTION, PENDING) | −55,000 … +13,000 ₹/t | −10.54 … +33.43 | ₹6,466 per ₹/t | **−38,702 ₹/t** | **yes** | **NO** |
| `conversion_cost_inr_t` | 8,000 … 30,000 ₹/t | +7.57 … +21.79 | −₹6,466 per ₹/t | +41,702 ₹/t | no | yes |
| desk share of the arb (S1) | 0.00 … 0.50 | +1.35 … +19.21 | ₹35.7 crore per unit | −0.04 | no | yes |
| flat desk margin | 5,000 … 8,000 ₹/t | +8.54 … +12.85 | ₹14,376 per ₹/t | −941 ₹/t | no | yes |
| purchase discount (S2) | 0 … 30 USD/t | +18.27 … +20.57 | ₹766,391 per USD/t | −238 USD/t | no | yes |
| grade mix (PIT / lag-1 / lag-3, re-priced) | three published variants | +9.73 … +22.00 | — | — | — | yes |
| grade differentials (evidence quartiles, re-priced) | q25 … q75 | +13.38 … +23.12 | — | — | — | yes |
| `claim_recovery_frac` (SIM) | 0.0 … 1.0 | +18.63 … +19.59 | ₹95.3 lakh per unit | −19.5 | no | yes |
| **all registered bands, one at a time** | 24 cases | **−10.54 … +33.43** | | | | **NO** |

**The answer, stated plainly: the headline P&L is not sign-robust.** It survives every registered band except the
one that matters most. At the bottom two values of the `domestic_anchor_premium_inr_t` grid the same nine tickets
**lose ₹8.6–10.5 crore**, and the book makes money only if the true 2022 premium was above about **−₹38,700/t** — a
threshold inside a grid whose own evidence runs from −52,000 to +13,000 and whose base value is PENDING verification.
At the top of the grid the book makes ₹33.43 crore. The result therefore **rides on one ASSUMPTION whose own
registered grid spans ₹68,000/t**, and no reader should quote ₹19.21 crore without that sentence attached. At the
anchor-premium floor, T02 (+₹2.50 crore), T01 (+₹1.37 crore) and T03 (+₹0.43 crore) still make money; the other six
tickets lose, T08 by ₹4.66 crore.

Three further readings worth having in an interview:

* **The 50/50 arb split is worth ₹17.85 crore.** At a 0 % desk share — every sale priced at the desk's own
  replacement value — the book makes ₹1.35 crore, which is what the purchase discounts and the market buckets leave
  once the rule's margin is removed. A flat ₹5,000–8,000/MT trading margin, closer to what a competitive import
  market pays a middleman, gives ₹8.54–12.85 crore. Most of the book's result is the 50 % rule; the rule is a stated
  convention, not a quote.
* **The purchase-discount band the tickets used (10–15 USD/t of a registered 0–30) is worth ₹2.30 crore** across
  its full width — small next to the anchor premium, and it moves the result in the direction you would expect.
* **The grade reconstruction, re-priced, costs up to ₹9.48 crore** (the point-in-time mix), and moves the book by
  −₹5.83 to +₹3.92 crore across the differentials' evidence quartiles. That is the number §13.6's re-mark cannot
  show and the one to quote when asked how much of this book is a reconstruction.

None of these cases is a book Phase 2 could have published: at a 0 % share or a −55,000 anchor premium the
re-derived sale prices fall outside the `[replacement, netback]` band that validation rule P09 enforces. They are
revaluations of the published decisions under another parameter, which is exactly what a sensitivity is. Nor is any
of them a joint scenario: no case moves two bands at once (a low premium *and* the point-in-time mix, say), and none
is published.

### 13.10 The MCX roll: INR carry, not term structure

`outputs/tables/mcx_roll_carry.csv` (and `_mcx_mirror`).

The panel MCX series is `spot × (1 + inr_rate_3m_pa × days_to_expiry/365)`. Because `dte(M2) > dte(M1)` always,
**M2 > M1 on all 126 window panel days** — the proxy is in permanent contango by construction, M1 and M2 print the
same daily percentage move to within 7 bp, and there is no calendar-spread risk in the model at all. A short
rolling M1 → M2 on day `d` therefore collects

```
carry = spot_parity(d) x inr_rate_3m_pa(d) x (dte(M2) - dte(M1)) / 365     ₹/kg
```

with no market view whatsoever — while the DIRECT LME cash–3M spread was in **backwardation on 33 of the 126 window
panel days** (36 of 148 through September). The table splits every executed roll into that carry and the remainder, prints the
LME spread beside it, and re-prices the same roll on a **reference curve that carries the LME's own term structure**:
`F(T) = LME cash forward to T (linear cash→3M) × CIP USD/INR forward to T × duty uplift + premium`, built from the
engine's own `curves.cash_fwd` and `curves.fx_x`. That reference roll splits into **rate carry** (the rupee-over-
dollar forward points) and **metal carry** (the LME slope, which itself contains USD financing, storage and
convenience yield):

| 13 executed rolls | Panel proxy (base) | Reference: parity with the LME curve | Third-party mirror (PROXY) |
|---|---|---|---|
| total roll P&L | **+₹8,421,697** | +₹7,332,004 | +₹9,469,250 |
| … INR carry (proxy) / rate carry INR over USD (reference) | +₹8,421,697 | +₹5,942,233 | +₹8,421,697 |
| … term structure (proxy: none) / **metal carry** (reference) | **₹0** | **+₹1,389,771** | +₹1,047,553 |
| rolls that were gains | **13 of 13** | 13 of 13 | 10 of 13 |
| rolls dealt in LME backwardation | 1 (T07, 2022-07-20, cash–3M +8.5) | metal carry **−₹327,394** on it | — |
| proxy minus reference | | **+₹1,089,693** | |

The `roll_carry_metal_component_max_abs` control asserts the proxy's zero. So the honest statement is narrower
than "the roll is an artefact": **the proxy's roll P&L is almost entirely rate carry, which is real** — a rupee
future carried at Indian rates against a dollar metal carried at US rates — **and it contains no metal term
structure at all.** On this book the LME curve was not in backwardation on 12 of the 13 roll dates, so a curve that
carried it would have paid the desk a little metal carry as well, and the proxy overstates the rolls by only
₹10.9 lakh. The
one roll dealt in backwardation (T07-MCX-2 on 20-Jul) shows the other state of the world: it loses ₹3.3 lakh of
metal carry and stays positive only because of the rate differential. A deep backwardation would have made rolling
a short cost money, and **the proxy cannot represent that**; any ticket rationale that frames rolling as "what
holding unsold cargo on a forty-day lane actually costs" is describing the metal half this engine did not measure.
The holding cost this book did bear is in the funding accrual inside (g), not in the roll.

### 13.11 Basis risk, two-sided — and the unit-beta assumption tested

`outputs/tables/mcx_basis_risk.csv`. **Every row is labelled `SENSITIVITY — not base P&L`.**

The mirror run's headline is +₹1.84 crore *better* than base (§13.6), which is exactly the wrong way to read a
risk. The per-ticket figures are the measure:

| Lifetime effect of swapping the MCX series, per ticket | ₹ |
|---|---|
| **worst ticket — the loss case (T01)** | **−19,206,374** |
| best ticket — the gain case (T05) | +19,173,462 |
| **range across the nine tickets** | **38,379,835** |
| mean absolute effect per ticket | 6,607,842 |
| sum of the tickets that lost (T01, T04) | −20,534,042 |
| netted book total — one draw | +18,402,493 |
| **the same path with its sign reversed (the adverse image)** | **−18,402,493** |

| (b) + (g) moved **jointly** by the MCX series, lifetime | ₹ |
|---|---|
| worst ticket (T01) | −19,210,220 |
| best ticket (T05) | +15,811,470 |
| **book, quoted as a two-sided band** | **± 18,949,834** |

Per-ticket bucket (b) on the mirror runs from −₹1.84 crore (T01) to +₹1.79 crore (T05). On a nine-ticket book the
netting is luck; on one ticket the basis is worth about ±₹1.9 crore against −₹1.2 to +₹6.4 crore of trade P&L. **Read
the range, and read (b) and (g) together**: nothing in one six-month mirror makes the favourable draw more likely
than its mirror image, so the book-level basis-and-curve risk is **±₹1.9 crore**, not a gain.

**The unit-beta assumption.** The engine hedges by holding the MCX basis and letting LME and FX drive the MCX
price — which is precisely an assumption that an MCX contract moves one-for-one with duty-paid LME parity. On the
panel proxy that is true by construction (the regression below returns 1.000). On the mirror it is testable, and it
fails:

| Daily changes, mirror M1 regressed on duty-paid parity, 2022-03-01 → 2022-08-31 | |
|---|---|
| beta | **0.452** |
| standard error | 0.063 |
| **t against H₀: beta = 1** | **−8.67** — rejected |
| R² | 0.294 |
| observations (daily changes) | 125 |
| share of a parity move a beta-1-sized short does **not** offset | **0.548** |

And because the basis is held as an additive state in **both** runs, the mirror sensitivity moves the attribution
but **no risk number**: every delta column of `book_exposures_daily_mcx_mirror.csv` equals the base file exactly
(§10). Read with `docs/10_parity_model.md` §11, which finds the same thing from the other side: mirror-versus-parity
daily return correlation is only 0.50–0.57 (weekly 0.84–0.93) and the basis standard deviation is ₹6,277–7,678/t,
larger than the desk's own ₹5,000/t hurdle. A weekly parity decision can live with that; a daily hedge P&L cannot. So
the honest statement about hedge effectiveness in this book is: **+₹197.1 m of hedge benefit over the crash window,
measured on a series whose basis is zero and whose beta is 1 by construction, against a measured hedge slope of 0.45
on the only observed-ish alternative.** The hedge worked in the model. Whether it would have worked on MCX is not
something this project can show, and Phase 4 should not size a VaR as if it had.
