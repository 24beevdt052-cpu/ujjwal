"""Shared UI pieces. Every page starts with `sim_banner()` and `page_header(...)`; see docs/80_frontend.md §3.

Honesty rules these helpers enforce:

* `sim_banner()` on every page ("ACADEMIC SIMULATION — not actual trades", from `desk.SIM_LABEL`).
* `pnl_headline(facts)` is the ONLY way to show the book's headline P&L: the value never appears without its
  anchor-premium band, the break-even and the sign-robustness statement read from
  `outputs/tables/pnl_sensitivity_sign_robustness.csv`.
* `source_caption(files, flags)` under every chart and table; `flag_badge` colours DIRECT / PROXY / ASSUMPTION and the
  labels a reader must not miss (SIM, HYPOTHETICAL, SYNTHETIC).
* `what_it_tells(doc)` quotes the doc's own "What this does and doesn't tell you" section instead of rewriting it.
* `missing_data(rel)` / `available(*rels)` / `guard()` turn a file that is not in this copy into an st.info.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitAPIException

from app.lib import data, docs_text
from desk import SIM_LABEL

APP_DIR = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------------------------------------ page registry
@dataclass(frozen=True)
class PageSpec:
    key: str
    section: str          # navigation group ("" = ungrouped, shown first)
    file: str             # file name under app/views/
    title: str
    icon: str
    blurb: str            # one line: what the page shows
    spec_rows: tuple[str, ...]

    @property
    def path(self) -> Path:
        return APP_DIR / "views" / self.file


PAGES: tuple[PageSpec, ...] = (
    PageSpec("overview", "", "overview.py", "Overview", ":material/dashboard:",
             "The desk, its headline P&L with its band, and the risk findings at a glance.", ("3.3",)),
    PageSpec("market", "Markets & trade finder", "market.py", "Market data", ":material/show_chart:",
             "LME, USD/INR, the MCX proxy and freight through 2022, each series with its provenance flag.",
             ("1.7", "8.1", "8.3")),
    PageSpec("parity", "Markets & trade finder", "parity.py", "Trade finder (parity)", ":material/travel_explore:",
             "Weekly import parity, the open/closed window, the ex-ante trade rule and the sensitivity tables.",
             ("1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7")),
    PageSpec("trade_book", "The book", "trade_book.py", "Trade book", ":material/receipt_long:",
             "Nine SIM tickets: SPA terms, Incoterms, pricing, LC and payment terms, hedges and cashflows.",
             ("2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7", "2.8", "2.9")),
    PageSpec("pnl", "The book", "pnl.py", "P&L & attribution", ":material/waterfall_chart:",
             "Daily MTM, attribution by bucket, per-ticket waterfalls and the three adverse events.",
             ("3.1", "3.2", "3.3", "3.4", "3.5", "3.6")),
    PageSpec("risk", "Risk", "risk.py", "Risk pack", ":material/shield:",
             "GARCH vs historical VaR with Kupiec, Monte Carlo stresses, credit scoring, margin and liquidity.",
             ("4.1", "4.2", "4.3", "4.4", "4.5", "4.6")),
    PageSpec("sentiment", "Research", "sentiment.py", "Sentiment overlay", ":material/newspaper:",
             "VADER tone of real dated headlines against LME, and the lead–lag tests.", ("5.2",)),
    PageSpec("reports", "Deliverables", "reports.py", "Reports & docs", ":material/description:",
             "Weekly desk notes, the post-mortem, the risk policy memo, the interview pack and the Excel workbook.",
             ("5.1", "5.3", "5.4", "8.2", "8.6")),
    PageSpec("data_assumptions", "Deliverables", "data_assumptions.py", "Data & assumptions", ":material/fact_check:",
             "The parameter register, series provenance, verification status and units.", ("8.1", "8.3", "8.4", "8.5")),
)
PAGE: dict[str, PageSpec] = {p.key: p for p in PAGES}


def navigation_pages() -> dict[str, list]:
    """st.navigation input: section -> [st.Page], in PAGES order (Overview is the default page)."""
    out: dict[str, list] = {}
    for p in PAGES:
        out.setdefault(p.section, []).append(
            st.Page(p.path, title=p.title, icon=p.icon, default=p.key == "overview",
                    url_path=None if p.key == "overview" else p.key))
    return out


def page_link(key: str, label: str | None = None) -> None:
    """Link to another page; plain text when the page runs standalone (no navigation registered)."""
    spec = PAGE[key]
    try:
        st.page_link(spec.path, label=label or spec.title, icon=spec.icon)
    except StreamlitAPIException:
        st.markdown(f"**{label or spec.title}**")


# ------------------------------------------------------------------------------------------------ banner and header
def sim_banner() -> None:
    """The simulation label, on every page."""
    st.markdown(
        f'<div role="note" style="border-left:4px solid #c55a11;background:#fbf1e9;padding:0.45rem 0.8rem;'
        f'border-radius:0.3rem;margin-bottom:0.6rem;font-size:0.92rem;color:#3a2a1a">'
        f"<strong>{SIM_LABEL}</strong> &nbsp;·&nbsp; Counterparties, vessels, banks, tickets and events are "
        "fictional (SIM). Market data is real where a public source exists, otherwise flagged PROXY or ASSUMPTION. "
        "Not investment advice.</div>",
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str | None = None, spec_rows: Sequence[str] = ()) -> None:
    """Title, one-line subtitle and the spec table rows the page delivers (from docs/INDEX.md, with any gap note)."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    if not spec_rows:
        return
    index = data.spec_index()
    with st.expander(f"Spec rows this page delivers: {', '.join(spec_rows)}"):
        if not index:
            missing_data(f"{data.DOCS}/INDEX.md")
            return
        lines = []
        for rid in spec_rows:
            row = index.get(rid)
            if row is None:
                lines.append(f"- **{rid}**: not in docs/INDEX.md")
                continue
            lines.append(f"- **{row.label}** {row.element} — {status_badge(row.status)}")
            for gap in row.gaps:
                lines.append(f"    - *Caveat:* {docs_text.for_streamlit(gap, data.DOCS + '/INDEX.md')}")
        st.markdown("\n".join(lines))
        st.caption("Source: `docs/INDEX.md` (MASTER_SPEC Tables 3–8 mapped to the files that deliver each row).")


def status_badge(status: str) -> str:
    s = status.upper()
    color = "green" if s.startswith("DONE") and "CAVEAT" not in s else "orange" if s.startswith("DONE") else "red"
    return f":{color}-badge[{status}]"


# ------------------------------------------------------------------------------------------------ flags and captions
FLAG_COLORS = {"DIRECT": "green", "PROXY": "orange", "ASSUMPTION": "violet", "SIM": "gray", "HYPOTHETICAL": "red",
               "SYNTHETIC": "blue", "SENSITIVITY": "gray"}


def flag_badge(flag: str) -> str:
    """Markdown badge for a provenance flag or label, usable inside st.markdown / st.caption text."""
    return f":{FLAG_COLORS.get(flag.upper(), 'gray')}-badge[{flag.upper()}]"


def source_caption(files: Sequence[str], flags: Mapping[str, str] | Sequence[str] | None = None,
                   note: str | None = None) -> None:
    """Caption under a chart or table: its source file(s), the flags that apply and an optional note.

    files  repo-relative paths ("outputs/tables/var_daily.csv"); bare table names are taken from outputs/tables/
    flags  {what: flag} ("MCX series": "PROXY") or a list of flags
    """
    shown = [f if "/" in f else data.table_rel(f.removesuffix(".csv")) for f in files]
    parts = ["Source: " + ", ".join(f"`{f}`" for f in shown)]
    if flags:
        items = flags.items() if isinstance(flags, Mapping) else [("", f) for f in flags]
        parts.append(" ".join(f"{flag_badge(fl)}{' ' + what if what else ''}" for what, fl in items))
    if note:
        parts.append(docs_text.escape_streamlit(note))
    st.caption(" · ".join(parts))


# ------------------------------------------------------------------------------------------------ missing data
def missing_data(rel: str, how_to_rebuild: str | None = None) -> None:
    """The single rendering of "this file is not in this copy" (an st.info with the rebuild instructions)."""
    st.info(f"**Not in this copy:** `{rel}`. {how_to_rebuild or data.rebuild_hint(rel)}", icon=":material/info:")


def available(*rels: str) -> bool:
    """True when every file exists; otherwise renders missing_data for each absent one and returns False."""
    absent = [r for r in rels if not data.exists(r)]
    for r in absent:
        missing_data(r)
    return not absent


@contextlib.contextmanager
def guard() -> Iterator[None]:
    """Run a block that calls data.require(...); a MissingData inside it becomes an st.info and the page goes on."""
    try:
        yield
    except data.MissingData as exc:
        missing_data(exc.rel, exc.how_to_rebuild)


# ------------------------------------------------------------------------------------------------ numbers
@dataclass(frozen=True)
class Kpi:
    label: str
    value: str
    help: str | None = None


def kpi_row(items: Sequence[Kpi | tuple[str, str] | tuple[str, str, str]]) -> None:
    """A row of st.metric tiles (wraps on narrow screens)."""
    kpis = [k if isinstance(k, Kpi) else Kpi(*k) for k in items]
    for col, k in zip(st.columns(len(kpis)), kpis):
        col.metric(k.label, k.value, help=k.help, border=True)


def inr_m(x: float, dp: int = 1, sign: bool = False) -> str:
    """₹ millions with a true minus sign, formatted exactly as the reports format them."""
    from desk.reporting.interview_pack import inr_m as f

    return f(x, dp, sign)


def num(x: float, dp: int = 0) -> str:
    from desk.reporting.interview_pack import num as f

    return f(x, dp)


def pct(frac: float, dp: int = 1, sign: bool = False) -> str:
    from desk.reporting.interview_pack import pct as f

    return f(frac, dp, sign)


def day(d, year: bool = False) -> str:
    from desk.reporting.interview_pack import day as f

    return f(d, year)


# ------------------------------------------------------------------------------------------------ the headline
BAND_TABLE = data.table_rel("pnl_sensitivity_sign_robustness")
ATTRIBUTION_TABLE = data.table_rel("attribution_daily")


def headline_band_ok(facts: data.Facts | None) -> bool:
    """True when the headline's band, break-even and sign-robustness flag are all computed (else nothing is shown)."""
    return (facts is not None and facts.has("book_pnl", "band_lo", "band_hi", "band_be")
            and "band_sign_robust" in facts.flags)


def pnl_band_note(facts: data.Facts | None) -> None:
    """One line under any other book-level P&L total on a page that already shows `pnl_headline`: the same band and
    sign-robustness statement, so a book total never stands without them. Renders nothing if the band is absent
    (callers withhold the book total in that case)."""
    if not headline_band_ok(facts):
        return
    t = facts.text
    anchor = t.get("anchor_key", "domestic_anchor_premium_inr_t")
    verdict = (":green-badge[Sign-robust within the band]" if facts.flags["band_sign_robust"]
               else ":orange-badge[Not sign-robust]")
    st.markdown(f"{verdict} Book totals read only with the headline's band: {t['band_lo']} to {t['band_hi']} to the "
                f"horizon across the registered `{anchor}` grid, break-even {t['band_be']} ₹/MT "
                f"(`{BAND_TABLE}`).")


def pnl_headline(facts: data.Facts | None) -> None:
    """The book's headline P&L with its anchor-premium band, break-even and sign-robustness statement.

    The only sanctioned rendering of the headline: if the band cannot be shown, neither is the value.
    """
    if not headline_band_ok(facts):
        absent = [r for r in (ATTRIBUTION_TABLE, BAND_TABLE, data.table_rel("trade_book")) if not data.exists(r)]
        for r in absent:
            missing_data(r)
        if not absent:
            st.info("The headline P&L is not shown: its sensitivity band could not be computed in this copy "
                    f"({'; '.join(facts.problems[:2]) if facts else 'no facts'}). Rebuild P3 and P6 with "
                    "`DESK_OFFLINE=1 .venv/bin/python run_all.py --from P3`.", icon=":material/info:")
        return
    t = facts.text
    robust = facts.flags["band_sign_robust"]
    anchor = t.get("anchor_key", "domestic_anchor_premium_inr_t")
    with st.container(border=True):
        st.markdown("##### Book P&L — read only with its band")
        c1, c2, c3 = st.columns([1.0, 1.35, 1.0])
        c1.metric(f"Book P&L to the horizon ({t.get('horizon_end', 'horizon')})", t["book_pnl"],
                  help=f"{t.get('book_pnl_mt', 'n/a')} per MT; {t.get('book_pnl_we', 'n/a')} at the window end "
                       f"({t.get('window_end', 'n/a')}).")
        c2.metric("Anchor-premium band", f"{t['band_lo']} to {t['band_hi']}",
                  help=f"Book P&L re-priced across the registered grid of `{anchor}`.")
        c3.metric("Break-even anchor premium", f"{t['band_be']} ₹/MT",
                  help="inside the registered grid" if facts.flags.get("band_be_inside") else
                  "outside the registered grid")
        flag = t.get("anchor_flag") or data.param_flag(anchor) or "ASSUMPTION"
        status = t.get("anchor_status") or data.param_verify_status(anchor) or "unknown"
        if robust:
            st.success(f"Sign-robust within the band: the book's P&L keeps its sign across the registered "
                       f"`{anchor}` grid ({flag}, verification {status}).")
        else:
            inside = "inside" if facts.flags.get("band_be_inside") else "outside"
            st.warning(f"**Not sign-robust.** Across the registered `{anchor}` grid ({flag}, verification {status}) "
                       f"the book's P&L runs from {t['band_lo']} to {t['band_hi']}, and the break-even "
                       f"({t['band_be']} ₹/MT) lies {inside} the grid. Read the headline only with this band.",
                       icon=":material/warning:")
        source_caption([ATTRIBUTION_TABLE, BAND_TABLE], {anchor: flag},
                       note="figures computed by desk.reporting.one_pager, the same code that writes one_pager.pdf")
    if not facts.complete:
        why = (("some inputs are not in this copy: " + ", ".join(f"`{m}`" for m in facts.missing)) if facts.missing
               else "the canonical computation could not run on these tables")
        st.caption(f"Computed on the partial path because {why}.")


# ------------------------------------------------------------------------------------------------ docs and downloads
def what_it_tells(doc_rel: str, heading: str = docs_text.WHAT_IT_TELLS, expanded: bool = False) -> None:
    """Expander quoting a doc section verbatim (links rewritten for the app)."""
    sec = docs_text.section(doc_rel, heading)
    if sec is None:
        if not data.exists(doc_rel):
            missing_data(doc_rel)
        else:
            st.info(f"`{doc_rel}` has no section headed “{heading}”.", icon=":material/info:")
        return
    label = heading if heading == docs_text.WHAT_IT_TELLS else sec.title
    with st.expander(label, expanded=expanded, icon=":material/menu_book:"):
        st.markdown(docs_text.for_streamlit(sec.body, doc_rel))
        where = f" §{sec.number}" if sec.number else ""
        st.caption(f"Quoted from `{doc_rel}`{where}, not rewritten for the app.")


_MIME = {"pdf": "application/pdf", "md": "text/markdown",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "csv": "text/csv",
         "json": "application/json", "png": "image/png"}


def download_button(rel: str, label: str | None = None, key: str | None = None, help: str | None = None) -> None:
    """Download a published file (PDF, MD, XLSX, CSV); an st.info when it is not in this copy."""
    blob = data.read_bytes(rel)
    if blob is None:
        missing_data(rel)
        return
    name = rel.rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1].lower()
    size = f"{len(blob) / 1024:,.0f} KB" if len(blob) < 1024 ** 2 else f"{len(blob) / 1024 ** 2:,.1f} MB"
    st.download_button(label or f"{name} ({size})", blob, file_name=name, mime=_MIME.get(ext, "application/octet-stream"),
                       key=key or f"dl:{rel}", help=help or f"`{rel}`", icon=":material/download:")


def recon_badge(summary: data.ReconSummary | None = None) -> str:
    s = summary or data.recon_status()
    color = {"VERIFIED": "green", "STALE": "orange", "NOT_RUN": "gray", "FAILED": "red"}.get(s.status, "gray")
    return f":{color}-badge[{s.status}]"


def sidebar_footer() -> None:
    """SIM label, Excel reconciliation status and the commit this copy was built from (entrypoint only)."""
    with st.sidebar:
        st.caption(f"**{SIM_LABEL}**")
        s = data.recon_status()
        detail = (f"{s.n_recalculated:,} formula cells recalculated outside Excel, {s.n_check_failures} failed checks"
                  if s.status == "VERIFIED" and s.n_recalculated is not None else s.reason)
        st.caption(f"Excel reconciliation {recon_badge(s)}  \n{docs_text.escape_streamlit(detail)}")
        st.caption(f"Commit `{data.git_commit()}` · read-only view of the published outputs")
