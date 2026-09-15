"""Checks on the regulatory / exchange / scrap-grade / commercial parameter register (Phase 0 research).

Why these tests exist: the parity model (CONTRACTS §5) multiplies these numbers together, so a unit slip
(2.5 instead of 0.025), a grade factor outside any physical range, or a DIRECT flag with no verification behind it
would silently corrupt every downstream P&L. The last test recomputes the grade-factor paths from the cached official
trade statistics so the published path cannot drift from its documented derivation.
"""

from __future__ import annotations

import datetime as dt
import re

import pandas as pd
import pytest

from desk import config
from desk.paths import PROCESSED_DIR, RAW_DIR

OWNED_FILES = ("regulatory.yaml", "exchange.yaml", "scrap_grades.yaml", "commercial.yaml")
GRADES = ("zorba", "taint_tabor", "tense")

CANONICAL_KEYS = (
    # CONTRACTS §5 names owned by this register
    "bcd_scrap_hs7602",
    "sws_rate_on_bcd",
    "igst_rate_hs7602",
    "igst_itc_available",
    "bcd_primary_al_hs7601",
    "domestic_anchor_premium_inr_t",
    "conversion_cost_inr_t",
    "margin_threshold_inr_t",
    *(f"grade_factor_{g}" for g in GRADES),
    *(f"moisture_frac_{g}" for g in GRADES),
    *(f"contamination_frac_{g}" for g in GRADES),
    *(f"metal_yield_frac_{g}" for g in GRADES),
    # keys requested for the research register
    "aidc_scrap_hs7602",
    "landing_charges_frac",
    "customs_usdinr_import",
    "customs_fx_markup_frac",
    "igst_credit_lag_days",
    "grade_factor_mix",
    "grade_factor_mix_lag1",
    "grade_factor_mix_lag3",
    "grade_factor_mix_pit",
    *(f"grade_factor_diff_{g}" for g in GRADES),
    *(f"heavies_frac_{g}" for g in GRADES),
    "heavies_net_value_frac_of_lme_al",
    "conversion_cost_sensitivity_inr_t_ingot",
    "domestic_anchor_premium_sensitivity_inr_t",
    "domestic_anchor_passthrough_frac",
    "domestic_anchor_trailing_bdays",
    "domestic_anchor_premium_trailing_inr_t",
    "psic_cost_usd_per_box",
    "qco_stress_delay_days",
    "qco_stress_rejection_frac",
    "mcx_al_lot_mt",
    "mcx_al_tick_inr_kg",
    "mcx_al_initial_margin_frac",
    "mcx_al_elm_frac",
    "mcx_al_expiry_rule",
    "mcx_roll_days_before_expiry",
    "fx_forward_bank_margin_inr",
    "lme_pricing_reference",
    "lc_opening_fee_frac",
    "lc_confirmation_fee_pa",
    "usance_interest_spread_pa",
    "standard_moisture_franchise_frac",
    "rejection_penalty_schedule",
    "radioactivity_clause",
    "domestic_buyer_credit_days",
)


@pytest.fixture(scope="module")
def params():
    config.reload()
    return config.load_params()


def _owned(params):
    return {k: p for k, p in params.items() if p.file in OWNED_FILES}


def _numbers(p):
    vals = [v for _, v in p.path] if p.is_path else [p.value]
    return [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]


def test_register_loads_with_canonical_keys(params):
    missing = [k for k in CANONICAL_KEYS if k not in params]
    assert not missing, f"missing canonical keys: {missing}"
    for k in CANONICAL_KEYS:
        assert params[k].file in OWNED_FILES, f"{k} should live in one of {OWNED_FILES}, found in {params[k].file}"


def test_flags_valid_and_fields_non_empty(params):
    for k, p in _owned(params).items():
        assert p.flag in config.VALID_FLAGS, k
        for field in ("unit", "source", "verify", "note"):
            assert str(getattr(p, field)).strip(), f"{k}.{field} is empty"


def test_direct_params_were_actually_checked(params):
    """Honesty rule: DIRECT means a named source was read, so the verify field must say VERIFIED or PARTIAL."""
    for k, p in _owned(params).items():
        if p.flag == "DIRECT":
            assert p.verify.startswith(("VERIFIED", "PARTIAL")), f"{k} is DIRECT but verify={p.verify[:40]!r}"


def test_fractions_in_unit_interval(params):
    for k, p in _owned(params).items():
        if p.unit.startswith("frac") or k.endswith("_frac"):
            for v in _numbers(p):
                assert 0.0 <= v <= 1.0, f"{k}={v} outside [0, 1]"


def test_grade_factors_within_physical_range(params):
    for g in GRADES:
        p = params[f"grade_factor_{g}"]
        assert p.is_path and p.interp == "linear"
        vals = _numbers(p)
        assert vals and all(0.6 <= v <= 0.98 for v in vals), (g, vals)
        for d in pd.date_range("2022-03-01", "2022-09-30", freq="7D"):
            assert 0.6 <= p.at(d) <= 0.98


def test_yields_and_recovery(params):
    rec = {}
    for g in GRADES:
        y = params[f"metal_yield_frac_{g}"].value
        assert 0.7 <= y <= 0.99, (g, y)
        rec[g] = (1 - params[f"moisture_frac_{g}"].value) * (1 - params[f"contamination_frac_{g}"].value) * y
        assert 0.7 <= rec[g] <= 0.95, (g, rec[g])
    # thick castings lose least in the melt, thin painted sheet more, Zorba 95/5 also loses its ~5% heavies
    assert rec["tense"] >= rec["taint_tabor"] > rec["zorba"]
    assert params["metal_yield_frac_tense"].value > params["metal_yield_frac_taint_tabor"].value


def test_zorba_definition_is_consistent_between_price_and_recovery(params):
    """Review finding: price evidence is Zorba 95/5, so recovery must exclude ~5% heavies and credit them."""
    assert params["heavies_frac_zorba"].value == pytest.approx(0.05)
    assert params["contamination_frac_zorba"].value >= params["heavies_frac_zorba"].value
    assert params["heavies_frac_tense"].value == params["heavies_frac_taint_tabor"].value == 0.0
    assert "95/5" in params["grade_factor_zorba"].source


def test_grade_factors_are_mix_plus_differential_and_flagged_by_weakest_component(params):
    for g in GRADES:
        p = params[f"grade_factor_{g}"]
        assert p.flag == "ASSUMPTION" and p.unit == "frac_of_lme_3m_cfr_india"
        for d, v in p.path:
            want = params["grade_factor_mix"].at(d) + params[f"grade_factor_diff_{g}"].value
            assert v == pytest.approx(want, abs=1e-9), (g, d)
    assert params["grade_factor_mix"].flag == "PROXY"


def test_conversion_cost_is_per_tonne_of_ingot(params):
    assert params["conversion_cost_inr_t"].unit == "inr_per_mt_ingot"
    assert params["conversion_cost_inr_t"].value in params["conversion_cost_sensitivity_inr_t_ingot"].value


def test_working_capital_rate_is_mclr_path_plus_spread(params):
    wc, mclr, spread = params["wc_rate_inr_pa"], params["sbi_mclr_1y_pa"], params["wc_rate_spread_over_mclr_pa"].value
    assert wc.is_path and mclr.flag == "DIRECT" and wc.flag == "ASSUMPTION"
    assert [d for d, _ in wc.path] == [d for d, _ in mclr.path]
    for d, v in wc.path:
        assert v == pytest.approx(mclr.at(d) + spread, abs=1e-9)
    assert wc.at(dt.date(2022, 8, 31)) > wc.at(dt.date(2022, 3, 1))  # rises with the 2022 tightening


def test_customs_note_records_the_175_notifications(params):
    note = params["customs_usdinr_import"].note
    assert "13 of the 15" in note and "64/2022" in note and "73/2022" in note


def test_secondary_cost_share_midpoint_is_not_direct(params):
    assert params["secondary_raw_material_cost_share"].flag == "PROXY"


def test_every_contract_section5_key_exists(params):
    keys = [
        "grade_factor_zorba", "insurance_rate", "insured_value_uplift", "customs_usdinr_import", "bcd_scrap_hs7602",
        "sws_rate_on_bcd", "igst_rate_hs7602", "igst_itc_available", "igst_credit_lag_days", "port_cf_charges_inr_t_nsa",
        "port_cf_charges_inr_t_mun", "psic_cost_usd_per_box", "finance_days_jea_nsa", "finance_days_usec_mun",
        "wc_rate_inr_pa", "domestic_anchor_premium_inr_t", "heavies_net_value_frac_of_lme_al", "conversion_cost_inr_t",
        "margin_threshold_inr_t", "container_payload_mt_20ft", "container_payload_mt_40ft",
        *(f"container_payload_mt_{b}_{g}" for b in ("20ft", "40ft") for g in GRADES),
    ]
    missing = [k for k in keys if k not in params]
    assert not missing, missing
    contract = (RAW_DIR.parent.parent / "CONTRACTS.md").read_text()
    assert "customs_usdinr_import" in contract and "× customs_usdinr\n" not in contract


def test_duty_magnitudes_are_fractions_not_percent(params):
    assert params["bcd_scrap_hs7602"].value == pytest.approx(0.025)
    assert params["sws_rate_on_bcd"].value == pytest.approx(0.10)
    assert params["igst_rate_hs7602"].value == pytest.approx(0.18)
    assert params["bcd_primary_al_hs7601"].value > params["bcd_scrap_hs7602"].value
    assert params["landing_charges_frac"].value == 0.0


def test_customs_exchange_rate_path(params):
    p = params["customs_usdinr_import"]
    assert p.is_path and p.interp == "step"
    dates = [d for d, _ in p.path]
    assert dates == sorted(dates) and dates[0] <= dt.date(2022, 3, 1) and dates[-1] >= dt.date(2022, 9, 1)
    assert all(70.0 < v < 85.0 for v in _numbers(p))
    assert p.at(dt.date(2022, 3, 3)) == pytest.approx(76.05)  # 13/2022 only effective from 04-Mar
    assert p.at(dt.date(2022, 3, 4)) == pytest.approx(76.65)
    assert p.at(dt.date(2022, 7, 25)) == pytest.approx(80.95)


def test_mcx_expiry_dates_are_month_end_business_days(params):
    dates = [pd.Timestamp(d) for d in params["mcx_al_expiry_dates_2022"].value]
    for d in dates:
        assert d.weekday() < 5, d
        month_end = d + pd.offsets.MonthEnd(0)
        assert 0 <= (month_end - d).days <= 3, d
    assert params["mcx_al_lot_mt"].value == 5.0 and params["mcx_al_tick_inr_kg"].value == pytest.approx(0.05)


# ---------------------------------------------------------------------------------------------------------------
# Reproducibility of the grade-factor and anchor parameters from cached public evidence
# ---------------------------------------------------------------------------------------------------------------
def test_register_matches_cached_price_evidence(monkeypatch):
    from desk.data import fetch_price_evidence as pe

    if not (pe.TRADESTAT_DIR.exists() and pe.ALCIRCLE_DIR.exists() and (PROCESSED_DIR / "lme_daily.csv").exists()):
        pytest.skip("cached TRADESTAT / AlCircle pages or lme_daily.csv not available")
    monkeypatch.setenv("DESK_OFFLINE", "1")
    tables = pe.build()
    assert pe.check_register(tables) == []
    d = tables["diffs"]
    assert d.loc["zorba", "n_quotes"] >= 10 and d.loc["tense", "n_quotes"] >= 20
    q = tables["quotes"]
    assert (q["lme_ref_date"] < q["article_date"]).all()  # D-1 convention: no same-day LME look-ahead


def test_price_evidence_rejects_a_quote_not_in_its_article(monkeypatch):
    from desk.data import fetch_price_evidence as pe

    if not pe.ALCIRCLE_DIR.exists():
        pytest.skip("cached AlCircle pages not available")
    monkeypatch.setenv("DESK_OFFLINE", "1")
    texts = {"ac_2024-02-24": pe.article_text("ac_2024-02-24")}
    bad = pe.Quote("ac_2024-02-24", "tense", "UAE", "ASSESSMENT", 1000, 0.0, "NONE", "CFR", "settling at $1,000 per ton")
    monkeypatch.setattr(pe, "QUOTES", [bad])
    lme = pd.Series([2200.0], index=pd.to_datetime(["2024-02-23"]))
    mix = pd.DataFrame({"mix_ratio_lag2": [0.9]}, index=pd.PeriodIndex(["2024-02"], freq="M"))
    monkeypatch.setattr(pe, "ARTICLES", {"ac_2024-02-24": pe.ARTICLES["ac_2024-02-24"]})
    monkeypatch.setattr(pe, "LABEL_SNIPPETS", [])
    with pytest.raises(ValueError, match="snippet not found"):
        pe.quotes_table(lme, mix, 2, texts)
