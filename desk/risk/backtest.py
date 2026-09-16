"""VaR backtesting: exceptions, Kupiec's proportion-of-failures test and Christoffersen's independence test.

A VaR at confidence c is *exceeded* on day t when the realised P&L is a loss larger than the VaR: `pnl_t < -VaR_t`.
Over n days with x exceptions:

* **Kupiec (1995) POF.** H0: the exception probability is p = 1 - c.
  `LR_pof = -2 ln[(1-p)^(n-x) p^x] + 2 ln[(1-x/n)^(n-x) (x/n)^x]  ~ chi2(1)`.
  It tests the *count* only, and it is weak on short samples: at n = 120 and p = 5 % it cannot reject anything
  from 2 to 11 exceptions (see `kupiec_acceptance_region`), which is why the book backtest is paired with a
  ~1,000-day constant-exposure backtest.
* **Christoffersen (1998) independence.** H0: an exception today is no more likely after an exception yesterday.
  This is the test that speaks to *clustering* — exactly what a slow volatility estimate produces and what GARCH is
  meant to remove — so it is published beside Kupiec even though the spec only names Kupiec.

`0 * ln 0` is taken as 0 throughout (scipy's `xlogy`), which is what makes x = 0 and x = n well defined.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import xlogy

TEST_SIZE = 0.05  # reject H0 when p-value < 5 %


def exceptions(pnl, var) -> np.ndarray:
    """Boolean exception flags: realised loss larger than VaR (VaR is a positive number)."""
    return np.asarray(pnl, dtype=float) < -np.asarray(var, dtype=float)


def _loglik_bernoulli(n: float, x: float, p: float) -> float:
    return float(xlogy(n - x, 1.0 - p) + xlogy(x, p))


def kupiec_pof(n: int, x: int, p: float) -> tuple[float, float]:
    """Kupiec LR statistic and chi2(1) p-value for x exceptions in n days at exception probability p."""
    if n <= 0:
        return float("nan"), float("nan")
    if not 0 <= x <= n:
        raise ValueError(f"exceptions {x} outside [0, {n}]")
    lr = -2.0 * (_loglik_bernoulli(n, x, p) - _loglik_bernoulli(n, x, x / n))
    lr = max(lr, 0.0)
    return lr, float(stats.chi2.sf(lr, 1))


def kupiec_acceptance_region(n: int, p: float, size: float = TEST_SIZE) -> tuple[int, int]:
    """Smallest and largest exception counts Kupiec does NOT reject at `size` (the test's power, in one line)."""
    ok = [x for x in range(n + 1) if kupiec_pof(n, x, p)[1] >= size]
    return (min(ok), max(ok)) if ok else (-1, -1)


def christoffersen_independence(hits) -> tuple[float, float, dict]:
    """Christoffersen LR_ind on a boolean exception sequence; returns (LR, p-value, transition counts)."""
    h = np.asarray(hits, dtype=bool).astype(int)
    if h.size < 2:
        return float("nan"), float("nan"), {}
    prev, cur = h[:-1], h[1:]
    n00 = int(np.sum((prev == 0) & (cur == 0)))
    n01 = int(np.sum((prev == 0) & (cur == 1)))
    n10 = int(np.sum((prev == 1) & (cur == 0)))
    n11 = int(np.sum((prev == 1) & (cur == 1)))
    counts = {"n00": n00, "n01": n01, "n10": n10, "n11": n11}
    tot = n00 + n01 + n10 + n11
    pi = (n01 + n11) / tot
    pi01 = n01 / (n00 + n01) if (n00 + n01) else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) else 0.0
    ll_null = xlogy(n00 + n10, 1.0 - pi) + xlogy(n01 + n11, pi)
    ll_alt = xlogy(n00, 1.0 - pi01) + xlogy(n01, pi01) + xlogy(n10, 1.0 - pi11) + xlogy(n11, pi11)
    lr = max(float(-2.0 * (ll_null - ll_alt)), 0.0)
    return lr, float(stats.chi2.sf(lr, 1)), counts


def verdict(n: int, x: int, p: float, pvalue: float, size: float = TEST_SIZE) -> str:
    if not np.isfinite(pvalue):
        return "NO DATA"
    if pvalue >= size:
        return "NOT REJECTED"
    return ("REJECTED — too many exceptions (VaR understates risk)" if x > n * p
            else "REJECTED — too few exceptions (VaR overstates risk)")


def summarise(hits: pd.Series, *, p: float, sample: str, method: str, **extra) -> dict:
    """One kupiec.csv row: counts, Kupiec POF, Christoffersen independence, acceptance region, verdict."""
    h = hits.astype(bool)
    n, x = int(h.size), int(h.sum())
    lr, pv = kupiec_pof(n, x, p)
    lr_ind, pv_ind, counts = christoffersen_independence(h.to_numpy())
    lo, hi = kupiec_acceptance_region(n, p) if n else (-1, -1)
    lr_cc = lr + lr_ind if np.isfinite(lr_ind) else float("nan")
    return {
        "sample": sample, "method": method,
        "start": h.index.min() if n else pd.NaT, "end": h.index.max() if n else pd.NaT,
        "n": n, "exceptions": x, "expected": n * p, "exception_rate_frac": x / n if n else float("nan"),
        "kupiec_lr": lr, "kupiec_pvalue": pv, "kupiec_accept_min": lo, "kupiec_accept_max": hi,
        "verdict": verdict(n, x, p, pv),
        "consecutive_exception_pairs": counts.get("n11", 0),
        "christoffersen_lr_ind": lr_ind, "christoffersen_pvalue_ind": pv_ind,
        "christoffersen_verdict_ind": ("NOT REJECTED" if pv_ind >= TEST_SIZE else "REJECTED — exceptions cluster")
        if np.isfinite(pv_ind) else "NO DATA",
        "lr_conditional_coverage": lr_cc,
        "pvalue_conditional_coverage": float(stats.chi2.sf(lr_cc, 2)) if np.isfinite(lr_cc) else float("nan"),
        **extra,
    }
