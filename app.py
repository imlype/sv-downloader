import os
import io
import uuid
from flask import Flask, render_template, request, send_file, jsonify
import yt_dlp

app = Flask(__name__)

# Vercel strict read-only bypass
DOWNLOAD_FOLDER = '/tmp/downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/recent')
def recent():
    return render_template('recent.html')

@app.route('/api/extract', methods=['POST'])
def extract_video():
    data = request.json
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "Target URL parameter is missing or malformed."}), 400

    unique_id = str(uuid.uuid4())
    ydl_opts = {
        'format': 'best[ext=mp4]/best', 
        'outtmpl': f'{DOWNLOAD_FOLDER}/{unique_id}.%(ext)s', 
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

            if not os.path.exists(filename):
                return jsonify({"error": "Extraction failed: File vanished after download protocol."}), 500

            # Extensive metadata extraction for premium UI display
            creator = info.get('uploader') or info.get('creator') or "Unknown Creator"
            description = info.get('description', 'No descriptive metadata provided by the source.')
            if len(description) > 200:
                description = description[:197] + "..."
                
            thumbnail = info.get('thumbnail', '')
            title = info.get('title', 'sv_download').replace('/', '_').replace('\\', '_')

            return jsonify({
                "id": unique_id,
                "title": title,
                "creator": creator,
                "description": description,
                "thumbnail": thumbnail,
                "original_url": video_url
            })
            
    except Exception as e:
        return jsonify({"error": f"Engine Error: {str(e)}"}), 500

@app.route('/api/download/<file_id>', methods=['GET'])
def download_file(file_id):
    title = request.args.get('title', 'sv_download')
    expected_path = f"{DOWNLOAD_FOLDER}/{file_id}.mp4"
    
    if os.path.exists(expected_path):
        with open(expected_path, 'rb') as f:
            file_data = io.BytesIO(f.read())
        
        # Immediate server purge to prevent memory bloat
        os.remove(expected_path)
        file_data.seek(0)
        
        return send_file(
            file_data, 
            as_attachment=True, 
            download_name=f"{title}.mp4",
            mimetype='video/mp4'
        )
    return jsonify({"error": "File signature not found or session expired."}), 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)