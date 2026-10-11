"""Photo and text animation helpers."""

from __future__ import annotations

import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from reels.colors import DEFAULT_BG_COLOR, FIT_IMAGE_RATIO, hex_to_rgb
from reels.fonts import auto_font_size, load_font


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    return 4 * t**3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


PHOTO_ANIMATIONS = {
    "zoom_in": "Приближение",
    "zoom_out": "Отдаление",
    "pan_left": "Панорама влево",
    "pan_right": "Панорама вправо",
    "pan_up": "Панорама вверх",
    "pan_down": "Панорама вниз",
    "ken_burns": "Ken Burns (зум + сдвиг)",
}

TEXT_ANIMATIONS = {
    "fade_in": "Появление",
    "slide_up": "Снизу вверх",
    "slide_down": "Сверху вниз",
    "slide_left": "Слева направо",
    "slide_right": "Справа налево",
    "scale_in": "Масштаб",
    "bounce_in": "Отскок",
}


def photo_transform(
    animation: str, progress: float, base_scale: float = 1.15
) -> tuple[float, float, float]:
    """Return (scale, offset_x, offset_y) relative to image center. progress in [0, 1]."""
    t = ease_in_out_cubic(max(0.0, min(1.0, progress)))

    if animation == "zoom_in":
        scale = base_scale * (1.0 + 0.2 * t)
        return scale, 0.0, 0.0
    if animation == "zoom_out":
        scale = base_scale * (1.2 - 0.2 * t)
        return scale, 0.0, 0.0
    if animation == "pan_left":
        return base_scale, -0.12 * t, 0.0
    if animation == "pan_right":
        return base_scale, 0.12 * t, 0.0
    if animation == "pan_up":
        return base_scale, 0.0, -0.12 * t
    if animation == "pan_down":
        return base_scale, 0.0, 0.12 * t
    if animation == "ken_burns":
        scale = base_scale * (1.0 + 0.15 * t)
        return scale, -0.08 * t, -0.05 * t
    if animation == "ken_burns_subtle":
        # Minimal motion — safe with fit framing (no crop)
        scale = 1.0 + 0.018 * t
        return scale, -0.015 * t, 0.01 * t

    return base_scale, 0.0, 0.0


def crop_animated_frame(
    pil_image: Image.Image,
    width: int,
    height: int,
    scale: float,
    offset_x: float,
    offset_y: float,
) -> Image.Image:
    """Crop and resize image to target frame with animated viewport (cover)."""
    img = pil_image.convert("RGB")
    iw, ih = img.size

    cover = max(width / iw, height / ih) * scale
    new_w, new_h = int(iw * cover), int(ih * cover)
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    cx = new_w / 2 + offset_x * new_w
    cy = new_h / 2 + offset_y * new_h
    left = int(cx - width / 2)
    top = int(cy - height / 2)
    left = max(0, min(left, new_w - width))
    top = max(0, min(top, new_h - height))

    cropped = resized.crop((left, top, left + width, top + height))
    if cropped.size != (width, height):
        cropped = cropped.resize((width, height), Image.Resampling.LANCZOS)
    return cropped


def fit_animated_frame(
    pil_image: Image.Image,
    width: int,
    height: int,
    scale: float,
    offset_x: float,
    offset_y: float,
    letterbox_rgb: tuple[int, int, int],
    fit_ratio: float = FIT_IMAGE_RATIO,
) -> Image.Image:
    """Fit almost the entire image inside the frame; letterbox uses brand background."""
    img = pil_image.convert("RGB")
    iw, ih = img.size

    canvas = Image.new("RGB", (width, height), letterbox_rgb)
    fit_scale = min(width / iw, height / ih) * fit_ratio * scale
    new_w = max(1, int(iw * fit_scale))
    new_h = max(1, int(ih * fit_scale))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    margin_x = max(0, (width - new_w) // 2)
    margin_y = max(0, (height - new_h) // 2)
    pan_x = int(offset_x * margin_x) if margin_x else 0
    pan_y = int(offset_y * margin_y) if margin_y else 0

    x = margin_x + pan_x
    y = margin_y + pan_y
    x = max(0, min(x, width - new_w))
    y = max(0, min(y, height - new_h))

    canvas.paste(resized, (x, y))
    return canvas


def frame_animated_image(
    pil_image: Image.Image,
    width: int,
    height: int,
    scale: float,
    offset_x: float,
    offset_y: float,
    mode: str = "fit",
    letterbox_rgb: tuple[int, int, int] | None = None,
    fit_ratio: float = FIT_IMAGE_RATIO,
) -> Image.Image:
    if mode == "cover":
        return crop_animated_frame(
            pil_image, width, height, scale, offset_x, offset_y
        )

    bg = letterbox_rgb or hex_to_rgb(DEFAULT_BG_COLOR)
    return fit_animated_frame(
        pil_image,
        width,
        height,
        scale,
        offset_x,
        offset_y,
        bg,
        fit_ratio=fit_ratio,
    )


def text_motion(
    animation: str, local_t: float, duration: float
) -> tuple[float, float, float]:
    """Return (opacity 0-1, dx px, dy px) for text overlay."""
    if duration <= 0:
        return 1.0, 0.0, 0.0

    enter = min(0.45 * duration, 0.8)
    if local_t >= duration:
        return 0.0, 0.0, 0.0
    if local_t < 0:
        return 0.0, 0.0, 0.0

    # Hold full opacity after enter
    if local_t > enter:
        return 1.0, 0.0, 0.0

    p = ease_out_cubic(local_t / enter) if enter > 0 else 1.0
    opacity = p
    travel = 80

    if animation == "fade_in":
        return opacity, 0.0, 0.0
    if animation == "slide_up":
        return opacity, 0.0, travel * (1 - p)
    if animation == "slide_down":
        return opacity, 0.0, -travel * (1 - p)
    if animation == "slide_left":
        return opacity, travel * (1 - p), 0.0
    if animation == "slide_right":
        return opacity, -travel * (1 - p), 0.0
    if animation == "scale_in":
        return opacity, 0.0, 0.0
    if animation == "bounce_in":
        bounce = math.sin(p * math.pi) * 0.15 * (1 - p)
        return opacity, 0.0, -30 * (1 - p) + bounce * 100

    return opacity, 0.0, 0.0


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Backward-compatible alias — always Jost when bundled."""
    return load_font(size)


def render_text_overlay(
    text: str,
    frame_w: int,
    frame_h: int,
    font_color: str,
    bg_color: str,
    position: str,
    opacity: float,
    dx: float,
    dy: float,
    scale_anim: float = 1.0,
    font_size: int | None = None,
) -> Image.Image:
    """RGBA overlay with text and rounded background."""
    overlay = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    if not text.strip() or opacity <= 0.01:
        return overlay

    draw = ImageDraw.Draw(overlay)
    resolved = int(font_size) if font_size and font_size > 0 else auto_font_size(frame_w, mode="frame")
    font = load_font(resolved)

    padding_x, padding_y = 24, 16
    max_text_w = int(frame_w * 0.88)
    lines = _wrap_text(text, font, max_text_w, draw)

    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    block_w = max(line_widths) + padding_x * 2
    block_h = sum(line_heights) + padding_y * 2 + (len(lines) - 1) * 8

    if position == "top":
        bx = (frame_w - block_w) // 2
        by = int(frame_h * 0.08)
    elif position == "bottom":
        bx = (frame_w - block_w) // 2
        by = int(frame_h * 0.78) - block_h
    else:
        bx = (frame_w - block_w) // 2
        by = (frame_h - block_h) // 2

    bx = int(bx + dx)
    by = int(by + dy)

    alpha = int(255 * max(0, min(1, opacity)))
    bg_rgba = _hex_to_rgba(bg_color, alpha)
    fg_rgba = _hex_to_rgba(font_color, alpha)

    radius = 16
    draw.rounded_rectangle(
        [bx, by, bx + block_w, by + block_h],
        radius=radius,
        fill=bg_rgba,
    )

    if scale_anim != 1.0 and animation_scale_applies(scale_anim):
        pass  # scale handled via font size below

    effective_size = int(resolved * scale_anim)
    if effective_size != resolved:
        font = load_font(effective_size)

    y = by + padding_y
    for i, line in enumerate(lines):
        tw = line_widths[i]
        tx = bx + (block_w - tw) // 2
        draw.text((tx, y), line, font=font, fill=fg_rgba)
        y += line_heights[i] + 8

    return overlay


def animation_scale_applies(scale: float) -> bool:
    return abs(scale - 1.0) > 0.01


def _wrap_text(
    text: str, font: ImageFont.FreeTypeFont, max_w: int, draw: ImageDraw.ImageDraw
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        test = f"{current} {word}"
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_w:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 8:
        return (
            int(h[0:2], 16),
            int(h[2:4], 16),
            int(h[4:6], 16),
            int(h[6:8], 16),
        )
    if len(h) == 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)
    return (0, 0, 0, alpha)


def composite_frame(
    base: Image.Image,
    overlays: list[Image.Image],
) -> np.ndarray:
    result = base.convert("RGBA")
    for ov in overlays:
        result = Image.alpha_composite(result, ov)
    return np.array(result.convert("RGB"))
