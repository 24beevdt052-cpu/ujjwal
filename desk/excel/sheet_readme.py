"""`README` — the first sheet: what each sheet is, the colour legend, the provenance legend, and how to drive it.

Written in two passes. `reserve` creates the sheet first so it lands at position 1 in the tab order; `fill` writes
the map once every other sheet exists, so the row counts and formula-coverage numbers on it are the real ones.
"""

from __future__ import annotations

from desk import DESK_NAME, HORIZON_END, SIM_LABEL, WINDOW_END, WINDOW_START
from desk.excel import style
from desk.excel.layout import FORMULA, INPUT, KEY, PASTED, Column, Counts, Sheet, Table

SHEET = "README"

SHEET_MAP = [
    ("README", "this page", "Sheet map, colour and provenance legends, how to use the workbook in an interview."),
    ("Inputs", "register", "Every parameter Components 1–3 read, with unit, flag, source and verification status. "
                           "Scalars carry named ranges; dated parameters are the register's own breakpoints and are "
                           "resolved by formula. Change a blue cell here and the whole workbook moves."),
    ("Market_Daily", "panel", "One row per LME trading day, 2022-01-03 → 2022-12-30: LME cash/3M/spread/stock, "
                              "USD/INR and the 3-month rates, the MCX slots and their expiries, freight per lane. "
                              "Four derived columns are formulas — contract months, the dated parameters resolved "
                              "on the day, and the MCX parity price with its basis."),
    ("Market_Weekly", "panel", "The CONTRACTS §3 weekly view (W-FRI, valued on the week's last panel day). Every "
                               "cell is an INDEX/MATCH into Market_Daily."),
    ("Parity", "Component 1", "CONTRACTS §5 per MT of scrap, line by line, for every week × grade × lane, plus the "
                              "three §5a eligibility flags. No computed value is pasted."),
    ("Sensitivity", "Component 1", "The two MASTER_SPEC Table 1.5 grids on 1,000 MT: LME × USD/INR, and freight × "
                                   "import duty under both FOB and CFR terms. Each cell re-derives the whole "
                                   "build-up at the shocked market."),
    ("Term_Structure", "Component 1", "Table 1.7: Cash–3M weekly, the M+1 pricing basis implied by the curve, the "
                                      "realised M+1 average (labelled HINDSIGHT), and the MCX M1 → M2 roll."),
    ("Counterparties", "Component 2", "The SIM supplier and buyer register with credit limits and the Phase 5 "
                                      "profile features."),
    ("Trade_Book", "Component 2", "The nine SPA tickets and the hedge stack. Ticket fields are inputs; the §5a "
                                  "eligibility of each trade is re-tested live against the Parity sheet."),
    ("Cashflows", "Component 3", "The dated cash ledger with its FX conversion derived per settle date, and the MCX "
                                 "margin schedule (variation margin, initial margin, slippage and charges) derived "
                                 "end to end from Market_Daily."),
    ("MTM_Daily", "Component 3", "Leg valuations on the declared marking grid, including the unsold-cargo "
                                 "replacement mark and the FX-forward marks, and per-trade cumulative P&L."),
    ("Attribution", "Component 3", "The daily bucket identities recomputed in Excel, lifetime P&L by trade and "
                                   "factor, and the eight-step attribution chain worked live on two legs."),
    ("Equity_Curve", "Component 3", "Book cumulative P&L every panel day, assembled by formula, with a native Excel "
                                    "line chart."),
    ("Checks", "controls", "Every workbook result differenced against the Python engine, with a named tolerance and "
                           "a PASS flag. Start here."),
]

COLOUR_LEGEND = [
    ("blue", INPUT, "An input you may change: a register parameter, a ticket field, a market print. "
                    "Everything downstream re-computes."),
    ("black", FORMULA, "An Excel formula. Never typed — derived from blue cells and other formulas."),
    ("green", PASTED, "A value produced by the Python engine and pasted here. Two kinds, and the sheets say which: "
                      "*check* columns that nothing depends on, and *carried* columns (a leg amount out of the "
                      "ticket lifecycle) that a formula then converts and aggregates. `value_src` / `amount_src` "
                      "name them row by row."),
    ("dark grey", KEY, "A row key or a label — a date, an id, a provenance flag, a source string."),
]

PROVENANCE_LEGEND = [
    ("DIRECT", "Observed from a named public source. Here: LME cash / 3M / spread / stock (Westmetall, which "
               "republishes LME official prices); the RBI and Fed policy-rate step paths; BCD, SWS and IGST on "
               "HS 7602 and the CBIC notified import rate; MCX contract specifications."),
    ("PROXY", "A real observable standing in for the thing we need, or a transformation of real data. Here: "
              "USD/INR (the ECB EUR/INR ÷ EUR/USD cross, standing in for the RBI/FBIL reference rate — "
              "PENDING a measured comparison); the 3-month rates and the covered-interest-parity forwards; the "
              "MCX panel series, which is duty-paid import parity and therefore has **zero cross-exchange basis "
              "by construction**; the Drewry WCI freight shape."),
    ("ASSUMPTION", "A judgement, with a justification in the register. Here: the freight *levels* and the lag-2 "
                   "grade mix (both hindsight reconstructions); container payloads; port and conversion costs; the "
                   "domestic anchor premium; the working-capital rate; every Phase 3 book parameter still served "
                   "from code."),
    ("SIM", "Simulated. Every counterparty, vessel, voyage, forwarder, bank, survey outcome, dwell day and payment "
            "delay in this workbook is fictional and its name ends \"(SIM)\"."),
]

HOW_TO = [
    ("Prove the parity is live",
     "Inputs → change `bcd_scrap_hs7602` from 0.025 to 0.05. Watch Parity `bcd_inr_t`, `landed_inr_t` and "
     "`net_arb_inr_t` move on all 258 rows, `trade_eligible` flip on the marginal weeks, and Trade_Book "
     "`parity_eligible_live` follow. Then undo it — Checks will go red until you do, which is the point."),
    ("Prove the P&L is live",
     "Market_Daily → change a `usdinr` print. Cashflows re-converts every USD flow settling that day, MTM_Daily "
     "re-prices the replacement mark and the FX forwards, and the Equity_Curve chart redraws."),
    ("Show the hedge is not a fake",
     "Attribution §3a: the short MCX hedge on the day the LME broke from its all-time high. (a) is the whole move, "
     "(b) the cross-exchange basis is **zero**, (e) is small and negative because a short MCX position is short "
     "USD, and (g) is the carry. §3b shows a USD payable and its forward cancelling in (e) and (g)."),
    ("Show the discipline",
     "Trade_Book `parity_eligible_live` vs `book_trade_eligible`: each ticket is re-tested against the CONTRACTS "
     "§5a rule that was declared before any Phase 1 result existed."),
    ("Show the honesty",
     "Checks → the scoreboard, then Inputs §4: the Phase 3 parameters still served from code rather than from the "
     "register, listed with their flags."),
]


def reserve(wb, counts: Counts) -> Sheet:
    return Sheet(wb, SHEET, f"{DESK_NAME}", counts,
                 subtitle=f"{SIM_LABEL}.  Master workbook, formula-driven for Components 1–3.  "
                          f"Backtest window {WINDOW_START} → {WINDOW_END}; engine horizon {HORIZON_END}.")


def fill(sh: Sheet, counts: Counts, ctx: dict) -> None:
    sh.section("How to read a cell — the colour convention")
    t = Table(sh, [Column("colour", KEY, width=12), Column("meaning", KEY, width=118)], sh.row + 1)
    for i, (name, kind, meaning) in enumerate(COLOUR_LEGEND):
        t.write_row(i, {"colour": name, "meaning": meaning})
        sh.ws.cell(t.first_row + i, 1).font = {INPUT: style.INPUT_FONT, FORMULA: style.FORMULA_FONT,
                                               PASTED: style.PASTED_FONT, KEY: style.KEY_FONT}[kind]
    t.n_rows = len(COLOUR_LEGEND)
    sh.after(t)

    sh.section("Provenance — CONTRACTS §1.2. Every input on every sheet carries one of these flags")
    pt = Table(sh, [Column("flag", KEY, width=14), Column("meaning", KEY, width=118)], sh.row + 1)
    for i, (flag, meaning) in enumerate(PROVENANCE_LEGEND):
        pt.write_row(i, {"flag": flag, "meaning": meaning})
    pt.n_rows = len(PROVENANCE_LEGEND)
    sh.after(pt)

    sh.section("Sheet map")
    mt = Table(sh, [Column("sheet", KEY, width=17), Column("part", KEY, width=14),
                    Column("rows", KEY, width=8), Column("formula_cells", KEY, width=14),
                    Column("formula_share", KEY, width=14), Column("what it is", KEY, width=104)], sh.row + 1)
    for i, (name, part, what) in enumerate(SHEET_MAP):
        c = counts.per_sheet.get(name, {})
        total = sum(c.values())
        mt.write_row(i, {"sheet": name, "part": part,
                         "rows": _rows_of(name, ctx),
                         "formula_cells": c.get(FORMULA, 0),
                         "formula_share": f"{counts.ratio(name):.0%}" if total else "—",
                         "what it is": what})
    mt.n_rows = len(SHEET_MAP)
    sh.after(mt)

    sh.section("Five things to do with this workbook in an interview")
    ht = Table(sh, [Column("do this", KEY, width=30), Column("and it shows", KEY, width=118)], sh.row + 1)
    for i, (title, body) in enumerate(HOW_TO):
        ht.write_row(i, {"do this": title, "and it shows": body})
    ht.n_rows = len(HOW_TO)
    sh.after(ht)

    sh.section("What is NOT in this workbook, and why")
    nt = Table(sh, [Column("left in Python", KEY, width=34), Column("why", KEY, width=118)], sh.row + 1)
    rows = [
        ("GARCH VaR, Monte Carlo, credit scoring",
         "MASTER_SPEC Table 8.2 puts them in Python. A 10,000-path joint simulation and a fitted GARCH(1,1) are not "
         "spreadsheet objects, and a spreadsheet version would be a worse model pretending to be the same one."),
        ("The eight-step attribution chain, per trade-day",
         "It is eight full revaluations of every leg of every ticket, every day, each needing the ticket's lifecycle "
         "expansion. Attribution §3a and §3b show the mechanism exactly on two closed-form legs and tie them to "
         "`desk.mtm.curves`; the daily identities are re-checked on the published table."),
        ("Leg amounts out of the ticket lifecycle",
         "Quotational-period averages, survey outcomes and claim arithmetic, demurrage day counts, LC fee bases. "
         "These are date-and-contract computations on rolled panel calendars, not market arithmetic. They are green "
         "and marked PYTHON_LIFECYCLE; the market conversion applied to them is a formula."),
        ("Funding",
         "A day-by-day walk of each trade's own dated cash balance at `wc_rate_inr_pa`, including variation margin "
         "and the balance-sheet flows. It is carried and labelled on Equity_Curve and MTM_Daily."),
        ("Every panel day of MTM",
         "`mtm_daily.csv` is 28,343 date × trade × leg rows. The workbook values every open leg on a declared "
         "marking grid — month-ends, trade dates, the adverse-event endpoints, WINDOW_END and HORIZON_END — which "
         "is a rule fixed in code, not a selection made after seeing results."),
    ]
    for i, (a, b) in enumerate(rows):
        nt.write_row(i, {"left in Python": a, "why": b})
    nt.n_rows = len(rows)
    sh.after(nt)

    sh.note("Rebuild:  DESK_OFFLINE=1 .venv/bin/python -c \"import desk.excel.build as m; m.main()\"   ·   "
            "Reconciliation test:  DESK_OFFLINE=1 .venv/bin/python -m pytest -q tests/test_excel_reconciliation.py"
            "   ·   Methods: docs/35_excel_workbook.md")
    sh.note(SIM_LABEL + " — no number in this workbook is a record of a real trade, counterparty or vessel.")


def _rows_of(name: str, ctx: dict) -> str:
    counts = {
        "Market_Daily": ctx["md"].n_rows, "Market_Weekly": ctx["mw"].n_rows, "Parity": ctx["parity"].n_rows,
        "Sensitivity": ctx["sens"]["lme_fx"].n_rows + ctx["sens"]["freight_duty"].n_rows,
        "Term_Structure": ctx["term"]["weekly"].n_rows + ctx["term"]["rolls"].n_rows,
        "Counterparties": ctx["cps"].n_rows,
        "Trade_Book": ctx["book"]["tickets"].n_rows + ctx["book"]["hedges"].n_rows,
        "Cashflows": ctx["cf"]["ledger"].n_rows + ctx["cf"]["mcx"].n_rows,
        "MTM_Daily": ctx["mtm"]["legs"].n_rows + ctx["mtm"]["cum"].n_rows,
        "Attribution": ctx["attr"]["daily"].n_rows + ctx["attr"]["lifetime"].n_rows,
        "Equity_Curve": ctx["equity"].n_rows,
        "Checks": sum(b["n"] for b in ctx["checks"]["blocks"]),
    }
    return str(counts.get(name, ""))
