# AI Dubbing Pipeline - Architecture

## Infrastructure

| Component | Platform | หน้าที่ | URL |
|-----------|----------|---------|-----|
| **Worker (Hono)** | Cloudflare Workers | ตัวสั่งงานหลัก: Telegram webhook, Gemini API, TTS, Gallery API, Pages CRUD | `https://dubbing-worker.yokthanwa1993-bc9.workers.dev` |
| **Merge API (Flask)** | CapRover | รวมเสียง+วิดีโอด้วย ffmpeg เท่านั้น | `https://dubbing-api.lslly.com` |
| **XHS Downloader** | CapRover | ดาวน์โหลดวิดีโอจาก Xiaohongshu | `https://xhs-dl.lslly.com` |
| **Webapp (React)** | Cloudflare Pages | UI สำหรับ Telegram Mini App | `https://dubbing-webapp.pages.dev` |
| **Database** | Cloudflare D1 | เก็บข้อมูล Pages, Queue, History | via Worker binding |
| **Storage** | Cloudflare R2 | เก็บวิดีโอ + metadata JSON | bucket: `dubbing-videos` |

## Pipeline Flow

```
Telegram → CF Worker (request handler — ไม่ใช้ waitUntil!)
              │
              ├─ 1. รับ webhook + dedup ด้วย R2
              ├─ 2. เรียก xhs-dl (CapRover) ดึง video URL
              ├─ 3. ดาวน์โหลดวิดีโอ → เก็บต้นฉบับใน R2
              ├─ 4. อัพโหลดไป Gemini → วิเคราะห์วิดีโอ → สร้าง script ไทย
              ├─ 5. Gemini TTS → ได้เสียง base64
              ├─ 6. ส่งไป CapRover POST /merge
              │        └─ ffmpeg merge → อัพกลับ R2
              ├─ 7. บันทึก metadata JSON ไป R2
              └─ 8. แจ้ง Telegram (ส่งวิดีโอ + ปุ่มเปิดคลัง)
```

## สิ่งที่ต้องจำ (สำคัญมาก!)

### 1. ห้ามใช้ `waitUntil` สำหรับ pipeline!
- `waitUntil` จำกัด 30 วินาที (แม้ paid plan ก็อาจยังไม่ propagate)
- Pipeline ใช้เวลา 60-90 วินาที → ถูก kill ทุกครั้ง
- **แก้: รัน `await runPipeline()` ตรงใน request handler** (ได้ CPU 15 นาที)
- ใช้ dedup key ใน R2 (`_dedup/{update_id}`) กัน Telegram retry ซ้ำ

### 2. Animated dots (จุดวิ่ง)
- อัพเดทข้อความ Telegram ทุก 600ms: กำลังดาวน์โหลดวิดีโอ. → .. → ... → (วนซ้ำ)
- ใช้ `startDotAnimation()` ที่ return `stopAnim()` function
- **ต้อง call `stopAnim()` ใน catch block ด้วย** ไม่งั้น animation ค้าง

### 3. XHS-Downloader API ไม่ต้องใช้ cookie
- อย่าใส่ XHS_COOKIE ใน env vars

### 4. CapRover เหลือแค่ 2 app
- `dubbing-api` — merge เสียง+วิดีโอ (ffmpeg) เท่านั้น
- `xhs-dl` — ดาวน์โหลดวิดีโอ XHS

### 5. Webapp deploy ต้องใส่ `--branch main`
- ไม่งั้นจะไปเป็น Preview deployment ไม่ใช่ Production
- Production = `dubbing-webapp.pages.dev`

## Environment Variables

### Worker (Cloudflare) — secrets ตั้งผ่าน `wrangler secret put`
```
GOOGLE_API_KEY=xxx (Gemini API key)
TELEGRAM_BOT_TOKEN=xxx
```

### Worker (Cloudflare) — vars ใน wrangler.toml
```toml
CORS_ORIGIN = "*"
R2_PUBLIC_URL = "https://pub-a706e0103203445680507a4f55084d86.r2.dev"
XHS_DL_URL = "https://xhs-dl.lslly.com"
CAPROVER_MERGE_URL = "https://dubbing-api.lslly.com"
GEMINI_MODEL = "gemini-3-flash-preview"
```

### CapRover (dubbing-api) — env vars
```
R2_ACCOUNT_ID=bc9db0f4b48f964b6e445dccc240af87
R2_BUCKET_NAME=dubbing-videos
R2_ACCESS_KEY_ID=xxx
R2_SECRET_ACCESS_KEY=xxx
R2_PUBLIC_URL=https://pub-a706e0103203445680507a4f55084d86.r2.dev
```

## Deploy Commands

### Worker (Cloudflare)
```bash
cd worker
npx tsc --noEmit    # type check
npx wrangler deploy
```

### Merge API (CapRover)
```bash
cd api
rm -f deploy.tar
tar -cf deploy.tar server.py Dockerfile requirements.txt captain-definition
# CapRover CLI มีปัญหา readline กับ Node v25 — ใช้ API ตรง:
AUTH="$(python3 -c "import json; print(json.load(open('$HOME/.config/configstore/caprover.json'))['CapMachines'][0]['authToken'])")"
curl -s --max-time 300 -X POST "https://captain.lslly.com/api/v2/user/apps/appData/dubbing-api" \
  -H "x-captain-auth: $AUTH" -F "sourceFile=@deploy.tar"
```

### Webapp (Cloudflare Pages)
```bash
cd webapp
npm run build
npx wrangler pages deploy dist --project-name dubbing-webapp --branch main
```

### ตั้ง Telegram Webhook
```bash
curl "https://api.telegram.org/bot${TOKEN}/setWebhook?url=https://dubbing-worker.yokthanwa1993-bc9.workers.dev/api/telegram"
```

## File Structure

```
worker/
  src/index.ts      — Hono routes: telegram webhook, gallery, pages CRUD, scheduler
  src/pipeline.ts   — Pipeline logic: download, gemini, TTS, merge, telegram helpers
  wrangler.toml     — Bindings: D1, R2, vars, limits

api/
  server.py         — Flask merge-only API (/health, /merge)
  Dockerfile        — python:3.11-slim + ffmpeg
  captain-definition

webapp/
  src/App.tsx        — React SPA (Telegram Mini App)
```
