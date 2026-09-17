"""Stage P6 — the two-page deal post-mortem on the single best trade (MASTER_SPEC Table 7 row 5.3).

    DESK_OFFLINE=1 .venv/bin/python -c "import desk.reporting.post_mortem as m; m.main()"

Reads (never writes) the published P1–P4 tables, the Phase 0 panel and the anchor-premium evidence extract, and writes:

    outputs/reports/post_mortem.md            the post-mortem (GitHub-readable)
    outputs/reports/post_mortem.pdf           the same, exactly two A4 pages (asserted), SIM label on every page
    outputs/charts/p6_post_mortem_waterfall.png   the ticket's lifetime attribution by bucket
    outputs/charts/p6_post_mortem_timeline.png    cumulative P&L and LME-equivalent position through the pricing windows

Design choices worth knowing
----------------------------
* **"Best" has a stated metric, computed for every ticket.** Raw rupees pick the largest ticket; a post-mortem should
  study the profit that survives the desk's own assumptions. The ranking metric is the *worst* horizon P&L across the
  registered one-at-a-time re-pricing cases in `pnl_sensitivity_pricing.csv` (docs/30 §13.9). The selection table
  prints raw P&L, ₹/MT, the anchor-premium floor and P&L per rupee of peak cash beside it, so a reader who prefers
  another metric can see what it would pick.
* **No hand-typed numbers.** The prose is one template whose every number is a `{placeholder}` filled from the tables
  by `compute_raw` → `format_facts`. `tests/test_post_mortem.py` renders the template with sentinels and fails if a
  digit survives outside a short allow-list of structural tokens (section numbers, bucket letters, GARCH(1,1)).
* **The narrative is pinned to one ticket.** Qualitative words ("short", "the only ticket", "on the due date") cannot
  be placeholders, so `check_claims` re-tests each one against the data and `main()` raises if any fails — including
  the metric selecting a ticket other than `TRADE_OF_RECORD`. A changed book fails loudly instead of publishing a
  story about the wrong trade.
* **Dating.** Only §2 (the thesis) is dated, and every input it quotes carries a date ≤ the trade date
  (`raw["thesis_input_dates"]`, asserted). The rest is a retrospective compiled from the Phase 3 tables; it cites
  evidence published after 2022 (the anchor-premium prints) and says so, rather than wearing a 2022 date it could
  not have been written on. "Dated" means no price, position, trade or event after the trade date; the subtitle says
  that the anchor premium, grade factors, freight levels and the monthly INR 3M rate are later reconstructions.
* **PDF.** Rendered with `desk.reporting.pdf` (fonts, footer with the SIM label and page numbers, determinism). That
  helper has no image or page-break support, so this module splits the Markdown at image lines and feeds the text
  chunks to `markdown_to_flowables`, inserting the charts as a side-by-side figure row.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, PageBreak, Table, TableStyle

from desk import DESK_NAME, HORIZON_END, SIM_LABEL, WINDOW_START, config
from desk.paths import CHARTS_DIR, INTERIM_DIR, PROCESSED_DIR, REPORTS_DIR, TABLES_DIR
from desk.reporting.pdf import (
    DeskDocTemplate,
    PdfStyle,
    _numbered_canvas_class,  # the shared footer (SIM label + "Page n of N"); reused so every report looks the same
    count_pdf_pages,
    markdown_to_flowables,
    register_fonts,
)
from desk.reporting.style import FACTOR_COLORS, PALETTE, PNL_BUCKETS, plt, save_fig

NAME = "post_mortem"
MAX_PAGES = 2
TRADE_OF_RECORD = "T02"            # the ticket the prose was written for; check_claims fails if the metric picks another
ANCHOR_KEY = "domestic_anchor_premium_inr_t"
DESK_SHARE_FAMILY = "desk_share"
PIT_CASE = "grade_mix_pit_repriced"
BASE_CASE = "base"                 # the published book re-derived; not a re-pricing case
WATERFALL = "p6_post_mortem_waterfall"
TIMELINE = "p6_post_mortem_timeline"
PAGEBREAK = "<!-- pagebreak -->"
M = 1e6
NB = "\u00a0"
MINUS = "\u2212"
GRADE_NAMES = {"zorba": "Zorba 95/5", "taint_tabor": "Taint/Tabor", "tense": "Tense"}
PM_STYLE = PdfStyle(font_size=8.3, table_font_size=7.5, title_size=12.0, h2_size=9.2, h3_size=8.4,
                    margin_left_mm=11.0, margin_right_mm=11.0, margin_top_mm=8.5, margin_bottom_mm=10.5,
                    leading_ratio=1.17, paragraph_space_after=1.9, heading_space_before=2.8, footer_font_size=6.2)
FIG_GAP_MM = 2.0


# ------------------------------------------------------------------------------------------------ formatting
def num(x: float, dp: int = 0) -> str:
    """Thousands-separated number with a true minus sign (U+2212); never prints a negative zero."""
    s = f"{abs(x):,.{dp}f}"
    return f"{MINUS}{s}" if x < 0 and any(ch not in "0.," for ch in s) else s


def signed(x: float, dp: int = 0) -> str:
    s = num(x, dp)
    return s if s.startswith(MINUS) or all(ch in "0.," for ch in s) else f"+{s}"


def inr_m(x: float, dp: int = 2, sign: bool = False) -> str:
    s = f"{abs(x) / M:,.{dp}f}"
    if x < 0 and any(ch not in "0.," for ch in s):
        return f"{MINUS}₹{s}{NB}m"
    return f"+₹{s}{NB}m" if sign and any(ch not in "0.," for ch in s) else f"₹{s}{NB}m"


def inr(x: float) -> str:
    s = f"{abs(x):,.0f}"
    return f"{MINUS}₹{s}" if x < 0 and s != "0" else f"₹{s}"


def usd(x: float, dp: int = 0) -> str:
    return f"USD{NB}{num(x, dp)}"


def pct(x: float, dp: int = 1) -> str:
    return f"{num(x * 100, dp)}{NB}%"


def day(d: str, year: bool = False) -> str:
    return pd.Timestamp(d).strftime("%#d-%b-%Y" if year else "%#d-%b")


def m_cell(x: float, dp: int = 2) -> str:
    """₹ m inside a table whose header already says '₹ m'."""
    return signed(x / M, dp)


def _f(x) -> float:
    """Parse a published number that may carry thousands separators (trade_book.csv writes some as text)."""
    return float(str(x).replace(",", ""))


def _split(x: str, sep: str = "|") -> list[str]:
    return [p.strip() for p in str(x).split(sep) if p.strip()]


# ------------------------------------------------------------------------------------------------ sources
def load_sources() -> dict[str, pd.DataFrame]:
    """Every file this stage reads, loaded once with only the columns it needs (low-memory machine)."""
    T = TABLES_DIR
    return {
        "att": pd.read_csv(T / "attribution_daily.csv"),
        "leg": pd.read_csv(T / "attribution_leg_daily.csv"),
        "exp": pd.read_csv(T / "book_exposures_daily.csv",
                           usecols=["date", "scope", "trade_id", "cash_balance_inr", "mcx_im_inr", "cum_pnl_inr",
                                    "lme_delta_mt", "lme_delta_physical_mt", "lme_delta_mcx_mt", "fx_delta_usd",
                                    "fx_delta_forwards_usd", "fx_delta_mcx_usd"]),
        "sens": pd.read_csv(T / "pnl_sensitivity_pricing.csv"),
        "robust": pd.read_csv(T / "pnl_sensitivity_sign_robustness.csv"),
        "nd_timing": pd.read_csv(T / "new_deal_timing.csv"),
        "book": pd.read_csv(T / "trade_book.csv", dtype=str),
        "hedges": pd.read_csv(T / "trade_hedges.csv",
                              usecols=["trade_id", "instrument", "hedge_id", "direction", "lots", "entry_date",
                                       "exit_date", "exit_reason", "lme_eq_mt_at_entry", "notional_usd",
                                       "booking_date", "value_date", "rate_inr"]),
        "cf": pd.read_csv(T / "trade_cashflows.csv",
                          usecols=["scenario", "trade_id", "leg_id", "cf_type", "due_date_contractual",
                                   "settle_date", "amount_ccy", "fx_rate_used", "amount_inr"]),
        "elig": pd.read_csv(T / "trade_eligibility_check.csv"),
        "parity": pd.read_csv(T / "parity_weekly.csv",
                              usecols=["week_end", "grade", "lane", "net_arb_inr_t", "trade_eligible"]),
        "credit": pd.read_csv(T / "trade_credit_exposure.csv"),
        "bookings": pd.read_csv(T / "credit_tracker_bookings.csv",
                                usecols=["contract_date", "trade_id", "sale_id", "cp_id", "band_as_of_date",
                                         "pd_model_annual_frac_prev_close",
                                         "band_final_prev_close", "band_policy_verdict"]),
        "basis": pd.read_csv(T / "mcx_basis_risk.csv"),
        "mcx_beta": pd.read_csv(T / "var_mcx_beta.csv").set_index("sampling"),
        "rolls": pd.read_csv(T / "mcx_roll_carry.csv", usecols=["trade_id", "roll_date", "roll_pnl_inr"]),
        "vol": pd.read_csv(T / "var_vol_forecasts.csv",
                           usecols=["date", "lme_ret", "sigma_lme_garch_frac", "sigma_lme_hist250_frac",
                                    "lme_garch_sample_end"]),
        "mkt": pd.read_csv(PROCESSED_DIR / "market_daily.csv",
                           usecols=["date", "lme_cash_usd_t", "lme_cash_3m_spread_usd_t", "usdinr",
                                    "mcx_al_spot_inr_kg", "mcx_al_m1_inr_kg"]),
        "anchor_ev": pd.read_csv(INTERIM_DIR / "price_evidence" / "adc12_vs_duty_paid_parity.csv",
                                 usecols=["article_date", "use", "duty_paid_cash_parity_inr_t",
                                          "premium_vs_cash_parity_inr_t"]),
    }


# ------------------------------------------------------------------------------------------------ selection
def selection_table(src: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per ticket: every candidate metric, ranked by the declared one (worst registered re-pricing)."""
    att = src["att"][src["att"]["trade_id"] != "BOOK"]          # BOOK rows would double count (fix log §3.8)
    life = att.groupby("trade_id")["daily_pnl_inr"].sum()
    final = att.sort_values("date").groupby("trade_id")["cum_pnl_inr"].last()
    if (life - final).abs().max() > 1.0:
        raise ValueError("attribution_daily: lifetime daily P&L does not tie to the horizon cumulative P&L")
    book = src["book"].set_index("trade_id")
    sens = src["sens"][(src["sens"]["trade_id"] != "BOOK") & (src["sens"]["case"] != BASE_CASE)]
    worst = sens.loc[sens.groupby("trade_id")["cum_pnl_horizon_inr"].idxmin()].set_index("trade_id")
    anchor = sens[sens["param_key"] == ANCHOR_KEY]
    floor = anchor.loc[anchor.groupby("trade_id")["param_value"].idxmin()].set_index("trade_id")
    exp = src["exp"][src["exp"]["scope"] == "trade"]
    cash_min = exp.groupby("trade_id")["cash_balance_inr"].min()
    t = pd.DataFrame({
        "grade": book["grade"], "lane": book["lane"], "quantity_mt": book["quantity_mt"].astype(float),
        "pnl_inr": final,
        "worst_case_inr": worst["cum_pnl_horizon_inr"], "worst_case": worst["case"],
        "worst_family": worst["family"], "worst_param_value": worst["param_value"],
        "n_cases": sens.groupby("trade_id").size(),
        "anchor_floor_value": floor["param_value"], "anchor_floor_pnl_inr": floor["cum_pnl_horizon_inr"],
        "peak_cash_drawn_inr": -cash_min.clip(upper=0.0),
    }).loc[final.index]
    t["pnl_per_mt"] = t["pnl_inr"] / t["quantity_mt"]
    t["pnl_per_peak_cash"] = t["pnl_inr"] / t["peak_cash_drawn_inr"].where(t["peak_cash_drawn_inr"] > 0)
    t = t.sort_values("worst_case_inr", ascending=False)
    t.insert(0, "rank", np.arange(1, len(t) + 1))
    return t


def case_label(family: str, param_value: float, case: str) -> str:
    """Plain-English name of a re-pricing case, built from the published row (no numbers typed here)."""
    if family == "anchor_premium":
        return f"the anchor premium at {num(param_value)}{NB}₹/MT"
    if family == DESK_SHARE_FAMILY:
        return f"a {pct(param_value, 0)} desk share of the arb"
    if case == PIT_CASE:
        return "both legs re-priced on the point-in-time grade mix"
    if family == "conversion":
        return f"conversion at {inr(param_value)}/MT"
    return f"case `{case}`"


# ------------------------------------------------------------------------------------------------ raw facts
def _row(df: pd.DataFrame, **eq) -> pd.Series:
    m = pd.Series(True, index=df.index)
    for k, v in eq.items():
        m &= df[k] == v
    sub = df[m]
    if len(sub) != 1:
        raise ValueError(f"expected one row for {eq}, found {len(sub)}")
    return sub.iloc[0]


def compute_raw(src: Mapping[str, pd.DataFrame], tid: str = TRADE_OF_RECORD) -> dict:
    """Every number the post-mortem prints, unformatted, straight from the tables (see module docstring)."""
    r: dict = {"tid": tid}
    sel = selection_table(src)
    r["selection"] = sel
    b = src["book"].set_index("trade_id").loc[tid]
    td = b["trade_date"]
    qty = float(b["quantity_mt"])
    r.update(trade_date=td, close_date=b["close_date"], qty=qty, grade=b["grade"], lane=b["lane"],
             boxes=int(b["boxes"]), box_type=b["box_type"], load_port=b["load_port"], spa_ref=b["spa_ref"],
             supplier=b["supplier_name"], buyer=b["buyer_names"], buyer_id=b["buyer_ids"],
             incoterm=b["incoterm"], named_place=b["named_place"], delivery=b["sale_delivery_basis"],
             p_factor=float(b["purchase_factor_frac"]), prov_frac=float(b["provisional_frac"]),
             qp_start=b["pricing_period_start"], qp_end=b["pricing_period_end"],
             final_invoice=b["final_invoice_date"], pay_instrument=b["payment_instrument"],
             usance_days=int(float(b["usance_days"])), lc_confirmed=b["lc_confirmed"] == "True",
             lc_open=b["lc_open_date"], laycan_start=b["laycan_start"], laycan_end=b["laycan_end"],
             bl_dates=_split(b["bl_dates"]), usance_mats=_split(b["usance_maturity_dates"]),
             sale_contract_dates=_split(b["sale_contract_dates"]), s_factor=_f(b["sale_factor_frac"]),
             s_prem=_f(b["sale_premium_inr_t"]), credit_days=int(float(b["sale_credit_days"])),
             sale_terms=b["sale_payment_terms"], invoice_date=b["sale_invoice_dates"],
             due_date=b["sale_due_dates_contractual"], sale_val_td=_f(b["sale_value_inr"]),
             hedge_ratio=float(b["mcx_hedge_ratio_target"]), fx_cover=float(b["fx_hedge_frac_target"]),
             psic_required=b["psic_required"] == "True", repl=float(b["replacement_inr_t_at_trade_date"]),
             netback=float(b["netback_inr_t_at_trade_date"]), gf_td=float(b["grade_factor_at_trade_date"]),
             events=[b[c] for c in ("event_quality", "event_logistics", "event_buyer_payment_delay")])
    sw_start, sw_end = b["sale_pricing_window"].split("..")
    r.update(sw_start=sw_start, sw_end=sw_end)

    # ---- selection facts
    s = sel.loc[tid]
    raw_id = sel["pnl_inr"].idxmax()
    rs = sel.loc[raw_id]
    r.update(rank=int(s["rank"]), pnl=float(s["pnl_inr"]), pnl_mt=float(s["pnl_per_mt"]), n_cases=int(s["n_cases"]),
             n_trades=len(sel), worst=float(s["worst_case_inr"]),
             worst_label=case_label(s["worst_family"], s["worst_param_value"], s["worst_case"]),
             raw_id=raw_id, raw_pnl=float(rs["pnl_inr"]), raw_worst=float(rs["worst_case_inr"]),
             raw_worst_label=case_label(rs["worst_family"], rs["worst_param_value"], rs["worst_case"]),
             n_positive_all=int((sel["worst_case_inr"] > 0).sum()), selected_id=sel.index[0],
             leads_per_mt=sel["pnl_per_mt"].idxmax() == tid, leads_per_cash=sel["pnl_per_peak_cash"].idxmax() == tid,
             anchor_floor_value=float(s["anchor_floor_value"]))

    # ---- book headline + the band it must always travel with
    att = src["att"]
    book_rows = att[att["trade_id"] == "BOOK"].sort_values("date")
    rob = _row(src["robust"], family="anchor_premium")
    share_row = _row(src["robust"], family=DESK_SHARE_FAMILY)
    r.update(book_pnl=float(book_rows["cum_pnl_inr"].iloc[-1]), book_lo=float(rob["pnl_min_inr"]),
             book_hi=float(rob["pnl_max_inr"]), book_be=float(rob["breakeven_value"]),
             book_be_inside=str(rob["breakeven_inside_band"]) == "True",
             book_sign_robust=str(rob["sign_robust_within_band"]) == "True", book_base_pnl=float(rob["base_pnl_inr"]),
             desk_share=float(share_row["base_value"]), desk_share_min=float(share_row["band_min_value"]),
             anchor_base=float(rob["base_value"]))
    prm = config.get(ANCHOR_KEY)
    r.update(anchor_flag=prm.flag, anchor_verify=prm.verify.split(" ")[0].strip("—-: "))

    # ---- thesis: market to the trade-date close only
    mkt = src["mkt"]
    pre = mkt[mkt["date"] <= td].reset_index(drop=True)
    ath_i = int(pre["lme_cash_usd_t"].idxmax())
    ath, nxt = pre.loc[ath_i], pre.loc[ath_i + 1]
    tdr = _row(pre, date=td)
    ws = pre[pre["date"] >= WINDOW_START.isoformat()].iloc[0]
    vol = src["vol"]
    vtd = _row(vol, date=td)
    r.update(ath_date=ath["date"], ath_px=float(ath["lme_cash_usd_t"]), break_date=nxt["date"],
             break_usd=float(nxt["lme_cash_usd_t"] - ath["lme_cash_usd_t"]),
             break_pct=float(nxt["lme_cash_usd_t"] / ath["lme_cash_usd_t"] - 1), cash_td=float(tdr["lme_cash_usd_t"]),
             spread_td=float(tdr["lme_cash_3m_spread_usd_t"]), fx_td=float(tdr["usdinr"]), ws_date=ws["date"],
             fx_ws=float(ws["usdinr"]), garch_td=float(vtd["sigma_lme_garch_frac"]),
             hist_td=float(vtd["sigma_lme_hist250_frac"]), garch_sample_end=vtd["lme_garch_sample_end"],
             hist_window=int(config.value("var_hist_window_base_days")))
    el = _row(src["elig"], trade_id=tid)
    board = src["parity"][src["parity"]["week_end"] == el["parity_week_end_used"]]
    board_ok = board[board["trade_eligible"]].sort_values("net_arb_inr_t", ascending=False)
    r.update(parity_week=el["parity_week_end_used"], n_board=len(board), n_board_eligible=len(board_ok),
             board_top=(board_ok.iloc[0]["grade"], board_ok.iloc[0]["lane"]), na_base=float(el["net_arb_inr_t"]),
             na_pit=float(el["net_arb_pit_mix_inr_t"]), na_conv=float(el["net_arb_conv18k_inr_t"]),
             hurdle=float(el["margin_threshold_inr_t"]), eligible=bool(el["trade_eligible"]))
    r["m1_td"] = float(tdr["mcx_al_m1_inr_kg"])
    r["formula_px_td"] = r["s_factor"] * r["m1_td"] * 1000 + r["s_prem"]
    r["rule_px_td"] = r["repl"] + r["desk_share"] * (r["netback"] - r["repl"])
    r["parity_td"] = (float(tdr["mcx_al_spot_inr_kg"]) - float(config.value("mcx_domestic_premium_inr_kg", td))) * 1000
    r["thesis_input_dates"] = [ath["date"], nxt["date"], td, ws["date"], r["garch_sample_end"], el["parity_value_date"],
                               el["parity_week_end_used"], vtd["date"]]

    # ---- hedges
    h = src["hedges"][src["hedges"]["trade_id"] == tid]
    mcx = h[h["instrument"] == "MCX_ALUMINIUM_FUTURE"].sort_values("entry_date")
    sells, buys = mcx[mcx["direction"] == "SELL"], mcx[mcx["direction"] == "BUY"]
    fwd = h[h["instrument"] == "USDINR_FORWARD"].sort_values("booking_date")
    r.update(sell_lots=int(sells["lots"].iloc[0]), sell_entry=sells["entry_date"].iloc[0],
             roll_dates=list(sells.loc[sells["exit_reason"] == "ROLL", "exit_date"]),
             sell_exit=sells["exit_date"].iloc[-1], sell_exit_reason=sells["exit_reason"].iloc[-1],
             n_sell_lot_sizes=sells["lots"].nunique(), n_buys=len(buys),
             buy_lots=int(buys["lots"].iloc[0]) if len(buys) else 0,
             buy_entry=buys["entry_date"].iloc[0] if len(buys) else "", buy_exit=buys["exit_date"].iloc[0] if len(buys) else "",
             metal_per_t=float(sells["lme_eq_mt_at_entry"].iloc[0]) / qty,
             mcx_exit_dates=sorted(set(mcx["exit_date"])),
             fwd_lines=[(row.direction, float(row.notional_usd), float(row.rate_inr), row.booking_date, row.value_date)
                        for row in fwd.itertuples()])
    rolls = src["rolls"][src["rolls"]["trade_id"] == tid]
    r.update(n_rolls=len(rolls), roll_pnl=float(rolls["roll_pnl_inr"].sum()))

    # ---- realised cashflows
    cf = src["cf"][(src["cf"]["trade_id"] == tid) & (src["cf"]["scenario"] == "REALISED")]
    by = cf.groupby("cf_type")
    prov = cf[cf["cf_type"] == "PURCHASE_PROVISIONAL"]
    usd_prov = -float(prov["amount_ccy"].sum())
    usd_final = float(cf.loc[cf["cf_type"] == "PURCHASE_FINAL", "amount_ccy"].sum())
    p_usd_t = (usd_prov - usd_final) / qty
    qp = mkt[(mkt["date"] >= r["qp_start"]) & (mkt["date"] <= r["qp_end"])]
    sale_cf = cf[cf["cf_type"].str.startswith("SALE_")]
    sale_val = float(sale_cf["amount_inr"].sum())
    sale_px = sale_val / qty
    swin = mkt[(mkt["date"] >= sw_start) & (mkt["date"] <= sw_end)]
    bal = _row(cf, cf_type="SALE_BALANCE")
    r.update(usd_prov=usd_prov, usd_final=usd_final, p_usd_t=p_usd_t, qp_avg_implied=p_usd_t / r["p_factor"],
             qp_avg_mkt=float(qp["lme_cash_usd_t"].mean()), sale_val=sale_val, sale_px=sale_px,
             mcx_avg_implied=(sale_px - r["s_prem"]) / r["s_factor"] / 1000,
             mcx_avg_mkt=float(swin["mcx_al_m1_inr_kg"].mean()), n_fix=len(swin), paid_date=bal["settle_date"],
             paid_due=bal["due_date_contractual"], fwd_pnl=float(by["amount_inr"].sum().get("FX_FORWARD", 0.0)),
             spot_mats=list(prov.sort_values("settle_date")["fx_rate_used"].astype(float)),
             psic=-float(by["amount_inr"].sum().get("PSIC", 0.0)), port=-float(by["amount_inr"].sum().get("PORT_CHARGES", 0.0)),
             duty=-float(cf.loc[cf["cf_type"].str.startswith("CUSTOMS_DUTY"), "amount_inr"].sum()),
             demurrage=-float(cf.loc[cf["cf_type"].str.contains("DEMURRAGE|CLAIM|REJECT"), "amount_inr"].sum()))
    cr = _row(src["credit"], trade_id=tid)
    buyer_sales = src["credit"][src["credit"]["buyer_id"] == cr["buyer_id"]]
    r["first_sale_to_buyer"] = bool(cr["contract_date"] == buyer_sales["contract_date"].min()
                                    and float(cr["exposure_before_inr"]) == 0.0)
    r.update(p04=float(cr["utilisation_frac"]), credit_limit=float(cr["credit_limit_inr"]))
    bks = src["bookings"]
    bk = _row(bks, trade_id=tid)
    firsts = bks.sort_values("contract_date").groupby("cp_id").head(1)
    r["first_bands"] = sorted(set(firsts["band_final_prev_close"]))
    r.update(band_date=bk["band_as_of_date"], band=bk["band_final_prev_close"],
             band_pd=float(bk["pd_model_annual_frac_prev_close"]), band_verdict=bk["band_policy_verdict"])

    # ---- attribution
    ta = att[att["trade_id"] == tid].sort_values("date").reset_index(drop=True)
    for k in PNL_BUCKETS:
        r[f"b_{k}"] = float(ta[k].sum())
    r["b_residual"] = float(ta["residual"].sum())
    ndt = _row(src["nd_timing"], trade_id=tid)
    r.update(nd_td=float(ndt["new_deal_on_trade_date_inr"]), nd_after=float(ndt["new_deal_after_trade_date_inr"]),
             min_cum=float(ta.loc[ta["date"] >= td, "cum_pnl_inr"].min()),
             nd_after_other=float(ndt["after_sale_inr"] + ndt["after_inventory_mark_inr"]
                                  + ndt["after_freight_fixture_inr"]),
             nd_after_costs=float(ndt["after_hedges_inr"] + ndt["after_purchase_costs_and_fees_inr"]))
    leg = src["leg"][src["leg"]["trade_id"] == tid]
    is_mcx = leg["leg_id"].str.startswith("MCX:")
    is_fwd = leg["leg_id"].str.startswith("FX:")
    is_purch = leg["leg_id"].str.startswith("PURCHASE:")
    is_fund = leg["leg_id"] == "FUNDING"
    r.update(lme_mcx=float(leg.loc[is_mcx, "lme_flat"].sum()), lme_phys=float(leg.loc[~is_mcx, "lme_flat"].sum()),
             fx_fwd=float(leg.loc[is_fwd, "fx"].sum()), fx_purch=float(leg.loc[is_purch, "fx"].sum()),
             fx_mcx=float(leg.loc[is_mcx, "fx"].sum()),
             fx_other=float(leg.loc[~(is_fwd | is_purch | is_mcx), "fx"].sum()),
             g_funding=float(leg.loc[is_fund, "roll_term_structure"].sum()))
    r["g_rest"] = r["b_roll_term_structure"] - r["g_funding"]

    # ---- the one-day LME gain and the exposure behind it
    big_i = int(ta["lme_flat"].abs().idxmax())
    big = ta.loc[big_i]
    ex = src["exp"][(src["exp"]["scope"] == "trade") & (src["exp"]["trade_id"] == tid)].sort_values("date")
    prev = ex[ex["date"] < big["date"]].iloc[-1]
    mprev, mbig = _row(mkt, date=prev["date"]), _row(mkt, date=big["date"])
    vbig = _row(vol, date=big["date"])
    r.update(big_date=big["date"], big_pnl=float(big["lme_flat"]), big_prev=prev["date"],
             big_net_mt=float(prev["lme_delta_mt"]), big_mcx_mt=float(prev["lme_delta_mcx_mt"]),
             big_phys_mt=float(prev["lme_delta_physical_mt"]),
             big_move=float(mbig["lme_cash_usd_t"] / mprev["lme_cash_usd_t"] - 1),
             big_z=float(vbig["lme_ret"]) / float(vbig["sigma_lme_garch_frac"]),
             big_prev_is_mcx_exit=prev["date"] in r["mcx_exit_dates"],
             big_in_sale_window=sw_start <= prev["date"] <= sw_end)
    r["big_rest"] = r["b_lme_flat"] - r["big_pnl"]
    r["big_share"] = r["big_pnl"] / r["pnl"]

    # ---- USD length between the sale's last fixing and the long hedge's exit
    pos = ex[(ex["date"] >= sw_end) & (ex["date"] < r["buy_exit"])]
    pnl_days = ta[(ta["date"] > sw_end) & (ta["date"] <= r["buy_exit"])]
    r.update(fx_long_from=sw_end, fx_long_to=r["buy_exit"], fx_long_usd=float(pos["fx_delta_usd"].mean()),
             fx_long_usd_min=float(pos["fx_delta_usd"].min()), fx_long_pnl=float(pnl_days["fx"].sum()),
             fx_long_fwd_min=float(pos["fx_delta_forwards_usd"].min()), fx_long_mcx_min=float(pos["fx_delta_mcx_usd"].min()),
             fx_long_inr_move=float(_row(mkt, date=r["buy_exit"])["usdinr"] / _row(mkt, date=sw_end)["usdinr"] - 1))

    # ---- cash
    r.update(cash_min=float(ex["cash_balance_inr"].min()), cash_min_date=ex.loc[ex["cash_balance_inr"].idxmin(), "date"],
             cash_max=float(ex["cash_balance_inr"].max()), cash_max_date=ex.loc[ex["cash_balance_inr"].idxmax(), "date"],
             cash_pos_date=ex.loc[ex["cash_balance_inr"] > 0, "date"].min(), peak_im=float(ex["mcx_im_inr"].max()))
    fund = leg[is_fund]
    r.update(g_fund_drawn=float(fund.loc[fund["date"] <= r["cash_pos_date"], "roll_term_structure"].sum()),
             g_fund_held=float(fund.loc[fund["date"] > r["cash_pos_date"], "roll_term_structure"].sum()))

    # ---- sensitivities of this ticket
    sens = src["sens"]
    ts = sens[sens["trade_id"] == tid]
    anc = ts[ts["param_key"] == ANCHOR_KEY].sort_values("param_value")
    slope, icpt = np.polyfit(anc["param_value"], anc["cum_pnl_horizon_inr"], 1)
    r.update(anc_lo_value=float(anc["param_value"].iloc[0]), anc_hi_value=float(anc["param_value"].iloc[-1]),
             anc_lo=float(anc["cum_pnl_horizon_inr"].iloc[0]), anc_hi=float(anc["cum_pnl_horizon_inr"].iloc[-1]),
             anc_slope=float(slope), anc_linear_dev=float(np.abs(np.polyval([slope, icpt], anc["param_value"])
                                                           - anc["cum_pnl_horizon_inr"]).max()),
             tid_be=float(-icpt / slope))
    r["tid_be_inside"] = r["anc_lo_value"] <= r["tid_be"] <= r["anc_hi_value"]
    share0 = ts[(ts["family"] == DESK_SHARE_FAMILY)].sort_values("param_value").iloc[0]
    r.update(share0_pnl=float(share0["cum_pnl_horizon_inr"]),
             pit_pnl=float(_row(ts, case=PIT_CASE)["cum_pnl_horizon_inr"]))
    ev = src["anchor_ev"]
    ev = ev[ev["use"].astype(str) == "True"]
    eb, ea = np.polyfit(ev["duty_paid_cash_parity_inr_t"], ev["premium_vs_cash_parity_inr_t"], 1)
    r.update(n_ev=len(ev), ev_from=ev["article_date"].min(), ev_to=ev["article_date"].max(),
             ev_max_parity=float(ev["duty_paid_cash_parity_inr_t"].max()),
             ev_corr=float(np.corrcoef(ev["duty_paid_cash_parity_inr_t"], ev["premium_vs_cash_parity_inr_t"])[0, 1]),
             ev_fit=float(ea + eb * r["parity_td"]), ev_median=float(ev["premium_vs_cash_parity_inr_t"].median()))
    r["ev_pnl"] = float(np.polyval([slope, icpt], r["ev_fit"]))
    r["ev_share"] = r["ev_pnl"] / r["pnl"]
    bs = src["basis"]
    r.update(mirror_basis=float(_row(bs, metric="basis_bucket_mirror_inr", scope=tid)["value"]),
             mirror_total=float(_row(bs, metric="total_pnl_change_vs_base_inr", scope=tid)["value"]),
             beta=float(_row(bs, metric="unit_beta_beta", scope="BOOK")["value"]),
             beta_t=float(_row(bs, metric="unit_beta_beta_t_vs_one", scope="BOOK")["value"]),
             unhedged=float(_row(bs, metric="unit_beta_unhedged_frac_at_beta", scope="BOOK")["value"]))
    mb = src["mcx_beta"]   # docs/40 §4.3: the daily beta is biased down by asynchronous closes
    r.update(beta_weekly=float(mb.at["weekly", "beta"]), beta_weekly_t=float(mb.at["weekly", "t_vs_one"]),
             unhedged_weekly=float(mb.at["weekly", "unhedged_frac_of_parity_move"]),
             beta_leadlag=float(mb.at["lead_lag", "beta"]))
    return r


# ------------------------------------------------------------------------------------------------ claims
def check_claims(r: Mapping) -> list[str]:
    """Each qualitative word in the template, re-tested against the data. Returns the claims that FAIL."""
    tid = r["tid"]
    claims = {
        "the declared metric selects the ticket the prose was written for": r["selected_id"] == tid,
        "it is the only ticket positive in every registered re-pricing case": r["n_positive_all"] == 1 and r["worst"] > 0,
        "it also leads on ₹/MT and on P&L per rupee of peak cash drawn": r["leads_per_mt"] and r["leads_per_cash"],
        "raw rupees pick a different ticket, whose floor is a loss": r["raw_id"] != tid and r["raw_worst"] < 0,
        "the book headline is NOT sign-robust, break-even inside the grid": (not r["book_sign_robust"]) and r["book_be_inside"],
        "book headline ties to the sensitivity base case": abs(r["book_pnl"] - r["book_base_pnl"]) < 1.0,
        "the ticket passed the §5a screen and was the widest eligible case that week":
            r["eligible"] and r["board_top"] == (r["grade"], r["lane"]),
        "the panel high sits before the trade date and the next session fell": r["ath_date"] < r["trade_date"] and r["break_usd"] < 0,
        "cash–3M was in contango on the trade date": r["spread_td"] < 0,
        "GARCH vol forecast above the long window and fitted on data before the trade date":
            r["garch_td"] > r["hist_td"] and r["garch_sample_end"] < r["trade_date"],
        "no thesis input is dated after the trade date": max(r["thesis_input_dates"]) <= r["trade_date"],
        "sold the same day it was bought": r["sale_contract_dates"] == [r["trade_date"]],
        "both legs formula-priced: grade, freight and event buckets exactly zero":
            max(abs(r["b_grade_spread"]), abs(r["b_freight"]), abs(r["b_demurrage_penalty"])) < 1.0,
        "basis bucket zero by construction in base": abs(r["b_cross_exchange_basis"]) < 1.0,
        "buckets sum to the P&L (residual zero)": abs(sum(r[f"b_{k}"] for k in PNL_BUCKETS) - r["pnl"]) < 1.0,
        "CFR purchase, unconfirmed usance LC, PSIC origin": r["incoterm"] == "CFR" and not r["lc_confirmed"]
            and r["pay_instrument"] == "LC_USANCE" and r["psic_required"],
        "sale on credit, usance longer than the credit": r["sale_terms"] == "CREDIT" and r["usance_days"] > r["credit_days"],
        "hedge shape: one lot size of SELLs rolled then unwound on the day ONE BUY starts": r["n_sell_lot_sizes"] == 1
            and r["n_buys"] == 1 and r["sell_exit_reason"] == "UNWIND" and r["sell_exit"] == r["buy_entry"],
        "the flip sits inside the sale's averaging window": r["sw_start"] < r["buy_entry"] < r["sw_end"],
        "the long leg came off inside the purchase quotational period": r["qp_start"] < r["buy_exit"] < r["qp_end"],
        "realised purchase ties to the QP average of LME cash": abs(r["qp_avg_implied"] - r["qp_avg_mkt"]) < 0.5,
        "realised sale ties to the MCX M1 average over the window": abs(r["mcx_avg_implied"] - r["mcx_avg_mkt"]) < 0.01,
        "buyer paid on the contractual due date": r["paid_date"] == r["paid_due"] == r["due_date"],
        "no events and no event cashflows": all(pd.isna(e) or str(e) in ("", "nan") for e in r["events"])
            and abs(r["demurrage"]) < 1.0,
        "largest LME day is a gain on a SHORT held at a clean (non-exit) close inside the sale window":
            r["big_pnl"] > 0 and r["big_net_mt"] < 0 and r["big_mcx_mt"] < 0 and r["big_move"] < 0
            and not r["big_prev_is_mcx_exit"] and r["big_in_sale_window"],
        "net LONG USD on every position day between the sale's last fixing and the long hedge's exit, and it paid":
            r["fx_long_usd_min"] > 0 and r["fx_long_pnl"] > 0,
        "over that span the forwards AND the MCX leg were both long USD": r["fx_long_fwd_min"] > 0 and r["fx_long_mcx_min"] > 0,
        "the rupee weakened over that span ('the rupee's slide')": r["fx_long_inr_move"] > 0,
        "daily beta below weekly below lead/lag ('biased down', 'overstates'), all below one":
            r["beta"] < r["beta_weekly"] < r["beta_leadlag"] < 1.0 and r["unhedged"] > r["unhedged_weekly"],
        "funding cost money while cash was drawn and earned it while the ticket held the buyer's cash":
            r["g_fund_drawn"] < 0 < r["g_fund_held"] and abs(r["g_fund_drawn"] + r["g_fund_held"] - r["g_funding"]) < 1.0,
        "the registered anchor premium is the evidence median rounded to the nearest thousand":
            round(r["ev_median"], -3) == r["anchor_base"],
        "the ticket went cash-positive and funding was a gain": r["cash_max"] > 0 and r["g_funding"] > 0,
        "the ticket's own anchor break-even lies outside the grid and P&L is linear in the premium":
            (not r["tid_be_inside"]) and r["anc_linear_dev"] < 1.0 and r["anc_lo"] > 0,
        "every usable premium print sits at a lower parity than the trade date's, and the fit is below the grid floor":
            r["ev_max_parity"] < r["parity_td"] and r["ev_fit"] < r["anc_lo_value"] and r["ev_corr"] < 0,
        "anchor premium is still an unverified ASSUMPTION": r["anchor_flag"] == "ASSUMPTION" and r["anchor_verify"] == "PENDING",
        "rolls were all gains (proxy contango)": r["roll_pnl"] > 0,
        "later-dated deal margin is only hedge execution costs and LC/purchase fees":
            abs(r["nd_after_other"]) < 1.0 and abs(r["nd_after_costs"] - r["nd_after"]) < 1.0 and r["nd_after"] < 0,
        "the booking sat inside the Phase 5 band policy at the previous close":
            r["band_verdict"] == "WITHIN_BAND_POLICY" and r["band_date"] < r["trade_date"],
        "this was the buyer's first sale with the desk, before any exposure": r["first_sale_to_buyer"],
        "every buyer scored the same band before its first sale, and it is this ticket's band":
            r["first_bands"] == [r["band"]],
    }
    return [k for k, ok in claims.items() if not ok]


# ------------------------------------------------------------------------------------------------ formatted facts
def selection_md(sel: pd.DataFrame, tid: str) -> str:
    floor_v = sel["anchor_floor_value"].iloc[0]
    head = ("| Rank | Ticket | Grade · lane | P&L ₹ m | ₹/MT | Worst re-pricing ₹ m | At anchor "
            f"{num(floor_v)} ₹ m | Peak cash drawn ₹ m | P&L ÷ peak cash |")
    lines = ["<!-- widths: 0.05, 0.065, 0.17, 0.09, 0.08, 0.13, 0.13, 0.13, 0.105 -->", head,
             "|--:|---|---|--:|--:|--:|--:|--:|--:|"]
    raw_id = sel["pnl_inr"].idxmax()
    for t, x in sel.iterrows():
        bold = (lambda s: f"**{s}**") if t == tid else (lambda s: s)
        pnl = m_cell(x["pnl_inr"])
        lines.append("| " + " | ".join([
            bold(str(int(x["rank"]))), bold(t), f"{x['grade']} · {x['lane']}",
            f"**{pnl}**" if t in (tid, raw_id) else pnl, bold(num(x["pnl_per_mt"])), bold(m_cell(x["worst_case_inr"])),
            m_cell(x["anchor_floor_pnl_inr"]), num(x["peak_cash_drawn_inr"] / M, 2),
            num(x["pnl_per_peak_cash"], 2) if pd.notna(x["pnl_per_peak_cash"]) else "—",
        ]) + " |")
    return "\n".join(lines)


def _cdf_cell(cells: list[str]) -> str:
    return f"{cells[0]} each" if len(set(cells)) == 1 else " · ".join(cells)


def format_facts(r: Mapping) -> dict[str, str]:
    """Raw facts -> the exact strings the template prints (one place owns every number format)."""
    tid = r["tid"]
    fwd = "; ".join(f"{d.replace('_', ' ')} {num(n)} at {num(rate, 2)}, {day(bk)}→{day(vd)}"
                    for d, n, rate, bk, vd in r["fwd_lines"])
    F = {
        "tid": tid, "sim_label": SIM_LABEL, "desk_name": DESK_NAME, "grade_name": GRADE_NAMES.get(r["grade"], r["grade"]),
        "load_port": r["load_port"].split(",")[0], "lane": r["lane"], "spa_ref": r["spa_ref"],
        "horizon": day(HORIZON_END.isoformat(), True), "td_long": day(r["trade_date"], True), "td_short": day(r["trade_date"]),
        "close_long": day(r["close_date"], True), "qty": f"{num(r['qty'])}{NB}MT",
        "pnl": inr_m(r["pnl"]), "pnl_mt": inr(r["pnl_mt"]), "book_share": pct(r["pnl"] / r["book_pnl"], 0),
        "book_pnl": inr_m(r["book_pnl"], 1), "book_lo": inr_m(r["book_lo"], 1), "book_hi": inr_m(r["book_hi"], 1, True),
        "book_be": num(r["book_be"]), "anchor_key": ANCHOR_KEY,
        # §1
        "selection_table": selection_md(r["selection"], tid), "n_cases": str(r["n_cases"]), "n_trades": str(r["n_trades"]),
        "tid_worst": inr_m(r["worst"], sign=True), "tid_worst_label": r["worst_label"], "raw_id": r["raw_id"],
        "raw_pnl": inr_m(r["raw_pnl"], sign=True), "raw_worst": inr_m(r["raw_worst"], sign=True),
        "raw_worst_label": r["raw_worst_label"],
        # §2
        "ath_px": f"USD{NB}{num(r['ath_px'], 1)}/t", "ath_date": day(r["ath_date"]),
        "break_usd": f"USD{NB}{num(-r['break_usd'], 0)}", "break_pct": pct(r["break_pct"]),
        "cash_td": f"USD{NB}{num(r['cash_td'], 0)}/t", "spread_td": f"{signed(r['spread_td'])}{NB}USD/t",
        "fx_td": num(r["fx_td"], 2), "fx_ws": num(r["fx_ws"], 2), "ws_date": day(r["ws_date"]),
        "garch_td": pct(r["garch_td"], 2), "hist_td": pct(r["hist_td"], 2), "hist_window": str(r["hist_window"]),
        "parity_week": day(r["parity_week"]), "n_board": str(r["n_board"]), "n_board_eligible": str(r["n_board_eligible"]),
        "na_base": inr(r["na_base"]), "na_pit": inr(r["na_pit"]), "na_conv": inr(r["na_conv"]), "hurdle": inr(r["hurdle"]),
        "repl": inr(r["repl"]), "netback": inr(r["netback"]), "incoterm": r["incoterm"],
        "p_factor": num(r["p_factor"], 3), "gf_td": num(r["gf_td"], 4), "s_factor": num(r["s_factor"], 3),
        "s_prem": f"{MINUS}{NB}{inr(-r['s_prem'])}" if r["s_prem"] < 0 else f"+{NB}{inr(r['s_prem'])}",
        "formula_px": inr(r["formula_px_td"]), "rule_px": inr(r["rule_px_td"]), "share": pct(r["desk_share"], 0),
        "metal_per_t": num(r["metal_per_t"], 2), "sell_lots": str(r["sell_lots"]), "buy_lots": str(r["buy_lots"]),
        "usance_days": str(r["usance_days"]), "credit_days": str(r["credit_days"]),
        # §3
        "supplier": r["supplier"], "named_place": r["named_place"].replace(r["incoterm"], "").strip(),
        "boxes": str(r["boxes"]), "box_type": r["box_type"], "qp": f"{day(r['qp_start'])}–{day(r['qp_end'])}",
        "prov_pct": pct(r["prov_frac"], 0), "lc_open": day(r["lc_open"]),
        "bl_dates": " and ".join(day(d) for d in r["bl_dates"]),
        "laycan": f"{day(r['laycan_start'])}–{day(r['laycan_end'])}", "usd_prov": usd(r["usd_prov"]),
        "spot_mats": " / ".join(num(x, 2) for x in r["spot_mats"]),
        "usance_mats": " and ".join(day(d) for d in r["usance_mats"]),
        "qp_avg": f"USD{NB}{num(r['qp_avg_mkt'], 0)}/t", "usd_final": usd(r["usd_final"]),
        "final_inv": day(r["final_invoice"]), "p_usd_t": f"USD{NB}{num(r['p_usd_t'], 0)}/t",
        "buyer": r["buyer"], "delivery": r["delivery"],
        "sw": f"{day(r['sw_start'])}–{day(r['sw_end'])}", "n_fix": str(r["n_fix"]), "p04": pct(r["p04"]),
        "credit_limit": inr_m(r["credit_limit"], 0), "mcx_avg": num(r["mcx_avg_mkt"], 2),
        "sale_px": inr(r["sale_px"]), "sale_val": inr_m(r["sale_val"], 1), "sale_val_td": inr_m(r["sale_val_td"], 1),
        "inv_date": day(r["invoice_date"]), "paid_date": day(r["paid_date"]), "band": r["band"],
        "band_pd": pct(r["band_pd"]), "band_date": day(r["band_date"]), "buyer_id": r["buyer_id"],
        "hedge_ratio": num(r["hedge_ratio"], 2), "sell_entry": day(r["sell_entry"]),
        "roll_dates": " and ".join(day(d) for d in r["roll_dates"]), "sell_exit": day(r["sell_exit"]),
        "buy_entry": day(r["buy_entry"]), "buy_exit": day(r["buy_exit"]), "peak_im": inr_m(r["peak_im"], 1),
        "n_rolls": str(r["n_rolls"]), "roll_pnl": inr_m(r["roll_pnl"], sign=True), "fx_cover": pct(r["fx_cover"], 0),
        "fwd_lines": fwd, "fwd_pnl": inr_m(r["fwd_pnl"], sign=True), "psic": inr_m(r["psic"]),
        "port": inr_m(r["port"]), "duty": inr_m(r["duty"]), "cash_min": inr_m(-r["cash_min"], 1),
        "cash_min_date": day(r["cash_min_date"]), "cash_pos_date": day(r["cash_pos_date"]),
        "cash_max": inr_m(r["cash_max"], 1), "cash_max_date": day(r["cash_max_date"]),
        # §4
        "b_new_deal": m_cell(r["b_new_deal"]), "b_lme": m_cell(r["b_lme_flat"]),
        "b_basis": m_cell(r["b_cross_exchange_basis"]),
        "b_cdf": _cdf_cell([m_cell(r[f"b_{k}"]) for k in ("grade_spread", "freight", "demurrage_penalty")]),
        "b_fx": m_cell(r["b_fx"]), "b_roll": m_cell(r["b_roll_term_structure"]), "b_total": m_cell(r["pnl"]),
        "nd_td": inr_m(r["nd_td"], sign=True), "nd_after": inr_m(r["nd_after"], sign=True),
        "lme_phys": inr_m(r["lme_phys"], sign=True), "lme_mcx": inr_m(r["lme_mcx"], sign=True),
        "big_pnl": inr_m(r["big_pnl"], sign=True), "big_date": day(r["big_date"]), "big_rest": inr_m(r["big_rest"], sign=True),
        "mirror_basis": inr_m(r["mirror_basis"], sign=True), "mirror_total": inr_m(r["mirror_total"], sign=True),
        "fx_fwd": inr_m(r["fx_fwd"], sign=True), "fx_purch": inr_m(r["fx_purch"], sign=True),
        "fx_mcx": inr_m(r["fx_mcx"], sign=True), "fx_other": inr_m(r["fx_other"], sign=True),
        "fx_long_pnl": inr_m(r["fx_long_pnl"], sign=True), "fx_long_usd": f"USD{NB}{num(r['fx_long_usd'] / M, 2)}{NB}m",
        "fx_long_from": day(r["fx_long_from"]), "fx_long_to": day(r["fx_long_to"]),
        "g_funding": inr_m(r["g_funding"], sign=True), "g_rest": inr_m(r["g_rest"], sign=True),
        "g_fund_drawn_abs": inr_m(abs(r["g_fund_drawn"])), "g_fund_held_abs": inr_m(abs(r["g_fund_held"])),
        # §5–7
        "nd_td_share": pct(r["nd_td"] / r["pnl"], 0), "min_cum": inr_m(r["min_cum"]),
        "big_prev": day(r["big_prev"]), "big_short": num(-r["big_net_mt"]), "big_mcx": num(-r["big_mcx_mt"]),
        "big_fall": pct(-r["big_move"]), "big_z": num(r["big_z"], 1), "big_share": pct(r["big_share"], 0),
        "anchor_base": num(r["anchor_base"]), "anchor_flag": r["anchor_flag"], "anchor_verify": r["anchor_verify"],
        "anc_lo": inr_m(r["anc_lo"], 1, True), "anc_hi": inr_m(r["anc_hi"], 1, True),
        "anc_lo_value": num(r["anc_lo_value"]), "anc_hi_value": signed(r["anc_hi_value"]),
        "tid_be": num(r["tid_be"]), "share_min": pct(r["desk_share_min"], 0), "share0_pnl": inr_m(r["share0_pnl"], 1, True),
        "pit_pnl": inr_m(r["pit_pnl"], 1, True), "n_ev": str(r["n_ev"]), "ev_from": day(r["ev_from"], True),
        "ev_to": day(r["ev_to"], True), "td_parity": inr(r["parity_td"]), "ev_max_parity": inr(r["ev_max_parity"]),
        "ev_corr": num(r["ev_corr"], 2), "ev_fit": num(r["ev_fit"]), "ev_pnl": inr_m(r["ev_pnl"], 1, True),
        "ev_share": pct(r["ev_share"], 0), "beta": num(r["beta"], 2), "beta_t": num(r["beta_t"], 1),
        "unhedged": pct(r["unhedged"], 0), "beta_w": num(r["beta_weekly"], 2), "beta_w_t": num(r["beta_weekly_t"], 1),
        "unhedged_w": pct(r["unhedged_weekly"], 0), "beta_ll": num(r["beta_leadlag"], 2), "waterfall_png": f"../charts/{WATERFALL}.png",
        "timeline_png": f"../charts/{TIMELINE}.png",
    }
    return F


# ------------------------------------------------------------------------------------------------ template
TEMPLATE = """# Deal post-mortem — {tid}: {grade_name} from {load_port}, floating in and floating out

**{desk_name}** · Trader's post-mortem on ticket {spa_ref}, traded {td_long}, last cashflow {close_long}. Only §2 is dated: it uses no price, position, trade or event dated after the {td_long} close, but the anchor premium behind its netback, the grade factors, freight levels and the INR 3M rate are reconstructions that use later publications (§6). The rest is a retrospective on the Phase 3 tables (horizon {horizon}).

> **{sim_label}.** {tid} made **{pnl}** on {qty} (**{pnl_mt}/MT**), {book_share} of the book's {book_pnl}. That book figure is **not sign-robust**: {book_lo} to {book_hi} across the registered `{anchor_key}` grid, break-even {book_be}{NB}₹/MT inside it. Counterparties, vessels and events are simulated; LME is DIRECT, USD/INR and MCX are PROXY, grade factors and freight levels are hindsight reconstructions.

## 1. Which trade, and by what measure

{selection_table}

**Metric: the worst P&L across the {n_cases} registered one-at-a-time re-pricing cases** (`pnl_sensitivity_pricing.csv`), because a post-mortem should study the profit that survives the desk's own assumptions. {tid} is the only one of {n_trades} tickets positive in all {n_cases} (floor {tid_worst}, at {tid_worst_label}), and it also leads on ₹/MT and on P&L per rupee of peak cash drawn. {raw_id} leads on raw rupees ({raw_pnl}) but falls to {raw_worst} with {raw_worst_label}. I chose the metric after the Phase 3 results were out; the table shows the alternatives so a reader can disagree.

## 2. Thesis — as of the {td_long} close

- **Tape.** LME cash made the panel's record close, {ath_px}, on {ath_date} and lost {break_usd} ({break_pct}) the next session; on {td_short} it closed at {cash_td} with cash–3M at {spread_td} (contango). USD/INR (ECB cross, PROXY) {fx_td}, from {fx_ws} on {ws_date}. The Phase 4.1 GARCH(1,1) one-day LME vol forecast for the session, fitted on returns to the previous close, was {garch_td} against {hist_td} on the {hist_window}-day window: no tape to be long flat price on a guess.
- **Parity (§5a screen).** Week to {parity_week}: {n_board_eligible} of {n_board} grade × lane cases eligible, and {grade_name} on {lane} the widest — {na_base}/MT base, {na_pit} on the point-in-time grade mix, {na_conv} with conversion stressed, against a {hurdle} hurdle. Replacement {repl}/MT, smelter netback {netback}/MT.
- **Structure.** Buy {incoterm} at {p_factor} × the LME cash average of the month after shipment (reconstructed trade-date grade factor {gf_td}); sell the same afternoon at {s_factor} × the MCX near-month average over the delivery window {s_prem}/MT, which at the day's MCX priced {formula_px}/MT against {rule_px} from the desk rule ({share} of the gap). Both legs float, so the trade is the factor gap — {metal_per_t}{NB}t of LME-equivalent metal per tonne of scrap: {sell_lots} MCX lots short now, flipping to {buy_lots} long once the sale has averaged and the purchase has not. A {usance_days}-day usance against {credit_days}-day buyer credit means the buyer pays before I do. The risk I flagged: {load_port} cargo needs a pre-shipment inspection certificate (PSIC), and a failed inspection stops the whole parcel.

## 3. Execution

<!-- widths: 0.11, 0.47, 0.42 -->
| Leg | Ticket terms | What happened |
|---|---|---|
| Purchase | {supplier}, {incoterm} {named_place}; {qty} {grade_name} in {boxes} × {box_type}; {p_factor} × LME cash avg {qp}, {prov_pct} provisional; usance LC {usance_days} days, unconfirmed, opened {lc_open} | B/Ls {bl_dates} (laycan {laycan}); provisional {usd_prov} paid at {spot_mats} on {usance_mats}; QP averaged {qp_avg}, final credit {usd_final} on {final_inv}; net {p_usd_t} |
| Sale | {buyer}, {delivery}; {s_factor} × MCX M1 avg {sw} {s_prem}/MT; {credit_days}-day credit | M1 averaged {mcx_avg}{NB}₹/kg → {sale_px}/MT = {sale_val} (vs {sale_val_td} at {td_short} prices); invoiced {inv_date}, paid {paid_date}, the due date |
| MCX, ratio {hedge_ratio} | SELL {sell_lots} lots {sell_entry}, rolled {roll_dates}, unwound {sell_exit}; BUY {buy_lots} lots {buy_entry}→{buy_exit}; each leg closed at the midpoint fixing of the leg it hedges | Peak initial margin {peak_im}; hedge legs' LME bucket {lme_mcx}; {n_rolls} rolls {roll_pnl}, proxy INR carry |
| FX, cover {fx_cover} | {fwd_lines} | Settled {fwd_pnl} |
| Credit | {buyer_id}: {p04} of its {credit_limit} line after booking | Phase 5 score at the {band_date} close: band {band}, model PD {band_pd} (synthetic-data model, retrospective) — but this was its first sale with the desk, and every buyer scored band {band} before its first sale |
| Costs, cash | No quality, logistics or payment events. PSIC {psic}, port {port}, duty {duty} | Cash drawn peaked at {cash_min} ({cash_min_date}); positive from {cash_pos_date}, peaking at {cash_max} on {cash_max_date} |

<!-- pagebreak -->
## 4. Attribution — {pnl} lifetime

![Lifetime attribution by bucket]({waterfall_png}) ![Cumulative P&L and LME-equivalent position]({timeline_png})

<!-- widths: 0.235, 0.105, 0.66 -->
| Bucket | ₹ m | Where it came from |
|---|--:|---|
| (0) deal margin at contract dates | {b_new_deal} | {nd_td} on {td_short} — the sale rule; {nd_after} on later dates (hedge execution costs, LC fees) |
| (a) LME flat price | {b_lme} | physical {lme_phys}, MCX legs {lme_mcx}; **{big_pnl} on {big_date} alone**, {big_rest} on every other day |
| (b) LME–MCX basis | {b_basis} | zero by construction on the proxy; {mirror_basis} on the third-party mirror (PROXY; whole-ticket effect {mirror_total}) |
| (c) grade · (d) freight · (f) events | {b_cdf} | both legs formula-priced; CFR; no events |
| (e) USD/INR | {b_fx} | forwards {fx_fwd}, USD purchase legs {fx_purch}, MCX legs {fx_mcx}, other {fx_other}; {fx_long_pnl} of it between {fx_long_from} and {fx_long_to} (§5) |
| (g) carry, roll, cross-terms | {b_roll} | funding {g_funding}; the rest {g_rest} (rolls {roll_pnl}, all proxy INR carry, and cross-terms) |
| **total** | **{b_total}** | residual zero |

## 5. What went right, what went wrong

- **Right — structure, not view.** {nd_td_share} of the result was booked the day I signed, and cumulative P&L never closed below {min_cum}.
- **Right — tenor.** The buyer paid on {paid_date}; my usance matured on {usance_mats}. Funding cost {g_fund_drawn_abs} while cash was drawn and earned {g_fund_held_abs} on the buyer's money after that — credited at the working-capital rate under the symmetric convention of CONTRACTS §7a.5; a deposit would have earned less.
- **Wrong — the midpoint flip.** At the {big_prev} close I was net short {big_short}{NB}MT LME-equivalent: the sale had started fixing, but the {big_mcx}{NB}MT MCX short stayed on until its midpoint. LME cash fell {big_fall} into {big_date} ({big_z}σ on the GARCH forecast) and paid {big_pnl}; the same rally would have cost it.
- **Wrong — double dollar cover.** From {fx_long_from} to {fx_long_to} the forwards on the payable and the long MCX leg (whose proxy moves one-for-one with USD/INR) were both long dollars — net about {fx_long_usd} — and the rupee's slide paid {fx_long_pnl}.

## 6. Honest admissions

> **Most of this P&L is my own pricing rule, not a price anyone quoted.** The {nd_td} booked on {td_short} comes from a sale priced at the replacement mark plus {share} of the gap to a netback built on `{anchor_key}` = {anchor_base}{NB}₹/MT ({anchor_flag}, verification {anchor_verify}). Across its registered grid ({anc_lo_value} … {anc_hi_value}) {tid} makes {anc_lo} to {anc_hi}, break-even {tid_be}{NB}₹/MT, far outside it; at a {share_min} desk share, {share0_pnl}; re-priced on the point-in-time grade mix, {pit_pnl}. Worse, the premium's base is the median of {n_ev} ADC12 prints dated {ev_from} to {ev_to} — published after this trade — all at duty-paid parities below the {td_short} level of {td_parity}/MT (highest {ev_max_parity}). Their own line (correlation {ev_corr}) puts the premium at {ev_fit}{NB}₹/MT at that parity, below the grid, where a linear extrapolation leaves {tid} {ev_pnl}: {ev_share} of its {pnl}.

> **And {big_share} of it was luck.** The {big_pnl} on {big_date} was an exposure my hedge convention created, not a call. Basis is unmeasured too: the hedge P&L sits on an MCX proxy with zero basis and unit beta, while the third-party mirror's beta is {beta_w} on weekly closes (t {beta_w_t} against one), so a unit-beta short would leave about {unhedged_w} of a parity move open. The daily figure, {beta}, is biased down by MCX's evening close and overstates that.

## 7. Lessons

1. **Keep the template:** formula to formula, both sides signed the same day, payment tenor running in my favour.
2. **Hedge an averaging leg per fixing** — an equal slice of the lots on each of the {n_fix} fixing days — not with a midpoint flip: the flip, not the market, made {big_share} of this ticket.
3. **Net the MCX leg's dollars before booking forwards** on the same payable; on a unit-beta proxy the two count the same cover twice.
4. **Put a buyer quote under the rule before calling it margin,** and print each sale's break-even anchor premium on the ticket.
5. **Measure the MCX beta at matched closing times** — {beta_w} on weekly closes, {beta_ll} with a lead/lag, never the biased daily {beta} — size on that, and carry basis in the risk numbers; here all three are PROXY sensitivities.

*What this does and doesn't tell you.* It shows where {tid}'s P&L came from inside the desk's own engine and how much survives the registered assumptions one at a time. It does not show that a real buyer would have paid this formula, that MCX would have tracked the proxy, or that the grade factor I benchmarked against was knowable on the day — those are reconstructions and proxies, and the ranking in §1 inherits them. No joint case (a low premium together with the point-in-time mix) is published.
"""


def render_markdown(facts: Mapping[str, str]) -> str:
    """Fill the template. `NB` is a layout token (non-breaking space), not a fact."""
    return TEMPLATE.format_map({**facts, "NB": NB})


def build_markdown(src: Mapping[str, pd.DataFrame], tid: str = TRADE_OF_RECORD) -> tuple[str, dict]:
    raw = compute_raw(src, tid)
    failed = check_claims(raw)
    if failed:
        raise ValueError("post-mortem prose no longer matches the data: " + "; ".join(failed))
    return render_markdown(format_facts(raw)), raw


# ------------------------------------------------------------------------------------------------ charts
def chart_waterfall(raw: Mapping) -> str:
    """Lifetime attribution of the ticket, (0) split into trade date vs later contract dates."""
    tid = raw["tid"]
    steps = [
        ("(0)\n" + day(raw["trade_date"]), raw["nd_td"], FACTOR_COLORS["new_deal"]),
        ("(0)\nlater", raw["nd_after"], FACTOR_COLORS["new_deal"]),
        ("(a)\nLME", raw["b_lme_flat"], FACTOR_COLORS["lme_flat"]),
        ("(b)\nbasis", raw["b_cross_exchange_basis"], FACTOR_COLORS["cross_exchange_basis"]),
        ("(c)\ngrade", raw["b_grade_spread"], FACTOR_COLORS["grade_spread"]),
        ("(d)\nfreight", raw["b_freight"], FACTOR_COLORS["freight"]),
        ("(e)\nFX", raw["b_fx"], FACTOR_COLORS["fx"]),
        ("(f)\nevents", raw["b_demurrage_penalty"], FACTOR_COLORS["demurrage_penalty"]),
        ("(g)\ncarry", raw["b_roll_term_structure"], FACTOR_COLORS["roll_term_structure"]),
    ]
    with plt.rc_context({"font.size": 8.4, "axes.titlesize": 9.0}):
        fig, ax = plt.subplots(figsize=(4.9, 3.35))
        fig.subplots_adjust(bottom=0.2)          # keep the two-line tick labels clear of save_fig's footer
        level = 0.0
        span = max(abs(raw["pnl"]), 1.0) / M
        for i, (lab, v, c) in enumerate(steps):
            vm = v / M
            ax.bar(i, vm if abs(vm) > 1e-9 else span * 0.004, bottom=level if abs(vm) > 1e-9 else level - span * 0.002,
                   color=c, alpha=0.55 if i == 1 else 0.95, width=0.72, edgecolor="none")
            top = level + max(vm, 0)
            ax.text(i, top + span * 0.015, signed(vm, 2), ha="center", va="bottom", fontsize=6.6)
            if i < len(steps) - 1:
                ax.plot([i + 0.36, i + 0.64], [level + vm] * 2, color=PALETTE["neutral"], lw=0.6)
            level += vm
        n = len(steps)
        ax.bar(n, raw["pnl"] / M, color=PALETTE["pnl"], width=0.72)
        ax.text(n, raw["pnl"] / M + span * 0.015, num(raw["pnl"] / M, 2), ha="center", va="bottom", fontsize=6.6,
                fontweight="bold")
        ax.set_xticks(range(n + 1), [s[0] for s in steps] + ["total"], fontsize=6.8)
        ax.grid(axis="x", visible=False)
        ax.set_ylabel("₹ m")
        ax.set_ylim(0, span * 1.22)
        ax.set_title(f"{tid} lifetime P&L by bucket, ₹ m (horizon {day(HORIZON_END.isoformat(), True)})")
        note = (f"(0) deal margin at contract dates\n(a) {signed(raw['big_pnl'] / M, 2)} on {day(raw['big_date'])} alone\n"
                "(b) zero by construction on the MCX proxy\n(c), (d), (f) formula legs, CFR, no events")
        ax.text(0.52, 0.52, note, transform=ax.transAxes, ha="center", va="top", fontsize=6.4,
                bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=PALETTE["band"]))
        return save_fig(fig, WATERFALL, "attribution_daily.csv, new_deal_timing.csv (P3); MCX and USD/INR PROXY")


def chart_timeline(src: Mapping[str, pd.DataFrame], raw: Mapping) -> str:
    """Cumulative P&L over the net LME-equivalent position, with the two averaging windows and the flip marked."""
    tid = raw["tid"]
    ex = src["exp"][(src["exp"]["scope"] == "trade") & (src["exp"]["trade_id"] == tid)].copy()
    ex = ex[ex["date"] <= raw["close_date"]]
    ex["d"] = pd.to_datetime(ex["date"])
    clean = ex[~ex["date"].isin(raw["mcx_exit_dates"])]     # exit-day rows still carry the closing contract (docs/40 §7.1)
    with plt.rc_context({"font.size": 8.4, "axes.titlesize": 9.0}):
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(4.9, 3.35), sharex=True, gridspec_kw={"height_ratios": [1, 1.25]})
        a1.plot(ex["d"], ex["cum_pnl_inr"] / M, color=PALETTE["pnl"], lw=1.4, drawstyle="steps-post")
        a1.set_ylabel("cum P&L ₹ m")
        a1.set_title(f"{tid}: cumulative P&L and LME-equivalent position (MT)")
        a2.plot(clean["d"], clean["lme_delta_physical_mt"], color=PALETTE["lme"], lw=1.0, label="physical")
        a2.plot(clean["d"], clean["lme_delta_mcx_mt"], color=PALETTE["mcx"], lw=1.0, label="MCX")
        a2.plot(clean["d"], clean["lme_delta_mt"], color="black", lw=1.5, label="net")
        a2.axhline(0, color=PALETTE["neutral"], lw=0.6)
        a2.set_ylabel("MT")
        for ax in (a1, a2):
            ax.axvspan(pd.Timestamp(raw["sw_start"]), pd.Timestamp(raw["sw_end"]), color=PALETTE["mcx"], alpha=0.12, lw=0)
            ax.axvspan(pd.Timestamp(raw["qp_start"]), pd.Timestamp(raw["qp_end"]), color=PALETTE["lme"], alpha=0.10, lw=0)
            ax.axvline(pd.Timestamp(raw["big_date"]), color=PALETTE["loss"], lw=0.8, ls="--")
        ymax = a2.get_ylim()[1]
        a2.text(pd.Timestamp(raw["sw_start"]), ymax * 0.92, "sale avg ", fontsize=6.4, va="top", ha="right")
        a2.text(pd.Timestamp(raw["qp_end"]), ymax * 0.92, " purchase QP", fontsize=6.4, va="top", ha="left")
        a2.annotate(f"net {signed(raw['big_net_mt'])} MT at\nthe {day(raw['big_prev'])} close",
                    xy=(pd.Timestamp(raw["big_prev"]), raw["big_net_mt"]),
                    xytext=(pd.Timestamp(raw["qp_end"]) + pd.Timedelta(days=4), raw["big_net_mt"] * 0.62),
                    fontsize=6.4, va="center", arrowprops=dict(arrowstyle="->", lw=0.6))
        a1.annotate(f"{signed(raw['big_pnl'] / M, 2)} on {day(raw['big_date'])}",
                    xy=(pd.Timestamp(raw["big_date"]), (raw["min_cum"] + raw["big_pnl"]) / M),
                    xytext=(pd.Timestamp(raw["qp_end"]), raw["min_cum"] / M), fontsize=6.5,
                    arrowprops=dict(arrowstyle="->", lw=0.6))
        a2.legend(loc="lower right", fontsize=6.5, ncol=3)
        a2.tick_params(axis="x", labelsize=7, rotation=0)
        a2.xaxis.set_major_locator(mdates.MonthLocator())
        a2.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        return save_fig(fig, TIMELINE, "book_exposures_daily.csv (MCX exit-day rows omitted); MCX PROXY")


# ------------------------------------------------------------------------------------------------ PDF
_IMG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _figure_row(paths: list[Path], avail_w: float) -> Table:
    col_w = avail_w / len(paths)
    cells = []
    for p in paths:
        iw, ih = ImageReader(str(p)).getSize()
        w = col_w - FIG_GAP_MM * mm
        cells.append(Image(str(p), width=w, height=w * ih / iw))
    t = Table([cells], colWidths=[col_w] * len(paths))
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    return t


def render_pdf(md: str, out_path: Path, style: PdfStyle = PM_STYLE) -> int:
    """Markdown -> PDF through the shared renderer, plus image rows and explicit page breaks. Returns the page count."""
    register_fonts()
    avail_w = style.pagesize[0] - (style.margin_left_mm + style.margin_right_mm) * mm
    flow: list = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            flow.extend(markdown_to_flowables("\n".join(buf), style))
            buf.clear()

    for line in md.split("\n"):
        s = line.strip()
        imgs = _IMG.findall(s)
        if imgs and not _IMG.sub("", s).strip():
            flush()
            flow.append(_figure_row([(out_path.parent / p).resolve() for p in imgs], avail_w))
        elif s == PAGEBREAK:
            flush()
            flow.append(PageBreak())
        else:
            buf.append(line)
    flush()
    doc = DeskDocTemplate(str(out_path), style, title="Deal post-mortem (SIM)", author="Aluminium scrap desk (SIM)",
                          subject=SIM_LABEL, creator="desk.reporting.post_mortem")
    sink: list[int] = []
    doc.build(flow, canvasmaker=_numbered_canvas_class(SIM_LABEL, style, sink))
    return sink[-1] if sink else 0


# ------------------------------------------------------------------------------------------------ stage
def main() -> None:
    src = load_sources()
    md, raw = build_markdown(src)
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    chart_waterfall(raw)
    chart_timeline(src, raw)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path, pdf_path = REPORTS_DIR / f"{NAME}.md", REPORTS_DIR / f"{NAME}.pdf"
    md_path.write_text(md, encoding="utf-8")
    n = render_pdf(md, pdf_path)
    if n != MAX_PAGES or count_pdf_pages(pdf_path) != MAX_PAGES:
        raise ValueError(f"post-mortem must be exactly {MAX_PAGES} A4 pages; rendered {n}")


if __name__ == "__main__":
    main()
