#!/usr/bin/env python3
"""
Video-Audio Merge API Service
Runs on CapRover with ffmpeg
"""
import os
import base64
import tempfile
import subprocess
import requests
import uuid
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for Mini App

# Config - ALL FROM ENVIRONMENT VARIABLES ONLY
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GOOGLE_API_KEY = os.environ.get("gemini") or os.environ.get("GOOGLE_API_KEY", "")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")

# Cloudflare R2 Config
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "")

# NOTE: XHS-Downloader API does NOT need cookies - removed

# Persistent storage for videos
STORAGE_DIR = "/app/data/videos"
os.makedirs(STORAGE_DIR, exist_ok=True)

# Logging setup
import logging
from datetime import datetime
from collections import deque

# In-memory log buffer (last 500 entries)
log_buffer = deque(maxlen=500)

class LogHandler(logging.Handler):
    def emit(self, record):
        log_entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "message": self.format(record)
        }
        log_buffer.append(log_entry)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dubbing")
logger.setLevel(logging.DEBUG)
handler = LogHandler()
handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(handler)

# Also print to stdout
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logger.addHandler(console)

def log_info(msg):
    logger.info(msg)
    print(f"[INFO] {msg}")

def log_error(msg):
    logger.error(msg)
    print(f"[ERROR] {msg}")

def log_debug(msg):
    logger.debug(msg)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "merge-api"})

@app.route("/config", methods=["GET"])
def check_config():
    """Check which environment variables are configured (not showing actual values)"""
    config_status = {
        "TELEGRAM_BOT_TOKEN": "✅ SET" if TELEGRAM_BOT_TOKEN else "❌ NOT SET",
        "GOOGLE_API_KEY": "✅ SET" if GOOGLE_API_KEY else "❌ NOT SET",
        "FB_PAGE_ID": "✅ SET" if FB_PAGE_ID else "❌ NOT SET",
        "FB_PAGE_TOKEN": "✅ SET" if FB_PAGE_TOKEN else "❌ NOT SET",
        "R2_ACCOUNT_ID": "✅ SET" if R2_ACCOUNT_ID else "❌ NOT SET",
        "R2_ACCESS_KEY_ID": "✅ SET" if R2_ACCESS_KEY_ID else "❌ NOT SET",
        "R2_SECRET_ACCESS_KEY": "✅ SET" if R2_SECRET_ACCESS_KEY else "❌ NOT SET",
        "R2_BUCKET_NAME": "✅ SET" if R2_BUCKET_NAME else "❌ NOT SET",
        "R2_PUBLIC_URL": "✅ SET" if R2_PUBLIC_URL else "❌ NOT SET",
        # XHS_COOKIE removed - not needed for XHS-Downloader API
    }
    all_set = all("SET" in v for v in config_status.values())
    return jsonify({
        "status": "ready" if all_set else "missing_config",
        "config": config_status
    })

@app.route("/logs", methods=["GET"])
def get_logs():
    """Get recent logs for debugging"""
    limit = request.args.get("limit", 100, type=int)
    level = request.args.get("level", "").upper()
    logs = list(log_buffer)[-limit:]
    if level:
        logs = [l for l in logs if l["level"] == level]
    return jsonify({
        "total": len(log_buffer),
        "showing": len(logs),
        "logs": logs
    })

@app.route("/logs/clear", methods=["POST"])
def clear_logs():
    """Clear log buffer"""
    log_buffer.clear()
    return jsonify({"status": "cleared"})

@app.route("/test-xhs", methods=["GET"])
def test_xhs_api():
    """Test XHS API connectivity from Docker"""
    test_url = request.args.get("url", "http://xhslink.com/o/3U0kR6ucRo2")
    try:
        resp = requests.post(
            "https://xhs-dl.lslly.com/xhs/detail",
            json={"url": test_url, "download": False},
            timeout=60
        )
        log_info(f"[TEST-XHS] Status: {resp.status_code}")
        data = resp.json()
        log_info(f"[TEST-XHS] Response keys: {list(data.keys())}")
        has_video = bool(data.get("data", {}).get("下载地址"))
        return jsonify({
            "status": resp.status_code,
            "has_video": has_video,
            "data_keys": list(data.get("data", {}).keys()) if data.get("data") else None,
            "message": data.get("message", "No message")
        })
    except Exception as e:
        log_error(f"[TEST-XHS] Error: {e}")
        return jsonify({"error": str(e)}), 500


# Gallery endpoints
GALLERY_DIR = "/app/data/gallery"
os.makedirs(GALLERY_DIR, exist_ok=True)

@app.route("/gallery", methods=["GET"])
def list_gallery():
    """List all videos in gallery from R2"""
    import json
    import boto3
    from botocore.config import Config
    
    try:
        r2_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        s3 = boto3.client(
            "s3",
            endpoint_url=r2_url,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto"
        )
        
        # List all .json files in videos/
        response = s3.list_objects_v2(Bucket=R2_BUCKET_NAME, Prefix="videos/")
        videos = []
        
        for obj in response.get("Contents", []):
            if obj["Key"].endswith(".json"):
                # Get metadata
                meta_obj = s3.get_object(Bucket=R2_BUCKET_NAME, Key=obj["Key"])
                metadata = json.loads(meta_obj["Body"].read().decode())
                videos.append(metadata)
        
        # Sort by createdAt descending
        videos.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return jsonify({"videos": videos})
    except Exception as e:
        print(f"[GALLERY] Error: {e}")
        return jsonify({"videos": [], "error": str(e)})

@app.route("/gallery/<video_id>", methods=["GET"])
def get_gallery_video_info(video_id):
    """Get video metadata from R2"""
    import json
    import boto3
    from botocore.config import Config
    
    try:
        r2_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        s3 = boto3.client(
            "s3",
            endpoint_url=r2_url,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto"
        )
        
        meta_obj = s3.get_object(Bucket=R2_BUCKET_NAME, Key=f"videos/{video_id}.json")
        metadata = json.loads(meta_obj["Body"].read().decode())
        return jsonify(metadata)
    except Exception as e:
        return jsonify({"error": "Video not found"}), 404



@app.route("/download", methods=["POST"])
def download_video():
    """
    Download video from URL using yt-dlp and store it
    Returns: public URL to access the video
    """
    try:
        data = request.json
        video_url = data.get("videoUrl")
        
        if not video_url:
            return jsonify({"error": "videoUrl is required"}), 400
        
        video_id = str(uuid.uuid4())[:8]
        video_path = os.path.join(STORAGE_DIR, f"{video_id}.mp4")
        
        # Try yt-dlp first with cookies
        cookies_file = "/app/cookies.txt"
        try:
            yt_dlp_cmd = [
                "yt-dlp", "-f", "best[ext=mp4]/best",
                "-o", video_path,
                "--no-playlist",
                "--quiet",
                video_url
            ]
            if os.path.exists(cookies_file):
                yt_dlp_cmd.insert(1, "--cookies")
                yt_dlp_cmd.insert(2, cookies_file)
            
            dl_result = subprocess.run(yt_dlp_cmd, capture_output=True, text=True, timeout=120)
            
            if dl_result.returncode != 0 or not os.path.exists(video_path):
                raise Exception(f"yt-dlp failed: {dl_result.stderr}")
            print(f"Downloaded with yt-dlp: {video_id}")
        except Exception as e:
            print(f"yt-dlp failed ({e}), trying direct download...")
            resp = requests.get(video_url, headers={"Referer": "https://www.xiaohongshu.com/"}, timeout=120)
            with open(video_path, "wb") as f:
                f.write(resp.content)
        
        video_size = os.path.getsize(video_path) / 1024 / 1024
        public_url = f"http://merge-api.lslly.com/videos/{video_id}.mp4"
        
        return jsonify({
            "success": True,
            "videoId": video_id,
            "videoUrl": public_url,
            "size": f"{video_size:.1f}MB"
        })
    except Exception as e:
        print(f"Download error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/videos/<filename>", methods=["GET"])
def serve_video(filename):
    """Serve stored video files"""
    video_path = os.path.join(STORAGE_DIR, filename)
    if os.path.exists(video_path):
        return send_file(video_path, mimetype="video/mp4")
    return jsonify({"error": "Video not found"}), 404


@app.route("/merge", methods=["POST"])
def merge_audio_video():
    """
    Merge audio with video
    
    Request JSON:
    {
        "videoUrl": "https://...",
        "audioBase64": "base64 encoded PCM audio",
        "audioSampleRate": 24000  # optional, default 24000
    }
    
    Response: merged video file
    """
    try:
        data = request.json
        video_url = data.get("videoUrl")
        audio_base64 = data.get("audioBase64")
        sample_rate = data.get("audioSampleRate", 24000)
        
        if not video_url or not audio_base64:
            return jsonify({"error": "videoUrl and audioBase64 are required"}), 400
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Download video
            video_path = os.path.join(tmpdir, "video.mp4")
            print(f"Downloading video from {video_url[:50]}...")
            resp = requests.get(video_url, timeout=120)
            with open(video_path, "wb") as f:
                f.write(resp.content)
            print(f"Downloaded: {len(resp.content) / 1024 / 1024:.1f} MB")
            
            # Save audio
            raw_audio = os.path.join(tmpdir, "audio.raw")
            wav_audio = os.path.join(tmpdir, "audio.wav")
            audio_bytes = base64.b64decode(audio_base64)
            with open(raw_audio, "wb") as f:
                f.write(audio_bytes)
            print(f"Audio size: {len(audio_bytes) / 1024:.1f} KB")
            
            # Convert to WAV
            subprocess.run([
                "sox", "-r", str(sample_rate), "-e", "signed", "-b", "16", "-c", "1",
                raw_audio, wav_audio
            ], check=True, capture_output=True)
            
            # Merge
            output_path = os.path.join(tmpdir, "output.mp4")
            subprocess.run([
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", wav_audio,
                "-c:v", "copy",
                "-map", "0:v:0",
                "-map", "1:a:0",
                output_path
            ], check=True, capture_output=True)
            
            print("Merge complete!")
            
            # Return file
            return send_file(
                output_path,
                mimetype="video/mp4",
                as_attachment=True,
                download_name="merged.mp4"
            )
            
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/merge-and-upload", methods=["POST"])
def merge_and_upload_to_fb():
    """
    Merge audio with video and upload to Facebook Reels
    
    Request JSON:
    {
        "videoUrl": "https://...",
        "audioBase64": "base64 encoded PCM audio",
        "audioSampleRate": 24000,
        "fbPageId": "page_id",
        "fbPageToken": "access_token",
        "description": "Reel description"
    }
    
    Response: { reelUrl: "https://..." }
    """
    try:
        data = request.json
        video_url = data.get("videoUrl")
        audio_base64 = data.get("audioBase64")
        sample_rate = data.get("audioSampleRate", 24000)
        fb_page_id = data.get("fbPageId")
        fb_page_token = data.get("fbPageToken")
        description = data.get("description", "")
        
        if not all([video_url, audio_base64, fb_page_id, fb_page_token]):
            return jsonify({"error": "Missing required fields"}), 400
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Download video
            video_path = os.path.join(tmpdir, "video.mp4")
            print(f"Downloading video...")
            resp = requests.get(video_url, headers={"Referer": "https://www.xiaohongshu.com/"}, timeout=120)
            with open(video_path, "wb") as f:
                f.write(resp.content)
            print(f"Video: {len(resp.content) / 1024 / 1024:.1f} MB")
            
            # Save and convert audio
            raw_audio = os.path.join(tmpdir, "audio.raw")
            wav_audio = os.path.join(tmpdir, "audio.wav")
            audio_bytes = base64.b64decode(audio_base64)
            with open(raw_audio, "wb") as f:
                f.write(audio_bytes)
            print(f"Audio: {len(audio_bytes) / 1024:.1f} KB")
            
            # Try sox first, fallback to ffmpeg
            try:
                result = subprocess.run([
                    "sox", "-r", str(sample_rate), "-e", "signed", "-b", "16", "-c", "1",
                    raw_audio, wav_audio
                ], check=True, capture_output=True, text=True)
                print("Sox conversion OK")
            except subprocess.CalledProcessError as e:
                print(f"Sox failed: {e.stderr}, trying ffmpeg...")
                # Fallback: use ffmpeg to convert
                subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "s16le", "-ar", str(sample_rate), "-ac", "1",
                    "-i", raw_audio,
                    wav_audio
                ], check=True, capture_output=True)
                print("FFmpeg audio conversion OK")
            
            # Merge
            output_path = os.path.join(tmpdir, "output.mp4")
            merge_result = subprocess.run([
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", wav_audio,
                "-c:v", "copy",
                "-c:a", "aac",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest",
                output_path
            ], capture_output=True, text=True)
            
            if merge_result.returncode != 0:
                print(f"FFmpeg error: {merge_result.stderr}")
                return jsonify({"error": f"FFmpeg failed: {merge_result.stderr[:200]}"}), 500
            
            print("Merge complete!")
            
            # Upload to Facebook Reels
            # Step 1: Init
            init_resp = requests.post(
                f"https://graph.facebook.com/v21.0/{fb_page_id}/video_reels",
                json={
                    "upload_phase": "start",
                    "access_token": fb_page_token,
                }
            )
            init_result = init_resp.json()
            if "error" in init_result:
                return jsonify({"error": f"FB init failed: {init_result['error']['message']}"}), 400
            
            video_id = init_result["video_id"]
            upload_url = init_result["upload_url"]
            
            # Step 2: Upload
            file_size = os.path.getsize(output_path)
            with open(output_path, "rb") as f:
                upload_resp = requests.post(
                    upload_url,
                    headers={
                        "Authorization": f"OAuth {fb_page_token}",
                        "offset": "0",
                        "file_size": str(file_size),
                    },
                    data=f.read(),
                )
            
            # Step 3: Publish
            publish_resp = requests.post(
                f"https://graph.facebook.com/v21.0/{fb_page_id}/video_reels",
                json={
                    "upload_phase": "finish",
                    "video_id": video_id,
                    "video_state": "PUBLISHED",
                    "description": description,
                    "access_token": fb_page_token,
                }
            )
            publish_result = publish_resp.json()
            if "error" in publish_result:
                return jsonify({"error": f"FB publish failed: {publish_result['error']['message']}"}), 400
            
            reel_url = f"https://www.facebook.com/reel/{video_id}"
            
            return jsonify({
                "success": True,
                "videoId": video_id,
                "reelUrl": reel_url,
            })
            
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/full-pipeline", methods=["POST"])
def full_pipeline():
    """
    Full dubbing pipeline: analyze video, generate TTS, merge, upload to FB
    
    Request JSON:
    {
        "videoUrl": "https://...",
        "googleApiKey": "...",
        "fbPageId": "...",
        "fbPageToken": "...",
        "callbackUrl": "..." (optional telegram callback)
    }
    """
    try:
        import json
        import time
        
        data = request.json
        video_url = data.get("videoUrl")
        google_api_key = data.get("googleApiKey")
        callback_url = data.get("callbackUrl")
        status_callback = data.get("statusCallback")  # {chatId, messageId}
        
        if not all([video_url, google_api_key]):
            return jsonify({"error": "Missing required fields"}), 400
        
        print(f"[PIPELINE] Starting for {video_url}")
        print(f"[PIPELINE] Status callback: {status_callback}")
        
        # Status tracking with cumulative display
        steps = {
            "completed": [],  # List of completed step texts
            "current": "",    # Current step text
            "stop": False,
            "dot_count": 0
        }
        
        # Step mapping: short name -> (icon, full text)
        step_map = {
            "วิดีโอ": ("📥", "กำลังดาวน์โหลดวิดีโอ"),
            "วิเคราะห์": ("🔍", "กำลังวิเคราะห์"),
            "เสียง": ("🎙️", "กำลังสร้างเสียง"),
            "รวม": ("🎬", "กำลังรวม"),
            "โพสต์": ("📤", "กำลังโพสต์")
        }
        
        def build_status_text(dot=""):
            lines = []
            # Completed steps: icon + short name + ✅
            for step in steps["completed"]:
                icon, _ = step_map.get(step, ("", ""))
                lines.append(f"{icon} {step} ✅")
            
            # Current step: icon + full text + dots
            if steps["current"]:
                icon, text = step_map.get(steps["current"], ("", steps["current"]))
                lines.append(f"{icon} {text}{dot}")
            
            return "\n".join(lines)
        
        def animate_dots():
            dots = [".", "..", "..."]
            while not steps["stop"]:
                if steps["current"] and status_callback:
                    try:
                        dot = dots[steps["dot_count"] % 3]
                        text = build_status_text(dot)
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText", json={
                            "chat_id": status_callback["chatId"],
                            "message_id": status_callback["messageId"],
                            "text": text,
                            "parse_mode": "HTML"
                        }, timeout=5)
                        steps["dot_count"] += 1
                    except:
                        pass
                time.sleep(0.6)
        
        import threading
        dot_thread = threading.Thread(target=animate_dots, daemon=True)
        dot_thread.start()
        
        def send_status(step_name):
            print(f"Starting step: {step_name}")
            # Move current to completed
            if steps["current"]:
                steps["completed"].append(steps["current"])
            steps["current"] = step_name
            steps["dot_count"] = 0
        
        def complete_step(suffix=""):
            """Complete current step"""
            if steps["current"]:
                steps["completed"].append(steps["current"])
                steps["current"] = ""
                steps["dot_count"] = 0
        
        def finish_status():
            steps["stop"] = True
            if steps["current"]:
                steps["completed"].append(steps["current"])
            steps["current"] = ""
        
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "video.mp4")
            
            # Step 1: Download video
            send_status("วิดีโอ")
            if "xhs" in video_url or "xiaohongshu" in video_url:
                try:
                    import asyncio
                    from pathlib import Path
                    from xhs_downloader import download_xhs_content
                    
                    log_info(f"[PIPELINE] Starting XHS download for: {video_url}")
                    result = asyncio.run(download_xhs_content(video_url, Path(tmpdir)))
                    log_info(f"[PIPELINE] XHS download result type: {type(result)}, value: {result}")
                    
                    if result and not isinstance(result, list):
                        video_path = str(result)
                        log_info(f"[PIPELINE] XHS download success: {video_path}")
                    else:
                        log_error(f"[PIPELINE] No video found in XHS link. Result: {result}")
                        return jsonify({"error": "ไม่พบวิดีโอใน XHS link นี้"}), 400
                except Exception as e:
                    import traceback
                    log_error(f"[PIPELINE] XHS download exception: {e}")
                    log_error(f"[PIPELINE] Traceback: {traceback.format_exc()}")
                    # Fallback to direct download
                    try:
                        log_info(f"[PIPELINE] Trying direct download...")
                        resp = requests.get(video_url, headers={"Referer": "https://www.xiaohongshu.com/"}, timeout=120)
                        with open(video_path, "wb") as f:
                            f.write(resp.content)
                        log_info(f"[PIPELINE] Direct download completed, size: {len(resp.content)} bytes")
                    except Exception as e2:
                        log_error(f"[PIPELINE] Direct download also failed: {e2}")
                        return jsonify({"error": f"Download failed: {e2}"}), 500
            else:
                # Non-XHS: direct download
                try:
                    resp = requests.get(video_url, headers={"Referer": "https://www.xiaohongshu.com/"}, timeout=120)
                    with open(video_path, "wb") as f:
                        f.write(resp.content)
                    print(f"Downloaded video")
                except Exception as e:
                    return jsonify({"error": f"Download failed: {e}"}), 500
            
            video_size = os.path.getsize(video_path) / 1024 / 1024
            print(f"Video: {video_size:.1f} MB")
            
            # Validate it's a real video file
            probe_check = subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                video_path
            ], capture_output=True, text=True)
            
            if "video" not in probe_check.stdout:
                error_msg = f"Downloaded file is not a valid video (got: {probe_check.stdout[:50]})"
                print(error_msg)
                # Check if it's HTML
                with open(video_path, "rb") as f:
                    first_bytes = f.read(200)
                if b"<html" in first_bytes.lower() or b"<!doctype" in first_bytes.lower():
                    return jsonify({"error": "XHS link expired or requires login. Please send direct MP4 URL."}), 400
                return jsonify({"error": error_msg}), 400
            
            # Save original video to persistent storage
            video_id = str(uuid.uuid4())[:8]
            saved_path = os.path.join(STORAGE_DIR, f"{video_id}.mp4")
            import shutil
            shutil.copy(video_path, saved_path)
            public_video_url = f"http://merge-api.lslly.com/videos/{video_id}.mp4"
            print(f"Saved original: {public_video_url}")
            
            # Get video duration
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path
            ], capture_output=True, text=True)
            duration = float(probe.stdout.strip()) if probe.stdout.strip() else 10.0
            print(f"Duration: {duration:.1f}s")
            
            # Complete download step with duration info
            complete_step(f"{duration:.0f} วินาที")
            
            # Step 2: Analyze video with AI
            send_status("วิเคราะห์")
            with open(video_path, "rb") as f:
                video_bytes = f.read()
            
            upload_start = requests.post(
                f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={google_api_key}",
                headers={
                    "X-Goog-Upload-Protocol": "resumable",
                    "X-Goog-Upload-Command": "start",
                    "X-Goog-Upload-Header-Content-Length": str(len(video_bytes)),
                    "X-Goog-Upload-Header-Content-Type": "video/mp4",
                    "Content-Type": "application/json",
                },
                json={"file": {"display_name": "video.mp4"}}
            )
            
            upload_url = upload_start.headers.get("X-Goog-Upload-URL")
            if not upload_url:
                return jsonify({"error": "Failed to get upload URL"}), 500
            
            upload_resp = requests.post(
                upload_url,
                headers={
                    "X-Goog-Upload-Command": "upload, finalize",
                    "X-Goog-Upload-Offset": "0",
                    "Content-Type": "video/mp4",
                },
                data=video_bytes
            )
            upload_result = upload_resp.json()
            file_uri = upload_result.get("file", {}).get("uri")
            file_name = upload_result.get("file", {}).get("name")
            
            # Wait for processing
            for _ in range(30):
                check = requests.get(f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={google_api_key}")
                state = check.json().get("state")
                if state != "PROCESSING":
                    file_uri = check.json().get("uri")
                    break
                time.sleep(2)
            
            # Step 3: Generate script
            target_chars = int(duration * 10)
            min_chars = int(duration * 8)
            gemini_model = os.environ.get("model", "gemini-3-flash-preview")
            prompt = f"""คุณคือ "พี่ต้น" นักรีวิวสินค้าออนไลน์มือฉมัง ที่มีผู้ติดตามหลายล้านคน

ดูวิดีโอสินค้านี้แล้วเขียน script พากย์เสียงภาษาไทย

⚠️ สำคัญมาก: วิดีโอยาว {duration:.0f} วินาที 
- Script ต้องยาว {min_chars}-{target_chars} ตัวอักษร (ภาษาไทยพูดประมาณ 8-10 ตัว/วินาที)
- ถ้า script สั้นกว่านี้ วิดีโอจะถูกตัด!

สไตล์:
- เปิดด้วย "โห้ อันนี้ต้องมี!" หรือ "ของดีมาแล้วครับพี่น้อง!"
- บรรยายจุดเด่นของสินค้าตามที่เห็นในวิดีโอ อธิบายให้ละเอียด
- ใส่ประโยชน์การใช้งาน วิธีใช้ ข้อดี
- ปิดด้วย "สนใจสั่งเลยครับ รีบๆนะ ของมีจำกัด!"

ตอบเป็น JSON: {{"thai_script": "ข้อความพากย์เสียงยาว {min_chars}-{target_chars} ตัวอักษร"}}"""
            
            script_resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={google_api_key}",
                json={
                    "contents": [{"parts": [
                        {"fileData": {"mimeType": "video/mp4", "fileUri": file_uri}},
                        {"text": prompt}
                    ]}],
                    "generationConfig": {"temperature": 0.8, "maxOutputTokens": 4096}
                },
                timeout=180
            )
            script_result = script_resp.json()
            script_text = script_result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            script_text = script_text.replace("```json", "").replace("```", "").strip()
            
            try:
                thai_script = json.loads(script_text).get("thai_script", "")
            except:
                import re
                match = re.search(r'"thai_script":\s*"([^"]+)"', script_text)
                thai_script = match.group(1) if match else script_text[:200]
            
            if not thai_script or len(thai_script) < 10:
                thai_script = "สินค้าคุณภาพดี ราคาประหยัด ใช้งานง่าย ทนทาน คุ้มค่าคุ้มราคา แนะนำเลยครับ"
            
            print(f"Script: {thai_script[:60]}... ({len(thai_script)} chars)")
            
            # Complete analyze step with script info
            complete_step(f"{len(thai_script)} ตัวอักษร")
            send_status("เสียง")
            
            # Step 4: Generate TTS
            tts_resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={google_api_key}",
                json={
                    "contents": [{"parts": [{"text": thai_script}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Puck"}}
                        }
                    }
                },
                timeout=180
            )
            tts_result = tts_resp.json()
            log_info(f"TTS Response status: {tts_resp.status_code}")
            if tts_resp.status_code != 200:
                log_error(f"TTS API Error: {tts_result}")
                log_error(f"TTS Request failed with status {tts_resp.status_code}")
            audio_base64 = tts_result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("inlineData", {}).get("data", "")
            
            if not audio_base64:
                error_msg = tts_result.get("error", {}).get("message", "Unknown error")
                log_error(f"TTS failed - no audio data. Error: {error_msg}")
                log_error(f"Full TTS response: {str(tts_result)[:800]}")
                return jsonify({"error": f"TTS generation failed: {error_msg}"}), 500
            
            # Step 5: Convert audio & merge
            send_status("รวม")
            raw_audio = os.path.join(tmpdir, "audio.raw")
            wav_audio = os.path.join(tmpdir, "audio.wav")
            audio_bytes = base64.b64decode(audio_base64)
            with open(raw_audio, "wb") as f:
                f.write(audio_bytes)
            
            # Convert raw to wav
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "s16le", "-ar", "24000", "-ac", "1",
                "-i", raw_audio,
                wav_audio
            ], check=True, capture_output=True)
            
            # Get audio duration
            audio_probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", wav_audio
            ], capture_output=True, text=True)
            audio_duration = float(audio_probe.stdout.strip()) if audio_probe.stdout.strip() else 0
            
            print(f"=== DURATION CHECK ===")
            print(f"Video duration: {duration:.1f}s")
            print(f"Audio duration: {audio_duration:.1f}s")
            print(f"Script chars: {len(thai_script)}")
            print(f"Expected chars (10/s): {int(duration * 10)}")
            print(f"======================")
            
            # Pad or trim audio to match video duration
            adjusted_audio = os.path.join(tmpdir, "audio_adjusted.wav")
            diff = duration - audio_duration
            print(f"Duration diff: {diff:+.1f}s")
            
            if abs(diff) < 0.5:
                adjusted_audio = wav_audio
            elif diff > 0:
                # Add silence to match video
                subprocess.run([
                    "ffmpeg", "-y", "-i", wav_audio,
                    "-af", f"apad=pad_dur={diff}",
                    adjusted_audio
                ], capture_output=True)
            else:
                # Trim audio
                subprocess.run([
                    "ffmpeg", "-y", "-i", wav_audio,
                    "-t", str(duration),
                    adjusted_audio
                ], capture_output=True)
            
            # Merge with video duration as master
            output_path = os.path.join(tmpdir, "output.mp4")
            merge_result = subprocess.run([
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", adjusted_audio,
                "-c:v", "copy",
                "-c:a", "aac",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-t", str(duration),
                output_path
            ], capture_output=True, text=True)
            
            if merge_result.returncode != 0:
                return jsonify({"error": f"FFmpeg merge failed: {merge_result.stderr[:200]}"}), 500
            
            # Get output video duration
            output_probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", output_path
            ], capture_output=True, text=True)
            output_duration = float(output_probe.stdout.strip()) if output_probe.stdout.strip() else 0
            print(f"Output video duration: {output_duration:.1f}s")
            
            # Step 5: Save to video gallery (skip FB posting)
            complete_step()
            
            # Generate unique video ID
            video_id = str(uuid.uuid4())[:8]
            
            # Upload to Cloudflare R2
            import boto3
            from botocore.config import Config
            
            r2_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
            s3 = boto3.client(
                "s3",
                endpoint_url=r2_url,
                aws_access_key_id=R2_ACCESS_KEY_ID,
                aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                config=Config(signature_version="s3v4"),
                region_name="auto"
            )
            
            # Upload video
            video_key = f"videos/{video_id}.mp4"
            with open(output_path, "rb") as f:
                s3.upload_fileobj(f, R2_BUCKET_NAME, video_key, ExtraArgs={"ContentType": "video/mp4"})
            print(f"[R2] Uploaded video: {video_key}")
            
            # Upload metadata
            import json
            from datetime import datetime
            video_public_url = f"{R2_PUBLIC_URL}/{video_key}"
            metadata = {
                "id": video_id,
                "script": thai_script,
                "duration": output_duration,
                "originalUrl": video_url,
                "createdAt": datetime.now().isoformat(),
                "publicUrl": video_public_url
            }
            meta_key = f"videos/{video_id}.json"
            s3.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=meta_key,
                Body=json.dumps(metadata, ensure_ascii=False),
                ContentType="application/json"
            )
            print(f"[R2] Uploaded metadata: {meta_key}")
            
            video_gallery_url = video_public_url
            steps["stop"] = True  # Stop animation
            
            # Delete status message and send video with button
            if status_callback:
                try:
                    chat_id = status_callback["chatId"]
                    msg_id = status_callback["messageId"]
                    
                    # Delete the status message
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage", json={
                        "chat_id": chat_id,
                        "message_id": msg_id
                    }, timeout=10)
                    
                    # Send video file with button
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo", json={
                        "chat_id": chat_id,
                        "video": video_gallery_url,
                        "reply_markup": {
                            "inline_keyboard": [[
                                {"text": "🎥 เปิดคลัง", "web_app": {"url": "https://dubbing-page.lslly.com"}}
                            ]]
                        }
                    }, timeout=30)
                    print(f"[PIPELINE] Video sent to Telegram")
                except Exception as e:
                    print(f"[PIPELINE] Failed to send Telegram video: {e}")
            
            return jsonify({
                "success": True,
                "videoId": video_id,
                "videoUrl": video_gallery_url,
                "script": thai_script,
                "duration": output_duration,
                "originalVideoUrl": public_video_url,
            })
            
    except Exception as e:
        import traceback
        print(f"Error: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


# ==================== TELEGRAM WEBHOOK ====================
import re
import threading

def send_telegram(chat_id, text, message_id=None):
    """Send or edit Telegram message"""
    if message_id:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText", json={
            "chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"
        })
    else:
        resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "HTML"
        })
        return resp.json().get("result", {}).get("message_id")

def process_video_async(chat_id, video_url):
    """Process video in background - just calls full-pipeline"""
    log_info(f"[TELEGRAM] Starting process for chat={chat_id}, url={video_url}")
    msg_id = send_telegram(chat_id, "📥 กำลังดาวน์โหลดวิดีโอ...")
    
    try:
        # Call full-pipeline with status callback
        data = {
            "videoUrl": video_url,
            "googleApiKey": GOOGLE_API_KEY,
            "fbPageId": FB_PAGE_ID,
            "fbPageToken": FB_PAGE_TOKEN,
            "statusCallback": {"chatId": chat_id, "messageId": msg_id}
        }
        
        log_info(f"[TELEGRAM] Calling full-pipeline for {video_url}")
        log_info(f"[TELEGRAM] API Key set: {bool(GOOGLE_API_KEY)}, FB: {bool(FB_PAGE_TOKEN)}")
        
        resp = requests.post("https://dubbing-api.lslly.com/full-pipeline", json=data, timeout=600)
        log_info(f"[TELEGRAM] Response status: {resp.status_code}")
        result = resp.json()
        log_info(f"[TELEGRAM] Result: {str(result)[:300]}")
        
        if result.get("success"):
            # Success message already sent by full-pipeline
            log_info(f"[TELEGRAM] Pipeline completed successfully")
        else:
            log_error(f"[TELEGRAM] Pipeline failed: {result.get('error', 'Unknown')}")
            send_telegram(chat_id, f"❌ <b>ผิดพลาด</b>\n\n{result.get('error', 'Unknown')[:150]}", msg_id)
                
    except Exception as e:
        import traceback
        log_error(f"[TELEGRAM] Error: {e}\n{traceback.format_exc()}")
        send_telegram(chat_id, f"❌ <b>ผิดพลาด</b>\n\n{str(e)[:150]}", msg_id)


@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    """Handle Telegram webhook"""
    data = request.json
    
    if not data or "message" not in data:
        return "ok"
    
    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    
    # Check for video upload
    if "video" in msg:
        file_id = msg["video"]["file_id"]
        # Get file path from Telegram
        file_info = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}").json()
        if file_info.get("ok"):
            file_path = file_info["result"]["file_path"]
            video_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
            thread = threading.Thread(target=process_video_async, args=(chat_id, video_url))
            thread.start()
        return "ok"
    
    # Check for XHS link
    xhs_match = re.search(r'https?://(xhslink\.com|www\.xiaohongshu\.com)[^\s]+', text)
    
    if xhs_match:
        video_url = xhs_match.group(0)
        thread = threading.Thread(target=process_video_async, args=(chat_id, video_url))
        thread.start()
        
    elif text == "/start":
        send_telegram(chat_id, "👋 สวัสดี! ส่งลิงก์วิดีโอจาก Xiaohongshu หรืออัพโหลดวิดีโอมาเลย")
    
    elif text.strip():
        # Any other text - reject
        send_telegram(chat_id, "❌ รองรับเฉพาะลิงก์ Xiaohongshu หรืออัพโหลดวิดีโอเท่านั้น\n\nตัวอย่าง: http://xhslink.com/...")
    
    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)
# Last updated: Wed Feb  5 20:25:00 +07 2026
