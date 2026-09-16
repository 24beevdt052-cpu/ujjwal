"""Phase 3 charts (MASTER_SPEC Table 5 row 3.3). Every figure goes through `desk.reporting.style.save_fig`, which
stamps the simulation label, so no chart can leave this module without saying what it is.

Four figures:

* `p3_equity_curve` — cumulative book P&L split into realised cash (including funding) and unrealised mark, with the
  headline Mar–Aug window shaded and the three derived event windows annotated.
* `p3_attribution_waterfall_<trade_id>` and `p3_attribution_waterfall_book` — the eight `PNL_BUCKETS` from zero to
  the final cumulative P&L, in the fixed `FACTOR_ORDER` with `new_deal` first.
* `p3_adverse_events` — each event's isolated impact beside its counterfactual, with event 3's honesty note.
* `p3_mcx_vm_schedule` — the variation-margin cash schedule from `WINDOW_START`, which is where the importer's short
  actually strains: margin is *paid* on the way up, in the 01–07 March spike, and received in the crash.
"""

from __future__ import annotations

import datetime as dt

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from desk import WINDOW_END, WINDOW_START
from desk.mtm import engine
from desk.reporting.style import FACTOR_COLORS, FACTOR_LABELS, PALETTE, PNL_BUCKETS, save_fig

CRORE = 1e7
SOURCE_NOTE = ("LME DIRECT; USD/INR, rates and MCX PROXY; grade factors and freight ASSUMPTION reconstructions; "
               "counterparties and operational events SIM")


def _fmt_date_axis(ax) -> None:
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))


def _shade_window(ax) -> None:
    ax.axvspan(WINDOW_START, WINDOW_END, color=PALETTE["band"], alpha=0.5, zorder=0)


def equity_curve(run: engine.BookRun, split: pd.DataFrame, windows: pd.DataFrame, name: str = "p3_equity_curve"):
    """Cumulative book P&L, realised vs unrealised, with the derived event windows annotated."""
    fig, ax = plt.subplots()
    d = pd.to_datetime(split["date"])
    _shade_window(ax)
    ax.plot(d, split["cum_pnl_inr"] / CRORE, color=PALETTE["pnl"], lw=1.8, label="Cumulative P&L")
    ax.plot(d, split["realised_plus_funding_inr"] / CRORE, color=PALETTE["gain"], lw=1.1, ls="--",
            label="Realised P&L + funding")
    ax.plot(d, split["mtm_inr"] / CRORE, color=PALETTE["neutral"], lw=1.1, ls=":", label="Unrealised mark")
    ax.axhline(0, color="black", lw=0.6)

    lo, hi = ax.get_ylim()
    ax.set_ylim(lo - 0.18 * (hi - lo), hi)
    for _, w in windows.iterrows():
        if w["event"].endswith("MEMO_9_RETURNS") or w["event"] == "E1_CRASH_FORTNIGHT":
            continue
        ax.axvline(pd.Timestamp(w["start"]), color=PALETTE["loss"], lw=0.8, alpha=0.6)
        ax.annotate(w["event"].replace("_", " "),
                    xy=(pd.Timestamp(w["start"]), ax.get_ylim()[0]), xytext=(3, 6),
                    textcoords="offset points", fontsize=7, color=PALETTE["loss"], va="bottom")
    ax.set_ylabel("₹ crore")
    ax.set_title("Phase 3 — cumulative book P&L (SIM book, Mar–Aug 2022 window shaded)")
    ax.legend(loc="upper right", ncols=3, fontsize=8)
    _fmt_date_axis(ax)
    return save_fig(fig, name, SOURCE_NOTE)


def attribution_waterfall(totals: dict, title: str, name: str):
    """One trade's (or the book's) life-of-trade P&L, bucket by bucket, in the fixed FACTOR_ORDER."""
    fig, ax = plt.subplots(figsize=(11, 6.4))
    labels = [FACTOR_LABELS[b] for b in PNL_BUCKETS]
    values = [totals.get(b, 0.0) / CRORE for b in PNL_BUCKETS]
    running = 0.0
    tops = []
    for i, (b, v) in enumerate(zip(PNL_BUCKETS, values)):
        ax.bar(i, v, bottom=running, color=FACTOR_COLORS[b], edgecolor="white")
        ax.annotate(f"{v:+,.2f}", xy=(i, max(running, running + v)), xytext=(0, 5),
                    textcoords="offset points", ha="center", fontsize=7.5)
        running += v
        tops.append(running)
        if i < len(values) - 1:
            ax.plot([i - 0.4, i + 1.4], [running, running], color=PALETTE["neutral"], lw=0.6, ls=":", zorder=0)
    ax.bar(len(values), running, color=PALETTE["pnl"], edgecolor="white")
    ax.annotate(f"{running:+,.2f}", xy=(len(values), max(0.0, running)), xytext=(0, 5),
                textcoords="offset points", ha="center", fontsize=8.5, fontweight="bold")
    ax.axhline(0, color="black", lw=0.6)
    lo = min([0.0, running] + [t for t in tops] + [t - v for t, v in zip(tops, values)])
    hi = max([0.0, running] + [t for t in tops] + [t - v for t, v in zip(tops, values)])
    pad = 0.14 * (hi - lo if hi > lo else abs(hi) + 1.0)
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xticks(range(len(values) + 1))
    ax.set_xticklabels(labels + ["Total"], rotation=22, ha="right", fontsize=8)
    ax.set_ylabel("₹ crore")
    ax.set_title(title)
    fig.subplots_adjust(bottom=0.28)          # leave room for the rotated labels above the SIM footer
    return save_fig(fig, name, SOURCE_NOTE)


def adverse_events(e1: pd.DataFrame, e2: pd.DataFrame, e3: pd.DataFrame, name: str = "p3_adverse_events"):
    """Isolated impact beside its counterfactual for each of the three events."""
    def pick(df, metric, default=0.0):
        m = df[df["metric"] == metric]
        if not len(m):
            return default
        try:
            return float(m["value"].iloc[0])
        except (TypeError, ValueError):
            return default

    def span(df, metric):
        m = df[df["metric"] == metric]
        return str(m["value"].iloc[0]) if len(m) else "?"

    # One panel per event with its own scale: E1 is two orders of magnitude bigger than E3, and forcing them onto
    # one axis would make the operational event invisible — which is the opposite of the point of reporting it.
    panels = [
        (f"E1 LME crash\n{span(e1, 'window_start')} → {span(e1, 'window_end')}",
         [("physical (a)", pick(e1, "lme_flat_physical_inr"), PALETTE["lme"]),
          ("MCX hedge (a)", pick(e1, "lme_flat_mcx_inr"), PALETTE["mcx"]),
          ("hedge benefit", pick(e1, "hedge_benefit_inr"), PALETTE["gain"])]),
        (f"E2 INR depreciation\n{span(e2, 'window_start')} → {span(e2, 'window_end')}",
         [("USD cash legs (e)", pick(e2, "fx_physical_usd_flows_inr"), PALETTE["lme"]),
          ("forwards (e)", pick(e2, "fx_forwards_inr"), PALETTE["mcx"]),
          ("inventory mark (e)", pick(e2, "fx_inventory_mark_inr"), PALETTE["neutral"])]),
        (f"E3 logistics + credit\n{span(e3, 'window_start')} → {span(e3, 'window_end')}",
         [("events (f)", pick(e3, "bucket_demurrage_penalty_inr"), PALETTE["lme"]),
          ("demurrage", pick(e3, "demurrage_leg_lifetime_inr"), PALETTE["loss"]),
          ("overdue funding", pick(e3, "overdue_funding_inr"), PALETTE["freight"])]),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 5.6))
    for ax, (title, bars) in zip(axes, panels):
        vals = [b[1] / CRORE for b in bars]
        ax.bar(range(len(bars)), vals, color=[b[2] for b in bars], width=0.6)
        for i, (label, v, _c) in enumerate(bars):
            ax.annotate(f"{v / CRORE:+,.2f}", xy=(i, v / CRORE), xytext=(0, 5 if v >= 0 else -13),
                        textcoords="offset points", ha="center", fontsize=8)
        ax.axhline(0, color="black", lw=0.6)
        ax.set_xticks(range(len(bars)))
        ax.set_xticklabels([b[0] for b in bars], rotation=18, ha="right", fontsize=8)
        ax.set_title(title, fontsize=9.5)
        lo, hi = min(vals + [0.0]), max(vals + [0.0])
        pad = 0.22 * (hi - lo if hi > lo else abs(hi) + 1.0)
        ax.set_ylim(lo - pad, hi + pad)
    axes[0].set_ylabel("₹ crore over the event window")
    fig.suptitle("Phase 3 — adverse events: isolated impact and its offset (note the three separate scales)",
                 fontweight="bold", fontsize=12)
    axes[1].set_xlabel("Event 3 carries no freight spike: container freight FELL about 36% on both lanes over the "
                       "window. Any spike is a labelled hypothetical stress.",
                       fontsize=7, color=PALETTE["loss"], labelpad=12)
    fig.subplots_adjust(bottom=0.30, top=0.82, wspace=0.32)
    return save_fig(fig, name, SOURCE_NOTE)


def event1_hedged_vs_unhedged(run: engine.BookRun, no_mcx: engine.BookRun, H, window: tuple[dt.date, dt.date],
                              fortnight: tuple[dt.date, dt.date] | None = None,
                              name: str = "p3_event1_hedged_vs_unhedged"):
    """The event-1 counterfactual as a picture: the same book with and without its MCX hedge, over the crash.

    Both lines are rebased to zero at the window start, because the question is what the crash did, not what the
    book had already made. The LME cash path behind them is the cause.
    """
    start, end = window
    base = _cum_over(run, start, end)
    cf = _cum_over(no_mcx, start, end)
    idx = pd.to_datetime(base.index)

    fig, ax = plt.subplots()
    if fortnight:
        ax.axvspan(pd.Timestamp(fortnight[0]), pd.Timestamp(fortnight[1]), color=PALETTE["loss"], alpha=0.12)
    ax.plot(idx, base.to_numpy() / CRORE, color=PALETTE["pnl"], lw=1.8, label="book as traded (MCX short on)")
    ax.plot(idx, cf.to_numpy() / CRORE, color=PALETTE["loss"], lw=1.4, ls="--",
            label="counterfactual: same book, no MCX hedge")
    ax.fill_between(idx, cf.to_numpy() / CRORE, base.to_numpy() / CRORE, color=PALETTE["gain"], alpha=0.18,
                    label="hedge benefit")
    ax.axhline(0, color="black", lw=0.6)
    ax.set_ylabel("₹ crore, rebased to 0 at the window start")

    ax2 = ax.twinx()
    ax2.plot(idx, [H.cash(d) for d in base.index], color=PALETTE["neutral"], lw=1.0, ls=":",
             label="LME cash (USD/t, right)")
    ax2.set_ylabel("LME cash USD/t")
    ax2.grid(False)

    _twin_legend(ax, ax2, fontsize=8)
    ax.set_title(f"Phase 3 — event 1: the book with and without its hedge, {start} → {end}")
    _fmt_date_axis(ax)
    return save_fig(fig, name, SOURCE_NOTE)


def event2_fx_offset(run: engine.BookRun, H, window: tuple[dt.date, dt.date], name: str = "p3_event2_fx_offset"):
    """Where the (e) USD/INR bucket came from through the rupee slide, and what the forward book offset."""
    from desk.mtm import events as ev

    start, end = window
    legs = run.attribution_leg[(run.attribution_leg["date"] > start) & (run.attribution_leg["date"] <= end)].copy()
    legs["instrument"] = [ev.leg_group(l) for l in legs["leg_id"]]
    cum = (legs.pivot_table(index="date", columns="instrument", values="fx", aggfunc="sum")
           .reindex(columns=["physical", "inventory_mark", "fx_forward", "mcx"], fill_value=0.0)
           .fillna(0.0).cumsum())
    idx = pd.to_datetime(cum.index)

    fig, ax = plt.subplots()
    series = [("physical", "USD cash legs (payables, receipts)", PALETTE["lme"]),
              ("inventory_mark", "replacement-value mark (long USD, design D5)", PALETTE["neutral"]),
              ("fx_forward", "USD/INR forward book", PALETTE["fx"]),
              ("mcx", "MCX short (short USD via duty parity)", PALETTE["mcx"])]
    for col, label, colour in series:
        ax.plot(idx, cum[col].to_numpy() / CRORE, lw=1.5, color=colour, label=label)
    ax.plot(idx, cum.sum(axis=1).to_numpy() / CRORE, lw=2.2, color="black", label="net (e) USD/INR bucket")
    ax.axhline(0, color="black", lw=0.6)
    ax.set_ylabel("₹ crore, cumulative over the window")

    ax2 = ax.twinx()
    ax2.plot(idx, [H.usdinr(d) for d in cum.index], color=PALETTE["loss"], lw=1.0, ls=":",
             label="USD/INR (PROXY, right)")
    ax2.set_ylabel("USD/INR (ECB cross, PROXY)")
    ax2.grid(False)

    _twin_legend(ax, ax2, fontsize=7.5)
    ax.set_title(f"Phase 3 — event 2: the rupee slide through the (e) bucket, {start} → {end}")
    _fmt_date_axis(ax)
    return save_fig(fig, name, SOURCE_NOTE)


def _twin_legend(ax, ax2, *, fontsize: float) -> None:
    """One legend across both y-axes, skipping matplotlib's auto-named artists (`_child*`, the zero line)."""
    handles, labels = [], []
    for a in (ax, ax2):
        h, l = a.get_legend_handles_labels()
        for hi, li in zip(h, l):
            if not li.startswith("_"):
                handles.append(hi)
                labels.append(li)
    ax.legend(handles, labels, loc="upper left", fontsize=fontsize)


def _cum_over(run: engine.BookRun, start: dt.date, end: dt.date) -> pd.Series:
    """Book cumulative P&L over `(start, end]`, rebased to zero at `start`."""
    df = run.attribution
    m = (df["trade_id"] == engine.BOOK_ID) & (df["date"] >= start) & (df["date"] <= end)
    s = df.loc[m].set_index("date")["cum_pnl_inr"]
    return s - s.iloc[0]


def mcx_vm_schedule(vm: pd.DataFrame, fortnight: tuple[dt.date, dt.date] | None = None,
                    name: str = "p3_mcx_vm_schedule"):
    """Variation margin and initial margin as cash, from WINDOW_START."""
    d = vm[vm["date"] >= WINDOW_START]
    by_day = d.groupby("date")[["vm_inr", "im_required_inr", "net_margin_cash_inr"]].sum().sort_index()
    cum = by_day["net_margin_cash_inr"].cumsum()
    fig, ax = plt.subplots()
    idx = pd.to_datetime(by_day.index)
    _shade_window(ax)
    ax.bar(idx, by_day["vm_inr"] / CRORE, color=PALETTE["mcx"], width=1.4, label="daily variation margin")
    ax.plot(idx, cum / CRORE, color=PALETTE["pnl"], lw=1.6, label="cumulative margin cash")
    ax.plot(idx, -by_day["im_required_inr"] / CRORE, color=PALETTE["neutral"], lw=1.0, ls="--",
            label="initial margin posted (shown negative)")
    if fortnight:
        ax.axvspan(pd.Timestamp(fortnight[0]), pd.Timestamp(fortnight[1]), color=PALETTE["loss"], alpha=0.12)
        ax.annotate("crash fortnight", xy=(pd.Timestamp(fortnight[0]), ax.get_ylim()[1]), xytext=(3, -10),
                    textcoords="offset points", fontsize=7, color=PALETTE["loss"], va="top")
    ax.axhline(0, color="black", lw=0.6)
    ax.set_ylabel("₹ crore")
    ax.set_title("Phase 3 — MCX margin cash schedule (a short pays margin on the way UP)")
    ax.legend(loc="lower right")
    _fmt_date_axis(ax)
    return save_fig(fig, name, SOURCE_NOTE)
