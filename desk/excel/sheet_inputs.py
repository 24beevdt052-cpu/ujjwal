"""`Inputs` — the assumptions register as the workbook's only set of model dials.

Every parameter CONTRACTS §5 and the Phase 3 valuation read is here once, with its unit, provenance flag, source and
verification status, exactly as `config/params/*.yaml` carries it. Scalars get a **named range** so a formula on any
other sheet can say `bcd_scrap_hs7602` instead of `$B$14`; grade- and lane-specific keys are looked up by key through
the `param_keys` / `param_values` pair, because the formula builds the key from the row (`"moisture_frac_" & grade`).

Dated parameters are written as the register's own breakpoint tables and resolved **by formula** on each market date
(`desk.excel.sheet_market`), step or linear as the register says — the workbook never pastes a resolved path value.
"""

from __future__ import annotations

import datetime as dt

from openpyxl.workbook.defined_name import DefinedName

from desk import HORIZON_END, WINDOW_END, WINDOW_START
from desk.excel import sources
from desk.excel.layout import INPUT, KEY, Column, Sheet

SHEET = "Inputs"

PARAM_COLS = [
    Column("key", KEY, width=38),
    Column("value", INPUT, width=16),
    Column("unit", KEY, width=26),
    Column("flag", KEY, width=12),
    Column("named_range", KEY, width=24),
    Column("file", KEY, width=18),
    Column("source", KEY, width=60),
    Column("verify", KEY, width=44),
    Column("note", KEY, width=90),
]

PATH_COLS = [Column("date", KEY, width=13), Column("value", INPUT, width=14)]

# Workbook-level constants: model structure, not market observations (CONTRACTS §1.6).
CONSTANTS = [
    ("window_start", dt.date(WINDOW_START.year, WINDOW_START.month, WINDOW_START.day),
     "date", "CONTRACTS §3 headline window start (desk.WINDOW_START)"),
    ("window_end", dt.date(WINDOW_END.year, WINDOW_END.month, WINDOW_END.day),
     "date", "CONTRACTS §3 headline window end (desk.WINDOW_END)"),
    ("horizon_end", dt.date(HORIZON_END.year, HORIZON_END.month, HORIZON_END.day),
     "date", "CONTRACTS §7 engine horizon (desk.HORIZON_END)"),
    ("conv_step_5a", float(sources.SECTION_5A_CONVERSION_INR_T_INGOT), "inr_per_mt_ingot",
     "CONTRACTS §5a case 3: conversion one grid step above base"),
    ("grid_tonnes_mt", 1000.0, "mt", "MASTER_SPEC Table 1.5 grids are quoted on 1,000 MT"),
    ("day_count_inr", 365.0, "days", "desk.units.DAY_COUNT_INR — INR ACT/365"),
    ("day_count_usd", 360.0, "days", "desk.units.DAY_COUNT_USD — USD ACT/360"),
    ("kg_per_mt", 1000.0, "kg", "desk.units.KG_PER_MT"),
    ("tol_parity_inr_t", 1.0, "inr_per_mt", "Checks tolerance: ₹1 per tonne on every parity line"),
    ("tol_trade_inr", 10.0, "inr", "Checks tolerance: ₹10 per trade on MTM and cumulative P&L"),
    ("tol_grid_inr", 10.0, "inr", "Checks tolerance: ₹10 on a 1,000 MT sensitivity grid cell"),
    ("tol_cashflow_inr", 1.0, "inr", "Checks tolerance: ₹1 per cash-ledger row (the published CSV rounds "
                                     "amount_ccy to 2 dp, so a re-derived INR amount cannot tie closer)"),
    ("tol_mcx_inr", 1.0, "inr", "Checks tolerance: ₹1 per MCX margin row. The engine marks a futures line at the "
                                "import-parity price it recomputes, not at the panel column the CSV rounds to 4 dp, "
                                "so the workbook can follow it to the paisa (design D4)"),
    ("tol_usd_t", 0.01, "usd_per_mt", "Checks tolerance: USD 0.01/t on term-structure prices"),
]


def write(wb, counts, data: sources.Data) -> dict:
    sh = Sheet(wb, SHEET, "Inputs — assumptions register (config/params/*.yaml) and workbook constants", counts,
               subtitle="blue = input you may change · black = formula · green = pasted Python output (checks only). "
                        "Flags: DIRECT = observed from a named public source, PROXY = a real observable standing in, "
                        "ASSUMPTION = a judgement.")

    sh.section("1. Scalar parameters — change a blue value and every sheet that uses it moves")
    rows = sources.param_rows()
    t = sh.table(PARAM_COLS)
    for i, r in enumerate(rows):
        v = r["value"]
        t.write_row(i, {
            "key": r["key"],
            "value": _excel_value(v),
            "unit": r["unit"], "flag": r["flag"], "named_range": r["named_range"], "file": r["file"],
            "source": r["source"], "verify": r["verify"], "note": r["note"],
        })
    t.freeze("value")
    t.autofilter()

    for i, r in enumerate(rows):
        if r["named_range"]:
            wb.defined_names.add(DefinedName(r["named_range"], attr_text=f"{SHEET}!${t.col('value')}${t.first_row + i}"))
    n_scalars = len(rows)
    wb.defined_names.add(DefinedName("param_keys", attr_text=f"{SHEET}!${t.col('key')}${t.first_row}:"
                                                             f"${t.col('key')}${t.first_row + n_scalars - 1}"))
    wb.defined_names.add(DefinedName("param_values", attr_text=f"{SHEET}!${t.col('value')}${t.first_row}:"
                                                               f"${t.col('value')}${t.first_row + n_scalars - 1}"))
    sh.after(t)

    sh.section("2. Dated parameters — the register's own breakpoints; every sheet resolves them by formula")
    path_info = {}
    for key in sources.PATH_KEYS:
        meta = sources.path_meta(key)
        sh.note(f"{key}  ·  interp = {meta['interp']}  ·  {meta['unit']}  ·  {meta['flag']}  ·  {meta['source']}")
        sh.note(f"    verify: {meta['verify']}")
        pt = sh.table(PATH_COLS, gap=0)
        pr = sources.path_rows(key)
        for i, row in enumerate(pr):
            pt.write_row(i, {"date": row["date"], "value": row["value"]})
        dates_ref = (f"{SHEET}!${pt.col('date')}${pt.first_row}:${pt.col('date')}${pt.first_row + len(pr) - 1}")
        vals_ref = (f"{SHEET}!${pt.col('value')}${pt.first_row}:${pt.col('value')}${pt.first_row + len(pr) - 1}")
        wb.defined_names.add(DefinedName(f"pdates_{key}", attr_text=dates_ref))
        wb.defined_names.add(DefinedName(f"pvals_{key}", attr_text=vals_ref))
        path_info[key] = {"interp": meta["interp"], "n": len(pr), "dates": f"pdates_{key}", "values": f"pvals_{key}",
                          "first_cell": f"{SHEET}!${pt.col('date')}${pt.first_row}",
                          "last_cell": f"{SHEET}!${pt.col('date')}${pt.first_row + len(pr) - 1}"}
        sh.after(pt, gap=1)
    wb.defined_names.add(DefinedName("customs_fx_first", attr_text=path_info["customs_usdinr_import"]["first_cell"]))
    wb.defined_names.add(DefinedName("customs_fx_last", attr_text=path_info["customs_usdinr_import"]["last_cell"]))

    sh.section("3. Workbook constants — model structure and check tolerances, not market observations")
    ct = sh.table([Column("name", KEY, width=22), Column("value", INPUT, width=16),
                   Column("unit", KEY, width=18), Column("meaning", KEY, width=80)])
    for i, (name, value, unit, meaning) in enumerate(CONSTANTS):
        ct.write_row(i, {"name": name, "value": value, "unit": unit, "meaning": meaning})
        wb.defined_names.add(DefinedName(name, attr_text=f"{SHEET}!${ct.col('value')}${ct.first_row + i}"))
    sh.after(ct)

    sh.section("4. Phase 3 book parameters served from code, not from the register")
    sh.note("`config/params/book.yaml` does not exist yet, so `desk.mtm.constants.BOOK_PARAM_FALLBACKS` supplies "
            "these (docs/design/30_position_model.md §14). They are shown separately so a code default can never be "
            "mistaken for a registered assumption; `pnl_controls.csv` lists every one the engine actually used.")
    bt = sh.table([Column("key", KEY, width=30), Column("value", INPUT, width=14), Column("unit", KEY, width=26),
                   Column("flag", KEY, width=12), Column("verify", KEY, width=44), Column("source", KEY, width=62),
                   Column("note", KEY, width=90)])
    fb = sources.book_fallback_rows()
    for i, r in enumerate(fb):
        bt.write_row(i, r)
        wb.defined_names.add(DefinedName(r["key"], attr_text=f"{SHEET}!${bt.col('value')}${bt.first_row + i}"))
    sh.after(bt)

    sh.section("5. MCX contract months present in the panel (contract month → panel expiry day)")
    sh.note("Derived from data/processed/market_daily.csv columns mcx_m1_expiry / mcx_m2_expiry; the panel expiry "
            "slot is what the Phase 3 engine carries a price to (docs/design/30_position_model.md §5.2).")
    mt = sh.table([Column("contract_month", KEY, width=16), Column("panel_expiry", INPUT, width=14)])
    months = _contract_months(data)
    for i, (m, d) in enumerate(months):
        mt.write_row(i, {"contract_month": m, "panel_expiry": d})
    wb.defined_names.add(DefinedName("mcx_months", attr_text=f"{SHEET}!${mt.col('contract_month')}${mt.first_row}:"
                                                             f"${mt.col('contract_month')}${mt.first_row + len(months) - 1}"))
    wb.defined_names.add(DefinedName("mcx_expiries", attr_text=f"{SHEET}!${mt.col('panel_expiry')}${mt.first_row}:"
                                                               f"${mt.col('panel_expiry')}${mt.first_row + len(months) - 1}"))
    sh.after(mt)

    return {"paths": path_info, "n_scalars": n_scalars, "n_months": len(months)}


def _contract_months(data: sources.Data) -> list[tuple[int, dt.date]]:
    pairs: dict[int, dt.date] = {}
    for col_exp in ("mcx_m1_expiry", "mcx_m2_expiry"):
        for e in data.panel[col_exp].dropna().unique():
            ts = __import__("pandas").Timestamp(e)
            pairs[ts.year * 100 + ts.month] = ts.date()
    return sorted(pairs.items())


def _excel_value(v):
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return v
