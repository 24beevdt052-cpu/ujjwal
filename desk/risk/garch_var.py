"""Phase 4.1 ★ — one-day volatility forecasts and parametric VaR: GARCH(1,1) against simple historical volatility.

MASTER_SPEC Table 6 row 4.1 asks for a daily 95 % VaR on the total book scaled day by day by a GARCH(1,1)
conditional-volatility forecast, set beside a simple historical-volatility VaR. This module holds the pure,
testable pieces; `desk.risk.run_var` wires them to the panel and the book.

Model choices (docs/40_var_garch.md §2, and why):

* **Zero mean.** The daily mean LME return (~0.02 %) is two orders of magnitude below its daily volatility
  (~1.3 %); estimating it adds noise, not information, and a zero mean keeps GARCH and the historical window on the
  same footing (the historical window is a root-mean-square, not a demeaned standard deviation).
* **Normal innovations for the base.** Both methods are then read with the same 1.645 multiplier, so the comparison is
  purely about the volatility forecast. Student-t is fitted as a sensitivity: at 95 % a unit-variance t quantile is
  *smaller* than the Normal one (fat tails bite beyond ~97.5 %), so t changes the 95 % VaR less than it changes the
  99 % VaR.
* **Expanding window, weekly refit, daily filtering.** Parameters are re-estimated on every return dated before
  the first panel day of each W-FRI week and held for the week; the variance recursion is run daily. The forecast
  for day t therefore uses returns dated t-1 or earlier — parameters included — which `tests/test_risk_var.py`
  asserts by perturbing the future.

The variance recursion reproduces `arch`'s own (`sigma2[0] = omega + (alpha + beta) * backcast`, backcast = 0.94-decay
weighted mean of the first 75 squared returns), so a forecast here equals `arch`'s fitted conditional variance with
the same parameters; a test pins that too.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from arch import arch_model
from scipy import stats

VAR_CONFIDENCE = 0.95
Z_VAR = float(stats.norm.ppf(VAR_CONFIDENCE))  # 1.6448536...
GARCH_MEAN = "Zero"
GARCH_DIST_BASE = "normal"
GARCH_DIST_SENSITIVITY = "t"
PCT = 100.0  # arch is fitted on percent returns: better-conditioned optimiser, identical model
ARCH_BACKCAST_TAU = 75
ARCH_BACKCAST_DECAY = 0.94
BOUNDARY_PERSISTENCE = 0.999  # alpha + beta at or above this is flagged as an integrated / boundary fit


# ----------------------------------------------------------------------------------------------------- returns
def log_returns(prices: pd.Series) -> pd.Series:
    """Daily log returns, dated on the later price (r_t = ln P_t / P_t-1). Missing prices give no return."""
    p = prices.astype(float)
    r = np.log(p / p.shift(1))
    return r.dropna()


def abs_changes(levels: pd.Series) -> pd.Series:
    """Daily absolute changes, for a factor that crosses zero (the LME cash-3M spread)."""
    return levels.astype(float).diff().dropna()


# ----------------------------------------------------------------------------------------------------- GARCH
def arch_backcast(r: np.ndarray) -> float:
    """`arch`'s GARCH backcast: 0.94-decay weighted mean of the first (up to) 75 squared returns."""
    r = np.asarray(r, dtype=float)
    tau = min(ARCH_BACKCAST_TAU, r.shape[0])
    w = ARCH_BACKCAST_DECAY ** np.arange(tau)
    w = w / w.sum()
    return float(np.sum(r[:tau] ** 2 * w))


def garch_variance_path(r: np.ndarray, omega: float, alpha: float, beta: float, backcast: float) -> np.ndarray:
    """Conditional variances for r[0..n-1] plus the one-step-ahead forecast after r[n-1] (length n + 1).

    `out[i]` depends on r[:i] only — that is the whole no-look-ahead property, and it is structural: the loop reads
    `r[i - 1]` to build `out[i]`.
    """
    r = np.asarray(r, dtype=float)
    n = r.shape[0]
    out = np.empty(n + 1)
    out[0] = omega + (alpha + beta) * backcast
    for i in range(1, n + 1):
        out[i] = omega + alpha * r[i - 1] * r[i - 1] + beta * out[i - 1]
    return out


@dataclass(frozen=True)
class GarchFit:
    """One weekly re-estimate. Variance parameters are in percent-squared units (arch's scale)."""

    series: str
    dist: str
    block: str             # W-FRI period label, e.g. 2022-03-05/2022-03-11
    first_target: pd.Timestamp
    sample_end: pd.Timestamp  # last return in the estimation sample (strictly before first_target)
    n_obs: int
    omega_pct2: float
    alpha: float
    beta: float
    nu: float
    loglik: float
    converged: bool

    @property
    def persistence(self) -> float:
        return self.alpha + self.beta

    @property
    def half_life_days(self) -> float:
        p = self.persistence
        return float(np.log(0.5) / np.log(p)) if 0.0 < p < 1.0 else float("inf")

    @property
    def uncond_vol_frac(self) -> float:
        p = self.persistence
        return float(np.sqrt(self.omega_pct2 / (1.0 - p)) / PCT) if p < 1.0 else float("nan")

    @property
    def boundary(self) -> bool:
        return self.persistence >= BOUNDARY_PERSISTENCE or self.alpha <= 1e-6


def fit_garch(r_frac: pd.Series, dist: str = GARCH_DIST_BASE) -> dict:
    """Fit a zero-mean GARCH(1,1) to daily returns given as fractions. Deterministic (SLSQP from arch's start values)."""
    am = arch_model(np.asarray(r_frac, dtype=float) * PCT, mean=GARCH_MEAN, vol="GARCH", p=1, q=1, dist=dist,
                    rescale=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = am.fit(disp="off", options={"maxiter": 1000})
    p = res.params
    return {
        "omega": float(p["omega"]), "alpha": float(p["alpha[1]"]), "beta": float(p["beta[1]"]),
        "nu": float(p["nu"]) if "nu" in p.index else float("nan"),
        "loglik": float(res.loglikelihood), "converged": int(res.convergence_flag) == 0,
    }


def garch_forecasts(returns: pd.Series, targets: pd.DatetimeIndex, *, series: str, min_obs: int,
                    refit_freq: str = "W-FRI", dist: str = GARCH_DIST_BASE) -> tuple[pd.DataFrame, list[GarchFit]]:
    """One-step-ahead GARCH(1,1) volatility for each target date, using only returns dated before it.

    `returns` is the full dated return series; each target must be one of its dates (a panel day with a return).
    Targets are grouped into `refit_freq` periods; each group is fitted once on returns dated before its first target,
    and the variance recursion is then filtered through the returns dated before each target.
    Returns (frame indexed by target with `sigma_frac`, `sample_end`, `block`, `boundary`, `nu`; list of fits).
    """
    returns = returns.sort_index()
    targets = pd.DatetimeIndex(targets).sort_values()
    missing = targets.difference(returns.index)
    if len(missing):
        raise ValueError(f"{series}: targets without a return on that date: {list(missing[:3])}")
    pos = returns.index.get_indexer(targets)
    values = returns.to_numpy(dtype=float) * PCT
    backcast = arch_backcast(values)  # the expanding sample always starts at the same first return
    periods = targets.to_period(refit_freq)

    sigma = np.full(len(targets), np.nan)
    sample_end = np.full(len(targets), np.datetime64("NaT"), dtype="datetime64[ns]")
    block_lbl = np.empty(len(targets), dtype=object)
    boundary = np.zeros(len(targets), dtype=bool)
    nu = np.full(len(targets), np.nan)
    fits: list[GarchFit] = []
    for period in pd.unique(periods):
        idx = np.flatnonzero(periods == period)
        first_pos = int(pos[idx[0]])
        block_lbl[idx] = str(period)
        if first_pos < min_obs:
            continue
        est = values[:first_pos]                      # returns dated strictly before the block's first target
        prm = fit_garch(est / PCT, dist)
        fit = GarchFit(series=series, dist=dist, block=str(period), first_target=targets[idx[0]],
                       sample_end=returns.index[first_pos - 1], n_obs=first_pos, omega_pct2=prm["omega"],
                       alpha=prm["alpha"], beta=prm["beta"], nu=prm["nu"], loglik=prm["loglik"],
                       converged=prm["converged"])
        fits.append(fit)
        last_pos = int(pos[idx[-1]])
        path = garch_variance_path(values[:last_pos], prm["omega"], prm["alpha"], prm["beta"], backcast)
        sigma[idx] = np.sqrt(path[pos[idx]]) / PCT     # path[k] uses values[:k] only
        sample_end[idx] = np.datetime64(fit.sample_end)
        boundary[idx] = fit.boundary
        nu[idx] = fit.nu
    frame = pd.DataFrame({"sigma_frac": sigma, "sample_end": sample_end, "block": block_lbl, "boundary": boundary,
                          "nu": nu}, index=targets)
    return frame, fits


def fits_frame(fits: list[GarchFit]) -> pd.DataFrame:
    rows = []
    for f in fits:
        rows.append({
            "series": f.series, "dist": f.dist, "block": f.block, "first_target": f.first_target,
            "sample_end": f.sample_end, "n_obs": f.n_obs, "omega_pct2": f.omega_pct2, "alpha": f.alpha,
            "beta": f.beta, "persistence": f.persistence, "half_life_days": f.half_life_days,
            "uncond_vol_daily_frac": f.uncond_vol_frac, "nu": f.nu, "loglik": f.loglik, "converged": f.converged,
            "boundary_fit": f.boundary,
        })
    return pd.DataFrame(rows)


def t_var_multiplier(nu: float, confidence: float = VAR_CONFIDENCE) -> float:
    """Quantile multiplier of a unit-variance Student-t (the scale arch's standardised t uses)."""
    if not np.isfinite(nu) or nu <= 2.0:
        return float("nan")
    return float(-stats.t.ppf(1.0 - confidence, nu) * np.sqrt((nu - 2.0) / nu))


# ------------------------------------------------------------------------------------------- historical vol
def hist_vol(changes: pd.Series, window: int) -> pd.Series:
    """Root-mean-square of the `window` changes dated strictly before each date (zero mean, like the GARCH)."""
    s = changes.astype(float)
    return (s * s).rolling(window, min_periods=window).mean().shift(1).pow(0.5)


def rolling_corr(a: pd.Series, b: pd.Series, window: int) -> pd.Series:
    """Pearson correlation over the `window` days dated strictly before each date."""
    return a.rolling(window, min_periods=window).corr(b).shift(1)


# ------------------------------------------------------------------------------------------------- VaR
def parametric_var(exposures: np.ndarray, sigmas: np.ndarray, corr: np.ndarray, z: float = Z_VAR) -> np.ndarray:
    """Delta-normal VaR: z * sqrt(e' D R D e), row by row.

    exposures (n, k): ₹ P&L per unit factor change (per unit log return, or per USD/t for an absolute factor);
    sigmas (n, k): one-day factor volatility in the same units; corr (n, k, k).
    """
    e = np.atleast_2d(np.asarray(exposures, dtype=float))
    s = np.atleast_2d(np.asarray(sigmas, dtype=float))
    c = np.asarray(corr, dtype=float)
    if c.ndim == 2:
        c = np.broadcast_to(c, (e.shape[0], *c.shape))
    es = e * s
    var = np.einsum("ni,nij,nj->n", es, c, es)
    return z * np.sqrt(np.clip(var, 0.0, None))


def corr_matrix(pairs: dict[tuple[str, str], np.ndarray], names: list[str], n: int) -> np.ndarray:
    """Assemble (n, k, k) correlation matrices from pairwise series; unit diagonal."""
    k = len(names)
    out = np.zeros((n, k, k))
    for i in range(k):
        out[:, i, i] = 1.0
    for (a, b), v in pairs.items():
        i, j = names.index(a), names.index(b)
        out[:, i, j] = v
        out[:, j, i] = v
    return out
