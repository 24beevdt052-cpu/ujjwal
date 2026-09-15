# MASTER SPEC V3.0 — "Virtual Metals Trading Desk" (Aluminium Scrap Import)

Cleaned transcription of `MASTER_SPEC_V3.md.pdf` (source of truth for scope). Status: FINAL — quant-upgraded
(GARCH VaR + Monte Carlo + credit scoring added).

## Table 1 — Role & mission
- **Role:** senior base-metals trader at a global trading house (Trafigura/Mercuria/Glencore-style) AND a quant
  developer. Build a complete, professional-grade Simulated Physical Metals Trading Desk to show recruiters at
  Hindalco (Aditya Birla), Vedanta, Tata International (Metals), JSW Group for a physical trading internship.
- **Simulation disclaimer:** all counterparties, vessels and trades labelled "ACADEMIC SIMULATION — not actual
  trades" on every document.
- **What changed in V3:** three defensible quant upgrades (GARCH volatility, Monte Carlo stress testing,
  counterparty credit scoring) and one optional NLP touch (sentiment on desk notes). Price-prediction ML
  (LSTM/deep learning) deliberately excluded — no credible physical trader claims to predict LME direction with a
  neural net; including one would undermine interview credibility.

## Table 2 — Commodity, lane & backtest window
- **Commodity:** aluminium scrap imports into India (ISRI grades: Zorba, Taint/Tabor, Tense — verify grade specs
  via ISRI / Recycling International). India imports ~1.5–2 Mn MT/yr, one of the world's largest scrap import markets.
- **Lane:** Jebel Ali (UAE) / USA → Mundra / Nhava Sheva, India. Sold to fictional secondary smelters & foundry
  buyers (Rajkot/Gujarat cluster, SIM-labelled).
- **Why this lane:** LME-linked pricing + grade discount (% of LME), container/bulk freight, USD/INR FX, real liquid
  hedges (LME + MCX Aluminium futures + USD/INR forwards), real policy risk (import duty changes, BIS-QCO scrap import
  restrictions), counterparty credit risk with foundry buyers.
- **Backtest window:** March–August 2022 (primary). LME aluminium made an all-time high (~$3,985/t, early Mar 2022)
  then crashed ~35% by August; USD/INR slid ~75.5→79. The crash and INR slide are REAL adverse events in the window.
- **Data sources (declare all):** LME aluminium prices (lme.com public/delayed), MCX bhavcopy, RBI reference rate /
  FBIL forwards, container freight proxy (Drewry WCI / SCFI Middle East routes), CBIC for HS 7602 scrap duty, public
  scrap-to-LME spread references. Every source labelled DIRECT / [PROXY] / [ASSUMPTION].

## Table 3 — Component 1: Trade finder (import parity model)
| # | Element | Specification |
|---|---|---|
| 1.1 | Format | Python + Excel; weekly parity computation over the 6-month window |
| 1.2 | Landed cost build-up (USD→INR) | LME 3M × grade factor (e.g. Zorba ~75–85% of LME, Taint-Tabor ~88–92% [VERIFY via published scrap spreads]) + ocean freight (USD/MT, proxy index) + insurance + USD/INR → assessable value; add BCD + SWS on HS 7602, IGST at import (creditable — exclude from cost if ITC available, verify), port/C&F charges ₹/MT, finance cost = (AV + duty) × days/365 × WC rate |
| 1.3 | Domestic price anchor | Secondary-ingot/foundry buying price modelled as MCX Aluminium + domestic premium [PROXY + correlation study] |
| 1.4 | Parity flag | Open/closed arbitrage window per week: domestic anchor − landed cost > conversion + margin threshold (₹/MT [ASSUMPTION with justification]) |
| 1.5 | Sensitivity tables (2-way) | (a) LME price × USD/INR; (b) freight × duty rate — P&L impact grid on 1,000 MT |
| 1.6 | Scrap reality check | Moisture/contamination deduction logic and yield factor (scrap→ingot recovery ~90–95% [ASSUMPTION]) |
| 1.7 | LME term structure | Model LME Cash–3M spread (contango/backwardation) weekly. Show effect on (a) M+1 pricing settlement basis and (b) roll yield on hedges. State which LME reference the pricing formula settles against, and what contango/backwardation cost or earned. |

## Table 4 — Component 2: Mock trading book (8–10 trades)
| # | Field | Specification |
|---|---|---|
| 2.1 | Quantity | 1,000–5,000 MT per trade (containerised ~24–26 MT/box; bulk parcels allowed) |
| 2.2 | Contract (SPA terms) | ISRI grade spec, moisture %, radioactivity check clause, rejection/discount penalty schedule |
| 2.3 | Incoterms | Mix of FOB and CFR (state who books freight + who bears freight risk in each) |
| 2.4 | Pricing formula | Mix of fixed price vs LME M+1 monthly-average pricing + grade premium; state pricing period dates and LME reference (Cash or 3M), tied to 1.7 |
| 2.5 | Counterparties | 2–3 fictional suppliers, 2–3 fictional buyers (SIM), each with assigned credit limits — limits feed 4.3 credit scoring |
| 2.6 | Payment terms | LC sight vs 60–90d usance on imports; advance vs 30d credit on domestic sales |
| 2.7 | Hedge stack (per trade) | (a) MCX Aluminium futures with hedge ratio + roll dates; (b) USD/INR forwards, hedge % per trade; (c) cross-exchange basis risk explanation; (d) freight risk layer — hedge with proxy instrument or accept unhedged with a stated stop-loss |
| 2.8 | Laycan | Shipment window per trade, vessel (SIM), freight rate vs proxy index |
| 2.9 | Trade discipline | Trades executed ONLY when Component 1 parity window is open — one-paragraph trader's rationale per trade |

## Table 5 — Component 3: Daily MTM & P&L attribution engine (Python)
| # | Element | Specification |
|---|---|---|
| 3.1 | Daily MTM | Per position, per day, over the window — pandas, clean and commented |
| 3.2 | Attribution split | (a) LME flat-price move, (b) LME–MCX cross-exchange basis, (c) grade premium/scrap spread change, (d) freight variation vs fixture, (e) FX move, (f) demurrage/penalty accruals, (g) roll yield / term-structure effect |
| 3.3 | Outputs | Equity-curve cumulative P&L chart + per-trade attribution waterfall charts |
| 3.4 | Adverse event #1 (real) | LME aluminium crash mid-window (2022 reversal) — isolated P&L impact + MCX variation-margin cash-flow schedule |
| 3.5 | Adverse event #2 (real) | USD/INR depreciation ~5% within the window — isolated impact + forward-book offset |
| 3.6 | Adverse event #3 (real) | Container freight spike / buyer payment delay event — isolated impact + credit-limit mitigation |

## Table 6 — Component 4: Risk pack (quant-upgraded)
| # | Element | Specification |
|---|---|---|
| 4.1 ★ | VaR with GARCH | Daily 95% VaR on the total book. Fit GARCH(1,1) (Python `arch`) to LME aluminium daily log returns over a lookback window; use the conditional volatility forecast to scale VaR day-by-day. Compare GARCH VaR vs simple historical-volatility VaR side-by-side — this comparison IS the finding: show where GARCH flagged rising risk earlier, especially heading into the crash. Backtest exceptions table + Kupiec test on both methods. |
| 4.2 ★ | Monte Carlo stress | 10,000 paths jointly simulating LME price, USD/INR and freight rate using their historical covariance over the backtest window. Full P&L distribution with 95%/99% percentile losses; overlay the five stress scenarios (LME −15%, INR −5%, freight +40%, buyer default, BIS-QCO + demurrage) on the distribution. |
| 4.3 ★ | Counterparty credit scoring | Simple logistic regression estimating default probability per fictional buyer using 3–4 features (exposure vs limit, days-past-due, payment-history length, order concentration). Train/illustrate on simulated trade-book data — clearly labelled illustrative on synthetic data. Output a ranked risk score per counterparty feeding 4.4. |
| 4.4 | Credit tracker | Counterparty exposure vs assigned limits, updated per trade; breach flags; annotated with the 4.3 risk score |
| 4.5 | Margin & liquidity | MCX margin deployed vs cash buffer through the crash fortnight |
| 4.6 | Risk policy memo (1 page) | Position limits (MT & USD), max unhedged %, stop-loss rules, hedge policy, counterparty limit rules tied to 4.3 score bands, freight risk policy — desk-memo voice |

## Table 7 — Component 5: Desk reporting pack (recruiter-facing)
| # | Element | Specification |
|---|---|---|
| 5.1 | Weekly desk notes | 6 one-page notes (PDF-ready) in real trader voice: what I saw, what I did, P&L attribution summary, risks next week — include Cash–3M structure and freight view |
| 5.2 ☆ optional | Sentiment overlay | Real aluminium/steel news headlines per week of the window (public sources — RSS/news APIs). Lightweight classifier (VADER, or FinBERT if time) → weekly "market sentiment score", referenced alongside price action in the desk notes. Simple, clearly labelled; a supporting signal, not a forecasting model. |
| 5.3 | Deal post-mortem | 2 pages on the single best trade: thesis, execution, attribution breakdown, lessons — including one honest admission |
| 5.4 | README.md | How a fresher built and ran this desk: folder structure, data pipeline, how to re-run, verification checklist. Include "Why these quant methods and not others" (3–4 sentences: why GARCH / Monte Carlo / logistic regression over more complex ML, and why price-prediction models were deliberately excluded). |

## Table 8 — Quality bar & definition of done
1. Every number internally consistent and traceable to a stated source or clearly-labelled [PROXY]/[ASSUMPTION].
2. Clean commented Python (pandas, matplotlib, arch, scikit-learn); master Excel workbook formula-driven for
   Components 1–3 (GARCH / Monte Carlo / credit scoring stay in Python).
3. Units consistent everywhere: USD/MT vs ₹/MT vs ₹/kg vs LME $/t — never mixed silently.
4. Volatile parameters (MCX contract specs, HS 7602 duty, QCO status, forward premium, LME Cash–3M spread) verified
   on CBIC / mcxindia.com / RBI before final submission — verification log included.
5. Every quant model includes a plain-English "what this does and doesn't tell you" paragraph.
6. Final section: 17 toughest interview questions a physical metal trader would ask — the original 15 PLUS "Why
   GARCH instead of just historical volatility?" and "Why didn't you try to predict LME direction with machine
   learning?" — with sharp model answers built on THIS trade book's numbers.

## Table 9 — Build sequence
| Phase | What | Why this order |
|---|---|---|
| 0 | Data dictionary + assumptions log | Nothing else works without clean, sourced data |
| 1 | Component 1 — parity model | Proves the core trading logic first |
| 2 | Component 2 — mock trading book | Turns the model into actual trade decisions |
| 3 | Component 3 — MTM & P&L attribution | Shows what happened to those trades over time |
| 4 | Component 4.1–4.2 — GARCH VaR + Monte Carlo | Single highest-value quant upgrade |
| 5 | Component 4.3–4.6 — credit scoring + rest of risk pack | Second-priority upgrade |
| 6 | Component 5.1, 5.3, 5.4 — desk notes, post-mortem, README | Core recruiter-facing pack |
| 7 | Component 5.2 — sentiment overlay | Nice-to-have; must not delay Phases 0–6 |

Note: the spec's "original 15" interview questions are not enumerated in the PDF; the interview pack defines them.
