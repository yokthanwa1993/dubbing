#!/usr/bin/env python3
"""
Full Pipeline: XHS → Dub → Facebook Reels
Usage: python full_pipeline.py <xhs_url> [voice] [description]
"""
import requests
import json
import base64
import subprocess
import sys
import os
import time
import re
from pathlib import Path

# Config
CF_ACCOUNT_ID = "bc9db0f4b48f964b6e445dccc240af87"
CF_GATEWAY_NAME = "google"
GOOGLE_API_KEY = "AIzaSyASbwx4jgnU8udf6BCteOdD8h20Wh8hmis"
GATEWAY_URL = f"https://gateway.ai.cloudflare.com/v1/{CF_ACCOUNT_ID}/{CF_GATEWAY_NAME}/google-ai-studio"

FB_PAGE_ID = "779838995206144"
FB_PAGE_TOKEN = "EAAChZCKmUTDcBQrUy3iRtSRHPJlFPgwa2sO3bRTSETIOZAsBKwCa2MEHT0ZCzLoNAeFh60d2EzSzfTw6GPfrDLcdPgqmCHQFlAr1Rm6Nx2P0FgTCJDoU8o6Liq8sbKFX5xRZCbl9APSyumblduWJYMiJZAvpV9iScoc6ZCZAmujZCl3ABUqKpXZAkRrHhfp2rs690JGrVBM7fNQYtOydhmhg0"

OUTPUT_DIR = Path("assets")


def download_xhs(url: str) -> Path:
    """Download XHS video using yt-dlp with Chrome cookies."""
    print("📥 Downloading XHS video...")
    
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    import hashlib
    note_id = hashlib.md5(url.encode()).hexdigest()[:8]
    output_path = OUTPUT_DIR / f"xhs_{note_id}.mp4"
    
    subprocess.run([
        "yt-dlp", 
        "--cookies-from-browser", "chrome",
        url, 
        "-o", str(output_path), 
        "--no-warnings"
    ], capture_output=True, timeout=120)
    
    if output_path.exists():
        size = output_path.stat().st_size / 1024 / 1024
        print(f"   ✅ Downloaded: {output_path} ({size:.1f} MB)")
        return output_path
    else:
        raise Exception("Download failed")


def get_video_duration(video_path: str) -> float:
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", video_path
    ], capture_output=True, text=True)
    return float(json.loads(probe.stdout)["format"]["duration"])


def upload_video_to_google(video_path: str) -> str:
    print("📤 Uploading to Google...")
    
    file_size = os.path.getsize(video_path)
    
    start_response = requests.post(
        f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={GOOGLE_API_KEY}",
        headers={
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(file_size),
            "X-Goog-Upload-Header-Content-Type": "video/mp4",
            "Content-Type": "application/json",
        },
        json={"file": {"display_name": os.path.basename(video_path)}},
    )
    
    upload_url = start_response.headers.get("X-Goog-Upload-URL")
    
    with open(video_path, "rb") as f:
        upload_response = requests.post(upload_url, headers={
            "X-Goog-Upload-Command": "upload, finalize",
            "X-Goog-Upload-Offset": "0",
            "Content-Type": "video/mp4",
        }, data=f.read())
    
    result = upload_response.json()
    file_name = result["file"]["name"]
    file_state = result["file"].get("state", "ACTIVE")
    
    while file_state == "PROCESSING":
        print("   ⏳ Processing...")
        time.sleep(3)
        check = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={GOOGLE_API_KEY}"
        )
        result = check.json()
        file_state = result.get("state", "ACTIVE")
    
    print(f"   ✅ Uploaded")
    return result["uri"]


def generate_script(file_uri: str, target_duration: float, adjustment: str = None) -> str:
    print(f"🤖 Generating script for {target_duration:.1f}s...")
    
    endpoint = f"{GATEWAY_URL}/v1beta/models/gemini-3-flash-preview:generateContent"
    
    prompt = f"""วิเคราะห์วิดีโอนี้และสร้าง script ภาษาไทยสำหรับพากย์เสียง

- วิดีโอยาว {target_duration:.0f} วินาที
- TTS พูดได้ประมาณ 10 ตัวอักษร/วินาที
- Script ต้องมีประมาณ {int(target_duration * 10)} ตัวอักษร

{f'หมายเหตุ: {adjustment}' if adjustment else ''}

ตอบเป็น JSON: {{"thai_script": "ข้อความ", "char_count": จำนวน}}"""

    payload = {
        "contents": [{"parts": [
            {"fileData": {"mimeType": "video/mp4", "fileUri": file_uri}},
            {"text": prompt}
        ]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 2048}
    }
    
    for retry in range(3):
        response = requests.post(endpoint, headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GOOGLE_API_KEY,
        }, json=payload, timeout=120)
        
        if response.status_code == 200:
            break
        elif response.status_code in [429, 503]:
            print(f"   ⏳ Rate limited, waiting...")
            time.sleep((retry + 1) * 10)
    
    result = response.json()
    text = result["candidates"][0]["content"]["parts"][0]["text"]
    text = text.replace("```json", "").replace("```", "").strip()
    
    try:
        script = json.loads(text).get("thai_script", "")
    except:
        match = re.search(r'"thai_script":\s*"([^"]+)"', text)
        script = match.group(1) if match else text
    
    print(f"   ✅ Script: {len(script)} chars")
    return script


def generate_tts(text: str, voice: str) -> tuple[bytes, float]:
    print("🎙️ Generating TTS...")
    endpoint = f"{GATEWAY_URL}/v1beta/models/gemini-2.5-flash-preview-tts:generateContent"
    
    response = requests.post(endpoint, headers={
        "Content-Type": "application/json",
        "x-goog-api-key": GOOGLE_API_KEY,
    }, json={
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}
        }
    }, timeout=120)
    
    result = response.json()
    audio_bytes = base64.b64decode(result["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
    duration = len(audio_bytes) / 48000
    print(f"   ✅ Audio: {duration:.1f}s")
    return audio_bytes, duration


def merge_audio_video(video_path: str, audio_bytes: bytes, output_path: str):
    print("🎬 Merging audio with video...")
    
    raw_audio = output_path.replace(".mp4", "_audio.raw")
    wav_audio = output_path.replace(".mp4", "_audio.wav")
    
    with open(raw_audio, "wb") as f:
        f.write(audio_bytes)
    
    subprocess.run(["sox", "-r", "24000", "-e", "signed", "-b", "16", "-c", "1", raw_audio, wav_audio], 
                   check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-i", video_path, "-i", wav_audio, "-c:v", "copy", 
                    "-map", "0:v:0", "-map", "1:a:0", output_path], 
                   check=True, capture_output=True)
    
    for f in [raw_audio, wav_audio]:
        if os.path.exists(f):
            os.remove(f)
    
    print(f"   ✅ Output: {output_path}")


def upload_to_facebook_reels(video_path: str, description: str) -> str:
    print("📤 Uploading to Facebook Reels...")
    
    # Step 1: Initialize upload
    init_response = requests.post(
        f"https://graph.facebook.com/v21.0/{FB_PAGE_ID}/video_reels",
        json={
            "upload_phase": "start",
            "access_token": FB_PAGE_TOKEN,
        }
    )
    init_result = init_response.json()
    if "error" in init_result:
        raise Exception(f"Init failed: {init_result['error']['message']}")
    
    video_id = init_result["video_id"]
    upload_url = init_result["upload_url"]
    print(f"   Video ID: {video_id}")
    
    # Step 2: Upload video file
    file_size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        upload_response = requests.post(
            upload_url,
            headers={
                "Authorization": f"OAuth {FB_PAGE_TOKEN}",
                "offset": "0",
                "file_size": str(file_size),
            },
            data=f.read(),
        )
    
    upload_result = upload_response.json()
    if "error" in upload_result:
        raise Exception(f"Upload failed: {upload_result['error']['message']}")
    print(f"   ✅ Uploaded")
    
    # Step 3: Publish
    publish_response = requests.post(
        f"https://graph.facebook.com/v21.0/{FB_PAGE_ID}/video_reels",
        json={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": description,
            "access_token": FB_PAGE_TOKEN,
        }
    )
    publish_result = publish_response.json()
    if "error" in publish_result:
        raise Exception(f"Publish failed: {publish_result['error']['message']}")
    
    reel_url = f"https://www.facebook.com/reel/{video_id}"
    print(f"   ✅ Published: {reel_url}")
    
    return reel_url


def main():
    if len(sys.argv) < 2:
        print("Usage: python full_pipeline.py <xhs_url> [voice] [description]")
        print("Example: python full_pipeline.py 'http://xhslink.com/xxx' Puck 'คำอธิบาย'")
        sys.exit(1)
    
    url = sys.argv[1]
    voice = sys.argv[2] if len(sys.argv) > 2 else "Puck"
    description = sys.argv[3] if len(sys.argv) > 3 else ""
    
    print("=" * 60)
    print("🚀 FULL PIPELINE: XHS → Dub → Facebook Reels")
    print("=" * 60)
    print(f"🔗 URL: {url}")
    print(f"🎤 Voice: {voice}")
    print("=" * 60)
    
    # Step 1: Download XHS
    video_path = download_xhs(url)
    
    # Step 2: Get duration
    duration = get_video_duration(str(video_path))
    print(f"⏱️ Duration: {duration:.1f}s")
    
    # Step 3: Upload & Analyze
    file_uri = upload_video_to_google(str(video_path))
    
    # Step 4: Generate matching audio
    best_script = None
    best_audio = None
    best_diff = float('inf')
    
    for attempt in range(3):
        print(f"\n🔄 Attempt {attempt + 1}/3")
        
        adjustment = None
        if best_diff != float('inf'):
            if best_diff > 0:
                adjustment = f"Script ก่อนหน้ายาวเกินไป {best_diff:.1f}s"
            else:
                adjustment = f"Script ก่อนหน้าสั้นเกินไป {abs(best_diff):.1f}s"
        
        script = generate_script(file_uri, duration, adjustment)
        audio_bytes, audio_duration = generate_tts(script, voice)
        
        diff = audio_duration - duration
        print(f"   Duration diff: {diff:+.1f}s")
        
        if abs(diff) < abs(best_diff):
            best_script, best_audio, best_diff = script, audio_bytes, diff
        
        if abs(diff) <= 1.0:
            print("   ✅ Within tolerance!")
            break
    
    print(f"\n📝 Script:\n{best_script}\n")
    
    # Step 5: Merge audio
    dubbed_path = str(video_path).replace(".mp4", "_thai.mp4")
    merge_audio_video(str(video_path), best_audio, dubbed_path)
    
    # Step 6: Upload to Facebook Reels
    final_description = description or best_script[:100] + "..."
    reel_url = upload_to_facebook_reels(dubbed_path, final_description)
    
    print("\n" + "=" * 60)
    print("✅ DONE!")
    print("=" * 60)
    print(f"📹 Dubbed Video: {dubbed_path}")
    print(f"🎬 Facebook Reel: {reel_url}")
    
    # Open the reel
    subprocess.run(["open", reel_url])


if __name__ == "__main__":
    main()
