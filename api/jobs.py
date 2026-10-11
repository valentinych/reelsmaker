"""File-based job store under REALSMAKER_DATA/jobs/."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from reels.persistence import root_dir

STATUSES = ("pending", "running", "done", "error")


def jobs_dir() -> Path:
    d = root_dir() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def job_dir(job_id: str) -> Path:
    return jobs_dir() / job_id


def _meta_path(job_id: str) -> Path:
    return job_dir(job_id) / "meta.json"


def new_job_id() -> str:
    return uuid.uuid4().hex[:16]


def write_meta(job_id: str, meta: dict[str, Any]) -> None:
    path = _meta_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_meta(job_id: str) -> dict[str, Any] | None:
    path = _meta_path(job_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def create_job(config: dict[str, Any]) -> dict[str, Any]:
    job_id = new_job_id()
    jd = job_dir(job_id)
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "work").mkdir(exist_ok=True)
    meta = {
        "id": job_id,
        "status": "pending",
        "progress": 0,
        "message": "В очереди",
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
        "result_file": None,
        "config": config,
    }
    write_meta(job_id, meta)
    return meta


def update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    meta = read_meta(job_id)
    if not meta:
        return None
    meta.update(fields)
    meta["updated_at"] = time.time()
    write_meta(job_id, meta)
    return meta


def list_pending(limit: int = 5) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    root = jobs_dir()
    for path in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime):
        if not path.is_dir():
            continue
        meta = read_meta(path.name)
        if meta and meta.get("status") == "pending":
            items.append(meta)
            if len(items) >= limit:
                break
    return items


def result_path(job_id: str) -> Path:
    return job_dir(job_id) / "result.mp4"


def public_status(meta: dict[str, Any]) -> dict[str, Any]:
    job_id = meta["id"]
    status = meta.get("status", "pending")
    result_url = None
    if status == "done" and result_path(job_id).is_file():
        result_url = f"/reel/api/jobs/{job_id}/download"
    return {
        "id": job_id,
        "status": status,
        "progress": int(meta.get("progress") or 0),
        "message": meta.get("message") or "",
        "error": meta.get("error"),
        "result_url": result_url,
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
    }
