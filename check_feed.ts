const WORKER_URL = 'https://dubbing-worker.yokthanwa1993-bc9.workers.dev'
const FEED_PAGE_ID = '116759241338040'

async function main() {
    // 1. ดึง token ของเพจฟีด
    const pageResp = await fetch(`${WORKER_URL}/api/pages/${FEED_PAGE_ID}`)
    const pageData = await pageResp.json() as any
    const page = pageData.page

    console.log(`📄 เพจ: ${page.name}`)
    console.log(`🔑 Access Token: ${page.access_token}`)
    console.log(`💬 Comment Token: ${page.comment_token || 'NULL'}`)
    console.log(`✅ แยก Token: ${page.comment_token && page.comment_token !== page.access_token ? 'YES' : 'NO'}`)
    console.log('')

    // 2. ทดสอบ Comment Token ว่ายัง valid ไหม
    console.log('--- ทดสอบ Comment Token ---')
    const ctResp = await fetch(`https://graph.facebook.com/v19.0/me?access_token=${page.comment_token}`)
    const ctData = await ctResp.json() as any
    console.log('Comment Token /me:', JSON.stringify(ctData))
    console.log('')

    // 3. ทดสอบ Access Token
    console.log('--- ทดสอบ Access Token ---')
    const atResp = await fetch(`https://graph.facebook.com/v19.0/me?access_token=${page.access_token}`)
    const atData = await atResp.json() as any
    console.log('Access Token /me:', JSON.stringify(atData))
    console.log('')

    // 4. ดู comment ของ Reel ล่าสุด
    const FB_VIDEO_ID = '1630410878087516'
    console.log(`--- ดู comments ของ Reel ${FB_VIDEO_ID} ---`)
    const commResp = await fetch(`https://graph.facebook.com/v19.0/${FB_VIDEO_ID}/comments?access_token=${page.access_token}`)
    const commData = await commResp.json() as any
    console.log('Comments:', JSON.stringify(commData, null, 2))
    console.log('')

    // 5. ดู video info ว่า meta มี shopeeLink ไหม
    console.log('--- ดู video meta (8fd5c0e1) ---')
    const metaResp = await fetch(`${WORKER_URL}/api/gallery/8fd5c0e1`)
    const meta = await metaResp.json() as any
    console.log('shopeeLink:', meta.shopeeLink || 'NULL')
    console.log('category:', meta.category || 'NULL')
}

main().catch(console.error)
