"""Phase 4.2 ★ stage — Monte Carlo stress: 10,000 joint paths, full revaluation of the book, five stresses overlaid.

    DESK_OFFLINE=1 .venv/bin/python -c "import desk.risk.run_mc as m; m.main()"

Reads only files (CONTRACTS §1.7): `data/processed/market_daily.csv`; the third-party MCX mirror through
`MarketHistory(mcx_source="mirror")` (basis sensitivity only); the trade book through `desk.mtm.run.load()`; and from
`outputs/tables/`: `book_exposures_daily.csv` (BOOK scope), `buyer_credit_exposure_by_trade_daily.csv`,
`mcx_variation_margin.csv` (exit/roll days), `attribution_daily.csv` (BOOK rows) and `attribution_leg_daily.csv`
(the FUNDING leg) for the reconciliation, and `adverse_event_3_freight_stress_hypothetical.csv` as a control.

What it builds (docs/41_monte_carlo.md is the method page):

1. The joint daily-unit covariance of LME cash, USD/INR and freight over the spec's estimation window (plus a
   point-in-time span per snapshot and a four-factor version with the mirror's MCX basis), scaled to the horizon.
2. Three snapshot dates chosen by the rules registered in `risk.yaml` (`mc_snapshot_rules`).
3. For each snapshot, 10,000 paths per variant revalued through `desk.mtm.valuation.revalue_book`; the base is a
   zero-mean multivariate normal on the window covariance over `mc_horizon_bdays`.
4. The five Table 6 stresses revalued through the same API, placed in the base distribution by percentile.
"""

from __future__ import annotations

import datetime as dt
import math
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from desk import HORIZON_END, RNG_SEED, SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.mtm import history
from desk.mtm import run as mtm_run
from desk.mtm import valuation as val
from desk.paths import PROCESSED_DIR, TABLES_DIR, ensure_dirs
from desk.reporting.style import PALETTE, save_fig
from desk.risk import monte_carlo as mc

MILLION = 1e6
BASE_VARIANT = "normal_window"
INPUT_FLAGS = ("LME DIRECT (LME official via Westmetall); USD/INR PROXY (ECB cross); freight ASSUMPTION "
               "(hindsight-calibrated reconstruction); MCX PROXY (duty-parity, unit beta); book SIM")
HYPOTHETICAL = "HYPOTHETICAL STRESS — not a 2022 event"
SOURCE_NOTE = ("LME DIRECT; USD/INR PROXY (ECB cross); freight ASSUMPTION reconstruction; MCX PROXY; "
               "book, exposures and P&L SIM")
EXPOSURE_COLS = ["date", "scope", "cum_pnl_inr", "lme_delta_inr_per_usd_t", "lme_delta_mt", "lme_delta_physical_mt",
                 "lme_delta_mcx_mt", "mcx_lots_open", "mcx_basis_delta_inr_per_inr_kg", "fx_delta_usd",
                 "fx_delta_physical_usd", "fx_delta_forwards_usd", "fx_delta_mcx_usd",
                 "freight_delta_inr_per_usd_t_jea_nsa", "freight_delta_inr_per_usd_t_usec_mun", "unsold_mt",
                 "buyer_receivable_inr", "buyer_presettlement_inr", "cash_balance_inr", "mcx_im_inr"]

VARIANTS = [
    # id, role, description
    ("normal_window", "BASE",
     "zero-mean multivariate normal; covariance of the estimation window (spec); 10-business-day horizon"),
    ("student_t_window", "SENSITIVITY",
     "multivariate Student-t (mc_student_t_dof) with the same window covariance — uncertain variance over the horizon"),
    ("bootstrap_window", "SENSITIVITY",
     "iid bootstrap of whole demeaned window days, 10 summed per path (freight as its carried daily series)"),
    ("normal_pit", "SENSITIVITY",
     "zero-mean normal on the mc_pit_lookback_days changes ending at the snapshot close (no hindsight)"),
    ("normal_window_mcx_basis", "SENSITIVITY",
     "base plus a 4th factor: MCX basis (₹/kg) from the third-party mirror (PROXY), MCX priced at the shocked basis"),
    ("normal_window_to_settlement", "MEMO",
     "base covariance scaled to the business days until the last open ticket closes — a STATIC position held to "
     "settlement, which the desk never did (hedges were added and prices fixed); not a risk number"),
]

SCENARIO_COLORS = {"market": PALETTE["lme"], "credit": PALETTE["loss"], "policy": PALETTE["freight"]}
# Extra panel days of levels loaded before the earliest point-in-time span, so its first complete W-FRI week has a
# prior weekly sample to difference against.
LOOKBACK_BUFFER_DAYS = 15


# --------------------------------------------------------------------------------------------------- params
def settings() -> dict:
    """Every judgement parameter from config/params/*.yaml (Phase 4.2 section of risk.yaml plus the shared stresses)."""
    v = config.value
    return {
        "horizon": int(v("mc_horizon_bdays")),
        "pit_days": int(v("mc_pit_lookback_days")),
        "nu": float(v("mc_student_t_dof")),
        "snapshot_rules": [(str(a), str(b)) for a, b in v("mc_snapshot_rules")],
        "lme_move": float(v("mc_stress_lme_move_frac")),
        "fx_move": float(v("mc_stress_usdinr_move_frac")),
        "freight_move": float(v("freight_stress_shock_frac")),
        "buyer": str(v("mc_buyer_default_buyer_id")),
        "recovery": float(v("mc_buyer_default_recovery_frac")),
        "recovery_grid": [float(x) for x in v("mc_buyer_default_recovery_sensitivity_frac")],
        "resale_discount": float(v("mc_buyer_default_resale_discount_frac")),
        "qco_uncleared_only": bool(v("mc_qco_uncleared_only")),
        "qco_delay_days": int(v("qco_stress_delay_days")),
        "qco_rejection": float(v("qco_stress_rejection_frac")),
        "qco_rejected_loss": float(v("qco_stress_rejected_loss_frac")),
    }


# ------------------------------------------------------------------------------------------------------ I/O
def write(df: pd.DataFrame, name: str) -> None:
    """Deterministic CSV (CONTRACTS §1.5): fixed rounding by unit suffix, ISO dates, LF endings."""
    out = df.copy()
    for c in out.columns:
        if not pd.api.types.is_float_dtype(out[c]):
            continue
        if c.endswith("_inr") or c.endswith("_usd"):
            out[c] = out[c].round(2)
        elif c.endswith("_mt") or c.endswith("_usd_t") or c.endswith("_inr_t"):
            out[c] = out[c].round(4)
        else:
            out[c] = out[c].round(12)
    out.to_csv(TABLES_DIR / f"{name}.csv", index=False, lineterminator="\n", date_format="%Y-%m-%d")


def load_panel() -> pd.DataFrame:
    cols = ["date", "lme_cash_usd_t", "usdinr", "freight_usec_mun_usd_t", "freight_jea_nsa_usd_t"]
    return pd.read_csv(PROCESSED_DIR / "market_daily.csv", usecols=cols, parse_dates=["date"]).set_index("date")


def load_book_exposures() -> pd.DataFrame:
    ex = pd.read_csv(TABLES_DIR / "book_exposures_daily.csv", usecols=EXPOSURE_COLS, parse_dates=["date"])
    return ex[ex["scope"].str.lower() == "book"].drop(columns="scope").set_index("date")


def mcx_exit_or_roll_dates() -> set[pd.Timestamp]:
    vm = pd.read_csv(TABLES_DIR / "mcx_variation_margin.csv", usecols=["date", "action"], parse_dates=["date"])
    return set(vm.loc[vm["action"].isin(["exit", "roll_out"]), "date"])


def buyer_contracted(buyer_id: str) -> pd.Series:
    b = pd.read_csv(TABLES_DIR / "buyer_credit_exposure_by_trade_daily.csv",
                    usecols=["date", "buyer_id", "contracted_inr"], parse_dates=["date"])
    return b[b["buyer_id"] == buyer_id].groupby("date")["contracted_inr"].sum()


def funding_to_date(t: dt.date) -> float:
    leg = pd.read_csv(TABLES_DIR / "attribution_leg_daily.csv", usecols=["date", "leg_id", "daily_pnl_inr"],
                      parse_dates=["date"])
    f = leg[(leg["leg_id"] == "FUNDING") & (leg["date"] <= pd.Timestamp(t))]
    return float(f["daily_pnl_inr"].sum())


def book_cum_pnl(t: dt.date) -> float:
    at = pd.read_csv(TABLES_DIR / "attribution_daily.csv", usecols=["date", "trade_id", "cum_pnl_inr"],
                     parse_dates=["date"])
    row = at[(at["trade_id"] == "BOOK") & (at["date"] == pd.Timestamp(t))]  # BOOK rows only: never sum with trades
    return float(row["cum_pnl_inr"].iloc[0]) if len(row) else float("nan")


# ------------------------------------------------------------------------------------------------ snapshots
def _clean_day(d: pd.Timestamp, days: pd.DatetimeIndex, blocked: set) -> pd.Timestamp:
    """`d`, or the next panel day that is not an MCX exit / roll-out day."""
    later = days[days >= d]
    for x in later:
        if x not in blocked:
            return x
    raise ValueError(f"no clean panel day on or after {d.date()}")


def select_snapshots(panel: pd.DataFrame, exposures: pd.DataFrame, s: dict) -> pd.DataFrame:
    """Apply the registered rules. They read prices, exposures and credit tables only — never P&L."""
    days = panel.index[(panel.index >= pd.Timestamp(WINDOW_START)) & (panel.index <= pd.Timestamp(WINDOW_END))]
    blocked = mcx_exit_or_roll_dates()
    rules = dict(s["snapshot_rules"])
    rows = []
    cash = panel.loc[days, "lme_cash_usd_t"]
    ath = cash.idxmax()
    raw = days[days.get_loc(ath) + 1]
    rows.append(("ATH_PLUS_1", raw, f"LME cash all-time high {cash.max():,.1f} USD/t on {ath.date()}"))
    ex = exposures.reindex(days)["lme_delta_physical_mt"]
    raw = ex.idxmax()
    rows.append(("PEAK_GROSS_LME", raw, f"BOOK lme_delta_physical_mt {ex.max():,.1f} MT"))
    bc = buyer_contracted(s["buyer"]).reindex(days).fillna(0.0)
    raw = bc[bc >= bc.max() - 0.5].index[0]
    rows.append(("PEAK_BUYER_CONTRACTED", raw, f"{s['buyer']} contracted exposure ₹{bc.max():,.0f}"))
    out = []
    for sid, d_raw, why in rows:
        d = _clean_day(d_raw, days, blocked)
        out.append({"snapshot_id": sid, "snapshot_date": d, "rule_date": d_raw, "moved_off_exit_roll_day": d != d_raw,
                    "rule": rules[sid], "rule_evidence": why})
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------------------------- factor data
def factor_levels(panel: pd.DataFrame, H_mirror: history.MarketHistory, start: pd.Timestamp) -> pd.DataFrame:
    """Daily levels from `start` to WINDOW_END, with the mirror's near-month basis (observed − duty-parity theo)."""
    lv = panel.loc[(panel.index >= start) & (panel.index <= pd.Timestamp(WINDOW_END)),
                   ["lme_cash_usd_t", "usdinr", "freight_usec_mun_usd_t"]].copy()
    lv["mcx_basis_inr_kg"] = [H_mirror.mcx_observed_inr_kg(d.date()) - H_mirror.mcx_theo_inr_kg(d.date())
                              for d in lv.index]
    if lv[["lme_cash_usd_t", "usdinr", "freight_usec_mun_usd_t"]].isna().any().any():
        raise ValueError("missing LME, USD/INR or freight level inside the Monte Carlo estimation spans")
    return lv


def covariance_tables(spans: dict, daily_chg: pd.DataFrame, weekly_chg: pd.DataFrame, horizon: int) -> tuple[dict, pd.DataFrame]:
    """Covariance per estimation span: the 3-factor base and (window only) the 4-factor basis variant."""
    covs = {}
    rows = []
    for key, (span, factors) in spans.items():
        cov, pairs = mc.assemble_covariance(span.daily(daily_chg), span.weekly(weekly_chg), factors)
        covs[key] = cov
        pairs.insert(0, "covariance_id", key)
        pairs.insert(1, "span_start", span.start)
        pairs.insert(2, "span_end", span.end)
        pairs["cov_horizon"] = pairs["cov_daily"] * horizon
        sd = np.sqrt(np.diag(cov.to_numpy()))
        pairs["sd_i_daily"] = [sd[factors.index(a)] for a in pairs.factor_i]
        pairs["sd_j_daily"] = [sd[factors.index(b)] for b in pairs.factor_j]
        pairs["sd_i_horizon"] = pairs["sd_i_daily"] * math.sqrt(horizon)
        pairs["unit_i"] = [mc.FACTOR_UNIT[a] for a in pairs.factor_i]
        pairs["unit_j"] = [mc.FACTOR_UNIT[b] for b in pairs.factor_j]
        rows.append(pairs)
    return covs, pd.concat(rows, ignore_index=True)


def factor_stats_table(window: mc.Span, daily_chg: pd.DataFrame, weekly_chg: pd.DataFrame, horizon: int) -> pd.DataFrame:
    rows = []
    for freq, frame in (("daily", window.daily(daily_chg)), ("weekly", window.weekly(weekly_chg))):
        for f in ("lme", "fx", "freight", "mcx_basis"):
            st = mc.factor_stats(frame[f], horizon=horizon if freq == "daily" else None)
            used = ((freq == "daily" and f in mc.DAILY_FACTORS) or (freq == "weekly" and f in mc.WEEKLY_FACTORS))
            role = "variance source" if used else "memo"
            if freq == "daily" and f == "freight":
                role = "bootstrap input (carried weekly series)"
            rows.append({"factor": f, "frequency": freq, "role": role, "unit": mc.FACTOR_UNIT[f],
                         "span_start": window.start, "span_end": window.end, **st,
                         "flag": {"lme": "DIRECT", "fx": "PROXY", "freight": "ASSUMPTION", "mcx_basis": "PROXY"}[f]})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------- horizons
def to_settlement_bdays(book, H, cache, t: dt.date) -> tuple[int, dt.date]:
    """Panel days after t until the last ticket on the book closes (capped at HORIZON_END, CONTRACTS §7.1)."""
    closes = [cache.get(tk, t, t).close_date for tk in mc.tickets_on_book(book, t)]
    last = min(max(closes), HORIZON_END)
    return len(H.cal.between(t, last)) - 1, last


def expost_memo(panel: pd.DataFrame, d: pd.Timestamp, horizon: int, cov_window: pd.DataFrame) -> dict:
    """AFTER-THE-FACT memo: the factor moves that actually followed the snapshot over the horizon, in sigmas of the
    base covariance. Reporting only — nothing in the simulation reads it, and the book changed over those days."""
    i = panel.index.get_loc(d)
    end = panel.index[i + horizon]
    lv0, lv1 = panel.iloc[i], panel.loc[end]
    sd = np.sqrt(np.diag(cov_window.to_numpy()) * horizon)
    moves = {"lme": math.log(lv1["lme_cash_usd_t"] / lv0["lme_cash_usd_t"]),
             "fx": math.log(lv1["usdinr"] / lv0["usdinr"]),
             "freight": math.log(lv1["freight_usec_mun_usd_t"] / lv0["freight_usec_mun_usd_t"])}
    out = {"expost_memo_horizon_end": end}
    for (f, m), sigma in zip(moves.items(), sd):
        out[f"expost_memo_{mc.SHOCK_KEY[f]}"] = m
        out[f"expost_memo_{f}_sigma_horizon"] = m / sigma if sigma > 0 else float("nan")
    return out


# --------------------------------------------------------------------------------------------------- the run
def run() -> dict:
    t_start = time.time()
    s = settings()
    panel = load_panel()
    exposures = load_book_exposures()
    H = history.MarketHistory()
    H_mirror = history.MarketHistory(mcx_source="mirror")
    book = mtm_run.load()
    cache = val.ScheduleCache(book, H)
    snaps = select_snapshots(panel, exposures, s)

    first_snap = snaps["snapshot_date"].min()
    start = panel.index[panel.index.get_loc(first_snap) - s["pit_days"] - LOOKBACK_BUFFER_DAYS]
    levels = factor_levels(panel, H_mirror, start)
    daily_chg = mc.factor_changes(levels)
    weekly_chg = mc.factor_changes(mc.weekly_samples(levels))
    window = mc.Span("window", pd.Timestamp(WINDOW_START), pd.Timestamp(WINDOW_END))
    spans = {"window": (window, list(mc.BASE_FACTORS)),
             "window_mcx_basis": (window, list(mc.BASE_FACTORS) + [mc.BASIS_FACTOR])}
    for r in snaps.itertuples(index=False):
        sp = mc.trailing_span(f"pit_{r.snapshot_id}", daily_chg.index, r.snapshot_date, s["pit_days"])
        spans[f"pit_{r.snapshot_id}"] = (sp, list(mc.BASE_FACTORS))
    covs, cov_table = covariance_tables(spans, daily_chg, weekly_chg, s["horizon"])
    fstats = factor_stats_table(window, daily_chg, weekly_chg, s["horizon"])
    boot_daily = window.daily(daily_chg)[list(mc.BASE_FACTORS)].to_numpy()

    draws = mc.standard_draws(mc.N_PATHS, 4, s["horizon"], s["nu"], seed=RNG_SEED)
    unhedged = val.ScheduleCache(book, H, drop_instruments=frozenset({"mcx"}))

    summary, dist, contrib, scen_rows, snap_rows, delta_rows, detail_rows = [], [], [], [], [], [], []
    base_pnl = {}
    for r in snaps.itertuples(index=False):
        t = r.snapshot_date.date()
        on_book = mc.tickets_on_book(book, t)
        base_by_trade = val.revalue_book(book, H, t, cache=cache)[:, 0]
        h_settle, last_close = to_settlement_bdays(book, H, cache, t)
        M = H.state_at(t)
        e = exposures.loc[r.snapshot_date]
        funding = funding_to_date(t)
        cum = book_cum_pnl(t)
        same_day = mc.same_day_flow_deltas(book, H, t, cache)
        snap_rows.append({
            "snapshot_id": r.snapshot_id, "snapshot_date": r.snapshot_date, "rule": r.rule,
            "rule_evidence": r.rule_evidence, "rule_date": r.rule_date,
            "moved_off_exit_roll_day": r.moved_off_exit_roll_day,
            "trades_on_book": " ".join(tk.trade_id for tk in on_book),
            "lme_cash_usd_t": M.lme_cash_usd_t, "usdinr": M.usdinr,
            "freight_usec_mun_usd_t": M.freight_usd_t["USEC_MUN"], "freight_jea_nsa_usd_t": M.freight_usd_t["JEA_NSA"],
            **{c: float(e[c]) for c in EXPOSURE_COLS if c not in ("date", "scope")},
            "base_value_excl_funding_inr": float(base_by_trade.sum()), "funding_to_date_inr": funding,
            "phase3_cum_pnl_inr": cum,
            "reconciliation_diff_inr": float(base_by_trade.sum()) + funding - cum,
            "lme_delta_all_flows_inr_per_usd_t": same_day["lme_delta_all_flows"],
            "lme_delta_ending_same_day_flows_inr_per_usd_t": same_day["lme_delta_ending_same_day_flows"],
            "fx_delta_all_flows_usd": same_day["fx_delta_all_flows"],
            "fx_delta_ending_same_day_flows_usd": same_day["fx_delta_ending_same_day_flows"],
            "to_settlement_bdays": h_settle, "to_settlement_last_close": last_close,
            **expost_memo(panel, r.snapshot_date, s["horizon"], covs["window"]),
            "label": SIM_LABEL,
        })

        for vid, role, desc in VARIANTS:
            t0 = time.time()
            factors = list(mc.BASE_FACTORS)
            hold = True
            horizon = s["horizon"]
            if vid == "normal_window":
                x = mc.simulate_normal(draws, covs["window"].to_numpy() * horizon)
                cov_id = "window"
            elif vid == "student_t_window":
                x = mc.simulate_student_t(draws, covs["window"].to_numpy() * horizon)
                cov_id = "window"
            elif vid == "bootstrap_window":
                x = mc.simulate_bootstrap(draws, boot_daily)
                cov_id = "window (resampled days)"
            elif vid == "normal_pit":
                cov_id = f"pit_{r.snapshot_id}"
                x = mc.simulate_normal(draws, covs[cov_id].to_numpy() * horizon)
            elif vid == "normal_window_mcx_basis":
                factors = factors + [mc.BASIS_FACTOR]
                cov_id = "window_mcx_basis"
                x = mc.simulate_normal(draws, covs[cov_id].to_numpy() * horizon)
                hold = False
            else:
                horizon = h_settle
                cov_id = "window"
                x = mc.simulate_normal(draws, covs["window"].to_numpy() * horizon)
            pnl_tr = mc.revalue_paths(book, H, t, mc.shocks_from_matrix(x, factors), cache=cache, mcx_hold_basis=hold)
            pnl = pnl_tr.sum(axis=0)
            st = mc.risk_stats(pnl)
            sim_sd = x.std(axis=0, ddof=1)
            summary.append({"snapshot_id": r.snapshot_id, "snapshot_date": r.snapshot_date, "variant": vid,
                            "role": role, "description": desc, "covariance_id": cov_id, "factors": " ".join(factors),
                            "horizon_bdays": horizon, **st,
                            **{f"sim_sd_{f}": float(sim_sd[i]) for i, f in enumerate(factors)},
                            "input_flags": INPUT_FLAGS + ("; MCX basis PROXY (third-party mirror)"
                                                          if vid == "normal_window_mcx_basis" else ""),
                            "label": SIM_LABEL})
            print(f"[mc] {r.snapshot_id} {t} {vid:<28} VaR99 ₹{st['var99_inr'] / MILLION:8.2f} m  "
                  f"ES99 ₹{st['es99_inr'] / MILLION:8.2f} m  ({time.time() - t0:.1f}s)")
            if vid == BASE_VARIANT:
                base_pnl[r.snapshot_id] = pnl
                dist.append(pd.DataFrame({
                    "snapshot_id": r.snapshot_id, "snapshot_date": r.snapshot_date, "variant": vid,
                    "horizon_bdays": horizon, "path_id": np.arange(mc.N_PATHS),
                    "lme_cash_logret": x[:, 0], "usdinr_logret": x[:, 1], "freight_logret": x[:, 2],
                    "pnl_inr": pnl}))
                es_c = mc.es_contributions(pnl_tr, 0.99)
                for i, tk in enumerate(book.trades):
                    if tk.trade_date > t:
                        continue
                    v99, e99 = mc.var_es(pnl_tr[i], 0.99)
                    contrib.append({"snapshot_id": r.snapshot_id, "snapshot_date": r.snapshot_date,
                                    "trade_id": tk.trade_id, "base_value_excl_funding_inr": float(base_by_trade[i]),
                                    "es99_contribution_inr": float(es_c[i]),
                                    "es99_share_frac": float(-es_c[i] / st["es99_inr"]) if st["es99_inr"] else 0.0,
                                    "standalone_var99_inr": v99, "standalone_es99_inr": e99,
                                    "mean_pnl_inr": float(pnl_tr[i].mean())})
                # linear cross-check against Phase 3's published bump-and-revalue deltas
                d_lin = (e["lme_delta_inr_per_usd_t"] * M.lme_cash_usd_t * np.expm1(x[:, 0])
                         + e["fx_delta_usd"] * M.usdinr * np.expm1(x[:, 1])
                         + e["freight_delta_inr_per_usd_t_usec_mun"] * M.freight_usd_t["USEC_MUN"] * np.expm1(x[:, 2])
                         + e["freight_delta_inr_per_usd_t_jea_nsa"] * M.freight_usd_t["JEA_NSA"] * np.expm1(x[:, 2]))
                v_lin, es_lin = mc.var_es(d_lin, 0.99)
                diff = pnl - d_lin
                delta_rows.append({"snapshot_id": r.snapshot_id, "snapshot_date": r.snapshot_date, "variant": vid,
                                   "var99_full_inr": st["var99_inr"], "var99_delta_approx_inr": v_lin,
                                   "es99_full_inr": st["es99_inr"], "es99_delta_approx_inr": es_lin,
                                   "corr_full_vs_delta": float(np.corrcoef(pnl, d_lin)[0, 1])
                                   if pnl.std() > 0 and d_lin.std() > 0 else float("nan"),
                                   "mean_abs_diff_inr": float(np.abs(diff).mean()),
                                   "max_abs_diff_inr": float(np.abs(diff).max()),
                                   "stdev_full_inr": st["stdev_pnl_inr"], "stdev_delta_approx_inr": float(d_lin.std(ddof=1)),
                                   "note": "full revaluation vs Phase 3 bump-and-revalue deltas x factor moves "
                                           "(no gamma / cross terms); a control, not a second risk number"})

        scen, details = stress_scenarios(book, H, t, cache, unhedged, s, base_pnl[r.snapshot_id], covs["window"],
                                         r.snapshot_id, r.snapshot_date)
        scen_rows.extend(scen)
        detail_rows.extend(details)

    print(f"[mc] done in {time.time() - t_start:.0f}s")
    return {
        "settings": s, "snapshots": pd.DataFrame(snap_rows), "covariance": cov_table, "factor_stats": fstats,
        "summary": pd.DataFrame(summary), "distribution": pd.concat(dist, ignore_index=True),
        "contributions": pd.DataFrame(contrib), "scenarios": pd.DataFrame(scen_rows),
        "scenario_details": pd.DataFrame(detail_rows), "delta_check": pd.DataFrame(delta_rows),
        "quantiles": quantile_table(pd.DataFrame(summary)),
    }


def quantile_table(summary: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in summary.columns if c.startswith("pnl_q")]
    return summary[["snapshot_id", "snapshot_date", "variant", "role", "horizon_bdays"] + cols].copy()


# --------------------------------------------------------------------------------------------- stresses
def _pct(x: float) -> str:
    """A signed whole percentage with a true minus sign: −15%, +40%."""
    return f"{'−' if x < 0 else '+'}{abs(x):.0%}"


def stress_scenarios(book, H, t: dt.date, cache, unhedged, s: dict, pnl: np.ndarray, cov_window: pd.DataFrame,
                     sid: str, sdate: pd.Timestamp) -> tuple[list[dict], list[dict]]:
    """The five Table 6 stresses plus memo rows, each revalued through `revalue_book` and placed in the base MC."""
    base = float(val.revalue_book(book, H, t, cache=cache).sum())
    v95, _ = mc.var_es(pnl, 0.95)
    v99, e99 = mc.var_es(pnl, 0.99)
    sd_h = np.sqrt(np.diag(cov_window.to_numpy()) * s["horizon"])
    sd_of = dict(zip(cov_window.index, sd_h))
    rows, details = [], []

    def add(scenario_id, label, kind, main, value, *, shock=None, factor=None, note="", hypothetical=False):
        sigma = prob = float("nan")
        if factor is not None and sd_of[factor] > 0:
            sigma = float(list(shock.values())[0] / sd_of[factor])
            prob = float(stats.norm.cdf(-abs(sigma)))
        rows.append({
            "snapshot_id": sid, "snapshot_date": sdate, "scenario_id": scenario_id, "scenario_label": label,
            "kind": kind, "role": "SCENARIO" if main else "MEMO",
            "lme_cash_logret": (shock or {}).get("lme_cash_logret", 0.0),
            "usdinr_logret": (shock or {}).get("usdinr_logret", 0.0),
            "freight_logret": (shock or {}).get("freight_logret", 0.0),
            "pnl_inr": value, "mc_percentile_frac": mc.percentile_in(pnl, value),
            "beyond_mc_var95": value < -v95, "beyond_mc_var99": value < -v99, "beyond_mc_es99": value < -e99,
            "beyond_every_mc_path": value < float(pnl.min()),
            "loss_over_mc_var99": (-value / v99) if v99 > 0 else float("nan"),
            "factor_move_sigma_horizon": sigma, "normal_prob_of_move_frac": prob,
            "label": HYPOTHETICAL if hypothetical else SIM_LABEL, "note": note})

    def market(shock, c=cache):
        b = base if c is cache else float(val.revalue_book(book, H, t, cache=c).sum())
        return float(val.revalue_book(book, H, t, shocks=shock, cache=c).sum()) - b

    sh = {"lme_cash_logret": math.log1p(s["lme_move"])}
    add("lme_minus_15pct", f"LME cash {_pct(s['lme_move'])}", "market", True, market(sh), shock=sh, factor="lme",
        note="MCX recomputed from shocked cash at the held basis (unit beta)")
    add("lme_minus_15pct_unhedged_memo", f"LME cash {_pct(s['lme_move'])}, MCX hedges removed", "market", False,
        market(sh, unhedged), shock=sh, factor="lme",
        note="counterfactual book without the MCX legs (ScheduleCache drop_instruments={'mcx'}): what the hedge saved")
    sh = {"usdinr_logret": math.log1p(s["fx_move"])}
    add("inr_minus_5pct", f"INR −5% (USD/INR {_pct(s['fx_move'])})", "market", True, market(sh), shock=sh,
        factor="fx", note="rupee depreciation convention: quoted USD/INR x 1.05; customs rate moves with it")
    sh = {"freight_logret": math.log1p(s["freight_move"])}
    add("freight_plus_40pct", f"Freight {_pct(s['freight_move'])} (HYPOTHETICAL)", "market", True, market(sh),
        shock=sh, factor="freight", hypothetical=True,
        note="both lanes; India-inbound freight FELL through Mar-Aug 2022 — a hypothetical spike, not a replay")

    kw = dict(recovery_unsecured=s["recovery"], resale_discount=s["resale_discount"], cache=cache)
    value, adj = mc.buyer_default_pnl(book, H, t, s["buyer"], **kw)
    note = ("no open flow with this buyer on the snapshot date — nothing to default on" if adj.empty else
            f"recovery {s['recovery']:.2f} on released cargo; retained cargo resold at replacement x "
            f"(1 − {s['resale_discount']:.2f}); implied API recovery per ticket in mc_stress_details.csv")
    add("buyer_default", f"{s['buyer']} (SIM) defaults", "credit", True, value, note=note)
    for r in adj.to_dict("records"):
        details.append({"snapshot_id": sid, "snapshot_date": sdate, "scenario_id": "buyer_default", **r})
    for rec in s["recovery_grid"]:
        v, _ = mc.buyer_default_pnl(book, H, t, s["buyer"], recovery_unsecured=rec,
                                    resale_discount=s["resale_discount"], cache=cache)
        add(f"buyer_default_recovery_{int(round(rec * 100))}pct_memo",
            f"{s['buyer']} defaults, recovery {rec:.0%} on released cargo", "credit", False, v,
            note="the recovery applies only to cargo already released to the buyer; retained cargo is unaffected")
    sh = {"lme_cash_logret": math.log1p(s["lme_move"])}
    v, adj2 = mc.buyer_default_pnl(book, H, t, s["buyer"], shocks=sh, **kw)
    add("buyer_default_with_lme_minus_15pct_memo", f"{s['buyer']} defaults AND LME {_pct(s['lme_move'])}",
        "credit", False, v, shock=sh,
        note="wrong-way combination: retained cargo is resold into the fallen market (its hedge was lifted at sale)")
    for r in adj2.to_dict("records"):
        details.append({"snapshot_id": sid, "snapshot_date": sdate,
                        "scenario_id": "buyer_default_with_lme_minus_15pct_memo", **r})

    ev = val.StressEvent(kind="qco_hold", delay_days=s["qco_delay_days"], rejection_frac=s["qco_rejection"],
                         rejected_loss_frac=s["qco_rejected_loss"])
    v, adj3 = mc.qco_hold_pnl(book, H, t, ev, cache=cache, uncleared_only=s["qco_uncleared_only"])
    add("qco_hold_demurrage", "BIS-QCO hold + demurrage (HYPOTHETICAL policy)", "policy", True, v, hypothetical=True,
        note=f"no QCO applied to scrap in 2022; +{s['qco_delay_days']} d dwell at the first-slab rate, "
             f"{s['qco_rejection']:.0%} rejected at {s['qco_rejected_loss']:.0%} loss; tickets with uncleared lots "
             "only; extra finance cost of the delay NOT included")
    for r in adj3.to_dict("records"):
        details.append({"snapshot_id": sid, "snapshot_date": sdate, "scenario_id": "qco_hold_demurrage", **r})
    v_all, _ = mc.qco_hold_pnl(book, H, t, ev, cache=cache, uncleared_only=False)
    add("qco_hold_all_tickets_memo", "BIS-QCO stress, API applied to every ticket on the book", "policy", False,
        v_all, hypothetical=True, note="overstates: charges dwell on boxes already released")
    return rows, details


# ----------------------------------------------------------------------------------------------------- charts
SNAP_TITLES = {"ATH_PLUS_1": "Day after the LME all-time high", "PEAK_GROSS_LME": "Peak gross LME exposure",
               "PEAK_BUYER_CONTRACTED": "Peak BUY_RJK_01 contracted exposure"}
SHORT = {"lme_minus_15pct": "LME −15%", "inr_minus_5pct": "INR −5%", "freight_plus_40pct": "Freight +40% (hyp.)",
         "buyer_default": "Buyer default", "qco_hold_demurrage": "BIS-QCO hold (hyp.)"}
RISK_LINE = "#404040"


def _m(x_inr: float) -> str:
    """₹ million with a true minus sign: −₹73.5 m."""
    v = x_inr / MILLION
    if abs(v) < 0.05:
        return "₹0.0 m"
    return f"{'−' if v < 0 else '+'}₹{abs(v):,.1f} m"


def _scenario_line(row) -> str:
    if abs(row.pnl_inr) < 1.0:
        return f"{SHORT[row.scenario_id]}: ₹0 — no exposure on this date"
    where = ("worse than every path" if row.beyond_every_mc_path
             else f"{row.mc_percentile_frac:.2%} of paths are as bad or worse")
    return f"{SHORT[row.scenario_id]}: {_m(row.pnl_inr)} ({where})"


def chart_distribution(dist: pd.DataFrame, summary: pd.DataFrame, scen: pd.DataFrame) -> None:
    ids = list(dict.fromkeys(dist["snapshot_id"]))
    fig, grid = plt.subplots(len(ids), 2, figsize=(13, 3.9 * len(ids)), gridspec_kw={"width_ratios": [2.5, 1]})
    grid = np.atleast_2d(grid)
    order = list(SHORT)
    for (ax, side), sid in zip(grid, ids):
        p = dist.loc[dist.snapshot_id == sid, "pnl_inr"].to_numpy() / MILLION
        st = summary[(summary.snapshot_id == sid) & (summary.variant == BASE_VARIANT)].iloc[0]
        sc = scen[(scen.snapshot_id == sid) & (scen.role == "SCENARIO")].set_index("scenario_id").reindex(order)
        lo, hi = min(p.min(), -st.es99_inr / MILLION), p.max()
        pad = 0.06 * (hi - lo)
        lo, hi = lo - pad, hi + pad
        ax.hist(p, bins=90, color=PALETTE["band"], edgecolor=PALETTE["hist"], linewidth=0.3)
        ymax = ax.get_ylim()[1] * 1.15
        ax.set_ylim(0, ymax)
        for v, style, lab in ((st.var95_inr, "--", "95% VaR"), (st.var99_inr, "-", "99% VaR"),
                              (st.es99_inr, ":", "99% ES")):
            ax.axvline(-v / MILLION, color=RISK_LINE, linestyle=style, linewidth=1.3, label=f"{lab} {_m(v)[1:]}")
        lines = []
        for k, row in enumerate(sc.reset_index().itertuples(index=False)):
            color = SCENARIO_COLORS[row.kind]
            x = row.pnl_inr / MILLION
            tag = str(k + 1)
            if abs(row.pnl_inr) >= 1.0 and lo <= x <= hi:
                ax.axvline(x, color=color, linewidth=1.8, alpha=0.9)
                ax.text(x, ymax * (0.985 - 0.06 * k), tag, color="white", fontsize=7.5, ha="center", va="top",
                        fontweight="bold", bbox=dict(boxstyle="circle,pad=0.2", fc=color, ec="none"))
            elif abs(row.pnl_inr) >= 1.0:  # off scale to the left: an arrow at the axis edge
                ax.annotate(tag, xy=(lo, ymax * 0.04), xytext=(lo + 0.04 * (hi - lo), ymax * (0.45 - 0.1 * k)),
                            color="white", fontsize=7.5, fontweight="bold", ha="center", va="center",
                            bbox=dict(boxstyle="circle,pad=0.2", fc=color, ec="none"),
                            arrowprops=dict(arrowstyle="->", color=color, lw=1.2))
            lines.append((f"{tag}  {_scenario_line(row)}", color))
        ax.set_xlim(lo, hi)
        ax.set_title(f"{SNAP_TITLES.get(sid, sid)} — {pd.Timestamp(st.snapshot_date).date()}", loc="left")
        ax.set_xlabel(f"{int(st.horizon_bdays)}-business-day book P&L vs the snapshot mark, ₹ million "
                      "(funding excluded; clock, contracts, events held)")
        ax.set_ylabel("paths (of 10,000)")
        ax.legend(loc="upper right", fontsize=7.5)
        side.axis("off")
        side.text(0.0, 0.97, "Stress scenarios (full revaluation)", fontsize=9, fontweight="bold", va="top",
                  transform=side.transAxes)
        for j, (text, color) in enumerate(lines):
            name, _, rest = text.partition(": ")
            side.text(0.0, 0.84 - 0.165 * j, f"{name}:\n    {rest}", fontsize=8, color=color, va="top",
                      transform=side.transAxes)
    fig.suptitle("Monte Carlo P&L distribution (zero-mean normal, window covariance) with the five Table 6 stresses",
                 fontweight="bold")
    fig.tight_layout(rect=(0, 0.01, 1, 0.985))
    save_fig(fig, "p4_mc_distribution", SOURCE_NOTE + "; freight +40% and BIS-QCO are HYPOTHETICAL")


def chart_scenarios(summary: pd.DataFrame, scen: pd.DataFrame) -> None:
    ids = list(dict.fromkeys(summary["snapshot_id"]))
    fig, axes = plt.subplots(1, len(ids), figsize=(5.4 * len(ids), 4.9), sharey=True)
    axes = np.atleast_1d(axes)
    order = list(SHORT)
    handles = None
    for ax, sid in zip(axes, ids):
        st = summary[(summary.snapshot_id == sid) & (summary.variant == BASE_VARIANT)].iloc[0]
        sb = summary[(summary.snapshot_id == sid) & (summary.variant == "normal_window_mcx_basis")].iloc[0]
        sc = scen[(scen.snapshot_id == sid) & (scen.role == "SCENARIO")].set_index("scenario_id").reindex(order)
        vals = sc["pnl_inr"].to_numpy() / MILLION
        y = np.arange(len(order))
        ax.barh(y, vals, color=[SCENARIO_COLORS[k] for k in sc["kind"]], alpha=0.85, height=0.62)
        lo = min(vals.min(), -st.es99_inr / MILLION, -sb.var99_inr / MILLION)
        hi = max(vals.max(), 0.0)
        span = hi - lo
        for yy, v, raw in zip(y, vals, sc["pnl_inr"].to_numpy()):
            txt = "0 (no exposure)" if abs(raw) < 1.0 else _m(raw)
            ax.text(max(v, 0.0) + 0.02 * span, yy, txt, va="center", ha="left", fontsize=8)
        ax.axvline(-st.var95_inr / MILLION, color=RISK_LINE, linestyle="--", linewidth=1.1, label="MC 95% VaR")
        ax.axvline(-st.var99_inr / MILLION, color=RISK_LINE, linestyle="-", linewidth=1.1, label="MC 99% VaR")
        ax.axvline(-st.es99_inr / MILLION, color=RISK_LINE, linestyle=":", linewidth=1.4, label="MC 99% ES")
        ax.axvline(-sb.var99_inr / MILLION, color=PALETTE["mcx"], linestyle="-.", linewidth=1.3,
                   label="MC 99% VaR with MCX basis factor (PROXY sensitivity)")
        ax.axvline(0, color=PALETTE["neutral"], linewidth=0.8)
        ax.set_yticks(y, [SHORT[k] for k in order])
        ax.invert_yaxis()
        ax.set_xlim(lo - 0.08 * span, hi + 0.45 * span + 0.5)
        ax.set_title(f"{SNAP_TITLES.get(sid, sid)} — {pd.Timestamp(st.snapshot_date).date()}\n"
                     f"99% VaR {_m(st.var99_inr)[1:]} · ES {_m(st.es99_inr)[1:]} · with basis {_m(sb.var99_inr)[1:]}",
                     fontsize=9.5)
        ax.set_xlabel("₹ million")
        handles = ax.get_legend_handles_labels()
    fig.legend(*handles, loc="lower center", ncol=4, fontsize=8, bbox_to_anchor=(0.5, 0.03))
    fig.suptitle(f"Stress scenario P&L against Monte Carlo VaR / ES ({int(summary.horizon_bdays.iloc[0])} business days, "
                 "zero-mean normal, window covariance)", fontweight="bold")
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    save_fig(fig, "p4_mc_scenarios", SOURCE_NOTE + "; freight +40% and BIS-QCO are HYPOTHETICAL")


# ----------------------------------------------------------------------------------------------------- main
def control_freight_vs_phase3(scen: pd.DataFrame) -> pd.DataFrame:
    """The freight +40 % stress must equal Phase 3's published hypothetical on the same date (same API call)."""
    p3 = pd.read_csv(TABLES_DIR / "adverse_event_3_freight_stress_hypothetical.csv", parse_dates=["date"])
    p3 = p3[p3["trade_id"] == "BOOK"].set_index("date")["impact_inr"]
    rows = []
    for r in scen[scen.scenario_id == "freight_plus_40pct"].itertuples(index=False):
        ref = float(p3.get(r.snapshot_date, float("nan")))
        rows.append({"snapshot_id": r.snapshot_id, "snapshot_date": r.snapshot_date, "mc_pnl_inr": r.pnl_inr,
                     "phase3_impact_inr": ref, "diff_inr": r.pnl_inr - ref,
                     "status": "PASS" if abs(r.pnl_inr - ref) <= 1.0 else "FAIL"})
    return pd.DataFrame(rows)


def main() -> None:
    ensure_dirs()
    out = run()
    ctl = control_freight_vs_phase3(out["scenarios"])
    snaps = out["snapshots"]
    if (ctl["status"] != "PASS").any():
        raise RuntimeError(f"freight stress does not reproduce Phase 3:\n{ctl}")
    if (snaps["reconciliation_diff_inr"].abs() > 1.0).any():
        raise RuntimeError(f"snapshot base values do not reconcile to Phase 3 cum P&L:\n{snaps}")
    write(snaps, "mc_snapshots")
    write(out["covariance"], "mc_covariance")
    write(out["factor_stats"], "mc_factor_stats")
    write(out["summary"], "mc_summary")
    write(out["quantiles"], "mc_pnl_quantiles")
    write(out["distribution"], "mc_pnl_distribution")
    write(out["contributions"], "mc_es_contributions")
    write(out["scenarios"], "mc_stress_scenarios")
    write(out["scenario_details"], "mc_stress_details")
    write(out["delta_check"], "mc_delta_check")
    write(ctl, "mc_controls")
    chart_distribution(out["distribution"], out["summary"], out["scenarios"])
    chart_scenarios(out["summary"], out["scenarios"])
    cols = ["snapshot_id", "variant", "horizon_bdays", "var95_inr", "var99_inr", "es99_inr", "prob_loss_frac"]
    print(out["summary"][cols].to_string(index=False))
    print(out["scenarios"][["snapshot_id", "scenario_id", "pnl_inr", "mc_percentile_frac"]].to_string(index=False))


if __name__ == "__main__":
    main()
