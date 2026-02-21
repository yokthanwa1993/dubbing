import { useEffect, useState } from 'react'

const WORKER_URL = 'https://dubbing-worker.yokthanwa1993-bc9.workers.dev'

interface Stats {
  total: number
  completed: number
  processing: number
  failed: number
}

interface Video {
  id: string
  script: string
  duration: number
  originalUrl: string
  createdAt: string
  publicUrl: string
  thumbnailUrl?: string
  shopeeLink?: string
  category?: string
  title?: string
}

interface PostHistory {
  id: number
  page_id: string
  video_id: string
  fb_post_id?: string
  posted_at: string
  status: string
  page_name: string
  page_image: string
}

interface FacebookPage {
  id: string
  name: string
  image_url: string
  access_token?: string
  comment_token?: string
  post_interval_minutes: number
  post_hours?: string  // comma-separated hours like "9,12,18"
  is_active: number
  last_post_at?: string
}

declare global {
  interface Window {
    Telegram?: {
      WebApp: {
        ready: () => void
        expand: () => void
        requestFullscreen: () => void
        disableVerticalSwipes: () => void
        setHeaderColor: (color: string) => void
        setBackgroundColor: (color: string) => void
        setBottomBarColor: (color: string) => void
        initDataUnsafe: {
          user?: { first_name: string; last_name?: string }
        }
      }
    }
  }
}

// Icons
const HomeIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const HomeIconFilled = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12.71 2.29a1 1 0 00-1.42 0l-9 9a1 1 0 001.42 1.42L4 12.41V21a1 1 0 001 1h4a1 1 0 001-1v-4h4v4a1 1 0 001 1h4a1 1 0 001-1v-8.59l.29.3a1 1 0 001.42-1.42l-9-9z" />
  </svg>
)
const VideoIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const VideoIconFilled = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
    <path d="M4 6a2 2 0 012-2h8a2 2 0 012 2v8a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 14l5.293 2.646A1 1 0 0021 15.75V8.25a1 1 0 00-1.707-.896L14 10v4z" />
  </svg>
)
const ProcessIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
  </svg>
)
const ProcessIconFilled = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
    <path fillRule="evenodd" d="M4.755 10.059a7.5 7.5 0 0112.548-3.364l1.903 1.903h-3.183a.75.75 0 100 1.5h4.992a.75.75 0 00.75-.75V4.356a.75.75 0 00-1.5 0v3.18l-1.9-1.9A9 9 0 003.306 9.67a.75.75 0 101.45.388zm15.408 3.352a.75.75 0 00-.919.53 7.5 7.5 0 01-12.548 3.364l-1.902-1.903h3.183a.75.75 0 000-1.5H2.984a.75.75 0 00-.75.75v4.992a.75.75 0 001.5 0v-3.18l1.9 1.9a9 9 0 0015.059-4.035.75.75 0 00-.53-.918z" clipRule="evenodd" />
  </svg>
)

const ListIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const ListIconFilled = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
    <path fillRule="evenodd" d="M3 5.25a.75.75 0 01.75-.75h16.5a.75.75 0 010 1.5H3.75A.75.75 0 013 5.25zm0 4.5A.75.75 0 013.75 9h16.5a.75.75 0 010 1.5H3.75A.75.75 0 013 9.75zm0 4.5a.75.75 0 01.75-.75h16.5a.75.75 0 010 1.5H3.75a.75.75 0 01-.75-.75zm0 4.5a.75.75 0 01.75-.75h16.5a.75.75 0 010 1.5H3.75a.75.75 0 01-.75-.75z" clipRule="evenodd" />
  </svg>
)
const PagesIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const PagesIconFilled = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
    <path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" />
  </svg>
)
const SettingsIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const SettingsIconFilled = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
    <path fillRule="evenodd" d="M11.078 2.25c-.917 0-1.699.663-1.85 1.567L9.05 4.889c-.02.12-.115.26-.297.348a7.493 7.493 0 00-.986.57c-.166.115-.334.126-.45.083L6.3 5.508a1.875 1.875 0 00-2.282.819l-.922 1.597a1.875 1.875 0 00.432 2.385l.84.692c.095.078.17.229.154.43a7.598 7.598 0 000 1.139c.015.2-.059.352-.153.43l-.841.692a1.875 1.875 0 00-.432 2.385l.922 1.597a1.875 1.875 0 002.282.818l1.019-.382c.115-.043.283-.031.45.082.312.214.641.405.985.57.182.088.277.228.297.35l.178 1.071c.151.904.933 1.567 1.85 1.567h1.844c.916 0 1.699-.663 1.85-1.567l.178-1.072c.02-.12.114-.26.297-.349.344-.165.673-.356.985-.57.167-.114.335-.125.45-.082l1.02.382a1.875 1.875 0 002.28-.819l.923-1.597a1.875 1.875 0 00-.432-2.385l-.84-.692c-.095-.078-.17-.229-.154-.43a7.614 7.614 0 000-1.139c-.016-.2.059-.352.153-.43l.84-.692c.708-.582.891-1.59.433-2.385l-.922-1.597a1.875 1.875 0 00-2.282-.818l-1.02.382c-.114.043-.282.031-.449-.083a7.49 7.49 0 00-.985-.57c-.183-.087-.277-.227-.297-.348l-.179-1.072a1.875 1.875 0 00-1.85-1.567h-1.843zM12 15.75a3.75 3.75 0 100-7.5 3.75 3.75 0 000 7.5z" clipRule="evenodd" />
  </svg>
)
const BackIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M15 19l-7-7 7-7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const CloseIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

// Thumbnail with localStorage cache
function Thumb({ id, url, fallback }: { id: string; url?: string; fallback: string }) {
  const [src, setSrc] = useState(() => {
    try { return localStorage.getItem(`t_${id}`) || '' } catch { return '' }
  })

  useEffect(() => {
    if (src) return // already cached
    if (!url) return
    fetch(url).then(r => r.blob()).then(blob => {
      const reader = new FileReader()
      reader.onloadend = () => {
        const b64 = reader.result as string
        setSrc(b64)
        try { localStorage.setItem(`t_${id}`, b64) } catch { }
      }
      reader.readAsDataURL(blob)
    }).catch(() => { })
  }, [id, url, src])

  if (src) return <img src={src} className="w-full h-full object-cover" alt="" />
  if (url) return <img src={url} className="w-full h-full object-cover" loading="lazy" alt="" />
  return <video src={`${fallback}#t=0.1`} className="w-full h-full object-cover" preload="metadata" muted playsInline />
}

// Video card component
function VideoCard({ video, formatDuration, onDelete, onUpdate }: { video: Video; formatDuration: (s: number) => string; onDelete: (id: string) => void; onUpdate: (id: string, fields: Partial<Video>) => void }) {
  const [expanded, setExpanded] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [shopeeInput, setShopeeInput] = useState('')
  const [savingShopee, setSavingShopee] = useState(false)
  const [localShopee, setLocalShopee] = useState(video.shopeeLink || '')
  const [localCats, setLocalCats] = useState<string[]>([])
  const [fetchedCats, setFetchedCats] = useState<string[]>([])
  const [editingTitle, setEditingTitle] = useState(false)
  const [localTitle, setLocalTitle] = useState(video.title || '')
  const [savingTitle, setSavingTitle] = useState(false)

  useEffect(() => {
    if (expanded) {
      setLocalCats(video.category ? video.category.split(',').filter(Boolean) : [])
      fetch(`${WORKER_URL}/api/categories`).then(r => r.json()).then(d => setFetchedCats(d.categories || [])).catch(() => { })
    }
  }, [expanded])

  const toggleCategory = async (cat: string) => {
    const next = localCats.includes(cat) ? localCats.filter(c => c !== cat) : [...localCats, cat]
    setLocalCats(next)
    const newCat = next.join(',')
    onUpdate(video.id, { category: newCat })
    await fetch(`${WORKER_URL}/api/gallery/${video.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category: newCat })
    }).catch(() => { })
  }

  const handleSaveShopee = async () => {
    if (!shopeeInput.trim()) return
    setSavingShopee(true)
    try {
      const resp = await fetch(`${WORKER_URL}/api/gallery/${video.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shopeeLink: shopeeInput.trim() })
      })
      if (resp.ok) {
        video.shopeeLink = shopeeInput.trim()
        setLocalShopee(shopeeInput.trim())
        setShopeeInput('')
      }
    } catch (e) {
      console.error('Save failed:', e)
    } finally {
      setSavingShopee(false)
    }
  }

  const handleSaveTitle = async (newTitle: string) => {
    setSavingTitle(true)
    try {
      const resp = await fetch(`${WORKER_URL}/api/gallery/${video.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle })
      })
      if (resp.ok) {
        video.title = newTitle
        onUpdate(video.id, { title: newTitle })
      }
    } catch (e) {
      console.error('Save title failed:', e)
    } finally {
      setSavingTitle(false)
      setEditingTitle(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm('ยืนยันลบวีดีโอนี้?')) return
    setDeleting(true)
    try {
      const resp = await fetch(`${WORKER_URL}/api/gallery/${video.id}`, { method: 'DELETE' })
      if (resp.ok) {
        try { localStorage.removeItem(`t_${video.id}`) } catch { }
        onDelete(video.id)
        setExpanded(false)
      }
    } catch (e) {
      console.error('Delete failed:', e)
    } finally {
      setDeleting(false)
    }
  }

  if (expanded) {
    return (
      <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-6">
        <div className="relative w-[85%] max-w-sm">
          {/* Close button */}
          <button
            onClick={() => setExpanded(false)}
            className="mx-auto mb-3 w-11 h-11 bg-white/20 rounded-full flex items-center justify-center backdrop-blur-sm"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          {/* Editable Title */}
          <div className="mb-2">
            {editingTitle ? (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={localTitle}
                  onChange={(e) => setLocalTitle(e.target.value)}
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleSaveTitle(localTitle)
                    if (e.key === 'Escape') { setEditingTitle(false); setLocalTitle(video.title || '') }
                  }}
                  className="flex-1 bg-white/10 text-white text-sm px-3 py-2 rounded-xl outline-none border border-white/20 focus:border-blue-400"
                  placeholder="ใส่แคปชั่น..."
                />
                <button
                  onClick={() => handleSaveTitle(localTitle)}
                  disabled={savingTitle}
                  className="shrink-0 bg-blue-500 text-white text-xs font-bold px-3 py-2 rounded-xl active:scale-95 transition-all disabled:opacity-50"
                >
                  {savingTitle ? '...' : 'OK'}
                </button>
              </div>
            ) : (
              <button
                onClick={() => setEditingTitle(true)}
                className="w-full text-left flex items-center gap-2 group"
              >
                <p className={`flex-1 text-sm ${localTitle ? 'text-white' : 'text-white/40'} line-clamp-2`}>
                  {localTitle || 'แตะเพื่อเพิ่มแคปชั่น...'}
                </p>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" className="shrink-0 opacity-40 group-active:opacity-80">
                  <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </div>
          <div className="aspect-[3/4] rounded-2xl overflow-hidden">
            <video
              src={video.publicUrl}
              className="w-full h-full object-cover"
              controls
              autoPlay
              playsInline
            />
          </div>
          {/* Category chips */}
          <div className="flex gap-1.5 mt-2 flex-wrap">
            {fetchedCats.map(cat => (
              <button
                key={cat}
                onClick={() => toggleCategory(cat)}
                className={`px-2.5 py-1 rounded-full text-xs font-bold transition-all active:scale-95 ${localCats.includes(cat) ? 'bg-blue-500 text-white' : 'bg-white/30 text-white'}`}
              >
                #{cat}
              </button>
            ))}
          </div>
          {/* Shopee Link */}
          {savingShopee ? (
            <div className="flex items-center justify-center gap-2 mt-3 bg-white/10 rounded-xl px-3 py-2.5">
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              <span className="text-white/60 text-sm">กำลังบันทึก...</span>
            </div>
          ) : localShopee ? (
            <div className="flex items-center gap-2 mt-3 bg-white/10 rounded-xl px-3 py-2.5">
              <span className="text-white text-sm truncate flex-1">{localShopee}</span>
              {/* แก้ไข */}
              <button
                onClick={() => { setShopeeInput(''); setLocalShopee('') }}
                className="shrink-0 bg-white/20 rounded-lg p-2 active:scale-90 transition-transform"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
                  <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {/* เปิดลิงก์ */}
              <a
                href={localShopee}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 bg-white/20 rounded-lg p-2 active:scale-90 transition-transform"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
                  <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M15 3h6v6" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M10 14L21 3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </a>
              {/* คัดลอก */}
              <button
                onClick={() => navigator.clipboard.writeText(localShopee)}
                className="shrink-0 bg-white/20 rounded-lg p-2 active:scale-90 transition-transform"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2 mt-3">
              <div
                contentEditable
                suppressContentEditableWarning
                onPaste={(e) => {
                  e.preventDefault()
                  const text = e.clipboardData.getData('text/plain').trim()
                  if (text) setShopeeInput(text)
                }}
                onBeforeInput={(e) => e.preventDefault()}
                onDrop={(e) => e.preventDefault()}
                className="flex-1 bg-white/10 text-white text-sm px-3 py-2.5 rounded-xl outline-none min-h-[40px] break-all"
                style={{ WebkitUserSelect: 'text', userSelect: 'text' }}
                inputMode="none"
              >
                {shopeeInput && <span className="text-white">{shopeeInput}</span>}
              </div>
              <button
                onClick={handleSaveShopee}
                disabled={!shopeeInput.trim()}
                className="shrink-0 bg-black text-white text-sm font-bold px-4 py-2.5 rounded-xl active:scale-95 transition-all disabled:opacity-50"
              >
                บันทึก
              </button>
            </div>
          )}
          {/* Delete button */}
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="w-full mt-2 py-3 rounded-xl bg-red-500 text-white text-sm font-bold flex items-center justify-center gap-2 active:scale-95 transition-all"
          >
            {deleting ? (
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : (
              <>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
                  <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                ลบวีดีโอ
              </>
            )}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div
      className="relative aspect-[9/16] rounded-2xl overflow-hidden cursor-pointer bg-gray-100 shadow-sm active:scale-95 transition-transform duration-200"
      onClick={() => setExpanded(true)}
    >
      <Thumb id={video.id} url={video.thumbnailUrl} fallback={video.publicUrl} />
      {video.shopeeLink && (
        <div className="absolute bottom-2 left-2 bg-orange-500 text-white w-6 h-6 rounded-full flex items-center justify-center shadow-lg border border-white/20">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      )}

      <div className="absolute bottom-2 right-2 bg-black/60 backdrop-blur-md text-white text-[10px] px-2 py-0.5 rounded-full font-medium">
        {formatDuration(video.duration)}
      </div>
    </div>
  )
}

// Add Page Token Popup
function AddPagePopup({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [token, setToken] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ imported: number; updated: number } | null>(null)

  const handleImport = async () => {
    if (!token.trim()) {
      setError('กรุณาใส่ Token')
      return
    }

    setLoading(true)
    setError('')

    try {
      const resp = await fetch(`${WORKER_URL}/api/pages/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_token: token.trim() })
      })

      const data = await resp.json()

      if (!resp.ok) {
        setError(data.details || data.error || 'เกิดข้อผิดพลาด')
        return
      }

      setResult({ imported: data.imported, updated: data.updated })
      setTimeout(() => {
        onSuccess()
        onClose()
      }, 1500)
    } catch (e) {
      setError('ไม่สามารถเชื่อมต่อ Server ได้')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div
        className="bg-white rounded-3xl w-full max-w-md p-6 space-y-4"
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold text-gray-900">เพิ่ม Facebook Pages</h2>
          <button onClick={onClose} className="p-2 text-gray-400 hover:text-gray-600">
            <CloseIcon />
          </button>
        </div>

        {/* Instructions */}
        <p className="text-sm text-gray-500">
          ใส่ User Access Token จาก Facebook เพื่อดึงข้อมูล Pages ที่คุณเป็นแอดมิน
        </p>

        {/* Token Input — paste only, no keyboard */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">User Access Token</label>
          <div
            contentEditable
            suppressContentEditableWarning
            onPaste={(e) => {
              e.preventDefault()
              const text = e.clipboardData.getData('text/plain').trim()
              if (text) setToken(text)
            }}
            onBeforeInput={(e) => e.preventDefault()}
            onDrop={(e) => e.preventDefault()}
            className="w-full p-3 border border-gray-200 rounded-xl text-sm min-h-[80px] break-all focus:outline-none focus:ring-2 focus:ring-blue-500"
            style={{ WebkitUserSelect: 'text', userSelect: 'text' }}
            inputMode="none"
          >
            {token && <span className="text-gray-900">{token}</span>}
          </div>
          {token && (
            <button onClick={() => setToken('')} className="text-xs text-red-400 mt-1 ml-1">ล้าง</button>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-50 text-red-600 text-sm p-3 rounded-xl">
            {error}
          </div>
        )}

        {/* Success */}
        {result && (
          <div className="bg-green-50 text-green-600 text-sm p-3 rounded-xl">
            ✅ นำเข้าสำเร็จ! เพิ่มใหม่ {result.imported} เพจ, อัพเดท {result.updated} เพจ
          </div>
        )}

        {/* Submit Button */}
        <button
          onClick={handleImport}
          disabled={loading || !!result}
          className={`w-full py-3 rounded-xl font-bold text-white transition-all ${loading || result ? 'bg-gray-400' : 'bg-blue-600 active:scale-95'
            }`}
        >
          {loading ? 'กำลังดึงข้อมูล...' : result ? 'สำเร็จ!' : 'นำเข้า Pages'}
        </button>
      </div>
    </div>
  )
}

// Page Detail Component
function PageDetail({ page, onBack, onSave }: { page: FacebookPage; onBack: () => void; onSave: (page: FacebookPage) => void }) {
  // Parse post_hours: supports "2:31,9:47" (new) and "2,9" (legacy) formats
  const parsePostHours = (raw: string): Record<number, number> => {
    const result: Record<number, number> = {}
    if (!raw) return result
    for (const part of raw.split(',')) {
      if (part.includes(':')) {
        const [h, m] = part.split(':').map(Number)
        if (h >= 1 && h <= 24) result[h] = m
      } else {
        const h = Number(part)
        if (h >= 1 && h <= 24) result[h] = Math.floor(Math.random() * 59) + 1
      }
    }
    return result
  }

  const [hourMinutes, setHourMinutes] = useState<Record<number, number>>(() => parsePostHours(page.post_hours || ''))
  const selectedHours = Object.keys(hourMinutes).map(Number).sort((a, b) => a - b)
  const [isActive, setIsActive] = useState(page.is_active === 1)
  const [accessToken, setAccessToken] = useState(page.access_token || '')
  const [commentToken, setCommentToken] = useState(page.comment_token || '')
  const [saving, setSaving] = useState(false)
  const [editingToken, setEditingToken] = useState<'access' | 'comment' | null>(null)
  const [editingTokenValue, setEditingTokenValue] = useState('')

  // Hours 1-24 for display
  const hourOptions = Array.from({ length: 24 }, (_, i) => i + 1)

  const toggleHour = (hour: number) => {
    const newMap = { ...hourMinutes }
    if (hour in newMap) {
      delete newMap[hour]
    } else {
      newMap[hour] = Math.floor(Math.random() * 59) + 1
    }
    setHourMinutes(newMap)
  }

  const postHoursString = selectedHours.map(h => `${h}:${hourMinutes[h].toString().padStart(2, '0')}`).join(',')

  const handleSave = async () => {
    setSaving(true)
    try {
      const resp = await fetch(`${WORKER_URL}/api/pages/${page.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          post_hours: postHoursString,
          is_active: isActive,
          access_token: accessToken || undefined,
          comment_token: commentToken || undefined
        })
      })
      if (resp.ok) {
        onSave({ ...page, post_hours: postHoursString, is_active: isActive ? 1 : 0, access_token: accessToken, comment_token: commentToken })
        onBack()
      }
    } catch (e) {
      console.error('Save failed:', e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="h-full flex flex-col px-5">
      {/* Back button */}
      <div className="flex items-center mb-4">
        <button onClick={onBack} className="p-1 text-gray-400">
          <BackIcon />
        </button>
      </div>
      {/* Scrollable content area */}
      <div className="flex-1 overflow-y-auto min-h-0">

        {/* Page Logo */}
        <div className="flex flex-col items-center mb-4">
          <img
            src={page.image_url || 'https://via.placeholder.com/100'}
            alt={page.name}
            className="w-24 h-24 rounded-full object-cover shadow-sm"
          />
        </div>

        {/* Auto Post toggle */}
        <div className="bg-white border border-gray-100 rounded-2xl p-4 flex items-center justify-between mb-3">
          <p className="font-bold text-gray-900">Auto Post</p>
          <button
            onClick={() => setIsActive(!isActive)}
            className={`w-12 h-7 rounded-full relative transition-colors ${isActive ? 'bg-green-500' : 'bg-gray-300'}`}
          >
            <div className={`w-5 h-5 bg-white rounded-full absolute top-1 transition-all shadow-sm ${isActive ? 'right-1' : 'left-1'}`}></div>
          </button>
        </div>

        {/* Tokens */}
        <div className="bg-white border border-gray-100 rounded-2xl mb-3 overflow-hidden">
          <button
            onClick={() => { setEditingToken('access'); setEditingTokenValue(accessToken) }}
            className="w-full flex items-center justify-between p-4 active:bg-gray-50 transition-colors"
          >
            <div className="text-left">
              <p className="text-sm font-bold text-gray-900">Access Token (โพสต์)</p>
              <p className="text-xs text-gray-400 mt-0.5 font-mono truncate max-w-[250px]">{accessToken ? `${accessToken.slice(0, 20)}...` : 'ยังไม่ได้ตั้งค่า'}</p>
            </div>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" strokeWidth="2"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>
          <div className="h-px bg-gray-100 mx-4" />
          <button
            onClick={() => { setEditingToken('comment'); setEditingTokenValue(commentToken) }}
            className="w-full flex items-center justify-between p-4 active:bg-gray-50 transition-colors"
          >
            <div className="text-left">
              <p className="text-sm font-bold text-gray-900">Comment Token (คอมเม้นท์)</p>
              <p className="text-xs text-gray-400 mt-0.5 font-mono truncate max-w-[250px]">{commentToken ? `${commentToken.slice(0, 20)}...` : 'ใช้ Access Token แทน'}</p>
            </div>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" strokeWidth="2"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>
        </div>

        {/* Token Edit Popup */}
        {editingToken && (
          <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center px-6" onClick={() => setEditingToken(null)}>
            <div className="bg-white rounded-2xl w-full max-w-md p-5 space-y-4" onClick={(e) => e.stopPropagation()}>
              <h3 className="font-bold text-gray-900 text-base text-center">
                {editingToken === 'access' ? 'Access Token (โพสต์)' : 'Comment Token (คอมเม้นท์)'}
              </h3>
              <textarea
                ref={(el) => { if (el) { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px' } }}
                value={editingTokenValue}
                onChange={(e) => { setEditingTokenValue(e.target.value); e.target.style.height = 'auto'; e.target.style.height = e.target.scrollHeight + 'px' }}
                placeholder={editingToken === 'access' ? 'วาง Page Access Token ที่นี่...' : 'วาง Comment Token ที่นี่ (เว้นว่างได้)'}
                rows={2}
                className="w-full bg-gray-50 border border-gray-200 rounded-xl px-4 py-3 text-sm font-mono outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all resize-none overflow-hidden"
              />
              <div className="flex gap-3">
                <button
                  onClick={() => setEditingToken(null)}
                  className="flex-1 py-3 rounded-xl font-bold text-sm border border-gray-200 text-gray-600 active:scale-95 transition-all"
                >
                  ยกเลิก
                </button>
                <button
                  onClick={() => {
                    if (editingToken === 'access') setAccessToken(editingTokenValue)
                    else setCommentToken(editingTokenValue)
                    setEditingToken(null)
                  }}
                  className="flex-1 py-3 rounded-xl font-bold text-sm bg-blue-600 text-white active:scale-95 transition-all"
                >
                  บันทึก
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Post Hours - Multi select */}
        <div className="bg-white border border-gray-100 rounded-2xl p-4 mb-3">
          <p className="font-bold text-gray-900 text-sm mb-1">โพสต์เวลาไหนบ้าง</p>
          <p className="text-xs text-gray-400 mb-3">เลือกได้หลายเวลา (กดติ๊ก)</p>
          <div className="grid grid-cols-6 gap-2">
            {hourOptions.map((hour) => (
              <button
                key={hour}
                onClick={() => toggleHour(hour)}
                className={`py-2 rounded-lg text-sm font-medium transition-all ${selectedHours.includes(hour)
                  ? 'bg-blue-500 text-white'
                  : 'bg-gray-100 text-gray-600'
                  }`}
              >
                {hour.toString().padStart(2, '0')}
              </button>
            ))}
          </div>
          {selectedHours.length > 0 && (
            <p className="text-xs text-blue-500 mt-3">จะโพสต์เวลา: {selectedHours.map(h => `${h.toString().padStart(2, '0')}:${hourMinutes[h].toString().padStart(2, '0')} น.`).join(', ')}</p>
          )}
        </div>

      </div>{/* End scrollable content */}

      {/* Bottom buttons */}
      <div className="pb-2 flex gap-3">
        <button
          onClick={onBack}
          className="py-4 px-5 rounded-2xl font-bold text-base border border-gray-200 text-gray-600 active:scale-95 transition-all"
        >
          <BackIcon />
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          className={`flex-1 py-4 rounded-2xl font-bold text-base transition-all ${saving ? 'bg-gray-400 text-white' : 'bg-blue-600 text-white active:scale-95'
            }`}
        >
          {saving ? 'กำลังบันทึก...' : 'Save'}
        </button>
      </div>
    </div>
  )
}

function ProcessingCard({ video, onCancel }: { video: any, onCancel: (id: string, isQueued: boolean) => void }) {
  const displayProgress = video.status === 'queued' ? 0 : Math.max(5, Math.min(100, Math.floor(((video.step || 0) / 5) * 100)));

  return (
    <div className="bg-white border border-gray-100 rounded-2xl p-4 shadow-sm relative flex flex-col gap-3">
      {/* Top Row: ID + Cancel form */}
      <div className="flex justify-between items-start">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${video.status === 'failed' ? 'bg-red-50 text-red-500' : video.status === 'queued' ? 'bg-amber-50 text-amber-500' : 'bg-blue-50 text-blue-500'}`}>
            {video.status === 'failed' ? '❌' : video.status === 'queued' ? '⏳' : (
              <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent animate-spin rounded-full" />
            )}
          </div>
          <div className="flex flex-col">
            <p className="font-extrabold text-gray-900 text-sm">ID: {video.id}</p>
            <p className="text-[10px] text-gray-400 font-medium">เริ่มเมื่อ {new Date(video.createdAt).toLocaleTimeString('th-TH')}</p>
          </div>
        </div>
        <button
          onClick={() => onCancel(video.id, video.status === 'queued')}
          title={video.status === 'failed' ? 'ลบประวัติ' : 'ยกเลิก'}
          className={`p-2 rounded-full transition-colors ${video.status === 'failed' ? 'bg-red-50 text-red-500 hover:bg-red-100' : 'bg-gray-50 text-gray-400 hover:bg-red-50 hover:text-red-500'}`}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6L6 18M6 6l12 12" /></svg>
        </button>
      </div>

      {/* Middle Row: Status Text + Link + % */}
      <div className="flex justify-between items-end mt-1">
        <div className="flex flex-col gap-1.5 flex-1 pr-4 min-w-0">
          <div className="flex items-center gap-1.5">
            {video.status === 'failed' ? (
              <span className="text-xs bg-red-50 text-red-600 px-2 py-0.5 rounded-md font-bold shrink-0 truncate">{video.error || 'ล้มเหลว'}</span>
            ) : video.status === 'queued' ? (
              <span className="text-xs bg-amber-50 text-amber-600 px-2 py-0.5 rounded-md font-bold shrink-0">กำลังรอคิว...</span>
            ) : (
              <span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded-md font-bold shrink-0 truncate break-all line-clamp-1">{video.stepName || 'กำลังประมวลผล...'}</span>
            )}
          </div>
          <p className="text-[10px] text-gray-500 flex items-center gap-1.5 truncate">
            <span className="w-4 h-4 rounded-full bg-gray-50 flex items-center justify-center shrink-0"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" strokeLinecap="round" strokeLinejoin="round" /><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
            <span className="truncate">{video.shopeeLink || 'ไม่มีลิงก์ Shopee'}</span>
          </p>
        </div>

        {video.status !== 'failed' && (
          <div className="text-right shrink-0">
            <span className="text-lg font-black text-blue-600">{video.status === 'queued' ? '0' : displayProgress}%</span>
          </div>
        )}
      </div>

      {/* Bottom Row: Progress Bar */}
      {video.status !== 'failed' && (
        <div className="w-full bg-gray-100 rounded-full h-2.5 overflow-hidden relative">
          <div
            className={`h-2.5 rounded-full transition-all duration-300 ease-linear ${video.status === 'queued' ? 'bg-amber-400' : 'bg-gradient-to-r from-blue-500 to-indigo-500'}`}
            style={{ width: `${Math.max(2, displayProgress)}%` }}
          />
        </div>
      )}
    </div>
  );
}

function App() {
  const [stats, setStats] = useState<Stats>({ total: 0, completed: 0, processing: 0, failed: 0 })
  const [postHistory, setPostHistory] = useState<PostHistory[]>([])
  const [deletingLogId, setDeletingLogId] = useState<number | null>(null)
  const [videos, _setVideos] = useState<Video[]>(() => {
    try { return JSON.parse(localStorage.getItem('gallery_cache') || '[]') } catch { return [] }
  })
  const setVideos = (v: Video[]) => {
    _setVideos(v)
    try { localStorage.setItem('gallery_cache', JSON.stringify(v)) } catch { }
  }
  const [usedVideos, _setUsedVideos] = useState<Video[]>(() => {
    try { return JSON.parse(localStorage.getItem('used_cache') || '[]') } catch { return [] }
  })
  const setUsedVideos = (v: Video[]) => {
    _setUsedVideos(v)
    try { localStorage.setItem('used_cache', JSON.stringify(v)) } catch { }
  }
  const [processingVideos, setProcessingVideos] = useState<Video[]>([])
  const [loading, setLoading] = useState(() => {
    try { return !localStorage.getItem('gallery_cache') } catch { return true }
  })
  // Get today's date in YYYY-MM-DD format for Thailand timezone
  const getTodayString = () => {
    const now = new Date()
    const thaiTime = new Date(now.getTime() + 7 * 60 * 60 * 1000)
    return thaiTime.toISOString().split('T')[0]
  }


  const [categoryFilter, setCategoryFilter] = useState<string>('unused')
  const [logDateFilter, setLogDateFilter] = useState<string>(getTodayString())
  const [categories, _setCategories] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('categories_cache') || '[]') } catch { return [] }
  })
  const setCategories = (c: string[]) => {
    _setCategories(c)
    try { localStorage.setItem('categories_cache', JSON.stringify(c)) } catch { }
  }
  const [newCat, setNewCat] = useState('')

  // Read initial tab from URL param
  const getInitialTab = (): 'home' | 'processing' | 'gallery' | 'logs' | 'pages' | 'settings' => {
    const params = new URLSearchParams(window.location.search)
    const tabParam = params.get('tab')
    if (tabParam === 'processing' || tabParam === 'gallery' || tabParam === 'logs' || tabParam === 'pages' || tabParam === 'settings') {
      return tabParam as 'processing' | 'gallery' | 'logs' | 'pages' | 'settings'
    }
    return 'home'
  }

  const [tab, setTab] = useState<'home' | 'processing' | 'gallery' | 'logs' | 'pages' | 'settings'>(getInitialTab())
  const [pages, setPages] = useState<FacebookPage[]>([])
  const [selectedPage, setSelectedPage] = useState<FacebookPage | null>(null)
  const [showAddPagePopup, setShowAddPagePopup] = useState(false)
  const [pagesLoading, setPagesLoading] = useState(false)
  const [deletePageId, setDeletePageId] = useState<string | null>(null)
  const [deletingPageId, setDeletingPageId] = useState<string | null>(null)

  const tg = window.Telegram?.WebApp
  const user = tg?.initDataUnsafe?.user

  useEffect(() => {
    if (tg) {
      tg.ready()
      tg.expand()
      try {
        tg.requestFullscreen()
        tg.disableVerticalSwipes()
        tg.setHeaderColor('#ffffff')
        tg.setBackgroundColor('#ffffff')
        tg.setBottomBarColor('#ffffff')
      } catch (e) {
        console.log('Setup error:', e)
      }
    }
    loadData()
    loadPages()
    loadCategories()
    const interval = setInterval(loadData, 10000)
    return () => clearInterval(interval)
  }, [])

  async function loadData() {
    try {
      try {
        const statsResp = await fetch(`${WORKER_URL}/api/stats`)
        if (statsResp.ok) setStats(await statsResp.json())
      } catch { }

      try {
        const histResp = await fetch(`${WORKER_URL}/api/post-history`)
        if (histResp.ok) {
          const data = await histResp.json()
          setPostHistory(data.history || [])
        }
      } catch { }

      try {
        const galleryResp = await fetch(`${WORKER_URL}/api/gallery`)
        if (galleryResp.ok) {
          const data = await galleryResp.json()
          setVideos(data.videos || [])
        }
      } catch { }

      try {
        const usedResp = await fetch(`${WORKER_URL}/api/gallery/used`)
        if (usedResp.ok) {
          const data = await usedResp.json()
          setUsedVideos(data.videos || [])
        }
      } catch { }

      try {
        const [procResp, queueResp] = await Promise.all([
          fetch(`${WORKER_URL}/api/processing`),
          fetch(`${WORKER_URL}/api/queue`),
        ])
        const procData = procResp.ok ? await procResp.json() : { videos: [] }
        const queueData = queueResp.ok ? await queueResp.json() : { queue: [] }
        setProcessingVideos([...(procData.videos || []), ...(queueData.queue || [])])
      } catch { }
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  async function loadPages() {
    setPagesLoading(true)
    try {
      const resp = await fetch(`${WORKER_URL}/api/pages`)
      if (resp.ok) {
        const data = await resp.json()
        setPages(data.pages || [])
      }
    } catch (e) {
      console.error('Failed to load pages:', e)
    } finally {
      setPagesLoading(false)
    }
  }

  async function loadCategories() {
    try {
      const resp = await fetch(`${WORKER_URL}/api/categories`)
      if (resp.ok) {
        const data = await resp.json()
        setCategories(data.categories || [])
      }
    } catch { }
  }

  async function saveCategories(cats: string[]) {
    setCategories(cats)
    await fetch(`${WORKER_URL}/api/categories`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ categories: cats })
    }).catch(() => { })
  }

  function formatDuration(seconds: number) {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const handleSavePage = (updatedPage: FacebookPage) => {
    setPages(pages.map(p => p.id === updatedPage.id ? updatedPage : p))
  }

  const handleDeletePage = async (pageId: string) => {
    setDeletingPageId(pageId)
    try {
      const resp = await fetch(`${WORKER_URL}/api/pages/${pageId}`, { method: 'DELETE' })
      if (resp.ok) {
        setPages(pages.filter(p => p.id !== pageId))
      }
    } catch (e) {
      console.error('Delete failed:', e)
    } finally {
      setDeletingPageId(null)
      setDeletePageId(null)
    }
  }

  const handleCancelJob = async (id: string, isQueued: boolean) => {
    try {
      const endpoint = isQueued ? 'queue' : 'processing'
      await fetch(`${WORKER_URL}/api/${endpoint}/${id}`, { method: 'DELETE' })
      setProcessingVideos(prev => prev.filter(v => v.id !== id))
    } catch { }
  }

  // If viewing a specific page detail
  if (selectedPage) {
    return (
      <div className="h-screen bg-white flex flex-col font-['Sukhumvit_Set','Kanit',sans-serif] overflow-hidden fixed inset-0">
        <div className="flex-1 pt-[52px] pb-6 flex flex-col overflow-hidden">
          <PageDetail
            page={selectedPage}
            onBack={() => setSelectedPage(null)}
            onSave={handleSavePage}
          />
        </div>
      </div>
    )
  }

  return (
    <div className={`h-screen bg-white flex flex-col font-['Sukhumvit_Set','Kanit',sans-serif] ${tab === 'home' ? 'fixed inset-0 overflow-hidden' : ''}`}>
      {/* Add Page Popup */}
      {showAddPagePopup && (
        <AddPagePopup
          onClose={() => setShowAddPagePopup(false)}
          onSuccess={loadPages}
        />
      )}

      {/* Top Nav — fixed */}
      <div className="fixed top-0 left-0 right-0 bg-white/90 backdrop-blur-lg border-b border-gray-100 z-30 pt-[52px] px-5">
        <h1 className="text-2xl font-extrabold text-gray-900 text-center pb-3">
          {tab === 'home' ? 'Dashboard' : tab === 'processing' ? 'Processing' : tab === 'gallery' ? 'Gallery' : tab === 'logs' ? 'Activity Logs' : tab === 'pages' ? 'Pages' : 'Settings'}
        </h1>
        {tab === 'gallery' && (() => {
          const usedIds = new Set(usedVideos.map(v => v.id))
          const videosToShow = [...videos.filter(v => !usedIds.has(v.id)), ...usedVideos]
          if (videosToShow.length === 0) return null
          const unUsedCount = videos.filter((v: Video) => !usedIds.has(v.id)).length
          const usedCount = usedVideos.length
          return (
            <div className="flex bg-gray-100 p-1 mt-1 mb-2 rounded-xl">
              <button
                onClick={() => setCategoryFilter('unused')}
                className={`flex-1 py-2 text-sm font-bold rounded-lg transition-all ${categoryFilter === 'unused' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
              >
                ยังไม่ใช้ ({unUsedCount})
              </button>
              <button
                onClick={() => setCategoryFilter('used')}
                className={`flex-1 py-2 text-sm font-bold rounded-lg transition-all ${categoryFilter === 'used' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
              >
                ใช้แล้ว ({usedCount})
              </button>
            </div>
          )
        })()}
      </div>

      {/* Main Content */}
      <div className={`flex-1 ${tab === 'gallery' && (() => { const ids = new Set(usedVideos.map(v => v.id)); return [...videos.filter(v => !ids.has(v.id)), ...usedVideos].length > 0 })() ? 'pt-[164px]' : 'pt-[104px]'} pb-24 [&::-webkit-scrollbar]:hidden ${tab === 'home' ? 'overflow-hidden' : 'overflow-y-auto'}`}>

        {tab === 'home' && (
          <div className="px-5 h-full flex flex-col">
            {/* Quick Stats */}
            <div className="grid grid-cols-2 gap-3 mb-4">
              <div className="bg-blue-50 p-4 rounded-2xl border border-blue-100">
                <p className="text-blue-600 font-medium text-xs">Total Dubbed</p>
                <p className="text-2xl font-bold text-gray-900 mt-1">{stats.total || '124'}</p>
              </div>
              <div className="bg-green-50 p-4 rounded-2xl border border-green-100">
                <p className="text-green-600 font-medium text-xs">Success Rate</p>
                <p className="text-2xl font-bold text-gray-900 mt-1">98%</p>
              </div>
            </div>

            {/* Credit Balance Card */}
            <div className="bg-gray-900 text-white p-5 rounded-2xl relative overflow-hidden mb-4">
              <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full blur-3xl -mr-10 -mt-10"></div>
              <div className="relative z-10">
                <p className="text-white/60 font-medium text-sm mb-1">Available Credits</p>
                <div className="flex items-baseline gap-2">
                  <span className="text-3xl font-bold">2,450</span>
                  <span className="text-white/60 text-sm">pts</span>
                </div>
                <div className="mt-4 flex gap-3">
                  <button className="flex-1 bg-white/20 py-2 rounded-xl text-sm font-medium">Top Up</button>
                  <button className="flex-1 bg-white text-gray-900 py-2 rounded-xl text-sm font-bold">History</button>
                </div>
              </div>
            </div>

            {/* Weekly Activity */}
            <div className="bg-white border border-gray-100 rounded-2xl p-4 flex-1 flex flex-col">
              <div className="flex justify-between items-center mb-3">
                <h3 className="font-bold text-gray-900 text-sm">Weekly Activity</h3>
                <span className="text-[10px] text-gray-400 font-medium bg-gray-50 px-2 py-1 rounded-lg">Last 7 Days</span>
              </div>
              <div className="flex items-end justify-between flex-1 gap-2 min-h-0">
                {[40, 70, 35, 90, 60, 80, 50].map((h, i) => (
                  <div key={i} className="w-full bg-gray-100 rounded-t-lg relative h-full">
                    <div style={{ height: `${h}%` }} className={`absolute bottom-0 w-full rounded-t-lg transition-all duration-500 ${i === 3 ? 'bg-blue-500' : 'bg-blue-200'}`}></div>
                  </div>
                ))}
              </div>
              <div className="flex justify-between mt-2 text-xs text-gray-400 font-medium">
                <span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span><span>S</span>
              </div>
            </div>
          </div>
        )}

        {tab === 'processing' && (
          <div className="px-4">
            {processingVideos.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-[50vh]">
                <div className="w-20 h-20 bg-gray-50 rounded-full flex items-center justify-center mb-4">
                  <span className="text-4xl grayscale opacity-50">⚙️</span>
                </div>
                <p className="text-gray-900 font-bold text-lg">No Processing Videos</p>
                <p className="text-gray-400 text-sm mt-1">Videos currently being dubbed will appear here</p>
              </div>
            ) : (
              <div className="space-y-3">
                {processingVideos.map((video: any) => (
                  <ProcessingCard key={video.id} video={video} onCancel={handleCancelJob} />
                ))}
              </div>
            )}
          </div>
        )}

        {tab === 'gallery' && (() => {
          const usedIds = new Set(usedVideos.map(v => v.id))
          const availableVideos = [...videos.filter((v: Video) => !usedIds.has(v.id)), ...usedVideos].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
          const filtered = categoryFilter === 'unused' ? availableVideos.filter((v: Video) => !usedIds.has(v.id))
            : categoryFilter === 'used' ? availableVideos.filter((v: Video) => usedIds.has(v.id))
              : availableVideos

          return (
            <div className="px-4">
              {loading ? (
                <div className="grid grid-cols-3 gap-3">
                  {[1, 2, 3, 4, 5, 6].map(i => (
                    <div key={i} className="aspect-[9/16] rounded-2xl bg-gray-100 animate-pulse" />
                  ))}
                </div>
              ) : availableVideos.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-[50vh]">
                  <div className="w-20 h-20 bg-gray-50 rounded-full flex items-center justify-center mb-4">
                    <span className="text-4xl grayscale opacity-50">🎬</span>
                  </div>
                  <p className="text-gray-900 font-bold text-lg">No Videos Yet</p>
                  <p className="text-gray-400 text-sm mt-1">Send a link to start dubbing</p>
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-3">
                  {filtered.map((video) => (
                    <VideoCard
                      key={video.id}
                      video={video}
                      formatDuration={formatDuration}
                      onDelete={(id) => {
                        setVideos(videos.filter(v => v.id !== id));
                        setUsedVideos(usedVideos.filter(v => v.id !== id));
                      }}
                      onUpdate={(id, fields) => {
                        setVideos(videos.map(v => v.id === id ? { ...v, ...fields } : v));
                        setUsedVideos(usedVideos.map(v => v.id === id ? { ...v, ...fields } : v));
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
          )
        })()}

        {tab === 'logs' && (
          <div className="px-4">
            {/* Date Filter - Pretty */}
            <div className="mb-4">
              <div className="flex items-center gap-2">
                {/* Date Picker Button */}
                <div className="flex-1 relative">
                  <input
                    type="date"
                    value={logDateFilter}
                    onChange={(e) => setLogDateFilter(e.target.value)}
                    className="absolute inset-0 opacity-0 w-full h-full cursor-pointer"
                  />
                  <div className="bg-white border border-gray-200 rounded-2xl px-4 py-3 flex items-center gap-3 active:scale-95 transition-all shadow-sm">
                    <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth="2">
                        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                        <line x1="16" y1="2" x2="16" y2="6" />
                        <line x1="8" y1="2" x2="8" y2="6" />
                        <line x1="3" y1="10" x2="21" y2="10" />
                      </svg>
                    </div>
                    <div className="flex-1">
                      <p className="text-[11px] text-gray-400 font-medium">เลือกวันที่</p>
                      <p className="text-sm font-bold text-gray-900">
                        {(() => {
                          const [y, m, d] = logDateFilter.split('-')
                          const thaiMonths = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']
                          return `${parseInt(d)} ${thaiMonths[parseInt(m) - 1]} ${parseInt(y) + 543}`
                        })()}
                      </p>
                    </div>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" strokeWidth="2">
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </div>
                </div>

                {/* Today Button */}
                <button
                  onClick={() => setLogDateFilter(getTodayString())}
                  className="shrink-0 bg-blue-500 text-white px-4 py-3 rounded-2xl text-sm font-bold active:scale-95 transition-all shadow-sm shadow-blue-200"
                >
                  วันนี้
                </button>
              </div>
            </div>

            {(() => {
              const filteredLogs = postHistory.filter(item => {
                const itemDate = new Date(item.posted_at)
                const thaiItemDate = new Date(itemDate.getTime() + 7 * 60 * 60 * 1000)
                const itemDateStr = thaiItemDate.toISOString().split('T')[0]
                return itemDateStr === logDateFilter
              })

              if (filteredLogs.length === 0) return (
                <div className="flex flex-col items-center justify-center h-[40vh]">
                  <div className="w-20 h-20 bg-gray-50 rounded-full flex items-center justify-center mb-4">
                    <span className="text-4xl grayscale opacity-50">📋</span>
                  </div>
                  <p className="text-gray-900 font-bold text-lg">ไม่มีข้อมูลวันนี้</p>
                  <p className="text-gray-400 text-sm mt-1">ลองเลือกวันอื่นดู</p>
                </div>
              )

              return (
                <div className="space-y-2.5">
                  {filteredLogs.map((item) => {
                    const postedDate = new Date(item.posted_at)
                    const thaiDate = new Date(postedDate.getTime() + 7 * 60 * 60 * 1000)
                    const timeStr = `${thaiDate.getUTCHours().toString().padStart(2, '0')}:${thaiDate.getUTCMinutes().toString().padStart(2, '0')}`
                    const fbLink = item.fb_post_id ? `https://www.facebook.com/reel/${item.fb_post_id}` : ''

                    return (
                      <div key={item.id} className="flex items-center gap-3 p-3 rounded-2xl border border-gray-100 bg-white shadow-sm">
                        {/* Page avatar */}
                        <img
                          src={item.page_image || 'https://via.placeholder.com/40'}
                          alt={item.page_name}
                          className="w-10 h-10 rounded-full object-cover shrink-0 ring-2 ring-gray-100"
                        />
                        {/* Info */}
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-bold text-gray-900 truncate">{item.page_name}</p>
                          <p className="text-xs text-gray-400">{timeStr} น.</p>
                        </div>
                        {/* Status + Link */}
                        <div className="flex items-center gap-2 shrink-0">
                          <span className={`text-[10px] font-bold px-2 py-1 rounded-lg ${item.status === 'success' ? 'bg-green-50 text-green-600' :
                            item.status === 'posting' ? 'bg-yellow-50 text-yellow-600' :
                              'bg-red-50 text-red-600'
                            }`}>
                            {item.status === 'success' ? 'สำเร็จ' : item.status === 'posting' ? 'กำลังโพสต์' : 'ผิดพลาด'}
                          </span>
                          {fbLink && (
                            <a
                              href={fbLink}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center active:scale-90 transition-transform"
                            >
                              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth="2">
                                <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" strokeLinecap="round" strokeLinejoin="round" />
                                <path d="M15 3h6v6" strokeLinecap="round" strokeLinejoin="round" />
                                <path d="M10 14L21 3" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            </a>
                          )}
                          <button
                            disabled={deletingLogId === item.id}
                            onClick={async () => {
                              setDeletingLogId(item.id)
                              try {
                                await fetch(`${WORKER_URL}/api/post-history/${item.id}`, { method: 'DELETE' })
                                setPostHistory(prev => prev.filter(h => h.id !== item.id))
                              } finally {
                                setDeletingLogId(null)
                              }
                            }}
                            className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center active:scale-90 transition-transform"
                          >
                            {deletingLogId === item.id ? (
                              <div className="w-3.5 h-3.5 border-2 border-red-400 border-t-transparent rounded-full animate-spin" />
                            ) : (
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2">
                                <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14z" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            )}
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )
            })()}
          </div>
        )}

        {tab === 'pages' && (
          <div className="px-4" onClick={() => deletePageId && setDeletePageId(null)}>
            {pagesLoading ? (
              <div className="grid grid-cols-3 gap-4">
                {[1, 2, 3, 4, 5, 6].map(i => (
                  <div key={i} className="aspect-square rounded-2xl bg-gray-100 animate-pulse" />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-4">
                {pages.map((page) => {
                  let longPressTimer: ReturnType<typeof setTimeout> | null = null
                  const isDeleting = deletePageId === page.id

                  const onTouchStart = () => {
                    longPressTimer = setTimeout(() => {
                      setDeletePageId(page.id)
                      longPressTimer = null
                    }, 500)
                  }
                  const onTouchEnd = () => {
                    if (longPressTimer) {
                      clearTimeout(longPressTimer)
                      longPressTimer = null
                    }
                  }

                  return (
                    <button
                      key={page.id}
                      onClick={() => !isDeleting && setSelectedPage(page)}
                      onTouchStart={onTouchStart}
                      onTouchEnd={onTouchEnd}
                      onTouchMove={onTouchEnd}
                      onContextMenu={(e) => { e.preventDefault(); setDeletePageId(page.id) }}
                      className="flex flex-col items-center group"
                    >
                      <div className="relative w-full">
                        <img
                          src={page.image_url || 'https://via.placeholder.com/100'}
                          alt={page.name}
                          className={`w-full aspect-square rounded-2xl object-cover shadow-md transition-all ${isDeleting ? 'scale-95 brightness-90' : 'group-active:scale-95'}`}
                        />
                        {/* Status Badge */}
                        <div className={`absolute -bottom-1 -right-1 w-5 h-5 rounded-full border-2 border-white ${page.is_active === 1 ? 'bg-green-500' : 'bg-gray-300'}`}></div>

                        {/* Delete button - bottom center pill */}
                        {isDeleting && (
                          <div
                            className="absolute bottom-2 left-1/2 -translate-x-1/2 bg-red-500 rounded-full px-3 py-1 flex items-center gap-1 shadow-lg"
                            onClick={(e) => {
                              e.stopPropagation()
                              handleDeletePage(page.id)
                            }}
                          >
                            {deletingPageId === page.id ? (
                              <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                            ) : (
                              <>
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
                                  <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14z" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                                <span className="text-white text-[11px] font-bold">ลบ</span>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                      <p className="mt-2 text-xs font-medium text-gray-700 text-center line-clamp-1">{page.name}</p>
                      <p className="text-[10px] text-gray-400">ทุก {page.post_interval_minutes} นาที</p>
                    </button>
                  )
                })}

                {/* Add Page Button */}
                <button
                  onClick={() => setShowAddPagePopup(true)}
                  className="flex flex-col items-center justify-center aspect-square rounded-2xl border-2 border-dashed border-gray-200 bg-gray-50 active:scale-95 transition-transform"
                >
                  <div className="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center text-gray-400 mb-2">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M12 5v14M5 12h14" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                  <p className="text-xs text-gray-400 font-medium">Add Page</p>
                </button>
              </div>
            )}
          </div>
        )}

        {tab === 'settings' && (
          <div className="px-5 space-y-6">
            {user && (
              <div className="flex items-center p-4 bg-gray-50 rounded-3xl border border-gray-100">
                <div className="w-16 h-16 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-full flex items-center justify-center text-white text-2xl font-bold shadow-lg">
                  {user.first_name?.charAt(0) || 'U'}
                </div>
                <div className="ml-4">
                  <h3 className="font-bold text-gray-900 text-lg">{user.first_name} {user.last_name}</h3>
                  <p className="text-blue-500 font-medium text-xs bg-blue-50 px-2 py-0.5 rounded-md inline-block mt-1">Premium Member</p>
                </div>
              </div>
            )}

            {/* Category Management */}
            <div className="space-y-3">
              <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider ml-2">หมวดหมู่วีดีโอ</h4>
              <div className="bg-white border border-gray-100 rounded-2xl p-4 space-y-3">
                {categories.map((cat) => (
                  <div key={cat} className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-900">#{cat}</span>
                    <button
                      onClick={() => saveCategories(categories.filter(c => c !== cat))}
                      className="w-8 h-8 rounded-lg bg-red-50 text-red-500 flex items-center justify-center active:scale-90 transition-transform"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </button>
                  </div>
                ))}
                <div className="flex gap-2 pt-1">
                  <input
                    type="text"
                    value={newCat}
                    onChange={(e) => setNewCat(e.target.value)}
                    placeholder="เพิ่มหมวดหมู่ใหม่"
                    className="flex-1 bg-gray-50 border border-gray-200 rounded-xl px-3 py-2.5 text-sm outline-none focus:border-blue-400"
                  />
                  <button
                    onClick={() => {
                      if (newCat.trim() && !categories.includes(newCat.trim())) {
                        saveCategories([...categories, newCat.trim()])
                        setNewCat('')
                      }
                    }}
                    disabled={!newCat.trim()}
                    className="bg-gray-900 text-white px-4 rounded-xl text-sm font-bold active:scale-95 transition-all disabled:opacity-30"
                  >
                    เพิ่ม
                  </button>
                </div>
              </div>
            </div>

            <div className="flex justify-center pt-8">
              <p className="text-gray-300 text-xs font-medium">Version 2.0.1 (Build 240)</p>
            </div>
          </div>
        )}
      </div>

      {/* Bottom Navigation */}
      <div className="fixed bottom-0 left-0 right-0 bg-white/90 backdrop-blur-lg border-t border-gray-100 safe-bottom z-40">
        <div className="flex pt-2 pb-1">
          <NavItem
            icon={<HomeIcon />}
            iconActive={<HomeIconFilled />}
            label="Home"
            active={tab === 'home'}
            onClick={() => setTab('home')}
          />
          <NavItem
            icon={<ProcessIcon />}
            iconActive={<ProcessIconFilled />}
            label="Processing"
            active={tab === 'processing'}
            onClick={() => setTab('processing')}
          />
          <NavItem
            icon={<VideoIcon />}
            iconActive={<VideoIconFilled />}
            label="Gallery"
            active={tab === 'gallery'}
            onClick={() => setTab('gallery')}
          />
          <NavItem
            icon={<ListIcon />}
            iconActive={<ListIconFilled />}
            label="Logs"
            active={tab === 'logs'}
            onClick={() => setTab('logs')}
          />
          <NavItem
            icon={<PagesIcon />}
            iconActive={<PagesIconFilled />}
            label="Pages"
            active={tab === 'pages'}
            onClick={() => setTab('pages')}
          />
          <NavItem
            icon={<SettingsIcon />}
            iconActive={<SettingsIconFilled />}
            label="Settings"
            active={tab === 'settings'}
            onClick={() => setTab('settings')}
          />
        </div>
      </div>
    </div>
  )
}

function NavItem({ icon, iconActive, label, active, onClick }: {
  icon: React.ReactNode;
  iconActive: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 py-2 flex flex-col items-center relative group`}
      style={{ WebkitTapHighlightColor: 'transparent' }}
    >
      <div className={`text-2xl mb-1 transition-all duration-300 ${active ? 'text-blue-600 scale-110' : 'text-gray-400 group-active:scale-95'}`}>
        {active ? iconActive : icon}
      </div>
      <span className={`text-[10px] font-bold tracking-wide transition-colors ${active ? 'text-blue-600' : 'text-gray-400'}`}>
        {label}
      </span>
      {/* Active Line */}
      {active && (
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-8 h-0.5 bg-blue-600 rounded-b-lg shadow-blue-400 shadow-[0_0_10px_rgba(37,99,235,0.5)]"></div>
      )}
    </button>
  )
}

export default App
