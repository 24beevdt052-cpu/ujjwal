"""Session setup: make sure the Phase 0 outputs the data tests read actually exist.

Review finding: with data/processed absent, ~35 data tests used to *skip* and the suite still went green. Now, if the
raw cache is present, the P0 stages are rebuilt offline (DESK_OFFLINE=1, deterministic) before any test runs, so those
tests really execute. Without a raw cache the data tests still skip, unless DESK_REQUIRE_P0=1 turns that into a
failure (use it in CI).
"""

from __future__ import annotations

import os

import pytest

from desk.paths import DOCS_DIR, PROCESSED_DIR, RAW_DIR

P0_OUTPUTS = [
    PROCESSED_DIR / "lme_daily.csv",
    PROCESSED_DIR / "fx_rates_daily.csv",
    PROCESSED_DIR / "freight_weekly.csv",
    PROCESSED_DIR / "headlines_weekly.csv",
    PROCESSED_DIR / "market_daily.csv",
    PROCESSED_DIR / "series_provenance.csv",
    DOCS_DIR / "00_data_dictionary.md",
    DOCS_DIR / "00_assumptions_log.md",
]
RAW_SENTINELS = [RAW_DIR / "westmetall_lme_al_2022.html", RAW_DIR / "rates", RAW_DIR / "freight" / "wayback",
                 RAW_DIR / "news", RAW_DIR / "regulatory" / "tradestat"]


def _run_p0_offline() -> None:
    import importlib

    import run_all

    old = os.environ.get("DESK_OFFLINE")
    os.environ["DESK_OFFLINE"] = "1"
    try:
        for phase, _label, module in run_all.STAGES:
            if phase == "P0":
                importlib.import_module(module).main()
    finally:
        if old is None:
            os.environ.pop("DESK_OFFLINE", None)
        else:
            os.environ["DESK_OFFLINE"] = old


@pytest.fixture(scope="session", autouse=True)
def p0_outputs():
    missing = [p for p in P0_OUTPUTS if not p.exists()]
    if not missing:
        return
    if all(s.exists() for s in RAW_SENTINELS):
        _run_p0_offline()
        still = [str(p) for p in P0_OUTPUTS if not p.exists()]
        if still:
            pytest.fail(f"offline P0 rebuild did not produce {still}")
    elif os.environ.get("DESK_REQUIRE_P0") == "1":
        pytest.fail(f"DESK_REQUIRE_P0=1 but P0 outputs {missing} are missing and the raw cache is incomplete")


# ---------------------------------------------------------------------------------------------- slow tests
# The full suite used to take more than ten minutes, almost all of it in the Excel workbook's full recalculation
# (`formulas` builds a graph of millions of objects: ~4 minutes and several GB on this machine) and its byte-for-byte
# rebuild. Those tests are marked `@pytest.mark.slow` and skipped by default. Every published control is still
# covered by the default run: the P3 sign-off controls by tests/test_mtm_*.py, and the workbook's own recalculated
# scoreboard by test_excel_reconciliation.py::test_published_reconciliation_report_passes, which reads the report
# the slow recalculation writes. Run the slow ones with DESK_RUN_SLOW=1 (or `-m slow`).
def pytest_configure(config):
    config.addinivalue_line("markers", "slow: long-running or memory-heavy; skipped unless DESK_RUN_SLOW=1 or -m slow")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("DESK_RUN_SLOW") == "1" or "slow" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="slow test: set DESK_RUN_SLOW=1 (or pass -m slow) to run it")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
