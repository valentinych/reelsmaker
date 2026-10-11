"""Sequential text timing and auto slide duration."""

from __future__ import annotations

from reels.colors import (
    DEFAULT_BG_ALPHA,
    DEFAULT_BG_COLOR,
    DEFAULT_FONT_COLOR,
)
from reels.generator import TextBlock

TEXT_GAP_SEC = 0.2
SLIDE_END_PADDING_SEC = 0.5
MIN_SLIDE_DURATION_SEC = 2.0


def schedule_texts(texts: list[TextBlock]) -> list[TextBlock]:
    """Place texts one after another with a fixed gap between them."""
    if not texts:
        return []

    scheduled: list[TextBlock] = []
    offset = 0.0
    for i, block in enumerate(texts):
        if i > 0:
            offset += scheduled[i - 1].duration + TEXT_GAP_SEC
        scheduled.append(
            TextBlock(
                text=block.text,
                font_color=block.font_color,
                bg_color=block.bg_color,
                duration=block.duration,
                start_offset=offset,
                animation=block.animation,
                position=block.position,
            )
        )
    return scheduled


def compute_slide_duration(texts: list[TextBlock]) -> float:
    """Slide length = last text end + trailing padding on photo."""
    if not texts:
        return MIN_SLIDE_DURATION_SEC
    last = texts[-1]
    end = last.start_offset + last.duration + SLIDE_END_PADDING_SEC
    return max(MIN_SLIDE_DURATION_SEC, end)
