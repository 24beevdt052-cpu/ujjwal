"""Counterparty credit scoring (MASTER_SPEC Table 6 row 4.3) — ILLUSTRATIVE, on SYNTHETIC training data.

What this module does, in order:

1. **Invents a buyer population.** `generate_synthetic` draws buyer-quarter observations for fictional Gujarat
   foundries and secondary smelters from a written-down data-generating process (DGP). Each buyer has a latent
   weakness `w` that makes its features move together (weak names run fuller lines, pay later, source more from one
   importer), but `w` never enters the default probability directly: the true 12-month PD is
   `sigmoid(b0 + Σ beta_k x_k)` over the four features, with every beta taken from an odds ratio in
   `config/params/risk_credit.yaml` and `b0` solved so the population default rate equals the registered base rate.
   A logistic model is therefore correctly specified *by construction* — the one property real data never has.
2. **Fits a plain logistic regression** (standardised features, unpenalised, scikit-learn) on a buyer-level
   train split and reports coefficients in both standardised and raw units, odds ratios per stated increment, and a
   buyer-cluster bootstrap of each sign.
3. **Scores** any frame carrying the four feature columns, maps PD to a band and applies the performance overlay.

Why logistic regression rather than gradient boosting or a neural net: a credit committee has to be able to read
every coefficient, challenge its sign and see which feature moved a name's score. Four coefficients do that; a
black box on a few hundred synthetic rows would only fit the generator's noise and could not be argued with.

Nothing fitted here is evidence of real predictive power. The fit statistics measure how well the model recovers
the process that generated its own data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.special import expit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from desk import RNG_SEED, config

SYNTH_LABEL = "ILLUSTRATIVE SYNTHETIC DATA — fictional buyer population, not real counterparties"

# Feature order is the model's column order everywhere (training frame, coefficients, scoring).
FEATURES = ("utilisation_frac", "dpd_max_days", "history_months", "order_concentration_frac")
FEATURE_LABELS = {
    "utilisation_frac": "Peak credit utilisation (91 d)",
    "dpd_max_days": "Worst days past due (12 m)",
    "history_months": "Payment history (months)",
    "order_concentration_frac": "Share of buyer's input from desk (12 m)",
}
# The increment each registered odds ratio is quoted per (part of the parameter's unit).
ODDS_RATIO_KEYS = {
    "utilisation_frac": ("credit_dgp_odds_ratio_utilisation_per_10pp", 0.10),
    "dpd_max_days": ("credit_dgp_odds_ratio_dpd_per_10d", 10.0),
    "history_months": ("credit_dgp_odds_ratio_history_per_12m", 12.0),
    "order_concentration_frac": ("credit_dgp_odds_ratio_concentration_per_10pp", 0.10),
}

# Model-structure constants (CONTRACTS §1.6). 300 buyers x 4 quarters = 1,200 buyer-quarters: at the 4 % base
# rate that is ~48 defaults, ~34 of them in training, i.e. ~8 events per variable, near the usual rule of thumb of
# ten. The brief's example of 300-600 rows gives ~17 training defaults (EPV ~4). The size was fixed from a 20-draw
# pilot of a draft generator; the 200-draw `sample_size_study` published with the model shows the weakest coefficient (concentration)
# is still recovered with the right sign in only ~80 % of fresh draws at this size, and the size was NOT re-chosen
# after seeing that — the study is published instead, because weak identification is itself the finding.
N_SYNTH_BUYERS = 300
N_SYNTH_QUARTERS = 4
TEST_FRAC_BUYERS = 0.30
N_BOOTSTRAP = 500
N_REDRAWS = 200
REDRAW_BUYER_COUNTS = (150, 300, 1000)
CALIBRATION_BINS = 5
SUPPORT_PCTL = (1.0, 99.0)
BANDS = ("A", "B", "C", "D")
MONTH_DAYS = 365.25 / 12.0


# ------------------------------------------------------------------------------------------------ the DGP
@dataclass(frozen=True)
class DGP:
    base_rate: float
    betas: dict[str, float]
    gen_util: dict
    gen_dpd: dict
    gen_hist: dict
    gen_conc: dict

    @property
    def beta_vector(self) -> np.ndarray:
        return np.array([self.betas[f] for f in FEATURES])


def load_dgp(base_rate: float | None = None) -> DGP:
    """The registered DGP; `base_rate` overrides the base rate for the published sensitivity only."""
    betas = {f: float(np.log(config.value(key)) / inc) for f, (key, inc) in ODDS_RATIO_KEYS.items()}
    return DGP(
        base_rate=float(config.value("credit_synth_base_default_rate_annual_frac") if base_rate is None else base_rate),
        betas=betas,
        gen_util=dict(config.value("credit_synth_gen_utilisation")),
        gen_dpd=dict(config.value("credit_synth_gen_dpd")),
        gen_hist=dict(config.value("credit_synth_gen_history")),
        gen_conc=dict(config.value("credit_synth_gen_concentration")),
    )


def _features(rng: np.random.Generator, dgp: DGP, n_buyers: int, n_quarters: int) -> pd.DataFrame:
    """Buyer-level draws first, then one block of draws per quarter, in a fixed order (determinism)."""
    gu, gd, gh, gc = dgp.gen_util, dgp.gen_dpd, dgp.gen_hist, dgp.gen_conc
    w = rng.normal(size=n_buyers)
    hist0 = np.exp(np.log(gh["median_months"]) + gh["weakness_loading_log"] * w + gh["log_sd"] * rng.normal(size=n_buyers))
    conc_buyer = rng.normal(size=n_buyers)
    blocks = []
    for q in range(n_quarters):
        util = np.clip(gu["mean"] + gu["weakness_loading"] * w + gu["noise_sd"] * rng.normal(size=n_buyers),
                       gu["floor"], gu["cap"])
        late = rng.random(n_buyers) < expit(gd["p_late_logit_intercept"] + gd["p_late_weakness_loading"] * w)
        days = np.ceil(rng.exponential(gd["late_mean_days"] * np.exp(gd["late_mean_weakness_elasticity"] * w)))
        dpd = np.where(late, np.minimum(np.maximum(days, 1.0), gd["cap_days"]), 0.0)
        hist = np.clip(hist0 + gh["months_per_quarter"] * q, gh["floor_months"], gh["cap_months"])
        conc = expit(gc["logit_intercept"] + gc["weakness_loading"] * w + gc["buyer_sd"] * conc_buyer
                     + gc["quarter_sd"] * rng.normal(size=n_buyers))
        blocks.append(pd.DataFrame({
            "buyer_id": [f"SYN_{i + 1:04d}" for i in range(n_buyers)],
            "quarter": q + 1,
            "latent_weakness": w,
            "utilisation_frac": util,
            "dpd_max_days": dpd,
            "history_months": hist,
            "order_concentration_frac": conc,
        }))
    return pd.concat(blocks, ignore_index=True)


def solve_intercept(X: np.ndarray, betas: np.ndarray, base_rate: float) -> float:
    """b0 such that the mean true PD over this population equals the registered base rate."""
    lin = X @ betas
    return float(brentq(lambda b: expit(b + lin).mean() - base_rate, -40.0, 40.0, xtol=1e-12))


def generate_synthetic(seed: int = RNG_SEED, n_buyers: int = N_SYNTH_BUYERS, n_quarters: int = N_SYNTH_QUARTERS,
                       dgp: DGP | None = None) -> tuple[pd.DataFrame, float]:
    """Synthetic buyer-quarters with true PD, a 12-month default flag and a buyer-level train/test split.

    Returns (frame, intercept). The split is by buyer so no buyer appears in both halves: the four quarters of one
    buyer share its latent weakness, and a row-level split would leak it into the test score.
    """
    dgp = dgp or load_dgp()
    rng = np.random.default_rng(seed)
    df = _features(rng, dgp, n_buyers, n_quarters)
    X = df[list(FEATURES)].to_numpy(float)
    b0 = solve_intercept(X, dgp.beta_vector, dgp.base_rate)
    df["true_pd_12m_frac"] = expit(b0 + X @ dgp.beta_vector)
    df["default_12m"] = (rng.random(len(df)) < df["true_pd_12m_frac"].to_numpy()).astype(int)
    order = rng.permutation(n_buyers)
    test_ids = {f"SYN_{i + 1:04d}" for i in order[: int(round(TEST_FRAC_BUYERS * n_buyers))]}
    df["split"] = np.where(df["buyer_id"].isin(test_ids), "test", "train")
    df.insert(0, "obs_id", [f"OBS_{i + 1:05d}" for i in range(len(df))])
    df["label"] = SYNTH_LABEL
    return df, b0


# ------------------------------------------------------------------------------------------------ the model
@dataclass
class FittedModel:
    mean: np.ndarray
    scale: np.ndarray
    coef_std: np.ndarray
    intercept_std: float
    train_support: dict[str, tuple[float, float]] = field(default_factory=dict)

    @property
    def coef_raw(self) -> np.ndarray:
        return self.coef_std / self.scale

    @property
    def intercept_raw(self) -> float:
        return float(self.intercept_std - np.sum(self.coef_std * self.mean / self.scale))

    def logit(self, X: np.ndarray) -> np.ndarray:
        return self.intercept_std + ((X - self.mean) / self.scale) @ self.coef_std

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return expit(self.logit(frame[list(FEATURES)].to_numpy(float)))

    def contributions(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Log-odds contribution of each feature relative to the training mean (what moved this name's score)."""
        Z = (frame[list(FEATURES)].to_numpy(float) - self.mean) / self.scale * self.coef_std
        return pd.DataFrame(Z, columns=[f"logodds_contrib_{f}" for f in FEATURES], index=frame.index)

    def in_support(self, frame: pd.DataFrame) -> pd.DataFrame:
        out = {}
        for f in FEATURES:
            lo, hi = self.train_support[f]
            out[f"in_support_{f}"] = frame[f].between(lo, hi)
        return pd.DataFrame(out, index=frame.index)


def _fit_arrays(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    mean, scale = X.mean(axis=0), X.std(axis=0)
    scale = np.where(scale > 0, scale, 1.0)
    # C = inf: unpenalised, so fitted coefficients are directly comparable with the DGP's. On standardised
    # features a mild L2 would barely move them at this sample size, and shrinkage would blur the sign check.
    m = LogisticRegression(C=np.inf, solver="lbfgs", max_iter=2000, tol=1e-10)
    m.fit((X - mean) / scale, y)
    return mean, scale, m.coef_[0].astype(float), float(m.intercept_[0])


def fit(train: pd.DataFrame, support_frame: pd.DataFrame | None = None) -> FittedModel:
    X = train[list(FEATURES)].to_numpy(float)
    y = train["default_12m"].to_numpy(int)
    mean, scale, coef, b = _fit_arrays(X, y)
    ref = train if support_frame is None else support_frame
    support = {f: tuple(float(v) for v in np.percentile(ref[f], SUPPORT_PCTL)) for f in FEATURES}
    return FittedModel(mean=mean, scale=scale, coef_std=coef, intercept_std=b, train_support=support)


def cluster_bootstrap(train: pd.DataFrame, n_boot: int = N_BOOTSTRAP, seed: int = RNG_SEED + 1) -> np.ndarray:
    """Raw-unit coefficients re-fitted on buyer-resampled training sets, shape (n_boot, n_features)."""
    rng = np.random.default_rng(seed)
    ids = train["buyer_id"].unique()
    groups = {b: g for b, g in train.groupby("buyer_id", sort=True)}
    X_by = {b: g[list(FEATURES)].to_numpy(float) for b, g in groups.items()}
    y_by = {b: g["default_12m"].to_numpy(int) for b, g in groups.items()}
    out = np.full((n_boot, len(FEATURES)), np.nan)
    for i in range(n_boot):
        pick = rng.choice(ids, size=len(ids), replace=True)
        X = np.vstack([X_by[b] for b in pick])
        y = np.concatenate([y_by[b] for b in pick])
        if y.min() == y.max():
            continue
        mean, scale, coef, _ = _fit_arrays(X, y)
        out[i] = coef / scale
    return out


def coefficient_table(model: FittedModel, dgp: DGP, intercept_true: float, boot: np.ndarray) -> pd.DataFrame:
    rows = []
    for k, f in enumerate(FEATURES):
        key, inc = ODDS_RATIO_KEYS[f]
        true_b, fit_b = dgp.betas[f], float(model.coef_raw[k])
        b = boot[:, k][~np.isnan(boot[:, k])]
        rows.append({
            "term": f,
            "label": FEATURE_LABELS[f],
            "increment": inc,
            "dgp_param_key": key,
            "beta_raw_true": true_b,
            "beta_raw_fitted": fit_b,
            "beta_std_fitted": float(model.coef_std[k]),
            "odds_ratio_per_increment_true": float(np.exp(true_b * inc)),
            "odds_ratio_per_increment_fitted": float(np.exp(fit_b * inc)),
            "odds_ratio_per_1sd_fitted": float(np.exp(model.coef_std[k])),
            "odds_ratio_per_increment_boot_p2_5": float(np.exp(np.percentile(b, 2.5) * inc)),
            "odds_ratio_per_increment_boot_p97_5": float(np.exp(np.percentile(b, 97.5) * inc)),
            "sign_true": int(np.sign(true_b)),
            "sign_fitted": int(np.sign(fit_b)),
            "sign_match": bool(np.sign(true_b) == np.sign(fit_b)),
            "boot_sign_match_share": float(np.mean(np.sign(b) == np.sign(true_b))),
            "train_mean": float(model.mean[k]),
            "train_sd": float(model.scale[k]),
            "support_p01": model.train_support[f][0],
            "support_p99": model.train_support[f][1],
        })
    rows.append({"term": "intercept", "label": "Intercept (raw units)", "beta_raw_true": intercept_true,
                 "beta_raw_fitted": model.intercept_raw, "beta_std_fitted": model.intercept_std,
                 "sign_true": int(np.sign(intercept_true)), "sign_fitted": int(np.sign(model.intercept_raw)),
                 "sign_match": bool(np.sign(intercept_true) == np.sign(model.intercept_raw))})
    out = pd.DataFrame(rows)
    out["label_synthetic"] = SYNTH_LABEL
    return out


def fit_metrics(model: FittedModel, data: pd.DataFrame) -> pd.DataFrame:
    """Fit to its own synthetic process — NOT evidence of real predictive power (every row says so)."""
    train_rate = float(data.loc[data["split"] == "train", "default_12m"].mean())
    rows = []
    for split in ("train", "test"):
        d = data[data["split"] == split]
        y = d["default_12m"].to_numpy(int)
        p = model.predict(d)
        t = d["true_pd_12m_frac"].to_numpy(float)
        vals = {
            "n_obs": len(d),
            "n_buyers": d["buyer_id"].nunique(),
            "n_defaults": int(y.sum()),
            "default_rate_observed": float(y.mean()),
            "pd_mean_fitted": float(p.mean()),
            "pd_mean_true": float(t.mean()),
            "auc_fitted": float(roc_auc_score(y, p)),
            "auc_true_pd_oracle": float(roc_auc_score(y, t)),
            "brier_fitted": float(brier_score_loss(y, p)),
            "brier_true_pd_oracle": float(brier_score_loss(y, t)),
            "brier_constant_train_rate": float(brier_score_loss(y, np.full(len(y), train_rate))),
            "log_loss_fitted": float(log_loss(y, p, labels=[0, 1])),
            "corr_fitted_vs_true_pd": float(np.corrcoef(p, t)[0, 1]),
        }
        for metric, v in vals.items():
            rows.append({"split": split, "metric": metric, "value": float(v)})
    n_train_def = int(data.loc[data["split"] == "train", "default_12m"].sum())
    rows.append({"split": "train", "metric": "events_per_variable", "value": n_train_def / len(FEATURES)})
    out = pd.DataFrame(rows)
    out["note"] = ("fit of the model to the synthetic process that generated its own data; NOT evidence of real "
                   "predictive power. auc_true_pd_oracle is the ceiling a perfect estimate of the DGP would reach.")
    return out


def calibration_table(model: FittedModel, data: pd.DataFrame, n_bins: int = CALIBRATION_BINS) -> pd.DataFrame:
    rows = []
    for split in ("train", "test"):
        d = data[data["split"] == split].copy()
        d["pd_fitted"] = model.predict(d)
        d["bin"] = pd.qcut(d["pd_fitted"].rank(method="first"), n_bins, labels=False) + 1
        for b, g in d.groupby("bin", sort=True):
            rows.append({"split": split, "bin": int(b), "n_obs": len(g), "pd_min": g["pd_fitted"].min(),
                         "pd_max": g["pd_fitted"].max(), "pd_mean_fitted": g["pd_fitted"].mean(),
                         "pd_mean_true": g["true_pd_12m_frac"].mean(), "n_defaults": int(g["default_12m"].sum()),
                         "default_rate_observed": g["default_12m"].mean()})
    out = pd.DataFrame(rows)
    out["label"] = SYNTH_LABEL
    return out


def sample_size_study(dgp: DGP | None = None, buyer_counts=REDRAW_BUYER_COUNTS, n_redraws: int = N_REDRAWS,
                      seed0: int = RNG_SEED + 1000) -> pd.DataFrame:
    """How often a fit on a fresh draw of the SAME DGP recovers every sign — the evidence for the sample size."""
    dgp = dgp or load_dgp()
    rows = []
    for nb in buyer_counts:
        match = np.zeros((n_redraws, len(FEATURES)), bool)
        n_def, auc = np.zeros(n_redraws), np.full(n_redraws, np.nan)
        for r in range(n_redraws):
            d, _ = generate_synthetic(seed=seed0 + r, n_buyers=nb, dgp=dgp)
            tr, te = d[d["split"] == "train"], d[d["split"] == "test"]
            m = fit(tr)
            match[r] = np.sign(m.coef_raw) == np.sign(dgp.beta_vector)
            n_def[r] = tr["default_12m"].sum()
            if te["default_12m"].nunique() == 2:
                auc[r] = roc_auc_score(te["default_12m"], m.predict(te))
        base = {"n_buyers": nb, "n_buyer_quarters": nb * N_SYNTH_QUARTERS, "n_redraws": n_redraws,
                "train_defaults_mean": float(n_def.mean()),
                "events_per_variable_mean": float(n_def.mean() / len(FEATURES)),
                "test_auc_mean": float(np.nanmean(auc)), "test_auc_p05": float(np.nanpercentile(auc, 5)),
                "test_auc_p95": float(np.nanpercentile(auc, 95))}
        rows.append({**base, "term": "all_four", "sign_recovery_share": float(match.all(axis=1).mean())})
        for k, f in enumerate(FEATURES):
            rows.append({**base, "term": f, "sign_recovery_share": float(match[:, k].mean())})
    out = pd.DataFrame(rows)
    out["label"] = SYNTH_LABEL
    return out


# ------------------------------------------------------------------------------------------------ bands
def band_cutoffs() -> dict[str, float]:
    c = config.value("credit_band_pd_upper_frac")
    return {b: float(c[b]) for b in ("A", "B", "C")}


def band_from_pd(pd_frac, cutoffs: dict[str, float] | None = None) -> np.ndarray:
    cutoffs = cutoffs or band_cutoffs()
    p = np.atleast_1d(np.asarray(pd_frac, float))
    out = np.full(p.shape, "D", dtype=object)
    for b in ("C", "B", "A"):
        out[p < cutoffs[b]] = b
    return out


def notch(bands, notches) -> np.ndarray:
    """Downgrade each band by its notch count, floored at D."""
    b = np.atleast_1d(np.asarray(bands, dtype=object))
    n = np.broadcast_to(np.asarray(notches, int), b.shape)
    return np.array([BANDS[min(BANDS.index(x) + int(k), len(BANDS) - 1)] for x, k in zip(b, n)], dtype=object)


def band_policy(band: str) -> dict:
    """The band -> limit policy row (config/params/risk_credit.yaml), as quoted by the risk memo."""
    return {
        "band_max_credit_utilisation_frac": float(config.value("credit_band_max_credit_utilisation_frac")[band]),
        "band_max_advance_reliance_multiple": float(config.value("credit_band_max_advance_reliance_multiple")[band]),
        "band_limit_multiplier": float(config.value("credit_band_limit_multiplier")[band]),
        "band_max_credit_days": int(config.value("credit_band_max_credit_days")[band]),
        "band_review_frequency_days": int(config.value("credit_band_review_frequency_days")[band]),
        "limit_action": str(config.value("credit_band_limit_action")[band]),
    }


def band_policy_table() -> pd.DataFrame:
    cut = band_cutoffs()
    lower = {"A": 0.0, "B": cut["A"], "C": cut["B"], "D": cut["C"]}
    upper = {"A": cut["A"], "B": cut["B"], "C": cut["C"], "D": 1.0}
    return pd.DataFrame([{"band": b, "pd_lower_frac": lower[b], "pd_upper_frac": upper[b], **band_policy(b)}
                         for b in BANDS])


# ------------------------------------------------------------------------------------------------ one call
@dataclass
class ModelRun:
    dgp: DGP
    data: pd.DataFrame
    intercept_true: float
    model: FittedModel
    boot: np.ndarray


def build_model(seed: int = RNG_SEED, dgp: DGP | None = None, n_boot: int = N_BOOTSTRAP) -> ModelRun:
    dgp = dgp or load_dgp()
    data, b0 = generate_synthetic(seed=seed, dgp=dgp)
    train = data[data["split"] == "train"]
    model = fit(train, support_frame=data)
    boot = cluster_bootstrap(train, n_boot=n_boot) if n_boot else np.empty((0, len(FEATURES)))
    return ModelRun(dgp=dgp, data=data, intercept_true=b0, model=model, boot=boot)


def true_pd(dgp: DGP, intercept: float, frame: pd.DataFrame) -> np.ndarray:
    return expit(intercept + frame[list(FEATURES)].to_numpy(float) @ dgp.beta_vector)
