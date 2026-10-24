"""Deck ingestion entry point: validate, convert, extract and report warnings."""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
import time
from pathlib import Path

from pitch90.config import Settings
from pitch90.ingest.convert import ConversionFailed, ConversionUnavailable, convert, find_soffice
from pitch90.ingest.pdf import extract_pdf, render_pages
from pitch90.ingest.pptx import extract_pptx
from pitch90.ingest.validate import UploadError, detect_kind, safe_filename
from pitch90.models import ExtractedDeck, ExtractionWarning

__all__ = ["extract_deck", "UploadError", "ConversionUnavailable", "ConversionFailed"]

log = logging.getLogger(__name__)

_INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|prompts?)",
    r"disregard (all |the )?(previous|prior|above) ",
    r"\byou are (now )?(an? )?(ai|assistant|language model|chatgpt|claude)\b",
    r"\bsystem prompt\b",
    r"\b(score|rate|grade) (this|the) (deck|pitch|company) (as |at )?\d",
    r"\bgive (this|the) (deck|pitch|company) (a )?(perfect|maximum|full|top) (score|rating|marks)",
    r"\b(assistant|ai|model)\s*:\s*",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def scan_for_instructions(deck: ExtractedDeck) -> ExtractionWarning | None:
    hits = [u.number for u in deck.units if _INJECTION_RE.search(u.all_text)]
    if not hits:
        return None
    return ExtractionWarning(
        severity="warning",
        message="Text that looks like instructions to an AI system was found. It is treated as "
                "deck content only and will not be followed.",
        units=hits,
        kind="security",
    )


def _summarise(deck: ExtractedDeck) -> None:
    label = deck.unit_label
    for u in deck.units:
        for w in u.warnings:
            severity = "warning" if ("No readable" in w or "Little" in w or "could not" in w) else "info"
            deck.warnings.append(ExtractionWarning(severity=severity, message=w, units=[u.number]))
    visual = [u.number for u in deck.units if u.needs_visual and u.number in deck.images]
    if visual:
        deck.warnings.append(ExtractionWarning(
            severity="info",
            message=f"These {label}s appear to rely on images, charts or diagrams. Their rendered "
                    f"images will be sent for visual interpretation during API analysis "
                    f"(not in demo mode).",
            units=visual,
        ))
    if not any(u.all_text.strip() for u in deck.units):
        deck.warnings.append(ExtractionWarning(
            severity="warning",
            message="No readable text was extracted from any "
                    f"{label}. The analysis will still run, relying on the {label} images that were "
                    "captured, and will report what it could not read.",
        ))
    injection = scan_for_instructions(deck)
    if injection:
        deck.warnings.append(injection)


def _render_slides(pdf: bytes, deck: ExtractedDeck, needed: set[int]) -> dict[int, bytes]:
    """Render slides from a LibreOffice PDF export, mapping pages back to slide numbers.

    LibreOffice omits hidden slides from PDF exports, so page N is not always slide N.
    """
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pages = doc.page_count
    all_slides = [u.number for u in deck.units]
    shown = [u.number for u in deck.units if not u.hidden]
    if pages == len(all_slides):
        order = all_slides
    elif pages == len(shown):
        order = shown
    else:
        log.warning("Rendered page count does not match slide count; renders discarded")
        return {}
    page_for = {slide: i + 1 for i, slide in enumerate(order)}
    rendered = render_pages(pdf, {page_for[n] for n in needed if n in page_for})
    return {slide: rendered[page] for slide, page in page_for.items() if page in rendered}


def extract_deck(filename: str, data: bytes, settings: Settings) -> ExtractedDeck:
    """Validate and extract an uploaded deck. Raises UploadError/Conversion* with clear messages."""
    name = safe_filename(filename)
    kind = detect_kind(name, data, settings.max_upload_bytes)
    soffice = find_soffice(settings.soffice_path)
    sha = hashlib.sha256(data).hexdigest()
    log.info("Extracting %s file (%d bytes)", kind, len(data))

    with tempfile.TemporaryDirectory(prefix="pitch90_") as tmp:
        work = Path(tmp)
        converted = False
        if kind == "ppt":
            src = work / name
            src.write_bytes(data)
            pptx_path = convert(src, "pptx", soffice)  # raises ConversionUnavailable
            data = pptx_path.read_bytes()
            converted = True

        if kind == "pdf":
            deck = extract_pdf(data, name, settings.max_pages,
                               budget_seconds=settings.extraction_budget_seconds)
            unrendered = [u.number for u in deck.units if u.needs_visual and u.number not in deck.images]
            if unrendered:
                deck.warnings.append(ExtractionWarning(
                    severity="warning",
                    message="These pages could not be rendered for visual interpretation.",
                    units=unrendered,
                ))
        else:
            started = time.monotonic()
            deck, pictures = extract_pptx(data, name, settings.max_pages,
                                          budget_seconds=settings.extraction_budget_seconds,
                                          source_type="ppt" if converted else "pptx")
            deck.converted_from_ppt = converted
            needed = {u.number for u in deck.units if u.needs_visual}
            within_budget = time.monotonic() - started < settings.extraction_budget_seconds
            if needed and soffice and within_budget:
                try:
                    pptx_file = work / "render.pptx"
                    pptx_file.write_bytes(data)
                    pdf = convert(pptx_file, "pdf", soffice)
                    deck.images = _render_slides(pdf.read_bytes(), deck, needed)
                except (ConversionFailed, ConversionUnavailable, UploadError):
                    log.warning("Slide rendering via LibreOffice failed")
            missing = needed - set(deck.images)
            if missing:
                fallback = {n: pictures[n] for n in missing if n in pictures}
                deck.images.update(fallback)
                if not soffice:
                    note = (
                        "LibreOffice is not installed, so full slide layouts cannot be rendered. "
                        "Only the largest embedded picture is available for these slides; charts "
                        "drawn as shapes or diagrams may be missed. Install LibreOffice or upload a "
                        "PDF export for complete visual interpretation."
                    )
                else:
                    note = "Some slides could not be rendered; embedded pictures were used where available."
                deck.warnings.append(ExtractionWarning(severity="warning", message=note, units=sorted(missing)))
                if missing - set(fallback):
                    deck.warnings.append(ExtractionWarning(
                        severity="warning",
                        message="No image is available for visual interpretation of these slides; "
                                "content conveyed only visually will not be evaluated.",
                        units=sorted(missing - set(fallback)),
                    ))
            if converted:
                deck.warnings.append(ExtractionWarning(
                    severity="info",
                    message="Converted from legacy .ppt with LibreOffice. Check that slide text "
                            "and notes survived conversion.",
                ))

    deck.sha256 = sha
    _summarise(deck)
    return deck
