"""`Cashflows` — the dated cash ledger of the nine tickets, plus the MCX margin schedule, live.

Two blocks:

**1. The ledger** (`outputs/tables/trade_cashflows.csv`, REALISED scenario). Each row is one dated flow with its
`pnl_class` — **PNL**, or **BS** for a balance-sheet flow that moves cash and funding but is never P&L and whose
lifetime sum per trade is zero (IGST paid and credited, MCX initial margin). Three things are formulas:

* the FX rate applied to every USD flow, looked up on its own **settle date** in `Market_Daily` (a settled flow is
  valued at the spot that actually fixed — CONTRACTS §7a.1 clause 4);
* `amount_ccy_calc` for the flows the workbook can derive end to end — every MCX flow, from the margin schedule
  below, and every FX forward, as `sign × notional × (spot on the value date − dealt rate)`;
* `amount_inr_calc`, and the difference against the engine.

Leg amounts the workbook does **not** derive are marked `PYTHON_LIFECYCLE` in `amount_src` and coloured green: they
come out of the ticket lifecycle (dates rolled on the panel calendar, quotational-period averages, survey outcomes,
demurrage day counts), which is a date-and-contract computation, not a market one. `docs/35_excel_workbook.md` §7
lists them and says why each stays in Python.

**2. The MCX margin schedule** (MASTER_SPEC Table 5 row 3.4 — the cash-flow schedule through the crash). This block
is derived from `Market_Daily` end to end: the settle for the contract month, the previous settle, variation margin,
contract value, initial margin at `mcx_al_margin_used_frac` and at the 12 % / 15 % stress levels, the slippage and
transaction charge on every entry, roll and exit, and the running margin cash. Rows are sorted by hedge line and then
by date so the previous-day settle is the row above; the Python values sit beside them as a check.
"""

from __future__ import annotations

import pandas as pd

from desk.excel import expr, sources
from desk.excel.layout import INPUT, KEY, PASTED, Column, Sheet, Table
from desk.paths import TABLES_DIR

SHEET = "Cashflows"

LEDGER_KEYS = ["trade_id", "leg_id", "hedge_id", "leg_type", "cf_type", "pnl_class", "currency",
               "contract_date", "fixing_date", "due_date_contractual", "settle_date", "date_rule",
               "event_ids", "weakest_input_flag"]
LEDGER_INPUTS = ["fx_sign", "fx_notional_usd", "fx_value_date", "fx_strike_inr"]
LEDGER_CALC = ["amount_src", "amount_ccy_calc", "fx_rate_calc", "amount_inr_calc", "diff_inr", "check"]

MCX_KEYS = ["trade_id", "hedge_id", "date", "contract_month", "direction", "action", "in_window"]
MCX_INPUTS = ["lots_signed", "lot_mt"]
MCX_CALC = ["is_opening", "is_closing", "desk_buys", "settle_inr_kg", "panel_settle_inr_kg",
            "basis_vs_panel_inr_kg", "prev_settle_inr_kg", "fill_inr_kg",
            "vm_inr", "cum_vm_inr", "contract_value_inr", "im_required_inr", "prev_im_required_inr",
            "im_change_inr", "im_stress_012_inr", "im_stress_015_inr", "slippage_inr", "txn_charge_inr",
            "txn_total_inr", "net_margin_cash_inr", "cum_margin_cash_inr"]
MCX_PY = ["vm_inr", "im_required_inr", "txn_cost_inr", "net_margin_cash_inr", "funding_on_margin_inr"]

DERIVED_TYPES = {"MCX_VARIATION_MARGIN", "MCX_INITIAL_MARGIN", "MCX_SLIPPAGE", "MCX_TRANSACTION_COST", "FX_FORWARD"}


def write(wb, counts, data: sources.Data, mdt):
    sh = Sheet(wb, SHEET, "Cashflows — the dated cash ledger, and the MCX margin schedule derived from the panel",
               counts,
               subtitle="pnl_class PNL = P&L; BS = balance-sheet (moves cash and funding, never P&L, lifetime sum "
                        "zero per trade). Funding is an accrual, not a dated flow — it is on Equity_Curve.")
    vm = _mcx_frame()
    ledger = data.cashflows
    fx_lines = _fx_lines(data)

    led_cols = [Column(c, KEY, width=_w(c)) for c in LEDGER_KEYS]
    led_cols += [Column("amount_ccy", PASTED, width=16), Column("amount_inr_py", PASTED, width=16)]
    led_cols += [Column(c, INPUT, width=15) for c in LEDGER_INPUTS]
    led_cols += [Column(c, width=16) for c in LEDGER_CALC]
    led_cols += [Column("formula", KEY, width=62), Column("label", KEY, width=30)]

    mcx_cols = [Column(c, KEY, width=_w(c)) for c in MCX_KEYS]
    mcx_cols += [Column(c, INPUT, width=12) for c in MCX_INPUTS]
    mcx_cols += [Column(c, width=16) for c in MCX_CALC]
    mcx_cols += [Column(f"py_{c}", PASTED, width=16) for c in MCX_PY]
    mcx_cols += [Column(c, width=14) for c in ("diff_vm_inr", "diff_im_inr", "diff_net_margin_inr", "check")]

    sh.section("1. Cash ledger — one row per dated flow (outputs/tables/trade_cashflows.csv, REALISED)")
    led_header = sh.row + 1
    mcx_header = led_header + len(ledger) + 4
    t = Table(sh, led_cols, led_header)
    m = Table(sh, mcx_cols, mcx_header)

    _fill_mcx(m, vm, mdt)
    _fill_ledger(t, m, ledger, fx_lines, mdt)

    t.freeze("amount_ccy")
    t.autofilter()
    sh.section_at(mcx_header - 2, "2. MCX margin schedule — variation margin, initial margin and charges, "
                                  "derived from Market_Daily (MASTER_SPEC Table 5 row 3.4)")
    sh.row = m.first_row + m.n_rows + 2
    return {"ledger": t, "mcx": m}


# ------------------------------------------------------------------------------------------------ MCX schedule
def _mcx_frame() -> pd.DataFrame:
    v = pd.read_csv(TABLES_DIR / "mcx_variation_margin.csv", parse_dates=["date"])
    v = v[v["mcx_series"] == "PANEL_PROXY"].copy()
    v["contract_month_n"] = v["contract_month"].str.replace("-", "", regex=False).astype(int)
    # sorted by hedge line, then date: the previous settle for a line is then always the row above
    return v.sort_values(["hedge_id", "date"], kind="mergesort").reset_index(drop=True)


def _fill_mcx(m: Table, v: pd.DataFrame, mdt) -> None:
    n = len(v)
    for i, row in enumerate(v.itertuples(index=False)):
        R = lambda c: m.rowref(c, i)  # noqa: E731
        prev = (lambda c: f"${m.col(c)}{m.first_row + i - 1}") if i else None
        same = f"(${m.col('hedge_id')}{m.first_row + i - 1}={R('hedge_id')})" if i else "FALSE"
        r = {
            "trade_id": row.trade_id, "hedge_id": row.hedge_id, "date": row.date.date(),
            "contract_month": int(row.contract_month_n), "direction": row.direction, "action": row.action,
            "in_window": bool(row.in_window),
            "lots_signed": int(row.lots), "lot_mt": float(row.lot_mt),
            "is_opening": f'=OR({R("action")}="entry",{R("action")}="roll_in")',
            "is_closing": f'=OR({R("action")}="exit",{R("action")}="roll_out")',
            "desk_buys": f'=OR(AND({R("direction")}="SELL",{R("is_closing")}),'
                         f'AND({R("direction")}="BUY",{R("is_opening")}))',
            # The engine marks a futures line at the duty-paid import-parity price it recomputes (design D4), not at
            # the panel column, which the CSV rounds to 4 dp — on 10^6 kg that rounding is worth ~₹100 a day.
            "settle_inr_kg": "=" + expr.mcx_theo(mdt, R("date"), R("contract_month")),
            "panel_settle_inr_kg": "=" + expr.mcx_settle(mdt, R("date"), R("contract_month")),
            "basis_vs_panel_inr_kg": f'={R("panel_settle_inr_kg")}-{R("settle_inr_kg")}',
            "prev_settle_inr_kg": f'=IF({same},{prev("settle_inr_kg")},"")' if i else '=""',
            "fill_inr_kg": f'={R("settle_inr_kg")}+IF({R("desk_buys")},1,-1)*mcx_slippage_ticks'
                           f'*mcx_al_tick_inr_kg',
            "vm_inr": (f'=IF({same},{R("lots_signed")}*{R("lot_mt")}*kg_per_mt'
                       f'*({R("settle_inr_kg")}-{prev("settle_inr_kg")}),0)') if i else "=0",
            "cum_vm_inr": (f'=IF({same},{prev("cum_vm_inr")},0)+{R("vm_inr")}') if i else f'={R("vm_inr")}',
            "contract_value_inr": f'=ABS({R("lots_signed")})*{R("lot_mt")}*kg_per_mt*{R("settle_inr_kg")}',
            "im_required_inr": f'=IF({R("is_closing")},0,{R("contract_value_inr")}*mcx_al_margin_used_frac)',
            "prev_im_required_inr": (f'=IF({same},{prev("im_required_inr")},0)') if i else "=0",
            "im_change_inr": f'={R("im_required_inr")}-{R("prev_im_required_inr")}',
            "im_stress_012_inr": f'=IF({R("is_closing")},0,{R("contract_value_inr")}*0.12)',
            "im_stress_015_inr": f'=IF({R("is_closing")},0,{R("contract_value_inr")}*0.15)',
            "slippage_inr": f'=IF({R("action")}="hold",0,-ABS({R("lots_signed")})*{R("lot_mt")}*kg_per_mt'
                            f'*mcx_slippage_ticks*mcx_al_tick_inr_kg)',
            "txn_charge_inr": f'=IF({R("action")}="hold",0,-ABS({R("lots_signed")})*{R("lot_mt")}*kg_per_mt'
                              f'*{R("fill_inr_kg")}*mcx_txn_cost_frac)',
            "txn_total_inr": f'={R("slippage_inr")}+{R("txn_charge_inr")}',
            "net_margin_cash_inr": f'={R("vm_inr")}-{R("im_change_inr")}+{R("txn_total_inr")}',
            "cum_margin_cash_inr": (f'=IF({same},{prev("cum_margin_cash_inr")},0)+{R("net_margin_cash_inr")}')
                                   if i else f'={R("net_margin_cash_inr")}',
            "py_vm_inr": float(row.vm_inr), "py_im_required_inr": float(row.im_required_inr),
            "py_txn_cost_inr": float(row.txn_cost_inr),
            "py_net_margin_cash_inr": float(row.net_margin_cash_inr),
            "py_funding_on_margin_inr": float(row.funding_on_margin_inr),
            "diff_vm_inr": f'={R("vm_inr")}-{R("py_vm_inr")}',
            "diff_im_inr": f'={R("im_required_inr")}-{R("py_im_required_inr")}',
            "diff_net_margin_inr": f'={R("net_margin_cash_inr")}-{R("py_net_margin_cash_inr")}',
            "check": f'=IF(AND(ABS({R("diff_vm_inr")})<=tol_mcx_inr,ABS({R("diff_im_inr")})<=tol_mcx_inr,'
                     f'ABS({R("diff_net_margin_inr")})<=tol_mcx_inr),"PASS","FAIL")',
        }
        m.write_row(i, r)
    m.n_rows = n


# ------------------------------------------------------------------------------------------------ ledger
def _fx_lines(data: sources.Data) -> dict[str, dict]:
    h = data.hedges
    fx = h[h["instrument"].astype(str).str.upper().str.contains("FORWARD")]
    out = {}
    for row in fx.itertuples(index=False):
        # direction is recorded as BUY_USD / SELL_USD on the ticket
        out[str(row.hedge_id)] = {
            "sign": 1.0 if "BUY" in str(row.direction).upper() else -1.0,
            "notional_usd": float(row.notional_usd),
            "value_date": pd.Timestamp(row.value_date).date(),
            "strike_inr": float(row.rate_inr),
        }
    return out


def _fill_ledger(t: Table, m: Table, ledger: pd.DataFrame, fx_lines: dict, mdt) -> None:
    n_mcx = m.n_rows
    for i, row in enumerate(ledger.itertuples(index=False)):
        R = lambda c: t.rowref(c, i)  # noqa: E731
        leg_id = str(row.leg_id)
        hedge_id = leg_id.split(":", 1)[1] if ":" in leg_id else ""
        cf = str(row.cf_type)
        fx = fx_lines.get(hedge_id)
        r = {
            "trade_id": row.trade_id, "leg_id": leg_id, "hedge_id": hedge_id, "leg_type": str(row.leg_type),
            "cf_type": cf, "pnl_class": str(row.pnl_class), "currency": str(row.currency),
            "contract_date": _d(row.contract_date), "fixing_date": _d(row.fixing_date),
            "due_date_contractual": _d(row.due_date_contractual), "settle_date": _d(row.settle_date),
            "date_rule": str(row.date_rule), "event_ids": _s(row.event_ids),
            "weakest_input_flag": str(row.weakest_input_flag),
            "amount_ccy": float(row.amount_ccy), "amount_inr_py": float(row.amount_inr),
            "formula": _s(row.formula), "label": _s(row.label),
            "fx_rate_calc": f'=IF({R("currency")}="INR",1,{expr.md(mdt, "usdinr", R("settle_date"))})',
            "amount_inr_calc": f'={R("amount_ccy_calc")}*{R("fx_rate_calc")}',
            "diff_inr": f'={R("amount_inr_calc")}-{R("amount_inr_py")}',
            "check": f'=IF(ABS({R("diff_inr")})<=tol_cashflow_inr,"PASS","FAIL")',
        }
        if cf in ("MCX_VARIATION_MARGIN", "MCX_SLIPPAGE", "MCX_TRANSACTION_COST", "MCX_INITIAL_MARGIN"):
            col = {"MCX_VARIATION_MARGIN": "vm_inr", "MCX_SLIPPAGE": "slippage_inr",
                   "MCX_TRANSACTION_COST": "txn_charge_inr", "MCX_INITIAL_MARGIN": "im_change_inr"}[cf]
            sign = "-" if cf == "MCX_INITIAL_MARGIN" else ""
            r["amount_src"] = "DERIVED_IN_WORKBOOK"
            r["amount_ccy_calc"] = (f'={sign}SUMIFS({m.abs(col, n_mcx)},{m.abs("hedge_id", n_mcx)},{R("hedge_id")},'
                                    f'{m.abs("date", n_mcx)},{R("settle_date")})')
        elif cf == "FX_FORWARD" and fx:
            r["amount_src"] = "DERIVED_IN_WORKBOOK"
            r["fx_sign"] = fx["sign"]
            r["fx_notional_usd"] = fx["notional_usd"]
            r["fx_value_date"] = fx["value_date"]
            r["fx_strike_inr"] = fx["strike_inr"]
            # Always valued to the forward's own VALUE date: that is the spot of the day when the line runs to
            # maturity (settle = value), and the covered-interest-parity forward from the cancel date when it does not.
            r["amount_ccy_calc"] = (f'={R("fx_sign")}*{R("fx_notional_usd")}'
                                    f'*({expr.fx_x(mdt, R("settle_date"), R("fx_value_date"))}'
                                    f'-{R("fx_strike_inr")})')
        else:
            r["amount_src"] = "PYTHON_LIFECYCLE"
            r["amount_ccy_calc"] = f'={R("amount_ccy")}'
        t.write_row(i, r)
    t.n_rows = len(ledger)


def _d(v):
    return pd.Timestamp(v).date() if pd.notna(v) else None


def _s(v):
    return "" if (v is None or (isinstance(v, float) and pd.isna(v))) else str(v)


def _w(name: str) -> float:
    if name in ("leg_id", "cf_type", "leg_type", "date_rule"):
        return 24
    if name.endswith("_date") or name == "date":
        return 12
    return 13
