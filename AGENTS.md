# AI Dubbing Pipeline - Architecture

## สรุปแบบเข้าใจง่าย

### ⚡ Cloudflare (serverless)
| Service | Platform | หน้าที่ |
|---------|----------|---------|
| **Webapp** | Cloudflare Pages | Mini App UI (React) |
| **Worker** | Cloudflare Workers | Pages CRUD, D1 database access |
| **Database** | Cloudflare D1 | เก็บข้อมูล Facebook Pages |
| **Storage** | Cloudflare R2 | เก็บวิดีโอ + metadata |

### 🖥️ CapRover (server - ต้องใช้เพราะมี ffmpeg)
| App | หน้าที่ |
|-----|---------|
| **dubbing-api** | รับ Telegram webhook, ดาวน์โหลด XHS, เรียก Gemini, TTS, รวมเสียง+วิดีโอ (ffmpeg), อัพ R2 |
| **xhs-dl** | XHS-Downloader API |

---

## URLs

| Component | URL |
|-----------|-----|
| API (Flask) | `https://dubbing-api.lslly.com` |
| Webapp (React) | `https://dubbing-webapp.pages.dev` |
| Worker (D1/Pages) | `https://dubbing-worker.yokthanwa1993-bc9.workers.dev` |
| XHS Downloader | `https://xhs-dl.lslly.com` |
| R2 Public | `https://pub-a706e0103203445680507a4f55084d86.r2.dev` |

---

## Pipeline Flow (ปัจจุบัน - ใช้ CapRover เป็นหลัก)

```
Telegram → CapRover (dubbing-api /telegram)
              │
              ├─ 1. ดาวน์โหลดวิดีโอจาก XHS
              ├─ 2. เรียก Gemini API สร้าง script ไทย
              ├─ 3. เรียก Gemini TTS สร้างเสียง
              ├─ 4. รวมเสียง+วิดีโอด้วย ffmpeg
              ├─ 5. อัพโหลดไป R2
              └─ 6. ส่งวิดีโอกลับ Telegram + ปุ่มเปิดคลัง
```

---

## สิ่งที่ต้องจำ

1. **XHS-Downloader API ไม่ต้องใช้ cookie** - อย่าใส่ XHS_COOKIE
2. **Telegram webhook** ชี้ไปที่ `/telegram` ไม่ใช่ `/telegram-webhook`
3. **Webapp ใช้ Cloudflare Pages** deploy ด้วย wrangler
4. **ffmpeg ต้องใช้ CapRover** ไม่สามารถรันบน Cloudflare Workers ได้

---

## Environment Variables

### CapRover (dubbing-api)
```
TELEGRAM_BOT_TOKEN=xxx
gemini=xxx (Gemini API key)
model=gemini-3-flash-preview
R2_ACCOUNT_ID=bc9db0f4b48f964b6e445dccc240af87
R2_BUCKET_NAME=dubbing-videos
R2_ACCESS_KEY_ID=xxx
R2_SECRET_ACCESS_KEY=xxx
R2_PUBLIC_URL=https://pub-a706e0103203445680507a4f55084d86.r2.dev
```

### Cloudflare Worker (wrangler.toml)
```toml
CORS_ORIGIN = "*"
```

---

## Deploy Commands

### API (CapRover)
```bash
cd api
rm -f deploy.tar
tar -cf deploy.tar server.py Dockerfile requirements.txt xhs_downloader.py cookies.txt captain-definition
caprover deploy -n lslly -a dubbing-api -t ./deploy.tar
```

### Webapp (Cloudflare Pages)
```bash
cd webapp
npm run build
yes | npx wrangler pages deploy dist --project-name=dubbing-webapp
```

### Worker (Cloudflare Workers)
```bash
cd worker
npx wrangler deploy
```

### ตั้ง Telegram Webhook
```bash
curl "https://api.telegram.org/bot${TOKEN}/setWebhook?url=https://dubbing-api.lslly.com/telegram"
```
