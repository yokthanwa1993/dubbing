/**
 * Dubbing Pipeline — 100% Cloudflare Native
 * ffmpeg merge รันใน Cloudflare Container
 */

export type Env = {
    DB: D1Database
    BUCKET: R2Bucket
    MERGE_CONTAINER: DurableObjectNamespace
    GOOGLE_API_KEY: string
    TELEGRAM_BOT_TOKEN: string
    R2_PUBLIC_URL: string
    XHS_DL_URL: string
    GEMINI_MODEL: string
    CORS_ORIGIN: string
}

// ==================== Telegram Helpers ====================

export async function sendTelegram(token: string, method: string, body: Record<string, unknown>) {
    const resp = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    })
    return resp.json() as Promise<{ ok: boolean; result?: Record<string, unknown> }>
}

type StepName = 'วิดีโอ' | 'วิเคราะห์' | 'เสียง' | 'รวม' | 'เสร็จ'

const STEP_ICONS: Record<StepName, string> = {
    'วิดีโอ': '📥',
    'วิเคราะห์': '🔍',
    'เสียง': '🎙️',
    'รวม': '🎬',
    'เสร็จ': '✅',
}

const STEP_DONE_TEXT: Record<StepName, string> = {
    'วิดีโอ': 'ดาวน์โหลดวิดีโอ',
    'วิเคราะห์': 'วิเคราะห์วิดีโอ',
    'เสียง': 'สร้างเสียงพากย์',
    'รวม': 'รวมวิดีโอ',
    'เสร็จ': 'เสร็จสิ้น',
}

const STEP_PROGRESS_TEXT: Record<StepName, string> = {
    'วิดีโอ': 'กำลังดาวน์โหลดวิดีโอ',
    'วิเคราะห์': 'กำลังวิเคราะห์วิดีโอ',
    'เสียง': 'กำลังสร้างเสียงพากย์',
    'รวม': 'กำลังรวมวิดีโอ',
    'เสร็จ': 'เสร็จสิ้น',
}

const DOT_FRAMES = ['', '.', '..', '...']

function buildStatusText(completedSteps: StepName[], currentStep?: StepName, dotIndex?: number): string {
    const lines: string[] = []
    for (const step of completedSteps) {
        lines.push(`${STEP_ICONS[step]} ${STEP_DONE_TEXT[step]} ✅`)
    }
    if (currentStep) {
        const dots = dotIndex !== undefined ? DOT_FRAMES[dotIndex % 4] : '...'
        lines.push(`${STEP_ICONS[currentStep]} ${STEP_PROGRESS_TEXT[currentStep]}${dots}`)
    }
    return lines.join('\n') || '⏳ เริ่มต้น...'
}

/** เริ่ม animation จุดวิ่ง — return ฟังก์ชัน stop() */
function startDotAnimation(
    token: string,
    chatId: number,
    msgId: number,
    completedSteps: StepName[],
    currentStep: StepName,
): () => void {
    let running = true
    let dotIndex = 0

    const loop = async () => {
        while (running) {
            const text = buildStatusText(completedSteps, currentStep, dotIndex)
            await sendTelegram(token, 'editMessageText', {
                chat_id: chatId,
                message_id: msgId,
                text,
                parse_mode: 'HTML',
            }).catch(() => { })
            dotIndex++
            if (running) {
                await new Promise(r => setTimeout(r, 600))
            }
        }
    }

    loop() // fire and forget — วนพร้อมกับงานหลัก

    return () => { running = false }
}

// ==================== XHS Download ====================

async function resolveXhsVideo(url: string, xhsDlUrl: string): Promise<string | null> {
    // เรียก XHS-Downloader API บน CapRover
    const resp = await fetch(`${xhsDlUrl}/xhs/detail`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, download: false }),
    })

    if (!resp.ok) return null

    const data = await resp.json() as {
        data?: { '下载地址'?: string[] }
    }

    const videoUrls = data?.data?.['下载地址']
    if (!videoUrls || videoUrls.length === 0) return null

    return videoUrls[0]
}

async function downloadVideo(videoUrl: string): Promise<ArrayBuffer> {
    const resp = await fetch(videoUrl, {
        headers: { 'Referer': 'https://www.xiaohongshu.com/' },
    })
    if (!resp.ok) throw new Error(`ดาวน์โหลดวิดีโอไม่ได้: ${resp.status}`)
    return resp.arrayBuffer()
}

// ==================== Gemini API ====================

async function uploadToGemini(videoBytes: ArrayBuffer, apiKey: string): Promise<{ fileUri: string; fileName: string }> {
    // Step 1: เริ่ม resumable upload
    const initResp = await fetch(
        `https://generativelanguage.googleapis.com/upload/v1beta/files?key=${apiKey}`,
        {
            method: 'POST',
            headers: {
                'X-Goog-Upload-Protocol': 'resumable',
                'X-Goog-Upload-Command': 'start',
                'X-Goog-Upload-Header-Content-Length': String(videoBytes.byteLength),
                'X-Goog-Upload-Header-Content-Type': 'video/mp4',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ file: { display_name: 'video.mp4' } }),
        }
    )

    const uploadUrl = initResp.headers.get('X-Goog-Upload-URL')
    if (!uploadUrl) throw new Error('ไม่ได้ upload URL จาก Gemini')

    // Step 2: อัพโหลดวิดีโอ
    const uploadResp = await fetch(uploadUrl, {
        method: 'POST',
        headers: {
            'X-Goog-Upload-Command': 'upload, finalize',
            'X-Goog-Upload-Offset': '0',
            'Content-Type': 'video/mp4',
        },
        body: videoBytes,
    })

    const result = await uploadResp.json() as {
        file?: { uri?: string; name?: string }
    }
    const fileUri = result?.file?.uri
    const fileName = result?.file?.name
    if (!fileUri || !fileName) throw new Error('อัพโหลดไป Gemini ไม่สำเร็จ')

    return { fileUri, fileName }
}

async function waitForProcessing(fileName: string, apiKey: string): Promise<string> {
    // รอ Gemini ประมวลผลวิดีโอ (poll ทุก 2 วินาที สูงสุด 30 รอบ)
    for (let i = 0; i < 30; i++) {
        const resp = await fetch(
            `https://generativelanguage.googleapis.com/v1beta/${fileName}?key=${apiKey}`
        )
        const data = await resp.json() as { state?: string; uri?: string }
        if (data.state !== 'PROCESSING') {
            return data.uri || ''
        }
        await new Promise(r => setTimeout(r, 2000))
    }
    throw new Error('Gemini ประมวลผลวิดีโอนานเกินไป')
}

async function generateScript(
    fileUri: string,
    duration: number,
    apiKey: string,
    model: string,
): Promise<string> {
    const targetChars = Math.floor(duration * 10)
    const minChars = Math.floor(duration * 8)

    const prompt = `คุณคือ "พี่ต้น" นักรีวิวสินค้าออนไลน์มือฉมัง ที่มีผู้ติดตามหลายล้านคน

ดูวิดีโอสินค้านี้แล้วเขียน script พากย์เสียงภาษาไทย

⚠️ สำคัญมาก: วิดีโอยาว ${Math.round(duration)} วินาที
- Script ต้องยาว ${minChars}-${targetChars} ตัวอักษร (ภาษาไทยพูดประมาณ 8-10 ตัว/วินาที)
- ถ้า script สั้นกว่านี้ วิดีโอจะถูกตัด!

สไตล์:
- เปิดด้วย "โห้ อันนี้ต้องมี!" หรือ "ของดีมาแล้วครับพี่น้อง!"
- บรรยายจุดเด่นของสินค้าตามที่เห็นในวิดีโอ อธิบายให้ละเอียด
- ใส่ประโยชน์การใช้งาน วิธีใช้ ข้อดี
- ปิดด้วย "สนใจสั่งเลยครับ รีบๆนะ ของมีจำกัด!"

ตอบเป็น JSON: {"thai_script": "ข้อความพากย์เสียงยาว ${minChars}-${targetChars} ตัวอักษร"}`

    const resp = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                contents: [{
                    parts: [
                        { fileData: { mimeType: 'video/mp4', fileUri } },
                        { text: prompt },
                    ]
                }],
                generationConfig: { temperature: 0.8, maxOutputTokens: 4096 },
            }),
        }
    )

    const result = await resp.json() as {
        candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>
    }

    let scriptText = result?.candidates?.[0]?.content?.parts?.[0]?.text || ''
    scriptText = scriptText.replace(/```json/g, '').replace(/```/g, '').trim()

    try {
        const parsed = JSON.parse(scriptText)
        return parsed.thai_script || ''
    } catch {
        // fallback: regex
        const match = scriptText.match(/"thai_script":\s*"([^"]+)"/)
        if (match) return match[1]
        return scriptText.slice(0, 200)
    }
}

async function generateTTS(script: string, apiKey: string): Promise<string> {
    const resp = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key=${apiKey}`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                contents: [{ parts: [{ text: script }] }],
                generationConfig: {
                    responseModalities: ['AUDIO'],
                    speechConfig: {
                        voiceConfig: { prebuiltVoiceConfig: { voiceName: 'Puck' } },
                    },
                },
            }),
        }
    )

    if (!resp.ok) {
        const err = await resp.json() as { error?: { message?: string } }
        throw new Error(`TTS ล้มเหลว: ${err?.error?.message || resp.status}`)
    }

    const result = await resp.json() as {
        candidates?: Array<{ content?: { parts?: Array<{ inlineData?: { data?: string } }> } }>
    }

    const audioBase64 = result?.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data
    if (!audioBase64) throw new Error('ไม่ได้เสียงจาก TTS')
    return audioBase64
}

// ==================== Container Merge ====================

async function callContainerMerge(
    env: Env,
    videoBytes: ArrayBuffer,
    audioBase64: string,
): Promise<{ video_base64: string; thumb_base64?: string; duration: number }> {
    const containerId = env.MERGE_CONTAINER.idFromName('merge-worker')
    const containerStub = env.MERGE_CONTAINER.get(containerId)

    const formData = new FormData()
    formData.append('video', new Blob([videoBytes], { type: 'video/mp4' }), 'video.mp4')
    formData.append('audio_base64', audioBase64)
    formData.append('sample_rate', '24000')

    const resp = await containerStub.fetch('http://container/merge', {
        method: 'POST',
        body: formData,
    })

    if (!resp.ok) {
        const err = await resp.json() as { error?: string }
        throw new Error(`Container merge ล้มเหลว: ${err?.error || resp.status}`)
    }

    return resp.json() as Promise<{ video_base64: string; thumb_base64?: string; duration: number }>
}

// ==================== Gallery Cache ====================

/** Rebuild _cache/gallery.json — อ่าน .json ทั้งหมดแล้วรวมเป็นไฟล์เดียว */
export async function rebuildGalleryCache(bucket: R2Bucket): Promise<unknown[]> {
    const list = await bucket.list({ prefix: 'videos/' })
    const videos: unknown[] = []

    for (const obj of list.objects) {
        if (!obj.key.endsWith('.json')) continue
        const metaObj = await bucket.get(obj.key)
        if (!metaObj) continue
        videos.push(await metaObj.json())
    }

    videos.sort((a: any, b: any) =>
        (b.createdAt || '').localeCompare(a.createdAt || '')
    )

    await bucket.put('_cache/gallery.json', JSON.stringify({ videos }), {
        httpMetadata: { contentType: 'application/json' },
    })

    return videos
}

// ==================== Main Pipeline ====================

export async function runPipeline(
    env: Env,
    videoUrl: string,
    chatId: number,
    statusMsgId: number,
) {
    const token = env.TELEGRAM_BOT_TOKEN
    const apiKey = env.GOOGLE_API_KEY
    const model = env.GEMINI_MODEL || 'gemini-3-flash-preview'
    const completed: StepName[] = []

    let stopAnim: (() => void) | null = null

    try {
        // === Step 1: ดาวน์โหลดวิดีโอ ===
        stopAnim = startDotAnimation(token, chatId, statusMsgId, completed, 'วิดีโอ')

        let directVideoUrl = videoUrl
        // ถ้าเป็น XHS link → ดึง URL จริงจาก API
        if (videoUrl.includes('xhs') || videoUrl.includes('xiaohongshu')) {
            const resolved = await resolveXhsVideo(videoUrl, env.XHS_DL_URL)
            if (!resolved) throw new Error('ไม่พบวิดีโอใน XHS link นี้')
            directVideoUrl = resolved
        }

        const videoBytes = await downloadVideo(directVideoUrl)
        console.log(`[PIPELINE] ดาวน์โหลดวิดีโอแล้ว: ${(videoBytes.byteLength / 1024 / 1024).toFixed(1)} MB`)

        // เก็บต้นฉบับไว้ใน R2
        const videoId = crypto.randomUUID().slice(0, 8)
        const originalKey = `videos/${videoId}_original.mp4`
        await env.BUCKET.put(originalKey, videoBytes, {
            httpMetadata: { contentType: 'video/mp4' },
        })
        const originalVideoUrl = `${env.R2_PUBLIC_URL}/${originalKey}`
        console.log(`[PIPELINE] เก็บต้นฉบับใน R2: ${originalKey}`)

        stopAnim()
        completed.push('วิดีโอ')

        // === Step 2: วิเคราะห์วิดีโอด้วย Gemini ===
        stopAnim = startDotAnimation(token, chatId, statusMsgId, completed, 'วิเคราะห์')

        const { fileUri, fileName } = await uploadToGemini(videoBytes, apiKey)
        console.log(`[PIPELINE] อัพโหลด Gemini แล้ว: ${fileName}`)

        const processedUri = await waitForProcessing(fileName, apiKey)
        const finalUri = processedUri || fileUri

        // คำนวณ duration จากขนาดไฟล์ (ประมาณ)
        // ถ้ามี duration จริงจะได้จาก CapRover merge ทีหลัง
        // ใช้ estimate 15 วินาทีเป็น default สำหรับ XHS short video
        const estimatedDuration = 15

        const script = await generateScript(finalUri, estimatedDuration, apiKey, model)
        if (!script || script.length < 10) {
            throw new Error('สร้าง script ไม่สำเร็จ')
        }
        console.log(`[PIPELINE] Script: ${script.slice(0, 60)}... (${script.length} ตัวอักษร)`)

        stopAnim()
        completed.push('วิเคราะห์')

        // === Step 3: สร้างเสียง TTS ===
        stopAnim = startDotAnimation(token, chatId, statusMsgId, completed, 'เสียง')

        const audioBase64 = await generateTTS(script, apiKey)
        console.log(`[PIPELINE] สร้างเสียงแล้ว: ${(audioBase64.length / 1024).toFixed(0)} KB base64`)

        stopAnim()
        completed.push('เสียง')

        // === Step 4: merge ใน Cloudflare Container ===
        stopAnim = startDotAnimation(token, chatId, statusMsgId, completed, 'รวม')

        const mergeResult = await callContainerMerge(env, videoBytes, audioBase64)
        console.log(`[PIPELINE] Container merge เสร็จ: duration=${mergeResult.duration}s`)

        // อัพโหลด merged video ไป R2
        const mergedVideoBytes = Uint8Array.from(atob(mergeResult.video_base64), c => c.charCodeAt(0))
        const videoKey = `videos/${videoId}.mp4`
        await env.BUCKET.put(videoKey, mergedVideoBytes, {
            httpMetadata: { contentType: 'video/mp4' },
        })
        const publicUrl = `${env.R2_PUBLIC_URL}/${videoKey}`
        console.log(`[PIPELINE] อัพโหลด R2: ${publicUrl}`)

        // อัพโหลด thumbnail (ถ้ามี)
        let thumbnailUrl = ''
        if (mergeResult.thumb_base64) {
            const thumbBytes = Uint8Array.from(atob(mergeResult.thumb_base64), c => c.charCodeAt(0))
            const thumbKey = `videos/${videoId}_thumb.webp`
            await env.BUCKET.put(thumbKey, thumbBytes, {
                httpMetadata: { contentType: 'image/webp' },
            })
            thumbnailUrl = `${env.R2_PUBLIC_URL}/${thumbKey}`
        }

        stopAnim()
        completed.push('รวม')

        // === Step 5: บันทึก metadata ใน R2 ===
        const metadata = {
            id: videoId,
            script,
            duration: mergeResult.duration,
            originalUrl: videoUrl,
            createdAt: new Date().toISOString(),
            publicUrl,
            thumbnailUrl,
        }
        await env.BUCKET.put(`videos/${videoId}.json`, JSON.stringify(metadata, null, 2), {
            httpMetadata: { contentType: 'application/json' },
        })

        // Rebuild gallery cache
        await rebuildGalleryCache(env.BUCKET)

        // === Step 6: แจ้ง Telegram ===
        // ลบ status message
        await sendTelegram(token, 'deleteMessage', {
            chat_id: chatId,
            message_id: statusMsgId,
        }).catch(() => { })

        // ส่งวิดีโอพร้อมปุ่มเปิดคลัง
        await sendTelegram(token, 'sendVideo', {
            chat_id: chatId,
            video: publicUrl,
            reply_markup: {
                inline_keyboard: [[
                    { text: '🎥 เปิดคลัง', web_app: { url: 'https://dubbing-webapp.pages.dev?tab=gallery' } },
                ]],
            },
        })

        console.log(`[PIPELINE] เสร็จสมบูรณ์! videoId=${videoId}`)

    } catch (error) {
        if (stopAnim) stopAnim()
        const errMsg = error instanceof Error ? error.message : String(error)
        console.error(`[PIPELINE] ผิดพลาด: ${errMsg}`)

        // แจ้ง error กลับ Telegram
        await sendTelegram(token, 'editMessageText', {
            chat_id: chatId,
            message_id: statusMsgId,
            text: `❌ ผิดพลาด\n\n${errMsg.slice(0, 150)}`,
            parse_mode: 'HTML',
        }).catch(() => { })
    }
}
