"""Pricing primitives (design §5.2, §5.3). Pure arithmetic on a `MarketState`, a clock and a history view.

Everything here is closed form and numpy-safe: each function is arithmetic plus `np.maximum`, never a branch on a
market value, so the whole Monte Carlo can be broadcast through the same code Phase 3 uses for one day
(design D2). Branches are on **dates only**.

Two approximations are deliberate and are the price of having only Cash and 3M as DIRECT points on the LME curve:

* the forward curve is **linear from cash to 3M and flat beyond** (`LME_CURVE_EXTRAPOLATION`), and
* the 2-day cash prompt (`lme_cash_prompt_bdays`) is ignored, exactly as Phase 1's `forward_price` ignores it.

Both leave a small timing effect that lands in bucket (g) and vanishes as fixings happen; design §11 records them.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from desk import units
from desk.mtm.calendar import to_date
from desk.mtm.state import MarketState

KG_PER_MT = units.KG_PER_MT


# ------------------------------------------------------------------------------------------------- LME curve
def lme_3m(M: MarketState):
    return M.lme_cash_usd_t - M.lme_spread_usd_t


def curve_weight(cal, tau: dt.date, s: dt.date) -> float:
    """Linear cash→3M weight, clipped at the 3-month point (flat extrapolation beyond)."""
    days = (s - tau).days
    if days <= 0:
        return 0.0
    return min(1.0, days / cal.tenor_days(tau))


def cash_fwd(M: MarketState, cal, tau: dt.date, s: dt.date):
    """Forward LME cash for prompt `s` seen at `tau`."""
    return M.lme_cash_usd_t - M.lme_spread_usd_t * curve_weight(cal, tau, s)


def cash_at(HV, M: MarketState, tau: dt.date, s: dt.date):
    """The cash price for day `s`: the observed fixing if it has happened, else today's forward estimate."""
    return HV.cash(s) if s <= tau else cash_fwd(M, HV.cal, tau, s)


def month_fixing_days(cal, month) -> tuple[dt.date, ...]:
    """The LME trading days of a quotational month (published in advance, so this is not hindsight)."""
    return cal.month_days(pd.Period(str(month), freq="M"))


def lme_month_avg(HV, M: MarketState, tau: dt.date, month) -> tuple[float, float]:
    """(arithmetic average of LME official cash over `month`, fraction of its days already fixed)."""
    days = month_fixing_days(HV.cal, month)
    if not days:
        raise ValueError(f"no panel days in pricing month {month}")
    total = 0.0
    n_fixed = 0
    for s in days:
        if s <= tau:
            total = total + HV.cash(s)
            n_fixed += 1
        else:
            total = total + cash_fwd(M, HV.cal, tau, s)
    return total / len(days), n_fixed / len(days)


# ------------------------------------------------------------------------------------------------------- FX
def fx_x(HV, M: MarketState, tau: dt.date, settle: dt.date):
    """USD/INR applicable to a flow settling on `settle`, seen at `tau` (CONTRACTS §7a.1 clause 4).

    Future flows are valued at the covered-interest-parity forward to their **own** settle date, settled flows at the
    spot that actually fixed. That is what makes a 100% forward hedge exactly flat in buckets (e) and (g).
    """
    if settle < tau:
        return HV.usdinr(settle)
    if settle == tau:
        return M.usdinr
    return units.fx_forward(M.usdinr, M.inr_rate_3m_pa, M.usd_rate_3m_pa, (settle - tau).days)


def fx_forward_strike(H, booking: dt.date, value_date: dt.date, direction_sign: int) -> float:
    """The dealt rate: the CIP mid on the booking date plus the bank's margin against the desk."""
    Mb = H.state_at(booking)
    mid = fx_x(H.view(booking), Mb, booking, value_date)
    margin = float(H.param("fx_forward_bank_margin_inr", booking))
    return mid + direction_sign * margin


# ------------------------------------------------------------------------------------------------------ MCX
def mcx_theo(HV, M: MarketState, tau: dt.date, month):
    """Duty-paid import parity carried to the contract month's expiry, before basis (design D4)."""
    uplift = HV.duty_uplift(tau)
    spot = M.lme_cash_usd_t * M.usdinr / KG_PER_MT * uplift + M.mcx_domestic_premium_inr_kg
    dte = max(0, (HV.cal.mcx_panel_expiry(month) - tau).days)
    return spot * (1.0 + M.inr_rate_3m_pa * dte / units.DAY_COUNT_INR)


def mcx_price(HV, M: MarketState, tau: dt.date, month):
    """Today's mark for a contract month: parity theo + that month's basis."""
    return mcx_theo(HV, M, tau, month) + HV.mcx_basis_for(M, tau, month)


def mcx_at(HV, M: MarketState, tau: dt.date, s: dt.date, month):
    """The settle for `month` on day `s`: observed if `s` is in the past, else today's mark."""
    return HV.mcx_settle(s, month) if s < tau else mcx_price(HV, M, tau, month)


def mcx_avg(HV, M: MarketState, tau: dt.date, start: dt.date, end: dt.date) -> tuple[float, float]:
    """(average near-month MCX price over [start, end], fraction already fixed) — the sale's pricing window."""
    days = HV.cal.between(start, end)
    if not days:
        raise ValueError(f"no panel days in the MCX averaging window {start}..{end}")
    total = 0.0
    n_fixed = 0
    for s in days:
        month = HV.cal.m1_month_on(s)
        if s <= tau:
            total = total + HV.mcx_settle(s, month)
            n_fixed += 1
        else:
            total = total + mcx_price(HV, M, tau, month)
    return total / len(days), n_fixed / len(days)


# --------------------------------------------------------------------------------------------------- freight
def box_mkt(HV, M: MarketState, tau: dt.date, lane: str, box: str):
    """Market freight per container: the panel USD/MT is quoted at the lane's BASE payload (CONTRACTS §4.3)."""
    base_payload = float(HV.param(f"container_payload_mt_{box}", tau))
    return M.freight_usd_t[lane] * base_payload


# ------------------------------------------------------------------------------- replacement value of cargo (D5)
def replacement_value(HV, M: MarketState, tau: dt.date, grade: str, lane: str, box: str,
                      goods_fx: float | None = None):
    """₹ per MT: what it would cost to replace this cargo today — goods + BCD + SWS + port/PSIC, NO finance.

    Design D5. Marking unsold cargo at the MCX-anchored smelter netback would book the whole parity margin on day one
    on `domestic_anchor_premium_inr_t`, an ASSUMPTION whose own evidence spans −52k…+13k ₹/t, and would kill grade
    spread as a live factor on open inventory. `goods_fx` overrides the 1-month forward (used only by the Phase 1
    reconciliation control, which substitutes the panel's rounded `usdinr_fwd_1m`).
    """
    factor = M.grade_factor_frac[grade]
    cfr = lme_3m(M) * factor
    ins_rate = float(HV.param("insurance_rate", tau))
    uplift = float(HV.param("insured_value_uplift", tau))
    cif = cfr * (1.0 + ins_rate * uplift)
    if goods_fx is None:
        goods_fx = fx_x(HV, M, tau, _one_month_after(HV.cal, tau))
    goods = cif * goods_fx
    bcd_rate = float(HV.param("bcd_scrap_hs7602", tau))
    sws_rate = float(HV.param("sws_rate_on_bcd", tau))
    av = cif * M.customs_usdinr_import
    duty = av * bcd_rate * (1.0 + sws_rate)
    base_payload = float(HV.param(f"container_payload_mt_{box}", tau))
    grade_payload = float(HV.param(f"container_payload_mt_{box}_{grade}", tau))
    payload_scale = base_payload / grade_payload
    port_key = "port_cf_charges_inr_t_nsa" if lane == "JEA_NSA" else "port_cf_charges_inr_t_mun"
    port = float(HV.param(port_key, tau)) * payload_scale
    if psic_applies(HV, tau, lane):
        payload_20 = float(HV.param(f"container_payload_mt_20ft_{grade}", tau))
        port = port + float(HV.param("psic_cost_usd_per_box", tau)) * M.usdinr / payload_20
    igst = 0.0
    if not bool(HV.param("igst_itc_available", tau)):
        igst = (av + duty) * float(HV.param("igst_rate_hs7602", tau))
    return goods + duty + port + igst


def psic_applies(HV, tau: dt.date, lane: str) -> bool:
    key = "psic_required_uae_origin" if lane == "JEA_NSA" else "psic_required_safe_origin_designated_port"
    return bool(HV.param(key, tau))


def _one_month_after(cal, tau: dt.date) -> dt.date:
    """`tau` + 1 calendar month — the tenor a replacement cargo would actually be paid at (design §5.3)."""
    return to_date(pd.Timestamp(tau) + pd.DateOffset(months=1))


def netback_inr_t(HV, M: MarketState, tau: dt.date, grade: str, lane: str):
    """MCX-anchored smelter netback per MT of scrap (CONTRACTS §5) — a **memo** bound on sale prices, never a mark."""
    month = HV.cal.m1_month_on(tau) if lane == "JEA_NSA" else HV.cal.m1_month_on(tau) + 1
    anchor = mcx_price(HV, M, tau, month) * KG_PER_MT + float(HV.param("domestic_anchor_premium_inr_t", tau))
    moisture = float(HV.param(f"moisture_frac_{grade}", tau))
    contamination = float(HV.param(f"contamination_frac_{grade}", tau))
    yield_frac = float(HV.param(f"metal_yield_frac_{grade}", tau))
    recovery = (1.0 - moisture) * (1.0 - contamination) * yield_frac
    heavies = float(HV.param(f"heavies_frac_{grade}", tau))
    heavies_value = float(HV.param("heavies_net_value_frac_of_lme_al", tau))
    byproduct = (1.0 - moisture) * heavies * heavies_value * lme_3m(M) * M.usdinr
    conversion = float(HV.param("conversion_cost_inr_t", tau)) * recovery
    return anchor * recovery + byproduct - conversion


def clip01(x):
    return np.clip(x, 0.0, 1.0)
