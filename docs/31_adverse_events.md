# 31 — Adverse events on the real book (MASTER_SPEC Table 5, rows 3.4–3.6)

**ACADEMIC SIMULATION — not actual trades.** Every counterparty, vessel, dwell day and payment delay in this
document is simulated and labelled (SIM). The *market* moves are real and dated; the *book* that lived through them
is not.

This page is the results companion to `docs/30_mtm_attribution.md` (the method). It takes the nine tickets in
`config/trades.yaml`, runs them through `desk.mtm.engine` over the real Mar–Oct 2022 panel, and reports what three
adverse events did to the book — each one isolated against a counterfactual re-run of the *same* engine with one
component of the book removed.

```sh
cd /Users/sujaljindal/Desktop/ujjwal
DESK_OFFLINE=1 .venv/bin/python run_all.py --only P3
```

| Output | What it holds |
|---|---|
| `outputs/tables/adverse_event_windows.csv` | the derived windows and the rule that produced each |
| `outputs/tables/adverse_event_1_lme_crash{,_daily}.csv` | event 1 summary and its daily path |
| `outputs/tables/adverse_event_2_usdinr{,_daily}.csv` | event 2 summary and its daily path |
| `outputs/tables/adverse_event_3_logistics_credit.csv` | event 3 summary, with each component isolated |
| `outputs/tables/adverse_event_3_freight_stress_hypothetical.csv` | a **labelled stress**, not a 2022 event |
| `outputs/tables/adverse_events_summary.csv` | all three in one scan |
| `outputs/tables/mcx_variation_margin.csv` | the margin cash schedule event 1 reads |
| `outputs/charts/p3_adverse_events.png`, `p3_mcx_vm_schedule.png`, `p3_event1_hedged_vs_unhedged.png`, `p3_event2_fx_offset.png` | the four figures below |

Aliases `adverse_event_2_inr_depreciation.csv` and `adverse_event_3_payment_delay_demurrage.csv` carry identical
content under the names the Phase 3 brief uses.

---

## 0. The three events in one table

| | E1 LME crash | E2 INR depreciation | E3 logistics + credit |
|---|---|---|---|
| Window | 2022-03-07 → 2022-07-15 | 2022-04-05 → 2022-07-14 | 2022-07-28 → 2022-10-11 |
| Market move | LME cash 3,984.5 → 2,320.5 USD/t, **−41.8 %** | USD/INR 75.3350 → 80.0352, **+6.24 %** | container freight **−35.6 %** on both lanes |
| Book P&L over the window | **+₹206.5 m** | +₹140.1 m | +₹8.0 m |
| The factor that carried it | (a) LME flat **−₹44.8 m** net | (e) USD/INR **+₹15.7 m** net | (f) penalties +₹0.07 m |
| Unhedged counterfactual | +₹9.3 m (no MCX) | +₹116.2 m (no forwards) | +₹8.9 m (no events) |
| **Isolated hedge / event impact** | **hedge benefit +₹197.1 m** | **forward-book benefit +₹23.9 m** | **event cost −₹2.15 m lifetime** |
| Cash strain | peak margin outflow **−₹105.7 m on 2022-03-24**; max IM ₹95.8 m | 25 forwards, all settled by 2022-10-24 | 25 days past due; buyer line 83 % drawn |

Every window is **derived by rule after the fact and is reporting-only**. No trade decision saw one:
`desk.book.validate` never imports `desk.mtm.events`, and a trade dated `d` prices only on information published on
or before `d` (CONTRACTS §1, §5a).

---

## 1. Event 1 — the crash from the 7-March-2022 all-time high

### 1.1 What actually happened (DIRECT)

| Date | LME Aluminium cash, USD/t | Note |
|---|---|---|
| 2022-03-07 | **3,984.5** (3M 3,968.0) | the all-time high, and the panel's window maximum |
| 2022-03-08 | 3,500.5 | **−12.2 %** (−12.95 % in logs) — the largest one-day fall anywhere in the 2018–2022 panel |
| 2022-03-31 | 3,503.0 | cash–3M spread turns to contango (−15.0) and stays there until late July |
| 2022-04-29 | 3,039.0 | |
| 2022-05-31 | 2,816.5 | |
| 2022-06-30 | 2,397.0 | |
| **2022-07-15** | **2,320.5** | the window minimum, **−41.8 %** from the high |
| 2022-08-31 | 2,368.5 | back to a small backwardation (+11.5) |

Source: Westmetall's yearly LME Aluminium tables, which republish LME official cash-settlement and 3-month prices
(`data/raw/westmetall_lme_al_2022.html`, retrieved 2026-09-16; `docs/research/market_data_notes.md` §2). Flag:
**DIRECT**. The 3,984.5 anchor and the −12.95 % log move are hard-checked in `desk.data.fetch_lme.validate`.

The backdrop is in the project's own cached news file (`data/processed/headlines_weekly.csv`, real Google News RSS
items, **DIRECT headline text**): Reuters on 2022-03-07 on the record one-day move in LME nickel, and Reuters and
the ABC on 2022-03-14 on the nickel squeeze and the exchange's response. Those are cited as context for why the
complex traded the way it did in that week. **No claim is made here about aluminium-specific causation.**

**Derived windows** (`desk.mtm.events`, rules in `adverse_event_windows.csv`):

| Window | Rule | Result |
|---|---|---|
| E1 crash | argmax cash in Mar–Aug → argmin after it | 2022-03-07 → 2022-07-15, −41.76 % |
| E1 crash fortnight | the 10-trading-day **return** window (11 observations) with the most negative return | 2022-04-22 → 2022-05-09, **−16.52 %** |
| memo, 9 returns | the 10-*observation* reading | 2022-03-07 → 2022-03-18, −15.16 % |

The off-by-one is pinned in CONTRACTS §7a.3 and both readings are published, because they genuinely select
different fortnights and a reader should be able to see which convention produced the number.

### 1.2 What it did to the book

Over the crash window the book made **+₹206.5 m**. That is not because the crash was good for it; it is because
`new_deal` (+₹130.4 m — eight of the nine tickets were contracted inside this window, and most of their sales
with them) and (c) grade spread (+₹128.8 m) both landed there. The crash itself is factor (a):

| (a) LME flat over 2022-03-07 → 2022-07-15 | ₹ |
|---|---|
| physical legs, of which — | **−263,495,973** |
| … the replacement-value mark on unsold cargo (design D5) | −261,508,640 |
| … everything else (priced purchases, sales, insurance) | −1,987,333 |
| MCX short | **+218,726,838** |
| **net bucket (a)** | **−44,769,135** |
| **hedge offset** = −MCX ÷ physical | **0.830** |

The 0.830 offset is below the desk's stated 0.90 ratio for two reasons, both real: the hedge is re-sized only at a
decision date, so `hedge_ratio_lme_frac` drifts between decisions (book median 0.903, and the exposure file shows
the drift day by day); and three tickets carry deliberately lower ratios (T04 at 0.50, T06's FX leg at 0.60).

### 1.3 Hedged versus unhedged — the counterfactual

`desk.mtm.events.counterfactual` re-runs the **same engine over the same panel** with every MCX leg deleted —
margin, transaction charges, slippage and the funding on all of it. The difference is therefore a like-for-like
hedge benefit, not a comparison of two models.

| Over 2022-03-07 → 2022-07-15 | ₹ |
|---|---|
| book as traded | **+206,460,404** |
| counterfactual: same book, no MCX hedge | +9,344,342 |
| **hedge benefit** | **+197,116,062** |

Chart: `outputs/charts/p3_event1_hedged_vs_unhedged.png` — both lines rebased to zero at the window start, with
the LME cash path behind them and the crash fortnight shaded.

The honest reading: the hedge did its job, and it did it **against a mark, not against a realised loss**. The
physical −₹263.5 m is almost entirely the replacement-value mark on cargo the desk had bought and not yet sold
(design D5). Had every parcel been sold on its trade date there would have been little to hedge. The number that
matters commercially is that the desk was carrying up to **4,980 MT unsold on 2022-04-06** into a −41.8 % market.

### 1.4 The margin cash schedule through the crash

A short pays variation margin when the market **rises**. For this book that inverts the intuition: the cash strain
is in March, on the way down from the high but through a violently two-sided market, and the crash itself *pays*.

| Month | Variation margin ₹m | Net margin cash ₹m (VM − IM change + charges) | Cumulative margin cash ₹m | Peak IM in month ₹m |
|---|---|---|---|---|
| Mar-2022 | +14.7 | **−60.4** | **−60.4** | 30.4 |
| Apr-2022 | +104.0 | +121.6 | +61.1 | 28.7 |
| May-2022 | +5.2 | −3.7 | +57.4 | 29.8 |
| Jun-2022 | +75.8 | +72.7 | +130.1 | 29.9 |
| Jul-2022 | −21.6 | +17.9 | +148.0 | 28.6 |
| Aug-2022 | −5.7 | +18.0 | +166.0 | 24.8 |

Key points, all from `mcx_variation_margin.csv`:

* **Peak cumulative margin outflow −₹105,707,065 on 2022-03-24** — four months *before* the price trough. The first
  tranche alone posts ₹44.2 m of initial margin on day one (2022-03-09; ₹44.4 m of cash once charges and slippage
  are counted), and the 21-Mar and 24-Mar sessions call −₹22.2 m and −₹21.9 m of variation margin as cash rallied
  from 3,288 on 17-Mar back to 3,664 on 24-Mar — within 8 % of the all-time high.
* **Peak cumulative margin inflow +₹169.6 m on 2022-07-14**, the day before the trough.
* **Maximum initial margin ₹95,803,038 on 2022-04-21** at the registered `mcx_al_margin_used_frac`; at a stressed
  12 % it is ₹114,963,645 and at 15 % ₹143,704,557. Peak net short was **709 lots (3,545 MT)** on 2022-04-21
  against the DIRECT 25,000 MT client position limit.
* Over the crash fortnight (2022-04-22 → 2022-05-09) variation margin was **+₹65.0 m** — money in.
* Lifetime variation margin **+₹172.4 m**, less ₹6.4 m of transaction charges and slippage, giving the
  **+₹166.0 m** of MCX leg P&L the attribution reports.

Chart: `outputs/charts/p3_mcx_vm_schedule.png`.

**The liquidity lesson is the March column, not the July one.** A desk that sized its hedge on the crash and
budgeted for margin *receipts* would have been wrong by ₹106 m of outflow in the first fortnight, on top of ₹96 m
of initial margin. Phase 5 owns the liquidity buffer; this is the input.

### 1.5 What could not be modelled

* **The MCX series is a PROXY** (duty-paid import parity), so the LME–MCX basis is identically zero in base runs
  and bucket (b) is empty by construction. §5 below prices that gap with the third-party mirror.
* **Daily price limits are not modelled.** The near-month proxy moved −12.0 % on 2022-03-08 against MCX's 9 %
  maximum slab (`mcx_al_dpl_max_frac`, DIRECT). A real position would have been limit-locked and unable to trade
  that session. Phase 2 acknowledges this by hedging T01 on 2022-03-09, one session naked, and saying so.
* No SPAN margining, no intraday calls, no MCX-versus-LME close-time gap.

---

## 2. Event 2 — the rupee's slide past 80

### 2.1 What actually happened (PROXY for the level, DIRECT for the policy path)

| Date | USD/INR (ECB cross, **PROXY**) |
|---|---|
| 2022-03-01 (window start) | 75.7046 |
| **2022-04-05** | **75.3350** — the window minimum |
| 2022-05-31 | 77.6916 |
| 2022-06-30 | 79.0536 |
| **2022-07-14** | **80.0352** — first panel day at or above 80 |
| 2022-08-31 (window end) | 79.5465 |

* Window first-to-last: **+5.07 %**. Maximum drawdown pair (the rule E2 uses): **+6.24 %**.
* `usdinr` is the **ECB EUR/INR ÷ EUR/USD cross**, a PROXY for the RBI/FBIL reference rate. The gap to the official
  fixing has **not been measured** (PENDING in `docs/verification_log.md`); the ECB fixing is several hours after
  the 13:30 IST reference and the cross itself moved a median 12 paise a day in this window. So "the rupee first
  went through 80 on 14 July" is a statement about **this proxy series**, not a citation of the official rate.
* The policy backdrop *is* DIRECT and verified step by step against the source releases (`rates.yaml`,
  `docs/research/market_data_notes.md` §4): RBI repo 4.00 % → 4.40 % (off-cycle, 2022-05-04) → 4.90 % (2022-06-08)
  → 5.40 % (2022-08-05), against a Fed upper bound going 0.25 % → 0.50 % (2022-03-17) → 1.00 % → 1.75 % → 2.50 %
  (2022-07-28). The differential narrowing is why the desk's 3-month forward premium fell from 3.46 % p.a. at the
  window start to 2.69 % at its end — hedging got cheaper as the rupee got weaker.

### 2.2 What it did to the book

| (e) USD/INR over 2022-04-05 → 2022-07-14 | ₹ |
|---|---|
| USD cash legs (supplier payables, insurance, freight, PSIC) | **−25,202,626** |
| replacement-value mark on unsold cargo — **long USD** (design D5) | +36,688,676 |
| USD/INR forward book | **+35,065,847** |
| MCX short — short USD, because duty-paid parity rises in rupees when the rupee falls | −30,846,986 |
| **net bucket (e)** | **+15,704,911** |

Two offset ratios are published because they answer different questions:

* **1.39× against the USD cash legs** — the forwards were booked to cover the payables, and over this window they
  more than covered them.
* **−3.05× against the net physical including the inventory mark** — which reads badly until you see why: marking
  unsold cargo at import replacement value makes it **long USD**, so a 100 % forward hedge of the payable leaves
  the book **net long USD while the cargo is unsold**. That is a genuine consequence of the marking policy, not an
  error, and it is the same effect that makes `hedge_ratio_fx_frac` unstable in `book_exposures_daily.csv`
  (§6 below).

**Counterfactual — the forward book removed:**

| Over 2022-04-05 → 2022-07-14 | ₹ |
|---|---|
| book as traded | **+140,138,848** |
| counterfactual: same book, no FX forwards | +116,239,968 |
| **forward-book benefit** | **+23,898,880** |
| cost of that cover (bank margin at inception + the forward legs' carry) | −11,002,089 |

**Settlements.** All 25 forward lines settled inside the horizon; none was open at 2022-10-31. Realised settlement
cash was **+₹13,970,390** across the book, from −₹9.17 m on T01 (three April lines struck before the slide, one of
them a SELL_USD) to +₹6.40 m on T02 and +₹6.19 m on T09. Each line settles at `sign × notional × (X(τ, value_date)
− K)`, with `X` the spot on the value date once settled — the formula is carried in `trade_cashflows.csv`.

Chart: `outputs/charts/p3_event2_fx_offset.png`.

### 2.3 What could not be modelled

* The forwards are **CIP-implied**, not dealt rates: real onshore points also carry RBI forward-book intervention,
  dollar liquidity and exporter/importer flow. The 1-month tenor reuses 3-month rates.
* The **customs duty base does not move on spot.** It moves on the CBIC notified rate, a fortnightly step
  (DIRECT), so `customs_fx_delta_usd` is reported separately from `fx_delta_usd` and a "100 % FX hedge" never
  covers the duty leg.

---

## 3. Event 3 — falling freight, the July void calls, and a buyer who paid late

CONTRACTS §7.6 requires this event to be framed honestly, and the honesty is the finding: **there was no container
freight spike on the desk's lanes in 2022.**

### 3.1 What actually happened (DIRECT where sourced, ASSUMPTION for the lane levels)

| Fact | Date | Source |
|---|---|---|
| Drewry WCI composite 9,279 → 7,626 → 5,986 USD/FEU | 3-Mar / 2-Jun / 25-Aug 2022 | Drewry WCI page via Internet Archive; AJOT republications (`freight_notes.md` S1, S2) — **DIRECT points** |
| Drewry's 18-Aug-2022 release called it the 25th consecutive weekly decrease | 2022-08-18 | AJOT (S2) — **DIRECT** |
| Europe → West India 2,500 → 2,050 → 1,950 → 1,900 USD/FEU | Mar/Apr → Jun → Jul → Aug 2022 | Container News (S3–S5) — **DIRECT** |
| US East Coast → West India return leg fell 10–15 % in July, then held at 1,450 | Jul–Aug 2022 | Container News 27-Jul and 30-Aug 2022 (S4, S5) — **DIRECT** |
| **Carriers voided calls at Nhava Sheva and Mundra**, announced up to November | reported **2022-07-27** | Container News, 27-Jul-2022 (S4) — **DIRECT** |
| Desk lanes over the window: JEA_NSA 24.51 → 15.78 USD/t, USEC_MUN 108.68 → 69.96 USD/t (**−35.6 %** both) | Mar → Aug 2022 | `data/processed/freight_weekly.csv` — shape PROXY, **level ASSUMPTION**, hindsight-calibrated |

The lane *levels* are a reconstruction: no India-inbound quote published before 29-Apr-2022 could be retrieved, so
March–April levels are built from anchors that only became public months later (`freight_notes.md` §1). Everything
in this section that depends on a freight *level* inherits that flag.

### 3.2 The three simulated components, each isolated

All three sit on **T07** (tense, USEC_MUN, 1,890 MT, traded 2022-05-25, sold to Saurashtra Castings and Alloys
Pvt Ltd (SIM) on 2022-07-26). The window runs from the earliest effective known date to the last settle those
events move: **2022-07-28 → 2022-10-11**.

| Component | What the ticket says | Lifetime cost vs the same book without it |
|---|---|---|
| **Extra CFS dwell** — T07-LOG-1 (+6 days, lot L1) and T07-LOG-2 (+12 days, lot L2), known 2022-07-28 | the void calls are real and dated; the dwell days are **SIM**, attributed to them | **−₹1,512,152** |
| **Buyer payment delay** — T07-PAY-1, 26 days on sale S1, known 2022-09-26 | **SIM**: the buyer's own castings receivables stretched as domestic ingot prices fell; four weeks given against post-dated cheques already held | **−₹561,839** |
| **Out-turn quality claims** — T07 lot L1 and T08 lot L2 moisture / contamination | **SIM** survey outcomes against the SPA franchise | **−₹66,605** |
| all three together | | **−₹2,151,974** (interaction −₹11,378) |

Supporting numbers: the demurrage leg costs **−₹1,248,958** over the book's life (chargeable dwell beyond
`detention_free_days`, at the registered `demurrage_usd_per_box_day`); overdue funding routed to bucket (f) by the
§7a.1 split is **−₹651,323**; maximum days past due **25**. The (f) bucket over the E3 window itself is only
+₹70,479, because most of the cost is carried by the funding accrual and by flows that settle outside the window —
which is why the lifetime column is the one to read.

An event's effective known date is `min(stated known_date, the milestone it moves)`. T07-PAY-1 is dated 2022-09-26
against a contractual due of 2022-09-15; taken literally the engine would have shown ₹89.6 m collected for eleven
days and then un-collected it. A desk learns a payment has not arrived on the day it was due.

### 3.3 Freight fixed early into a falling market

The desk does not hedge freight (no accessible India-lane derivative). It floats under a stop at trade-date index
+15 % and books by 10 days before the first bill of lading. The index fell monotonically, so all three FOB fixtures
were taken on their book-by dates.

| Counterfactual | ₹ |
|---|---|
| book as traded | (lifetime) **+197,910,352** |
| counterfactual: no fixture, freight floats and fixes at each B/L | +200,407,509 |
| **fixture-timing cost, lifetime** | **−2,497,157** |

This is a **competitiveness cost, not a loss on the cargo.** Under CONTRACTS §5 the CFR grade factor does not fall
when freight falls, so a later importer lands the same metal cheaper; the desk's own margin is unchanged on the
CFR tickets. The daily memo `fixture_vs_market_inr` in `mtm_daily.csv` averages **−₹1,317,503** over the leg-days
it is defined, and is a **stock** measure — never summed into P&L.

### 3.4 Credit-limit mitigation for the delayed buyer

The buyer that paid late has the smallest line on the book: **Saurashtra Castings and Alloys Pvt Ltd (SIM),
`credit_limit_inr` ₹120,000,000**. The T07 sale was worth ₹314,685,000 — 2.6× that line. It was still sold, because
the exposure that counts against a credit limit is what the desk has **invoiced and not been paid**:

| T07 sale S1 to BUY_RJK_01 | ₹ |
|---|---|
| invoice value | 314,685,000 |
| advance, received 2022-08-12 **before** the trucks moved (70 %) | 220,279,500 |
| credit extended (30 days) | **94,405,500** |
| … against a limit of | 120,000,000 |
| peak receivable actually carried | 89,642,900 (**74.7 %** of the line) |

So the 26-day delay hit a line that was three-quarters drawn on ₹89.6 m — not an unsecured ₹315 m. Three
mitigations are visible in the book and all three are policy decisions, not luck: the 70 % advance; the post-dated
cheques held as security (SIM); and the fact that the ticket was not contracted until 2022-07-26, after the same
buyer's T04 invoice cleared on 2022-07-23.

Across the book, peak buyer credit utilisation is **83.4 %** (BUY_JNPT_01) and **no buyer breached its limit on any
day**. That agrees with Phase 2's own P04 rule, which nets the advance out at booking for exactly the same reason.

> **Correction made during integration.** Phase 3 originally summed *everything contracted and unsettled* against
> the credit limit and reported a 2.58× breach over 46 days. That measure counted the ₹220.3 m advance the buyer
> had **not yet paid** as if it were credit the desk had extended — the opposite of credit risk. CONTRACTS §7a.4
> already separates `buyer_receivable_inr` (invoiced, unpaid) from `buyer_presettlement_inr` (contracted, not yet
> invoiced), and the limit check now uses the first. Both are still published: the
> `max_buyer_contracted_utilisation_frac` row keeps the 2.58× figure, correctly labelled as a **performance**
> exposure. Phase 5 owns the credit tracker and should carry both.

### 3.5 The freight spike that did not happen

`adverse_event_3_freight_stress_hypothetical.csv` prices a **+40 % container shock**
(`freight_stress_shock_frac`, MASTER_SPEC Table 6 row 4.2) on every in-window day. **Every row carries the label
`HYPOTHETICAL STRESS — not a 2022 event`.**

The worst it can do is **−₹8,551,738** (T01, 2022-03-08) and the book impact reaches zero by 2022-03-18, because
once a fixture is booked the cargo carries no freight price risk at all (design D12) and a CFR cargo never did.
Only three tickets are exposed at all — T01, T04 and T07, the three FOB tickets, and only before their fixtures.
**The stress is small by construction, and that fact is the result**: this desk's freight risk is a timing risk,
not a price risk.

---

## 4. Charts

| File | What it shows |
|---|---|
| `p3_event1_hedged_vs_unhedged.png` | the book as traded against the same book with no MCX hedge, rebased at the E1 window start, over the LME cash path, with the crash fortnight shaded |
| `p3_mcx_vm_schedule.png` | daily variation margin, cumulative margin cash and initial margin posted from 2022-03-01 — the March outflow is the point |
| `p3_event2_fx_offset.png` | the (e) bucket split into USD cash legs, the D5 inventory mark, the forward book and the MCX short, over the USD/INR path |
| `p3_adverse_events.png` | the three events side by side on **three separate scales**, with event 3's honesty note printed on the figure |

Every figure is stamped `ACADEMIC SIMULATION — not actual trades` by `desk.reporting.style.save_fig`.

---

## 5. The basis sensitivity: what event 1 looks like on the third-party MCX mirror

Base runs value MCX at the panel's import-parity proxy, so the LME–MCX basis is **zero by construction**. The
engine re-runs the whole book on the third-party mirror series (`data/interim`, also PROXY) so the basis can at
least be sized. **This is a sensitivity. It is never presented as base P&L.**

| Over 2022-03-07 → 2022-07-15 | base (panel proxy) | MCX mirror |
|---|---|---|
| book P&L over the window | +₹206,460,404 | +₹210,729,894 |
| bucket (b) LME–MCX basis | **0** by construction | **−₹8,216,965** |
| bucket (g) roll / term structure | −₹20,062,594 | −₹7,216,669 |
| hedge benefit vs no MCX | +₹197,116,062 | +₹193,673,624 |
| peak cumulative margin outflow | −₹105,707,065 (2022-03-24) | −₹101,017,277 (2022-03-23) |
| maximum initial margin | ₹95,803,038 | ₹96,424,000 |

Read it as: **a plausible real basis is worth about −₹8 m of P&L over the crash and moves the hedge benefit by
about 1.7 %** — material but not decisive. It does not validate the proxy: the mirror's own provenance cannot be
checked against MCX's bhavcopy, and its second-month series is partly stale.

---

## 6. What this does and doesn't tell you

**Does.** For three dated, real market episodes it shows what this simulated book's hedges actually did, measured
as the difference between two runs of one engine over one panel — so the "hedge benefit" includes the margin, the
transaction charges, the slippage and the funding on all of it, and cannot be inflated by comparing two different
models. It shows *when* the cash strain fell (March, not July), how large it was in rupees (−₹105.7 m of margin
outflow and ₹95.8 m of initial margin), and what the forward book was worth against the payables it was booked to
cover. It separates the operational event into dwell, payment delay and quality, and it reports the freight story
the evidence supports rather than the one the brief anticipated.

**Doesn't.**

* **These are not realised 2022 losses.** The book is simulated; the counterparties, vessels, dwell days and the
  payment delay are SIM. Only the market moves are real.
* **The windows were drawn after the fact**, by rule, to describe the book. They were never inputs to a decision,
  and a desk in March 2022 could not have known that 15 July would be the low.
* **Event 1's physical loss is a mark, not a realisation.** −₹263.5 m of factor (a) is almost entirely the
  replacement-value mark on unsold cargo. The hedge benefit is correspondingly a benefit against a mark.
* **Bucket (b) is empty in base runs** because MCX is a duty-parity proxy. §5 sizes the gap on another proxy.
* **Event 1's margin schedule ignores daily price limits and SPAN.** The proxy's −12.0 % move on 2022-03-08
  against a 9 % slab means a real short would have been locked that session.
* **Event 2's rate is a PROXY.** "The rupee went through 80 on 14 July" is a statement about the ECB cross used
  here; the comparison to the official RBI/FBIL fixing is PENDING.
* **Event 3's freight levels are a hindsight reconstruction** and its dwell days, delay length and survey outcomes
  are simulated. What is real and dated is the 27-Jul-2022 void-call report and the direction of freight.
* **Nothing here is a credit model.** The credit numbers are the headline event 3 needs; Phase 5 owns scoring,
  the tracker and the liquidity buffer.

---

## 7. Provenance

| Input to this page | Flag |
|---|---|
| LME official cash and 3M prices, and the dates of the high and the trough | **DIRECT** (Westmetall republication of LME official prices) |
| RBI repo and Fed funds step paths | **DIRECT** (RBI press releases, Federal Reserve open-market table; every step verified) |
| MCX contract specs, expiries, daily price-limit slab, client position limit | **DIRECT** |
| Drewry WCI points; Container News India-lane rates; the 27-Jul-2022 Nhava Sheva / Mundra void calls | **DIRECT** |
| News headlines used as backdrop | **DIRECT** (cached Google News RSS items, stored verbatim; never paraphrased or invented) |
| USD/INR, INR and USD 3-month rates, CIP forwards | **PROXY** |
| MCX panel series (duty-paid import parity) — so bucket (b) ≡ 0 in base runs | **PROXY** |
| MCX third-party mirror (§5 only) | **PROXY** |
| Freight lane levels; grade factors; payloads, free days, demurrage rate, port charges, WC rate, margin used | **ASSUMPTION** (freight levels and the lag-2 grade mix are hindsight reconstructions) |
| Counterparties, vessels, dwell days, survey outcomes, the payment delay and its length | **SIM** |
