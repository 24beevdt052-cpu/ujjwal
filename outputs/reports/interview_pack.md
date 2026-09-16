# Interview pack — the 17 toughest questions a physical metal trader would ask

**Meridian Non-Ferrous Trading Pvt Ltd (SIM) — Aluminium Scrap Desk, Mumbai** · aluminium scrap into India, 1-Mar-2022 to 31-Aug-2022; 9 tickets, 14,350 MT in 656 containers.

> **ACADEMIC SIMULATION — not actual trades.** Counterparties, vessels, trades and events are simulated. LME prices are DIRECT (LME official prices via Westmetall); USD/INR and MCX are PROXY; freight levels and the grade-factor path are hindsight reconstructions. Every parameter carries a DIRECT, PROXY or ASSUMPTION flag in `config/params/`.

> **Where the questions come from.** The spec's quality bar (Table 8) asks for "the original 15" plus two named questions, but never lists the 15. Questions 1 to 15 were therefore written for this pack, one per area a physical desk head would probe. Questions 16 and 17 are the spec's, verbatim.

> **The headline, always with its band.** The book made **₹192.1 m** to 31-Oct-2022 (₹13,384/MT; ₹195.9 m at 31-Aug-2022). It is **not sign-robust**: across the registered `domestic_anchor_premium_inr_t` grid it runs **−₹105.4 m to +₹334.3 m**, break-even −38,702 ₹/MT inside the grid. Every answer that quotes the book's P&L quotes this band.

> **How to read the numbers.** Every number below is filled from the published tables by `desk/reporting/interview_pack.py` when the pack is built; none is typed by hand. The qualitative claims ("the only negative", "worse than every path") are re-tested against the data first, and the build fails if one no longer holds. Sources follow each answer.

## 1. Walk me through the landed cost on your first trade. Where is the duty wedge, and why did you trust the arb?

*Import parity, landed cost and the duty wedge.*

T01 is Zorba 95/5 on US East Coast → Mundra, parity week to 4-Mar. CFR is USD 2,709/t (LME 3M USD 3,820/t × grade factor 0.709); at ₹76.57/USD that is ₹207,631/MT of goods. BCD at 2.5 % plus SWS adds ₹5,716, port ₹2,650, finance ₹4,504; IGST is only financed, because I take it back as input credit. Landed: ₹220,501/MT. The wedge sits on the selling side: my anchor is MCX, which trades at *primary* import parity with 7.5 % BCD (HS 7601), while scrap pays 2.5 % (HS 7602) — about ₹16,170/t of metal that week. After recovery 86.5 %, by-product and conversion, the net arb was ₹49,904/MT against a ₹5,000 hurdle. I traded only where three screens agreed — base, the point-in-time grade mix (₹14,650) and conversion stressed (₹44,711) — a rule declared before any result: 82 of 162 in-window cases passed, against 111 open on base alone.

*Sources:* `outputs/tables/parity_weekly.csv`, `config/params/regulatory.yaml`, `docs/10_parity_model.md`

## 2. Scrap is not LME. How did you price grade and recovery, and how much of your P&L is really grade spread?

*Grade spreads and recovery.*

Grade is a CFR-India factor on LME 3M — 0.699 for Zorba 95/5 on T01's trade date — and my formula tickets buy at 0.638–0.782 × the cash average. Recovery to ingot is (1 − moisture) × (1 − contamination) × yield: 86.5 % Zorba, 89.7 % Taint/Tabor, 91.7 % Tense; a point of recovery is worth about ₹3,111/MT at T01's anchor. Grade spread is +₹103.3 m of lifetime P&L, second only to deal margin, and I would not sell it as skill: the grade path behind it uses DGCIS unit values published months later. Re-priced on the point-in-time mix a 2022 desk could see, the book falls from ₹192.1 m to ₹97.3 m and grade spread turns −₹36.8 m; the lag-1 and lag-3 mixes give ₹187.0 m and ₹220.0 m. The headline band on the anchor premium is −₹105.4 m to +₹334.3 m. T08 is the only ticket with a negative grade spread (−₹10.9 m).

*Sources:* `outputs/tables/attribution_daily.csv`, `outputs/tables/pnl_sensitivity_summary.csv`, `config/params/scrap_grades.yaml`, `docs/30_mtm_attribution.md`

## 3. FOB or CFR — who carries the freight risk on your tickets, and what did freight do to you?

*Incoterms and freight risk.*

3 of 9 tickets are FOB (T01, T04 and T07): I book the boxes, so the freight is my risk until the fixture is paid. The other 6 are CFR — the seller's freight sits inside the price. Cargo risk passes on board at the load port either way. There is no liquid India-inbound container swap, so every FOB ticket runs freight unhedged against a stated stop-loss per box (USD 2,170–2,570 a box). Freight fell 34.3 % on the US lane and 34.2 % on the Gulf lane across the window; fixing ahead of the B/L cost ₹2.5 m over the tickets' lives, and bucket (d) ended at +₹1.2 m. Two caveats I state up front: lane levels are hindsight-calibrated reconstructions, and the Gulf lane is 0.226 × the US lane every week, so freight is really one factor. The +40 % spike is a hypothetical stress: −₹8.6 m on 8-Mar, with only T01 on the book.

*Sources:* `outputs/tables/trade_book.csv`, `outputs/tables/adverse_events_summary.csv`, `outputs/tables/mc_stress_scenarios.csv`, `data/processed/freight_weekly.csv`, `docs/31_adverse_events.md`

## 4. How did you pay your suppliers — sight or usance LCs — and did you actually have the bank lines for this book?

*LC, usance and funding.*

6 tickets on sight LCs, 3 on usance (60–90 days). Usance pays when the buyer settles inside the tenor: on 2 of the 3 the sale was due before the usance matured. On lines, the honest answer is no. I sized a ₹1,000 m working-capital line and a ₹1,000 m LC line ex ante on the February plan's average balance, not from the book. Funding need peaked at ₹1,179.0 m on 20-Jul: 30 days into the ₹150 m cash buffer, 19 over the line, which one more ₹25 crore step (₹1,250 m) would have held. LCs outstanding, counted at face plus tolerance, reached ₹1,414.8 m, over the line for 17 days. The book needed ₹1,387 m and ₹1,415 m to avoid any breach, and paid ₹32.6 m of interest to the horizon. The fix is sequencing, not a bigger bank: fewer purchases ahead of sale advances, and usance matched to buyer credit.

*Sources:* `outputs/tables/trade_book.csv`, `outputs/tables/margin_liquidity_summary.csv`, `outputs/tables/margin_liquidity_limit_grid.csv`, `docs/51_margin_liquidity.md`

## 5. Your formula purchases settle on the LME cash average of the month after shipment. What does the Cash–3M structure do to you?

*M+1 pricing and the Cash–3M structure.*

3 tickets (T02, T05 and T08) buy at a factor × the LME *cash* average of M+1, so they settle against cash, while parity is struck on 3M. The structure is a basis between the two: in contango the M+1 cash average sits below 3M and I gain as a buyer; in backwardation I pay. In the window Cash–3M ran −37.5 to +31.0 USD/t, contango in 19 of 27 weeks — worth at most USD 21.0/t against a T01 arb of USD 654/t. Rolls tell me nothing here: my MCX proxy curve is in contango by construction, so all 13 short rolls gained +₹8.42 m of rupee carry, not term structure; on a curve with the LME's own slope they make +₹7.33 m. Bucket (g), −₹56.6 m, is not structure either: −₹32.0 m of it is funding and −₹19.1 m sits on the MCX legs, cross-terms included.

*Sources:* `outputs/tables/term_structure_weekly.csv`, `outputs/tables/mcx_roll_carry.csv`, `outputs/tables/attribution_leg_daily.csv`, `docs/30_mtm_attribution.md`

## 6. You hedge LME-priced scrap with MCX futures. What is your basis risk, and did you measure it?

*MCX hedging and cross-exchange basis.*

My MCX series is a PROXY at duty-paid import parity, so it has unit beta to LME × USD/INR by construction and bucket (b) is zero every day, which flatters the hedge. Against a third-party mirror the beta is 0.45 on daily changes (t −8.7), but MCX closes hours after the LME fix, which biases a daily beta down: on weekly closes it is 0.75 (t −4.9), and 0.94 once closes are matched. So a unit-beta short leaves about 25 % of a parity move open, not 55 %. A Monte Carlo basis factor lifts the 99 % 10-day VaR from ₹23.0 m to ₹32.8 m on 21-Apr and from ₹1.00 m to ₹14.6 m on 27-Jul. Mean daily GARCH VaR is ₹4.27 m on the proxy, ₹8.5 m at the weekly beta and ₹17.3 m at the daily one, which nobody would hedge on. I would hedge on the weekly beta and carry basis as a risk factor.

*Sources:* `outputs/tables/mcx_basis_risk.csv`, `outputs/tables/var_mcx_beta.csv`, `outputs/tables/mc_summary.csv`, `outputs/tables/var_summary.csv`, `docs/40_var_garch.md`, `docs/41_monte_carlo.md`

## 7. What hedge ratio did you run, how did you roll, and did the hedge work in the crash?

*Hedge ratios and rolls.*

Target 0.90 of LME-equivalent metal on 6 tickets, 1.00 on T02 and T05, and 0.50 on T04 — outside my own 0.80–1.10 policy band, and I say so. Rolls go 7 trading days before expiry: 13 rolls, none late. The test was the fall from the 7-Mar high to the 15-Jul trough, LME cash −41.8 %: physical cargo lost ₹263.5 m on flat price, the MCX legs made ₹218.7 m — 83 % offset — and against an unhedged book the hedges were worth ₹197.1 m. Where it failed: net unhedged metal broke my 1,000 MT limit on 5 clean days, and the physical-to-hedge timing on averaging sales left net positions I had not chosen. And the hedge is only as good as unit beta; the third-party MCX mirror says 0.75 on weekly closes.

*Sources:* `outputs/tables/trade_book.csv`, `outputs/tables/adverse_events_summary.csv`, `outputs/tables/margin_liquidity_policy_limits.csv`, `docs/31_adverse_events.md`

## 8. How did you hedge USD/INR, and what did the rupee's slide do to the book?

*USD/INR forwards.*

The payable is in dollars, so I buy dollars forward against it: 25 forward lines, full cover as policy except T06 at 60 %, below my 90 % minimum. The rupee went from ₹75.33 to ₹80.04 a dollar (+6.2 %) between 5-Apr and 14-Jul. Over that stretch the forwards made +₹26.3 m, against −₹25.2 m on the dollar payables — 104 % cover — while the MCX legs lost ₹30.8 m, because a rupee contract priced at import parity is itself a dollar position. The lifetime FX bucket is +₹14.1 m. So I read FX risk on physical plus forwards (₹2.34 m mean daily GARCH VaR) and the MCX leg (₹2.61 m) separately; netted, it shows ₹1.17 m, which hides two offsetting positions. And USD/INR itself is a PROXY — the ECB cross, not the RBI reference rate.

*Sources:* `outputs/tables/trade_book.csv`, `outputs/tables/adverse_events_summary.csv`, `outputs/tables/var_summary.csv`, `docs/31_adverse_events.md`, `docs/40_var_garch.md`

## 9. Your book shows ₹192.1 m. How much of that is real, and how do you know the attribution adds up?

*P&L attribution and deal margin.*

It adds up by construction: sequential full revaluation in a fixed factor order, a largest residual of ₹0 on any trade-day, and a formula-driven Excel workbook that recalculates 132,447 cells with 0 failed checks. Whether it is real is the better question. +₹165.2 m of it — 86 % — is deal margin at contract dates, and that is my own sale-pricing rule on a domestic anchor premium still PENDING verification. Across that premium's registered grid the book runs −₹105.4 m to +₹334.3 m, break-even −38,702 ₹/MT inside the grid: not sign-robust. Grade spread adds +₹103.3 m on a reconstructed grade path; flat price cost ₹30.0 m and carry ₹56.6 m. ₹94.3 m of the deal margin landed on trade dates and ₹70.9 m on later bookings. So: the arithmetic is audited; the level is an assumption, and I would put a buyer quote under it before calling it profit.

*Sources:* `outputs/tables/attribution_daily.csv`, `outputs/tables/pnl_sensitivity_sign_robustness.csv`, `outputs/tables/new_deal_timing.csv`, `outputs/tables/pnl_controls.csv`, `outputs/excel/reconciliation.json`, `docs/30_mtm_attribution.md`

## 10. Walk me through your worst trade, T08. What went wrong?

*The worst trade.*

T08: 1,680 MT of Tense on US East Coast → Mundra, bought 8-Jun at 0.782 × the LME cash average — ₹8,883/MT of arb with conversion stressed, against a ₹5,000 hurdle. Lifetime −₹11.7 m (−₹6,980/MT). Deal margin of +₹20.1 m was more than eaten: carry and roll −₹13.0 m, because it was sold on 9-Aug, 62 days after purchase, once the buyer's line had room; grade spread −₹10.9 m, the book's only negative; flat price −₹8.6 m; and events −₹3.7 m — a radiation-portal box rejection plus arrival and dwell delays (all SIM). My hard drawdown stop would have triggered on 1-Aug. What I got wrong: I bought formula cargo with no buyer on a thin screen, and let a credit line set my sale date. The formula purchase did its job on flat price; the time did the damage.

*Sources:* `outputs/tables/attribution_daily.csv`, `outputs/tables/trade_book.csv`, `outputs/tables/margin_liquidity_policy_limits.csv`, `docs/30_mtm_attribution.md`

## 11. Who was your riskiest buyer, and why did you keep selling to them?

*Counterparty credit and advance concentration.*

BUY_RJK_01, Saurashtra Castings and Alloys Pvt Ltd (SIM), on a ₹120 m line. On receivables it never breached — peak 74.4 %. The risk was in advances: I sold it 3 parcels against advances of 1.26×, 1.53× and 1.83× its line, so contracted exposure peaked at 2.57× the line. If an advance fails I hold unsold cargo, perhaps with the hedge already lifted. My logistic score gives it 41.8 % PD, band D: cut the line to ₹60 m, advance or cash-against-documents only. But that model is fitted on 1,200 synthetic buyer-quarters, and the profile that makes it riskiest was written by the same hand as the book — an illustration, not a validation. Looking back, 5 of 10 bookings broke the band policy. In the Monte Carlo on 27-Jul its default costs ₹28.3 m, or ₹68.9 m with LME −15 % — worse than every simulated path.

*Sources:* `outputs/tables/credit_scores.csv`, `outputs/tables/credit_tracker_bookings.csv`, `outputs/tables/mc_stress_scenarios.csv`, `docs/50_credit_scoring.md`

## 12. LME fell hard in the crash fortnight and you were short MCX. Where did the cash stress actually come from?

*Margin and liquidity through the crash.*

Not from the crash: the short hedges were paid in it. From 22-Apr to 9-May LME cash fell 16.5 % and variation margin brought in +₹65.0 m. The squeeze was March: margin cash deployed peaked at ₹105.7 m on 24-Mar, and in the worst fortnight, 15-Mar to 29-Mar, LME rose 11.4 % and net margin cash out was ₹77.1 m. Peak initial margin was ₹95.8 m on 21-Apr. The stress I rehearse is the move that did not happen: LME up 23.3 % against the hedges in the crash fortnight calls ₹181.8 m more, headroom falls to −₹181.6 m, and the cargo's offsetting ₹427.0 m gain is only on paper. The real problem was working capital: funding need of ₹1,179.0 m against a ₹1,000 m line, on a day when margin was already a net source of ₹115.6 m.

*Sources:* `outputs/tables/margin_liquidity_summary.csv`, `docs/51_margin_liquidity.md`

## 13. What is your policy risk — say a BIS quality-control order on scrap lands while your boxes are at the port?

*Policy risk — BIS quality-control orders.*

The fact first: no BIS QCO applied to aluminium scrap in 2022. The register marks that DIRECT and VERIFIED; the first Mines-ministry QCOs came later and covered primary products, not scrap. So this is a hypothetical shock, not a replay — but a plausible one, because the primary industry has lobbied for scrap standards. My stress holds every unreleased box 21 days, rejects 10 % of the tonnage and loses 15 % of CIF value on the rejects. It costs ₹14.3 m on 8-Mar, ₹45.6 m on 21-Apr and ₹18.3 m on 27-Jul; the last two are worse than every one of the 10,000 Monte Carlo paths, because no covariance matrix contains a customs hold. Charged to every ticket on 27-Jul, not only unreleased lots, it is −₹67.4 m. Mitigants: keep unreleased tonnage small, buy from inspected origins, and write a regulatory-hold clause into the SPA.

*Sources:* `config/params/regulatory.yaml`, `outputs/tables/mc_stress_scenarios.csv`, `docs/41_monte_carlo.md`

## 14. Which of your numbers are real, and which are proxies or assumptions?

*Data limitations and proxies.*

Of 232 registered parameters, 51 are DIRECT, 16 PROXY and 165 ASSUMPTION; 47 are VERIFIED and 46 still PENDING. In the daily market panel 7 of 28 columns are DIRECT. Real: LME cash, 3M and stocks (LME official prices via Westmetall), duty rates, MCX contract specs, policy rates and 649 dated news headlines. Proxies: USD/INR is an ECB cross, not the RBI reference rate; MCX is duty-paid import parity, and a third-party mirror puts its beta at 0.75 on weekly closes, not one. Reconstructions: freight lane levels, the INR 3M rate and the grade-factor path use information published after the fact. The domestic anchor premium that drives most of the deal margin is unverified. Every counterparty, vessel, event and trade is simulated. First upgrade: MCX bhavcopy closes and FBIL reference rates, which drop into `data/manual/` and replace the proxies.

*Sources:* `config/params/`, `data/processed/series_provenance.csv`, `docs/00_assumptions_log.md`, `docs/verification_log.md`

## 15. If you ran this desk again, what would you do differently?

*What would you do differently.*

Four things. First, put a buyer quote under the pricing rule before calling it margin: deal margin is 86 % of P&L, and the book's break-even anchor premium, −38,702 ₹/MT, sits inside the registered grid (−₹105.4 m to +₹334.3 m). Second, stress the plan's peak, not its average: my lines were sanctioned on the plan's average balance, and one ₹25 crore step more (₹1,250 m) would have held the working-capital line, but usance maturities, IGST and buyer credit bunched into ₹1,179.0 m. Third, hedge averaging sales one fixing at a time, not with a midpoint flip, and size MCX on a weekly-close beta (0.75), never the daily 0.45. Fourth, keep the stops but know their cost: T08 hit its drawdown stop on 1-Aug, which bars new exposure in the grade, so my stops would have refused T09, same grade, on 3-Aug — and T09 finished +₹10.0 m. Stops are insurance, not forecasts.

*Sources:* `outputs/tables/pnl_sensitivity_sign_robustness.csv`, `outputs/tables/margin_liquidity_limit_grid.csv`, `outputs/tables/margin_liquidity_policy_limits.csv`, `outputs/reports/post_mortem.md`, `outputs/reports/risk_policy_memo.md`

## 16. Why GARCH instead of just historical volatility?

*Volatility model.*

Because a 250-day window answers "how volatile was last year?" and a desk needs "how volatile is tomorrow?". At the 7-Mar all-time high, GARCH(1,1) forecast 2.89 % a day against 1.67 % for the window; the next day's −12.95 % log fall was −4.5σ for GARCH and −7.7σ for the window. Not a crystal ball, though. On the alert rule I declared before looking — each method's 90th percentile over 2019–2021 — the window crossed on 9-Feb, 3 trading days before GARCH (14-Feb). Entering the crash fortnight GARCH sat below both windows (1.85 % against 1.96 % and 2.84 %). On the book it broke 7 times in 120 days against the window's 5 (expected 6); Kupiec accepts 2 to 11, so 120 days cannot rank them. On a fixed long over 1,011 days neither fails; in 2021 alone the window fails and GARCH does not. GARCH sizes today's risk; the long window is my floor.

*Sources:* `outputs/tables/var_summary.csv`, `outputs/tables/var_lead_lag.csv`, `outputs/tables/kupiec.csv`, `docs/40_var_garch.md`

## 17. Why didn't you try to predict LME direction with machine learning?

*Price prediction.*

Because a physical desk earns on structure, not on calling the tape, and this book shows it. The money is landed cost against a domestic anchor, grade, freight and tenor; flat price is hedged. From the 7-Mar high to the 15-Jul trough the MCX legs offset 83 % of the physical's LME loss, and lifetime flat-price P&L was −₹30.0 m. Nor would the data carry one: 2022 was one regime-shift year with a handful of independent shocks, which a model fitted on 2018–2021 had never seen. My one exogenous signal — 649 real headlines over 28 weeks, scored with VADER — showed no evidence of a lead: 0 of 12 lead tests significant, against 0.6 expected by chance. A neural net on that would fit noise. I spent the quant effort where it changes a decision: GARCH to size risk, Monte Carlo for joint shocks, a logistic score for credit limits.

*Sources:* `outputs/tables/sentiment_summary.csv`, `outputs/tables/adverse_events_summary.csv`, `docs/70_sentiment_overlay.md`, `docs/spec/MASTER_SPEC_V3.md`

## What this pack does and doesn't tell you

It shows how this simulated book would be defended under questioning, with every figure traceable to a table and every weakness stated next to the number it weakens. It does not show that the trades were real (they are not), that the anchor premium or grade path was knowable in 2022 (it was not verified, and the grade path uses later data), or that the risk models forecast anything: they size and stress the risk they are given. Answers are capped at 150 words; the docs they cite carry the detail.
