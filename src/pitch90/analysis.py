"""Turn a validated model response into a checked AnalysisResult."""

from __future__ import annotations

from pitch90.evidence import (
    build_facts,
    is_missing_value,
    mark_conflicts,
    merge_inconsistencies,
    normalize,
    unsupported_figures,
)
from pitch90.models import (
    NOT_PROVIDED,
    AnalysisResult,
    ExtractedDeck,
    ExtractionLimitation,
    LLMAnalysis,
    LLMOnePager,
    OnePagerSection,
)
from pitch90.scoring import pitch_timing, total_score

SECTION_FIELDS = [
    "positioning", "problem_why_now", "solution_benefit", "market_business_model",
    "traction_evidence", "differentiation", "fundraising_target", "terms",
    "use_of_funds", "milestones", "exit_strategy", "contact",
]


def _filter_pages(pages: list[int], valid: set[int]) -> tuple[list[int], list[int]]:
    keep = sorted({p for p in pages if p in valid})
    return keep, sorted(set(pages) - valid)


def _check_onepager(op: LLMOnePager, deck: ExtractedDeck, warnings: list[str]) -> LLMOnePager:
    op = op.model_copy(deep=True)
    valid = deck.unit_numbers
    label = deck.unit_label
    deck_text = "\n".join(u.all_text for u in deck.units)

    for name in SECTION_FIELDS:
        section: OnePagerSection = getattr(op, name)
        section.citations, bad = _filter_pages(section.citations, valid)
        if bad:
            warnings.append(f"One-pager '{name}': removed citations to non-existent {label}(s) {bad}.")
        if is_missing_value(section.text):
            section.text, section.citations = NOT_PROVIDED, []
        elif not section.citations and name in ("exit_strategy", "contact"):
            warnings.append(f"One-pager '{name}' had no deck citation and was set to '{NOT_PROVIDED}'.")
            section.text = NOT_PROVIDED
        elif not section.citations:
            warnings.append(f"One-pager '{name}' has no deck citation; verify before sharing.")

    for member in op.team:
        member.citations, _ = _filter_pages(member.citations, valid)
        if not member.citations:
            warnings.append(f"Team member '{member.name}' has no deck citation; verify before sharing.")

    if not is_missing_value(op.website):
        site = op.website.lower().removeprefix("https://").removeprefix("http://").rstrip("/")
        if normalize(site) not in normalize(deck_text):
            warnings.append(f"Website '{op.website}' was not found in the deck and was removed.")
            op.website = NOT_PROVIDED
    else:
        op.website = NOT_PROVIDED
    return op


def onepager_figure_warnings(op: LLMOnePager, deck: ExtractedDeck, result_facts,
                             user_texts: list[str] | None = None) -> list[str]:
    out = []
    for name in SECTION_FIELDS:
        text = getattr(op, name).text
        missing = unsupported_figures(text, deck, result_facts, user_texts)
        if missing:
            out.append(f"One-pager '{name}': figure(s) {', '.join(missing)} not found in the deck or facts.")
    for m in op.team:
        missing = unsupported_figures(m.qualifications, deck, result_facts, user_texts)
        if missing:
            out.append(f"Team '{m.name}': figure(s) {', '.join(missing)} not found in the deck.")
    return out


def finalize(
    llm: LLMAnalysis,
    deck: ExtractedDeck,
    *,
    mode: str,
    model: str | None,
    words_per_minute: int,
    images_sent: list[int],
) -> AnalysisResult:
    warnings: list[str] = []
    valid = deck.unit_numbers
    label = deck.unit_label

    facts = build_facts(llm.facts, deck)
    detected = mark_conflicts(facts, label)

    elements = [e.model_copy(deep=True) for e in llm.elements]
    for e in elements:
        e.source_pages, bad = _filter_pages(e.source_pages, valid)
        if bad:
            warnings.append(f"Removed citations to non-existent {label}(s) {bad} from '{e.element.value}'.")
    total, pct = total_score(elements)

    def clean_points(items):
        out = []
        for item in items:
            item = item.model_copy(deep=True)
            item.source_pages, _ = _filter_pages(item.source_pages, valid)
            out.append(item)
        return out

    pairs = clean_points(llm.obstacle_capability_pairs)[:3]
    strongest = clean_points(llm.strongest_points)
    if len(strongest) != 3 or len(llm.priority_fixes) != 3:
        warnings.append("The model did not return exactly three strongest points and three fixes.")

    for obs in llm.visual_observations:
        if obs.page not in images_sent:
            warnings.append(f"Visual observation for {label} {obs.page} discarded: no image of it was provided.")
    visual = [o for o in llm.visual_observations if o.page in images_sent]

    limitations = [l.model_copy(deep=True) for l in llm.extraction_limitations]
    covered = {p for l in limitations for p in l.pages}
    for w in deck.warnings:
        if w.kind == "extraction" and w.severity in ("warning", "error") and (not w.units or not set(w.units) <= covered):
            limitations.append(ExtractionLimitation(
                pages=w.units, limitation=w.message,
                effect_on_evaluation="Content on these units may be incomplete, so related "
                                     "scores and facts may understate or misread the deck.",
            ))
    not_sent = sorted(n for n in deck.images if n not in images_sent)
    unrendered = [u.number for u in deck.units if u.needs_visual and u.number not in deck.images]
    if mode == "demo" and deck.images:
        not_sent = sorted(deck.images)
    if not_sent or unrendered:
        limitations.append(ExtractionLimitation(
            pages=sorted(set(not_sent) | set(unrendered)),
            limitation="Image-based content on these units was not visually interpreted.",
            effect_on_evaluation="Charts, diagrams or image text here were assessed only from "
                                 "extracted/OCR text, which may miss values or context.",
        ))

    script_flags = unsupported_figures(llm.pitch_script, deck, facts)
    if script_flags:
        warnings.append(f"Pitch script figure(s) {', '.join(script_flags)} not found in the deck or facts.")
    timing = pitch_timing(llm.pitch_script, words_per_minute)
    if not timing.within_target_words:
        warnings.append(f"Pitch script is {timing.word_count} words (target 180-210).")

    onepager = _check_onepager(llm.onepager, deck, warnings)
    warnings += onepager_figure_warnings(onepager, deck, facts)

    for f in facts:
        if f.excerpt and f.citation_check and f.citation_check.value == "excerpt_not_found_on_cited_pages":
            in_images = any(n in images_sent for n in f.source_pages)
            if in_images:
                f.flags.append(f"Cited {label} was interpreted from its image; excerpt cannot be text-matched.")

    if mode == "demo":
        warnings.insert(0, "Demo mode: this analysis is pre-written synthetic output for the bundled sample deck, "
                           "processed through the same validation checks as a live analysis.")

    return AnalysisResult(
        mode=mode,  # type: ignore[arg-type]
        model=model,
        source_filename=deck.filename,
        source_sha256=deck.sha256,
        unit_label=label,
        company_name=llm.company_name,
        facts=facts,
        elements=elements,
        total_score=total,
        percentage=pct,
        obstacle_capability_pairs=pairs,
        strongest_points=strongest,
        priority_fixes=llm.priority_fixes,
        inconsistencies=merge_inconsistencies(llm.inconsistencies, detected),
        information_gaps=llm.information_gaps,
        extraction_limitations=limitations,
        extraction_warnings=deck.warnings,
        visual_observations=visual,
        pitch_script=llm.pitch_script,
        timing=timing,
        validation_warnings=list(dict.fromkeys(warnings)),
        onepager=onepager,
    )

