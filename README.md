# AI JOB FILTER

A personal Telegram job filtering and scoring daemon.

## Project Purpose
This application monitors specified Telegram groups and channels for job postings, extracts structured data (from both text and image posters), matches the roles against a configured candidate profile, and sends high-quality job alerts to the user.

## High-Level Architecture
- **Ingestion**: Telethon (MTProto user client) + web job-board ingestion (`scripts/ingest_web_candidate.py`)
- **Local Filtering**: Regex, exact/fuzzy text deduplication, and dHash image deduplication ($0 cost)
- **Extraction**: LLM-based structured extraction via free tiers (Groq for text, Gemini Flash for images)
- **Database**: Local SQLite with WAL mode (`data/jobs.db`)
- **Scoring**: Deterministic rule-based scoring (0-100)
- **Notification**: Telegram Bot API (duplicate-job alerts suppressed; rows kept as audit trail)

## Current Status
**PRODUCTION — Running as systemd service.** Core pipeline (detection → dedup → extraction → scoring → notification) is working, covered by a test suite. Web scheduler ingests 8 job boards daily at 07:00 (talentics, dealls, techinasia, kitalulus, glints, kalibrr, karircom, topkarir). Telegram listener monitors `@LowonganKerjaIT`, `@joinkerjatalenthub`, `@devopsindonesia` in real-time.

## Deployment (VPS)
Runs as a systemd service with auto-restart:

```bash
# Service management
sudo systemctl status ai-job-filter.service
sudo systemctl restart ai-job-filter.service
sudo journalctl -u ai-job-filter -f

# Application logs
sudo tail -f /var/log/ai-job-filter.log
sudo tail -f /var/log/ai-job-filter-error.log
```

Service definition: `/etc/systemd/system/ai-job-filter.service` (User=ubuntu, WorkingDirectory=/home/ubuntu/ai-job-filter, Restart=always, RestartSec=10).

### Configuration (.env)
Key settings:
- `TELEGRAM_CHANNELS` — monitored channels (comma-separated @usernames)
- `MIN_SCORE_APPLY` / `MIN_SCORE_REVIEW` — scoring thresholds (current: 65 / 40)
- `HISTORY_LOOKBACK_HOURS` / `HISTORY_MAX_MESSAGES` — history sync on startup
- `DRY_RUN` — log notifications instead of sending

Note: notification threshold in `telegram/notifier.py` reads `config.min_score_review` from `.env` (previously hardcoded).

## Known Fixes (2026-08-31)
- **Score=0 notifications**: listener enriched payload via `get_job_by_message_id(telegram_msg_id)` — wrong ID space (expects internal `messages.id`). Now enriches from `get_job(job_id)` (`SELECT *`).
- **Hardcoded notify threshold**: `MIN_SCORE_TO_NOTIFY=55` constant replaced with config-driven `self.min_score_to_notify`.
- **Crash on NULL fields**: `escape(None)` in notifier for `title`/`company` — now falls back to "Unknown Role"/"Unknown Company".
- **Daemon instability**: manual `nohup` runs died silently; replaced with systemd auto-restart.
- Pending investigation: intermittent `FOREIGN KEY constraint failed` on some history messages (handler-level, non-fatal), Groq 429 rate limits on free tier (retry worker handles these).

## Useful Queries
```bash
# Recent jobs
sqlite3 data/jobs.db "SELECT datetime(created_at) c, title, classification, match_score FROM jobs ORDER BY created_at DESC LIMIT 10;"

# Today's ingestion count by classification
sqlite3 data/jobs.db "SELECT classification, COUNT(*) FROM jobs WHERE date(created_at)=date('now') GROUP BY classification;"

# Notifications sent
sqlite3 data/jobs.db "SELECT n.id, j.title, j.match_score, n.sent_at FROM notifications n JOIN jobs j ON j.id=n.job_id ORDER BY n.id DESC LIMIT 10;"
```

## MVP Scope
The MVP focuses on a $0-cost operating model using local SQLite, Python asyncio, Telethon, and free-tier APIs (Groq/Gemini). It includes text and image processing, deductive filtering, and deterministic scoring. It does NOT include auto-applying, web dashboards, or heavy infrastructure (PostgreSQL/Redis/Docker).

## Getting Started for Developers / Agents
If you are an AI agent continuing this project, **STOP** and read `docs/HANDOFF.md` and `docs/architecture-decision-record-v1.1.md` before making any modifications.

### Quick commands
```bash
# Run the test suite
uv run python -m pytest tests/ -q

# Ingest a web job candidate (dry-run: no DB writes)
uv run python scripts/ingest_web_candidate.py --file candidate.json --dry-run
```
