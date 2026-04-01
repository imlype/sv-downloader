import os
from flask import Flask, render_template, request, send_file, jsonify
import yt_dlp

app = Flask(__name__)

# Create the downloads folder if it doesn't exist
DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download_video():
    data = request.json
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "No URL provided! 🔗"}), 400

    # NEW SETTINGS: This forces the conversion to MP4
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best', # Grab best video and best audio
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s', # Save in downloads folder
        'merge_output_format': 'mp4', # Force the merge into MP4
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4', # Ensure final file is .mp4
        }],
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info and download
            info = ydl.extract_info(video_url, download=True)
            
            # Get the final filename (it might have changed to .mp4 during conversion)
            filename = ydl.prepare_filename(info)
            base, ext = os.path.splitext(filename)
            final_filename = base + ".mp4"

            # Check if the file actually exists before sending
            if os.path.exists(final_filename):
                return send_file(final_filename, as_attachment=True)
            else:
                return jsonify({"error": "File conversion failed! 🛠️"}), 500
            
    except Exception as e:
        print(f"Detailed Error: {e}")
        return jsonify({"error": "Download failed. Make sure the link is public! 🕵️"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)