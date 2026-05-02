"""Optional FFmpeg CUDA (NVDEC) decode path before CPU filters.

Requires NVIDIA GPU + drivers in the container (same as NVENC). When unavailable,
the PiP pipeline stays on CPU decode — no functional change.

Set DISABLE_CUDA_DECODE=1 to force CPU decode. FORCE_FFMPEG_CPU=1 also disables
this path so behaviour matches encoder CPU fallback."""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_cached_cuda_decode: Optional[bool] = None


def _force_cpu_like_encode() -> bool:
    return os.environ.get("FORCE_FFMPEG_CPU", "").strip() in ("1", "true", "yes")


def _disabled_by_env() -> bool:
    return os.environ.get("DISABLE_CUDA_DECODE", "").strip() in ("1", "true", "yes")


def reset_cuda_decode_cache_for_tests() -> None:
    global _cached_cuda_decode
    _cached_cuda_decode = None


def cuda_decode_available() -> bool:
    """True if FFmpeg can decode H.264 with hwaccel=cuda and run hwdownload."""
    global _cached_cuda_decode
    if _cached_cuda_decode is not None:
        return _cached_cuda_decode
    if _disabled_by_env() or _force_cpu_like_encode():
        _cached_cuda_decode = False
        return False
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-hwaccels"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        combined = (out.stdout or "") + (out.stderr or "")
        if out.returncode != 0 or "cuda" not in combined.lower():
            _cached_cuda_decode = False
            return False
    except (OSError, subprocess.TimeoutExpired):
        _cached_cuda_decode = False
        return False

    fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        gen = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x240:d=0.15",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(tmp),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if gen.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 100:
            _cached_cuda_decode = False
            return False
        probe = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-hwaccel",
                "cuda",
                "-hwaccel_output_format",
                "cuda",
                "-i",
                str(tmp),
                "-vf",
                "hwdownload,format=yuv420p",
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        ok = probe.returncode == 0
        if not ok and probe.stderr:
            logger.debug("CUDA decode probe stderr (tail): %s", probe.stderr[-600:])
        _cached_cuda_decode = ok
        return ok
    except (OSError, subprocess.TimeoutExpired):
        _cached_cuda_decode = False
        return False
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def use_cuda_decode_for_pip(encoder_name: str) -> bool:
    """PiP may use NVDEC when the export encoder is NVIDIA NVENC."""
    if encoder_name not in ("h264_nvenc", "hevc_nvenc"):
        return False
    return cuda_decode_available()
