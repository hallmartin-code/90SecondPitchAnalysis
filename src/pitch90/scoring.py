"""Narrative score totals and spoken-pitch duration estimates."""

from __future__ import annotations

import re

from pitch90.models import ElementAssessment, NarrativeElement, PitchTiming

MAX_ELEMENT_SCORE = 5
PITCH_MIN_WORDS = 180
PITCH_MAX_WORDS = 210


class ScoreError(ValueError):
    pass


def validate_elements(elements: list[ElementAssessment]) -> None:
    seen = [e.element for e in elements]
    missing = set(NarrativeElement) - set(seen)
    duplicates = {e for e in seen if seen.count(e) > 1}
    if missing or duplicates:
        raise ScoreError(
            f"Expected one assessment per element; missing={sorted(m.value for m in missing)}, "
            f"duplicated={sorted(d.value for d in duplicates)}"
        )
    for e in elements:
        if not isinstance(e.score, int) or not 0 <= e.score <= MAX_ELEMENT_SCORE:
            raise ScoreError(f"Score for {e.element.value} must be an integer 0-5, got {e.score!r}")


def total_score(elements: list[ElementAssessment]) -> tuple[int, float]:
    """Return (total out of 25, percentage rounded to one decimal)."""
    validate_elements(elements)
    total = sum(e.score for e in elements)
    return total, round(total / (MAX_ELEMENT_SCORE * len(NarrativeElement)) * 100, 1)


def word_count(text: str) -> int:
    return sum(1 for token in text.split() if re.search(r"[A-Za-z0-9]", token))


def pitch_timing(script: str, words_per_minute: int = 140) -> PitchTiming:
    if words_per_minute <= 0:
        raise ValueError("words_per_minute must be positive")
    words = word_count(script)
    return PitchTiming(
        word_count=words,
        words_per_minute=words_per_minute,
        seconds=round(words / words_per_minute * 60, 1),
        within_target_words=PITCH_MIN_WORDS <= words <= PITCH_MAX_WORDS,
    )
