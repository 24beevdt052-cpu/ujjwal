"""The market state vector and the seven attribution blocks (design §5.1, §6.1).

`MarketState` is the **only door** through which a dated market input reaches the valuation. That is what makes the
attribution exhaustive: if every market number the engine reads is a field of this dataclass, and every field belongs
to exactly one block of `FACTOR_ORDER`, then swapping the blocks one at a time from yesterday's state to today's
must reproduce the whole day's P&L. Anything left over is the residual, and the residual is a control
(CONTRACTS §7.2, design D9).

Every float may be a numpy array: Phase 4 broadcasts the whole Monte Carlo through the same valuation.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Mapping

from desk.reporting.style import FACTOR_ORDER


@dataclass(frozen=True)
class MarketState:
    """Dated market inputs at one clock. Scalars, or numpy arrays of equal shape for vectorised revaluation."""

    lme_cash_usd_t: Any                              # (a) lme_flat
    lme_spread_usd_t: Any                            # (g) cash - 3M; panel sign: + = backwardation
    mcx_basis_inr_kg: Mapping[str, Any]              # (b) keyed by contract month "YYYY-MM"
    mcx_domestic_premium_inr_kg: Any                 # (b)
    grade_factor_frac: Mapping[str, Any]             # (c)
    freight_usd_t: Mapping[str, Any]                 # (d) per lane, at BASE payload (panel units)
    usdinr: Any                                      # (e)
    customs_usdinr_import: Any                       # (e) CBIC notified rate in force
    inr_rate_3m_pa: Any                              # (g)
    usd_rate_3m_pa: Any                              # (g)
    wc_rate_inr_pa: Any                              # (g)
    asof: dt.date = None                             # memo only; valuation never reads it

    def lme_3m_usd_t(self) -> Any:
        """The 3-month price implied by the panel's cash and cash-3M spread."""
        return self.lme_cash_usd_t - self.lme_spread_usd_t


# Block -> the MarketState fields swapped at that step of the chain (design §6.1). The clock, the events-as-of date
# and the contracts-as-of date are swapped alongside (g), (f) and `new_deal` respectively and are NOT fields here.
BLOCKS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "lme_flat": ("lme_cash_usd_t",),
    "cross_exchange_basis": ("mcx_basis_inr_kg", "mcx_domestic_premium_inr_kg"),
    "grade_spread": ("grade_factor_frac",),
    "freight": ("freight_usd_t",),
    "fx": ("usdinr", "customs_usdinr_import"),
    "demurrage_penalty": (),                          # the events-as-of date, plus the overdue funding accrual
    "roll_term_structure": ("lme_spread_usd_t", "inr_rate_3m_pa", "usd_rate_3m_pa", "wc_rate_inr_pa"),
})

_ASSIGNED = {f for fields in BLOCKS.values() for f in fields}
_UNASSIGNED = {f for f in MarketState.__dataclass_fields__ if f != "asof"} - _ASSIGNED
if _UNASSIGNED:  # design §5.1: an unassigned dated input would leak into the residual
    raise AssertionError(f"MarketState fields not assigned to an attribution block: {sorted(_UNASSIGNED)}")
if list(BLOCKS) != list(FACTOR_ORDER):
    raise AssertionError(f"BLOCKS order {list(BLOCKS)} must equal desk.reporting.style.FACTOR_ORDER {FACTOR_ORDER}")


def swap(base: MarketState, new: MarketState, block: str) -> MarketState:
    """`base` with the fields of one block taken from `new` — one step of the attribution chain."""
    fields = BLOCKS[block]
    if not fields:
        return base
    return replace(base, **{f: getattr(new, f) for f in fields})


def shocked(state: MarketState, **fields: Any) -> MarketState:
    """A copy with named fields replaced — the only way exposures and stresses perturb the state."""
    return replace(state, **fields)
