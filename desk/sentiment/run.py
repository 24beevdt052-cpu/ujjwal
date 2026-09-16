"""Phase 7 (MASTER_SPEC Table 7 row 5.2, optional): a weekly headline-sentiment overlay next to LME price action.

What it does. Every real headline in data/processed/headlines_weekly.csv (Google News RSS, P0) is scored with VADER
(vaderSentiment 3.3.2, compound score) twice: raw, exactly as the tool ships, and with a small, pre-declared
metals price-direction lexicon (config/params/risk.yaml `sent_domain_lexicon`) that only ADDS price verbs VADER lacks
("surge", "slump", ...) or FLIPS words VADER signs against price ("deficit", "shortage"). Headlines are aggregated to
W-FRI weeks (the same Saturday..Friday weeks the fetcher filtered on), each week gets a z-score against EARLIER weeks
only, and the weekly score is compared with the weekly LME cash log return (Friday close to Friday close):
contemporaneous and lead/lag correlations over -3..+3 weeks with naive p-values, Fisher intervals and moving-block
bootstrap intervals, plus a pre-declared episode test of whether sentiment turned before the March 2022 spike, the
7-Mar top, the April-May crash fortnight and the 15-Jul trough.

Why VADER and not FinBERT: the spec allows either; VADER is transparent (a word list you can print), deterministic,
needs no model download on a low-memory machine, and its known blind spot for commodity language is exactly what the
published raw-vs-adjusted comparison makes visible.

What this does and doesn't tell you: it describes the TONE of a Google-ranked sample of real headlines each week and
whether that tone moved with, before or after LME aluminium prices over 28 weeks. It is a supporting signal for the
desk notes, not a forecasting model: n = 28 weeks cannot establish a lead, the headline sample is a proxy for the news
flow, and VADER is a general-purpose social-media lexicon, not a commodity model. See docs/70_sentiment_overlay.md.

Run: DESK_OFFLINE=1 .venv/bin/python -c "import desk.sentiment.run as m; m.main()"
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from vaderSentiment.vaderSentiment import SentiText, SentimentIntensityAnalyzer

from desk import RNG_SEED, SIM_LABEL, WINDOW_END, WINDOW_START, config
from desk.paths import DOCS_DIR, PROCESSED_DIR, TABLES_DIR
from desk.sentiment.fetch_news import AUDIT_PATH, CORE_TERMS
from desk.sentiment.fetch_news import OUT_PATH as HEADLINES_PATH

# Model-structure constants fixed by the Phase 7 brief (CONTRACTS §1.6); judgement parameters live in risk.yaml.
MAX_LAG_WEEKS = 3
N_BOOT = 10_000
CI_LEVEL = 0.95
SIG_LEVEL = 0.05
LEAD_WINDOW_WEEKS = MAX_LAG_WEEKS  # the episode test looks at the same three weeks the lead/lag table reaches

MARKET_PATH = PROCESSED_DIR / "market_daily.csv"
EVENTS_PATH = TABLES_DIR / "adverse_event_windows.csv"
DOC_PATH = DOCS_DIR / "70_sentiment_overlay.md"

OUT_SCORED = TABLES_DIR / "sentiment_headlines_scored.csv"
OUT_WEEKLY = TABLES_DIR / "sentiment_weekly.csv"
OUT_LEADLAG = TABLES_DIR / "sentiment_leadlag.csv"
OUT_EPISODES = TABLES_DIR / "sentiment_episodes.csv"
OUT_EPISODE_WEEKS = TABLES_DIR / "sentiment_episode_weeks.csv"
OUT_EXTREMES = TABLES_DIR / "sentiment_week_extremes.csv"
OUT_LEXICON = TABLES_DIR / "sentiment_lexicon.csv"
OUT_SUMMARY = TABLES_DIR / "sentiment_summary.csv"

CHART_VS_LME = "p7_sentiment_vs_lme"
CHART_LEADLAG = "p7_sentiment_leadlag"

# Lead/lag variants: the spec's raw VADER score on every kept headline is the PRIMARY series; the rest are declared
# sensitivities, all reported whatever they show.
VARIANTS: tuple[tuple[str, str, str], ...] = (
    ("vader_all", "mean", "Raw VADER, all headlines (primary)"),
    ("adjusted_all", "adj_mean", "Price-direction adjusted, all headlines"),
    ("vader_core", "core_mean", "Raw VADER, aluminium-chain titles only"),
    ("adjusted_core", "core_adj_mean", "Adjusted, aluminium-chain titles only"),
)
PRIMARY_VARIANT = "vader_all"
EPISODE_VARIANTS = ("vader_all", "adjusted_all")

# Titles where a price-direction word probably moves something other than the metal price (a share price, stocks,
# output). Not used in scoring — only counted and listed so the reader can see how often rule (1) of the lexicon fails.
_SUBJECT_CAVEAT_RX = re.compile(
    r"\b(?:shares?|stocks?|sensex|nifty|inventor(?:y|ies)|output|production|exports?|imports?|profits?|revenues?|"
    r"sales|margins?|earnings)\b",
    re.IGNORECASE,
)

KEY_WEEKS_DOC_WORDS = 15  # doc quotes are cut to this many words ("keep quotes short"); the CSVs keep full titles


@dataclass(frozen=True)
class Settings:
    pos_threshold: float
    neg_threshold: float
    z_min_past_weeks: int
    signal_z_abs: float
    block_weeks: int
    valence_abs: float
    lexicon: dict[str, list[str]]


def settings() -> Settings:
    """Every judgement parameter from the Phase 7 section of config/params/risk.yaml."""
    return Settings(
        pos_threshold=float(config.value("sent_vader_pos_threshold")),
        neg_threshold=float(config.value("sent_vader_neg_threshold")),
        z_min_past_weeks=int(config.value("sent_zscore_min_past_weeks")),
        signal_z_abs=float(config.value("sent_signal_z_abs")),
        block_weeks=int(config.value("sent_bootstrap_block_weeks")),
        valence_abs=float(config.value("sent_domain_valence_abs")),
        lexicon={k: [str(w) for w in v] for k, v in config.value("sent_domain_lexicon").items()},
    )


# ------------------------------------------------------------------------------------------------------- scoring
def domain_overrides(lexicon: dict[str, list[str]], valence_abs: float) -> tuple[dict[str, float], tuple[str, ...]]:
    """(words to set -> valence, words to remove). 'up' = +valence, 'down' = -valence, 'neutral' = removed.

    Removing a neutral word (rather than setting it to 0.0) matters: VADER's booster and "least" rules test lexicon
    MEMBERSHIP, so a 0.0 entry would still behave like a lexicon word.
    """
    groups = {"up": valence_abs, "down": -valence_abs}
    unknown = set(lexicon) - {"up", "down", "neutral"}
    if unknown:
        raise ValueError(f"sent_domain_lexicon has unknown groups {sorted(unknown)}")
    seen: dict[str, str] = {}
    for group, words in lexicon.items():
        for w in words:
            if w != w.lower() or not re.fullmatch(r"[a-z]+", w):
                raise ValueError(f"lexicon word {w!r} must be a single lower-case token (VADER matches lower-cased tokens)")
            if w in seen:
                raise ValueError(f"lexicon word {w!r} listed in both {seen[w]!r} and {group!r}")
            seen[w] = group
    sets = {w: groups[g] for w, g in seen.items() if g in groups}
    removed = tuple(w for w, g in seen.items() if g == "neutral")
    return sets, removed


def make_analyzers(s: Settings) -> tuple[SentimentIntensityAnalyzer, SentimentIntensityAnalyzer]:
    """(raw VADER, VADER with the domain overlay). Separate instances: the raw lexicon is never mutated."""
    raw = SentimentIntensityAnalyzer()
    adj = SentimentIntensityAnalyzer()
    sets, removed = domain_overrides(s.lexicon, s.valence_abs)
    lex = dict(adj.lexicon)
    lex.update(sets)
    for w in removed:
        lex.pop(w, None)
    adj.lexicon = lex
    return raw, adj


def lexicon_table(raw: SentimentIntensityAnalyzer, s: Settings) -> pd.DataFrame:
    """One row per overlay word: VADER's own valence, the adjusted one, and whether it was added / flipped / removed."""
    sets, removed = domain_overrides(s.lexicon, s.valence_abs)
    group_of = {w: g for g, ws in s.lexicon.items() for w in ws}
    rows = []
    for w in list(sets) + list(removed):
        vader = raw.lexicon.get(w)
        new = sets.get(w)
        if w in removed:
            action = "removed" if vader is not None else "no_op"
        elif vader is None:
            action = "added"
        elif math.copysign(1.0, vader) != math.copysign(1.0, new):
            action = "flipped"
        else:
            action = "rescaled"
        rows.append({"word": w, "group": group_of[w], "vader_valence": vader, "adjusted_valence": new, "action": action})
    return pd.DataFrame(rows)


def tokens(title: str) -> list[str]:
    """VADER's own tokenisation, lower-cased — so a recorded lexicon hit is exactly a word VADER looked up."""
    return [t.lower() for t in SentiText(title).words_and_emoticons]


def score_titles(titles: pd.Series, raw: SentimentIntensityAnalyzer, adj: SentimentIntensityAnalyzer,
                 domain_words: frozenset[str]) -> pd.DataFrame:
    rows = []
    for title in titles:
        r = raw.polarity_scores(title)
        a = adj.polarity_scores(title)
        hits = sorted({t for t in tokens(title) if t in domain_words})
        rows.append({
            "vader_compound": r["compound"], "vader_pos": r["pos"], "vader_neu": r["neu"], "vader_neg": r["neg"],
            "adj_compound": a["compound"], "lexicon_hits": ";".join(hits),
        })
    return pd.DataFrame(rows, index=titles.index)


def load_headlines() -> pd.DataFrame:
    """P0 headlines joined 1:1 to their audit row (relevance terms, later-date flag). Raises if the join is not exact."""
    h = pd.read_csv(HEADLINES_PATH, dtype=str, keep_default_na=False)
    audit = pd.read_csv(AUDIT_PATH, dtype=str, keep_default_na=False,
                        usecols=["week_end", "published_utc", "source", "title", "link", "relevance_match",
                                 "cites_later_date", "status"])
    kept = audit[audit["status"] == "kept"].drop(columns="status")
    keys = ["week_end", "published_utc", "source", "title", "link"]
    m = h.merge(kept, on=keys, how="left", validate="one_to_one", indicator=True)
    if (m["_merge"] != "both").any() or len(m) != len(h):
        raise ValueError("headlines_weekly.csv and the kept rows of _audit_headlines.csv do not match 1:1; re-run P0 news")
    m = m.drop(columns="_merge")
    m["core_chain"] = m["relevance_match"].map(lambda s: bool(set(s.split("|")) & set(CORE_TERMS)))
    m["cites_later_date"] = m["cites_later_date"].eq("True")
    return m


def score_headlines(s: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(scored headlines, lexicon table)."""
    raw, adj = make_analyzers(s)
    h = load_headlines()
    domain_words = frozenset(w for ws in s.lexicon.values() for w in ws)
    scored = pd.concat([h, score_titles(h["title"], raw, adj, domain_words)], axis=1)
    scored["vader_class"] = classify(scored["vader_compound"], s)
    scored["adj_class"] = classify(scored["adj_compound"], s)
    scored["lexicon_subject_caveat"] = scored["lexicon_hits"].ne("") & scored["title"].str.contains(_SUBJECT_CAVEAT_RX)
    cols = ["week_end", "published_utc", "source", "title", "query", "relevance_match", "core_chain",
            "cites_later_date", "vader_compound", "vader_pos", "vader_neu", "vader_neg", "vader_class",
            "adj_compound", "adj_class", "lexicon_hits", "lexicon_subject_caveat", "link"]
    scored = scored[cols].sort_values(["week_end", "published_utc", "source", "title"], kind="mergesort")
    lex = lexicon_table(raw, s)
    hits = scored["lexicon_hits"][scored["lexicon_hits"] != ""].str.split(";").explode().value_counts()
    lex["n_headlines_hit"] = lex["word"].map(hits).fillna(0).astype(int)
    return scored.reset_index(drop=True), lex


def classify(compound: pd.Series, s: Settings) -> pd.Series:
    return pd.Series(np.select([compound >= s.pos_threshold, compound <= s.neg_threshold], ["positive", "negative"],
                               default="neutral"), index=compound.index)


# ------------------------------------------------------------------------------------------------- weekly series
def weekly_aggregate(scored: pd.DataFrame, col: str, s: Settings, weeks: list[str], prefix: str = "") -> pd.DataFrame:
    """n, mean, median, positive / negative / neutral shares of one score column per week_end (weeks with no
    headline get n = 0 and blank statistics)."""
    x = scored[["week_end", col]].copy()
    x["_pos"] = (x[col] >= s.pos_threshold).astype(float)
    x["_neg"] = (x[col] <= s.neg_threshold).astype(float)
    g = x.groupby("week_end")
    out = pd.DataFrame({
        f"{prefix}n": g.size(),
        f"{prefix}mean": g[col].mean(),
        f"{prefix}median": g[col].median(),
        f"{prefix}se": g[col].std(ddof=1) / np.sqrt(g.size()),
        f"{prefix}pos_share": g["_pos"].mean(),
        f"{prefix}neg_share": g["_neg"].mean(),
    }).reindex(weeks)
    out[f"{prefix}neutral_share"] = 1.0 - out[f"{prefix}pos_share"] - out[f"{prefix}neg_share"]
    out[f"{prefix}n"] = out[f"{prefix}n"].fillna(0).astype(int)
    return out


def past_only_zscore(x: pd.Series, min_past: int) -> pd.Series:
    """z_t = (x_t - mean(x_0..x_{t-1})) / sd(x_0..x_{t-1}); blank until `min_past` earlier non-blank weeks exist.

    The reference excludes week t itself and every later week, so the z-score dated t uses nothing published after
    Friday t.
    """
    past = x.shift(1)
    mu = past.expanding(min_periods=min_past).mean()
    sd = past.expanding(min_periods=min_past).std(ddof=1)
    z = (x - mu) / sd.where(sd > 0)
    return z


def week_end_of(date) -> pd.Timestamp:
    """The W-FRI week_end (Saturday..Friday week) containing `date`."""
    return pd.offsets.Week(weekday=4).rollforward(pd.Timestamp(date).normalize())


def weekly_lme(start, end) -> pd.DataFrame:
    """Last LME cash close in each W-FRI week and its log return vs the previous week's last close (DIRECT prices)."""
    m = pd.read_csv(MARKET_PATH, usecols=["date", "lme_cash_usd_t"], parse_dates=["date"])
    m = m.dropna(subset=["lme_cash_usd_t"])
    m = m[(m["date"] >= pd.Timestamp(start) - pd.Timedelta(days=14)) & (m["date"] <= pd.Timestamp(end))]
    m["week_end"] = m["date"].map(week_end_of)
    last = m.sort_values("date").groupby("week_end").tail(1).set_index("week_end")
    full = pd.date_range(last.index.min(), last.index.max(), freq="W-FRI")
    last = last.reindex(full)
    out = pd.DataFrame({
        "lme_close_date": last["date"],
        "lme_cash_usd_t": last["lme_cash_usd_t"],
    }, index=full)
    out["lme_cash_logret"] = np.log(out["lme_cash_usd_t"]).diff()
    out.index.name = "week_end"
    return out


def build_weekly(scored: pd.DataFrame, s: Settings) -> pd.DataFrame:
    weeks = sorted(scored["week_end"].unique())
    idx = pd.DatetimeIndex(pd.to_datetime(weeks))
    raw = weekly_aggregate(scored, "vader_compound", s, weeks)
    adj = weekly_aggregate(scored, "adj_compound", s, weeks, prefix="adj_").drop(columns="adj_n")
    core = scored[scored["core_chain"]]
    core_raw = weekly_aggregate(core, "vader_compound", s, weeks, prefix="core_")[["core_n", "core_mean"]]
    core_adj = weekly_aggregate(core, "adj_compound", s, weeks, prefix="core_adj_")[["core_adj_mean"]]
    w = pd.concat([raw, adj, core_raw, core_adj], axis=1)
    w.index = idx
    w["z_score"] = past_only_zscore(w["mean"], s.z_min_past_weeks)
    w["adj_z_score"] = past_only_zscore(w["adj_mean"], s.z_min_past_weeks)
    g = scored.assign(week_end=pd.to_datetime(scored["week_end"])).groupby("week_end")
    w["n_lexicon_hit"] = g["lexicon_hits"].apply(lambda t: int(t.ne("").sum())).reindex(idx).fillna(0).astype(int)
    w["n_cites_later_date"] = g["cites_later_date"].sum().reindex(idx).fillna(0).astype(int)
    lme = weekly_lme(idx.min() - pd.Timedelta(days=7), idx.max())
    w = w.join(lme, how="left")
    w.insert(0, "week_start", w.index - pd.Timedelta(days=6))
    w.insert(1, "in_window", (w.index >= pd.Timestamp(WINDOW_START)) & (w["week_start"] <= pd.Timestamp(WINDOW_END)))
    w.index.name = "week_end"
    order = ["week_start", "in_window", "n", "mean", "median", "se", "pos_share", "neg_share", "neutral_share",
             "z_score", "adj_mean", "adj_median", "adj_se", "adj_pos_share", "adj_neg_share", "adj_neutral_share",
             "adj_z_score",
             "n_lexicon_hit", "core_n", "core_mean", "core_adj_mean", "n_cites_later_date", "lme_close_date",
             "lme_cash_usd_t", "lme_cash_logret"]
    return w[order]


# ------------------------------------------------------------------------------------------------- lead / lag
def lagged_pairs(x: np.ndarray, y: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Pairs (x_t, y_{t+k}); k > 0 means x (sentiment) LEADS y (the LME return) by k weeks. Blank pairs dropped."""
    n = len(x)
    if abs(k) >= n:
        return np.array([]), np.array([])
    xs, ys = (x[: n - k], y[k:]) if k >= 0 else (x[-k:], y[: n + k])
    ok = np.isfinite(xs) & np.isfinite(ys)
    return xs[ok], ys[ok]


def rowwise_corr(X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    Xd = X - X.mean(axis=1, keepdims=True)
    Yd = Y - Y.mean(axis=1, keepdims=True)
    den = np.sqrt((Xd * Xd).sum(axis=1) * (Yd * Yd).sum(axis=1))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, (Xd * Yd).sum(axis=1) / den, np.nan)


def block_bootstrap_corr(xs: np.ndarray, ys: np.ndarray, block: int, n_boot: int,
                         rng: np.random.Generator) -> np.ndarray:
    """Moving-block bootstrap of the paired weeks: blocks of `block` consecutive pairs, drawn with replacement."""
    n = len(xs)
    b = min(block, n)
    n_blocks = math.ceil(n / b)
    starts = rng.integers(0, n - b + 1, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(b)[None, None, :]).reshape(n_boot, -1)[:, :n]
    return rowwise_corr(xs[idx], ys[idx])


def lead_lag_table(weekly: pd.DataFrame, s: Settings) -> pd.DataFrame:
    y = weekly["lme_cash_logret"].to_numpy(float)
    zcrit = stats.norm.ppf(0.5 + CI_LEVEL / 2)
    q = [100 * (1 - CI_LEVEL) / 2, 100 * (1 + CI_LEVEL) / 2]
    n_tests = 2 * MAX_LAG_WEEKS + 1
    rows = []
    for vi, (variant, col, label) in enumerate(VARIANTS):
        x = weekly[col].to_numpy(float)
        for k in range(-MAX_LAG_WEEKS, MAX_LAG_WEEKS + 1):
            xs, ys = lagged_pairs(x, y, k)
            n = len(xs)
            r, p = stats.pearsonr(xs, ys)
            rho, p_s = stats.spearmanr(xs, ys)
            fz, se = np.arctanh(r), 1.0 / math.sqrt(n - 3)
            rng = np.random.default_rng([RNG_SEED, vi, k + MAX_LAG_WEEKS])
            boot = block_bootstrap_corr(xs, ys, s.block_weeks, N_BOOT, rng)
            lo, hi = np.nanpercentile(boot, q)
            reading = ("same week" if k == 0 else
                       f"sentiment leads LME by {k} week{'s' if k > 1 else ''}" if k > 0 else
                       f"LME leads sentiment by {-k} week{'s' if k < -1 else ''}")
            rows.append({
                "variant": variant, "variant_label": label, "is_primary": variant == PRIMARY_VARIANT,
                "lag_weeks": k, "reading": reading, "n_pairs": n,
                "pearson_r": float(r), "pearson_p_naive": float(p),
                "fisher_ci_lo": float(np.tanh(fz - zcrit * se)), "fisher_ci_hi": float(np.tanh(fz + zcrit * se)),
                "boot_ci_lo": float(lo), "boot_ci_hi": float(hi), "boot_ci_excludes_zero": bool(lo > 0 or hi < 0),
                "boot_valid_draws": int(np.isfinite(boot).sum()),
                "spearman_rho": float(rho), "spearman_p_naive": float(p_s),
                "significant_naive_5pct": bool(p < SIG_LEVEL),
                "significant_bonferroni_7lags": bool(p < SIG_LEVEL / n_tests),
                "n_boot": N_BOOT, "block_weeks": s.block_weeks,
            })
    return pd.DataFrame(rows)


def critical_r(n: int, alpha: float) -> float:
    """|r| needed for a two-sided naive t-test at `alpha` with n pairs (iid assumption)."""
    t = stats.t.ppf(1 - alpha / 2, n - 2)
    return float(t / math.sqrt(n - 2 + t * t))


# --------------------------------------------------------------------------------------------------- episodes
@dataclass(frozen=True)
class Anchor:
    name: str
    anchor_date: pd.Timestamp  # the last close BEFORE the move; lead weeks end on or before this date
    direction: str  # "up" | "down"
    rule: str


def episode_anchors(weekly_prices: pd.DataFrame) -> list[Anchor]:
    """Price turns chosen by rules on prices only (P3 adverse_event_windows.csv + the P4 episode window), never on
    sentiment. Reporting-only, like the tables they come from."""
    ev = pd.read_csv(EVENTS_PATH, usecols=["event", "start", "end"]).set_index("event")
    episodes = {e[0]: (pd.Timestamp(e[1]), pd.Timestamp(e[2])) for e in config.value("var_lead_episodes")}
    sp_start, sp_end = episodes["LME_MARCH_SPIKE"]
    wk = weekly_prices[(weekly_prices.index >= sp_start) & (weekly_prices.index <= sp_end + pd.Timedelta(days=6))]
    spike_week = wk["lme_cash_logret"].idxmax()
    prev_close = weekly_prices["lme_close_date"].shift(1).loc[spike_week]
    return [
        Anchor("MARCH_SPIKE_UP", pd.Timestamp(prev_close), "up",
               f"week with the largest weekly LME cash log return inside var_lead_episodes LME_MARCH_SPIKE "
               f"(week ending {spike_week.date()}, {wk['lme_cash_logret'].max():+.2%}); the move starts after the "
               f"previous week's last close"),
        Anchor("MARCH_TOP", pd.Timestamp(ev.loc["E1_LME_CRASH", "start"]), "down",
               "E1_LME_CRASH start in adverse_event_windows.csv (the all-time-high close)"),
        Anchor("CRASH_FORTNIGHT", pd.Timestamp(ev.loc["E1_CRASH_FORTNIGHT", "start"]), "down",
               "E1_CRASH_FORTNIGHT start in adverse_event_windows.csv (the 10-return window with the worst return)"),
        Anchor("JULY_TROUGH", pd.Timestamp(ev.loc["E1_LME_CRASH", "end"]), "up",
               "E1_LME_CRASH end in adverse_event_windows.csv (the lowest close after the high)"),
    ]


def signal_fires(z: pd.Series, direction: str, thr: float) -> pd.Series:
    return (z >= thr) if direction == "up" else (z <= -thr)


def lead_verdict(n_valid_z: int, n_hits: int) -> str:
    """Declared before any result: no past-only z in the window -> NOT TESTABLE; any hit -> SIGNAL FIRED."""
    if n_valid_z == 0:
        return "NOT TESTABLE"
    return "SIGNAL FIRED" if n_hits else "DID NOT LEAD"


def episode_tables(weekly: pd.DataFrame, s: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Did the past-only z-score point the way of the coming move, in the 3 weeks ending on/before the turn?"""
    prices = weekly_lme(weekly.index.min() - pd.Timedelta(days=120), weekly.index.max())
    anchors = episode_anchors(prices)
    zcols = {"vader_all": ("mean", "z_score"), "adjusted_all": ("adj_mean", "adj_z_score")}
    verdicts, weeks_rows = [], []
    for a in anchors:
        lead_weeks = [w for w in prices.index if w <= a.anchor_date][-LEAD_WINDOW_WEEKS:]
        after = [w for w in prices.index if w > a.anchor_date][:LEAD_WINDOW_WEEKS]
        ret_lead = prices.loc[lead_weeks, "lme_cash_logret"].sum(min_count=1)
        ret_after = prices.loc[after, "lme_cash_logret"].sum(min_count=1)
        for w in lead_weeks + after:
            row = {"anchor": a.name, "anchor_date": a.anchor_date.date(), "direction": a.direction,
                   "role": "lead" if w in lead_weeks else "after", "week_end": w.date(),
                   "lme_cash_usd_t": prices.loc[w, "lme_cash_usd_t"], "lme_cash_logret": prices.loc[w, "lme_cash_logret"]}
            for c in ("n", "mean", "z_score", "adj_mean", "adj_z_score"):
                row[c] = weekly.loc[w, c] if w in weekly.index else np.nan
            row["n"] = int(row["n"]) if pd.notna(row["n"]) else 0
            weeks_rows.append(row)
        # Sensitivity: the register note's first wording — the three weeks strictly before the week containing the
        # anchor date (differs from the base only when the anchor falls on a Friday).
        alt_weeks = [w for w in prices.index if w < week_end_of(a.anchor_date)][-LEAD_WINDOW_WEEKS:]
        for variant in EPISODE_VARIANTS:
            mcol, zcol = zcols[variant]
            z_all = weekly[zcol]
            lead_z = z_all.reindex(lead_weeks)
            valid = lead_z.dropna()
            hits = valid[signal_fires(valid, a.direction, s.signal_z_abs)]
            opposite = "down" if a.direction == "up" else "up"
            contrary = valid[signal_fires(valid, opposite, s.signal_z_abs)]
            others = z_all.drop(index=[w for w in lead_weeks if w in z_all.index]).dropna()
            base = float(signal_fires(others, a.direction, s.signal_z_abs).mean()) if len(others) else np.nan
            chance = 1 - (1 - base) ** len(valid) if len(valid) and np.isfinite(base) else np.nan
            n_with_headlines = int(weekly["n"].reindex(lead_weeks).fillna(0).gt(0).sum())
            verdict = lead_verdict(len(valid), len(hits))
            alt_z = z_all.reindex(alt_weeks).dropna()
            verdict_alt = lead_verdict(len(alt_z), int(signal_fires(alt_z, a.direction, s.signal_z_abs).sum()))
            verdicts.append({
                "anchor": a.name, "anchor_date": a.anchor_date.date(), "direction": a.direction, "rule": a.rule,
                "variant": variant,
                "lead_weeks": ";".join(str(w.date()) for w in lead_weeks),
                "lead_weeks_with_headlines": n_with_headlines,
                "lead_weeks_with_z": len(valid),
                "lead_z_values": ";".join("" if pd.isna(v) else f"{v:+.2f}" for v in lead_z),
                "lead_mean_score": float(weekly[mcol].reindex(lead_weeks).mean()),
                "signal_hit_weeks": ";".join(str(w.date()) for w in hits.index),
                "contrary_hit_weeks": ";".join(str(w.date()) for w in contrary.index),
                "signal_z_abs": s.signal_z_abs,
                "base_rate_other_weeks_frac": base,
                "base_rate_n_weeks": len(others),
                "chance_of_hit_in_window_approx_frac": chance,
                "lme_logret_lead_weeks": ret_lead,
                "lme_logret_next_3_weeks": ret_after,
                "verdict": verdict,
                "lead_weeks_alt_window": ";".join(str(w.date()) for w in alt_weeks),
                "verdict_alt_window": verdict_alt,
            })
    return pd.DataFrame(verdicts), pd.DataFrame(weeks_rows)


# ------------------------------------------------------------------------------------------------ week extremes
def week_extremes(scored: pd.DataFrame, s: Settings, top: int = 2) -> pd.DataFrame:
    """Per week and score: up to `top` most negative (compound <= neg threshold) and most positive (>= pos threshold)
    headlines, verbatim with source — for the desk notes. Ties break on published time then title (deterministic)."""
    rows = []
    for score in ("vader_compound", "adj_compound"):
        for week, g in scored.groupby("week_end", sort=True):
            neg = g[g[score] <= s.neg_threshold].sort_values([score, "published_utc", "title"], kind="mergesort")
            pos = g[g[score] >= s.pos_threshold].sort_values([score, "published_utc", "title"],
                                                             ascending=[False, True, True], kind="mergesort")
            for side, frame in (("most_negative", neg), ("most_positive", pos)):
                for rank, (_, r) in enumerate(frame.head(top).iterrows(), start=1):
                    rows.append({"week_end": week, "score": score, "side": side, "rank": rank,
                                 "compound": r[score], "vader_compound": r["vader_compound"],
                                 "adj_compound": r["adj_compound"], "published_utc": r["published_utc"],
                                 "source": r["source"], "title": r["title"], "lexicon_hits": r["lexicon_hits"],
                                 "cites_later_date": r["cites_later_date"]})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------------------- summary
def ar1(x: pd.Series) -> float:
    x = x.dropna()
    return float(np.corrcoef(x.to_numpy()[:-1], x.to_numpy()[1:])[0, 1])


def noise_share(se: pd.Series, means: pd.Series) -> float:
    """How much of the week-to-week variance of the mean score sampling noise alone would produce (~1 = all noise)."""
    return float((se ** 2).mean() / means.var(ddof=1))


def summary_table(scored: pd.DataFrame, weekly: pd.DataFrame, leadlag: pd.DataFrame, episodes: pd.DataFrame,
                  lexicon: pd.DataFrame) -> pd.DataFrame:
    prim = leadlag[leadlag["variant"] == PRIMARY_VARIANT].set_index("lag_weeks")
    adj = leadlag[leadlag["variant"] == "adjusted_all"].set_index("lag_weeks")
    lead = leadlag[leadlag["lag_weeks"] > 0]
    src_h = "headlines_weekly.csv (Google News RSS; text DIRECT, sample PROXY)"
    rows = [
        ("n_headlines", len(scored), "count", src_h),
        ("n_weeks", len(weekly), "count", src_h),
        ("headlines_per_week_median", float(weekly["n"].median()), "count", src_h),
        ("headlines_per_week_min", int(weekly["n"].min()), "count", src_h),
        ("headlines_per_week_max", int(weekly["n"].max()), "count", src_h),
        ("share_vader_exactly_zero", float((scored["vader_compound"] == 0).mean()), "frac", "VADER 3.3.2"),
        ("share_vader_positive", float((scored["vader_class"] == "positive").mean()), "frac", "VADER 3.3.2"),
        ("share_vader_negative", float((scored["vader_class"] == "negative").mean()), "frac", "VADER 3.3.2"),
        ("share_adj_exactly_zero", float((scored["adj_compound"] == 0).mean()), "frac", "VADER + sent_domain_lexicon"),
        ("share_adj_positive", float((scored["adj_class"] == "positive").mean()), "frac", "VADER + sent_domain_lexicon"),
        ("share_adj_negative", float((scored["adj_class"] == "negative").mean()), "frac", "VADER + sent_domain_lexicon"),
        ("n_headlines_lexicon_hit", int(scored["lexicon_hits"].ne("").sum()), "count", "sent_domain_lexicon"),
        ("n_headlines_class_changed_by_lexicon", int((scored["vader_class"] != scored["adj_class"]).sum()), "count",
         "sent_domain_lexicon"),
        ("n_lexicon_hits_subject_caveat", int(scored["lexicon_subject_caveat"].sum()), "count",
         "title also names shares/stocks/output/trade etc. (price verb may not refer to the metal price)"),
        ("n_lexicon_words_added", int((lexicon["action"] == "added").sum()), "count", "sentiment_lexicon.csv"),
        ("n_lexicon_words_flipped", int((lexicon["action"] == "flipped").sum()), "count", "sentiment_lexicon.csv"),
        ("n_lexicon_words_removed", int((lexicon["action"] == "removed").sum()), "count", "sentiment_lexicon.csv"),
        ("n_headlines_core_chain", int(scored["core_chain"].sum()), "count", "audit relevance_match ∩ fetch_news.CORE_TERMS"),
        ("n_headlines_cites_later_date", int(scored["cites_later_date"].sum()), "count", "P0 audit look-ahead flag"),
        ("weekly_mean_vader_avg", float(weekly["mean"].mean()), "vader_compound", "sentiment_weekly.csv"),
        ("weekly_mean_vader_sd", float(weekly["mean"].std(ddof=1)), "vader_compound", "sentiment_weekly.csv"),
        ("weekly_mean_adj_avg", float(weekly["adj_mean"].mean()), "vader_compound", "sentiment_weekly.csv"),
        ("weekly_mean_adj_sd", float(weekly["adj_mean"].std(ddof=1)), "vader_compound", "sentiment_weekly.csv"),
        ("noise_share_weekly_var_vader", noise_share(weekly["se"], weekly["mean"]), "frac",
         "mean squared standard error of the weekly mean / variance of the weekly means"),
        ("noise_share_weekly_var_adj", noise_share(weekly["adj_se"], weekly["adj_mean"]), "frac",
         "mean squared standard error of the weekly mean / variance of the weekly means"),
        ("n_weeks_95ci_excludes_zero_vader", int(((weekly["mean"].abs() - 1.96 * weekly["se"]) > 0).sum()), "count",
         "weeks whose mean +/- 1.96 standard errors does not straddle zero"),
        ("n_weeks_95ci_excludes_zero_adj", int(((weekly["adj_mean"].abs() - 1.96 * weekly["adj_se"]) > 0).sum()), "count",
         "weeks whose mean +/- 1.96 standard errors does not straddle zero"),
        ("corr_weekly_vader_vs_adj", float(weekly["mean"].corr(weekly["adj_mean"])), "pearson_r", "sentiment_weekly.csv"),
        ("ar1_weekly_vader", ar1(weekly["mean"]), "pearson_r", "sentiment_weekly.csv"),
        ("ar1_weekly_adj", ar1(weekly["adj_mean"]), "pearson_r", "sentiment_weekly.csv"),
        ("ar1_weekly_lme_logret", ar1(weekly["lme_cash_logret"]), "pearson_r", "market_daily.csv lme_cash_usd_t (DIRECT)"),
        ("primary_r_same_week", float(prim.loc[0, "pearson_r"]), "pearson_r", "sentiment_leadlag.csv"),
        ("primary_p_same_week_naive", float(prim.loc[0, "pearson_p_naive"]), "p_value", "sentiment_leadlag.csv"),
        ("adjusted_r_same_week", float(adj.loc[0, "pearson_r"]), "pearson_r", "sentiment_leadlag.csv"),
        ("adjusted_p_same_week_naive", float(adj.loc[0, "pearson_p_naive"]), "p_value", "sentiment_leadlag.csv"),
        ("n_lead_tests", len(lead), "count", "sentiment_leadlag.csv (lags +1..+3, 4 variants)"),
        ("n_lead_tests_naive_5pct", int(lead["significant_naive_5pct"].sum()), "count", "sentiment_leadlag.csv"),
        ("n_lead_tests_bonferroni", int(lead["significant_bonferroni_7lags"].sum()), "count", "sentiment_leadlag.csv"),
        ("n_lead_tests_boot_ci_excludes_zero", int(lead["boot_ci_excludes_zero"].sum()), "count", "sentiment_leadlag.csv"),
        ("n_tests_total", len(leadlag), "count", "sentiment_leadlag.csv"),
        ("n_tests_total_naive_5pct", int(leadlag["significant_naive_5pct"].sum()), "count", "sentiment_leadlag.csv"),
        ("n_tests_total_boot_ci_excludes_zero", int(leadlag["boot_ci_excludes_zero"].sum()), "count",
         "sentiment_leadlag.csv"),
        ("expected_false_positives_naive_5pct", len(leadlag) * SIG_LEVEL, "count", "if no relation existed"),
        ("n_episode_verdicts_signal_fired", int((episodes["verdict"] == "SIGNAL FIRED").sum()), "count", "sentiment_episodes.csv"),
        ("n_episode_verdicts_not_testable", int((episodes["verdict"] == "NOT TESTABLE").sum()), "count", "sentiment_episodes.csv"),
        ("n_episode_verdicts_did_not_lead", int((episodes["verdict"] == "DID NOT LEAD").sum()), "count", "sentiment_episodes.csv"),
    ]
    return pd.DataFrame(rows, columns=["metric", "value", "unit", "source"])


# -------------------------------------------------------------------------------------------------------- charts
def chart_vs_lme(weekly: pd.DataFrame) -> str:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    from desk.reporting.style import PALETTE, save_fig

    ev = pd.read_csv(EVENTS_PATH, usecols=["event", "start", "end"]).set_index("event")
    ath = pd.Timestamp(ev.loc["E1_LME_CRASH", "start"])
    trough = pd.Timestamp(ev.loc["E1_LME_CRASH", "end"])
    cf0, cf1 = pd.Timestamp(ev.loc["E1_CRASH_FORTNIGHT", "start"]), pd.Timestamp(ev.loc["E1_CRASH_FORTNIGHT", "end"])
    daily = pd.read_csv(MARKET_PATH, usecols=["date", "lme_cash_usd_t"], parse_dates=["date"])
    daily = daily[(daily["date"] >= weekly["week_start"].min()) & (daily["date"] <= weekly.index.max())]

    fig, axes = plt.subplots(2, 1, figsize=(11, 8.2), sharex=True)
    panels = (("mean", "(a) Raw VADER compound, weekly mean — the spec's score"),
              ("adj_mean", "(b) VADER + price-direction lexicon (surge/slump/deficit/glut…), weekly mean"))
    mid = weekly.index - pd.Timedelta(days=3)
    lim = float(np.nanmax(np.abs(np.concatenate([
        (weekly["mean"].abs() + 1.96 * weekly["se"]).to_numpy(), (weekly["adj_mean"].abs() + 1.96 * weekly["adj_se"]).to_numpy()])))) * 1.12
    for ax, (col, title) in zip(axes, panels):
        vals = weekly[col]
        colors = [PALETTE["gain"] if v >= 0 else PALETTE["loss"] for v in vals]
        ax.bar(mid, vals, width=5.2, color=colors, alpha=0.75, label="weekly mean score (left)")
        se = weekly["se" if col == "mean" else "adj_se"]
        ax.errorbar(mid, vals, yerr=1.96 * se, fmt="none", ecolor="#595959", elinewidth=0.8, capsize=2,
                    label="±1.96 standard errors (headline sampling noise)")
        ax.axhline(0, color="#404040", lw=0.8)
        ax.set_ylim(-lim, lim)
        ax.set_ylabel("mean compound score")
        ax.set_title(title, loc="left")
        ax.axvspan(cf0, cf1, color=PALETTE["band"], alpha=0.8, zorder=0)
        for d in (ath, trough):
            ax.axvline(d, color=PALETTE["neutral"], ls="--", lw=0.9)
        ax2 = ax.twinx()
        ax2.plot(daily["date"], daily["lme_cash_usd_t"], color=PALETTE["lme"], lw=1.4, label="LME cash, daily (right)")
        ax2.plot(weekly.index, weekly["lme_cash_usd_t"], "o", color=PALETTE["lme"], ms=3)
        ax2.set_ylabel("LME aluminium cash, USD/t")
        ax2.grid(False)
        ax2.spines["right"].set_visible(True)
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=8)
    top = axes[0]
    ytxt = lim * 0.88
    px = daily.set_index("date")["lme_cash_usd_t"]
    top.annotate(f"LME all-time high\n{ath:%d-%b} ${px.loc[ath]:,.0f}",
                 xy=(ath, ytxt), xytext=(ath + pd.Timedelta(days=4), ytxt), fontsize=8, va="top")
    top.annotate(f"crash fortnight\n{cf0:%d-%b}–{cf1:%d-%b}", xy=(cf0, ytxt), xytext=(cf0 + pd.Timedelta(days=1), -ytxt * 0.55),
                 fontsize=8, va="top")
    top.annotate(f"trough {trough:%d-%b}\n${px.loc[trough]:,.0f}",
                 xy=(trough, ytxt), xytext=(trough + pd.Timedelta(days=4), -ytxt * 0.55), fontsize=8, va="top")
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%d-%b-%y"))
    axes[1].set_xlabel("week (W-FRI, bars centred mid-week); 28 weeks, "
                       f"{int(weekly['n'].sum())} real headlines, {int(weekly['n'].min())}–{int(weekly['n'].max())} per week")
    fig.suptitle("Headline sentiment vs LME aluminium cash, weeks ending 25-Feb-2022 → 2-Sep-2022 "
                 "(supporting signal, not a forecast)", fontweight="bold", x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    return save_fig(fig, CHART_VS_LME, "Headlines: Google News RSS titles (DIRECT text; sample PROXY) · VADER 3.3.2 · "
                                       "LME cash: Westmetall (DIRECT) · events: adverse_event_windows.csv")


def chart_leadlag(leadlag: pd.DataFrame) -> str:
    import matplotlib.pyplot as plt

    from desk.reporting.style import PALETTE, save_fig

    styles = {
        "vader_all": (-0.21, PALETTE["lme"], "o", True),
        "adjusted_all": (-0.07, PALETTE["mcx"], "s", True),
        "vader_core": (0.07, PALETTE["lme"], "o", False),
        "adjusted_core": (0.21, PALETTE["mcx"], "s", False),
    }
    fig, ax = plt.subplots(figsize=(11, 5.6))
    lags = np.arange(-MAX_LAG_WEEKS, MAX_LAG_WEEKS + 1)
    n_by_lag = leadlag[leadlag["variant"] == PRIMARY_VARIANT].set_index("lag_weeks")["n_pairs"]
    naive = np.array([critical_r(int(n_by_lag[k]), SIG_LEVEL) for k in lags])
    bonf = np.array([critical_r(int(n_by_lag[k]), SIG_LEVEL / len(lags)) for k in lags])
    ax.fill_between(np.append(lags - 0.5, lags[-1] + 0.5), np.append(-naive, -naive[-1]), np.append(naive, naive[-1]),
                    step="post", color=PALETTE["band"], alpha=0.9, label="naive 5 % band (|r| inside = not significant, iid)")
    ax.step(np.append(lags - 0.5, lags[-1] + 0.5), np.append(bonf, bonf[-1]), where="post", color=PALETTE["neutral"],
            ls=":", lw=1, label="Bonferroni 5 %/7 lags")
    ax.step(np.append(lags - 0.5, lags[-1] + 0.5), -np.append(bonf, bonf[-1]), where="post", color=PALETTE["neutral"],
            ls=":", lw=1)
    for variant, (off, color, marker, filled) in styles.items():
        d = leadlag[leadlag["variant"] == variant].sort_values("lag_weeks")
        label = d["variant_label"].iloc[0]
        yerr = np.clip(np.vstack([d["pearson_r"] - d["boot_ci_lo"], d["boot_ci_hi"] - d["pearson_r"]]), 0, None)
        ax.errorbar(d["lag_weeks"] + off, d["pearson_r"], yerr=yerr, fmt=marker, color=color, ms=6, capsize=3,
                    mfc=color if filled else "white", lw=1.1, label=f"{label} (95 % block-bootstrap CI)")
    ax.axhline(0, color="#404040", lw=0.8)
    ax.axvline(0, color=PALETTE["neutral"], lw=0.6)
    ax.set_xticks(lags)
    ax.set_xticklabels([f"{k:+d}" if k else "0" for k in lags])
    ax.set_xlim(lags[0] - 0.5, lags[-1] + 0.5)
    ax.set_ylim(-1, 1)
    ax.set_xlabel("lag k (weeks): corr(sentiment in week t, LME cash log return in week t+k)")
    ax.set_ylabel("Pearson r")
    ax.text(-MAX_LAG_WEEKS - 0.45, -0.93, "← k < 0: LME moved first, headlines followed", fontsize=8.5, color="#404040")
    ax.text(MAX_LAG_WEEKS + 0.45, -0.93, "k > 0: sentiment first (a lead) →", fontsize=8.5, color="#404040", ha="right")
    ax.set_title(f"Lead/lag: weekly headline sentiment vs LME cash returns (n = {int(n_by_lag[0])} weeks at k = 0, "
                 f"{int(n_by_lag[MAX_LAG_WEEKS])} at |k| = {MAX_LAG_WEEKS})", loc="left")
    ax.legend(loc="upper left", fontsize=7.5, ncol=2)
    fig.tight_layout()
    return save_fig(fig, CHART_LEADLAG, f"sentiment_leadlag.csv · moving-block bootstrap, {N_BOOT:,} draws, "
                                        "seed desk.RNG_SEED · 28 tests: ~1.4 false positives expected at 5 %")


# ----------------------------------------------------------------------------------------------- doc generated blocks
def _md_escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _short(title: str, words: int = KEY_WEEKS_DOC_WORDS) -> str:
    parts = title.split()
    return " ".join(parts) if len(parts) <= words else " ".join(parts[:words]) + " …"


def _lag(k: int) -> str:
    return f"{k:+d}" if k else "0"


def _z_list(values: str) -> str:
    parts = values.split(";")
    return "—" if not any(parts) else ", ".join(v or "n/a" for v in parts)


def _fmt(x, spec: str) -> str:
    return "" if x is None or (isinstance(x, float) and not np.isfinite(x)) else format(x, spec)


def doc_blocks(weekly: pd.DataFrame, leadlag: pd.DataFrame, episodes: pd.DataFrame, extremes: pd.DataFrame,
               key_weeks: list[tuple[str, str]]) -> dict[str, str]:
    """Markdown tables regenerated into docs/70_sentiment_overlay.md between marker comments (numbers never drift)."""
    L = ["| week_end | n | raw mean | raw z (past-only) | adj mean | adj z | pos / neg share (raw) | LME cash USD/t | LME log ret |",
         "|---|---|---|---|---|---|---|---|---|"]
    for w, r in weekly.iterrows():
        L.append(f"| {w.date()} | {int(r['n'])} | {r['mean']:+.3f} | {_fmt(r['z_score'], '+.2f') or '—'} | {r['adj_mean']:+.3f} | "
                 f"{_fmt(r['adj_z_score'], '+.2f') or '—'} | {r['pos_share']:.0%} / {r['neg_share']:.0%} | "
                 f"{r['lme_cash_usd_t']:,.1f} | {r['lme_cash_logret']:+.2%} |")
    weekly_block = "\n".join(L)

    L = ["| variant | k | reading | n | r | naive p | Fisher 95 % CI | block-bootstrap 95 % CI | Spearman ρ | sig. naive 5 % | sig. Bonferroni |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in leadlag.iterrows():
        L.append(f"| {r['variant']} | {_lag(r['lag_weeks'])} | {r['reading']} | {r['n_pairs']} | {r['pearson_r']:+.2f} | "
                 f"{r['pearson_p_naive']:.3f} | [{r['fisher_ci_lo']:+.2f}, {r['fisher_ci_hi']:+.2f}] | "
                 f"[{r['boot_ci_lo']:+.2f}, {r['boot_ci_hi']:+.2f}] | {r['spearman_rho']:+.2f} | "
                 f"{'yes' if r['significant_naive_5pct'] else 'no'} | {'yes' if r['significant_bonferroni_7lags'] else 'no'} |")
    leadlag_block = "\n".join(L)

    L = ["| anchor (move after this close) | direction | variant | lead weeks (≤ anchor) | weeks with headlines / z | lead z-scores | declared verdict | base rate in other weeks | chance of ≥1 hit | opposite-way signals in the same weeks | LME next 3 weeks (log) |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in episodes.iterrows():
        L.append(f"| {r['anchor']} {r['anchor_date']} | {r['direction']} | {r['variant']} | {r['lead_weeks'].replace(';', ', ')} | "
                 f"{r['lead_weeks_with_headlines']} / {r['lead_weeks_with_z']} | {_z_list(r['lead_z_values'])} | "
                 f"**{r['verdict']}**{' (' + r['signal_hit_weeks'].replace(';', ', ') + ')' if r['signal_hit_weeks'] else ''} | "
                 f"{_fmt(r['base_rate_other_weeks_frac'], '.0%')} of {r['base_rate_n_weeks']} | "
                 f"{_fmt(r['chance_of_hit_in_window_approx_frac'], '.0%')} | "
                 f"{r['contrary_hit_weeks'].replace(';', ', ') if r['contrary_hit_weeks'] else 'none'} | "
                 f"{r['lme_logret_next_3_weeks']:+.1%} |")
    episode_block = "\n".join(L)

    L = ["| week_end | why this week | side | raw | adj | source | title (verbatim; cut at 15 words) |",
         "|---|---|---|---|---|---|---|"]
    ex = extremes[extremes["score"] == "vader_compound"]
    for week, why in key_weeks:
        sub = ex[(ex["week_end"] == week) & (ex["rank"] == 1)]
        for side in ("most_negative", "most_positive"):
            r = sub[sub["side"] == side]
            if r.empty:
                L.append(f"| {week} | {why} | {side.replace('_', ' ')} | — | — | — | (no headline past the VADER threshold) |")
                continue
            r = r.iloc[0]
            L.append(f"| {week} | {why} | {side.replace('_', ' ')} | {r['vader_compound']:+.3f} | {r['adj_compound']:+.3f} | "
                     f"{_md_escape(r['source'])} | {_md_escape(_short(r['title']))} |")
    ex_adj = extremes[extremes["score"] == "adj_compound"]
    L.append("")
    L.append("Same key weeks, ranked on the **adjusted** score instead (where it picks a different headline):")
    L.append("")
    L.append("| week_end | side | raw | adj | lexicon words hit | source | title (verbatim; cut at 15 words) |")
    L.append("|---|---|---|---|---|---|---|")
    for week, _ in key_weeks:
        for side in ("most_negative", "most_positive"):
            a = ex_adj[(ex_adj["week_end"] == week) & (ex_adj["rank"] == 1) & (ex_adj["side"] == side)]
            v = ex[(ex["week_end"] == week) & (ex["rank"] == 1) & (ex["side"] == side)]
            if a.empty or (not v.empty and a.iloc[0]["title"] == v.iloc[0]["title"]):
                continue
            a = a.iloc[0]
            L.append(f"| {week} | {side.replace('_', ' ')} | {a['vader_compound']:+.3f} | {a['adj_compound']:+.3f} | "
                     f"{a['lexicon_hits'] or '—'} | {_md_escape(a['source'])} | {_md_escape(_short(a['title']))} |")
    headlines_block = "\n".join(L)
    return {"WEEKLY": weekly_block, "LEADLAG": leadlag_block, "EPISODES": episode_block, "HEADLINES": headlines_block}


def key_weeks_for_doc(weekly: pd.DataFrame, episodes: pd.DataFrame) -> list[tuple[str, str]]:
    """Key weeks picked by price rules (biggest up and down week, the ATH week, the crash-fortnight weeks, the trough
    week and the week after it) plus any week where the episode lead rule fired on the primary score (labelled as
    selected by sentiment)."""
    ev = pd.read_csv(EVENTS_PATH, usecols=["event", "start", "end"]).set_index("event")
    ath = week_end_of(ev.loc["E1_LME_CRASH", "start"])
    trough = week_end_of(ev.loc["E1_LME_CRASH", "end"])
    cf0, cf1 = pd.Timestamp(ev.loc["E1_CRASH_FORTNIGHT", "start"]), pd.Timestamp(ev.loc["E1_CRASH_FORTNIGHT", "end"])
    up = weekly["lme_cash_logret"].idxmax()
    down = weekly["lme_cash_logret"].idxmin()
    picks = [(up, f"largest weekly LME rise ({weekly.loc[up, 'lme_cash_logret']:+.1%})"),
             (ath, "LME all-time high (7-Mar) and first crash days"),
             (down, f"largest weekly LME fall ({weekly.loc[down, 'lme_cash_logret']:+.1%})")]
    for w in weekly.index:
        if week_end_of(cf0) < w <= week_end_of(cf1):
            picks.append((w, "crash fortnight"))
    picks += [(trough, "LME trough (15-Jul)"), (trough + pd.Timedelta(days=7), "week after the trough")]
    lo, hi = weekly["mean"].idxmin(), weekly["mean"].idxmax()
    picks += [(lo, f"lowest weekly raw score ({weekly.loc[lo, 'mean']:+.3f}; week chosen by SENTIMENT, not price)"),
              (hi, f"highest weekly raw score ({weekly.loc[hi, 'mean']:+.3f}; week chosen by SENTIMENT, not price)")]
    fired = episodes[(episodes["variant"] == PRIMARY_VARIANT) & (episodes["signal_hit_weeks"] != "")]
    for r in fired.itertuples():
        for d in r.signal_hit_weeks.split(";"):
            picks.append((pd.Timestamp(d), f"lead rule fired before {r.anchor} (week chosen by SENTIMENT, not price)"))
    seen, out = set(), []
    for w, why in sorted(picks, key=lambda p: p[0]):
        if w in weekly.index and w not in seen:
            seen.add(w)
            out.append((str(w.date()), why))
        elif w in seen:
            out = [(d, f"{y}; {why}") if d == str(w.date()) else (d, y) for d, y in out]
    return out


def write_doc_blocks(blocks: dict[str, str], path: Path = DOC_PATH) -> bool:
    if not path.exists():
        print(f"[sentiment] {path.name} missing — generated tables not written into the doc")
        return False
    text = path.read_text(encoding="utf-8")
    for name, body in blocks.items():
        start = f"<!-- {name}:START (generated by desk.sentiment.run; do not hand-edit) -->"
        end = f"<!-- {name}:END -->"
        if start not in text or end not in text:
            print(f"[sentiment] marker {name} not found in {path.name}; block skipped")
            continue
        head, rest = text.split(start, 1)
        _, tail = rest.split(end, 1)
        text = f"{head}{start}\n\n{body}\n\n{end}{tail}"
    path.write_text(text, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------------------------------------- stage
def build() -> dict[str, pd.DataFrame]:
    """Every table, computed in memory (no files written) — tests call this to check determinism."""
    s = settings()
    scored, lexicon = score_headlines(s)
    weekly = build_weekly(scored, s)
    leadlag = lead_lag_table(weekly, s)
    episodes, episode_weeks = episode_tables(weekly, s)
    extremes = week_extremes(scored, s)
    summary = summary_table(scored, weekly, leadlag, episodes, lexicon)
    return {"scored": scored, "weekly": weekly, "leadlag": leadlag, "episodes": episodes,
            "episode_weeks": episode_weeks, "extremes": extremes, "lexicon": lexicon, "summary": summary}


def _write(df: pd.DataFrame, path: Path, index: bool = False) -> None:
    out = df.copy()
    if index:
        out = out.reset_index()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    out.to_csv(path, index=False, float_format="%.6g", lineterminator="\n")


def main() -> None:
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    t = build()
    _write(t["scored"], OUT_SCORED)
    _write(t["weekly"], OUT_WEEKLY, index=True)
    _write(t["leadlag"], OUT_LEADLAG)
    _write(t["episodes"], OUT_EPISODES)
    _write(t["episode_weeks"], OUT_EPISODE_WEEKS)
    _write(t["extremes"], OUT_EXTREMES)
    _write(t["lexicon"], OUT_LEXICON)
    _write(t["summary"], OUT_SUMMARY)
    chart_vs_lme(t["weekly"])
    chart_leadlag(t["leadlag"])
    write_doc_blocks(doc_blocks(t["weekly"], t["leadlag"], t["episodes"], t["extremes"], key_weeks_for_doc(t["weekly"], t["episodes"])))
    prim = t["leadlag"][t["leadlag"]["variant"] == PRIMARY_VARIANT].set_index("lag_weeks")
    print(f"[sentiment] {SIM_LABEL} | {len(t['scored'])} headlines, {len(t['weekly'])} weeks | primary r by lag: "
          + ", ".join(f"{k:+d}:{prim.loc[k, 'pearson_r']:+.2f}" for k in prim.index)
          + " | episodes: " + ", ".join(f"{r.anchor}/{r.variant}={r.verdict}" for r in t["episodes"].itertuples()))


if __name__ == "__main__":
    main()
