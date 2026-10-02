"""
================================================================================
SV DOWNLOADER PRO - FLASK BACKEND APPLICATION
================================================================================
CS STUDENT EDUCATIONAL GUIDE:
This Python backend serves as the core API and routing engine for the video
downloader web application. It demonstrates several foundational Computer Science
and software engineering concepts:

1. Web Framework Architecture (Flask):
   - Microframework principles: minimal core with extensible routing.
   - Request-Response lifecycle: Client HTTP request -> Routing -> Controller
     logic -> HTTP Response (HTML templates or JSON payloads).
2. Asynchronous Network Extraction & Web Scraping (yt-dlp & curl_cffi):
   - Extracting multimedia streams from platform CDNs.
   - Bypassing WAF (Web Application Firewall) bot challenges via browser TLS
     impersonation (JA3/Akamai fingerprints) and reliable public DNS resolution.
3. Audio/Video Codec Engineering:
   - Universal playback standards: Selecting H.264 (AVC) container formats to avoid
     proprietary hardware licensing errors (e.g. Windows HEVC errors).
4. Memory Management & Ephemeral Storage:
   - Handling temporary files on ephemeral cloud filesystems (such as Vercel's
     read-only filesystem where only `/tmp` is writable).
   - In-memory binary streaming (`io.BytesIO`) and immediate server-side cleanup
     to prevent server memory leaks and disk exhaustion.
5. Error Sanitization & Defensive Programming:
   - Sanitizing raw terminal ANSI color sequences before sending user-facing errors.
================================================================================
"""

import os
import io
import re
import uuid
from flask import Flask, render_template, request, send_file, jsonify
import yt_dlp

# ==============================================================================
# NETWORK & DNS RESOLUTION PATCH FOR TIKTOK SCRAPING (curl_cffi)
# ------------------------------------------------------------------------------
# CS CONCEPT: DOMAIN NAME RESOLUTION (DNS) & CNAME CHAINS
# When scraping platforms like TikTok, modern CDNs (e.g., Akamai) use deep CNAME
# aliasing chains (e.g. tiktok.com -> edgesuite.net -> akadns.net).
# Precompiled c-ares DNS resolvers inside libcurl on Windows can fail or time out
# when querying local ISP home routers over UDP (resulting in `curl: (6) Could not
# resolve host: www.tiktok.com`).
# Here, we defensively configure `curl_cffi` sessions to fallback to ultra-fast,
# reliable public DNS resolvers (Cloudflare 1.1.1.1 and Google 8.8.8.8).
# ==============================================================================
try:
    import curl_cffi.requests
    from curl_cffi.curl import CurlOpt

    _original_session_init = curl_cffi.requests.Session.__init__

    def _patched_session_init(self, *args, **kwargs):
        """
        Intercepts Session instantiation to inject reliable public DNS servers.
        This ensures seamless domain resolution across both local dev and production.
        """
        curl_opts = kwargs.get('curl_options') or {}
        curl_opts[CurlOpt.DNS_SERVERS] = '1.1.1.1,8.8.8.8'
        kwargs['curl_options'] = curl_opts
        _original_session_init(self, *args, **kwargs)

    # Monkey-patch curl_cffi Session constructor
    curl_cffi.requests.Session.__init__ = _patched_session_init
except ImportError:
    # If curl_cffi is not installed in the environment, fallback gracefully to native urllib
    pass

# ==============================================================================
# FLASK APPLICATION INITIALIZATION
# ------------------------------------------------------------------------------
# Flask uses `__name__` (which evaluates to '__main__' or the module name) to
# locate static assets, templates, and the application root directory.
# ==============================================================================
app = Flask(__name__)

# ==============================================================================
# EPHEMERAL STORAGE CONFIGURATION
# ------------------------------------------------------------------------------
# In serverless cloud hosting environments like Vercel or AWS Lambda, the local
# root directory is mounted as read-only. The `/tmp` directory is the only
# writable scratch space available for temporary file processing.
# `exist_ok=True` prevents race condition errors if multiple threads/processes
# attempt to create this directory concurrently.
# ==============================================================================
DOWNLOAD_FOLDER = '/tmp/downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)


# ==============================================================================
# HELPER: ERROR MESSAGE SANITIZER
# ------------------------------------------------------------------------------
# yt-dlp outputs formatted terminal strings that contain ANSI escape codes
# (such as '\x1b[0;31mERROR:\x1b[0m'). In a web API, sending raw escape sequences
# creates garbled text in UI toast notifications.
# This utility strips terminal codes and provides human-friendly explanations.
# ==============================================================================
def sanitize_error_message(raw_error: str) -> str:
    """
    Cleans up terminal formatting and maps common platform errors to friendly messages.
    """
    # Remove terminal color codes (ANSI escape sequences)
    clean_msg = re.sub(r'\x1b\[[0-9;]*m', '', str(raw_error))
    
    # Strip generic prefixes like "ERROR: "
    clean_msg = clean_msg.replace('ERROR:', '').strip()

    # Detect Instagram authentication / cookie requirement
    if 'login required' in clean_msg.lower() or 'cookies' in clean_msg.lower():
        if 'instagram' in clean_msg.lower():
            return "Instagram requires active login credentials or cookies to view this Reel. Public anonymous access is currently blocked by Instagram."
        return "Authentication required by the platform to access this media link."

    # Detect network or DNS resolution failure
    if 'could not resolve host' in clean_msg.lower():
        return "Unable to connect to the video host. Please check your internet connection and try again."

    # Return the cleaned string if no specific rule matched
    return clean_msg


# ==============================================================================
# ROUTE: INDEX / HOME VIEW (GET /)
# ------------------------------------------------------------------------------
# Renders the main user interface template (`index.html`).
# ==============================================================================
@app.route('/')
def index():
    return render_template('index.html')


# ==============================================================================
# ROUTE: USER LOGIN VIEW (GET /login)
# ------------------------------------------------------------------------------
# Renders the authentication interface (`login.html`) connecting to Supabase.
# ==============================================================================
@app.route('/login')
def login():
    return render_template('login.html')


# ==============================================================================
# ROUTE: DOWNLOAD HISTORY VIEW (GET /recent)
# ------------------------------------------------------------------------------
# Renders the user's previously downloaded media library (`recent.html`).
# ==============================================================================
@app.route('/recent')
def recent():
    return render_template('recent.html')


# ==============================================================================
# API ENDPOINT: EXTRACT VIDEO STREAM (POST /api/extract)
# ------------------------------------------------------------------------------
# Receives a JSON payload containing `{ "url": "..." }`, invokes `yt-dlp` to
# inspect the target platform, downloads the high-quality H.264 stream to `/tmp`,
# and returns metadata (title, creator, description, thumbnail, temporary file ID).
# ==============================================================================
@app.route('/api/extract', methods=['POST'])
def extract_video():
    # 1. Parse client JSON request body
    data = request.json or {}
    video_url = data.get('url')

    # Defensive validation: Check for empty or missing URL parameter
    if not video_url:
        return jsonify({"error": "Target URL parameter is missing or malformed."}), 400

    # 2. Generate a Cryptographically Unique Identifier (UUIDv4)
    # Using a UUID prevents filename collisions when multiple users download simultaneously.
    unique_id = str(uuid.uuid4())
    
    # 3. Configure yt-dlp extraction options:
    # - format: Prioritizes AVC / H.264 video codec. This ensures universal playback
    #   on Windows Media Player, QuickTime, iOS, and Android without requiring
    #   paid third-party HEVC extensions.
    # - outtmpl: Directs the output to the temporary writable directory.
    # - noplaylist: Restricts download to the single target video instead of a channel list.
    ydl_opts = {
        'format': 'best[ext=mp4][vcodec^=avc]/best[ext=mp4]/best', 
        'outtmpl': f'{DOWNLOAD_FOLDER}/{unique_id}.%(ext)s', 
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        # Context Manager (`with` statement): Ensures yt-dlp cleans up resources upon completion
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract video metadata and trigger download of the target stream
            info = ydl.extract_info(video_url, download=True)
            
            # If the platform returned a playlist wrapper with 1 entry, unpack the first item
            if 'entries' in info:
                info = info['entries'][0]
                
            # Retrieve the final path of the downloaded file on disk
            filename = ydl.prepare_filename(info)

            # Defensive verification: Ensure file actually exists on the filesystem
            if not os.path.exists(filename):
                return jsonify({"error": "Extraction failed: File vanished after download protocol."}), 500

            # 4. Extract rich metadata for presentation in the frontend UI
            creator = info.get('uploader') or info.get('creator') or "Unknown Creator"
            
            description = info.get('description', 'No descriptive metadata provided by the source.')
            if len(description) > 200:
                description = description[:197] + "..."
                
            thumbnail = info.get('thumbnail', '')
            
            # Sanitize title by removing path separators that could corrupt download headers
            raw_title = info.get('title', 'sv_download')
            clean_title = raw_title.replace('/', '_').replace('\\', '_')

            # 5. Return success payload with HTTP 200 OK
            return jsonify({
                "id": unique_id,
                "title": clean_title,
                "creator": creator,
                "description": description,
                "thumbnail": thumbnail,
                "original_url": video_url
            }), 200
            
    except Exception as e:
        # Sanitize exception message before returning to frontend
        friendly_error = sanitize_error_message(str(e))
        return jsonify({"error": friendly_error}), 500


# ==============================================================================
# API ENDPOINT: STREAM DOWNLOAD FILE (GET /api/download/<file_id>)
# ------------------------------------------------------------------------------
# Streams the temporary MP4 file from `/tmp/downloads` to the user's browser
# as an attachment (`Content-Disposition: attachment`).
# To prevent disk bloat on the server, the file is read into memory (`io.BytesIO`)
# and the disk copy is immediately purged via `os.remove`.
# ==============================================================================
@app.route('/api/download/<file_id>', methods=['GET'])
def download_file(file_id):
    # Retrieve user-friendly title from query parameters (defaults to 'sv_download')
    title = request.args.get('title', 'sv_download')
    expected_path = f"{DOWNLOAD_FOLDER}/{file_id}.mp4"
    
    # Verify file existence on disk
    if os.path.exists(expected_path):
        # Read the binary file bytes into memory
        with open(expected_path, 'rb') as f:
            file_data = io.BytesIO(f.read())
        
        # Immediate server purge: Remove file from disk to avoid storage exhaustion
        os.remove(expected_path)
        
        # Rewind byte stream pointer back to byte 0 before streaming to the client
        file_data.seek(0)
        
        # Send binary stream to client with correct attachment headers and MIME type
        return send_file(
            file_data, 
            as_attachment=True, 
            download_name=f"{title}.mp4",
            mimetype='video/mp4'
        )
    
    # If the file ID doesn't exist or has already been downloaded/purged, return 404
    return jsonify({"error": "File signature not found or session expired."}), 404


# ==============================================================================
# LOCAL DEVELOPMENT ENTRY POINT
# ------------------------------------------------------------------------------
# `if __name__ == '__main__':` ensures this block only executes when `python app.py`
# is run directly, and NOT when imported by a WSGI server (like Gunicorn on Vercel).
# ==============================================================================
if __name__ == '__main__':
    app.run(debug=True, port=5000)