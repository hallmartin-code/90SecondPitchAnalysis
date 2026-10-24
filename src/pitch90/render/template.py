"""Parse and validate Markdown document-structure templates.

A template fixes a document's section order, headings, notes, table columns and line
formats using {{placeholders}}; the renderer supplies the data. See
templates/analysis_report.md for the syntax.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{\s*(item\.)?([a-z_]+)\s*\}\}")
_DIRECTIVE = re.compile(r"^<!--\s*(section|if-empty|widths|guide)\s*:\s*(.*?)\s*-->$", re.S)


class TemplateError(ValueError):
    """The template is malformed or references unknown sections or fields."""


@dataclass
class Section:
    id: str
    heading: str | None
    optional: bool = False
    lines: list[str] = field(default_factory=list)
    empty_text: str | None = None
    widths: list[float] | None = None


@dataclass
class DocumentTemplate:
    meta: dict[str, str]
    title: str
    sections: list[Section]

    def section(self, section_id: str) -> Section | None:
        return next((s for s in self.sections if s.id == section_id), None)


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        raise TemplateError("Front matter starts with '---' but is never closed.")
    meta = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"')
    return meta, text[end + 4:]


def parse_template(text: str) -> DocumentTemplate:
    meta, body = _front_matter(text.lstrip("﻿"))
    title = ""
    sections: list[Section] = []
    heading: str | None = None
    current: Section | None = None
    comment: list[str] | None = None

    for raw in body.splitlines():
        line = raw.rstrip()
        if comment is not None:  # inside a multi-line comment: skip, it is documentation
            if "-->" in line:
                comment = None
            continue
        stripped = line.strip()
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                comment = [stripped]
                continue
            match = _DIRECTIVE.match(stripped)
            if not match:
                continue
            kind, value = match.groups()
            if kind == "section":
                parts = value.split()
                if not parts:
                    raise TemplateError("Section marker without an id.")
                current = Section(id=parts[0], heading=heading, optional="optional" in parts[1:])
                sections.append(current)
                heading = None
            elif current is None:
                raise TemplateError(f"'{kind}' directive appears before any section marker.")
            elif kind == "if-empty":
                current.empty_text = value
            elif kind == "widths":
                try:
                    current.widths = [float(w) for w in value.split(",")]
                except ValueError as exc:
                    raise TemplateError(f"Invalid widths in section '{current.id}': {value}") from exc
            continue
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            continue
        if stripped.startswith("## "):
            heading, current = stripped[3:].strip(), None
            continue
        if not stripped:
            continue
        if current is None:
            raise TemplateError(f"Content outside a section: {stripped[:60]!r}")
        current.lines.append(stripped)

    if comment is not None:
        raise TemplateError("Unclosed HTML comment.")
    ids = [s.id for s in sections]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise TemplateError(f"Duplicate section id(s): {sorted(duplicates)}")
    return DocumentTemplate(meta=meta, title=title, sections=sections)


def validate_template(
    template: DocumentTemplate,
    doc_fields: set[str],
    item_fields: dict[str, set[str]],
    footer_fields: set[str] = frozenset(),
) -> None:
    """Raise TemplateError for unknown sections or placeholders, so typos fail early."""
    problems: list[str] = []
    for key in ("title", "footer"):
        allowed = doc_fields | (footer_fields if key == "footer" else set())
        for item, name in PLACEHOLDER.findall(template.meta.get(key, "")):
            if item or name not in allowed:
                problems.append(f"front matter '{key}': unknown placeholder {{{{{item}{name}}}}}")
    for item, name in PLACEHOLDER.findall(template.title):
        if item or name not in doc_fields:
            problems.append(f"title: unknown placeholder {{{{{item}{name}}}}}")
    for section in template.sections:
        if section.id not in item_fields:
            problems.append(f"unknown section id '{section.id}'")
            continue
        allowed_items = item_fields[section.id]
        for line in section.lines:
            for item, name in PLACEHOLDER.findall(line):
                if item and name not in allowed_items:
                    problems.append(f"section '{section.id}': unknown item field '{name}'")
                elif not item and name not in doc_fields:
                    problems.append(f"section '{section.id}': unknown field '{name}'")
            if section.widths and line.startswith("|") and not line.startswith("|-"):
                cells = [c for c in line.strip("|").split("|")]
                if len(cells) != len(section.widths):
                    problems.append(f"section '{section.id}': table row has {len(cells)} cells "
                                    f"but widths lists {len(section.widths)}")
    if problems:
        raise TemplateError("Invalid template: " + "; ".join(problems))


def load_template(path: Path) -> DocumentTemplate:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateError(f"Cannot read template {path}: {exc}") from exc
    return parse_template(text)
