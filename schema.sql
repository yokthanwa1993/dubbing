-- Jobs table to track dubbing jobs
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  source_url TEXT NOT NULL,
  video_url TEXT,
  status TEXT DEFAULT 'pending',
  script TEXT,
  voice TEXT DEFAULT 'Puck',
  description TEXT,
  reel_url TEXT,
  reel_id TEXT,
  error TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

-- Create index for status queries
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
