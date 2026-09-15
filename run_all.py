"""Rebuild the entire desk from raw data, in Table 9 build order.

    .venv/bin/python run_all.py                 # everything (fetches data if raw cache is missing)
    DESK_OFFLINE=1 .venv/bin/python run_all.py  # never touch the network; use data/raw cache only
    .venv/bin/python run_all.py --from P3       # resume from a phase prefix
    .venv/bin/python run_all.py --only P4       # run one phase prefix
    .venv/bin/python run_all.py --list          # show stages

Each stage is a module exposing `main() -> None`; stages communicate only through files
(data/processed, outputs/tables), so any stage can be re-run in isolation.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time

STAGES: list[tuple[str, str, str]] = [
    ("P0", "LME Cash / 3M / stocks (Westmetall, DIRECT)", "desk.data.fetch_lme"),
    ("P0", "USD/INR (ECB cross) + rates / forward premium", "desk.data.fetch_fx"),
    ("P0", "Freight proxy (weekly, per lane)", "desk.data.fetch_freight"),
    ("P0", "News headlines (Google News RSS, weekly)", "desk.sentiment.fetch_news"),
    ("P0", "MCX third-party mirror extract (PROXY evidence)", "desk.data.fetch_mcx_mirror"),
    ("P0", "Grade-factor and anchor price evidence (DGCIS, BigMint)", "desk.data.fetch_price_evidence"),
    ("P0", "Daily market panel (+ MCX manual/proxy)", "desk.data.build_panel"),
    ("P0", "Data dictionary + assumptions log", "desk.data.dictionary"),
    ("P1", "Import parity model", "desk.parity.run"),
    ("P2", "Mock trading book", "desk.book.run"),
    ("P3", "Daily MTM + P&L attribution + adverse events", "desk.mtm.run"),
    ("P3", "Master Excel workbook (Components 1–3, formula-driven)", "desk.excel.build"),
    ("P4", "GARCH vs historical VaR + Kupiec backtest", "desk.risk.run_var"),
    ("P4", "Monte Carlo stress (10,000 paths)", "desk.risk.run_mc"),
    ("P5", "Counterparty credit scoring + tracker", "desk.risk.run_credit"),
    ("P5", "Margin & liquidity", "desk.risk.run_liquidity"),
    ("P7", "Sentiment overlay (VADER)", "desk.sentiment.run"),
    ("P6", "Desk notes, post-mortem, risk memo, interview pack", "desk.reporting.run_reports"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", help="phase prefix to start from, e.g. P3")
    ap.add_argument("--only", help="run only stages whose phase starts with this prefix")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--skip-missing", action="store_true", help="skip stages whose module does not exist yet")
    args = ap.parse_args()

    from desk.paths import ensure_dirs

    ensure_dirs()
    started = args.start is None
    for phase, label, module in STAGES:
        if args.list:
            print(f"{phase}  {module:<32} {label}")
            continue
        if not started and phase.startswith(args.start):
            started = True
        if not started or (args.only and not phase.startswith(args.only)):
            continue
        try:
            mod = importlib.import_module(module)
        except ModuleNotFoundError as e:
            if args.skip_missing and e.name == module:
                print(f"[skip] {phase} {label} ({module} not built yet)")
                continue
            raise
        t0 = time.time()
        print(f"[run ] {phase} {label}")
        mod.main()
        print(f"[done] {phase} {label} ({time.time() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
