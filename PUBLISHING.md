# Publishing the desk to GitHub: owner's checklist

> **ACADEMIC SIMULATION — not actual trades.** This page is for you, the repository owner. The strict export leaves
> it out of the public copy. Nothing in it has been done for you: no repository has been created and nothing has
> been uploaded. It is not legal advice.

**Why a separate copy is needed.** `data/raw/` in this repository (about 96 MB) caches every downloaded source. Most
of that is other people's copyrighted pages (news articles, Google News RSS results, archived Drewry pages, an
industry report) or restricted market data (LME official prices via Westmetall, MCX prices via a mirror site). All
of it is also in the git history. So:

- **Never push this local repository, or its history, to a public remote.**
- Publish a **fresh repository created from `dist/public/`**, which `tools/export_public.py` builds from the working
  tree. The local repository stays exactly as it is.

## Step 1. Build the export

Finish and commit your local work first, so the public copy matches a known commit. The export records the commit
and counts any uncommitted changes. Then run:

```sh
cd /Users/sujaljindal/Desktop/ujjwal
DESK_OFFLINE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_CONCURRENT_THREADS=1 \
  .venv/bin/python tools/export_public.py --profile strict
```

- The export takes a couple of seconds, copies files, and runs no pipeline stage.
- It prints a summary: files and bytes excluded by category, broken links, and possible personal data.
- The full detail is written to `dist/strict_export_report.json`, outside the public copy.
- `--profile full-local` builds `dist/full-local/`, a private backup that still holds every cache. **Never publish
  it.**
- `dist/` is gitignored.

To change a classification, edit `tools/public_export_policy.yaml` (for example, add `export: false` to an entry)
and re-run. A raw file that matches no entry is excluded automatically.

## Step 2. Read `dist/public/DATA_NOTICE.md`

The notice is written into the public copy and is meant to be published with it. It lists:

- every source category, with its reason and certainty;
- the derived data files that were left out;
- how anyone can rebuild the data from the kept manifest (URL, retrieval date, sha256);
- the tables, workbook sheets, charts and documents that **still carry derived third-party data points**.

Read it before making the decisions below.

## Step 3. Make the open decisions

The counts below are from the export run on 2026-09-16. Re-read them in DATA_NOTICE after re-exporting.

### (i) Publish the derived LME price series at all?

LME official prices belong to the London Metal Exchange. Redistributing them normally requires an LME market-data
licence, and Westmetall's pages carry their own terms. The strict export drops the raw pages and
`data/processed/lme_daily.csv` / `market_daily.csv`. It **keeps** the results that show LME levels:

- 22 tables with LME data, as price levels or returns (in `mc_*` tables the returns are simulated shocks); the
  current list is `outputs_carriers` in `dist/strict_export_report.json`, rewritten on every export;
- 6 sheets of `Metals_Desk_Master.xlsx` (Market_Daily holds the full daily series);
- 11 charts;
- 2 tables and 1 workbook sheet with MCX closes from the third-party mirror.

The options:

| Option | What it means | Trade-off |
|---|---|---|
| a. Publish as exported | Keep everything, with the attribution "LME official prices, as republished by Westmetall" and the notice | Least work. Carries the unresolved licensing question for a few thousand historical daily prices. |
| b. Check terms or ask first | Read the LME and Westmetall terms on historical, non-commercial or academic use, or ask them, then choose a or c | Slower, but it turns an assumption into an answer. |
| c. Publish without the series | Leave out the workbook's market sheets and the tables and charts listed in DATA_NOTICE §5, or regenerate them without price columns | Needs code changes (the pipeline writes those columns, and README and tests link to some of the files). Weakens the "every number traces" story unless the rebuild path is clear. |

### (ii) Keep verbatim headline titles?

Google News RSS feeds say they are for personal, non-commercial feed-reader use. The titles are the publishers'
text. The strict export drops the raw feeds, `data/processed/headlines_weekly.csv` and the audit file, but keeps:

- all 649 scored titles in `outputs/tables/sentiment_headlines_scored.csv`, plus a 218-row subset in
  `sentiment_week_extremes.csv`;
- 20 titles quoted in `docs/70_sentiment_overlay.md` and 12 in `docs/research/news_notes.md`;
- one title in each of five desk notes, and a few in `tests/` and `desk/sentiment/fetch_news.py`.

A related item: **72 verbatim sentences from AlCircle articles** are embedded in `desk/data/fetch_price_evidence.py`
as extraction anchors.

The options:

- (a) Keep as is. The titles are short, dated and linked. Whether a headline is protected, and whether the feed terms
  bind a republisher, is uncertain.
- (b) Keep only the handful quoted with attribution in notes and docs. Replace the table's `title` column with its
  link, a hash and the scores, so the sentiment result stays checkable by re-fetching.
- (c) Also shorten the AlCircle anchor sentences to the minimum needed to locate each number.

Options (b) and (c) change Phase 7 and Phase 0 code and tests.

### (iii) Which licence?

No licence has been added. Without one, the default is "all rights reserved": people can read the repository but
not legally reuse it. Choose deliberately:

- **MIT.** Short and permissive, and the one most readers already know. It has no explicit patent grant.
- **Apache-2.0.** Permissive, with an explicit patent grant and a NOTICE convention. Slightly heavier.
- **CC-BY-4.0 for docs, reports and charts.** Suits prose and figures. Do not use a Creative Commons licence for the
  code. A common split is MIT or Apache-2.0 for code, and CC-BY-4.0 for `docs/` and `outputs/reports/`. If you split,
  state which paths each licence covers.
- **Whichever you choose, it covers only what you own.** It cannot licence LME-derived values, headline titles, or
  the kept government files (CBIC, USGS, ECB, OECD, TradeStat, PIB). Say so in the README next to the licence, and
  keep the attributions in DATA_NOTICE §6.
- **Before licensing `docs/spec/MASTER_SPEC_V3.md`, confirm its source.** It is a transcription of a spec PDF, so
  check you wrote it or may publish it.

### (iv) Smaller calls

- **Uncertain category-A caches, kept by default.** These are the TradeStat result pages (96 files, 10.2 MB), the PIB
  press-release page, the OECD CSV and the Internet Archive CDX listings. To drop one, set `export: false` on its
  policy entry.
- **Personal data.** Your macOS home path, which includes your username, appears in six docs (a `cd /Users/...` line
  in `docs/31_adverse_events.md`, `40_var_garch.md`, `41_monte_carlo.md`, `50_credit_scoring.md`,
  `51_margin_liquidity.md` and `70_sentiment_overlay.md`) and 39 times in `docs/reviews/phase1-3_review_findings.json`.
  Fix these in the local repository (use repo-relative paths) and re-export, or accept them. No email address was
  found in the exported text files, and a byte scan of the PDFs, the workbook and the PNGs found no username or home
  path. Your new commits will carry your git name and email. To avoid exposing the email, set
  `git config user.email <id>+<username>@users.noreply.github.com` in the new repository.
- **README and INDEX consistency (not edited).**
  - No README link points to an excluded file.
  - The README pipeline diagram names `market_daily.csv`, which the export leaves out.
  - "How to re-run it" says `DESK_OFFLINE=1` rebuilds from the caches. In the public copy, Phase 0 must first be run
    online (DATA_NOTICE §4). A one-line pointer to DATA_NOTICE would fix that.
  - `docs/INDEX.md` line 87 links to `data/processed/headlines_weekly.csv`, which is excluded. That link will be broken
    on GitHub, and the INDEX link check in `tests/test_reports_runner.py` would fail in the public copy until Phase 0
    is rebuilt.

## Step 4. Check the honesty items before pushing

Confirm each of these in the public copy:

- **Every report, chart and workbook carries "ACADEMIC SIMULATION — not actual trades".** To list any report or doc
  that lacks it (no output means none), run this in the public copy:

  ```sh
  grep -rL "ACADEMIC SIMULATION" outputs/reports/*.md docs/*.md README.md
  ```

- **Every counterparty and vessel ends in "(SIM)".**
- **The headline book P&L is never quoted without its band.** To print the band, run:

  ```sh
  python3 -c "import csv; r=[x for x in csv.DictReader(open('outputs/tables/pnl_sensitivity_sign_robustness.csv')) if x['family']=='anchor_premium'][0]; print(r['base_pnl_inr'], r['pnl_min_inr'], r['pnl_max_inr'], 'sign_robust=', r['sign_robust_within_band'])"
  ```

  On 2026-09-16 this showed:
  - ₹192.1 m at the 31-Oct-2022 horizon;
  - a band of −₹105.4 m to +₹334.3 m across the registered `domestic_anchor_premium_inr_t` grid;
  - not sign-robust.

  Any new text (the GitHub description, a pinned-repo blurb, a LinkedIn post) must carry the band too.
- **Nothing labelled PROXY, ASSUMPTION or (SIM) is described as real** in the repository description or topics.

## Step 5. Size check

- The strict export is about 63 MB across 505 files (current figures: `dist/strict_export_report.json`). The largest file is
  `data/raw/regulatory/cbic_notifications/cs50-2017_principal.pdf` (13.4 MB), followed by `outputs/tables/mtm_daily.csv`
  (4.4 MB).
- GitHub blocks files over 100 MB and warns above 50 MB, so no Git LFS is needed.
- To slim the repository, the CBIC principal notification is the obvious candidate. Its manifest entry has no URL, so
  if you drop it, the source is described in `config/params/regulatory.yaml`.

## Step 6. Create a fresh repository from the export

Copy the export **outside** this repository, so no git command can reach the local history:

```sh
cd /Users/sujaljindal/Desktop/ujjwal
rsync -a --delete dist/public/ ~/Desktop/metals-desk-public/
cd ~/Desktop/metals-desk-public
git init -b main
git add -A
git status --short | head -50                          # review what will be committed

# expect NO output from the next two commands (category B/C caches and the derived files left out)
find data/raw -type f | grep -E "westmetall_|mcx_thirdparty/|\.xml$|freight/articles/|drewry_wci_[0-9]*\.html|alcircle/|/isri/|/cmr/|/banks/|sbi_mclr|argus_|tribune_|elplaw_"
ls data/processed data/interim/news 2>/dev/null | grep -E "lme_daily|market_daily|headlines_weekly|freight_weekly|_audit_headlines"

grep -rIl "/Users/" . --exclude-dir=.git               # personal paths still present? (see decision iv)
du -sh . .git                                          # total size, and the part that is git objects
git commit -m "Initial public release"
```

Then:

1. On GitHub, create an **empty private** repository, without a README, licence or .gitignore, so the first push is
   clean.
2. Add it as a remote and push:
   `git remote add origin git@github.com:<you>/<repo>.git && git push -u origin main`.
3. Review the repository on GitHub as a stranger would: README rendering, charts, DATA_NOTICE and links. Only then
   switch it to **public**.

## Step 7. Later updates

Re-run the export after local changes, sync it into the public folder without touching its `.git`, and commit there:

```sh
cd /Users/sujaljindal/Desktop/ujjwal && DESK_OFFLINE=1 .venv/bin/python tools/export_public.py --profile strict
rsync -a --delete --exclude .git dist/public/ ~/Desktop/metals-desk-public/
```

If a third-party file ever reaches a public commit, deleting it in a later commit does not remove it from history.
You would need to rewrite the history (for example with `git filter-repo`), force-push, and ask GitHub support to
purge cached views. Forks keep their own copies. That is why the checks in Step 6 run before the first push.
