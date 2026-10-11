"""Load images from URLs or local paths."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _request_headers(url: str) -> dict[str, str]:
    headers = dict(DEFAULT_HEADERS)
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    return headers


def load_image(source: str, timeout: int = 30) -> Image.Image:
    source = source.strip()
    if not source:
        raise ValueError("Empty image source")

    if source.startswith(("http://", "https://")):
        resp = requests.get(
            source,
            headers=_request_headers(source),
            timeout=timeout,
        )
        resp.raise_for_status()
        return Image.open(BytesIO(resp.content))

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {source}")
    return Image.open(path)
