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
import queue
import requests as req
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ==================== Job Queue ====================
pipeline_queue = queue.Queue()
current_job_id = None  # track which job is running

# Cloudflare R2 Config
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "dubbing-videos")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "")

# API Keys (set via CapRover env vars — fallback ชื่อเก่า)
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("gemini", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("telegram_bot", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or os.environ.get("model", "gemini-3-flash-preview")
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


LOADER_FRAMES = ['.', '..', '...']

STEP_ICONS = {'วิดีโอ': '📥', 'วิเคราะห์': '🔍', 'เสียง': '🎙️', 'รวม': '🎬', 'shopee': '🔗'}
STEP_DONE = {'วิดีโอ': 'ดาวน์โหลดวิดีโอ', 'วิเคราะห์': 'วิเคราะห์วิดีโอ', 'เสียง': 'สร้างเสียงพากย์', 'รวม': 'รวมวิดีโอ', 'shopee': 'ลิงก์ Shopee'}
STEP_PROGRESS = {'วิดีโอ': 'กำลังดาวน์โหลดวิดีโอ', 'วิเคราะห์': 'กำลังวิเคราะห์วิดีโอ', 'เสียง': 'กำลังสร้างเสียงพากย์', 'รวม': 'กำลังรวมวิดีโอ', 'shopee': 'ส่งลิงก์ Shopee มาเลยครับ'}


def build_status(completed, current=None, frame_idx=0):
    lines = []
    for s in completed:
        lines.append(f"{STEP_ICONS[s]} {STEP_DONE[s]} ✅")
    if current:
        dots = LOADER_FRAMES[frame_idx % len(LOADER_FRAMES)]
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
            stop.wait(0.35)

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
    prompt = f"""คุณคือนักรีวิวสินค้าออนไลน์ ดูวิดีโอสินค้านี้แล้วทำ 2 อย่าง:
1. เขียนแคปชั่น Facebook Reels 1 บรรทัด น่าสนใจ ดึงดูดคนกด ใช้ภาษาชวนซื้อ มี emoji นำหน้า 1 ตัว ห้ามตัดคำ ต้องจบประโยคสมบูรณ์
2. เขียน script พากย์เสียงภาษาไทย เปิดด้วย "สวัสดีครับ" เสมอ

⚠️ สำคัญมาก: วิดีโอยาว {round(duration)} วินาที
- Script ต้องยาว {min_chars}-{target_chars} ตัวอักษร (ภาษาไทยพูดประมาณ 8-10 ตัว/วินาที)
- ถ้า script สั้นกว่านี้ วิดีโอจะถูกตัด!

สไตล์:
- พูดเป็นธรรมชาติเหมือนคนรีวิวจริงๆ ไม่ต้องเป็นทางการ
- ดูวิดีโอให้ละเอียดแล้วบรรยายตามที่เห็นจริง ห้ามแต่งเอง
- ชวนซื้อแบบไม่กดดัน พูดถึงข้อดีจริงๆ ของสินค้า

ตอบเป็น JSON: {{"title": "แคปชั่น 1 บรรทัด มี emoji จบประโยคสมบูรณ์", "thai_script": "สวัสดีครับ ...ข้อความพากย์เสียงยาว {min_chars}-{target_chars} ตัวอักษร"}}"""

    resp = req.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GOOGLE_API_KEY}",
        json={
            'contents': [{'parts': [
                {'fileData': {'mimeType': 'video/mp4', 'fileUri': file_uri}},
                {'text': prompt},
            ]}],
            'generationConfig': {'temperature': 1.0, 'maxOutputTokens': 4096},
        },
        timeout=120
    ).json()

    text = resp.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
    text = text.replace('```json', '').replace('```', '').strip()
    title = ''
    script = ''
    try:
        parsed = json.loads(text)
        title = parsed.get('title', '')
        script = parsed.get('thai_script', '')
    except Exception:
        import re
        m = re.search(r'"thai_script":\s*"([^"]+)"', text)
        script = m.group(1) if m else text[:200]
        mt = re.search(r'"title":\s*"([^"]+)"', text)
        title = mt.group(1) if mt else ''
    return script, title


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

        script, title = generate_script(final_uri, duration)
        if not script or len(script) < 10:
            raise Exception('สร้าง script ไม่สำเร็จ')
        print(f"[PIPELINE] Title: {title}")
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

            # Generate WebP thumbnail from video
            thumb_path = os.path.join(tmpdir, "thumb.webp")
            subprocess.run([
                "ffmpeg", "-y", "-i", output_path, "-vframes", "1", "-ss", "0.1",
                "-vf", "scale=270:480:force_original_aspect_ratio=increase,crop=270:480",
                "-q:v", "80", thumb_path
            ], capture_output=True)
            thumb_url = ''
            if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
                thumb_key = f"videos/{video_id}_thumb.webp"
                with open(thumb_path, "rb") as f:
                    s3.upload_fileobj(f, R2_BUCKET_NAME, thumb_key, ExtraArgs={"ContentType": "image/webp"})
                thumb_url = f"{R2_PUBLIC_URL}/{thumb_key}"
                print(f"[PIPELINE] Thumbnail: {thumb_url}")

        stop_anim.set()
        completed.append('รวม')

        # === Step 5: Save metadata + rebuild gallery cache ===
        metadata = {
            'id': video_id,
            'title': title,
            'script': script,
            'duration': out_dur,
            'originalUrl': video_url,
            'createdAt': time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime()),
            'publicUrl': public_url,
            'thumbnailUrl': thumb_url,
            'shopeeLink': '',
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

        # === Step 6: แสดง step Shopee ต่อจาก progress เดิม (ไม่ลบข้อความ) ===
        text = build_status(completed, 'shopee', 0)
        send_telegram('editMessageText', {
            'chat_id': chat_id, 'message_id': msg_id,
            'text': text, 'parse_mode': 'HTML'
        })

        # บันทึก pending shopee state ใน R2 (เก็บ publicUrl + msgId ไว้ให้ Worker ลบทีหลัง)
        s3.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=f"_pending_shopee/{chat_id}.json",
            Body=json.dumps({'videoId': video_id, 'publicUrl': public_url, 'msgId': msg_id}),
            ContentType='application/json'
        )
        print(f"[PIPELINE] เสร็จสมบูรณ์! รอ Shopee link videoId={video_id}")

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


# ==================== Generate Titles ====================

def generate_title_from_script(script):
    """ใช้ Gemini สร้างชื่อวีดีโอสั้นๆ จาก script"""
    resp = req.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GOOGLE_API_KEY}",
        json={
            'contents': [{'parts': [{'text': f"""จาก script วีดีโอสินค้านี้ ช่วยสร้างแคปชั่นสำหรับโพสต์ Facebook Reels

กฎ:
- 1 บรรทัดเท่านั้น
- น่าสนใจ ดึงดูดคนกด ใช้ภาษาชวนซื้อ
- มี emoji 1-2 ตัว
- ความยาว 40-80 ตัวอักษร
- ห้ามตัดคำ ต้องจบประโยคสมบูรณ์
- ตอบแค่แคปชั่นเลย ไม่ต้องมีเครื่องหมายคำพูดหรือคำอธิบาย

script: {script[:300]}"""}]}],
            'generationConfig': {'temperature': 0.9, 'maxOutputTokens': 1024},
        },
        timeout=60
    ).json()
    title = resp.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '').strip()
    # Remove quotes if present
    if title and title[0] in '""\'"' and title[-1] in '""\'"':
        title = title[1:-1]
    return title


title_gen_status = {"running": False, "done": 0, "total": 0, "errors": 0, "last": ""}


def generate_all_titles():
    global title_gen_status
    s3 = get_r2_client()
    title_gen_status = {"running": True, "done": 0, "total": 0, "errors": 0, "last": ""}
    try:
        resp = s3.list_objects_v2(Bucket=R2_BUCKET_NAME, Prefix='videos/', MaxKeys=1000)
        objects = resp.get('Contents', [])
        json_files = [o for o in objects if o['Key'].endswith('.json')]
        # regenerate all titles (force mode)
        to_process = []
        for obj in json_files:
            video_id = obj['Key'].replace('videos/', '').replace('.json', '')
            meta_obj = s3.get_object(Bucket=R2_BUCKET_NAME, Key=obj['Key'])
            meta = json.loads(meta_obj['Body'].read())
            if not meta.get('script'):
                print(f"[TITLE] Skip {video_id} (no script)")
                continue
            to_process.append((obj['Key'], video_id, meta))

        title_gen_status["total"] = len(to_process)
        print(f"[TITLE] Need to generate {len(to_process)} titles")

        for key, video_id, meta in to_process:
            try:
                print(f"[TITLE] Generating for {video_id}...")
                title = generate_title_from_script(meta['script'])
                if title:
                    meta['title'] = title
                    s3.put_object(
                        Bucket=R2_BUCKET_NAME, Key=key,
                        Body=json.dumps(meta, ensure_ascii=False, indent=2),
                        ContentType='application/json'
                    )
                    title_gen_status["done"] += 1
                    title_gen_status["last"] = f"{video_id}: {title[:50]}"
                    print(f"[TITLE] Done {title_gen_status['done']}/{title_gen_status['total']}: {video_id} → {title}")
                else:
                    title_gen_status["errors"] += 1
                    print(f"[TITLE] No title generated for {video_id}")
                # delay 3s to avoid rate limit
                time.sleep(3)
            except Exception as e:
                title_gen_status["errors"] += 1
                import traceback
                print(f"[TITLE] Failed {video_id}: {e}\n{traceback.format_exc()}")
                time.sleep(5)
        # Rebuild gallery cache
        rebuild_gallery_cache(s3)
        print(f"[TITLE] All done! Generated {title_gen_status['done']} titles")
    except Exception as e:
        import traceback
        print(f"[TITLE] Fatal error: {e}\n{traceback.format_exc()}")
    finally:
        title_gen_status["running"] = False
    return title_gen_status["done"]


# ==================== Generate Thumbnails ====================

def generate_all_thumbs():
    s3 = get_r2_client()
    count = 0
    try:
        resp = s3.list_objects_v2(Bucket=R2_BUCKET_NAME, Prefix='videos/', MaxKeys=1000)
        objects = resp.get('Contents', [])
        json_files = [o for o in objects if o['Key'].endswith('.json')]
        print(f"[THUMB] Found {len(json_files)} video metadata files")
        for obj in json_files:
            video_id = obj['Key'].replace('videos/', '').replace('.json', '')
            try:
                meta_obj = s3.get_object(Bucket=R2_BUCKET_NAME, Key=obj['Key'])
                meta = json.loads(meta_obj['Body'].read())
                if meta.get('thumbnailUrl'):
                    print(f"[THUMB] Skip {video_id} (already has thumb)")
                    continue
                video_url = meta.get('publicUrl', '')
                if not video_url:
                    continue
                print(f"[THUMB] Generating for {video_id}...")
                with tempfile.TemporaryDirectory() as tmpdir:
                    video_path = os.path.join(tmpdir, "video.mp4")
                    r = req.get(video_url, timeout=120)
                    with open(video_path, "wb") as f:
                        f.write(r.content)
                    thumb_path = os.path.join(tmpdir, "thumb.webp")
                    result = subprocess.run([
                        "ffmpeg", "-y", "-ss", "0.1", "-i", video_path, "-vframes", "1",
                        "-vf", "scale=270:480:force_original_aspect_ratio=increase,crop=270:480",
                        "-q:v", "80", thumb_path
                    ], capture_output=True, text=True)
                    if result.returncode != 0:
                        print(f"[THUMB] ffmpeg error {video_id}: {result.stderr[:200]}")
                        continue
                    if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
                        thumb_key = f"videos/{video_id}_thumb.webp"
                        with open(thumb_path, "rb") as f:
                            s3.upload_fileobj(f, R2_BUCKET_NAME, thumb_key, ExtraArgs={"ContentType": "image/webp"})
                        meta['thumbnailUrl'] = f"{R2_PUBLIC_URL}/{thumb_key}"
                        s3.put_object(
                            Bucket=R2_BUCKET_NAME, Key=obj['Key'],
                            Body=json.dumps(meta, ensure_ascii=False, indent=2),
                            ContentType='application/json'
                        )
                        count += 1
                        print(f"[THUMB] Done: {video_id} ({count})")
                    else:
                        print(f"[THUMB] No output for {video_id}")
            except Exception as e:
                import traceback
                print(f"[THUMB] Failed {video_id}: {e}\n{traceback.format_exc()}")
        # Rebuild gallery cache
        rebuild_gallery_cache(s3)
        print(f"[THUMB] All done! Generated {count} thumbnails")
    except Exception as e:
        import traceback
        print(f"[THUMB] Fatal error: {e}\n{traceback.format_exc()}")
    return count


# ==================== Routes ====================

@app.route("/generate-titles", methods=["POST"])
def gen_titles():
    if title_gen_status.get("running"):
        return jsonify({"status": "already_running", **title_gen_status})
    t = threading.Thread(target=generate_all_titles, daemon=True)
    t.start()
    return jsonify({"status": "started"}), 202


@app.route("/generate-titles/status", methods=["GET"])
def gen_titles_status():
    return jsonify(title_gen_status)


@app.route("/generate-thumbs", methods=["POST"])
def gen_thumbs():
    t = threading.Thread(target=generate_all_thumbs, daemon=True)
    t.start()
    return jsonify({"status": "started"}), 202


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "dubbing-pipeline",
        "queue": pipeline_queue.qsize(),
        "running": current_job_id is not None,
    })


@app.route("/pipeline", methods=["POST"])
def pipeline():
    """
    CF Worker ส่งงานมา → ใส่คิว → รันทีละ 1 งาน
    """
    data = request.json
    video_url = data.get("videoUrl")
    chat_id = data.get("chatId")
    msg_id = data.get("msgId")
    if not all([video_url, chat_id, msg_id]):
        return jsonify({"error": "videoUrl, chatId, msgId required"}), 400

    job_id = str(uuid.uuid4())[:8]
    pipeline_queue.put({"id": job_id, "videoUrl": video_url, "chatId": chat_id, "msgId": msg_id})

    pos = pipeline_queue.qsize()
    if current_job_id:
        pos += 1  # +1 for the currently running job

    if pos > 1:
        send_telegram('editMessageText', {
            'chat_id': chat_id,
            'message_id': msg_id,
            'text': f'⏳ อยู่ในคิวลำดับที่ {pos} กรุณารอสักครู่...',
            'parse_mode': 'HTML',
        })

    return jsonify({"status": "queued", "position": pos}), 202


def queue_worker():
    """Worker thread — ดึงงานจากคิวมารันทีละ 1"""
    global current_job_id
    while True:
        job = pipeline_queue.get()
        try:
            current_job_id = job["id"]
            run_pipeline(job["videoUrl"], job["chatId"], job["msgId"])
        except Exception as e:
            print(f"[QUEUE] Job {job['id']} failed: {e}")
        finally:
            current_job_id = None
            pipeline_queue.task_done()


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
    # Start queue worker thread
    t = threading.Thread(target=queue_worker, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)
