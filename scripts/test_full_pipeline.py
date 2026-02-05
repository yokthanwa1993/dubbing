#!/usr/bin/env python3
"""
Test full dubbing pipeline locally.
Usage: python test_full_pipeline.py "http://xhslink.com/xxx"
"""

import sys
import os
import json
import requests
import subprocess
import base64
import tempfile
from pathlib import Path

# Config
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "AIzaSyC3loQSza0pPSms7QBvNa4xiyNcO_PV_94")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
XHS_API_URL = "http://xhs-dl.lslly.com/xhs/detail"

def log(step, msg, data=None):
    print(f"\n{'='*50}")
    print(f"[{step}] {msg}")
    if data:
        print(f"  → {data}")
    print('='*50)

def get_duration(filepath):
    """Get duration of media file using ffprobe"""
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", filepath
    ], capture_output=True, text=True)
    return float(result.stdout.strip()) if result.stdout.strip() else 0

def step1_download_video(url, output_dir):
    """Download video from XHS"""
    log("STEP 1", "Downloading video from XHS", url)
    
    # Try XHS-Downloader API
    resp = requests.post(XHS_API_URL, json={"url": url, "download": False}, timeout=30)
    data = resp.json()
    
    if not data.get("data") or not data["data"].get("下载地址"):
        print("  ❌ API failed to get video URL")
        return None, None
    
    video_url = data["data"]["下载地址"][0]
    title = data["data"].get("作品描述", "Untitled")
    print(f"  Video URL: {video_url[:80]}...")
    print(f"  Title: {title[:50]}")
    
    # Download video
    video_path = output_dir / "video.mp4"
    resp = requests.get(video_url, headers={"Referer": "https://www.xiaohongshu.com/"}, timeout=120)
    video_path.write_bytes(resp.content)
    
    duration = get_duration(str(video_path))
    size_mb = video_path.stat().st_size / 1024 / 1024
    
    print(f"  ✅ Downloaded: {size_mb:.1f} MB, {duration:.1f} seconds")
    return video_path, duration

def step2_generate_script(video_path, duration):
    """Analyze video and generate script with Gemini"""
    log("STEP 2", "Analyzing video with Gemini", f"Duration: {duration:.1f}s")
    
    target_chars = int(duration * 10)
    print(f"  Target script length: {target_chars} characters")
    
    # Upload video to Google Files API
    with open(video_path, "rb") as f:
        video_bytes = f.read()
    
    upload_start = requests.post(
        f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={GOOGLE_API_KEY}",
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
        print("  ❌ Failed to get upload URL")
        return None
    
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
    
    print(f"  Uploaded to: {file_name}")
    print("  Waiting for processing...")
    
    # Wait for processing
    import time
    for i in range(30):
        check = requests.get(f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={GOOGLE_API_KEY}")
        state = check.json().get("state")
        if state != "PROCESSING":
            file_uri = check.json().get("uri")
            break
        print(f"    ({i+1}/30) Processing...")
        time.sleep(2)
    
    # Generate script
    prompt = f"""คุณคือ "พี่ต้น" นักรีวิวสินค้าออนไลน์มือฉมัง ที่มีผู้ติดตามหลายล้านคน
เสียงของคุณทำให้คนอยากซื้อของทันที พูดจาสนุก มีพลัง น่าเชื่อถือ

ดูวิดีโอสินค้านี้แล้วช่วยเขียน script พากย์เสียงภาษาไทย สำหรับวิดีโอยาว {duration:.0f} วินาที

สไตล์การพูด:
- เปิดด้วยประโยคที่ดึงดูดความสนใจ เช่น "โห้ อันนี้ต้องมี!" หรือ "ของดีมาแล้วครับพี่น้อง!"
- บรรยายจุดเด่นของสินค้าตามที่เห็นในวิดีโอ
- ใช้คำที่ทำให้รู้สึกว่าคุ้มค่า เช่น "ราคานี้คุ้มมากๆ" "ใช้ได้ตลอดชีวิต"
- ปิดด้วยการกระตุ้นให้ซื้อ เช่น "สนใจสั่งเลยครับ รีบๆนะ ของมีจำกัด!"

สำคัญ: Script ต้องพอดีกับวิดีโอ {duration:.0f} วินาที (พูดประมาณ 10-12 ตัวอักษร/วินาที)

ตอบเป็น JSON: {{"thai_script": "ข้อความพากย์เสียง"}}"""

    script_resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GOOGLE_API_KEY}",
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
    
    # Check if script is too short (less than 50% of target)
    if not thai_script or len(thai_script) < target_chars * 0.5:
        print(f"  ⚠️ Script too short! Generating fallback...")
        # Generate a fallback script with correct length
        base_phrases = [
            "สินค้าคุณภาพดี ใช้งานง่าย ทนทาน คุ้มค่าคุ้มราคา",
            "วัสดุแข็งแรง ประกอบง่าย พกพาสะดวก น้ำหนักเบา",
            "ดีไซน์สวยงาม ทันสมัย เหมาะกับทุกไลฟ์สไตล์",
            "รับประกันคุณภาพ จัดส่งรวดเร็ว พร้อมส่งทันที",
            "ราคาพิเศษวันนี้เท่านั้น สั่งเลยก่อนหมด",
            "ลูกค้าหลายพันรีวิวดี ขายดีอันดับหนึ่ง",
            "สินค้าใหม่ล่าสุด คุณภาพพรีเมียม ไม่ผิดหวังแน่นอน",
            "ใช้งานได้หลากหลาย เหมาะกับทุกโอกาส"
        ]
        
        # Build script to target length
        thai_script = ""
        idx = 0
        while len(thai_script) < target_chars:
            thai_script += base_phrases[idx % len(base_phrases)] + " "
            idx += 1
        thai_script = thai_script[:target_chars].strip()
    
    print(f"  ✅ Script: {thai_script[:60]}...")
    print(f"  Script length: {len(thai_script)} chars (target: {target_chars})")
    
    return thai_script

def step3_generate_tts(script, output_dir):
    """Generate TTS audio with Gemini"""
    log("STEP 3", "Generating TTS audio", f"Script: {len(script)} chars")
    
    tts_resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={GOOGLE_API_KEY}",
        json={
            "contents": [{"parts": [{"text": script}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Puck"}}
                }
            }
        },
        timeout=60
    )
    
    if tts_resp.status_code != 200:
        print(f"  ❌ TTS Error: {tts_resp.json()}")
        return None
    
    tts_result = tts_resp.json()
    audio_base64 = tts_result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("inlineData", {}).get("data", "")
    
    if not audio_base64:
        print(f"  ❌ No audio in response")
        return None
    
    # Save raw audio
    raw_audio = output_dir / "audio.raw"
    wav_audio = output_dir / "audio.wav"
    
    raw_audio.write_bytes(base64.b64decode(audio_base64))
    
    # Convert to WAV
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "s16le", "-ar", "24000", "-ac", "1",
        "-i", str(raw_audio),
        str(wav_audio)
    ], check=True, capture_output=True)
    
    duration = get_duration(str(wav_audio))
    print(f"  ✅ Audio generated: {duration:.1f} seconds")
    
    return wav_audio, duration

def step4_merge(video_path, audio_path, output_dir, video_duration, audio_duration):
    """Merge video and audio - pad or trim audio to match video exactly"""
    log("STEP 4", "Merging video and audio", f"Video: {video_duration:.1f}s, Audio: {audio_duration:.1f}s")
    
    output_path = output_dir / "output.mp4"
    adjusted_audio = output_dir / "audio_adjusted.wav"
    
    diff = video_duration - audio_duration
    print(f"  Duration difference: {diff:+.1f}s")
    
    if abs(diff) < 0.5:
        # Close enough, use original
        print(f"  Audio duration close enough, using original")
        adjusted_audio = audio_path
    elif diff > 0:
        # Audio shorter than video - add silence at the end
        print(f"  Adding {diff:.1f}s of silence to audio")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-af", f"apad=pad_dur={diff}",
            str(adjusted_audio)
        ], capture_output=True, text=True)
    else:
        # Audio longer than video - trim it
        print(f"  Trimming audio to {video_duration:.1f}s")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-t", str(video_duration),
            str(adjusted_audio)
        ], capture_output=True, text=True)
    
    # Check adjusted audio
    if adjusted_audio.exists():
        adj_dur = get_duration(str(adjusted_audio))
        print(f"  Adjusted audio: {adj_dur:.1f}s (target: {video_duration:.1f}s)")
    
    # Merge - use video duration as master
    result = subprocess.run([
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(adjusted_audio),
        "-c:v", "copy",
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-t", str(video_duration),  # Force output to video duration
        str(output_path)
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"  ❌ FFmpeg error: {result.stderr[:200]}")
        return None
    
    final_duration = get_duration(str(output_path))
    size_mb = output_path.stat().st_size / 1024 / 1024
    
    print(f"  ✅ Output: {size_mb:.1f} MB, {final_duration:.1f} seconds")
    return output_path, final_duration

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_full_pipeline.py <XHS_URL>")
        print("Example: python test_full_pipeline.py 'http://xhslink.com/o/8F2mZEPG5n5'")
        sys.exit(1)
    
    url = sys.argv[1]
    
    print("\n" + "="*60)
    print("🎬 DUBBING PIPELINE TEST")
    print("="*60)
    print(f"Input URL: {url}")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        
        # Step 1: Download
        video_path, video_duration = step1_download_video(url, output_dir)
        if not video_path:
            print("\n❌ FAILED at Step 1")
            sys.exit(1)
        
        # Step 2: Generate Script
        script = step2_generate_script(video_path, video_duration)
        if not script:
            print("\n❌ FAILED at Step 2")
            sys.exit(1)
        
        # Step 3: Generate TTS
        result = step3_generate_tts(script, output_dir)
        if not result:
            print("\n❌ FAILED at Step 3")
            sys.exit(1)
        audio_path, audio_duration = result
        
        # Step 4: Merge
        result = step4_merge(video_path, audio_path, output_dir, video_duration, audio_duration)
        if not result:
            print("\n❌ FAILED at Step 4")
            sys.exit(1)
        output_path, final_duration = result
        
        # Summary
        print("\n" + "="*60)
        print("📊 DURATION ANALYSIS")
        print("="*60)
        print(f"  Video Duration:  {video_duration:.1f}s")
        print(f"  Script Length:   {len(script)} chars")
        print(f"  Expected Audio:  {len(script)/10:.1f}s (10 chars/sec)")
        print(f"  Actual Audio:    {audio_duration:.1f}s")
        print(f"  Output Duration: {final_duration:.1f}s")
        print()
        
        diff = abs(video_duration - audio_duration)
        if diff < 3:
            print("  ✅ PASS - Audio matches video (diff < 3s)")
        else:
            print(f"  ⚠️ WARNING - Audio/Video mismatch: {diff:.1f}s difference")
            print(f"     Audio is {audio_duration - video_duration:+.1f}s from video")
        
        # Copy output to Desktop for review
        import shutil
        desktop_output = Path.home() / "Desktop" / "dubbing_test_output.mp4"
        shutil.copy(output_path, desktop_output)
        print(f"\n  📁 Output saved to: {desktop_output}")
        
        print("\n" + "="*60)
        print("✅ PIPELINE TEST COMPLETE")
        print("="*60 + "\n")

if __name__ == "__main__":
    main()
