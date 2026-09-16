"""Is the Excel reconciliation on record for the workbook that is on disk *now*?

`tests/test_excel_reconciliation.py` recalculates the saved workbook from its formulas alone — minutes of CPU and about
2.8 GB of RAM, so it is a slow test that a normal build never runs — and writes `outputs/excel/reconciliation.json`.
That record carries the SHA-256 and byte size of the exact file it recalculated. The workbook is byte-for-byte
deterministic (CONTRACTS §1.5), so the hash identifies what was verified: a rebuild from the same inputs keeps it, and
any real change to the workbook breaks it.

Everything that quotes the reconciliation — `docs/35_excel_workbook.md` §7, the interview pack and the README
verification checklist — asks `status()` first, so none of them can quote a pass for a workbook that was never
recalculated, and none of them crashes when the record is missing:

    VERIFIED  the record exists, shows a pass, and its hash matches the workbook on disk
    STALE     the record shows a pass, but for a different workbook (hash or size differs), for an unidentified one
              (no hash recorded), or there is no workbook on disk to compare it with
    NOT_RUN   there is no record: the slow recalculation has not been run on this build
    FAILED    the record exists but does not show a pass — a failing check, an error value, a partial scope, a
              missing field — or cannot be read at all

Standard library only (no openpyxl, no pandas), so the reporting stages can call it cheaply.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desk.paths import EXCEL_DIR, ROOT

WORKBOOK = EXCEL_DIR / "Metals_Desk_Master.xlsx"
RECON_JSON = EXCEL_DIR / "reconciliation.json"

VERIFIED, STALE, NOT_RUN, FAILED = "VERIFIED", "STALE", "NOT_RUN", "FAILED"
STATUSES = (VERIFIED, STALE, NOT_RUN, FAILED)

VERIFY_COMMAND = "DESK_OFFLINE=1 DESK_RUN_SLOW=1 .venv/bin/python -m pytest -q tests/test_excel_reconciliation.py"
VERIFY_CONDITIONS = ("on its own, with no other stage or test running (it peaks at about 2.8 GB of RAM, so allow "
                     "about 3 GB, and takes a few minutes)")
REFRESH_COMMANDS = ('DESK_OFFLINE=1 .venv/bin/python -c "import desk.excel.build as m; m.main()"',
                    "DESK_OFFLINE=1 .venv/bin/python run_all.py --only P6")
HASH_RECORDED_BY_RUN = "hashed by tests/test_excel_reconciliation.py immediately before the recalculation it records"


# ------------------------------------------------------------------------------------------------ fingerprints
def fingerprint(path: Path) -> dict[str, Any]:
    """SHA-256 and byte size of a file, read in 1 MB chunks."""
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return {"sha256": h.hexdigest(), "bytes": n}


def workbook_record(path: Path | None = None, hash_source: str = HASH_RECORDED_BY_RUN) -> dict[str, Any]:
    """The `workbook` entry the slow test writes into reconciliation.json."""
    path = WORKBOOK if path is None else Path(path)
    return {"path": _rel(path), **fingerprint(path), "hash_source": hash_source}


def _rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


# ------------------------------------------------------------------------------------------------ the status
@dataclass(frozen=True)
class ReconStatus:
    status: str
    reason: str
    report: Mapping[str, Any] | None = None       # the parsed record, whenever it could be read
    workbook_sha256: str | None = None            # the workbook on disk now
    workbook_bytes: int | None = None
    recorded_sha256: str | None = None            # what the record says it recalculated
    recorded_bytes: int | None = None

    @property
    def verified(self) -> bool:
        return self.status == VERIFIED

    def _num(self, key: str) -> int | None:
        try:
            return int(self.report[key]) if self.report is not None else None
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def n_recalculated(self) -> int | None:
        return self._num("n_recalculated")

    @property
    def n_check_cells(self) -> int | None:
        return self._num("n_check_cells")

    @property
    def n_check_failures(self) -> int | None:
        return self._num("n_check_failures")

    @property
    def n_errors(self) -> int | None:
        return self._num("n_errors")

    @property
    def scoreboard(self) -> str | None:
        return None if self.report is None or "scoreboard" not in self.report else str(self.report["scoreboard"])

    @property
    def hash_source(self) -> str | None:
        wb = self.report.get("workbook") if self.report is not None else None
        return str(wb["hash_source"]) if isinstance(wb, Mapping) and wb.get("hash_source") else None

    def how_to_verify(self) -> str:
        """The exact commands, for any status other than VERIFIED (markdown code spans)."""
        return (f"To verify, run `{VERIFY_COMMAND}` {VERIFY_CONDITIONS}; then regenerate what quotes it: "
                f"`{REFRESH_COMMANDS[0]}` rewrites docs/35_excel_workbook.md, and `{REFRESH_COMMANDS[1]}` rewrites "
                "the interview pack and the README checklist.")


def status(recon_path: Path | None = None, workbook_path: Path | None = None) -> ReconStatus:
    """Classify the reconciliation record against the workbook on disk. Never raises for a missing or bad record."""
    recon_path = RECON_JSON if recon_path is None else Path(recon_path)
    workbook_path = WORKBOOK if workbook_path is None else Path(workbook_path)
    current = fingerprint(workbook_path) if workbook_path.exists() else None
    cur = {"workbook_sha256": current["sha256"] if current else None,
           "workbook_bytes": current["bytes"] if current else None}

    if not recon_path.exists():
        return ReconStatus(NOT_RUN, f"No reconciliation record: `{_rel(recon_path)}` does not exist, so the full "
                                    "recalculation of the workbook has not been run on this build.", **cur)
    try:
        report = json.loads(recon_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("the record is not a JSON object")
    except (OSError, ValueError) as exc:
        return ReconStatus(FAILED, f"The reconciliation record `{_rel(recon_path)}` exists but cannot be read "
                                   f"({type(exc).__name__}), so it shows no pass.", **cur)

    wb = report.get("workbook")
    wb = wb if isinstance(wb, Mapping) else {}
    rec_sha = str(wb["sha256"]) if wb.get("sha256") else None
    try:
        rec_bytes = int(wb["bytes"]) if wb.get("bytes") is not None else None
    except (TypeError, ValueError):
        rec_bytes = None
    rec = {"report": report, "recorded_sha256": rec_sha, "recorded_bytes": rec_bytes, **cur}

    problems = pass_problems(report)
    matches = current is not None and rec_sha == current["sha256"] and rec_bytes in (None, current["bytes"])
    if problems:
        tie = ("the workbook on disk" if matches else
               "a workbook it cannot be tied to (no hash recorded)" if rec_sha is None else
               "a different workbook from the one on disk")
        return ReconStatus(FAILED, f"The last recorded recalculation, of {tie}, did not pass: "
                                   f"{'; '.join(problems)}.", **rec)
    if current is None:
        return ReconStatus(STALE, f"The recorded recalculation passed, but there is no workbook at "
                                  f"`{_rel(workbook_path)}` to tie it to.", **rec)
    if rec_sha is None:
        return ReconStatus(STALE, "The recorded recalculation passed, but the record carries no workbook SHA-256, "
                                  "so it cannot be tied to the workbook on disk.", **rec)
    if not matches:
        return ReconStatus(STALE, f"The recorded recalculation passed for a different workbook (SHA-256 "
                                  f"{rec_sha[:12]}…) than the one on disk ({current['sha256'][:12]}…): the workbook "
                                  "has changed since it was recalculated.", **rec)
    return ReconStatus(VERIFIED, f"The recorded full recalculation passed, and its SHA-256 matches the workbook on "
                                 f"disk ({current['sha256'][:12]}…).", **rec)


def pass_problems(report: Mapping[str, Any]) -> list[str]:
    """Why a record does not show a pass (empty list = it does). Same bar as the fast test on the published report."""
    out: list[str] = []
    if report.get("scope") != "full workbook":
        out.append(f"scope is {report.get('scope')!r}, not 'full workbook'")
    if report.get("scoreboard") != "PASS":
        out.append(f"scoreboard is {report.get('scoreboard')!r}")
    for key, want in (("n_check_failures", 0), ("n_errors", 0)):
        v = report.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or v != want:
            out.append(f"{key} is {v!r}")
    v = report.get("n_check_cells")
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
        out.append(f"n_check_cells is {v!r}")
    fams = report.get("families")
    if not isinstance(fams, Mapping) or not fams:
        out.append("no check families recorded")
    else:
        bad = sorted(k for k, f in fams.items() if not isinstance(f, Mapping) or f.get("status") != "PASS")
        if bad:
            out.append(f"{len(bad)} check famil{'y' if len(bad) == 1 else 'ies'} not PASS ({', '.join(bad)})")
    return out
