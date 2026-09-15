"""Real weekly news headlines for the optional sentiment overlay (CONTRACTS §4.4; feeds P7 `desk.sentiment.run`).

Why Google News RSS search: it is free, needs no API key, reaches back to 2022 through the `after:`/`before:` date
operators, and returns publisher metadata (title, source, pubDate, link) without article bodies — exactly the
"real public headline, stored as returned" evidence the spec asks for. Everything is cached as raw XML under
data/raw/news/ so the processed file can be rebuilt offline (DESK_OFFLINE=1) byte-for-byte.

Empirically (probed 2026-09-16) `after:X before:Y` returns items dated X..Y *inclusive* at day granularity, so each
week is queried over [Saturday, next Saturday] and then filtered STRICTLY on pubDate into the W-FRI week
(Saturday 00:00 UTC .. Friday 23:59:59 UTC). Out-of-window items are dropped, never re-assigned.

Output columns are exactly the contract: week_end, published_utc, source, title, link, query. The `query` value is
"<edition>:<query text>" for the first query (in priority order) that returned the headline. Which relevance term
kept each row, and why every other RSS item was dropped, is recorded in data/interim/news/_audit_headlines.csv (a
derived table, so it lives in data/interim/, not data/raw/).

Look-ahead guard: Google News returns a page's CURRENT (re-crawled) title with its ORIGINAL pubDate. A title that was
edited after publication can therefore leak later information into an earlier week (e.g. an 8-Mar-2022 item titled
"Update: LME nickel trading to resume March 16" — a date reportedly announced only around 14-15 Mar). Titles starting with
"Update"/"Updated" are excluded (`retitled_update_prefix`), and titles citing a calendar date after their pubDate are
flagged in the audit (`cites_later_date`) and listed in the notes for manual review (not auto-excluded, because
genuine forward-looking headlines also cite future dates).
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import pandas as pd

from desk.data._http import FetchError, fetch_cached, offline
from desk.paths import DOCS_DIR, INTERIM_DIR, PROCESSED_DIR, RAW_DIR

NEWS_RAW_DIR = RAW_DIR / "news"
OUT_PATH = PROCESSED_DIR / "headlines_weekly.csv"
AUDIT_PATH = INTERIM_DIR / "news" / "_audit_headlines.csv"
NOTES_PATH = DOCS_DIR / "research" / "news_notes.md"

COLUMNS = ["week_end", "published_utc", "source", "title", "link", "query"]
FIRST_WEEK_END = dt.date(2022, 2, 25)
LAST_WEEK_END = dt.date(2022, 9, 2)
MIN_HEADLINES_PER_WEEK = 10
NETWORK_PAUSE_S = 2.0  # politeness gap between live Google News calls
INVALID_BODY_RETRIES = 3

EDITIONS: dict[str, str] = {
    "en-IN": "hl=en-IN&gl=IN&ceid=IN:en",
    "en-US": "hl=en-US&gl=US&ceid=US:en",
}

# Priority order matters: when the same headline comes back from several queries, the first query here is credited.
# Queries are deliberately direction-neutral (no "surge"/"slump" words) so the sample does not pre-load sentiment.
CORE_QUERIES: tuple[tuple[str, str], ...] = (
    ("en-IN", "aluminium LME"),
    ("en-IN", "aluminium price"),
    ("en-IN", "aluminum prices"),
    ("en-IN", "aluminium scrap"),
    ("en-IN", "aluminum scrap"),
    ("en-IN", "LME metals"),
    ("en-IN", "base metals"),
    ("en-IN", "metal prices"),
    ("en-IN", "steel prices India"),
    ("en-US", "aluminum prices"),
    ("en-US", "aluminum scrap"),
    ("en-US", "LME metals"),
)

# Only run for weeks whose kept count after the core queries is below MIN_HEADLINES_PER_WEEK.
EXTRA_QUERIES: tuple[tuple[str, str], ...] = (
    ("en-IN", "aluminium"),
    ("en-US", "aluminum"),
    ("en-IN", "steel prices"),
    ("en-IN", "Hindalco OR Vedanta OR NALCO"),
    ("en-US", "aluminium smelter"),
    ("en-IN", "non-ferrous metals"),
)

# Title (after stripping the " - Source" suffix) must match at least one of these, case-insensitive.
RELEVANCE_TERMS: tuple[tuple[str, str], ...] = (
    ("aluminium", r"\baluminium"),
    ("aluminum", r"\baluminum"),
    ("alumina", r"\balumina\b"),
    ("bauxite", r"\bbauxite"),
    ("smelter", r"\bsmelt"),
    ("scrap", r"\bscrap"),
    ("LME", r"\bLME\b"),
    ("metal", r"metal"),
    ("steel", r"\bsteel"),
)
_RELEVANCE_RX = tuple((name, re.compile(rx, re.IGNORECASE)) for name, rx in RELEVANCE_TERMS)
# Terms specific to the aluminium/scrap chain; the generic "metal"/"steel" words alone do not protect a title from the
# exclusion rules below.
CORE_TERMS = frozenset({"aluminium", "aluminum", "alumina", "bauxite", "smelter", "scrap", "LME"})

# A few transparent exclusions, tuned after inspecting the first full pull (2026-09-16): the generic word "metal"
# let in daily Indian gold-rate pages ("yellow metal") and journal articles, which would swamp a base-metals
# sentiment score. Rules are applied in order; the rule name is recorded per item in the audit file.
_PRECIOUS_RX = re.compile(r"\b(gold|silver|platinum|palladium|precious|jewell?ery)\b", re.IGNORECASE)
_HEAVY_METAL_RX = re.compile(r"\bheavy[- ]metals?\b", re.IGNORECASE)
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_MONTH_YEAR_RX = re.compile(rf"(?:^|(\w+)\W+)(?:{_MONTHS})\s+(20\d\d)\b", re.IGNORECASE)
_UPDATE_PREFIX_RX = re.compile(r"^\s*(?:update|updated)\b", re.IGNORECASE)
_MONTH_NUM = {m.lower(): i for i, m in enumerate(_MONTHS.split("|"), start=1)}
_DAY_MONTH_RX = re.compile(
    rf"\b(?:(?P<m1>{_MONTHS})\.?\s+(?P<d1>[0-3]?\d)(?:st|nd|rd|th)?|(?P<d2>[0-3]?\d)(?:st|nd|rd|th)?\s+(?P<m2>{_MONTHS}))\b"
    rf"(?!\s*,?\s*20\d\d)",
    re.IGNORECASE,
)
_FORWARD_LOOKING_WORDS = frozenset(
    {"by", "until", "till", "before", "from", "to", "in", "through", "after", "since", "of", "for"}
)
SCHOLARLY_SOURCES = frozenset(
    {
        "Nature",
        "Frontiers",
        "Wiley Online Library",
        "Science | AAAS",
        "Cambridge University Press & Assessment",
        "ChemistryViews",
    }
)

COVERAGE_START = "<!-- COVERAGE:START (generated by desk.sentiment.fetch_news.main; do not hand-edit) -->"
COVERAGE_END = "<!-- COVERAGE:END -->"


def week_ends() -> list[dt.date]:
    """W-FRI week-end dates from FIRST_WEEK_END to LAST_WEEK_END inclusive."""
    return [d.date() for d in pd.date_range(FIRST_WEEK_END, LAST_WEEK_END, freq="W-FRI")]


def week_bounds_utc(week_end: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """[Saturday 00:00 UTC, next Saturday 00:00 UTC) for the week ending Friday `week_end`."""
    start = dt.datetime.combine(week_end - dt.timedelta(days=6), dt.time(0, 0), tzinfo=dt.timezone.utc)
    return start, start + dt.timedelta(days=7)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def query_url(edition: str, query: str, week_end: dt.date) -> str:
    """Google News RSS search URL; the window over-covers by one day because both operators are inclusive."""
    after = week_end - dt.timedelta(days=6)
    before = week_end + dt.timedelta(days=1)
    q = quote_plus(f"{query} after:{after.isoformat()} before:{before.isoformat()}", safe=":")
    return f"https://news.google.com/rss/search?q={q}&{EDITIONS[edition]}"


def cache_path(edition: str, query: str, week_end: dt.date) -> Path:
    return NEWS_RAW_DIR / f"{edition}_{slug(query)}_{week_end.isoformat()}.xml"


def _looks_like_rss(body: bytes) -> bool:
    return b"<rss" in body[:2000]


def fetch_feed(edition: str, query: str, week_end: dt.date) -> bytes | None:
    """Raw RSS bytes from cache or network; None when unavailable (offline without cache, or repeated failure).

    fetch_cached caches any HTTP 200, so a consent/HTML interstitial is detected here, deleted and retried rather
    than silently poisoning the cache.
    """
    path = cache_path(edition, query, week_end)
    url = query_url(edition, query, week_end)
    for attempt in range(INVALID_BODY_RETRIES):
        hits_network = not path.exists() and not offline()
        try:
            body = fetch_cached(url, path)
        except FetchError as e:
            print(f"  [news] unavailable {path.name}: {e}")
            return None
        finally:
            if hits_network:
                time.sleep(NETWORK_PAUSE_S)
        if _looks_like_rss(body):
            return body
        path.unlink(missing_ok=True)
        print(f"  [news] non-RSS body for {path.name} (attempt {attempt + 1}); discarded")
        if offline():
            return None
        time.sleep(NETWORK_PAUSE_S * 5)
    return None


def split_source(raw_title: str, source: str) -> tuple[str, str]:
    """Strip the trailing " - <Source>" Google News appends, moving it into `source`. Text is otherwise untouched."""
    title = raw_title.strip()
    source = (source or "").strip()
    if source and title.endswith(f" - {source}"):
        return title[: -len(f" - {source}")].rstrip(), source
    return title, source  # no <source> element: keep the title exactly as returned rather than guess a split


def relevance_match(title: str) -> str:
    """Pipe-joined names of every relevance term the title matches ('' = irrelevant)."""
    return "|".join(name for name, rx in _RELEVANCE_RX if rx.search(title))


def exclusion_rule(title: str, source: str, rel: str, published: dt.datetime | None) -> str:
    """Name of the first exclusion rule the item trips ('' = none)."""
    core = bool(CORE_TERMS.intersection(rel.split("|"))) if rel else False
    if source in SCHOLARLY_SOURCES:
        return "scholarly_journal"
    if not core and _PRECIOUS_RX.search(title):
        return "precious_metals_not_base"
    if not core and _HEAVY_METAL_RX.search(title):
        return "heavy_metals_pollution"
    if _UPDATE_PREFIX_RX.search(title):
        # the page was re-titled after publication; its current title may carry later information
        return "retitled_update_prefix"
    if published is not None:
        for m in _MONTH_YEAR_RX.finditer(title):
            before = (m.group(1) or "").lower()
            if int(m.group(2)) > published.year and before not in _FORWARD_LOOKING_WORDS:
                # e.g. an evergreen price page whose title Google re-crawled years later ("- September 2026 ...")
                return "retitled_future_month_year"
    return ""


def cites_later_date(title: str, published: dt.datetime | None) -> bool:
    """True if the title names a day+month (no year) that falls after the pubDate in the pubDate's year."""
    if published is None:
        return False
    for m in _DAY_MONTH_RX.finditer(title):
        month = _MONTH_NUM[(m.group("m1") or m.group("m2")).lower()]
        day = int(m.group("d1") or m.group("d2"))
        try:
            cited = dt.date(published.year, month, day)
        except ValueError:
            continue
        if cited > published.date():
            return True
    return False


def normalise_title(title: str) -> str:
    """Key for de-duplication: NFKC, case-folded, punctuation removed, whitespace collapsed."""
    t = unicodedata.normalize("NFKC", title).casefold()
    t = re.sub(r"[\W_]+", " ", t)
    return " ".join(t.split())


def parse_feed(body: bytes, edition: str, query: str, week_end: dt.date, rank: int) -> list[dict]:
    """Every RSS item as an audit row (window / relevance decided here, de-duplication later)."""
    start, end = week_bounds_utc(week_end)
    rows = []
    for pos, e in enumerate(feedparser.parse(body).entries):
        src = e.get("source", {}).get("title", "") if isinstance(e.get("source"), dict) else ""
        title, source = split_source(e.get("title", ""), src)
        pub = None
        if e.get("published_parsed"):
            pub = dt.datetime.fromtimestamp(calendar.timegm(e.published_parsed), tz=dt.timezone.utc)
        in_window = pub is not None and start <= pub < end
        rel = relevance_match(title)
        excl = exclusion_rule(title, source, rel, pub) if rel else ""
        if pub is None:
            status = "no_pubdate"
        elif not in_window:
            status = "out_of_window"
        elif not rel:
            status = "irrelevant"
        elif excl:
            status = "excluded"
        else:
            status = "candidate"
        rows.append(
            {
                "week_end": week_end.isoformat(),
                "published_utc": pub.strftime("%Y-%m-%dT%H:%M:%SZ") if pub else "",
                "source": source,
                "title": title,
                "link": e.get("link", ""),
                "query": f"{edition}:{query}",
                "query_rank": rank,
                "feed_pos": pos,
                "relevance_match": rel,
                "exclusion_rule": excl,
                "cites_later_date": cites_later_date(title, pub),
                "status": status,
            }
        )
    return rows


def collect_week(week_end: dt.date, queries: tuple[tuple[str, str], ...], rank_offset: int) -> tuple[list[dict], int]:
    rows: list[dict] = []
    fetched = 0
    for i, (edition, query) in enumerate(queries):
        body = fetch_feed(edition, query, week_end)
        if body is None:
            continue
        fetched += 1
        rows.extend(parse_feed(body, edition, query, week_end, rank_offset + i))
    return rows, fetched


def deduplicate(audit: pd.DataFrame) -> pd.DataFrame:
    """Mark duplicates across queries/editions/weeks: earliest publication wins, then query priority."""
    audit = audit.sort_values(["published_utc", "query_rank", "feed_pos"], kind="mergesort").reset_index(drop=True)
    audit["title_key"] = audit["title"].map(normalise_title)
    cand = audit["status"] == "candidate"
    dup = cand & audit[cand].duplicated("title_key", keep="first").reindex(audit.index, fill_value=False)
    audit.loc[dup, "status"] = "duplicate"
    audit.loc[cand & ~dup, "status"] = "kept"
    return audit


def coverage(kept: pd.DataFrame, fetched: dict[str, int], extras_used: set[str]) -> pd.DataFrame:
    counts = kept.groupby("week_end").size()
    return pd.DataFrame(
        [
            {
                "week_end": w.isoformat(),
                "headlines": int(counts.get(w.isoformat(), 0)),
                "feeds_fetched": fetched.get(w.isoformat(), 0),
                "extra_queries": "yes" if w.isoformat() in extras_used else "no",
                "below_min": int(counts.get(w.isoformat(), 0)) < MIN_HEADLINES_PER_WEEK,
            }
            for w in week_ends()
        ]
    )


def _md_table(df: pd.DataFrame) -> str:
    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    body = ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def render_generated_section(kept: pd.DataFrame, cov: pd.DataFrame, audit: pd.DataFrame) -> str:
    """Deterministic markdown (no timestamps) so an offline rebuild reproduces the notes byte-for-byte."""
    queries = pd.DataFrame(
        [{"set": "core", "edition": e, "query": q} for e, q in CORE_QUERIES]
        + [{"set": "extra (thin weeks only)", "edition": e, "query": q} for e, q in EXTRA_QUERIES]
    )
    status = audit["status"].value_counts().rename_axis("status").reset_index(name="rss_items")
    excluded = audit.loc[audit["status"] == "excluded", "exclusion_rule"].value_counts()
    excluded = excluded.rename_axis("exclusion_rule").reset_index(name="in_window_items")
    future_year = kept[kept["title"].str.contains(r"\b20(?:2[3-9]|[3-9]\d)\b", regex=True)]
    future_year = future_year[["week_end", "source", "title"]]
    later_date = kept.loc[kept["cites_later_date"].astype(bool), ["week_end", "published_utc", "source", "title"]]
    by_query = kept["query"].value_counts().rename_axis("credited_query").reset_index(name="kept_headlines")
    top_sources = kept["source"].value_counts().head(15).rename_axis("source").reset_index(name="kept_headlines")
    terms = kept["relevance_match"].str.split("|").explode().value_counts()
    terms = terms.rename_axis("relevance_term").reset_index(name="kept_titles_matching")
    cov_md = cov.assign(below_min=cov["below_min"].map({True: "YES", False: ""}))
    thin = cov.loc[cov["below_min"], "week_end"].tolist()
    tod = kept["published_utc"].str[11:19].value_counts()
    placeholder_counts = {t: int(tod.get(t, 0)) for t in ("07:00:00", "08:00:00")}
    placeholders = ", ".join(f"{t}Z: {n}" for t, n in placeholder_counts.items())
    other_times = len(kept) - sum(placeholder_counts.values())
    feed_sizes = audit.groupby(["week_end", "query"]).size()
    lines = [
        COVERAGE_START,
        "",
        f"Totals: **{len(kept)} kept headlines** across **{kept['week_end'].nunique()} of {len(cov)} weeks**; "
        f"median {int(cov['headlines'].median())}/week, min {cov['headlines'].min()}, max {cov['headlines'].max()}. "
        f"Weeks below {MIN_HEADLINES_PER_WEEK}: {', '.join(thin) if thin else 'none'}.",
        "",
        f"RSS items per non-empty feed: median {int(feed_sizes.median())}, max {int(feed_sizes.max())}. "
        f"Kept `published_utc` time-of-day — {placeholders}, other: {other_times}.",
        "",
        "### Queries (exact strings sent, before the date operators)",
        "",
        _md_table(queries),
        "",
        "### Coverage per week (week ending Friday)",
        "",
        _md_table(cov_md),
        "",
        "### RSS item outcomes (all feeds, before/after filters)",
        "",
        _md_table(status),
        "",
        "### Exclusion rules tripped (in-window, relevant items only; before de-duplication)",
        "",
        _md_table(excluded),
        "",
        "### Kept titles that mention a year after 2022 (manual review: forecasts are fine, re-titled pages are not)",
        "",
        _md_table(future_year) if len(future_year) else "None.",
        "",
        "### Kept titles citing a day-month after their pubDate (manual look-ahead review: could be a re-titled page)",
        "",
        _md_table(later_date) if len(later_date) else "None.",
        "",
        "### Kept headlines by credited query",
        "",
        _md_table(by_query),
        "",
        "### Relevance terms matched by kept titles (a title can match several)",
        "",
        _md_table(terms),
        "",
        "### Top 15 publishers in the kept set",
        "",
        _md_table(top_sources),
        "",
        COVERAGE_END,
    ]
    return "\n".join(lines)


def update_notes(section: str) -> None:
    """Replace only the generated block in the hand-written notes (prose stays under version control)."""
    NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = NOTES_PATH.read_text() if NOTES_PATH.exists() else "# News headline notes\n\n"
    if COVERAGE_START in text and COVERAGE_END in text:
        pre = text.split(COVERAGE_START)[0]
        post = text.split(COVERAGE_END, 1)[1]
        text = pre + section + post
    else:
        text = text.rstrip("\n") + "\n\n## Generated coverage\n\n" + section + "\n"
    NOTES_PATH.write_text(text)


def build() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch/parse every week; returns (headlines, audit, coverage)."""
    NEWS_RAW_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    fetched: dict[str, int] = {}
    for w in week_ends():
        week_rows, n = collect_week(w, CORE_QUERIES, 0)
        rows.extend(week_rows)
        fetched[w.isoformat()] = n
        print(f"  [news] core {w}: {n}/{len(CORE_QUERIES)} feeds, {len(week_rows)} items")

    extras_used: set[str] = set()
    audit = deduplicate(pd.DataFrame(rows))
    counts = audit[audit["status"] == "kept"].groupby("week_end").size()
    for w in week_ends():
        if int(counts.get(w.isoformat(), 0)) >= MIN_HEADLINES_PER_WEEK:
            continue
        extras_used.add(w.isoformat())
        week_rows, n = collect_week(w, EXTRA_QUERIES, len(CORE_QUERIES))
        rows.extend(week_rows)
        fetched[w.isoformat()] += n
        print(f"  [news] extra {w}: {n}/{len(EXTRA_QUERIES)} feeds, {len(week_rows)} items")
    if extras_used:
        audit = deduplicate(pd.DataFrame(rows))

    kept = audit[audit["status"] == "kept"].sort_values(["week_end", "published_utc", "query_rank", "feed_pos"])
    kept = kept.reset_index(drop=True)
    cov = coverage(kept, fetched, extras_used)
    return kept, audit, cov


def main() -> None:
    kept, audit, cov = build()
    if kept.empty:
        raise RuntimeError("No headlines collected (network down and no cache in data/raw/news/?)")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    kept[COLUMNS].to_csv(OUT_PATH, index=False)
    audit_cols = [*COLUMNS, "relevance_match", "exclusion_rule", "cites_later_date", "status", "query_rank", "feed_pos"]
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    audit.sort_values(["week_end", "query_rank", "feed_pos"])[audit_cols].to_csv(AUDIT_PATH, index=False)
    update_notes(render_generated_section(kept, cov, audit))
    thin = cov.loc[cov["below_min"], ["week_end", "headlines"]]
    print(f"  [news] wrote {OUT_PATH} ({len(kept)} headlines, {kept['week_end'].nunique()}/{len(cov)} weeks)")
    if not thin.empty:
        print(f"  [news] weeks below {MIN_HEADLINES_PER_WEEK}: {thin.to_dict('records')}")


if __name__ == "__main__":
    main()
