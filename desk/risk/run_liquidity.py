"""Stage P5 — margin & liquidity (Table 6 row 4.5) and the one-page risk policy memo (row 4.6).

    DESK_OFFLINE=1 .venv/bin/python -c "import desk.risk.run_liquidity as m; m.main()"

Reads (never writes) the P3 tables, the Phase 4.1 volatility forecasts, the P1 parity week the facilities are sized
on and the P5 credit tables the memo quotes, and writes:

    outputs/tables/margin_liquidity.csv                 panel day: margin, cash by category, funding need, facility
                                                        headroom and breach flags, LC use, 99 % margin-at-risk
    outputs/tables/margin_liquidity_fortnight.csv       crash fortnight + worst margin fortnight: actual vs stressed
    outputs/tables/margin_liquidity_stress_moves.csv    the point-in-time 99 % 10-day LME move, every reading
    outputs/tables/margin_liquidity_facility.csv        the plan arithmetic behind each registered facility limit
    outputs/tables/margin_liquidity_limit_grid.csv      breach days at other facility sizes
    outputs/tables/margin_liquidity_lc_lots.csv         each LC lot: face, opening, release
    outputs/tables/margin_liquidity_windows.csv         the two fortnights and the rules that picked them
    outputs/tables/margin_liquidity_summary.csv         the numbers docs/51 and the memo quote
    outputs/tables/margin_liquidity_controls.csv        reconciliations to the P3 files (raises on FAIL)
    outputs/tables/margin_liquidity_policy_limits.csv   (via desk.risk.policy_memo) each limit vs the book
    outputs/charts/p5_liquidity_margin.png, p5_liquidity_fortnight.png
    outputs/reports/risk_policy_memo.md, risk_policy_memo.pdf
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from desk import SIM_LABEL, WINDOW_END
from desk.paths import TABLES_DIR, ensure_dirs
from desk.reporting.style import PALETTE, plt, save_fig
from desk.risk import liquidity as lq

FLOAT_DECIMALS = 6
GRID_FB_LIMITS_INR = (750e6, 1250e6, 1500e6)       # reporting grid around the registered ₹1,000 m line
GRID_LC_LIMITS_INR = (750e6, 1250e6, 1500e6)
M = 1e6


# ------------------------------------------------------------------------------------------------ io
def write(df: pd.DataFrame, name: str) -> str:
    """Deterministic CSV (CONTRACTS §1.5): fixed rounding, LF endings."""
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].round(FLOAT_DECIMALS)
    path = TABLES_DIR / f"{name}.csv"
    out.to_csv(path, index=False, lineterminator="\n")
    return str(path)


# ------------------------------------------------------------------------------------------------ summary
def _peak(d: pd.DataFrame, col: str, fn: str = "max") -> tuple[float, str]:
    i = d[col].idxmax() if fn == "max" else d[col].idxmin()
    return float(d.at[i, col]), str(d.at[i, "date"])


def _flag_span(d: pd.DataFrame, flag: str) -> tuple[int, str, str]:
    f = d[d[flag]]
    return int(len(f)), (str(f["date"].iloc[0]) if len(f) else ""), (str(f["date"].iloc[-1]) if len(f) else "")


def build_summary(daily: pd.DataFrame, fort: pd.DataFrame, windows: list[lq.Window], fac: lq.Facility,
                  moves: pd.DataFrame, fort_garch: pd.DataFrame) -> pd.DataFrame:
    rows: list[tuple] = []

    def add(metric, scope, value, unit, note=""):
        rows.append((metric, scope, value, unit, note))

    d = daily
    for col, fn, unit in (("cash_balance_inr", "min", "inr"), ("funding_need_total_inr", "max", "inr"),
                          ("commercial_funding_need_inr", "max", "inr"), ("margin_cash_deployed_inr", "max", "inr"),
                          ("margin_cash_deployed_inr", "min", "inr"), ("mcx_im_inr", "max", "inr"),
                          ("mcx_im_stress_015_inr", "max", "inr"), ("lc_outstanding_inr", "max", "inr"),
                          ("lc_outstanding_usd", "max", "usd"), ("bank_exposure_fb_plus_lc_inr", "max", "inr"),
                          ("mar_99_inr", "max", "inr"), ("mar_99_stressed_im_inr", "max", "inr"),
                          ("fb_utilisation_frac", "max", "frac"), ("lc_utilisation_frac", "max", "frac"),
                          ("mcx_lots_gross_open", "max", "lots")):
        v, dt = _peak(d, col, fn)
        add(f"{col}_{fn}", "book", v, unit, f"on {dt}")
    at = d.set_index("date")
    peak_day = str(d.loc[d["funding_need_total_inr"].idxmax(), "date"])
    for col in ("commercial_funding_need_inr", "margin_cash_deployed_inr", "interest_accrued_inr", "mcx_im_inr",
                "cash_purchase_cum_inr", "cash_sale_cum_inr", "cash_igst_cum_inr", "cash_duty_cum_inr",
                "lc_outstanding_inr"):
        add(f"{col}_on_peak_funding_day", "book", float(at.at[peak_day, col]), "inr", f"on {peak_day}")
    add("interest_accrued_inr_final", "book", float(d["interest_accrued_inr"].iloc[-1]), "inr",
        f"on {d['date'].iloc[-1]}; P3's funding accrual, added to the line as interest debited")
    add("fb_limit_inr", "facility", fac.fb_limit_inr, "inr", "liq_fb_wc_limit_inr")
    add("min_cash_buffer_inr", "facility", fac.buffer_inr, "inr", "liq_min_cash_buffer_frac_of_fb_limit x limit")
    add("lc_limit_inr", "facility", fac.lc_limit_inr, "inr", "liq_nfb_lc_limit_inr")
    for flag in ("flag_buffer_breach", "flag_fb_limit_breach", "flag_lc_limit_breach", "flag_mar_exceeds_buffer",
                 "flag_mar_exceeds_undrawn"):
        n, first, last = _flag_span(d, flag)
        add(f"days_{flag.removeprefix('flag_')}", "book", n, "count", f"{first} .. {last}" if n else "none")
    v, dt = _peak(d, "memo_lc_outstanding_ex_tolerance_inr", "max")
    add("memo_lc_outstanding_ex_tolerance_inr_max", "book", v, "inr",
        f"on {dt}; MEMO: planned face without the LC amount tolerance (an accepted usance bill is booked at invoice)")
    n_ex = int((d["memo_lc_outstanding_ex_tolerance_inr"] > fac.lc_limit_inr).sum())
    add("memo_days_lc_limit_breach_ex_tolerance", "book", n_ex, "count", "MEMO: as above, days over the LC line")
    v, dt = _peak(d, "headroom_inr", "min")
    add("headroom_inr_min", "book", v, "inr", f"on {dt}")
    v, dt = _peak(d, "undrawn_inr", "min")
    add("undrawn_inr_min", "book", v, "inr", f"on {dt}")
    rule = d["funding_need_total_inr"] + np.maximum(fac.buffer_inr, d["mar_99_stressed_im_inr"]) > fac.fb_limit_inr
    add("days_need_plus_max_buffer_or_mar_over_limit", "book", int(rule.sum()), "count",
        "the memo's liquidity rule: funding need + max(buffer, 99 % margin-at-risk at 15 % IM) > fund-based limit")
    first_book = d[d["cash_balance_inr"] != 0]["date"].iloc[0]
    add("book_first_cash_day", "book", str(first_book), "date", "")
    add("days_reported", "book", int(len(d)), "count", f"{d['date'].iloc[0]} .. {d['date'].iloc[-1]}")
    add("days_in_window_reported", "book", int(d["in_window"].sum()), "count", f"to WINDOW_END {WINDOW_END}")

    for w in windows:
        f = fort[fort["window"] == w.name]
        s = f.iloc[0]
        dw = d.set_index("date").loc[w.start:w.end]
        add("window_start", w.name, w.start, "date", w.rule)
        add("window_end", w.name, w.end, "date", "")
        add("lme_cash_return_frac", w.name, float(dw["lme_cash_usd_t"].iloc[-1] / dw["lme_cash_usd_t"].iloc[0] - 1),
            "frac", "actual, start close to end close")
        add("vm_actual_sum_inr", w.name, float(dw["vm_inr"].iloc[1:].sum()), "inr", "days after the start close")
        add("net_margin_cash_actual_sum_inr", w.name, float(dw["net_margin_cash_inr"].iloc[1:].sum()), "inr",
            "VM + charges − IM change; + = cash received")
        add("mcx_im_actual_max_inr", w.name, float(dw["mcx_im_inr"].max()), "inr", "")
        add("mcx_lots_net_open_at_start", w.name, float(dw["mcx_lots_net_open"].iloc[0]), "lots", "")
        add("stress_direction", w.name, str(s["stress_direction"]), "text", "the direction that calls more cash")
        add("stress_move_logret", w.name, float(s["stress_move_logret"]), "logret",
            f"binding reading: {s['stress_binding_method']} (as of the {w.start} close)")
        add("stress_move_frac", w.name, float(np.expm1(s["stress_move_logret"])), "frac", "")
        mv = moves.loc[w.start]
        for k in ("move_normal_garch_logret", "move_normal_hist250_logret", "move_normal_hist60_logret",
                  "move_empirical_up_logret", "move_empirical_down_logret"):
            add(k, w.name, float(mv[k]), "logret", f"as of the {w.start} close")
        add("lme_cash_stressed_end_usd_t", w.name, float(f["lme_cash_stressed_usd_t"].iloc[-1]), "usd_t", "")
        add("vm_stressed_sum_inr", w.name, float(f["vm_stressed_inr"].iloc[1:].sum()), "inr", "")
        for col in ("extra_margin_cash_out_inr", "extra_margin_cash_out_stressed_im_inr"):
            i = f[col].idxmax()
            add(f"{col}_max", w.name, float(f.at[i, col]), "inr", f"on {f.at[i, 'date']}")
        for col in ("headroom_actual_inr", "headroom_stressed_inr", "headroom_stressed_im_inr"):
            i = f[col].idxmin()
            add(f"{col}_min", w.name, float(f.at[i, col]), "inr", f"on {f.at[i, 'date']}")
        for col in ("flag_buffer_breach_actual", "flag_buffer_breach_stressed_im", "flag_fb_limit_breach_actual",
                    "flag_fb_limit_breach_stressed_im"):
            add(f"days_{col.removeprefix('flag_')}", w.name, int(f[col].iloc[1:].sum()), "count",
                "days after the start close")
        g = fort_garch[fort_garch["window"] == w.name]
        note = "SENSITIVITY: the same stress on the GARCH reading alone (not binding)"
        add("sens_garch_stress_move_frac", w.name, float(np.expm1(g["stress_move_logret"].iloc[0])), "frac", note)
        add("sens_garch_extra_margin_cash_out_stressed_im_inr_max", w.name,
            float(g["extra_margin_cash_out_stressed_im_inr"].max()), "inr", note)
        add("sens_garch_headroom_stressed_im_inr_min", w.name, float(g["headroom_stressed_im_inr"].min()), "inr", note)
        for col in ("flag_buffer_breach_stressed_im", "flag_fb_limit_breach_stressed_im"):
            add(f"sens_garch_days_{col.removeprefix('flag_')}", w.name, int(g[col].iloc[1:].sum()), "count", note)
        add("memo_physical_mtm_gain_end_inr", w.name, float(f["memo_physical_mtm_gain_inr"].iloc[-1]), "inr",
            "unrealised gain on the physical from the same move (start-day delta, linear): a mark, not cash")
        mc_std, mc_src = moves.attrs["mc_lme_daily_std"], moves.attrs["mc_lme_daily_std_source"]
        add("memo_mc_window_move_logret", w.name, float(fac.z * np.sqrt(fac.stress_horizon_days) * mc_std), "logret",
            f"HINDSIGHT memo, never binding: the Phase 4.2 Monte Carlo's LME marginal (Mar–Aug 2022 daily stdev "
            f"{mc_std:.6f} x sqrt(10) x z99, Normal) — {mc_src}")
    out = pd.DataFrame(rows, columns=["metric", "scope", "value", "unit", "note"])
    out["value"] = out["value"].astype(object)
    return out


def mc_lme_daily_std(inputs: lq.LiquidityInputs) -> tuple[float, str]:
    """The LME daily volatility behind the Phase 4.2 Monte Carlo (its 'variance source' row), for a memo comparison.

    The brief asks for the stress 'by the MC 99 % move'. That covariance is estimated on Mar–Aug 2022, i.e. partly
    AFTER an April stress date, so it is reported beside the point-in-time move and never used as the binding one.
    If the Monte Carlo table is absent (a stage run out of order) the same statistic is recomputed from the panel.
    """
    path = TABLES_DIR / "mc_factor_stats.csv"
    if path.exists():
        fs = pd.read_csv(path)
        row = fs[(fs["factor"] == "lme") & (fs["frequency"] == "daily") & (fs["role"] == "variance source")]
        if len(row) == 1:
            return float(row["stdev"].iloc[0]), "read from mc_factor_stats.csv"
    mkt = inputs.market["lme_cash_usd_t"]
    r = np.log(mkt).diff()
    win = r[(r.index >= str(lq.WINDOW_START)) & (r.index <= str(WINDOW_END))].dropna()
    return float(win.std(ddof=1)), "recomputed from market_daily.csv (mc_factor_stats.csv not built)"


# ------------------------------------------------------------------------------------------------ charts
def _shade(ax, windows: list[lq.Window], dates: pd.DatetimeIndex, legend: bool = False) -> None:
    colours = {"CRASH_FORTNIGHT": ("#f4b183", "crash fortnight (price)"),
               "MARGIN_FORTNIGHT": ("#bdd7ee", "worst margin fortnight (cash)")}
    for w in windows:
        c, lab = colours[w.name]
        ax.axvspan(pd.Timestamp(w.start), pd.Timestamp(w.end), color=c, alpha=0.45, lw=0,
                   label=lab if legend else None)
    ax.axvline(pd.Timestamp(WINDOW_END), color=PALETTE["neutral"], lw=0.8, ls=":")


def chart_margin(daily: pd.DataFrame, windows: list[lq.Window], fac: lq.Facility) -> str:
    d = daily.copy()
    x = pd.to_datetime(d["date"])
    fig, axes = plt.subplots(4, 1, figsize=(11, 12.5), sharex=True,
                             gridspec_kw={"height_ratios": [1.0, 1.35, 1.35, 1.2]})
    ax = axes[0]
    _shade(ax, windows, x, legend=True)
    ax.plot(x, d["lme_cash_usd_t"], color=PALETTE["lme"], lw=1.4, label="LME aluminium cash (DIRECT)")
    ax.set_ylabel("USD/t")
    ax.set_title("LME cash, with the two reporting fortnights shaded (dotted line = WINDOW_END)")
    ax.legend(loc="upper right", ncol=3, fontsize=8)

    ax = axes[1]
    _shade(ax, windows, x)
    ax.fill_between(x, 0, d["mcx_im_inr"] / M, step="post", color=PALETTE["mcx"], alpha=0.25,
                    label="initial margin posted (book)")
    ax.plot(x, d["mcx_im_stress_015_inr"] / M, color=PALETTE["mcx"], lw=0.9, ls="--", drawstyle="steps-post",
            label=f"initial margin at {lq.STRESS_IM_LABEL}")
    ax.plot(x, d["cum_vm_inr"] / M, color=PALETTE["gain"], lw=1.4, label="cumulative variation margin (+ received)")
    ax.plot(x, d["cum_margin_cash_inr"] / M, color=PALETTE["lme"], lw=1.6,
            label="cumulative net margin cash (VM + charges − IM)")
    ax.plot(x, d["mar_99_stressed_im_inr"] / M, color=PALETTE["loss"], lw=0.9, ls=":",
            label="99 % 10-day margin-at-risk (15 % IM)")
    ax.axhline(fac.buffer_inr / M, color=PALETTE["loss"], lw=0.8, ls="-.", label="minimum cash buffer")
    ax.axhline(0, color="black", lw=0.6)
    i = d["cum_margin_cash_inr"].idxmin()
    ax.annotate(f"peak outflow −₹{-d.at[i, 'cum_margin_cash_inr'] / M:,.1f} m on {d.at[i, 'date']}",
                (pd.Timestamp(d.at[i, "date"]), d.at[i, "cum_margin_cash_inr"] / M), xytext=(14, 2),
                textcoords="offset points", fontsize=8, color=PALETTE["lme"], va="center")
    ax.set_ylabel("₹ m")
    ax.set_ylim(top=max(d["mar_99_stressed_im_inr"].max(), d["cum_vm_inr"].max()) / M * 1.45)
    ax.set_title("MCX margin: posted, received and at risk (PROXY MCX series)")
    ax.legend(loc="upper right", ncol=2, fontsize=7.5)

    ax = axes[2]
    _shade(ax, windows, x)
    ax.fill_between(x, fac.fb_limit_inr / M, np.maximum(d["funding_need_total_inr"], fac.fb_limit_inr) / M,
                    color=PALETTE["loss"], alpha=0.35, lw=0, label="above the fund-based limit")
    ax.plot(x, d["funding_need_total_inr"] / M, color="black", lw=1.6, label="funding need (= line drawn)")
    ax.plot(x, d["commercial_funding_need_inr"] / M, color=PALETTE["freight"], lw=1.0,
            label="of which commercial cash (ex margin, ex interest)")
    ax.plot(x, d["margin_cash_deployed_inr"] / M, color=PALETTE["mcx"], lw=1.0,
            label="of which margin cash deployed (− = net received)")
    ax.plot(x, d["lc_outstanding_inr"] / M, color=PALETTE["fx"], lw=1.0, ls="--", label="LC outstanding (non-fund)")
    ax.axhline(fac.fb_limit_inr / M, color=PALETTE["loss"], lw=1.2, label="fund-based limit / LC limit (₹1,000 m)")
    ax.axhline((fac.fb_limit_inr - fac.buffer_inr) / M, color=PALETTE["loss"], lw=0.9, ls="-.",
               label="limit − buffer")
    ax.axhline(0, color="black", lw=0.6)
    ax.set_ylabel("₹ m")
    ax.set_title("Funding need against the ASSUMPTION facilities (sized on the Feb-2022 plan, not on this book)")
    ax.legend(loc="upper left", ncol=2, fontsize=7.5)

    ax = axes[3]
    _shade(ax, windows, x)
    h = d["headroom_inr"] / M
    ax.plot(x, h, color=PALETTE["lme"], lw=1.5, label="fund-based headroom = limit − buffer − funding need")
    ax.plot(x, (d["lc_limit_inr"] - d["lc_outstanding_inr"]) / M, color=PALETTE["fx"], lw=1.1, ls="--",
            label="LC headroom = LC limit − outstanding")
    ax.plot(x, (d["undrawn_inr"] - np.maximum(d["min_cash_buffer_inr"], d["mar_99_stressed_im_inr"])) / M,
            color=PALETTE["loss"], lw=0.9, ls=":", label="memo rule: limit − need − max(buffer, 99 % margin-at-risk)")
    ax.fill_between(x, h, 0, where=h < 0, color=PALETTE["loss"], alpha=0.3, lw=0, interpolate=True)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("₹ m")
    ax.set_title("Headroom (below zero = breach)")
    ax.legend(loc="lower left", ncol=2, fontsize=7.5)
    fig.tight_layout()
    return save_fig(fig, "p5_liquidity_margin",
                    "facilities ASSUMPTION (risk.yaml liq_*); cash, margin and LC from P3 tables; "
                    "MCX PROXY; LME DIRECT")


def chart_fortnight(fort: pd.DataFrame, windows: list[lq.Window], fac: lq.Facility) -> str:
    fig, axes = plt.subplots(len(windows), 2, figsize=(12.5, 5.4 * len(windows)))
    axes = np.atleast_2d(axes)
    for r, w in enumerate(windows):
        f = fort[fort["window"] == w.name].reset_index(drop=True)
        x = np.arange(len(f))
        labels = [s[5:] for s in f["date"]]
        ax = axes[r, 0]
        bw = 0.38
        ax.bar(x - bw / 2, f["vm_actual_inr"] / M, width=bw, color=PALETTE["gain"], label="VM actual")
        ax.bar(x + bw / 2, f["vm_stressed_inr"] / M, width=bw, color=PALETTE["loss"], label="VM stressed")
        ax.plot(x, f["im_actual_inr"] / M, color=PALETTE["mcx"], lw=1.3, marker="o", ms=3, label="IM actual")
        ax.plot(x, f["im_stressed_015_inr"] / M, color=PALETTE["mcx"], lw=1.3, ls="--", marker="o", ms=3,
                label=f"IM stressed at {lq.STRESS_IM_LABEL}")
        ax.plot(x, -f["extra_margin_cash_out_stressed_im_inr"] / M, color="black", lw=1.4,
                label="cumulative extra margin cash (− = out)")
        ax.axhline(0, color="black", lw=0.6)
        ax.set_xticks(x, labels, rotation=45, fontsize=8)
        ax.set_ylabel("₹ m")
        move = f["stress_move_logret"].iloc[0]
        ax.set_title(f"{w.name.replace('_', ' ').lower()} {w.start} → {w.end}\nMCX margin: actual vs LME "
                     f"{'+' if move > 0 else '−'}{abs(np.expm1(move)) * 100:.1f} % over the fortnight", fontsize=9.5)
        ax.legend(fontsize=7.5, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.2), frameon=False)
        ax2 = axes[r, 1]
        ax2.plot(x, f["headroom_actual_inr"] / M, color=PALETTE["lme"], lw=1.6, marker="o", ms=3,
                 label="headroom actual")
        ax2.plot(x, f["headroom_stressed_inr"] / M, color=PALETTE["loss"], lw=1.2, marker="o", ms=3,
                 label="headroom stressed (IM at 10 %)")
        ax2.plot(x, f["headroom_stressed_im_inr"] / M, color=PALETTE["loss"], lw=1.2, ls="--", marker="o", ms=3,
                 label=f"headroom stressed (IM at {lq.STRESS_IM_LABEL})")
        ax2.axhline(0, color="black", lw=0.8)
        ax2.axhline(-fac.buffer_inr / M, color=PALETTE["neutral"], lw=0.8, ls="-.", label="buffer spent (limit hit)")
        ax2.set_xticks(x, labels, rotation=45, fontsize=8)
        ax2.set_ylabel("₹ m")
        tw = ax2.twinx()
        tw.plot(x, f["lme_cash_actual_usd_t"], color=PALETTE["neutral"], lw=0.9, label="LME actual")
        tw.plot(x, f["lme_cash_stressed_usd_t"], color=PALETTE["neutral"], lw=0.9, ls="--", label="LME stressed")
        tw.set_ylabel("LME cash USD/t", color=PALETTE["neutral"])
        tw.grid(False)
        ax2.set_title(f"fund-based headroom, actual vs stressed\nbinding 99 % 10-day move: "
                      f"{f['stress_binding_method'].iloc[0]} reading at the {w.start} close", fontsize=9.5)
        h1, l1 = ax2.get_legend_handles_labels()
        h2, l2 = tw.get_legend_handles_labels()
        ax2.legend(h1 + h2, l1 + l2, fontsize=7.5, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.2),
                   frameon=False)
    fig.tight_layout()
    return save_fig(fig, "p5_liquidity_fortnight",
                    "STRESS: LME against the MCX hedges by the 99 % 10-day move; not a 2022 event. "
                    "Facilities ASSUMPTION")


# ------------------------------------------------------------------------------------------------ main
def main() -> None:
    ensure_dirs()
    fac = lq.facility_params()
    inputs = lq.load_inputs(fac)
    daily, lots, moves = lq.build_daily(inputs, fac)

    ctrl = lq.controls(inputs, daily)
    write(ctrl, "margin_liquidity_controls")
    if (ctrl["status"] == "FAIL").any():
        raise ValueError(f"margin & liquidity controls failed:\n{ctrl[ctrl['status'] == 'FAIL']}")

    windows = [lq.crash_fortnight(inputs), lq.margin_fortnight(daily)]
    for w in windows:
        col = f"in_{w.name.lower()}"
        daily.insert(2, col, (daily["date"] >= w.start) & (daily["date"] <= w.end))
    fort = pd.concat([lq.fortnight_stress(inputs, daily, moves, w, fac) for w in windows], ignore_index=True)
    moves.attrs["mc_lme_daily_std"], moves.attrs["mc_lme_daily_std_source"] = mc_lme_daily_std(inputs)

    sizing = lq.facility_sizing(inputs, fac)
    grid = lq.limit_grid(daily, fac, GRID_FB_LIMITS_INR, GRID_LC_LIMITS_INR)
    garch_only = moves.copy()
    garch_only["stress_move_up_logret"] = garch_only["move_normal_garch_logret"]
    garch_only["stress_move_down_logret"] = -garch_only["move_normal_garch_logret"]
    garch_only["stress_binding_up"] = garch_only["stress_binding_down"] = "garch"
    fort_garch = pd.concat([lq.fortnight_stress(inputs, daily, garch_only, w, fac) for w in windows], ignore_index=True)
    summary = build_summary(daily, fort, windows, fac, moves, fort_garch)
    win_tbl = pd.DataFrame([{"window": w.name, "start": w.start, "end": w.end, "rule": w.rule, "reporting_only": True}
                            for w in windows])

    write(daily, "margin_liquidity")
    write(fort, "margin_liquidity_fortnight")
    mv = moves.reset_index()
    mv["label"] = SIM_LABEL
    write(mv, "margin_liquidity_stress_moves")
    write(sizing.assign(value=sizing["value"].astype(str)), "margin_liquidity_facility")
    write(grid, "margin_liquidity_limit_grid")
    lot_cols = ["trade_id", "lot", "payment_instrument", "usance_days", "lc_open_date", "lc_release_date",
                "face_planned_usd", "lc_amount_tolerance_frac", "lc_face_usd"]
    write(lots[lot_cols].sort_values(["trade_id", "lot"]).assign(label=SIM_LABEL), "margin_liquidity_lc_lots")
    write(win_tbl, "margin_liquidity_windows")
    write(summary.assign(value=summary["value"].map(lambda v: repr(round(v, FLOAT_DECIMALS)) if isinstance(v, float)
                                                     else str(v))), "margin_liquidity_summary")

    chart_margin(daily, windows, fac)
    chart_fortnight(fort, windows, fac)

    from desk.risk import policy_memo
    policy_memo.main()


if __name__ == "__main__":
    main()
