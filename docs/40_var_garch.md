# 40 — Daily 95 % VaR: GARCH(1,1) against historical volatility (MASTER_SPEC Table 6 row 4.1 ★)

> **ACADEMIC SIMULATION — not actual trades.** The book whose risk is measured here is simulated (every counterparty,
> vessel and operational outcome is SIM). The LME aluminium prices are **DIRECT** (LME official cash, republished by
> Westmetall). USD/INR is a **PROXY** (ECB cross rates). The MCX hedge series is a **PROXY** (duty-paid import parity,
> unit beta to LME × FX by construction). Freight levels are an **ASSUMPTION** reconstruction. Every rupee of VaR and
> of backtest P&L below comes from `outputs/tables/book_exposures_daily.csv` and `attribution_daily.csv`, so it
> inherits all of that.
>
> **This page is about risk, not the result.** Where it mentions the book's headline P&L (₹195.9 m at 2022-08-31,
> ₹192.1 m at 2022-10-31), read it with its band: across the registered `domestic_anchor_premium_inr_t` grid the same
> nine tickets make anywhere from **−₹105.4 m to +₹334.3 m**, with break-even at −38,702 ₹/t *inside* the grid
> (`pnl_sensitivity_sign_robustness.csv`). The headline is **not sign-robust**.

```sh
cd /Users/sujaljindal/Desktop/ujjwal
DESK_OFFLINE=1 .venv/bin/python -c "import desk.risk.run_var as m; m.main()"   # ~10 s, ~200 MB
DESK_OFFLINE=1 .venv/bin/python -m pytest -q tests/test_risk_var.py            # 23 tests
```

Code: `desk/risk/garch_var.py` (volatility, correlation, VaR), `desk/risk/backtest.py` (Kupiec, Christoffersen),
`desk/risk/run_var.py` (the stage, tables, charts). Parameters: `config/params/risk.yaml`, section "Phase 4.1 VaR".

---

## 0. The finding on one page

The spec says the comparison *is* the finding: show where GARCH flagged rising risk earlier, especially heading into
the crash. On this panel the honest answer has three parts, and the third is not the one the spec expected.

| | GARCH(1,1) | Historical 250 d (base) | Historical 60 d |
|---|---|---|---|
| LME one-day vol forecast, lowest in the month before the window | 1.04 % (4-Feb) | 1.50 % (7-Feb) | 1.44 % (10-Feb) |
| … forecast for 8-Mar, made at the 7-Mar-2022 all-time-high close | **2.89 %** (×2.79) | 1.67 % (×1.12) | 2.02 % (×1.41) |
| the −12.95 % log return on 8-Mar (−12.1 % simple) in those sigmas | **−4.5 σ** | −7.7 σ | −6.4 σ |
| peak forecast inside Mar–Aug | **5.40 % on 9-Mar** | 2.11 % on **31-Aug** | 3.01 % on 10-May |
| forecast for 22-Apr (start of the E1 crash fortnight) | **1.85 %** — the lowest | 1.96 % | 2.84 % |
| first alert at the declared 90th-percentile threshold, into March | 14-Feb | **9-Feb** (3 days earlier) | above since 15-Oct-2021 |
| … into May–July | no fresh alert (above since 14-Feb; dipped, re-alerted 8-Apr) | no fresh alert (above since 9-Feb) | no fresh alert |
| book VaR, mean / max over 120 position days | ₹4.27 m / **₹43.5 m** (9-Mar) | ₹3.98 m / ₹20.9 m (21-Apr) | ₹4.93 m / ₹30.1 m (21-Apr) |
| book exceptions (6.0 expected), Kupiec p | **7**, 0.68 | 5, 0.67 | 2, 0.053 |
| fixed 1,000 MT LME long 2019–2022 (50.6 expected), Kupiec p | **45**, 0.41 | 57, 0.36 | 52, 0.83 |
| … 2021 alone (12.7 expected) | 16, p 0.35 | **22, p 0.014 — rejected** | 16, p 0.35 |

1. **Into the March spike GARCH moved first and hardest — but it did not win the declared test.** Its forecast
   nearly tripled in February while the 250-day window rose 12 %. On the threshold rule registered before any
   result (`var_vol_alert_percentiles`, each method's own 90th percentile of 2019–2021), the 250-day window crossed
   on 9-Feb, three trading days before GARCH — by drifting from 1.50 % to 1.51 % across a 1.507 % line it had
   hovered on since 23-Dec. At the stricter 95th percentile GARCH crossed on 14-Feb and the 250-day window only on
   9-Mar, the day *after* the crash: a 17-trading-day lead. The declared result stands as declared; §5 explains why a
   threshold crossing is a poor measure of "rose first".
2. **After the shock GARCH reset; the rolling windows could not.** GARCH put the book's VaR at ₹43.5 m on 9-Mar
   (₹15.0 m on 250 d) and was back to 1.5 % vol by 7-Apr (half-life 17 days). The 250-day window climbed through the
   whole crash and hit its window high on 31-Aug, after the market had calmed, because 8-Mar stays inside it for 250
   trading days.
3. **Into the April–May crash GARCH did NOT lead.** It had decayed below both rolling windows, which were still
   carrying March. It re-rose only *after* each big down day. On all 7 of its book exceptions GARCH's VaR was the
   lowest of the three methods. Kupiec cannot separate 7 from 5 or 2 at n = 120: it accepts anything from 2 to 11.

---

## 1. "Why GARCH instead of just historical volatility?"

*(written to be quoted in the interview pack)*

Because a 250-day window answers "how volatile was the last year?" and a desk needs "how volatile is tomorrow?". In
February 2022 GARCH's one-day forecast for LME aluminium went from 1.04 % to 3.10 %. Over the same weeks the 250-day
number went from 1.50 % to 1.62 %. At the close of the 7-March all-time high GARCH said 2.89 % a day and the window
said 1.67 %. The next day's −12.95 % log return (−12.1 % simple) was a 4.5-sigma day for GARCH and a 7.7-sigma day for the window. Then GARCH let
go: it was back to 1.5 % by early April, while the 250-day number was still rising on 31 August. But GARCH is not a
crystal ball, and I would not sell it as one. Going into the April–May crash fortnight it was *below* both rolling
windows (1.85 % against 1.96 % and 2.84 %), and it rose only after each big down day. On the book it had 7 VaR breaks
in 120 days against the 250-day window's 5, a gap no test can see on 120 days. Over 1,011 days of a fixed 1,000 MT long
it had 45 breaks against 50.6 expected; the 250-day window had 57. In 2021 alone the 250-day window's 22 breaks fail
Kupiec and GARCH's 16 do not. So: GARCH to size today's risk, a long window as a floor, and neither as a forecast of
the next shock.

---

## 2. Method

### 2.1 Data and returns

| Factor | Series (`data/processed/market_daily.csv`) | Change used | Flag |
|---|---|---|---|
| LME | `lme_cash_usd_t` | log return | DIRECT |
| USD/INR | `usdinr` | log return | PROXY (ECB cross; 3 zero-return fill days in 2018–2022) |
| Freight | `freight_usec_mun_usd_t` | log return of the point-in-time weekly series | ASSUMPTION |
| LME cash–3M spread (memo only) | `lme_cash_3m_spread_usd_t` | absolute change, USD/t | DIRECT |

Every return is dated on its later price. The panel calendar is LME trading days from `HISTORY_START` (2018-01-02)
to `PANEL_END` (2022-12-30). Freight is **one factor**: JEA_NSA is 0.2255 × USEC_MUN in every week (fix log #15), so the
two lanes' log returns are identical. Freight is assessed weekly and carried forward (CONTRACTS §3), so a daily freight
"return" is zero on most days and the whole week's move on the assessment day. The book has no JEA-lane freight
exposure on any day anyway.

### 2.2 GARCH(1,1)

`σ²ₜ = ω + α·r²ₜ₋₁ + β·σ²ₜ₋₁`, fitted with `arch` 8.0.0 by maximum likelihood on percent returns.

* **Zero mean.** The daily mean LME return is two orders of magnitude below its daily volatility. Estimating it adds
  noise, and a zero mean keeps GARCH on the same footing as the historical window, which is a root-mean-square.
* **Normal innovations (base).** Both methods then share the 1.645 multiplier, so the comparison isolates the
  volatility forecast. Student-t is a sensitivity (§2.5).
* **Estimation sample: expanding from `HISTORY_START`.** No forecast until at least `var_garch_min_estimation_obs`
  = 250 returns exist. The first forecast is for 2018-12-28.
* **Refit weekly, filter daily** (`var_garch_refit_frequency` = W-FRI). For each week ending Friday, the parameters
  are estimated on every return dated before that week's first panel day and held for the week. The variance
  recursion then runs day by day. The forecast for day t uses returns dated t−1 or earlier, and so do the parameters.
  One weekly refit costs about 10 ms; 840 fits (2 series × 2 distributions × 210 weeks) run in a few seconds.
* **The recursion is `arch`'s own.** `sigma2[0] = ω + (α + β) × backcast`, where the backcast is the 0.94-decay
  weighted mean of the first 75 squared returns. `tests/test_risk_var.py` checks that our path equals `arch`'s fitted
  conditional volatility and one-step forecast to 1e-10.
* **No look-ahead, tested by perturbation.** The test rewrites every return dated t or later and checks that the
  forecast for t is unchanged to the bit. It does this for a mid-week and a week-start date. The published
  `var_vol_forecasts.csv` also carries `*_garch_sample_end`, which is earlier than the forecast date on every row.

### 2.3 Historical volatility

`σₜ = sqrt(mean(r²) over the W returns dated t−W … t−1)`: a rolling root-mean-square around zero, strictly past.

* **Base W = 250** (`var_hist_window_base_days`). This is the one-year observation period of the Basel market-risk
  rules and the "simple historical vol" most desks mean.
* **W = 60 is published in every table** (`var_hist_window_fast_days`). A fast window is the honest counterpart: any
  GARCH advantage over 60 days is the conservative reading.

Both windows were registered in `risk.yaml` before any Phase 4 number was computed. The freight and spread
volatilities use W = 250 in **all** methods: they are not what this comparison is about.

### 2.4 Correlations

The Pearson correlation of daily factor changes over the 250 panel days ending t−1 (`var_corr_window_days`). **All
methods use the same matrix**, so the GARCH/historical difference is purely the volatility forecast. (A
constant-conditional-correlation GARCH would standardise by the GARCH vol first; not done, to keep the comparison
clean.) Over the 120 backtest days the correlations are small and stable: LME–FX +0.023 (−0.014 … +0.054), LME–freight
−0.008, FX–freight +0.056, LME–spread +0.403. The freight correlations are attenuated by the weekly assessment.

### 2.5 Student-t sensitivity

The same weekly GARCH is fitted with standardised-t innovations. The 95 % multiplier becomes the unit-variance t
quantile `t⁻¹(0.05; ν) × sqrt((ν−2)/ν)`. At 95 % this is **smaller** than 1.645, because fat tails move mass into the
far tail *and* into the centre. For the fit used in the week of 7-Mar-2022, LME ν = 8.49 gives a multiplier of 1.614,
and USD/INR ν = 4.64 gives 1.547. The t version is run on the constant-exposure backtests only (§6.3). Its per-factor ν
has no exact portfolio analogue.

---

## 3. Parameter estimates

`var_garch_params.csv` has every weekly fit: 210 per series and distribution, with ω, α, β, persistence, half-life,
unconditional vol, ν, log-likelihood, convergence and a boundary flag. Variance parameters are in %² units.

| Zero-mean Normal GARCH(1,1) | ω (%²) | α | β | α + β | half-life (days) | unconditional daily vol |
|---|---|---|---|---|---|---|
| **LME**, fit used in the week of 7-Mar-2022 (1,056 returns to 2022-03-04) | 0.0826 | 0.1320 | 0.8283 | **0.9602** | **17.1** | 1.44 % |
| LME, last fit (1,260 returns to 2022-12-23) | 0.0456 | 0.1112 | 0.8744 | 0.9856 | 47.7 | 1.78 % |
| **USD/INR**, week of 7-Mar-2022 | 0.0112 | 0.0893 | 0.8281 | 0.9174 | 8.0 | 0.37 % |
| USD/INR, last fit | 0.0108 | 0.0853 | 0.8313 | 0.9166 | 8.0 | 0.36 % |

Half-life = ln 0.5 / ln(α + β): how many days before a volatility shock has decayed halfway back to the long-run level.

* **2022 taught the model that shocks last longer.** LME persistence rose from 0.958 (fit for 4-Jan-2022) to 0.978
  (fit for 15-Aug-2022), and the half-life from 16 to 31 days. With data through December it reached 0.986. Parameters
  estimated before the crash understate how long it lasted. The weekly refits pick this up only as the data arrive.
* **No LME fit is at the boundary**, and all 840 fits converged. **24 of the 210 USD/INR Normal fits (and 17 of the
  t fits) are boundary fits** (α = 0, β ≈ 1, i.e. a constant variance), the Normal ones all between 2018-12-28 and
  2019-06-03. The 2018 USD/INR sample does not identify a GARCH. It affects only the early part of the 2019 FX unit
  backtest, and is flagged row by row.

---

## 4. From exposures to rupees

### 4.1 The mapping

Every VaR for day t uses the **previous panel close's BOOK exposures**: the position held into t. Deltas from
`book_exposures_daily.csv` (scope = book) are turned into rupees per unit factor move at the previous close's levels:

| VaR factor | Exposure, ₹ per unit move | Mean \|exposure\| per 1 % move, backtest days |
|---|---|---|
| LME log return | `lme_delta_inr_per_usd_t × lme_cash_usd_t` | ₹1.12 m net: physical ₹5.41 m, MCX leg ₹4.88 m |
| USD/INR log return | `fx_delta_usd × usdinr` | ₹2.11 m net: physical + forwards ₹4.46 m, MCX leg ₹4.88 m |
| Freight log return | `Σ lanes freight_delta_inr_per_usd_t_<lane> × freight_<lane>_usd_t` | ₹21 k |
| LME cash–3M spread (memo) | `spread_delta_inr_per_usd_t` per USD/t | — |

`VaRₜ = 1.645 × sqrt(e' D R D e)`: delta-normal and one-day, with `D` = the method's one-day vols and `R` = §2.4.

**FX is built from its legs and combined on one factor.** The review warned that netted `fx_delta_usd` hides
offsetting positions (fix log §3 item 3). So `var_daily.csv` carries the physical + forwards FX exposure and the MCX
leg's FX exposure separately, each with its own standalone VaR. The base VaR then combines them **on the same USD/INR
factor**. That is the consistent choice on this panel: the MCX proxy is `LME × USDINR × duty uplift`, so its FX delta
equals its LME delta on every row (checked: `exp_lme_mcx_inr ≡ exp_fx_mcx_inr`) and it nets one-for-one against the
physical. How much that netting is worth, and what happens if it is wrong, is in §4.2 and §4.3.

The exposure–P&L link is exact. Over the 164 book days, bucket (a) `lme_flat` on day t equals
`lme_delta_inr_per_usd_t(t−1) × ΔLME` to within ₹0.71, and bucket (d) freight to within ₹0.01. Bucket (e) matches its
delta × ΔFX plus the measured LME × FX cross term to within ₹0.18 m on a bucket whose daily standard deviation is
₹0.66 m. VaR and backtest P&L therefore describe the same positions.

### 4.2 What drives the number (GARCH, means over the 120 window position days)

| Component | Standalone VaR |
|---|---|
| LME, physical legs alone | together with the MCX leg alone: **₹36.1 m** gross |
| **LME, net** (physical + MCX short) | **₹3.95 m** |
| USD/INR, physical + forwards alone | ₹2.34 m |
| USD/INR, MCX leg alone | ₹2.61 m |
| **USD/INR, net** | **₹1.17 m** |
| Freight | ₹0.05 m (max ₹0.53 m) — immaterial |
| **Book VaR (LME, FX, freight; correlated)** | **₹4.27 m** |
| memo: plus the LME cash–3M spread factor | ₹5.03 m |

The book's VaR is a **hedge-effectiveness number**: the MCX short takes a ₹36 m gross LME VaR down to about ₹4 m. That
is only as true as the unit-beta proxy that makes the hedge perfect (§4.3). Freight is carried as a factor because
the spec asks for the book's VaR, but it never matters. The LME cash–3M spread is material (+18 %) and is a real
market factor, but its P&L lands in bucket (g) mixed with funding and MCX clock effects (§6.1). It is therefore a
memo VaR with a memo backtest, not the base.

### 4.3 The MCX unit-beta sensitivity (SENSITIVITY, not base)

The P3 review measured the mirror MCX series against duty-paid parity at **beta 0.452, R² 0.294** on daily changes
(`mcx_basis_risk.csv`, docs/30 §13.11) and warned that Phase 4 should not size a VaR as if the hedge were perfect.
`var_<method>_mcx_beta_sensitivity_inr` re-runs the book VaR with two changes. The MCX leg's LME and FX exposures are
scaled by beta. The leg also carries an independent basis residual with volatility
`beta × σ_parity × sqrt((1 − R²)/R²)`, where σ_parity comes from the day's LME and FX vols.

**A daily beta is the wrong number to hedge on.** Parity is struck on the LME official price (London midday); the MCX
evening close lands hours later, so news after the LME fix reaches MCX on day t and parity only on t + 1. That timing
error biases a same-day slope toward zero (weekly mirror–parity correlation is 0.84–0.93 against 0.50–0.57 daily,
docs/10 §11). `run_var.mcx_beta_samplings` therefore re-measures the same mirror over the same window two standard ways
(`var_mcx_beta.csv`, PROXY, retrospective), and the VaR is re-run at the weekly beta as well
(`var_<method>_mcx_beta_weekly_sensitivity_inr`, weekly R² for the residual):

| Sampling | Beta (s.e.) | t against 1 | R² | n | Unhedged share of a parity move | Mean GARCH VaR | Mean 250-day VaR |
|---|---|---|---|---|---|---|---|
| Engine proxy (unit beta, zero basis) — **optimistic end** | 1 | — | — | — | 0 % | ₹4.27 m | ₹3.98 m |
| Lead/lag (Dimson: parity at t−1, t, t+1, slopes summed) | 0.94 (0.10) | −0.6 | 0.47 | 125 days | 6 % | not run | not run |
| Weekly (W-FRI closes) — **central read** | 0.75 (0.05) | −4.9 | 0.90 | 26 weeks | 25 % | **₹8.48 m** (×2.0) | ₹7.83 m |
| Daily (P3's test) — **pessimistic end** | 0.45 (0.06) | −8.7 | 0.29 | 125 days | 55 % | ₹17.25 m (×4.0) | ₹16.08 m |

Read it as a range, not as a better number. Once closing times are matched the mirror cannot reject unit beta
(0.94, t −0.6); on weekly closes it can (0.75, t −4.9), and 25 % of a parity move would be left open. **No desk would
size an MCX hedge on the daily 0.45**: it would leave more than half the metal unhedged because of a clock artefact.
The VaR range is therefore ₹4.27 m (proxy taken at face value) → ₹8.5 m (weekly beta, central) → ₹17.3 m (daily beta,
pessimistic). The lead/lag beta is not run through the VaR: its R² mixes three days of parity and has no one-day
residual to scale. All three betas come from one six-month sample of a mirror whose provenance is unverified. The
Kupiec tests below cannot check any of this: the realised P&L is computed on the same proxy.

---

## 5. The comparison: did GARCH flag rising risk earlier?

### 5.1 The declared test

`var_lead_lag.csv`. A method **alerts** when its forecast rises above its own percentile of its own 2019–2021 forecasts
(`var_vol_alert_percentiles` = 0.75 / **0.90** / 0.95; `var_vol_alert_reference_period`; no 2022 data in any
threshold). Each method is judged against its own distribution because a smooth 250-day series never reaches GARCH's
peaks. The search windows (`var_lead_episodes`) are reporting-only.

If a method is **already above** its threshold when a window opens, the table does not invent a crossing. It reports
the day that spell began (`ABOVE_WHEN_WINDOW_OPENED`), and separately any fresh up-crossing after a dip
(`first_upcrossing_in_window`). Lead = trading days between alerts; positive means GARCH was first.

**LME, 90th percentile (the declared base)**

| Episode | Method | Threshold | Alert | Type | GARCH lead |
|---|---|---|---|---|---|
| into the March spike (search 3-Jan → 31-Mar) | GARCH | 1.60 % | **14-Feb-2022** (σ 1.86 %) | up-crossing | — |
| | 250 d | 1.51 % | **9-Feb-2022** (σ 1.51 %) | up-crossing | **−3 (GARCH later)** |
| | 60 d | 1.43 % | 15-Oct-2021 | already above when the window opened | −83 |
| into the May–July crash (1-Apr → 15-Jul) | GARCH | 1.60 % | 14-Feb | already above; dipped below on 2 days, **fresh re-alert 8-Apr** | — |
| | 250 d | 1.51 % | 9-Feb | already above; 0 days below | −3 |
| | 60 d | 1.43 % | 15-Oct-2021 | already above; 0 days below | −83 |

**Robustness (same table, other percentiles).** At the **95th**, GARCH crossed on 14-Feb and the 250-day window only on
**9-Mar**, the day after the −12.95 % (log) day: a **17-trading-day GARCH lead**. The 60-day window was already above but
dipped, and its fresh crossing came on 25-Feb, **9 days after GARCH**. At the **75th**, all three were already above
when January opened (GARCH dipped and re-crossed on 21-Jan), so the threshold says nothing. Into May–July, at every
percentile, no method gave a fresh alert except GARCH's re-alert on 8-Apr (at the 90th and 95th).

**Verdict, stated plainly.** On the declared 90th-percentile rule, GARCH did **not** lead into March. At the 95th it led
the 250-day window by 17 trading days and the 60-day by 9. Into the May–July crash **no method led**. The rolling
windows had never come down from February (250 d) or October 2021 (60 d). GARCH's 8-Apr re-alert followed a −2.87 %
day on 7-Apr: a reaction, not a forecast.

### 5.2 What the forecasts actually did

A threshold crossing asks "when did this series cross a line?". That is dominated by where a smooth series happens to
sit relative to its line. The 250-day window hovered within 0.01 pp of its 1.507 % threshold from 23-Dec to 9-Feb
and "crossed" by drifting. The forecasts themselves (`var_summary.csv`; each is the forecast **for** the
date, made at the previous close):

| Forecast for | GARCH | 250 d | 60 d | What happened |
|---|---|---|---|---|
| 2022-02-01 | 1.12 % | 1.50 % | 1.69 % | calm |
| 2022-03-01 | **3.01 %** | 1.62 % | 1.85 % | after +5.72 % (24-Feb) and −4.76 % (25-Feb) |
| 2022-03-08 (made at the ATH close) | **2.89 %** | 1.67 % | 2.02 % | −12.95 % log (−12.1 % simple), the largest one-day fall in the 2018–2022 panel |
| 2022-03-09 | **5.40 %** | 1.86 % | 2.62 % | |
| 2022-04-22 (E1 crash fortnight opens) | 1.85 % | 1.96 % | **2.84 %** | fortnight return −16.5 % |
| 2022-05-09 (fortnight closes) | 2.13 % | 2.00 % | 2.95 % | |
| 2022-07-15 (E1 trough, 2,320.5 USD/t) | 1.58 % | **2.08 %** | 2.02 % | |
| 2022-08-31 (window end) | 1.95 % | **2.11 %** (its window peak) | 1.76 % | |

Two readings follow, and both are true:

* **GARCH is a better *level* of today's risk after a regime change.** It rose ×2.79 from its February low to the ATH
  close, against ×1.12 for 250 days and ×1.41 for 60. Under a Normal, the −12.95 % (log) day is a once-in-~1,100-years event
  on GARCH's forecast and a practical impossibility on the 250-day one (−7.7 σ). It is still a tail event on both: **no
  daily vol model saw 8-March coming.**
* **The rolling windows are a better *floor* after a shock, for the wrong reason.** Into the April–May fortnight they
  were higher than GARCH only because they still contained 8-March. That "ghost" also keeps the 250-day VaR elevated
  into a calm August (§6.4), and it would stay until about March 2023, past the panel.

### 5.3 On the book

The book starts after the spike (first position held into 2022-03-09), so its VaR shows the reset, not the build-up
(`p4_var_garch_vs_hist.png`):

| Mean book VaR, ₹ m | Mar | Apr | May | Jun | Jul | Aug |
|---|---|---|---|---|---|---|
| GARCH | **6.51** | 6.19 | 5.36 | 3.57 | 3.24 | 1.47 |
| 250 d | 3.77 | 6.13 | 5.01 | 3.65 | **3.89** | **1.69** |
| 60 d | 4.77 | **8.80** | **7.28** | 3.90 | 3.80 | 1.45 |
| share of days GARCH > 250 d | 100 % | 53 % | 71 % | 35 % | 0 % | 18 % |

* **9-Mar-2022:** GARCH VaR ₹43.5 m, 250 d ₹15.0 m, 60 d ₹21.2 m, on a position that was still unhedged at the 8-Mar
  close (MCX entries are dated 9-Mar; ₹490 m per unit LME log return). The day's market P&L was +₹4.4 m. The big
  GARCH number was the right size for the risk, not a loss that happened.
* **E1 crash fortnight (the 10 return days 25-Apr → 9-May):** mean VaR GARCH ₹5.00 m, 250 d ₹4.87 m, 60 d ₹7.10 m.
  Market P&L −₹24.7 m over those 10 days. Exceptions: GARCH 2, 250 d 2, 60 d 0.

---

## 6. Backtests

### 6.1 What P&L the VaR is tested against

**Base backtest P&L = BOOK-row buckets (a) `lme_flat` + (b) `cross_exchange_basis` + (d) `freight` + (e) `fx`** of
`attribution_daily.csv`, on day t (`pnl_market_inr`). This is a *hypothetical* ("clean") P&L: yesterday's positions
revalued for today's moves in exactly the factors the VaR models (§4.1 shows the match). Bucket (b) is zero on every
base day by construction.

| Excluded | Why |
|---|---|
| `new_deal` | New contracts booked today are not a market move on yesterday's position. |
| (c) `grade_spread` | The grade factors are an ASSUMPTION reconstruction (a hindsight path, interpolated between breakpoints), not an observed market return, and not a VaR factor. Daily std ₹2.20 m over the window. |
| (f) `demurrage_penalty` | Events known that day. |
| (g) `roll_term_structure` | Funding carry (−₹0.24 m a day on average), clock and carry effects, and the reversal of the MCX exit/roll artefact (§7.1), mixed with the LME cash–3M spread move. The spread is market risk but cannot be separated cleanly. So (g) minus funding goes into the **broad memo** backtest, against a VaR that adds the spread (§6.5). |

`attribution_daily.csv` has no `scope` column. Only `trade_id == "BOOK"` rows are read, never added to trade rows.
The backtest sample is every window day with a position held at the previous close: **120 days, 2022-03-09 →
2022-08-31**.

### 6.2 The book: exceptions, Kupiec, Christoffersen

`var_backtest_exceptions.csv` (sample `book_window`). Every exception is an LME day. (a) is the largest loss bucket
on all of them.

| Date | LME return | Market P&L, ₹ m | GARCH VaR | 250 d VaR | 60 d VaR | Breached |
|---|---|---|---|---|---|---|
| 2022-04-07 | −2.87 % | −6.93 | 5.89 | 7.13 | 10.13 | GARCH |
| 2022-04-11 | −4.84 % | **−10.65** (worst day) | 6.47 | 7.14 | 10.24 | all three |
| 2022-04-25 | −4.86 % | −5.46 | 3.35 | 3.82 | 5.53 | GARCH, 250 d |
| 2022-05-03 | −4.29 % | −6.09 | 4.68 | 5.06 | 7.36 | GARCH, 250 d |
| 2022-06-01 | −4.17 % | −2.73 | 2.03 | 2.36 | 3.21 | GARCH, 250 d |
| 2022-06-13 | −3.99 % | −5.11 | 4.35 | 4.75 | 5.08 | all three |
| 2022-07-28 | +2.78 % | −0.17 | 0.14 | 0.19 | 0.18 | GARCH (net short that day) |

On **every** GARCH exception day, GARCH's VaR was the lowest of the three. These are the April–June days on which
GARCH had decayed below windows still carrying March (§5.2).

`kupiec.csv`:

| `book_window`, n = 120, expected 6.0 | exceptions | Kupiec LR | p | Kupiec non-rejection region | verdict | exceptions on consecutive days | Christoffersen p (independence) |
|---|---|---|---|---|---|---|---|
| GARCH | 7 | 0.167 | 0.683 | 2 – 11 | NOT REJECTED | 0 | 0.349 |
| 250 d | 5 | 0.186 | 0.667 | 2 – 11 | NOT REJECTED | 0 | 0.508 |
| 60 d | 2 | 3.744 | 0.053 | 2 – 11 | NOT REJECTED (just) | 0 | 0.794 |

`LR = −2 ln[(1−p)^(n−x) p^x] + 2 ln[(1−x/n)^(n−x) (x/n)^x] ~ χ²(1)`, p = 5 %. **The low-power caveat is the result.** At
n = 120 Kupiec rejects neither 2 nor 11 exceptions, so the book backtest cannot rank the methods. It says only that
none of them is grossly wrong on this book. The 60-day VaR's 2 exceptions (p = 0.053) hint that it was too loose,
and its mean VaR was the highest.

### 6.3 Constant exposure, 2019-01-02 → 2022-12-30 (n = 1,011): the power check

A fixed **long 1,000 MT of LME cash** (`var_unit_lme_mt`; P&L = 1,000 × ΔLME × USD/INR of the day) and a fixed **long
USD 1 m against INR** (`var_unit_fx_usd`). Same forecasts, same 1.645 (or the t multiplier). Kupiec non-rejection
region at n = 1,011: **38 – 64** (expected 50.6). See `p4_var_unit_backtest.png`.

| | GARCH | 250 d | 60 d | GARCH-t (sensitivity) |
|---|---|---|---|---|
| **LME** exceptions, Kupiec p | **45**, 0.41 | 57, 0.36 | 52, 0.83 | 52, 0.83 |
| LME Christoffersen p / consecutive pairs | 0.41 / 1 | 0.65 / 4 | 0.42 / 4 | 0.65 / 2 |
| **USD/INR** exceptions, Kupiec p | 22, **0.000004 — rejected** | 29, **0.0008 — rejected** | 34, **0.011 — rejected** | 31, **0.002 — rejected** |

* **LME: no method is rejected over four years.** GARCH is closest in total (45 against 50.6) and has the fewest
  back-to-back exceptions. The 250-day window runs above expectation from 2021 on (the rising line in the chart).
* **USD/INR: every method has too FEW exceptions — the Normal VaR overstates FX risk at 95 %.** The proxy rupee has
  long calm stretches and rare jumps (GARCH-t ν ≈ 4.6), so a Normal 95 % quantile sits too far out. Student-t pulls
  the multiplier to ~1.55 and gets closer (31) but is still rejected. **For the book this is conservative: the FX leg
  of the VaR is overstated.**

### 6.4 By period (`var_calibration.csv`)

Where each VaR was too tight or too loose. The statistic is the standard deviation of P&L ÷ (VaR / 1.645): above 1 the
VaR was too small, below 1 too big. The yearly splits are also Kupiec-tested (`kupiec.csv`, samples
`unit_*_<year>`, flagged MEMO: 32 tests, so about one false rejection at 5 % is expected by chance).

| LME long 1,000 MT | 2019 | 2020 | 2021 | 2022 |
|---|---|---|---|---|
| GARCH: exceptions (≈12.6 expected) / scaling | 4 / 0.79 — **rejected, too few** | 11 / 0.97 | 16 / 1.11 | 14 / 1.12 |
| 250 d | 3 / 0.71 — **rejected, too few** | 19 / 1.16 | **22 / 1.21 — rejected, too many** | 13 / 1.16 |
| 60 d | 11 / 1.02 | 13 / 1.08 | 16 / 1.08 | 12 / 1.09 |

| Book, scaling by month | Mar | Apr | May | Jun | Jul | Aug | all |
|---|---|---|---|---|---|---|---|
| GARCH | 0.64 | 1.07 | 0.96 | 1.17 | 0.97 | 0.95 | 0.98 |
| 250 d | 0.90 | 0.98 | 0.97 | 1.10 | **0.78** | **0.83** | 0.93 |
| 60 d | 0.74 | 0.68 | 0.67 | 1.06 | 0.80 | 0.98 | 0.84 |

The pattern is the textbook one, with the textbook caveat. A long window is too loose after calm years (2019, which
still carried 2018) and too tight when a calm period ends (2021). It is too loose again after a shock has passed
(book, July–August 2022). GARCH was too loose in March 2022 right after the shock (0.64: its ₹43.5 m day did not
materialise) and is otherwise the most even. 2019 also shows GARCH carrying 2018 too long.

### 6.5 Memo variants (`kupiec.csv`)

| Sample | n | GARCH | 250 d | 60 d | Note |
|---|---|---|---|---|---|
| `book_to_horizon_memo` | 159 | 10 | 9 | 6 | adds Sep–Oct 2022 as the book runs off; the extra exceptions are FX days on VaRs of ₹4–16 k |
| `book_window_broad_memo` | 120 | 8 | 9 | 6 | P&L adds (g) minus funding; VaR adds the cash–3M spread; tests coverage, not the vol forecast |
| `book_window_ex_mcx_exit_roll_days_memo` | 104 | 7 | 5 | 2 | drops the 16 days whose exposure carries an exiting MCX contract (§7.1); no exception moves |

None is rejected by Kupiec or by Christoffersen.

---

## 7. Limitations

### 7.1 The day after an MCX exit or roll: exposure carries the exiting contract

On the 16 backtest days whose previous close was an MCX `exit` or `roll_out` date (`mcx_variation_margin.csv`), the
BOOK exposure still contains the contract that was closed that day. On 2022-04-20 (five rolls) `lme_delta_mcx_mt` is
−6,558 MT against −3,273 the day before and −3,854 the day after, with `mcx_lots_open` unchanged at −604. Bucket (a)
the next day uses the same delta, and step 7 of the attribution chain (the clock) reverses it into (g). Examples:
market P&L (a)+(b)+(d)+(e) = +₹10.1 m and (g) minus funding = −₹8.1 m on 22-Jun; +₹6.7 m and −₹6.7 m on 30-Aug. It
follows from P3 valuing a flow that fixes today at today's state until the clock moves. VaR and backtest P&L here are
therefore **consistent with each other
but not with economics** on those days. The VaR spikes on 21-Apr (GARCH ₹21.4 m), 23-May, 22-Jun, 21-Jul and 27-Jul
are this artefact. They are flagged `position_date_mcx_exit_or_roll` in `var_daily.csv` and tick-marked on the chart.
Excluding those days, mean VaR is GARCH ₹3.92 m, 250 d ₹3.55 m, 60 d ₹4.42 m, and no exception changes. **Open item for
the P3 owner** (§11).

### 7.2 The rest

* **The MCX hedge is a proxy with unit beta by construction.** Basis risk is under-represented. Base bucket (b) is
  identically zero, and the realised P&L the VaR is tested against has the same property, so the backtest cannot
  catch it. §4.3 sizes it at ×4 on the VaR.
* **Parametric Normal tails.** 95 % delta-normal VaR says nothing about the size of the loss beyond it: 8-March was
  −4.5 σ even on GARCH. USD/INR is overstated at 95 % (§6.3); at 99 % a Normal would likely understate both factors.
* **Positions change daily.** VaR is on the previous close's deltas. New deals, hedge changes and fixings during day t
  are outside it (they land in `new_deal` or (g), which the backtest excludes). The deltas are first-order: the
  LME × FX cross-gamma is measured in P3 (`lme_fx_cross_inr`) but not used in the VaR.
* **Freight is a reconstruction and effectively one weekly factor.** Its daily vol and correlations are artefacts of
  weekly assessment. It is immaterial here (mean ₹0.05 m of standalone VaR).
* **USD/INR is an ECB cross, not the RBI/FBIL reference rate.** The customs exchange-rate exposure
  (`customs_fx_delta_usd`, at most USD 0.29 m) is not a VaR factor, and moves on notification days in bucket (e).
* **Unmodelled market factors:** the LME cash–3M spread (memo VaR +18 %), grade factors (reconstructed), MCX basis and
  curve (zero or contango on the proxy), and rates.
* **One-day horizon at 95 %.** It is not a liquidation horizon: a 3,000 MT physical position does not exit in a day,
  and MCX had daily price limits (docs/31 §6).
* **Weekly refits** make parameters up to four trading days stale. The daily filter carries yesterday's return, which
  is what moves the forecast.
* **One path, one book.** 120 days of a simulated book: the book backtest has no power (§6.2), and the constant-exposure
  backtests are about the vol models, not about this book.

---

## 8. What this does and doesn't tell you

**Does.** It gives a day-by-day 95 % one-day VaR for the simulated book, on the positions actually held each night, in
rupees, from two volatility models run strictly point-in-time. It shows, with dates, how the two models reacted to
the largest volatility event in the panel. GARCH nearly tripled its forecast in the three weeks before the 7-March
all-time high, and let go within a month. The 250-day window barely moved before the high and was still rising at the
end of August. It also shows the opposite case: going into the April–May crash GARCH was the *least* cautious model,
and it took more VaR breaks there. It tests every VaR with Kupiec and Christoffersen on the book and on four years of
a fixed position, and says which results those tests can and cannot support. It prices the hedge-effectiveness
assumption the book's VaR depends on: ×2.0 at the mirror's weekly beta of 0.75, ×4.0 at the daily 0.45, which
asynchronous closes bias down (§4.3).

**Doesn't.**

* **It does not predict crashes.** No volatility model here, GARCH included, anticipated the −12.95 % log fall on 8 March or
  the April–May slide. GARCH measures today's risk faster; it does not see the next shock.
* **It does not say GARCH "beat" historical VaR on this book.** 7 vs 5 vs 2 exceptions in 120 days is statistically
  indistinguishable (Kupiec accepts 2–11). The four-year LME test favours GARCH mildly (45 against 57 for 250 days, both
  accepted). The declared first-alert rule went to the 250-day window by 3 days into March.
* **It is not the risk of a real desk.** The book, its exposures and its P&L are simulated. USD/INR and MCX are
  proxies, and freight and grade factors are reconstructions. The "hedged" VaR is only as low as the proxy's unit beta
  makes it.
* **It says nothing about the tail beyond 95 %,** about liquidity (a one-day VaR on positions that take weeks to exit),
  about credit or advance exposure (Phase 5), or about the book's headline P&L. That P&L is **not sign-robust**: −₹105.4 m
  to +₹334.3 m across the registered anchor-premium grid.
* **The search windows and checkpoints in §5 were drawn after the fact** to describe what happened. The thresholds use
  only pre-2022 data, and no VaR or backtest number depends on them.

---

## 9. Outputs and tests

| File | Grain | What it holds |
|---|---|---|
| `outputs/tables/var_daily.csv` | panel day, 2022-03-01 → 2022-10-31 | position date, exposures by leg, every vol and correlation used, VaR by method (base, components, spread memo, MCX-beta sensitivity), market P&L buckets and memo buckets, exception flags, `position_date_mcx_exit_or_roll` |
| `var_vol_forecasts.csv` | panel day, 2018-12-28 → 2022-12-30 | LME and USD/INR returns; GARCH, GARCH-t, 250 d and 60 d vols; ν; GARCH sample end and boundary flag; freight and spread vols; rolling correlations |
| `var_garch_params.csv` | weekly fit × series × distribution | ω, α, β, persistence, half-life, unconditional vol, ν, log-likelihood, converged, boundary |
| `var_unit_backtest_daily.csv` | panel day, 2019–2022 | constant-exposure P&L, VaR by method, exception flags |
| `var_backtest_exceptions.csv` | sample × method × exception day | VaR, P&L, shortfall, loss/VaR, vols, factor returns, P&L by bucket, largest loss bucket |
| `kupiec.csv` | sample × method | n, exceptions, expected, Kupiec LR / p / non-rejection region / verdict, Christoffersen independence and conditional coverage, role (BASE / MEMO / SENSITIVITY) |
| `var_calibration.csv` | sample × period × method | exceptions, expected, std of P&L ÷ (VaR/1.645), mean VaR |
| `var_lead_lag.csv` | series × episode × percentile × method | threshold, alert date and type, first fresh up-crossing, days below, peak, GARCH lead |
| `var_mcx_beta.csv` | sampling (engine unit beta, daily, weekly, lead/lag) | mirror MCX beta, s.e., t against one, R², n, unhedged share, mean GARCH and 250-day VaR at that beta (SENSITIVITY, PROXY) |
| `var_summary.csv` | metric | every number quoted on this page that is not a direct row of the tables above |
| `outputs/charts/p4_var_garch_vs_hist.png` | | book VaR paths for three methods, realised market P&L, exceptions, exit/roll days; LME price with the ATH, the low and the E1 crash fortnight |
| `p4_var_vol_forecasts.png` | | LME and USD/INR vol forecasts Sep-2021 → Aug-2022, thresholds and dated alerts |
| `p4_var_unit_backtest.png` | | cumulative exceptions minus expected, 2019–2022, both constant exposures |

`tests/test_risk_var.py` (23 tests, ~12 s) covers:

* **No look-ahead:** GARCH forecasts, parameters included, are unchanged under rewriting of all returns dated t or
  later; rolling vol and correlation ignore day t; published sample ends are earlier than forecast dates; published
  VaR uses the previous panel close's BOOK exposures.
* **The recursion is `arch`'s own**, to 1e-10.
* **Kupiec:** closed-form cases (x = np → 0; x = 0 → −2n ln 0.95 = 25.6466; a hand-expanded x = 20), and Jorion's
  published non-rejection regions (255/510/1,000 days at 95 %, 510/1,000 at 99 %). The one discrepancy, 255 days at 99 %
  (the table prints N < 7, and x = 0 has LR 5.13 > 3.84), is not asserted.
* **Christoffersen** separates spread-out from clustered exceptions with equal counts.
* **VaR scaling:** linear in exposure and vol; root-sum-square for independent factors; zero for a perfect hedge;
  z = 1.6449; the t multiplier below Normal at 95 %.
* **Honest alert typing** on a synthetic series.
* **Published tables:** the VaR rebuilds from its own columns; backtest P&L = (a)+(b)+(d)+(e); Kupiec rows match the
  daily flags.
* **MCX beta samplings:** the daily beta equals P3's; the weekly and lead/lag betas recompute from the raw mirror
  file and the panel; daily < weekly < lead/lag and the VaR falls as beta rises.
* **Determinism:** a full stage re-run reproduces `var_daily.csv` and `kupiec.csv`. Two consecutive `main()` runs gave
  byte-identical CSVs.

---

## 10. Provenance

| Input | Flag | Where |
|---|---|---|
| LME aluminium cash, cash–3M spread | DIRECT | `market_daily.csv` (Westmetall republication of LME official prices) |
| USD/INR | PROXY | `market_daily.csv` (ECB cross) |
| Freight lane levels | ASSUMPTION | `market_daily.csv` (hindsight reconstruction; JEA = 0.2255 × USEC) |
| Book exposures (deltas) | SIM book on PROXY/ASSUMPTION inputs | `book_exposures_daily.csv`, scope = book |
| Realised P&L buckets | SIM | `attribution_daily.csv` BOOK rows; FUNDING leg of `attribution_leg_daily.csv` (memo) |
| MCX exit/roll dates | SIM | `mcx_variation_margin.csv` |
| Event dates (ATH, E1 trough, crash fortnight) | DIRECT prices, reporting-only rules | `adverse_event_windows.csv` |
| MCX mirror beta: daily 0.452 (R² 0.294), weekly 0.752 (R² 0.903), lead/lag 0.939 | PROXY | `mcx_basis_risk.csv` (daily, P3); `var_mcx_beta.csv` (all three, re-measured through `MarketHistory(mcx_source="mirror")`); sensitivity only |
| Windows, refit frequency, thresholds, unit exposures | ASSUMPTION | `config/params/risk.yaml`, Phase 4.1 section |
| 95 % confidence, GARCH(1,1), zero mean, Normal base, t sensitivity | model-structure constants | `desk/risk/garch_var.py` |

---

## 11. Open items for other phases

1. **P3 — exposures on MCX exit/roll dates (§7.1).** `book_exposures_daily.csv` dated on an exit or roll day includes
   the contract that closed that day, and bucket (a) the next day uses it (reversed in (g)). A forward-looking risk
   delta should exclude flows fixed at today's close. 16 of 120 backtest days are affected. No VaR exception depends
   on it.
2. **P3/P4.2 — MCX beta shock.** There is still no MCX-beta or basis shock key in `valuation.SHOCK_KEYS` (fix log #20).
   §4.3 does the beta sensitivity at the VaR level only. The Monte Carlo should carry the basis as a factor.
3. **P4.2 — tails.** The Normal 95 % VaR overstates USD/INR (§6.3), while 8-March was −4.5 σ on GARCH. Tail percentiles
   for the Monte Carlo should come from fat-tailed or historical-shock draws, not a Normal scaled by these vols.
4. **P6 interview pack.** Quote §1 with its caveats, not only its first half.
