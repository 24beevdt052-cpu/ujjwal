"""`Market_Daily` and `Market_Weekly` — the panel values the workbook prices off, and the dated parameters resolved.

`Market_Daily` is `data/processed/market_daily.csv` for 2022-01-03 → `HORIZON_END`, one row per LME trading day, with
its provenance labels carried through. Every value is a blue input: change a price here and the parity, the marks and
the P&L all move. Four derived columns are formulas, not pastes:

* `mcx_m1_month` / `mcx_m2_month` — the contract month (`YYYYMM`) each MCX slot holds on that day;
* the dated register parameters (`wc_rate_inr_pa`, `customs_usdinr_import`, the three grade factors and the
  point-in-time mix) resolved on the day, step or linear exactly as the register declares;
* `mcx_theo_m1_inr_kg` and `mcx_basis_m1_inr_kg` — the duty-paid import-parity price the Phase 3 engine carries, and
  the panel's residual against it. On a `PROXY_IMPORT_PARITY` day that basis is zero **by construction**; the Checks
  sheet asserts it, which is what stops a proxy series manufacturing a fake cross-exchange basis (design D4).

`Market_Weekly` is the CONTRACTS §3 weekly view: one W-FRI row valued on the week's last panel day, every cell an
`INDEX/MATCH` into `Market_Daily`. Nothing is pasted.
"""

from __future__ import annotations

import pandas as pd

from desk import config
from desk.excel import expr, sources, style
from desk.excel.layout import INPUT, KEY, Column, Sheet
from desk.paths import PROCESSED_DIR

DAILY = "Market_Daily"
WEEKLY = "Market_Weekly"

PANEL_INPUTS = ["lme_cash_usd_t", "lme_3m_usd_t", "lme_cash_3m_spread_usd_t", "lme_stock_mt", "usdinr",
                "usdinr_fwd_1m", "usdinr_fwd_3m", "inr_rate_3m_pa", "usd_rate_3m_pa", "rbi_repo_pa",
                "mcx_al_spot_inr_kg", "mcx_al_m1_inr_kg", "mcx_al_m2_inr_kg",
                "freight_jea_nsa_usd_t", "freight_usec_mun_usd_t"]
PANEL_LABELS = ["mcx_src", "usdinr_src", "freight_src", "usdinr_filled", "freight_filled"]

WEEKLY_FROM_DAILY = ["lme_cash_usd_t", "lme_3m_usd_t", "lme_cash_3m_spread_usd_t", "usdinr", "usdinr_fwd_1m",
                     "inr_rate_3m_pa", "usd_rate_3m_pa", "mcx_al_spot_inr_kg", "mcx_al_m1_inr_kg",
                     "mcx_al_m2_inr_kg", "freight_jea_nsa_usd_t", "freight_usec_mun_usd_t",
                     "wc_rate_inr_pa", "customs_usdinr_import", "grade_factor_zorba", "grade_factor_taint_tabor",
                     "grade_factor_tense", "grade_factor_mix_pit"]


def write_daily(wb, counts, data: sources.Data, paths: dict):
    sh = Sheet(wb, DAILY, "Market_Daily — LME trading-day panel (data/processed/market_daily.csv)", counts,
               subtitle="DIRECT: LME cash / 3M / spread / stock (Westmetall).  PROXY: usdinr (ECB cross), the 3-month "
                        "rates, the MCX columns (duty-paid import parity).  ASSUMPTION: freight levels, "
                        "wc_rate_inr_pa.  The row directly above the headers carries each column's flag, read from "
                        "data/processed/series_provenance.csv and the register.")
    cols = [Column("date", KEY, width=12)]
    cols += [Column(c, INPUT) for c in PANEL_INPUTS]
    cols += [Column("mcx_m1_expiry", INPUT, width=13), Column("mcx_m2_expiry", INPUT, width=13)]
    cols += [Column("mcx_m1_month"), Column("mcx_m2_month")]
    cols += [Column(c) for c in ("wc_rate_inr_pa", "customs_usdinr_import", "customs_fx_src",
                                 "grade_factor_zorba", "grade_factor_taint_tabor", "grade_factor_tense",
                                 "grade_factor_mix_pit", "mcx_theo_m1_inr_kg", "mcx_basis_m1_inr_kg")]
    cols += [Column(c, KEY, width=18) for c in PANEL_LABELS]
    t = sh.table(cols)
    _flag_row(sh, t, cols)

    p = data.panel
    for i, row in enumerate(p.itertuples(index=False)):
        r = {"date": row.date.date()}
        for c in PANEL_INPUTS:
            r[c] = float(getattr(row, c))
        for c in ("mcx_m1_expiry", "mcx_m2_expiry"):
            v = getattr(row, c)
            r[c] = pd.Timestamp(v).date() if pd.notna(v) else None
        for c in PANEL_LABELS:
            v = getattr(row, c)
            r[c] = bool(v) if isinstance(v, (bool,)) else str(v)
        d = t.rowref("date", i)
        r["mcx_m1_month"] = f"=YEAR({t.rowref('mcx_m1_expiry', i)})*100+MONTH({t.rowref('mcx_m1_expiry', i)})"
        r["mcx_m2_month"] = f"=YEAR({t.rowref('mcx_m2_expiry', i)})*100+MONTH({t.rowref('mcx_m2_expiry', i)})"
        r["wc_rate_inr_pa"] = expr.path_at("wc_rate_inr_pa", d, paths)
        r["customs_usdinr_import"] = expr.customs_fx_at(d, t.rowref("usdinr", i), paths)
        r["customs_fx_src"] = expr.customs_fx_src(d)
        for g in ("zorba", "taint_tabor", "tense"):
            r[f"grade_factor_{g}"] = expr.path_at(f"grade_factor_{g}", d, paths)
        r["grade_factor_mix_pit"] = expr.path_at("grade_factor_mix_pit", d, paths)
        spot = (f"({t.rowref('lme_cash_usd_t', i)}*{t.rowref('usdinr', i)}/kg_per_mt"
                f"*(1+bcd_primary_al_hs7601*(1+sws_rate_on_bcd))+mcx_domestic_premium_inr_kg)")
        dte = f"MAX(0,{t.rowref('mcx_m1_expiry', i)}-{d})"
        r["mcx_theo_m1_inr_kg"] = f"={spot}*(1+{t.rowref('inr_rate_3m_pa', i)}*{dte}/day_count_inr)"
        r["mcx_basis_m1_inr_kg"] = f"={t.rowref('mcx_al_m1_inr_kg', i)}-{t.rowref('mcx_theo_m1_inr_kg', i)}"
        t.write_row(i, r)
    t.freeze("lme_cash_usd_t")
    t.autofilter()
    sh.after(t)
    return t


def _flag_row(sh: Sheet, t, cols) -> None:
    """One row above the header carrying each column's CONTRACTS §1.2 flag (data/processed/series_provenance.csv).

    Derived columns show the flag of the register key they resolve, and the two MCX parity columns show PROXY
    because the panel MCX series is import parity, not an observed settle.
    """
    prov = pd.read_csv(PROCESSED_DIR / "series_provenance.csv").set_index("column")["flag"].to_dict()
    derived = {"mcx_m1_month": "—", "mcx_m2_month": "—", "customs_fx_src": "—",
               "wc_rate_inr_pa": config.get("wc_rate_inr_pa").flag,
               "customs_usdinr_import": config.get("customs_usdinr_import").flag,
               "grade_factor_zorba": config.get("grade_factor_zorba").flag,
               "grade_factor_taint_tabor": config.get("grade_factor_taint_tabor").flag,
               "grade_factor_tense": config.get("grade_factor_tense").flag,
               "grade_factor_mix_pit": config.get("grade_factor_mix_pit").flag,
               "mcx_theo_m1_inr_kg": "PROXY", "mcx_basis_m1_inr_kg": "PROXY"}
    for c in cols:
        flag = derived.get(c.name, prov.get(c.name, ""))
        if flag:
            sh.put(t.header_row - 1, t.col_index(c.name), flag, kind=KEY, fmt=style.FMT["text"])


def write_weekly(wb, counts, data: sources.Data, mdt):
    sh = Sheet(wb, WEEKLY, "Market_Weekly — CONTRACTS §3 weekly view (W-FRI, valued on the week's last panel day)",
               counts,
               subtitle="Every cell is an INDEX/MATCH into Market_Daily on the week's value_date. Nothing is "
                        "pasted, and each column carries the provenance flag of the Market_Daily column it reads.")
    cols = [Column("week_end", KEY, width=12), Column("value_date", KEY, width=12),
            Column("in_window", KEY, width=10)]
    cols += [Column(c) for c in WEEKLY_FROM_DAILY]
    cols += [Column("customs_fx_src", width=18)]
    t = sh.table(cols)
    w = data.weekly
    for i, row in enumerate(w.itertuples(index=False)):
        vd = t.rowref("value_date", i)
        r = {"week_end": row.week_end.date(), "value_date": row.value_date.date(), "in_window": bool(row.in_window)}
        for c in WEEKLY_FROM_DAILY:
            r[c] = "=" + expr.md(mdt, c, vd)
        r["customs_fx_src"] = "=" + expr.md(mdt, "customs_fx_src", vd)
        t.write_row(i, r)
    t.freeze("lme_cash_usd_t")
    sh.after(t)
    return t
