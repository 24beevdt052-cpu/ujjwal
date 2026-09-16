"""`MarketHistory` — the point-in-time-guarded panel reader that builds `MarketState` (design §5.1, D10).

Why a guard rather than a convention. CONTRACTS §1.2 forbids hindsight in a trade decision, and design D10 makes the
rule executable: every accessor takes its clock from a `view(tau)` and **raises** `LookaheadError` when asked for a
date beyond it. A rule that is only written down gets broken; a rule that raises does not.

What this module decides:

* **Basis extraction (D4).** On a `PROXY_IMPORT_PARITY` day the panel MCX price *is* the duty-parity formula, so the
  cross-exchange basis is zero **by construction** — and the builder asserts the theoretical price replicates the
  panel column to `MCX_PROXY_REPLICATION_TOL_INR_KG` before it says so. On a MANUAL (bhavcopy) day the basis is the
  real residual `panel - theo`. This is what stops a proxy series manufacturing fake basis on every hedged day: an
  LME move must reach an MCX hedge through (a), FX through (e) and carry through (g).
* **The MCX source switch (CONTRACTS §7.5).** `mcx_source="mirror"` swaps in the third-party mirror
  (`data/interim/mcx_thirdparty_*.csv`, PROXY) on the LME calendar with a point-in-time carry of at most
  `MAX_FILL_BDAYS`; longer gaps raise. Mirror runs are a basis **sensitivity** and are never base P&L.
* **Grade factors (D13).** `grade_source="base"` reads `grade_factor_<g>`; `grade_source="pit"` rebuilds them from
  `grade_factor_mix_pit + grade_factor_diff_<g>`, the variant that a 2022 desk could actually have known. The
  variant is applied to contract terms *and* marks together, never mixed.
* **The customs notified rate** comes from `desk.parity.model.customs_fx`, not a second implementation, so the
  Phase 3 duty base and the Phase 1 parity duty base can never disagree.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from typing import Callable, Iterable, Mapping

import numpy as np
import pandas as pd

from desk import MAX_FILL_BDAYS, config
from desk.data import mcx as mcx_data
from desk.mtm.calendar import PanelCalendar, to_date
from desk.mtm.constants import MCX_PROXY_REPLICATION_TOL_INR_KG, param
from desk.mtm.state import MarketState
from desk.parity import model as parity_model
from desk.paths import PROCESSED_DIR

PANEL_CSV = PROCESSED_DIR / "market_daily.csv"
MIRROR_CSV = mcx_data.THIRDPARTY_CSV

GRADES = ("zorba", "taint_tabor", "tense")
LANES = ("JEA_NSA", "USEC_MUN")
LANE_FREIGHT_COL = {"JEA_NSA": "freight_jea_nsa_usd_t", "USEC_MUN": "freight_usec_mun_usd_t"}
LANE_BOX = {"JEA_NSA": "20ft", "USEC_MUN": "40ft"}

MCX_SOURCES = ("panel", "mirror")
GRADE_SOURCES = ("base", "pit")

ParamProvider = Callable[[str, dt.date | None], object]
_MISS = object()


class LookaheadError(RuntimeError):
    """An accessor was asked for a date beyond the clock (design D10)."""


@lru_cache(maxsize=4096)
def _duty_uplift(d: dt.date) -> float:
    """1 + BCD(primary) x (1 + SWS) — the duty-paid parity uplift MCX trades at."""
    return 1.0 + float(config.value("bcd_primary_al_hs7601", d)) * (1.0 + float(config.value("sws_rate_on_bcd", d)))


class MarketHistory:
    """The panel, the register and the contract calendar behind one point-in-time interface."""

    def __init__(self, panel: pd.DataFrame | None = None, *, mcx_source: str = "panel",
                 grade_source: str = "base", params: ParamProvider = param) -> None:
        if mcx_source not in MCX_SOURCES:
            raise ValueError(f"mcx_source must be one of {MCX_SOURCES}, got {mcx_source!r}")
        if grade_source not in GRADE_SOURCES:
            raise ValueError(f"grade_source must be one of {GRADE_SOURCES}, got {grade_source!r}")
        self.mcx_source = mcx_source
        self.grade_source = grade_source
        self.params = params
        self._param_cache: dict[tuple, object] = {}
        panel = load_panel() if panel is None else panel
        self.panel = panel.copy()
        self.panel["date"] = pd.to_datetime(self.panel["date"])
        self.panel = self.panel.sort_values("date").reset_index(drop=True)
        self.cal = PanelCalendar(self.panel["date"])
        self._rows: dict[dt.date, pd.Series] = {to_date(r.date): r for r in self.panel.itertuples(index=False)}
        self._customs = self._build_customs()
        self._mcx = self._build_mcx()
        self._grade = self._build_grade_factors()
        self._states: dict[dt.date, MarketState] = {}

    # ------------------------------------------------------------------------------------------------ builders
    def _build_customs(self) -> dict[dt.date, float]:
        rates, _src = parity_model.customs_fx(self.panel["date"], self.panel["usdinr"])
        return {to_date(d): float(r) for d, r in zip(self.panel["date"], rates)}

    def _build_grade_factors(self) -> dict[dt.date, dict[str, float]]:
        dates = [to_date(d) for d in self.panel["date"]]
        if self.grade_source == "base":
            paths = {g: [float(config.value(f"grade_factor_{g}", d)) for d in dates] for g in GRADES}
        else:  # D13: the point-in-time mix plus each grade's registered differential
            mix = [float(config.value("grade_factor_mix_pit", d)) for d in dates]
            paths = {g: [m + float(config.value(f"grade_factor_diff_{g}", d)) for m, d in zip(mix, dates)]
                     for g in GRADES}
        return {d: {g: paths[g][i] for g in GRADES} for i, d in enumerate(dates)}

    def _mirror_series(self) -> pd.DataFrame:
        """Third-party mirror carried point-in-time onto the LME calendar; a gap beyond MAX_FILL_BDAYS raises."""
        if not MIRROR_CSV.exists():
            raise FileNotFoundError(f"{MIRROR_CSV} missing — mcx_source='mirror' needs the P0 mirror extract")
        mir = pd.read_csv(MIRROR_CSV, parse_dates=["date"]).set_index("date").sort_index()
        out = {}
        for d in self.panel["date"]:
            hist = mir.loc[:d]
            if hist.empty:
                raise ValueError(f"mirror has no observation on or before {to_date(d)}")
            src_day = hist.index[-1]
            gap = int(np.busday_count(src_day.date(), d.date()))
            if gap > MAX_FILL_BDAYS:
                raise ValueError(f"mirror gap of {gap} business days at {to_date(d)} exceeds MAX_FILL_BDAYS")
            out[to_date(d)] = (float(hist["m1_close_inr_kg"].iloc[-1]), float(hist["m2_close_inr_kg"].iloc[-1]),
                               gap > 0)
        return out

    def _build_mcx(self) -> dict[dt.date, dict]:
        """Per panel day: the two listed contract months, their observed prices and the extracted basis."""
        mirror = self._mirror_series() if self.mcx_source == "mirror" else None
        out: dict[dt.date, dict] = {}
        worst = 0.0
        for row in self.panel.itertuples(index=False):
            d = to_date(row.date)
            m1_month = self.cal.m1_month_on(d)
            m2_month = m1_month + 1
            theo1 = self._theo(d, float(row.lme_cash_usd_t), float(row.usdinr), float(row.inr_rate_3m_pa), m1_month)
            theo2 = self._theo(d, float(row.lme_cash_usd_t), float(row.usdinr), float(row.inr_rate_3m_pa), m2_month)
            if mirror is not None:
                px1, px2, filled = mirror[d]
                src, basis1, basis2 = "MIRROR", px1 - theo1, px2 - theo2
            else:
                px1, px2, filled = float(row.mcx_al_m1_inr_kg), float(row.mcx_al_m2_inr_kg), False
                src = str(row.mcx_src)
                if src == mcx_data.SRC_PROXY:
                    worst = max(worst, abs(px1 - theo1), abs(px2 - theo2))
                    basis1 = basis2 = 0.0            # D4: zero BY CONSTRUCTION on a parity-proxy day
                else:
                    basis1, basis2 = px1 - theo1, px2 - theo2
            # The engine's observed price is `theo + basis`. On a MANUAL or MIRROR day that is the observed close
            # exactly. On a PROXY day it is the *unrounded* duty-parity value: the panel column is the same formula
            # rounded to 4 dp for the CSV, and carrying that rounding into daily variation margin would leave a few
            # rupees of un-telescoped margin per trade (the balance-sheet lifetime sum is asserted to ₹0.01).
            out[d] = {"m1_month": str(m1_month), "m2_month": str(m2_month), "m1_px": px1, "m2_px": px2,
                      "m1_model": theo1 + basis1, "m2_model": theo2 + basis2,
                      "basis": {str(m1_month): basis1, str(m2_month): basis2}, "src": src, "filled": filled}
        if mirror is None and worst > MCX_PROXY_REPLICATION_TOL_INR_KG:
            raise AssertionError(
                f"MCX parity replication error {worst:.6f} ₹/kg exceeds {MCX_PROXY_REPLICATION_TOL_INR_KG} — "
                "the proxy formula in desk.data.mcx and desk.mtm.history have diverged")
        self.mcx_replication_max_inr_kg = worst
        return out

    def _theo(self, d: dt.date, cash: float, usdinr: float, rate: float, month) -> float:
        """Duty-paid import parity for one contract month (the panel's own proxy formula, D4)."""
        premium = float(config.value("mcx_domestic_premium_inr_kg", d))
        spot = cash * usdinr / 1000.0 * _duty_uplift(d) + premium
        dte = max(0, (self.cal.mcx_panel_expiry(month) - d).days)
        return spot * (1.0 + rate * dte / 365.0)

    # ----------------------------------------------------------------------------------------------- accessors
    @property
    def panel_days(self) -> tuple[dt.date, ...]:
        return self.cal.days

    def row(self, d) -> pd.Series:
        d = to_date(d)
        if d not in self._rows:
            raise KeyError(f"{d} is not an LME panel day")
        return self._rows[d]

    def state_at(self, d) -> MarketState:
        d = to_date(d)
        if d in self._states:
            return self._states[d]
        r = self.row(d)
        mcx = self._mcx[d]
        st = MarketState(
            lme_cash_usd_t=float(r.lme_cash_usd_t),
            lme_spread_usd_t=float(r.lme_cash_3m_spread_usd_t),
            mcx_basis_inr_kg=dict(mcx["basis"]),
            mcx_domestic_premium_inr_kg=float(config.value("mcx_domestic_premium_inr_kg", d)),
            grade_factor_frac=dict(self._grade[d]),
            freight_usd_t={lane: float(getattr(r, LANE_FREIGHT_COL[lane])) for lane in LANES},
            usdinr=float(r.usdinr),
            customs_usdinr_import=self._customs[d],
            inr_rate_3m_pa=float(r.inr_rate_3m_pa),
            usd_rate_3m_pa=float(r.usd_rate_3m_pa),
            wc_rate_inr_pa=float(config.value("wc_rate_inr_pa", d)),
            asof=d,
        )
        self._states[d] = st
        return st

    def cash(self, d) -> float:
        return float(self.row(d).lme_cash_usd_t)

    def usdinr(self, d) -> float:
        return float(self.row(d).usdinr)

    def usdinr_fwd_1m(self, d) -> float:
        """The panel's 1-month CIP forward — Phase 1's `parity_goods_fx_basis`; used only by the P1 control."""
        col = str(config.value("parity_goods_fx_basis"))
        return float(getattr(self.row(d), col))

    def wc_rate(self, d) -> float:
        return float(config.value("wc_rate_inr_pa", to_date(d)))

    def mcx_settle(self, d, month) -> float:
        """Observed MCX settle for a contract month on a past panel day (the price a VM flow fixed against)."""
        d = to_date(d)
        m = str(month)
        info = self._mcx[d]
        if m == info["m1_month"]:
            return info["m1_model"]
        if m == info["m2_month"]:
            return info["m2_model"]
        # Unlisted month (design §11): the furthest listed contract's basis on the month's own theoretical price.
        r = self.row(d)
        return (self._theo(d, float(r.lme_cash_usd_t), float(r.usdinr), float(r.inr_rate_3m_pa), m)
                + info["basis"][info["m2_month"]])

    def mcx_basis_for(self, state: MarketState, d, month) -> float:
        """Basis to apply to a contract month at clock `d` (unlisted months take the furthest listed one)."""
        basis = state.mcx_basis_inr_kg
        m = str(month)
        if m in basis:
            return basis[m]
        return basis[max(basis)] if basis else 0.0

    def mcx_src(self, d) -> str:
        return self._mcx[to_date(d)]["src"]

    def freight_usd_t(self, d, lane: str) -> float:
        return float(getattr(self.row(d), LANE_FREIGHT_COL[lane]))

    def duty_uplift(self, d) -> float:
        return _duty_uplift(to_date(d))

    def param(self, key: str, d=None):
        """Register look-up, memoised on (key, date) — the register is deterministic, so this changes no number."""
        d = to_date(d) if d is not None else None
        hit = self._param_cache.get((key, d), _MISS)
        if hit is _MISS:
            hit = self.params(key, d)
            self._param_cache[(key, d)] = hit
        return hit

    # --------------------------------------------------------------------------------------------------- guard
    def view(self, clock) -> "HistoryView":
        """A clock-bounded view: every accessor raises `LookaheadError` beyond `clock` (design D10)."""
        return HistoryView(self, to_date(clock))


class HistoryView:
    """`MarketHistory` restricted to dates on or before one clock."""

    __slots__ = ("h", "clock")

    def __init__(self, h: MarketHistory, clock: dt.date) -> None:
        self.h = h
        self.clock = clock

    def _check(self, d) -> dt.date:
        d = to_date(d)
        if d > self.clock:
            raise LookaheadError(f"asked for {d} with the clock at {self.clock}")
        return d

    @property
    def cal(self) -> PanelCalendar:
        return self.h.cal

    def state_at(self, d) -> MarketState:
        return self.h.state_at(self._check(d))

    def cash(self, d) -> float:
        return self.h.cash(self._check(d))

    def usdinr(self, d) -> float:
        return self.h.usdinr(self._check(d))

    def mcx_settle(self, d, month) -> float:
        return self.h.mcx_settle(self._check(d), month)

    def freight_usd_t(self, d, lane: str) -> float:
        return self.h.freight_usd_t(self._check(d), lane)

    def wc_rate(self, d) -> float:
        return self.h.wc_rate(self._check(d))

    def duty_uplift(self, d) -> float:
        return self.h.duty_uplift(self._check(d))

    def mcx_basis_for(self, state, d, month) -> float:
        return self.h.mcx_basis_for(state, self._check(d), month)

    def param(self, key: str, d=None):
        return self.h.param(key, self._check(d) if d is not None else None)


def load_panel(path=None) -> pd.DataFrame:
    path = PANEL_CSV if path is None else path
    if not path.exists():
        raise FileNotFoundError(f"{path} missing — run `DESK_OFFLINE=1 .venv/bin/python run_all.py --only P0`")
    return pd.read_csv(path, parse_dates=["date"])


def panel_days(panel: pd.DataFrame | None = None) -> set[dt.date]:
    """The LME trading days, for `desk.book.schema` validation rule V04."""
    panel = load_panel() if panel is None else panel
    return {to_date(d) for d in panel["date"]}


def weakest_flag(flags: Iterable[str]) -> str:
    """Weakest provenance among a set of inputs (CONTRACTS §1.2): SIM < ASSUMPTION < PROXY < DIRECT."""
    order = {"DIRECT": 3, "PROXY": 2, "ASSUMPTION": 1, "SIM": 0}
    fl = [f for f in flags if f in order]
    return min(fl, key=lambda f: order[f]) if fl else "DIRECT"


INPUT_FLAGS: Mapping[str, str] = {
    "lme": "DIRECT", "fx": "PROXY", "rates": "PROXY", "mcx": "PROXY",
    "grade": "ASSUMPTION", "freight": "ASSUMPTION", "customs_fx": "DIRECT", "sim": "SIM",
}
