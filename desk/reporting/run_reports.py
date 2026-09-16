"""Stage P6 — the recruiter-facing reporting pack, in order (MASTER_SPEC Table 7 rows 5.1, 5.3, 5.4; Table 8 row 6).

    DESK_OFFLINE=1 .venv/bin/python run_all.py --only P6

Runs, in this order:

1. `desk.reporting.desk_notes.main`      the six weekly desk notes (row 5.1)
2. `desk.reporting.post_mortem.main`     the two-page post-mortem on the best trade (row 5.3)
3. `desk.reporting.interview_pack.main`  the 17-question interview pack (Table 8 row 6); it re-tests a claim against
                                         the post-mortem, so it runs after it
4. `refresh_readme()`                    regenerates the number blocks in the root README.md (row 5.4)
5. `desk.reporting.one_pager.main`       the one-page recruiter summary linked from the top of the README; last, so
                                         it is built from the same tables the pack and README were just refreshed from

The one-page risk policy memo (Table 6 row 4.6) is written by `desk.risk.run_liquidity`, not here.

Design choices worth knowing
----------------------------
* **Fail before doing anything.** Every step's module is imported before the first one runs, so a missing module
  (the desk notes are built by a separate workstream) stops the stage with a message naming it, instead of
  half-refreshing the pack. The one-page summary (`SUMMARY_STEP`) is imported up front too.
* **README numbers are generated, the prose is not.** README.md is hand-written, but every number in it sits inside
  a `<!-- BEGIN GENERATED: name -->` … `<!-- END GENERATED: name -->` block that `refresh_readme()` rewrites from the
  published tables (through the interview pack's own loaders, so the two can never disagree).
  `tests/test_reports_runner.py` fails if a block is stale, so a re-run upstream phase cannot leave the README
  quoting old numbers.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Mapping
from types import ModuleType

import pandas as pd

from desk import HORIZON_END, WINDOW_END
from desk.paths import ROOT, TABLES_DIR

README_PATH = ROOT / "README.md"
STEPS: tuple[tuple[str, str], ...] = (
    ("weekly desk notes", "desk.reporting.desk_notes"),
    ("deal post-mortem", "desk.reporting.post_mortem"),
    ("interview pack", "desk.reporting.interview_pack"),
)
SUMMARY_STEP: tuple[str, str] = ("one-page summary", "desk.reporting.one_pager")   # runs after refresh_readme()
BLOCK_NAMES = ("headline", "provenance", "verification", "caveats")
_BLOCK = re.compile(r"(<!-- BEGIN GENERATED: (?P<name>[a-z_]+) [^>]*-->\n)(?P<body>.*?)(<!-- END GENERATED: (?P=name) -->)",
                    re.S)


class MissingStageError(RuntimeError):
    """A reporting step's module does not exist yet."""


def load_step(module: str) -> ModuleType:
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as e:
        if e.name == module:
            raise MissingStageError(
                f"{module} is not built yet — the P6 reporting stage needs it before it can run. Build that module "
                f"(it must expose main()), or run the other steps directly, e.g. "
                f"`python -c \"import desk.reporting.post_mortem as m; m.main()\"`."
            ) from e
        raise
    if not callable(getattr(mod, "main", None)):
        raise MissingStageError(f"{module} exists but has no main()")
    return mod


def main() -> None:
    modules = [(label, load_step(name)) for label, name in STEPS]
    summary = load_step(SUMMARY_STEP[1])
    for label, mod in modules:
        print(f"[P6  ] {label}")
        mod.main()
    changed = refresh_readme()
    print(f"[P6  ] README generated blocks {'updated' if changed else 'already current'}")
    print(f"[P6  ] {SUMMARY_STEP[0]}")
    summary.main()


# ------------------------------------------------------------------------------------------------ README blocks
def _t(name: str) -> str:
    return f"[`{name}`](outputs/tables/{name})"


def _verdicts(bw: pd.DataFrame) -> str:
    g, h = str(bw.loc["garch", "verdict"]).lower(), str(bw.loc["hist250", "verdict"]).lower()
    return f"{g} for both" if g == h else f"{g} (GARCH), {h} (window)"


def render_readme_blocks(src: Mapping | None = None) -> dict[str, str]:
    """The README's generated blocks, rendered from the same raw facts the interview pack uses."""
    from desk.reporting import interview_pack as ip

    src = src if src is not None else ip.load_sources()
    r = ip.compute_raw(src)
    f = ip.format_facts(r)
    NB, m = ip.NB, ip.inr_m

    book = src["book"]
    elig = pd.read_csv(TABLES_DIR / "trade_eligibility_check.csv", usecols=["trade_id", "status"])
    pricing = pd.read_csv(TABLES_DIR / "pnl_sensitivity_pricing.csv", usecols=["case", "trade_id", "cum_pnl_horizon_inr"])
    reprice = pricing[(pricing["case"] != "base") & (pricing["trade_id"] != "BOOK")]
    robust_ids = sorted(t for t, g in reprice.groupby("trade_id") if (g["cum_pnl_horizon_inr"] > 0).all())
    tp = r["trade_pnl"]
    best_id = str(tp.idxmax())
    mc = src["mc"]
    ath_var99 = float(ip._one(mc, snapshot_id=ip.MC_SNAP_ATH, variant="normal_window")["var99_inr"])
    kp = src["kupiec"]
    bw = kp[kp["sample"] == "book_window"].set_index("method")
    var = src["var"]
    hist_mean = ip._f(ip._metric(var, "var_mean_hist250", "book_window"))
    bk = r["buckets"]
    controls = src["controls"]
    mc_controls = pd.read_csv(TABLES_DIR / "mc_controls.csv")
    liq_controls = pd.read_csv(TABLES_DIR / "margin_liquidity_controls.csv", usecols=["status"])
    n_resid_days = int((src["att"]["trade_id"] != "BOOK").sum())
    liq_sum = src["liq"].set_index(["metric", "scope"])["value"]
    lc_ex_tol = float(liq_sum.loc[("memo_lc_outstanding_ex_tolerance_inr_max", "book")])
    lc_ex_tol_days = int(float(liq_sum.loc[("memo_days_lc_limit_breach_ex_tolerance", "book")]))
    first_td, last_td = book["trade_date"].min(), book["trade_date"].max()

    headline = "\n".join([
        "| Result | Value | Source |",
        "|---|---|---|",
        f"| The book | {f['n_trades']} tickets, {f['book_mt']}{NB}MT in {f['book_boxes']} containers, traded "
        f"{ip.day(first_td, True)} to {ip.day(last_td, True)} | {_t('trade_book.csv')} |",
        f"| Book P&L to the horizon ({ip.day(HORIZON_END, True)}) | **{f['book_pnl']}** ({f['book_pnl_mt']}/MT); "
        f"{f['book_pnl_we']} at the window end ({ip.day(WINDOW_END, True)}) | {_t('attribution_daily.csv')} |",
        f"| **…read only with its band** | **{f['band_lo']} to {f['band_hi']}** across the registered "
        f"`{ip.ANCHOR_KEY}` grid; break-even {f['band_be']}{NB}₹/MT inside the grid — **not sign-robust** | "
        f"{_t('pnl_sensitivity_sign_robustness.csv')} |",
        f"| Where it came from (lifetime, ₹{NB}m) | deal margin {m(bk['new_deal'], sign=True)}, grade spread "
        f"{m(bk['grade_spread'], sign=True)}, FX {m(bk['fx'], sign=True)}, freight {m(bk['freight'], sign=True)}, "
        f"LME flat price {m(bk['lme_flat'], sign=True)}, events {m(bk['demurrage_penalty'], sign=True)}, carry and "
        f"roll {m(bk['roll_term_structure'], sign=True)}, LME–MCX basis {m(bk['cross_exchange_basis'])} (proxy, by "
        f"construction); residual {f['q9_residual']} | {_t('attribution_daily.csv')} |",
        f"| Tickets | largest {best_id} {m(float(tp[best_id]), sign=True)}; worst {f['worst_tid']} {f['q10_pnl']}; "
        f"positive in every registered re-pricing case: {', '.join(robust_ids) or 'none'} (the post-mortem's "
        f"subject) | {_t('pnl_sensitivity_pricing.csv')} |",
        f"| Trade discipline | {f['q1_n_elig']} of {f['q1_n_cases']} in-window parity cases eligible under the ex-ante "
        f"rule ({f['q1_n_open']} open on the base screen alone); {int((elig['status'] == 'PASS').sum())} of "
        f"{len(elig)} tickets pass it | {_t('parity_weekly.csv')}, {_t('trade_eligibility_check.csv')} |",
        f"| Daily 95{NB}% VaR, {f['q16_n']} position days | mean GARCH {f['q6_var_base']} against "
        f"{m(hist_mean, 2)} on the {f['q16_window']}-day window; exceptions {f['q16_exc_g']} and {f['q16_exc_h']} "
        f"({f['q16_exp']} expected), Kupiec {_verdicts(bw)} | {_t('var_summary.csv')}, "
        f"{_t('kupiec.csv')} |",
        f"| Monte Carlo 99{NB}% {f['mc_h']}-day VaR, {f['n_paths']} paths | {m(ath_var99)} ({f['ath1_date']}), "
        f"{f['q6_apr_base']} ({f['apr_date']}), {f['q6_jul_base']} ({f['jul_date']}); with an MCX basis factor "
        f"{f['q6_apr_basis']} and {f['q6_jul_basis']} on the last two | {_t('mc_summary.csv')} |",
        f"| Riskiest buyer (synthetic-data model) | {f['rjk_id']}: PD {f['q11_pd']}, band {f['q11_band']}; advances "
        f"up to {ip.mult(max(r['q11_adv']))} its line, contracted exposure {f['q11_contracted']} | "
        f"{_t('credit_scores.csv')} |",
        f"| Liquidity | funding need peaked at {f['q4_funding_peak']} ({f['q4_funding_date']}) against a "
        f"{f['q4_wc_limit']} line sized ex ante on the plan's average balance: {f['q4_fb_days']} days over (none at "
        f"{f['q15_wc_step']}, one {f['q15_step']} step higher); peak MCX initial margin {f['q12_im']} | "
        f"{_t('margin_liquidity_summary.csv')} |",
        f"| Sentiment overlay | {f['q14_n_headlines']} real headlines over {f['q17_n_weeks']} weeks; {f['q17_n_sig']} "
        f"of {f['q17_n_lead']} lead tests significant — no evidence that headline tone led LME; the March spike could "
        f"not be tested, and {f['q17_n_weeks']} weeks can only rule out a strong lead | "
        f"{_t('sentiment_summary.csv')} |",
    ])

    provenance = "\n".join([
        "| Count | DIRECT | PROXY | ASSUMPTION | Total |",
        "|---|--:|--:|--:|--:|",
        f"| Parameters in `config/params/*.yaml` | {r['q14_n_direct']} | {r['q14_n_proxy']} | {r['q14_n_assump']} | "
        f"{r['q14_n_params']} |",
        f"| Columns of the daily market panel ([`series_provenance.csv`](data/processed/series_provenance.csv)) | "
        f"{r['q14_sp_direct']} | {r['q14_sp_proxy']} | {r['q14_sp_assump']} | {r['q14_sp_n']} |",
        "",
        f"Verification status of the {r['q14_n_params']} parameters: **{r['q14_n_verified']} VERIFIED**, "
        f"{r['q14_n_partial']} PARTIAL, **{r['q14_n_pending']} PENDING** (each with its next step), and "
        f"{r['q14_n_na']} N/A (desk policy, model design or scenario choices that no public source can verify).",
    ])

    n_ctrl = len(controls)
    n_ctrl_pass = int((controls["status"] == "PASS").sum())
    n_ctrl_bad = int((~controls["status"].isin(["PASS", "INFO"])).sum())
    mc_status = mc_controls["status"] if "status" in mc_controls.columns else pd.Series(dtype=str)
    verification = "\n".join([
        f"- [x] **Attribution closes.** Largest |residual| across {n_resid_days:,} trade-day rows: {f['q9_residual']} "
        f"(tolerance ₹1). Phase 3 controls: {n_ctrl_pass} of {n_ctrl} PASS, {n_ctrl_bad} failing, the rest INFO "
        f"({_t('pnl_controls.csv')}).",
        ip.readme_recon_item(src["recon"]),     # ticked only when the record is VERIFIED against the workbook
        f"- [x] **Eligibility rule declared ex ante** (CONTRACTS §5a, before any Phase 1 result): "
        f"{int((elig['status'] == 'PASS').sum())} of {len(elig)} tickets pass ({_t('trade_eligibility_check.csv')}).",
        f"- [x] **Risk numbers tie to P&L.** Monte Carlo controls: {int((mc_status == 'PASS').sum())} of "
        f"{len(mc_status)} PASS ({_t('mc_controls.csv')}); liquidity controls: "
        f"{int((liq_controls['status'] == 'PASS').sum())} of {len(liq_controls)} PASS "
        f"({_t('margin_liquidity_controls.csv')}).",
    ])

    caveats = "\n".join([
        f"1. **The headline is an assumption, not a result.** {f['q9_nd_share']} of lifetime P&L is deal margin from "
        f"the desk's own sale-pricing rule on `{ip.ANCHOR_KEY}` (PENDING verification); the band is "
        f"{f['band_lo']} to {f['band_hi']}.",
        f"2. **The grade path is hindsight.** Re-priced on the point-in-time grade mix the book makes "
        f"{f['q2_pit_pnl']}, and grade spread turns {f['q2_pit_grade']}.",
        f"3. **MCX is a proxy with unit beta by construction.** A third-party mirror gives beta {f['q6_beta_w']} on "
        f"weekly closes (t {f['q6_beta_w_t']} against one); its daily {f['q6_beta']} is biased down by MCX's evening "
        f"close and is the pessimistic end, not a hedge ratio. Mean daily GARCH VaR is {f['q6_var_base']} on the "
        f"proxy, {f['q6_var_beta_w']} at the weekly beta and {f['q6_var_beta']} at the daily one; a basis factor "
        f"raises Monte Carlo 99{NB}% VaR from {f['q6_jul_base']} to {f['q6_jul_basis']} on {f['jul_date']}. Basis "
        "risk is under-represented in every base number.",
        f"4. **Freight is one factor and reconstructed.** The Gulf lane is {f['q3_ratio']} × the US lane every week, "
        "and lane levels are hindsight-calibrated.",
        f"5. **The book did not fit its own bank lines — on two stated conventions.** Funding need "
        f"{f['q4_funding_peak']} against a {f['q4_wc_limit']} line sized ex ante on the plan's *average* balance "
        f"({f['q4_fb_days']} days over); one more {f['q15_step']} step ({f['q15_wc_step']}) and the line is never "
        f"breached. LCs outstanding {f['q4_lc_peak']} against {f['q4_lc_limit']} ({f['q4_lc_days']} days over), "
        f"counted at face plus the LC tolerance; without the tolerance {m(lc_ex_tol)} and {lc_ex_tol_days} days. "
        "The lesson is to stress the plan's peak, not its average — a bank sanctions before the book exists.",
        f"6. **GARCH did not win its declared lead test.** The {f['q16_window']}-day window crossed its alert level "
        f"{f['q16_lead']} trading days before GARCH into March; into the crash fortnight GARCH sat below both windows.",
        f"7. **Credit scores are illustrative.** The logistic model is fitted on {f['q11_n_synth']} synthetic "
        "buyer-quarters, and the buyer profiles were written by the same author as the book.",
        f"8. **Stresses outside the distribution are hypothetical.** No BIS QCO applied to scrap in {f['window_year']}; the QCO "
        f"stress (a {f['q13_apr']} loss on {f['apr_date']}) and the freight {f['q3_shock']} spike are labelled "
        "HYPOTHETICAL.",
    ])
    return {"headline": headline, "provenance": provenance, "verification": verification, "caveats": caveats}


def apply_blocks(text: str, blocks: Mapping[str, str]) -> str:
    """Replace every generated block body in `text`; raise if a block marker is missing or duplicated."""
    for name in BLOCK_NAMES:
        n = len([mm for mm in _BLOCK.finditer(text) if mm.group("name") == name])
        if n != 1:
            raise ValueError(f"README.md must contain exactly one GENERATED block named {name!r}; found {n}")

    def _sub(mm: re.Match) -> str:
        name = mm.group("name")
        if name not in blocks:
            return mm.group(0)
        return f"{mm.group(1)}{blocks[name].rstrip()}\n{mm.group(4)}"

    return _BLOCK.sub(_sub, text)


def readme_block_bodies(text: str) -> dict[str, str]:
    return {mm.group("name"): mm.group("body").rstrip("\n") for mm in _BLOCK.finditer(text)}


def refresh_readme(src: Mapping | None = None) -> bool:
    """Rewrite the generated blocks in README.md. Returns True if the file changed."""
    old = README_PATH.read_text(encoding="utf-8")
    new = apply_blocks(old, render_readme_blocks(src))
    if new != old:
        README_PATH.write_text(new, encoding="utf-8")
    return new != old


if __name__ == "__main__":
    main()
