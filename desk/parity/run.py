"""Phase 1 stage: import parity model, sensitivities, quality check, term structure, anchor study, charts, methods doc.

    DESK_OFFLINE=1 .venv/bin/python -c "import desk.parity.run as m; m.main()"

Reads only Phase 0 files (data/processed panel, config/params register, the data/interim MCX mirror and ADC12
evidence used as labelled PROXY evidence) and writes outputs/tables/parity_*.csv, term_structure_*.csv,
outputs/charts/p1_*.png and docs/10_parity_model.md. Deterministic: no clocks, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from desk import SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.parity import charts, model, quality, sensitivity, term_structure
from desk.paths import DOCS_DIR, PROCESSED_DIR, TABLES_DIR, ensure_dirs

DOC_PATH = DOCS_DIR / "10_parity_model.md"

ROUND_RULES = [  # (suffix, decimals) — first match wins; applied only when writing CSVs
    ("_1000mt_inr", 0), ("_1000mt_usd", 0), ("_inr_t", 2), ("_usd_t", 4), ("_inr_kg", 4), ("_mt", 4),
    ("_frac", 6), ("_pa", 8), ("_pct", 2),
]


@dataclass
class Results:
    panel: pd.DataFrame
    market: pd.DataFrame
    inputs: pd.DataFrame
    parity: pd.DataFrame
    cases: list
    cases_long: pd.DataFrame
    summary: pd.DataFrame
    refs: list
    grid_lme_fx: pd.DataFrame
    grid_freight_duty: pd.DataFrame
    quality: pd.DataFrame
    ts_weekly: pd.DataFrame
    ts_rolls: pd.DataFrame
    correlation: pd.DataFrame


def build() -> Results:
    panel = model.load_panel()
    market = model.weekly_market(panel)
    inputs = model.build_inputs(market)
    parity = model.build_parity_weekly(inputs)
    mirror = sensitivity.load_mirror()
    cases = sensitivity.build_cases(market, panel, mirror)
    cases_long = sensitivity.sensitivity_cases_table(inputs, cases)
    summary = sensitivity.sensitivity_summary(cases_long, parity)
    refs = sensitivity.reference_cases(parity)
    return Results(
        panel=panel, market=market, inputs=inputs, parity=parity, cases=cases, cases_long=cases_long,
        summary=summary, refs=refs,
        grid_lme_fx=sensitivity.lme_fx_grid(inputs, refs),
        grid_freight_duty=sensitivity.freight_duty_grid(inputs, refs),
        quality=quality.scenario_table(refs[0].week_end, refs[0].lane, inputs),
        ts_weekly=term_structure.weekly_table(panel),
        ts_rolls=term_structure.roll_table(panel, mirror),
        correlation=sensitivity.anchor_correlation(panel, mirror),
    )


def _rounded(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if not pd.api.types.is_float_dtype(out[col]):
            continue
        dec = next((d for suffix, d in ROUND_RULES if col.endswith(suffix)), 4 if "usdinr" in col else 6)
        out[col] = out[col].round(dec)
    return out


def tables(r: Results) -> dict[str, pd.DataFrame]:
    refs = pd.DataFrame([{"ref_case": x.ref, "week_end": x.week_end, "grade": x.grade, "lane": x.lane,
                          "rule": x.rule} for x in r.refs])
    return {
        "parity_weekly.csv": r.parity,
        "parity_sensitivity_cases.csv": r.cases_long,
        "parity_sensitivity_summary.csv": r.summary,
        "parity_reference_cases.csv": refs,
        "parity_sensitivity_lme_fx.csv": r.grid_lme_fx,
        "parity_sensitivity_lme_fx_wide.csv": sensitivity.lme_fx_wide(r.grid_lme_fx),
        "parity_sensitivity_freight_duty.csv": r.grid_freight_duty,
        "parity_sensitivity_freight_duty_wide.csv": sensitivity.freight_duty_wide(r.grid_freight_duty),
        "parity_quality_scenarios.csv": r.quality,
        "parity_anchor_correlation.csv": r.correlation,
        "term_structure_weekly.csv": r.ts_weekly,
        "term_structure_roll_monthly.csv": r.ts_rolls,
    }


def csv_text(df: pd.DataFrame) -> str:
    return _rounded(df).to_csv(index=False, lineterminator="\n", date_format="%Y-%m-%d")


def write_tables(r: Results) -> dict[str, str]:
    written = {}
    for name, df in tables(r).items():
        path = TABLES_DIR / name
        path.write_text(csv_text(df), encoding="utf-8")
        written[name] = str(path)
    return written


def make_charts(r: Results) -> list[str]:
    ref = r.refs[0]
    row = model.parity_row(ref.week_end, ref.grade, ref.lane, inputs=r.inputs)
    label = f"{pd.Timestamp(ref.week_end).date()} {ref.grade} {ref.lane}"
    return [
        charts.net_arb_weekly(r.parity),
        charts.window_heatmap(r.parity),
        charts.landed_cost_waterfall(row, label),
        charts.sensitivity_lme_fx(r.grid_lme_fx),
        charts.sensitivity_freight_duty(r.grid_freight_duty),
        charts.sensitivity_band(r.cases_long),
        charts.term_structure(r.ts_weekly, r.ts_rolls),
    ]


def main() -> None:
    ensure_dirs()
    r = build()
    write_tables(r)
    make_charts(r)
    DOC_PATH.write_text(render_doc(r), encoding="utf-8")


# ==================================================================================================================
# docs/10_parity_model.md — rendered from the same frames the CSVs are written from, so every number matches them
# ==================================================================================================================
FLAG_RANK = {"DIRECT": 0, "PROXY": 1, "ASSUMPTION": 2}
PANEL_FLAG_COLUMNS = ["lme_3m_usd_t", "lme_cash_usd_t", "usdinr", "usdinr_fwd_1m", "mcx_al_m1_inr_kg",
                      "mcx_al_m2_inr_kg", "mcx_al_spot_inr_kg", "freight_jea_nsa_usd_t", "freight_usec_mun_usd_t"]


def _md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def _inr(x: float, dec: int = 0) -> str:
    txt = f"{abs(x):,.{dec}f}"
    return ("−₹" if x < 0 and float(txt.replace(",", "")) != 0 else "₹") + txt


def _num(x: float, dec: int = 2) -> str:
    txt = f"{x:,.{dec}f}"
    return txt.replace("-", "−") if float(txt.replace(",", "")) != 0 else txt.lstrip("-")


def _mn(x: float, dec: int = 2) -> str:
    return _num(x / 1e6, dec)


def _d(ts) -> str:
    return pd.Timestamp(ts).strftime("%d-%b-%Y")


def _dd(ts) -> str:
    return pd.Timestamp(ts).strftime("%d-%b")


def _ranges(weeks) -> str:
    """Compress sorted week_end dates into 'dd-Mon–dd-Mon (n)' runs of consecutive weeks."""
    weeks = sorted(pd.Timestamp(w) for w in weeks)
    if not weeks:
        return "none"
    runs, start, prev = [], weeks[0], weeks[0]
    for w in weeks[1:]:
        if (w - prev).days != model.DAYS_PER_WEEK:
            runs.append((start, prev))
            start = w
        prev = w
    runs.append((start, prev))
    parts = []
    for a, b in runs:
        n = (b - a).days // model.DAYS_PER_WEEK + 1
        parts.append(_dd(a) if a == b else f"{_dd(a)}–{_dd(b)} ({n})")
    return ", ".join(parts)


def _panel_flags() -> dict[str, str]:
    prov = pd.read_csv(PROCESSED_DIR / "series_provenance.csv").set_index("column")["flag"]
    return {c: str(prov[c]) for c in PANEL_FLAG_COLUMNS}


def _flag(key: str, pflags: dict[str, str]) -> str:
    return pflags[key] if key in pflags else config.get(key).flag


def _weakest(keys: list[str], pflags: dict[str, str]) -> str:
    return max((_flag(k, pflags) for k in keys), key=FLAG_RANK.get)


FORMULAS = [  # (line item, formula, unit, new input keys, upstream line items); <g> grade, <box> 20ft|40ft
    ("cfr_usd_t", "lme_3m_usd_t × grade_factor_<g>(w)", "USD/MT", ["lme_3m_usd_t", "grade_factor_zorba"], []),
    ("payload_scale", "container_payload_mt_<box> ÷ container_payload_mt_<box>_<g>", "frac",
     ["container_payload_mt_20ft", "container_payload_mt_20ft_zorba"], []),
    ("freight_usd_t", "freight_<lane>_usd_t × payload_scale", "USD/MT", ["freight_jea_nsa_usd_t"], ["payload_scale"]),
    ("fob_usd_t", "cfr − freight (memo: origin netback)", "USD/MT", [], ["cfr_usd_t", "freight_usd_t"]),
    ("insurance_usd_t", "insurance_rate × insured_value_uplift × cfr", "USD/MT",
     ["insurance_rate", "insured_value_uplift"], ["cfr_usd_t"]),
    ("cif_usd_t", "cfr + insurance", "USD/MT", [], ["cfr_usd_t", "insurance_usd_t"]),
    ("av_customs_inr_t", "cif × customs_usdinr_import(w) — duty base only", "INR/MT", ["customs_usdinr_import"],
     ["cif_usd_t"]),
    ("goods_inr_t", "cif × usdinr_fwd_1m (parity_goods_fx_basis)", "INR/MT",
     ["usdinr_fwd_1m", "parity_goods_fx_basis"], ["cif_usd_t"]),
    ("bcd_inr_t", "av × bcd_scrap_hs7602", "INR/MT", ["bcd_scrap_hs7602"], ["av_customs_inr_t"]),
    ("sws_inr_t", "bcd × sws_rate_on_bcd", "INR/MT", ["sws_rate_on_bcd"], ["bcd_inr_t"]),
    ("igst_inr_t", "(av + bcd + sws) × igst_rate_hs7602", "INR/MT", ["igst_rate_hs7602"],
     ["av_customs_inr_t", "bcd_inr_t", "sws_inr_t"]),
    ("port_inr_t", "port_cf_charges_inr_t_<nsa/mun> × payload_scale + [JEA_NSA] psic_cost_usd_per_box × usdinr ÷ "
     "container_payload_mt_20ft_<g>", "INR/MT", ["port_cf_charges_inr_t_nsa", "psic_cost_usd_per_box", "usdinr",
                                                 "psic_required_uae_origin"], ["payload_scale"]),
    ("finance_inr_t", "(goods + bcd + sws) × finance_days_<lane> ÷ 365 × wc_rate_inr_pa(w)", "INR/MT",
     ["finance_days_jea_nsa", "wc_rate_inr_pa"], ["goods_inr_t", "bcd_inr_t", "sws_inr_t"]),
    ("igst_finance_inr_t", "igst × igst_credit_lag_days ÷ 365 × wc_rate_inr_pa(w)", "INR/MT",
     ["igst_credit_lag_days", "wc_rate_inr_pa"], ["igst_inr_t"]),
    ("landed_inr_t", "goods + bcd + sws + port + finance + igst_finance [+ igst only if igst_itc_available is false]",
     "INR/MT", ["igst_itc_available"], ["goods_inr_t", "bcd_inr_t", "sws_inr_t", "port_inr_t", "finance_inr_t",
                                        "igst_finance_inr_t"]),
    ("recovery_frac", "(1 − moisture_frac_<g>) × (1 − contamination_frac_<g>) × metal_yield_frac_<g>", "frac",
     ["moisture_frac_zorba", "contamination_frac_zorba", "metal_yield_frac_zorba"], []),
    ("anchor_inr_t", "mcx_al_<m1 JEA_NSA, m2 USEC_MUN>_inr_kg × 1000 + domestic_anchor_premium_inr_t", "INR/MT",
     ["mcx_al_m1_inr_kg", "domestic_anchor_premium_inr_t"], []),
    ("byproduct_inr_t", "(1 − moisture) × heavies_frac_<g> × heavies_net_value_frac_of_lme_al × lme_3m × usdinr",
     "INR/MT", ["moisture_frac_zorba", "heavies_frac_zorba", "heavies_net_value_frac_of_lme_al", "lme_3m_usd_t",
                "usdinr"], []),
    ("conversion_inr_t", "conversion_cost_inr_t (per t ingot) × recovery", "INR/MT", ["conversion_cost_inr_t"],
     ["recovery_frac"]),
    ("net_arb_inr_t", "anchor × recovery + byproduct − landed − conversion", "INR/MT", [],
     ["anchor_inr_t", "recovery_frac", "byproduct_inr_t", "landed_inr_t", "conversion_inr_t"]),
    ("window_open", "net_arb_inr_t > margin_threshold_inr_t", "bool", ["margin_threshold_inr_t"], ["net_arb_inr_t"]),
]


def _doc_intro(r: Results) -> list[str]:
    return [
        "# Phase 1 — Import parity model (Component 1, MASTER_SPEC Table 3 rows 1.1–1.7)", "",
        f"**{SIM_LABEL}.** Every counterparty, trade and SPA here is simulated; market series are labelled DIRECT / "
        "PROXY / ASSUMPTION exactly as in the Phase 0 register.", "",
        "_Rendered by `desk.parity.run` from the same data frames it writes to `outputs/tables/` — do not hand-edit; "
        "re-run `DESK_OFFLINE=1 .venv/bin/python -c \"import desk.parity.run as m; m.main()\"`._", "",
        "## 1. Purpose", "",
        "Each Friday the desk asks one question per grade × lane: *if I buy containerised aluminium scrap CFR India "
        "today, clear it, and sell it as melt feed to a (SIM) secondary smelter, does the rupee margin per tonne of "
        "scrap clear the hurdle?* The model answers with CONTRACTS §5 line by line (LME 3M × grade factor → CIF → "
        "duties → port and finance → landed cost, against a domestic secondary-ingot anchor × metal recovery, plus the "
        "Zorba heavies credit, minus conversion). Because the base flag is only as good as its weakest input, the "
        "answer that Component 2 may trade on is the ex-ante §5a rule: open under the base case, under the "
        "point-in-time grade mix, and with conversion one grid step above base.", "",
        "Grades: Zorba 95/5, Taint/Tabor (ISRI-clean), Tense (ISRI-clean). Lanes: **JEA_NSA** Jebel Ali → Nhava Sheva "
        "(20ft, anchor MCX M1) and **USEC_MUN** US East Coast → Mundra (40ft, anchor MCX M2).", "",
        "## 2. Outputs", "",
        _md_table(["File", "Grain", "Content"], [
            ["`outputs/tables/parity_weekly.csv`", "week_end × grade × lane (43 × 3 × 2)",
             "key inputs, every §5 line item, `window_open`, §5a flags `open_base`, `open_pit_mix`, `open_conv18k`, "
             "`trade_eligible`, their net arbs, USD memo"],
            ["`parity_sensitivity_cases.csv` / `_summary.csv`", "case × week × grade × lane / case × grade × lane",
             "the §5 required band (+ informational cases); open-week counts and flips vs base, in-window"],
            ["`parity_reference_cases.csv`", "2 rows", "declared Table 1.5 reference cases and their selection rules"],
            ["`parity_sensitivity_lme_fx.csv` (+`_wide`)", "ref × LME shock × USD/INR",
             "Table 1.5(a) P&L impact on 1,000 MT"],
            ["`parity_sensitivity_freight_duty.csv` (+`_wide`)", "ref × terms × freight shock × BCD",
             "Table 1.5(b) P&L impact on 1,000 MT (FOB and CFR terms)"],
            ["`parity_quality_scenarios.csv`", "grade × moisture × contamination × yield",
             "Table 1.6 settlement, recovery, landed per t recovered metal, net-arb impact"],
            ["`parity_anchor_correlation.csv`", "sample × pair × metric", "Table 1.3 anchor study"],
            ["`term_structure_weekly.csv`, `term_structure_roll_monthly.csv`", "week / MCX contract month",
             "Table 1.7 Cash–3M, M+1 pricing basis, roll yield"],
            ["`outputs/charts/p1_*.png`", "7 charts", "net arb, eligibility heatmap, waterfall, grids, band, term "
                                                     "structure"],
        ]), "",
        "Helpers for later phases (`desk.parity.model`): `load_parity()`, `eligible_on(trade_date, grade, lane)` "
        "(latest `week_end ≤ trade_date`; returns `(trade_eligible, week_end, row)`), `parity_row(week_end, grade, "
        "lane, overrides)`, `market_shock_overrides(...)`; `desk.parity.quality.settle_weight_and_penalty(...)`.", "",
    ]


def _doc_formulas(r: Results, pflags: dict[str, str]) -> list[str]:
    rows, value_flag = [], {}
    for item, formula, unit, keys, deps in FORMULAS:
        own = sorted({_flag(k, pflags) for k in keys}, key=FLAG_RANK.get)
        value_flag[item] = max(own + [value_flag[d] for d in deps], key=FLAG_RANK.get)
        rows.append([f"`{item}`", formula, unit, " / ".join(own) if own else "—", f"**{value_flag[item]}**"])
    win = r.parity[r.parity["in_window"]]
    fx_effect = win["goods_inr_t"] * (1 - win["usdinr"] / win["usdinr_goods"])
    fb = r.parity.loc[r.parity["customs_fx_src"] == "MARKUP_FALLBACK", "week_end"].unique()
    conv_step = model.conversion_step_above_base()
    return [
        "## 3. Formula table (CONTRACTS §5 — canonical keys, per MT of scrap)", "",
        "Flags: *new inputs* = flags of the panel columns (`data/processed/series_provenance.csv`) and register keys "
        "(`config/params/*.yaml`) that the line introduces; *value* = the weakest of those and of every upstream line "
        "item. For grade/lane-specific keys the Zorba / JEA_NSA key is checked; the other grades and lanes carry the "
        "same flags.",
        "", _md_table(["Line item", "Formula", "Unit", "New inputs", "Value flag"], rows), "",
        "## 4. Choices Phase 1 had to make (and why)", "",
        f"1. **Goods paid at the 1-month forward, not spot** (`parity_goods_fx_basis = usdinr_fwd_1m`, ASSUMPTION). A "
        "sight LC is paid ~7 days after the B/L, which falls inside the 15-day shipment window after the decision, so "
        "the dollar payment is ~1 month out on both lanes; the domestic anchor is itself a forward (the MCX contract "
        "matched to the sale date). Valuing both legs at prices lockable on the decision day avoids booking the "
        "forward premium as margin. In the window this adds "
        f"{_inr(fx_effect.min())}–{_inr(fx_effect.max())} per MT to landed cost (mean {_inr(fx_effect.mean())}); "
        "`finance_inr_t` then covers LC payment → buyer receipt only. Spot is case `goods_fx_spot`.",
        f"2. **Customs FX coverage.** `customs_usdinr_import` is used from its first notification to "
        f"`customs_fx_notification_validity_days` ({config.value('customs_fx_notification_validity_days')}) after the "
        f"last one; outside that the register's `customs_fx_markup_frac` fallback applies (weeks ending "
        f"{_ranges(fb)}; none in the window). Column `customs_fx_src` labels each row.",
        f"3. **Weeks.** W-FRI week_ends {_d(model.FIRST_WEEK_END)} → {_d(model.LAST_WEEK_END)}, each valued on its last "
        "panel day; every dated parameter path is read on that value date. `in_window` = the week (Sat–Fri) overlaps "
        f"{WINDOW_START}…{WINDOW_END}: 27 weeks, 04-Mar-2022 → 02-Sep-2022 (the last one is valued on 2 Sep because "
        "its Monday–Wednesday fall in August).",
        f"4. **§5a flags** are three separate one-change cases combined with AND: `open_base`; `open_pit_mix` (grade "
        f"factor = `grade_factor_mix_pit` + the registered differential); `open_conv18k` (conversion = the first value "
        f"of `conversion_cost_sensitivity_inr_t_ingot` above base = {_inr(conv_step)}/t ingot; the code raises if the "
        "register ever makes that anything other than the 18,000 the contract named). Case 3 can only close windows, so "
        "`trade_eligible = open_pit_mix ∧ open_conv18k` in practice.",
        "5. **PSIC** applies where the register says the origin/port pair needs one (`psic_required_uae_origin` for "
        "JEA_NSA = true; `psic_required_safe_origin_designated_port` for USEC_MUN = false).",
        "6. **Overrides.** Any sensitivity swaps an input column or a canonical register key (a scalar, a weekly series "
        "or a function of the *un-overridden* inputs) and re-runs the same `compute`; the base frame is never mutated "
        "(tested).", "",
    ]


def _doc_worked_example(r: Results, pflags: dict[str, str]) -> list[str]:
    ref = r.refs[0]
    par = _rounded(r.parity)
    row = par[(par["week_end"] == ref.week_end) & (par["grade"] == ref.grade) & (par["lane"] == ref.lane)].iloc[0]
    ins = r.inputs[(r.inputs["week_end"] == ref.week_end) & (r.inputs["grade"] == ref.grade)
                   & (r.inputs["lane"] == ref.lane)].iloc[0]
    g, spec = ref.grade, model.LANE_SPECS[ref.lane]
    raw = r.panel.set_index("date").loc[row["value_date"]]
    k = lambda name: config.get(name)  # noqa: E731
    inputs_rows = [
        ["value date", _d(row["value_date"]), "last panel day of the week", "—"],
        ["`lme_3m_usd_t`", _num(raw["lme_3m_usd_t"]), "Westmetall LME official 3M", pflags["lme_3m_usd_t"]],
        ["`usdinr` (spot)", _num(raw["usdinr"], 4), "ECB EUR/INR ÷ EUR/USD", pflags["usdinr"]],
        ["`usdinr_fwd_1m`", _num(raw["usdinr_fwd_1m"], 4), "covered interest parity", pflags["usdinr_fwd_1m"]],
        ["`customs_usdinr_import`", _num(ins["customs_usdinr_import"], 2), row["customs_fx_src"],
         k("customs_usdinr_import").flag],
        [f"`grade_factor_{g}`", _num(ins["grade_factor"], 6), "lag-2 DGCIS mix + 2024–25 differential (linear path)",
         k(f"grade_factor_{g}").flag],
        [f"`{spec.freight_col}`", _num(raw[spec.freight_col]), "WCI shape × assumed level", pflags[spec.freight_col]],
        [f"`container_payload_mt_{spec.box}` / `_{g}`",
         f"{ins['container_payload_base_mt']:g} / {ins['container_payload_grade_mt']:g}", "logistics.yaml",
         _weakest([f"container_payload_mt_{spec.box}", f"container_payload_mt_{spec.box}_{g}"], pflags)],
        ["`insurance_rate` × `insured_value_uplift`", f"{ins['insurance_rate']:g} × {ins['insured_value_uplift']:g}",
         "logistics.yaml", _weakest(["insurance_rate", "insured_value_uplift"], pflags)],
        ["`bcd_scrap_hs7602`, `sws_rate_on_bcd`, `igst_rate_hs7602`",
         f"{ins['bcd_scrap_hs7602']:g}, {ins['sws_rate_on_bcd']:g}, {ins['igst_rate_hs7602']:g}", "CBIC / GST",
         _weakest(["bcd_scrap_hs7602", "sws_rate_on_bcd", "igst_rate_hs7602"], pflags)],
        [f"`port_cf_charges_inr_t_{spec.port}`, `psic_cost_usd_per_box`",
         f"{ins['port_cf_charges_inr_t']:,.0f}, {ins['psic_cost_usd_per_box']:g} (PSIC applies: "
         f"{bool(ins['psic_applies'])})", "logistics / regulatory",
         _weakest([f"port_cf_charges_inr_t_{spec.port}", "psic_cost_usd_per_box"], pflags)],
        [f"`{spec.finance_key}`, `wc_rate_inr_pa`, `igst_credit_lag_days`",
         f"{ins['finance_days']:g}, {ins['wc_rate_inr_pa']:g}, {ins['igst_credit_lag_days']:g}", "logistics / rates",
         _weakest([spec.finance_key, "wc_rate_inr_pa", "igst_credit_lag_days"], pflags)],
        [f"moisture / contamination / yield / heavies ({g})",
         f"{ins['moisture_frac']:g} / {ins['contamination_frac']:g} / {ins['metal_yield_frac']:g} / "
         f"{ins['heavies_frac']:g}", "scrap_grades.yaml",
         _weakest([f"moisture_frac_{g}", f"contamination_frac_{g}", f"metal_yield_frac_{g}", f"heavies_frac_{g}"],
                  pflags)],
        ["`heavies_net_value_frac_of_lme_al`", f"{ins['heavies_net_value_frac_of_lme_al']:g}", "scrap_grades.yaml",
         k("heavies_net_value_frac_of_lme_al").flag],
        [f"`{spec.mcx_col}`", _num(raw[spec.mcx_col], 4), "MCX import-parity proxy", pflags[spec.mcx_col]],
        ["`domestic_anchor_premium_inr_t`, `conversion_cost_inr_t`, `margin_threshold_inr_t`",
         f"{_num(ins['domestic_anchor_premium_inr_t'], 0)}, {ins['conversion_cost_inr_t']:,.0f}, "
         f"{ins['margin_threshold_inr_t']:,.0f}", "commercial.yaml",
         _weakest(["domestic_anchor_premium_inr_t", "conversion_cost_inr_t", "margin_threshold_inr_t"], pflags)],
    ]
    fx, fxg = raw["usdinr"], raw["usdinr_fwd_1m"]
    psic_txt = (f" + {ins['psic_cost_usd_per_box']:g} × {_num(fx, 4)} ÷ {ins['container_payload_20ft_grade_mt']:g}"
                if bool(ins["psic_applies"]) else "")
    steps = [
        ("cfr_usd_t", f"{_num(raw['lme_3m_usd_t'])} × {_num(ins['grade_factor'], 6)}", 4),
        ("payload_scale", f"{ins['container_payload_base_mt']:g} ÷ {ins['container_payload_grade_mt']:g}", 6),
        ("freight_usd_t", f"{_num(raw[spec.freight_col])} × {_num(row['payload_scale'], 6)}", 4),
        ("fob_usd_t", f"{_num(row['cfr_usd_t'], 4)} − {_num(row['freight_usd_t'], 4)}", 4),
        ("insurance_usd_t", f"{ins['insurance_rate']:g} × {ins['insured_value_uplift']:g} × {_num(row['cfr_usd_t'], 4)}",
         4),
        ("cif_usd_t", f"{_num(row['cfr_usd_t'], 4)} + {_num(row['insurance_usd_t'], 4)}", 4),
        ("av_customs_inr_t", f"{_num(row['cif_usd_t'], 4)} × {_num(ins['customs_usdinr_import'], 2)}", 2),
        ("goods_inr_t", f"{_num(row['cif_usd_t'], 4)} × {_num(fxg, 4)}", 2),
        ("bcd_inr_t", f"{_num(row['av_customs_inr_t'])} × {ins['bcd_scrap_hs7602']:g}", 2),
        ("sws_inr_t", f"{_num(row['bcd_inr_t'])} × {ins['sws_rate_on_bcd']:g}", 2),
        ("igst_inr_t", f"({_num(row['av_customs_inr_t'])} + {_num(row['bcd_inr_t'])} + {_num(row['sws_inr_t'])}) × "
                       f"{ins['igst_rate_hs7602']:g}", 2),
        ("port_inr_t", f"{ins['port_cf_charges_inr_t']:,.0f} × {_num(row['payload_scale'], 6)}{psic_txt}", 2),
        ("finance_inr_t", f"({_num(row['goods_inr_t'])} + {_num(row['bcd_inr_t'])} + {_num(row['sws_inr_t'])}) × "
                          f"{ins['finance_days']:g} ÷ 365 × {ins['wc_rate_inr_pa']:g}", 2),
        ("igst_finance_inr_t", f"{_num(row['igst_inr_t'])} × {ins['igst_credit_lag_days']:g} ÷ 365 × "
                               f"{ins['wc_rate_inr_pa']:g}", 2),
        ("landed_inr_t", f"{_num(row['goods_inr_t'])} + {_num(row['bcd_inr_t'])} + {_num(row['sws_inr_t'])} + "
                         f"{_num(row['port_inr_t'])} + {_num(row['finance_inr_t'])} + "
                         f"{_num(row['igst_finance_inr_t'])} (IGST itself excluded: ITC available)", 2),
        ("recovery_frac", f"(1 − {ins['moisture_frac']:g}) × (1 − {ins['contamination_frac']:g}) × "
                          f"{ins['metal_yield_frac']:g}", 6),
        ("anchor_inr_t", f"{_num(raw[spec.mcx_col], 4)} × 1,000 + ({_num(ins['domestic_anchor_premium_inr_t'], 0)})", 2),
        ("byproduct_inr_t", f"(1 − {ins['moisture_frac']:g}) × {ins['heavies_frac']:g} × "
                            f"{ins['heavies_net_value_frac_of_lme_al']:g} × {_num(raw['lme_3m_usd_t'])} × "
                            f"{_num(fx, 4)}", 2),
        ("conversion_inr_t", f"{ins['conversion_cost_inr_t']:,.0f} × {_num(row['recovery_frac'], 6)}", 2),
        ("net_arb_inr_t", f"{_num(row['anchor_inr_t'])} × {_num(row['recovery_frac'], 6)} + "
                          f"{_num(row['byproduct_inr_t'])} − {_num(row['landed_inr_t'])} − "
                          f"{_num(row['conversion_inr_t'])}", 2),
    ]
    step_rows = [[f"`{item}`", expr, f"**{_num(row[item], dec)}**"] for item, expr, dec in steps]
    step_rows.append(["`window_open`", f"{_num(row['net_arb_inr_t'])} > {ins['margin_threshold_inr_t']:,.0f}",
                      f"**{bool(row['window_open'])}**"])
    step_rows.append(["`net_arb_usd_t` (memo)", f"{_num(row['net_arb_inr_t'])} ÷ {_num(fx, 4)}",
                      f"**{_num(row['net_arb_usd_t'], 4)}**"])
    return [
        f"## 5. Worked example — reference case `{ref.ref}`: {_d(ref.week_end)}, {ref.grade}, {ref.lane}", "",
        f"Selection rule (declared in `desk.parity.sensitivity.reference_cases`): {ref.rule}. Every result below is "
        "the value in `outputs/tables/parity_weekly.csv` for that row (INR to 2 dp, USD to 4 dp).", "",
        "**Inputs**", "", _md_table(["Input", "Value", "Source", "Flag"], inputs_rows), "",
        "**Line items**", "", _md_table(["Line item", "Arithmetic", "Result"], step_rows), "",
        f"§5a for the same row: point-in-time mix net arb {_inr(row['net_arb_pit_mix_inr_t'])} → `open_pit_mix` = "
        f"{bool(row['open_pit_mix'])}; conversion {_inr(model.conversion_step_above_base())}/t ingot net arb "
        f"{_inr(row['net_arb_conv18k_inr_t'])} → `open_conv18k` = {bool(row['open_conv18k'])}; `trade_eligible` = "
        f"**{bool(row['trade_eligible'])}**. Chart: `outputs/charts/p1_landed_cost_waterfall.png`.", "",
    ]


def _doc_results(r: Results) -> list[str]:
    p = r.parity
    win = p[p["in_window"]]
    rows, elig_rows, block_rows = [], [], []
    for g in model.GRADES:
        for l in model.LANES:
            s = win[(win["grade"] == g) & (win["lane"] == l)]
            rows.append([g, l, int(s["open_base"].sum()), int(s["open_pit_mix"].sum()), int(s["open_conv18k"].sum()),
                         f"**{int(s['trade_eligible'].sum())}**", _inr(s["net_arb_inr_t"].max()) + " (" +
                         _dd(s.loc[s["net_arb_inr_t"].idxmax(), "week_end"]) + ")",
                         _inr(s["net_arb_inr_t"].min()) + " (" + _dd(s.loc[s["net_arb_inr_t"].idxmin(), "week_end"])
                         + ")"])
            elig_rows.append([g, l, _ranges(s.loc[s["trade_eligible"], "week_end"])])
            blocked = s[s["open_base"] & ~s["trade_eligible"]]
            pit_only = blocked[~blocked["open_pit_mix"] & blocked["open_conv18k"]]
            conv_only = blocked[blocked["open_pit_mix"] & ~blocked["open_conv18k"]]
            both = blocked[~blocked["open_pit_mix"] & ~blocked["open_conv18k"]]
            block_rows.append([g, l, len(blocked), _ranges(pit_only["week_end"]), _ranges(conv_only["week_end"]),
                               _ranges(both["week_end"])])
    ctx = p[~p["in_window"] & p["trade_eligible"]]
    ctx_all = all(((ctx["grade"] == g) & (ctx["lane"] == l)).any() for g in model.GRADES for l in model.LANES)
    extra = (model.conversion_step_above_base() - float(config.value("conversion_cost_inr_t"))) * p["recovery_frac"]
    zt = win[win["grade"] != "tense"]
    late_zt = zt[zt["week_end"].dt.month >= 8]
    tense_el = {l: _ranges(win[(win["grade"] == "tense") & (win["lane"] == l) & win["trade_eligible"]]["week_end"])
                for l in model.LANES}
    total_elig = int(win["trade_eligible"].sum())
    never = [f"{g} {l}" for g in model.GRADES for l in model.LANES
             if not win[(win["grade"] == g) & (win["lane"] == l)]["trade_eligible"].any()]
    return [
        "## 6. Results (base, §5a flags, eligible weeks)", "",
        f"Counts are over the 27 in-window weeks. In total **{total_elig} of {len(win)}** in-window week × grade × "
        f"lane cases are trade-eligible (base alone: {int(win['open_base'].sum())}).", "",
        _md_table(["Grade", "Lane", "Base open", "PIT-mix open", "Conv 18k open", "Trade-eligible",
                   "Max base net arb", "Min base net arb"], rows), "",
        "**Trade-eligible in-window weeks (week ending, run length)**", "",
        _md_table(["Grade", "Lane", "Eligible weeks"], elig_rows), "",
        "**Base-open weeks that the §5a rule rejects, and which case rejects them**", "",
        _md_table(["Grade", "Lane", "Base open, not eligible", "Only PIT mix closed", "Only conv 18k closed",
                   "Both closed"], block_rows), "",
        f"Out-of-window context weeks that are eligible: {_ranges(ctx['week_end'].unique())}"
        f"{' (every grade-lane)' if ctx_all else ''}; those rows exist only for look-ups and charts, not for trading. "
        + ("Every grade-lane has at least one eligible window week." if not never else
           f"Never eligible in the window: {', '.join(never)}."), "",
        "How to read it. The base net arb is huge in the March spike and collapses into June–July: the constant anchor "
        "premium rides the MCX proxy down with LME, while the lag-2 grade factor *rises* through the crash (scrap "
        "prices lag LME), squeezing Zorba and Taint/Tabor below the hurdle. The point-in-time mix is three months "
        "staler, so it is low when the lag-2 mix is high and vice-versa — it opens June–July and shaves March. The "
        f"₹{model.conversion_step_above_base() / 1000:g}k conversion case is what shuts Zorba and Taint/Tabor after "
        f"early May: their August base margin (at most {_inr(late_zt['net_arb_inr_t'].max())}/t) does not survive the "
        f"extra ₹{(model.conversion_step_above_base() - float(config.value('conversion_cost_inr_t'))) / 1000:g}k per t "
        f"of ingot (≈ {_inr(extra.min())}–{_inr(extra.max())} per t of scrap). Tense (lowest grade factor, highest "
        f"recovery) is eligible {tense_el['JEA_NSA']} on JEA_NSA and {tense_el['USEC_MUN']} on USEC_MUN. Charts: "
        "`p1_net_arb_weekly.png`, `p1_window_heatmap.png`.",
        "",
    ]


KEY_FLIP_CASES = ["mix_lag1", "mix_lag3", "mix_pit", "grade_diff_minus_iqr", "grade_diff_plus_iqr",
                  "anchor_premium_-52000", "anchor_premium_+13000", "anchor_sticky_trailing", "anchor_mirror_m1",
                  "conversion_18000", "conversion_30000", "metal_yield_low", "heavies_value_0.4", "goods_fx_spot"]


def _doc_band(r: Results) -> list[str]:
    sm = r.summary
    cols = [(g, l) for g in model.GRADES for l in model.LANES]
    rows = []
    for case in dict.fromkeys(sm["case"]):
        s = sm[sm["case"] == case].set_index(["grade", "lane"])
        req = "rule" if case == "trade_eligible_5a" else ("yes" if s["required"].iloc[0] else "info")
        rows.append([f"`{case}`", s["case_group"].iloc[0], req]
                    + [int(s.loc[c, "open_weeks"]) for c in cols] + [int(s["flips_vs_base"].sum())])
    long = r.cases_long[r.cases_long["in_window"]]
    base = long[long["case"] == "base"].set_index(["week_end", "grade", "lane"])["window_open"]
    flip_rows = []
    for case in KEY_FLIP_CASES:
        c = long[long["case"] == case].set_index(["week_end", "grade", "lane"])["window_open"]
        for g, l in cols:
            cb = c.xs((g, l), level=("grade", "lane"))
            bb = base.xs((g, l), level=("grade", "lane"))
            opened, closed = cb[cb & ~bb].index, cb[~cb & bb].index
            if len(opened) or len(closed):
                flip_rows.append([f"`{case}`", f"{g} {l}", _ranges(opened), _ranges(closed)])
    none_flip = sorted(set(KEY_FLIP_CASES) - {row[0].strip("`") for row in flip_rows})
    first_week = long["week_end"].min()
    fw = long[long["week_end"] == first_week]
    shut_first = [c for c, sub in fw[fw["required"]].groupby("case", sort=False) if not sub["window_open"].any()]
    stick = fw[fw["case"] == "anchor_sticky_trailing"]
    mirror_first_open = bool(fw[fw["case"] == "anchor_mirror_m1"]["window_open"].all())
    minor = sm[sm["case"].isin(["goods_fx_spot", "anchor_mirror_m1"])]["flips_vs_base"].max()
    short = {"zorba": "Zorba", "taint_tabor": "TT", "tense": "Tense"}
    return [
        "## 7. Sensitivity band — the CONTRACTS §5 required cases", "",
        "Each case swaps one input through the same arithmetic (`parity_sensitivity_cases.csv`). Required cases: lag-1 / "
        "lag-3 / point-in-time grade mix; each grade differential at its evidence quartiles and ± one IQR width "
        "(both readings of \"± IQR\" are shown); every `domestic_anchor_premium_sensitivity_inr_t` value; the sticky "
        "anchor (trailing `domestic_anchor_trailing_bdays`-day mean MCX spot + `domestic_anchor_premium_trailing_inr_t`, "
        "window ending on the value date); every `conversion_cost_sensitivity_inr_t_ingot` value; metal-yield and "
        "heavies-value ranges from the Phase 0 notes (registered in parity.yaml); the anchor on the third-party MCX "
        "mirror M1 (PROXY). Informational: mirror M1/2M by lane, goods at spot, PIT mix and 18k together, and the "
        "MASTER_SPEC Taint/Tabor +0.10 factor.", "",
        "**Open in-window weeks (of 27) per case**", "",
        _md_table(["Case", "Group", "Req."] + [f"{short[g]} {l.split('_')[0]}" for g, l in cols]
                  + ["Flips vs base (Σ)"], rows), "",
        "**When the key cases flip the base flag** (in-window weeks opened / closed relative to base)", "",
        _md_table(["Case", "Grade-lane", "Opens", "Closes"], flip_rows), "",
        *([f"Cases in the list with no flip anywhere: {', '.join('`' + c + '`' for c in none_flip)}.", ""]
          if none_flip else []),
        "Findings.",
        "- **The grade-mix lag and the anchor model decide the shape of the window; costs decide its width.** The "
        "point-in-time mix and the sticky anchor each re-open Zorba and Taint/Tabor through the June–July trough that "
        "shuts the base case; the extreme premiums (−52k/−55k vs +13k) shut or open almost every week.",
        f"- Required cases that shut the first window week ({_dd(first_week)}) for every grade-lane: "
        f"{', '.join('`' + c + '`' for c in shut_first) or 'none'} (sticky-anchor net arb that week "
        f"{_inr(stick['net_arb_inr_t'].min())} to {_inr(stick['net_arb_inr_t'].max())}). The mirror-M1 anchor, which "
        "removes the proxy's March overshoot, "
        + ("still leaves that week open for every grade-lane — so the March eligibility does not rest on the proxy "
           "bias alone, but it does rest on the constant-premium anchor." if mirror_first_open else
           "closes part of it — the March eligibility partly rests on the proxy bias."),
        "- Conversion 18k/30k, the low yield and Tense's + IQR differential flip Tense around the June–July trough; "
        f"goods at spot and the mirror-M1 anchor flip at most {int(minor)} weeks per grade-lane.",
        "- Chart: `p1_sensitivity_band.png` (min–max and inter-quartile envelope across the required cases).", "",
    ]


def _doc_grids(r: Results) -> list[str]:
    lf, fd = r.grid_lme_fx, r.grid_freight_duty
    lines = ["## 8. Table 1.5 — two-way P&L grids on 1,000 MT", "",
             "P&L impact = (net_arb_shocked − net_arb_base) × 1,000 MT: the change in the *parity margin* of a trade "
             "whose purchase and sale both re-price (a fixed-price position is Phase 3). `model.market_shock_overrides` "
             "re-derives every dependent input: LME shocks scale 3M and cash, so CFR, the customs duty base, finance "
             "and the Zorba by-product move; the MCX proxy anchor (duty-paid LME cash parity × carry, premium 0) scales "
             "with LME × FX and keeps its carry; a USD/INR level scales the goods forward and the customs notified rate "
             "by the week's observed ratio to spot. Scrap BCD does not move the MCX anchor (that parity uses the HS 7601 "
             "primary duty). INR costs are held. Freight: under **CFR** the seller books freight, so freight shocks do "
             "not change the buyer's margin (only BCD columns move); under **FOB** the desk books freight and the CFR-"
             "equivalent cost rises one-for-one with the freight change. Freight levels are hindsight reconstructions.",
             ""]
    for ref in r.refs:
        g = lf[lf["ref_case"] == ref.ref]
        base_fx = float(g.loc[g["usdinr_is_base"], "usdinr"].iloc[0])
        show_fx = [74.0, 76.0, 78.0, 80.0, 82.0]
        hdr = ["LME shock"] + [f"{x:.0f}" for x in show_fx] + [f"base {base_fx:.2f}"]
        rows = []
        for pct in sorted(g["lme_shock_pct"].unique(), reverse=True):
            s = g[g["lme_shock_pct"] == pct]
            vals = [_mn(s.loc[(s["usdinr"] == x) & ~s["usdinr_is_base"], "pnl_impact_1000mt_inr"].iloc[0]) for x in
                    show_fx]
            vals.append(_mn(s.loc[s["usdinr_is_base"], "pnl_impact_1000mt_inr"].iloc[0]))
            rows.append([f"{pct:+d}%".replace("-", "−")] + vals)
        b = g.iloc[0]
        at_base = g[g["usdinr_is_base"]].set_index("lme_shock_pct")["pnl_impact_1000mt_inr"]
        fx_slope = (g[(g["lme_shock_pct"] == 0) & (g["usdinr"] == 79.0)]["pnl_impact_1000mt_inr"].iloc[0]
                    - g[(g["lme_shock_pct"] == 0) & (g["usdinr"] == 78.0)]["pnl_impact_1000mt_inr"].iloc[0])
        opens = g[g["window_open_shocked"]]
        lines += [f"**(a) LME × USD/INR — `{ref.ref}` {_d(ref.week_end)} {ref.grade} {ref.lane}** (base net arb "
                  f"{_inr(b['net_arb_base_inr_t'])}/t; ₹ million on 1,000 MT; all 9 FX columns in the CSV)", "",
                  _md_table(hdr, rows), "",
                  f"At base FX a −10% LME move costs ₹{abs(at_base[-10]) / 1e6:,.2f} mn and −30% "
                  f"₹{abs(at_base[-30]) / 1e6:,.2f} mn on 1,000 MT; each ₹1 on USD/INR (78→79, LME unchanged) is worth "
                  f"₹{_mn(fx_slope)} mn. The margin is long LME and long USD because the anchor (primary aluminium at "
                  "7.5% duty, × recovery) carries more metal value than the scrap cost (grade factor × LME at 2.75% "
                  f"duty) while conversion and port costs stay fixed in rupees. Window open in {len(opens)} of "
                  f"{len(g)} grid cells.", ""]
        f = fd[(fd["ref_case"] == ref.ref) & (fd["freight_terms"] == "FOB_desk_books_freight")]
        bcds = sorted(f["bcd_rate_pct"].unique())
        rows = []
        for pct in sorted(f["freight_shock_pct"].unique(), reverse=True):
            s = f[f["freight_shock_pct"] == pct].set_index("bcd_rate_pct")["pnl_impact_1000mt_inr"]
            rows.append([f"{pct:+d}%".replace("-", "−")] + [_mn(s[x]) for x in bcds])
        lines += [f"**(b) Freight × BCD, FOB terms — `{ref.ref}`** (₹ million on 1,000 MT; CFR rows all equal the "
                  "0% freight row)", "",
                  _md_table(["Freight shock"] + [f"BCD {x:g}%" for x in bcds], rows), ""]
    ref = r.refs[0]
    other_lane = [l for l in model.LANES if l != ref.lane][0]
    base_o = model.parity_row(ref.week_end, ref.grade, other_lane, inputs=r.inputs)
    shock_o = model.parity_row(ref.week_end, ref.grade, other_lane, inputs=r.inputs,
                               overrides=model.market_shock_overrides(freight_shock_frac=0.6, freight_on_buyer=True))
    fob = fd[fd["freight_terms"] == "FOB_desk_books_freight"]
    bcd5 = fob[(fob["freight_shock_pct"] == 0) & (fob["bcd_rate_pct"] == 5.0)]["pnl_impact_1000mt_inr"].abs()
    max_freight = fob[(fob["bcd_rate_pct"] == float(config.value("bcd_scrap_hs7602")) * 100)][
        "pnl_impact_1000mt_inr"].abs().max()
    lines += [f"Freight matters little on the short Gulf lane (JEA_NSA freight ≈ USD "
              f"{_num(model.parity_row(ref.week_end, ref.grade, ref.lane, inputs=r.inputs)['freight_usd_t'])}/t). "
              f"For scale, the same week on {other_lane} (freight USD {_num(base_o['freight_usd_t'])}/t): +60% "
              f"freight on FOB terms costs ₹{abs(shock_o['net_arb_inr_t'] - base_o['net_arb_inr_t']) * 1000 / 1e6:,.2f}"
              f" mn per 1,000 MT. A BCD rise from 2.5% to 5% costs ₹{bcd5.min() / 1e6:,.2f}–{bcd5.max() / 1e6:,.2f} mn "
              f"per 1,000 MT at the two reference weeks, against at most ₹{max_freight / 1e6:,.2f} mn for any freight "
              "shock in the Gulf-lane grid at the base duty. Charts: `p1_sensitivity_lme_fx.png`, "
              "`p1_sensitivity_freight_duty.png`.", ""]
    return lines


def _doc_quality(r: Results) -> list[str]:
    q = r.quality
    ref = r.refs[0]
    rows = []
    for g in model.GRADES:
        s = q[(q["grade"] == g) & (q["metal_yield_case"] == "base")]
        base_m = float(config.value(f"moisture_frac_{g}"))
        base_c = float(config.value(f"contamination_frac_{g}"))
        picks = [(base_m, base_c), (0.03, base_c), (base_m, round(base_c + 0.02, 6)), (0.03, round(base_c + 0.02, 6)),
                 (base_m, round(base_c + 0.05, 6))]
        for m, c in picks:
            x = s[(np.isclose(s["moisture_frac"], m)) & (np.isclose(s["contamination_frac"], c))].iloc[0]
            rows.append([g, f"{m:.3f}", f"{c:.3f}", x["outcome"], f"{x['payable_frac']:.3f}",
                         f"{x['discount_frac']:.3f}", f"{x['recovery_frac']:.4f}",
                         _inr(x["landed_per_t_recovered_inr_t"]), _inr(x["net_arb_impact_inr_t"]),
                         _inr(x["spa_clause_value_inr_t"])])
    y = q[q["is_base_quality"] | ((q["metal_yield_case"] != "base")
                                  & q.apply(lambda x: np.isclose(x["moisture_frac"], config.value(
                                      f"moisture_frac_{x['grade']}")) and np.isclose(x["contamination_frac"],
                                                                                    config.value(f"contamination_frac_{x['grade']}")),
                                            axis=1))]
    yrows = [[g] + [_inr(y[(y["grade"] == g) & (y["metal_yield_case"] == c)]["net_arb_impact_inr_t"].iloc[0])
                    for c in ("low", "high")] for g in model.GRADES]
    franchise = float(config.value("standard_moisture_franchise_frac"))
    fr = q[(q["grade"] == "tense") & (q["metal_yield_case"] == "base") & np.isclose(q["moisture_frac"], franchise)
           & np.isclose(q["contamination_frac"], float(config.value("contamination_frac_tense")))].iloc[0]
    tt_y = y[(y["grade"] == "taint_tabor") & (y["metal_yield_case"] == "low")]["net_arb_impact_inr_t"].iloc[0]
    c2 = q[(q["metal_yield_case"] == "base") & np.isclose(q["contamination_excess_frac"], 0.02)
           & q.apply(lambda x: np.isclose(x["moisture_frac"], config.value(f"moisture_frac_{x['grade']}")), axis=1)]
    return [
        "## 9. Table 1.6 — scrap reality check (SPA settlement, moisture, contamination, yield)", "",
        "Rules (`desk.parity.quality`, numbers registered in parity.yaml from commercial.yaml "
        "`rejection_penalty_schedule`): moisture above `standard_moisture_franchise_frac` "
        f"({config.value('standard_moisture_franchise_frac'):g}) is deducted from invoice weight "
        f"{config.value('spa_moisture_deduction_ratio'):g}:1; contamination above the grade's priced "
        "`contamination_frac_<grade>` earns a price discount of "
        f"{config.value('spa_contamination_discount_multiple'):g} × the excess on the whole lot; an excess above "
        f"{config.value('spa_contamination_rejection_excess_frac') * 100:g} points (or any radioactivity finding) makes "
        "the lot rejectable. Value-based costs (goods, duties, finance) scale with the settled invoice value; box-based "
        "costs (port, PSIC) do not. Recovery = (1 − moisture)(1 − contamination) × yield. Scenarios re-value the "
        f"reference week/lane ({_d(ref.week_end)}, {ref.lane}) for every grade; REJECTABLE rows are shown as if the desk "
        "accepted at the schedule discount (the renegotiation reference).", "",
        _md_table(["Grade", "Moisture", "Contam.", "Outcome", "Payable", "Discount", "Recovery",
                   "Landed / t recovered", "Net-arb impact / t", "Value of SPA clauses / t"], rows), "",
        "Metal-yield range at base moisture/contamination (net-arb impact per MT of scrap):", "",
        _md_table(["Grade", "Yield low", "Yield high"], yrows), "",
        "Findings. (1) Wet or dirty cargo costs the desk its share of metal value; the 'value of SPA clauses' column "
        "is what the weight deduction and discount give back (`net_arb_no_spa_clauses_inr_t` is the unprotected "
        "margin). The weight deduction returns most, not all, of a moisture excess (port costs and the metal in "
        "franchise moisture are not refunded). At this week's prices the 1.5× contamination discount more than "
        "compensates the lost metal (+2 points: impact "
        f"{', '.join(_inr(v) for v in c2['net_arb_impact_inr_t'])} for Zorba / Taint-Tabor / Tense) — a punitive design "
        "that deters dilution and that a supplier would negotiate down. (2) Moisture *inside* the franchise is paid "
        f"for: Tense priced at {config.value('moisture_frac_tense'):g} but delivered at the {franchise:g} franchise "
        f"costs {_inr(abs(fr['net_arb_impact_inr_t']))}/t with no recourse. (3) Melt yield, which no clause covers, moves "
        f"the margin by the size of the hurdle: Taint/Tabor at the low end of its yield range loses "
        f"{_inr(abs(tt_y))}/t.", "",
    ]


def _doc_term_structure(r: Results) -> list[str]:
    w, ro = r.ts_weekly, r.ts_rolls
    tw = w[w["in_window"]]
    daily = r.panel[r.panel["in_window"]]
    n_cont, n_back = int((daily["lme_cash_3m_spread_usd_t"] < 0).sum()), int((daily["lme_cash_3m_spread_usd_t"] > 0).sum())
    month_rows = []
    tw = tw.assign(month=pd.to_datetime(tw["value_date"]).dt.to_period("M").astype(str))
    for mth, s in tw.groupby("month"):
        month_rows.append([mth, len(s), _num(s["lme_cash_3m_spread_usd_t"].mean(), 1),
                           f"{int((s['structure'] == 'CONTANGO').sum())}/{int((s['structure'] == 'BACKWARDATION').sum())}",
                           _num(s["carry_3m_pct_pa"].mean() * 100, 2), s["mplus1_month"].iloc[0],
                           _num(s["structure_effect_buyer_usd_t"].mean(), 2),
                           _mn(s["structure_effect_buyer_1000mt_inr"].mean()),
                           _num((s["lme_3m_usd_t"] - s["hindsight_realised_mplus1_avg_cash_usd_t"]).mean(), 1),
                           _mn(s["hindsight_effect_buyer_vs_3m_1000mt_inr"].mean())])
    roll_rows = [[x.contract_month, _d(x.roll_date), "yes" if x.in_window else "no", _num(x.roll_spread_inr_kg, 2),
                  _mn(x.short_hedge_roll_yield_1000mt_inr), _mn(x.mirror_short_hedge_roll_yield_1000mt_inr),
                  x.lme_structure, _num(x.lme_equiv_carry_usd_t, 2), _mn(x.lme_equiv_short_roll_yield_1000mt_inr),
                  "" if x.expiry_matches_published in (True, None) else f"panel {_dd(x.m1_expiry)} vs MCX "
                                                                           f"{_dd(x.mcx_published_expiry)}"]
                 for x in ro.itertuples()]
    rw = ro[ro["in_window"]]
    neg = tw.loc[tw["structure_effect_buyer_usd_t"] < 0, "week_end"]
    n_mismatch = int((ro["expiry_matches_published"] == False).sum())  # noqa: E712
    mism = ", ".join(x.contract_month for x in ro.itertuples() if x.expiry_matches_published is False)
    return [
        "## 10. Table 1.7 — LME term structure", "",
        "**Pricing reference.** The desk's LME-linked SPAs settle against the **LME Official Cash Settlement Price** "
        f"(exchange.yaml `lme_pricing_reference`: \"{config.value('lme_pricing_reference')}\"), averaged over the month "
        f"after the B/L month (`lme_m1_pricing_rule`: \"{config.value('lme_m1_pricing_rule')}\"). The parity itself "
        "prices off **3M**, the forward that can be hedged on the decision date; this section measures the gap.", "",
        "**Method.** Weekly Cash − 3M on the parity value date (positive = backwardation). The market-implied expected "
        "M+1 average of cash is read off a forward curve linear in calendar days between the cash prompt (value date + "
        f"{config.value('lme_cash_prompt_bdays')} business days) and the 3M prompt (value date + 3 months, next "
        "weekday); each weekday of the M+1 month fixes a cash price for its own T+2 prompt, and the expected average is "
        "the mean of the curve over those prompts (expectations hypothesis — no risk premium; LME holidays ignored). "
        "B/L month = the parity week's month (`mplus1_bl_month_offset_months` = 0). Structure effect for a buyer priced "
        "on M+1 average cash = 3M − implied M+1 average (positive: the structure earns the buyer vs a 3M-priced parity). "
        "The realised M+1 average is shown as **HINDSIGHT** only.", "",
        f"In the window the daily LME curve was in contango on {n_cont} days and backwardation on {n_back} "
        f"(parity value dates: {int((tw['structure'] == 'CONTANGO').sum())} contango / "
        f"{int((tw['structure'] == 'BACKWARDATION').sum())} backwardation weeks; mean Cash − 3M "
        f"USD {_num(tw['lme_cash_3m_spread_usd_t'].mean(), 2)}/t, range {_num(tw['lme_cash_3m_spread_usd_t'].min(), 1)} to "
        f"{_num(tw['lme_cash_3m_spread_usd_t'].max(), 1)}).", "",
        _md_table(["Parity month", "Weeks", "Mean Cash−3M USD/t", "Contango/backw. weeks", "3M carry % p.a.",
                   "M+1 month", "Ex-ante effect USD/t", "Ex-ante ₹ mn / 1,000 t", "HINDSIGHT 3M − realised USD/t",
                   "HINDSIGHT ₹ mn / 1,000 t"], month_rows), "",
        f"(a) **M+1 basis.** Averaged over the window weeks the curve shape alone earned a buyer priced on M+1 average "
        f"cash USD {_num(tw['structure_effect_buyer_usd_t'].mean(), 2)}/t of aluminium content "
        f"(₹{tw['structure_effect_buyer_1000mt_inr'].mean() / 1e6:,.2f} mn per 1,000 t; multiply by the grade factor, "
        f"~0.7–0.85, for tonnes of scrap) versus the 3M price the parity used; it cost the buyer only in the "
        f"backwardation weeks ({_ranges(neg)}). That is small next to what the *price move* did: in hindsight the "
        f"realised M+1 cash average was on average USD "
        f"{_num((tw['lme_3m_usd_t'] - tw['hindsight_realised_mplus1_avg_cash_usd_t']).mean(), 0)}/t below the 3M at "
        "decision (the crash). That windfall on the purchase leg is only kept if the sale price was fixed or hedged "
        "over the same period — an MCX-linked sale fell too — which is why the M+1 quotational period must be matched "
        "to the sale and hedge dates.", "",
        "(b) **Roll yield on a 1,000 MT short MCX hedge** (200 lots of 5 MT), rolled M1 → M2 "
        f"{config.value('mcx_roll_days_before_expiry')} panel trading days before expiry (₹ million per 1,000 MT; + = "
        "earned by the short):", "",
        _md_table(["Contract", "Roll date", "In window", "Proxy M2−M1 ₹/kg", "MCX proxy", "MCX mirror (PROXY)",
                   "LME structure", "LME carry USD/t", "LME-equivalent", "Expiry note"], roll_rows), "",
        f"Over the six in-window rolls the MCX proxy roll earns ₹{rw['short_hedge_roll_yield_1000mt_inr'].sum() / 1e6:,.2f}"
        f" mn per 1,000 MT, the mirror ₹{rw['mirror_short_hedge_roll_yield_1000mt_inr'].sum() / 1e6:,.2f} mn and the "
        f"LME-equivalent carry ₹{rw['lme_equiv_short_roll_yield_1000mt_inr'].sum() / 1e6:,.2f} mn. Read carefully: the "
        "proxy's M2 − M1 is *by construction* INR interest carry on duty-paid parity (~₹0.9–1.0/kg a month), not metal "
        "contango — earning it only offsets the desk's own financing of the physical. The LME curve itself was nearly "
        "flat on roll dates (small contango earns, small backwardation costs). The mirror's in-window rolls swing from "
        f"₹{_mn(rw['mirror_short_hedge_roll_yield_1000mt_inr'].min())} mn to "
        f"₹{_mn(rw['mirror_short_hedge_roll_yield_1000mt_inr'].max())} mn because its 2M series is partly stale, so it "
        "is not evidence of a real MCX roll yield. The panel's rule-based expiry differs from MCX's published date in "
        f"{n_mismatch} contract month(s) ({mism or 'none'}). Chart: `p1_term_structure.png`.", "",
    ]


def _doc_correlation(r: Results) -> list[str]:
    c = r.correlation
    rows = []
    for pair, *_ in sensitivity.ANCHOR_PAIRS:
        for sample in ("window_2022-03-01_2022-08-31", "panel_2018-01-02_2022-12-30"):
            s = c[(c["pair"] == pair) & (c["sample"] == sample)].set_index("metric")["value"]
            rows.append([f"`{pair}`", "Mar–Aug 2022" if sample.startswith("window") else "2018–2022",
                         int(s["n_common_days"]), _num(s["level_corr"], 3), _num(s["daily_logret_corr"], 3),
                         _num(s["weekly_logret_corr"], 3), _inr(s["basis_mean_inr_t"]),
                         _inr(s["basis_std_inr_kg"] * 1000)])
    adc = c[c["pair"] == "adc12_vs_duty_paid_cash_parity"].set_index("metric")["value"]
    mir = c[c["pair"] == "mirror_m1_vs_duty_paid_parity"].pivot_table(index="sample", columns="metric", values="value")
    return [
        "## 11. Table 1.3 — domestic anchor: correlation study (the anchor is PROXY)", "",
        "The anchor is MCX Aluminium (panel PROXY: duty-paid LME cash import parity × INR carry, "
        "`mcx_domestic_premium_inr_kg` = 0) plus a constant secondary-ingot premium. Basis = series A − series B.", "",
        _md_table(["Pair (A vs B)", "Sample", "Days", "Level corr", "Daily log-ret corr", "Weekly log-ret corr",
                   "Basis mean ₹/t", "Basis std ₹/t"], rows), "",
        "- Proxy vs LME × FX × duty parity: correlations ≈ 1 are **mechanical** (the proxy is that parity), so they "
        "prove nothing about MCX; the spot identity (basis 0) confirms the construction.",
        "- Mirror (third-party MCX closes, PROXY: provenance unverified) vs the same parity is the informative pair: "
        f"level correlation {_num(mir['level_corr'].min(), 3)}–{_num(mir['level_corr'].max(), 3)}, weekly returns "
        f"{_num(mir['weekly_logret_corr'].min(), 2)}–{_num(mir['weekly_logret_corr'].max(), 2)}, but daily returns only "
        f"{_num(mir['daily_logret_corr'].min(), 2)}–{_num(mir['daily_logret_corr'].max(), 2)} (MCX's evening close vs "
        f"the LME midday official) and a basis std of {_inr(mir['basis_std_inr_kg'].min() * 1000)}–"
        f"{_inr(mir['basis_std_inr_kg'].max() * 1000)}/t, larger than the {_inr(config.value('margin_threshold_inr_t'))}"
        "/t hurdle. A weekly parity decision can live with that; a daily hedge P&L cannot (Phase 3 factor b).",
        f"- Secondary ingot vs parity (Phase 0 evidence, BigMint ADC12 via AlCircle, {int(adc['n'])} dated prints "
        f"2023-12 → 2025-12, not 2022): median premium {_inr(adc['median_premium_inr_t'])}/t, std "
        f"{_inr(adc['std_premium_inr_t'])}; correlation of the premium with parity {_num(adc['corr_premium_parity'], 2)}; "
        f"short-run pass-through of parity into ADC12 {_num(adc['passthrough_slope_adc12_on_parity'], 2)}; against a "
        f"120-day trailing parity the premium is {_inr(adc['median_premium_vs_trailing120_inr_t'])} with std "
        f"{_inr(adc['std_premium_vs_trailing120_inr_t'])}. Secondary ingot is sticky: the constant-premium anchor "
        "overstates it when parity spikes and understates it in a crash — exactly the March/June asymmetry in §6.", "",
    ]


def _doc_closing(r: Results) -> list[str]:
    fw = pd.read_csv(PROCESSED_DIR / "freight_weekly.csv")
    cash = r.panel[r.panel["in_window"]].set_index("date")["lme_cash_usd_t"]
    peak_day = cash.idxmax()
    low_day = cash.loc[peak_day:].idxmin()
    fall = cash[low_day] / cash[peak_day] - 1
    band = r.cases_long[r.cases_long["in_window"] & r.cases_long["required"]].groupby(
        ["week_end", "grade", "lane"])["net_arb_inr_t"].agg(lambda x: x.max() - x.min())
    return [
        "## 12. Hindsight and provenance disclosure", "",
        "- **Freight levels are hindsight reconstructions** (CONTRACTS §4.3): the WCI shape is PROXY, the lane levels "
        "are ASSUMPTION calibrated to Container News anchors published up to ~7 months after the March 2022 weeks "
        f"(`freight_weekly.csv` notes, {len(fw)} weeks). Under CFR terms freight only moves the FOB memo; under FOB "
        "terms see §8(b).",
        "- **The lag-2 grade mix is a hindsight reconstruction**: DGCIS unit values for month m+2 were not published "
        "during month m. That is why §5a requires the point-in-time mix — itself an ASSUMPTION about the DGCIS release "
        "lag (verify PENDING).",
        "- Grade differentials, the anchor premium and conversion cost come from 2024–25 evidence applied to 2022 "
        "(ASSUMPTION). USD/INR is the ECB cross (PROXY for the RBI reference rate). MCX is the import-parity proxy.",
        "- The realised M+1 averages and every 'hindsight_' column are labelled and are never inputs to a flag.",
        "- No trade decision here uses data published after its week, except through the disclosed reconstructions "
        "above; `eligible_on` enforces the latest week_end ≤ trade date.", "",
        "## 13. What this does and doesn't tell you", "",
        "**Does:** it shows, per grade and lane, whether the published ingredients of a 2022 import margin — LME, the "
        "rupee, notified duties, container logistics, a secondary-ingot anchor and recovery physics — added up to more "
        "than a ₹5,000/t hurdle, which assumption moves that answer, and by how much a price, FX, freight or duty shock "
        "changes it. It gives Component 2 a rule it cannot bend after the fact: trade only where the base, the "
        "point-in-time grade mix and a higher conversion cost all agree.", "",
        "**Doesn't:** it is not a record of real 2022 margins. No 2022 scrap grade quote, secondary-ingot price or "
        "freight fixture was retrievable, so the level of the margin (tens of thousands of rupees in March, below zero "
        f"in July) is a model output, not a market fact; the spread between the required cases (median "
        f"{_inr(band.median())}/t, up to {_inr(band.max())}/t in a week) is the honest error bar. The weekly flag also "
        f"ignores execution: supplier availability, the {config.value('finance_days_jea_nsa')}–"
        f"{config.value('finance_days_usec_mun')} days between paying for the cargo and being paid for it in a window "
        f"when LME cash fell {abs(fall):.0%} from its {_dd(peak_day)} peak to its {_dd(low_day)} low, credit limits, and "
        "quality claims beyond the SPA schedule. A window being open is a licence to look for a trade, not evidence "
        "that the trade made money — that is Phase 3's job.", "",
        "## 14. Open issues", "",
        "1. MCX: replace the proxy with MCX bhavcopy closes (and re-run this page) — Table 1.3 then becomes a real "
        "LME–MCX basis study.",
        "2. Anchor: any dated 2022 ADC12/LM6 India print would replace the 2024–25 premium and settle whether the "
        "constant or the sticky anchor is closer to 2022 reality.",
        "3. Grade factors: a 2022 Zorba/Tense/Taint-Tabor CFR India assessment would remove the cross-period "
        "differential; a DGCIS release calendar would verify the point-in-time lag.",
        "4. `lme_cash_prompt_bdays` (T+2) is stated from convention (verify PENDING); LME holidays are not removed from "
        "the M+1 averaging days.",
        "5. The SPA contamination limit equals the priced composition by design; real contracts quote ISRI limits, "
        "which would make small excesses free for the supplier.", "",
    ]


def render_doc(r: Results) -> str:
    pflags = _panel_flags()
    lines: list[str] = []
    for part in (_doc_intro(r), _doc_formulas(r, pflags), _doc_worked_example(r, pflags), _doc_results(r),
                 _doc_band(r), _doc_grids(r), _doc_quality(r), _doc_term_structure(r), _doc_correlation(r),
                 _doc_closing(r)):
        lines += part
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    main()
