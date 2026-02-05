import { Hono } from "hono";
import { cors } from "hono/cors";

type Bindings = {
  GOOGLE_API_KEY: string;
  CF_ACCOUNT_ID: string;
  CF_GATEWAY_NAME: string;
  XHS_COOKIES: string;
  FB_PAGE_TOKEN: string;
  FB_PAGE_ID: string;
  TELEGRAM_BOT_TOKEN: string;
  DB: D1Database;
  R2: R2Bucket;
  ASSETS: Fetcher;
};

const app = new Hono<{ Bindings: Bindings }>();

app.use("*", cors());

// Default XHS cookies (can be overridden via env)
const DEFAULT_XHS_COOKIES = {
  "acw_tc": "",
  "abRequestId": "",
  "a1": "",
  "webId": "",
  "web_session": "",
};

// Health check
app.get("/api/health", (c) => {
  return c.json({ status: "ok", timestamp: new Date().toISOString() });
});

// XHS Download - resolve short URL and get video URL
app.post("/api/xhs/resolve", async (c) => {
  try {
    const { url } = await c.req.json();

    if (!url) {
      return c.json({ error: "URL is required" }, 400);
    }

    // Parse cookies from env or use defaults
    let cookies: Record<string, string> = DEFAULT_XHS_COOKIES;
    if (c.env.XHS_COOKIES) {
      try {
        cookies = JSON.parse(c.env.XHS_COOKIES);
      } catch { }
    }

    // Build cookie string
    const cookieStr = Object.entries(cookies)
      .filter(([_, v]) => v)
      .map(([k, v]) => `${k}=${v}`)
      .join("; ");

    // Resolve short URL
    const response = await fetch(url, {
      headers: {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Cookie": cookieStr,
      },
      redirect: "follow",
    });

    const finalUrl = response.url;
    const html = await response.text();

    // Try to extract video URL from HTML
    const videoMatch = html.match(/https:\/\/sns-video[^"'\s]+\.mp4[^"'\s]*/);
    const videoUrl = videoMatch ? videoMatch[0].replace(/\\u002F/g, "/") : null;

    // Extract note ID
    const noteIdMatch = finalUrl.match(/\/explore\/([a-f0-9]+)/);
    const noteId = noteIdMatch ? noteIdMatch[1] : null;

    return c.json({
      success: true,
      originalUrl: url,
      resolvedUrl: finalUrl,
      noteId,
      videoUrl,
      hasVideo: !!videoUrl,
    });
  } catch (error) {
    return c.json({ error: String(error) }, 500);
  }
});

// Get current cookies config
app.get("/api/xhs/cookies", (c) => {
  let cookies = DEFAULT_XHS_COOKIES;
  if (c.env.XHS_COOKIES) {
    try {
      cookies = JSON.parse(c.env.XHS_COOKIES);
    } catch { }
  }
  // Mask cookie values for security
  const maskedCookies = Object.fromEntries(
    Object.entries(cookies).map(([k, v]) => [k, v ? `${v.slice(0, 8)}...` : "(not set)"])
  );
  return c.json({ cookies: maskedCookies });
});

// Serve videos from R2
app.get("/videos/:id", async (c) => {
  const videoId = c.req.param("id");
  const object = await c.env.R2.get(`videos/${videoId}`);

  if (!object) {
    return c.json({ error: "Video not found" }, 404);
  }

  const headers = new Headers();
  headers.set("Content-Type", "video/mp4");
  headers.set("Cache-Control", "public, max-age=86400");

  return new Response(object.body, { headers });
});

// ========== TELEGRAM BOT WEBHOOK ==========
app.post("/api/telegram/webhook", async (c) => {
  try {
    const update = await c.req.json();
    const message = update.message;

    // Get chat ID
    const chatId = message?.chat?.id;
    if (!chatId) {
      return c.json({ ok: true });
    }

    // Helper to send telegram message
    const sendTelegram = async (text: string) => {
      await fetch(`https://api.telegram.org/bot${c.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, text, parse_mode: "HTML" }),
      });
    };


    // Handle video file sent directly OR from link preview
    const video = message?.video || message?.link_preview_options?.video;
    if (video) {
      const fileId = video.file_id;

      // Get file path from Telegram
      const fileResponse = await fetch(
        `https://api.telegram.org/bot${c.env.TELEGRAM_BOT_TOKEN}/getFile?file_id=${fileId}`
      );
      const fileResult = await fileResponse.json() as { ok: boolean; result?: { file_path: string } };

      if (fileResult.ok && fileResult.result?.file_path) {
        const videoUrl = `https://api.telegram.org/file/bot${c.env.TELEGRAM_BOT_TOKEN}/${fileResult.result.file_path}`;

        // Create job
        const jobId = crypto.randomUUID();
        await c.env.DB.prepare(
          "INSERT INTO jobs (id, source_url, status) VALUES (?, ?, ?)"
        ).bind(jobId, videoUrl, "pending").run();

        await sendTelegram(`📥 รับวิดีโอจาก Telegram!\n\nJob ID: <code>${jobId.slice(0, 8)}...</code>\n\n🚀 กำลังประมวลผล...`);

        c.executionCtx.waitUntil(processJob(c.env, jobId, videoUrl, chatId));
        return c.json({ ok: true });
      }
    }

    // Also check for external video URL in link preview
    const externalVideo = message?.link_preview_options?.url;
    if (externalVideo && (externalVideo.includes('.mp4') || externalVideo.includes('video'))) {
      const jobId = crypto.randomUUID();
      await c.env.DB.prepare(
        "INSERT INTO jobs (id, source_url, status) VALUES (?, ?, ?)"
      ).bind(jobId, externalVideo, "pending").run();

      await sendTelegram(`📥 รับลิงก์วิดีโอจาก preview!\n\nJob ID: <code>${jobId.slice(0, 8)}...</code>\n\n🚀 กำลังประมวลผล...`);

      c.executionCtx.waitUntil(processJob(c.env, jobId, externalVideo, chatId));
      return c.json({ ok: true });
    }

    // Handle text message
    const text = message?.text?.trim();
    if (!text) {
      return c.json({ ok: true });
    }

    // Handle /start command
    if (text === "/start") {
      await sendTelegram("🎬 <b>Dubbing Bot</b>\n\nส่งลิงก์ XHS/วิดีโอมา แล้วจะ dub เป็นภาษาไทยและโพสลง FB Reels ให้!");
      return c.json({ ok: true });
    }

    // Handle /status command
    if (text === "/status") {
      const jobs = await c.env.DB.prepare(
        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 5"
      ).all();

      if (!jobs.results?.length) {
        await sendTelegram("📭 ยังไม่มีงานในระบบ");
      } else {
        const statusEmoji: Record<string, string> = {
          pending: "⏳",
          processing: "🔄",
          completed: "✅",
          failed: "❌",
        };
        const list = jobs.results.map((j: any) =>
          `${statusEmoji[j.status] || "❓"} ${j.id.slice(0, 8)}... - ${j.status}`
        ).join("\n");
        await sendTelegram(`📋 <b>งานล่าสุด:</b>\n${list}`);
      }
      return c.json({ ok: true });
    }

    // Check if it's a URL
    const urlMatch = text.match(/https?:\/\/[^\s]+/);
    if (urlMatch) {
      const url = urlMatch[0];

      // Create job
      const jobId = crypto.randomUUID();
      await c.env.DB.prepare(
        "INSERT INTO jobs (id, source_url, status) VALUES (?, ?, ?)"
      ).bind(jobId, url, "pending").run();

      await sendTelegram(`📥 รับลิงก์แล้ว!\n\nJob ID: <code>${jobId.slice(0, 8)}...</code>\n\nกำลังประมวลผล...`);

      // Process in background (trigger queue or direct call)
      c.executionCtx.waitUntil(processJob(c.env, jobId, url, chatId));

      return c.json({ ok: true });
    }

    await sendTelegram("❓ ส่งลิงก์ XHS หรือลิงก์วิดีโอมาเลย!\n\nหรือใช้ /status ดูสถานะงาน");
    return c.json({ ok: true });

  } catch (error) {
    console.error("Telegram webhook error:", error);
    return c.json({ ok: true });
  }
});

// Background job processor - calls merge-api for full pipeline
async function processJob(env: Bindings, jobId: string, sourceUrl: string, chatId: number) {
  let statusMessageId: number | null = null;

  // Send initial message and get message_id
  const sendInitialStatus = async (text: string): Promise<number> => {
    const resp = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text, parse_mode: "HTML" }),
    });
    const result = await resp.json() as { ok: boolean; result?: { message_id: number } };
    return result.result?.message_id || 0;
  };

  // Update existing message
  const updateStatus = async (text: string) => {
    if (!statusMessageId) return;
    await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/editMessageText`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        message_id: statusMessageId,
        text,
        parse_mode: "HTML"
      }),
    });
  };

  try {
    // Update status
    await env.DB.prepare("UPDATE jobs SET status = ?, updated_at = datetime('now') WHERE id = ?")
      .bind("processing", jobId).run();

    // Send initial status message
    statusMessageId = await sendInitialStatus("🚀 <b>กำลังประมวลผล...</b>\n\n⏳ เริ่มต้น...");

    // Call merge-api full-pipeline with callback for status updates
    const callbackUrl = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/editMessageText`;

    await updateStatus("🚀 <b>กำลังประมวลผล...</b>\n\n📥 ดาวน์โหลดวิดีโอ...");

    const response = await fetch("http://merge-api.lslly.com/full-pipeline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        videoUrl: sourceUrl,
        googleApiKey: env.GOOGLE_API_KEY,
        fbPageId: env.FB_PAGE_ID,
        fbPageToken: env.FB_PAGE_TOKEN,
      }),
    });

    const result = await response.json() as {
      success: boolean;
      reelUrl?: string;
      videoId?: string;
      script?: string;
      originalVideoUrl?: string;
      error?: string
    };

    if (result.success) {
      await updateStatus("🚀 <b>กำลังประมวลผล...</b>\n\n💾 บันทึกวิดีโอต้นฉบับ...");

      // Download original video and save to R2
      let r2VideoUrl = "";
      if (result.originalVideoUrl) {
        try {
          const videoResp = await fetch(result.originalVideoUrl);
          if (videoResp.ok) {
            const videoData = await videoResp.arrayBuffer();
            const videoKey = `videos/${jobId}.mp4`;
            await env.R2.put(videoKey, videoData, {
              httpMetadata: { contentType: "video/mp4" }
            });
            r2VideoUrl = `https://dubbing-app.yokthanwa1993-bc9.workers.dev/videos/${jobId}.mp4`;
          }
        } catch (e) {
          console.log("Failed to save to R2:", e);
        }
      }

      await env.DB.prepare(
        "UPDATE jobs SET status = ?, reel_url = ?, reel_id = ?, script = ?, updated_at = datetime('now') WHERE id = ?"
      ).bind("completed", result.reelUrl, result.videoId, result.script || "", jobId).run();

      await updateStatus(`✅ <b>เสร็จแล้ว!</b>\n\n📝 ${(result.script || "").substring(0, 80)}...\n\n🎬 ${result.reelUrl}\n\n📥 ${r2VideoUrl || "N/A"}`);
    } else {
      throw new Error(result.error || "Unknown error");
    }

  } catch (error) {
    await env.DB.prepare(
      "UPDATE jobs SET status = ?, error = ?, updated_at = datetime('now') WHERE id = ?"
    ).bind("failed", String(error), jobId).run();

    if (statusMessageId) {
      await updateStatus(`❌ <b>เกิดข้อผิดพลาด</b>\n\n${String(error).slice(0, 150)}`);
    }
  }
}

// ========== DASHBOARD API ==========
// Get all jobs
app.get("/api/jobs", async (c) => {
  const status = c.req.query("status");
  let query = "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50";

  if (status) {
    query = `SELECT * FROM jobs WHERE status = '${status}' ORDER BY created_at DESC LIMIT 50`;
  }

  const jobs = await c.env.DB.prepare(query).all();
  return c.json({ jobs: jobs.results || [] });
});

// Get job stats
app.get("/api/jobs/stats", async (c) => {
  const stats = await c.env.DB.prepare(`
    SELECT 
      COUNT(*) as total,
      SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
      SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing,
      SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
      SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
    FROM jobs
  `).first();

  return c.json(stats || { total: 0, pending: 0, processing: 0, completed: 0, failed: 0 });
});

// Facebook Reels - Initialize upload
app.post("/api/fb/reels/init", async (c) => {
  try {
    const { description } = await c.req.json();

    const pageId = c.env.FB_PAGE_ID;
    const token = c.env.FB_PAGE_TOKEN;

    if (!pageId || !token) {
      return c.json({ error: "FB_PAGE_ID and FB_PAGE_TOKEN are required" }, 400);
    }

    // Initialize resumable upload for Reels
    const response = await fetch(
      `https://graph.facebook.com/v21.0/${pageId}/video_reels`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          upload_phase: "start",
          access_token: token,
        }),
      }
    );

    const result = await response.json() as any;

    if (result.error) {
      return c.json({ error: result.error.message }, 400);
    }

    return c.json({
      success: true,
      videoId: result.video_id,
      uploadUrl: result.upload_url,
    });
  } catch (error) {
    return c.json({ error: String(error) }, 500);
  }
});

// Facebook Reels - Upload video from URL
app.post("/api/fb/reels/upload", async (c) => {
  try {
    const { videoUrl, uploadUrl } = await c.req.json();

    if (!videoUrl || !uploadUrl) {
      return c.json({ error: "videoUrl and uploadUrl are required" }, 400);
    }

    // Download video
    const videoResponse = await fetch(videoUrl);
    const videoBuffer = await videoResponse.arrayBuffer();
    const fileSize = videoBuffer.byteLength;

    // Upload to Facebook
    const uploadResponse = await fetch(uploadUrl, {
      method: "POST",
      headers: {
        "Authorization": `OAuth ${c.env.FB_PAGE_TOKEN}`,
        "offset": "0",
        "file_size": fileSize.toString(),
        "Content-Type": "application/octet-stream",
      },
      body: videoBuffer,
    });

    const result = await uploadResponse.json() as any;

    if (result.error) {
      return c.json({ error: result.error.message }, 400);
    }

    return c.json({
      success: true,
      uploaded: true,
      result,
    });
  } catch (error) {
    return c.json({ error: String(error) }, 500);
  }
});

// Facebook Reels - Publish
app.post("/api/fb/reels/publish", async (c) => {
  try {
    const { videoId, description = "" } = await c.req.json();

    const pageId = c.env.FB_PAGE_ID;
    const token = c.env.FB_PAGE_TOKEN;

    if (!videoId) {
      return c.json({ error: "videoId is required" }, 400);
    }

    // Publish the reel
    const response = await fetch(
      `https://graph.facebook.com/v21.0/${pageId}/video_reels`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          upload_phase: "finish",
          video_id: videoId,
          video_state: "PUBLISHED",
          description,
          access_token: token,
        }),
      }
    );

    const result = await response.json() as any;

    if (result.error) {
      return c.json({ error: result.error.message }, 400);
    }

    return c.json({
      success: true,
      published: true,
      reelId: result.video_id || videoId,
      reelUrl: `https://www.facebook.com/reel/${result.video_id || videoId}`,
    });
  } catch (error) {
    return c.json({ error: String(error) }, 500);
  }
});

// Facebook Reels - Full pipeline (init + upload + publish)
app.post("/api/fb/reels/auto", async (c) => {
  try {
    const { videoUrl, description = "" } = await c.req.json();

    const pageId = c.env.FB_PAGE_ID;
    const token = c.env.FB_PAGE_TOKEN;

    if (!videoUrl) {
      return c.json({ error: "videoUrl is required" }, 400);
    }
    if (!pageId || !token) {
      return c.json({ error: "FB_PAGE_ID and FB_PAGE_TOKEN are required" }, 400);
    }

    // Step 1: Initialize upload
    const initResponse = await fetch(
      `https://graph.facebook.com/v21.0/${pageId}/video_reels`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          upload_phase: "start",
          access_token: token,
        }),
      }
    );
    const initResult = await initResponse.json() as any;
    if (initResult.error) {
      return c.json({ error: `Init failed: ${initResult.error.message}` }, 400);
    }

    const videoId = initResult.video_id;
    const uploadUrl = initResult.upload_url;

    // Step 2: Download and upload video
    const videoResponse = await fetch(videoUrl);
    const videoBuffer = await videoResponse.arrayBuffer();

    const uploadResponse = await fetch(uploadUrl, {
      method: "POST",
      headers: {
        "Authorization": `OAuth ${token}`,
        "offset": "0",
        "file_size": videoBuffer.byteLength.toString(),
        "Content-Type": "application/octet-stream",
      },
      body: videoBuffer,
    });
    const uploadResult = await uploadResponse.json() as any;
    if (uploadResult.error) {
      return c.json({ error: `Upload failed: ${uploadResult.error.message}` }, 400);
    }

    // Step 3: Publish
    const publishResponse = await fetch(
      `https://graph.facebook.com/v21.0/${pageId}/video_reels`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          upload_phase: "finish",
          video_id: videoId,
          video_state: "PUBLISHED",
          description,
          access_token: token,
        }),
      }
    );
    const publishResult = await publishResponse.json() as any;
    if (publishResult.error) {
      return c.json({ error: `Publish failed: ${publishResult.error.message}` }, 400);
    }

    return c.json({
      success: true,
      videoId,
      reelUrl: `https://www.facebook.com/reel/${videoId}`,
      description,
    });
  } catch (error) {
    return c.json({ error: String(error) }, 500);
  }
});

// Step 1: Upload video to Google File API
async function uploadToGoogleFiles(file: File, apiKey: string): Promise<string> {
  // Step 1: Start resumable upload
  const startResponse = await fetch(
    `https://generativelanguage.googleapis.com/upload/v1beta/files?key=${apiKey}`,
    {
      method: "POST",
      headers: {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": file.size.toString(),
        "X-Goog-Upload-Header-Content-Type": file.type,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        file: { display_name: file.name }
      }),
    }
  );

  const uploadUrl = startResponse.headers.get("X-Goog-Upload-URL");
  if (!uploadUrl) {
    throw new Error("Failed to get upload URL");
  }

  // Step 2: Upload the file
  const fileBytes = await file.arrayBuffer();
  const uploadResponse = await fetch(uploadUrl, {
    method: "POST",
    headers: {
      "X-Goog-Upload-Command": "upload, finalize",
      "X-Goog-Upload-Offset": "0",
      "Content-Type": file.type,
    },
    body: fileBytes,
  });

  const result = await uploadResponse.json() as any;

  if (!result.file?.uri) {
    throw new Error("Upload failed: " + JSON.stringify(result));
  }

  // Step 3: Wait for processing
  const fileName = result.file.name;
  let fileState = result.file.state;

  while (fileState === "PROCESSING") {
    await new Promise(r => setTimeout(r, 2000));

    const checkResponse = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/${fileName}?key=${apiKey}`
    );
    const checkResult = await checkResponse.json() as any;
    fileState = checkResult.state;

    if (fileState === "FAILED") {
      throw new Error("File processing failed");
    }
  }

  return result.file.uri;
}

// Analyze video with Gemini
app.post("/api/analyze-video", async (c) => {
  try {
    const formData = await c.req.formData();
    const videoFile = formData.get("video") as File;

    if (!videoFile) {
      return c.json({ error: "Video file is required" }, 400);
    }

    console.log(`Uploading video: ${videoFile.name} (${(videoFile.size / 1024 / 1024).toFixed(2)} MB)`);

    // Upload to Google File API
    const fileUri = await uploadToGoogleFiles(videoFile, c.env.GOOGLE_API_KEY);
    console.log(`File uploaded: ${fileUri}`);

    // Call Gemini with file reference
    const gatewayUrl = `https://gateway.ai.cloudflare.com/v1/${c.env.CF_ACCOUNT_ID}/${c.env.CF_GATEWAY_NAME}/google-ai-studio`;
    const endpoint = `${gatewayUrl}/v1beta/models/gemini-3-flash-preview:generateContent`;

    const payload = {
      contents: [{
        parts: [
          {
            fileData: {
              mimeType: videoFile.type,
              fileUri: fileUri
            }
          },
          {
            text: `วิเคราะห์วิดีโอนี้และสร้าง script ภาษาไทยสำหรับพากย์เสียง

กรุณาให้ข้อมูลในรูปแบบ JSON ดังนี้:
{
  "title": "ชื่อวิดีโอ",
  "totalDuration": ความยาวทั้งหมดเป็นวินาที,
  "segments": [
    {
      "start": เวลาเริ่มต้น (วินาที),
      "end": เวลาสิ้นสุด (วินาที),
      "duration": ความยาว (วินาที),
      "originalText": "เนื้อหาต้นฉบับ (ถ้ามีเสียงพูด)",
      "thaiText": "ข้อความภาษาไทยที่จะพากย์ (ปรับให้พอดีกับเวลา)"
    }
  ],
  "description": "คำอธิบายวิดีโอโดยรวม"
}

สำคัญ:
- แบ่ง segments ตามช่วงเวลาที่มีการพูดหรือเหตุการณ์สำคัญ
- ข้อความภาษาไทยต้องพอดีกับความยาวของแต่ละ segment
- ใช้ภาษาไทยที่เป็นธรรมชาติ ไม่แข็งทื่อ
- ตอบเป็น JSON เท่านั้น ไม่ต้องมี markdown code block`
          }
        ]
      }],
      generationConfig: {
        temperature: 0.7,
        maxOutputTokens: 8192,
      }
    };

    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": c.env.GOOGLE_API_KEY,
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const error = await response.text();
      return c.json({ error: `Gemini API error: ${response.status}`, details: error }, 500);
    }

    const result = await response.json() as any;

    if (result.candidates?.[0]?.content?.parts?.[0]?.text) {
      let analysisText = result.candidates[0].content.parts[0].text;
      analysisText = analysisText.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();

      try {
        const analysis = JSON.parse(analysisText);
        return c.json({ success: true, analysis });
      } catch {
        return c.json({ success: true, rawText: analysisText });
      }
    }

    return c.json({ error: "No analysis in response" }, 500);
  } catch (error) {
    console.error("Error:", error);
    return c.json({ error: String(error) }, 500);
  }
});

// TTS endpoint
app.post("/api/tts", async (c) => {
  try {
    const { text, voice = "Kore" } = await c.req.json();

    if (!text) {
      return c.json({ error: "Text is required" }, 400);
    }

    const gatewayUrl = `https://gateway.ai.cloudflare.com/v1/${c.env.CF_ACCOUNT_ID}/${c.env.CF_GATEWAY_NAME}/google-ai-studio`;
    const endpoint = `${gatewayUrl}/v1beta/models/gemini-2.5-flash-preview-tts:generateContent`;

    const payload = {
      contents: [{ parts: [{ text }] }],
      generationConfig: {
        responseModalities: ["AUDIO"],
        speechConfig: {
          voiceConfig: {
            prebuiltVoiceConfig: { voiceName: voice },
          },
        },
      },
    };

    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": c.env.GOOGLE_API_KEY,
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const error = await response.text();
      return c.json({ error: `TTS API error: ${response.status}`, details: error }, 500);
    }

    const result = await response.json() as any;

    if (result.candidates?.[0]?.content?.parts?.[0]?.inlineData) {
      const audioData = result.candidates[0].content.parts[0].inlineData;
      return c.json({
        success: true,
        audio: audioData.data,
        mimeType: audioData.mimeType,
      });
    }

    return c.json({ error: "No audio data in response" }, 500);
  } catch (error) {
    return c.json({ error: String(error) }, 500);
  }
});

// Available voices
app.get("/api/voices", (c) => {
  return c.json({
    voices: [
      { id: "Puck", name: "Puck", gender: "Male" },
      { id: "Charon", name: "Charon", gender: "Male" },
      { id: "Kore", name: "Kore", gender: "Female" },
      { id: "Fenrir", name: "Fenrir", gender: "Male" },
      { id: "Aoede", name: "Aoede", gender: "Female" },
    ],
  });
});

// ========== FULL DUBBING PIPELINE ==========
// Complete pipeline: XHS download -> analyze -> TTS -> merge -> FB Reels
const MERGE_API_URL = "http://merge-api.lslly.com";

app.post("/api/dub/full", async (c) => {
  try {
    const { xhsUrl, voice = "Puck", description } = await c.req.json();

    if (!xhsUrl) {
      return c.json({ error: "xhsUrl is required" }, 400);
    }

    const gatewayUrl = `https://gateway.ai.cloudflare.com/v1/${c.env.CF_ACCOUNT_ID}/${c.env.CF_GATEWAY_NAME}/google-ai-studio`;

    // Step 1: Resolve XHS URL to get video URL
    console.log("Step 1: Resolving XHS URL...");
    const xhsResponse = await fetch(xhsUrl, {
      headers: {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
        "Cookie": Object.entries(DEFAULT_XHS_COOKIES).map(([k, v]) => `${k}=${v}`).join("; "),
      },
      redirect: "follow",
    });

    const xhsHtml = await xhsResponse.text();
    const videoMatch = xhsHtml.match(/https:\/\/sns-video[^"'\s]+\.mp4[^"'\s]*/);
    if (!videoMatch) {
      return c.json({ error: "No video found in XHS URL" }, 400);
    }
    const videoUrl = videoMatch[0].replace(/\\u002F/g, "/");
    console.log("Video URL:", videoUrl);

    // Step 2: Download video and get duration
    console.log("Step 2: Downloading video...");
    const videoResponse = await fetch(videoUrl, {
      headers: { "Referer": "https://www.xiaohongshu.com/" },
    });
    const videoBuffer = await videoResponse.arrayBuffer();
    const videoBase64 = btoa(String.fromCharCode(...new Uint8Array(videoBuffer)));

    // Estimate duration (rough estimate based on file size - 1MB per 10s for typical XHS video)
    const estimatedDuration = Math.max(10, Math.min(60, videoBuffer.byteLength / 100000));
    console.log(`Video size: ${(videoBuffer.byteLength / 1024 / 1024).toFixed(1)}MB, Est duration: ${estimatedDuration}s`);

    // Step 3: Upload to Google and generate script
    console.log("Step 3: Uploading to Google...");
    const uploadStartResponse = await fetch(
      `https://generativelanguage.googleapis.com/upload/v1beta/files?key=${c.env.GOOGLE_API_KEY}`,
      {
        method: "POST",
        headers: {
          "X-Goog-Upload-Protocol": "resumable",
          "X-Goog-Upload-Command": "start",
          "X-Goog-Upload-Header-Content-Length": String(videoBuffer.byteLength),
          "X-Goog-Upload-Header-Content-Type": "video/mp4",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ file: { display_name: "xhs_video.mp4" } }),
      }
    );

    const uploadUrl = uploadStartResponse.headers.get("X-Goog-Upload-URL");
    if (!uploadUrl) {
      return c.json({ error: "Failed to get upload URL" }, 500);
    }

    const uploadResponse = await fetch(uploadUrl, {
      method: "POST",
      headers: {
        "X-Goog-Upload-Command": "upload, finalize",
        "X-Goog-Upload-Offset": "0",
        "Content-Type": "video/mp4",
      },
      body: videoBuffer,
    });

    const uploadResult = await uploadResponse.json() as { file: { name: string; uri: string; state: string } };
    let fileUri = uploadResult.file?.uri;
    let fileState = uploadResult.file?.state;

    // Wait for processing
    while (fileState === "PROCESSING") {
      await new Promise(r => setTimeout(r, 3000));
      const checkResponse = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/${uploadResult.file.name}?key=${c.env.GOOGLE_API_KEY}`
      );
      const checkResult = await checkResponse.json() as { state: string; uri: string };
      fileState = checkResult.state;
      fileUri = checkResult.uri;
    }

    // Step 4: Generate script
    console.log("Step 4: Generating script...");
    const targetChars = Math.round(estimatedDuration * 10);
    const scriptPrompt = `วิเคราะห์วิดีโอนี้และสร้าง script ภาษาไทยสำหรับพากย์เสียง
- วิดีโอยาว ${estimatedDuration.toFixed(0)} วินาที
- TTS พูดได้ประมาณ 10 ตัวอักษร/วินาที
- Script ต้องมีประมาณ ${targetChars} ตัวอักษร

ตอบเป็น JSON: {"thai_script": "ข้อความ", "char_count": จำนวน}`;

    const scriptResponse = await fetch(
      `${gatewayUrl}/v1beta/models/gemini-2.0-flash:generateContent`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-goog-api-key": c.env.GOOGLE_API_KEY,
        },
        body: JSON.stringify({
          contents: [{
            parts: [
              { fileData: { mimeType: "video/mp4", fileUri } },
              { text: scriptPrompt }
            ]
          }],
          generationConfig: { temperature: 0.8, maxOutputTokens: 2048 }
        }),
      }
    );

    const scriptResult = await scriptResponse.json() as { candidates: Array<{ content: { parts: Array<{ text: string }> } }> };
    let scriptText = scriptResult.candidates?.[0]?.content?.parts?.[0]?.text || "";
    scriptText = scriptText.replace(/```json/g, "").replace(/```/g, "").trim();

    let thaiScript = "";
    try {
      thaiScript = JSON.parse(scriptText).thai_script;
    } catch {
      const match = scriptText.match(/"thai_script":\s*"([^"]+)"/);
      thaiScript = match ? match[1] : scriptText;
    }
    console.log("Script:", thaiScript.substring(0, 50) + "...");

    // Step 5: Generate TTS
    console.log("Step 5: Generating TTS...");
    const ttsResponse = await fetch(
      `${gatewayUrl}/v1beta/models/gemini-2.5-flash-preview-tts:generateContent`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-goog-api-key": c.env.GOOGLE_API_KEY,
        },
        body: JSON.stringify({
          contents: [{ parts: [{ text: thaiScript }] }],
          generationConfig: {
            responseModalities: ["AUDIO"],
            speechConfig: {
              voiceConfig: { prebuiltVoiceConfig: { voiceName: voice } }
            }
          }
        }),
      }
    );

    const ttsResult = await ttsResponse.json() as { candidates: Array<{ content: { parts: Array<{ inlineData: { data: string } }> } }> };
    const audioBase64 = ttsResult.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data;

    if (!audioBase64) {
      return c.json({ error: "Failed to generate TTS" }, 500);
    }

    // Step 6: Call merge-api to merge video + audio
    console.log("Step 6: Merging audio with video...");
    const mergeResponse = await fetch(`${MERGE_API_URL}/merge-and-upload`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        videoUrl,
        audioBase64,
        audioSampleRate: 24000,
        fbPageId: c.env.FB_PAGE_ID,
        fbPageToken: c.env.FB_PAGE_TOKEN,
        description: description || thaiScript.substring(0, 100) + "...",
      }),
    });

    const mergeResult = await mergeResponse.json() as { success: boolean; videoId: string; reelUrl: string; error?: string };

    if (!mergeResult.success) {
      return c.json({ error: mergeResult.error || "Merge failed" }, 500);
    }

    return c.json({
      success: true,
      script: thaiScript,
      reelUrl: mergeResult.reelUrl,
      videoId: mergeResult.videoId,
    });

  } catch (error) {
    console.error("Pipeline error:", error);
    return c.json({ error: String(error) }, 500);
  }
});

// Serve static files
app.get("*", async (c) => {
  return c.env.ASSETS.fetch(c.req.raw);
});

export default app;
