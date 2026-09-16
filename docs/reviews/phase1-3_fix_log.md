# Phase 1–3 review: fix log and final check

The source is `docs/reviews/phase1-3_review_findings.json`: 39 findings, 21 of them critical or major. The fixes
landed in `ab39f98` and `24bad20`. Pre-fix state `503c93d`, checked state `aa9eadd` plus the small doc corrections
listed at the end. Status was checked against code, config, docs and `outputs/tables/*.csv`. The pipeline, the
tests and the Excel recalculation were not re-run for this check; they had already passed.

Status key: **RESOLVED** means the problem is gone, or the right fix was disclosure and the disclosure is prominent
and accurate. **PARTIAL** means part of the fix is in. **UNRESOLVED** means the finding still stands.

**Totals:** 31 RESOLVED, 4 PARTIAL, 4 UNRESOLVED, 0 NOT-REAL.
**Critical and major (21):** 19 RESOLVED, 2 PARTIAL (#13, #20).
**Minor (18):** 12 RESOLVED, 2 PARTIAL, 4 UNRESOLVED.

## 1. Findings

| # | Lens | Sev | Short issue | Status | Evidence / what changed |
|---|---|---|---|---|---|
| 1 | trader | critical | Sale prices anchored on hindsight lag-2 grade mix; sensitivity blind to it | RESOLVED | `desk/mtm/sensitivity.py` re-prices both legs. In `pnl_sensitivity_summary.csv` the PIT mix gives 9.73 cr, lag-1 18.70, lag-3 22.00, diff q25/q75 23.12/13.38, against base 19.21. Stated in the docs/30 header, §10 and §13.9. |
| 2 | trader | critical | MCX proxy in permanent contango, so 13/13 rolls are gains | RESOLVED (disclosure + reference curve) | `mcx_roll_carry.csv`: 13/13 gains, +₹8,421,697, all INR carry, metal component 0 (control `roll_carry_metal_component_max_abs`). Re-priced on an LME-curve reference: +₹7,332,004. The one roll dealt in backwardation (T07, 20-Jul) has metal carry −₹327,394. Covered in docs/30 §13.10, and every rolling ticket note names the artefact. The curve itself is still contango (open item). |
| 3 | trader | critical | Mirror basis sensitivity shown as upside | RESOLVED | `mcx_basis_risk.csv`: per-ticket −₹19,206,374 … +₹19,173,462; adverse image −₹18,402,493; (b)+(g) jointly ±₹18,949,834. See docs/30 §13.6 and §13.11, docs/31 §5. |
| 4 | trader | major | Bucket (f) net positive: events "made money" | RESOLVED | Lifetime (f) is now −₹5,246,478 (T07 −0.16 cr, T08 −0.37 cr). docs/30 §4.1 says the buyer passthrough lands in (0) and that the lifetime event cost is −₹9.35 m (`event_cost_lifetime_inr`). |
| 5 | trader | major | T08 radiation rejection costless | RESOLVED | T08 in `trade_cashflows.csv`: DEMURRAGE:L2 −USD 20,475, REJECTED_BOX_COST −USD 5,730 (45-day hold + USD 3,000 re-export), QUALITY_CLAIM −USD 17,252 (unaccepted 40 % handed back). Recovery 0.0 → 18.63 cr, 1.0 → 19.59 cr. Decontamination is disclosed as not modelled. |
| 6 | trader | major | CFR "risk with seller until discharge" | RESOLVED | `desk/book/run.py:160-163` splits the field into `cargo_risk_passes` ("on board at the load port") and `freight_risk_borne_by` ("SELLER (inside the CFR price)"). All nine cards re-rendered. |
| 7 | trader | major | Wrong market facts in T01/T06/T03 rationales | RESOLVED | T01: "down on the week and five dollars under late January" (108.68→106.41; 21-Jan 111.22). T06: "almost a rupee weaker than three sessions ago" (76.29→77.26). T03: 306 dollars (3M). New validator rule P13 reconciles quoted numbers and "N running" streaks. |
| 8 | trader | major | Compound `buyer_id` blocks per-counterparty credit | RESOLVED | New `buyer_credit_exposure_by_trade_daily.csv` at (date, trade, buyer) grain; it ties to `buyer_credit_exposure_daily.csv` receivables to ₹0.00. The 93 %/88 % notes in `counterparties.yaml` are now labelled as the P04 booking-time measure. The compound id stays in `book_exposures_daily.csv`, flagged in docs/30 §7. |
| 9 | trader | major | T05-FX-3 speculative USD long, cancelled at mid | RESOLVED | Now SELL_USD 90,000, booked 2022-07-01 after the quotational period (QP) closed (`trade_hedges.csv`). The book has no cancellations; the unwind-spread asymmetry is disclosed in docs/31 §2.2. |
| 10 | trader | major | Detention flat, conflated with demurrage | RESOLVED | Slabs 35/70/105 USD per box-day (5 d / 5 d) in `logistics.yaml`. T07 L2 costs USD 17,325 and T08 L2 USD 20,475 (flat would be USD 11,550 less). Carrier detention and CFS ground rent share one tariff, disclosed as a floor in docs/31 §3.2 and docs/30 §10. |
| 11 | trader | major | T06 MSMED statute inverted | RESOLVED | T06 comment (`trades.yaml:997`) and docs/20 rule C1 now say s.15 protects a registered supplier and that the 45 days is a desk policy cap. |
| 12 | trader | major | Only losing discretionary calls confessed | RESOLVED | docs/20 §6.6 "What went right that the desk did not choose": T01 deferral +₹1,296,150, waiting on fixtures USD 15,066, stop counterfactual −USD 72,534, QP-slip range, grade path. |
| 13 | trader | major | Zero operational slippage; T08 has 1 day of laycan slack | **PARTIAL** | docs/20 §6.5 sizes a one-month QP slip (T02 +₹7.8 m, T05 +₹9.4 m, T08 −₹1.5 m; T08 slack 1 d), and T08's note states the risk. T08 gains +7 d void-call arrival delays. No lot actually slips its laycan and no booking is rolled; every other B/L is still laycan start + 2 d. |
| 19 | controller | critical | Headline not sign-robust to `domestic_anchor_premium_inr_t`; no rupee sensitivity | RESOLVED (disclosed; the risk stands) | `pnl_sensitivity_sign_robustness.csv`: −₹105.4 m … +₹334.3 m, break-even −38,702 ₹/t inside the band, `sign_robust_within_band = False`. Stated in the docs/30 header, §10 and §13.9, and in docs/20 §12. |
| 20 | controller | major | MCX unit beta untested; mirror moves no risk number | **PARTIAL** | Tested and disclosed: mirror beta 0.452 (SE 0.063, t vs 1 = −8.67, R² 0.29; `mcx_basis_risk.csv`). docs/30 §10 says mirror deltas equal the base deltas and warns against FX VaR on netted `fx_delta_usd`. Missing: an MCX beta shock in `valuation.SHOCK_KEYS` and a beta ≠ 1 exposure variant. docs/30 lists this as a Phase 4 open item. |
| 21 | controller | major | `new_deal` labelled "at inception" | RESOLVED | `style.py:50` now reads "(0) Deal margin at contract dates". `new_deal_timing.csv`: ₹94,324,860 on trade dates, ₹70,916,742 later. See docs/30 §13.2. |
| 29 | spec-honesty | major | `trade_cashflows.csv` never written | RESOLVED | `desk/mtm/run.py:203` `write(cf, name)`. File has 1,411 rows, `written_by = P3`, mtime equal to `mtm_daily.csv`. |
| 30 | spec-honesty | major | docs/31 §1.4 IM column is single-line, not book | RESOLVED | Two columns now. Book peak IM 78.6/95.8/63.7/67.7/64.6/41.8 and single-line 30.4/28.7/29.8/29.9/28.6/24.8 both match `mcx_variation_margin.csv`. |
| 31 | spec-honesty | major | docs/31 §3.5 "reaches zero by 18-Mar" false | RESOLVED | Three spells, last non-zero day 2022-05-26. T01 −8,551,738, T04 −3,703,140, T07 −5,437,666 all match the CSV. |
| 32 | spec-honesty | major | "Phases agree at 83.4 %" conflates two measures | RESOLVED | docs/20 §2 column is "Peak use at booking (P04)" with an explainer; the §11 "agree" claim is withdrawn. docs/31 §3.4 and docs/30 §13.8 give both measures with their denominators. |
| 33 | spec-honesty | major | docs/20 header says decision inputs are real | RESOLVED | Header now lists the LME path, duties, MCX specs and dated news as real. Grade factors and freight are called hindsight reconstructions; USD/INR and MCX are called proxies. |
| 14 | trader | minor | 40ft payload 21.0 MT for all grades; FEU economics | PARTIAL | docs/20 "Box weights" explains the 21.0 MT US road weight limit. Grade-specific 40ft payloads and the FEU-vs-TEU per-tonne freight rationale are not added. |
| 15 | trader | minor | JEA lane is a fixed multiple of USEC | UNRESOLVED | JEA/USEC = 0.22546–0.22560 in every week (`freight_weekly.csv`). `docs/00_data_dictionary.md` implies it ("x USEC_MUN weekly shape") but never states the fixed ratio. |
| 16 | trader | minor | Flat ₹0.10 bank margin, no cancellation spread | UNRESOLVED | `bank_margin_inr` = 0.1 on all 25 forwards. No tenor or size table. The book has no cancellations, so the unwind leg does not matter here. |
| 17 | trader | minor | T09 sale on a local LME high with no trigger | UNRESOLVED | T09/S1 still `contract_date: 2022-08-26`. Its terms note gives price arithmetic only, no dated operational trigger. |
| 18 | trader | minor | Limit-lock asserted as fact from proxy | RESOLVED | T01 rationale: "bid only at the limit, if at all". docs/20 §6.1 and docs/30 §10 use conditional, proxy-labelled wording. |
| 22 | controller | minor | VM table does not tie by hand; unsigned `contract_value_inr` | UNRESOLVED (defended) | No model-price column. `contract_value_inr` min is +₹95.2 m while `lots` min is −279. docs/30 §11.6 defends pricing at `theo + basis`. |
| 23 | controller | minor | FX hedge ratio blanked as artefact when some readings are economics | RESOLVED | docs/30 §13.8 calls large-denominator negative ratios a D5 hedge-design finding (2022-03-14 example) and says how to read forwards against the payable. No second column added. |
| 24 | controller | minor | FUNDING accrual shown as "realised, settled" | RESOLVED (disclosure) | docs/30 §7 names the trap and §11.7 lists the CONTRACTS §7.3 amendment. Rows still carry `status = settled`. (This pass corrected the doc's `settle_date` description: it equals each row's own date.) |
| 25 | controller | minor | `attribution_daily.csv` BOOK rows with no `scope` column | RESOLVED (disclosure) | docs/30 §7 outputs table: "Filter `trade_id != "BOOK"` … double-counts". No column added, because CONTRACTS §7a.3 fixes the columns. |
| 26 | controller | minor | Headline replacement control at ₹0.50, not ₹0.01 | RESOLVED | docs/30 §13.7 lists the `_panelfx` row (1.16e-10 against ₹0.01) as the §7a.1.3 control and the CIP row (0.228 against ₹0.50) as a memo. §11.7 amendment. |
| 27 | controller | minor | Empty `label` column; days past due (DPD) 25 vs ticketed 26 | PARTIAL | DPD is documented (docs/31 §3.4, "25 at the last overdue close"), and `max_ticketed_payment_delay_days = 26` is published. `label` is still all-NaN float64 on 1,411 rows. |
| 28 | controller | minor | No `residual` column at leg grain | RESOLVED (disclosure) | docs/30 §7: the residual is a trade-grain control, and the 483 trade-days with no leg rows all have zero P&L. |
| 34 | spec-honesty | minor | §13.6 PIT table missing (f); "₹140 m between (0) and (c)" | RESOLVED | §13.6 now has the (f) row (+0.03) and the corrected prose. The same wrong phrase was still in the §10 bullet; **fixed in this pass**. |
| 35 | spec-honesty | minor | "Monotonically" falling freight | RESOLVED | docs/20 §6.4: "only 4 small up-weeks". "Monotonic" no longer appears in any doc. |
| 36 | spec-honesty | minor | docs/31 §2.2 FX settlement sentence wrong | RESOLVED | Range now matches `mtm_daily.csv` (T01 −₹0.41 m, T05 +₹6.54 m, T02 +₹6.40 m; total +₹19,557,673) and both SELL_USD lines are named. The T01 lines were still described as "struck on 08-Mar and 18-Mar", out of date since the forwards moved to B/L dates (03-18, 03-29, 04-04, 04-07); **fixed in this pass**. |
| 37 | spec-honesty | minor | T03 "180 dollars", T09 "130 dollars" | RESOLVED | Now 306 (3M) and 82. P13 enforces them. |
| 38 | spec-honesty | minor | T07 card "2; 8" rendering | RESOLVED | docs/20 T07 card reads "Chargeable dwell L1 2 d, L2 8 d beyond 14 free days ⇒ USD 20,475". |
| 39 | spec-honesty | minor | docs/10 never points to the Excel half | RESOLVED | docs/10 §2 and docs/30 §7 point to `outputs/excel/Metals_Desk_Master.xlsx` and `reconciliation.json`. |

## 2. Spot-check: numbers in the docs against the CSVs

| # | Doc / section | Claim | CSV value | Result |
|---|---|---|---|---|
| 1 | docs/30 §13.1 | Book P&L at HORIZON_END ₹192,054,771 | `attribution_daily.csv` BOOK cum 192,054,770.66 | ✓ |
| 2 | docs/30 §13.1 | Book P&L at WINDOW_END ₹195,936,980 | 195,936,979.57 | ✓ |
| 3 | docs/30 §13.3 | T08 final −₹1.17 cr; T02 +₹5.05 cr | −11,726,590; +50,546,931 | ✓ |
| 4 | docs/30 §13.4 | Peak +22.49 cr on 2022-06-09; max drawdown −4.99 cr to 2022-08-08 | 224,878,677 on 06-09; −49,872,922 at 08-08 | ✓ |
| 5 | docs/30 §13.9 | Anchor −55,000 gives −10.54 cr; break-even −38,702 ₹/t | −105,380,800; −38,702.30 | ✓ |
| 6 | docs/30 §13.10 / §10 | Rolls +₹8,421,697; backwardation roll metal carry −₹327,394; §10 said "₹0.33 crore" | `mcx_roll_carry.csv` 8,421,696.91; −327,394.49 | ✓ §13.10; **§10 wrong by 10×, fixed to ₹0.03 crore** |
| 7 | docs/30 §13.2 | `new_deal` ₹94.3 m on trade dates / ₹70.9 m later | `new_deal_timing.csv` 94,324,860 / 70,916,742 | ✓ |
| 8 | docs/30 §10 | Book `fx_delta_usd` mean −USD 0.42 m; physical + forwards +USD 4.19 m (max 13.3 m); MCX −4.61 m | −420,681; 4,186,929 (max 13,297,718); −4,607,610 | ✓ |
| 9 | docs/31 §1.4 | Max book IM ₹95,803,038 on 2022-04-21; peak outflow −₹105,707,065 on 2022-03-24; lifetime VM +₹172.4 m | Same values (`mcx_variation_margin.csv`) | ✓ |
| 10 | docs/31 §3.5 | Freight stress last non-zero 2022-05-26; T01 −₹8,551,738 | Same | ✓ |
| 11 | docs/31 §3.4 | Peak receivable utilisation 83.4 % (BUY_JNPT_01); RJK peak ₹89,239,103 = 74.4 % | 0.8341 on 2022-04-29; RJK 0.7437 | ✓ |
| 12 | docs/31 §0 | E1 window P&L +₹210.5 m, hedge benefit +₹197.1 m; E3 lifetime event cost −₹9.35 m | 210,503,943; 197,116,062; −9,352,773 | ✓ |
| 13 | docs/20 §2 | P04 peaks 93/88/78 %; P14 advances 1.26x/1.53x/1.83x of ₹120 m | `trade_credit_exposure.csv` 0.926/0.885/0.783; 151.62/183.80/219.29 m | ✓ |
| 14 | docs/10 §6 | 82 of 162 in-window cases eligible (111 base open); zorba USEC max ₹49,904 on 04-Mar | `parity_weekly.csv` 82/162/111; 49,903.86 on 2022-03-04 | ✓ |
| 15 | docs/35 §7 | 132,447 cells recalculated, 3,998 checks, 0 failures | `reconciliation.json` | ✓ |

Other doc corrections made in this pass (hand-written docs only; docs/10, /20 and /35 are generated and were not
touched):

- **docs/31 §5:** "±₹1.9 crore on ₹2–5 crore of trade P&L" now reads "against −₹1.2 to +₹6.4 crore of per-ticket
  P&L" (per-ticket range −11.73 m to +64.28 m).
- **docs/30 §5.1:** the API signature now includes the `cache` and `funding` parameters. It also says the return
  value excludes funding.

## 3. Open items carried into Phases 4–5

1. **Advance-reliance performance exposure (P14, deliberate, not cleared).** BUY_RJK_01 (limit ₹120 m) is relied on
   for three advances:
   - T01-S2: ₹151.62 m, 1.26x, due 2022-05-24
   - T04-S1: ₹183.80 m, 1.53x, due 2022-06-14
   - T07-S1: ₹219.29 m, 1.83x, due 2022-08-12

   Contracted-incl-presettlement utilisation peaks at 2.57x (RJK) and 1.15x (MUN), against a receivable peak of
   83.4 %. Phase 5 credit scoring must score advance failure (cargo unsold, hedge lifted) as well as receivable
   default.
2. **The headline P&L is not sign-robust** to `domestic_anchor_premium_inr_t`: −₹105.4 m … +₹334.3 m, break-even
   −38,702 ₹/t inside the band (PENDING verification). No joint cases are published (for example a low premium
   together with the PIT grade mix); the Phase 4 Monte Carlo is the natural place for them.
3. **MCX unit beta (#20, PARTIAL).** No MCX beta shock in `SHOCK_KEYS` and no beta ≠ 1 exposure variant; the mirror
   beta is 0.452. Phase 4 must not build FX or LME VaR on netted deltas alone: use `fx_delta_physical_usd +
   fx_delta_forwards_usd` and `fx_delta_mcx_usd` separately, and treat the MCX offset as an assumption.
4. **The MCX proxy has no curve risk.** It is in contango by construction, so there is no calendar-spread or
   backwardation roll cost (#2). `book_exposures_daily_mcx_mirror.csv` deltas equal the base deltas, so it is not a
   risk sensitivity.
5. **Freight is one factor.** JEA_NSA = 0.2255 × USEC_MUN every week (#15). The Monte Carlo should model freight as
   a single factor and say so.
6. **Schedule / QP-slip risk is not simulated (#13, PARTIAL).** A one-month slip swings −₹1.5 m to +₹9.4 m per lot,
   and T08 had one day of slack. This is a candidate Phase 4 stress.
7. **Liquidity is unconstrained.** Book cash bottoms at −₹1,159.9 m on 2022-07-20, with ₹95.8 m of peak IM on top.
   The first-fortnight margin outflow is −₹105.7 m. No facility is modelled; Phase 5 owns `risk.yaml`.
8. **Traps for anyone reading the files.**
   - `attribution_daily.csv` has no `scope` column: filter `trade_id != "BOOK"`.
   - `book_exposures_daily.csv` has a compound `buyer_id` on T01: use `buyer_credit_exposure_by_trade_daily.csv`.
   - The FUNDING leg's accrual sits in `realised_cum_inr`.
   - `revalue_book` excludes funding: pass `funding=`.
   - `hedge_ratio_fx_frac` is blank on 14 days and runs −14.3 … +49.5 otherwise.
   - `trade_cashflows.csv` has `scenario ∈ {PLANNED_AT_TRADE_DATE, REALISED}`: filter to REALISED for realised cash.
9. **Minor data hygiene (UNRESOLVED/PARTIAL, not blocking).**
   - #16 flat bank margin
   - #22 VM model-price column and unsigned `contract_value_inr`
   - #27 empty `label` column
   - #17 T09 sale trigger
   - #14 40ft payload / FEU rationale

   Any docs/20 wording fix must go through `desk/book/run.py` (the doc is generated).
