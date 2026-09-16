"""The Phase 3 sign-off controls, run on the checked-in example book (`config/*.example.yaml`).

These are the tests that decide whether the engine can be believed: the attribution residual, the cumulative-P&L
identity, the terminal state, the balance-sheet lifetime sum, determinism and the performance budget.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import time

import pandas as pd
import pytest

from desk import HORIZON_END
from desk.book import schema as bs
from desk.mtm import engine, valuation as val
from desk.mtm.constants import LEDGER_TOL_INR, RESIDUAL_TOL_INR
from desk.mtm.history import MarketHistory, panel_days
from desk.mtm.lifecycle import BS, PNL
from desk.paths import CONFIG_DIR
from desk.reporting.style import PNL_BUCKETS

PERFORMANCE_BUDGET_S = 60.0


@pytest.fixture(scope="module")
def H() -> MarketHistory:
    return MarketHistory()


@pytest.fixture(scope="module")
def book() -> bs.Book:
    return bs.load_book(CONFIG_DIR / "trades.example.yaml", CONFIG_DIR / "counterparties.example.yaml",
                        panel_days=panel_days())


@pytest.fixture(scope="module")
def run(book, H) -> engine.BookRun:
    return engine.run_book(book, H)


# ------------------------------------------------------------------------------------------------- additivity
def test_attribution_residual_is_within_one_rupee(run):
    trades = run.attribution[run.attribution["trade_id"] != engine.BOOK_ID]
    assert trades["residual"].abs().max() <= RESIDUAL_TOL_INR


def test_buckets_sum_to_the_daily_pnl(run):
    df = run.attribution
    total = df[list(PNL_BUCKETS)].sum(axis=1) + df["residual"]
    assert (total - df["daily_pnl_inr"]).abs().max() < 1e-6


def test_book_pricing_fractions_are_tonnage_weighted(run, book):
    """`purchase_priced_frac` / `sale_priced_frac` at BOOK scope read "share of the book that is priced".

    They are the one pair of columns that is not a sum of the trade rows, so the weighting has to be stated. An
    unweighted mean of tickets makes a 1,200 MT ticket count as much as a 2,520 MT one; the book row is weighted by
    each ticket's contracted tonnage over the trades on the book that day.
    """
    qty = {t.trade_id: t.quantity_mt for t in book.trades}
    e = run.exposures
    trade, bk = e[e["scope"] == "trade"], e[e["scope"] == "book"].set_index("date")
    for col in ("purchase_priced_frac", "sale_priced_frac"):
        for d, sub in trade.groupby("date"):
            w = sub["trade_id"].map(qty).to_numpy(float)
            want = float((sub[col].to_numpy(float) * w).sum() / w.sum())
            assert bk.loc[d, col] == pytest.approx(want, abs=1e-9)
        assert (bk[col] >= -1e-12).all() and (bk[col] <= 1 + 1e-12).all()


def test_no_panel_freight_move_means_no_freight_bucket(run, H):
    """Bucket (d) is exactly zero on a day neither lane's panel freight moved (the docs/30 §4.3 complement)."""
    att = run.attribution[run.attribution["trade_id"] != engine.BOOK_ID]
    days = list(run.days)
    still = {d for p, d in zip(days, days[1:])
             if all(H.freight_usd_t(d, ln) == H.freight_usd_t(p, ln) for ln in ("JEA_NSA", "USEC_MUN"))}
    sub = att[att["date"].isin(still)]
    assert len(sub) > 0
    assert sub["freight"].abs().max() == 0.0


def test_leg_rows_sum_exactly_to_the_trade_rows(run):
    """Σ legs == the trade row. Leg rows are sparse: a day on which a leg moves nothing produces no row."""
    legs = run.attribution_leg.groupby(["date", "trade_id"], as_index=False)[list(PNL_BUCKETS)].sum()
    trades = run.attribution[run.attribution["trade_id"] != engine.BOOK_ID]
    merged = trades.merge(legs, on=["date", "trade_id"], how="left", suffixes=("", "_leg")).fillna(0.0)
    assert len(merged) == len(trades)
    for b in PNL_BUCKETS:
        assert (merged[b] - merged[f"{b}_leg"]).abs().max() < 1e-6


def test_book_rows_are_the_sum_of_the_trades(run):
    book_rows = run.attribution[run.attribution["trade_id"] == engine.BOOK_ID].set_index("date")
    trades = (run.attribution[run.attribution["trade_id"] != engine.BOOK_ID]
              .groupby("date")[list(PNL_BUCKETS) + ["daily_pnl_inr", "cum_pnl_inr"]].sum())
    aligned = book_rows.loc[trades.index]
    for c in list(PNL_BUCKETS) + ["daily_pnl_inr", "cum_pnl_inr"]:
        assert (aligned[c] - trades[c]).abs().max() < 1e-6


# ---------------------------------------------------------------------------------------------- the identity
def test_cumulative_pnl_equals_realised_plus_funding_plus_mtm_every_day(run):
    """CONTRACTS §7.3, checked on both paths: the valuation's realised total and the cash ledger's must agree."""
    for tr in run.per_trade.values():
        for d, a in tr.atts.items():
            assert a.cum_pnl_inr == pytest.approx(a.realised_cum_inr + a.funding_cum_inr + a.mtm_inr, abs=1e-6)
            assert a.value_today.realised_pnl_inr == pytest.approx(a.realised_cum_inr, abs=LEDGER_TOL_INR)


def test_daily_pnl_is_the_first_difference_of_cumulative_pnl(run):
    for tr in run.per_trade.values():
        prev = 0.0
        for d in tr.days:
            a = tr.atts[d]
            assert a.daily_pnl_inr == pytest.approx(a.cum_pnl_inr - prev, abs=1e-6)
            prev = a.cum_pnl_inr


def test_final_cumulative_pnl_equals_the_sum_of_all_cashflows(run, H):
    """At the horizon nothing is unsettled, so cumulative P&L is exactly the realised flows plus funding."""
    for tr in run.per_trade.values():
        last = tr.atts[tr.days[-1]]
        flows = sum(val.realised_inr(tr.schedule, i, H)
                    for i, f in enumerate(tr.schedule.flows) if f.pnl_class == PNL)
        assert last.mtm_inr == pytest.approx(0.0, abs=LEDGER_TOL_INR)
        assert last.cum_pnl_inr == pytest.approx(flows + last.funding_cum_inr, abs=LEDGER_TOL_INR)


def test_balance_sheet_flows_net_to_zero_over_the_life(run, H):
    """IGST paid and credited, MCX initial margin posted and returned: cash and funding, never P&L (§7a.5)."""
    for tr in run.per_trade.values():
        s = sum(val.realised_inr(tr.schedule, i, H)
                for i, f in enumerate(tr.schedule.flows) if f.pnl_class == BS)
        assert abs(s) <= LEDGER_TOL_INR
        last = tr.atts[tr.days[-1]]
        assert last.cash_balance_inr == pytest.approx(last.realised_cum_inr, abs=LEDGER_TOL_INR)


def test_new_deal_is_the_whole_first_day_value(run):
    """CONTRACTS §7.2: a ticket has Pi = 0 through step 7 on its trade date, so day one is entirely `new_deal`."""
    for tr in run.per_trade.values():
        first = tr.atts[tr.days[0]]
        totals = first.totals()
        assert first.cum_pnl_inr == pytest.approx(totals["new_deal"], abs=1e-6)
        for b in PNL_BUCKETS:
            if b != "new_deal":
                assert totals[b] == pytest.approx(0.0, abs=1e-6)


def test_cross_exchange_basis_is_zero_on_a_base_run(run):
    """Design D4: with the panel MCX proxy the measured basis is empty BY CONSTRUCTION, and must say so."""
    assert run.attribution["cross_exchange_basis"].abs().max() == 0.0


def test_every_cashflow_settles_inside_the_horizon(run):
    for tr in run.per_trade.values():
        assert tr.schedule.close_date <= HORIZON_END


# --------------------------------------------------------------------------------------------------- controls
def test_all_pnl_controls_pass(run, H):
    controls = engine.controls(run, H)
    failed = controls[controls["status"] == "FAIL"]
    assert failed.empty, failed.to_string(index=False)


def test_mcx_variation_margin_telescopes_to_the_settle_difference(book, H, run):
    vm = engine.mcx_variation_margin(book, H, run)
    lot_kg = float(H.param("mcx_al_lot_mt")) * 1000.0
    for (tid, hid), sub in vm.groupby(["trade_id", "hedge_id"]):
        sub = sub.sort_values("date")
        ticket = book.trade(tid)
        tr = next(x for x in ticket.hedges.mcx.tranches if x.hedge_id == hid)
        sign = 1 if tr.direction is bs.HedgeDirection.BUY else -1
        expected = sign * tr.lots * lot_kg * (H.mcx_settle(tr.exit_date, tr.contract_month)
                                              - H.mcx_settle(tr.entry_date, tr.contract_month))
        assert float(sub["cum_vm_inr"].iloc[-1]) == pytest.approx(expected, abs=0.01)
        assert float(sub["im_required_inr"].iloc[-1]) == 0.0      # margin comes back at exit


def test_mtm_daily_leg_pnl_reconciles_to_the_trade(run):
    """Σ over legs of `leg_cum_pnl_inr` (funding included) is the trade's cumulative P&L."""
    last = run.mtm[run.mtm["date"] == run.days[-1]]
    for tid, sub in last.groupby("trade_id"):
        cum = run.attribution[(run.attribution["trade_id"] == tid)
                              & (run.attribution["date"] == run.days[-1])]["cum_pnl_inr"].iloc[0]
        assert float(sub["leg_cum_pnl_inr"].sum()) == pytest.approx(cum, abs=LEDGER_TOL_INR)


def test_exposures_book_rows_sum_the_trade_rows(run):
    e = run.exposures
    bookr = e[e["scope"] == "book"].set_index("date")
    trades = e[e["scope"] == "trade"].groupby("date")[["lme_delta_mt", "fx_delta_usd", "mtm_inr"]].sum()
    for c in ("lme_delta_mt", "fx_delta_usd", "mtm_inr"):
        assert (bookr.loc[trades.index, c] - trades[c]).abs().max() < 1e-6


def test_exposure_delta_predicts_a_small_revaluation(book, H, run):
    """The bump deltas are the derivative of the same Pi: a 1 USD/t move must reprice to the delta."""
    d = dt.date(2022, 6, 10)
    row = run.exposures[(run.exposures["scope"] == "book") & (run.exposures["date"] == d)].iloc[0]
    base = val.revalue_book(book, H, d).sum()
    up = val.revalue_book(book, H, d, shocks={"lme_cash_logret": math.log(1 + 1.0 / H.cash(d))}).sum()
    assert (up - base) == pytest.approx(row["lme_delta_inr_per_usd_t"], rel=1e-3)


# --------------------------------------------------------------------------------------- determinism / budget
def _digest(df: pd.DataFrame) -> str:
    return hashlib.sha256(engine.round_frame(df).to_csv(index=False, lineterminator="\n",
                                                        date_format="%Y-%m-%d").encode()).hexdigest()


def test_two_independent_runs_are_byte_identical(book):
    a = engine.run_book(book, MarketHistory())
    b = engine.run_book(book, MarketHistory())
    for name in ("attribution", "attribution_leg", "mtm", "exposures"):
        assert _digest(getattr(a, name)) == _digest(getattr(b, name)), name


def test_full_book_run_is_inside_the_performance_budget(book):
    t0 = time.time()
    H = MarketHistory()
    r = engine.run_book(book, H)
    engine.mcx_variation_margin(book, H, r)
    engine.trade_cashflows(book, H, r.cache)
    elapsed = time.time() - t0
    assert elapsed < PERFORMANCE_BUDGET_S, f"full book run took {elapsed:.1f}s"


def test_trade_cashflows_realised_scenario_reconciles_to_the_ledger(book, H, run):
    cf = engine.trade_cashflows(book, H, run.cache)
    realised = cf[cf["scenario"] == "REALISED"]
    for tid, tr in run.per_trade.items():
        pnl = realised[(realised["trade_id"] == tid) & (realised["pnl_class"] == PNL)]["amount_inr"].sum()
        last = tr.atts[tr.days[-1]]
        assert pnl == pytest.approx(last.realised_cum_inr, abs=LEDGER_TOL_INR)
        allflows = realised[realised["trade_id"] == tid]["amount_inr"].sum()
        assert allflows == pytest.approx(last.cash_balance_inr, abs=LEDGER_TOL_INR)


def test_fx_forward_mtm_equals_covered_interest_parity(book, H, run):
    """An open forward marks at `sign x notional x (CIP forward to its value date - the dealt rate)`, exactly."""
    from desk.mtm import curves

    checked = 0
    for ticket in book.trades:
        for fwd in ticket.hedges.fx_forwards.lines:
            sign = 1 if fwd.direction is bs.FxDirection.BUY_USD else -1
            K = curves.fx_forward_strike(H, fwd.booking_date, fwd.value_date, sign)
            settle = fwd.cancel_date or fwd.value_date
            for d in H.cal.between(fwd.booking_date, settle):
                row = run.mtm[(run.mtm["date"] == d) & (run.mtm["trade_id"] == ticket.trade_id)
                              & (run.mtm["leg_id"] == f"FX:{fwd.fwd_id}")]
                if not len(row) or d == settle:
                    continue                       # on the settle date the leg is realised, not marked
                expected = sign * fwd.notional_usd * (
                    curves.fx_x(H.view(d), H.state_at(d), d, fwd.value_date) - K)
                assert float(row["mtm_inr"].iloc[0]) == pytest.approx(expected, abs=0.01)
                checked += 1
    assert checked > 50
