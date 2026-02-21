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
    if not msg_id:
        return
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
        if not self.msg_id:
            return
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
    video_id = payload.get("video_id") or uuid.uuid4().hex[:8]

    def _update_step(step, step_name):
        """อัปเดตสถานะ step ใน R2 _processing queue"""
        try:
            url = f"{worker_url}/api/r2-proxy/_processing/{video_id}.json"
            get_req = http_requests.get(url, headers={'x-auth-token': token}, timeout=10)
            if get_req.status_code == 200:
                data = get_req.json()
            else:
                data = {"id": video_id, "status": "processing", "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
            data["step"] = step
            data["stepName"] = step_name
            data["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            _r2_put(worker_url, token, f"_processing/{video_id}.json", json.dumps(data).encode(), "application/json")
        except Exception as e:
            print(f"[PIPELINE] Step update error: {e}")

    anim = DotAnimator(token, chat_id, msg_id)

    try:
        # ── Step 1: ดาวน์โหลดวิดีโอ ──
        _update_step(1, "📥 ดาวน์โหลดวิดีโอ")
        anim.start("📥 กำลังดาวน์โหลดวิดีโอ")

        print(f"[PIPELINE] Downloading: {video_url[:80]}")
        vr = http_requests.get(video_url, stream=True, timeout=120)
        if vr.status_code != 200:
            raise Exception(f"Download failed: {vr.status_code}")
        
        total_size = int(vr.headers.get('content-length', 0))
        video_bytes = bytearray()
        last_pct = 0
        for chunk in vr.iter_content(chunk_size=1024*1024):
            if chunk:
                video_bytes.extend(chunk)
                if total_size > 0:
                    pct = len(video_bytes) / total_size
                    # Only update every 10% or strictly to reduce R2 spam
                    if pct - last_pct > 0.1 or pct == 1.0:
                        _update_step(1.0 + (pct * 0.9), f"📥 กำลังดาวน์โหลดวิดีโอ... ({len(video_bytes)/1024/1024:.1f}MB)")
                        last_pct = pct

        video_bytes = bytes(video_bytes)
        print(f"[PIPELINE] Downloaded: {len(video_bytes)/1024/1024:.1f} MB")

        # อัพโหลด original ไป R2 ผ่าน Worker proxy
        _r2_put(worker_url, token,
                f"videos/{video_id}_original.mp4", video_bytes, "video/mp4")

        # ── Step 2: Gemini upload + analyze ──
        _update_step(2, "🔍 อัปโหลดวิดีโอไป Gemini...")
        anim.start("📥 ดาวน์โหลดวิดีโอ ✅\n🔍 กำลังวิเคราะห์วิดีโอ")

        gemini_uri = _gemini_upload(video_bytes, api_key)
        _update_step(2.3, "🔍 รอ Gemini ประมวลผลวิดีโอ...")
        gemini_uri = _gemini_wait(gemini_uri, api_key)

        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(video_bytes)
            tmp_video_path = tf.name
            
        try:
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", tmp_video_path
            ], capture_output=True, text=True)
            duration = float(probe.stdout.strip()) if probe.stdout.strip() else 15.0
        except Exception as e:
            print(f"[PIPELINE] Error getting duration: {e}")
            duration = 15.0
        finally:
            os.remove(tmp_video_path)

        _update_step(2.7, "🔍 สร้างบทพากย์จาก AI...")
        script, title, category = _gemini_script(gemini_uri, api_key, model, duration)
        print(f"[PIPELINE] Script ({len(script)} chars): {script[:60]}")

        # ── Step 3: TTS ──
        _update_step(3, "🎙 กำลังสร้างเสียงพากย์ไทย...")
        anim.start("📥 ดาวน์โหลดวิดีโอ ✅\n🔍 วิเคราะห์วิดีโอ ✅\n🎙 กำลังสร้างเสียงพากย์")

        audio_b64 = _gemini_tts(script, api_key)
        _update_step(3.5, "🎙 ได้เสียงพากย์แล้ว กำลังเตรียมรวม...")
        print(f"[PIPELINE] TTS: {len(audio_b64)//1024} KB base64")

        # ── Step 4: FFmpeg merge ──
        _update_step(4, "🎬 กำลังรวมเสียง+วิดีโอ...")
        anim.start("📥 ดาวน์โหลดวิดีโอ ✅\n🔍 วิเคราะห์วิดีโอ ✅\n🎙 สร้างเสียงพากย์ ✅\n🎬 กำลังรวมวิดีโอ")

        original_url = f"{r2_public_url}/videos/{video_id}_original.mp4"

        def update_progress(text, step_num=None):
            try:
                import datetime
                url_get = f"{worker_url}/api/r2-proxy/_processing/{video_id}.json"
                req = http_requests.get(url_get, headers={'x-auth-token': token}, timeout=5)
                if req.status_code == 200:
                    data = req.json()
                    data["stepName"] = text
                    if step_num:
                        data["step"] = step_num
                    data["updatedAt"] = datetime.datetime.utcnow().isoformat() + "Z"
                    _r2_put(worker_url, token, f"_processing/{video_id}.json", json.dumps(data).encode(), "application/json")
            except:
                pass

        merged_bytes, thumb_bytes, duration = _ffmpeg_merge(original_url, audio_b64, script, api_key, progress_cb=update_progress)
        print(f"[PIPELINE] Merged: {len(merged_bytes)/1024/1024:.1f} MB, {duration:.1f}s")

        # ── Step 5: อัพโหลด ──
        _update_step(5, "📤 อัพโหลดผลลัพธ์")

        _r2_put(worker_url, token,
                f"videos/{video_id}.mp4", merged_bytes, "video/mp4")
        public_url = f"{r2_public_url}/videos/{video_id}.mp4"

        thumb_url = ""
        if thumb_bytes:
            _r2_put(worker_url, token,
                    f"videos/{video_id}_thumb.webp", thumb_bytes, "image/webp")
            thumb_url = f"{r2_public_url}/videos/{video_id}_thumb.webp"

        # ── Step 6: เช็คลิงก์ Shopee ที่รออยู่ และบันทึก metadata ──
        import datetime
        shopee_link_data = None
        try:
            get_req = http_requests.get(f"{worker_url}/api/r2-proxy/_waiting_shopee/{chat_id}.json", headers={'x-auth-token': token}, timeout=15)
            if get_req.status_code == 200:
                shopee_link_data = get_req.json().get("shopeeLink")
                # ลบทิ้งทันทีหลังใช้
                http_requests.delete(f"{worker_url}/api/r2-proxy/_waiting_shopee/{chat_id}.json", headers={'x-auth-token': token}, timeout=15)
        except Exception as e:
            print(f"[PIPELINE] Error fetching waiting shopee: {e}")

        metadata = {
            "id": video_id, "script": script, "title": title,
            "category": category, "duration": duration,
            "originalUrl": video_url, "publicUrl": public_url,
            "thumbnailUrl": thumb_url,
            "chatId": chat_id,
            "createdAt": datetime.datetime.utcnow().isoformat() + "Z",
        }
        if shopee_link_data:
            metadata["shopeeLink"] = shopee_link_data

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
            "📥 รับวิดีโอ ✅\n🔍 วิเคราะห์วิดีโอ ✅\n🎙 สร้างเสียงพากย์ ✅\n🎬 รวมวิดีโอ ✅")




        send_telegram(token, "sendMessage", {
            "chat_id": chat_id,
            "text": "✅ สร้างวิดีโอสำเร็จ! ดูได้ที่คลังวิดีโอ",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "🎥 เปิดคลังวิดีโอ", "web_app": {"url": "https://dubbing-chearb-webapp.pages.dev?tab=gallery"}}
                ]]
            }
        })

        # ลบ queue _processing
        try:
            http_requests.delete(f"{worker_url}/api/r2-proxy/_processing/{video_id}.json", headers={'x-auth-token': token}, timeout=15)
        except Exception as e:
            print(f"[PIPELINE] Error deleting processing state: {e}")

        # อัปเดต Gallery cache เพื่อให้วิดีโอใหม่โผล่ทันที
        try:
            http_requests.post(f"{worker_url}/api/gallery/refresh/{video_id}", headers={'x-auth-token': token}, timeout=15)
            print(f"[PIPELINE] Gallery cache refreshed for {video_id}")
        except Exception as e:
            print(f"[PIPELINE] Gallery refresh error: {e}")

        print(f"[PIPELINE] Done! videoId={video_id}")

    except Exception as e:
        if anim:
            anim.stop()
        import traceback
        print(f"[PIPELINE] Error: {e}\n{traceback.format_exc()}")
        if msg_id:
            send_telegram(token, "editMessageText", {
                "chat_id": chat_id,
                "message_id": msg_id,
                "text": f"❌ ผิดพลาด\n\n{str(e)[:150]}",
            })
        else:
            send_telegram(token, "sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ ระบบขัดข้องระหว่างสร้างวิดีโอพากย์เสียง\n\n{str(e)[:150]}",
            })

        # อัปเดตสถานะเป็น failed ในคิวแทนการลบ
        try:
            url = f"{worker_url}/api/r2-proxy/_processing/{video_id}.json"
            get_req = http_requests.get(url, headers={'x-auth-token': token}, timeout=15)
            if get_req.status_code == 200:
                data = get_req.json()
                data["status"] = "failed"
                data["error"] = str(e)[:200]
                _r2_put(worker_url, token, f"_processing/{video_id}.json", json.dumps(data).encode(), "application/json")
        except Exception as e2:
            print(f"[PIPELINE] Error updating failed status: {e2}")

        # ไม่ว่าจะ fail ก็ให้เช็คคิวถัดไป
        try:
            http_requests.post(f"{worker_url}/api/queue/next", headers={'x-auth-token': token}, timeout=15)
        except Exception as e3:
            print(f"[PIPELINE] Queue next error: {e3}")



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


def _gemini_script(file_uri, api_key, model, video_duration=15.0):
    """สร้าง script ภาษาไทยจากวิดีโอ — ปรับความยาว script ตามความยาววิดีโอ"""
    # คำนวณความยาว script ที่เหมาะสม (~10 ตัวอักษร/วินาที สำหรับภาษาไทย TTS)
    max_chars = min(int(video_duration * 10), 800)
    min_chars = max(int(video_duration * 7), 80)

    prompt = f"""คุณคือ "เฉียบ" สาวสองนักรีวิวสินค้าสุดแซ่บ พูดจากวนตีน จี๊ดจ๊าด ดราม่าเว่อร์ ชอบแซวคนดู ปากจัดแต่น่ารัก

ดูวิดีโอสินค้านี้แล้วสร้าง script พากย์เสียงสำหรับ Facebook Reels

⏱️ สำคัญมาก: วิดีโอนี้ยาว {video_duration:.1f} วินาที เท่านั้น! Script ต้องบรรยายยาวไปจนจบวิดีโอ!

สไตล์ "เฉียบ":
- เปิดด้วยประโยคจี๊ดๆ เช่น "แม่จ๋าา ของดีมาแล้วค่า!" / "อี๋ย ใครยังไม่มีอันนี้ เชยระเบิดเลยนะคะ!" / "ตายแล้วค่ะ ของมันต้องมี!"
- พูดแบบสาวสองเต็มตัว ใช้คำว่า "ค่ะ" "จ๊ะ" "นะคะ" "แม่" "ตัวเอง" เยอะๆ ดราม่านิดๆ โอเวอร์หน่อยๆ
- แซวคนดูแบบน่ารัก เช่น "ยังใช้ของเดิมอยู่เหรอจ๊ะ น่าสงสารตัวเอง!" / "ใช้แล้วสวยขึ้น ไม่ได้พูดเล่นนะคะ!"
- บรรยายจุดเด่นสินค้าจริงจากวิดีโอ แต่ใส่อารมณ์โอเวอร์ เช่น "โอ้โห เห็นปุ๊บหัวใจแม่สั่นเลยค่ะ!" / "ดีจนอยากกรี๊ดดดด!"
- ปิดด้วยทิ้งท้ายจี๊ดๆ เช่น "กดซื้อเลยค่ะ ไม่งั้นแม่จะโกรธ!" / "ไม่ซื้อก็ได้ค่ะ แต่อย่ามาร้องไห้ตอนของหมดนะจ๊ะ 555!" / "ลิงก์ข้างล่างจ้า แม่จัดให้แล้ว!"

⚠️ ข้อห้าม: ห้ามพูด "สวัสดี" ห้ามเรียบๆ น่าเบื่อ ต้องจี๊ดจ๊าดตั้งแต่คำแรก! กระชับแต่แซ่บ!

⚠️ ความยาว: Script ต้องยาว {min_chars}-{max_chars} ตัวอักษรเท่านั้น สำคัญมาก! ห้ามสั้นเกินไปเพราะวิดีโอยาวตั้ง {video_duration:.0f} วินาที

ตอบเป็น JSON เท่านั้น:
{{
  "thai_script": "script ภาษาไทยสไตล์สาวสองกวนๆ {min_chars}-{max_chars} ตัวอักษร จี๊ดจ๊าดชวนซื้อ",
  "title": "แคปชั่นสั้นแซ่บๆ ดึงดูดคนกด",
  "category": "หมวดหมู่ (เครื่องมือช่าง/อาหาร/เครื่องครัว/ของใช้ในบ้าน/เฟอร์นิเจอร์/บิวตี้/แฟชั่น/อิเล็กทรอนิกส์/สุขภาพ/กีฬา/สัตว์เลี้ยง/ยานยนต์/อื่นๆ)"
}}"""

    import time
    for attempt in range(5):
        try:
            resp = http_requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                json={"contents": [{"parts": [
                    {"file_data": {"mime_type": "video/mp4", "file_uri": file_uri}},
                    {"text": prompt}
                ]}]},
                timeout=60,
            ).json()

            if resp.get("error"):
                err_msg = resp['error'].get('message', '')
                if "high demand" in err_msg.lower() or "503" in str(err_msg):
                    print(f"[PIPELINE] Gemini high demand, retrying... ({attempt+1}/5)")
                    time.sleep(5)
                    if attempt >= 2 and model == "gemini-3-flash-preview":
                        model = "gemini-2.0-flash"
                        print(f"[PIPELINE] Fallback to {model}")
                    continue
                raise Exception(f"Gemini error: {err_msg}")
            break
        except Exception as e:
            if attempt < 4 and "Gemini error" not in str(e):
                time.sleep(5)
                continue
            raise

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
    import time
    for attempt in range(5):
        try:
            resp = http_requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={api_key}",
                json={
                    "contents": [{"parts": [{"text": script}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Puck"}}}
                    }
                },
                timeout=60,
            ).json()

            if resp.get("error"):
                err_msg = resp['error'].get('message', '')
                if "high demand" in err_msg.lower() or "503" in str(err_msg):
                    print(f"[PIPELINE] TTS high demand, retrying... ({attempt+1}/5)")
                    time.sleep(5)
                    continue
                raise Exception(f"TTS error: {err_msg}")
            
            return resp["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        except Exception as e:
            if attempt < 4 and "TTS error" not in str(e):
                time.sleep(5)
                continue
            raise

    return resp["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]


def _ffmpeg_merge(video_url, audio_b64, script=None, api_key=None, progress_cb=None):
    """FFmpeg merge — เหมือน /merge endpoint เดิม แต่มีการใส่ซับด้วย Whisper + Gemini + MoviePy"""
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

        merged_nosub = os.path.join(tmpdir, "merged_nosub.mp4")
        mr = subprocess.run([
            "ffmpeg", "-y", "-i", video_path, "-i", adjusted,
            "-c:v", "copy", "-c:a", "aac",
            "-map", "0:v:0", "-map", "1:a:0", "-t", str(duration), merged_nosub
        ], capture_output=True, text=True)
        if mr.returncode != 0:
            raise Exception(f"FFmpeg failed: {mr.stderr[:300]}")
            
        output_path = os.path.join(tmpdir, "output.mp4")
        
        if script and api_key:
            if progress_cb:
                progress_cb("📝 กำลังวิเคราะห์และแกะเวลาเสียงพูด (Word Sync)...", 4.3)
                
            print("[PIPELINE] Transcribing with Whisper (Turbo model)...")
            try:
                subprocess.run([
                    "whisper-ctranslate2", adjusted,
                    "--model", "turbo",
                    "--language", "th",
                    "--output_format", "srt",
                    "--output_dir", tmpdir,
                    "--compute_type", "int8",
                    "--word_timestamps", "True",
                    "--max_line_width", "20",
                    "--max_line_count", "1"
                ], check=True, timeout=300)  # 5 min timeout
            except subprocess.TimeoutExpired:
                raise Exception("Whisper transcription timed out (>300s)")
            except subprocess.CalledProcessError as e:
                raise Exception(f"Whisper failed: {e}")
            
            srt_name = os.path.splitext(os.path.basename(adjusted))[0] + ".srt"
            srt_path = os.path.join(tmpdir, srt_name)
            
            with open(srt_path, "r", encoding="utf-8") as fs:
                raw_srt_text = fs.read()
                
            if progress_cb:
                progress_cb("✨ กำลังแปลและจัดเรียงซับไตเติ้ล...", 4.6)
                
            print("[PIPELINE] Translating/Fixing SRT with Gemini...")
            prompt = f"""คุณคือผู้เชี่ยวชาญด้านการตัดต่อ Subtitle วิดีโอสั้นสไตล์ TikTok/Reels แบบคำปังๆ เน้นขึ้นโชว์ทีละบรรทัดสั้นๆ
นี่คือต้นฉบับบทพากย์ที่ถูกต้อง (Original Script):
{script}

และนี่คือไฟล์ SRT ที่ได้จากเสียงพูด:
{raw_srt_text}

คำสั่งบังคับ (สำคัญมากต้องทำตาม):
1. แปลงข้อมูลเป็น SRT ใหม่ ให้เนื้อหาซับไตเติ้ลแสดงผล "ทีละ 1 บรรทัดเท่านั้น" ห้ามมีการขึ้นบรรทัดใหม่ ใน 1 block
2. หั่นประโยคให้สั้น (กะประมาณไม่เกิน 15-20 ตัวอักษรต่อ 1 block SRT) เพื่อให้อ่านทันทีละจังหวะสั้นๆ
3. เนื้อหาและคำศัพท์ต้องถูกต้อง 100% ตาม "Original Script" ห้ามมีคำผิดแหลมมา (แก้คำที่ Whisper แปลงมามั่วให้ถูกเป๊ะๆ)
4. คุณต้อง "คำนวณแบ่งและสร้าง Timestamps ใหม่" โดยซอย block ยาวๆ ให้เป็น block สั้นๆ ตามสัดส่วนความยาวคำให้เนียนที่สุด โดยให้เวลาเริ่มและเวลาจบครอบคลุมตาม SRT ของเดิมอย่าให้ล้น
5. เลี่ยงการตัดคำที่มีความหมายติดกัน (เช่น 'เชยระเบิด' ไม่ควรแยก 'เชย' กับ 'ระเบิด' ข้ามเวลา)
6. ⚠️ ห้ามเอาข้อความสอง block หรือสองวรรคมาต่อกันแบบไม่มีเว้นวรรค เช่น "ดูความแบ๊วสิคะแม่ ขี่" หรือ "งอร้านสะดวกซื้อปาก" จะต้องแบ่งเป็นคำที่มีความหมายสมบูรณ์ "ดูความแบ๊วสิคะแม่", "ง้อร้านสะดวกซื้อปากซอย" 
7. ตอบกลับมาแค่เนื้อหา SRT ล้วนๆ ห้ามตอบอย่างอื่น ห้ามมี markdown ```srt

SRT ที่แก้ไขแล้ว:"""
            import time
            sub_model = "gemini-3-flash-preview"
            for attempt in range(5):
                try:
                    gemini_resp = http_requests.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{sub_model}:generateContent?key={api_key}",
                        json={"contents": [{"parts": [{"text": prompt}]}]},
                        timeout=60,
                    ).json()
                    
                    if gemini_resp.get("error"):
                        err_msg = gemini_resp['error'].get('message', '')
                        if "high demand" in err_msg.lower() or "503" in str(err_msg):
                            print(f"[PIPELINE] Subtitle Gemini high demand, retrying... ({attempt+1}/5)")
                            time.sleep(5)
                            if attempt >= 2 and sub_model == "gemini-3-flash-preview":
                                sub_model = "gemini-2.0-flash"
                                print(f"[PIPELINE] Fallback subtitle model to {sub_model}")
                            continue
                        print(f"[PIPELINE] Gemini Subtitling error: {err_msg}")
                        fixed_srt_content = raw_srt_text
                        break
                    else:
                        fixed_srt_content = gemini_resp.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        fixed_srt_content = fixed_srt_content.replace("```srt", "").replace("```", "").strip()
                        break
                except Exception as e:
                    if attempt < 4:
                        time.sleep(5)
                        continue
                    print(f"[PIPELINE] Gemini Subtitle Exception: {e}")
                    fixed_srt_content = raw_srt_text
                    break
                
            with open(srt_path, "w", encoding="utf-8") as fs:
                fs.write(fixed_srt_content)
                
            ass_path = os.path.join(tmpdir, "subtitles.ass")
            
            vp = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x", merged_nosub
            ], capture_output=True, text=True)
            res = vp.stdout.strip().split('x')
            vw = int(res[0]) if len(res) == 2 else 1080
            vh = int(res[1]) if len(res) == 2 else 1920
            
            _convert_to_ass(srt_path, ass_path, vw, vh)
            
            print("[PIPELINE] Burning subtitles with FFmpeg Native...")
            if progress_cb:
                progress_cb("🎬 กำลังเตรียมซับไตเติ้ล...", 4.8)
            
            # Use Native FFmpeg ASS plugin, pointing fontsdir to /app where font.ttf resides
            import re
            
            cmd = [
                "ffmpeg", "-y", "-i", merged_nosub,
                "-progress", "-", "-nostats",
                "-vf", f"ass={ass_path}:fontsdir=/app",
                "-c:v", "libx264", "-c:a", "copy", "-preset", "fast", output_path
            ]
            
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            
            last_pct = 0
            for line in p.stdout:
                line = line.strip()
                if line.startswith("out_time_us="):
                    try:
                        us_val = line.split("=")[1]
                        if us_val != "N/A":
                            current_sec = int(us_val) / 1000000.0
                            if duration > 0:
                                pct = min(1.0, current_sec / duration)
                                if pct - last_pct > 0.05 or pct == 1.0:
                                    if progress_cb:
                                        # Map 0..1 to 4.8..4.99
                                        progress_cb(f"🎬 กำลังฝังซับไตเติ้ล ({current_sec:.1f}s / {duration:.1f}s)", 4.8 + (pct * 0.19))
                                    last_pct = pct
                    except Exception:
                        pass
                        
            p.wait()
            
            if p.returncode != 0:
                print(f"[PIPELINE] FFmpeg sub error: returncode {p.returncode}")
                # Fallback on merge_nosub if subtitle burning fails completely
                import shutil
                shutil.move(merged_nosub, output_path)
                
        else:
            import shutil
            shutil.move(merged_nosub, output_path)

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


def _convert_to_ass(srt_file, ass_file, vw, vh):
    with open(srt_file, 'r', encoding='utf-8') as f:
        srt_content = f.read()
    
    font_size = int(vw * 0.115)
    if font_size < 50: font_size = 50
    
    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {vw}
PlayResY: {vh}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,FC Iconic,{font_size},&H00FFFFFF,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,10,0,2,10,10,250,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    blocks = srt_content.strip().split('\n\n')
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines: continue
        
        time_idx = -1
        for i, l in enumerate(lines):
            if '-->' in l:
                time_idx = i
                break
                
        if time_idx != -1 and time_idx + 1 < len(lines):
            times = lines[time_idx].split('-->')
            if len(times) == 2:
                def fmt_time(t):
                    t = t.strip().replace(',', '.')
                    parts = t.split(':')
                    if len(parts) == 3:
                        h = int(parts[0])
                        m = parts[1].zfill(2)
                        s_ms = parts[2].split('.')
                        s = s_ms[0].zfill(2)
                        ms = s_ms[1] if len(s_ms) > 1 else "000"
                        cs = ms[:2].ljust(2, '0')
                        return f"{h}:{m}:{s}.{cs}"
                    return t
                
                start = fmt_time(times[0])
                end = fmt_time(times[1])
                text = " ".join(lines[time_idx+1:]).replace('\n', '\\N')
                events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
            
    with open(ass_file, 'w', encoding='utf-8') as f:
        f.write(ass_header + '\n'.join(events))


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
