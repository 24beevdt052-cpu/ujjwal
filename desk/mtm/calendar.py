"""Panel-calendar arithmetic for the MTM engine (design §4.1 date rules, D4b contract months).

Everything the engine does with dates goes through here so that two rules are true everywhere:

* **Decision dates are never silently rolled.** A ticket's dates are LME trading days already (schema V04). Only
  *derived* cashflow dates roll, and they roll **following** — `roll(x)` is the first panel day on or after `x`.
  Each milestone rolls independently from its own calendar date, so a rolled arrival never drags the Bill of Entry
  with it (design §4.1).
* **MCX positions key on a contract month, not an expiry date** (design D4b). The panel's contract calendar uses a
  last-calendar-day rule (so the August-2022 slot is 31-Aug) while the DIRECT `mcx_al_expiry_dates_2022` list says
  30-Aug. Both are views of contract month ``2022-08``: prices come from the panel slot, roll deadlines from the
  DIRECT list. `desk.data.mcx.month_expiry` is reused rather than re-derived so the panel slot can never drift.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache

import pandas as pd

from desk import config
from desk.data import mcx as mcx_data
from desk.mtm.constants import LME_CURVE_TENOR_MONTHS


def to_date(x) -> dt.date:
    return x if type(x) is dt.date else pd.Timestamp(x).date()


class PanelCalendar:
    """The LME trading days of `market_daily.csv`, with following-roll and month helpers."""

    def __init__(self, days) -> None:
        self.days: tuple[dt.date, ...] = tuple(sorted(to_date(d) for d in days))
        self._index = {d: i for i, d in enumerate(self.days)}
        self._set = set(self.days)
        self._ts = pd.DatetimeIndex([pd.Timestamp(d) for d in self.days])
        self._expiry: dict[str, dt.date] = {}
        self._m1: dict[dt.date, pd.Period] = {}
        self._month_days: dict[str, tuple[dt.date, ...]] = {}
        self._tenor: dict[tuple[dt.date, int], int] = {}
        self._between: dict[tuple[dt.date, dt.date], tuple[dt.date, ...]] = {}

    # ------------------------------------------------------------------------------------------------ membership
    def __contains__(self, d) -> bool:
        return to_date(d) in self._set

    def __len__(self) -> int:
        return len(self.days)

    @property
    def first(self) -> dt.date:
        return self.days[0]

    @property
    def last(self) -> dt.date:
        return self.days[-1]

    def position(self, d) -> int:
        d = to_date(d)
        if d not in self._index:
            raise KeyError(f"{d} is not an LME panel day")
        return self._index[d]

    # ----------------------------------------------------------------------------------------------------- rolls
    def roll(self, d) -> dt.date:
        """First panel day on or after `d` (derived cashflow dates roll FOLLOWING; design §4.1)."""
        d = to_date(d)
        if d in self._set:
            return d
        i = self._ts.searchsorted(pd.Timestamp(d), side="left")
        if i >= len(self.days):
            raise ValueError(f"{d} rolls past the end of the panel ({self.last})")
        return self.days[i]

    def roll_back(self, d) -> dt.date:
        """Last panel day on or before `d` (used for point-in-time look-ups, never for cashflow dates)."""
        d = to_date(d)
        if d in self._set:
            return d
        i = self._ts.searchsorted(pd.Timestamp(d), side="right") - 1
        if i < 0:
            raise ValueError(f"{d} is before the start of the panel ({self.first})")
        return self.days[i]

    def shift(self, d, n: int) -> dt.date:
        """`n` panel days after the panel day on or after `d` (n may be negative)."""
        i = self.position(self.roll(d)) + n
        if not 0 <= i < len(self.days):
            raise ValueError(f"{d} shifted by {n} panel days falls outside the panel")
        return self.days[i]

    def prev(self, d) -> dt.date:
        return self.shift(d, -1)

    def next(self, d) -> dt.date:
        return self.shift(d, 1)

    def between(self, start, end) -> tuple[dt.date, ...]:
        """Panel days in the inclusive range [start, end]."""
        a, b = to_date(start), to_date(end)
        key = (a, b)
        if key not in self._between:
            i = self._ts.searchsorted(pd.Timestamp(a), side="left")
            j = self._ts.searchsorted(pd.Timestamp(b), side="right")
            self._between[key] = self.days[i:j]
        return self._between[key]

    def month_days(self, month) -> tuple[dt.date, ...]:
        """Panel days of a calendar month — the LME fixing days of an M+1 quotational period."""
        key = str(month)
        if key not in self._month_days:
            m = pd.Period(key, freq="M")
            self._month_days[key] = tuple(d for d in self.days if d.year == m.year and d.month == m.month)
        return self._month_days[key]

    def tenor_days(self, d, months: int = LME_CURVE_TENOR_MONTHS) -> int:
        """Calendar days from `d` to `d + months` — the denominator of the curve interpolation weight."""
        d = to_date(d)
        key = (d, months)
        if key not in self._tenor:
            ts = pd.Timestamp(d)
            self._tenor[key] = int(((ts + pd.DateOffset(months=months)) - ts).days)
        return self._tenor[key]

    # --------------------------------------------------------------------------------------------------- MCX (D4b)
    def mcx_panel_expiry(self, month) -> dt.date:
        """The panel's expiry slot for a contract month (`desk.data.mcx.month_expiry`, reused not re-derived)."""
        key = str(month)
        if key not in self._expiry:
            self._expiry[key] = to_date(mcx_data.month_expiry(pd.Period(key, freq="M"), self._ts))
        return self._expiry[key]

    def m1_month_on(self, d) -> pd.Period:
        """Contract month in the M1 slot on panel day `d` (M1 is the current month up to and including its expiry)."""
        d = to_date(d)
        if d not in self._m1:
            cur = pd.Period(f"{d.year}-{d.month:02d}", freq="M")
            self._m1[d] = cur if d <= self.mcx_panel_expiry(cur) else cur + 1
        return self._m1[d]

    def mcx_slot(self, d, month: pd.Period | str) -> str | None:
        """'m1' / 'm2' when `month` is a listed slot on day `d`, else None (the caller extrapolates; design §11)."""
        m = pd.Period(str(month), freq="M")
        m1 = self.m1_month_on(d)
        if m == m1:
            return "m1"
        if m == m1 + 1:
            return "m2"
        return None


@lru_cache(maxsize=1)
def _direct_expiries() -> dict[str, dt.date]:
    """exchange.yaml `mcx_al_expiry_dates_2022` (DIRECT) keyed by contract month."""
    out: dict[str, dt.date] = {}
    for raw in config.value("mcx_al_expiry_dates_2022"):
        d = to_date(raw)
        out[f"{d.year}-{d.month:02d}"] = d
    return out


def mcx_direct_expiry(month: pd.Period | str) -> dt.date | None:
    """The exchange's published expiry for a contract month, or None outside the DIRECT list."""
    return _direct_expiries().get(str(pd.Period(str(month), freq="M")))


def mcx_roll_deadline(cal: PanelCalendar, month: pd.Period | str) -> dt.date:
    """`mcx_roll_days_before_expiry` panel days before the **DIRECT** expiry (panel slot when the month is unlisted).

    Positions roll before the tender period opens (design §11: MCX aluminium is compulsory delivery).
    """
    n = int(config.value("mcx_roll_days_before_expiry"))
    direct = mcx_direct_expiry(month)
    expiry = direct if direct is not None else cal.mcx_panel_expiry(month)
    return cal.shift(cal.roll_back(expiry), -n)
