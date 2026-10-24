"""Register embedded TrueType fonts (Carlito, SIL Open Font License 1.1)."""

from __future__ import annotations

from functools import lru_cache

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from pitch90.config import ASSETS_DIR

FONT_DIR = ASSETS_DIR / "fonts"
REGULAR, BOLD, ITALIC = "Carlito", "Carlito-Bold", "Carlito-Italic"


@lru_cache(maxsize=1)
def register_fonts() -> None:
    for name, file in ((REGULAR, "Carlito-Regular.ttf"), (BOLD, "Carlito-Bold.ttf"),
                       (ITALIC, "Carlito-Italic.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
    addMapping(REGULAR, 0, 0, REGULAR)
    addMapping(REGULAR, 1, 0, BOLD)
    addMapping(REGULAR, 0, 1, ITALIC)
    addMapping(REGULAR, 1, 1, BOLD)
