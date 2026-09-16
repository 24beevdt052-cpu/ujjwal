"""Everything the workbook reads, loaded once (CONTRACTS §1.7: stages talk through files).

The workbook is a *rendering* stage: it reads the published Phase 0–3 files and the parameter register, and writes
one .xlsx. It recomputes nothing in Python that a sheet then presents as its own result — the only Python numbers it
carries are the green "pasted output" columns the Checks sheet compares formulas against, plus the two pricing
primitives (`desk.mtm.curves.mcx_price`, `curves.fx_x`) used by the Attribution worked examples, which are called
directly so the Excel formulas are checked against the *engine*, not against a literal copied out of a document.

The MTM marking grid. `mtm_daily.csv` is 28,343 date × trade × leg rows; a formula-per-leg reproduction of all of
them would make the file unusable and could not be recalculated in a test. The workbook therefore values every open
leg on a **declared marking grid** — month-end panel days, every trade date, the adverse-event endpoints from
`adverse_event_windows.csv`, `WINDOW_END` and `HORIZON_END` — and reconciles per-trade cumulative P&L to Python on
that grid. The grid is a *rule*, fixed here, not a selection made after seeing results.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import pandas as pd
import yaml

from desk import HORIZON_END, PANEL_END, WINDOW_END, config
from desk.parity import model as parity_model
from desk.paths import CONFIG_DIR, PROCESSED_DIR, TABLES_DIR

PANEL_FIRST = dt.date(2022, 1, 3)   # first panel day of the first parity week (week ending 2022-01-07)
PANEL_LAST = PANEL_END  # the M+1 hindsight average on the last parity week needs November prints

# Register keys the workbook exposes on the Inputs sheet as named ranges (scalars only).
NAMED_SCALARS = (
    "bcd_scrap_hs7602", "sws_rate_on_bcd", "igst_rate_hs7602", "insurance_rate", "insured_value_uplift",
    "igst_credit_lag_days", "igst_itc_available", "psic_cost_usd_per_box", "heavies_net_value_frac_of_lme_al",
    "domestic_anchor_premium_inr_t", "conversion_cost_inr_t", "margin_threshold_inr_t", "bcd_primary_al_hs7601",
    "mcx_domestic_premium_inr_kg", "customs_fx_markup_frac", "customs_fx_notification_validity_days",
    "mcx_al_lot_mt", "mcx_al_margin_used_frac", "fx_forward_bank_margin_inr", "mcx_roll_days_before_expiry",
    "lme_cash_prompt_bdays", "mcx_al_tick_inr_kg", "demurrage_usd_per_box_day",
)
# Extra scalar keys shown on Inputs (looked up by key, not by name) because a formula builds the key from a row.
KEYED_SCALARS = (
    "container_payload_mt_20ft", "container_payload_mt_40ft",
    "container_payload_mt_20ft_zorba", "container_payload_mt_20ft_taint_tabor", "container_payload_mt_20ft_tense",
    "container_payload_mt_40ft_zorba", "container_payload_mt_40ft_taint_tabor", "container_payload_mt_40ft_tense",
    "port_cf_charges_inr_t_nsa", "port_cf_charges_inr_t_mun",
    "psic_required_uae_origin", "psic_required_safe_origin_designated_port",
    "finance_days_jea_nsa", "finance_days_usec_mun",
    "moisture_frac_zorba", "moisture_frac_taint_tabor", "moisture_frac_tense",
    "contamination_frac_zorba", "contamination_frac_taint_tabor", "contamination_frac_tense",
    "metal_yield_frac_zorba", "metal_yield_frac_taint_tabor", "metal_yield_frac_tense",
    "heavies_frac_zorba", "heavies_frac_taint_tabor", "heavies_frac_tense",
    "grade_factor_diff_zorba", "grade_factor_diff_taint_tabor", "grade_factor_diff_tense",
)
# Dated paths resolved on each market date by formula (see desk.excel.sheet_market).
PATH_KEYS = ("grade_factor_zorba", "grade_factor_taint_tabor", "grade_factor_tense", "grade_factor_mix_pit",
             "wc_rate_inr_pa", "customs_usdinr_import")
# List-valued register entries shown on Inputs for reference (the §5a conversion grid).
LIST_KEYS = ("conversion_cost_sensitivity_inr_t_ingot", "domestic_anchor_premium_sensitivity_inr_t")
# Text / switch keys shown for completeness (they select a basis rather than carry a number).
TEXT_KEYS = ("parity_goods_fx_basis", "mplus1_bl_month_offset_months")

GRADES = parity_model.GRADES
LANES = parity_model.LANES
LANE_BOX = {"JEA_NSA": "20ft", "USEC_MUN": "40ft"}
LANE_PORT = {"JEA_NSA": "nsa", "USEC_MUN": "mun"}
LANE_FREIGHT = {"JEA_NSA": "freight_jea_nsa_usd_t", "USEC_MUN": "freight_usec_mun_usd_t"}
LANE_MCX = {"JEA_NSA": "mcx_al_m1_inr_kg", "USEC_MUN": "mcx_al_m2_inr_kg"}

SECTION_5A_CONVERSION_INR_T_INGOT = parity_model.SECTION_5A_CONVERSION_INR_T_INGOT

# Phase 3 book parameters the engine still serves from code: `config/params/book.yaml` does not exist, so
# `desk.mtm.constants.BOOK_PARAM_FALLBACKS` supplies them (docs/design/30_position_model.md §14, and the Phase 3
# integration report's open issue 1). The workbook shows them in their own block, flagged, so a code default can
# never be mistaken for a registered assumption.
BOOK_FALLBACK_KEYS = ("mcx_slippage_ticks", "mcx_txn_cost_frac", "lc_sight_payment_lag_days",
                      "lc_presentation_period_days", "boe_lag_days", "survey_lag_days",
                      "provisional_invoice_frac", "final_invoice_lag_bdays", "claim_settle_lag_days",
                      "freight_stop_loss_frac", "overdue_interest_collected_frac")


def book_fallback_rows() -> list[dict[str, Any]]:
    from desk.mtm.constants import BOOK_PARAM_FALLBACKS

    return [{"key": k, "value": BOOK_PARAM_FALLBACKS[k].value, "unit": BOOK_PARAM_FALLBACKS[k].unit,
             "flag": BOOK_PARAM_FALLBACKS[k].flag, "verify": BOOK_PARAM_FALLBACKS[k].verify,
             "note": BOOK_PARAM_FALLBACKS[k].justification,
             "source": "docs/design/30_position_model.md §14 (config/params/book.yaml not present)"}
            for k in BOOK_FALLBACK_KEYS]


def _t(path: str, **kw) -> pd.DataFrame:
    return pd.read_csv(TABLES_DIR / path, **kw)


@dataclass(frozen=True)
class Data:
    panel: pd.DataFrame
    weekly: pd.DataFrame
    parity: pd.DataFrame
    parity_inputs: pd.DataFrame
    refs: pd.DataFrame
    grid_lme_fx: pd.DataFrame
    grid_freight_duty: pd.DataFrame
    term_weekly: pd.DataFrame
    term_rolls: pd.DataFrame
    counterparties: dict[str, Any]
    trade_book: pd.DataFrame
    hedges: pd.DataFrame
    cashflows: pd.DataFrame
    mtm: pd.DataFrame
    attribution: pd.DataFrame
    controls: pd.DataFrame
    mark_dates: tuple[dt.date, ...]
    events: pd.DataFrame

    @property
    def panel_days(self) -> list[dt.date]:
        return [d.date() for d in self.panel["date"]]


def _mark_dates(panel: pd.DataFrame, trade_book: pd.DataFrame, events: pd.DataFrame,
                mtm: pd.DataFrame) -> tuple[dt.date, ...]:
    """The declared marking grid (see the module docstring). Deterministic, and a rule rather than a selection."""
    days = pd.Series(sorted(mtm["date"].unique()))
    month_ends = days.groupby([days.dt.year, days.dt.month]).max().tolist()
    wanted = set(month_ends)
    wanted |= set(pd.to_datetime(trade_book["trade_date"]))
    for col in ("start", "end"):
        for v in pd.to_datetime(events[col], errors="coerce").dropna():
            wanted.add(v)
    wanted |= {pd.Timestamp(WINDOW_END), pd.Timestamp(HORIZON_END)}
    have = set(days)
    return tuple(sorted(d.date() for d in wanted if d in have))


@lru_cache(maxsize=1)
def load() -> Data:
    panel = pd.read_csv(PROCESSED_DIR / "market_daily.csv", parse_dates=["date", "mcx_m1_expiry", "mcx_m2_expiry"])
    panel = panel[(panel["date"].dt.date >= PANEL_FIRST) & (panel["date"].dt.date <= PANEL_LAST)]
    panel = panel.reset_index(drop=True)

    weekly = parity_model.weekly_market()
    parity_inputs = parity_model.build_inputs(weekly)
    parity = _t("parity_weekly.csv", parse_dates=["week_end", "value_date"])
    refs = _t("parity_reference_cases.csv", parse_dates=["week_end"])
    grid_lme_fx = _t("parity_sensitivity_lme_fx.csv", parse_dates=["week_end"])
    grid_freight_duty = _t("parity_sensitivity_freight_duty.csv", parse_dates=["week_end"])
    term_weekly = _t("term_structure_weekly.csv", parse_dates=["week_end", "value_date", "cash_prompt_date",
                                                               "three_m_prompt_date"])
    term_rolls = _t("term_structure_roll_monthly.csv", parse_dates=["m1_expiry", "m2_expiry", "roll_date"])
    counterparties = yaml.safe_load((CONFIG_DIR / "counterparties.yaml").read_text())
    trade_book = _t("trade_book.csv", parse_dates=["trade_date", "parity_week_end"])
    hedges = _t("trade_hedges.csv", parse_dates=["decision_date", "entry_date", "exit_date", "booking_date",
                                                 "value_date", "cancel_date"])
    cashflows = _t("trade_cashflows.csv", parse_dates=["contract_date", "fixing_date", "due_date_contractual",
                                                       "settle_date"])
    cashflows = cashflows[cashflows["scenario"] == "REALISED"].reset_index(drop=True)
    mtm = _t("mtm_daily.csv", parse_dates=["date", "settle_date"])
    attribution = _t("attribution_daily.csv", parse_dates=["date"])
    controls = _t("pnl_controls.csv")
    events = _t("adverse_event_windows.csv")
    marks = _mark_dates(panel, trade_book, events, mtm)
    return Data(panel=panel, weekly=weekly, parity=parity, parity_inputs=parity_inputs, refs=refs,
                grid_lme_fx=grid_lme_fx, grid_freight_duty=grid_freight_duty, term_weekly=term_weekly,
                term_rolls=term_rolls, counterparties=counterparties, trade_book=trade_book, hedges=hedges,
                cashflows=cashflows, mtm=mtm, attribution=attribution, controls=controls, mark_dates=marks,
                events=events)


# ------------------------------------------------------------------------------------------------ register views
def param_rows() -> list[dict[str, Any]]:
    """Register rows for the Inputs sheet: scalars (with a named range where one is defined), then list/text keys."""
    P = config.load_params()
    rows = []
    for key in list(NAMED_SCALARS) + list(KEYED_SCALARS) + list(LIST_KEYS) + list(TEXT_KEYS):
        p = P[key]
        rows.append({
            "key": key, "value": p.value, "unit": p.unit, "flag": p.flag, "source": p.source,
            "verify": p.verify, "note": p.note, "file": p.file,
            "named_range": key if key in NAMED_SCALARS else "",
        })
    return rows


def path_rows(key: str) -> list[dict[str, Any]]:
    p = config.get(key)
    return [{"date": d, "value": float(v)} for d, v in p.path]


def path_meta(key: str) -> dict[str, Any]:
    p = config.get(key)
    return {"key": key, "interp": p.interp, "unit": p.unit, "flag": p.flag, "source": p.source,
            "verify": p.verify, "note": p.note, "n_points": len(p.path)}
