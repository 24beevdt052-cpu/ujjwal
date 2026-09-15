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
