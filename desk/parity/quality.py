"""Scrap reality check (Table 3 row 1.6): SPA moisture franchise, contamination discount / rejection, and recovery.

Why this exists. The parity values a tonne of scrap by the aluminium ingot it yields (``recovery_frac``) and pays for
it by invoice weight. Wet or dirty cargo breaks that link twice: it yields less metal per tonne AND the desk may have
paid for water and dirt. The SPA template (commercial.yaml ``rejection_penalty_schedule``) claws some of that back —
weight deduction above the moisture franchise, a punitive price discount on excess contamination, rejection beyond a
limit. These functions implement that schedule once so Phase 2 (trade terms) and Phase 3 (penalty accruals, attribution
factor f) use the same numbers, and the scenario table shows what survives the clauses.

Settlement conventions (desk SPA, ASSUMPTION):
* The contracted contamination limit is the grade's registered ``contamination_frac_<grade>`` — the composition the
  grade factor and the recovery already price — so the base case settles with no adjustment.
* Moisture: payable weight = contracted × (1 − ``spa_moisture_deduction_ratio`` × max(0, moisture − franchise)).
* Contamination excess ≤ ``spa_contamination_rejection_excess_frac``: price discount
  ``spa_contamination_discount_multiple`` × excess on the whole (payable) lot. Above it — or any radioactivity finding —
  the lot is rejectable; the as-if-accepted discount is still reported as the renegotiation reference.
* Extra contamination is non-metallic (the Zorba heavies fraction is unchanged), and extra moisture is water.
* Per-tonne costs that follow boxes (port, PSIC, ocean freight inside CFR paid by the seller) do not fall with the
  weight deduction; value-based costs (goods, duties, finance) scale with the invoice value.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from desk import config
from desk.parity import model

MOISTURE_SCENARIOS_FRAC = (0.02, 0.03, 0.05)                    # plus each grade's base and the SPA franchise
CONTAMINATION_EXCESS_SCENARIOS_FRAC = (0.0, 0.01, 0.02, 0.03, 0.05)
SCENARIO_TONNES_MT = 1000.0


@dataclass(frozen=True)
class Settlement:
    grade: str
    contracted_mt: float
    moisture_actual_frac: float
    contamination_actual_frac: float
    moisture_franchise_frac: float
    moisture_excess_frac: float
    weight_deduction_mt: float
    payable_mt: float
    contamination_limit_frac: float
    contamination_excess_frac: float
    discount_frac: float
    penalty_usd: float
    rejectable: bool
    mandatory_rejection: bool
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def recovery_frac(moisture: float, contamination: float, metal_yield: float):
    """CONTRACTS §5: aluminium ingot per MT of scrap as received."""
    return (1.0 - moisture) * (1.0 - contamination) * metal_yield


def settle_weight_and_penalty(grade: str, contracted_mt: float, moisture_actual: float, contamination_actual: float,
                              price_usd_t: float = 0.0, radioactive: bool = False) -> Settlement:
    """Apply the desk SPA quality schedule to one lot.

    ``price_usd_t`` is the contract price per payable MT (e.g. CFR); ``penalty_usd`` is the discount credited to the
    buyer on the payable weight (0 when no price is given). Weight deduction is reported separately in MT.
    """
    if grade not in model.GRADES:
        raise KeyError(f"unknown grade {grade!r}")
    franchise = float(config.value("standard_moisture_franchise_frac"))
    ratio = float(config.value("spa_moisture_deduction_ratio"))
    limit = float(config.value(f"contamination_frac_{grade}"))
    multiple = float(config.value("spa_contamination_discount_multiple"))
    reject_at = float(config.value("spa_contamination_rejection_excess_frac"))

    m_excess = max(0.0, moisture_actual - franchise)
    deduction = contracted_mt * ratio * m_excess
    payable = contracted_mt - deduction
    c_excess = max(0.0, contamination_actual - limit)
    discount = multiple * c_excess
    rejectable = radioactive or c_excess > reject_at + 1e-12
    reasons = []
    if m_excess > 0:
        reasons.append(f"moisture {m_excess:.2%} above franchise → weight deduction")
    if c_excess > 0:
        reasons.append(f"contamination {c_excess:.2%} above limit → {discount:.2%} price discount")
    if c_excess > reject_at + 1e-12:
        reasons.append("contamination excess above rejection threshold → lot rejectable")
    if radioactive:
        reasons.append("radioactivity finding → mandatory rejection, all costs for seller")
    return Settlement(
        grade=grade, contracted_mt=contracted_mt, moisture_actual_frac=moisture_actual,
        contamination_actual_frac=contamination_actual, moisture_franchise_frac=franchise,
        moisture_excess_frac=m_excess, weight_deduction_mt=deduction,
        payable_mt=0.0 if radioactive else payable, contamination_limit_frac=limit, contamination_excess_frac=c_excess,
        discount_frac=discount, penalty_usd=0.0 if radioactive else discount * price_usd_t * payable,
        rejectable=rejectable, mandatory_rejection=radioactive, reason="; ".join(reasons) or "within specification",
    )


def quality_adjusted(row: pd.Series, moisture: float, contamination: float, metal_yield: float,
                     spa_protection: bool = True) -> dict:
    """Re-value one parity row (inputs + §5 line items, e.g. ``model.parity_row``) per contracted MT of scrap."""
    grade = str(row["grade"])
    if spa_protection:
        s = settle_weight_and_penalty(grade, 1.0, moisture, contamination)
        value_factor = s.payable_mt * (1.0 - s.discount_frac)
    else:
        s = None
        value_factor = 1.0
    itc = bool(row["igst_itc_available"])
    value_costs = (row["goods_inr_t"] + row["bcd_inr_t"] + row["sws_inr_t"] + row["finance_inr_t"]
                   + row["igst_finance_inr_t"] + (0.0 if itc else row["igst_inr_t"]))
    landed = value_costs * value_factor + row["port_inr_t"]
    rec = recovery_frac(moisture, contamination, metal_yield)
    byproduct = ((1.0 - moisture) * row["heavies_frac"] * row["heavies_net_value_frac_of_lme_al"]
                 * row["lme_3m_usd_t"] * row["usdinr"])
    net = row["anchor_inr_t"] * rec + byproduct - landed - row["conversion_cost_inr_t"] * rec
    return {"recovery_frac": rec, "value_factor_frac": value_factor, "landed_inr_t": landed,
            "landed_per_t_recovered_inr_t": landed / rec, "byproduct_inr_t": byproduct, "net_arb_inr_t": net,
            "settlement": s}


def scenario_table(week_end, lane: str, inputs: pd.DataFrame | None = None) -> pd.DataFrame:
    """grade × moisture × contamination × yield → recovery, landed per t recovered, net-arb impact (reference week)."""
    inputs = model.build_inputs() if inputs is None else inputs
    franchise = float(config.value("standard_moisture_franchise_frac"))
    rows = []
    for grade in model.GRADES:
        row = model.parity_row(week_end, grade, lane, inputs=inputs)
        base_m, base_c, base_y = (float(config.value(f"moisture_frac_{grade}")),
                                  float(config.value(f"contamination_frac_{grade}")),
                                  float(config.value(f"metal_yield_frac_{grade}")))
        y_lo, y_hi = (float(v) for v in config.value(f"metal_yield_sensitivity_frac_{grade}"))
        moistures = sorted({round(v, 6) for v in (base_m, franchise, *MOISTURE_SCENARIOS_FRAC)})
        contams = [round(base_c + e, 6) for e in CONTAMINATION_EXCESS_SCENARIOS_FRAC]
        base_net = float(row["net_arb_inr_t"])
        for m in moistures:
            for c in contams:
                for y_label, y in (("low", y_lo), ("base", base_y), ("high", y_hi)):
                    q = quality_adjusted(row, m, c, y)
                    raw = quality_adjusted(row, m, c, y, spa_protection=False)
                    s: Settlement = q["settlement"]
                    outcome = ("REJECTABLE" if s.rejectable else
                               "ACCEPT_ADJUSTED" if (s.moisture_excess_frac > 0 or s.contamination_excess_frac > 0)
                               else "ACCEPT")
                    rows.append({
                        "week_end": pd.Timestamp(week_end), "lane": lane, "grade": grade,
                        "moisture_frac": m, "contamination_frac": c, "metal_yield_case": y_label,
                        "metal_yield_frac": y, "is_base_quality": bool(m == base_m and c == base_c and y == base_y),
                        "moisture_excess_frac": s.moisture_excess_frac, "payable_frac": s.payable_mt,
                        "contamination_excess_frac": s.contamination_excess_frac, "discount_frac": s.discount_frac,
                        "outcome": outcome, "recovery_frac": q["recovery_frac"], "landed_inr_t": q["landed_inr_t"],
                        "landed_per_t_recovered_inr_t": q["landed_per_t_recovered_inr_t"],
                        "net_arb_base_inr_t": base_net, "net_arb_inr_t": q["net_arb_inr_t"],
                        "net_arb_impact_inr_t": q["net_arb_inr_t"] - base_net,
                        "net_arb_impact_1000mt_inr": (q["net_arb_inr_t"] - base_net) * SCENARIO_TONNES_MT,
                        "net_arb_no_spa_clauses_inr_t": raw["net_arb_inr_t"],
                        "spa_clause_value_inr_t": q["net_arb_inr_t"] - raw["net_arb_inr_t"],
                        "window_open": bool(q["net_arb_inr_t"] > float(row["margin_threshold_inr_t"])),
                    })
    return pd.DataFrame(rows)
