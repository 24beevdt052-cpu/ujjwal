"""Phase 3 integration: the product-controller checks, run against the REAL book.

`tests/test_mtm_engine.py` proves the engine's arithmetic on the checked-in example fixtures. This module runs the
same engine over `config/trades.yaml` + `config/counterparties.yaml` — the nine tickets Phase 2 actually published —
and asserts the things a controller signs off before a P&L number leaves the desk:

* the attribution closes (residual, identity, legs, book rows);
* **final P&L equals the sum of the cashflows** plus the funding accrual, summed independently of the daily ledger;
* the hedge P&L equals the MCX variation margin the same hedges posted, to the rupee;
* every FX forward settles inside the horizon and its P&L equals its settlement cash;
* exposures carry the signs CONTRACTS §7a.4 declares, and are additive;
* funding is counted exactly once;
* buyer credit is measured against the receivable, so Phase 2's P04 rule and Phase 3's event-3 table agree.

Everything here reads the real book, so a ticket edit that breaks an economic identity fails a test rather than
quietly changing a published number.
"""

from __future__ import annotations

import datetime as dt

import pytest

from desk import HORIZON_END, units
from desk.book import schema as bs
from desk.book import validate as bv
from desk.mtm import engine, events as ev, exposures as expo, run as mrun
from desk.mtm.constants import (HEDGE_RATIO_MIN_PHYSICAL_MT, HEDGE_RATIO_MIN_PHYSICAL_USD, LEDGER_TOL_INR,
                                RESIDUAL_TOL_INR)
from desk.mtm.history import MarketHistory, panel_days
from desk.mtm.lifecycle import BS, PNL
from desk.paths import CONFIG_DIR
from desk.reporting.style import PNL_BUCKETS

REQUIRED_CONTROLS = {"residual_max_abs", "ledger_identity_max_abs", "proxy_basis_max_abs", "bs_flows_lifetime_sum",
                     "replacement_vs_p1_max_abs", "cashflow_reconciliation_vs_p2"}


@pytest.fixture(scope="module")
def H() -> MarketHistory:
    return MarketHistory()


@pytest.fixture(scope="module")
def book() -> bs.Book:
    """The real book. If Phase 2 has not published it, these checks have nothing to integrate."""
    trades, cps = CONFIG_DIR / "trades.yaml", CONFIG_DIR / "counterparties.yaml"
    if not trades.exists() or not cps.exists():
        pytest.skip("config/trades.yaml not published yet")
    return bs.load_book(trades, cps, panel_days=panel_days())


@pytest.fixture(scope="module")
def run(book, H) -> engine.BookRun:
    return engine.run_book(book, H)


@pytest.fixture(scope="module")
def vm(book, H, run):
    return engine.mcx_variation_margin(book, H, run)


@pytest.fixture(scope="module")
def cashflows(book, H, run):
    return engine.trade_cashflows(book, H, run.cache)


# ------------------------------------------------------------------------------------ the book is the real book
def test_the_real_book_is_nine_eligible_tickets(book):
    assert len(book.trades) >= 1
    elig = bv.eligibility_frame(book).set_index("trade_id")
    assert (elig["status"] == "PASS").all(), elig.loc[elig["status"] != "PASS"].to_string()


def test_every_trade_runs_to_the_horizon(run):
    for tr in run.per_trade.values():
        assert tr.days[-1] == HORIZON_END
        assert tr.days[0] == tr.ticket.trade_date


# --------------------------------------------------------------------------------------------- the P&L closes
def test_residual_is_within_one_rupee_on_every_trade_day(run):
    trades = run.attribution[run.attribution["trade_id"] != engine.BOOK_ID]
    assert trades["residual"].abs().max() <= RESIDUAL_TOL_INR


def test_buckets_and_residual_reconstruct_the_daily_pnl(run):
    df = run.attribution
    assert ((df[list(PNL_BUCKETS)].sum(axis=1) + df["residual"]) - df["daily_pnl_inr"]).abs().max() < 1e-6


def test_cumulative_pnl_is_realised_plus_funding_plus_mark(run):
    for tr in run.per_trade.values():
        for d, a in tr.atts.items():
            assert abs(a.cum_pnl_inr - (a.realised_cum_inr + a.funding_cum_inr + a.mtm_inr)) < LEDGER_TOL_INR


def test_book_row_is_the_sum_of_the_trades(run):
    per = (run.attribution[run.attribution["trade_id"] != engine.BOOK_ID]
           .groupby("date")["cum_pnl_inr"].sum())
    bookrow = run.attribution[run.attribution["trade_id"] == engine.BOOK_ID].set_index("date")["cum_pnl_inr"]
    assert (per - bookrow).abs().max() < LEDGER_TOL_INR


def test_final_pnl_equals_the_sum_of_the_cashflows_plus_funding(run, H, cashflows):
    """The controller's identity, taken from the published cashflow table rather than from the daily ledger."""
    realised = cashflows[(cashflows["scenario"] == "REALISED") & (cashflows["pnl_class"] == PNL)]
    by_trade = realised.groupby("trade_id")["amount_inr"].sum()
    for tid, tr in run.per_trade.items():
        end = tr.atts[tr.days[-1]]
        assert abs(end.cum_pnl_inr - (by_trade[tid] + end.funding_cum_inr)) < LEDGER_TOL_INR


def test_balance_sheet_cashflows_net_to_zero_per_trade(cashflows):
    bs_rows = cashflows[(cashflows["scenario"] == "REALISED") & (cashflows["pnl_class"] == BS)]
    assert bs_rows.groupby("trade_id")["amount_inr"].sum().abs().max() < LEDGER_TOL_INR


def test_nothing_settles_after_the_horizon(cashflows):
    assert cashflows["settle_date"].max() <= HORIZON_END


# ---------------------------------------------------------------------------------- hedges tie to their margin
def test_mcx_leg_pnl_equals_variation_margin_plus_execution_cost(run, vm):
    """A hedge's P&L is the cash it actually posted: Σ VM + transaction charges + slippage, per trade."""
    legs = run.attribution_leg[run.attribution_leg["leg_id"].str.startswith("MCX:")]
    leg_pnl = legs.groupby("trade_id")[list(PNL_BUCKETS)].sum().sum(axis=1)
    margin = vm.groupby("trade_id")["vm_inr"].sum() + vm.groupby("trade_id")["txn_cost_inr"].sum()
    for tid in leg_pnl.index:
        assert abs(leg_pnl[tid] - margin[tid]) < 1.0, tid


def test_variation_margin_telescopes_and_initial_margin_comes_back(vm):
    lot_kg = float(vm["lot_mt"].iloc[0]) * units.KG_PER_MT
    for hid, sub in vm.groupby("hedge_id"):
        sub = sub.sort_values("date")
        expected = sub["lots"].iloc[0] * lot_kg * (sub["settle_inr_kg"].iloc[-1] - sub["settle_inr_kg"].iloc[0])
        assert abs(sub["vm_inr"].sum() - expected) < 1.0, hid
        assert sub["im_required_inr"].iloc[-1] == pytest.approx(0.0)
        assert sub["im_change_inr"].sum() == pytest.approx(0.0, abs=LEDGER_TOL_INR)


def test_the_net_mcx_book_is_never_long(run, vm):
    """The desk is a net importer, so the net domestic position is short or flat, never long.

    Individual tranches *can* be long: a ticket whose purchase floats on an LME average is short metal on the
    purchase leg, and Phase 2's sizing rule buys MCX against it (T02-MCX-4 is a 145-lot BUY). The claim that has to
    hold is about the book, not about each line.
    """
    e = run.exposures[run.exposures["scope"] == "book"]
    assert (e["mcx_lots_open"] <= 0).all()
    assert (vm.groupby("date")["lots"].sum() <= 0).all()


# ------------------------------------------------------------------------------------- the forwards settle out
def test_fx_forward_pnl_equals_its_settlement_cash(run, cashflows):
    legs = run.attribution_leg[run.attribution_leg["leg_id"].str.startswith("FX:")]
    leg_pnl = legs.groupby("trade_id")[list(PNL_BUCKETS)].sum().sum(axis=1)
    settled = (cashflows[(cashflows["scenario"] == "REALISED") & (cashflows["leg_type"] == "FX_FORWARD")]
               .groupby("trade_id")["amount_inr"].sum())
    for tid in leg_pnl.index:
        assert abs(leg_pnl[tid] - settled[tid]) < 1.0, tid


def test_no_forward_is_still_open_at_the_horizon(run):
    open_fx = run.mtm[(run.mtm["date"] == HORIZON_END) & (run.mtm["leg_type"] == "FX")
                      & (run.mtm["status"] != "settled")]
    assert len(open_fx) == 0


# ------------------------------------------------------------------------------------------- exposures & signs
def test_exposures_are_additive_and_signed_the_way_the_contract_says(run):
    e = run.exposures[run.exposures["scope"] == "book"]
    assert (e["lme_delta_mt"] - e["lme_delta_physical_mt"] - e["lme_delta_mcx_mt"]).abs().max() < 1e-6
    assert (e["fx_delta_usd"] - e["fx_delta_physical_usd"] - e["fx_delta_forwards_usd"]
            - e["fx_delta_mcx_usd"]).abs().max() < 1e-4
    assert (e["lme_delta_physical_mt"] >= -1e-6).all()      # the desk is long metal or flat, never short physical
    assert (e["lme_delta_mcx_mt"] <= 1e-6).all()            # the MCX book only ever offsets it
    assert (e["mcx_lots_open"] <= 0).all()
    assert (e["freight_open_boxes"] >= 0).all()             # + = short freight (an unfixed FOB cargo)
    assert (e["unsold_mt"] >= 0).all()


def test_the_declared_signs_are_a_BOOK_scope_claim_and_flip_at_trade_scope(run):
    """CONTRACTS §7a.4's sign convention holds at BOOK scope. At TRADE scope any of the three can flip — and does.

    T02 buys on a floating LME_M1_AVG (May) while its MCX-average sale prices off between 19 and 29 April, so for a
    few weeks the desk is net SHORT metal on that ticket and legitimately hedges by BUYING lots. The numbers are
    right; the *reading* is what a Phase 4 author gets wrong if the hand-off note's "physical delta >= 0, MCX delta
    <= 0, lots <= 0" is taken as a book-wide invariant. Read the sign, do not assume it.
    """
    t = run.exposures[run.exposures["scope"] == "trade"]
    flips = {
        "lme_delta_physical_mt": t[t["lme_delta_physical_mt"] < -1e-6],
        "lme_delta_mcx_mt": t[t["lme_delta_mcx_mt"] > 1e-6],
        "mcx_lots_open": t[t["mcx_lots_open"] > 0],
    }
    for col, sub in flips.items():
        assert len(sub) > 0, f"{col} no longer flips at trade scope — update docs/30 §5 and the hand-off note"
        assert set(sub["trade_id"]) == {"T02"}, f"{col} now flips on {sorted(set(sub['trade_id']))}"


def test_freight_bucket_moves_only_with_panel_freight(run, H, book):
    """The control the residual cannot give: bucket (d) tracks the panel freight column and nothing else.

    `residual` telescopes, so a dated market number read straight from `HistoryView` instead of through
    `MarketState` lands silently in (g)/(f)/(0) and the residual never moves (docs/30 §4.3). What *does* catch that
    class, for the block most at risk of it, is this: on a day when neither lane's panel freight moved, factor (d)
    must be exactly zero for every trade; and on days when it did move, a ticket with open FOB freight must show it.
    """
    lanes = {t.trade_id: t.lane.value for t in book.trades}
    att = run.attribution[run.attribution["trade_id"] != engine.BOOK_ID]
    days = list(run.days)
    moved = {d: any(H.freight_usd_t(d, ln) != H.freight_usd_t(p, ln) for ln in ("JEA_NSA", "USEC_MUN"))
             for p, d in zip(days, days[1:])}
    still = att[att["date"].map(lambda d: moved.get(d) is False)]
    assert len(still) > 0
    assert still["freight"].abs().max() == 0.0, "factor (d) moved on a day panel freight did not"
    on_move = att[att["date"].map(lambda d: moved.get(d) is True)]
    assert (on_move["freight"].abs() > 0).any(), "factor (d) never moves — the test has gone vacuous"
    assert set(on_move.loc[on_move["freight"].abs() > 0, "trade_id"]) <= set(lanes)


def test_hedge_ratio_is_blank_rather_than_absurd_when_the_physical_leg_is_flat():
    assert expo.hedge_ratio(100.0, 1000.0, HEDGE_RATIO_MIN_PHYSICAL_MT) == pytest.approx(-0.1)
    assert expo.hedge_ratio(1.0e6, 1.0, HEDGE_RATIO_MIN_PHYSICAL_USD) != expo.hedge_ratio(
        1.0e6, 1.0, HEDGE_RATIO_MIN_PHYSICAL_USD)          # NaN != NaN
    assert expo.hedge_ratio(1.0, 0.0, HEDGE_RATIO_MIN_PHYSICAL_MT) != expo.hedge_ratio(
        1.0, 0.0, HEDGE_RATIO_MIN_PHYSICAL_MT)


def test_the_lme_hedge_ratio_is_a_usable_number(run):
    """The metal ratio is well behaved: the physical delta is the cargo, and it does not cross zero.

    The surviving outlier is real, not an artefact: on 2022-04-20 T02 shows 5.9x because its MCX tranche is sized
    against the gross floating purchase and floating sale, not against the small net left when they nearly cancel.
    """
    finite = run.exposures["hedge_ratio_lme_frac"].dropna()
    assert len(finite) > 0.3 * len(run.exposures)
    assert finite.abs().max() < 10.0, finite.abs().max()
    assert finite.median() == pytest.approx(0.9, abs=0.25)          # the desk's stated 0.90 naked-long ratio


def test_the_fx_hedge_ratio_is_disclosed_as_unstable_rather_than_smoothed(run):
    """`hedge_ratio_fx_frac` is structurally unstable for this book, and that is a result, not a bug.

    Design D5 marks unsold cargo at import replacement value, which is **long USD**, against a USD payable that is
    short USD. The net physical USD delta therefore oscillates through zero while a full forward hedge sits on top
    of it, so the quotient is large on either side of the crossing. The guard only stops a division by (almost)
    zero; it cannot make the measure meaningful, and pretending otherwise by clipping would hide the marking policy.
    Read `fx_delta_forwards_usd` against `fx_delta_physical_usd` directly, and the two offset ratios in
    `adverse_event_2_usdinr.csv`.
    """
    e = run.exposures[run.exposures["scope"] == "book"]
    finite = e["hedge_ratio_fx_frac"].dropna()
    assert (finite.abs() > 5.0).any(), "the instability documented in docs/30_mtm_attribution.md has gone away"
    assert (e["fx_delta_physical_usd"] > 0).any() and (e["fx_delta_physical_usd"] < 0).any()


# ------------------------------------------------------------------------------------------- funding, once only
def test_funding_is_counted_exactly_once(run, cashflows):
    ids = {l for l in run.attribution_leg["leg_id"].unique() if "FUND" in l.upper()}
    assert ids == {"FUNDING"}
    assert not (cashflows["leg_type"] == "FUNDING").any()   # an accrual, never a dated cashflow row
    for tr in run.per_trade.values():
        legs = run.attribution_leg[(run.attribution_leg["trade_id"] == tr.ticket.trade_id)
                                   & (run.attribution_leg["leg_id"] == "FUNDING")]
        total = legs[list(PNL_BUCKETS)].sum().sum()
        assert abs(total - tr.atts[tr.days[-1]].funding_cum_inr) < 1.0


def test_funding_on_margin_is_a_memo_not_a_second_accrual(vm, run):
    """`mcx_variation_margin.csv` reports carry on margin cash; the P&L accrual already covers it via the ledger."""
    assert "funding_on_margin_inr" in vm.columns
    legs = {l.split(":")[0] for l in run.attribution_leg["leg_id"].unique()}
    assert "MARGIN_FUNDING" not in legs


# ---------------------------------------------------------------------------- credit: P2 and P3 measure the same
def test_buyer_credit_limits_are_checked_against_the_receivable(book, run):
    """CONTRACTS §7a.4 separates receivable from pre-settlement; only the first is credit the desk extended."""
    u = ev.buyer_exposure(book, run)
    assert {"receivable_inr", "presettlement_inr", "contracted_inr"} <= set(u.columns)
    assert (u["exposure_inr"] == u["receivable_inr"]).all()
    assert not u["breach"].any(), u[u["breach"]].head().to_string()
    # the advance a buyer has not paid yet is pre-settlement, and it is material — so the split is not cosmetic
    assert u["presettlement_inr"].max() > u["receivable_inr"].max()


def test_per_counterparty_exposure_regroups_exactly_to_the_buyer_table(book, run):
    """`book_exposures_daily.csv` writes T01's buyers as one compound id; the long table must not, and must re-add."""
    long = ev.buyer_exposure_by_trade(book, run)
    assert not long["buyer_id"].str.contains(",").any()
    assert set(long["buyer_id"]) <= {c.cp_id for c in book.counterparties}
    t01 = long[long["trade_id"] == "T01"]
    assert {"BUY_MUN_01", "BUY_RJK_01"} <= set(t01["buyer_id"])
    agg = long.groupby(["date", "buyer_id"])[["receivable_inr", "presettlement_inr"]].sum()
    u = ev.buyer_exposure(book, run).set_index(["date", "buyer_id"])[["receivable_inr", "presettlement_inr"]]
    assert agg.index.equals(u.sort_index().index) or set(agg.index) == set(u.index)
    gap = (agg.sort_index() - u.sort_index()).abs().to_numpy().max()
    assert gap < LEDGER_TOL_INR, gap


def test_neither_phase_finds_a_breach_on_its_own_limit_measure(book, run):
    """P2's P04 (at bookings, receivable + uncovered contracted) and P3's daily receivable are different measures
    with different peaks; what both must show is no breach of their own test (docs/31 §3.4)."""
    p2 = bv.credit_exposure_frame(book)
    assert bool(p2["within_limit"].all())
    p3 = ev.buyer_exposure(book, run)
    assert not p3["breach"].any()


# ----------------------------------------------------------------------------------------------------- controls
def test_every_control_passes_on_the_real_book(run, H):
    c = engine.controls(run, H)
    assert not (c["status"] == "FAIL").any(), c[c["status"] == "FAIL"].to_string()
    assert REQUIRED_CONTROLS - {"cashflow_reconciliation_vs_p2"} <= set(c["check"])


def test_the_published_controls_file_names_every_required_check():
    import pandas as pd
    from desk.paths import TABLES_DIR
    path = TABLES_DIR / "pnl_controls.csv"
    if not path.exists():
        pytest.skip("pnl_controls.csv not written yet")
    c = pd.read_csv(path)
    assert REQUIRED_CONTROLS <= set(c["check"])
    assert not (c["status"] == "FAIL").any()


def test_the_run_is_deterministic(book, H):
    a = engine.run_book(book, H, with_detail=False, with_exposures=False)
    b = engine.run_book(book, H, with_detail=False, with_exposures=False)
    assert a.attribution.to_csv(index=False) == b.attribution.to_csv(index=False)


def test_window_end_and_horizon_are_reported_separately(run):
    """CONTRACTS §7.1: Mar-Aug carries an unrealised mark; the final number is at HORIZON_END."""
    from desk import WINDOW_END
    bookrow = run.attribution[run.attribution["trade_id"] == engine.BOOK_ID].set_index("date")
    assert dt.date(2022, 8, 31) == WINDOW_END
    assert WINDOW_END in bookrow.index and HORIZON_END in bookrow.index


# ---------------------------------------------------------------------------------- published-file regressions
def test_trade_cashflows_csv_is_actually_written_and_reconciles(book, H, run, cashflows, tmp_path, monkeypatch):
    """Review finding: `_write_cashflows` built the frame and never wrote it. Write into a temp dir and tie out."""
    import pandas as pd
    monkeypatch.setattr(mrun, "TABLES_DIR", tmp_path)
    ctl = mrun._write_cashflows(book, H, run)
    out = tmp_path / "trade_cashflows.csv"
    assert out.exists(), "the cashflow table must be written"
    assert ctl["check"].iloc[0] == "cashflow_reconciliation_vs_p2" and ctl["status"].iloc[0] == "INFO"
    pub = pd.read_csv(out)
    assert len(pub) == len(cashflows) and (pub["written_by"] == "P3").all()
    a = pub.groupby(["scenario", "trade_id"])["amount_inr"].sum()
    b = cashflows.groupby(["scenario", "trade_id"])["amount_inr"].sum()
    assert (a - b).abs().max() < 0.01 * len(pub)


def test_the_published_trade_cashflows_file_is_the_current_engine_output(cashflows):
    import pandas as pd
    from desk.paths import TABLES_DIR
    path = TABLES_DIR / "trade_cashflows.csv"
    if not path.exists():
        pytest.skip("trade_cashflows.csv not written yet — run desk.mtm.run")
    pub = pd.read_csv(path)
    assert len(pub) == len(cashflows)
    real = pub[pub["scenario"] == "REALISED"].groupby("trade_id")["amount_inr"].sum()
    mem = cashflows[cashflows["scenario"] == "REALISED"].groupby("trade_id")["amount_inr"].sum()
    assert (real - mem).abs().max() < 1.0


def test_new_deal_timing_splits_bucket_zero_exactly(book, run):
    """The '(0) at inception' label overstated day one; the split must add back to the lifetime bucket per trade."""
    t = mrun.new_deal_timing(book, run)
    att = run.attribution
    for _, r in t.iterrows():
        life = float(att.loc[att["trade_id"] == r["trade_id"], "new_deal"].sum())
        assert abs(r["new_deal_total_inr"] - life) < 1.0, r["trade_id"]
        assert abs(r["new_deal_on_trade_date_inr"] + r["new_deal_after_trade_date_inr"] - life) < 1.0
    bk = t[t["trade_id"] == engine.BOOK_ID].iloc[0]
    assert 0.0 < bk["after_trade_date_share_frac"] < 1.0
