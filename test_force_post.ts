const WORKER_URL = 'https://dubbing-worker.yokthanwa1993-bc9.workers.dev'
const PAGE_ID = '106489280989050' // เพจ ว้าว

async function main() {
    console.log('')
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    console.log('  🔬 เทส Force Post แบบละเอียด')
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')

    // ดึงข้อมูลเพจ
    console.log('\n📡 กำลังดึงข้อมูลเพจ...')
    const pageResp = await fetch(`${WORKER_URL}/api/pages/${PAGE_ID}`)
    const pageData = await pageResp.json() as any
    const page = pageData.page

    const accessToken: string = page.access_token || ''
    const commentToken: string = page.comment_token || ''

    console.log(`\n📄 เพจ: ${page.name} (ID: ${PAGE_ID})`)
    console.log('')
    console.log('┌─────────────────────────────────────────')
    console.log(`│ 🔑 ACCESS TOKEN (ใช้โพสต์ Reel):`)
    console.log(`│    ${accessToken}`)
    console.log('│')

    if (commentToken) {
        console.log(`│ 💬 COMMENT TOKEN (ใช้คอมเม้นท์):`)
        console.log(`│    ${commentToken}`)
        console.log('│')
        console.log(accessToken === commentToken
            ? '│ ⚠️  TOKEN เหมือนกัน!'
            : '│ ✅ TOKEN แยกกัน — คอมเม้นท์ใช้คนละตัวกับโพสต์')
    } else {
        console.log('│ 💬 COMMENT TOKEN: ไม่มี')
        console.log('│ ⚠️  จะใช้ ACCESS TOKEN ตัวเดียวกันคอมเม้นท์')
    }
    console.log('└─────────────────────────────────────────')

    // Force Post
    console.log('\n🚀 กำลัง Force Post...\n')
    const postResp = await fetch(`${WORKER_URL}/api/pages/${PAGE_ID}/force-post`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    })
    const result = await postResp.json() as any

    if (result.success) {
        const actualCT = commentToken || accessToken
        const ctLabel = commentToken
            ? 'COMMENT TOKEN (แยกจาก access token)'
            : 'ACCESS TOKEN (fallback — ไม่มี comment token)'

        console.log('✅ โพสต์สำเร็จ!')
        console.log('')
        console.log('┌─────────────────────────────────────────')
        console.log(`│ Video ID:    ${result.video_id}`)
        console.log(`│ FB Video ID: ${result.fb_video_id}`)
        console.log(`│ Reel:        https://www.facebook.com/reel/${result.fb_video_id}`)
        console.log('│')
        console.log('│ 🔑 โพสต์ด้วย: ACCESS TOKEN')
        console.log(`│    ${accessToken}`)
        console.log('│')
        console.log(`│ 💬 คอมเม้นท์ด้วย: ${ctLabel}`)
        console.log(`│    ${actualCT}`)
        console.log('└─────────────────────────────────────────')
        console.log('')
        console.log(`⏳ รอ Cron คอมเม้นท์... (~1 นาที)`)
        console.log(`   ไปเช็คที่ Reel: https://www.facebook.com/reel/${result.fb_video_id}`)
    } else {
        console.log('❌ โพสต์ไม่สำเร็จ!')
        console.log(`   Error: ${result.error}`)
        if (result.details) console.log(`   Details: ${result.details}`)
    }

    console.log('')
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
}

main().catch(console.error)
