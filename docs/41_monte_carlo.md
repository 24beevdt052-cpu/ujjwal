# 41 — Monte Carlo stress testing (MASTER_SPEC Table 6 row 4.2 ★)

> **ACADEMIC SIMULATION — not actual trades.** The book revalued here is simulated: every counterparty, vessel and
> operational outcome is SIM. LME aluminium prices are **DIRECT** (LME official cash, republished by Westmetall).
> USD/INR is a **PROXY** (ECB cross rates). The MCX hedge series is a **PROXY** (duty-paid import parity, unit beta to
> LME × FX by construction). Freight levels are an **ASSUMPTION** (a hindsight-calibrated reconstruction). The MCX
> basis in the §5.4 sensitivity comes from a third-party mirror (**PROXY**, not checkable against MCX bhavcopies).
> Every rupee below comes out of `desk.mtm.valuation.revalue_book`, so it inherits all of that.
>
> **This page is about risk, not the result.** Where it mentions the book's headline P&L (₹195.9 m at 2022-08-31,
> ₹192.1 m at 2022-10-31), read it with its band: across the registered `domestic_anchor_premium_inr_t` grid the same
> nine tickets make anywhere from **−₹105.4 m to +₹334.3 m**, with break-even at −38,702 ₹/t *inside* the grid
> (`pnl_sensitivity_sign_robustness.csv`). The headline is **not sign-robust**, and nothing on this page changes that.

```sh
cd ujjwal   # the repository root
DESK_OFFLINE=1 .venv/bin/python -c "import desk.risk.run_mc as m; m.main()"   # ~70 s, ~200 MB peak
DESK_OFFLINE=1 .venv/bin/python -m pytest -q tests/test_risk_mc.py            # 22 tests, ~2 s
```

Code: `desk/risk/monte_carlo.py` (covariance, simulation, revaluation loop, statistics, stress helpers) and
`desk/risk/run_mc.py` (the stage: snapshots, variants, tables, charts). Parameters: `config/params/risk.yaml`, section
"Phase 4.2 Monte Carlo". The shared stresses read `freight_stress_shock_frac` (logistics.yaml) and `qco_stress_*`
(regulatory.yaml). Two back-to-back runs give byte-identical `mc_*.csv` files.

---

## 0. The finding on one page

Three snapshot dates were fixed by rule before any result existed (§2.2). On each one the book as it stood at that
close is revalued on 10,000 joint 10-business-day moves of LME, USD/INR and freight, and then under the five Table 6
stresses.

| | 8-Mar-2022 (day after the ATH) | 21-Apr-2022 (peak gross LME) | 27-Jul-2022 (peak BUY_RJK_01 exposure) |
|---|---|---|---|
| Position | T01 only: 1,817 MT LME-long, **no hedge yet** | T01–T05: 4,450 MT physical, −3,854 MT MCX, **net +596 MT** | T08 open: 1,223 MT physical, −1,251 MT MCX, **net −29 MT** |
| 95 % VaR, 10 days | ₹56.1 m | ₹17.0 m | ₹0.71 m |
| 99 % VaR [MC 95 % interval] | **₹76.3 m** [74.4, 78.6] | **₹23.0 m** [22.6, 23.7] | **₹1.00 m** [0.97, 1.04] |
| 99 % expected shortfall | ₹85.2 m | ₹25.7 m | ₹1.15 m |
| 99 % VaR with an MCX basis factor (PROXY) | ₹76.3 m (no MCX yet) | **₹32.8 m** (+43 %) | **₹14.6 m** (14.6×) |
| LME −15 % | −₹73.5 m (1.35th pctile) | −₹22.2 m (1.37th); unhedged −₹165.9 m | **+₹0.8 m**; unhedged −₹35.0 m |
| INR −5 % (USD/INR +5 %) | +₹0.1 m | −₹1.4 m | +₹0.4 m |
| Freight +40 % (HYPOTHETICAL) | −₹8.6 m | ₹0 (all freight fixed) | ₹0 |
| BUY_RJK_01 defaults | ₹0 (no sale yet) | ₹0 (no RJK sale yet) | **−₹28.3 m**, worse than every path (28× VaR99) |
| BIS-QCO hold + demurrage (HYPOTHETICAL) | −₹14.3 m (34th pctile) | **−₹45.6 m**, worse than every path (2.0× VaR99) | **−₹18.3 m**, worse than every path (18× VaR99) |

1. **The hedge is the risk number.** The same physical book that loses ₹165.9 m on an LME −15 % move unhedged loses
   ₹22.2 m hedged on 21-Apr. By 27-Jul the net position is 29 MT *short* and the 99 % VaR is ₹1.0 m. On 8-Mar
   (unhedged) and 21-Apr (hedged) LME −15 % sits at about the 99th percentile, because LME dominates what is left.
2. **That small number depends on unit beta.** MCX is priced here at unit beta to LME × USD/INR, so the hedge offsets
   the metal exactly. Add a basis factor estimated from the third-party mirror (weekly basis changes correlate −0.76
   with LME) and the 99 % VaR rises from ₹23.0 m to ₹32.8 m on 21-Apr and from ₹1.0 m to ₹14.6 m on 27-Jul. On a
   hedged book, **basis risk is most of the market risk**, and the base simulation cannot see it.
3. **The non-market stresses are where the losses are.** A buyer default and a clearance hold are jumps, not moves
   in a covariance matrix, so no path of the Monte Carlo can produce them. On 27-Jul the default costs 28 times the
   99 % VaR; combined with LME −15 % it costs ₹68.9 m, because the cargo the desk keeps is resold into the fallen
   market (§4.4).
4. **The INR and freight stresses are extreme moves that barely matter.** USD/INR +5 % in 10 days is a 5.5-sigma move
   on the window covariance, and freight +40 % is a 14-sigma move. The book's net FX delta is small, *because* the
   MCX leg is assumed to offset the physical-plus-forwards leg: ±₹47 m each way on 21-Apr (§4.2). Freight is already
   fixed on every open cargo on the two later snapshot dates.
5. **The distribution shape is secondary; the covariance span and the factor list are not.** A Student-t or a
   bootstrap of window days moves the 99 % VaR by −7 % to +22 % (§5). A point-in-time covariance moves it by −3 % to
   +3 %. Adding the basis moves it by 0 % (no MCX yet on 8-Mar), +43 % and ×14.6.

---

## 1. "Why Monte Carlo, and not just VaR?"

*(written to be quoted in the interview pack)*

Delta-normal VaR tells you how big a normal day is. A physical desk needs to know what a bad fortnight does to
*this* book, with its averaging clauses, its hedges and its FX conversions all reacting together. So I shocked
LME, the rupee and freight jointly, 10,000 times, over a 10-day horizon, with the covariance they actually had between
March and August 2022. Each path goes through the same valuation function that produces the daily P&L, so the risk
number and the P&L number cannot disagree. On 21 April, my peak metal day, the 99 % 10-day loss was ₹23 m on a book
carrying 4,450 tonnes of physical aluminium. Without the MCX hedge, LME −15 % alone cost ₹166 m. But the simulation
also showed me what it cannot see. Once I let the LME–MCX basis move the way a third-party MCX series says it moved,
the 99 % number rose by 43 %. On 27 July it went from ₹1 m to ₹15 m. And the two stresses that really hurt, a buyer
walking away and a clearance hold at the port, sit outside every one of the 10,000 paths. So I use Monte Carlo to size
market risk, and scenarios for everything a covariance matrix cannot contain.

---

## 2. Method

### 2.1 Factors and how they reach the book

| Factor | Series | Change | Shock key in `revalue_book` | Flag |
|---|---|---|---|---|
| LME | `lme_cash_usd_t` | log return | `lme_cash_logret` | DIRECT |
| USD/INR | `usdinr` | log return | `usdinr_logret` (the CBIC customs rate moves with it) | PROXY |
| Freight | `freight_usec_mun_usd_t` | log return | `freight_logret`, applied to **both** lanes | ASSUMPTION |
| MCX basis (§5.4 only) | mirror near-month close − duty-parity theo, ₹/kg | absolute change | `mcx_basis_abs`, with `mcx_hold_basis=False` | PROXY |

* **One freight factor.** JEA_NSA is 0.2255 × USEC_MUN in every week of the panel (fix log #15). A second lane factor
  would be a copy with correlation 1. This also means the model cannot show a lane-specific freight shock.
* **MCX moves with the shocked LME and USD/INR at the held basis** in every base run (docs/30 §5.1). That is the
  unit-beta assumption. The mirror measures beta at 0.452 on daily changes (t = −8.67 against 1), but asynchronous
  MCX/LME closes bias that down: 0.75 weekly and 0.94 close-time-matched (`var_mcx_beta.csv`, docs/40 §4.3). §5.4
  relaxes the assumption with a weekly-estimated basis factor.
* **Not simulated:** the LME cash–3M spread, grade factors, interest rates and the domestic anchor premium. These
  are respectively a small carry effect, a reconstruction with no market return series, a funding effect, and a
  parameter uncertainty rather than a market move (§7).

### 2.2 Snapshot dates, declared before any result (`mc_snapshot_rules`)

| Id | Rule | Date | Why this date |
|---|---|---|---|
| `ATH_PLUS_1` | first panel day after the window's highest LME cash close (3,984.5 USD/t on 7-Mar) | **2022-03-08** | The spec's crash narrative. It is also the book's first day: T01 is long 2,520 MT of Zorba, and its MCX hedge only enters on 9-Mar. |
| `PEAK_GROSS_LME` | window day with the largest BOOK `lme_delta_physical_mt` | **2022-04-21** | The most metal the desk carried (4,450.4 MT). This is where hedge slippage matters most. |
| `PEAK_BUYER_CONTRACTED` | first window day on which BUY_RJK_01's contracted exposure is at its window maximum | **2022-07-27** | ₹308.5 m, 2.57× its ₹120 m limit: the day the buyer-default stress has most to bite on. The rule's own date, 26-Jul, is an MCX exit day, so the snapshot moves to 27-Jul. |

The rules read prices, exposures and credit tables only, never P&L. Any date a rule picks that is an MCX exit or
roll-out day moves to the next panel day. On such a close the valuation still carries the exiting contract, which is
the Phase 4.1 finding (docs/40 §7.1). `mc_snapshots.csv` then measures what is left:
`lme_delta_ending_same_day_flows_inr_per_usd_t`. This is the delta of P&L flows that fix or settle at that close and
do not continue past it. Today's variation margin on an MCX line that stays open is excluded, because that *is* the
hedge. The value is 0 on 8-Mar and 27-Jul. On 21-Apr it is −₹13 per USD/t, against a book delta of ₹45,439, and
comes from T05's entry transaction cost.

Two facts about 21-Apr worth knowing: T05 (bought that day) and its MCX hedge both enter at that close, and T03's
first-lot forward had settled on 20-Apr while its second was booked on 22-Apr. So the forwards FX delta is USD 1.48 m
lower that day than on either side: the second lot's payable is unhedged for one day. Both are real positions, not
artefacts.

**Base value reconciles to Phase 3.** On each snapshot, `revalue_book` (which excludes funding) plus funding
accrued to date equals `attribution_daily.csv` BOOK `cum_pnl_inr` to within ₹0.03 (`reconciliation_diff_inr`). The
stage raises if any difference exceeds ₹1.

### 2.3 Horizon (`mc_horizon_bdays` = 10)

**Ten business days** is the Basel holding period. It is also roughly how long a physical desk needs to re-hedge or
re-sell a cargo-sized position: an MCX hedge can be lifted in a day, a sale to a new smelter takes a week or two. The
book is re-marked **instantaneously** at the snapshot close under a 10-day-sized move. The clock, contracts and
events are held, and nothing fixes, settles, rolls or gets re-hedged over the horizon. P&L is `revalue_book(shocked)
− revalue_book(unshocked)`. Funding cancels.

A **to-settlement** horizon is published only as a memo (`normal_window_to_settlement`): the business days until the
last open ticket closes (79, 78 and 41 days). It holds the snapshot position static all that time, which the desk
never did. On 8-Mar, for example, T01 was hedged the next morning. It is **not a risk number**.

### 2.4 The covariance

The spec says "historical covariance over the backtest window". The window is 2022-03-01 … 2022-08-31: 126 daily
changes and 26 complete W-FRI weeks.

**Daily versus weekly.** LME and USD/INR are daily series, so their variances and their correlation come from daily
log returns. Freight is assessed weekly and carried forward on the daily calendar (CONTRACTS §3). Its daily
"returns" are four zeros and a jump, which dilutes every correlation it enters. So freight's variance and its
correlations with LME and USD/INR come from **complete weeks**. The weekly variance is divided by 5 to put it in daily
units, and each cross-covariance is `ρ_weekly × σ_daily,i × σ_daily,j`. The MCX basis gets the same weekly treatment
for a different reason. Its daily changes are mostly close-time noise that reverses the next day: the daily
variance ratio over 10 days is 0.12, and the weekly σ is about a third of the daily σ × √5. A daily estimate scaled by
√10 would overstate it about threefold. Mixing samples does not guarantee a positive semi-definite matrix, so
`nearest_psd_corr` checks every matrix. None needed repair: the smallest eigenvalue of the window correlation matrix
is 0.76, and 0.23 with the basis added.

**Window covariance, daily units** (`mc_covariance.csv`, `covariance_id = window`):

| | LME | USD/INR | Freight | σ daily | σ 10 days | sample |
|---|---|---|---|---|---|---|
| LME | 5.3669e-4 | −9.457e-7 | −3.709e-5 | 2.317 % | **7.33 %** | 126 days |
| USD/INR | | 7.8925e-6 | −1.962e-6 | 0.281 % | **0.89 %** | 126 days |
| Freight | | | 5.7589e-5 | 0.759 % | **2.40 %** | 26 weeks (1.697 %/week) |

**Correlations:**

| | LME | USD/INR | Freight | MCX basis (§5.4) |
|---|---|---|---|---|
| LME | 1 | −0.015 (daily) | −0.211 (weekly) | **−0.758** (weekly) |
| USD/INR | | 1 | −0.092 (weekly) | −0.143 (weekly) |
| Freight | | | 1 | +0.201 (weekly) |
| MCX basis σ | | | | ₹4.02/kg a week → ₹5.69/kg over 10 days |

With 26 weekly observations a correlation has a standard error of about 0.2. Only the LME–basis correlation is
clearly distinguishable from zero. Its sign is what beta 0.452 means: when LME falls, the mirror MCX falls less than
parity, so the basis rises.

**Point-in-time spans** (`mc_pit_lookback_days` = 126). Using the window covariance on 8-Mar uses returns from after
8-Mar. That is hindsight, fine for describing risk after the fact but not a number a desk could have had. The
`normal_pit` variant uses the 126 daily changes, and the complete weeks inside them, that end at each snapshot close:

| Span | σ LME 10 d | σ USD/INR 10 d | σ freight 10 d | ρ LME–FX | ρ LME–freight | ρ FX–freight |
|---|---|---|---|---|---|---|
| window (base) | 7.33 % | 0.89 % | 2.40 % | −0.015 | −0.211 | −0.092 |
| to 2022-03-08 (from 2021-09-09) | 7.16 % | 0.91 % | 2.45 % | +0.159 | +0.167 | +0.001 |
| to 2022-04-21 (from 2021-10-21) | 7.47 % | 0.95 % | 2.69 % | +0.173 | +0.189 | +0.130 |
| to 2022-07-27 (from 2022-01-26) | 7.67 % | 0.93 % | 2.41 % | +0.151 | −0.154 | −0.108 |

The vol levels hardly differ. The six months before March 2022 were already volatile. The LME–USD/INR correlation
changes sign (+0.15 to +0.17 before, −0.015 in the window), but the book's net FX delta is small enough that this
barely registers (§5.3).

### 2.5 Is a multivariate normal adequate?

Not for daily LME returns, and it matters less at 10 days than it looks (`mc_factor_stats.csv`):

| Window statistic | LME daily | USD/INR daily | LME weekly | Freight weekly | Basis weekly |
|---|---|---|---|---|---|
| skew | −1.37 | +0.29 | +0.91 | −0.25 | −0.00 |
| excess kurtosis | **6.00** | 0.61 | 1.35 | −1.03 | −1.23 |
| Jarque–Bera p | < 0.001 | 0.20 | 0.13 | 0.48 | 0.44 |
| 10-day variance ratio | **0.62** | 0.63 | — | — | — |

* The LME daily tail is one day: a −12.95 % log return on 8-Mar-2022, a 5.6-sigma day on the window's own daily σ of
  2.32 %. At weekly frequency normality is not rejected.
* The 10-day variance ratios of 0.62–0.63 say that on this window **√time overstates** 10-day variance: daily moves
  partly reversed. With about 12 independent 10-day blocks, that estimate is itself noisy. The base keeps √time,
  which is conservative here.
* Hence two tail sensitivities rather than a claim of normality. One is a **multivariate Student-t**
  (`mc_student_t_dof` = 5, same covariance, one chi-square per path: a normal whose variance is uncertain over the
  horizon). The other is an **iid bootstrap of whole window days**, 10 per path, demeaned, which keeps the 8-Mar day and
  the empirical same-day co-movement.
* **Zero mean** everywhere. The window's LME drift, about −0.3 % a day, *is* the crash, and simulating it forward
  would put 2022's realised direction into a risk number. The published path means (+₹1.6 m on 8-Mar, for example) are
  lognormal convexity plus sampling error of about ₹0.4 m.

### 2.6 Full revaluation, and why path by path

Every path goes through `desk.mtm.valuation.revalue_book(book, H, t, shocks=…, cache=…)`: the function behind the
daily MTM, the attribution and the exposures. `revalue_book` is documented to take equal-length arrays. But an
array-valued freight shock raises inside `shock_state` (`if freight != M.freight_usd_t` compares two dicts of numpy
arrays). So the stage loops over paths with scalar shocks, in batches of 1,000. That costs 0.1–0.6 ms a call, about
70 s for all 180,000 revaluations and roughly 200 MB. `tests/test_risk_mc.py` checks the loop against the API's own
vectorised call where it works (LME and USD/INR arrays) and finds the same numbers.

The delta(-gamma) fallback in the brief was not needed. Its linear half is still published as a control
(`mc_delta_check.csv`). Phase 3's bump-and-revalue deltas times the same factor moves give a 99 % VaR within 0.5 % of
full revaluation (₹75.98 m against ₹76.33 m on 8-Mar, ₹23.00 m against ₹22.99 m on 21-Apr, ₹0.996 m against
₹0.995 m on 27-Jul), with a path correlation of 0.99994 or better. The book is nearly linear over a 10-day horizon.
Full revaluation adds nothing to the size of the number, but it guarantees the number is the P&L engine's own.

### 2.7 Statistics

VaR and ES are the historical-simulation estimators on the 10,000 simulated P&Ls, both reported as positive losses.
With k = ⌈(1 − c) × n⌉ (100 paths at 99 %, 500 at 95 %), VaR is minus the k-th worst P&L and ES is minus the mean of
the k worst. `var99_ci95_*` is the binomial interval of that order statistic, which comes to about ±2.5 %. It
measures **Monte Carlo sampling error only, not model error.** A stress's `mc_percentile_frac` is the share of paths
with P&L at or below it. One random stream (`default_rng(desk.RNG_SEED)`: normals, chi-square, bootstrap picks) is
drawn once and reused by every snapshot and variant (common random numbers), so the differences in §5 come from the
model, not from the draw.

---

## 3. Results

### 3.1 All variants (`mc_summary.csv`, `mc_pnl_quantiles.csv`)

| Snapshot | Variant | Horizon | 95 % VaR | 99 % VaR | 99 % ES | P(loss) |
|---|---|---|---|---|---|---|
| 8-Mar | **normal, window (BASE)** | 10 | ₹56.1 m | **₹76.3 m** | ₹85.2 m | 49.4 % |
| | Student-t (ν = 5) | 10 | ₹53.2 m | ₹83.5 m | ₹108.1 m | 49.4 % |
| | bootstrap of window days | 10 | ₹59.7 m | ₹87.3 m | ₹101.9 m | 48.1 % |
| | normal, point-in-time | 10 | ₹54.5 m | ₹74.0 m | ₹82.5 m | 49.4 % |
| | + MCX basis factor (PROXY) | 10 | ₹56.1 m | ₹76.3 m | ₹85.2 m | 49.4 % |
| | *memo: static to settlement* | 79 | *₹142.4 m* | *₹186.3 m* | *₹204.3 m* | |
| 21-Apr | **normal, window (BASE)** | 10 | ₹17.0 m | **₹23.0 m** | ₹25.7 m | 49.6 % |
| | Student-t (ν = 5) | 10 | ₹16.0 m | ₹25.4 m | ₹32.6 m | 49.6 % |
| | bootstrap of window days | 10 | ₹18.0 m | ₹26.4 m | ₹30.8 m | 48.0 % |
| | normal, point-in-time | 10 | ₹17.2 m | ₹23.2 m | ₹25.9 m | 49.6 % |
| | + MCX basis factor (PROXY) | 10 | ₹24.0 m | **₹32.8 m** | ₹36.6 m | 49.6 % |
| | *memo: static to settlement* | 78 | *₹42.8 m* | *₹56.3 m* | *₹61.4 m* | |
| 27-Jul | **normal, window (BASE)** | 10 | ₹0.71 m | **₹1.00 m** | ₹1.15 m | 50.5 % |
| | Student-t (ν = 5) | 10 | ₹0.69 m | ₹1.21 m | ₹1.61 m | 50.5 % |
| | bootstrap of window days | 10 | ₹0.66 m | ₹0.93 m | ₹1.05 m | 52.2 % |
| | normal, point-in-time | 10 | ₹0.73 m | ₹1.02 m | ₹1.18 m | 50.5 % |
| | + MCX basis factor (PROXY) | 10 | ₹10.4 m | **₹14.6 m** | ₹16.5 m | 50.1 % |
| | *memo: static to settlement* | 41 | *₹1.53 m* | *₹2.19 m* | *₹2.56 m* | |

### 3.2 What drives the tail (`mc_es_contributions.csv`, base variant)

Each ticket's mean P&L over the book's 100 worst paths. The contributions add up to −ES99 exactly.

| 21-Apr | Net LME (MT) | ES99 contribution | Standalone 99 % VaR |
|---|---|---|---|
| T04 | +508.8 | −₹22.1 m | ₹20.2 m |
| T01 | +332.6 | −₹14.1 m | ₹12.9 m |
| T03 | +157.6 | −₹6.9 m | ₹6.5 m |
| T05 | −4.4 | +₹0.2 m | ₹0.2 m |
| T02 | **−398.3** | **+₹17.3 m** | ₹17.9 m |
| Book | +596.3 | −₹25.7 m | ₹23.0 m |

T04 carries most of the tail. It was 981.7 MT physical against 472.9 MT of MCX: about half-hedged. T02 is net
*short*: its sale prices off the MCX average of 19–29 April while its purchase floats on the May LME average
(docs/30 §5). So it gains in the paths where the rest lose. The per-ticket standalone VaRs add up to ₹57.7 m against a book VaR of ₹23.0 m. On 8-Mar all of the tail is
T01. On 27-Jul 99 % of it is T08 (−₹1.14 m).

### 3.3 Against Phase 4.1

Phase 4.1 publishes one-day 95 % VaR using the previous close's exposures, so the VaR dated the day after each
snapshot is the comparable one (`var_daily.csv`). Scaled by √10 for scale only (the methods differ in covariance and
factors):

| Position date | GARCH 1-day × √10 | Historical 250 d × √10 | Historical 60 d × √10 | MC 10-day 95 % VaR |
|---|---|---|---|---|
| 2022-03-08 | **₹137.7 m** | ₹47.5 m | ₹66.9 m | ₹56.1 m |
| 2022-04-21 | ₹14.3 m | ₹15.1 m | ₹21.9 m | ₹17.0 m |
| 2022-07-27 | ₹0.44 m | ₹0.60 m | ₹0.56 m | ₹0.71 m |

Away from the shock, the numbers agree within the spread of the methods. On 8-Mar they do not. At that close GARCH
forecast 5.40 % daily LME volatility for 9-Mar, while the window covariance averages six months to 2.32 %. **A
six-month covariance understates risk in the days right after a regime break**, and the spec's window choice cannot
fix that (§7).

---

## 4. The five stresses on the distribution

Every stress is revalued through the same `revalue_book`, at the same close, with the same held clock
(`mc_stress_scenarios.csv`; per-ticket workings in `mc_stress_details.csv`). "Percentile" is the share of the 10,000
base paths with P&L at or below the stress. "σ" is the size of the shocked factor move in 10-day standard deviations
of the window covariance.

| Stress | σ at 10 d | 8-Mar | 21-Apr | 27-Jul | Beyond the 99th percentile? |
|---|---|---|---|---|---|
| LME −15 % | −2.22 (normal prob. 1.3 %) | −₹73.5 m, 1.35 % | −₹22.2 m, 1.37 % | +₹0.8 m, 98.4 % | No: at about the 99 % VaR on 8-Mar and 21-Apr |
| INR −5 % (USD/INR +5 %) | +5.49 | +₹0.1 m, 49.5 % | −₹1.4 m, 44.1 % | +₹0.4 m, 83.9 % | No |
| Freight +40 % *(HYPOTHETICAL)* | +14.0 | −₹8.6 m, 40.1 % | ₹0 | ₹0 | No |
| BUY_RJK_01 default | n/a (no factor) | ₹0 | ₹0 | **−₹28.3 m**, below every path | **Yes on 27-Jul** (28× VaR99) |
| BIS-QCO hold + demurrage *(HYPOTHETICAL)* | n/a (no factor) | −₹14.3 m, 34.2 % | **−₹45.6 m**, below every path | **−₹18.3 m**, below every path | **Yes on 21-Apr and 27-Jul** |

### 4.1 LME −15 %

The move is `lme_cash_logret = ln 0.85`. On 8-Mar-2022 alone LME cash had a −12.95 % log return. MCX moves with it at
the held basis, so on a hedged date only the net position loses. It is a 2.22-sigma 10-day move on the window
covariance. On 8-Mar (unhedged) and 21-Apr (hedged, net long) it lands at about the 99 % VaR, as it should when LME
dominates the book. The **hedge-removed memo** (`lme_minus_15pct_unhedged_memo`, the same book with every MCX leg
dropped) shows what the hedge was worth:

| | Hedged | Without the MCX legs |
|---|---|---|
| 8-Mar | −₹73.5 m | −₹73.5 m (no hedge existed yet) |
| 21-Apr | −₹22.2 m | **−₹165.9 m** |
| 27-Jul | +₹0.8 m | −₹35.0 m |

After the fact: over the 10 business days that followed 21-Apr (to 6-May) LME cash actually fell 13.2 %, a −1.93σ
move. That was the E1 crash fortnight (`expost_memo_*` in `mc_snapshots.csv`; reporting only, nothing reads it).

### 4.2 INR −5 %

Convention (`mc_stress_usdinr_move_frac`): the quoted USD/INR rate rises 5 % (`ln 1.05`). The rupee's own USD value
falls 4.76 %; a 5 % fall in that measure would be USD/INR +5.26 %. In 10 days this is a 5.49-sigma move: the window
saw about 5 % over six months. The P&L is small because the netted FX delta is small. On 21-Apr the physical-plus-
forwards leg is long USD 12.28 m, worth about **+₹46.8 m** for +5 %. The MCX leg is short USD 12.57 m, worth about
**−₹47.9 m** (exposure × rate × 5 %, derived from `mc_snapshots.csv`). **The offset is exactly the unit-beta
assumption**, the one the mirror rejects. If MCX tracked parity at the mirror's weekly beta of 0.75, about three-quarters
of that offset would be there; at the daily 0.452 (biased down by asynchronous closes) less than half.

### 4.3 Freight +40 % (HYPOTHETICAL)

India-inbound container freight **fell** through March–August 2022 (docs/research/freight_notes.md; the window's
weekly USEC lane averaged −1.7 % a week). This is a labelled hypothetical spike, not a replay. At 14 sigma it is far
outside anything the window's freight volatility produces. It costs −₹8.6 m on 8-Mar, the only snapshot with unfixed
freight (T01, FOB). That equals Phase 3's own freight stress on the same date to the rupee (`mc_controls.csv`, PASS).
It is zero on 21-Apr and 27-Jul because by then the open FOB tickets had booked their fixtures, and a CFR cargo carries
no freight price risk (design D12). Between those dates it is not always zero: Phase 3's daily version of this stress
has three non-zero spells, the last ending 26-May (docs/31 §3.5).

### 4.4 Buyer default: BUY_RJK_01

* **Who.** BUY_RJK_01 (`mc_buyer_default_buyer_id`), chosen for performance exposure, not rupee exposure. The desk
  relied on its advances at 1.26×, 1.53× and 1.83× a ₹120 m limit (fix log open item 1). It has no open flow on 8-Mar or
  21-Apr, so the stress is ₹0 there and the table says so.
* **What `StressEvent("buyer_default")` does, and why it is not used as-is.** The API writes off every future flow
  with the buyer at a single `recovery_frac`. That is right for cargo already released to the buyer, an unsecured
  receivable. It is wrong for cargo still in the desk's hands, which the desk keeps and resells. So, per sale and pro
  rata by B/L tonnage:
  * **Released lots:** lose receipts × (1 − `mc_buyer_default_recovery_frac` = 0.25).
  * **Unreleased lots:** lose max(0, lost receipts − retained MT × import replacement mark ×
    (1 − `mc_buyer_default_resale_discount_frac` = 0.05)).

  The implied per-ticket recovery is then passed to the API, so the number still comes out of `revalue_book`. A test
  checks that the API reproduces the computed loss to ₹1.
* **27-Jul.** All of RJK's open flow is T07-S1: ₹308.5 m of receipts on 1,890 MT, none of it released (T07's lots
  release on 3-Aug and 16-Aug). The replacement mark is ₹156,064/t, so resale at a 5 % discount returns ₹280.2 m. The
  loss is **₹28.3 m**, the API recovery 0.908. Because nothing was released, the 0 % and 50 % recovery memo rows give
  the same ₹28.3 m.
* **The credit number overstates the loss; the market makes it worse.** The 2.57×-limit contracted exposure in
  `buyer_credit_exposure_by_trade_daily.csv` (₹308.5 m) is not the loss. The desk still owns the metal, so the loss
  is the lost margin plus the resale discount.
  But T07's MCX hedge was lifted when the sale was contracted on 26-Jul, so the retained cargo is **unhedged**.
  Combined with LME −15 % (`buyer_default_with_lme_minus_15pct_memo`) the replacement mark falls to ₹133,014/t and the
  book loses **₹68.9 m**. That is wrong-way risk: a small foundry is most likely to walk away exactly when prices
  have fallen below its contract.
* **Why the MC cannot produce it.** A default is a jump in a counterparty's behaviour, not a move in LME, USD/INR or
  freight. No covariance matrix of market returns contains it, so it sits below every simulated path. It must be
  managed by limits, advances and scoring (Phase 5), not by VaR.

### 4.5 BIS-QCO hold + demurrage (HYPOTHETICAL policy)

No BIS quality-control order applied to aluminium scrap in 2022 (`bis_qco_scrap_in_force_2022` = false, VERIFIED).
The first Mines-ministry QCOs came in August 2023 and did not cover scrap. This is a plausible policy shock, not a
replay.

The stress is `StressEvent("qco_hold", delay_days=21, rejection_frac=0.10, rejected_loss_frac=0.15)` from
regulatory.yaml. The API charges 21 extra days at the first-slab USD 35 per box-day on every box of a ticket, plus a
15 % loss on 10 % of the unsold (or, if sold, whole) tonnage at the replacement mark. A clearance-stage QCO bites at
the Bill of Entry, so it is applied only to tickets with at least one lot not yet released (`mc_qco_uncleared_only`):

| | Tickets | Boxes | Demurrage (boxes × 21 × USD 35 × USD/INR) | Rejection (remainder) | Total |
|---|---|---|---|---|---|
| 8-Mar | T01 | 120 | ₹6.8 m | ₹7.5 m | −₹14.3 m |
| 21-Apr | T01–T05 | 388 | ₹21.7 m | ₹23.8 m | **−₹45.6 m** |
| 27-Jul | T07, T08 | 170 | ₹10.0 m | ₹8.4 m | **−₹18.3 m** |

The API applied to every ticket on the book (`qco_hold_all_tickets_memo`) gives −₹67.4 m on 27-Jul. That overstates
the stress, because it charges dwell on cargo released months earlier. Even the scoped version counts every box of a
ticket with one uncleared lot (T02 on 21-Apr). The extra finance cost of 21 days' delay is **not** included, and the
detention rate is the first slab only, so the stress is a floor on its own assumptions. On 8-Mar the QCO stress lands
at the 34th percentile because T01's unhedged market risk is so large. On the hedged dates it is beyond every path:
twice the 99 % VaR on 21-Apr, 18 times on 27-Jul.

### 4.6 Which stresses are beyond the 99th percentile, and why

* **Beyond:** the buyer default (27-Jul) and the QCO hold (21-Apr, 27-Jul). Neither is a market move, so the
  simulation's distribution does not contain them at any probability.
* **At:** LME −15 % on 8-Mar and 21-Apr. It is a 2.2-sigma LME move, and LME is the book's dominant factor.
* **Inside:** INR −5 % and freight +40 %. These are extreme *factor* moves (5.5σ and 14σ) against small *book*
  exposures, and that smallness rests on the unit-beta MCX offset and on freight being fixed.
* The plain reading: **on this book the Monte Carlo measures the residual metal and FX position, and the stresses
  measure the business.**

---

## 5. Sensitivities

### 5.1 Student-t (ν = 5)
99 % VaR +9 % (8-Mar), +10 % (21-Apr), +22 % (27-Jul). 99 % ES +27 %, +27 %, +40 %. 95 % VaR 3–6 % *lower*. At equal
variance a t puts less mass at moderate losses and more in the far tail. For a linear book the theoretical ratios are
+12 % (99 % VaR), +29 % (99 % ES) and −5 % (95 % VaR) on every date, and the book is linear to within 0.5 % (§2.6). So
the spread across dates, and the +22 % on 27-Jul in particular, is sampling error in a 100-path tail, not a
property of that book.

### 5.2 Bootstrap of window days
99 % VaR +14 %, +15 %, −7 %. About 7.7 % of paths contain 8-Mar-2022, the −12.95 % day, and on the first two dates
they make up the tail. On 27-Jul the book is short LME, so the same day helps. Caveat: freight's carried daily series
also resamples its steady fall (−1.7 % a week, as large as its weekly σ), so the bootstrap's 10-day freight σ is 3.2 %
against 2.4 % in the base. This is immaterial except on 8-Mar.

### 5.3 Point-in-time covariance (no hindsight)
99 % VaR −3.0 %, +0.9 %, +2.7 %. Hindsight in the spec's window covariance does not drive the level on these dates.
The LME–USD/INR correlation flips sign between the spans, but it is multiplied by a small net FX delta.

### 5.4 MCX basis factor (PROXY)
99 % VaR unchanged on 8-Mar (no MCX position), **+43 %** on 21-Apr (₹23.0 m → ₹32.8 m) and **×14.6** on 27-Jul
(₹1.0 m → ₹14.6 m). The basis delta is −₹888,758 per ₹/kg on 21-Apr and −₹1,150,000 on 27-Jul. The factor is a 10-day
σ of ₹5.69/kg correlated −0.76 with LME, so a falling LME comes with a rising basis, which a short MCX hedge pays for.
This is the covariance version of the mirror's beta below one (daily 0.452, weekly 0.75, docs/40 §4.3); being
estimated on weekly changes, it is not driven by the daily close-time artefact. It is a **sensitivity, not base**, for three reasons:
the mirror's provenance cannot be checked against MCX bhavcopies, it rests on 26 weekly observations, and "additive
basis on every contract month" is itself a simplification. What it shows is the size of what unit beta hides, and on
a hedged book that is most of the market risk.

### 5.5 Static to settlement (memo)
Scaled to 79, 78 and 41 business days, the 99 % VaR rises +144 %, +145 % and +120 %. √time alone would give +181 %,
+179 % and +102 %. The gap is the lognormal: a long position's loss is capped as the price falls, a short position's is
not (27-Jul is net short). The desk did not hold these positions static, so this is not a risk number, and it is
published only because the brief asked for it.

---

## 6. After the fact (memo, hindsight)

The factor moves that actually followed each snapshot over 10 business days (`expost_memo_*`), in 10-day sigmas of the
window covariance. The book changed over those days, so this is **not** a backtest: three dates cannot test a
99 % number.

| Snapshot → +10 days | LME cash | USD/INR | Freight |
|---|---|---|---|
| 8-Mar → 22-Mar | +1.4 % (+0.19σ) | −1.2 % (−1.37σ) | −4.8 % (−2.05σ) |
| 21-Apr → 6-May | **−13.2 % (−1.93σ)** | +0.9 % (+1.04σ) | −1.5 % (−0.64σ) |
| 27-Jul → 10-Aug | +3.0 % (+0.41σ) | −0.6 % (−0.64σ) | −0.4 % (−0.15σ) |

---

## 7. Limitations

1. **A six-month covariance in a regime shift.** The window mixes the March spike with a calmer summer. Right after the
   shock it understates risk: GARCH's 5.40 % daily LME vol for 9-Mar against the window's 2.32 % would put the 8-Mar
   VaR at about 2.3 times the published number. Later it can overstate risk: the window still carries 8-Mar in August.
   The point-in-time variant does not fix this, because it is another six-month average.
2. **Normality and √time.** The daily LME kurtosis of 6.0 is one day. The variance ratio of 0.62 says √time
   overstates on this window, but ~12 independent blocks cannot pin that down. The Student-t and bootstrap bracket the
   shape (−7 % … +22 % on VaR99, up to +40 % on ES99). They do not bracket a vol regime the window never saw.
3. **Unit beta hides the basis.** In the base, MCX moves one-for-one with LME × USD/INR, so the hedge looks perfect in
   both LME and FX. The mirror rejects that on daily (beta 0.452, t = −8.67) and weekly (0.75, t = −4.9) changes, though not once
   closing times are matched (0.94, t = −0.6; docs/40 §4.3). The §5.4 basis factor shows the gap is large
   (+43 %, ×14.6), and it rests on a third-party series. The engine has no beta ≠ 1 shock (fix log #20).
4. **One freight factor, reconstructed levels.** JEA_NSA is a fixed multiple of USEC_MUN. Freight levels are a
   hindsight reconstruction, and its correlations rest on 26 weeks (SE ≈ 0.2). Of the three snapshots, freight matters
   only on 8-Mar.
5. **Static position, held clock.** No fixings, settlements, rolls, re-hedging, carry or funding over the horizon.
   An instantaneous move re-marks the unfixed part of an averaging price at once, where the real average would absorb
   the move gradually over its pricing days. The to-settlement memo exaggerates all of this.
6. **Factors not simulated.** Grade factors (bucket (c), the largest market bucket, +₹103.3 m at horizon) are a
   reconstruction with no return series. The LME cash–3M spread and rates are carry effects. The domestic anchor
   premium is a **parameter** uncertainty, and it is what makes the headline P&L span −₹105.4 m … +₹334.3 m. It
   belongs to a re-pricing grid, not a market covariance, and this stage does not add the joint premium × grade cases
   the fix log suggested (§10).
7. **Stress mechanics are floors on their own assumptions.** The QCO stress uses first-slab detention, no finance
   cost, and whole-ticket box counts. The buyer default resells at the import replacement mark (not the smelter
   netback), with no storage cost while re-selling, a judgement recovery of 0.25 (PENDING verification) and a 5 %
   discount.
8. **Liquidity is not in any of these numbers.** On 21-Apr the book's cash balance was −₹659.6 m with ₹95.8 m of MCX
   initial margin. On 27-Jul it was −₹1,074.0 m. A hedged book is flat in P&L but not in cash. The short MCX leg
   settles variation margin daily, while the physical offset is only realised at sale, so an LME *rise* drains cash
   (docs/31 §1.4). No working-capital facility is modelled (Phase 5).
9. **Sampling error** of the 99 % VaR is about ±2.5 % (the published interval). Model error is much larger.

---

## 8. What this does and doesn't tell you

**Does.** It tells you how much this simulated book could lose over two weeks on a bad but ordinary market draw, on
three dates that matter: ₹76 m on the first day, when T01 was bought and not yet hedged; ₹23 m at the peak of
physical metal; ₹1 m in late July, when the book was hedged almost flat. It tells you which ticket drives that loss,
and that it agrees with the P&L engine because it *is* the P&L engine. It shows the hedge at work: a 15 % LME fall
costs ₹22 m instead of ₹166 m. It shows that the scary-looking stresses (a 5 % rupee slide, a 40 % freight spike)
barely touch this book, and why: FX nets against the MCX leg, and freight is fixed. Most usefully, it shows the losses
a covariance matrix cannot produce. A buyer walking away costs 28 times the 99 % VaR, and 70 times combined with a
price fall. A port hold costs 2 to 18 times.

**Doesn't.** It is not a forecast, and not evidence of what a 2022 desk would have risked. The trades are simulated,
the MCX series is a proxy that makes the hedge look perfect, and the covariance is a six-month average that is too
calm right after the March shock. It says nothing about the headline P&L's biggest uncertainty, the anchor premium
assumption that moves the result from −₹105 m to +₹334 m. It ignores liquidity: a hedged book can be flat in P&L and
still need hundreds of millions of rupees of working capital and margin. Its tails rest on a normal distribution the
LME data rejects. It holds the position still for 10 days, which no desk does. The basis-risk and bootstrap numbers
show how far off the base could be, not how far off it is. Treat the base VaR as the floor of market risk on a hedged
book, and the stresses as the real risk register.

---

## 9. Outputs and tests

| File | Grain | What |
|---|---|---|
| `outputs/tables/mc_snapshots.csv` | snapshot | rule, evidence, position (Phase 3 BOOK exposures), base value vs Phase 3 cum P&L, same-day-flow diagnostic, to-settlement days, `expost_memo_*` |
| `mc_covariance.csv` | covariance id × factor pair | sample (daily/weekly), n, correlation, daily and 10-day covariance, σ, PSD check |
| `mc_factor_stats.csv` | factor × frequency | window moments, Jarque–Bera, 10-day variance ratio, role (variance source / memo), flag |
| `mc_summary.csv` | snapshot × variant | mean, σ, 95/99 % VaR and ES, VaR99 sampling interval, P(loss), quantiles, simulated factor σ, input flags |
| `mc_pnl_quantiles.csv` | snapshot × variant | 0.1 … 99.9 % P&L quantiles |
| `mc_pnl_distribution.csv` | snapshot × path (base variant) | the three factor shocks and book P&L of all 10,000 paths |
| `mc_es_contributions.csv` | snapshot × ticket | ES99 contribution, standalone VaR/ES |
| `mc_stress_scenarios.csv` | snapshot × stress | P&L, percentile, beyond VaR95/VaR99/ES99/every path, loss ÷ VaR99, σ-size of the move, label (HYPOTHETICAL rows labelled), note; five `SCENARIO` rows plus `MEMO` rows |
| `mc_stress_details.csv` | snapshot × stress × ticket | buyer-default workings (receipts, released/retained MT, replacement mark, loss, implied API recovery) and QCO rows |
| `mc_delta_check.csv` | snapshot | full revaluation vs Phase 3 deltas × the same moves |
| `mc_controls.csv` | snapshot | freight stress = Phase 3's hypothetical (PASS/FAIL; the stage raises on FAIL) |
| `outputs/charts/p4_mc_distribution.png` | | histogram per snapshot with 95/99 % VaR, 99 % ES and the five stresses (off-scale ones arrowed) |
| `outputs/charts/p4_mc_scenarios.png` | | stress P&L bars against 95/99 % VaR, 99 % ES and the basis-factor 99 % VaR |

`tests/test_risk_mc.py` (22 tests):
* **Determinism:** seeded draws; the published factor shocks re-simulated from the published covariance; the
  published paths re-revalued to ₹0.05.
* **Simulation:** covariance reproduced on 200,000 normal draws; t keeps the covariance and fattens the 0.1 % tail;
  the bootstrap is demeaned and scales with the horizon; appending the basis leaves the base paths unchanged.
* **Covariance:** the mixed daily/weekly estimator; PSD repair; no hindsight (rewriting everything after t leaves the
  point-in-time covariance unchanged).
* **Estimators:** VaR/ES order statistics; ES contributions add up.
* **Revaluation:** a zero shock gives zero P&L; the per-path loop equals the vectorised API.
* **Stresses:** LME −15 % hedged is under 25 % (21-Apr) and 5 % (27-Jul) of unhedged, and equal on 8-Mar; the freight
  stress equals Phase 3; the buyer default goes through the API, orders by recovery and worsens with LME −15 %; QCO
  scoped is no worse than all-tickets.
* **Published tables:** internally consistent; snapshot dates reproduce from the rules; the window covariance
  reproduces from `market_daily.csv`.

---

## 10. Open items for other phases

1. **P3 (`desk/mtm/valuation.py`, `shock_state`):** an array-valued `freight_logret` or `freight_<lane>_logret` raises
   `ValueError` at `if freight != M.freight_usd_t`, contradicting the documented array contract. Comparing by
   identity, or always rebuilding the dict when a freight key is present, would let the Monte Carlo vectorise: two
   orders of magnitude faster (measured: 1,000 paths in about 2 ms against 0.6 s path by path).
2. **P3 (`_stress_adjustment`, `qco_hold`):** it charges extra dwell on every box of a ticket, including lots already
   released, uses the first detention slab only, and omits the delay's finance cost. This stage scopes by ticket and
   says so, but a lot-level version belongs in the engine.
3. **P3 (`buyer_default`):** one recovery on all future buyer flows treats undelivered cargo as lost. This stage
   derives an implied recovery from cargo retention. A `resale_discount` and release-aware logic in the API would
   remove the workaround.
4. **P3/P4.1 (fix log #20):** still no MCX beta ≠ 1 shock or exposure variant. §5.4's additive basis factor from the
   mirror is the Monte Carlo's answer, and it says the base understates hedged-book risk by 43 % to 14×.
5. **P5 credit:** on 27-Jul BUY_RJK_01's 2.57×-limit contracted exposure maps to a ₹28.3 m default loss, and ₹68.9 m with
   LME −15 %, because the cargo is retained but unhedged. Scoring advance failure as "cargo unsold, hedge lifted"
   (fix log open item 1) should use the wrong-way number, not the exposure.
6. **P5 liquidity:** none of these numbers include margin calls or funding. The cash balances on the snapshot dates
   (−₹659.6 m, −₹1,074.0 m) are in `mc_snapshots.csv`.
7. **Not done here (fix log open item 2):** joint re-pricing cases of `domestic_anchor_premium_inr_t` × the PIT grade
   mix. They are parameter uncertainty, not market covariance, and need the Phase 3 re-pricing machinery
   (`desk/mtm/sensitivity.py`). The headline's −₹105.4 m … +₹334.3 m band still stands without them.
