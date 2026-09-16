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
from desk.mtm.history import GRADES, MarketHistory
from desk.mtm.lifecycle import LANE_BOX
from desk.reporting.style import PNL_BUCKETS

SENSITIVITY_LABEL = "SENSITIVITY — not base P&L"
GRADES_FOR_SENSITIVITY = GRADES

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
EVENT_CASE = "EVENT_CASE"              # a SIM operational-event magnitude moves; no price is re-derived
CLAIM_RECOVERY_CASES = (0.0, 1.0)      # around the 0.6 both quality events type (docs/20 §7)


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
    claim_recovery_frac: float | None = None
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
    for src in ("lag1", "lag3"):
        cases.append(Case(f"grade_mix_{src}_repriced", "grade_mix", f"grade_factor_mix_{src}", float("nan"),
                          "PROXY", REPRICE_BOTH, share=DESK_ARB_SHARE_FRAC, grade_source=src,
                          note=f"the {src} published mix variant (as hindsight as the base lag-2) re-prices both legs "
                               "and re-marks: how much the headline depends on WHICH reconstruction was used"))
    # The grade DIFFERENTIAL is the other half of the reconstruction: the lag-2 mix sets the shape, a 2024-25
    # differential applied to 2022 sets the level. Its evidence quartiles are registered (parity.yaml); P1 already
    # screens on them, and here they re-price both legs (review finding, trader lens: "±1 IQR on grade_factor_diff").
    for q, label in ((0, "q25"), (1, "q75")):
        over = tuple((f"grade_factor_diff_{g}", float(params(f"grade_factor_diff_quartiles_{g}", None)[q]))
                     for g in GRADES_FOR_SENSITIVITY)
        cases.append(Case(f"grade_diff_{label}_repriced", "grade_diff", f"grade_factor_diff_quartiles_<g> [{label}]",
                          float("nan"), "ASSUMPTION", REPRICE_BOTH, share=DESK_ARB_SHARE_FRAC, grade_source="lag2",
                          overrides=over,
                          note=f"every grade differential at its evidence {label} on the lag-2 mix; re-prices both legs "
                               "and re-marks"))
    for r in CLAIM_RECOVERY_CASES:
        cases.append(Case(f"claim_recovery_{r:.2f}", "claim_recovery", "events.quality.claim_recovery_frac (SIM)",
                          float(r), "SIM", EVENT_CASE, claim_recovery_frac=float(r),
                          note="both quality events at this recovery instead of the typed 0.6; no price moves"))
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
    if case.mechanism == EVENT_CASE:
        return replace(book, trades=tuple(_with_claim_recovery(t, case.claim_recovery_frac) for t in book.trades))
    return replace(book, trades=tuple(_reprice_ticket(t, base, H, case) for t in book.trades))


def _with_claim_recovery(t: bs.Ticket, recovery: float | None) -> bs.Ticket:
    if recovery is None or not t.events.quality:
        return t
    quality = tuple(replace(q, claim_recovery_frac=recovery) for q in t.events.quality)
    return replace(t, events=replace(t.events, quality=quality))


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
    ref0 = reference(base, s.contract_date, t.grade.value, t.lane.value)
    ref1 = reference(H, s.contract_date, t.grade.value, t.lane.value)
    shift = rule_sale_price(ref1, case.share, case.fixed_margin_inr_t) - rule_sale_price(ref0, DESK_ARB_SHARE_FRAC)
    if s.pricing.type is bs.SalePricingType.FIXED:
        return replace(s, pricing=replace(s.pricing, price_inr_t=float(s.pricing.price_inr_t) + shift))
    # An MCX-average sale is a formula, but its PREMIUM is not: every one in this book was struck so that
    # `factor x MCX + premium` equals the same half-the-gap rule on the contract date (T02, T05, T08 terms notes).
    # The first version of this module held those premiums fixed, which silently exempted 4,980 MT — a third of
    # the book — from every sale-rule case and overstated the bottom of the anchor-premium band by ~₹10 crore
    # (Phase 1-3 review follow-up). The premium now moves by exactly what the rule price moves.
    return replace(s, pricing=replace(s.pricing, premium_inr_t=float(s.pricing.premium_inr_t) + shift))


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


# ------------------------------------------------------------------------------- sign robustness, per band
NUMERIC_FAMILIES = ("anchor_premium", "conversion", "desk_share", "desk_margin", "purchase_discount",
                    "claim_recovery")


def sign_robustness(summary: pd.DataFrame, book: bs.Book, params: Callable = register_param) -> pd.DataFrame:
    """One row per registered band: the P&L range across it, and whether the book's SIGN survives the whole band.

    For a numeric band the book P&L is (to float noise) linear in the parameter — the sale rule is linear in the
    netback and the netback is linear in the premium and the conversion cost — so the table also publishes the
    slope and the **break-even value**: the parameter value at which the re-priced book makes exactly zero. A
    break-even inside the registered band is the plain statement that the headline is not sign-robust to that
    assumption. `linear_max_dev_inr` is the evidence for the linearity claim, not an assumption of it.
    """
    base_pnl = float(summary.loc[summary["case"] == "base", "cum_pnl_horizon_inr"].iloc[0])
    recoveries = sorted({float(q.claim_recovery_frac) for t in book.trades for q in t.events.quality})
    base_values = {"anchor_premium": float(params("domestic_anchor_premium_inr_t", None)),
                   "conversion": float(params("conversion_cost_inr_t", None)),
                   "desk_share": DESK_ARB_SHARE_FRAC,
                   "claim_recovery": recoveries[0] if len(recoveries) == 1 else None}
    rows = []
    priced = summary[summary["mechanism"] != REMARK_ONLY]
    for fam, g in priced[priced["family"] != "base"].groupby("family", sort=False):
        pnl = g["cum_pnl_horizon_inr"].to_numpy(float)
        row = {"family": fam, "param_key": g["param_key"].iloc[0], "flag": g["flag"].iloc[0], "n_cases": len(g),
               "cases": "; ".join(g["case"]), "pnl_min_inr": float(pnl.min()), "pnl_max_inr": float(pnl.max()),
               "base_pnl_inr": base_pnl, "base_value": float("nan"), "band_min_value": float("nan"),
               "band_max_value": float("nan"), "slope_inr_per_unit": float("nan"),
               "linear_max_dev_inr": float("nan"), "breakeven_value": float("nan"),
               "breakeven_inside_band": False}
        if fam in NUMERIC_FAMILIES:
            x = g["param_value"].to_numpy(float)
            y = pnl
            bv = base_values.get(fam)
            if bv is not None and not np.any(np.isclose(x, bv)):
                x, y = np.append(x, bv), np.append(y, base_pnl)
            row.update(base_value=float("nan") if bv is None else bv,
                       band_min_value=float(x.min()), band_max_value=float(x.max()))
            if len(np.unique(x)) >= 2:
                slope, icpt = np.polyfit(x, y, 1)
                row["slope_inr_per_unit"] = float(slope)
                row["linear_max_dev_inr"] = float(np.abs(y - (slope * x + icpt)).max())
                if abs(slope) > 1e-9:
                    be = float(-icpt / slope)
                    row["breakeven_value"] = be
                    row["breakeven_inside_band"] = bool(x.min() <= be <= x.max())
        row["sign_robust_within_band"] = bool((pnl > 0).all() and base_pnl > 0)
        row["label"] = SENSITIVITY_LABEL
        rows.append(row)
    allp = priced["cum_pnl_horizon_inr"].to_numpy(float)
    rows.append({"family": "ALL_REGISTERED_BANDS", "param_key": "every case above, one at a time", "flag": "—",
                 "n_cases": len(priced), "cases": "one parameter moved per case; no joint scenario",
                 "pnl_min_inr": float(allp.min()), "pnl_max_inr": float(allp.max()), "base_pnl_inr": base_pnl,
                 "base_value": float("nan"), "band_min_value": float("nan"), "band_max_value": float("nan"),
                 "slope_inr_per_unit": float("nan"), "linear_max_dev_inr": float("nan"),
                 "breakeven_value": float("nan"), "breakeven_inside_band": bool((allp <= 0).any()),
                 "sign_robust_within_band": bool((allp > 0).all()), "label": SENSITIVITY_LABEL})
    cols = ["family", "param_key", "flag", "n_cases", "cases", "base_value", "band_min_value", "band_max_value",
            "base_pnl_inr", "pnl_min_inr", "pnl_max_inr", "slope_inr_per_unit", "linear_max_dev_inr",
            "breakeven_value", "breakeven_inside_band", "sign_robust_within_band", "label"]
    return pd.DataFrame(rows)[cols]


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
            # What the same roll would have been on a duty-paid parity curve that carried the LME's OWN term
            # structure and a CIP rupee forward, built from the engine's primitives (linear cash->3M, `fx_x`):
            #   F(T) = cash_fwd(T) x fx_x(T) / 1000 x uplift + domestic premium.
            # Its roll spread splits into rupee-vs-dollar rate carry (the forward points) and METAL carry (the LME
            # cash-3M slope at the forward rate). In backwardation the metal carry is negative: a short roll pays.
            exp_out, exp_in = H.cal.mcx_panel_expiry(tr.contract_month), H.cal.mcx_panel_expiry(nxt.contract_month)
            uplift = HV.duty_uplift(d)

            def lme_curve_px(expiry):
                s_ = max(expiry, d)
                return (curves.cash_fwd(M, H.cal, d, s_) * curves.fx_x(HV, M, d, s_) / units.KG_PER_MT * uplift
                        + M.mcx_domestic_premium_inr_kg)

            spread_lme = lme_curve_px(exp_in) - lme_curve_px(exp_out)
            fx_points = (M.lme_cash_usd_t / units.KG_PER_MT * uplift
                         * (curves.fx_x(HV, M, d, max(exp_in, d)) - curves.fx_x(HV, M, d, max(exp_out, d))))
            metal_carry = spread_lme - fx_points
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
                "lme_curve_roll_spread_inr_kg": spread_lme,
                "lme_curve_rate_carry_inr_kg": fx_points,
                "lme_curve_metal_carry_inr_kg": metal_carry,
                "lme_curve_roll_pnl_inr": -sign * spread_lme * qty_kg,
                "lme_curve_metal_carry_pnl_inr": -sign * metal_carry * qty_kg,
                "proxy_minus_lme_curve_roll_pnl_inr": -sign * (spread - spread_lme) * qty_kg,
                # The DIRECT LME curve on the same day, shown beside the proxy's roll so the contradiction is on the
                # page: a positive cash-3M spread is backwardation, where a real short roll would have PAID.
                "lme_cash_3m_spread_usd_t": float(getattr(H.row(d), "lme_cash_3m_spread_usd_t")),
                "lme_backwardation": bool(float(getattr(H.row(d), "lme_cash_3m_spread_usd_t")) > 0),
                "mcx_series": "MIRROR" if H.mcx_source == "mirror" else "PANEL_PROXY",
                "note": ("PANEL_PROXY: M2 > M1 on every panel day by construction, so every short roll is a gain "
                         "by construction and `metal_inr_kg` is 0 — the gain is INR carry, not term structure. "
                         "The lme_curve_* columns re-price the same roll on a parity curve carrying the LME's own "
                         "cash-3M slope and CIP rupee points: a SENSITIVITY, not base P&L"
                         if H.mcx_source != "mirror" else
                         "MIRROR: `metal_inr_kg` is the mirror's term structure net of the proxy's INR carry; the "
                         "lme_curve_* columns are the parity-with-LME-curve reference, identical to the base file"),
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
    book_change = float(m.loc[engine.BOOK_ID, "cum_pnl_inr"] - b.loc[engine.BOOK_ID, "cum_pnl_inr"])
    add("book_pnl_change_vs_base_inr", "BOOK", book_change, "inr", "PROXY",
        "the netted book number. It is POSITIVE here; that is one realisation of a two-sided risk, not evidence "
        "that a real basis would have helped")
    add("book_pnl_change_adverse_image_inr", "BOOK", -abs(book_change), "inr", "PROXY",
        "the same basis path with its sign reversed: nothing in one six-month mirror makes the favourable draw more "
        "likely than its mirror image, so the book-level basis risk is quoted as +/- this number, not as a gain")
    add("sum_of_losing_tickets_inr", "BOOK", float(per_trade[per_trade < 0].sum()), "inr", "PROXY",
        "the tickets that lost on the mirror, summed without the winners that happened to net them out")

    # (b) and (g) move TOGETHER when the MCX series is swapped: the mirror's different curve shape moves the executed
    # roll spreads (g) as well as the basis (b), and the review found the (g) move was larger. Read them jointly.
    bg = [(float(m.loc[t, "cross_exchange_basis"] + m.loc[t, "roll_term_structure"]
                 - b.loc[t, "cross_exchange_basis"] - b.loc[t, "roll_term_structure"])) for t in trades]
    for tid, v in zip(trades, bg):
        add("basis_plus_roll_change_vs_base_inr", tid, v, "inr", "PROXY",
            "(b) + (g) on the mirror minus (b) + (g) in the base run")
    bg_arr = np.asarray(bg)
    add("basis_plus_roll_change_worst_ticket_inr", "BOOK", float(bg_arr.min()), "inr", "PROXY",
        "(b)+(g) jointly: the worst ticket")
    add("basis_plus_roll_change_best_ticket_inr", "BOOK", float(bg_arr.max()), "inr", "PROXY",
        "(b)+(g) jointly: the best ticket")
    bg_book = float(m.loc[engine.BOOK_ID, "cross_exchange_basis"] + m.loc[engine.BOOK_ID, "roll_term_structure"]
                    - b.loc[engine.BOOK_ID, "cross_exchange_basis"] - b.loc[engine.BOOK_ID, "roll_term_structure"])
    add("basis_plus_roll_change_book_two_sided_inr", "BOOK", abs(bg_book), "inr", "PROXY",
        "(b)+(g) jointly at book level, quoted as a +/- band: the mirror moved them by this much in the desk's favour, "
        "and a curve that went the other way moves them by as much against it")

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
