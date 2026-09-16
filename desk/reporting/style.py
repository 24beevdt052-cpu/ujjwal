"""Shared chart style. Every chart goes through `save_fig` so it carries the simulation label."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from desk import SIM_LABEL  # noqa: E402
from desk.paths import CHARTS_DIR  # noqa: E402

PALETTE = {
    "lme": "#1f4e79",
    "mcx": "#c55a11",
    "fx": "#548235",
    "freight": "#7f6000",
    "pnl": "#1f4e79",
    "loss": "#c00000",
    "gain": "#2e7d32",
    "neutral": "#7f7f7f",
    "garch": "#c00000",
    "hist": "#1f4e79",
    "band": "#dbe5f1",
}

# Attribution factor order + colours (Table 5, 3.2 a–g) — keep identical across all charts.
# The (f) and (g) labels name what the bucket actually holds rather than only what the spec calls it, because both
# are wider than their spec names and a reader who takes them at face value gets them wrong (docs/30 §4.2, §13.2):
#   (f) is everything that changes when the events-as-of date advances — demurrage and claims, but also the
#       restatement of the unsold-cargo inventory mark from B/L weight to accepted weight when a survey lands. It is
#       the *inception* value of those events, not their lifetime cost (read `event_cost_lifetime_*` for that).
#   (g) is the last block swapped, so besides carry and executed roll spreads it absorbs every cross-term the
#       documented order pushes to the end — above all ΔLME × ΔFX on USD-priced physical.
FACTOR_ORDER = ["lme_flat", "cross_exchange_basis", "grade_spread", "freight", "fx", "demurrage_penalty", "roll_term_structure"]
FACTOR_LABELS = {
    "lme_flat": "(a) LME flat price",
    "cross_exchange_basis": "(b) LME–MCX basis",
    "grade_spread": "(c) Grade / scrap spread",
    "freight": "(d) Freight vs fixture",
    "fx": "(e) USD/INR",
    "demurrage_penalty": "(f) Events known that day\n(demurrage, claims, restatements)",
    "roll_term_structure": "(g) Carry, roll and cross-terms",
}
# Full P&L bucket list for attribution tables: day-one deal margin + the seven market factors (CONTRACTS §7).
PNL_BUCKETS = ["new_deal"] + FACTOR_ORDER
# "(0) at contract", not "at inception": new_deal is booked on EVERY contract date — the purchase, each sale, each
# freight fixture and hedge booking — and on this book under two thirds of it lands on the purchase trade date
# (docs/30 §13.2 publishes the split). "Inception" read as day one would overstate what was locked at signature.
FACTOR_LABELS["new_deal"] = "(0) Deal margin at contract dates"

FACTOR_COLORS = {
    "new_deal": "#2e7d32",
    "lme_flat": "#1f4e79",
    "cross_exchange_basis": "#c55a11",
    "grade_spread": "#8064a2",
    "freight": "#7f6000",
    "fx": "#548235",
    "demurrage_penalty": "#c00000",
    "roll_term_structure": "#4bacc6",
}


def apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.figsize": (11, 5.5),
            "figure.dpi": 110,
            "axes.grid": True,
            "grid.alpha": 0.3,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "axes.titlesize": 12,
            "font.size": 9.5,
            "legend.frameon": False,
        }
    )


def save_fig(fig, name: str, source_note: str = "") -> str:
    """Stamp the SIM label (+ optional data-source note) and save to outputs/charts/<name>.png."""
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    footer = SIM_LABEL + (f"  |  {source_note}" if source_note else "")
    fig.text(0.01, 0.005, footer, fontsize=7, color="#7f7f7f", ha="left", va="bottom")
    out = CHARTS_DIR / f"{name}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(out)


apply_style()
