import { useEffect, useState } from 'react'

const API_URL = 'https://dubbing-api.lslly.com'

interface Stats {
  total: number
  completed: number
  processing: number
  failed: number
}

interface Job {
  id: string
  url: string
  status: 'completed' | 'processing' | 'failed'
  created_at: string
}

interface Video {
  id: string
  script: string
  duration: number
  originalUrl: string
  createdAt: string
  publicUrl: string
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

// Video card component
function VideoCard({ video, formatDuration }: { video: Video; formatDuration: (s: number) => string }) {
  const [expanded, setExpanded] = useState(false)

  if (expanded) {
    return (
      <div className="fixed inset-0 z-50 bg-black flex items-center justify-center p-4 bg-opacity-90 backdrop-blur-sm" onClick={() => setExpanded(false)}>
        <div className="w-full max-w-lg aspect-[9/16] relative rounded-2xl overflow-hidden shadow-2xl">
          <video
            src={video.publicUrl}
            className="w-full h-full object-cover"
            controls
            autoPlay
            playsInline
          />
        </div>
      </div>
    )
  }

  return (
    <div
      className="relative aspect-[9/16] rounded-2xl overflow-hidden cursor-pointer bg-gray-100 shadow-sm active:scale-95 transition-transform duration-200"
      onClick={() => setExpanded(true)}
    >
      <video
        src={video.publicUrl}
        className="w-full h-full object-cover"
        autoPlay
        muted
        loop
        playsInline
      />
      <div className="absolute bottom-2 right-2 bg-black/60 backdrop-blur-md text-white text-[10px] px-2 py-0.5 rounded-full font-medium">
        {formatDuration(video.duration)}
      </div>
    </div>
  )
}

function App() {
  const [stats, setStats] = useState<Stats>({ total: 0, completed: 0, processing: 0, failed: 0 })
  const [jobs, setJobs] = useState<Job[]>([])
  const [videos, setVideos] = useState<Video[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'home' | 'gallery' | 'logs' | 'settings'>('home')

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
    const interval = setInterval(loadData, 10000)
    return () => clearInterval(interval)
  }, [])

  async function loadData() {
    try {
      try {
        const statsResp = await fetch(`${API_URL}/stats`)
        if (statsResp.ok) setStats(await statsResp.json())
      } catch { }

      try {
        const jobsResp = await fetch(`${API_URL}/jobs`)
        if (jobsResp.ok) setJobs(await jobsResp.json())
      } catch { }

      try {
        const galleryResp = await fetch(`${API_URL}/gallery`)
        if (galleryResp.ok) {
          const data = await galleryResp.json()
          setVideos(data.videos || [])
        }
      } catch { }
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  function formatDuration(seconds: number) {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  return (
    <div className="fixed inset-0 bg-white font-['Sukhumvit_Set','Kanit',sans-serif] overflow-hidden">

      {/* Header Title - Always Fixed at Top */}
      <div className="fixed top-0 left-0 right-0 h-14 bg-white z-10 flex items-end justify-center pb-2">
        <h1 className="text-3xl font-extrabold text-gray-900 tracking-tight translate-y-1">
          {tab === 'home' ? 'Dashboard' : tab === 'gallery' ? 'Gallery' : tab === 'logs' ? 'Activity Logs' : 'Settings'}
        </h1>
      </div>

      {/* Main Content Area - Separated Logic */}
      <div className="fixed top-14 bottom-[80px] left-0 right-0 w-full">

        {/* HOME TAB: LOCKED (No Scroll) */}
        {tab === 'home' && (
          <div className="w-full h-full overflow-hidden px-5 flex flex-col gap-4 py-2">
            {/* Quick Stats Mockup */}
            <div className="grid grid-cols-2 gap-3 shrink-0">
              <div className="bg-blue-50 p-4 rounded-3xl border border-blue-100 flex flex-col justify-center">
                <div className="w-8 h-8 bg-blue-500 rounded-full flex items-center justify-center text-white mb-2 shadow-blue-200 shadow-lg">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 6v6m0 0v6m0-6h6m-6 0H6" strokeLinecap="round" strokeLinejoin="round" /></svg>
                </div>
                <p className="text-blue-600 font-medium text-xs">Total Dubbed</p>
                <p className="text-2xl font-bold text-gray-900">{stats.total || '124'}</p>
              </div>
              <div className="bg-green-50 p-4 rounded-3xl border border-green-100 flex flex-col justify-center">
                <div className="w-8 h-8 bg-green-500 rounded-full flex items-center justify-center text-white mb-2 shadow-green-200 shadow-lg">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                </div>
                <p className="text-green-600 font-medium text-xs">Success Rate</p>
                <p className="text-2xl font-bold text-gray-900">98%</p>
              </div>
            </div>

            {/* Credit Balance Card */}
            <div className="bg-gray-900 text-white p-5 rounded-[28px] shadow-xl relative overflow-hidden shrink-0">
              <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full blur-3xl -mr-10 -mt-10"></div>
              <div className="relative z-10">
                <p className="text-white/60 font-medium mb-1 text-sm">Available Credits</p>
                <div className="flex items-baseline gap-2">
                  <span className="text-3xl font-bold">2,450</span>
                  <span className="text-white/60 text-sm">pts</span>
                </div>
                <div className="mt-4 flex gap-3">
                  <button className="flex-1 bg-white/20 hover:bg-white/30 transition-colors py-2 rounded-xl text-xs font-medium backdrop-blur-md">Top Up</button>
                  <button className="flex-1 bg-white text-gray-900 py-2 rounded-xl text-xs font-bold shadow-lg">History</button>
                </div>
              </div>
            </div>

            {/* Weekly Activity Mockup - Flexible Height */}
            <div className="bg-white border border-gray-100 rounded-3xl p-4 shadow-sm flex-1 min-h-0 flex flex-col">
              <div className="flex justify-between items-center mb-2 shrink-0">
                <h3 className="font-bold text-gray-900 text-sm">Weekly Activity</h3>
                <span className="text-[10px] text-gray-400 font-medium bg-gray-50 px-2 py-0.5 rounded-lg">Last 7 Days</span>
              </div>
              <div className="flex items-end justify-between flex-1 gap-2 min-h-0 px-2 pb-1">
                {[40, 70, 35, 90, 60, 80, 50].map((h, i) => (
                  <div key={i} className="w-full bg-gray-100 rounded-t-lg relative group h-full">
                    <div style={{ height: `${h}%` }} className={`absolute bottom-0 w-full rounded-t-lg transition-all duration-500 ${i === 3 ? 'bg-blue-500' : 'bg-blue-200'}`}></div>
                  </div>
                ))}
              </div>
              <div className="flex justify-between mt-1 text-[10px] text-gray-400 font-medium shrink-0">
                <span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span><span>S</span>
              </div>
            </div>
          </div>
        )}

        {/* OTHER TABS: SCROLLABLE */}
        {tab !== 'home' && (
          <div className="w-full h-full overflow-y-auto overscroll-y-auto pb-4" style={{ WebkitOverflowScrolling: 'touch' }}>

            {/* Gallery Content */}
            {tab === 'gallery' && (
              <div className="px-4">
                {loading ? (
                  <div className="grid grid-cols-3 gap-3">
                    {[1, 2, 3, 4, 5, 6].map(i => (
                      <div key={i} className="aspect-[9/16] rounded-2xl bg-gray-100 animate-pulse" />
                    ))}
                  </div>
                ) : videos.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-[50vh]">
                    <div className="w-20 h-20 bg-gray-50 rounded-full flex items-center justify-center mb-4">
                      <span className="text-4xl grayscale opacity-50">🎬</span>
                    </div>
                    <p className="text-gray-900 font-bold text-lg">No Videos Yet</p>
                    <p className="text-gray-400 text-sm mt-1">Send a link to start dubbing</p>
                  </div>
                ) : (
                  <div className="grid grid-cols-3 gap-3">
                    {videos.map((video) => (
                      <VideoCard key={video.id} video={video} formatDuration={formatDuration} />
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Logs Content */}
            {tab === 'logs' && (
              <div className="bg-white px-4">
                <div className="space-y-4">
                  {jobs.length === 0 ? (
                    <div className="text-center py-10 text-gray-400">No logs available</div>
                  ) : jobs.slice(0, 10).map((job) => (
                    <div key={job.id} className="flex items-center p-3 sm:p-4 rounded-2xl border border-gray-100 bg-white shadow-sm">
                      <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${job.status === 'completed' ? 'bg-green-100 text-green-600' :
                        job.status === 'processing' ? 'bg-yellow-100 text-yellow-600' : 'bg-red-100 text-red-600'
                        }`}>
                        {job.status === 'completed' ? (
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                        ) : job.status === 'processing' ? (
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z" strokeLinecap="round" strokeLinejoin="round" /><path d="M12 6v6l4 2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                        ) : (
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" /></svg>
                        )}
                      </div>
                      <div className="ml-3 flex-1 min-w-0">
                        <p className="text-sm font-bold text-gray-900 truncate">Dubbing Job</p>
                        <p className="text-xs text-gray-400 truncate">{job.url}</p>
                      </div>
                      <div className="text-right">
                        <span className={`text-xs font-bold px-2 py-1 rounded-lg ${job.status === 'completed' ? 'bg-green-50 text-green-700' :
                          job.status === 'processing' ? 'bg-yellow-50 text-yellow-700' : 'bg-red-50 text-red-700'
                          }`}>
                          {job.status}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Settings Content */}
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

                <div className="space-y-1">
                  <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider ml-2 mb-2">Application</h4>
                  <button className="w-full flex items-center justify-between p-4 rounded-2xl hover:bg-gray-50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-orange-100 text-orange-600 flex items-center justify-center">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2a10 10 0 1010 10A10 10 0 0012 2zm0 14a1 1 0 111-1 1 1 0 01-1 1zm1-5a1 1 0 00-1-1 1 1 0 000 2 1 1 0 001-1z" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      </div>
                      <span className="font-medium text-gray-900">Notifications</span>
                    </div>
                    <div className="w-10 h-6 bg-blue-500 rounded-full relative"><div className="w-5 h-5 bg-white rounded-full absolute top-0.5 right-0.5 shadow-sm"></div></div>
                  </button>
                  <button className="w-full flex items-center justify-between p-4 rounded-2xl hover:bg-gray-50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-purple-100 text-purple-600 flex items-center justify-center">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      </div>
                      <span className="font-medium text-gray-900">Dark Mode</span>
                    </div>
                    <div className="w-10 h-6 bg-gray-200 rounded-full relative"><div className="w-5 h-5 bg-white rounded-full absolute top-0.5 left-0.5 shadow-sm"></div></div>
                  </button>
                </div>

                <div className="flex justify-center pt-8">
                  <p className="text-gray-300 text-xs font-medium">Version 2.0.1 (Build 240)</p>
                </div>
              </div>
            )}
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
