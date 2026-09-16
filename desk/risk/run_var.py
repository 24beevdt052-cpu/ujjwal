"""Phase 4.1 ★ stage — daily 95 % VaR on the book, GARCH(1,1) against historical volatility, with Kupiec backtests.

    DESK_OFFLINE=1 .venv/bin/python -c "import desk.risk.run_var as m; m.main()"

Reads only files (CONTRACTS §1.7): `data/processed/market_daily.csv`, `outputs/tables/book_exposures_daily.csv`
(BOOK scope), `attribution_daily.csv` (BOOK rows), `attribution_leg_daily.csv` (the FUNDING leg, memo only),
`adverse_event_windows.csv` (chart annotations), `mcx_basis_risk.csv` (the P3 daily MCX beta, sensitivity only) and,
through `desk.mtm.history.MarketHistory(mcx_source="mirror")`, the third-party MCX mirror (the same engine view P3's
beta test and Phase 4.2 use), to re-measure that beta at weekly and close-time-matched sampling (`var_mcx_beta.csv`).

What it builds (docs/40_var_garch.md is the method page):

1. One-step-ahead daily volatility for LME cash and USD/INR log returns by GARCH(1,1) (weekly refit, daily filter,
   expanding sample from HISTORY_START) and by two rolling windows (base and fast), every forecast using returns
   dated strictly before its date. Freight (one factor, the USEC lane) and the LME cash-3M spread use the base
   rolling window in both methods: they are not what the comparison is about.
2. Book VaR for each panel day t from the previous close's BOOK exposures (the position held into t), mapped to
   rupees per unit factor move, combined with a rolling past-only correlation matrix: delta-normal, 95 %, one day.
3. Backtests against the day's realised MARKET P&L of the same factors — attribution buckets (a) lme_flat,
   (b) cross_exchange_basis, (d) freight, (e) fx — plus a constant-exposure backtest over 2019–2022 for power.
4. The finding: when each method's volatility first rose above its own pre-2022 percentile going into the March-2022
   spike and the May–July crash, and by how many trading days GARCH led or lagged.
5. SENSITIVITY: the MCX leg at the mirror's measured beta instead of the proxy's unit beta. The P3 daily beta (0.45)
   is biased toward zero by asynchronous closes, so the beta is also measured on weekly changes and with a
   lead/lag regression, and the VaR is re-run at the daily and weekly betas (`var_mcx_beta.csv`, docs/40 §4.3).
"""

from __future__ import annotations

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from desk import HISTORY_START, HORIZON_END, PANEL_END, SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.paths import PROCESSED_DIR, TABLES_DIR, ensure_dirs
from desk.reporting.style import PALETTE, save_fig
from desk.risk import backtest as bt
from desk.risk import garch_var as gv

P_EXCEPTION = 1.0 - gv.VAR_CONFIDENCE
MILLION = 1e6
BOOK_FACTORS = ["lme", "fx", "freight"]            # base VaR factors: exactly the buckets the backtest P&L holds
MEMO_FACTORS = ["lme", "fx", "freight", "spread"]  # memo: adds the LME cash-3M spread
MARKET_BUCKETS = ["lme_flat", "cross_exchange_basis", "freight", "fx"]
# MCX beta samplings the VaR is re-run at (SENSITIVITY). The column suffix "" keeps the published daily-beta names.
BETA_VAR_SAMPLINGS = {"daily": "", "weekly": "_weekly"}
WEEK_FREQ = "W-FRI"                                  # CONTRACTS §3: week = week ending Friday
SOURCE_NOTE = ("LME DIRECT (Westmetall/LME official); USD/INR PROXY (ECB cross); freight ASSUMPTION reconstruction; "
               "book, exposures and P&L SIM")
EXPOSURE_COLS = ["date", "scope", "lme_delta_inr_per_usd_t", "lme_delta_physical_mt", "lme_delta_mcx_mt",
                 "fx_delta_usd", "fx_delta_physical_usd", "fx_delta_forwards_usd", "fx_delta_mcx_usd",
                 "freight_delta_inr_per_usd_t_jea_nsa", "freight_delta_inr_per_usd_t_usec_mun",
                 "spread_delta_inr_per_usd_t", "customs_fx_delta_usd", "lme_fx_cross_inr"]


# --------------------------------------------------------------------------------------------------- params
def settings() -> dict:
    """Every judgement parameter from config/params/risk.yaml (Phase 4.1 section)."""
    v = config.value
    return {
        "refit": str(v("var_garch_refit_frequency")),
        "min_obs": int(v("var_garch_min_estimation_obs")),
        "w_base": int(v("var_hist_window_base_days")),
        "w_fast": int(v("var_hist_window_fast_days")),
        "w_corr": int(v("var_corr_window_days")),
        "alert_pcts": [float(x) for x in v("var_vol_alert_percentiles")],
        "alert_ref": tuple(pd.Timestamp(x) for x in v("var_vol_alert_reference_period")),
        "episodes": [(str(n), pd.Timestamp(a), pd.Timestamp(b)) for n, a, b in v("var_lead_episodes")],
        "unit_start": pd.Timestamp(v("var_unit_backtest_start")),
        "unit_lme_mt": float(v("var_unit_lme_mt")),
        "unit_fx_usd": float(v("var_unit_fx_usd")),
    }


def method_names(s: dict) -> dict[str, str]:
    return {"garch": "garch", "hist_base": f"hist{s['w_base']}", "hist_fast": f"hist{s['w_fast']}"}


# ------------------------------------------------------------------------------------------------------ I/O
def write(df: pd.DataFrame, name: str) -> None:
    """Deterministic CSV (CONTRACTS §1.5): fixed rounding by unit suffix, ISO dates, LF endings."""
    out = df.copy()
    for c in out.columns:
        if not pd.api.types.is_float_dtype(out[c]):
            continue
        if c.endswith("_inr") or c.endswith("_usd"):
            out[c] = out[c].round(2)
        elif c.endswith("_mt") or c.endswith("_usd_t") or c.endswith("_days"):
            out[c] = out[c].round(4)
        else:
            out[c] = out[c].round(8)
    out.to_csv(TABLES_DIR / f"{name}.csv", index=False, lineterminator="\n", date_format="%Y-%m-%d")


def load_panel() -> pd.DataFrame:
    cols = ["date", "lme_cash_usd_t", "lme_cash_3m_spread_usd_t", "usdinr", "freight_jea_nsa_usd_t",
            "freight_usec_mun_usd_t"]
    p = pd.read_csv(PROCESSED_DIR / "market_daily.csv", usecols=cols, parse_dates=["date"]).set_index("date")
    if p.index[0].date() != HISTORY_START:
        raise ValueError(f"panel starts {p.index[0].date()}, expected HISTORY_START {HISTORY_START}")
    if p[["lme_cash_usd_t", "usdinr"]].isna().any().any():
        raise ValueError("panel has missing LME or USD/INR values")
    return p


def factor_changes(panel: pd.DataFrame) -> pd.DataFrame:
    """Daily factor changes dated on the later day: three log returns and the spread's absolute change."""
    fr = panel["freight_usec_mun_usd_t"]
    return pd.DataFrame({
        "lme": gv.log_returns(panel["lme_cash_usd_t"]),
        "fx": gv.log_returns(panel["usdinr"]),
        # JEA_NSA = 0.2255 x USEC_MUN on every week (docs/reviews fix log #15): one freight factor, the USEC lane.
        "freight": np.log(fr / fr.shift(1)),
        "spread": gv.abs_changes(panel["lme_cash_3m_spread_usd_t"]),
    }).iloc[1:]  # the first panel day has no change


# ---------------------------------------------------------------------------------------------- vol forecasts
def vol_forecasts(chg: pd.DataFrame, s: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every daily vol forecast the stage uses, on every panel day that has `min_obs` prior returns."""
    names = method_names(s)
    targets = chg.index[s["min_obs"]:]
    out = pd.DataFrame(index=targets)
    fits = []
    for series in ("lme", "fx"):
        r = chg[series]
        g, f = gv.garch_forecasts(r, targets, series=series, min_obs=s["min_obs"], refit_freq=s["refit"])
        gt, ft = gv.garch_forecasts(r, targets, series=series, min_obs=s["min_obs"], refit_freq=s["refit"],
                                    dist=gv.GARCH_DIST_SENSITIVITY)
        fits += f + ft
        out[f"{series}_ret"] = r.reindex(targets)
        out[f"sigma_{series}_garch_frac"] = g["sigma_frac"]
        out[f"sigma_{series}_{names['hist_base']}_frac"] = gv.hist_vol(r, s["w_base"]).reindex(targets)
        out[f"sigma_{series}_{names['hist_fast']}_frac"] = gv.hist_vol(r, s["w_fast"]).reindex(targets)
        out[f"sigma_{series}_garch_t_frac"] = gt["sigma_frac"]
        out[f"nu_{series}_garch_t"] = gt["nu"]
        out[f"{series}_garch_sample_end"] = g["sample_end"]
        out[f"{series}_garch_boundary_fit"] = g["boundary"]
    out[f"sigma_freight_{names['hist_base']}_frac"] = gv.hist_vol(chg["freight"], s["w_base"]).reindex(targets)
    out[f"sigma_spread_{names['hist_base']}_usd_t"] = gv.hist_vol(chg["spread"], s["w_base"]).reindex(targets)
    for a, b in [("lme", "fx"), ("lme", "freight"), ("fx", "freight"), ("lme", "spread"), ("fx", "spread"),
                 ("freight", "spread")]:
        out[f"corr_{a}_{b}"] = gv.rolling_corr(chg[a], chg[b], s["w_corr"]).reindex(targets)
    out.index.name = "date"
    return out, gv.fits_frame(fits)


# -------------------------------------------------------------------------------------------------- book VaR
def load_book_inputs(days: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    ex = pd.read_csv(TABLES_DIR / "book_exposures_daily.csv", usecols=EXPOSURE_COLS, parse_dates=["date"])
    ex = ex[ex["scope"].str.lower() == "book"].drop(columns="scope").set_index("date")
    at = pd.read_csv(TABLES_DIR / "attribution_daily.csv", parse_dates=["date"])
    at = at[at["trade_id"] == "BOOK"].set_index("date")   # BOOK rows only: never add them to the trade rows
    leg = pd.read_csv(TABLES_DIR / "attribution_leg_daily.csv", usecols=["date", "leg_id", "roll_term_structure"],
                      parse_dates=["date"])
    funding_g = leg[leg["leg_id"] == "FUNDING"].groupby("date")["roll_term_structure"].sum()
    return ex, at, funding_g


def mcx_exit_or_roll_dates() -> set:
    """Days an MCX tranche exits or rolls out (mcx_variation_margin.csv). See docs/40 §7: the P3 exposures dated on
    these days still carry the exiting contract, and bucket (a) the next day does too (reversed in (g))."""
    vm = pd.read_csv(TABLES_DIR / "mcx_variation_margin.csv", usecols=["date", "action"], parse_dates=["date"])
    return set(vm.loc[vm["action"].isin(["exit", "roll_out"]), "date"])


def book_var(panel: pd.DataFrame, vols: pd.DataFrame, s: dict, betas: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """One row per panel day WINDOW_START..HORIZON_END: exposures held from the previous close, VaR, realised P&L."""
    names = method_names(s)
    hb = names["hist_base"]
    cal = panel.index
    days = cal[(cal >= pd.Timestamp(WINDOW_START)) & (cal <= pd.Timestamp(HORIZON_END))]
    prev = cal[cal.get_indexer(days) - 1]
    ex, at, funding_g = load_book_inputs(days)
    e = ex.reindex(prev).fillna(0.0)
    e.index = days
    lvl = panel.reindex(prev)
    lvl.index = days

    d = pd.DataFrame(index=days)
    d.index.name = "date"
    d["in_window"] = days <= pd.Timestamp(WINDOW_END)
    d["position_date"] = prev
    d["lme_cash_usd_t_prev"] = lvl["lme_cash_usd_t"]
    d["usdinr_prev"] = lvl["usdinr"]
    L, F = lvl["lme_cash_usd_t"], lvl["usdinr"]
    # ₹ per unit log return (per USD/t for the spread): delta x level of the previous close
    d["exp_lme_inr"] = e["lme_delta_inr_per_usd_t"] * L
    d["exp_lme_physical_inr"] = e["lme_delta_physical_mt"] * F * L
    d["exp_lme_mcx_inr"] = e["lme_delta_mcx_mt"] * F * L
    d["exp_fx_inr"] = e["fx_delta_usd"] * F
    d["exp_fx_physical_forwards_inr"] = (e["fx_delta_physical_usd"] + e["fx_delta_forwards_usd"]) * F
    d["exp_fx_mcx_inr"] = e["fx_delta_mcx_usd"] * F
    d["exp_freight_inr"] = (e["freight_delta_inr_per_usd_t_usec_mun"] * lvl["freight_usec_mun_usd_t"].fillna(0.0)
                            + e["freight_delta_inr_per_usd_t_jea_nsa"] * lvl["freight_jea_nsa_usd_t"].fillna(0.0))
    d["exp_spread_inr_per_usd_t"] = e["spread_delta_inr_per_usd_t"]
    d["memo_customs_fx_delta_usd"] = e["customs_fx_delta_usd"]
    d["lme_ret_frac"] = vols["lme_ret"].reindex(days)
    d["fx_ret_frac"] = vols["fx_ret"].reindex(days)
    d["position_held"] = (d[["exp_lme_inr", "exp_fx_inr", "exp_freight_inr"]].abs().sum(axis=1) > 0)
    d["position_date_mcx_exit_or_roll"] = d["position_date"].isin(mcx_exit_or_roll_dates())

    v = vols.reindex(days)
    if v[[f"sigma_lme_garch_frac", f"sigma_fx_garch_frac", f"sigma_freight_{hb}_frac", "corr_lme_fx"]].isna().any().any():
        raise ValueError("missing vol or correlation forecast on a book day")
    for series in ("lme", "fx"):
        for m in names.values():
            d[f"sigma_{series}_{m}_frac"] = v[f"sigma_{series}_{m}_frac"]
    d[f"sigma_freight_{hb}_frac"] = v[f"sigma_freight_{hb}_frac"]
    d[f"sigma_spread_{hb}_usd_t"] = v[f"sigma_spread_{hb}_usd_t"]
    for c in ["corr_lme_fx", "corr_lme_freight", "corr_fx_freight", "corr_lme_spread", "corr_fx_spread",
              "corr_freight_spread"]:
        d[c] = v[c].fillna(0.0)

    n = len(days)
    pair_cols = {("lme", "fx"): "corr_lme_fx", ("lme", "freight"): "corr_lme_freight",
                 ("fx", "freight"): "corr_fx_freight", ("lme", "spread"): "corr_lme_spread",
                 ("fx", "spread"): "corr_fx_spread", ("freight", "spread"): "corr_freight_spread"}

    def corr_for(factors):
        pairs = {k: d[c].to_numpy() for k, c in pair_cols.items() if k[0] in factors and k[1] in factors}
        return gv.corr_matrix(pairs, factors, n)

    R3, R4 = corr_for(BOOK_FACTORS), corr_for(MEMO_FACTORS)
    sig_fr = d[f"sigma_freight_{hb}_frac"].to_numpy()
    sig_sp = d[f"sigma_spread_{hb}_usd_t"].to_numpy()
    E3 = d[["exp_lme_inr", "exp_fx_inr", "exp_freight_inr"]].to_numpy()
    E4 = d[["exp_lme_inr", "exp_fx_inr", "exp_freight_inr", "exp_spread_inr_per_usd_t"]].to_numpy()
    z = gv.Z_VAR
    for m in names.values():
        sl, sf = d[f"sigma_lme_{m}_frac"].to_numpy(), d[f"sigma_fx_{m}_frac"].to_numpy()
        d[f"var_{m}_inr"] = gv.parametric_var(E3, np.column_stack([sl, sf, sig_fr]), R3)
        d[f"var_{m}_incl_spread_memo_inr"] = gv.parametric_var(E4, np.column_stack([sl, sf, sig_fr, sig_sp]), R4)
    for m in (names["garch"], names["hist_base"]):
        sl, sf = d[f"sigma_lme_{m}_frac"], d[f"sigma_fx_{m}_frac"]
        d[f"var_{m}_lme_inr"] = z * d["exp_lme_inr"].abs() * sl
        d[f"var_{m}_lme_physical_inr"] = z * d["exp_lme_physical_inr"].abs() * sl
        d[f"var_{m}_lme_mcx_inr"] = z * d["exp_lme_mcx_inr"].abs() * sl
        d[f"var_{m}_fx_inr"] = z * d["exp_fx_inr"].abs() * sf
        d[f"var_{m}_fx_physical_forwards_inr"] = z * d["exp_fx_physical_forwards_inr"].abs() * sf
        d[f"var_{m}_fx_mcx_inr"] = z * d["exp_fx_mcx_inr"].abs() * sf
        # SENSITIVITY: the MCX leg moves beta x parity plus an idiosyncratic basis (R² of the mirror regression at
        # the same sampling, variance scaled with time like parity's), instead of one-for-one. Physical and forwards
        # are unchanged. Daily beta = the pessimistic end (asynchronous closes bias it down); weekly = the central read.
        rho = d["corr_lme_fx"]
        sig_parity = np.sqrt(sl ** 2 + sf ** 2 + 2 * rho * sl * sf)
        for sampling, suffix in BETA_VAR_SAMPLINGS.items():
            mcx_beta, mcx_r2 = betas[sampling]
            sig_basis = mcx_beta * sig_parity * np.sqrt((1.0 - mcx_r2) / mcx_r2)
            Eb = np.column_stack([d["exp_lme_physical_inr"] + mcx_beta * d["exp_lme_mcx_inr"],
                                  d["exp_fx_physical_forwards_inr"] + mcx_beta * d["exp_fx_mcx_inr"],
                                  d["exp_freight_inr"], d["exp_lme_mcx_inr"]])
            Sb = np.column_stack([sl, sf, sig_fr, sig_basis])
            Rb = np.zeros((n, 4, 4))
            Rb[:, :3, :3] = R3
            Rb[:, 3, 3] = 1.0
            d[f"var_{m}_mcx_beta{suffix}_sensitivity_inr"] = gv.parametric_var(Eb, Sb, Rb)
    d[f"var_freight_{hb}_inr"] = z * d["exp_freight_inr"].abs() * d[f"sigma_freight_{hb}_frac"]

    a = at.reindex(days).fillna(0.0)
    for b in MARKET_BUCKETS:
        d[f"pnl_{b}_inr"] = a[b]
    d["pnl_market_inr"] = a[MARKET_BUCKETS].sum(axis=1)
    d["memo_pnl_grade_spread_inr"] = a["grade_spread"]
    d["memo_pnl_roll_term_structure_inr"] = a["roll_term_structure"]
    d["memo_pnl_funding_carry_inr"] = funding_g.reindex(days).fillna(0.0)
    d["memo_pnl_roll_ex_funding_inr"] = d["memo_pnl_roll_term_structure_inr"] - d["memo_pnl_funding_carry_inr"]
    d["memo_pnl_broad_inr"] = d["pnl_market_inr"] + d["memo_pnl_roll_ex_funding_inr"]
    d["memo_pnl_new_deal_inr"] = a["new_deal"]
    d["memo_pnl_demurrage_penalty_inr"] = a["demurrage_penalty"]
    d["daily_pnl_inr"] = a["daily_pnl_inr"]
    for m in names.values():
        d[f"exception_{m}"] = d["position_held"] & bt.exceptions(d["pnl_market_inr"], d[f"var_{m}_inr"])
    return d


# ---------------------------------------------------------------------------------------------- unit backtest
def unit_backtest(panel: pd.DataFrame, vols: pd.DataFrame, s: dict) -> pd.DataFrame:
    names = method_names(s)
    cal = panel.index
    days = vols.index[(vols.index >= s["unit_start"]) & (vols.index <= pd.Timestamp(PANEL_END))]
    pos = cal.get_indexer(days)
    L, F = panel["lme_cash_usd_t"].to_numpy(), panel["usdinr"].to_numpy()
    u = pd.DataFrame(index=days)
    u.index.name = "date"
    u["lme_cash_usd_t"] = L[pos]
    u["usdinr"] = F[pos]
    u["unit_lme_pnl_inr"] = s["unit_lme_mt"] * (L[pos] - L[pos - 1]) * F[pos]
    u["unit_fx_pnl_inr"] = s["unit_fx_usd"] * (F[pos] - F[pos - 1])
    lme_exp = s["unit_lme_mt"] * L[pos - 1] * F[pos - 1]
    fx_exp = s["unit_fx_usd"] * F[pos - 1]
    v = vols.reindex(days)
    for series, exp in (("lme", lme_exp), ("fx", fx_exp)):
        for m in list(names.values()):
            u[f"unit_{series}_var_{m}_inr"] = gv.Z_VAR * v[f"sigma_{series}_{m}_frac"].to_numpy() * exp
        mult = np.array([gv.t_var_multiplier(x) for x in v[f"nu_{series}_garch_t"].to_numpy()])
        u[f"unit_{series}_var_garch_t_inr"] = mult * v[f"sigma_{series}_garch_t_frac"].to_numpy() * exp
        for m in list(names.values()) + ["garch_t"]:
            u[f"unit_{series}_exception_{m}"] = bt.exceptions(u[f"unit_{series}_pnl_inr"], u[f"unit_{series}_var_{m}_inr"])
    return u


# ------------------------------------------------------------------------------------------------ backtests
def kupiec_table(book: pd.DataFrame, unit: pd.DataFrame, vols: pd.DataFrame,
                 s: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    names = method_names(s)
    rows, exc = [], []
    held = book[book["position_held"]]
    samples = [
        ("book_window", held[held["in_window"]], "pnl_market_inr", "var_{m}_inr", "BASE"),
        ("book_to_horizon_memo", held, "pnl_market_inr", "var_{m}_inr", "MEMO — extends past WINDOW_END"),
        ("book_window_broad_memo", held[held["in_window"]], "memo_pnl_broad_inr", "var_{m}_incl_spread_memo_inr",
         "MEMO — P&L adds (g) ex-funding, VaR adds the cash-3M spread; tests coverage, not the vol forecast"),
        ("book_window_ex_mcx_exit_roll_days_memo",
         held[held["in_window"] & ~held["position_date_mcx_exit_or_roll"]], "pnl_market_inr", "var_{m}_inr",
         "MEMO — drops the days after an MCX exit/roll, whose exposure carries the exiting contract (docs/40 §7)"),
    ]
    for sample, frame, pnl_col, var_tmpl, role in samples:
        for key, m in names.items():
            var_col = var_tmpl.format(m=m)
            hits = pd.Series(bt.exceptions(frame[pnl_col], frame[var_col]), index=frame.index)
            rows.append(bt.summarise(hits, p=P_EXCEPTION, sample=sample, method=m, role=role, pnl_column=pnl_col,
                                     var_column=var_col, mean_var_inr=float(frame[var_col].mean()),
                                     label=SIM_LABEL))
            for dte in hits.index[hits.to_numpy()]:
                r = frame.loc[dte]
                buckets = {b: r[f"pnl_{b}_inr"] for b in MARKET_BUCKETS}
                exc.append({
                    "sample": sample, "method": m, "date": dte, "position_date": r["position_date"],
                    "var_inr": r[var_col], "pnl_inr": r[pnl_col], "shortfall_inr": -r[pnl_col] - r[var_col],
                    "loss_to_var_frac": -r[pnl_col] / r[var_col],
                    "sigma_lme_frac": r[f"sigma_lme_{m}_frac"], "sigma_fx_frac": r[f"sigma_fx_{m}_frac"],
                    "lme_ret_frac": r["lme_ret_frac"], "fx_ret_frac": r["fx_ret_frac"],
                    "pnl_lme_flat_inr": buckets["lme_flat"], "pnl_fx_inr": buckets["fx"],
                    "pnl_freight_inr": buckets["freight"], "pnl_cross_exchange_basis_inr": buckets["cross_exchange_basis"],
                    "largest_loss_bucket": min(buckets, key=buckets.get), "label": SIM_LABEL,
                })
    unit_samples = [("unit_lme_long_1000mt", "lme"), ("unit_usd_long_1m", "fx")]
    years = sorted(set(unit.index.year))
    year_rows = []
    for sample, series in unit_samples:
        for y in years:
            sub = unit[unit.index.year == y]
            for m in list(names.values()) + ["garch_t"]:
                var_col = f"unit_{series}_var_{m}_inr"
                year_rows.append(bt.summarise(sub[f"unit_{series}_exception_{m}"], p=P_EXCEPTION, sample=f"{sample}_{y}",
                                         method=m, role=f"MEMO — calendar-year split ({len(years) * 4} tests per "
                                         "series: about one false rejection at 5 % is expected by chance)",
                                         pnl_column=f"unit_{series}_pnl_inr", var_column=var_col,
                                         mean_var_inr=float(sub[var_col].mean()), label=SIM_LABEL))
        for m in list(names.values()) + ["garch_t"]:
            hits = unit[f"unit_{series}_exception_{m}"]
            role = "SENSITIVITY — Student-t GARCH" if m == "garch_t" else "BASE (power check)"
            var_col = f"unit_{series}_var_{m}_inr"
            rows.append(bt.summarise(hits, p=P_EXCEPTION, sample=sample, method=m, role=role,
                                     pnl_column=f"unit_{series}_pnl_inr", var_column=var_col,
                                     mean_var_inr=float(unit[var_col].mean()), label=SIM_LABEL))
            for dte in hits.index[hits.to_numpy()]:
                pnl, var = unit.at[dte, f"unit_{series}_pnl_inr"], unit.at[dte, var_col]
                sig_col = f"sigma_{series}_{m}_frac"
                exc.append({
                    "sample": sample, "method": m, "date": dte, "position_date": pd.NaT, "var_inr": var,
                    "pnl_inr": pnl, "shortfall_inr": -pnl - var, "loss_to_var_frac": -pnl / var,
                    "sigma_lme_frac": vols.at[dte, sig_col] if series == "lme" else np.nan,
                    "sigma_fx_frac": vols.at[dte, sig_col] if series == "fx" else np.nan,
                    "lme_ret_frac": vols.at[dte, "lme_ret"], "fx_ret_frac": vols.at[dte, "fx_ret"],
                    "largest_loss_bucket": "n/a (constant exposure)", "label": SIM_LABEL,
                })
    exc = pd.DataFrame(exc)
    exc["position_date"] = pd.to_datetime(exc["position_date"])
    return pd.DataFrame(rows + year_rows), exc


def calibration_table(book: pd.DataFrame, unit: pd.DataFrame, s: dict) -> pd.DataFrame:
    """How well each VaR was SCALED, period by period: std of P&L / (VaR / z) should be ~1, exceptions ~5 %.

    Kupiec only counts exceptions over the whole sample; this shows where a method was too tight or too loose.
    """
    names = method_names(s)
    rows = []
    held = book[book["position_held"] & book["in_window"]]
    groups = [("book_window", held, "pnl_market_inr", "var_{m}_inr", held.index.to_period("M").astype(str),
               list(names.values()))]
    for series, sample in (("lme", "unit_lme_long_1000mt"), ("fx", "unit_usd_long_1m")):
        groups.append((sample, unit, f"unit_{series}_pnl_inr", f"unit_{series}_var_{{m}}_inr",
                       unit.index.year.astype(str), list(names.values()) + ["garch_t"]))
    for sample, frame, pnl_col, tmpl, period, methods in groups:
        for m in methods:
            var = frame[tmpl.format(m=m)]
            zstd = frame[pnl_col] / (var / gv.Z_VAR)
            hits = pd.Series(bt.exceptions(frame[pnl_col], var), index=frame.index)
            for per in list(pd.unique(period)) + ["ALL"]:
                mask = np.ones(len(frame), dtype=bool) if per == "ALL" else (np.asarray(period) == per)
                rows.append({"sample": sample, "period": per, "method": m, "n": int(mask.sum()),
                             "exceptions": int(hits[mask].sum()), "expected": mask.sum() * P_EXCEPTION,
                             "std_pnl_over_var_sigma": float(zstd[mask].std()),
                             "mean_var_inr": float(var[mask].mean()),
                             "note": "std_pnl_over_var_sigma = std of P&L / (VaR / 1.645): >1 VaR too tight, <1 too loose"})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------- lead / lag finding
def _alert(sig: pd.Series, thr: float, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """When a vol forecast flagged rising risk inside [start, end].

    `alert_date` is the first up-crossing of `thr` inside the window; if the forecast was ALREADY above `thr` when the
    window opened, it is the day that spell began (possibly long before the window) and `alert_type` says so — a
    method that never came back down cannot "flag" a new episode, and the table must not pretend it did.
    `first_upcrossing_in_window` is reported separately either way (a fresh alert after a dip below the threshold).
    """
    s = sig.dropna()
    above = s > thr
    prev = above.shift(1, fill_value=False)
    win = above[(above.index >= start) & (above.index <= end)]
    out = {"alert_date": None, "alert_type": "NO_DATA", "above_at_window_open": None,
           "first_upcrossing_in_window": None, "days_below_threshold_in_window": 0}
    if win.empty:
        return out
    prev_w = prev.reindex(win.index)
    ups = win[win & ~prev_w]  # an up-crossing on the opening day itself counts as a fresh alert
    out["days_below_threshold_in_window"] = int((~win).sum())
    carried = bool(win.iloc[0]) and bool(prev_w.iloc[0])
    out["above_at_window_open"] = bool(win.iloc[0])
    out["first_upcrossing_in_window"] = ups.index[0] if len(ups) else None
    if carried:
        before = above[above.index <= win.index[0]]
        below = before[~before]
        out["alert_date"] = before.index[before.index.get_loc(below.index[-1]) + 1] if len(below) else before.index[0]
        out["alert_type"] = "ABOVE_WHEN_WINDOW_OPENED"
    elif len(ups):
        out["alert_date"], out["alert_type"] = ups.index[0], "UP_CROSSING"
    else:
        out["alert_type"] = "NO_ALERT"
    return out


def lead_lag(vols: pd.DataFrame, s: dict) -> pd.DataFrame:
    names = method_names(s)
    ref0, ref1 = s["alert_ref"]
    cal = vols.index
    rows = []
    for series in ("lme", "fx"):
        for ep, start, end in s["episodes"]:
            for pct in s["alert_pcts"]:
                found = {}
                for key, m in names.items():
                    sig = vols[f"sigma_{series}_{m}_frac"]
                    ref = sig[(sig.index >= ref0) & (sig.index <= ref1)].dropna()
                    thr = float(ref.quantile(pct))
                    al = _alert(sig, thr, start, end)
                    date = al["alert_date"]
                    w = sig[(sig.index >= start) & (sig.index <= end)]
                    found[key] = (date, al["first_upcrossing_in_window"])
                    rows.append({
                        "series": series, "episode": ep, "search_start": start, "search_end": end,
                        "percentile": pct, "base_percentile": pct == 0.90, "method": m,
                        "threshold_sigma_frac": thr, **al,
                        "sigma_at_alert_frac": float(sig.get(date, np.nan)) if date is not None else np.nan,
                        "sigma_at_window_open_frac": float(w.iloc[0]),
                        "peak_date_in_window": w.idxmax(), "peak_sigma_in_window_frac": float(w.max()),
                        "reference_period": f"{ref0.date()}..{ref1.date()}",
                    })
                g_alert, g_up = found["garch"]
                for r in rows[-3:]:
                    o_alert, o_up = found[[k for k, m in names.items() if m == r["method"]][0]]
                    r["garch_lead_trading_days"] = (np.nan if g_alert is None or o_alert is None
                                                    else int(cal.get_loc(o_alert) - cal.get_loc(g_alert)))
                    r["garch_lead_on_fresh_upcrossing_days"] = (np.nan if g_up is None or o_up is None
                                                                else int(cal.get_loc(o_up) - cal.get_loc(g_up)))
    out = pd.DataFrame(rows)
    out["alert_date"] = pd.to_datetime(out["alert_date"])
    out["first_upcrossing_in_window"] = pd.to_datetime(out["first_upcrossing_in_window"])
    out["note"] = ("positive garch_lead_trading_days = GARCH alerted that many panel days BEFORE this method "
                   "(alert_date, which is the start of an already-running spell when alert_type says so); "
                   "garch_lead_on_fresh_upcrossing_days compares only up-crossings inside the window; negative = GARCH "
                   "later; thresholds are each method's own percentile over the reference period (no 2022 data); "
                   "search windows are reporting-only")
    return out


# ---------------------------------------------------------------------------------------------------- summary
def summary_table(book: pd.DataFrame, vols: pd.DataFrame, fits: pd.DataFrame, s: dict, ev: dict,
                  betas: dict[str, tuple[float, float]]) -> pd.DataFrame:
    names = method_names(s)
    g, hb, hf = names["garch"], names["hist_base"], names["hist_fast"]
    rows = []

    def add(metric, value, unit_, scope="", note=""):
        if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
            value = round(float(value), 2 if unit_ == "inr" else 8)
        rows.append({"metric": metric, "scope": scope, "value": value, "unit": unit_, "note": note})

    w = book[book["in_window"] & book["position_held"]]
    add("book_days_with_position", len(w), "count", "book_window", f"{w.index.min().date()} .. {w.index.max().date()}")
    for m in names.values():
        c = f"var_{m}_inr"
        add(f"var_mean_{m}", w[c].mean(), "inr", "book_window")
        add(f"var_median_{m}", w[c].median(), "inr", "book_window")
        add(f"var_max_{m}", w[c].max(), "inr", "book_window", f"on {w[c].idxmax().date()}")
        add(f"var_min_{m}", w[c].min(), "inr", "book_window", f"on {w[c].idxmin().date()}")
        add(f"exceptions_{m}", int(w[f"exception_{m}"].sum()), "count", "book_window")
    add("days_garch_var_above_hist_base", int((w[f"var_{g}_inr"] > w[f"var_{hb}_inr"]).sum()), "count", "book_window")
    clean = w[~w["position_date_mcx_exit_or_roll"]]
    add("days_after_mcx_exit_or_roll", int(w["position_date_mcx_exit_or_roll"].sum()), "count", "book_window",
        "exposure on these days still carries the exiting MCX contract (docs/40 §7)")
    for m in names.values():
        add(f"var_mean_{m}_ex_mcx_exit_roll_days", clean[f"var_{m}_inr"].mean(), "inr", "book_window")
    add("ratio_mean_var_garch_to_hist_base", w[f"var_{g}_inr"].mean() / w[f"var_{hb}_inr"].mean(), "x", "book_window")
    add("realised_market_pnl_worst_day", w["pnl_market_inr"].min(), "inr", "book_window",
        f"on {w['pnl_market_inr'].idxmin().date()}")
    add("realised_market_pnl_std", w["pnl_market_inr"].std(), "inr", "book_window",
        "sample std of the backtest P&L; 1.645 x this is a no-model yardstick for the VaR level")
    add("realised_market_pnl_sum", w["pnl_market_inr"].sum(), "inr", "book_window",
        "(a)+(b)+(d)+(e) over the backtest days; NOT the book P&L (which is ₹195.9 m at WINDOW_END, "
        "not sign-robust: −₹105.4 m .. +₹334.3 m across the registered anchor-premium grid)")
    gross = w[f"var_{g}_lme_physical_inr"] + w[f"var_{g}_lme_mcx_inr"]
    add("garch_var_lme_physical_plus_mcx_standalone_mean", gross.mean(), "inr", "book_window",
        "gross LME VaR if the MCX short did not offset the physical (both standalone)")
    add("garch_var_lme_net_mean", w[f"var_{g}_lme_inr"].mean(), "inr", "book_window")
    add("garch_var_fx_physical_forwards_standalone_mean", w[f"var_{g}_fx_physical_forwards_inr"].mean(), "inr",
        "book_window")
    add("garch_var_fx_mcx_leg_standalone_mean", w[f"var_{g}_fx_mcx_inr"].mean(), "inr", "book_window")
    add("garch_var_fx_net_mean", w[f"var_{g}_fx_inr"].mean(), "inr", "book_window",
        "physical+forwards and the MCX leg's FX delta netted on one USD/INR factor (unit beta)")
    add(f"var_freight_{hb}_mean", w[f"var_freight_{hb}_inr"].mean(), "inr", "book_window")
    add(f"var_freight_{hb}_max", w[f"var_freight_{hb}_inr"].max(), "inr", "book_window")
    add("garch_var_incl_spread_memo_mean", w[f"var_{g}_incl_spread_memo_inr"].mean(), "inr", "book_window")
    bd, bw_ = betas["daily"], betas["weekly"]
    add("garch_var_mcx_beta_sensitivity_mean", w[f"var_{g}_mcx_beta_sensitivity_inr"].mean(), "inr", "book_window",
        f"SENSITIVITY, PESSIMISTIC END: MCX leg at the DAILY beta {bd[0]:.3f} + basis residual from R² {bd[1]:.3f} "
        "(mcx_basis_risk.csv); asynchronous MCX/LME closes bias a daily beta down (var_mcx_beta.csv)")
    add("hist_base_var_mcx_beta_sensitivity_mean", w[f"var_{hb}_mcx_beta_sensitivity_inr"].mean(), "inr",
        "book_window", "SENSITIVITY, as above")
    add("garch_var_mcx_beta_weekly_sensitivity_mean", w[f"var_{g}_mcx_beta_weekly_sensitivity_inr"].mean(), "inr",
        "book_window", f"SENSITIVITY, CENTRAL: MCX leg at the WEEKLY beta {bw_[0]:.3f} + basis residual from weekly "
        f"R² {bw_[1]:.3f} (var_mcx_beta.csv)")
    add("hist_base_var_mcx_beta_weekly_sensitivity_mean", w[f"var_{hb}_mcx_beta_weekly_sensitivity_inr"].mean(),
        "inr", "book_window", "SENSITIVITY, as above")
    fn0, fn1 = ev["fortnight_start"], ev["fortnight_end"]
    fn = w[(w.index > fn0) & (w.index <= fn1)]
    for m in names.values():
        add(f"crash_fortnight_var_mean_{m}", fn[f"var_{m}_inr"].mean(), "inr", "E1_CRASH_FORTNIGHT",
            f"return days after {fn0.date()} .. {fn1.date()}")
        add(f"crash_fortnight_exceptions_{m}", int(fn[f"exception_{m}"].sum()), "count", "E1_CRASH_FORTNIGHT")
    add("crash_fortnight_market_pnl_sum", fn["pnl_market_inr"].sum(), "inr", "E1_CRASH_FORTNIGHT")

    day_after = vols.index[vols.index.get_loc(ev["ath"]) + 1]  # the −12.95 % day; forecast made at the ATH close
    r = vols.at[day_after, "lme_ret"]
    tag = f"{day_after:%Y_%m_%d}"
    add(f"lme_return_{tag}", r, "frac", "LME", "the day after the all-time high (DIRECT)")
    for m in names.values():
        sig = vols.at[day_after, f"sigma_lme_{m}_frac"]
        add(f"sigma_lme_forecast_for_{tag}_{m}", sig, "frac", "LME", f"forecast made at the {ev['ath'].date()} ATH close")
        add(f"z_of_{tag}_return_{m}", r / sig, "sigma", "LME")
    checkpoints = [("one_month_before_window", vols.index[vols.index >= pd.Timestamp(WINDOW_START)
                                                         - pd.DateOffset(months=1)][0]),
                   ("window_start", pd.Timestamp(WINDOW_START)), ("day_after_ath", day_after),
                   ("two_days_after_ath", vols.index[vols.index.get_loc(day_after) + 1]),
                   ("crash_fortnight_start", fn0), ("crash_fortnight_end", fn1), ("e1_trough", ev["trough"]),
                   ("window_end", pd.Timestamp(WINDOW_END))]
    for key, date in checkpoints:
        for m in names.values():
            add(f"sigma_lme_{m}_on_{key}", vols.at[date, f"sigma_lme_{m}_frac"], "frac", "LME",
                f"forecast FOR {date.date()} (made at the previous close)")
    feb = pd.Timestamp(WINDOW_START) - pd.DateOffset(months=1)
    feb_lo = vols.loc[feb:pd.Timestamp(WINDOW_START) - pd.Timedelta(days=1)]
    for m in names.values():
        c = f"sigma_lme_{m}_frac"
        lo_date = feb_lo[c].idxmin()
        pre = vols.loc[lo_date:ev["ath"], c]
        add(f"sigma_lme_{m}_rise_into_ath_x", float(vols.at[day_after, c] / feb_lo[c].min()), "x", "LME",
            f"forecast for {day_after.date()} / the method's lowest forecast in the month before WINDOW_START "
            f"({lo_date.date()})")
        add(f"sigma_lme_{m}_max_before_ath", float(pre.max()), "frac", "LME", f"on {pre.idxmax().date()}")
    for series in ("lme", "fx"):
        for m in names.values():
            x = vols.loc[pd.Timestamp(WINDOW_START):pd.Timestamp(WINDOW_END), f"sigma_{series}_{m}_frac"]
            add(f"sigma_{series}_{m}_window_peak", x.max(), "frac", series.upper(), f"on {x.idxmax().date()}")
    for series in ("lme", "fx"):
        f = fits[(fits["series"] == series) & (fits["dist"] == gv.GARCH_DIST_BASE)]
        for lbl, row in (("first_window_fit", f[f["first_target"] >= pd.Timestamp(WINDOW_START)].iloc[0]),
                         ("last_fit", f.iloc[-1])):
            for k in ("omega_pct2", "alpha", "beta", "persistence", "half_life_days", "uncond_vol_daily_frac"):
                add(f"garch_{series}_{lbl}_{k}", row[k], k, series.upper(),
                    f"estimated on {row['n_obs']} returns to {pd.Timestamp(row['sample_end']).date()}")
        add(f"garch_{series}_boundary_fits", int(f["boundary_fit"].sum()), "count", series.upper(),
            f"of {len(f)} weekly fits; alpha+beta >= {gv.BOUNDARY_PERSISTENCE} or alpha ~ 0")
        add(f"garch_{series}_nonconverged_fits", int((~f["converged"]).sum()), "count", series.upper())
        ft = fits[(fits["series"] == series) & (fits["dist"] == gv.GARCH_DIST_SENSITIVITY)]
        row = ft[ft["first_target"] >= pd.Timestamp(WINDOW_START)].iloc[0]
        add(f"garch_t_{series}_first_window_fit_nu", row["nu"], "dof", series.upper())
        add(f"garch_t_{series}_first_window_var_multiplier", gv.t_var_multiplier(row["nu"]), "x", series.upper(),
            f"unit-variance t 95 % quantile vs Normal {gv.Z_VAR:.4f}")
    first_forecast = vols.index[vols["sigma_lme_garch_frac"].notna()][0]
    add("first_garch_forecast_date", str(first_forecast.date()), "date", "LME")
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------------ charts
def _fmt_month(ax):
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b-%y"))


def chart_var_paths(book: pd.DataFrame, panel: pd.DataFrame, s: dict, ev: dict) -> str:
    names = method_names(s)
    g, hb, hf = names["garch"], names["hist_base"], names["hist_fast"]
    w = book[book["in_window"]]
    held = w[w["position_held"]]
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(12, 9.4), sharex=True,
                                  gridspec_kw={"height_ratios": [2.3, 1], "hspace": 0.42})
    pnl = held["pnl_market_inr"] / MILLION
    ax.bar(held.index, pnl, width=0.8, color=np.where(pnl < 0, "#e6a0a0", "#a8c8a0"),
           label="realised market P&L, buckets (a)+(b)+(d)+(e)", zorder=1)
    for m, col, lw, ls, lbl in ((g, PALETTE["garch"], 1.8, "-", "GARCH(1,1)"),
                                (hb, PALETTE["hist"], 1.8, "-", f"historical {s['w_base']}d"),
                                (hf, PALETTE["hist"], 1.0, "--", f"historical {s['w_fast']}d")):
        ax.plot(held.index, -held[f"var_{m}_inr"] / MILLION, color=col, lw=lw, ls=ls, zorder=3,
                label=f"−VaR {lbl}: {int(held[f'exception_{m}'].sum())} exceptions / {len(held)} days")
    for m, mk, col in ((g, "v", PALETTE["garch"]), (hb, "o", PALETTE["hist"])):
        e = held[held[f"exception_{m}"]]
        ax.scatter(e.index, e["pnl_market_inr"] / MILLION, marker=mk, s=60 if mk == "v" else 120,
                   facecolors=col if mk == "v" else "none", edgecolors=col, lw=1.4, zorder=4)
    ax.scatter([], [], marker="v", color=PALETTE["garch"], label="exception vs GARCH VaR")
    ax.scatter([], [], marker="o", facecolors="none", edgecolors=PALETTE["hist"],
               label=f"exception vs {s['w_base']}d VaR")
    floor = -25.0
    ax.set_ylim(floor, max(12.0, float(pnl.max()) * 1.15))
    clipped = held[-held[f"var_{g}_inr"] / MILLION < floor]
    for dte, r in clipped.iterrows():
        # three short lines: one long line ran across the 22-Apr exit-day VaR spike
        ax.annotate(f"GARCH VaR ₹{r[f'var_{g}_inr'] / MILLION:.1f} m\non {dte:%d-%b} (off scale;\n{s['w_base']}d: "
                    f"₹{r[f'var_{hb}_inr'] / MILLION:.1f} m)", xy=(dte, floor), xytext=(30, 52),
                    textcoords="offset points", fontsize=7.5, color=PALETTE["garch"],
                    arrowprops={"arrowstyle": "->", "lw": 0.8, "color": PALETTE["garch"]})
    roll = held[held["position_date_mcx_exit_or_roll"]]
    ax.scatter(roll.index, np.full(len(roll), floor + 0.8), marker="|", s=40, color="#7f7f7f", zorder=2,
               label="day after an MCX exit/roll (VaR carries the exiting contract, docs/40 §7)")
    ax.axhline(0, color="black", lw=0.6)
    ax.set_ylabel("₹ million, one day")
    ax.set_title("Book 95% one-day VaR: GARCH(1,1) vs historical volatility, against realised market P&L", pad=18)
    ax.text(0.5, 1.005, "VaR on the previous close's BOOK exposures to LME, USD/INR and freight (delta-normal, "
            "past-only vols and correlations); exceptions = market P&L below −VaR",
            transform=ax.transAxes, ha="center", va="bottom", fontsize=8, color="#555555")
    ax.tick_params(labelbottom=True)
    ax.legend(loc="upper center", fontsize=7.5, ncol=2, bbox_to_anchor=(0.5, -0.07), frameon=False)

    L = panel.loc[pd.Timestamp(WINDOW_START):pd.Timestamp(WINDOW_END), "lme_cash_usd_t"]
    ax2.plot(L.index, L, color=PALETTE["lme"], lw=1.5)
    ax2.set_ylabel("LME cash, USD/t (DIRECT)")
    ath, low = L.idxmax(), L.idxmin()
    next_day_simple = L.iloc[L.index.get_loc(ath) + 1] / L.max() - 1   # simple return, as a trader quotes it
    ax2.annotate(f"{ath:%d-%b-%Y} all-time high {L.max():,.1f}\nnext day {next_day_simple:.1%}".replace("day -", "day −"),
                 xy=(ath, L.max()),
                 xytext=(18, -22), textcoords="offset points", fontsize=8, arrowprops={"arrowstyle": "->", "lw": 0.8})
    ax2.annotate(f"window low {low:%d-%b} {L.min():,.1f} USD/t\n"
                 f"{f'{L.min() / L.max() - 1:.1%}'.replace('-', '−')} from the high",
                 xy=(low, L.min()), xytext=(12, 48), textcoords="offset points", fontsize=8,
                 arrowprops={"arrowstyle": "->", "lw": 0.8})
    ax2.axvspan(ev["fortnight_start"], ev["fortnight_end"], color=PALETTE["band"], alpha=0.9, zorder=0)
    fret = L.at[ev["fortnight_end"]] / L.at[ev["fortnight_start"]] - 1
    ax2.text(ev["fortnight_start"], L.min() + 30, f" E1 crash fortnight\n {fret:.1%}".replace("-", "−"), fontsize=7.5,
             color="#555555")
    _fmt_month(ax2)
    return save_fig(fig, "p4_var_garch_vs_hist", SOURCE_NOTE)


def chart_vol_forecasts(vols: pd.DataFrame, lead: pd.DataFrame, s: dict, ev: dict) -> str:
    names = method_names(s)
    g, hb, hf = names["garch"], names["hist_base"], names["hist_fast"]
    start, end = pd.Timestamp("2021-09-01"), pd.Timestamp(WINDOW_END)
    v = vols.loc[start:end]
    fig, axes = plt.subplots(2, 1, figsize=(12, 8.6), sharex=True, gridspec_kw={"height_ratios": [1.7, 1]})
    for ax, series, title in ((axes[0], "lme", "LME aluminium cash (DIRECT)"),
                              (axes[1], "fx", "USD/INR (PROXY: ECB cross)")):
        ax.bar(v.index, v[f"{series}_ret"].abs() * 100, width=1.0, color="#d9d9d9", label="|daily log return|",
               zorder=1)
        for m, col, ls, lw, lbl in ((g, PALETTE["garch"], "-", 1.8, "GARCH(1,1) conditional vol"),
                                    (hb, PALETTE["hist"], "-", 1.8, f"rolling {s['w_base']}d vol"),
                                    (hf, PALETTE["hist"], "--", 1.1, f"rolling {s['w_fast']}d vol")):
            ax.plot(v.index, v[f"sigma_{series}_{m}_frac"] * 100, color=col, ls=ls, lw=lw, label=lbl, zorder=3)
            base = lead[(lead["series"] == series) & lead["base_percentile"] & (lead["method"] == m)]
            thr = float(base["threshold_sigma_frac"].iloc[0]) * 100
            ax.axhline(thr, color=col, ls=":", lw=0.9, alpha=0.9)
            if series != "lme":
                continue
            for _, r in base.iterrows():
                for col_name, filled in (("alert_date", True), ("first_upcrossing_in_window", False)):
                    dte = r[col_name]
                    if pd.isna(dte) or pd.Timestamp(dte) < start:
                        continue
                    dte = pd.Timestamp(dte)
                    if not filled and dte == pd.Timestamp(r["alert_date"]):
                        continue
                    y = v.at[dte, f"sigma_{series}_{m}_frac"] * 100
                    ax.scatter([dte], [y], marker="D" if m == g else "o", s=46, zorder=5, lw=1.3,
                               facecolors=col if filled else "white", edgecolors=col)
                    if m in (g, hb):
                        txt = f"{dte:%d-%b}" + ("" if filled else " (re-alert)")
                        ax.annotate(txt, xy=(dte, y), xytext=(5, (9 if filled else 26) if m == g else -15),
                                    textcoords="offset points",
                                    fontsize=7.5, color=col, fontweight="bold")
        ax.set_ylim(0, 6.0 if series == "lme" else 1.0)
        ax.set_ylabel("% per day")
        ax.set_title(f"{title}: one-day-ahead volatility forecasts", loc="left")
        ax.axvline(ev["ath"], color="black", lw=0.7, alpha=0.6)
        ax.axvspan(ev["fortnight_start"], ev["fortnight_end"], color=PALETTE["band"], alpha=0.8, zorder=0)
    axes[0].annotate(f"{ev['ath']:%d-%b} ATH", xy=(ev["ath"], 5.75), xytext=(4, 0), textcoords="offset points",
                     fontsize=7.5)
    big = v["lme_ret"].abs().idxmax()
    fig.text(0.5, 0.035, f"Dotted lines: each method's own 90th percentile of its 2019–2021 forecasts (no 2022 data). "
             f"Markers: first alert per episode (hollow = fresh re-alert after a dip below). |r| on {big:%d-%b-%Y} = "
             f"{abs(v.at[big, 'lme_ret']):.2%} (bar clipped). Shaded: E1 crash fortnight.",
             ha="center", fontsize=7, color="#555555")
    h60 = lead[(lead["series"] == "lme") & lead["base_percentile"] & (lead["method"] == hf)
               & (lead["alert_type"] == "ABOVE_WHEN_WINDOW_OPENED")]
    if len(h60):
        axes[0].text(0.01, 0.97, f"{s['w_fast']}d: above its threshold since "
                     f"{pd.Timestamp(h60['alert_date'].iloc[0]):%d-%b-%Y} (no fresh alert)",
                     transform=axes[0].transAxes, fontsize=7, va="top", color=PALETTE["hist"])
    axes[0].legend(loc="upper left", fontsize=8, bbox_to_anchor=(0.0, 0.92))
    _fmt_month(axes[1])
    return save_fig(fig, "p4_var_vol_forecasts", SOURCE_NOTE)


def chart_unit_backtest(unit: pd.DataFrame, s: dict) -> str:
    names = method_names(s)
    fig, axes = plt.subplots(2, 1, figsize=(12, 7.6), sharex=True)
    styles = {names["garch"]: (PALETTE["garch"], "-", "GARCH(1,1)"),
              names["hist_base"]: (PALETTE["hist"], "-", f"historical {s['w_base']}d"),
              names["hist_fast"]: (PALETTE["hist"], "--", f"historical {s['w_fast']}d"),
              "garch_t": (PALETTE["garch"], ":", "GARCH-t (sensitivity)")}
    n = np.arange(1, len(unit) + 1)
    for ax, series, title, loc in ((axes[0], "lme", f"Long {s['unit_lme_mt']:,.0f} MT LME aluminium", "upper left"),
                                   (axes[1], "fx", f"Long USD {s['unit_fx_usd']:,.0f} against INR", "lower left")):
        for m, (col, ls, lbl) in styles.items():
            h = unit[f"unit_{series}_exception_{m}"].astype(int).cumsum()
            ax.plot(unit.index, h - n * P_EXCEPTION, color=col, ls=ls, lw=1.4,
                    label=f"{lbl}: {int(h.iloc[-1])} exceptions")
        ax.axhline(0, color="black", lw=0.6)
        ax.set_title(f"{title}: cumulative 95% VaR exceptions − expected, n = {len(unit):,} days", loc="left",
                     fontsize=11)
        ax.set_ylabel("exceptions − expected")
        # headroom on the legend's side so the two-column legend sits clear of the lines
        lo, hi = ax.get_ylim()
        pad = 0.28 * (hi - lo)
        ax.set_ylim(lo, hi + pad) if loc.startswith("upper") else ax.set_ylim(lo - pad, hi)
        ax.legend(loc=loc, fontsize=8, ncol=2, title=f"expected {len(unit) * P_EXCEPTION:.1f} exceptions",
                  title_fontsize=8, alignment="left")
    axes[1].xaxis.set_major_locator(mdates.YearLocator())
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.text(0.5, 0.955, "Rising line = exceptions arriving faster than 5% (VaR too tight); falling = VaR too loose. "
             "Constant hypothetical exposures, not the book.", ha="center", fontsize=8, color="#555555")
    return save_fig(fig, "p4_var_unit_backtest", "LME DIRECT; USD/INR PROXY (ECB cross); constant hypothetical "
                                                 "exposures, not trades")


# --------------------------------------------------------------------------------------------------------- main
def read_event_dates() -> dict[str, pd.Timestamp]:
    """Reporting-only P3 event dates (CONTRACTS §7a.3): the ATH, the E1 trough and the E1 crash fortnight."""
    w = pd.read_csv(TABLES_DIR / "adverse_event_windows.csv", usecols=["event", "start", "end"]).set_index("event")
    return {"ath": pd.Timestamp(w.at["E1_LME_CRASH", "start"]), "trough": pd.Timestamp(w.at["E1_LME_CRASH", "end"]),
            "fortnight_start": pd.Timestamp(w.at["E1_CRASH_FORTNIGHT", "start"]),
            "fortnight_end": pd.Timestamp(w.at["E1_CRASH_FORTNIGHT", "end"])}


def read_mcx_beta() -> tuple[float, float]:
    b = pd.read_csv(TABLES_DIR / "mcx_basis_risk.csv", usecols=["metric", "scope", "value"])
    b = b[b["scope"] == "BOOK"].set_index("metric")["value"]
    return float(b["unit_beta_beta"]), float(b["unit_beta_beta_r2"])


def _ols(y: np.ndarray, X: np.ndarray, g: np.ndarray) -> tuple[float, float, float, int]:
    """OLS with an intercept column in X: returns g'b, its standard error, R² and n."""
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ b
    n, k = X.shape
    cov = float(resid @ resid) / (n - k) * np.linalg.inv(X.T @ X)
    r2 = 1.0 - float(resid @ resid) / float(((y - y.mean()) ** 2).sum())
    return float(g @ b), float(np.sqrt(g @ cov @ g)), r2, n


def mcx_beta_samplings(start=WINDOW_START, end=WINDOW_END) -> dict[str, dict]:
    """Slope of third-party-mirror MCX near-month price changes on duty-paid-parity changes (₹/kg), three samplings.

    The engine's hedge assumes this slope is 1. `daily` is exactly P3's test (`desk.mtm.sensitivity.unit_beta_test`,
    published in mcx_basis_risk.csv). A daily slope is biased toward zero here because the two sides do not close at
    the same time: parity is struck on the LME official price (London midday) while MCX's evening close lands hours
    later, so news after the LME fix reaches MCX on day t but parity only on t+1 (errors-in-timing, the
    Scholes–Williams/Dimson problem). Two standard corrections:

    * `weekly` — W-FRI last-close changes (CONTRACTS §3), where the misaligned half-day is a small part of each change;
    * `lead_lag` — a Dimson (1979) regression of MCX on parity changes at t−1, t and t+1 over the same daily sample;
      the summed slope is the close-time-matched beta, its standard error from the coefficient covariance.

    All three are retrospective PROXY statistics on one six-month sample of an unverified mirror (docs/10 §11).
    """
    from desk.mtm.history import MarketHistory      # the mirror view P3 and Phase 4.2 use; imported only here

    H = MarketHistory(mcx_source="mirror")
    days = list(H.cal.days)
    theo = pd.Series([H.mcx_theo_inr_kg(d) for d in days], index=pd.to_datetime(days), dtype=float)
    obs = pd.Series([H.mcx_observed_inr_kg(d) for d in days], index=pd.to_datetime(days), dtype=float)
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    win = (theo.index >= lo) & (theo.index <= hi)
    out: dict[str, dict] = {}

    x, y = theo[win].diff().iloc[1:], obs[win].diff().iloc[1:]
    X = np.column_stack([np.ones(len(x)), x.to_numpy()])
    b, se, r2, n = _ols(y.to_numpy(), X, np.array([0.0, 1.0]))
    out["daily"] = {"beta": b, "se": se, "r2": r2, "n": n, "unit": "daily changes",
                    "note": "P3's test (mcx_basis_risk.csv): same-day changes; biased toward zero by asynchronous "
                            "closes, so the PESSIMISTIC end"}

    wk = pd.DataFrame({"x": theo[win], "y": obs[win]}).resample(WEEK_FREQ).last().diff().dropna()
    X = np.column_stack([np.ones(len(wk)), wk["x"].to_numpy()])
    b, se, r2, n = _ols(wk["y"].to_numpy(), X, np.array([0.0, 1.0]))
    out["weekly"] = {"beta": b, "se": se, "r2": r2, "n": n, "unit": "W-FRI weekly changes",
                     "note": "week-end closes: the timing mismatch is a small share of each change; the CENTRAL read"}

    dx = theo.diff()
    ll = pd.DataFrame({"y": obs.diff(), "x_lag": dx.shift(1), "x": dx, "x_lead": dx.shift(-1)})
    ll = ll.loc[x.index].dropna()
    X = np.column_stack([np.ones(len(ll)), ll[["x_lag", "x", "x_lead"]].to_numpy()])
    b, se, r2, n = _ols(ll["y"].to_numpy(), X, np.array([0.0, 1.0, 1.0, 1.0]))
    out["lead_lag"] = {"beta": b, "se": se, "r2": r2, "n": n, "unit": "daily changes, parity at t-1, t, t+1",
                       "note": "Dimson sum of slopes: the close-time-matched beta; R² is the three-regressor fit"}
    return out


def beta_table(samplings: dict[str, dict], book: pd.DataFrame, s: dict) -> pd.DataFrame:
    """var_mcx_beta.csv: each beta reading next to the book VaR it implies (window position days, means)."""
    names = method_names(s)
    g, hb = names["garch"], names["hist_base"]
    w = book[book["in_window"] & book["position_held"]]
    rows = [{"sampling": "engine_unit_beta", "beta": 1.0, "beta_se": np.nan, "t_vs_one": np.nan, "r2": np.nan,
             "n_obs": np.nan, "obs_unit": "by construction", "unhedged_frac_of_parity_move": 0.0,
             f"var_mean_{g}_inr": w[f"var_{g}_inr"].mean(), f"var_mean_{hb}_inr": w[f"var_{hb}_inr"].mean(),
             "reading": "OPTIMISTIC END: the base VaR; the proxy MCX has unit beta and zero basis by construction",
             "flag": "PROXY"}]
    for k, r in samplings.items():
        suffix = BETA_VAR_SAMPLINGS.get(k)
        rows.append({"sampling": k, "beta": r["beta"], "beta_se": r["se"], "t_vs_one": (r["beta"] - 1.0) / r["se"],
                     "r2": r["r2"], "n_obs": float(r["n"]), "obs_unit": r["unit"],
                     "unhedged_frac_of_parity_move": abs(1.0 - r["beta"]),
                     f"var_mean_{g}_inr": w[f"var_{g}_mcx_beta{suffix}_sensitivity_inr"].mean() if suffix is not None else np.nan,
                     f"var_mean_{hb}_inr": w[f"var_{hb}_mcx_beta{suffix}_sensitivity_inr"].mean() if suffix is not None else np.nan,
                     "reading": r["note"], "flag": "PROXY"})
    out = pd.DataFrame(rows)
    out["label"] = f"{SIM_LABEL}. SENSITIVITY — not base VaR; third-party MCX mirror (PROXY, provenance unverified)"
    return out


def run() -> dict:
    ensure_dirs()
    s = settings()
    panel = load_panel()
    chg = factor_changes(panel)
    vols, fits = vol_forecasts(chg, s)
    ev = read_event_dates()
    mcx_beta, mcx_r2 = read_mcx_beta()
    samplings = mcx_beta_samplings()
    if abs(samplings["daily"]["beta"] - mcx_beta) > 1e-6 or abs(samplings["daily"]["r2"] - mcx_r2) > 1e-6:
        raise ValueError(f"daily MCX beta {samplings['daily']['beta']:.6f} does not reproduce mcx_basis_risk.csv "
                         f"({mcx_beta:.6f}): the mirror or the panel changed since Phase 3 ran")
    betas = {k: (samplings[k]["beta"], samplings[k]["r2"]) for k in BETA_VAR_SAMPLINGS}
    book = book_var(panel, vols, s, betas)
    unit = unit_backtest(panel, vols, s)
    kup, exc = kupiec_table(book, unit, vols, s)
    calib = calibration_table(book, unit, s)
    lead = lead_lag(vols, s)
    summ = summary_table(book, vols, fits, s, ev, betas)
    beta_tab = beta_table(samplings, book, s)
    return {"settings": s, "events": ev, "panel": panel, "vols": vols, "fits": fits, "book": book, "unit": unit, "kupiec": kup,
            "exceptions": exc, "lead": lead, "summary": summ, "calibration": calib, "mcx_beta": beta_tab}


def main() -> None:
    out = run()
    s = out["settings"]
    write(out["book"].reset_index(), "var_daily")
    write(out["vols"].reset_index(), "var_vol_forecasts")
    write(out["fits"], "var_garch_params")
    write(out["unit"].reset_index(), "var_unit_backtest_daily")
    write(out["kupiec"], "kupiec")
    write(out["exceptions"], "var_backtest_exceptions")
    write(out["lead"], "var_lead_lag")
    write(out["summary"], "var_summary")
    write(out["calibration"], "var_calibration")
    write(out["mcx_beta"], "var_mcx_beta")
    chart_var_paths(out["book"], out["panel"], s, out["events"])
    chart_vol_forecasts(out["vols"], out["lead"], s, out["events"])
    chart_unit_backtest(out["unit"], s)
    k = out["kupiec"]
    print(k[["sample", "method", "n", "exceptions", "expected", "kupiec_pvalue", "verdict",
             "christoffersen_pvalue_ind"]].to_string(index=False))


if __name__ == "__main__":
    main()
