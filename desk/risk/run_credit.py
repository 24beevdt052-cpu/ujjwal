"""Stage P5 — counterparty credit scoring (Table 6 row 4.3) and the credit tracker (row 4.4).

    DESK_OFFLINE=1 .venv/bin/python -c "import desk.risk.run_credit as m; m.main()"

Reads (never writes) the P2/P3 tables, fits the illustrative model on synthetic data, scores the three SIM buyers
point-in-time and writes:

    outputs/tables/credit_synthetic_training_data.csv   buyer-quarter x features, true PD, default flag, split
    outputs/tables/credit_model_coefficients.csv        true vs fitted coefficients, odds ratios, bootstrap signs
    outputs/tables/credit_model_fit.csv                 AUC / Brier / log loss vs the DGP oracle (train, test)
    outputs/tables/credit_model_calibration.csv         quintile calibration (train, test)
    outputs/tables/credit_model_sample_size.csv         sign recovery over re-draws of the same DGP
    outputs/tables/credit_band_policy.csv               band -> PD range -> limit policy (quoted by the risk memo)
    outputs/tables/credit_scores.csv                    ranked buyers as of WINDOW_END
    outputs/tables/credit_scores_sensitivity.csv        the same ranking under DGP / feature / base-rate variants
    outputs/tables/credit_tracker.csv                   date x counterparty exposures, flags, band, events
    outputs/tables/credit_tracker_bookings.csv          each sale booking vs the band policy at the previous close
    outputs/charts/p5_credit_scores.png, p5_credit_tracker.png, p5_credit_model_fit.png
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from desk import SIM_LABEL, WINDOW_END, config
from desk.paths import TABLES_DIR, ensure_dirs
from desk.risk import credit_scoring as cs
from desk.risk import credit_tracker as ct

AS_OF = WINDOW_END
BASE_RATE_VARIANTS = (0.02, 0.05)
FLOAT_DECIMALS = 8
RECON_TOL_INR = 0.01


# ------------------------------------------------------------------------------------------------ io
def write(df: pd.DataFrame, name: str) -> str:
    """Deterministic CSV (CONTRACTS §1.5): fixed rounding, ISO dates, LF endings."""
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].round(FLOAT_DECIMALS)
    path = TABLES_DIR / f"{name}.csv"
    out.to_csv(path, index=False, lineterminator="\n", date_format="%Y-%m-%d")
    return str(path)


# ------------------------------------------------------------------------------------------------ controls
def reconcile(tracker: pd.DataFrame, inputs: ct.CreditInputs) -> pd.DataFrame:
    """The tracker must tie to the P3 per-buyer file it is built from, and to P2's booking-time advances."""
    p3 = pd.read_csv(TABLES_DIR / "buyer_credit_exposure_daily.csv", parse_dates=["date"])
    b = tracker[tracker["role"] == ct.BUYER_ROLE].merge(p3, left_on=["date", "cp_id"], right_on=["date", "buyer_id"],
                                                         how="left", suffixes=("", "_p3"))
    rows = []
    for col in ("receivable_inr", "presettlement_inr", "contracted_inr"):
        diff = (b[col] - b[f"{col}_p3"].fillna(0.0)).abs().max()
        rows.append({"check": f"tracker_{col}_vs_p3_buyer_file_max_abs", "value": float(diff), "tolerance": RECON_TOL_INR})
    have = b["utilisation_frac_p3"].notna()
    diff = (b.loc[have, "utilisation_receivable_frac"] - b.loc[have, "utilisation_frac_p3"]).abs().max()
    rows.append({"check": "utilisation_receivable_vs_p3_max_abs", "value": float(diff), "tolerance": 1e-4})
    adv = inputs.bookings.merge(inputs.advance_receipts, on=["trade_id", "sale_id"], how="inner")
    diff = (adv["advance_value_inr"] - adv["realised_advance_inr"]).abs().max() if len(adv) else 0.0
    rows.append({"check": "booking_advance_vs_realised_advance_max_abs", "value": float(diff), "tolerance": 1.0})
    neg = float((b["receivable_inr"] + b["presettlement_inr"] - b["advance_pending_inr"]).min())
    rows.append({"check": "advance_pending_never_exceeds_presettlement_min", "value": min(neg, 0.0) * -1.0,
                 "tolerance": RECON_TOL_INR})
    out = pd.DataFrame(rows)
    out["status"] = np.where(out["value"] <= out["tolerance"], "PASS", "FAIL")
    if (out["status"] == "FAIL").any():
        raise ValueError(f"credit tracker reconciliation failed:\n{out[out['status'] == 'FAIL']}")
    return out


# ------------------------------------------------------------------------------------------------ snapshot
def scores_snapshot(run: cs.ModelRun, tracker: pd.DataFrame, inputs: ct.CreditInputs) -> pd.DataFrame:
    snap = ct.as_of_rows(tracker, AS_OF).reset_index(drop=True)
    feats = ct.features_frame(snap)
    model = run.model
    snap["pd_true_dgp_annual_frac"] = cs.true_pd(run.dgp, run.intercept_true, feats)
    contrib = model.contributions(feats)
    support = model.in_support(feats)
    snap = pd.concat([snap, contrib, support], axis=1)
    snap["in_support_all"] = support.all(axis=1)
    top = contrib.idxmax(axis=1).str.replace("logodds_contrib_", "", regex=False)
    snap["top_risk_driver"] = top.map(cs.FEATURE_LABELS)
    alt = feats.copy()
    alt["utilisation_frac"] = feats["contracted_utilisation_peak_frac"]
    snap["pd_alt_contracted_utilisation_annual_frac"] = model.predict(alt)
    lo, hi = model.train_support["utilisation_frac"]
    snap["alt_utilisation_in_support"] = alt["utilisation_frac"].between(lo, hi)
    for key in ("band_max_credit_days", "band_review_frequency_days"):
        snap[key] = snap["band_final"].map(lambda b, k=key: cs.band_policy(b)[k])

    buyers = tracker[(tracker["role"] == ct.BUYER_ROLE) & (tracker["date"] <= pd.Timestamp(AS_OF))]
    first = buyers.sort_values("date").groupby("cp_id").first()
    snap["pd_first_day_annual_frac"] = snap["cp_id"].map(first["pd_model_annual_frac"])
    snap["band_final_first_day"] = snap["cp_id"].map(first["band_final"])
    worst = buyers.assign(rank=buyers["band_final"].map(cs.BANDS.index)).sort_values(["cp_id", "rank", "date"],
                                                                                     ascending=[True, False, True])
    w = worst.groupby("cp_id").first()
    snap["band_final_worst_to_date"] = snap["cp_id"].map(w["band_final"])
    snap["band_final_worst_first_date"] = snap["cp_id"].map(w["date"])
    peaks = buyers.groupby("cp_id")[["utilisation_p04_basis_frac", "utilisation_contracted_frac",
                                     "advance_reliance_multiple"]].max()
    snap["credit_utilisation_peak_to_date_frac"] = snap["cp_id"].map(peaks["utilisation_p04_basis_frac"])
    snap["contracted_utilisation_peak_to_date_frac"] = snap["cp_id"].map(peaks["utilisation_contracted_frac"])
    snap["advance_reliance_peak_to_date_multiple"] = snap["cp_id"].map(peaks["advance_reliance_multiple"])
    ratings = {c.cp_id: c.profile.internal_rating_sim for c in inputs.counterparties}
    snap["internal_rating_sim_memo"] = snap["cp_id"].map(ratings)
    snap = snap.sort_values("pd_model_annual_frac", ascending=False).reset_index(drop=True)
    snap.insert(0, "rank_riskiest_first", np.arange(1, len(snap) + 1))
    snap.insert(1, "as_of_date", snap.pop("date"))
    snap["label"] = (f"{SIM_LABEL}. ILLUSTRATIVE: PD from a logistic model trained on SYNTHETIC data; not a "
                     f"measured default probability of any real company")
    cols = [
        "rank_riskiest_first", "as_of_date", "cp_id", "cp_name", "internal_rating_sim_memo", "credit_limit_inr",
        "feat_utilisation_peak_91d_frac", "feat_dpd_max_12m_days", "feat_history_months",
        "feat_order_concentration_frac", "pd_model_annual_frac", "pd_true_dgp_annual_frac", "band_model",
        "advance_reliance_peak_91d_multiple", "overlay_notches", "band_final", "limit_action", "recommended_limit_inr",
        "band_max_credit_utilisation_frac", "band_max_advance_reliance_multiple", "band_max_credit_days",
        "band_review_frequency_days", "top_risk_driver", *contrib.columns, *support.columns, "in_support_all",
        "contracted_utilisation_peak_91d_frac", "pd_alt_contracted_utilisation_annual_frac",
        "alt_utilisation_in_support", "credit_exposure_inr", "utilisation_frac", "receivable_inr",
        "advance_pending_inr", "days_past_due", "credit_utilisation_peak_to_date_frac",
        "contracted_utilisation_peak_to_date_frac", "advance_reliance_peak_to_date_multiple",
        "pd_first_day_annual_frac", "band_final_first_day", "band_final_worst_to_date", "band_final_worst_first_date",
        "label",
    ]
    return snap[cols]


def score_sensitivity(run: cs.ModelRun, snapshot: pd.DataFrame) -> pd.DataFrame:
    """Does the ranking survive the assumptions it rests on? Every variant scores the same as-of feature rows."""
    feats = ct.features_frame(snapshot)
    base_notch = snapshot["overlay_notches"].to_numpy()
    train = run.data[run.data["split"] == "train"]
    variants: list[tuple[str, str, np.ndarray, bool]] = [
        ("base_fitted", "fitted model, registered DGP (base)", run.model.predict(feats), True),
        ("true_dgp", "the DGP's own PD (what a perfectly estimated model would say)",
         cs.true_pd(run.dgp, run.intercept_true, feats), True),
    ]
    for f in cs.FEATURES:
        tr = train.copy()
        m = float(tr[f].mean())
        tr[f] = m
        model_f = cs.fit(tr, support_frame=run.data)
        x = feats.copy()
        x[f] = m
        variants.append((f"drop_{f}", f"refit without {cs.FEATURE_LABELS[f]} (held at the synthetic mean)",
                         model_f.predict(x), True))
    for rate in BASE_RATE_VARIANTS:
        r = cs.build_model(dgp=cs.load_dgp(base_rate=rate), n_boot=0)
        variants.append((f"base_rate_{rate:.2f}", f"synthetic population base default rate {rate:.0%} (base 4 %)",
                         r.model.predict(feats), True))
    alt = feats.copy()
    alt["utilisation_frac"] = feats["contracted_utilisation_peak_frac"]
    variants.append(("alt_contracted_utilisation",
                     "advances owed counted inside utilisation instead of the overlay (OUT OF TRAINING SUPPORT where "
                     "flagged: the logistic curve is extrapolating)", run.model.predict(alt), False))
    rows = []
    lo, hi = run.model.train_support["utilisation_frac"]
    for name, desc, pd_arr, overlay in variants:
        band_m = cs.band_from_pd(pd_arr)
        notches = base_notch if overlay else np.zeros_like(base_notch)
        band_f = cs.notch(band_m, notches)
        order = (-pd_arr).argsort(kind="stable")
        rank = np.empty(len(pd_arr), int)
        rank[order] = np.arange(1, len(pd_arr) + 1)
        for i, cp in enumerate(snapshot["cp_id"]):
            util = alt["utilisation_frac"].iloc[i] if name == "alt_contracted_utilisation" else feats["utilisation_frac"].iloc[i]
            rows.append({"scenario": name, "description": desc, "as_of_date": snapshot["as_of_date"].iloc[i],
                         "cp_id": cp, "pd_annual_frac": float(pd_arr[i]), "rank_riskiest_first": int(rank[i]),
                         "band_model": band_m[i], "overlay_notches": int(notches[i]), "band_final": band_f[i],
                         "utilisation_in_support": bool(lo <= util <= hi)})
    no = [{**r, "scenario": "no_overlay", "description": "fitted model, performance overlay switched off",
           "overlay_notches": 0, "band_final": r["band_model"]} for r in rows if r["scenario"] == "base_fitted"]
    out = pd.DataFrame(rows + no)
    out["label"] = f"{SIM_LABEL}. ILLUSTRATIVE model on SYNTHETIC training data"
    return out


# ------------------------------------------------------------------------------------------------ charts
BAND_COLORS = {"A": "#d9ead3", "B": "#fff2cc", "C": "#fce5cd", "D": "#f4cccc", ct.NOT_SCORED: "#eeeeee"}
BUYER_COLORS = {"BUY_MUN_01": "#1f4e79", "BUY_JNPT_01": "#548235", "BUY_RJK_01": "#c00000"}


def _short(cp_name: str) -> str:
    return cp_name.replace(" Pvt Ltd", "").replace(" (SIM)", "") + " (SIM)"


def chart_scores(snapshot: pd.DataFrame, run: cs.ModelRun) -> str:
    import matplotlib.pyplot as plt

    from desk.reporting.style import save_fig

    cut = cs.band_cutoffs()
    s = snapshot.sort_values("pd_model_annual_frac")
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [1.15, 1]})
    x_lo = 0.003
    edges = [x_lo, cut["A"], cut["B"], cut["C"], 1.0]
    for b, lo, hi in zip(cs.BANDS, edges[:-1], edges[1:]):
        ax.axvspan(lo, hi, color=BAND_COLORS[b], zorder=0)
        ax.text(np.sqrt(lo * hi), len(s) - 0.45, f"band {b}", ha="center", va="bottom", fontsize=8.5,
                fontweight="bold", color="#555555")
    y = np.arange(len(s))
    ax.barh(y, s["pd_model_annual_frac"] - x_lo, left=x_lo, color=[BUYER_COLORS.get(c, "#7f7f7f") for c in s["cp_id"]],
            height=0.5, zorder=2, label="fitted model PD")
    ax.scatter(s["pd_true_dgp_annual_frac"], y, marker="|", s=400, color="black", zorder=3,
               label="synthetic DGP's own PD")
    for i, r in enumerate(s.itertuples()):
        txt = f"{r.pd_model_annual_frac:.1%}  band {r.band_model}"
        txt += f" → {r.band_final} (advance overlay)" if r.band_final != r.band_model else ""
        ax.text(x_lo * 1.1, i + 0.36, txt, va="center", fontsize=8.5, zorder=4)
    ax.set_yticks(y, [f"{_short(n)}\nlimit ₹{l / 1e6:,.0f}m" for n, l in zip(s["cp_name"], s["credit_limit_inr"])])
    ax.set_xscale("log")
    ax.set_xlim(x_lo, 1.0)
    ax.set_ylim(-0.6, len(s) - 0.1)
    ax.set_xlabel("12-month probability of default (illustrative, log scale)")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1%}" if v < 0.01 else f"{v:.0%}"))
    ax.set_title(f"Ranked PD and score band as of {pd.Timestamp(AS_OF):%d-%b-%Y}")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2, fontsize=8)

    cols = [f"logodds_contrib_{f}" for f in cs.FEATURES]
    colors = ["#1f4e79", "#c00000", "#7f6000", "#8064a2"]
    h = 0.18
    for k, (c, f) in enumerate(zip(cols, cs.FEATURES)):
        ax2.barh(y + (k - 1.5) * h, s[c], height=h, color=colors[k], label=cs.FEATURE_LABELS[f])
    ax2.axvline(0, color="#444444", lw=0.8)
    ax2.set_yticks(y, [_short(n) for n in s["cp_name"]])
    ax2.set_xlabel("contribution to log-odds vs the synthetic population average (+ = riskier)")
    ax2.set_title("What drives each score")
    ax2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2, fontsize=8)
    fig.suptitle("Counterparty credit scoring — ILLUSTRATIVE logistic model trained on SYNTHETIC data "
                 "(not evidence of real predictive power)", fontsize=11, fontweight="bold")
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    return save_fig(fig, "p5_credit_scores",
                    f"Model: {len(run.data):,} synthetic buyer-quarters (ILLUSTRATIVE SYNTHETIC). Features: SIM book "
                    f"(P3 credit exposure files, trade_credit_exposure.csv, counterparties.yaml profile)")


def chart_tracker(tracker: pd.DataFrame) -> str:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    from desk.reporting.style import save_fig

    b = tracker[tracker["role"] == ct.BUYER_ROLE]
    ids = ["BUY_MUN_01", "BUY_JNPT_01", "BUY_RJK_01"]
    ids = [i for i in ids if i in set(b["cp_id"])] + sorted(set(b["cp_id"]) - set(ids))
    fig, axes = plt.subplots(len(ids) + 1, 1, figsize=(12.5, 3.0 * len(ids) + 2.8), sharex=True,
                             gridspec_kw={"height_ratios": [3] * len(ids) + [2.2]})
    soft = float(config.value("credit_soft_utilisation_frac"))
    for ax, cp in zip(axes, ids):
        g = b[b["cp_id"] == cp].sort_values("date")
        d = g["date"]
        # band strip: final band as of each day, drawn as background spans
        run_start = 0
        bands = g["band_final"].to_list()
        for i in range(1, len(bands) + 1):
            if i == len(bands) or bands[i] != bands[run_start]:
                end = d.iloc[i] if i < len(bands) else d.iloc[-1] + pd.Timedelta(days=1)
                ax.axvspan(d.iloc[run_start], end, ymin=0.93, ymax=1.0, color=BAND_COLORS[bands[run_start]], lw=0)
                ax.text(d.iloc[run_start] + (end - d.iloc[run_start]) / 2, 0.965, bands[run_start],
                        transform=ax.get_xaxis_transform(), ha="center", va="center", fontsize=8, fontweight="bold")
                run_start = i
        ax.fill_between(d, 0, g["advance_reliance_multiple"], step="post", color="#f4b183", alpha=0.6,
                        label="advance reliance (advances owed / limit)")
        ax.step(d, g["utilisation_contracted_frac"], where="post", color="#7f7f7f", ls="--", lw=1,
                label="contracted incl. pre-settlement / limit (memo)")
        ax.step(d, g["utilisation_p04_basis_frac"], where="post", color=BUYER_COLORS.get(cp, "#1f4e79"), lw=2,
                label="credit utilisation (receivable + uncovered contracted; buyer colour)")
        ax.step(d, g["utilisation_receivable_frac"], where="post", color="black", lw=0.8,
                label="receivable / limit (hard-breach measure)")
        ax.axhline(1.0, color="#c00000", lw=1)
        ax.axhline(soft, color="#c55a11", lw=0.8, ls=":")
        ax.text(d.iloc[-1], 1.02, "limit = P14 advance cap (1.0x) ", fontsize=7, color="#c00000", va="bottom",
                ha="right")
        ax.text(d.iloc[-1], soft - 0.02, f"soft flag {soft:.0%} ", fontsize=7, color="#c55a11", va="top", ha="right")
        pd_days = g[g["days_past_due"] > 0]
        if len(pd_days):
            ax.axvspan(pd_days["date"].min(), pd_days["date"].max(), ymin=0, ymax=0.9, color="#c00000", alpha=0.08)
            # inside the top of the shaded span: on the zero line the label sat on the utilisation step
            ax.text(pd_days["date"].min(), 0.86, f" past due (max {int(pd_days['days_past_due'].max())} d)",
                    fontsize=7.5, color="#c00000", va="top", transform=ax.get_xaxis_transform())
        ev = g[g["events"].str.contains("SALE_CONTRACTED", na=False)]
        ymax = max(1.2, float(g[["utilisation_contracted_frac", "advance_reliance_multiple"]].max().max()) * 1.18)
        last, level = None, 0
        for r in ev.itertuples():
            tags = [e.split()[1] for e in r.events.split(ct.EVENT_SEP) if e.startswith("SALE_CONTRACTED")]
            level = (level + 1) % 2 if last is not None and (r.date - last).days < 12 else 0
            last = r.date
            ax.annotate(" / ".join(tags), (r.date, ymax * (0.86 - 0.09 * level)), fontsize=7, ha="center",
                        color="#333333", bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none"})
            ax.axvline(r.date, color="#333333", lw=0.5, ls=":", ymax=0.84)
        flagged = g[g["flag_band_utilisation"] | g["flag_band_advance"]]
        if len(flagged):
            ax.scatter(flagged["date"], np.full(len(flagged), -0.06 * ymax), marker="s", s=6, color="#c00000",
                       clip_on=False, label="outside band policy that day")
        ax.set_ylim(-0.1 * ymax, ymax)
        name = g["cp_name"].iloc[0]
        lim = g["credit_limit_inr"].iloc[0]
        ax.set_title(f"{_short(name)} — credit limit ₹{lim / 1e6:,.0f}m", loc="left", fontsize=10)
        ax.set_ylabel("multiple of limit")
        ax.axvline(pd.Timestamp(WINDOW_END), color="#7f7f7f", lw=0.8, ls="-.")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, fontsize=8, bbox_to_anchor=(0.5, 0.965))
    ax = axes[-1]
    for cp in ids:
        g = b[b["cp_id"] == cp].sort_values("date")
        ax.step(g["date"], g["pd_model_annual_frac"], where="post", color=BUYER_COLORS.get(cp, "#7f7f7f"), lw=1.8,
                label=_short(g["cp_name"].iloc[0]))
    cut = cs.band_cutoffs()
    for bnd, v in cut.items():
        ax.axhline(v, color="#7f7f7f", lw=0.7, ls=":")
        ax.text(b["date"].max(), v, f" {bnd}|{chr(ord(bnd) + 1)}", fontsize=7, va="center")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1%}" if v < 0.1 else f"{v:.0%}"))
    ax.set_ylabel("model PD (log)")
    ax.set_title("Point-in-time model PD (before the advance overlay); dash-dot line = window end", loc="left",
                 fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
    fig.suptitle("Credit tracker — exposure vs limit, breach / soft / performance flags, score band (top strip)",
                 fontsize=12, fontweight="bold")
    fig.tight_layout(rect=(0, 0.02, 1, 0.935))
    return save_fig(fig, "p5_credit_tracker",
                    "Exposures: P3 buyer_credit_exposure_by_trade_daily.csv, trade_credit_exposure.csv, "
                    "trade_cashflows.csv (SIM book). Bands: ILLUSTRATIVE model on SYNTHETIC data")


def chart_model_fit(run: cs.ModelRun, coefs: pd.DataFrame, calib: pd.DataFrame) -> str:
    import matplotlib.pyplot as plt

    from desk.reporting.style import save_fig

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    c = coefs[coefs["term"] != "intercept"].reset_index(drop=True)
    y = np.arange(len(c))
    lo = c["odds_ratio_per_increment_fitted"] - c["odds_ratio_per_increment_boot_p2_5"]
    hi = c["odds_ratio_per_increment_boot_p97_5"] - c["odds_ratio_per_increment_fitted"]
    ax.errorbar(c["odds_ratio_per_increment_fitted"], y + 0.12, xerr=[lo, hi], fmt="o", color="#1f4e79",
                label="fitted (95 % buyer-cluster bootstrap)")
    ax.scatter(c["odds_ratio_per_increment_true"], y - 0.12, marker="D", color="#c00000", label="DGP truth")
    ax.axvline(1.0, color="#444444", lw=0.8)
    inc = {"utilisation_frac": "+10 pp", "dpd_max_days": "+10 days", "history_months": "+12 months",
           "order_concentration_frac": "+10 pp"}
    ax.set_yticks(y, [f"{cs.FEATURE_LABELS[t]}\n({inc[t]}; bootstrap sign ok {s:.0%})"
                      for t, s in zip(c["term"], c["boot_sign_match_share"])])
    ax.set_xlabel("odds ratio per increment (1 = no effect)")
    ax.set_title("Coefficients: fitted vs the synthetic truth")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2, fontsize=8)
    for split, color in (("train", "#7f7f7f"), ("test", "#1f4e79")):
        g = calib[calib["split"] == split]
        ax2.plot(g["pd_mean_fitted"], g["default_rate_observed"], "o-", color=color, label=f"{split}: observed rate")
        ax2.plot(g["pd_mean_fitted"], g["pd_mean_true"], "x:", color=color, label=f"{split}: DGP's true PD")
    m = float(calib[["pd_mean_fitted", "default_rate_observed"]].max().max()) * 1.1
    ax2.plot([0, m], [0, m], color="#444444", lw=0.8, ls="--")
    ax2.set_xlabel("mean fitted PD in quintile")
    ax2.set_ylabel("default rate")
    ax2.set_title("Calibration by quintile of fitted PD")
    ax2.legend(fontsize=8)
    fig.suptitle("Model fit on SYNTHETIC data — shows the model recovers its own generating process; "
                 "NOT evidence of real predictive power", fontsize=11, fontweight="bold")
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    return save_fig(fig, "p5_credit_model_fit", f"{cs.SYNTH_LABEL}; {len(run.data):,} buyer-quarters, buyer-level "
                                                f"70/30 split, seed desk.RNG_SEED")


# ------------------------------------------------------------------------------------------------ main
def main() -> None:
    ensure_dirs()
    run = cs.build_model()
    coefs = cs.coefficient_table(run.model, run.dgp, run.intercept_true, run.boot)
    fit = cs.fit_metrics(run.model, run.data)
    calib = cs.calibration_table(run.model, run.data)
    study = cs.sample_size_study(run.dgp)
    write(run.data, "credit_synthetic_training_data")
    write(coefs, "credit_model_coefficients")
    write(fit, "credit_model_fit")
    write(calib, "credit_model_calibration")
    write(study, "credit_model_sample_size")
    write(cs.band_policy_table(), "credit_band_policy")

    inputs = ct.load_inputs()
    tracker = ct.build_tracker(inputs, run.model)
    controls = reconcile(tracker, inputs)
    bookings = ct.booking_checks(inputs, tracker)
    snapshot = scores_snapshot(run, tracker, inputs)
    sens = score_sensitivity(run, snapshot)
    write(tracker, "credit_tracker")
    write(bookings, "credit_tracker_bookings")
    write(snapshot, "credit_scores")
    write(sens, "credit_scores_sensitivity")

    chart_scores(snapshot, run)
    chart_tracker(tracker)
    chart_model_fit(run, coefs, calib)

    f = fit.pivot(index="metric", columns="split", values="value")
    print(f"[credit] synthetic: {len(run.data)} buyer-quarters, {int(run.data['default_12m'].sum())} defaults; "
          f"test AUC {f.loc['auc_fitted', 'test']:.3f} (oracle {f.loc['auc_true_pd_oracle', 'test']:.3f}); "
          f"signs match DGP: {bool(coefs['sign_match'].all())}")
    for r in snapshot.itertuples():
        print(f"[credit] #{r.rank_riskiest_first} {r.cp_id}: PD {r.pd_model_annual_frac:.2%} "
              f"(DGP {r.pd_true_dgp_annual_frac:.2%}) band {r.band_model}->{r.band_final}")
    buyers = tracker[tracker["role"] == ct.BUYER_ROLE]
    print(f"[credit] tracker rows {len(tracker)}; hard breaches {int(buyers['breach_hard'].sum())}; "
          f"P14 performance-flag days {int(buyers['flag_performance_advance_p14'].sum())}; "
          f"bookings outside band policy {int((bookings['band_policy_verdict'] == 'OUTSIDE_BAND_POLICY').sum())}"
          f"/{len(bookings)}; controls {controls['status'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
