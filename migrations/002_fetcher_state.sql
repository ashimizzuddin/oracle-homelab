-- PRD F-WEB-3: DB-backed fetcher state (replaces per-fetcher *_seen.json files).
-- State is transactional, queryable, and aligned with the 30-day dedup window.
CREATE TABLE IF NOT EXISTS fetcher_state (
    source         TEXT PRIMARY KEY,
    last_run_at    TEXT,
    last_status    TEXT,                -- ok | error | partial
    seen_slugs     TEXT NOT NULL DEFAULT '[]',  -- JSON array of slug/url strings
    stats          TEXT NOT NULL DEFAULT '{}'   -- JSON {found, new, ingested, skipped}
);
