# Deliverables index: every spec row mapped to the files that deliver it

> **ACADEMIC SIMULATION — not actual trades.** This page maps
> [`MASTER_SPEC_V3.md`](spec/MASTER_SPEC_V3.md) Tables 3–8 to the code, tables, charts and document sections that
> deliver each row.

**How to read it.** Tables and charts are in [`outputs/tables/`](../outputs/tables/) and
[`outputs/charts/`](../outputs/charts/). "§" means a section of the named document. `tests/test_reports_runner.py`
checks that every link on this page resolves and that every spec row appears.

**Status key.**

- **DONE** means the row is delivered.
- **DONE, with a caveat** means it is delivered, and the caveat is what a reviewer should read first.
- **PARTIAL** means part of the row is missing or weaker than the spec asks.

## Gaps and flags at a glance

| Row | Status | What is missing or weak |
|---|---|---|
| 5.1 | DONE, with a caveat | "As of the week end" covers prices, positions, trades and events only. The anchor premium, grade factors, freight levels and the INR 3M rate (same-month OECD average, up to a month of look-ahead) are later reconstructions, footnoted in every note. The credit band policy is a retrospective Phase 5 test: the notes name every booking that breaks it rather than voicing it as the trader's rule ([`reviews/phase4-7_review_log.md`](reviews/phase4-7_review_log.md) F2–F3). |
| 4.1, 4.6 | DONE, with a caveat | The mirror's daily MCX beta (0.45) is biased down by asynchronous closes; weekly it is 0.75 and close-time-matched 0.94. Mean GARCH VaR runs ₹4.27 m (proxy) → ₹8.5 m (weekly beta) → ₹17.3 m (daily beta, pessimistic) ([`40_var_garch.md`](40_var_garch.md) §4.3, [`var_mcx_beta.csv`](../outputs/tables/var_mcx_beta.csv)). The memo's position and stop levels were set with the 2022 book in view, and its VaR limit excludes grade spread. |
| 4.5 | DONE, with a caveat | The facility breach rests on two stated conventions: lines sanctioned on the plan's average balance (one ₹25 crore step higher, no day over the working-capital line) and LC use at face plus tolerance (without it: ₹1,286.2 m peak, 11 days over) ([`51_margin_liquidity.md`](51_margin_liquidity.md) §0, §1.4). |
| 5.2 | DONE, with a caveat | No evidence that headline tone led LME, but the March spike could not be tested and 28 weeks can only rule out a strong lead ([`70_sentiment_overlay.md`](70_sentiment_overlay.md) §0, §2.6). |
| 3.4 (text) | DONE (fixed after Phase 4–7) | The 8-Mar-2022 fall was printed as −12.2 % in [`31_adverse_events.md`](31_adverse_events.md) §1, the `exchange.yaml` note on `mcx_al_dpl_base_frac` and `research/regulatory_contract_notes.md`; all now read −12.1 % simple (−12.95 % log), and [`00_assumptions_log.md`](00_assumptions_log.md) has been re-rendered. |
| 1.3 | DONE, with a caveat | `domestic_anchor_premium_inr_t` is an ASSUMPTION with verification PENDING. The book's P&L is not sign-robust to it ([`30_mtm_attribution.md`](30_mtm_attribution.md) §13.9). |
| 1.7, 2.7 | DONE, with a caveat | The MCX series is a duty-parity proxy: it is always in contango and has unit beta. Roll gains are rupee carry, and basis risk is under-represented ([`30_mtm_attribution.md`](30_mtm_attribution.md) §13.10–13.11). |
| 2.8 | PARTIAL | Schedule and laycan slippage is sized, not simulated; no lot actually slips ([`reviews/phase1-3_fix_log.md`](reviews/phase1-3_fix_log.md) #13). |
| 4.2 | DONE, with a caveat | No MCX beta shock exists in the valuation API, so basis enters only as a sensitivity factor. No joint case of a low anchor premium with the point-in-time grade mix is published ([`41_monte_carlo.md`](41_monte_carlo.md) §10). |
| 4.3 | DONE, with a caveat | The model is illustrative, on synthetic data by design. The ranking is largely built into the SIM profiles ([`50_credit_scoring.md`](50_credit_scoring.md) §1). |
| 8.1 | DONE, with a caveat | [`00_assumptions_log.md`](00_assumptions_log.md) has not yet been re-rendered by Phase 0. It does not list the Phase 4–7 keys in `risk.yaml` and `risk_credit.yaml`, although the loader and the register itself include them. |
| 8.4 | PARTIAL | Several volatile parameters remain PENDING, each with a stated next step ([`verification_log.md`](verification_log.md) §A). |

## Table 3: Component 1, trade finder (import parity model)

| Row | Element | Delivered by | Status |
|---|---|---|---|
| 1.1 | Format: Python + Excel, weekly parity | [`desk/parity/`](../desk/parity/); [`parity_weekly.csv`](../outputs/tables/parity_weekly.csv); [`Metals_Desk_Master.xlsx`](../outputs/excel/Metals_Desk_Master.xlsx); [`10_parity_model.md`](10_parity_model.md) §2–§3; [`35_excel_workbook.md`](35_excel_workbook.md) §3 | DONE |
| 1.2 | Landed cost build-up | [`CONTRACTS.md`](../CONTRACTS.md) §5; [`10_parity_model.md`](10_parity_model.md) §3 (formula table), §5 (worked example); [`parity_weekly.csv`](../outputs/tables/parity_weekly.csv); [`p1_landed_cost_waterfall.png`](../outputs/charts/p1_landed_cost_waterfall.png) | DONE |
| 1.3 | Domestic price anchor + correlation study | [`10_parity_model.md`](10_parity_model.md) §11; [`parity_anchor_correlation.csv`](../outputs/tables/parity_anchor_correlation.csv); [`commercial.yaml`](../config/params/commercial.yaml) `domestic_anchor_premium_inr_t` | DONE, with a caveat |
| 1.4 | Parity flag (open/closed window) | [`10_parity_model.md`](10_parity_model.md) §6, §6.1; [`CONTRACTS.md`](../CONTRACTS.md) §5a; [`parity_weekly.csv`](../outputs/tables/parity_weekly.csv) `window_open`, `trade_eligible`; [`p1_window_heatmap.png`](../outputs/charts/p1_window_heatmap.png); [`p1_net_arb_weekly.png`](../outputs/charts/p1_net_arb_weekly.png) | DONE |
| 1.5 | Two-way sensitivity tables on 1,000 MT | [`10_parity_model.md`](10_parity_model.md) §8 (and the §7 sensitivity band); [`parity_sensitivity_lme_fx.csv`](../outputs/tables/parity_sensitivity_lme_fx.csv); [`parity_sensitivity_freight_duty.csv`](../outputs/tables/parity_sensitivity_freight_duty.csv); [`parity_sensitivity_summary.csv`](../outputs/tables/parity_sensitivity_summary.csv); [`p1_sensitivity_lme_fx.png`](../outputs/charts/p1_sensitivity_lme_fx.png); [`p1_sensitivity_freight_duty.png`](../outputs/charts/p1_sensitivity_freight_duty.png); [`p1_sensitivity_band.png`](../outputs/charts/p1_sensitivity_band.png) | DONE |
| 1.6 | Scrap reality check: moisture, contamination, yield | [`10_parity_model.md`](10_parity_model.md) §9; [`parity_quality_scenarios.csv`](../outputs/tables/parity_quality_scenarios.csv); [`scrap_grades.yaml`](../config/params/scrap_grades.yaml) | DONE |
| 1.7 | LME term structure: M+1 settlement basis, roll yield | [`10_parity_model.md`](10_parity_model.md) §10; [`term_structure_weekly.csv`](../outputs/tables/term_structure_weekly.csv); [`term_structure_roll_monthly.csv`](../outputs/tables/term_structure_roll_monthly.csv); [`p1_term_structure.png`](../outputs/charts/p1_term_structure.png); [`30_mtm_attribution.md`](30_mtm_attribution.md) §13.10; [`mcx_roll_carry.csv`](../outputs/tables/mcx_roll_carry.csv) | DONE, with a caveat |

## Table 4: Component 2, mock trading book

| Row | Element | Delivered by | Status |
|---|---|---|---|
| 2.1 | Quantity 1,000–5,000 MT per trade | [`trades.yaml`](../config/trades.yaml); [`trade_book.csv`](../outputs/tables/trade_book.csv); [`20_trade_book.md`](20_trade_book.md) §1 | DONE |
| 2.2 | Contract (SPA terms) | [`20_trade_book.md`](20_trade_book.md) §5 ticket cards (rows labelled 2.2); [`commercial.yaml`](../config/params/commercial.yaml) `rejection_penalty_schedule`, `radioactivity_clause` | DONE |
| 2.3 | Incoterms: FOB and CFR, freight booking and risk | [`20_trade_book.md`](20_trade_book.md) §5; [`trade_book.csv`](../outputs/tables/trade_book.csv) `incoterm`, `freight_booked_by`, `cargo_risk_passes`, `freight_risk_borne_by` | DONE |
| 2.4 | Pricing formula: fixed vs LME M+1 average | [`20_trade_book.md`](20_trade_book.md) §5; [`trade_book.csv`](../outputs/tables/trade_book.csv) `purchase_pricing_*`, `pricing_period_*`; [`10_parity_model.md`](10_parity_model.md) §10 | DONE |
| 2.5 | Counterparties with credit limits | [`counterparties.yaml`](../config/counterparties.yaml); [`20_trade_book.md`](20_trade_book.md) §2 | DONE |
| 2.6 | Payment terms: LC sight or usance, advance or credit | [`20_trade_book.md`](20_trade_book.md) §4–§5; [`trade_cashflows.csv`](../outputs/tables/trade_cashflows.csv) | DONE |
| 2.7 | Hedge stack: MCX, FX forwards, basis, freight layer | [`20_trade_book.md`](20_trade_book.md) §6.1–§6.4; [`trade_hedges.csv`](../outputs/tables/trade_hedges.csv) | DONE, with a caveat |
| 2.8 | Laycan, vessel, freight vs index | [`20_trade_book.md`](20_trade_book.md) §5, §6.5; [`trade_book.csv`](../outputs/tables/trade_book.csv) `laycan_*`, `vessels`, `freight_rate_usd_box`, `freight_index_usd_box_at_fixture` | PARTIAL |
| 2.9 | Trade discipline: parity window open + rationale | [`CONTRACTS.md`](../CONTRACTS.md) §5a; [`20_trade_book.md`](20_trade_book.md) §3; [`trade_eligibility_check.csv`](../outputs/tables/trade_eligibility_check.csv); `rationale` in [`trades.yaml`](../config/trades.yaml) | DONE |

## Table 5: Component 3, daily MTM and P&L attribution engine

| Row | Element | Delivered by | Status |
|---|---|---|---|
| 3.1 | Daily MTM per position | [`desk/mtm/`](../desk/mtm/); [`mtm_daily.csv`](../outputs/tables/mtm_daily.csv); [`30_mtm_attribution.md`](30_mtm_attribution.md) §2–§3, §7 | DONE |
| 3.2 | Attribution split (a)–(g) | [`30_mtm_attribution.md`](30_mtm_attribution.md) §4, §13.2; [`attribution_daily.csv`](../outputs/tables/attribution_daily.csv); [`attribution_leg_daily.csv`](../outputs/tables/attribution_leg_daily.csv); [`pnl_controls.csv`](../outputs/tables/pnl_controls.csv) | DONE |
| 3.3 | Equity curve + per-trade waterfalls | [`p3_equity_curve.png`](../outputs/charts/p3_equity_curve.png); [`p3_attribution_waterfall_book.png`](../outputs/charts/p3_attribution_waterfall_book.png) and `p3_attribution_waterfall_T01.png` … `_T09.png`; [`30_mtm_attribution.md`](30_mtm_attribution.md) §13.3–§13.4 | DONE |
| 3.4 | Adverse event #1: LME crash + MCX variation margin | [`31_adverse_events.md`](31_adverse_events.md) §1; [`adverse_event_1_lme_crash.csv`](../outputs/tables/adverse_event_1_lme_crash.csv); [`mcx_variation_margin.csv`](../outputs/tables/mcx_variation_margin.csv); [`p3_event1_hedged_vs_unhedged.png`](../outputs/charts/p3_event1_hedged_vs_unhedged.png); [`p3_mcx_vm_schedule.png`](../outputs/charts/p3_mcx_vm_schedule.png) | DONE |
| 3.5 | Adverse event #2: USD/INR depreciation + forward offset | [`31_adverse_events.md`](31_adverse_events.md) §2; [`adverse_event_2_usdinr.csv`](../outputs/tables/adverse_event_2_usdinr.csv); [`p3_event2_fx_offset.png`](../outputs/charts/p3_event2_fx_offset.png) | DONE |
| 3.6 | Adverse event #3: freight and buyer payment delay + credit mitigation | [`31_adverse_events.md`](31_adverse_events.md) §3; [`adverse_event_3_logistics_credit.csv`](../outputs/tables/adverse_event_3_logistics_credit.csv); [`adverse_event_3_freight_stress_hypothetical.csv`](../outputs/tables/adverse_event_3_freight_stress_hypothetical.csv); [`buyer_credit_exposure_by_trade_daily.csv`](../outputs/tables/buyer_credit_exposure_by_trade_daily.csv); [`p3_adverse_events.png`](../outputs/charts/p3_adverse_events.png) | DONE (freight fell in 2022; the spike is a labelled hypothetical, per CONTRACTS §7.6) |

## Table 6: Component 4, risk pack

| Row | Element | Delivered by | Status |
|---|---|---|---|
| 4.1 ★ | VaR with GARCH vs historical, backtest + Kupiec | [`40_var_garch.md`](40_var_garch.md) §0–§6 (§1 "Why GARCH"); [`var_daily.csv`](../outputs/tables/var_daily.csv); [`var_backtest_exceptions.csv`](../outputs/tables/var_backtest_exceptions.csv); [`kupiec.csv`](../outputs/tables/kupiec.csv); [`var_lead_lag.csv`](../outputs/tables/var_lead_lag.csv); [`p4_var_garch_vs_hist.png`](../outputs/charts/p4_var_garch_vs_hist.png); [`p4_var_vol_forecasts.png`](../outputs/charts/p4_var_vol_forecasts.png); [`p4_var_unit_backtest.png`](../outputs/charts/p4_var_unit_backtest.png); MCX beta sensitivity [`var_mcx_beta.csv`](../outputs/tables/var_mcx_beta.csv) (§4.3) | DONE (GARCH did not clearly lead; stated), with a caveat |
| 4.2 ★ | Monte Carlo, 10,000 paths + five stresses | [`41_monte_carlo.md`](41_monte_carlo.md) §0–§5; [`mc_summary.csv`](../outputs/tables/mc_summary.csv); [`mc_pnl_distribution.csv`](../outputs/tables/mc_pnl_distribution.csv); [`mc_stress_scenarios.csv`](../outputs/tables/mc_stress_scenarios.csv); [`p4_mc_distribution.png`](../outputs/charts/p4_mc_distribution.png); [`p4_mc_scenarios.png`](../outputs/charts/p4_mc_scenarios.png) | DONE, with a caveat |
| 4.3 ★ | Counterparty credit scoring (logistic) | [`50_credit_scoring.md`](50_credit_scoring.md) §1–§6; [`credit_scores.csv`](../outputs/tables/credit_scores.csv); [`credit_model_coefficients.csv`](../outputs/tables/credit_model_coefficients.csv); [`credit_synthetic_training_data.csv`](../outputs/tables/credit_synthetic_training_data.csv); [`risk_credit.yaml`](../config/params/risk_credit.yaml); [`p5_credit_scores.png`](../outputs/charts/p5_credit_scores.png); [`p5_credit_model_fit.png`](../outputs/charts/p5_credit_model_fit.png) | DONE, with a caveat |
| 4.4 | Credit tracker: exposure vs limits, breach flags, scores | [`50_credit_scoring.md`](50_credit_scoring.md) §7; [`credit_tracker.csv`](../outputs/tables/credit_tracker.csv); [`credit_tracker_bookings.csv`](../outputs/tables/credit_tracker_bookings.csv); [`p5_credit_tracker.png`](../outputs/charts/p5_credit_tracker.png) | DONE |
| 4.5 | Margin and liquidity through the crash fortnight | [`51_margin_liquidity.md`](51_margin_liquidity.md) §0–§3; [`margin_liquidity.csv`](../outputs/tables/margin_liquidity.csv); [`margin_liquidity_fortnight.csv`](../outputs/tables/margin_liquidity_fortnight.csv); [`margin_liquidity_summary.csv`](../outputs/tables/margin_liquidity_summary.csv); [`p5_liquidity_margin.png`](../outputs/charts/p5_liquidity_margin.png); [`p5_liquidity_fortnight.png`](../outputs/charts/p5_liquidity_fortnight.png); [`margin_liquidity_limit_grid.csv`](../outputs/tables/margin_liquidity_limit_grid.csv) | DONE, with a caveat |
| 4.6 | Risk policy memo (one page) | [`risk_policy_memo.md`](../outputs/reports/risk_policy_memo.md) and [`.pdf`](../outputs/reports/risk_policy_memo.pdf); [`51_margin_liquidity.md`](51_margin_liquidity.md) §7; [`margin_liquidity_policy_limits.csv`](../outputs/tables/margin_liquidity_policy_limits.csv) | DONE, with a caveat |

## Table 7: Component 5, desk reporting pack

| Row | Element | Delivered by | Status |
|---|---|---|---|
| 5.1 | Six weekly desk notes | [`desk/reporting/desk_notes.py`](../desk/reporting/desk_notes.py) → `outputs/reports/desk_note_<n>_<week_end>.{md,pdf}` in [`outputs/reports/`](../outputs/reports/) (weeks: the last Friday of each window month); [`tests/test_desk_notes.py`](../tests/test_desk_notes.py); run by [`run_reports.py`](../desk/reporting/run_reports.py); reviewed in [`reviews/phase4-7_review_log.md`](reviews/phase4-7_review_log.md) | DONE, with a caveat |
| 5.2 ☆ | Sentiment overlay | [`70_sentiment_overlay.md`](70_sentiment_overlay.md) (§5 feeds the desk notes); [`desk/sentiment/run.py`](../desk/sentiment/run.py); [`headlines_weekly.csv`](../data/processed/headlines_weekly.csv); [`sentiment_weekly.csv`](../outputs/tables/sentiment_weekly.csv); [`sentiment_leadlag.csv`](../outputs/tables/sentiment_leadlag.csv); [`p7_sentiment_vs_lme.png`](../outputs/charts/p7_sentiment_vs_lme.png); [`p7_sentiment_leadlag.png`](../outputs/charts/p7_sentiment_leadlag.png) | DONE, with a caveat |
| 5.3 | Deal post-mortem (two pages, best trade) | [`post_mortem.md`](../outputs/reports/post_mortem.md) and [`.pdf`](../outputs/reports/post_mortem.pdf); [`desk/reporting/post_mortem.py`](../desk/reporting/post_mortem.py); [`p6_post_mortem_waterfall.png`](../outputs/charts/p6_post_mortem_waterfall.png); [`p6_post_mortem_timeline.png`](../outputs/charts/p6_post_mortem_timeline.png) | DONE |
| 5.4 | README: folder structure, pipeline, re-run, verification, "Why these quant methods" | [`README.md`](../README.md) (all sections; numbers generated by [`run_reports.py`](../desk/reporting/run_reports.py)) | DONE |

## Table 8: Quality bar and definition of done

| Row | Requirement | Delivered by | Status |
|---|---|---|---|
| 8.1 | Numbers consistent and traceable to DIRECT, PROXY or ASSUMPTION sources | [`config/params/`](../config/params/); [`00_assumptions_log.md`](00_assumptions_log.md); [`00_data_dictionary.md`](00_data_dictionary.md); [`series_provenance.csv`](../data/processed/series_provenance.csv); [`pnl_controls.csv`](../outputs/tables/pnl_controls.csv); [`reviews/phase1-3_fix_log.md`](reviews/phase1-3_fix_log.md); [`reviews/phase4-7_review_log.md`](reviews/phase4-7_review_log.md) | DONE, with a caveat |
| 8.2 | Commented Python; formula-driven Excel for Components 1–3 | [`desk/`](../desk/); [`Metals_Desk_Master.xlsx`](../outputs/excel/Metals_Desk_Master.xlsx); [`35_excel_workbook.md`](35_excel_workbook.md) §4, §7; [`reconciliation.json`](../outputs/excel/reconciliation.json); [`test_excel_reconciliation.py`](../tests/test_excel_reconciliation.py) | DONE |
| 8.3 | Units consistent, never mixed silently | [`desk/units.py`](../desk/units.py); [`CONTRACTS.md`](../CONTRACTS.md) §1.3; [`00_data_dictionary.md`](00_data_dictionary.md) | DONE |
| 8.4 | Volatile parameters verified + verification log | [`verification_log.md`](verification_log.md) §A–§D | PARTIAL |
| 8.5 | Plain-English "What this does and doesn't tell you" for every quant model | [`10_parity_model.md`](10_parity_model.md) §13; [`20_trade_book.md`](20_trade_book.md) §10; [`30_mtm_attribution.md`](30_mtm_attribution.md) §10; [`31_adverse_events.md`](31_adverse_events.md) §6; [`35_excel_workbook.md`](35_excel_workbook.md) §2; [`40_var_garch.md`](40_var_garch.md) §8; [`41_monte_carlo.md`](41_monte_carlo.md) §8; [`50_credit_scoring.md`](50_credit_scoring.md) §1; [`51_margin_liquidity.md`](51_margin_liquidity.md) §8; [`70_sentiment_overlay.md`](70_sentiment_overlay.md) §7; closing paragraphs of [`post_mortem.md`](../outputs/reports/post_mortem.md) and [`interview_pack.md`](../outputs/reports/interview_pack.md) | DONE |
| 8.6 | The 17 toughest interview questions, including the two named ones | [`interview_pack.md`](../outputs/reports/interview_pack.md) and [`.pdf`](../outputs/reports/interview_pack.pdf); [`desk/reporting/interview_pack.py`](../desk/reporting/interview_pack.py); [`test_reports_runner.py`](../tests/test_reports_runner.py) | DONE |
