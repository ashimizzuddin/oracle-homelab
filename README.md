# AI JOB FILTER

A personal Telegram job filtering and scoring daemon.

## Project Purpose
This application monitors specified Telegram groups and channels for job postings, extracts structured data (from both text and image posters), matches the roles against a configured candidate profile, and sends high-quality job alerts to the user.

## High-Level Architecture
- **Ingestion**: Telethon (MTProto user client) + web job-board ingestion (`scripts/ingest_web_candidate.py`)
- **Local Filtering**: Regex, exact/fuzzy text deduplication, and dHash image deduplication ($0 cost)
- **Extraction**: LLM-based structured extraction via free tiers (Groq for text, Gemini Flash for images)
- **Database**: Local SQLite with WAL mode
- **Scoring**: Deterministic rule-based scoring (0-100)
- **Notification**: Telegram Bot API (duplicate-job alerts suppressed; rows kept as audit trail)

## Current Status
**IMPLEMENTED — MVP functional.** Core pipeline (detection → dedup → extraction → scoring → notification) is working, covered by a test suite (89 tests passing). Web candidate ingestion adapter included with real-world fixtures. Not yet running as a persistent daemon in production.

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
