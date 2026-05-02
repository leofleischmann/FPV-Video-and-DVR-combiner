from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class FileInfo(BaseModel):
    file_id: str
    filename: str
    size: int
    kind: Literal["hires", "dvr", "audio"]
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    has_audio: bool = False
    video_codec: str = ""
    # Browser can decode the raw file directly (no preview transcode needed).
    browser_playable: bool = False
    preview_ready: bool = False


class InitUploadRequest(BaseModel):
    filename: str
    size: int
    kind: Literal["hires", "dvr", "audio"]


class InitUploadResponse(BaseModel):
    upload_id: str
    received: int


class CompleteUploadResponse(BaseModel):
    file: FileInfo


class TrimSpec(BaseModel):
    start: float = Field(0.0, ge=0)
    end: Optional[float] = Field(None, gt=0)


class PipSpec(BaseModel):
    # All values are fractions (0..1) of the OUTPUT canvas, so they survive
    # any final scaling decision the user makes.
    x: float = Field(0.02, ge=0, le=1)
    y: float = Field(0.02, ge=0, le=1)
    width: float = Field(0.30, gt=0, le=1)


class RenderJobRequest(BaseModel):
    hires_file_ids: List[str] = Field(..., min_length=1)
    dvr_file_id: str
    audio_file_id: Optional[str] = None
    hires_trim: TrimSpec = TrimSpec()
    dvr_trim: TrimSpec = TrimSpec()
    audio_trim: TrimSpec = TrimSpec()
    pip: PipSpec = PipSpec()
    output_width: int = Field(..., gt=0)
    output_height: int = Field(..., gt=0)
    codec: Literal["h264", "h265"] = "h264"


class ConcatPreviewRequest(BaseModel):
    hires_file_ids: List[str] = Field(..., min_length=1)


class ConcatPreviewStatus(BaseModel):
    hash: str
    status: Literal["ready", "pending", "failed", "missing"]
    duration: Optional[float] = None
    error: Optional[str] = None


class JobStatus(BaseModel):
    job_id: str
    state: str  # PENDING, STARTED, PROGRESS, SUCCESS, FAILURE
    progress: float = 0.0  # 0..1
    stage: str = ""
    message: str = ""
    error: Optional[str] = None
    output_filename: Optional[str] = None
