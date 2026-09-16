# Phase 1 — Import parity model (Component 1, MASTER_SPEC Table 3 rows 1.1–1.7)

**ACADEMIC SIMULATION — not actual trades.** Every counterparty, trade and SPA here is simulated; market series are labelled DIRECT / PROXY / ASSUMPTION exactly as in the Phase 0 register.

_Rendered by `desk.parity.run` from the same data frames it writes to `outputs/tables/` — do not hand-edit; re-run `DESK_OFFLINE=1 .venv/bin/python -c "import desk.parity.run as m; m.main()"`._

## 1. Purpose

Each Friday the desk asks one question per grade × lane: *if I buy containerised aluminium scrap CFR India today, clear it, and sell it as melt feed to a (SIM) secondary smelter, does the rupee margin per tonne of scrap clear the hurdle?* The model answers with CONTRACTS §5 line by line (LME 3M × grade factor → CIF → duties → port and finance → landed cost, against a domestic secondary-ingot anchor × metal recovery, plus the Zorba heavies credit, minus conversion). Because the base flag is only as good as its weakest input, the answer that Component 2 may trade on is the ex-ante §5a rule: open under the base case, under the point-in-time grade mix, and with conversion one grid step above base.

Grades: Zorba 95/5, Taint/Tabor (ISRI-clean), Tense (ISRI-clean). Lanes: **JEA_NSA** Jebel Ali → Nhava Sheva (20ft, anchor MCX M1) and **USEC_MUN** US East Coast → Mundra (40ft, anchor MCX M2).

## 2. Outputs

| File | Grain | Content |
|---|---|---|
| `outputs/tables/parity_weekly.csv` | week_end × grade × lane (43 × 3 × 2) | key inputs, every §5 line item, `window_open`, §5a flags `open_base`, `open_pit_mix`, `open_conv18k`, `trade_eligible`, the no-hindsight disclosure gate `open_pit_conv18k` / `trade_eligible_pit`, their net arbs, USD memo |
| `parity_sensitivity_cases.csv` / `_summary.csv` | case × week × grade × lane / case × grade × lane | the §5 required band (+ informational cases); open-week counts and flips vs base, in-window |
| `parity_reference_cases.csv` | 3 rows | declared Table 1.5 reference cases and their selection rules |
| `parity_sensitivity_lme_fx.csv` (+`_wide`) | ref × LME shock × USD/INR | Table 1.5(a) P&L impact on 1,000 MT |
| `parity_sensitivity_freight_duty.csv` (+`_wide`) | ref × terms × freight shock × BCD | Table 1.5(b) P&L impact on 1,000 MT (FOB and CFR terms) |
| `parity_quality_scenarios.csv` | grade × moisture × contamination × yield | Table 1.6 settlement, recovery, landed per t recovered metal, net-arb impact |
| `parity_anchor_correlation.csv` | sample × pair × metric | Table 1.3 anchor study |
| `term_structure_weekly.csv`, `term_structure_roll_monthly.csv` | week / MCX contract month | Table 1.7 Cash–3M, M+1 pricing basis, roll yield |
| `outputs/charts/p1_*.png` | 7 charts | net arb, eligibility heatmap, waterfall, grids, band, term structure |

Helpers for later phases (`desk.parity.model`): `load_parity()`, `eligible_on(trade_date, grade, lane)` (latest `week_end ≤ trade_date`; returns `(trade_eligible, week_end, row)`), `parity_row(week_end, grade, lane, overrides)`, `market_shock_overrides(...)`; `desk.parity.quality.settle_weight_and_penalty(...)`.

**The Excel half of MASTER_SPEC row 1.1** ("Python + Excel") is `outputs/excel/Metals_Desk_Master.xlsx`, built by `desk.excel.build` (run_all stage P3) from these same tables with formula-driven parity sheets (CONTRACTS §2); `outputs/excel/reconciliation.json` records its tie-out to the CSVs. This page documents the Python half; the workbook recomputes the weekly parity from the same register and panel.

## 3. Formula table (CONTRACTS §5 — canonical keys, per MT of scrap)

Flags: *new inputs* = flags of the panel columns (`data/processed/series_provenance.csv`) and register keys (`config/params/*.yaml`) that the line introduces; *value* = the weakest of those and of every upstream line item. For grade/lane-specific keys the Zorba / JEA_NSA key is checked; the other grades and lanes carry the same flags.

| Line item | Formula | Unit | New inputs | Value flag |
|---|---|---|---|---|
| `cfr_usd_t` | lme_3m_usd_t × grade_factor_<g>(w) | USD/MT | DIRECT / ASSUMPTION | **ASSUMPTION** |
| `payload_scale` | container_payload_mt_<box> ÷ container_payload_mt_<box>_<g> | frac | ASSUMPTION | **ASSUMPTION** |
| `freight_usd_t` | freight_<lane>_usd_t × payload_scale | USD/MT | ASSUMPTION | **ASSUMPTION** |
| `fob_usd_t` | cfr − freight (memo: origin netback) | USD/MT | — | **ASSUMPTION** |
| `insurance_usd_t` | insurance_rate × insured_value_uplift × cfr | USD/MT | DIRECT / ASSUMPTION | **ASSUMPTION** |
| `cif_usd_t` | cfr + insurance | USD/MT | — | **ASSUMPTION** |
| `av_customs_inr_t` | cif × customs_usdinr_import(w) — duty base only | INR/MT | DIRECT | **ASSUMPTION** |
| `goods_inr_t` | cif × usdinr_fwd_1m (parity_goods_fx_basis) | INR/MT | PROXY / ASSUMPTION | **ASSUMPTION** |
| `bcd_inr_t` | av × bcd_scrap_hs7602 | INR/MT | DIRECT | **ASSUMPTION** |
| `sws_inr_t` | bcd × sws_rate_on_bcd | INR/MT | DIRECT | **ASSUMPTION** |
| `igst_inr_t` | (av + bcd + sws) × igst_rate_hs7602 | INR/MT | DIRECT | **ASSUMPTION** |
| `port_inr_t` | port_cf_charges_inr_t_<nsa/mun> × payload_scale + [JEA_NSA] psic_cost_usd_per_box × usdinr ÷ container_payload_mt_20ft_<g> | INR/MT | DIRECT / PROXY / ASSUMPTION | **ASSUMPTION** |
| `finance_inr_t` | (goods + bcd + sws) × finance_days_<lane> ÷ 365 × wc_rate_inr_pa(w) | INR/MT | ASSUMPTION | **ASSUMPTION** |
| `igst_finance_inr_t` | igst × igst_credit_lag_days ÷ 365 × wc_rate_inr_pa(w) | INR/MT | ASSUMPTION | **ASSUMPTION** |
| `landed_inr_t` | goods + bcd + sws + port + finance + igst_finance [+ igst only if igst_itc_available is false] | INR/MT | ASSUMPTION | **ASSUMPTION** |
| `recovery_frac` | (1 − moisture_frac_<g>) × (1 − contamination_frac_<g>) × metal_yield_frac_<g> | frac | ASSUMPTION | **ASSUMPTION** |
| `anchor_inr_t` | mcx_al_<m1 JEA_NSA, m2 USEC_MUN>_inr_kg × 1000 + domestic_anchor_premium_inr_t | INR/MT | PROXY / ASSUMPTION | **ASSUMPTION** |
| `byproduct_inr_t` | (1 − moisture) × heavies_frac_<g> × heavies_net_value_frac_of_lme_al × lme_3m × usdinr | INR/MT | DIRECT / PROXY / ASSUMPTION | **ASSUMPTION** |
| `conversion_inr_t` | conversion_cost_inr_t (per t ingot) × recovery | INR/MT | ASSUMPTION | **ASSUMPTION** |
| `net_arb_inr_t` | anchor × recovery + byproduct − landed − conversion | INR/MT | — | **ASSUMPTION** |
| `window_open` | net_arb_inr_t > margin_threshold_inr_t | bool | ASSUMPTION | **ASSUMPTION** |

## 4. Choices Phase 1 had to make (and why)

1. **Goods paid at the 1-month forward, not spot** (`parity_goods_fx_basis = usdinr_fwd_1m`, ASSUMPTION). A sight LC is paid ~7 days after the B/L, which falls inside the 15-day shipment window after the decision, so the dollar payment is ~1 month out on both lanes; the domestic anchor is itself a forward (the MCX contract matched to the sale date). Valuing both legs at prices lockable on the decision day avoids booking the forward premium as margin. In the window this adds ₹342–₹606 per MT to landed cost (mean ₹470); `finance_inr_t` then covers LC payment → buyer receipt only. Spot is case `goods_fx_spot`.
2. **Customs FX coverage.** `customs_usdinr_import` is used from its first notification to `customs_fx_notification_validity_days` (14) after the last one; outside that the register's `customs_fx_markup_frac` fallback applies (weeks ending 07-Jan–11-Feb (6), 07-Oct–28-Oct (4); none in the window). Column `customs_fx_src` labels each row.
3. **Weeks.** W-FRI week_ends 07-Jan-2022 → 28-Oct-2022, each valued on its last panel day; every dated parameter path is read on that value date. `in_window` = the week (Sat–Fri) overlaps 2022-03-01…2022-08-31: 27 weeks, 04-Mar-2022 → 02-Sep-2022 (the last one is valued on 2 Sep because its Monday–Wednesday fall in August).
4. **§5a flags** are three separate one-change cases combined with AND: `open_base`; `open_pit_mix` (grade factor = `grade_factor_mix_pit` + the registered differential); `open_conv18k` (conversion = the first value of `conversion_cost_sensitivity_inr_t_ingot` above base = ₹18,000/t ingot; the code raises if the register ever makes that anything other than the 18,000 the contract named). Case 3 can only close windows, so `trade_eligible = open_pit_mix ∧ open_conv18k` in practice. **Read §6.1 before quoting the rule as point-in-time discipline: on this panel the point-in-time screen never binds and the binding screen reads a hindsight-reconstructed grade mix.**
5. **PSIC** applies where the register says the origin/port pair needs one (`psic_required_uae_origin` for JEA_NSA = true; `psic_required_safe_origin_designated_port` for USEC_MUN = false).
6. **Overrides.** Any sensitivity swaps an input column or a canonical register key (a scalar, a weekly series or a function of the *un-overridden* inputs) and re-runs the same `compute`; the base frame is never mutated (tested).

## 5. Worked example — reference case `first_eligible`: 04-Mar-2022, zorba, JEA_NSA

Selection rule (declared in `desk.parity.sensitivity.reference_cases`): first trade-eligible in-window case (earliest week, then grade, then lane order). Every result below is the value in `outputs/tables/parity_weekly.csv` for that row (INR to 2 dp, USD to 4 dp).

**Inputs**

| Input | Value | Source | Flag |
|---|---|---|---|
| value date | 04-Mar-2022 | last panel day of the week | — |
| `lme_3m_usd_t` | 3,820.00 | Westmetall LME official 3M | DIRECT |
| `usdinr` (spot) | 76.3431 | ECB EUR/INR ÷ EUR/USD | PROXY |
| `usdinr_fwd_1m` | 76.5667 | covered interest parity | PROXY |
| `customs_usdinr_import` | 76.65 | CBIC_NOTIFIED | DIRECT |
| `grade_factor_zorba` | 0.709107 | lag-2 DGCIS mix + 2024–25 differential (linear path) | ASSUMPTION |
| `freight_jea_nsa_usd_t` | 24.00 | WCI shape × assumed level | ASSUMPTION |
| `container_payload_mt_20ft` / `_zorba` | 25 / 26 | logistics.yaml | ASSUMPTION |
| `insurance_rate` × `insured_value_uplift` | 0.001 × 1.1 | logistics.yaml | ASSUMPTION |
| `bcd_scrap_hs7602`, `sws_rate_on_bcd`, `igst_rate_hs7602` | 0.025, 0.1, 0.18 | CBIC / GST | DIRECT |
| `port_cf_charges_inr_t_nsa`, `psic_cost_usd_per_box` | 1,600, 40 (PSIC applies: True) | logistics / regulatory | ASSUMPTION |
| `finance_days_jea_nsa`, `wc_rate_inr_pa`, `igst_credit_lag_days` | 40, 0.095, 45 | logistics / rates | ASSUMPTION |
| moisture / contamination / yield / heavies (zorba) | 0.01 / 0.06 / 0.93 / 0.05 | scrap_grades.yaml | ASSUMPTION |
| `heavies_net_value_frac_of_lme_al` | 0.8 | scrap_grades.yaml | ASSUMPTION |
| `mcx_al_m1_inr_kg` | 319.1419 | MCX import-parity proxy | PROXY |
| `domestic_anchor_premium_inr_t`, `conversion_cost_inr_t`, `margin_threshold_inr_t` | −9,000, 12,000, 5,000 | commercial.yaml | ASSUMPTION |

**Line items**

| Line item | Arithmetic | Result |
|---|---|---|
| `cfr_usd_t` | 3,820.00 × 0.709107 | **2,708.7893** |
| `payload_scale` | 25 ÷ 26 | **0.961538** |
| `freight_usd_t` | 24.00 × 0.961538 | **23.0769** |
| `fob_usd_t` | 2,708.7893 − 23.0769 | **2,685.7124** |
| `insurance_usd_t` | 0.001 × 1.1 × 2,708.7893 | **2.9797** |
| `cif_usd_t` | 2,708.7893 + 2.9797 | **2,711.7690** |
| `av_customs_inr_t` | 2,711.7690 × 76.65 | **207,857.09** |
| `goods_inr_t` | 2,711.7690 × 76.5667 | **207,631.20** |
| `bcd_inr_t` | 207,857.09 × 0.025 | **5,196.43** |
| `sws_inr_t` | 5,196.43 × 0.1 | **519.64** |
| `igst_inr_t` | (207,857.09 + 5,196.43 + 519.64) × 0.18 | **38,443.17** |
| `port_inr_t` | 1,600 × 0.961538 + 40 × 76.3431 ÷ 26 | **1,655.91** |
| `finance_inr_t` | (207,631.20 + 5,196.43 + 519.64) × 40 ÷ 365 × 0.095 | **2,221.15** |
| `igst_finance_inr_t` | 38,443.17 × 45 ÷ 365 × 0.095 | **450.26** |
| `landed_inr_t` | 207,631.20 + 5,196.43 + 519.64 + 1,655.91 + 2,221.15 + 450.26 (IGST itself excluded: ITC available) | **217,674.59** |
| `recovery_frac` | (1 − 0.01) × (1 − 0.06) × 0.93 | **0.865458** |
| `anchor_inr_t` | 319.1419 × 1,000 + (−9,000) | **310,141.90** |
| `byproduct_inr_t` | (1 − 0.01) × 0.05 × 0.8 × 3,820.00 × 76.3431 | **11,548.57** |
| `conversion_inr_t` | 12,000 × 0.865458 | **10,385.50** |
| `net_arb_inr_t` | 310,141.90 × 0.865458 + 11,548.57 − 217,674.59 − 10,385.50 | **51,903.27** |
| `window_open` | 51,903.27 > 5,000 | **True** |
| `net_arb_usd_t` (memo) | 51,903.27 ÷ 76.3431 | **679.8686** |

§5a for the same row: point-in-time mix net arb ₹16,946 → `open_pit_mix` = True; conversion ₹18,000/t ingot net arb ₹46,711 → `open_conv18k` = True; `trade_eligible` = **True**. Chart: `outputs/charts/p1_landed_cost_waterfall.png`.

## 6. Results (base, §5a flags, eligible weeks)

Counts are over the 27 in-window weeks. In total **82 of 162** in-window week × grade × lane cases are trade-eligible (base alone: 111).

| Grade | Lane | Base open | PIT-mix open | Conv 18k open | Trade-eligible | Max base net arb | Min base net arb |
|---|---|---|---|---|---|---|---|
| zorba | JEA_NSA | 17 | 26 | 10 | **10** | ₹51,903 (04-Mar) | −₹5,126 (15-Jul) |
| zorba | USEC_MUN | 14 | 24 | 10 | **10** | ₹49,904 (04-Mar) | −₹6,768 (15-Jul) |
| taint_tabor | JEA_NSA | 14 | 24 | 10 | **10** | ₹49,289 (04-Mar) | −₹7,317 (15-Jul) |
| taint_tabor | USEC_MUN | 13 | 24 | 9 | **9** | ₹47,817 (04-Mar) | −₹8,430 (15-Jul) |
| tense | JEA_NSA | 27 | 27 | 22 | **22** | ₹70,766 (04-Mar) | ₹6,368 (15-Jul) |
| tense | USEC_MUN | 26 | 27 | 21 | **21** | ₹69,011 (04-Mar) | ₹4,929 (15-Jul) |

**Trade-eligible in-window weeks (week ending, run length)**

| Grade | Lane | Eligible weeks |
|---|---|---|
| zorba | JEA_NSA | 04-Mar–06-May (10) |
| zorba | USEC_MUN | 04-Mar–06-May (10) |
| taint_tabor | JEA_NSA | 04-Mar–06-May (10) |
| taint_tabor | USEC_MUN | 04-Mar–29-Apr (9) |
| tense | JEA_NSA | 04-Mar–10-Jun (15), 22-Jul–02-Sep (7) |
| tense | USEC_MUN | 04-Mar–10-Jun (15), 22-Jul–26-Aug (6) |

**Base-open weeks that the §5a rule rejects, and which case rejects them**

| Grade | Lane | Base open, not eligible | Only PIT mix closed | Only conv 18k closed | Both closed |
|---|---|---|---|---|---|
| zorba | JEA_NSA | 7 | none | 13-May–27-May (3), 05-Aug–26-Aug (4) | none |
| zorba | USEC_MUN | 4 | none | 13-May–20-May (2), 12-Aug | 19-Aug |
| taint_tabor | JEA_NSA | 4 | none | 13-May–20-May (2), 12-Aug | 19-Aug |
| taint_tabor | USEC_MUN | 4 | none | 06-May–20-May (3), 12-Aug | none |
| tense | JEA_NSA | 5 | none | 17-Jun–15-Jul (5) | none |
| tense | USEC_MUN | 5 | none | 17-Jun–08-Jul (4), 02-Sep | none |

Out-of-window context weeks that are eligible: 07-Jan–25-Feb (8) (every grade-lane); those rows exist only for look-ups and charts, not for trading. Every grade-lane has at least one eligible window week.

How to read it. The base net arb is huge in the March spike and collapses into June–July: the constant anchor premium rides the MCX proxy down with LME, while the lag-2 grade factor *rises* through the crash (scrap prices lag LME), squeezing Zorba and Taint/Tabor below the hurdle. The point-in-time mix is three months staler, so it is low when the lag-2 mix is high and vice-versa — it opens June–July and shaves March. The ₹18k conversion case is what shuts Zorba and Taint/Tabor after early May: their August base margin (at most ₹9,266/t) does not survive the extra ₹6k per t of ingot (≈ ₹5,193–₹5,500 per t of scrap). Tense (lowest grade factor, highest recovery) is eligible 04-Mar–10-Jun (15), 22-Jul–02-Sep (7) on JEA_NSA and 04-Mar–10-Jun (15), 22-Jul–26-Aug (6) on USEC_MUN. Charts: `p1_net_arb_weekly.png`, `p1_window_heatmap.png`.

### 6.1 What the §5a rule actually screens on (read this before quoting it)

CONTRACTS §5a asks for three independent screens. On this panel they are not independent, and the one that a 2022 desk could genuinely have computed — `open_pit_mix`, the point-in-time grade mix — **never binds**: of 162 in-window grade × lane × week cases it is open in 152, and there is no case it closes that `open_conv18k` does not already close (0 such cases). `trade_eligible` is therefore **identical to `open_conv18k`** on every row of `parity_weekly.csv` (82 of 162 open; base alone 111, conv-18k alone 82).

`open_base` and `open_conv18k` both read the **lag-2 DGCIS grade mix**, which is a hindsight reconstruction (§12): the unit values for month *m* were published around month *m+2*. So the binding screen is a screen a desk could not have run in the week it was trading. The rule is frozen and is not being re-interpreted — but a reader must not take the eligibility calendar as point-in-time discipline.

`trade_eligible_pit` is published beside it as the honest counterpart: the same discipline with the point-in-time mix on **both** legs (`open_pit_mix ∧ open_pit_conv18k`). It opens **140 of 162** cases against 82 — **62 cases the published rule stood aside from**, and 4 the published rule allowed that it would have blocked:

| Grade | Lane | Extra cases | Weeks the no-hindsight gate would have opened |
|---|---|---|---|
| zorba | JEA_NSA | 13 | 13-May–05-Aug (13) |
| zorba | USEC_MUN | 13 | 13-May–05-Aug (13) |
| taint_tabor | JEA_NSA | 12 | 13-May–29-Jul (12) |
| taint_tabor | USEC_MUN | 13 | 06-May–29-Jul (13) |
| tense | JEA_NSA | 5 | 17-Jun–15-Jul (5) |
| tense | USEC_MUN | 6 | 17-Jun–15-Jul (5), 02-Sep |

The consequence is concrete and unflattering. The published book's headline discipline is that it stood aside through the last leg of the crash; on the no-hindsight gate those weeks were **open**, so a desk trading the screen it could actually compute would have kept buying into the low. Phase 2 must not change the book for this (§5a forbids it) and Phase 3 must not re-cut the P&L for it — what changes is the claim: entry timing in this book is **not** point-in-time, and `docs/20_trade_book.md` and the interview pack say so. The rupee cost of the difference is a Phase 2/3 question, not a Phase 1 one.

## 7. Sensitivity band — the CONTRACTS §5 required cases

Each case swaps one input through the same arithmetic (`parity_sensitivity_cases.csv`). Required cases: lag-1 / lag-3 / point-in-time grade mix; each grade differential at its evidence quartiles and ± one IQR width (both readings of "± IQR" are shown); every `domestic_anchor_premium_sensitivity_inr_t` value; the sticky anchor (trailing `domestic_anchor_trailing_bdays`-day mean MCX spot + `domestic_anchor_premium_trailing_inr_t`, window ending on the value date); every `conversion_cost_sensitivity_inr_t_ingot` value; metal-yield and heavies-value ranges from the Phase 0 notes (registered in parity.yaml); the anchor on the third-party MCX mirror M1 (PROXY). Informational: mirror M1/2M by lane, goods at spot, PIT mix and 18k together, and the MASTER_SPEC Taint/Tabor +0.10 factor.

**Open in-window weeks (of 27) per case**

| Case | Group | Req. | Zorba JEA | Zorba USEC | TT JEA | TT USEC | Tense JEA | Tense USEC | Flips vs base (Σ) |
|---|---|---|---|---|---|---|---|---|---|
| `base` | base | yes | 17 | 14 | 14 | 13 | 27 | 26 | 0 |
| `mix_lag1` | grade_mix | yes | 9 | 9 | 9 | 9 | 19 | 18 | 38 |
| `mix_lag3` | grade_mix | yes | 27 | 26 | 24 | 19 | 27 | 27 | 41 |
| `mix_pit` | grade_mix | yes | 26 | 24 | 24 | 24 | 27 | 27 | 45 |
| `grade_diff_q25` | grade_diff | yes | 20 | 19 | 22 | 20 | 27 | 27 | 24 |
| `grade_diff_q75` | grade_diff | yes | 10 | 9 | 11 | 10 | 19 | 17 | 35 |
| `grade_diff_minus_iqr` | grade_diff | yes | 26 | 23 | 22 | 22 | 27 | 27 | 36 |
| `grade_diff_plus_iqr` | grade_diff | yes | 9 | 9 | 9 | 8 | 17 | 14 | 45 |
| `anchor_premium_-55000` | anchor_premium | yes | 4 | 1 | 1 | 1 | 6 | 6 | 92 |
| `anchor_premium_-52000` | anchor_premium | yes | 4 | 4 | 3 | 1 | 6 | 6 | 87 |
| `anchor_premium_-9000` | anchor_premium | yes | 17 | 14 | 14 | 13 | 27 | 26 | 0 |
| `anchor_premium_+13000` | anchor_premium | yes | 27 | 27 | 27 | 27 | 27 | 27 | 51 |
| `anchor_sticky_trailing` | anchor_sticky | yes | 26 | 26 | 25 | 25 | 26 | 26 | 59 |
| `anchor_mirror_m1` | anchor_mirror | yes | 17 | 15 | 15 | 13 | 27 | 27 | 7 |
| `anchor_mirror_lane_contract` | anchor_mirror | info | 17 | 18 | 15 | 16 | 27 | 27 | 11 |
| `conversion_8000` | conversion | yes | 19 | 17 | 17 | 17 | 27 | 27 | 13 |
| `conversion_12000` | conversion | yes | 17 | 14 | 14 | 13 | 27 | 26 | 0 |
| `conversion_18000` | conversion | yes | 10 | 10 | 10 | 9 | 22 | 21 | 29 |
| `conversion_30000` | conversion | yes | 8 | 8 | 8 | 8 | 13 | 11 | 55 |
| `metal_yield_low` | recovery | yes | 14 | 13 | 10 | 9 | 22 | 22 | 21 |
| `metal_yield_high` | recovery | yes | 17 | 17 | 17 | 17 | 27 | 27 | 11 |
| `heavies_value_0.4` | heavies | yes | 13 | 10 | 14 | 13 | 27 | 26 | 8 |
| `heavies_value_1.5` | heavies | yes | 22 | 21 | 14 | 13 | 27 | 26 | 12 |
| `goods_fx_spot` | goods_fx | info | 17 | 15 | 14 | 13 | 27 | 27 | 2 |
| `pit_mix_and_conv18k` | informational | info | 23 | 22 | 21 | 20 | 27 | 27 | 53 |
| `tt_spec_factor_plus` | informational | info | 17 | 14 | 5 | 5 | 27 | 26 | 17 |
| `trade_eligible_5a` | section_5a_rule | rule | 10 | 10 | 10 | 9 | 22 | 21 | 29 |

**When the key cases flip the base flag** (in-window weeks opened / closed relative to base)

| Case | Grade-lane | Opens | Closes |
|---|---|---|---|
| `mix_lag1` | zorba JEA_NSA | none | 06-May–27-May (4), 05-Aug–26-Aug (4) |
| `mix_lag1` | zorba USEC_MUN | none | 06-May–20-May (3), 12-Aug–19-Aug (2) |
| `mix_lag1` | taint_tabor JEA_NSA | none | 06-May–20-May (3), 12-Aug–19-Aug (2) |
| `mix_lag1` | taint_tabor USEC_MUN | none | 06-May–20-May (3), 12-Aug |
| `mix_lag1` | tense JEA_NSA | none | 10-Jun–29-Jul (8) |
| `mix_lag1` | tense USEC_MUN | none | 03-Jun–08-Jul (6), 22-Jul–29-Jul (2) |
| `mix_lag3` | zorba JEA_NSA | 03-Jun–29-Jul (9), 02-Sep | none |
| `mix_lag3` | zorba USEC_MUN | 27-May–08-Jul (7), 22-Jul–05-Aug (3), 26-Aug–02-Sep (2) | none |
| `mix_lag3` | taint_tabor JEA_NSA | 27-May–10-Jun (3), 01-Jul–08-Jul (2), 22-Jul–05-Aug (3), 26-Aug–02-Sep (2) | none |
| `mix_lag3` | taint_tabor USEC_MUN | 27-May–10-Jun (3), 22-Jul–29-Jul (2), 26-Aug–02-Sep (2) | 12-Aug |
| `mix_lag3` | tense USEC_MUN | 15-Jul | none |
| `mix_pit` | zorba JEA_NSA | 03-Jun–29-Jul (9) | none |
| `mix_pit` | zorba USEC_MUN | 27-May–05-Aug (11) | 19-Aug |
| `mix_pit` | taint_tabor JEA_NSA | 27-May–05-Aug (11) | 19-Aug |
| `mix_pit` | taint_tabor USEC_MUN | 27-May–05-Aug (11) | none |
| `mix_pit` | tense USEC_MUN | 15-Jul | none |
| `grade_diff_minus_iqr` | zorba JEA_NSA | 03-Jun–08-Jul (6), 22-Jul–29-Jul (2), 02-Sep | none |
| `grade_diff_minus_iqr` | zorba USEC_MUN | 27-May–17-Jun (4), 22-Jul–05-Aug (3), 26-Aug–02-Sep (2) | none |
| `grade_diff_minus_iqr` | taint_tabor JEA_NSA | 27-May–10-Jun (3), 22-Jul–05-Aug (3), 26-Aug–02-Sep (2) | none |
| `grade_diff_minus_iqr` | taint_tabor USEC_MUN | 27-May–10-Jun (3), 22-Jul–05-Aug (3), 19-Aug–02-Sep (3) | none |
| `grade_diff_minus_iqr` | tense USEC_MUN | 15-Jul | none |
| `grade_diff_plus_iqr` | zorba JEA_NSA | none | 06-May–27-May (4), 05-Aug–26-Aug (4) |
| `grade_diff_plus_iqr` | zorba USEC_MUN | none | 06-May–20-May (3), 12-Aug–19-Aug (2) |
| `grade_diff_plus_iqr` | taint_tabor JEA_NSA | none | 06-May–20-May (3), 12-Aug–19-Aug (2) |
| `grade_diff_plus_iqr` | taint_tabor USEC_MUN | none | 29-Apr–20-May (4), 12-Aug |
| `grade_diff_plus_iqr` | tense JEA_NSA | none | 03-Jun–29-Jul (9), 02-Sep |
| `grade_diff_plus_iqr` | tense USEC_MUN | none | 27-May–08-Jul (7), 22-Jul–05-Aug (3), 26-Aug–02-Sep (2) |
| `anchor_premium_-52000` | zorba JEA_NSA | none | 01-Apr–27-May (9), 05-Aug–26-Aug (4) |
| `anchor_premium_-52000` | zorba USEC_MUN | none | 01-Apr–20-May (8), 12-Aug–19-Aug (2) |
| `anchor_premium_-52000` | taint_tabor JEA_NSA | none | 18-Mar, 01-Apr–20-May (8), 12-Aug–19-Aug (2) |
| `anchor_premium_-52000` | taint_tabor USEC_MUN | none | 11-Mar–20-May (11), 12-Aug |
| `anchor_premium_-52000` | tense JEA_NSA | none | 15-Apr–02-Sep (21) |
| `anchor_premium_-52000` | tense USEC_MUN | none | 15-Apr–08-Jul (13), 22-Jul–02-Sep (7) |
| `anchor_premium_+13000` | zorba JEA_NSA | 03-Jun–29-Jul (9), 02-Sep | none |
| `anchor_premium_+13000` | zorba USEC_MUN | 27-May–05-Aug (11), 26-Aug–02-Sep (2) | none |
| `anchor_premium_+13000` | taint_tabor JEA_NSA | 27-May–05-Aug (11), 26-Aug–02-Sep (2) | none |
| `anchor_premium_+13000` | taint_tabor USEC_MUN | 27-May–05-Aug (11), 19-Aug–02-Sep (3) | none |
| `anchor_premium_+13000` | tense USEC_MUN | 15-Jul | none |
| `anchor_sticky_trailing` | zorba JEA_NSA | 03-Jun–29-Jul (9), 02-Sep | 04-Mar |
| `anchor_sticky_trailing` | zorba USEC_MUN | 27-May–05-Aug (11), 26-Aug–02-Sep (2) | 04-Mar |
| `anchor_sticky_trailing` | taint_tabor JEA_NSA | 27-May–05-Aug (11), 26-Aug–02-Sep (2) | 04-Mar, 25-Mar |
| `anchor_sticky_trailing` | taint_tabor USEC_MUN | 27-May–05-Aug (11), 19-Aug–02-Sep (3) | 04-Mar, 25-Mar |
| `anchor_sticky_trailing` | tense JEA_NSA | none | 04-Mar |
| `anchor_sticky_trailing` | tense USEC_MUN | 15-Jul | 04-Mar |
| `anchor_mirror_m1` | zorba JEA_NSA | 03-Jun | 26-Aug |
| `anchor_mirror_m1` | zorba USEC_MUN | 27-May | none |
| `anchor_mirror_m1` | taint_tabor JEA_NSA | 27-May | none |
| `anchor_mirror_m1` | taint_tabor USEC_MUN | 19-Aug | 12-Aug |
| `anchor_mirror_m1` | tense USEC_MUN | 15-Jul | none |
| `conversion_18000` | zorba JEA_NSA | none | 13-May–27-May (3), 05-Aug–26-Aug (4) |
| `conversion_18000` | zorba USEC_MUN | none | 13-May–20-May (2), 12-Aug–19-Aug (2) |
| `conversion_18000` | taint_tabor JEA_NSA | none | 13-May–20-May (2), 12-Aug–19-Aug (2) |
| `conversion_18000` | taint_tabor USEC_MUN | none | 06-May–20-May (3), 12-Aug |
| `conversion_18000` | tense JEA_NSA | none | 17-Jun–15-Jul (5) |
| `conversion_18000` | tense USEC_MUN | none | 17-Jun–08-Jul (4), 02-Sep |
| `conversion_30000` | zorba JEA_NSA | none | 29-Apr–27-May (5), 05-Aug–26-Aug (4) |
| `conversion_30000` | zorba USEC_MUN | none | 29-Apr–20-May (4), 12-Aug–19-Aug (2) |
| `conversion_30000` | taint_tabor JEA_NSA | none | 29-Apr–20-May (4), 12-Aug–19-Aug (2) |
| `conversion_30000` | taint_tabor USEC_MUN | none | 29-Apr–20-May (4), 12-Aug |
| `conversion_30000` | tense JEA_NSA | none | 27-May–05-Aug (11), 19-Aug–02-Sep (3) |
| `conversion_30000` | tense USEC_MUN | none | 13-May, 27-May–08-Jul (7), 22-Jul–02-Sep (7) |
| `metal_yield_low` | zorba JEA_NSA | none | 27-May, 05-Aug, 26-Aug |
| `metal_yield_low` | zorba USEC_MUN | none | 19-Aug |
| `metal_yield_low` | taint_tabor JEA_NSA | none | 13-May–20-May (2), 12-Aug–19-Aug (2) |
| `metal_yield_low` | taint_tabor USEC_MUN | none | 06-May–20-May (3), 12-Aug |
| `metal_yield_low` | tense JEA_NSA | none | 17-Jun–15-Jul (5) |
| `metal_yield_low` | tense USEC_MUN | none | 17-Jun–08-Jul (4) |
| `heavies_value_0.4` | zorba JEA_NSA | none | 27-May, 05-Aug, 19-Aug–26-Aug (2) |
| `heavies_value_0.4` | zorba USEC_MUN | none | 13-May–20-May (2), 12-Aug–19-Aug (2) |
| `goods_fx_spot` | zorba USEC_MUN | 05-Aug | none |
| `goods_fx_spot` | tense USEC_MUN | 15-Jul | none |

Findings.
- **The grade-mix lag and the anchor model decide the shape of the window; costs decide its width.** The point-in-time mix and the sticky anchor each re-open Zorba and Taint/Tabor through the June–July trough that shuts the base case; the extreme premiums (−52k/−55k vs +13k) shut or open almost every week.
- Required cases that shut the first window week (04-Mar) for every grade-lane: `anchor_sticky_trailing` (sticky-anchor net arb that week −₹20,382 to ₹1,960). The mirror-M1 anchor, which removes the proxy's March overshoot, still leaves that week open for every grade-lane — so the March eligibility does not rest on the proxy bias alone, but it does rest on the constant-premium anchor.
- Conversion 18k/30k, the low yield and Tense's + IQR differential flip Tense around the June–July trough; goods at spot and the mirror-M1 anchor flip at most 2 weeks per grade-lane.
- Chart: `p1_sensitivity_band.png` (min–max and inter-quartile envelope across the required cases).

## 8. Table 1.5 — two-way P&L grids on 1,000 MT

P&L impact = (net_arb_shocked − net_arb_base) × 1,000 MT: the change in the *parity margin* of a trade whose purchase and sale both re-price (a fixed-price position is Phase 3). `model.market_shock_overrides` re-derives every dependent input: LME shocks scale 3M and cash, so CFR, the customs duty base, finance and the Zorba by-product move; the MCX proxy anchor (duty-paid LME cash parity × carry, premium 0) scales with LME × FX and keeps its carry; a USD/INR level scales the goods forward and the customs notified rate by the week's observed ratio to spot. Scrap BCD does not move the MCX anchor (that parity uses the HS 7601 primary duty). INR costs are held. Freight: under **CFR** the seller books freight, so freight shocks do not change the buyer's margin (only BCD columns move); under **FOB** the desk books freight and the CFR-equivalent cost rises one-for-one with the freight change. Freight levels are hindsight reconstructions.

**(a) LME × USD/INR — `first_eligible` 04-Mar-2022 zorba JEA_NSA** (base net arb ₹51,903/t; ₹ million on 1,000 MT; all 9 FX columns in the CSV)

| LME shock | 74 | 76 | 78 | 80 | 82 | base 76.34 |
|---|---|---|---|---|---|---|
| +10% | 4.76 | 6.82 | 8.88 | 10.95 | 13.01 | 7.17 |
| +5% | 1.28 | 3.25 | 5.22 | 7.19 | 9.16 | 3.59 |
| +0% | −2.20 | −0.32 | 1.55 | 3.43 | 5.31 | 0.00 |
| −5% | −5.67 | −3.89 | −2.11 | −0.33 | 1.45 | −3.59 |
| −10% | −9.15 | −7.46 | −5.77 | −4.09 | −2.40 | −7.17 |
| −15% | −12.63 | −11.03 | −9.44 | −7.85 | −6.25 | −10.76 |
| −20% | −16.10 | −14.60 | −13.10 | −11.60 | −10.10 | −14.35 |
| −25% | −19.58 | −18.17 | −16.77 | −15.36 | −13.96 | −17.93 |
| −30% | −23.06 | −21.75 | −20.43 | −19.12 | −17.81 | −21.52 |

At base FX a −10% LME move costs ₹7.17 mn and −30% ₹21.52 mn on 1,000 MT; each ₹1 on USD/INR (78→79, LME unchanged) is worth ₹0.94 mn. The margin is long LME and long USD because the anchor (primary aluminium at 7.5% duty, × recovery) carries more metal value than the scrap cost (grade factor × LME at 2.75% duty) while conversion and port costs stay fixed in rupees. Window open in 90 of 90 grid cells.

**(b) Freight × BCD, FOB terms — `first_eligible`** (₹ million on 1,000 MT; CFR rows all equal the 0% freight row)

| Freight shock | BCD 0% | BCD 2.5% | BCD 5% | BCD 7.5% | BCD 10% |
|---|---|---|---|---|---|
| +60% | 4.71 | −1.10 | −6.92 | −12.74 | −18.56 |
| +40% | 5.07 | −0.74 | −6.54 | −12.35 | −18.16 |
| +20% | 5.43 | −0.37 | −6.17 | −11.96 | −17.76 |
| +0% | 5.79 | 0.00 | −5.79 | −11.58 | −17.36 |
| −20% | 6.15 | 0.37 | −5.41 | −11.19 | −16.97 |
| −40% | 6.50 | 0.74 | −5.03 | −10.80 | −16.57 |

**(a) LME × USD/INR — `june_trough` 17-Jun-2022 zorba JEA_NSA** (base net arb −₹3,678/t; ₹ million on 1,000 MT; all 9 FX columns in the CSV)

| LME shock | 74 | 76 | 78 | 80 | 82 | base 78.08 |
|---|---|---|---|---|---|---|
| +10% | 0.69 | 1.15 | 1.60 | 2.05 | 2.50 | 1.62 |
| +5% | −0.07 | 0.36 | 0.79 | 1.22 | 1.65 | 0.81 |
| +0% | −0.84 | −0.43 | −0.02 | 0.40 | 0.81 | 0.00 |
| −5% | −1.60 | −1.21 | −0.82 | −0.43 | −0.04 | −0.81 |
| −10% | −2.37 | −2.00 | −1.63 | −1.26 | −0.89 | −1.62 |
| −15% | −3.13 | −2.79 | −2.44 | −2.09 | −1.74 | −2.42 |
| −20% | −3.90 | −3.57 | −3.24 | −2.92 | −2.59 | −3.23 |
| −25% | −4.67 | −4.36 | −4.05 | −3.74 | −3.44 | −4.04 |
| −30% | −5.43 | −5.14 | −4.86 | −4.57 | −4.28 | −4.85 |

At base FX a −10% LME move costs ₹1.62 mn and −30% ₹4.85 mn on 1,000 MT; each ₹1 on USD/INR (78→79, LME unchanged) is worth ₹0.21 mn. The margin is long LME and long USD because the anchor (primary aluminium at 7.5% duty, × recovery) carries more metal value than the scrap cost (grade factor × LME at 2.75% duty) while conversion and port costs stay fixed in rupees. Window open in 0 of 90 grid cells.

**(b) Freight × BCD, FOB terms — `june_trough`** (₹ million on 1,000 MT; CFR rows all equal the 0% freight row)

| Freight shock | BCD 0% | BCD 2.5% | BCD 5% | BCD 7.5% | BCD 10% |
|---|---|---|---|---|---|
| +60% | 3.79 | −0.90 | −5.59 | −10.28 | −14.97 |
| +40% | 4.08 | −0.60 | −5.28 | −9.96 | −14.64 |
| +20% | 4.37 | −0.30 | −4.97 | −9.64 | −14.32 |
| +0% | 4.66 | 0.00 | −4.66 | −9.33 | −13.99 |
| −20% | 4.96 | 0.30 | −4.36 | −9.01 | −13.67 |
| −40% | 5.25 | 0.60 | −4.05 | −8.69 | −13.34 |

**(a) LME × USD/INR — `first_eligible_long_lane` 04-Mar-2022 zorba USEC_MUN** (base net arb ₹49,904/t; ₹ million on 1,000 MT; all 9 FX columns in the CSV)

| LME shock | 74 | 76 | 78 | 80 | 82 | base 76.34 |
|---|---|---|---|---|---|---|
| +10% | 4.68 | 6.72 | 8.76 | 10.80 | 12.84 | 7.07 |
| +5% | 1.26 | 3.20 | 5.15 | 7.09 | 9.04 | 3.54 |
| +0% | −2.17 | −0.32 | 1.54 | 3.39 | 5.24 | 0.00 |
| −5% | −5.60 | −3.84 | −2.08 | −0.32 | 1.44 | −3.54 |
| −10% | −9.03 | −7.36 | −5.69 | −4.02 | −2.36 | −7.07 |
| −15% | −12.45 | −10.88 | −9.30 | −7.73 | −6.15 | −10.61 |
| −20% | −15.88 | −14.40 | −12.92 | −11.44 | −9.95 | −14.15 |
| −25% | −19.31 | −17.92 | −16.53 | −15.14 | −13.75 | −17.68 |
| −30% | −22.74 | −21.44 | −20.14 | −18.85 | −17.55 | −21.22 |

At base FX a −10% LME move costs ₹7.07 mn and −30% ₹21.22 mn on 1,000 MT; each ₹1 on USD/INR (78→79, LME unchanged) is worth ₹0.93 mn. The margin is long LME and long USD because the anchor (primary aluminium at 7.5% duty, × recovery) carries more metal value than the scrap cost (grade factor × LME at 2.75% duty) while conversion and port costs stay fixed in rupees. Window open in 90 of 90 grid cells.

**(b) Freight × BCD, FOB terms — `first_eligible_long_lane`** (₹ million on 1,000 MT; CFR rows all equal the 0% freight row)

| Freight shock | BCD 0% | BCD 2.5% | BCD 5% | BCD 7.5% | BCD 10% |
|---|---|---|---|---|---|
| +60% | 0.84 | −5.13 | −11.11 | −17.08 | −23.06 |
| +40% | 2.51 | −3.42 | −9.35 | −15.28 | −21.21 |
| +20% | 4.17 | −1.71 | −7.59 | −13.48 | −19.36 |
| +0% | 5.84 | 0.00 | −5.84 | −11.67 | −17.51 |
| −20% | 7.50 | 1.71 | −4.08 | −9.87 | −15.66 |
| −40% | 9.17 | 3.42 | −2.32 | −8.07 | −13.81 |

Freight matters little on the short Gulf lane (JEA_NSA freight ≈ USD 23.08/t): at the base duty no freight shock in the Gulf-lane grid moves the margin by more than ₹1.10 mn per 1,000 MT. For scale, the same week on USEC_MUN (freight USD 106.41/t): +60% freight on FOB terms costs ₹5.13 mn per 1,000 MT — the `first_eligible_long_lane` row of `parity_sensitivity_freight_duty.csv`, published so this number can be checked without re-running the model (worst long-lane shock at the base duty ₹5.13 mn). A BCD rise from 2.5% to 5% costs ₹4.66–5.84 mn per 1,000 MT across the reference cases. Charts: `p1_sensitivity_lme_fx.png`, `p1_sensitivity_freight_duty.png`.

## 9. Table 1.6 — scrap reality check (SPA settlement, moisture, contamination, yield)

Rules (`desk.parity.quality`, numbers registered in parity.yaml from commercial.yaml `rejection_penalty_schedule`): moisture above `standard_moisture_franchise_frac` (0.01) is deducted from invoice weight 1:1; contamination above the grade's priced `contamination_frac_<grade>` earns a price discount of 1.5 × the excess on the whole lot; an excess above 3 points (or any radioactivity finding) makes the lot rejectable. Value-based costs (goods, duties, finance) scale with the settled invoice value; box-based costs (port, PSIC) do not. Recovery = (1 − moisture)(1 − contamination) × yield. Scenarios re-value the reference week/lane (04-Mar-2022, JEA_NSA) for every grade; REJECTABLE rows are shown as if the desk accepted at the schedule discount (the renegotiation reference).

| Grade | Moisture | Contam. | Outcome | Payable | Discount | Recovery | Landed / t recovered | Net-arb impact / t | Value of SPA clauses / t |
|---|---|---|---|---|---|---|---|---|---|
| zorba | 0.010 | 0.060 | ACCEPT | 1.000 | 0.000 | 0.8655 | ₹251,514 | ₹0 | ₹0 |
| zorba | 0.030 | 0.060 | ACCEPT_ADJUSTED | 0.980 | 0.000 | 0.8480 | ₹251,605 | −₹1,126 | ₹4,320 |
| zorba | 0.010 | 0.080 | ACCEPT_ADJUSTED | 1.000 | 0.030 | 0.8470 | ₹249,331 | ₹991 | ₹6,481 |
| zorba | 0.030 | 0.080 | ACCEPT_ADJUSTED | 0.980 | 0.030 | 0.8299 | ₹249,422 | −₹154 | ₹10,671 |
| zorba | 0.010 | 0.110 | REJECTABLE | 1.000 | 0.075 | 0.8194 | ₹245,872 | ₹2,476 | ₹16,201 |
| taint_tabor | 0.005 | 0.020 | ACCEPT | 1.000 | 0.000 | 0.8971 | ₹243,198 | ₹0 | ₹0 |
| taint_tabor | 0.030 | 0.020 | ACCEPT_ADJUSTED | 0.980 | 0.000 | 0.8746 | ₹244,526 | −₹2,400 | ₹4,320 |
| taint_tabor | 0.005 | 0.040 | ACCEPT_ADJUSTED | 1.000 | 0.030 | 0.8788 | ₹240,891 | ₹1,022 | ₹6,481 |
| taint_tabor | 0.030 | 0.040 | ACCEPT_ADJUSTED | 0.980 | 0.030 | 0.8567 | ₹242,207 | −₹1,370 | ₹10,671 |
| taint_tabor | 0.005 | 0.070 | REJECTABLE | 1.000 | 0.075 | 0.8513 | ₹237,243 | ₹2,555 | ₹16,201 |
| tense | 0.005 | 0.020 | ACCEPT | 1.000 | 0.000 | 0.9166 | ₹220,937 | ₹0 | ₹0 |
| tense | 0.030 | 0.020 | ACCEPT_ADJUSTED | 0.980 | 0.000 | 0.8936 | ₹222,137 | −₹2,850 | ₹4,016 |
| tense | 0.005 | 0.040 | ACCEPT_ADJUSTED | 1.000 | 0.030 | 0.8979 | ₹218,831 | ₹447 | ₹6,024 |
| tense | 0.030 | 0.040 | ACCEPT_ADJUSTED | 0.980 | 0.030 | 0.8753 | ₹220,021 | −₹2,384 | ₹9,919 |
| tense | 0.005 | 0.070 | REJECTABLE | 1.000 | 0.075 | 0.8698 | ₹215,502 | ₹1,116 | ₹15,059 |

Metal-yield range at base moisture/contamination (net-arb impact per MT of scrap):

| Grade | Yield low | Yield high |
|---|---|---|
| zorba | −₹2,775 | ₹2,775 |
| taint_tabor | −₹5,814 | ₹5,814 |
| tense | −₹5,814 | ₹2,907 |

Findings. (1) Wet or dirty cargo costs the desk its share of metal value; the 'value of SPA clauses' column is what the weight deduction and discount give back (`net_arb_no_spa_clauses_inr_t` is the unprotected margin). The weight deduction returns most, not all, of a moisture excess (port costs and the metal in franchise moisture are not refunded). At this week's prices the 1.5× contamination discount more than compensates the lost metal (+2 points: impact ₹991, ₹1,022, ₹447 for Zorba / Taint-Tabor / Tense) — a punitive design that deters dilution and that a supplier would negotiate down. (2) Moisture *inside* the franchise is paid for: Tense priced at 0.005 but delivered at the 0.01 franchise costs ₹1,373/t with no recourse. (3) Melt yield, which no clause covers, moves the margin by the size of the hurdle: Taint/Tabor at the low end of its yield range loses ₹5,814/t.

## 10. Table 1.7 — LME term structure

**Pricing reference.** The desk's LME-linked SPAs settle against the **LME Official Cash Settlement Price** (exchange.yaml `lme_pricing_reference`: "LME Official Settlement Price = LME Aluminium cash offer at the close of the second Ring session (established and published within 12:20–13:25 London; see lme_official_publication_window_london)"), averaged over the month after the B/L month (`lme_m1_pricing_rule`: "Provisional invoice on B/L; final price = arithmetic average of daily LME Official Cash Settlement Prices over the calendar month following the B/L month (M+1), × grade factor"). The parity itself prices off **3M**, the forward that can be hedged on the decision date; this section measures the gap.

**Method.** Weekly Cash − 3M on the parity value date (positive = backwardation). The market-implied expected M+1 average of cash is read off a forward curve linear in calendar days between the cash prompt (value date + 2 business days) and the 3M prompt (value date + 3 months, next weekday); each weekday of the M+1 month fixes a cash price for its own T+2 prompt, and the expected average is the mean of the curve over those prompts (expectations hypothesis — no risk premium; LME holidays ignored). B/L month = the parity week's month (`mplus1_bl_month_offset_months` = 0). Structure effect for a buyer priced on M+1 average cash = 3M − implied M+1 average (positive: the structure earns the buyer vs a 3M-priced parity). The realised M+1 average is shown as **HINDSIGHT** only.

In the window the daily LME curve was in contango on 91 days and backwardation on 33 (parity value dates: 19 contango / 8 backwardation weeks; mean Cash − 3M USD −11.04/t, range −37.5 to 31.0).

| Parity month | Weeks | Mean Cash−3M USD/t | Contango/backw. weeks | 3M carry % p.a. | M+1 month | Ex-ante effect USD/t | Ex-ante ₹ mn / 1,000 t | HINDSIGHT 3M − realised USD/t | HINDSIGHT ₹ mn / 1,000 t |
|---|---|---|---|---|---|---|---|---|---|
| 2022-03 | 4 | −6.0 | 3/1 | 0.80 | 2022-04 | 4.97 | 0.38 | 321.0 | 24.49 |
| 2022-04 | 5 | −18.9 | 5/0 | 2.39 | 2022-05 | 11.86 | 0.90 | 472.2 | 35.94 |
| 2022-05 | 4 | −23.1 | 4/0 | 3.35 | 2022-06 | 15.06 | 1.16 | 287.6 | 22.26 |
| 2022-06 | 4 | −21.5 | 4/0 | 3.38 | 2022-07 | 13.47 | 1.05 | 196.6 | 15.29 |
| 2022-07 | 5 | −6.0 | 3/2 | 1.05 | 2022-08 | 2.77 | 0.22 | −22.1 | −1.76 |
| 2022-08 | 4 | 5.2 | 0/4 | −0.86 | 2022-09 | −3.56 | −0.28 | 211.6 | 16.85 |
| 2022-09 | 1 | 8.0 | 0/1 | −1.45 | 2022-10 | −4.05 | −0.32 | 57.7 | 4.61 |

(a) **M+1 basis.** Averaged over the window weeks the curve shape alone earned a buyer priced on M+1 average cash USD 6.99/t of aluminium content (₹0.54 mn per 1,000 t; multiply by the grade factor, ~0.7–0.85, for tonnes of scrap) versus the 3M price the parity used; it cost the buyer only in the backwardation weeks (04-Mar, 22-Jul–02-Sep (7)). That is small next to what the *price move* did: in hindsight the realised M+1 cash average was on average USD 236/t below the 3M at decision (the crash). That windfall on the purchase leg is only kept if the sale price was fixed or hedged over the same period — an MCX-linked sale fell too — which is why the M+1 quotational period must be matched to the sale and hedge dates.

(b) **Roll yield on a 1,000 MT short MCX hedge** (200 lots of 5 MT), rolled M1 → M2 7 panel trading days before expiry (₹ million per 1,000 MT; + = earned by the short):

| Contract | Roll date | In window | Proxy M2−M1 ₹/kg | MCX proxy | MCX mirror (PROXY) | LME structure | LME carry USD/t | LME-equivalent | Expiry note |
|---|---|---|---|---|---|---|---|---|---|
| 2022-01 | 20-Jan-2022 | no | 0.70 | 0.70 | 0.60 | BACKWARDATION | −8.95 | −0.67 |  |
| 2022-02 | 17-Feb-2022 | no | 0.86 | 0.86 | 1.45 | BACKWARDATION | −19.33 | −1.45 |  |
| 2022-03 | 22-Mar-2022 | yes | 0.88 | 0.88 | 6.70 | FLAT | 0.00 | 0.00 |  |
| 2022-04 | 20-Apr-2022 | yes | 0.92 | 0.92 | 2.00 | CONTANGO | 3.60 | 0.27 |  |
| 2022-05 | 20-May-2022 | yes | 0.96 | 0.96 | 1.00 | CONTANGO | 1.33 | 0.10 |  |
| 2022-06 | 21-Jun-2022 | yes | 0.87 | 0.87 | −1.05 | CONTANGO | 4.03 | 0.31 |  |
| 2022-07 | 20-Jul-2022 | yes | 1.02 | 1.02 | −0.40 | BACKWARDATION | −3.12 | −0.25 |  |
| 2022-08 | 19-Aug-2022 | yes | 0.95 | 0.95 | 3.25 | BACKWARDATION | −0.83 | −0.07 | panel 31-Aug vs MCX 30-Aug |
| 2022-09 | 21-Sep-2022 | no | 0.93 | 0.93 | 5.40 | CONTANGO | 9.40 | 0.75 |  |
| 2022-10 | 20-Oct-2022 | no | 1.02 | 1.02 | 2.20 | CONTANGO | 4.77 | 0.39 |  |

Over the six in-window rolls the MCX proxy roll earns ₹5.60 mn per 1,000 MT, the mirror ₹11.50 mn and the LME-equivalent carry ₹0.38 mn. Read carefully: the proxy's M2 − M1 is *by construction* INR interest carry on duty-paid parity (~₹0.9–1.0/kg a month), not metal contango — earning it only offsets the desk's own financing of the physical. The LME curve itself was nearly flat on roll dates (small contango earns, small backwardation costs). The mirror's in-window rolls swing from ₹−1.05 mn to ₹6.70 mn because its 2M series is partly stale, so it is not evidence of a real MCX roll yield. The panel's rule-based expiry differs from MCX's published date in 1 contract month(s) (2022-08). Chart: `p1_term_structure.png`.

## 11. Table 1.3 — domestic anchor: correlation study (the anchor is PROXY)

The anchor is MCX Aluminium (panel PROXY: duty-paid LME cash import parity × INR carry, `mcx_domestic_premium_inr_kg` = 0) plus a constant secondary-ingot premium. Basis = series A − series B.

| Pair (A vs B) | Sample | Days | Level corr | Daily log-ret corr | Weekly log-ret corr | Basis mean ₹/t | Basis std ₹/t |
|---|---|---|---|---|---|---|---|
| `proxy_m1_vs_duty_paid_parity` | Mar–Aug 2022 | 126 | 1.000 | 0.999 | 0.999 | ₹431 | ₹270 |
| `proxy_m1_vs_duty_paid_parity` | 2018–2022 | 1264 | 1.000 | 0.998 | 0.999 | ₹324 | ₹229 |
| `proxy_spot_vs_duty_paid_parity` | Mar–Aug 2022 | 126 | 1.000 | 1.000 | 1.000 | ₹0 | ₹0 |
| `proxy_spot_vs_duty_paid_parity` | 2018–2022 | 1264 | 1.000 | 1.000 | 1.000 | ₹0 | ₹0 |
| `mirror_m1_vs_duty_paid_parity` | Mar–Aug 2022 | 125 | 0.988 | 0.565 | 0.935 | ₹104 | ₹6,277 |
| `mirror_m1_vs_duty_paid_parity` | 2018–2022 | 1250 | 0.983 | 0.496 | 0.837 | −₹707 | ₹7,678 |
| `mirror_m1_vs_proxy_m1` | Mar–Aug 2022 | 125 | 0.988 | 0.563 | 0.937 | −₹327 | ₹6,286 |
| `mirror_m1_vs_proxy_m1` | 2018–2022 | 1250 | 0.982 | 0.499 | 0.844 | −₹1,031 | ₹7,726 |
| `mirror_m2_vs_proxy_m2` | Mar–Aug 2022 | 125 | 0.986 | 0.407 | 0.908 | ₹1,626 | ₹6,281 |
| `mirror_m2_vs_proxy_m2` | 2018–2022 | 1231 | 0.982 | 0.360 | 0.788 | ₹413 | ₹7,927 |

- Proxy vs LME × FX × duty parity: correlations ≈ 1 are **mechanical** (the proxy is that parity), so they prove nothing about MCX; the spot identity (basis 0) confirms the construction.
- Mirror (third-party MCX closes, PROXY: provenance unverified) vs the same parity is the informative pair: level correlation 0.983–0.988, weekly returns 0.84–0.93, but daily returns only 0.50–0.57 (MCX's evening close vs the LME midday official) and a basis std of ₹6,277–₹7,678/t, larger than the ₹5,000/t hurdle. A weekly parity decision can live with that; a daily hedge P&L cannot (Phase 3 factor b).
- Secondary ingot vs parity (Phase 0 evidence, BigMint ADC12 via AlCircle, 15 dated prints 2023-12 → 2025-12, not 2022): median premium −₹8,955/t, std ₹23,965; correlation of the premium with parity −0.93; short-run pass-through of parity into ADC12 0.15; against a 120-day trailing parity the premium is −₹2,071 with std ₹17,533. Secondary ingot is sticky: the constant-premium anchor overstates it when parity spikes and understates it in a crash — exactly the March/June asymmetry in §6.

## 12. Hindsight and provenance disclosure

- **Freight levels are hindsight reconstructions** (CONTRACTS §4.3): the WCI shape is PROXY, the lane levels are ASSUMPTION calibrated to Container News anchors published up to ~7 months after the March 2022 weeks (`freight_weekly.csv` notes, 106 weeks). Under CFR terms freight only moves the FOB memo; under FOB terms see §8(b).
- **The lag-2 grade mix is a hindsight reconstruction**: DGCIS unit values for month m+2 were not published during month m. §5a adds the point-in-time mix as a screen against exactly that — itself an ASSUMPTION about the DGCIS release lag (verify PENDING) — **but on this panel that screen never binds, so `trade_eligible` reduces to a screen built on the lag-2 reconstruction (§6.1).** The eligibility calendar is therefore not a point-in-time calendar, and `trade_eligible_pit` is published beside it to show the difference.
- Grade differentials, the anchor premium and conversion cost come from 2024–25 evidence applied to 2022 (ASSUMPTION). USD/INR is the ECB cross (PROXY for the RBI reference rate). MCX is the import-parity proxy.
- The realised M+1 averages and every 'hindsight_' column are labelled and are never inputs to a flag.
- No trade decision here uses data published after its week, except through the disclosed reconstructions above; `eligible_on` enforces the latest week_end ≤ trade date.

## 13. What this does and doesn't tell you

**Does:** it shows, per grade and lane, whether the published ingredients of a 2022 import margin — LME, the rupee, notified duties, container logistics, a secondary-ingot anchor and recovery physics — added up to more than a ₹5,000/t hurdle, which assumption moves that answer, and by how much a price, FX, freight or duty shock changes it. It gives Component 2 a rule it cannot bend after the fact: trade only where the base, the point-in-time grade mix and a higher conversion cost all agree.

**Doesn't, first:** that rule is *unbendable*, not *point-in-time*. Two of its three screens read the lag-2 grade mix, the third never binds, and §6.1 measures what that costs: the no-hindsight gate would have been open in 140 of 162 in-window cases against the published rule's 82, including every week of the June–July trough. Anyone quoting the book's standing-aside as discipline must quote that with it.

**Doesn't:** it is not a record of real 2022 margins. No 2022 scrap grade quote, secondary-ingot price or freight fixture was retrievable, so the level of the margin (tens of thousands of rupees in March, below zero in July) is a model output, not a market fact; the spread between the required cases (median ₹71,342/t, up to ₹94,725/t in a week) is the honest error bar. The weekly flag also ignores execution: supplier availability, the 40–73 days between paying for the cargo and being paid for it in a window when LME cash fell 42% from its 07-Mar peak to its 15-Jul low, credit limits, and quality claims beyond the SPA schedule. A window being open is a licence to look for a trade, not evidence that the trade made money — that is Phase 3's job.

## 14. Open issues

1. MCX: replace the proxy with MCX bhavcopy closes (and re-run this page) — Table 1.3 then becomes a real LME–MCX basis study.
2. Anchor: any dated 2022 ADC12/LM6 India print would replace the 2024–25 premium and settle whether the constant or the sticky anchor is closer to 2022 reality.
3. Grade factors: a 2022 Zorba/Tense/Taint-Tabor CFR India assessment would remove the cross-period differential; a DGCIS release calendar would verify the point-in-time lag.
4. `lme_cash_prompt_bdays` (T+2) is stated from convention (verify PENDING); LME holidays are not removed from the M+1 averaging days.
5. The SPA contamination limit equals the priced composition by design; real contracts quote ISRI limits, which would make small excesses free for the supplier.
