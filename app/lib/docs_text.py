"""Pull prose out of the repository's markdown so the app quotes the docs instead of rewriting them.

    section("docs/40_var_garch.md", WHAT_IT_TELLS)  -> Section(title="8. What this does and doesn't tell you", body=...)
    lead_paragraph("outputs/reports/one_pager.md")  -> the first paragraph under the H1
    for_streamlit(markdown, "docs/40_var_garch.md") -> links rewritten, images referenced, `$` and `~` escaped

Relative links in a doc point at files next to it (`../outputs/tables/x.csv`), which mean nothing inside the app. They
become the repo-relative path in a code span, or, when the environment variable `DESK_APP_REPO_URL` is set (e.g.
`https://github.com/<you>/<repo>/blob/main`), a real link to that file in the published repository.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from app.lib import data

WHAT_IT_TELLS = "What this does and doesn't tell you"

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1", flags=re.S)


@dataclass(frozen=True)
class Section:
    doc: str          # repo-relative path of the document
    title: str        # the heading text as written ("8. What this does and doesn't tell you")
    level: int
    body: str         # raw markdown under the heading, up to the next heading of the same or a higher level

    @property
    def number(self) -> str | None:
        """ "8" for "8. What this ...", "13.9" for "13.9 Sign robustness" (None when the heading is unnumbered)."""
        m = re.match(r"§?(\d+(?:\.\d+)*)[.)]?\s", self.title)
        return m.group(1) if m else None


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("`", "").lower()
    s = re.sub(r"^§?\d+(?:\.\d+)*[.)]?\s+", "", s.strip())
    return re.sub(r"\s+", " ", s).strip(" .:")


def headings(md: str) -> list[tuple[int, int, str]]:
    """(line index, level, text) of every heading outside fenced code blocks."""
    out, fenced = [], False
    for i, line in enumerate(md.splitlines()):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        m = None if fenced else _HEADING.match(line)
        if m:
            out.append((i, len(m.group(1)), m.group(2)))
    return out


def extract_section(md: str, heading: str) -> tuple[str, int, str] | None:
    """(title, level, body) of the first heading whose normalised text contains `heading` (numbering, case, curly
    apostrophes and backticks ignored)."""
    want = _norm(heading)
    lines = md.splitlines()
    hs = headings(md)
    for n, (i, level, text) in enumerate(hs):
        if want and want in _norm(text):
            end = next((j for j, lv, _ in hs[n + 1:] if lv <= level), len(lines))
            return text, level, "\n".join(lines[i + 1:end]).strip("\n")
    return None


def section(doc_rel: str, heading: str = WHAT_IT_TELLS) -> Section | None:
    """A section of a repository markdown file, or None if the file or the heading is missing."""
    md = data.read_text(doc_rel)
    hit = None if md is None else extract_section(md, heading)
    return None if hit is None else Section(doc_rel, hit[0], hit[1], hit[2])


def lead_paragraph(doc_rel: str) -> str | None:
    """The first non-empty paragraph after the document's first heading (not a quote, table, list or comment)."""
    md = data.read_text(doc_rel)
    if md is None:
        return None
    lines = md.splitlines()
    hs = headings(md)
    start = hs[0][0] + 1 if hs else 0
    para: list[str] = []
    for line in lines[start:]:
        s = line.strip()
        if not s:
            if para:
                break
            continue
        if _HEADING.match(line) or s.startswith(("|", ">", "<!--", "- ", "* ", "!")):
            if para:
                break
            continue
        para.append(s)
    return " ".join(para) or None


def _target_repr(text: str, rel: str) -> str:
    base = os.environ.get("DESK_APP_REPO_URL", "").rstrip("/")
    if base:
        return f"[{text}]({base}/{rel})"
    plain = text.replace("`", "").strip()
    if plain in (rel, rel.rsplit("/", 1)[-1]):
        return f"`{rel}`"
    return f"{text} (`{rel}`)"


def rewrite_links(md: str, doc_rel: str) -> str:
    """Make a doc's relative links and images meaningful inside the app (see module docstring)."""

    def image(m: re.Match) -> str:
        alt, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://")):
            return m.group(0)
        rel = data.rel_join(doc_rel, target.split("#")[0])
        return f"*(chart: {alt + ', ' if alt else ''}`{rel or target}`)*"

    def link(m: re.Match) -> str:
        text, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://", "mailto:")):
            return m.group(0)
        if target.startswith("#"):
            return text
        rel = data.rel_join(doc_rel, target.split("#")[0])
        return text if rel is None else _target_repr(text, rel)

    return _LINK.sub(link, _IMAGE.sub(image, md))


def escape_streamlit(md: str) -> str:
    """Escape `$` (Streamlit renders $…$ as LaTeX) and `~` (GFM strikethrough) outside code; drop HTML comments."""
    out, fenced = [], False
    for line in re.sub(r"<!--.*?-->", "", md, flags=re.S).splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            out.append(line)
            continue
        if fenced:
            out.append(line)
            continue
        parts, last = [], 0
        for m in _CODE_SPAN.finditer(line):
            parts.append(_escape_plain(line[last:m.start()]))
            parts.append(m.group(0))
            last = m.end()
        parts.append(_escape_plain(line[last:]))
        out.append("".join(parts))
    return "\n".join(out)


def _escape_plain(s: str) -> str:
    return re.sub(r"(?<!\\)([$~])", r"\\\1", s)


def for_streamlit(md: str, doc_rel: str) -> str:
    """rewrite_links + escape_streamlit: ready for st.markdown."""
    return escape_streamlit(rewrite_links(md, doc_rel))
