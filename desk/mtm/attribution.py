"""Daily P&L attribution by sequential block swap (design §6, CONTRACTS §7.4 and §7a.1).

The chain, per trade, per panel day — each step swaps **one** block of the market state from yesterday's value to
today's and revalues the whole ticket:

| step | bucket | what is swapped |
|---|---|---|
| 0 | — | `V0 = Pi_val(C(t-), E(t-), M(t-), tau = t-)` |
| 1 | `lme_flat` | `lme_cash_usd_t` — the spread is held, so the whole curve shifts in parallel |
| 2 | `cross_exchange_basis` | the MCX basis and the domestic premium |
| 3 | `grade_spread` | the grade factors |
| 4 | `freight` | both lane freight levels |
| 5 | `fx` | `usdinr` and the CBIC notified rate |
| 6 | `demurrage_penalty` | **events-as-of**, plus the overdue-receivable funding accrual |
| 7 | `roll_term_structure` | cash-3M, the three rates, **the clock**, plus the carry accrual and `ROLL` bookings |
| 8 | `new_deal` | **contracts-as-of** — every other booking dated today, valued at the day's close |

`new_deal` is computed **last** and reported **first**, so a new contract is valued at today's closing market with no
factor cross-terms. Every cross-term (ΔLME × ΔFX and friends) lands in the factor swapped **later**, which is the
convention CONTRACTS §7.4 fixes and §12 of the design doc states plainly in the "doesn't tell you" paragraph.

**The residual is a control, not arithmetic hygiene** (design D9). The day's total is computed *independently* from
the cash ledger — `Δ[realised P&L + funding + Σ mtm]` — while the buckets come from the chain. They agree only if the
valuation has no hidden input: a parameter read at a date other than the clock, history read beyond the clock,
contract logic touching the wall calendar, or a realised amount that the estimate does not converge to at settlement.
Any of those shows up as a non-zero residual, and `|residual| <= ₹1` per trade-day is therefore a real sign-off.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Mapping

from desk.book import schema as bs
from desk.mtm import valuation as val
from desk.mtm.lifecycle import PNL, ROLL, Schedule
from desk.mtm.state import BLOCKS, swap
from desk.reporting.style import FACTOR_ORDER, PNL_BUCKETS

FUNDING_LEG = "FUNDING"


@dataclass
class DayAttribution:
    """One trade, one day: buckets at leg grain, the ledger totals and the control residual."""

    trade_id: str
    date: dt.date
    prev_date: dt.date
    legs: dict[str, dict[str, float]] = field(default_factory=dict)   # leg_id -> bucket -> ₹
    daily_pnl_inr: float = 0.0
    cum_pnl_inr: float = 0.0
    residual_inr: float = 0.0
    mtm_inr: float = 0.0
    realised_cum_inr: float = 0.0
    funding_cum_inr: float = 0.0
    cash_balance_inr: float = 0.0
    v0_inr: float = 0.0
    value_today: val.TradeValue | None = None
    schedule_today: Schedule | None = None

    def totals(self) -> dict[str, float]:
        out = {b: 0.0 for b in PNL_BUCKETS}
        for buckets in self.legs.values():
            for b, v in buckets.items():
                out[b] += v
        return out

    def bucket(self, leg_id: str, name: str, amount: float) -> None:
        if amount == 0.0:
            return
        self.legs.setdefault(leg_id, {})[name] = self.legs.setdefault(leg_id, {}).get(name, 0.0) + amount


def _leg_values(tv: val.TradeValue) -> dict[str, float]:
    """Π_val split by leg (P&L flows only — balance-sheet flows are cash, never P&L)."""
    out: dict[str, float] = {}
    for f, v in zip(tv.schedule.flows, tv.per_flow):
        if f.pnl_class == PNL:
            out[f.leg_id] = out.get(f.leg_id, 0.0) + v
    return out


def _diff(after: Mapping[str, float], before: Mapping[str, float]) -> dict[str, float]:
    """Per-leg step delta, in **sorted** leg order.

    The sort is not cosmetic. Set iteration order over strings depends on `PYTHONHASHSEED`, so an unsorted union
    would change the order in which per-leg floats are summed, which changes the last bit of the residual and
    flips `0.0` to `-0.0` in the CSV. CONTRACTS §1.5 asks for byte-identical re-runs.
    """
    keys = sorted(set(after) | set(before))
    return {k: after.get(k, 0.0) - before.get(k, 0.0) for k in keys}


def attribute_day(ticket: bs.Ticket, book: bs.Book, t: dt.date, t_prev: dt.date, H,
                  cache: val.ScheduleCache, fp_today: val.FundingPath,
                  prev_state: "DayState | None" = None) -> tuple[DayAttribution, "DayState"]:
    """Run the eight-step chain for one ticket on one panel day."""
    M_prev, M_now = H.state_at(t_prev), H.state_at(t)
    att = DayAttribution(ticket.trade_id, t, t_prev)

    # step 0 — yesterday's state, yesterday's contracts, yesterday's events, yesterday's clock
    tv0 = val.trade_value(ticket, book, t_prev, t_prev, M_prev, t_prev, H, cache)
    L = _leg_values(tv0)
    att.v0_inr = tv0.pi_val

    # steps 1-5 — one market block at a time, clock and contracts held at t-
    M = M_prev
    for bucket in ("lme_flat", "cross_exchange_basis", "grade_spread", "freight", "fx"):
        M = swap(M, M_now, bucket)
        tv = val.trade_value(ticket, book, t_prev, t_prev, M, t_prev, H, cache)
        nxt = _leg_values(tv)
        for leg, d in _diff(nxt, L).items():
            att.bucket(leg, bucket, d)
        L = nxt

    # step 6 — events become known (design D7); the overdue funding accrual joins them
    tv6 = val.trade_value(ticket, book, t_prev, t, M, t_prev, H, cache)
    nxt = _leg_values(tv6)
    for leg, d in _diff(nxt, L).items():
        att.bucket(leg, "demurrage_penalty", d)
    L = nxt
    att.bucket(FUNDING_LEG, "demurrage_penalty", fp_today.accrual_overdue.get(t, 0.0))

    # step 7 — term structure, rates and THE CLOCK; carry accrual; ROLL bookings are added after step 8
    M = swap(M, M_now, "roll_term_structure")
    tv7 = val.trade_value(ticket, book, t_prev, t, M, t, H, cache)
    nxt = _leg_values(tv7)
    for leg, d in _diff(nxt, L).items():
        att.bucket(leg, "roll_term_structure", d)
    L = nxt
    att.bucket(FUNDING_LEG, "roll_term_structure", fp_today.accrual_carry.get(t, 0.0))

    # step 8 — contracts-as-of. A booking made with purpose ROLL routes to (g) (design D8c): a roll at settle is
    # value-neutral, so (g) receives exactly the roll's execution cost, which is what "roll yield" means.
    tv8 = val.trade_value(ticket, book, t, t, M_now, t, H, cache)
    nxt = _leg_values(tv8)
    roll_today: dict[str, float] = {}
    for f, v in zip(tv8.schedule.flows, tv8.per_flow):
        if f.pnl_class == PNL and f.purpose == ROLL and f.contract_date == t:
            roll_today[f.leg_id] = roll_today.get(f.leg_id, 0.0) + v
    for leg, d in _diff(nxt, L).items():
        r = roll_today.get(leg, 0.0)
        att.bucket(leg, "roll_term_structure", r)
        att.bucket(leg, "new_deal", d - r)

    att.value_today = tv8
    att.schedule_today = tv8.schedule
    att.mtm_inr = tv8.mtm_inr
    att.realised_cum_inr = fp_today.realised_pnl_cum.get(t, 0.0)
    att.funding_cum_inr = fp_today.cum_funding.get(t, 0.0)
    att.cash_balance_inr = fp_today.cash_balance.get(t, 0.0)
    att.cum_pnl_inr = att.realised_cum_inr + att.funding_cum_inr + att.mtm_inr

    prev_cum = prev_state.cum_pnl_inr if prev_state is not None else 0.0
    att.daily_pnl_inr = att.cum_pnl_inr - prev_cum
    att.residual_inr = att.daily_pnl_inr - sum(att.totals().values())
    return att, DayState(att.cum_pnl_inr, tv8.pi_val)


@dataclass(frozen=True)
class DayState:
    """What the next day needs from this one: the cumulative P&L and the chain's end point `V8`."""

    cum_pnl_inr: float
    pi_val_inr: float


def bucket_frame_row(att: DayAttribution, in_window: bool) -> dict:
    """One `attribution_daily.csv` row."""
    row = {"date": att.date, "in_window": in_window, "trade_id": att.trade_id}
    row.update(att.totals())
    row["residual"] = att.residual_inr
    row["daily_pnl_inr"] = att.daily_pnl_inr
    row["cum_pnl_inr"] = att.cum_pnl_inr
    return row


def leg_rows(att: DayAttribution, in_window: bool) -> list[dict]:
    """`attribution_leg_daily.csv` rows — Σ legs equals the trade row exactly, by construction."""
    out = []
    for leg_id, buckets in sorted(att.legs.items()):
        row = {"date": att.date, "in_window": in_window, "trade_id": att.trade_id, "leg_id": leg_id}
        for b in PNL_BUCKETS:
            row[b] = buckets.get(b, 0.0)
        row["daily_pnl_inr"] = sum(buckets.get(b, 0.0) for b in PNL_BUCKETS)
        out.append(row)
    return out


assert list(PNL_BUCKETS) == ["new_deal"] + list(FACTOR_ORDER)
assert set(BLOCKS) == set(FACTOR_ORDER)
