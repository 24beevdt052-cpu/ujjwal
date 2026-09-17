"""Reports & docs: the six weekly desk notes, the post-mortem, the risk policy memo, the interview pack, the one-pager,
the README, the Excel workbook with its reconciliation status, a browser over docs/ and the spec coverage map.

Every report is rendered from its published markdown in outputs/reports/ (charts from outputs/charts/), never
re-written, and offered as the published PDF / MD download. The book's headline P&L, which every report quotes, is
shown once at the top through `components.pnl_headline` with its band. The workbook is offered for download only; its
reconciliation figures are quoted only when `desk.excel.reconciliation_status` says VERIFIED. Markdown is rendered
with `st.markdown` (no raw HTML), links rewritten to repo paths by `docs_text.for_streamlit`.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import re  # noqa: E402
from dataclasses import dataclass  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.lib import components, data, docs_text  # noqa: E402
from app.lib.components import Kpi  # noqa: E402
from desk.excel import reconciliation_status as rs  # noqa: E402

R = data.REPORTS
POST_MORTEM = f"{R}/post_mortem"
RISK_MEMO = f"{R}/risk_policy_memo"
PACK = f"{R}/interview_pack"
ONE_PAGER = f"{R}/one_pager"
INDEX = f"{data.DOCS}/INDEX.md"
EXCEL_DOC = f"{data.DOCS}/35_excel_workbook.md"
NOTE_RE = re.compile(r"^desk_note_(\d+)_(\d{4}-\d{2}-\d{2})$")
Q_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)")
BOTTOM_RE = re.compile(r"\*\*Bottom line:\*\*\s*(.+?)\s*$")
LARGE_DOC_CHARS = 60_000

spec = components.PAGE["reports"]
components.sim_banner()
components.page_header(spec.title, spec.blurb, spec.spec_rows)


# ------------------------------------------------------------------------------------------------ markdown helpers
def _demote(md: str, by: int = 2) -> str:
    """Push headings down (# -> ###) so a report's H1 does not outrank the page title; fenced code untouched."""
    out, fenced = [], False
    for line in md.splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
        elif not fenced and re.match(r"^#{1,6}\s", line):
            line = "#" * min(6, len(line) - len(line.lstrip("#")) + by) + line.lstrip("#")
        out.append(line)
    return "\n".join(out)


def render_markdown(md: str, doc_rel: str, *, demote: int = 2) -> None:
    """Render repository markdown safely: text through docs_text.for_streamlit (no raw HTML, links as repo paths), and
    lines that hold only local images as st.image rows (the published PNGs), each with its source."""
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        buf.clear()
        if text:
            st.markdown(docs_text.for_streamlit(_demote(text, demote), doc_rel))

    fenced = False
    for line in md.splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
        imgs = [] if fenced else IMAGE_RE.findall(line)
        if imgs and not IMAGE_RE.sub("", line).strip():
            flush()
            cols = st.columns(len(imgs))
            for col, (alt, target) in zip(cols, imgs):
                rel = None if target.startswith(("http://", "https://")) else data.rel_join(doc_rel, target)
                with col:
                    if rel and data.exists(rel) and rel.lower().endswith((".png", ".jpg", ".jpeg")):
                        st.image(str(data.path(rel)), width="stretch" if len(imgs) > 1 else 680)
                        components.source_caption([rel], ["SIM"], note=alt or None)
                    elif rel:
                        components.missing_data(rel)
            continue
        buf.append(line)
    flush()


@dataclass(frozen=True)
class DocSection:
    title: str
    body: str


def split_sections(md: str, level: int = 2) -> list[DocSection]:
    """The document cut at its level-`level` headings; text before the first one is "Introduction"."""
    lines = md.splitlines()
    cuts = [(i, text) for i, lv, text in docs_text.headings(md) if lv == level]
    out: list[DocSection] = []
    first = cuts[0][0] if cuts else len(lines)
    intro = "\n".join(lines[:first]).strip()
    if intro:
        out.append(DocSection("Introduction", intro))
    for n, (i, text) in enumerate(cuts):
        end = cuts[n + 1][0] if n + 1 < len(cuts) else len(lines)
        out.append(DocSection(text, "\n".join(lines[i:end]).strip()))
    return out


def doc_viewer(rel: str, key: str) -> None:
    """A markdown file with a section picker (large files open on their first section) and its download."""
    md = data.doc_markdown(rel)
    if md is None:
        components.missing_data(rel)
        return
    sections = split_sections(md)
    names = ["Whole document", *[s.title for s in sections]]
    large = len(md) > LARGE_DOC_CHARS and len(sections) > 1
    c1, c2 = st.columns([3, 1])
    pick = c1.selectbox("Section", names, index=1 if large else 0, key=f"{key}:section:{rel}",
                        help="Large documents open on their first section.")
    with c2:
        components.download_button(rel, "Download (MD)", key=f"{key}:dl:{rel}")
    if large and pick != "Whole document":
        st.caption(f"`{rel}` is {len(md) / 1000:,.0f} KB; choose “Whole document” to render all of it.")
    body = md if pick == "Whole document" else next(s.body for s in sections if s.title == pick)
    with st.container(border=True):
        render_markdown(body, rel, demote=1)
    st.caption(f"Rendered from `{rel}` as published; links point at repository paths.")


def report_block(stem: str, key: str, label: str) -> None:
    """Downloads for <stem>.pdf and <stem>.md, then the rendered markdown."""
    md_rel, pdf_rel = f"{stem}.md", f"{stem}.pdf"
    c1, c2, _ = st.columns([1, 1, 2])
    with c1:
        components.download_button(pdf_rel, f"{label} (PDF)", key=f"{key}:pdf")
    with c2:
        components.download_button(md_rel, f"{label} (MD)", key=f"{key}:md")
    md = data.doc_markdown(md_rel)
    if md is None:
        return
    with st.container(border=True):
        render_markdown(md, md_rel)
    st.caption(f"Rendered from `{md_rel}`, generated by `desk/reporting/` from the published tables; the PDF is the "
               "same text through the report renderer.")


@st.cache_data(show_spinner=False, max_entries=4)
def recon_detail(recon_abs: str, wb_abs: str, stamps: tuple) -> dict:
    s = rs.status(recon_path=Path(recon_abs), workbook_path=Path(wb_abs))
    rep = dict(s.report) if s.report is not None else {}
    return {"status": s.status, "reason": s.reason, "verified": s.verified, "how": s.how_to_verify(),
            "n_recalculated": s.n_recalculated, "n_check_cells": s.n_check_cells,
            "n_check_failures": s.n_check_failures, "n_errors": s.n_errors, "scoreboard": s.scoreboard,
            "hash_source": s.hash_source, "workbook_sha256": s.workbook_sha256, "recorded_sha256": s.recorded_sha256,
            "seconds": rep.get("seconds"), "scope_note": rep.get("scope_note"),
            "families": rep.get("families") if isinstance(rep.get("families"), dict) else {},
            "sheets": rep.get("sheets") if isinstance(rep.get("sheets"), dict) else {}}


# ------------------------------------------------------------------------------------------------ inventories
files = data.report_files()
notes = sorted({(int(m.group(1)), m.group(2), f.name) for f in files if f.ext == "md"
                for m in [NOTE_RE.match(f.name)] if m})
n_pdfs = sum(1 for f in files if f.ext == "pdf")


@dataclass(frozen=True)
class PackQuestion:
    number: int
    question: str
    topic: str
    body: str


def parse_pack(md: str) -> tuple[str, list[PackQuestion], str]:
    """(preamble, the numbered questions, the closing section) of interview_pack.md."""
    sections = split_sections(md)
    pre = next((s.body for s in sections if s.title == "Introduction"), "")
    pre = "\n".join(line for line in pre.splitlines() if not line.startswith("# ")).strip()
    qs, tail = [], ""
    for s in sections:
        m = Q_RE.match(s.body.splitlines()[0]) if s.title != "Introduction" else None
        if m:
            rest = s.body.splitlines()[1:]
            body_lines = [x for x in rest]
            topic = ""
            for i, x in enumerate(body_lines):
                if x.strip():
                    if x.strip().startswith("*") and x.strip().endswith("*") and not x.strip().startswith("**"):
                        topic = x.strip().strip("*")
                        body_lines = body_lines[:i] + body_lines[i + 1:]
                    break
            qs.append(PackQuestion(int(m.group(1)), m.group(2), topic, "\n".join(body_lines).strip()))
        elif s.title != "Introduction":
            tail = s.body
    return pre, qs, tail


pack_md = data.doc_markdown(f"{PACK}.md")
pack = parse_pack(pack_md) if pack_md is not None else None
facts = data.headline_facts()
recon = data.recon_status()

# ------------------------------------------------------------------------------------------------ takeaway
st.subheader("The takeaway")
n_q = len(pack[1]) if pack else 0
st.markdown(
    f"**{len(notes)} weekly desk notes, a post-mortem on the best trade, a risk policy memo, a {n_q}-question "
    "interview pack and a one-pager, all generated by code from the published tables.** Each report that quotes the "
    "book's P&L quotes it with its anchor-premium band, as here:")
components.pnl_headline(facts)
if facts.failed_claims:
    st.error("These tables no longer support some of the reports' claims: " + "; ".join(facts.failed_claims)
             + ". Rebuild P6 (`DESK_OFFLINE=1 .venv/bin/python run_all.py --only P6`) before quoting the reports.",
             icon=":material/error:")

def status_group(status: str) -> str:
    """DONE / DONE, with a caveat / PARTIAL: the grouping components.status_badge colours by."""
    s = status.upper()
    return ("DONE" if "CAVEAT" not in s else "DONE, with a caveat") if s.startswith("DONE") else status


index = data.spec_index()
spec_counts = (pd.Series([status_group(r.status) for r in index.values()]).value_counts() if index
               else pd.Series(dtype=int))
components.kpi_row([
    Kpi("Weekly desk notes", f"{len(notes)}", "the last Friday of each window month, as of that close"),
    Kpi("Reports as PDF", f"{n_pdfs}", f"in `{R}/`"),
    Kpi("Interview questions", f"{n_q}", "15 written for the pack plus the spec's two named questions"),
    Kpi("Excel reconciliation", recon.status, docs_text.escape_streamlit(recon.reason)),
    Kpi("Spec rows DONE", f"{sum(v for k, v in spec_counts.items() if k.upper().startswith('DONE'))} of {len(index)}",
        ", ".join(f"{v} {k}" for k, v in spec_counts.items()) or "docs/INDEX.md not in this copy"),
])
components.source_caption([f"{R}/", data.RECON_JSON, INDEX], ["SIM"],
                          note="counts of the published files; reconciliation status from "
                               "desk.excel.reconciliation_status")

tabs = st.tabs(["Desk notes", "Post-mortem", "Risk memo", "Interview pack", "One-pager", "README", "Excel workbook",
                "Docs browser", "Spec coverage"])

# ------------------------------------------------------------------------------------------------ desk notes
with tabs[0]:
    if not notes:
        components.missing_data(f"{R}/desk_note_1_2022-03-25.md",
                                "The six weekly desk notes are written by Phase 6: "
                                "`DESK_OFFLINE=1 .venv/bin/python run_all.py --only P6`.")
    else:
        labels = {name: f"Note {n} — week ending {components.day(d, year=True)}" for n, d, name in notes}
        rows = []
        for n, d, name in notes:
            md = data.doc_markdown(f"{R}/{name}.md") or ""
            hit = next((BOTTOM_RE.search(line) for line in md.splitlines() if BOTTOM_RE.search(line)), None)
            rows.append({"note": n, "week ending": d, "bottom line": hit.group(1) if hit else ""})
        with st.expander("All six bottom lines at a glance", icon=":material/summarize:", expanded=False):
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                         column_config={"bottom line": st.column_config.TextColumn(width="large")})
            components.source_caption([f"{R}/desk_note_<n>_<week_end>.md"], ["SIM"],
                                      note="the “Bottom line” sentence of each note, verbatim")
        chosen = st.selectbox("Desk note", [name for _, _, name in notes], format_func=labels.get,
                              key="rep_note")
        st.caption("Written as of the week's close: prices, positions, trades and events are point-in-time; the "
                   "anchor premium, grade factors, freight levels and the INR 3M rate are later reconstructions, "
                   "footnoted in every note.")
        report_block(f"{R}/{chosen}", key=f"rep_note:{chosen}", label=labels[chosen].split(" — ")[0])
        components.source_caption([f"{R}/{chosen}.md"],
                                  {"counterparties, tickets": "SIM", "MCX series": "PROXY",
                                   "anchor premium": data.param_flag("domestic_anchor_premium_inr_t") or "ASSUMPTION",
                                   "credit bands (synthetic-data model)": "SYNTHETIC"})

# ------------------------------------------------------------------------------------------------ post-mortem
with tabs[1]:
    st.caption("The two-page post-mortem on the best trade by the worst P&L across the registered re-pricing cases.")
    report_block(POST_MORTEM, key="rep_pm", label="Post-mortem")
    components.source_caption([f"{POST_MORTEM}.md", data.table_rel("pnl_sensitivity_pricing")],
                              {"tickets": "SIM", "anchor premium": data.param_flag("domestic_anchor_premium_inr_t")
                               or "ASSUMPTION", "MCX series": "PROXY"})

# ------------------------------------------------------------------------------------------------ risk memo
with tabs[2]:
    st.caption("One page: limits for the next book, each set against what the 2022 book actually did.")
    report_block(RISK_MEMO, key="rep_memo", label="Risk policy memo")
    components.source_caption([f"{RISK_MEMO}.md"],
                              {"BIS-QCO hold": "HYPOTHETICAL", "credit PDs": "SYNTHETIC", "MCX series": "PROXY",
                               "facility sizes": data.param_flag("liq_fb_wc_limit_inr") or "ASSUMPTION"})

# ------------------------------------------------------------------------------------------------ interview pack
with tabs[3]:
    c1, c2, _ = st.columns([1, 1, 2])
    with c1:
        components.download_button(f"{PACK}.pdf", "Interview pack (PDF)", key="rep_pack:pdf")
    with c2:
        components.download_button(f"{PACK}.md", "Interview pack (MD)", key="rep_pack:md")
    if pack is not None:
        pre, questions, _tail = pack
        try:
            from desk.reporting import interview_pack as ip

            expected, named = ip.N_QUESTIONS, set(ip.REQUIRED_QUESTIONS)
        except ImportError:
            expected, named = None, set()
        if expected is not None and len(questions) != expected:
            st.warning(f"`{PACK}.md` holds {len(questions)} numbered questions; the pack is built for {expected}. "
                       "Rebuild P6.", icon=":material/warning:")
        with st.expander("How to read the pack (its own preamble)", icon=":material/menu_book:"):
            render_markdown(pre, f"{PACK}.md", demote=2)
        mode = st.radio("View", ["One question", f"All {len(questions)} as an accordion"], horizontal=True,
                        key="rep_pack_mode")

        def show_question(q: PackQuestion) -> None:
            tag = " · :blue-badge[named in the spec]" if q.question in named else ""
            st.caption(f"Q{q.number} · {docs_text.escape_streamlit(q.topic)}{tag}")
            render_markdown(q.body, f"{PACK}.md", demote=2)

        if mode == "One question":
            by_label = {f"Q{q.number}. {q.question}": q for q in questions}
            pick = st.selectbox("Question", list(by_label), key="rep_pack_q")
            with st.container(border=True):
                st.markdown(f"#### {docs_text.escape_streamlit(pick)}")
                show_question(by_label[pick])
        else:
            needle = st.text_input("Filter questions and answers", key="rep_pack_filter",
                                   placeholder="e.g. basis, LC, GARCH, T08")
            hits = [q for q in questions if not needle.strip() or needle.strip().lower() in
                    f"{q.question} {q.topic} {q.body}".lower()]
            st.caption(f"{len(hits)} of {len(questions)} questions match.")
            for q in hits:
                with st.expander(f"Q{q.number}. {q.question}"):
                    show_question(q)
        components.source_caption([f"{PACK}.md"], {"tickets, counterparties": "SIM", "MCX, USD/INR": "PROXY",
                                                    "credit model": "SYNTHETIC"},
                                  note="every number filled from the published tables by "
                                       "desk/reporting/interview_pack.py; each answer names its sources")
        components.what_it_tells(f"{PACK}.md", heading="What this pack does and doesn't tell you")

# ------------------------------------------------------------------------------------------------ one-pager
with tabs[4]:
    report_block(ONE_PAGER, key="rep_one", label="One-pager")
    components.source_caption([f"{ONE_PAGER}.md"], {"tickets": "SIM", "MCX proxy": "PROXY",
                                                    "BIS-QCO hold": "HYPOTHETICAL", "credit model": "SYNTHETIC"})

# ------------------------------------------------------------------------------------------------ README
with tabs[5]:
    st.caption("The repository README (spec row 5.4): folder structure, pipeline, re-run steps, verification "
               "checklist and “Why these quant methods”.")
    doc_viewer("README.md", key="rep_readme")

# ------------------------------------------------------------------------------------------------ Excel workbook
with tabs[6]:
    stamps = tuple(data.path(r).stat().st_mtime if data.exists(r) else None for r in (data.RECON_JSON, data.WORKBOOK))
    d = recon_detail(str(data.path(data.RECON_JSON)), str(data.path(data.WORKBOOK)), stamps)
    c1, c2 = st.columns([1, 2])
    with c1:
        components.download_button(data.WORKBOOK, "Metals_Desk_Master.xlsx", key="rep_xlsx")
    c2.markdown(f"Reconciliation {components.recon_badge()} {docs_text.escape_streamlit(d['reason'])}")
    if d["verified"]:
        components.kpi_row([
            Kpi("Formula cells recalculated", f"{d['n_recalculated']:,}", d["scope_note"]),
            Kpi("Check cells", f"{d['n_check_cells']:,}" if d["n_check_cells"] is not None else "n/a"),
            Kpi("Failed checks", f"{d['n_check_failures']}"),
            Kpi("Formula errors", f"{d['n_errors']}"),
            Kpi("Workbook hash", "matches the record",
                f"sha256 {str(d['workbook_sha256'])[:12]}…; {d['hash_source'] or 'hash source not recorded'}"),
        ])
        if d["families"]:
            fam = pd.DataFrame([{"check family": k, **v} for k, v in d["families"].items()])
            st.dataframe(fam, hide_index=True, width="stretch", column_config={
                "max_abs_diff": st.column_config.NumberColumn("largest |Excel − Python|", format="%.4g")})
        if d["sheets"]:
            sh = pd.DataFrame([{"sheet": k, **v} for k, v in d["sheets"].items()])
            st.dataframe(sh, hide_index=True, width="stretch", column_config={
                "formula": st.column_config.NumberColumn("formula cells", format="%,d"),
                "constant": st.column_config.NumberColumn("constant cells", format="%,d"),
                "ratio": st.column_config.ProgressColumn("formula share", format="percent", min_value=0,
                                                         max_value=1)})
        components.source_caption([data.RECON_JSON, data.WORKBOOK], ["SIM"],
                                  note="the record of the last full recalculation outside Excel, tied to this "
                                       "workbook by its SHA-256")
    else:
        st.warning(f"No reconciliation figures are quoted: the status is {d['status']}. "
                   f"{docs_text.escape_streamlit(d['how'])}", icon=":material/warning:")
        components.source_caption([data.RECON_JSON], None,
                                  note="status from desk.excel.reconciliation_status.status()")
    components.what_it_tells(EXCEL_DOC)
    components.what_it_tells(EXCEL_DOC, heading="Sheet by sheet")

# ------------------------------------------------------------------------------------------------ docs browser
with tabs[7]:
    docs_dir = data.path(data.DOCS)
    doc_rels = sorted(p.relative_to(data.ROOT).as_posix() for p in docs_dir.rglob("*.md")) if docs_dir.is_dir() else []
    options = [r for r in ("CONTRACTS.md",) if data.exists(r)] + doc_rels
    if not options:
        components.missing_data(f"{data.DOCS}/INDEX.md")
    else:
        def doc_label(rel: str) -> str:
            md = data.doc_markdown(rel) or ""
            h1 = next((text for _, lv, text in docs_text.headings(md) if lv == 1), "")
            return f"{rel} — {h1}" if h1 else rel

        folders = ["All", *sorted({r.split("/")[1] if r.count("/") >= 2 else "docs" if r.startswith("docs/")
                                   else "repository root" for r in options})]
        c1, c2 = st.columns([1, 3])
        folder = c1.selectbox("Folder", folders, key="rep_doc_folder")
        shown = [r for r in options if folder == "All"
                 or (folder == "repository root" and "/" not in r)
                 or (folder == "docs" and r.count("/") == 1)
                 or (r.count("/") >= 2 and r.split("/")[1] == folder)]
        default = options.index(INDEX) if INDEX in shown else 0
        doc = c2.selectbox("Document", shown, index=min(default, len(shown) - 1) if folder == "All" else 0,
                           format_func=doc_label, key=f"rep_doc:{folder}")
        doc_viewer(doc, key="rep_docs")

# ------------------------------------------------------------------------------------------------ spec coverage
with tabs[8]:
    if not index:
        components.missing_data(INDEX)
    else:
        page_of = {r: p.title for p in components.PAGES for r in p.spec_rows}

        def plain_links(md: str) -> str:
            out = LINK_RE.sub(lambda m: data.rel_join(INDEX, m.group(2).split("#")[0]) or m.group(1), md)
            return out.replace("`", "")

        cov = pd.DataFrame([{"row": r.label, "table": r.table.split(":")[0], "element": r.element,
                             "group": status_group(r.status), "status": r.status,
                             "caveat": " · ".join(plain_links(g) for g in r.gaps),
                             "delivered by": plain_links(r.delivered_by),
                             "dashboard page": page_of.get(r.row, "")} for r in index.values()])
        c1, c2 = st.columns(2)
        statuses = c1.multiselect("Status", list(cov["group"].value_counts().index), key="rep_spec_status",
                                  placeholder="All statuses")
        tables = ["All tables", *list(dict.fromkeys(cov["table"]))]
        table = c2.selectbox("Spec table", tables, key="rep_spec_table")
        view = cov
        if statuses:
            view = view[view["group"].isin(statuses)]
        if table != "All tables":
            view = view[view["table"] == table]
        counts = cov["group"].value_counts()
        components.kpi_row([Kpi(k, f"{v}") for k, v in counts.items()]
                           + [Kpi("Rows shown", f"{len(view)} of {len(cov)}")])

        def tint(row: pd.Series) -> list[str]:
            color = {"DONE": "", "DONE, with a caveat": "background-color: #fff4e5"}.get(
                row["group"], "background-color: #fde8e8")
            return [color] * len(row)

        st.dataframe(view.style.apply(tint, axis=1), hide_index=True, width="stretch", height=420, column_order=[
            "row", "table", "element", "status", "caveat", "delivered by", "dashboard page"], column_config={
            "element": st.column_config.TextColumn(width="medium"),
            "caveat": st.column_config.TextColumn(width="large"),
            "delivered by": st.column_config.TextColumn(width="large")})
        components.source_caption([INDEX], None,
                                  note="MASTER_SPEC Tables 3–8 mapped to the files that deliver each row; rows with a "
                                       "caveat are tinted amber, PARTIAL rows red; the dashboard page column is this "
                                       "app's own page registry")
        gaps = docs_text.section(INDEX, "Gaps and flags at a glance")
        if gaps is not None:
            with st.expander("Gaps and flags at a glance (quoted)", icon=":material/flag:"):
                st.markdown(docs_text.for_streamlit(gaps.body, INDEX))
                st.caption(f"Quoted from `{INDEX}`, not rewritten for the app.")
