"""`Equity_Curve` — the book's cumulative P&L day by day, assembled by formula, with a native Excel chart.

The curve is not a pasted series. Each day's cumulative P&L is the CONTRACTS §7.3 identity computed in the sheet:

    cum P&L(t) = realised cash P&L to t  +  funding accrued to t  +  mark-to-market of everything still open

* **realised cash P&L** is a `SUMIFS` over the `Cashflows` ledger — every PNL flow whose settle date is on or before
  `t`, valued at the FX rate that sheet derives. Change a cashflow and the curve moves.
* **funding accrued** is carried from the engine (green): it is a day-by-day walk of each trade's own dated cash
  balance at `wc_rate_inr_pa`, which a flat sheet cannot express.
* **open MTM** is carried from the engine on every panel day, and on the marking grid it is *also* recomputed from
  `MTM_Daily` and the two are differenced — so the carried series is checked wherever the workbook can check it.

The chart is a real Excel line chart on this data, not a picture: it redraws when an input changes.
"""

from __future__ import annotations

from openpyxl.chart import LineChart, Reference

from desk.excel import sources
from desk.excel.layout import KEY, PASTED, Column, Sheet

SHEET = "Equity_Curve"


def write(wb, counts, data: sources.Data, cf, mtm):
    sh = Sheet(wb, SHEET, "Equity_Curve — book cumulative P&L, rebuilt from the ledger every day", counts,
               subtitle="cum P&L = realised cash P&L (formula, from Cashflows) + funding accrued (carried) "
                        "+ open MTM (carried; re-derived from MTM_Daily on the marking grid).")
    a = data.attribution
    book = a[a["trade_id"] == "BOOK"].sort_values("date").reset_index(drop=True)
    m = data.mtm
    funding = m[m["leg_type"] == "FUNDING"].groupby("date")["realised_cum_inr"].sum()
    open_mtm = m[m["pnl_class"] == "PNL"].groupby("date")["mtm_inr"].sum()
    marks = set(data.mark_dates)

    ledger = cf["ledger"]
    n_led = ledger.n_rows
    legs = mtm["legs"]
    n_legs = legs.n_rows

    cols = [Column("date", KEY, width=12), Column("in_window", KEY, width=10),
            Column("funding_cum_inr_py", PASTED, width=18), Column("mtm_open_inr_py", PASTED, width=18),
            Column("cum_pnl_inr_py", PASTED, width=18), Column("daily_pnl_inr_py", PASTED, width=18),
            Column("realised_pnl_cum_inr", width=19), Column("cum_pnl_calc_inr", width=19),
            Column("daily_pnl_calc_inr", width=19), Column("diff_cum_inr", width=15),
            Column("diff_daily_inr", width=15), Column("on_marking_grid", width=13),
            Column("mtm_open_from_mtm_sheet_inr", width=22), Column("diff_mtm_inr", width=15),
            Column("check", width=9)]
    t = sh.table(cols)
    for i, row in enumerate(book.itertuples(index=False)):
        R = lambda c: t.rowref(c, i)  # noqa: E731
        prev = f"${t.col('cum_pnl_calc_inr')}{t.first_row + i - 1}" if i else None
        d = row.date
        on_grid = d.date() in marks
        t.write_row(i, {
            "date": d.date(), "in_window": bool(row.in_window),
            "funding_cum_inr_py": float(funding.get(d, 0.0)),
            "mtm_open_inr_py": float(open_mtm.get(d, 0.0)),
            "cum_pnl_inr_py": float(row.cum_pnl_inr), "daily_pnl_inr_py": float(row.daily_pnl_inr),
            "realised_pnl_cum_inr":
                f'=SUMIFS({ledger.abs("amount_inr_calc", n_led)},{ledger.abs("pnl_class", n_led)},"PNL",'
                f'{ledger.abs("settle_date", n_led)},"<="&{R("date")})',
            "cum_pnl_calc_inr": f'={R("realised_pnl_cum_inr")}+{R("funding_cum_inr_py")}+{R("mtm_open_inr_py")}',
            "daily_pnl_calc_inr": (f'={R("cum_pnl_calc_inr")}-{prev}') if i else f'={R("cum_pnl_calc_inr")}',
            "diff_cum_inr": f'={R("cum_pnl_calc_inr")}-{R("cum_pnl_inr_py")}',
            "diff_daily_inr": f'={R("daily_pnl_calc_inr")}-{R("daily_pnl_inr_py")}',
            "on_marking_grid": on_grid,
            "mtm_open_from_mtm_sheet_inr":
                (f'=SUMIFS({legs.abs("mtm_inr_calc", n_legs)},{legs.abs("mark_date", n_legs)},{R("date")},'
                 f'{legs.abs("pnl_class", n_legs)},"PNL")') if on_grid else None,
            "diff_mtm_inr": (f'={R("mtm_open_from_mtm_sheet_inr")}-{R("mtm_open_inr_py")}') if on_grid else None,
            "check": f'=IF(ABS({R("diff_cum_inr")})<=tol_trade_inr,"PASS","FAIL")',
        })
    t.freeze("funding_cum_inr_py")
    n = t.n_rows

    chart = LineChart()
    chart.title = "Book cumulative P&L (₹) — ACADEMIC SIMULATION, not actual trades"
    chart.style = 2
    chart.height = 9
    chart.width = 26
    chart.y_axis.title = "cumulative P&L (INR)"
    chart.x_axis.title = "panel day"
    chart.x_axis.number_format = "yyyy-mm-dd"
    chart.x_axis.majorTimeUnit = "days"
    for col in ("cum_pnl_calc_inr", "realised_pnl_cum_inr", "cum_pnl_inr_py"):
        ref = Reference(sh.ws, min_col=_n(t.col(col)), min_row=t.header_row, max_row=t.first_row + n - 1)
        chart.add_data(ref, titles_from_data=True)
    cats = Reference(sh.ws, min_col=_n(t.col("date")), min_row=t.first_row, max_row=t.first_row + n - 1)
    chart.set_categories(cats)
    for s in chart.series:
        s.smooth = False
        s.marker.symbol = "none"
    sh.ws.add_chart(chart, f"A{t.first_row + n + 3}")
    sh.row = t.first_row + n + 22
    return t


def _n(letter: str) -> int:
    from openpyxl.utils import column_index_from_string

    return column_index_from_string(letter)
