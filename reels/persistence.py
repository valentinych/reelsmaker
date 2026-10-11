"""Autosave snapshots + durable media under TMPDIR/realsmaker."""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

AUTOSAVE_INTERVAL_SEC = 3 * 60
RETENTION = timedelta(hours=6)
SNAPSHOT_PREFIX = "reals_autosave_"
SNAPSHOT_RE = re.compile(
    r"^reals_autosave_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.json$"
)


def root_dir() -> Path:
    import os

    # Prefer explicit data dir; else TMPDIR if already .../realsmaker; else TMPDIR/realsmaker.
    explicit = os.environ.get("REALSMAKER_DATA", "").strip()
    if explicit:
        base = Path(explicit)
    else:
        tmp = Path(os.environ.get("TMPDIR") or "/tmp")
        base = tmp if tmp.name == "realsmaker" else tmp / "realsmaker"
    base.mkdir(parents=True, exist_ok=True)
    return base


def snapshots_dir() -> Path:
    d = root_dir() / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_media_dir(session_id: str) -> Path:
    d = root_dir() / "media" / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def ensure_session_id(existing: str | None) -> str:
    return existing if existing else new_session_id()


def cleanup_expired(now: float | None = None) -> int:
    """Delete snapshots and media older than RETENTION. Returns removed count."""
    now = now if now is not None else time.time()
    cutoff = now - RETENTION.total_seconds()
    removed = 0
    root = root_dir()

    snap = root / "snapshots"
    if snap.is_dir():
        for path in snap.glob(f"{SNAPSHOT_PREFIX}*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                pass

    media_root = root / "media"
    if media_root.is_dir():
        for session_dir in media_root.iterdir():
            if not session_dir.is_dir():
                continue
            try:
                mtime = max(
                    (p.stat().st_mtime for p in session_dir.rglob("*") if p.is_file()),
                    default=session_dir.stat().st_mtime,
                )
                if mtime < cutoff:
                    shutil.rmtree(session_dir, ignore_errors=True)
                    removed += 1
            except OSError:
                pass
    return removed


def _safe_name(name: str) -> str:
    name = Path(name).name
    return re.sub(r"[^\w.\-]+", "_", name)[:120] or "file.bin"


def persist_upload(
    session_id: str,
    *,
    filename: str,
    data: bytes,
    subdir: str = "",
    index: int | None = None,
) -> dict[str, Any]:
    """Write uploaded bytes to durable media dir. Returns descriptor."""
    base = session_media_dir(session_id)
    target_dir = base / subdir if subdir else base
    target_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{index:03d}_" if index is not None else ""
    path = target_dir / f"{prefix}{_safe_name(filename)}"
    path.write_bytes(data)
    return {
        "path": str(path),
        "name": filename,
        "size": len(data),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }


def list_snapshots() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(snapshots_dir().glob(f"{SNAPSHOT_PREFIX}*.json"), reverse=True):
        m = SNAPSHOT_RE.match(path.name)
        label = m.group(1) if m else path.stem
        try:
            size = path.stat().st_size
            mtime = path.stat().st_mtime
        except OSError:
            continue
        items.append(
            {
                "path": str(path),
                "name": path.name,
                "label": label.replace("_", " "),
                "size": size,
                "mtime": mtime,
            }
        )
    return items


def build_snapshot_payload(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 2,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "session_id": state.get("session_id"),
        "youtube_url": state.get("youtube_url", ""),
        "music_start": state.get("music_start", 0.0),
        "music_end": state.get("music_end"),
        "fit_percent": state.get("fit_percent", 98),
        "default_font_color": state.get("default_font_color"),
        "default_bg_color": state.get("default_bg_color"),
        "default_bg_alpha": state.get("default_bg_alpha"),
        "slides": state.get("slides", []),
        "reals": {
            "photo_duration": state.get("reals_photo_duration", 3.0),
            "wm_position": state.get("reals_wm_position", "bottom_right"),
            "wm_scale": state.get("reals_wm_scale", 22),
            "wm_opacity": state.get("reals_wm_opacity", 92),
            "opening_enabled": state.get("reals_opening_enabled", False),
            "opening_duration": state.get("reals_opening_duration", 2.0),
            "credits_enabled": state.get("reals_credits_enabled", False),
            "credits_duration": state.get("reals_credits_duration", 3.0),
            "text_blocks": state.get("reals_text_blocks", []),
            "media": state.get("reals_media", []),
            "watermark": state.get("reals_watermark"),
        },
        "static": {
            "slide_duration": state.get("static_slide_duration", 3.0),
            "media": state.get("static_media", []),
        },
    }


def write_snapshot(payload: dict[str, Any], *, stamp: datetime | None = None) -> Path:
    cleanup_expired()
    stamp = stamp or datetime.now()
    name = f"{SNAPSHOT_PREFIX}{stamp.strftime('%Y-%m-%d_%H-%M-%S')}.json"
    path = snapshots_dir() / name
    # avoid overwrite within same second
    if path.exists():
        name = f"{SNAPSHOT_PREFIX}{stamp.strftime('%Y-%m-%d_%H-%M-%S')}_{uuid.uuid4().hex[:4]}.json"
        path = snapshots_dir() / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_snapshot(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Некорректный JSON snapshot")
    return data


def media_paths_exist(descriptors: list[dict[str, Any]] | None) -> tuple[int, int]:
    """Return (ok, missing) counts for media path descriptors."""
    if not descriptors:
        return 0, 0
    ok = missing = 0
    for d in descriptors:
        p = Path(d.get("path", ""))
        if p.is_file():
            ok += 1
        else:
            missing += 1
    return ok, missing


def should_autosave(last_ts: float | None, interval_sec: int = AUTOSAVE_INTERVAL_SEC) -> bool:
    if last_ts is None:
        return True
    return (time.time() - float(last_ts)) >= interval_sec
