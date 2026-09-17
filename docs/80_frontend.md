# 80 — Dashboard: a read-only Streamlit frontend over the published outputs

> **ACADEMIC SIMULATION — not actual trades.** The dashboard shows the pipeline's own tables, charts and reports. It
> adds no new analysis: every number on it is a number the pipeline published, with its source file named.

## 1. How to run

```sh
.venv/bin/pip install -r requirements.txt                              # adds streamlit and plotly (pinned)
.venv/bin/streamlit run app/streamlit_app.py --server.address localhost
```

Open the URL it prints (default <http://localhost:8501>); stop it with Ctrl+C.

- `--server.address localhost` binds the server to this machine only. It also stops Streamlit's own start-up lookup of
  the machine's external IP address, which it otherwise makes once to print an "External URL" when it runs headless.
  The app code itself never opens a network connection.
- `.streamlit/config.toml` sets a light theme on the desk palette, `server.headless = true` (no browser is opened),
  `runOnSave = false`, `fileWatcherType = "none"` and `browser.gatherUsageStats = false`. After changing code under
  `app/`, restart the server: with no file watcher, imported modules are not reloaded.
- Optional: set `DESK_APP_REPO_URL` (for example `https://github.com/<you>/<repo>/blob/main`) and links quoted from
  the docs become real links into that repository. Without it they are shown as repo-relative paths.
- Memory on this 8 GB laptop: the server starts at about 80 MB RSS. After direct loads of the Trade book, P&L, Risk,
  Reports and Market pages its footprint was about 175 MB (`top` MEM; plain RSS swung between 30 and 175 MB because
  macOS compresses idle pages). The app test files peak between 230 and 410 MB each. The 3 GB Excel recalculation is
  never loaded (the app reads only the reconciliation record).

## 2. Architecture and the honesty contract

```text
app/
  streamlit_app.py      entrypoint: set_page_config, st.navigation from components.PAGES, sidebar footer
  lib/data.py           cached, typed loaders; headline facts; spec index; build status (Excel reconciliation, commit)
  lib/components.py     SIM banner, P&L headline with its band, captions, flag badges, downloads, page header, PAGES
  lib/charts.py         Plotly helpers: palette, window shading, event markers, SIM watermark
  lib/docs_text.py      markdown sections quoted from docs/*.md, links rewritten for the app
  views/*.py            one file per page; each also runs on its own
.streamlit/config.toml
tests/test_app_pages.py            shared layer, every page once, entrypoint, facts, missing data
tests/test_app_contract.py         cross-page contract: read-only source, public export, headline, captions, numbers
tests/test_app_page_*.py           each page's own filters and selectors (market_parity, book_pnl, risk,
                                   research_deliverables)
```

The page scripts live in `app/views/`, **not** `app/pages/`. Streamlit treats a `pages/` directory next to the
entrypoint as a legacy multipage app: on a freshly started server, the first request for a direct link such as
`/trade_book` then ran the page file by itself (a sidebar listing file names, no navigation groups, narrow layout)
until some session had run the entrypoint once. `tests/test_app_contract.py` fails if `app/pages/` comes back.

**Read-only.** The app reads `outputs/tables/*.csv`, `outputs/charts/*.png`, `outputs/reports/*`, `outputs/excel/*`,
`data/processed/*.csv`, `config/*.yaml` and `docs/*.md`. It never runs a pipeline stage, never writes a file and never
fetches data. A loader may select columns or filter rows; a page may do light arithmetic on a published column (the
Overview's "realised P&L + funding" is cumulative P&L minus the unrealised mark, the engine's own identity), and the
caption says so. Nothing re-derives a published result.

**One source for the headline facts.** `data.headline_facts()` runs `desk.reporting.one_pager`'s own computation
(`load_sources` → `compute_raw` → `format_facts`, over the interview pack's loaders) and re-tests the one-pager's
qualitative claims (`check_claims`). The Overview, the one-pager PDF and the README's generated block therefore quote
the same figures, formatted the same way. If a claim no longer holds, the page says so in red instead of repeating
it.

**Graceful degradation.** Every loader returns `None` for a file that is not in this copy, and the page renders
`components.missing_data(rel)`: an `st.info` that names the file and says how to rebuild it (the Phase 0 fetchers
online for the files the public export leaves out, otherwise `DESK_OFFLINE=1 .venv/bin/python run_all.py --only
<phase>`). The public export (`tools/export_public.py`, strict profile) omits `data/processed/market_daily.csv`,
`lme_daily.csv`, `freight_weekly.csv` and `headlines_weekly.csv`. The canonical fact loader reads all of its inputs
at once, so without those files `headline_facts()` takes a partial path. That path loads each input only if it is
present and runs the same component functions one by one. `tests/test_app_pages.py` checks that every fact the
partial path produces equals the canonical fact. It drops only one: the first trading day after the LME record
close, which needs the market panel's calendar and is not used by the app.

**Honesty rules the shared layer enforces.**

| Rule | Where |
|---|---|
| Every page shows "ACADEMIC SIMULATION — not actual trades" | `components.sim_banner()`, first call on every page (tested); the sidebar footer and every Plotly figure's watermark repeat it |
| The book's headline P&L appears only with its anchor-premium band, its break-even and the sign-robustness statement, read from `pnl_sensitivity_sign_robustness.csv` | `components.pnl_headline(facts)`; if the band cannot be computed the value is withheld too (tested). A book-level total elsewhere on a page (the P&L page's BOOK view) carries `components.pnl_band_note(facts)` and is withheld when `headline_band_ok(facts)` is false (tested) |
| Every chart and table has a caption naming its source files and the DIRECT / PROXY / ASSUMPTION flag where one applies | `components.source_caption(files, flags)`, flags from `data.series_flags()` and `data.param_flag(key)`; a chart and its data table may share one caption, but a heading, expander or tab ends the group (tested on every page) |
| Proxies, hypothetical stresses, synthetic data and SIM entities are labelled wherever shown | `components.flag_badge`: DIRECT, PROXY, ASSUMPTION, SIM, HYPOTHETICAL, SYNTHETIC, SENSITIVITY |
| "What this does and doesn't tell you" is quoted from the doc, not rewritten | `components.what_it_tells(doc)` via `docs_text.section` |
| The Excel reconciliation is quoted only as its status says | `data.recon_status()` wraps `desk.excel.reconciliation_status.status()`; figures only when VERIFIED |

## 3. The shared layer at a glance

| Module | Use it for |
|---|---|
| `data` | `table(name, usecols)` for any `outputs/tables` CSV; named loaders (`parity_weekly`, `parity_sensitivity(kind, wide)`, `term_structure`, `trade_book`, `trade_hedges`, `trade_eligibility_check`, `trade_cashflows(scenario)`, `trades_yaml`, `counterparties_yaml`, `mtm_daily(usecols)`, `attribution_daily(variant)` + `split_book`, `book_exposures_daily(usecols)`, `adverse_event(name)`, `mcx_variation_margin`, `pnl_sensitivity(kind)`, `var_table(name)`, `kupiec`, `mc_table(name)`, `credit_table(name)`, `margin_liquidity(name)`, `sentiment_table(name)`, `market_daily(usecols)`, `series_provenance`, `params_register`, `doc_markdown`, `report_files`, `chart_path`); `headline_facts()`; `event_markers()`; `spec_index()`; `recon_status()`; `git_commit()`; `require(value, rel)` / `MissingData`; `rebuild_hint(rel)` |
| `components` | `sim_banner()`, `page_header(title, subtitle, spec_rows)`, `pnl_headline(facts)`, `headline_band_ok(facts)`, `pnl_band_note(facts)`, `kpi_row([Kpi(...)])`, `source_caption(files, flags, note)`, `flag_badge(flag)`, `what_it_tells(doc)`, `download_button(rel)`, `missing_data(rel)`, `available(*rels)`, `guard()`, `page_link(key)`, formatters `inr_m` / `num` / `pct` / `day` (the reports' own), `PAGES` / `PAGE` |
| `charts` | `line_chart(df, x, {col: label}, events=...)`, `band_marker`, `bar_chart`, `waterfall`, `bucket_waterfall(totals)` (fixed bucket order and colours), `heatmap(wide_df)`, `histogram(values, markers)`, `shade_window`, `mark_events`, `finish`, `show(fig)` |
| `docs_text` | `section(doc, heading)`, `lead_paragraph(doc)`, `rewrite_links`, `escape_streamlit` (`$` and `~` would otherwise render as LaTeX and strikethrough), `for_streamlit` |

## 4. Page map

All nine pages are built. URL paths are the page keys (`/market`, `/parity`, …; the Overview is `/`).

| Navigation | Page | File | Spec rows | What it shows |
|---|---|---|---|---|
| — | Overview | `app/views/overview.py` | 3.3 | Pitch quoted from the one-pager; P&L headline with its band; desk KPIs; equity curve with the band at the horizon (realised/unrealised split as a toggle); attribution by bucket; six "risk in one glance" cards with flags; links; downloads (one-pager PDF, README, workbook); docs/30 §10 quoted |
| Markets & trade finder | Market data | `app/views/market.py` | 1.7, 8.1, 8.3 | Record close and crash facts; date filter; tabs for LME (cash/3M, spread, stocks), USD/INR and rates, MCX (PROXY, optional third-party mirror), freight (reconstruction warning; +40 % stress HYPOTHETICAL), at-a-glance table, series provenance with flags. Falls back to weekly series from P1 tables when the daily panel is not in the copy |
| Markets & trade finder | Trade finder (parity) | `app/views/parity.py` | 1.1–1.7 | Eligible cases against the §5a rule; grade/lane selectors; net arb vs hurdle, eligibility heatmap, landed-cost and net-arb waterfalls with line-item formulas, LME×FX and freight×duty grids (SENSITIVITY), band table, term structure (realised M+1 labelled HINDSIGHT), quality grid, anchor study; docs/10 §6.1 and §13 quoted |
| The book | Trade book | `app/views/trade_book.py` | 2.1–2.9 | Nine SIM tickets with filters; per-ticket card (rationale from `trades.yaml`, SPA terms, shipment and freight, sales, hedge stack, eligibility, SIM events); Gantt timeline; counterparties and credit use; eligibility evidence; docs/20 §10 and §12 quoted |
| The book | P&L & attribution | `app/views/pnl.py` | 3.1–3.6 | Headline with band; equity curve with the window-end and horizon bands; sign-robustness tab; per-ticket waterfall (BOOK view carries the band note); buckets over time; adverse events E1–E3 (freight +40 % HYPOTHETICAL); MCX basis risk as two-sided; docs/30 and docs/31 quoted |
| Risk | Risk pack | `app/views/risk.py` | 4.1–4.6 | GARCH vs 250/60-day VaR with exceptions, lead/lag verdicts, Kupiec and Christoffersen, unit backtests, GARCH fits, MCX beta (PROXY); Monte Carlo histogram with VaR/ES and stresses (freight +40 % and BIS-QCO HYPOTHETICAL); credit scoring (ILLUSTRATIVE, SYNTHETIC data) and tracker; liquidity and margin with the breach conventions and the fortnight stress; the risk policy memo behind the headline component |
| Research | Sentiment overlay | `app/views/sentiment.py` | 5.2 | "No evidence" verdict quoted only while the tables show no significant lead; weekly tone vs LME; lead/lag with intervals; episode verdicts; headline explorer (falls back to the weekly extremes); docs/70 caveats quoted |
| Deliverables | Reports & docs | `app/views/reports.py` | 5.1, 5.3, 5.4, 8.2, 8.6 | Headline with band; desk notes, post-mortem, risk memo and one-pager rendered with their charts and downloads; interview pack; README by section; Excel status (figures only when VERIFIED); docs browser; spec coverage from `INDEX.md` |
| Deliverables | Data & assumptions | `app/views/data_assumptions.py` | 8.1, 8.3–8.5 | Parameter register with flag/status filters and PENDING list; series provenance and units; verification log; every model's "What this does and doesn't tell you"; download manifest (counts only); public-export policy; review logs |

Each page's header opens an expander listing its spec rows, their status and any caveat, parsed from
[`INDEX.md`](INDEX.md).

## 5. Adding or building a page

1. Register it (or keep its entry) in `components.PAGES`: key, navigation section, file, title, Material icon, a
   one-line blurb and its spec rows. `test_every_page_file_is_registered_in_navigation` fails until file and entry
   agree.
2. Start the file with the bootstrap and the two honesty calls:

   ```python
   import sys
   from pathlib import Path

   ROOT = Path(__file__).resolve().parents[2]
   if str(ROOT) not in sys.path:
       sys.path.insert(0, str(ROOT))

   import streamlit as st  # noqa: E402

   from app.lib import charts, components, data  # noqa: E402

   spec = components.PAGE["risk"]
   components.sim_banner()
   components.page_header(spec.title, spec.blurb, spec.spec_rows)

   var = data.var_table("daily", usecols=["date", "in_window", "var_garch_inr", "var_hist250_inr"])
   if var is None:
       components.missing_data(data.table_rel("var_daily"))
   else:
       fig = charts.line_chart(var.assign(g=var["var_garch_inr"] / 1e6, h=var["var_hist250_inr"] / 1e6), "date",
                               {"g": "GARCH(1,1)", "h": "250-day history"}, y_title="₹ million",
                               events=data.event_markers())
       charts.show(fig)
       components.source_caption(["var_daily"], {"MCX series": "PROXY"})
   components.what_it_tells("docs/40_var_garch.md")
   ```

3. Do not call `st.set_page_config` in a page (only the entrypoint does), and do not read navigation or session state
   set by another page: `AppTest.from_file` runs each page on its own.
4. Headline P&L only through `components.pnl_headline(data.headline_facts())`. Name columns for the large tables
   (`mtm_daily`, `book_exposures_daily`, `mc_pnl_distribution`). Keep figures modest (a few thousand points).
5. For a block that needs several files, either check first with `if components.available(rel_a, rel_b):` or raise
   with `data.require(loader(...), rel)` inside `with components.guard():`.
6. Put the file in `app/views/` (never `app/pages/`, see §2) and run the page's tests:
   `.venv/bin/python -m pytest -q tests/test_app_pages.py tests/test_app_contract.py -k <file stem>`.

## 6. Testing

Six test files, 104 tests, all under `streamlit.testing.v1.AppTest` (no browser, no server). Measured on this
machine, one file at a time:

| File | Tests | Time | Peak RSS | Covers |
|---|--:|--:|--:|---|
| `tests/test_app_pages.py` | 22 | 7 s | 280 MB | shared layer, every page once, entrypoint, facts, missing data (below) |
| `tests/test_app_contract.py` | 35 | 15 s | 410 MB | read-only source scan (no writes, network or stage imports); no `app/pages/`; every page and the entrypoint on a copy without `market_daily.csv` and `headlines_weekly.csv`; the headline only with its band on every page, the P&L BOOK view's band note, the BOOK view withheld without the band; a source caption after every chart, table and image; 15 displayed numbers against the tables and `one_pager.md` |
| `tests/test_app_page_market_parity.py` | 11 | 8 s | 230 MB | Market and Trade finder filters and fallbacks |
| `tests/test_app_page_book_pnl.py` | 13 | 8 s | 320 MB | Trade book and P&L selectors, reconciliation, missing files |
| `tests/test_app_page_risk.py` | 10 | 8 s | 270 MB | Risk pack tabs against their tables, missing files |
| `tests/test_app_page_research_deliverables.py` | 13 | 11 s | 390 MB | Sentiment, Reports & docs, Data & assumptions |

`tests/test_app_pages.py` in detail:

- every file in `app/views/` under `AppTest.from_file(...).run()`: no exception, SIM banner shown, a title;
- the entrypoint: navigation, the default page and the sidebar footer (SIM label, reconciliation status, commit);
- the Overview's headline metric equals the canonical fact and sits with its band and its sign-robustness statement;
- the partial fact path equals the canonical one on the local copy;
- missing data: with `data.ROOT` pointed at an empty directory (every file missing), at a symlinked copy without the
  public export's omissions, and at a copy without the band table, the Overview raises nothing, shows `st.info`
  messages and withholds the headline when its band is missing;
- the doc sections quoted by `what_it_tells`, the link rewriting and escaping, and the spec index.

On this machine run the app tests one file at a time, never with the full suite:

```sh
for f in tests/test_app_pages.py tests/test_app_contract.py tests/test_app_page_*.py; do
  DESK_OFFLINE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_CONCURRENT_THREADS=1 \
    .venv/bin/python -m pytest -q -p no:cacheprovider "$f"
done
```

Add `-k <page stem>` (for example `-k overview`) to run a single page's tests.

## 7. Limitations

- AppTest checks the element tree, not the browser rendering. The Overview was checked by eye at desktop and phone
  widths; the other pages at desktop width (about 1440 px) only, and four of the parity tabs only in code. Phone width
  is unchecked for eight pages. At a medium width (an 800 px window with the sidebar open) rows of five or six KPI
  tiles cut their values short ("USD 3,…", "₹…" on the Market and Trade book pages); hovering does not reveal them.
  Widen the window or collapse the sidebar.
- Links between pages work inside the navigation. A page run on its own shows their titles as plain text.
- Prose quoted verbatim from `docs/30_mtm_attribution.md` and `docs/31_adverse_events.md` (their "What this does and
  doesn't tell you" sections, quoted on the Overview, P&L and Data & assumptions pages) mentions the ₹192.1 m book P&L
  in a liquidity sentence without the band. The contract keeps quotes verbatim, so the app does not edit them; the
  pages that quote them show the headline component, except Data & assumptions.
- Importing `desk.reporting.one_pager` for `headline_facts()` also imports matplotlib and reportlab (about 95 MB of
  RSS), because the one-pager module renders PDFs. That is the price of reusing the canonical fact code instead of
  re-deriving it.
- The Data & assumptions page imports `tools/export_public.py` for its raw-cache classifier only (no export runs); if
  the import fails the page skips that breakdown.
- `mc_pnl_distribution.csv` holds only the base variant's paths, so the MCX-basis Monte Carlo variant is shown by its
  summary figures, not a second histogram. The book's daily path without its MCX hedge is not published as a CSV;
  E1 shows the pipeline's PNG for it.
- `reports.py` and `data_assumptions.py` each carry their own section splitter and doc viewer; they could move into
  `app/lib/docs_text.py`.
- The cache is keyed on file modification times: a pipeline re-run is picked up on the next rerun, but a server
  started before the outputs existed keeps showing "Not in this copy" for files that are still absent.
- The partial fact path mirrors the interview pack's source list (`data._PARTIAL_SOURCES`). If a reporting module
  starts reading a new file, the partial path reports that part as not computed, and the equality test fails on the
  full copy until the list is updated.
- The Excel workbook is offered as a download only; the app never opens it.

## 8. Deploying to Streamlit Community Cloud

Nothing has been deployed. Settle the open decisions in `PUBLISHING.md` §3 (owner-only, not in the public copy) first: whether to
publish the derived LME price series (i) and the verbatim headline titles (ii). A public app republishes whatever
the public repository holds, and it is reachable by anyone with the link.

1. Build the strict export: `.venv/bin/python tools/export_public.py --profile strict`. The export keeps code files,
   so `app/`, `.streamlit/config.toml` and `requirements.txt` are in `dist/public/`. Check that they are.
2. Create the public repository from `dist/public/` as PUBLISHING.md describes. Never deploy from this local
   repository, whose history holds the raw caches.
3. On share.streamlit.io choose **Create app**, then the public repository and branch, main file path
   `app/streamlit_app.py`, and Python 3.12 under advanced settings. No secrets are needed.
4. Optionally set the environment variable `DESK_APP_REPO_URL` to the repository's `blob/<branch>` URL.
5. Do not pass `--server.address localhost` there; the platform runs the server. Expect "Not in this copy" notes where
   a page would read the files the export leaves out. The Overview keeps its headline and band on the partial path.
