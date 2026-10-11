"""Bundled typefaces for Reels captions."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONTS_DIR = Path(__file__).resolve().parent / "fonts"
JOST_VARIABLE = FONTS_DIR / "Jost-Variable.ttf"
JOST_WEIGHT = "Bold"

_FALLBACKS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
)


def auto_font_size(frame_or_block_w: int, *, mode: str = "frame") -> int:
    """Default size from available width. mode: frame | block."""
    w = max(1, int(frame_or_block_w))
    if mode == "block":
        return max(26, w // 18)
    return max(28, w // 22)


@lru_cache(maxsize=64)
def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(8, int(size))
    if JOST_VARIABLE.exists():
        try:
            font = ImageFont.truetype(str(JOST_VARIABLE), size)
            try:
                font.set_variation_by_name(JOST_WEIGHT)
            except (AttributeError, OSError, ValueError, TypeError):
                pass
            return font
        except OSError:
            pass
    for path in _FALLBACKS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()
