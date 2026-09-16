"""Adverse events (MASTER_SPEC Table 5 rows 3.4–3.6, design §8, CONTRACTS §7.6 and §7a.3).

Windows are **reporting** windows. They are derived mechanically from real LME and USD/INR data *after the fact*, to
describe what the book went through; they were never inputs to a trade, and `desk.book.validate` never sees them.

| Event | Rule |
|---|---|
| E1 LME crash | start = argmax `lme_cash_usd_t` in the headline window; end = argmin on `[start, WINDOW_END]` |
| E1 crash fortnight | the **10-trading-day return** window (11 observations) with the most negative cash return |
| E2 INR depreciation | the pair `i < j` in the window maximising `usdinr_j / usdinr_i` |
| E3 logistics + credit | earliest E3 `known_date` → the last settle date it moves |

The off-by-one is pinned deliberately: "10 panel days" must mean 10 *returns*, `c[i+10]/c[i]`. The 10-*observation*
reading (9 returns) selects a different fortnight, and both are defensible — so the convention is fixed in
`CRASH_FORTNIGHT_RETURN_DAYS` and the other reading is reported as a memo.

**Isolated impact** = the sum of the relevant buckets over the window, split by leg group, **plus** counterfactual
re-runs of the same book with one component removed (`without mcx`, `without fx_forward`, `without the simulated
events`, `with the freight fixture undone`). A hedge benefit is therefore the difference between two runs of one
engine — including the margin-funding difference — not a comparison of two models.

**Event 3 is framed honestly.** Freight *fell* through the window (JEA_NSA and USEC_MUN both about −36% from
1-Mar to 31-Aug-2022), so there was no 2022 freight spike to report. The three real components are a simulated buyer
payment delay, the real and dated July-2022 void calls at Nhava Sheva / Mundra with simulated dwell, and the cost of
fixtures locked above a falling market. Any freight **spike** lives in its own file with every row labelled
`HYPOTHETICAL STRESS — not a 2022 event`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from desk import WINDOW_END, WINDOW_START
from desk.book import schema as bs
from desk.mtm import engine, valuation as val
from desk.mtm.constants import CRASH_FORTNIGHT_RETURN_DAYS
from desk.mtm.history import MarketHistory
from desk.reporting.style import PNL_BUCKETS

HYPOTHETICAL_LABEL = "HYPOTHETICAL STRESS — not a 2022 event"
VOID_CALL_DATE = dt.date(2022, 7, 27)


@dataclass(frozen=True)
class Window:
    event: str
    start: dt.date
    end: dt.date
    metric: str
    start_value: float
    end_value: float
    rule: str
    note: str = ""

    @property
    def change_frac(self) -> float:
        return self.end_value / self.start_value - 1.0 if self.start_value else float("nan")


# --------------------------------------------------------------------------------------------- window rules
def _window_series(H: MarketHistory, column: str) -> pd.Series:
    p = H.panel
    mask = (p["date"] >= pd.Timestamp(WINDOW_START)) & (p["date"] <= pd.Timestamp(WINDOW_END))
    s = p.loc[mask, ["date", column]].set_index("date")[column]
    s.index = [d.date() for d in s.index]
    return s


def lme_crash_window(H: MarketHistory) -> Window:
    s = _window_series(H, "lme_cash_usd_t")
    start = s.idxmax()
    after = s.loc[start:]
    end = after.idxmin()
    return Window("E1_LME_CRASH", start, end, "lme_cash_usd_t", float(s[start]), float(s[end]),
                  "start = argmax cash in the headline window; end = argmin on [start, WINDOW_END]")


def crash_fortnight(H: MarketHistory, n_returns: int = CRASH_FORTNIGHT_RETURN_DAYS) -> Window:
    s = _window_series(H, "lme_cash_usd_t")
    days, vals = list(s.index), s.to_numpy(float)
    best_i, best_r = 0, np.inf
    for i in range(len(vals) - n_returns):
        r = vals[i + n_returns] / vals[i] - 1.0
        if r < best_r:
            best_i, best_r = i, r
    i, j = best_i, best_i + n_returns
    return Window("E1_CRASH_FORTNIGHT", days[i], days[j], "lme_cash_usd_t", float(vals[i]), float(vals[j]),
                  f"the {n_returns}-trading-day RETURN window (11 observations) with the most negative cash return",
                  "the 10-observation reading (9 returns) selects a different fortnight; reported as a memo")


def inr_depreciation_window(H: MarketHistory) -> Window:
    s = _window_series(H, "usdinr")
    days, vals = list(s.index), s.to_numpy(float)
    best = (0, 0, -np.inf)
    running_min_i = 0
    for j in range(len(vals)):
        if vals[j] < vals[running_min_i]:
            running_min_i = j
        ratio = vals[j] / vals[running_min_i]
        if ratio > best[2] and j > running_min_i:
            best = (running_min_i, j, ratio)
    i, j, _ = best
    return Window("E2_INR_DEPRECIATION", days[i], days[j], "usdinr", float(vals[i]), float(vals[j]),
                  "the pair i < j in the headline window maximising usdinr_j / usdinr_i",
                  f"memo: first-to-last move over the window is {vals[-1] / vals[0] - 1:.2%}")


def logistics_credit_window(book: bs.Book, run: engine.BookRun) -> Window | None:
    """E3: from the earliest simulated operational `known_date` to the last settle date it moves."""
    starts, ends = [], []
    for ticket in book.trades:
        tr = run.per_trade.get(ticket.trade_id)
        if tr is None:
            continue
        for e in ticket.events.logistics:
            starts.append(e.known_date)
            ends.append(tr.schedule.lot_dates[e.lot_id].release)
        for e in ticket.events.buyer_payment_delay:
            starts.append(e.known_date)
            ends.append(tr.schedule.sale_dates[e.sale_id].due)
    if not starts:
        return None
    return Window("E3_LOGISTICS_CREDIT", min(starts), max(ends), "known_date -> last affected settle",
                  float("nan"), float("nan"),
                  "earliest E3 known_date to the last settle date those events move",
                  f"the cited void-call trigger is dated {VOID_CALL_DATE} (Container News)")


def windows_frame(H: MarketHistory, book: bs.Book, run: engine.BookRun) -> tuple[pd.DataFrame, dict[str, Window]]:
    ws = [lme_crash_window(H), crash_fortnight(H), inr_depreciation_window(H)]
    memo = crash_fortnight(H, n_returns=CRASH_FORTNIGHT_RETURN_DAYS - 1)
    memo = Window("E1_CRASH_FORTNIGHT_MEMO_9_RETURNS", memo.start, memo.end, memo.metric, memo.start_value,
                  memo.end_value, "the 10-OBSERVATION (9-return) reading, reported so the convention is visible",
                  "not the contract convention; CONTRACTS §7a.3 fixes the 10-return window")
    ws.append(memo)
    e3 = logistics_credit_window(book, run)
    if e3 is not None:
        ws.append(e3)
    rows = [{"event": w.event, "start": w.start, "end": w.end, "metric": w.metric,
             "start_value": w.start_value, "end_value": w.end_value, "change_frac": w.change_frac,
             "n_panel_days": len(H.cal.between(w.start, w.end)), "rule": w.rule, "note": w.note,
             "reporting_only": True} for w in ws]
    return pd.DataFrame(rows), {w.event: w for w in ws}


# ------------------------------------------------------------------------------------------- window arithmetic
def window_buckets(run: engine.BookRun, start: dt.date, end: dt.date, *, trade_id: str = engine.BOOK_ID
                   ) -> dict[str, float]:
    """Bucket sums over the *returns* of the window, i.e. days in (start, end]."""
    df = run.attribution
    m = (df["trade_id"] == trade_id) & (df["date"] > start) & (df["date"] <= end)
    sub = df.loc[m]
    out = {b: float(sub[b].sum()) for b in PNL_BUCKETS}
    out["daily_pnl_inr"] = float(sub["daily_pnl_inr"].sum())
    return out


def leg_group(leg_id: str) -> str:
    """Leg groups the event tables read: the inventory mark is separated from the USD cash legs on purpose.

    Marking unsold cargo at import replacement value (design D5) makes it **long USD** — the goods leg of `R` is a
    USD price converted at the 1-month forward. Netting that against the USD payables would hide the fact that a
    100% forward hedge of the payable leaves the book net long USD while the cargo is unsold, which is a real
    consequence of the marking policy and belongs in the open.
    """
    prefix = leg_id.split(":")[0]
    if prefix == "INVENTORY":
        return "inventory_mark"
    return engine._INSTRUMENT_BY_LEG_PREFIX.get(prefix, "physical")


def window_leg_buckets(run: engine.BookRun, start: dt.date, end: dt.date, bucket: str) -> pd.DataFrame:
    df = run.attribution_leg
    m = (df["date"] > start) & (df["date"] <= end)
    sub = df.loc[m].copy()
    sub["instrument"] = [leg_group(l) for l in sub["leg_id"]]
    return sub.groupby(["trade_id", "instrument"], as_index=False)[bucket].sum()


def counterfactual(book: bs.Book, H: MarketHistory, label: str, **cache_kwargs) -> engine.BookRun:
    """The same engine, the same panel, one component of the book removed (design §8)."""
    cache = val.ScheduleCache(book, H, **cache_kwargs)
    return engine.run_book(book, H, cache=cache, label=label, with_detail=False, with_exposures=False)


# ----------------------------------------------------------------------------------------------------- event 1
def event1_lme_crash(book: bs.Book, H: MarketHistory, run: engine.BookRun, vm: pd.DataFrame,
                     windows: dict[str, Window], no_mcx: engine.BookRun) -> tuple[pd.DataFrame, pd.DataFrame]:
    w, f = windows["E1_LME_CRASH"], windows["E1_CRASH_FORTNIGHT"]
    tot = window_buckets(run, w.start, w.end)
    legs = window_leg_buckets(run, w.start, w.end, "lme_flat")
    phys = float(legs.loc[legs["instrument"] != "mcx", "lme_flat"].sum())
    mcx = float(legs.loc[legs["instrument"] == "mcx", "lme_flat"].sum())
    inv = float(legs.loc[legs["instrument"] == "inventory_mark", "lme_flat"].sum())

    cf = window_buckets(no_mcx, w.start, w.end)
    vm_w = vm[(vm["date"] > w.start) & (vm["date"] <= w.end)]
    vm_from_window_start = vm[vm["date"] >= WINDOW_START]
    cum_cash = vm_from_window_start.groupby("date")["net_margin_cash_inr"].sum().cumsum()
    peak_out = float(cum_cash.min()) if len(cum_cash) else 0.0
    peak_date = cum_cash.idxmin() if len(cum_cash) else None
    im_by_day = vm_from_window_start.groupby("date")["im_required_inr"].sum()
    vm_fortnight = float(vm[(vm["date"] > f.start) & (vm["date"] <= f.end)]["vm_inr"].sum())

    rows = [
        {"metric": "window_start", "value": str(w.start)},
        {"metric": "window_end", "value": str(w.end)},
        {"metric": "lme_cash_start_usd_t", "value": w.start_value},
        {"metric": "lme_cash_end_usd_t", "value": w.end_value},
        {"metric": "lme_change_frac", "value": w.change_frac},
        {"metric": "book_pnl_window_inr", "value": tot["daily_pnl_inr"]},
        *({"metric": f"bucket_{b}_inr", "value": tot[b]} for b in PNL_BUCKETS),
        {"metric": "lme_flat_physical_inr", "value": phys},
        {"metric": "lme_flat_inventory_mark_inr", "value": inv,
         "note": "the part of the physical leg that is the replacement-value mark on unsold cargo (design D5)"},
        {"metric": "lme_flat_mcx_inr", "value": mcx},
        {"metric": "hedge_offset_frac", "value": (-mcx / phys) if phys else float("nan")},
        {"metric": "grade_spread_offset_inr", "value": tot["grade_spread"],
         "note": "scrap stickiness in a falling market (scrap_grades.yaml grade_falling_market_logic); "
                 "the grade factors are an ASSUMPTION reconstruction, not an observed spread"},
        {"metric": "counterfactual_no_mcx_pnl_inr", "value": cf["daily_pnl_inr"]},
        {"metric": "hedge_benefit_inr", "value": tot["daily_pnl_inr"] - cf["daily_pnl_inr"],
         "note": "book minus the same book without MCX, including the margin-funding difference"},
        {"metric": "mcx_vm_window_inr", "value": float(vm_w["vm_inr"].sum())},
        {"metric": "mcx_vm_crash_fortnight_inr", "value": vm_fortnight},
        {"metric": "crash_fortnight_start", "value": str(f.start)},
        {"metric": "crash_fortnight_end", "value": str(f.end)},
        {"metric": "crash_fortnight_change_frac", "value": f.change_frac},
        {"metric": "peak_cumulative_margin_outflow_inr", "value": peak_out,
         "note": f"measured from WINDOW_START; a short pays margin when the market RISES, so for this book the "
                 f"peak strain is at {peak_date}, before the trough, not in the crash"},
        {"metric": "peak_cumulative_margin_outflow_date", "value": str(peak_date) if peak_date is not None else ""},
        {"metric": "max_im_required_inr", "value": float(im_by_day.max()) if len(im_by_day) else 0.0},
        {"metric": "max_im_stress_012_inr",
         "value": float(vm_from_window_start.groupby("date")["im_stress_012_inr"].sum().max())
         if len(vm_from_window_start) else 0.0},
        {"metric": "max_im_stress_015_inr",
         "value": float(vm_from_window_start.groupby("date")["im_stress_015_inr"].sum().max())
         if len(vm_from_window_start) else 0.0},
        {"metric": "mcx_daily_price_limit_caveat", "value": float(H.param("mcx_al_dpl_max_frac")),
         "note": "the MCX import-parity proxy ignores daily price limits: the near-month proxy moved -12.0% on "
                 "08-Mar-2022 against a 9% maximum slab, so a real position would have been limit-locked"},
    ]
    summary = pd.DataFrame(rows)
    summary["event"] = "E1_LME_CRASH"
    if "note" not in summary:
        summary["note"] = ""
    summary["note"] = summary["note"].fillna("")

    daily = run.attribution[(run.attribution["trade_id"] == engine.BOOK_ID)
                            & (run.attribution["date"] > w.start) & (run.attribution["date"] <= w.end)].copy()
    vm_daily = vm.groupby("date")[["vm_inr", "im_required_inr", "net_margin_cash_inr"]].sum()
    daily = daily.merge(vm_daily, on="date", how="left").fillna({"vm_inr": 0.0, "im_required_inr": 0.0,
                                                                 "net_margin_cash_inr": 0.0})
    daily["cum_vm_inr"] = daily["vm_inr"].cumsum()
    daily["lme_cash_usd_t"] = [H.cash(d) for d in daily["date"]]
    daily["event"] = "E1_LME_CRASH"
    return summary, daily


# ----------------------------------------------------------------------------------------------------- event 2
def event2_usdinr(book: bs.Book, H: MarketHistory, run: engine.BookRun, windows: dict[str, Window],
                  no_fwd: engine.BookRun) -> tuple[pd.DataFrame, pd.DataFrame]:
    w = windows["E2_INR_DEPRECIATION"]
    tot = window_buckets(run, w.start, w.end)
    legs = window_leg_buckets(run, w.start, w.end, "fx")
    by_inst = legs.groupby("instrument")["fx"].sum().to_dict()
    usd_flows = float(by_inst.get("physical", 0.0))
    inv = float(by_inst.get("inventory_mark", 0.0))
    phys = usd_flows + inv
    fwd = float(by_inst.get("fx_forward", 0.0))
    mcx = float(by_inst.get("mcx", 0.0))

    fwd_legs = run.attribution_leg[(run.attribution_leg["leg_id"].str.startswith("FX:"))
                                   & (run.attribution_leg["date"] > w.start)
                                   & (run.attribution_leg["date"] <= w.end)]
    cf = window_buckets(no_fwd, w.start, w.end)
    expo = run.exposures[(run.exposures["scope"] == "book")] if run.exposures is not None else pd.DataFrame()

    rows = [
        {"metric": "window_start", "value": str(w.start)},
        {"metric": "window_end", "value": str(w.end)},
        {"metric": "usdinr_start", "value": w.start_value},
        {"metric": "usdinr_end", "value": w.end_value},
        {"metric": "usdinr_change_frac", "value": w.change_frac},
        {"metric": "book_pnl_window_inr", "value": tot["daily_pnl_inr"]},
        {"metric": "bucket_fx_inr", "value": tot["fx"]},
        {"metric": "fx_physical_inr", "value": phys},
        {"metric": "fx_physical_usd_flows_inr", "value": usd_flows,
         "note": "the USD payables and receipts themselves — what the forwards were sized against"},
        {"metric": "fx_inventory_mark_inr", "value": inv,
         "note": "unsold cargo marked at import replacement value is LONG USD (design D5), so it partly offsets the "
                 "USD payables; a 100% forward hedge of the payable therefore leaves the book net long USD "
                 "while the cargo is unsold"},
        {"metric": "fx_forwards_inr", "value": fwd},
        {"metric": "fx_mcx_inr", "value": mcx,
         "note": "a short MCX is short USD: duty-paid parity rises in rupees when the rupee weakens"},
        {"metric": "forward_offset_frac_vs_usd_flows", "value": (-fwd / usd_flows) if usd_flows else float("nan"),
         "note": "against the USD cash legs, which is what the forwards were booked to cover"},
        {"metric": "forward_offset_frac_vs_net_physical", "value": (-fwd / phys) if phys else float("nan"),
         "note": "against the physical INCLUDING the replacement-value mark; read it with the note above"},
        {"metric": "forward_cost_memo_inr",
         "value": float(fwd_legs["new_deal"].sum() + fwd_legs["roll_term_structure"].sum()),
         "note": "the bank margin booked at inception plus the forward legs' carry — what the offset cost"},
        {"metric": "counterfactual_no_forwards_pnl_inr", "value": cf["daily_pnl_inr"]},
        {"metric": "forward_book_benefit_inr", "value": tot["daily_pnl_inr"] - cf["daily_pnl_inr"]},
        {"metric": "customs_fx_note", "value": float("nan"),
         "note": "the duty base moves on the CBIC notified rate, which is a fortnightly step, not the spot"},
    ]
    summary = pd.DataFrame(rows)
    summary["event"] = "E2_INR_DEPRECIATION"
    if "note" not in summary:
        summary["note"] = ""
    summary["note"] = summary["note"].fillna("")

    daily = run.attribution[(run.attribution["trade_id"] == engine.BOOK_ID)
                            & (run.attribution["date"] > w.start) & (run.attribution["date"] <= w.end)].copy()
    daily["usdinr"] = [H.usdinr(d) for d in daily["date"]]
    if len(expo):
        pos = expo.set_index("date")[["fx_delta_usd", "fx_delta_physical_usd", "fx_delta_forwards_usd"]]
        daily = daily.merge(pos, on="date", how="left")
    daily["event"] = "E2_INR_DEPRECIATION"
    return summary, daily


# ----------------------------------------------------------------------------------------------------- event 3
def event3_logistics_credit(book: bs.Book, H: MarketHistory, run: engine.BookRun, windows: dict[str, Window],
                            no_events: engine.BookRun, fixtures_at_bl: engine.BookRun,
                            parts: dict[str, engine.BookRun] | None = None) -> pd.DataFrame:
    w = windows.get("E3_LOGISTICS_CREDIT")
    if w is None:
        return pd.DataFrame([{"event": "E3_LOGISTICS_CREDIT", "metric": "no_e3_events_in_book", "value": 0.0,
                              "note": ""}])
    tot = window_buckets(run, w.start, w.end)
    cf_events = window_buckets(no_events, w.start, w.end)
    cf_fixture = window_buckets(fixtures_at_bl, w.start, w.end)

    dem = run.attribution_leg[run.attribution_leg["leg_id"].str.startswith("DEMURRAGE:")]
    funding_f = run.attribution_leg[(run.attribution_leg["leg_id"] == "FUNDING")]["demurrage_penalty"].sum()
    life = _lifetime_pnl(run)
    life_events = _lifetime_pnl(no_events)
    life_fixture = _lifetime_pnl(fixtures_at_bl)
    fixture_memo = float(run.mtm["fixture_vs_market_inr"].mean()) if run.mtm is not None else float("nan")

    util_df = buyer_exposure(book, run)
    max_util = float(util_df["utilisation_frac"].max()) if len(util_df) else 0.0
    breach_days = int(util_df.loc[util_df["breach"], "date"].nunique()) if len(util_df) else 0
    worst_name = (util_df.loc[util_df["utilisation_frac"].idxmax(), "buyer_id"] if len(util_df) else "")
    max_util_all = float(util_df["utilisation_incl_presettlement_frac"].max()) if len(util_df) else 0.0
    worst_name_all = (util_df.loc[util_df["utilisation_incl_presettlement_frac"].idxmax(), "buyer_id"]
                      if len(util_df) else "")
    max_dpd = int(run.exposures["days_past_due"].max()) if run.exposures is not None else 0

    rows = [
        {"metric": "window_start", "value": str(w.start)},
        {"metric": "window_end", "value": str(w.end)},
        {"metric": "book_pnl_window_inr", "value": tot["daily_pnl_inr"]},
        {"metric": "bucket_demurrage_penalty_inr", "value": tot["demurrage_penalty"]},
        {"metric": "overdue_funding_inr", "value": float(funding_f),
         "note": "interest on receivables past their contractual due date, routed to (f) by the §7a.1 split"},
        {"metric": "demurrage_leg_lifetime_inr", "value": float(dem["daily_pnl_inr"].sum()),
         "note": "chargeable dwell beyond detention_free_days; the dwell magnitude is SIM, anchored to the real "
                 "27-Jul-2022 void calls at Nhava Sheva / Mundra"},
        {"metric": "max_buyer_limit_utilisation_frac", "value": max_util,
         "note": f"worst name: {worst_name}; RECEIVABLE (invoiced, unpaid) summed ACROSS trades for one buyer "
                 f"against that buyer's credit_limit_inr — the same measure Phase 2's P04 rule enforces"},
        {"metric": "max_buyer_contracted_utilisation_frac", "value": max_util_all,
         "note": f"worst name: {worst_name_all}; receivable PLUS pre-settlement (contracted, not yet invoiced, "
                 f"including an advance the buyer still owes). Pre-settlement is a performance risk, not credit "
                 f"extended, so it is reported beside the limit rather than against it"},
        {"metric": "credit_limit_breach_days", "value": float(breach_days),
         "note": "panel days on which at least one buyer's receivable was over its limit (Phase 5 owns the tracker)"},
        {"metric": "max_days_past_due", "value": float(max_dpd)},
        {"metric": "counterfactual_no_events_pnl_inr", "value": cf_events["daily_pnl_inr"]},
        {"metric": "event_cost_inr", "value": tot["daily_pnl_inr"] - cf_events["daily_pnl_inr"],
         "note": "book minus the same book without the simulated quality, dwell and payment-delay events"},
        {"metric": "event_cost_lifetime_inr", "value": life - life_events,
         "note": "the same comparison over the whole life of the book, because the quality and dwell events bite "
                 "outside the E3 window as well"},
        *_part_rows(parts, life),
        {"metric": "counterfactual_fixture_at_bl_pnl_inr", "value": cf_fixture["daily_pnl_inr"]},
        {"metric": "fixture_timing_cost_lifetime_inr", "value": life - life_fixture,
         "note": "the freight fixture settles at arrival, well before the E3 window opens, so the lifetime number "
                 "is the one to read"},
        {"metric": "fixture_vs_market_memo_mean_inr", "value": fixture_memo,
         "note": "average over the leg-days it is defined of boxes x (lane index - fixture) x usdinr: a daily "
                 "STOCK memo of competitiveness against a later importer, never summed into P&L"},
        {"metric": "fixture_timing_cost_inr", "value": tot["daily_pnl_inr"] - cf_fixture["daily_pnl_inr"],
         "note": "the cost of having fixed freight early into a falling market; a competitiveness cost against "
                 "later importers, not a loss on the cargo, because CONTRACTS §5's CFR grade factor does not fall "
                 "when freight falls"},
        {"metric": "freight_change_window_jea_nsa_frac", "value": _freight_change(H, "JEA_NSA")},
        {"metric": "freight_change_window_usec_mun_frac", "value": _freight_change(H, "USEC_MUN"),
         "note": "freight FELL through the window: there was no 2022 container spike on these lanes"},
    ]
    out = pd.DataFrame(rows)
    out["event"] = "E3_LOGISTICS_CREDIT"
    if "note" not in out:
        out["note"] = ""
    out["note"] = out["note"].fillna("")
    return out


_PART_NOTES = {
    "dwell": "extra CFS dwell attributed to the real 27-Jul-2022 void calls at Nhava Sheva / Mundra "
             "(Container News, docs/research/freight_notes.md S4); the dwell days themselves are SIM",
    "payment_delay": "the SIM buyer payment delay: pure funding cost, because penal interest on a late foundry "
                     "payment is assumed uncollected (overdue_interest_collected_frac = 0)",
    "quality": "out-turn moisture and contamination against the SPA franchise — a claim, not a market move",
}


def _part_rows(parts: dict[str, engine.BookRun] | None, life: float) -> list[dict]:
    """Each E3 component isolated on its own, so 'the events cost X' can be read component by component."""
    if not parts:
        return []
    return [{"metric": f"event_cost_lifetime_{name}_inr", "value": life - _lifetime_pnl(cf),
             "note": _PART_NOTES.get(name, "")}
            for name, cf in sorted(parts.items())]


def buyer_exposure(book: bs.Book, run: engine.BookRun) -> pd.DataFrame:
    """Date x buyer: unsettled sale value against that buyer's credit limit, summed ACROSS trades.

    The exposure row in `book_exposures_daily.csv` is at trade grain, and a ticket may sell to two buyers, so a
    limit check has to be rebuilt per counterparty. Credit-limit utilisation and pre-settlement risk are Phase 5's
    subject; this is only the headline event-3 needs.

    **The limit is checked against the receivable, not against everything contracted.** CONTRACTS §7a.4 splits the
    two, and they are different risks: `buyer_receivable_inr` is goods invoiced and not yet paid — credit the desk
    has actually extended, which is what `credit_limit_inr` caps — while `buyer_presettlement_inr` is a contracted
    sale not yet invoiced, including an **advance the buyer still owes**. Summing them made the book look 2.58x over
    a line it never drew on: on 2022-07-26 T07's S1 books a Rs 220.3 m advance (received 2022-08-12, before any
    truck moves) and a Rs 89.6 m credit balance, and only the second is credit. Phase 2's P04 rule nets the advance
    out for exactly this reason, so the two phases now measure the same thing and agree.
    """
    rows = []
    for d in run.days:
        recv: dict[str, float] = {}
        pre: dict[str, float] = {}
        for tr in run.per_trade.values():
            a = tr.atts.get(d)
            if a is None or a.value_today is None:
                continue
            for f, v in zip(a.value_today.schedule.flows, a.value_today.per_flow):
                if not f.sale_id or f.settle_date is None or f.settle_date <= d:
                    continue
                book_side = recv if (f.fixing_date is not None and f.fixing_date <= d) else pre
                book_side[f.counterparty_id] = book_side.get(f.counterparty_id, 0.0) + v
        for buyer in sorted(set(recv) | set(pre)):
            receivable, presettlement = recv.get(buyer, 0.0), pre.get(buyer, 0.0)
            limit = book.counterparty(buyer).credit_limit_inr or 0.0
            contracted = receivable + presettlement
            rows.append({"date": d, "buyer_id": buyer, "exposure_inr": receivable,
                         "receivable_inr": receivable, "presettlement_inr": presettlement,
                         "contracted_inr": contracted, "credit_limit_inr": limit,
                         "utilisation_frac": (receivable / limit) if limit > 0 else float("nan"),
                         "utilisation_incl_presettlement_frac": (contracted / limit) if limit > 0 else float("nan"),
                         "breach": bool(limit > 0 and receivable > limit)})
    return pd.DataFrame(rows, columns=["date", "buyer_id", "exposure_inr", "receivable_inr", "presettlement_inr",
                                       "contracted_inr", "credit_limit_inr", "utilisation_frac",
                                       "utilisation_incl_presettlement_frac", "breach"])


def _lifetime_pnl(run: engine.BookRun) -> float:
    """Book cumulative P&L at the end of the run — the basis for lifetime counterfactual comparisons."""
    df = run.attribution
    m = (df["trade_id"] == engine.BOOK_ID) & (df["date"] == run.days[-1])
    return float(df.loc[m, "cum_pnl_inr"].iloc[0]) if m.any() else 0.0


def _freight_change(H: MarketHistory, lane: str) -> float:
    s = _window_series(H, {"JEA_NSA": "freight_jea_nsa_usd_t", "USEC_MUN": "freight_usec_mun_usd_t"}[lane])
    return float(s.iloc[-1] / s.iloc[0] - 1.0)


def freight_stress_hypothetical(book: bs.Book, H: MarketHistory, run: engine.BookRun) -> pd.DataFrame:
    """A labelled counterfactual: what a +`freight_stress_shock_frac` container spike would have cost, day by day.

    It is a **stress**, not an event. Once a fixture is booked the cargo carries no freight price risk (design D12),
    so this number is small by construction and must be read beside that fact rather than instead of it.
    """
    shock = float(H.param("freight_stress_shock_frac"))
    rows = []
    for d in run.days:
        if not engine.in_window(d):
            continue
        base = val.revalue_book(book, H, d)
        up = val.revalue_book(book, H, d, shocks={"freight_logret": float(np.log1p(shock))})
        for i, ticket in enumerate(book.trades):
            rows.append({"date": d, "trade_id": ticket.trade_id,
                         "freight_shock_frac": shock,
                         "pnl_base_inr": float(base[i, 0]), "pnl_shocked_inr": float(up[i, 0]),
                         "impact_inr": float(up[i, 0] - base[i, 0]),
                         "label": HYPOTHETICAL_LABEL})
    df = pd.DataFrame(rows)
    book_rows = df.groupby(["date", "freight_shock_frac", "label"], as_index=False)[
        ["pnl_base_inr", "pnl_shocked_inr", "impact_inr"]].sum()
    book_rows["trade_id"] = engine.BOOK_ID
    return (pd.concat([df, book_rows], ignore_index=True)
            .sort_values(["date", "trade_id"], kind="mergesort").reset_index(drop=True))


def summary_frame(parts: Iterable[pd.DataFrame]) -> pd.DataFrame:
    """One table a reader can scan: every event's headline metrics, with its honesty note attached."""
    frames = [p[["event", "metric", "value", "note"]] for p in parts if len(p)]
    return pd.concat(frames, ignore_index=True)
