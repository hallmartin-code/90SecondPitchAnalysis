"""Internal analysis report (multi-page PDF) and JSON export.

Kept separate from the investor one-pager: it contains scores, critique, evidence
checks and user edits. The document structure (section order, headings, notes,
table columns and line formats) comes from a Markdown template, by default
templates/analysis_report.md; this module only supplies the data and the styling.
The footer follows the TEN Capital pattern from the project CLAUDE.md:
[Document Title]  [PAGE#]  Compiled on [DATE] by TEN Capital Network  [logo].
"""

from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Table, TableStyle

from pitch90.config import ASSETS_DIR, TEMPLATES_DIR, get_settings
from pitch90.framework import ARTICLE_URL, ELEMENT_GUIDANCE, ELEMENT_TITLES, RUBRIC_LEVELS
from pitch90.models import AnalysisResult
from pitch90.render.fonts import BOLD, ITALIC, REGULAR, register_fonts
from pitch90.render.template import (
    PLACEHOLDER,
    DocumentTemplate,
    Section,
    load_template,
    validate_template,
)

NAVY = HexColor("#1F3A5F")
MUTED = HexColor("#6B7280")
GRID = HexColor("#D5DBE5")
SHADE = HexColor("#F2F5F9")
LOGO = ASSETS_DIR / "TEN_Capital_logo_footer.png"
DEFAULT_TEMPLATE = TEMPLATES_DIR / "analysis_report.md"

DOC_FIELDS = {
    "company_name", "source_filename", "mode", "model", "created_at", "disclaimer",
    "article_url", "unit", "unit_lower", "total_score", "max_score", "percentage",
    "word_count", "seconds", "words_per_minute", "pitch_target_note", "pitch_script", "date",
}
FOOTER_FIELDS = {"title", "page"}
_ELEMENT = {"n", "element_title", "guidance", "score", "rubric_level", "source_pages",
            "source_numbers", "rationale", "missing_or_weak", "improvement"}
ITEM_FIELDS: dict[str, set[str]] = {
    "header": set(),
    "pitch": set(),
    "score_summary": _ELEMENT,
    "element_assessments": _ELEMENT,
    "obstacle_capability_pairs": {"n", "obstacle", "capability", "source_pages", "source_numbers"},
    "strongest_points": {"n", "text", "source_pages", "source_numbers"},
    "priority_fixes": {"n", "text"},
    "inconsistencies": {"n", "description", "values", "source_pages", "source_numbers"},
    "extraction_limitations": {"n", "pages", "limitation", "effect"},
    "visual_observations": {"n", "page", "observation"},
    "information_gaps": {"n", "text"},
    "facts": {"id", "label", "value", "unit", "period", "basis", "commitment", "basis_commitment",
              "status", "source", "excerpt", "formula", "checks", "origin", "original_value",
              "value_display"},
    "validation_warnings": {"n", "text"},
    "onepager_edits": {"n", "field", "kind"},
    "extraction_warnings": {"n", "severity", "message", "units"},
}

_NUMBERED = re.compile(r"^(\d+|\{\{\s*item\.n\s*\}\})\.\s")
_SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")


# ------------------------------------------------------------------ data contexts


def _styles():
    return {
        "h1": ParagraphStyle("h1", fontName=BOLD, fontSize=18, leading=22, textColor=NAVY, spaceAfter=4),
        "h2": ParagraphStyle("h2", fontName=BOLD, fontSize=12.5, leading=16, textColor=NAVY,
                             spaceBefore=10, spaceAfter=4),
        "h3": ParagraphStyle("h3", fontName=BOLD, fontSize=10.5, leading=13, spaceBefore=6, spaceAfter=2),
        "body": ParagraphStyle("body", fontName=REGULAR, fontSize=9.5, leading=12.5, spaceAfter=3),
        "small": ParagraphStyle("small", fontName=REGULAR, fontSize=8.5, leading=10.5),
        "note": ParagraphStyle("note", fontName=ITALIC, fontSize=8.5, leading=11, textColor=MUTED, spaceAfter=4),
        "bullet": ParagraphStyle("bullet", fontName=REGULAR, fontSize=9.5, leading=12.5, leftIndent=10,
                                 firstLineIndent=-8, spaceAfter=2),
    }


def _pages(pages: list[int], label: str) -> str:
    return f"{label} {', '.join(map(str, pages))}" if pages else "–"


def _numbers(pages: list[int]) -> str:
    return ", ".join(map(str, pages)) if pages else "–"


def _contexts(result: AnalysisResult) -> tuple[dict, dict[str, list[dict] | None]]:
    unit = result.unit_label.capitalize()
    t = result.timing
    doc = {
        "company_name": result.company_name,
        "source_filename": result.source_filename,
        "mode": result.mode,
        "model": result.model or "none (demo)",
        "created_at": result.created_at,
        "disclaimer": result.disclaimer,
        "article_url": ARTICLE_URL,
        "unit": unit,
        "unit_lower": result.unit_label,
        "total_score": str(result.total_score),
        "max_score": str(result.max_score),
        "percentage": f"{result.percentage:.0f}",
        "word_count": str(t.word_count),
        "seconds": f"{t.seconds:.0f}",
        "words_per_minute": str(t.words_per_minute),
        "pitch_target_note": "" if t.within_target_words else " · outside the 180–210 word target",
        "pitch_script": result.pitch_script,
        "date": date.today().strftime("%B %d, %Y").replace(" 0", " "),
    }
    elements = [{
        "n": str(i), "element_title": ELEMENT_TITLES[e.element], "guidance": ELEMENT_GUIDANCE[e.element],
        "score": str(e.score), "rubric_level": RUBRIC_LEVELS[e.score],
        "source_pages": _pages(e.source_pages, unit), "source_numbers": _numbers(e.source_pages),
        "rationale": e.rationale, "missing_or_weak": list(e.missing_or_weak), "improvement": e.improvement,
    } for i, e in enumerate(result.elements, 1)]

    facts = []
    for f in result.facts:
        value = f.value + (f" {f.unit}" if f.unit and f.unit not in f.value else "")
        if f.formula:
            value += f" (formula: {f.formula})"
        if f.original_value:
            value += f" (deck value: {f.original_value})"
        user = f.origin.value == "user_provided"
        facts.append({
            "id": f.id, "label": f.label, "value": f.value, "unit": f.unit or "–",
            "period": f.period or "–", "basis": f.basis.value.replace("_", " "),
            "commitment": f.commitment.value.replace("_", " "),
            "basis_commitment": f"{f.basis.value} / {f.commitment.value}".replace("_", " "),
            "status": f.status.value, "source": "User-provided" if user else _pages(f.source_pages, unit),
            "excerpt": f.excerpt or "–", "formula": f.formula or "–",
            "checks": "; ".join(([f.citation_check.value.replace("_", " ")] if f.citation_check else []) + f.flags) or "–",
            "origin": f.origin.value, "original_value": f.original_value or "–", "value_display": value,
        })

    def numbered(items: list[dict]) -> list[dict]:
        return [{"n": str(i), **d} for i, d in enumerate(items, 1)]

    collections: dict[str, list[dict] | None] = {
        "header": None,
        "pitch": None,
        "score_summary": elements,
        "element_assessments": elements,
        "obstacle_capability_pairs": numbered([
            {"obstacle": p.obstacle, "capability": p.capability,
             "source_pages": _pages(p.source_pages, unit), "source_numbers": _numbers(p.source_pages)}
            for p in result.obstacle_capability_pairs]),
        "strongest_points": numbered([
            {"text": p.text, "source_pages": _pages(p.source_pages, unit), "source_numbers": _numbers(p.source_pages)}
            for p in result.strongest_points]),
        "priority_fixes": numbered([{"text": x} for x in result.priority_fixes]),
        "inconsistencies": numbered([
            {"description": i.description, "values": "; ".join(i.values),
             "source_pages": _pages(i.source_pages, unit), "source_numbers": _numbers(i.source_pages)}
            for i in result.inconsistencies]),
        "extraction_limitations": numbered([
            {"pages": _pages(l.pages, unit), "limitation": l.limitation, "effect": l.effect_on_evaluation}
            for l in result.extraction_limitations]),
        "visual_observations": numbered([
            {"page": str(v.page), "observation": v.observation} for v in result.visual_observations]),
        "information_gaps": numbered([{"text": g} for g in result.information_gaps]),
        "facts": facts,
        "validation_warnings": numbered([{"text": w} for w in result.validation_warnings]),
        "onepager_edits": numbered([{"field": k, "kind": v.replace("_", " ")}
                                    for k, v in sorted(result.onepager_edits.items())]),
        "extraction_warnings": numbered([
            {"severity": w.severity, "message": w.message, "units": _pages(w.units, unit)}
            for w in result.extraction_warnings]),
    }
    return doc, collections


# ------------------------------------------------------------------ template rendering


def _value(name: str, is_item: bool, doc: dict, item: dict | None):
    source = item if is_item else doc
    value = (source or {}).get(name)
    return "–" if value is None or value == "" and name != "pitch_target_note" else value


def _fill(text: str, doc: dict, item: dict | None, markup: bool = True) -> str:
    """Substitute placeholders; escape literal text and values; convert **bold**."""
    out, pos = [], 0
    for m in PLACEHOLDER.finditer(text):
        literal = text[pos:m.start()]
        out.append(escape(literal) if markup else literal)
        value = str(_value(m.group(2), bool(m.group(1)), doc, item))
        out.append(escape(value).replace("*", "&#42;") if markup else value)
        pos = m.end()
    rest = text[pos:]
    out.append(escape(rest) if markup else rest)
    joined = "".join(out)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", joined) if markup else joined


def _expand(line: str, doc: dict, item: dict | None) -> list[tuple[str, dict | None, dict]]:
    """Repeat a line once per entry of the first list-valued placeholder in it."""
    for m in PLACEHOLDER.finditer(line):
        is_item, name = bool(m.group(1)), m.group(2)
        value = _value(name, is_item, doc, item)
        if isinstance(value, list):
            out = []
            for entry in value:
                if is_item:
                    out.append((line, {**item, name: entry}, doc))
                else:
                    out.append((line, item, {**doc, name: entry}))
            return out
    return [(line, item, doc)]


def _is_item_line(line: str) -> bool:
    return any(m.group(1) for m in PLACEHOLDER.finditer(line))


def _render_line(line: str, doc: dict, item: dict | None, st: dict) -> list[Paragraph]:
    if line.startswith("### "):
        style, text = st["h3"], line[4:]
    elif line.startswith("> "):
        style, text = st["note"], line[2:]
    elif line.startswith("- "):
        style, text = st["bullet"], "– " + line[2:]
    elif _NUMBERED.match(line):
        style, text = st["bullet"], line
    else:
        style, text = st["body"], line
    return [Paragraph(_fill(t, d, i), style) for t, i, d in _expand(text, doc, item)]


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _render_table(rows: list[str], doc: dict, items: list[dict] | None, widths: list[float] | None,
                  total_width: float, st: dict) -> Table | None:
    header, body = rows[0], [r for r in rows[1:] if not _SEPARATOR.match(r)]
    data = [[Paragraph(_fill(c, doc, None), st["small"]) for c in _cells(header)]]
    item_rows = [r for r in body if _is_item_line(r)]
    if item_rows and not items:
        return None
    for row in body:
        contexts = items if _is_item_line(row) else [None]
        for ctx in contexts:
            data.append([Paragraph(_fill(c, doc, ctx), st["small"]) for c in _cells(row)])
    cols = len(data[0])
    rel = widths if widths and len(widths) == cols else [1.0] * cols
    col_widths = [total_width * w / sum(rel) for w in rel]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("FONTNAME", (0, 0), (-1, -1), REGULAR),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 0), (-1, 0), SHADE),
    ]))
    return table


def _render_section(section: Section, doc: dict, items: list[dict] | None, st: dict, width: float) -> list:
    if items is not None and not items and section.optional:
        return []
    out: list = []
    if section.heading:
        out.append(Paragraph(_fill(section.heading, doc, None), st["h2"]))
    empty_shown = False

    def show_empty():
        nonlocal empty_shown
        if section.empty_text and not empty_shown:
            out.append(Paragraph(escape(section.empty_text), st["body"]))
            empty_shown = True

    lines, i = section.lines, 0
    while i < len(lines):
        if lines[i].startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            table = _render_table(lines[i:j], doc, items, section.widths, width, st)
            out.append(table) if table is not None else show_empty()
            i = j
        elif _is_item_line(lines[i]):
            j = i
            while j < len(lines) and not lines[j].startswith("|") and _is_item_line(lines[j]):
                j += 1
            if items:
                for item in items:
                    block = [p for line in lines[i:j] for p in _render_line(line, doc, item, st)]
                    out.append(KeepTogether(block) if len(block) > 1 else block[0])
            else:
                show_empty()
            i = j
        else:
            out += _render_line(lines[i], doc, None, st)
            i += 1
    return out


def _footer_factory(pattern: str, doc: dict, title: str):
    def draw(canvas, page_doc):
        canvas.saveState()
        canvas.setFont(REGULAR, 7)
        canvas.setFillColor(MUTED)
        text = _fill(pattern, {**doc, "title": title, "page": str(page_doc.page)}, None, markup=False)
        logo_w, logo_h = 0.67 * inch, 0.25 * inch
        text_w = canvas.stringWidth(text, REGULAR, 7)
        total = text_w + 6 + (logo_w if LOGO.exists() else 0)
        x = (LETTER[0] - total) / 2
        y = 0.45 * inch
        canvas.drawString(x, y + 6, text)
        if LOGO.exists():
            canvas.drawImage(str(LOGO), x + text_w + 6, y, width=logo_w, height=logo_h,
                             mask="auto", preserveAspectRatio=True)
        canvas.restoreState()

    return draw


def get_report_template(path: Path | None = None) -> DocumentTemplate:
    """Load and validate a report template.

    Order of precedence: ``path``, then PITCH90_REPORT_TEMPLATE, then templates/analysis_report.md.
    """
    template = load_template(path or get_settings().report_template or DEFAULT_TEMPLATE)
    validate_template(template, DOC_FIELDS, ITEM_FIELDS, FOOTER_FIELDS)
    return template


def render_report(result: AnalysisResult, template: DocumentTemplate | Path | None = None) -> bytes:
    register_fonts()
    if not isinstance(template, DocumentTemplate):
        template = get_report_template(template)
    st = _styles()
    doc, collections = _contexts(result)
    title = _fill(template.meta.get("title") or template.title, doc, None, markup=False)
    width = LETTER[0] - 1.5 * inch

    story: list = []
    if template.title:
        story.append(Paragraph(_fill(template.title, doc, None), st["h1"]))
    for section in template.sections:
        story += _render_section(section, doc, collections[section.id], st, width)

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.9 * inch, title=title,
                            author="TEN Capital Network")
    footer = _footer_factory(template.meta.get("footer", "{{title}}     {{page}}"), doc, title)
    pdf.build(story, onFirstPage=footer, onLaterPages=footer,
              canvasmaker=lambda *a, **k: Canvas(*a, **{**k, "initialFontName": REGULAR}))
    return buf.getvalue()


def export_json(result: AnalysisResult) -> str:
    return result.model_dump_json(indent=2)
