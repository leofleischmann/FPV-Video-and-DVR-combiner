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

from app.hw_cuda import use_cuda_decode_for_pip
from app.hw_encode import encoder_args_for_codec, get_h264_encoder

ProgressCb = Callable[[float, str], None]

# Input seek: skip decoding before trim start (large files). Trim filters then use t=0…relative.
_SEEK_EPS = 1e-3


def _ss_args(start: float) -> List[str]:
    if start > _SEEK_EPS:
        return ["-ss", f"{start:.6f}"]
    return []


def _trim_v_from_zero(end_rel: Optional[float]) -> str:
    if end_rel is not None:
        return f"trim=start=0:end={end_rel:.3f},setpts=PTS-STARTPTS"
    return "trim=start=0,setpts=PTS-STARTPTS"


def _trim_a_from_zero(end_rel: Optional[float]) -> str:
    if end_rel is not None:
        return f"atrim=start=0:end={end_rel:.3f},asetpts=PTS-STARTPTS"
    return f"atrim=start=0,asetpts=PTS-STARTPTS"


def _video_input(path: Path, ss: float, *, cuda: bool) -> List[str]:
    out: List[str] = []
    if cuda:
        out += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    out += _ss_args(ss)
    out += ["-i", str(path)]
    return out


def _audio_only_input(path: Path, ss: float) -> List[str]:
    return _ss_args(ss) + ["-i", str(path)]


def _dvr_privacy_drawfilters(
    masks: List[Tuple[float, float, float, float, str]],
) -> str:
    """drawbox chain on scaled DVR (coordinates as fractions of iw/ih). hex color #RRGGBB."""
    parts: List[str] = []
    for x, y, w, h, hex_col in masks:
        hc = hex_col.strip()
        if len(hc) == 7 and hc.startswith("#"):
            ffcol = f"0x{hc[1:]}FF"
        else:
            ffcol = "0x000000FF"
        parts.append(
            f"drawbox=x='iw*{x:.8f}':y='ih*{y:.8f}':w='iw*{w:.8f}':h='ih*{h:.8f}':color={ffcol}:t=fill"
        )
    return ",".join(parts)


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


def concat_lossless(
    parts: List[Path],
    dst: Path,
    *,
    faststart: bool = False,
    progress_cb: Optional[ProgressCb] = None,
    progress_stage: str = "preparing",
    stage_start: float = 0.0,
    stage_end: float = 1.0,
) -> None:
    """Lossless concat of equally-encoded MP4 chunks via the concat demuxer.

    Uses stream copy only (**no** decode/encode) — a GPU cannot accelerate this
    step meaningfully; time is dominated by disk I/O.

    **faststart**: When True, adds ``-movflags +faststart`` (good for files
    served over HTTP). For intermediate stitches fed back into FFmpeg, keep
    **False** — ``+faststart`` forces extra mux work and often makes large
    concatenations much slower with no benefit.

    Optional **progress_cb** runs ffmpeg with ``-progress pipe:1`` and maps
    output time to ``[stage_start, stage_end]`` (total duration = sum of part
    durations from ffprobe).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    list_file = dst.with_suffix(".txt")
    with list_file.open("w", encoding="utf-8") as f:
        for p in parts:
            safe = str(p).replace("'", r"'\''")
            f.write(f"file '{safe}'\n")

    total_seconds = 0.0
    for p in parts:
        try:
            total_seconds += max(0.001, ffprobe(p).duration or 0.0)
        except Exception:
            total_seconds += 60.0
    total_seconds = max(total_seconds, 0.1)

    tail_args: List[str] = ["-c", "copy"]
    if faststart:
        tail_args += ["-movflags", "+faststart"]
    tail_args.append(str(dst))

    try:
        if progress_cb is not None:
            cmd = [
                "ffmpeg",
                "-y",
                "-progress",
                "pipe:1",
                "-nostats",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                *tail_args,
            ]
            _run_with_progress(
                cmd,
                total_seconds,
                progress_cb,
                progress_stage,
                stage_start,
                stage_end,
            )
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                *tail_args,
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"concat -c copy failed: {proc.stderr[-1500:]}")
    finally:
        try:
            list_file.unlink(missing_ok=True)
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
    dvr_privacy_masks: Optional[List[Tuple[float, float, float, float, str]]] = None,
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
    hires_probe_for_audio: Optional[ProbeInfo] = None
    if he is not None:
        out_duration = max(0.001, he - hs)
    else:
        hires_probe_for_audio = ffprobe(hires)
        out_duration = max(0.001, hires_probe_for_audio.duration - hs)

    # Relative trim lengths after optional -ss on each input (fast seek on large files).
    hires_end = (he - hs) if he is not None else None
    dvr_end = (de - ds) if de is not None else None
    audio_end = (ae - as_) if audio is not None and ae is not None else None

    # Compute integer pixel offsets/sizes against the output canvas.
    pip_w = max(2, int(round(output_width * pip_w_frac)))
    if pip_w % 2:  # libx264 requires even dimensions when yuv420p
        pip_w -= 1
    pip_x = max(0, int(round(output_width * pip_x_frac)))
    pip_y = max(0, int(round(output_height * pip_y_frac)))
    if pip_x + pip_w > output_width:
        pip_x = max(0, output_width - pip_w)
    # height is preserved by aspect ratio in scale=-2

    enc_name, vcodec = encoder_args_for_codec(codec if codec in ("h264", "h265") else "h264")
    use_cuda_decode = use_cuda_decode_for_pip(enc_name)
    vf_pre = "hwdownload,format=yuv420p," if use_cuda_decode else ""

    # Filter graph
    # [0:v]  hi-res  -> trim -> scale to output
    # [1:v]  dvr     -> trim -> scale to pip width
    # overlay -> [v]
    # audio handled separately (see below)
    filters: List[str] = []
    filters.append(
        f"[0:v]{vf_pre}{_trim_v_from_zero(hires_end)},scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
        f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[base]"
    )
    dvr_v = f"{vf_pre}{_trim_v_from_zero(dvr_end)},scale={pip_w}:-2,setsar=1"
    if dvr_privacy_masks:
        dvr_v += "," + _dvr_privacy_drawfilters(dvr_privacy_masks)
    filters.append(f"[1:v]{dvr_v}[pip]")
    filters.append(
        f"[base][pip]overlay=x={pip_x}:y={pip_y}:eof_action=pass:shortest=0[v]"
    )

    inputs: List[str] = []
    inputs += _video_input(hires, hs, cuda=use_cuda_decode)
    inputs += _video_input(dvr, ds, cuda=use_cuda_decode)

    audio_label: Optional[str] = None

    if audio is not None:
        inputs += _audio_only_input(audio, as_)
        filters.append(f"[2:a]{_trim_a_from_zero(audio_end)}[a]")
        audio_label = "[a]"
    else:
        info = hires_probe_for_audio or ffprobe(hires)
        if info.has_audio:
            hires_audio_end = (he - hs) if he is not None else None
            filters.append(f"[0:a]{_trim_a_from_zero(hires_audio_end)}[a]")
            audio_label = "[a]"
        # else: silent output

    filter_complex = ";".join(filters)

    extra_head: List[str] = []
    if use_cuda_decode:
        # Fewer edge-case failures when feeding CUDA surfaces into hwdownload + filters.
        extra_head = ["-extra_hw_frames", "64"]

    print(
        f"[render_pip] encoder={enc_name} codec_choice={codec} cuda_decode={use_cuda_decode} "
        f"seek_hi={hs:g} seek_dvr={ds:g} seek_au={as_ if audio else 0:g} "
        f"dvr_privacy_masks={len(dvr_privacy_masks or [])}",
        flush=True,
    )

    cmd: List[str] = [
        "ffmpeg", "-y",
        "-progress", "pipe:1", "-nostats",
        *extra_head,
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
    _, venc = get_h264_encoder()
    cmd = [
        "ffmpeg", "-y",
        "-progress", "pipe:1", "-nostats",
        "-i", str(src),
        *venc,
        "-c:a", "aac", "-b:a", "192k", "-ac", "2",
        "-movflags", "+faststart",
        str(dst),
    ]
    if progress_cb is None:
        progress_cb = lambda *_: None  # noqa: E731
    _run_with_progress(cmd, duration, progress_cb, stage_label, stage_start, stage_end)
