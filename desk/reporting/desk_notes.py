"""Stage P6 — six weekly desk notes, one A4 page each, written as of their own Friday close (MASTER_SPEC Table 7 row 5.1).

    DESK_OFFLINE=1 .venv/bin/python -c "import desk.reporting.desk_notes as m; m.main()"

Reads (never writes) the published P0–P7 tables and writes, for n = 1..6:

    outputs/reports/desk_note_<n>_<week_end>.md     the note (GitHub-readable)
    outputs/reports/desk_note_<n>_<week_end>.pdf    the same, exactly one A4 page (asserted), SIM label in the footer
    outputs/charts/p6_note_<n>_tape.png             a small inline chart: LME cash and book P&L up to the week end

Design choices worth knowing
----------------------------
* **Which weeks.** Declared before any note was drafted: the week containing the **last Friday of each calendar month
  of the window** (Mar–Aug 2022), valued on that Friday's close, or on the last LME day of that week if the Friday is
  not a trading day. A rule that never looks at P&L or prices; one note a month gives the arc from the March spike,
  through the April–May crash and the July trough, to the August re-opening.
* **Strictly as of the week end.** `load_sources` reads every table into long, **row-dated** frames: each row carries
  the date its information became known (a trade's date, a sale's contract date, a hedge line's entry date and — as a
  separate row — its exit date, a B/L date, an event's `known_date`, a VaR row's *position* date). Columns that are
  hindsight by construction are never loaded (`hindsight_*` in the term-structure table, the reporting-only fortnight
  flags in the liquidity table, realised P&L and exception columns in the VaR row that forecasts the next session).
  `as_of` then drops every row dated after the week end, and **every number a note prints is computed from that view
  only**. `tests/test_desk_notes.py` writes copies of every input file with each row (and each later-dated field)
  after the week end overwritten, requires the note to come out byte-identical, and scans each note for any date,
  ticket, sale or headline later than its week end.
* **No hand-typed numbers.** Every number is produced through `Ledger.put`, which records the table, column, key and
  information date it came from. The tests re-read the CSVs independently and check the recorded levels and sums, and
  strip every recorded fact from the text to prove no other digit survives (identifiers such as T01, L2 or 40ft and
  a short list of structural tokens such as "95 %" excepted).
* **Trader voice from data conditions.** Each paragraph is one or more fixed template sentences; which one is used is
  decided by the data (a two-sigma week on the desk's own GARCH forecast, a curve that has flipped, a buyer carrying
  advances above its line, a funding need over the working-capital line). The thresholds that pick sentences are
  presentation constants below; they never change a number.
* **The headline P&L band, point-in-time.** The book's horizon P&L is not sign-robust to the domestic anchor premium
  (docs/30 §13.9), but that published band uses trades booked after any given note. Each note therefore prints its
  own band: the P&L to date re-struck at the registered premium grid on the **sales booked so far** — each sale's price
  moves by desk share x recovery x Δpremium (the S1 rule, `desk.mtm.sensitivity`). Summed over the whole book this
  slope reproduces the published horizon slope to within 0.2 % (tested; the gap is funding carry), so the per-note
  band is the same sensitivity restricted to what was contracted by that Friday.
* **What "as of" does not cover.** The header promises no price, position, trade or event dated after the week end,
  not "nothing published later": the anchor premium (2023–25 prints), the grade-factor path, freight lane levels and
  the INR 3M rate (a same-month OECD average, up to a month of look-ahead, which feeds the forward premium, forward
  rates and the MCX proxy's carry) are reconstructions that use later publications, and each has a footnote. The
  poison test cannot see that last kind of leak, because the leaked value sits in rows dated on or before the week end.
  A simulated logistics event also arrives with its full realised delay on its `known_date`; the note calls it an
  expected delay.
* **The band policy is retrospective.** Phase 5's credit bands and band policy were built after the fact and the desk
  did not run them in 2022, so the notes never state them as the trader's own rule: they say what the policy would
  allow, show what is actually open, and name every booking that breaks it (`band_policy_verdict`).
* **Proxies stay labelled.** Footnotes carry the freight reconstruction, the unit-beta MCX proxy, the reconstructed
  grade mix, the synthetic-data credit model, the ex-ante facility sizes, the post-2022 evidence behind the premium and
  the monthly INR rate.
  Headline tone is quoted as a supporting signal with its noise, never as a reason for a trade. Engine artefacts that
  distort a week's numbers (the closed MCX contract left in the delta on exit and roll days) are called out in place.
* **Known limits.** The notes inherit every Phase 1–5 caveat: marks on unsold cargo use reconstructed grade factors
  and freight levels; the MCX leg is a unit-beta proxy, so hedged-book VaR and margin understate basis risk; credit
  bands are illustrative; the facilities and the domestic premium are assumptions. The "decisions" are the simulated
  book's, narrated after the fact from its tables — a dated voice, not a record of anyone's real 2022 judgement.
"""

from __future__ import annotations

import calendar
import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import yaml
from reportlab.lib.units import mm
from reportlab.platypus import Image, Table, TableStyle

from desk import DESK_NAME, SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.paths import CHARTS_DIR, CONFIG_DIR, PROCESSED_DIR, REPORTS_DIR, TABLES_DIR
from desk.reporting.pdf import (
    DeskDocTemplate,
    PdfStyle,
    _numbered_canvas_class,  # the shared footer (SIM label + "Page n of N"), as the post-mortem uses it
    count_pdf_pages,
    markdown_to_flowables,
    register_fonts,
)
from desk.reporting.style import PALETTE, plt, save_fig

NAME = "desk_note"
N_NOTES = 6
MAX_PAGES = 1
M = 1e6
NB = " "
MINUS = "−"
FRIDAY = 4
CHART_PREFIX = "p6_note"
FOOTNOTES = "<!-- footnotes -->"
CHART_SLOT = "<!-- chart -->"

# Presentation constants: they choose which sentence is printed, never a number.
SIGMA_NOTABLE = 1.0          # |weekly move| / (GARCH daily sigma x sqrt(days)) at which a move is worth a comment
SIGMA_BIG = 2.0              # ... and at which it is a big week
VAR_GAP_FRAC = 0.20          # GARCH vs 250-day VaR difference worth a sentence
NET_OPEN_FRAC = 0.10         # net LME delta as a share of physical delta above which the book is "running a position"
PIT_HAIRCUT_FRAC = 0.50      # point-in-time parity below this share of base: "size to the smaller number"
VADER_NEUTRAL = 0.05         # VADER's own neutral band (Hutto & Gilbert 2014): |compound| < 0.05 is neutral
HEADLINE_MAX_WORDS = 15      # quoted headlines are cut, never paraphrased
Z_SIGNIFICANT = 1.96         # headline tone z-score outside the noise
TAPE_LOOKBACK_BDAYS = 65     # chart: about one quarter of LME days to the week end
MAX_LIST = 3                 # items named in a list before "and n more"
PUBLISHER_MIN_HEADLINES = 3  # a quoted headline's publisher must have this many headlines in the sample to date

GRADE_NAMES = {"zorba": "Zorba 95/5", "taint_tabor": "Taint/Tabor", "tense": "Tense"}
LANE_NAMES = {"JEA_NSA": "Jebel Ali → Nhava Sheva", "USEC_MUN": "US East Coast → Mundra"}
BUCKET_SHORT = {"new_deal": "(0) Deal", "lme_flat": "(a) LME", "cross_exchange_basis": "(b) Basis²",
                "grade_spread": "(c) Grade⁴", "freight": "(d) Freight¹", "fx": "(e) FX", "demurrage_penalty": "(f) Events",
                "roll_term_structure": "(g) Carry/roll"}
PNL_COLS = list(BUCKET_SHORT)
BINDING_NAMES = {"hist60": "60-day", "hist250": "250-day", "garch": "GARCH", "empirical": "empirical"}

NOTE_STYLE = PdfStyle(font_size=8.0, table_font_size=7.2, title_size=11.5, h2_size=8.8, h3_size=8.0,
                      margin_left_mm=11.0, margin_right_mm=11.0, margin_top_mm=8.0, margin_bottom_mm=10.0,
                      leading_ratio=1.16, paragraph_space_after=1.6, heading_space_before=2.4, footer_font_size=6.2)
FOOT_SCALE = 0.86            # footnotes print a little smaller than the body
MIN_FONT = 6.6               # the renderer shrinks the body in small steps to keep one page, never below this
CHART_W_FRAC = 0.33          # the tape chart sits beside "What I saw" at this share of the text width


# ------------------------------------------------------------------------------------------------ formatting
def num(x: float, dp: int = 0) -> str:
    """Thousands separators and a true minus sign; never prints a negative zero."""
    s = f"{abs(x):,.{dp}f}"
    return f"{MINUS}{s}" if x < 0 and any(c not in "0.," for c in s) else s


def signed(x: float, dp: int = 0) -> str:
    s = num(x, dp)
    return s if s.startswith(MINUS) or all(c in "0.," for c in s) else f"+{s}"


def inr_m(x: float, dp: int = 1, sign: bool = False) -> str:
    s = f"{abs(x) / M:,.{dp}f}"
    nonzero = any(c not in "0.," for c in s)
    if x < 0 and nonzero:
        return f"{MINUS}₹{s}{NB}m"
    return f"+₹{s}{NB}m" if sign and nonzero else f"₹{s}{NB}m"


def usd_m(x: float, dp: int = 2) -> str:
    s = f"{abs(x) / M:,.{dp}f}"
    return f"{MINUS}USD{NB}{s}{NB}m" if x < 0 and any(c not in "0.," for c in s) else f"USD{NB}{s}{NB}m"


def pct(x: float, dp: int = 1, sign: bool = False) -> str:
    return f"{signed(x * 100, dp) if sign else num(x * 100, dp)}{NB}%"


def day(d: str, year: bool = False) -> str:
    return pd.Timestamp(d).strftime("%#d-%b-%Y" if year else "%#d-%b")


def month_name(d: str) -> str:
    return pd.Timestamp(d).strftime("%B")


def contract_month(ym: str) -> str:
    return pd.Timestamp(f"{ym}-01").strftime("%b")


NUM_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def count_word(k: int) -> str:
    """Small counts read better as words at the start of a sentence; a word carries no digit to trace."""
    return NUM_WORDS.get(k, str(k))


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def join_names(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def cut_words(title: str, n: int = HEADLINE_MAX_WORDS) -> str:
    w = str(title).split()
    return " ".join(w) if len(w) <= n else " ".join(w[:n]) + " …"


def _s(x) -> str:
    """Normalise a date-like cell to 'YYYY-MM-DD' (or '' for missing)."""
    if x is None or (isinstance(x, float) and math.isnan(x)) or str(x).strip() in ("", "nan", "NaT"):
        return ""
    return str(x).strip()[:10]


def _f(x) -> float:
    return float(str(x).replace(",", ""))


def _split(x, sep: str = "|") -> list[str]:
    return [p.strip() for p in str(x).split(sep)] if isinstance(x, str) else []


# ------------------------------------------------------------------------------------------------ provenance ledger
@dataclass(frozen=True)
class Fact:
    """One printed number (or data identifier) and where it came from.

    op: level (one cell) | sum (a column summed over date_from < date <= date) | change (cell at date minus cell at
    date_from) | pct_change | config (a registered parameter) | derived (arithmetic on recorded inputs; `column`
    names the formula) | ident (text taken verbatim from a table cell).
    """

    text: str
    value: object
    table: str
    column: str
    date: str
    key: tuple = ()
    op: str = "level"
    date_from: str = ""


@dataclass
class Ledger:
    week_end: str
    facts: list[Fact] = field(default_factory=list)

    def put(self, text: str, value, table: str, column: str, date: str, key: Mapping | None = None, op: str = "level",
            date_from: str = "") -> str:
        d = _s(date) if date != "static" else "static"
        if d not in ("static", "") and d > self.week_end:
            raise ValueError(f"fact {text!r} from {table}.{column} is dated {d}, after the note's week end {self.week_end}")
        self.facts.append(Fact(text, value, table, column, d, tuple(sorted((key or {}).items())), op, date_from))
        return text


# ------------------------------------------------------------------------------------------------ week ends
def week_friday(d: str) -> str:
    t = pd.Timestamp(d)
    return (t + pd.Timedelta(days=(FRIDAY - t.weekday()) % 7)).strftime("%Y-%m-%d")


def select_week_ends(panel_dates: list[str]) -> list[str]:
    """Last Friday of each month in the window -> that W-FRI week's last LME trading day (declared rule, see docstring)."""
    days = sorted(panel_dates)
    out = []
    for y, mth in pd.period_range(WINDOW_START, WINDOW_END, freq="M").map(lambda p: (p.year, p.month)):
        last = dt.date(y, mth, calendar.monthrange(y, mth)[1])
        fri = last - dt.timedelta(days=(last.weekday() - FRIDAY) % 7)
        week_start = (fri - dt.timedelta(days=6)).isoformat()
        cands = [d for d in days if week_start <= d <= fri.isoformat()]
        if not cands:
            raise ValueError(f"no LME trading day in the week ending {fri}")
        out.append(cands[-1])
    if len(out) != N_NOTES:
        raise ValueError(f"expected {N_NOTES} week ends, got {len(out)}")
    return out


def previous_close(panel_dates: list[str], week_end: str) -> str:
    """Last LME day of the previous W-FRI week: the base for every 'on the week' move."""
    prev_fri = (pd.Timestamp(week_friday(week_end)) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    return max(d for d in panel_dates if d <= prev_fri)


# ------------------------------------------------------------------------------------------------ sources
# Every frame is row-dated: AS_OF names the column holding the date its information became known.
AS_OF = {
    "mkt": "date", "att": "date", "exp": "date", "var_ante": "position_date", "var_post": "date",
    "credit": "date", "bookings": "contract_date", "liq": "date", "parity": "value_date", "term": "value_date",
    "sent": "lme_close_date", "heads": "published_date", "elig": "trade_date", "tickets": "trade_date",
    "sales": "contract_date", "lines": "entry_date", "exits": "exit_date", "fwds": "booking_date",
    "fixtures": "booking_date", "lc": "lc_open_date", "lots": "bl_date", "arrivals": "date", "releases": "date",
    "maturities": "bl_date", "cash": "settle_date", "incidents": "known_date", "recovery": "value_date",
}


def _read(path: Path, usecols=None, **kw) -> pd.DataFrame:
    return pd.read_csv(path, usecols=usecols, **kw)


def load_sources() -> dict[str, pd.DataFrame]:
    """Load every input once, reshaped into row-dated frames (see AS_OF); hindsight columns are never loaded."""
    T = TABLES_DIR
    src: dict[str, pd.DataFrame] = {}
    src["mkt"] = _read(PROCESSED_DIR / "market_daily.csv",
                       ["date", "lme_cash_usd_t", "lme_3m_usd_t", "lme_cash_3m_spread_usd_t", "usdinr",
                        "fwd_premium_3m_pa", "mcx_al_m1_inr_kg", "freight_jea_nsa_usd_t", "freight_usec_mun_usd_t"])
    src["att"] = _read(T / "attribution_daily.csv", ["date", "trade_id", *PNL_COLS, "residual", "daily_pnl_inr",
                                                     "cum_pnl_inr"])
    src["exp"] = _read(T / "book_exposures_daily.csv",
                       ["date", "scope", "trade_id", "cum_pnl_inr", "cash_balance_inr", "mcx_im_inr", "lme_delta_mt",
                        "lme_delta_physical_mt", "lme_delta_mcx_mt", "hedge_ratio_lme_frac", "mcx_lots_open",
                        "fx_delta_physical_usd", "fx_delta_forwards_usd", "fx_delta_mcx_usd", "freight_open_boxes",
                        "unsold_mt", "phys_sold_mt"])
    src["exp"] = src["exp"][src["exp"]["scope"] == "book"].reset_index(drop=True)
    var_cols = ["date", "position_date", "position_held", "position_date_mcx_exit_or_roll", "sigma_lme_garch_frac",
                "sigma_lme_hist250_frac", "sigma_fx_garch_frac", "var_garch_inr", "var_hist250_inr", "var_hist60_inr"]
    # Ex-ante columns only: a row dated t is the forecast made at the close of position_date (docs/40 §5.2).
    src["var_ante"] = _read(T / "var_daily.csv", var_cols)
    # Realised side of the backtest, known at the close of the row's own date.
    src["var_post"] = _read(T / "var_daily.csv", ["date", "position_held", "exception_garch", "exception_hist250"])
    src["credit"] = _read(T / "credit_tracker.csv",
                          ["date", "cp_id", "role", "credit_limit_inr", "credit_exposure_inr", "utilisation_frac",
                           "advance_reliance_multiple", "days_past_due", "band_final", "overlay_notches",
                           "flag_soft_utilisation"])
    src["credit"] = src["credit"][src["credit"]["role"] == "BUYER"].reset_index(drop=True)
    src["bookings"] = _read(T / "credit_tracker_bookings.csv",
                            ["contract_date", "trade_id", "sale_id", "cp_id", "p04_utilisation_after_frac",
                             "advance_reliance_multiple", "credit_days", "band_final_prev_close",
                             "band_max_credit_utilisation_frac", "band_max_advance_reliance_multiple",
                             "band_max_credit_days", "band_policy_verdict"])
    src["liq"] = _read(T / "margin_liquidity.csv",
                       ["date", "net_margin_cash_inr", "mcx_im_inr", "funding_need_total_inr", "fb_limit_inr",
                        "min_cash_buffer_inr", "headroom_inr", "flag_buffer_breach", "flag_fb_limit_breach",
                        "lc_outstanding_inr", "lc_limit_inr", "flag_lc_limit_breach", "stress_move_up_logret",
                        "stress_binding_up", "mar_99_inr", "flag_mar_exceeds_buffer"])
    src["parity"] = _read(T / "parity_weekly.csv",
                          ["week_end", "value_date", "grade", "lane", "net_arb_inr_t", "net_arb_pit_mix_inr_t",
                           "trade_eligible"])
    src["recovery"] = _read(T / "parity_weekly.csv", ["value_date", "grade", "recovery_frac"])
    src["term"] = _read(T / "term_structure_weekly.csv",
                        ["week_end", "value_date", "lme_cash_3m_spread_usd_t", "structure",
                         "mplus1_implied_minus_3m_usd_t"])
    src["sent"] = _read(T / "sentiment_weekly.csv", ["week_end", "lme_close_date", "n", "mean", "se", "z_score"])
    heads = _read(T / "sentiment_headlines_scored.csv",
                  ["week_end", "published_utc", "source", "title", "core_chain", "cites_later_date", "vader_compound"])
    heads["published_date"] = heads["published_utc"].str[:10]
    src["heads"] = heads
    src["elig"] = _read(T / "trade_eligibility_check.csv",
                        ["trade_id", "trade_date", "parity_week_end_used", "trade_eligible", "net_arb_inr_t",
                         "net_arb_pit_mix_inr_t", "net_arb_conv18k_inr_t", "margin_threshold_inr_t"])
    src["robust"] = _read(T / "pnl_sensitivity_sign_robustness.csv", ["family", "base_value"])

    book = _read(T / "trade_book.csv", dtype=str)
    src.update(_book_frames(book))
    hedges = _read(T / "trade_hedges.csv",
                   ["trade_id", "instrument", "hedge_id", "contract_month", "roll_deadline", "direction", "lots",
                    "entry_date", "exit_date", "exit_reason", "roll_to", "entry_price_inr_kg", "exit_price_inr_kg",
                    "hedge_ratio_target", "sizing_basis", "notional_usd", "booking_date", "matched_leg", "rate_inr",
                    "index_usd_box_at_fixture", "fixture_vs_index_frac"])
    src.update(_hedge_frames(hedges, book))
    cf = _read(T / "trade_cashflows.csv",
               ["scenario", "trade_id", "leg_id", "cf_type", "fixing_date", "settle_date", "amount_ccy", "currency",
                "amount_inr", "event_ids"])
    src["cash"] = cf[(cf["scenario"] == "REALISED") & cf["cf_type"].isin(
        ["SALE_ADVANCE", "SALE_BALANCE", "PURCHASE_INVOICE", "PURCHASE_PROVISIONAL", "PURCHASE_FINAL"])
        & (cf["amount_ccy"].abs() > 0)].reset_index(drop=True)
    src["incidents"] = _incident_frame(book, cf)
    for name, col in AS_OF.items():
        src[name][col] = src[name][col].map(_s)
    return src


def _book_frames(book: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """trade_book.csv (one wide row per ticket) -> purchase, sale, LC, lot-milestone and maturity rows, each dated."""
    tickets, sales, lcs, lots, arrivals, releases, maturities = [], [], [], [], [], [], []
    for r in book.itertuples(index=False):
        tickets.append({
            "trade_id": r.trade_id, "trade_date": r.trade_date, "grade": r.grade, "lane": r.lane,
            "quantity_mt": _f(r.quantity_mt), "boxes": int(_f(r.boxes)), "box_type": r.box_type,
            "supplier_name": r.supplier_name, "incoterm": r.incoterm, "named_place": r.named_place,
            "discharge_port": r.discharge_port, "pricing": r.purchase_pricing_type,
            "price_usd_t": _f(r.purchase_price_usd_t) if isinstance(r.purchase_price_usd_t, str) else np.nan,
            "factor_frac": _f(r.purchase_factor_frac) if isinstance(r.purchase_factor_frac, str) else np.nan,
            "provisional_frac": _f(r.provisional_frac) if isinstance(r.provisional_frac, str) else np.nan,
            "qp_start": _s(r.pricing_period_start), "qp_end": _s(r.pricing_period_end),
            "payment_instrument": r.payment_instrument,
            "usance_days": int(_f(r.usance_days)) if isinstance(r.usance_days, str) else 0,
            "lc_confirmed": r.lc_confirmed == "True",
        })
        lcs.append({"trade_id": r.trade_id, "lc_open_date": r.lc_open_date, "payment_instrument": r.payment_instrument,
                    "usance_days": int(_f(r.usance_days)) if isinstance(r.usance_days, str) else 0,
                    "lc_confirmed": r.lc_confirmed == "True"})
        lot_ids, boxes = _split(r.lot_ids), [int(_f(b)) for b in _split(r.lot_boxes)]
        payload = _f(r.payload_mt_per_box)
        lot_mt = {lid: b * payload for lid, b in zip(lot_ids, boxes)}
        for lid, bl, arr, rel in zip(lot_ids, _split(r.bl_dates), _split(r.arrival_dates), _split(r.release_dates)):
            lots.append({"trade_id": r.trade_id, "lot_id": lid, "bl_date": bl, "port": r.discharge_port})
            arrivals.append({"trade_id": r.trade_id, "lot_id": lid, "date": arr, "port": r.discharge_port})
            releases.append({"trade_id": r.trade_id, "lot_id": lid, "date": rel, "port": r.discharge_port})
        if r.payment_instrument == "LC_USANCE":
            for lid, bl, mat in zip(lot_ids, _split(r.bl_dates), _split(r.usance_maturity_dates)):
                maturities.append({"trade_id": r.trade_id, "lot_id": lid, "bl_date": bl, "maturity_date": mat})
        cols = {c: _split(getattr(r, c)) for c in
                ("sale_ids", "buyer_ids", "buyer_names", "sale_contract_dates", "sale_lot_ids", "sale_pricing_types",
                 "sale_price_inr_t", "sale_pricing_window", "sale_factor_frac", "sale_premium_inr_t",
                 "sale_payment_terms", "sale_credit_days", "sale_advance_frac")}
        for i, sid in enumerate(cols["sale_ids"]):
            def g(c, i=i):
                v = cols[c]
                return v[i] if i < len(v) else ""
            win = g("sale_pricing_window").split("..") if ".." in g("sale_pricing_window") else ["", ""]
            sales.append({
                "trade_id": r.trade_id, "sale_id": sid, "buyer_id": g("buyer_ids"), "buyer_name": g("buyer_names"),
                "contract_date": g("sale_contract_dates"), "grade": r.grade,
                "quantity_mt": sum(lot_mt[x] for x in g("sale_lot_ids").split("+")),
                "pricing": g("sale_pricing_types"),
                "price_inr_t": _f(g("sale_price_inr_t")) if g("sale_price_inr_t") else np.nan,
                "window_start": win[0], "window_end": win[1],
                "factor_frac": _f(g("sale_factor_frac")) if g("sale_factor_frac") else np.nan,
                "premium_inr_t": _f(g("sale_premium_inr_t")) if g("sale_premium_inr_t") else np.nan,
                "payment_terms": g("sale_payment_terms"),
                "credit_days": int(_f(g("sale_credit_days"))) if g("sale_credit_days") else 0,
                "advance_frac": _f(g("sale_advance_frac")) if g("sale_advance_frac") else 0.0,
            })
    return {"tickets": pd.DataFrame(tickets), "sales": pd.DataFrame(sales), "lc": pd.DataFrame(lcs),
            "lots": pd.DataFrame(lots), "arrivals": pd.DataFrame(arrivals), "releases": pd.DataFrame(releases),
            "maturities": pd.DataFrame(maturities, columns=["trade_id", "lot_id", "bl_date", "maturity_date"])}


def _hedge_frames(h: pd.DataFrame, book: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """trade_hedges.csv -> MCX entry rows, MCX exit rows (dated on the exit), forward bookings and freight fixtures."""
    mcx = h[h["instrument"] == "MCX_ALUMINIUM_FUTURE"].copy()
    # an entry row carries nothing decided later: the exit, its reason and the roll target live on the exit row
    lines = mcx.drop(columns=["exit_date", "exit_reason", "exit_price_inr_kg", "roll_to"]).copy()
    lines["is_roll_in"] = lines["hedge_id"].isin(set(mcx["roll_to"].dropna()))
    exits = mcx[["trade_id", "hedge_id", "contract_month", "direction", "lots", "exit_date", "exit_reason", "roll_to",
                 "exit_price_inr_kg"]].copy()
    fwds = h[h["instrument"] == "USDINR_FORWARD"][["trade_id", "hedge_id", "direction", "notional_usd", "booking_date",
                                                   "matched_leg", "rate_inr"]].copy()
    fx = h[h["instrument"] == "FREIGHT_FIXTURE"][["trade_id", "hedge_id", "lots", "booking_date",
                                                   "index_usd_box_at_fixture", "fixture_vs_index_frac"]].copy()
    rate = book.set_index("trade_id")[["freight_rate_usd_box", "freight_stop_loss_usd_box", "box_type"]]
    fx = fx.join(rate, on="trade_id")
    return {"lines": lines.reset_index(drop=True), "exits": exits.reset_index(drop=True),
            "fwds": fwds.reset_index(drop=True), "fixtures": fx.reset_index(drop=True)}


def _incident_frame(book: pd.DataFrame, cf: pd.DataFrame) -> pd.DataFrame:
    """Simulated operational events, dated on the day the desk learns of them.

    Logistics and payment-delay events carry `known_date` in config/trades.yaml. A quality survey carries no
    known_date; the desk learns the out-turn on the survey (the QUALITY_CLAIM fixing date the engine books).
    """
    raw = yaml.safe_load((CONFIG_DIR / "trades.yaml").read_text(encoding="utf-8"))
    rows = []
    for t in raw["trades"]:
        ev = t.get("events") or {}
        for e in ev.get("logistics") or []:
            full = " ".join(str(e.get("real_trigger_ref", "")).split())
            ref = full.split(" (")[0].split(" — ")[0].strip()
            ref += " (real mechanism)" if "mechanism is real" in full else " (real)"
            rows.append({"trade_id": t["trade_id"], "kind": "LOGISTICS", "event_id": e["event_id"],
                         "lot_id": e["lot_id"], "known_date": str(e["known_date"]), "ref": ref,
                         "arrival_delay_days": int(e.get("arrival_delay_days", 0)),
                         "extra_dwell_days": int(e.get("extra_dwell_days", 0)), "detail": ""})
        for e in ev.get("buyer_payment_delay") or []:
            rows.append({"trade_id": t["trade_id"], "kind": "PAY_DELAY", "event_id": e["event_id"],
                         "lot_id": e.get("sale_id", ""), "known_date": str(e["known_date"]), "ref": "",
                         "arrival_delay_days": int(e.get("delay_days", 0)), "extra_dwell_days": 0, "detail": ""})
        for q in ev.get("quality") or []:
            claim = cf[(cf["scenario"] == "REALISED") & (cf["trade_id"] == t["trade_id"])
                       & (cf["cf_type"] == "QUALITY_CLAIM") & (cf["event_ids"] == f"QUALITY:{q['lot_id']}")]
            if claim.empty:
                continue
            rows.append({"trade_id": t["trade_id"], "kind": "QUALITY", "event_id": f"{t['trade_id']}-Q-{q['lot_id']}",
                         "lot_id": q["lot_id"], "known_date": str(claim["fixing_date"].iloc[0]), "ref": "",
                         "arrival_delay_days": int(q.get("rejected_boxes", 0)), "extra_dwell_days": 0,
                         "detail": f"{q.get('moisture_actual_frac', '')}|{q.get('contamination_actual_frac', '')}|"
                                   f"{q.get('rejection_reason', '')}|{q.get('claim_recovery_frac', '')}"})
    cols = ["trade_id", "kind", "event_id", "lot_id", "known_date", "ref", "arrival_delay_days", "extra_dwell_days",
            "detail"]
    return pd.DataFrame(rows, columns=cols).sort_values(["known_date", "event_id"]).reset_index(drop=True)


def as_of(src: Mapping[str, pd.DataFrame], week_end: str) -> dict[str, pd.DataFrame]:
    """The only view a note is built from: every row whose information date is after `week_end` is gone."""
    out = {}
    for name, df in src.items():
        if name in AS_OF:
            out[name] = df[(df[AS_OF[name]] != "") & (df[AS_OF[name]] <= week_end)].reset_index(drop=True)
        else:
            out[name] = df
    return out


# ------------------------------------------------------------------------------------------------ helpers on the view
def _one(df: pd.DataFrame, what: str) -> pd.Series:
    if len(df) != 1:
        raise ValueError(f"expected exactly one row for {what}, found {len(df)}")
    return df.iloc[0]


def in_week(df: pd.DataFrame, col: str, prev: str, week_end: str) -> pd.DataFrame:
    return df[(df[col] > prev) & (df[col] <= week_end)]


def sale_slope_inr_per_premium(sales: pd.DataFrame, recovery: pd.DataFrame, share: float) -> pd.Series:
    """₹ of P&L per ₹/t of domestic premium, per sale: the S1 sale rule moves price by share x recovery x Δpremium."""
    rec = recovery.sort_values("value_date").groupby("grade")["recovery_frac"].last()
    return sales["quantity_mt"] * share * sales["grade"].map(rec)


# ------------------------------------------------------------------------------------------------ the note
@dataclass
class Context:
    n: int
    week_end: str
    prev: str
    month_start: str
    S: dict
    L: Ledger
    flags: dict = field(default_factory=dict)


def build_note(src: Mapping[str, pd.DataFrame], n: int, week_end: str, panel_dates: list[str]) -> tuple[str, Ledger, dict]:
    """Markdown for note n as of `week_end`, its provenance ledger and chart inputs."""
    prev = previous_close(panel_dates, week_end)
    ctx = Context(n=n, week_end=week_end, prev=prev, month_start=week_end[:8] + "01", S=as_of(src, week_end),
                  L=Ledger(week_end))
    saw = section_saw(ctx)
    did = section_did(ctx)
    pnl = section_pnl(ctx)
    risks = section_risks(ctx)
    head = section_header(ctx)
    foot = section_footnotes(ctx)
    md = "\n\n".join([head, "## What I saw", CHART_SLOT, saw, "## What I did", did, "## P&L attribution", pnl,
                      "## Risks next week", risks, FOOTNOTES, foot]) + "\n"
    chart = {"mkt": ctx.S["mkt"], "att": ctx.S["att"], "tickets": ctx.S["tickets"], "sales": ctx.S["sales"]}
    return md, ctx.L, chart


# ---- header
def section_header(c: Context) -> str:
    L, W = c.L, c.week_end
    title = (f"# Desk note {c.n} — week ending {L.put(day(W, True), W, 'market_daily', 'date', W, op='ident')}")
    written = (f"**{DESK_NAME}** · To: Head of Trading (SIM) · From: scrap desk (SIM) · Written after the "
               f"{L.put(day(W, True), W, 'market_daily', 'date', W, op='ident')} close; uses no price, position, trade "
               "or event dated later. The anchor premium, grade factors, freight levels and the INR 3M rate are "
               "reconstructions that use later publications (footnotes).")
    callout = (f"> **{SIM_LABEL}.** Counterparties, vessels, tickets and operational events are simulated. LME prices "
               "are DIRECT; USD/INR and MCX are PROXY; grade factors and freight levels are hindsight reconstructions "
               f"(footnotes). **Bottom line:** {bottom_line(c)}")
    return "\n\n".join([title, written, callout])


def bottom_line(c: Context) -> str:
    """Up to four fragments, in a fixed priority order, each chosen by a data condition."""
    fl = c.flags
    parts = []
    if fl.get("fb_breach"):
        parts.append("the funding need is over the working-capital line, and that is the constraint on everything")
    elif fl.get("buffer_breach"):
        parts.append("we are inside the cash buffer")
    buys, sells = fl.get("buys", []), fl.get("sells", [])
    act = ([f"bought {join_names(buys)}"] if buys else []) + ([f"sold {join_names(sells)}"] if sells else [])
    parts.append(" and ".join(act) if act else "no new tickets")
    if fl.get("z") is not None and abs(fl["z"]) >= SIGMA_BIG:
        parts.append(f"LME had a {'big up' if fl['z'] > 0 else 'heavy down'} week")
    if fl.get("flip"):
        parts.append(f"the LME curve flipped to {fl['flip'].lower()}")
    if fl.get("open_position"):
        parts.append(f"the book is running {fl['open_position']} metal the hedge does not cover")
    if fl.get("lc_breach"):
        parts.append("the LC line is over its limit")
    if fl.get("soft_credit"):
        parts.append(f"{fl['soft_credit']} over the credit early-warning line")
    if fl.get("mar_over_buffer") and not fl.get("fb_breach"):
        parts.append("a 99 % margin call would be bigger than the cash buffer")
    if fl.get("advance_over_line"):
        parts.append("the credit risk that matters is advance reliance, not receivables")
    if fl.get("eligible") == 0:
        parts.append("the parity window is shut")
    elif fl.get("eligible") is not None and fl.get("eligible") == fl.get("cases"):
        parts.append("the parity board is wide open")
    elif fl.get("eligible"):
        parts.append(f"only {count_word(fl['eligible'])} of the {count_word(fl['cases'])} parity cases clear all three screens")
    if fl.get("fully_sold"):
        parts.append("the book is fully sold")
    text = "; ".join(parts[:4])
    return cap(text) + "."


# ---- what I saw
def section_saw(c: Context) -> str:
    S, L, W, P = c.S, c.L, c.week_end, c.prev
    mk = S["mkt"]
    r = _one(mk[mk["date"] == W], f"market_daily {W}")
    p = _one(mk[mk["date"] == P], f"market_daily {P}")
    bullets = []

    # LME level, weekly move, sigma, record
    cash, cash_p = float(r["lme_cash_usd_t"]), float(p["lme_cash_usd_t"])
    n_ret = int(((mk["date"] > P) & (mk["date"] <= W)).sum())
    first = mk[mk["date"] > P]["date"].iloc[0]
    va = S["var_ante"]
    sig = float(_one(va[(va["date"] == first) & (va["position_date"] == P)], "GARCH week-start")["sigma_lme_garch_frac"])
    z = math.log(cash / cash_p) / (sig * math.sqrt(n_ret))
    c.flags["z"] = z
    rec_i = mk["lme_cash_usd_t"].idxmax()
    rec, rec_d = float(mk.loc[rec_i, "lme_cash_usd_t"]), mk.loc[rec_i, "date"]
    t = (f"**LME.** Cash closed USD{NB}{L.put(num(cash, 1 if cash % 1 else 0), cash, 'market_daily', 'lme_cash_usd_t', W)}/t "
         f"({L.put(signed(cash - cash_p, 1 if (cash - cash_p) % 1 else 0), cash - cash_p, 'market_daily', 'lme_cash_usd_t', W, op='change', date_from=P)} "
         f"on the week, {L.put(pct(cash / cash_p - 1, 1, True), cash / cash_p - 1, 'market_daily', 'lme_cash_usd_t', W, op='pct_change', date_from=P)}); "
         f"3M USD{NB}{L.put(num(float(r['lme_3m_usd_t']), 1 if float(r['lme_3m_usd_t']) % 1 else 0), float(r['lme_3m_usd_t']), 'market_daily', 'lme_3m_usd_t', W)}. ")
    zt = L.put(num(abs(z), 1), z, "var_daily+market_daily", "ln(cash/cash_prev)/(sigma_lme_garch_frac*sqrt(days))", W,
               op="derived")
    if abs(z) >= SIGMA_BIG:
        t += (f"A {zt}-sigma {'rally' if z > 0 else 'sell-off'} against the vol our GARCH forecast going into the week — "
              f"{'metal ripped' if z > 0 else 'heavy tape'}. ")
    elif abs(z) >= SIGMA_NOTABLE:
        t += f"{'Firm' if z > 0 else 'Soft'} week, {zt} sigma on our GARCH vol: a real move, but inside what this vol allows. "
    else:
        t += f"Inside the noise at {zt} sigma on our GARCH vol. "
    if cash >= rec:
        t += "A record close."
    else:
        t += (f"Still {L.put(pct(1 - cash / rec, 1), 1 - cash / rec, 'market_daily', 'lme_cash_usd_t (max to date)', W, op='derived')} "
              f"under the {L.put(day(rec_d), rec_d, 'market_daily', 'date', rec_d, op='ident')} record close of "
              f"USD{NB}{L.put(num(rec, 1 if rec % 1 else 0), rec, 'market_daily', 'lme_cash_usd_t', rec_d)}.")
    bullets.append(t)

    # Cash-3M structure
    term = S["term"]
    tr = _one(term[term["value_date"] == W], f"term_structure_weekly {W}")
    tp = _one(term[term["value_date"] == P], f"term_structure_weekly {P}")
    spr, spr_p = float(tr["lme_cash_3m_spread_usd_t"]), float(tp["lme_cash_3m_spread_usd_t"])
    impl = float(tr["mplus1_implied_minus_3m_usd_t"])
    structure = str(tr["structure"])
    same = structure == str(tp["structure"])
    move = ("unchanged from" if spr == spr_p else
            ("wider than" if abs(spr) > abs(spr_p) else "narrower than") if same else "flipped from")
    t = (f"**Cash–3M.** {L.put(signed(spr, 1), spr, 'term_structure_weekly', 'lme_cash_3m_spread_usd_t', W)} USD/t, "
         f"{structure.lower()}, {move} {L.put(signed(spr_p, 1), spr_p, 'term_structure_weekly', 'lme_cash_3m_spread_usd_t', P)} "
         "a week ago. ")
    if structure != str(tp["structure"]):
        c.flags["flip"] = structure
        before = term[(term["value_date"] < W) & (term["structure"] == structure)]
        if len(before):
            ld = before["value_date"].iloc[-1]
            t += (f"First {structure.lower()} on our weekly read since "
                  f"{L.put(day(ld), ld, 'term_structure_weekly', 'value_date', ld, op='ident')}. ")
    tk = S["tickets"]
    floating = tk[(tk["pricing"] == "LME_M1_AVG") & (tk["qp_end"] > W)]["trade_id"].tolist()
    who = (f"our cash-average purchases ({join_names([L.put(x, x, 'trade_book', 'trade_id', W, op='ident') for x in floating])})"
           if floating else "a cash-average purchase")
    plural = bool(floating)
    impl_t = L.put(num(abs(impl), 1), impl, "term_structure_weekly", "mplus1_implied_minus_3m_usd_t", W)
    if spr < 0:
        t += (f"M+1 cash averaging implies USD{NB}{impl_t}/t under 3M, so {who} {'price' if plural else 'prices'} below the 3M screen in "
              "expectation. On the LME a short rolled forward earns the carry; our MCX proxy is in contango by "
              "construction, so I bank no roll gain from it².")
    else:
        t += (f"Nearby metal is tight: M+1 cash averaging implies USD{NB}{impl_t}/t over 3M, so {who} {'cost' if plural else 'costs'} more than "
              "the 3M screen, and on the LME a short rolled forward now pays the spread. No reason to hold metal for "
              "carry.")
    bullets.append(t)

    # Rupee (+ MCX)
    fx, fx_p = float(r["usdinr"]), float(p["usdinr"])
    sig_fx = float(_one(va[(va["date"] == first) & (va["position_date"] == P)], "FX week-start")["sigma_fx_garch_frac"])
    zfx = math.log(fx / fx_p) / (sig_fx * math.sqrt(n_ret))
    yr = mk[mk["date"] >= W[:4] + "-01-01"]
    t = (f"**Rupee.** USD/INR {L.put(num(fx, 2), fx, 'market_daily', 'usdinr', W)} "
         f"({L.put(signed((fx - fx_p) * 100, 0), (fx - fx_p) * 100, 'market_daily', 'usdinr (paise)', W, op='derived')} "
         f"paise on the week); 3M forward premium⁸ "
         f"{L.put(pct(float(r['fwd_premium_3m_pa']), 2), float(r['fwd_premium_3m_pa']), 'market_daily', 'fwd_premium_3m_pa', W)} a year. ")
    if fx >= float(yr["usdinr"].max()):
        t += "A fresh closing high for the year on our series: the slide is intact. "
    elif zfx >= SIGMA_NOTABLE:
        t += "Rupee under pressure. "
    elif zfx <= -SIGMA_NOTABLE:
        t += "Rupee firmer. "
    else:
        t += "Rupee steady. "
    m1, m1_p = float(r["mcx_al_m1_inr_kg"]), float(p["mcx_al_m1_inr_kg"])
    t += (f"MCX² near month ₹{L.put(num(m1, 2), m1, 'market_daily', 'mcx_al_m1_inr_kg', W)}/kg "
          f"({L.put(pct(m1 / m1_p - 1, 1, True), m1 / m1_p - 1, 'market_daily', 'mcx_al_m1_inr_kg', W, op='pct_change', date_from=P)}).")
    bullets.append(t)

    # Freight
    jea, usec = float(r["freight_jea_nsa_usd_t"]), float(r["freight_usec_mun_usd_t"])
    four = max(d for d in mk["date"] if d <= (pd.Timestamp(W) - pd.Timedelta(days=28)).strftime("%Y-%m-%d"))
    usec4 = float(_one(mk[mk["date"] == four], "freight 4w")["freight_usec_mun_usd_t"])
    t = (f"**Freight¹.** Gulf lane USD{NB}{L.put(num(jea, 2), jea, 'market_daily', 'freight_jea_nsa_usd_t', W)}/t, US East "
         f"Coast USD{NB}{L.put(num(usec, 2), usec, 'market_daily', 'freight_usec_mun_usd_t', W)}/t; "
         f"{L.put(pct(usec / usec4 - 1, 1, True), usec / usec4 - 1, 'market_daily', 'freight_usec_mun_usd_t', W, op='pct_change', date_from=four)} "
         "in four weeks. ")
    fob = tk[tk["incoterm"] == "FOB"]["trade_id"]
    fixed = set(S["fixtures"]["trade_id"])
    open_fob = [x for x in fob if x not in fixed]
    if open_fob:
        t += (f"Still to fix: {join_names([L.put(x, x, 'trade_book', 'trade_id', W, op='ident') for x in open_fob])} — "
              f"{'a falling market is paying me to wait' if usec < usec4 else 'rates are not helping; fix before the stop'}.")
    else:
        t += ("Nothing open to fix: FOB freight is booked and CFR cargo carries it in the price"
              + ("; the slide only helps the next FOB bid." if usec < usec4 else "."))
    bullets.append(t)

    # Headlines
    sent = S["sent"]
    sw = sent[sent["week_end"] == week_friday(W)]
    if len(sw):
        s = sw.iloc[0]
        zt = s["z_score"]
        t = (f"**Headlines³.** Mean VADER tone {L.put(signed(float(s['mean']), 2), float(s['mean']), 'sentiment_weekly', 'mean', W, key={'week_end': s['week_end']})} "
             f"on {L.put(num(float(s['n'])), int(s['n']), 'sentiment_weekly', 'n', W, key={'week_end': s['week_end']})} "
             f"headlines (s.e. {L.put(num(float(s['se']), 2), float(s['se']), 'sentiment_weekly', 'se', W, key={'week_end': s['week_end']})}")
        if pd.isna(zt):
            t += "; too few past weeks for a z-score): colour, not a signal. "
        else:
            zs = L.put(signed(float(zt), 2), float(zt), "sentiment_weekly", "z_score", W, key={"week_end": s["week_end"]})
            if abs(float(zt)) < Z_SIGNIFICANT:
                t += f", z {zs} against past weeks): inside the noise — colour, not a signal. "
            else:
                t += (f", z {zs}): unusually {'upbeat' if float(zt) > 0 else 'downbeat'} for this series; still colour, "
                      "not a signal. ")
        hd = S["heads"]
        known = hd.groupby("source").size()   # headlines per publisher published up to this close (as_of view)
        hd = hd[(hd["week_end"] == s["week_end"]) & hd["core_chain"].astype(bool) & ~hd["cites_later_date"].astype(bool)
                & (hd["vader_compound"].abs() >= VADER_NEUTRAL)
                & (hd["source"].map(known) >= PUBLISHER_MIN_HEADLINES)].copy()
        if len(hd):
            hd["_abs"] = hd["vader_compound"].abs()
            h = hd.sort_values(["_abs", "published_utc", "title"], ascending=[False, True, True]).iloc[0]
            key = {"title": h["title"]}
            t += (f"Loudest aluminium-chain headline from a regular publisher: “{L.put(cut_words(h['title']), h['title'], 'sentiment_headlines_scored', 'title', h['published_date'], key=key, op='ident')}” "
                  f"({L.put(str(h['source']), h['source'], 'sentiment_headlines_scored', 'source', h['published_date'], key=key, op='ident')}, "
                  f"VADER {L.put(signed(float(h['vader_compound']), 2), float(h['vader_compound']), 'sentiment_headlines_scored', 'vader_compound', h['published_date'], key=key)}).")
        bullets.append(t)
    return "\n".join(f"- {b.strip()}" for b in bullets)


# ---- what I did
def _qty(L: Ledger, x: float, table: str, col: str, d: str, key: Mapping, op: str = "level") -> str:
    return L.put(num(x), x, table, col, d, key=key, op=op)


def purchase_line(c: Context, t: pd.Series) -> str:
    L, W = c.L, c.week_end
    k = {"trade_id": t["trade_id"]}
    d = t["trade_date"]
    tid = L.put(t["trade_id"], t["trade_id"], "trade_book", "trade_id", d, key=k, op="ident")
    if t["pricing"] == "FIXED":
        price = f"USD{NB}{L.put(num(t['price_usd_t']), t['price_usd_t'], 'trade_book', 'purchase_price_usd_t', d, key=k)}/t fixed"
    else:
        price = (f"{L.put(num(t['factor_frac'], 3), t['factor_frac'], 'trade_book', 'purchase_factor_frac', d, key=k)} × "
                 "LME cash average of the month after shipment, "
                 f"{L.put(pct(t['provisional_frac'], 0), t['provisional_frac'], 'trade_book', 'provisional_frac', d, key=k)} provisional")
    pay = ("sight LC" if t["payment_instrument"] == "LC_SIGHT" else
           f"{L.put(num(t['usance_days']), t['usance_days'], 'trade_book', 'usance_days', d, key=k)}-day usance LC")
    el = _one(c.S["elig"][c.S["elig"]["trade_id"] == t["trade_id"]], f"eligibility {t['trade_id']}")
    if not bool(el["trade_eligible"]):
        raise ValueError(f"{t['trade_id']} was not eligible on all three screens; the purchase sentence would be false")
    pw = el["parity_week_end_used"]
    ek = {"trade_id": t["trade_id"]}
    return (f"**Bought {tid}:** {_qty(L, t['quantity_mt'], 'trade_book', 'quantity_mt', d, k)}{NB}MT "
            f"{GRADE_NAMES[t['grade']]}, {LANE_NAMES[t['lane']]}, "
            f"{L.put(num(t['boxes']), t['boxes'], 'trade_book', 'boxes', d, key=k)} × "
            f"{L.put(t['box_type'], t['box_type'], 'trade_book', 'box_type', d, key=k, op='ident')} from "
            f"{L.put(t['supplier_name'], t['supplier_name'], 'trade_book', 'supplier_name', d, key=k, op='ident')}; "
            f"{L.put(t['named_place'], t['named_place'], 'trade_book', 'named_place', d, key=k, op='ident')} at "
            f"{price}, {pay}. It cleared all three parity screens in the week to "
            f"{L.put(day(pw), pw, 'trade_eligibility_check', 'parity_week_end_used', d, key=ek, op='ident')}: "
            f"₹{L.put(num(el['net_arb_inr_t']), el['net_arb_inr_t'], 'trade_eligibility_check', 'net_arb_inr_t', d, key=ek)}/MT base, "
            f"₹{L.put(num(el['net_arb_pit_mix_inr_t']), el['net_arb_pit_mix_inr_t'], 'trade_eligibility_check', 'net_arb_pit_mix_inr_t', d, key=ek)} "
            "point-in-time⁴, "
            f"₹{L.put(num(el['net_arb_conv18k_inr_t']), el['net_arb_conv18k_inr_t'], 'trade_eligibility_check', 'net_arb_conv18k_inr_t', d, key=ek)} "
            f"with conversion stressed (hurdle ₹{L.put(num(el['margin_threshold_inr_t']), el['margin_threshold_inr_t'], 'trade_eligibility_check', 'margin_threshold_inr_t', d, key=ek)})."
            + (" I size to the smallest of the three." if el["net_arb_pit_mix_inr_t"] < PIT_HAIRCUT_FRAC * el["net_arb_inr_t"]
               else ""))


def sale_line(c: Context, s: pd.Series) -> str:
    L = c.L
    d = s["contract_date"]
    k = {"trade_id": s["trade_id"], "sale_id": s["sale_id"]}
    sid = L.put(f"{s['trade_id']}-{s['sale_id']}", f"{s['trade_id']}-{s['sale_id']}", "trade_book", "sale_ids", d, key=k,
                op="ident")
    if s["pricing"] == "FIXED":
        price = f"₹{L.put(num(s['price_inr_t']), s['price_inr_t'], 'trade_book', 'sale_price_inr_t', d, key=k)}/MT fixed"
    else:
        prem = s["premium_inr_t"]
        price = (f"{L.put(num(s['factor_frac'], 3), s['factor_frac'], 'trade_book', 'sale_factor_frac', d, key=k)} × MCX "
                 f"near-month average over the delivery window {'−' if prem < 0 else '+'} "
                 f"₹{L.put(num(abs(prem)), prem, 'trade_book', 'sale_premium_inr_t', d, key=k)}/MT")
    if s["payment_terms"] == "CREDIT":
        pay = f"{L.put(num(s['credit_days']), s['credit_days'], 'trade_book', 'sale_credit_days', d, key=k)}-day credit"
    elif s["advance_frac"] >= 1.0:
        pay = "full advance"
    else:
        pay = (f"{L.put(pct(s['advance_frac'], 0), s['advance_frac'], 'trade_book', 'sale_advance_frac', d, key=k)} advance, "
               f"balance on {L.put(num(s['credit_days']), s['credit_days'], 'trade_book', 'sale_credit_days', d, key=k)}-day credit")
    bk = c.S["bookings"]
    b = _one(bk[(bk["trade_id"] == s["trade_id"]) & (bk["sale_id"] == s["sale_id"])], f"booking {sid}")
    use = float(b["p04_utilisation_after_frac"])
    bkey = {"trade_id": s["trade_id"], "sale_id": s["sale_id"]}
    return (f"**Sold {sid}** to {L.put(s['buyer_name'], s['buyer_name'], 'trade_book', 'buyer_names', d, key=k, op='ident')} "
            f"({L.put(s['buyer_id'], s['buyer_id'], 'trade_book', 'buyer_ids', d, key=k, op='ident')}): "
            f"{_qty(L, s['quantity_mt'], 'trade_book', 'sale_lot_ids x lot_boxes x payload_mt_per_box', d, k, op='derived')}{NB}MT at {price}, {pay}; "
            f"line use after booking {L.put(pct(use, 0), use, 'credit_tracker_bookings', 'p04_utilisation_after_frac', d, key=bkey)} "
            f"on the planned invoice.{band_breach_sentence(c, b)}")


def band_breach_sentence(c: Context, b: pd.Series) -> str:
    """Name the breach when a booking broke the (retrospective) band policy at the previous close; else nothing.

    Only the dimensions actually breached are printed, each as "what the band allows" against "what this sale takes",
    so a reader of the notes in order sees the rule and the sale that overrides it side by side.
    """
    if b["band_policy_verdict"] != "OUTSIDE_BAND_POLICY":
        return ""
    L, d = c.L, b["contract_date"]
    k = {"trade_id": b["trade_id"], "sale_id": b["sale_id"]}
    T = "credit_tracker_bookings"
    allow, takes = [], []
    use, cap_u = float(b["p04_utilisation_after_frac"]), float(b["band_max_credit_utilisation_frac"])
    adv, cap_a = float(b["advance_reliance_multiple"]), float(b["band_max_advance_reliance_multiple"])
    days, cap_d = int(b["credit_days"]), int(b["band_max_credit_days"])
    if use > cap_u:
        allow.append(f"line use to {L.put(pct(cap_u, 0), cap_u, T, 'band_max_credit_utilisation_frac', d, key=k)}")
        takes.append(L.put(pct(use, 0), use, T, "p04_utilisation_after_frac", d, key=k))
    if adv > cap_a:
        allow.append("no advance reliance" if cap_a == 0 else
                     f"advances to {L.put(num(cap_a, 2), cap_a, T, 'band_max_advance_reliance_multiple', d, key=k)}× the line")
        takes.append(f"{L.put(num(adv, 2), adv, T, 'advance_reliance_multiple', d, key=k)}× the line in advances")
    if days > cap_d:
        allow.append("no open credit" if cap_d == 0 else
                     f"credit to {L.put(num(cap_d), cap_d, T, 'band_max_credit_days', d, key=k)} days")
        takes.append(f"{L.put(num(days), days, T, 'credit_days', d, key=k)}-day credit")
    if not allow:
        raise ValueError(f"booking {b['trade_id']}-{b['sale_id']} is OUTSIDE_BAND_POLICY but breaches no cap")
    band = L.put(str(b["band_final_prev_close"]), str(b["band_final_prev_close"]), T, "band_final_prev_close", d, key=k,
                 op="ident")
    return (f" **That breaks the band policy⁵:** band {band} at the previous close allows {join_names(allow)}; this "
            f"sale takes {join_names(takes)}.")


def hedge_lines(c: Context) -> list[str]:
    S, L, P, W = c.S, c.L, c.prev, c.week_end
    out = []
    lines = in_week(S["lines"], "entry_date", P, W)
    exits = in_week(S["exits"], "exit_date", P, W)
    parts: dict[str, list[tuple[str, int, str]]] = {}
    for tid, g in exits.groupby("trade_id", sort=True):
        for (d, reason, cm), gg in g.groupby(["exit_date", "exit_reason", "contract_month"], sort=True):
            lots = float(gg["lots"].sum())
            k = {"trade_id": tid, "exit_date": d, "exit_reason": reason}
            lt = L.put(num(lots), lots, "trade_hedges", "lots", d, key=k, op="derived")
            if reason == "ROLL":
                to = S["lines"][S["lines"]["hedge_id"].isin(gg["roll_to"])]
                to_m = contract_month(to["contract_month"].iloc[0]) if len(to) else "next"
                parts.setdefault(tid, []).append((d, 0, f"rolled {lt} lots {contract_month(cm)}→{to_m}"))
            else:
                px = float(gg["exit_price_inr_kg"].iloc[0])
                parts.setdefault(tid, []).append((d, 0, 
                    f"lifted {lt} {contract_month(cm)} lots at "
                    f"₹{L.put(num(px, 2), px, 'trade_hedges', 'exit_price_inr_kg', d, key={'hedge_id': gg['hedge_id'].iloc[0]})}/kg"))
    for tid, g in lines[~lines["is_roll_in"]].groupby("trade_id", sort=True):
        for (d, direction, cm), gg in g.groupby(["entry_date", "direction", "contract_month"], sort=True):
            lots = float(gg["lots"].sum())
            px = float(gg["entry_price_inr_kg"].iloc[0])
            k = {"hedge_id": gg["hedge_id"].iloc[0]}
            basis = str(gg["sizing_basis"].iloc[0])
            why = ("against the unsold cargo" if basis.startswith("unsold") else
                   "against the floating purchase" if basis.startswith("purchase") else "against the MCX-average sale")
            parts.setdefault(tid, []).append((d, 1,
                f"{'sold' if direction == 'SELL' else 'bought'} "
                f"{L.put(num(lots), lots, 'trade_hedges', 'lots', d, key={'trade_id': tid, 'entry_date': d, 'direction': direction}, op='derived')} "
                f"{contract_month(cm)} lots at ₹{L.put(num(px, 2), px, 'trade_hedges', 'entry_price_inr_kg', d, key=k)}/kg {why}"))
    parts = {t: [x[2] for x in sorted(v, key=lambda y: (y[0], y[1]))] for t, v in parts.items()}
    if parts:
        items = [f"{L.put(t, t, 'trade_hedges', 'trade_id', W, op='ident')} {'; '.join(v)}" for t, v in sorted(parts.items())]
        out.append("**MCX².** " + ". ".join(items) + ".")
    fw = in_week(S["fwds"], "booking_date", P, W)
    if len(fw):
        items = []
        for r in fw.sort_values(["booking_date", "hedge_id"]).itertuples():
            k = {"hedge_id": r.hedge_id}
            leg = {"PURCHASE_INVOICE": "invoice", "PURCHASE_PROVISIONAL": "provisional payment",
                   "PURCHASE_FINAL": "final purchase adjustment", "FREIGHT": "freight"}.get(r.matched_leg, "payable")
            items.append(f"{'bought' if r.direction == 'BUY_USD' else 'sold'} "
                         f"{L.put(usd_m(r.notional_usd), r.notional_usd, 'trade_hedges', 'notional_usd', r.booking_date, key=k)} "
                         f"at {L.put(num(r.rate_inr, 2), r.rate_inr, 'trade_hedges', 'rate_inr', r.booking_date, key=k)} "
                         f"for {L.put(r.trade_id, r.trade_id, 'trade_hedges', 'trade_id', r.booking_date, key=k, op='ident')}'s {leg}")
        shown = items[:MAX_LIST]
        more = len(items) - len(shown)
        out.append("**Forwards⁸.** " + cap("; ".join(shown))
                   + (f"; and {L.put(num(more), more, 'trade_hedges', 'count(forwards)', W, op='derived')} more" if more else "")
                   + ".")
    fx = in_week(S["fixtures"], "booking_date", P, W)
    for r in fx.itertuples():
        k = {"trade_id": r.trade_id}
        out.append(f"**Freight¹.** Fixed {L.put(r.trade_id, r.trade_id, 'trade_hedges', 'trade_id', r.booking_date, key=k, op='ident')}: "
                   f"{L.put(num(r.lots), r.lots, 'trade_hedges', 'lots', r.booking_date, key={'hedge_id': r.hedge_id})} × "
                   f"{L.put(r.box_type, r.box_type, 'trade_book', 'box_type', r.booking_date, key=k, op='ident')} at "
                   f"USD{NB}{L.put(num(_f(r.freight_rate_usd_box)), _f(r.freight_rate_usd_box), 'trade_book', 'freight_rate_usd_box', r.booking_date, key=k)}/box, "
                   f"{L.put(pct(r.fixture_vs_index_frac, 1), r.fixture_vs_index_frac, 'trade_hedges', 'fixture_vs_index_frac', r.booking_date, key={'hedge_id': r.hedge_id})} "
                   "over the index at fixture; stop at "
                   f"USD{NB}{L.put(num(_f(r.freight_stop_loss_usd_box)), _f(r.freight_stop_loss_usd_box), 'trade_book', 'freight_stop_loss_usd_box', r.booking_date, key=k)}.")
    return out


def ops_lines(c: Context) -> list[str]:
    S, L, P, W = c.S, c.L, c.prev, c.week_end
    out = []
    bits = []
    lc = in_week(S["lc"], "lc_open_date", P, W)
    if len(lc):
        names = []
        for r in lc.itertuples():
            kind = ("sight" if r.payment_instrument == "LC_SIGHT" else
                    f"{L.put(num(r.usance_days), r.usance_days, 'trade_book', 'usance_days', r.lc_open_date, key={'trade_id': r.trade_id})}-day usance")
            names.append(f"{L.put(r.trade_id, r.trade_id, 'trade_book', 'trade_id', r.lc_open_date, key={'trade_id': r.trade_id}, op='ident')} "
                         f"({kind}{', confirmed' if r.lc_confirmed else ''})")
        bits.append(f"LC{'s' if len(names) > 1 else ''} opened for " + join_names(names))
    for name, col, verb in (("lots", "bl_date", "on board"), ("arrivals", "date", "arrived"), ("releases", "date", "cleared")):
        df = in_week(S[name], col, P, W)
        if len(df):
            names = [f"{L.put(r.trade_id, r.trade_id, 'trade_book', 'trade_id', getattr(r, col), key={'trade_id': r.trade_id}, op='ident')} "
                     f"{L.put(r.lot_id, r.lot_id, 'trade_book', 'lot_ids', getattr(r, col), key={'trade_id': r.trade_id}, op='ident')}"
                     for r in df.sort_values([col, "trade_id", "lot_id"]).itertuples()]
            bits.append(f"{verb}: {join_names(names)}")
    if bits:
        out.append("**Paper and boxes.** " + cap("; ".join(bits)) + ".")
    cash = in_week(S["cash"], "settle_date", P, W)
    liq = S["liq"]
    vm = in_week(liq, "date", P, W)
    cbits = []
    rec = cash[cash["cf_type"].str.startswith("SALE")]
    if len(rec):
        tot = float(rec["amount_inr"].sum())
        who = sorted({f"{r.trade_id}-{r.leg_id.split(':')[1]}" for r in rec.itertuples()})
        cbits.append(f"in {L.put(inr_m(tot), tot, 'trade_cashflows', 'sum(amount_inr | SALE_*, REALISED)', W, op='derived', date_from=P)} "
                     f"from buyers ({join_names([L.put(w, w, 'trade_cashflows', 'leg_id', W, op='ident') for w in who])})")
    pay = cash[cash["cf_type"].str.startswith("PURCHASE") & (cash["amount_ccy"] < 0)]
    if len(pay):
        tot = float(-pay["amount_ccy"].sum())
        who = sorted({r.trade_id for r in pay.itertuples()})
        cbits.append(f"out {L.put(usd_m(tot), tot, 'trade_cashflows', 'sum(-amount_ccy | PURCHASE_* < 0, REALISED)', W, op='derived', date_from=P)} "
                     f"to suppliers ({join_names([L.put(w, w, 'trade_cashflows', 'trade_id', W, op='ident') for w in who])})")
    if len(vm) and float(vm["net_margin_cash_inr"].abs().sum()) > 0:
        tot = float(vm["net_margin_cash_inr"].sum())
        cbits.append(f"MCX margin {L.put(inr_m(tot, 1, True), tot, 'margin_liquidity', 'net_margin_cash_inr', W, op='sum', date_from=P)} net")
    if cbits:
        out.append("**Cash.** " + cap("; ".join(cbits)) + ".")
    return out


def incident_lines(c: Context, start: str, end: str) -> list[str]:
    S, L = c.S, c.L
    inc = S["incidents"]
    inc = inc[(inc["known_date"] > start) & (inc["known_date"] <= end)]
    out = []
    logi = inc[inc["kind"] == "LOGISTICS"]
    for ref, g in logi.groupby("ref", sort=False):
        d = g["known_date"].iloc[0]
        ref_t = L.put(ref, ref, "config/trades.yaml", "real_trigger_ref", d, op="ident") if ref else ""
        items = []
        for r in g.itertuples():
            k = {"event_id": r.event_id}
            eff = []
            if r.arrival_delay_days:
                eff.append(f"+{L.put(num(r.arrival_delay_days), r.arrival_delay_days, 'config/trades.yaml', 'arrival_delay_days', d, key=k)}{NB}d arrival")
            if r.extra_dwell_days:
                eff.append(f"+{L.put(num(r.extra_dwell_days), r.extra_dwell_days, 'config/trades.yaml', 'extra_dwell_days', d, key=k)}{NB}d dwell")
            items.append(f"{L.put(r.trade_id, r.trade_id, 'config/trades.yaml', 'trade_id', d, key=k, op='ident')} "
                         f"{L.put(r.lot_id, r.lot_id, 'config/trades.yaml', 'lot_id', d, key=k, op='ident')} {' '.join(eff)}")
        out.append(f"**Ops.** {ref_t + '. ' if ref_t else ''}Expected delays for us (SIM; the simulation sets their "
                   f"full length on this date): {join_names(items)}.")
    for r in inc[inc["kind"] == "QUALITY"].itertuples():
        mo, co, reason, recov = (r.detail.split("|") + ["", "", "", ""])[:4]
        k = {"event_id": r.event_id}
        d = r.known_date
        rej = (f"{L.put(num(r.arrival_delay_days), r.arrival_delay_days, 'config/trades.yaml', 'rejected_boxes', d, key=k)} "
               f"box rejected ({reason.lower()})" if r.arrival_delay_days else "no rejections")
        out.append(f"**Survey (SIM).** {L.put(r.trade_id, r.trade_id, 'config/trades.yaml', 'trade_id', d, key=k, op='ident')} "
                   f"{L.put(r.lot_id, r.lot_id, 'config/trades.yaml', 'lot_id', d, key=k, op='ident')}: moisture "
                   f"{L.put(pct(float(mo), 1), float(mo), 'config/trades.yaml', 'moisture_actual_frac', d, key=k)}, "
                   + (f"contamination {L.put(pct(float(co), 1), float(co), 'config/trades.yaml', 'contamination_actual_frac', d, key=k)}, " if co else "")
                   + f"{rej}; claim on the seller, and I book only "
                   f"{L.put(pct(float(recov), 0), float(recov), 'config/trades.yaml', 'claim_recovery_frac', d, key=k)} recovery.")
    for r in inc[inc["kind"] == "PAY_DELAY"].itertuples():
        k = {"event_id": r.event_id}
        out.append(f"**Credit (SIM).** {L.put(r.trade_id, r.trade_id, 'config/trades.yaml', 'trade_id', r.known_date, key=k, op='ident')} "
                   f"buyer asks for {L.put(num(r.arrival_delay_days), r.arrival_delay_days, 'config/trades.yaml', 'delay_days', r.known_date, key=k)} more days.")
    return out


def incident_label(r) -> str:
    if r.kind == "LOGISTICS":
        return "void-call delays" if "void" in r.ref else "a port hold"
    if r.kind == "QUALITY":
        reason = (r.detail.split("|") + ["", "", ""])[2]
        return f"a {reason.lower()} rejection" if r.arrival_delay_days and reason else "a cargo survey"
    return "a payment delay"


def section_did(c: Context) -> str:
    S, L, P, W = c.S, c.L, c.prev, c.week_end
    bullets = []
    buys = in_week(S["tickets"], "trade_date", P, W).sort_values(["trade_date", "trade_id"])
    sells = in_week(S["sales"], "contract_date", P, W).sort_values(["contract_date", "trade_id", "sale_id"])
    c.flags["buys"] = list(buys["trade_id"])
    c.flags["sells"] = [f"{r.trade_id}-{r.sale_id}" for r in sells.itertuples()]
    bullets += [purchase_line(c, t) for _, t in buys.iterrows()]
    bullets += [sale_line(c, s) for _, s in sells.iterrows()]
    bullets += incident_lines(c, P, W)
    bullets += hedge_lines(c)
    bullets += ops_lines(c)
    if not bullets:
        bullets.append("Quiet week on the book: no new tickets, no hedge changes, nothing landed.")
    # Earlier in the month (before this week): one compact line
    ms = c.month_start
    eb = S["tickets"][(S["tickets"]["trade_date"] >= ms) & (S["tickets"]["trade_date"] <= P)]
    es = S["sales"][(S["sales"]["contract_date"] >= ms) & (S["sales"]["contract_date"] <= P)]
    ei = S["incidents"][(S["incidents"]["known_date"] >= ms) & (S["incidents"]["known_date"] <= P)]
    if len(eb) or len(es) or len(ei):
        bits = []
        if len(eb):
            bits.append("bought " + join_names([L.put(x, x, "trade_book", "trade_id", d, op="ident")
                                                for x, d in zip(eb["trade_id"], eb["trade_date"])]))
        if len(es):
            bk = S["bookings"].set_index(["trade_id", "sale_id"])["band_policy_verdict"]
            bits.append("sold " + join_names([
                L.put(f"{a}-{b}", f"{a}-{b}", "trade_book", "sale_ids", d, op="ident")
                + (" (outside the band policy⁵)" if bk.get((a, b)) == "OUTSIDE_BAND_POLICY" else "")
                for a, b, d in zip(es["trade_id"], es["sale_id"], es["contract_date"])]))
        ei = ei.assign(label=[incident_label(r) for r in ei.itertuples()])
        for label, g in ei.groupby("label", sort=False):
            bits.append(f"{label} on " + join_names(sorted({L.put(x, x, 'config/trades.yaml', 'trade_id', d, op='ident')
                                                            for x, d in zip(g['trade_id'], g['known_date'])})))
        bullets.append(f"*Earlier in {month_name(W)}:* " + "; ".join(bits) + ".")
    return "\n".join(f"- {b.strip()}" for b in bullets)


# ---- P&L
def section_pnl(c: Context) -> str:
    S, L, P, W = c.S, c.L, c.prev, c.week_end
    att = S["att"]
    tr = att[att["trade_id"] != "BOOK"]          # BOOK rows would double count (fix log §3.8)
    book = att[att["trade_id"] == "BOOK"]
    cum = float(_one(book[book["date"] == W], f"BOOK {W}")["cum_pnl_inr"])
    life = float(tr["daily_pnl_inr"].sum())
    if abs(life - cum) > 1.0:
        raise ValueError(f"trade rows do not tie to the BOOK cumulative P&L at {W}: {life} vs {cum}")
    start = WINDOW_START.isoformat()
    periods = [("Week", P, W), (f"{month_name(W)} to date", (pd.Timestamp(c.month_start) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"), W),
               (f"Since {day(start)}", (pd.Timestamp(start) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"), W)]
    header = "| ₹ m | " + " | ".join(BUCKET_SHORT[b] for b in PNL_COLS) + " | **Total** |"
    rows = [header, "|---|" + "--:|" * (len(PNL_COLS) + 1)]
    week_vals = {}
    for label, d0, d1 in periods:
        sub = tr[(tr["date"] > d0) & (tr["date"] <= d1)]
        cells = []
        for b in PNL_COLS:
            v = float(sub[b].sum())
            if label == "Week":
                week_vals[b] = v
            cells.append(L.put(signed(v / M, 1), v, "attribution_daily", b, d1, key={"trade_id": "!BOOK"}, op="sum",
                               date_from=d0))
        tot = float(sub["daily_pnl_inr"].sum())
        tl = L.put(signed(tot / M, 1), tot, "attribution_daily", "daily_pnl_inr", d1, key={"trade_id": "!BOOK"}, op="sum",
                   date_from=d0)
        if label.startswith("Since"):
            label = f"Since {L.put(day(start), start, 'desk.WINDOW_START', 'date', 'static', op='ident')}"
        rows.append(f"| {label} | " + " | ".join(cells) + f" | **{tl}** |")
    table = "<!-- widths: 0.13, 0.085, 0.085, 0.085, 0.085, 0.095, 0.085, 0.085, 0.11, 0.09 -->\n" + "\n".join(rows)

    # the week's driver
    b = max(PNL_COLS, key=lambda k: (abs(week_vals[k]), k))
    v = week_vals[b]
    vt = L.put(inr_m(abs(v)), abs(v), "attribution_daily", b, W, key={"trade_id": "!BOOK", "abs": True}, op="sum",
               date_from=P)
    if abs(v) < 0.05 * M:
        driver = "A flat week for P&L."
    else:
        driver = {
            ("new_deal", True): f"The week was the contract dates: {vt} of deal margin booked at signature.",
            ("new_deal", False): f"Contract-date costs took {vt} (hedge execution, LC fees, deal terms under the market).",
            ("lme_flat", True): f"LME made {vt} net of hedges — that is the net position, not the hedged book.",
            ("lme_flat", False): f"LME cost {vt} net of hedges — the unhedged residual, not the hedged book.",
            ("grade_spread", True): f"Grade-spread marks added {vt}: a reconstructed series⁴, so I do not lean on it.",
            ("grade_spread", False): f"Grade-spread marks took {vt}: a reconstructed series⁴, and the scrap discount "
                                     "went against the unsold cargo.",
            ("fx", True): f"The rupee made {vt} on the physical-plus-forwards leg net of the MCX leg².",
            ("fx", False): f"The rupee cost {vt} on the physical-plus-forwards leg net of the MCX leg².",
            ("roll_term_structure", True): f"Carry, rolls and cross-terms added {vt}.",
            ("roll_term_structure", False): f"Carry and cross-terms took {vt}: funding on the cash we are out, plus the "
                                            "LME × FX cross-term on USD cargo.",
            ("demurrage_penalty", True): f"Events added {vt} (survey restatements).",
            ("demurrage_penalty", False): f"Events cost {vt}: demurrage and claims.",
            ("freight", True): f"Freight fixed below the market added {vt}.",
            ("freight", False): f"Freight fixed above a falling market cost {vt}.",
            ("cross_exchange_basis", True): f"Basis added {vt}.",
            ("cross_exchange_basis", False): f"Basis cost {vt}.",
        }[(b, v > 0)]

    # the point-in-time premium band on the sales booked so far
    share = float(_one(S["robust"][S["robust"]["family"] == "desk_share"], "desk share")["base_value"])
    base_prem = float(config.value("domestic_anchor_premium_inr_t"))
    grid = [float(x) for x in config.value("domestic_anchor_premium_sensitivity_inr_t")]
    slope = float(sale_slope_inr_per_premium(S["sales"], S["recovery"], share).sum())
    cum_t = L.put(inr_m(cum), cum, "attribution_daily", "cum_pnl_inr", W, key={"trade_id": "BOOK"})
    cash_bal = float(_one(S["exp"][S["exp"]["date"] == W], "exposure")["cash_balance_inr"])
    va = S["var_ante"]
    stale = va[(va["date"] > P) & (va["date"] <= W) & va["position_date_mcx_exit_or_roll"].astype(bool)]
    if len(stale):
        k = len(stale)
        driver += (f" {cap(count_word(k))} {'day' if k == 1 else 'days'} this week followed an MCX exit or roll, where the engine keeps the "
                   "closed contract in the delta: part of the move lands in (a) and is reversed in (g), so read the "
                   "two together.")
    text = (f"{driver} Book P&L since inception {cum_t} on marks, with the cash account at "
            f"{L.put(inr_m(cash_bal), cash_bal, 'book_exposures_daily', 'cash_balance_inr', W, key={'scope': 'book'})}. ")
    if slope <= 0:
        text += "No sale booked yet, so none of it rests on the domestic premium⁷."
    else:
        lo, hi = cum + slope * (min(grid) - base_prem), cum + slope * (max(grid) - base_prem)
        spec = "sales(contract<=W): quantity_mt x desk_share x recovery_frac x (grid - base)"
        text += (f"The sales booked so far hang it on our unverified domestic premium⁷: "
                 f"{L.put(inr_m(lo), lo, 'attribution_daily+trade_book+parity_weekly', spec, W, op='derived')} to "
                 f"{L.put(inr_m(hi), hi, 'attribution_daily+trade_book+parity_weekly', spec, W, op='derived')} across the "
                 f"registered range ({L.put(num(min(grid)), min(grid), 'config', 'domestic_anchor_premium_sensitivity_inr_t', 'static', op='config')} "
                 f"to {L.put(signed(max(grid)), max(grid), 'config', 'domestic_anchor_premium_sensitivity_inr_t', 'static', op='config')} ₹/MT"
                 f" against {L.put(num(base_prem), base_prem, 'config', 'domestic_anchor_premium_inr_t', 'static', op='config')} base)")
        be = base_prem - cum / slope
        if min(grid) <= be <= max(grid):
            text += (f"; break-even at {L.put(num(be), be, 'attribution_daily+trade_book+parity_weekly', 'base - cum/slope', W, op='derived')} "
                     "₹/MT sits inside it, so the sign of this P&L is not robust.")
        else:
            text += "; positive across all of it."
    return table + "\n\n" + text


# ---- risks next week
def section_risks(c: Context) -> str:
    S, L, P, W = c.S, c.L, c.prev, c.week_end
    bullets = []
    e = _one(S["exp"][S["exp"]["date"] == W], f"book exposures {W}")
    ek = {"scope": "book"}
    va = S["var_ante"]
    v = _one(va[va["position_date"] == W], f"VaR forecast made at the {W} close")
    net, phys, mcx = float(e["lme_delta_mt"]), float(e["lme_delta_physical_mt"]), float(e["lme_delta_mcx_mt"])
    lots = float(e["mcx_lots_open"])
    lots_t = (f"on {L.put(num(abs(lots)), lots, 'book_exposures_daily', 'mcx_lots_open', W, key=ek)} lots "
              f"{'short' if lots < 0 else 'long'}" if lots else "with no MCX lots open")
    t = (f"**Position.** Net LME {L.put(signed(net), net, 'book_exposures_daily', 'lme_delta_mt', W, key=ek)}{NB}MT: physical "
         f"{L.put(signed(phys), phys, 'book_exposures_daily', 'lme_delta_physical_mt', W, key=ek)}, MCX "
         f"{L.put(signed(mcx), mcx, 'book_exposures_daily', 'lme_delta_mcx_mt', W, key=ek)} {lots_t}")
    hr = e["hedge_ratio_lme_frac"]
    if pd.notna(hr):
        t += f" (hedge ratio {L.put(num(float(hr), 2), float(hr), 'book_exposures_daily', 'hedge_ratio_lme_frac', W, key=ek)})"
    unsold = float(e["unsold_mt"])
    c.flags["fully_sold"] = unsold == 0 and float(e["phys_sold_mt"]) > 0
    t += f"; unsold {L.put(num(unsold), unsold, 'book_exposures_daily', 'unsold_mt', W, key=ek)}{NB}MT. "
    artefact = bool(v["position_date_mcx_exit_or_roll"])
    if artefact:
        t += ("Today's MCX exits still sit in these deltas, the MCX FX leg and the VaR below (a known engine artefact "
              "on exit and roll days); the clean read is the physical and the lots actually open. ")
    elif abs(phys) > 0 and abs(net) > NET_OPEN_FRAC * abs(phys):
        c.flags["open_position"] = f"{L.put(num(abs(net)), abs(net), 'book_exposures_daily', '|lme_delta_mt|', W, key=ek, op='derived')}{NB}MT of {'long' if net > 0 else 'short'}"
        t += (f"That is a {'long' if net > 0 else 'short'} position, not rounding: "
              f"{'the hedge lags the physical' if net > 0 else 'the hedge is ahead of the physical'}. ")
    elif abs(phys) > 0:
        share = abs(net) / abs(phys)
        t += (f"Hedged to within {L.put(pct(share, 0), share, 'book_exposures_daily', '|lme_delta_mt|/|lme_delta_physical_mt|', W, op='derived')} "
              "of the physical. ")
    pf = float(e["fx_delta_physical_usd"]) + float(e["fx_delta_forwards_usd"])
    fm = float(e["fx_delta_mcx_usd"])
    t += (f"FX: physical plus forwards {'long' if pf >= 0 else 'short'} "
          f"{L.put(usd_m(abs(pf)), abs(pf), 'book_exposures_daily', 'fx_delta_physical_usd+fx_delta_forwards_usd', W, key=ek, op='derived')}, "
          f"MCX² leg {'long' if fm >= 0 else 'short'} {L.put(usd_m(abs(fm)), fm, 'book_exposures_daily', 'fx_delta_mcx_usd', W, key=ek)} "
          "— I read them separately, because the netted number hides the offset.")
    bullets.append(t)

    vg, vh, v60 = float(v["var_garch_inr"]), float(v["var_hist250_inr"]), float(v["var_hist60_inr"])
    vk = {"position_date": W}
    t = (f"**VaR (1-day 95 %), into the next session.** GARCH "
         f"{L.put(inr_m(vg, 2), vg, 'var_daily', 'var_garch_inr', W, key=vk)} (σ "
         f"{L.put(pct(float(v['sigma_lme_garch_frac']), 2), float(v['sigma_lme_garch_frac']), 'var_daily', 'sigma_lme_garch_frac', W, key=vk)}), "
         f"250-day {L.put(inr_m(vh, 2), vh, 'var_daily', 'var_hist250_inr', W, key=vk)} (σ "
         f"{L.put(pct(float(v['sigma_lme_hist250_frac']), 2), float(v['sigma_lme_hist250_frac']), 'var_daily', 'sigma_lme_hist250_frac', W, key=vk)}), "
         f"60-day {L.put(inr_m(v60, 2), v60, 'var_daily', 'var_hist60_inr', W, key=vk)}. ")
    if vg > (1 + VAR_GAP_FRAC) * vh:
        t += "GARCH is the higher read: the latest shocks still dominate its memory. "
    elif vh > (1 + VAR_GAP_FRAC) * vg:
        t += "GARCH has decayed below the 250-day window, which still carries March; I size off the higher number. "
    else:
        t += "The two agree. "
    if v60 > (1 + VAR_GAP_FRAC) * max(vg, vh):
        t += "The 60-day window is the hot read: it holds the recent sell-off at full weight. "
    vp = S["var_post"]
    vp = vp[vp["position_held"].astype(bool)]
    ng, nh, nd = int(vp["exception_garch"].sum()), int(vp["exception_hist250"].sum()), len(vp)
    if nd:
        t += (f"Exceptions so far: GARCH {L.put(num(ng), ng, 'var_daily', 'exception_garch', W, key={'position_held': True}, op='sum', date_from='')}, "
              f"250-day {L.put(num(nh), nh, 'var_daily', 'exception_hist250', W, key={'position_held': True}, op='sum', date_from='')} "
              f"in {L.put(num(nd), nd, 'var_daily', 'count(position_held)', W, op='derived')} days.")
    bullets.append(t)

    cr = S["credit"]
    cr = cr[cr["date"] == W].sort_values(["utilisation_frac", "cp_id"], ascending=[False, True])
    items, extra, soft = [], [], []
    for r in cr.itertuples():
        k = {"cp_id": r.cp_id}
        cp = L.put(r.cp_id, r.cp_id, "credit_tracker", "cp_id", W, key=k, op="ident")
        items.append(f"{cp} {L.put(pct(r.utilisation_frac, 0), r.utilisation_frac, 'credit_tracker', 'utilisation_frac', W, key=k)} "
                     f"of {L.put(inr_m(r.credit_limit_inr, 0), r.credit_limit_inr, 'credit_tracker', 'credit_limit_inr', W, key=k)} "
                     f"(band {L.put(r.band_final, r.band_final, 'credit_tracker', 'band_final', W, key=k, op='ident')})")
        if r.advance_reliance_multiple > 1.0:
            c.flags["advance_over_line"] = True
            extra.append(f"{cp} also carries advances of "
                         f"{L.put(num(r.advance_reliance_multiple, 2), r.advance_reliance_multiple, 'credit_tracker', 'advance_reliance_multiple', W, key=k)}× "
                         "its line: if one fails I hold unsold cargo with the hedge already lifted, so no hedge comes "
                         "off before the money lands.")
        if bool(r.flag_soft_utilisation):
            soft.append(cp)
        elif r.overlay_notches > 0 and r.advance_reliance_multiple <= 1.0:
            cap_d = int(config.value("credit_band_max_credit_days")[r.band_final])   # static rule, no date
            rule = "would allow it no open credit" if cap_d == 0 else "would cap the credit days it gets"
            t_extra = f"{cp} is band {r.band_final} on its advance reliance in the last quarter; the band policy⁵ {rule}"
            if r.credit_exposure_inr > 0:
                t_extra += (f", yet {L.put(inr_m(r.credit_exposure_inr), r.credit_exposure_inr, 'credit_tracker', 'credit_exposure_inr', W, key=k)} "
                            "is open from sales already booked.")
            else:
                t_extra += "."
            extra.append(t_extra)
        if r.days_past_due > 0:
            extra.append(f"{cp} is {L.put(num(r.days_past_due), r.days_past_due, 'credit_tracker', 'days_past_due', W, key=k)} days past due.")
    if soft:
        c.flags["soft_credit"] = ("two buyers are" if len(soft) == 2 else "three buyers are" if len(soft) == 3
                                  else f"{soft[0]} is")
        lim = float(config.value("credit_soft_utilisation_frac"))
        extra.insert(0, f"{join_names(soft)} {'are' if len(soft) > 1 else 'is'} over the "
                        f"{L.put(pct(lim, 0), lim, 'config', 'credit_soft_utilisation_frac', 'static', op='config')} "
                        f"early-warning line: no new open credit to {'them' if len(soft) > 1 else 'it'} until cash comes in.")
    bullets.append(("**Credit⁵.** Line use on today's exposure: " + "; ".join(items) + ". " + " ".join(extra)).strip())

    lq = _one(S["liq"][S["liq"]["date"] == W], f"liquidity {W}")
    need, lim, buf, head = (float(lq[x]) for x in ("funding_need_total_inr", "fb_limit_inr", "min_cash_buffer_inr",
                                                   "headroom_inr"))
    c.flags["fb_breach"], c.flags["buffer_breach"] = bool(lq["flag_fb_limit_breach"]), bool(lq["flag_buffer_breach"])
    c.flags["lc_breach"], c.flags["mar_over_buffer"] = bool(lq["flag_lc_limit_breach"]), bool(lq["flag_mar_exceeds_buffer"])
    move = math.exp(float(lq["stress_move_up_logret"])) - 1
    mar = float(lq["mar_99_inr"])
    t = (f"**Cash⁶.** Funding need {L.put(inr_m(need), need, 'margin_liquidity', 'funding_need_total_inr', W)} on the "
         f"{L.put(inr_m(lim, 0), lim, 'margin_liquidity', 'fb_limit_inr', W)} working-capital line; headroom after the "
         f"{L.put(inr_m(buf, 0), buf, 'margin_liquidity', 'min_cash_buffer_inr', W)} buffer "
         f"{L.put(inr_m(head), head, 'margin_liquidity', 'headroom_inr', W)}. ")
    if c.flags["fb_breach"]:
        t += "Over the line: I need an ad-hoc limit or I stop buying. "
    elif c.flags["buffer_breach"]:
        t += "Inside the buffer: nothing new that draws cash until receipts land. "
    t += f"Initial margin {L.put(inr_m(float(lq['mcx_im_inr'])), float(lq['mcx_im_inr']), 'margin_liquidity', 'mcx_im_inr', W)}. "
    if mar > 0:
        t += (f"A 99 % 10-day LME move against the hedges "
              f"({L.put(pct(move, 1, True), move, 'margin_liquidity', 'exp(stress_move_up_logret)-1', W, op='derived')}, "
              f"{BINDING_NAMES.get(str(lq['stress_binding_up']), str(lq['stress_binding_up']))} vol) calls "
              f"{L.put(inr_m(mar), mar, 'margin_liquidity', 'mar_99_inr', W)}"
              + (" — more than the buffer." if bool(lq["flag_mar_exceeds_buffer"]) else ", inside the buffer.") + " ")
    lc, lcl = float(lq["lc_outstanding_inr"]), float(lq["lc_limit_inr"])
    t += (f"LC line {L.put(inr_m(lc), lc, 'margin_liquidity', 'lc_outstanding_inr', W)} of "
          f"{L.put(inr_m(lcl, 0), lcl, 'margin_liquidity', 'lc_limit_inr', W)}"
          + (": over limit, so no new LC until usance runs off." if bool(lq["flag_lc_limit_breach"]) else "."))
    bullets.append(t)

    pw = S["parity"]
    board = pw[pw["week_end"] == week_friday(W)]
    if len(board):
        ok = board[board["trade_eligible"].astype(bool)].sort_values(["net_arb_inr_t", "grade", "lane"],
                                                                      ascending=[False, True, True])
        c.flags["eligible"], c.flags["cases"] = len(ok), len(board)
        bk = {"week_end": week_friday(W)}
        t = (f"**Parity for next week's decisions⁴.** "
             f"{L.put(num(len(ok)), len(ok), 'parity_weekly', 'trade_eligible', W, key=bk, op='sum')} of "
             f"{L.put(num(len(board)), len(board), 'parity_weekly', 'count(cases)', W, key=bk, op='derived')} grade × lane "
             "cases clear all three screens")
        if len(ok):
            best = ok.iloc[0]
            k = {"week_end": week_friday(W), "grade": best["grade"], "lane": best["lane"]}
            base, pit = float(best["net_arb_inr_t"]), float(best["net_arb_pit_mix_inr_t"])
            t += (f"; best is {GRADE_NAMES[best['grade']]} on {LANE_NAMES[best['lane']]} at "
                  f"₹{L.put(num(base), base, 'parity_weekly', 'net_arb_inr_t', W, key=k)}/MT base, "
                  f"₹{L.put(num(pit), pit, 'parity_weekly', 'net_arb_pit_mix_inr_t', W, key=k)} point-in-time. ")
            if len(ok) == len(board):
                t += "Wide open: cash and credit set the size, not the board."
            elif pit < PIT_HAIRCUT_FRAC * base:
                t += "The point-in-time number is under half the base: size to it."
            else:
                t += "Selective: only these cases, and small."
        else:
            t += ". Window shut: no new purchases next week."
        bullets.append(t)

    diary = diary_items(c)
    if diary:
        bullets.append("**Diary (contract dates next week).** " + cap("; ".join(diary)) + ".")
    return "\n".join(f"- {b.strip()}" for b in bullets)


def diary_items(c: Context) -> list[str]:
    """Contractual dates in the coming week, from terms known at the close (never from what later happened)."""
    S, L, W = c.S, c.L, c.week_end
    horizon = (pd.Timestamp(W) + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    out = []
    lines, exits = S["lines"], S["exits"]
    open_lines = lines[~lines["hedge_id"].isin(set(exits["hedge_id"]))]
    due = open_lines[(open_lines["roll_deadline"] > W) & (open_lines["roll_deadline"] <= horizon)]
    if len(due):
        ids = sorted(set(due["trade_id"]))
        months = sorted(set(due["contract_month"]))
        out.append(f"{join_names([L.put(x, x, 'trade_hedges', 'trade_id', W, op='ident') for x in ids])} "
                   f"{'/'.join(contract_month(m) for m in months)} MCX lines reach their roll deadline")
    tk = S["tickets"]
    qp = tk[(tk["pricing"] == "LME_M1_AVG") & (tk["qp_start"] <= horizon) & (tk["qp_end"] > W)]
    if len(qp):
        out.append(f"{join_names([L.put(x, x, 'trade_book', 'trade_id', W, op='ident') for x in qp['trade_id']])} "
                   "purchase pricing on the LME cash average")
    sa = S["sales"]
    sw = sa[(sa["pricing"] == "MCX_AVG") & (sa["window_start"] <= horizon) & (sa["window_end"] > W)]
    if len(sw):
        out.append(f"{join_names([L.put(f'{a}-{b}', f'{a}-{b}', 'trade_book', 'sale_ids', W, op='ident') for a, b in zip(sw['trade_id'], sw['sale_id'])])} "
                   "sale pricing on the MCX average")
    mt = S["maturities"]
    mt = mt[(mt["maturity_date"] > W) & (mt["maturity_date"] <= horizon)]
    if len(mt):
        out.append("usance LC maturity on " + join_names(
            [f"{L.put(r.trade_id, r.trade_id, 'trade_book', 'trade_id', r.bl_date, op='ident')} "
             f"{L.put(r.lot_id, r.lot_id, 'trade_book', 'lot_ids', r.bl_date, op='ident')}" for r in mt.itertuples()]))
    return out


# ---- footnotes
def section_footnotes(c: Context) -> str:
    L, W = c.L, c.week_end
    plan = str(config.value("liq_plan_parity_week_end"))
    return "\n".join([
        "¹ **Freight:** lane levels are a reconstruction whose level inputs were published after this note (Drewry WCI "
        "shape = PROXY, lane level = ASSUMPTION), and the Gulf lane is a fixed multiple of the US lane, so freight is one "
        "factor, not two.",
        "² **MCX:** a duty-paid import-parity proxy built from LME × USD/INR, not MCX bhavcopy. It has unit beta to LME "
        "by construction, so basis (b) reads zero and hedge effectiveness is overstated, and its curve is always in "
        "contango (INR carry), so roll gains are an artefact.",
        "³ **Headlines:** real Google News RSS titles (DIRECT text, PROXY selection), scored with VADER; a supporting "
        "signal, never a reason for a trade.",
        "⁴ **Grade factors:** the parity board, the unsold-cargo marks and bucket (c) use a reconstructed grade-factor "
        "mix; the point-in-time mix is shown where it matters.",
        "⁵ **Credit:** bands come from an illustrative logistic model fitted to synthetic data, applied to this book's "
        "own utilisation and payment history as of this close; the band policy is a retrospective test the desk did not "
        "run at the time.",
        f"⁶ **Facilities:** the working-capital line, LC line and buffer are ASSUMPTIONS sized on the "
        f"{L.put(day(plan, True), plan, 'config', 'liq_plan_parity_week_end', 'static', op='config')} plan, not on this book.",
        "⁷ **Premium:** the domestic anchor premium behind every sale price, and its registered range, come from price "
        "prints published after this note; they are simulation assumptions, not evidence a desk had at the time.",
        "⁸ **Rates:** the INR 3M rate behind the forward premium, forward rates and the MCX² proxy's carry is the OECD "
        "average for the whole calendar month (PROXY), published after it ends: up to one month of look-ahead.",
    ])


# ------------------------------------------------------------------------------------------------ chart
def chart_tape(n: int, week_end: str, data: Mapping[str, pd.DataFrame]) -> Path:
    """LME cash (one quarter to the week end, our trade and sale dates marked) over book P&L since the first trade."""
    mk = data["mkt"]
    mk = mk[mk["date"] <= week_end].tail(TAPE_LOOKBACK_BDAYS)
    att = data["att"]
    bk = att[(att["trade_id"] == "BOOK") & (att["date"] <= week_end)]
    x = pd.to_datetime(mk["date"])
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(2.9, 2.75), sharex=True, gridspec_kw={"height_ratios": [1.25, 1]})
    a1.plot(x, mk["lme_cash_usd_t"], color=PALETTE["lme"], lw=1.1)
    first = mk["date"].iloc[0]
    for df, col, mkr, colr, lab in ((data["tickets"], "trade_date", "^", PALETTE["gain"], "purchase"),
                                    (data["sales"], "contract_date", "v", PALETTE["mcx"], "sale")):
        d = df[(df[col] >= first) & (df[col] <= week_end)][col].unique()
        if len(d):
            px = mk.set_index("date").loc[list(d), "lme_cash_usd_t"]
            a1.scatter(pd.to_datetime(px.index), px.values, marker=mkr, s=16, color=colr, zorder=3, label=lab)
    a1.set_title(f"LME cash, USD/t, to {day(week_end)} (DIRECT)", fontsize=7, loc="left")
    a1.legend(fontsize=5.8, loc="best", handletextpad=0.2, borderaxespad=0.2, markerscale=0.9)
    b = bk[bk["date"] >= first]
    a2.fill_between(pd.to_datetime(b["date"]), b["cum_pnl_inr"] / M, 0, color=PALETTE["band"], step="post")
    a2.plot(pd.to_datetime(b["date"]), b["cum_pnl_inr"] / M, color=PALETTE["pnl"], lw=1.0, drawstyle="steps-post")
    a2.set_title("Book P&L since inception, ₹ m (on marks)", fontsize=7, loc="left")
    for a in (a1, a2):
        a.tick_params(labelsize=5.8, length=2, pad=1.5)
        a.grid(alpha=0.25)
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%#d-%b"))
    a2.xaxis.set_major_locator(mdates.MonthLocator())
    fig.tight_layout(pad=0.3, h_pad=0.5, rect=(0, 0.045, 1, 1))
    name = chart_name(n)
    save_fig(fig, name)
    return CHARTS_DIR / f"{name}.png"


# ------------------------------------------------------------------------------------------------ PDF
def _style(scale: float) -> PdfStyle:
    s = NOTE_STYLE
    return PdfStyle(font_size=s.font_size * scale, table_font_size=s.table_font_size * scale,
                    title_size=s.title_size * scale, h2_size=s.h2_size * scale, h3_size=s.h3_size * scale,
                    margin_left_mm=s.margin_left_mm, margin_right_mm=s.margin_right_mm, margin_top_mm=s.margin_top_mm,
                    margin_bottom_mm=s.margin_bottom_mm, leading_ratio=s.leading_ratio,
                    paragraph_space_after=s.paragraph_space_after * scale,
                    heading_space_before=s.heading_space_before * scale, footer_font_size=s.footer_font_size)


def _flow(md: str, chart: Path | None, style: PdfStyle) -> list:
    """Markdown -> flowables, with the tape chart set beside the 'What I saw' bullets and smaller footnotes."""
    body, foot = md.split(FOOTNOTES) if FOOTNOTES in md else (md, "")
    pre, post = body.split(CHART_SLOT) if CHART_SLOT in body else (body, "")
    flow = markdown_to_flowables(pre, style)
    if post:
        saw, rest = post.split("## What I did", 1)
        avail = style.pagesize[0] - (style.margin_left_mm + style.margin_right_mm) * mm
        saw_flow = markdown_to_flowables(saw, style)
        if chart is not None and chart.exists():
            from reportlab.lib.utils import ImageReader

            iw, ih = ImageReader(str(chart)).getSize()
            cw = avail * CHART_W_FRAC
            img = Image(str(chart), width=cw - 2 * mm, height=(cw - 2 * mm) * ih / iw)
            t = Table([[saw_flow, img]], colWidths=[avail - cw, cw])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (0, 0), 3), ("RIGHTPADDING", (1, 0), (1, 0), 0),
                                   ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
            flow.append(t)
        else:
            flow.extend(saw_flow)
        flow.extend(markdown_to_flowables("## What I did" + rest, style))
    if foot.strip():
        fs = replace(style, font_size=style.font_size * FOOT_SCALE, paragraph_space_after=0.6)
        flow.extend(markdown_to_flowables(foot, fs))
    return flow


def render_pdf(md: str, out_path: Path, chart: Path | None, title: str) -> tuple[int, float]:
    """Render at the base size; if the note spills, shrink in small steps (deterministic) down to MIN_FONT.

    Returns (pages, body font size used).
    """
    register_fonts()
    scale = 1.0
    while True:
        style = _style(scale)
        doc = DeskDocTemplate(str(out_path), style, title=title, author="Aluminium scrap desk (SIM)",
                              subject=SIM_LABEL, creator="desk.reporting.desk_notes")
        sink: list[int] = []
        doc.build(_flow(md, chart, style), canvasmaker=_numbered_canvas_class(SIM_LABEL, style, sink))
        pages = sink[-1] if sink else 0
        if pages <= MAX_PAGES or style.font_size * 0.97 < MIN_FONT:
            return pages, style.font_size
        scale *= 0.97


# ------------------------------------------------------------------------------------------------ stage
def note_paths(n: int, week_end: str) -> tuple[Path, Path]:
    stem = f"{NAME}_{n}_{week_end}"
    return REPORTS_DIR / f"{stem}.md", REPORTS_DIR / f"{stem}.pdf"


def build_all(src: Mapping[str, pd.DataFrame] | None = None) -> list[tuple[int, str, str, Ledger, dict]]:
    src = src if src is not None else load_sources()
    panel = src["mkt"]["date"].tolist()
    return [(n, w, *build_note(src, n, w, panel)) for n, w in enumerate(select_week_ends(panel), start=1)]


def chart_name(n: int) -> str:
    return f"{CHART_PREFIX}_{n}_tape"


def publishable_md(md: str, n: int, week_end: str) -> str:
    """The GitHub copy: the chart slot becomes an image link and the footnote marker a rule."""
    md = md.replace(CHART_SLOT, f"![LME cash and book P&L to {day(week_end)}](../charts/{chart_name(n)}.png)")
    return md.replace(FOOTNOTES + "\n\n", "---\n\n")


def main() -> None:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for n, w, md, _ledger, chart_data in build_all():
        chart = chart_tape(n, w, chart_data)
        md_path, pdf_path = note_paths(n, w)
        md_path.write_text(publishable_md(md, n, w), encoding="utf-8")
        pages, _font = render_pdf(md, pdf_path, chart, title=f"Desk note {n} — week ending {w} (SIM)")
        if pages != MAX_PAGES or count_pdf_pages(pdf_path) != MAX_PAGES:
            raise ValueError(f"desk note {n} must be exactly {MAX_PAGES} A4 page; rendered {pages}")


if __name__ == "__main__":
    main()
