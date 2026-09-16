"""Phase 3 stage: the master Excel workbook, formula-driven for Components 1–3 (MASTER_SPEC Table 8.2).

    DESK_OFFLINE=1 .venv/bin/python -c "import desk.excel.build as m; m.main()"

Writes `outputs/excel/Metals_Desk_Master.xlsx` and `docs/35_excel_workbook.md`. Reads only published files
(`data/processed/`, `config/`, `outputs/tables/`) and the parameter register, so it can be re-run at any time and is
byte-for-byte deterministic: the workbook is re-zipped with fixed entry timestamps and fixed document properties,
because an .xlsx is a zip and a zip records the clock.

What "formula-driven" means here, precisely — the same statement `docs/35_excel_workbook.md` opens with:

* **Components 1 and 2 are fully live.** Parity, both Table 1.5 sensitivity grids and the Table 1.7 term structure
  contain no computed constants at all; the trade tickets and counterparties are inputs, as they are in `config/`.
* **Component 3 is live at the leg level on a declared marking grid.** Per-leg valuations, the FX conversion of
  every USD flow, the MCX variation-margin and initial-margin schedule, the FX-forward marks and the unsold-cargo
  replacement mark are Excel formulas; per-trade and per-book cumulative P&L is assembled from them by formula.
  Leg *amounts* that come out of the ticket lifecycle (dates rolled on the panel calendar, quotational-period
  averages, survey outcomes) are pasted and labelled green, and the eight-step sequential attribution chain is
  reproduced only on two worked legs — §7 of the methods doc says exactly why and shows the Python value alongside.
* **GARCH, Monte Carlo and credit scoring stay in Python** (MASTER_SPEC Table 8.2).
"""

from __future__ import annotations

import datetime as dt
import io
import re
import zipfile

from openpyxl import Workbook

from desk.excel import (doc, sheet_attribution, sheet_cashflows, sheet_checks, sheet_counterparties, sheet_equity,
                        sheet_inputs, sheet_market, sheet_mtm, sheet_parity, sheet_readme, sheet_sensitivity,
                        sheet_term, sheet_trade_book, sources)
from desk.excel.layout import Counts
from desk.paths import DOCS_DIR, EXCEL_DIR, ensure_dirs

WORKBOOK = EXCEL_DIR / "Metals_Desk_Master.xlsx"
DOC_PATH = DOCS_DIR / "35_excel_workbook.md"

# Determinism: an .xlsx is a zip, and a zip stores a timestamp per entry. Fix both that and the document properties.
ZIP_TIMESTAMP = (2022, 3, 7, 0, 0, 0)          # desk.RNG_SEED as a date: the LME all-time high
DOC_TIMESTAMP = dt.datetime(2022, 3, 7, 0, 0, 0)
CREATOR = "desk.excel.build (Virtual Metals Trading Desk — ACADEMIC SIMULATION)"


def build() -> tuple[Workbook, Counts, dict]:
    data = sources.load()
    counts = Counts()
    wb = Workbook()
    wb.remove(wb.active)

    ctx: dict = {"data": data, "counts": counts}
    readme = sheet_readme.reserve(wb, counts)
    ctx["inputs"] = sheet_inputs.write(wb, counts, data)
    ctx["md"] = sheet_market.write_daily(wb, counts, data, ctx["inputs"]["paths"])
    ctx["mw"] = sheet_market.write_weekly(wb, counts, data, ctx["md"])
    ctx["parity"], ctx["parity_order"] = sheet_parity.write(wb, counts, data, ctx["mw"])
    ctx["sens"] = sheet_sensitivity.write(wb, counts, data, ctx["parity"], ctx["mw"])
    ctx["term"] = sheet_term.write(wb, counts, data, ctx["md"])
    ctx["cps"] = sheet_counterparties.write(wb, counts, data)
    ctx["book"] = sheet_trade_book.write(wb, counts, data, ctx["parity"])
    ctx["cf"] = sheet_cashflows.write(wb, counts, data, ctx["md"])
    ctx["mtm"] = sheet_mtm.write(wb, counts, data, ctx["md"], ctx["cf"])
    ctx["attr"] = sheet_attribution.write(wb, counts, data, ctx["md"])
    ctx["equity"] = sheet_equity.write(wb, counts, data, ctx["cf"], ctx["mtm"])
    ctx["checks"] = sheet_checks.write(wb, counts, data, ctx)
    sheet_readme.fill(readme, counts, ctx)
    return wb, counts, ctx


def save(wb: Workbook, path=WORKBOOK) -> str:
    """Save deterministically: fixed document properties, then re-zip with fixed per-entry timestamps."""
    wb.properties.creator = CREATOR
    wb.properties.lastModifiedBy = CREATOR
    wb.properties.created = DOC_TIMESTAMP
    wb.properties.modified = DOC_TIMESTAMP
    wb.properties.title = "Metals Desk Master — ACADEMIC SIMULATION"
    # openpyxl writes formulas with no cached results, so tell Excel to recalculate the whole book when it opens it.
    wb.calculation.fullCalcOnLoad = True
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    with zipfile.ZipFile(buf) as src, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as out:
        for name in src.namelist():
            data = src.read(name)
            if name == "docProps/core.xml":
                data = _fix_modified(data)
            info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            out.writestr(info, data)
    return str(path)


def _fix_modified(core_xml: bytes) -> bytes:
    """openpyxl stamps `dcterms:modified` with the wall clock as it writes; replace it with the fixed timestamp."""
    stamp = DOC_TIMESTAMP.strftime("%Y-%m-%dT%H:%M:%SZ").encode()
    # a function replacement, not a template: the stamp starts with digits and would be read as a group number
    return re.sub(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                  lambda m: m.group(1) + stamp + m.group(2), core_xml)


def main() -> None:
    ensure_dirs()
    EXCEL_DIR.mkdir(parents=True, exist_ok=True)
    wb, counts, ctx = build()
    save(wb)
    DOC_PATH.write_text(doc.render(counts, ctx), encoding="utf-8")


if __name__ == "__main__":
    main()
