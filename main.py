#!/usr/bin/env python3
"""
============================================================================
 Combined Video+Audio Direct Link Extractor – No FFmpeg, Pure Python
 Author : Kobir Shah
 Fixes : Handles invalid cookie formats gracefully, prevents file corruption.
 Usage : python main.py --cookies cookies.txt --proxy socks5://127.0.0.1:9050
============================================================================
"""

import os
import re
import logging
import argparse
import sys
from datetime import datetime

import yt_dlp
from flask import Flask, request, jsonify, render_template_string

# ---------------------- Configuration ----------------------
PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "0.0.0.0")
COOKIES_FILE = os.environ.get("COOKIES_FILE", "")
PROXY = os.environ.get("PROXY", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("YtdlAPI")

app = Flask(__name__)

# CORS
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


# ---------------- Cookies Validation ----------------
def is_valid_netscape_cookies(filepath: str) -> bool:
    """Check if the first line of the file is a valid Netscape header."""
    if not filepath or not os.path.isfile(filepath):
        return False
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        return first_line.startswith("# Netscape HTTP Cookie File") or \
               first_line.startswith("# HTTP Cookie File")
    except Exception:
        return False


# ---------------- yt-dlp Options Builder ----------------
def get_ydl_opts(cookies_file: str = None, proxy: str = None) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": None,
        "skip_download": True,
        "noplaylist": True,
        "no_color": True,
        "socket_timeout": 15,
        "retries": 3,
        "fragment_retries": 3,
    }

    # Validate and attach cookies file
    if cookies_file:
        if is_valid_netscape_cookies(cookies_file):
            opts["cookiefile"] = cookies_file
            # Prevent yt-dlp from writing back to the original file
            opts["cookiejar"] = os.devnull  # discard any new cookies
            logger.info(f"Using cookies: {cookies_file}")
        else:
            logger.warning(
                f"Cookies file '{cookies_file}' is NOT in Netscape format – skipping. "
                "You must export cookies as 'Netscape HTTP Cookie File' to bypass bot detection."
            )

    if proxy:
        opts["proxy"] = proxy
        logger.info(f"Using proxy: {proxy}")
    return opts


# ---------------- Sanitize Filename ----------------
def safe_filename(title: str, ext: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title).strip().rstrip('.') or "video"
    return f"{clean[:100]}.{ext}"


# ---------------- Core Extraction ----------------
def extract_direct_url(video_url: str, quality: str = "best",
                       cookies_file: str = None, proxy: str = None) -> dict:
    ydl_opts = get_ydl_opts(cookies_file, proxy)

    if quality == "worst":
        ydl_opts["format"] = "worst[ext=mp4]/worst"
    elif re.match(r'^\d+p$', quality):
        height = quality[:-1]
        ydl_opts["format"] = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"best[height<={height}][ext=mp4]/best[height<={height}]"
        )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
        combined = [f for f in info["formats"] if f.get("vcodec") != "none" and f.get("acodec") != "none"]
        if not combined:
            raise ValueError("No combined video+audio format available for this video.")
        combined.sort(key=lambda f: (0 if f.get("ext") == "mp4" else 1, -f.get("height", 0)))
        chosen = combined[0]
        title = info.get("title", "unknown")
        ext = chosen.get("ext", "mp4")
        return {
            "direct_url": chosen["url"],
            "title": title,
            "filename": safe_filename(title, ext),
            "duration": info.get("duration"),
            "filesize": chosen.get("filesize"),
            "resolution": f"{chosen.get('width','?')}x{chosen.get('height','?')}",
        }


# ---------------- API Endpoints ----------------
@app.route("/extract", methods=["GET"])
def extract():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "Missing 'url' parameter"}), 400

    quality = request.args.get("quality", "best").strip().lower()
    cookies_param = request.args.get("cookies") or COOKIES_FILE
    proxy_param = request.args.get("proxy") or PROXY

    try:
        data = extract_direct_url(url, quality, cookies_param, proxy_param)
        logger.info(f"Extracted: {data['title']} [{data['resolution']}]")
        return jsonify({"success": True, "data": data})
    except ValueError as e:
        logger.warning(f"Extraction failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("Unexpected error")
        return jsonify({"success": False, "error": "Internal server error"}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok", "credit": "Kobir Shah"})


# ---------------- Web UI ----------------
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
        input, select, button { width: 100%; padding: 0.5em; margin: 0.5em 0; box-sizing: border-box; }
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
    <div class="footer">Author: <strong>Kobir Shah</strong> · No FFmpeg · Cookies/Proxy supported</div>
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


# ---------------- Main ----------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Combined Link Extractor (KaiOS)")
    parser.add_argument("--cookies", help="Path to cookies.txt (Netscape format)")
    parser.add_argument("--proxy", help="SOCKS5 proxy, e.g., socks5://127.0.0.1:9050")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--host", default=HOST)
    args = parser.parse_args()

    if args.cookies:
        COOKIES_FILE = args.cookies
    if args.proxy:
        PROXY = args.proxy

    if COOKIES_FILE and not is_valid_netscape_cookies(COOKIES_FILE):
        logger.error(
            f"Cookies file '{COOKIES_FILE}' is NOT in Netscape format. "
            "Please export it as 'Netscape HTTP Cookie File' and restart."
        )
        sys.exit(1)  # Hard exit if explicitly provided but invalid

    app.run(host=args.host, port=args.port, debug=False, threaded=True)
