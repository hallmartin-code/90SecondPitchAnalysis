from __future__ import annotations

import pytest

from pitch90.models import ElementAssessment, NarrativeElement
from pitch90.scoring import ScoreError, pitch_timing, total_score, word_count


def elements(scores):
    return [ElementAssessment(element=e, score=s, rationale="r", source_pages=[], missing_or_weak=[],
                              improvement="i") for e, s in zip(NarrativeElement, scores)]


def test_total_and_percentage():
    assert total_score(elements([4, 3, 3, 4, 3])) == (17, 68.0)
    assert total_score(elements([5, 5, 5, 5, 5])) == (25, 100.0)
    assert total_score(elements([0, 0, 0, 0, 1])) == (1, 4.0)


@pytest.mark.parametrize("bad", [6, -1])
def test_out_of_range_score_rejected(bad):
    with pytest.raises(ScoreError):
        total_score(elements([bad, 3, 3, 3, 3]))


def test_missing_or_duplicate_elements_rejected():
    with pytest.raises(ScoreError, match="missing"):
        total_score(elements([3, 3, 3, 3]))
    dup = elements([3, 3, 3, 3, 3])
    dup[4] = dup[4].model_copy(update={"element": NarrativeElement.WHY_NOW})
    with pytest.raises(ScoreError, match="duplicated"):
        total_score(dup)


def test_pitch_duration_default_rate():
    script = " ".join(["word"] * 210)
    t = pitch_timing(script)
    assert t.word_count == 210 and t.words_per_minute == 140
    assert t.seconds == 90.0
    assert t.within_target_words


def test_pitch_duration_configurable_rate():
    t = pitch_timing(" ".join(["word"] * 180), words_per_minute=160)
    assert t.seconds == 67.5


def test_pitch_outside_target_flagged():
    assert not pitch_timing("too short").within_target_words
    assert not pitch_timing(" ".join(["w"] * 211)).within_target_words


def test_word_count_ignores_punctuation_tokens():
    assert word_count("We raised $4M — and grew 118% ; fast.") == 7


def test_invalid_rate():
    with pytest.raises(ValueError):
        pitch_timing("x", 0)
