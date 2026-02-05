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

app = Flask(__name__)

# Persistent storage for videos
STORAGE_DIR = "/app/data/videos"
os.makedirs(STORAGE_DIR, exist_ok=True)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "merge-api"})


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
        fb_page_id = data.get("fbPageId")
        fb_page_token = data.get("fbPageToken")
        callback_url = data.get("callbackUrl")
        
        if not all([video_url, google_api_key, fb_page_id, fb_page_token]):
            return jsonify({"error": "Missing required fields"}), 400
        
        def send_status(msg):
            print(msg)
            if callback_url:
                try:
                    requests.post(callback_url, json={"status": msg}, timeout=5)
                except:
                    pass
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Step 1: Resolve XHS URL to direct MP4 URL via XHS-Downloader API
            if "xhs" in video_url or "xiaohongshu" in video_url:
                send_status("🔗 กำลัง resolve XHS link...")
                try:
                    xhs_resp = requests.post(
                        "http://xhs-dl.lslly.com/xhs/detail",
                        json={"url": video_url, "download": False},
                        timeout=30
                    )
                    xhs_data = xhs_resp.json()
                    if xhs_data.get("data") and xhs_data["data"].get("下载地址"):
                        video_url = xhs_data["data"]["下载地址"][0]
                        print(f"Resolved XHS to: {video_url}")
                except Exception as e:
                    print(f"XHS resolve failed: {e}")
            
            # Step 2: Download video
            send_status("📥 กำลังดาวน์โหลดวิดีโอ...")
            video_path = os.path.join(tmpdir, "video.mp4")
            
            # Try direct download first for direct MP4 URLs
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
            
            # Step 2: Upload to Google Files API
            send_status("📤 กำลังอัพโหลดไป Google...")
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
            send_status("🤖 กำลังวิเคราะห์และสร้าง script...")
            target_chars = int(duration * 10)
            prompt = f"""วิเคราะห์วิดีโอนี้และสร้าง script ภาษาไทยสำหรับพากย์เสียง
- วิดีโอยาว {duration:.0f} วินาที
- TTS พูดได้ประมาณ 10 ตัวอักษร/วินาที
- Script ต้องมีประมาณ {target_chars} ตัวอักษร

ตอบเป็น JSON: {{"thai_script": "ข้อความ", "char_count": จำนวน}}"""
            
            script_resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={google_api_key}",
                json={
                    "contents": [{"parts": [
                        {"fileData": {"mimeType": "video/mp4", "fileUri": file_uri}},
                        {"text": prompt}
                    ]}],
                    "generationConfig": {"temperature": 0.8, "maxOutputTokens": 2048}
                },
                timeout=60
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
            
            print(f"Script: {thai_script[:60]}...")
            send_status(f"📝 Script: {thai_script[:50]}...")
            
            # Step 4: Generate TTS
            send_status("🎙️ กำลังสร้างเสียง...")
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
                timeout=60
            )
            tts_result = tts_resp.json()
            audio_base64 = tts_result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("inlineData", {}).get("data", "")
            
            if not audio_base64:
                return jsonify({"error": "TTS generation failed"}), 500
            
            # Step 5: Convert audio & merge
            send_status("🎬 กำลังรวมเสียงกับวิดีโอ...")
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
                return jsonify({"error": f"FFmpeg merge failed: {merge_result.stderr[:200]}"}), 500
            
            # Step 6: Upload to Facebook Reels
            send_status("📤 กำลังโพสลง Facebook Reels...")
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
            fb_upload_url = init_result["upload_url"]
            
            file_size = os.path.getsize(output_path)
            with open(output_path, "rb") as f:
                requests.post(
                    fb_upload_url,
                    headers={
                        "Authorization": f"OAuth {fb_page_token}",
                        "offset": "0",
                        "file_size": str(file_size),
                    },
                    data=f.read(),
                )
            
            publish_resp = requests.post(
                f"https://graph.facebook.com/v21.0/{fb_page_id}/video_reels",
                json={
                    "upload_phase": "finish",
                    "video_id": video_id,
                    "video_state": "PUBLISHED",
                    "description": thai_script[:100] + "...",
                    "access_token": fb_page_token,
                }
            )
            
            if "error" in publish_resp.json():
                return jsonify({"error": f"FB publish failed: {publish_resp.json()['error']['message']}"}), 400
            
            reel_url = f"https://www.facebook.com/reel/{video_id}"
            send_status(f"✅ เสร็จแล้ว! {reel_url}")
            
            return jsonify({
                "success": True,
                "videoId": video_id,
                "reelUrl": reel_url,
                "script": thai_script,
                "originalVideoUrl": public_video_url,
            })
            
    except Exception as e:
        import traceback
        print(f"Error: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)
# Last updated: Thu Feb  5 17:59:11 +07 2026
