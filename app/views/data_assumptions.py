"""Data & assumptions: the parameter register, series provenance and the data dictionary, the verification log, each
model's "What this does and doesn't tell you", the download manifest, the public-export policy and the review logs.

The register is `desk.config.params_frame()` (via `data.params_register()`); its verification status is the leading
word of the `verify` field, extracted the way `desk/reporting/interview_pack.py` does it. The verification log's
tables are parsed from docs/verification_log.md as written. The download manifest is summarised by folder, host,
retrieval date and method only: no raw file is listed or opened. The export policy's manifest breakdown uses the
exporter's own classifier (`tools/export_public.py`), so it cannot drift from what an export would do.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json  # noqa: E402
import re  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.lib import charts, components, data, docs_text  # noqa: E402
from app.lib.components import Kpi  # noqa: E402
from desk.reporting.style import PALETTE  # noqa: E402

PARAMS_GLOB = f"{data.PARAMS}/*.yaml"
PROV = data.processed_rel("series_provenance")
DICTIONARY = f"{data.DOCS}/00_data_dictionary.md"
ASSUMPTIONS_LOG = f"{data.DOCS}/00_assumptions_log.md"
VERIFICATION = f"{data.DOCS}/verification_log.md"
CONTRACTS = "CONTRACTS.md"
MANIFEST = "data/raw/_download_manifest.json"
POLICY = "tools/public_export_policy.yaml"
REVIEWS = f"{data.DOCS}/reviews"
FINDINGS = f"{REVIEWS}/phase1-3_review_findings.json"
ANCHOR = "domestic_anchor_premium_inr_t"
LARGE_DOC_CHARS = 60_000
FLAGS = ("DIRECT", "PROXY", "ASSUMPTION")
FLAG_COLORS = {"DIRECT": PALETTE["gain"], "PROXY": PALETTE["mcx"], "ASSUMPTION": "#6f42c1"}
STATUS_ORDER = ("VERIFIED", "PARTIAL", "PENDING", "N/A")
STATUS_COLORS = {"VERIFIED": PALETTE["gain"], "PARTIAL": "#d4a017", "PENDING": PALETTE["loss"],
                 "N/A": PALETTE["neutral"]}
PENDING_BG = "background-color: #fde8e8"
PARTIAL_BG = "background-color: #fff4e5"
MODEL_DOCS = (   # docs/INDEX.md row 8.5: every quant model's plain-English section
    (f"{data.DOCS}/10_parity_model.md", "Import parity model", docs_text.WHAT_IT_TELLS),
    (f"{data.DOCS}/20_trade_book.md", "Trade book", docs_text.WHAT_IT_TELLS),
    (f"{data.DOCS}/30_mtm_attribution.md", "MTM and P&L attribution", docs_text.WHAT_IT_TELLS),
    (f"{data.DOCS}/31_adverse_events.md", "Adverse events", docs_text.WHAT_IT_TELLS),
    (f"{data.DOCS}/35_excel_workbook.md", "Excel workbook", docs_text.WHAT_IT_TELLS),
    (f"{data.DOCS}/40_var_garch.md", "GARCH vs historical VaR", docs_text.WHAT_IT_TELLS),
    (f"{data.DOCS}/41_monte_carlo.md", "Monte Carlo VaR and stresses", docs_text.WHAT_IT_TELLS),
    (f"{data.DOCS}/50_credit_scoring.md", "Credit scoring (synthetic data)", docs_text.WHAT_IT_TELLS),
    (f"{data.DOCS}/51_margin_liquidity.md", "Margin and liquidity", docs_text.WHAT_IT_TELLS),
    (f"{data.DOCS}/70_sentiment_overlay.md", "Sentiment overlay", docs_text.WHAT_IT_TELLS),
    (f"{data.REPORTS}/interview_pack.md", "Interview pack", "What this pack does and doesn't tell you"),
)

spec = components.PAGE["data_assumptions"]
components.sim_banner()
components.page_header(spec.title, spec.blurb, spec.spec_rows)


# ------------------------------------------------------------------------------------------------ helpers
def verify_status(verify: pd.Series) -> pd.Series:
    """VERIFIED / PARTIAL / PENDING / N/A: the leading capitals of `verify` (desk/reporting/interview_pack.py)."""
    return verify.astype(str).str.extract(r"^\s*([A-Z/]+)")[0].fillna("unknown")


def plain(md: str) -> str:
    """A markdown table cell as plain text: emphasis and code marks dropped, links reduced to their text."""
    md = re.sub(r"(?<!!)\[([^\]]+)\]\([^)]+\)", r"\1", md)
    return md.replace("**", "").replace("`", "").strip()


def md_tables(body: str) -> list[pd.DataFrame]:
    """Every pipe table in a markdown block, as strings (escaped pipes kept inside their cell)."""
    out, cur = [], []
    for line in [*body.splitlines(), ""]:
        if line.strip().startswith("|"):
            cur.append(line)
            continue
        if len(cur) >= 2:
            rows = [[plain(c.replace("\x00", "|")) for c in r.replace("\\|", "\x00").strip().strip("|").split("|")]
                    for r in cur]
            header, body_rows = rows[0], [r for r in rows[1:] if not all(re.fullmatch(r":?-+:?", c) for c in r)]
            body_rows = [(r + [""] * len(header))[:len(header)] for r in body_rows]
            out.append(pd.DataFrame(body_rows, columns=header))
        cur = []
    return out


def split_sections(md: str, level: int = 2) -> list[tuple[str, str]]:
    """(title, markdown) per level-`level` heading; text before the first heading is "Introduction"."""
    lines = md.splitlines()
    cuts = [(i, text) for i, lv, text in docs_text.headings(md) if lv == level]
    first = cuts[0][0] if cuts else len(lines)
    out = [("Introduction", "\n".join(lines[:first]).strip())] if "\n".join(lines[:first]).strip() else []
    for n, (i, text) in enumerate(cuts):
        end = cuts[n + 1][0] if n + 1 < len(cuts) else len(lines)
        out.append((text, "\n".join(lines[i:end]).strip()))
    return out


def demote(md: str, by: int = 1) -> str:
    out, fenced = [], False
    for line in md.splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
        elif not fenced and re.match(r"^#{1,6}\s", line):
            line = "#" * min(6, len(line) - len(line.lstrip("#")) + by) + line.lstrip("#")
        out.append(line)
    return "\n".join(out)


def doc_viewer(rel: str, key: str, default_section: str | None = None) -> None:
    """A markdown file rendered safely (st.markdown, links as repo paths), with a section picker and its download."""
    md = data.doc_markdown(rel)
    if md is None:
        components.missing_data(rel)
        return
    sections = split_sections(md)
    names = ["Whole document", *[t for t, _ in sections]]
    large = len(md) > LARGE_DOC_CHARS and len(sections) > 1
    index = names.index(default_section) if default_section in names else (1 if large else 0)
    c1, c2 = st.columns([3, 1])
    pick = c1.selectbox("Section", names, index=index, key=f"{key}:section:{rel}")
    with c2:
        components.download_button(rel, "Download (MD)", key=f"{key}:dl:{rel}")
    body = md if pick == "Whole document" else dict(sections)[pick]
    with st.container(border=True):
        st.markdown(docs_text.for_streamlit(demote(body), rel))
    st.caption(f"Rendered from `{rel}` as published; links point at repository paths.")


def count_bars(counts: pd.Series, order: tuple[str, ...], colors: dict[str, str], title: str, key: str) -> None:
    labels = [k for k in order if k in counts.index] + [k for k in counts.index if k not in order]
    fig = charts.bar_chart(labels, [int(counts[k]) for k in labels], title=title,
                           colors=[colors.get(k, PALETTE["neutral"]) for k in labels],
                           text=[f"{int(counts[k]):,}" for k in labels], height=max(240, 44 * len(labels) + 110))
    charts.show(pad_bottom(fig, len(labels)), key=key)


def pad_bottom(fig: go.Figure, n: int) -> go.Figure:
    """Leave an empty band under the last horizontal bar, where the shared SIM watermark sits."""
    return fig.update_yaxes(range=[n - 0.5 + 0.9, -0.5], autorange=False)


@st.cache_data(show_spinner=False, max_entries=2)
def load_manifest(abs_path: str, mtime: float) -> pd.DataFrame:
    """One row per manifest entry, with only the fields a summary needs (no file names are shown)."""
    raw = json.loads(Path(abs_path).read_text(encoding="utf-8"))
    rows = []
    for key, rec in raw.items():
        rec = rec if isinstance(rec, dict) else {}
        url = str(rec.get("url") or "")
        rows.append({"key": key, "folder": key.split("/", 1)[0] if "/" in key else "(top level)",
                     "host": urlparse(url).netloc or "(no URL recorded)",
                     "how": str(rec.get("how") or "(not recorded)"),
                     "retrieved": str(rec.get("retrieved") or "")[:10], "bytes": int(rec.get("bytes") or 0)})
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False, max_entries=2)
def classify_manifest(policy_abs: str, stamp: tuple, keys: tuple[str, ...]) -> pd.DataFrame | None:
    """Each manifest key's policy entry through tools/export_public.py's own loader and classifier (None if the
    exporter is not importable in this copy)."""
    try:
        from tools import export_public as ex

        policy = ex.load_policy(Path(policy_abs))
    except (ImportError, AttributeError, KeyError, TypeError, ValueError, SystemExit):
        return None
    rows = []
    for k in keys:
        e = ex.classify_raw(ex.RAW_PREFIX + k, policy)
        rows.append({"key": k, "policy_id": e.id if e else "UNCLASSIFIED",
                     "category": e.category if e else "UNCLASSIFIED",
                     "exported": bool(e.export) if e else False, "certainty": e.certainty if e else ""})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------ takeaway
reg = data.params_register()
prov = data.series_provenance()

st.subheader("The takeaway")
if reg is None:
    components.missing_data(f"{data.PARAMS}/", "The register is the repository's `config/params/*.yaml`: restore "
                                                "it from the repository copy you cloned.")
else:
    reg = reg.assign(value=reg["value"].astype(str), verify_status=verify_status(reg["verify"]))
    flags = reg["flag"].value_counts()
    status = reg["verify_status"].value_counts()
    anchor_status = data.param_verify_status(ANCHOR)
    anchor_flag = data.param_flag(ANCHOR)
    anchor_clause = (f" One of them is `{ANCHOR}` ({anchor_flag}), the assumption the headline P&L is not sign-robust "
                     "to." if anchor_status == "PENDING" else "")
    st.markdown(
        f"**Every one of the {len(reg)} parameters carries a flag and a verification note: {flags.get('DIRECT', 0)} "
        f"DIRECT, {flags.get('PROXY', 0)} PROXY, {flags.get('ASSUMPTION', 0)} ASSUMPTION.** "
        f"{status.get('VERIFIED', 0)} are VERIFIED against a primary source, {status.get('PARTIAL', 0)} PARTIAL and "
        f"{status.get('PENDING', 0)} still PENDING, each with a stated next step; {status.get('N/A', 0)} are N/A "
        f"(desk policy or model design, which no public source can verify).{anchor_clause}")
    kpis = [Kpi("Parameters", f"{len(reg)}", f"in {reg['file'].nunique()} files under `{data.PARAMS}/`")]
    kpis += [Kpi(f, f"{flags.get(f, 0)}") for f in FLAGS]
    kpis += [Kpi("PENDING", f"{status.get('PENDING', 0)}",
                 f"parameters still PENDING verification; {status.get('VERIFIED', 0)} VERIFIED · "
                 f"{status.get('PARTIAL', 0)} PARTIAL · {status.get('N/A', 0)} N/A")]
    if prov is not None:
        pf = prov["flag"].value_counts()
        kpis.append(Kpi("Panel columns", f"{len(prov)}",
                        "columns of the daily market panel: " + " · ".join(f"{pf.get(f, 0)} {f}" for f in FLAGS)))
    components.kpi_row(kpis)
    components.source_caption([PARAMS_GLOB] + ([PROV] if prov is not None else []), list(FLAGS),
                              note="register loaded by desk.config.params_frame(); verification status is the "
                                   "leading word of each `verify` note")

tabs = st.tabs(["Parameter register", "Data dictionary & units", "Verification log", "What each model can't tell you",
                "Download manifest", "Public-export policy", "Review logs"])

# ------------------------------------------------------------------------------------------------ register
with tabs[0]:
    if reg is None:
        components.missing_data(f"{data.PARAMS}/", "Restore `config/params/*.yaml` from the repository copy.")
    else:
        c1, c2, c3 = st.columns([1.1, 1.2, 1.4])
        f_flag = c1.multiselect("Flag", list(FLAGS), key="da_flag", placeholder="All flags")
        f_status = c2.multiselect("Verification", [s for s in STATUS_ORDER if s in set(reg["verify_status"])],
                                  key="da_verify", placeholder="All statuses")
        f_file = c3.multiselect("File", sorted(reg["file"].unique()), key="da_file", placeholder="All files")
        c4, c5 = st.columns([3, 1])
        needle = c4.text_input("Search key, source, note or verification", key="da_search",
                               placeholder="e.g. freight, duty, anchor, MCX")
        pending_only = c5.toggle("PENDING only", value=False, key="da_pending")
        view = reg
        if f_flag:
            view = view[view["flag"].isin(f_flag)]
        if f_status:
            view = view[view["verify_status"].isin(f_status)]
        if f_file:
            view = view[view["file"].isin(f_file)]
        if pending_only:
            view = view[view["verify_status"] == "PENDING"]
        if needle.strip():
            hay = (view["key"] + " " + view["source"] + " " + view["note"] + " " + view["verify"]).str.lower()
            view = view[hay.str.contains(needle.strip().lower(), regex=False)]

        b1, b2 = st.columns(2)
        with b1:
            if view.empty:
                st.info("No parameter matches these filters.", icon=":material/filter_alt_off:")
            else:
                count_bars(view["flag"].value_counts(), FLAGS, FLAG_COLORS, "By provenance flag", "da_bars_flag")
        with b2:
            if not view.empty:
                count_bars(view["verify_status"].value_counts(), STATUS_ORDER, STATUS_COLORS, "By verification status",
                           "da_bars_status")
        components.source_caption([PARAMS_GLOB], list(FLAGS),
                                  note=f"{len(view)} of {len(reg)} parameters match the filters")

        def highlight(row: pd.Series) -> list[str]:
            bg = {"PENDING": PENDING_BG, "PARTIAL": PARTIAL_BG}.get(row["verify_status"], "")
            return [bg] * len(row)

        cols = ["key", "value", "unit", "flag", "verify_status", "verify", "source", "note", "file"]
        st.dataframe(view[cols].style.apply(highlight, axis=1), hide_index=True, width="stretch", height=420,
                     column_config={
                         "key": st.column_config.TextColumn("key", pinned=True),
                         "value": st.column_config.TextColumn("value (path: date: value; …)", width="medium"),
                         "verify_status": "status",
                         "verify": st.column_config.TextColumn("verification", width="large"),
                         "source": st.column_config.TextColumn(width="large"),
                         "note": st.column_config.TextColumn(width="large")})
        components.source_caption([PARAMS_GLOB], list(FLAGS),
                                  note="PENDING rows are tinted red and PARTIAL rows amber; values are shown as text "
                                       "(dated paths joined with “;”)")

        if not view.empty:
            pick = st.selectbox("Read one parameter in full", list(view["key"]),
                                index=list(view["key"]).index(ANCHOR) if ANCHOR in set(view["key"]) else 0,
                                key="da_param")
            row = view[view["key"] == pick].iloc[0]
            with st.container(border=True):
                badge = {"VERIFIED": "green", "PARTIAL": "orange", "PENDING": "red"}.get(row["verify_status"], "gray")
                st.markdown(f"**`{pick}`** {components.flag_badge(row['flag'])} · verification "
                            f":{badge}-badge[{row['verify_status']}] · `{data.PARAMS}/{row['file']}`")
                esc = docs_text.escape_streamlit
                st.markdown(f"**Value:** `{row['value']}` {esc(str(row['unit']))}"
                            + (f" (interpolation: {row['interp']})" if str(row.get("interp", "")) else ""))
                st.markdown(f"**Source:** {esc(str(row['source']))}")
                st.markdown(f"**Verification:** {esc(str(row['verify']))}")
                st.markdown(f"**Note:** {esc(str(row['note']))}")
                components.download_button(f"{data.PARAMS}/{row['file']}", f"{row['file']} (YAML)",
                                           key=f"da_yaml:{row['file']}")

        pend = reg[reg["verify_status"] == "PENDING"]
        with st.expander(f"The {len(pend)} PENDING parameters and their next step", icon=":material/pending_actions:"):
            st.dataframe(pend[["key", "flag", "file", "verify"]], hide_index=True, width="stretch",
                         column_config={"verify": st.column_config.TextColumn("verification and next step",
                                                                              width="large")})
            components.source_caption([PARAMS_GLOB], list(FLAGS))
        if data.exists(ASSUMPTIONS_LOG):
            st.caption(f"The same register rendered as a document: `{ASSUMPTIONS_LOG}` (Reports & docs → Docs "
                       "browser). Its Phase 4–7 keys lag the register until Phase 0 re-renders it (docs/INDEX.md, row "
                       "8.1).")

# ------------------------------------------------------------------------------------------------ dictionary and units
with tabs[1]:
    st.markdown("##### Series provenance: every column of the daily market panel")
    if prov is None:
        components.missing_data(PROV)
    else:
        c1, c2 = st.columns([1.2, 2])
        p_flag = c1.radio("Flag", ["All", *FLAGS], horizontal=True, key="da_prov_flag")
        p_search = c2.text_input("Search column, source or transformation", key="da_prov_search")
        pv = prov if p_flag == "All" else prov[prov["flag"] == p_flag]
        if p_search.strip():
            hay = (pv["column"] + " " + pv["source"].astype(str) + " " + pv["transformation"].astype(str)).str.lower()
            pv = pv[hay.str.contains(p_search.strip().lower(), regex=False)]
        st.dataframe(pv, hide_index=True, width="stretch", column_config={
            "column": st.column_config.TextColumn(pinned=True),
            "source": st.column_config.TextColumn(width="large"),
            "transformation": st.column_config.TextColumn(width="large")})
        components.source_caption([PROV], list(FLAGS),
                                  note=f"{len(pv)} of {len(prov)} columns; indicator and label columns carry the "
                                       "weakest flag of the series they qualify")
    if not data.exists(data.processed_rel("market_daily")):
        components.missing_data(data.processed_rel("market_daily"))

    st.markdown("##### Data dictionary")
    doc_viewer(DICTIONARY, key="da_dict", default_section="Files")

    st.markdown("##### Units (Table 8.3)")
    ground = docs_text.section(CONTRACTS, "Ground rules")
    item = None
    if ground is not None:
        lines = ground.body.splitlines()
        start = next((i for i, x in enumerate(lines) if x.lstrip().startswith("3. **Units**")), None)
        if start is not None:
            block = [lines[start]]
            for x in lines[start + 1:]:
                if re.match(r"^\d+\.\s", x) or not x.strip():
                    break
                block.append(x)
            item = "\n".join(block)
    if item is None:
        components.available(CONTRACTS)
    else:
        with st.container(border=True):
            st.markdown(docs_text.for_streamlit(item, CONTRACTS))
            st.caption(f"Quoted from `{CONTRACTS}` §1 (ground rule 3), not rewritten for the app; conversions live in "
                       "`desk/units.py`.")

# ------------------------------------------------------------------------------------------------ verification log
with tabs[2]:
    md = data.doc_markdown(VERIFICATION)
    if md is None:
        components.missing_data(VERIFICATION)
    else:
        sections = split_sections(md)
        frames = []
        for title, body in sections:
            for t in md_tables(body):
                if "Status" in t.columns and "Parameter" in t.columns:
                    frames.append(t.assign(section=title))
        intro = dict(sections).get("Introduction", "")
        rules = next((b for b in re.split(r"\n\s*\n", intro) if b.startswith("Status rules")), None)
        if frames:
            log = pd.concat(frames, ignore_index=True)
            log["status_word"] = log["Status"].str.extract(r"^\s*([A-Z/]+)")[0].fillna("—")
            counts = log["status_word"].value_counts()
            components.kpi_row([Kpi("Rows in the log", f"{len(log)}",
                                    f"{len(frames)} status tables: " + "; ".join(dict.fromkeys(log["section"])))]
                               + [Kpi(f"{s} rows", f"{counts.get(s, 0)}") for s in ("VERIFIED", "PARTIAL", "PENDING")])
            c1, c2 = st.columns(2)
            v_status = c1.multiselect("Status", [s for s in ("VERIFIED", "PARTIAL", "PENDING") if s in counts.index],
                                      key="da_ver_status", placeholder="All statuses")
            v_section = c2.selectbox("Section", ["All sections", *dict.fromkeys(log["section"])], key="da_ver_section")
            lv = log
            if v_status:
                lv = lv[lv["status_word"].isin(v_status)]
            if v_section != "All sections":
                lv = lv[lv["section"] == v_section]

            def tint(row: pd.Series) -> list[str]:
                bg = {"PENDING": PENDING_BG, "PARTIAL": PARTIAL_BG}.get(row["status_word"], "")
                return [bg] * len(row)

            shown = [c for c in ["Parameter", "Value used", "Authoritative source", "Inputs checked",
                                 "What was checked", "Date checked", "Status", "Next step", "section", "status_word"]
                     if c in lv.columns]
            st.dataframe(lv[shown].style.apply(tint, axis=1), hide_index=True, width="stretch", height=420,
                         column_order=[c for c in shown if c != "status_word"], column_config={
                             "Parameter": st.column_config.TextColumn(pinned=True, width="medium"),
                             "Authoritative source": st.column_config.TextColumn(width="large"),
                             "What was checked": st.column_config.TextColumn(width="large"),
                             "Inputs checked": st.column_config.TextColumn(width="large"),
                             "Next step": st.column_config.TextColumn(width="large")})
            components.source_caption([VERIFICATION], None,
                                      note=f"{len(lv)} of {len(log)} rows; tables parsed from the log as written "
                                           "(PENDING tinted red, PARTIAL amber)")
        else:
            st.info(f"`{VERIFICATION}` has no status tables in the expected shape; read it below.",
                    icon=":material/info:")
        if rules:
            with st.expander("What VERIFIED, PARTIAL and PENDING mean here (quoted)", icon=":material/menu_book:"):
                st.markdown(docs_text.for_streamlit(rules, VERIFICATION))
                st.caption(f"Quoted from `{VERIFICATION}`, not rewritten for the app.")
        with st.expander("Read the log as written", icon=":material/article:"):
            doc_viewer(VERIFICATION, key="da_verlog")

# ------------------------------------------------------------------------------------------------ 8.5
with tabs[3]:
    st.caption("Every quant model ships a plain-English “What this does and doesn't tell you” section (spec Table "
               "8.5). Each is quoted from its doc, not rewritten.")
    labels = {doc: label for doc, label, _ in MODEL_DOCS}
    mode = st.radio("Show", ["One model", "All models"], horizontal=True, key="da_model_mode")
    if mode == "One model":
        doc = st.selectbox("Model", [d for d, _, _ in MODEL_DOCS], format_func=labels.get, key="da_model_doc",
                           index=2)
        heading = next(h for d, _, h in MODEL_DOCS if d == doc)
        components.what_it_tells(doc, heading=heading, expanded=True)
        st.caption(f"From `{doc}`.")
    else:
        for doc, label, heading in MODEL_DOCS:
            st.markdown(f"**{label}** · `{doc}`")
            components.what_it_tells(doc, heading=heading)

# ------------------------------------------------------------------------------------------------ download manifest
with tabs[4]:
    mtime = data.path(MANIFEST).stat().st_mtime if data.exists(MANIFEST) else None
    if mtime is None:
        components.missing_data(MANIFEST, "It is written by every Phase 0 fetcher (`desk/data/_http.py`) and kept in "
                                          "the public export; rebuild it by running the Phase 0 fetchers "
                                          "(`.venv/bin/python run_all.py --only P0`).")
        man = None
    else:
        man = load_manifest(str(data.path(MANIFEST)), mtime)
        dates = man.loc[man["retrieved"] != "", "retrieved"]
        components.kpi_row([
            Kpi("Manifest entries", f"{len(man):,}", "cached downloads, each recorded with URL, retrieval date, "
                                                     "sha256 and size"),
            Kpi("Total size", f"{man['bytes'].sum() / 1024 ** 2:,.1f} MB"),
            Kpi("Source hosts", f"{man.loc[man['host'] != '(no URL recorded)', 'host'].nunique():,}"),
            Kpi("Retrieved", "not recorded" if dates.empty else dates.min() if dates.min() == dates.max()
                else f"{dates.min()[5:]} → {dates.max()[5:]}",
                "not recorded" if dates.empty else f"{dates.min()} to {dates.max()}, on {dates.nunique()} distinct "
                                                   "day(s)"),
            Kpi("Entries without a URL", f"{int((man['host'] == '(no URL recorded)').sum()):,}",
                "files cached before the manifest existed (back-filled from file times)"),
        ])
        folders = st.multiselect("Folder under data/raw/", list(man["folder"].value_counts().index),
                                 key="da_man_folder", placeholder="All folders")
        mv = man[man["folder"].isin(folders)] if folders else man
        c1, c2 = st.columns(2)
        with c1:
            by_folder = mv.groupby("folder").agg(files=("key", "size"), mb=("bytes", lambda b: b.sum() / 1024 ** 2))
            by_folder = by_folder.sort_values("files", ascending=False)
            fig = charts.bar_chart(list(by_folder.index), list(by_folder["files"]), title="Entries by folder",
                                   text=[f"{n:,} · {m:,.1f} MB" for n, m in zip(by_folder["files"], by_folder["mb"])])
            charts.show(pad_bottom(fig, len(by_folder)), key="da_man_folders")
        with c2:
            top = mv["host"].value_counts().head(12)
            fig = charts.bar_chart(list(top.index), list(top.values), title="Entries by source host (top 12)",
                                   colors=PALETTE["fx"], text=[f"{v:,}" for v in top.values])
            charts.show(pad_bottom(fig, len(top)), key="da_man_hosts")
        by_day = mv[mv["retrieved"] != ""].groupby("retrieved").size()
        how = mv["how"].value_counts()
        c3, c4 = st.columns([2, 1])
        with c3:
            fig = go.Figure(go.Bar(x=list(by_day.index), y=list(by_day.values), marker_color=PALETTE["lme"],
                                   hovertemplate="%{x}: %{y} entries<extra></extra>"))
            charts.finish(fig, title="Entries by retrieval date", height=300, legend=False, y_title="entries")
            fig.update_xaxes(type="category")
            charts.show(fig, key="da_man_days")
        with c4:
            st.dataframe(how.rename_axis("how recorded").reset_index(name="entries"), hide_index=True,
                         width="stretch")
        components.source_caption([MANIFEST], None,
                                  note="counts only: file names and file contents are not listed; the manifest is "
                                       "what lets anyone re-fetch and check each cached source byte for byte")

# ------------------------------------------------------------------------------------------------ public export policy
with tabs[5]:
    policy = data.read_yaml(POLICY)
    if policy is None:
        st.info(f"`{POLICY}` is not in this copy, so there is no public-export policy to summarise.",
                icon=":material/info:")
    else:
        st.caption(f"`{POLICY}` records which downloaded caches a public copy may republish and which derived data "
                   "files the strict profile also leaves out. By its own header it is a record of reasoning for the "
                   "owner, not legal advice.")
        cats = policy.get("categories", {}) or {}
        cat_df = pd.DataFrame([{"category": k, "label": v.get("label", ""),
                                "exported by default": bool(v.get("export"))} for k, v in cats.items()])
        raw_entries = policy.get("raw_classification", []) or []
        entries = pd.DataFrame([{"policy id": e.get("id"), "pattern (under data/raw/)": e.get("pattern"),
                                 "category": e.get("category"),
                                 "exported": bool(e.get("export", cats.get(e.get("category"), {}).get("export"))),
                                 "certainty": e.get("certainty", ""), "source": e.get("source", "")}
                                for e in raw_entries])
        if man is not None and not man.empty:
            stamp = (data.path(POLICY).stat().st_mtime, mtime)
            cls = classify_manifest(str(data.path(POLICY)), stamp, tuple(man["key"]))
            if cls is not None:
                merged = man.merge(cls, on="key")
                kept = merged[merged["exported"]]
                components.kpi_row([
                    Kpi("Kept in a strict export", f"{len(kept):,} of {len(merged):,}",
                        f"{kept['bytes'].sum() / 1024 ** 2:,.1f} MB of {merged['bytes'].sum() / 1024 ** 2:,.1f} MB"),
                    Kpi("Excluded (B, editorial)", f"{int((merged['category'] == 'B').sum()):,}",
                        "third-party copyrighted editorial content"),
                    Kpi("Excluded (C, market data)", f"{int((merged['category'] == 'C').sum()):,}",
                        "licensed or restricted market data"),
                    Kpi("Unclassified", f"{int((merged['category'] == 'UNCLASSIFIED').sum()):,}",
                        "matched by no policy entry, so excluded (fail closed)"),
                ])
                tab = (merged.groupby(["category", "exported"])
                       .agg(entries=("key", "size"), MB=("bytes", lambda b: round(b.sum() / 1024 ** 2, 1)))
                       .reset_index())
                st.dataframe(tab, hide_index=True, width="stretch")
                components.source_caption([MANIFEST, POLICY], None,
                                          note="each manifest entry classified by tools/export_public.py's own "
                                               "classifier (first matching pattern wins)")
        st.markdown("##### Categories")
        st.dataframe(cat_df, hide_index=True, width="stretch")
        st.markdown("##### Raw-cache classification")
        cat_pick = st.multiselect("Category", list(cat_df["category"]) if not cat_df.empty else [],
                                  key="da_pol_category", placeholder="All categories")
        ev = entries[entries["category"].isin(cat_pick)] if cat_pick and not entries.empty else entries
        st.dataframe(ev, hide_index=True, width="stretch",
                     column_config={"source": st.column_config.TextColumn(width="large")})
        components.source_caption([POLICY], None, note="certainty: high / likely / uncertain, as the policy rates it")
        st.markdown("##### Derived files the strict profile leaves out")
        rules = pd.DataFrame([{"rule": r.get("id"), "category": r.get("category"),
                               "certainty": r.get("certainty", "likely"),
                               "reason": " ".join(str(r.get("reason", "")).split())}
                              for r in policy.get("strict_content_rules", []) or []])
        st.dataframe(rules, hide_index=True, width="stretch",
                     column_config={"reason": st.column_config.TextColumn(width="large")})
        omitted = pd.DataFrame([{"file": rel, "in this copy": data.exists(rel)}
                                for rel in sorted(data.PUBLIC_EXPORT_OMITS)])
        st.dataframe(omitted, hide_index=True, width="stretch")
        components.source_caption([POLICY], None,
                                  note="the files listed last are the data/processed tables a strict public copy "
                                       "omits; the dashboard shows “Not in this copy” where a page needs them")

# ------------------------------------------------------------------------------------------------ review logs
with tabs[6]:
    rdir = data.path(REVIEWS)
    reviews = sorted(p.relative_to(data.ROOT).as_posix() for p in rdir.glob("*.md")) if rdir.is_dir() else []
    if not reviews:
        components.missing_data(f"{REVIEWS}/phase4-7_review_log.md")
    else:
        pick = st.selectbox("Review log", reviews, key="da_review",
                            index=reviews.index(f"{REVIEWS}/phase4-7_review_log.md")
                            if f"{REVIEWS}/phase4-7_review_log.md" in reviews else 0)
        doc_viewer(pick, key="da_reviews")
    text = data.read_text(FINDINGS)
    if text is not None:
        try:
            findings = pd.DataFrame(json.loads(text))
        except (ValueError, TypeError):
            findings = None
        if findings is not None and {"severity", "lens", "file", "issue"} <= set(findings.columns):
            with st.expander(f"Phase 1–3 review findings ({len(findings)}, structured)", icon=":material/rule:"):
                sev = st.multiselect("Severity", list(findings["severity"].value_counts().index), key="da_find_sev",
                                     placeholder="All severities")
                fv = findings[findings["severity"].isin(sev)] if sev else findings
                st.dataframe(pd.crosstab(findings["lens"], findings["severity"]), width="stretch")
                st.dataframe(fv[[c for c in ("severity", "lens", "file", "issue", "suggested_fix") if c in fv.columns]],
                             hide_index=True, width="stretch", column_config={
                                 "issue": st.column_config.TextColumn(width="large"),
                                 "suggested_fix": st.column_config.TextColumn(width="large")})
                components.source_caption([FINDINGS], None,
                                          note="the reviewers' findings as recorded; what was changed is in "
                                               "phase1-3_fix_log.md")
