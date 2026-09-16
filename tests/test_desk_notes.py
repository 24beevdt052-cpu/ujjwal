"""Tests for the P6 weekly desk notes (desk.reporting.desk_notes, MASTER_SPEC Table 7 row 5.1).

What these protect:
* the declared week-end rule (last Friday of each window month) and one A4 page per note, SIM-labelled;
* no hindsight — (1) every CSV row and config event dated after the week end is poisoned on disk and the note must
  come out byte-identical, (2) no date later than the week end appears in the text, (3) no ticket, sale or headline
  from after the week end is named;
* traceability — every digit in a note belongs to a recorded fact, and every recorded level, sum and change is
  recomputed here straight from the CSVs (not through the module) and must match;
* the P&L table excludes the BOOK rows and ties to the BOOK cumulative P&L, and the point-in-time premium band is
  the published horizon sensitivity restricted to the sales booked by that Friday;
* the published files are the current build (no stale notes).
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
import shutil

import pandas as pd
import pytest
import yaml

from desk import SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.paths import CHARTS_DIR, CONFIG_DIR, PROCESSED_DIR, TABLES_DIR
from desk.reporting import desk_notes as dn
from desk.reporting.pdf import count_pdf_pages

MINUS = "−"
NB = " "
MONTHS = {m: i for i, m in enumerate(calendar.month_abbr) if m}


# ------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def src():
    return dn.load_sources()


@pytest.fixture(scope="module")
def notes(src):
    return dn.build_all(src)


@pytest.fixture(scope="module")
def published(notes):
    paths = [dn.note_paths(n, w) for n, w, *_ in notes]
    if not all(md.exists() and pdf.exists() for md, pdf in paths) or not all(
            (CHARTS_DIR / f"{dn.chart_name(n)}.png").exists() for n, *_ in notes):
        dn.main()
    return {n: (md.read_text(encoding="utf-8"), pdf) for (n, *_), (md, pdf) in zip(notes, paths)}


def _panel_dates() -> list[str]:
    return pd.read_csv(PROCESSED_DIR / "market_daily.csv", usecols=["date"])["date"].tolist()


# ------------------------------------------------------------------------------------------------ rule and pages
def test_week_ends_are_last_friday_of_each_window_month():
    days = set(_panel_dates())
    got = dn.select_week_ends(sorted(days))
    want = []
    for m in range(WINDOW_START.month, WINDOW_END.month + 1):
        last = dt.date(WINDOW_START.year, m, calendar.monthrange(WINDOW_START.year, m)[1])
        fri = last - dt.timedelta(days=(last.weekday() - 4) % 7)
        d = fri
        while d.isoformat() not in days:          # a Friday holiday falls back inside the same week
            d -= dt.timedelta(days=1)
            assert d > fri - dt.timedelta(days=5)
        want.append(d.isoformat())
    assert got == want and len(got) == dn.N_NOTES == 6
    assert len({g[:7] for g in got}) == 6


def test_one_page_each_with_sim_label(notes, published):
    for n, w, *_ in notes:
        md, pdf = published[n]
        assert count_pdf_pages(pdf) == 1, f"note {n} is not one page"
        assert SIM_LABEL in md
        assert b"ACADEMIC SIMULATION" in pdf.read_bytes()   # document subject; the footer is enforced by desk.reporting.pdf
        assert dn.note_paths(n, w)[0].name == f"desk_note_{n}_{w}.md"


def test_published_notes_are_the_current_build(notes, published):
    for n, w, md, *_ in notes:
        assert published[n][0] == dn.publishable_md(md, n, w), f"note {n} on disk is stale: re-run the stage"


def test_build_is_deterministic(src, notes):
    again = dn.build_all(src)
    assert [x[2] for x in again] == [x[2] for x in notes]


def test_honesty_labels_present(published):
    needles = ["hindsight reconstructions", "unit beta to LME by construction", "fitted to synthetic data",
               "ASSUMPTIONS sized on the", "published after this note", "not a signal", "domestic premium",
               "uses no price, position, trade or event dated later", "reconstructions that use later publications",
               "retrospective test the desk did not run", "up to one month of look-ahead"]
    for n, (md, _pdf) in published.items():
        for s in needles:
            assert s in md, f"note {n} lost the label {s!r}"
        assert "uses nothing dated later" not in md, "the header must not claim more than the as-of view delivers"


def test_band_policy_breaches_are_named_and_the_rule_is_never_the_traders_own(notes):
    """A note that states the band policy never contradicts the bookings: every booking that broke it is named where it
    is reported, the policy is framed as retrospective, and a buyer with credit open is never 'given no open credit'."""
    bk = pd.read_csv(TABLES_DIR / "credit_tracker_bookings.csv")
    tr = pd.read_csv(TABLES_DIR / "credit_tracker.csv", usecols=["date", "cp_id", "credit_exposure_inr"])
    panel = _panel_dates()
    named = 0
    for n, w, md, *_ in notes:
        assert "from me" not in md
        prev = dn.previous_close(panel, w)
        for r in bk[(bk["contract_date"] > prev) & (bk["contract_date"] <= w)].itertuples():
            line = next(ln for ln in md.splitlines() if f"**Sold {r.trade_id}-{r.sale_id}**" in ln)
            outside = r.band_policy_verdict == "OUTSIDE_BAND_POLICY"
            assert ("breaks the band policy" in line) == outside, (n, r.trade_id, r.sale_id)
            named += outside
        month = bk[(bk["contract_date"] >= w[:8] + "01") & (bk["contract_date"] <= prev)]
        for r in month[month["band_policy_verdict"] == "OUTSIDE_BAND_POLICY"].itertuples():
            assert f"{r.trade_id}-{r.sale_id} (outside the band policy" in md, (n, r.trade_id, r.sale_id)
            named += 1
        for ln in md.splitlines():
            if "would allow it no open credit" in ln:
                cp = re.search(r"(BUY_[A-Z]+_\d{2}) is band", ln).group(1)
                open_inr = float(tr[(tr["date"] == w) & (tr["cp_id"] == cp)]["credit_exposure_inr"].iloc[0])
                assert (", yet ₹" in ln) == (open_inr > 0), (n, cp)
    assert named == int((bk["band_policy_verdict"] == "OUTSIDE_BAND_POLICY").sum())


# ------------------------------------------------------------------------------------------------ no hindsight
_DMY = re.compile(r"\b(\d{1,2})-(" + "|".join(MONTHS) + r")(?:-(\d{4}))?\b")
_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_MY = re.compile(r"(?<![0-9]-)\b(" + "|".join(MONTHS) + r")-(\d{4})\b")


def dates_in(text: str) -> list[dt.date]:
    out = [dt.date(int(y or 2022), MONTHS[mo], int(d)) for d, mo, y in _DMY.findall(text)]
    out += [dt.date(int(y), int(m), int(d)) for y, m, d in _ISO.findall(text)]
    out += [dt.date(int(y), MONTHS[mo], 1) for mo, y in _MY.findall(text)]
    return out


def test_dates_parser_catches_all_formats():
    assert dates_in("on 3-Sep and 2022-09-01, Feb-2022, 7-Mar-2022") == [
        dt.date(2022, 9, 3), dt.date(2022, 3, 7), dt.date(2022, 9, 1), dt.date(2022, 2, 1)]


def test_no_date_after_week_end_in_text(notes):
    for n, w, md, *_ in notes:
        found = dates_in(md)
        assert found, "the parser found no dates at all"
        late = [d for d in found if d.isoformat() > w]
        assert not late, f"note {n} ({w}) mentions later dates {late}"


def test_no_later_ticket_sale_or_headline_named(notes):
    book = pd.read_csv(TABLES_DIR / "trade_book.csv", dtype=str)
    heads = pd.read_csv(PROCESSED_DIR / "headlines_weekly.csv", usecols=["published_utc", "title"])
    for n, w, md, *_ in notes:
        for tid in set(re.findall(r"\bT\d{2}\b", md)):
            assert book.set_index("trade_id").loc[tid, "trade_date"] <= w, f"note {n} names {tid}, traded later"
        for tid, sid in set(re.findall(r"\b(T\d{2})-(S\d)\b", md)):
            r = book.set_index("trade_id").loc[tid]
            dates = dict(zip([s.strip() for s in r["sale_ids"].split("|")],
                             [s.strip() for s in r["sale_contract_dates"].split("|")]))
            assert dates[sid] <= w, f"note {n} names {tid}-{sid}, contracted later"
        for q in re.findall(r"“(.+?)”", md):
            stem = q.replace(" …", "")
            hit = heads[heads["title"].str.startswith(stem)]
            assert len(hit) and hit["published_utc"].str[:10].min() <= w, f"note {n} quotes an unknown or later headline"
            assert len(stem.split()) <= dn.HEADLINE_MAX_WORDS


def _poison_frame(df: pd.DataFrame, mask: pd.Series, keep: set[str]) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if c in keep or not mask.any():
            continue
        if pd.api.types.is_bool_dtype(df[c]):
            df.loc[mask, c] = ~df.loc[mask, c]
        elif pd.api.types.is_numeric_dtype(df[c]):
            df.loc[mask, c] = df.loc[mask, c] * 7.0 + 12345.0
        else:
            df[c] = df[c].astype(object)
            df.loc[mask, c] = "987654"          # parses as a number, so a leak shows up as a wrong value, not a crash
    return df


def _write_poisoned_copies(tmp, week_end: str) -> None:
    """Copies of every input with each row (or field) dated after the week end overwritten by garbage.

    Written from each table's own meaning, independently of the module's AS_OF map: a row is poisoned when the
    information in it is dated after the week end.
    """
    T, P = tmp / "tables", tmp / "processed"
    T.mkdir()
    P.mkdir()
    (tmp / "config").mkdir()
    W = week_end
    date_cols = {"attribution_daily.csv": "date", "book_exposures_daily.csv": "date", "credit_tracker.csv": "date",
                 "margin_liquidity.csv": "date", "parity_weekly.csv": "value_date",
                 "term_structure_weekly.csv": "value_date", "credit_tracker_bookings.csv": "contract_date",
                 "trade_eligibility_check.csv": "trade_date", "sentiment_weekly.csv": "lme_close_date",
                 "pnl_sensitivity_sign_robustness.csv": None}
    for name, col in date_cols.items():
        df = pd.read_csv(TABLES_DIR / name)
        if col:
            df = _poison_frame(df, df[col].astype(str).str[:10] > W, {col, "week_end", "trade_id", "cp_id"})
        df.to_csv(T / name, index=False)
    m = pd.read_csv(PROCESSED_DIR / "market_daily.csv")
    _poison_frame(m, m["date"] > W, {"date"}).to_csv(P / "market_daily.csv", index=False)

    # VaR: the row dated t is the forecast made at the close of position_date; its realised half is known at t.
    v = pd.read_csv(TABLES_DIR / "var_daily.csv")
    realised = [c for c in v.columns if c.startswith(("pnl_", "memo_pnl", "exception_")) or c in (
        "lme_ret_frac", "fx_ret_frac", "daily_pnl_inr")]
    v = _poison_frame(v, v["position_date"] > W, {"date", "position_date"})
    v = _poison_frame(v, v["date"] > W, set(v.columns) - set(realised))
    v.to_csv(T / "var_daily.csv", index=False)

    h = pd.read_csv(TABLES_DIR / "sentiment_headlines_scored.csv")
    _poison_frame(h, h["published_utc"].str[:10] > W, {"published_utc", "week_end"}).to_csv(
        T / "sentiment_headlines_scored.csv", index=False)

    cf = pd.read_csv(TABLES_DIR / "trade_cashflows.csv")
    late = cf["settle_date"].astype(str) > W
    for c in ("amount_ccy", "amount_inr"):
        cf.loc[late, c] = cf.loc[late, c] * 7.0 + 12345.0
    cf.to_csv(T / "trade_cashflows.csv", index=False)

    hd = pd.read_csv(TABLES_DIR / "trade_hedges.csv")
    entry = hd["entry_date"].fillna(hd["booking_date"]).astype(str)
    hd = _poison_frame(hd, entry > W, {"trade_id", "instrument", "hedge_id", "entry_date", "booking_date",
                                       "exit_date", "exit_reason", "roll_to", "contract_month", "roll_deadline"})
    late_exit = hd["exit_date"].astype(str) > W
    hd.loc[late_exit, "exit_price_inr_kg"] = hd.loc[late_exit, "exit_price_inr_kg"] * 7.0 + 12345.0
    hd.to_csv(T / "trade_hedges.csv", index=False)

    book = pd.read_csv(TABLES_DIR / "trade_book.csv", dtype=str)
    late_trade = book["trade_date"] > W
    keep = {"trade_id", "trade_date", "lot_ids", "lot_boxes", "bl_dates", "arrival_dates", "release_dates",
            "usance_maturity_dates", "sale_ids", "sale_contract_dates", "sale_lot_ids", "sale_pricing_window",
            "pricing_period_start", "pricing_period_end", "lc_open_date", "payload_mt_per_box", "grade", "lane",
            "incoterm", "purchase_pricing_type", "sale_pricing_types", "payment_instrument", "sale_payment_terms",
            "discharge_port", "box_type"}
    book = _poison_frame(book, late_trade, keep)
    for i in book.index[~late_trade]:                 # sales contracted after the week end: poison their prices
        sids = [s.strip() for s in book.at[i, "sale_ids"].split("|")]
        cds = [s.strip() for s in book.at[i, "sale_contract_dates"].split("|")]
        for col in ("sale_price_inr_t", "sale_factor_frac", "sale_premium_inr_t", "sale_credit_days", "sale_advance_frac",
                    "buyer_names", "buyer_ids"):
            parts = [p.strip() for p in str(book.at[i, col]).split("|")]
            if len(parts) == len(sids):
                parts = ["9" if cd > W and p else p for p, cd in zip(parts, cds)]
                book.at[i, col] = " | ".join(parts)
    book.to_csv(T / "trade_book.csv", index=False)

    raw = yaml.safe_load((CONFIG_DIR / "trades.yaml").read_text(encoding="utf-8"))
    for t in raw["trades"]:
        for kind in ("logistics", "buyer_payment_delay"):
            for e in (t.get("events") or {}).get(kind) or []:
                if str(e["known_date"]) > W:
                    e.update({k: 99 for k in ("arrival_delay_days", "extra_dwell_days", "delay_days") if k in e})
                    e["real_trigger_ref"] = "POISON"
    (tmp / "config" / "trades.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
                                               encoding="utf-8")


def test_poisoning_everything_after_the_week_end_changes_nothing(notes, tmp_path, monkeypatch):
    panel = _panel_dates()
    for n, w, md, _ledger, chart in notes:
        tmp = tmp_path / f"w{n}"
        tmp.mkdir()
        _write_poisoned_copies(tmp, w)
        with monkeypatch.context() as mp:
            mp.setattr(dn, "TABLES_DIR", tmp / "tables")
            mp.setattr(dn, "PROCESSED_DIR", tmp / "processed")
            mp.setattr(dn, "CONFIG_DIR", tmp / "config")
            poisoned = dn.load_sources()
        md2, _l2, chart2 = dn.build_note(poisoned, n, w, panel)
        assert md2 == md, f"note {n} ({w}) changed when data after its week end was poisoned"
        for k in chart:
            pd.testing.assert_frame_equal(chart[k].reset_index(drop=True), chart2[k].reset_index(drop=True),
                                          check_dtype=False)
        shutil.rmtree(tmp)


def test_poison_would_be_caught(src, notes):
    """The poison test has teeth: a view that forgets to cut one frame changes the note."""
    n, w, md, *_ = notes[0]
    leaky = dict(src)
    orig = dn.as_of

    def as_of_leaky(s, week_end):
        out = orig(s, week_end)
        out["sales"] = s["sales"]                  # forgets to cut sales contracted after the week end
        return out

    try:
        dn.as_of = as_of_leaky
        md2 = dn.build_note(leaky, n, w, _panel_dates())[0]
    finally:
        dn.as_of = orig
    assert md2 != md


# ------------------------------------------------------------------------------------------------ traceability
_STRUCTURAL = [r"\bT\d{2}(?:-S\d)?\b", r"\bL\d\b", r"\b(?:BUY|SUP)_[A-Z]+_\d{2}\b", r"\b\d{2}ft\b", r"\b3M\b",
               r"M\+1", r"\b95 %", r"\b99 %", r"\b1-day\b", r"\b10-day\b", r"\b250-day\b", r"\b60-day\b",
               r"\(0\)", r"Desk note \d", r"<!-- widths:[^>]*-->"]


def test_every_digit_belongs_to_a_recorded_fact(notes):
    for n, w, md, ledger, _ in notes:
        text = md
        for pat in _STRUCTURAL:
            text = re.sub(pat, "§", text)
        for f in sorted({f.text for f in ledger.facts}, key=len, reverse=True):
            # whole tokens only, so a one-character fact ("0", band "A") cannot eat part of another word or number
            text = re.sub(r"(?<![0-9A-Za-z.,])" + re.escape(f) + r"(?![0-9A-Za-z])", "§", text)
        stray = [m.group(0) for m in re.finditer(r".{0,25}[0-9].{0,10}", text)]
        assert not stray, f"note {n}: digits not traceable to a recorded fact: {stray[:5]}"


LEVEL_DATE = {"market_daily": "date", "attribution_daily": "date", "book_exposures_daily": "date",
              "credit_tracker": "date", "margin_liquidity": "date", "term_structure_weekly": "value_date",
              "parity_weekly": "value_date", "var_daily": "position_date", "sentiment_weekly": "lme_close_date"}
SUM_DATE = {"attribution_daily": "date", "margin_liquidity": "date", "var_daily": "date", "parity_weekly": "value_date"}


def _table(name: str, cache: dict) -> pd.DataFrame:
    if name not in cache:
        path = PROCESSED_DIR / f"{name}.csv" if name == "market_daily" else TABLES_DIR / f"{name}.csv"
        cache[name] = pd.read_csv(path, dtype={"trade_id": str})
    return cache[name]


def _filter(df: pd.DataFrame, key: tuple) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    for k, v in key:
        if k == "abs":
            continue
        if isinstance(v, str) and v.startswith("!"):
            m &= df[k].astype(str) != v[1:]
        elif isinstance(v, bool):
            m &= df[k].astype(bool) == v
        else:
            m &= df[k].astype(str) == str(v)
    return df[m]


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(1e-6, 1e-9 * max(abs(a), abs(b)))


def _book_value(book: pd.DataFrame, col: str, key: dict) -> str:
    r = book[book["trade_id"] == key["trade_id"]].iloc[0]
    if "sale_id" not in key:
        return r[col]
    sids = [s.strip() for s in r["sale_ids"].split("|")]
    return [s.strip() for s in str(r[col]).split("|")][sids.index(key["sale_id"])]


def test_recorded_facts_recompute_from_the_csvs(notes):
    cache: dict = {}
    events = {}
    for t in yaml.safe_load((CONFIG_DIR / "trades.yaml").read_text(encoding="utf-8"))["trades"]:
        for kind, evs in (t.get("events") or {}).items():
            for e in evs or []:
                events[e.get("event_id") or f"{t['trade_id']}-Q-{e['lot_id']}"] = e
    checked = {"level": 0, "sum": 0, "change": 0, "pct_change": 0, "config": 0, "ident": 0}
    for n, w, md, ledger, _ in notes:
        for f in ledger.facts:
            assert f.date == "static" or f.date <= w, f"note {n}: fact {f.text!r} dated {f.date} after {w}"
            assert f.text in md or f.op == "derived", f"note {n}: recorded fact {f.text!r} not in the note"
            key = dict(f.key)
            if f.op == "config":
                v = config.value(f.column)
                assert (f.value in v) if isinstance(v, list) else str(v) == str(f.value) or _close(float(v), f.value)
            elif f.table == "config/trades.yaml":
                if f.op == "level":
                    e = events[key["event_id"]]
                    assert _close(float(e[f.column]), float(f.value)), f
            elif f.op == "ident":
                if f.table.startswith(("desk.", "config")):
                    continue
                if re.fullmatch(r"T\d{2}-S\d", str(f.value)):
                    tid, sid = str(f.value).split("-")
                    book = _table("trade_book", cache)
                    assert sid in [x.strip() for x in book.set_index("trade_id").loc[tid, "sale_ids"].split("|")], f
                    checked["ident"] += 1
                    continue
                df = _table(f.table, cache)
                col = f.column if f.column in df.columns else None
                if col is None:
                    continue
                cells = df[col].astype(str)
                assert cells.str.contains(re.escape(str(f.value)), regex=True).any(), f"note {n}: {f} not in {f.table}"
            elif f.op == "level":
                df = _table(f.table, cache)
                if f.table == "trade_book":
                    raw = _book_value(df, f.column, key)
                    assert _close(float(str(raw).replace(",", "")), float(f.value)), f
                else:
                    sub = _filter(df, f.key)
                    if f.table in LEVEL_DATE and LEVEL_DATE[f.table] not in key:
                        sub = sub[sub[LEVEL_DATE[f.table]].astype(str).str[:10] == f.date]
                    if f.table == "sentiment_headlines_scored":
                        sub = sub[sub["published_utc"].str[:10] == f.date]
                    assert len(sub) >= 1, f"note {n}: no row for {f}"
                    assert _close(float(sub[f.column].iloc[0]), float(f.value)), f"note {n}: {f} vs {sub[f.column].iloc[0]}"
            elif f.op == "sum":
                df = _filter(_table(f.table, cache), f.key)
                dc = SUM_DATE[f.table]
                d = df[dc].astype(str).str[:10]
                df = df[(d > f.date_from) & (d <= f.date)] if f.date_from else df[d <= f.date]
                if f.table == "var_daily":
                    df = df[df["position_held"].astype(bool)]
                total = float(df[f.column].astype(float).sum())
                assert _close(abs(total) if key.get("abs") else total, float(f.value)), f"note {n}: {f} vs {total}"
            elif f.op in ("change", "pct_change"):
                df = _table(f.table, cache)
                dc = LEVEL_DATE[f.table]
                a = float(df[df[dc] == f.date][f.column].iloc[0])
                b = float(df[df[dc] == f.date_from][f.column].iloc[0])
                assert _close(a - b if f.op == "change" else a / b - 1, float(f.value)), f
            checked[f.op] = checked.get(f.op, 0) + 1
    assert checked["level"] > 300 and checked["sum"] > 150 and checked["change"] >= 6 and checked["pct_change"] >= 18


def test_formatted_levels_spot_check(published, notes):
    """A second, formatting-level check: key levels re-read from the CSVs appear in the text as printed."""
    mkt = pd.read_csv(PROCESSED_DIR / "market_daily.csv").set_index("date")
    att = pd.read_csv(TABLES_DIR / "attribution_daily.csv")
    var = pd.read_csv(TABLES_DIR / "var_daily.csv").set_index("position_date")
    liq = pd.read_csv(TABLES_DIR / "margin_liquidity.csv").set_index("date")
    cr = pd.read_csv(TABLES_DIR / "credit_tracker.csv")
    for n, w, *_ in notes:
        md = published[n][0]
        assert f"USD/INR {mkt.loc[w, 'usdinr']:.2f}" in md
        assert f"USD{NB}{mkt.loc[w, 'lme_3m_usd_t']:,.{1 if mkt.loc[w, 'lme_3m_usd_t'] % 1 else 0}f}" in md
        cum = att[(att["trade_id"] == "BOOK") & (att["date"] == w)]["cum_pnl_inr"].iloc[0]
        assert f"since inception ₹{cum / 1e6:,.1f}{NB}m" in md
        g = var.loc[w, "var_garch_inr"]
        assert f"GARCH ₹{g / 1e6:,.2f}{NB}m" in md
        need = liq.loc[w, "funding_need_total_inr"]
        assert f"Funding need ₹{need / 1e6:,.1f}{NB}m" in md
        for r in cr[(cr["date"] == w) & (cr["role"] == "BUYER")].itertuples():
            assert f"{r.cp_id} {r.utilisation_frac * 100:,.0f}{NB}%" in md


def test_pnl_table_excludes_book_rows_and_ties(published, notes):
    att = pd.read_csv(TABLES_DIR / "attribution_daily.csv")
    trades = att[att["trade_id"] != "BOOK"]
    for n, w, *_ in notes:
        md = published[n][0]
        row = [ln for ln in md.splitlines() if ln.startswith("| Since ")][0]
        total = float(row.split("|")[-2].replace("*", "").replace(MINUS, "-").replace("+", "").replace(",", ""))
        book = att[(att["trade_id"] == "BOOK") & (att["date"] == w)]["cum_pnl_inr"].iloc[0]
        life = trades[trades["date"] <= w]["daily_pnl_inr"].sum()
        assert abs(life - book) <= 1.0
        assert round(book / 1e6, 1) == total
        with_book = att[att["date"] <= w]["daily_pnl_inr"].sum() / 1e6
        assert abs(with_book - total) > 1.0, "double counting BOOK rows would not be detectable here"


# ------------------------------------------------------------------------------------------------ premium band
def _sales_until(w: str | None) -> pd.DataFrame:
    book = pd.read_csv(TABLES_DIR / "trade_book.csv", dtype=str)
    rows = []
    for r in book.itertuples():
        lots = dict(zip([x.strip() for x in r.lot_ids.split("|")], [float(x) for x in r.lot_boxes.split("|")]))
        for sid, cd, lids in zip(r.sale_ids.split("|"), r.sale_contract_dates.split("|"), r.sale_lot_ids.split("|")):
            if w is None or cd.strip() <= w:
                q = sum(lots[x.strip()] for x in lids.split("+")) * float(r.payload_mt_per_box)
                rows.append({"trade_id": r.trade_id, "grade": r.grade, "q": q})
    return pd.DataFrame(rows)


def _slope(sales: pd.DataFrame) -> float:
    rec = pd.read_csv(TABLES_DIR / "parity_weekly.csv").groupby("grade")["recovery_frac"].last()
    share = pd.read_csv(TABLES_DIR / "pnl_sensitivity_sign_robustness.csv").set_index("family").loc["desk_share",
                                                                                                    "base_value"]
    return float((sales["q"] * share * sales["grade"].map(rec)).sum()) if len(sales) else 0.0


def test_premium_slope_reproduces_published_horizon_sensitivity():
    rob = pd.read_csv(TABLES_DIR / "pnl_sensitivity_sign_robustness.csv").set_index("family")
    published = float(rob.loc["anchor_premium", "slope_inr_per_unit"])
    assert abs(_slope(_sales_until(None)) / published - 1) < 0.002     # the published slope also carries funding


def test_point_in_time_premium_band_in_each_note(published, notes):
    att = pd.read_csv(TABLES_DIR / "attribution_daily.csv")
    base = float(config.value("domestic_anchor_premium_inr_t"))
    grid = [float(x) for x in config.value("domestic_anchor_premium_sensitivity_inr_t")]
    for n, w, *_ in notes:
        md = published[n][0]
        s = _slope(_sales_until(w))
        cum = att[(att["trade_id"] == "BOOK") & (att["date"] == w)]["cum_pnl_inr"].iloc[0]
        lo, hi = cum + s * (min(grid) - base), cum + s * (max(grid) - base)

        def m(x):
            v = f"{abs(x) / 1e6:,.1f}"
            return f"{MINUS}₹{v}{NB}m" if x < 0 else f"₹{v}{NB}m"

        assert f"{m(lo)} to {m(hi)} across the registered range" in md
        inside = min(grid) <= base - cum / s <= max(grid)
        assert ("not robust" in md) == inside
    # the last note must reach the same verdict as the published horizon table: not sign-robust
    assert "not robust" in published[notes[-1][0]][0]


# ------------------------------------------------------------------------------------------------ smaller rules
def test_var_quoted_is_the_forecast_made_at_the_week_end(notes, published):
    var = pd.read_csv(TABLES_DIR / "var_daily.csv")
    for n, w, *_ in notes:
        row = var[var["position_date"] == w]
        assert len(row) == 1 and row["date"].iloc[0] > w     # a forecast for the next session, made at w's close
        assert f"GARCH ₹{row['var_garch_inr'].iloc[0] / 1e6:,.2f}{NB}m" in published[n][0]


def test_headline_quotes_follow_the_declared_rule(notes):
    h = pd.read_csv(TABLES_DIR / "sentiment_headlines_scored.csv")
    for n, w, md, *_ in notes:
        for q, source, score in re.findall(r"“(.+?)” \((.+?), VADER ([+−\-][0-9.]+)\)", md):
            stem = q.replace(" …", "")
            hit = h[h["title"].str.startswith(stem) & (h["source"] == source)]
            assert len(hit) == 1
            r = hit.iloc[0]
            assert r["published_utc"][:10] <= w and bool(r["core_chain"]) and not bool(r["cites_later_date"])
            assert abs(r["vader_compound"]) >= dn.VADER_NEUTRAL
            known = h[h["published_utc"].str[:10] <= w].groupby("source").size()
            assert known[source] >= dn.PUBLISHER_MIN_HEADLINES


def test_chart_is_deterministic_and_labelled(notes):
    n, w, _md, _l, chart = notes[0]
    p1 = dn.chart_tape(n, w, chart).read_bytes()
    p2 = dn.chart_tape(n, w, chart).read_bytes()
    assert p1 == p2
    assert not (chart["mkt"]["date"] > w).any() and not (chart["att"]["date"] > w).any()


def test_pdf_render_is_deterministic(notes, tmp_path):
    n, w, md, *_ = notes[-1]
    chart = CHARTS_DIR / f"{dn.chart_name(n)}.png"
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    assert dn.render_pdf(md, a, chart, "t")[0] == 1
    dn.render_pdf(md, b, chart, "t")
    assert a.read_bytes() == b.read_bytes()


def test_ledger_refuses_a_fact_dated_after_the_week_end():
    L = dn.Ledger("2022-03-25")
    with pytest.raises(ValueError):
        L.put("1", 1.0, "market_daily", "usdinr", "2022-03-28")
    assert L.put("1", 1.0, "market_daily", "usdinr", "2022-03-25") == "1"


def test_as_of_columns_are_information_dates(src):
    v = src["var_ante"]
    assert (v["position_date"] < v["date"]).all()
    lines, exits = src["lines"], src["exits"]
    ex = exits[exits["exit_date"] != ""].set_index("hedge_id")["exit_date"]
    ent = lines.set_index("hedge_id")["entry_date"]
    assert (ent.loc[ex.index] <= ex).all()
    assert (src["parity"]["value_date"] <= src["parity"]["week_end"]).all()
    assert (src["term"]["value_date"] <= src["term"]["week_end"]).all()
    assert (src["sent"]["lme_close_date"] <= src["sent"]["week_end"]).all()
    assert set(dn.AS_OF) <= set(src)
