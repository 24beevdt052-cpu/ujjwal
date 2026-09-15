"""Tests for desk.sentiment.fetch_news (CONTRACTS §4.4). Offline-safe: data checks skip when the cache is absent."""

import datetime as dt

import pandas as pd
import pytest

import desk.sentiment.fetch_news as fn

# Synthetic fixture: clearly fake items used only to exercise the parser, never written to data/.
_FIXTURE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>fixture</title>
<item><title>FIXTURE aluminium item - Fixture Wire</title><link>https://example.invalid/a</link>
<pubDate>Mon, 07 Mar 2022 08:00:00 GMT</pubDate><source url="https://example.invalid">Fixture Wire</source></item>
<item><title>FIXTURE item outside week - Fixture Wire</title><link>https://example.invalid/b</link>
<pubDate>Sat, 12 Mar 2022 00:00:00 GMT</pubDate><source url="https://example.invalid">Fixture Wire</source></item>
<item><title>FIXTURE coconut item - Fixture Wire</title><link>https://example.invalid/c</link>
<pubDate>Tue, 08 Mar 2022 08:00:00 GMT</pubDate><source url="https://example.invalid">Fixture Wire</source></item>
</channel></rss>"""


def test_week_calendar_is_w_fri_feb25_to_sep2():
    weeks = fn.week_ends()
    assert weeks[0] == dt.date(2022, 2, 25) and weeks[-1] == dt.date(2022, 9, 2)
    assert len(weeks) == 28
    assert all(w.weekday() == 4 for w in weeks)


def test_query_url_over_covers_saturday_to_saturday():
    url = fn.query_url("en-IN", "aluminium LME", dt.date(2022, 3, 11))
    assert "q=aluminium+LME+after:2022-03-05+before:2022-03-12" in url
    assert url.endswith("hl=en-IN&gl=IN&ceid=IN:en")
    path = fn.cache_path("en-US", "aluminum prices", dt.date(2022, 3, 11))
    assert path.name == "en-US_aluminum-prices_2022-03-11.xml"


def test_split_source_strips_only_the_publisher_suffix():
    assert fn.split_source("Steel - what next? - Some Paper", "Some Paper") == ("Steel - what next?", "Some Paper")
    assert fn.split_source("No suffix here", "Some Paper") == ("No suffix here", "Some Paper")
    assert fn.split_source("Kept as is - X", "") == ("Kept as is - X", "")


def test_relevance_filter_terms():
    assert fn.relevance_match("LME aluminium stocks fall") == "aluminium|LME"
    assert fn.relevance_match("Base-metals rally") == "metal"
    assert fn.relevance_match("New helmet rules") == ""  # 'lme' inside a word must not count
    assert fn.relevance_match("Nickel price jumps") == ""


def test_exclusion_rules():
    pub = dt.datetime(2022, 3, 7, 8, tzinfo=dt.timezone.utc)
    rule = fn.exclusion_rule
    assert rule("Gold Rate Today: Yellow Metal jumps", "Paper", "metal", pub) == "precious_metals_not_base"
    assert rule("LME to end gold and silver contracts", "Paper", "LME", pub) == ""  # core term protects
    assert rule("Heavy metals found in river fish", "Paper", "metal", pub) == "heavy_metals_pollution"
    assert rule("Any aluminium study", "Nature", "aluminium", pub) == "scholarly_journal"
    assert rule("Bike price in Steel City - September 2026 on road price", "X", "steel", pub) == (
        "retitled_future_month_year"
    )
    assert rule("Smelter to run until March 2025", "X", "smelter", pub) == ""  # forward-looking phrasing is fine
    # Google serves the page's CURRENT title with its original pubDate: an "Update:" title may carry later news
    assert rule("Update: LME nickel trading to resume March 16", "Recycling Today", "LME", pub) == (
        "retitled_update_prefix"
    )
    assert rule("Updated: SDI ventures into aluminum sheet production", "X", "aluminum", pub) == (
        "retitled_update_prefix"
    )
    assert rule("Upbeat update on aluminium demand", "X", "aluminium", pub) == ""


def test_cites_later_date_flags_day_month_after_pubdate():
    pub = dt.datetime(2022, 3, 8, 8, tzinfo=dt.timezone.utc)
    assert fn.cites_later_date("LME nickel trading to resume March 16", pub)
    assert fn.cites_later_date("Prices from 1 July", dt.datetime(2022, 6, 29, tzinfo=dt.timezone.utc))
    assert not fn.cites_later_date("LME halted nickel on March 8", pub)
    assert not fn.cites_later_date("Aluminium outlook for March 2022", pub)  # month-year, no day
    assert not fn.cites_later_date("No dates here", pub)


def test_no_update_prefixed_titles_are_kept():
    df = _load()
    assert not df["title"].str.match(r"(?i)^\s*updated?\b").any()


def test_normalise_title_collapses_punctuation_and_case():
    assert fn.normalise_title("Aluminium’s  Rally, Again!") == fn.normalise_title("aluminium s rally again")


def test_parse_feed_applies_strict_window_and_relevance():
    rows = fn.parse_feed(_FIXTURE_RSS, "en-IN", "aluminium LME", dt.date(2022, 3, 11), 0)
    status = {r["title"]: r["status"] for r in rows}
    assert status == {
        "FIXTURE aluminium item": "candidate",
        "FIXTURE item outside week": "out_of_window",
        "FIXTURE coconut item": "irrelevant",
    }
    assert rows[0]["source"] == "Fixture Wire" and rows[0]["published_utc"] == "2022-03-07T08:00:00Z"


def _load() -> pd.DataFrame:
    if not fn.OUT_PATH.exists():
        pytest.skip("headlines_weekly.csv not built (run desk.sentiment.fetch_news.main)")
    return pd.read_csv(fn.OUT_PATH, dtype=str, keep_default_na=False)


def test_schema_matches_contract():
    df = _load()
    assert list(df.columns) == fn.COLUMNS
    assert len(df) > 0
    assert (df["title"].str.len() > 0).all() and (df["source"].str.len() > 0).all()
    assert df["link"].str.startswith("https://").all()
    assert df["query"].str.match(r"^en-(IN|US):").all()


def test_every_headline_is_inside_its_week():
    df = _load()
    week_end = pd.to_datetime(df["week_end"])
    pub = pd.to_datetime(df["published_utc"], utc=True).dt.tz_localize(None)
    assert (week_end.dt.weekday == 4).all()
    assert (pub >= week_end - pd.Timedelta(days=6)).all()
    assert (pub < week_end + pd.Timedelta(days=1)).all()


def test_no_duplicate_titles():
    df = _load()
    assert not df["title"].map(fn.normalise_title).duplicated().any()


def test_at_least_27_weeks_present():
    df = _load()
    assert df["week_end"].nunique() >= 27
    assert set(df["week_end"]) <= {w.isoformat() for w in fn.week_ends()}


def test_offline_rebuild_reproduces_processed_file(monkeypatch):
    df = _load()
    core = [fn.cache_path(e, q, w) for w in fn.week_ends() for e, q in fn.CORE_QUERIES]
    if not all(p.exists() for p in core):
        pytest.skip("raw RSS cache incomplete in data/raw/news/")
    monkeypatch.setenv("DESK_OFFLINE", "1")
    kept, _, _ = fn.build()
    rebuilt = kept[fn.COLUMNS].reset_index(drop=True).astype(str)
    pd.testing.assert_frame_equal(rebuilt, df.reset_index(drop=True))
