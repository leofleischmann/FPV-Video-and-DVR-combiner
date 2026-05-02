"""FFmpeg helper functions: probing, concat (lossless), and the render pipeline.

Progress is reported via a callback that receives a fraction in [0, 1] and a
short stage label.  We parse FFmpeg's `-progress pipe:1` output (`out_time_us`)
to compute it, which is more reliable than scraping stderr.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple  # noqa: F401


ProgressCb = Callable[[float, str], None]


@dataclass
class ProbeInfo:
    width: int
    height: int
    duration: float
    has_audio: bool
    video_codec: str


def ffprobe(path: Path) -> ProbeInfo:
    """Return basic info for a media file using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-print_format", "json",
        "-show_streams", "-show_format",
        str(path),
    ]
    out = subprocess.check_output(cmd)
    data = json.loads(out)
    width = height = 0
    video_codec = ""
    has_audio = False
    duration = 0.0
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not width:
            width = int(s.get("width") or 0)
            height = int(s.get("height") or 0)
            video_codec = s.get("codec_name") or ""
            if s.get("duration"):
                try:
                    duration = float(s["duration"])
                except (TypeError, ValueError):
                    pass
        elif s.get("codec_type") == "audio":
            has_audio = True
    if not duration:
        try:
            duration = float(data.get("format", {}).get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
    return ProbeInfo(width, height, duration, has_audio, video_codec)


BROWSER_FRIENDLY_CODECS = {"h264", "avc", "avc1"}


def is_browser_playable(probe: ProbeInfo) -> bool:
    """Heuristic: H.264 in MP4/MOV plays in every modern browser.

    HEVC/H.265 (typical for DJI Goggles), VP9, AV1, MPEG-4 etc. need a
    transcoded preview — even though Chrome/Edge sometimes play HEVC, we
    don't want to depend on it.
    """
    return probe.video_codec.lower() in BROWSER_FRIENDLY_CODECS


def _capture_run(cmd: List[str]) -> None:
    """Run a short ffmpeg command, surface stderr if it fails."""
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-1500:]}")


def make_preview(src: Path, dst: Path) -> None:
    """Generate a small MP4 preview the browser can play and seek.

    We optimise hard for *speed*, not quality — the user only needs to find
    trim points.  Settings:
      * 480p cap, 24 fps  (cuts the encode workload by ~4× vs 720p)
      * libx264 ultrafast / crf 32
      * no audio (the player is muted anyway)
      * +faststart so the moov atom is at the front for instant seeking
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-vf", "scale='min(854,iw)':-2,fps=24",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
        "-pix_fmt", "yuv420p",
        "-an",
        "-movflags", "+faststart",
        str(dst),
    ]
    _capture_run(cmd)


def concat_lossless(parts: List[Path], dst: Path) -> None:
    """Lossless concat of equally-encoded MP4 chunks via the concat demuxer.

    Raises with the captured stderr tail so we can actually diagnose failures
    (e.g. mismatched codec params between chunks → caller falls back to
    re-encoding).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    list_file = dst.with_suffix(".txt")
    with list_file.open("w", encoding="utf-8") as f:
        for p in parts:
            safe = str(p).replace("'", r"'\''")
            f.write(f"file '{safe}'\n")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(dst),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        list_file.unlink()
    except OSError:
        pass
    if proc.returncode != 0:
        raise RuntimeError(f"concat -c copy failed: {proc.stderr[-1500:]}")


def _run_with_progress(
    cmd: List[str],
    total_seconds: float,
    progress_cb: ProgressCb,
    stage: str,
    stage_start: float,
    stage_end: float,
) -> None:
    """Run ffmpeg, parse `-progress pipe:1`, map to [stage_start..stage_end].

    stderr is *also* streamed to the worker's stdout (without flooding it) so
    docker compose logs show ffmpeg progress lines in real time — invaluable
    when something hangs.
    """
    import sys
    import threading

    print(f"[ffmpeg] {shlex.join(cmd)}", flush=True)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stderr_buf: List[str] = []

    def pump_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_buf.append(line)
            # Cap retained tail so we don't balloon RAM on long renders.
            if len(stderr_buf) > 500:
                del stderr_buf[: len(stderr_buf) - 500]
            sys.stdout.write(f"[ffmpeg-stderr] {line}")
            sys.stdout.flush()

    t = threading.Thread(target=pump_stderr, daemon=True)
    t.start()

    last_us = 0
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                val = int(line.split("=", 1)[1])
            except ValueError:
                continue
            # ffmpeg historically used `out_time_ms` but actually emits µs.
            last_us = val
            if total_seconds > 0:
                frac = max(0.0, min(1.0, (last_us / 1_000_000.0) / total_seconds))
                mapped = stage_start + frac * (stage_end - stage_start)
                progress_cb(mapped, stage)
        elif line == "progress=end":
            progress_cb(stage_end, stage)
            break

    rc = proc.wait()
    t.join(timeout=2)
    if rc != 0:
        err = "".join(stderr_buf)[-2000:]
        raise RuntimeError(f"ffmpeg failed (rc={rc}): {err}\nCMD: {shlex.join(cmd)}")


def render_pip(
    *,
    hires: Path,
    dvr: Path,
    audio: Optional[Path],
    hires_trim: Tuple[float, Optional[float]],
    dvr_trim: Tuple[float, Optional[float]],
    audio_trim: Tuple[float, Optional[float]],
    pip_x_frac: float,
    pip_y_frac: float,
    pip_w_frac: float,
    output_width: int,
    output_height: int,
    codec: str,
    dst: Path,
    progress_cb: ProgressCb,
    stage_start: float = 0.0,
    stage_end: float = 1.0,
) -> None:
    """Run the main PiP composite render.

    Audio rules:
      - if `audio` is given: drop both video tracks' audio, mux the trimmed mp3
      - else: keep the hi-res original audio, drop the dvr audio
    """
    dst.parent.mkdir(parents=True, exist_ok=True)

    hs, he = hires_trim
    ds, de = dvr_trim
    as_, ae = audio_trim

    # Output duration determined by hi-res trim (DVR is overlaid only while
    # the hi-res plays; if the DVR is shorter the overlay just disappears).
    if he is not None:
        out_duration = max(0.001, he - hs)
    else:
        info = ffprobe(hires)
        out_duration = max(0.001, info.duration - hs)

    # Compute integer pixel offsets/sizes against the output canvas.
    pip_w = max(2, int(round(output_width * pip_w_frac)))
    if pip_w % 2:  # libx264 requires even dimensions when yuv420p
        pip_w -= 1
    pip_x = max(0, int(round(output_width * pip_x_frac)))
    pip_y = max(0, int(round(output_height * pip_y_frac)))
    if pip_x + pip_w > output_width:
        pip_x = max(0, output_width - pip_w)
    # height is preserved by aspect ratio in scale=-2

    # Build trim expressions.
    def trim_v(start: float, end: Optional[float]) -> str:
        if end is not None:
            return f"trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS"
        return f"trim=start={start:.3f},setpts=PTS-STARTPTS"

    def trim_a(start: float, end: Optional[float]) -> str:
        if end is not None:
            return f"atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS"
        return f"atrim=start={start:.3f},asetpts=PTS-STARTPTS"

    # Filter graph
    # [0:v]  hi-res  -> trim -> scale to output
    # [1:v]  dvr     -> trim -> scale to pip width
    # overlay -> [v]
    # audio handled separately (see below)
    filters: List[str] = []
    filters.append(
        f"[0:v]{trim_v(hs, he)},scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
        f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[base]"
    )
    filters.append(
        f"[1:v]{trim_v(ds, de)},scale={pip_w}:-2,setsar=1[pip]"
    )
    filters.append(
        f"[base][pip]overlay=x={pip_x}:y={pip_y}:eof_action=pass:shortest=0[v]"
    )

    inputs: List[str] = ["-i", str(hires), "-i", str(dvr)]
    audio_label: Optional[str] = None
    audio_input_index: Optional[int] = None

    if audio is not None:
        inputs += ["-i", str(audio)]
        audio_input_index = 2
        filters.append(f"[2:a]{trim_a(as_, ae)}[a]")
        audio_label = "[a]"
    else:
        info = ffprobe(hires)
        if info.has_audio:
            filters.append(f"[0:a]{trim_a(hs, he)}[a]")
            audio_label = "[a]"
        # else: silent output

    filter_complex = ";".join(filters)

    if codec == "h265":
        vcodec = ["-c:v", "libx265", "-preset", "medium", "-crf", "26", "-tag:v", "hvc1"]
    else:
        vcodec = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]

    cmd: List[str] = [
        "ffmpeg", "-y",
        "-progress", "pipe:1", "-nostats",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]",
    ]
    if audio_label is not None:
        cmd += ["-map", audio_label, "-c:a", "aac", "-b:a", "192k", "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd += [
        *vcodec,
        "-movflags", "+faststart",
        "-t", f"{out_duration:.3f}",
        str(dst),
    ]

    _run_with_progress(cmd, out_duration, progress_cb, "rendering", stage_start, stage_end)


def re_encode_normalize(
    src: Path,
    dst: Path,
    *,
    progress_cb: Optional[ProgressCb] = None,
    stage_label: str = "normalizing",
    stage_start: float = 0.0,
    stage_end: float = 1.0,
) -> None:
    """Re-encode a chunk to a known-uniform format so the concat demuxer can be
    used safely. Only used as a fallback when `concat -c copy` fails.

    Reports progress via the standard ffmpeg `-progress pipe:1` stream so the
    user gets feedback during what's otherwise a many-minute step.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    info = ffprobe(src)
    duration = max(0.001, info.duration or 0.001)
    cmd = [
        "ffmpeg", "-y",
        "-progress", "pipe:1", "-nostats",
        "-i", str(src),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ac", "2",
        "-movflags", "+faststart",
        str(dst),
    ]
    if progress_cb is None:
        progress_cb = lambda *_: None  # noqa: E731
    _run_with_progress(cmd, duration, progress_cb, stage_label, stage_start, stage_end)
