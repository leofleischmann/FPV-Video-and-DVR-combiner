"""FastAPI app: chunked uploads, job submission, status polling, downloads.

Chunked-upload protocol (HTTP, resumable):
  1. POST /api/uploads/init  -> { upload_id, received: 0 }
  2. (repeat) PUT /api/uploads/{upload_id}?offset=N  body=raw bytes
     -> { received: <new total> }
     The client may also call GET /api/uploads/{upload_id} to learn how many
     bytes were already received and resume from there after a network drop.
  3. POST /api/uploads/{upload_id}/complete -> FileInfo

The on-disk layout under DATA_DIR:
  uploads/<upload_id>.part   incomplete chunked uploads
  uploads/<upload_id>.json   metadata (filename, size, kind)
  files/<file_id>            committed media files (renamed from .part)
  previews/<file_id>.mp4     low-res H.264 preview for in-browser scrubbing
  outputs/<job_id>.mp4       final renders
"""
from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from pathlib import Path
from typing import Optional

import aiofiles
from celery.result import AsyncResult
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from app.celery_app import celery_app
from app.config import (
    FILES_DIR,
    MAX_UPLOAD_BYTES,
    OUTPUTS_DIR,
    PREVIEWS_DIR,
    UPLOADS_DIR,
    WORK_DIR,
)
from app import ffmpeg_utils as ff
from app.models import (
    CompleteUploadResponse,
    ConcatPreviewRequest,
    ConcatPreviewStatus,
    FileInfo,
    InitUploadRequest,
    InitUploadResponse,
    JobStatus,
    RenderJobRequest,
)
from app import tasks as celery_tasks  # noqa: F401  (registers tasks on app load)


app = FastAPI(title="FPV Video-Merger & PiP-Generator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges"],
)


def _new_id() -> str:
    return secrets.token_hex(16)


def _meta_path(upload_id: str) -> Path:
    return UPLOADS_DIR / f"{upload_id}.json"


def _part_path(upload_id: str) -> Path:
    return UPLOADS_DIR / f"{upload_id}.part"


def _read_meta(upload_id: str) -> dict:
    p = _meta_path(upload_id)
    if not p.exists():
        raise HTTPException(404, "upload not found")
    return json.loads(p.read_text())


def _write_meta(upload_id: str, meta: dict) -> None:
    _meta_path(upload_id).write_text(json.dumps(meta))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/api/encoding")
async def encoding_status() -> dict:
    """Which FFmpeg encoders this API process selected (mirrors worker if same GPU setup)."""
    from app.hw_encode import encoding_public_info

    return encoding_public_info()


@app.post("/api/reset-workspace")
async def reset_workspace() -> dict:
    """Delete all uploads, committed files, previews, rendered outputs, and temp work dirs."""
    for d in (UPLOADS_DIR, FILES_DIR, PREVIEWS_DIR, OUTPUTS_DIR, WORK_DIR):
        if d.is_dir():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    # Redis persists the Celery broker queue — drop stale tasks that reference deleted files.
    purged = None
    try:
        purged = celery_app.control.purge()
    except Exception:
        pass
    return {"ok": True, "purged_tasks": purged}


# ---------------------------------------------------------------------------
# Chunked upload
# ---------------------------------------------------------------------------
@app.post("/api/uploads/init", response_model=InitUploadResponse)
async def init_upload(req: InitUploadRequest) -> InitUploadResponse:
    if req.size <= 0 or req.size > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"invalid size (max {MAX_UPLOAD_BYTES})")
    if req.kind not in ("hires", "dvr", "audio"):
        raise HTTPException(400, "invalid kind")
    upload_id = _new_id()
    meta = {
        "upload_id": upload_id,
        "filename": req.filename,
        "size": req.size,
        "kind": req.kind,
        "received": 0,
    }
    _part_path(upload_id).touch()
    _write_meta(upload_id, meta)
    return InitUploadResponse(upload_id=upload_id, received=0)


@app.get("/api/uploads/{upload_id}")
async def get_upload(upload_id: str) -> dict:
    meta = _read_meta(upload_id)
    return {"upload_id": upload_id, "received": meta["received"], "size": meta["size"]}


@app.put("/api/uploads/{upload_id}")
async def put_chunk(
    upload_id: str,
    request: Request,
    offset: int = Query(..., ge=0),
) -> dict:
    meta = _read_meta(upload_id)
    if offset > meta["received"]:
        raise HTTPException(409, f"out of order chunk: have {meta['received']}, got offset {offset}")
    part = _part_path(upload_id)

    # Seek to `offset` (which equals meta["received"] for normal sequential
    # uploads; smaller if the client is resending after retry).
    written = 0
    async with aiofiles.open(part, "r+b") as f:
        await f.seek(offset)
        async for chunk in request.stream():
            if not chunk:
                continue
            if offset + written + len(chunk) > meta["size"]:
                raise HTTPException(400, "chunk exceeds declared size")
            await f.write(chunk)
            written += len(chunk)

    new_received = max(meta["received"], offset + written)
    if new_received > meta["size"]:
        raise HTTPException(400, "exceeds declared size")
    meta["received"] = new_received
    _write_meta(upload_id, meta)
    return {"received": new_received}


@app.post("/api/uploads/{upload_id}/complete", response_model=CompleteUploadResponse)
async def complete_upload(upload_id: str) -> CompleteUploadResponse:
    meta = _read_meta(upload_id)
    if meta["received"] != meta["size"]:
        raise HTTPException(
            400,
            f"upload incomplete: {meta['received']}/{meta['size']} bytes",
        )

    file_id = _new_id()
    src = _part_path(upload_id)
    dst = FILES_DIR / file_id
    shutil.move(str(src), str(dst))
    _meta_path(upload_id).unlink(missing_ok=True)

    info = ff.ffprobe(dst)
    browser_playable = ff.is_browser_playable(info) if meta["kind"] in ("hires", "dvr") else False
    file_info = FileInfo(
        file_id=file_id,
        filename=meta["filename"],
        size=meta["size"],
        kind=meta["kind"],
        width=info.width or None,
        height=info.height or None,
        duration=info.duration or None,
        has_audio=info.has_audio,
        video_codec=info.video_codec,
        browser_playable=browser_playable,
        preview_ready=False,
    )
    _persist_file_info(file_info)

    # Only transcode a preview if the browser can't play the raw file.
    # H.264 sources (typical DJI drone .mp4) skip the worker entirely, which
    # gets the user past the upload step in seconds instead of minutes.
    if meta["kind"] in ("hires", "dvr") and not browser_playable:
        celery_app.send_task("generate_preview", args=[file_id])

    return CompleteUploadResponse(file=file_info)


@app.delete("/api/uploads/{upload_id}")
async def cancel_upload(upload_id: str) -> dict:
    _meta_path(upload_id).unlink(missing_ok=True)
    _part_path(upload_id).unlink(missing_ok=True)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Files: info, preview streaming
# ---------------------------------------------------------------------------
def _info_path(file_id: str) -> Path:
    return FILES_DIR / f"{file_id}.json"


def _persist_file_info(info: FileInfo) -> None:
    _info_path(info.file_id).write_text(info.model_dump_json())


def _load_file_info(file_id: str) -> FileInfo:
    p = _info_path(file_id)
    if not p.exists():
        raise HTTPException(404, "file not found")
    info = FileInfo.model_validate_json(p.read_text())
    info.preview_ready = (PREVIEWS_DIR / f"{file_id}.mp4").exists()
    return info


@app.get("/api/files/{file_id}", response_model=FileInfo)
async def get_file(file_id: str) -> FileInfo:
    return _load_file_info(file_id)


@app.delete("/api/files/{file_id}")
async def delete_file(file_id: str) -> dict:
    for p in (FILES_DIR / file_id, _info_path(file_id), PREVIEWS_DIR / f"{file_id}.mp4"):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    return {"ok": True}


def _range_response(path: Path, request: Request, media_type: str) -> Response:
    """Serve a file with HTTP Range support so browsers can seek inside videos."""
    file_size = path.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")

    if range_header is None:
        # Advertise byte-range support so browsers know seeking is possible.
        return FileResponse(
            path,
            media_type=media_type,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)},
        )

    # bytes=START-END
    try:
        units, rng = range_header.split("=", 1)
        if units.strip().lower() != "bytes":
            raise ValueError
        start_s, end_s = rng.split("-", 1)
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
    except ValueError:
        raise HTTPException(400, "invalid Range header")

    if start >= file_size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
    end = min(end, file_size - 1)
    length = end - start + 1

    async def streamer():
        async with aiofiles.open(path, "rb") as f:
            await f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = await f.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
    }
    return StreamingResponse(streamer(), status_code=206, media_type=media_type, headers=headers)


@app.get("/api/files/{file_id}/preview")
async def file_preview(file_id: str, request: Request) -> Response:
    p = PREVIEWS_DIR / f"{file_id}.mp4"
    if not p.exists():
        raise HTTPException(404, "preview not ready")
    return _range_response(p, request, "video/mp4")


@app.get("/api/files/{file_id}/raw")
async def file_raw(file_id: str, request: Request) -> Response:
    p = FILES_DIR / file_id
    if not p.exists():
        raise HTTPException(404, "file not found")
    info = _load_file_info(file_id)
    media = "video/mp4" if info.filename.lower().endswith(".mp4") else (
        "video/quicktime" if info.filename.lower().endswith(".mov") else
        "audio/mpeg" if info.filename.lower().endswith(".mp3") else "application/octet-stream"
    )
    return _range_response(p, request, media)


# ---------------------------------------------------------------------------
# Concat preview (full-length browser preview spanning multiple hi-res chunks)
# ---------------------------------------------------------------------------
def _concat_hash(ids) -> str:
    return hashlib.sha1("|".join(ids).encode()).hexdigest()[:16]


@app.post("/api/concat-preview", response_model=ConcatPreviewStatus)
async def start_concat_preview(req: ConcatPreviewRequest) -> ConcatPreviewStatus:
    h = _concat_hash(req.hires_file_ids)
    out = PREVIEWS_DIR / f"concat_{h}.mp4"
    status_file = PREVIEWS_DIR / f"concat_{h}.json"

    if out.exists() and not status_file.exists():
        return ConcatPreviewStatus(hash=h, status="ready")

    if status_file.exists():
        try:
            data = json.loads(status_file.read_text())
            return ConcatPreviewStatus(
                hash=h,
                status=data.get("status", "pending"),
                error=data.get("error"),
            )
        except (json.JSONDecodeError, OSError):
            pass

    for fid in req.hires_file_ids:
        if not (FILES_DIR / fid).exists():
            raise HTTPException(400, f"missing source: {fid}")

    status_file.write_text(json.dumps({"status": "pending"}))
    celery_app.send_task("generate_concat_preview", args=[h, req.hires_file_ids])
    return ConcatPreviewStatus(hash=h, status="pending")


@app.get("/api/concat-preview/{h}/status", response_model=ConcatPreviewStatus)
async def concat_preview_status(h: str) -> ConcatPreviewStatus:
    out = PREVIEWS_DIR / f"concat_{h}.mp4"
    status_file = PREVIEWS_DIR / f"concat_{h}.json"
    if out.exists() and not status_file.exists():
        return ConcatPreviewStatus(hash=h, status="ready")
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text())
            return ConcatPreviewStatus(
                hash=h, status=data.get("status", "pending"), error=data.get("error")
            )
        except (json.JSONDecodeError, OSError):
            pass
    return ConcatPreviewStatus(hash=h, status="missing")


@app.get("/api/concat-preview/{h}")
async def serve_concat_preview(h: str, request: Request) -> Response:
    p = PREVIEWS_DIR / f"concat_{h}.mp4"
    if not p.exists():
        raise HTTPException(404, "preview not ready")
    return _range_response(p, request, "video/mp4")


# ---------------------------------------------------------------------------
# Render jobs
# ---------------------------------------------------------------------------
@app.post("/api/jobs", response_model=JobStatus)
async def create_job(req: RenderJobRequest) -> JobStatus:
    # Sanity: required files must exist.
    for fid in req.hires_file_ids:
        if not (FILES_DIR / fid).exists():
            raise HTTPException(400, f"hi-res file missing: {fid}")
    if not (FILES_DIR / req.dvr_file_id).exists():
        raise HTTPException(400, "dvr file missing")
    if req.audio_file_id and not (FILES_DIR / req.audio_file_id).exists():
        raise HTTPException(400, "audio file missing")

    # Make output dimensions even (libx264 requires it).
    ow = req.output_width if req.output_width % 2 == 0 else req.output_width - 1
    oh = req.output_height if req.output_height % 2 == 0 else req.output_height - 1

    async_result = celery_app.send_task(
        "render_pip_job",
        kwargs={
            "hires_file_ids": req.hires_file_ids,
            "dvr_file_id": req.dvr_file_id,
            "audio_file_id": req.audio_file_id,
            "hires_trim": req.hires_trim.model_dump(),
            "dvr_trim": req.dvr_trim.model_dump(),
            "audio_trim": req.audio_trim.model_dump(),
            "pip": req.pip.model_dump(),
            "dvr_privacy_masks": [m.model_dump() for m in req.dvr_privacy_masks],
            "output_width": ow,
            "output_height": oh,
            "codec": req.codec,
        },
    )
    return JobStatus(job_id=async_result.id, state="PENDING", progress=0.0)


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str) -> JobStatus:
    res: AsyncResult = AsyncResult(job_id, app=celery_app)
    state = res.state
    progress = 0.0
    stage = ""
    message = ""
    error: Optional[str] = None
    output_filename: Optional[str] = None

    if state == "PROGRESS" and isinstance(res.info, dict):
        progress = float(res.info.get("progress", 0.0))
        stage = str(res.info.get("stage", ""))
        message = str(res.info.get("message", ""))
    elif state == "SUCCESS":
        result = res.result if isinstance(res.result, dict) else {}
        if result.get("ok"):
            progress = 1.0
            stage = "done"
            output_filename = result.get("output_filename")
        else:
            state = "FAILURE"
            error = str(result.get("error", "unknown error"))
    elif state == "FAILURE":
        error = str(res.info) if res.info else "task failed"
    elif state == "STARTED":
        progress = 0.01
        stage = "starting"

    return JobStatus(
        job_id=job_id,
        state=state,
        progress=progress,
        stage=stage,
        message=message,
        error=error,
        output_filename=output_filename,
    )


@app.get("/api/jobs/{job_id}/preview")
async def preview_job(job_id: str, request: Request) -> Response:
    """Inline-stream the rendered MP4 for in-browser <video> playback,
    with HTTP Range support for seeking."""
    out = OUTPUTS_DIR / f"{job_id}.mp4"
    if not out.exists():
        raise HTTPException(404, "output not ready")
    return _range_response(out, request, "video/mp4")


@app.get("/api/jobs/{job_id}/download")
async def download_job(job_id: str):
    out = OUTPUTS_DIR / f"{job_id}.mp4"
    if not out.exists():
        raise HTTPException(404, "output not ready")
    return FileResponse(
        out,
        media_type="video/mp4",
        filename=f"fpv_pip_{job_id[:8]}.mp4",
    )


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str) -> dict:
    out = OUTPUTS_DIR / f"{job_id}.mp4"
    out.unlink(missing_ok=True)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
