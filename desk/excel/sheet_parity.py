"""`Parity` — CONTRACTS §5 line by line, as live Excel formulas, one row per week × grade × lane.

This is Component 1 in the workbook. Not a single computed value is pasted: every line item is an Excel formula
reading `Inputs` (register parameters, by named range or by a key the formula builds) and `Market_Weekly` (the panel
values on the week's value date). Change `bcd_scrap_hs7602` on `Inputs`, or an LME print on `Market_Daily`, and all
258 rows re-price.

The three CONTRACTS §5a flags are formulas too. Two of them are written as *exact algebraic shortcuts* rather than as
a second full re-derivation of the whole build-up, and the Checks sheet proves both against Python row by row:

* **conversion one grid step above base** changes only `conversion_inr_t`, which is `conversion_cost × recovery`, so
  `net_arb_conv18k = net_arb − (conv_step_5a − conversion_cost_inr_t) × recovery_frac`;
* **the point-in-time grade mix** changes only the grade factor, and every term of `landed_inr_t` except `port_inr_t`
  is proportional to `cfr_usd_t` (goods, duty, SWS, the two finance lines and the IGST term all scale with CIF), so
  `net_arb_pit_mix = net_arb − (landed_inr_t − port_inr_t) × (grade_factor_pit / grade_factor − 1)`.

Both identities are exact, not approximations; writing them this way keeps the sheet readable and the workbook small
enough to be recalculated in a test.
"""

from __future__ import annotations

import pandas as pd

from desk.excel import expr, sources
from desk.excel.layout import KEY, Column, Sheet

SHEET = "Parity"

MARKET_COLS = ["lme_3m_usd_t", "lme_cash_usd_t", "usdinr", "usdinr_goods", "customs_usdinr_import",
               "customs_fx_src", "freight_base_usd_t", "mcx_contract", "mcx_anchor_inr_kg", "wc_rate_inr_pa",
               "grade_factor", "grade_factor_mix_pit"]
PARAM_COLS = ["box", "port_key", "lane_key", "container_payload_base_mt", "container_payload_grade_mt",
              "container_payload_20ft_grade_mt", "port_cf_charges_inr_t", "psic_applies", "finance_days",
              "moisture_frac", "contamination_frac", "metal_yield_frac", "heavies_frac", "grade_factor_diff"]
LINE_ITEMS = ["cfr_usd_t", "payload_scale", "freight_usd_t", "fob_usd_t", "insurance_usd_t", "cif_usd_t",
              "av_customs_inr_t", "goods_inr_t", "bcd_inr_t", "sws_inr_t", "igst_inr_t", "port_inr_t",
              "finance_inr_t", "igst_finance_inr_t", "landed_inr_t", "recovery_frac", "anchor_inr_t",
              "byproduct_inr_t", "conversion_inr_t", "net_arb_inr_t", "net_arb_usd_t", "window_open"]
CASE_COLS = ["grade_factor_pit", "landed_ex_port_inr_t", "net_arb_pit_mix_inr_t", "net_arb_conv18k_inr_t",
             "open_base", "open_pit_mix", "open_conv18k", "trade_eligible", "trade_eligible_n"]


def write(wb, counts, data: sources.Data, mwt):
    sh = Sheet(wb, SHEET, "Parity — CONTRACTS §5 per MT of scrap, every line item a live formula", counts,
               subtitle="Rows: 43 W-FRI weeks × 3 grades × 2 lanes. Inputs come from the Inputs sheet (named ranges "
                        "and key look-ups) and Market_Weekly. Goods are paid at usdinr_fwd_1m "
                        "(register key parity_goods_fx_basis); the customs notified rate sets the duty base only.")
    cols = [Column("week_end", KEY, width=12), Column("value_date", KEY, width=12),
            Column("grade", KEY, width=13), Column("lane", KEY, width=11), Column("in_window", KEY, width=10)]
    cols += [Column(c) for c in MARKET_COLS + PARAM_COLS + LINE_ITEMS + CASE_COLS]
    t = sh.table(cols)

    keyed = data.parity_inputs[["week_end", "grade", "lane"]].copy()  # canonical row order (week → grade → lane)
    order = list(keyed.itertuples(index=False))
    pw = data.parity.set_index(["week_end", "grade", "lane"])

    gf_block = mwt.abs_block("grade_factor_zorba", "grade_factor_tense")
    gf_head = mwt.header_abs("grade_factor_zorba", "grade_factor_tense")

    for i, key in enumerate(order):
        we, grade, lane = pd.Timestamp(key.week_end), key.grade, key.lane
        src = pw.loc[(we, grade, lane)]
        R = lambda c: t.rowref(c, i)  # noqa: E731
        wk = R("week_end")
        mw = lambda c: (f"INDEX({mwt.abs(c)},MATCH({wk},{mwt.abs('week_end')},0))")  # noqa: E731
        r = {
            "week_end": we.date(), "value_date": pd.Timestamp(src["value_date"]).date(),
            "grade": grade, "lane": lane, "in_window": bool(src["in_window"]),
            # ---- market
            "lme_3m_usd_t": "=" + mw("lme_3m_usd_t"),
            "lme_cash_usd_t": "=" + mw("lme_cash_usd_t"),
            "usdinr": "=" + mw("usdinr"),
            "usdinr_goods": "=" + mw("usdinr_fwd_1m"),
            "customs_usdinr_import": "=" + mw("customs_usdinr_import"),
            "customs_fx_src": "=" + mw("customs_fx_src"),
            "freight_base_usd_t": f'=IF({R("lane")}="JEA_NSA",{mw("freight_jea_nsa_usd_t")},'
                                  f'{mw("freight_usec_mun_usd_t")})',
            "mcx_contract": f'=IF({R("lane")}="JEA_NSA","M1","M2")',
            "mcx_anchor_inr_kg": f'=IF({R("lane")}="JEA_NSA",{mw("mcx_al_m1_inr_kg")},{mw("mcx_al_m2_inr_kg")})',
            "wc_rate_inr_pa": "=" + mw("wc_rate_inr_pa"),
            "grade_factor": f'=INDEX({gf_block},MATCH({wk},{mwt.abs("week_end")},0),'
                            f'MATCH("grade_factor_"&{R("grade")},{gf_head},0))',
            "grade_factor_mix_pit": "=" + mw("grade_factor_mix_pit"),
            # ---- parameters resolved from the row's grade and lane
            "box": f'={expr.box_of(R("lane"))}',
            "port_key": f'={expr.port_of(R("lane"))}',
            "lane_key": f'=IF({R("lane")}="JEA_NSA","jea_nsa","usec_mun")',
            "container_payload_base_mt": "=" + expr.param('"container_payload_mt_"&' + R("box")),
            "container_payload_grade_mt":
                "=" + expr.param('"container_payload_mt_"&' + R("box") + '&"_"&' + R("grade")),
            "container_payload_20ft_grade_mt":
                "=" + expr.param('"container_payload_mt_20ft_"&' + R("grade")),
            "port_cf_charges_inr_t": "=" + expr.param('"port_cf_charges_inr_t_"&' + R("port_key")),
            "psic_applies": "=" + expr.param(expr.psic_key_of(R("lane"))),
            "finance_days": "=" + expr.param('"finance_days_"&' + R("lane_key")),
            "moisture_frac": "=" + expr.param('"moisture_frac_"&' + R("grade")),
            "contamination_frac": "=" + expr.param('"contamination_frac_"&' + R("grade")),
            "metal_yield_frac": "=" + expr.param('"metal_yield_frac_"&' + R("grade")),
            "heavies_frac": "=" + expr.param('"heavies_frac_"&' + R("grade")),
            "grade_factor_diff": "=" + expr.param('"grade_factor_diff_"&' + R("grade")),
            # ---- CONTRACTS §5, line by line
            "cfr_usd_t": f'={R("lme_3m_usd_t")}*{R("grade_factor")}',
            "payload_scale": f'={R("container_payload_base_mt")}/{R("container_payload_grade_mt")}',
            "freight_usd_t": f'={R("freight_base_usd_t")}*{R("payload_scale")}',
            "fob_usd_t": f'={R("cfr_usd_t")}-{R("freight_usd_t")}',
            "insurance_usd_t": f'=insurance_rate*insured_value_uplift*{R("cfr_usd_t")}',
            "cif_usd_t": f'={R("cfr_usd_t")}+{R("insurance_usd_t")}',
            "av_customs_inr_t": f'={R("cif_usd_t")}*{R("customs_usdinr_import")}',
            "goods_inr_t": f'={R("cif_usd_t")}*{R("usdinr_goods")}',
            "bcd_inr_t": f'={R("av_customs_inr_t")}*bcd_scrap_hs7602',
            "sws_inr_t": f'={R("bcd_inr_t")}*sws_rate_on_bcd',
            "igst_inr_t": f'=({R("av_customs_inr_t")}+{R("bcd_inr_t")}+{R("sws_inr_t")})*igst_rate_hs7602',
            "port_inr_t": f'={R("port_cf_charges_inr_t")}*{R("payload_scale")}'
                          f'+IF({R("psic_applies")},psic_cost_usd_per_box*{R("usdinr")}'
                          f'/{R("container_payload_20ft_grade_mt")},0)',
            "finance_inr_t": f'=({R("goods_inr_t")}+{R("bcd_inr_t")}+{R("sws_inr_t")})*{R("finance_days")}'
                             f'/day_count_inr*{R("wc_rate_inr_pa")}',
            "igst_finance_inr_t": f'={R("igst_inr_t")}*igst_credit_lag_days/day_count_inr*{R("wc_rate_inr_pa")}',
            "landed_inr_t": f'={R("goods_inr_t")}+{R("bcd_inr_t")}+{R("sws_inr_t")}+{R("port_inr_t")}'
                            f'+{R("finance_inr_t")}+{R("igst_finance_inr_t")}'
                            f'+IF(igst_itc_available,0,{R("igst_inr_t")})',
            "recovery_frac": f'=(1-{R("moisture_frac")})*(1-{R("contamination_frac")})*{R("metal_yield_frac")}',
            "anchor_inr_t": f'={R("mcx_anchor_inr_kg")}*kg_per_mt+domestic_anchor_premium_inr_t',
            "byproduct_inr_t": f'=(1-{R("moisture_frac")})*{R("heavies_frac")}*heavies_net_value_frac_of_lme_al'
                               f'*{R("lme_3m_usd_t")}*{R("usdinr")}',
            "conversion_inr_t": f'=conversion_cost_inr_t*{R("recovery_frac")}',
            "net_arb_inr_t": f'={R("anchor_inr_t")}*{R("recovery_frac")}+{R("byproduct_inr_t")}'
                             f'-{R("landed_inr_t")}-{R("conversion_inr_t")}',
            "net_arb_usd_t": f'={R("net_arb_inr_t")}/{R("usdinr")}',
            "window_open": f'={R("net_arb_inr_t")}>margin_threshold_inr_t',
            # ---- CONTRACTS §5a (exact algebraic shortcuts, proved on the Checks sheet)
            "grade_factor_pit": f'={R("grade_factor_mix_pit")}+{R("grade_factor_diff")}',
            "landed_ex_port_inr_t": f'={R("landed_inr_t")}-{R("port_inr_t")}',
            "net_arb_pit_mix_inr_t": f'={R("net_arb_inr_t")}-{R("landed_ex_port_inr_t")}'
                                     f'*({R("grade_factor_pit")}/{R("grade_factor")}-1)',
            "net_arb_conv18k_inr_t": f'={R("net_arb_inr_t")}-(conv_step_5a-conversion_cost_inr_t)'
                                     f'*{R("recovery_frac")}',
            "open_base": f'={R("window_open")}',
            "open_pit_mix": f'={R("net_arb_pit_mix_inr_t")}>margin_threshold_inr_t',
            "open_conv18k": f'={R("net_arb_conv18k_inr_t")}>margin_threshold_inr_t',
            "trade_eligible": f'=AND({R("open_base")},{R("open_pit_mix")},{R("open_conv18k")})',
            # a 1/0 mirror of the flag, so a three-key look-up elsewhere can use SUMIFS instead of an array formula
            "trade_eligible_n": f'=IF({R("trade_eligible")},1,0)',
        }
        t.write_row(i, r)

    t.freeze("lme_3m_usd_t")
    t.autofilter()
    sh.after(t)
    return t, order
