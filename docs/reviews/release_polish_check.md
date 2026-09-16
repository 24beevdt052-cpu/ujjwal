# Release-polish check (final verifier, read-only)

ACADEMIC SIMULATION — not actual trades. Checked 2026-09-17 on the working tree (commit 3dab8f4 with 70 uncommitted changes). Scratch work is in `/private/tmp/release_check/`. Nothing was committed or published. Hashes of 194 output and doc files were the same before and after the test runs.

| # | Check | Result | Evidence |
|---|---|---|---|
| 1a | One-pager: 1 page, professional, no clipped text, ₹ renders, SIM label | PASS | PDFKit render at 2× and 3.5×: 1 A4 page, nothing clipped, ₹ and − render correctly; the SIM label appears in the callout, the footer and both chart footers. |
| 1b | Headline P&L quoted with its band | PASS | ₹192.1 m at 31-Oct-2022, with "−₹105.4 m to +₹334.3 m … not sign-robust" in the next row and as a red bar on the chart. Both match `pnl_sensitivity_sign_robustness.csv` (192,054,771 / −105,380,780 / 334,306,556; break-even −38,702.3). |
| 1c | Spot-check of 8+ numbers against CSVs | PASS | Recomputed and matching: ₹195.9 m at 31-Aug; T02 +₹50.55 m (worst case +₹10.65 m, the only positive minimum); T01 +₹64.28 m / −₹28.93 m; T08 −₹11.73 m; buckets +₹165.2 m / +₹103.3 m / −₹56.6 m / −₹30.0 m / +₹10.0 m, 86 % deal margin; VaR means ₹4.27 m and ₹3.98 m, max ₹43.5 m on 9-Mar; 7 and 5 exceptions, Kupiec 2–11; MC 99 % ₹76.3 m, ₹23.0 m, basis ₹32.8 m; funding ₹1,179.0 m, 19 days; LC ₹1,414.8 m, 17 days; IM ₹95.8 m; RJK PD 41.8 % D; 649 headlines over 28 weeks. |
| 1d | Excel reconciliation line is computed, not hard-coded | PASS | `reconciliation_status.status()` gives VERIFIED; an independent SHA-256 of the workbook (195bbca5…, 1,096,224 B) matches the record. `one_pager.py` contains no "132,447" literal, and `_recon_clause` with a NOT_RUN status leaves out every figure. Caveat: the record's hash was backfilled from git evidence rather than written by the slow run itself (see decision 2). |
| 2 | Visual QA fixes hold (5+ items re-rendered or inspected) | PASS | Interview pack still 4 pp, with Q4 entirely on p2 and Q9 plus its sources on p3. Memo: 1 page, "Counterparty" no longer broken. Post-mortem p2: lessons numbered "1."–"5.", chart footers wrapped. `p3_equity_curve`: band subtitle −₹10.54 to +₹33.43 crore, legend clear of the lines. `p1_sensitivity_lme_fx`: separate colour bar, true minus signs. `p1_window_heatmap`: footer clear of the tick labels. |
| 3 | Fresh-build fix (P6 with no reconciliation record) | **FAIL** | Both test files pass (7 and 26). But `run_all.py --only P6` in a copy with no record still **exits 1**: the pack step prints NOT_RUN, then `one_pager.main()` raises `ValueError: … rendered 2`. The status sentence pushes the two-column block onto a second page. Scratch renders show the same for STALE and FAILED, and no test renders the one-pager for any status other than VERIFIED. |
| 4a | Strict export runs into `dist/public` | PASS | Exit 0 in 1.8 s, 61 MB RSS. Kept 504 files (63.1 MB), excluded 528 (61.5 MB). |
| 4b | No category B/C raw files in the export | PASS | An independent first-match classifier over all 687 repo raw files found 0 B/C/unclassified files among the 171 exported (167 A, 4 META). `market_daily`, `lme_daily`, `headlines_weekly`, `freight_weekly` and the MCX mirror are absent. |
| 4c | DATA_NOTICE.md and PUBLISHING.md exist and state the open decisions | PASS | `dist/public/DATA_NOTICE.md` (sections 1–7). `PUBLISHING.md` sits at the repo root and is left out of the export by policy; Step 3 (i)–(iv) covers LME series, headlines, licence and the smaller calls. Its counts (20 tables, 498 files) are older than today's run (22 tables, 504 files). |
| 4d | README links inside the export that point to excluded files | PASS (none) | No README markdown link targets an excluded file. The README diagram (line 123) names the excluded `market_daily.csv`, and `docs/INDEX.md:87` links to the excluded `data/processed/headlines_weekly.csv` (broken in the export). |
| 5 | Fast tests, one file at a time (default mode) | PASS | test_one_pager 13, test_desk_notes 23, test_post_mortem 11, test_risk_liquidity 20, test_reports_runner 26, test_fresh_build 7, test_excel_reconciliation 6 passed + 4 slow skipped. Peak RSS 211 MB or less. |

## Blocking before publishing

- **Fresh-build P6 crash is back, now in the one-pager.** When the status is not VERIFIED, `_recon_clause` adds the full `st.reason`, and the page overflows. Fix: shorten that clause (status plus a pointer to docs/35 §7), then add a test that renders all three non-VERIFIED statuses and checks the result is 1 page. The same clause ends in a double period ("…on this build..").

## Decisions for the owner

1. Who fixes the one-pager overflow above, and whether to re-run the fresh-clone P6 check after the fix.
2. Run `DESK_OFFLINE=1 DESK_RUN_SLOW=1 .venv/bin/python -m pytest -q tests/test_excel_reconciliation.py` on its own (~2.8 GB), so that VERIFIED rests on a hash written by the run. The alternative is to accept the git-evidence backfill, which the record discloses and the one-pager does not. If `sheet_readme.py` gets `DESK_RUN_SLOW=1` added, do that first: it changes the workbook bytes.
3. LME-derived prices still in `outputs/` (22 tables, 6 workbook sheets, 11 charts, plus the MCX mirror): publish as is, check LME/Westmetall terms first, or strip them.
4. The 649 verbatim headline titles (`sentiment_headlines_scored.csv`, docs, desk notes), and the 72 AlCircle sentences in `desk/data/fetch_price_evidence.py`.
5. Licence (none added), and confirm the right to publish `docs/spec/MASTER_SPEC_V3.md`.
6. The uncertain category-A caches: TradeStat (96 files, 10.2 MB), PIB, OECD, Internet Archive CDX listings.
7. The home path and username in 6 docs and 39 times in `docs/reviews/phase1-3_review_findings.json`.
8. Public-copy wording. `docs/INDEX.md:87` has a broken link. The README diagram names `market_daily.csv`. README line 193 and the one-pager's "Built with" say `DESK_OFFLINE=1` rebuilds from cached raw data, which does not hold in the export until Phase 0 is fetched online. `docs/INDEX.md` does not list the one-pager.
9. Earlier agents' open calls: keep the stricter STALE-fails default test; the memo stop-loss wording ("the book its stop from 1-Aug"); the band on the two README charts; the white space on pack pp 1–2; stubbing `SUMMARY_STEP` in the runner step-order test.
10. Commit the 70 working-tree changes, then re-export (today's export snapshot records uncommitted changes).
