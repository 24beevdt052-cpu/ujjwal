"""Explicit unit conversions (Table 8.3: units are never mixed silently).

Conventions used across the codebase (column-name suffixes):
    _usd_t   USD per metric tonne. LME quotes "$/t" = USD per metric tonne = USD/MT.
    _inr_t   INR per metric tonne (₹/MT).
    _inr_kg  INR per kilogram (₹/kg) — MCX Aluminium quote unit.
    _mt      quantity in metric tonnes.
    _usd / _inr   money totals.
    _pa      annualised rate as a decimal fraction (0.054 = 5.4 % p.a.).
    _frac    dimensionless fraction (0.80 = 80 %).
    usdinr   INR per 1 USD.
"""

from __future__ import annotations

import math

KG_PER_MT = 1000.0
DAY_COUNT_INR = 365.0  # INR money-market / finance-cost convention (ACT/365)
DAY_COUNT_USD = 360.0  # USD money-market convention (ACT/360)


def usd_t_to_inr_t(usd_t, usdinr):
    return usd_t * usdinr


def inr_t_to_usd_t(inr_t, usdinr):
    return inr_t / usdinr


def inr_t_to_inr_kg(inr_t):
    return inr_t / KG_PER_MT


def inr_kg_to_inr_t(inr_kg):
    return inr_kg * KG_PER_MT


def usd_t_to_inr_kg(usd_t, usdinr):
    return usd_t * usdinr / KG_PER_MT


def mt_to_lots(mt: float, lot_size_mt: float) -> int:
    """Whole exchange lots for a tonnage (rounded to nearest; hedges cannot trade fractions)."""
    return int(round(mt / lot_size_mt))


def lots_to_mt(lots: int, lot_size_mt: float) -> float:
    return lots * lot_size_mt


def simple_interest(principal, rate_pa, days, basis=DAY_COUNT_INR):
    """Interest on `principal` for `days` at `rate_pa` (simple, ACT/basis)."""
    return principal * rate_pa * days / basis


def fx_forward(spot: float, inr_rate_pa: float, usd_rate_pa: float, days: int) -> float:
    """Covered-interest-parity USD/INR forward (INR ACT/365, USD ACT/360)."""
    return spot * (1 + inr_rate_pa * days / DAY_COUNT_INR) / (1 + usd_rate_pa * days / DAY_COUNT_USD)


def log_return(p1, p0):
    return math.log(p1 / p0)
