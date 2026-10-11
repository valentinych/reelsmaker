"""FastAPI: media upload, jobs, drafts, SPA under /reel/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.jobs import create_job, public_status, read_meta, result_path
from reels.persistence import (
    build_snapshot_payload,
    cleanup_expired,
    ensure_session_id,
    list_snapshots,
    load_snapshot,
    persist_upload,
    session_media_dir,
    write_snapshot,
)
from reels.watermark_reels import probe_duration_sec, safe_media_kind

APP_ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = APP_ROOT / "web" / "dist"

app = FastAPI(title="RealsMaker", docs_url="/reel/api/docs", openapi_url="/reel/api/openapi.json")


class TextBlockIn(BaseModel):
    text: str = ""
    start_time: float = 0.0
    duration: float = 3.0
    position: str = "bottom_right"
    font_size: int = 0


class MediaItemIn(BaseModel):
    path: str = ""
    trim_start: float | None = None
    trim_end: float | None = None


class JobCreate(BaseModel):
    session_id: str = ""
    kind: str = "watermark"  # watermark | static
    media_ids: list[str] = Field(default_factory=list)
    """Absolute paths or media descriptor paths already on disk."""
    media_paths: list[str] = Field(default_factory=list)
    """Ordered media descriptors (preferred); includes optional video trim."""
    media: list[MediaItemIn] = Field(default_factory=list)
    watermark_path: str = ""
    photo_duration: float = 3.0
    fit_percent: int = 98
    wm_position: str = "bottom_right"
    wm_scale: int = 22
    wm_opacity: int = 92
    youtube_url: str = ""
    music_start: float = 0.0
    music_end: float | None = None
    opening_enabled: bool = False
    opening_duration: float = 2.0
    credits_enabled: bool = False
    credits_duration: float = 3.0
    text_blocks: list[TextBlockIn] = Field(default_factory=list)


class DraftIn(BaseModel):
    session_id: str = ""
    state: dict[str, Any] = Field(default_factory=dict)


@app.on_event("startup")
def _startup() -> None:
    cleanup_expired()


@app.get("/reel/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "realsmaker"}


def _media_preview_url(session_id: str, abs_path: str) -> str:
    return f"/reel/api/media/file?session_id={quote(session_id)}&path={quote(abs_path)}"


def _resolve_session_file(session_id: str, path: str) -> Path:
    """Resolve a media path and ensure it stays under the session media dir."""
    sid = (session_id or "").strip()
    if not sid or "/" in sid or ".." in sid:
        raise HTTPException(400, "invalid session_id")
    root = session_media_dir(sid).resolve()
    candidate = Path(path).expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(403, "path outside session media") from exc
    if not candidate.is_file():
        raise HTTPException(404, "media not found")
    return candidate


@app.post("/reel/api/media")
async def upload_media(
    files: list[UploadFile] = File(...),
    session_id: str = Form(""),
    subdir: str = Form("reals"),
) -> dict[str, Any]:
    sid = ensure_session_id(session_id or None)
    cleanup_expired()
    saved: list[dict[str, Any]] = []
    for i, upl in enumerate(files):
        data = await upl.read()
        name = upl.filename or f"file_{i}.bin"
        kind = safe_media_kind(Path(name))
        desc = persist_upload(sid, filename=name, data=data, subdir=subdir, index=i)
        desc["kind"] = kind
        desc["id"] = desc["path"]
        desc["url"] = _media_preview_url(sid, desc["path"])
        duration_sec = None
        if kind == "video":
            duration_sec = probe_duration_sec(Path(desc["path"]))
        desc["duration_sec"] = duration_sec
        saved.append(desc)
    return {"session_id": sid, "files": saved}


@app.get("/reel/api/media/file")
def serve_media_file(
    session_id: str = Query(...),
    path: str = Query(...),
) -> FileResponse:
    file_path = _resolve_session_file(session_id, path)
    return FileResponse(file_path, filename=file_path.name)


@app.post("/reel/api/jobs")
def create_render_job(body: JobCreate) -> dict[str, Any]:
    kind = (body.kind or "watermark").strip().lower()
    if kind not in ("watermark", "static"):
        raise HTTPException(400, "kind must be watermark or static")
    media_items = [m.model_dump() for m in body.media if (m.path or "").strip()]
    if media_items:
        paths = [str(m["path"]) for m in media_items]
    else:
        # Prefer ordered media_ids when present (ids are absolute paths today).
        paths = list(body.media_ids) if body.media_ids else list(body.media_paths)
        media_items = [{"path": p, "trim_start": None, "trim_end": None} for p in paths]
    if not paths:
        raise HTTPException(400, "media_paths or media_ids required")
    for p in paths:
        if not Path(p).is_file():
            raise HTTPException(400, f"media not found: {Path(p).name}")
    if kind == "watermark":
        if not body.watermark_path:
            raise HTTPException(400, "watermark_path required")
        wm = Path(body.watermark_path)
        if not wm.is_file():
            raise HTTPException(400, "watermark file not found")
    else:
        for p in paths:
            if safe_media_kind(Path(p)) != "image":
                raise HTTPException(400, f"static jobs need images only: {Path(p).name}")

    config = body.model_dump()
    config["kind"] = kind
    config["media_paths"] = paths
    config["media_ids"] = paths
    config["media"] = media_items
    meta = create_job(config)
    return {"job_id": meta["id"], **public_status(meta)}


@app.get("/reel/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    meta = read_meta(job_id)
    if not meta:
        raise HTTPException(404, "job not found")
    return public_status(meta)


@app.get("/reel/api/jobs/{job_id}/download")
def download_job(job_id: str):
    meta = read_meta(job_id)
    if not meta:
        raise HTTPException(404, "job not found")
    if meta.get("status") != "done":
        raise HTTPException(409, "job not ready")
    path = result_path(job_id)
    if not path.is_file():
        raise HTTPException(404, "result missing")
    kind = ((meta.get("config") or {}).get("kind") or "watermark")
    filename = "static_reels.mp4" if kind == "static" else "reals_watermark.mp4"
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=filename,
    )


@app.get("/reel/api/drafts")
def drafts_list() -> dict[str, Any]:
    cleanup_expired()
    return {"drafts": list_snapshots()}


@app.post("/reel/api/drafts")
def drafts_save(body: DraftIn) -> dict[str, Any]:
    sid = ensure_session_id(body.session_id or None)
    state = dict(body.state)
    state["session_id"] = sid
    payload = build_snapshot_payload(state)
    path = write_snapshot(payload)
    return {"ok": True, "session_id": sid, "path": str(path), "name": path.name}


@app.get("/reel/api/drafts/{name}")
def drafts_get(name: str) -> dict[str, Any]:
    safe = Path(name).name
    if not safe.startswith("reals_autosave_") or not safe.endswith(".json"):
        raise HTTPException(400, "invalid draft name")
    from reels.persistence import snapshots_dir

    path = snapshots_dir() / safe
    if not path.is_file():
        raise HTTPException(404, "draft not found")
    return load_snapshot(path)


@app.get("/reel/api/meta")
def ui_meta() -> dict[str, Any]:
    from reels.corner_text import CORNER_POSITIONS
    from reels.watermark import POSITIONS

    return {
        "wm_positions": POSITIONS,
        "corner_positions": CORNER_POSITIONS,
        "default_bg": "#1A1A2E",
        "default_font": "#FFFFFF",
    }


# SPA: serve built assets under /reel/
if WEB_DIST.is_dir():
    assets = WEB_DIST / "assets"
    if assets.is_dir():
        app.mount("/reel/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/reel")
    @app.get("/reel/")
    @app.get("/reel/{full_path:path}")
    def spa(full_path: str = ""):
        # Don't steal API routes; reject leftover Streamlit paths
        if full_path.startswith("api") or full_path.startswith("_"):
            raise HTTPException(404)
        index = WEB_DIST / "index.html"
        if not index.is_file():
            raise HTTPException(503, "SPA not built")
        # Prefer exact static file if present
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)
