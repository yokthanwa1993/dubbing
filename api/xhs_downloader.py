#!/usr/bin/env python3
"""Xiaohongshu downloader using XHS-Downloader API (no playwright needed)."""

import asyncio
import re
from pathlib import Path
import httpx
import requests

# Playwright is optional - only needed for fallback
try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("[XHS] Playwright not installed, using API-only mode")

# XHS-Downloader API endpoint - use HTTPS for Docker compatibility
XHS_API_URL = "https://xhs-dl.lslly.com/xhs/detail"


async def get_video_url_from_api(url: str) -> dict | None:
    """Try to get video URL from XHS-Downloader API first (faster and more reliable)."""
    try:
        # Resolve short link first
        if "xhslink.com" in url:
            print(f"[XHS] Resolving short link: {url}")
            try:
                redirect_resp = requests.head(url, allow_redirects=True, timeout=30)
                if redirect_resp.url and "xiaohongshu.com" in redirect_resp.url:
                    url = redirect_resp.url
                    print(f"[XHS] Resolved to: {url}")
            except Exception as e:
                print(f"[XHS] Short link resolution failed: {e}, trying original URL")
        
        print(f"[XHS] Trying XHS-Downloader API: {XHS_API_URL}")
        print(f"[XHS] URL to fetch: {url}")
        resp = requests.post(
            XHS_API_URL,
            json={"url": url, "download": False},
            timeout=120
        )
        print(f"[XHS] API Response status: {resp.status_code}")
        data = resp.json()
        print(f"[XHS] API Response keys: {list(data.keys())}")
        
        if data.get("data") and data["data"].get("下载地址"):
            video_urls = data["data"]["下载地址"]
            title = data["data"].get("作品描述", "")
            author = data["data"].get("作者昵称", "")
            print(f"[XHS] API success! Found {len(video_urls)} video URLs")
            print(f"[XHS] First URL: {video_urls[0][:80]}..." if video_urls else "[XHS] No URLs")
            return {
                "video_urls": [u for u in video_urls if u],
                "image_urls": [],
                "title": title,
                "author": author
            }
        else:
            print(f"[XHS] API returned no video URLs. Response: {str(data)[:300]}")
    except Exception as e:
        print(f"[XHS] API failed with exception: {e}")
        import traceback
        print(f"[XHS] Traceback: {traceback.format_exc()}")
    return None


# Default cookies - update these from browser if needed
DEFAULT_COOKIES = [
    {"name": "a1", "value": "19a90f6bc56svf6e84o8s43lqt5jhn8fo6hcjfvpb30000518932", "domain": ".xiaohongshu.com", "path": "/"},
    {"name": "webId", "value": "7adabb4b2bc4bfdd80f18f30754b1728", "domain": ".xiaohongshu.com", "path": "/"},
    {"name": "web_session", "value": "040069b2a37562cb56388332593b4b7d7dd974", "domain": ".xiaohongshu.com", "path": "/"},
    {"name": "xsecappid", "value": "xhs-pc-web", "domain": ".xiaohongshu.com", "path": "/"},
]


async def resolve_short_url(short_url: str, cookies: list = None) -> str | None:
    """Resolve xhslink.com short URL to full URL."""
    if "xhslink.com" not in short_url and "xiaohongshu.com" in short_url:
        return short_url  # Already full URL

    if cookies is None:
        cookies = DEFAULT_COOKIES

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        try:
            await page.goto(short_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            return page.url
        except Exception as e:
            print(f"Error resolving URL: {e}")
            return None
        finally:
            await browser.close()


async def get_xhs_video_url(url: str, cookies: list = None) -> dict | None:
    """Extract video/image URLs from Xiaohongshu page."""
    if cookies is None:
        cookies = DEFAULT_COOKIES

    result = {
        "video_urls": [],
        "image_urls": [],
        "title": None,
        "author": None,
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        # Intercept network requests for video URLs
        async def handle_response(response):
            resp_url = response.url
            if "sns-video" in resp_url and ".mp4" in resp_url:
                if resp_url not in result["video_urls"]:
                    result["video_urls"].append(resp_url)
            elif "sns-webpic" in resp_url or "sns-img" in resp_url:
                if ".jpg" in resp_url or ".png" in resp_url or ".webp" in resp_url:
                    if resp_url not in result["image_urls"]:
                        result["image_urls"].append(resp_url)

        page.on("response", handle_response)

        try:
            # Navigate to URL (short URLs will auto-redirect)
            print(f"[XHS] Navigating to: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Get the final URL after redirect
            final_url = page.url
            print(f"[XHS] Final URL after redirect: {final_url}")

            # Wait for video to load and network requests to complete
            print("[XHS] Waiting for video to load...")
            await asyncio.sleep(8)
            
            # Also try clicking play button if exists
            try:
                play_btn = await page.query_selector('video, .player-container, [class*="video"]')
                if play_btn:
                    await play_btn.click()
                    await asyncio.sleep(2)
            except:
                pass
            
            print(f"[XHS] Found {len(result['video_urls'])} video URLs, {len(result['image_urls'])} image URLs")
            
            # If no video URLs from network, try extracting from __INITIAL_STATE__
            if not result["video_urls"]:
                print("[XHS] Trying to extract from __INITIAL_STATE__...")
                try:
                    video_info = await page.evaluate("""
                        () => {
                            if (window.__INITIAL_STATE__) {
                                const state = window.__INITIAL_STATE__;
                                const noteId = Object.keys(state.note?.noteDetailMap || {})[0];
                                if (noteId) {
                                    const note = state.note.noteDetailMap[noteId]?.note;
                                    if (note && note.video) {
                                        const video = note.video;
                                        const urls = [];
                                        // Get H264 stream (more compatible)
                                        if (video.media?.stream?.h264?.[0]?.masterUrl) {
                                            urls.push(video.media.stream.h264[0].masterUrl);
                                        }
                                        // Get backup URL
                                        if (video.media?.stream?.h265?.[0]?.masterUrl) {
                                            urls.push(video.media.stream.h265[0].masterUrl);
                                        }
                                        // Also try consumer
                                        if (video.consumer?.originVideoKey) {
                                            urls.push('http://sns-video-bd.xhscdn.com/' + video.consumer.originVideoKey);
                                        }
                                        return {
                                            urls: urls,
                                            title: note.title,
                                            author: note.user?.nickname
                                        };
                                    }
                                }
                            }
                            return null;
                        }
                    """)
                    if video_info and video_info.get("urls"):
                        result["video_urls"] = video_info["urls"]
                        result["title"] = video_info.get("title")
                        result["author"] = video_info.get("author")
                        print(f"[XHS] Extracted {len(result['video_urls'])} video URLs from __INITIAL_STATE__")
                except Exception as e:
                    print(f"[XHS] Error extracting from __INITIAL_STATE__: {e}")

            # Try to get title
            try:
                title_el = await page.query_selector('meta[name="og:title"], meta[property="og:title"], .title, h1')
                if title_el:
                    result["title"] = await title_el.get_attribute("content") or await title_el.inner_text()
            except:
                pass

            return result

        except asyncio.TimeoutError:
            print(f"[XHS] Timeout! But captured: {len(result['video_urls'])} videos, {len(result['image_urls'])} images")
            # Even if timeout, we might have captured video URLs
            if result["video_urls"] or result["image_urls"]:
                return result
            return None
        except Exception as e:
            print(f"[XHS] Error: {e}")
            if result["video_urls"] or result["image_urls"]:
                return result
            return None
        finally:
            await browser.close()


async def download_xhs_content(url: str, output_dir: Path, cookies: list = None) -> Path | list[Path] | None:
    """Download video or images from Xiaohongshu URL."""
    if cookies is None:
        cookies = DEFAULT_COOKIES

    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    print(f"[XHS-DL] Starting download for: {url}")
    
    # Try XHS-Downloader API first (faster and more reliable)
    result = await get_video_url_from_api(url)
    print(f"[XHS-DL] API result: {result is not None}, has video_urls: {bool(result and result.get('video_urls'))}")
    
    # Fallback to Playwright if API fails AND playwright is available
    if not result or not result.get("video_urls"):
        if HAS_PLAYWRIGHT:
            print("[XHS-DL] API failed or no video, trying Playwright...")
            result = await get_xhs_video_url(url, cookies)
        else:
            print("[XHS-DL] API failed and Playwright not available")
    
    if not result:
        print("[XHS-DL] No result from API or Playwright, returning None")
        return None

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.xiaohongshu.com/",
    }

    async with httpx.AsyncClient() as client:
        # Download video if available
        if result["video_urls"]:
            video_url = result["video_urls"][0]  # Get first (usually best quality)
            print(f"[XHS-DL] Got video URL: {video_url[:80]}...")

            # Extract note ID from URL
            note_id_match = re.search(r'/explore/([a-f0-9]+)', url)
            note_id = note_id_match.group(1) if note_id_match else "video"

            video_path = output_dir / f"xhs_{note_id}.mp4"
            print(f"[XHS-DL] Downloading to: {video_path}")

            try:
                resp = await client.get(video_url, headers=headers, follow_redirects=True, timeout=120)
                print(f"[XHS-DL] Download response status: {resp.status_code}, size: {len(resp.content)} bytes")
                resp.raise_for_status()
                video_path.write_bytes(resp.content)
                print(f"[XHS-DL] Video saved successfully: {video_path}")
                return video_path
            except Exception as e:
                print(f"[XHS-DL] Error downloading video: {e}")
                return None

        # Download images if no video
        elif result["image_urls"]:
            downloaded = []
            for i, img_url in enumerate(result["image_urls"][:10]):  # Limit to 10 images
                img_path = output_dir / f"xhs_image_{i+1}.jpg"
                try:
                    resp = await client.get(img_url, headers=headers, follow_redirects=True, timeout=60)
                    resp.raise_for_status()
                    img_path.write_bytes(resp.content)
                    downloaded.append(img_path)
                except Exception as e:
                    print(f"Error downloading image {i+1}: {e}")
            return downloaded if downloaded else None

    return None


# For testing
if __name__ == "__main__":
    import sys

    async def main():
        if len(sys.argv) < 2:
            print("Usage: python xhs_downloader.py <url>")
            sys.exit(1)

        url = sys.argv[1]
        output_dir = Path("downloads")

        print(f"Downloading from: {url}")
        result = await download_xhs_content(url, output_dir)

        if result:
            if isinstance(result, list):
                print(f"Downloaded {len(result)} images:")
                for p in result:
                    print(f"  - {p}")
            else:
                print(f"Downloaded video: {result}")
        else:
            print("Failed to download")
            sys.exit(1)

    asyncio.run(main())
