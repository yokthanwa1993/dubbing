import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { type Env, rebuildGalleryCache, sendTelegram } from './pipeline'

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

// ==================== TELEGRAM WEBHOOK ====================

app.post('/api/telegram', async (c) => {
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

    // กรณีส่งวิดีโอมา
    if (msg.video) {
        const fileInfo = await fetch(
            `https://api.telegram.org/bot${token}/getFile?file_id=${msg.video.file_id}`
        ).then(r => r.json()) as { ok: boolean; result?: { file_path: string } }

        if (fileInfo.ok && fileInfo.result) {
            const videoUrl = `https://api.telegram.org/file/bot${token}/${fileInfo.result.file_path}`
            await c.env.BUCKET.put(dedupKey, 'processing')
            const statusMsg = await sendTelegram(token, 'sendMessage', {
                chat_id: chatId,
                text: '📥 กำลังดาวน์โหลดวิดีโอ...',
                parse_mode: 'HTML',
            })
            const msgId = (statusMsg.result as { message_id: number })?.message_id

            if (msgId) {
                // ส่งงานไป CapRover — รอแค่ 202 response (CapRover รัน background)
                const pipeResp = await fetch(`${c.env.CAPROVER_MERGE_URL}/pipeline`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ videoUrl, chatId, msgId }),
                }).catch(e => console.error('CapRover pipeline error:', e))
                if (pipeResp) console.log('CapRover pipeline response:', pipeResp.status)
            }
        }
        return c.text('ok')
    }

    // กรณีส่ง XHS link
    const xhsMatch = text.match(/https?:\/\/(xhslink\.com|www\.xiaohongshu\.com)\S+/)
    if (xhsMatch) {
        const videoUrl = xhsMatch[0]
        await c.env.BUCKET.put(dedupKey, 'processing')
        const statusMsg = await sendTelegram(token, 'sendMessage', {
            chat_id: chatId,
            text: '📥 กำลังดาวน์โหลดวิดีโอ...',
            parse_mode: 'HTML',
        })
        const msgId = (statusMsg.result as { message_id: number })?.message_id

        if (msgId) {
            // ส่งงานไป CapRover — รอแค่ 202 response (CapRover รัน background)
            const pipeResp = await fetch(`${c.env.CAPROVER_MERGE_URL}/pipeline`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ videoUrl, chatId, msgId }),
            }).catch(e => console.error('CapRover pipeline error:', e))
            if (pipeResp) console.log('CapRover pipeline response:', pipeResp.status)
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
        await sendTelegram(token, 'sendMessage', {
            chat_id: chatId,
            text: '❌ รองรับเฉพาะลิงก์ Xiaohongshu หรืออัพโหลดวิดีโอเท่านั้น\n\nตัวอย่าง: http://xhslink.com/...',
        })
    }

    return c.text('ok')
})

// ==================== GALLERY API (R2) ====================

app.get('/api/gallery', async (c) => {
    try {
        // อ่านจาก cache file เดียว (เร็วกว่าอ่านทีละไฟล์มาก)
        const cached = await c.env.BUCKET.get('_cache/gallery.json')
        if (cached) {
            return c.json(await cached.json())
        }

        // ถ้ายังไม่มี cache → สร้างใหม่
        const videos = await rebuildGalleryCache(c.env.BUCKET)
        return c.json({ videos })
    } catch (e) {
        return c.json({ videos: [], error: String(e) })
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
            'SELECT id, name, image_url, post_interval_minutes, is_active, last_post_at, created_at FROM pages ORDER BY created_at DESC'
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
            'SELECT id, name, image_url, post_interval_minutes, is_active, last_post_at, created_at FROM pages WHERE id = ?'
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
        const { post_interval_minutes, is_active } = body

        await c.env.DB.prepare(
            'UPDATE pages SET post_interval_minutes = ?, is_active = ?, updated_at = datetime("now") WHERE id = ?'
        ).bind(post_interval_minutes, is_active ? 1 : 0, id).run()

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

export default app
