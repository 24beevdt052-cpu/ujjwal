"""The one valuation function every other module calls (design D2, §5.4).

```
Pi(ticket; C, E, M, tau) = Pi_val(C, E, M, tau) + Fund(tau)
```

* `C` **contracts-as-of** — a term is active only from its own contract / entry / booking / fixture date.
* `E` **events-as-of** — an event bites only from its `known_date`.
* `M` **market state** — the only door for dated market inputs; every field may be a numpy array.
* `tau` **the clock** — settled flows are valued at their own fixing and settle dates from history, unsettled flows
  from `M` at the clock.

`Pi_val` is pure: no files, no wall clock, no `desk.config` except through the history's parameter provider, and no
branch on a market value. `Fund` comes from the **actual dated cash path** (history only, design §4.4), which is why
it is constant across an attribution chain and is added to buckets (f) and (g) explicitly rather than swapped.

Daily MTM, attribution, exposures, counterfactuals, the five Table 6 stresses and the Monte Carlo all call this
function. Only one code path can be wrong, so a risk number can never disagree with a P&L number.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from desk import units
from desk.book import schema as bs
from desk.mtm import curves, lifecycle
from desk.mtm.lifecycle import PNL, USD, Schedule
from desk.mtm.state import MarketState

# Instrument groups used by the counterfactual books (design §8).
INSTRUMENT_OF_LEG = {
    "MCX_VARIATION_MARGIN": "mcx", "MCX_INITIAL_MARGIN": "mcx", "MCX_SLIPPAGE": "mcx",
    "MCX_TRANSACTION_COST": "mcx", "FX_FORWARD": "fx_forward",
    "FREIGHT_SWAP_HYPOTHETICAL": "freight_swap",
}


# ------------------------------------------------------------------------------------------------ schedule cache
class ScheduleCache:
    """Schedules keyed by (trade, contracts-as-of, events-as-of). Few distinct keys: C and E only move on event days."""

    def __init__(self, book: bs.Book, H, *, allow_hypothetical: bool = False,
                 drop_instruments: frozenset[str] = frozenset(),
                 drop_event_kinds: frozenset[str] = frozenset(),
                 fixtures_at_bl: bool = False) -> None:
        self.book = book
        self.H = H
        self.allow_hypothetical = allow_hypothetical
        self.drop_instruments = frozenset(drop_instruments)
        self.drop_event_kinds = frozenset(drop_event_kinds)
        self.fixtures_at_bl = fixtures_at_bl
        self._cache: dict[tuple[str, dt.date, dt.date], Schedule] = {}
        self._breaks: dict[str, tuple[tuple[dt.date, ...], tuple[dt.date, ...]]] = {}

    def _breakpoints(self, ticket: bs.Ticket) -> tuple[tuple[dt.date, ...], tuple[dt.date, ...]]:
        """The only dates at which `expand` can change answer — everything else is a plateau.

        Canonicalising `C` and `E` onto these breakpoints is an optimisation with no effect on any number: the
        expansion compares them to exactly this set of dates and to nothing else.
        """
        if ticket.trade_id in self._breaks:
            return self._breaks[ticket.trade_id]
        t = self._transform(ticket)
        contracts = {t.trade_date, t.purchase.payment.lc_open_date}
        if t.freight is not None and t.freight.fixture_date is not None:
            contracts.add(t.freight.fixture_date)
        if t.freight is not None and t.freight.swap is not None:
            contracts.add(t.freight.swap.start_date)
        contracts.update(s.contract_date for s in t.sales)
        for tr in t.hedges.mcx.tranches:
            contracts.update((tr.entry_date, tr.exit_date))
        contracts.update(f.booking_date for f in t.hedges.fx_forwards.lines)
        events = {e.known_date for e in t.events.logistics}
        events |= {e.known_date for e in t.events.buyer_payment_delay}
        # An event is effective at min(known_date, the milestone it moves), so those milestones are breakpoints too.
        for extreme in (dt.date.min, dt.date.max):
            lots = {}
            for lot in t.shipment.lots:
                ld = lifecycle.lot_dates(t, lot, extreme, self.H)
                events.update({ld.survey, ld.arrival, ld.release})
                lots[lot.lot_id] = ld
            # the contractual due date differs with and without the dwell events, and both are breakpoints
            for sale in t.sales:
                events.add(lifecycle.sale_dates(t, sale, lots, dt.date.min, self.H).due_contractual)
        self._breaks[ticket.trade_id] = (tuple(sorted(contracts)), tuple(sorted(events)))
        return self._breaks[ticket.trade_id]

    @staticmethod
    def _floor(d: dt.date, breaks: tuple[dt.date, ...]) -> dt.date:
        prior = [b for b in breaks if b <= d]
        return max(prior) if prior else dt.date.min

    def get(self, ticket: bs.Ticket, C: dt.date, E: dt.date) -> Schedule:
        cb, eb = self._breakpoints(ticket)
        C, E = self._floor(C, cb), self._floor(E, eb)
        key = (ticket.trade_id, C, E)
        sched = self._cache.get(key)
        if sched is None:
            t = self._transform(ticket)
            sched = lifecycle.expand(t, self.book, C, E, self.H, allow_hypothetical=self.allow_hypothetical)
            if self.drop_instruments:
                sched = replace(sched, flows=tuple(
                    f for f in sched.flows
                    if INSTRUMENT_OF_LEG.get(f.leg_type, "physical") not in self.drop_instruments))
            self._cache[key] = sched
        return sched

    def _transform(self, t: bs.Ticket) -> bs.Ticket:
        """Counterfactual books: drop event kinds, or move the freight fixture to the first bill of lading."""
        if self.drop_event_kinds:
            ev = t.events
            t = replace(t, events=bs.Events(
                quality=() if "quality" in self.drop_event_kinds else ev.quality,
                logistics=() if "logistics_delay" in self.drop_event_kinds else ev.logistics,
                buyer_payment_delay=() if "buyer_payment_delay" in self.drop_event_kinds else ev.buyer_payment_delay,
            ))
        if self.fixtures_at_bl and t.freight is not None and t.freight.fixture_date is not None:
            # Drop the executed fixture: `freight_rate_box` then floats to market and fixes on each lot's B/L date,
            # which is the counterfactual "what if the desk had never fixed early" (design §8, event E3 part iii).
            t = replace(t, freight=replace(t.freight, fixture_date=None, rate_usd_box=None))
        return t


# ------------------------------------------------------------------------------------------------ flow valuation
def flow_value_inr(sched: Schedule, i: int, H, M: MarketState, tau: dt.date, HV=None):
    """One flow's INR value at the clock: frozen once fixed, forward-converted while the settlement is in the future."""
    f = sched.flows[i]
    HV = H.view(tau) if HV is None else HV
    if f.fixing_date is not None and f.fixing_date < tau:
        amt = sched.frozen_amount(i, H)
    else:
        amt = f.amount(M, tau, HV)
    if f.currency == USD:
        amt = amt * curves.fx_x(HV, M, tau, f.settle_date)
    return amt


def flow_values(sched: Schedule, H, M: MarketState, tau: dt.date) -> list:
    HV = H.view(tau)
    return [flow_value_inr(sched, i, H, M, tau, HV) for i in range(len(sched.flows))]


def realised_inr(sched: Schedule, i: int, H):
    """The INR amount a flow actually settled at — evaluated once, at its own settle date, from history."""
    key = ("realised", i)
    cache = sched._frozen
    if key not in cache:
        f = sched.flows[i]
        s = f.settle_date
        cache[key] = flow_value_inr(sched, i, H, H.state_at(s), s)
    return cache[key]


# ------------------------------------------------------------------------------------------------- trade value
@dataclass(frozen=True)
class TradeValue:
    """`Pi_val` and its breakdown. Funding is added by the ledger (design §4.4), never here."""

    trade_id: str
    pi_val: Any
    per_flow: tuple
    mtm_inr: Any
    realised_pnl_inr: Any
    schedule: Schedule

    def per_leg(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f, v in zip(self.schedule.flows, self.per_flow):
            if f.pnl_class == PNL:
                out[f.leg_id] = out.get(f.leg_id, 0.0) + v
        return out


def trade_value(ticket: bs.Ticket, book: bs.Book, C: dt.date, E: dt.date, M: MarketState, tau: dt.date, H,
                cache: ScheduleCache | None = None) -> TradeValue:
    """Cumulative P&L of one ticket excluding funding, plus the per-flow breakdown.

    This is the signature Phase 4 revalues through (CONTRACTS §7a.4). It is a pure function of the ticket, the
    contracts-as-of and events-as-of dates, the market state and the clock: give it the same five and it returns the
    same number, on any machine, in any order.
    """
    cache = cache or ScheduleCache(book, H)
    sched = cache.get(ticket, C, E)
    vals = flow_values(sched, H, M, tau)
    pi = 0.0
    mtm = 0.0
    realised = 0.0
    for f, v in zip(sched.flows, vals):
        if f.pnl_class != PNL:
            continue
        pi = pi + v
        if f.settle_date is not None and f.settle_date <= tau:
            realised = realised + v
        else:
            mtm = mtm + v
    return TradeValue(ticket.trade_id, pi, tuple(vals), mtm, realised, sched)


# ------------------------------------------------------------------------------------------------------ funding
@dataclass
class FundingPath:
    """The dated cash path of one trade and the interest it accrues (design §4.4, CONTRACTS §7a.5)."""

    days: tuple[dt.date, ...]
    cash_balance: dict[dt.date, float] = field(default_factory=dict)
    accrual: dict[dt.date, float] = field(default_factory=dict)
    accrual_overdue: dict[dt.date, float] = field(default_factory=dict)
    accrual_carry: dict[dt.date, float] = field(default_factory=dict)
    cum_funding: dict[dt.date, float] = field(default_factory=dict)
    realised_pnl_cum: dict[dt.date, float] = field(default_factory=dict)
    bs_cum: dict[dt.date, float] = field(default_factory=dict)
    overdue_inr: dict[dt.date, float] = field(default_factory=dict)
    days_past_due: dict[dt.date, int] = field(default_factory=dict)


def funding_path(sched: Schedule, H, days: Sequence[dt.date]) -> FundingPath:
    """Walk the trade's own cash line day by day: every settled flow, then interest on yesterday's balance.

    The rate is symmetric — the desk runs one always-drawn cash-credit line, so a positive balance reduces drawings
    at the same rate. That is what makes trade-level funding add exactly to desk-level funding.
    """
    out = FundingPath(tuple(days))
    settles: dict[dt.date, list[int]] = {}
    for i, f in enumerate(sched.flows):
        if f.settle_date is not None:
            settles.setdefault(f.settle_date, []).append(i)

    receivables = [(i, sched.sale_dates[sched.flows[i].sale_id].due_contractual, sched.flows[i].settle_date)
                   for i, f in enumerate(sched.flows)
                   if f.sale_id and f.settle_date is not None and realised_inr(sched, i, H) > 0]

    close = sched.close_date
    balance = 0.0
    realised_pnl = 0.0
    bs_cum = 0.0
    cum_fund = 0.0
    prev: dt.date | None = None
    for d in days:
        if prev is not None and d <= close:
            overdue = sum(realised_inr(sched, i, H) for i, due_c, settle in receivables if due_c <= prev < settle)
            rate = H.wc_rate(prev)
            dcount = (d - prev).days / units.DAY_COUNT_INR
            acc = balance * rate * dcount
            acc_over = -overdue * rate * dcount
            out.overdue_inr[d] = overdue
            out.days_past_due[d] = max(
                [0] + [(prev - due_c).days for i, due_c, settle in receivables if due_c <= prev < settle])
        else:
            acc = acc_over = 0.0
            out.overdue_inr[d] = 0.0
            out.days_past_due[d] = 0
        cum_fund += acc
        out.accrual[d] = acc
        out.accrual_overdue[d] = acc_over
        out.accrual_carry[d] = acc - acc_over
        out.cum_funding[d] = cum_fund

        for i in settles.get(d, ()):
            v = realised_inr(sched, i, H)
            balance += v
            if sched.flows[i].pnl_class == PNL:
                realised_pnl += v
            else:
                bs_cum += v
        out.cash_balance[d] = balance
        out.realised_pnl_cum[d] = realised_pnl
        out.bs_cum[d] = bs_cum
        prev = d
    return out


# -------------------------------------------------------------------------------------- Phase 4 revaluation API
@dataclass(frozen=True)
class StressEvent:
    """A stress accepted **only** through `revalue_book` — never from `trades.yaml` (CONTRACTS §7a.4)."""

    kind: str                       # "buyer_default" | "qco_hold"
    buyer_id: str = ""
    recovery_frac: float = 0.0
    delay_days: int = 0
    rejection_frac: float = 0.0
    rejected_loss_frac: float = 0.0


SHOCK_KEYS = ("lme_cash_logret", "usdinr_logret", "freight_logret", "freight_JEA_NSA_logret",
              "freight_USEC_MUN_logret", "lme_spread_abs", "grade_factor_abs", "mcx_basis_abs")


def shock_state(M: MarketState, shocks: Mapping[str, Any] | None, *, mcx_hold_basis: bool = True) -> MarketState:
    """Apply Monte Carlo / scenario shocks to one state. MCX is recomputed from the shocked cash and FX."""
    if not shocks:
        return M
    unknown = set(shocks) - set(SHOCK_KEYS)
    if unknown:
        raise KeyError(f"unknown shock keys {sorted(unknown)}; allowed {SHOCK_KEYS}")
    new: dict[str, Any] = {}
    if "lme_cash_logret" in shocks:
        new["lme_cash_usd_t"] = M.lme_cash_usd_t * np.exp(shocks["lme_cash_logret"])
    if "usdinr_logret" in shocks:
        new["usdinr"] = M.usdinr * np.exp(shocks["usdinr_logret"])
        # the CBIC notified rate tracks the market with the registered markup, so a stress moves both
        new["customs_usdinr_import"] = M.customs_usdinr_import * np.exp(shocks["usdinr_logret"])
    freight = dict(M.freight_usd_t)
    for lane in freight:
        key = f"freight_{lane}_logret"
        r = shocks.get(key, shocks.get("freight_logret"))
        if r is not None:
            freight[lane] = freight[lane] * np.exp(r)
    if freight != M.freight_usd_t:
        new["freight_usd_t"] = freight
    if "lme_spread_abs" in shocks:
        new["lme_spread_usd_t"] = M.lme_spread_usd_t + shocks["lme_spread_abs"]
    if "grade_factor_abs" in shocks:
        new["grade_factor_frac"] = {g: v + shocks["grade_factor_abs"] for g, v in M.grade_factor_frac.items()}
    if not mcx_hold_basis and "mcx_basis_abs" in shocks:
        new["mcx_basis_inr_kg"] = {m: v + shocks["mcx_basis_abs"] for m, v in M.mcx_basis_inr_kg.items()}
    return replace(M, **new) if new else M


def revalue_book(book: bs.Book, H, t: dt.date, shocks: Mapping[str, Any] | None = None,
                 extra_events: Iterable[StressEvent] = (), mcx_hold_basis: bool = True,
                 cache: ScheduleCache | None = None, funding: Mapping[str, float] | None = None) -> np.ndarray:
    """Instantaneous full revaluation at clock `t` (contracts and events as of `t`); shape `(n_trades, n_paths)`.

    `shocks` may hold scalars or equal-length numpy arrays: `'lme_cash_logret'`, `'usdinr_logret'`,
    `'freight_logret'` or `'freight_<lane>_logret'`, and optionally `'lme_spread_abs'`, `'grade_factor_abs'`,
    `'mcx_basis_abs'`. MCX is recomputed from the shocked cash and FX with the basis **held**, so a hedge moves
    consistently with the physical it hedges.

    The clock is held: a one-day carry is deterministic, and advancing it would need history beyond `t`, which is
    look-ahead. `funding` (trade_id → accrued funding to `t`) is added when supplied; it is a history-only number
    and is unaffected by the shocks.
    """
    cache = cache or ScheduleCache(book, H)
    M = shock_state(H.state_at(t), shocks, mcx_hold_basis=mcx_hold_basis)
    events = tuple(extra_events)
    rows = []
    for ticket in book.trades:
        if ticket.trade_date > t:
            rows.append(np.asarray(0.0))
            continue
        tv = trade_value(ticket, book, t, t, M, t, H, cache)
        v = tv.pi_val
        if funding:
            v = v + funding.get(ticket.trade_id, 0.0)
        for ev in events:
            v = v + _stress_adjustment(ev, ticket, tv, H, M, t)
        rows.append(np.asarray(v, dtype=float))
    if not rows:
        return np.zeros((0, 1))
    shape = np.broadcast_shapes(*(r.shape for r in rows))
    n_paths = int(np.prod(shape)) if shape else 1
    return np.stack([np.broadcast_to(r, shape).reshape(n_paths) for r in rows])


def _stress_adjustment(ev: StressEvent, ticket: bs.Ticket, tv: TradeValue, H, M: MarketState, t: dt.date):
    """Table 6 row 4.2 stresses that cannot be expressed as a market shock (buyer default, BIS-QCO hold)."""
    sched = tv.schedule
    if ev.kind == "buyer_default":
        loss = 0.0
        for f, v in zip(sched.flows, tv.per_flow):
            if f.counterparty_id == ev.buyer_id and f.settle_date is not None and f.settle_date > t:
                loss = loss + v * (1.0 - ev.recovery_frac)
        return -loss
    if ev.kind == "qco_hold":
        # extra dwell on every box still in the desk's hands, plus a write-off on the rejected fraction
        rate = float(H.param("demurrage_usd_per_box_day", t))
        boxes = sum(q.boxes for q in sched.quantities.values())
        demurrage = -boxes * ev.delay_days * rate * M.usdinr
        unsold = sum(f.qty_mt for f in sched.flows if f.leg_type == "INVENTORY_MARK")
        exposure = unsold if unsold else ticket.quantity_mt
        box = lifecycle.LANE_BOX[ticket.lane.value]
        rep = curves.replacement_value(H.view(t), M, t, ticket.grade.value, ticket.lane.value, box)
        return demurrage - exposure * ev.rejection_frac * ev.rejected_loss_frac * rep
    raise KeyError(f"unknown stress event kind {ev.kind!r}")
