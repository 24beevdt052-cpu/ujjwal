"""Stage P6 — the interview pack: 17 hard questions with answers built on this book (MASTER_SPEC Table 8 row 6).

    DESK_OFFLINE=1 .venv/bin/python -c "import desk.reporting.interview_pack as m; m.main()"

Reads (never writes) the published P1–P7 tables, the Phase 0 panel and the parameter register, and writes:

    outputs/reports/interview_pack.md     the pack (GitHub-readable)
    outputs/reports/interview_pack.pdf    the same through desk.reporting.pdf (SIM label and page numbers on every page)

Design choices worth knowing
----------------------------
* **Which 17.** The spec asks for "the original 15" plus two named questions but never lists the 15. The first
  fifteen here were written for this pack, one per area a physical desk head probes (parity, grade, incoterms and
  freight, LC funding, M+1 pricing and structure, MCX basis, hedge ratios and rolls, FX, attribution, the worst trade,
  credit, margin, policy, data, hindsight); the last two are the spec's, verbatim (`REQUIRED_QUESTIONS`). The pack
  says so at the top.
* **No hand-typed numbers.** Every number in a question or an answer is a `{placeholder}` filled from the tables by
  `compute_raw` → `format_facts`. `tests/test_reports_runner.py` renders every template with sentinels and fails if a
  digit survives outside a short allow-list of structural tokens (GARCH(1,1), bucket letters, HS codes, the 95/99 %
  confidence labels, "3M").
* **Qualitative words are tested, not trusted.** "the only negative", "beyond every path", "before the usance
  matures" cannot be placeholders, so `check_claims` re-tests each against the data and `main()` raises if any
  fails. A changed book fails loudly instead of publishing an answer about the wrong trade.
* **The headline never travels alone.** Wherever an answer quotes the book's P&L it also quotes the
  `domestic_anchor_premium_inr_t` band from `pnl_sensitivity_sign_robustness.csv` (asserted in the tests), because
  the headline is not sign-robust.
* **Short.** Each answer is capped at `MAX_ANSWER_WORDS` words (asserted): an interview answer, not a doc page.
* **The Excel reconciliation is quoted only when it is VERIFIED.** The full recalculation is a slow test a normal
  build never runs. `desk.excel.reconciliation_status` compares the record's workbook SHA-256 with the workbook on
  disk; unless they match and the record passed, Q9 says the check is not current and a note at the top gives the
  status (STALE, NOT_RUN or FAILED) and the exact command to verify, instead of quoting old numbers or crashing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from desk import DESK_NAME, HISTORY_START, HORIZON_END, SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.excel import reconciliation_status as recon_status
from desk.paths import PROCESSED_DIR, REPORTS_DIR, ROOT, TABLES_DIR
from desk.reporting.pdf import PdfStyle, count_pdf_pages, render_markdown_pdf
from desk.reporting.style import PNL_BUCKETS

NAME = "interview_pack"
N_QUESTIONS = 17                       # Table 8 row 6: "the original 15" plus the two named questions
MAX_ANSWER_WORDS = 150
ANCHOR_KEY = "domestic_anchor_premium_inr_t"
RECON_SOURCE = "outputs/excel/reconciliation.json"   # written only by the slow Excel reconciliation test
WORST_TRADE_OF_RECORD = "T08"          # the ticket Q10 was written for; check_claims fails if the book's worst changes
RISKIEST_BUYER_OF_RECORD = "BUY_RJK_01"  # the buyer Q11 was written for
MC_SNAP_ATH, MC_SNAP_APR, MC_SNAP_JUL = "ATH_PLUS_1", "PEAK_GROSS_LME", "PEAK_BUYER_CONTRACTED"
REQUIRED_QUESTIONS = (
    "Why GARCH instead of just historical volatility?",
    "Why didn't you try to predict LME direction with machine learning?",
)
NB = "\u00a0"
MINUS = "\u2212"
M = 1e6
GRADE_NAMES = {"zorba": "Zorba 95/5", "taint_tabor": "Taint/Tabor", "tense": "Tense"}
LANE_NAMES = {"JEA_NSA": "Jebel Ali → Nhava Sheva", "USEC_MUN": "US East Coast → Mundra"}
# keep_sections: a question, its answer and its sources never split across a page break
PACK_STYLE = PdfStyle(font_size=8.6, table_font_size=7.6, title_size=13.0, h2_size=9.6, h3_size=8.8,
                      paragraph_space_after=3.0, heading_space_before=6.0, margin_top_mm=13.0, margin_bottom_mm=14.0,
                      keep_sections=True)


# ------------------------------------------------------------------------------------------------ formatting
def _nonzero(s: str) -> bool:
    return any(ch not in "0.," for ch in s)


def num(x: float, dp: int = 0) -> str:
    """Thousands-separated number with a true minus sign (U+2212); never prints a negative zero."""
    s = f"{abs(x):,.{dp}f}"
    return f"{MINUS}{s}" if x < 0 and _nonzero(s) else s


def signed(x: float, dp: int = 0) -> str:
    s = num(x, dp)
    return s if s.startswith(MINUS) or not _nonzero(s) else f"+{s}"


def inr_m(x: float, dp: int = 1, sign: bool = False) -> str:
    s = f"{abs(x) / M:,.{dp}f}"
    if x < 0 and _nonzero(s):
        return f"{MINUS}₹{s}{NB}m"
    return f"+₹{s}{NB}m" if sign and _nonzero(s) else f"₹{s}{NB}m"


def inr(x: float) -> str:
    s = f"{abs(x):,.0f}"
    return f"{MINUS}₹{s}" if x < 0 and _nonzero(s) else f"₹{s}"


def pct(frac: float, dp: int = 1, sign: bool = False) -> str:
    return f"{(signed if sign else num)(frac * 100, dp)}{NB}%"


def mult(x: float, dp: int = 2) -> str:
    return f"{num(x, dp)}×"


def day(d, year: bool = False) -> str:
    ts = pd.Timestamp(d)
    return ts.strftime(f"{ts.day}-%b-%Y" if year else f"{ts.day}-%b")


def usd_t(x: float, dp: int = 0) -> str:
    return f"USD{NB}{num(x, dp)}/t"


# ------------------------------------------------------------------------------------------------ questions
@dataclass(frozen=True)
class Question:
    """One question. `question` and `answer` are templates; `sources` are repo-relative paths (a test checks them)."""

    qid: str
    topic: str
    question: str
    answer: str
    sources: tuple[str, ...]


QUESTIONS: tuple[Question, ...] = (
    Question(
        "parity", "Import parity, landed cost and the duty wedge",
        "Walk me through the landed cost on your first trade. Where is the duty wedge, and why did you trust the arb?",
        "{first_tid} is {first_grade} on {first_lane}, parity week to {q1_week}. CFR is {q1_cfr} (LME 3M "
        "{q1_lme3m} × grade factor {q1_gf}); at {q1_fx} that is {q1_goods}/MT of goods. BCD at {q1_bcd_rate} plus "
        "SWS adds {q1_duty}, port {q1_port}, finance {q1_fin}; IGST is only financed, because I take it back as "
        "input credit. Landed: {q1_landed}/MT. The wedge sits on the selling side: my anchor is MCX, which trades at "
        "*primary* import parity with {q1_bcd_primary} BCD (HS 7601), while scrap pays {q1_bcd_rate} (HS 7602) — "
        "about {q1_wedge}/t of metal that week. After recovery {q1_recovery}, by-product and conversion, the net arb "
        "was {q1_na}/MT against a {q1_hurdle} hurdle. I traded only where three screens agreed — base, the "
        "point-in-time grade mix ({q1_na_pit}) and conversion stressed ({q1_na_conv}) — a rule declared before any "
        "result: {q1_n_elig} of {q1_n_cases} in-window cases passed, against {q1_n_open} open on base alone.",
        ("outputs/tables/parity_weekly.csv", "config/params/regulatory.yaml", "docs/10_parity_model.md"),
    ),
    Question(
        "grade", "Grade spreads and recovery",
        "Scrap is not LME. How did you price grade and recovery, and how much of your P&L is really grade spread?",
        "Grade is a CFR-India factor on LME 3M — {q2_gf_first} for {first_grade} on {first_tid}'s trade date — and my "
        "formula tickets buy at {q2_formula_factors} × the cash average. Recovery to ingot is (1 − moisture) × "
        "(1 − contamination) × yield: {q2_rec_zorba} Zorba, {q2_rec_tt} Taint/Tabor, {q2_rec_tense} Tense; a point of "
        "recovery is worth about {q2_rec_point}/MT at {first_tid}'s anchor. Grade spread is {q2_grade} of lifetime "
        "P&L, second only to deal margin, and I would not sell it as skill: the grade path behind it uses DGCIS unit "
        "values published months later. Re-priced on the point-in-time mix a {window_year} desk could see, the book falls from "
        "{book_pnl} to {q2_pit_pnl} and grade spread turns {q2_pit_grade}; the lag-1 and lag-3 mixes give "
        "{q2_lag1_pnl} and {q2_lag3_pnl}. The headline band on the anchor premium is {band_lo} to {band_hi}. "
        "{worst_tid} is the only ticket with a negative grade spread ({q2_worst_grade}).",
        ("outputs/tables/attribution_daily.csv", "outputs/tables/pnl_sensitivity_summary.csv",
         "config/params/scrap_grades.yaml", "docs/30_mtm_attribution.md"),
    ),
    Question(
        "freight", "Incoterms and freight risk",
        "FOB or CFR — who carries the freight risk on your tickets, and what did freight do to you?",
        "{q3_n_fob} of {n_trades} tickets are FOB ({q3_fob_ids}): I book the boxes, so the freight is my risk until the "
        "fixture is paid. The other {q3_n_cfr} are CFR — the seller's freight sits inside the price. Cargo risk passes "
        "on board at the load port either way. There is no liquid India-inbound container swap, so every FOB ticket "
        "runs freight unhedged against a stated stop-loss per box ({q3_stops}). Freight fell {q3_fall_usec} on the US "
        "lane and {q3_fall_jea} on the Gulf lane across the window; fixing ahead of the B/L cost {q3_fixture_cost} "
        "over the tickets' lives, and bucket (d) ended at {q3_freight_bucket}. Two caveats I state up front: lane "
        "levels are hindsight-calibrated reconstructions, and the Gulf lane is {q3_ratio} × the US lane every week, "
        "so freight is really one factor. The {q3_shock} spike is a hypothetical stress: {q3_stress} on {ath1_date}, "
        "with only {ath1_trades} on the book.",
        ("outputs/tables/trade_book.csv", "outputs/tables/adverse_events_summary.csv",
         "outputs/tables/mc_stress_scenarios.csv", "data/processed/freight_weekly.csv", "docs/31_adverse_events.md"),
    ),
    Question(
        "funding", "LC, usance and funding",
        "How did you pay your suppliers — sight or usance LCs — and did you actually have the bank lines for this book?",
        "{q4_n_sight} tickets on sight LCs, {q4_n_usance} on usance ({q4_usance_days} days). Usance pays when the buyer "
        "settles inside the tenor: on {q4_n_usance_covered} of the {q4_n_usance} the sale was due before the usance "
        "matured. On lines, the honest answer is no. I sized a {q4_wc_limit} working-capital line and a {q4_lc_limit} "
        "LC line ex ante on the February plan's average balance, not from the book. Funding need peaked at "
        "{q4_funding_peak} on {q4_funding_date}: {q4_buffer_days} days into the {q4_buffer} cash buffer, {q4_fb_days} "
        "over the line, which one more {q15_step} step ({q15_wc_step}) would have held. LCs outstanding, counted at "
        "face plus tolerance, reached {q4_lc_peak}, over the line for {q4_lc_days} days. The book needed {q4_wc_needed} and {q4_lc_needed} "
        "to avoid any breach, and paid {q4_interest} of interest to the horizon. The fix is sequencing, not a bigger "
        "bank: fewer purchases ahead of sale advances, and usance matched to buyer credit.",
        ("outputs/tables/trade_book.csv", "outputs/tables/margin_liquidity_summary.csv",
         "outputs/tables/margin_liquidity_limit_grid.csv", "docs/51_margin_liquidity.md"),
    ),
    Question(
        "structure", "M+1 pricing and the Cash–3M structure",
        "Your formula purchases settle on the LME cash average of the month after shipment. What does the Cash–3M "
        "structure do to you?",
        "{q5_n_formula} tickets ({q5_formula_ids}) buy at a factor × the LME *cash* average of M+1, so they settle "
        "against cash, while parity is struck on 3M. The structure is a basis between the two: in contango the M+1 "
        "cash average sits below 3M and I gain as a buyer; in backwardation I pay. In the window Cash–3M ran "
        "{q5_spread_min} to {q5_spread_max} USD/t, contango in {q5_n_contango} of {q5_n_weeks} weeks — worth at most "
        "{q5_effect_max} against a {first_tid} arb of {q5_arb_usd}. Rolls tell me nothing here: my MCX proxy curve is "
        "in contango by construction, so all {q5_n_rolls} short rolls gained {q5_roll_pnl} of rupee carry, not term "
        "structure; on a curve with the LME's own slope they make {q5_roll_lme}. Bucket (g), {q5_g}, is not structure "
        "either: {q5_g_funding} of it is funding and {q5_g_mcx} sits on the MCX legs, cross-terms included.",
        ("outputs/tables/term_structure_weekly.csv", "outputs/tables/mcx_roll_carry.csv",
         "outputs/tables/attribution_leg_daily.csv", "docs/30_mtm_attribution.md"),
    ),
    Question(
        "basis", "MCX hedging and cross-exchange basis",
        "You hedge LME-priced scrap with MCX futures. What is your basis risk, and did you measure it?",
        "My MCX series is a PROXY at duty-paid import parity, so it has unit beta to LME × USD/INR by construction "
        "and bucket (b) is zero every day, which flatters the hedge. Against a third-party mirror the beta is "
        "{q6_beta} on daily changes (t {q6_beta_t}), but MCX closes hours after the LME fix, which biases "
        "a daily beta down: on weekly closes it is {q6_beta_w} (t {q6_beta_w_t}), and {q6_beta_ll} once closes are "
        "matched. So a unit-beta short leaves about {q6_open_w} of a parity move open, not {q6_open}. A Monte Carlo "
        "basis factor lifts the 99 % {mc_h}-day VaR from {q6_apr_base} to {q6_apr_basis} on {apr_date} and from "
        "{q6_jul_base} to {q6_jul_basis} on {jul_date}. Mean daily GARCH VaR is {q6_var_base} on the proxy, "
        "{q6_var_beta_w} at the weekly beta and {q6_var_beta} at the daily one, which nobody would hedge on. I would "
        "hedge on the weekly beta and carry basis as a risk factor.",
        ("outputs/tables/mcx_basis_risk.csv", "outputs/tables/var_mcx_beta.csv", "outputs/tables/mc_summary.csv",
         "outputs/tables/var_summary.csv", "docs/40_var_garch.md", "docs/41_monte_carlo.md"),
    ),
    Question(
        "hedge", "Hedge ratios and rolls",
        "What hedge ratio did you run, how did you roll, and did the hedge work in the crash?",
        "Target {q7_hr_common} of LME-equivalent metal on {q7_n_common} tickets, {q7_hr_full} on {q7_full_ids}, and "
        "{q7_hr_low} on {q7_low_id} — outside my own {q7_band} policy band, and I say so. Rolls go {q7_roll_days} "
        "trading days before expiry: {q7_n_rolls} rolls, none late. The test was the fall from the {e1_start} high to "
        "the {e1_end} trough, LME cash {q7_e1_move}: physical cargo lost {q7_phys} on flat price, the MCX legs made "
        "{q7_mcx} — {q7_offset} offset — and against an unhedged book the hedges were worth {q7_benefit}. Where it "
        "failed: net unhedged metal broke my {q7_nu_limit} MT limit on {q7_nu_days} clean days, and the "
        "physical-to-hedge timing on averaging sales left net positions I had not chosen. And the hedge is only as good "
        "as unit beta; the third-party MCX mirror says {q6_beta_w} on weekly closes.",
        ("outputs/tables/trade_book.csv", "outputs/tables/adverse_events_summary.csv",
         "outputs/tables/margin_liquidity_policy_limits.csv", "docs/31_adverse_events.md"),
    ),
    Question(
        "fx", "USD/INR forwards",
        "How did you hedge USD/INR, and what did the rupee's slide do to the book?",
        "The payable is in dollars, so I buy dollars forward against it: {q8_n_lines} forward lines, "
        "full cover as policy except {q8_low_id} at {q8_low_cover}, below my {q8_min_cover} minimum. The rupee went "
        "from {q8_fx_start} to {q8_fx_end} a dollar ({q8_fx_move}) between {e2_start} and {e2_end}. Over that stretch the "
        "forwards made {q8_fwd}, against {q8_usd_flows} on the dollar payables — {q8_offset} cover — while the MCX "
        "legs lost {q8_mcx}, because a rupee contract priced at import parity is itself a dollar position. The "
        "lifetime FX bucket is {q8_fx_bucket}. So I read FX risk on physical plus forwards ({q8_var_pf} mean daily "
        "GARCH VaR) and the MCX leg ({q8_var_mcx}) separately; netted, it shows {q8_var_net}, which hides two "
        "offsetting positions. And USD/INR itself is a PROXY — the ECB cross, not the RBI reference rate.",
        ("outputs/tables/trade_book.csv", "outputs/tables/adverse_events_summary.csv", "outputs/tables/var_summary.csv",
         "docs/31_adverse_events.md", "docs/40_var_garch.md"),
    ),
    Question(
        "attribution", "P&L attribution and deal margin",
        "Your book shows {book_pnl}. How much of that is real, and how do you know the attribution adds up?",
        "It adds up by construction: sequential full revaluation in a fixed factor order, a largest residual of "
        "{q9_residual} on any trade-day, and {q9_excel}. Whether it is real is the better question. {q9_nd} of it — "
        "{q9_nd_share} — is deal margin at contract dates, and that is my own sale-pricing rule on a domestic anchor premium still PENDING "
        "verification. Across that premium's registered grid the book runs {band_lo} to {band_hi}, break-even "
        "{band_be}{NB}₹/MT inside the grid: not sign-robust. Grade spread adds {q2_grade} on a reconstructed grade "
        "path; flat price cost {q9_lme_abs} and carry {q5_g_abs}. {q9_nd_td} of the deal margin landed on trade dates and "
        "{q9_nd_later} on later bookings. So: the arithmetic is audited; the level is an assumption, and I would put "
        "a buyer quote under it before calling it profit.",
        ("outputs/tables/attribution_daily.csv", "outputs/tables/pnl_sensitivity_sign_robustness.csv",
         "outputs/tables/new_deal_timing.csv", "outputs/tables/pnl_controls.csv", RECON_SOURCE,
         "docs/30_mtm_attribution.md"),
    ),
    Question(
        "worst", "The worst trade",
        "Walk me through your worst trade, {worst_tid}. What went wrong?",
        "{worst_tid}: {q10_qty} MT of {q10_grade} on {q10_lane}, bought {q10_date} at {q10_factor} × the LME cash "
        "average — {q10_na_conv}/MT of arb with conversion stressed, against a {q1_hurdle} hurdle. Lifetime "
        "{q10_pnl} ({q10_pnl_mt}/MT). Deal margin of {q10_nd} was more than eaten: carry and roll {q10_g}, because it "
        "was sold on {q10_sale_date}, {q10_sale_lag} days after purchase, once the buyer's line had room; grade spread "
        "{q10_grade_b}, the book's only negative; flat price {q10_lme}; and events {q10_events} — a radiation-portal "
        "box rejection plus arrival and dwell delays (all SIM). My hard drawdown stop would have triggered on "
        "{q10_stop_date}. What I got wrong: I bought formula cargo with no buyer on a thin screen, and let a credit "
        "line set my sale date. The formula purchase did its job on flat price; the time did the damage.",
        ("outputs/tables/attribution_daily.csv", "outputs/tables/trade_book.csv",
         "outputs/tables/margin_liquidity_policy_limits.csv", "docs/30_mtm_attribution.md"),
    ),
    Question(
        "credit", "Counterparty credit and advance concentration",
        "Who was your riskiest buyer, and why did you keep selling to them?",
        "{rjk_id}, {q11_name}, on a {q11_limit} line. On receivables it never breached — peak {q11_util}. The risk "
        "was in advances: I sold it {q11_n_adv} parcels against advances of {q11_adv_list} its line, so contracted "
        "exposure peaked at {q11_contracted}. If an advance fails I hold unsold cargo, perhaps with the hedge already "
        "lifted. My logistic score gives it {q11_pd} PD, band {q11_band}: cut the line to {q11_new_limit}, advance or "
        "cash-against-documents only. But that model is fitted on {q11_n_synth} synthetic buyer-quarters, and the "
        "profile that makes it riskiest was written by the same hand as the book — an illustration, not a validation. "
        "Looking back, {q11_n_outside} of {q11_n_bookings} bookings broke the band policy. In the Monte Carlo on "
        "{jul_date} its default costs {q11_default}, or {q11_default_lme} with LME {q11_lme_shock} — worse than every "
        "simulated path.",
        ("outputs/tables/credit_scores.csv", "outputs/tables/credit_tracker_bookings.csv",
         "outputs/tables/mc_stress_scenarios.csv", "docs/50_credit_scoring.md"),
    ),
    Question(
        "margin", "Margin and liquidity through the crash",
        "LME fell hard in the crash fortnight and you were short MCX. Where did the cash stress actually come from?",
        "Not from the crash: the short hedges were paid in it. From {q12_cf_start} to {q12_cf_end} LME cash fell "
        "{q12_cf_move} and variation margin brought in {q12_cf_vm}. The squeeze was March: margin cash deployed "
        "peaked at {q12_margin_peak} on {q12_margin_date}, and in the worst fortnight, {q12_mf_start} to {q12_mf_end}, "
        "LME rose {q12_mf_move} and net margin cash out was {q12_mf_net}. Peak initial margin was {q12_im} on {q12_im_date}. The "
        "stress I rehearse is the move that did not happen: LME up {q12_stress_move} against the hedges in the crash "
        "fortnight calls {q12_stress_call} more, headroom falls to {q12_stress_headroom}, and the cargo's offsetting "
        "{q12_paper} gain is only on paper. The real problem was working capital: funding need of {q4_funding_peak} "
        "against a {q4_wc_limit} line, on a day when margin was already a net source of {q12_margin_source}.",
        ("outputs/tables/margin_liquidity_summary.csv", "docs/51_margin_liquidity.md"),
    ),
    Question(
        "policy", "Policy risk — BIS quality-control orders",
        "What is your policy risk — say a BIS quality-control order on scrap lands while your boxes are at the port?",
        "The fact first: no BIS QCO applied to aluminium scrap in {window_year}. The register marks that DIRECT and VERIFIED; "
        "the first Mines-ministry QCOs came later and covered primary products, not scrap. So this is a hypothetical "
        "shock, not a replay — but a plausible one, because the primary industry has lobbied for scrap standards. My "
        "stress holds every unreleased box {q13_delay} days, rejects {q13_rej} of the tonnage and loses {q13_loss} of "
        "CIF value on the rejects. It costs {q13_ath} on {ath1_date}, {q13_apr} on {apr_date} and {q13_jul} on "
        "{jul_date}; the last two are worse than every one of the {n_paths} Monte Carlo paths, because no covariance "
        "matrix contains a customs hold. Charged to every ticket on {jul_date}, not only unreleased lots, it is "
        "{q13_all}. Mitigants: keep unreleased tonnage small, buy from inspected origins, and write a "
        "regulatory-hold clause into the SPA.",
        ("config/params/regulatory.yaml", "outputs/tables/mc_stress_scenarios.csv", "docs/41_monte_carlo.md"),
    ),
    Question(
        "data", "Data limitations and proxies",
        "Which of your numbers are real, and which are proxies or assumptions?",
        "Of {q14_n_params} registered parameters, {q14_n_direct} are DIRECT, {q14_n_proxy} PROXY and {q14_n_assump} "
        "ASSUMPTION; {q14_n_verified} are VERIFIED and {q14_n_pending} still PENDING. In the daily market panel "
        "{q14_sp_direct} of {q14_sp_n} columns are DIRECT. Real: LME cash, 3M and stocks (LME official prices via "
        "Westmetall), duty rates, MCX contract specs, policy rates and {q14_n_headlines} dated news headlines. "
        "Proxies: USD/INR is an ECB cross, not the RBI reference rate; MCX is duty-paid import parity, and a "
        "third-party mirror puts its beta at {q6_beta_w} on weekly closes, not one. Reconstructions: freight lane "
        "levels, the INR 3M rate and the "
        "grade-factor path use information published after the fact. The domestic anchor premium that drives most "
        "of the deal margin is unverified. Every counterparty, vessel, event and trade is simulated. First upgrade: "
        "MCX bhavcopy closes and FBIL reference rates, which drop into `data/manual/` and replace the proxies.",
        ("config/params/", "data/processed/series_provenance.csv", "docs/00_assumptions_log.md",
         "docs/verification_log.md"),
    ),
    Question(
        "differently", "What would you do differently",
        "If you ran this desk again, what would you do differently?",
        "Four things. First, put a buyer quote under the pricing rule before calling it margin: deal margin is "
        "{q9_nd_share} of P&L, and the book's break-even anchor premium, {band_be}{NB}₹/MT, sits inside the "
        "registered grid ({band_lo} to {band_hi}). Second, stress the plan's peak, not its average: my lines were "
        "sanctioned on the plan's average balance, and one {q15_step} step more ({q15_wc_step}) would have held the "
        "working-capital line, but usance maturities, IGST and buyer credit bunched into {q4_funding_peak}. Third, "
        "hedge averaging sales one fixing at a time, not with a midpoint flip, and size MCX on a weekly-close beta "
        "({q6_beta_w}), never the daily {q6_beta}. Fourth, keep the "
        "stops but know their cost: {worst_tid} hit its drawdown stop on {q10_stop_date}, which bars new exposure in "
        "the grade, so my stops would have refused {q15_blocked_id}, same grade, on {q15_blocked_date} — and "
        "{q15_blocked_id} finished {q15_blocked_pnl}. Stops are insurance, not forecasts.",
        ("outputs/tables/pnl_sensitivity_sign_robustness.csv", "outputs/tables/margin_liquidity_limit_grid.csv",
         "outputs/tables/margin_liquidity_policy_limits.csv", "outputs/reports/post_mortem.md",
         "outputs/reports/risk_policy_memo.md"),
    ),
    Question(
        "garch", "Volatility model",
        REQUIRED_QUESTIONS[0],
        "Because a {q16_window}-day window answers \"how volatile was last year?\" and a desk needs \"how volatile is "
        "tomorrow?\". At the {ath_date} all-time high, GARCH(1,1) forecast {q16_g_ath} a day against "
        "{q16_h_ath} for the window; the next day's {q16_ret} log fall was {q16_z_g}σ for GARCH and {q16_z_h}σ for the "
        "window. "
        "Not a crystal ball, though. On the alert rule I declared before looking — each method's {q16_pctl} "
        "percentile over {q16_ref} — the window crossed on {q16_h_cross}, {q16_lead} trading days before GARCH "
        "({q16_g_cross}). Entering the crash fortnight GARCH sat below both windows ({q16_g_cf} against {q16_h_cf} "
        "and {q16_h60_cf}). On the book it broke {q16_exc_g} times in {q16_n} days against the window's {q16_exc_h} "
        "(expected {q16_exp}); Kupiec accepts {q16_kmin} to {q16_kmax}, so {q16_n} days cannot rank them. On a fixed "
        "long over {q16_unit_n} days neither fails; in {q16_fail_year} alone the window fails and GARCH does not. "
        "GARCH sizes today's risk; the long window is my floor.",
        ("outputs/tables/var_summary.csv", "outputs/tables/var_lead_lag.csv", "outputs/tables/kupiec.csv",
         "docs/40_var_garch.md"),
    ),
    Question(
        "ml", "Price prediction",
        REQUIRED_QUESTIONS[1],
        "Because a physical desk earns on structure, not on calling the tape, and this book shows it. The money is "
        "landed cost against a domestic anchor, grade, freight and tenor; flat price is hedged. From the {e1_start} "
        "high to the {e1_end} trough the MCX legs offset {q7_offset} of the physical's LME loss, and lifetime "
        "flat-price P&L was {q9_lme}. Nor would the data carry one: {window_year} was one regime-shift year with a "
        "handful of independent shocks, which a model fitted on {q17_fit_from}–{q17_fit_to} had never seen. My one "
        "exogenous signal — {q14_n_headlines} real headlines over {q17_n_weeks} weeks, scored with VADER — showed "
        "no evidence of a lead: {q17_n_sig} of {q17_n_lead} lead tests significant, against {q17_exp_fp} expected "
        "by chance. A neural net on that would fit noise. "
        "I spent the quant effort where it changes a decision: GARCH to size risk, Monte Carlo for joint shocks, a "
        "logistic score for credit limits.",
        ("outputs/tables/sentiment_summary.csv", "outputs/tables/adverse_events_summary.csv",
         "docs/70_sentiment_overlay.md", "docs/spec/MASTER_SPEC_V3.md"),
    ),
)

HEADER = """# Interview pack — the {n_q} toughest questions a physical metal trader would ask

**{desk_name}** · aluminium scrap into India, {window_start} to {window_end}; {n_trades} tickets, {book_mt} MT in {book_boxes} containers.

> **{sim_label}.** Counterparties, vessels, trades and events are simulated. LME prices are DIRECT (LME official prices via Westmetall); USD/INR and MCX are PROXY; freight levels and the grade-factor path are hindsight reconstructions. Every parameter carries a DIRECT, PROXY or ASSUMPTION flag in `config/params/`.

> **Where the questions come from.** The spec's quality bar (Table 8) asks for "the original {n_authored}" plus two named questions, but never lists the {n_authored}. Questions {first_authored_no} to {last_authored_no} were therefore written for this pack, one per area a physical desk head would probe. Questions {first_required_no} and {last_required_no} are the spec's, verbatim.

> **The headline, always with its band.** The book made **{book_pnl}** to {horizon_end} ({book_pnl_mt}/MT; {book_pnl_we} at {window_end}). It is **not sign-robust**: across the registered `{anchor_key}` grid it runs **{band_lo} to {band_hi}**, break-even {band_be}{NB}₹/MT inside the grid. Every answer that quotes the book's P&L quotes this band.

> **How to read the numbers.** Every number below is filled from the published tables by `desk/reporting/interview_pack.py` when the pack is built; none is typed by hand. The qualitative claims ("the only negative", "worse than every path") are re-tested against the data first, and the build fails if one no longer holds. Sources follow each answer.
{recon_note}"""

FOOTER = """## What this pack does and doesn't tell you

It shows how this simulated book would be defended under questioning, with every figure traceable to a table and every weakness stated next to the number it weakens. It does not show that the trades were real (they are not), that the anchor premium or grade path was knowable in {window_year} (it was not verified, and the grade path uses later data), or that the risk models forecast anything: they size and stress the risk they are given. Answers are capped at {max_words} words; the docs they cite carry the detail.
"""


# ------------------------------------------------------------------------------------------------ sources
def load_sources() -> dict[str, object]:
    """Every file this stage reads, loaded once with only the columns it needs (low-memory machine)."""
    T, P = TABLES_DIR, PROCESSED_DIR
    book_cols = ["trade_id", "trade_date", "lane", "grade", "quantity_mt", "boxes", "parity_week_end", "incoterm",
                 "freight_risk_layer", "freight_stop_loss_usd_box", "purchase_pricing_type", "purchase_lme_reference",
                 "purchase_factor_frac", "payment_instrument", "usance_days", "usance_maturity_dates", "buyer_ids",
                 "sale_contract_dates", "sale_due_dates_with_events", "event_quality", "mcx_hedge_ratio_target",
                 "fx_forward_lines", "fx_hedge_frac_target", "fx_cover_frac_of_fixed_purchase", "grade_factor_at_trade_date",
                 "net_arb_conv18k_inr_t"]
    parity_cols = ["week_end", "value_date", "grade", "lane", "in_window", "lme_3m_usd_t", "usdinr_goods",
                   "grade_factor", "cfr_usd_t", "goods_inr_t", "bcd_inr_t", "sws_inr_t", "port_inr_t",
                   "finance_inr_t", "igst_finance_inr_t", "landed_inr_t", "recovery_frac", "anchor_inr_t",
                   "net_arb_inr_t", "net_arb_usd_t", "margin_threshold_inr_t", "open_base", "open_pit_mix",
                   "open_conv18k", "trade_eligible", "net_arb_pit_mix_inr_t", "net_arb_conv18k_inr_t"]
    return {
        "att": pd.read_csv(T / "attribution_daily.csv",
                           usecols=["date", "trade_id", *PNL_BUCKETS, "residual", "cum_pnl_inr"]),
        "leg": pd.read_csv(T / "attribution_leg_daily.csv", usecols=["trade_id", "leg_id", "roll_term_structure"]),
        "robust": pd.read_csv(T / "pnl_sensitivity_sign_robustness.csv"),
        "sens": pd.read_csv(T / "pnl_sensitivity_summary.csv", usecols=["case", "grade_spread", "cum_pnl_horizon_inr"]),
        "nd_timing": pd.read_csv(T / "new_deal_timing.csv",
                                 usecols=["trade_id", "new_deal_on_trade_date_inr", "new_deal_after_trade_date_inr"]),
        "controls": pd.read_csv(T / "pnl_controls.csv", usecols=["check", "status"]),
        "book": pd.read_csv(T / "trade_book.csv", dtype=str, usecols=book_cols),
        "parity": pd.read_csv(T / "parity_weekly.csv", usecols=parity_cols),
        "mkt": pd.read_csv(P / "market_daily.csv", usecols=["date", "lme_cash_usd_t", "usdinr"]),
        "freight": pd.read_csv(P / "freight_weekly.csv",
                               usecols=["week_end", "freight_jea_nsa_usd_t", "freight_usec_mun_usd_t"]),
        "prov": pd.read_csv(P / "series_provenance.csv", usecols=["column", "flag"]),
        "events": pd.read_csv(T / "adverse_events_summary.csv", usecols=["event", "metric", "value"], dtype=str),
        "ts": pd.read_csv(T / "term_structure_weekly.csv",
                          usecols=["week_end", "in_window", "lme_cash_3m_spread_usd_t", "structure",
                                   "structure_effect_buyer_usd_t"]),
        "rolls": pd.read_csv(T / "mcx_roll_carry.csv", usecols=["trade_id", "roll_date", "roll_pnl_inr",
                                                                "lme_curve_roll_pnl_inr"]),
        "basis": pd.read_csv(T / "mcx_basis_risk.csv", usecols=["metric", "scope", "value"]),
        "mc": pd.read_csv(T / "mc_summary.csv", usecols=["snapshot_id", "snapshot_date", "variant", "n_paths",
                                                         "horizon_bdays", "var99_inr"]),
        "stress": pd.read_csv(T / "mc_stress_scenarios.csv",
                              usecols=["snapshot_id", "snapshot_date", "scenario_id", "lme_cash_logret",
                                       "freight_logret", "pnl_inr", "beyond_every_mc_path"]),
        "snaps": pd.read_csv(T / "mc_snapshots.csv", usecols=["snapshot_id", "snapshot_date", "trades_on_book"]),
        "var": pd.read_csv(T / "var_summary.csv", usecols=["metric", "scope", "value", "note"], dtype=str),
        "leadlag": pd.read_csv(T / "var_lead_lag.csv",
                               usecols=["series", "episode", "percentile", "base_percentile", "method", "alert_date",
                                        "garch_lead_trading_days", "reference_period"]),
        "kupiec": pd.read_csv(T / "kupiec.csv", usecols=["sample", "method", "n", "exceptions", "expected",
                                                         "kupiec_accept_min", "kupiec_accept_max", "verdict"]),
        "credit": pd.read_csv(T / "credit_scores.csv",
                              usecols=["rank_riskiest_first", "cp_id", "cp_name", "credit_limit_inr",
                                       "pd_model_annual_frac", "band_final", "recommended_limit_inr",
                                       "credit_utilisation_peak_to_date_frac",
                                       "contracted_utilisation_peak_to_date_frac"]),
        "bookings": pd.read_csv(T / "credit_tracker_bookings.csv",
                                usecols=["contract_date", "trade_id", "sale_id", "cp_id", "advance_reliance_multiple",
                                         "band_policy_verdict"]),
        "n_synth": len(pd.read_csv(T / "credit_synthetic_training_data.csv", usecols=[0])),
        "liq": pd.read_csv(T / "margin_liquidity_summary.csv", usecols=["metric", "scope", "value", "note"], dtype=str),
        "grid": pd.read_csv(T / "margin_liquidity_limit_grid.csv", usecols=["facility", "limit_inr"]),
        "grid_full": pd.read_csv(T / "margin_liquidity_limit_grid.csv",
                                 usecols=["facility", "limit_inr", "registered", "days_limit_breach"]),
        "mcx_beta": pd.read_csv(T / "var_mcx_beta.csv", usecols=["sampling", "beta", "t_vs_one",
                                                                 "unhedged_frac_of_parity_move"]).set_index("sampling"),
        "facility": pd.read_csv(T / "margin_liquidity_facility.csv", usecols=["metric", "value"], dtype=str),
        "limits": pd.read_csv(T / "margin_liquidity_policy_limits.csv",
                              usecols=["limit_id", "limit_value", "days_breached", "first_breach", "book_verdict"],
                              dtype=str),
        "sent": pd.read_csv(T / "sentiment_summary.csv", usecols=["metric", "value"]),
        "params": config.params_frame()[["key", "flag", "verify"]],
        "recon": recon_status.status(),
        "post_mortem_md": (REPORTS_DIR / "post_mortem.md").read_text(encoding="utf-8")
        if (REPORTS_DIR / "post_mortem.md").exists() else "",
    }


# ------------------------------------------------------------------------------------------------ small getters
def _one(df: pd.DataFrame, **eq) -> pd.Series:
    m = df
    for k, v in eq.items():
        m = m[m[k] == v]
    if len(m) != 1:
        raise KeyError(f"expected one row for {eq}, found {len(m)}")
    return m.iloc[0]


def _metric(df: pd.DataFrame, metric: str, scope: str | None = None, col: str = "value"):
    eq = {"metric": metric} if scope is None else {"metric": metric, "scope": scope}
    return _one(df, **eq)[col]


def _f(x) -> float:
    return float(str(x).replace(",", ""))


def _split(x, sep: str = "|") -> list[str]:
    return [p.strip() for p in str(x).split(sep) if p.strip() and p.strip().lower() != "nan"]


def _final_by_trade(att: pd.DataFrame) -> pd.DataFrame:
    """Lifetime bucket sums per ticket (BOOK rows excluded: attribution_daily has no scope column)."""
    t = att[att["trade_id"] != "BOOK"]
    return t.groupby("trade_id")[[*PNL_BUCKETS, "residual"]].sum()


# ------------------------------------------------------------------------------------------------ raw facts
def _raw_book(src: Mapping) -> dict:
    att, book, robust = src["att"], src["book"], src["robust"]
    bk = att[att["trade_id"] == "BOOK"].sort_values("date")
    horizon = bk[bk["date"] == str(HORIZON_END)]
    window = bk[bk["date"] == str(WINDOW_END)]
    anc = _one(robust, param_key=ANCHOR_KEY)
    by_trade = _final_by_trade(att)
    return {
        "book_pnl": float(horizon["cum_pnl_inr"].iloc[0]),
        "book_pnl_we": float(window["cum_pnl_inr"].iloc[0]),
        "book_mt": book["quantity_mt"].map(_f).sum(),
        "book_boxes": book["boxes"].map(_f).sum(),
        "n_trades": len(book),
        "band_lo": float(anc["pnl_min_inr"]),
        "band_hi": float(anc["pnl_max_inr"]),
        "band_be": float(anc["breakeven_value"]),
        "band_be_inside": str(anc["breakeven_inside_band"]) == "True",
        "band_sign_robust": str(anc["sign_robust_within_band"]) == "True",
        "buckets": by_trade[PNL_BUCKETS].sum().to_dict(),
        "by_trade": by_trade,
        "trade_pnl": by_trade[PNL_BUCKETS].sum(axis=1),
    }


def _raw_parity(src: Mapping, book_raw: dict) -> dict:
    book, pw, mkt = src["book"], src["parity"], src["mkt"]
    first = book.sort_values("trade_date").iloc[0]
    row = _one(pw, week_end=first["parity_week_end"], grade=first["grade"], lane=first["lane"])
    m = _one(mkt, date=row["value_date"])
    bcd_s, bcd_p, sws = (config.value(k) for k in ("bcd_scrap_hs7602", "bcd_primary_al_hs7601", "sws_rate_on_bcd"))
    win = pw[pw["in_window"]]
    anchor = float(row["anchor_inr_t"])
    return {
        "first_tid": first["trade_id"], "first_grade": first["grade"], "first_lane": first["lane"],
        "first_trade_date": first["trade_date"], "first_gf_td": _f(first["grade_factor_at_trade_date"]),
        "q1_week": row["week_end"], "q1_cfr": row["cfr_usd_t"], "q1_lme3m": row["lme_3m_usd_t"],
        "q1_gf": row["grade_factor"], "q1_fx": row["usdinr_goods"], "q1_goods": row["goods_inr_t"],
        "q1_duty": row["bcd_inr_t"] + row["sws_inr_t"], "q1_port": row["port_inr_t"],
        "q1_fin": row["finance_inr_t"] + row["igst_finance_inr_t"], "q1_landed": row["landed_inr_t"],
        "q1_recovery": row["recovery_frac"], "q1_anchor": anchor, "q1_na": row["net_arb_inr_t"],
        "q1_na_usd": row["net_arb_usd_t"], "q1_hurdle": row["margin_threshold_inr_t"],
        "q1_na_pit": row["net_arb_pit_mix_inr_t"], "q1_na_conv": row["net_arb_conv18k_inr_t"],
        "q1_row_eligible": bool(row["trade_eligible"]) and bool(row["open_pit_mix"]) and bool(row["open_conv18k"]),
        "q1_bcd_rate": bcd_s, "q1_bcd_primary": bcd_p, "q1_sws": sws,
        "q1_wedge": float(m["lme_cash_usd_t"]) * float(m["usdinr"]) * (bcd_p - bcd_s) * (1 + sws),
        "q1_igst_itc": bool(config.value("igst_itc_available")),
        "q1_n_cases": len(win), "q1_n_elig": int(win["trade_eligible"].sum()), "q1_n_open": int(win["open_base"].sum()),
        "rec_by_grade": pw.groupby("grade")["recovery_frac"].agg(["min", "max"]),
        "q2_rec_point": 0.01 * anchor,
    }


def _raw_grade(src: Mapping, br: dict) -> dict:
    sens, book = src["sens"], src["book"]
    formula = book[book["purchase_pricing_type"] == "LME_M1_AVG"]
    grade_by_trade = br["by_trade"]["grade_spread"]
    buckets = pd.Series(br["buckets"]).sort_values(ascending=False)
    return {
        "q2_formula_factors": sorted(formula["purchase_factor_frac"].map(_f)),
        "q2_grade": br["buckets"]["grade_spread"],
        "q2_grade_rank": list(buckets.index).index("grade_spread") + 1,
        "q2_pit_pnl": float(_one(sens, case="grade_mix_pit_repriced")["cum_pnl_horizon_inr"]),
        "q2_pit_grade": float(_one(sens, case="grade_mix_pit_repriced")["grade_spread"]),
        "q2_lag1_pnl": float(_one(sens, case="grade_mix_lag1_repriced")["cum_pnl_horizon_inr"]),
        "q2_lag3_pnl": float(_one(sens, case="grade_mix_lag3_repriced")["cum_pnl_horizon_inr"]),
        "q2_negative_grade_ids": sorted(grade_by_trade[grade_by_trade < 0].index),
    }


def _raw_freight(src: Mapping, br: dict) -> dict:
    book, fw, ev, stress, snaps = src["book"], src["freight"], src["events"], src["stress"], src["snaps"]
    fob, cfr = book[book["incoterm"] == "FOB"], book[book["incoterm"] == "CFR"]
    wk = fw[(fw["week_end"] >= str(WINDOW_START)) & (fw["week_end"] <= str(WINDOW_END))].sort_values("week_end")
    ratio = fw["freight_jea_nsa_usd_t"] / fw["freight_usec_mun_usd_t"]
    fr = _one(stress, snapshot_id=MC_SNAP_ATH, scenario_id="freight_plus_40pct")  # scenario id, not a number
    return {
        "q3_fob_ids": list(fob["trade_id"]), "q3_n_cfr": len(cfr),
        "q3_fob_layers": set(fob["freight_risk_layer"]), "q3_cfr_layers": set(cfr["freight_risk_layer"].fillna("")),
        "q3_stops": list(fob["freight_stop_loss_usd_box"].map(_f)),
        "q3_fall_usec": wk["freight_usec_mun_usd_t"].iloc[-1] / wk["freight_usec_mun_usd_t"].iloc[0] - 1,
        "q3_fall_jea": wk["freight_jea_nsa_usd_t"].iloc[-1] / wk["freight_jea_nsa_usd_t"].iloc[0] - 1,
        "q3_fixture_cost": _f(_one(ev, event="E3_LOGISTICS_CREDIT", metric="fixture_timing_cost_lifetime_inr")["value"]),
        "q3_freight_bucket": br["buckets"]["freight"],
        "q3_ratio_min": float(ratio.min()), "q3_ratio_max": float(ratio.max()),
        "q3_shock": float(np.expm1(fr["freight_logret"])), "q3_stress": float(fr["pnl_inr"]),
        "ath1_date": fr["snapshot_date"],
        "ath1_trades": str(_one(snaps, snapshot_id=MC_SNAP_ATH)["trades_on_book"]).split(),
    }


def _raw_funding(src: Mapping) -> dict:
    book, liq, grid = src["book"], src["liq"], src["grid"]
    usance = book[book["payment_instrument"] == "LC_USANCE"]
    covered = 0
    for _, r in usance.iterrows():
        if max(_split(r["sale_due_dates_with_events"])) < min(_split(r["usance_maturity_dates"])):
            covered += 1

    def lm(metric: str, scope: str = "book") -> str:
        return str(_metric(liq, metric, scope))

    return {
        "q4_n_sight": int((book["payment_instrument"] == "LC_SIGHT").sum()), "q4_n_usance": len(usance),
        "q4_usance_days": sorted({int(_f(x)) for x in usance["usance_days"]}),
        "q4_n_usance_covered": covered,
        "q4_wc_limit": _f(lm("fb_limit_inr", "facility")), "q4_buffer": _f(lm("min_cash_buffer_inr", "facility")), "q4_lc_limit": _f(lm("lc_limit_inr", "facility")),
        "q4_funding_peak": _f(lm("funding_need_total_inr_max")),
        "q4_funding_date": _note_date(liq, "funding_need_total_inr_max"),
        "q4_buffer_days": int(_f(lm("days_buffer_breach"))), "q4_fb_days": int(_f(lm("days_fb_limit_breach"))),
        "q4_lc_peak": _f(lm("lc_outstanding_inr_max")), "q4_lc_days": int(_f(lm("days_lc_limit_breach"))),
        "q4_wc_needed": float(_one(grid, facility="FUND_BASED_WC_MIN_NO_BREACH")["limit_inr"]),
        "q4_lc_needed": float(_one(grid, facility="NON_FUND_LC_MIN_NO_BREACH")["limit_inr"]),
        "q4_interest": _f(lm("interest_accrued_inr_final")),
        "q4_cash_min": _f(lm("cash_balance_inr_min")),
        "q4_plan_week": str(_one(src["facility"], metric="plan_parity_week_end")["value"]),
    }


def _note_date(liq: pd.DataFrame, metric: str) -> str:
    """Peak dates in margin_liquidity_summary.csv live in the note column ("on 2022-07-20")."""
    note = str(_one(liq, metric=metric, scope="book")["note"])
    m = re.search(r"\d{4}-\d{2}-\d{2}", note)
    if not m:
        raise ValueError(f"no date in the note of {metric}: {note!r}")
    return m.group(0)


def _raw_structure(src: Mapping, br: dict) -> dict:
    book, ts, rolls, leg = src["book"], src["ts"], src["rolls"], src["leg"]
    formula = book[book["purchase_pricing_type"] == "LME_M1_AVG"]
    tw = ts[ts["in_window"]]
    g_legs = leg[leg["trade_id"] != "BOOK"]
    return {
        "q5_formula_ids": list(formula["trade_id"]), "q5_formula_refs": set(formula["purchase_lme_reference"]),
        "q5_spread_min": float(tw["lme_cash_3m_spread_usd_t"].min()),
        "q5_spread_max": float(tw["lme_cash_3m_spread_usd_t"].max()),
        "q5_n_contango": int((tw["structure"] == "CONTANGO").sum()),
        "q5_n_backwardation": int((tw["structure"] == "BACKWARDATION").sum()), "q5_n_weeks": len(tw),
        "q5_effect_max": float(tw["structure_effect_buyer_usd_t"].abs().max()),
        "q5_n_rolls": len(rolls), "q5_n_roll_gains": int((rolls["roll_pnl_inr"] > 0).sum()),
        "q5_roll_pnl": float(rolls["roll_pnl_inr"].sum()), "q5_roll_lme": float(rolls["lme_curve_roll_pnl_inr"].sum()),
        "q5_g": br["buckets"]["roll_term_structure"],
        "q5_g_funding": float(g_legs.loc[g_legs["leg_id"] == "FUNDING", "roll_term_structure"].sum()),
        "q5_g_mcx": float(g_legs.loc[g_legs["leg_id"].str.startswith("MCX:"), "roll_term_structure"].sum()),
    }


def _raw_basis(src: Mapping, br: dict) -> dict:
    b, mc, var, mb = src["basis"], src["mc"], src["var"], src["mcx_beta"]

    def bm(metric: str) -> float:
        return float(_metric(b, metric, "BOOK"))

    def v99(snap: str, variant: str) -> float:
        return float(_one(mc, snapshot_id=snap, variant=variant)["var99_inr"])

    return {
        "q6_beta": bm("unit_beta_beta"), "q6_beta_se": bm("unit_beta_beta_se"), "q6_beta_t": bm("unit_beta_beta_t_vs_one"),
        "q6_r2": bm("unit_beta_beta_r2"), "q6_n": bm("unit_beta_beta_n_days"),
        "q6_open": bm("unit_beta_unhedged_frac_at_beta"),
        "q6_worst": bm("per_trade_pnl_change_worst_inr"), "q6_best": bm("per_trade_pnl_change_best_inr"),
        "q6_book": abs(bm("book_pnl_change_vs_base_inr")),
        "q6_basis_bucket_abs": float(src["att"]["cross_exchange_basis"].abs().sum()),
        "q6_apr_base": v99(MC_SNAP_APR, "normal_window"), "q6_apr_basis": v99(MC_SNAP_APR, "normal_window_mcx_basis"),
        "q6_jul_base": v99(MC_SNAP_JUL, "normal_window"), "q6_jul_basis": v99(MC_SNAP_JUL, "normal_window_mcx_basis"),
        "q6_var_beta": _f(_metric(var, "garch_var_mcx_beta_sensitivity_mean", "book_window")),
        "q6_var_base": _f(_metric(var, "var_mean_garch", "book_window")),
        "q6_var_beta_w": _f(_metric(var, "garch_var_mcx_beta_weekly_sensitivity_mean", "book_window")),
        "q6_beta_daily_tab": float(mb.at["daily", "beta"]),
        "q6_beta_w": float(mb.at["weekly", "beta"]), "q6_beta_w_t": float(mb.at["weekly", "t_vs_one"]),
        "q6_open_w": float(mb.at["weekly", "unhedged_frac_of_parity_move"]),
        "q6_beta_ll": float(mb.at["lead_lag", "beta"]), "q6_beta_ll_t": float(mb.at["lead_lag", "t_vs_one"]),
        "mc_h": int(_one(mc, snapshot_id=MC_SNAP_APR, variant="normal_window")["horizon_bdays"]),
        "n_paths": int(_one(mc, snapshot_id=MC_SNAP_APR, variant="normal_window")["n_paths"]),
        "apr_date": _one(mc, snapshot_id=MC_SNAP_APR, variant="normal_window")["snapshot_date"],
        "jul_date": _one(mc, snapshot_id=MC_SNAP_JUL, variant="normal_window")["snapshot_date"],
    }


def _ev(src: Mapping, event: str, metric: str) -> str:
    return str(_one(src["events"], event=event, metric=metric)["value"])


def _raw_hedge(src: Mapping) -> dict:
    book, limits = src["book"], src["limits"]
    hr = book.set_index("trade_id")["mcx_hedge_ratio_target"].map(_f)
    common = float(hr.mode().iloc[0])
    band = [float(x) for x in re.split(r"[-–]", str(_one(limits, limit_id="MCX_HEDGE_RATIO")["limit_value"]))]
    outside = hr[(hr < band[0]) | (hr > band[1])]
    full = hr[(hr != common) & (hr >= band[0]) & (hr <= band[1])]
    e1 = "E1_LME_CRASH"
    nu = _one(limits, limit_id="NET_UNHEDGED_MT")
    return {
        "q7_hr_common": common, "q7_n_common": int((hr == common).sum()),
        "q7_full_ids": list(full.index), "q7_hr_full": sorted(set(full)),
        "q7_low_ids": list(outside.index), "q7_hr_low": sorted(set(outside)), "q7_band": band,
        "q7_band_breach_ids": _split(_one(limits, limit_id="MCX_HEDGE_RATIO")["first_breach"]),
        "q7_roll_days": int(config.value("mcx_roll_days_before_expiry")),
        "q7_roll_verdict": str(_one(limits, limit_id="MCX_ROLL")["book_verdict"]),
        "q7_roll_breaches": int(_f(_one(limits, limit_id="MCX_ROLL")["days_breached"])),
        "e1_start": _ev(src, e1, "window_start"), "e1_end": _ev(src, e1, "window_end"),
        "q7_e1_move": _f(_ev(src, e1, "lme_change_frac")),
        "q7_phys": _f(_ev(src, e1, "lme_flat_physical_inr")), "q7_mcx": _f(_ev(src, e1, "lme_flat_mcx_inr")),
        "q7_offset": _f(_ev(src, e1, "hedge_offset_frac")), "q7_benefit": _f(_ev(src, e1, "hedge_benefit_inr")),
        "q7_nu_limit": _f(nu["limit_value"]), "q7_nu_days": int(_f(nu["days_breached"])),
    }


def _raw_fx(src: Mapping, br: dict) -> dict:
    book, limits, var = src["book"], src["limits"], src["var"]
    cover = book.set_index("trade_id")["fx_cover_frac_of_fixed_purchase"].map(_f)
    target = book.set_index("trade_id")["fx_hedge_frac_target"].map(_f)
    min_cover = float(config.value("policy_fx_forward_cover_min_frac"))
    low = cover[cover < min_cover]
    e2 = "E2_INR_DEPRECIATION"
    return {
        "q8_n_lines": int(book["fx_forward_lines"].map(_f).sum()),
        "q8_low_ids": list(low.index), "q8_low_cover": float(low.min()) if len(low) else float("nan"),
        "q8_min_cover": min_cover, "q8_below_target_ids": list(target[target < 1].index), "q8_breach_ids": _split(_one(limits, limit_id="FX_COVER")["first_breach"]),
        "e2_start": _ev(src, e2, "window_start"), "e2_end": _ev(src, e2, "window_end"),
        "q8_fx_start": _f(_ev(src, e2, "usdinr_start")), "q8_fx_end": _f(_ev(src, e2, "usdinr_end")),
        "q8_fx_move": _f(_ev(src, e2, "usdinr_change_frac")),
        "q8_fwd": _f(_ev(src, e2, "fx_forwards_inr")), "q8_usd_flows": _f(_ev(src, e2, "fx_physical_usd_flows_inr")),
        "q8_offset": _f(_ev(src, e2, "forward_offset_frac_vs_usd_flows")), "q8_mcx": _f(_ev(src, e2, "fx_mcx_inr")),
        "q8_fx_bucket": br["buckets"]["fx"],
        "q8_var_pf": _f(_metric(var, "garch_var_fx_physical_forwards_standalone_mean", "book_window")),
        "q8_var_mcx": _f(_metric(var, "garch_var_fx_mcx_leg_standalone_mean", "book_window")),
        "q8_var_net": _f(_metric(var, "garch_var_fx_net_mean", "book_window")),
    }


def _raw_attribution(src: Mapping, br: dict) -> dict:
    nd, controls, recon = src["nd_timing"], src["controls"], src["recon"]
    total = sum(br["buckets"].values())
    return {
        "q9_residual": float(src["att"]["residual"].abs().max()),
        "q9_controls_all_pass": bool(controls["status"].isin(["PASS", "INFO"]).all())
        and bool((controls["status"] == "PASS").any()),
        "q9_recon": recon, "q9_recon_status": recon.status,
        "q9_cells": recon.n_recalculated, "q9_fail": recon.n_check_failures, "q9_scoreboard": recon.scoreboard,
        "q9_nd": br["buckets"]["new_deal"], "q9_nd_share": br["buckets"]["new_deal"] / total,
        "q9_nd_largest": max(br["buckets"], key=br["buckets"].get) == "new_deal",
        "q9_nd_td": float(_one(nd, trade_id="BOOK")["new_deal_on_trade_date_inr"]),
        "q9_nd_later": float(_one(nd, trade_id="BOOK")["new_deal_after_trade_date_inr"]),
        "q9_lme": br["buckets"]["lme_flat"], "q9_bucket_total": total,
    }


def _raw_worst(src: Mapping, br: dict) -> dict:
    book, limits = src["book"], src["limits"]
    tp = br["trade_pnl"]
    wid = str(tp.idxmin())
    t = _one(book, trade_id=wid)
    b = br["by_trade"].loc[wid]
    sale = min(_split(t["sale_contract_dates"]))
    buyer = _split(t["buyer_ids"])[0]
    same_buyer = book[(book["trade_id"] != wid) & (book["buyer_ids"].map(lambda b: buyer in _split(b)))]
    freed = [d for dues in same_buyer["sale_due_dates_with_events"] for d in _split(dues)
             if t["trade_date"] <= d <= sale]
    return {
        "worst_tid": wid, "q10_qty": _f(t["quantity_mt"]), "q10_grade": t["grade"], "q10_lane": t["lane"],
        "q10_date": t["trade_date"], "q10_pricing": t["purchase_pricing_type"], "q10_factor": _f(t["purchase_factor_frac"]),
        "q10_na_conv": _f(t["net_arb_conv18k_inr_t"]),
        "q10_pnl": float(tp[wid]), "q10_pnl_mt": float(tp[wid]) / _f(t["quantity_mt"]),
        "q10_nd": float(b["new_deal"]), "q10_g": float(b["roll_term_structure"]), "q10_grade_b": float(b["grade_spread"]),
        "q10_lme": float(b["lme_flat"]), "q10_events": float(b["demurrage_penalty"]),
        "q10_sale_date": sale, "q10_line_freed_before_sale": bool(freed), "q10_sale_lag": (pd.Timestamp(sale) - pd.Timestamp(t["trade_date"])).days,
        "q10_event_quality": str(t["event_quality"]),
        "q10_conv_rank": int(book["net_arb_conv18k_inr_t"].map(_f).rank(method="min")[t.name]),
        "q10_stop": str(_one(limits, limit_id="STOP_TICKET_HARD")["first_breach"]),
        "q10_nd_share_of_losses": float(b["new_deal"]) / -float(b[["roll_term_structure", "grade_spread", "lme_flat",
                                                                   "demurrage_penalty"]].sum()),
    }


def _raw_credit(src: Mapping) -> dict:
    cs, bk, stress = src["credit"], src["bookings"], src["stress"]
    top = _one(cs, rank_riskiest_first=1)
    rid = str(top["cp_id"])
    adv = bk[(bk["cp_id"] == rid) & (bk["advance_reliance_multiple"] > 0)].sort_values("contract_date")
    d = _one(stress, snapshot_id=MC_SNAP_JUL, scenario_id="buyer_default")
    dl = _one(stress, snapshot_id=MC_SNAP_JUL, scenario_id="buyer_default_with_lme_minus_15pct_memo")
    return {
        "rjk_id": rid, "q11_name": str(top["cp_name"]), "q11_limit": float(top["credit_limit_inr"]),
        "q11_util": float(top["credit_utilisation_peak_to_date_frac"]),
        "q11_contracted": float(top["contracted_utilisation_peak_to_date_frac"]),
        "q11_adv": list(adv["advance_reliance_multiple"]),
        "q11_n_rjk_bookings": int((bk["cp_id"] == rid).sum()),
        "q11_pd": float(top["pd_model_annual_frac"]), "q11_band": str(top["band_final"]),
        "q11_new_limit": float(top["recommended_limit_inr"]), "q11_n_synth": int(src["n_synth"]),
        "q11_n_outside": int((bk["band_policy_verdict"] == "OUTSIDE_BAND_POLICY").sum()), "q11_n_bookings": len(bk),
        "q11_default": float(d["pnl_inr"]), "q11_default_lme": float(dl["pnl_inr"]),
        "q11_default_beyond": bool(d["beyond_every_mc_path"]), "q11_default_lme_beyond": bool(dl["beyond_every_mc_path"]),
        "q11_lme_shock": float(np.expm1(dl["lme_cash_logret"])),
    }


def _raw_margin(src: Mapping) -> dict:
    liq = src["liq"]

    def lm(metric: str, scope: str) -> str:
        return str(_metric(liq, metric, scope))

    cf, mf = "CRASH_FORTNIGHT", "MARGIN_FORTNIGHT"
    return {
        "q12_cf_start": lm("window_start", cf), "q12_cf_end": lm("window_end", cf),
        "q12_cf_move": _f(lm("lme_cash_return_frac", cf)), "q12_cf_vm": _f(lm("vm_actual_sum_inr", cf)),
        "q12_margin_peak": _f(lm("margin_cash_deployed_inr_max", "book")),
        "q12_margin_date": _note_date(liq, "margin_cash_deployed_inr_max"),
        "q12_mf_start": lm("window_start", mf), "q12_mf_end": lm("window_end", mf),
        "q12_mf_move": _f(lm("lme_cash_return_frac", mf)), "q12_mf_net": _f(lm("net_margin_cash_actual_sum_inr", mf)),
        "q12_im": _f(lm("mcx_im_inr_max", "book")), "q12_im_date": _note_date(liq, "mcx_im_inr_max"),
        "q12_stress_move": _f(lm("stress_move_frac", cf)),
        "q12_stress_call": _f(lm("extra_margin_cash_out_stressed_im_inr_max", cf)),
        "q12_stress_headroom": _f(lm("headroom_stressed_im_inr_min", cf)),
        "q12_paper": _f(lm("memo_physical_mtm_gain_end_inr", cf)),
        "q12_margin_source": -_f(lm("margin_cash_deployed_inr_on_peak_funding_day", "book")),
        "q12_cf_lots": _f(lm("mcx_lots_net_open_at_start", cf)),
    }


def _raw_policy(src: Mapping) -> dict:
    stress = src["stress"]

    def q(snap: str, sid: str = "qco_hold_demurrage") -> pd.Series:
        return _one(stress, snapshot_id=snap, scenario_id=sid)

    p = config.get("bis_qco_scrap_in_force_2022")
    return {
        "q13_in_force": bool(p.value), "q13_flag": p.flag, "q13_verified": p.verify.startswith("VERIFIED"),
        "q13_not_scrap": "did not cover scrap" in p.verify,
        "q13_delay": int(config.value("qco_stress_delay_days")),
        "q13_rej": float(config.value("qco_stress_rejection_frac")),
        "q13_loss": float(config.value("qco_stress_rejected_loss_frac")),
        "q13_ath": float(q(MC_SNAP_ATH)["pnl_inr"]), "q13_apr": float(q(MC_SNAP_APR)["pnl_inr"]),
        "q13_jul": float(q(MC_SNAP_JUL)["pnl_inr"]),
        "q13_beyond": [bool(q(s)["beyond_every_mc_path"]) for s in (MC_SNAP_ATH, MC_SNAP_APR, MC_SNAP_JUL)],
        "q13_all": float(q(MC_SNAP_JUL, "qco_hold_all_tickets_memo")["pnl_inr"]),
    }


def _raw_data(src: Mapping) -> dict:
    params, prov, sent = src["params"], src["prov"], src["sent"]
    status = params["verify"].str.extract(r"^\s*([A-Z/]+)")[0]
    return {
        "q14_n_params": len(params),
        "q14_n_direct": int((params["flag"] == "DIRECT").sum()), "q14_n_proxy": int((params["flag"] == "PROXY").sum()),
        "q14_n_assump": int((params["flag"] == "ASSUMPTION").sum()),
        "q14_n_verified": int((status == "VERIFIED").sum()), "q14_n_pending": int((status == "PENDING").sum()),
        "q14_n_partial": int((status == "PARTIAL").sum()), "q14_n_na": int((status == "N/A").sum()),
        "q14_sp_n": len(prov), "q14_sp_direct": int((prov["flag"] == "DIRECT").sum()),
        "q14_sp_proxy": int((prov["flag"] == "PROXY").sum()), "q14_sp_assump": int((prov["flag"] == "ASSUMPTION").sum()),
        "q14_n_headlines": int(_one(sent, metric="n_headlines")["value"]),
    }


def _raw_differently(src: Mapping, br: dict) -> dict:
    limits = src["limits"]
    blocked = str(_one(limits, limit_id="STOP_BLOCKED_PURCHASES")["first_breach"])
    bid, bdate = blocked.split("@")
    wid = str(_one(limits, limit_id="STOP_TICKET_HARD")["first_breach"]).split("@")[0]
    grades = src["book"].set_index("trade_id")["grade"]
    grid = src["grid_full"]
    reg = grid[(grid["facility"] == "FUND_BASED_WC") & grid["registered"]]
    above = grid[(grid["facility"] == "FUND_BASED_WC") & (grid["limit_inr"] > float(reg["limit_inr"].iloc[0]))]
    step = above.sort_values("limit_inr").iloc[0]
    return {
        "q15_wc_step": float(step["limit_inr"]), "q15_wc_step_days": int(step["days_limit_breach"]),
        "q15_wc_registered": float(reg["limit_inr"].iloc[0]), "q15_rounding": float(config.value("liq_facility_rounding_inr")),
        "q15_fb_limit_rule": str(config.get("liq_fb_wc_limit_inr").note),
        "q15_blocked_id": bid, "q15_blocked_date": bdate, "q15_blocked_pnl": float(br["trade_pnl"][bid]),
        "q15_pm_has_midpoint_flip": "midpoint flip" in src["post_mortem_md"],
        "q15_stop_tid": wid, "q15_same_grade": grades[bid] == grades[wid],
        "q15_hard_stop_unit": config.get("policy_stop_ticket_hard_inr").unit,
    }


def _raw_garch(src: Mapping) -> dict:
    var, ll, kp = src["var"], src["leadlag"], src["kupiec"]

    def vm(metric: str, scope: str = "LME") -> float:
        return _f(_metric(var, metric, scope))

    base = ll[(ll["series"] == "lme") & (ll["episode"] == "LME_MARCH_SPIKE") & (ll["base_percentile"])]
    g, h = _one(base, method="garch"), _one(base, method="hist250")
    bw = kp[kp["sample"] == "book_window"].set_index("method")
    unit = kp[kp["sample"] == "unit_lme_long_1000mt"].set_index("method")
    years = []
    for s in sorted(kp["sample"].unique()):
        m = re.fullmatch(r"unit_lme_long_1000mt_(\d{4})", s)
        if not m:
            continue
        yr = kp[kp["sample"] == s].set_index("method")
        if yr.loc["hist250", "verdict"].startswith("REJECTED") and yr.loc["garch", "verdict"] == "NOT REJECTED":
            years.append(m.group(1))
    ref = str(g["reference_period"]).split("..")
    tags = [re.fullmatch(r"lme_return_(\d{4}_\d{2}_\d{2})", m) for m in var["metric"]]
    tags = [t.group(1) for t in tags if t]
    if len(tags) != 1:
        raise KeyError(f"expected one lme_return_<date> metric in var_summary.csv, found {tags}")
    ret_tag = tags[0]
    mkt = src["mkt"]
    ath = _ev(src, "E1_LME_CRASH", "window_start")
    return {
        "q16_g_ath": vm("sigma_lme_garch_on_day_after_ath"), "q16_h_ath": vm("sigma_lme_hist250_on_day_after_ath"),
        "q16_ret": vm(f"lme_return_{ret_tag}"), "q16_z_g": vm(f"z_of_{ret_tag}_return_garch"),
        "q16_z_h": vm(f"z_of_{ret_tag}_return_hist250"), "q16_ret_date": ret_tag.replace("_", "-"),
        "q16_day_after_ath": str(mkt.loc[mkt["date"] > ath, "date"].min()),
        "q16_pctl": float(g["percentile"]), "q16_ref": (ref[0][:4], ref[1][:4]),
        "q16_g_cross": g["alert_date"], "q16_h_cross": h["alert_date"], "q16_lead": float(h["garch_lead_trading_days"]),
        "q16_g_cf": vm("sigma_lme_garch_on_crash_fortnight_start"),
        "q16_h_cf": vm("sigma_lme_hist250_on_crash_fortnight_start"),
        "q16_h60_cf": vm("sigma_lme_hist60_on_crash_fortnight_start"),
        "q16_exc_g": int(bw.loc["garch", "exceptions"]), "q16_exc_h": int(bw.loc["hist250", "exceptions"]),
        "q16_exc_h60": int(bw.loc["hist60", "exceptions"]),
        "q16_n": int(bw.loc["garch", "n"]), "q16_exp": float(bw.loc["garch", "expected"]),
        "q16_kmin": int(bw.loc["garch", "kupiec_accept_min"]), "q16_kmax": int(bw.loc["garch", "kupiec_accept_max"]),
        "q16_unit_n": int(unit.loc["garch", "n"]), "q16_fail_years": years,
        "q16_unit_verdicts": {m: str(unit.loc[m, "verdict"]) for m in ("garch", "hist250")},
        "q16_window": int(config.value("var_hist_window_base_days")),
        "ath_date": ath,
    }


def _raw_ml(src: Mapping) -> dict:
    sent = src["sent"]

    def sv(metric: str) -> float:
        return float(_one(sent, metric=metric)["value"])

    return {
        "q17_fit_from": str(HISTORY_START.year), "q17_fit_to": str(WINDOW_START.year - 1),
        "q17_n_weeks": int(sv("n_weeks")), "q17_n_lead": int(sv("n_lead_tests")),
        "q17_n_sig": int(sv("n_lead_tests_naive_5pct")), "q17_n_boot": int(sv("n_lead_tests_boot_ci_excludes_zero")),
        "q17_exp_fp": sv("expected_false_positives_naive_5pct"), "q17_n_tests_total": int(sv("n_tests_total")),
    }


def compute_raw(src: Mapping) -> dict:
    br = _raw_book(src)
    raw: dict = dict(br)
    raw.update(_raw_parity(src, br))
    raw.update(_raw_grade(src, br))
    raw.update(_raw_freight(src, br))
    raw.update(_raw_funding(src))
    raw.update(_raw_structure(src, br))
    raw.update(_raw_basis(src, br))
    raw.update(_raw_hedge(src))
    raw.update(_raw_fx(src, br))
    raw.update(_raw_attribution(src, br))
    raw.update(_raw_worst(src, br))
    raw.update(_raw_credit(src))
    raw.update(_raw_margin(src))
    raw.update(_raw_policy(src))
    raw.update(_raw_data(src))
    raw.update(_raw_differently(src, br))
    raw.update(_raw_garch(src))
    raw.update(_raw_ml(src))
    return raw


# ------------------------------------------------------------------------------------------------ claims
def check_claims(r: Mapping) -> list[str]:
    """Every qualitative word in the templates, re-tested against the data. Returns the failed claims."""
    fails: list[str] = []

    def need(ok: bool, claim: str) -> None:
        if not ok:
            fails.append(claim)

    need(not r["band_sign_robust"] and r["band_be_inside"], "headline: break-even inside the grid, not sign-robust")
    # Q1
    need(r["q1_row_eligible"], "Q1: the first trade's parity case passed all three screens")
    need(r["q1_n_open"] > r["q1_n_elig"], "Q1: base alone opens more cases than the rule")
    need(r["q1_bcd_primary"] > r["q1_bcd_rate"], "Q1: primary BCD above scrap BCD (the wedge)")
    need(r["q1_igst_itc"], "Q1: IGST taken back as input credit")
    # Q2
    need(r["q2_grade_rank"] == 2, "Q2: grade spread second only to deal margin")
    need(r["q2_pit_pnl"] < r["book_pnl"], "Q2: book falls on the point-in-time mix")
    need(r["q2_pit_grade"] < 0, "Q2: grade spread turns negative on the point-in-time mix")
    need(r["q2_negative_grade_ids"] == [r["worst_tid"]], "Q2: the worst ticket is the only negative grade spread")
    # Q3
    need(r["q3_fob_layers"] == {"UNHEDGED_STOP_LOSS"}, "Q3: every FOB ticket runs freight unhedged with a stop")
    need(r["q3_cfr_layers"] == {""}, "Q3: no CFR ticket carries a freight layer")
    need(all(s > 0 for s in r["q3_stops"]), "Q3: a stop-loss per box on every FOB ticket")
    need(r["q3_fall_usec"] < 0 and r["q3_fall_jea"] < 0, "Q3: freight fell on both lanes")
    need(r["q3_fixture_cost"] < 0, "Q3: fixing ahead of the B/L cost money")
    need(r["q3_ratio_max"] - r["q3_ratio_min"] < 1e-3, "Q3: the Gulf lane is a fixed multiple of the US lane")
    need(r["q3_stress"] < 0 and len(r["ath1_trades"]) == 1, "Q3: freight stress is a loss with only one ticket on")
    # Q4
    need(0 < r["q4_n_usance_covered"] < r["q4_n_usance"], "Q4: some but not all usance tickets are covered")
    need(r["q4_fb_days"] > 0 and r["q4_lc_days"] > 0, "Q4: both bank lines breached")
    need(pd.Timestamp(r["q4_plan_week"]).month == 2 and pd.Timestamp(r["q4_plan_week"]) < pd.Timestamp(WINDOW_START),
         "Q4: lines sized ex ante on a February plan")
    need(r["q4_wc_needed"] > r["q4_wc_limit"] and r["q4_lc_needed"] > r["q4_lc_limit"], "Q4: no-breach sizes above lines")
    # Q5
    need(r["q5_formula_refs"] == {"CASH"}, "Q5: formula purchases settle on LME cash")
    need(r["q5_n_contango"] > r["q5_n_backwardation"] > 0, "Q5: mostly contango, some backwardation")
    need(r["q5_n_roll_gains"] == r["q5_n_rolls"] > 0, "Q5: all short rolls gained")
    need(r["q5_g"] < 0 and r["q5_g_funding"] < 0 and r["q5_g_mcx"] < 0, "Q5: bucket (g) split signs")
    need(abs(r["q5_g_funding"]) > abs(r["q5_g"]) / 2, "Q5: funding is most of bucket (g)")
    need(r["q5_effect_max"] < r["q1_na_usd"], "Q5: structure effect small against the arb")
    # Q6
    need(r["q6_beta"] < 1 and r["q6_beta_t"] < -2, "Q6: mirror beta significantly below one")
    need(r["q6_basis_bucket_abs"] == 0, "Q6: bucket (b) zero on every day")
    need(r["q6_worst"] < 0 < r["q6_best"], "Q6: mirror swing is two-sided")
    need(r["q6_apr_basis"] > r["q6_apr_base"] and r["q6_jul_basis"] > r["q6_jul_base"], "Q6: basis factor lifts VaR")
    need(r["q6_var_beta"] > r["q6_var_beta_w"] > r["q6_var_base"], "Q6: VaR daily beta > weekly beta > proxy")
    need(abs(r["q6_beta_daily_tab"] - r["q6_beta"]) < 1e-6, "Q6: var_mcx_beta.csv daily beta is P3's")
    need(r["q6_beta"] < r["q6_beta_w"] < r["q6_beta_ll"] < 1, "Q6: daily beta biased down; weekly and matched higher")
    need(r["q6_open_w"] < r["q6_open"], "Q6: weekly beta leaves less open than the daily one")
    need(r["q6_beta_w_t"] < -2 < r["q6_beta_ll_t"], "Q6: weekly rejects unit beta, matched closes do not")
    need(r["q6_jul_base"] < 0.1 * r["q6_apr_base"], "Q6: the hedged book looked flat in July")
    # Q7
    need(r["q7_low_ids"] == r["q7_band_breach_ids"] and len(r["q7_low_ids"]) == 1, "Q7: one ticket outside the band")
    need(len(r["q7_full_ids"]) >= 1, "Q7: some tickets at a second in-band ratio")
    need(r["q7_roll_verdict"] == "WITHIN" and r["q7_roll_breaches"] == 0, "Q7: no roll late")
    need(r["q7_phys"] < 0 < r["q7_mcx"] and r["q7_benefit"] > 0, "Q7: hedge offset the physical loss")
    need(r["q7_nu_days"] > 0, "Q7: net unhedged limit breached")
    # Q8
    need(r["q8_low_ids"] == r["q8_breach_ids"] and len(r["q8_low_ids"]) == 1, "Q8: one ticket below the cover minimum")
    need(r["q8_fwd"] > 0 > r["q8_usd_flows"] and r["q8_mcx"] < 0, "Q8: forwards gained, payables and MCX lost")
    need(r["q8_fx_move"] > 0, "Q8: the rupee weakened")
    need(r["q8_below_target_ids"] == r["q8_low_ids"], "Q8: full cover targeted on every other ticket")
    need(r["q8_var_net"] < min(r["q8_var_pf"], r["q8_var_mcx"]), "Q8: netting hides two offsetting positions")
    # Q9
    need(r["q9_residual"] == 0 and r["q9_controls_all_pass"], "Q9: residual zero and controls pass")
    need(r["q9_recon_status"] != recon_status.VERIFIED or (r["q9_fail"] == 0 and r["q9_scoreboard"] == "PASS"),
         "Q9: a VERIFIED Excel reconciliation passes")
    need(r["q9_nd_largest"], "Q9: deal margin is the largest bucket")
    need(abs(r["q9_bucket_total"] - r["book_pnl"]) < 1.0, "Q9: buckets sum to the headline")
    need(abs(r["q9_nd_td"] + r["q9_nd_later"] - r["q9_nd"]) < 1.0, "Q9: deal-margin timing adds up")
    need(r["q9_lme"] < 0 and r["q5_g"] < 0, "Q9: flat price and carry cost money")
    # Q10
    need(r["worst_tid"] == WORST_TRADE_OF_RECORD, f"Q10: the worst ticket is still {WORST_TRADE_OF_RECORD}")
    need(r["q10_pnl"] < 0 and r["q10_pricing"] == "LME_M1_AVG", "Q10: a losing formula purchase")
    need(r["q10_nd"] > 0 and r["q10_nd_share_of_losses"] < 1, "Q10: deal margin more than eaten")
    need(r["q10_g"] < 0 and r["q10_grade_b"] < 0 and r["q10_lme"] < 0 and r["q10_events"] < 0, "Q10: four losing buckets")
    need("RADIOACTIVITY" in r["q10_event_quality"], "Q10: radiation-portal rejection")
    need(r["q10_stop"].startswith(f"{r['worst_tid']}@"), "Q10: the worst ticket fired the hard stop")
    need(r["q10_sale_lag"] > 0, "Q10: bought with no buyer")
    need(r["q10_line_freed_before_sale"], "Q10: a previous invoice to the same buyer fell due before the sale")
    need(r["q10_conv_rank"] <= 2, "Q10: a thin screen (among the two lowest conversion-stressed arbs)")
    # Q11
    need(r["rjk_id"] == RISKIEST_BUYER_OF_RECORD, f"Q11: the riskiest buyer is still {RISKIEST_BUYER_OF_RECORD}")
    need(r["q11_util"] < 1 < r["q11_contracted"], "Q11: no receivable breach, contracted over the line")
    need(len(r["q11_adv"]) == r["q11_n_rjk_bookings"] and all(a > 1 for a in r["q11_adv"]),
         "Q11: every parcel sold against an advance above the line")
    need(r["q11_new_limit"] < r["q11_limit"], "Q11: the line is cut")
    need(r["q11_default"] < 0 and r["q11_default_lme"] < r["q11_default"], "Q11: default is a loss, worse with LME down")
    need(r["q11_default_beyond"] and r["q11_default_lme_beyond"], "Q11: default worse than every path")
    # Q12
    need(r["q12_cf_move"] < 0 < r["q12_cf_vm"], "Q12: the crash paid the short hedges")
    need(r["q12_cf_lots"] < 0, "Q12: net short MCX entering the crash fortnight")
    need(pd.Timestamp(r["q12_margin_date"]).month == 3 and pd.Timestamp(r["q12_mf_start"]).month == 3,
         "Q12: the margin squeeze was in March")
    need(r["q12_mf_move"] > 0 and r["q12_mf_net"] < 0, "Q12: LME rose and margin cash went out")
    need(r["q12_stress_headroom"] < 0 and r["q12_paper"] > 0, "Q12: stress breaks headroom, cargo gain on paper")
    need(r["q12_margin_source"] > 0, "Q12: margin a net source on the peak funding day")
    # Q13
    need(r["q13_not_scrap"], "Q13: the later QCOs did not cover scrap")
    need(not r["q13_in_force"] and r["q13_flag"] == "DIRECT" and r["q13_verified"], "Q13: no scrap QCO in 2022, verified")
    need(max(r["q13_ath"], r["q13_apr"], r["q13_jul"]) < 0, "Q13: the QCO stress is a loss on every snapshot")
    need(r["q13_beyond"] == [False, True, True], "Q13: QCO worse than every path on the last two snapshots only")
    # Q15
    need(r["q15_blocked_pnl"] > 0, "Q15: the refused ticket made money")
    need(r["q15_stop_tid"] == r["worst_tid"] and r["q15_same_grade"], "Q15: the refused ticket is the stopped grade")
    need("drawdown" in r["q15_hard_stop_unit"], "Q15: the hard stop is a drawdown stop")
    need(r["q15_pm_has_midpoint_flip"], "Q15: the post-mortem documents the midpoint flip")
    need(r["q15_wc_step_days"] == 0 and abs(r["q15_wc_step"] - r["q15_wc_registered"] - r["q15_rounding"]) < 1,
         "Q15: one rounding step above the registered WC line has no day over the line")
    need("AVERAGE" in r["q15_fb_limit_rule"] and "rounded up" in r["q15_fb_limit_rule"],
         "Q15: the WC line is sanctioned on the plan's average balance, rounded up")
    # Q16
    need(r["q16_lead"] < 0, "Q16: the window crossed before GARCH on the declared rule")
    need(r["q16_g_cf"] < min(r["q16_h_cf"], r["q16_h60_cf"]), "Q16: GARCH below both windows into the crash fortnight")
    need(len(r["q16_fail_years"]) == 1, "Q16: exactly one year where only the window fails Kupiec")
    need(set(r["q16_unit_verdicts"].values()) == {"NOT REJECTED"}, "Q16: neither fails on the full fixed-long sample")
    need(all(r["q16_kmin"] <= e <= r["q16_kmax"] for e in (r["q16_exc_g"], r["q16_exc_h"], r["q16_exc_h60"])),
         "Q16: Kupiec accepts every method on the book")
    need(r["q16_g_ath"] > r["q16_h_ath"], "Q16: GARCH above the window at the high")
    need(r["q16_ret_date"] == r["q16_day_after_ath"], "Q16: the quoted return is the day after the high")
    # Q17
    need(r["q17_n_sig"] == 0 and r["q17_n_boot"] == 0, "Q17: no lead test significant")
    need(r["q7_offset"] > 0.5, "Q17: the hedge offset most of the LME loss")
    return fails


# ------------------------------------------------------------------------------------------------ Excel reconciliation
def excel_clause(st: recon_status.ReconStatus) -> str:
    """Q9's Excel clause. Only a VERIFIED record (passed, and hashed to the workbook on disk) is quoted as a result."""
    if st.verified:
        return (f"a formula-driven Excel workbook that recalculates {num(st.n_recalculated)} cells with "
                f"{num(st.n_check_failures)} failed checks")
    return {
        recon_status.STALE: "a formula-driven Excel workbook, though its recorded recalculation is not of the current "
                            "file and must be re-run",
        recon_status.NOT_RUN: "a formula-driven Excel workbook, though its full recalculation has not been run on this "
                              "build",
        recon_status.FAILED: "a formula-driven Excel workbook, though its last recorded recalculation did not pass, so "
                             "I would not cite it yet",
    }[st.status]


def recon_note(st: recon_status.ReconStatus) -> str:
    """A header callout whenever the reconciliation is not VERIFIED (empty otherwise, leaving the header unchanged)."""
    if st.verified:
        return ""
    again = "run" if st.status == recon_status.NOT_RUN else "re-run"
    return (f"\n> **Excel reconciliation: {st.status}.** {st.reason} Until it is {again}, this pack quotes no Excel "
            f"reconciliation figures. {st.how_to_verify()}\n")


def readme_recon_item(st: recon_status.ReconStatus) -> str:
    """The README verification-checklist line for the Excel reconciliation (ticked only when VERIFIED)."""
    if st.verified:
        return (f"- [x] **Excel reconciliation {st.scoreboard}.** {num(st.n_recalculated)} formula cells recalculated "
                f"outside Excel, {num(st.n_check_cells)} check cells, {num(st.n_check_failures)} failures "
                f"([`reconciliation.json`]({RECON_SOURCE})).")
    return f"- [ ] **Excel reconciliation {st.status}.** {st.reason} {st.how_to_verify()}"


# ------------------------------------------------------------------------------------------------ formatting facts
def _list_and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def format_facts(r: Mapping) -> dict[str, str]:
    n_q = len(QUESTIONS)
    n_req = len(REQUIRED_QUESTIONS)
    fac = r["q2_formula_factors"]
    ref = r["q16_ref"]
    return {
        # pack-wide
        "n_q": num(n_q), "n_authored": num(n_q - n_req), "first_authored_no": num(1), "last_authored_no": num(n_q - n_req),
        "first_required_no": num(n_q - n_req + 1), "last_required_no": num(n_q),
        "desk_name": DESK_NAME, "sim_label": SIM_LABEL, "anchor_key": ANCHOR_KEY, "window_year": str(WINDOW_START.year),
        "window_start": day(WINDOW_START, True), "window_end": day(WINDOW_END, True), "horizon_end": day(HORIZON_END, True),
        "n_trades": num(r["n_trades"]), "book_mt": num(r["book_mt"]), "book_boxes": num(r["book_boxes"]),
        "book_pnl": inr_m(r["book_pnl"]), "book_pnl_we": inr_m(r["book_pnl_we"]),
        "book_pnl_mt": inr(r["book_pnl"] / r["book_mt"]),
        "band_lo": inr_m(r["band_lo"], sign=True), "band_hi": inr_m(r["band_hi"], sign=True), "band_be": num(r["band_be"]),
        "max_words": num(MAX_ANSWER_WORDS),
        # Q1
        "first_tid": r["first_tid"], "first_grade": GRADE_NAMES[r["first_grade"]], "first_lane": LANE_NAMES[r["first_lane"]],
        "q1_week": day(r["q1_week"]), "q1_cfr": usd_t(r["q1_cfr"]), "q1_lme3m": usd_t(r["q1_lme3m"]),
        "q1_gf": num(r["q1_gf"], 3), "q1_fx": f"₹{num(r['q1_fx'], 2)}/USD", "q1_goods": inr(r["q1_goods"]),
        "q1_bcd_rate": pct(r["q1_bcd_rate"]), "q1_bcd_primary": pct(r["q1_bcd_primary"]), "q1_duty": inr(r["q1_duty"]),
        "q1_port": inr(r["q1_port"]), "q1_fin": inr(r["q1_fin"]), "q1_landed": inr(r["q1_landed"]),
        "q1_wedge": inr(r["q1_wedge"]), "q1_recovery": pct(r["q1_recovery"]), "q1_na": inr(r["q1_na"]),
        "q1_hurdle": inr(r["q1_hurdle"]), "q1_na_pit": inr(r["q1_na_pit"]), "q1_na_conv": inr(r["q1_na_conv"]),
        "q1_n_elig": num(r["q1_n_elig"]), "q1_n_cases": num(r["q1_n_cases"]), "q1_n_open": num(r["q1_n_open"]),
        # Q2
        "q2_gf_first": num(r["first_gf_td"], 3),
        "q2_formula_factors": f"{num(fac[0], 3)}–{num(fac[-1], 3)}" if len(fac) > 1 else num(fac[0], 3),
        "q2_rec_zorba": pct(r["rec_by_grade"].loc["zorba", "min"]),
        "q2_rec_tt": pct(r["rec_by_grade"].loc["taint_tabor", "min"]),
        "q2_rec_tense": pct(r["rec_by_grade"].loc["tense", "min"]),
        "q2_rec_point": inr(r["q2_rec_point"]), "q2_grade": inr_m(r["q2_grade"], sign=True),
        "q2_pit_pnl": inr_m(r["q2_pit_pnl"]), "q2_pit_grade": inr_m(r["q2_pit_grade"], sign=True),
        "q2_lag1_pnl": inr_m(r["q2_lag1_pnl"]), "q2_lag3_pnl": inr_m(r["q2_lag3_pnl"]),
        "worst_tid": r["worst_tid"],
        "q2_worst_grade": inr_m(float(r["by_trade"].loc[r["worst_tid"], "grade_spread"]), sign=True),
        # Q3
        "q3_n_fob": num(len(r["q3_fob_ids"])), "q3_fob_ids": _list_and(r["q3_fob_ids"]), "q3_n_cfr": num(r["q3_n_cfr"]),
        "q3_stops": f"USD{NB}{num(min(r['q3_stops']))}–{num(max(r['q3_stops']))} a box",
        "q3_fall_usec": pct(abs(r["q3_fall_usec"])), "q3_fall_jea": pct(abs(r["q3_fall_jea"])),
        "q3_fixture_cost": inr_m(abs(r["q3_fixture_cost"])), "q3_freight_bucket": inr_m(r["q3_freight_bucket"], sign=True),
        "q3_ratio": num((r["q3_ratio_min"] + r["q3_ratio_max"]) / 2, 3), "q3_shock": pct(r["q3_shock"], 0, sign=True),
        "q3_stress": inr_m(r["q3_stress"], sign=True), "ath1_date": day(r["ath1_date"]),
        "ath1_trades": _list_and(r["ath1_trades"]),
        # Q4
        "q4_n_sight": num(r["q4_n_sight"]), "q4_n_usance": num(r["q4_n_usance"]),
        "q4_usance_days": "–".join(num(d) for d in (r["q4_usance_days"][0], r["q4_usance_days"][-1]))
        if len(r["q4_usance_days"]) > 1 else num(r["q4_usance_days"][0]),
        "q4_n_usance_covered": num(r["q4_n_usance_covered"]),
        "q4_wc_limit": inr_m(r["q4_wc_limit"], 0), "q4_buffer": inr_m(r["q4_buffer"], 0), "q4_lc_limit": inr_m(r["q4_lc_limit"], 0),
        "q4_funding_peak": inr_m(r["q4_funding_peak"]), "q4_funding_date": day(r["q4_funding_date"]),
        "q4_buffer_days": num(r["q4_buffer_days"]), "q4_fb_days": num(r["q4_fb_days"]),
        "q4_lc_peak": inr_m(r["q4_lc_peak"]), "q4_lc_days": num(r["q4_lc_days"]),
        "q4_wc_needed": inr_m(r["q4_wc_needed"], 0), "q4_lc_needed": inr_m(r["q4_lc_needed"], 0),
        "q4_interest": inr_m(r["q4_interest"]),
        # Q5
        "q5_n_formula": num(len(r["q5_formula_ids"])), "q5_formula_ids": _list_and(r["q5_formula_ids"]),
        "q5_spread_min": signed(r["q5_spread_min"], 1), "q5_spread_max": signed(r["q5_spread_max"], 1),
        "q5_n_contango": num(r["q5_n_contango"]), "q5_n_weeks": num(r["q5_n_weeks"]),
        "q5_effect_max": usd_t(r["q5_effect_max"], 1), "q5_arb_usd": usd_t(r["q1_na_usd"]),
        "q5_n_rolls": num(r["q5_n_rolls"]), "q5_roll_pnl": inr_m(r["q5_roll_pnl"], 2, sign=True),
        "q5_roll_lme": inr_m(r["q5_roll_lme"], 2, sign=True), "q5_g": inr_m(r["q5_g"], sign=True),
        "q5_g_funding": inr_m(r["q5_g_funding"], sign=True), "q5_g_mcx": inr_m(r["q5_g_mcx"], sign=True),
        # Q6
        "q6_beta": num(r["q6_beta"], 2), "q6_beta_se": num(r["q6_beta_se"], 2), "q6_beta_t": num(r["q6_beta_t"], 1),
        "q6_r2": num(r["q6_r2"], 2), "q6_n": num(r["q6_n"]), "q6_open": pct(r["q6_open"], 0),
        "q6_worst": inr_m(r["q6_worst"], sign=True), "q6_best": inr_m(r["q6_best"], sign=True),
        "q6_book": inr_m(r["q6_book"]), "mc_h": num(r["mc_h"]),
        "q6_apr_base": inr_m(r["q6_apr_base"]), "q6_apr_basis": inr_m(r["q6_apr_basis"]),
        "q6_jul_base": inr_m(r["q6_jul_base"], 2), "q6_jul_basis": inr_m(r["q6_jul_basis"]),
        "apr_date": day(r["apr_date"]), "jul_date": day(r["jul_date"]),
        "q6_var_beta": inr_m(r["q6_var_beta"], 1), "q6_var_base": inr_m(r["q6_var_base"], 2),
        "q6_var_beta_w": inr_m(r["q6_var_beta_w"], 1), "q6_beta_w": num(r["q6_beta_w"], 2),
        "q6_beta_w_t": num(r["q6_beta_w_t"], 1), "q6_beta_ll": num(r["q6_beta_ll"], 2),
        "q6_open_w": pct(r["q6_open_w"], 0),
        # Q7
        "q7_hr_common": num(r["q7_hr_common"], 2), "q7_n_common": num(r["q7_n_common"]),
        "q7_hr_full": "/".join(num(x, 2) for x in r["q7_hr_full"]), "q7_full_ids": _list_and(r["q7_full_ids"]),
        "q7_hr_low": "/".join(num(x, 2) for x in r["q7_hr_low"]), "q7_low_id": _list_and(r["q7_low_ids"]),
        "q7_band": f"{num(r['q7_band'][0], 2)}–{num(r['q7_band'][1], 2)}", "q7_roll_days": num(r["q7_roll_days"]),
        "q7_n_rolls": num(r["q5_n_rolls"]), "e1_start": day(r["e1_start"]), "e1_end": day(r["e1_end"]),
        "q7_e1_move": pct(r["q7_e1_move"]), "q7_phys": inr_m(abs(r["q7_phys"])),
        "q7_mcx": inr_m(abs(r["q7_mcx"])), "q7_offset": pct(r["q7_offset"], 0),
        "q7_benefit": inr_m(abs(r["q7_benefit"])), "q7_nu_limit": num(r["q7_nu_limit"]),
        "q7_nu_days": num(r["q7_nu_days"]),
        # Q8
        "q8_n_lines": num(r["q8_n_lines"]), "q8_low_id": _list_and(r["q8_low_ids"]),
        "q8_low_cover": pct(r["q8_low_cover"], 0), "q8_min_cover": pct(r["q8_min_cover"], 0),
        "q8_fx_start": f"₹{num(r['q8_fx_start'], 2)}", "q8_fx_end": f"₹{num(r['q8_fx_end'], 2)}",
        "q8_fx_move": pct(r["q8_fx_move"], sign=True), "e2_start": day(r["e2_start"]), "e2_end": day(r["e2_end"]),
        "q8_fwd": inr_m(r["q8_fwd"], sign=True), "q8_usd_flows": inr_m(r["q8_usd_flows"], sign=True),
        "q8_offset": pct(r["q8_offset"], 0), "q8_mcx": inr_m(abs(r["q8_mcx"])),
        "q8_fx_bucket": inr_m(r["q8_fx_bucket"], sign=True), "q8_var_pf": inr_m(r["q8_var_pf"], 2),
        "q8_var_mcx": inr_m(r["q8_var_mcx"], 2), "q8_var_net": inr_m(r["q8_var_net"], 2),
        # Q9
        "q9_residual": inr(r["q9_residual"]), "q9_excel": excel_clause(r["q9_recon"]),
        "recon_note": recon_note(r["q9_recon"]),
        "q9_nd": inr_m(r["q9_nd"], sign=True), "q9_nd_share": pct(r["q9_nd_share"], 0),
        "q9_nd_td": inr_m(r["q9_nd_td"]), "q9_nd_later": inr_m(r["q9_nd_later"]),
        "q9_lme": inr_m(r["q9_lme"], sign=True), "q9_lme_abs": inr_m(abs(r["q9_lme"])),
        "q5_g_abs": inr_m(abs(r["q5_g"])), "NB": NB,
        # Q10
        "q10_qty": num(r["q10_qty"]), "q10_grade": GRADE_NAMES[r["q10_grade"]], "q10_lane": LANE_NAMES[r["q10_lane"]],
        "q10_date": day(r["q10_date"]), "q10_factor": num(r["q10_factor"], 3), "q10_na_conv": inr(r["q10_na_conv"]),
        "q10_pnl": inr_m(r["q10_pnl"], sign=True), "q10_pnl_mt": inr(r["q10_pnl_mt"]),
        "q10_nd": inr_m(r["q10_nd"], sign=True), "q10_g": inr_m(r["q10_g"], sign=True),
        "q10_sale_date": day(r["q10_sale_date"]), "q10_sale_lag": num(r["q10_sale_lag"]),
        "q10_grade_b": inr_m(r["q10_grade_b"], sign=True), "q10_lme": inr_m(r["q10_lme"], sign=True),
        "q10_events": inr_m(r["q10_events"], sign=True), "q10_stop_date": day(r["q10_stop"].split("@")[1]),
        # Q11
        "rjk_id": r["rjk_id"], "q11_name": r["q11_name"], "q11_limit": inr_m(r["q11_limit"], 0),
        "q11_util": pct(r["q11_util"]), "q11_contracted": f"{mult(r['q11_contracted'])} the line",
        "q11_n_adv": num(len(r["q11_adv"])), "q11_adv_list": _list_and([mult(a) for a in r["q11_adv"]]),
        "q11_pd": pct(r["q11_pd"]), "q11_band": r["q11_band"], "q11_new_limit": inr_m(r["q11_new_limit"], 0),
        "q11_n_synth": num(r["q11_n_synth"]), "q11_n_outside": num(r["q11_n_outside"]),
        "q11_n_bookings": num(r["q11_n_bookings"]), "q11_default": inr_m(abs(r["q11_default"])),
        "q11_default_lme": inr_m(abs(r["q11_default_lme"])), "q11_lme_shock": pct(r["q11_lme_shock"], 0, sign=True),
        # Q12
        "q12_cf_start": day(r["q12_cf_start"]), "q12_cf_end": day(r["q12_cf_end"]),
        "q12_cf_move": pct(abs(r["q12_cf_move"])), "q12_cf_vm": inr_m(r["q12_cf_vm"], sign=True),
        "q12_margin_peak": inr_m(r["q12_margin_peak"]), "q12_margin_date": day(r["q12_margin_date"]),
        "q12_mf_start": day(r["q12_mf_start"]), "q12_mf_end": day(r["q12_mf_end"]),
        "q12_mf_move": pct(abs(r["q12_mf_move"])), "q12_mf_net": inr_m(abs(r["q12_mf_net"])),
        "q12_im": inr_m(r["q12_im"]), "q12_im_date": day(r["q12_im_date"]),
        "q12_stress_move": pct(r["q12_stress_move"]), "q12_stress_call": inr_m(r["q12_stress_call"]),
        "q12_stress_headroom": inr_m(r["q12_stress_headroom"], sign=True), "q12_paper": inr_m(r["q12_paper"]),
        "q12_margin_source": inr_m(r["q12_margin_source"]),
        # Q13
        "q13_delay": num(r["q13_delay"]), "q13_rej": pct(r["q13_rej"], 0), "q13_loss": pct(r["q13_loss"], 0),
        "q13_ath": inr_m(abs(r["q13_ath"])), "q13_apr": inr_m(abs(r["q13_apr"])),
        "q13_jul": inr_m(abs(r["q13_jul"])), "n_paths": num(r["n_paths"]), "q13_all": inr_m(r["q13_all"], sign=True),
        # Q14
        "q14_n_params": num(r["q14_n_params"]), "q14_n_direct": num(r["q14_n_direct"]), "q14_n_proxy": num(r["q14_n_proxy"]),
        "q14_n_assump": num(r["q14_n_assump"]), "q14_n_verified": num(r["q14_n_verified"]),
        "q14_n_pending": num(r["q14_n_pending"]), "q14_sp_direct": num(r["q14_sp_direct"]), "q14_sp_n": num(r["q14_sp_n"]),
        "q14_n_headlines": num(r["q14_n_headlines"]),
        # Q15
        "q15_blocked_id": r["q15_blocked_id"], "q15_blocked_date": day(r["q15_blocked_date"]),
        "q15_blocked_pnl": inr_m(r["q15_blocked_pnl"], sign=True), "q15_wc_step": inr_m(r["q15_wc_step"], 0),
        "q15_step": f"₹{num(r['q15_rounding'] / 1e7)}{NB}crore",
        # Q16
        "q16_window": num(r["q16_window"]), "ath_date": day(r["ath_date"]),
        "q16_g_ath": pct(r["q16_g_ath"], 2), "q16_h_ath": pct(r["q16_h_ath"], 2), "q16_ret": pct(r["q16_ret"], 2),
        "q16_z_g": num(r["q16_z_g"], 1), "q16_z_h": num(r["q16_z_h"], 1),
        "q16_pctl": f"{num(r['q16_pctl'] * 100)}th", "q16_ref": f"{ref[0]}–{ref[1]}",
        "q16_h_cross": day(r["q16_h_cross"]), "q16_g_cross": day(r["q16_g_cross"]),
        "q16_lead": num(abs(r["q16_lead"])), "q16_g_cf": pct(r["q16_g_cf"], 2), "q16_h_cf": pct(r["q16_h_cf"], 2),
        "q16_h60_cf": pct(r["q16_h60_cf"], 2), "q16_exc_g": num(r["q16_exc_g"]), "q16_exc_h": num(r["q16_exc_h"]),
        "q16_n": num(r["q16_n"]), "q16_exp": num(r["q16_exp"], 0 if float(r["q16_exp"]).is_integer() else 1),
        "q16_kmin": num(r["q16_kmin"]), "q16_kmax": num(r["q16_kmax"]), "q16_unit_n": num(r["q16_unit_n"]),
        "q16_fail_year": _list_and(r["q16_fail_years"]) if r["q16_fail_years"] else "no year",
        # Q17
        "q17_n_weeks": num(r["q17_n_weeks"]), "q17_n_sig": num(r["q17_n_sig"]), "q17_n_lead": num(r["q17_n_lead"]),
        "q17_exp_fp": num(r["q17_exp_fp"] * r["q17_n_lead"] / r["q17_n_tests_total"], 1),
        "q17_fit_from": r["q17_fit_from"], "q17_fit_to": r["q17_fit_to"],
    }


# ------------------------------------------------------------------------------------------------ render
def answer_words(text: str) -> int:
    """Words as a reader counts them: '₹1.2 m' is one figure, markdown emphasis is not a word."""
    return len(re.sub(r"[*`]", "", text.replace(NB, "")).split())


def render_questions(facts: Mapping[str, str]) -> list[dict[str, str]]:
    out = []
    for q in QUESTIONS:
        out.append({"qid": q.qid, "topic": q.topic, "question": q.question.format_map(facts),
                    "answer": q.answer.format_map(facts), "sources": ", ".join(f"`{s}`" for s in q.sources)})
    return out


def render_markdown(facts: Mapping[str, str]) -> str:
    parts = [HEADER.format_map(facts).rstrip(), ""]
    for i, q in enumerate(render_questions(facts), start=1):
        parts += [f"## {i}. {q['question']}", "", f"*{q['topic']}.*", "", q["answer"], "", f"*Sources:* {q['sources']}", ""]
    parts.append(FOOTER.format_map(facts).rstrip())
    return "\n".join(parts) + "\n"


def build_markdown(src: Mapping) -> tuple[str, dict]:
    raw = compute_raw(src)
    failed = check_claims(raw)
    if failed:
        raise ValueError("interview pack prose no longer matches the data: " + "; ".join(failed))
    facts = format_facts(raw)
    long = [(q["qid"], answer_words(q["answer"])) for q in render_questions(facts)
            if answer_words(q["answer"]) > MAX_ANSWER_WORDS]
    if long:
        raise ValueError(f"answers over {MAX_ANSWER_WORDS} words: {long}")
    return render_markdown(facts), raw


def main() -> None:
    if len(QUESTIONS) != N_QUESTIONS or [q.question for q in QUESTIONS[-2:]] != list(REQUIRED_QUESTIONS):
        raise ValueError("the pack must hold exactly 17 questions ending with the two the spec names")
    src = load_sources()
    md, _raw = build_markdown(src)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path, pdf_path = REPORTS_DIR / f"{NAME}.md", REPORTS_DIR / f"{NAME}.pdf"
    md_path.write_text(md, encoding="utf-8")
    n = render_markdown_pdf(md, pdf_path, title="Interview pack (SIM)", author="Aluminium scrap desk (SIM)",
                            style=PACK_STYLE)
    if n < 1 or count_pdf_pages(pdf_path) != n:
        raise ValueError(f"interview pack PDF page count mismatch ({n})")
    st: recon_status.ReconStatus = src["recon"]
    # the reconciliation record is written only by the slow test; with no record the pack says NOT_RUN at the top
    missing = [s for q in QUESTIONS for s in q.sources if not (ROOT / s.split(" ")[0]).exists()
               and not (s == RECON_SOURCE and st.status == recon_status.NOT_RUN)]
    if missing:
        raise ValueError(f"an interview-pack source path does not exist: {missing}")
    print(f"[pack] Excel reconciliation: {st.status} — {st.reason}")
    if not st.verified:
        print(f"[pack] {st.how_to_verify()}")


if __name__ == "__main__":
    main()
