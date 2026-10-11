"""Build vertical Reels from photos/videos with a watermark overlay."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from moviepy.editor import AudioFileClip, ImageSequenceClip, VideoFileClip, concatenate_videoclips
from PIL import Image

from reels.animations import composite_frame, frame_animated_image
from reels.corner_text import CornerTextBlock, overlays_at_time
from reels.audio import download_youtube_audio
from reels.colors import DEFAULT_BG_COLOR, FIT_IMAGE_RATIO, hex_to_rgb
from reels.generator import REELS_HEIGHT, REELS_WIDTH, DEFAULT_FPS
from reels.watermark import (
    apply_watermark,
    compute_watermark_layout,
    load_watermark,
    render_brand_splash_frame,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


@dataclass
class WatermarkMediaItem:
    path: Path
    kind: str  # "image" | "video"
    duration: float | None = None  # seconds, images only
    trim_start: float | None = None  # video clip start (sec)
    trim_end: float | None = None  # video clip end (sec)


@dataclass
class WatermarkReelsConfig:
    items: list[WatermarkMediaItem]
    watermark_path: Path
    photo_duration: float = 3.0
    fit_ratio: float = FIT_IMAGE_RATIO
    letterbox_rgb: tuple[int, int, int] | None = None
    watermark_position: str = "bottom_right"
    watermark_scale: float = 0.22
    watermark_opacity: float = 0.92
    watermark_margin: int = 36
    youtube_url: str = ""
    music_start: float = 0.0
    music_end: float | None = None
    fps: int = DEFAULT_FPS
    text_blocks: list[CornerTextBlock] = field(default_factory=list)
    opening_enabled: bool = False
    opening_duration: float = 2.0
    credits_enabled: bool = False
    credits_duration: float = 3.0


def media_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    raise ValueError(f"Неподдерживаемый формат: {path.name}")


def safe_media_kind(path: Path) -> str | None:
    try:
        return media_kind(path)
    except ValueError:
        return None


def probe_duration_sec(path: Path) -> float | None:
    """Return media duration in seconds via ffprobe, or None on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return None
        raw = (result.stdout or "").strip()
        if not raw:
            return None
        value = float(raw)
        return value if value > 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def normalize_trim(
    duration: float,
    trim_start: float | None,
    trim_end: float | None,
) -> tuple[float, float]:
    """Clamp trim window to [0, duration] with start < end; fall back to full clip."""
    dur = float(duration or 0.0)
    if dur <= 0:
        return 0.0, 0.0
    start = 0.0 if trim_start is None else float(trim_start)
    end = dur if trim_end is None else float(trim_end)
    start = max(0.0, min(start, dur))
    end = max(0.0, min(end, dur))
    if end <= start:
        return 0.0, dur
    return start, end


def _fit_and_watermark(
    pil_image: Image.Image,
    watermark: Image.Image,
    config: WatermarkReelsConfig,
) -> Image.Image:
    letterbox = config.letterbox_rgb or hex_to_rgb(DEFAULT_BG_COLOR)
    fitted = frame_animated_image(
        pil_image,
        REELS_WIDTH,
        REELS_HEIGHT,
        scale=1.0,
        offset_x=0.0,
        offset_y=0.0,
        mode="fit",
        letterbox_rgb=letterbox,
        fit_ratio=config.fit_ratio,
    )
    return apply_watermark(
        fitted,
        watermark,
        position=config.watermark_position,
        scale=config.watermark_scale,
        opacity=config.watermark_opacity,
        margin=config.watermark_margin,
    )


def _image_clip(
    path: Path,
    duration: float,
    watermark: Image.Image,
    config: WatermarkReelsConfig,
):
    pil = Image.open(path).convert("RGB")
    frame = np.array(_fit_and_watermark(pil, watermark, config))
    n_frames = max(1, int(duration * config.fps))
    frames = [frame] * n_frames
    return ImageSequenceClip(frames, fps=config.fps)


def _video_clip(
    path: Path,
    watermark: Image.Image,
    config: WatermarkReelsConfig,
    trim_start: float | None = None,
    trim_end: float | None = None,
):
    source = VideoFileClip(str(path))
    full_dur = float(source.duration or 0.0)
    start, end = normalize_trim(full_dur, trim_start, trim_end)
    if start > 0 or end < full_dur - 1e-6:
        source = source.subclip(start, end)

    def transform(frame: np.ndarray) -> np.ndarray:
        pil = Image.fromarray(frame)
        return np.array(_fit_and_watermark(pil, watermark, config))

    clip = source.fl_image(transform).set_fps(config.fps)
    if source.audio is not None:
        clip = clip.set_audio(source.audio)
    return clip


def _splash_clip(
    watermark: Image.Image,
    duration: float,
    config: WatermarkReelsConfig,
):
    letterbox = config.letterbox_rgb or hex_to_rgb(DEFAULT_BG_COLOR)
    # Opening / Титры: solid brand fill + fully opaque PNG (no transparency).
    splash_scale = max(config.watermark_scale * 1.6, 0.32)
    frame = np.array(
        render_brand_splash_frame(
            watermark,
            REELS_WIDTH,
            REELS_HEIGHT,
            letterbox,
            scale=splash_scale,
            opacity=1.0,
        )
    )
    n_frames = max(1, int(duration * config.fps))
    return ImageSequenceClip([frame] * n_frames, fps=config.fps)


def generate_watermark_reels(
    config: WatermarkReelsConfig,
    output_path: Path,
    work_dir: Path,
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    if not config.items:
        raise ValueError("Добавьте хотя бы одно фото или видео")
    if not config.watermark_path.exists():
        raise ValueError("Файл вотермарки не найден")

    work_dir.mkdir(parents=True, exist_ok=True)
    watermark = load_watermark(str(config.watermark_path))
    clips = []

    if config.opening_enabled and config.opening_duration > 0:
        if progress_callback:
            progress_callback("Рендер Opening...")
        clips.append(_splash_clip(watermark, config.opening_duration, config))

    for idx, item in enumerate(config.items):
        if progress_callback:
            progress_callback(f"Обработка {idx + 1}/{len(config.items)}: {item.path.name}")
        if item.kind == "image":
            duration = item.duration if item.duration else config.photo_duration
            clips.append(_image_clip(item.path, duration, watermark, config))
        else:
            clips.append(
                _video_clip(
                    item.path,
                    watermark,
                    config,
                    trim_start=item.trim_start,
                    trim_end=item.trim_end,
                )
            )

    if config.credits_enabled and config.credits_duration > 0:
        if progress_callback:
            progress_callback("Рендер титров...")
        clips.append(_splash_clip(watermark, config.credits_duration, config))

    if not clips:
        raise ValueError("Нет контента для сборки ролика")

    if progress_callback:
        progress_callback("Сборка ролика...")

    final = concatenate_videoclips(clips, method="compose")
    total_duration = final.duration

    active_texts = [b for b in config.text_blocks if b.text.strip()]
    if active_texts:
        if progress_callback:
            progress_callback("Наложение текстовых блоков...")

        wm_layout = compute_watermark_layout(
            REELS_WIDTH,
            REELS_HEIGHT,
            watermark,
            position=config.watermark_position,
            scale=config.watermark_scale,
            margin=config.watermark_margin,
        )

        def _with_texts(get_frame, t):
            frame = get_frame(t)
            overlays = overlays_at_time(
                active_texts, t, REELS_WIDTH, REELS_HEIGHT, wm_layout
            )
            if not overlays:
                return frame
            pil = Image.fromarray(frame)
            return composite_frame(pil, overlays)

        final = final.fl(_with_texts)

    if config.youtube_url.strip():
        if progress_callback:
            progress_callback("Загрузка музыки с YouTube...")
        audio_path = work_dir / "music.m4a"
        download_youtube_audio(
            config.youtube_url,
            config.music_start,
            config.music_end,
            audio_path,
        )
        audio = AudioFileClip(str(audio_path))
        if audio.duration > total_duration:
            audio = audio.subclip(0, total_duration)
        final = final.set_audio(audio)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.write_videofile(
        str(output_path),
        fps=config.fps,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        threads=4,
        logger=None,
    )
    final.close()
    for clip in clips:
        clip.close()

    return output_path
