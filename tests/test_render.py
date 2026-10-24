from __future__ import annotations

import json
import re

import pymupdf
import pytest

from pitch90.analysis import finalize
from pitch90.demo import demo_analysis
from pitch90.models import AnalysisResult, LLMOnePager, OnePagerSection, TeamMember
from pitch90.render.onepager import FOOTER_TEXT, SECTIONS, check_fit, render_onepager, shorten_to_fit
from pitch90.render.report import export_json, render_report


def open_pdf(data: bytes) -> pymupdf.Document:
    return pymupdf.open(stream=data, filetype="pdf")


def words(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def assert_fully_rendered(pdf: bytes, op: LLMOnePager):
    """Exactly one page, embedded fonts, body >= 9 pt, and every section's text present."""
    doc = open_pdf(pdf)
    assert doc.page_count == 1
    page = doc[0]
    for font in page.get_fonts():
        assert font[1] == "ttf", f"font {font[3]} not embedded TrueType"
    page_text = words(page.get_text())
    assert FOOTER_TEXT in page_text
    for name in ("problem_why_now", "solution_benefit", "market_business_model",
                 "traction_evidence", "differentiation", "use_of_funds", "milestones"):
        text = getattr(op, name).text
        tail = " ".join(text.split()[-3:])
        head = " ".join(text.split()[:3])
        assert words(head) in page_text and words(tail) in page_text, f"{name} clipped"
    for span in (s for b in page.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]):
        if FOOTER_TEXT in span["text"] or "source deck" in span["text"]:
            continue
        assert span["size"] >= 8.99, f"text below 9 pt: {span['text']!r} at {span['size']}"
    # Nothing drawn outside the page margins.
    for b in page.get_text("dict")["blocks"]:
        x0, y0, x1, y1 = b["bbox"]
        assert x0 >= 30 and x1 <= page.rect.width - 30 and y0 >= 30 and y1 <= page.rect.height - 25


def test_demo_onepager_one_page(demo_llm):
    pdf, report = render_onepager(demo_llm.onepager, "S")
    assert report.fits and pdf
    assert_fully_rendered(pdf, demo_llm.onepager)


def test_onepager_excludes_scores_and_critique(sample_deck, demo_llm):
    result = finalize(demo_llm, sample_deck, mode="demo", model=None, words_per_minute=140, images_sent=[])
    pdf, _ = render_onepager(result.onepager, "S")
    text = open_pdf(pdf)[0].get_text().lower()
    for banned in ("/ 25", "score", "rubric", "improvement", "priority fix"):
        assert banned not in text


def test_missing_exit_and_contact_omitted(demo_llm):
    op = demo_llm.onepager.model_copy(deep=True)
    op.exit_strategy = OnePagerSection(text="Not provided", citations=[])
    op.contact = OnePagerSection(text="Not provided", citations=[])
    pdf, _ = render_onepager(op, "S")
    text = open_pdf(pdf)[0].get_text()
    assert "EXIT STRATEGY" not in text and "CONTACT" not in text


def long_onepager(demo_llm, sentences: int) -> LLMOnePager:
    op = demo_llm.onepager.model_copy(deep=True)
    op.company_name = ("The Extraordinarily Long-Named International Consolidated Predictive Grid "
                       "Reliability And Outage Prevention Technologies Holding Company Incorporated")
    op.website = "https://www.an-unusually-long-domain-name-for-testing-wrapping-behaviour.example/path"
    filler = ("Customers report measurable improvements in planning accuracy and crew utilisation "
              "across seasonal storm periods. ")
    for name in ("problem_why_now", "solution_benefit", "market_business_model", "differentiation",
                 "traction_evidence"):
        sec = getattr(op, name)
        sec.text = sec.text + " " + filler * sentences
    op.team = op.team + [TeamMember(name=f"Advisor {i}", role="Advisor",
                                    qualifications="Former utility executive with board experience",
                                    citations=[11]) for i in range(2)]
    return op


def test_long_name_and_content_fit_by_shrinking(demo_llm):
    op = long_onepager(demo_llm, 1)
    pdf, report = render_onepager(op, "S")
    assert report.fits, report.message
    assert report.body_size >= 9.0
    assert_fully_rendered(pdf, op)
    assert "Holding Company Incorporated" in words(open_pdf(pdf)[0].get_text())


def test_overflow_refused_with_specific_guidance(demo_llm):
    op = long_onepager(demo_llm, 8)
    pdf, report = render_onepager(op, "S")
    assert pdf is None and not report.fits
    assert report.overflow_points > 0
    assert report.suggestions and "Shorten" in report.message
    named = {s[0] for s in report.suggestions}
    assert named & {"problem_why_now", "solution_benefit", "market_business_model",
                    "differentiation", "traction_evidence"}


def test_auto_shorten_removes_whole_sentences_and_fits(demo_llm):
    op = long_onepager(demo_llm, 8)
    shorter, changes, report = shorten_to_fit(op, "S")
    assert report.fits and changes
    pdf, _ = render_onepager(shorter, "S")
    assert_fully_rendered(pdf, shorter)
    for name in ("problem_why_now", "solution_benefit"):
        assert getattr(shorter, name).text.rstrip().endswith(".")  # never cut mid-sentence


def test_unbroken_long_token_does_not_break_layout(demo_llm):
    op = demo_llm.onepager.model_copy(deep=True)
    op.contact = OnePagerSection(text="x" * 300 + "@example.com", citations=[1])
    pdf, report = render_onepager(op, "S")
    assert report.fits
    assert open_pdf(pdf).page_count == 1


def test_page_citation_prefix(demo_llm):
    pdf, _ = render_onepager(demo_llm.onepager, "p")
    text = open_pdf(pdf)[0].get_text()
    assert "[p 2, p 3]" in words(text)


def test_report_and_json(sample_deck, demo_llm):
    result = finalize(demo_llm, sample_deck, mode="demo", model=None, words_per_minute=140, images_sent=[])
    result.onepager_edits["traction_evidence"] = "user_edited"
    pdf = render_report(result)
    doc = open_pdf(pdf)
    assert doc.page_count >= 2
    text = " ".join(p.get_text() for p in doc)
    assert "17 / 25" in text and "Compiled on" in text and "TEN Capital Network" in text
    data = json.loads(export_json(result))
    assert data["onepager_edits"] == {"traction_evidence": "user_edited"}
    assert AnalysisResult.model_validate(data).total_score == 17
    assert "images" not in data


@pytest.mark.parametrize("key", [k for k, _ in SECTIONS if k not in ("team", "raise")])
def test_each_section_field_exists(key, demo_llm):
    assert hasattr(demo_llm.onepager, key)


def test_check_fit_reports_body_size(demo_llm):
    assert check_fit(demo_llm.onepager).body_size in (10.0, 9.5, 9.0)
