"""Trade-ticket and counterparty schema for the mock trading book (Phase 2) and the MTM engine (Phase 3).

Why this module exists. `docs/design/30_position_model.md` fixes one ticket grammar that three stages must agree on:
P2 writes the book, P3 revalues it every day, P4/P5 re-run it under shocks and counterfactuals. If any of them can
silently accept a field the others ignore, the P&L identity (CONTRACTS §7.3) stops being checkable. So the loader is
**closed**: a ticket may carry only the fields listed here, plus an explicit ``extra`` mapping wherever the author
wants to record something the engine must not read. Anything else is an error naming the offending path.

Two kinds of number never appear in a ticket:

* **Derived numbers** (fill prices, forward strikes, the freight index at fixture, box counts, quotational-period
  dates). They are recomputed point-in-time by the engine from the panel and written to `outputs/tables/*.csv`.
  Typing them in would let hindsight in through the back door, so the loader rejects them by name.
* **Parameters.** Everything with a register key (payloads, transit days, free days, the MSME cap, lot size) is read
  from `config/params/*.yaml` through `desk.config`. The few literals below are *model-structure* constants from
  MASTER_SPEC_V3 Table 4 (trade size band, lots per ticket, usance band), not market assumptions.

The split of duties: this module validates everything that can be checked from the ticket, the counterparty file and
the register alone. Checks that need the market panel or Phase 1 parity — that a decision date is an LME trading day,
that `eligible_on(trade_date, grade, lane)` is True (CONTRACTS §5a), that every derived cashflow lands on or before
`HORIZON_END`, that a resolved stop-loss fixture matches the freight index — belong to `desk.book.validate`. The
panel-day check is available here too when the caller passes `panel_days`.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from desk import HORIZON_END, WINDOW_END, WINDOW_START, config

# ------------------------------------------------------------------------------- model-structure constants (Table 4)
SCHEMA_VERSION = 1
MIN_TRADE_MT = 1_000.0                 # Table 4 row 2.1
MAX_TRADE_MT = 5_000.0                 # Table 4 row 2.1
MAX_LOTS_PER_TICKET = 3                # a container SPA ships on 1-3 sailings (design §2.2)
MIN_USANCE_DAYS = 60                   # Table 4 row 2.6
MAX_USANCE_DAYS = 90                   # Table 4 row 2.6
BOX_TONNAGE_TOL_MT = 0.5               # Σ(boxes × payload) must match quantity_mt to within half a tonne
MAX_LAYCAN_SPAN_DAYS = 31
HEDGE_RATIO_MAX = 2.0
HEDGE_RATIO_SANE = (0.5, 1.2)          # outside this band is a warning, not an error
SIM_SUFFIX = "(SIM)"
# The July-2022 port disruption is a real, dated public report; a ticket may not "know" it earlier (CONTRACTS §7.6).
VOID_CALL_EVIDENCE_DATE = dt.date(2022, 7, 27)
VOID_CALL_MARKERS = ("void call", "void-call", "blank sailing")

TRADE_ID_RE = re.compile(r"^T\d{2}$")
LOT_ID_RE = re.compile(r"^L\d$")
SALE_ID_RE = re.compile(r"^S\d$")
HEDGE_ID_RE = re.compile(r"^[A-Z0-9]+-MCX-\d+$")
FWD_ID_RE = re.compile(r"^[A-Z0-9]+-FX-\d+$")
CP_ID_RE = re.compile(r"^(SUP|BUY)_[A-Z0-9]+_\d{2}$")
CONTRACT_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


class SchemaError(ValueError):
    """The YAML does not parse into the ticket grammar (unknown field, wrong type, derived field typed in)."""


class ValidationError(ValueError):
    """The ticket parses but breaks a book rule. Carries every issue so one run reports them all."""

    def __init__(self, issues: Sequence["Issue"]):
        self.issues = list(issues)
        super().__init__("\n".join(i.format() for i in self.issues))


# --------------------------------------------------------------------------------------------------------- enums
class _Str(str, Enum):
    def __str__(self) -> str:  # so f-strings and CSV writes give the plain token
        return self.value


class Lane(_Str):
    JEA_NSA = "JEA_NSA"
    USEC_MUN = "USEC_MUN"


class Grade(_Str):
    ZORBA = "zorba"
    TAINT_TABOR = "taint_tabor"
    TENSE = "tense"


class Incoterm(_Str):
    FOB = "FOB"
    CFR = "CFR"


class Port(_Str):
    NHAVA_SHEVA = "NHAVA_SHEVA"
    MUNDRA = "MUNDRA"


class TicketStatus(_Str):
    EXECUTED = "EXECUTED"
    DRAFT = "DRAFT"


class PurchasePricingType(_Str):
    FIXED = "FIXED"
    LME_M1_AVG = "LME_M1_AVG"


class LmeReference(_Str):
    CASH = "CASH"                      # LME Official Cash Settlement (exchange.yaml lme_pricing_reference)


class SalePricingType(_Str):
    FIXED = "FIXED"
    MCX_AVG = "MCX_AVG"


class McxSeries(_Str):
    M1 = "M1"                          # the near-month contract on each averaging day


class PaymentInstrument(_Str):
    LC_SIGHT = "LC_SIGHT"
    LC_USANCE = "LC_USANCE"


class ChargesFor(_Str):
    APPLICANT = "APPLICANT"
    BENEFICIARY = "BENEFICIARY"


class SalePaymentTerms(_Str):
    CREDIT = "CREDIT"
    ADVANCE = "ADVANCE"
    ADVANCE_PLUS_CREDIT = "ADVANCE_PLUS_CREDIT"


class FreightPaymentTerms(_Str):
    PREPAID_AT_BL = "PREPAID_AT_BL"
    COLLECT_AT_ARRIVAL = "COLLECT_AT_ARRIVAL"


class FreightRiskLayer(_Str):
    UNHEDGED_STOP_LOSS = "UNHEDGED_STOP_LOSS"
    PROXY_SWAP_HYPOTHETICAL = "PROXY_SWAP_HYPOTHETICAL"


class HedgeDirection(_Str):
    SELL = "SELL"
    BUY = "BUY"


class HedgeExitReason(_Str):
    UNWIND = "UNWIND"                  # exposure gone (sale contracted / pricing finished)
    ROLL = "ROLL"                      # same exposure, next contract month
    TRANCHE = "TRANCHE"                # part of the line lifted as the underlying prices


class ExposureBasis(_Str):
    NET_LME_EQ_DELTA = "NET_LME_EQ_DELTA"


class FxDirection(_Str):
    BUY_USD = "BUY_USD"
    SELL_USD = "SELL_USD"


class MatchedLeg(_Str):
    PURCHASE_INVOICE = "PURCHASE_INVOICE"
    PURCHASE_PROVISIONAL = "PURCHASE_PROVISIONAL"
    PURCHASE_FINAL = "PURCHASE_FINAL"
    FREIGHT = "FREIGHT"
    USANCE_INTEREST = "USANCE_INTEREST"
    DEMURRAGE = "DEMURRAGE"


class RejectionReason(_Str):
    RADIOACTIVITY = "RADIOACTIVITY"
    WRONG_GRADE = "WRONG_GRADE"
    NON_METALLIC = "NON_METALLIC"


class Role(_Str):
    SUPPLIER = "SUPPLIER"
    BUYER = "BUYER"


class CounterpartyType(_Str):
    SCRAP_YARD = "SCRAP_YARD"
    PROCESSOR = "PROCESSOR"
    TRADER = "TRADER"
    SECONDARY_SMELTER = "SECONDARY_SMELTER"
    FOUNDRY = "FOUNDRY"


class Security(_Str):
    NONE = "NONE"
    PDC = "PDC"
    BANK_GUARANTEE = "BANK_GUARANTEE"


class Flag(_Str):
    DIRECT = "DIRECT"
    PROXY = "PROXY"
    ASSUMPTION = "ASSUMPTION"
    SIM = "SIM"


LANE_PORT: dict[Lane, Port] = {Lane.JEA_NSA: Port.NHAVA_SHEVA, Lane.USEC_MUN: Port.MUNDRA}
LANE_BOX: dict[Lane, str] = {Lane.JEA_NSA: "20ft", Lane.USEC_MUN: "40ft"}
SUPPLIER_TYPES = (CounterpartyType.SCRAP_YARD, CounterpartyType.PROCESSOR, CounterpartyType.TRADER)
BUYER_TYPES = (CounterpartyType.SECONDARY_SMELTER, CounterpartyType.FOUNDRY, CounterpartyType.TRADER)


# ------------------------------------------------------------------------------------------------------ parsing
def _where(*parts: object) -> str:
    return ".".join(str(p) for p in parts if p not in (None, ""))


def _fields(raw: Any, where: str, allowed: Sequence[str], derived: Sequence[str] = ()) -> dict[str, Any]:
    """Return a mapping restricted to `allowed` (+ `extra`), rejecting unknown and derived keys by name."""
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise SchemaError(f"{where}: expected a mapping, got {type(raw).__name__}")
    out = dict(raw)
    extra = out.pop("extra", None)
    if extra is not None and not isinstance(extra, Mapping):
        raise SchemaError(f"{where}.extra: expected a mapping of free-form notes, got {type(extra).__name__}")
    for key in list(out):
        if key in derived:
            raise SchemaError(
                f"{where}.{key}: derived field must not be typed in the ticket — the engine computes it "
                f"point-in-time and writes it to outputs/tables/ (design §2.1)"
            )
        if key not in allowed:
            raise SchemaError(
                f"{where}.{key}: unknown field. Allowed here: {', '.join(sorted(allowed))}, extra. "
                f"Put anything the engine must not read under '{where}.extra'."
            )
    out["extra"] = dict(extra) if extra else {}
    return out


def _req(d: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in d or d[key] is None:
        raise SchemaError(f"{_where(where, key)}: required field is missing")
    return d[key]


def _date(value: Any, where: str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise SchemaError(f"{where}: '{value}' is not an ISO date (YYYY-MM-DD)") from exc
    raise SchemaError(f"{where}: expected an ISO date (YYYY-MM-DD), got {type(value).__name__}")


def _opt_date(value: Any, where: str) -> dt.date | None:
    return None if value is None else _date(value, where)


def _float(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaError(f"{where}: expected a number, got {value!r}")
    return float(value)


def _opt_float(value: Any, where: str) -> float | None:
    return None if value is None else _float(value, where)


def _int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaError(f"{where}: expected a whole number, got {value!r}")
    return value


def _opt_int(value: Any, where: str) -> int | None:
    return None if value is None else _int(value, where)


def _bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise SchemaError(f"{where}: expected true/false, got {value!r}")
    return value


def _str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{where}: expected a non-empty string, got {value!r}")
    return value


def _enum(cls: type[_Str], value: Any, where: str) -> Any:
    try:
        return cls(value)
    except ValueError as exc:
        allowed = ", ".join(m.value for m in cls)
        raise SchemaError(f"{where}: '{value}' is not valid. Allowed: {allowed}") from exc


def _opt_enum(cls: type[_Str], value: Any, where: str) -> Any:
    return None if value is None else _enum(cls, value, where)


def _str_list(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SchemaError(f"{where}: expected a list of strings")
    return tuple(_str(v, f"{where}[{i}]") for i, v in enumerate(value))


def _seq(value: Any, where: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SchemaError(f"{where}: expected a list")
    return list(value)


# ------------------------------------------------------------------------------------------------- dataclasses
@dataclass(frozen=True)
class Lot:
    """One bill of lading: the container parcel that sails, prices and clears together."""

    lot_id: str
    boxes: int
    bl_date: dt.date
    vessel: str
    voyage: str
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SpaTerms:
    isri_grade_spec: str
    moisture_franchise_frac: float | None = None          # default standard_moisture_franchise_frac
    contamination_limit_frac: float | None = None         # default contamination_frac_<grade>
    discount_multiple: float | None = None                # default spa_contamination_discount_multiple
    rejection_excess_frac: float | None = None            # default spa_contamination_rejection_excess_frac
    radioactivity_clause_key: str = "radioactivity_clause"
    penalty_schedule_key: str = "rejection_penalty_schedule"
    quantity_tolerance_frac: float = 0.0                  # LC sizing only; B/L weight is not toleranced (design §9)
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PurchasePricing:
    type: PurchasePricingType
    price_usd_t: float | None = None                      # FIXED, on the incoterm basis
    lme_reference: LmeReference | None = None              # LME_M1_AVG
    factor_frac: float | None = None                       # LME_M1_AVG, CFR-basis grade factor
    premium_usd_t: float = 0.0
    provisional_frac: float | None = None                  # default provisional_invoice_frac (book.yaml)
    terms_basis_note: str = ""
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LcTerms:
    instrument: PaymentInstrument
    lc_open_date: dt.date
    issuing_bank: str
    usance_days: int | None = None
    confirmed: bool = False
    confirmation_charges_for: ChargesFor | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Purchase:
    supplier_id: str
    spa_ref: str
    incoterm: Incoterm
    named_place: str
    pricing: PurchasePricing
    payment: LcTerms
    spa: SpaTerms
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Shipment:
    laycan_start: dt.date
    laycan_end: dt.date
    load_port: str
    discharge_port: Port
    lots: tuple[Lot, ...]
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FreightStopLoss:
    stop_loss_usd_box: float
    latest_fixture_date: dt.date
    note: str = ""
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FreightSwap:
    """HYPOTHETICAL container-freight swap. No liquid India-lane instrument existed; never in the base book."""

    swap_id: str
    boxes: int
    strike_usd_box: float
    start_date: dt.date
    settle_date: dt.date
    hypothetical: bool = True
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Freight:
    booked_by: str
    forwarder: str
    payment_terms: FreightPaymentTerms
    risk_layer: FreightRiskLayer
    fixture_date: dt.date | None = None                   # None = book at market on the first B/L date
    rate_usd_box: float | None = None                     # the executed fixture; required when fixture_date is set
    stop_loss: FreightStopLoss | None = None
    swap: FreightSwap | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SalePricing:
    type: SalePricingType
    price_inr_t: float | None = None
    mcx_series: McxSeries | None = None
    window_start: dt.date | None = None
    window_end: dt.date | None = None
    factor_frac: float | None = None                      # recovery / scrap-discount basis on the MCX ₹/t
    premium_inr_t: float = 0.0
    terms_basis_note: str = ""
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SalePayment:
    terms: SalePaymentTerms
    credit_days: int | None = None
    advance_frac: float | None = None
    advance_date: dt.date | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Sale:
    sale_id: str
    buyer_id: str
    contract_date: dt.date
    lot_ids: tuple[str, ...]
    delivery_basis: str
    pricing: SalePricing
    payment: SalePayment
    quality_passthrough: bool = True
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class McxTranche:
    hedge_id: str
    contract_month: str                                   # "YYYY-MM"; the panel slot and the DIRECT expiry both key off it
    direction: HedgeDirection
    lots: int
    entry_date: dt.date
    exit_date: dt.date
    exit_reason: HedgeExitReason
    roll_to: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class McxHedge:
    hedge_ratio_target: float | None = None
    exposure_basis: ExposureBasis = ExposureBasis.NET_LME_EQ_DELTA
    basis_risk_note: str = ""
    unhedged_reason: str = ""
    tranches: tuple[McxTranche, ...] = ()
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FxForward:
    fwd_id: str
    booking_date: dt.date
    direction: FxDirection
    notional_usd: float
    value_date: dt.date
    matched_leg: MatchedLeg
    cancel_date: dt.date | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FxHedge:
    hedge_frac_target: float | None = None
    lines: tuple[FxForward, ...] = ()
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Hedges:
    mcx: McxHedge = field(default_factory=McxHedge)
    fx_forwards: FxHedge = field(default_factory=FxHedge)
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class QualityEvent:
    """Joint-survey outcome for one lot (SIM). Known on the survey date; before it the ticket assumes nominal quality."""

    lot_id: str
    moisture_actual_frac: float
    contamination_actual_frac: float
    rejected_boxes: int = 0
    rejection_reason: RejectionReason | None = None
    claim_recovery_frac: float = 1.0
    flag: Flag = Flag.SIM
    note: str = ""
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LogisticsEvent:
    event_id: str
    lot_id: str
    known_date: dt.date
    arrival_delay_days: int = 0
    extra_dwell_days: int = 0
    real_trigger_ref: str = ""
    flag: Flag = Flag.SIM
    note: str = ""
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BuyerPaymentDelayEvent:
    event_id: str
    sale_id: str
    known_date: dt.date
    delay_days: int
    reason: str = ""
    flag: Flag = Flag.SIM
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Events:
    quality: tuple[QualityEvent, ...] = ()
    logistics: tuple[LogisticsEvent, ...] = ()
    buyer_payment_delay: tuple[BuyerPaymentDelayEvent, ...] = ()
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Rationale:
    text: str
    parity_week_end: dt.date
    cited_columns: tuple[str, ...] = ()
    cited_refs: tuple[str, ...] = ()
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Ticket:
    trade_id: str
    status: TicketStatus
    trade_date: dt.date
    lane: Lane
    grade: Grade
    quantity_mt: float
    purchase: Purchase
    shipment: Shipment
    sales: tuple[Sale, ...]
    rationale: Rationale
    freight: Freight | None = None
    hedges: Hedges = field(default_factory=Hedges)
    events: Events = field(default_factory=Events)
    extra: dict = field(default_factory=dict)

    @property
    def box(self) -> str:
        return LANE_BOX[self.lane]

    @property
    def boxes(self) -> int:
        return sum(lot.boxes for lot in self.shipment.lots)

    @property
    def payload_mt_per_box(self) -> float:
        return float(config.value(f"container_payload_mt_{self.box}_{self.grade.value}"))

    def lot_weight_mt(self, lot: Lot) -> float:
        """B/L weight of one lot (design §3.1: nominal payload, no quantity tolerance on the B/L)."""
        return lot.boxes * self.payload_mt_per_box

    def lot(self, lot_id: str) -> Lot:
        for lot in self.shipment.lots:
            if lot.lot_id == lot_id:
                return lot
        raise KeyError(f"{self.trade_id}: no lot {lot_id!r}")


@dataclass(frozen=True)
class CounterpartyProfile:
    relationship_start: dt.date
    years_in_business: int
    annual_turnover_inr: float
    prior_invoices_n: int
    prior_dpd_mean_days: float = 0.0
    prior_dpd_max_days: int = 0
    prior_defaults_n: int = 0
    prior_disputed_claims_n: int = 0
    gst_returns_regular: bool = True
    internal_rating_sim: str = ""
    group_concentration_frac: float | None = None
    security: Security = Security.NONE
    security_amount_inr: float = 0.0
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Counterparty:
    cp_id: str
    name: str
    role: Role
    type: CounterpartyType
    country: str
    location: str
    profile: CounterpartyProfile
    lanes: tuple[Lane, ...] = ()
    grades: tuple[Grade, ...] = ()
    credit_limit_inr: float | None = None                 # BUYER: receivable + pre-settlement cap
    claims_exposure_limit_usd: float | None = None        # SUPPLIER: refunds/claims receivable cap
    default_payment_terms: SalePaymentTerms | None = None
    credit_days_default: int | None = None
    lc_confirmation_required: bool = False
    safe_origin_for_psic: bool = False
    msme_registered: bool = False
    flag: Flag = Flag.SIM
    note: str = ""
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Book:
    trades: tuple[Ticket, ...]
    counterparties: tuple[Counterparty, ...]
    schema_version: int = SCHEMA_VERSION
    trades_path: str = ""
    counterparties_path: str = ""

    def counterparty(self, cp_id: str) -> Counterparty:
        for cp in self.counterparties:
            if cp.cp_id == cp_id:
                return cp
        raise KeyError(f"unknown counterparty {cp_id!r}")

    def trade(self, trade_id: str) -> Ticket:
        for t in self.trades:
            if t.trade_id == trade_id:
                return t
        raise KeyError(f"unknown trade {trade_id!r}")


# ------------------------------------------------------------------------------------------------------- issues
@dataclass(frozen=True)
class Issue:
    severity: str                                          # ERROR | WARNING
    code: str                                              # V01..V20
    where: str
    message: str

    def format(self) -> str:
        return f"{self.severity} {self.code} {self.where}: {self.message}"


def _err(code: str, where: str, message: str) -> Issue:
    return Issue("ERROR", code, where, message)


def _warn(code: str, where: str, message: str) -> Issue:
    return Issue("WARNING", code, where, message)


# ------------------------------------------------------------------------------------------------------ readers
def _read_lot(raw: Any, where: str) -> Lot:
    d = _fields(raw, where, ("lot_id", "boxes", "bl_date", "vessel", "voyage"),
                derived=("bl_weight_mt", "arrival_date", "boe_date", "survey_date", "release_date"))
    return Lot(
        lot_id=_str(_req(d, "lot_id", where), _where(where, "lot_id")),
        boxes=_int(_req(d, "boxes", where), _where(where, "boxes")),
        bl_date=_date(_req(d, "bl_date", where), _where(where, "bl_date")),
        vessel=_str(_req(d, "vessel", where), _where(where, "vessel")),
        voyage=_str(d.get("voyage", ""), _where(where, "voyage")) if d.get("voyage") else "",
        extra=d["extra"],
    )


def _read_spa(raw: Any, where: str) -> SpaTerms:
    d = _fields(raw, where, ("isri_grade_spec", "moisture_franchise_frac", "contamination_limit_frac",
                             "discount_multiple", "rejection_excess_frac", "radioactivity_clause_key",
                             "penalty_schedule_key", "quantity_tolerance_frac"))
    return SpaTerms(
        isri_grade_spec=_str(_req(d, "isri_grade_spec", where), _where(where, "isri_grade_spec")),
        moisture_franchise_frac=_opt_float(d.get("moisture_franchise_frac"), _where(where, "moisture_franchise_frac")),
        contamination_limit_frac=_opt_float(d.get("contamination_limit_frac"),
                                            _where(where, "contamination_limit_frac")),
        discount_multiple=_opt_float(d.get("discount_multiple"), _where(where, "discount_multiple")),
        rejection_excess_frac=_opt_float(d.get("rejection_excess_frac"), _where(where, "rejection_excess_frac")),
        radioactivity_clause_key=str(d.get("radioactivity_clause_key", "radioactivity_clause")),
        penalty_schedule_key=str(d.get("penalty_schedule_key", "rejection_penalty_schedule")),
        quantity_tolerance_frac=_float(d.get("quantity_tolerance_frac", 0.0), _where(where, "quantity_tolerance_frac")),
        extra=d["extra"],
    )


def _read_purchase_pricing(raw: Any, where: str) -> PurchasePricing:
    d = _fields(raw, where, ("type", "price_usd_t", "lme_reference", "factor_frac", "premium_usd_t",
                             "provisional_frac", "terms_basis_note"),
                derived=("qp_month", "qp_start", "qp_end", "qp_days", "pricing_month", "pricing_start",
                         "pricing_end", "pricing_days", "provisional_price_usd_t", "final_price_usd_t"))
    return PurchasePricing(
        type=_enum(PurchasePricingType, _req(d, "type", where), _where(where, "type")),
        price_usd_t=_opt_float(d.get("price_usd_t"), _where(where, "price_usd_t")),
        lme_reference=_opt_enum(LmeReference, d.get("lme_reference"), _where(where, "lme_reference")),
        factor_frac=_opt_float(d.get("factor_frac"), _where(where, "factor_frac")),
        premium_usd_t=_float(d.get("premium_usd_t", 0.0), _where(where, "premium_usd_t")),
        provisional_frac=_opt_float(d.get("provisional_frac"), _where(where, "provisional_frac")),
        terms_basis_note=str(d.get("terms_basis_note", "")),
        extra=d["extra"],
    )


def _read_lc(raw: Any, where: str) -> LcTerms:
    d = _fields(raw, where, ("instrument", "usance_days", "lc_open_date", "issuing_bank", "confirmed",
                             "confirmation_charges_for"),
                derived=("lc_value_usd", "lc_pay_date", "acceptance_date", "usance_maturity", "validity_days"))
    return LcTerms(
        instrument=_enum(PaymentInstrument, _req(d, "instrument", where), _where(where, "instrument")),
        lc_open_date=_date(_req(d, "lc_open_date", where), _where(where, "lc_open_date")),
        issuing_bank=_str(_req(d, "issuing_bank", where), _where(where, "issuing_bank")),
        usance_days=_opt_int(d.get("usance_days"), _where(where, "usance_days")),
        confirmed=_bool(d.get("confirmed", False), _where(where, "confirmed")),
        confirmation_charges_for=_opt_enum(ChargesFor, d.get("confirmation_charges_for"),
                                           _where(where, "confirmation_charges_for")),
        extra=d["extra"],
    )


def _read_purchase(raw: Any, where: str) -> Purchase:
    d = _fields(raw, where, ("supplier_id", "spa_ref", "incoterm", "named_place", "pricing", "payment", "spa"),
                derived=("freight_booked_by", "freight_risk_bearer", "psic_required"))
    return Purchase(
        supplier_id=_str(_req(d, "supplier_id", where), _where(where, "supplier_id")),
        spa_ref=_str(_req(d, "spa_ref", where), _where(where, "spa_ref")),
        incoterm=_enum(Incoterm, _req(d, "incoterm", where), _where(where, "incoterm")),
        named_place=_str(_req(d, "named_place", where), _where(where, "named_place")),
        pricing=_read_purchase_pricing(_req(d, "pricing", where), _where(where, "pricing")),
        payment=_read_lc(_req(d, "payment", where), _where(where, "payment")),
        spa=_read_spa(_req(d, "spa", where), _where(where, "spa")),
        extra=d["extra"],
    )


def _read_shipment(raw: Any, where: str) -> Shipment:
    d = _fields(raw, where, ("laycan_start", "laycan_end", "load_port", "discharge_port", "lots"))
    lots_raw = _seq(_req(d, "lots", where), _where(where, "lots"))
    lots = tuple(_read_lot(r, f"{_where(where, 'lots')}[{i}]") for i, r in enumerate(lots_raw))
    return Shipment(
        laycan_start=_date(_req(d, "laycan_start", where), _where(where, "laycan_start")),
        laycan_end=_date(_req(d, "laycan_end", where), _where(where, "laycan_end")),
        load_port=_str(_req(d, "load_port", where), _where(where, "load_port")),
        discharge_port=_enum(Port, _req(d, "discharge_port", where), _where(where, "discharge_port")),
        lots=lots,
        extra=d["extra"],
    )


def _read_freight(raw: Any, where: str) -> Freight:
    d = _fields(raw, where, ("booked_by", "forwarder", "payment_terms", "risk_layer", "fixture_date",
                             "rate_usd_box", "stop_loss", "swap"),
                derived=("index_usd_box_at_fixture", "fixture_vs_index_frac", "stop_loss_resolution",
                         "freight_pay_date"))
    stop_raw, swap_raw = d.get("stop_loss"), d.get("swap")
    stop = None
    if stop_raw is not None:
        sw = _where(where, "stop_loss")
        s = _fields(stop_raw, sw, ("stop_loss_usd_box", "latest_fixture_date", "note"),
                    derived=("triggered", "trigger_date"))
        stop = FreightStopLoss(
            stop_loss_usd_box=_float(_req(s, "stop_loss_usd_box", sw), _where(sw, "stop_loss_usd_box")),
            latest_fixture_date=_date(_req(s, "latest_fixture_date", sw), _where(sw, "latest_fixture_date")),
            note=str(s.get("note", "")), extra=s["extra"],
        )
    swap = None
    if swap_raw is not None:
        ww = _where(where, "swap")
        s = _fields(swap_raw, ww, ("swap_id", "boxes", "strike_usd_box", "start_date", "settle_date", "hypothetical"))
        swap = FreightSwap(
            swap_id=_str(_req(s, "swap_id", ww), _where(ww, "swap_id")),
            boxes=_int(_req(s, "boxes", ww), _where(ww, "boxes")),
            strike_usd_box=_float(_req(s, "strike_usd_box", ww), _where(ww, "strike_usd_box")),
            start_date=_date(_req(s, "start_date", ww), _where(ww, "start_date")),
            settle_date=_date(_req(s, "settle_date", ww), _where(ww, "settle_date")),
            hypothetical=_bool(s.get("hypothetical", True), _where(ww, "hypothetical")), extra=s["extra"],
        )
    return Freight(
        booked_by=_str(_req(d, "booked_by", where), _where(where, "booked_by")),
        forwarder=_str(_req(d, "forwarder", where), _where(where, "forwarder")),
        payment_terms=_enum(FreightPaymentTerms, _req(d, "payment_terms", where), _where(where, "payment_terms")),
        risk_layer=_enum(FreightRiskLayer, _req(d, "risk_layer", where), _where(where, "risk_layer")),
        fixture_date=_opt_date(d.get("fixture_date"), _where(where, "fixture_date")),
        rate_usd_box=_opt_float(d.get("rate_usd_box"), _where(where, "rate_usd_box")),
        stop_loss=stop, swap=swap, extra=d["extra"],
    )


def _read_sale(raw: Any, where: str) -> Sale:
    d = _fields(raw, where, ("sale_id", "buyer_id", "contract_date", "lot_ids", "delivery_basis", "pricing",
                             "payment", "quality_passthrough"),
                derived=("invoice_date", "due_date", "sale_price_inr_t", "credit_check_utilisation_frac"))
    pw = _where(where, "pricing")
    p = _fields(_req(d, "pricing", where), pw,
                ("type", "price_inr_t", "mcx_series", "window_start", "window_end", "factor_frac",
                 "premium_inr_t", "terms_basis_note"),
                derived=("mcx_average_inr_kg", "realised_price_inr_t", "replacement_inr_t", "netback_inr_t"))
    pricing = SalePricing(
        type=_enum(SalePricingType, _req(p, "type", pw), _where(pw, "type")),
        price_inr_t=_opt_float(p.get("price_inr_t"), _where(pw, "price_inr_t")),
        mcx_series=_opt_enum(McxSeries, p.get("mcx_series"), _where(pw, "mcx_series")),
        window_start=_opt_date(p.get("window_start"), _where(pw, "window_start")),
        window_end=_opt_date(p.get("window_end"), _where(pw, "window_end")),
        factor_frac=_opt_float(p.get("factor_frac"), _where(pw, "factor_frac")),
        premium_inr_t=_float(p.get("premium_inr_t", 0.0), _where(pw, "premium_inr_t")),
        terms_basis_note=str(p.get("terms_basis_note", "")), extra=p["extra"],
    )
    yw = _where(where, "payment")
    y = _fields(_req(d, "payment", where), yw, ("terms", "credit_days", "advance_frac", "advance_date"))
    payment = SalePayment(
        terms=_enum(SalePaymentTerms, _req(y, "terms", yw), _where(yw, "terms")),
        credit_days=_opt_int(y.get("credit_days"), _where(yw, "credit_days")),
        advance_frac=_opt_float(y.get("advance_frac"), _where(yw, "advance_frac")),
        advance_date=_opt_date(y.get("advance_date"), _where(yw, "advance_date")), extra=y["extra"],
    )
    return Sale(
        sale_id=_str(_req(d, "sale_id", where), _where(where, "sale_id")),
        buyer_id=_str(_req(d, "buyer_id", where), _where(where, "buyer_id")),
        contract_date=_date(_req(d, "contract_date", where), _where(where, "contract_date")),
        lot_ids=_str_list(_req(d, "lot_ids", where), _where(where, "lot_ids")),
        delivery_basis=_str(_req(d, "delivery_basis", where), _where(where, "delivery_basis")),
        pricing=pricing, payment=payment,
        quality_passthrough=_bool(d.get("quality_passthrough", True), _where(where, "quality_passthrough")),
        extra=d["extra"],
    )


def _read_hedges(raw: Any, where: str) -> Hedges:
    d = _fields(raw, where, ("mcx", "fx_forwards"))
    mw = _where(where, "mcx")
    m = _fields(d.get("mcx"), mw, ("hedge_ratio_target", "exposure_basis", "basis_risk_note", "unhedged_reason",
                                   "tranches"),
                derived=("hedge_ratio_actual", "exposure_at_entry_mt_eq", "sizing_basis"))
    tranches = []
    for i, r in enumerate(_seq(m.get("tranches"), _where(mw, "tranches"))):
        tw = f"{_where(mw, 'tranches')}[{i}]"
        t = _fields(r, tw, ("hedge_id", "contract_month", "direction", "lots", "entry_date", "exit_date",
                            "exit_reason", "roll_to"),
                    derived=("entry_price_inr_kg", "exit_price_inr_kg", "settle_inr_kg", "vm_inr",
                             "im_required_inr", "roll_deadline"))
        tranches.append(McxTranche(
            hedge_id=_str(_req(t, "hedge_id", tw), _where(tw, "hedge_id")),
            contract_month=_str(_req(t, "contract_month", tw), _where(tw, "contract_month")),
            direction=_enum(HedgeDirection, _req(t, "direction", tw), _where(tw, "direction")),
            lots=_int(_req(t, "lots", tw), _where(tw, "lots")),
            entry_date=_date(_req(t, "entry_date", tw), _where(tw, "entry_date")),
            exit_date=_date(_req(t, "exit_date", tw), _where(tw, "exit_date")),
            exit_reason=_enum(HedgeExitReason, _req(t, "exit_reason", tw), _where(tw, "exit_reason")),
            roll_to=(None if t.get("roll_to") is None else _str(t["roll_to"], _where(tw, "roll_to"))),
            extra=t["extra"]))
    mcx = McxHedge(
        hedge_ratio_target=_opt_float(m.get("hedge_ratio_target"), _where(mw, "hedge_ratio_target")),
        exposure_basis=_enum(ExposureBasis, m.get("exposure_basis", ExposureBasis.NET_LME_EQ_DELTA.value),
                             _where(mw, "exposure_basis")),
        basis_risk_note=str(m.get("basis_risk_note", "")), unhedged_reason=str(m.get("unhedged_reason", "")),
        tranches=tuple(tranches), extra=m["extra"])

    fw = _where(where, "fx_forwards")
    f = _fields(d.get("fx_forwards"), fw, ("hedge_frac_target", "lines"))
    lines = []
    for i, r in enumerate(_seq(f.get("lines"), _where(fw, "lines"))):
        lw = f"{_where(fw, 'lines')}[{i}]"
        x = _fields(r, lw, ("fwd_id", "booking_date", "direction", "notional_usd", "value_date", "matched_leg",
                            "cancel_date"),
                    derived=("forward_mid_inr", "bank_margin_inr", "rate_inr", "strike_usdinr", "hedge_pct_actual"))
        lines.append(FxForward(
            fwd_id=_str(_req(x, "fwd_id", lw), _where(lw, "fwd_id")),
            booking_date=_date(_req(x, "booking_date", lw), _where(lw, "booking_date")),
            direction=_enum(FxDirection, _req(x, "direction", lw), _where(lw, "direction")),
            notional_usd=_float(_req(x, "notional_usd", lw), _where(lw, "notional_usd")),
            value_date=_date(_req(x, "value_date", lw), _where(lw, "value_date")),
            matched_leg=_enum(MatchedLeg, _req(x, "matched_leg", lw), _where(lw, "matched_leg")),
            cancel_date=_opt_date(x.get("cancel_date"), _where(lw, "cancel_date")), extra=x["extra"]))
    fx = FxHedge(hedge_frac_target=_opt_float(f.get("hedge_frac_target"), _where(fw, "hedge_frac_target")),
                 lines=tuple(lines), extra=f["extra"])
    return Hedges(mcx=mcx, fx_forwards=fx, extra=d["extra"])


def _read_events(raw: Any, where: str) -> Events:
    d = _fields(raw, where, ("quality", "logistics", "buyer_payment_delay"))
    quality = []
    for i, r in enumerate(_seq(d.get("quality"), _where(where, "quality"))):
        qw = f"{_where(where, 'quality')}[{i}]"
        q = _fields(r, qw, ("lot_id", "moisture_actual_frac", "contamination_actual_frac", "rejected_boxes",
                            "rejection_reason", "claim_recovery_frac", "flag", "note"),
                    derived=("known_date", "payable_mt", "discount_frac", "claim_usd"))
        quality.append(QualityEvent(
            lot_id=_str(_req(q, "lot_id", qw), _where(qw, "lot_id")),
            moisture_actual_frac=_float(_req(q, "moisture_actual_frac", qw), _where(qw, "moisture_actual_frac")),
            contamination_actual_frac=_float(_req(q, "contamination_actual_frac", qw),
                                             _where(qw, "contamination_actual_frac")),
            rejected_boxes=_int(q.get("rejected_boxes", 0), _where(qw, "rejected_boxes")),
            rejection_reason=_opt_enum(RejectionReason, q.get("rejection_reason"), _where(qw, "rejection_reason")),
            claim_recovery_frac=_float(q.get("claim_recovery_frac", 1.0), _where(qw, "claim_recovery_frac")),
            flag=_enum(Flag, q.get("flag", Flag.SIM.value), _where(qw, "flag")),
            note=str(q.get("note", "")), extra=q["extra"]))
    logistics = []
    for i, r in enumerate(_seq(d.get("logistics"), _where(where, "logistics"))):
        gw = f"{_where(where, 'logistics')}[{i}]"
        g = _fields(r, gw, ("event_id", "lot_id", "known_date", "arrival_delay_days", "extra_dwell_days",
                            "real_trigger_ref", "flag", "note"),
                    derived=("demurrage_usd", "demurrage_inr"))
        logistics.append(LogisticsEvent(
            event_id=_str(_req(g, "event_id", gw), _where(gw, "event_id")),
            lot_id=_str(_req(g, "lot_id", gw), _where(gw, "lot_id")),
            known_date=_date(_req(g, "known_date", gw), _where(gw, "known_date")),
            arrival_delay_days=_int(g.get("arrival_delay_days", 0), _where(gw, "arrival_delay_days")),
            extra_dwell_days=_int(g.get("extra_dwell_days", 0), _where(gw, "extra_dwell_days")),
            real_trigger_ref=str(g.get("real_trigger_ref", "")),
            flag=_enum(Flag, g.get("flag", Flag.SIM.value), _where(gw, "flag")),
            note=str(g.get("note", "")), extra=g["extra"]))
    delays = []
    for i, r in enumerate(_seq(d.get("buyer_payment_delay"), _where(where, "buyer_payment_delay"))):
        bw = f"{_where(where, 'buyer_payment_delay')}[{i}]"
        b = _fields(r, bw, ("event_id", "sale_id", "known_date", "delay_days", "reason", "flag"),
                    derived=("receipt_date", "days_past_due", "overdue_funding_inr"))
        delays.append(BuyerPaymentDelayEvent(
            event_id=_str(_req(b, "event_id", bw), _where(bw, "event_id")),
            sale_id=_str(_req(b, "sale_id", bw), _where(bw, "sale_id")),
            known_date=_date(_req(b, "known_date", bw), _where(bw, "known_date")),
            delay_days=_int(_req(b, "delay_days", bw), _where(bw, "delay_days")),
            reason=str(b.get("reason", "")),
            flag=_enum(Flag, b.get("flag", Flag.SIM.value), _where(bw, "flag")), extra=b["extra"]))
    return Events(quality=tuple(quality), logistics=tuple(logistics), buyer_payment_delay=tuple(delays),
                  extra=d["extra"])


def _read_rationale(raw: Any, where: str) -> Rationale:
    d = _fields(raw, where, ("text", "parity_week_end", "cited_columns", "cited_refs"),
                derived=("trade_eligible", "net_arb_inr_t", "net_arb_pit_mix_inr_t", "net_arb_conv18k_inr_t"))
    return Rationale(
        text=_str(_req(d, "text", where), _where(where, "text")),
        parity_week_end=_date(_req(d, "parity_week_end", where), _where(where, "parity_week_end")),
        cited_columns=_str_list(d.get("cited_columns", []), _where(where, "cited_columns")),
        cited_refs=_str_list(d.get("cited_refs", []), _where(where, "cited_refs")),
        extra=d["extra"],
    )


def _read_ticket(raw: Any, where: str) -> Ticket:
    d = _fields(raw, where, ("trade_id", "status", "trade_date", "lane", "grade", "quantity_mt", "purchase",
                             "shipment", "freight", "sales", "hedges", "events", "rationale"),
                derived=("boxes", "payload_mt_per_box", "day_one_value_inr", "close_date", "cum_pnl_inr"))
    sales_raw = _seq(_req(d, "sales", where), _where(where, "sales"))
    return Ticket(
        trade_id=_str(_req(d, "trade_id", where), _where(where, "trade_id")),
        status=_enum(TicketStatus, d.get("status", TicketStatus.EXECUTED.value), _where(where, "status")),
        trade_date=_date(_req(d, "trade_date", where), _where(where, "trade_date")),
        lane=_enum(Lane, _req(d, "lane", where), _where(where, "lane")),
        grade=_enum(Grade, _req(d, "grade", where), _where(where, "grade")),
        quantity_mt=_float(_req(d, "quantity_mt", where), _where(where, "quantity_mt")),
        purchase=_read_purchase(_req(d, "purchase", where), _where(where, "purchase")),
        shipment=_read_shipment(_req(d, "shipment", where), _where(where, "shipment")),
        freight=(None if d.get("freight") is None else _read_freight(d["freight"], _where(where, "freight"))),
        sales=tuple(_read_sale(r, f"{_where(where, 'sales')}[{i}]") for i, r in enumerate(sales_raw)),
        hedges=_read_hedges(d.get("hedges"), _where(where, "hedges")),
        events=_read_events(d.get("events"), _where(where, "events")),
        rationale=_read_rationale(_req(d, "rationale", where), _where(where, "rationale")),
        extra=d["extra"],
    )


def _read_counterparty(raw: Any, where: str) -> Counterparty:
    d = _fields(raw, where, ("cp_id", "name", "role", "type", "country", "location", "lanes", "grades",
                             "credit_limit_inr", "claims_exposure_limit_usd", "default_payment_terms",
                             "credit_days_default", "lc_confirmation_required", "safe_origin_for_psic",
                             "msme_registered", "profile", "flag", "note"),
                derived=("exposure_inr", "utilisation_frac", "days_past_due", "credit_score", "order_concentration_frac"))
    pw = _where(where, "profile")
    p = _fields(_req(d, "profile", where), pw,
                ("relationship_start", "years_in_business", "annual_turnover_inr", "prior_invoices_n",
                 "prior_dpd_mean_days", "prior_dpd_max_days", "prior_defaults_n", "prior_disputed_claims_n",
                 "gst_returns_regular", "internal_rating_sim", "group_concentration_frac", "security",
                 "security_amount_inr"),
                derived=("payment_history_months",))
    profile = CounterpartyProfile(
        relationship_start=_date(_req(p, "relationship_start", pw), _where(pw, "relationship_start")),
        years_in_business=_int(_req(p, "years_in_business", pw), _where(pw, "years_in_business")),
        annual_turnover_inr=_float(_req(p, "annual_turnover_inr", pw), _where(pw, "annual_turnover_inr")),
        prior_invoices_n=_int(_req(p, "prior_invoices_n", pw), _where(pw, "prior_invoices_n")),
        prior_dpd_mean_days=_float(p.get("prior_dpd_mean_days", 0.0), _where(pw, "prior_dpd_mean_days")),
        prior_dpd_max_days=_int(p.get("prior_dpd_max_days", 0), _where(pw, "prior_dpd_max_days")),
        prior_defaults_n=_int(p.get("prior_defaults_n", 0), _where(pw, "prior_defaults_n")),
        prior_disputed_claims_n=_int(p.get("prior_disputed_claims_n", 0), _where(pw, "prior_disputed_claims_n")),
        gst_returns_regular=_bool(p.get("gst_returns_regular", True), _where(pw, "gst_returns_regular")),
        internal_rating_sim=str(p.get("internal_rating_sim", "")),
        group_concentration_frac=_opt_float(p.get("group_concentration_frac"), _where(pw, "group_concentration_frac")),
        security=_enum(Security, p.get("security", Security.NONE.value), _where(pw, "security")),
        security_amount_inr=_float(p.get("security_amount_inr", 0.0), _where(pw, "security_amount_inr")),
        extra=p["extra"],
    )
    return Counterparty(
        cp_id=_str(_req(d, "cp_id", where), _where(where, "cp_id")),
        name=_str(_req(d, "name", where), _where(where, "name")),
        role=_enum(Role, _req(d, "role", where), _where(where, "role")),
        type=_enum(CounterpartyType, _req(d, "type", where), _where(where, "type")),
        country=_str(_req(d, "country", where), _where(where, "country")),
        location=_str(_req(d, "location", where), _where(where, "location")),
        profile=profile,
        lanes=tuple(_enum(Lane, v, f"{_where(where, 'lanes')}[{i}]")
                    for i, v in enumerate(_seq(d.get("lanes"), _where(where, "lanes")))),
        grades=tuple(_enum(Grade, v, f"{_where(where, 'grades')}[{i}]")
                     for i, v in enumerate(_seq(d.get("grades"), _where(where, "grades")))),
        credit_limit_inr=_opt_float(d.get("credit_limit_inr"), _where(where, "credit_limit_inr")),
        claims_exposure_limit_usd=_opt_float(d.get("claims_exposure_limit_usd"),
                                             _where(where, "claims_exposure_limit_usd")),
        default_payment_terms=_opt_enum(SalePaymentTerms, d.get("default_payment_terms"),
                                        _where(where, "default_payment_terms")),
        credit_days_default=_opt_int(d.get("credit_days_default"), _where(where, "credit_days_default")),
        lc_confirmation_required=_bool(d.get("lc_confirmation_required", False),
                                       _where(where, "lc_confirmation_required")),
        safe_origin_for_psic=_bool(d.get("safe_origin_for_psic", False), _where(where, "safe_origin_for_psic")),
        msme_registered=_bool(d.get("msme_registered", False), _where(where, "msme_registered")),
        flag=_enum(Flag, d.get("flag", Flag.SIM.value), _where(where, "flag")),
        note=str(d.get("note", "")), extra=d["extra"],
    )


def _load_yaml(path: str | Path, root_key: str) -> list[Any]:
    p = Path(path)
    if not p.exists():
        raise SchemaError(f"{p}: file not found")
    raw = yaml.safe_load(p.read_text()) or {}
    if not isinstance(raw, Mapping):
        raise SchemaError(f"{p}: expected a mapping with 'schema_version' and '{root_key}'")
    unknown = set(raw) - {"schema_version", root_key}
    if unknown:
        raise SchemaError(f"{p}: unknown top-level keys {sorted(unknown)} (allowed: schema_version, {root_key})")
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaError(f"{p}.schema_version: expected {SCHEMA_VERSION}, got {version!r}")
    items = raw.get(root_key)
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)) or not items:
        raise SchemaError(f"{p}.{root_key}: expected a non-empty list")
    return list(items)


def load_trades(path: str | Path) -> list[Ticket]:
    """Parse `config/trades.yaml` (or a fixture) into tickets. Raises SchemaError naming the offending path."""
    items = _load_yaml(path, "trades")
    out = []
    for i, raw in enumerate(items):
        tid = raw.get("trade_id") if isinstance(raw, Mapping) else None
        where = f"{Path(path).name}:trades[{i}]" + (f" ({tid})" if tid else "")
        out.append(_read_ticket(raw, where))
    return out


def load_counterparties(path: str | Path) -> list[Counterparty]:
    """Parse `config/counterparties.yaml` (or a fixture). Raises SchemaError naming the offending path."""
    items = _load_yaml(path, "counterparties")
    out = []
    for i, raw in enumerate(items):
        cid = raw.get("cp_id") if isinstance(raw, Mapping) else None
        where = f"{Path(path).name}:counterparties[{i}]" + (f" ({cid})" if cid else "")
        out.append(_read_counterparty(raw, where))
    return out


# --------------------------------------------------------------------------------------------------- validation
def _dupes(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    dup: list[str] = []
    for v in values:
        if v in seen and v not in dup:
            dup.append(v)
        seen.add(v)
    return dup


def validate_counterparties(cps: Sequence[Counterparty]) -> list[Issue]:
    """Structural and role rules for `config/counterparties.yaml` (design §2.4)."""
    issues: list[Issue] = []
    for d in _dupes(c.cp_id for c in cps):
        issues.append(_err("V01", f"counterparties({d})", "duplicate cp_id"))
    for c in cps:
        w = f"counterparties({c.cp_id})"
        if not CP_ID_RE.match(c.cp_id):
            issues.append(_err("V01", w, f"cp_id {c.cp_id!r} must match {CP_ID_RE.pattern} (e.g. SUP_JEA_01)"))
        if not c.name.endswith(SIM_SUFFIX):
            issues.append(_err("V02", f"{w}.name", f"every counterparty is fictional: name must end with '{SIM_SUFFIX}'"))
        if c.flag is not Flag.SIM:
            issues.append(_err("V02", f"{w}.flag", "counterparties are simulated: flag must be SIM"))
        if c.role is Role.SUPPLIER:
            if c.type not in SUPPLIER_TYPES:
                issues.append(_err("V03", f"{w}.type", f"supplier type must be one of "
                                                       f"{', '.join(t.value for t in SUPPLIER_TYPES)}"))
            if not c.lanes:
                issues.append(_err("V03", f"{w}.lanes", "a supplier must declare the lane(s) it can load"))
            if c.credit_limit_inr is not None:
                issues.append(_err("V03", f"{w}.credit_limit_inr",
                                   "credit_limit_inr is a buyer field; use claims_exposure_limit_usd for suppliers"))
        else:
            if c.type not in BUYER_TYPES:
                issues.append(_err("V03", f"{w}.type", f"buyer type must be one of "
                                                       f"{', '.join(t.value for t in BUYER_TYPES)}"))
            if c.credit_limit_inr is None:
                issues.append(_err("V03", f"{w}.credit_limit_inr",
                                   "a buyer needs a credit limit (0 means advance-only); it feeds the P5 tracker"))
            elif c.credit_limit_inr < 0:
                issues.append(_err("V03", f"{w}.credit_limit_inr", "must be >= 0"))
            cap = int(config.value("msme_max_payment_days"))
            if c.credit_days_default is not None and c.credit_days_default > cap:
                issues.append(_err("V09", f"{w}.credit_days_default",
                                   f"{c.credit_days_default} days exceeds the desk policy cap "
                                   f"msme_max_payment_days = {cap}"))
        if c.profile.relationship_start > WINDOW_START:
            issues.append(_warn("V03", f"{w}.profile.relationship_start",
                                f"relationship starts after WINDOW_START ({WINDOW_START}); P5 payment history is empty"))
    return issues


def _validate_dates_are_panel_days(t: Ticket, panel_days: set[dt.date] | None) -> list[Issue]:
    """Decision dates are made by a trader on a trading day; derived cashflow dates are rolled by the engine."""
    if panel_days is None:
        return []
    issues: list[Issue] = []
    w = f"trades({t.trade_id})"
    checks: list[tuple[str, dt.date]] = [("trade_date", t.trade_date),
                                         ("purchase.payment.lc_open_date", t.purchase.payment.lc_open_date)]
    for lot in t.shipment.lots:
        checks.append((f"shipment.lots({lot.lot_id}).bl_date", lot.bl_date))
    if t.freight is not None:
        if t.freight.fixture_date is not None:
            checks.append(("freight.fixture_date", t.freight.fixture_date))
        if t.freight.stop_loss is not None:
            checks.append(("freight.stop_loss.latest_fixture_date", t.freight.stop_loss.latest_fixture_date))
    for s in t.sales:
        checks.append((f"sales({s.sale_id}).contract_date", s.contract_date))
        if s.payment.advance_date is not None:
            checks.append((f"sales({s.sale_id}).payment.advance_date", s.payment.advance_date))
        if s.pricing.window_start is not None:
            checks.append((f"sales({s.sale_id}).pricing.window_start", s.pricing.window_start))
            checks.append((f"sales({s.sale_id}).pricing.window_end", s.pricing.window_end))
    for tr in t.hedges.mcx.tranches:
        checks.append((f"hedges.mcx({tr.hedge_id}).entry_date", tr.entry_date))
        checks.append((f"hedges.mcx({tr.hedge_id}).exit_date", tr.exit_date))
    for fx in t.hedges.fx_forwards.lines:
        checks.append((f"hedges.fx_forwards({fx.fwd_id}).booking_date", fx.booking_date))
        if fx.cancel_date is not None:
            checks.append((f"hedges.fx_forwards({fx.fwd_id}).cancel_date", fx.cancel_date))
    for name, d in checks:
        if d is not None and d not in panel_days:
            issues.append(_err("V04", f"{w}.{name}",
                               f"{d} is not an LME trading day; decision dates are never silently rolled "
                               f"(CONTRACTS §3)"))
    return issues


def validate_trades(trades: Sequence[Ticket], counterparties: Sequence[Counterparty] = (), *,
                    panel_days: set[dt.date] | None = None, allow_hypothetical: bool = False) -> list[Issue]:
    """Every rule that the ticket, the counterparty file and the register can decide on their own.

    `panel_days` (optional) adds the LME-trading-day check on decision dates. `allow_hypothetical` must be True
    before a ticket may carry the labelled hypothetical freight swap — it is never allowed in the base book.
    """
    issues: list[Issue] = []
    by_id = {c.cp_id: c for c in counterparties}
    for d in _dupes(t.trade_id for t in trades):
        issues.append(_err("V01", f"trades({d})", "duplicate trade_id"))

    for t in trades:
        w = f"trades({t.trade_id})"
        if not TRADE_ID_RE.match(t.trade_id):
            issues.append(_err("V01", w, f"trade_id must match {TRADE_ID_RE.pattern}"))

        # --- V05 window, discipline
        if not (WINDOW_START <= t.trade_date <= WINDOW_END):
            issues.append(_err("V05", f"{w}.trade_date",
                               f"{t.trade_date} is outside the backtest window {WINDOW_START}..{WINDOW_END}"))
        if t.rationale.parity_week_end > t.trade_date:
            issues.append(_err("V05", f"{w}.rationale.parity_week_end",
                               f"parity week {t.rationale.parity_week_end} is after the trade date {t.trade_date}: "
                               f"a decision may only use information published on or before it (CONTRACTS §5a)"))
        elif (t.trade_date - t.rationale.parity_week_end).days >= 7:
            issues.append(_err("V05", f"{w}.rationale.parity_week_end",
                               f"parity week {t.rationale.parity_week_end} is stale for a trade on {t.trade_date}: "
                               f"use the latest week_end <= trade_date"))
        if not t.rationale.text.strip():
            issues.append(_err("V05", f"{w}.rationale.text", "Table 4 row 2.9 requires a trader's rationale"))

        # --- V06 size and boxes
        if not (MIN_TRADE_MT <= t.quantity_mt <= MAX_TRADE_MT):
            issues.append(_err("V06", f"{w}.quantity_mt",
                               f"{t.quantity_mt:,.1f} MT is outside the Table 4 row 2.1 band "
                               f"{MIN_TRADE_MT:,.0f}-{MAX_TRADE_MT:,.0f} MT"))
        if not t.shipment.lots:
            issues.append(_err("V06", f"{w}.shipment.lots", "a ticket needs at least one lot (one bill of lading)"))
        elif len(t.shipment.lots) > MAX_LOTS_PER_TICKET:
            issues.append(_err("V06", f"{w}.shipment.lots",
                               f"{len(t.shipment.lots)} lots: a container SPA is modelled on at most "
                               f"{MAX_LOTS_PER_TICKET} sailings"))
        for d in _dupes(l.lot_id for l in t.shipment.lots):
            issues.append(_err("V01", f"{w}.shipment.lots({d})", "duplicate lot_id"))
        for lot in t.shipment.lots:
            if not LOT_ID_RE.match(lot.lot_id):
                issues.append(_err("V01", f"{w}.shipment.lots({lot.lot_id})",
                                   f"lot_id must match {LOT_ID_RE.pattern}"))
            if lot.boxes < 1:
                issues.append(_err("V06", f"{w}.shipment.lots({lot.lot_id}).boxes", "must be at least one container"))
            if not lot.vessel.endswith(SIM_SUFFIX):
                issues.append(_err("V02", f"{w}.shipment.lots({lot.lot_id}).vessel",
                                   f"vessel names are fictional: must end with '{SIM_SUFFIX}'"))
        if t.shipment.lots:
            implied = t.boxes * t.payload_mt_per_box
            if abs(implied - t.quantity_mt) > BOX_TONNAGE_TOL_MT:
                issues.append(_err("V06", f"{w}.quantity_mt",
                                   f"{t.quantity_mt:,.1f} MT does not match {t.boxes} × "
                                   f"container_payload_mt_{t.box}_{t.grade.value} = {implied:,.1f} MT "
                                   f"(containers ship whole)"))

        # --- V07 lane / port / incoterm / freight block
        if t.shipment.discharge_port is not LANE_PORT[t.lane]:
            issues.append(_err("V07", f"{w}.shipment.discharge_port",
                               f"lane {t.lane} discharges at {LANE_PORT[t.lane]}, not {t.shipment.discharge_port}"))
        if t.purchase.incoterm is Incoterm.FOB and t.freight is None:
            issues.append(_err("V07", f"{w}.freight",
                               "FOB: the desk books and bears the ocean freight, so a freight block is required"))
        if t.purchase.incoterm is Incoterm.CFR and t.freight is not None:
            issues.append(_err("V07", f"{w}.freight",
                               "CFR: freight is the seller's cost inside the price; remove the freight block"))

        # --- V08 laycan and B/L dates
        sh = t.shipment
        if sh.laycan_start > sh.laycan_end:
            issues.append(_err("V08", f"{w}.shipment", "laycan_start is after laycan_end"))
        if (sh.laycan_end - sh.laycan_start).days > MAX_LAYCAN_SPAN_DAYS:
            issues.append(_err("V08", f"{w}.shipment", f"laycan spans more than {MAX_LAYCAN_SPAN_DAYS} days"))
        if sh.laycan_start < t.trade_date:
            issues.append(_err("V08", f"{w}.shipment.laycan_start", "shipment cannot start before the contract date"))
        if t.purchase.pricing.type is PurchasePricingType.LME_M1_AVG and (
                (sh.laycan_start.year, sh.laycan_start.month) != (sh.laycan_end.year, sh.laycan_end.month)):
            issues.append(_err("V08", f"{w}.shipment",
                               "an M+1 laycan must sit inside one calendar month so the quotational period is "
                               "known on the trade date (design D3)"))
        for lot in sh.lots:
            if not (sh.laycan_start <= lot.bl_date <= sh.laycan_end):
                issues.append(_err("V08", f"{w}.shipment.lots({lot.lot_id}).bl_date",
                                   f"{lot.bl_date} is outside the laycan {sh.laycan_start}..{sh.laycan_end}"))

        # --- V10 purchase pricing
        pr, pw = t.purchase.pricing, f"{w}.purchase.pricing"
        if pr.type is PurchasePricingType.FIXED:
            if pr.price_usd_t is None or pr.price_usd_t <= 0:
                issues.append(_err("V10", f"{pw}.price_usd_t", "FIXED pricing needs a positive price_usd_t"))
            for extra_key in ("factor_frac", "lme_reference", "provisional_frac"):
                if getattr(pr, extra_key) is not None:
                    issues.append(_err("V10", f"{pw}.{extra_key}", f"not used with FIXED pricing"))
        else:
            if pr.factor_frac is None or not (0.40 <= pr.factor_frac <= 1.00):
                issues.append(_err("V10", f"{pw}.factor_frac",
                                   "LME_M1_AVG pricing needs a grade factor in 0.40..1.00"))
            if pr.lme_reference is None:
                issues.append(_err("V10", f"{pw}.lme_reference",
                                   "state the LME reference the formula settles against (CASH — exchange.yaml "
                                   "lme_pricing_reference)"))
            if pr.price_usd_t is not None:
                issues.append(_err("V10", f"{pw}.price_usd_t", "not used with LME_M1_AVG pricing"))
            if pr.provisional_frac is not None and not (0.5 < pr.provisional_frac <= 1.0):
                issues.append(_err("V10", f"{pw}.provisional_frac", "must be in (0.5, 1.0]"))
        if not pr.terms_basis_note.strip():
            issues.append(_warn("V10", f"{pw}.terms_basis_note",
                                "record how the price/factor was set from information dated <= trade_date"))

        # --- V11 payment instrument
        pay, yw = t.purchase.payment, f"{w}.purchase.payment"
        if pay.instrument is PaymentInstrument.LC_USANCE:
            if pay.usance_days is None or not (MIN_USANCE_DAYS <= pay.usance_days <= MAX_USANCE_DAYS):
                issues.append(_err("V11", f"{yw}.usance_days",
                                   f"usance must be {MIN_USANCE_DAYS}-{MAX_USANCE_DAYS} days from B/L "
                                   f"(Table 4 row 2.6)"))
        elif pay.usance_days is not None:
            issues.append(_err("V11", f"{yw}.usance_days", "a sight LC has no usance tenor"))
        if not (t.trade_date <= pay.lc_open_date <= sh.laycan_start):
            issues.append(_err("V11", f"{yw}.lc_open_date",
                               f"{pay.lc_open_date} must fall between the trade date {t.trade_date} and the laycan "
                               f"start {sh.laycan_start} — the seller will not ship without a workable LC"))
        if pay.confirmed and pay.confirmation_charges_for is None:
            issues.append(_err("V11", f"{yw}.confirmation_charges_for",
                               "say who pays the confirmation fee (APPLICANT creates a desk cashflow)"))
        if not pay.confirmed and pay.confirmation_charges_for is not None:
            issues.append(_err("V11", f"{yw}.confirmation_charges_for", "only meaningful when confirmed is true"))
        if not pay.issuing_bank.endswith(SIM_SUFFIX):
            issues.append(_err("V02", f"{yw}.issuing_bank", f"bank names are fictional: must end with '{SIM_SUFFIX}'"))

        # --- V12 freight layer
        if t.freight is not None:
            f, fw = t.freight, f"{w}.freight"
            if not f.forwarder.endswith(SIM_SUFFIX):
                issues.append(_err("V02", f"{fw}.forwarder", f"must end with '{SIM_SUFFIX}'"))
            if (f.fixture_date is None) != (f.rate_usd_box is None):
                issues.append(_err("V12", fw, "give fixture_date and rate_usd_box together, or neither "
                                              "(neither = book at market on the first B/L date)"))
            first_bl = min((l.bl_date for l in sh.lots), default=None)
            if f.fixture_date is not None:
                if f.fixture_date < t.trade_date:
                    issues.append(_err("V12", f"{fw}.fixture_date", "cannot fix freight before the trade date"))
                if first_bl is not None and f.fixture_date > first_bl:
                    issues.append(_err("V12", f"{fw}.fixture_date",
                                       f"{f.fixture_date} is after the first B/L {first_bl}"))
                if f.rate_usd_box is not None and f.rate_usd_box <= 0:
                    issues.append(_err("V12", f"{fw}.rate_usd_box", "must be positive"))
            if f.risk_layer is FreightRiskLayer.UNHEDGED_STOP_LOSS:
                if f.stop_loss is None:
                    issues.append(_err("V12", f"{fw}.stop_loss",
                                       "Table 4 row 2.7(d): an unhedged freight layer needs a stated stop-loss"))
                else:
                    if f.stop_loss.stop_loss_usd_box <= 0:
                        issues.append(_err("V12", f"{fw}.stop_loss.stop_loss_usd_box", "must be positive"))
                    if first_bl is not None and f.stop_loss.latest_fixture_date > first_bl:
                        issues.append(_err("V12", f"{fw}.stop_loss.latest_fixture_date",
                                           f"{f.stop_loss.latest_fixture_date} is after the first B/L {first_bl}: "
                                           f"space must be booked before the boxes sail"))
                if f.swap is not None:
                    issues.append(_err("V12", f"{fw}.swap", "an UNHEDGED_STOP_LOSS layer carries no swap"))
            else:
                if f.swap is None:
                    issues.append(_err("V12", f"{fw}.swap", "a PROXY_SWAP_HYPOTHETICAL layer needs the swap block"))
                elif not f.swap.hypothetical:
                    issues.append(_err("V12", f"{fw}.swap.hypothetical",
                                       "no liquid India-lane container derivative is assumed: the swap must stay "
                                       "labelled hypothetical"))
                if not allow_hypothetical:
                    issues.append(_err("V12", f"{fw}.risk_layer",
                                       "the hypothetical freight swap may not enter the base book; it is a labelled "
                                       "stress instrument only (pass allow_hypothetical=True for that run)"))

        # --- V13 sales
        for d in _dupes(s.sale_id for s in t.sales):
            issues.append(_err("V01", f"{w}.sales({d})", "duplicate sale_id"))
        covered: dict[str, str] = {}
        lot_ids = {l.lot_id for l in sh.lots}
        if not t.sales:
            issues.append(_err("V13", f"{w}.sales", "every lot must be sold: the desk does not warehouse cargo"))
        for s in t.sales:
            sw = f"{w}.sales({s.sale_id})"
            if not SALE_ID_RE.match(s.sale_id):
                issues.append(_err("V01", sw, f"sale_id must match {SALE_ID_RE.pattern}"))
            if s.contract_date < t.trade_date:
                issues.append(_err("V13", f"{sw}.contract_date",
                                   "the desk does not sell before it has bought (no short sales in the base book)"))
            # The cargo must be sold before it is released, or the desk is warehousing it (design §9.3).
            # Calendar-day approximation; P2 re-checks against the rolled release date including delay events.
            transit = int(config.value(f"transit_days_{t.lane.value.lower()}"))
            clearance = int(config.value("clearance_delivery_days"))
            covered_lots = [l for l in sh.lots if l.lot_id in set(s.lot_ids)]
            if covered_lots:
                first_release = min(l.bl_date for l in covered_lots) + dt.timedelta(days=transit + clearance)
                if s.contract_date > first_release:
                    issues.append(_warn("V13", f"{sw}.contract_date",
                                        f"{s.contract_date} is after the planned release of the earliest covered lot "
                                        f"({first_release}): that cargo would sit in the port unsold"))
            for lid in s.lot_ids:
                if lid not in lot_ids:
                    issues.append(_err("V13", f"{sw}.lot_ids", f"{lid!r} is not a lot of this ticket"))
                elif lid in covered:
                    issues.append(_err("V13", f"{sw}.lot_ids",
                                       f"lot {lid} is already sold under {covered[lid]}"))
                else:
                    covered[lid] = s.sale_id
            sp, spw = s.pricing, f"{sw}.pricing"
            if sp.type is SalePricingType.FIXED:
                if sp.price_inr_t is None or sp.price_inr_t <= 0:
                    issues.append(_err("V14", f"{spw}.price_inr_t", "FIXED sale pricing needs a positive ₹/MT price"))
                for k in ("mcx_series", "window_start", "window_end", "factor_frac"):
                    if getattr(sp, k) is not None:
                        issues.append(_err("V14", f"{spw}.{k}", "not used with FIXED sale pricing"))
            else:
                if sp.mcx_series is None or sp.window_start is None or sp.window_end is None:
                    issues.append(_err("V14", spw,
                                       "MCX_AVG sale pricing needs mcx_series, window_start and window_end "
                                       "(Table 4 row 2.4: state the pricing period)"))
                else:
                    if sp.window_start < s.contract_date:
                        issues.append(_err("V14", f"{spw}.window_start",
                                           f"averaging starts {sp.window_start}, before the sale is contracted "
                                           f"{s.contract_date}"))
                    if sp.window_end < sp.window_start:
                        issues.append(_err("V14", f"{spw}.window_end", "window_end is before window_start"))
                    if sp.window_end > HORIZON_END:
                        issues.append(_err("V14", f"{spw}.window_end",
                                           f"{sp.window_end} is after HORIZON_END {HORIZON_END}"))
                if sp.factor_frac is None or not (0.40 <= sp.factor_frac <= 1.00):
                    issues.append(_err("V14", f"{spw}.factor_frac",
                                       "MCX_AVG sale pricing needs a recovery/discount factor in 0.40..1.00"))
                if sp.price_inr_t is not None:
                    issues.append(_err("V14", f"{spw}.price_inr_t", "not used with MCX_AVG sale pricing"))
            yp, ypw = s.payment, f"{sw}.payment"
            cap = int(config.value("msme_max_payment_days"))
            if yp.terms is SalePaymentTerms.ADVANCE:
                if yp.advance_frac is None or abs(yp.advance_frac - 1.0) > 1e-9:
                    issues.append(_err("V15", f"{ypw}.advance_frac", "ADVANCE means advance_frac = 1.0"))
                if yp.credit_days is not None:
                    issues.append(_err("V15", f"{ypw}.credit_days", "not used with ADVANCE"))
            elif yp.terms is SalePaymentTerms.CREDIT:
                if yp.advance_frac is not None or yp.advance_date is not None:
                    issues.append(_err("V15", ypw, "CREDIT carries no advance"))
                if yp.credit_days is None or yp.credit_days < 1:
                    issues.append(_err("V15", f"{ypw}.credit_days", "CREDIT needs credit_days >= 1"))
            else:
                if yp.advance_frac is None or not (0.0 < yp.advance_frac < 1.0):
                    issues.append(_err("V15", f"{ypw}.advance_frac", "ADVANCE_PLUS_CREDIT needs 0 < advance_frac < 1"))
                if yp.credit_days is None or yp.credit_days < 1:
                    issues.append(_err("V15", f"{ypw}.credit_days", "ADVANCE_PLUS_CREDIT needs credit_days >= 1"))
            if yp.credit_days is not None and yp.credit_days > cap:
                issues.append(_err("V09", f"{ypw}.credit_days",
                                   f"{yp.credit_days} days exceeds the desk policy cap msme_max_payment_days = {cap}"))
            if yp.terms in (SalePaymentTerms.ADVANCE, SalePaymentTerms.ADVANCE_PLUS_CREDIT):
                if yp.advance_date is None:
                    issues.append(_err("V15", f"{ypw}.advance_date", "an advance needs its payment date"))
                elif yp.advance_date < s.contract_date:
                    issues.append(_err("V15", f"{ypw}.advance_date", "advance cannot precede the sale contract"))
            # counterparty cross-reference
            buyer = by_id.get(s.buyer_id)
            if counterparties and buyer is None:
                issues.append(_err("V16", f"{sw}.buyer_id", f"{s.buyer_id!r} is not in the counterparty file"))
            elif buyer is not None and buyer.role is not Role.BUYER:
                issues.append(_err("V16", f"{sw}.buyer_id", f"{s.buyer_id} is a {buyer.role}, not a BUYER"))
        for lid in sorted(lot_ids - set(covered)):
            issues.append(_err("V13", f"{w}.sales", f"lot {lid} is never sold"))

        # --- V16 supplier cross-reference
        sup = by_id.get(t.purchase.supplier_id)
        if counterparties and sup is None:
            issues.append(_err("V16", f"{w}.purchase.supplier_id",
                               f"{t.purchase.supplier_id!r} is not in the counterparty file"))
        elif sup is not None:
            if sup.role is not Role.SUPPLIER:
                issues.append(_err("V16", f"{w}.purchase.supplier_id", f"{sup.cp_id} is a {sup.role}, not a SUPPLIER"))
            if sup.lanes and t.lane not in sup.lanes:
                issues.append(_err("V16", f"{w}.purchase.supplier_id",
                                   f"{sup.cp_id} does not load on {t.lane} (declared: "
                                   f"{', '.join(l.value for l in sup.lanes)})"))
            if sup.grades and t.grade not in sup.grades:
                issues.append(_err("V16", f"{w}.grade",
                                   f"{sup.cp_id} does not supply {t.grade} (declared: "
                                   f"{', '.join(g.value for g in sup.grades)})"))

        # --- V17 MCX hedge stack
        mx = t.hedges.mcx
        tranche_by_id = {tr.hedge_id: tr for tr in mx.tranches}
        for d in _dupes(tr.hedge_id for tr in mx.tranches):
            issues.append(_err("V01", f"{w}.hedges.mcx({d})", "duplicate hedge_id"))
        if not mx.tranches and not mx.unhedged_reason.strip():
            issues.append(_err("V17", f"{w}.hedges.mcx",
                               "no MCX hedge: Table 4 row 2.7 requires a stated reason for running unhedged"))
        if mx.tranches and not mx.basis_risk_note.strip():
            issues.append(_err("V17", f"{w}.hedges.mcx.basis_risk_note",
                               "Table 4 row 2.7(c) requires the cross-exchange basis-risk explanation"))
        if mx.hedge_ratio_target is not None:
            if not (0 < mx.hedge_ratio_target <= HEDGE_RATIO_MAX):
                issues.append(_err("V17", f"{w}.hedges.mcx.hedge_ratio_target",
                                   f"must be in (0, {HEDGE_RATIO_MAX}]"))
            elif not (HEDGE_RATIO_SANE[0] <= mx.hedge_ratio_target <= HEDGE_RATIO_SANE[1]):
                issues.append(_warn("V17", f"{w}.hedges.mcx.hedge_ratio_target",
                                    f"{mx.hedge_ratio_target} is outside the usual "
                                    f"{HEDGE_RATIO_SANE[0]}-{HEDGE_RATIO_SANE[1]} band"))
        lot_mt = float(config.value("mcx_al_lot_mt"))
        limit_mt = float(config.value("mcx_al_position_limit_client_mt"))
        listed = {str(d)[:7] for d in config.value("mcx_al_expiry_dates_2022")}
        for tr in mx.tranches:
            tw = f"{w}.hedges.mcx({tr.hedge_id})"
            if not HEDGE_ID_RE.match(tr.hedge_id):
                issues.append(_err("V01", tw, f"hedge_id must match {HEDGE_ID_RE.pattern} (e.g. T91-MCX-1)"))
            if not CONTRACT_MONTH_RE.match(tr.contract_month):
                issues.append(_err("V17", f"{tw}.contract_month", "must be YYYY-MM"))
            elif tr.contract_month not in listed:
                issues.append(_err("V17", f"{tw}.contract_month",
                                   f"{tr.contract_month} is not a listed MCX Aluminium month "
                                   f"(exchange.yaml mcx_al_expiry_dates_2022)"))
            if tr.lots < 1:
                issues.append(_err("V17", f"{tw}.lots",
                                   "lots is the position size in whole 5 MT lots; direction carries the sign"))
            elif tr.lots * lot_mt > limit_mt:
                issues.append(_err("V17", f"{tw}.lots",
                                   f"{tr.lots} lots = {tr.lots * lot_mt:,.0f} MT exceeds the DIRECT client position "
                                   f"limit mcx_al_position_limit_client_mt = {limit_mt:,.0f} MT"))
            if tr.entry_date < t.trade_date:
                issues.append(_err("V17", f"{tw}.entry_date", "a hedge cannot pre-date the trade it hedges"))
            if tr.exit_date <= tr.entry_date:
                issues.append(_err("V17", f"{tw}.exit_date", f"{tr.exit_date} is not after entry {tr.entry_date}"))
            if tr.exit_reason is HedgeExitReason.ROLL:
                if tr.roll_to is None:
                    issues.append(_err("V17", f"{tw}.roll_to", "a ROLL exit must name the tranche it rolls into"))
                else:
                    tgt = tranche_by_id.get(tr.roll_to)
                    if tgt is None:
                        issues.append(_err("V17", f"{tw}.roll_to", f"{tr.roll_to!r} is not a tranche of this ticket"))
                    else:
                        if tgt.entry_date != tr.exit_date:
                            issues.append(_err("V17", f"{tw}.roll_to",
                                               f"a roll is one decision: {tr.roll_to} must enter on {tr.exit_date}, "
                                               f"not {tgt.entry_date}"))
                        if tgt.direction is not tr.direction or tgt.lots != tr.lots:
                            issues.append(_err("V17", f"{tw}.roll_to",
                                               f"a roll keeps the position: {tr.roll_to} must be "
                                               f"{tr.direction} {tr.lots} lots"))
                        if tgt.contract_month <= tr.contract_month:
                            issues.append(_err("V17", f"{tw}.roll_to",
                                               f"a roll moves to a later contract month than {tr.contract_month}"))
            elif tr.roll_to is not None:
                issues.append(_err("V17", f"{tw}.roll_to", f"only a ROLL exit carries roll_to (this is {tr.exit_reason})"))

        # --- V18 FX forwards
        fx = t.hedges.fx_forwards
        for d in _dupes(x.fwd_id for x in fx.lines):
            issues.append(_err("V01", f"{w}.hedges.fx_forwards({d})", "duplicate fwd_id"))
        nodoc = float(config.value("fx_hedge_no_documentation_limit_usd"))
        gross = sum(abs(x.notional_usd) for x in fx.lines)
        if gross > nodoc:
            issues.append(_warn("V18", f"{w}.hedges.fx_forwards",
                                f"USD {gross:,.0f} of forwards exceeds the DIRECT no-documentation limit "
                                f"fx_hedge_no_documentation_limit_usd = {nodoc:,.0f}; underlying documents must be "
                                f"produced to the AD bank"))
        for x in fx.lines:
            xw = f"{w}.hedges.fx_forwards({x.fwd_id})"
            if not FWD_ID_RE.match(x.fwd_id):
                issues.append(_err("V01", xw, f"fwd_id must match {FWD_ID_RE.pattern} (e.g. T91-FX-1)"))
            if x.notional_usd <= 0:
                issues.append(_err("V18", f"{xw}.notional_usd",
                                   "notional is positive; direction (BUY_USD/SELL_USD) carries the sign"))
            if x.booking_date < t.trade_date:
                issues.append(_err("V18", f"{xw}.booking_date",
                                   "a forward hedges a contracted exposure: it cannot pre-date the trade"))
            if x.value_date <= x.booking_date:
                issues.append(_err("V18", f"{xw}.value_date", "value date must be after the booking date"))
            if x.value_date > HORIZON_END:
                issues.append(_err("V19", f"{xw}.value_date",
                                   f"{x.value_date} is after HORIZON_END {HORIZON_END}: every cashflow must settle "
                                   f"inside the engine horizon (CONTRACTS §7.1)"))
            if x.cancel_date is not None and not (x.booking_date < x.cancel_date < x.value_date):
                issues.append(_err("V18", f"{xw}.cancel_date",
                                   f"{x.cancel_date} must fall strictly between booking {x.booking_date} and value "
                                   f"{x.value_date}"))

        # --- V20 events
        sale_ids = {s.sale_id for s in t.sales}
        for q in t.events.quality:
            qw = f"{w}.events.quality({q.lot_id})"
            if q.lot_id not in lot_ids:
                issues.append(_err("V20", qw, f"{q.lot_id!r} is not a lot of this ticket"))
            else:
                if q.rejected_boxes > t.lot(q.lot_id).boxes:
                    issues.append(_err("V20", f"{qw}.rejected_boxes",
                                       f"{q.rejected_boxes} exceeds the {t.lot(q.lot_id).boxes} boxes in the lot"))
            if q.rejected_boxes < 0:
                issues.append(_err("V20", f"{qw}.rejected_boxes", "cannot be negative"))
            if (q.rejected_boxes > 0) != (q.rejection_reason is not None):
                issues.append(_err("V20", f"{qw}.rejection_reason",
                                   "give the rejection reason exactly when rejected_boxes > 0"))
            if not (0.0 <= q.moisture_actual_frac <= 0.25):
                issues.append(_err("V20", f"{qw}.moisture_actual_frac", "must be a fraction in 0..0.25"))
            if not (0.0 <= q.contamination_actual_frac <= 0.5):
                issues.append(_err("V20", f"{qw}.contamination_actual_frac", "must be a fraction in 0..0.5"))
            if not (0.0 <= q.claim_recovery_frac <= 1.0):
                issues.append(_err("V20", f"{qw}.claim_recovery_frac", "must be a fraction in 0..1"))
        for g in t.events.logistics:
            gw = f"{w}.events.logistics({g.event_id})"
            if g.lot_id not in lot_ids:
                issues.append(_err("V20", f"{gw}.lot_id", f"{g.lot_id!r} is not a lot of this ticket"))
            if g.known_date < t.trade_date:
                issues.append(_err("V20", f"{gw}.known_date", "an event cannot be known before the trade exists"))
            if g.arrival_delay_days < 0 or g.extra_dwell_days < 0:
                issues.append(_err("V20", gw, "delay and dwell days are non-negative"))
            if g.arrival_delay_days == 0 and g.extra_dwell_days == 0:
                issues.append(_err("V20", gw, "a logistics event must delay arrival or add dwell"))
            ref = g.real_trigger_ref.lower()
            if any(m in ref for m in VOID_CALL_MARKERS) and g.known_date < VOID_CALL_EVIDENCE_DATE:
                issues.append(_err("V20", f"{gw}.known_date",
                                   f"the void-call report is dated {VOID_CALL_EVIDENCE_DATE} "
                                   f"(docs/research/freight_notes.md S4); it cannot be known on {g.known_date}"))
            if g.flag is Flag.DIRECT:
                issues.append(_err("V20", f"{gw}.flag",
                                   "the delay magnitudes are simulated: flag SIM (the trigger is cited separately "
                                   "in real_trigger_ref)"))
        for b in t.events.buyer_payment_delay:
            bw = f"{w}.events.buyer_payment_delay({b.event_id})"
            if b.sale_id not in sale_ids:
                issues.append(_err("V20", f"{bw}.sale_id", f"{b.sale_id!r} is not a sale of this ticket"))
            if b.delay_days <= 0:
                issues.append(_err("V20", f"{bw}.delay_days", "must be positive"))
            if b.known_date < t.trade_date:
                issues.append(_err("V20", f"{bw}.known_date", "an event cannot be known before the trade exists"))
            if b.flag is Flag.DIRECT:
                issues.append(_err("V20", f"{bw}.flag", "a simulated payment delay is flagged SIM"))

        issues.extend(_validate_dates_are_panel_days(t, panel_days))

    return issues


def validate_book(book: Book, *, panel_days: set[dt.date] | None = None,
                  allow_hypothetical: bool = False) -> list[Issue]:
    """Every counterparty and trade rule, in one list, most-structural first."""
    return (validate_counterparties(book.counterparties)
            + validate_trades(book.trades, book.counterparties, panel_days=panel_days,
                              allow_hypothetical=allow_hypothetical))


def load_book(trades_path: str | Path, counterparties_path: str | Path, *, strict: bool = True,
              panel_days: set[dt.date] | None = None, allow_hypothetical: bool = False) -> Book:
    """Parse both files and validate. With `strict`, any ERROR raises ValidationError listing all of them."""
    cps = load_counterparties(counterparties_path)
    trades = load_trades(trades_path)
    book = Book(trades=tuple(trades), counterparties=tuple(cps), trades_path=str(trades_path),
                counterparties_path=str(counterparties_path))
    issues = validate_book(book, panel_days=panel_days, allow_hypothetical=allow_hypothetical)
    errors = [i for i in issues if i.severity == "ERROR"]
    if strict and errors:
        raise ValidationError(errors)
    return book
