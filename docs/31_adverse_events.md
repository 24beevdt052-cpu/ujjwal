# 31 — Adverse events on the real book (MASTER_SPEC Table 5, rows 3.4–3.6)

**ACADEMIC SIMULATION — not actual trades.** Every counterparty, vessel, dwell day and payment delay in this
document is simulated and labelled (SIM). The LME moves and the dated news are real; USD/INR and the MCX series are
PROXIES, and the grade factors and freight levels are hindsight-calibrated reconstructions. The *book* that lived
through them is not real at all.

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
| Book P&L over the window | **+₹210.5 m** | +₹130.1 m | +₹1.81 m |
| The factor that carried it | (a) LME flat **−₹44.8 m** net | (e) USD/INR **+₹6.9 m** net | (f) events known **−₹4.34 m** |
| Unhedged counterfactual | +₹13.4 m (no MCX) | +₹113.6 m (no forwards) | +₹7.65 m (no events) |
| **Isolated hedge / event impact** | **hedge benefit +₹197.1 m** | **forward-book benefit +₹16.5 m** | **event cost −₹9.35 m lifetime** |
| Cash strain | peak margin outflow **−₹105.7 m on 2022-03-24**; max book IM ₹95.8 m | 25 forwards, all settled inside the horizon | 26 days late (25 at the last overdue close); buyer line 74 % drawn |

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

**The window is bounded at `WINDOW_END` by rule, and the market did not stop there.** `desk.mtm.events` takes the
argmin on `[start, WINDOW_END]`, which is why E1 ends at 2,320.5 on 15 July. On the panel, cash fell further after
the reporting window — to **$2,080.0 on 2022-09-28, −47.8 % from the 7-March high** — and that low is inside the
engine horizon (`HORIZON_END` 2022-10-31). CONTRACTS §7a.3 states the rule as "argmax cash → argmin after it"
without the bound; the bound is printed in the `rule` column of `adverse_event_windows.csv`, and "−41.8 %" is
therefore the *reporting-window* drawdown, not the worst the book's own horizon saw.

### 1.2 What it did to the book

Over the crash window the book made **+₹210.5 m**. That is not because the crash was good for it; it is because
`new_deal` (+₹127.8 m — eight of the nine tickets were contracted inside this window, and most of their sales
with them) and (c) grade spread (+₹128.8 m) both landed there. The crash itself is factor (a):

| (a) LME flat over 2022-03-07 → 2022-07-15 | ₹ |
|---|---|
| physical legs, of which — | **−263,478,429** |
| … the replacement-value mark on unsold cargo (design D5) | −261,508,640 |
| … everything else (priced purchases, sales, insurance) | −1,969,789 |
| MCX short | **+218,726,838** |
| **net bucket (a)** | **−44,751,591** |
| **hedge offset** = −MCX ÷ physical | **0.830** |

The 0.830 offset is below the desk's stated 0.90 ratio for two reasons, both real: the hedge is re-sized only at a
decision date, so `hedge_ratio_lme_frac` drifts between decisions (book median 0.903, and the exposure file shows
the drift day by day); and two tickets carry deliberately lower ratios (T04's MCX target at 0.50, T06's FX cover
at 0.60).

### 1.3 Hedged versus unhedged — the counterfactual

`desk.mtm.events.counterfactual` re-runs the **same engine over the same panel** with every MCX leg deleted —
margin, transaction charges, slippage and the funding on all of it. The difference is therefore a like-for-like
hedge benefit, not a comparison of two models.

| Over 2022-03-07 → 2022-07-15 | ₹ |
|---|---|
| book as traded | **+210,503,943** |
| counterfactual: same book, no MCX hedge | +13,387,881 |
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

Two initial-margin columns, because they are different numbers and the difference is the point: the desk posts the
**book** total every day, while the largest single hedge line is at most a third of it.

| Month | Variation margin ₹m | Net margin cash ₹m (VM − IM change + charges) | Cumulative margin cash ₹m | Peak IM on one line ₹m | **Peak book IM in month ₹m** |
|---|---|---|---|---|---|
| Mar-2022 | +14.7 | **−60.4** | **−60.4** | 30.4 | **78.6** |
| Apr-2022 | +104.0 | +121.6 | +61.1 | 28.7 | **95.8** |
| May-2022 | +5.2 | −3.7 | +57.4 | 29.8 | **63.7** |
| Jun-2022 | +75.8 | +72.7 | +130.1 | 29.9 | **67.7** |
| Jul-2022 | −21.6 | +17.9 | +148.0 | 28.6 | **64.6** |
| Aug-2022 | −5.7 | +18.0 | +166.0 | 24.8 | **41.8** |

Key points, all from `mcx_variation_margin.csv`:

* **Peak cumulative margin outflow −₹105,707,065 on 2022-03-24** — four months *before* the price trough. The first
  tranche alone posts ₹44.2 m of initial margin on day one (2022-03-09; ₹44.4 m of cash once charges and slippage
  are counted), and the 21-Mar and 24-Mar sessions call −₹22.2 m and −₹21.9 m of variation margin as cash rallied
  from 3,288 on 17-Mar back to 3,664 on 24-Mar — within 8 % of the all-time high.
* **Peak cumulative margin inflow +₹169.6 m on 2022-07-14**, the day before the trough.
* **Maximum initial margin ₹95,803,038 on 2022-04-21** — the daily **sum** of `im_required_inr`, i.e. the book
  total, which is the last column of the table above and the number the two paragraphs below quote. At the
  registered `mcx_al_margin_used_frac`; at a stressed 12 % it is ₹114,963,645 and at 15 % ₹143,704,557. Peak net
  short was **709 lots (3,545 MT)** on 2022-04-21 (`book_exposures_daily.csv`, `mcx_lots_open`) against the DIRECT
  25,000 MT client position limit.
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
* **There is no curve risk in the proxy, and every roll is a gain by construction.** The panel builds the futures
  as `m1/m2 = spot × (1 + inr_rate_3m_pa × days_to_expiry/365)` (CONTRACTS §4.5). Because `dte(M2) > dte(M1)`
  always, **M2 > M1 on all 126 window panel days** and M1 and M2 print the same daily percentage move to within
  7 bp. A short rolling M1 → M2 therefore *always* collects `spot × r_INR × Δdte/365`, which is INR interest on a
  duty-paid parity — not metal contango, and not a view. All **13 rolls in this book are gains, ₹8,421,697 in
  total, of which ₹8,421,697 is that carry and ₹0 is term structure** (`mcx_roll_carry.csv`, and the
  `roll_carry_metal_component_max_abs` control asserts the split). On the third-party mirror the same 13 rolls are
  worth ₹9,469,250, of which **₹1,047,553 is genuine term structure and three of the thirteen are losses**. The
  table also re-prices each roll on a parity curve that carries the **LME's own cash–3M slope** and CIP rupee
  points: **₹7,332,004**, of which ₹5,942,233 is rupee-over-dollar rate carry and ₹1,389,771 metal carry, so the
  proxy overstates roll P&L by ₹1.09 m. LME aluminium went into backwardation from 20-Jul-2022 (DIRECT: cash−3M
  +8.5 on 20-Jul, +21.5 on 01-Aug), and the one roll dealt in it (T07, 20-Jul) loses **₹327,394 of metal carry** on
  that reference, kept positive only by the rate differential. **In a deep backwardation a short roll pays** — the
  proxy cannot represent that, so any "the roll costs me carry" framing in a ticket rationale describes the metal
  half of a market this engine did not measure (`docs/30_mtm_attribution.md` §13.10).
* **Daily price limits are not modelled.** The near-month proxy moved −12.0 % on 2022-03-08 against MCX's 9 %
  maximum slab (`mcx_al_dpl_max_frac`, DIRECT). A real contract would have traded only at the limit, if at all,
  and a seller would have found no bid inside the band — an inference from the proxy, not an MCX print. Phase 2 acknowledges this by hedging T01 on 2022-03-09, one session naked, and saying so. The same
  caveat applies to the margin schedule above: the proxy prints moves on several window days that the real
  contract could not have printed, and the −₹105.7 m peak is computed on it.
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
| USD cash legs (supplier payables, insurance, freight, PSIC) | **−25,203,508** |
| replacement-value mark on unsold cargo — **long USD** (design D5) | +36,688,676 |
| USD/INR forward book | **+26,306,476** |
| MCX short — short USD, because duty-paid parity rises in rupees when the rupee falls | −30,846,986 |
| **net bucket (e)** | **+6,944,658** |

Two offset ratios are published because they answer different questions:

* **1.04× against the USD cash legs** — the forwards were booked to cover the payables, and over this window they
  covered them almost exactly.
* **−2.29× against the net physical including the inventory mark** — which reads badly until you see why: marking
  unsold cargo at import replacement value makes it **long USD**, so a 100 % forward hedge of the payable leaves
  the book **net long USD while the cargo is unsold**. That is a genuine consequence of the marking policy, not an
  error, and it is the same effect that makes `hedge_ratio_fx_frac` unstable in `book_exposures_daily.csv`
  (§6 below).

**Counterfactual — the forward book removed:**

| Over 2022-04-05 → 2022-07-14 | ₹ |
|---|---|
| book as traded | **+130,110,340** |
| counterfactual: same book, no FX forwards | +113,581,511 |
| **forward-book benefit** | **+16,528,829** |
| cost of that cover (bank margin at inception + the forward legs' carry) | −9,786,254 |

**Settlements.** All 25 forward lines settled inside the horizon; none was open at 2022-10-31. Realised settlement
cash was **+₹19,557,673** across the book, from **−₹0.41 m on T01** (four BUY_USD lines struck on 08-Mar and
18-Mar, before the slide) to +₹6.54 m on T05 and +₹6.40 m on T02. The book carries exactly two SELL_USD lines —
T02-FX-3 and T05-FX-3 — and `docs/20_trade_book.md` §6.3 explains why. Each line settles at
`sign × notional × (X(τ, value_date) − K)`, with `X` the spot on the value date once settled — the formula is
carried in `trade_cashflows.csv`.

Cancellations, if any, are closed out at the CIP **mid** to the original value date, with no unwind spread, while
the same line paid `fx_forward_bank_margin_inr` on the way in. That asymmetry is worth ₹0.10/USD of notional in the
desk's favour on any cancelled line; there are none in the current book, so it costs the published P&L nothing
(`docs/30_mtm_attribution.md` §11.6).

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

They sit on **T07** (tense, USEC_MUN, 1,890 MT, traded 2022-05-25, sold to Saurashtra Castings and Alloys
Pvt Ltd (SIM) on 2022-07-26) and **T08** (tense, USEC_MUN, 1,680 MT). The window runs from the earliest effective
known date to the last settle those events move: **2022-07-28 → 2022-10-11**.

| Component | What the ticket says | Lifetime cost vs the same book without it |
|---|---|---|
| **Vessel delay and extra CFS dwell** — T07-LOG-1/2 and T08-LOG-1/2/3, known 2022-07-28 and 2022-08-16 | the July void calls and the radiation-portal referral procedure are real; the delay and dwell days are **SIM**, attributed to them | **−₹4,944,009** |
| **Buyer payment delay** — T07-PAY-1, 26 days on sale S1, known 2022-09-26 | **SIM**: the buyer's own castings receivables stretched as domestic ingot prices fell; four weeks given against post-dated cheques already held | **−₹591,206** |
| **Out-turn quality claims** — T07 lot L1 and T08 lot L2 moisture / contamination / one rejected box, including the rejected box's hold and re-export | **SIM** survey outcomes against the SPA franchise, recovered at 0.6 | **−₹3,812,527** |
| all three together | | **−₹9,352,773** (interaction −₹5,031) |

Supporting numbers: the demurrage leg costs **−₹3,254,974** over the book's life — chargeable dwell beyond
`detention_free_days` on the cleared boxes, **charged up the registered detention slabs** (T07 L1 45 boxes × 2 days
USD 3,150; T07 L2 45 × 8 days USD 17,325; T08 L2 39 × 10 days USD 20,475). At the flat first-slab rate the first
build used, the same dwell would have cost USD 11,550 less: that flat rate was a **floor** on the real bill, not an
estimate of it, and the slabbed figure is still a single combined rate for carrier detention and CFS ground rent
rather than two tariffs with their own free periods. The rejected T08 box is a separate `REJECTED_BOX_COST` leg:
45 days of hold (`rejected_box_hold_days`, ASSUMPTION) at the slabbed rate plus a USD 3,000 re-export
(`rejected_box_reexport_cost_usd_per_box`, ASSUMPTION), **USD 5,730 = −₹468,236**, paid by the desk and claimed back
at 0.6; decontamination or disposal of a genuinely contaminated box is not modelled and would cost far more. Overdue
funding routed to bucket (f) by the §7a.1 split is **−₹648,389**; the buyer paid **26 days** late, which
`days_past_due` records as 25 because it is measured at the last overdue close. Bucket (f) over the E3 window is
**−₹4,335,418**; the lifetime column above is still the one to read, because (f) books an event at the value it has
on the day it becomes known, excludes the quality discount passed through to the buyer (that is priced into the
sale contract, in (0)), and the rest of the cost then flows through (a), (e) and (g) as the market moves
(`docs/30_mtm_attribution.md` §4.1–§4.2).

**These events are no longer a source of profit.** Before the review bucket (f) was **+₹1.45 m** for the book: a
rejected box left at no cost, detention was flat, and both claims recovered 100 % (on the formula-priced T08 the
engine ignored the typed recovery altogether). The claim-recovery fraction is SIM, so it is published as a band:
at 0.0 the book makes −₹5.72 m less and T07 turns to a loss (−₹1.8 m); at 1.0, +₹3.81 m more
(`pnl_sensitivity_summary.csv`, `claim_recovery_*`).

An event's effective known date is `min(stated known_date, the milestone it moves)`. T07-PAY-1 is dated 2022-09-26
against a contractual due of 2022-09-15; taken literally the engine would have shown ₹89.6 m collected for eleven
days and then un-collected it. A desk learns a payment has not arrived on the day it was due.

### 3.3 Freight fixed early into a falling market

The desk does not hedge freight (no accessible India-lane derivative). It floats under a stop at trade-date index
+15 % and books by 10 days before the first bill of lading. The index fell through the window with only four small
up-weeks and never came closer to a stop than the 15 % it was set at, so all three FOB fixtures were taken on their
book-by dates.

| Counterfactual | ₹ |
|---|---|
| book as traded | (lifetime) **+192,054,771** |
| counterfactual: no fixture, freight floats and fixes at each B/L | +194,551,928 |
| **fixture-timing cost, lifetime** | **−2,497,157** |

This is a **competitiveness cost, not a loss on the cargo.** Under CONTRACTS §5 the CFR grade factor does not fall
when freight falls, so a later importer lands the same metal cheaper; the desk's own margin is unchanged on the
CFR tickets. The daily memo `fixture_vs_market_inr` in `mtm_daily.csv` averages **−₹1,317,503** over the leg-days
it is defined, and is a **stock** measure — never summed into P&L.

### 3.4 Credit-limit mitigation for the delayed buyer

The buyer that paid late has the smallest line on the book: **Saurashtra Castings and Alloys Pvt Ltd (SIM),
`credit_limit_inr` ₹120,000,000**. The T07 sale was worth ₹313,267,500 — 2.6× that line. It was still sold, because
the exposure that counts against a credit limit is what the desk has **invoiced and not been paid**:

| T07 sale S1 to BUY_RJK_01 | ₹ |
|---|---|
| invoice value | 313,267,500 |
| advance, received 2022-08-12 **before** the trucks moved (70 %) | 219,287,250 |
| credit extended (30 days) | **93,980,250** |
| … against a limit of | 120,000,000 |
| peak receivable actually carried | 89,239,103 (**74.4 %** of the line) |

So the 26-day delay hit a line that was three-quarters drawn on ₹89.2 m — not an unsecured ₹313 m. Three
mitigations are visible in the book and all three are policy decisions, not luck: the 70 % advance; the post-dated
cheques held as security (SIM); and the fact that the ticket was not contracted until 2022-07-26, after the same
buyer's T04 invoice cleared on **2022-07-25** (`trade_cashflows.csv`, T04 `SALE_BALANCE`, due and settled
2022-07-25; the unrolled invoice + 30 days falls on Saturday 23 July, which is where an earlier draft of this page
took the date from).

**Two different utilisation measures, and they must be quoted with their denominators.** Phase 2's P04 checks,
**at each booking**, the receivable *plus* contracted sales not covered by an advance, against the buyer's line —
peak **93 % (BUY_MUN_01)**, and that is the "Peak use" column on `docs/20_trade_book.md` §2. Phase 3 checks the
**receivable daily**, per CONTRACTS §7a.4 — peak **83.4 % (BUY_JNPT_01)**, the
`max_buyer_limit_utilisation_frac` row of `adverse_event_3_logistics_credit.csv`. Neither shows a breach on its own
measure, and `credit_limit_breach_days` is 0. They are *not* the same number and the two pages must not be read as
if they were: P2's measure evaluated **daily** rather than at bookings would exceed 100 % on BUY_MUN_01 and
BUY_RJK_01, so P04 is a booking-time control, not a daily one.

> **Correction made during integration.** Phase 3 originally summed *everything contracted and unsettled* against
> the credit limit and reported a 2.57× breach over several weeks. That measure counted the ₹219.3 m advance the
> buyer had **not yet paid** as if it were credit the desk had extended — the opposite of credit risk. CONTRACTS
> §7a.4 already separates `buyer_receivable_inr` (invoiced, unpaid) from `buyer_presettlement_inr` (contracted,
> not yet invoiced), and the limit check now uses the first. Both are still published: the
> `max_buyer_contracted_utilisation_frac` row keeps the **2.57×** figure, correctly labelled as a **performance**
> exposure. Reported beside the limit is not the same as cleared by it: if that advance does not arrive, the desk
> owns 1,890 MT of unsold Tense with its hedge already lifted. Phase 5 owns the credit tracker and should carry
> both measures and that scenario.

### 3.5 The freight spike that did not happen

`adverse_event_3_freight_stress_hypothetical.csv` prices a **+40 % container shock**
(`freight_stress_shock_frac`, MASTER_SPEC Table 6 row 4.2) on every in-window day. **Every row carries the label
`HYPOTHETICAL STRESS — not a 2022 event`.**

The book impact is **non-zero only while an FOB ticket is unfixed**, and there are exactly three such spells:
**08-Mar → 17-Mar (T01), 06-Apr → 13-Apr (T04) and 25-May → 26-May (T07)** — 16 panel days in all, with the last
non-zero day **2022-05-26**. Per ticket the worst the shock can do is **T01 −₹8,551,738 (2022-03-08)**,
**T07 −₹5,437,666 (2022-05-25)** and **T04 −₹3,703,140 (2022-04-13)**; every other trade is exactly zero on every
day. Once a fixture is booked the cargo carries no freight price risk at all (design D12) and a CFR cargo never
did. **The stress is small by construction, and that fact is the result**: this desk's freight risk is a timing
risk, not a price risk.

Two things follow that a reader should not have to infer. First, the risk layer the FOB tickets carry — a stop at
the trade-date index +15 %, live for at most ten business days — **cannot be triggered on this panel**: the largest
weekly rise in the reconstructed USEC_MUN index anywhere in Jan–Sep 2022 is +3.0 % (week to 09-Sep, after every
fixture) and between 04-Mar and 29-Jul only +0.4 %, so reaching the stop inside its window would need about five
consecutive record weeks (`docs/20_trade_book.md` §6.4). Had each FOB index nevertheless gone straight to its stop,
the same policy would have cost about USD 72,500 (≈ ₹5.6 m) — roughly five times what waiting to the book-by date
gained (§6.6 there). All three fixtures were therefore taken on their book-by
dates and the stop never bound. Second, the honest decision that *was* live — fix now or stay open to the book-by
date — is already priced: §3.3's `counterfactual_fixture_at_bl_pnl_inr` is the other side of it.

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
| book P&L over the window | +₹210,503,943 | +₹214,773,433 |
| bucket (b) LME–MCX basis | **0** by construction | **−₹8,216,965** |
| bucket (g) carry, roll and cross-terms | −₹16,892,669 | −₹4,046,744 |
| hedge benefit vs no MCX | +₹197,116,062 | +₹193,673,624 |
| peak cumulative margin outflow | −₹105,707,065 (2022-03-24) | −₹101,017,277 (2022-03-23) |
| maximum initial margin (book) | ₹95,803,038 | ₹96,424,000 |

**This is a risk disclosure, and it must not be read as a better result.** Lifetime, the mirror run finishes
**+₹18,402,493 above** the base book. That is one realisation of a two-sided risk, not evidence that a real basis
would have helped: the same path with its sign reversed is **−₹18,402,493**, and nothing in one six-month mirror makes
the favourable draw more likely. Nor is (b) the bucket that moves most — (g) moves +₹30.7 m against (b)'s −₹11.7 m,
so the two are published **jointly**: ±₹18.9 m at book level, from −₹19.2 m (T01) to +₹15.8 m (T05) per ticket. The
per-ticket spread says the same (`outputs/tables/mcx_basis_risk.csv`):

| Basis risk, lifetime, per ticket | ₹ |
|---|---|
| **worst ticket — the loss case (T01)** | **−19,206,374** |
| best ticket — the gain case (T05) | +19,173,462 |
| **range across the nine tickets** | **38,379,835** |
| mean absolute effect per ticket | 6,607,842 |
| netted book total (what a single headline would show) | +18,402,493 |

Read the **range**, not the netted total: on a book of nine tickets the netting is luck, and on one ticket the
basis is worth about ±₹1.9 crore on ₹2–5 crore of trade P&L.

**The unit-beta assumption, tested.** The engine hedges by holding the MCX basis and letting LME and FX drive the
MCX price — which is exactly an assumption that MCX moves one-for-one with duty-paid LME parity. On the mirror,
that slope is measurable and it is **not 1**:

| Daily changes, mirror M1 on duty-paid parity, 2022-03-01 → 2022-08-31 | |
|---|---|
| beta | **0.452** |
| standard error | 0.063 |
| **t against H₀: beta = 1** | **−8.67** — rejected |
| R² | 0.294 |
| observations (daily changes) | 125 |
| share of a parity move a beta-1-sized short does **not** offset | **0.548** |

On a day-to-day basis, therefore, an MCX short sized as this engine sizes it would have offset roughly **45 %** of
a duty-paid-parity move on the only observed-ish MCX series available here, not 100 %. The base run cannot show
that at all, because on the proxy the slope is 1 by construction.

None of this validates the mirror either: its provenance cannot be checked against MCX's bhavcopy, its second-month
series is partly stale, and the low R² partly reflects MCX's evening close against the LME midday official
(`docs/10_parity_model.md` §11). It is one PROXY measured against another — which is why the honest output is a
**range and a rejected assumption**, not a point estimate.

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
* **Bucket (b) is empty in base runs** because MCX is a duty-parity proxy. §5 sizes the gap on another proxy, and
  publishes it as a **two-sided per-ticket range (−₹1.92 cr to +₹1.92 cr)** rather than as the netted book number,
  which happens to be positive. §5 also rejects the unit-beta assumption the hedge sizing rests on (beta 0.45,
  t = −8.7 against 1).
* **There is no curve risk anywhere in the base run.** The MCX proxy is in contango on every panel day by
  construction, so all 13 rolls are gains and the whole ₹8.42 m of roll P&L is INR carry rather than term
  structure (§1.5). On a curve carrying the LME's own slope the rolls make ₹7.33 m, and the one roll dealt in the
  late-July backwardation loses ₹0.33 m of metal carry; a deep backwardation would have made a short roll pay.
* **Event 1's margin schedule ignores daily price limits and SPAN.** The proxy's −12.0 % move on 2022-03-08
  against a 9 % slab means a real short could have traded only at the limit that session, and the −₹105.7 m peak outflow is
  computed on a series that could print moves the real contract could not.
* **Event 2's rate is a PROXY.** "The rupee went through 80 on 14 July" is a statement about the ECB cross used
  here; the comparison to the official RBI/FBIL fixing is PENDING.
* **Event 3's freight levels are a hindsight reconstruction** and its dwell days, delay length and survey outcomes
  are simulated. What is real and dated is the 27-Jul-2022 void-call report and the direction of freight.
* **Nothing here is a credit model.** The credit numbers are the headline event 3 needs; Phase 5 owns scoring,
  the tracker and the liquidity buffer. Note in particular that a 2.57× *contracted* utilisation against a ₹120 m
  line is reported beside the limit, not against it (§3.4), and that no facility size, cash buffer or position
  limit is modelled anywhere in Phase 3: the book's own minimum cash balance is **−₹1,159,856,633 on 2022-07-20**
  on top of ₹95.8 m of initial margin, against ₹192.1 m of lifetime P&L. That is an output of the book, not a
  constraint it was tested against.
* **The adverse events are not the book's largest exposures.** All three simulated operational events together
  cost **−₹9.35 m**, 4.9 % of the result. The registered ASSUMPTION bands move it by far more:
  `docs/30_mtm_attribution.md` §13.9 re-prices the book through the desk's own rules under each registered value
  and finds a spread of **−₹10.5 cr to +₹33.4 cr** — the book **loses money** at two of the four
  `domestic_anchor_premium_inr_t` values and breaks even at about −₹38,700/t. Event 1's hedge benefit and event 2's
  forward-book benefit are measured on a book whose headline sign that one assumption decides.

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
| Freight lane levels; grade factors; payloads, free days, slabbed detention rates, rejected-box hold days and re-export cost, port charges, WC rate, margin used | **ASSUMPTION** (freight levels and the lag-2 grade mix are hindsight reconstructions) |
| Counterparties, vessels, dwell days, survey outcomes, the payment delay and its length | **SIM** |
