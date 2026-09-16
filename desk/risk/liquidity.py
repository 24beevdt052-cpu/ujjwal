"""Margin & liquidity through the crash fortnight (MASTER_SPEC Table 6 row 4.5).

The Phase 3 book is funded by one always-drawn cash-credit line with no limit (CONTRACTS §7a.5): its cash balance
bottoms at −₹1,159.9 m on 2022-07-20 with nothing to say whether a bank would have lent that. This module asks the
question a desk treasurer asks every morning — *can we meet today's margin call and next week's LC payments inside
the lines we have?* — and answers it with the book's own cash, not a second valuation:

1. **Cash, decomposed.** `trade_cashflows.csv` (REALISED) is summed by settle date into commercial categories and the
   MCX margin category; the sum reproduces `book_exposures_daily.cash_balance_inr` and the MCX category reproduces
   `mcx_variation_margin.csv` (controls). The funding accrual P3 books as P&L is added back as interest debited to
   the line.
2. **Facilities (ASSUMPTION, sized ex ante).** A fund-based working-capital limit and a non-fund LC limit sized the
   way a bank would at sanction — on the desk's *plan* at the last parity week before the window — and a minimum
   undrawn buffer. Headroom = limit − buffer − funding need, where the funding need is commercial cash + margin cash
   + interest. Nothing is sized from the book's realised peak; `limit_grid` shows the answer at other sizes.
3. **Margin at risk.** For every day, the extra margin cash the open MCX lines would call if LME moved by a 99 %
   10-day move (point-in-time: GARCH and rolling vols from the Phase 4.1 VaR report, and the empirical 10-day
   quantile, whichever is largest), with initial margin re-struck at the stressed 15 % rate P3 publishes.
4. **The crash-fortnight stress.** The CONTRACTS §7a.3 crash fortnight (the 10-return window with the most negative
   LME cash return) re-run with LME moving *against* the hedges by that 99 % move, every held line re-marked
   through the MCX proxy (which is exactly proportional to LME cash when FX and carry are held — the domestic
   premium is 0), the physical cargo's offsetting gain left as what it is inside a fortnight: a mark, not cash.

Everything here is reporting on a SIMULATED book (ACADEMIC SIMULATION — not actual trades). The MCX series is a
PROXY (duty-paid import parity), so margin moves inherit its unit beta to LME x FX.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd

from desk import HISTORY_START, HORIZON_END, SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.paths import PROCESSED_DIR, TABLES_DIR

# CONTRACTS §7a.3: a "fortnight" is 10 trading-day returns (11 observations). Used for both reporting windows.
FORTNIGHT_RETURNS = 10
# MCX VM rows that close a line at that day's settle; every other action leaves the line open after the close.
CLOSING_ACTIONS = ("exit", "roll_out")
STRESS_IM_COLUMN = "im_stress_015_inr"     # P3's stressed initial margin at 15 % of contract value
STRESS_IM_LABEL = "15 %"
CRASH_WINDOW_EVENT = "E1_CRASH_FORTNIGHT"
RECON_TOL_INR = 1.0
LABEL = SIM_LABEL

# trade_cashflows leg_type -> cash category. Order is the column order of the published table.
CASH_CATEGORIES = {
    "purchase": ("PURCHASE_INVOICE", "PURCHASE_PROVISIONAL", "PURCHASE_FINAL"),
    "sale": ("SALE_ADVANCE", "SALE_BALANCE"),
    "duty": ("CUSTOMS_DUTY", "CUSTOMS_DUTY_DIFFERENTIAL"),
    "igst": ("IGST_IMPORT", "IGST_CREDIT"),
    "freight": ("FREIGHT",),
    "logistics_claims": ("PORT_CHARGES", "PSIC", "INSURANCE", "DEMURRAGE", "REJECTED_BOX_COST", "QUALITY_CLAIM"),
    "bank_charges": ("LC_OPENING_FEE", "LC_CONFIRMATION_FEE", "LC_USANCE_FEE", "IMPORT_BILL_COMMISSION",
                     "USANCE_INTEREST"),
    "fx_forward": ("FX_FORWARD",),
    "mcx_margin": ("MCX_VARIATION_MARGIN", "MCX_INITIAL_MARGIN", "MCX_TRANSACTION_COST", "MCX_SLIPPAGE"),
}
LC_PRINCIPAL_LEGS = ("PURCHASE_INVOICE", "PURCHASE_PROVISIONAL")


# ------------------------------------------------------------------------------------------------ parameters
@dataclass(frozen=True)
class Facility:
    fb_limit_inr: float
    lc_limit_inr: float
    buffer_frac: float
    plan_week_end: str
    plan_throughput_mt_pa: float
    plan_lc_tenor_days: float
    rounding_inr: float
    stress_conf: float
    stress_horizon_days: int

    @property
    def buffer_inr(self) -> float:
        return self.buffer_frac * self.fb_limit_inr

    @property
    def z(self) -> float:
        return NormalDist().inv_cdf(self.stress_conf)


def facility_params() -> Facility:
    """Every judgement below is an ASSUMPTION in config/params/risk.yaml, section 'Phase 5 liquidity & policy'."""
    v = config.value
    return Facility(
        fb_limit_inr=float(v("liq_fb_wc_limit_inr")),
        lc_limit_inr=float(v("liq_nfb_lc_limit_inr")),
        buffer_frac=float(v("liq_min_cash_buffer_frac_of_fb_limit")),
        plan_week_end=str(v("liq_plan_parity_week_end")),
        plan_throughput_mt_pa=float(v("liq_plan_throughput_mt_pa")),
        plan_lc_tenor_days=float(v("liq_plan_lc_tenor_days")),
        rounding_inr=float(v("liq_facility_rounding_inr")),
        stress_conf=float(v("liq_stress_confidence_frac")),
        stress_horizon_days=int(v("liq_stress_horizon_days")),
    )


# ------------------------------------------------------------------------------------------------ inputs
@dataclass
class LiquidityInputs:
    vm: pd.DataFrame            # mcx_variation_margin.csv (date x hedge line)
    book: pd.DataFrame          # book_exposures_daily.csv, scope == book, indexed by date string
    cashflows: pd.DataFrame     # trade_cashflows.csv, REALISED only
    planned: pd.DataFrame       # trade_cashflows.csv, PLANNED_AT_TRADE_DATE purchase legs
    funding_cum: pd.Series      # Σ trades' FUNDING-leg accrual to date (≤ 0 is a cost), indexed by date
    market: pd.DataFrame        # market_daily.csv, indexed by date
    vol: pd.DataFrame           # var_vol_forecasts.csv, indexed by forecast date
    garch_fits: pd.DataFrame    # var_garch_params.csv, LME Normal fits, indexed by sample_end
    trade_book: pd.DataFrame
    windows: pd.DataFrame       # adverse_event_windows.csv
    parity: pd.DataFrame        # parity_weekly.csv rows of the plan week


def load_inputs(fac: Facility | None = None) -> LiquidityInputs:
    fac = fac or facility_params()
    T = TABLES_DIR
    vm = pd.read_csv(T / "mcx_variation_margin.csv")
    ex = pd.read_csv(T / "book_exposures_daily.csv",
                     usecols=["date", "scope", "cash_balance_inr", "mcx_im_inr", "mcx_lots_open", "lme_delta_mt",
                              "lme_delta_physical_mt", "lme_delta_mcx_mt", "unsold_mt"])
    book = ex[ex["scope"] == "book"].drop(columns="scope").set_index("date").sort_index()
    cf = pd.read_csv(T / "trade_cashflows.csv",
                     usecols=["scenario", "trade_id", "leg_id", "leg_type", "settle_date", "amount_ccy", "amount_inr"])
    realised = cf[cf["scenario"] == "REALISED"].drop(columns="scenario").reset_index(drop=True)
    planned = cf[(cf["scenario"] == "PLANNED_AT_TRADE_DATE") & cf["leg_type"].str.startswith("PURCHASE")]
    md = pd.read_csv(T / "mtm_daily.csv", usecols=["date", "leg_type", "realised_cum_inr"])
    funding = md[md["leg_type"] == "FUNDING"].groupby("date")["realised_cum_inr"].sum().sort_index()
    del md
    market = pd.read_csv(PROCESSED_DIR / "market_daily.csv",
                         usecols=["date", "lme_cash_usd_t", "usdinr", "mcx_al_m1_inr_kg", "mcx_src"]).set_index("date")
    vol = pd.read_csv(T / "var_vol_forecasts.csv",
                      usecols=["date", "sigma_lme_garch_frac", "sigma_lme_hist250_frac", "sigma_lme_hist60_frac",
                               "lme_garch_sample_end"]).set_index("date")
    fits = pd.read_csv(T / "var_garch_params.csv",
                       usecols=["series", "dist", "sample_end", "persistence", "uncond_vol_daily_frac"])
    fits = fits[(fits["series"] == "lme") & (fits["dist"] == "normal")].set_index("sample_end")
    tb = pd.read_csv(T / "trade_book.csv", usecols=["trade_id", "lc_open_date", "lc_amount_tolerance_frac",
                                                     "payment_instrument", "usance_days"])
    windows = pd.read_csv(T / "adverse_event_windows.csv")
    pw = pd.read_csv(T / "parity_weekly.csv", usecols=["week_end", "value_date", "grade", "lane", "usdinr", "cif_usd_t",
                                                        "finance_inr_t", "igst_finance_inr_t", "landed_inr_t"])
    parity = pw[pw["week_end"] == fac.plan_week_end].reset_index(drop=True)
    if parity.empty:
        raise ValueError(f"no parity rows for liq_plan_parity_week_end {fac.plan_week_end}")
    return LiquidityInputs(vm, book, realised, planned, funding, market, vol, fits, tb, windows, parity)


def report_dates(inputs: LiquidityInputs) -> pd.Index:
    """Panel days WINDOW_START → HORIZON_END: the book's own days plus the pre-trade days of March (all zero)."""
    idx = inputs.market.index
    dates = idx[(idx >= str(WINDOW_START)) & (idx <= str(HORIZON_END))]
    missing = inputs.book.index.difference(dates)
    if len(missing):
        raise ValueError(f"book exposure dates off the panel calendar: {list(missing[:5])}")
    return dates


# ------------------------------------------------------------------------------------------------ cash + margin
def cash_components(cf: pd.DataFrame, dates: pd.Index) -> pd.DataFrame:
    """Cumulative settled cash by category (INR), on the panel calendar. A flow settling on a non-panel day lands on
    the next panel day (never earlier)."""
    known = {lt for lts in CASH_CATEGORIES.values() for lt in lts}
    unknown = set(cf["leg_type"]) - known
    if unknown:
        raise ValueError(f"trade_cashflows leg types without a cash category: {sorted(unknown)}")
    cat_of = {lt: c for c, lts in CASH_CATEGORIES.items() for lt in lts}
    flows = cf.assign(category=cf["leg_type"].map(cat_of))
    pos = dates.searchsorted(flows["settle_date"].to_numpy(), side="left")
    if (pos >= len(dates)).any():
        raise ValueError("a realised cashflow settles after HORIZON_END")
    flows = flows.assign(panel_date=dates[pos])
    daily = flows.pivot_table(index="panel_date", columns="category", values="amount_inr", aggfunc="sum")
    daily = daily.reindex(index=dates, columns=list(CASH_CATEGORIES)).fillna(0.0)
    out = daily.cumsum()
    out.columns = [f"cash_{c}_cum_inr" for c in out.columns]
    return out


def mcx_leg_cumulative(cf: pd.DataFrame, dates: pd.Index) -> pd.DataFrame:
    """The MCX category split by leg type, for the reconciliation to the VM table."""
    m = cf[cf["leg_type"].str.startswith("MCX_")]
    pos = dates.searchsorted(m["settle_date"].to_numpy(), side="left")
    m = m.assign(panel_date=dates[pos])
    p = m.pivot_table(index="panel_date", columns="leg_type", values="amount_inr", aggfunc="sum")
    return p.reindex(index=dates).fillna(0.0).cumsum()


def margin_daily(vm: pd.DataFrame, dates: pd.Index) -> pd.DataFrame:
    """Book-level MCX margin per day from the P3 hedge-line table. `im_required_inr` is a STOCK (take the daily sum,
    never a running total); VM, charges and IM changes are FLOWS."""
    g = vm.groupby("date")
    open_rows = vm[~vm["action"].isin(CLOSING_ACTIONS)]
    out = pd.DataFrame({
        "vm_inr": g["vm_inr"].sum(),
        "txn_cost_inr": g["txn_cost_inr"].sum(),
        "im_change_inr": g["im_change_inr"].sum(),
        "net_margin_cash_inr": g["net_margin_cash_inr"].sum(),
        "mcx_im_inr": g["im_required_inr"].sum(),
        "mcx_im_stress_015_inr": g[STRESS_IM_COLUMN].sum(),
        "mcx_lots_net_open": open_rows.groupby("date")["lots"].sum(),
        "mcx_lots_gross_open": open_rows.assign(a=open_rows["lots"].abs()).groupby("date")["a"].sum(),
    })
    out = out.reindex(dates)
    flows = ["vm_inr", "txn_cost_inr", "im_change_inr", "net_margin_cash_inr"]
    out[flows] = out[flows].fillna(0.0)
    stocks = ["mcx_im_inr", "mcx_im_stress_015_inr", "mcx_lots_net_open", "mcx_lots_gross_open"]
    out[stocks] = out[stocks].fillna(0.0)
    out["cum_vm_inr"] = out["vm_inr"].cumsum()
    out["cum_txn_cost_inr"] = out["txn_cost_inr"].cumsum()
    out["cum_margin_cash_inr"] = out["net_margin_cash_inr"].cumsum()
    out["margin_cash_deployed_inr"] = -out["cum_margin_cash_inr"]
    return out


# ------------------------------------------------------------------------------------------------ LC limit
def lc_lots(inputs: LiquidityInputs) -> pd.DataFrame:
    """One row per bill-of-lading lot: the LC face the desk opened and the day the bank's liability for it ended.

    Face = the purchase value planned at the trade date (PLANNED_AT_TRADE_DATE provisional + final, or invoice) x
    (1 + the ticket's LC amount tolerance): what a desk can put on an LC application before the quotational period
    has priced. The liability ends when the LC principal is paid — at sight on document presentation, or at usance
    maturity (the REALISED settle date of the invoice / provisional payment). Final price adjustments settle outside
    the credit.
    """
    pl = inputs.planned.assign(lot=inputs.planned["leg_id"].str.split(":").str[1])
    face = pl.groupby(["trade_id", "lot"])["amount_ccy"].sum().mul(-1.0).rename("face_planned_usd").reset_index()
    re = inputs.cashflows[inputs.cashflows["leg_type"].isin(LC_PRINCIPAL_LEGS)]
    re = re.assign(lot=re["leg_id"].str.split(":").str[1])[["trade_id", "lot", "settle_date"]]
    if re.duplicated(["trade_id", "lot"]).any():
        raise ValueError("more than one LC principal payment on a lot")
    lots = face.merge(re, on=["trade_id", "lot"], how="left").merge(inputs.trade_book, on="trade_id", how="left")
    if lots["settle_date"].isna().any() or lots["lc_open_date"].isna().any():
        raise ValueError("an LC lot has no opening date or no principal payment")
    lots["lc_face_usd"] = lots["face_planned_usd"] * (1.0 + lots["lc_amount_tolerance_frac"])
    return lots.rename(columns={"settle_date": "lc_release_date"})


def lc_outstanding(lots: pd.DataFrame, market: pd.DataFrame, dates: pd.Index) -> pd.DataFrame:
    """LC line use per day at face incl. tolerance (base), plus a MEMO without the amount tolerance.

    The base is the conservative count: a usance bill, once accepted, is a bank liability at its invoice value, not at
    face plus tolerance, so the memo (planned face, no tolerance, same life) bounds how much of the breach is that
    convention (docs/51 §1.4). Planned-vs-final price differences are not in either.
    """
    usd = pd.Series(0.0, index=dates)
    usd_ex_tol = pd.Series(0.0, index=dates)
    d = dates.to_numpy()
    for row in lots.itertuples(index=False):
        live = (d >= row.lc_open_date) & (d < row.lc_release_date)
        usd[live] += row.lc_face_usd
        usd_ex_tol[live] += row.face_planned_usd
    fx = market.loc[dates, "usdinr"]
    return pd.DataFrame({"lc_outstanding_usd": usd, "lc_outstanding_inr": usd * fx,
                         "memo_lc_outstanding_ex_tolerance_inr": usd_ex_tol * fx})


# ------------------------------------------------------------------------------------------------ stress moves
def stress_moves(inputs: LiquidityInputs, dates: pd.Index, fac: Facility) -> pd.DataFrame:
    """The 99 % h-day LME cash log move as of each CLOSE t, point-in-time.

    Normal readings use each volatility forecast made at close t — the Phase 4.1 row dated the next panel day (its
    parameters were estimated on returns to that fit's sample_end ≤ t). GARCH is aggregated over h days with its own
    term structure, Σ_k [σ²∞ + p^(k−1) (σ²₁ − σ²∞)], so a spike decays at the fitted persistence p instead of being
    scaled by sqrt(h); the two rolling windows assume constant volatility and scale by sqrt(h). The empirical
    reading is the 99th (1st) percentile of overlapping h-day log returns from HISTORY_START to t. The binding move is
    the largest, because docs/40 §6.3 and §11.3 show the Normal understating LME tails (the 8-Mar-2022 fall was
    −4.5 σ even on GARCH).
    """
    h = fac.stress_horizon_days
    vol = inputs.vol.shift(-1)          # row t now holds the forecast made at close t
    mkt = inputs.market
    lme = mkt.loc[(mkt.index >= str(HISTORY_START))]["lme_cash_usd_t"]
    rh = np.log(lme).diff(h)
    rows = []
    scale = fac.z * math.sqrt(h)
    for d in dates:
        hist = rh.loc[:d].dropna().to_numpy()
        q_up = float(np.quantile(hist, fac.stress_conf))
        q_dn = float(np.quantile(hist, 1.0 - fac.stress_conf))
        sg = vol.loc[d]
        fit = inputs.garch_fits.loc[sg["lme_garch_sample_end"]]
        p, s_inf, s1 = float(fit["persistence"]), float(fit["uncond_vol_daily_frac"]), float(sg["sigma_lme_garch_frac"])
        var_h = (h * s_inf ** 2 + (s1 ** 2 - s_inf ** 2) * (1.0 - p ** h) / (1.0 - p)) if p < 1.0 else h * s1 ** 2
        sigma_garch_h = math.sqrt(var_h)
        normal = {
            "garch": fac.z * sigma_garch_h,
            "hist250": scale * sg["sigma_lme_hist250_frac"],
            "hist60": scale * sg["sigma_lme_hist60_frac"],
        }
        up = {**normal, "empirical": q_up}
        dn = {**normal, "empirical": -q_dn}
        rows.append({
            "date": d,
            "sigma_lme_garch_frac": s1,
            "garch_persistence": p,
            "sigma_lme_garch_hday_frac": sigma_garch_h,
            "sigma_lme_hist250_frac": sg["sigma_lme_hist250_frac"],
            "sigma_lme_hist60_frac": sg["sigma_lme_hist60_frac"],
            "move_normal_garch_logret": normal["garch"],
            "move_normal_hist250_logret": normal["hist250"],
            "move_normal_hist60_logret": normal["hist60"],
            "move_empirical_up_logret": q_up,
            "move_empirical_down_logret": q_dn,
            "stress_move_up_logret": max(up.values()),
            "stress_move_down_logret": -max(dn.values()),
            "stress_binding_up": max(up, key=up.get),
            "stress_binding_down": max(dn, key=dn.get),
        })
    return pd.DataFrame(rows).set_index("date")


def _open_lines(vm: pd.DataFrame, d: str) -> pd.DataFrame:
    rows = vm[(vm["date"] == d) & ~vm["action"].isin(CLOSING_ACTIONS)]
    return rows.assign(kg=rows["lots"] * rows["lot_mt"] * 1000.0)


def margin_at_risk(vm: pd.DataFrame, moves: pd.DataFrame, dates: pd.Index) -> pd.DataFrame:
    """Instantaneous margin call if LME jumps by the day's 99 % move against the lines open after close t.

    A line's settle is proportional to LME cash in the proxy (premium 0, FX and carry held), so a log move x re-marks
    it by e^x: VM = kg x settle x (e^x − 1), IM = im x e^x. The call is −VM + ΔIM; the stressed variant re-strikes IM
    at P3's 15 % column. Both directions are tried and the worse is reported (the book is net short MCX, but T02
    held a long line in April–May)."""
    out = []
    for d in dates:
        lines = _open_lines(vm, d)
        if lines.empty:
            out.append({"date": d, "mar_99_inr": 0.0, "mar_99_stressed_im_inr": 0.0, "mar_direction": ""})
            continue
        notional = float((lines["kg"] * lines["settle_inr_kg"]).sum())
        im = float(lines["im_required_inr"].sum())
        im15 = float(lines[STRESS_IM_COLUMN].sum())
        best, best15, direction = 0.0, 0.0, ""
        for name, x in (("LME_UP", moves.at[d, "stress_move_up_logret"]),
                        ("LME_DOWN", moves.at[d, "stress_move_down_logret"])):
            f = math.exp(x)
            vm_move = notional * (f - 1.0)
            call = -vm_move + im * (f - 1.0)
            call15 = -vm_move + im15 * f - im
            if call15 > best15:
                best15, direction = call15, name
            best = max(best, call)
        out.append({"date": d, "mar_99_inr": best, "mar_99_stressed_im_inr": best15, "mar_direction": direction})
    return pd.DataFrame(out).set_index("date")


# ------------------------------------------------------------------------------------------------ daily table
def build_daily(inputs: LiquidityInputs, fac: Facility) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The published `margin_liquidity.csv`, plus the LC lot table and the stress-move table it rests on."""
    dates = report_dates(inputs)
    mkt = inputs.market.loc[dates]
    if not (mkt["mcx_src"] == "PROXY_IMPORT_PARITY").all():
        raise ValueError("the margin stress re-marks MCX through the parity proxy; a MANUAL MCX day breaks that")
    if abs(float(config.value("mcx_domestic_premium_inr_kg"))) > 0:
        raise ValueError("MCX proxy premium is non-zero: settle is no longer proportional to LME cash")
    book = inputs.book.reindex(dates)
    margin = margin_daily(inputs.vm, dates)
    cash = cash_components(inputs.cashflows, dates)
    lots = lc_lots(inputs)
    lc = lc_outstanding(lots, inputs.market, dates)
    moves = stress_moves(inputs, dates, fac)
    mar = margin_at_risk(inputs.vm, moves, dates)

    d = pd.DataFrame(index=dates)
    d.index.name = "date"
    d["in_window"] = (dates >= str(WINDOW_START)) & (dates <= str(WINDOW_END))
    d["lme_cash_usd_t"] = mkt["lme_cash_usd_t"]
    d["usdinr"] = mkt["usdinr"]
    d = d.join(margin)
    d = d.join(cash)
    d["cash_balance_inr"] = book["cash_balance_inr"].fillna(0.0)
    d["funding_accrued_cum_inr"] = inputs.funding_cum.reindex(dates).fillna(0.0)
    d["interest_accrued_inr"] = -d["funding_accrued_cum_inr"]
    d["commercial_funding_need_inr"] = -(d["cash_balance_inr"] - d["cum_margin_cash_inr"])
    d["funding_need_total_inr"] = d["commercial_funding_need_inr"] + d["margin_cash_deployed_inr"] + d[
        "interest_accrued_inr"]
    d["fb_limit_inr"] = fac.fb_limit_inr
    d["min_cash_buffer_inr"] = fac.buffer_inr
    d["fb_drawn_inr"] = d["funding_need_total_inr"].clip(lower=0.0)
    d["surplus_cash_inr"] = (-d["funding_need_total_inr"]).clip(lower=0.0)
    d["fb_utilisation_frac"] = d["fb_drawn_inr"] / fac.fb_limit_inr
    d["undrawn_inr"] = fac.fb_limit_inr - d["funding_need_total_inr"]
    d["headroom_inr"] = fac.fb_limit_inr - fac.buffer_inr - d["funding_need_total_inr"]
    d["flag_buffer_breach"] = d["headroom_inr"] < 0
    d["flag_fb_limit_breach"] = d["funding_need_total_inr"] > fac.fb_limit_inr
    d = d.join(lc)
    d["lc_limit_inr"] = fac.lc_limit_inr
    d["lc_utilisation_frac"] = d["lc_outstanding_inr"] / fac.lc_limit_inr
    d["flag_lc_limit_breach"] = d["lc_outstanding_inr"] > fac.lc_limit_inr
    d["bank_exposure_fb_plus_lc_inr"] = d["fb_drawn_inr"] + d["lc_outstanding_inr"]
    d = d.join(moves[["stress_move_up_logret", "stress_move_down_logret", "stress_binding_up"]])
    d = d.join(mar)
    d["flag_mar_exceeds_buffer"] = d["mar_99_stressed_im_inr"] > fac.buffer_inr
    d["flag_mar_exceeds_undrawn"] = d["mar_99_stressed_im_inr"] > d["undrawn_inr"]
    d["label"] = LABEL
    return d.reset_index(), lots, moves


# ------------------------------------------------------------------------------------------------ windows
@dataclass(frozen=True)
class Window:
    name: str
    start: str
    end: str
    rule: str


def crash_fortnight(inputs: LiquidityInputs) -> Window:
    w = inputs.windows[inputs.windows["event"] == CRASH_WINDOW_EVENT]
    if len(w) != 1:
        raise ValueError(f"{CRASH_WINDOW_EVENT} missing from adverse_event_windows.csv")
    r = w.iloc[0]
    return Window("CRASH_FORTNIGHT", str(r["start"]), str(r["end"]),
                  "CONTRACTS §7a.3: the 10-trading-day RETURN window (11 observations) with the most negative LME "
                  "cash return in the headline window (adverse_event_windows.csv E1_CRASH_FORTNIGHT)")


def margin_fortnight(daily: pd.DataFrame) -> Window:
    """The 10 consecutive margin-cash days (after a start observation) with the most negative net margin cash in the
    headline window — the same 11-observation convention as the crash fortnight, applied to cash instead of price.
    Reporting-only: drawn after the fact, an input to nothing."""
    w = daily[daily["in_window"]].reset_index(drop=True)
    roll = w["net_margin_cash_inr"].rolling(FORTNIGHT_RETURNS).sum()
    end_i = int(roll.idxmin())
    start_i = end_i - FORTNIGHT_RETURNS
    return Window("MARGIN_FORTNIGHT", str(w.at[start_i, "date"]), str(w.at[end_i, "date"]),
                  "the 10 trading days (11 observations) with the most negative summed net MCX margin cash "
                  "(VM + charges − IM change) in the headline window")


# ------------------------------------------------------------------------------------------------ fortnight stress
def fortnight_days(daily: pd.DataFrame, win: Window) -> list[str]:
    days = list(daily.set_index("date").loc[win.start:win.end].index)
    if len(days) != FORTNIGHT_RETURNS + 1:
        raise ValueError(f"{win.name}: expected {FORTNIGHT_RETURNS + 1} observations, got {len(days)}")
    return days


def remark_fortnight(inputs: LiquidityInputs, daily: pd.DataFrame, days: list[str], lme_stressed: np.ndarray
                     ) -> pd.DataFrame:
    """Re-mark every MCX line over `days` on an alternative LME cash path (FX, carry and positions held).

    The proxy settle is proportional to LME cash, so each line's settle on day k is scaled by r_k = L_s(k) / L_a(k).
    VM on a line held over the day becomes kg x (settle_k r_k − prev_settle r_{k−1}), applied as the actual VM plus
    the increment; an entry or roll-in keeps its actual VM (it fills at that day's price either way); IM becomes
    im x r_k at the base rate and im_15 % x r_k when the exchange re-strikes margin. Passing the ACTUAL path reproduces P3's margin exactly (a test asserts it).
    """
    d = daily.set_index("date")
    lme_a = d.loc[days, "lme_cash_usd_t"].to_numpy()
    ratio = lme_stressed / lme_a
    vm = inputs.vm[inputs.vm["date"].isin(days[1:])]
    s0 = days[0]
    phys_delta = float(inputs.book.at[s0, "lme_delta_physical_mt"]) if s0 in inputs.book.index else 0.0
    rows = []
    cum_extra_vm = 0.0
    for j, day in enumerate(days):
        if j == 0:
            vm_a = vm_s = 0.0
            im_a = im_s = im15_s = float(d.at[day, "mcx_im_inr"])
        else:
            lines = vm[vm["date"] == day]
            kg = lines["lots"] * lines["lot_mt"] * 1000.0
            held = lines["prev_settle_inr_kg"].notna()
            vm_a = float(lines["vm_inr"].sum())
            # stressed = actual + the re-mark increment, so the published settles' 4-dp rounding cannot leak in
            vm_s = vm_a + float((kg[held] * (lines.loc[held, "settle_inr_kg"] * (ratio[j] - 1.0)
                                             - lines.loc[held, "prev_settle_inr_kg"] * (ratio[j - 1] - 1.0))).sum())
            im_a = float(lines["im_required_inr"].sum())
            im_s = im_a * ratio[j]
            im15_s = float(lines[STRESS_IM_COLUMN].sum()) * ratio[j]
        cum_extra_vm += vm_s - vm_a
        rows.append({
            "obs": j, "date": day,
            "lme_cash_actual_usd_t": lme_a[j], "lme_cash_stressed_usd_t": float(lme_stressed[j]),
            "mcx_lots_net_open": float(d.at[day, "mcx_lots_net_open"]),
            "vm_actual_inr": vm_a, "vm_stressed_inr": vm_s,
            "im_actual_inr": im_a, "im_stressed_inr": im_s, "im_stressed_015_inr": im15_s,
            "extra_margin_cash_out_inr": -cum_extra_vm + (im_s - im_a),
            "extra_margin_cash_out_stressed_im_inr": -cum_extra_vm + (im15_s - im_a),
            "funding_need_actual_inr": float(d.at[day, "funding_need_total_inr"]),
            "headroom_actual_inr": float(d.at[day, "headroom_inr"]),
            "memo_physical_mtm_gain_inr": float(d.at[s0, "usdinr"]) * (float(lme_stressed[j]) - lme_a[j]) * phys_delta,
        })
    f = pd.DataFrame(rows)
    f.insert(f.columns.get_loc("im_actual_inr"), "cum_vm_actual_inr", f["vm_actual_inr"].cumsum())
    f.insert(f.columns.get_loc("im_actual_inr"), "cum_vm_stressed_inr", f["vm_stressed_inr"].cumsum())
    return f


def fortnight_stress(inputs: LiquidityInputs, daily: pd.DataFrame, moves: pd.DataFrame, win: Window,
                     fac: Facility) -> pd.DataFrame:
    """Re-run one fortnight with LME moving AGAINST the hedges by the 99 % h-day move known at its start close.

    Path: L_s(k) = L(start) x exp(±m x k / 10), k = 0..10 — the move spread evenly in log terms (≈ 2 % a day for a
    20 % move, inside MCX's 4-9 % daily price limits), re-marked by `remark_fortnight`. The commercial cash is held at
    what happened: the physical cargo's gain from the same move is published as a memo MTM (start-day physical delta,
    linear), because inside a fortnight it is not cash. Both directions are computed; the one that calls more cash
    (with IM re-struck at 15 %) is published.
    """
    days = fortnight_days(daily, win)
    s0 = days[0]
    lme0 = float(daily.set_index("date").at[s0, "lme_cash_usd_t"])
    k = np.arange(len(days))
    best: pd.DataFrame | None = None
    for direction, col, binding in (("LME_UP", "stress_move_up_logret", "stress_binding_up"),
                                    ("LME_DOWN", "stress_move_down_logret", "stress_binding_down")):
        m = float(moves.at[s0, col])
        f = remark_fortnight(inputs, daily, days, lme0 * np.exp(m * k / FORTNIGHT_RETURNS))
        meta = {"window": win.name, "window_start": win.start, "window_end": win.end, "stress_direction": direction,
                "stress_move_logret": m, "stress_binding_method": moves.at[s0, binding]}
        for i, (name, value) in enumerate(meta.items()):
            f.insert(i, name, value)
        if best is None or f["extra_margin_cash_out_stressed_im_inr"].max() > best[
                "extra_margin_cash_out_stressed_im_inr"].max():
            best = f
    assert best is not None
    b = best
    b["funding_need_stressed_inr"] = b["funding_need_actual_inr"] + b["extra_margin_cash_out_inr"]
    b["funding_need_stressed_im_inr"] = b["funding_need_actual_inr"] + b["extra_margin_cash_out_stressed_im_inr"]
    b["headroom_stressed_inr"] = b["headroom_actual_inr"] - b["extra_margin_cash_out_inr"]
    b["headroom_stressed_im_inr"] = b["headroom_actual_inr"] - b["extra_margin_cash_out_stressed_im_inr"]
    b["flag_buffer_breach_actual"] = b["headroom_actual_inr"] < 0
    b["flag_buffer_breach_stressed_im"] = b["headroom_stressed_im_inr"] < 0
    b["flag_fb_limit_breach_actual"] = b["funding_need_actual_inr"] > fac.fb_limit_inr
    b["flag_fb_limit_breach_stressed_im"] = b["funding_need_stressed_im_inr"] > fac.fb_limit_inr
    b["label"] = LABEL + " | STRESS — LME moved against the MCX hedges by the 99 % 10-day move; not a 2022 event"
    return b


# ------------------------------------------------------------------------------------------------ sizing + grid
def facility_sizing(inputs: LiquidityInputs, fac: Facility) -> pd.DataFrame:
    """Recompute each registered limit from its plan rule, so a reader can see it was not fitted to the book."""
    p = inputs.parity
    value_date = str(p["value_date"].iloc[0])
    rate = float(config.value("wc_rate_inr_pa", value_date))
    capital_years = ((p["finance_inr_t"] + p["igst_finance_inr_t"]) / rate).mean()
    fb_plan = fac.plan_throughput_mt_pa * capital_years
    lc_value_t = (p["cif_usd_t"] * p["usdinr"]).mean()
    lc_plan = fac.plan_throughput_mt_pa * lc_value_t * fac.plan_lc_tenor_days / 365.0
    up = lambda x: math.ceil(x / fac.rounding_inr) * fac.rounding_inr  # noqa: E731
    mcx_plan = float(inputs.market.loc[:value_date, "mcx_al_m1_inr_kg"].iloc[-1])
    months2_mt = fac.plan_throughput_mt_pa / 6.0
    im_frac = float(config.value("mcx_al_margin_used_frac"))
    rows = [
        ("plan_parity_week_end", fac.plan_week_end, "date", "liq_plan_parity_week_end"),
        ("plan_value_date", value_date, "date", "parity_weekly.csv value_date"),
        ("plan_wc_rate_pa", rate, "rate_pa", "wc_rate_inr_pa on the plan value date"),
        ("plan_throughput_mt_pa", fac.plan_throughput_mt_pa, "mt_per_year", "liq_plan_throughput_mt_pa"),
        ("plan_mean_landed_inr_t", float(p["landed_inr_t"].mean()), "inr_t", "mean over the six grade x lane cases"),
        ("plan_funded_inr_years_per_mt", capital_years, "inr_years_per_mt",
         "mean (finance_inr_t + igst_finance_inr_t) / wc_rate: rupee-years of funding one tonne of throughput needs"),
        ("plan_cash_cycle_days_equiv", capital_years / float(p["landed_inr_t"].mean()) * 365.0, "days",
         "the same expressed as days of mean landed cost (P1 finance_days_* plus the IGST credit lag)"),
        ("plan_avg_funded_balance_inr", fb_plan, "inr",
         "throughput x mean (finance_inr_t + igst_finance_inr_t) / wc_rate: average funded balance of the plan"),
        ("fb_limit_rule_inr", up(fb_plan), "inr", "plan balance rounded UP by liq_facility_rounding_inr"),
        ("fb_limit_registered_inr", fac.fb_limit_inr, "inr", "liq_fb_wc_limit_inr"),
        ("fb_limit_matches_rule", bool(up(fb_plan) == fac.fb_limit_inr), "bool", ""),
        ("plan_lc_value_inr_t", lc_value_t, "inr_t", "mean cif_usd_t x usdinr over the six cases"),
        ("plan_lc_tenor_days", fac.plan_lc_tenor_days, "days", "liq_plan_lc_tenor_days"),
        ("plan_avg_lc_outstanding_inr", lc_plan, "inr", "throughput x LC value per tonne x tenor / 365"),
        ("lc_limit_rule_inr", up(lc_plan), "inr", "plan LC outstanding rounded UP by liq_facility_rounding_inr"),
        ("lc_limit_registered_inr", fac.lc_limit_inr, "inr", "liq_nfb_lc_limit_inr"),
        ("lc_limit_matches_rule", bool(up(lc_plan) == fac.lc_limit_inr), "bool", ""),
        ("min_cash_buffer_inr", fac.buffer_inr, "inr", "liq_min_cash_buffer_frac_of_fb_limit x fund-based limit"),
        ("memo_plan_mcx_m1_inr_kg", mcx_plan, "inr_kg", "MCX M1 (PROXY) on the plan value date"),
        ("memo_im_on_two_months_plan_hedged_inr", months2_mt * 1000.0 * mcx_plan * im_frac, "inr",
         "two months of plan throughput hedged 1:1 at mcx_al_margin_used_frac: the buffer's anchor"),
    ]
    return pd.DataFrame(rows, columns=["metric", "value", "unit", "note"])


def breach_stats(need: pd.Series, dates: pd.Series, limit: float) -> dict:
    over = need > limit
    return {
        "days_over": int(over.sum()),
        "first_over": str(dates[over].iloc[0]) if over.any() else "",
        "last_over": str(dates[over].iloc[-1]) if over.any() else "",
        "worst_shortfall_inr": float((need - limit).clip(lower=0.0).max()),
    }


def limit_grid(daily: pd.DataFrame, fac: Facility, fb_limits: tuple[float, ...], lc_limits: tuple[float, ...]
               ) -> pd.DataFrame:
    """Breach days at other facility sizes (buffer kept at the registered fraction of each fund-based limit)."""
    rows = []
    need, lc, dates = daily["funding_need_total_inr"], daily["lc_outstanding_inr"], daily["date"]
    for L in sorted(set(fb_limits) | {fac.fb_limit_inr}):
        buf = fac.buffer_frac * L
        s_buf = breach_stats(need, dates, L - buf)
        s_lim = breach_stats(need, dates, L)
        rows.append({"facility": "FUND_BASED_WC", "limit_inr": L, "buffer_inr": buf,
                     "registered": L == fac.fb_limit_inr,
                     "days_buffer_breach": s_buf["days_over"], "first_buffer_breach": s_buf["first_over"],
                     "last_buffer_breach": s_buf["last_over"], "days_limit_breach": s_lim["days_over"],
                     "first_limit_breach": s_lim["first_over"], "last_limit_breach": s_lim["last_over"],
                     "worst_shortfall_vs_limit_inr": s_lim["worst_shortfall_inr"]})
    for L in sorted(set(lc_limits) | {fac.lc_limit_inr}):
        s_lim = breach_stats(lc, dates, L)
        rows.append({"facility": "NON_FUND_LC", "limit_inr": L, "buffer_inr": 0.0, "registered": L == fac.lc_limit_inr,
                     "days_buffer_breach": 0, "first_buffer_breach": "", "last_buffer_breach": "",
                     "days_limit_breach": s_lim["days_over"], "first_limit_breach": s_lim["first_over"],
                     "last_limit_breach": s_lim["last_over"],
                     "worst_shortfall_vs_limit_inr": s_lim["worst_shortfall_inr"]})
    peak_need = float(need.max())
    rows.append({"facility": "FUND_BASED_WC_MIN_NO_BREACH", "limit_inr": peak_need / (1.0 - fac.buffer_frac),
                 "buffer_inr": fac.buffer_frac * peak_need / (1.0 - fac.buffer_frac), "registered": False,
                 "days_buffer_breach": 0, "first_buffer_breach": "", "last_buffer_breach": "", "days_limit_breach": 0,
                 "first_limit_breach": "", "last_limit_breach": "", "worst_shortfall_vs_limit_inr": 0.0})
    rows.append({"facility": "NON_FUND_LC_MIN_NO_BREACH", "limit_inr": float(lc.max()), "buffer_inr": 0.0,
                 "registered": False, "days_buffer_breach": 0, "first_buffer_breach": "", "last_buffer_breach": "",
                 "days_limit_breach": 0, "first_limit_breach": "", "last_limit_breach": "",
                 "worst_shortfall_vs_limit_inr": 0.0})
    out = pd.DataFrame(rows)
    out["label"] = LABEL
    return out


# ------------------------------------------------------------------------------------------------ controls
def controls(inputs: LiquidityInputs, daily: pd.DataFrame) -> pd.DataFrame:
    """Everything in margin_liquidity.csv must tie to the P3 files it is read from."""
    d = daily.set_index("date")
    dates = d.index
    book = inputs.book.reindex(dates)
    cat_cols = [f"cash_{c}_cum_inr" for c in CASH_CATEGORIES]
    mcx = mcx_leg_cumulative(inputs.cashflows, dates)
    have = book["cash_balance_inr"].notna()
    checks = [
        ("cash_categories_sum_vs_book_cash_balance_max_abs",
         (d.loc[have, cat_cols].sum(axis=1) - book.loc[have, "cash_balance_inr"]).abs().max()),
        ("cash_mcx_category_vs_vm_table_cum_margin_cash_max_abs",
         (d["cash_mcx_margin_cum_inr"] - d["cum_margin_cash_inr"]).abs().max()),
        ("cashflow_vm_leg_vs_vm_table_cum_vm_max_abs",
         (mcx.get("MCX_VARIATION_MARGIN", 0.0) - d["cum_vm_inr"]).abs().max()),
        ("cashflow_im_leg_vs_vm_table_im_stock_max_abs",
         (mcx.get("MCX_INITIAL_MARGIN", 0.0) + d["mcx_im_inr"]).abs().max()),
        ("cashflow_charges_vs_vm_table_cum_txn_cost_max_abs",
         (mcx.get("MCX_TRANSACTION_COST", 0.0) + mcx.get("MCX_SLIPPAGE", 0.0) - d["cum_txn_cost_inr"]).abs().max()),
        ("vm_table_im_stock_vs_book_mcx_im_max_abs",
         (d.loc[have, "mcx_im_inr"] - book.loc[have, "mcx_im_inr"]).abs().max()),
        ("vm_table_net_margin_identity_max_abs",
         (d["vm_inr"] + d["txn_cost_inr"] - d["im_change_inr"] - d["net_margin_cash_inr"]).abs().max()),
        ("cum_margin_cash_equals_vm_plus_charges_minus_im_stock_max_abs",
         (d["cum_vm_inr"] + d["cum_txn_cost_inr"] - d["mcx_im_inr"] - d["cum_margin_cash_inr"]).abs().max()),
        ("funding_need_decomposition_max_abs",
         (d["commercial_funding_need_inr"] + d["margin_cash_deployed_inr"] + d["interest_accrued_inr"]
          + d["cash_balance_inr"] + d["funding_accrued_cum_inr"]).abs().max()),
        ("headroom_arithmetic_max_abs",
         (d["fb_limit_inr"] - d["min_cash_buffer_inr"] - d["funding_need_total_inr"] - d["headroom_inr"]).abs().max()),
        ("lots_net_open_vs_book_mcx_lots_open_max_abs",
         (d.loc[have, "mcx_lots_net_open"] - book.loc[have, "mcx_lots_open"]).abs().max()),
    ]
    out = pd.DataFrame(checks, columns=["check", "value"])
    out["value"] = out["value"].astype(float)
    out["tolerance"] = RECON_TOL_INR
    out["status"] = np.where(out["value"] <= out["tolerance"], "PASS", "FAIL")
    return out
