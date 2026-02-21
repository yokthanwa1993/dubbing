#!/usr/bin/env python3
"""
ทดสอบ pipeline พากย์เสียงในเครื่อง (flow เดียวกับ production)
ใช้: python scripts/test_pipeline.py video.mp4
ผลลัพธ์: output.mp4
"""
import sys
import os
import json
import re
import base64
import tempfile
import subprocess
import requests

# Get API key from environment variable or use the new one as a fallback for local testing
API_KEY = os.environ.get("GOOGLE_API_KEY", "AIzaSyDO3alwmA6p9xUV2O3VzX1Kfs9vKxycRzU")
MODEL = "gemini-3-flash-preview"

PROMPT = """คุณคือ "เฉียบ" สาวสองนักรีวิวสินค้าสุดแซ่บ พูดจากวนตีน จี๊ดจ๊าด ดราม่าเว่อร์ ชอบแซวคนดู ปากจัดแต่น่ารัก

ดูวิดีโอสินค้านี้แล้วสร้าง script พากย์เสียงสำหรับ Facebook Reels

สไตล์ "เฉียบ":
- เปิดด้วยประโยคจี๊ดๆ เช่น "แม่จ๋าา ของดีมาแล้วค่า!" / "อี๋ย ใครยังไม่มีอันนี้ เชยระเบิดเลยนะคะ!" / "ตายแล้วค่ะ ของมันต้องมี!"
- พูดแบบสาวสองเต็มตัว ใช้คำว่า "ค่ะ" "จ๊ะ" "นะคะ" "แม่" "ตัวเอง" เยอะๆ ดราม่านิดๆ โอเวอร์หน่อยๆ
- แซวคนดูแบบน่ารัก เช่น "ยังใช้ของเดิมอยู่เหรอจ๊ะ น่าสงสารตัวเอง!" / "ใช้แล้วสวยขึ้น ไม่ได้พูดเล่นนะคะ!"
- บรรยายจุดเด่นสินค้าจริงจากวิดีโอ แต่ใส่อารมณ์โอเวอร์ เช่น "โอ้โห เห็นปุ๊บหัวใจแม่สั่นเลยค่ะ!" / "ดีจนอยากกรี๊ดดดด!"
- ปิดด้วยทิ้งท้ายจี๊ดๆ เช่น "กดซื้อเลยค่ะ ไม่งั้นแม่จะโกรธ!" / "ไม่ซื้อก็ได้ค่ะ แต่อย่ามาร้องไห้ตอนของหมดนะจ๊ะ 555!" / "ลิงก์ข้างล่างจ้า แม่จัดให้แล้ว!"

⚠️ ข้อห้าม: ห้ามพูด "สวัสดี" ห้ามเรียบๆ น่าเบื่อ ต้องจี๊ดจ๊าดตั้งแต่คำแรก! กระชับแต่แซ่บ!

ตอบเป็น JSON เท่านั้น:
{
  "thai_script": "script ภาษาไทยสไตล์สาวสองกวนๆ 150-300 ตัวอักษร จี๊ดจ๊าดชวนซื้อ",
  "title": "แคปชั่นสั้นแซ่บๆ ดึงดูดคนกด",
  "category": "หมวดหมู่ (เครื่องมือช่าง/อาหาร/เครื่องครัว/ของใช้ในบ้าน/เฟอร์นิเจอร์/บิวตี้/แฟชั่น/อิเล็กทรอนิกส์/สุขภาพ/กีฬา/สัตว์เลี้ยง/ยานยนต์/อื่นๆ)"
}"""


def resolve_xhs(url):
    """Resolve XHS short link → direct video URL"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }
    resp = requests.get(url, headers=headers, allow_redirects=True, timeout=15)
    html = resp.text

    for m in re.finditer(r'"masterUrl"\s*:\s*"([^"]+)"', html):
        u = m.group(1).replace("\\u002F", "/")
        if "sns-video" in u:
            return u

    m = re.search(r'"originVideoKey"\s*:\s*"([^"]+)"', html)
    if m:
        return f"https://sns-video-bd.xhscdn.com/{m.group(1)}"
    return None


def download_video(url):
    print(f"📥 ดาวน์โหลดวิดีโอ...")
    resp = requests.get(url, headers={"Referer": "https://www.xiaohongshu.com/"}, timeout=120)
    if resp.status_code != 200:
        raise Exception(f"Download failed: {resp.status_code}")
    print(f"   ✅ ขนาด {len(resp.content)/1024/1024:.1f} MB")
    return resp.content


def get_duration(video_path):
    r = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path
    ], capture_output=True, text=True)
    return float(r.stdout.strip()) if r.stdout.strip() else 15.0


def gemini_upload(video_bytes):
    print(f"🔍 อัพโหลดไป Gemini...")
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/upload/v1beta/files?uploadType=media&key={API_KEY}",
        data=video_bytes,
        headers={"Content-Type": "video/mp4", "X-Goog-Upload-Protocol": "raw"},
        timeout=120,
    )
    data = resp.json()
    if "file" not in data:
        raise Exception(f"Upload failed: {json.dumps(data, indent=2)}")
    uri = data["file"]["uri"]
    name = data["file"]["name"]
    print(f"   ✅ URI: {uri}")
    return uri, name


def gemini_wait(file_name):
    import time
    print(f"   ⏳ รอ Gemini ประมวลผล...")
    for i in range(30):
        r = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={API_KEY}",
            timeout=15
        ).json()
        state = r.get("state", "UNKNOWN")
        if state == "ACTIVE":
            print(f"   ✅ ประมวลผลเสร็จ")
            return
        print(f"   ... {state} ({i+1}/30)")
        time.sleep(3)
    raise Exception("Gemini ประมวลผลนานเกินไป")


def gemini_script(file_uri, video_duration):
    print(f"📝 สร้าง script (สำหรับ {video_duration:.1f} วินาที)...")
    
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
    for attempt in range(3):
        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}",
                json={"contents": [{"parts": [
                    {"file_data": {"mime_type": "video/mp4", "file_uri": file_uri}},
                    {"text": prompt}
                ]}]},
                timeout=120,
            ).json()

            if resp.get("error"):
                raise Exception(f"Gemini error: {resp['error'].get('message')}")
            break
        except Exception as e:
            if attempt == 2: raise
            print(f"   ⚠️ Gemini script timeout/error, retrying... ({attempt+1}/3)")
            time.sleep(5)

    text = resp.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    text = text.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(text)
        script = parsed.get("thai_script", "")
        title = parsed.get("title", "")
        category = parsed.get("category", "อื่นๆ")
    except:
        m = re.search(r'"thai_script"\s*:\s*"([^"]+)"', text)
        script = m.group(1) if m else text[:500]
        title = ""
        category = "อื่นๆ"

    print(f"   ✅ Script ({len(script)} ตัวอักษร):")
    print(f"   📝 {script}")
    print(f"   📌 Title: {title}")
    print(f"   📂 Category: {category}")
    return script, title, category


def gemini_tts(script):
    print(f"🎙️ สร้างเสียงพากย์...")
    import time
    for attempt in range(3):
        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={API_KEY}",
                json={
                    "contents": [{"parts": [{"text": script}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Puck"}}}
                    }
                },
                timeout=120,
            ).json()

            if resp.get("error"):
                raise Exception(f"TTS error: {resp['error'].get('message')}")
            break
        except Exception as e:
            if attempt == 2: raise
            print(f"   ⚠️ TTS timeout/error, retrying... ({attempt+1}/3)")
            time.sleep(5)

    audio_b64 = resp["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
    print(f"   ✅ เสียง {len(audio_b64)//1024} KB")
    return audio_b64


def fix_srt_with_gemini(srt_content, original_script):
    print(f"🤖 ส่งซับไปให้ Gemini Flash จัดบรรทัดและเวลา SRT ใหม่ให้เป๊ะ...")
    prompt = f"""คุณคือผู้เชี่ยวชาญด้านการตัดต่อ Subtitle วิดีโอสั้นสไตล์ TikTok/Reels แบบคำปังๆ เน้นขึ้นโชว์ทีละบรรทัดสั้นๆ
นี่คือต้นฉบับบทพากย์ที่ถูกต้อง (Original Script):
{original_script}

และนี่คือไฟล์ SRT ที่ได้จากเสียงพูด (ซึ่งเวลายังรวบยาวเป็นก้อนใหญ่ๆ และมีคำสะกดผิด):
{srt_content}

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
    for attempt in range(3):
        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}]
                },
                timeout=120,
            ).json()
            
            if resp.get("error"):
                print(f"   ⚠️ Gemini Subtitling error: {resp['error'].get('message')}")
                if attempt == 2: return srt_content
                time.sleep(5)
                continue
                
            fixed_srt = resp.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            fixed_srt = fixed_srt.replace("```srt", "").replace("```", "").strip()
            print(f"   ✅ Gemini Flash แก้ซับไตเติ้ลเรียบร้อย!")
            return fixed_srt
        except Exception as e:
            if attempt == 2:
                print(f"   ⚠️ Gemini Error: {e}")
                return srt_content
            print(f"   ⚠️ Subtitle fix timeout/error, retrying... ({attempt+1}/3)")
            time.sleep(5)


def convert_to_ass(srt_file, ass_file, vw, vh):
    with open(srt_file, 'r', encoding='utf-8') as f:
        srt_content = f.read()
    
    # Scale font size optimally (~11.5% of width)
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


def ffmpeg_merge(video_path, audio_b64, output_path, script=None):
    print(f"🎬 รวมวิดีโอ + เสียง...")
    duration = get_duration(video_path)
    print(f"   วิดีโอยาว {duration:.1f} วินาที")

    with tempfile.TemporaryDirectory() as tmpdir:
        raw_audio = os.path.join(tmpdir, "audio.raw")
        wav_audio = os.path.join(tmpdir, "audio.wav")

        with open(raw_audio, "wb") as f:
            f.write(base64.b64decode(audio_b64))

        subprocess.run([
            "ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
            "-i", raw_audio, wav_audio
        ], check=True, capture_output=True)

        ap = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", wav_audio
        ], capture_output=True, text=True)
        audio_dur = float(ap.stdout.strip()) if ap.stdout.strip() else 0
        print(f"   เสียงพากย์ยาว {audio_dur:.1f} วินาที")

        adjusted = os.path.join(tmpdir, "audio_adj.wav")
        diff = duration - audio_dur
        if abs(diff) < 0.5:
            adjusted = wav_audio
        elif diff > 0:
            subprocess.run(["ffmpeg", "-y", "-i", wav_audio, "-af", f"apad=pad_dur={diff}", adjusted], capture_output=True)
        else:
            subprocess.run(["ffmpeg", "-y", "-i", wav_audio, "-t", str(duration), adjusted], capture_output=True)

        # Merge video + audio (ไม่มี subtitle ก่อน)
        merged_nosub = os.path.join(tmpdir, "merged_nosub.mp4")
        mr = subprocess.run([
            "ffmpeg", "-y", "-i", video_path, "-i", adjusted,
            "-c:v", "copy", "-c:a", "aac",
            "-map", "0:v:0", "-map", "1:a:0",
            "-t", str(duration), merged_nosub
        ], capture_output=True, text=True)
        if mr.returncode != 0:
            raise Exception(f"FFmpeg merge failed: {mr.stderr[-500:]}")

        # Burn subtitle ด้วย FFmpeg Native
        if script:
            print(f"📝 Transcribing ด้วย Whisper เพื่อเวลาที่เป๊ะที่สุด...")
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
            ], check=True)
            
            srt_name = os.path.splitext(os.path.basename(adjusted))[0] + ".srt"
            srt_path = os.path.join(tmpdir, srt_name)
            
            with open(srt_path, "r", encoding="utf-8") as fs:
                raw_srt_text = fs.read()
            
            fixed_srt_content = fix_srt_with_gemini(raw_srt_text, script)
            
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
            
            convert_to_ass(srt_path, ass_path, vw, vh)
            print(f"🎬 กำลังฝังซับไตเติ้ลด้วย FFmpeg Native (Hardware Accelerated)...")
            
            import shutil
            shutil.copy(srt_path, os.path.abspath("debug_subtitles.srt"))
            shutil.copy(ass_path, os.path.abspath("debug_subtitles.ass"))
            
            font_src = os.path.abspath("FC Iconic Bold.ttf")
            
            ffmpeg_check = subprocess.run(["ffmpeg", "-filters"], capture_output=True, text=True)
            if " ass " in ffmpeg_check.stdout:
                cwd_cmd = os.path.abspath(tmpdir)
                if os.path.exists(font_src):
                    shutil.copy(font_src, os.path.join(cwd_cmd, "font.ttf"))
                
                mr = subprocess.run([
                    "ffmpeg", "-y", "-i", merged_nosub,
                    "-vf", f"ass={ass_path}:fontsdir={cwd_cmd}",
                    "-c:v", "libx264", "-c:a", "copy", "-preset", "fast", output_path
                ], capture_output=True, text=True)
            else:
                print("   [INFO] ไม่พบ libass ใน FFmpeg เครื่องนี้ -> อัญเชิญ Docker มาทำแทน!")
                
                # macOS Docker can't mount /var/folders (symlink) -> use project dir instead
                docker_work = os.path.abspath("_docker_work")
                os.makedirs(docker_work, exist_ok=True)
                
                shutil.copy(merged_nosub, os.path.join(docker_work, "input.mp4"))
                shutil.copy(ass_path, os.path.join(docker_work, "subtitles.ass"))
                if os.path.exists(font_src):
                    shutil.copy(font_src, os.path.join(docker_work, "font.ttf"))
                
                out_name = os.path.basename(output_path)
                out_dir = os.path.abspath(os.path.dirname(output_path) or ".")
                
                print(f"   📂 Docker work dir: {docker_work}")
                print(f"   📂 Output dir: {out_dir}")
                
                mr = subprocess.run([
                    "docker", "run", "--rm", 
                    "-v", f"{docker_work}:/work", 
                    "-v", f"{out_dir}:/outdir",
                    "-w", "/work", 
                    "-e", "HOME=/work",
                    "mwader/static-ffmpeg:7.0.2",
                    "-y", "-i", "input.mp4",
                    "-vf", "ass=subtitles.ass:fontsdir=/work",
                    "-c:v", "libx264", "-c:a", "copy", "-preset", "fast", f"/outdir/{out_name}"
                ], capture_output=True, text=True)
                
                # cleanup docker work dir
                shutil.rmtree(docker_work, ignore_errors=True)
                
            if mr.returncode != 0:
                print(f"   ⚠️ FFmpeg sub error: {mr.stderr[-1000:] if hasattr(mr, 'stderr') and mr.stderr else 'Unknown'}")
                shutil.move(merged_nosub, output_path)
            else:
                print(f"   ✅ Docker FFmpeg log:\n{mr.stderr[-1000:]}")
                
        else:
            import shutil
            shutil.move(merged_nosub, output_path)

    out_size = os.path.getsize(output_path) / 1024 / 1024
    print(f"   ✅ เสร็จ! ขนาด {out_size:.1f} MB → {output_path}")


def main():
    if len(sys.argv) < 2:
        print("ใช้: python scripts/test_pipeline.py <video_file_or_url>")
        print("ตัวอย่าง:")
        print("  python scripts/test_pipeline.py video.mp4")
        print("  python scripts/test_pipeline.py https://xhslink.com/xxxxx")
        sys.exit(1)

    input_path = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else "output.mp4"

    print(f"\n{'='*50}")
    print(f"🎬 ทดสอบ Pipeline พากย์เสียง — เฉียบ")
    print(f"{'='*50}\n")

    is_local = os.path.exists(input_path)

    if is_local:
        print(f"📁 ใช้ไฟล์ local: {input_path}")
        tmp_video = input_path
        with open(input_path, "rb") as f:
            video_bytes = f.read()
        print(f"   ✅ ขนาด {len(video_bytes)/1024/1024:.1f} MB")
    else:
        url = input_path
        video_url = url
        if "xhs" in url or "xiaohongshu" in url:
            print(f"🔗 Resolve XHS link...")
            video_url = resolve_xhs(url)
            if not video_url:
                print("❌ ไม่พบวิดีโอใน XHS link")
                sys.exit(1)
            print(f"   ✅ {video_url[:80]}...")

        video_bytes = download_video(video_url)
        tmp_video = "temp_input.mp4"
        with open(tmp_video, "wb") as f:
            f.write(video_bytes)

    try:
        file_uri, file_name = gemini_upload(video_bytes)
        gemini_wait(file_name)
        
        duration = get_duration(tmp_video)
        script, title, category = gemini_script(file_uri, duration)
        audio_b64 = gemini_tts(script)
        ffmpeg_merge(tmp_video, audio_b64, output, script=script)

        print(f"\n{'='*50}")
        print(f"🎉 สำเร็จ!")
        print(f"📁 ไฟล์: {output}")
        print(f"📝 Script: {script}")
        print(f"📌 Title: {title}")
        print(f"📂 Category: {category}")
        print(f"{'='*50}\n")

    finally:
        if not is_local and os.path.exists(tmp_video):
            os.remove(tmp_video)


if __name__ == "__main__":
    main()
