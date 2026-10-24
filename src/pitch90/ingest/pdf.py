"""PDF extraction with PyMuPDF, OCR fallback and page renders for visual review."""

from __future__ import annotations

import logging
import re

import pymupdf

from pitch90.ingest.ocr import ocr_image
from pitch90.ingest.validate import UploadError
from pitch90.models import ExtractedDeck, ExtractionWarning, UnitContent

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 40  # alphanumeric characters below which a page counts as image-based
IMAGE_COVERAGE_VISUAL = 0.30
DRAWINGS_VISUAL = 25  # many vector paths usually means a chart or diagram
DRAWINGS_VISUAL_NO_TABLE = 12  # fewer paths suffice when they are not table borders
_JUNK = re.compile("[\ufffd\ue000-\uf8ff\u2022\u25aa\u25cf]")


def clean_text(text: str) -> str:
    """Drop bullet glyphs and replacement characters left by symbol fonts."""
    lines = [_JUNK.sub("", line).rstrip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line.strip())


def _alnum(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]", text))


def render_page(page: pymupdf.Page, max_px: int = 1400) -> bytes:
    zoom = max_px / max(page.rect.width, page.rect.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("jpeg", jpg_quality=80)


def open_pdf(data: bytes) -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise UploadError("The PDF is corrupt or unreadable and could not be opened.") from exc
    if doc.needs_pass:
        doc.close()
        raise UploadError(
            "This PDF is password-protected. Remove the password (or export an unprotected "
            "copy) and upload it again."
        )
    if doc.page_count == 0:
        doc.close()
        raise UploadError("The PDF contains no pages.")
    return doc


def _tables(page: pymupdf.Page) -> list[list[list[str]]]:
    try:
        found = page.find_tables()
    except Exception:
        return []
    tables = []
    for table in found.tables:
        rows = [[(c or "").strip() for c in row] for row in table.extract()]
        rows = [r for r in rows if any(r)]
        if len(rows) >= 2:
            tables.append(rows)
    return tables


def extract_pdf(
    data: bytes,
    filename: str,
    max_pages: int,
    unit_label: str = "page",
    source_type: str = "pdf",
) -> ExtractedDeck:
    doc = open_pdf(data)
    try:
        if doc.page_count > max_pages:
            raise UploadError(
                f"The document has {doc.page_count} pages; the limit is {max_pages}."
            )
        units: list[UnitContent] = []
        images: dict[int, bytes] = {}
        warnings: list[ExtractionWarning] = []
        ocr_missing: list[int] = []

        for index, page in enumerate(doc):
            number = index + 1
            unit = UnitContent(number=number)
            try:
                unit.text = clean_text(page.get_text("text"))
            except Exception:
                unit.warnings.append("Text layer could not be read.")
            unit.tables = _tables(page)
            try:
                info = page.get_image_info()
            except Exception:
                info = []
            unit.image_count = len(info)
            page_area = max(page.rect.width * page.rect.height, 1)
            coverage = sum(
                pymupdf.Rect(i["bbox"]).intersect(page.rect).get_area() for i in info
            ) / page_area
            try:
                drawings = len(page.get_drawings())
            except Exception:
                drawings = 0

            low_text = _alnum(unit.text) < MIN_TEXT_CHARS
            if low_text:
                ocr = ocr_image(page.get_pixmap(dpi=200, alpha=False).tobytes("png"))
                if ocr is None:
                    ocr_missing.append(number)
                    unit.warnings.append("Little extractable text and OCR is unavailable.")
                else:
                    unit.ocr_text = ocr
                    if ocr:
                        unit.warnings.append("Text recovered by OCR; check for recognition errors.")
                    else:
                        unit.warnings.append("No readable text found, even with OCR.")

            reasons = []
            if low_text:
                reasons.append("little extractable text")
            if coverage >= IMAGE_COVERAGE_VISUAL:
                reasons.append(f"images cover {coverage:.0%} of the page")
            if drawings >= DRAWINGS_VISUAL or (drawings >= DRAWINGS_VISUAL_NO_TABLE and not unit.tables):
                reasons.append("likely chart or diagram")
            if reasons:
                unit.needs_visual = True
                unit.visual_reason = "; ".join(reasons)
                try:
                    images[number] = render_page(page)
                except Exception:
                    unit.warnings.append("Page could not be rendered for visual review.")
            units.append(unit)

        if ocr_missing:
            warnings.append(ExtractionWarning(
                severity="error",
                message="OCR is unavailable (install rapidocr-onnxruntime); these pages have "
                        "little or no extractable text and were not read.",
                units=ocr_missing,
            ))
        try:
            labels = [p.get_label() for p in doc]
            if any(lbl and lbl != str(i + 1) for i, lbl in enumerate(labels)):
                warnings.append(ExtractionWarning(
                    severity="info",
                    message="The PDF defines custom page labels; citations use physical page "
                            "numbers (1 = first page of the file).",
                ))
        except Exception:
            pass
        return ExtractedDeck(
            filename=filename,
            source_type=source_type,  # type: ignore[arg-type]
            unit_label=unit_label,  # type: ignore[arg-type]
            units=units,
            warnings=warnings,
            images=images,
        )
    finally:
        doc.close()


def render_pages(data: bytes, numbers: set[int], max_px: int = 1400) -> dict[int, bytes]:
    """Render selected 1-based pages of a PDF (used for PPTX converted to PDF)."""
    doc = open_pdf(data)
    try:
        return {n: render_page(doc[n - 1], max_px) for n in sorted(numbers) if 1 <= n <= doc.page_count}
    finally:
        doc.close()
