# AI Dubbing Pipeline - Architecture

## Infrastructure

| Component | Platform | URL |
|-----------|----------|-----|
| **API (Flask)** | CapRover | `https://dubbing-api.lslly.com` |
| **Webapp (React)** | Cloudflare Pages | `https://dubbing-webapp.pages.dev` |
| **Database** | Cloudflare D1 | via Worker |
| **XHS Downloader** | CapRover | `https://xhs-dl.lslly.com` |
| **Storage** | Cloudflare R2 | `dubbing-videos` bucket |

## Environment Variables (CapRover - dubbing-api)

```
TELEGRAM_BOT_TOKEN=xxx
GOOGLE_API_KEY=xxx (gemini key)
model=gemini-3-flash-preview
R2_ACCOUNT_ID=xxx
R2_BUCKET_NAME=dubbing-videos
R2_ACCESS_KEY_ID=xxx
R2_SECRET_ACCESS_KEY=xxx
R2_PUBLIC_URL=https://pub-xxx.r2.dev

# ไม่ต้องใช้ XHS_COOKIE - XHS-Downloader API ใหม่ไม่ต้องใช้ cookie
```

## สิ่งที่ต้องจำ

1. **XHS-Downloader API ไม่ต้องใช้ cookie** - อย่าใส่ XHS_COOKIE ใน env vars
2. **Webapp deploy ไป Cloudflare Pages** ไม่ใช่ CapRover
3. **API deploy ไป CapRover**
4. **ปุ่ม "เปิดคลัง"** ใช้ URL: `https://dubbing-webapp.pages.dev?tab=gallery`

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
