# AI Dubbing Pipeline — CHEARB Channel (ช่องที่ 2)

## สถาปัตยกรรมปัจจุบัน

### CF Worker = API + Webhook + Cron ทั้งหมด
### CapRover = แค่รัน Pipeline หลังบ้าน (ffmpeg + ประมวลผลหนัก)
### แยกอิสระจาก dubbing เดิม — มี D1/R2/Worker/Webapp ของตัวเอง

---

## Components

### 1. CF Worker (`dubbing-chearb-worker`)
**URL**: `https://dubbing-chearb-worker.yokthanwa1993-bc9.workers.dev`
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
| `cron * * * * *` | — | **Auto-post** ตรวจสอบทุกนาที โพสต์ Facebook Reels ตามเวลาที่ตั้งไว้ |

Bindings:
- **D1** (`DB`) — database `dubbing-chearb-db` (ID: `02bf7a49-6ef2-4a53-b75e-e8a5962295ab`)
- **R2** (`BUCKET`) — bucket `dubbing-chearb-videos`
- **Secrets** — `GOOGLE_API_KEY`, `TELEGRAM_BOT_TOKEN`
- **Vars** — `CORS_ORIGIN`, `R2_PUBLIC_URL`, `GEMINI_MODEL`

### 2. CapRover (`dubbing-api`) — ใช้ร่วมกับ dubbing เดิม
**URL**: `https://dubbing-api.lslly.com`
**Source**: `api/server.py` (Flask)

CapRover ทำแค่งานหนักที่ต้องใช้ ffmpeg:
| Endpoint | Method | หน้าที่ |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/pipeline` | POST | **รัน pipeline ทั้งหมด** (background thread) |
| `/merge` | POST | Legacy: merge video+audio อย่างเดียว |

### 3. Webapp (`dubbing-chearb-webapp`)
**URL**: `https://dubbing-chearb-webapp.pages.dev`
**Source**: `webapp/src/App.tsx` (React + Vite)

Telegram Mini App — ใช้ `WORKER_URL` = `dubbing-chearb-worker` เรียก API ทั้งหมด:
- **Home** — Dashboard + Stats
- **Gallery** — แสดงวีดีโอทั้งหมดจาก R2
- **Logs** — Activity logs
- **Pages** — จัดการ Facebook Pages (เปิด/ปิด auto-post, ตั้งเวลาโพสต์)
- **Settings** — ตั้งค่า

### 4. R2 Storage (`dubbing-chearb-videos`)
**Public URL**: `https://pub-1b94ef9da5c447c3b4c080893c2f6613.r2.dev`
```
videos/{id}.json          — metadata (script, publicUrl, shopeeLink, duration, ...)
videos/{id}.mp4           — วีดีโอ merged (พากย์เสียงแล้ว)
videos/{id}_original.mp4  — วีดีโอต้นฉบับ
_cache/gallery.json       — gallery cache (rebuild โดย CapRover หลัง pipeline เสร็จ)
_dedup/{update_id}        — กัน Telegram retry (ห้ามลบมัน ยกเว้นค้าง → DELETE /api/dedup)
_pending_shopee/{chatId}.json — รอ Shopee link หลัง pipeline เสร็จ
```

### 5. D1 Database (`dubbing-chearb-db`)
**ID**: `02bf7a49-6ef2-4a53-b75e-e8a5962295ab`
```sql
pages          — id, name, access_token, image_url, post_hours, is_active, last_post_at
post_history   — page_id, video_id, posted_at, fb_post_id, status, error_message
post_queue     — (legacy, ไม่ใช้แล้ว)
```

---

## ความแตกต่างจาก dubbing เดิม

| รายการ | dubbing (ช่องเดิม) | dubbing-chearb (ช่องที่ 2) |
|--------|------|------|
| Worker | `dubbing-worker` | `dubbing-chearb-worker` |
| Webapp | `dubbing-webapp.pages.dev` | `dubbing-chearb-webapp.pages.dev` |
| D1 DB | `dubbing-db` (`af814a17-...`) | `dubbing-chearb-db` (`02bf7a49-...`) |
| R2 Bucket | `dubbing-videos` | `dubbing-chearb-videos` |
| R2 Public URL | `pub-a706e01...r2.dev` | `pub-1b94ef9...r2.dev` |
| CapRover API | **ใช้ร่วมกัน** | **ใช้ร่วมกัน** |

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
npx wrangler pages deploy dist --project-name dubbing-chearb-webapp --branch main --commit-dirty=true
```

### ตั้ง Telegram Webhook
**ต้องชี้ไป CF Worker ไม่ใช่ CapRover!**
```bash
curl "https://api.telegram.org/bot${TOKEN}/setWebhook?url=https://dubbing-chearb-worker.yokthanwa1993-bc9.workers.dev/api/telegram"
```

---

## สิ่งที่ต้องจำ (Critical)

1. **Telegram webhook ต้องชี้ CF Worker** — `https://dubbing-chearb-worker.../api/telegram` ไม่ใช่ CapRover
2. **Webapp เรียก API จาก CF Worker เท่านั้น** — ไม่เรียก CapRover โดยตรง
3. **CapRover ทำแค่ pipeline** — ffmpeg merge + ประมวลผลหนัก ไม่มี API อื่น
4. **Webapp deploy ต้อง `--branch main`** — ไม่งั้นจะเป็น Preview ไม่ใช่ Production
5. **Dedup key ค้างได้** — ถ้าบอทไม่ตอบ ลอง `DELETE /api/dedup` ก่อน
6. **post_hours format** — `"2:22,9:49,16:49"` (ชม:นาที) backward compat กับ `"2,9,16"` (ชม. อย่างเดียว = :00)
7. **waitUntil 30s hard limit** — pipeline ต้องรันบน CapRover ไม่ใช่ Worker
8. **R2 gallery cache** — rebuild โดย CapRover หลัง pipeline เสร็จ
9. **1 เพจ ห้ามโพสต์วีดีโอซ้ำ** — เช็คจาก post_history WHERE page_id = ?
10. **ใช้ CapRover ร่วมกับ dubbing เดิม** — ระวังอย่าสร้าง bot token ชนกัน!
