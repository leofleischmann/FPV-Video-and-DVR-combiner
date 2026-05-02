"""Celery tasks: preview generation and the main PiP render pipeline."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from app.celery_app import celery_app
from app.config import FILES_DIR, OUTPUTS_DIR, PREVIEWS_DIR, WORK_DIR
from app import ffmpeg_utils as ff


@celery_app.task(bind=True, name="generate_preview")
def generate_preview(self, file_id: str) -> dict:
    src = FILES_DIR / file_id
    dst = PREVIEWS_DIR / f"{file_id}.mp4"
    if not src.exists():
        return {"ok": False, "error": "source missing"}
    if dst.exists():
        return {"ok": True, "cached": True}
    try:
        ff.make_preview(src, dst)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True}


@celery_app.task(bind=True, name="generate_concat_preview")
def generate_concat_preview(self, h: str, file_ids: List[str]) -> dict:
    """Single-pass concat + 480p transcode covering ALL hi-res chunks.

    Output is a small browser-friendly MP4 the frontend uses for the
    full-length preview in the trim and PiP-editor steps. Cached by hash.
    """
    out = PREVIEWS_DIR / f"concat_{h}.mp4"
    status_file = PREVIEWS_DIR / f"concat_{h}.json"

    def write_status(status: str, error: Optional[str] = None) -> None:
        try:
            payload = {"status": status}
            if error:
                payload["error"] = error[:500]
            status_file.write_text(json.dumps(payload))
        except OSError:
            pass

    paths = [FILES_DIR / fid for fid in file_ids]
    for p in paths:
        if not p.exists():
            write_status("failed", f"missing source: {p.name}")
            return {"ok": False, "error": "missing"}

    list_file = PREVIEWS_DIR / f"concat_{h}.txt"
    with list_file.open("w", encoding="utf-8") as f:
        for p in paths:
            safe = str(p).replace("'", r"'\''")
            f.write(f"file '{safe}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-vf", "scale='min(854,iw)':-2,fps=24",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
        "-pix_fmt", "yuv420p",
        "-an",
        "-movflags", "+faststart",
        str(out),
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            write_status("failed", proc.stderr[-1500:])
            try: out.unlink(missing_ok=True)
            except OSError: pass
            return {"ok": False, "error": proc.stderr[-1500:]}
    finally:
        try: list_file.unlink()
        except OSError: pass

    # Mark ready by removing the status file (presence of out + absence of
    # status file means "ready"; status file present means in-progress/failed).
    try: status_file.unlink(missing_ok=True)
    except OSError: pass
    return {"ok": True}


@celery_app.task(bind=True, name="render_pip_job")
def render_pip_job(  # noqa: PLR0913
    self,
    *,
    hires_file_ids: List[str],
    dvr_file_id: str,
    audio_file_id: Optional[str],
    hires_trim: dict,
    dvr_trim: dict,
    audio_trim: dict,
    pip: dict,
    output_width: int,
    output_height: int,
    codec: str,
) -> dict:
    job_id = self.request.id
    work = WORK_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)

    def report(progress: float, stage: str, message: str = "") -> None:
        self.update_state(
            state="PROGRESS",
            meta={
                "progress": float(max(0.0, min(1.0, progress))),
                "stage": stage,
                "message": message,
            },
        )

    try:
        # 1. Concatenate hi-res chunks if needed (lossless when possible).
        report(0.0, "preparing", "Vorbereiten der Hi-Res-Datei")
        hires_paths = [FILES_DIR / fid for fid in hires_file_ids]
        for p in hires_paths:
            if not p.exists():
                raise FileNotFoundError(f"hi-res chunk missing: {p.name}")

        if len(hires_paths) == 1:
            hires_master = hires_paths[0]
        else:
            hires_master = work / "hires_master.mp4"
            try:
                report(0.005, "preparing", f"Verlustfreier Concat von {len(hires_paths)} Chunks")
                ff.concat_lossless(hires_paths, hires_master)
                report(0.04, "preparing", "Concat fertig")
            except Exception as concat_err:
                # Fallback: re-encode each part to a uniform format, then concat.
                # This is the slow path — give the user visible progress.
                msg = str(concat_err)[:200]
                report(0.005, "preparing", f"Lossless concat fehlgeschlagen ({msg}), normalisiere Chunks…")
                normalized: List[Path] = []
                # Reserve [0.005..0.04] of the total job for normalize+concat.
                slice_size = (0.04 - 0.005) / max(1, len(hires_paths))
                for i, p in enumerate(hires_paths):
                    n = work / f"norm_{i:03d}.mp4"
                    s0 = 0.005 + i * slice_size
                    s1 = 0.005 + (i + 1) * slice_size

                    def cb(p_, _stage, i_=i, n_=len(hires_paths)):
                        report(p_, "preparing", f"Normalisiere Chunk {i_ + 1}/{n_}")

                    ff.re_encode_normalize(
                        p, n,
                        progress_cb=cb,
                        stage_label="preparing",
                        stage_start=s0, stage_end=s1,
                    )
                    normalized.append(n)
                report(0.04, "preparing", "Concat normalisierter Chunks")
                ff.concat_lossless(normalized, hires_master)

        report(0.05, "preparing", "Hi-Res bereit, starte Render")

        dvr_path = FILES_DIR / dvr_file_id
        if not dvr_path.exists():
            raise FileNotFoundError("dvr file missing")
        audio_path: Optional[Path] = None
        if audio_file_id:
            audio_path = FILES_DIR / audio_file_id
            if not audio_path.exists():
                raise FileNotFoundError("audio file missing")

        # 2. Render PiP.
        out_path = OUTPUTS_DIR / f"{job_id}.mp4"

        def cb(p: float, stage: str) -> None:
            report(p, stage)

        ff.render_pip(
            hires=hires_master,
            dvr=dvr_path,
            audio=audio_path,
            hires_trim=(float(hires_trim.get("start", 0.0)), hires_trim.get("end")),
            dvr_trim=(float(dvr_trim.get("start", 0.0)), dvr_trim.get("end")),
            audio_trim=(float(audio_trim.get("start", 0.0)), audio_trim.get("end")),
            pip_x_frac=float(pip.get("x", 0.02)),
            pip_y_frac=float(pip.get("y", 0.02)),
            pip_w_frac=float(pip.get("width", 0.30)),
            output_width=int(output_width),
            output_height=int(output_height),
            codec=codec,
            dst=out_path,
            progress_cb=cb,
            stage_start=0.05,
            stage_end=0.99,
        )

        report(1.0, "done", "Fertig")
        return {
            "ok": True,
            "output_filename": out_path.name,
        }

    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    finally:
        # Clean intermediate work files.  Keep the output (lives in OUTPUTS_DIR).
        try:
            shutil.rmtree(work, ignore_errors=True)
        except OSError:
            pass
