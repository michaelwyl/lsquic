from flask import Flask, Response, send_file
import subprocess
import os

app = Flask(__name__)

LSQUIC_SERVER = "localhost"
LSQUIC_PORT = 4433
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route('/')
def index():
    return send_file("index_flask.html") 

@app.route('/<filename>')
def stream_video(filename):
    """ Stream video dynamically using LSQUIC """
    video_path = f"/{filename}"
    lsquic_cmd = ["./http_client", "-s", f"{LSQUIC_SERVER}:{LSQUIC_PORT}", "-H", "localhost", "-Q", "h3-29", "-p", video_path]

    try:
        process = subprocess.Popen(lsquic_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def generate():
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break
                yield chunk

        return Response(generate(), mimetype="video/mp4")

    except Exception as e:
        return f"Error fetching video: {str(e)}", 500

if __name__ == '__main__':
    print("🎬 LSQUIC Flask Proxy running at http://localhost:8000")
    app.run(host="0.0.0.0", port=8000)