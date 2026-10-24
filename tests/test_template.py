from __future__ import annotations

import re

import pymupdf
import pytest

from pitch90.analysis import finalize
from pitch90.render.report import (
    DEFAULT_TEMPLATE,
    DOC_FIELDS,
    FOOTER_FIELDS,
    ITEM_FIELDS,
    get_report_template,
    render_report,
)
from pitch90.render.template import TemplateError, parse_template, validate_template


@pytest.fixture
def result(sample_deck, demo_llm):
    return finalize(demo_llm, sample_deck, mode="demo", model=None, words_per_minute=140, images_sent=[])


def pdf_text(pdf: bytes) -> str:
    return re.sub(r"\s+", " ", " ".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf")))


def check(text: str) -> None:
    validate_template(parse_template(text), DOC_FIELDS, ITEM_FIELDS, FOOTER_FIELDS)


# --------------------------------------------------------------------------- default template


def test_default_template_is_valid_and_covers_every_section():
    template = get_report_template()
    assert {s.id for s in template.sections} == set(ITEM_FIELDS)
    assert template.meta["footer"].startswith("{{title}}")


def test_default_template_contains_no_company_data(demo_json):
    text = DEFAULT_TEMPLATE.read_text(encoding="utf-8").lower()
    specifics = {demo_json["company_name"], demo_json["onepager"]["website"], "tidewell", "co-op"}
    specifics |= {m["name"] for m in demo_json["onepager"]["team"]}
    specifics |= {f["value"] for f in demo_json["facts"] if f["value"] != "Not provided" and len(f["value"]) > 3}
    for value in specifics:
        assert value.lower() not in text, f"template contains deck-specific text: {value!r}"
    assert "$" not in text


def test_default_report_renders_all_sections(result):
    text = pdf_text(render_report(result))
    for heading in ("Narrative score", "Element assessments", "Three strongest narrative points",
                    "Evidence register", "Proposed 90-second pitch", "Information gaps"):
        assert heading in text
    assert f"{result.total_score} / 25" in text
    assert text.count("Missing/weak:") == sum(len(e.missing_or_weak) for e in result.elements)


# --------------------------------------------------------------------------- template control


CUSTOM = """---
title: "Custom {{company_name}}"
footer: "{{title}} p{{page}}"
---
# Review of {{company_name}}
## Fixes first
<!-- section: priority_fixes -->
{{item.n}}. {{item.text}}
## Score
<!-- section: score_summary -->
| Element | Score |
|---|---|
| {{item.element_title}} | {{item.score}} |
## Contradictions
<!-- section: inconsistencies -->
<!-- if-empty: Nothing contradictory. -->
- {{item.description}}
## Pairs
<!-- section: obstacle_capability_pairs optional -->
- {{item.obstacle}}
"""


def test_custom_template_controls_order_headings_and_content(result):
    text = pdf_text(render_report(result, parse_template(CUSTOM)))
    assert text.index("Fixes first") < text.index("Score") < text.index("Contradictions")
    assert "Review of " + result.company_name in text
    assert "Evidence register" not in text and "Element assessments" not in text


def test_empty_and_optional_sections(result):
    empty = result.model_copy(update={"inconsistencies": [], "obstacle_capability_pairs": []})
    text = pdf_text(render_report(empty, parse_template(CUSTOM)))
    assert "Nothing contradictory." in text
    assert "Pairs" not in text


def test_values_are_escaped_not_interpreted(result):
    odd = result.model_copy(update={"company_name": "A&B <Labs> **bold**"})
    text = pdf_text(render_report(odd, parse_template(CUSTOM)))
    assert "A&B <Labs> **bold**" in text


def test_template_path_override(tmp_path, result):
    path = tmp_path / "t.md"
    path.write_text(CUSTOM, encoding="utf-8")
    assert "Fixes first" in pdf_text(render_report(result, path))


# --------------------------------------------------------------------------- validation


@pytest.mark.parametrize("bad,match", [
    ("## X\n<!-- section: nonsense -->\nhi", "unknown section"),
    ("## X\n<!-- section: priority_fixes -->\n{{item.colour}}", "unknown item field"),
    ("## X\n<!-- section: priority_fixes -->\n{{companyname}}", "unknown field"),
    ("## X\n<!-- section: facts -->\n<!-- widths: 1,2 -->\n| a | b | c |", "widths"),
    ("---\ntitle: \"{{nope}}\"\n---\n# T", "front matter"),
])
def test_invalid_templates_rejected(bad, match):
    with pytest.raises(TemplateError, match=match):
        check(bad)


@pytest.mark.parametrize("bad,match", [
    ("## X\n<!-- section: facts -->\n## Y\n<!-- section: facts -->", "Duplicate"),
    ("stray text", "outside a section"),
    ("<!-- never closed\n# T", "Unclosed"),
])
def test_malformed_templates_rejected(bad, match):
    with pytest.raises(TemplateError, match=match):
        parse_template(bad)
