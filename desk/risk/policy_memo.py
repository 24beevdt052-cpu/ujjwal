"""One-page risk policy memo (MASTER_SPEC Table 6 row 4.6), written against the book's own numbers.

The memo is a desk document, so its limits are judgements — they live in config/params/risk.yaml as `policy_*`
ASSUMPTIONS. What this module adds is the part a committee should insist on: for every limit it recomputes, from the
published tables, the evidence the limit was set against and **whether the 2022 book would have breached it**, and
it prints both next to the limit. A limit the book breached is reported with the date and a remediation, never
quietly widened until the book fits.

Conventions:
* Exposure checks that include the MCX leg skip the 16 position dates Phase 4.1 flags as MCX exit/roll days
  (`var_daily.csv` `position_date_mcx_exit_or_roll`): the P3 exposure on those closes still carries the contract that
  closed (docs/40 §7.1), so a net or VaR figure there is an artefact. Physical-only checks use every day.
* Stop-loss and booking checks read the PREVIOUS close (what the desk knew when it signed that day).
* The memo is dated `policy_memo_date`, after the last input it quotes (HORIZON_END 2022-10-31).

Outputs: outputs/tables/margin_liquidity_policy_limits.csv, outputs/reports/risk_policy_memo.md and .pdf (one A4 page,
asserted).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from desk import HORIZON_END, SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.paths import PROCESSED_DIR, REPORTS_DIR, TABLES_DIR
from desk.reporting.pdf import PdfStyle, count_pdf_pages, render_markdown_pdf

MEMO_NAME = "risk_policy_memo"
MAX_PAGES = 1
LIMITS_TABLE = "margin_liquidity_policy_limits"
FLOAT_DECIMALS = 6
M = 1e6
NB = "\u00a0"  # non-breaking space: a number never wraps away from its unit in the one-page layout
# sized to fill about 94 % of the page: readable, with room for the numbers to move without a second page
MEMO_STYLE = PdfStyle(font_size=8.3, table_font_size=7.6, title_size=12.0, h2_size=8.6, h3_size=8.0,
                      margin_left_mm=11.0, margin_right_mm=11.0, margin_top_mm=9.0, margin_bottom_mm=11.0,
                      leading_ratio=1.18, paragraph_space_after=2.2, heading_space_before=2.6,
                      footer_font_size=6.3)


# ------------------------------------------------------------------------------------------------ formatting
def inr_m(x: float, dp: int = 1, sign: bool = False) -> str:
    s = f"{abs(x) / M:,.{dp}f}"
    if x < 0:
        return f"−₹{s}{NB}m"
    return f"+₹{s}{NB}m" if sign else f"₹{s}{NB}m"


def usd_m(x: float, dp: int = 2) -> str:
    return f"USD{NB}{x / M:,.{dp}f}{NB}m"


def mt(x: float) -> str:
    return f"{x:,.0f}{NB}MT"


def num(x: float, dp: int = 0) -> str:
    """Thousands-separated number with a true minus sign (U+2212), as printed everywhere in the pack."""
    s = f"{abs(x):,.{dp}f}"
    return f"−{s}" if x < 0 else s


def pct(x: float, dp: int = 1) -> str:
    return f"{x * 100:.{dp}f}{NB}%"


def day(d: str) -> str:
    return pd.Timestamp(d).strftime("%-d-%b")


# ------------------------------------------------------------------------------------------------ sources
def load_sources() -> dict[str, pd.DataFrame]:
    T = TABLES_DIR
    ex = pd.read_csv(T / "book_exposures_daily.csv",
                     usecols=["date", "scope", "trade_id", "lme_delta_mt", "lme_delta_usd", "lme_delta_physical_mt",
                              "unsold_mt"])
    return {
        "book": ex[ex["scope"] == "book"].set_index("date"),
        "market": pd.read_csv(PROCESSED_DIR / "market_daily.csv", usecols=["date", "lme_cash_usd_t"]).set_index("date"),
        "var_daily": pd.read_csv(T / "var_daily.csv", usecols=["date", "in_window", "position_held", "position_date",
                                                               "position_date_mcx_exit_or_roll", "var_garch_inr",
                                                               "var_hist250_inr", "memo_pnl_grade_spread_inr"]),
        "var_summary": pd.read_csv(T / "var_summary.csv").set_index("metric"),
        "att": pd.read_csv(T / "attribution_daily.csv", usecols=["date", "trade_id", "cum_pnl_inr"]),
        "trade_book": pd.read_csv(T / "trade_book.csv", usecols=["trade_id", "trade_date", "grade", "incoterm",
                                                                 "freight_fixture_date", "freight_rate_usd_box",
                                                                 "freight_stop_loss_usd_box", "fx_hedge_frac_target"]),
        "hedges": pd.read_csv(T / "trade_hedges.csv", usecols=["trade_id", "instrument", "hedge_ratio_target",
                                                               "hedge_ratio_actual"]),
        "vm": pd.read_csv(T / "mcx_variation_margin.csv", usecols=["date", "hedge_id", "action", "roll_deadline"]),
        "band_policy": pd.read_csv(T / "credit_band_policy.csv").set_index("band"),
        "scores": pd.read_csv(T / "credit_scores.csv").set_index("cp_id"),
        "bookings": pd.read_csv(T / "credit_tracker_bookings.csv"),
        "tracker": pd.read_csv(T / "credit_tracker.csv", usecols=["date", "cp_id", "advance_reliance_multiple",
                                                                  "flag_performance_advance_p14"]),
        "freight_stress": pd.read_csv(T / "adverse_event_3_freight_stress_hypothetical.csv"),
        "sign": pd.read_csv(T / "pnl_sensitivity_sign_robustness.csv").set_index("family"),
        "basis": pd.read_csv(T / "mcx_basis_risk.csv").set_index("metric"),
        "mcx_beta": pd.read_csv(T / "var_mcx_beta.csv").set_index("sampling"),
        "liq": pd.read_csv(T / "margin_liquidity.csv"),
        "liq_summary": pd.read_csv(T / "margin_liquidity_summary.csv"),
        "liq_grid": pd.read_csv(T / "margin_liquidity_limit_grid.csv"),
    }


def summary_value(summary: pd.DataFrame, metric: str, scope: str = "book") -> tuple[str, str]:
    r = summary[(summary["metric"] == metric) & (summary["scope"] == scope)]
    if len(r) != 1:
        raise KeyError(f"margin_liquidity_summary.csv has no unique ({metric}, {scope})")
    return str(r["value"].iloc[0]), str(r["note"].iloc[0])


def clean_position_dates(var_daily: pd.DataFrame) -> set[str]:
    return set(var_daily.loc[var_daily["position_date_mcx_exit_or_roll"], "position_date"])


def drawdowns(att: pd.DataFrame, trade_id: str) -> pd.DataFrame:
    s = att[att["trade_id"] == trade_id].set_index("date")["cum_pnl_inr"].sort_index()
    return pd.DataFrame({"cum": s, "peak": s.cummax(), "dd": s - s.cummax()})


# ------------------------------------------------------------------------------------------------ evaluation
def evaluate(src: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    """Every limit, the book evidence behind it, and the book's record against it."""
    v = config.value
    ev: dict = {}
    rows: list[dict] = []

    def add(limit_id, area, param_key, limit_value, unit, evidence, source, days_checked, breach_dates, remediation):
        rows.append({"limit_id": limit_id, "area": area, "param_key": param_key, "limit_value": limit_value,
                     "unit": unit, "evidence": evidence, "source": source, "days_checked": days_checked,
                     "days_breached": len(breach_dates),
                     "first_breach": breach_dates[0] if breach_dates else "",
                     "last_breach": breach_dates[-1] if breach_dates else "",
                     "breach_dates": ";".join(breach_dates),
                     "book_verdict": "BREACHED" if breach_dates else "WITHIN",
                     "remediation": remediation})

    book = src["book"]
    win = book[(book.index >= str(WINDOW_START)) & (book.index <= str(WINDOW_END))].copy()
    win["lme_cash_usd_t"] = src["market"].loc[win.index, "lme_cash_usd_t"]
    win["phys_usd"] = win["lme_delta_physical_mt"] * win["lme_cash_usd_t"]
    stale = clean_position_dates(src["var_daily"])
    clean = win[~win.index.isin(stale)]
    ev["n_stale_dates"] = len(stale)

    # --- position limits (physical only: every day) ---------------------------------------------------------------
    lim_mt, lim_usd = float(v("policy_max_physical_open_mt")), float(v("policy_max_physical_open_usd"))
    ev["phys_mt_peak"], ev["phys_mt_peak_date"] = float(win["lme_delta_physical_mt"].max()), win[
        "lme_delta_physical_mt"].idxmax()
    ev["phys_usd_peak"], ev["phys_usd_peak_date"] = float(win["phys_usd"].max()), win["phys_usd"].idxmax()
    ev["unsold_peak"], ev["unsold_peak_date"] = float(win["unsold_mt"].max()), win["unsold_mt"].idxmax()
    add("POS_GROSS_MT", "position", "policy_max_physical_open_mt", lim_mt, "mt",
        f"peak {mt(ev['phys_mt_peak'])} on {ev['phys_mt_peak_date']}; unsold peak {mt(ev['unsold_peak'])} on "
        f"{ev['unsold_peak_date']}", "book_exposures_daily.csv BOOK lme_delta_physical_mt, unsold_mt", len(win),
        list(win.index[win["lme_delta_physical_mt"] > lim_mt]), "")
    add("POS_GROSS_USD", "position", "policy_max_physical_open_usd", lim_usd, "usd",
        f"peak {usd_m(ev['phys_usd_peak'])} on {ev['phys_usd_peak_date']}",
        "book_exposures_daily.csv lme_delta_physical_mt x market_daily.csv lme_cash_usd_t", len(win),
        list(win.index[win["phys_usd"] > lim_usd]), "")

    # --- net unhedged (clean days) ---------------------------------------------------------------------------------
    lim_net, lim_net_usd = float(v("policy_max_net_unhedged_mt")), float(v("policy_max_net_unhedged_usd"))
    lim_frac, min_phys = float(v("policy_max_unhedged_frac")), float(v("policy_unhedged_frac_min_physical_mt"))
    absnet = clean["lme_delta_mt"].abs()
    ev["net_mt_p95"] = float(absnet.quantile(0.95))
    ev["net_mt_max"], ev["net_mt_max_date"] = float(absnet.max()), absnet.idxmax()
    ev["net_usd_max"] = float(clean["lme_delta_usd"].abs().max())
    net_dates = list(clean.index[absnet > lim_net])
    usd_dates = list(clean.index[clean["lme_delta_usd"].abs() > lim_net_usd])
    big = clean[clean["lme_delta_physical_mt"] >= min_phys]
    frac = (big["lme_delta_mt"] / big["lme_delta_physical_mt"]).abs()
    frac_dates = list(big.index[frac > lim_frac])
    ev["frac_days_checked"] = len(big)
    rem_net = "rebalance MCX within 2 sessions of a breach; no purchase before its hedge can be placed"
    add("NET_UNHEDGED_MT", "unhedged", "policy_max_net_unhedged_mt", lim_net, "mt",
        f"absolute net 95th pct {mt(ev['net_mt_p95'])}; max {mt(ev['net_mt_max'])} on {ev['net_mt_max_date']}",
        "book_exposures_daily.csv BOOK lme_delta_mt, clean days", len(clean), net_dates, rem_net)
    add("NET_UNHEDGED_USD", "unhedged", "policy_max_net_unhedged_usd", lim_net_usd, "usd",
        f"absolute net max {usd_m(ev['net_usd_max'])}", "book_exposures_daily.csv BOOK lme_delta_usd, clean days",
        len(clean), usd_dates, rem_net)
    add("UNHEDGED_FRAC", "unhedged", "policy_max_unhedged_frac", lim_frac, "frac",
        f"absolute net / physical above {pct(lim_frac, 0)} on days with physical ≥ {mt(min_phys)}",
        "book_exposures_daily.csv lme_delta_mt / lme_delta_physical_mt, clean days", len(big), frac_dates, rem_net)

    # --- hedge policy ----------------------------------------------------------------------------------------------
    lo, hi = (float(x) for x in v("policy_mcx_hedge_ratio_band_frac"))
    h = src["hedges"][src["hedges"]["instrument"] == "MCX_ALUMINIUM_FUTURE"]
    per = h.groupby("trade_id")["hedge_ratio_actual"].agg(["min", "max"])
    outside = per[(per["min"] < lo) | (per["max"] > hi)]
    inside = per.drop(outside.index)
    ev["hedge_inside_min"], ev["hedge_inside_max"] = float(inside["min"].min()), float(inside["max"].max())
    ev["hedge_inside_n"] = len(inside)
    ev["hedge_outside"] = {t: float(r["min"]) for t, r in outside.iterrows()}
    add("MCX_HEDGE_RATIO", "hedge", "policy_mcx_hedge_ratio_band_frac", f"{lo:.2f}-{hi:.2f}", "frac",
        f"{len(inside)} tickets {ev['hedge_inside_min']:.3f}-{ev['hedge_inside_max']:.3f}; outside: "
        + ", ".join(f"{t} {x:.2f}" for t, x in ev["hedge_outside"].items()),
        "trade_hedges.csv hedge_ratio_actual (MCX)", len(per), list(outside.index),
        "prior committee approval for any ratio outside the band")
    rolls = src["vm"][src["vm"]["action"] == "roll_out"]
    late = rolls[rolls["date"] > rolls["roll_deadline"]]
    ev["rolls_n"], ev["rolls_late"] = len(rolls), len(late)
    ev["roll_days"] = int(v("mcx_roll_days_before_expiry"))
    add("MCX_ROLL", "hedge", "mcx_roll_days_before_expiry", ev["roll_days"], "trading_days_before_expiry",
        f"{len(rolls) - len(late)} of {len(rolls)} rolls on or before the deadline",
        "mcx_variation_margin.csv roll_out date vs roll_deadline", len(rolls), list(late["date"]), "")
    fx_min = float(v("policy_fx_forward_cover_min_frac"))
    tb = src["trade_book"]
    fx_low = tb[tb["fx_hedge_frac_target"] < fx_min]
    ev["fx_low"] = {r.trade_id: float(r.fx_hedge_frac_target) for r in fx_low.itertuples()}
    add("FX_COVER", "hedge", "policy_fx_forward_cover_min_frac", fx_min, "frac",
        f"{len(tb) - len(fx_low)} tickets at 100 %; " + ", ".join(f"{t} {pct(x, 0)}" for t, x in ev["fx_low"].items()),
        "trade_book.csv fx_hedge_frac_target", len(tb), list(fx_low["trade_id"]),
        "cover to ≥ 90 % or take a committee exception")

    # --- stop-loss (previous-close reading) ------------------------------------------------------------------------
    rev, hard, bstop = (float(v(k)) for k in ("policy_stop_ticket_review_inr", "policy_stop_ticket_hard_inr",
                                             "policy_stop_book_drawdown_inr"))
    att = src["att"]
    tickets = sorted(t for t in att["trade_id"].unique() if t != "BOOK")
    dds = {t: drawdowns(att, t) for t in tickets}
    ev["ticket_dd"] = {t: (float(d["dd"].min()), d["dd"].idxmin()) for t, d in dds.items()}
    review = {t: d.index[d["dd"] <= -rev][0] for t, d in dds.items() if (d["dd"] <= -rev).any()}
    hard_hit = {t: d.index[d["dd"] <= -hard][0] for t, d in dds.items() if (d["dd"] <= -hard).any()}
    ev["review_tickets"], ev["hard_tickets"] = review, hard_hit
    bk = drawdowns(att, "BOOK")
    trough = bk["dd"].idxmin()
    ev["book_dd"], ev["book_dd_trough"] = float(bk["dd"].min()), trough
    ev["book_dd_peak_date"] = bk.loc[:trough, "cum"].idxmax()
    ev["book_stop_first"] = bk.index[bk["dd"] <= -bstop][0] if (bk["dd"] <= -bstop).any() else ""
    # purchases signed while a stop was live at the previous close
    blocked = []
    for r in tb.sort_values("trade_date").itertuples():
        prev = bk.index[bk.index < r.trade_date]
        if not len(prev):
            continue
        p = prev[-1]
        why = []
        if bk.at[p, "dd"] <= -bstop:
            why.append(f"book {inr_m(bk.at[p, 'dd'])}")
        for t, d in dds.items():
            same = tb.loc[tb["trade_id"] == t, "grade"].iloc[0] == r.grade and t != r.trade_id
            if same and p in d.index and d.at[p, "dd"] <= -hard:
                why.append(f"{t} {inr_m(d.at[p, 'dd'])}")
        if why:
            blocked.append((r.trade_id, r.trade_date, p, why))
    ev["blocked"] = blocked
    final = att[att["date"] == str(HORIZON_END)].set_index("trade_id")["cum_pnl_inr"]
    ev["final_pnl"] = final.to_dict()
    add("STOP_TICKET_REVIEW", "stop_loss", "policy_stop_ticket_review_inr", rev, "inr",
        "; ".join(f"{t} {inr_m(ev['ticket_dd'][t][0])}" for t in sorted(review, key=lambda t: ev["ticket_dd"][t][0])),
        "attribution_daily.csv per-ticket cum_pnl_inr drawdown from its own peak", len(tickets),
        [f"{t}@{review[t]}" for t in sorted(review, key=lambda t: review[t])], "same-day review with head of desk")
    add("STOP_TICKET_HARD", "stop_loss", "policy_stop_ticket_hard_inr", hard, "inr",
        "; ".join(f"{t} first {hard_hit[t]}" for t in sorted(hard_hit)), "attribution_daily.csv", len(tickets),
        [f"{t}@{hard_hit[t]}" for t in sorted(hard_hit)], "hedge ticket to 1.0; no same-grade additions until closed")
    add("STOP_BOOK", "stop_loss", "policy_stop_book_drawdown_inr", bstop, "inr",
        f"book {inr_m(ev['book_dd'])} from {ev['book_dd_peak_date']} to {trough}",
        "attribution_daily.csv BOOK cum_pnl_inr", int(len(bk)),
        list(bk.index[bk["dd"] <= -bstop]), "no new purchases until committee review")
    add("STOP_BLOCKED_PURCHASES", "stop_loss", "policy_stop_book_drawdown_inr; policy_stop_ticket_hard_inr", "", "",
        "; ".join(f"{t} on {d} (prev close {p}: {', '.join(w)})" for t, d, p, w in blocked),
        "trade_book.csv trade_date vs drawdowns at the previous close", len(tb), [f"{t}@{d}" for t, d, _, _ in blocked],
        "purchase would have been refused")

    # --- VaR -------------------------------------------------------------------------------------------------------
    var_lim = float(v("policy_var_limit_inr"))
    vd = src["var_daily"]
    vd = vd[vd["in_window"] & vd["position_held"]].copy()
    ev["var_position_days"] = len(vd)
    vd["limit_var"] = vd[["var_garch_inr", "var_hist250_inr"]].max(axis=1)
    vclean = vd[~vd["position_date_mcx_exit_or_roll"]]
    ev["var_mean_garch"] = float(src["var_summary"].at["var_mean_garch", "value"])
    ev["var_max_garch"] = float(src["var_summary"].at["var_max_garch", "value"])
    ev["var_max_garch_note"] = str(src["var_summary"].at["var_max_garch", "note"])
    ev["var_breach_all_days"] = int((vd["limit_var"] > var_lim).sum())
    ev["var_beta_mean"] = float(src["var_summary"].at["garch_var_mcx_beta_sensitivity_mean", "value"])
    ev["mcx_beta"] = float(src["basis"].at["unit_beta_beta", "value"])
    mb = src["mcx_beta"]
    if abs(float(mb.at["daily", "beta"]) - ev["mcx_beta"]) > 1e-6:
        raise ValueError("var_mcx_beta.csv daily beta disagrees with mcx_basis_risk.csv")
    ev["mcx_beta_weekly"] = float(mb.at["weekly", "beta"])
    ev["var_beta_weekly_mean"] = float(src["var_summary"].at["garch_var_mcx_beta_weekly_sensitivity_mean", "value"])
    # what the VaR limit does not cover: grade spread (not a VaR factor) and the cash-3M spread (memo VaR)
    ev["grade_pnl_std"] = float(vd["memo_pnl_grade_spread_inr"].std())
    ev["spread_var_uplift"] = float(src["var_summary"].at["garch_var_incl_spread_memo_mean", "value"]) / ev[
        "var_mean_garch"] - 1.0
    add("VAR", "var", "policy_var_limit_inr", var_lim, "inr",
        f"GARCH mean {inr_m(ev['var_mean_garch'], 2)}, max {inr_m(ev['var_max_garch'])} ({ev['var_max_garch_note']})",
        "var_daily.csv max(var_garch_inr, var_hist250_inr), clean position dates", len(vclean),
        list(vclean.loc[vclean["limit_var"] > var_lim, "date"]), "cut the position that drives it the same day")

    # --- counterparty ----------------------------------------------------------------------------------------------
    sc, bp = src["scores"], src["band_policy"]
    bookings = src["bookings"]
    outside_b = bookings[bookings["band_policy_verdict"] == "OUTSIDE_BAND_POLICY"]
    rjk = src["tracker"][src["tracker"]["cp_id"] == "BUY_RJK_01"]
    ev["rjk_band"] = str(sc.at["BUY_RJK_01", "band_final"])
    ev["rjk_pd"] = float(sc.at["BUY_RJK_01", "pd_model_annual_frac"])
    ev["rjk_limit"], ev["rjk_rec_limit"] = float(sc.at["BUY_RJK_01", "credit_limit_inr"]), float(
        sc.at["BUY_RJK_01", "recommended_limit_inr"])
    ev["rjk_adv_days"] = int(rjk["flag_performance_advance_p14"].sum())
    ev["rjk_adv_peak"] = float(rjk["advance_reliance_multiple"].max())
    ev["rjk_contracted_peak"] = float(sc.at["BUY_RJK_01", "contracted_utilisation_peak_to_date_frac"])
    ev["bands"] = {cp: str(sc.at[cp, "band_final"]) for cp in sc.index}
    ev["band_actions"] = {cp: str(sc.at[cp, "limit_action"]).split(" —")[0] for cp in sc.index}
    ev["bookings_outside"], ev["bookings_n"] = len(outside_b), len(bookings)
    ev["band_policy"] = bp
    add("CREDIT_BANDS", "counterparty", "credit_* (risk_credit.yaml) via credit_band_policy.csv",
        "A/B/C/D", "band", f"{len(outside_b)} of {len(bookings)} sale bookings outside the band policy at the previous "
        f"close; BUY_RJK_01 advances > 1.0x limit on {ev['rjk_adv_days']} days (peak {ev['rjk_adv_peak']:.2f}x)",
        "credit_tracker_bookings.csv, credit_tracker.csv, credit_scores.csv", len(bookings),
        [f"{r.trade_id}-{r.sale_id}@{r.contract_date}" for r in outside_b.itertuples()],
        f"BUY_RJK_01 line {inr_m(ev['rjk_limit'], 0)} → {inr_m(ev['rjk_rec_limit'], 0)}, advance/CAD only")

    # --- freight ---------------------------------------------------------------------------------------------------
    fix_lim, stop_lim = int(v("policy_freight_fix_within_bdays")), float(v("policy_freight_stop_max_frac_over_fixture"))
    cal = src["market"].index
    fob = tb[tb["freight_fixture_date"].notna()].copy()
    fob["bdays_to_fix"] = [int(((cal > r.trade_date) & (cal <= r.freight_fixture_date)).sum())
                           for r in fob.itertuples()]
    fob["stop_over_fixture"] = fob["freight_stop_loss_usd_box"] / fob["freight_rate_usd_box"] - 1.0
    ev["freight"] = fob.set_index("trade_id")[["bdays_to_fix", "stop_over_fixture"]].to_dict("index")
    fs = src["freight_stress"]
    ev["freight_stress_t01"] = float(fs.loc[fs["trade_id"] == "T01", "impact_inr"].min())
    ev["freight_var_mean"] = float(src["var_summary"].at["var_freight_hist250_mean", "value"])
    add("FREIGHT_FIX", "freight", "policy_freight_fix_within_bdays", fix_lim, "trading_days",
        ", ".join(f"{t} {r['bdays_to_fix']} d" for t, r in ev["freight"].items()), "trade_book.csv", len(fob),
        list(fob.loc[fob["bdays_to_fix"] > fix_lim, "trade_id"]), "")
    add("FREIGHT_STOP", "freight", "policy_freight_stop_max_frac_over_fixture", stop_lim, "frac",
        ", ".join(f"{t} +{pct(r['stop_over_fixture'])}" for t, r in ev["freight"].items()), "trade_book.csv",
        len(fob), list(fob.loc[fob["stop_over_fixture"] > stop_lim, "trade_id"]), "")

    # --- liquidity (this stage's own tables) -----------------------------------------------------------------------
    liq, ls = src["liq"], src["liq_summary"]
    fac_fb, fac_lc = float(v("liq_fb_wc_limit_inr")), float(v("liq_nfb_lc_limit_inr"))
    buffer = fac_fb * float(v("liq_min_cash_buffer_frac_of_fb_limit"))
    ev.update(fb_limit=fac_fb, lc_limit=fac_lc, buffer=buffer)
    i = liq["funding_need_total_inr"].idxmax()
    ev["need_peak"], ev["need_peak_date"] = float(liq.at[i, "funding_need_total_inr"]), str(liq.at[i, "date"])
    i = liq["lc_outstanding_inr"].idxmax()
    ev["lc_peak"], ev["lc_peak_date"] = float(liq.at[i, "lc_outstanding_inr"]), str(liq.at[i, "date"])
    i = liq["mar_99_stressed_im_inr"].idxmax()
    ev["mar_peak"], ev["mar_peak_date"] = float(liq.at[i, "mar_99_stressed_im_inr"]), str(liq.at[i, "date"])
    i = liq["margin_cash_deployed_inr"].idxmax()
    ev["margin_out_peak"], ev["margin_out_peak_date"] = float(liq.at[i, "margin_cash_deployed_inr"]), str(
        liq.at[i, "date"])
    rule = liq["funding_need_total_inr"] + np.maximum(buffer, liq["mar_99_stressed_im_inr"]) > fac_fb
    ev["mar_over_buffer_days"] = int((liq["mar_99_stressed_im_inr"] > buffer).sum())
    fb_dates = list(liq.loc[liq["flag_fb_limit_breach"], "date"])
    lc_dates = list(liq.loc[liq["flag_lc_limit_breach"], "date"])
    ev["fb_limit_days"] = len(fb_dates)
    ev["crash_move"] = float(summary_value(ls, "stress_move_frac", "CRASH_FORTNIGHT")[0])
    ev["crash_binding"] = summary_value(ls, "stress_move_logret", "CRASH_FORTNIGHT")[1]
    ev["crash_extra"] = float(summary_value(ls, "extra_margin_cash_out_stressed_im_inr_max", "CRASH_FORTNIGHT")[0])
    ev["crash_headroom_actual"] = float(summary_value(ls, "headroom_actual_inr_min", "CRASH_FORTNIGHT")[0])
    ev["crash_headroom_stressed"] = float(summary_value(ls, "headroom_stressed_im_inr_min", "CRASH_FORTNIGHT")[0])
    ev["crash_vm_actual"] = float(summary_value(ls, "vm_actual_sum_inr", "CRASH_FORTNIGHT")[0])
    ev["crash_start"] = summary_value(ls, "window_start", "CRASH_FORTNIGHT")[0]
    ev["crash_end"] = summary_value(ls, "window_end", "CRASH_FORTNIGHT")[0]
    ev["crash_phys_gain"] = float(summary_value(ls, "memo_physical_mtm_gain_end_inr", "CRASH_FORTNIGHT")[0])
    rounding = float(v("liq_facility_rounding_inr"))
    ev["adhoc_fb"] = math.ceil((ev["need_peak"] + buffer - fac_fb) / rounding) * rounding
    ev["adhoc_lc"] = math.ceil((ev["lc_peak"] - fac_lc) / rounding) * rounding
    add("LIQ_BUFFER_RULE", "liquidity", "liq_fb_wc_limit_inr; liq_min_cash_buffer_frac_of_fb_limit", fac_fb, "inr",
        f"peak funding need {inr_m(ev['need_peak'])} on {ev['need_peak_date']}; 99 % margin-at-risk peak "
        f"{inr_m(ev['mar_peak'])} on {ev['mar_peak_date']}", "margin_liquidity.csv", len(liq),
        list(liq.loc[rule, "date"]), f"ad-hoc WC limit {inr_m(ev['adhoc_fb'], 0)} for peak months, or fewer "
                                     "concurrent parcels")
    add("LIQ_FB_LIMIT", "liquidity", "liq_fb_wc_limit_inr", fac_fb, "inr", f"{len(fb_dates)} days drawn above the line",
        "margin_liquidity.csv flag_fb_limit_breach", len(liq), fb_dates, "as LIQ_BUFFER_RULE")
    add("LIQ_LC_LIMIT", "liquidity", "liq_nfb_lc_limit_inr", fac_lc, "inr",
        f"LC outstanding peak {inr_m(ev['lc_peak'])} on {ev['lc_peak_date']}", "margin_liquidity.csv", len(liq),
        lc_dates, f"ad-hoc LC limit {inr_m(ev['adhoc_lc'], 0)}, or open the next LC only after a payment clears")

    # --- context ---------------------------------------------------------------------------------------------------
    allb = src["sign"].loc["ALL_REGISTERED_BANDS"]
    ev["pnl_horizon"] = float(ev["final_pnl"]["BOOK"])
    ev["pnl_band_min"], ev["pnl_band_max"] = float(allb["pnl_min_inr"]), float(allb["pnl_max_inr"])
    ev["breakeven_anchor"] = float(src["sign"].at["anchor_premium", "breakeven_value"])

    limits = pd.DataFrame(rows)
    limits["label"] = SIM_LABEL
    return limits, ev


# ------------------------------------------------------------------------------------------------ memo text
def _lim(limits: pd.DataFrame, limit_id: str) -> pd.Series:
    return limits.set_index("limit_id").loc[limit_id]


def upper_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def _span(r: pd.Series) -> str:
    if not r["days_breached"]:
        return "within"
    if r["days_breached"] == 1:
        return f"breached once ({day(r['first_breach'].split('@')[-1])})"
    return (f"breached {r['days_breached']} days ({day(r['first_breach'].split('@')[-1])}–"
            f"{day(r['last_breach'].split('@')[-1])})")


def render_md(limits: pd.DataFrame, ev: dict) -> str:
    v = config.value
    L = lambda k: _lim(limits, k)  # noqa: E731
    memo_date = pd.Timestamp(v("policy_memo_date"))
    lo, hi = (float(x) for x in v("policy_mcx_hedge_ratio_band_frac"))
    bp = ev["band_policy"]
    ticket_dd = ev["ticket_dd"]
    dd_list = ", ".join(f"{t} {inr_m(ticket_dd[t][0])}" for t in sorted(ev["review_tickets"],
                                                                     key=lambda t: ticket_dd[t][0]))
    blocked = ev["blocked"]
    blk = "; ".join(f"{t} bought {day(d)} would have been refused" for t, d, _, _ in blocked)
    blk_pnl = ", ".join(f"{t} finished {inr_m(ev['final_pnl'][t], sign=True)}" for t, _, _, _ in blocked)
    fr = ev["freight"]
    hard = ev["hard_tickets"]
    t08 = next(iter(hard)) if hard else ""
    unhedged_frac = L("UNHEDGED_FRAC")

    md = f"""# Risk policy memo — aluminium scrap import desk (SIM)

**To:** Risk Committee (SIM) · **From:** Head of Desk (SIM), Meridian Non-Ferrous Trading (SIM) · **Date:** {memo_date.strftime('%-d %B %Y')} · **Re:** limits for the next book, set against what the Mar–Oct 2022 book actually did

> **{SIM_LABEL}.** Book P&L was {inr_m(ev['pnl_horizon'])} at {day(str(HORIZON_END))}-2022, but it is **not sign-robust**: {inr_m(ev['pnl_band_min'])} to {inr_m(ev['pnl_band_max'], sign=True)} across the registered domestic anchor-premium grid (break-even {num(ev['breakeven_anchor'])} ₹/t inside it). So every limit below is sized on the risk the book ran, not on what it earned. Evidence is from the published tables; checks that include the MCX leg skip the {ev['n_stale_dates']} MCX exit/roll position dates P3 flags. Hedge effectiveness is measured on a unit-beta MCX proxy, so the MCX basis is under-represented in every hedge number here. The third-party mirror's beta is {ev['mcx_beta_weekly']:.2f} on weekly closes and {ev['mcx_beta']:.2f} on daily data, which the MCX evening close biases down: mean GARCH VaR is {inr_m(ev['var_beta_weekly_mean'])} at the weekly beta and {inr_m(ev['var_beta_mean'])} at the daily one (the pessimistic end, not a hedge ratio anyone would use), against {inr_m(ev['var_mean_garch'], 2)} on the proxy.

<!-- widths: 0.124, 0.276, 0.31, 0.29 -->
| Area | Limit / rule proposed | Book evidence (2022) | Book vs limit → remediation |
|---|---|---|---|
| **Position** | Gross physical LME exposure ≤ {mt(float(v('policy_max_physical_open_mt')))} and ≤ {usd_m(float(v('policy_max_physical_open_usd')), 0)} | Peak {mt(ev['phys_mt_peak'])} / {usd_m(ev['phys_usd_peak'], 1)} on {day(ev['phys_usd_peak_date'])}; unsold cargo {mt(ev['unsold_peak'])} on {day(ev['unsold_peak_date'])} | Within by construction — the limit was set just above the book's own peak, so this is not evidence; not raised, because that size already used the whole working-capital line (Liquidity row) |
| **Unhedged** | Net LME delta ≤ {mt(float(v('policy_max_net_unhedged_mt')))} and ≤ {usd_m(float(v('policy_max_net_unhedged_usd')), 0)}; net ≤ {pct(float(v('policy_max_unhedged_frac')), 0)} of physical once physical ≥ {mt(float(v('policy_unhedged_frac_min_physical_mt')))} | Absolute net: 95th pct {mt(ev['net_mt_p95'])}; max {mt(ev['net_mt_max'])} ({usd_m(ev['net_usd_max'])}) on {day(ev['net_mt_max_date'])}, the naked session before T01's hedge | MT {_span(L('NET_UNHEDGED_MT'))}; USD {_span(L('NET_UNHEDGED_USD'))}; % breached {unhedged_frac['days_breached']} of {unhedged_frac['days_checked']} days (ratios drift between re-sizings) → rebalance within 2 sessions; no purchase before its hedge can be placed |
| **Hedge** | MCX ratio {lo:.2f}–{hi:.2f} of LME-equivalent physical at every decision; roll ≥ {ev['roll_days']} trading days before expiry, roll gains never budgeted (proxy curve is always contango); FX forwards ≥ {pct(float(v('policy_fx_forward_cover_min_frac')), 0)} of each fixed USD payable, on physical + forwards only | {ev['hedge_inside_n']} tickets filled {ev['hedge_inside_min']:.3f}–{ev['hedge_inside_max']:.3f}; {', '.join(f'{t} at {x:.2f}' for t, x in ev['hedge_outside'].items())}; {ev['rolls_n'] - ev['rolls_late']} of {ev['rolls_n']} rolls by the deadline; FX 100 % except {', '.join(f'{t} {pct(x, 0)}' for t, x in ev['fx_low'].items())} | {', '.join(ev['hedge_outside'])} and {', '.join(ev['fx_low'])} breach → re-size, or a committee exception signed before the trade |
| **Stop-loss** | Ticket {inr_m(-float(v('policy_stop_ticket_review_inr')), 0)} from its own peak: same-day review. Ticket {inr_m(-float(v('policy_stop_ticket_hard_inr')), 0)}: hedge to 1.0, no same-grade additions. Book {inr_m(-float(v('policy_stop_book_drawdown_inr')), 0)} from peak: no new purchase until the committee reviews | Review level hit by {dd_list}; book {inr_m(ev['book_dd'])} ({day(ev['book_dd_peak_date'])}→{day(ev['book_dd_trough'])}), past {inr_m(-float(v('policy_stop_book_drawdown_inr')), 0)} from {day(ev['book_stop_first'])} | {t08} hit its hard stop on {day(hard[t08]) if t08 else ''}, the book its stop from {day(ev['book_stop_first'])}; {blk} (same grade as {t08}). Honest cost: {blk_pnl} on base marks. The levels were chosen with these drawdowns in view, so which tickets trip is illustration, not a test |
| **VaR** | 1-day 95 % VaR ≤ {inr_m(float(v('policy_var_limit_inr')), 0)} on the larger of GARCH(1,1) and 250-day historical (docs/40: the historical is the floor, because GARCH decayed below it into the April–May crash). Covers LME, FX and freight only: grade spread (daily σ {inr_m(ev['grade_pnl_std'])}) and the cash–3M spread (memo VaR +{pct(ev['spread_var_uplift'], 0)}) sit outside it | {ev['var_position_days']} position days: GARCH mean {inr_m(ev['var_mean_garch'], 2)}, max {inr_m(ev['var_max_garch'])} on {day(ev['var_max_garch_note'].replace('on ', ''))} | {upper_first(_span(L('VAR')))} on clean days (the naked session); {ev['var_breach_all_days']} days counting roll-day artefacts → cut the driving position the same day |
| **Counterparty** | Band from the illustrative score: A max use {pct(float(bp.at['A', 'band_max_credit_utilisation_frac']), 0)}, B {pct(float(bp.at['B', 'band_max_credit_utilisation_frac']), 0)}, C {pct(float(bp.at['C', 'band_max_credit_utilisation_frac']), 0)} + security + advances ≤ {float(bp.at['C', 'band_max_advance_reliance_multiple']):.1f}x limit, D line cut to {pct(float(bp.at['D', 'band_limit_multiplier']), 0)}, advance/CAD only; never lift a hedge before an advance lands | BUY_RJK_01 band {ev['rjk_band']} (model PD {pct(ev['rjk_pd'])}, synthetic-data model); advances > 1.0x its {inr_m(ev['rjk_limit'], 0)} line on {ev['rjk_adv_days']} days, peak {ev['rjk_adv_peak']:.2f}x, contracted {ev['rjk_contracted_peak']:.2f}x; {ev['bookings_outside']} of {ev['bookings_n']} bookings outside the bands | Breached → BUY_RJK_01 line {inr_m(ev['rjk_limit'], 0)} → {inr_m(ev['rjk_rec_limit'], 0)}, advance or CAD only; {'; '.join(f"{cp} band {ev['bands'][cp]}: {ev['band_actions'][cp].lower()}" for cp in sorted(ev['bands']) if cp != 'BUY_RJK_01')} |
| **Freight** | FOB freight fixed ≤ {int(v('policy_freight_fix_within_bdays'))} trading days after purchase; unhedged with a stop ≤ fixture + {pct(float(v('policy_freight_stop_max_frac_over_fixture')), 0)}; no proxy hedge (no instrument tracks the India lanes; the two lanes are one factor) | Fixed after {', '.join(f"{t} {r['bdays_to_fix']}" for t, r in fr.items())} days; stops {', '.join(f"+{pct(r['stop_over_fixture'])}" for r in fr.values())}; freight VaR mean {inr_m(ev['freight_var_mean'], 2)}; hypothetical +40 % spike costs T01 {inr_m(ev['freight_stress_t01'], 2)} | Within |
| **Liquidity** | Working-capital line {inr_m(ev['fb_limit'], 0)} and LC line {inr_m(ev['lc_limit'], 0)} (sized on the Feb-2022 plan). Funding need + max({inr_m(ev['buffer'], 0)}, 99 % 10-day margin-at-risk at 15 % IM) ≤ line, checked daily; no LC opened that takes the LC line over limit | Peak need {inr_m(ev['need_peak'])} on {day(ev['need_peak_date'])}; LC peak {inr_m(ev['lc_peak'])} on {day(ev['lc_peak_date'])}; margin-at-risk peak {inr_m(ev['mar_peak'])} on {day(ev['mar_peak_date'])}; crash fortnight ({day(ev['crash_start'])}–{day(ev['crash_end'])}) actually paid in {inr_m(ev['crash_vm_actual'], sign=True)} of VM, but LME +{pct(ev['crash_move'], 0)} against the MCX shorts calls {inr_m(ev['crash_extra'])} more and takes headroom from {inr_m(ev['crash_headroom_actual'])} to {inr_m(ev['crash_headroom_stressed'])} while the cargo gains {inr_m(ev['crash_phys_gain'], 0)} of mark, not cash | Buffer rule {_span(L('LIQ_BUFFER_RULE'))}; line {_span(L('LIQ_FB_LIMIT'))}; LC {_span(L('LIQ_LC_LIMIT'))} → pre-agree ad-hoc limits of {inr_m(ev['adhoc_fb'], 0)} (WC) and {inr_m(ev['adhoc_lc'], 0)} (LC) for peak months, or stagger usance maturities and purchases |

**Decisions requested.** (1) Adopt the limits above for the next book. (2) Approve the BUY_RJK_01 line cut and the advance-before-hedge-lift rule now. (3) Mandate the treasury to seek the ad-hoc lines before the next book's peak months; until they are in place, no ticket is signed that the daily liquidity rule shows breaching the line within its cash cycle.

**What these limits cannot see.** The position, unhedged and stop levels were set with the 2022 book in view, so where the book lands against them is illustration, not evidence; the VaR limit excludes grade spread, the book's largest bucket after deal margin. The MCX series and USD/INR are proxies; grade factors and freight levels are hindsight reconstructions; credit PDs come from a model fitted to synthetic data; no drawing-power (stock and receivables) test is modelled; the stop-loss rules would not have fixed the drawdowns driven by grade spread and carry, only stopped the desk adding to them.
"""
    return md


# ------------------------------------------------------------------------------------------------ main
def write_limits(limits: pd.DataFrame) -> None:
    out = limits.copy()
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].round(FLOAT_DECIMALS)
    out["limit_value"] = out["limit_value"].astype(str)
    out.to_csv(TABLES_DIR / f"{LIMITS_TABLE}.csv", index=False, lineterminator="\n")


def main() -> None:
    src = load_sources()
    limits, ev = evaluate(src)
    write_limits(limits)
    md = render_md(limits, ev)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS_DIR / f"{MEMO_NAME}.md"
    pdf_path = REPORTS_DIR / f"{MEMO_NAME}.pdf"
    md_path.write_text(md, encoding="utf-8")
    n = render_markdown_pdf(md, pdf_path, title="Risk policy memo — aluminium scrap desk (SIM)",
                            author="Head of Desk (SIM)", style=MEMO_STYLE)
    if n != MAX_PAGES or count_pdf_pages(pdf_path) != MAX_PAGES:
        raise ValueError(f"risk policy memo must be exactly {MAX_PAGES} A4 page; rendered {n}")


if __name__ == "__main__":
    main()
