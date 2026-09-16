"""Adverse-event windows, counterfactual consistency and the block-isolation property, on the real panel."""

from __future__ import annotations

import datetime as dt

import pytest

from desk.book import schema as bs
from desk.mtm import engine, events as ev
from desk.mtm.constants import CRASH_FORTNIGHT_RETURN_DAYS, LEDGER_TOL_INR
from desk.mtm.history import MarketHistory, panel_days
from desk.paths import CONFIG_DIR


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


# ----------------------------------------------------------------------------------------------- window rules
def test_lme_crash_window_is_pinned(H):
    w = ev.lme_crash_window(H)
    assert (w.start, w.end) == (dt.date(2022, 3, 7), dt.date(2022, 7, 15))
    assert w.start_value == pytest.approx(3984.5)
    assert w.end_value == pytest.approx(2320.5)
    assert w.change_frac == pytest.approx(-0.4176, abs=5e-4)


def test_crash_fortnight_uses_the_ten_RETURN_convention(H):
    """CONTRACTS §7a.3 fixes the convention; the 10-observation reading picks a different fortnight."""
    ten_returns = ev.crash_fortnight(H, n_returns=CRASH_FORTNIGHT_RETURN_DAYS)
    assert (ten_returns.start, ten_returns.end) == (dt.date(2022, 4, 22), dt.date(2022, 5, 9))
    assert ten_returns.change_frac == pytest.approx(-0.1652, abs=5e-4)
    assert len(H.cal.between(ten_returns.start, ten_returns.end)) == CRASH_FORTNIGHT_RETURN_DAYS + 1

    nine_returns = ev.crash_fortnight(H, n_returns=CRASH_FORTNIGHT_RETURN_DAYS - 1)
    assert (nine_returns.start, nine_returns.end) == (dt.date(2022, 3, 7), dt.date(2022, 3, 18))
    assert nine_returns.change_frac == pytest.approx(-0.1516, abs=5e-4)
    assert nine_returns.start != ten_returns.start          # the off-by-one really does change the answer


def test_inr_depreciation_window_is_pinned(H):
    w = ev.inr_depreciation_window(H)
    assert (w.start, w.end) == (dt.date(2022, 4, 5), dt.date(2022, 7, 14))
    assert w.change_frac == pytest.approx(0.0624, abs=5e-4)


def test_logistics_window_cannot_start_before_the_void_call_report(book, run):
    w = ev.logistics_credit_window(book, run)
    assert w is not None
    assert w.start >= ev.VOID_CALL_DATE
    assert w.end <= dt.date(2022, 10, 31)


def test_freight_fell_through_the_window_so_event_3_carries_no_spike(H):
    for lane in ("JEA_NSA", "USEC_MUN"):
        assert ev._freight_change(H, lane) < -0.30


def test_hypothetical_freight_stress_is_labelled_on_every_row(book, H, run):
    stress = ev.freight_stress_hypothetical(book, H, run)
    assert len(stress)
    assert (stress["label"] == ev.HYPOTHETICAL_LABEL).all()


# ------------------------------------------------------------------------------------- counterfactual identity
def test_removing_the_forwards_costs_exactly_the_forward_legs_plus_their_funding(book, H, run):
    """Design §10 test 15: a counterfactual is the same engine minus one component, and it must decompose."""
    no_fwd = ev.counterfactual(book, H, "no_fx_forward", drop_instruments=frozenset({"fx_forward"}))
    last = run.days[-1]
    for tid, tr in run.per_trade.items():
        base = tr.atts[last].cum_pnl_inr
        cf = no_fwd.per_trade[tid].atts[last].cum_pnl_inr
        legs = run.attribution_leg[(run.attribution_leg["trade_id"] == tid)
                                   & (run.attribution_leg["leg_id"].str.startswith("FX:"))]
        fwd_pnl = float(legs[["new_deal", "lme_flat", "cross_exchange_basis", "grade_spread", "freight", "fx",
                              "demurrage_penalty", "roll_term_structure"]].to_numpy().sum())
        funding_diff = tr.atts[last].funding_cum_inr - no_fwd.per_trade[tid].atts[last].funding_cum_inr
        assert base - cf == pytest.approx(fwd_pnl + funding_diff, abs=LEDGER_TOL_INR)


def test_dropping_mcx_removes_every_margin_leg(book, H):
    no_mcx = ev.counterfactual(book, H, "no_mcx", drop_instruments=frozenset({"mcx"}))
    for tr in no_mcx.per_trade.values():
        assert not any(f.leg_id.startswith("MCX:") for f in tr.schedule.flows)


# ---------------------------------------------------------------------------------------- block isolation (§10.6)
def test_a_block_that_did_not_move_contributes_nothing(run, H):
    """Weekly freight and the step-path grade factors are flat on most days; their buckets must be exactly zero."""
    checked_freight = checked_grade = 0
    for tr in run.per_trade.values():
        for d in tr.days[1:]:
            prev = H.cal.prev(d)
            m_prev, m_now = H.state_at(prev), H.state_at(d)
            totals = tr.atts[d].totals()
            if m_prev.freight_usd_t == m_now.freight_usd_t:
                assert totals["freight"] == pytest.approx(0.0, abs=1e-9)
                checked_freight += 1
            if m_prev.grade_factor_frac == m_now.grade_factor_frac:
                assert totals["grade_spread"] == pytest.approx(0.0, abs=1e-9)
                checked_grade += 1
    assert checked_freight > 100
    assert checked_grade > 0


def test_mcx_source_switch_produces_a_non_zero_basis(book, H):
    """CONTRACTS §7.5: the third-party mirror is the only place the LME-MCX basis is visible — and never base P&L."""
    mirror = MarketHistory(mcx_source="mirror")
    d = dt.date(2022, 6, 10)
    assert any(v != 0.0 for v in mirror.state_at(d).mcx_basis_inr_kg.values())
    run = engine.run_book(book, mirror, with_detail=False, with_exposures=False)
    assert run.attribution["cross_exchange_basis"].abs().max() > 0.0


def test_grade_pit_variant_moves_both_contract_and_mark(book, H):
    """Design D13: the point-in-time grade mix is applied to marks AND terms together, never mixed."""
    pit = MarketHistory(grade_source="pit")
    d = dt.date(2022, 4, 11)
    assert pit.state_at(d).grade_factor_frac != H.state_at(d).grade_factor_frac
    run = engine.run_book(book, pit, with_detail=False, with_exposures=False)
    assert run.attribution["residual"].abs().max() <= 1.0
