import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
UPLOADS_DIR = DATA_DIR / "uploads"
FILES_DIR = DATA_DIR / "files"
PREVIEWS_DIR = DATA_DIR / "previews"
OUTPUTS_DIR = DATA_DIR / "outputs"
WORK_DIR = DATA_DIR / "work"

for d in (UPLOADS_DIR, FILES_DIR, PREVIEWS_DIR, OUTPUTS_DIR, WORK_DIR):
    d.mkdir(parents=True, exist_ok=True)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(20 * 1024**3)))  # 20 GiB
