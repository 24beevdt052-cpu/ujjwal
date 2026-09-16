"""Small shared markdown-ish -> PDF renderer (reportlab) for every report in the pack.

Why this exists: the risk memo, the weekly desk notes and the post-mortem are all written as Markdown first (so they
diff cleanly in git and read on GitHub) and must also ship as PDFs that carry the simulation label on every page
(CONTRACTS §1.1). One renderer keeps their look, footer and determinism identical.

Usage
-----
    from desk.reporting.pdf import render_markdown_pdf, PdfStyle
    n_pages = render_markdown_pdf(md_text, "outputs/reports/x.pdf", title="Risk policy memo")

Supported Markdown subset (anything else is rendered as plain paragraph text):

    # Title / ## Heading / ### Sub-heading
    blank-line separated paragraphs (consecutive lines are joined)
    - bullet  or  * bullet    (continuation lines indented by two or more spaces)
    1. numbered item
    > callout paragraph        (shaded box; consecutive '>' lines are joined)
    | a | b |  pipe tables     (header row, a |---|:--:|--:| separator row, body rows; ':' sets alignment;
                               write \\| for a literal pipe inside a cell)
    <!-- widths: 0.2, 0.5, 0.3 -->   optional, immediately before a table: relative column widths
    ---                        horizontal rule
    inline: **bold**, *italic* or _italic_, `code`
    <!-- any other comment -->  ignored

Design choices worth knowing:

* **Fonts.** reportlab's built-in Helvetica has no rupee sign (U+20B9) and no true minus (U+2212), both of which this
  project prints everywhere. The renderer embeds DejaVu Sans from matplotlib's own `mpl-data` folder — a pinned
  dependency, so every machine renders the same glyphs without a system font lookup.
* **Determinism.** Documents are built with reportlab's `invariant=True`, which fixes the creation date and file id,
  so re-running a stage reproduces the PDF byte-for-byte (CONTRACTS §1.5).
* **Footer.** Every page carries `desk.SIM_LABEL` on the left and "Page n of N" on the right. N is known only after
  layout, so pages are buffered by `_NumberedCanvas` and stamped at save time; the same count is returned to the
  caller, which lets a stage assert a one-page limit without parsing the PDF.
* **Alignment.** Documents are built on `DeskDocTemplate`, whose frame has no inner padding, so paragraphs, tables,
  side-by-side figure rows and the footer all share the same left and right edges (reportlab's default frame pads text
  by 6 pt but not the full-width tables, which then overhang the text column on both sides). Callout boxes are inset
  so their border, not their text, sits on those edges.
* **Page flow.** Headings are kept with what follows them. A style with `keep_sections=True` also keeps each `##`
  section together when it fits on one page (used by the question-by-question interview pack).
* `count_pdf_pages(path)` re-counts from the file bytes (page objects), for tests that should not trust the renderer.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from desk import SIM_LABEL

_FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
_FONT_FILES = {
    "DeskSans": "DejaVuSans.ttf",
    "DeskSans-Bold": "DejaVuSans-Bold.ttf",
    "DeskSans-Oblique": "DejaVuSans-Oblique.ttf",
    "DeskSans-BoldOblique": "DejaVuSans-BoldOblique.ttf",
    "DeskMono": "DejaVuSansMono.ttf",
}
_fonts_registered = False


def register_fonts() -> None:
    """Embed the DejaVu faces once per process and map <b>/<i> onto them."""
    global _fonts_registered
    if _fonts_registered:
        return
    for name, fname in _FONT_FILES.items():
        pdfmetrics.registerFont(TTFont(name, str(_FONT_DIR / fname)))
    pdfmetrics.registerFontFamily("DeskSans", normal="DeskSans", bold="DeskSans-Bold", italic="DeskSans-Oblique",
                                  boldItalic="DeskSans-BoldOblique")
    _fonts_registered = True


@dataclass
class PdfStyle:
    """Layout knobs. Defaults suit a dense one-page desk memo on A4; notes can raise the font size."""

    pagesize: tuple[float, float] = A4
    margin_left_mm: float = 13.0
    margin_right_mm: float = 13.0
    margin_top_mm: float = 11.0
    margin_bottom_mm: float = 13.0
    font_size: float = 8.0
    leading_ratio: float = 1.22
    title_size: float = 12.5
    h2_size: float = 9.2
    h3_size: float = 8.4
    table_font_size: float = 7.2
    footer_font_size: float = 6.5
    paragraph_space_after: float = 2.6
    heading_space_before: float = 4.0
    accent: colors.Color = field(default_factory=lambda: colors.HexColor("#1f4e79"))
    rule_color: colors.Color = field(default_factory=lambda: colors.HexColor("#9fb4cc"))
    table_header_bg: colors.Color = field(default_factory=lambda: colors.HexColor("#dbe5f1"))
    table_grid: colors.Color = field(default_factory=lambda: colors.HexColor("#b7c3d0"))
    callout_bg: colors.Color = field(default_factory=lambda: colors.HexColor("#f3f6fa"))
    footer_color: colors.Color = field(default_factory=lambda: colors.HexColor("#7f7f7f"))
    keep_sections: bool = False     # keep each "##" section on one page when it fits


CALLOUT_PAD = (2.5, 3.0, 2.5, 3.0)  # top, right, bottom, left (pt): the box's padding around the callout text
CALLOUT_GAP = 3.0                   # visible gap between two stacked callout boxes, pt


# ------------------------------------------------------------------------------------------------ inline markup
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL_STAR = re.compile(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])")
_ITAL_UND = re.compile(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])")


def inline_markup(text: str) -> str:
    """Markdown inline syntax -> reportlab paragraph XML. Escapes &, <, > first so data text can never inject tags."""
    out = html.escape(text, quote=False)
    codes: list[str] = []

    def _stash(m: re.Match) -> str:
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    out = _CODE.sub(_stash, out)
    out = _BOLD.sub(r"<b>\1</b>", out)
    out = _ITAL_STAR.sub(r"<i>\1</i>", out)
    out = _ITAL_UND.sub(r"<i>\1</i>", out)
    for i, c in enumerate(codes):
        out = out.replace(f"\x00{i}\x00", f'<font name="DeskMono">{c}</font>')
    return out


# ------------------------------------------------------------------------------------------------ block parsing
@dataclass
class Block:
    kind: str                       # title | h2 | h3 | para | bullets | numbers | callout | table | rule
    text: str = ""
    items: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    align: list[str] = field(default_factory=list)
    widths: list[float] | None = None


_TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_WIDTHS = re.compile(r"^<!--\s*widths:\s*([0-9.,\s]+)-->\s*$")
_BULLET = re.compile(r"^[-*]\s+(.*)$")
_NUMBER = re.compile(r"^\d+[.)]\s+(.*)$")


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def parse_markdown(md: str) -> list[Block]:
    """Line-oriented parser for the subset documented in the module docstring."""
    lines = md.replace("\r\n", "\n").split("\n")
    blocks: list[Block] = []
    pending_widths: list[float] | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        wm = _WIDTHS.match(s)
        if wm:
            pending_widths = [float(x) for x in wm.group(1).replace(" ", "").split(",") if x]
            i += 1
            continue
        if s.startswith("<!--"):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue
        if s.startswith("### "):
            blocks.append(Block("h3", s[4:]))
            i += 1
            continue
        if s.startswith("## "):
            blocks.append(Block("h2", s[3:]))
            i += 1
            continue
        if s.startswith("# "):
            blocks.append(Block("title", s[2:]))
            i += 1
            continue
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", s):
            blocks.append(Block("rule"))
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1].strip()):
            header = _split_row(s)
            align = []
            for spec in _split_row(lines[i + 1]):
                spec = spec.strip()
                align.append("CENTER" if spec.startswith(":") and spec.endswith(":")
                             else "RIGHT" if spec.endswith(":") else "LEFT")
            rows = [header]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            n = len(header)
            rows = [(r + [""] * n)[:n] for r in rows]
            blocks.append(Block("table", rows=rows, align=(align + ["LEFT"] * n)[:n], widths=pending_widths))
            pending_widths = None
            continue
        if s.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            blocks.append(Block("callout", " ".join(b for b in buf if b)))
            continue
        bm, nm = _BULLET.match(s), _NUMBER.match(s)
        if bm or nm:
            kind = "bullets" if bm else "numbers"
            pat = _BULLET if bm else _NUMBER
            items: list[str] = []
            while i < len(lines):
                cur = lines[i]
                m = pat.match(cur.strip())
                if m and not cur.startswith("  "):
                    items.append(m.group(1))
                elif cur.startswith("  ") and cur.strip() and items:
                    items[-1] += " " + cur.strip()
                else:
                    break
                i += 1
            blocks.append(Block(kind, items=items))
            continue
        buf = [s]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith(("#", "|", ">", "<!--")) or _BULLET.match(nxt) or _NUMBER.match(nxt)
                    or re.fullmatch(r"-{3,}", nxt)):
                break
            buf.append(nxt)
            i += 1
        blocks.append(Block("para", " ".join(buf)))
    return blocks


# ------------------------------------------------------------------------------------------------ flowables
def _styles(st: PdfStyle) -> dict[str, ParagraphStyle]:
    lead = st.leading_ratio
    base = ParagraphStyle("body", fontName="DeskSans", fontSize=st.font_size, leading=st.font_size * lead,
                          spaceAfter=st.paragraph_space_after, alignment=TA_LEFT)
    return {
        "body": base,
        "title": ParagraphStyle("title", parent=base, fontName="DeskSans-Bold", fontSize=st.title_size,
                                leading=st.title_size * 1.18, textColor=st.accent, spaceAfter=2.5),
        "h2": ParagraphStyle("h2", parent=base, fontName="DeskSans-Bold", fontSize=st.h2_size,
                             leading=st.h2_size * 1.2, textColor=st.accent, spaceBefore=st.heading_space_before,
                             spaceAfter=1.6, keepWithNext=1),
        "h3": ParagraphStyle("h3", parent=base, fontName="DeskSans-Bold", fontSize=st.h3_size,
                             leading=st.h3_size * 1.2, spaceBefore=st.heading_space_before * 0.6, spaceAfter=1.2,
                             keepWithNext=1),
        # reportlab collapses adjacent spaceAfter/spaceBefore to the larger one, and the box padding eats into it, so
        # the spacing is padding + gap; the indents put the box border (not the text) on the column edges
        "callout": ParagraphStyle("callout", parent=base, backColor=st.callout_bg, borderPadding=CALLOUT_PAD,
                                  borderColor=st.rule_color, borderWidth=0.4, leftIndent=CALLOUT_PAD[3],
                                  rightIndent=CALLOUT_PAD[1], spaceBefore=CALLOUT_PAD[0] + CALLOUT_PAD[2] + CALLOUT_GAP,
                                  spaceAfter=CALLOUT_PAD[0] + CALLOUT_PAD[2] + CALLOUT_GAP),
        "bullet": ParagraphStyle("bullet", parent=base, spaceAfter=0.9),
        "cell": ParagraphStyle("cell", parent=base, fontSize=st.table_font_size,
                               leading=st.table_font_size * 1.17, spaceAfter=0),
        "cell_head": ParagraphStyle("cell_head", parent=base, fontName="DeskSans-Bold", fontSize=st.table_font_size,
                                    leading=st.table_font_size * 1.17, spaceAfter=0),
    }


def _table(block: Block, st: PdfStyle, S: dict[str, ParagraphStyle], avail_w: float) -> Table:
    n = len(block.rows[0])
    if block.widths and len(block.widths) == n:
        rel = block.widths
    else:
        # proportional to the longest cell text per column, floored so a narrow column still wraps legibly
        rel = [max(4, max(len(r[c]) for r in block.rows)) ** 0.8 for c in range(n)]
    tot = sum(rel)
    widths = [avail_w * w / tot for w in rel]
    aligns = {"LEFT": TA_LEFT, "RIGHT": TA_RIGHT, "CENTER": TA_CENTER}
    data = []
    for ri, row in enumerate(block.rows):
        cells = []
        for ci, txt in enumerate(row):
            base = S["cell_head"] if ri == 0 else S["cell"]
            ps = ParagraphStyle(f"c{ri}_{ci}", parent=base, alignment=aligns[block.align[ci]])
            cells.append(Paragraph(inline_markup(txt), ps))
        data.append(cells)
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), st.table_header_bg),
        ("GRID", (0, 0), (-1, -1), 0.3, st.table_grid),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.4),
    ]))
    return t


def markdown_to_flowables(md: str, style: PdfStyle | None = None) -> list:
    """Parse `md` and return reportlab flowables (exposed so a caller can prepend its own header block)."""
    register_fonts()
    st = style or PdfStyle()
    S = _styles(st)
    avail_w = st.pagesize[0] - (st.margin_left_mm + st.margin_right_mm) * mm
    out: list = []
    sections: list[tuple[int, int]] = []            # (start index, end index) of each "##" section in `out`
    for b in parse_markdown(md):
        if b.kind in ("title", "h2") and sections and sections[-1][1] < 0:
            sections[-1] = (sections[-1][0], len(out))
        if b.kind == "h2":
            sections.append((len(out), -1))
        if b.kind in ("title", "h2", "h3"):
            out.append(Paragraph(inline_markup(b.text), S[b.kind]))
        elif b.kind == "para":
            out.append(Paragraph(inline_markup(b.text), S["body"]))
        elif b.kind == "callout":
            out.append(Paragraph(inline_markup(b.text), S["callout"]))
        elif b.kind == "rule":
            out.append(HRFlowable(width="100%", thickness=0.5, color=st.rule_color, spaceBefore=1.5, spaceAfter=2.5))
        elif b.kind in ("bullets", "numbers"):
            indent = 9 if b.kind == "bullets" else 11.5         # "1." is wider than "•"
            items = [ListItem(Paragraph(inline_markup(t), S["bullet"]), leftIndent=indent) for t in b.items]
            kw = dict(bulletType="bullet", start="•") if b.kind == "bullets" else dict(bulletType="1",
                                                                                       bulletFormat="%s.")
            out.append(ListFlowable(items, leftIndent=indent, bulletFontName="DeskSans",
                                    bulletFontSize=st.font_size * 0.9, spaceAfter=st.paragraph_space_after, **kw))
        elif b.kind == "table":
            out.append(_table(b, st, S, avail_w))
            out.append(Spacer(1, st.paragraph_space_after + 1))
    if st.keep_sections and sections:
        if sections[-1][1] < 0:
            sections[-1] = (sections[-1][0], len(out))
        for start, end in reversed(sections):
            out[start:end] = [KeepTogether(out[start:end])]
    return out


class DeskDocTemplate(BaseDocTemplate):
    """One A4 page template whose frame has no inner padding: text, tables, figures and footer share both edges."""

    def __init__(self, filename: str, style: PdfStyle, **meta):
        super().__init__(filename, pagesize=style.pagesize, leftMargin=style.margin_left_mm * mm,
                         rightMargin=style.margin_right_mm * mm, topMargin=style.margin_top_mm * mm,
                         bottomMargin=style.margin_bottom_mm * mm, invariant=True, **meta)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal", leftPadding=0,
                      rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="page", frames=[frame], pagesize=style.pagesize)])


# ------------------------------------------------------------------------------------------------ canvas + build
def _numbered_canvas_class(footer_text: str, st: PdfStyle, sink: list[int]):
    """A canvas that buffers pages so the footer can say 'Page n of N' (N unknown until the build ends)."""

    class _NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_pages: list[dict] = []

        def showPage(self):  # noqa: N802 (reportlab API name)
            self._saved_pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_pages)
            sink.append(total)
            for state in self._saved_pages:
                self.__dict__.update(state)
                self._draw_footer(total)
                super().showPage()
            super().save()

        def _draw_footer(self, total: int) -> None:
            w, _h = st.pagesize
            y = st.margin_bottom_mm * mm * 0.45
            self.setFont("DeskSans", st.footer_font_size)
            self.setFillColor(st.footer_color)
            self.drawString(st.margin_left_mm * mm, y, footer_text)
            self.drawRightString(w - st.margin_right_mm * mm, y, f"Page {self._pageNumber} of {total}")

    return _NumberedCanvas


def render_markdown_pdf(md: str, out_path: str | Path, *, title: str = "", author: str = "", subject: str = SIM_LABEL,
                        style: PdfStyle | None = None, footer_text: str = SIM_LABEL) -> int:
    """Render `md` to `out_path` and return the number of pages written.

    The footer always contains `footer_text`, which defaults to the simulation label; a caller that passes its own
    text must keep the label in it (asserted here, because a PDF without it breaks CONTRACTS §1.1).
    """
    if SIM_LABEL not in footer_text:
        raise ValueError("footer_text must contain desk.SIM_LABEL (CONTRACTS §1.1)")
    register_fonts()
    st = style or PdfStyle()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = DeskDocTemplate(str(out_path), st, title=title, author=author, subject=subject, creator="desk.reporting.pdf")
    sink: list[int] = []
    doc.build(markdown_to_flowables(md, st), canvasmaker=_numbered_canvas_class(footer_text, st, sink))
    return sink[-1] if sink else 0


_PAGE_OBJ = re.compile(rb"/Type\s*/Page(?![a-zA-Z])")


def count_pdf_pages(path: str | Path) -> int:
    """Count page objects in a PDF file's bytes (reportlab writes page dictionaries uncompressed)."""
    return len(_PAGE_OBJ.findall(Path(path).read_bytes()))
