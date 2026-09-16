"""Import parity model — CONTRACTS §5 per MT of scrap, vectorised over (week_end × grade × lane).

Why this shape. Table 3 row 1.4 asks for one open/closed flag per week, but the Phase 0 review showed the flag is only
as good as its least-certain input (lagged grade mix, anchor premium, reconstructed freight). So the model is split in
two steps that every sensitivity, the Excel workbook and the tests can reuse:

1. ``build_inputs`` resolves every §5 input for every row into one flat frame: market columns from the week's last
   panel day and parameters from the register evaluated on that day. Grade- and lane-specific canonical keys
   (``grade_factor_zorba``, ``port_cf_charges_inr_t_nsa`` …) become generic input columns (``grade_factor``,
   ``port_cf_charges_inr_t``) so the arithmetic is written once.
2. ``compute`` applies §5 line by line to that frame. It never reads the register or the panel itself.

Overrides (sensitivities, stresses, tests) are applied between the two steps. An override key is either an input
column name (applies to every row) or a canonical register key (applies to the rows it belongs to, e.g.
``grade_factor_tense`` only to Tense rows); its value is a scalar, a Series indexed by ``week_end``, or a callable
``f(base_inputs) -> array`` evaluated on the *un-overridden* inputs so dependent series are always re-derived from the
same base (see ``market_shock_overrides``). Nothing is cached in a mutable form: an override never alters the base.

Goods FX (CONTRACTS §5 leaves the choice to P1): goods are paid at the panel column named by
``parity_goods_fx_basis`` (parity.yaml; base = ``usdinr_fwd_1m``), because the sight-LC payment is ~1 month after the
decision and the anchor is itself a forward (MCX contract matched to the sale date). Spot is sensitivity case
``goods_fx_spot`` (desk.parity.sensitivity).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from desk import WINDOW_END, WINDOW_START, config, units
from desk.paths import PROCESSED_DIR, TABLES_DIR

# ------------------------------------------------------------------------------------------------ model structure
GRADES: tuple[str, ...] = ("zorba", "taint_tabor", "tense")
LANES: tuple[str, ...] = ("JEA_NSA", "USEC_MUN")
FIRST_WEEK_END = dt.date(2022, 1, 7)   # context weeks before the window (eligibility look-ups, charts)
LAST_WEEK_END = dt.date(2022, 10, 28)  # last Friday before HORIZON_END
WEEK_FREQ = "W-FRI"
DAYS_PER_WEEK = 7

PANEL_CSV = PROCESSED_DIR / "market_daily.csv"
PARITY_CSV = TABLES_DIR / "parity_weekly.csv"


@dataclass(frozen=True)
class LaneSpec:
    box: str                 # container size used on the lane (logistics.yaml payload keys)
    port: str                # port-charge key suffix
    finance_key: str
    freight_col: str         # panel freight column (USD/MT at base payload)
    mcx_col: str             # MCX contract matched to the lane's domestic sale date (CONTRACTS §5 anchor)
    mcx_contract: str
    psic_key: str            # register boolean: does this origin/port combination need a PSIC?


LANE_SPECS: dict[str, LaneSpec] = {
    "JEA_NSA": LaneSpec("20ft", "nsa", "finance_days_jea_nsa", "freight_jea_nsa_usd_t", "mcx_al_m1_inr_kg", "M1",
                        "psic_required_uae_origin"),
    "USEC_MUN": LaneSpec("40ft", "mun", "finance_days_usec_mun", "freight_usec_mun_usd_t", "mcx_al_m2_inr_kg", "M2",
                         "psic_required_safe_origin_designated_port"),
}

KEY_COLUMNS = ["week_end", "value_date", "grade", "lane", "in_window"]
# Resolved inputs (after the keys). Market columns first, then parameters in §5 order.
MARKET_INPUTS = ["lme_3m_usd_t", "lme_cash_usd_t", "usdinr", "usdinr_goods", "customs_usdinr_import",
                 "freight_base_usd_t", "mcx_anchor_inr_kg", "mcx_al_spot_inr_kg"]
PARAM_INPUTS = ["grade_factor", "container_payload_base_mt", "container_payload_grade_mt",
                "container_payload_20ft_grade_mt", "insurance_rate", "insured_value_uplift", "bcd_scrap_hs7602",
                "sws_rate_on_bcd", "igst_rate_hs7602", "port_cf_charges_inr_t", "psic_applies",
                "psic_cost_usd_per_box", "finance_days", "wc_rate_inr_pa", "igst_credit_lag_days",
                "igst_itc_available", "moisture_frac", "contamination_frac", "metal_yield_frac", "heavies_frac",
                "heavies_net_value_frac_of_lme_al", "domestic_anchor_premium_inr_t", "conversion_cost_inr_t",
                "margin_threshold_inr_t"]
LABEL_INPUTS = ["customs_fx_src", "mcx_contract", "freight_src"]
INPUT_COLUMNS = MARKET_INPUTS + PARAM_INPUTS

# Canonical register key template -> resolved input column. {g} = grade, {box} = 20ft|40ft, {port} = nsa|mun.
CANONICAL_TEMPLATES: dict[str, str] = {
    "grade_factor_{g}": "grade_factor",
    "container_payload_mt_{box}": "container_payload_base_mt",
    "container_payload_mt_{box}_{g}": "container_payload_grade_mt",
    "container_payload_mt_20ft_{g}": "container_payload_20ft_grade_mt",
    "insurance_rate": "insurance_rate",
    "insured_value_uplift": "insured_value_uplift",
    "customs_usdinr_import": "customs_usdinr_import",
    "bcd_scrap_hs7602": "bcd_scrap_hs7602",
    "sws_rate_on_bcd": "sws_rate_on_bcd",
    "igst_rate_hs7602": "igst_rate_hs7602",
    "port_cf_charges_inr_t_{port}": "port_cf_charges_inr_t",
    "psic_cost_usd_per_box": "psic_cost_usd_per_box",
    "{finance_key}": "finance_days",
    "wc_rate_inr_pa": "wc_rate_inr_pa",
    "igst_credit_lag_days": "igst_credit_lag_days",
    "igst_itc_available": "igst_itc_available",
    "moisture_frac_{g}": "moisture_frac",
    "contamination_frac_{g}": "contamination_frac",
    "metal_yield_frac_{g}": "metal_yield_frac",
    "heavies_frac_{g}": "heavies_frac",
    "heavies_net_value_frac_of_lme_al": "heavies_net_value_frac_of_lme_al",
    "domestic_anchor_premium_inr_t": "domestic_anchor_premium_inr_t",
    "conversion_cost_inr_t": "conversion_cost_inr_t",
    "margin_threshold_inr_t": "margin_threshold_inr_t",
}

LINE_ITEMS = ["cfr_usd_t", "payload_scale", "freight_usd_t", "fob_usd_t", "insurance_usd_t", "cif_usd_t",
              "av_customs_inr_t", "goods_inr_t", "bcd_inr_t", "sws_inr_t", "igst_inr_t", "port_inr_t",
              "finance_inr_t", "igst_finance_inr_t", "landed_inr_t", "recovery_frac", "anchor_inr_t",
              "byproduct_inr_t", "conversion_inr_t", "net_arb_inr_t", "margin_threshold_inr_t", "window_open"]
CASE_FLAGS = ["open_base", "open_pit_mix", "open_conv18k", "trade_eligible", "open_pit_conv18k",
              "trade_eligible_pit"]

# CONTRACTS §5a — declared ex ante; the conversion case is "one grid step above base" and the contract names 18,000.
SECTION_5A_CONVERSION_INR_T_INGOT = 18000
PIT_MIX_KEY = "grade_factor_mix_pit"

Override = Any  # scalar | pd.Series indexed by week_end | Callable[[pd.DataFrame], array-like]


# ------------------------------------------------------------------------------------------------ calendar / market
def week_ends(first: dt.date = FIRST_WEEK_END, last: dt.date = LAST_WEEK_END) -> pd.DatetimeIndex:
    return pd.date_range(first, last, freq=WEEK_FREQ)


def load_panel() -> pd.DataFrame:
    return pd.read_csv(PANEL_CSV, parse_dates=["date"])


def weekly_market(panel: pd.DataFrame | None = None, weeks: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """One row per W-FRI week_end: the panel row of the week's last panel day (CONTRACTS §3) + in_window flag.

    A week is in the window when any of its seven days (Sat → Fri) falls inside WINDOW_START..WINDOW_END.
    """
    panel = load_panel() if panel is None else panel
    weeks = week_ends() if weeks is None else weeks
    days = panel.set_index("date").sort_index()
    rows = []
    for we in weeks:
        start = we - pd.Timedelta(days=DAYS_PER_WEEK - 1)
        sub = days.loc[start:we]
        if sub.empty:
            raise ValueError(f"no panel day in the week ending {we.date()}")
        row = sub.iloc[-1].copy()
        row["week_end"] = we
        row["value_date"] = sub.index[-1]
        row["in_window"] = bool(start.date() <= WINDOW_END and we.date() >= WINDOW_START)
        rows.append(row)
    out = pd.DataFrame(rows).reset_index(drop=True)
    return out


def customs_fx(value_dates: pd.Series, market_usdinr: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Customs notified USD import rate in force on each date; documented markup fallback outside the notifications."""
    p = config.get("customs_usdinr_import")
    first, last = p.path[0][0], p.path[-1][0]
    valid_to = last + dt.timedelta(days=int(config.value("customs_fx_notification_validity_days")))
    markup = float(config.value("customs_fx_markup_frac"))
    rates, srcs = [], []
    for d, mkt in zip(pd.to_datetime(value_dates), market_usdinr):
        day = d.date()
        if first <= day <= valid_to:
            rates.append(float(p.at(day)))
            srcs.append("CBIC_NOTIFIED")
        else:
            rates.append(float(mkt) * (1.0 + markup))
            srcs.append("MARKUP_FALLBACK")
    return np.asarray(rates), np.asarray(srcs, dtype=object)


# ------------------------------------------------------------------------------------------------ inputs
def _param_at(key: str, dates: pd.Series) -> np.ndarray:
    p = config.get(key)
    if not p.is_path:
        return np.full(len(dates), p.value, dtype=object if isinstance(p.value, (bool, str)) else float)
    return np.asarray([float(p.at(d.date())) for d in pd.to_datetime(dates)], dtype=float)


def _canonical_key(template: str, grade: str, lane: str) -> str:
    spec = LANE_SPECS[lane]
    return template.format(g=grade, box=spec.box, port=spec.port, finance_key=spec.finance_key)


def build_inputs(market: pd.DataFrame | None = None) -> pd.DataFrame:
    """Resolve every §5 input for every (week_end, grade, lane) row, in week → grade → lane order."""
    market = weekly_market() if market is None else market
    goods_fx_col = str(config.value("parity_goods_fx_basis"))
    frames = []
    for grade in GRADES:
        for lane in LANES:
            spec = LANE_SPECS[lane]
            f = pd.DataFrame({
                "week_end": market["week_end"].values,
                "value_date": market["value_date"].values,
                "grade": grade,
                "lane": lane,
                "in_window": market["in_window"].astype(bool).values,
            })
            f["lme_3m_usd_t"] = market["lme_3m_usd_t"].astype(float).values
            f["lme_cash_usd_t"] = market["lme_cash_usd_t"].astype(float).values
            f["usdinr"] = market["usdinr"].astype(float).values
            f["usdinr_goods"] = market[goods_fx_col].astype(float).values
            rate, src = customs_fx(market["value_date"], market["usdinr"])
            f["customs_usdinr_import"] = rate
            f["freight_base_usd_t"] = market[spec.freight_col].astype(float).values
            f["mcx_anchor_inr_kg"] = market[spec.mcx_col].astype(float).values
            f["mcx_al_spot_inr_kg"] = market["mcx_al_spot_inr_kg"].astype(float).values
            for template, col in CANONICAL_TEMPLATES.items():
                if col == "customs_usdinr_import":
                    continue
                f[col] = _param_at(_canonical_key(template, grade, lane), market["value_date"])
            f["psic_applies"] = bool(config.value(spec.psic_key))
            f["customs_fx_src"] = src
            f["mcx_contract"] = spec.mcx_contract
            f["freight_src"] = market["freight_src"].values
            frames.append(f)
    out = pd.concat(frames, ignore_index=True)
    out["_g"] = out["grade"].map({g: i for i, g in enumerate(GRADES)})
    out["_l"] = out["lane"].map({l: i for i, l in enumerate(LANES)})
    out = out.sort_values(["week_end", "_g", "_l"], kind="mergesort").drop(columns=["_g", "_l"])
    out = out.reset_index(drop=True)
    if out[["freight_base_usd_t", "mcx_anchor_inr_kg", "lme_3m_usd_t", "usdinr_goods"]].isna().any().any():
        raise ValueError("missing market input in a parity week (freight / MCX / LME / FX)")
    for col in ("psic_applies", "igst_itc_available"):
        out[col] = out[col].astype(bool)
    return out[KEY_COLUMNS + INPUT_COLUMNS + LABEL_INPUTS]


def _resolve_override_targets(key: str, inputs: pd.DataFrame) -> list[tuple[str, np.ndarray]]:
    """Map an override key to [(input column, boolean row mask), ...] (one register key can feed two columns)."""
    if key in inputs.columns and key not in KEY_COLUMNS:
        return [(key, np.ones(len(inputs), dtype=bool))]
    targets: dict[str, np.ndarray] = {}
    for template, col in CANONICAL_TEMPLATES.items():
        for g in GRADES:
            for l in LANES:
                if _canonical_key(template, g, l) == key:
                    mask = ((inputs["grade"] == g) & (inputs["lane"] == l)).to_numpy()
                    targets[col] = targets.get(col, np.zeros(len(inputs), dtype=bool)) | mask
    if not targets:
        raise KeyError(f"override key {key!r} is neither a parity input column nor a canonical §5 register key")
    return list(targets.items())


def apply_overrides(inputs: pd.DataFrame, overrides: Mapping[str, Override] | None) -> pd.DataFrame:
    """Return a NEW inputs frame with overrides applied; callables see the un-overridden `inputs`."""
    if not overrides:
        return inputs
    base = inputs
    out = inputs.copy()
    for key, val in overrides.items():
        targets = _resolve_override_targets(key, base)
        if callable(val):
            new = np.asarray(val(base))
            if new.shape == ():
                new = np.full(len(base), new)
        elif isinstance(val, pd.Series):
            s = val.copy()
            s.index = pd.DatetimeIndex(s.index)
            new = base["week_end"].map(s).to_numpy()
        else:
            new = np.full(len(base), val, dtype=object if isinstance(val, (bool, str)) else float)
        for col, mask in targets:
            if pd.isna(np.asarray(new, dtype=object)[mask]).any():
                raise ValueError(f"override {key!r} leaves missing values in {col}")
            vals = out[col].to_numpy(copy=True)
            if vals.dtype != object and np.asarray(new).dtype == object:
                vals = vals.astype(object)
            vals[mask] = np.asarray(new)[mask]
            out[col] = vals
    for col in ("psic_applies", "igst_itc_available"):
        out[col] = out[col].astype(bool)
    return out


# ------------------------------------------------------------------------------------------------ §5 arithmetic
def compute(inputs: pd.DataFrame) -> pd.DataFrame:
    """CONTRACTS §5, line by line. Returns keys + line items (no register or panel access here)."""
    x = inputs
    num = {c: x[c].astype(float) for c in INPUT_COLUMNS if c not in ("psic_applies", "igst_itc_available")}
    out = x[KEY_COLUMNS].copy()

    cfr = num["lme_3m_usd_t"] * num["grade_factor"]
    payload_scale = num["container_payload_base_mt"] / num["container_payload_grade_mt"]
    freight = num["freight_base_usd_t"] * payload_scale
    fob = cfr - freight
    insurance = num["insurance_rate"] * num["insured_value_uplift"] * cfr
    cif = cfr + insurance
    av = units.usd_t_to_inr_t(cif, num["customs_usdinr_import"])
    goods = units.usd_t_to_inr_t(cif, num["usdinr_goods"])
    bcd = av * num["bcd_scrap_hs7602"]
    sws = bcd * num["sws_rate_on_bcd"]
    igst = (av + bcd + sws) * num["igst_rate_hs7602"]
    psic = np.where(x["psic_applies"].to_numpy(),
                    units.usd_t_to_inr_t(num["psic_cost_usd_per_box"], num["usdinr"])
                    / num["container_payload_20ft_grade_mt"], 0.0)
    port = num["port_cf_charges_inr_t"] * payload_scale + psic
    finance = units.simple_interest(goods + bcd + sws, num["wc_rate_inr_pa"], num["finance_days"])
    igst_finance = units.simple_interest(igst, num["wc_rate_inr_pa"], num["igst_credit_lag_days"])
    landed = goods + bcd + sws + port + finance + igst_finance + np.where(x["igst_itc_available"].to_numpy(), 0.0, igst)
    recovery = (1 - num["moisture_frac"]) * (1 - num["contamination_frac"]) * num["metal_yield_frac"]
    anchor = units.inr_kg_to_inr_t(num["mcx_anchor_inr_kg"]) + num["domestic_anchor_premium_inr_t"]
    byproduct = ((1 - num["moisture_frac"]) * num["heavies_frac"] * num["heavies_net_value_frac_of_lme_al"]
                 * units.usd_t_to_inr_t(num["lme_3m_usd_t"], num["usdinr"]))
    conversion = num["conversion_cost_inr_t"] * recovery
    net_arb = anchor * recovery + byproduct - landed - conversion

    for name, val in [("cfr_usd_t", cfr), ("payload_scale", payload_scale), ("freight_usd_t", freight),
                      ("fob_usd_t", fob), ("insurance_usd_t", insurance), ("cif_usd_t", cif),
                      ("av_customs_inr_t", av), ("goods_inr_t", goods), ("bcd_inr_t", bcd), ("sws_inr_t", sws),
                      ("igst_inr_t", igst), ("port_inr_t", port), ("finance_inr_t", finance),
                      ("igst_finance_inr_t", igst_finance), ("landed_inr_t", landed), ("recovery_frac", recovery),
                      ("anchor_inr_t", anchor), ("byproduct_inr_t", byproduct), ("conversion_inr_t", conversion),
                      ("net_arb_inr_t", net_arb), ("margin_threshold_inr_t", num["margin_threshold_inr_t"])]:
        out[name] = np.asarray(val, dtype=float)
    out["window_open"] = out["net_arb_inr_t"] > out["margin_threshold_inr_t"]
    out["net_arb_usd_t"] = units.inr_t_to_usd_t(out["net_arb_inr_t"], num["usdinr"])
    return out


def evaluate(overrides: Mapping[str, Override] | None = None, inputs: pd.DataFrame | None = None) -> pd.DataFrame:
    """Inputs (+ overrides) → §5 line items. The convenience entry point for sensitivities."""
    base = build_inputs() if inputs is None else inputs
    return compute(apply_overrides(base, overrides))


# ------------------------------------------------------------------------------------------------ §5a cases
def mix_variant_overrides(mix_key: str) -> dict[str, Override]:
    """Grade factors rebuilt from another all-grade mix path + the registered grade differential (scrap_grades.yaml)."""
    over: dict[str, Override] = {}
    for g in GRADES:
        diff = float(config.value(f"grade_factor_diff_{g}"))
        mix = config.get(mix_key)
        over[f"grade_factor_{g}"] = (lambda base, mix=mix, diff=diff:
                                     np.asarray([mix.at(d.date()) for d in pd.to_datetime(base["value_date"])],
                                                dtype=float) + diff)
    return over


def conversion_step_above_base() -> float:
    base = float(config.value("conversion_cost_inr_t"))
    grid = sorted(float(v) for v in config.value("conversion_cost_sensitivity_inr_t_ingot"))
    above = [v for v in grid if v > base]
    if not above:
        raise ValueError("conversion_cost_sensitivity_inr_t_ingot has no value above the base")
    if above[0] != SECTION_5A_CONVERSION_INR_T_INGOT:
        raise ValueError(f"CONTRACTS §5a names 18,000 ₹/t ingot as one grid step above base; the register now gives "
                         f"{above[0]:,.0f} — the ex-ante rule cannot be re-interpreted silently")
    return above[0]


def section_5a_overrides() -> dict[str, dict[str, Override]]:
    """The two one-change §5a cases, plus the both-changes case that is the **no-hindsight** gate.

    `open_pit_conv18k` applies the point-in-time mix *and* the higher conversion cost together. It is not part of
    the §5a rule — that rule is frozen (CONTRACTS §5a) and this changes nothing about it — but it is the version of
    the same discipline a 2022 desk could actually have computed, because the §5a base and conv18k legs both read
    the lag-2 mix, which was published months later. `trade_eligible_pit` is published beside `trade_eligible` so a
    reader can see exactly how much of the book's standing-aside came from a reconstruction (docs/10 §6).
    """
    return {
        "open_pit_mix": mix_variant_overrides(PIT_MIX_KEY),
        "open_conv18k": {"conversion_cost_inr_t": conversion_step_above_base()},
        "open_pit_conv18k": {**mix_variant_overrides(PIT_MIX_KEY),
                             "conversion_cost_inr_t": conversion_step_above_base()},
    }


def build_parity_weekly(inputs: pd.DataFrame | None = None) -> pd.DataFrame:
    """parity_weekly.csv content: keys, key inputs, §5 line items, §5a case flags, USD memo."""
    base_inputs = build_inputs() if inputs is None else inputs
    base = compute(base_inputs)
    cases = {name: compute(apply_overrides(base_inputs, over)) for name, over in section_5a_overrides().items()}
    out = base_inputs[KEY_COLUMNS + ["lme_3m_usd_t", "usdinr", "usdinr_goods", "customs_usdinr_import",
                                     "customs_fx_src", "grade_factor", "freight_base_usd_t", "freight_src",
                                     "mcx_contract", "mcx_anchor_inr_kg"]].copy()
    for col in LINE_ITEMS:
        out[col] = base[col].values
    out["open_base"] = base["window_open"].values
    out["open_pit_mix"] = cases["open_pit_mix"]["window_open"].values
    out["open_conv18k"] = cases["open_conv18k"]["window_open"].values
    out["trade_eligible"] = out["open_base"] & out["open_pit_mix"] & out["open_conv18k"]
    # The no-hindsight counterpart, published as disclosure only: `trade_eligible` above is untouched (§5a).
    out["open_pit_conv18k"] = cases["open_pit_conv18k"]["window_open"].values
    out["trade_eligible_pit"] = out["open_pit_mix"] & out["open_pit_conv18k"]
    out["net_arb_pit_mix_inr_t"] = cases["open_pit_mix"]["net_arb_inr_t"].values
    out["net_arb_conv18k_inr_t"] = cases["open_conv18k"]["net_arb_inr_t"].values
    out["net_arb_pit_conv18k_inr_t"] = cases["open_pit_conv18k"]["net_arb_inr_t"].values
    out["net_arb_usd_t"] = base["net_arb_usd_t"].values
    return out


# ------------------------------------------------------------------------------------------------ market shocks
def market_shock_overrides(lme_shock_frac: float = 0.0, usdinr_level: float | None = None,
                           freight_shock_frac: float = 0.0, freight_on_buyer: bool = False) -> dict[str, Override]:
    """Consistent re-derivation of every LME/FX-dependent input for a shocked market (Table 1.5 grids).

    * LME: 3M and cash scale by (1 + shock). CFR (3M × grade factor), the duty base, finance and the Zorba by-product
      credit follow automatically in ``compute``.
    * USD/INR set to a level: spot = level; the goods forward and the customs notified rate keep their observed ratio
      to spot for that week (forward points and the ~1% customs markup scale with the level).
    * MCX anchor: the panel MCX is duty-paid LME cash import parity × carry (CONTRACTS §4.5), so the contract
      price net of the domestic premium scales with (LME ratio × FX ratio) and keeps its carry factor. If real MCX data
      replace the proxy this becomes an assumption of full pass-through, stated in docs/10_parity_model.md.
    * Freight: ocean freight USD/t scales by (1 + shock). Under CFR terms the seller bears it, so CFR and net arb do not
      move (``freight_on_buyer=False``). For an FOB-term purchase (``freight_on_buyer=True``) the FOB price is fixed
      and the desk books the freight, so the CFR-equivalent cost rises one-for-one with the freight change.
    INR-denominated costs (port, conversion, anchor premium) and USD PSIC fees are held constant.
    """
    over: dict[str, Override] = {}
    r_lme = 1.0 + lme_shock_frac
    prem_kg = float(config.value("mcx_domestic_premium_inr_kg"))

    def fx_ratio(base: pd.DataFrame) -> np.ndarray:
        if usdinr_level is None:
            return np.ones(len(base))
        return usdinr_level / base["usdinr"].to_numpy(dtype=float)

    if lme_shock_frac:
        over["lme_3m_usd_t"] = lambda b: b["lme_3m_usd_t"].to_numpy(dtype=float) * r_lme
        over["lme_cash_usd_t"] = lambda b: b["lme_cash_usd_t"].to_numpy(dtype=float) * r_lme
    if usdinr_level is not None:
        over["usdinr"] = lambda b: np.full(len(b), float(usdinr_level))
        over["usdinr_goods"] = lambda b: b["usdinr_goods"].to_numpy(dtype=float) * fx_ratio(b)
        over["customs_usdinr_import"] = lambda b: b["customs_usdinr_import"].to_numpy(dtype=float) * fx_ratio(b)
    if lme_shock_frac or usdinr_level is not None:
        def mcx(b: pd.DataFrame, col: str) -> np.ndarray:
            spot = b["mcx_al_spot_inr_kg"].to_numpy(dtype=float)
            carry = b[col].to_numpy(dtype=float) / spot
            spot_new = (spot - prem_kg) * r_lme * fx_ratio(b) + prem_kg
            return spot_new * carry
        over["mcx_anchor_inr_kg"] = lambda b: mcx(b, "mcx_anchor_inr_kg")
        over["mcx_al_spot_inr_kg"] = lambda b: mcx(b, "mcx_al_spot_inr_kg")
    if freight_shock_frac:
        over["freight_base_usd_t"] = lambda b: b["freight_base_usd_t"].to_numpy(dtype=float) * (1 + freight_shock_frac)
        if freight_on_buyer:
            def gf(b: pd.DataFrame) -> np.ndarray:
                scale = b["container_payload_base_mt"].to_numpy(float) / b["container_payload_grade_mt"].to_numpy(float)
                d_freight = b["freight_base_usd_t"].to_numpy(float) * scale * freight_shock_frac
                return b["grade_factor"].to_numpy(float) + d_freight / (b["lme_3m_usd_t"].to_numpy(float) * r_lme)
            over["grade_factor"] = gf
    return over


# ------------------------------------------------------------------------------------------------ exports for P2/P3
def load_parity(path=None) -> pd.DataFrame:
    """Read outputs/tables/parity_weekly.csv (stages talk through files, CONTRACTS §1.7)."""
    path = PARITY_CSV if path is None else path
    if not path.exists():
        raise FileNotFoundError(f"{path} missing — run `DESK_OFFLINE=1 .venv/bin/python run_all.py --only P1`")
    return pd.read_csv(path, parse_dates=["week_end", "value_date"])


def eligible_on(trade_date, grade: str, lane: str, parity: pd.DataFrame | None = None
                ) -> tuple[bool, pd.Timestamp | None, pd.Series | None]:
    """CONTRACTS §5a look-up: the latest parity week_end ≤ trade_date decides (no information after the trade date).

    Returns (trade_eligible, week_end, row). A trade dated before the first parity week returns (False, None, None);
    a trade dated a full week or more after the last parity week raises (the look-up would be stale).
    """
    parity = load_parity() if parity is None else parity
    if grade not in GRADES or lane not in LANES:
        raise KeyError(f"unknown grade/lane {grade!r}/{lane!r}")
    d = pd.Timestamp(trade_date).normalize()
    sub = parity[(parity["grade"] == grade) & (parity["lane"] == lane) & (parity["week_end"] <= d)]
    if sub.empty:
        return False, None, None
    row = sub.sort_values("week_end").iloc[-1]
    if (d - row["week_end"]).days >= DAYS_PER_WEEK:
        raise ValueError(f"trade date {d.date()} is beyond the parity weeks (last {row['week_end'].date()})")
    return bool(row["trade_eligible"]), row["week_end"], row


def parity_row(week_end, grade: str, lane: str, overrides: Mapping[str, Override] | None = None,
               inputs: pd.DataFrame | None = None) -> pd.Series:
    """One §5 row (inputs + line items) for a week/grade/lane, optionally under overrides."""
    base = build_inputs() if inputs is None else inputs
    we = pd.Timestamp(week_end)
    sub = base[(base["week_end"] == we) & (base["grade"] == grade) & (base["lane"] == lane)].reset_index(drop=True)
    if sub.empty:
        raise KeyError(f"no parity row for {we.date()} {grade} {lane}")
    ins = apply_overrides(sub, overrides)
    res = compute(ins)
    dup = [c for c in res.columns if c in ins.columns]  # keys and margin_threshold_inr_t appear in both
    return pd.concat([ins.iloc[0], res.iloc[0].drop(labels=dup)])
