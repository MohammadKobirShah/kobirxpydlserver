#!/usr/bin/env python3
"""
====================================================================
Video+Audio Direct Link Extractor API (Pure Python, Zero Dependencies)
Author : Kobir Shah
License: MIT
For KaiOS Downloader Apps – Returns a single combined video+audio URL
====================================================================
"""

import os
import re
import logging
import urllib.parse
from datetime import datetime
from functools import wraps

import yt_dlp
from flask import Flask, request, jsonify, render_template_string

# ---------- Configuration ----------
PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "0.0.0.0")
LOG_LEVEL = logging.INFO

# ---------- Logging Setup ----------
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("YtdlAPI")

# ---------- Flask App ----------
app = Flask(__name__)

# ---------- CORS Decorator ----------
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

app.after_request(add_cors_headers)

# ---------- yt-dlp Options (combined video+audio only) ----------
YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",  
    # This ensures we get a combined mp4 if possible; otherwise any combined format.
    "merge_output_format": None,   # no post-processing
    "skip_download": True,
    "noplaylist": True,
    "extract_flat": False,
    "no_color": True,
    "socket_timeout": 15,
    "retries": 3,
    "fragment_retries": 3,
}

# ---------- Helper: sanitize filename ----------
def safe_filename(title: str, ext: str) -> str:
    """Remove unsafe characters, keep spaces, limit length."""
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title)  # remove forbidden chars
    title = title.strip().rstrip('.')
    if not title:
        title = "video"
    max_len = 100  # KaiOS filesystem friendly
    if len(title) > max_len:
        title = title[:max_len]
    return f"{title}.{ext}"

# ---------- Core Extraction Logic ----------
def extract_direct_url(video_url: str, quality: str = "best") -> dict:
    """
    Extract a direct download link for a combined video+audio format.
    Parameters:
        video_url : str
        quality   : one of "best", "worst", "720p", "1080p", "480p" etc.
    Returns:
        dict with keys: direct_url, title, duration, filesize, filename, ext, format_note, resolution
    """
    opts = YDL_OPTS.copy()
    # Apply quality selection while still keeping combined streams
    if quality == "worst":
        format_selector = "worst[ext=mp4]/worst"
    elif re.match(r'^\d+p$', quality):  # e.g., 720p
        height = quality[:-1]
        # Prefer mp4 with that height, combined streams
        format_selector = f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}][ext=mp4]/best[height<={height}]"
    else:
        format_selector = opts.get("format", "best[ext=mp4]/best")

    opts["format"] = format_selector

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(video_url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise ValueError(f"Cannot process URL: {e}")

        # Filter combined formats (both video and audio codec)
        combined_formats = [
            f for f in info.get("formats", [])
            if f.get("vcodec") != "none" and f.get("acodec") != "none"
        ]
        if not combined_formats:
            raise ValueError("No combined video+audio format found. Try another video.")

        # Sort by preference: mp4 first, then by quality (height)
        def sort_key(f):
            is_mp4 = 1 if f.get("ext") == "mp4" else 0
            height = f.get("height") or 0
            return (-is_mp4, -height)

        combined_formats.sort(key=sort_key)
        chosen = combined_formats[0]  # best mp4/combined

        # Extract useful info
        title = info.get("title", "unknown")
        ext = chosen.get("ext", "mp4")
        filename = safe_filename(title, ext)
        direct_url = chosen["url"]
        filesize = chosen.get("filesize") or chosen.get("filesize_approx")
        duration = info.get("duration")

        return {
            "direct_url": direct_url,
            "title": title,
            "filename": filename,
            "duration": duration,
            "filesize": filesize,
            "format_id": chosen.get("format_id"),
            "ext": ext,
            "resolution": f"{chosen.get('width', 0)}x{chosen.get('height', 0)}" if chosen.get('width') else "",
            "format_note": chosen.get("format_note", ""),
            "vcodec": chosen.get("vcodec"),
            "acodec": chosen.get("acodec"),
        }

# ---------- API Endpoints ----------
@app.route("/extract", methods=["GET"])
def extract():
    """Main endpoint: ?url=VIDEO_URL&quality=best"""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "Missing 'url' parameter"}), 400

    quality = request.args.get("quality", "best").strip().lower()

    try:
        result = extract_direct_url(url, quality)
        logger.info(f"Extracted: {result['title']} [{result['resolution']}]")
        return jsonify({"success": True, "data": result})
    except ValueError as e:
        logger.warning(f"Extraction failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("Unexpected error")
        return jsonify({"success": False, "error": "Internal server error"}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "powered_by": "yt-dlp + Flask",
        "credit": "Kobir Shah"
    })

# ---------- Simple Web UI for manual testing ----------
INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YtDlp Link Extractor - Kobir Shah</title>
    <style>
        body { font-family: sans-serif; margin: 2em; background: #f8f9fa; color: #212529; }
        .container { max-width: 600px; margin: auto; background: white; padding: 2em; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        h1 { text-align: center; color: #0d6efd; }
        label { font-weight: bold; display: block; margin-top: 1em; }
        input[type="text"], select { width: 100%; padding: 0.5em; margin-top: 0.3em; border: 1px solid #ced4da; border-radius: 5px; }
        button { margin-top: 1.5em; width: 100%; padding: 0.7em; background: #0d6efd; color: white; border: none; border-radius: 5px; font-size: 1.1em; cursor: pointer; }
        button:hover { background: #0b5ed7; }
        #result { margin-top: 1.5em; padding: 1em; background: #e9ecef; border-radius: 5px; white-space: pre-wrap; word-break: break-all; display: none; }
        .footer { text-align: center; margin-top: 2em; font-size: 0.85em; color: #6c757d; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎬 Direct Link Extractor</h1>
        <p style="text-align:center;">Get a single video+audio (no merging needed)</p>
        <label for="url">Video URL</label>
        <input type="text" id="url" placeholder="https://www.youtube.com/watch?v=...">
        <label for="quality">Quality</label>
        <select id="quality">
            <option value="best">Best available</option>
            <option value="1080p">1080p</option>
            <option value="720p">720p</option>
            <option value="480p">480p</option>
            <option value="360p">360p</option>
            <option value="worst">Worst available</option>
        </select>
        <button onclick="fetchLink()">Get Direct Link</button>
        <div id="result"></div>
    </div>
    <div class="footer">
        Created by <strong>Kobir Shah</strong> | Powered by yt-dlp & Flask | No FFmpeg required
    </div>
    <script>
        async function fetchLink() {
            const url = document.getElementById('url').value.trim();
            const quality = document.getElementById('quality').value;
            const resultDiv = document.getElementById('result');
            if (!url) { resultDiv.style.display = 'block'; resultDiv.textContent = 'Please enter a URL'; return; }
            resultDiv.style.display = 'block';
            resultDiv.textContent = 'Loading...';
            try {
                const res = await fetch(`/extract?url=${encodeURIComponent(url)}&quality=${quality}`);
                const data = await res.json();
                if (data.success) {
                    resultDiv.innerHTML = `<strong>Title:</strong> ${data.data.title}<br>
                                           <strong>Resolution:</strong> ${data.data.resolution}<br>
                                           <strong>File:</strong> ${data.data.filename}<br>
                                           <strong>Size:</strong> ${data.data.filesize ? (data.data.filesize/1024/1024).toFixed(2) + ' MB' : 'Unknown'}<br>
                                           <strong>Direct URL:</strong><br><a href="${data.data.direct_url}" target="_blank">${data.data.direct_url}</a>`;
                } else {
                    resultDiv.textContent = 'Error: ' + data.error;
                }
            } catch (err) {
                resultDiv.textContent = 'Request failed: ' + err.message;
            }
        }
    </script>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML)

# ---------- Main ----------
if __name__ == "__main__":
    logger.info(f"Starting YtDlp Link Extractor API on {HOST}:{PORT}")
    logger.info("Author: Kobir Shah – Pure Python, No FFmpeg, Combined streams only")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
