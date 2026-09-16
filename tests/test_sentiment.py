"""Phase 7 sentiment overlay (MASTER_SPEC Table 7 row 5.2) — the claims docs/70_sentiment_overlay.md makes:

* the stage is deterministic: two builds agree, and a rebuild is byte-identical to the published CSVs;
* the weekly score is plain arithmetic on the scored headlines, and the weekly LME return rebuilds from the panel;
* the z-score dated week t uses nothing after week t, and the episode verdicts use only weeks up to the anchor close;
* the lead/lag sign convention is what the tables say (k > 0 = sentiment first);
* the domain lexicon only adds missing words, flips wrongly-signed ones or removes one, and never touches raw VADER;
* every headline is scored verbatim and every headline quoted in the doc is a real row of the P0 file.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from desk import SIM_LABEL, config
from desk.paths import PROCESSED_DIR, TABLES_DIR
from desk.sentiment import run

OWN = ("sentiment_headlines_scored.csv", "sentiment_weekly.csv", "sentiment_leadlag.csv", "sentiment_episodes.csv",
       "sentiment_episode_weeks.csv", "sentiment_week_extremes.csv", "sentiment_lexicon.csv", "sentiment_summary.csv")
UPSTREAM = (PROCESSED_DIR / "headlines_weekly.csv", PROCESSED_DIR / "market_daily.csv", run.AUDIT_PATH,
            TABLES_DIR / "adverse_event_windows.csv")


def _need_upstream() -> None:
    missing = [str(p) for p in UPSTREAM if not p.exists()]
    if missing:
        pytest.skip(f"upstream inputs missing: {missing}")


def _need_own() -> None:
    missing = [f for f in OWN if not (TABLES_DIR / f).exists()]
    if missing:
        pytest.skip(f"run desk.sentiment.run first; missing {missing}")


@pytest.fixture(scope="module")
def settings() -> run.Settings:
    return run.settings()


@pytest.fixture(scope="module")
def built() -> dict[str, pd.DataFrame]:
    _need_upstream()
    return run.build()


# ----------------------------------------------------------------------------------------------- determinism
def test_build_is_deterministic(built):
    again = run.build()
    for name, frame in built.items():
        pd.testing.assert_frame_equal(frame, again[name], obj=name)


def test_rebuild_is_byte_identical_to_published_tables(built, tmp_path):
    _need_own()
    written = {
        "sentiment_headlines_scored.csv": (built["scored"], False),
        "sentiment_weekly.csv": (built["weekly"], True),
        "sentiment_leadlag.csv": (built["leadlag"], False),
        "sentiment_episodes.csv": (built["episodes"], False),
        "sentiment_episode_weeks.csv": (built["episode_weeks"], False),
        "sentiment_week_extremes.csv": (built["extremes"], False),
        "sentiment_lexicon.csv": (built["lexicon"], False),
        "sentiment_summary.csv": (built["summary"], False),
    }
    assert set(written) == set(OWN)
    for fname, (frame, index) in written.items():
        run._write(frame, tmp_path / fname, index=index)
        assert (tmp_path / fname).read_bytes() == (TABLES_DIR / fname).read_bytes(), fname


def test_bootstrap_is_seeded_and_repeatable():
    x = np.arange(20, dtype=float)
    y = np.sin(x)
    a = run.block_bootstrap_corr(x, y, 3, 500, np.random.default_rng([1, 2, 3]))
    b = run.block_bootstrap_corr(x, y, 3, 500, np.random.default_rng([1, 2, 3]))
    np.testing.assert_array_equal(a, b)
    assert a.shape == (500,) and np.all((a[np.isfinite(a)] >= -1 - 1e-12) & (a[np.isfinite(a)] <= 1 + 1e-12))


# ------------------------------------------------------------------------------------------- weekly aggregation
def test_weekly_aggregation_by_hand(settings):
    scored = pd.DataFrame({
        "week_end": ["2022-03-04"] * 4 + ["2022-03-18"] * 3,
        "vader_compound": [0.05, -0.05, 0.0, 0.5, -0.4, -0.04, 0.2],
    })
    weeks = ["2022-03-04", "2022-03-11", "2022-03-18"]
    w = run.weekly_aggregate(scored, "vader_compound", settings, weeks)
    assert list(w["n"]) == [4, 0, 3]
    assert w.loc["2022-03-04", "mean"] == pytest.approx(0.125)
    assert w.loc["2022-03-04", "median"] == pytest.approx(0.025)
    # threshold equality counts (VADER README: >= 0.05 positive, <= -0.05 negative)
    assert w.loc["2022-03-04", "pos_share"] == pytest.approx(0.5)
    assert w.loc["2022-03-04", "neg_share"] == pytest.approx(0.25)
    assert w.loc["2022-03-04", "neutral_share"] == pytest.approx(0.25)
    assert w.loc["2022-03-04", "se"] == pytest.approx(np.std([0.05, -0.05, 0.0, 0.5], ddof=1) / 2)
    assert w.loc["2022-03-18", "pos_share"] == pytest.approx(1 / 3)
    assert w.loc["2022-03-18", "neg_share"] == pytest.approx(1 / 3)
    assert w.loc["2022-03-11", ["mean", "median", "pos_share", "neg_share"]].isna().all()


def test_published_weekly_table_reaggregates_from_scored_headlines(built, settings):
    scored, weekly = built["scored"], built["weekly"]
    assert int(weekly["n"].sum()) == len(scored) == 649
    assert len(weekly) == 28 and weekly.index.is_monotonic_increasing
    assert (weekly.index.dayofweek == 4).all()  # W-FRI week ends
    g = scored.groupby("week_end")
    for col, src in (("mean", "vader_compound"), ("adj_mean", "adj_compound")):
        expect = g[src].mean()
        np.testing.assert_allclose(weekly[col].to_numpy(), expect.reindex(weekly.index.strftime("%Y-%m-%d")).to_numpy())
    pos = g["vader_compound"].apply(lambda s: (s >= settings.pos_threshold).mean())
    np.testing.assert_allclose(weekly["pos_share"].to_numpy(), pos.to_numpy())
    core = scored[scored["core_chain"]].groupby("week_end")["vader_compound"].mean()
    np.testing.assert_allclose(weekly["core_mean"].to_numpy(), core.reindex(weekly.index.strftime("%Y-%m-%d")).to_numpy())
    np.testing.assert_allclose(weekly[["pos_share", "neg_share", "neutral_share"]].sum(axis=1), 1.0)


def test_weekly_lme_returns_rebuild_from_panel(built):
    weekly = built["weekly"]
    m = pd.read_csv(PROCESSED_DIR / "market_daily.csv", usecols=["date", "lme_cash_usd_t"], parse_dates=["date"])
    m = m.dropna().set_index("date")["lme_cash_usd_t"]
    for w, r in weekly.iterrows():
        in_week = m[(m.index > w - pd.Timedelta(days=7)) & (m.index <= w)]
        prev = m[m.index <= w - pd.Timedelta(days=7)]
        assert r["lme_close_date"] == in_week.index[-1]
        assert r["lme_cash_usd_t"] == in_week.iloc[-1]
        assert r["lme_cash_logret"] == pytest.approx(np.log(in_week.iloc[-1] / prev.iloc[-1]))
    # spot checks against the P3 event table: the 7-Mar high sits in the week ending 11-Mar
    assert run.week_end_of("2022-03-07") == pd.Timestamp("2022-03-11")
    assert run.week_end_of("2022-04-22") == pd.Timestamp("2022-04-22")
    assert run.week_end_of("2022-02-19") == pd.Timestamp("2022-02-25")


# -------------------------------------------------------------------------------------------------- look-ahead
def test_zscore_uses_only_past_weeks():
    rng = np.random.default_rng(7)
    x = pd.Series(rng.normal(size=20))
    z = run.past_only_zscore(x, 4)
    assert z.iloc[:4].isna().all() and z.iloc[4:].notna().all()
    for t in range(4, 20):
        past = x.iloc[:t]
        assert z.iloc[t] == pytest.approx((x.iloc[t] - past.mean()) / past.std(ddof=1))
    for t in range(4, 19):
        changed = x.copy()
        changed.iloc[t + 1:] = rng.normal(loc=50, scale=10, size=len(x) - t - 1)
        pd.testing.assert_series_equal(run.past_only_zscore(changed, 4).iloc[: t + 1], z.iloc[: t + 1])


def test_published_zscores_have_no_look_ahead(built, settings):
    weekly = built["weekly"]
    m = settings.z_min_past_weeks
    for col, zcol in (("mean", "z_score"), ("adj_mean", "adj_z_score")):
        assert weekly[zcol].iloc[:m].isna().all()
        for t in range(m, len(weekly)):
            past = weekly[col].iloc[:t]
            assert weekly[zcol].iloc[t] == pytest.approx((weekly[col].iloc[t] - past.mean()) / past.std(ddof=1))
    assert weekly.index[m] == pd.Timestamp("2022-03-25")  # the first z-score: nothing for the March spike weeks


def test_episode_verdicts_use_only_weeks_up_to_the_anchor(built, settings):
    eps = built["episodes"]
    for r in eps.itertuples():
        weeks = [pd.Timestamp(w) for w in r.lead_weeks.split(";")]
        assert len(weeks) == run.LEAD_WINDOW_WEEKS and all(w <= pd.Timestamp(r.anchor_date) for w in weeks)
        alt = [pd.Timestamp(w) for w in r.lead_weeks_alt_window.split(";")]
        assert all(w < run.week_end_of(r.anchor_date) for w in alt)
    # Rewriting every week after an anchor must not change that anchor's verdict.
    weekly = built["weekly"].copy()
    anchor = pd.Timestamp("2022-04-22")
    after = weekly.index > anchor
    weekly.loc[after, ["mean", "adj_mean"]] = 5.0
    weekly.loc[after, "lme_cash_logret"] = 0.5
    weekly["z_score"] = run.past_only_zscore(weekly["mean"], settings.z_min_past_weeks)
    weekly["adj_z_score"] = run.past_only_zscore(weekly["adj_mean"], settings.z_min_past_weeks)
    changed, _ = run.episode_tables(weekly, settings)
    base = eps[eps["anchor"] == "CRASH_FORTNIGHT"].set_index("variant")
    new = changed[changed["anchor"] == "CRASH_FORTNIGHT"].set_index("variant")
    for c in ("lead_weeks", "lead_z_values", "signal_hit_weeks", "verdict", "lead_mean_score"):
        assert (base[c] == new[c]).all(), c


# ---------------------------------------------------------------------------------------------------- lead / lag
def test_lag_sign_convention_k_positive_means_sentiment_leads():
    rng = np.random.default_rng(3)
    s = rng.normal(size=30)
    r = np.empty(30)
    r[0] = 0.0
    r[1:] = s[:-1]  # the return in week t+1 copies sentiment in week t
    xs, ys = run.lagged_pairs(s, r, 1)
    assert np.corrcoef(xs, ys)[0, 1] == pytest.approx(1.0)
    xs, ys = run.lagged_pairs(r, s, -1)  # the same relation read from the other side
    assert np.corrcoef(xs, ys)[0, 1] == pytest.approx(1.0)
    xs, ys = run.lagged_pairs(s, r, 0)
    assert len(xs) == 30 and abs(np.corrcoef(xs, ys)[0, 1]) < 0.5


def test_leadlag_table_shape_and_consistency(built):
    ll = built["leadlag"]
    assert len(ll) == len(run.VARIANTS) * (2 * run.MAX_LAG_WEEKS + 1)
    assert set(ll.loc[ll["is_primary"], "variant"]) == {run.PRIMARY_VARIANT}
    assert (ll["n_pairs"] == 28 - ll["lag_weeks"].abs()).all()
    assert ((ll["fisher_ci_lo"] <= ll["pearson_r"]) & (ll["pearson_r"] <= ll["fisher_ci_hi"])).all()
    assert (ll["boot_ci_lo"] <= ll["boot_ci_hi"]).all() and (ll["boot_valid_draws"] > 9_000).all()
    assert (ll["significant_bonferroni_7lags"] <= ll["significant_naive_5pct"]).all()
    weekly = built["weekly"]
    prim0 = ll[(ll["variant"] == run.PRIMARY_VARIANT) & (ll["lag_weeks"] == 0)].iloc[0]
    assert prim0["pearson_r"] == pytest.approx(weekly["mean"].corr(weekly["lme_cash_logret"]))
    assert run.critical_r(28, 0.05) == pytest.approx(0.374, abs=1e-3)


# ----------------------------------------------------------------------------------------------------- lexicon
def test_lexicon_only_adds_flips_or_removes(settings):
    raw, adj = run.make_analyzers(settings)
    fresh = run.SentimentIntensityAnalyzer().lexicon
    assert raw.lexicon == fresh  # the raw analyser is never mutated
    sets, removed = run.domain_overrides(settings.lexicon, settings.valence_abs)
    flipped = {w for w in sets if w in fresh}
    assert flipped == {"deficit", "shortage", "shortages"}
    for w in flipped:
        assert np.sign(fresh[w]) != np.sign(sets[w])
    assert set(removed) == {"demand"} and "demand" in fresh and "demand" not in adj.lexicon
    assert all(abs(v) == settings.valence_abs for v in sets.values())
    assert {k: v for k, v in adj.lexicon.items() if k not in sets and k not in removed} == {
        k: v for k, v in fresh.items() if k not in sets and k not in removed}
    table = run.lexicon_table(raw, settings)
    assert set(table["action"]) == {"added", "flipped", "removed"}
    with pytest.raises(ValueError):
        run.domain_overrides({"up": ["surge"], "down": ["surge"]}, 1.5)
    with pytest.raises(ValueError):
        run.domain_overrides({"up": ["pushes up"]}, 1.5)


def test_lexicon_examples_score_as_documented(settings):
    raw, adj = run.make_analyzers(settings)
    t = "Aluminium prices surge"
    assert raw.polarity_scores(t)["compound"] == 0.0 and adj.polarity_scores(t)["compound"] > 0.05
    t = "Aluminium prices slump"
    assert raw.polarity_scores(t)["compound"] == 0.0 and adj.polarity_scores(t)["compound"] < -0.05
    t = "Global aluminium deficit widens"
    assert raw.polarity_scores(t)["compound"] < 0 < adj.polarity_scores(t)["compound"]
    assert run.tokens("Prices SURGE, again!") == ["prices", "surge", "again"]


def test_register_keys_are_flagged(settings):
    keys = [k for k in config.load_params() if k.startswith("sent_")]
    assert len(keys) == 7
    for k in keys:
        p = config.get(k)
        assert p.file == "risk.yaml" and p.flag == "ASSUMPTION" and len(p.note) > 40, k
        assert p.verify.startswith("N/A"), k
    words = [w for ws in settings.lexicon.values() for w in ws]
    assert len(words) == len(set(words)) == 82


# ----------------------------------------------------------------------------------------------------- honesty
def test_headlines_are_scored_verbatim(built):
    h = pd.read_csv(PROCESSED_DIR / "headlines_weekly.csv", dtype=str, keep_default_na=False)
    scored = built["scored"]
    key = ["week_end", "published_utc", "source", "title", "link", "query"]
    a = h[key].sort_values(key).reset_index(drop=True)
    b = scored[key].sort_values(key).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    assert scored["vader_compound"].between(-1, 1).all() and scored["adj_compound"].between(-1, 1).all()
    assert (scored["lexicon_hits"].ne("") | (scored["vader_compound"] == scored["adj_compound"])).all()


def test_doc_quotes_only_real_headlines_and_carries_labels():
    _need_own()
    doc = run.DOC_PATH.read_text(encoding="utf-8")
    assert SIM_LABEL in doc and "## 7. What this does and doesn't tell you" in doc
    assert "not a forecasting model" in doc
    h = pd.read_csv(PROCESSED_DIR / "headlines_weekly.csv", dtype=str, keep_default_na=False)
    block = doc.split("<!-- HEADLINES:START")[1].split("<!-- HEADLINES:END -->")[0]
    rows = [line for line in block.splitlines() if re.match(r"^\| 2022-\d\d-\d\d \|", line)]
    assert len(rows) >= 14
    for line in rows:
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        source, title = cells[-2].replace("\\|", "|"), cells[-1].replace("\\|", "|")
        if title.startswith("(no headline"):
            continue
        prefix = title.removesuffix(" …")
        match = h[(h["source"] == source) & h["title"].str.startswith(prefix) & (h["week_end"] == cells[0])]
        assert len(match) >= 1, (cells[0], source, title)
    # titles quoted in the prose (§0, §4.4) exist verbatim too
    for quoted in ("Russia - Ukraine war pushes up the prices of nickel and aluminum",
                   "Steel materials prices surge as impact of Ukraine war bites"):
        assert quoted in doc and quoted in set(h["title"])
    for prefix in ("Square Cuts On Aluminum Extrusion", "Tata Steel output falls 3% to 7.57 MT in Q4",
                   "Indices snap 5-day winning streak, Sensex tumbles 709 points"):
        assert prefix in doc and h["title"].str.startswith(prefix).any(), prefix
    s = pd.read_csv(TABLES_DIR / "sentiment_summary.csv").set_index("metric")["value"]
    assert (f"only {int(s['n_weeks_95ci_excludes_zero_vader'])} of the\n28 raw weekly means "
            f"({int(s['n_weeks_95ci_excludes_zero_adj'])} adjusted)") in doc
    # every generated block was filled
    for name in ("WEEKLY", "LEADLAG", "EPISODES", "HEADLINES"):
        body = doc.split(f"<!-- {name}:START")[1].split(f"<!-- {name}:END -->")[0]
        assert body.count("\n|") >= 3, name


def test_summary_numbers_quoted_in_doc(built):
    _need_own()
    doc = run.DOC_PATH.read_text(encoding="utf-8")
    s = built["summary"].set_index("metric")["value"]
    ll = built["leadlag"].set_index(["variant", "lag_weeks"])
    assert f"**{s['share_vader_exactly_zero']:.0%}".replace("%", " %") in doc
    assert f"r = **{ll.loc[('vader_all', 0), 'pearson_r']:+.2f}**".replace("-", "−") in doc
    assert f"(naive p = {ll.loc[('vader_all', 0), 'pearson_p_naive']:.2f})" in doc
    assert int(s["n_lead_tests_naive_5pct"]) == 0 and int(s["n_lead_tests_boot_ci_excludes_zero"]) == 0
    assert int(s["n_tests_total_boot_ci_excludes_zero"]) == 1
    only = built["leadlag"][built["leadlag"]["boot_ci_excludes_zero"]].iloc[0]
    assert (only["variant"], int(only["lag_weeks"])) == ("adjusted_all", -1)
    assert f"{int(s['n_headlines_lexicon_hit'])} of 649 headlines" in doc
    assert f"{int(s['n_headlines_class_changed_by_lexicon'])} change class" in doc
    assert f"{int(s['n_lexicon_hits_subject_caveat'])} of the {int(s['n_headlines_lexicon_hit'])} hits" in doc
    eps = built["episodes"].set_index(["anchor", "variant"])
    assert eps.loc[("MARCH_SPIKE_UP", "vader_all"), "verdict"] == "NOT TESTABLE"
    assert eps.loc[("MARCH_TOP", "vader_all"), "verdict"] == "NOT TESTABLE"
    assert eps.loc[("CRASH_FORTNIGHT", "vader_all"), "verdict"] == "SIGNAL FIRED"
    assert eps.loc[("JULY_TROUGH", "vader_all"), "verdict"] == "DID NOT LEAD"
    assert (built["episodes"]["verdict"] == built["episodes"]["verdict_alt_window"]).all()
    assert f"{eps.loc[('CRASH_FORTNIGHT', 'vader_all'), 'chance_of_hit_in_window_approx_frac']:.0%}".replace("%", " %") in doc
