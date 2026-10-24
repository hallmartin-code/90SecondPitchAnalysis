"""Synthetic demonstration mode: works without API credentials.

Demo mode analyses only the bundled fictional sample deck. Its pre-written response
goes through the same schema validation and evidence checks as a live response.
"""

from __future__ import annotations

from pathlib import Path

from pitch90.config import SAMPLES_DIR
from pitch90.llm import parse_response
from pitch90.models import ExtractedDeck, LLMAnalysis

SAMPLE_DECK = SAMPLES_DIR / "tidewell_sample_deck.pptx"
SAMPLE_PDF = SAMPLES_DIR / "tidewell_sample_deck.pdf"
DEMO_RESPONSE = SAMPLES_DIR / "demo_analysis.json"
SAMPLE_MARKER = "SYNTHETIC SAMPLE DECK"


class DemoUnavailable(Exception):
    pass


def is_sample_deck(deck: ExtractedDeck) -> bool:
    first = deck.units[0].all_text if deck.units else ""
    return SAMPLE_MARKER in first and "Tidewell" in first


def demo_analysis(deck: ExtractedDeck) -> LLMAnalysis:
    if not is_sample_deck(deck):
        raise DemoUnavailable(
            "Demo mode only analyses the bundled synthetic sample deck. Load the sample, "
            "or configure ANTHROPIC_API_KEY to analyse your own deck."
        )
    return parse_response(Path(DEMO_RESPONSE).read_text(encoding="utf-8"))
