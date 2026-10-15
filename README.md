# YT Trim API

REST API for downloading trimmed YouTube clips and recording live streams.  
Built with **FastAPI + yt-dlp + ffmpeg**, deployable on [Render](https://render.com).

---

## Deploy to Render (one-time setup)

1. Push this folder to a GitHub repo.
2. Go to **Render → New → Web Service** and connect the repo.
3. Render will detect `render.yaml` automatically. Click **Deploy**.
4. Your API will be live at `https://yt-trim-api.onrender.com` (or your chosen name).

> **Free tier note:** Render free instances sleep after inactivity.  
> The first request after sleep takes ~30 s while the instance wakes.

---

## Endpoints

### `GET /health`
Check that ffmpeg and yt-dlp are available.

```json
{ "status": "ok", "ffmpeg": true, "yt_dlp": true, "js_runtime": "nodejs" }
```

---

### `POST /clip`
Download a trimmed segment. The server blocks, then streams the MP4 back.

**Body (JSON):**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | **required** | YouTube URL |
| `start` | string | **required** | Start time: `HH:MM:SS` or plain seconds |
| `end` | string | **required** | End time or duration (see `end_mode`) |
| `end_mode` | string | `"endtime"` | `"endtime"` or `"duration"` |
| `filename` | string | `"clip.mp4"` | Output filename |

**Example — download 30-second clip:**
```bash
curl -X POST https://your-service.onrender.com/clip \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "start": "00:01:00",
    "end": "30",
    "end_mode": "duration",
    "filename": "my_clip.mp4"
  }' \
  --output my_clip.mp4
```

**Example — clip between two timestamps:**
```bash
curl -X POST https://your-service.onrender.com/clip \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "start": "00:01:00",
    "end": "00:01:30",
    "end_mode": "endtime"
  }' \
  --output clip.mp4
```

---

### `POST /record`
Start an **async** live-stream recording job. Returns a `job_id` immediately.

**Body (JSON):**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | **required** | Live stream URL |
| `filename` | string | `"live_recording.mp4"` | Output filename |

**Example:**
```bash
curl -X POST https://your-service.onrender.com/record \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=LIVE_ID"}'
```

**Response:**
```json
{
  "job_id": "a3f7c...",
  "status": "running",
  "message": "Recording live stream to live_recording.mp4",
  "started_at": "2025-01-01T12:00:00"
}
```

---

### `GET /jobs/{job_id}`
Poll a job's status. Includes the last 20 log lines.

```bash
curl https://your-service.onrender.com/jobs/a3f7c...
```

**Statuses:** `running` → `done` | `error` | `stopped`

---

### `POST /jobs/{job_id}/stop`
Gracefully stop a live recording (sends `q` to ffmpeg stdin).

```bash
curl -X POST https://your-service.onrender.com/jobs/a3f7c.../stop
```

---

### `GET /jobs/{job_id}/download`
Download the finished recording once status is `done` or `stopped`.

```bash
curl https://your-service.onrender.com/jobs/a3f7c.../download \
  --output recording.mp4
```

---

## Local development

```bash
pip install -r requirements.txt
# also needs: brew install ffmpeg  (macOS) / apt install ffmpeg (Linux)
uvicorn main:app --reload
# Interactive docs at http://localhost:8000/docs
```

---

## Notes

- **Storage:** output files are written to `/tmp/yt-trim/` (ephemeral on Render). For persistent storage, mount a Render Disk or upload to S3 after download.
- **Timeouts:** Render free tier has a 60-second request timeout. Long clips will time out on `/clip`; use `/record` + `/jobs/{id}/download` instead.
- **Concurrency:** jobs run in background threads; multiple simultaneous recordings are supported.
