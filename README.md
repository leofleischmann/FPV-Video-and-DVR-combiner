# FPV PiP Merger

**Combine your goggles recording and your drone into one video** — full-screen FPV with the drone picture-in-picture. Everything runs **on your machine** in the **browser**; your files never leave your system.

---

## What problem does this solve?

FPV pilots often have **two recordings**: **goggles** (DVR) and the **drone** in high resolution. You usually want both in one clip — drone as the main frame, goggles as a small overlay — with **start and end** of both sources **aligned** to the same real-world moment and length.

Doing that by hand in an editor is tedious. **FPV PiP Merger** streamlines it: **upload**, **sync**, **position the overlay**, **export** — you get a shareable **MP4**.

---

## In short

A small app (runs at home via **Docker**) with a simple flow:

1. **Files** — hi-res drone clips (multiple parts if needed), goggles recording, optional **MP3** music.
2. **Sync** — set start/end so both angles line up in time.
3. **Layout** — size and place the small goggles window; drag it in the preview.
4. **Export** — render and **download**, or copy the file straight from the project folder.

If you add an MP3, that becomes the soundtrack; otherwise the drone’s audio is kept.

---

## Requirements

- **Docker Desktop** (Windows or Mac) to run the stack.
- Enough **disk space** for source files and the output.

---

## Run it

1. Open a terminal in this project folder (where you unpacked or cloned it).
2. Run:

```bash
docker compose up --build
```

3. Open in your browser: **http://localhost:8080**

When you’re done:

```bash
docker compose down
```

**Note:** Uploads and exports live under **`data/`** in this project. After a render, the finished file is at **`data/outputs/`** (filename matches the job id). For huge files, copying from that folder avoids a long browser download.

---

## If something goes wrong

- **Page won’t load** — Check that Docker is running and `docker compose` started without errors.
- **Preview won’t play** — Some goggles codecs are transcoded in the background for the browser; wait a bit. **Export** can still work once uploads finished.
- **Very large files** — Uploads are chunked; on a flaky network, prefer working locally (`localhost`).

---

## Technical note (optional)

Services run in containers (web UI, worker, cache). Video is processed with **FFmpeg**. An **NVIDIA GPU** can speed up encoding — see `docker-compose.gpu.yml` if you use GPU passthrough.

---

## License

Private project — no license granted.
