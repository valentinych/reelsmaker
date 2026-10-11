"""Brand colors for letterbox and text defaults."""

DEFAULT_FONT_COLOR = "#FFD8B5"
DEFAULT_BG_COLOR = "#56858C"
DEFAULT_BG_ALPHA = 255

# Almost full frame — keeps bottom content visible
FIT_IMAGE_RATIO = 0.98


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) < 6:
        return 86, 133, 140
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
