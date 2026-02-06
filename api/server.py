#!/usr/bin/env python3
"""
Dubbing Pipeline API — รัน pipeline ทั้งหมดบน CapRover (ไม่มี time limit)
- /health — health check
- /pipeline — รับงานจาก CF Worker แล้วรัน background (download, Gemini, TTS, merge, Telegram)
- /merge — merge video+audio (legacy, ยังใช้ได้)
"""
import os
import json
import base64
import tempfile
import subprocess
import time
import threading
import uuid
import requests as req
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Cloudflare R2 Config
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "dubbing-videos")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "")

# API Keys (set via CapRover env vars)
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
XHS_DL_URL = os.environ.get("XHS_DL_URL", "https://xhs-dl.lslly.com")
WORKER_URL = os.environ.get("WORKER_URL", "https://dubbing-worker.yokthanwa1993-bc9.workers.dev")


def get_r2_client():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto"
    )


# ==================== Telegram Helpers ====================

def send_telegram(method, body):
    resp = req.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
        json=body, timeout=30
    )
    return resp.json()


DOT_FRAMES = ['', '.', '..', '...']

STEP_ICONS = {'วิดีโอ': '📥', 'วิเคราะห์': '🔍', 'เสียง': '🎙️', 'รวม': '🎬'}
STEP_DONE = {'วิดีโอ': 'ดาวน์โหลดวิดีโอ', 'วิเคราะห์': 'วิเคราะห์วิดีโอ', 'เสียง': 'สร้างเสียงพากย์', 'รวม': 'รวมวิดีโอ'}
STEP_PROGRESS = {'วิดีโอ': 'กำลังดาวน์โหลดวิดีโอ', 'วิเคราะห์': 'กำลังวิเคราะห์วิดีโอ', 'เสียง': 'กำลังสร้างเสียงพากย์', 'รวม': 'กำลังรวมวิดีโอ'}


def build_status(completed, current=None, dot_idx=0):
    lines = []
    for s in completed:
        lines.append(f"{STEP_ICONS[s]} {STEP_DONE[s]} ✅")
    if current:
        dots = DOT_FRAMES[dot_idx % 4]
        lines.append(f"{STEP_ICONS[current]} {STEP_PROGRESS[current]}{dots}")
    return '\n'.join(lines) or '⏳ เริ่มต้น...'


def start_dot_animation(chat_id, msg_id, completed, current):
    stop = threading.Event()

    def loop():
        idx = 0
        while not stop.is_set():
            text = build_status(completed, current, idx)
            try:
                send_telegram('editMessageText', {
                    'chat_id': chat_id, 'message_id': msg_id,
                    'text': text, 'parse_mode': 'HTML'
                })
            except Exception:
                pass
            idx += 1
            stop.wait(0.6)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return stop


# ==================== Gemini API ====================

def upload_to_gemini(video_bytes):
    # Resumable upload
    init = req.post(
        f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={GOOGLE_API_KEY}",
        headers={
            'X-Goog-Upload-Protocol': 'resumable',
            'X-Goog-Upload-Command': 'start',
            'X-Goog-Upload-Header-Content-Length': str(len(video_bytes)),
            'X-Goog-Upload-Header-Content-Type': 'video/mp4',
            'Content-Type': 'application/json',
        },
        json={'file': {'display_name': 'video.mp4'}},
        timeout=60
    )
    upload_url = init.headers.get('X-Goog-Upload-URL')
    if not upload_url:
        raise Exception('ไม่ได้ upload URL จาก Gemini')

    result = req.post(upload_url, headers={
        'X-Goog-Upload-Command': 'upload, finalize',
        'X-Goog-Upload-Offset': '0',
        'Content-Type': 'video/mp4',
    }, data=video_bytes, timeout=120).json()

    file_uri = result.get('file', {}).get('uri')
    file_name = result.get('file', {}).get('name')
    if not file_uri or not file_name:
        raise Exception('อัพโหลดไป Gemini ไม่สำเร็จ')
    return file_uri, file_name


def wait_for_processing(file_name):
    for _ in range(30):
        data = req.get(
            f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={GOOGLE_API_KEY}",
            timeout=30
        ).json()
        if data.get('state') != 'PROCESSING':
            return data.get('uri', '')
        time.sleep(2)
    raise Exception('Gemini ประมวลผลวิดีโอนานเกินไป')


def generate_script(file_uri, duration):
    target_chars = int(duration * 10)
    min_chars = int(duration * 8)
    prompt = f"""คุณคือ "พี่ต้น" นักรีวิวสินค้าออนไลน์มือฉมัง ที่มีผู้ติดตามหลายล้านคน

ดูวิดีโอสินค้านี้แล้วเขียน script พากย์เสียงภาษาไทย

⚠️ สำคัญมาก: วิดีโอยาว {round(duration)} วินาที
- Script ต้องยาว {min_chars}-{target_chars} ตัวอักษร (ภาษาไทยพูดประมาณ 8-10 ตัว/วินาที)
- ถ้า script สั้นกว่านี้ วิดีโอจะถูกตัด!

สไตล์:
- เปิดด้วย "โห้ อันนี้ต้องมี!" หรือ "ของดีมาแล้วครับพี่น้อง!"
- บรรยายจุดเด่นของสินค้าตามที่เห็นในวิดีโอ อธิบายให้ละเอียด
- ใส่ประโยชน์การใช้งาน วิธีใช้ ข้อดี
- ปิดด้วย "สนใจสั่งเลยครับ รีบๆนะ ของมีจำกัด!"

ตอบเป็น JSON: {{"thai_script": "ข้อความพากย์เสียงยาว {min_chars}-{target_chars} ตัวอักษร"}}"""

    resp = req.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GOOGLE_API_KEY}",
        json={
            'contents': [{'parts': [
                {'fileData': {'mimeType': 'video/mp4', 'fileUri': file_uri}},
                {'text': prompt},
            ]}],
            'generationConfig': {'temperature': 0.8, 'maxOutputTokens': 4096},
        },
        timeout=120
    ).json()

    text = resp.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
    text = text.replace('```json', '').replace('```', '').strip()
    try:
        return json.loads(text).get('thai_script', '')
    except Exception:
        import re
        m = re.search(r'"thai_script":\s*"([^"]+)"', text)
        return m.group(1) if m else text[:200]


def generate_tts(script):
    resp = req.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={GOOGLE_API_KEY}",
        json={
            'contents': [{'parts': [{'text': script}]}],
            'generationConfig': {
                'responseModalities': ['AUDIO'],
                'speechConfig': {
                    'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': 'Puck'}},
                },
            },
        },
        timeout=120
    )
    if not resp.ok:
        err = resp.json().get('error', {}).get('message', str(resp.status_code))
        raise Exception(f'TTS ล้มเหลว: {err}')

    data = resp.json()
    audio = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('inlineData', {}).get('data')
    if not audio:
        raise Exception('ไม่ได้เสียงจาก TTS')
    return audio


# ==================== Pipeline ====================

def run_pipeline(video_url, chat_id, msg_id):
    completed = []
    stop_anim = None

    try:
        # === Step 1: Download ===
        stop_anim = start_dot_animation(chat_id, msg_id, completed, 'วิดีโอ')

        direct_url = video_url
        if 'xhs' in video_url or 'xiaohongshu' in video_url:
            r = req.post(f"{XHS_DL_URL}/xhs/detail", json={'url': video_url, 'download': False}, timeout=30)
            urls = r.json().get('data', {}).get('下载地址', [])
            if not urls:
                raise Exception('ไม่พบวิดีโอใน XHS link นี้')
            direct_url = urls[0]

        video_bytes = req.get(direct_url, headers={'Referer': 'https://www.xiaohongshu.com/'}, timeout=120).content
        print(f"[PIPELINE] ดาวน์โหลดวิดีโอแล้ว: {len(video_bytes) / 1024 / 1024:.1f} MB")

        # เก็บต้นฉบับใน R2
        video_id = uuid.uuid4().hex[:8]
        s3 = get_r2_client()
        original_key = f"videos/{video_id}_original.mp4"
        s3.put_object(Bucket=R2_BUCKET_NAME, Key=original_key, Body=video_bytes, ContentType='video/mp4')
        print(f"[PIPELINE] เก็บต้นฉบับ R2: {original_key}")

        stop_anim.set()
        completed.append('วิดีโอ')

        # === Step 2: Gemini Analysis ===
        stop_anim = start_dot_animation(chat_id, msg_id, completed, 'วิเคราะห์')

        file_uri, file_name = upload_to_gemini(video_bytes)
        print(f"[PIPELINE] อัพโหลด Gemini: {file_name}")
        processed_uri = wait_for_processing(file_name)
        final_uri = processed_uri or file_uri

        # Get duration from video bytes via ffprobe
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name
        try:
            probe = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', tmp_path
            ], capture_output=True, text=True)
            duration = float(probe.stdout.strip()) if probe.stdout.strip() else 15.0
        finally:
            os.unlink(tmp_path)

        script = generate_script(final_uri, duration)
        if not script or len(script) < 10:
            raise Exception('สร้าง script ไม่สำเร็จ')
        print(f"[PIPELINE] Script: {script[:60]}... ({len(script)} chars)")

        stop_anim.set()
        completed.append('วิเคราะห์')

        # === Step 3: TTS ===
        stop_anim = start_dot_animation(chat_id, msg_id, completed, 'เสียง')

        audio_base64 = generate_tts(script)
        print(f"[PIPELINE] เสียง: {len(audio_base64) // 1024} KB base64")

        stop_anim.set()
        completed.append('เสียง')

        # === Step 4: Merge ===
        stop_anim = start_dot_animation(chat_id, msg_id, completed, 'รวม')

        original_url = f"{R2_PUBLIC_URL}/{original_key}"
        with tempfile.TemporaryDirectory() as tmpdir:
            # Download video
            video_path = os.path.join(tmpdir, "video.mp4")
            with open(video_path, "wb") as f:
                f.write(video_bytes)

            # Decode + convert audio
            raw_audio = os.path.join(tmpdir, "audio.raw")
            wav_audio = os.path.join(tmpdir, "audio.wav")
            with open(raw_audio, "wb") as f:
                f.write(base64.b64decode(audio_base64))

            subprocess.run([
                "ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
                "-i", raw_audio, wav_audio
            ], check=True, capture_output=True)

            # Audio duration
            ap = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", wav_audio
            ], capture_output=True, text=True)
            audio_dur = float(ap.stdout.strip()) if ap.stdout.strip() else 0

            # Adjust audio
            adjusted = os.path.join(tmpdir, "audio_adj.wav")
            diff = duration - audio_dur
            if abs(diff) < 0.5:
                adjusted = wav_audio
            elif diff > 0:
                subprocess.run(["ffmpeg", "-y", "-i", wav_audio, "-af", f"apad=pad_dur={diff}", adjusted], capture_output=True)
            else:
                subprocess.run(["ffmpeg", "-y", "-i", wav_audio, "-t", str(duration), adjusted], capture_output=True)

            # Merge
            output_path = os.path.join(tmpdir, "output.mp4")
            mr = subprocess.run([
                "ffmpeg", "-y", "-i", video_path, "-i", adjusted,
                "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
                "-t", str(duration), output_path
            ], capture_output=True, text=True)
            if mr.returncode != 0:
                raise Exception(f"FFmpeg merge ล้มเหลว: {mr.stderr[:200]}")

            # Output duration
            op = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", output_path
            ], capture_output=True, text=True)
            out_dur = float(op.stdout.strip()) if op.stdout.strip() else duration

            # Upload merged to R2
            video_key = f"videos/{video_id}.mp4"
            with open(output_path, "rb") as f:
                s3.upload_fileobj(f, R2_BUCKET_NAME, video_key, ExtraArgs={"ContentType": "video/mp4"})
            public_url = f"{R2_PUBLIC_URL}/{video_key}"
            print(f"[PIPELINE] Merge เสร็จ: {public_url}")

        stop_anim.set()
        completed.append('รวม')

        # === Step 5: Save metadata + rebuild gallery cache ===
        metadata = {
            'id': video_id,
            'script': script,
            'duration': out_dur,
            'originalUrl': video_url,
            'createdAt': time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime()),
            'publicUrl': public_url,
        }
        s3.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=f"videos/{video_id}.json",
            Body=json.dumps(metadata, ensure_ascii=False, indent=2),
            ContentType='application/json'
        )

        # Rebuild gallery cache
        try:
            rebuild_gallery_cache(s3)
        except Exception as e:
            print(f"[PIPELINE] Cache rebuild failed: {e}")

        # === Step 6: Notify Telegram ===
        send_telegram('deleteMessage', {'chat_id': chat_id, 'message_id': msg_id})
        send_telegram('sendVideo', {
            'chat_id': chat_id,
            'video': public_url,
            'reply_markup': {
                'inline_keyboard': [[
                    {'text': '🎥 เปิดคลัง', 'web_app': {'url': 'https://dubbing-webapp.pages.dev?tab=gallery'}}
                ]]
            }
        })
        print(f"[PIPELINE] เสร็จสมบูรณ์! videoId={video_id}")

    except Exception as e:
        if stop_anim:
            stop_anim.set()
        import traceback
        err_msg = str(e)
        print(f"[PIPELINE] Error: {err_msg}\n{traceback.format_exc()}")
        try:
            send_telegram('editMessageText', {
                'chat_id': chat_id, 'message_id': msg_id,
                'text': f"❌ ผิดพลาด\n\n{err_msg[:150]}", 'parse_mode': 'HTML'
            })
        except Exception:
            pass


def rebuild_gallery_cache(s3):
    """Rebuild _cache/gallery.json"""
    resp = s3.list_objects_v2(Bucket=R2_BUCKET_NAME, Prefix='videos/')
    videos = []
    for obj in resp.get('Contents', []):
        if not obj['Key'].endswith('.json'):
            continue
        body = s3.get_object(Bucket=R2_BUCKET_NAME, Key=obj['Key'])['Body'].read()
        videos.append(json.loads(body))
    videos.sort(key=lambda v: v.get('createdAt', ''), reverse=True)
    s3.put_object(
        Bucket=R2_BUCKET_NAME,
        Key='_cache/gallery.json',
        Body=json.dumps({'videos': videos}, ensure_ascii=False),
        ContentType='application/json'
    )
    print(f"[CACHE] Rebuilt gallery cache: {len(videos)} videos")


# ==================== Routes ====================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "dubbing-pipeline"})


@app.route("/pipeline", methods=["POST"])
def pipeline():
    """
    CF Worker ส่งงานมา → CapRover รัน background ทันที → return 202
    """
    data = request.json
    video_url = data.get("videoUrl")
    chat_id = data.get("chatId")
    msg_id = data.get("msgId")

    if not all([video_url, chat_id, msg_id]):
        return jsonify({"error": "videoUrl, chatId, msgId required"}), 400

    # รัน pipeline ใน background thread
    t = threading.Thread(target=run_pipeline, args=(video_url, chat_id, msg_id), daemon=True)
    t.start()

    return jsonify({"status": "accepted"}), 202


@app.route("/merge", methods=["POST"])
def merge():
    """Legacy merge endpoint — ยังใช้ได้"""
    try:
        data = request.json
        video_url = data.get("videoUrl")
        audio_base64 = data.get("audioBase64")
        sample_rate = data.get("audioSampleRate", 24000)
        video_id = data.get("videoId")

        if not all([video_url, audio_base64, video_id]):
            return jsonify({"error": "videoUrl, audioBase64, videoId จำเป็นต้องมี"}), 400

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "video.mp4")
            resp = req.get(video_url, timeout=120)
            with open(video_path, "wb") as f:
                f.write(resp.content)

            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path
            ], capture_output=True, text=True)
            duration = float(probe.stdout.strip()) if probe.stdout.strip() else 10.0

            raw_audio = os.path.join(tmpdir, "audio.raw")
            wav_audio = os.path.join(tmpdir, "audio.wav")
            with open(raw_audio, "wb") as f:
                f.write(base64.b64decode(audio_base64))
            subprocess.run([
                "ffmpeg", "-y", "-f", "s16le", "-ar", str(sample_rate), "-ac", "1",
                "-i", raw_audio, wav_audio
            ], check=True, capture_output=True)

            output_path = os.path.join(tmpdir, "output.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-i", video_path, "-i", wav_audio,
                "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
                "-t", str(duration), output_path
            ], check=True, capture_output=True)

            op = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", output_path
            ], capture_output=True, text=True)
            out_dur = float(op.stdout.strip()) if op.stdout.strip() else duration

            s3 = get_r2_client()
            video_key = f"videos/{video_id}.mp4"
            with open(output_path, "rb") as f:
                s3.upload_fileobj(f, R2_BUCKET_NAME, video_key, ExtraArgs={"ContentType": "video/mp4"})

            return jsonify({"success": True, "publicUrl": f"{R2_PUBLIC_URL}/{video_key}", "duration": out_dur})

    except Exception as e:
        import traceback
        print(f"[MERGE] Error: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)
