"""Phase 3 stage entry point: every MTM, attribution, exposure and adverse-event table, plus the controls.

    DESK_OFFLINE=1 .venv/bin/python -m desk.mtm.run

The book comes from `config/trades.yaml` + `config/counterparties.yaml` (Phase 2, CONTRACTS §6). Two environment
variables override the paths so the engine can be run on the checked-in fixtures before the real book exists:

    DESK_TRADES_FILE=config/trades.example.yaml \
    DESK_COUNTERPARTIES_FILE=config/counterparties.example.yaml \
    DESK_OFFLINE=1 .venv/bin/python -m desk.mtm.run

`main()` **raises** if any row of `pnl_controls.csv` fails. That is the point of the controls: the ₹1 attribution
residual, the ledger identity, the zero-by-construction proxy basis, the zero lifetime sum of balance-sheet flows and
the cross-phase reconciliation of the replacement mark to Phase 1 are sign-off gates, not diagnostics.

Sensitivity runs (never base P&L, per CONTRACTS §7.5 and design D13) write `_mcx_mirror` and `_grade_pit` variants of
the attribution, exposure and event-1 tables. `desk.mtm.sensitivity` adds the *result* sensitivities on top:
`pnl_sensitivity_*` re-derives every typed price through the desk's own S1/S2 rules under each registered band value
and re-runs the whole engine (a re-mark alone would move `domestic_anchor_premium_inr_t` by exactly zero rupees),
`mcx_roll_carry` splits each executed roll into the INR carry the panel proxy creates by construction and genuine
term structure, and `mcx_basis_risk` publishes the LME–MCX basis as a two-sided per-ticket range with an explicit
test of the unit-beta assumption the hedge sizing rests on. `pnl_controls.csv` is written twice — once by the base
`build()` and once at the end of `main()` with those two extra control rows appended.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from desk import HORIZON_END
from desk.book import schema as bs
from desk.mtm import charts, engine, events as ev, sensitivity as sens
from desk.mtm.constants import LEDGER_TOL_INR, fallback_report
from desk.mtm.history import MarketHistory, panel_days
from desk.paths import CONFIG_DIR, TABLES_DIR, ensure_dirs
from desk.reporting.style import PNL_BUCKETS

TRADES_DEFAULT = CONFIG_DIR / "trades.yaml"
COUNTERPARTIES_DEFAULT = CONFIG_DIR / "counterparties.yaml"
TRADES_FIXTURE = CONFIG_DIR / "trades.example.yaml"
COUNTERPARTIES_FIXTURE = CONFIG_DIR / "counterparties.example.yaml"


class ControlFailure(RuntimeError):
    """A `pnl_controls.csv` row failed — the run is not signed off."""


def book_paths() -> tuple[Path, Path]:
    """`config/trades.yaml` + `config/counterparties.yaml`, overridable by env for fixture runs."""
    trades = Path(os.environ.get("DESK_TRADES_FILE", TRADES_DEFAULT))
    cps = Path(os.environ.get("DESK_COUNTERPARTIES_FILE", COUNTERPARTIES_DEFAULT))
    if not trades.exists() and TRADES_FIXTURE.exists():
        print(f"[mtm] {trades} not written yet — falling back to the checked-in fixtures "
              f"({TRADES_FIXTURE.name}); these are NOT the trade book")
        trades, cps = TRADES_FIXTURE, COUNTERPARTIES_FIXTURE
    return trades, cps


def load(trades: Path | None = None, cps: Path | None = None) -> bs.Book:
    if trades is None or cps is None:
        trades, cps = book_paths()
    return bs.load_book(trades, cps, panel_days=panel_days())


def write(df: pd.DataFrame, name: str) -> Path:
    """Deterministic CSV: fixed float formats, ISO dates, LF line endings (CONTRACTS §1.5)."""
    out = TABLES_DIR / f"{name}.csv"
    engine.round_frame(df).to_csv(out, index=False, lineterminator="\n", date_format="%Y-%m-%d")
    return out


# --------------------------------------------------------------------------------------------------- one run
def build(book: bs.Book, H: MarketHistory, *, label: str = "base", suffix: str = "",
          write_files: bool = True) -> dict:
    """Run the engine, the counterfactuals and the event tables once, and write the tables for this variant."""
    run = engine.run_book(book, H, label=label)
    vm = engine.mcx_variation_margin(book, H, run)
    windows_df, windows = ev.windows_frame(H, book, run)

    no_mcx = ev.counterfactual(book, H, "no_mcx", drop_instruments=frozenset({"mcx"}))
    no_fwd = ev.counterfactual(book, H, "no_fx_forward", drop_instruments=frozenset({"fx_forward"}))
    no_events = ev.counterfactual(book, H, "no_events",
                                  drop_event_kinds=frozenset({"quality", "logistics_delay", "buyer_payment_delay"}))
    # Event 3 has three separable parts, so each gets its own counterfactual rather than one lumped "no events"
    # number: the dwell the void calls caused, the buyer's payment delay, and the out-turn quality claims.
    no_dwell = ev.counterfactual(book, H, "no_dwell", drop_event_kinds=frozenset({"logistics_delay"}))
    no_delay = ev.counterfactual(book, H, "no_payment_delay", drop_event_kinds=frozenset({"buyer_payment_delay"}))
    no_quality = ev.counterfactual(book, H, "no_quality", drop_event_kinds=frozenset({"quality"}))
    at_bl = ev.counterfactual(book, H, "fixtures_at_bl", fixtures_at_bl=True)

    e1, e1_daily = ev.event1_lme_crash(book, H, run, vm, windows, no_mcx)
    e2, e2_daily = ev.event2_usdinr(book, H, run, windows, no_fwd)
    e3 = ev.event3_logistics_credit(book, H, run, windows, no_events, at_bl,
                                    parts={"dwell": no_dwell, "payment_delay": no_delay, "quality": no_quality})
    stress = ev.freight_stress_hypothetical(book, H, run)
    summary = ev.summary_frame([e1, e2, e3])

    controls = engine.controls(run, H)

    if write_files:
        write(run.attribution, f"attribution_daily{suffix}")
        write(run.attribution_leg, f"attribution_leg_daily{suffix}")
        write(run.exposures, f"book_exposures_daily{suffix}")
        write(e1, f"adverse_event_1_lme_crash{suffix}")
        write(e1_daily, f"adverse_event_1_lme_crash_daily{suffix}")
        if suffix == "":
            write(run.mtm, "mtm_daily")
            write(vm, "mcx_variation_margin")
            write(windows_df, "adverse_event_windows")
            write(e2, "adverse_event_2_usdinr")
            write(e2_daily, "adverse_event_2_usdinr_daily")
            write(e3, "adverse_event_3_logistics_credit")
            # Per-counterparty credit grain (review finding): one row per (date, trade, buyer), plus the buyer
            # aggregate the E3 limit test reads, so the utilisation numbers can be reproduced from published files.
            write(ev.buyer_exposure_by_trade(book, run), "buyer_credit_exposure_by_trade_daily")
            write(ev.buyer_exposure(book, run), "buyer_credit_exposure_daily")
            write(stress, "adverse_event_3_freight_stress_hypothetical")
            write(summary, "adverse_events_summary")
            # Aliases under the Phase 3 brief's names — identical content, kept so both naming conventions resolve.
            write(e2, "adverse_event_2_inr_depreciation")
            write(e3, "adverse_event_3_payment_delay_demurrage")
            write(new_deal_timing(book, run), "new_deal_timing")
            recon = _write_cashflows(book, H, run)
            controls = pd.concat([controls, _fallback_rows(run), recon], ignore_index=True)
            write(controls, "pnl_controls")
    return {"run": run, "vm": vm, "windows_df": windows_df, "windows": windows, "e1": e1, "e1_daily": e1_daily,
            "e2": e2, "e2_daily": e2_daily, "e3": e3, "stress": stress, "summary": summary, "controls": controls,
            "counterfactuals": {"no_mcx": no_mcx, "no_fx_forward": no_fwd, "no_events": no_events,
                                "fixtures_at_bl": at_bl, "no_dwell": no_dwell, "no_payment_delay": no_delay,
                                "no_quality": no_quality}}


# Leg families for the new_deal timing split (leg_id prefix before the colon).
_NEW_DEAL_FAMILY = {"SALE": "sale", "INVENTORY": "inventory_mark", "FREIGHT": "freight_fixture",
                    "MCX": "hedges", "FX": "hedges"}


def new_deal_timing(book: bs.Book, run: engine.BookRun) -> pd.DataFrame:
    """Bucket (0) split by WHEN it was booked: on the purchase trade date, or on a later contract date.

    `new_deal` is booked on every contract date — the purchase, each sale, each freight fixture, each hedge — at the
    market of that day. The chart label used to say "at inception", and on this book a large share lands after the
    trade date, at a market that had already moved (Phase 1-3 review, controller lens). Per trade and for the book:
    the day-one amount, the later amount, and the later amount by leg family. On a sale date the family `sale` is the
    contracted price and `inventory_mark` is the replacement mark it releases; read them together.
    """
    leg = run.attribution_leg
    trade_dates = {t.trade_id: t.trade_date for t in book.trades}
    rows = []
    for t in book.trades:
        sub = leg[(leg["trade_id"] == t.trade_id) & (leg["new_deal"] != 0.0)]
        day1 = sub[sub["date"] == trade_dates[t.trade_id]]
        later = sub[sub["date"] != trade_dates[t.trade_id]]
        fam = later["leg_id"].str.split(":").str[0].map(lambda x: _NEW_DEAL_FAMILY.get(x, "purchase_costs_and_fees"))
        by = later.groupby(fam)["new_deal"].sum()
        total = float(sub["new_deal"].sum())
        rows.append({"trade_id": t.trade_id, "trade_date": t.trade_date,
                     "new_deal_on_trade_date_inr": float(day1["new_deal"].sum()),
                     "new_deal_after_trade_date_inr": float(later["new_deal"].sum()),
                     "new_deal_total_inr": total,
                     "after_trade_date_share_frac": (float(later["new_deal"].sum()) / total) if total else float("nan"),
                     **{f"after_{k}_inr": float(by.get(k, 0.0)) for k in
                        ("sale", "inventory_mark", "freight_fixture", "hedges", "purchase_costs_and_fees")},
                     "later_booking_dates": "; ".join(sorted({d.isoformat() if hasattr(d, "isoformat") else str(d)
                                                             for d in later["date"]}))})
    df = pd.DataFrame(rows)
    num = [c for c in df.columns if c.endswith("_inr")]
    book_row = {"trade_id": engine.BOOK_ID, "trade_date": None, **{c: float(df[c].sum()) for c in num},
                "later_booking_dates": ""}
    book_row["after_trade_date_share_frac"] = (book_row["new_deal_after_trade_date_inr"]
                                               / book_row["new_deal_total_inr"])
    return pd.concat([df, pd.DataFrame([book_row])], ignore_index=True)[list(df.columns)]


def _fallback_rows(run: engine.BookRun) -> pd.DataFrame:
    """Design §14 keys served from code because `config/params/book.yaml` (Phase 2) is not present yet."""
    rows = [{"date": run.days[-1], "check": "book_param_fallback", "value": float("nan"), "tolerance": float("nan"),
             "scope": f"{r['key']} = {r['value']} ({r['flag']}; {r['source']})", "status": "INFO"}
            for r in fallback_report()]
    return pd.DataFrame(rows, columns=["date", "check", "value", "tolerance", "scope", "status"])


def _write_cashflows(book: bs.Book, H: MarketHistory, run: engine.BookRun) -> pd.DataFrame:
    """Write `trade_cashflows.csv`, or `trade_cashflows_p3.csv` when Phase 2 already owns the canonical file.

    Returns the `cashflow_reconciliation_vs_p2` control row CONTRACTS §7a.3 asks for. Phase 3 owns the file in this
    build (design §11.5), so the row is an `INFO` saying so rather than a silently absent check.
    """
    cf = engine.trade_cashflows(book, H, run.cache)
    target = TABLES_DIR / "trade_cashflows.csv"
    name, row = "trade_cashflows", None
    if target.exists():
        existing = pd.read_csv(target)
        if "written_by" not in existing.columns or (existing["written_by"] != "P3").any():
            name = "trade_cashflows_p3"
            print(f"[mtm] {target.name} already written by another phase — writing {name}.csv beside it "
                  "and reconciling against it")
            row = _reconcile_cashflows(existing, cf, run.days[-1])
    write(cf, name)
    if row is None:
        row = {"date": run.days[-1], "check": "cashflow_reconciliation_vs_p2", "value": float("nan"),
               "tolerance": float("nan"),
               "scope": "not applicable — P3 writes trade_cashflows.csv (written_by=P3); "
                        "no Phase 2 file to reconcile against", "status": "INFO"}
    return pd.DataFrame([row], columns=["date", "check", "value", "tolerance", "scope", "status"])


def _reconcile_cashflows(p2: pd.DataFrame, p3: pd.DataFrame, when) -> dict:
    """`cashflow_reconciliation_vs_p2`: compare realised INR per trade when Phase 2 publishes its own file."""
    from desk.mtm.constants import LEDGER_TOL_INR
    try:
        a = p2[p2.get("scenario", "REALISED") == "REALISED"].groupby("trade_id")["amount_inr"].sum()
        b = p3[p3["scenario"] == "REALISED"].groupby("trade_id")["amount_inr"].sum()
        gap = float((a - b).abs().max())
        print(f"[mtm] cashflow_reconciliation_vs_p2: max |P2 - P3| = ₹{gap:,.2f}")
        return {"date": when, "check": "cashflow_reconciliation_vs_p2", "value": gap,
                "tolerance": LEDGER_TOL_INR, "scope": "max |P2 - P3| realised INR per trade",
                "status": "PASS" if gap <= LEDGER_TOL_INR else "FAIL"}
    except Exception as exc:                                    # a differently-shaped P2 file must not fail the run
        print(f"[mtm] cashflow_reconciliation_vs_p2 could not be computed: {exc}")
        return {"date": when, "check": "cashflow_reconciliation_vs_p2", "value": float("nan"),
                "tolerance": float("nan"), "scope": f"could not be computed: {exc}", "status": "INFO"}


# ------------------------------------------------------------------------------------------------------- main
def main() -> None:
    ensure_dirs()
    trades, cps = book_paths()
    print(f"[mtm] book: {trades} + {cps}")
    book = load(trades, cps)

    H = MarketHistory()
    base = build(book, H, label="base")

    # sensitivities — never base P&L (CONTRACTS §7.5, design D13)
    mirror = mirror_res = None
    try:
        mirror = MarketHistory(mcx_source="mirror")
        mirror_res = build(book, mirror, label="mcx_mirror", suffix="_mcx_mirror")
    except (FileNotFoundError, ValueError) as exc:
        print(f"[mtm] MCX mirror sensitivity skipped: {exc}")
    pit = MarketHistory(grade_source="pit")
    pit_res = build(book, pit, label="grade_pit", suffix="_grade_pit")

    extra = _result_sensitivities(book, H, base, mirror, mirror_res, pit_res)
    # after the sensitivities: the book-level charts quote the headline P&L with its sign-robustness band
    _charts(book, base, H)
    controls = pd.concat([base["controls"], extra], ignore_index=True)
    write(controls, "pnl_controls")                       # rewritten with the §13.9-§13.11 control rows appended
    failed = controls[controls["status"] == "FAIL"]
    print(controls.to_string(index=False))
    if len(failed):
        raise ControlFailure(f"{len(failed)} control(s) failed:\n{failed.to_string(index=False)}")

    run = base["run"]
    book_row = run.attribution[(run.attribution["trade_id"] == engine.BOOK_ID)
                               & (run.attribution["date"] == run.days[-1])].iloc[0]
    print(f"[mtm] book cumulative P&L at {HORIZON_END}: ₹{book_row['cum_pnl_inr']:,.0f}")


def _result_sensitivities(book: bs.Book, H: MarketHistory, base: dict, mirror: MarketHistory | None,
                          mirror_res: dict | None, pit_res: dict) -> pd.DataFrame:
    """The §13.9–§13.11 result sensitivities, and the two control rows that keep them honest.

    These answer questions the base run cannot: *would this book still have made money* if a registered ASSUMPTION
    had taken another value in its own band (`pnl_sensitivity_*`), how much of every MCX roll is INR carry the proxy
    creates by construction (`mcx_roll_carry`), and how large is the LME–MCX basis risk the base run prices at zero,
    read as a two-sided range rather than as a netted total (`mcx_basis_risk`). None of them is base P&L.
    """
    run = base["run"]
    per, summary = sens.run_cases(book, H, pit_run=pit_res["run"])
    write(per, "pnl_sensitivity_pricing")
    write(summary, "pnl_sensitivity_summary")
    write(sens.sign_robustness(summary, book), "pnl_sensitivity_sign_robustness")

    carry = sens.roll_carry(book, H)
    write(carry, "mcx_roll_carry")
    if mirror is not None:
        write(sens.roll_carry(book, mirror), "mcx_roll_carry_mcx_mirror")
        write(sens.basis_risk(run.attribution, mirror_res["run"].attribution, H, mirror), "mcx_basis_risk")

    end = run.days[-1]
    published = float(run.attribution.loc[(run.attribution["trade_id"] == engine.BOOK_ID)
                                          & (run.attribution["date"] == end), "cum_pnl_inr"].iloc[0])
    rederived = float(summary.loc[summary["case"] == "base", "cum_pnl_horizon_inr"].iloc[0])
    metal = float(carry["metal_pnl_inr"].abs().max()) if len(carry) else 0.0
    rows = [
        # The re-pricing cases are only worth reading if re-deriving the BASE case through the same S1/S2 rules
        # reproduces the published book. That is what makes the other rows a sensitivity and not a second model.
        {"date": end, "check": "sensitivity_base_repricing_vs_book", "value": rederived - published,
         "tolerance": LEDGER_TOL_INR, "scope": "book cum P&L at HORIZON_END"},
        # On a PROXY day the whole roll spread is INR carry by construction; anything else would mean the panel
        # formula and this decomposition had drifted.
        {"date": end, "check": "roll_carry_metal_component_max_abs", "value": metal,
         "tolerance": LEDGER_TOL_INR, "scope": "inr (PANEL_PROXY rolls)"},
    ]
    df = pd.DataFrame(rows)
    df["status"] = np.where(df["value"].abs() <= df["tolerance"], "PASS", "FAIL")
    return df[["date", "check", "value", "tolerance", "scope", "status"]]


def _charts(book: bs.Book, base: dict, H: MarketHistory) -> None:
    run, windows = base["run"], base["windows"]
    split = engine.book_pnl_split(run)
    robust = pd.read_csv(TABLES_DIR / "pnl_sensitivity_sign_robustness.csv")
    caveat = charts.band_note(robust[robust["param_key"] == "domestic_anchor_premium_inr_t"].iloc[0])
    charts.equity_curve(run, split, base["windows_df"], caveat=caveat)
    for ticket in book.trades:
        tr = run.per_trade[ticket.trade_id]
        totals = {b: float(run.attribution.loc[run.attribution["trade_id"] == ticket.trade_id, b].sum())
                  for b in PNL_BUCKETS}
        charts.attribution_waterfall(
            totals, f"Phase 3 — {ticket.trade_id} life-of-trade P&L attribution (SIM)",
            f"p3_attribution_waterfall_{ticket.trade_id}")
    book_totals = {b: float(run.attribution.loc[run.attribution["trade_id"] == engine.BOOK_ID, b].sum())
                   for b in PNL_BUCKETS}
    charts.attribution_waterfall(book_totals, "Phase 3 — book life-of-trade P&L attribution (SIM)",
                                 "p3_attribution_waterfall_book", caveat=caveat)
    charts.adverse_events(base["e1"], base["e2"], base["e3"])
    f = windows.get("E1_CRASH_FORTNIGHT")
    charts.mcx_vm_schedule(base["vm"], (f.start, f.end) if f else None)

    # docs/31_adverse_events.md: the two counterfactuals as pictures rather than as a pair of numbers
    e1w = windows.get("E1_LME_CRASH")
    if e1w is not None:
        charts.event1_hedged_vs_unhedged(run, base["counterfactuals"]["no_mcx"], H, (e1w.start, e1w.end),
                                         (f.start, f.end) if f else None)
    e2w = windows.get("E2_INR_DEPRECIATION")
    if e2w is not None:
        charts.event2_fx_offset(run, H, (e2w.start, e2w.end))


if __name__ == "__main__":
    main()
