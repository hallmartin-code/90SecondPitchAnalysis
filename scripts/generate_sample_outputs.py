"""Run the demo pipeline on the synthetic sample deck and write all outputs.

Usage:  python scripts/generate_sample_outputs.py
Writes to samples/output/: one-pager PDF + PNG preview, analysis report PDF, JSON,
and verifies programmatically that the one-pager is exactly one page.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pitch90.analysis import finalize  # noqa: E402
from pitch90.config import get_settings  # noqa: E402
from pitch90.demo import SAMPLE_DECK, demo_analysis  # noqa: E402
from pitch90.ingest import extract_deck  # noqa: E402
from pitch90.render.onepager import render_onepager  # noqa: E402
from pitch90.render.report import export_json, render_report  # noqa: E402


def main() -> None:
    settings = get_settings()
    out = ROOT / "samples" / "output"
    out.mkdir(parents=True, exist_ok=True)
    deck = extract_deck(SAMPLE_DECK.name, SAMPLE_DECK.read_bytes(), settings)
    result = finalize(demo_analysis(deck), deck, mode="demo", model=None,
                      words_per_minute=settings.words_per_minute, images_sent=[])

    pdf, fit = render_onepager(result.onepager, "S")
    if pdf is None:
        raise SystemExit(f"One-pager does not fit: {fit.message}")
    (out / "tidewell_onepager.pdf").write_bytes(pdf)
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    assert doc.page_count == 1, "one-pager must be exactly one page"
    doc[0].get_pixmap(dpi=120).save(out / "tidewell_onepager_preview.png")

    report = render_report(result)
    (out / "tidewell_analysis_report.pdf").write_bytes(report)
    (out / "tidewell_analysis.json").write_text(export_json(result), encoding="utf-8")

    print(f"Score {result.total_score}/25 ({result.percentage:.0f}%), pitch "
          f"{result.timing.word_count} words ~{result.timing.seconds:.0f}s")
    print(f"One-pager: 1 page at {fit.body_size:g} pt body; report: "
          f"{pymupdf.open(stream=report, filetype='pdf').page_count} pages")
    print(f"Outputs written to {out}")


if __name__ == "__main__":
    main()
