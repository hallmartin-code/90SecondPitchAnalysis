from __future__ import annotations

from pitch90.evidence import (
    apply_user_correction,
    build_facts,
    evaluate_formula,
    excerpt_found,
    unsupported_figures,
)
from pitch90.models import (
    NOT_PROVIDED,
    Basis,
    CitationCheck,
    Commitment,
    EvidenceStatus,
    ExtractedDeck,
    FactCategory,
    LLMFact,
    Origin,
    UnitContent,
)


def deck() -> ExtractedDeck:
    return ExtractedDeck(
        filename="d.pptx", source_type="pptx", unit_label="slide",
        units=[
            UnitContent(number=1, text="Acme Robotics\nwww.acme.example"),
            UnitContent(number=2, text="ARR $1.2M (June 2026)\n40 signed customers"),
            UnitContent(number=3, text="Current ARR: $1.5M", notes="Say ARR loudly"),
            UnitContent(number=4, text="500 hospitals x $20K = $10M SAM"),
        ],
    )


def fact(**kw) -> LLMFact:
    base = dict(key="arr", category=FactCategory.REVENUE, label="ARR", value="$1.2M", unit="USD",
                period="June 2026", basis=Basis.ACTUAL, commitment=Commitment.NOT_APPLICABLE,
                source_pages=[2], excerpt="ARR $1.2M (June 2026)", status=EvidenceStatus.STATED)
    base.update(kw)
    return LLMFact(**base)


def test_stated_fact_excerpt_verified():
    [f] = build_facts([fact()], deck())
    assert f.citation_check == CitationCheck.VERIFIED
    assert f.status == EvidenceStatus.STATED
    assert f.flags == []


def test_excerpt_not_on_cited_page_flagged():
    [f] = build_facts([fact(source_pages=[3])], deck())
    assert f.citation_check == CitationCheck.NOT_FOUND
    assert any("not on the cited" in x for x in f.flags)


def test_fabricated_excerpt_flagged():
    [f] = build_facts([fact(excerpt="ARR $9.9M", value="$9.9M")], deck())
    assert f.citation_check == CitationCheck.NOT_FOUND
    assert any("not found" in x for x in f.flags)


def test_nonexistent_page_citation_removed():
    [f] = build_facts([fact(source_pages=[2, 99])], deck())
    assert f.source_pages == [2]
    assert any("non-existent" in x for x in f.flags)


def test_missing_fact_normalised():
    [f] = build_facts([fact(key="runway", value="n/a", status=EvidenceStatus.MISSING,
                            source_pages=[2], excerpt="x")], deck())
    assert f.value == NOT_PROVIDED
    assert f.source_pages == [] and f.excerpt is None
    assert f.status == EvidenceStatus.MISSING


def test_conflicting_values_flagged_not_resolved():
    a = fact()
    b = fact(value="$1.5M", period="Current", source_pages=[3], excerpt="Current ARR: $1.5M")
    fa, fb = build_facts([a, b], deck())
    assert fa.status == fb.status == EvidenceStatus.CONFLICTING
    assert fa.value == "$1.2M" and fb.value == "$1.5M"  # neither chosen or overwritten
    assert any("F02" in x for x in fa.flags)


def test_same_value_different_format_not_conflicting():
    a = fact()
    b = fact(value="$1,200,000", source_pages=[2], excerpt="ARR $1.2M")
    fa, fb = build_facts([a, b], deck())
    assert fa.status == fb.status == EvidenceStatus.STATED


def test_different_periods_or_bases_not_conflicting():
    a = fact()
    b = fact(value="$5M", period="FY2028", basis=Basis.FORECAST, source_pages=[2], excerpt=None)
    c = fact(value="$0.8M", period="June 2025", source_pages=[2], excerpt=None)
    facts = build_facts([a, b, c], deck())
    assert all(f.status != EvidenceStatus.CONFLICTING for f in facts)


def test_calculated_fact_formula_checked():
    good = fact(key="sam", value="$10M", status=EvidenceStatus.CALCULATED,
                formula="500 * 20000 = 10000000", source_pages=[4], excerpt="500 hospitals x $20K")
    bad = fact(key="sam2", value="$12M", status=EvidenceStatus.CALCULATED,
               formula="500 * 20000", source_pages=[4], excerpt="500 hospitals x $20K")
    none = fact(key="sam3", value="$10M", status=EvidenceStatus.CALCULATED, formula=None,
                source_pages=[4], excerpt="500 hospitals")
    g, b, n = build_facts([good, bad, none], deck())
    assert g.flags == []
    assert any("does not match" in x for x in b.flags)
    assert any("no formula" in x for x in n.flags)


def test_evaluate_formula_is_safe():
    assert evaluate_formula("$1,200 x 12 = 14,400") == 14400
    assert evaluate_formula("(4000000 - 1500000)") == 2500000
    assert evaluate_formula("__import__('os').system('x')") is None
    assert evaluate_formula("2 ** 1000000") is None


def test_inferred_fact_flagged():
    [f] = build_facts([fact(status=EvidenceStatus.INFERRED, note="implied")], deck())
    assert any("Inferred" in x for x in f.flags)


def test_user_correction_has_no_deck_citation():
    [f] = build_facts([fact()], deck())
    corrected = apply_user_correction(f, "$1.3M", period="July 2026")
    assert corrected.origin == Origin.USER
    assert corrected.citation_check == CitationCheck.USER
    assert corrected.source_pages == [] and corrected.excerpt is None
    assert corrected.original_value == "$1.2M"
    assert corrected.value == "$1.3M" and corrected.period == "July 2026"
    assert any("User-provided" in x for x in corrected.flags)


def test_excerpt_matching_tolerates_formatting():
    assert excerpt_found("ARR  $1.2M (June 2026)", "arr $1.2m (june 2026)")
    assert excerpt_found("ARR $1.2M ... 40 signed", "ARR $1.2M (June 2026)\n40 signed customers")
    assert not excerpt_found("", "anything")


def test_unsupported_figures_detected():
    facts = build_facts([fact()], deck())
    text = "ARR reached $1.2M with 40 signed customers and a $250M market."
    assert unsupported_figures(text, deck(), facts) == ["$250M"]
