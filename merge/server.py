#!/usr/bin/env python3
"""
Dubbing Container Service — Cloudflare Container
1) FFmpeg merge: video + audio → merged video
2) XHS resolver: XHS URL → direct video URL
"""
import os
import base64
import tempfile
import subprocess
import json
import re
import requests as http_requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


@app.route("/health", methods=["GET"])
def health():
    """Health check — Container class ใช้เช็คว่า container พร้อมรับงาน"""
    # ตรวจว่า ffmpeg ใช้งานได้
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        ffmpeg_ok = result.returncode == 0
    except Exception:
        ffmpeg_ok = False

    return jsonify({
        "status": "ok" if ffmpeg_ok else "error",
        "service": "dubbing-merge-container",
        "ffmpeg": ffmpeg_ok,
    })


@app.route("/merge", methods=["POST"])
def merge():
    """
    รับ video (binary) + audio (base64 PCM) → ffmpeg merge → ส่ง merged video กลับ

    Request: multipart/form-data
      - video: video file (binary)
      - audio_base64: base64 encoded PCM s16le 24kHz mono
      - sample_rate: (optional, default 24000)

    Response: merged video/mp4 binary
    """
    try:
        # รับ video file
        video_file = request.files.get("video")
        audio_base64 = request.form.get("audio_base64")
        sample_rate = int(request.form.get("sample_rate", "24000"))

        if not video_file or not audio_base64:
            return jsonify({"error": "video file and audio_base64 required"}), 400

        with tempfile.TemporaryDirectory() as tmpdir:
            # บันทึก video
            video_path = os.path.join(tmpdir, "video.mp4")
            video_file.save(video_path)

            # ดึง video duration ด้วย ffprobe
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path
            ], capture_output=True, text=True)
            duration = float(probe.stdout.strip()) if probe.stdout.strip() else 10.0

            # Decode audio base64 → raw PCM
            raw_audio = os.path.join(tmpdir, "audio.raw")
            wav_audio = os.path.join(tmpdir, "audio.wav")
            with open(raw_audio, "wb") as f:
                f.write(base64.b64decode(audio_base64))

            # แปลง raw PCM → WAV
            subprocess.run([
                "ffmpeg", "-y", "-f", "s16le", "-ar", str(sample_rate), "-ac", "1",
                "-i", raw_audio, wav_audio
            ], check=True, capture_output=True)

            # ดึง audio duration
            ap = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", wav_audio
            ], capture_output=True, text=True)
            audio_dur = float(ap.stdout.strip()) if ap.stdout.strip() else 0

            # ปรับ audio ให้ตรงกับ video duration
            adjusted = os.path.join(tmpdir, "audio_adj.wav")
            diff = duration - audio_dur
            if abs(diff) < 0.5:
                adjusted = wav_audio
            elif diff > 0:
                # Audio สั้นกว่า video → pad silence
                subprocess.run([
                    "ffmpeg", "-y", "-i", wav_audio,
                    "-af", f"apad=pad_dur={diff}", adjusted
                ], capture_output=True)
            else:
                # Audio ยาวกว่า video → trim
                subprocess.run([
                    "ffmpeg", "-y", "-i", wav_audio,
                    "-t", str(duration), adjusted
                ], capture_output=True)

            # Merge video + audio
            output_path = os.path.join(tmpdir, "output.mp4")
            mr = subprocess.run([
                "ffmpeg", "-y", "-i", video_path, "-i", adjusted,
                "-c:v", "copy", "-c:a", "aac",
                "-map", "0:v:0", "-map", "1:a:0",
                "-t", str(duration), output_path
            ], capture_output=True, text=True)
            if mr.returncode != 0:
                return jsonify({"error": f"FFmpeg merge failed: {mr.stderr[:300]}"}), 500

            # ดึง output duration
            op = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", output_path
            ], capture_output=True, text=True)
            out_dur = float(op.stdout.strip()) if op.stdout.strip() else duration

            # สร้าง thumbnail
            thumb_path = os.path.join(tmpdir, "thumb.webp")
            subprocess.run([
                "ffmpeg", "-y", "-i", output_path, "-vframes", "1", "-ss", "0.1",
                "-vf", "scale=270:480:force_original_aspect_ratio=increase,crop=270:480",
                "-q:v", "80", thumb_path
            ], capture_output=True)

            # อ่าน output video
            with open(output_path, "rb") as f:
                video_bytes = f.read()

            # อ่าน thumbnail (ถ้ามี)
            thumb_bytes = None
            if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
                with open(thumb_path, "rb") as f:
                    thumb_bytes = f.read()

            # ส่งผลลัพธ์เป็น JSON + base64 encoded video/thumb
            result = {
                "success": True,
                "duration": out_dur,
                "video_duration": duration,
                "video_size": len(video_bytes),
                "video_base64": base64.b64encode(video_bytes).decode("ascii"),
            }
            if thumb_bytes:
                result["thumb_base64"] = base64.b64encode(thumb_bytes).decode("ascii")

            return jsonify(result)

    except Exception as e:
        import traceback
        print(f"[MERGE] Error: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


# ==================== XHS Video Resolver ====================

XHS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


@app.route("/xhs/resolve", methods=["POST"])
def xhs_resolve():
    """
    รับ XHS URL → resolve เป็น direct video URL

    Request JSON: {"url": "https://xhslink.com/..."}
    Response JSON: {"video_url": "https://..."} or {"error": "..."}
    """
    try:
        data = request.get_json()
        url = data.get("url", "") if data else ""
        if not url:
            return jsonify({"error": "url required"}), 400

        print(f"[XHS] Resolving: {url}")

        # Follow redirects เพื่อได้ URL จริง
        session = http_requests.Session()
        resp = session.get(url, headers=XHS_HEADERS, allow_redirects=True, timeout=15)
        final_url = resp.url
        html = resp.text
        print(f"[XHS] Final URL: {final_url}")

        # หา video URL จาก HTML
        video_url = None

        # Pattern 1: JSON-LD / embedded data
        json_match = re.search(r'"originVideoKey"\s*:\s*"([^"]+)"', html)
        if json_match:
            key = json_match.group(1)
            video_url = f"https://sns-video-bd.xhscdn.com/{key}"
            print(f"[XHS] Found via originVideoKey: {video_url}")

        # Pattern 2: video src in HTML
        if not video_url:
            video_match = re.search(r'"url"\s*:\s*"(https?://sns-video[^"]+)"', html)
            if video_match:
                video_url = video_match.group(1)
                print(f"[XHS] Found via url pattern: {video_url}")

        # Pattern 3: og:video meta tag
        if not video_url:
            og_match = re.search(r'<meta[^>]*property="og:video"[^>]*content="([^"]+)"', html)
            if og_match:
                video_url = og_match.group(1)
                print(f"[XHS] Found via og:video: {video_url}")

        # Pattern 4: video stream in JSON
        if not video_url:
            stream_match = re.search(r'"masterUrl"\s*:\s*"([^"]+)"', html)
            if stream_match:
                video_url = stream_match.group(1).replace("\\u002F", "/")
                print(f"[XHS] Found via masterUrl: {video_url}")

        if not video_url:
            print(f"[XHS] No video found in HTML (length={len(html)})")
            return jsonify({"error": "ไม่พบวิดีโอใน XHS link นี้"}), 404

        return jsonify({"video_url": video_url})

    except Exception as e:
        import traceback
        print(f"[XHS] Error: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[CONTAINER] Starting dubbing container on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
