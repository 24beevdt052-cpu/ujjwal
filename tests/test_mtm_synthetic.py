"""Synthetic-market tests: the properties that must hold for *any* book, isolated from the real panel's noise.

The frame is the real LME trading calendar with controllable, constant market paths and a single injectable shock,
so that when one block moves, only its bucket may move. Tickets are built straight from `desk.book.schema`
dataclasses (no YAML, no validation) because these tests are about the engine's arithmetic, not the book's grammar.

The market overrides poke `MarketHistory`'s private caches on purpose: the point is to hold everything constant
*except* the block under test, which no public constructor argument can do.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from desk import config
from desk.book import schema as bs
from desk.mtm import engine, lifecycle, valuation as val
from desk.mtm.constants import RESIDUAL_TOL_INR
from desk.mtm.history import GRADES, MarketHistory
from desk.mtm.lifecycle import PNL
from desk.reporting.style import PNL_BUCKETS

BASE_CASH = 2500.0
BASE_SPREAD = -10.0            # panel sign: negative = contango
BASE_USDINR = 78.0
BASE_INR_RATE = 0.05
BASE_USD_RATE = 0.02
BASE_FREIGHT = {"JEA_NSA": 20.0, "USEC_MUN": 80.0}
BASE_GRADE_FACTOR = 0.80
BASE_WC_RATE = 0.10

START = dt.date(2022, 3, 1)
END = dt.date(2022, 10, 31)


# ------------------------------------------------------------------------------------------- synthetic market
def synthetic_history(*, cash=BASE_CASH, cash_path=None, usdinr=BASE_USDINR, spread=BASE_SPREAD,
                      customs_equals_spot=True, grade_factor=BASE_GRADE_FACTOR) -> MarketHistory:
    """The real LME calendar with flat market paths (and optionally a deterministic LME path)."""
    real = MarketHistory()
    days = [d for d in real.cal.days if dt.date(2021, 12, 1) <= d <= END]
    n = len(days)
    cash_series = [cash_path(i) if cash_path else cash for i in range(n)]
    panel = pd.DataFrame({
        "date": pd.to_datetime(days),
        "lme_cash_usd_t": cash_series,
        "lme_cash_3m_spread_usd_t": [spread] * n,
        "usdinr": [usdinr] * n,
        "inr_rate_3m_pa": [BASE_INR_RATE] * n,
        "usd_rate_3m_pa": [BASE_USD_RATE] * n,
        "freight_jea_nsa_usd_t": [BASE_FREIGHT["JEA_NSA"]] * n,
        "freight_usec_mun_usd_t": [BASE_FREIGHT["USEC_MUN"]] * n,
        "mcx_src": ["PROXY_IMPORT_PARITY"] * n,
        "mcx_al_m1_inr_kg": [0.0] * n,
        "mcx_al_m2_inr_kg": [0.0] * n,
        "usdinr_fwd_1m": [usdinr] * n,
    })
    # fill the MCX columns with the same duty-parity formula the panel uses, so the extracted basis is exactly zero
    cal = real.cal
    m1, m2 = [], []
    for d, c in zip(days, cash_series):
        uplift = real.duty_uplift(d)
        premium = float(config.value("mcx_domestic_premium_inr_kg", d))
        spot = c * usdinr / 1000.0 * uplift + premium
        for slot, out in ((0, m1), (1, m2)):
            month = cal.m1_month_on(d) + slot
            dte = max(0, (cal.mcx_panel_expiry(month) - d).days)
            out.append(spot * (1 + BASE_INR_RATE * dte / 365.0))
    panel["mcx_al_m1_inr_kg"] = m1
    panel["mcx_al_m2_inr_kg"] = m2

    H = MarketHistory(panel=panel)
    if customs_equals_spot:
        H._customs = {d: usdinr for d in H.cal.days}
    H._grade = {d: {g: grade_factor for g in GRADES} for d in H.cal.days}
    H._param_cache[("wc_rate_inr_pa", None)] = BASE_WC_RATE
    H._states.clear()
    return H


def _flat_wc(H: MarketHistory) -> MarketHistory:
    """Hold the working-capital rate flat too, so bucket (g) is pure carry and roll-down."""
    orig = H.params

    def provider(key, d=None):
        return BASE_WC_RATE if key == "wc_rate_inr_pa" else orig(key, d)

    H.params = provider
    H._param_cache.clear()
    H._states.clear()
    return H


# -------------------------------------------------------------------------------------------- synthetic ticket
def make_ticket(*, trade_id="T01", trade_date=dt.date(2022, 3, 7), bl=dt.date(2022, 3, 21), boxes=100,
                price_usd_t=2000.0, sale_price_inr_t=None, sale_date=None, mcx_lots=0,
                mcx_month="2022-06", mcx_entry=None, mcx_exit=dt.date(2022, 9, 1),
                fwd_notional=None, fwd_value_date=None, lane="USEC_MUN", grade="zorba") -> bs.Ticket:
    payload = float(config.value(f"container_payload_mt_{lifecycle.LANE_BOX[lane]}_{grade}"))
    sales = ()
    if sale_price_inr_t is not None:
        sales = (bs.Sale(sale_id="S1", buyer_id="BUY_X_01", contract_date=sale_date or trade_date,
                         lot_ids=("L1",), delivery_basis="FOR works (SIM)",
                         pricing=bs.SalePricing(type=bs.SalePricingType.FIXED, price_inr_t=sale_price_inr_t),
                         payment=bs.SalePayment(terms=bs.SalePaymentTerms.CREDIT, credit_days=30),
                         quality_passthrough=True),)
    tranches = ()
    if mcx_lots:
        tranches = (bs.McxTranche(hedge_id=f"{trade_id}-MCX-1", contract_month=mcx_month,
                                  direction=bs.HedgeDirection.SELL if mcx_lots > 0 else bs.HedgeDirection.BUY,
                                  lots=abs(mcx_lots), entry_date=mcx_entry or trade_date, exit_date=mcx_exit,
                                  exit_reason=bs.HedgeExitReason.UNWIND),)
    lines = ()
    if fwd_notional:
        lines = (bs.FxForward(fwd_id=f"{trade_id}-FX-1", booking_date=trade_date,
                              direction=bs.FxDirection.BUY_USD, notional_usd=fwd_notional,
                              value_date=fwd_value_date, matched_leg=bs.MatchedLeg.PURCHASE_INVOICE),)
    return bs.Ticket(
        trade_id=trade_id, status=bs.TicketStatus.EXECUTED, trade_date=trade_date, lane=bs.Lane(lane),
        grade=bs.Grade(grade), quantity_mt=boxes * payload,
        purchase=bs.Purchase(
            supplier_id="SUP_X_01", spa_ref="SPA/TEST (SIM)", incoterm=bs.Incoterm.CFR,
            named_place="CFR test (SIM)",
            pricing=bs.PurchasePricing(type=bs.PurchasePricingType.FIXED, price_usd_t=price_usd_t),
            payment=bs.LcTerms(instrument=bs.PaymentInstrument.LC_SIGHT, lc_open_date=trade_date,
                               issuing_bank="Test Bank (SIM)"),
            spa=bs.SpaTerms(isri_grade_spec="test")),
        shipment=bs.Shipment(laycan_start=bl, laycan_end=bl, load_port="test",
                             discharge_port=bs.LANE_PORT[bs.Lane(lane)],
                             lots=(bs.Lot(lot_id="L1", boxes=boxes, bl_date=bl, vessel="MV Test (SIM)",
                                          voyage="001 (SIM)"),)),
        sales=sales,
        rationale=bs.Rationale(text="synthetic fixture", parity_week_end=trade_date),
        hedges=bs.Hedges(mcx=bs.McxHedge(tranches=tranches), fx_forwards=bs.FxHedge(lines=lines)),
    )


def make_book(*tickets: bs.Ticket) -> bs.Book:
    cps = (bs.Counterparty(cp_id="SUP_X_01", name="Test Supplier (SIM)", role=bs.Role.SUPPLIER,
                           type=bs.CounterpartyType.PROCESSOR, country="US", location="test (SIM)",
                           profile=bs.CounterpartyProfile(relationship_start=dt.date(2020, 1, 1),
                                                          years_in_business=10, annual_turnover_inr=1e9,
                                                          prior_invoices_n=5)),
           bs.Counterparty(cp_id="BUY_X_01", name="Test Buyer (SIM)", role=bs.Role.BUYER,
                           type=bs.CounterpartyType.FOUNDRY, country="IN", location="test (SIM)",
                           credit_limit_inr=1e9,
                           profile=bs.CounterpartyProfile(relationship_start=dt.date(2020, 1, 1),
                                                          years_in_business=10, annual_turnover_inr=1e9,
                                                          prior_invoices_n=5)))
    return bs.Book(trades=tickets, counterparties=cps)


def bucket_totals(run: engine.BookRun, trade_id: str, legs: tuple[str, ...] | None = None) -> dict[str, float]:
    df = run.attribution_leg[run.attribution_leg["trade_id"] == trade_id]
    if legs is not None:
        df = df[df["leg_id"].isin(legs)]
    return {b: float(df[b].sum()) for b in PNL_BUCKETS}


# ------------------------------------------------------------------------------------------------- properties
def test_zero_market_move_leaves_only_carry():
    """Design §10 test 10: with every block flat, (a)–(f) and `new_deal` are zero and only (g) moves."""
    H = _flat_wc(synthetic_history())
    book = make_book(make_ticket(sale_price_inr_t=170_000.0))
    run = engine.run_book(book, H, with_exposures=False)
    tr = run.per_trade["T01"]
    quiet = [d for d in tr.days if d > dt.date(2022, 4, 1) and d < dt.date(2022, 4, 20)]
    assert quiet
    for d in quiet:
        totals = tr.atts[d].totals()
        for b in ("new_deal", "lme_flat", "cross_exchange_basis", "grade_spread", "freight", "fx",
                  "demurrage_penalty"):
            assert totals[b] == pytest.approx(0.0, abs=1e-6), (d, b, totals[b])
        assert abs(totals["roll_term_structure"]) > 0.0


def test_fx_forward_is_hedge_perfect_against_a_fixed_usd_payable():
    """Design §10 test 7: a 100% forward on the payable's own value date is flat in (e) and (g), every day."""
    H = _flat_wc(synthetic_history())
    ticket = make_ticket(sale_price_inr_t=170_000.0)
    payload = ticket.payload_mt_per_box
    notional = 100 * payload * 2000.0
    H0 = H
    sched = lifecycle.expand(ticket, make_book(ticket), END, END, H0)
    pay_date = sched.lot_dates["L1"].pay
    ticket = make_ticket(sale_price_inr_t=170_000.0, fwd_notional=notional, fwd_value_date=pay_date)
    book = make_book(ticket)
    run = engine.run_book(book, H, with_exposures=False)

    pair = ("PURCHASE:L1", "FX:T01-FX-1")
    totals = bucket_totals(run, "T01", pair)
    scale = abs(bucket_totals(run, "T01", ("PURCHASE:L1",))["fx"]) + 1.0
    assert abs(totals["fx"]) < 1e-6 * scale
    assert abs(totals["roll_term_structure"]) < 1e-6 * scale

    # the whole INR cost of the pair is the dealt forward rate: -notional x K
    from desk.mtm import curves
    K = curves.fx_forward_strike(H, ticket.trade_date, pay_date, +1)
    realised = sum(val.realised_inr(run.per_trade["T01"].schedule, i, H)
                   for i, f in enumerate(run.per_trade["T01"].schedule.flows) if f.leg_id in pair)
    assert realised == pytest.approx(-notional * K, rel=1e-9)


def test_new_deal_on_a_forward_is_exactly_the_bank_margin():
    """Design §6.2: a forward struck at the mid plus the bank's margin is worth -notional x margin on day one."""
    H = _flat_wc(synthetic_history())
    notional = 1_000_000.0
    ticket = make_ticket(sale_price_inr_t=170_000.0, fwd_notional=notional,
                         fwd_value_date=dt.date(2022, 6, 15))
    run = engine.run_book(make_book(ticket), H, with_exposures=False)
    margin = float(config.value("fx_forward_bank_margin_inr"))
    day_one = run.attribution_leg[(run.attribution_leg["leg_id"] == "FX:T01-FX-1")
                                  & (run.attribution_leg["date"] == ticket.trade_date)]
    assert float(day_one["new_deal"].iloc[0]) == pytest.approx(-notional * margin, abs=1e-6)


def test_mcx_short_offsets_the_physical_lme_move():
    """Design §10 test 8: an unsold fixed-price cargo hedged on its LME-equivalent delta nets out in bucket (a)."""
    H = _flat_wc(synthetic_history(cash_path=lambda i: BASE_CASH * (1.0 - 0.0015 * i)))
    # the cargo is never sold, so the hedge must run to the end of the engine horizon to cover the same exposure
    hedge_kwargs = dict(mcx_month="2022-11", mcx_exit=dt.date(2022, 10, 31))
    probe = make_ticket(mcx_lots=1, **hedge_kwargs)
    run0 = engine.run_book(make_book(probe), H, with_detail=False)
    e0 = run0.exposures[(run0.exposures["scope"] == "trade")
                        & (run0.exposures["date"] == probe.trade_date)].iloc[0]
    lot_lme_eq = float(e0["lme_delta_mcx_mt"]) / -1.0                     # one SELL lot's LME-equivalent tonnes
    phys_mt = float(e0["lme_delta_physical_mt"])
    lots = int(round(phys_mt / abs(lot_lme_eq)))
    assert lots > 0

    ticket = make_ticket(mcx_lots=lots, **hedge_kwargs)
    run = engine.run_book(make_book(ticket), H, with_exposures=False)
    legs = run.attribution_leg[run.attribution_leg["trade_id"] == "T01"].copy()
    legs["is_mcx"] = legs["leg_id"].str.startswith("MCX:")
    phys = float(legs.loc[~legs["is_mcx"], "lme_flat"].sum())
    hedge = float(legs.loc[legs["is_mcx"], "lme_flat"].sum())
    assert abs(phys) > 1e6                                                # the cargo really did move
    assert abs(phys + hedge) < 0.05 * abs(phys), (phys, hedge)


def test_buckets_are_linear_in_size():
    """Design §10 test 14: double the tonnage, the lots and the notional and every bucket doubles."""
    H = _flat_wc(synthetic_history(cash_path=lambda i: BASE_CASH * (1.0 - 0.001 * i)))
    small = make_ticket(trade_id="T01", boxes=50, mcx_lots=40, sale_price_inr_t=170_000.0,
                        fwd_notional=1_000_000.0, fwd_value_date=dt.date(2022, 6, 15))
    big = make_ticket(trade_id="T02", boxes=100, mcx_lots=80, sale_price_inr_t=170_000.0,
                      fwd_notional=2_000_000.0, fwd_value_date=dt.date(2022, 6, 15))
    run = engine.run_book(make_book(small, big), H, with_detail=False, with_exposures=False)
    a = bucket_totals(run, "T01")
    b = bucket_totals(run, "T02")
    for k in PNL_BUCKETS:
        assert b[k] == pytest.approx(2.0 * a[k], rel=1e-9, abs=1e-6), k


def test_residual_catches_a_planted_hidden_input():
    """Design D9: the ₹1 residual is a control. Plant a settled flow that keeps marking and it must fire."""
    H = _flat_wc(synthetic_history(cash_path=lambda i: BASE_CASH * (1.0 - 0.001 * i)))
    ticket = make_ticket(sale_price_inr_t=170_000.0)
    book = make_book(ticket)

    class BuggyCache(val.ScheduleCache):
        def get(self, t, C, E):
            sched = super().get(t, C, E)
            if not any(f.leg_type == "PLANTED_BUG" for f in sched.flows):
                bug = lifecycle.Flow(
                    t.trade_id, "PLANTED_BUG", "PLANTED_BUG", PNL, "INR", t.trade_date,
                    dt.date(2022, 4, 11), None,
                    # no fixing date: the amount keeps moving with the market AFTER it has settled, so the
                    # realised ledger and the mark stop agreeing — exactly the class of bug D9 is aimed at
                    lambda M, tau, HV: 1000.0 * M.lme_cash_usd_t)
                sched = replace(sched, flows=sched.flows + (bug,))
                self._cache[(t.trade_id, sched.contracts_asof, sched.events_asof)] = sched
            return sched

    cache = BuggyCache(book, H)
    run = engine.run_book(book, H, cache=cache, with_detail=False, with_exposures=False)
    worst = run.attribution[run.attribution["trade_id"] == "T01"]["residual"].abs().max()
    assert worst > RESIDUAL_TOL_INR, f"the planted bug slipped past the residual control ({worst})"


def test_revalue_book_broadcasts_over_monte_carlo_paths():
    """The Phase 4 API: array-valued shocks must return one column per path from the same valuation."""
    H = _flat_wc(synthetic_history())
    book = make_book(make_ticket(sale_price_inr_t=170_000.0, mcx_lots=20))
    d = dt.date(2022, 6, 10)
    paths = np.array([-0.10, 0.0, 0.10])
    out = val.revalue_book(book, H, d, shocks={"lme_cash_logret": paths})
    assert out.shape == (1, 3)
    scalar_mid = val.revalue_book(book, H, d)
    assert out[0, 1] == pytest.approx(scalar_mid[0, 0], abs=1e-6)
    assert out[0, 0] != out[0, 2]


def test_stress_events_are_only_accepted_through_the_api():
    H = _flat_wc(synthetic_history())
    book = make_book(make_ticket(sale_price_inr_t=170_000.0))
    d = dt.date(2022, 5, 20)            # the sale is invoiced 10-May and due 09-Jun: the receivable is live here
    base = val.revalue_book(book, H, d)[0, 0]
    default = val.revalue_book(book, H, d, extra_events=[
        val.StressEvent(kind="buyer_default", buyer_id="BUY_X_01", recovery_frac=0.4)])[0, 0]
    assert default < base
    with pytest.raises(KeyError):
        val.revalue_book(book, H, d, extra_events=[val.StressEvent(kind="not_a_stress")])


def test_freight_is_a_live_exposure_only_while_unfixed():
    """Design D12: a CFR cargo carries no freight price risk at all, because §5's grade factor is a CFR factor."""
    H = _flat_wc(synthetic_history())
    book = make_book(make_ticket(sale_price_inr_t=170_000.0))
    run = engine.run_book(book, H, with_detail=False, with_exposures=False)
    assert bucket_totals(run, "T01")["freight"] == pytest.approx(0.0, abs=1e-9)
