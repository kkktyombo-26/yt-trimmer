"""
yt_trim_api — FastAPI service for downloading trimmed YouTube segments
and recording live streams. Deployable on Render.
"""

import imageio_ffmpeg
import os
import re
import sys
import uuid
import shutil
import asyncio
import subprocess
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime

# ── ffmpeg setup ──────────────────────────────────────────────────────────────
_ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["PATH"] = os.path.dirname(_ffmpeg_exe) + os.pathsep + os.environ.get("PATH", "")

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

# ── Config ────────────────────────────────────────────────────────────────────
WORK_DIR = Path(os.getenv("WORK_DIR", "/tmp/yt-trim"))
WORK_DIR.mkdir(parents=True, exist_ok=True)

_COOKIES_SOURCE = os.getenv("COOKIES_FILE", "/etc/secrets/cookies.txt")
COOKIES_FILE = "/tmp/yt-trim/cookies.txt"

if Path(_COOKIES_SOURCE).exists():
    shutil.copy2(_COOKIES_SOURCE, COOKIES_FILE)

JOBS: dict[str, dict] = {}

# ── Format strings ────────────────────────────────────────────────────────────
CLIP_FORMAT   = "bestvideo[protocol=m3u8_native]+bestaudio[protocol=m3u8_native]/best[protocol=m3u8_native]/bestvideo+bestaudio/best"
RECORD_FORMAT = "bestvideo+bestaudio/best"

# ── Helpers ───────────────────────────────────────────────────────────────────
def to_seconds(t: str) -> int:
    t = t.strip().lstrip("t").rstrip("s")
    if re.fullmatch(r"\d+", t):
        return int(t)
    parts = list(map(int, t.split(":")))
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"Unrecognised time format: {t!r}")


def fmt(seconds: int) -> str:
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def clean_url(url: str) -> str:
    return re.sub(
        r"[?&]t=\d+s?",
        lambda m: "" if m.group(0).startswith("&") else "?",
        url,
    ).rstrip("?")


def detect_js_runtime() -> Optional[str]:
    for r in ("node", "deno", "bun"):
        if shutil.which(r):
            return r
    return None


def js_runtime_args() -> list[str]:
    """Return --js-runtimes flag with the correct runtime name, or empty list."""
    runtime = detect_js_runtime()
    if runtime:
        return ["--js-runtimes", runtime]   # "node" not "nodejs"
    return []


def cookies_args() -> list[str]:
    if Path(COOKIES_FILE).exists():
        return ["--cookies", COOKIES_FILE]
    return []


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="YT Trim API",
    description="Download trimmed YouTube clips or record live streams via REST.",
    version="1.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.kkktdmpyombo.org",
        "https://kkktdmpyombo.org",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Models ────────────────────────────────────────────────────────────────────
class ClipRequest(BaseModel):
    url: str
    start: str
    end: str
    end_mode: str = "endtime"
    filename: str = "clip.mp4"

    @field_validator("end_mode")
    @classmethod
    def validate_end_mode(cls, v):
        if v not in ("endtime", "duration"):
            raise ValueError("end_mode must be 'endtime' or 'duration'")
        return v

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, v):
        v = Path(v).name
        if not v.endswith(".mp4"):
            v += ".mp4"
        return v


class RecordRequest(BaseModel):
    url: str
    filename: str = "live_recording.mp4"

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, v):
        v = Path(v).name
        if not v.endswith(".mp4"):
            v += ".mp4"
        return v


class JobStatus(BaseModel):
    job_id: str
    status: str
    message: str
    started_at: str
    ended_at: Optional[str] = None
    output_file: Optional[str] = None
    log_tail: list[str] = []


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status":       "ok",
        "ffmpeg":       bool(shutil.which("ffmpeg")),
        "yt_dlp":       True,
        "js_runtime":   detect_js_runtime(),
        "cookies_file": Path(COOKIES_FILE).exists(),
    }


# ── /clip ─────────────────────────────────────────────────────────────────────
@app.post("/clip", summary="Download a trimmed clip and stream it back")
async def clip(req: ClipRequest):
    if not shutil.which("ffmpeg"):
        raise HTTPException(503, "ffmpeg not found on this server")

    try:
        start_s = to_seconds(req.start)
        end_s   = start_s + int(req.end) if req.end_mode == "duration" else to_seconds(req.end)
    except Exception as e:
        raise HTTPException(422, f"Invalid time value: {e}")

    if end_s <= start_s:
        raise HTTPException(422, "end must be after start")

    job_id   = uuid.uuid4().hex
    out_dir  = WORK_DIR / job_id
    out_dir.mkdir(parents=True)
    out_path = out_dir / req.filename

    section = f"*{fmt(start_s)}-{fmt(end_s)}"

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--download-sections", section,          # ← restored (was missing!)
        "-f", CLIP_FORMAT,                       # ← clip format, not record format
        "--merge-output-format", "mp4",
        "--no-playlist",
        *js_runtime_args(),                      # ← "node" not "nodejs"
        *cookies_args(),
        "-o", str(out_path),
        clean_url(req.url),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()

    if proc.returncode != 0:
        log = stdout.decode(errors="replace")
        shutil.rmtree(out_dir, ignore_errors=True)
        raise HTTPException(500, f"yt-dlp failed:\n{log[-2000:]}")

    if not out_path.exists():
        candidates = list(out_dir.glob("*"))
        if candidates:
            out_path = candidates[0]
        else:
            raise HTTPException(500, "Output file not found after download")

    return FileResponse(
        path=str(out_path),
        media_type="video/mp4",
        filename=out_path.name,
        background=BackgroundTasks(),
    )


# ── /record ───────────────────────────────────────────────────────────────────
def _run_record_job(job_id: str, cmd: list[str], out_path: Path):
    job = JOBS[job_id]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
        )
        job["proc"] = proc
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                job["log"].append(line)
                if len(job["log"]) > 200:
                    job["log"] = job["log"][-200:]
        proc.wait()
        rc = proc.returncode
        job["ended_at"] = datetime.utcnow().isoformat()
        if rc in (0, -2, -15):
            job["status"]      = "done"
            job["message"]     = f"Recording saved → {out_path.name}"
            job["output_file"] = str(out_path)
        else:
            job["status"]  = "error"
            job["message"] = f"yt-dlp exited with code {rc}"
    except Exception as e:
        job["status"]   = "error"
        job["message"]  = str(e)
        job["ended_at"] = datetime.utcnow().isoformat()
    finally:
        job.pop("proc", None)


@app.post("/record", summary="Start an async live-recording job", response_model=JobStatus)
def record(req: RecordRequest, background_tasks: BackgroundTasks):
    if not shutil.which("ffmpeg"):
        raise HTTPException(503, "ffmpeg not found on this server")

    job_id   = uuid.uuid4().hex
    out_dir  = WORK_DIR / job_id
    out_dir.mkdir(parents=True)
    out_path = out_dir / req.filename

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", RECORD_FORMAT,
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--live-from-start",
        "--hls-prefer-native",
        *js_runtime_args(),                      # ← same helper, always correct
        *cookies_args(),
        "-o", str(out_path),
        req.url,
    ]

    job = {
        "job_id":      job_id,
        "status":      "running",
        "message":     f"Recording live stream to {req.filename}",
        "started_at":  datetime.utcnow().isoformat(),
        "ended_at":    None,
        "output_file": None,
        "log":         [],
        "proc":        None,
    }
    JOBS[job_id] = job

    threading.Thread(
        target=_run_record_job, args=(job_id, cmd, out_path), daemon=True
    ).start()

    return _job_response(job_id)


# ── Job management ────────────────────────────────────────────────────────────
def _job_response(job_id: str) -> JobStatus:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id!r} not found")
    return JobStatus(
        job_id=job["job_id"],
        status=job["status"],
        message=job["message"],
        started_at=job["started_at"],
        ended_at=job.get("ended_at"),
        output_file=job.get("output_file"),
        log_tail=job["log"][-20:],
    )


@app.get("/jobs/{job_id}", response_model=JobStatus)
def job_status(job_id: str):
    return _job_response(job_id)


@app.post("/jobs/{job_id}/stop", response_model=JobStatus)
def job_stop(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id!r} not found")
    if job["status"] != "running":
        raise HTTPException(409, f"Job is not running (status: {job['status']})")
    proc: subprocess.Popen = job.get("proc")
    if proc:
        try:
            proc.stdin.write("q\n")
            proc.stdin.flush()
        except Exception:
            proc.terminate()
    job["status"]  = "stopped"
    job["message"] = "Stop requested"
    return _job_response(job_id)


@app.get("/jobs/{job_id}/download", summary="Download a completed recording")
def job_download(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id!r} not found")
    if job["status"] not in ("done", "stopped"):
        raise HTTPException(409, f"Job not finished yet (status: {job['status']})")
    out = job.get("output_file")
    if not out or not Path(out).exists():
        raise HTTPException(404, "Output file not found")
    return FileResponse(path=out, media_type="video/mp4", filename=Path(out).name)