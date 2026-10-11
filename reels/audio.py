"""Download and trim audio from YouTube."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def download_youtube_audio(
    url: str,
    start_sec: float,
    end_sec: float | None,
    output_path: Path,
) -> Path:
    """Download audio segment from YouTube using yt-dlp and ffmpeg."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        raw_audio = tmp_dir / "audio.%(ext)s"

        ytdlp_cmd = [
            "yt-dlp",
            "-x",
            "--audio-format",
            "m4a",
            "-o",
            str(raw_audio),
            "--no-playlist",
            url,
        ]
        result = subprocess.run(ytdlp_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"yt-dlp failed: {result.stderr or result.stdout or 'unknown error'}"
            )

        downloaded = list(tmp_dir.glob("audio.*"))
        if not downloaded:
            raise FileNotFoundError("Audio file not found after download")
        source = downloaded[0]

        trim_cmd = ["ffmpeg", "-y", "-i", str(source)]
        if start_sec > 0:
            trim_cmd.extend(["-ss", str(start_sec)])
        if end_sec is not None and end_sec > start_sec:
            duration = end_sec - start_sec
            trim_cmd.extend(["-t", str(duration)])
        trim_cmd.extend(
            [
                "-vn",
                "-acodec",
                "aac",
                "-b:a",
                "192k",
                str(output_path),
            ]
        )

        result = subprocess.run(trim_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg trim failed: {result.stderr or result.stdout or 'unknown error'}"
            )

    return output_path
