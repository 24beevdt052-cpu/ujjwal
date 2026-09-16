"""Daily risk exposures by central bump-and-revalue of the *same* valuation (design §7, CONTRACTS §7a.4).

Nothing here re-implements pricing. Every delta is `(Pi(M+) - Pi(M-)) / (2 x bump)` on the function that produced
the day's P&L, with the clock, the contracts and the events held. Two consequences matter:

* a risk number can never disagree with a P&L number — they are the same code;
* the legs are linear or bilinear in every factor, so the central difference is exact to float error, and the one
  genuinely second-order number (`lme_fx_cross_inr`) is measured with a four-point cross bump rather than assumed
  away.

Signs are from the desk's point of view: `+ lme_delta_mt` = long metal (gains when LME rises), `+ fx_delta_usd` =
long USD (gains when the rupee weakens), `+ freight_open_boxes` = short freight (an unfixed FOB cargo still to book).
One MCX lot is `lot_mt x duty uplift x carry` ~= **5.44 MT of LME-equivalent metal**, which is why hedge sizing is
quoted in LME-equivalent tonnes rather than physical tonnes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import Mapping

from desk import units
from desk.book import schema as bs
from desk.mtm import curves, valuation as val
from desk.mtm.constants import (BUMP_FREIGHT_USD_T, BUMP_GRADE_FACTOR, BUMP_LME_CASH_USD_T,
                                BUMP_MCX_BASIS_INR_KG, BUMP_RATE_PA, BUMP_SPREAD_USD_T, BUMP_USDINR,
                                HEDGE_RATIO_MIN_PHYSICAL_MT, HEDGE_RATIO_MIN_PHYSICAL_USD)
from desk.mtm.history import GRADES, LANES
from desk.mtm.lifecycle import LANE_BOX, PNL
from desk.mtm.state import MarketState

MCX_LEG_TYPES = {"MCX_VARIATION_MARGIN", "MCX_INITIAL_MARGIN", "MCX_SLIPPAGE", "MCX_TRANSACTION_COST"}
FX_LEG_TYPES = {"FX_FORWARD"}
ONE_BP = 1e-4


def hedge_ratio(hedge: float, physical: float, floor: float) -> float:
    """`-hedge / physical`, or NaN when the physical leg is too small for the quotient to mean anything.

    Not a cosmetic guard: on the real book the net physical USD delta crosses zero (design D5 marks unsold cargo
    long USD while the payable is short USD), and an unguarded ratio printed values from -10,716 to +434 on days
    when the denominator was under USD 100k. A number like that is worse than a blank for whoever reads it next.
    """
    return -hedge / physical if abs(physical) >= floor else float("nan")


def instrument_of(leg_type: str) -> str:
    if leg_type in MCX_LEG_TYPES:
        return "mcx"
    if leg_type in FX_LEG_TYPES:
        return "fx_forward"
    if leg_type == "FREIGHT_SWAP_HYPOTHETICAL":
        return "freight_swap"
    return "physical"


def _group_values(tv: val.TradeValue) -> dict[str, float]:
    """Π split into physical / mcx / fx_forward, so a hedge ratio can be read off the same revaluation."""
    out = {"physical": 0.0, "mcx": 0.0, "fx_forward": 0.0, "freight_swap": 0.0, "total": 0.0}
    for f, v in zip(tv.schedule.flows, tv.per_flow):
        if f.pnl_class != PNL:
            continue
        out[instrument_of(f.leg_type)] += v
        out["total"] += v
    return out


def _bumped(ticket, book, t: dt.date, H, cache, M: MarketState, **fields) -> dict[str, float]:
    return _group_values(val.trade_value(ticket, book, t, t, replace(M, **fields), t, H, cache))


def _central(up: Mapping[str, float], dn: Mapping[str, float], bump: float, key: str = "total") -> float:
    return (up[key] - dn[key]) / (2.0 * bump)


def trade_exposures(ticket: bs.Ticket, book: bs.Book, t: dt.date, H, cache: val.ScheduleCache,
                    fp: val.FundingPath, tv: val.TradeValue) -> dict:
    """Every `book_exposures_daily.csv` measure for one trade on one day."""
    M = H.state_at(t)
    lane = ticket.lane.value
    grade = ticket.grade.value
    box = LANE_BOX[lane]
    sched = tv.schedule

    b = BUMP_LME_CASH_USD_T
    lme_up = _bumped(ticket, book, t, H, cache, M, lme_cash_usd_t=M.lme_cash_usd_t + b)
    lme_dn = _bumped(ticket, book, t, H, cache, M, lme_cash_usd_t=M.lme_cash_usd_t - b)
    lme_delta = _central(lme_up, lme_dn, b)
    lme_phys = _central(lme_up, lme_dn, b, "physical") + _central(lme_up, lme_dn, b, "fx_forward")
    lme_mcx = _central(lme_up, lme_dn, b, "mcx")

    f = BUMP_USDINR
    fx_up = _bumped(ticket, book, t, H, cache, M, usdinr=M.usdinr + f)
    fx_dn = _bumped(ticket, book, t, H, cache, M, usdinr=M.usdinr - f)
    fx_delta = _central(fx_up, fx_dn, f)

    c = BUMP_USDINR
    cfx_up = _bumped(ticket, book, t, H, cache, M, customs_usdinr_import=M.customs_usdinr_import + c)
    cfx_dn = _bumped(ticket, book, t, H, cache, M, customs_usdinr_import=M.customs_usdinr_import - c)

    g = BUMP_GRADE_FACTOR
    gf_up = _bumped(ticket, book, t, H, cache, M,
                    grade_factor_frac={k: v + (g if k == grade else 0.0) for k, v in M.grade_factor_frac.items()})
    gf_dn = _bumped(ticket, book, t, H, cache, M,
                    grade_factor_frac={k: v - (g if k == grade else 0.0) for k, v in M.grade_factor_frac.items()})
    grade_delta = _central(gf_up, gf_dn, g)

    fr = BUMP_FREIGHT_USD_T
    freight_delta = {}
    for ln in LANES:
        up = _bumped(ticket, book, t, H, cache, M,
                     freight_usd_t={k: v + (fr if k == ln else 0.0) for k, v in M.freight_usd_t.items()})
        dn = _bumped(ticket, book, t, H, cache, M,
                     freight_usd_t={k: v - (fr if k == ln else 0.0) for k, v in M.freight_usd_t.items()})
        freight_delta[ln] = _central(up, dn, fr)

    bb = BUMP_MCX_BASIS_INR_KG
    bs_up = _bumped(ticket, book, t, H, cache, M,
                    mcx_basis_inr_kg={k: v + bb for k, v in M.mcx_basis_inr_kg.items()})
    bs_dn = _bumped(ticket, book, t, H, cache, M,
                    mcx_basis_inr_kg={k: v - bb for k, v in M.mcx_basis_inr_kg.items()})

    sp = BUMP_SPREAD_USD_T
    sp_up = _bumped(ticket, book, t, H, cache, M, lme_spread_usd_t=M.lme_spread_usd_t + sp)
    sp_dn = _bumped(ticket, book, t, H, cache, M, lme_spread_usd_t=M.lme_spread_usd_t - sp)

    r = BUMP_RATE_PA
    ri_up = _bumped(ticket, book, t, H, cache, M, inr_rate_3m_pa=M.inr_rate_3m_pa + r)
    ri_dn = _bumped(ticket, book, t, H, cache, M, inr_rate_3m_pa=M.inr_rate_3m_pa - r)
    ru_up = _bumped(ticket, book, t, H, cache, M, usd_rate_3m_pa=M.usd_rate_3m_pa + r)
    ru_dn = _bumped(ticket, book, t, H, cache, M, usd_rate_3m_pa=M.usd_rate_3m_pa - r)

    # cross bump — the only genuinely second-order number in the book (LME x FX on USD-priced physical)
    pp = _bumped(ticket, book, t, H, cache, M, lme_cash_usd_t=M.lme_cash_usd_t + b, usdinr=M.usdinr + f)
    pm = _bumped(ticket, book, t, H, cache, M, lme_cash_usd_t=M.lme_cash_usd_t + b, usdinr=M.usdinr - f)
    mp = _bumped(ticket, book, t, H, cache, M, lme_cash_usd_t=M.lme_cash_usd_t - b, usdinr=M.usdinr + f)
    mm = _bumped(ticket, book, t, H, cache, M, lme_cash_usd_t=M.lme_cash_usd_t - b, usdinr=M.usdinr - f)
    cross = (pp["total"] - pm["total"] - mp["total"] + mm["total"]) / 4.0

    lots_open = sum(tr.lots * (1 if tr.direction is bs.HedgeDirection.BUY else -1)
                    for tr in ticket.hedges.mcx.tranches if tr.entry_date <= t < tr.exit_date)
    im = sum(-val.realised_inr(sched, i, H) for i, fl in enumerate(sched.flows)
             if fl.leg_type == "MCX_INITIAL_MARGIN" and fl.settle_date <= t)

    purchased = sum(q.q_bl_mt for lid, q in sched.quantities.items() if sched.lot_dates[lid].bl <= t)
    sold = sum(sum(sched.quantities[lid].q_bl_mt for lid in s.lot_ids)
               for s in ticket.sales if s.contract_date <= t)
    unsold_mt = sum(fl.qty_mt for fl in sched.flows if fl.leg_type == "INVENTORY_MARK")

    open_boxes = 0
    if ticket.freight is not None:
        fixed = ticket.freight.fixture_date is not None and ticket.freight.fixture_date <= t
        if not fixed:
            open_boxes = sum(lot.boxes for lot in ticket.shipment.lots
                             if sched.lot_dates[lot.lot_id].freight_settle is None
                             or sched.lot_dates[lot.lot_id].freight_settle > t)
    open_mt = open_boxes * ticket.payload_mt_per_box

    receivable, presettlement, supplier_exp = 0.0, 0.0, 0.0
    for fl, v in zip(sched.flows, tv.per_flow):
        if fl.settle_date is None or fl.settle_date <= t:
            continue
        if fl.sale_id:
            if fl.fixing_date is not None and fl.fixing_date <= t:
                receivable += v          # invoiced, unpaid
            else:
                presettlement += v       # contracted, not yet invoiced
        elif fl.counterparty_id == ticket.purchase.supplier_id and v > 0:
            supplier_exp += v            # supplier refunds and claims the desk is owed

    cash = fp.cash_balance.get(t, 0.0)
    return {
        "buyer_id": ",".join(sorted({s.buyer_id for s in ticket.sales if s.contract_date <= t})),
        "supplier_id": ticket.purchase.supplier_id,
        "mtm_inr": tv.mtm_inr,
        "cash_balance_inr": cash,
        "mcx_im_inr": im,
        "lme_delta_inr_per_usd_t": lme_delta,
        "lme_delta_mt": lme_delta / M.usdinr,
        "lme_delta_usd": lme_delta / M.usdinr * M.lme_cash_usd_t,
        "lme_delta_physical_mt": lme_phys / M.usdinr,
        "lme_delta_mcx_mt": lme_mcx / M.usdinr,
        "hedge_ratio_lme_frac": hedge_ratio(lme_mcx / M.usdinr, lme_phys / M.usdinr, HEDGE_RATIO_MIN_PHYSICAL_MT),
        "mcx_lots_open": lots_open,
        "mcx_basis_delta_inr_per_inr_kg": _central(bs_up, bs_dn, bb),
        "fx_delta_usd": fx_delta,
        "fx_delta_physical_usd": _central(fx_up, fx_dn, f, "physical"),
        "fx_delta_forwards_usd": _central(fx_up, fx_dn, f, "fx_forward"),
        "fx_delta_mcx_usd": _central(fx_up, fx_dn, f, "mcx"),
        "hedge_ratio_fx_frac": hedge_ratio(_central(fx_up, fx_dn, f, "fx_forward"),
                                           _central(fx_up, fx_dn, f, "physical"), HEDGE_RATIO_MIN_PHYSICAL_USD),
        "customs_fx_delta_usd": _central(cfx_up, cfx_dn, c),
        "freight_delta_inr_per_usd_t_jea_nsa": freight_delta["JEA_NSA"],
        "freight_delta_inr_per_usd_t_usec_mun": freight_delta["USEC_MUN"],
        "freight_open_mt_jea_nsa": open_mt if lane == "JEA_NSA" else 0.0,
        "freight_open_mt_usec_mun": open_mt if lane == "USEC_MUN" else 0.0,
        "freight_open_boxes": open_boxes,
        **{f"grade_delta_inr_per_0p01_{g_}": (grade_delta * 0.01 if g_ == grade else 0.0) for g_ in GRADES},
        **{f"grade_exposure_mt_{g_}": (unsold_mt if g_ == grade else 0.0) for g_ in GRADES},
        "spread_delta_inr_per_usd_t": _central(sp_up, sp_dn, sp),
        "inr_rate_delta_inr_per_bp": _central(ri_up, ri_dn, r) * ONE_BP,
        "usd_rate_delta_inr_per_bp": _central(ru_up, ru_dn, r) * ONE_BP,
        # The working-capital rate touches funding only, and funding is a history-only accrual: the exposure is
        # today's accrual per basis point on today's actual dated cash balance.
        "wc_rate_delta_inr_per_bp": cash * ONE_BP / units.DAY_COUNT_INR,
        "lme_fx_cross_inr": cross,
        "phys_purchased_mt": purchased,
        "phys_sold_mt": sold,
        "unsold_mt": unsold_mt,
        "purchase_priced_frac": _purchase_priced_frac(ticket, sched, H, M, t),
        "sale_priced_frac": _sale_priced_frac(ticket, H, M, t),
        "buyer_receivable_inr": receivable,
        "buyer_presettlement_inr": presettlement,
        "supplier_exposure_inr": supplier_exp,
        "days_past_due": fp.days_past_due.get(t, 0),
    }


def _purchase_priced_frac(ticket: bs.Ticket, sched, H, M, t: dt.date) -> float:
    """Fraction of the purchase whose price is already fixed (a FIXED SPA is 1.0 from the trade date)."""
    if ticket.purchase.pricing.type is bs.PurchasePricingType.FIXED:
        return 1.0
    HV = H.view(t)
    total = sum(q.q_bl_mt for q in sched.quantities.values())
    if not total:
        return 0.0
    fixed = 0.0
    for lid, q in sched.quantities.items():
        _avg, frac = curves.lme_month_avg(HV, M, t, sched.lot_dates[lid].pricing_month)
        fixed += q.q_bl_mt * frac
    return fixed / total


def _sale_priced_frac(ticket: bs.Ticket, H, M, t: dt.date) -> float:
    HV = H.view(t)
    total = sum(1 for s in ticket.sales if s.contract_date <= t)
    if not total:
        return 0.0
    fixed = 0.0
    for s in ticket.sales:
        if s.contract_date > t:
            continue
        if s.pricing.type is bs.SalePricingType.FIXED:
            fixed += 1.0
        else:
            _avg, frac = curves.mcx_avg(HV, M, t, s.pricing.window_start, s.pricing.window_end)
            fixed += frac
    return fixed / total


# CONTRACTS §7a.4 column order, so a reader can scan the file the way the contract describes it.
COLUMN_ORDER = (
    "date", "scope", "trade_id", "in_window", "buyer_id", "supplier_id",
    "mtm_inr", "cum_pnl_inr", "cash_balance_inr", "mcx_im_inr",
    "lme_delta_inr_per_usd_t", "lme_delta_mt", "lme_delta_usd", "lme_delta_physical_mt", "lme_delta_mcx_mt",
    "hedge_ratio_lme_frac", "mcx_lots_open", "mcx_basis_delta_inr_per_inr_kg",
    "fx_delta_usd", "fx_delta_physical_usd", "fx_delta_forwards_usd", "fx_delta_mcx_usd", "hedge_ratio_fx_frac",
    "customs_fx_delta_usd",
    "freight_delta_inr_per_usd_t_jea_nsa", "freight_delta_inr_per_usd_t_usec_mun",
    "freight_open_mt_jea_nsa", "freight_open_mt_usec_mun", "freight_open_boxes",
    *(f"grade_delta_inr_per_0p01_{g}" for g in GRADES),
    *(f"grade_exposure_mt_{g}" for g in GRADES),
    "spread_delta_inr_per_usd_t", "inr_rate_delta_inr_per_bp", "usd_rate_delta_inr_per_bp",
    "wc_rate_delta_inr_per_bp", "lme_fx_cross_inr",
    "phys_purchased_mt", "phys_sold_mt", "unsold_mt", "purchase_priced_frac", "sale_priced_frac",
    "buyer_receivable_inr", "buyer_presettlement_inr", "supplier_exposure_inr", "days_past_due",
)

SUM_COLUMNS = (
    "mtm_inr", "cum_pnl_inr", "cash_balance_inr", "mcx_im_inr",
    "lme_delta_inr_per_usd_t", "lme_delta_mt", "lme_delta_usd", "lme_delta_physical_mt", "lme_delta_mcx_mt",
    "mcx_lots_open", "mcx_basis_delta_inr_per_inr_kg",
    "fx_delta_usd", "fx_delta_physical_usd", "fx_delta_forwards_usd", "fx_delta_mcx_usd", "customs_fx_delta_usd",
    "freight_delta_inr_per_usd_t_jea_nsa", "freight_delta_inr_per_usd_t_usec_mun",
    "freight_open_mt_jea_nsa", "freight_open_mt_usec_mun", "freight_open_boxes",
    *(f"grade_delta_inr_per_0p01_{g}" for g in GRADES),
    *(f"grade_exposure_mt_{g}" for g in GRADES),
    "spread_delta_inr_per_usd_t", "inr_rate_delta_inr_per_bp", "usd_rate_delta_inr_per_bp",
    "wc_rate_delta_inr_per_bp", "lme_fx_cross_inr",
    "phys_purchased_mt", "phys_sold_mt", "unsold_mt",
    "buyer_receivable_inr", "buyer_presettlement_inr", "supplier_exposure_inr",
)
