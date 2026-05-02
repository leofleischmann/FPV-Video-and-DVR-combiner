"""GPU-first FFmpeg video encoder selection with automatic CPU fallback.

Detection order (H.264): NVENC → AMF → QuickSync → libx264
(HEVC): hevc_nvenc → hevc_amf → hevc_qsv → libx265

Set FORCE_FFMPEG_CPU=1 to skip hardware probes (tests / deterministic CI).
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# --- Cached picks (evaluated lazily on first use) ---
_cached_h264: Optional[Tuple[str, List[str]]] = None
_cached_h265: Optional[Tuple[str, List[str]]] = None


def _force_cpu() -> bool:
    return os.environ.get("FORCE_FFMPEG_CPU", "").strip() in ("1", "true", "yes")


def _probe_encoder(codec_name: str, extra_before: Optional[List[str]] = None) -> bool:
    """One-frame black encode; succeeds only if the encoder actually runs."""
    extra_before = extra_before or []
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        # NVENC rejects very small frames (e.g. 128x128); use a size above driver minimum.
        "color=c=black:s=320x240:d=0.05",
        "-vf",
        "format=yuv420p",
        "-frames:v",
        "1",
        *extra_before,
        "-c:v",
        codec_name,
        "-f",
        "null",
        "-",
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=45,
            stdin=subprocess.DEVNULL,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# Encoder argument templates (quality roughly comparable to previous libx264 medium crf20 / libx265 crf26)
_CPU_H264 = [
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "20",
    "-pix_fmt",
    "yuv420p",
]
_CPU_H265 = [
    "-c:v",
    "libx265",
    "-preset",
    "medium",
    "-crf",
    "26",
    "-tag:v",
    "hvc1",
    "-pix_fmt",
    "yuv420p",
]

_NVENC_H264 = [
    "-c:v",
    "h264_nvenc",
    "-preset",
    "p4",
    "-tune",
    "hq",
    "-rc",
    "vbr",
    "-cq",
    "21",
    "-bf",
    "2",
    "-pix_fmt",
    "yuv420p",
]
_NVENC_H265 = [
    "-c:v",
    "hevc_nvenc",
    "-preset",
    "p4",
    "-tune",
    "hq",
    "-rc",
    "vbr",
    "-cq",
    "24",
    "-tag:v",
    "hvc1",
    "-pix_fmt",
    "yuv420p",
]

_AMF_H264 = [
    "-c:v",
    "h264_amf",
    "-quality",
    "quality",
    "-rc",
    "cqp",
    "-qp_i",
    "22",
    "-qp_p",
    "24",
    "-pix_fmt",
    "yuv420p",
]
_AMF_H265 = [
    "-c:v",
    "hevc_amf",
    "-quality",
    "quality",
    "-rc",
    "cqp",
    "-qp_i",
    "24",
    "-qp_p",
    "26",
    "-tag:v",
    "hvc1",
    "-pix_fmt",
    "yuv420p",
]

_QSV_H264 = [
    "-c:v",
    "h264_qsv",
    "-preset",
    "medium",
    "-global_quality",
    "23",
    "-look_ahead",
    "1",
    "-pix_fmt",
    "yuv420p",
]
_QSV_H265 = [
    "-c:v",
    "hevc_qsv",
    "-preset",
    "medium",
    "-global_quality",
    "26",
    "-tag:v",
    "hvc1",
    "-pix_fmt",
    "yuv420p",
]


def get_h264_encoder() -> Tuple[str, List[str]]:
    """Return (encoder_name, ffmpeg_args_without_audio)."""
    global _cached_h264
    if _cached_h264 is not None:
        return _cached_h264

    if _force_cpu():
        _cached_h264 = ("libx264", list(_CPU_H264))
        logger.info("Video encoder: libx264 (FORCE_FFMPEG_CPU)")
        return _cached_h264

    candidates: List[Tuple[str, List[str], str]] = [
        ("h264_nvenc", _NVENC_H264, "NVIDIA NVENC"),
        ("h264_amf", _AMF_H264, "AMD AMF"),
        ("h264_qsv", _QSV_H264, "Intel Quick Sync"),
    ]
    for enc_name, args, label in candidates:
        if _probe_encoder(enc_name):
            _cached_h264 = (enc_name, list(args))
            logger.info("Video encoder: %s (%s)", enc_name, label)
            return _cached_h264

    _cached_h264 = ("libx264", list(_CPU_H264))
    logger.info("Video encoder: libx264 (CPU fallback — no working HW encoder)")
    return _cached_h264


def get_h265_encoder() -> Tuple[str, List[str]]:
    """Return (encoder_name, ffmpeg_args_without_audio)."""
    global _cached_h265
    if _cached_h265 is not None:
        return _cached_h265

    if _force_cpu():
        _cached_h265 = ("libx265", list(_CPU_H265))
        logger.info("HEVC encoder: libx265 (FORCE_FFMPEG_CPU)")
        return _cached_h265

    candidates: List[Tuple[str, List[str], str]] = [
        ("hevc_nvenc", _NVENC_H265, "NVIDIA NVENC"),
        ("hevc_amf", _AMF_H265, "AMD AMF"),
        ("hevc_qsv", _QSV_H265, "Intel Quick Sync"),
    ]
    for enc_name, args, label in candidates:
        if _probe_encoder(enc_name):
            _cached_h265 = (enc_name, list(args))
            logger.info("HEVC encoder: %s (%s)", enc_name, label)
            return _cached_h265

    _cached_h265 = ("libx265", list(_CPU_H265))
    logger.info("HEVC encoder: libx265 (CPU fallback — no working HW encoder)")
    return _cached_h265


def encoder_args_for_codec(codec: str) -> Tuple[str, List[str]]:
    """codec is 'h264' or 'h265' from the API."""
    if codec == "h265":
        return get_h265_encoder()
    return get_h264_encoder()


def log_encoder_cache_status() -> str:
    """Human-readable summary for job logs."""
    h264_n, _ = get_h264_encoder()
    h265_n, _ = get_h265_encoder()
    return f"H.264->{h264_n}, HEVC->{h265_n}"


def reset_cache_for_tests() -> None:
    global _cached_h264, _cached_h265
    _cached_h264 = None
    _cached_h265 = None


def encoding_public_info() -> dict:
    """Structured encoder status for GET /api/encoding (UI badge)."""
    h264_n, _ = get_h264_encoder()
    h265_n, _ = get_h265_encoder()
    h264_hw = h264_n not in ("libx264",)
    h265_hw = h265_n not in ("libx265",)
    return {
        "h264": {"encoder": h264_n, "hardware": h264_hw},
        "h265": {"encoder": h265_n, "hardware": h265_hw},
        "force_cpu_env": _force_cpu(),
        # Typical PiP export uses H.264 — this drives the main GPU/CPU badge.
        "primary_hw": h264_hw,
        "label_short": "GPU" if h264_hw else "CPU",
    }
