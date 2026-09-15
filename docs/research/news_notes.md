# News headlines (Phase 0 → optional Phase 7 sentiment overlay)

Owner module: `desk/sentiment/fetch_news.py` · Output: `data/processed/headlines_weekly.csv` (CONTRACTS §4.4) ·
Raw cache: `data/raw/news/<edition>_<query-slug>_<week_end>.xml` · Audit trail: `data/interim/news/_audit_headlines.csv` ·
Tests: `tests/test_fetch_news.py`

## What this is (and is not)

A weekly sample of **real, public news headlines** about aluminium, LME base metals, scrap and Indian steel prices,
for the 28 weeks ending Friday 2022-02-25 → 2022-09-02 (the Mar–Aug 2022 window plus one week either side). It
exists only to feed the optional, clearly-labelled sentiment overlay (spec 5.2). It is **not** a complete news
record, not a trading signal, and not a measure of what a desk trader actually read that week.

Provenance flag: **DIRECT for the headline text, publisher name, link and publication timestamp** — each row is an
item returned by Google News RSS and stored as returned (only the trailing " - Publisher" suffix is moved into
`source`). The *selection* of headlines is a PROXY for "the news flow that week": it depends on our query list,
Google's ranking, and the relevance filter below.

## Method

1. **Calendar.** Weeks end Friday (`W-FRI`, CONTRACTS §3). Week `w` covers Saturday 00:00 UTC → Friday 23:59:59 UTC.
2. **Source.** Google News RSS search, e.g.
   `https://news.google.com/rss/search?q=aluminium+LME+after:2022-03-05+before:2022-03-12&hl=en-IN&gl=IN&ceid=IN:en`.
   Probing on 2026-09-16 showed `after:X before:Y` returns items dated X..Y **inclusive** (day granularity), so each
   week is requested over [Saturday, next Saturday] and then **strictly** filtered on `pubDate` into the W-FRI week.
   Items outside the week are dropped (status `out_of_window` in the audit), never moved to another week.
3. **Editions.** Mostly `en-IN` (the desk is Mumbai-based) plus three `en-US` core queries. A probe of one March 2022
   week found ~80 % title overlap between editions for the same query, and in the full pull the en-US core queries
   were credited with almost no unique headlines (see "Kept headlines by credited query"): for 2022 archive
   searches the edition changes little. They are kept because the cache already exists and they cost nothing
   offline.
4. **Queries.** Direction-neutral keyword searches (no "surge"/"slump" words, so the sample does not pre-load
   sentiment). Core queries run for every week; extra queries run only for weeks with fewer than 10 kept headlines
   after the core set. The exact lists are in the generated section below and in `CORE_QUERIES` / `EXTRA_QUERIES`.
   Google treats space-separated words as AND over the whole article, so many returned items are only loosely
   related — hence step 5.
5. **Relevance filter (title-level, case-insensitive).** After stripping the publisher suffix, the title must match
   at least one of: `aluminium`, `aluminum`, `alumina`, `bauxite`, `smelt*` (smelter/smelting), `scrap*`, `LME`
   (whole word, so "helmet" does not match), `metal` (substring: metals, metallurgy, base-metals), `steel*`.
   Every matched term is recorded per item in the audit file (`relevance_match`). Publisher names never count
   (e.g. a title from "Steel Times" does not pass on its source name).
6. **Exclusion rules (added after inspecting the first full pull on 2026-09-16).** The generic word "metal" let in
   ~100 gold/precious-metal items (mostly Indian daily "yellow metal" gold-rate pages) and dozens of journal articles, which would swamp a
   base-metals sentiment score. Five transparent rules, applied in order, set status `excluded` and record the rule
   in `exclusion_rule`:
   - `scholarly_journal` — publisher is one of Nature, Frontiers, Wiley Online Library, Science | AAAS, Cambridge
     University Press & Assessment, ChemistryViews (research articles, not market news);
   - `precious_metals_not_base` — title mentions gold/silver/platinum/palladium/precious/jewellery **and** no
     aluminium-chain term (aluminium, aluminum, alumina, bauxite, smelt*, scrap*, LME), so "LME to end gold and
     silver contracts" is kept;
   - `heavy_metals_pollution` — "heavy metal(s)" with no aluminium-chain term;
   - `retitled_update_prefix` — title starts with "Update" / "Updated" (added after review: the page was re-titled
     after publication and may carry later information, see "Known biases");
   - `retitled_future_month_year` — title contains "<Month> <year>" with the year after the publication year and not
     introduced by a forward-looking word (by/until/from/in/…). This caught evergreen vehicle price-listing pages
     carrying "September 2026" in titles attached to 2022 pubDates (apparently re-crawled page titles). Forecast titles such as "operating after
     2024" are kept; every kept title that mentions a year after 2022 is listed below for manual review.
7. **De-duplication.** Titles are normalised (Unicode NFKC, case-folded, punctuation removed, whitespace collapsed)
   and de-duplicated across queries, editions and weeks. The earliest publication wins; ties go to the query that
   comes first in the priority list, which is the query credited in the `query` column (`<edition>:<query>`).
8. **Caching / offline.** Every feed is cached via `desk.data._http.fetch_cached` (retries with exponential
   backoff), with a ~2 s pause between live calls. Non-RSS bodies (consent pages) are deleted and retried rather
   than cached. `DESK_OFFLINE=1` rebuilds from cache only; `tests/test_fetch_news.py` checks that an offline rebuild
   reproduces `headlines_weekly.csv` exactly.

## Known biases and limitations

- **Google News ranking is opaque and not stable.** Each RSS search returns a small ranked subset (at most 33 items
  per query-week here, median 10 — see the generated stats), not everything published. Re-running the same URL on
  another day can return a different set; the cached XML in `data/raw/news/` is the frozen record this project uses.
- **Weekly counts are not a clean "news intensity" measure.** The busiest week is the LME nickel-crisis week ending
  2022-03-11, but counts elsewhere move with Google's archive depth and ranking as much as with events. P7 should
  score average tone per week, not headline volume.
- **Titles are Google's crawl of the page title, not necessarily the headline as first printed.** The re-titled
  price pages above show titles can be updated after publication; most wire/trade-press titles look contemporaneous,
  but this was not verified article by article. A concrete look-ahead case found in review: Recycling Today's item
  dated Tue 08-Mar-2022 (week ending 2022-03-11) carried the title "Update: LME nickel trading to resume March 16", a
  resumption date the independent reviewer traced to announcements around 14–15 Mar 2022 (an S&P Global item of that
  title dated 15-Mar-2022; not re-retrieved here) — i.e. the page was very likely re-titled after publication. Google
  returns the current title with the original pubDate, so a sentiment score for that week would have seen later news.
  Rule `retitled_update_prefix` now excludes titles starting "Update"/"Updated" (2 kept rows removed: that item and
  "Updated: SDI ventures into aluminum sheet production", 19-Jul-2022), and every kept title citing a day-month after
  its pubDate is flagged in the audit (`cites_later_date`) and listed below for manual review — the ones found read as
  genuine forward-looking headlines (event dates, board meetings, price-hike dates).
- **Publisher mix.** Results skew to English-language wires, Indian business dailies and free trade press that Google
  indexes well (top publishers are listed below). Price-reporting agencies that actually set physical scrap and
  premium benchmarks are nearly absent from the kept set (Fastmarkets 2, spglobal.com 3, no Argus, Platts, Mysteel,
  BigMint or Kallanish items), and there are no non-English Chinese or Hindi sources.
- **Indian steel / equity tilt.** `steel*` is the most-matched relevance term: Indian steel company and share-market
  stories (e.g. Tata Steel and SAIL results, "steel stocks to watch" pieces) are prominent, especially via the
  "steel prices India" query, and are only loosely linked to aluminium scrap economics.
- **Residual title-keyword noise.** The filter is deliberately simple and auditable, so it still keeps off-topic
  items whose titles happen to say "aluminium"/"metal"/"steel" (aluminium-frame bicycles, an aluminium watch, a
  guitar neck, steel-frame bikes, junior-miner press releases) and it drops genuinely relevant base-metal stories
  whose titles only say "nickel" or "copper" (e.g. several nickel-price items in March 2022). P7 should treat the
  weekly score as a noisy supporting signal; `relevance_match` / `exclusion_rule` in the audit file allow a stricter
  subset if needed.
- **Timestamps are day-granular.** Almost every kept `pubDate` is exactly `07:00:00 GMT` or `08:00:00 GMT` (counts in
  the generated stats) — consistent with a date stamped at midnight US Pacific time (PDT/PST), which is our
  inference, not documented by Google. Intraday ordering is meaningless, and an item near a week boundary may sit
  one day off its local (IST) publication date.
- **Links are Google News redirect URLs** (`news.google.com/rss/articles/...`), not publisher URLs; they are stored
  exactly as returned and may stop resolving in future.

## Terms-of-use note

Only feed **metadata** is stored: title, publisher name, publication time and the Google News link. No article
bodies or images are downloaded or stored; the cached RSS `description` field contains only an HTML anchor repeating
the title plus the publisher name (checked in the cache), no article text. Headlines are used for a non-commercial academic simulation,
attributed to their publishers, and never paraphrased or edited. Google News RSS is provided for personal,
non-commercial feed-reader use; anyone re-using this dataset beyond this academic project should check Google's
and each publisher's current terms.

## Generated coverage

<!-- COVERAGE:START (generated by desk.sentiment.fetch_news.main; do not hand-edit) -->

Totals: **649 kept headlines** across **28 of 28 weeks**; median 24/week, min 12, max 39. Weeks below 10: none.

RSS items per non-empty feed: median 10, max 33. Kept `published_utc` time-of-day — 07:00:00Z: 565, 08:00:00Z: 74, other: 10.

### Queries (exact strings sent, before the date operators)

| set | edition | query |
|---|---|---|
| core | en-IN | aluminium LME |
| core | en-IN | aluminium price |
| core | en-IN | aluminum prices |
| core | en-IN | aluminium scrap |
| core | en-IN | aluminum scrap |
| core | en-IN | LME metals |
| core | en-IN | base metals |
| core | en-IN | metal prices |
| core | en-IN | steel prices India |
| core | en-US | aluminum prices |
| core | en-US | aluminum scrap |
| core | en-US | LME metals |
| extra (thin weeks only) | en-IN | aluminium |
| extra (thin weeks only) | en-US | aluminum |
| extra (thin weeks only) | en-IN | steel prices |
| extra (thin weeks only) | en-IN | Hindalco OR Vedanta OR NALCO |
| extra (thin weeks only) | en-US | aluminium smelter |
| extra (thin weeks only) | en-IN | non-ferrous metals |

### Coverage per week (week ending Friday)

| week_end | headlines | feeds_fetched | extra_queries | below_min |
|---|---|---|---|---|
| 2022-02-25 | 17 | 12 | no |  |
| 2022-03-04 | 16 | 12 | no |  |
| 2022-03-11 | 39 | 12 | no |  |
| 2022-03-18 | 34 | 12 | no |  |
| 2022-03-25 | 26 | 12 | no |  |
| 2022-04-01 | 19 | 12 | no |  |
| 2022-04-08 | 23 | 12 | no |  |
| 2022-04-15 | 17 | 12 | no |  |
| 2022-04-22 | 29 | 12 | no |  |
| 2022-04-29 | 25 | 12 | no |  |
| 2022-05-06 | 18 | 12 | no |  |
| 2022-05-13 | 17 | 12 | no |  |
| 2022-05-20 | 14 | 12 | no |  |
| 2022-05-27 | 31 | 12 | no |  |
| 2022-06-03 | 25 | 12 | no |  |
| 2022-06-10 | 26 | 12 | no |  |
| 2022-06-17 | 24 | 12 | no |  |
| 2022-06-24 | 12 | 12 | no |  |
| 2022-07-01 | 24 | 12 | no |  |
| 2022-07-08 | 24 | 12 | no |  |
| 2022-07-15 | 15 | 12 | no |  |
| 2022-07-22 | 26 | 12 | no |  |
| 2022-07-29 | 27 | 12 | no |  |
| 2022-08-05 | 29 | 18 | yes |  |
| 2022-08-12 | 20 | 12 | no |  |
| 2022-08-19 | 25 | 12 | no |  |
| 2022-08-26 | 25 | 12 | no |  |
| 2022-09-02 | 22 | 12 | no |  |

### RSS item outcomes (all feeds, before/after filters)

| status | rss_items |
|---|---|
| irrelevant | 2251 |
| duplicate | 786 |
| kept | 649 |
| out_of_window | 186 |
| excluded | 170 |

### Exclusion rules tripped (in-window, relevant items only; before de-duplication)

| exclusion_rule | in_window_items |
|---|---|
| precious_metals_not_base | 111 |
| scholarly_journal | 40 |
| retitled_update_prefix | 9 |
| retitled_future_month_year | 8 |
| heavy_metals_pollution | 2 |

### Kept titles that mention a year after 2022 (manual review: forecasts are fine, re-titled pages are not)

| week_end | source | title |
|---|---|---|
| 2022-04-22 | statista.com | Forecast global steel price 2023 |
| 2022-04-22 | PR Newswire | Aluminum Market: 74% of Growth to Originate from APAC | By End-user (transportation, construction, packaging, electrical engineering, and others), Production Process, and Geography | Global Opportunity Analysis and Industry Forecast, 2020-2024 |
| 2022-07-29 | RNZ | Tiwai Point aluminium smelter begins talks to continue operating after 2024 |

### Kept titles citing a day-month after their pubDate (manual look-ahead review: could be a re-titled page)

| week_end | published_utc | source | title |
|---|---|---|---|
| 2022-03-18 | 2022-03-15T07:00:00Z | County of Union, New Jersey | Union County Offers First Scrap Metal Recycling Events of 2022 on Thursday, April 7 and Saturday, April 16 |
| 2022-04-22 | 2022-04-18T07:00:00Z | financialexpress.com | Tata Steel to consider stock split at May 3 board meet |
| 2022-05-27 | 2022-05-24T07:00:00Z | County of Union, New Jersey | Free Scrap Metal Recycling for Union County Residents, June 2 and 18 |
| 2022-06-03 | 2022-05-28T07:00:00Z | The Economic Times | India's longest steel bridge Mahatma Gandhi Setu to be fully functional by June 7th |
| 2022-06-10 | 2022-06-09T07:00:00Z | Reuters | Britannia Global Markets to give up LME membership on June 20 |
| 2022-06-24 | 2022-06-21T07:00:00Z | County of Union, New Jersey | Union County Offers Next Scrap Metal Recycling Events of 2022 on Thursday, July 7 and Saturday, July 16 |
| 2022-07-01 | 2022-06-29T07:00:00Z | Livemint | Steel prices may rise from 1 July amid high input costs: JSPL MD |

### Kept headlines by credited query

| credited_query | kept_headlines |
|---|---|
| en-IN:aluminium price | 158 |
| en-IN:metal prices | 128 |
| en-IN:steel prices India | 83 |
| en-IN:aluminum prices | 51 |
| en-IN:base metals | 46 |
| en-IN:aluminium LME | 45 |
| en-IN:LME metals | 45 |
| en-IN:aluminum scrap | 36 |
| en-IN:aluminium scrap | 34 |
| en-US:aluminum | 9 |
| en-IN:steel prices | 6 |
| en-IN:aluminium | 5 |
| en-US:LME metals | 1 |
| en-IN:non-ferrous metals | 1 |
| en-US:aluminum prices | 1 |

### Relevance terms matched by kept titles (a title can match several)

| relevance_term | kept_titles_matching |
|---|---|
| steel | 189 |
| metal | 173 |
| aluminum | 117 |
| aluminium | 116 |
| scrap | 43 |
| LME | 37 |
| alumina | 14 |
| smelter | 13 |
| bauxite | 5 |

### Top 15 publishers in the kept set

| source | kept_headlines |
|---|---|
| Reuters | 43 |
| The Economic Times | 27 |
| AL Circle | 27 |
| Recycling Today | 18 |
| GMK Center | 16 |
| Bloomberg.com | 16 |
| mining.com | 15 |
| Livemint | 14 |
| Moneycontrol.com | 12 |
| EUROMETAL | 8 |
| Business Standard | 7 |
| MetalMiner | 6 |
| South China Morning Post | 6 |
| Business Today | 6 |
| news24.com | 5 |

<!-- COVERAGE:END -->
