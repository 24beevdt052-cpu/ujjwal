"""Phase 4.2 ★ — Monte Carlo stress: joint factor simulation, full revaluation of the book, tail statistics.

MASTER_SPEC Table 6 row 4.2 asks for 10,000 paths jointly simulating LME, USD/INR and freight from their historical
covariance over the backtest window, the full P&L distribution with 95 % / 99 % percentile losses, and the five stress
scenarios overlaid on it. This module holds the pure, testable pieces; `desk.risk.run_mc` wires them to the panel, the
book and the charts (docs/41_monte_carlo.md is the method page).

Model choices, and why:

* **Factors are the valuation API's own shock keys** (`desk.mtm.valuation.SHOCK_KEYS`): LME cash log return, USD/INR
  log return, ONE freight log return applied to both lanes (JEA_NSA is a fixed 0.2255 × USEC_MUN in every week of the
  panel, so a second lane factor would be a copy), and — in a sensitivity only — an additive MCX basis in ₹/kg.
* **Mixed-frequency covariance.** LME and USD/INR are daily series, so their block comes from daily returns. Freight
  is assessed weekly and carried forward on the daily calendar (CONTRACTS §3): its daily returns are four zeros and
  a jump, which attenuates every correlation it enters. Its variance and correlations are therefore estimated on
  complete W-FRI weeks and converted to daily units (variance ÷ 5 business days). The MCX basis from the third-party
  mirror is handled the same way, for a different reason: its daily changes are dominated by close-time noise that
  reverses the next day (weekly σ is ~1/3 of daily σ × √5), so a daily estimate scaled by √h would overstate it.
* **Zero mean.** Every simulation is centred. The window's LME drift (about −0.3 % a day) is the crash itself;
  simulating it forward would bake 2022's realised direction into a risk number.
* **Square-root-of-time horizon** (`h × Σ_daily`), i.e. no autocorrelation. `factor_stats` publishes the 10-day
  variance ratio so a reader can see how far that holds on the window.
* **Full revaluation, one path at a time.** `revalue_book` accepts equal-length arrays, but an array-valued freight
  shock raises inside `shock_state` (`if freight != M.freight_usd_t` compares dicts of arrays). Per-path scalar calls
  go through exactly the published function and take well under a millisecond each, so 10,000 paths cost seconds.
* **Common random numbers.** One `numpy.random.default_rng(desk.RNG_SEED)` stream is drawn once (normals, the
  chi-square mixing variable, bootstrap picks) and reused by every snapshot and variant, so differences between
  variants are differences in the model, not in the draw.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from desk import RNG_SEED
from desk.mtm import curves, lifecycle
from desk.mtm import valuation as val

N_PATHS = 10_000
CONFIDENCE_LEVELS = (0.95, 0.99)
BATCH_PATHS = 1_000              # progress / memory granularity of the revaluation loop
BDAYS_PER_WEEK = 5
Z_CI = float(stats.norm.ppf(0.975))

BASE_FACTORS = ("lme", "fx", "freight")
BASIS_FACTOR = "mcx_basis"
SHOCK_KEY = {"lme": "lme_cash_logret", "fx": "usdinr_logret", "freight": "freight_logret",
             "mcx_basis": "mcx_basis_abs"}
FACTOR_UNIT = {"lme": "log_return", "fx": "log_return", "freight": "log_return", "mcx_basis": "inr_kg_abs_change"}
DAILY_FACTORS = ("lme", "fx")    # estimated on daily returns
WEEKLY_FACTORS = ("freight", "mcx_basis")  # estimated on complete weeks, converted to daily units


# ------------------------------------------------------------------------------------------------ factor data
def weekly_samples(daily_levels: pd.DataFrame) -> pd.DataFrame:
    """Last panel day of each W-FRI week, indexed by the week's Friday label (CONTRACTS §3 week convention)."""
    lv = daily_levels.copy()
    lv["sample_date"] = lv.index
    return lv.resample("W-FRI").last().dropna(subset=["sample_date"])


def factor_changes(levels: pd.DataFrame) -> pd.DataFrame:
    """Changes dated on the later observation: log returns for prices, absolute changes for the basis (₹/kg)."""
    out = pd.DataFrame(index=levels.index)
    out["lme"] = np.log(levels["lme_cash_usd_t"] / levels["lme_cash_usd_t"].shift(1))
    out["fx"] = np.log(levels["usdinr"] / levels["usdinr"].shift(1))
    out["freight"] = np.log(levels["freight_usec_mun_usd_t"] / levels["freight_usec_mun_usd_t"].shift(1))
    if "mcx_basis_inr_kg" in levels:
        out["mcx_basis"] = levels["mcx_basis_inr_kg"].diff()
    return out.iloc[1:]


@dataclass(frozen=True)
class Span:
    """An estimation span: daily changes dated in [start, end]; complete weeks whose Friday label is in [start, end]."""

    name: str
    start: pd.Timestamp
    end: pd.Timestamp

    def daily(self, daily_chg: pd.DataFrame) -> pd.DataFrame:
        return daily_chg.loc[(daily_chg.index >= self.start) & (daily_chg.index <= self.end)]

    def weekly(self, weekly_chg: pd.DataFrame) -> pd.DataFrame:
        return weekly_chg.loc[(weekly_chg.index >= self.start) & (weekly_chg.index <= self.end)]


def trailing_span(name: str, daily_index: pd.DatetimeIndex, end: pd.Timestamp, n_days: int) -> Span:
    """The `n_days` daily changes dated on or before `end` — what a desk knew at that close (no hindsight)."""
    idx = daily_index[daily_index <= end]
    if len(idx) < n_days:
        raise ValueError(f"only {len(idx)} daily changes on or before {end.date()}, need {n_days}")
    return Span(name, idx[-n_days], end)


# ------------------------------------------------------------------------------------------------ covariance
def nearest_psd_corr(corr: np.ndarray) -> tuple[np.ndarray, float]:
    """Clip negative eigenvalues of a correlation matrix and restore a unit diagonal. Returns (matrix, min eigenvalue).

    Needed only when pairwise correlations come from different samples (daily vs weekly), which does not guarantee a
    positive semi-definite matrix. On this panel no span needed it; the check stays so a future panel cannot fail
    silently in the Cholesky factorisation.
    """
    w, v = np.linalg.eigh(corr)
    min_eig = float(w.min())
    if min_eig >= 0.0:
        return corr, min_eig
    fixed = (v * np.clip(w, 0.0, None)) @ v.T
    d = np.sqrt(np.diag(fixed))
    return fixed / np.outer(d, d), min_eig


def assemble_covariance(daily: pd.DataFrame, weekly: pd.DataFrame, factors: Sequence[str],
                        bdays_per_week: int = BDAYS_PER_WEEK) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily-unit covariance of `factors`: daily pairs from daily data, any pair with a weekly factor from weeks.

    Returns (covariance DataFrame, pair table with the sample each number came from). Standard deviations are sample
    (ddof = 1, demeaned) statistics — the simulation itself is zero-mean.
    """
    factors = list(factors)
    sd = {}
    n_obs = {}
    for f in factors:
        if f in WEEKLY_FACTORS:
            x = weekly[f].dropna()
            sd[f] = float(x.std(ddof=1)) / math.sqrt(bdays_per_week)
        else:
            x = daily[f].dropna()
            sd[f] = float(x.std(ddof=1))
        n_obs[f] = int(len(x))
    k = len(factors)
    corr = np.eye(k)
    rows = []
    for i, a in enumerate(factors):
        for j, b in enumerate(factors):
            if j < i:
                continue
            if i == j:
                src = "weekly" if a in WEEKLY_FACTORS else "daily"
                n = n_obs[a]
                r = 1.0
            else:
                weekly_pair = a in WEEKLY_FACTORS or b in WEEKLY_FACTORS
                src = "weekly" if weekly_pair else "daily"
                frame = (weekly if weekly_pair else daily)[[a, b]].dropna()
                n = int(len(frame))
                r = float(np.corrcoef(frame[a], frame[b])[0, 1])
                corr[i, j] = corr[j, i] = r
            rows.append({"factor_i": a, "factor_j": b, "sample": src, "n_obs": n, "corr_raw": r})
    corr_psd, min_eig = nearest_psd_corr(corr)
    s = np.array([sd[f] for f in factors])
    cov = corr_psd * np.outer(s, s)
    pairs = pd.DataFrame(rows)
    pairs["corr"] = [corr_psd[factors.index(a), factors.index(b)] for a, b in zip(pairs.factor_i, pairs.factor_j)]
    pairs["cov_daily"] = [cov[factors.index(a), factors.index(b)] for a, b in zip(pairs.factor_i, pairs.factor_j)]
    pairs["min_eigenvalue_raw_corr"] = min_eig
    pairs["psd_adjusted"] = min_eig < 0.0
    return pd.DataFrame(cov, index=factors, columns=factors), pairs


def cholesky(cov: np.ndarray) -> np.ndarray:
    """Lower Cholesky factor; a factor with zero variance (e.g. no weekly freight moves) gets a zero column."""
    cov = np.asarray(cov, dtype=float)
    d = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    live = d > 0
    L = np.zeros_like(cov)
    if live.any():
        sub = cov[np.ix_(live, live)]
        L[np.ix_(live, live)] = np.linalg.cholesky(sub + np.eye(sub.shape[0]) * 1e-18 * np.trace(sub))
    return L


# ----------------------------------------------------------------------------------------------------- draws
@dataclass(frozen=True)
class Draws:
    """The one random stream every snapshot and variant reuses (common random numbers)."""

    z: np.ndarray        # (n_paths, n_factors) iid standard normals
    chi2: np.ndarray     # (n_paths,) chi-square(nu) mixing variable for the multivariate t
    u_boot: np.ndarray   # (n_paths, horizon_bdays) uniforms for the bootstrap's day picks
    nu: float


def standard_draws(n_paths: int, n_factors: int, horizon_bdays: int, nu: float, seed: int = RNG_SEED) -> Draws:
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n_paths, n_factors))
    chi2 = rng.chisquare(nu, n_paths)
    u = rng.random((n_paths, horizon_bdays))
    return Draws(z=z, chi2=chi2, u_boot=u, nu=float(nu))


def simulate_normal(draws: Draws, cov_h: np.ndarray) -> np.ndarray:
    """Multivariate normal, zero mean, covariance `cov_h`. Cholesky keeps the first factors' paths unchanged when a
    factor is appended last, so the basis sensitivity differs from the base only by the basis."""
    k = cov_h.shape[0]
    return draws.z[:, :k] @ cholesky(cov_h).T


def simulate_student_t(draws: Draws, cov_h: np.ndarray) -> np.ndarray:
    """Multivariate t with `nu` degrees of freedom scaled to the SAME covariance: x = L z · sqrt((nu − 2) / chi2).

    One mixing variable per path moves every factor together — a normal whose variance is itself uncertain over the
    horizon, which is the regime-shift story (GARCH half-life of about 17 days, docs/40), not a daily fat tail.
    """
    if draws.nu <= 2:
        raise ValueError("Student-t needs nu > 2 for a finite covariance")
    scale = np.sqrt((draws.nu - 2.0) / draws.chi2)
    return simulate_normal(draws, cov_h) * scale[:, None]


def simulate_bootstrap(draws: Draws, daily_matrix: np.ndarray) -> np.ndarray:
    """iid bootstrap of whole days: each path sums `horizon` demeaned daily factor vectors drawn with replacement.

    Keeps the window's fat tails and same-day co-movement; drops autocorrelation. Freight enters as its carried daily
    series, so a 10-day path holds on average two weekly assessments — the right variance, attenuated correlation.
    """
    x = np.asarray(daily_matrix, dtype=float)
    x = x - x.mean(axis=0)
    idx = np.floor(draws.u_boot * x.shape[0]).astype(np.int64)
    idx = np.minimum(idx, x.shape[0] - 1)
    return x[idx].sum(axis=1)


# ---------------------------------------------------------------------------------------------- revaluation
def revalue_paths(book, H, t: dt.date, shocks: Mapping[str, np.ndarray], *, cache: val.ScheduleCache,
                  mcx_hold_basis: bool = True, batch: int = BATCH_PATHS) -> np.ndarray:
    """P&L per trade per path, `(n_trades, n_paths)`: `revalue_book(shocked) − revalue_book(unshocked)` at clock t.

    Funding is excluded on both sides (it is a history-only accrual and cancels in the difference). The clock,
    contracts and events are held at t: an instantaneous re-mark of the position as it stood at that close.
    """
    keys = list(shocks)
    arrays = [np.asarray(shocks[k], dtype=float) for k in keys]
    n = int(arrays[0].shape[0]) if arrays else 0
    base = val.revalue_book(book, H, t, cache=cache, mcx_hold_basis=mcx_hold_basis)[:, 0]
    out = np.empty((len(book.trades), n))
    for start in range(0, n, batch):
        for i in range(start, min(n, start + batch)):
            s = {k: float(a[i]) for k, a in zip(keys, arrays)}
            out[:, i] = val.revalue_book(book, H, t, shocks=s, mcx_hold_basis=mcx_hold_basis, cache=cache)[:, 0]
    return out - base[:, None]


def shocks_from_matrix(x: np.ndarray, factors: Sequence[str]) -> dict[str, np.ndarray]:
    return {SHOCK_KEY[f]: x[:, i] for i, f in enumerate(factors)}


# ----------------------------------------------------------------------------------------------- statistics
def tail_count(n: int, confidence: float) -> int:
    """Number of paths in the (1 − confidence) tail: 100 of 10,000 at 99 %."""
    return max(1, int(math.ceil(round((1.0 - confidence) * n, 9))))


def var_es(pnl: np.ndarray, confidence: float) -> tuple[float, float]:
    """Historical-simulation estimators on the simulated P&L: VaR = −(k-th worst), ES = −mean(k worst), k = ⌈(1−c)n⌉.
    Both are reported as positive loss amounts."""
    s = np.sort(np.asarray(pnl, dtype=float))
    k = tail_count(len(s), confidence)
    return float(-s[k - 1]), float(-s[:k].mean())


def var_ci(pnl: np.ndarray, confidence: float) -> tuple[float, float]:
    """Distribution-free 95 % interval for the VaR order statistic (binomial, normal approximation): the Monte Carlo
    sampling error of the quoted VaR, NOT model uncertainty."""
    s = np.sort(np.asarray(pnl, dtype=float))
    n = len(s)
    p = 1.0 - confidence
    k = tail_count(n, confidence)
    half = Z_CI * math.sqrt(n * p * (1.0 - p))
    lo_i = int(max(0, math.floor(k - 1 - half)))
    hi_i = int(min(n - 1, math.ceil(k - 1 + half)))
    return float(-s[hi_i]), float(-s[lo_i])


def risk_stats(pnl: np.ndarray) -> dict:
    pnl = np.asarray(pnl, dtype=float)
    out = {"n_paths": int(len(pnl)), "mean_pnl_inr": float(pnl.mean()), "stdev_pnl_inr": float(pnl.std(ddof=1)),
           "prob_loss_frac": float((pnl < 0).mean())}
    for c in CONFIDENCE_LEVELS:
        tag = int(round(c * 100))
        v, e = var_es(pnl, c)
        out[f"var{tag}_inr"] = v
        out[f"es{tag}_inr"] = e
    lo, hi = var_ci(pnl, 0.99)
    out["var99_ci95_low_inr"] = lo
    out["var99_ci95_high_inr"] = hi
    for q in (0.001, 0.01, 0.05, 0.5, 0.95, 0.99, 0.999):
        out[f"pnl_q{q * 100:g}_inr".replace(".", "p")] = float(np.quantile(pnl, q))
    out["min_pnl_inr"] = float(pnl.min())
    out["max_pnl_inr"] = float(pnl.max())
    return out


def percentile_in(pnl: np.ndarray, x: float) -> float:
    """Share of simulated paths with P&L at or below `x` (0.0 = worse than every path)."""
    return float((np.asarray(pnl) <= x).mean())


def es_contributions(pnl_by_trade: np.ndarray, confidence: float = 0.99) -> np.ndarray:
    """Each trade's mean P&L over the book's worst-k paths. The contributions add up to −ES of the book exactly."""
    book = pnl_by_trade.sum(axis=0)
    k = tail_count(book.shape[0], confidence)
    worst = np.argsort(book, kind="stable")[:k]
    return pnl_by_trade[:, worst].mean(axis=1)


def factor_stats(x: pd.Series, horizon: int | None = None) -> dict:
    """Moments and a Jarque–Bera normality test; with `horizon`, the overlapping h-day variance ratio."""
    x = x.dropna().astype(float)
    jb = stats.jarque_bera(x.to_numpy())
    out = {"n_obs": int(len(x)), "mean": float(x.mean()), "stdev": float(x.std(ddof=1)),
           "skew": float(stats.skew(x, bias=False)), "excess_kurtosis": float(stats.kurtosis(x, bias=False)),
           "jarque_bera_stat": float(jb.statistic), "jarque_bera_p": float(jb.pvalue),
           "min": float(x.min()), "max": float(x.max()), "date_of_min": x.idxmin(), "date_of_max": x.idxmax()}
    if horizon:
        agg = x.rolling(horizon).sum().dropna()
        out["variance_ratio_h"] = float(agg.var(ddof=1) / (horizon * x.var(ddof=1)))
    return out


# ------------------------------------------------------------------------------------------ stress scenarios
def sub_book(book, ticket):
    return replace(book, trades=(ticket,))


def tickets_on_book(book, t: dt.date) -> list:
    return [tk for tk in book.trades if tk.trade_date <= t]


def buyer_default_adjustments(book, H, t: dt.date, buyer_id: str, *, recovery_unsecured: float,
                              resale_discount: float, cache: val.ScheduleCache,
                              shocks: Mapping[str, float] | None = None) -> pd.DataFrame:
    """Per ticket: the loss if `buyer_id` defaults at t, and the single recovery that makes the API reproduce it.

    `StressEvent("buyer_default")` writes off every future flow with the buyer at one `recovery_frac`. That is right
    for cargo already released to the buyer (an unsecured receivable), wrong for cargo still in the desk's hands:
    there the desk keeps the goods and resells them. So, per sale, pro rata by bill-of-lading tonnage:

    * released lots → lose `receipts × (1 − recovery_unsecured)`;
    * unreleased lots → lose `max(0, receipts − retained_mt × replacement_value × (1 − resale_discount))` — the lost
      price net of a distressed resale at today's import replacement mark (CONTRACTS §7a.1.3), never a windfall.

    The implied per-ticket recovery = 1 − loss / Σ future buyer receipts is then passed to the API, so the published
    number still comes out of `revalue_book`.
    """
    M = val.shock_state(H.state_at(t), shocks) if shocks else H.state_at(t)
    HV = H.view(t)
    rows = []
    for ticket in tickets_on_book(book, t):
        tv = val.trade_value(ticket, book, t, t, M, t, H, cache)
        sched = tv.schedule
        future = [(f, float(v)) for f, v in zip(sched.flows, tv.per_flow)
                  if f.counterparty_id == buyer_id and f.settle_date is not None and f.settle_date > t]
        if not future:
            continue
        total = sum(v for _, v in future)
        box = lifecycle.LANE_BOX[ticket.lane.value]
        rep = float(curves.replacement_value(HV, M, t, ticket.grade.value, ticket.lane.value, box))
        loss = 0.0
        released_mt = retained_mt = 0.0
        for sale in ticket.sales:
            if sale.buyer_id != buyer_id:
                continue
            receipts = sum(v for f, v in future if f.sale_id == sale.sale_id)
            q_rel = sum(sched.quantities[l].q_bl_mt for l in sale.lot_ids if sched.lot_dates[l].release <= t)
            q_ret = sum(sched.quantities[l].q_bl_mt - sched.quantities[l].q_rej_mt
                        for l in sale.lot_ids if sched.lot_dates[l].release > t)
            q_all = sum(sched.quantities[l].q_bl_mt for l in sale.lot_ids)
            share_rel = q_rel / q_all if q_all else 0.0
            loss += receipts * share_rel * (1.0 - recovery_unsecured)
            lost_unreleased = receipts * (1.0 - share_rel)
            loss += max(0.0, lost_unreleased - q_ret * rep * (1.0 - resale_discount))
            released_mt += q_rel
            retained_mt += q_ret
        rows.append({"trade_id": ticket.trade_id, "future_receipts_inr": total, "released_mt": released_mt,
                     "retained_mt": retained_mt, "replacement_inr_t": rep, "loss_inr": loss,
                     "implied_recovery_frac": (1.0 - loss / total) if total else 1.0})
    return pd.DataFrame(rows)


def buyer_default_pnl(book, H, t: dt.date, buyer_id: str, *, recovery_unsecured: float, resale_discount: float,
                      cache: val.ScheduleCache, shocks: Mapping[str, float] | None = None) -> tuple[float, pd.DataFrame]:
    """Book P&L of the default (with optional simultaneous market shocks), revalued through `revalue_book`."""
    adj = buyer_default_adjustments(book, H, t, buyer_id, recovery_unsecured=recovery_unsecured,
                                    resale_discount=resale_discount, cache=cache, shocks=shocks)
    base = float(val.revalue_book(book, H, t, cache=cache).sum())
    shocked = float(val.revalue_book(book, H, t, shocks=shocks, cache=cache).sum()) if shocks else base
    stressed = shocked
    api_rows = []
    for r in adj.itertuples(index=False):
        tk = book.trade(r.trade_id)
        sb = sub_book(book, tk)
        ev = val.StressEvent(kind="buyer_default", buyer_id=buyer_id, recovery_frac=float(r.implied_recovery_frac))
        with_ev = float(val.revalue_book(sb, H, t, shocks=shocks, extra_events=[ev], cache=cache).sum())
        without = float(val.revalue_book(sb, H, t, shocks=shocks, cache=cache).sum())
        stressed += with_ev - without
        api_rows.append(with_ev - without)
    if len(adj):
        adj = adj.assign(api_adjustment_inr=api_rows)
    return stressed - base, adj


def qco_hold_pnl(book, H, t: dt.date, event: val.StressEvent, *, cache: val.ScheduleCache,
                 uncleared_only: bool = True) -> tuple[float, pd.DataFrame]:
    """BIS-QCO hold through the API, applied to the tickets a clearance-stage policy could reach.

    `StressEvent("qco_hold")` charges demurrage on every box of a ticket and a write-off on its unsold (or whole)
    tonnage, whatever the lots' status. A QCO bites at the Bill of Entry, so by default the stress is applied only to
    tickets on the book with at least one lot not yet released at t; `uncleared_only=False` reproduces the API applied
    to every ticket on the book (published as a memo row).
    """
    rows = []
    total = 0.0
    for ticket in tickets_on_book(book, t):
        sched = cache.get(ticket, t, t)
        uncleared = [l for l, ld in sched.lot_dates.items() if ld.release > t]
        if uncleared_only and not uncleared:
            continue
        sb = sub_book(book, ticket)
        adj = float(val.revalue_book(sb, H, t, extra_events=[event], cache=cache).sum()
                    - val.revalue_book(sb, H, t, cache=cache).sum())
        boxes = sum(q.boxes for q in sched.quantities.values())
        total += adj
        rows.append({"trade_id": ticket.trade_id, "boxes": boxes, "uncleared_lots": len(uncleared),
                     "adjustment_inr": adj})
    return total, pd.DataFrame(rows)


def same_day_flow_deltas(book, H, t: dt.date, cache: val.ScheduleCache) -> dict:
    """LME (₹ per USD/t) and USD/INR (₹ per ₹) deltas of P&L flows that fix or settle ON the snapshot date and do not
    continue past it.

    `revalue_book` shocks the close of t, so a flow fixing at that close moves with the shock even if the position
    ends there — an MCX line exiting or rolling out at t is the Phase 4.1 finding. Today's variation margin on an MCX
    line that stays open after t is excluded: that IS the hedge's delta, carried through its daily settlement.
    Snapshots avoid exit/roll days; this measures anything that is left.
    """
    M = H.state_at(t)
    bumps = {"lme": ("lme_cash_logret", math.log(1.0 + 1.0 / M.lme_cash_usd_t),
                     math.log(1.0 - 1.0 / M.lme_cash_usd_t), 2.0),
             "fx": ("usdinr_logret", math.log(1.0 + 0.01 / M.usdinr), math.log(1.0 - 0.01 / M.usdinr), 0.02)}
    out = {}
    for name, (key, up, dn, width) in bumps.items():
        ending = total = 0.0
        for ticket in tickets_on_book(book, t):
            exits = {tr.hedge_id: tr.exit_date for tr in ticket.hedges.mcx.tranches}
            vu = val.trade_value(ticket, book, t, t, val.shock_state(M, {key: up}), t, H, cache)
            vd = val.trade_value(ticket, book, t, t, val.shock_state(M, {key: dn}), t, H, cache)
            for f, a, b in zip(vu.schedule.flows, vu.per_flow, vd.per_flow):
                if f.pnl_class != lifecycle.PNL:
                    continue
                d = (float(a) - float(b)) / width
                total += d
                continuing_vm = f.leg_type == "MCX_VARIATION_MARGIN" and exits.get(f.hedge_id, t) > t
                if (f.settle_date == t or f.fixing_date == t) and not continuing_vm:
                    ending += d
        out[f"{name}_delta_all_flows"] = total
        out[f"{name}_delta_ending_same_day_flows"] = ending
    return out
