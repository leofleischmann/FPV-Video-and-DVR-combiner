# FPV Video-Merger & PiP-Generator

Lokale, Docker-basierte Web-App, die hochauflösende Drohnen-Aufnahmen (Hi-Res, MP4) mit
einem DVR-Feed (Brillen-Aufnahme, MOV) als Picture-in-Picture kombiniert und optional
mit einer eigenen Audiospur (MP3) hinterlegt.

---

## Features

- **Resumable Chunked Uploads** über HTTP (8 MiB pro Chunk + Retry/Resume) —
  Videos > 4 GB sind kein Problem.
- **Verlustfreie Concat** mehrerer Hi-Res-Chunks via FFmpeg Concat-Demuxer
  (`-c copy`), mit automatischem Fallback (Re-Encode auf einheitliches Format),
  falls die Chunks abweichende Codec-Parameter haben.
- **Trim & Sync**: unabhängiges Zuschneiden von Hi-Res, DVR und MP3 über
  Dual-Range-Slider mit Live-Vorschau.
- **PiP-Editor** im Browser: DVR-Overlay live per Drag & Drop positionieren und
  per Eck-Handle skalieren. Position/Größe werden als Bruchteile (0–1) der
  Output-Canvas gespeichert und sind damit unabhängig von späteren Auflösungs-
  Änderungen.
- **Audio-Regeln** (laut Spec):
  - MP3 hochgeladen → Original-Tonspuren beider Videos werden verworfen,
    nur die geschnittene MP3 wird gemuxt.
  - Keine MP3 → Hi-Res-Ton bleibt erhalten, DVR-Ton wird verworfen.
- **Browser-Preview**: Worker erzeugt nach jedem Upload eine 720p H.264-MP4-Preview
  mit `+faststart`, damit MOV/HEVC-Quellen browserweit scrubbar sind.
- **Render-Einstellungen**: Auflösungs-Presets (4K / 1440p / 1080p / 720p / Auto /
  Custom), Codec-Wahl H.264 (libx264) oder H.265 (libx265, `hvc1`-Tag).
  Default-Auflösung wird aus den Hi-Res-Metadaten gelesen.
- **Asynchroner Render** über Celery + Redis. Fortschritt wird aus FFmpegs
  `-progress pipe:1` geparst und vom Frontend per Polling (1 s) angezeigt.
- **Range-Requests** vom Backend unterstützt → Browser kann in Vorschauen seeken.

---

## Tech-Stack

| Schicht         | Technologie                                |
|-----------------|--------------------------------------------|
| Backend         | FastAPI (Python 3.12)                      |
| Worker          | Celery 5.4                                 |
| Broker / Result | Redis 7                                    |
| Video-Pipeline  | FFmpeg (subprocess, mit Progress-Parser)   |
| Frontend        | Vue 3 + Vite                               |
| Reverse Proxy   | nginx (statisches Frontend + `/api`-Proxy) |
| Deployment      | Docker Compose                             |

---

## Architektur

```
┌──────────┐   chunked PUT    ┌──────────┐   send_task   ┌────────┐
│ Frontend │ ───────────────► │  Backend │ ────────────► │  Redis │
│ (nginx)  │ ◄─── poll ─────  │ (FastAPI)│ ◄──── state ─ │ (broker│
└──────────┘                  └────┬─────┘               │+result)│
                                   │                     └────┬───┘
                                   │ shares /data            │
                                   ▼                         ▼
                              ┌─────────────────────────────────┐
                              │      Celery Worker (FFmpeg)     │
                              └─────────────────────────────────┘
```

Alle Container teilen das Volume `./data`:

```
data/
├── uploads/    # in-flight Chunked-Uploads (.part + .json)
├── files/      # committed Quelldateien
├── previews/   # 720p H.264-Previews fürs Browser-Scrubbing
├── outputs/    # finale Renders
└── work/       # temporäre Render-Artefakte (werden bereinigt)
```

---

## Quickstart

Voraussetzung: **Docker Desktop** (Windows/macOS) bzw. Docker + Docker Compose
Plugin (Linux).

```bash
docker compose up --build
```

Anschließend öffnen:

- **Frontend**: <http://localhost:8080>
- **Backend / API-Docs**: <http://localhost:8000/docs>

Stoppen:

```bash
docker compose down
```

Vollständig zurücksetzen (inkl. Uploads/Renders):

```bash
docker compose down -v
rm -rf data/
```

---

## Workflow im UI

1. **Upload**
   - Hi-Res-Chunks (.mp4, mehrere) hochladen — Reihenfolge ist per Pfeil-Buttons
     anpassbar.
   - DVR-Datei (.mov) hochladen.
   - Optional: MP3 hochladen.
2. **Trim & Sync**
   - Hi-Res-, DVR- und MP3-Trim über die Dual-Range-Slider setzen.
   - Hi-Res definiert die finale Render-Zeitachse; DVR-Trim wird ab `t=0` als
     Overlay synchronisiert. Tipp: DVR-Startzeit so wählen, dass sie zum
     Hi-Res-Frame passt.
3. **PiP & Settings**
   - Auflösung wählen (Default: Original der ersten Hi-Res-Datei).
   - Codec wählen.
   - Overlay im Vorschaubild ziehen / per Eck-Handle skalieren oder per Slider
     justieren.
4. **Render**
   - „Rendern starten" klicken → Fortschrittsbalken. Nach Fertigstellung
     erscheint der Download-Button.

---

## Chunked-Upload-Protokoll

Implementiert auf reinem HTTP — keine externen Libraries nötig.

```text
POST   /api/uploads/init                  { filename, size, kind } -> { upload_id, received }
PUT    /api/uploads/{upload_id}?offset=N  raw bytes               -> { received }
GET    /api/uploads/{upload_id}                                   -> { received, size }   # Resume
POST   /api/uploads/{upload_id}/complete                          -> FileInfo
DELETE /api/uploads/{upload_id}                                   -> {}                   # Cancel
```

Bei Netzwerk-Abbruch fragt der Client per `GET` ab, wie viele Bytes der Server
schon hat, und fährt ab dieser Position fort. Pro Chunk werden bis zu fünf
Retries durchgeführt.

---

## Render-Pipeline (Backend / Celery)

1. **Concat**: Wenn mehr als ein Hi-Res-Chunk → FFmpeg Concat-Demuxer (`-c copy`).
   Bei Codec-Mismatches automatisches Re-Encoding auf einheitliches Profil und
   erneuter Concat.
2. **Filtergraph** (vereinfacht):

```text
[0:v]trim=start=Hs:end=He,setpts=PTS-STARTPTS,
     scale=W:H:force_original_aspect_ratio=decrease,
     pad=W:H:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1   [base]
[1:v]trim=start=Ds:end=De,setpts=PTS-STARTPTS,
     scale=PIPw:-2,setsar=1                              [pip]
[base][pip]overlay=x=Px:y=Py:eof_action=pass:shortest=0  [v]
[2:a]atrim=start=As:end=Ae,asetpts=PTS-STARTPTS          [a]   # nur falls MP3
```

3. **Encode**:
   - H.264: `libx264 -preset medium -crf 20 -pix_fmt yuv420p`
   - H.265: `libx265 -preset medium -crf 26 -tag:v hvc1`
   - Audio (falls vorhanden): `aac -b:a 192k -ac 2`
   - `-movflags +faststart` für Web-Playback

4. **Progress**: `-progress pipe:1 -nostats` wird live geparst und als
   `task.update_state(state="PROGRESS", meta={progress, stage, message})` an
   Redis gemeldet.

---

## Konfiguration

Alle relevanten Settings sind in `docker-compose.yml` als Environment-Variablen
gesetzt:

| Variable          | Default            | Bedeutung                                  |
|-------------------|--------------------|--------------------------------------------|
| `REDIS_URL`       | `redis://redis:6379/0` | Celery Broker + Result-Backend         |
| `DATA_DIR`        | `/data`            | Wurzel für Uploads/Files/Outputs           |
| `MAX_UPLOAD_BYTES`| `21474836480` (20 GiB) | Hard limit pro Datei (init-Check)      |

nginx im Frontend-Container ist auf `client_max_body_size 1024m` gesetzt und
streamt Uploads ungebuffert ans Backend.

---

## Wichtige API-Endpoints

| Methode | Pfad                              | Zweck                                   |
|---------|-----------------------------------|-----------------------------------------|
| GET     | `/api/health`                     | Liveness-Check                          |
| POST    | `/api/uploads/init`               | Chunked-Upload starten                  |
| PUT     | `/api/uploads/{id}?offset=N`      | Chunk hochladen                         |
| GET     | `/api/uploads/{id}`               | Upload-Status (für Resume)              |
| POST    | `/api/uploads/{id}/complete`      | Upload abschließen, Datei probieren     |
| GET     | `/api/files/{id}`                 | FileInfo (inkl. Preview-Status)         |
| GET     | `/api/files/{id}/preview`         | 720p H.264 Browser-Preview (Range)      |
| GET     | `/api/files/{id}/raw`             | Original-Datei streamen (Range)         |
| DELETE  | `/api/files/{id}`                 | Datei + Preview löschen                 |
| POST    | `/api/jobs`                       | Render-Job in die Queue schicken        |
| GET     | `/api/jobs/{job_id}`              | Job-Status (inkl. Progress)             |
| GET     | `/api/jobs/{job_id}/download`     | Fertige MP4 herunterladen               |

OpenAPI-Dokumentation: <http://localhost:8000/docs>

---

## Lokale Entwicklung (ohne kompletten Container-Build)

Backend und Frontend lassen sich auch separat starten:

```bash
# Terminal 1 — Redis
docker run -p 6379:6379 redis:7-alpine

# Terminal 2 — FastAPI
cd backend
pip install -r requirements.txt
DATA_DIR=./data REDIS_URL=redis://localhost:6379/0 \
  uvicorn app.main:app --reload --port 8000

# Terminal 3 — Celery Worker
cd backend
DATA_DIR=./data REDIS_URL=redis://localhost:6379/0 \
  celery -A app.celery_app worker --loglevel=info --concurrency=1

# Terminal 4 — Vite Dev-Server (proxyt /api → :8000)
cd frontend
npm install
npm run dev
```

> Voraussetzung lokal: `ffmpeg` und `ffprobe` müssen im `PATH` liegen.

---

## Troubleshooting

- **Upload bricht ab / Timeout im Browser** — Chunk-Größe verkleinern in
  `frontend/src/api.js` (`CHUNK_SIZE`). Standard 8 MiB sollte für jede
  Internetverbindung passen.
- **Preview wird nie „ready"** — Worker-Logs prüfen
  (`docker compose logs -f worker`). Häufigste Ursache: Quellcodec wird vom
  installierten FFmpeg-Build nicht unterstützt.
- **Render schlägt fehl mit `height not divisible by 2`** — Output-Auflösung
  auf gerade Werte setzen. Das Backend rundet zwar automatisch ab, aber bei
  exotischen Custom-Werten kann es klemmen.
- **DVR-Overlay erscheint nicht im Output** — DVR-Trim prüfen: ist die getrimmte
  DVR-Spur kürzer als die Hi-Res-Spur, blendet das Overlay am Ende aus
  (`eof_action=pass`).
- **HEVC-Quelle spielt im Browser nicht ab** — egal: das ist nur die Vorschau-
  Quelle. Sobald der Worker das `previews/<id>.mp4` erzeugt hat, schaltet die UI
  automatisch um.

---

## Lizenz

Privates Projekt — keine Lizenz vergeben.
