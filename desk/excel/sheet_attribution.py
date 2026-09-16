"""`Attribution` — the P&L split (MASTER_SPEC Table 5 row 3.2), its identities re-checked, and the chain worked live.

Three things are on this sheet, and the third is the one to read in an interview.

**1. The daily identity, recomputed in Excel.** For the book, every panel day: `Σ buckets + residual = daily P&L`
and `cum P&L(t) = cum P&L(t−1) + daily P&L(t)`. The buckets are pasted; the two identities are formulas. That is a
real control — CONTRACTS §7.2 requires `|residual| ≤ ₹1` per trade-day, and the sheet shows the residual rather
than asserting it.

**2. Lifetime buckets per trade**, with formula totals down each factor column and across each trade row, and a
`BOOK` reconciliation.

**3. The attribution chain, live, on two worked legs.** The engine computes each day's split by *fully revaluing*
every leg of every ticket eight times — once per `FACTOR_ORDER` block, then the contracts block — from the state of
the previous day to the state of today. That is 8 × 28,343 revaluations over the book's life, each needing the
ticket's whole lifecycle expansion; it is not something a spreadsheet can carry, and pretending otherwise would be
worse than saying so. What a spreadsheet *can* do is show the mechanism exactly, on a leg whose value is closed
form, and tie it to the engine:

* a **short MCX hedge** across 07 → 08-Mar-2022 (the day the LME broke from its all-time high), with the duty-paid
  parity price recomputed at each partially-swapped state;
* a **USD payable against the forward that hedges it**, showing the hedge netting to zero in (e) and (g) — the
  hedge-perfect property the engine asserts in its own tests.

Both worked blocks are formulas over `Market_Daily` and `Inputs`; the numbers beside them come from calling
`desk.mtm.curves` and `desk.mtm.state.swap` directly, so the check is against the engine, not against a document.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from desk import config
from desk.reporting.style import FACTOR_LABELS, FACTOR_ORDER, PNL_BUCKETS
from desk.excel import expr, sources, style
from desk.excel.layout import INPUT, KEY, PASTED, Column, Sheet, Table

SHEET = "Attribution"

# The two worked legs (dates chosen for the story: the day the LME broke from its 07-Mar-2022 all-time high).
WORKED_PREV = dt.date(2022, 3, 7)
WORKED_TODAY = dt.date(2022, 3, 8)
WORKED_MCX_LOTS = -100          # short 100 lots of MCX Aluminium
WORKED_MCX_MONTH = "2022-03"
WORKED_FX_NOTIONAL_USD = 1_000_000.0
WORKED_FX_VALUE_DATE = dt.date(2022, 4, 15)

CHAIN_STEPS = [("V0", "state at t-1", False, False, False, False)] + [
    ("lme_flat", "lme_cash_usd_t", True, False, False, False),
    ("cross_exchange_basis", "mcx basis + domestic premium", True, False, False, False),
    ("grade_spread", "grade_factor_frac", True, False, False, False),
    ("freight", "freight_usd_t", True, False, False, False),
    ("fx", "usdinr + customs_usdinr_import", True, True, False, False),
    ("demurrage_penalty", "events-as-of", True, True, False, False),
    ("roll_term_structure", "spread + rates + the clock", True, True, True, True),
]


def write(wb, counts, data: sources.Data, mdt):
    sh = Sheet(wb, SHEET, "Attribution — the seven market factors plus new_deal, and the chain worked live", counts,
               subtitle="Buckets are exactly desk.reporting.style.PNL_BUCKETS. Cross-terms land in the factor that "
                        "moves last (CONTRACTS §7.4); new_deal is computed last and reported first.")

    sh.section("1. Book daily attribution — the two identities, recomputed in Excel")
    daily = _daily_block(sh, data)
    sh.after(daily)

    sh.section("2. Lifetime P&L by trade and factor (₹) — final cumulative values at HORIZON_END")
    life = _lifetime_block(sh, data)
    sh.after(life)

    sh.section("3a. Worked chain — short 100 MCX lots, 07 → 08-Mar-2022 (design §6.3)")
    sh.note("Position value = lots × lot_mt × 1,000 kg × F, where F is the duty-paid import-parity price carried to "
            "the contract month's panel expiry. Each step swaps one block of the market state and re-prices; the "
            "bucket is the change. (b), (c), (d) and (f) are zero for a futures leg — a panel PROXY day has zero "
            "cross-exchange basis by construction, and a futures position has no grade, freight or event exposure.")
    mcx = _mcx_chain(sh, data, mdt)
    sh.after(mcx)

    sh.section("3b. Worked chain — USD 1,000,000 payable due 15-Apr-2022 against the forward that hedges it")
    sh.note("The forward was booked on 07-Mar at the covered-interest-parity mid plus the bank's margin against the "
            "desk, so its whole day-one value is −notional × fx_forward_bank_margin_inr and lands in new_deal. "
            "Afterwards the two legs cancel in (e) and in (g): that is the hedge-perfect property.")
    fx = _fx_chain(sh, data, mdt)
    sh.after(fx)
    return {"daily": daily, "lifetime": life, "mcx_chain": mcx, "fx_chain": fx}


# ------------------------------------------------------------------------------------------------ block 1
def _daily_block(sh: Sheet, data: sources.Data) -> Table:
    a = data.attribution
    book = a[a["trade_id"] == "BOOK"].sort_values("date").reset_index(drop=True)
    cols = [Column("date", KEY, width=12), Column("in_window", KEY, width=10)]
    cols += [Column(b, PASTED, width=16, header=f"{b}\n{FACTOR_LABELS[b]}") for b in PNL_BUCKETS]
    cols += [Column("residual", PASTED, width=12), Column("daily_pnl_inr_py", PASTED, width=16),
             Column("cum_pnl_inr_py", PASTED, width=16)]
    cols += [Column(c, width=16) for c in ("sum_buckets_inr", "diff_vs_daily_inr", "cum_pnl_calc_inr",
                                           "diff_vs_cum_inr", "check")]
    t = sh.table(cols)
    for i, row in enumerate(book.itertuples(index=False)):
        R = lambda c: t.rowref(c, i)  # noqa: E731
        prev = f"${t.col('cum_pnl_calc_inr')}{t.first_row + i - 1}" if i else None
        r = {"date": row.date.date(), "in_window": bool(row.in_window),
             "residual": float(row.residual), "daily_pnl_inr_py": float(row.daily_pnl_inr),
             "cum_pnl_inr_py": float(row.cum_pnl_inr),
             "sum_buckets_inr": f'=SUM({t.cell(PNL_BUCKETS[0], i)}:{t.cell(PNL_BUCKETS[-1], i)})'
                                f'+{R("residual")}',
             "diff_vs_daily_inr": f'={R("sum_buckets_inr")}-{R("daily_pnl_inr_py")}',
             "cum_pnl_calc_inr": (f'={prev}+{R("daily_pnl_inr_py")}') if i else f'={R("daily_pnl_inr_py")}',
             "diff_vs_cum_inr": f'={R("cum_pnl_calc_inr")}-{R("cum_pnl_inr_py")}',
             "check": f'=IF(AND(ABS({R("diff_vs_daily_inr")})<=tol_trade_inr,'
                      f'ABS({R("diff_vs_cum_inr")})<=tol_trade_inr),"PASS","FAIL")'}
        for b in PNL_BUCKETS:
            r[b] = float(getattr(row, b))
        t.write_row(i, r)
    t.freeze("new_deal")
    return t


# ------------------------------------------------------------------------------------------------ block 2
def _lifetime_block(sh: Sheet, data: sources.Data) -> Table:
    a = data.attribution
    trades = sorted(t for t in a["trade_id"].unique() if t != "BOOK")
    cols = [Column("trade_id", KEY, width=10)]
    cols += [Column(b, PASTED, width=16) for b in PNL_BUCKETS]
    cols += [Column("residual", PASTED, width=12), Column("cum_pnl_inr_py", PASTED, width=18)]
    cols += [Column("sum_buckets_inr", width=18), Column("diff_inr", width=14), Column("check", width=10)]
    t = sh.table(cols)
    rows = []
    for trade in trades:
        sub = a[a["trade_id"] == trade].sort_values("date")
        rows.append((trade, {b: float(sub[b].sum()) for b in PNL_BUCKETS},
                     float(sub["residual"].sum()), float(sub["cum_pnl_inr"].iloc[-1])))
    for i, (trade, buckets, residual, cum) in enumerate(rows):
        R = lambda c: t.rowref(c, i)  # noqa: E731
        r = {"trade_id": trade, "residual": residual, "cum_pnl_inr_py": cum,
             "sum_buckets_inr": f'=SUM({t.cell(PNL_BUCKETS[0], i)}:{t.cell(PNL_BUCKETS[-1], i)})+{R("residual")}',
             "diff_inr": f'={R("sum_buckets_inr")}-{R("cum_pnl_inr_py")}',
             "check": f'=IF(ABS({R("diff_inr")})<=tol_trade_inr,"PASS","FAIL")'}
        r.update(buckets)
        t.write_row(i, r)
    i = len(rows)
    total = {"trade_id": "BOOK (Σ trades, formula)"}
    for b in PNL_BUCKETS + ["residual", "cum_pnl_inr_py"]:
        c = t.col(b)
        total[b] = f"=SUM({c}{t.first_row}:{c}{t.first_row + len(rows) - 1})"
    R = lambda c: t.rowref(c, i)  # noqa: E731
    total["sum_buckets_inr"] = f'=SUM({t.cell(PNL_BUCKETS[0], i)}:{t.cell(PNL_BUCKETS[-1], i)})+{R("residual")}'
    total["diff_inr"] = f'={total["sum_buckets_inr"][1:]}-{R("cum_pnl_inr_py")}'
    total["check"] = f'=IF(ABS({R("diff_inr")})<=tol_trade_inr,"PASS","FAIL")'
    t.write_row(i, total, kinds={b: "formula" for b in PNL_BUCKETS + ["residual", "cum_pnl_inr_py"]})
    return t


# ------------------------------------------------------------------------------------------------ block 3a
MCX_CHAIN_KEYS = ["step", "bucket", "block_swapped", "cash_src_date", "fx_src_date", "rate_src_date", "clock_date"]
MCX_CHAIN_CALC = ["lme_cash_usd_t", "usdinr", "inr_rate_3m_pa", "expiry_date", "dte_days", "mcx_price_inr_kg",
                  "position_value_inr", "bucket_inr"]


def _mcx_chain(sh: Sheet, data: sources.Data, mdt) -> Table:
    engine = _engine_mcx_chain()
    cols = [Column("step", KEY, width=6), Column("bucket", KEY, width=22), Column("block_swapped", KEY, width=32)]
    cols += [Column(c, INPUT, width=13) for c in ("cash_src_date", "fx_src_date", "rate_src_date", "clock_date")]
    cols += [Column("lots_signed", INPUT, width=11), Column("lot_mt", INPUT, width=9),
             Column("contract_month", INPUT, width=13)]
    cols += [Column(c, width=16) for c in MCX_CHAIN_CALC]
    cols += [Column("py_bucket_inr", PASTED, width=16), Column("diff_inr", width=13), Column("check", width=9)]
    t = sh.table(cols)
    for i, (name, block, cash_new, fx_new, rate_new, clock_new) in enumerate(CHAIN_STEPS):
        R = lambda c: t.rowref(c, i)  # noqa: E731
        prev = f"${t.col('position_value_inr')}{t.first_row + i - 1}" if i else None
        r = {
            "step": i, "bucket": name if i else "—", "block_swapped": block,
            "cash_src_date": WORKED_TODAY if cash_new else WORKED_PREV,
            "fx_src_date": WORKED_TODAY if fx_new else WORKED_PREV,
            "rate_src_date": WORKED_TODAY if rate_new else WORKED_PREV,
            "clock_date": WORKED_TODAY if clock_new else WORKED_PREV,
            "lots_signed": WORKED_MCX_LOTS, "lot_mt": float(config.value("mcx_al_lot_mt")),
            "contract_month": int(WORKED_MCX_MONTH.replace("-", "")),
            "lme_cash_usd_t": "=" + expr.md(mdt, "lme_cash_usd_t", R("cash_src_date")),
            "usdinr": "=" + expr.md(mdt, "usdinr", R("fx_src_date")),
            "inr_rate_3m_pa": "=" + expr.md(mdt, "inr_rate_3m_pa", R("rate_src_date")),
            "expiry_date": f'=INDEX(mcx_expiries,MATCH({R("contract_month")},mcx_months,0))',
            "dte_days": f'=MAX(0,{R("expiry_date")}-{R("clock_date")})',
            "mcx_price_inr_kg": f'=({R("lme_cash_usd_t")}*{R("usdinr")}/kg_per_mt'
                                f'*(1+bcd_primary_al_hs7601*(1+sws_rate_on_bcd))+mcx_domestic_premium_inr_kg)'
                                f'*(1+{R("inr_rate_3m_pa")}*{R("dte_days")}/day_count_inr)',
            "position_value_inr": f'={R("lots_signed")}*{R("lot_mt")}*kg_per_mt*{R("mcx_price_inr_kg")}',
            "bucket_inr": (f'={R("position_value_inr")}-{prev}') if i else "=0",
            "py_bucket_inr": engine[name] if i else 0.0,
            "diff_inr": f'={R("bucket_inr")}-{R("py_bucket_inr")}',
            "check": f'=IF(ABS({R("diff_inr")})<=tol_trade_inr,"PASS","FAIL")',
        }
        t.write_row(i, r)
    return t


# ------------------------------------------------------------------------------------------------ block 3b
def _fx_chain(sh: Sheet, data: sources.Data, mdt) -> Table:
    engine, strike = _engine_fx_chain()
    cols = [Column("step", KEY, width=6), Column("bucket", KEY, width=22), Column("block_swapped", KEY, width=32)]
    cols += [Column(c, INPUT, width=13) for c in ("fx_src_date", "rate_src_date", "clock_date")]
    cols += [Column("notional_usd", INPUT, width=14), Column("value_date", INPUT, width=12),
             Column("strike_inr", INPUT, width=12)]
    cols += [Column(c, width=17) for c in ("usdinr", "inr_rate_3m_pa", "usd_rate_3m_pa", "days_to_value",
                                           "fx_x_calc", "forward_value_inr", "payable_value_inr",
                                           "net_value_inr", "forward_bucket_inr", "payable_bucket_inr",
                                           "net_bucket_inr")]
    cols += [Column("py_forward_bucket_inr", PASTED, width=18), Column("diff_inr", width=13),
             Column("check", width=9)]
    t = sh.table(cols)
    for i, (name, block, _cash_new, fx_new, rate_new, clock_new) in enumerate(CHAIN_STEPS):
        R = lambda c: t.rowref(c, i)  # noqa: E731
        pf = f"${t.col('forward_value_inr')}{t.first_row + i - 1}" if i else None
        pp = f"${t.col('payable_value_inr')}{t.first_row + i - 1}" if i else None
        r = {
            "step": i, "bucket": name if i else "—", "block_swapped": block,
            "fx_src_date": WORKED_TODAY if fx_new else WORKED_PREV,
            "rate_src_date": WORKED_TODAY if rate_new else WORKED_PREV,
            "clock_date": WORKED_TODAY if clock_new else WORKED_PREV,
            "notional_usd": WORKED_FX_NOTIONAL_USD, "value_date": WORKED_FX_VALUE_DATE, "strike_inr": strike,
            "usdinr": "=" + expr.md(mdt, "usdinr", R("fx_src_date")),
            "inr_rate_3m_pa": "=" + expr.md(mdt, "inr_rate_3m_pa", R("rate_src_date")),
            "usd_rate_3m_pa": "=" + expr.md(mdt, "usd_rate_3m_pa", R("rate_src_date")),
            "days_to_value": f'={R("value_date")}-{R("clock_date")}',
            "fx_x_calc": "=" + expr.fx_forward(R("usdinr"), R("inr_rate_3m_pa"), R("usd_rate_3m_pa"),
                                               R("days_to_value")),
            "forward_value_inr": f'={R("notional_usd")}*({R("fx_x_calc")}-{R("strike_inr")})',
            "payable_value_inr": f'=-{R("notional_usd")}*{R("fx_x_calc")}',
            "net_value_inr": f'={R("forward_value_inr")}+{R("payable_value_inr")}',
            "forward_bucket_inr": (f'={R("forward_value_inr")}-{pf}') if i else "=0",
            "payable_bucket_inr": (f'={R("payable_value_inr")}-{pp}') if i else "=0",
            "net_bucket_inr": f'={R("forward_bucket_inr")}+{R("payable_bucket_inr")}',
            "py_forward_bucket_inr": engine[name] if i else 0.0,
            "diff_inr": f'={R("forward_bucket_inr")}-{R("py_forward_bucket_inr")}',
            "check": f'=IF(ABS({R("diff_inr")})<=tol_trade_inr,"PASS","FAIL")',
        }
        t.write_row(i, r)
    return t


# --------------------------------------------------------------- the engine's own answer, for the two chains
def _engine_mcx_chain() -> dict[str, float]:
    from desk.mtm import curves, state as st
    from desk.mtm.history import MarketHistory

    H = MarketHistory()
    M0, M1 = H.state_at(WORKED_PREV), H.state_at(WORKED_TODAY)
    HV0, HV1 = H.view(WORKED_PREV), H.view(WORKED_TODAY)
    month = pd.Period(WORKED_MCX_MONTH, freq="M")
    n = WORKED_MCX_LOTS * float(H.param("mcx_al_lot_mt", WORKED_PREV)) * 1000.0
    prev = curves.mcx_price(HV0, M0, WORKED_PREV, month)
    S = M0
    out: dict[str, float] = {}
    for name in FACTOR_ORDER:
        S = st.swap(S, M1, name)
        last = name == FACTOR_ORDER[-1]
        price = curves.mcx_price(HV1 if last else HV0, S, WORKED_TODAY if last else WORKED_PREV, month)
        out[name] = n * (price - prev)
        prev = price
    return out


def _engine_fx_chain() -> tuple[dict[str, float], float]:
    from desk.mtm import curves, state as st
    from desk.mtm.history import MarketHistory

    H = MarketHistory()
    M0, M1 = H.state_at(WORKED_PREV), H.state_at(WORKED_TODAY)
    HV0, HV1 = H.view(WORKED_PREV), H.view(WORKED_TODAY)
    T = WORKED_FX_VALUE_DATE
    strike = curves.fx_forward_strike(H, WORKED_PREV, T, +1)
    prev = curves.fx_x(HV0, M0, WORKED_PREV, T)
    S = M0
    out: dict[str, float] = {}
    for name in FACTOR_ORDER:
        S = st.swap(S, M1, name)
        last = name == FACTOR_ORDER[-1]
        x = curves.fx_x(HV1 if last else HV0, S, WORKED_TODAY if last else WORKED_PREV, T)
        out[name] = WORKED_FX_NOTIONAL_USD * (x - prev)
        prev = x
    return out, strike
