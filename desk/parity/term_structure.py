"""LME Cash–3M term structure (Table 3 row 1.7): weekly structure, M+1 pricing basis and hedge roll yield.

Why it matters to this desk. The parity (CONTRACTS §5) prices scrap off LME **3M** — the forward a desk can hedge
on the decision date — but the desk's LME-linked SPAs settle on the arithmetic average of the LME **Official Cash
Settlement Price** over the month after the B/L month (exchange.yaml ``lme_pricing_reference`` and
``lme_m1_pricing_rule``). The gap between the M+1 average of cash and today's 3M is set by the curve's shape:

* (a) M+1 basis. The market-implied expected M+1 average of cash is read off a forward curve interpolated linearly in
  calendar days between the cash prompt (value date + ``lme_cash_prompt_bdays`` business days) and the 3M prompt
  (value date + 3 calendar months, next weekday): F(p) = cash + (3M − cash) × (p − p_cash) / (p_3M − p_cash). Each
  weekday d of the M+1 month fixes a cash price for prompt d + ``lme_cash_prompt_bdays``; the expected average is the
  mean of F over those prompts (expectations hypothesis: forward = expected spot, no risk premium; LME holidays in
  the averaging month are not removed). In contango the implied M+1 average is below 3M, so a buyer priced on M+1
  cash pays less than the 3M-based parity assumed (the structure *earns* the buyer the difference); in backwardation
  it costs. The realised M+1 average is shown too, labelled HINDSIGHT — it adds the price move nobody knew.
* (b) Roll yield. MCX hedges roll M1 → M2 ``mcx_roll_days_before_expiry`` panel trading days before M1 expiry. A
  short hedge (the importer's hedge) buys back M1 and sells M2, so it earns M2 − M1 when M2 > M1 (contango) and pays
  it in backwardation. The panel MCX is a PROXY whose M2 − M1 is pure INR carry, so the third-party mirror roll and
  the LME-equivalent carry (Cash–3M pro-rated to the M1→M2 expiry gap) are shown beside it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from desk import WINDOW_END, WINDOW_START, config, units
from desk.parity import model

THREE_MONTHS = 3
ROLL_TONNES_MT = 1000.0
FIRST_ROLL_MONTH = pd.Period("2022-01", freq="M")
LAST_ROLL_MONTH = pd.Period("2022-10", freq="M")


def _next_weekday(ts: pd.Timestamp) -> pd.Timestamp:
    while ts.dayofweek >= 5:
        ts += pd.Timedelta(days=1)
    return ts


def prompts(value_date: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    cash_bd = int(config.value("lme_cash_prompt_bdays"))
    cash_prompt = value_date + pd.offsets.BDay(cash_bd)
    three_m = _next_weekday(value_date + pd.DateOffset(months=THREE_MONTHS))
    return pd.Timestamp(cash_prompt), pd.Timestamp(three_m)


def forward_price(prompt: pd.Timestamp, cash: float, three_m: float, p_cash: pd.Timestamp, p_3m: pd.Timestamp) -> float:
    """Linear-in-days forward curve through (p_cash, cash) and (p_3m, 3M); linear extrapolation outside."""
    span = (p_3m - p_cash).days
    return cash + (three_m - cash) * (prompt - p_cash).days / span


def implied_month_average(month: pd.Period, value_date: pd.Timestamp, cash: float, three_m: float) -> float:
    p_cash, p_3m = prompts(value_date)
    cash_bd = int(config.value("lme_cash_prompt_bdays"))
    fixing_days = pd.bdate_range(month.start_time, month.end_time)
    fwd = [forward_price(d + pd.offsets.BDay(cash_bd), cash, three_m, p_cash, p_3m) for d in fixing_days]
    return float(np.mean(fwd))


def classify(spread_usd_t: float) -> str:
    return "BACKWARDATION" if spread_usd_t > 0 else ("CONTANGO" if spread_usd_t < 0 else "FLAT")


def weekly_table(panel: pd.DataFrame | None = None) -> pd.DataFrame:
    panel = model.load_panel() if panel is None else panel
    market = model.weekly_market(panel)
    cash_daily = panel.set_index("date")["lme_cash_usd_t"].sort_index()
    offset = int(config.value("mplus1_bl_month_offset_months"))
    rows = []
    for r in market.itertuples():
        vd = pd.Timestamp(r.value_date)
        cash, three_m, fx = float(r.lme_cash_usd_t), float(r.lme_3m_usd_t), float(r.usdinr)
        p_cash, p_3m = prompts(vd)
        days = (p_3m - p_cash).days
        carry = three_m - cash
        mplus1 = vd.to_period("M") + offset + 1
        implied = implied_month_average(mplus1, vd, cash, three_m)
        realised_days = cash_daily.loc[mplus1.start_time:mplus1.end_time]
        realised = float(realised_days.mean()) if len(realised_days) else np.nan
        rows.append({
            "week_end": r.week_end, "value_date": vd, "in_window": bool(r.in_window),
            "lme_cash_usd_t": cash, "lme_3m_usd_t": three_m,
            "lme_cash_3m_spread_usd_t": float(r.lme_cash_3m_spread_usd_t),
            "structure": classify(float(r.lme_cash_3m_spread_usd_t)),
            "cash_prompt_date": p_cash, "three_m_prompt_date": p_3m, "days_cash_to_3m": days,
            "carry_3m_usd_t": carry,
            "carry_3m_pct_pa": (three_m / cash - 1.0) * 365.0 / days,
            "usdinr": fx,
            "mplus1_month": str(mplus1),
            "mplus1_implied_avg_cash_usd_t": implied,
            "mplus1_implied_minus_3m_usd_t": implied - three_m,
            "structure_effect_buyer_usd_t": three_m - implied,
            "structure_effect_buyer_1000mt_usd": (three_m - implied) * ROLL_TONNES_MT,
            "structure_effect_buyer_1000mt_inr": units.usd_t_to_inr_t(three_m - implied, fx) * ROLL_TONNES_MT,
            "hindsight_realised_mplus1_avg_cash_usd_t": realised,
            "hindsight_price_move_vs_implied_usd_t": realised - implied,
            "hindsight_effect_buyer_vs_3m_1000mt_inr": units.usd_t_to_inr_t(three_m - realised, fx) * ROLL_TONNES_MT,
            "hindsight_n_fixing_days": int(len(realised_days)),
        })
    return pd.DataFrame(rows)


def roll_table(panel: pd.DataFrame | None = None, mirror: pd.DataFrame | None = None) -> pd.DataFrame:
    """One MCX M1 → M2 roll per contract month, 2022-01 … 2022-10."""
    from desk.parity.sensitivity import load_mirror

    panel = model.load_panel() if panel is None else panel
    mirror = load_mirror() if mirror is None else mirror
    p = panel.set_index("date").sort_index()
    days = p.index
    n_before = int(config.value("mcx_roll_days_before_expiry"))
    lot = float(config.value("mcx_al_lot_mt"))
    published = [pd.Timestamp(x) for x in config.value("mcx_al_expiry_dates_2022")]
    rows = []
    expiries = sorted(pd.to_datetime(p["mcx_m1_expiry"]).unique())
    for exp in expiries:
        exp = pd.Timestamp(exp)
        month = exp.to_period("M")
        if month < FIRST_ROLL_MONTH or month > LAST_ROLL_MONTH:
            continue
        pos = days.get_loc(exp)
        roll_date = days[pos - n_before]
        row = p.loc[roll_date]
        if pd.Timestamp(row["mcx_m1_expiry"]) != exp:
            raise ValueError(f"roll date {roll_date.date()} is not inside the {month} contract")
        m1, m2 = float(row["mcx_al_m1_inr_kg"]), float(row["mcx_al_m2_inr_kg"])
        m2_exp = pd.Timestamp(row["mcx_m2_expiry"])
        mir = mirror.loc[:roll_date].iloc[-1]
        cash, three_m, fx = float(row["lme_cash_usd_t"]), float(row["lme_3m_usd_t"]), float(row["usdinr"])
        p_cash, p_3m = prompts(roll_date)
        roll_days = (m2_exp - exp).days
        lme_carry = (three_m - cash) * roll_days / (p_3m - p_cash).days
        pub = [d for d in published if d.to_period("M") == month]
        rows.append({
            "contract_month": str(month), "m1_expiry": exp, "m2_expiry": m2_exp,
            "mcx_published_expiry": pub[0] if pub else pd.NaT,
            "expiry_matches_published": bool(pub and pub[0] == exp) if pub else None,
            "roll_date": roll_date, "in_window": bool(WINDOW_START <= roll_date.date() <= WINDOW_END),
            "mcx_al_m1_inr_kg": m1, "mcx_al_m2_inr_kg": m2,
            "roll_spread_inr_kg": m2 - m1,
            "short_hedge_roll_yield_inr_t": units.inr_kg_to_inr_t(m2 - m1),
            "short_hedge_roll_yield_1000mt_inr": units.inr_kg_to_inr_t(m2 - m1) * ROLL_TONNES_MT,
            "lots_per_1000mt": units.mt_to_lots(ROLL_TONNES_MT, lot),
            "mirror_date": mirror.loc[:roll_date].index[-1],
            "mirror_m1_inr_kg": float(mir["m1_close_inr_kg"]), "mirror_m2_inr_kg": float(mir["m2_close_inr_kg"]),
            "mirror_short_hedge_roll_yield_1000mt_inr":
                units.inr_kg_to_inr_t(float(mir["m2_close_inr_kg"]) - float(mir["m1_close_inr_kg"])) * ROLL_TONNES_MT,
            "lme_cash_usd_t": cash, "lme_3m_usd_t": three_m,
            "lme_structure": classify(cash - three_m),
            "roll_days": roll_days,
            "lme_equiv_carry_usd_t": lme_carry,
            "lme_equiv_short_roll_yield_1000mt_inr": units.usd_t_to_inr_t(lme_carry, fx) * ROLL_TONNES_MT,
            "usdinr": fx,
        })
    return pd.DataFrame(rows)
