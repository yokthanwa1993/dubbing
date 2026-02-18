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
import threading
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
    รับ video URL + audio base64 → ffmpeg merge → ส่ง merged video กลับ

    Request JSON:
      - video_url: URL ของ video ให้ container ดาวน์โหลดเอง
      - audio_base64: base64 encoded PCM s16le 24kHz mono
      - sample_rate: (optional, default 24000)

    Response JSON: { video_base64, thumb_base64, duration, ... }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        video_url = data.get("video_url")
        audio_base64 = data.get("audio_base64")
        sample_rate = int(data.get("sample_rate", 24000))

        if not video_url or not audio_base64:
            return jsonify({"error": "video_url and audio_base64 required"}), 400

        with tempfile.TemporaryDirectory() as tmpdir:
            # ดาวน์โหลด video จาก URL
            print(f"[MERGE] Downloading video from: {video_url[:80]}...")
            video_resp = http_requests.get(video_url, timeout=60)
            if video_resp.status_code != 200:
                return jsonify({"error": f"Failed to download video: {video_resp.status_code}"}), 400

            video_path = os.path.join(tmpdir, "video.mp4")
            with open(video_path, "wb") as f:
                f.write(video_resp.content)
            print(f"[MERGE] Downloaded video: {len(video_resp.content) / 1024 / 1024:.1f} MB")

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
    # Desktop UA เพื่อให้ได้ clean URL เหมือน Playwright
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
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

        # Pattern 1: masterUrl (H264 stream - usually clean)
        # มองหา "masterUrl":"http..." ใน JSON
        master_matches = re.finditer(r'"masterUrl"\s*:\s*"([^"]+)"', html)
        for m in master_matches:
            url_cand = m.group(1).replace("\\u002F", "/")
            if "sns-video" in url_cand:
                video_url = url_cand
                print(f"[XHS] Found via masterUrl (Priority): {video_url}")
                break

        # Pattern 2: originVideoKey (Backup)
        if not video_url:
            json_match = re.search(r'"originVideoKey"\s*:\s*"([^"]+)"', html)
            if json_match:
                key = json_match.group(1)
                video_url = f"https://sns-video-bd.xhscdn.com/{key}"
                print(f"[XHS] Found via originVideoKey: {video_url}")

        # Pattern 3: video src / url
        if not video_url:
            video_match = re.search(r'"url"\s*:\s*"(https?://sns-video[^"]+)"', html)
            if video_match:
                video_url = video_match.group(1).replace("\\u002F", "/")
                print(f"[XHS] Found via url pattern: {video_url}")

        if not video_url:
            print(f"[XHS] No video found in HTML (length={len(html)})")
            return jsonify({"error": "ไม่พบวิดีโอใน XHS link นี้"}), 404

        return jsonify({"video_url": video_url})

    except Exception as e:
        import traceback
        print(f"[XHS] Error: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500




# ==================== Full Pipeline (async background) ====================

def send_telegram(token, method, payload):
    url = f"https://api.telegram.org/bot{token}/{method}"
    resp = http_requests.post(url, json=payload, timeout=30)
    return resp.json()

def edit_status(token, chat_id, msg_id, text):
    send_telegram(token, "editMessageText", {
        "chat_id": chat_id,
        "message_id": msg_id,
        "text": text,
        "parse_mode": "HTML",
    })

class DotAnimator:
    """Animate จุดท้ายข้อความ . → .. → ... วนเป็นรอบ ทุก 1.5 วินาที"""
    def __init__(self, token, chat_id, msg_id):
        self.token = token
        self.chat_id = chat_id
        self.msg_id = msg_id
        self._base_text = ""
        self._stop = threading.Event()
        self._thread = None

    def start(self, base_text):
        """เริ่ม animate — base_text ควรลงท้ายด้วยข้อความ step ปัจจุบัน (ไม่ต้องใส่จุด)"""
        self.stop()
        self._base_text = base_text
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        dots = [".", "..", "..."]
        i = 0
        while not self._stop.is_set():
            text = self._base_text + dots[i % 3]
            try:
                edit_status(self.token, self.chat_id, self.msg_id, text)
            except:
                pass
            i += 1
            self._stop.wait(1.5)

    def stop(self):
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=3)

def run_pipeline_bg(payload):
    """รัน full pipeline ใน background thread — ไม่มี time limit"""
    token = payload["token"]
    video_url = payload["video_url"]
    chat_id = payload["chat_id"]
    msg_id = payload["msg_id"]
    api_key = payload["api_key"]
    model = payload.get("model", "gemini-2.0-flash")
    r2_public_url = payload["r2_public_url"]
    worker_url = payload["worker_url"]

    import uuid, time
    video_id = uuid.uuid4().hex[:8]

    anim = DotAnimator(token, chat_id, msg_id)

    try:
        # ── Step 1: ดาวน์โหลดวิดีโอ ──
        anim.start("📥 กำลังดาวน์โหลดวิดีโอ")

        print(f"[PIPELINE] Downloading: {video_url[:80]}")
        vr = http_requests.get(video_url, timeout=120)
        if vr.status_code != 200:
            raise Exception(f"Download failed: {vr.status_code}")
        video_bytes = vr.content
        print(f"[PIPELINE] Downloaded: {len(video_bytes)/1024/1024:.1f} MB")

        # อัพโหลด original ไป R2 ผ่าน Worker proxy
        _r2_put(worker_url, token,
                f"videos/{video_id}_original.mp4", video_bytes, "video/mp4")

        # ── Step 2: Gemini upload + analyze ──
        anim.start("📥 ดาวน์โหลดวิดีโอ ✅\n🔍 กำลังวิเคราะห์วิดีโอ")

        gemini_uri = _gemini_upload(video_bytes, api_key)
        gemini_uri = _gemini_wait(gemini_uri, api_key)

        script, title, category = _gemini_script(gemini_uri, api_key, model)
        print(f"[PIPELINE] Script ({len(script)} chars): {script[:60]}")

        # ── Step 3: TTS ──
        anim.start("📥 ดาวน์โหลดวิดีโอ ✅\n🔍 วิเคราะห์วิดีโอ ✅\n🎙 กำลังสร้างเสียงพากย์")

        audio_b64 = _gemini_tts(script, api_key)
        print(f"[PIPELINE] TTS: {len(audio_b64)//1024} KB base64")

        # ── Step 4: FFmpeg merge ──
        anim.start("📥 ดาวน์โหลดวิดีโอ ✅\n🔍 วิเคราะห์วิดีโอ ✅\n🎙 สร้างเสียงพากย์ ✅\n🎬 กำลังรวมวิดีโอ")

        original_url = f"{r2_public_url}/videos/{video_id}_original.mp4"
        merged_bytes, thumb_bytes, duration = _ffmpeg_merge(original_url, audio_b64)
        print(f"[PIPELINE] Merged: {len(merged_bytes)/1024/1024:.1f} MB, {duration:.1f}s")

        # ── Step 5: อัพโหลด ──

        _r2_put(worker_url, token,
                f"videos/{video_id}.mp4", merged_bytes, "video/mp4")
        public_url = f"{r2_public_url}/videos/{video_id}.mp4"

        thumb_url = ""
        if thumb_bytes:
            _r2_put(worker_url, token,
                    f"videos/{video_id}_thumb.webp", thumb_bytes, "image/webp")
            thumb_url = f"{r2_public_url}/videos/{video_id}_thumb.webp"

        # ── Step 6: บันทึก metadata + pending shopee ──
        import datetime
        metadata = {
            "id": video_id, "script": script, "title": title,
            "category": category, "duration": duration,
            "originalUrl": video_url, "publicUrl": public_url,
            "thumbnailUrl": thumb_url,
            "createdAt": datetime.datetime.utcnow().isoformat() + "Z",
        }
        _r2_put(worker_url, token,
                f"videos/{video_id}.json",
                json.dumps(metadata, ensure_ascii=False).encode(), "application/json")

        pending = {"videoId": video_id, "publicUrl": public_url, "msgId": msg_id}
        _r2_put(worker_url, token,
                f"_pending_shopee/{chat_id}.json",
                json.dumps(pending).encode(), "application/json")

        # ── Step 7: เสร็จ! ──
        anim.stop()
        edit_status(token, chat_id, msg_id,
            "📥 ดาวน์โหลดวิดีโอ ✅\n🔍 วิเคราะห์วิดีโอ ✅\n🎙 สร้างเสียงพากย์ ✅\n🎬 รวมวิดีโอ ✅")

        send_telegram(token, "sendVideo", {
            "chat_id": chat_id,
            "video": public_url,
            "caption": "🛒 ส่งลิงก์ Shopee มาเลย",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "🎥 เปิดคลัง", "web_app": {"url": "https://dubbing-webapp.pages.dev?tab=gallery"}}
                ]]
            }
        })

        print(f"[PIPELINE] Done! videoId={video_id}")

    except Exception as e:
        anim.stop()
        import traceback
        print(f"[PIPELINE] Error: {e}\n{traceback.format_exc()}")
        send_telegram(token, "editMessageText", {
            "chat_id": chat_id,
            "message_id": msg_id,
            "text": f"❌ ผิดพลาด\n\n{str(e)[:150]}",
        })


def _r2_put(worker_url, token, key, data, content_type):
    """อัพโหลดไฟล์ไป R2 ผ่าน Worker /api/r2-upload proxy"""
    url = f"{worker_url}/api/r2-upload/{key}"
    resp = http_requests.put(url, data=data, headers={
        "x-auth-token": token,
        "content-type": content_type,
    }, timeout=120)
    if resp.status_code not in (200, 201):
        raise Exception(f"R2 upload failed: {resp.status_code} {resp.text[:200]}")


def _gemini_upload(video_bytes, api_key):
    """Upload video ไป Gemini Files API"""
    resp = http_requests.post(
        f"https://generativelanguage.googleapis.com/upload/v1beta/files?uploadType=media&key={api_key}",
        data=video_bytes,
        headers={"Content-Type": "video/mp4", "X-Goog-Upload-Protocol": "raw"},
        timeout=120,
    )
    data = resp.json()
    return data["file"]["uri"]


def _gemini_wait(file_uri, api_key, max_wait=120):
    """รอให้ Gemini ประมวลผลวิดีโอเสร็จ"""
    import time
    file_name = file_uri.split("/files/")[-1]
    for _ in range(max_wait // 5):
        r = http_requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/files/{file_name}?key={api_key}",
            timeout=15
        ).json()
        if r.get("state") == "ACTIVE":
            return file_uri
        time.sleep(5)
    return file_uri


def _gemini_script(file_uri, api_key, model):
    """สร้าง script ภาษาไทยจากวิดีโอ"""
    prompt = """วิเคราะห์วิดีโอสินค้านี้และสร้าง script พากย์เสียงภาษาไทยสำหรับ Facebook Reels
ตอบเป็น JSON เท่านั้น:
{
  "thai_script": "script ภาษาไทย 150-250 ตัวอักษร น่าสนใจ ชวนซื้อ",
  "title": "ชื่อสินค้าภาษาไทย",
  "category": "หมวดหมู่ (เครื่องใช้ไฟฟ้า/ของใช้ในบ้าน/เสื้อผ้า/อาหาร/ความงาม/เครื่องมือช่าง/อื่นๆ)"
}"""

    resp = http_requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        json={"contents": [{"parts": [
            {"file_data": {"mime_type": "video/mp4", "file_uri": file_uri}},
            {"text": prompt}
        ]}]},
        timeout=60,
    ).json()

    if resp.get("error"):
        raise Exception(f"Gemini error: {resp['error'].get('message')}")

    text = resp.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    text = text.replace("```json", "").replace("```", "").strip()
    print(f"[PIPELINE] Gemini raw: {text[:100]}")

    try:
        parsed = json.loads(text)
        return parsed.get("thai_script", ""), parsed.get("title", ""), parsed.get("category", "อื่นๆ")
    except:
        m = re.search(r'"thai_script"\s*:\s*"([^"]+)"', text)
        t = re.search(r'"title"\s*:\s*"([^"]+)"', text)
        c = re.search(r'"category"\s*:\s*"([^"]+)"', text)
        return (m.group(1) if m else text[:200]), (t.group(1) if t else ""), (c.group(1) if c else "อื่นๆ")


def _gemini_tts(script, api_key):
    """สร้างเสียงพากย์จาก script"""
    resp = http_requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={api_key}",
        json={
            "contents": [{"parts": [{"text": script}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}}
            }
        },
        timeout=60,
    ).json()

    if resp.get("error"):
        raise Exception(f"TTS error: {resp['error'].get('message')}")

    return resp["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]


def _ffmpeg_merge(video_url, audio_b64):
    """FFmpeg merge — เหมือน /merge endpoint เดิม แต่ return bytes"""
    with tempfile.TemporaryDirectory() as tmpdir:
        vr = http_requests.get(video_url, timeout=120)
        video_path = os.path.join(tmpdir, "video.mp4")
        with open(video_path, "wb") as f:
            f.write(vr.content)

        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ], capture_output=True, text=True)
        duration = float(probe.stdout.strip()) if probe.stdout.strip() else 15.0

        raw_audio = os.path.join(tmpdir, "audio.raw")
        wav_audio = os.path.join(tmpdir, "audio.wav")
        with open(raw_audio, "wb") as f:
            f.write(base64.b64decode(audio_b64))
        subprocess.run(["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
                        "-i", raw_audio, wav_audio], check=True, capture_output=True)

        ap = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", wav_audio
        ], capture_output=True, text=True)
        audio_dur = float(ap.stdout.strip()) if ap.stdout.strip() else 0

        adjusted = os.path.join(tmpdir, "audio_adj.wav")
        diff = duration - audio_dur
        if abs(diff) < 0.5:
            adjusted = wav_audio
        elif diff > 0:
            subprocess.run(["ffmpeg", "-y", "-i", wav_audio, "-af", f"apad=pad_dur={diff}", adjusted], capture_output=True)
        else:
            subprocess.run(["ffmpeg", "-y", "-i", wav_audio, "-t", str(duration), adjusted], capture_output=True)

        output_path = os.path.join(tmpdir, "output.mp4")
        mr = subprocess.run([
            "ffmpeg", "-y", "-i", video_path, "-i", adjusted,
            "-c:v", "copy", "-c:a", "aac",
            "-map", "0:v:0", "-map", "1:a:0", "-t", str(duration), output_path
        ], capture_output=True, text=True)
        if mr.returncode != 0:
            raise Exception(f"FFmpeg failed: {mr.stderr[:300]}")

        op = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", output_path
        ], capture_output=True, text=True)
        out_dur = float(op.stdout.strip()) if op.stdout.strip() else duration

        thumb_path = os.path.join(tmpdir, "thumb.webp")
        subprocess.run([
            "ffmpeg", "-y", "-i", output_path, "-vframes", "1", "-ss", "0.1",
            "-vf", "scale=270:480:force_original_aspect_ratio=increase,crop=270:480",
            "-q:v", "80", thumb_path
        ], capture_output=True)

        with open(output_path, "rb") as f:
            merged = f.read()
        thumb = None
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            with open(thumb_path, "rb") as f:
                thumb = f.read()

        return merged, thumb, out_dur


@app.route("/pipeline", methods=["POST"])
def pipeline():
    """
    รับงาน pipeline จาก Worker → รัน background thread → return ทันที
    Worker ไม่ต้องรอ ไม่ติด time limit
    """
    data = request.get_json()
    if not data or not data.get("token"):
        return jsonify({"error": "token required"}), 400

    t = threading.Thread(target=run_pipeline_bg, args=(data,), daemon=True)
    t.start()
    print(f"[PIPELINE] Started background thread for chat_id={data.get('chat_id')}")
    return jsonify({"status": "started"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[CONTAINER] Starting dubbing container on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
