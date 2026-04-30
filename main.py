"""
KaiOS Video & Audio Download Server
Powered by yt‑dlp + Cloud FFmpeg (rendi.dev)
Supports all yt‑dlp websites (YouTube, SoundCloud, Vimeo, Twitter, etc.)
Custom output resolution with smart source selection.
Audio downloads with embedded metadata + cover art.
"""

import os
import time
import tempfile
import uuid
import asyncio
from pathlib import Path

import requests
import yt_dlp
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl

# ========== CONFIGURATION ==========
# Built‑in cloud FFmpeg API key (override with env var if needed)
RENDI_API_KEY = os.environ.get(
    "RENDI_API_KEY",
    "eJxLTEkzT7UwNetE1MDM00DUxtTDQtTBKNtY1NjJKNE1OTDNLNEmKTw4pCykrSE9J9XEMzswJTzQtqXKtcAQA4zIRuw=="
)
FFMPEG_BASE = "https://api.rendi.dev/v1"
FFMPEG_HEADERS = {"X-API-KEY": RENDI_API_KEY}

# Temporary public file hosting (files live 24h)
TMP_UPLOAD_URL = "https://tmpfiles.org/api/v1/upload"

CLEANUP_DELAY = 120          # seconds before we delete local temp files

# ========== REQUEST MODELS ==========
class DownloadVideoRequest(BaseModel):
    url: HttpUrl
    convert: bool = False          # If True, re‑encode for KaiOS
    width: int = 320               # Output width
    height: int = 240              # Output height
    audio_bitrate: str = "64k"     # Audio bitrate for final video
    source_height: int | None = None  # Max source height (auto if not set)

class DownloadAudioRequest(BaseModel):
    url: HttpUrl
    audio_bitrate: str = "128k"    # Final MP3 bitrate

# ========== HELPER FUNCTIONS ==========

def download_stream(url: str, fmt: str, output_dir: str) -> str:
    """
    Download with yt‑dlp and return the local file path.
    `fmt` is a yt‑dlp format selection string.
    """
    outtmpl = str(Path(output_dir) / "%(title).50s.%(ext)s")
    ydl_opts = {
        "format": fmt,
        "outtmpl": outtmpl,
        "quiet": True,
        "noplaylist": True,
        "nooverwrites": True,
        "postprocessors": [],   # no local ffmpeg needed
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(str(url), download=True)
        filename = ydl.prepare_filename(info)
        if os.path.exists(filename):
            return filename
        # Fallback: yt‑dlp might have changed the extension
        stem = Path(filename).stem
        for f in Path(output_dir).iterdir():
            if f.stem == stem:
                return str(f)
    raise RuntimeError("Download failed – file not found after yt‑dlp run")

def upload_to_tmpfile(file_path: str) -> str:
    """Upload a file to tmpfiles.org and return its public download URL."""
    with open(file_path, "rb") as f:
        files = {"file": (Path(file_path).name, f)}
        r = requests.post(TMP_UPLOAD_URL, files=files, timeout=30)
        r.raise_for_status()
        return r.json()["data"]["url"]

def submit_ffmpeg_command(payload: dict) -> str:
    """Send a job to the cloud FFmpeg API, return command_id."""
    resp = requests.post(
        f"{FFMPEG_BASE}/run-ffmpeg-command",
        headers=FFMPEG_HEADERS,
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()["command_id"]

def poll_ffmpeg(command_id: str, timeout: int = 300) -> str:
    """Wait for cloud FFmpeg to finish and return the output file storage URL."""
    start = time.time()
    while time.time() - start < timeout:
        res = requests.get(
            f"{FFMPEG_BASE}/commands/{command_id}",
            headers=FFMPEG_HEADERS,
        ).json()
        if res["status"] == "SUCCESS":
            return res["output_files"]["out_1"]["storage_url"]
        if res["status"] == "FAILED":
            raise RuntimeError(f"FFmpeg job failed: {res}")
        time.sleep(2)
    raise TimeoutError("FFmpeg processing timed out")

def extract_metadata(url: str) -> dict:
    """
    Extract title, uploader, date, description and thumbnail URL
    without downloading any media file.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(str(url), download=False)
    title = info.get("title", "Unknown")
    uploader = info.get("uploader", "Unknown Artist")
    upload_date = info.get("upload_date", None)  # YYYYMMDD
    year = upload_date[:4] if upload_date else ""
    album = f"{year}" if year else uploader
    comment = (info.get("description", "") or "")[:200]
    thumbnail_url = info.get("thumbnail", None)
    return {
        "title": title.replace('"', '\\"'),
        "artist": uploader.replace('"', '\\"'),
        "album": album.replace('"', '\\"'),
        "comment": comment.replace('"', '\\"'),
        "thumbnail_url": thumbnail_url,
    }

async def cleanup_temp_dir(temp_dir: str):
    """Delete temporary directory after a delay (background task)."""
    await asyncio.sleep(CLEANUP_DELAY)
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)

# ========== FASTAPI APP ==========
app = FastAPI(
    title="KaiOS Download Server",
    description="Download videos & audio from any yt‑dlp supported site, with KaiOS‑optimised conversion",
    version="2.1.0",
)

@app.post("/download")
async def download_video(req: DownloadVideoRequest):
    """
    Download a video (all yt‑dlp supported sites).
    - `convert=true` → re‑encodes to KaiOS‑compatible H.264 baseline using your custom resolution.
    - `convert=false` → returns the raw video URL (temporary hosting).
    """
    temp_dir = tempfile.mkdtemp(prefix="ytdlp_video_")
    try:
        # --- Smart source height selection ---
        if req.source_height is not None:
            max_src_height = req.source_height
        else:
            # Auto: 1.5× output height, at least 480, capped at 1080
            max_src_height = max(480, int(req.height * 1.5))
            max_src_height = min(max_src_height, 1080)

        fmt = f"best[height<={max_src_height}]/best"
        video_path = await asyncio.to_thread(
            download_stream, str(req.url), fmt, temp_dir
        )
        raw_url = await asyncio.to_thread(upload_to_tmpfile, video_path)

        if not req.convert:
            return JSONResponse({"url": raw_url, "converted": False})

        # --- Cloud FFmpeg re‑encode to custom resolution ---
        output_filename = f"kaios_video_{uuid.uuid4()}.mp4"
        ffmpeg_cmd = (
            f"-i {{in_1}} "
            f"-vf \"scale={req.width}:{req.height}:force_original_aspect_ratio=decrease,"
            f"pad={req.width}:{req.height}:(ow-iw)/2:(oh-ih)/2\" "
            f"-c:v libx264 -profile:v baseline -level 3.0 -preset ultrafast -crf 28 "
            f"-c:a aac -ar 22050 -b:a {req.audio_bitrate} "
            f"-movflags +faststart {{out_1}}"
        )
        payload = {
            "input_files": {"in_1": raw_url},
            "output_files": {"out_1": output_filename},
            "ffmpeg_command": ffmpeg_cmd,
        }
        command_id = await asyncio.to_thread(submit_ffmpeg_command, payload)
        final_url = await asyncio.to_thread(poll_ffmpeg, command_id)

        return JSONResponse({"url": final_url, "converted": True})

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        asyncio.create_task(cleanup_temp_dir(temp_dir))

@app.post("/download-audio")
async def download_audio(req: DownloadAudioRequest):
    """
    Download audio from any yt‑dlp supported site, convert to MP3 with
    full metadata (title, artist, album, comment) and embedded cover art.
    """
    temp_dir = tempfile.mkdtemp(prefix="ytdlp_audio_")
    try:
        # 1. Extract metadata (no download)
        meta = await asyncio.to_thread(extract_metadata, str(req.url))
        if not meta["thumbnail_url"]:
            raise HTTPException(status_code=400, detail="No thumbnail available to embed")

        # 2. Download best audio stream (original format)
        audio_path = await asyncio.to_thread(
            download_stream, str(req.url), "bestaudio/best", temp_dir
        )
        audio_url = await asyncio.to_thread(upload_to_tmpfile, audio_path)

        # 3. Cloud FFmpeg: MP3 conversion + metadata injection + cover art
        output_filename = f"kaios_audio_{uuid.uuid4()}.mp3"
        ffmpeg_cmd = (
            f'-i {{in_1}} -i {{in_2}} '
            f'-map 0:a -map 1:v '
            f'-c:v copy '
            f'-c:a libmp3lame -q:a 2 -b:a {req.audio_bitrate} '
            f'-id3v2_version 3 '
            f'-metadata title="{meta["title"]}" '
            f'-metadata artist="{meta["artist"]}" '
            f'-metadata album="{meta["album"]}" '
            f'-metadata comment="{meta["comment"]}" '
            f'-metadata:s:v title="Album cover" '
            f'-metadata:s:v comment="Cover (front)" '
            f'{{out_1}}'
        )
        payload = {
            "input_files": {
                "in_1": audio_url,
                "in_2": meta["thumbnail_url"],
            },
            "output_files": {"out_1": output_filename},
            "ffmpeg_command": ffmpeg_cmd,
        }
        command_id = await asyncio.to_thread(submit_ffmpeg_command, payload)
        final_url = await asyncio.to_thread(poll_ffmpeg, command_id)

        return JSONResponse({"url": final_url, "metadata": meta})

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        asyncio.create_task(cleanup_temp_dir(temp_dir))

@app.get("/health")
async def health():
    return {"status": "ok"}

# ========== START SERVER ==========
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
