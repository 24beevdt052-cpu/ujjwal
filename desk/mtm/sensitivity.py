"""Result sensitivities: what the **headline book P&L** does when a registered ASSUMPTION moves (design D13+).

Three things live here, and all three exist because the base Phase 3 run answers a narrower question than a reader
assumes.

1. **Re-pricing sensitivities** (`pnl_sensitivity_*.csv`). The engine values a book whose prices are *typed* in
   `config/trades.yaml`, so swapping a parameter and re-running only **re-marks** the book. For a parameter that
   never reaches a mark — `domestic_anchor_premium_inr_t` is the important one; it enters only the smelter netback,
   and design D5 deliberately keeps the netback out of the inventory mark — a re-mark changes the P&L by exactly
   zero and says nothing. But the desk's own sale rule (`docs/20_trade_book.md` S1:
   `replacement + share x (netback - replacement)`) sets every typed sale price *from* that parameter, and its
   purchase rule (S2: trade-date parity less a discount) sets every typed purchase price from the grade factor. So
   these cases **re-derive the prices through the same two rules**, rebuild the tickets, and re-run the whole
   engine. That is the question a reader is actually asking: *would this book still have made money?*

   The desk's own negotiation delta on each leg (the ₹/MT a ticket sits away from its rule, and the USD/t a bid sits
   under parity) is **held constant**, so a case moves the rule and nothing else. Trade dates, lots, hedges, events
   and §5a eligibility are untouched: these are sensitivities, never an alternative book.

2. **Roll P&L split into carry and metal** (`mcx_roll_carry.csv`). The panel MCX series is
   `spot x (1 + inr_rate_3m_pa x days_to_expiry/365)`, so M2 > M1 on **every** panel day by construction and every
   short roll is a gain by construction. This table separates the part of each executed roll that is nothing but
   INR interest on duty-paid parity from the part that is genuine term structure (identically zero on a proxy day;
   non-zero on the mirror).

3. **Basis risk as a two-sided range** (`mcx_basis_risk.csv`). The mirror run happens to come out *better* than the
   base run, which reads like a better result and is not one. This table publishes the per-trade spread — the loss
   case beside the gain case — and tests the unit-beta assumption the hedge sizing rests on: the engine sizes an
   MCX short so that one rupee of duty-paid LME parity is one rupee of MCX, i.e. beta = 1 against parity. On the
   mirror that beta is measurable, and it is not 1.

None of these is base P&L. Every row carries a `label` saying so.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from desk import WINDOW_END, WINDOW_START, units
from desk.book import schema as bs
from desk.mtm import curves, engine
from desk.mtm.constants import param as register_param
from desk.mtm.history import MarketHistory
from desk.mtm.lifecycle import LANE_BOX
from desk.reporting.style import PNL_BUCKETS

SENSITIVITY_LABEL = "SENSITIVITY — not base P&L"

# `docs/20_trade_book.md` rules S1/S2, mirrored from `desk.book.validate` so Phase 3 can re-derive a price without
# importing Phase 2's validator. `tests/test_mtm_sensitivity.py` asserts the base re-derivation reproduces every
# typed price to the rupee, which is what keeps the two copies honest.
DESK_ARB_SHARE_FRAC = 0.50
DESK_SHARE_CASES = (0.50, 0.25, 0.10, 0.00)
DESK_FIXED_MARGIN_INR_T = (5000.0, 8000.0)
PURCHASE_DISCOUNT_BAND_USD_T = (0.0, 30.0)

REPRICE_SALE = "REPRICE_SALE"          # only the sale rule moves (the parameter never touches a purchase)
REPRICE_BOTH = "REPRICE_BOTH"          # the grade factor moves both legs and the mark
REMARK_ONLY = "REMARK_ONLY"            # the published `_grade_pit` variant: marks move, typed prices do not


# ------------------------------------------------------------------------------------------------ parity refs
@dataclass(frozen=True)
class Reference:
    """The two bounds the desk's sale rule sits between, plus the purchase parity, on one date."""

    replacement_inr_t: float
    netback_inr_t: float
    cfr_usd_t: float
    fob_usd_t: float
    grade_factor: float


def reference(H: MarketHistory, d: dt.date, grade: str, lane: str) -> Reference:
    """CONTRACTS §5 on a single day, through the same `desk.mtm.curves` the engine marks with."""
    M, HV = H.state_at(d), H.view(d)
    box = LANE_BOX[lane]
    cfr = curves.lme_3m(M) * M.grade_factor_frac[grade]
    base_payload = float(HV.param(f"container_payload_mt_{box}", d))
    grade_payload = float(HV.param(f"container_payload_mt_{box}_{grade}", d))
    freight = M.freight_usd_t[lane] * base_payload / grade_payload
    return Reference(
        replacement_inr_t=curves.replacement_value(HV, M, d, grade, lane, box),
        netback_inr_t=curves.netback_inr_t(HV, M, d, grade, lane),
        cfr_usd_t=cfr, fob_usd_t=cfr - freight, grade_factor=M.grade_factor_frac[grade],
    )


def rule_sale_price(ref: Reference, share: float | None, fixed_margin_inr_t: float | None = None) -> float:
    """S1: `replacement + share x (netback - replacement)`, or a flat trading margin over replacement."""
    if fixed_margin_inr_t is not None:
        return ref.replacement_inr_t + fixed_margin_inr_t
    return ref.replacement_inr_t + float(share) * (ref.netback_inr_t - ref.replacement_inr_t)


def rule_purchase_price(ref: Reference, incoterm: bs.Incoterm, discount_usd_t: float) -> float:
    """S2: the trade-date parity on the ticket's own incoterm basis, less the desk's bid discount."""
    parity = ref.fob_usd_t if incoterm is bs.Incoterm.FOB else ref.cfr_usd_t
    return parity - discount_usd_t


# --------------------------------------------------------------------------------------------------- cases
@dataclass(frozen=True)
class Case:
    """One registered band value, and how far through the book it is allowed to reach."""

    case: str
    family: str
    param_key: str
    param_value: float
    flag: str
    mechanism: str
    share: float | None = None
    fixed_margin_inr_t: float | None = None
    purchase_discount_usd_t: float | None = None
    grade_source: str = "base"
    overrides: tuple[tuple[str, float], ...] = ()
    note: str = ""

    @property
    def is_base(self) -> bool:
        return self.case == "base"


def _fmt(v: float) -> str:
    return f"{v:+,.0f}".replace(",", "") if abs(v) >= 1 else f"{v:g}"


def registered_cases(params: Callable = register_param) -> list[Case]:
    """Every case this module runs, built from the register so the bands cannot drift from `config/params/`."""
    cases = [Case("base", "base", "—", float("nan"), "—", REPRICE_SALE, share=DESK_ARB_SHARE_FRAC,
                  note="the published book, re-derived through the same rules (must reproduce it to the rupee)")]

    for v in params("domestic_anchor_premium_sensitivity_inr_t", None):
        cases.append(Case(f"anchor_premium_{_fmt(float(v))}", "anchor_premium", "domestic_anchor_premium_inr_t",
                          float(v), "ASSUMPTION", REPRICE_SALE, share=DESK_ARB_SHARE_FRAC,
                          overrides=(("domestic_anchor_premium_inr_t", float(v)),),
                          note="the smelter netback, and therefore every typed sale price, moves with it"))
    for v in params("conversion_cost_sensitivity_inr_t_ingot", None):
        cases.append(Case(f"conversion_{int(v)}", "conversion", "conversion_cost_inr_t", float(v), "ASSUMPTION",
                          REPRICE_SALE, share=DESK_ARB_SHARE_FRAC,
                          overrides=(("conversion_cost_inr_t", float(v)),),
                          note="conversion enters the netback x recovery, so the sale rule moves with it"))
    for s in DESK_SHARE_CASES:
        cases.append(Case(f"desk_share_{s:.2f}", "desk_share", "desk_arb_share_frac (docs/20 S1)", float(s),
                          "ASSUMPTION", REPRICE_SALE, share=float(s),
                          note="how much of the modelled arbitrage the desk keeps; 0.50 is the base rule"))
    for m in DESK_FIXED_MARGIN_INR_T:
        cases.append(Case(f"desk_margin_{int(m)}", "desk_margin", "flat trading margin over replacement", float(m),
                          "ASSUMPTION", REPRICE_SALE, fixed_margin_inr_t=float(m),
                          note="a competitive import market pays a middleman a margin, not a share of the arb"))
    for dsc in PURCHASE_DISCOUNT_BAND_USD_T:
        cases.append(Case(f"purchase_discount_{int(dsc)}", "purchase_discount",
                          "purchase discount USD/t (docs/20 S2 band)", float(dsc), "ASSUMPTION", REPRICE_SALE,
                          share=DESK_ARB_SHARE_FRAC, purchase_discount_usd_t=float(dsc),
                          note="the registered band is 0-30 USD/t under parity; the book used 10-15"))
    cases.append(Case("grade_mix_pit_repriced", "grade_mix", "grade_factor_mix_pit", float("nan"), "ASSUMPTION",
                      REPRICE_BOTH, share=DESK_ARB_SHARE_FRAC, grade_source="pit",
                      note="the point-in-time mix re-prices BOTH legs and re-marks: the honest grade sensitivity"))
    cases.append(Case("grade_mix_pit_remark_only", "grade_mix", "grade_factor_mix_pit", float("nan"), "ASSUMPTION",
                      REMARK_ONLY, grade_source="pit",
                      note="the published `_grade_pit` variant: marks move, typed prices do not (zero by design)"))
    return cases


def history_for(case: Case, base: MarketHistory) -> MarketHistory:
    """A `MarketHistory` with this case's register overrides and grade source."""
    if not case.overrides and case.grade_source == "base":
        return base
    over = dict(case.overrides)

    def provider(key: str, date=None):
        return over[key] if key in over else register_param(key, date)

    return MarketHistory(panel=base.panel, grade_source=case.grade_source, params=provider)


# ------------------------------------------------------------------------------------------------- re-pricing
def reprice(book: bs.Book, base: MarketHistory, H: MarketHistory, case: Case) -> bs.Book:
    """Rebuild every ticket with its prices re-derived under `case`, holding each leg's negotiation delta."""
    if case.mechanism == REMARK_ONLY:
        return book
    return replace(book, trades=tuple(_reprice_ticket(t, base, H, case) for t in book.trades))


def _reprice_ticket(t: bs.Ticket, base: MarketHistory, H: MarketHistory, case: Case) -> bs.Ticket:
    purchase = _reprice_purchase(t, base, H, case)
    sales = tuple(_reprice_sale(t, s, base, H, case) for s in t.sales)
    return replace(t, purchase=purchase, sales=sales)


def _reprice_purchase(t: bs.Ticket, base: MarketHistory, H: MarketHistory, case: Case) -> bs.Purchase:
    p = t.purchase.pricing
    ref0 = reference(base, t.trade_date, t.grade.value, t.lane.value)
    ref1 = reference(H, t.trade_date, t.grade.value, t.lane.value)
    if p.type is bs.PurchasePricingType.FIXED:
        parity0 = ref0.fob_usd_t if t.purchase.incoterm is bs.Incoterm.FOB else ref0.cfr_usd_t
        discount = parity0 - float(p.price_usd_t)
        if case.purchase_discount_usd_t is not None:
            discount = case.purchase_discount_usd_t
        price = rule_purchase_price(ref1, t.purchase.incoterm, discount)
        return replace(t.purchase, pricing=replace(p, price_usd_t=price))
    giveaway = ref0.grade_factor - float(p.factor_frac)
    return replace(t.purchase, pricing=replace(p, factor_frac=ref1.grade_factor - giveaway))


def _reprice_sale(t: bs.Ticket, s: bs.Sale, base: MarketHistory, H: MarketHistory, case: Case) -> bs.Sale:
    if s.pricing.type is not bs.SalePricingType.FIXED:
        return s                                   # an MCX-average sale is a formula; no rule parameter reaches it
    ref0 = reference(base, s.contract_date, t.grade.value, t.lane.value)
    ref1 = reference(H, s.contract_date, t.grade.value, t.lane.value)
    delta = float(s.pricing.price_inr_t) - rule_sale_price(ref0, DESK_ARB_SHARE_FRAC)
    price = rule_sale_price(ref1, case.share, case.fixed_margin_inr_t) + delta
    return replace(s, pricing=replace(s.pricing, price_inr_t=price))


# ------------------------------------------------------------------------------------------------- the runs
def _book_row(run: engine.BookRun) -> dict:
    att = run.attribution
    bk = att[att["trade_id"] == engine.BOOK_ID]
    window = bk[bk["date"] <= WINDOW_END]
    out = {b: float(bk[b].sum()) for b in PNL_BUCKETS}
    out["cum_pnl_horizon_inr"] = float(bk["cum_pnl_inr"].iloc[-1])
    out["cum_pnl_window_end_inr"] = float(window["cum_pnl_inr"].iloc[-1]) if len(window) else float("nan")
    return out


def run_cases(book: bs.Book, base: MarketHistory, cases: Iterable[Case] | None = None,
              pit_run: engine.BookRun | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run every case and return (per-trade table, book-level summary)."""
    cases = list(cases if cases is not None else registered_cases())
    qty = {t.trade_id: t.quantity_mt for t in book.trades}
    total_mt = sum(qty.values())

    rows, summary = [], []
    base_total = None
    for c in cases:
        if c.mechanism == REMARK_ONLY and pit_run is not None:
            run = pit_run
        else:
            H = history_for(c, base)
            run = engine.run_book(reprice(book, base, H, c), H, label=c.case,
                                  with_detail=False, with_exposures=False)
        br = _book_row(run)
        if c.is_base:
            base_total = br["cum_pnl_horizon_inr"]
        att = run.attribution
        for tid in [*sorted(qty), engine.BOOK_ID]:
            sub = att[att["trade_id"] == tid]
            cum = float(sub["cum_pnl_inr"].iloc[-1])
            mt = total_mt if tid == engine.BOOK_ID else qty[tid]
            rows.append({"case": c.case, "family": c.family, "mechanism": c.mechanism, "trade_id": tid,
                         "param_key": c.param_key, "param_value": c.param_value, "flag": c.flag,
                         "cum_pnl_horizon_inr": cum, "pnl_inr_t": cum / mt if mt else float("nan"),
                         "label": SENSITIVITY_LABEL})
        summary.append({"case": c.case, "family": c.family, "mechanism": c.mechanism, "param_key": c.param_key,
                        "param_value": c.param_value, "flag": c.flag, **br,
                        "pnl_inr_t": br["cum_pnl_horizon_inr"] / total_mt,
                        "note": c.note, "label": SENSITIVITY_LABEL})

    sm = pd.DataFrame(summary)
    sm["delta_vs_base_inr"] = sm["cum_pnl_horizon_inr"] - base_total
    sm["book_pnl_positive"] = sm["cum_pnl_horizon_inr"] > 0
    per = pd.DataFrame(rows)
    per = per.merge(per[per["case"] == "base"][["trade_id", "cum_pnl_horizon_inr"]]
                    .rename(columns={"cum_pnl_horizon_inr": "_base"}), on="trade_id", how="left")
    per["delta_vs_base_inr"] = per["cum_pnl_horizon_inr"] - per["_base"]
    per = per.drop(columns=["_base"])
    cols = ["case", "family", "mechanism", "param_key", "param_value", "flag", "trade_id",
            "cum_pnl_horizon_inr", "delta_vs_base_inr", "pnl_inr_t", "label"]
    sm_cols = ["case", "family", "mechanism", "param_key", "param_value", "flag", *PNL_BUCKETS,
               "cum_pnl_window_end_inr", "cum_pnl_horizon_inr", "delta_vs_base_inr", "pnl_inr_t",
               "book_pnl_positive", "note", "label"]
    return per[cols], sm[sm_cols]


# --------------------------------------------------------------------------------- MCX roll: carry vs metal
def roll_carry(book: bs.Book, H: MarketHistory) -> pd.DataFrame:
    """Every executed roll split into the INR carry the proxy creates by construction and everything else.

    The panel MCX series is `spot x (1 + inr_rate_3m_pa x dte/365)`. Rolling a short from M1 to M2 on day `d`
    therefore earns, **by construction and with no market view**,

        carry = spot_parity(d) x inr_rate_3m_pa(d) x (dte(M2) - dte(M1)) / 365     ₹/kg

    which is INR interest on a duty-paid parity, i.e. the desk's own cost of carrying the physical seen from the
    other side. Anything left over is genuine term structure (a real curve, a real basis): identically zero on a
    PROXY day, and the reason this table is worth publishing on the mirror.
    """
    lot_mt = float(H.param("mcx_al_lot_mt"))
    lot_kg = lot_mt * units.KG_PER_MT
    rows = []
    for t in book.trades:
        by_id = {tr.hedge_id: tr for tr in t.hedges.mcx.tranches}
        for tr in t.hedges.mcx.tranches:
            if tr.exit_reason is not bs.HedgeExitReason.ROLL or not tr.roll_to:
                continue
            nxt = by_id[tr.roll_to]
            d = tr.exit_date
            M, HV = H.state_at(d), H.view(d)
            sign = 1 if tr.direction is bs.HedgeDirection.BUY else -1
            px_out = curves.mcx_price(HV, M, d, tr.contract_month)
            px_in = curves.mcx_price(HV, M, d, nxt.contract_month)
            spread = px_in - px_out                                   # a short sells the far month and buys the near
            spot_parity = M.lme_cash_usd_t * M.usdinr / units.KG_PER_MT * HV.duty_uplift(d) \
                + M.mcx_domestic_premium_inr_kg
            dte_out = max(0, (H.cal.mcx_panel_expiry(tr.contract_month) - d).days)
            dte_in = max(0, (H.cal.mcx_panel_expiry(nxt.contract_month) - d).days)
            carry = spot_parity * M.inr_rate_3m_pa * (dte_in - dte_out) / units.DAY_COUNT_INR
            qty_kg = tr.lots * lot_kg
            rows.append({
                "trade_id": t.trade_id, "roll_date": d, "roll_from": tr.hedge_id, "roll_to": nxt.hedge_id,
                "contract_from": tr.contract_month, "contract_to": nxt.contract_month,
                "direction": tr.direction.value, "lots": tr.lots, "qty_kg": qty_kg,
                "px_from_inr_kg": px_out, "px_to_inr_kg": px_in, "roll_spread_inr_kg": spread,
                "carry_inr_kg": carry, "metal_inr_kg": spread - carry,
                "roll_pnl_inr": -sign * spread * qty_kg,
                "carry_pnl_inr": -sign * carry * qty_kg,
                "metal_pnl_inr": -sign * (spread - carry) * qty_kg,
                "days_to_expiry_from": dte_out, "days_to_expiry_to": dte_in,
                "mcx_series": "MIRROR" if H.mcx_source == "mirror" else "PANEL_PROXY",
                "note": "PANEL_PROXY: M2 > M1 on every panel day by construction, so every short roll is a gain "
                        "by construction and `metal_inr_kg` is 0 — the gain is INR carry, not term structure",
            })
    return (pd.DataFrame(rows).sort_values(["roll_date", "trade_id", "roll_from"], kind="mergesort")
            .reset_index(drop=True))


# ------------------------------------------------------------------- MCX basis risk: two-sided, and unit beta
def basis_risk(base_att: pd.DataFrame, mirror_att: pd.DataFrame, base: MarketHistory,
               mirror: MarketHistory) -> pd.DataFrame:
    """The basis as a **range with a loss case**, plus an explicit test of the unit-beta hedge assumption."""
    rows = []

    def fold(att: pd.DataFrame) -> pd.DataFrame:
        """Buckets are daily flows (sum); `cum_pnl_inr` is cumulative (take the last day)."""
        g = att.sort_values("date", kind="mergesort").groupby("trade_id")
        out = g[list(PNL_BUCKETS)].sum()
        out["cum_pnl_inr"] = g["cum_pnl_inr"].last()
        return out

    b, m = fold(base_att), fold(mirror_att)
    trades = [t for t in sorted(b.index) if t != engine.BOOK_ID]

    def add(metric, scope, value, unit, flag, note):
        rows.append({"metric": metric, "scope": scope, "value": value, "unit": unit, "flag": flag,
                     "note": note, "label": SENSITIVITY_LABEL})

    for tid in trades:
        add("basis_bucket_mirror_inr", tid, float(m.loc[tid, "cross_exchange_basis"]), "inr", "PROXY",
            "bucket (b) on the mirror; 0 in every base run by construction")
        add("total_pnl_change_vs_base_inr", tid, float(m.loc[tid, "cum_pnl_inr"] - b.loc[tid, "cum_pnl_inr"]),
            "inr", "PROXY", "the whole effect of swapping the MCX series on this ticket")

    per_trade = np.array([float(m.loc[t, "cum_pnl_inr"] - b.loc[t, "cum_pnl_inr"]) for t in trades])
    worst, best = float(per_trade.min()), float(per_trade.max())
    add("per_trade_pnl_change_worst_inr", "BOOK", worst, "inr", "PROXY",
        f"the LOSS case: {trades[int(per_trade.argmin())]} on the mirror")
    add("per_trade_pnl_change_best_inr", "BOOK", best, "inr", "PROXY",
        f"the gain case: {trades[int(per_trade.argmax())]} on the mirror")
    add("per_trade_pnl_change_range_inr", "BOOK", best - worst, "inr", "PROXY",
        "read the RANGE, not the netted book total: the book total is one draw of a two-sided risk")
    add("per_trade_abs_mean_inr", "BOOK", float(np.abs(per_trade).mean()), "inr", "PROXY",
        "mean absolute per-ticket effect — the size of the basis risk the base run cannot see")
    add("book_pnl_change_vs_base_inr", "BOOK",
        float(m.loc[engine.BOOK_ID, "cum_pnl_inr"] - b.loc[engine.BOOK_ID, "cum_pnl_inr"]), "inr", "PROXY",
        "the netted book number. It is POSITIVE here; that is one realisation of a two-sided risk, not evidence "
        "that a real basis would have helped")

    beta = unit_beta_test(base, mirror)
    for k, v in beta.items():
        add(f"unit_beta_{k}", "BOOK", v["value"], v["unit"], "PROXY", v["note"])
    return pd.DataFrame(rows)


def unit_beta_test(base: MarketHistory, mirror: MarketHistory,
                   start: dt.date = WINDOW_START, end: dt.date = WINDOW_END) -> dict:
    """OLS of daily mirror-MCX changes on duty-paid-parity changes: the hedge assumes this slope is 1.

    The engine hedges by holding the MCX basis and letting LME and FX drive the MCX price, which is the same as
    assuming an MCX contract moves one-for-one with duty-paid LME parity. That is exactly a unit beta, and it is
    testable on the only observed-ish MCX series in the project.
    """
    days = [d for d in base.cal.days if start <= d <= end]
    theo = [base.mcx_theo_inr_kg(d) for d in days]
    obs = [mirror.mcx_observed_inr_kg(d) for d in days]
    x = np.diff(np.asarray(theo, float))
    y = np.diff(np.asarray(obs, float))
    n = len(x)
    xb, yb = x.mean(), y.mean()
    sxx = float(((x - xb) ** 2).sum())
    beta = float(((x - xb) * (y - yb)).sum() / sxx)
    alpha = float(yb - beta * xb)
    resid = y - (alpha + beta * x)
    dof = n - 2
    s2 = float((resid ** 2).sum() / dof)
    se = float(np.sqrt(s2 / sxx))
    r2 = float(1.0 - (resid ** 2).sum() / ((y - yb) ** 2).sum())
    return {
        "beta": {"value": beta, "unit": "frac",
                 "note": "OLS slope of daily mirror M1 changes on duty-paid-parity changes over the window; the "
                         "engine's hedge sizing assumes 1.0"},
        "beta_se": {"value": se, "unit": "frac", "note": "OLS standard error of the slope"},
        "beta_t_vs_one": {"value": (beta - 1.0) / se if se else float("nan"), "unit": "t",
                          "note": "t statistic for H0: beta = 1. |t| > ~2 rejects the unit-beta assumption the "
                                  "hedge is sized on"},
        "beta_r2": {"value": r2, "unit": "frac",
                    "note": "R^2 of that regression: how much of a day's MCX move duty-paid parity explains"},
        "beta_n_days": {"value": float(n), "unit": "count", "note": "daily changes used (window panel days)"},
        "unhedged_frac_at_beta": {"value": abs(1.0 - beta), "unit": "frac",
                                  "note": "the share of a parity move an MCX short sized at beta = 1 does NOT "
                                          "offset if the true slope is the measured beta"},
    }
