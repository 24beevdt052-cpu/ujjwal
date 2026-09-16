"""Named model-structure constants for the Phase 3 engine, plus the bridge to the parameter register.

Two kinds of number live here and nowhere else in `desk.mtm`:

1. **Model-structure constants** (CONTRACTS §1.6 allows these in code): tolerances, bump sizes, the crash-window
   convention, the curve-extrapolation rule. They describe *the model*, not the market.
2. **A temporary fallback for the fifteen `config/params/book.yaml` keys** that
   `docs/design/30_position_model.md` §14 specifies but that Phase 2 owns and had not yet written when this engine
   was built. `param(key, date)` reads the register first and falls back to the §14 table only when the key is
   absent, recording every fallback it used in `FALLBACKS_USED`. `desk.mtm.run` writes that list into
   `outputs/tables/pnl_controls.csv` so a reader can never mistake a code default for a registered assumption.
   The moment `book.yaml` lands, the register wins and the fallback disappears with no code change.

Nothing here is a market observation. Every fallback value, its unit, flag and justification is copied verbatim from
design §14 so the two cannot drift.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from desk import config

# ------------------------------------------------------------------------------------------- control tolerances
RESIDUAL_TOL_INR = 1.0                     # CONTRACTS §7.2: |residual| per trade-day
LEDGER_TOL_INR = 0.01                      # cum P&L identity, BS lifetime sum, cross-phase cashflow reconciliation
MCX_PROXY_REPLICATION_TOL_INR_KG = 1e-3    # panel M1/M2 vs the theoretical parity price on PROXY days (4-dp CSV)
# The panel rounds usdinr_fwd_1m to 4 dp, so the replacement mark cannot reconcile to Phase 1 to the paisa on the
# CIP forward alone. The base control carries that rounding; the `_panelfx` variant substitutes the panel column
# and must then hold to LEDGER_TOL_INR.
REPLACEMENT_VS_P1_TOL_INR_T = 0.50

# ------------------------------------------------------------------------------------------------ model shape
LME_CURVE_EXTRAPOLATION = "flat_beyond_3m"
LME_CURVE_TENOR_MONTHS = 3
MPLUS1_MONTH_OFFSET = 1                    # design D3: the calendar month AFTER the B/L month
CRASH_FORTNIGHT_RETURN_DAYS = 10           # design §8: 10 *returns* (11 observations), pinned in CONTRACTS §7a.3
MCX_LOT_LME_EQ_NOTE = "one MCX lot ~= lot_mt x duty uplift x carry ~= 5.44 MT of LME-equivalent metal"

# A hedge ratio is hedge / physical. When the physical leg is passing through zero the quotient is arbitrarily
# large and says nothing about the hedge, so below these denominators the ratio is reported as NaN (blank in the
# CSV) rather than as a number a reader would take seriously. The thresholds are the smallest position the desk
# could actually trade: one MCX lot (`mcx_al_lot_mt` = 5 MT) of metal, against parcels of 1,200-2,520 MT, and
# USD 100k of currency, against forward notionals of USD 3-12 m. Below one lot there is nothing to hedge.
HEDGE_RATIO_MIN_PHYSICAL_MT = 5.0
HEDGE_RATIO_MIN_PHYSICAL_USD = 1.0e5

# ------------------------------------------------------------------------------------------------- bump sizes (§7)
BUMP_LME_CASH_USD_T = 1.0
BUMP_USDINR = 0.01
BUMP_FREIGHT_USD_T = 1.0
BUMP_GRADE_FACTOR = 0.001
BUMP_SPREAD_USD_T = 1.0
BUMP_MCX_BASIS_INR_KG = 1.0
BUMP_RATE_PA = 0.0001

# ------------------------------------------------------------------------------------------------ output format
# CONTRACTS §2 determinism: fixed float formats so a re-run is byte-identical.
ROUND_INR = 2
ROUND_USD = 2
ROUND_PRICE = 4                            # ₹/kg, USD/t, FX rates
ROUND_FRAC = 6                             # rates and fractions


@dataclass(frozen=True)
class BookParam:
    """One design §14 key, with everything the assumptions log would have carried."""

    value: Any
    unit: str
    flag: str
    justification: str
    verify: str = "N/A"


# design/30_position_model.md §14 — verbatim. P2 owns `config/params/book.yaml`; this is the fallback until it lands.
BOOK_PARAM_FALLBACKS: dict[str, BookParam] = {
    "lc_sight_payment_lag_days": BookParam(
        7, "days_after_bl", "ASSUMPTION",
        "the document-presentation and payment timeline in the finance_days_jea_nsa note (supplier paid ~day 7)"),
    "lc_presentation_period_days": BookParam(
        21, "days_after_shipment", "ASSUMPTION",
        "UCP 600 Art. 14(c) default presentation period; sets LC validity for the opening fee",
        "PENDING — read the ICC UCP 600 text"),
    "lc_amount_tolerance_frac": BookParam(
        0.10, "frac", "ASSUMPTION", "the 'about' tolerance used to size the LC value",
        "PENDING — UCP 600 Art. 30"),
    "survey_lag_days": BookParam(
        1, "days_after_arrival", "ASSUMPTION",
        "joint survey at the CFS before the BoE is filed (design §11 simplification 5)"),
    "boe_lag_days": BookParam(
        1, "days_after_arrival", "ASSUMPTION",
        "the igst_credit_lag_days note puts the Bill of Entry ~1 day after arrival"),
    "provisional_invoice_frac": BookParam(
        0.95, "frac", "ASSUMPTION",
        "90-100% provisional payment is common on LME-linked scrap SPAs; P5 shows 0.90-1.00 as a sensitivity"),
    "final_invoice_lag_bdays": BookParam(
        5, "panel_days_after_pricing_end", "ASSUMPTION",
        "the seller computes the M+1 average and invoices by T/T"),
    "claim_settle_lag_days": BookParam(
        30, "days_after_survey", "ASSUMPTION", "survey report, seller acceptance, credit note"),
    "advance_days_before_delivery": BookParam(
        2, "days", "ASSUMPTION", "advance received before truck release"),
    "freight_booking_days_before_bl": BookParam(
        10, "days", "ASSUMPTION",
        "NVOCC space-confirmation lead time; sets the default latest_fixture_date"),
    "freight_stop_loss_frac": BookParam(
        0.15, "frac", "ASSUMPTION", "the desk's freight-risk policy; the P5 memo may override it"),
    "mcx_slippage_ticks": BookParam(
        2, "ticks", "ASSUMPTION", "execution against the settle on a thin contract"),
    "mcx_txn_cost_frac": BookParam(
        0.0003, "frac_of_contract_value", "ASSUMPTION",
        "one combined charge for brokerage, exchange transaction charges, GST on them and the Commodity Transaction "
        "Tax on the sell side; deliberately un-decomposed rather than state a remembered rate (CONTRACTS §1.2)",
        "PENDING — MCX transaction-charge circular and Finance Act 2013 Ch. VII"),
    "buyer_margin_inr_t": BookParam(
        6450, "inr_per_mt_scrap", "ASSUMPTION",
        "the smelter's retained share of the netback; used only by the sale-terms helper"),
    "overdue_interest_collected_frac": BookParam(
        0.0, "frac", "ASSUMPTION",
        "penal interest on late foundry payments is rarely collected, so the delay is a pure funding cost"),
}

FALLBACKS_USED: dict[str, BookParam] = {}


def param(key: str, date: dt.date | None = None) -> Any:
    """Register value for `key` at `date`; the design §14 fallback only when the register has no such key.

    Every fallback hit is recorded in `FALLBACKS_USED` and republished in `pnl_controls.csv`, so an un-registered
    assumption can never pass silently as a registered one.
    """
    try:
        return config.value(key, date)
    except KeyError:
        if key not in BOOK_PARAM_FALLBACKS:
            raise
        fb = BOOK_PARAM_FALLBACKS[key]
        FALLBACKS_USED[key] = fb
        return fb.value


def fallback_report() -> list[dict[str, Any]]:
    """Rows describing every design §14 key served from code rather than from the register."""
    return [
        {"key": k, "value": fb.value, "unit": fb.unit, "flag": fb.flag,
         "source": "docs/design/30_position_model.md §14 (config/params/book.yaml not present)",
         "verify": fb.verify, "note": fb.justification}
        for k, fb in sorted(FALLBACKS_USED.items())
    ]
