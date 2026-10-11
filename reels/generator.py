"""Build vertical Reels video from slides configuration."""

from __future__ import annotations

import gc
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from moviepy.editor import AudioFileClip, ImageSequenceClip, VideoFileClip
from PIL import Image

from reels.animations import (
    composite_frame,
    frame_animated_image,
    photo_transform,
    render_text_overlay,
    text_motion,
)
from reels.colors import FIT_IMAGE_RATIO, DEFAULT_BG_COLOR, hex_to_rgb
from reels.audio import download_youtube_audio
from reels.images import load_image


REELS_WIDTH = 1080
REELS_HEIGHT = 1920
DEFAULT_FPS = 30


@dataclass
class TextBlock:
    text: str
    font_color: str = "#FFFFFF"
    bg_color: str = "#000000CC"
    duration: float = 2.0
    start_offset: float = 0.0
    animation: str = "fade_in"
    position: str = "bottom"
    font_size: int | None = None  # None / 0 = auto


@dataclass
class SlideConfig:
    image_url: str = ""
    image_path: str | None = None
    duration: float = 5.0
    photo_animation: str = "ken_burns"
    texts: list[TextBlock] = field(default_factory=list)
    frame_mode: str = "fit"  # fit = full image + letterbox; cover = crop fill
    fit_ratio: float = FIT_IMAGE_RATIO
    letterbox_rgb: tuple[int, int, int] | None = None


@dataclass
class ReelsConfig:
    slides: list[SlideConfig]
    youtube_url: str = ""
    music_start: float = 0.0
    music_end: float | None = None
    fps: int = DEFAULT_FPS


def load_slide_image(slide: SlideConfig) -> Image.Image:
    if slide.image_path:
        return Image.open(slide.image_path).convert("RGB")
    if slide.image_url.strip():
        return load_image(slide.image_url)
    raise ValueError("Slide has no image_url or image_path")


def build_slide_frames(
    pil_image: Image.Image,
    slide: SlideConfig,
    fps: int,
) -> list[np.ndarray]:
    n_frames = max(1, int(slide.duration * fps))
    frames: list[np.ndarray] = []

    letterbox = slide.letterbox_rgb or hex_to_rgb(DEFAULT_BG_COLOR)
    use_fit = slide.frame_mode == "fit"

    for i in range(n_frames):
        t = i / max(n_frames - 1, 1)
        if slide.photo_animation == "ken_burns_subtle":
            base_scale = 1.0
        elif use_fit:
            base_scale = 1.0
        else:
            base_scale = 1.15
        scale, ox, oy = photo_transform(
            slide.photo_animation, t, base_scale=base_scale
        )
        if use_fit:
            # Keep almost the full image visible — limit zoom/pan strength
            scale = min(scale, 1.03)
            ox = max(-0.5, min(0.5, ox))
            oy = max(-0.5, min(0.5, oy))
        base = frame_animated_image(
            pil_image,
            REELS_WIDTH,
            REELS_HEIGHT,
            scale,
            ox,
            oy,
            mode=slide.frame_mode,
            letterbox_rgb=letterbox,
            fit_ratio=slide.fit_ratio,
        )

        time_sec = i / fps
        overlays: list[Image.Image] = []

        for block in slide.texts:
            local_t = time_sec - block.start_offset
            opacity, dx, dy = text_motion(block.animation, local_t, block.duration)
            scale_anim = 1.0
            if block.animation == "scale_in" and local_t >= 0:
                enter = min(0.45 * block.duration, 0.8)
                if local_t < enter and enter > 0:
                    p = local_t / enter
                    scale_anim = 0.6 + 0.4 * p

            if opacity > 0.01 and local_t < block.duration:
                overlays.append(
                    render_text_overlay(
                        block.text,
                        REELS_WIDTH,
                        REELS_HEIGHT,
                        block.font_color,
                        block.bg_color,
                        block.position,
                        opacity,
                        dx,
                        dy,
                        scale_anim,
                        font_size=block.font_size,
                    )
                )

        frames.append(composite_frame(base, overlays))

    return frames


def _ffmpeg_concat(parts: list[Path], output: Path) -> None:
    """Lossless-concat slide MP4s without loading frames into RAM."""
    list_path = output.with_suffix(".concat.txt")
    list_path.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in parts),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg concat failed: {(result.stderr or result.stdout or '')[-500:]}"
        )


def generate_reels(
    config: ReelsConfig,
    output_path: Path,
    work_dir: Path,
    progress_callback: Any | None = None,
) -> Path:
    """Generate MP4 and return output path.

    Encodes one slide at a time so peak RAM stays ~1 slide (not N×duration×fps frames).
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    part_paths: list[Path] = []
    total_slides = len(config.slides)
    total_duration = 0.0

    for idx, slide in enumerate(config.slides):
        if progress_callback:
            progress_callback(f"Загрузка фото {idx + 1}/{total_slides}...")
        img = load_slide_image(slide)
        if progress_callback:
            progress_callback(f"Рендер слайда {idx + 1}/{total_slides}...")
        frames = build_slide_frames(img, slide, config.fps)
        img.close()
        del img

        part = work_dir / f"slide_{idx:04d}.mp4"
        clip = ImageSequenceClip(frames, fps=config.fps)
        total_duration += float(clip.duration or 0.0)
        clip.write_videofile(
            str(part),
            fps=config.fps,
            codec="libx264",
            audio=False,
            preset="ultrafast",
            threads=2,
            logger=None,
        )
        clip.close()
        del frames
        del clip
        gc.collect()
        part_paths.append(part)

    if not part_paths:
        raise ValueError("No frames generated")

    if progress_callback:
        progress_callback("Сборка видео...")

    silent = work_dir / "silent.mp4"
    _ffmpeg_concat(part_paths, silent)

    output_path.parent.mkdir(parents=True, exist_ok=True)
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
        video = VideoFileClip(str(silent))
        audio = AudioFileClip(str(audio_path))
        if audio.duration > total_duration:
            audio = audio.subclip(0, total_duration)
        mixed = video.set_audio(audio)
        mixed.write_videofile(
            str(output_path),
            fps=config.fps,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=4,
            logger=None,
        )
        mixed.close()
        video.close()
        audio.close()
    else:
        silent.replace(output_path)

    return output_path
