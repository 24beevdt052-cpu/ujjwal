"""`Checks` — every workbook result differenced against the Python output that produced the published tables.

The rule is simple: a formula is only worth anything if something checks it. Each block pastes the engine's value in
green, references the workbook's own formula cell, shows the difference and raises a PASS/FAIL against a named
tolerance from `Inputs`. The scoreboard at the top is a formula over the blocks, so it cannot be stale.

Tolerances and why they are what they are:

| Family | Tolerance | Why not tighter |
|---|---|---|
| Parity line items, per row | ₹1 per tonne (`tol_parity_inr_t`) | the brief's tolerance; the published CSV rounds to 2 dp |
| Sensitivity grid cells | ₹10 on 1,000 MT (`tol_grid_inr`) | ₹0.01/t of rounding × 1,000 t |
| Per-trade MTM and cumulative P&L | ₹10 per trade (`tol_trade_inr`) | the brief's tolerance |
| Cash-ledger rows | ₹1 (`tol_cashflow_inr`) | `amount_ccy` is published to 2 dp, so an INR re-derivation cannot tie closer |
| MCX margin rows | ₹1 (`tol_mcx_inr`) | the margin schedule is rebuilt from the import-parity price the engine itself marks at (design D4), not from the 4-dp panel column, so it ties to the paisa |
| Term structure | USD 0.01/t (`tol_usd_t`) | published to 4 dp |

One tie the workbook cannot make directly is the Phase 1 ↔ Phase 3 replacement-value control: the engine asserts
`R = goods + bcd + sws + port` on every parity **value date**, and the workbook's marking grid is month-ends, which
are not parity value dates. The chain here is workbook `replacement_inr_t` ↔ engine `px_inr_t` (checked on every
`INVENTORY` row) ↔ Phase 1 (checked in `pnl_controls.csv`), and that is stated rather than papered over.
"""

from __future__ import annotations

import pandas as pd

from desk import HORIZON_END, WINDOW_END
from desk.reporting.style import PNL_BUCKETS
from desk.excel import sources, style
from desk.excel.layout import KEY, PASTED, Column, Sheet, Table

SHEET = "Checks"
N_FAMILIES = 7   # parity, grid (a), grid (b), term structure, per-trade P&L, factors, structural


def write(wb, counts, data: sources.Data, ctx: dict):
    sh = Sheet(wb, SHEET, "Checks — workbook formulas differenced against the Python engine", counts,
               subtitle="Green = the published Python value. Black = the workbook's own formula, referenced from its "
                        "sheet. Every family carries a named tolerance from Inputs.")
    blocks: list[dict] = []

    score_row = sh.row + 1
    sh.row = score_row + N_FAMILIES + 4   # rows reserved for the scoreboard, filled in once the blocks exist

    sh.section("1. Parity — CONTRACTS §5 net arb and the two §5a cases, every row")
    blocks.append(_parity(sh, data, ctx))
    sh.section("2. Sensitivity — Table 1.5(a) LME × USD/INR, every grid cell")
    blocks.append(_grid(sh, data, ctx, "lme_fx", data.grid_lme_fx,
                        ["ref_case", "lme_shock_pct", "usdinr"], "grid_lme_fx"))
    sh.section("3. Sensitivity — Table 1.5(b) freight × BCD, every grid cell")
    blocks.append(_grid(sh, data, ctx, "freight_duty", data.grid_freight_duty,
                        ["ref_case", "freight_terms", "freight_shock_pct", "bcd_rate_pct"], "grid_freight_duty"))
    sh.section("4. Term structure — the implied M+1 average of LME cash, every week")
    blocks.append(_term(sh, data, ctx))
    sh.section("5. Per-trade cumulative P&L at WINDOW_END and HORIZON_END")
    blocks.append(_trades(sh, data, ctx))
    sh.section("6. Book P&L by factor — lifetime")
    blocks.append(_factors(sh, data, ctx))
    sh.section("7. Structural controls carried from other sheets")
    blocks.append(_structural(sh, data, ctx))

    _scoreboard(sh, score_row, blocks)
    return {"blocks": blocks, "score_row": score_row}


# ------------------------------------------------------------------------------------------------ scoreboard
SUMMARY_COLS = [Column("family", KEY, width=46), Column("n_rows", KEY, width=9),
                Column("tolerance", KEY, width=18), Column("max_abs_diff", width=18),
                Column("n_fail", width=9), Column("status", width=10)]


def _scoreboard(sh: Sheet, row: int, blocks: list[dict]) -> None:
    sh.section_at(row - 1, "Scoreboard — recomputed from the blocks below")
    t = Table(sh, SUMMARY_COLS, row)
    for i, b in enumerate(blocks):
        R = lambda c: t.rowref(c, i)  # noqa: E731
        diff = b["diff_range"]
        chk = b["check_range"]
        t.write_row(i, {
            "family": b["family"], "n_rows": b["n"], "tolerance": b["tolerance"],
            "max_abs_diff": f"=MAX(MAX({diff}),-MIN({diff}))",
            "n_fail": f'=COUNTIF({chk},"FAIL")',
            "status": f'=IF({R("n_fail")}=0,"PASS","FAIL")',
        })
    t.n_rows = len(blocks)
    sh.section_at(row + len(blocks) + 1, "ALL CHECKS")
    c = sh.put(row + len(blocks) + 1, 2, f'=IF(SUM({t.abs("n_fail")})=0,"PASS","FAIL")', kind="formula")
    c.fill = style.PASS_FILL


def _finish(t: Table, family: str, tolerance: str, n: int) -> dict:
    t.n_rows = n
    return {"family": family, "n": n, "tolerance": tolerance,
            "diff_range": t.abs("diff", n), "check_range": t.abs("check", n), "table": t}


# ------------------------------------------------------------------------------------------------ blocks
def _parity(sh: Sheet, data, ctx) -> dict:
    parity_t = ctx["parity"]
    order = ctx["parity_order"]
    pw = data.parity.set_index(["week_end", "grade", "lane"])
    cols = [Column("week_end", KEY, width=12), Column("grade", KEY, width=13), Column("lane", KEY, width=11),
            Column("py_net_arb_inr_t", PASTED, width=17), Column("py_net_arb_pit_inr_t", PASTED, width=19),
            Column("py_net_arb_conv18k_inr_t", PASTED, width=21), Column("py_landed_inr_t", PASTED, width=17),
            Column("xl_net_arb_inr_t", width=17), Column("xl_net_arb_pit_inr_t", width=19),
            Column("xl_net_arb_conv18k_inr_t", width=21), Column("xl_landed_inr_t", width=17),
            Column("diff", width=13), Column("diff_pit", width=13), Column("diff_conv18k", width=14),
            Column("diff_landed", width=13), Column("check", width=9)]
    t = sh.table(cols)
    for i, key in enumerate(order):
        we, grade, lane = pd.Timestamp(key.week_end), key.grade, key.lane
        src = pw.loc[(we, grade, lane)]
        P = lambda c: f"{parity_t.sheet.name}!${parity_t.col(c)}${parity_t.first_row + i}"  # noqa: E731
        R = lambda c: t.rowref(c, i)  # noqa: E731
        t.write_row(i, {
            "week_end": we.date(), "grade": grade, "lane": lane,
            "py_net_arb_inr_t": float(src["net_arb_inr_t"]),
            "py_net_arb_pit_inr_t": float(src["net_arb_pit_mix_inr_t"]),
            "py_net_arb_conv18k_inr_t": float(src["net_arb_conv18k_inr_t"]),
            "py_landed_inr_t": float(src["landed_inr_t"]),
            "xl_net_arb_inr_t": f"={P('net_arb_inr_t')}",
            "xl_net_arb_pit_inr_t": f"={P('net_arb_pit_mix_inr_t')}",
            "xl_net_arb_conv18k_inr_t": f"={P('net_arb_conv18k_inr_t')}",
            "xl_landed_inr_t": f"={P('landed_inr_t')}",
            "diff": f'={R("xl_net_arb_inr_t")}-{R("py_net_arb_inr_t")}',
            "diff_pit": f'={R("xl_net_arb_pit_inr_t")}-{R("py_net_arb_pit_inr_t")}',
            "diff_conv18k": f'={R("xl_net_arb_conv18k_inr_t")}-{R("py_net_arb_conv18k_inr_t")}',
            "diff_landed": f'={R("xl_landed_inr_t")}-{R("py_landed_inr_t")}',
            "check": f'=IF(AND(ABS({R("diff")})<=tol_parity_inr_t,ABS({R("diff_pit")})<=tol_parity_inr_t,'
                     f'ABS({R("diff_conv18k")})<=tol_parity_inr_t,ABS({R("diff_landed")})<=tol_parity_inr_t),'
                     f'"PASS","FAIL")',
        })
    out = _finish(t, "Parity — net arb, §5a cases and landed cost (every week × grade × lane)",
                  "tol_parity_inr_t = ₹1/t", len(order))
    sh.after(t)
    return out


def _grid(sh: Sheet, data, ctx, which: str, frame: pd.DataFrame, keys: list[str], label: str) -> dict:
    grid_t = ctx["sens"][which]
    refs = list(data.refs["ref_case"])
    ordered = pd.concat([frame[frame["ref_case"] == r] for r in refs], ignore_index=True)
    cols = [Column(k, KEY, width=15) for k in keys]
    cols += [Column("py_pnl_impact_1000mt_inr", PASTED, width=22),
             Column("xl_pnl_impact_1000mt_inr", width=22), Column("diff", width=13), Column("check", width=9)]
    t = sh.table(cols)
    for i, row in enumerate(ordered.itertuples(index=False)):
        G = lambda c: f"{grid_t.sheet.name}!${grid_t.col(c)}${grid_t.first_row + i}"  # noqa: E731
        R = lambda c: t.rowref(c, i)  # noqa: E731
        vals = {k: _key_value(row, k) for k in keys}
        vals.update({
            "py_pnl_impact_1000mt_inr": float(row.pnl_impact_1000mt_inr),
            "xl_pnl_impact_1000mt_inr": f"={G('pnl_impact_1000mt_inr')}",
            "diff": f'={R("xl_pnl_impact_1000mt_inr")}-{R("py_pnl_impact_1000mt_inr")}',
            "check": f'=IF(ABS({R("diff")})<=tol_grid_inr,"PASS","FAIL")',
        })
        t.write_row(i, vals)
    out = _finish(t, f"Sensitivity grid {label} — P&L impact on 1,000 MT", "tol_grid_inr = ₹10", len(ordered))
    sh.after(t)
    return out


def _key_value(row, k):
    v = getattr(row, k)
    if isinstance(v, pd.Timestamp):
        return v.date()
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def _term(sh: Sheet, data, ctx) -> dict:
    tt = ctx["term"]["weekly"]
    cols = [Column("week_end", KEY, width=12), Column("mplus1_month", KEY, width=13),
            Column("py_implied_avg_usd_t", PASTED, width=20), Column("xl_implied_avg_usd_t", width=20),
            Column("py_realised_avg_usd_t", PASTED, width=20), Column("xl_realised_avg_usd_t", width=20),
            Column("diff", width=13), Column("diff_realised", width=14), Column("check", width=9)]
    t = sh.table(cols)
    tw = data.term_weekly
    for i, row in enumerate(tw.itertuples(index=False)):
        T = lambda c: f"{tt.sheet.name}!${tt.col(c)}${tt.first_row + i}"  # noqa: E731
        R = lambda c: t.rowref(c, i)  # noqa: E731
        t.write_row(i, {
            "week_end": row.week_end.date(), "mplus1_month": str(row.mplus1_month),
            "py_implied_avg_usd_t": float(row.mplus1_implied_avg_cash_usd_t),
            "xl_implied_avg_usd_t": f"={T('mplus1_implied_avg_cash_usd_t')}",
            "py_realised_avg_usd_t": float(row.hindsight_realised_mplus1_avg_cash_usd_t),
            "xl_realised_avg_usd_t": f"={T('hindsight_realised_mplus1_avg_cash_usd_t')}",
            "diff": f'={R("xl_implied_avg_usd_t")}-{R("py_implied_avg_usd_t")}',
            "diff_realised": f'={R("xl_realised_avg_usd_t")}-{R("py_realised_avg_usd_t")}',
            "check": f'=IF(AND(ABS({R("diff")})<=tol_usd_t,ABS({R("diff_realised")})<=tol_usd_t),"PASS","FAIL")',
        })
    out = _finish(t, "Term structure — implied and realised M+1 average of LME cash", "tol_usd_t = USD 0.01/t",
                  len(tw))
    sh.after(t)
    return out


def _trades(sh: Sheet, data, ctx) -> dict:
    cum = ctx["mtm"]["cum"]
    trades = sorted(data.trade_book["trade_id"])
    marks = list(data.mark_dates)
    want = [d for d in (WINDOW_END, HORIZON_END) if d in marks]
    cols = [Column("mark_date", KEY, width=12), Column("trade_id", KEY, width=10),
            Column("py_cum_pnl_inr", PASTED, width=20), Column("xl_cum_pnl_inr", width=20),
            Column("xl_realised_inr", width=20), Column("xl_mtm_open_inr", width=20),
            Column("diff", width=14), Column("check", width=9)]
    t = sh.table(cols)
    attr = data.attribution.set_index(["date", "trade_id"])["cum_pnl_inr"].to_dict()
    i = 0
    for d in want:
        base = marks.index(d) * len(trades)
        for j, trade in enumerate(trades):
            k = base + j
            C = lambda c: f"{cum.sheet.name}!${cum.col(c)}${cum.first_row + k}"  # noqa: E731
            R = lambda c: t.rowref(c, i)  # noqa: E731
            t.write_row(i, {
                "mark_date": d, "trade_id": trade,
                "py_cum_pnl_inr": float(attr.get((pd.Timestamp(d), trade), 0.0)),
                "xl_cum_pnl_inr": f"={C('cum_pnl_calc_inr')}",
                "xl_realised_inr": f"={C('realised_pnl_cum_inr')}",
                "xl_mtm_open_inr": f"={C('mtm_open_inr')}",
                "diff": f'={R("xl_cum_pnl_inr")}-{R("py_cum_pnl_inr")}',
                "check": f'=IF(ABS({R("diff")})<=tol_trade_inr,"PASS","FAIL")',
            })
            i += 1
    out = _finish(t, "Per-trade cumulative P&L at WINDOW_END and HORIZON_END", "tol_trade_inr = ₹10", i)
    sh.after(t)
    return out


def _factors(sh: Sheet, data, ctx) -> dict:
    life = ctx["attr"]["lifetime"]
    daily = ctx["attr"]["daily"]
    n_trades = life.n_rows - 1
    book_row = life.first_row + n_trades  # the BOOK (Σ trades) row written by sheet_attribution
    a = data.attribution
    book = a[a["trade_id"] == "BOOK"]
    cols = [Column("bucket", KEY, width=26), Column("py_lifetime_inr", PASTED, width=20),
            Column("xl_sum_trades_inr", width=20), Column("xl_sum_book_daily_inr", width=22),
            Column("diff", width=14), Column("diff_daily", width=14), Column("check", width=9)]
    t = sh.table(cols)
    for i, b in enumerate(PNL_BUCKETS + ["residual"]):
        R = lambda c: t.rowref(c, i)  # noqa: E731
        t.write_row(i, {
            "bucket": b, "py_lifetime_inr": float(book[b].sum()),
            "xl_sum_trades_inr": f"={life.sheet.name}!${life.col(b)}${book_row}",
            "xl_sum_book_daily_inr": f"=SUM({daily.abs(b)})",
            "diff": f'={R("xl_sum_trades_inr")}-{R("py_lifetime_inr")}',
            "diff_daily": f'={R("xl_sum_book_daily_inr")}-{R("py_lifetime_inr")}',
            "check": f'=IF(AND(ABS({R("diff")})<=tol_trade_inr,ABS({R("diff_daily")})<=tol_trade_inr),'
                     f'"PASS","FAIL")',
        })
    out = _finish(t, "Book P&L by factor — lifetime, Σ trades and Σ book-days", "tol_trade_inr = ₹10",
                  len(PNL_BUCKETS) + 1)
    sh.after(t)
    return out


def _structural(sh: Sheet, data, ctx) -> dict:
    md = ctx["md"]
    cf = ctx["cf"]
    mtm = ctx["mtm"]
    eq = ctx["equity"]
    attrd = ctx["attr"]["daily"]
    mcx_chain = ctx["attr"]["mcx_chain"]
    fx_chain = ctx["attr"]["fx_chain"]
    book_t = ctx["book"]["tickets"]
    inv_n = mtm["legs"].n_rows
    rows = [
        ("Cross-exchange basis is zero by construction on every PROXY panel day (design D4)",
         f'=MAX(MAX({md.abs("mcx_basis_m1_inr_kg")}),-MIN({md.abs("mcx_basis_m1_inr_kg")}))', "1e-3 ₹/kg", 0.001),
        ("Cash ledger — every dated flow re-derived in INR",
         f'=MAX(MAX({cf["ledger"].abs("diff_inr")}),-MIN({cf["ledger"].abs("diff_inr")}))', "tol_cashflow_inr", None),
        ("MCX margin schedule — variation margin, initial margin and net margin cash",
         f'=MAX(MAX({cf["mcx"].abs("diff_net_margin_inr")}),-MIN({cf["mcx"].abs("diff_net_margin_inr")}))',
         "tol_mcx_inr", None),
        ("Leg marks on the marking grid (replacement value, FX forwards, carried amounts)",
         f'=MAX(MAX({mtm["legs"].abs("diff_inr", inv_n)}),-MIN({mtm["legs"].abs("diff_inr", inv_n)}))',
         "tol_trade_inr", None),
        ("Book equity curve — cum P&L identity every panel day",
         f'=MAX(MAX({eq.abs("diff_cum_inr")}),-MIN({eq.abs("diff_cum_inr")}))', "tol_trade_inr", None),
        ("Attribution — Σ buckets + residual = daily P&L, every book-day",
         f'=MAX(MAX({attrd.abs("diff_vs_daily_inr")}),-MIN({attrd.abs("diff_vs_daily_inr")}))',
         "tol_trade_inr", None),
        ("Worked chain (a) — short MCX hedge, 07→08-Mar-2022, vs desk.mtm.curves",
         f'=MAX(MAX({mcx_chain.abs("diff_inr")}),-MIN({mcx_chain.abs("diff_inr")}))', "tol_trade_inr", None),
        ("Worked chain (b) — USD payable vs its forward, vs desk.mtm.curves",
         f'=MAX(MAX({fx_chain.abs("diff_inr")}),-MIN({fx_chain.abs("diff_inr")}))', "tol_trade_inr", None),
        ("Trade discipline — live §5a eligibility equals the flag Phase 2 recorded",
         f'=COUNTIF({book_t.abs("eligible_matches_book")},"FAIL")', "0 failures", 0.0),
    ]
    cols = [Column("control", KEY, width=76), Column("max_abs_diff", width=20),
            Column("tolerance_name", KEY, width=20), Column("diff", width=16), Column("check", width=9)]
    t = sh.table(cols)
    for i, (name, formula, tol_label, tol_value) in enumerate(rows):
        R = lambda c: t.rowref(c, i)  # noqa: E731
        tol = str(tol_value) if tol_value is not None else tol_label
        t.write_row(i, {
            "control": name, "max_abs_diff": formula, "tolerance_name": tol_label,
            "diff": f'={R("max_abs_diff")}',
            "check": f'=IF(ABS({R("diff")})<={tol},"PASS","FAIL")',
        })
    out = _finish(t, "Structural controls (basis, ledger, margin, marks, equity, attribution, discipline)",
                  "per row", len(rows))
    sh.after(t)
    return out
