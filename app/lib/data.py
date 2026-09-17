"""Read-only, cached loaders over the pipeline's published files.

Contract (docs/80_frontend.md §2):

* **Read-only.** Nothing here runs a stage, writes a file or opens a socket. The numbers are the pipeline's own: a
  loader reads a CSV (optionally a subset of columns), and the headline facts come from the reporting modules'
  canonical code (`desk.reporting.one_pager` over `desk.reporting.interview_pack`), so the app and the one-pager can
  never disagree.
* **One missing-file policy.** Every loader returns ``None`` when its file is absent (the public export leaves out
  `data/processed/market_daily.csv`, `lme_daily.csv`, `freight_weekly.csv`, `headlines_weekly.csv` and some interim
  files). Pages render `components.missing_data(rel)` for a ``None``; code that prefers exceptions calls
  `require(value, rel)`, which raises `MissingData`, and wraps the block in `components.guard()`.
* **Cheap.** `st.cache_data` keyed on the absolute path *and the file's mtime*, so a pipeline re-run invalidates the
  cache by itself; large tables take `usecols` (required for `mtm_daily` and `book_exposures_daily`).

Paths are repo-relative strings (``"outputs/tables/var_daily.csv"``) resolved against the module-level ``ROOT`` at
call time, so a test can point the whole app at another directory with ``monkeypatch.setattr(data, "ROOT", tmp)``.
"""

from __future__ import annotations

import posixpath
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]

TABLES = "outputs/tables"
CHARTS = "outputs/charts"
REPORTS = "outputs/reports"
EXCEL = "outputs/excel"
PROCESSED = "data/processed"
DOCS = "docs"
CONFIG = "config"
PARAMS = "config/params"

WORKBOOK = f"{EXCEL}/Metals_Desk_Master.xlsx"
RECON_JSON = f"{EXCEL}/reconciliation.json"

# Files the strict public export (tools/export_public.py) leaves out because they republish LME prices, freight index
# values or headline text. Their absence is expected in a public copy, not a broken build.
PUBLIC_EXPORT_OMITS = frozenset({
    f"{PROCESSED}/market_daily.csv", f"{PROCESSED}/lme_daily.csv", f"{PROCESSED}/freight_weekly.csv",
    f"{PROCESSED}/headlines_weekly.csv",
})

Usecols = Sequence[str | int] | None
T = TypeVar("T")


# ------------------------------------------------------------------------------------------------ paths and policy
def path(rel: str) -> Path:
    """Absolute path of a repo-relative file (resolved against ROOT at call time)."""
    return ROOT / rel


def exists(rel: str) -> bool:
    return path(rel).exists()


def table_rel(name: str) -> str:
    """``"var_daily"`` -> ``"outputs/tables/var_daily.csv"``."""
    return f"{TABLES}/{name}.csv"


def processed_rel(name: str) -> str:
    return f"{PROCESSED}/{name}.csv"


def _mtime(rel: str) -> float | None:
    try:
        return path(rel).stat().st_mtime
    except OSError:
        return None


class MissingData(FileNotFoundError):
    """A published file the page needs is not in this copy. `components.guard()` renders it as an st.info."""

    def __init__(self, rel: str, how_to_rebuild: str | None = None):
        self.rel = rel
        self.how_to_rebuild = how_to_rebuild or rebuild_hint(rel)
        super().__init__(f"{rel} is not in this copy")


def require(value: T | None, rel: str) -> T:
    """Return `value`, or raise MissingData(rel) when a loader returned None."""
    if value is None:
        raise MissingData(rel)
    return value


_RUN = "DESK_OFFLINE=1 .venv/bin/python run_all.py"
_STAGE_BY_PREFIX: tuple[tuple[str, str], ...] = (
    (f"{TABLES}/parity_", "P1"), (f"{TABLES}/term_structure_", "P1"),
    (f"{TABLES}/trade_cashflows", "P3"), (f"{TABLES}/trade_", "P2"),
    (f"{TABLES}/var_", "P4"), (f"{TABLES}/kupiec", "P4"), (f"{TABLES}/mc_", "P4"),
    (f"{TABLES}/credit_", "P5"), (f"{TABLES}/margin_liquidity", "P5"),
    (f"{TABLES}/sentiment_", "P7"),
    (f"{TABLES}/", "P3"),  # mtm, attribution, exposures, adverse events, mcx_*, pnl_*, buyer credit
    (f"{CHARTS}/p0_", "P0"), (f"{CHARTS}/p1_", "P1"), (f"{CHARTS}/p3_", "P3"), (f"{CHARTS}/p4_", "P4"),
    (f"{CHARTS}/p5_", "P5"), (f"{CHARTS}/p6_", "P6"), (f"{CHARTS}/p7_", "P7"),
    (f"{REPORTS}/risk_policy_memo", "P5"), (f"{REPORTS}/", "P6"),
    (WORKBOOK, "P3"),
)


def rebuild_hint(rel: str) -> str:
    """How to get a missing file back, in one or two sentences (markdown)."""
    if rel in PUBLIC_EXPORT_OMITS:
        return ("The public export leaves it out because it republishes LME prices, freight index values or headline "
                "text (see `DATA_NOTICE.md` in the public copy). Rebuild it by running the Phase 0 fetchers online: "
                "`.venv/bin/python run_all.py --only P0` (without `DESK_OFFLINE`), then "
                f"`{_RUN} --from P1`.")
    if rel.startswith(f"{PROCESSED}/") or rel.startswith("data/"):
        return (f"Rebuild Phase 0 with `{_RUN} --only P0` (offline, from the raw cache); if the raw cache is not in "
                "this copy either, run it without `DESK_OFFLINE` to fetch the sources online.")
    if rel == RECON_JSON:
        from desk.excel import reconciliation_status as rs  # standard library only: cheap
        return (f"The slow full recalculation of the workbook has not been run on this build. Run `{rs.VERIFY_COMMAND}` "
                f"{rs.VERIFY_CONDITIONS}.")
    for prefix, stage in _STAGE_BY_PREFIX:
        if rel.startswith(prefix):
            return (f"Rebuild it with `{_RUN} --only {stage}` (stages read upstream files, so run the earlier phases "
                    "first if their outputs are missing too).")
    return "It is a source file of the repository: restore it from the repository copy you cloned."


# ------------------------------------------------------------------------------------------------ generic readers
def _tuple(x: Iterable[Any] | None) -> tuple[Any, ...] | None:
    return None if x is None else tuple(x)


@st.cache_data(show_spinner=False, max_entries=128)
def _read_csv_cached(abs_path: str, mtime: float, usecols: tuple[Any, ...] | None, dtype_str: bool) -> pd.DataFrame:
    return pd.read_csv(abs_path, usecols=list(usecols) if usecols is not None else None,
                       dtype=str if dtype_str else None, low_memory=False)


def read_csv(rel: str, usecols: Usecols = None, *, dtype_str: bool = False) -> pd.DataFrame | None:
    """Any repo-relative CSV, or None when it is not in this copy. Dates stay ISO strings (sortable, plot-ready)."""
    mtime = _mtime(rel)
    if mtime is None:
        return None
    return _read_csv_cached(str(path(rel)), mtime, _tuple(usecols), dtype_str)


def table(name: str, usecols: Usecols = None, *, dtype_str: bool = False) -> pd.DataFrame | None:
    """outputs/tables/<name>.csv."""
    return read_csv(table_rel(name), usecols, dtype_str=dtype_str)


@st.cache_data(show_spinner=False, max_entries=64)
def _read_text_cached(abs_path: str, mtime: float) -> str:
    return Path(abs_path).read_text(encoding="utf-8")


def read_text(rel: str) -> str | None:
    mtime = _mtime(rel)
    return None if mtime is None else _read_text_cached(str(path(rel)), mtime)


@st.cache_data(show_spinner=False, max_entries=16)
def _read_bytes_cached(abs_path: str, mtime: float) -> bytes:
    return Path(abs_path).read_bytes()


def read_bytes(rel: str) -> bytes | None:
    """Raw bytes for downloads (PDF, XLSX, MD)."""
    mtime = _mtime(rel)
    return None if mtime is None else _read_bytes_cached(str(path(rel)), mtime)


@st.cache_data(show_spinner=False, max_entries=8)
def _read_yaml_cached(abs_path: str, mtime: float) -> Any:
    import yaml

    return yaml.safe_load(Path(abs_path).read_text(encoding="utf-8"))


def read_yaml(rel: str) -> Any | None:
    mtime = _mtime(rel)
    return None if mtime is None else _read_yaml_cached(str(path(rel)), mtime)


# ------------------------------------------------------------------------------------------------ market and provenance
def market_daily(usecols: Usecols = None) -> pd.DataFrame | None:
    """data/processed/market_daily.csv, the Phase 0 daily panel. Not in the public export."""
    return read_csv(processed_rel("market_daily"), usecols)


def lme_daily(usecols: Usecols = None) -> pd.DataFrame | None:
    return read_csv(processed_rel("lme_daily"), usecols)


def fx_rates_daily(usecols: Usecols = None) -> pd.DataFrame | None:
    return read_csv(processed_rel("fx_rates_daily"), usecols)


def freight_weekly(usecols: Usecols = None) -> pd.DataFrame | None:
    return read_csv(processed_rel("freight_weekly"), usecols)


def headlines_weekly(usecols: Usecols = None) -> pd.DataFrame | None:
    return read_csv(processed_rel("headlines_weekly"), usecols)


def series_provenance() -> pd.DataFrame | None:
    """column, flag, source, transformation, unit for every column of the daily market panel."""
    return read_csv(processed_rel("series_provenance"))


def series_flags() -> dict[str, str]:
    """Market-panel column -> DIRECT/PROXY/ASSUMPTION ({} when series_provenance.csv is missing)."""
    prov = series_provenance()
    return {} if prov is None else dict(zip(prov["column"], prov["flag"]))


# ------------------------------------------------------------------------------------------------ parity (P1)
def parity_weekly(usecols: Usecols = None) -> pd.DataFrame | None:
    return table("parity_weekly", usecols)


def parity_sensitivity(kind: Literal["lme_fx", "freight_duty", "summary", "cases"], wide: bool = False,
                       usecols: Usecols = None) -> pd.DataFrame | None:
    """parity_sensitivity_<kind>[_wide].csv (`wide` exists for lme_fx and freight_duty only)."""
    if wide and kind not in ("lme_fx", "freight_duty"):
        raise ValueError(f"no wide table for parity_sensitivity_{kind}")
    return table(f"parity_sensitivity_{kind}{'_wide' if wide else ''}", usecols)


def parity_extra(kind: Literal["reference_cases", "quality_scenarios", "anchor_correlation"],
                 usecols: Usecols = None) -> pd.DataFrame | None:
    return table(f"parity_{kind}", usecols)


def term_structure(kind: Literal["weekly", "roll_monthly"] = "weekly", usecols: Usecols = None) -> pd.DataFrame | None:
    return table(f"term_structure_{kind}", usecols)


# ------------------------------------------------------------------------------------------------ book (P2)
def trade_book(usecols: Usecols = None, *, dtype_str: bool = False) -> pd.DataFrame | None:
    return table("trade_book", usecols, dtype_str=dtype_str)


def trade_hedges(usecols: Usecols = None) -> pd.DataFrame | None:
    return table("trade_hedges", usecols)


def trade_eligibility_check(usecols: Usecols = None) -> pd.DataFrame | None:
    return table("trade_eligibility_check", usecols)


def trade_credit_exposure(usecols: Usecols = None) -> pd.DataFrame | None:
    return table("trade_credit_exposure", usecols)


def trade_cashflows(scenario: Literal["REALISED", "PLANNED_AT_TRADE_DATE"] | None = "REALISED",
                    usecols: Usecols = None) -> pd.DataFrame | None:
    """trade_cashflows.csv filtered to one scenario (None = both)."""
    cols = None if usecols is None else tuple(dict.fromkeys(["scenario", *usecols]))
    df = table("trade_cashflows", cols)
    if df is None or scenario is None:
        return df
    return df[df["scenario"] == scenario].reset_index(drop=True)


def trades_yaml() -> dict | None:
    """config/trades.yaml, the authoritative SIM ticket inputs."""
    return read_yaml(f"{CONFIG}/trades.yaml")


def counterparties_yaml() -> dict | None:
    """config/counterparties.yaml (every counterparty is SIM)."""
    return read_yaml(f"{CONFIG}/counterparties.yaml")


# ------------------------------------------------------------------------------------------------ MTM and attribution (P3)
Variant = Literal["base", "grade_pit", "mcx_mirror"]


def _variant(name: str, variant: Variant) -> str:
    return name if variant == "base" else f"{name}_{variant}"


def mtm_daily(usecols: Sequence[str]) -> pd.DataFrame | None:
    """mtm_daily.csv (4.6 MB, leg level): columns must be named."""
    return table("mtm_daily", usecols)


def attribution_daily(variant: Variant = "base", usecols: Usecols = None) -> pd.DataFrame | None:
    """Daily attribution by bucket. Holds BOOK rows and per-ticket rows in one table (split with `split_book`)."""
    return table(_variant("attribution_daily", variant), usecols)


def split_book(att: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(BOOK rows, ticket rows) of an attribution-style table with a `trade_id` column, each sorted by date."""
    is_book = att["trade_id"] == "BOOK"
    book = att[is_book].sort_values("date").reset_index(drop=True)
    trades = att[~is_book].sort_values(["trade_id", "date"]).reset_index(drop=True)
    return book, trades


def attribution_leg_daily(variant: Variant = "base", usecols: Usecols = None) -> pd.DataFrame | None:
    return table(_variant("attribution_leg_daily", variant), usecols)


def book_exposures_daily(usecols: Sequence[str], variant: Variant = "base") -> pd.DataFrame | None:
    """Daily exposures; `scope` is "book" or "trade". Columns must be named."""
    return table(_variant("book_exposures_daily", variant), usecols)


def adverse_event(name: str, usecols: Usecols = None) -> pd.DataFrame | None:
    """adverse_event_<name>.csv, e.g. "1_lme_crash", "1_lme_crash_daily", "2_usdinr", "3_freight_stress_hypothetical"
    (the freight spike is a labelled HYPOTHETICAL: freight fell in 2022)."""
    return table(f"adverse_event_{name}", usecols)


def adverse_events_summary() -> pd.DataFrame | None:
    return table("adverse_events_summary", dtype_str=True)


def adverse_event_windows() -> pd.DataFrame | None:
    return table("adverse_event_windows")


def event_markers() -> list[tuple[str, str]]:
    """(date, label) markers for charts, from adverse_event_windows.csv: the LME record close (E1 start = argmax of
    cash in the window), the start of the crash fortnight and of the INR slide. [] when the table is missing."""
    w = adverse_event_windows()
    if w is None:
        return []
    labels = {"E1_LME_CRASH": "LME record close", "E1_CRASH_FORTNIGHT": "crash fortnight",
              "E2_INR_DEPRECIATION": "INR slide begins"}
    rows = w[w["event"].isin(labels)]
    return [(str(r.start), labels[r.event]) for r in rows.itertuples()]


def mcx_variation_margin(usecols: Usecols = None) -> pd.DataFrame | None:
    return table("mcx_variation_margin", usecols)


def mcx_table(name: Literal["basis_risk", "roll_carry", "roll_carry_mcx_mirror"],
              usecols: Usecols = None) -> pd.DataFrame | None:
    return table(f"mcx_{name}", usecols)


def pnl_sensitivity(kind: Literal["pricing", "summary", "sign_robustness"], usecols: Usecols = None
                    ) -> pd.DataFrame | None:
    """pnl_sensitivity_<kind>.csv. Every row is a SENSITIVITY, not base P&L."""
    return table(f"pnl_sensitivity_{kind}", usecols)


def pnl_controls() -> pd.DataFrame | None:
    return table("pnl_controls")


def new_deal_timing() -> pd.DataFrame | None:
    return table("new_deal_timing")


def buyer_credit_exposure(by_trade: bool = False, usecols: Usecols = None) -> pd.DataFrame | None:
    return table("buyer_credit_exposure_by_trade_daily" if by_trade else "buyer_credit_exposure_daily", usecols)


# ------------------------------------------------------------------------------------------------ risk (P4, P5) and P7
def var_table(name: Literal["daily", "summary", "backtest_exceptions", "calibration", "garch_params", "lead_lag",
                            "mcx_beta", "unit_backtest_daily", "vol_forecasts"],
              usecols: Usecols = None) -> pd.DataFrame | None:
    return table(f"var_{name}", usecols)


def kupiec(usecols: Usecols = None) -> pd.DataFrame | None:
    return table("kupiec", usecols)


def mc_table(name: Literal["summary", "pnl_distribution", "pnl_quantiles", "snapshots", "stress_scenarios",
                           "stress_details", "es_contributions", "factor_stats", "covariance", "delta_check",
                           "controls"],
             usecols: Usecols = None) -> pd.DataFrame | None:
    """mc_<name>.csv. mc_pnl_distribution is 3 MB: name the columns."""
    return table(f"mc_{name}", usecols)


def credit_table(name: Literal["scores", "scores_sensitivity", "tracker", "tracker_bookings", "model_coefficients",
                               "model_fit", "model_calibration", "model_sample_size", "band_policy",
                               "synthetic_training_data"],
                 usecols: Usecols = None) -> pd.DataFrame | None:
    """credit_<name>.csv. The model is fitted on SYNTHETIC data by design (docs/50_credit_scoring.md §1)."""
    return table(f"credit_{name}", usecols)


def margin_liquidity(name: Literal["", "summary", "controls", "facility", "fortnight", "lc_lots", "limit_grid",
                                   "policy_limits", "stress_moves", "windows"] = "",
                     usecols: Usecols = None) -> pd.DataFrame | None:
    """margin_liquidity.csv (name="") or margin_liquidity_<name>.csv."""
    return table(f"margin_liquidity_{name}" if name else "margin_liquidity", usecols)


def sentiment_table(name: Literal["weekly", "summary", "leadlag", "episodes", "episode_weeks", "lexicon",
                                  "headlines_scored", "week_extremes"],
                    usecols: Usecols = None) -> pd.DataFrame | None:
    return table(f"sentiment_{name}", usecols)


# ------------------------------------------------------------------------------------------------ register, docs, reports
@st.cache_data(show_spinner=False, max_entries=2)
def _params_cached(stamp: tuple[float, ...]) -> pd.DataFrame:
    from desk import config

    return config.params_frame()


def params_register() -> pd.DataFrame | None:
    """The whole assumptions register (desk.config.params_frame()): key, value, unit, flag, source, verify, note."""
    d = path(PARAMS)
    files = sorted(d.glob("*.yaml")) if d.is_dir() else []
    if not files:
        return None
    return _params_cached(tuple(f.stat().st_mtime for f in files))


def param_flag(key: str) -> str | None:
    p = params_register()
    if p is None:
        return None
    hit = p.loc[p["key"] == key, "flag"]
    return None if hit.empty else str(hit.iloc[0])


def param_verify_status(key: str) -> str | None:
    """VERIFIED / PARTIAL / PENDING / N/A: the leading word of the register's `verify` field."""
    p = params_register()
    if p is None:
        return None
    hit = p.loc[p["key"] == key, "verify"]
    m = re.match(r"\s*([A-Z/]+)", str(hit.iloc[0])) if not hit.empty else None
    return m.group(1) if m else None


def doc_markdown(rel: str) -> str | None:
    """A markdown file (docs/*.md, outputs/reports/*.md, README.md)."""
    return read_text(rel)


@dataclass(frozen=True)
class ReportFile:
    rel: str
    name: str
    ext: str
    size_bytes: int


def report_files() -> list[ReportFile]:
    """Every file in outputs/reports/ (desk notes, post-mortem, risk memo, interview pack, one-pager), sorted."""
    d = path(REPORTS)
    if not d.is_dir():
        return []
    return [ReportFile(f"{REPORTS}/{f.name}", f.stem, f.suffix.lstrip("."), f.stat().st_size)
            for f in sorted(d.iterdir()) if f.is_file() and not f.name.startswith(".")]


def chart_path(name: str) -> Path | None:
    """outputs/charts/<name>.png as an absolute path (for st.image), or None."""
    rel = f"{CHARTS}/{name if name.endswith('.png') else name + '.png'}"
    return path(rel) if exists(rel) else None


# ------------------------------------------------------------------------------------------------ build status
@dataclass(frozen=True)
class ReconSummary:
    status: str               # VERIFIED / STALE / NOT_RUN / FAILED
    reason: str
    n_recalculated: int | None
    n_check_failures: int | None
    how_to_verify: str


@st.cache_data(show_spinner=False, max_entries=4)
def _recon_cached(recon: str, workbook: str, stamps: tuple[float | None, float | None]) -> ReconSummary:
    from desk.excel import reconciliation_status as rs

    s = rs.status(recon_path=Path(recon), workbook_path=Path(workbook))
    return ReconSummary(s.status, s.reason, s.n_recalculated, s.n_check_failures,
                        "" if s.verified else s.how_to_verify())


def recon_status() -> ReconSummary:
    """desk.excel.reconciliation_status.status() for the workbook in this copy (never raises)."""
    return _recon_cached(str(path(RECON_JSON)), str(path(WORKBOOK)), (_mtime(RECON_JSON), _mtime(WORKBOOK)))


@st.cache_data(show_spinner=False, ttl=300)
def _git_commit_cached(root: str) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True,
                             timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "unknown"


def git_commit() -> str:
    """Short commit hash of this copy, or "unknown" (no git, not a repository, timeout)."""
    return _git_commit_cached(str(ROOT))


# ------------------------------------------------------------------------------------------------ headline facts
# Every file `desk.reporting.one_pager.load_sources` (and the interview pack's loader under it) reads. The canonical
# computation runs only when all of them are present in the same tree the desk package reads from.
FACT_INPUTS: tuple[str, ...] = tuple(
    [table_rel(n) for n in (
        "attribution_daily", "attribution_leg_daily", "pnl_sensitivity_sign_robustness", "pnl_sensitivity_summary",
        "new_deal_timing", "pnl_controls", "trade_book", "parity_weekly", "adverse_events_summary",
        "term_structure_weekly", "mcx_roll_carry", "mcx_basis_risk", "mc_summary", "mc_stress_scenarios",
        "mc_snapshots", "var_summary", "var_lead_lag", "kupiec", "credit_scores", "credit_tracker_bookings",
        "credit_synthetic_training_data", "margin_liquidity_summary", "margin_liquidity_limit_grid", "var_mcx_beta",
        "margin_liquidity_facility", "margin_liquidity_policy_limits", "sentiment_summary", "pnl_sensitivity_pricing",
        "var_daily", "trade_eligibility_check")]
    + [processed_rel(n) for n in ("market_daily", "freight_weekly", "series_provenance")]
    + [f"{REPORTS}/post_mortem.md", RECON_JSON, WORKBOOK]
)
# Files whose absence the canonical loader cannot survive (the last three are read defensively by it).
_FACT_REQUIRED = FACT_INPUTS[:-3]


@dataclass(frozen=True)
class Facts:
    """The one-pager's facts, formatted exactly as `one_pager.format_facts` renders them.

    text      placeholder -> formatted string ("book_pnl" -> "₹192.1 m"); see desk/reporting/one_pager.py
    num       raw numbers the charts need (book_pnl, book_pnl_we, band_lo, band_hi, band_be, book_mt)
    flags     band_sign_robust, band_be_inside (from pnl_sensitivity_sign_robustness.csv)
    buckets   lifetime P&L by bucket (PNL_BUCKETS keys), the sums the one-pager quotes
    complete  True when computed by the canonical loader; False on the partial path used when inputs are missing
    missing   repo-relative inputs absent from this copy
    problems  parts of the partial computation that could not run (with the reason)
    failed_claims   qualitative one-pager claims that no longer hold (`one_pager.check_claims`)
    claims_checked  False when the claims could not be re-tested
    """

    text: dict[str, str]
    num: dict[str, float]
    flags: dict[str, bool]
    buckets: dict[str, float]
    complete: bool
    missing: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    failed_claims: tuple[str, ...] = ()
    claims_checked: bool = True

    def has(self, *keys: str) -> bool:
        return all(k in self.text for k in keys)

    def t(self, key: str, default: str = "n/a") -> str:
        return self.text.get(key, default)


_NUM_KEYS = ("book_pnl", "book_pnl_we", "band_lo", "band_hi", "band_be", "book_mt")
_FLAG_KEYS = ("band_sign_robust", "band_be_inside")
_ERRORS = (KeyError, IndexError, ValueError, TypeError, AttributeError, FileNotFoundError)


def _pack(text: Mapping[str, str], raw: Mapping[str, Any], complete: bool, missing: Iterable[str] = (),
          problems: Iterable[str] = (), failed: Iterable[str] = (), checked: bool = True) -> Facts:
    return Facts(text={k: str(v) for k, v in text.items()},
                 num={k: float(raw[k]) for k in _NUM_KEYS if k in raw},
                 flags={k: bool(raw[k]) for k in _FLAG_KEYS if k in raw},
                 buckets={str(k): float(v) for k, v in dict(raw.get("buckets", {})).items()},
                 complete=complete, missing=tuple(missing), problems=tuple(problems), failed_claims=tuple(failed),
                 claims_checked=checked)


def _canonical_facts() -> Facts:
    from desk.reporting import one_pager as op

    src = op.load_sources()
    raw = op.compute_raw(src)
    text = op.format_facts(raw)
    return _pack(text, raw, complete=True, failed=op.check_claims(raw))


# Partial path. The canonical loader reads every input eagerly, so one missing file (the public export omits
# market_daily.csv and freight_weekly.csv) stops it. Here each source is loaded only if present, with the same dtype
# policy as interview_pack.load_sources (all columns: those functions select columns by name), and the same
# component functions run in the canonical order, each on its own. tests/test_app_pages.py checks that every fact
# this path produces equals the canonical one.
_PARTIAL_SOURCES: dict[str, tuple[str, bool]] = {   # src key -> (repo-relative file, read as str)
    "att": (table_rel("attribution_daily"), False),
    "robust": (table_rel("pnl_sensitivity_sign_robustness"), False),
    "sens": (table_rel("pnl_sensitivity_summary"), False),
    "nd_timing": (table_rel("new_deal_timing"), False),
    "controls": (table_rel("pnl_controls"), False),
    "book": (table_rel("trade_book"), True),
    "cp": (table_rel("trade_book"), True),
    "parity": (table_rel("parity_weekly"), False),
    "events": (table_rel("adverse_events_summary"), True),
    "basis": (table_rel("mcx_basis_risk"), False),
    "mc": (table_rel("mc_summary"), False),
    "stress": (table_rel("mc_stress_scenarios"), False),
    "stress_full": (table_rel("mc_stress_scenarios"), False),
    "snap_mcx": (table_rel("mc_snapshots"), False),
    "var": (table_rel("var_summary"), True),
    "leadlag": (table_rel("var_lead_lag"), False),
    "kupiec": (table_rel("kupiec"), False),
    "kupiec_unit": (table_rel("kupiec"), False),
    "credit": (table_rel("credit_scores"), False),
    "bookings": (table_rel("credit_tracker_bookings"), False),
    "liq": (table_rel("margin_liquidity_summary"), True),
    "grid": (table_rel("margin_liquidity_limit_grid"), False),
    "grid_full": (table_rel("margin_liquidity_limit_grid"), False),
    "facility": (table_rel("margin_liquidity_facility"), True),
    "limits": (table_rel("margin_liquidity_policy_limits"), True),
    "mcx_beta": (table_rel("var_mcx_beta"), False),
    "sent": (table_rel("sentiment_summary"), False),
    "pricing": (table_rel("pnl_sensitivity_pricing"), False),
    "var_daily": (table_rel("var_daily"), False),
    "elig": (table_rel("trade_eligibility_check"), False),
    "prov": (processed_rel("series_provenance"), False),
    "mkt": (processed_rel("market_daily"), False),
}


def _partial_sources(absent: frozenset[str]) -> dict[str, Any]:
    src: dict[str, Any] = {}
    for key, (rel, as_str) in _PARTIAL_SOURCES.items():
        if rel in absent:
            continue
        df = read_csv(rel, dtype_str=as_str)
        if df is not None:
            src[key] = df
    if "mcx_beta" in src:
        src["mcx_beta"] = src["mcx_beta"].set_index("sampling")
    synth = table_rel("credit_synthetic_training_data")
    if synth not in absent and exists(synth):
        src["n_synth"] = len(require(read_csv(synth, usecols=(0,)), synth))
    params = params_register()
    if params is not None:
        src["params"] = params
    pm = f"{REPORTS}/post_mortem.md"
    src["post_mortem_md"] = (read_text(pm) or "") if pm not in absent else ""
    src["n_desk_notes"] = len(sorted(path(REPORTS).glob("desk_note_*.md"))) if path(REPORTS).is_dir() else 0
    from desk.excel import reconciliation_status as rs

    src["recon"] = rs.status(recon_path=path(RECON_JSON), workbook_path=path(WORKBOOK))
    return src


def _partial_facts(absent: frozenset[str]) -> Facts:
    from desk import config
    from desk.reporting import interview_pack as ip
    from desk.reporting import one_pager as op

    src = _partial_sources(absent)
    missing = sorted(r for r in _FACT_REQUIRED if r in absent or not exists(r))
    r: dict[str, Any] = {}
    problems: list[str] = []
    drop: set[str] = set()

    def step(name: str, fn: Callable[[], Mapping[str, Any]]) -> None:
        try:
            r.update(fn())
        except _ERRORS as exc:
            problems.append(f"{name}: {type(exc).__name__}: {exc}")

    step("book", lambda: ip._raw_book(src))
    if "book_pnl" not in r:
        return _pack({}, r, complete=False, missing=missing, problems=problems, checked=False)

    def parity_counts() -> dict[str, int]:     # the three counts interview_pack._raw_parity takes from parity_weekly
        win = src["parity"][src["parity"]["in_window"]]
        return {"q1_n_cases": len(win), "q1_n_elig": int(win["trade_eligible"].sum()),
                "q1_n_open": int(win["open_base"].sum())}

    def garch() -> dict[str, Any]:
        if "mkt" in src:
            return ip._raw_garch(src)
        out = ip._raw_garch({**src, "mkt": pd.DataFrame({"date": pd.Series(dtype=str)})})
        out["q16_day_after_ath"] = out["ath_date"]  # placeholder: the next panel day needs market_daily.csv
        drop.add("day_after_ath")
        return out

    def ath1_date() -> dict[str, Any]:           # interview_pack._raw_freight reads it from the stress table
        fr = ip._one(src["stress"], snapshot_id=ip.MC_SNAP_ATH, scenario_id="freight_plus_40pct")
        return {"ath1_date": fr["snapshot_date"]}

    step("parity counts", parity_counts)
    step("grade", lambda: ip._raw_grade(src, r))
    step("MC first snapshot date", ath1_date)
    step("funding", lambda: ip._raw_funding(src))
    step("basis", lambda: ip._raw_basis(src, r))
    step("attribution", lambda: ip._raw_attribution(src, r))
    step("worst trade", lambda: ip._raw_worst(src, r))
    step("credit", lambda: ip._raw_credit(src))
    step("margin", lambda: ip._raw_margin(src))
    step("data", lambda: ip._raw_data(src))
    step("what I'd do differently", lambda: ip._raw_differently(src, r))
    step("GARCH", garch)
    step("ML", lambda: ip._raw_ml(src))
    step("best trade", lambda: op._best_trade(src, r))
    step("buckets", lambda: op._buckets(r))
    step("VaR peak", lambda: op._var(src))
    step("unit backtest", lambda: op._unit_backtest(src))
    step("stresses", lambda: op._stresses(src))
    step("desk", lambda: op._desk(src))
    step("credit ranking", lambda: op._credit(src))
    step("scalars", lambda: {
        "var_mean_hist": ip._f(ip._metric(src["var"], "var_mean_hist250", "book_window")),
        "mc_ath_var99": float(ip._one(src["mc"], snapshot_id=ip.MC_SNAP_ATH, variant="normal_window")["var99_inr"]),
        "win_base": int(config.value("var_hist_window_base_days")),
        "win_fast": int(config.value("var_hist_window_fast_days"))})
    r["recon"] = src["recon"]

    try:
        text = dict(op.format_facts(r))
    except _ERRORS as exc:
        problems.append(f"formatting: {type(exc).__name__}: {exc}")
        text = _headline_text(r)
    for k in drop:
        text.pop(k, None)
    try:
        failed, checked = op.check_claims(r), True
    except _ERRORS as exc:
        failed, checked = [], False
        problems.append(f"claims: {type(exc).__name__}: {exc}")
    return _pack(text, r, complete=False, missing=missing, problems=problems, failed=failed, checked=checked)


def _headline_text(r: Mapping[str, Any]) -> dict[str, str]:
    """Last resort when the full formatter cannot run: the headline keys only, formatted as one_pager.format_facts
    formats them (and checked against it by the tests)."""
    import desk
    from desk.reporting.interview_pack import day, inr, inr_m, num

    text = {"anchor_key": "domestic_anchor_premium_inr_t", "window_start": day(desk.WINDOW_START, True),
            "window_end": day(desk.WINDOW_END, True), "horizon_end": day(desk.HORIZON_END, True),
            "book_pnl": inr_m(r["book_pnl"]), "book_pnl_mt": inr(r["book_pnl"] / r["book_mt"]),
            "book_pnl_we": inr_m(r["book_pnl_we"]), "band_lo": inr_m(r["band_lo"], sign=True),
            "band_hi": inr_m(r["band_hi"], sign=True), "band_be": num(r["band_be"]),
            "n_trades": num(r["n_trades"]), "book_mt": num(r["book_mt"]), "book_boxes": num(r["book_boxes"])}
    for k in ("anchor_flag", "anchor_status"):
        if k in r:
            text[k] = str(r[k])
    return text


def compute_facts(absent: Iterable[str] = ()) -> Facts:
    """Uncached. `absent` treats those repo-relative inputs as missing (tests use it to simulate the public copy)."""
    from desk.paths import ROOT as DESK_ROOT

    absent = frozenset(absent)
    same_tree = Path(ROOT).resolve() == DESK_ROOT.resolve()
    if same_tree and not absent and all(exists(rel) for rel in _FACT_REQUIRED):
        try:
            return _canonical_facts()
        except _ERRORS:
            pass    # a file vanished or a table changed shape: the partial path records which part failed
    return _partial_facts(absent)


@st.cache_data(show_spinner="Reading the published tables…", max_entries=4)
def _facts_cached(root: str, stamps: tuple[tuple[str, float | None], ...]) -> Facts:
    return compute_facts()


def headline_facts() -> Facts:
    """The one-pager's facts for this copy (cached; recomputed when any input file changes)."""
    return _facts_cached(str(ROOT), tuple((rel, _mtime(rel)) for rel in FACT_INPUTS))


# ------------------------------------------------------------------------------------------------ spec index
@dataclass(frozen=True)
class SpecRow:
    row: str                   # "4.1"
    label: str                 # "4.1 ★"
    table: str                 # "Table 6: Component 4, risk pack"
    element: str
    delivered_by: str          # markdown, links as written in docs/INDEX.md (rewrite with docs_text.rewrite_links)
    status: str
    gaps: tuple[str, ...] = field(default_factory=tuple)   # "Gaps and flags at a glance" notes that name this row


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


@st.cache_data(show_spinner=False, max_entries=2)
def _spec_index_cached(abs_path: str, mtime: float) -> dict[str, SpecRow]:
    rows: dict[str, dict[str, Any]] = {}
    gaps: dict[str, list[str]] = {}
    heading = ""
    for line in Path(abs_path).read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            continue
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        if heading.startswith("Gaps") and len(cells) >= 3:
            for rid in re.findall(r"\d\.\d+", cells[0]):
                gaps.setdefault(rid, []).append(cells[2])
        elif heading.startswith("Table") and len(cells) >= 4:
            m = re.match(r"(\d\.\d+)", cells[0])
            if m:
                rows[m.group(1)] = {"row": m.group(1), "label": cells[0], "table": heading, "element": cells[1],
                                    "delivered_by": cells[2], "status": cells[3]}
    return {rid: SpecRow(**v, gaps=tuple(gaps.get(rid, ()))) for rid, v in rows.items()}


def spec_index() -> dict[str, SpecRow]:
    """docs/INDEX.md parsed: spec row -> element, status, delivering files and any gap note. {} if missing."""
    rel = f"{DOCS}/INDEX.md"
    mtime = _mtime(rel)
    return {} if mtime is None else _spec_index_cached(str(path(rel)), mtime)


def rel_join(doc_rel: str, target: str) -> str | None:
    """Resolve a link target written inside `doc_rel` to a repo-relative path (None if it leaves the repo)."""
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(doc_rel), target))
    return None if joined.startswith("..") or joined.startswith("/") else joined
