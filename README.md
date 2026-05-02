# FPV Picture Merger

Turn your **drone recording** and **goggles recording** into **one MP4**: drone fills the screen, goggles appear as a small overlay you can move and resize. Everything runs **on your computer** in the browser — your videos stay local.

---

## What you’ll do

1. Add your **drone** video(s) and your **goggles** video.
2. **Sync** them so the same moment in real life lines up on both clips.
3. Choose **layout** (where the small goggles window sits and how big it is).
4. **Export** and download — or grab the file from the project folder if the browser download is slow.

Optional: add an **MP3** as the soundtrack. If you skip music, the drone’s audio is used.

---

## Before you start

| You need | Why |
|----------|-----|
| **Docker Desktop** (Windows or Mac) | Runs the app for you — no manual install of Python, FFmpeg, etc. |
| **Enough disk space** | Room for uploads plus the finished video |

---

## Start the app

1. Open a terminal **in this project folder** (where this README lives).
2. Run:

```bash
docker compose up --build
```

3. Wait until the terminal looks settled (no repeating errors).
4. Open your browser and go to: **http://localhost:8080**

**Stop** when you’re finished:

```bash
docker compose down
```

---

## Where your files go

- Uploads and exports are stored in the **`data`** folder inside this project.
- After a successful export, look in **`data/outputs/`** for the MP4 (you can copy it directly instead of downloading through the browser).

---

## If something doesn’t work

| Problem | What to try |
|---------|-------------|
| Page won’t open | Make sure Docker Desktop is running. Run `docker compose up --build` again and check for red error lines in the terminal. |
| Preview takes a while | Some goggles files need a quick conversion for the browser — wait a bit. **Export** can still work once uploads finished. |
| Upload feels slow | Prefer using **localhost** on the same PC as Docker; very large files need time and stable disk. |

---

## Faster encoding (optional)

If your PC has an **NVIDIA GPU** and you use GPU passthrough with Docker, see **`docker-compose.gpu.yml`** for a GPU-enabled setup. Not required for normal use.

---

## License

Private project — no license granted.
