"""`MTM_Daily` — per trade-day leg valuations, and per-trade cumulative P&L assembled from them.

Grain: **mark date × trade × open leg**, on the marking grid declared in `desk.excel.sources` (month-end panel days,
every trade date, the adverse-event endpoints, `WINDOW_END`, `HORIZON_END`). Settled legs are not repeated here —
their mark is zero by definition and their cash is already on `Cashflows`.

What is a formula:

* **`fx_x_calc`** for every leg — `curves.fx_x`: the spot that actually fixed once a flow has settled, the spot of
  the day on its own settle day, and the covered-interest-parity forward to its **own** settle date before that.
  This is the single rule that makes a 100 % forward hedge exactly flat in buckets (e) and (g).
* **The unsold-cargo replacement mark** (design D5), end to end: `lme_3m × grade factor → CIF → goods at the
  one-month forward + BCD/SWS on the CBIC notified base + port/PSIC`, with **no finance** — the same arithmetic as
  `Parity`, minus the finance lines, which is exactly why the Checks sheet can tie it to Phase 1's
  `goods + bcd + sws + port` on every parity value date.
* **The FX-forward mark** — `sign × notional × (X(τ, value date) − dealt rate)`.
* **`mtm_inr_calc`** for every leg, and the per-trade cumulative P&L identity
  `cum P&L = realised cash P&L to date + funding accrued + Σ open-leg marks` (CONTRACTS §7.3), with the realised
  part a `SUMIFS` over the `Cashflows` ledger.

What is carried from Python, and `value_src` says which on every row:

* `PYTHON_LIFECYCLE` — the leg **amount** falls out of the ticket lifecycle rather than out of the market
  (quotational-period averages, survey outcomes and claim arithmetic, demurrage day counts, LC fee bases). The
  workbook still derives everything the market does to it: the FX conversion to its own settle date, and the
  aggregation into cumulative P&L.
* `PYTHON_MULTI_FLOW_LEG` — the leg carries more than one dated flow (an `LME_M1_AVG` purchase pays a provisional
  and a final invoice on different days; IGST is paid at the Bill of Entry and credited 45 days later), so the row's
  INR mark is a sum over flows at *different* FX rates and one rate cannot reproduce it. `n_settle_dates` comes
  from the published cash ledger, so the classification is structural, not fitted to the difference.

Funding is carried too: it is a day-by-day walk of the trade's own dated cash balance, which a flat sheet cannot
express without one row per calendar day per trade.
"""

from __future__ import annotations

import pandas as pd

from desk.excel import expr, sources
from desk.excel.layout import INPUT, KEY, PASTED, Column, Sheet, Table

SHEET = "MTM_Daily"

KEYS = ["mark_date", "trade_id", "leg_id", "leg_type", "instrument", "lot_id", "counterparty_id", "grade", "lane",
        "currency", "status", "pnl_class", "settle_date"]
INPUTS = ["qty_mt", "lots", "notional_usd", "one_month_days", "n_settle_dates", "fx_value_date",
          "fx_strike_inr"]
REP = ["rep_box", "rep_port_key", "rep_payload_scale", "rep_cfr_usd_t", "rep_cif_usd_t", "rep_goods_fx",
       "rep_goods_inr_t", "rep_av_inr_t", "rep_duty_inr_t", "rep_port_inr_t", "rep_igst_inr_t",
       "replacement_inr_t"]
CALC = ["value_src", "fx_x_calc", "diff_fx_rate", "amount_ccy_calc", "mtm_inr_calc", "diff_inr", "check"]
PY = ["mtm_ccy_py", "mtm_inr_py", "px_inr_t_py", "fx_rate_used_py"]

CUM_KEYS = ["mark_date", "trade_id"]
CUM_CALC = ["realised_pnl_cum_inr", "mtm_open_inr", "cum_pnl_calc_inr", "diff_inr", "check"]
CUM_PY = ["funding_cum_inr_py", "cum_pnl_inr_py"]


def write(wb, counts, data: sources.Data, mdt, cf):
    sh = Sheet(wb, SHEET, "MTM_Daily — leg valuations on the declared marking grid, and cumulative P&L per trade",
               counts,
               subtitle="Marking grid: month-end panel days + every trade date + the adverse-event endpoints + "
                        "WINDOW_END + HORIZON_END. Settled legs are omitted (their mark is zero); their cash is on "
                        "Cashflows. Green = carried from the Python lifecycle, see value_src.")

    marks = set(data.mark_dates)
    m = data.mtm
    live = m[(m["status"] != "settled") & (m["date"].dt.date.isin(marks))].copy()
    live = live.sort_values(["date", "trade_id", "leg_id"], kind="mergesort").reset_index(drop=True)
    gl = data.trade_book.set_index("trade_id")[["grade", "lane"]]
    fx_lines = _fx_lines(data)
    # A published mtm row is one LEG, and a leg can carry more than one dated flow (an M+1 purchase pays a
    # provisional and a final invoice on different days; IGST is paid and credited). Such a row's INR mark is a sum
    # over flows with different settle dates, so `mtm_ccy x one FX rate` cannot reproduce it. The count comes from
    # the published cash ledger, not from the difference it would explain.
    n_settles = data.cashflows.groupby(["trade_id", "leg_id"])["settle_date"].nunique().to_dict()

    cols = [Column(c, KEY, width=_w(c)) for c in KEYS]
    cols += [Column(c, INPUT, width=14) for c in INPUTS]
    cols += [Column(c, PASTED, width=16) for c in PY]
    cols += [Column(c, width=15) for c in REP + CALC]
    t = Table(sh, cols, sh.row + 1)

    for i, row in enumerate(live.itertuples(index=False)):
        R = lambda c: t.rowref(c, i)  # noqa: E731
        trade = str(row.trade_id)
        grade, lane = str(gl.loc[trade, "grade"]), str(gl.loc[trade, "lane"])
        mark = row.date
        hedge_id = str(row.leg_id).split(":", 1)[1] if ":" in str(row.leg_id) else ""
        fx = fx_lines.get(hedge_id) if str(row.leg_type) == "FX" else None
        r = {
            "mark_date": mark.date(), "trade_id": trade, "leg_id": str(row.leg_id),
            "leg_type": str(row.leg_type), "instrument": str(row.instrument), "lot_id": _s(row.lot_id),
            "counterparty_id": _s(row.counterparty_id), "grade": grade, "lane": lane,
            "currency": str(row.currency), "status": str(row.status), "pnl_class": str(row.pnl_class),
            "settle_date": _d(row.settle_date),
            "qty_mt": float(row.qty_mt), "lots": int(row.lots), "notional_usd": float(row.notional_usd),
            "one_month_days": int((pd.Timestamp(mark) + pd.DateOffset(months=1) - pd.Timestamp(mark)).days),
            "n_settle_dates": int(n_settles.get((trade, str(row.leg_id)), 0)),
            "mtm_ccy_py": float(row.mtm_ccy), "mtm_inr_py": float(row.mtm_inr),
            "px_inr_t_py": None if pd.isna(row.px_inr_t) else float(row.px_inr_t),
            "fx_rate_used_py": float(row.fx_rate_used) if pd.notna(row.fx_rate_used) else None,
            "fx_x_calc": "=" + _fx_x(mdt, R("mark_date"), R("settle_date"), R("currency")),
            "diff_fx_rate": f'=IF(OR({R("currency")}="INR",{R("n_settle_dates")}>1),"",'
                            f'{R("fx_x_calc")}-{R("fx_rate_used_py")})',
            "diff_inr": f'={R("mtm_inr_calc")}-{R("mtm_inr_py")}',
            "check": f'=IF(ABS({R("diff_inr")})<=tol_trade_inr,"PASS","FAIL")',
        }
        multi = int(n_settles.get((trade, str(row.leg_id)), 0)) > 1
        if str(row.leg_type) == "INVENTORY":
            r["value_src"] = "DERIVED_IN_WORKBOOK"
            r.update(_replacement(t, i, mdt, R))
            r["amount_ccy_calc"] = f'={R("qty_mt")}*{R("replacement_inr_t")}'
            r["mtm_inr_calc"] = f'={R("amount_ccy_calc")}'
        elif fx:
            # `notional_usd` on an mtm row is already signed (a SELL_USD line carries a negative notional), and the
            # forward is always valued to its own VALUE date — for a cancelled line that is later than the date the
            # cash settles, so the settlement is the forward from the cancel date, not the spot of that day.
            r["value_src"] = "DERIVED_IN_WORKBOOK"
            r["fx_value_date"] = fx["value_date"]
            r["fx_strike_inr"] = fx["strike_inr"]
            r["amount_ccy_calc"] = (f'={R("notional_usd")}'
                                    f'*({_fx_x(mdt, R("mark_date"), R("fx_value_date"), None)}'
                                    f'-{R("fx_strike_inr")})')
            r["mtm_inr_calc"] = f'={R("amount_ccy_calc")}'
        elif multi:
            r["value_src"] = "PYTHON_MULTI_FLOW_LEG"
            r["amount_ccy_calc"] = f'={R("mtm_ccy_py")}'
            r["mtm_inr_calc"] = f'={R("mtm_inr_py")}'
        else:
            r["value_src"] = "PYTHON_LIFECYCLE"
            r["amount_ccy_calc"] = f'={R("mtm_ccy_py")}'
            r["mtm_inr_calc"] = f'={R("amount_ccy_calc")}*IF({R("currency")}="INR",1,{R("fx_x_calc")})'
        t.write_row(i, r)
    t.n_rows = len(live)
    t.freeze("qty_mt")
    t.autofilter()

    cum = _cum_block(sh, wb, data, t, cf, first_row=t.first_row + t.n_rows + 3)
    sh.row = cum.first_row + cum.n_rows + 2
    return {"legs": t, "cum": cum}


# ------------------------------------------------------------------------------------------- replacement value
def _replacement(t: Table, i: int, mdt, R) -> dict:
    """Design D5 `R_{g,l}(M)` in ₹ per MT: goods + BCD + SWS + port/PSIC, NO finance, goods at the 1-month forward."""
    mark = R("mark_date")
    lme3m = expr.md(mdt, "lme_3m_usd_t", mark)
    spot = expr.md(mdt, "usdinr", mark)
    inr = expr.md(mdt, "inr_rate_3m_pa", mark)
    usd = expr.md(mdt, "usd_rate_3m_pa", mark)
    customs = expr.md(mdt, "customs_usdinr_import", mark)
    gf = (f'INDEX({mdt.abs_block("grade_factor_zorba", "grade_factor_tense")},'
          f'MATCH({mark},{mdt.abs("date")},0),'
          f'MATCH("grade_factor_"&{R("grade")},{mdt.header_abs("grade_factor_zorba", "grade_factor_tense")},0))')
    return {
        "rep_box": f'={expr.box_of(R("lane"))}',
        "rep_port_key": f'={expr.port_of(R("lane"))}',
        "rep_payload_scale": "=" + expr.param('"container_payload_mt_"&' + R("rep_box")) + "/"
                             + expr.param('"container_payload_mt_"&' + R("rep_box") + '&"_"&' + R("grade")),
        "rep_cfr_usd_t": f"={lme3m}*{gf}",
        "rep_cif_usd_t": f'={R("rep_cfr_usd_t")}*(1+insurance_rate*insured_value_uplift)',
        "rep_goods_fx": "=" + expr.fx_forward(spot, inr, usd, R("one_month_days")),
        "rep_goods_inr_t": f'={R("rep_cif_usd_t")}*{R("rep_goods_fx")}',
        "rep_av_inr_t": f'={R("rep_cif_usd_t")}*{customs}',
        "rep_duty_inr_t": f'={R("rep_av_inr_t")}*bcd_scrap_hs7602*(1+sws_rate_on_bcd)',
        "rep_port_inr_t": "=" + expr.param('"port_cf_charges_inr_t_"&' + R("rep_port_key"))
                          + f'*{R("rep_payload_scale")}'
                          + f'+IF({expr.param(expr.psic_key_of(R("lane")))},psic_cost_usd_per_box*{spot}/'
                          + expr.param('"container_payload_mt_20ft_"&' + R("grade")) + ",0)",
        "rep_igst_inr_t": f'=IF(igst_itc_available,0,({R("rep_av_inr_t")}+{R("rep_duty_inr_t")})'
                          f'*igst_rate_hs7602)',
        "replacement_inr_t": f'={R("rep_goods_inr_t")}+{R("rep_duty_inr_t")}+{R("rep_port_inr_t")}'
                             f'+{R("rep_igst_inr_t")}',
    }


def _fx_x(mdt, clock_ref: str, settle_ref: str, currency_ref: str | None) -> str:
    core = expr.fx_x(mdt, clock_ref, settle_ref)
    if currency_ref is None:
        return core
    return f'IF({currency_ref}="INR",1,{core})'


# ------------------------------------------------------------------------------------ per-trade cumulative P&L
def _cum_block(sh: Sheet, wb, data: sources.Data, legs: Table, cf, first_row: int) -> Table:
    sh.section_at(first_row - 2,
                  "Per trade × mark date — CONTRACTS §7.3: cumulative P&L = realised cash P&L + funding accrued "
                  "+ Σ open-leg marks")
    cols = [Column(c, KEY, width=13) for c in CUM_KEYS]
    cols += [Column(c, PASTED, width=18) for c in CUM_PY]
    cols += [Column(c, width=18) for c in CUM_CALC]
    t = Table(sh, cols, first_row)

    ledger = cf["ledger"]
    n_led = ledger.n_rows
    n_legs = legs.n_rows
    m = data.mtm
    funding = (m[m["leg_type"] == "FUNDING"].set_index(["date", "trade_id"])["realised_cum_inr"].to_dict())
    attr = data.attribution.set_index(["date", "trade_id"])["cum_pnl_inr"].to_dict()
    trades = sorted(data.trade_book["trade_id"])
    i = 0
    for mark in data.mark_dates:
        for trade in trades:
            R = lambda c: t.rowref(c, i)  # noqa: E731
            key = (pd.Timestamp(mark), trade)
            t.write_row(i, {
                "mark_date": mark, "trade_id": trade,
                "funding_cum_inr_py": float(funding.get(key, 0.0)),
                "cum_pnl_inr_py": float(attr.get(key, 0.0)),
                "realised_pnl_cum_inr":
                    f'=SUMIFS({ledger.abs("amount_inr_calc", n_led)},{ledger.abs("trade_id", n_led)},'
                    f'{R("trade_id")},{ledger.abs("pnl_class", n_led)},"PNL",'
                    f'{ledger.abs("settle_date", n_led)},"<="&{R("mark_date")})',
                "mtm_open_inr":
                    f'=SUMIFS({legs.abs("mtm_inr_calc", n_legs)},{legs.abs("trade_id", n_legs)},{R("trade_id")},'
                    f'{legs.abs("mark_date", n_legs)},{R("mark_date")},'
                    f'{legs.abs("pnl_class", n_legs)},"PNL")',
                "cum_pnl_calc_inr": f'={R("realised_pnl_cum_inr")}+{R("funding_cum_inr_py")}+{R("mtm_open_inr")}',
                "diff_inr": f'={R("cum_pnl_calc_inr")}-{R("cum_pnl_inr_py")}',
                "check": f'=IF(ABS({R("diff_inr")})<=tol_trade_inr,"PASS","FAIL")',
            })
            i += 1
    t.n_rows = i
    return t


def _fx_lines(data: sources.Data) -> dict[str, dict]:
    h = data.hedges
    fx = h[h["instrument"].astype(str).str.upper().str.contains("FORWARD")]
    return {str(r.hedge_id): {"value_date": pd.Timestamp(r.value_date).date(),
                              "strike_inr": float(r.rate_inr)} for r in fx.itertuples(index=False)}


def _d(v):
    return pd.Timestamp(v).date() if pd.notna(v) else None


def _s(v):
    return "" if (v is None or (isinstance(v, float) and pd.isna(v))) else str(v)


def _w(name: str) -> float:
    if name in ("leg_id", "leg_type", "counterparty_id", "instrument"):
        return 20
    return 13
