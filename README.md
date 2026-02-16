# AI Dubbing Pipeline

100% Cloudflare-native video dubbing system.

## Architecture

```
dubbing/
├── merge/    → FFmpeg Container (Docker, runs on Cloudflare Containers)
├── worker/   → Cloudflare Worker (pipeline orchestration, API, cron)
└── webapp/   → Frontend (Cloudflare Pages, Telegram Mini App)
```

## Stack

- **Worker**: Hono + TypeScript on Cloudflare Workers
- **Container**: Python Flask + FFmpeg on Cloudflare Containers
- **Storage**: Cloudflare R2 (videos) + D1 (metadata)
- **AI**: Gemini API (video analysis, TTS)
- **Bot**: Telegram Bot (input/output)

## Deploy

```bash
# Worker + Container
cd worker && npx wrangler deploy

# Webapp (auto-deploy via Cloudflare Pages)
```
