# AI Dubbing Pipeline - Architecture

## สถาปัตยกรรมปัจจุบัน

### CF Worker = API + Webhook + Cron ทั้งหมด
### CapRover = แค่รัน Pipeline หลังบ้าน (ffmpeg + ประมวลผลหนัก)

---

## Components

### 1. CF Worker (`dubbing-worker`)
**URL**: `https://dubbing-worker.yokthanwa1993-bc9.workers.dev`
**Source**: `worker/src/index.ts`

API ทั้งหมดอยู่ที่นี่:
| Endpoint | Method | หน้าที่ |
|----------|--------|---------|
| `/api/telegram` | POST | **Telegram Webhook** — รับข้อความจาก Telegram |
| `/api/gallery` | GET | ดึงรายการวีดีโอทั้งหมด (จาก R2 cache) |
| `/api/gallery/:id` | GET | ดึง metadata วีดีโอรายตัว |
| `/api/pages` | GET | ดึงรายการ Facebook Pages |
| `/api/pages/import` | POST | นำเข้า Pages จาก Facebook Token |
| `/api/pages/:id` | PUT | อัพเดทการตั้งค่าเพจ (post_hours, is_active) |
| `/api/pages/:id` | DELETE | ลบเพจ |
| `/api/pages/:id/force-post` | POST | บังคับโพสต์วีดีโอไปเพจนั้นทันที |
| `/api/dedup` | DELETE | ล้าง dedup keys ที่ค้าง |
| `cron */5 * * * *` | — | **Auto-post** ตรวจสอบทุก 5 นาที โพสต์ Facebook Reels ตามเวลาที่ตั้งไว้ |

Bindings:
- **D1** (`DB`) — database `dubbing-db`
- **R2** (`BUCKET`) — bucket `dubbing-videos`
- **Secrets** — `GOOGLE_API_KEY`, `TELEGRAM_BOT_TOKEN`
- **Vars** — `CORS_ORIGIN`, `R2_PUBLIC_URL`, `XHS_DL_URL`, `CAPROVER_MERGE_URL`, `GEMINI_MODEL`

### 2. CapRover (`dubbing-api`)
**URL**: `https://dubbing-api.lslly.com`
**Source**: `api/server.py` (Flask)

CapRover ทำแค่งานหนักที่ต้องใช้ ffmpeg:
| Endpoint | Method | หน้าที่ |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/pipeline` | POST | **รัน pipeline ทั้งหมด** (background thread) — ดาวน์โหลด, Gemini, TTS, ffmpeg merge, R2 upload, แจ้ง Telegram |
| `/merge` | POST | Legacy: merge video+audio อย่างเดียว |

Env vars (ตั้งใน CapRover dashboard):
```
TELEGRAM_BOT_TOKEN, GOOGLE_API_KEY, GEMINI_MODEL
R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_PUBLIC_URL
XHS_DL_URL, WORKER_URL
```

### 3. Webapp (`dubbing-webapp`)
**URL**: `https://dubbing-webapp.pages.dev`
**Source**: `webapp/src/App.tsx` (React + Vite)

Telegram Mini App — ใช้ `WORKER_URL` เรียก API ทั้งหมด:
- **Home** — Dashboard + Stats
- **Gallery** — แสดงวีดีโอทั้งหมดจาก R2
- **Logs** — Activity logs
- **Pages** — จัดการ Facebook Pages (เปิด/ปิด auto-post, ตั้งเวลาโพสต์)
- **Settings** — ตั้งค่า

### 4. R2 Storage (`dubbing-videos`)
```
videos/{id}.json          — metadata (script, publicUrl, shopeeLink, duration, ...)
videos/{id}.mp4           — วีดีโอ merged (พากย์เสียงแล้ว)
videos/{id}_original.mp4  — วีดีโอต้นฉบับ
_cache/gallery.json       — gallery cache (rebuild โดย CapRover หลัง pipeline เสร็จ)
_dedup/{update_id}        — กัน Telegram retry (ห้ามลบมัน ยกเว้นค้าง → DELETE /api/dedup)
_pending_shopee/{chatId}.json — รอ Shopee link หลัง pipeline เสร็จ
```

### 5. D1 Database (`dubbing-db`)
```sql
pages          — id, name, access_token, image_url, post_hours, is_active, last_post_at
post_history   — page_id, video_id, posted_at, fb_post_id, status, error_message
post_queue     — (legacy, ไม่ใช้แล้ว)
```

---

## Flow: ส่งวีดีโอในบอท Telegram

```
User ส่ง XHS link / วีดีโอ
      │
      ▼
CF Worker (/api/telegram)
      │  ตอบ "📥 กำลังดาวน์โหลดวิดีโอ..."
      │  เซ็ต dedup key ใน R2
      │
      ▼
CapRover (/pipeline) — background thread
      │
      ├─ 1. ดาวน์โหลดวีดีโอ (XHS → resolve URL → download)
      ├─ 2. อัพโหลดไป Gemini → วิเคราะห์วีดีโอ → สร้าง script ไทย
      ├─ 3. Gemini TTS → สร้างเสียงพากย์
      ├─ 4. ffmpeg merge เสียง+วีดีโอ
      ├─ 5. อัพโหลด R2 (วีดีโอ + metadata)
      ├─ 6. ส่งวีดีโอกลับ Telegram
      ├─ 7. เซ็ต _pending_shopee/{chatId} ใน R2
      └─ 8. ถาม "🔗 ส่งลิงก์ Shopee Affiliate มาเลยครับ"
              │
              ▼
User ส่ง Shopee link
      │
      ▼
CF Worker → อัพเดท shopeeLink ใน videos/{id}.json
      │
      ▼
      ✅ บันทึกเรียบร้อย
```

## Flow: Auto-post Facebook Reels (Cron ทุก 5 นาที)

```
Cron trigger (*/5 * * * *)
      │
      ▼
CF Worker (handleScheduled)
      │
      ├─ ดึง pages ที่ is_active=1 และมี post_hours
      ├─ เช็คเวลาไทย (UTC+7) ตรงกับ post_hours ใน 5-min window หรือไม่
      │   post_hours format: "2:22,9:49,16:49,23:09" (ชม:นาที สุ่มตอนเลือก)
      ├─ เช็ค dedup: โพสต์ชั่วโมงนี้วันนี้ไปแล้วหรือยัง
      ├─ หาวีดีโอที่เพจนี้ยังไม่เคยโพสต์ (เช็คจาก post_history)
      ├─ Gemini สร้างแคปชั่นสั้นๆ จาก script
      ├─ ต่อท้าย Shopee link ถ้ามี
      ├─ โพสต์ Facebook Reels API (init → upload → finish)
      └─ บันทึก post_history + อัพเดท last_post_at
```

---

## Deploy Commands

### Worker (Cloudflare Workers)
```bash
cd worker
npx wrangler deploy
```

### Webapp (Cloudflare Pages)
**สำคัญ: ต้องใส่ `--branch main` ไม่งั้นจะเป็น Preview**
```bash
cd webapp
npm run build
npx wrangler pages deploy dist --project-name dubbing-webapp --branch main
```

### CapRover (dubbing-api)
**สำคัญ: `caprover deploy` CLI ใช้ไม่ได้กับ Node v25 — ใช้ curl API แทน**
```bash
cd api
tar -cf deploy.tar captain-definition server.py xhs_downloader.py requirements.txt cookies.txt
curl -X POST "https://captain.lslly.com/api/v2/user/apps/appData/dubbing-api" \
  -H "x-captain-auth: <TOKEN_FROM_~/.config/configstore/caprover.json>" \
  -F "sourceFile=@deploy.tar"
```

### ตั้ง Telegram Webhook
**ต้องชี้ไป CF Worker ไม่ใช่ CapRover!**
```bash
curl "https://api.telegram.org/bot${TOKEN}/setWebhook?url=https://dubbing-worker.yokthanwa1993-bc9.workers.dev/api/telegram"
```

---

## สิ่งที่ต้องจำ (Critical)

1. **Telegram webhook ต้องชี้ CF Worker** — `https://dubbing-worker.../api/telegram` ไม่ใช่ CapRover
2. **Webapp เรียก API จาก CF Worker เท่านั้น** — ไม่เรียก CapRover โดยตรง
3. **CapRover ทำแค่ pipeline** — ffmpeg merge + ประมวลผลหนัก ไม่มี API อื่น
4. **Webapp deploy ต้อง `--branch main`** — ไม่งั้นจะเป็น Preview ไม่ใช่ Production
5. **CapRover CLI broken กับ Node v25** — ใช้ curl API ตรง
6. **Dedup key ค้างได้** — ถ้าบอทไม่ตอบ ลอง `DELETE /api/dedup` ก่อน
7. **post_hours format ใหม่** — `"2:22,9:49,16:49"` (ชม:นาที) backward compat กับ `"2,9,16"` (ชม. อย่างเดียว = :00)
8. **waitUntil 30s hard limit** — pipeline ต้องรันบน CapRover ไม่ใช่ Worker
9. **R2 gallery cache** — rebuild โดย CapRover หลัง pipeline เสร็จ (function `rebuild_gallery_cache`)
10. **1 เพจ ห้ามโพสต์วีดีโอซ้ำ** — เช็คจาก post_history WHERE page_id = ? / แต่ต่างเพจโพสต์วีดีโอเดียวกันได้
