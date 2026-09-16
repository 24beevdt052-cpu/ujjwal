"""The daily engine: walk the book day by day and build every Phase 3 table (design §9.1).

One pass over the panel calendar produces, per trade and per day, the attribution chain, the leg-level mark-to-market,
the cash ledger and the funding accrual; a second (optional) pass adds the bump-and-revalue exposures. Counterfactual
books — without MCX, without the forwards, without the simulated events, with the freight fixture undone — are the
*same* pass with a different `ScheduleCache`, which is what keeps a hedge-benefit number honest: it is the difference
between two runs of one engine, not two models.

Controls are computed here and enforced in `desk.mtm.run`: the ₹1 attribution residual, the ledger identity, the
zero-by-construction proxy basis, the zero lifetime sum of balance-sheet flows, and the cross-phase reconciliation
of the replacement mark to Phase 1's parity components.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from desk import HORIZON_END, WINDOW_END, WINDOW_START, units
from desk.book import schema as bs
from desk.mtm import attribution as attrib, curves, exposures as expo, valuation as val
from desk.mtm.constants import (HEDGE_RATIO_MIN_PHYSICAL_MT, HEDGE_RATIO_MIN_PHYSICAL_USD, ROUND_FRAC, ROUND_INR,
                                ROUND_PRICE)
from desk.mtm.history import GRADES, MarketHistory
from desk.mtm.lifecycle import BS, LANE_BOX, PNL, Schedule
from desk.reporting.style import PNL_BUCKETS

BOOK_ID = "BOOK"
MCX_STRESS_MARGINS = (0.12, 0.15)          # the `mcx_al_margin_used_frac` note's stressed levels
# Internal weight for the book-level pricing fractions; dropped before the file is written (§7a.4 fixes the columns).
WEIGHT_COLUMN = "_ticket_qty_mt"


def in_window(d: dt.date) -> bool:
    return WINDOW_START <= d <= WINDOW_END


@dataclass
class TradeRun:
    ticket: bs.Ticket
    schedule: Schedule
    funding: val.FundingPath
    days: tuple[dt.date, ...]
    atts: dict[dt.date, attrib.DayAttribution] = field(default_factory=dict)


@dataclass
class BookRun:
    book: bs.Book
    H: MarketHistory
    cache: val.ScheduleCache
    label: str
    days: tuple[dt.date, ...]
    per_trade: dict[str, TradeRun]
    attribution: pd.DataFrame
    attribution_leg: pd.DataFrame
    mtm: pd.DataFrame | None = None
    exposures: pd.DataFrame | None = None

    def book_daily(self) -> pd.DataFrame:
        return self.attribution[self.attribution["trade_id"] == BOOK_ID].set_index("date")


# ------------------------------------------------------------------------------------------------------- driver
def run_book(book: bs.Book, H: MarketHistory, *, cache: val.ScheduleCache | None = None, label: str = "base",
             with_detail: bool = True, with_exposures: bool = True, horizon: dt.date = HORIZON_END) -> BookRun:
    """Walk every trade from its trade date to `horizon` and build the daily frames."""
    cache = cache or val.ScheduleCache(book, H)
    cal = H.cal
    first = min(t.trade_date for t in book.trades)
    days = cal.between(first, horizon)

    per_trade: dict[str, TradeRun] = {}
    att_rows: list[dict] = []
    leg_rows: list[dict] = []
    mtm_rows: list[dict] = []
    expo_rows: list[dict] = []

    for ticket in book.trades:
        tdays = cal.between(ticket.trade_date, horizon)
        sched = cache.get(ticket, horizon, horizon)
        fp = val.funding_path(sched, H, tdays)
        run = TradeRun(ticket, sched, fp, tdays)
        prev_state = None
        for d in tdays:
            att, prev_state = attrib.attribute_day(ticket, book, d, cal.prev(d), H, cache, fp, prev_state)
            run.atts[d] = att
            att_rows.append(attrib.bucket_frame_row(att, in_window(d)))
            leg_rows.extend(attrib.leg_rows(att, in_window(d)))
            if with_detail:
                mtm_rows.extend(_mtm_rows(ticket, att, H, d))
            if with_exposures:
                row = expo.trade_exposures(ticket, book, d, H, cache, fp, att.value_today)
                row.update({"date": d, "scope": "trade", "trade_id": ticket.trade_id, "in_window": in_window(d),
                            "cum_pnl_inr": att.cum_pnl_inr, WEIGHT_COLUMN: ticket.quantity_mt})
                expo_rows.append(row)
        per_trade[ticket.trade_id] = run

    att_df = pd.DataFrame(att_rows)
    att_df = pd.concat([att_df, _book_attribution(att_df, days)], ignore_index=True)
    att_df = att_df.sort_values(["date", "trade_id"], kind="mergesort").reset_index(drop=True)
    leg_df = (pd.DataFrame(leg_rows).sort_values(["date", "trade_id", "leg_id"], kind="mergesort")
              .reset_index(drop=True))

    mtm_df = None
    if with_detail:
        mtm_df = (pd.DataFrame(mtm_rows).sort_values(["date", "trade_id", "leg_id"], kind="mergesort")
                  .reset_index(drop=True))
    expo_df = None
    if with_exposures:
        expo_df = pd.DataFrame(expo_rows)
        expo_df = pd.concat([expo_df, _book_exposures(expo_df)], ignore_index=True)
        expo_df = expo_df.sort_values(["date", "scope", "trade_id"], kind="mergesort").reset_index(drop=True)
        expo_df = expo_df[list(expo.COLUMN_ORDER)]

    return BookRun(book, H, cache, label, days, per_trade, att_df, leg_df, mtm_df, expo_df)


def book_pnl_split(run: BookRun) -> pd.DataFrame:
    """Book cumulative P&L split into realised cash (with funding) and the unrealised mark — the equity curve."""
    rows = []
    for d in run.days:
        realised = funding = mtm = 0.0
        for tr in run.per_trade.values():
            a = tr.atts.get(d)
            if a is None:
                continue
            realised += a.realised_cum_inr
            funding += a.funding_cum_inr
            mtm += a.mtm_inr
        rows.append({"date": d, "realised_pnl_inr": realised, "funding_cum_inr": funding,
                     "realised_plus_funding_inr": realised + funding, "mtm_inr": mtm,
                     "cum_pnl_inr": realised + funding + mtm, "in_window": in_window(d)})
    return pd.DataFrame(rows)


def _book_attribution(att_df: pd.DataFrame, days: Sequence[dt.date]) -> pd.DataFrame:
    """Desk-level rows: the sum of the trades, which is exact because every bucket is additive in ₹."""
    cols = list(PNL_BUCKETS) + ["residual", "daily_pnl_inr", "cum_pnl_inr"]
    g = att_df.groupby("date", as_index=False)[cols].sum()
    full = pd.DataFrame({"date": list(days)}).merge(g, on="date", how="left").fillna(0.0)
    full["trade_id"] = BOOK_ID
    full["in_window"] = [in_window(d) for d in full["date"]]
    return full[["date", "in_window", "trade_id"] + cols]


def _ratio(hedge: pd.Series, physical: pd.Series, floor: float) -> np.ndarray:
    """Book-level hedge ratio, blanked on the same rule as the trade rows (`exposures.hedge_ratio`)."""
    p = physical.to_numpy(float)
    safe = np.where(np.abs(p) >= floor, p, np.nan)
    return -hedge.to_numpy(float) / safe


def _book_exposures(expo_df: pd.DataFrame) -> pd.DataFrame:
    g = expo_df.groupby("date", as_index=False)[list(expo.SUM_COLUMNS)].sum()
    g["scope"] = "book"
    g["trade_id"] = BOOK_ID
    g["in_window"] = [in_window(d) for d in g["date"]]
    g["buyer_id"] = BOOK_ID
    g["supplier_id"] = BOOK_ID
    g["days_past_due"] = expo_df.groupby("date")["days_past_due"].max().to_numpy()
    g["hedge_ratio_lme_frac"] = _ratio(g["lme_delta_mcx_mt"], g["lme_delta_physical_mt"],
                                       HEDGE_RATIO_MIN_PHYSICAL_MT)
    g["hedge_ratio_fx_frac"] = _ratio(g["fx_delta_forwards_usd"], g["fx_delta_physical_usd"],
                                      HEDGE_RATIO_MIN_PHYSICAL_USD)
    # Tonnage-weighted, not a mean of tickets: the column reads "share of the book that is priced", and an
    # unweighted mean makes a 1,200 MT ticket count as much as a 2,520 MT one (published 0.500 against a
    # tonnage-weighted 0.677 on 2022-03-11). Weights are the ticket's contracted quantity over the trades on
    # the book that day; a closed ticket still counts, because its purchase price is still struck.
    for col in ("purchase_priced_frac", "sale_priced_frac"):
        g[col] = _weighted(expo_df, col, WEIGHT_COLUMN)
    return g


def _weighted(expo_df: pd.DataFrame, col: str, weight_col: str) -> np.ndarray:
    """Per-date tonnage-weighted mean of a trade-level fraction."""
    w = expo_df[weight_col].to_numpy(float)
    num = expo_df.assign(_n=expo_df[col].to_numpy(float) * w).groupby("date")["_n"].sum()
    den = expo_df.groupby("date")[weight_col].sum()
    return np.where(den.to_numpy() > 0, num.to_numpy() / np.where(den.to_numpy() > 0, den.to_numpy(), 1.0), 0.0)


# ------------------------------------------------------------------------------------------------- mtm_daily
_INSTRUMENT_BY_LEG_PREFIX = {"MCX": "mcx", "FX": "fx_forward", "FUNDING": "funding",
                             "FREIGHT_SWAP": "freight_swap"}


def _mtm_rows(ticket: bs.Ticket, att: attrib.DayAttribution, H: MarketHistory, d: dt.date) -> list[dict]:
    """One row per leg per day (`mtm_daily.csv`, CONTRACTS §7a.3). Funding is a leg with `mtm_inr = 0`."""
    tv = att.value_today
    sched = tv.schedule
    M = H.state_at(d)
    HV = H.view(d)
    by_leg: dict[str, list[int]] = {}
    for i, f in enumerate(sched.flows):
        by_leg.setdefault(f.leg_id, []).append(i)

    rows = []
    for leg_id, idx in by_leg.items():
        flows = [sched.flows[i] for i in idx]
        head = flows[0]
        prefix = leg_id.split(":")[0]
        mtm_inr = mtm_fixed = mtm_float = realised = leg_pnl = 0.0
        mtm_ccy = 0.0
        w_fixed = w_total = 0.0
        for i, f in zip(idx, flows):
            v = tv.per_flow[i]
            if f.pnl_class != PNL:
                continue
            leg_pnl += v
            settled = f.settle_date is not None and f.settle_date <= d
            fixed = f.fixing_date is None or f.fixing_date <= d
            w_total += abs(v)
            if fixed:
                w_fixed += abs(v)
            if settled:
                realised += v
            else:
                mtm_inr += v
                if fixed:
                    mtm_fixed += v
                else:
                    mtm_float += v
                if f.currency == "USD":
                    mtm_ccy += v / curves.fx_x(HV, M, d, f.settle_date)
                else:
                    mtm_ccy += v
        status = _leg_status(flows, d)
        px_usd_t, px_inr_t, px_inr_kg = _leg_prices(ticket, sched, leg_id, prefix, HV, M, d)
        settle = max((f.settle_date for f in flows if f.settle_date is not None), default=None)
        rows.append({
            "date": d, "in_window": in_window(d), "trade_id": ticket.trade_id, "leg_id": leg_id,
            "leg_type": prefix, "instrument": _INSTRUMENT_BY_LEG_PREFIX.get(prefix, "physical"),
            "lot_id": head.lot_id, "counterparty_id": head.counterparty_id or head.sale_id,
            "currency": head.currency, "status": status,
            "fixed_frac": _fixed_frac(ticket, sched, leg_id, prefix, HV, M, d, w_fixed, w_total),
            "pnl_class": head.pnl_class, "qty_mt": sum(f.qty_mt for f in flows if f.pnl_class == PNL),
            "lots": sum(f.lots for f in flows) // max(1, sum(1 for f in flows if f.lots)),
            "notional_usd": sum(f.notional_usd for f in flows),
            "px_usd_t": px_usd_t, "px_inr_t": px_inr_t, "px_inr_kg": px_inr_kg,
            "fx_rate_used": curves.fx_x(HV, M, d, settle) if (settle and head.currency == "USD") else M.usdinr,
            "settle_date": settle, "mtm_ccy": mtm_ccy, "mtm_inr": mtm_inr,
            "mtm_fixed_inr": mtm_fixed, "mtm_floating_inr": mtm_float, "realised_cum_inr": realised,
            "leg_cum_pnl_inr": leg_pnl,
            "leg_daily_pnl_inr": sum(att.legs.get(leg_id, {}).values()),
            "fixture_vs_market_inr": _fixture_vs_market(ticket, sched, leg_id, HV, M, d),
            "weakest_input_flag": head.weakest_input_flag,
        })
    # the funding leg carries no mark: it is a realised accrual on the trade's own dated cash balance
    rows.append({
        "date": d, "in_window": in_window(d), "trade_id": ticket.trade_id, "leg_id": attrib.FUNDING_LEG,
        "leg_type": attrib.FUNDING_LEG, "instrument": "funding", "lot_id": "", "counterparty_id": "",
        "currency": "INR", "status": "settled", "fixed_frac": 1.0, "pnl_class": PNL, "qty_mt": 0.0, "lots": 0,
        "notional_usd": 0.0, "px_usd_t": np.nan, "px_inr_t": np.nan, "px_inr_kg": np.nan,
        "fx_rate_used": M.usdinr, "settle_date": d, "mtm_ccy": 0.0, "mtm_inr": 0.0, "mtm_fixed_inr": 0.0,
        "mtm_floating_inr": 0.0, "realised_cum_inr": att.funding_cum_inr,
        "leg_cum_pnl_inr": att.funding_cum_inr,
        "leg_daily_pnl_inr": sum(att.legs.get(attrib.FUNDING_LEG, {}).values()),
        "fixture_vs_market_inr": np.nan, "weakest_input_flag": "ASSUMPTION",
    })
    return rows


def _leg_status(flows, d: dt.date) -> str:
    pnl = [f for f in flows if f.pnl_class == PNL]
    if not pnl:
        pnl = flows
    if all(f.settle_date is not None and f.settle_date <= d for f in pnl):
        return "settled"
    fixed = [f.fixing_date is None or f.fixing_date <= d for f in pnl]
    if all(fixed):
        return "fixed_unsettled"
    if any(fixed):
        return "partially_fixed"
    return "floating"


def _fixed_frac(ticket, sched, leg_id, prefix, HV, M, d, w_fixed, w_total) -> float:
    """How much of the leg's price is already struck — the pricing-window fraction where one exists."""
    if prefix == "PURCHASE" and ticket.purchase.pricing.type is bs.PurchasePricingType.LME_M1_AVG:
        lid = leg_id.split(":")[1]
        _avg, frac = curves.lme_month_avg(HV, M, d, sched.lot_dates[lid].pricing_month)
        return frac
    if prefix == "SALE":
        sid = leg_id.split(":")[1]
        sale = next(s for s in ticket.sales if s.sale_id == sid)
        if sale.pricing.type is bs.SalePricingType.MCX_AVG:
            _avg, frac = curves.mcx_avg(HV, M, d, sale.pricing.window_start, sale.pricing.window_end)
            return frac
        return 1.0
    return (w_fixed / w_total) if w_total else 1.0


def _leg_prices(ticket, sched, leg_id, prefix, HV, M, d):
    """A representative price for the leg, in whichever unit the leg is quoted in."""
    from desk.mtm import lifecycle as lc

    if prefix == "PURCHASE":
        lid = leg_id.split(":")[1]
        return lc.purchase_unit_price(ticket, HV, M, d, sched.lot_dates[lid], provisional=True), np.nan, np.nan
    if prefix == "SALE":
        sid = leg_id.split(":")[1]
        sale = next(s for s in ticket.sales if s.sale_id == sid)
        return np.nan, lc.sale_unit_price(sale, HV, M, d), np.nan
    if prefix == "MCX":
        hid = leg_id.split(":")[1]
        tr = next(x for x in ticket.hedges.mcx.tranches if x.hedge_id == hid)
        return np.nan, np.nan, curves.mcx_price(HV, M, d, tr.contract_month)
    if prefix == "INVENTORY":
        return np.nan, curves.replacement_value(HV, M, d, ticket.grade.value, ticket.lane.value,
                                                LANE_BOX[ticket.lane.value]), np.nan
    if prefix == "FREIGHT":
        return curves.box_mkt(HV, M, d, ticket.lane.value, LANE_BOX[ticket.lane.value]), np.nan, np.nan
    return np.nan, np.nan, np.nan


def _fixture_vs_market(ticket, sched, leg_id, HV, M, d) -> float:
    """Design D12: a booked fixture is a fixed payable; this is the daily memo of what the market would cost."""
    if not leg_id.startswith("FREIGHT:") or ticket.freight is None or ticket.freight.fixture_date is None:
        return np.nan
    if ticket.freight.fixture_date > d:
        return np.nan
    lid = leg_id.split(":")[1]
    lot = ticket.lot(lid)
    market = curves.box_mkt(HV, M, d, ticket.lane.value, LANE_BOX[ticket.lane.value])
    return lot.boxes * (market - ticket.freight.rate_usd_box) * M.usdinr


# --------------------------------------------------------------------------------------- MCX variation margin
def mcx_variation_margin(book: bs.Book, H: MarketHistory, run: BookRun) -> pd.DataFrame:
    """`mcx_variation_margin.csv` — the cash an importer's short actually posts and receives, day by day."""
    cal = H.cal
    lot_mt = float(H.param("mcx_al_lot_mt"))
    lot_kg = lot_mt * units.KG_PER_MT
    margin_frac = float(H.param("mcx_al_margin_used_frac"))
    slip = float(H.param("mcx_slippage_ticks")) * float(H.param("mcx_al_tick_inr_kg"))
    txn_frac = float(H.param("mcx_txn_cost_frac"))
    series = "MIRROR" if H.mcx_source == "mirror" else "PANEL_PROXY"

    rows = []
    for ticket in book.trades:
        roll_targets = {tr.roll_to for tr in ticket.hedges.mcx.tranches if tr.roll_to}
        for tr in ticket.hedges.mcx.tranches:
            sign = 1 if tr.direction is bs.HedgeDirection.BUY else -1
            month = tr.contract_month
            days = cal.between(tr.entry_date, tr.exit_date)
            cum_vm = cum_cash = 0.0
            prev_im = 0.0
            for i, d in enumerate(days):
                settle = H.mcx_settle(d, month)
                prev_settle = H.mcx_settle(days[i - 1], month) if i else np.nan
                is_entry, is_exit = d == tr.entry_date, d == tr.exit_date
                if is_entry:
                    action = "roll_in" if tr.hedge_id in roll_targets else "entry"
                elif is_exit:
                    action = "roll_out" if tr.exit_reason is bs.HedgeExitReason.ROLL else "exit"
                else:
                    action = "hold"
                vm = 0.0 if i == 0 else sign * tr.lots * lot_kg * (settle - prev_settle)
                fill = np.nan
                txn = slip_cost = 0.0
                if is_entry or is_exit:
                    fill_sign = -sign if is_exit else sign
                    fill = settle + fill_sign * slip
                    txn = -tr.lots * lot_kg * fill * txn_frac
                    slip_cost = -tr.lots * lot_kg * slip
                im_req = 0.0 if is_exit else tr.lots * lot_kg * settle * margin_frac
                im_change = im_req - prev_im
                net_cash = vm + txn + slip_cost - im_change
                cum_vm += vm
                funding = cum_cash * H.wc_rate(days[i - 1]) * (d - days[i - 1]).days / units.DAY_COUNT_INR if i else 0.0
                cum_cash += net_cash
                rows.append({
                    "date": d, "in_window": in_window(d), "trade_id": ticket.trade_id, "hedge_id": tr.hedge_id,
                    "contract_month": month, "panel_expiry_slot": cal.mcx_panel_expiry(month),
                    "direct_expiry": _direct_expiry(month), "roll_deadline": _roll_deadline(cal, month),
                    "direction": tr.direction.value, "lots": sign * tr.lots, "lot_mt": lot_mt, "action": action,
                    "fill_inr_kg": fill, "settle_inr_kg": settle, "prev_settle_inr_kg": prev_settle,
                    "vm_inr": vm, "cum_vm_inr": cum_vm, "txn_cost_inr": txn + slip_cost,
                    "contract_value_inr": tr.lots * lot_kg * settle,
                    "im_required_inr": im_req, "im_change_inr": im_change,
                    "im_stress_012_inr": 0.0 if is_exit else tr.lots * lot_kg * settle * MCX_STRESS_MARGINS[0],
                    "im_stress_015_inr": 0.0 if is_exit else tr.lots * lot_kg * settle * MCX_STRESS_MARGINS[1],
                    "net_margin_cash_inr": net_cash, "cum_margin_cash_inr": cum_cash,
                    "funding_on_margin_inr": funding, "mcx_series": series,
                })
                prev_im = im_req
    return (pd.DataFrame(rows).sort_values(["date", "trade_id", "hedge_id"], kind="mergesort")
            .reset_index(drop=True))


def _direct_expiry(month: str):
    from desk.mtm.calendar import mcx_direct_expiry
    return mcx_direct_expiry(month)


def _roll_deadline(cal, month: str):
    from desk.mtm.calendar import mcx_roll_deadline
    return mcx_roll_deadline(cal, month)


# ------------------------------------------------------------------------------------------- trade cashflows
SCENARIO_NOTES = {
    "REALISED": "what actually settled: every flow at its own settle date, USD at the spot that fixed there",
    "PLANNED_AT_TRADE_DATE":
        "the flows ALREADY CONTRACTED on the trade date, valued on trade-date CIP forwards. NOT an expected "
        "P&L: a sale contracted later is absent, so the PNL rows of a ticket sold after inception sum to a "
        "large negative number (the purchase with no sale against it). Only T02 and T05 contract both legs on "
        "the trade date, and only there does the total equal the day-one new_deal.",
}


def trade_cashflows(book: bs.Book, H: MarketHistory, cache: val.ScheduleCache,
                    horizon: dt.date = HORIZON_END) -> pd.DataFrame:
    """Every dated cashflow under two scenarios: as planned on the trade date, and as realised."""
    rows = []
    for ticket in book.trades:
        for scenario, C, E, clock in (("PLANNED_AT_TRADE_DATE", ticket.trade_date, ticket.trade_date,
                                       ticket.trade_date),
                                      ("REALISED", horizon, horizon, None)):
            sched = cache.get(ticket, C, E)
            for i, f in enumerate(sched.flows):
                if f.settle_date is None:
                    continue
                if scenario == "REALISED":
                    tau = f.settle_date
                    M = H.state_at(tau)
                    amount_inr = val.realised_inr(sched, i, H)
                    fx = H.usdinr(f.settle_date) if f.currency == "USD" else 1.0
                    fx_rule = "spot at settlement" if f.currency == "USD" else "n/a (INR flow)"
                    est = np.nan
                else:
                    tau = clock
                    M = H.state_at(tau)
                    HV = H.view(tau)
                    amount_inr = val.flow_value_inr(sched, i, H, M, tau)
                    fx = curves.fx_x(HV, M, tau, f.settle_date) if f.currency == "USD" else 1.0
                    fx_rule = "CIP forward to the settle date" if f.currency == "USD" else "n/a (INR flow)"
                    est = amount_inr
                due_c = (sched.sale_dates[f.sale_id].due_contractual if f.sale_id else f.settle_date)
                rows.append({
                    "scenario": scenario, "scenario_note": SCENARIO_NOTES[scenario],
                    "trade_id": ticket.trade_id, "leg_id": f.leg_id, "leg_type": f.leg_type,
                    "cf_type": f.leg_type, "pnl_class": f.pnl_class, "currency": f.currency,
                    "contract_date": f.contract_date, "fixing_date": f.fixing_date,
                    "due_date_contractual": due_c, "settle_date": f.settle_date,
                    "amount_ccy": amount_inr / fx if fx else amount_inr, "fx_rate_used": fx, "fx_rule": fx_rule,
                    "amount_inr": amount_inr, "amount_inr_est_at_trade_date": est,
                    "date_rule": "roll following on the LME panel calendar",
                    "weakest_input_flag": f.weakest_input_flag,
                    "event_ids": "|".join(f.event_ids), "formula": f.formula, "label": f.label,
                    "written_by": "P3",
                })
    return (pd.DataFrame(rows)
            .sort_values(["scenario", "trade_id", "settle_date", "leg_id", "leg_type"], kind="mergesort")
            .reset_index(drop=True))


# --------------------------------------------------------------------------------------------------- controls
def controls(run: BookRun, H: MarketHistory) -> pd.DataFrame:
    """`pnl_controls.csv` — the checks `desk.mtm.run.main()` raises on (design §9.1)."""
    from desk.mtm.constants import (LEDGER_TOL_INR, MCX_PROXY_REPLICATION_TOL_INR_KG,
                                    REPLACEMENT_VS_P1_TOL_INR_T, RESIDUAL_TOL_INR)

    rows = []
    att = run.attribution[run.attribution["trade_id"] != BOOK_ID]
    for d, sub in att.groupby("date"):
        rows.append({"date": d, "check": "residual_max_abs", "value": float(sub["residual"].abs().max()),
                     "tolerance": RESIDUAL_TOL_INR, "scope": "trade-day"})

    # ledger identity: the valuation's own realised total against the day-by-day cash ledger
    for tid, tr in run.per_trade.items():
        worst = 0.0
        for d, a in tr.atts.items():
            worst = max(worst, abs(a.value_today.realised_pnl_inr - tr.funding.realised_pnl_cum.get(d, 0.0)))
        rows.append({"date": tr.days[-1], "check": "ledger_identity_max_abs", "value": worst,
                     "tolerance": LEDGER_TOL_INR, "scope": tid})

    rows.append({"date": run.days[-1], "check": "proxy_basis_max_abs",
                 "value": float(H.mcx_replication_max_inr_kg),
                 "tolerance": MCX_PROXY_REPLICATION_TOL_INR_KG, "scope": "inr_per_kg"})

    for tid, tr in run.per_trade.items():
        s = sum(val.realised_inr(tr.schedule, i, H) for i, f in enumerate(tr.schedule.flows) if f.pnl_class == BS)
        rows.append({"date": tr.days[-1], "check": "bs_flows_lifetime_sum", "value": float(s),
                     "tolerance": LEDGER_TOL_INR, "scope": tid})
        mtm_end = tr.atts[tr.days[-1]].mtm_inr
        rows.append({"date": tr.days[-1], "check": "terminal_mtm_abs", "value": abs(float(mtm_end)),
                     "tolerance": LEDGER_TOL_INR, "scope": tid})
        # CONTRACTS §7.3 stated as an independent sum: re-add every P&L cashflow from the schedule and the funding
        # accrual, and land on the trade's final cumulative P&L. `ledger_identity_max_abs` checks the same identity
        # through the daily ledger; this one bypasses the ledger, so the two together close both paths.
        end = tr.days[-1]
        cf_sum = sum(val.realised_inr(tr.schedule, i, H)
                     for i, f in enumerate(tr.schedule.flows) if f.pnl_class == PNL)
        gap = tr.atts[end].cum_pnl_inr - (cf_sum + tr.atts[end].funding_cum_inr)
        rows.append({"date": end, "check": "final_pnl_vs_cashflows", "value": float(gap),
                     "tolerance": LEDGER_TOL_INR, "scope": tid})

    worst_cip, worst_panel = replacement_vs_p1(H)
    rows.append({"date": run.days[-1], "check": "replacement_vs_p1_max_abs", "value": worst_cip,
                 "tolerance": REPLACEMENT_VS_P1_TOL_INR_T, "scope": "inr_per_mt (CIP 1m forward)"})
    rows.append({"date": run.days[-1], "check": "replacement_vs_p1_panelfx_max_abs", "value": worst_panel,
                 "tolerance": LEDGER_TOL_INR, "scope": "inr_per_mt (panel usdinr_fwd_1m)"})

    df = pd.DataFrame(rows)
    df["status"] = np.where(df["value"].abs() <= df["tolerance"], "PASS", "FAIL")
    return df.sort_values(["check", "date", "scope"], kind="mergesort").reset_index(drop=True)


def replacement_vs_p1(H: MarketHistory) -> tuple[float, float]:
    """Design §5.3's cross-phase control: `R` must equal Phase 1's goods + BCD + SWS + port on every parity week.

    Phase 1 is **recomputed** here rather than read from `parity_weekly.csv`, because that file rounds every INR
    column to 2 dp and four rounded components cannot reconcile to ₹0.01. Recomputing compares the two *formulas*
    on the same register and the same panel, which is the tie the design actually claims.
    """
    from desk.parity import model as parity_model

    parity = parity_model.compute(parity_model.build_inputs())
    worst_cip = worst_panel = 0.0
    for row in parity.itertuples(index=False):
        d = row.value_date.date()
        if d not in H.cal:
            continue
        M = H.state_at(d)
        HV = H.view(d)
        box = LANE_BOX[row.lane]
        p1 = row.goods_inr_t + row.bcd_inr_t + row.sws_inr_t + row.port_inr_t
        cip = curves.replacement_value(HV, M, d, row.grade, row.lane, box)
        panel = curves.replacement_value(HV, M, d, row.grade, row.lane, box, goods_fx=H.usdinr_fwd_1m(d))
        worst_cip = max(worst_cip, abs(cip - p1))
        worst_panel = max(worst_panel, abs(panel - p1))
    return worst_cip, worst_panel


# --------------------------------------------------------------------------------------------------- rounding
ROUNDING: Mapping[str, int] = {
    **{c: ROUND_INR for c in (
        *PNL_BUCKETS, "residual", "daily_pnl_inr", "cum_pnl_inr", "mtm_inr", "mtm_fixed_inr", "mtm_floating_inr",
        "realised_cum_inr", "leg_cum_pnl_inr", "leg_daily_pnl_inr", "fixture_vs_market_inr", "amount_inr",
        "amount_inr_est_at_trade_date", "mtm_ccy", "amount_ccy", "cash_balance_inr", "mcx_im_inr", "vm_inr",
        "cum_vm_inr", "txn_cost_inr", "contract_value_inr", "im_required_inr", "im_change_inr", "im_stress_012_inr",
        "im_stress_015_inr", "net_margin_cash_inr", "cum_margin_cash_inr", "funding_on_margin_inr",
        "buyer_receivable_inr", "buyer_presettlement_inr", "supplier_exposure_inr", "lme_fx_cross_inr",
        "lme_delta_inr_per_usd_t", "spread_delta_inr_per_usd_t", "inr_rate_delta_inr_per_bp",
        "usd_rate_delta_inr_per_bp", "wc_rate_delta_inr_per_bp", "mcx_basis_delta_inr_per_inr_kg",
        "freight_delta_inr_per_usd_t_jea_nsa", "freight_delta_inr_per_usd_t_usec_mun",
        "fx_delta_usd", "fx_delta_physical_usd", "fx_delta_forwards_usd", "fx_delta_mcx_usd",
        "customs_fx_delta_usd", "lme_delta_usd",
        *(f"grade_delta_inr_per_0p01_{g}" for g in GRADES))},
    **{c: ROUND_PRICE for c in ("px_usd_t", "px_inr_t", "px_inr_kg", "fx_rate_used", "fill_inr_kg",
                                "settle_inr_kg", "prev_settle_inr_kg", "lme_delta_mt", "lme_delta_physical_mt",
                                "lme_delta_mcx_mt", "qty_mt", "unsold_mt", "phys_purchased_mt", "phys_sold_mt",
                                "freight_open_mt_jea_nsa", "freight_open_mt_usec_mun", "notional_usd",
                                *(f"grade_exposure_mt_{g}" for g in GRADES))},
    **{c: ROUND_FRAC for c in ("fixed_frac", "hedge_ratio_lme_frac", "hedge_ratio_fx_frac",
                               "purchase_priced_frac", "sale_priced_frac", "tolerance")},
    # a control whose value rounds to 0.00 tells the reader nothing about how much headroom it has
    "value": 12,
}


def round_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Fixed float formats so a re-run is byte-identical (CONTRACTS §1.5, design §2)."""
    out = df.copy()
    for col, nd in ROUNDING.items():
        if col in out.columns and pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].round(nd)
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]) and col not in ROUNDING:
            out[col] = out[col].round(ROUND_PRICE)
    return out
