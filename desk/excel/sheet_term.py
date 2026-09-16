"""`Term_Structure` — MASTER_SPEC Table 1.7: LME Cash–3M weekly, the M+1 pricing basis, and the MCX roll yield.

Two calculations, both live:

* **(a) M+1 pricing basis.** The parity prices scrap off LME **3M**, but an LME-linked SPA settles on the average of
  the official **cash** price over the month after the B/L month. The forward curve is linear in calendar days
  between the cash prompt and the 3M prompt, and a linear function's average over a set of prompts is its value at
  the *mean* prompt — so the implied M+1 average is one formula,
  `cash + (3M − cash) × (mean prompt − cash prompt) ÷ (3M prompt − cash prompt)`, with no hidden averaging block.
  In contango the implied M+1 average sits below 3M, so a buyer priced on M+1 cash pays less than the 3M-based
  parity assumed; in backwardation it costs. The realised average is shown beside it, labelled HINDSIGHT, as a live
  `AVERAGEIFS` over `Market_Daily` — it adds the price move nobody knew on the decision day.
* **(b) Roll yield.** A short MCX hedge rolls M1 → M2 `mcx_roll_days_before_expiry` panel days before expiry; it buys
  back M1 and sells M2, so it *earns* M2 − M1 in contango. The panel MCX is a parity PROXY whose M2 − M1 is pure INR
  carry, so the third-party mirror roll (an observed-style series, PROXY) and the LME-equivalent carry are shown
  beside it — that comparison is the point of the table, not the panel number on its own.

Prompt dates, the M+1 month's boundaries and its mean prompt date are **calendar inputs** (blue): they are published
LME prompt rules, not market observations, and Excel's date functions are not all supported by the recalculation
library used in the reconciliation test. Every number derived from them is a formula.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from desk import config
from desk.excel import expr, sources
from desk.excel.layout import INPUT, KEY, Column, Sheet

SHEET = "Term_Structure"

WEEK_KEYS = ["week_end", "value_date", "in_window"]
WEEK_CAL = ["cash_prompt_date", "three_m_prompt_date", "mplus1_month", "mplus1_first_day", "mplus1_last_day",
            "mplus1_mean_prompt_date"]
WEEK_CALC = ["lme_cash_usd_t", "lme_3m_usd_t", "lme_cash_3m_spread_usd_t", "structure", "usdinr",
             "days_cash_to_3m", "carry_3m_usd_t", "carry_3m_pct_pa", "mplus1_implied_avg_cash_usd_t",
             "mplus1_implied_minus_3m_usd_t", "structure_effect_buyer_usd_t", "structure_effect_buyer_1000mt_usd",
             "structure_effect_buyer_1000mt_inr", "hindsight_realised_mplus1_avg_cash_usd_t",
             "hindsight_price_move_vs_implied_usd_t", "hindsight_effect_buyer_vs_3m_1000mt_inr"]

ROLL_KEYS = ["contract_month", "in_window"]
ROLL_CAL = ["m1_expiry", "m2_expiry", "roll_date", "cash_prompt_date", "three_m_prompt_date"]
ROLL_INPUT = ["mirror_m1_inr_kg", "mirror_m2_inr_kg"]
ROLL_CALC = ["mcx_al_m1_inr_kg", "mcx_al_m2_inr_kg", "roll_spread_inr_kg", "short_hedge_roll_yield_inr_t",
             "short_hedge_roll_yield_1000mt_inr", "lots_per_1000mt", "lme_cash_usd_t", "lme_3m_usd_t",
             "lme_structure", "usdinr", "roll_days", "days_cash_to_3m", "lme_equiv_carry_usd_t",
             "lme_equiv_short_roll_yield_1000mt_inr", "mirror_short_hedge_roll_yield_1000mt_inr"]


def write(wb, counts, data: sources.Data, mdt):
    sh = Sheet(wb, SHEET, "Term_Structure — Table 1.7: Cash–3M, the M+1 pricing basis and the MCX roll", counts,
               subtitle="Blue = calendar inputs (LME prompt rules and month boundaries). Everything else is a "
                        "formula over Market_Daily and the Inputs register.")

    sh.section("(a) Weekly structure and the M+1 pricing basis")
    cols = [Column(c, KEY, width=12) for c in WEEK_KEYS]
    cols += [Column(c, INPUT, width=14) for c in WEEK_CAL]
    cols += [Column(c) for c in WEEK_CALC]
    t = sh.table(cols)
    tw = data.term_weekly
    for i, row in enumerate(tw.itertuples(index=False)):
        R = lambda c: t.rowref(c, i)  # noqa: E731
        vd = R("value_date")
        month = pd.Period(row.mplus1_month, freq="M")
        r = {
            "week_end": row.week_end.date(), "value_date": row.value_date.date(), "in_window": bool(row.in_window),
            "cash_prompt_date": row.cash_prompt_date.date(), "three_m_prompt_date": row.three_m_prompt_date.date(),
            "mplus1_month": str(month), "mplus1_first_day": month.start_time.date(),
            "mplus1_last_day": month.end_time.date(),
            "mplus1_mean_prompt_date": _mean_prompt(month),
            "lme_cash_usd_t": "=" + expr.md(mdt, "lme_cash_usd_t", vd),
            "lme_3m_usd_t": "=" + expr.md(mdt, "lme_3m_usd_t", vd),
            "lme_cash_3m_spread_usd_t": f"={R('lme_cash_usd_t')}-{R('lme_3m_usd_t')}",
            "structure": f'=IF({R("lme_cash_3m_spread_usd_t")}>0,"BACKWARDATION",'
                         f'IF({R("lme_cash_3m_spread_usd_t")}<0,"CONTANGO","FLAT"))',
            "usdinr": "=" + expr.md(mdt, "usdinr", vd),
            "days_cash_to_3m": f"={R('three_m_prompt_date')}-{R('cash_prompt_date')}",
            "carry_3m_usd_t": f"={R('lme_3m_usd_t')}-{R('lme_cash_usd_t')}",
            "carry_3m_pct_pa": f"=({R('lme_3m_usd_t')}/{R('lme_cash_usd_t')}-1)*day_count_inr"
                               f"/{R('days_cash_to_3m')}",
            "mplus1_implied_avg_cash_usd_t":
                f"={R('lme_cash_usd_t')}+({R('lme_3m_usd_t')}-{R('lme_cash_usd_t')})"
                f"*({R('mplus1_mean_prompt_date')}-{R('cash_prompt_date')})/{R('days_cash_to_3m')}",
            "mplus1_implied_minus_3m_usd_t": f"={R('mplus1_implied_avg_cash_usd_t')}-{R('lme_3m_usd_t')}",
            "structure_effect_buyer_usd_t": f"={R('lme_3m_usd_t')}-{R('mplus1_implied_avg_cash_usd_t')}",
            "structure_effect_buyer_1000mt_usd": f"={R('structure_effect_buyer_usd_t')}*grid_tonnes_mt",
            "structure_effect_buyer_1000mt_inr": f"={R('structure_effect_buyer_usd_t')}*{R('usdinr')}"
                                                 f"*grid_tonnes_mt",
            "hindsight_realised_mplus1_avg_cash_usd_t":
                f'=AVERAGEIFS({mdt.abs("lme_cash_usd_t")},{mdt.abs("date")},">="&{R("mplus1_first_day")},'
                f'{mdt.abs("date")},"<="&{R("mplus1_last_day")})',
            "hindsight_price_move_vs_implied_usd_t":
                f"={R('hindsight_realised_mplus1_avg_cash_usd_t')}-{R('mplus1_implied_avg_cash_usd_t')}",
            "hindsight_effect_buyer_vs_3m_1000mt_inr":
                f"=({R('lme_3m_usd_t')}-{R('hindsight_realised_mplus1_avg_cash_usd_t')})*{R('usdinr')}"
                f"*grid_tonnes_mt",
        }
        t.write_row(i, r)
    t.freeze("lme_cash_usd_t")
    sh.after(t)

    sh.section("(b) MCX M1 → M2 roll, one row per contract month")
    sh.note("mirror_* are the third-party MCX mirror closes (data/interim, PROXY evidence) — an observed-style series "
            "the panel proxy cannot produce, so they are inputs here, not formulas.")
    rcols = [Column(c, KEY, width=14) for c in ROLL_KEYS]
    rcols += [Column(c, INPUT, width=13) for c in ROLL_CAL]
    rcols += [Column(c, INPUT) for c in ROLL_INPUT]
    rcols += [Column(c) for c in ROLL_CALC]
    rt = sh.table(rcols)
    for i, row in enumerate(data.term_rolls.itertuples(index=False)):
        R = lambda c: rt.rowref(c, i)  # noqa: E731
        rd = R("roll_date")
        cp, tp = _prompts(pd.Timestamp(row.roll_date))
        r = {
            "contract_month": str(row.contract_month), "in_window": bool(row.in_window),
            "m1_expiry": row.m1_expiry.date(), "m2_expiry": row.m2_expiry.date(),
            "roll_date": row.roll_date.date(), "cash_prompt_date": cp, "three_m_prompt_date": tp,
            "mirror_m1_inr_kg": float(row.mirror_m1_inr_kg), "mirror_m2_inr_kg": float(row.mirror_m2_inr_kg),
            "mcx_al_m1_inr_kg": "=" + expr.md(mdt, "mcx_al_m1_inr_kg", rd),
            "mcx_al_m2_inr_kg": "=" + expr.md(mdt, "mcx_al_m2_inr_kg", rd),
            "roll_spread_inr_kg": f"={R('mcx_al_m2_inr_kg')}-{R('mcx_al_m1_inr_kg')}",
            "short_hedge_roll_yield_inr_t": f"={R('roll_spread_inr_kg')}*kg_per_mt",
            "short_hedge_roll_yield_1000mt_inr": f"={R('short_hedge_roll_yield_inr_t')}*grid_tonnes_mt",
            "lots_per_1000mt": "=ROUND(grid_tonnes_mt/mcx_al_lot_mt,0)",
            "lme_cash_usd_t": "=" + expr.md(mdt, "lme_cash_usd_t", rd),
            "lme_3m_usd_t": "=" + expr.md(mdt, "lme_3m_usd_t", rd),
            "lme_structure": f'=IF({R("lme_cash_usd_t")}-{R("lme_3m_usd_t")}>0,"BACKWARDATION",'
                             f'IF({R("lme_cash_usd_t")}-{R("lme_3m_usd_t")}<0,"CONTANGO","FLAT"))',
            "usdinr": "=" + expr.md(mdt, "usdinr", rd),
            "roll_days": f"={R('m2_expiry')}-{R('m1_expiry')}",
            "days_cash_to_3m": f"={R('three_m_prompt_date')}-{R('cash_prompt_date')}",
            "lme_equiv_carry_usd_t": f"=({R('lme_3m_usd_t')}-{R('lme_cash_usd_t')})*{R('roll_days')}"
                                     f"/{R('days_cash_to_3m')}",
            "lme_equiv_short_roll_yield_1000mt_inr": f"={R('lme_equiv_carry_usd_t')}*{R('usdinr')}*grid_tonnes_mt",
            "mirror_short_hedge_roll_yield_1000mt_inr":
                f"=({R('mirror_m2_inr_kg')}-{R('mirror_m1_inr_kg')})*kg_per_mt*grid_tonnes_mt",
        }
        rt.write_row(i, r)
    sh.after(rt)
    return {"weekly": t, "rolls": rt}


def _prompts(value_date: pd.Timestamp):
    """LME prompt rules, as `desk.parity.term_structure.prompts` computes them (calendar only, no market input)."""
    cash_bd = int(config.value("lme_cash_prompt_bdays"))
    cash = pd.Timestamp(value_date) + pd.offsets.BDay(cash_bd)
    three = pd.Timestamp(value_date) + pd.DateOffset(months=3)
    while three.dayofweek >= 5:
        three += pd.Timedelta(days=1)
    return cash.date(), three.date()


def _mean_prompt(month: pd.Period):
    """Mean of the prompts fixed by the quotational month's weekdays.

    Each weekday `d` of the month fixes a cash price for prompt `d + lme_cash_prompt_bdays` business days. The forward
    curve is affine in the prompt date, so the average of the curve over these prompts equals the curve at their
    mean — that identity is what lets the implied M+1 average be one formula instead of a 20-row block. The mean lands
    on a fractional day; Excel keeps the fraction, and the workbook reconciles to Phase 1 to 1e-9 USD/t.
    """
    cash_bd = int(config.value("lme_cash_prompt_bdays"))
    days = pd.bdate_range(month.start_time, month.end_time)
    prompts = [d + pd.offsets.BDay(cash_bd) for d in days]
    serials = np.array([(p - pd.Timestamp("1899-12-30")).days for p in prompts], dtype=float)
    return float(serials.mean())
