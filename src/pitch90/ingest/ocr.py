"""Optional local OCR using RapidOCR (ONNX runtime, no system install needed)."""

from __future__ import annotations

import logging
from functools import lru_cache

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:  # pragma: no cover - depends on environment
        return None
    try:
        return RapidOCR()
    except Exception:  # pragma: no cover
        log.warning("RapidOCR failed to initialise")
        return None


def ocr_available() -> bool:
    return _engine() is not None


def ocr_image(image_bytes: bytes, min_confidence: float = 0.5) -> str | None:
    """Return recognised text (top-to-bottom), or None when OCR is unavailable."""
    engine = _engine()
    if engine is None:
        return None
    try:
        result, _ = engine(image_bytes)
    except Exception:
        log.warning("OCR failed on one image")
        return ""
    if not result:
        return ""
    lines = []
    for box, text, score in sorted(result, key=lambda r: (r[0][0][1], r[0][0][0])):
        if float(score) >= min_confidence and text.strip():
            lines.append(text.strip())
    return "\n".join(lines)
