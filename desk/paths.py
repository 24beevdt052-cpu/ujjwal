"""Canonical filesystem locations. Import these instead of hard-coding paths."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = ROOT / "config"
PARAMS_DIR = CONFIG_DIR / "params"

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
MANUAL_DIR = DATA_DIR / "manual"
PROCESSED_DIR = DATA_DIR / "processed"

OUTPUTS_DIR = ROOT / "outputs"
TABLES_DIR = OUTPUTS_DIR / "tables"
CHARTS_DIR = OUTPUTS_DIR / "charts"
EXCEL_DIR = OUTPUTS_DIR / "excel"
REPORTS_DIR = OUTPUTS_DIR / "reports"

DOCS_DIR = ROOT / "docs"


def ensure_dirs() -> None:
    for d in (RAW_DIR, MANUAL_DIR, PROCESSED_DIR, TABLES_DIR, CHARTS_DIR, EXCEL_DIR, REPORTS_DIR, DOCS_DIR):
        d.mkdir(parents=True, exist_ok=True)
