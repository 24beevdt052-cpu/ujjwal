"""Workbook look-and-feel and the colour convention every sheet obeys.

One convention, stated once here and printed on the README sheet, decides how a reader reads any cell:

* **blue** — an *input*: a register parameter, a ticket field or a market observation typed into the workbook.
  Change a blue cell and the workbook moves.
* **black** — a *formula*: derived inside Excel from blue cells and other formulas. Never typed.
* **green** — a *pasted Python output*, present only so a formula can be checked against it. Nothing depends on a
  green cell except a difference column.

Provenance (DIRECT / PROXY / ASSUMPTION / SIM) is carried as a text column, never as a colour, because a single cell
can be a blue input and a PROXY at the same time.
"""

from __future__ import annotations

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

# ------------------------------------------------------------------------------------------------ colour legend
INPUT_COLOR = "0000CC"      # blue  — typed input
FORMULA_COLOR = "000000"    # black — Excel formula
PASTED_COLOR = "008000"     # green — pasted Python output, for checks only
KEY_COLOR = "404040"        # dark grey — row keys (dates, ids); inputs in the technical sense, not model dials
NOTE_COLOR = "7F7F7F"

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
SUBHEADER_FILL = PatternFill("solid", fgColor="DBE5F1")
SIM_FILL = PatternFill("solid", fgColor="FFF2CC")
PASS_FILL = PatternFill("solid", fgColor="E2EFDA")
FAIL_FILL = PatternFill("solid", fgColor="FFC7CE")
BLOCK_FILL = PatternFill("solid", fgColor="F2F2F2")

THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

TITLE_FONT = Font(bold=True, size=13, color="1F4E79")
HEADER_FONT = Font(bold=True, size=9, color="FFFFFF")
SIM_FONT = Font(bold=True, size=9, color="7F6000")
NOTE_FONT = Font(size=8.5, color=NOTE_COLOR, italic=True)
SECTION_FONT = Font(bold=True, size=10, color="1F4E79")

INPUT_FONT = Font(size=9, color=INPUT_COLOR)
FORMULA_FONT = Font(size=9, color=FORMULA_COLOR)
PASTED_FONT = Font(size=9, color=PASTED_COLOR)
KEY_FONT = Font(size=9, color=KEY_COLOR, bold=False)

# ------------------------------------------------------------------------------------------------ number formats
FMT = {
    "date": "yyyy-mm-dd",
    "inr": "#,##0.00",
    "inr0": "#,##0",
    "inr_mn": "#,##0.00,,",
    "usd": "#,##0.0000",
    "price": "#,##0.0000",
    "frac": "0.000000",
    "pct": "0.00%",
    "int": "#,##0",
    "text": "@",
    "bool": "General",
}

# Column-name suffix -> number format (CONTRACTS §1.3 units carry through to the workbook).
SUFFIX_FMT = [
    ("_inr_t", "inr"), ("_inr_kg", "price"), ("_usd_t", "usd"), ("_inr", "inr"), ("_usd", "usd"),
    ("_mt", "price"), ("_frac", "frac"), ("_pa", "frac"), ("_pct", "inr"), ("_bdays", "int"),
    ("_days", "int"), ("_date", "date"), ("usdinr", "price"), ("_boxes", "int"), ("_lots", "int"),
]


def fmt_for(column: str) -> str:
    for suffix, key in SUFFIX_FMT:
        if column.endswith(suffix) or column == suffix:
            return FMT[key]
    return FMT["text"]
