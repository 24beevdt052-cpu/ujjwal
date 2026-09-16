"""Phase 3 pricing primitives: the calendar, the curves, the MCX parity identity and the Phase 1 reconciliation."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from desk import config, units
from desk.data import mcx as mcx_data
from desk.mtm import curves
from desk.mtm.calendar import mcx_direct_expiry, mcx_roll_deadline
from desk.mtm.constants import MCX_PROXY_REPLICATION_TOL_INR_KG, REPLACEMENT_VS_P1_TOL_INR_T, param
from desk.mtm.engine import replacement_vs_p1
from desk.mtm.history import MarketHistory


@pytest.fixture(scope="module")
def H() -> MarketHistory:
    return MarketHistory()


# ------------------------------------------------------------------------------------------------- calendar
def test_roll_following_is_never_backwards(H):
    cal = H.cal
    # 2022-06-02/03 are LME holidays (the Platinum Jubilee); a derived date there rolls FORWARD to 06-06.
    assert cal.roll(dt.date(2022, 6, 2)) == dt.date(2022, 6, 6)
    assert cal.roll(dt.date(2022, 6, 3)) == dt.date(2022, 6, 6)
    assert cal.roll(dt.date(2022, 8, 29)) == dt.date(2022, 8, 30)
    for d in (dt.date(2022, 5, 5), dt.date(2022, 6, 24)):
        assert cal.roll(d) == d


def test_mcx_contract_month_resolves_both_expiry_views(H):
    """Design D4b: the panel's 31-Aug slot and the DIRECT 30-Aug expiry are two views of contract month 2022-08."""
    assert H.cal.mcx_panel_expiry("2022-08") == dt.date(2022, 8, 31)
    assert mcx_direct_expiry("2022-08") == dt.date(2022, 8, 30)
    n = int(config.value("mcx_roll_days_before_expiry"))
    deadline = mcx_roll_deadline(H.cal, "2022-08")
    assert deadline == H.cal.shift(H.cal.roll_back(dt.date(2022, 8, 30)), -n)
    assert deadline < dt.date(2022, 8, 30)


def test_m1_month_switches_on_the_expiry_day(H):
    assert str(H.cal.m1_month_on(dt.date(2022, 3, 31))) == "2022-03"
    assert str(H.cal.m1_month_on(dt.date(2022, 4, 1))) == "2022-04"


# ---------------------------------------------------------------------------------------------------- curves
def test_cash_forward_interpolates_to_3m_then_flattens(H):
    d = dt.date(2022, 4, 11)
    M = H.state_at(d)
    three_m = M.lme_cash_usd_t - M.lme_spread_usd_t
    assert curves.cash_fwd(M, H.cal, d, d) == pytest.approx(M.lme_cash_usd_t)
    three_m_date = d + pd.DateOffset(months=3)
    assert curves.cash_fwd(M, H.cal, d, three_m_date.date()) == pytest.approx(three_m)
    far = d + dt.timedelta(days=400)
    assert curves.cash_fwd(M, H.cal, d, far) == pytest.approx(three_m)   # flat beyond 3M
    half = d + dt.timedelta(days=H.cal.tenor_days(d) // 2)
    mid = curves.cash_fwd(M, H.cal, d, half)
    assert min(M.lme_cash_usd_t, three_m) <= mid <= max(M.lme_cash_usd_t, three_m)


def test_month_average_fixed_fraction_grows_through_the_month(H):
    d1, d2 = dt.date(2022, 7, 1), dt.date(2022, 7, 29)
    _a1, f1 = curves.lme_month_avg(H.view(d1), H.state_at(d1), d1, "2022-07")
    _a2, f2 = curves.lme_month_avg(H.view(d2), H.state_at(d2), d2, "2022-07")
    assert 0 < f1 < f2 == pytest.approx(1.0)


def test_fx_forward_equals_the_panel_cip_column(H):
    """`fx_x` must reproduce the panel's own 3-month forward — the same `desk.units.fx_forward` on the same inputs."""
    for iso in ("2022-03-07", "2022-06-10", "2022-08-12"):
        d = dt.date.fromisoformat(iso)
        M = H.state_at(d)
        target = (pd.Timestamp(d) + pd.DateOffset(months=3)).date()
        theo = curves.fx_x(H.view(d), M, d, target)
        panel = float(H.row(d).usdinr_fwd_3m)
        assert theo == pytest.approx(panel, abs=1e-4)


def test_fx_settled_and_spot_cases(H):
    d = dt.date(2022, 6, 10)
    M = H.state_at(d)
    assert curves.fx_x(H.view(d), M, d, d) == pytest.approx(M.usdinr)
    past = dt.date(2022, 5, 5)
    assert curves.fx_x(H.view(d), M, d, past) == pytest.approx(H.usdinr(past))


def test_fx_forward_strike_carries_only_the_bank_margin(H):
    booking, value_date = dt.date(2022, 4, 11), dt.date(2022, 5, 12)
    margin = float(config.value("fx_forward_bank_margin_inr"))
    mid = curves.fx_x(H.view(booking), H.state_at(booking), booking, value_date)
    assert curves.fx_forward_strike(H, booking, value_date, +1) == pytest.approx(mid + margin)
    assert curves.fx_forward_strike(H, booking, value_date, -1) == pytest.approx(mid - margin)


# ------------------------------------------------------------------------------------------------------- MCX
def test_theoretical_mcx_replicates_the_panel_on_every_2022_day(H):
    """Design D4: on a PROXY day the panel price IS the parity formula, so the basis is zero by construction."""
    worst = 0.0
    for d in H.cal.between(dt.date(2022, 1, 3), dt.date(2022, 10, 31)):
        M = H.state_at(d)
        HV = H.view(d)
        for slot, col in (("m1", "mcx_al_m1_inr_kg"), ("m2", "mcx_al_m2_inr_kg")):
            month = H.cal.m1_month_on(d) + (0 if slot == "m1" else 1)
            worst = max(worst, abs(curves.mcx_price(HV, M, d, str(month)) - float(getattr(H.row(d), col))))
    assert worst < MCX_PROXY_REPLICATION_TOL_INR_KG
    # the builder scans the whole panel (2018 onwards), so its worst case is at least the 2022 one
    assert worst <= H.mcx_replication_max_inr_kg < MCX_PROXY_REPLICATION_TOL_INR_KG


def test_proxy_basis_is_identically_zero(H):
    for d in H.cal.between(dt.date(2022, 3, 1), dt.date(2022, 8, 31)):
        assert H.mcx_src(d) == mcx_data.SRC_PROXY
        assert all(v == 0.0 for v in H.state_at(d).mcx_basis_inr_kg.values())


def test_one_mcx_lot_is_about_5_44_lme_equivalent_tonnes(H):
    """The design's sizing constant, recomputed rather than asserted from memory."""
    d = dt.date(2022, 4, 11)
    M = H.state_at(d)
    lot_mt = float(config.value("mcx_al_lot_mt"))
    month = str(H.cal.m1_month_on(d))
    dte = (H.cal.mcx_panel_expiry(month) - d).days
    lme_eq = lot_mt * H.duty_uplift(d) * (1 + M.inr_rate_3m_pa * dte / units.DAY_COUNT_INR)
    assert 5.3 < lme_eq < 5.6


# --------------------------------------------------------------------------------------- replacement value (D5)
def test_replacement_value_reconciles_to_phase_1(H):
    """Design §5.3's cross-phase control, on the panel-FX basis Phase 1 itself uses."""
    worst_cip, worst_panel = replacement_vs_p1(H)
    assert worst_panel < 0.01, f"R vs Phase 1 on the panel 1m forward: {worst_panel} ₹/MT"
    assert worst_cip < REPLACEMENT_VS_P1_TOL_INR_T


def test_replacement_value_excludes_finance(H):
    """`R` must be the *replacement* cost, not the parity screen's landed cost: no finance, no IGST financing."""
    from desk.parity import model as parity_model

    parity = parity_model.compute(parity_model.build_inputs())
    row = parity[(parity["grade"] == "zorba") & (parity["lane"] == "USEC_MUN")].iloc[10]
    d = row["value_date"].date()
    r = curves.replacement_value(H.view(d), H.state_at(d), d, "zorba", "USEC_MUN", "40ft",
                                 goods_fx=H.usdinr_fwd_1m(d))
    assert r == pytest.approx(row["goods_inr_t"] + row["bcd_inr_t"] + row["sws_inr_t"] + row["port_inr_t"], abs=0.01)
    assert r < row["landed_inr_t"]                      # landed cost adds finance and IGST financing


def test_psic_applies_only_to_the_gulf_lane(H):
    d = dt.date(2022, 5, 16)
    assert curves.psic_applies(H.view(d), d, "JEA_NSA") is True
    assert curves.psic_applies(H.view(d), d, "USEC_MUN") is False


# --------------------------------------------------------------------------------------------- PIT guard (D10)
def test_history_view_raises_beyond_the_clock(H):
    from desk.mtm.history import LookaheadError

    view = H.view(dt.date(2022, 6, 10))
    assert view.cash(dt.date(2022, 6, 10)) > 0
    with pytest.raises(LookaheadError):
        view.cash(dt.date(2022, 6, 13))
    with pytest.raises(LookaheadError):
        view.state_at(dt.date(2022, 7, 1))


def test_book_param_fallback_matches_the_design_table():
    """Until Phase 2 writes `config/params/book.yaml`, the §14 values must be served verbatim and recorded."""
    from desk.mtm.constants import BOOK_PARAM_FALLBACKS, FALLBACKS_USED, fallback_report

    assert param("boe_lag_days") == 1
    assert param("mcx_txn_cost_frac") == 0.0003
    try:
        config.get("boe_lag_days")
    except KeyError:
        assert "boe_lag_days" in FALLBACKS_USED
        assert any(r["key"] == "boe_lag_days" for r in fallback_report())
    assert set(BOOK_PARAM_FALLBACKS) >= {"lc_sight_payment_lag_days", "survey_lag_days", "provisional_invoice_frac"}
