#!/usr/bin/env python3
"""
============================================================
 Combined Video+Audio Link Extractor (No FFmpeg, Pure Python)
 Author : Kobir Shah
 For KaiOS Downloader Apps
 Solves bot-detection by using browser cookies.
============================================================
"""

import os
import re
import logging
import argparse
from datetime import datetime

import yt_dlp
from flask import Flask, request, jsonify, render_template_string

# ---------------------- Configuration ----------------------
PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "0.0.0.0")
COOKIES_FILE = os.environ.get("COOKIES_FILE", "")  # path to cookies.txt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("YtdlAPI")

app = Flask(__name__)

# ---------------- CORS (for KaiOS WebView) -----------------
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


# ------------------ yt-dlp Options Builder ------------------
def get_ydl_opts(cookies_file: str = None):
    """Create yt-dlp options, optionally with a cookies file."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": None,   # never merge, we only pick pre-muxed streams
        "skip_download": True,
        "noplaylist": True,
        "no_color": True,
        "socket_timeout": 15,
        "retries": 3,
        "fragment_retries": 3,
    }
    if cookies_file and os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file
        logger.info(f"Using cookies from: {cookies_file}")
    return opts


# ------------------ Sanitize Filename ------------------
def safe_filename(title: str, ext: str) -> str:
    """Remove illegal characters for KaiOS filesystem."""
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title)
    clean = clean.strip().rstrip('.') or "video"
    if len(clean) > 100:
        clean = clean[:100]
    return f"{clean}.{ext}"


# ------------------ Core Extraction Function ------------------
def extract_direct_url(video_url: str, quality: str = "best",
                       cookies_file: str = None) -> dict:
    """
    Returns a direct download URL for a combined video+audio stream.
    Raises ValueError on failure.
    """
    ydl_opts = get_ydl_opts(cookies_file)

    # Adjust format selector based on quality
    if quality == "worst":
        ydl_opts["format"] = "worst[ext=mp4]/worst"
    elif re.match(r'^\d+p$', quality):  # e.g., 720p
        height = quality[:-1]
        ydl_opts["format"] = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"best[height<={height}][ext=mp4]/best[height<={height}]"
        )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(video_url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise ValueError(f"Cannot process URL: {e}")

        # Filter only formats that contain both video and audio
        combined = [
            f for f in info.get("formats", [])
            if f.get("vcodec") != "none" and f.get("acodec") != "none"
        ]
        if not combined:
            raise ValueError("No combined video+audio format available for this video.")

        # Prefer mp4 container, then highest resolution
        combined.sort(key=lambda f: (
            0 if f.get("ext") == "mp4" else 1,
            -f.get("height", 0)
        ))
        chosen = combined[0]

        # Metadata
        title = info.get("title", "unknown")
        ext = chosen.get("ext", "mp4")
        filename = safe_filename(title, ext)

        return {
            "direct_url": chosen["url"],
            "title": title,
            "filename": filename,
            "duration": info.get("duration"),
            "filesize": chosen.get("filesize"),
            "format_id": chosen.get("format_id"),
            "ext": ext,
            "resolution": f"{chosen.get('width', '?')}x{chosen.get('height', '?')}",
            "vcodec": chosen.get("vcodec"),
            "acodec": chosen.get("acodec"),
        }


# ------------------ API Endpoints ------------------
@app.route("/extract", methods=["GET"])
def extract():
    """Main endpoint: ?url=VIDEO_URL&quality=best&cookies=/path/to/cookies"""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "Missing 'url' parameter"}), 400

    quality = request.args.get("quality", "best").strip().lower()
    # Allow overriding cookies via query param (useful for testing)
    cookies_param = request.args.get("cookies")
    cookies_path = cookies_param or COOKIES_FILE

    try:
        result = extract_direct_url(url, quality, cookies_path)
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
        "credit": "Kobir Shah"
    })


# ------------------ Minimal Web UI (for testing) ------------------
INDEX_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Direct Link Extractor – Kobir Shah</title>
    <style>
        body { font-family: sans-serif; max-width: 600px; margin: 2em auto; padding: 1em; }
        h1 { color: #0d6efd; }
        label { font-weight: bold; }
        input, select, button { width: 100%; padding: 0.5em; margin: 0.5em 0; }
        button { background: #0d6efd; color: white; border: none; cursor: pointer; }
        button:hover { background: #0b5ed7; }
        #result { margin-top: 1em; padding: 1em; background: #e9ecef; white-space: pre-wrap; word-break: break-all; }
        .footer { margin-top: 2em; font-size: 0.85em; color: #6c757d; text-align: center; }
    </style>
</head>
<body>
    <h1>🎬 Video+Audio Direct Link Extractor</h1>
    <label>Video URL:</label>
    <input type="text" id="url" placeholder="https://www.youtube.com/watch?v=...">
    <label>Quality:</label>
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
    <div class="footer">Author: <strong>Kobir Shah</strong> | No FFmpeg required</div>
    <script>
        async function fetchLink() {
            const url = document.getElementById('url').value.trim();
            const quality = document.getElementById('quality').value;
            const resDiv = document.getElementById('result');
            if (!url) { resDiv.textContent = 'Please enter a URL'; return; }
            resDiv.textContent = 'Loading...';
            try {
                const res = await fetch(`/extract?url=${encodeURIComponent(url)}&quality=${quality}`);
                const data = await res.json();
                if (data.success) {
                    resDiv.innerHTML = `<strong>Title:</strong> ${data.data.title}<br>
                                        <strong>Resolution:</strong> ${data.data.resolution}<br>
                                        <strong>Filename:</strong> ${data.data.filename}<br>
                                        <strong>Direct URL:</strong><br><a href="${data.data.direct_url}" target="_blank">${data.data.direct_url}</a>`;
                } else {
                    resDiv.textContent = 'Error: ' + data.error;
                }
            } catch (err) {
                resDiv.textContent = 'Request failed: ' + err.message;
            }
        }
    </script>
</body>
</html>"""

@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML)


# ------------------ Command Line Entry Point ------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YtDlp Combined Link Extractor (No FFmpeg)")
    parser.add_argument("--cookies", help="Path to cookies.txt file (for avoiding bot detection)")
    parser.add_argument("--port", type=int, default=PORT, help="Server port")
    parser.add_argument("--host", default=HOST, help="Server host")
    args = parser.parse_args()

    if args.cookies:
        COOKIES_FILE = args.cookies
        logger.info(f"Cookies file set via --cookies: {COOKIES_FILE}")
    else:
        logger.info("No cookies file provided – may fail for YouTube bot checks")

    app.run(host=args.host, port=args.port, debug=False, threaded=True)
