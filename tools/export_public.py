"""Build a publishable copy of the repository under dist/, leaving third-party caches out.

    .venv/bin/python tools/export_public.py                        # strict profile -> dist/public/
    .venv/bin/python tools/export_public.py --profile full-local   # owner backup  -> dist/full-local/ (never publish)
    .venv/bin/python tools/export_public.py --dry-run              # classify and report, copy nothing

Why this exists: data/raw/ caches every downloaded source so the desk rebuilds offline. Many of those files are
other people's copyrighted pages or licensed market data. They were fine to cache for private study, but they should
not be pushed to a public repository. This script never touches the local repository. It copies the working tree
(tracked files plus untracked files git does not ignore) into a fresh folder and:

* drops every data/raw file that tools/public_export_policy.yaml classifies as B (editorial content) or C (restricted
  market data), and fails closed on any raw file the policy does not classify;
* in the strict profile, also drops data/processed, data/interim and data/manual files whose columns or content
  republish category-C prices or category-B text (for example LME price columns or headline titles);
* keeps outputs/ (the recruiter-facing results) but reports which tables, workbook sheets, charts and text files
  still carry derived third-party data points, so the owner can decide before publishing;
* always keeps data/raw/_download_manifest.json (URL, retrieval date, sha256) so anyone can re-fetch and verify;
* writes DATA_NOTICE.md into the export, and a detailed JSON report next to it under dist/ (outside the export).

It is a helper for an informed decision, not a legal opinion.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import posixpath
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
DEFAULT_POLICY = ROOT / "tools" / "public_export_policy.yaml"
RAW_PREFIX = "data/raw/"
MANIFEST_REL = "data/raw/_download_manifest.json"
STRICT_DATA_PREFIXES = ("data/processed/", "data/interim/", "data/manual/")
PROFILES = {"strict": DIST / "public", "full-local": DIST / "full-local"}
BINARY_SCAN_LIMIT = 20_000_000
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(2**31 - 1)
# ------------------------------------------------------------------------------------------------ helpers


def glob_regex(pattern: str) -> re.Pattern[str]:
    """Translate a policy glob (`*` one segment, `**` any depth) into an anchored regex."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024
    return str(n)


def cell(text: object) -> str:
    """Make text safe inside a markdown table cell."""
    return " ".join(str(text).split()).replace("|", "/")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")


def read_text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def csv_header(rel: str) -> list[str]:
    with open(ROOT / rel, newline="", encoding="utf-8", errors="replace") as fh:
        return [c.strip() for c in next(csv.reader(fh), [])]


def count_rows(rel: str) -> int:
    with open(ROOT / rel, "rb") as fh:
        return max(sum(1 for _ in fh) - 1, 0)


def sha256(rel: str) -> str:
    h = hashlib.sha256()
    with open(ROOT / rel, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------ policy


@dataclass
class RawEntry:
    id: str
    pattern: str
    category: str
    export: bool
    certainty: str
    reason: str
    source: str = ""
    fetched_by: str = ""
    attribution: str = ""
    regex: re.Pattern[str] | None = None


@dataclass
class ContentRule:
    id: str
    category: str
    reason: str
    columns: re.Pattern[str] | None = None
    content: re.Pattern[str] | None = None
    paths: re.Pattern[str] | None = None
    phrase_source: bool = False
    certainty: str = "likely"


@dataclass
class Policy:
    raw: list[RawEntry]
    rules: list[ContentRule]
    categories: dict
    always_exclude: list[str]
    strict_never: dict[str, str]
    phrase_scan: dict
    charts: list[dict]
    url_fallbacks: list[dict]


def load_policy(path: Path) -> Policy:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    cats = doc["categories"]
    raw = []
    for e in doc["raw_classification"]:
        cat = e["category"]
        if cat not in cats:
            raise SystemExit(f"policy: raw entry {e['id']} has unknown category {cat}")
        raw.append(RawEntry(id=e["id"], pattern=e["pattern"], category=cat,
                            export=bool(e.get("export", cats[cat]["export"])), certainty=e.get("certainty", ""),
                            reason=" ".join(str(e.get("reason", "")).split()), source=e.get("source", ""),
                            fetched_by=e.get("fetched_by", ""), attribution=e.get("attribution", ""),
                            regex=glob_regex(e["pattern"])))
    rules = [ContentRule(id=r["id"], category=r["category"], reason=" ".join(str(r["reason"]).split()),
                         columns=re.compile(r["columns"]) if r.get("columns") else None,
                         content=re.compile(r["content"]) if r.get("content") else None,
                         paths=glob_regex(r["paths"]) if r.get("paths") else None,
                         phrase_source=bool(r.get("phrase_source")), certainty=r.get("certainty", "likely"))
             for r in doc["strict_content_rules"]]
    return Policy(raw=raw, rules=rules, categories=cats, always_exclude=doc["always_exclude_prefixes"],
                  strict_never={x["path"]: x["reason"] for x in doc.get("strict_never_export", [])},
                  phrase_scan=doc["phrase_scan"], charts=doc.get("known_derived_charts", []),
                  url_fallbacks=doc.get("url_fallbacks", []))


# ------------------------------------------------------------------------------------------------ selection


@dataclass
class Decision:
    path: str
    size: int
    export: bool
    group: str  # raw category (A/B/C/META/UNCLASSIFIED), DERIVED_B/DERIVED_C, OWNER_ONLY or KEEP
    rule_ids: list[str] = field(default_factory=list)
    detail: str = ""


def working_tree_files(policy: Policy) -> tuple[list[str], list[str]]:
    """Tracked + untracked-not-ignored files that exist on disk (skipped: symlinks, deleted tracked files)."""
    listed = sorted({p for p in git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0") if p})
    files, skipped = [], []
    for rel in listed:
        if any(rel.startswith(x) for x in policy.always_exclude):
            continue
        p = ROOT / rel
        if p.is_symlink() or not p.is_file():
            skipped.append(rel)
            continue
        files.append(rel)
    return files, skipped


def classify_raw(rel: str, policy: Policy) -> RawEntry | None:
    sub = rel[len(RAW_PREFIX):]
    return next((e for e in policy.raw if e.regex.match(sub)), None)


def rule_hits(rel: str, rules: list[ContentRule]) -> dict[str, list[str]]:
    """Rules matched by a CSV (or other text) file -> the matching column names (empty list for content-only)."""
    header = csv_header(rel) if rel.endswith(".csv") else []
    text: str | None = None
    hits: dict[str, list[str]] = {}
    for r in rules:
        if r.paths and not r.paths.match(rel):
            continue
        cols: list[str] = []
        if r.columns:
            cols = [c for c in header if r.columns.search(c)]
            if not cols:
                continue
        if r.content:
            if text is None:
                text = read_text(rel)
            if not r.content.search(text):
                continue
        if not r.columns and not r.content:
            continue
        hits[r.id] = cols
    return hits


def xlsx_hits(rel: str, rules: list[ContentRule]) -> dict[str, dict[str, list[str]]]:
    """Per-sheet rule hits for an .xlsx: header-like cell texts matching a rule's column regex."""
    import zipfile

    out: dict[str, dict[str, list[str]]] = {}
    with zipfile.ZipFile(ROOT / rel) as z:
        names = set(z.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            sst = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            shared = ["".join(re.findall(r"<t[^>]*>([^<]*)</t>", si)) for si in re.findall(r"<si>(.*?)</si>", sst, re.S)]
        wb = z.read("xl/workbook.xml").decode("utf-8", "replace")
        rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
        targets = {}
        for rel_tag in re.findall(r"<Relationship\b[^>]*>", rels):
            rid = re.search(r'\bId="([^"]+)"', rel_tag)
            tgt = re.search(r'\bTarget="([^"]+)"', rel_tag)
            if rid and tgt:
                targets[rid.group(1)] = tgt.group(1)
        for sheet_tag in re.findall(r"<sheet\b[^>]*>", wb):
            name = re.search(r'\bname="([^"]+)"', sheet_tag).group(1)
            rid = re.search(r'\br:id="([^"]+)"', sheet_tag).group(1)
            target = targets[rid].lstrip("/")
            member = target if target.startswith("xl/") else "xl/" + target
            xml = z.read(member).decode("utf-8", "replace")
            texts = set(re.findall(r"<t[^>]*>([^<]*)</t>", xml))
            if shared:
                texts.update(shared[int(i)] for i in re.findall(r'<c\b[^>]*\bt="s"[^>]*>\s*<v>(\d+)</v>', xml)
                             if int(i) < len(shared))
            for r in rules:
                if not r.columns or (r.paths and not r.paths.match(rel)):
                    continue
                cols = sorted(t.strip() for t in texts if r.columns.search(t.strip()))
                if not cols or (r.content and not r.content.search(xml)):
                    continue
                out.setdefault(name, {})[r.id] = cols
            del xml, texts
    return out


def select(files: list[str], policy: Policy, profile: str) -> list[Decision]:
    decisions = []
    for rel in files:
        size = (ROOT / rel).stat().st_size
        if profile == "full-local":
            group = "KEEP"
            if rel.startswith(RAW_PREFIX):
                e = classify_raw(rel, policy)
                group = e.category if e else "UNCLASSIFIED"
            decisions.append(Decision(rel, size, True, group, detail="full-local keeps everything"))
            continue
        if rel in policy.strict_never:
            decisions.append(Decision(rel, size, False, "OWNER_ONLY", detail=policy.strict_never[rel]))
        elif rel.startswith(RAW_PREFIX):
            e = classify_raw(rel, policy)
            if e is None:
                decisions.append(Decision(rel, size, False, "UNCLASSIFIED",
                                          detail="no policy entry matched; excluded (fail closed)"))
            else:
                decisions.append(Decision(rel, size, e.export, e.category, [e.id], e.reason))
        elif rel.startswith(STRICT_DATA_PREFIXES) and not rel.endswith((".csv", ".json", ".txt", ".md")):
            decisions.append(Decision(rel, size, False, "UNSCANNED",
                                      detail="data file type the content rules cannot read; excluded (fail closed)"))
        elif rel.startswith(STRICT_DATA_PREFIXES):
            hits = rule_hits(rel, policy.rules)
            if hits:
                cats = {r.category for r in policy.rules if r.id in hits}
                group = "DERIVED_C" if "C" in cats else "DERIVED_B"
                detail = "; ".join(f"{rid}: {', '.join(cols) if cols else 'content match'}" for rid, cols in hits.items())
                decisions.append(Decision(rel, size, False, group, list(hits), detail))
            else:
                decisions.append(Decision(rel, size, True, "KEEP"))
        else:
            decisions.append(Decision(rel, size, True, "KEEP"))
    return decisions


# ------------------------------------------------------------------------------------------------ scans

WORD = re.compile(r"[a-z0-9]+")


class PhraseIndex:
    """Verbatim-phrase lookup keyed on each phrase's first n words (an O(tokens) scan per file)."""

    def __init__(self, n: int):
        self.n = n
        self.by_key: dict[tuple[str, ...], list[tuple[tuple[str, ...], str]]] = defaultdict(list)
        self.first: set[str] = set()
        self.seen: set[tuple[str, ...]] = set()

    def add(self, text: str, kind: str) -> None:
        w = tuple(WORD.findall(text.lower()))
        if len(w) < self.n or w in self.seen:
            return
        self.seen.add(w)
        self.by_key[w[: self.n]].append((w, kind))
        self.first.add(w[0])

    def find(self, words: list[str]) -> set[tuple[tuple[str, ...], str]]:
        hits, n, first, by_key = set(), self.n, self.first, self.by_key
        for i in range(len(words) - n + 1):
            if words[i] not in first:
                continue
            cands = by_key.get(tuple(words[i:i + n]))
            if cands:
                for seq, kind in cands:
                    if tuple(words[i:i + len(seq)]) == seq:
                        hits.add((seq, kind))
        return hits


def build_phrase_index(all_files: list[str], policy: Policy) -> tuple[PhraseIndex, set[str]]:
    cfg = policy.phrase_scan
    idx = PhraseIndex(int(cfg["min_words"]))
    globs = [glob_regex(g) for g in cfg["source_globs"]]
    source_rules = [r for r in policy.rules if r.phrase_source and r.columns]
    source_files: set[str] = set()
    for rel in all_files:
        if not rel.endswith(".csv") or not any(g.match(rel) for g in globs):
            continue
        header = csv_header(rel)
        cols = {c: r.id for r in source_rules for c in header if r.columns.search(c)}
        if not cols:
            continue
        source_files.add(rel)
        with open(ROOT / rel, newline="", encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh):
                for col, rid in cols.items():
                    val = (row.get(col) or "").strip()
                    if not val:
                        continue
                    idx.add(val, rid)
                    if " - " in val:  # Google News titles end in " - Publisher"; quotes often drop it
                        idx.add(val.rsplit(" - ", 1)[0], rid)
    return idx, source_files


def phrase_scan(exported: list[str], idx: PhraseIndex, source_files: set[str], policy: Policy) -> dict[str, dict]:
    exts = tuple(policy.phrase_scan["text_extensions"])
    found: dict[str, dict] = {}
    for rel in exported:
        if rel.startswith(RAW_PREFIX) or rel in source_files or not rel.endswith(exts):
            continue
        hits: set = set()
        if rel.endswith(".csv"):
            with open(ROOT / rel, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    hits |= idx.find(WORD.findall(line.lower()))
        else:
            hits = idx.find(WORD.findall(read_text(rel).lower()))
        if hits:
            by_kind: dict[str, int] = defaultdict(int)
            for _seq, kind in hits:
                by_kind[kind] += 1
            found[rel] = dict(by_kind)
    return found


def identity_tokens() -> dict[str, str]:
    """Strings that would identify the machine owner if they leaked into the export (labels only are reported)."""
    tokens = {"home_directory_path": str(Path.home())}
    if len(Path.home().name) >= 4:
        tokens["os_username"] = Path.home().name
    for key, label in (("user.name", "git_user_name"), ("user.email", "git_user_email")):
        try:
            val = git("config", key).strip()
        except subprocess.CalledProcessError:
            val = ""
        if len(val) >= 4:
            tokens[label] = val
    return tokens


EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")


def personal_data_scan(exported: list[str], policy: Policy) -> dict[str, dict]:
    tokens = identity_tokens()
    exts = tuple(policy.phrase_scan["text_extensions"])
    out: dict[str, dict] = {}
    for rel in exported:
        if rel.startswith(RAW_PREFIX) and rel != MANIFEST_REL:
            continue
        p = ROOT / rel
        rec: dict = {}
        if rel.endswith(exts):
            text = read_text(rel)
            low = text.lower()
            for label, tok in tokens.items():
                n = low.count(tok.lower())
                if n:
                    rec[label] = n
            emails = sorted(set(EMAIL.findall(text)))
            if emails:
                rec["emails"] = emails
        elif p.stat().st_size <= BINARY_SCAN_LIMIT:
            data = p.read_bytes().lower()
            for label, tok in tokens.items():
                n = data.count(tok.lower().encode())
                if n:
                    rec[label] = n
        if rec:
            out[rel] = rec
    return out


MD_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HTML_LINK = re.compile(r"<(?:a|img)\b[^>]*\b(?:href|src)=\"([^\"]+)\"", re.I)
FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)


def blank_fences(text: str) -> str:
    """Drop fenced code blocks but keep their line breaks, so reported line numbers stay true."""
    return FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def link_check(exported: list[str]) -> list[dict]:
    """Relative links in exported markdown whose targets are not in the export."""
    exported_set = set(exported)
    exported_dirs = {posixpath.dirname(p) for p in exported}
    all_dirs = set()
    for d in list(exported_dirs):
        while d:
            all_dirs.add(d)
            d = posixpath.dirname(d)
    broken = []
    for rel in exported:
        if not rel.endswith(".md"):
            continue
        text = blank_fences(read_text(rel))
        for m in list(MD_LINK.finditer(text)) + list(HTML_LINK.finditer(text)):
            target = m.group(1)
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
                continue
            path = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not path:
                continue
            resolved = posixpath.normpath(path.lstrip("/") if path.startswith("/")
                                          else posixpath.join(posixpath.dirname(rel), path))
            if resolved in exported_set or resolved.rstrip("/") in all_dirs or resolved == ".":
                continue
            on_disk = (ROOT / resolved).exists()
            line = text.count("\n", 0, m.start()) + 1
            broken.append({"file": rel, "line": line, "target": target, "resolved": resolved,
                           "cause": "excluded_by_export" if on_disk else "missing_in_source"})
    return broken


PATH_TOKEN = re.compile(r"(?<![\w/.:-])((?:[\w.-]+/)*[\w.-]+\.(?:csv|html|xml|json|pdf|xlsx|md|png|yaml)"
                        r"|(?:[\w.-]+/)+)(?![\w/])")


def readme_mentions(exported_set: set[str], excluded: list[Decision]) -> list[dict]:
    """Path-like mentions in README.md (prose, code and diagrams) that name excluded files or wholly excluded folders."""
    if "README.md" not in exported_set:
        return []
    text = read_text("README.md")
    fenced = [(m.start(), m.end()) for m in FENCE.finditer(text)]
    excluded_paths = {d.path for d in excluded}
    base = defaultdict(set)
    for p in excluded_paths:
        base[posixpath.basename(p)].add(p)
    out, seen = [], set()
    for m in PATH_TOKEN.finditer(text):
        tok = m.group(1)
        if tok in seen:
            continue
        hit = None
        if tok in excluded_paths:
            hit = tok
        elif "/" not in tok and len(base.get(tok, ())) == 1 and not any(p.endswith("/" + tok) or p == tok
                                                                        for p in exported_set):
            hit = next(iter(base[tok]))
        elif tok.endswith("/") and not any(p.startswith(tok) for p in exported_set) and \
                any(p.startswith(tok) for p in excluded_paths):
            hit = tok
        if hit:
            seen.add(tok)
            out.append({"mention": tok, "excluded": hit, "line": text.count("\n", 0, m.start()) + 1,
                        "in_code_block": any(a <= m.start() < b for a, b in fenced)})
    return out


# ------------------------------------------------------------------------------------------------ report


def manifest_facts(decisions: list[Decision], policy: Policy) -> dict:
    manifest = json.loads((ROOT / MANIFEST_REL).read_text(encoding="utf-8"))
    kept_raw = [d for d in decisions if d.export and d.path.startswith(RAW_PREFIX) and d.path != MANIFEST_REL]
    mismatched, unrecorded = [], []
    for d in kept_raw:
        key = d.path[len(RAW_PREFIX):]
        if key not in manifest:
            if d.group != "META":
                unrecorded.append(d.path)
            continue
        if sha256(d.path) != manifest[key]["sha256"]:
            mismatched.append(d.path)
    no_url = defaultdict(int)
    for key, rec in manifest.items():
        if not rec.get("url"):
            e = classify_raw(RAW_PREFIX + key, policy)
            no_url[e.id if e else "UNCLASSIFIED"] += 1
    return {"entries": len(manifest), "kept_raw_checked": len(kept_raw), "sha256_mismatch": mismatched,
            "kept_not_in_manifest": unrecorded, "entries_without_url_by_policy_id": dict(no_url)}


def outputs_carriers(exported: list[str], policy: Policy) -> dict:
    tables, workbooks, charts = {}, {}, []
    for rel in exported:
        if not rel.startswith("outputs/"):
            continue
        if rel.endswith(".csv"):
            hits = rule_hits(rel, policy.rules)
            if hits:
                tables[rel] = {"rules": hits, "rows": count_rows(rel)}
        elif rel.endswith(".xlsx"):
            hits = xlsx_hits(rel, policy.rules)
            if hits:
                workbooks[rel] = hits
    exported_set = set(exported)
    for c in policy.charts:
        rx = glob_regex(c["path"])
        matches = sorted(p for p in exported_set if rx.match(p))
        charts.append({**c, "files": matches})
    return {"tables": tables, "workbooks": workbooks, "charts": charts}


def write_notice(out_dir: Path, profile: str, decisions: list[Decision], policy: Policy, facts: dict,
                 carriers: dict, phrases: dict, broken: list[dict], head: str, dirty: int) -> None:
    rules = {r.id: r for r in policy.rules}
    exported = [d for d in decisions if d.export]
    excluded = [d for d in decisions if not d.export]
    L: list[str] = []
    add = L.append
    add("# DATA_NOTICE: what this copy leaves out, and why")
    add("")
    add("> **ACADEMIC SIMULATION — not actual trades.** This notice covers the data in this copy of the Virtual Metals "
        "Trading Desk. It is not legal advice.")
    add("")
    if profile == "full-local":
        add("> **FULL-LOCAL BACKUP. DO NOT PUBLISH.** This copy still contains every third-party cache (categories B "
            "and C below). It exists only as the owner's private backup.")
        add("")
    add(f"Generated by `tools/export_public.py --profile {profile}` on {dt.date.today().isoformat()} from the working "
        f"tree at commit `{head[:12]}`" + (f" ({dirty} uncommitted changes at export time)." if dirty else "."))
    add("")
    add("The classification behind every decision here, with a reason and a certainty level for each source, is in "
        "[`tools/public_export_policy.yaml`](tools/public_export_policy.yaml). **Certainty** is *high*, *likely* or "
        "*uncertain*. None of it is a legal determination: publishers' terms change, and a page being free to read "
        "does not make it free to republish.")
    add("")

    add("## 1. Summary")
    add("")
    add("| Group | Meaning | Files kept | Size kept | Files excluded | Size excluded |")
    add("|---|---|--:|--:|--:|--:|")
    meaning = {k: v["label"] for k, v in policy.categories.items()}
    meaning.update({"DERIVED_C": "Derived data file republishing category-C prices or index values",
                    "DERIVED_B": "Derived data file republishing category-B verbatim text",
                    "OWNER_ONLY": "Maintainer's release checklist, not part of the project",
                    "UNCLASSIFIED": "Raw file with no policy entry (fail closed)",
                    "UNSCANNED": "Data file of a type the content rules cannot read (fail closed)",
                    "KEEP": "Code, config, docs, tests, outputs and other project files"})
    groups = defaultdict(lambda: [0, 0, 0, 0])
    for d in decisions:
        g = groups[d.group]
        if d.export:
            g[0] += 1
            g[1] += d.size
        else:
            g[2] += 1
            g[3] += d.size
    order = ["KEEP", "META", "A", "B", "C", "DERIVED_B", "DERIVED_C", "OWNER_ONLY", "UNCLASSIFIED", "UNSCANNED"]
    for key in order:
        if key in groups:
            g = groups[key]
            add(f"| {key} | {cell(meaning.get(key, key))} | {g[0]:,} | {human(g[1])} | {g[2]:,} | {human(g[3])} |")
    add(f"| **Total** | | **{len(exported):,}** | **{human(sum(d.size for d in exported))}** | "
        f"**{len(excluded):,}** | **{human(sum(d.size for d in excluded))}** |")
    add("")

    add("## 2. Downloaded sources (`data/raw/`)")
    add("")
    add("Each file under `data/raw/` is matched to the first policy entry whose pattern fits. A file that matches no "
        "entry is excluded. Categories: "
        "**A** = public-domain, open government or reuse-with-attribution data (kept); **B** = third-party "
        "copyrighted editorial content (excluded); **C** = licensed or restricted market data (excluded); "
        "**META** = index metadata written by this project or a machine-generated capture listing (kept).")
    add("")
    add("| Policy entry | Files | Size | Category | Certainty | In this copy | Source | Fetched by | Why |")
    add("|---|--:|--:|---|---|---|---|---|---|")
    per_entry = defaultdict(lambda: [0, 0])
    for d in decisions:
        if d.path.startswith(RAW_PREFIX):
            e = classify_raw(d.path, policy)
            k = e.id if e else "UNCLASSIFIED"
            per_entry[k][0] += 1
            per_entry[k][1] += d.size
    for e in policy.raw:
        n, b = per_entry.get(e.id, (0, 0))
        if not n:
            continue
        kept = "kept" if (e.export or profile == "full-local") else "**excluded**"
        add(f"| `{e.id}` (`{e.pattern}`) | {n:,} | {human(b)} | {e.category} | {e.certainty} | {kept} | "
            f"{cell(e.source)} | {cell(e.fetched_by)} | {cell(e.reason)} |")
    if "UNCLASSIFIED" in per_entry:
        n, b = per_entry["UNCLASSIFIED"]
        add(f"| UNCLASSIFIED | {n:,} | {human(b)} | — | — | **excluded** | — | — | No policy entry matched. |")
    add("")

    derived = [d for d in decisions if d.group.startswith("DERIVED")]
    if derived:
        add("## 3. Derived data files left out (strict profile)")
        add("")
        add("These files sit in `data/processed/` or `data/interim/`. They were left out because their columns or "
            "content republish category-C prices or category-B text. Running Phase 0 online rebuilds them.")
        add("")
        add("| File | Size | Matched rules (columns) |")
        add("|---|--:|---|")
        for d in derived:
            add(f"| `{d.path}` | {human(d.size)} | {cell(d.detail)} |")
        add("")
        add("Rules:")
        add("")
        for r in policy.rules:
            add(f"- `{r.id}` ({r.category}, {r.certainty}): {r.reason}")
        add("")

    add("## 4. How to rebuild the excluded data")
    add("")
    add("The manifest [`data/raw/_download_manifest.json`](data/raw/_download_manifest.json) is always kept. It "
        f"has {facts['entries']:,} entries, each with a URL (where recorded), a retrieval date, a sha256 and a size. "
        "Anyone can use it to re-fetch the excluded files and check them. Fetching from a source is subject to that "
        "source's own terms, so read them first.")
    add("")
    add("```sh")
    add("python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt")
    add("cp data/raw/_download_manifest.json published_manifest.json   # fetchers rewrite manifest entries they download")
    add(".venv/bin/python run_all.py --only P0                          # ONLINE: no DESK_OFFLINE, missing caches are fetched")
    add("DESK_OFFLINE=1 .venv/bin/python run_all.py --from P1           # then the rest, offline (see README memory note)")
    add("```")
    add("")
    add("To compare re-fetched bodies with the published hashes:")
    add("")
    add("```sh")
    add(".venv/bin/python - <<'EOF'")
    add("import hashlib, json, pathlib")
    add("pub = json.load(open('published_manifest.json'))")
    add("raw = pathlib.Path('data/raw')")
    add("same = [k for k, v in pub.items() if (raw / k).exists() and hashlib.sha256((raw / k).read_bytes()).hexdigest() == v['sha256']]")
    add("missing = [k for k in pub if not (raw / k).exists()]")
    add("print(len(same), 'identical;', len(pub) - len(same) - len(missing), 'differ;', len(missing), 'not fetched')")
    add("EOF")
    add("```")
    add("")
    add("What to expect:")
    add("")
    add("- **Some bodies will differ, and that is not an error.** Google News RSS results change over time, and each "
        "feed carries the current copyright year. Live article and price pages change their markup. The current "
        "year's Westmetall table keeps growing, and Internet Archive availability varies. The published `outputs/` "
        "are the reference results. A rebuild from re-fetched data can move numbers, and the headline P&L must "
        "always be read with its sensitivity band (`outputs/tables/pnl_sensitivity_sign_robustness.csv`).")
    add("- **Not every cache is fetched by the pipeline.** Entries whose *Fetched by* column says *manual* are reference "
        "documents cited in `config/params/*.yaml` and `docs/research/`. No stage reads them. Download them by hand "
        "from their manifest URL if you want to check a citation.")
    if facts["entries_without_url_by_policy_id"]:
        add("- **Some manifest entries have an empty `url`.** They were back-filled from file modification times "
            "(`how: mtime_backfill`). Their sources are recorded here:")
        fallbacks = [(glob_regex(f["pattern"]), f["pattern"], f["where"]) for f in policy.url_fallbacks]
        raw_by_id = {e.id: e for e in policy.raw}
        for pid, n in sorted(facts["entries_without_url_by_policy_id"].items()):
            e = raw_by_id.get(pid)
            where = ""
            if e:
                probe = e.pattern.replace("**", "x").replace("*", "x")
                where = next((w for rx, _p, w in fallbacks if rx.match(probe)), "")
            add(f"  - `{pid}`: {n} {'entry' if n == 1 else 'entries'}" + (f", source in {where}" if where else ""))
    add("- **Offline mode needs the caches.** In this copy `DESK_OFFLINE=1 run_all.py --only P0` cannot run until the "
        "caches are rebuilt. The P1+ stages need `data/processed/market_daily.csv`, which Phase 0 writes. Until then, "
        "expect some tests to skip and others to fail, because they read the files left out in section 3. This "
        "expectation comes from reading the tests; the suite was not run on this copy. For example, several desk-note, "
        "post-mortem and risk tests read `market_daily.csv`, and the link check in `tests/test_reports_runner.py` "
        "fails on any link listed in section 7.")
    add("")

    add("## 5. Derived third-party data points still in this copy")
    add("")
    add("`outputs/` holds the project's published results and is kept whole. All of its P&L, marks, parity values and "
        "risk numbers are computed from the sources above. The lists below cover the columns, sheets, charts and text "
        "that still show a source value, or a direct transformation of one, so that publishing them is an informed "
        "decision.")
    add("")
    if carriers["tables"]:
        add("### 5.1 Tables (`outputs/tables/`)")
        add("")
        add("| Table | Rows | Rule: matching columns |")
        add("|---|--:|---|")
        for rel, rec in sorted(carriers["tables"].items()):
            desc = "; ".join(f"`{rid}`: {', '.join(cols) if cols else 'content'}" for rid, cols in rec["rules"].items())
            add(f"| `{rel}` | {rec['rows']:,} | {cell(desc)} |")
        add("")
        by_rule = defaultdict(int)
        for rec in carriers["tables"].values():
            for rid in rec["rules"]:
                by_rule[rid] += 1
        add("Tables per rule: " + ", ".join(f"`{k}` {v}" for k, v in sorted(by_rule.items())) + ".")
        add("")
    if carriers["workbooks"]:
        add("### 5.2 Workbook sheets")
        add("")
        add("| Workbook | Sheet | Rule: matching header cells |")
        add("|---|---|---|")
        for rel, sheets in carriers["workbooks"].items():
            for sheet, hits in sheets.items():
                desc = "; ".join(f"`{rid}`: {', '.join(cols)}" for rid, cols in hits.items())
                add(f"| `{rel}` | {cell(sheet)} | {cell(desc)} |")
        add("")
    add("### 5.3 Charts")
    add("")
    add("Charts cannot be scanned by column. This list comes from reading the plotting code.")
    add("")
    add("| Chart(s) | Carries | Evidence |")
    add("|---|---|---|")
    for c in carriers["charts"]:
        files = ", ".join(f"`{f}`" for f in c["files"]) or f"`{c['path']}` (not present)"
        add(f"| {files} | {cell(', '.join(c['carries']))} | {cell(c['evidence'])} |")
    add("")
    add("### 5.4 Verbatim third-party text in documents and tables")
    add("")
    add(f"Every headline title and article snippet in the project's CSVs with at least "
        f"{policy.phrase_scan['min_words']} words was searched for, word for word, in the other exported text files "
        "(PDFs are not scanned, but their `.md` sources are). Files that hold the text as a column are listed in 5.1.")
    add("")
    if phrases:
        add("| File | Distinct matches by kind |")
        add("|---|---|")
        for rel, kinds in sorted(phrases.items()):
            add(f"| `{rel}` | {cell(', '.join(f'{k}: {v}' for k, v in sorted(kinds.items())))} |")
    else:
        add("No verbatim headline titles or article snippets were found outside the files listed in 5.1.")
    add("")
    add("### 5.5 Not scanned")
    add("")
    add("- Prose in `docs/`, `outputs/reports/` and `config/params/*.yaml` quotes individual LME, MCX, freight and "
        "price-assessment levels as evidence, for example the LME peak or an ADC12 price. These are not listed one "
        "by one.")
    add("- `docs/00_data_dictionary.md`, `docs/research/` and `config/params/*.yaml` cite source URLs and short "
        "descriptions of cached documents.")
    add("")

    add("## 6. Attribution for the kept category-A data")
    add("")
    for e in policy.raw:
        if e.category == "A" and e.attribution and per_entry.get(e.id, (0, 0))[0]:
            flag = " *(uncertain: check the terms before publishing)*" if e.certainty == "uncertain" else ""
            add(f"- `{e.pattern}`: {e.attribution}{flag}")
    add("")
    if broken:
        add("## 7. Links in this copy whose targets are not included")
        add("")
        add("| File | Line | Link target | Why |")
        add("|---|--:|---|---|")
        for b in broken:
            why = "left out of this copy" if b["cause"] == "excluded_by_export" else "missing in the source repository too"
            add(f"| `{b['file']}` | {b['line']} | `{cell(b['target'])}` | {why} |")
        add("")
    (out_dir / "DATA_NOTICE.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", choices=sorted(PROFILES), default="strict")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--out", type=Path, help="output folder; must be inside dist/ (default: dist/public or dist/full-local)")
    ap.add_argument("--dry-run", action="store_true", help="classify and report without copying")
    args = ap.parse_args(argv)

    out_dir = (args.out or PROFILES[args.profile]).resolve()
    if DIST.resolve() not in out_dir.parents:
        raise SystemExit(f"refusing to write outside {DIST}: {out_dir}")
    policy = load_policy(args.policy)
    files, skipped = working_tree_files(policy)
    decisions = select(files, policy, args.profile)
    exported = [d.path for d in decisions if d.export]
    excluded = [d for d in decisions if not d.export]

    # Safety net: nothing classified B/C (or unclassified) under data/raw may be in a strict export.
    if args.profile == "strict":
        leaks = [d.path for d in decisions if d.export and d.path.startswith(RAW_PREFIX)
                 and (classify_raw(d.path, policy) is None or not classify_raw(d.path, policy).export)]
        if leaks:
            raise SystemExit(f"internal error: B/C raw files selected for export: {leaks[:5]}")

    facts = manifest_facts(decisions, policy)
    carriers = outputs_carriers(exported, policy)
    idx, source_files = build_phrase_index(files, policy)
    phrases = phrase_scan(exported, idx, source_files, policy)
    exported_set = set(exported)
    broken = link_check(exported)
    readme = [b for b in broken if b["file"] == "README.md"]
    mentions = readme_mentions(exported_set, excluded)
    personal = personal_data_scan(exported, policy)
    head = git("rev-parse", "HEAD").strip()
    dirty = len([ln for ln in git("status", "--porcelain").splitlines() if ln.strip()])

    if not args.dry_run:
        if out_dir.exists():
            shutil.rmtree(out_dir)
        for rel in exported:
            dst = out_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dst)
        write_notice(out_dir, args.profile, decisions, policy, facts, carriers, phrases, broken, head, dirty)
        notice = out_dir / "DATA_NOTICE.md"
        copied = [p for p in out_dir.rglob("*") if p.is_file() and p != notice]
        if len(copied) != len(exported) or sum(p.stat().st_size for p in copied) != sum(d.size for d in decisions if d.export):
            raise SystemExit("post-copy check failed: file count or byte total differs from the selection")
        if args.profile == "strict":
            raw_in_copy = [p.relative_to(out_dir).as_posix() for p in (out_dir / "data" / "raw").rglob("*") if p.is_file()] \
                if (out_dir / "data" / "raw").exists() else []
            bad = [r for r in raw_in_copy if (classify_raw(r, policy) is None or not classify_raw(r, policy).export)]
            if bad:
                raise SystemExit(f"post-copy check failed: B/C raw files present: {bad[:5]}")

    report = {
        "profile": args.profile, "out_dir": str(out_dir), "dry_run": args.dry_run, "commit": head,
        "uncommitted_changes": dirty, "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "skipped_not_regular_files": skipped,
        "excluded": [{"path": d.path, "size": d.size, "group": d.group, "rule_ids": d.rule_ids,
                      **({"detail": d.detail} if not d.path.startswith(RAW_PREFIX) or d.group == "UNCLASSIFIED" else {})}
                     for d in excluded], "manifest": facts, "outputs_carriers": carriers,
        "verbatim_phrase_hits": phrases, "broken_links": broken, "readme_code_mentions_of_excluded": mentions,
        "personal_data_hits": personal,
    }
    DIST.mkdir(exist_ok=True)
    report_path = DIST / f"{args.profile}_export_report.json"
    report_path.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")

    # ---- console summary
    tot_in = sum(d.size for d in decisions)
    tot_out = sum(d.size for d in decisions if d.export)
    print(f"profile {args.profile}{' (dry run)' if args.dry_run else ''} -> {out_dir.relative_to(ROOT)}")
    print(f"working tree: {len(decisions):,} files, {human(tot_in)} (commit {head[:12]}, {dirty} uncommitted changes)")
    print(f"exported:     {len(exported):,} files, {human(tot_out)} (+ DATA_NOTICE.md)")
    print(f"excluded:     {len(excluded):,} files, {human(tot_in - tot_out)}")
    groups = defaultdict(lambda: [0, 0])
    for d in excluded:
        groups[d.group][0] += 1
        groups[d.group][1] += d.size
    for g in ["A", "META", "B", "C", "DERIVED_B", "DERIVED_C", "OWNER_ONLY", "UNCLASSIFIED", "UNSCANNED"]:
        if g in groups:
            print(f"  {g:<13}{groups[g][0]:>6,} files {human(groups[g][1]):>10}")
    if skipped:
        print(f"skipped (symlink or deleted in working tree): {len(skipped)}")
    kept_raw = [d for d in decisions if d.export and d.path.startswith(RAW_PREFIX)]
    print(f"raw kept:     {len(kept_raw)} files ({human(sum(d.size for d in kept_raw))}); sha256 vs manifest: "
          f"{facts['kept_raw_checked'] - len(facts['sha256_mismatch']) - len(facts['kept_not_in_manifest'])}"
          f"/{facts['kept_raw_checked']} match"
          + (f", MISMATCH {facts['sha256_mismatch'][:3]}" if facts["sha256_mismatch"] else ""))
    big = sorted((d for d in decisions if d.export), key=lambda d: -d.size)[:3]
    print("largest kept: " + ", ".join(f"{d.path} ({human(d.size)})" for d in big))
    print(f"outputs carrying derived third-party data: {len(carriers['tables'])} tables, "
          f"{sum(len(s) for s in carriers['workbooks'].values())} workbook sheets, "
          f"{sum(len(c['files']) for c in carriers['charts'])} charts; verbatim-text hits in {len(phrases)} other files")
    print(f"broken relative links in exported markdown: {len(broken)} "
          f"({sum(b['cause'] == 'excluded_by_export' for b in broken)} caused by the export)")
    for b in readme:
        print(f"  README.md -> {b['target']} ({b['cause']})")
    for m in mentions:
        where = "code block/diagram" if m["in_code_block"] else "text"
        print(f"  README.md line {m['line']} ({where}) mentions {m['mention']} -> excluded {m['excluded']}")
    if personal:
        print(f"possible personal data in {len(personal)} exported files (labels only; details in the JSON report):")
        for rel, rec in sorted(personal.items()):
            labels = ", ".join(f"{k}={len(v) if isinstance(v, list) else v}" for k, v in rec.items())
            print(f"  {rel}: {labels}")
    print(f"report: {report_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
