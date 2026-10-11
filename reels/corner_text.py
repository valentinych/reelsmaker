"""Corner text blocks with edge-to-center expand/collapse animation."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from reels.animations import _hex_to_rgba, _wrap_text, ease_out_cubic
from reels.colors import DEFAULT_BG_COLOR, DEFAULT_FONT_COLOR
from reels.fonts import auto_font_size, load_font
from reels.watermark import WatermarkLayout

CORNER_POSITIONS = {
    "top_left": "Верх-лево",
    "top_right": "Верх-право",
    "bottom_left": "Низ-лево",
    "bottom_right": "Низ-право",
}

MAX_BLOCK_WIDTH_RATIO = 0.70
CORNER_MARGIN = 32
TEXT_WM_GAP = 20

BOTTOM_WM_POSITIONS = {"bottom_right", "bottom_left", "bottom_center"}
TOP_WM_POSITIONS = {"top_center"}


@dataclass
class CornerTextBlock:
    text: str
    start_time: float
    duration: float
    position: str = "bottom_right"
    font_color: str = DEFAULT_FONT_COLOR
    bg_color: str = DEFAULT_BG_COLOR
    font_size: int | None = None  # None / 0 = auto


def ease_in_cubic(t: float) -> float:
    return t**3


def corner_block_width_factor(
    local_t: float,
    duration: float,
    max_ratio: float = MAX_BLOCK_WIDTH_RATIO,
) -> float:
    """Width as fraction of frame width. Expand ease-out, collapse ease-in."""
    if local_t < 0 or local_t >= duration or duration <= 0:
        return 0.0

    enter = min(0.35 * duration, 0.65)
    exit_d = min(0.35 * duration, 0.65)
    hold_end = max(enter, duration - exit_d)

    if local_t < enter:
        p = local_t / enter if enter > 0 else 1.0
        return ease_out_cubic(p) * max_ratio

    if local_t >= hold_end:
        p = (local_t - hold_end) / exit_d if exit_d > 0 else 1.0
        return (1.0 - ease_in_cubic(min(1.0, p))) * max_ratio

    return max_ratio


def _render_block_image(
    text: str,
    max_block_w: int,
    font_color: str,
    bg_color: str,
    font_size: int | None = None,
) -> Image.Image:
    padding_x, padding_y = 28, 20
    resolved = int(font_size) if font_size and font_size > 0 else auto_font_size(max_block_w, mode="block")
    font = load_font(resolved)

    probe = Image.new("RGBA", (max_block_w, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    max_text_w = max_block_w - padding_x * 2
    lines = _wrap_text(text, font, max_text_w, draw)

    line_heights: list[int] = []
    line_widths: list[int] = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    block_w = min(max_block_w, max(line_widths) + padding_x * 2)
    block_h = sum(line_heights) + padding_y * 2 + max(0, len(lines) - 1) * 10

    block = Image.new("RGBA", (block_w, block_h), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(block)
    bdraw.rounded_rectangle(
        [0, 0, block_w - 1, block_h - 1],
        radius=14,
        fill=_hex_to_rgba(bg_color),
    )

    fg = _hex_to_rgba(font_color)
    y = padding_y
    for i, line in enumerate(lines):
        tw = line_widths[i]
        tx = (block_w - tw) // 2
        bdraw.text((tx, y), line, font=font, fill=fg)
        y += line_heights[i] + 10

    return block


def _horizontal_overlap(ax: int, aw: int, bx: int, bw: int, pad: int = 0) -> bool:
    return not (ax + aw + pad <= bx or bx + bw + pad <= ax)


def _adjust_y_for_watermark(
    x: int,
    y: int,
    block_w: int,
    block_h: int,
    position: str,
    frame_h: int,
    wm: WatermarkLayout | None,
) -> int:
    if wm is None:
        return y

    if wm.position == "center":
        return y

    is_bottom_text = position in ("bottom_left", "bottom_right")
    is_top_text = position in ("top_left", "top_right")
    if not is_bottom_text and not is_top_text:
        return y

    overlaps = _horizontal_overlap(x, block_w, wm.x, wm.width, TEXT_WM_GAP)
    if not overlaps:
        return y

    wm_bottom = wm.position in BOTTOM_WM_POSITIONS
    wm_top = wm.position in TOP_WM_POSITIONS

    if is_bottom_text and wm_bottom:
        y = wm.y - block_h - TEXT_WM_GAP
    elif is_top_text and wm_top:
        y = wm.y + wm.height + TEXT_WM_GAP

    return max(CORNER_MARGIN, min(y, frame_h - CORNER_MARGIN - block_h))


def render_corner_text_overlay(
    text: str,
    frame_w: int,
    frame_h: int,
    position: str,
    width_factor: float,
    font_color: str = DEFAULT_FONT_COLOR,
    bg_color: str = DEFAULT_BG_COLOR,
    watermark_layout: WatermarkLayout | None = None,
    font_size: int | None = None,
) -> Image.Image:
    overlay = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    if not text.strip() or width_factor <= 0.001:
        return overlay

    max_block_w = int(frame_w * MAX_BLOCK_WIDTH_RATIO)
    block = _render_block_image(text, max_block_w, font_color, bg_color, font_size=font_size)
    bw, bh = block.size

    visible_w = min(bw, int(frame_w * width_factor))
    if visible_w <= 0:
        return overlay

    if position in ("top_left", "bottom_left"):
        cropped = block.crop((0, 0, visible_w, bh))
        x = CORNER_MARGIN
    else:
        crop_left = max(0, bw - visible_w)
        cropped = block.crop((crop_left, 0, bw, bh))
        x = frame_w - CORNER_MARGIN - cropped.width

    if position in ("top_left", "top_right"):
        y = CORNER_MARGIN
    else:
        y = frame_h - CORNER_MARGIN - bh

    y = _adjust_y_for_watermark(x, y, cropped.width, bh, position, frame_h, watermark_layout)

    overlay.paste(cropped, (x, y), cropped)
    return overlay


def overlays_at_time(
    blocks: list[CornerTextBlock],
    t: float,
    frame_w: int,
    frame_h: int,
    watermark_layout: WatermarkLayout | None = None,
) -> list[Image.Image]:
    result: list[Image.Image] = []
    for block in blocks:
        if not block.text.strip():
            continue
        local_t = t - block.start_time
        if local_t < 0 or local_t >= block.duration:
            continue
        wf = corner_block_width_factor(local_t, block.duration)
        if wf <= 0.001:
            continue
        result.append(
            render_corner_text_overlay(
                block.text,
                frame_w,
                frame_h,
                block.position,
                wf,
                block.font_color,
                block.bg_color,
                watermark_layout=watermark_layout,
                font_size=block.font_size,
            )
        )
    return result
