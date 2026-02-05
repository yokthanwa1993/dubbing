#!/usr/bin/env python3
"""Test script to run on server to debug pipeline"""

import os
import sys
import requests
import json

# Config from environment
GOOGLE_API_KEY = os.environ.get("gemini", "")
TELEGRAM_BOT_TOKEN = os.environ.get("telegram_bot", "")
FB_PAGE_ID = os.environ.get("fb_page_id", "")
FB_PAGE_TOKEN = os.environ.get("fb_page_token", "")

print("=" * 60)
print("DUBBING API SERVER TEST")
print("=" * 60)

print(f"\n[1] Environment Variables:")
print(f"  GOOGLE_API_KEY: {'✅ Set' if GOOGLE_API_KEY else '❌ Not set'}")
print(f"  TELEGRAM_BOT_TOKEN: {'✅ Set' if TELEGRAM_BOT_TOKEN else '❌ Not set'}")
print(f"  FB_PAGE_ID: {'✅ Set' if FB_PAGE_ID else '❌ Not set'}")
print(f"  FB_PAGE_TOKEN: {'✅ Set' if FB_PAGE_TOKEN else '❌ Not set'}")

print(f"\n[2] Testing XHS API...")
try:
    xhs_resp = requests.post(
        "http://xhs-dl.lslly.com/xhs/detail",
        json={"url": "http://xhslink.com/o/1FMeg0lloOe", "download": False},
        timeout=60
    )
    xhs_data = xhs_resp.json()
    if xhs_data.get("data"):
        print(f"  ✅ XHS API works! Got data for video")
        video_urls = xhs_data["data"].get("下载地址", [])
        print(f"  Video URLs: {len(video_urls)} found")
        if video_urls:
            print(f"  First URL: {video_urls[0][:80]}...")
    else:
        print(f"  ❌ XHS API returned no data: {str(xhs_data)[:200]}")
except Exception as e:
    print(f"  ❌ XHS API error: {e}")

print(f"\n[3] Testing Telegram Bot...")
if TELEGRAM_BOT_TOKEN:
    try:
        tg_resp = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=10)
        tg_data = tg_resp.json()
        if tg_data.get("ok"):
            print(f"  ✅ Telegram Bot works! @{tg_data['result']['username']}")
        else:
            print(f"  ❌ Telegram error: {tg_data}")
    except Exception as e:
        print(f"  ❌ Telegram error: {e}")
else:
    print(f"  ⚠️ Skipped - no token")

print(f"\n[4] Testing Gemini API...")
if GOOGLE_API_KEY:
    try:
        gemini_resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GOOGLE_API_KEY}",
            json={"contents": [{"parts": [{"text": "Say 'hello' in Thai"}]}]},
            timeout=30
        )
        if gemini_resp.status_code == 200:
            print(f"  ✅ Gemini API works!")
        else:
            print(f"  ❌ Gemini error: {gemini_resp.status_code} - {gemini_resp.text[:200]}")
    except Exception as e:
        print(f"  ❌ Gemini error: {e}")
else:
    print(f"  ⚠️ Skipped - no key")

print(f"\n[5] Testing internal full-pipeline call...")
try:
    resp = requests.post(
        "http://127.0.0.1:80/health",
        timeout=5
    )
    print(f"  Health check: {resp.status_code} - {resp.text[:100]}")
except Exception as e:
    print(f"  ❌ Internal call error: {e}")

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
