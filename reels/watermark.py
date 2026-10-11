"""Watermark overlay for Reels frames."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


POSITIONS = {
    "bottom_right": "Справа внизу",
    "bottom_center": "По центру внизу",
    "bottom_left": "Слева внизу",
    "middle_right": "По центру справа",
    "middle_left": "По центру слева",
    "center": "По центру",
    "top_center": "По центру вверху",
}


@dataclass
class WatermarkLayout:
    x: int
    y: int
    width: int
    height: int
    position: str


def load_watermark(path: str) -> Image.Image:
    return Image.open(path).convert("RGBA")


def resized_watermark(
    watermark: Image.Image,
    frame_width: int,
    scale: float,
) -> Image.Image:
    target_w = max(1, int(frame_width * scale))
    ratio = target_w / max(watermark.width, 1)
    target_h = max(1, int(watermark.height * ratio))
    return watermark.resize((target_w, target_h), Image.Resampling.LANCZOS)


def compute_watermark_layout(
    frame_width: int,
    frame_height: int,
    watermark: Image.Image,
    *,
    position: str = "bottom_right",
    scale: float = 0.22,
    margin: int = 36,
) -> WatermarkLayout:
    wm = resized_watermark(watermark, frame_width, scale)
    x, y = _position_xy((frame_width, frame_height), wm.size, position, margin)
    return WatermarkLayout(x=x, y=y, width=wm.width, height=wm.height, position=position)


def apply_watermark(
    base: Image.Image,
    watermark: Image.Image,
    *,
    position: str = "bottom_right",
    scale: float = 0.22,
    opacity: float = 0.92,
    margin: int = 36,
) -> Image.Image:
    """Overlay watermark on a frame. scale = fraction of frame width."""
    if scale <= 0 or opacity <= 0:
        return base.convert("RGB")

    base_rgba = base.convert("RGBA")
    wm = resized_watermark(watermark, base_rgba.width, scale)

    if opacity < 1.0:
        r, g, b, a = wm.split()
        a = a.point(lambda v: int(v * opacity))
        wm = Image.merge("RGBA", (r, g, b, a))

    x, y = _position_xy(base_rgba.size, wm.size, position, margin)
    out = base_rgba.copy()
    out.paste(wm, (x, y), wm)
    return out.convert("RGB")


def render_brand_splash_frame(
    watermark: Image.Image,
    frame_width: int,
    frame_height: int,
    letterbox_rgb: tuple[int, int, int],
    *,
    scale: float = 0.35,
    opacity: float = 0.92,
) -> Image.Image:
    """Full-frame brand color with centered watermark (Opening / Титры)."""
    base = Image.new("RGB", (frame_width, frame_height), letterbox_rgb)
    return apply_watermark(
        base,
        watermark,
        position="center",
        scale=scale,
        opacity=opacity,
        margin=0,
    )


def _position_xy(
    frame_size: tuple[int, int],
    wm_size: tuple[int, int],
    position: str,
    margin: int,
) -> tuple[int, int]:
    fw, fh = frame_size
    ww, wh = wm_size

    if position == "bottom_left":
        return margin, fh - wh - margin
    if position == "bottom_center":
        return (fw - ww) // 2, fh - wh - margin
    if position == "middle_left":
        return margin, (fh - wh) // 2
    if position == "middle_right":
        return fw - ww - margin, (fh - wh) // 2
    if position == "center":
        return (fw - ww) // 2, (fh - wh) // 2
    if position == "top_center":
        return (fw - ww) // 2, margin
    # bottom_right default
    return fw - ww - margin, fh - wh - margin
