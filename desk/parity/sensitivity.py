"""Parity sensitivities: the required CONTRACTS §5 band, the Table 1.5 two-way grids and the Table 1.3 anchor study.

Why a band and not a flag. The base window flag stacks three weakly-evidenced inputs — a lag-2 DGCIS grade mix known
only with hindsight, a 2024–25 anchor premium applied to 2022, and hindsight-calibrated freight — so every case CONTRACTS
§5 lists is recomputed through the same ``desk.parity.model`` arithmetic with one input swapped (``overrides``), and the
open-week counts per case are what the parity result actually is.

Table 1.5 grids re-price BOTH legs of a floating trade at a shocked market (``model.market_shock_overrides`` re-derives
the MCX proxy anchor, the by-product credit, the duty base and finance from the shocked LME and USD/INR), so the grid
is the change in the parity margin on 1,000 MT, not the P&L of a fixed-price position (that is Phase 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from desk import config
from desk.parity import model
from desk.paths import INTERIM_DIR

MIRROR_CSV = INTERIM_DIR / "mcx_thirdparty_commoditieschart_2017_2022.csv"
ADC12_SUMMARY_CSV = INTERIM_DIR / "price_evidence" / "adc12_anchor_summary.csv"

GRID_TONNES_MT = 1000.0                                      # Table 1.5: P&L impact on 1,000 MT
LME_SHOCKS_PCT = tuple(range(-30, 11, 5))                    # −30 % … +10 % step 5 %
USDINR_LEVELS = tuple(float(x) for x in range(74, 83))       # 74 … 82 step 1
FREIGHT_SHOCKS_PCT = tuple(range(-40, 61, 20))               # −40 % … +60 % step 20 %
BCD_RATES_PCT = (0.0, 2.5, 5.0, 7.5, 10.0)
REFERENCE_TROUGH_MONTH = pd.Period("2022-06", freq="M")      # "mid-June trough": lowest base net arb among June weeks
FREIGHT_TERMS = {"FOB_desk_books_freight": True, "CFR_seller_books_freight": False}


@dataclass(frozen=True)
class Case:
    name: str
    group: str
    required: bool          # listed in CONTRACTS §5 "Required P1 sensitivities" (else informational)
    description: str
    overrides: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------------------------ external series
def load_mirror() -> pd.DataFrame:
    """Third-party MCX Aluminium mirror (commoditieschart.net, PROXY evidence; see docs/research/market_data_notes.md §6)."""
    return pd.read_csv(MIRROR_CSV, parse_dates=["date"]).set_index("date").sort_index()


def mirror_at(value_dates: pd.Series, week_ends: pd.Series, col: str, mirror: pd.DataFrame) -> pd.Series:
    """Latest mirror close on or before each value date (point in time; MCX and LME calendars differ)."""
    s = mirror[col].dropna()
    vals = [float(s.loc[:d].iloc[-1]) for d in pd.to_datetime(value_dates)]
    return pd.Series(vals, index=pd.DatetimeIndex(week_ends))


def sticky_anchor_spot_inr_kg(market: pd.DataFrame, panel: pd.DataFrame) -> pd.Series:
    """CONTRACTS §5 sticky variant: mean MCX spot over the trailing domestic_anchor_trailing_bdays LME days.

    The window ends on (and includes) the week's value date, the same day the base anchor is read.
    """
    n = int(config.value("domestic_anchor_trailing_bdays"))
    spot = panel.set_index("date")["mcx_al_spot_inr_kg"].sort_index()
    vals = []
    for d in pd.to_datetime(market["value_date"]):
        hist = spot.loc[:d]
        if len(hist) < n:
            raise ValueError(f"fewer than {n} panel days before {d.date()} for the sticky anchor")
        vals.append(float(hist.iloc[-n:].mean()))
    return pd.Series(vals, index=pd.DatetimeIndex(market["week_end"]))


# ------------------------------------------------------------------------------------------------ case list
def _per_grade(key_fmt: str, values: dict[str, float]) -> dict:
    return {key_fmt.format(g=g): v for g, v in values.items()}


def _diff_case_overrides(new_diff: dict[str, float]) -> dict:
    """Grade factor = registered lag-2 mix + a replacement differential."""
    mix = config.get("grade_factor_mix")
    over = {}
    for g, diff in new_diff.items():
        over[f"grade_factor_{g}"] = (lambda b, diff=diff:
                                     np.asarray([mix.at(d.date()) for d in pd.to_datetime(b["value_date"])]) + diff)
    return over


def build_cases(market: pd.DataFrame, panel: pd.DataFrame, mirror: pd.DataFrame) -> list[Case]:
    G = model.GRADES
    diffs = {g: float(config.value(f"grade_factor_diff_{g}")) for g in G}
    quart = {g: [float(v) for v in config.value(f"grade_factor_diff_quartiles_{g}")] for g in G}
    yields = {g: [float(v) for v in config.value(f"metal_yield_sensitivity_frac_{g}")] for g in G}
    heavies = [float(v) for v in config.value("heavies_net_value_sensitivity_frac")]
    base_prem = float(config.value("domestic_anchor_premium_inr_t"))
    base_conv = float(config.value("conversion_cost_inr_t"))

    cases = [Case("base", "base", True, "CONTRACTS §5 exactly as registered")]
    for key, label in [("grade_factor_mix_lag1", "mix_lag1"), ("grade_factor_mix_lag3", "mix_lag3"),
                       ("grade_factor_mix_pit", "mix_pit")]:
        cases.append(Case(label, "grade_mix", True, f"{key} + registered grade differential in place of the lag-2 mix",
                          model.mix_variant_overrides(key)))
    cases += [
        Case("grade_diff_q25", "grade_diff", True, "each grade differential at its evidence lower quartile",
             _diff_case_overrides({g: quart[g][0] for g in G})),
        Case("grade_diff_q75", "grade_diff", True, "each grade differential at its evidence upper quartile",
             _diff_case_overrides({g: quart[g][1] for g in G})),
        Case("grade_diff_minus_iqr", "grade_diff", True, "registered differential − one evidence IQR width",
             _diff_case_overrides({g: diffs[g] - (quart[g][1] - quart[g][0]) for g in G})),
        Case("grade_diff_plus_iqr", "grade_diff", True, "registered differential + one evidence IQR width",
             _diff_case_overrides({g: diffs[g] + (quart[g][1] - quart[g][0]) for g in G})),
    ]
    for prem in config.value("domestic_anchor_premium_sensitivity_inr_t"):
        tag = "base value" if float(prem) == base_prem else "sensitivity value"
        cases.append(Case(f"anchor_premium_{int(prem):+d}", "anchor_premium", True,
                          f"domestic_anchor_premium_inr_t = {int(prem):,} ({tag})",
                          {"domestic_anchor_premium_inr_t": float(prem)}))
    cases.append(Case("anchor_sticky_trailing", "anchor_sticky", True,
                      "anchor = trailing domestic_anchor_trailing_bdays-day mean MCX spot × 1000 + "
                      "domestic_anchor_premium_trailing_inr_t (both lanes)",
                      {"mcx_anchor_inr_kg": sticky_anchor_spot_inr_kg(market, panel),
                       "domestic_anchor_premium_inr_t": float(config.value("domestic_anchor_premium_trailing_inr_t"))}))
    m1 = mirror_at(market["value_date"], market["week_end"], "m1_close_inr_kg", mirror)
    m2 = mirror_at(market["value_date"], market["week_end"], "m2_close_inr_kg", mirror)
    cases.append(Case("anchor_mirror_m1", "anchor_mirror", True,
                      "anchor on the third-party MCX mirror nearest-contract close (PROXY) for both lanes",
                      {"mcx_anchor_inr_kg": m1}))
    cases.append(Case("anchor_mirror_lane_contract", "anchor_mirror", False,
                      "mirror M1 for JEA_NSA and mirror 2M for USEC_MUN (2M series partly stale, PROXY)",
                      {"mcx_anchor_inr_kg": lambda b: np.where(b["lane"] == "JEA_NSA",
                                                               b["week_end"].map(m1).to_numpy(),
                                                               b["week_end"].map(m2).to_numpy())}))
    for conv in config.value("conversion_cost_sensitivity_inr_t_ingot"):
        tag = "base value" if float(conv) == base_conv else "sensitivity value"
        cases.append(Case(f"conversion_{int(conv)}", "conversion", True,
                          f"conversion_cost_inr_t = {int(conv):,} per t ingot ({tag})",
                          {"conversion_cost_inr_t": float(conv)}))
    cases += [
        Case("metal_yield_low", "recovery", True, "metal yield at the low end of each grade's registered range",
             _per_grade("metal_yield_frac_{g}", {g: yields[g][0] for g in G})),
        Case("metal_yield_high", "recovery", True, "metal yield at the high end of each grade's registered range",
             _per_grade("metal_yield_frac_{g}", {g: yields[g][1] for g in G})),
        Case(f"heavies_value_{heavies[0]:g}", "heavies", True,
             f"heavies_net_value_frac_of_lme_al = {heavies[0]:g} (Zorba only)",
             {"heavies_net_value_frac_of_lme_al": heavies[0]}),
        Case(f"heavies_value_{heavies[1]:g}", "heavies", True,
             f"heavies_net_value_frac_of_lme_al = {heavies[1]:g} (Zorba only)",
             {"heavies_net_value_frac_of_lme_al": heavies[1]}),
        Case("goods_fx_spot", "goods_fx", False, "goods paid at market spot usdinr instead of the 1M forward",
             {"usdinr_goods": lambda b: b["usdinr"].to_numpy(dtype=float)}),
        Case("pit_mix_and_conv18k", "informational", False,
             "§5a cases 2 and 3 applied together (stricter than the rule, which requires each separately)",
             {**model.mix_variant_overrides(model.PIT_MIX_KEY),
              "conversion_cost_inr_t": model.conversion_step_above_base()}),
        Case("tt_spec_factor_plus", "informational", False,
             "Taint/Tabor grade factor + grade_factor_taint_tabor_spec_uplift (MASTER_SPEC 88–92% guide)",
             {"grade_factor_taint_tabor": lambda b: b["grade_factor"].to_numpy(dtype=float)
              + float(config.value("grade_factor_taint_tabor_spec_uplift"))}),
    ]
    return cases


def sensitivity_cases_table(inputs: pd.DataFrame, cases: list[Case]) -> pd.DataFrame:
    """Long table: week_end, grade, lane, in_window, case, case_group, required, net_arb_inr_t, window_open."""
    frames = []
    for c in cases:
        res = model.compute(model.apply_overrides(inputs, c.overrides))
        f = res[["week_end", "grade", "lane", "in_window"]].copy()
        f["case"] = c.name
        f["case_group"] = c.group
        f["required"] = c.required
        f["net_arb_inr_t"] = res["net_arb_inr_t"].values
        f["window_open"] = res["window_open"].values
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def sensitivity_summary(cases_long: pd.DataFrame, parity: pd.DataFrame) -> pd.DataFrame:
    """Open-week counts per case per grade-lane over in-window weeks, with flips vs base; §5a rule appended."""
    win = cases_long[cases_long["in_window"]]
    base = win[win["case"] == "base"].set_index(["week_end", "grade", "lane"])["window_open"]
    rows = []
    order = list(dict.fromkeys(win["case"]))
    elig = parity[parity["in_window"]].set_index(["week_end", "grade", "lane"])
    for case in order + ["trade_eligible_5a"]:
        if case == "trade_eligible_5a":
            sub = elig.reset_index().assign(window_open=elig["trade_eligible"].values,
                                            net_arb_inr_t=elig["net_arb_inr_t"].values,
                                            case_group="section_5a_rule", required=True)
        else:
            sub = win[win["case"] == case]
        for g in model.GRADES:
            for l in model.LANES:
                s = sub[(sub["grade"] == g) & (sub["lane"] == l)].sort_values("week_end")
                flags = s.set_index(["week_end", "grade", "lane"])["window_open"]
                open_weeks = s.loc[s["window_open"], "week_end"]
                rows.append({
                    "case": case, "case_group": s["case_group"].iloc[0], "required": bool(s["required"].iloc[0]),
                    "grade": g, "lane": l, "n_weeks_in_window": int(len(s)), "open_weeks": int(s["window_open"].sum()),
                    "flips_vs_base": int((flags != base.reindex(flags.index)).sum()),
                    "first_open_week": open_weeks.min().date().isoformat() if len(open_weeks) else "",
                    "last_open_week": open_weeks.max().date().isoformat() if len(open_weeks) else "",
                    "net_arb_min_inr_t": float(s["net_arb_inr_t"].min()),
                    "net_arb_median_inr_t": float(s["net_arb_inr_t"].median()),
                    "net_arb_max_inr_t": float(s["net_arb_inr_t"].max()),
                })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------ reference cases
@dataclass(frozen=True)
class RefCase:
    ref: str
    week_end: pd.Timestamp
    grade: str
    lane: str
    rule: str


def reference_cases(parity: pd.DataFrame) -> list[RefCase]:
    """Declared rules: (1) first trade-eligible in-window case — earliest week, then GRADES then LANES order;
    (2) the same grade-lane's lowest base net-arb week among weeks ending in REFERENCE_TROUGH_MONTH."""
    p = parity.copy()
    p["_g"] = p["grade"].map({g: i for i, g in enumerate(model.GRADES)})
    p["_l"] = p["lane"].map({l: i for i, l in enumerate(model.LANES)})
    elig = p[p["in_window"] & p["trade_eligible"]].sort_values(["week_end", "_g", "_l"], kind="mergesort")
    if elig.empty:
        raise ValueError("no trade-eligible in-window case: Table 1.5 reference case undefined")
    first = elig.iloc[0]
    same = p[(p["grade"] == first["grade"]) & (p["lane"] == first["lane"])
             & (p["week_end"].dt.to_period("M") == REFERENCE_TROUGH_MONTH)]
    trough = same.sort_values(["net_arb_inr_t", "week_end"]).iloc[0]
    other_lane = [l for l in model.LANES if l != first["lane"]][0]
    return [
        RefCase("first_eligible", first["week_end"], first["grade"], first["lane"],
                "first trade-eligible in-window case (earliest week, then grade, then lane order)"),
        RefCase("june_trough", trough["week_end"], trough["grade"], trough["lane"],
                f"lowest base net arb among {REFERENCE_TROUGH_MONTH} weeks for the same grade-lane"),
        # Added in the Phase 1-3 review: §8 quoted a freight-scale number on the long lane that no published CSV
        # contained, so the reader could not check the one figure that gives freight risk its size. The long-lane
        # counterpart of `first_eligible` is now a declared reference case and both grids carry it.
        RefCase("first_eligible_long_lane", first["week_end"], first["grade"], other_lane,
                "the long-lane counterpart of `first_eligible`: same week and grade, the other lane"),
    ]


def _ref_inputs(inputs: pd.DataFrame, ref: RefCase) -> pd.DataFrame:
    sub = inputs[(inputs["week_end"] == ref.week_end) & (inputs["grade"] == ref.grade) & (inputs["lane"] == ref.lane)]
    return sub.reset_index(drop=True)


# ------------------------------------------------------------------------------------------------ Table 1.5 grids
def lme_fx_grid(inputs: pd.DataFrame, refs: list[RefCase]) -> pd.DataFrame:
    rows = []
    for ref in refs:
        sub = _ref_inputs(inputs, ref)
        base = model.compute(sub).iloc[0]
        base_fx = float(sub["usdinr"].iloc[0])
        for fx, is_base_fx in [(x, False) for x in USDINR_LEVELS] + [(base_fx, True)]:
            for pct in LME_SHOCKS_PCT:
                shocked = model.compute(model.apply_overrides(
                    sub, model.market_shock_overrides(lme_shock_frac=pct / 100.0, usdinr_level=fx))).iloc[0]
                rows.append({
                    "ref_case": ref.ref, "week_end": ref.week_end, "grade": ref.grade, "lane": ref.lane,
                    "lme_shock_pct": pct, "usdinr": round(fx, 4), "usdinr_is_base": is_base_fx,
                    "lme_3m_shocked_usd_t": float(sub["lme_3m_usd_t"].iloc[0]) * (1 + pct / 100.0),
                    "net_arb_base_inr_t": float(base["net_arb_inr_t"]),
                    "net_arb_shocked_inr_t": float(shocked["net_arb_inr_t"]),
                    "window_open_shocked": bool(shocked["window_open"]),
                    "pnl_impact_1000mt_inr": (float(shocked["net_arb_inr_t"]) - float(base["net_arb_inr_t"]))
                    * GRID_TONNES_MT,
                })
    return pd.DataFrame(rows)


def freight_duty_grid(inputs: pd.DataFrame, refs: list[RefCase]) -> pd.DataFrame:
    rows = []
    for ref in refs:
        sub = _ref_inputs(inputs, ref)
        base = model.compute(sub).iloc[0]
        for terms, on_buyer in FREIGHT_TERMS.items():
            for pct in FREIGHT_SHOCKS_PCT:
                for bcd in BCD_RATES_PCT:
                    over = model.market_shock_overrides(freight_shock_frac=pct / 100.0, freight_on_buyer=on_buyer)
                    over["bcd_scrap_hs7602"] = bcd / 100.0
                    shocked = model.compute(model.apply_overrides(sub, over)).iloc[0]
                    rows.append({
                        "ref_case": ref.ref, "week_end": ref.week_end, "grade": ref.grade, "lane": ref.lane,
                        "freight_terms": terms, "freight_shock_pct": pct, "bcd_rate_pct": bcd,
                        "freight_shocked_usd_t": float(shocked["freight_usd_t"]),
                        "net_arb_base_inr_t": float(base["net_arb_inr_t"]),
                        "net_arb_shocked_inr_t": float(shocked["net_arb_inr_t"]),
                        "window_open_shocked": bool(shocked["window_open"]),
                        "pnl_impact_1000mt_inr": (float(shocked["net_arb_inr_t"]) - float(base["net_arb_inr_t"]))
                        * GRID_TONNES_MT,
                    })
    return pd.DataFrame(rows)


def grid_wide(grid: pd.DataFrame, row_keys: list[str], col_key: str, col_label: Callable[[pd.Series], str]
              ) -> pd.DataFrame:
    g = grid.copy()
    g["_col"] = g.apply(col_label, axis=1)
    wide = g.pivot_table(index=row_keys, columns="_col", values="pnl_impact_1000mt_inr", sort=False)
    cols = list(dict.fromkeys(g["_col"]))
    wide = wide[cols].reset_index()
    wide.columns.name = None
    return wide


def lme_fx_wide(grid: pd.DataFrame) -> pd.DataFrame:
    w = grid_wide(grid, ["ref_case", "week_end", "grade", "lane", "lme_shock_pct"], "usdinr",
                  lambda r: f"usdinr_base_{r['usdinr']:.4f}" if r["usdinr_is_base"] else f"usdinr_{r['usdinr']:.0f}")
    return w


def freight_duty_wide(grid: pd.DataFrame) -> pd.DataFrame:
    return grid_wide(grid, ["ref_case", "week_end", "grade", "lane", "freight_terms", "freight_shock_pct"],
                     "bcd_rate_pct", lambda r: f"bcd_{r['bcd_rate_pct']:g}pct")


# ------------------------------------------------------------------------------------------------ Table 1.3
def duty_paid_cash_parity_inr_kg(panel: pd.DataFrame) -> pd.Series:
    duty = 1.0 + float(config.value("bcd_primary_al_hs7601")) * (1.0 + float(config.value("sws_rate_on_bcd")))
    p = panel.set_index("date")
    return p["lme_cash_usd_t"] * p["usdinr"] / 1000.0 * duty


def _pair_stats(a: pd.Series, b: pd.Series, start=None, end=None) -> dict[str, float]:
    """Same construction as desk.data.mcx.proxy_vs_observed: common days, log returns, W-FRI last."""
    j = pd.concat({"a": a, "b": b}, axis=1, join="inner", sort=True).loc[start:end].dropna()
    r = np.log(j).diff().dropna()
    wk = np.log(j.resample(model.WEEK_FREQ).last()).diff().dropna()
    basis = j["a"] - j["b"]
    return {
        "n_common_days": float(len(j)),
        "level_corr": float(j["a"].corr(j["b"])),
        "daily_logret_corr": float(r["a"].corr(r["b"])),
        "weekly_logret_corr": float(wk["a"].corr(wk["b"])),
        "basis_mean_inr_kg": float(basis.mean()),
        "basis_std_inr_kg": float(basis.std()),
        "basis_mean_inr_t": float(basis.mean() * 1000.0),
        "daily_vol_a": float(r["a"].std()),
        "daily_vol_b": float(r["b"].std()),
    }


ANCHOR_PAIRS = [
    ("proxy_m1_vs_duty_paid_parity", "mcx_al_m1_inr_kg (panel PROXY)", "LME cash × USDINR × (1 + BCD 7601 × (1 + SWS))",
     "PROXY vs PROXY: the proxy IS this parity times carry, so these statistics are mechanical"),
    ("proxy_spot_vs_duty_paid_parity", "mcx_al_spot_inr_kg (panel PROXY)", "duty-paid LME cash parity",
     "identity check: premium mcx_domestic_premium_inr_kg = 0, so basis must be 0"),
    ("mirror_m1_vs_duty_paid_parity", "third-party mirror nearest contract (PROXY)", "duty-paid LME cash parity",
     "the informative pair: observed-style MCX closes against the parity the anchor is built on"),
    ("mirror_m1_vs_proxy_m1", "third-party mirror nearest contract (PROXY)", "mcx_al_m1_inr_kg (panel PROXY)",
     "basis the parity anchor ignores; reproduces docs/research/market_data_notes.md §6.4"),
    ("mirror_m2_vs_proxy_m2", "third-party mirror 2M contract (PROXY, partly stale)", "mcx_al_m2_inr_kg (panel PROXY)",
     "USEC_MUN anchor contract; mirror 2M has stale days"),
]


def anchor_correlation(panel: pd.DataFrame, mirror: pd.DataFrame) -> pd.DataFrame:
    from desk import WINDOW_END, WINDOW_START

    p = panel.set_index("date")
    parity = duty_paid_cash_parity_inr_kg(panel)
    series = {
        "proxy_m1_vs_duty_paid_parity": (p["mcx_al_m1_inr_kg"], parity),
        "proxy_spot_vs_duty_paid_parity": (p["mcx_al_spot_inr_kg"], parity),
        "mirror_m1_vs_duty_paid_parity": (mirror["m1_close_inr_kg"], parity),
        "mirror_m1_vs_proxy_m1": (mirror["m1_close_inr_kg"], p["mcx_al_m1_inr_kg"]),
        "mirror_m2_vs_proxy_m2": (mirror["m2_close_inr_kg"], p["mcx_al_m2_inr_kg"]),
    }
    rows = []
    samples = [("window_2022-03-01_2022-08-31", pd.Timestamp(WINDOW_START), pd.Timestamp(WINDOW_END)),
               ("panel_2018-01-02_2022-12-30", None, None)]
    for name, a_label, b_label, note in ANCHOR_PAIRS:
        a, b = series[name]
        for sample, start, end in samples:
            for metric, val in _pair_stats(a, b, start, end).items():
                rows.append({"sample": sample, "pair": name, "series_a": a_label, "series_b": b_label,
                             "metric": metric, "value": val, "flag": "PROXY", "note": note})
    adc = pd.read_csv(ADC12_SUMMARY_CSV).iloc[0]
    evidence = [
        ("n", "count"), ("median_premium_inr_t", "inr_per_mt"), ("mean_premium_inr_t", "inr_per_mt"),
        ("std_premium_inr_t", "inr_per_mt"), ("corr_premium_parity", "corr"),
        ("passthrough_slope_adc12_on_parity", "frac"), ("median_premium_vs_trailing120_inr_t", "inr_per_mt"),
        ("std_premium_vs_trailing120_inr_t", "inr_per_mt"),
    ]
    sample = f"adc12_{adc['first']}_{adc['last']}"
    for metric, _unit in evidence:
        rows.append({"sample": sample, "pair": "adc12_vs_duty_paid_cash_parity",
                     "series_a": "BigMint ADC12 ex-Delhi, non-OEM basis (via AlCircle)",
                     "series_b": "duty-paid LME cash parity, day before publication", "metric": metric,
                     "value": float(adc[metric]), "flag": "PROXY",
                     "note": "Phase 0 evidence (data/interim/price_evidence/adc12_anchor_summary.csv); 2023–25, not 2022"})
    return pd.DataFrame(rows)
