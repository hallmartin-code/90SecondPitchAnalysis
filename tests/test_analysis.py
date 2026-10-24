from __future__ import annotations

import pytest

from pitch90.analysis import finalize
from pitch90.demo import DemoUnavailable, demo_analysis
from pitch90.models import NOT_PROVIDED, EvidenceStatus, ExtractedDeck, UnitContent


def run(llm, deck, images=()):
    return finalize(llm, deck, mode="demo", model=None, words_per_minute=140, images_sent=list(images))


def test_demo_pipeline_end_to_end(sample_deck):
    result = run(demo_analysis(sample_deck), sample_deck)
    assert (result.total_score, result.percentage) == (17, 68.0)
    arr = [f for f in result.facts if f.key == "arr"]
    assert len(arr) == 2 and all(f.status == EvidenceStatus.CONFLICTING for f in arr)
    assert {f.value for f in arr} == {"$1.2M", "$1.4M"}
    assert result.timing.within_target_words
    assert result.onepager.website == "www.tidewell-grid.example"
    assert any(l.pages == [7] for l in result.extraction_limitations)
    # The embedded instruction on slide 12 is a security notice, not an extraction limitation.
    assert not any("instructions" in l.limitation for l in result.extraction_limitations)


def test_demo_refuses_other_decks():
    deck = ExtractedDeck(filename="x.pdf", source_type="pdf", unit_label="page",
                         units=[UnitContent(number=1, text="Other company")])
    with pytest.raises(DemoUnavailable):
        demo_analysis(deck)


def test_unsupported_onepager_claims_removed_or_flagged(sample_deck, demo_llm):
    llm = demo_llm.model_copy(deep=True)
    llm.onepager.website = "www.invented-site.example"
    llm.onepager.exit_strategy.citations = []
    llm.onepager.traction_evidence.text += " Revenue grew to $9.7M."
    llm.onepager.positioning.citations = [99]
    result = run(llm, sample_deck)
    assert result.onepager.website == NOT_PROVIDED
    assert result.onepager.exit_strategy.text == NOT_PROVIDED
    assert result.onepager.positioning.citations == []
    warnings = " ".join(result.validation_warnings)
    assert "$9.7M" in warnings and "non-existent" in warnings


def test_visual_observation_without_image_discarded(sample_deck, demo_llm):
    from pitch90.models import VisualObservation

    llm = demo_llm.model_copy(deep=True)
    llm.visual_observations = [VisualObservation(page=7, observation="bar chart shows decline"),
                               VisualObservation(page=3, observation="invented")]
    result = run(llm, sample_deck, images=[7])
    assert [v.page for v in result.visual_observations] == [7]


def test_salvage_notes_become_validation_warnings(sample_deck, demo_json):
    import json

    from pitch90.llm import parse_response

    demo_json["elements"] = demo_json["elements"][:4]
    llm = parse_response(json.dumps(demo_json))
    result = run(llm, sample_deck)
    assert result.total_score == 14  # evidence not assessed -> 0
    assert any("not assessed" in w for w in result.validation_warnings)
