"""A fresh build never runs the slow Excel recalculation, so nothing downstream may depend on its record existing.

`outputs/excel/reconciliation.json` is written only by `DESK_RUN_SLOW=1 pytest tests/test_excel_reconciliation.py`
(minutes, ~2.8 GB of RAM). A rebuild from raw data therefore either has no record (NOT_RUN) or keeps a record that was
made for a different workbook (STALE). These tests fake both — and a failed and a verified record — with temporary
files and monkeypatched paths, and assert that:

* `desk.excel.reconciliation_status.status()` classifies each case, and never raises on a missing or corrupt record;
* the interview pack still builds (P6 `interview_pack.main()` end to end on a missing record), states the status and
  the exact command to verify, and quotes the recalculation numbers only when VERIFIED;
* the README verification item is ticked only when VERIFIED;
* the docs/35 generator (`desk.excel.build.main` → `doc.render` → §7) still runs, prints the status, and writes it.

Fast: nothing here recalculates or rebuilds the workbook; the real outputs are never written.
"""

from __future__ import annotations

import json
import shutil

import pytest

from desk.excel import build, doc
from desk.excel import reconciliation_status as rs
from desk.paths import REPORTS_DIR
from desk.reporting import interview_pack as ip
from desk.reporting import run_reports as rr

N_CELLS = 424_242          # distinctive numbers, so a test can tell whether a record's figures were quoted
N_CELLS_TXT = "424,242"
N_CHECKS = 3_917


def _record(**over) -> dict:
    rec = {
        "scope": "full workbook",
        "scope_note": "Every formula cell in every sheet is recalculated; nothing is sampled.",
        "n_recalculated": N_CELLS, "seconds": 1.0, "n_check_cells": N_CHECKS, "n_check_failures": 0, "n_errors": 0,
        "scoreboard": "PASS",
        "sheets": {"Parity": {"formula": 9, "constant": 1, "ratio": 0.9}},
        "families": {"Parity — toy family": {"max_abs_diff": 0.001, "tolerance": "tol_parity_inr_t = ₹1/t",
                                             "status": "PASS"}},
    }
    rec.update(over)
    return rec


@pytest.fixture
def files(tmp_path):
    """A stand-in workbook and a writer for records about it."""
    wb = tmp_path / "Metals_Desk_Master.xlsx"
    wb.write_bytes(b"PK\x03\x04 stand-in workbook bytes for the status tests")
    recon = tmp_path / "reconciliation.json"

    def write(record: dict | None, *, hash_of=wb) -> None:
        rec = dict(record) if record is not None else None
        if rec is not None and hash_of is not None:
            rec["workbook"] = rs.workbook_record(hash_of)
        recon.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return wb, recon, write


def _point_at(monkeypatch, wb, recon) -> None:
    monkeypatch.setattr(rs, "WORKBOOK", wb)
    monkeypatch.setattr(rs, "RECON_JSON", recon)


# ------------------------------------------------------------------------------------------------ the helper
def test_status_classifies_every_case_and_never_raises(files, tmp_path):
    wb, recon, write = files
    st = rs.status(recon, wb)
    assert st.status == rs.NOT_RUN and st.report is None and not st.verified
    assert "does not exist" in st.reason

    write(_record())
    st = rs.status(recon, wb)
    assert st.status == rs.VERIFIED and st.verified
    assert (st.n_recalculated, st.n_check_cells, st.n_check_failures, st.scoreboard) == (N_CELLS, N_CHECKS, 0, "PASS")
    assert st.recorded_sha256 == st.workbook_sha256 and st.recorded_bytes == wb.stat().st_size

    write(_record(), hash_of=None)                                   # a record from before hashes were recorded
    st = rs.status(recon, wb)
    assert st.status == rs.STALE and "no workbook SHA-256" in st.reason

    other = tmp_path / "other.xlsx"
    other.write_bytes(b"a different workbook")
    write(_record(), hash_of=other)                                  # the workbook was rebuilt with new content
    st = rs.status(recon, wb)
    assert st.status == rs.STALE and "different workbook" in st.reason

    write(_record())
    rec = json.loads(recon.read_text(encoding="utf-8"))
    rec["workbook"]["bytes"] += 1                                    # same hash field, wrong size: still not tied
    recon.write_text(json.dumps(rec), encoding="utf-8")
    assert rs.status(recon, wb).status == rs.STALE

    write(_record())
    assert rs.status(recon, tmp_path / "no_such_workbook.xlsx").status == rs.STALE

    write(_record(scoreboard="FAIL", n_check_failures=3))
    st = rs.status(recon, wb)
    assert st.status == rs.FAILED and "scoreboard is 'FAIL'" in st.reason and "n_check_failures is 3" in st.reason

    write(_record(families={"toy": {"status": "FAIL"}}))
    assert rs.status(recon, wb).status == rs.FAILED

    write(_record(scope="sampled"))
    assert rs.status(recon, wb).status == rs.FAILED

    recon.write_text("{ not json", encoding="utf-8")
    st = rs.status(recon, wb)
    assert st.status == rs.FAILED and st.report is None and "cannot be read" in st.reason

    assert rs.STATUSES == (rs.VERIFIED, rs.STALE, rs.NOT_RUN, rs.FAILED)
    hint = st.how_to_verify()
    assert rs.VERIFY_COMMAND in hint and "DESK_RUN_SLOW=1" in hint and "3 GB" in hint and "on its own" in hint


# ------------------------------------------------------------------------------------------ interview pack + README
@pytest.fixture(scope="module")
def src():
    return ip.load_sources()


def test_interview_pack_main_runs_and_says_not_run_when_the_record_is_missing(files, tmp_path, monkeypatch, capsys):
    wb, recon, _write = files
    assert not recon.exists()
    _point_at(monkeypatch, wb, recon)
    reports = tmp_path / "reports"
    reports.mkdir()
    if (REPORTS_DIR / "post_mortem.md").exists():                    # Q15 re-tests a claim against the post-mortem
        shutil.copy(REPORTS_DIR / "post_mortem.md", reports / "post_mortem.md")
    monkeypatch.setattr(ip, "REPORTS_DIR", reports)

    ip.main()

    out = capsys.readouterr().out
    assert "[pack] Excel reconciliation: NOT_RUN" in out and rs.VERIFY_COMMAND in out
    md = (reports / f"{ip.NAME}.md").read_text(encoding="utf-8")
    assert (reports / f"{ip.NAME}.pdf").exists()
    head = md.split("\n## 1. ")[0]
    assert "> **Excel reconciliation: NOT_RUN.**" in head and f"`{rs.VERIFY_COMMAND}`" in head
    assert "quotes no Excel reconciliation figures" in head
    assert "its full recalculation has not been run on this build" in md
    assert "cells with" not in md                                    # no recalculation figures quoted


@pytest.mark.parametrize("case, record_kw, hash_other, clause", [
    ("STALE", {}, True, "its recorded recalculation is not of the current file and must be re-run"),
    ("FAILED", {"scoreboard": "FAIL", "n_check_failures": 2}, False, "its last recorded recalculation did not pass"),
])
def test_interview_pack_states_a_stale_or_failed_record_without_quoting_it(src, files, tmp_path, case, record_kw,
                                                                          hash_other, clause):
    wb, recon, write = files
    other = tmp_path / "other.xlsx"
    other.write_bytes(b"the workbook as it was when the record was made")
    write(_record(**record_kw), hash_of=other if hash_other else wb)
    st = rs.status(recon, wb)
    assert st.status == case

    md, raw = ip.build_markdown(dict(src, recon=st))                 # also re-tests every claim and the word cap
    assert raw["q9_recon_status"] == case
    head = md.split("\n## 1. ")[0]
    assert f"> **Excel reconciliation: {case}.**" in head and f"`{rs.VERIFY_COMMAND}`" in head
    assert clause in md
    assert N_CELLS_TXT not in md

    readme = rr.render_readme_blocks(dict(src, recon=st))["verification"]
    assert f"- [ ] **Excel reconciliation {case}.**" in readme and rs.VERIFY_COMMAND in readme
    assert "[x] **Excel reconciliation" not in readme and N_CELLS_TXT not in readme


def test_readme_item_is_unticked_when_not_run_and_ticked_only_when_verified(src, files):
    wb, recon, write = files
    not_run = rs.status(recon, wb)
    block = rr.render_readme_blocks(dict(src, recon=not_run))["verification"]
    assert "- [ ] **Excel reconciliation NOT_RUN.**" in block and rs.VERIFY_COMMAND in block
    assert "reconciliation.json)" not in block                       # no link to a file that does not exist

    write(_record())
    verified = rs.status(recon, wb)
    item = ip.readme_recon_item(verified)
    assert item.startswith("- [x] **Excel reconciliation PASS.**") and f"{N_CELLS_TXT} formula cells" in item
    md, _ = ip.build_markdown(dict(src, recon=verified))
    assert "Excel reconciliation:" not in md.split("\n## 1. ")[0]
    assert f"recalculates {N_CELLS_TXT} cells with 0 failed checks" in md


# ------------------------------------------------------------------------------------------------ docs/35
def _stub_other_sections(monkeypatch) -> None:
    for name in ("_intro", "_sheets", "_coverage", "_interview", "_checks", "_not_in_excel", "_limitations"):
        monkeypatch.setattr(doc, name, lambda *a, **k: [])


def test_docs35_generator_runs_and_prints_the_status_for_a_missing_record(files, tmp_path, monkeypatch, capsys):
    wb, recon, _write = files
    _point_at(monkeypatch, wb, recon)
    _stub_other_sections(monkeypatch)
    out_doc = tmp_path / "35_excel_workbook.md"
    monkeypatch.setattr(build, "build", lambda: (None, None, {"data": None}))
    monkeypatch.setattr(build, "save", lambda *a, **k: None)
    monkeypatch.setattr(build, "DOC_PATH", out_doc)

    build.main()

    out = capsys.readouterr().out
    assert "[excel] reconciliation status: NOT_RUN" in out and rs.VERIFY_COMMAND in out
    text = out_doc.read_text(encoding="utf-8")
    assert "## 7. Reconciliation test" in text
    assert "**Status: NOT_RUN.**" in text and f"`{rs.VERIFY_COMMAND}`" in text
    assert "cells recalculated" not in text


def test_docs35_section_for_stale_failed_and_verified_records(files, tmp_path, monkeypatch):
    wb, recon, write = files
    _point_at(monkeypatch, wb, recon)
    other = tmp_path / "other.xlsx"
    other.write_bytes(b"an older workbook")

    write(_record(), hash_of=other)
    text = "\n".join(doc._recon())
    assert "**Status: STALE.**" in text and f"`{rs.VERIFY_COMMAND}`" in text
    assert "last recorded run, not a verification of the workbook" in text   # old numbers only with that label

    write(_record(), hash_of=None)
    text = "\n".join(doc._recon())
    assert "**Status: STALE.**" in text and "not identified (the record carries no SHA-256)" in text

    write(_record(scoreboard="FAIL", n_check_failures=1))
    text = "\n".join(doc._recon())
    assert "**Status: FAILED.**" in text and f"`{rs.VERIFY_COMMAND}`" in text

    recon.write_text("[]", encoding="utf-8")
    text = "\n".join(doc._recon())
    assert "**Status: FAILED.**" in text and "cells recalculated" not in text

    write(_record())
    text = "\n".join(doc._recon())
    assert "**Status: VERIFIED.**" in text and rs.VERIFY_COMMAND not in text
    assert "not a verification" not in text and f"cells recalculated: **{N_CELLS_TXT}**" in text
    assert rs.fingerprint(wb)["sha256"] in text
