-- ============================================
-- Pragmas (set on every connection open)
-- ============================================
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA cache_size = -64000;  -- 64MB

-- ============================================
-- 1. SOURCES: Monitored Telegram groups/channels
-- ============================================
CREATE TABLE IF NOT EXISTS sources (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id         INTEGER UNIQUE NOT NULL,
    username            TEXT,
    title               TEXT NOT NULL,
    source_type         TEXT NOT NULL DEFAULT 'CHANNEL',  -- CHANNEL | GROUP
    is_active           INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ============================================
-- 2. MESSAGES: Raw Telegram messages (all types)
-- ============================================
CREATE TABLE IF NOT EXISTS messages (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id           INTEGER NOT NULL,
    telegram_msg_id     INTEGER NOT NULL,
    sender_id           INTEGER,

    -- Content
    raw_text            TEXT NOT NULL DEFAULT '',
    caption             TEXT,
    has_media           INTEGER NOT NULL DEFAULT 0,
    media_type          TEXT,                    -- PHOTO | DOCUMENT | null
    media_path          TEXT,                    -- Local path to downloaded file
    media_sha256        TEXT,                    -- SHA-256 of image binary
    media_dhash         TEXT,                    -- dHash perceptual hash (hex string)
    vision_text         TEXT,                    -- Text extracted via Vision API

    -- Metadata
    message_url         TEXT,
    posted_at           TEXT NOT NULL,
    scraped_at          TEXT DEFAULT (datetime('now')),

    -- Processing state
    processing_status   TEXT NOT NULL DEFAULT 'PENDING',
    skip_reason         TEXT,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    last_retry_at       TEXT,

    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE,
    UNIQUE(source_id, telegram_msg_id)
);

-- ============================================
-- 3. JOBS: Extracted & scored job postings
-- ============================================
CREATE TABLE IF NOT EXISTS jobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id          INTEGER NOT NULL UNIQUE,
    source_id           INTEGER NOT NULL,

    -- Extracted structured data
    title               TEXT NOT NULL,
    company             TEXT,
    location            TEXT,
    workplace_type      TEXT DEFAULT 'unknown',
    employment_type     TEXT DEFAULT 'unknown',
    experience_level    TEXT DEFAULT 'not_specified',
    min_years_exp       INTEGER,
    experience_required TEXT,          -- "required" | "preferred" | "plus" | null
    salary_min          REAL,
    salary_max          REAL,
    salary_currency     TEXT DEFAULT 'IDR',
    salary_period       TEXT DEFAULT 'monthly',
    salary_raw          TEXT,
    skills_required     TEXT DEFAULT '[]',
    skills_preferred    TEXT DEFAULT '[]',
    requirements_raw    TEXT DEFAULT '[]',
    contacts            TEXT DEFAULT '{}',
    application_url     TEXT,
    summary             TEXT,
    deadline            TEXT,

    -- Scoring & classification
    match_score         REAL NOT NULL DEFAULT 0,
    classification      TEXT NOT NULL DEFAULT 'IGNORE',
    score_breakdown     TEXT DEFAULT '{}',
    hard_fail_reason    TEXT,

    -- Deduplication
    content_hash        TEXT NOT NULL,
    is_duplicate        INTEGER NOT NULL DEFAULT 0,
    parent_job_id       INTEGER,
    duplicate_method    TEXT,

    -- Status tracking
    status              TEXT NOT NULL DEFAULT 'NEW',
    created_at          TEXT DEFAULT (datetime('now')),

    FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE,
    FOREIGN KEY(parent_job_id) REFERENCES jobs(id) ON DELETE SET NULL
);

-- ============================================
-- 4. NOTIFICATIONS: Sent alerts & user feedback
-- ============================================
CREATE TABLE IF NOT EXISTS notifications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id              INTEGER NOT NULL,
    bot_message_id      INTEGER,
    chat_id             INTEGER NOT NULL,
    sent_at             TEXT DEFAULT (datetime('now')),
    user_action         TEXT,
    user_notes          TEXT,
    action_at           TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

-- ============================================
-- 5. SCHEMA_VERSION: Migration tracking
-- ============================================
CREATE TABLE IF NOT EXISTS schema_version (
    version             INTEGER PRIMARY KEY,
    applied_at          TEXT DEFAULT (datetime('now')),
    description         TEXT
);

-- ============================================
-- Full-Text Search
-- ============================================
CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
    title, company, summary, skills_required,
    content='jobs', content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS jobs_fts_ai AFTER INSERT ON jobs BEGIN
    INSERT INTO jobs_fts(rowid, title, company, summary, skills_required)
    VALUES (new.id, new.title, new.company, new.summary, new.skills_required);
END;

CREATE TRIGGER IF NOT EXISTS jobs_fts_ad AFTER DELETE ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, title, company, summary, skills_required)
    VALUES ('delete', old.id, old.title, old.company, old.summary, old.skills_required);
END;

CREATE TRIGGER IF NOT EXISTS jobs_fts_au AFTER UPDATE ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, title, company, summary, skills_required)
    VALUES ('delete', old.id, old.title, old.company, old.summary, old.skills_required);
    INSERT INTO jobs_fts(rowid, title, company, summary, skills_required)
    VALUES (new.id, new.title, new.company, new.summary, new.skills_required);
END;

-- ============================================
-- Performance indexes
-- ============================================
CREATE INDEX IF NOT EXISTS idx_msg_source ON messages(source_id, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_msg_status ON messages(processing_status)
    WHERE processing_status IN ('PENDING', 'PENDING_AI', 'PENDING_VISION', 'RATE_LIMITED');
CREATE INDEX IF NOT EXISTS idx_msg_media_hash ON messages(media_sha256)
    WHERE media_sha256 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_msg_dhash ON messages(media_dhash)
    WHERE media_dhash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jobs_hash ON jobs(content_hash);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_class ON jobs(classification, status);
CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_job_id)
    WHERE parent_job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jobs_title_company ON jobs(title, company)
    WHERE is_duplicate = 0;
