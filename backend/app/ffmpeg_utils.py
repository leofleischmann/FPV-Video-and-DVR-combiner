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
from typing import Callable, List, Optional, Tuple


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


def make_preview(src: Path, dst: Path) -> None:
    """Generate a small H.264 MP4 preview that any browser can play.

    Used so that the user can scrub uploaded `.mov` / large `.mp4` files in the
    browser.  Faststart so it streams.  720p cap, 24 fps, AAC if audio exists.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-vf", "scale='min(1280,iw)':-2,fps=24",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-ac", "2",
        "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def concat_lossless(parts: List[Path], dst: Path) -> None:
    """Lossless concat of equally-encoded MP4 chunks via the concat demuxer."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    list_file = dst.with_suffix(".txt")
    with list_file.open("w", encoding="utf-8") as f:
        for p in parts:
            # Concat demuxer requires escaping single quotes.
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
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        list_file.unlink()
    except OSError:
        pass


def _run_with_progress(
    cmd: List[str],
    total_seconds: float,
    progress_cb: ProgressCb,
    stage: str,
    stage_start: float,
    stage_end: float,
) -> None:
    """Run ffmpeg, parse `-progress pipe:1`, map to [stage_start..stage_end]."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
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
            # ffmpeg has historically used out_time_ms but actually emitted µs.
            last_us = val
            if total_seconds > 0:
                frac = max(0.0, min(1.0, (last_us / 1_000_000.0) / total_seconds))
                mapped = stage_start + frac * (stage_end - stage_start)
                progress_cb(mapped, stage)
        elif line == "progress=end":
            progress_cb(stage_end, stage)
            break
    rc = proc.wait()
    if rc != 0:
        err = ""
        if proc.stderr is not None:
            err = proc.stderr.read() or ""
        raise RuntimeError(f"ffmpeg failed (rc={rc}): {err[-2000:]}\nCMD: {shlex.join(cmd)}")


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


def re_encode_normalize(src: Path, dst: Path) -> None:
    """Re-encode a single hi-res chunk to a known-uniform format so that the
    concat demuxer can be used safely.  Only used as a fallback if `concat -c copy`
    fails (e.g. mismatching codec params between chunks).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ac", "2",
        "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
