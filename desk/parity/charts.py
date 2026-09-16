"""Phase 1 charts (all through desk.reporting.style.save_fig, so each carries the SIM label and a source note)."""

from __future__ import annotations

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap, TwoSlopeNorm
from matplotlib.patches import Patch

from desk import WINDOW_END, WINDOW_START, config
from desk.parity import model
from desk.reporting.style import PALETTE, save_fig

GRADE_LABELS = {"zorba": "Zorba 95/5", "taint_tabor": "Taint/Tabor", "tense": "Tense"}
LANE_LABELS = {"JEA_NSA": "Jebel Ali → Nhava Sheva (20ft, MCX M1)", "USEC_MUN": "US East Coast → Mundra (40ft, MCX M2)"}
SOURCE_PARITY = ("CONTRACTS §5 on data/processed/market_daily.csv: LME DIRECT; USD/INR, MCX anchor PROXY; freight "
                 "levels ASSUMPTION (hindsight reconstruction); grade factors, premium, costs ASSUMPTION")
BAND_LINES = {"mix_pit": ("#8064a2", "point-in-time mix"), "anchor_sticky_trailing": ("#c55a11", "sticky anchor"),
              "anchor_mirror_m1": ("#548235", "mirror MCX M1 anchor")}


def _window_span(ax) -> None:
    ax.axvspan(pd.Timestamp(WINDOW_START), pd.Timestamp(WINDOW_END), color=PALETTE["band"], alpha=0.35, lw=0,
               zorder=0)


def net_arb_weekly(parity: pd.DataFrame) -> str:
    fig, axes = plt.subplots(3, 2, figsize=(13, 10), sharex=True, sharey=True)
    for i, g in enumerate(model.GRADES):
        for j, l in enumerate(model.LANES):
            ax = axes[i, j]
            s = parity[(parity["grade"] == g) & (parity["lane"] == l)].sort_values("week_end")
            _window_span(ax)
            for we in s.loc[s["trade_eligible"] & s["in_window"], "week_end"]:
                ax.axvspan(we - pd.Timedelta(days=model.DAYS_PER_WEEK), we, color=PALETTE["gain"], alpha=0.22, lw=0,
                           zorder=0)
            ax.plot(s["week_end"], s["net_arb_inr_t"] / 1000, color=PALETTE["pnl"], lw=1.8, marker="o", ms=2.5,
                    label="net arb, base (§5)")
            ax.plot(s["week_end"], s["net_arb_pit_mix_inr_t"] / 1000, color="#8064a2", lw=1.1, ls="--",
                    label="point-in-time grade mix (§5a case 2)")
            ax.plot(s["week_end"], s["net_arb_conv18k_inr_t"] / 1000, color=PALETTE["mcx"], lw=1.0, ls=":",
                    label=f"conversion ₹{model.conversion_step_above_base() / 1000:g}k/t ingot (§5a case 3)")
            ax.axhline(s["margin_threshold_inr_t"].iloc[0] / 1000, color=PALETTE["loss"], lw=1.0, ls="-.",
                       label=f"margin threshold ₹{s['margin_threshold_inr_t'].iloc[0] / 1000:g}k/t")
            ax.axhline(0, color=PALETTE["neutral"], lw=0.6)
            n_el = int((s["trade_eligible"] & s["in_window"]).sum())
            n_win = int(s["in_window"].sum())
            ax.set_title(f"{GRADE_LABELS[g]} — {LANE_LABELS[l]}\ntrade-eligible {n_el}/{n_win} window weeks",
                         fontsize=9.5)
            if j == 0:
                ax.set_ylabel("₹ '000 per MT scrap")
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    handles, labels = axes[0, 0].get_legend_handles_labels()
    handles += [Patch(color=PALETTE["gain"], alpha=0.3), Patch(color=PALETTE["band"], alpha=0.6)]
    labels += ["trade-eligible window week (§5a)", "headline window Mar–Aug 2022"]
    fig.legend(handles, labels, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.02), fontsize=8.5)
    thr = float(config.value("margin_threshold_inr_t"))
    fig.suptitle(f"Import parity: weekly net arbitrage per MT of scrap vs the ₹{thr:,.0f}/t hurdle", y=1.05, fontsize=13,
                 fontweight="bold")
    fig.tight_layout()
    return save_fig(fig, "p1_net_arb_weekly", SOURCE_PARITY)


def window_heatmap(parity: pd.DataFrame) -> str:
    win = parity[parity["in_window"]].copy()
    weeks = sorted(win["week_end"].unique())
    flags = [("open_base", "base"), ("open_pit_mix", "PIT mix"), ("open_conv18k", "conv 18k"),
             ("trade_eligible", "ELIGIBLE")]
    rows, labels = [], []
    for g in model.GRADES:
        for l in model.LANES:
            s = win[(win["grade"] == g) & (win["lane"] == l)].set_index("week_end").reindex(weeks)
            for col, lab in flags:
                rows.append(s[col].astype(float).to_numpy() + (2.0 if col == "trade_eligible" else 0.0))
                labels.append(f"{GRADE_LABELS[g]} {l} · {lab}")
    mat = np.vstack(rows)
    cmap = ListedColormap(["#f2f2f2", "#9dc3e6", "#fbe5d6", PALETTE["gain"]])
    fig, ax = plt.subplots(figsize=(14, 9))
    ax.imshow(mat, aspect="auto", cmap=cmap, vmin=-0.5, vmax=3.5, interpolation="nearest")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=7.5)
    ax.set_xticks(range(len(weeks)))
    ax.set_xticklabels([pd.Timestamp(w).strftime("%d-%b") for w in weeks], rotation=90, fontsize=7.5)
    for k in range(1, 6):
        ax.axhline(k * len(flags) - 0.5, color="white", lw=3)
    ax.grid(False)
    ax.legend(handles=[Patch(color="#9dc3e6", label="case open"), Patch(color="#f2f2f2", label="case closed"),
                       Patch(color=PALETTE["gain"], label="trade-eligible (all three open)"),
                       Patch(color="#fbe5d6", label="not eligible")],
              loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=4, fontsize=8.5)
    fig.suptitle("CONTRACTS §5a trade eligibility by week ending: base ∧ point-in-time mix ∧ conversion one step above "
                 "base", fontsize=12, fontweight="bold")
    fig.tight_layout()
    return save_fig(fig, "p1_window_heatmap", SOURCE_PARITY)


def landed_cost_waterfall(row: pd.Series, ref_label: str) -> str:
    fx = float(row["usdinr_goods"])
    lme_inr = row["lme_3m_usd_t"] * fx
    cfr_inr = row["cfr_usd_t"] * fx
    steps = [
        ("LME 3M\n× FX", lme_inr, "total"),
        ("grade discount\n(CFR factor)", cfr_inr - lme_inr, "delta"),
        ("CFR", cfr_inr, "total"),
        ("insurance", row["insurance_usd_t"] * fx, "delta"),
        ("BCD + SWS", row["bcd_inr_t"] + row["sws_inr_t"], "delta"),
        ("port, C&F,\nPSIC", row["port_inr_t"], "delta"),
        ("finance +\nIGST finance", row["finance_inr_t"] + row["igst_finance_inr_t"], "delta"),
        ("LANDED", row["landed_inr_t"], "total"),
        ("anchor ×\nrecovery", row["anchor_inr_t"] * row["recovery_frac"], "total"),
        ("by-product\n(heavies)", row["byproduct_inr_t"], "delta"),
        ("conversion", -row["conversion_inr_t"], "delta"),
        ("NET\nREALISATION", row["anchor_inr_t"] * row["recovery_frac"] + row["byproduct_inr_t"]
         - row["conversion_inr_t"], "total"),
    ]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [5, 1]})
    level = 0.0
    for i, (lab, val, kind) in enumerate(steps):
        if kind == "total":
            color = PALETTE["lme"] if i < 8 else PALETTE["mcx"]
            ax.bar(i, val / 1000, color=color, alpha=0.85)
            level = val
            ax.text(i, val / 1000 + 3, _fmt_num(val / 1000, 1), ha="center", fontsize=8)
        else:
            bottom = level if val >= 0 else level + val
            raises_cost = i < 8
            good = (val < 0) if raises_cost else (val > 0)
            ax.bar(i, abs(val) / 1000, bottom=bottom / 1000, color=PALETTE["gain"] if good else PALETTE["loss"],
                   alpha=0.8)
            ax.text(i, (level + max(val, 0)) / 1000 + 3, _fmt_num(val / 1000, 1) if val < 0
                    else f"+{val / 1000:,.1f}", ha="center", fontsize=8)
            level += val
    ax.set_xticks(range(len(steps)))
    ax.set_xticklabels([s[0] for s in steps], fontsize=8)
    ax.set_ylabel("₹ '000 per MT of scrap")
    lo = min(row["landed_inr_t"], row["anchor_inr_t"] * row["recovery_frac"]) / 1000
    ax.set_ylim(lo * 0.75, max(lme_inr, row["anchor_inr_t"] * row["recovery_frac"]) / 1000 * 1.08)
    ax.set_title(f"Landed cost vs domestic realisation — {ref_label} (y-axis truncated)")
    net = float(row["net_arb_inr_t"])
    ax2.bar([0], [net / 1000], color=PALETTE["gain"] if net > 0 else PALETTE["loss"])
    thr_k = row["margin_threshold_inr_t"] / 1000
    ax2.axhline(thr_k, color=PALETTE["loss"], ls="-.", lw=1)
    # labelled on the line: a legend box in this narrow panel sat on top of the bar
    ax2.annotate(f"threshold ₹{thr_k:g}k/MT", xy=(0, thr_k), xytext=(0, 3), textcoords="offset points", ha="center",
                 va="bottom", fontsize=8, color=PALETTE["loss"],
                 bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.9})
    ax2.text(0, net / 1000 + (1 if net >= 0 else -3), f"{_rupee(net)}/MT", ha="center", fontsize=9, fontweight="bold")
    ax2.axhline(0, color=PALETTE["neutral"], lw=0.6)
    ax2.set_xticks([0])
    ax2.set_xticklabels(["NET ARB\n= realisation − landed"], fontsize=8)
    ax2.set_ylabel("₹ '000 per MT")
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.15)      # keep the two-line tick labels clear of the source footer
    note = (f"FX for goods = 1M forward {fx:.4f} (parity_goods_fx_basis); duties on customs rate "
            f"{row['customs_usdinr_import']:.2f}; anchor = MCX {row['mcx_contract']} proxy + premium")
    return save_fig(fig, "p1_landed_cost_waterfall", note)


def _fmt_num(v: float, dec: int) -> str:
    txt = f"{v:,.{dec}f}"
    if txt.startswith("-") and float(txt.replace(",", "")) == 0:
        return txt[1:]
    return txt.replace("-", "−")


def _rupee(v: float) -> str:
    return f"−₹{abs(v):,.0f}" if v < 0 else f"₹{v:,.0f}"


def _annotated_heatmap(ax, mat: np.ndarray, xlabels, ylabels, title: str, vmax: float, dec: int = 1):
    im = ax.imshow(mat, cmap="RdYlGn", norm=TwoSlopeNorm(vcenter=0.0, vmin=-vmax, vmax=vmax), aspect="auto")
    ax.set_xticks(range(len(xlabels)))
    ax.set_xticklabels(xlabels, fontsize=8)
    ax.set_yticks(range(len(ylabels)))
    ax.set_yticklabels([str(y).replace("-", "−") for y in ylabels], fontsize=8)
    for (i, j), v in np.ndenumerate(mat):
        ax.text(j, i, _fmt_num(v, dec), ha="center", va="center", fontsize=7)
    ax.grid(False)
    ax.set_title(title, fontsize=9.5)
    return im


def _ref_title(ref: str, base: pd.Series, extra: str = "") -> str:
    """Three short lines per panel: three wide two-line titles side by side ran into each other."""
    return (f"{ref.replace('_', ' ')}\n{pd.Timestamp(base['week_end']).date()} · {GRADE_LABELS[base['grade']]} · "
            f"{base['lane']}{extra}")


def _heatmap_grid(n: int):
    """One row of heatmaps sharing the y labels, with an explicit colour-bar axis so nothing overlaps."""
    fig, axes = plt.subplots(1, n, figsize=(15, 6.6), sharey=True)
    fig.subplots_adjust(left=0.08, right=0.9, bottom=0.11, top=0.8, wspace=0.07)
    cax = fig.add_axes((0.915, 0.18, 0.012, 0.55))
    return fig, np.atleast_1d(axes), cax


def sensitivity_lme_fx(grid: pd.DataFrame) -> str:
    refs = list(dict.fromkeys(grid["ref_case"]))
    fig, axes, cax = _heatmap_grid(len(refs))
    vmax = float(np.abs(grid["pnl_impact_1000mt_inr"]).max() / 1e6)
    for k, (ax, ref) in enumerate(zip(axes, refs)):
        g = grid[(grid["ref_case"] == ref) & (~grid["usdinr_is_base"])]
        piv = g.pivot_table(index="lme_shock_pct", columns="usdinr", values="pnl_impact_1000mt_inr").sort_index(
            ascending=False)
        base = grid[(grid["ref_case"] == ref) & grid["usdinr_is_base"]].iloc[0]
        im = _annotated_heatmap(
            ax, piv.to_numpy() / 1e6, [f"{c:.0f}" for c in piv.columns], [f"{i:+d}%" for i in piv.index],
            _ref_title(ref, base) + f"\nbase net arb {_rupee(base['net_arb_base_inr_t'])}/t at USD/INR "
            f"{base['usdinr']:.2f}", vmax)
        ax.set_xlabel("USD/INR level")
        if k == 0:
            ax.set_ylabel("LME shock (3M and cash)")
    fig.colorbar(im, cax=cax, label="Δ net arb on 1,000 MT, ₹ million")
    fig.suptitle("Table 1.5(a) — parity P&L impact on 1,000 MT: LME × USD/INR (both legs re-priced), ₹ million",
                 fontsize=12, fontweight="bold", y=0.97)
    return save_fig(fig, "p1_sensitivity_lme_fx",
                    "MCX proxy anchor, by-product, duty base and finance re-derived from shocked LME/FX")


def sensitivity_freight_duty(grid: pd.DataFrame) -> str:
    refs = list(dict.fromkeys(grid["ref_case"]))
    fig, axes, cax = _heatmap_grid(len(refs))
    fob = grid[grid["freight_terms"] == "FOB_desk_books_freight"]
    vmax = float(np.abs(fob["pnl_impact_1000mt_inr"]).max() / 1e6)
    for k, (ax, ref) in enumerate(zip(axes, refs)):
        g = fob[fob["ref_case"] == ref]
        piv = g.pivot_table(index="freight_shock_pct", columns="bcd_rate_pct", values="pnl_impact_1000mt_inr"
                            ).sort_index(ascending=False)
        base = g.iloc[0]
        im = _annotated_heatmap(
            ax, piv.to_numpy() / 1e6, [f"{c:g}%" for c in piv.columns], [f"{i:+d}%" for i in piv.index],
            _ref_title(ref, base, ", FOB terms") + f"\nbase net arb {_rupee(base['net_arb_base_inr_t'])}/t "
            "(CFR terms: rows identical)", vmax, dec=2)
        ax.set_xlabel("BCD rate on HS 7602 (base 2.5%)")
        if k == 0:
            ax.set_ylabel("ocean freight shock")
    fig.colorbar(im, cax=cax, label="Δ net arb on 1,000 MT, ₹ million")
    fig.suptitle("Table 1.5(b) — parity P&L impact on 1,000 MT: ocean freight × BCD, ₹ million", fontsize=12,
                 fontweight="bold", y=0.97)
    return save_fig(fig, "p1_sensitivity_freight_duty",
                    "Freight levels are hindsight reconstructions (CONTRACTS §4.3); FOB = desk books freight")


def sensitivity_band(cases_long: pd.DataFrame) -> str:
    win = cases_long[cases_long["in_window"]]
    req = win[win["required"]]
    fig, axes = plt.subplots(3, 2, figsize=(13, 10), sharex=True, sharey=True)
    for i, g in enumerate(model.GRADES):
        for j, l in enumerate(model.LANES):
            ax = axes[i, j]
            s = req[(req["grade"] == g) & (req["lane"] == l)]
            env = s.groupby("week_end")["net_arb_inr_t"].agg(["min", "max", lambda x: x.quantile(0.25),
                                                              lambda x: x.quantile(0.75)])
            env.columns = ["min", "max", "q25", "q75"]
            ax.fill_between(env.index, env["min"] / 1000, env["max"] / 1000, color=PALETTE["band"], alpha=0.8,
                            label="min–max across required cases")
            ax.fill_between(env.index, env["q25"] / 1000, env["q75"] / 1000, color="#9dc3e6", alpha=0.7,
                            label="inter-quartile across cases")
            base = s[s["case"] == "base"].set_index("week_end")["net_arb_inr_t"]
            ax.plot(base.index, base / 1000, color=PALETTE["pnl"], lw=2, label="base")
            for case, (color, lab) in BAND_LINES.items():
                c = s[s["case"] == case].set_index("week_end")["net_arb_inr_t"]
                ax.plot(c.index, c / 1000, color=color, lw=1.0, ls="--", label=lab)
            thr = float(config.value("margin_threshold_inr_t")) / 1000
            ax.axhline(thr, color=PALETTE["loss"], lw=1, ls="-.", label=f"threshold ₹{thr:g}k/t")
            ax.axhline(0, color=PALETTE["neutral"], lw=0.6)
            n_cases = s["case"].nunique()
            ax.set_title(f"{GRADE_LABELS[g]} — {l} ({n_cases} required cases)", fontsize=9.5)
            if j == 0:
                ax.set_ylabel("₹ '000 per MT scrap")
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.02), fontsize=8.5)
    fig.suptitle("Net-arb sensitivity band (CONTRACTS §5 required cases), in-window weeks", y=1.05, fontsize=13,
                 fontweight="bold")
    fig.tight_layout()
    return save_fig(fig, "p1_sensitivity_band", SOURCE_PARITY)


def term_structure(weekly: pd.DataFrame, rolls: pd.DataFrame) -> str:
    fig, axes = plt.subplots(3, 1, figsize=(12, 11))
    ax = axes[0]
    # same colour convention as the Phase 0 market panel: backwardation red, contango green
    colors = [PALETTE["loss"] if v > 0 else PALETTE["gain"] for v in weekly["lme_cash_3m_spread_usd_t"]]
    ax.bar(weekly["week_end"], weekly["lme_cash_3m_spread_usd_t"], width=5, color=colors)
    _window_span(ax)
    ax.axhline(0, color=PALETTE["neutral"], lw=0.6)
    ax.set_ylabel("Cash − 3M, USD/t")
    ax.set_title("LME aluminium Cash–3M on the parity value date (red = backwardation, green = contango)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b-%y"))

    ax = axes[1]
    _window_span(ax)
    ax.bar(weekly["week_end"], weekly["structure_effect_buyer_1000mt_inr"] / 1e6, width=5, color=PALETTE["lme"],
           label="ex ante: 3M − implied M+1 average cash (known at decision)")
    ax2 = ax.twinx()
    ax2.plot(weekly["week_end"], weekly["hindsight_effect_buyer_vs_3m_1000mt_inr"] / 1e6, color=PALETTE["mcx"],
             lw=1.2, marker=".", label="HINDSIGHT: 3M − realised M+1 average cash (adds the price move)")
    ax.axhline(0, color=PALETTE["neutral"], lw=0.6)
    ax.set_ylabel("₹ million per 1,000 t (ex ante)")
    ax2.set_ylabel("₹ million per 1,000 t (hindsight)", color=PALETTE["mcx"])
    ax.set_title("(a) M+1 pricing basis: + = a buyer priced on M+1 average LME Official Cash pays less than 3M")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b-%y"))

    ax = axes[2]
    x = np.arange(len(rolls))
    w = 0.27
    ax.bar(x - w, rolls["short_hedge_roll_yield_1000mt_inr"] / 1e6, width=w, color=PALETTE["mcx"],
           label="MCX panel proxy (INR carry only)")
    ax.bar(x, rolls["mirror_short_hedge_roll_yield_1000mt_inr"] / 1e6, width=w, color="#f4b183",
           label="MCX third-party mirror (PROXY, 2M partly stale)")
    ax.bar(x + w, rolls["lme_equiv_short_roll_yield_1000mt_inr"] / 1e6, width=w, color=PALETTE["lme"],
           label="LME-equivalent carry (Cash–3M pro-rated)")
    ax.axhline(0, color=PALETTE["neutral"], lw=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{m}\nroll {pd.Timestamp(d).strftime('%d-%b')}" for m, d in
                        zip(rolls["contract_month"], rolls["roll_date"])], fontsize=7.5)
    ax.set_ylabel("₹ million per 1,000 MT")
    ax.set_title("(b) Roll yield on a 1,000 MT SHORT hedge rolled M1 → M2 (+ = earned)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return save_fig(fig, "p1_term_structure",
                    "LME Westmetall official DIRECT; forward curve linear in days (method: docs/10_parity_model.md)")
