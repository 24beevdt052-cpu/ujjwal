"""`Sensitivity` — the two MASTER_SPEC Table 1.5 two-way grids, re-derived cell by cell from formulas.

Excel's own Data Tables are not used: no Python library can evaluate them, so a Data Table would be a number nobody
could check. Instead every grid row re-runs the whole CONTRACTS §5 build-up at the shocked market, exactly as
`desk.parity.model.market_shock_overrides` does:

* **(a) LME × USD/INR.** The LME shock scales 3M and cash, so CFR, the customs duty base, the finance lines and the
  Zorba by-product follow. A USD/INR *level* scales the goods forward and the CBIC notified rate by that week's
  observed ratio to spot. The MCX anchor is the duty-paid import-parity proxy, so its price net of the domestic
  premium scales with (LME ratio × FX ratio) and keeps the week's own carry factor. INR costs are held.
* **(b) Freight × BCD.** Under **CFR** the seller books freight, so a freight shock moves `freight_usd_t` and the FOB
  netback but not the buyer's margin — only the duty columns move. Under **FOB** the desk books freight and the
  CFR-equivalent cost rises one-for-one, which the grid applies as a grade-factor uplift of
  `Δfreight ÷ LME 3M`, the same construction Phase 1 uses.

The base row of each reference case is a direct reference into the `Parity` sheet, so a change on `Inputs` moves both
the base and the shocked cell and the grid stays consistent.
"""

from __future__ import annotations

import pandas as pd

from desk.excel import sources
from desk.excel.layout import KEY, Column, Sheet

SHEET = "Sensitivity"

CHAIN = ["cfr_usd_t", "freight_usd_t", "fob_usd_t", "insurance_usd_t", "cif_usd_t", "av_customs_inr_t",
         "goods_inr_t", "bcd_inr_t", "sws_inr_t", "igst_inr_t", "port_inr_t", "finance_inr_t",
         "igst_finance_inr_t", "landed_inr_t", "anchor_inr_t", "byproduct_inr_t", "net_arb_shocked_inr_t",
         "window_open_shocked", "pnl_impact_1000mt_inr"]


def _parity_index(order, week_end, grade, lane) -> int:
    for i, k in enumerate(order):
        if pd.Timestamp(k.week_end) == pd.Timestamp(week_end) and k.grade == grade and k.lane == lane:
            return i
    raise KeyError(f"no Parity row for {week_end} {grade} {lane}")


def _weekly_index(weekly, week_end) -> int:
    idx = weekly.index[weekly["week_end"] == pd.Timestamp(week_end)]
    if not len(idx):
        raise KeyError(f"no Market_Weekly row for {week_end}")
    return int(idx[0])


def write(wb, counts, data: sources.Data, parity_t, mwt):
    sh = Sheet(wb, SHEET, "Sensitivity — MASTER_SPEC Table 1.5 two-way grids on 1,000 MT, every cell a formula",
               counts,
               subtitle="P&L impact = (shocked net arb − base net arb) × 1,000 MT: the change in the parity MARGIN of "
                        "a trade whose purchase and sale both re-price. A fixed-price position is Phase 3 (MTM_Daily). "
                        "Freight levels are hindsight reconstructions (CONTRACTS §4.3).")
    order = _parity_order(data)
    refs = list(data.refs.itertuples(index=False))

    a = _grid_a(sh, data, parity_t, mwt, order, refs)
    b = _grid_b(sh, data, parity_t, mwt, order, refs)
    return {"lme_fx": a, "freight_duty": b}


def _parity_order(data: sources.Data):
    return list(data.parity_inputs[["week_end", "grade", "lane"]].itertuples(index=False))


# ------------------------------------------------------------------------------------------------ shared chain
def _chain(t, i, *, P, lme3m, usdinr, goods_fx, customs, anchor_kg, freight_base, grade_factor, bcd_rate,
           base_net_arb) -> dict:
    """The CONTRACTS §5 build-up at a shocked market. `P(col)` is the base Parity cell for the reference case."""
    R = lambda c: t.rowref(c, i)  # noqa: E731
    return {
        "cfr_usd_t": f"={lme3m}*{grade_factor}",
        "freight_usd_t": f"={freight_base}*{P('payload_scale')}",
        "fob_usd_t": f"={R('cfr_usd_t')}-{R('freight_usd_t')}",
        "insurance_usd_t": f"=insurance_rate*insured_value_uplift*{R('cfr_usd_t')}",
        "cif_usd_t": f"={R('cfr_usd_t')}+{R('insurance_usd_t')}",
        "av_customs_inr_t": f"={R('cif_usd_t')}*{customs}",
        "goods_inr_t": f"={R('cif_usd_t')}*{goods_fx}",
        "bcd_inr_t": f"={R('av_customs_inr_t')}*{bcd_rate}",
        "sws_inr_t": f"={R('bcd_inr_t')}*sws_rate_on_bcd",
        "igst_inr_t": f"=({R('av_customs_inr_t')}+{R('bcd_inr_t')}+{R('sws_inr_t')})*igst_rate_hs7602",
        "port_inr_t": f"={P('port_cf_charges_inr_t')}*{P('payload_scale')}"
                      f"+IF({P('psic_applies')},psic_cost_usd_per_box*{usdinr}"
                      f"/{P('container_payload_20ft_grade_mt')},0)",
        "finance_inr_t": f"=({R('goods_inr_t')}+{R('bcd_inr_t')}+{R('sws_inr_t')})*{P('finance_days')}"
                         f"/day_count_inr*{P('wc_rate_inr_pa')}",
        "igst_finance_inr_t": f"={R('igst_inr_t')}*igst_credit_lag_days/day_count_inr*{P('wc_rate_inr_pa')}",
        "landed_inr_t": f"={R('goods_inr_t')}+{R('bcd_inr_t')}+{R('sws_inr_t')}+{R('port_inr_t')}"
                        f"+{R('finance_inr_t')}+{R('igst_finance_inr_t')}"
                        f"+IF(igst_itc_available,0,{R('igst_inr_t')})",
        "anchor_inr_t": f"={anchor_kg}*kg_per_mt+domestic_anchor_premium_inr_t",
        "byproduct_inr_t": f"=(1-{P('moisture_frac')})*{P('heavies_frac')}*heavies_net_value_frac_of_lme_al"
                           f"*{lme3m}*{usdinr}",
        "net_arb_shocked_inr_t": f"={R('anchor_inr_t')}*{P('recovery_frac')}+{R('byproduct_inr_t')}"
                                 f"-{R('landed_inr_t')}-{P('conversion_inr_t')}",
        "window_open_shocked": f"={R('net_arb_shocked_inr_t')}>margin_threshold_inr_t",
        "pnl_impact_1000mt_inr": f"=({R('net_arb_shocked_inr_t')}-{base_net_arb})*grid_tonnes_mt",
    }


# ------------------------------------------------------------------------------------------------ grid (a)
GRID_A_KEYS = ["ref_case", "week_end", "grade", "lane", "lme_shock_pct", "usdinr_level", "usdinr_is_base"]
GRID_A_SHOCKED = ["lme_ratio", "fx_ratio", "lme_3m_shocked_usd_t", "usdinr_goods_shocked", "customs_shocked",
                  "mcx_spot_shocked_inr_kg", "mcx_carry_frac", "mcx_anchor_shocked_inr_kg", "net_arb_base_inr_t"]


def _grid_a(sh, data, parity_t, mwt, order, refs):
    sh.section("(a) LME price × USD/INR — Table 1.5(a)")
    sh.note("lme_shock_pct −30 % … +10 % step 5 %; usdinr 74 … 82 step 1, plus the week's own observed spot.")
    cols = [Column(c, KEY if c in GRID_A_KEYS else "formula",
                   width=13 if c in GRID_A_KEYS else None) for c in GRID_A_KEYS + GRID_A_SHOCKED + CHAIN]
    t = sh.table(cols)
    g = data.grid_lme_fx
    i = 0
    for ref in refs:
        pi = _parity_index(order, ref.week_end, ref.grade, ref.lane)
        wi = _weekly_index(data.weekly, ref.week_end)
        P = _parity_ref(parity_t, pi)
        MW = _weekly_ref(mwt, wi)
        sub = g[g["ref_case"] == ref.ref_case]
        for row in sub.itertuples(index=False):
            R = lambda c: t.rowref(c, i)  # noqa: E731
            vals = {
                "ref_case": ref.ref_case, "week_end": pd.Timestamp(ref.week_end).date(), "grade": ref.grade,
                "lane": ref.lane, "lme_shock_pct": float(row.lme_shock_pct),
                "usdinr_level": float(row.usdinr), "usdinr_is_base": bool(row.usdinr_is_base),
                "lme_ratio": f"=1+{R('lme_shock_pct')}/100",
                "fx_ratio": f"={R('usdinr_level')}/{P('usdinr')}",
                "lme_3m_shocked_usd_t": f"={P('lme_3m_usd_t')}*{R('lme_ratio')}",
                "usdinr_goods_shocked": f"={P('usdinr_goods')}*{R('fx_ratio')}",
                "customs_shocked": f"={P('customs_usdinr_import')}*{R('fx_ratio')}",
                "mcx_spot_shocked_inr_kg": f"=({MW('mcx_al_spot_inr_kg')}-mcx_domestic_premium_inr_kg)"
                                           f"*{R('lme_ratio')}*{R('fx_ratio')}+mcx_domestic_premium_inr_kg",
                "mcx_carry_frac": f"={P('mcx_anchor_inr_kg')}/{MW('mcx_al_spot_inr_kg')}",
                "mcx_anchor_shocked_inr_kg": f"={R('mcx_spot_shocked_inr_kg')}*{R('mcx_carry_frac')}",
                "net_arb_base_inr_t": f"={P('net_arb_inr_t')}",
            }
            vals.update(_chain(t, i, P=P, lme3m=R("lme_3m_shocked_usd_t"), usdinr=R("usdinr_level"),
                               goods_fx=R("usdinr_goods_shocked"), customs=R("customs_shocked"),
                               anchor_kg=R("mcx_anchor_shocked_inr_kg"), freight_base=P("freight_base_usd_t"),
                               grade_factor=P("grade_factor"), bcd_rate="bcd_scrap_hs7602",
                               base_net_arb=R("net_arb_base_inr_t")))
            t.write_row(i, vals)
            i += 1
    t.freeze("lme_ratio")
    t.autofilter()
    sh.after(t)
    return t


# ------------------------------------------------------------------------------------------------ grid (b)
GRID_B_KEYS = ["ref_case", "week_end", "grade", "lane", "freight_terms", "freight_shock_pct", "bcd_rate_pct"]
GRID_B_SHOCKED = ["freight_base_shocked_usd_t", "d_freight_usd_t", "grade_factor_used", "bcd_rate_used",
                  "net_arb_base_inr_t"]


def _grid_b(sh, data, parity_t, mwt, order, refs):
    sh.section("(b) Freight × import duty (BCD on HS 7602) — Table 1.5(b)")
    sh.note("freight_shock_pct −40 % … +60 % step 20 %; BCD 0 / 2.5 / 5 / 7.5 / 10 %. FOB = the desk books freight; "
            "CFR = the seller books it, so only the duty columns move.")
    cols = [Column(c, KEY if c in GRID_B_KEYS else "formula",
                   width=15 if c in GRID_B_KEYS else None) for c in GRID_B_KEYS + GRID_B_SHOCKED + CHAIN]
    t = sh.table(cols)
    g = data.grid_freight_duty
    i = 0
    for ref in refs:
        pi = _parity_index(order, ref.week_end, ref.grade, ref.lane)
        P = _parity_ref(parity_t, pi)
        sub = g[g["ref_case"] == ref.ref_case]
        for row in sub.itertuples(index=False):
            R = lambda c: t.rowref(c, i)  # noqa: E731
            vals = {
                "ref_case": ref.ref_case, "week_end": pd.Timestamp(ref.week_end).date(), "grade": ref.grade,
                "lane": ref.lane, "freight_terms": row.freight_terms,
                "freight_shock_pct": float(row.freight_shock_pct), "bcd_rate_pct": float(row.bcd_rate_pct),
                "freight_base_shocked_usd_t": f"={P('freight_base_usd_t')}*(1+{R('freight_shock_pct')}/100)",
                "d_freight_usd_t": f"={P('freight_base_usd_t')}*{P('payload_scale')}*{R('freight_shock_pct')}/100",
                "grade_factor_used": f'=IF({R("freight_terms")}="FOB_desk_books_freight",'
                                     f"{P('grade_factor')}+{R('d_freight_usd_t')}/{P('lme_3m_usd_t')},"
                                     f"{P('grade_factor')})",
                "bcd_rate_used": f"={R('bcd_rate_pct')}/100",
                "net_arb_base_inr_t": f"={P('net_arb_inr_t')}",
            }
            vals.update(_chain(t, i, P=P, lme3m=P("lme_3m_usd_t"), usdinr=P("usdinr"),
                               goods_fx=P("usdinr_goods"), customs=P("customs_usdinr_import"),
                               anchor_kg=P("mcx_anchor_inr_kg"), freight_base=R("freight_base_shocked_usd_t"),
                               grade_factor=R("grade_factor_used"), bcd_rate=R("bcd_rate_used"),
                               base_net_arb=R("net_arb_base_inr_t")))
            t.write_row(i, vals)
            i += 1
    t.freeze("freight_base_shocked_usd_t")
    t.autofilter()
    sh.after(t)
    return t


def _parity_ref(parity_t, i: int):
    return lambda c: f"{parity_t.sheet.name}!${parity_t.col(c)}${parity_t.first_row + i}"


def _weekly_ref(mwt, i: int):
    return lambda c: f"{mwt.sheet.name}!${mwt.col(c)}${mwt.first_row + i}"
