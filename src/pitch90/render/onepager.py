"""Investor-facing one-page PDF (US Letter, two columns).

Layout is measured before drawing. Content is fitted by choosing the column split and
stepping the body size down to the 9 pt minimum; if it still does not fit, nothing is
rendered and the caller gets a FitReport naming the sections to shorten. Text is never
clipped and a second page is never added.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from pitch90.evidence import is_missing_value
from pitch90.models import NOT_PROVIDED, LLMOnePager, OnePagerSection
from pitch90.render.fonts import BOLD, ITALIC, REGULAR, register_fonts
from pitch90.scoring import word_count

PAGE_W, PAGE_H = LETTER
MARGIN = 36.0
GUTTER = 20.0
COL_W = (PAGE_W - 2 * MARGIN - GUTTER) / 2
FOOTER_H = 22.0
BODY_SIZES = (10.0, 9.5, 9.0)
MIN_BODY_SIZE = 9.0
TITLE_SIZES = (22.0, 20.0, 18.0, 16.0, 14.0)

NAVY = HexColor("#1F3A5F")
INK = HexColor("#222222")
MUTED = HexColor("#6B7280")
RULE = HexColor("#C9D3E0")

FOOTER_TEXT = "Confidential – for recipients only."

# Section keys in reading order, with headings.
SECTIONS = [
    ("problem_why_now", "Problem & Why Now"),
    ("solution_benefit", "Solution & Customer Benefit"),
    ("market_business_model", "Market & Business Model"),
    ("differentiation", "Differentiation"),
    ("traction_evidence", "Traction & Evidence"),
    ("team", "Team"),
    ("raise", "The Raise"),
    ("exit_strategy", "Exit Strategy"),
    ("contact", "Contact"),
]
RAISE_FIELDS = [
    ("fundraising_target", "Target"),
    ("terms", "Terms"),
    ("use_of_funds", "Use of funds"),
    ("milestones", "Milestones"),
]
# Sections whose trailing sentences may be dropped by auto-shorten, lowest priority first.
SHORTEN_ORDER = [
    "exit_strategy", "differentiation", "market_business_model", "solution_benefit",
    "problem_why_now", "milestones", "use_of_funds", "traction_evidence",
]


@dataclass
class FitReport:
    fits: bool
    body_size: float | None = None
    overflow_points: float = 0.0
    suggestions: list[tuple[str, int, int]] = field(default_factory=list)  # (field, words, cut)
    message: str = ""


def _cite(pages: list[int], prefix: str) -> str:
    if not pages:
        return ""
    sep = "" if prefix == "S" else " "
    refs = ", ".join(f"{prefix}{sep}{p}" for p in sorted(set(pages)))
    return f' <font color="#6B7280">[{escape(refs)}]</font>'


def _styles(body: float) -> dict[str, ParagraphStyle]:
    lead = round(body * 1.25, 2)
    return {
        "body": ParagraphStyle("body", fontName=REGULAR, fontSize=body, leading=lead,
                               textColor=INK, alignment=TA_LEFT, splitLongWords=1),
        "head": ParagraphStyle("head", fontName=BOLD, fontSize=body + 1.5, leading=(body + 1.5) * 1.2,
                               textColor=NAVY, splitLongWords=1),
        "item": ParagraphStyle("item", fontName=REGULAR, fontSize=body, leading=lead, textColor=INK,
                               leftIndent=8, firstLineIndent=-8, splitLongWords=1),
    }


def _has(section: OnePagerSection) -> bool:
    return not is_missing_value(section.text)


def _section_paragraphs(key: str, op: LLMOnePager, st: dict, prefix: str) -> list[Paragraph] | None:
    if key == "team":
        if not op.team:
            return [Paragraph(NOT_PROVIDED, st["body"])]
        return [
            Paragraph(f"• <b>{escape(m.name)}</b>, {escape(m.role)} – "
                      f"{escape(m.qualifications)}{_cite(m.citations, prefix)}", st["item"])
            for m in op.team
        ]
    if key == "raise":
        return [
            Paragraph(f"<b>{label}:</b> {escape(getattr(op, f).text)}{_cite(getattr(op, f).citations, prefix)}",
                      st["item"])
            for f, label in RAISE_FIELDS
        ]
    section: OnePagerSection = getattr(op, key)
    if key in ("exit_strategy", "contact") and not _has(section):
        return None  # only shown when supplied in the source
    return [Paragraph(escape(section.text) + _cite(section.citations, prefix), st["body"])]


def _measure(paras: list, width: float) -> float:
    return sum(p.wrap(width, 10_000)[1] for p in paras)


@dataclass
class _Block:
    key: str
    heading: Paragraph
    paras: list[Paragraph]
    height: float


def _header(op: LLMOnePager, body: float) -> tuple[list[Paragraph], float]:
    width = PAGE_W - 2 * MARGIN
    title = None
    for size in TITLE_SIZES:
        style = ParagraphStyle("title", fontName=BOLD, fontSize=size, leading=size * 1.15,
                               textColor=NAVY, splitLongWords=1)
        title = Paragraph(escape(op.company_name), style)
        if title.wrap(width, 10_000)[1] <= size * 1.15 * 2 + 0.1:
            break
    paras = [title]
    if not is_missing_value(op.website):
        paras.append(Paragraph(escape(op.website), ParagraphStyle(
            "site", fontName=REGULAR, fontSize=body, leading=body * 1.3, textColor=MUTED, splitLongWords=1)))
    if _has(op.positioning):
        paras.append(Paragraph(escape(op.positioning.text), ParagraphStyle(
            "pos", fontName=ITALIC, fontSize=body + 1.5, leading=(body + 1.5) * 1.25, textColor=INK,
            spaceBefore=2, splitLongWords=1)))
    height = sum(p.wrap(width, 10_000)[1] for p in paras) + 4 * (len(paras) - 1) + 10
    return paras, height


def _plan(op: LLMOnePager, body: float, prefix: str):
    st = _styles(body)
    header, header_h = _header(op, body)
    col_h = PAGE_H - 2 * MARGIN - FOOTER_H - header_h
    gap_head, gap_section, gap_item = 2.0, body * 0.9, 1.5
    blocks: list[_Block] = []
    for key, title in SECTIONS:
        paras = _section_paragraphs(key, op, st, prefix)
        if paras is None:
            continue
        heading = Paragraph(title.upper(), st["head"])
        h = heading.wrap(COL_W, 10_000)[1] + gap_head + _measure(paras, COL_W) + gap_item * (len(paras) - 1)
        blocks.append(_Block(key, heading, paras, h + gap_section))
    best = None
    for k in range(1, len(blocks)):
        left = sum(b.height for b in blocks[:k])
        right = sum(b.height for b in blocks[k:])
        over = max(left - col_h, right - col_h, 0)
        score = (over, max(left, right))
        if best is None or score < best[0]:
            best = (score, k)
    if best is None:  # a single block: everything in the left column
        best = ((max(blocks[0].height - col_h, 0), blocks[0].height), 1)
    (overflow, _), split = best
    return header, header_h, blocks, split, overflow, col_h, (gap_head, gap_item)


def _suggest(op: LLMOnePager, overflow: float, body: float) -> list[tuple[str, int, int]]:
    words_per_line = max(int(COL_W / (body * 0.47) / 6.2), 6)
    words_needed = int(overflow / (body * 1.25) + 1) * words_per_line
    sizes = []
    for f in ["problem_why_now", "solution_benefit", "market_business_model", "differentiation",
              "traction_evidence", "exit_strategy", "fundraising_target", "terms", "use_of_funds",
              "milestones", "positioning"]:
        sizes.append((f, word_count(getattr(op, f).text)))
    sizes.append(("team", sum(word_count(m.qualifications) + 3 for m in op.team)))
    sizes.sort(key=lambda s: s[1], reverse=True)
    out, remaining = [], words_needed
    for name, words in sizes:
        if remaining <= 0 or words < 15:
            break
        cut = min(max(remaining, 5), words // 2)
        out.append((name, words, cut))
        remaining -= cut
    return out


def check_fit(op: LLMOnePager, cite_prefix: str = "S") -> FitReport:
    register_fonts()
    overflow = 0.0
    for body in BODY_SIZES:
        *_, overflow, _col, _gaps = _plan(op, body, cite_prefix)
        if overflow <= 0:
            return FitReport(fits=True, body_size=body)
    suggestions = _suggest(op, overflow, MIN_BODY_SIZE)
    names = ", ".join(f"{n} (about {c} words)" for n, _, c in suggestions) or "the longest sections"
    return FitReport(
        fits=False, overflow_points=round(overflow, 1), suggestions=suggestions,
        message=f"The content does not fit on one page at the 9 pt minimum (over by "
                f"{overflow:.0f} pt). Shorten: {names}.",
    )


def render_onepager(op: LLMOnePager, cite_prefix: str = "S") -> tuple[bytes | None, FitReport]:
    """Render the one-pager. Returns (pdf_bytes, report); pdf_bytes is None if it does not fit."""
    report = check_fit(op, cite_prefix)
    if not report.fits:
        return None, report
    body = report.body_size
    header, header_h, blocks, split, overflow, col_h, (gap_head, gap_item) = _plan(op, body, cite_prefix)
    assert overflow <= 0

    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER, pageCompression=1, initialFontName=REGULAR, initialFontSize=10)
    c.setTitle(f"{op.company_name} – Investor One-Pager")
    c.setAuthor(op.company_name)
    c.setSubject("Investor one-page summary")

    width = PAGE_W - 2 * MARGIN
    y = PAGE_H - MARGIN
    for p in header:
        _, h = p.wrap(width, 10_000)
        y -= h
        p.drawOn(c, MARGIN, y)
        y -= 4
    y -= 2
    c.setStrokeColor(RULE)
    c.setLineWidth(0.8)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    top = y - 8
    bottom = MARGIN + FOOTER_H

    for col, group in enumerate((blocks[:split], blocks[split:])):
        x = MARGIN + col * (COL_W + GUTTER)
        y = top
        for block in group:
            _, h = block.heading.wrap(COL_W, 10_000)
            y -= h
            block.heading.drawOn(c, x, y)
            y -= gap_head
            for i, p in enumerate(block.paras):
                _, h = p.wrap(COL_W, 10_000)
                y -= h
                if y < bottom - 0.5:
                    raise RuntimeError("Layout overflow detected during drawing")  # never clip
                p.drawOn(c, x, y)
                if i < len(block.paras) - 1:
                    y -= gap_item
            y -= body * 0.9

    c.setStrokeColor(RULE)
    c.line(MARGIN, MARGIN + 12, PAGE_W - MARGIN, MARGIN + 12)
    c.setFont(REGULAR, 7.5)
    c.setFillColor(MUTED)
    c.drawCentredString(PAGE_W / 2, MARGIN, FOOTER_TEXT)
    if cite_prefix:
        unit = "slide" if cite_prefix == "S" else "page"
        c.drawRightString(PAGE_W - MARGIN, MARGIN, f"[{cite_prefix}{'' if cite_prefix == 'S' else ' '}n] = source deck {unit} n")
    c.showPage()
    c.save()
    return buf.getvalue(), report


_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9$\"'])")


def shorten_to_fit(op: LLMOnePager, cite_prefix: str = "S", max_steps: int = 40
                   ) -> tuple[LLMOnePager, list[str], FitReport]:
    """Drop trailing sentences from lower-priority sections until the page fits.

    Whole sentences only; never truncates mid-sentence. Returns the shortened copy,
    a list of change descriptions (for the edit log), and the final FitReport.
    """
    op = op.model_copy(deep=True)
    changes: list[str] = []
    report = check_fit(op, cite_prefix)
    steps = 0
    while not report.fits and steps < max_steps:
        steps += 1
        candidates = []
        for name in SHORTEN_ORDER:
            sentences = _SENTENCE.split(getattr(op, name).text.strip())
            if len(sentences) > 1:
                candidates.append((name, sentences))
        if not candidates:
            if len(op.team) > 4:
                removed = op.team.pop()
                changes.append(f"Removed team member '{removed.name}' to fit the page.")
                report = check_fit(op, cite_prefix)
                continue
            break
        # Lowest priority first, but prefer the longest candidate among the first three.
        name, sentences = max(candidates[:3], key=lambda c: word_count(" ".join(c[1])))
        section = getattr(op, name)
        dropped = sentences.pop()
        section.text = " ".join(sentences)
        changes.append(f"Shortened '{name}': removed sentence \"{dropped[:80]}\"")
        report = check_fit(op, cite_prefix)
    return op, changes, report
