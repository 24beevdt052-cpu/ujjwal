"""Weekly container freight for the two desk lanes (CONTRACTS §4.3) — shape from a real index, level from real quotes.

Output: data/processed/freight_weekly.csv
    week_end, freight_jea_nsa_usd_t, freight_usec_mun_usd_t, index_name, index_value, freight_src, note

How the series is built, and why:
1. SHAPE — Drewry World Container Index (WCI) composite, USD per 40ft. Drewry's own page shows only the latest
   week, so every weekly value is read from Internet Archive (Wayback Machine) snapshots of that page (cached
   under data/raw/freight/wayback/). A week whose snapshot is missing is back-filled from the following week's
   published change ("decreased 2.1% to $9,279.46" / "or $71") -> WCI_DERIVED, and only then linearly
   interpolated -> WCI_INTERPOLATED. All real points go to data/interim/freight/points_wci.csv with archive URLs.
2. LEVEL, USEC_MUN (40ft) — the WCI composite is dominated by China headhaul lanes, which fell ~77% in 2022,
   while India-inbound backhaul lanes fell far less. So we do NOT scale the lane 1:1 with the composite.
   Instead we anchor to monthly USD/box averages for "USEC (New York) -> West India (Nhava Sheva/Mundra)"
   published by Container News (cached articles; regex-extracted so every number traces to its text) and
   let the WCI supply only the week-to-week wiggle between anchors:
        usec_box_t = WCI_t * k(t),   k_i = anchor_i / WCI(anchor_i),   k log-linear in time, flat outside.
   Anchors for Jul/Jun 2022 are derived from the articles' own "steady" / "dropped 10-15%" statements; Mar/Apr
   2022 (before Container News reported the USEC leg) are carried by the sibling India-inbound backhaul lane
   Felixstowe/Rotterdam -> West India times the USEC/Europe ratio observed in the same months (Jun-Sep 2022).
3. LEVEL, JEA_NSA (20ft) — no citable 2022 Jebel Ali -> Nhava Sheva quote was found (see
   docs/research/freight_notes.md), so the level at the reference week is an ASSUMPTION from logistics.yaml and
   the lane is assumed to move proportionally with the India-inbound USEC series.
4. USD per MT of scrap = USD per box / payload MT per box (logistics.yaml).

freight_src = "<shape>|USEC:<level>|JEA:ASSUMPTION" with shape ∈ {WCI_REPORTED, WCI_DERIVED, WCI_INTERPOLATED} and
level ∈ {ANCHORED (between USEC-leg anchors), SIBLING (anchored to the Europe->West India bridge), EXTRAP_PRE,
EXTRAP_POST (lane/index ratio held flat beyond the anchors)}.

LOOK-AHEAD (read before using freight as a decision signal): the LEVELS are hindsight-calibrated. Every anchor is
tagged with `available_from` = the latest publication date of any article it depends on (written to
data/interim/freight/points_india_inbound_anchors.csv), and each weekly `note` states when that week's level inputs
became public. The Mar–Apr 2022 SIBLING anchors depend on the USEC/Europe ratio from articles published up to
30-Sep-2022, the Jun/Jul-2022 USEC anchors on the 30-Aug-2022 article, so a Mar-2022 week's level carries ~7 months of
look-ahead. WCI_DERIVED / WCI_INTERPOLATED shape weeks also use the following week's publication. No point-in-time
level can be built for Mar–Apr 2022 from the cached sources (no India-inbound lane quote published before
29-Apr-2022 was found), so none is offered: later phases must treat freight levels as a reconstruction and test
decisions for freight sensitivity rather than read them as information available on the trade date.

What this does and doesn't tell you: it gives a defensible, source-traced order of magnitude and direction for
ocean freight on each lane in each week (e.g. that India-inbound freight eased through Mar-Aug 2022). It is not
a quote: weekly moves between monthly anchors are borrowed from a global index, the JEA_NSA level is a
judgement, the levels use information published after the week, and neither series includes THC/CFS/haulage
(those are port_cf_charges_* in logistics.yaml).
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from desk import config
from desk.data._http import FetchError, fetch_cached, offline, retrieval_dates
from desk.paths import INTERIM_DIR, PROCESSED_DIR, RAW_DIR

RAW = RAW_DIR / "freight"
WAYBACK_DIR = RAW / "wayback"
ARTICLE_DIR = RAW / "articles"
OUT_PATH = PROCESSED_DIR / "freight_weekly.csv"
POINTS_WCI = INTERIM_DIR / "freight" / "points_wci.csv"  # derived tables: data/interim, never data/raw (CONTRACTS §2)
POINTS_ANCHORS = INTERIM_DIR / "freight" / "points_india_inbound_anchors.csv"

FIRST_WEEK = pd.Timestamp("2020-12-25")
LAST_WEEK = pd.Timestamp("2022-12-30")
INDEX_NAME = "DREWRY_WCI_COMPOSITE_USD_FEU"
MAX_INTERP_GAP_WEEKS = 4  # a longer hole in the index would make the "shape" fiction, so it raises
WAYBACK_SLEEP_S = 11.0  # archive.org rate-limits hard; only slept when a snapshot is actually downloaded

DREWRY_WCI_URL = (
    "https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry"
)
CDX_URL = (
    "https://web.archive.org/cdx/search/cdx?url=drewry.co.uk/supply-chain-advisors/supply-chain-expertise/"
    "world-container-index-assessed-by-drewry&from=20201201&to=20230115&output=json&filter=statuscode:200"
    "&collapse=timestamp:8"
)
CDX_CACHE = WAYBACK_DIR / "cdx_drewry_wci_2020-12_2023-01.json"
# Same WCI page archived under other URLs (newsletter/query-string variants, the "weekly-update" path). Used only to
# fill Thursday windows the canonical URL's snapshots miss.
CDX_VARIANTS_URL = (
    "https://web.archive.org/cdx/search/cdx?url=drewry.co.uk&matchType=domain&from=20201201&to=20230115"
    "&filter=original:.*(world-container-index-assessed-by-drewry%5C?|weekly-update/world-container-index).*"
    "&filter=statuscode:200&output=json&fl=original,timestamp,digest"
)
CDX_VARIANTS_CACHE = WAYBACK_DIR / "cdx_drewry_wci_variants_2020-12_2023-01.json"
MANIFEST = WAYBACK_DIR / "manifest.json"  # snapshot timestamp -> archived original URL


def retrieved(path: Path) -> str:
    """Download date of a cached file from data/raw/_download_manifest.json ('' if not recorded)."""
    dates = retrieval_dates([path])
    return dates[0] if dates else ""


# ----------------------------------------------------------------------------------------------------------------
# text helpers
# ----------------------------------------------------------------------------------------------------------------
def html_to_text(raw: bytes) -> str:
    """Visible text of an HTML page on one line (scripts/styles dropped) — what a reader of the page sees."""
    t = raw.decode("utf-8", "replace")
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S | re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).replace("’", "'")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


# ----------------------------------------------------------------------------------------------------------------
# 1. Drewry WCI composite from Wayback snapshots
# ----------------------------------------------------------------------------------------------------------------
def _thursday(ts: str) -> dt.date:
    d = dt.datetime.strptime(ts[:8], "%Y%m%d").date()
    return d - dt.timedelta(days=(d.weekday() - 3) % 7)


def _download_snapshot(ts: str, original: str, manifest: dict) -> None:
    path = WAYBACK_DIR / f"drewry_wci_{ts}.html"
    manifest[ts] = original
    if path.exists():
        return
    try:
        fetch_cached(f"https://web.archive.org/web/{ts}id_/{original}", path, backoff_s=15, retries=4)
    except FetchError as e:  # a missing week is back-filled/interpolated and flagged, not fatal
        print(f"  wayback snapshot {ts} failed: {e}")
    time.sleep(WAYBACK_SLEEP_S)


def download_wci_snapshots() -> None:
    """Cache one Wayback snapshot per Thursday-to-Wednesday window (WCI is published on Thursdays).

    Pass 1 uses the canonical page URL (latest snapshot in each window = most likely to show that Thursday).
    Pass 2 tries archived URL variants only for windows whose parsed assessment is still missing.
    """
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    rows = json.loads(fetch_cached(CDX_URL, CDX_CACHE, backoff_s=10))[1:]
    windows: dict[dt.date, list] = {}
    for r in rows:
        windows.setdefault(_thursday(r[1]), []).append(r)
    seen_digests: set[str] = set()
    for _, snaps in sorted(windows.items()):
        last = sorted(snaps, key=lambda x: x[1])[-1]
        if last[5] not in seen_digests:
            seen_digests.add(last[5])
            _download_snapshot(last[1], last[2], manifest)
    have = {p.assessed for p in _parsed_snapshots()}
    variants = json.loads(fetch_cached(CDX_VARIANTS_URL, CDX_VARIANTS_CACHE, backoff_s=10))[1:]
    tried: set[dt.date] = set()
    for original, ts, _digest in sorted(variants, key=lambda x: x[1]):
        thu = _thursday(ts)
        # a snapshot taken Thu..Wed shows that Thursday (or, early Thursday, the previous one)
        if thu in have or thu in tried or not (FIRST_WEEK.date() - dt.timedelta(8) <= thu <= LAST_WEEK.date()):
            continue
        tried.add(thu)
        _download_snapshot(ts, original, manifest)
    MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True))


_WCI_DATE = re.compile(r"assessment for (?:Thursday,? )?(\d{1,2}) (\w+),? (\d{4})")
_WCI_COMPOSITE = re.compile(
    r"(?:composite World Container [Ii]ndex|World Container Index composite index) (.{0,110}?)\$([\d,]+\.\d{2}) per 40ft",
    flags=re.S,
)
_WCI_PCT = re.compile(r"(increased|decreased|inched up|inched down|slid|slipped|surged|rose|fell|dropped|declined|"
                      r"jumped|grew|gained|plunged|plummeted|sank|eased|up|down)\D{0,25}?([\d.]+)%", flags=re.I)
_WCI_USD = re.compile(r"or \$([\d,]+)")
_NEGATIVE = re.compile(r"\b(decreas\w*|down|slid|slipped|fell|dropped|declin\w*|plung\w*|plummet\w*|sank|eased|"
                       r"weaken\w*|lower\w*)\b", flags=re.I)


@dataclass(frozen=True)
class WciPoint:
    assessed: dt.date
    value: float
    wow_pct: float | None
    wow_usd: float | None
    snapshot: str


def parse_wci_snapshot(raw: bytes, snapshot_ts: str) -> WciPoint | None:
    """Assessment date + composite value (+ published week-on-week change) from one archived WCI page."""
    text = html_to_text(raw)
    d = _WCI_DATE.search(text)
    c = _WCI_COMPOSITE.search(text)
    if not (d and c):
        return None
    assessed = dt.datetime.strptime(f"{d.group(1)} {d.group(2)} {d.group(3)}", "%d %B %Y").date()
    clause = c.group(1)
    sign = -1.0 if _NEGATIVE.search(clause) else 1.0
    pct = _WCI_PCT.search(clause)
    usd = _WCI_USD.search(clause)
    steady = re.search(r"steady|stable|unchanged", clause, flags=re.I)
    return WciPoint(
        assessed=assessed,
        value=_num(c.group(2)),
        wow_pct=sign * float(pct.group(2)) / 100 if pct else (0.0 if steady else None),
        wow_usd=sign * _num(usd.group(1)) if usd else None,  # "steady" is rounded: back-fill via pct 0.0 (approx.)
        snapshot=snapshot_ts,
    )


def _parsed_snapshots() -> list[WciPoint]:
    pts = []
    for f in sorted(WAYBACK_DIR.glob("drewry_wci_*.html")):
        p = parse_wci_snapshot(f.read_bytes(), f.stem.split("_")[-1])
        if p:
            pts.append(p)
    return pts


# Weekly WCI releases republished verbatim by AJOT (American Journal of Transportation). Used only for Thursdays the
# Wayback snapshots miss; each is checked to carry the expected assessment date. (url, assessment date, retrieved)
REPUBLISHED_WCI = [
    ("https://www.ajot.com/news/world-container-index-may-5th", "2022-05-05"),
    ("https://www.ajot.com/news/drewry-world-container-index-18-aug", "2022-08-18"),
]


def _republished_points() -> list[dict]:
    rows = []
    for url, assessed in REPUBLISHED_WCI:
        path = ARTICLE_DIR / f"ajot_{url.rstrip('/').split('/')[-1]}.html"
        try:
            raw = fetch_cached(url, path, retries=4, backoff_s=3, min_bytes=2000)
        except FetchError as e:
            print(f"  republished WCI {assessed} unavailable: {e}")
            continue
        p = parse_wci_snapshot(raw, "republished")
        if p is None or p.assessed.isoformat() != assessed:
            raise ValueError(f"{url} did not parse to a WCI assessment dated {assessed}: {p}")
        rows.append({**p.__dict__, "url": url, "archive_url": "", "archived": "", "retrieved": retrieved(path), "rank": 1})
    return rows


def wci_points() -> pd.DataFrame:
    """All reported WCI composite points (Wayback snapshots first, verbatim republications second), one per Thursday."""
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    rows = [
        {**p.__dict__, "url": DREWRY_WCI_URL,
         "archive_url": f"https://web.archive.org/web/{p.snapshot}/{manifest.get(p.snapshot, DREWRY_WCI_URL)}",
         "archived": pd.Timestamp(p.snapshot[:8]).date().isoformat(),
         "retrieved": retrieved(WAYBACK_DIR / f"drewry_wci_{p.snapshot}.html"), "rank": 0}
        for p in _parsed_snapshots()
    ]
    rows += _republished_points()
    if not rows:
        raise FetchError(f"No parsable Drewry WCI snapshots in {WAYBACK_DIR}")
    df = pd.DataFrame(rows).sort_values(["assessed", "rank", "snapshot"])
    df = df.drop_duplicates("assessed", keep="first").drop(columns="rank").reset_index(drop=True)
    df["assessed"] = pd.to_datetime(df["assessed"])
    return df


def weekly_wci(points: pd.DataFrame) -> pd.DataFrame:
    """W-FRI grid of WCI values: REPORTED, else DERIVED from next week's published change, else INTERPOLATED.

    A Thursday assessment belongs to the week ending the next day (Friday).
    """
    rep = points.set_index(points["assessed"] + pd.Timedelta(days=1))
    # work on a grid spanning all reported weeks so the output edges can be interpolated between real points
    grid = pd.date_range(min(rep.index.min(), FIRST_WEEK), max(rep.index.max(), LAST_WEEK), freq="W-FRI")
    out = pd.DataFrame(index=grid)
    out["index_value"] = rep["value"].reindex(grid)
    out["shape_src"] = np.where(out["index_value"].notna(), "WCI_REPORTED", "")
    out["shape_note"] = ""
    for wk in grid[out["index_value"].isna().to_numpy()]:
        nxt = wk + pd.Timedelta(days=7)
        if nxt not in rep.index:
            continue
        r = rep.loc[nxt]
        if pd.notna(r["wow_usd"]):
            out.loc[wk, "index_value"] = r["value"] - r["wow_usd"]
            how = f"{r['wow_usd']:+,.0f} USD"
        elif pd.notna(r["wow_pct"]):
            out.loc[wk, "index_value"] = r["value"] / (1 + r["wow_pct"])
            how = f"{r['wow_pct']:+.1%} (rounded pct => approx.)"
        else:
            continue
        out.loc[wk, "shape_src"] = "WCI_DERIVED"
        out.loc[wk, "shape_note"] = f"back-filled from {nxt.date()} WCI {r['value']:,.2f} and published change {how}"
    missing = out["index_value"].isna()
    if missing.any():
        run = (missing != missing.shift()).cumsum()
        longest = int(missing.groupby(run).sum().max())
        if longest > MAX_INTERP_GAP_WEEKS:
            raise ValueError(f"WCI gap of {longest} weeks exceeds {MAX_INTERP_GAP_WEEKS}; refusing to interpolate")
        out["index_value"] = out["index_value"].interpolate(method="time", limit_area="inside")
        out.loc[missing, "shape_src"] = "WCI_INTERPOLATED"
        out.loc[missing, "shape_note"] = "linear interpolation between neighbouring WCI weeks"
    out = out.loc[FIRST_WEEK:LAST_WEEK]
    if out["index_value"].isna().any():
        raise ValueError("WCI missing at the edge of the output range; cannot interpolate")
    return out


# ----------------------------------------------------------------------------------------------------------------
# 2. India-inbound level anchors (Container News monthly rate analyses)
# ----------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Article:
    key: str
    url: str
    published: str


ARTICLES = [
    Article("cn_2022_04", "https://container-news.com/freight-rate-analysis-for-indian-shippers-reflects-easing-signs-on-some-trades/", "2022-04-29"),
    Article("cn_2022_07", "https://container-news.com/cn-freight-rate-analysis-for-indian-trades-reflects-easing-trends-but-for-intra-asia/", "2022-07-27"),
    Article("cn_2022_08", "https://container-news.com/cn-analysis-slowing-exports-send-freight-rates-on-major-trades-out-of-india-further-downwards/", "2022-08-30"),
    Article("cn_2022_09", "https://container-news.com/cn-analysis-india-container-freight-rates-continue-to-slide-amid-weakening-demand/", "2022-09-30"),
    Article("mg_2022_11", "https://www.maritimegateway.com/freight-rates-on-indian-trades-hit-new-lows/", "2022-11-29"),
    Article("cn_2023_01", "https://container-news.com/cn-analysis-freight-rates-on-indian-trades-continue-to-cool-amid-falling-export-volumes/", "2023-01-30"),
]


def _article_path(a: Article) -> Path:
    slug = a.url.rstrip("/").split("/")[-1][:80]
    prefix = "maritimegateway" if "maritimegateway" in a.url else "containernews"
    return ARTICLE_DIR / f"{prefix}_{slug}.html"


def article_text(a: Article) -> str:
    return html_to_text(fetch_cached(a.url, _article_path(a), retries=4, backoff_s=4, min_bytes=5000))


def _find(text: str, pattern: str, key: str) -> re.Match:
    m = re.search(pattern, text)
    if not m:
        raise ValueError(f"Anchor pattern not found in {key}: {pattern!r} — article changed or cache corrupt")
    return m


def _sentence(text: str, m: re.Match) -> str:
    start = text.rfind(". ", 0, m.start()) + 2
    end = text.find(". ", m.end())
    return text[start : end + 1 if end > 0 else len(text)].strip()


def india_inbound_anchors() -> pd.DataFrame:
    """Observed and derived USD/box anchor points for India-inbound lanes, each traced to its sentence.

    Columns: date, lane, value, unit, flag, rule, url, published, available_from, retrieved, quote.
    `lane` ∈ {USEC_WI_FEU, EUR_WI_FEU}. flag ∈ {REPORTED, DERIVED}. `published` = the article the quote is taken
    from; `available_from` = the latest publication date of EVERY article the value depends on (e.g. the June USEC
    anchor = August level / (1 − July article's drop) is only knowable once the August article is out).
    """
    by_key = {a.key: a for a in ARTICLES}
    txt = {k: article_text(a) for k, a in by_key.items()}
    rows: list[dict] = []

    def add(date, lane, value, flag, rule, key, m, depends_on=()):
        a = by_key[key]
        avail = max(by_key[k].published for k in (key, *depends_on))
        rows.append(dict(date=pd.Timestamp(date), lane=lane, value=round(float(value), 2), unit="USD/box", flag=flag,
                         rule=rule, url=a.url, published=a.published, available_from=avail,
                         retrieved=retrieved(_article_path(a)), quote=_sentence(txt[key], m)))

    # --- USEC (New York) -> West India (Nhava Sheva/Mundra), 40ft ---------------------------------------------
    usec = r"US\$[\d,]+/(?:TEU|20-foot box) and US\$([\d,]+)/(?:FEU|40-foot box) from USEC"
    m = _find(txt["cn_2022_08"], usec, "cn_2022_08")
    aug = _num(m.group(1))
    add("2022-08-30", "USEC_WI_FEU", aug, "REPORTED", "August 2022 average", "cn_2022_08", m)
    steady = _find(txt["cn_2022_08"], r"On the return leg, average rate levels have remained steady", "cn_2022_08")
    add("2022-07-27", "USEC_WI_FEU", aug, "DERIVED", "Aug article: return leg 'remained steady' vs July",
        "cn_2022_08", steady)
    drop = _find(txt["cn_2022_07"], r"On the return leg, rates offered by leading liners have dropped by between "
                                    r"(\d+)% and (\d+)%", "cn_2022_07")
    lo, hi = float(drop.group(1)) / 100, float(drop.group(2)) / 100
    assert abs((lo + hi) / 2 - config.value("freight_usec_jun2022_drop_frac")) < 1e-9, "YAML/article mismatch"
    add("2022-06-30", "USEC_WI_FEU", aug / (1 - config.value("freight_usec_jun2022_drop_frac")), "DERIVED",
        f"Jul article: return leg dropped {lo:.0%}-{hi:.0%} vs June (midpoint used) applied to the Aug level",
        "cn_2022_07", drop, depends_on=("cn_2022_08",))
    m = _find(txt["cn_2022_09"], usec, "cn_2022_09")
    add("2022-09-30", "USEC_WI_FEU", _num(m.group(1)), "REPORTED", "September 2022 average", "cn_2022_09", m)
    m = _find(txt["mg_2022_11"], r"not changed from the levels maintained by major operators last month – pegged at "
                                 r"US\$[\d,]+/20-foot box and US\$([\d,]+)/40-foot box from USEC", "mg_2022_11")
    add("2022-11-29", "USEC_WI_FEU", _num(m.group(1)), "REPORTED", "November 2022 average", "mg_2022_11", m)
    add("2022-10-31", "USEC_WI_FEU", _num(m.group(1)), "DERIVED", "Nov article: 'not changed' vs October",
        "mg_2022_11", m)
    m = _find(txt["cn_2023_01"], r"US\$([\d,]+)/40-foot box, down from US\$([\d,]+), from USEC", "cn_2023_01")
    add("2022-12-30", "USEC_WI_FEU", _num(m.group(2)), "REPORTED", "December 2022 level (Jan-2023 article)",
        "cn_2023_01", m)
    add("2023-01-30", "USEC_WI_FEU", _num(m.group(1)), "REPORTED", "January 2023 average", "cn_2023_01", m)

    # --- Felixstowe/Rotterdam -> West India, 40ft (sibling India-inbound backhaul lane) ---------------------------
    m = _find(txt["cn_2022_04"], r"eastbound rates are at the same levels as they were at the end of March — at around "
                                 r"US\$[\d,]+/20-foot container and US\$([\d,]+)/40-foot container", "cn_2022_04")
    add("2022-03-31", "EUR_WI_FEU", _num(m.group(1)), "DERIVED", "Apr article: 'same levels as end of March'",
        "cn_2022_04", m)
    add("2022-04-29", "EUR_WI_FEU", _num(m.group(1)), "REPORTED", "April 2022 average", "cn_2022_04", m)
    m = _find(txt["cn_2022_07"], r"Eastbound rates have also tapered off – now hovering at around US\$[\d,]+/20-foot "
                                 r"container and US\$([\d,]+)/40-foot container, versus US\$[\d,]+ and US\$([\d,]+)",
              "cn_2022_07")
    add("2022-07-27", "EUR_WI_FEU", _num(m.group(1)), "REPORTED", "July 2022 average", "cn_2022_07", m)
    add("2022-06-30", "EUR_WI_FEU", _num(m.group(2)), "REPORTED", "June 2022 level (Jul article 'versus')",
        "cn_2022_07", m)
    m = _find(txt["cn_2022_08"], r"now hovering at around US\$[\d,]+/TEU and US\$([\d,]+)/FEU, versus", "cn_2022_08")
    add("2022-08-30", "EUR_WI_FEU", _num(m.group(1)), "REPORTED", "August 2022 average", "cn_2022_08", m)
    m = _find(txt["cn_2022_09"], r"hovering at US\$[\d,]+/20-foot container and US\$([\d,]+)/40-foot container, versus",
              "cn_2022_09")
    add("2022-09-30", "EUR_WI_FEU", _num(m.group(1)), "REPORTED", "September 2022 average", "cn_2022_09", m)

    df = pd.DataFrame(rows).sort_values(["lane", "date"]).reset_index(drop=True)
    _check_against_register(df)
    return df


def _check_against_register(df: pd.DataFrame) -> None:
    """The DIRECT anchor values in logistics.yaml must equal what the cached articles actually say."""
    for lane, key in (("USEC_WI_FEU", "freight_usec_west_india_usd_feu_reported"),
                      ("EUR_WI_FEU", "freight_europe_west_india_usd_feu_reported")):
        yaml_pts = {pd.Timestamp(d): float(v) for d, v in config.get(key).path}
        got = df[(df["lane"] == lane) & (df["flag"] == "REPORTED")].set_index("date")["value"].to_dict()
        if lane == "EUR_WI_FEU":  # 31 Mar is stated in the text ("same levels as end of March"), tagged DERIVED
            got.update(df[(df["lane"] == lane) & (df["date"] == "2022-03-31")].set_index("date")["value"].to_dict())
        if got != yaml_pts:
            raise ValueError(f"{key} in logistics.yaml {yaml_pts} != article-extracted {got}")


def usec_anchor_series(anchors: pd.DataFrame) -> pd.DataFrame:
    """USEC->West India FEU anchors incl. sibling-lane proxies for Mar/Apr 2022 (before the USEC leg was reported).

    Sibling rule: USEC_t = EUR_t × mean(USEC/EUR over months where both are known). The ratio is computed from the
    data (Jun–Sep 2022: ~0.74–0.84), not assumed.
    """
    usec = anchors[anchors["lane"] == "USEC_WI_FEU"].set_index("date")
    eur = anchors[anchors["lane"] == "EUR_WI_FEU"].set_index("date")
    common = usec.index.intersection(eur.index)
    ratio = float((usec.loc[common, "value"] / eur.loc[common, "value"]).mean())
    first_usec = usec.index.min()
    sib = eur[eur.index < first_usec].copy()
    sib["value"] = (sib["value"] * ratio).round(2)
    sib["lane"] = "USEC_WI_FEU"
    sib["flag"] = "SIBLING"
    sib["rule"] = [f"EUR->WI {v:,.0f} x USEC/EUR ratio {ratio:.3f} (mean of {len(common)} common months)"
                   for v in eur.loc[sib.index, "value"]]
    ratio_avail = max(usec.loc[common, "available_from"].max(), eur.loc[common, "available_from"].max())
    sib["available_from"] = [max(a, ratio_avail) for a in sib["available_from"]]
    out = pd.concat([sib, usec]).sort_index()
    out.attrs["usec_eur_ratio"] = ratio
    out.attrs["ratio_months"] = [d.date().isoformat() for d in common]
    return out


def level_available_from(weeks: pd.DatetimeIndex, anchors: pd.DataFrame) -> pd.Series:
    """Latest publication date of the anchors that set k(t): the bracketing anchors (or the nearest one outside)."""
    idx = anchors.index
    avail = anchors["available_from"]
    out = []
    for t in weeks:
        before, after = idx[idx <= t], idx[idx >= t]
        used = ([before.max()] if len(before) else []) + ([after.min()] if len(after) else [])
        out.append(max(avail.loc[d] for d in used))
    return pd.Series(out, index=weeks)


def ratio_path(index: pd.Series, anchors: pd.DataFrame) -> pd.Series:
    """k(t) = anchor / WCI at the anchor date; log-linear interpolation in calendar time; flat beyond the ends."""
    daily = index.resample("D").interpolate(method="time")
    daily = daily.reindex(pd.date_range(daily.index.min(), max(daily.index.max(), anchors.index.max()), freq="D"))
    daily = daily.ffill()
    k = pd.Series(anchors["value"].to_numpy() / daily.reindex(anchors.index).to_numpy(), index=anchors.index)
    x = index.index.map(pd.Timestamp.toordinal).to_numpy(dtype=float)
    xa = k.index.map(pd.Timestamp.toordinal).to_numpy(dtype=float)
    return pd.Series(np.exp(np.interp(x, xa, np.log(k.to_numpy()))), index=index.index)


# ----------------------------------------------------------------------------------------------------------------
# 3. assemble
# ----------------------------------------------------------------------------------------------------------------
def build() -> pd.DataFrame:
    """Build the weekly lane table from caches (network only if a cache is missing and DESK_OFFLINE is unset)."""
    pts = wci_points()
    wk = weekly_wci(pts)
    anchors = india_inbound_anchors()
    usec_anch = usec_anchor_series(anchors)

    k = ratio_path(wk["index_value"], usec_anch)
    usec_box = wk["index_value"] * k
    first_a, last_a = usec_anch.index.min(), usec_anch.index.max()

    ref_date = pd.Timestamp(config.value("freight_jea_nsa_ref_date"))
    ref_week = ref_date + pd.offsets.Week(weekday=4) if ref_date.weekday() != 4 else ref_date
    jea_ref = config.value("freight_jea_nsa_usd_box_ref")
    jea_box = jea_ref * usec_box / usec_box.loc[ref_week]

    p20 = config.value("container_payload_mt_20ft")
    p40 = config.value("container_payload_mt_40ft")
    out = pd.DataFrame(index=wk.index)
    out.index.name = "week_end"
    out["freight_jea_nsa_usd_t"] = (jea_box / p20).round(2)
    out["freight_usec_mun_usd_t"] = (usec_box / p40).round(2)
    out["index_name"] = INDEX_NAME
    out["index_value"] = wk["index_value"].round(2)

    first_own = usec_anch.index[usec_anch["flag"] != "SIBLING"].min()  # first anchor from the USEC leg itself
    level_avail = level_available_from(out.index, usec_anch)
    level = np.select(
        [out.index < first_a, out.index < first_own, out.index > last_a],
        ["EXTRAP_PRE", "SIBLING", "EXTRAP_POST"],
        default="ANCHORED",
    )
    out["freight_src"] = [f"{s}|USEC:{lv}|JEA:ASSUMPTION" for s, lv in zip(wk["shape_src"], level)]
    notes = []
    for t, s_note, lv in zip(out.index, wk["shape_note"], level):
        parts = [f"USEC 40ft {usec_box.loc[t]:,.0f} USD/box (WCI x k={k.loc[t]:.4f}; k {lv.lower()} "
                 f"vs Container News USEC->West India anchors)",
                 f"JEA 20ft {jea_box.loc[t]:,.0f} USD/box (assumed {jea_ref:,.0f} at {ref_week.date()} x USEC shape)",
                 f"level inputs public from {level_avail.loc[t]} "
                 f"({(pd.Timestamp(level_avail.loc[t]) - t).days:+d} days vs week end; hindsight-calibrated)"]
        if s_note:
            parts.insert(0, s_note)
        notes.append("; ".join(parts))
    out["note"] = notes
    out.attrs.update(anchors=anchors, usec_anchors=usec_anch, wci_points=pts)
    return out.reset_index()


def write_points(df: pd.DataFrame) -> None:
    pts: pd.DataFrame = df.attrs["wci_points"]
    POINTS_WCI.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "date": pts["assessed"].dt.date,
            "value": pts["value"],
            "unit": "USD/FEU (Drewry WCI composite, assessed Thursday)",
            "wow_pct_change_published": pts["wow_pct"],
            "wow_usd_change_published": pts["wow_usd"],
            "url": pts["url"],
            "archive_url": pts["archive_url"],
            "archived": pts["archived"],
            "retrieved": pts["retrieved"],
        }
    ).to_csv(POINTS_WCI, index=False)
    anchors: pd.DataFrame = df.attrs["usec_anchors"].reset_index()
    eur = df.attrs["anchors"]
    allp = pd.concat([anchors, eur[eur["lane"] == "EUR_WI_FEU"]], ignore_index=True)
    allp["date"] = pd.to_datetime(allp["date"]).dt.date
    POINTS_ANCHORS.parent.mkdir(parents=True, exist_ok=True)
    allp[["date", "lane", "value", "unit", "flag", "rule", "url", "published", "available_from", "retrieved",
          "quote"]].to_csv(POINTS_ANCHORS, index=False)


def main() -> None:
    if not offline():
        download_wci_snapshots()
    df = build()
    write_points(df)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False, date_format="%Y-%m-%d")

    src = df["freight_src"].str.split("|").str[0].value_counts()
    n = len(df)
    print(f"freight_weekly.csv: {n} weeks {df['week_end'].min().date()}..{df['week_end'].max().date()}")
    print("  shape coverage: " + ", ".join(f"{k} {v} ({v / n:.0%})" for k, v in src.items()))
    ratio = df.attrs["usec_anchors"].attrs["usec_eur_ratio"]
    print(f"  USEC/EUR India-inbound ratio used for Mar/Apr-2022 sibling anchors: {ratio:.3f}")
    idx = df.set_index("week_end")
    for d in ("2022-03-04", "2022-06-03", "2022-08-26"):
        r = idx.loc[d]
        print(f"  {d}: JEA_NSA {r['freight_jea_nsa_usd_t']:.2f} USD/t | USEC_MUN {r['freight_usec_mun_usd_t']:.2f} "
              f"USD/t | WCI {r['index_value']:,.0f}")
    a, b = idx.loc["2022-03-04"], idx.loc["2022-08-26"]
    for c in ("freight_jea_nsa_usd_t", "freight_usec_mun_usd_t", "index_value"):
        print(f"  {c}: {b[c] / a[c] - 1:+.1%} (2022-03-04 -> 2022-08-26)")


if __name__ == "__main__":
    main()
