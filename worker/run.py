"""Poll pending jobs and run generate_* off the request path."""

from __future__ import annotations

import logging
import signal
import sys
import time
import traceback
from pathlib import Path

from api.jobs import jobs_dir, list_pending, read_meta, result_path, update_job
from reels.corner_text import CornerTextBlock
from reels.generator import ReelsConfig, SlideConfig, generate_reels
from reels.persistence import cleanup_expired
from reels.watermark_reels import (
    WatermarkMediaItem,
    WatermarkReelsConfig,
    generate_watermark_reels,
    media_kind,
)

log = logging.getLogger("realsmaker.worker")
POLL_SEC = 1.5
_running = True


def _stop(*_args) -> None:
    global _running
    _running = False


MAX_CRASH_RECLAIMS = 3


def _reclaim_stale_running() -> None:
    """Jobs left as 'running' after an OOM/crash would never finish — re-queue them."""
    root = jobs_dir()
    if not root.is_dir():
        return
    for path in root.iterdir():
        if not path.is_dir():
            continue
        meta = read_meta(path.name)
        if not meta or meta.get("status") != "running":
            continue
        attempts = int(meta.get("crash_reclaims") or 0) + 1
        if attempts > MAX_CRASH_RECLAIMS:
            update_job(
                path.name,
                status="error",
                progress=0,
                message="Ошибка",
                error=(
                    f"Воркер упал {attempts}× во время рендера "
                    "(часто OOM). Уменьшите число слайдов/длительность и повторите."
                ),
                crash_reclaims=attempts,
            )
            log.error("gave up on crash-looping job %s after %s reclaims", path.name, attempts)
            continue
        update_job(
            path.name,
            status="pending",
            progress=0,
            message=f"В очереди (перезапуск воркера #{attempts})",
            error=None,
            crash_reclaims=attempts,
        )
        log.warning("reclaimed stale running job %s (attempt %s)", path.name, attempts)


def _on_progress(job_id: str, msg: str) -> None:
    cur = read_meta(job_id) or {}
    prog = min(90, int(cur.get("progress") or 5) + 5)
    update_job(job_id, status="running", progress=prog, message=msg)
    log.info("[%s] %s", job_id, msg)


def _run_static(job_id: str, config_data: dict, out: Path, work_dir: Path) -> None:
    media_paths = config_data.get("media_paths") or []
    photo_duration = float(config_data.get("photo_duration") or 3.0)
    fit_percent = int(config_data.get("fit_percent") or 98)
    music_end = config_data.get("music_end")
    if music_end is not None and float(music_end) <= float(config_data.get("music_start") or 0):
        music_end = None

    slides = [
        SlideConfig(
            image_path=str(p),
            duration=photo_duration,
            photo_animation="ken_burns_subtle",
            texts=[],
            frame_mode="fit",
            fit_ratio=fit_percent / 100.0,
        )
        for p in media_paths
    ]
    cfg = ReelsConfig(
        slides=slides,
        youtube_url=str(config_data.get("youtube_url") or "").strip(),
        music_start=float(config_data.get("music_start") or 0.0),
        music_end=float(music_end) if music_end is not None else None,
    )
    generate_reels(
        cfg,
        out,
        work_dir,
        progress_callback=lambda msg: _on_progress(job_id, msg),
    )


def _run_watermark(job_id: str, config_data: dict, out: Path, work_dir: Path) -> None:
    photo_duration = float(config_data.get("photo_duration") or 3.0)
    raw_media = config_data.get("media") or []
    if not raw_media:
        raw_media = [{"path": p} for p in (config_data.get("media_paths") or [])]

    items: list[WatermarkMediaItem] = []
    for entry in raw_media:
        if isinstance(entry, str):
            path = Path(entry)
            trim_start = None
            trim_end = None
        else:
            path = Path(entry.get("path") or "")
            trim_start = entry.get("trim_start")
            trim_end = entry.get("trim_end")
            if trim_start is not None:
                trim_start = float(trim_start)
            if trim_end is not None:
                trim_end = float(trim_end)
        kind = media_kind(path)
        items.append(
            WatermarkMediaItem(
                path=path,
                kind=kind,
                duration=photo_duration if kind == "image" else None,
                trim_start=trim_start if kind == "video" else None,
                trim_end=trim_end if kind == "video" else None,
            )
        )

    fit_percent = int(config_data.get("fit_percent") or 98)
    music_end = config_data.get("music_end")
    if music_end is not None and float(music_end) <= float(config_data.get("music_start") or 0):
        music_end = None

    text_blocks = [
        CornerTextBlock(
            text=tb.get("text", ""),
            start_time=float(tb.get("start_time", 0.0)),
            duration=float(tb.get("duration", 3.0)),
            position=tb.get("position", "bottom_right"),
            font_size=(
                int(tb["font_size"])
                if int(tb.get("font_size") or 0) > 0
                else None
            ),
        )
        for tb in (config_data.get("text_blocks") or [])
        if (tb.get("text") or "").strip()
    ]

    opening_enabled = bool(config_data.get("opening_enabled"))
    credits_enabled = bool(config_data.get("credits_enabled"))

    cfg = WatermarkReelsConfig(
        items=items,
        watermark_path=Path(config_data["watermark_path"]),
        photo_duration=photo_duration,
        fit_ratio=fit_percent / 100.0,
        watermark_position=str(config_data.get("wm_position") or "bottom_right"),
        watermark_scale=int(config_data.get("wm_scale") or 22) / 100.0,
        watermark_opacity=int(config_data.get("wm_opacity") or 92) / 100.0,
        youtube_url=str(config_data.get("youtube_url") or "").strip(),
        music_start=float(config_data.get("music_start") or 0.0),
        music_end=float(music_end) if music_end is not None else None,
        text_blocks=text_blocks,
        opening_enabled=opening_enabled,
        opening_duration=float(config_data.get("opening_duration") or 2.0)
        if opening_enabled
        else 0.0,
        credits_enabled=credits_enabled,
        credits_duration=float(config_data.get("credits_duration") or 3.0)
        if credits_enabled
        else 0.0,
    )

    generate_watermark_reels(
        cfg,
        out,
        work_dir,
        progress_callback=lambda msg: _on_progress(job_id, msg),
    )


def _run_job(job_id: str) -> None:
    meta = read_meta(job_id)
    if not meta or meta.get("status") != "pending":
        return

    claimed = update_job(job_id, status="running", progress=1, message="Старт...")
    if not claimed or claimed.get("status") != "running":
        return

    config_data = meta.get("config") or {}
    from api.jobs import job_dir

    jd = job_dir(job_id)
    work_dir = jd / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    out = result_path(job_id)
    kind = str(config_data.get("kind") or "watermark").lower()

    try:
        if kind == "static":
            _run_static(job_id, config_data, out, work_dir)
        else:
            _run_watermark(job_id, config_data, out, work_dir)
        update_job(
            job_id,
            status="done",
            progress=100,
            message="Готово",
            error=None,
            result_file=str(out),
            crash_reclaims=0,
        )
        log.info("[%s] done → %s", job_id, out)
    except Exception as exc:
        log.exception("[%s] failed", job_id)
        update_job(
            job_id,
            status="error",
            progress=0,
            message="Ошибка",
            error=f"{exc}\n{traceback.format_exc()[-800:]}",
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("worker started (file queue)")
    try:
        _reclaim_stale_running()
    except Exception:
        log.exception("stale-job reclaim failed")
    last_cleanup = 0.0
    while _running:
        now = time.time()
        if now - last_cleanup > 600:
            try:
                cleanup_expired()
            except Exception:
                log.exception("cleanup failed")
            last_cleanup = now

        pending = list_pending(limit=1)
        if pending:
            _run_job(pending[0]["id"])
        else:
            time.sleep(POLL_SEC)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
