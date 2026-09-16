"""Stage P6 — the one-page recruiter summary: the desk, its honest headline and its risk findings on one A4 page.

    DESK_OFFLINE=1 .venv/bin/python -c "import desk.reporting.one_pager as m; m.main()"

Reads (never writes) the published P1–P7 tables, the parameter register, the post-mortem's declared metric and the
Excel reconciliation status, and writes:

    outputs/reports/one_pager.md              the summary (GitHub-readable; linked from the top of README.md)
    outputs/reports/one_pager.pdf             the same on exactly one A4 page (asserted), SIM label in the footer
    outputs/charts/p6_one_pager_equity.png    cumulative book P&L with the anchor-premium band drawn on it
    outputs/charts/p6_one_pager_var.png       book 95 % one-day VaR, GARCH(1,1) against the 250-day window

Design choices worth knowing
----------------------------
* **One source of facts.** The numbers come from the interview pack's own loaders (`interview_pack.load_sources` →
  `compute_raw`), the same path `run_reports.refresh_readme` uses for the README, so the one-pager, the README and the
  pack can never quote different figures. The few facts only this page needs (the best trade by the post-mortem's
  metric, the stresses beyond every Monte Carlo path, the VaR peak) are read here straight from their tables.
* **No hand-typed numbers.** `TEMPLATE` holds only `{placeholders}`; `tests/test_one_pager.py` renders it with
  sentinels and fails if a digit survives outside a short allow-list (GARCH(1,1), the 95/99 % confidence labels,
  CONTRACTS §5a), and recomputes the published numbers from the CSVs without going through this module.
* **Qualitative words are tested.** "not sign-robust", "the only ticket positive in every case", "crossed first",
  "sat below both windows", "worse than every path" are re-tested by `check_claims`; `main()` raises if one fails,
  so a changed book cannot publish a summary of a different result.
* **The headline never travels alone.** The book P&L sits in the same table row group as its
  `domestic_anchor_premium_inr_t` band, and the equity chart draws the band as a bar at the horizon.
* **Excel status is asked, not asserted.** The workbook line quotes `desk.excel.reconciliation_status.status()`:
  recalculation figures only when VERIFIED, otherwise the status and its reason.
* **PDF.** Rendered through `desk.reporting.pdf` (fonts, SIM footer, determinism). Like the post-mortem, this module
  splits the Markdown at image lines (a side-by-side figure row) and at `<!-- columns -->` / `<!-- column-break -->`
  / `<!-- end-columns -->` markers (a two-column block); GitHub ignores the markers and reads the page top to bottom.
  Markdown links are reduced to their text in the PDF.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from pathlib import Path

import matplotlib.dates as mdates
import pandas as pd
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Spacer, Table, TableStyle

from desk import HORIZON_END, SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.excel import reconciliation_status as recon_status
from desk.paths import CHARTS_DIR, REPORTS_DIR, TABLES_DIR
from desk.reporting import interview_pack as ip
from desk.reporting import post_mortem as pm
from desk.reporting.pdf import (
    DeskDocTemplate,
    PdfStyle,
    _numbered_canvas_class,  # the shared footer (SIM label + "Page n of N"), as in the post-mortem
    count_pdf_pages,
    markdown_to_flowables,
    register_fonts,
)
from desk.reporting.style import PALETTE, save_fig, plt

NAME = "one_pager"
MAX_PAGES = 1
CHART_EQUITY = "p6_one_pager_equity"
CHART_VAR = "p6_one_pager_var"
ANCHOR_KEY = ip.ANCHOR_KEY
BASE_CASE = pm.BASE_CASE
NB, M = ip.NB, ip.M
num, inr, inr_m, pct, day, mult = ip.num, ip.inr, ip.inr_m, ip.pct, ip.day, ip.mult

BUCKET_NAMES = {
    "new_deal": "deal margin at contract dates", "grade_spread": "grade spread",
    "roll_term_structure": "carry, roll and cross-terms", "lme_flat": "LME flat price", "fx": "USD/INR",
    "freight": "freight", "demurrage_penalty": "events", "cross_exchange_basis": "LME–MCX basis",
}
N_TOP_BUCKETS = 4
COLUMNS, COLUMN_BREAK, END_COLUMNS = "<!-- columns -->", "<!-- column-break -->", "<!-- end-columns -->"
COLUMN_GAP_MM = 5.0
COLUMN_SPACE_BEFORE_PT = 3.0
FIG_GAP_MM = 2.5
FIG_SIZE_IN = (4.8, 2.2)           # drawn at ~1.35× the printed column width, so type prints at about 6–7 pt
ONE_PAGER_STYLE = PdfStyle(font_size=7.55, table_font_size=6.95, title_size=13.5, h2_size=8.9, h3_size=8.0,
                           margin_left_mm=11.0, margin_right_mm=11.0, margin_top_mm=8.0, margin_bottom_mm=11.0,
                           leading_ratio=1.17, paragraph_space_after=1.8, heading_space_before=3.4,
                           footer_font_size=6.2)


# ------------------------------------------------------------------------------------------------ sources
def load_sources() -> dict[str, object]:
    """The interview pack's sources plus the handful of columns only this page reads (low-memory machine)."""
    T = TABLES_DIR
    src = ip.load_sources()
    src.update({
        "pricing": pd.read_csv(T / "pnl_sensitivity_pricing.csv", usecols=["case", "trade_id", "cum_pnl_horizon_inr"]),
        "var_daily": pd.read_csv(T / "var_daily.csv",
                                 usecols=["date", "in_window", "position_held", "var_garch_inr", "var_hist250_inr",
                                          "pnl_market_inr", "exception_garch", "exception_hist250"]),
        "stress_full": pd.read_csv(T / "mc_stress_scenarios.csv",
                                   usecols=["snapshot_id", "snapshot_date", "scenario_id", "scenario_label", "role",
                                            "pnl_inr", "beyond_every_mc_path"]),
        "snap_mcx": pd.read_csv(T / "mc_snapshots.csv",
                                usecols=["snapshot_id", "mcx_lots_open", "lme_delta_mt", "lme_delta_physical_mt"]),
        "cp": pd.read_csv(T / "trade_book.csv", dtype=str, usecols=["trade_id", "supplier_id", "buyer_ids"]),
        "elig": pd.read_csv(T / "trade_eligibility_check.csv", usecols=["trade_id", "status"]),
        "kupiec_unit": pd.read_csv(T / "kupiec.csv", usecols=["sample", "method", "start", "end"]),
        "n_desk_notes": len(sorted(REPORTS_DIR.glob("desk_note_*.md"))),
    })
    return src


# ------------------------------------------------------------------------------------------------ raw facts
def _best_trade(src: Mapping, r: Mapping) -> dict:
    """The post-mortem's declared metric (worst P&L across the registered re-pricing cases), recomputed per ticket."""
    p = src["pricing"]
    reprice = p[(p["trade_id"] != "BOOK") & (p["case"] != BASE_CASE)]
    worst = reprice.groupby("trade_id")["cum_pnl_horizon_inr"].min()
    n_cases = reprice.groupby("trade_id").size()
    best = str(worst.idxmax())
    tp = r["trade_pnl"]
    raw_leader = str(tp.idxmax())
    book = src["book"].set_index("trade_id")
    return {
        "best_tid": best, "best_pnl": float(tp[best]), "best_mt": ip._f(book.at[best, "quantity_mt"]),
        "best_grade": book.at[best, "grade"], "best_lane": book.at[best, "lane"], "best_floor": float(worst[best]),
        "n_reprice_cases": int(n_cases[best]), "n_reprice_cases_all_equal": bool(n_cases.nunique() == 1),
        "n_positive_all": int((worst > 0).sum()),
        "raw_leader": raw_leader, "raw_leader_pnl": float(tp[raw_leader]), "raw_leader_worst": float(worst[raw_leader]),
        "worst_lane": book.at[r["worst_tid"], "lane"],
    }


def _buckets(r: Mapping) -> dict:
    b = pd.Series(r["buckets"])
    order = b.abs().sort_values(ascending=False).index
    top = list(order[:N_TOP_BUCKETS])
    rest = b.drop(top)
    return {"top_buckets": [(k, float(b[k])) for k in top], "rest_sum": float(rest.sum()), "n_rest": len(rest),
            "largest_bucket": str(order[0])}


def _var(src: Mapping) -> dict:
    v = src["var_daily"]
    pos = v[v["in_window"] & v["position_held"]]
    peak = pos.loc[pos["var_garch_inr"].idxmax()]
    return {"var_peak_g": float(peak["var_garch_inr"]), "var_peak_h": float(peak["var_hist250_inr"]),
            "var_peak_date": str(peak["date"]), "var_n_pos": len(pos)}


def _unit_backtest(src: Mapping) -> dict:
    k = src["kupiec_unit"]
    u = k[(k["sample"] == "unit_lme_long_1000mt") & (k["method"] == "garch")].iloc[0]
    return {"unit_from": str(u["start"])[:4], "unit_to": str(u["end"])[:4]}


def _stresses(src: Mapping) -> dict:
    s = src["stress_full"]
    beyond = s[(s["role"] == "SCENARIO") & s["beyond_every_mc_path"]].sort_values(["scenario_id", "snapshot_date"])
    groups = []
    for sid, g in beyond.groupby("scenario_id", sort=False):
        groups.append((str(g["scenario_label"].iloc[0]), [(str(d), float(x)) for d, x in zip(g["snapshot_date"],
                                                                                              g["pnl_inr"])]))
    groups.sort(key=lambda t: min(d for d, _ in t[1]))
    snaps = src["snap_mcx"].set_index("snapshot_id")
    return {"beyond_groups": groups, "ath_mcx_lots": float(snaps.at[ip.MC_SNAP_ATH, "mcx_lots_open"]),
            "jul_net_lme_mt": float(snaps.at[ip.MC_SNAP_JUL, "lme_delta_mt"]),
            "jul_phys_lme_mt": float(snaps.at[ip.MC_SNAP_JUL, "lme_delta_physical_mt"])}


def _desk(src: Mapping) -> dict:
    book, cp, elig = src["book"], src["cp"], src["elig"]
    buyers = {b for ids in cp["buyer_ids"] for b in ip._split(ids)}
    params = src["params"]
    anc = params[params["key"] == ANCHOR_KEY].iloc[0]
    return {
        "n_grades": book["grade"].nunique(), "n_lanes": book["lane"].nunique(),
        "grades": [ip.GRADE_NAMES[g] for g in ip.GRADE_NAMES if g in set(book["grade"])],
        "lanes": [ip.LANE_NAMES[x] for x in ip.LANE_NAMES if x in set(book["lane"])],
        "n_suppliers": cp["supplier_id"].nunique(), "n_buyers": len(buyers),
        "first_td": book["trade_date"].min(), "last_td": book["trade_date"].max(),
        "elig_pass": int((elig["status"] == "PASS").sum()), "elig_n": len(elig),
        "anchor_flag": str(anc["flag"]), "anchor_status": re.match(r"\s*([A-Z/]+)", str(anc["verify"])).group(1),
        "n_desk_notes": int(src["n_desk_notes"]),
    }


def _credit(src: Mapping) -> dict:
    cs = src["credit"].sort_values("rank_riskiest_first")
    return {"credit_rank": [(str(x["cp_id"]), float(x["pd_model_annual_frac"]), str(x["band_final"]))
                            for _, x in cs.iterrows()]}


def compute_raw(src: Mapping) -> dict:
    r = dict(ip.compute_raw(src))
    r.update(_best_trade(src, r))
    r.update(_buckets(r))
    r.update(_var(src))
    r.update(_unit_backtest(src))
    r.update(_stresses(src))
    r.update(_desk(src))
    r.update(_credit(src))
    r["var_mean_hist"] = ip._f(ip._metric(src["var"], "var_mean_hist250", "book_window"))
    r["mc_ath_var99"] = float(ip._one(src["mc"], snapshot_id=ip.MC_SNAP_ATH, variant="normal_window")["var99_inr"])
    r["win_base"] = int(config.value("var_hist_window_base_days"))
    r["win_fast"] = int(config.value("var_hist_window_fast_days"))
    r["recon"] = src["recon"]
    return r


# ------------------------------------------------------------------------------------------------ claims
def check_claims(r: Mapping) -> list[str]:
    """Every qualitative word in TEMPLATE, re-tested against the data. Returns the failed claims."""
    fails: list[str] = []

    def need(ok: bool, claim: str) -> None:
        if not ok:
            fails.append(claim)

    need(not r["band_sign_robust"] and r["band_be_inside"] and r["band_lo"] < 0 < r["band_hi"],
         "headline: not sign-robust, break-even inside the grid")
    need(r["anchor_flag"] == "ASSUMPTION", "headline: the anchor premium is an ASSUMPTION")
    need(r["largest_bucket"] == "new_deal", "attribution: deal margin is the largest bucket")
    need(r["best_tid"] == pm.TRADE_OF_RECORD, "best trade: the declared metric still selects the post-mortem's ticket")
    need(r["n_positive_all"] == 1 and r["best_floor"] > 0, "best trade: the only ticket positive in every case")
    need(r["n_reprice_cases_all_equal"], "best trade: every ticket has the same number of re-pricing cases")
    need(r["raw_leader"] != r["best_tid"] and r["raw_leader_worst"] < 0,
         "best trade: the raw-rupee leader is another ticket and goes negative in its worst case")
    need(r["worst_tid"] == ip.WORST_TRADE_OF_RECORD and r["q10_pnl"] < 0, "worst trade: the ticket of record, a loss")
    need(r["elig_pass"] == r["elig_n"], "discipline: every ticket passes the ex-ante rule")
    need(r["q16_g_ath"] > r["q16_h_ath"], "VaR: GARCH above the 250-day window at the high")
    need(r["var_peak_g"] > r["var_peak_h"], "VaR: GARCH's peak above the window's VaR that day")
    need(r["q16_lead"] < 0, "VaR: the 250-day window crossed the declared alert first")
    need(r["q16_g_cf"] < min(r["q16_h_cf"], r["q16_h60_cf"]), "VaR: GARCH below both windows into the crash fortnight")
    need(all(str(v) == "NOT REJECTED" for v in r["q16_unit_verdicts"].values()),
         "Kupiec: fixed position over the full sample, neither method rejected")
    need(len(r["q16_fail_years"]) >= 1, "Kupiec: a year that rejects the 250-day window but not GARCH")
    need(r["q16_kmin"] <= min(r["q16_exc_g"], r["q16_exc_h"]) and max(r["q16_exc_g"], r["q16_exc_h"]) <= r["q16_kmax"],
         "Kupiec: both book exception counts inside the acceptance region")
    need(r["ath_mcx_lots"] == 0, "Monte Carlo: no MCX hedge on the first snapshot")
    need(r["q6_apr_basis"] > r["q6_apr_base"] and r["q6_jul_basis"] > 2 * r["q6_jul_base"],
         "Monte Carlo: the basis factor raises VaR, and is most of it on the last snapshot")
    need(abs(r["jul_net_lme_mt"]) < 0.1 * abs(r["jul_phys_lme_mt"]), "Monte Carlo: the last snapshot book is near-flat")
    need(len(r["beyond_groups"]) >= 1 and all(x < 0 for _, g in r["beyond_groups"] for _, x in g),
         "Monte Carlo: some stress losses sit beyond every path")
    need(r["credit_rank"][0][0] == ip.RISKIEST_BUYER_OF_RECORD and r["q11_new_limit"] < r["q11_limit"],
         "credit: the riskiest buyer of record, with its line cut")
    need(r["q4_funding_peak"] > r["q4_wc_limit"] and r["q15_wc_step_days"] == 0,
         "liquidity: over the line, and never over it one step higher")
    need(r["q4_lc_peak"] > r["q4_lc_limit"], "liquidity: LCs outstanding over the LC line")
    need(r["q17_n_sig"] == 0 and r["q17_n_boot"] == 0, "sentiment: no lead test significant")
    need(r["q6_beta_w"] < 1 and r["q6_var_beta_w"] > r["q6_var_base"], "MCX proxy: mirror beta below one raises VaR")
    need(r["q2_pit_pnl"] < r["book_pnl"] and r["q2_pit_grade"] < 0, "grade path: the point-in-time mix earns less")
    return fails


# ------------------------------------------------------------------------------------------------ formatting
def _list_and(items: list[str]) -> str:
    return ip._list_and(items)


def _recon_clause(st: recon_status.ReconStatus) -> str:
    if st.verified:
        return (f"reconciliation **{st.status}**: {num(st.n_recalculated)} formula cells recalculated outside Excel, "
                f"{num(st.n_check_failures)} failed checks")
    # Kept to one short clause: the full reason and the verify command live in docs/35 and the interview pack, and a
    # longer sentence here pushes the page onto a second sheet on exactly the fresh builds that lack a record.
    return f"reconciliation **{st.status}**, so no figures are quoted (the Excel workbook doc gives the verify command)"


def format_facts(r: Mapping) -> dict[str, str]:
    tb = r["top_buckets"]
    buckets = ", ".join(f"{BUCKET_NAMES[k]} {inr_m(v, sign=True)}" for k, v in tb)
    beyond = "; ".join(
        f"{label} on {_list_and([f'{day(d)} ({inr_m(x)})' for d, x in g])}" for label, g in r["beyond_groups"])
    cr = r["credit_rank"]
    credit = "; ".join([f"**{cr[0][0]}** PD {pct(cr[0][1])}, band {cr[0][2]}"]
                       + [f"{c} {pct(p)} (band {b})" for c, p, b in cr[1:]])
    total = sum(r["buckets"].values())
    return {
        "sim_label": SIM_LABEL, "anchor_key": ANCHOR_KEY,
        "window_start": day(WINDOW_START, True), "window_end": day(WINDOW_END, True),
        "horizon_end": day(HORIZON_END, True),
        "grades": _list_and(r["grades"]), "lanes": _list_and(r["lanes"]), "ath_date": day(r["ath_date"]),
        # the desk in numbers
        "n_trades": num(r["n_trades"]), "book_mt": num(r["book_mt"]), "book_boxes": num(r["book_boxes"]),
        "n_grades": num(r["n_grades"]), "n_lanes": num(r["n_lanes"]), "n_suppliers": num(r["n_suppliers"]),
        "n_buyers": num(r["n_buyers"]), "first_td": day(r["first_td"]), "last_td": day(r["last_td"], True),
        "elig_pass": num(r["elig_pass"]), "elig_n": num(r["elig_n"]), "n_elig_cases": num(r["q1_n_elig"]),
        "n_cases": num(r["q1_n_cases"]), "n_open_base": num(r["q1_n_open"]),
        # headline
        "book_pnl": inr_m(r["book_pnl"]), "book_pnl_mt": inr(r["book_pnl"] / r["book_mt"]),
        "book_pnl_we": inr_m(r["book_pnl_we"]), "band_lo": inr_m(r["band_lo"], sign=True),
        "band_hi": inr_m(r["band_hi"], sign=True), "band_be": num(r["band_be"]), "anchor_flag": r["anchor_flag"],
        "anchor_status": r["anchor_status"], "buckets": buckets, "n_rest": num(r["n_rest"]),
        "rest_sum": inr_m(r["rest_sum"], sign=True), "nd_share": pct(r["buckets"]["new_deal"] / total, 0),
        "residual": inr(r["q9_residual"]),
        "best_tid": r["best_tid"], "best_grade": ip.GRADE_NAMES[r["best_grade"]],
        "best_lane": ip.LANE_NAMES[r["best_lane"]],
        "best_pnl": inr_m(r["best_pnl"], 2, sign=True), "best_pnl_mt": inr(r["best_pnl"] / r["best_mt"]),
        "best_floor": inr_m(r["best_floor"], 2, sign=True), "n_reprice": num(r["n_reprice_cases"]),
        "raw_leader": r["raw_leader"], "raw_leader_pnl": inr_m(r["raw_leader_pnl"], 2, sign=True),
        "raw_leader_worst": inr_m(r["raw_leader_worst"], 2, sign=True),
        "worst_tid": r["worst_tid"], "worst_grade": ip.GRADE_NAMES[r["q10_grade"]],
        "worst_lane": ip.LANE_NAMES[r["worst_lane"]], "worst_pnl": inr_m(r["q10_pnl"], 2, sign=True),
        "worst_pnl_mt": inr(r["q10_pnl_mt"]), "worst_stop": day(r["q10_stop"].split("@")[1]),
        # VaR and backtest
        "var_n": num(r["q16_n"]), "var_mean_g": inr_m(r["q6_var_base"], 2),
        "var_mean_h": inr_m(r["var_mean_hist"], 2),
        "day_after_ath": day(r["q16_day_after_ath"]), "g_ath": pct(r["q16_g_ath"], 2), "h_ath": pct(r["q16_h_ath"], 2),
        "var_peak_g": inr_m(r["var_peak_g"]), "var_peak_h": inr_m(r["var_peak_h"]),
        "var_peak_date": day(r["var_peak_date"]), "pctl": f"{num(r['q16_pctl'] * 100)}th",
        "h_cross": day(r["q16_h_cross"]), "g_cross": day(r["q16_g_cross"]), "lead": num(abs(r["q16_lead"])),
        "cf_start": day(r["q12_cf_start"]), "g_cf": pct(r["q16_g_cf"], 2), "h_cf": pct(r["q16_h_cf"], 2),
        "h60_cf": pct(r["q16_h60_cf"], 2), "exc_g": num(r["q16_exc_g"]), "exc_h": num(r["q16_exc_h"]),
        "exc_exp": num(r["q16_exp"], 0 if float(r["q16_exp"]).is_integer() else 1),
        "kmin": num(r["q16_kmin"]), "kmax": num(r["q16_kmax"]), "unit_from": r["unit_from"], "unit_to": r["unit_to"],
        "fail_year": _list_and(r["q16_fail_years"]),
        # Monte Carlo
        "n_paths": num(r["n_paths"]), "mc_h": num(r["mc_h"]), "ath1_date": day(r["ath1_date"]),
        "mc_ath": inr_m(r["mc_ath_var99"]), "apr_date": day(r["apr_date"]), "mc_apr": inr_m(r["q6_apr_base"]),
        "jul_date": day(r["jul_date"]), "mc_jul": inr_m(r["q6_jul_base"], 2), "mc_apr_basis": inr_m(r["q6_apr_basis"]),
        "mc_jul_basis": inr_m(r["q6_jul_basis"]), "beyond": beyond,
        # credit, liquidity, sentiment
        "credit": credit, "rjk": cr[0][0], "rjk_contracted": mult(r["q11_contracted"]),
        "rjk_limit": inr_m(r["q11_limit"], 0), "rjk_new_limit": inr_m(r["q11_new_limit"], 0),
        "n_synth": num(r["q11_n_synth"]),
        "funding_peak": inr_m(r["q4_funding_peak"]), "funding_date": day(r["q4_funding_date"]),
        "wc_limit": inr_m(r["q4_wc_limit"], 0), "fb_days": num(r["q4_fb_days"]),
        "wc_step": f"₹{num(r['q15_rounding'] / 1e7)}{NB}crore", "lc_peak": inr_m(r["q4_lc_peak"]),
        "lc_limit": inr_m(r["q4_lc_limit"], 0), "lc_days": num(r["q4_lc_days"]), "im_peak": inr_m(r["q12_im"]),
        "im_date": day(r["q12_im_date"]),
        "n_headlines": num(r["q14_n_headlines"]), "n_weeks": num(r["q17_n_weeks"]), "n_sig": num(r["q17_n_sig"]),
        "n_lead": num(r["q17_n_lead"]),
        # provenance
        "p_direct": num(r["q14_n_direct"]), "p_proxy": num(r["q14_n_proxy"]), "p_assump": num(r["q14_n_assump"]),
        "p_total": num(r["q14_n_params"]), "sp_direct": num(r["q14_sp_direct"]), "sp_proxy": num(r["q14_sp_proxy"]),
        "sp_assump": num(r["q14_sp_assump"]), "sp_total": num(r["q14_sp_n"]),
        "v_verified": num(r["q14_n_verified"]), "v_partial": num(r["q14_n_partial"]),
        "v_pending": num(r["q14_n_pending"]), "v_na": num(r["q14_n_na"]),
        "beta_w": num(r["q6_beta_w"], 2), "var_beta_w": inr_m(r["q6_var_beta_w"], 1),
        "pit_pnl": inr_m(r["q2_pit_pnl"]), "pit_grade": inr_m(r["q2_pit_grade"], sign=True),
        # where to look
        "n_desk_notes": num(r["n_desk_notes"]), "pm_pages": num(pm.MAX_PAGES), "n_questions": num(ip.N_QUESTIONS),
        "recon": _recon_clause(r["recon"]),
        "chart_equity": CHART_EQUITY, "chart_var": CHART_VAR,
        "win": num(r["win_base"]), "win_fast": num(r["win_fast"]),
    }


TEMPLATE = """# Virtual Metals Trading Desk — one-page summary

**A simulated physical aluminium-scrap import desk into India, built to be defended in a physical-trading interview.** It buys {grades} on {lanes}, sells to Indian smelters and hedges on MCX and in USD/INR forwards, through the real {window_start} to {window_end} market, including the {ath_date} LME record close and the crash after it.

> **{sim_label}.** Counterparties, vessels, banks, tickets and events are fictional (SIM). Market data is real where a public source exists, otherwise flagged PROXY or ASSUMPTION. Every number is filled from the published tables by code, with its source file named.

## The desk in numbers

| Tickets | Tonnes | Containers | Grades · lanes | Counterparties | Traded | Ex-ante trade rule |
|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **{n_trades}** | **{book_mt}{NB}MT** | **{book_boxes}** | **{n_grades}** · **{n_lanes}** | {n_suppliers} suppliers, {n_buyers} buyers | {first_td} to {last_td} | **{elig_pass} of {elig_n}** tickets pass |

Rule declared before any parity result ([CONTRACTS §5a](../../CONTRACTS.md)): parity window open on the base screen, on the point-in-time grade mix and with conversion cost a step higher. {n_elig_cases} of {n_cases} weekly cases passed ({n_open_base} on the base screen alone) *([parity_weekly.csv](../tables/parity_weekly.csv))*.

## Headline results

<!-- widths: 0.17, 0.83 -->
| Result | Value and source |
|---|---|
| Book P&L to the horizon ({horizon_end}) | **{book_pnl}** ({book_pnl_mt}/MT); {book_pnl_we} at the window end ({window_end}) *([attribution_daily.csv](../tables/attribution_daily.csv))* |
| **…read only with its band** | **{band_lo} to {band_hi}** across the registered `{anchor_key}` grid ({anchor_flag}, verification {anchor_status}); break-even {band_be}{NB}₹/MT inside the grid, so the headline is **not sign-robust** *([pnl_sensitivity_sign_robustness.csv](../tables/pnl_sensitivity_sign_robustness.csv))* |
| Where it came from | {buckets}; the other {n_rest} buckets {rest_sum}; residual {residual}. Deal margin ({nd_share} of the total) comes from the desk's own sale-pricing rule on that anchor premium *([attribution_daily.csv](../tables/attribution_daily.csv))* |
| Best trade ([post-mortem](post_mortem.pdf) metric) | **{best_tid}**, {best_grade}, {best_lane}: **{best_pnl}** ({best_pnl_mt}/MT). Ranked on worst P&L across {n_reprice} registered re-pricing cases, its floor is {best_floor}: the only ticket positive in every case. {raw_leader} makes more in rupees ({raw_leader_pnl}) but falls to {raw_leader_worst} in its worst case *([pnl_sensitivity_pricing.csv](../tables/pnl_sensitivity_pricing.csv))* |
| Worst trade | **{worst_tid}**, {worst_grade}, {worst_lane}: **{worst_pnl}** ({worst_pnl_mt}/MT); hit its hard stop on {worst_stop} *([attribution_daily.csv](../tables/attribution_daily.csv))* |

![Cumulative book P&L with the anchor-premium band](../charts/{chart_equity}.png) ![Book 95 % one-day VaR, GARCH against the historical window](../charts/{chart_var}.png)

## Risk findings, as they came out

<!-- widths: 0.14, 0.86 -->
| Model | Finding and source |
|---|---|
| Daily 95 % VaR: GARCH(1,1) vs {win}-day history | **Mixed, not the win the spec expected.** Into March GARCH moved hardest (LME vol forecast for {day_after_ath} {g_ath} against {h_ath}; book VaR {var_peak_g} on {var_peak_date} against {var_peak_h}). But on the declared {pctl}-percentile alert rule the {win}-day window crossed first ({h_cross}, {lead} trading days before GARCH), and into the {cf_start} crash fortnight GARCH ({g_cf}) sat below both windows ({h_cf} at {win} days, {h60_cf} at {win_fast}). Mean VaR, {var_n} days: {var_mean_g} against {var_mean_h} *([var_summary.csv](../tables/var_summary.csv), [var_lead_lag.csv](../tables/var_lead_lag.csv))* |
| Kupiec backtest | Book: {exc_g} GARCH and {exc_h} window exceptions against {exc_exp} expected. Neither is rejected, but the test accepts {kmin} to {kmax} here, so it cannot separate them. On a fixed LME long, {unit_from}–{unit_to}, neither is rejected either; taking {fail_year} alone, the {win}-day window is rejected and GARCH is not *([kupiec.csv](../tables/kupiec.csv))* |
| Monte Carlo, {n_paths} paths, 99 % {mc_h}-day VaR | On three dates fixed by rule: {mc_ath} on {ath1_date} (no MCX hedge yet), {mc_apr} on {apr_date}, {mc_jul} on {jul_date}. An MCX basis factor lifts the last two to {mc_apr_basis} and {mc_jul_basis}: on the near-flat {jul_date} book, basis is most of the risk. Beyond every path: {beyond} *([mc_summary.csv](../tables/mc_summary.csv), [mc_stress_scenarios.csv](../tables/mc_stress_scenarios.csv))* |
| Credit scoring (logistic) | Riskiest first: {credit}. {rjk}'s contracted exposure reached {rjk_contracted} its line, which the model cuts from {rjk_limit} to {rjk_new_limit}. **Illustrative:** fitted on {n_synth} synthetic buyer-quarters; profiles written by the book's author *([credit_scores.csv](../tables/credit_scores.csv))* |
| Liquidity and margin | **The book did not fit its bank lines.** Funding need peaked at {funding_peak} on {funding_date} against a {wc_limit} line sized on the plan's average balance: {fb_days} days over (none on a line one {wc_step} step higher). LCs peaked at {lc_peak} against {lc_limit} ({lc_days} days over, face plus tolerance). Peak MCX initial margin {im_peak} ({im_date}) *([margin_liquidity_summary.csv](../tables/margin_liquidity_summary.csv))* |
| Sentiment overlay (VADER) | {n_headlines} real headlines over {n_weeks} weeks: {n_sig} of {n_lead} lead tests significant, so no evidence that headline tone led LME. The March spike could not be tested, and {n_weeks} weeks can only rule out a strong lead *([sentiment_summary.csv](../tables/sentiment_summary.csv))* |

<!-- columns -->
## What is real, a proxy or an assumption

<!-- widths: 0.33, 0.15, 0.14, 0.23, 0.15 -->
| Count | DIRECT | PROXY | ASSUMPTION | Total |
|---|--:|--:|--:|--:|
| Parameters (register) | {p_direct} | {p_proxy} | {p_assump} | {p_total} |
| Market-panel columns | {sp_direct} | {sp_proxy} | {sp_assump} | {sp_total} |

Parameter verification: {v_verified} VERIFIED, {v_partial} PARTIAL, {v_pending} PENDING, {v_na} N/A (desk policy or model design).

- **Biggest proxy: MCX** at duty-paid import parity, one-for-one with LME × USD/INR, so hedges look perfect. A third-party mirror gives weekly beta {beta_w}; at that beta mean GARCH VaR is {var_beta_w}, not {var_mean_g}.
- **Reconstructed: freight and grade factors.** Freight levels are hindsight-calibrated; the grade path uses later data. On the point-in-time grade mix the book makes {pit_pnl} and grade spread turns {pit_grade}.
<!-- column-break -->
## Where to look

- [README.md](../../README.md) (method, re-run steps, caveats) and [docs/INDEX.md](../../docs/INDEX.md) (every spec row mapped to its files).
- In `outputs/reports/`: {n_desk_notes} weekly desk notes, the {pm_pages}-page [post-mortem](post_mortem.pdf) on {best_tid}, the one-page [risk policy memo](risk_policy_memo.pdf) and the {n_questions}-question [interview pack](interview_pack.pdf).
- [Metals_Desk_Master.xlsx](../excel/Metals_Desk_Master.xlsx): formula-driven parity, book and P&L attribution; {recon}.

## Built with

Python (pandas, arch, SciPy, scikit-learn, matplotlib, reportlab, VADER); formula-driven Excel (openpyxl, recalculated outside Excel with `formulas`). Seeded, staged through files: `DESK_OFFLINE=1 python run_all.py` rebuilds everything offline from cached raw data.
<!-- end-columns -->
"""


def render_markdown(facts: Mapping[str, str]) -> str:
    return TEMPLATE.format_map({**facts, "NB": NB})


def build_markdown(src: Mapping) -> tuple[str, dict]:
    raw = compute_raw(src)
    failed = check_claims(raw)
    if failed:
        raise ValueError("one-pager prose no longer matches the data: " + "; ".join(failed))
    return render_markdown(format_facts(raw)), raw


# ------------------------------------------------------------------------------------------------ charts
_RC = {"font.size": 8.0, "axes.titlesize": 9.2, "axes.titleweight": "bold", "axes.labelsize": 8.0,
       "xtick.labelsize": 7.6, "ytick.labelsize": 7.6, "legend.fontsize": 7.2, "axes.grid": True, "grid.alpha": 0.3,
       "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False}


def _month_axis(ax) -> None:
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))


def chart_equity(src: Mapping, raw: Mapping) -> str:
    """Cumulative book P&L to the horizon, with the anchor-premium band drawn as a bar at the horizon."""
    att = src["att"]
    bk = att[att["trade_id"] == "BOOK"].sort_values("date")
    d = pd.to_datetime(bk["date"])
    x_h = pd.Timestamp(HORIZON_END)
    lo, hi, pnl = raw["band_lo"] / M, raw["band_hi"] / M, raw["book_pnl"] / M
    with plt.rc_context(_RC):
        fig, ax = plt.subplots(figsize=FIG_SIZE_IN)
        ax.axvspan(pd.Timestamp(WINDOW_START), pd.Timestamp(WINDOW_END), color=PALETTE["band"], alpha=0.55, lw=0,
                   label=f"{WINDOW_START:%b}–{WINDOW_END:%b} trading window")
        ax.axhline(0, color="black", lw=0.6)
        ax.plot(d, bk["cum_pnl_inr"] / M, color=PALETTE["pnl"], lw=1.6, label="cumulative book P&L")
        ax.vlines(x_h, lo, hi, color=PALETTE["loss"], lw=2.4, label=f"anchor-premium band at {day(HORIZON_END)}")
        ax.plot([x_h, x_h], [lo, hi], ls="none", marker="_", ms=9, mew=2.0, color=PALETTE["loss"])
        ax.plot([x_h], [pnl], "o", ms=4.5, color=PALETTE["pnl"], zorder=5)
        ax.annotate(f"{inr_m(raw['band_hi'], sign=True)}", (x_h, hi), xytext=(-5, -1), textcoords="offset points",
                    ha="right", va="center", fontsize=7.4, color=PALETTE["loss"])
        ax.annotate(f"{inr_m(raw['band_lo'], sign=True)}", (x_h, lo), xytext=(-5, 1), textcoords="offset points",
                    ha="right", va="center", fontsize=7.4, color=PALETTE["loss"])
        ax.annotate(f"headline {inr_m(raw['book_pnl'])}\nnot sign-robust", (x_h, pnl), xytext=(-8, 7),
                    textcoords="offset points", ha="right", va="bottom", fontsize=7.4, color=PALETTE["pnl"],
                    fontweight="bold")
        ax.set_ylim(lo * 1.25, hi * 1.12)
        ax.set_xlim(pd.Timestamp(WINDOW_START) - pd.Timedelta(days=4), x_h + pd.Timedelta(days=9))
        ax.set_ylabel("₹ million")
        ax.set_title("Cumulative book P&L and its band", loc="left")
        _month_axis(ax)
        ax.legend(loc="upper left", ncol=1, handlelength=1.6)
        return save_fig(fig, CHART_EQUITY, "attribution_daily.csv; band: pnl_sensitivity_sign_robustness.csv")


def chart_var(src: Mapping, raw: Mapping) -> str:
    """Book 95 % one-day VaR on position days: GARCH against the 250-day window, exceptions marked."""
    v = src["var_daily"]
    v = v[v["in_window"]].copy()
    d = pd.to_datetime(v["date"])
    held = v["position_held"].astype(bool)
    g = (v["var_garch_inr"] / M).where(held)
    h = (v["var_hist250_inr"] / M).where(held)
    loss = -v["pnl_market_inr"] / M
    eg, eh = v["exception_garch"].astype(bool) & held, v["exception_hist250"].astype(bool) & held
    with plt.rc_context(_RC):
        fig, ax = plt.subplots(figsize=FIG_SIZE_IN)
        ax.axvspan(pd.Timestamp(raw["q12_cf_start"]), pd.Timestamp(raw["q12_cf_end"]), color=PALETTE["neutral"],
                   alpha=0.16, lw=0, label="crash fortnight")
        ax.plot(d, g, color=PALETTE["garch"], lw=1.2, label=f"GARCH(1,1): {num(int(eg.sum()))} exceptions")
        ax.plot(d, h, color=PALETTE["hist"], lw=1.2, label=f"{num(raw['win_base'])}-day window: {num(int(eh.sum()))} exceptions")
        ax.plot(d[eg], loss[eg], ls="none", marker="v", ms=4.2, color=PALETTE["garch"],
                label="day's loss, beyond GARCH VaR")
        ax.plot(d[eh], loss[eh], ls="none", marker="o", ms=5.6, mfc="none", mew=0.9, color=PALETTE["hist"],
                label="day's loss, beyond window VaR")
        pk = pd.Timestamp(raw["var_peak_date"])
        ax.annotate(f"GARCH {inr_m(raw['var_peak_g'])} on {day(raw['var_peak_date'])}\n"
                    f"window {inr_m(raw['var_peak_h'])}", (pk, raw["var_peak_g"] / M), xytext=(10, -2),
                    textcoords="offset points", ha="left", va="top", fontsize=7.4, color=PALETTE["garch"])
        ax.set_ylim(0, raw["var_peak_g"] / M * 1.08)
        ax.set_xlim(pd.Timestamp(WINDOW_START) - pd.Timedelta(days=3), pd.Timestamp(WINDOW_END) + pd.Timedelta(days=3))
        ax.set_ylabel("₹ million, one day")
        ax.set_title(f"Book 95 % one-day VaR, {num(raw['var_n_pos'])} position days", loc="left")
        _month_axis(ax)
        ax.legend(loc="upper right", ncol=1, handlelength=1.6)
        return save_fig(fig, CHART_VAR, "var_daily.csv; LME DIRECT, USD/INR and MCX PROXY; book SIM")


# ------------------------------------------------------------------------------------------------ PDF
_IMG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\([^)]+\)")


def _figure_row(paths: list[Path], avail_w: float) -> Table:
    col_w = avail_w / len(paths)
    cells = []
    for p in paths:
        iw, ih = ImageReader(str(p)).getSize()
        w = col_w - FIG_GAP_MM * mm
        cells.append(Image(str(p), width=w, height=w * ih / iw))
    t = Table([cells], colWidths=[col_w] * len(paths))
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (0, -1), "LEFT"),
                           ("ALIGN", (-1, 0), (-1, -1), "RIGHT")]))
    return t


def _columns(chunks: list[str], style: PdfStyle, avail_w: float) -> Table:
    """Side-by-side Markdown chunks; each column is laid out with its own width (tables size to the column)."""
    gap = COLUMN_GAP_MM * mm
    col_w = (avail_w - gap * (len(chunks) - 1)) / len(chunks)
    side = (style.margin_left_mm + style.margin_right_mm) * mm
    col_style = dataclasses.replace(style, pagesize=(col_w + side, style.pagesize[1]))
    cells = [markdown_to_flowables(c, col_style) for c in chunks]
    widths = []
    for i in range(len(chunks)):
        widths.append(col_w + (gap if i < len(chunks) - 1 else 0))
    t = Table([cells], colWidths=widths)
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-2, -1), gap), ("TOPPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def render_pdf(md: str, out_path: Path, style: PdfStyle = ONE_PAGER_STYLE) -> int:
    """Markdown -> PDF through the shared renderer, plus a figure row and a two-column block. Returns the page count."""
    register_fonts()
    avail_w = style.pagesize[0] - (style.margin_left_mm + style.margin_right_mm) * mm
    flow: list = []
    buf: list[str] = []
    cols: list[list[str]] | None = None

    def flush() -> None:
        if buf:
            flow.extend(markdown_to_flowables(_LINK.sub(r"\1", "\n".join(buf)), style))
            buf.clear()

    for line in md.split("\n"):
        s = line.strip()
        imgs = _IMG.findall(s)
        if cols is not None:
            if s == COLUMN_BREAK:
                cols.append([])
            elif s == END_COLUMNS:
                flow.append(Spacer(1, COLUMN_SPACE_BEFORE_PT))
                flow.append(_columns([_LINK.sub(r"\1", "\n".join(c)) for c in cols], style, avail_w))
                cols = None
            else:
                cols[-1].append(line)
        elif s == COLUMNS:
            flush()
            cols = [[]]
        elif imgs and not _IMG.sub("", s).strip():
            flush()
            flow.append(_figure_row([(out_path.parent / p).resolve() for p in imgs], avail_w))
        else:
            buf.append(line)
    if cols is not None:
        raise ValueError(f"unclosed {COLUMNS} block")
    flush()
    doc = DeskDocTemplate(str(out_path), style, title="Virtual Metals Trading Desk: one-page summary (SIM)",
                          author="Aluminium scrap desk (SIM)", subject=SIM_LABEL, creator="desk.reporting.one_pager")
    sink: list[int] = []
    doc.build(flow, canvasmaker=_numbered_canvas_class(SIM_LABEL, style, sink))
    return sink[-1] if sink else 0


# ------------------------------------------------------------------------------------------------ stage
def main() -> None:
    src = load_sources()
    md, raw = build_markdown(src)
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    chart_equity(src, raw)
    chart_var(src, raw)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path, pdf_path = REPORTS_DIR / f"{NAME}.md", REPORTS_DIR / f"{NAME}.pdf"
    md_path.write_text(md, encoding="utf-8")
    n = render_pdf(md, pdf_path)
    if n != MAX_PAGES or count_pdf_pages(pdf_path) != MAX_PAGES:
        raise ValueError(f"the one-pager must be exactly {MAX_PAGES} A4 page; rendered {n}")
    st: recon_status.ReconStatus = src["recon"]
    print(f"[1pg ] one-pager written ({n} page); Excel reconciliation: {st.status}")


if __name__ == "__main__":
    main()
