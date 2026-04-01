import os
import io
import uuid
from flask import Flask, render_template, request, send_file, jsonify
import yt_dlp

app = Flask(__name__)

# Ensure clean temp storage
DOWNLOAD_FOLDER = 'downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download_video():
    data = request.json
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "Bruv, paste a link first."}), 400

    # THE FIX: 'best[ext=mp4]/best' forces a single file download. No FFmpeg required.
    unique_id = str(uuid.uuid4())[:8]
    ydl_opts = {
        'format': 'best[ext=mp4]/best', 
        'outtmpl': f'{DOWNLOAD_FOLDER}/{unique_id}_%(title)s.%(ext)s', 
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            
            if 'entries' in info:
                info = info['entries'][0]
                
            filename = ydl.prepare_filename(info)

            if os.path.exists(filename):
                # Buffer to memory so we can delete the file immediately
                with open(filename, 'rb') as f:
                    file_data = io.BytesIO(f.read())
                
                os.remove(filename)
                file_data.seek(0)
                
                # Sanitize the filename for the user
                safe_title = info.get('title', 'social_video').replace('/', '_').replace('\\', '_')
                final_name = f"{safe_title}.mp4"

                return send_file(
                    file_data, 
                    as_attachment=True, 
                    download_name=final_name,
                    mimetype='video/mp4'
                )
            else:
                return jsonify({"error": "File vanished after download."}), 500
            
    except Exception as e:
        # Pass the exact crash reason to the frontend
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)