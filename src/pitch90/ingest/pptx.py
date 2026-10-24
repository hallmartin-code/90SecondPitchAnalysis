"""PPTX extraction with python-pptx: text, tables, chart data, pictures and notes."""

from __future__ import annotations

import io
import logging
import re

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Emu

from pitch90.ingest.ocr import ocr_image
from pitch90.ingest.validate import UploadError
from pitch90.models import ExtractedDeck, ExtractionWarning, UnitContent

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 40
IMAGE_COVERAGE_VISUAL = 0.30


def _alnum(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]", text))


def _iter_shapes(shapes):
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_shapes(shape.shapes)
        else:
            yield shape


def _chart_summary(chart) -> str:
    parts = []
    try:
        if chart.has_title and chart.chart_title.has_text_frame:
            parts.append(f"Chart: {chart.chart_title.text_frame.text.strip()}")
        else:
            parts.append("Chart")
        plot = chart.plots[0]
        categories = [str(c) for c in plot.categories]
        for series in plot.series:
            values = list(series.values)
            pairs = ", ".join(
                f"{cat}={val:g}" if isinstance(val, (int, float)) else f"{cat}={val}"
                for cat, val in zip(categories, values)
            )
            parts.append(f"{series.name}: {pairs}")
    except Exception:
        parts.append("(chart data could not be read)")
    return "; ".join(parts)


def _to_jpeg(blob: bytes, max_px: int = 1400) -> bytes | None:
    try:
        img = Image.open(io.BytesIO(blob))
        img.thumbnail((max_px, max_px))
        out = io.BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=80)
        return out.getvalue()
    except Exception:
        return None


def extract_pptx(
    data: bytes, filename: str, max_pages: int, source_type: str = "pptx"
) -> tuple[ExtractedDeck, dict[int, bytes]]:
    """Return the extracted deck and, per slide, its largest embedded picture."""
    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as exc:
        raise UploadError("The presentation is corrupt or unreadable and could not be opened.") from exc
    slides = list(prs.slides)
    if not slides:
        raise UploadError("The presentation contains no slides.")
    if len(slides) > max_pages:
        raise UploadError(f"The presentation has {len(slides)} slides; the limit is {max_pages}.")

    slide_area = max(int(prs.slide_width or Emu(9144000)) * int(prs.slide_height or Emu(5143500)), 1)
    units: list[UnitContent] = []
    pictures: dict[int, bytes] = {}
    warnings: list[ExtractionWarning] = []
    ocr_missing: list[int] = []

    for number, slide in enumerate(slides, start=1):
        unit = UnitContent(number=number, hidden=slide._element.get("show") == "0")
        if unit.hidden:
            unit.warnings.append("Hidden slide (included in extraction).")
        texts: list[tuple[int, int, str]] = []
        picture_blobs: list[tuple[int, bytes]] = []
        picture_area = 0
        unreadable_graphics = 0

        for shape in _iter_shapes(slide.shapes):
            top, left = int(shape.top or 0), int(shape.left or 0)
            area = int(shape.width or 0) * int(shape.height or 0)
            if shape.has_text_frame:
                text = "\n".join(p.text for p in shape.text_frame.paragraphs).strip()
                if text:
                    texts.append((top, left, text))
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [[cell.text.strip() for cell in row.cells] for row in shape.table.rows]
                unit.tables.append(rows)
            elif getattr(shape, "has_chart", False) and shape.has_chart:
                unit.chart_data.append(_chart_summary(shape.chart))
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE or hasattr(shape, "image"):
                try:
                    picture_blobs.append((area, shape.image.blob))
                    picture_area += area
                except Exception:
                    pass
            elif type(shape).__name__ == "GraphicFrame" or shape.shape_type in (
                MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT, MSO_SHAPE_TYPE.LINKED_OLE_OBJECT,
            ):
                # SmartArt diagrams and OLE objects: python-pptx cannot read their text.
                unreadable_graphics += 1

        texts.sort(key=lambda t: (t[0], t[1]))
        unit.text = "\n".join(t[2] for t in texts)
        unit.image_count = len(picture_blobs)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            unit.notes = slide.notes_slide.notes_text_frame.text.strip()
        if unreadable_graphics:
            unit.warnings.append(
                f"{unreadable_graphics} diagram/SmartArt/embedded object(s) whose text could not be extracted."
            )

        picture_blobs.sort(key=lambda p: p[0], reverse=True)
        if picture_blobs:
            jpeg = _to_jpeg(picture_blobs[0][1])
            if jpeg:
                pictures[number] = jpeg

        visible_chars = _alnum(unit.text) + sum(_alnum(" ".join(r)) for t in unit.tables for r in t)
        low_text = visible_chars < MIN_TEXT_CHARS and not unit.chart_data
        if low_text and picture_blobs:
            ocr_parts = []
            for _, blob in picture_blobs[:3]:
                result = ocr_image(blob)
                if result is None:
                    ocr_missing.append(number)
                    break
                if result:
                    ocr_parts.append(result)
            unit.ocr_text = "\n".join(ocr_parts)
            if unit.ocr_text:
                unit.warnings.append("Text recovered from slide images by OCR; check for recognition errors.")
        if low_text and not unit.ocr_text:
            unit.warnings.append("Little or no readable text on this slide.")

        reasons = []
        if low_text:
            reasons.append("little extractable text")
        if picture_area / slide_area >= IMAGE_COVERAGE_VISUAL:
            reasons.append(f"images cover {picture_area / slide_area:.0%} of the slide")
        if unreadable_graphics:
            reasons.append("diagram or embedded object")
        if reasons:
            unit.needs_visual = True
            unit.visual_reason = "; ".join(reasons)
        units.append(unit)

    if ocr_missing:
        warnings.append(ExtractionWarning(
            severity="error",
            message="OCR is unavailable (install rapidocr-onnxruntime); image-based text on these "
                    "slides was not read.",
            units=sorted(set(ocr_missing)),
        ))
    deck = ExtractedDeck(
        filename=filename, source_type=source_type, unit_label="slide",  # type: ignore[arg-type]
        units=units, warnings=warnings,
    )
    return deck, pictures
