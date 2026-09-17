"""Tests for the P6 deal post-mortem (desk.reporting.post_mortem, MASTER_SPEC Table 7 row 5.3).

What these protect:
* the published numbers are the tables' numbers — recomputed here straight from the CSVs, not through the module;
* the prose template carries no hand-typed numbers (every digit is a placeholder or a structural token);
* the ticket the prose was written for is still the one the declared metric selects, and every qualitative claim holds;
* the thesis section uses nothing dated after the trade date (asserted, and tested by perturbing later market data);
* the PDF is exactly two pages and labelled.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from desk import SIM_LABEL
from desk.paths import CHARTS_DIR, INTERIM_DIR, PROCESSED_DIR, REPORTS_DIR, TABLES_DIR
from desk.reporting import post_mortem as pm
from desk.reporting.pdf import count_pdf_pages

MINUS = "\u2212"
NB = "\u00a0"
TID = pm.TRADE_OF_RECORD
MD = REPORTS_DIR / f"{pm.NAME}.md"
PDF = REPORTS_DIR / f"{pm.NAME}.pdf"
PNGS = [CHARTS_DIR / f"{pm.WATERFALL}.png", CHARTS_DIR / f"{pm.TIMELINE}.png"]


# ------------------------------------------------------------------------------------------------ helpers
def _m(x: float, dp: int = 2, sign: bool = False) -> str:
    """Independent re-implementation of the report's ₹ m format (so a formatting bug cannot hide a data bug)."""
    s = f"{abs(x) / 1e6:,.{dp}f}"
    if x < 0 and float(s.replace(",", "")) != 0:
        return f"{MINUS}₹{s}{NB}m"
    return (f"+₹{s}{NB}m" if sign and float(s.replace(",", "")) != 0 else f"₹{s}{NB}m")


def _n(x: float, dp: int = 0) -> str:
    s = f"{abs(x):,.{dp}f}"
    return f"{MINUS}{s}" if x < 0 and float(s.replace(",", "")) != 0 else s


def _parse(cell: str) -> float:
    c = cell.replace("**", "").replace(MINUS, "-").replace(",", "").replace("+", "").strip()
    return float(c)


def _final_pnl() -> pd.Series:
    att = pd.read_csv(TABLES_DIR / "attribution_daily.csv")
    att = att[att["trade_id"] != "BOOK"]
    return att.sort_values("date").groupby("trade_id")["cum_pnl_inr"].last()


def _repricings() -> pd.DataFrame:
    s = pd.read_csv(TABLES_DIR / "pnl_sensitivity_pricing.csv")
    return s[(s["trade_id"] != "BOOK") & (s["case"] != "base")]


# ------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def published() -> str:
    if not (MD.exists() and PDF.exists() and all(p.exists() for p in PNGS)):
        pm.main()
    return MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def src():
    return pm.load_sources()


@pytest.fixture(scope="module")
def raw(src):
    return pm.compute_raw(src)


# ------------------------------------------------------------------------------------------------ selection
def test_metric_selects_trade_of_record_independently():
    rp = _repricings()
    assert rp.groupby("trade_id").size().nunique() == 1          # every ticket faces the same case set
    worst = rp.groupby("trade_id")["cum_pnl_horizon_inr"].min()
    assert worst.idxmax() == TID
    assert (worst > 0).sum() == 1 and worst[TID] > 0             # "the only ticket positive in all cases"
    final = _final_pnl()
    assert final.idxmax() != TID                                 # raw rupees pick another ticket — the doc says so
    assert worst[final.idxmax()] < 0


def test_selection_table_matches_csvs(published):
    section = published.split("## 1.")[1].split("## 2.")[0]
    rows = [r for r in section.splitlines() if re.match(r"^\| (\*\*)?\d", r)]
    final = _final_pnl()
    rp = _repricings()
    worst = rp.groupby("trade_id")["cum_pnl_horizon_inr"].min()
    anchor = rp[rp["param_key"] == pm.ANCHOR_KEY]
    floor = anchor[anchor["param_value"] == anchor["param_value"].min()].set_index("trade_id")["cum_pnl_horizon_inr"]
    qty = pd.read_csv(TABLES_DIR / "trade_book.csv", usecols=["trade_id", "quantity_mt"]).set_index("trade_id")["quantity_mt"]
    exp = pd.read_csv(TABLES_DIR / "book_exposures_daily.csv", usecols=["scope", "trade_id", "cash_balance_inr"])
    drawn = -exp[exp["scope"] == "trade"].groupby("trade_id")["cash_balance_inr"].min().clip(upper=0)
    assert len(rows) == len(final)
    seen = []
    for row in rows:
        c = [x.strip() for x in row.strip("|").split("|")]
        t = c[1].replace("**", "")
        seen.append(t)
        assert _parse(c[3]) == pytest.approx(round(final[t] / 1e6, 2), abs=1e-9)
        assert _parse(c[4]) == pytest.approx(round(final[t] / qty[t]), abs=1e-9)
        assert _parse(c[5]) == pytest.approx(round(worst[t] / 1e6, 2), abs=1e-9)
        assert _parse(c[6]) == pytest.approx(round(floor[t] / 1e6, 2), abs=1e-9)
        assert _parse(c[7]) == pytest.approx(round(drawn[t] / 1e6, 2), abs=1e-9)
        assert _parse(c[8]) == pytest.approx(round(final[t] / drawn[t], 2), abs=1e-9)
    assert seen == list(worst.sort_values(ascending=False).index)   # ranked by the declared metric
    assert f"{_n(anchor['param_value'].min())} ₹ m" in section


# ------------------------------------------------------------------------------------------------ numbers
def test_headline_and_attribution_numbers_match_csvs(published):
    att = pd.read_csv(TABLES_DIR / "attribution_daily.csv")
    t = att[att["trade_id"] == TID].sort_values("date")
    life = t[pm.PNL_BUCKETS].sum()
    pnl = t["cum_pnl_inr"].iloc[-1]
    assert abs(life.sum() - pnl) < 1.0
    qty = float(pd.read_csv(TABLES_DIR / "trade_book.csv").set_index("trade_id").loc[TID, "quantity_mt"])
    assert f"made **{_m(pnl)}** on {qty:,.0f}{NB}MT (**₹{pnl / qty:,.0f}/MT**)" in published

    def cell(x):
        s = _n(x / 1e6, 2)
        return s if s.startswith(MINUS) or float(s.replace(",", "")) == 0 else f"+{s}"
    assert f"| (0) deal margin at contract dates | {cell(life['new_deal'])} |" in published
    assert f"| (a) LME flat price | {cell(life['lme_flat'])} |" in published
    assert f"| (b) LME–MCX basis | {cell(life['cross_exchange_basis'])} |" in published
    assert f"| (e) USD/INR | {cell(life['fx'])} |" in published
    assert f"| (g) carry, roll, cross-terms | {cell(life['roll_term_structure'])} |" in published
    assert f"| **total** | **{cell(pnl)}** |" in published

    ndt = pd.read_csv(TABLES_DIR / "new_deal_timing.csv").set_index("trade_id").loc[TID]
    assert f"{_m(ndt['new_deal_on_trade_date_inr'], sign=True)} on " in published
    assert abs(ndt["new_deal_on_trade_date_inr"] + ndt["new_deal_after_trade_date_inr"] - life["new_deal"]) < 1.0

    big = t.loc[t["lme_flat"].abs().idxmax()]
    big_day = pd.Timestamp(big["date"]).strftime("%#d-%b")
    assert f"**{_m(big['lme_flat'], sign=True)} on {big_day} alone**" in published
    assert f"{_m(life['lme_flat'] - big['lme_flat'], sign=True)} on every other day" in published

    book = att[att["trade_id"] == "BOOK"].sort_values("date")["cum_pnl_inr"].iloc[-1]
    rob = pd.read_csv(TABLES_DIR / "pnl_sensitivity_sign_robustness.csv").set_index("family").loc["anchor_premium"]
    assert f"of the book's {_m(book, 1)}" in published
    assert f"{_m(rob['pnl_min_inr'], 1)} to {_m(rob['pnl_max_inr'], 1, sign=True)}" in published
    assert f"break-even {_n(rob['breakeven_value'])}{NB}₹/MT inside it" in published


def test_thesis_execution_and_admission_numbers_match_csvs(published):
    el = pd.read_csv(TABLES_DIR / "trade_eligibility_check.csv").set_index("trade_id").loc[TID]
    for col in ("net_arb_inr_t", "net_arb_pit_mix_inr_t", "net_arb_conv18k_inr_t"):
        assert f"₹{el[col]:,.0f}" in published
    cf = pd.read_csv(TABLES_DIR / "trade_cashflows.csv")
    cf = cf[(cf["trade_id"] == TID) & (cf["scenario"] == "REALISED")]
    sale = cf.loc[cf["cf_type"].str.startswith("SALE_"), "amount_inr"].sum()
    assert f"= {_m(sale, 1)} (vs" in published
    assert f"Settled {_m(cf.loc[cf['cf_type'] == 'FX_FORWARD', 'amount_inr'].sum(), sign=True)}" in published
    exp = pd.read_csv(TABLES_DIR / "book_exposures_daily.csv", usecols=["trade_id", "cash_balance_inr", "mcx_im_inr"])
    e = exp[exp["trade_id"] == TID]
    assert f"Cash drawn peaked at {_m(-e['cash_balance_inr'].min(), 1)}" in published
    assert f"Peak initial margin {_m(e['mcx_im_inr'].max(), 1)}" in published

    rp = pd.read_csv(TABLES_DIR / "pnl_sensitivity_pricing.csv")
    t = rp[rp["trade_id"] == TID].set_index("case")["cum_pnl_horizon_inr"]
    anc = rp[(rp["trade_id"] == TID) & (rp["param_key"] == pm.ANCHOR_KEY)].sort_values("param_value")
    assert (f"makes {_m(anc['cum_pnl_horizon_inr'].iloc[0], 1, True)} to "
            f"{_m(anc['cum_pnl_horizon_inr'].iloc[-1], 1, True)}") in published
    assert f"on the point-in-time grade mix, {_m(t[pm.PIT_CASE], 1, True)}" in published
    assert f"desk share, {_m(t['desk_share_0.00'], 1, True)}" in published
    slope, icpt = np.polyfit(anc["param_value"], anc["cum_pnl_horizon_inr"], 1)
    assert f"break-even {_n(-icpt / slope)}{NB}₹/MT, far outside it" in published

    ev = pd.read_csv(INTERIM_DIR / "price_evidence" / "adc12_vs_duty_paid_parity.csv")
    ev = ev[ev["use"]]
    b, a = np.polyfit(ev["duty_paid_cash_parity_inr_t"], ev["premium_vs_cash_parity_inr_t"], 1)
    mkt = pd.read_csv(PROCESSED_DIR / "market_daily.csv", usecols=["date", "mcx_al_spot_inr_kg"]).set_index("date")
    td = el["trade_date"]
    parity = mkt.loc[td, "mcx_al_spot_inr_kg"] * 1000        # mcx_domestic_premium_inr_kg is 0 (asserted by the stage)
    fit = a + b * parity
    assert f"premium at {_n(fit)}{NB}₹/MT at that parity" in published
    assert f"leaves {TID} {_m(np.polyval([slope, icpt], fit), 1, True)}" in published

    basis = pd.read_csv(TABLES_DIR / "mcx_basis_risk.csv")
    mb = basis[(basis["metric"] == "basis_bucket_mirror_inr") & (basis["scope"] == TID)]["value"].iloc[0]
    assert f"{_m(mb, sign=True)} on the third-party mirror" in published
    mbeta = pd.read_csv(TABLES_DIR / "var_mcx_beta.csv").set_index("sampling")
    assert f"beta is {_n(mbeta.at['weekly', 'beta'], 2)} on weekly closes" in published
    assert f"never the biased daily {_n(mbeta.at['daily', 'beta'], 2)}" in published
    assert "uses nothing published after" not in published and "reconstructions that use later publications" in published


def test_published_markdown_is_the_current_render(published, src):
    md, _ = pm.build_markdown(src)
    assert md == published


# ------------------------------------------------------------------------------------------------ honesty guards
class _Sentinel(dict):
    def __missing__(self, key):
        return "@"


STRUCTURAL = [r"^#+ \d+\.", r"^\d+\. ", r"\((?:0|[a-g])\)", r"GARCH\(1,1\)", r"§\d+[a-z]?(?:\.\d+)*",
              r"Phase \d+(?:\.\d+)?", r"\bM1\b", r"\b3M\b", r"ADC12"]


def test_template_has_no_hand_typed_numbers():
    text = pm.TEMPLATE.format_map(_Sentinel())
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    for pat in STRUCTURAL:
        text = re.sub(pat, "", text, flags=re.M)
    leftovers = [ln for ln in text.splitlines() if re.search(r"\d", ln)]
    assert not leftovers, f"digits typed into the post-mortem template: {leftovers}"


def test_every_claim_holds_and_the_guard_bites(raw):
    assert pm.check_claims(raw) == []
    broken = dict(raw, selected_id="T01", big_net_mt=abs(raw["big_net_mt"]), paid_date="2099-01-01")
    failed = pm.check_claims(broken)
    assert any("selects the ticket" in f for f in failed)
    assert any("SHORT" in f for f in failed)
    assert any("due date" in f for f in failed)


def test_thesis_uses_nothing_after_the_trade_date(src, raw):
    td = raw["trade_date"]
    assert max(raw["thesis_input_dates"]) <= td
    assert raw["garch_sample_end"] < td
    # perturb every market and volatility row dated after the trade date: the thesis numbers must not move
    later = dict(src)
    mkt = src["mkt"].copy()
    after = mkt["date"] > td
    for col in ("lme_cash_usd_t", "lme_cash_3m_spread_usd_t", "usdinr", "mcx_al_spot_inr_kg", "mcx_al_m1_inr_kg"):
        mkt.loc[after, col] = mkt.loc[after, col] * 1.7
    vol = src["vol"].copy()
    vol.loc[vol["date"] > td, ["sigma_lme_garch_frac", "sigma_lme_hist250_frac"]] *= 3.0
    later.update(mkt=mkt, vol=vol)
    shifted = pm.compute_raw(later)
    thesis_keys = ["ath_px", "ath_date", "break_usd", "break_pct", "cash_td", "spread_td", "fx_td", "fx_ws", "garch_td",
                   "hist_td", "na_base", "na_pit", "na_conv", "hurdle", "repl", "netback", "gf_td", "m1_td",
                   "formula_px_td", "rule_px_td", "metal_per_t", "sell_lots", "buy_lots", "n_board", "n_board_eligible"]
    for k in thesis_keys:
        assert shifted[k] == raw[k], k


def test_buckets_and_waterfall_steps_tie(raw):
    total = sum(raw[f"b_{k}"] for k in pm.PNL_BUCKETS)
    assert abs(total - raw["pnl"]) < 1.0
    assert abs(raw["nd_td"] + raw["nd_after"] - raw["b_new_deal"]) < 1.0
    assert abs(raw["lme_phys"] + raw["lme_mcx"] - raw["b_lme_flat"]) < 1.0
    assert abs(raw["fx_fwd"] + raw["fx_purch"] + raw["fx_mcx"] + raw["fx_other"] - raw["b_fx"]) < 1.0


# ------------------------------------------------------------------------------------------------ outputs
def test_pdf_is_exactly_two_pages_and_labelled(published):
    assert count_pdf_pages(PDF) == pm.MAX_PAGES == 2
    head = published[:1200]
    assert SIM_LABEL in head
    assert "not sign-robust" in head                             # the headline travels with its band
    assert b"/Subject (ACADEMIC SIMULATION" in PDF.read_bytes()   # metadata carries the label (em dash is PDFDocEncoded)
    for p in PNGS:
        assert p.exists() and p.stat().st_size > 10_000
        assert f"../charts/{p.name}" in published


def test_page_guard_sees_an_overflow(tmp_path, published):
    """The stage's two-page assert is only as good as the count it reads: an overflowing render must report > 2,
    and the renderer's count must agree with the file's own page objects."""
    text = "\n".join(ln for ln in published.splitlines() if not ln.startswith("!["))   # tmp_path has no charts
    probe = tmp_path / "overflow.pdf"
    n = pm.render_pdf(text + "\n\n" + published.split("## 5.")[1] * 3, probe)
    assert n > pm.MAX_PAGES
    assert count_pdf_pages(probe) == n
