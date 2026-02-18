import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { Container } from '@cloudflare/containers'
import { type Env, rebuildGalleryCache, updateGalleryCache, sendTelegram, runPipeline } from './pipeline'

const app = new Hono<{ Bindings: Env }>()

// CORS
app.use('*', async (c, next) => {
    const corsMiddleware = cors({
        origin: c.env.CORS_ORIGIN || '*',
        allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    })
    return corsMiddleware(c, next)
})

// Health check
app.get('/', (c) => c.json({ status: 'ok', service: 'dubbing-worker' }))

// ==================== CATEGORIES HELPER ====================

const DEFAULT_CATEGORIES = ['เครื่องมือช่าง', 'อาหาร', 'เครื่องครัว', 'ของใช้ในบ้าน', 'เฟอร์นิเจอร์', 'บิวตี้', 'แฟชั่น', 'อิเล็กทรอนิกส์', 'สุขภาพ', 'กีฬา', 'สัตว์เลี้ยง', 'ยานยนต์', 'อื่นๆ']

async function getCategories(bucket: R2Bucket): Promise<string[]> {
    const obj = await bucket.get('_config/categories.json')
    if (obj) return await obj.json() as string[]
    return DEFAULT_CATEGORIES
}

// ==================== TELEGRAM WEBHOOK ====================

app.post('/api/telegram', async (c) => {
    try {
        const data = await c.req.json() as {
            update_id?: number
            message?: {
                message_id: number
                chat: { id: number }
                text?: string
                video?: { file_id: string }
            }
        }

        if (!data?.message) return c.text('ok')

        const msg = data.message
        const chatId = msg.chat.id
        const text = msg.text || ''
        const token = c.env.TELEGRAM_BOT_TOKEN

        // Dedup: ป้องกัน Telegram retry ขณะ pipeline ยังรันอยู่
        const dedupKey = `_dedup/${data.update_id || msg.message_id}`
        const existing = await c.env.BUCKET.head(dedupKey)
        if (existing) return c.text('ok')

        const pendingShopeeKey = `_pending_shopee/${chatId}.json`
        const pendingCategoryKey = `_pending_category/${chatId}.json`

        const CATEGORIES = await getCategories(c.env.BUCKET)

        // กรณีเลือกหมวดหมู่ → บันทึก category
        const pendingCatObj = await c.env.BUCKET.get(pendingCategoryKey)
        if (pendingCatObj && text.trim() && CATEGORIES.includes(text.trim())) {
            const pending = await pendingCatObj.json() as { videoId: string }

            // ตอบ user ก่อนเลย (ไว)
            const [, metaObj] = await Promise.all([
                c.env.BUCKET.delete(pendingCategoryKey),
                c.env.BUCKET.get(`videos/${pending.videoId}.json`),
                sendTelegram(token, 'sendMessage', {
                    chat_id: chatId,
                    text: '📝 บันทึกหมวดหมู่แล้ว',
                    reply_markup: { remove_keyboard: true },
                }),
            ])

            // บันทึก metadata + cache ทีหลัง
            if (metaObj) {
                const meta = await metaObj.json() as Record<string, unknown>
                meta.category = text.trim()
                await c.env.BUCKET.put(`videos/${pending.videoId}.json`, JSON.stringify(meta, null, 2), {
                    httpMetadata: { contentType: 'application/json' },
                })
                await updateGalleryCache(c.env.BUCKET, pending.videoId)
            }

            return c.text('ok')
        }

        // กรณีส่งวิดีโอมา → เริ่ม pipeline ทันที
        if (msg.video) {
            const fileInfo = await fetch(
                `https://api.telegram.org/bot${token}/getFile?file_id=${msg.video.file_id}`
            ).then(r => r.json()) as { ok: boolean; result?: { file_path: string } }

            if (fileInfo.ok && fileInfo.result) {
                const videoUrl = `https://api.telegram.org/file/bot${token}/${fileInfo.result.file_path}`
                const statusMsg = await sendTelegram(token, 'sendMessage', {
                    chat_id: chatId,
                    text: '📥 กำลังดาวน์โหลดวิดีโอ.',
                    parse_mode: 'HTML',
                })
                const msgId = (statusMsg.result as { message_id: number })?.message_id
                await c.env.BUCKET.put(dedupKey, 'processing')

                if (msgId) {
                    c.executionCtx.waitUntil(runPipeline(c.env, videoUrl, chatId, msgId))
                }
            }
            return c.text('ok')
        }

        // กรณีส่ง XHS link → เริ่ม pipeline ทันที
        const xhsMatch = text.match(/https?:\/\/(xhslink\.com|www\.xiaohongshu\.com)\S+/)
        if (xhsMatch) {
            const videoUrl = xhsMatch[0]
            const statusMsg = await sendTelegram(token, 'sendMessage', {
                chat_id: chatId,
                text: '📥 กำลังดาวน์โหลดวิดีโอ.',
                parse_mode: 'HTML',
            })
            const msgId = (statusMsg.result as { message_id: number })?.message_id
            await c.env.BUCKET.put(dedupKey, 'processing')

            if (msgId) {
                c.executionCtx.waitUntil(runPipeline(c.env, videoUrl, chatId, msgId))
            }
            return c.text('ok')
        }

        // กรณีส่ง Shopee link → บันทึก + ส่งวีดีโอพร้อมปุ่ม
        const shopeeMatch = text.match(/https?:\/\/\S*shopee\S+/) || text.match(/https?:\/\/shope\.ee\S+/)
        if (shopeeMatch) {
            const shopeeLink = shopeeMatch[0]
            let videoId = ''
            let publicUrl = ''

            // เช็ค pending จาก pipeline ก่อน
            const pendingObj = await c.env.BUCKET.get(pendingShopeeKey)
            if (pendingObj) {
                const pending = await pendingObj.json() as { videoId: string; publicUrl: string; msgId?: number }
                videoId = pending.videoId
                publicUrl = pending.publicUrl
                await c.env.BUCKET.delete(pendingShopeeKey)
            } else {
                // fallback: ใช้ cache หาวีดีโอล่าสุดที่ยังไม่มี shopeeLink
                const cacheObj = await c.env.BUCKET.get('_cache/gallery.json')
                if (cacheObj) {
                    const cache = await cacheObj.json() as { videos: Record<string, unknown>[] }
                    const found = (cache.videos || []).find(v => !v.shopeeLink)
                    if (found) {
                        videoId = found.id as string
                        publicUrl = found.publicUrl as string
                    }
                }
            }

            if (!videoId) {
                await sendTelegram(token, 'sendMessage', {
                    chat_id: chatId,
                    text: '❌ ไม่มีวีดีโอรอใส่ลิงก์\n\nส่งวีดีโอหรือลิงก์ XHS มาก่อนนะครับ',
                })
                return c.text('ok')
            }

            // อัพเดท metadata + ตอบ user พร้อมกัน
            const metaObj2 = await c.env.BUCKET.get(`videos/${videoId}.json`)
            if (metaObj2) {
                const meta = await metaObj2.json() as Record<string, unknown>
                meta.shopeeLink = shopeeLink
                await Promise.all([
                    c.env.BUCKET.put(`videos/${videoId}.json`, JSON.stringify(meta, null, 2), {
                        httpMetadata: { contentType: 'application/json' },
                    }),
                    sendTelegram(token, 'sendMessage', {
                        chat_id: chatId,
                        text: '✅ บันทึกลิงก์ Shopee แล้ว',
                    }),
                ])
                await updateGalleryCache(c.env.BUCKET, videoId)
            }

            return c.text('ok')
        }

        // /start
        if (text === '/start') {
            await sendTelegram(token, 'sendMessage', {
                chat_id: chatId,
                text: '👋 สวัสดี! ส่งลิงก์วิดีโอจาก Xiaohongshu หรืออัพโหลดวิดีโอมาเลย',
            })
            return c.text('ok')
        }

        // ข้อความอื่น
        if (text.trim()) {
            const hasPending = await c.env.BUCKET.head(pendingShopeeKey)
            if (hasPending) {
                await sendTelegram(token, 'sendMessage', {
                    chat_id: chatId,
                    text: '❌ ลิงก์ Shopee ไม่ถูกต้อง\n\nส่งลิงก์ที่ขึ้นต้นด้วย https://s.shopee.co.th/... หรือ https://shopee.co.th/...',
                })
            } else {
                await sendTelegram(token, 'sendMessage', {
                    chat_id: chatId,
                    text: '❌ รองรับเฉพาะลิงก์ Xiaohongshu หรืออัพโหลดวิดีโอเท่านั้น\n\nตัวอย่าง: http://xhslink.com/...',
                })
            }
        }

        return c.text('ok')
    } catch (e) {
        console.error('[TELEGRAM] Handler error:', e instanceof Error ? e.message : String(e))
        return c.text('ok')
    }
})

// ล้าง dedup keys (กรณีค้าง)
app.delete('/api/dedup', async (c) => {
    const list = await c.env.BUCKET.list({ prefix: '_dedup/' })
    for (const obj of list.objects) {
        await c.env.BUCKET.delete(obj.key)
    }
    return c.json({ deleted: list.objects.length })
})

// ==================== CATEGORIES API ====================

app.get('/api/categories', async (c) => {
    const cats = await getCategories(c.env.BUCKET)
    return c.json({ categories: cats })
})

app.put('/api/categories', async (c) => {
    const body = await c.req.json() as { categories: string[] }
    await c.env.BUCKET.put('_config/categories.json', JSON.stringify(body.categories), {
        httpMetadata: { contentType: 'application/json' },
    })
    return c.json({ success: true })
})

// ==================== GALLERY API (R2) ====================

app.get('/api/gallery', async (c) => {
    try {
        // อ่านจาก cache file เดียว (เร็วกว่าอ่านทีละไฟล์มาก)
        const cached = await c.env.BUCKET.get('_cache/gallery.json')
        if (cached) {
            const data = await cached.json()
            return c.json(data, 200, { 'Cache-Control': 'public, max-age=30, stale-while-revalidate=60' })
        }

        // ถ้ายังไม่มี cache → สร้างใหม่
        const videos = await rebuildGalleryCache(c.env.BUCKET)
        return c.json({ videos })
    } catch (e) {
        return c.json({ videos: [], error: String(e) })
    }
})

// Get videos that have been posted (used videos)
app.get('/api/gallery/used', async (c) => {
    try {
        // Get all posted video IDs from post_history
        const { results: posted } = await c.env.DB.prepare(
            "SELECT DISTINCT video_id FROM post_history WHERE status IN ('success', 'posting')"
        ).all() as { results: Array<{ video_id: string }> }

        const postedIds = new Set(posted.map(p => p.video_id))

        if (postedIds.size === 0) {
            return c.json({ videos: [] })
        }

        // Get video metadata for each posted video
        const videos: unknown[] = []
        for (const videoId of postedIds) {
            const metaObj = await c.env.BUCKET.get(`videos/${videoId}.json`)
            if (metaObj) {
                const meta = await metaObj.json()
                videos.push(meta)
            }
        }

        // Sort by createdAt desc
        videos.sort((a: any, b: any) => {
            return new Date(b.createdAt || 0).getTime() - new Date(a.createdAt || 0).getTime()
        })

        return c.json({ videos })
    } catch (e) {
        return c.json({ videos: [], error: String(e) })
    }
})

app.put('/api/gallery/:id', async (c) => {
    const id = c.req.param('id')
    try {
        const body = await c.req.json() as { shopeeLink?: string; category?: string; title?: string }
        const metaObj = await c.env.BUCKET.get(`videos/${id}.json`)
        if (!metaObj) return c.json({ error: 'Video not found' }, 404)
        const meta = await metaObj.json() as Record<string, unknown>
        if (body.shopeeLink !== undefined) meta.shopeeLink = body.shopeeLink
        if (body.category !== undefined) meta.category = body.category
        if (body.title !== undefined) meta.title = body.title
        await c.env.BUCKET.put(`videos/${id}.json`, JSON.stringify(meta, null, 2), {
            httpMetadata: { contentType: 'application/json' },
        })
        await updateGalleryCache(c.env.BUCKET, id)
        return c.json({ success: true })
    } catch {
        return c.json({ error: 'Failed to update video' }, 500)
    }
})

app.delete('/api/gallery/:id', async (c) => {
    const id = c.req.param('id')
    try {
        // Delete video files + metadata from R2
        await c.env.BUCKET.delete(`videos/${id}.json`)
        await c.env.BUCKET.delete(`videos/${id}.mp4`)
        await c.env.BUCKET.delete(`videos/${id}_original.mp4`)
        await c.env.BUCKET.delete(`videos/${id}_thumb.webp`)
        // Rebuild gallery cache
        await rebuildGalleryCache(c.env.BUCKET)
        return c.json({ success: true })
    } catch {
        return c.json({ error: 'Failed to delete video' }, 500)
    }
})

app.get('/api/gallery/:id', async (c) => {
    const id = c.req.param('id')
    try {
        const metaObj = await c.env.BUCKET.get(`videos/${id}.json`)
        if (!metaObj) return c.json({ error: 'ไม่พบวิดีโอ' }, 404)
        const metadata = await metaObj.json()
        return c.json(metadata)
    } catch {
        return c.json({ error: 'ไม่พบวิดีโอ' }, 404)
    }
})

// ==================== PAGES API ====================

// Get all pages
app.get('/api/pages', async (c) => {
    try {
        const { results } = await c.env.DB.prepare(
            'SELECT id, name, image_url, post_interval_minutes, post_hours, is_active, last_post_at, created_at FROM pages ORDER BY created_at DESC'
        ).all()
        return c.json({ pages: results })
    } catch (e) {
        return c.json({ error: 'Failed to fetch pages' }, 500)
    }
})

// Get single page
app.get('/api/pages/:id', async (c) => {
    const id = c.req.param('id')
    try {
        const page = await c.env.DB.prepare(
            'SELECT id, name, image_url, post_interval_minutes, post_hours, is_active, last_post_at, created_at FROM pages WHERE id = ?'
        ).bind(id).first()
        if (!page) return c.json({ error: 'Page not found' }, 404)
        return c.json({ page })
    } catch (e) {
        return c.json({ error: 'Failed to fetch page' }, 500)
    }
})

// Create page
app.post('/api/pages', async (c) => {
    try {
        const body = await c.req.json()
        const { id, name, image_url, access_token, post_interval_minutes = 60 } = body

        await c.env.DB.prepare(
            'INSERT INTO pages (id, name, image_url, access_token, post_interval_minutes) VALUES (?, ?, ?, ?, ?)'
        ).bind(id, name, image_url, access_token, post_interval_minutes).run()

        return c.json({ success: true, id })
    } catch (e) {
        return c.json({ error: 'Failed to create page' }, 500)
    }
})

// Update page settings
app.put('/api/pages/:id', async (c) => {
    const id = c.req.param('id')
    try {
        const body = await c.req.json()
        const { post_interval_minutes, post_hours, is_active } = body

        // Support both old interval and new hours-based scheduling
        if (post_hours !== undefined) {
            await c.env.DB.prepare(
                'UPDATE pages SET post_hours = ?, is_active = ?, updated_at = datetime("now") WHERE id = ?'
            ).bind(post_hours, is_active ? 1 : 0, id).run()
        } else {
            await c.env.DB.prepare(
                'UPDATE pages SET post_interval_minutes = ?, is_active = ?, updated_at = datetime("now") WHERE id = ?'
            ).bind(post_interval_minutes, is_active ? 1 : 0, id).run()
        }

        return c.json({ success: true })
    } catch (e) {
        return c.json({ error: 'Failed to update page' }, 500)
    }
})

// Delete page
app.delete('/api/pages/:id', async (c) => {
    const id = c.req.param('id')
    try {
        await c.env.DB.prepare('DELETE FROM pages WHERE id = ?').bind(id).run()
        return c.json({ success: true })
    } catch (e) {
        return c.json({ error: 'Failed to delete page' }, 500)
    }
})

// ==================== FACEBOOK IMPORT ====================

app.post('/api/pages/import', async (c) => {
    try {
        const body = await c.req.json()
        const { user_token } = body

        if (!user_token) {
            return c.json({ error: 'User token is required' }, 400)
        }

        const fbResponse = await fetch(
            `https://graph.facebook.com/v21.0/me/accounts?fields=id,name,picture.type(large),access_token&access_token=${user_token}`
        )

        if (!fbResponse.ok) {
            const errorData = await fbResponse.json() as any
            return c.json({
                error: 'Facebook API error',
                details: errorData.error?.message || 'Unknown error'
            }, 400)
        }

        const fbData = await fbResponse.json() as any
        const fbPages = fbData.data || []

        if (fbPages.length === 0) {
            return c.json({ error: 'No pages found for this account' }, 404)
        }

        const imported: { id: string; name: string }[] = []
        const skipped: { id: string; name: string; reason: string }[] = []

        for (const fbPage of fbPages) {
            const pageId = fbPage.id
            const pageName = fbPage.name
            const pageImageUrl = fbPage.picture?.data?.url || ''
            const pageAccessToken = fbPage.access_token

            const existing = await c.env.DB.prepare(
                'SELECT id FROM pages WHERE id = ?'
            ).bind(pageId).first()

            if (existing) {
                await c.env.DB.prepare(
                    'UPDATE pages SET access_token = ?, image_url = ?, name = ?, updated_at = datetime("now") WHERE id = ?'
                ).bind(pageAccessToken, pageImageUrl, pageName, pageId).run()
                skipped.push({ id: pageId, name: pageName, reason: 'updated' })
            } else {
                await c.env.DB.prepare(
                    'INSERT INTO pages (id, name, image_url, access_token, post_interval_minutes, is_active) VALUES (?, ?, ?, ?, 60, 1)'
                ).bind(pageId, pageName, pageImageUrl, pageAccessToken).run()
                imported.push({ id: pageId, name: pageName })
            }
        }

        return c.json({
            success: true,
            imported: imported.length,
            updated: skipped.length,
            pages: [...imported, ...skipped]
        })
    } catch (e) {
        return c.json({ error: 'Failed to import pages', details: String(e) }, 500)
    }
})

// ==================== POST QUEUE API ====================

app.get('/api/pages/:id/queue', async (c) => {
    const pageId = c.req.param('id')
    try {
        const { results } = await c.env.DB.prepare(
            'SELECT * FROM post_queue WHERE page_id = ? ORDER BY scheduled_at ASC'
        ).bind(pageId).all()
        return c.json({ queue: results })
    } catch (e) {
        return c.json({ error: 'Failed to fetch queue' }, 500)
    }
})

app.post('/api/pages/:id/queue', async (c) => {
    const pageId = c.req.param('id')
    try {
        const body = await c.req.json()
        const { video_id, scheduled_at } = body

        await c.env.DB.prepare(
            'INSERT INTO post_queue (video_id, page_id, scheduled_at) VALUES (?, ?, ?)'
        ).bind(video_id, pageId, scheduled_at).run()

        return c.json({ success: true })
    } catch (e) {
        return c.json({ error: 'Failed to add to queue' }, 500)
    }
})

// ==================== POST HISTORY API ====================

app.get('/api/post-history', async (c) => {
    try {
        const { results } = await c.env.DB.prepare(
            `SELECT ph.*, p.name as page_name, p.image_url as page_image
             FROM post_history ph
             JOIN pages p ON ph.page_id = p.id
             WHERE ph.status != 'deleted'
             ORDER BY ph.posted_at DESC LIMIT 100`
        ).all()
        return c.json({ history: results })
    } catch (e) {
        return c.json({ error: 'Failed to fetch history' }, 500)
    }
})

app.delete('/api/post-history/:id', async (c) => {
    try {
        const id = c.req.param('id')
        const row = await c.env.DB.prepare(
            'SELECT ph.fb_post_id, p.access_token FROM post_history ph JOIN pages p ON ph.page_id = p.id WHERE ph.id = ?'
        ).bind(id).first() as { fb_post_id?: string; access_token: string } | null

        if (row?.fb_post_id && row.access_token) {
            await fetch(`https://graph.facebook.com/v19.0/${row.fb_post_id}`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ access_token: row.access_token }),
            }).catch(() => { })
        }

        // Mark as hidden instead of deleting (keep record to prevent re-posting same video)
        await c.env.DB.prepare("UPDATE post_history SET status = 'deleted' WHERE id = ?").bind(id).run()
        return c.json({ success: true })
    } catch {
        return c.json({ error: 'Failed to delete' }, 500)
    }
})

app.get('/api/pages/:id/history', async (c) => {
    const pageId = c.req.param('id')
    try {
        const { results } = await c.env.DB.prepare(
            'SELECT * FROM post_history WHERE page_id = ? ORDER BY posted_at DESC LIMIT 50'
        ).bind(pageId).all()
        return c.json({ history: results })
    } catch (e) {
        return c.json({ error: 'Failed to fetch history' }, 500)
    }
})

app.get('/api/pages/:id/stats', async (c) => {
    const pageId = c.req.param('id')
    try {
        const today = await c.env.DB.prepare(
            "SELECT COUNT(*) as count FROM post_history WHERE page_id = ? AND date(posted_at) = date('now')"
        ).bind(pageId).first()

        const week = await c.env.DB.prepare(
            "SELECT COUNT(*) as count FROM post_history WHERE page_id = ? AND posted_at >= datetime('now', '-7 days')"
        ).bind(pageId).first()

        const total = await c.env.DB.prepare(
            'SELECT COUNT(*) as count FROM post_history WHERE page_id = ?'
        ).bind(pageId).first()

        return c.json({
            today: today?.count || 0,
            week: week?.count || 0,
            total: total?.count || 0
        })
    } catch (e) {
        return c.json({ error: 'Failed to fetch stats' }, 500)
    }
})

// ==================== SCHEDULER ====================

app.get('/api/scheduler/process', async (c) => {
    try {
        const { results: pendingPosts } = await c.env.DB.prepare(
            "SELECT pq.*, p.access_token, p.name as page_name FROM post_queue pq JOIN pages p ON pq.page_id = p.id WHERE pq.status = 'pending' AND pq.scheduled_at <= datetime('now') AND p.is_active = 1 LIMIT 10"
        ).all()

        const processed: number[] = []

        for (const post of pendingPosts || []) {
            await c.env.DB.prepare(
                "UPDATE post_queue SET status = 'processing' WHERE id = ?"
            ).bind(post.id).run()

            // TODO: Implement actual Facebook Reels posting
            await c.env.DB.prepare(
                'INSERT INTO post_history (video_id, page_id, fb_post_id, status) VALUES (?, ?, ?, ?)'
            ).bind(post.video_id, post.page_id, 'simulated_' + Date.now(), 'success').run()

            await c.env.DB.prepare(
                'DELETE FROM post_queue WHERE id = ?'
            ).bind(post.id).run()

            await c.env.DB.prepare(
                "UPDATE pages SET last_post_at = datetime('now') WHERE id = ?"
            ).bind(post.page_id).run()

            processed.push(post.id as number)
        }

        return c.json({ processed: processed.length, ids: processed })
    } catch (e) {
        return c.json({ error: 'Scheduler failed', details: String(e) }, 500)
    }
})

// Generate short caption from long script using Gemini
async function generateCaption(script: string, apiKey: string, model: string): Promise<string> {
    try {
        const resp = await fetch(
            `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    contents: [{ parts: [{ text: `สร้างแคปชั่น Facebook Reels จาก script นี้ 1 บรรทัด มี emoji ดึงดูด จบประโยคสมบูรณ์ ห้ามตัดคำกลางคัน ตอบแค่แคปชั่น:\n\n${script}` }] }],
                    generationConfig: { temperature: 0.9, maxOutputTokens: 1024 },
                }),
            }
        )
        const result = await resp.json() as { candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }> }
        const caption = result?.candidates?.[0]?.content?.parts?.[0]?.text?.trim()
        return caption || script.slice(0, 100)
    } catch {
        return script.slice(0, 100)
    }
}

// Generate title for ONE video at a time (call repeatedly to process all)
app.post('/api/generate-title/:id', async (c) => {
    const env = c.env
    const id = c.req.param('id')
    const apiKey = env.GOOGLE_API_KEY
    const model = env.GEMINI_MODEL || 'gemini-3-flash-preview'

    const obj = await env.BUCKET.get(`videos/${id}.json`)
    if (!obj) return c.json({ error: 'not found' }, 404)
    const meta = await obj.json() as Record<string, unknown>
    if (!meta.script) return c.json({ error: 'no script' }, 400)

    const script = (meta.script as string).slice(0, 300)
    const resp = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                contents: [{
                    parts: [{
                        text: `จาก script รีวิวสินค้านี้ ช่วยเขียนแคปชั่น Facebook Reels ให้หน่อย

ตัวอย่างแคปชั่นที่ดี:
- "🔧 ประแจ 8 in 1 ตัวเดียวครบ ไม่ต้องหาหลายอัน!"
- "⚡ เลื่อยไร้สายจิ๋วแต่แจ๋ว ตัดกิ่งไม้ได้ลื่นปรื๊ด!"
- "🛠️ คีมเชื่อมรุ่นใหม่ หนีบแน่น เชื่อมนานมือไม่พอง!"

กฎสำคัญ:
- ตอบแค่ 1 บรรทัดเท่านั้น ห้ามขึ้นบรรทัดใหม่
- ใส่ emoji นำหน้า 1 ตัว
- ต้องจบประโยคสมบูรณ์ ห้ามตัดคำกลางคัน
- ตอบแค่แคปชั่น ไม่ต้องใส่เครื่องหมายคำพูด

script: ${script}`
                    }]
                }],
                generationConfig: { temperature: 0.9, maxOutputTokens: 1024 },
            }),
        }
    )
    const result = await resp.json() as { candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }> }
    let title = result?.candidates?.[0]?.content?.parts?.[0]?.text?.trim() || ''
    if (title.startsWith('"') && title.endsWith('"')) title = title.slice(1, -1)
    if (title.startsWith('\u201c') && title.endsWith('\u201d')) title = title.slice(1, -1)

    if (!title) return c.json({ error: 'no title generated' }, 500)

    meta.title = title
    await env.BUCKET.put(`videos/${id}.json`, JSON.stringify(meta, null, 2), {
        httpMetadata: { contentType: 'application/json' },
    })

    return c.json({ id, title })
})

// Rebuild gallery cache
app.post('/api/rebuild-cache', async (c) => {
    const videos = await rebuildGalleryCache(c.env.BUCKET)
    return c.json({ rebuilt: true, count: videos.length })
})

// List videos needing titles
app.get('/api/generate-titles/pending', async (c) => {
    const videoList = await c.env.BUCKET.list({ prefix: 'videos/' })
    const pending: Array<{ id: string; currentTitle: string }> = []
    for (const file of videoList.objects) {
        if (!file.key.endsWith('.json')) continue
        const obj = await c.env.BUCKET.get(file.key)
        if (!obj) continue
        const meta = await obj.json() as Record<string, unknown>
        if (!meta.script) continue
        const id = file.key.replace('videos/', '').replace('.json', '')
        pending.push({ id, currentTitle: (meta.title as string) || '' })
    }
    return c.json({ total: pending.length, videos: pending })
})

// Force post for a specific page (bypass time check)
app.post('/api/pages/:id/force-post', async (c) => {
    const pageId = c.req.param('id')
    const env = c.env

    try {
        // Get page info
        const page = await env.DB.prepare(
            'SELECT id, name, access_token, post_hours FROM pages WHERE id = ?'
        ).bind(pageId).first() as { id: string; name: string; access_token: string; post_hours: string } | null

        if (!page) return c.json({ error: 'Page not found' }, 404)

        // Get a video that hasn't been posted to this page yet
        const videoList = await env.BUCKET.list({ prefix: 'videos/' })
        const allVideoIds: string[] = []
        for (const obj of videoList.objects) {
            if (obj.key.endsWith('.json')) {
                allVideoIds.push(obj.key.replace('videos/', '').replace('.json', ''))
            }
        }

        if (allVideoIds.length === 0) return c.json({ error: 'No videos available' }, 404)

        // Get video IDs that are already posted by ANY page
        const { results: posted } = await env.DB.prepare(
            "SELECT video_id FROM post_history WHERE status IN ('success', 'posting')"
        ).all() as { results: Array<{ video_id: string }> }
        const postedIds = new Set(posted.map(p => p.video_id))

        // Find all unposted videos and pick one randomly
        const unpostedVideos = allVideoIds.filter(id => !postedIds.has(id))
        if (unpostedVideos.length === 0) return c.json({ error: 'No unposted videos left' }, 404)

        // Randomly select one video
        const unpostedId = unpostedVideos[Math.floor(Math.random() * unpostedVideos.length)]

        const metaObj = await env.BUCKET.get(`videos/${unpostedId}.json`)
        if (!metaObj) return c.json({ error: 'Video metadata not found' }, 404)
        const meta = await metaObj.json() as { publicUrl: string; script?: string; title?: string; shopeeLink?: string }

        // Use title if available, otherwise generate caption from script
        const apiKey = env.GOOGLE_API_KEY
        const model = env.GEMINI_MODEL || 'gemini-3-flash-preview'
        let caption = meta.title
            ? meta.title
            : meta.script
                ? await generateCaption(meta.script, apiKey, model)
                : 'AI Dubbed Video'
        caption += `\n#สินค้า #ของน่าใช้ #ช็อปปิ้งออนไลน์${meta.category ? ` #${meta.category}` : ''}`

        // Record attempt BEFORE posting (prevents duplicate on failure)
        const nowStr = new Date().toISOString()
        await env.DB.prepare(
            'INSERT INTO post_history (page_id, video_id, posted_at, status) VALUES (?, ?, ?, ?)'
        ).bind(page.id, unpostedId, nowStr, 'posting').run()
        await env.DB.prepare('UPDATE pages SET last_post_at = ? WHERE id = ?').bind(nowStr, page.id).run()

        // Post to Facebook Reels
        const initResp = await fetch(`https://graph.facebook.com/v19.0/${page.id}/video_reels`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ upload_phase: 'start', access_token: page.access_token }),
        })
        const initData = await initResp.json() as { video_id?: string; upload_url?: string; error?: { message: string } }
        if (initData.error) throw new Error(initData.error.message)

        const { video_id: fbVideoId, upload_url } = initData
        if (!upload_url || !fbVideoId) throw new Error('No upload URL or video ID returned')

        const videoResp = await fetch(meta.publicUrl)
        const videoBuffer = await videoResp.arrayBuffer()

        const uploadResp = await fetch(upload_url, {
            method: 'POST',
            headers: {
                'Authorization': `OAuth ${page.access_token}`,
                'offset': '0',
                'file_size': videoBuffer.byteLength.toString(),
            },
            body: videoBuffer,
        })
        const uploadData = await uploadResp.json() as { success?: boolean; error?: { message: string } }
        if (uploadData.error) throw new Error(uploadData.error.message)

        const finishResp = await fetch(`https://graph.facebook.com/v19.0/${page.id}/video_reels`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                upload_phase: 'finish',
                video_id: fbVideoId,
                video_state: 'PUBLISHED',
                description: caption,
                access_token: page.access_token,
            }),
        })
        const finishData = await finishResp.json() as { success?: boolean; error?: { message: string } }
        if (finishData.error) throw new Error(finishData.error.message)

        // Wait 10s for video to be processed before commenting
        if (meta.shopeeLink) {
            await new Promise(r => setTimeout(r, 10000))
            await fetch(`https://graph.facebook.com/v19.0/${fbVideoId}/comments`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: `📍Shopee : ${meta.shopeeLink}`,
                    access_token: page.access_token,
                }),
            }).catch(e => console.error(`[FORCE-POST] Comment failed: ${e}`))
        }

        // Update to success
        await env.DB.prepare(
            "UPDATE post_history SET fb_post_id = ?, status = 'success' WHERE page_id = ? AND video_id = ? AND status = 'posting'"
        ).bind(fbVideoId, page.id, unpostedId).run()

        return c.json({ success: true, page: page.name, video_id: unpostedId, fb_video_id: fbVideoId })
    } catch (e) {
        const errorMsg = e instanceof Error ? e.message : String(e)
        return c.json({ error: 'Post failed', details: errorMsg }, 500)
    }
})

// ==================== SCHEDULED HANDLER (CRON) ====================

async function handleScheduled(env: Env) {
    console.log('[CRON] Starting auto-post check...')

    // Get current time in Thailand timezone (UTC+7) using proper Intl
    const now = new Date()
    const nowISO = now.toISOString()

    // Use Intl.DateTimeFormat for accurate Thailand time
    const thaiTimeFormatter = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Bangkok',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    })
    const thaiDateFormatter = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Bangkok',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    })

    const thaiTimeParts = thaiTimeFormatter.formatToParts(now)
    const thaiHour = parseInt(thaiTimeParts.find(p => p.type === 'hour')?.value || '0', 10)
    const thaiMinute = parseInt(thaiTimeParts.find(p => p.type === 'minute')?.value || '0', 10)

    const thaiDateParts = thaiDateFormatter.formatToParts(now)
    const thaiYear = thaiDateParts.find(p => p.type === 'year')?.value
    const thaiMonth = thaiDateParts.find(p => p.type === 'month')?.value
    const thaiDay = thaiDateParts.find(p => p.type === 'day')?.value
    const todayStr = `${thaiYear}-${thaiMonth}-${thaiDay}`

    // 1. Get active pages with their post_hours
    const { results: pages } = await env.DB.prepare(`
        SELECT id, name, access_token, post_hours, last_post_at
        FROM pages
        WHERE is_active = 1 AND post_hours IS NOT NULL AND post_hours != ''
    `).all() as {
        results: Array<{
            id: string
            name: string
            access_token: string
            post_hours: string
            last_post_at: string | null
        }>
    }

    // Current time in minutes since midnight (Thailand)
    const nowMinutes = thaiHour * 60 + thaiMinute

    console.log(`[CRON] Found ${pages.length} active pages, Thai time: ${thaiHour}:${thaiMinute.toString().padStart(2, '0')} (${nowMinutes}m), date: ${todayStr}`)

    for (const page of pages) {
        // Parse scheduled times
        const scheduledTimes = page.post_hours.split(',').map(part => {
            const trimmed = part.trim()
            if (trimmed.includes(':')) {
                const [h, m] = trimmed.split(':').map(Number)
                return { hour: h, minute: m, totalMin: h * 60 + m }
            }
            return { hour: Number(trimmed), minute: 0, totalMin: Number(trimmed) * 60 }
        }).sort((a, b) => a.totalMin - b.totalMin)

        // Find a slot that matches NOW (within 2 min window) and hasn't been posted today
        const { results: todayPosts } = await env.DB.prepare(
            "SELECT posted_at FROM post_history WHERE page_id = ? AND status IN ('success','posting')"
        ).bind(page.id).all() as { results: Array<{ posted_at: string }> }

        // Helper to get Thai time parts from ISO date
        const getThaiTimeParts = (isoDate: string) => {
            const d = new Date(isoDate)
            const timeParts = thaiTimeFormatter.formatToParts(d)
            const dateParts = thaiDateFormatter.formatToParts(d)
            const hour = parseInt(timeParts.find(p => p.type === 'hour')?.value || '0', 10)
            const minute = parseInt(timeParts.find(p => p.type === 'minute')?.value || '0', 10)
            const year = dateParts.find(p => p.type === 'year')?.value
            const month = dateParts.find(p => p.type === 'month')?.value
            const day = dateParts.find(p => p.type === 'day')?.value
            return {
                totalMin: hour * 60 + minute,
                dateStr: `${year}-${month}-${day}`
            }
        }

        const postedSlots = new Set(todayPosts.map(p => getThaiTimeParts(p.posted_at))
            .filter(pt => pt.dateStr === todayStr)
            .map(pt => pt.totalMin))

        // Match slot within 1 minute window (to handle cron timing variance)
        const matchedSlot = scheduledTimes.find(({ totalMin }) => {
            const diff = Math.abs(nowMinutes - totalMin)
            if (diff > 1) return false  // Allow 1 minute tolerance
            return !postedSlots.has(totalMin)
        })

        if (!matchedSlot) {
            console.log(`[CRON] Page ${page.name}: skip (no matching slot, now=${nowMinutes}m, slots=${page.post_hours})`)
            continue
        }

        console.log(`[CRON] Page ${page.name}: posting for slot ${matchedSlot.hour}:${matchedSlot.minute.toString().padStart(2, '0')}`)

        // CRITICAL: Atomic dedup using R2 (prevents concurrent cron executions from double-posting)
        const dedupKey = `_cron_dedup/${page.id}/${todayStr}/${matchedSlot.hour}_${matchedSlot.minute}`
        const existingDedup = await env.BUCKET.head(dedupKey)
        if (existingDedup) {
            console.log(`[CRON] Page ${page.name}: already posted for this slot (dedup key exists)`)
            continue
        }
        // Set dedup key immediately (before any async operations) - TTL 24 hours
        await env.BUCKET.put(dedupKey, nowISO, {
            httpMetadata: { contentType: 'text/plain' },
            customMetadata: { createdAt: nowISO }
        })

        // 2. Get a video that hasn't been posted to this page yet
        // First, get all video IDs from R2
        const videoList = await env.BUCKET.list({ prefix: 'videos/' })
        const allVideoIds: string[] = []
        for (const obj of videoList.objects) {
            if (obj.key.endsWith('.json')) {
                const id = obj.key.replace('videos/', '').replace('.json', '')
                allVideoIds.push(id)
            }
        }

        if (allVideoIds.length === 0) {
            console.log(`[CRON] No videos available`)
            await env.BUCKET.delete(dedupKey).catch(() => { }) // Clean up dedup key
            continue
        }

        // Get video IDs that are already posted by ANY page (success or posting)
        // This ensures each video is only posted by one page
        const { results: posted } = await env.DB.prepare(
            "SELECT video_id FROM post_history WHERE status IN ('success', 'posting')"
        ).all() as { results: Array<{ video_id: string }> }
        const postedIds = new Set(posted.map(p => p.video_id))

        // Find all unposted videos and pick one randomly
        const unpostedVideos = allVideoIds.filter(id => !postedIds.has(id))
        if (unpostedVideos.length === 0) {
            console.log(`[CRON] Page ${page.name}: no unposted videos`)
            await env.BUCKET.delete(dedupKey).catch(() => { }) // Clean up dedup key
            continue
        }
        // Randomly select one video
        const unpostedId = unpostedVideos[Math.floor(Math.random() * unpostedVideos.length)]
        if (!unpostedId) {
            console.log(`[CRON] Page ${page.name}: no unposted videos`)
            await env.BUCKET.delete(dedupKey).catch(() => { }) // Clean up dedup key
            continue
        }

        // Get video metadata
        const metaObj = await env.BUCKET.get(`videos/${unpostedId}.json`)
        if (!metaObj) {
            await env.BUCKET.delete(dedupKey).catch(() => { }) // Clean up dedup key
            continue
        }
        const meta = await metaObj.json() as { publicUrl: string; script?: string; title?: string; shopeeLink?: string }

        // Generate short caption from script (no Shopee link)
        const apiKey = env.GOOGLE_API_KEY
        const geminiModel = env.GEMINI_MODEL || 'gemini-3-flash-preview'
        let caption = meta.title
            ? meta.title
            : meta.script
                ? await generateCaption(meta.script, apiKey, geminiModel)
                : 'AI Dubbed Video'
        caption += `\n#สินค้า #ของน่าใช้ #ช็อปปิ้งออนไลน์${meta.category ? ` #${meta.category}` : ''}`

        console.log(`[CRON] Page ${page.name}: posting video ${unpostedId} — caption: ${caption}`)

        // 3. Record attempt BEFORE posting (prevents duplicate posts if FB succeeds but D1 fails after)
        await env.DB.prepare(
            'INSERT INTO post_history (page_id, video_id, posted_at, status) VALUES (?, ?, ?, ?)'
        ).bind(page.id, unpostedId, nowISO, 'posting').run()
        await env.DB.prepare('UPDATE pages SET last_post_at = ? WHERE id = ?').bind(nowISO, page.id).run()

        try {
            // Initialize upload
            const initResp = await fetch(
                `https://graph.facebook.com/v19.0/${page.id}/video_reels`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        upload_phase: 'start',
                        access_token: page.access_token,
                    }),
                }
            )
            const initData = await initResp.json() as { video_id?: string; upload_url?: string; error?: { message: string } }

            if (initData.error) {
                throw new Error(initData.error.message)
            }

            const { video_id: fbVideoId, upload_url } = initData
            if (!upload_url || !fbVideoId) {
                throw new Error('No upload URL or video ID returned')
            }

            // Download video and upload to Facebook
            const videoResp = await fetch(meta.publicUrl)
            const videoBuffer = await videoResp.arrayBuffer()

            const uploadResp = await fetch(upload_url, {
                method: 'POST',
                headers: {
                    'Authorization': `OAuth ${page.access_token}`,
                    'offset': '0',
                    'file_size': videoBuffer.byteLength.toString(),
                },
                body: videoBuffer,
            })
            const uploadData = await uploadResp.json() as { success?: boolean; error?: { message: string } }

            if (uploadData.error) {
                throw new Error(uploadData.error.message)
            }

            // Finish upload
            const finishResp = await fetch(
                `https://graph.facebook.com/v19.0/${page.id}/video_reels`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        upload_phase: 'finish',
                        video_id: fbVideoId,
                        video_state: 'PUBLISHED',
                        description: caption,
                        access_token: page.access_token,
                    }),
                }
            )
            const finishData = await finishResp.json() as { success?: boolean; error?: { message: string } }

            if (finishData.error) {
                throw new Error(finishData.error.message)
            }

            // Wait 10s for video to be processed before commenting
            if (meta.shopeeLink) {
                await new Promise(r => setTimeout(r, 10000))
                await fetch(`https://graph.facebook.com/v19.0/${fbVideoId}/comments`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: `📍Shopee : ${meta.shopeeLink}`,
                        access_token: page.access_token,
                    }),
                }).catch(e => console.error(`[CRON] Comment failed: ${e}`))
            }

            // Update to success
            await env.DB.prepare(
                "UPDATE post_history SET fb_post_id = ?, status = 'success' WHERE page_id = ? AND video_id = ? AND status = 'posting'"
            ).bind(fbVideoId, page.id, unpostedId).run()

            console.log(`[CRON] Page ${page.name}: posted successfully (fb_id: ${fbVideoId})`)

        } catch (e) {
            const errorMsg = e instanceof Error ? e.message : String(e)
            console.error(`[CRON] Page ${page.name}: post failed - ${errorMsg}`)

            // Update to failed
            await env.DB.prepare(
                "UPDATE post_history SET status = 'failed', error_message = ? WHERE page_id = ? AND video_id = ? AND status = 'posting'"
            ).bind(errorMsg, page.id, unpostedId).run()

            // Clean up dedup key to allow retry in next cron cycle
            await env.BUCKET.delete(dedupKey).catch(() => { })
        }
    }

    console.log('[CRON] Auto-post check complete')
}

// Container class สำหรับ FFmpeg merge
export class MergeContainer extends Container {
    defaultPort = 8080
    sleepAfter = '5m'
}

export default {
    fetch: app.fetch,
    scheduled: async (event: ScheduledEvent, env: Env, _ctx: ExecutionContext) => {
        await handleScheduled(env)
    },
}
