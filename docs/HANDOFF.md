# AI JOB FILTER - Project Handoff

**IMPORTANT: Application code has NOT been implemented yet.**

This document provides a complete context for the next Antigravity agent or developer to continue this project.

## 1. Project Objective
A personal Telegram job filtering system that monitors groups/channels, extracts job postings (text and image-based), scores them against a specific candidate profile, and notifies the user of relevant opportunities.

## 2. Candidate Profile
* **Experience**: 0 years formal professional IT experience.
* **Certifications**: RHCSA.
* **Strongest Area**: Linux / System Administration, RHEL, Networking, VMware, Kali Linux, Bash.
* **CRITICAL RULE**: Never fabricate experience. Certifications are NOT professional work experience.

## 3. Career Direction
Cybersecurity (long-term), Infrastructure Security, SOC, Penetration Testing, Bug Bounty, Security Engineering. Focus is on Entry-level / Junior / Fresh Graduate positions.

## 4. Current Architecture
Free-first, single-process asyncio daemon using Python (3.13/3.14). Dual Telegram client architecture (Telethon + Bot API), with a local SQLite database (WAL mode). No heavy infrastructure (no Docker, Redis, Postgres, or microservices).

## 5. Telegram Ingestion Strategy
* **Telethon**: Used as an MTProto user client to monitor groups/channels passively.
* **Telegram Bot API**: Used to send notifications and receive user feedback (inline buttons).

## 6. Image/Poster Processing
Image-only Telegram posts MUST be processed. Branching occurs on media presence, not text keywords. Images are downloaded, deduplicated locally via dHash, and then processed using the free-tier Gemini API.

## 7. Text Processing
Raw text goes through local regex/keyword detection ($0 cost). If job keywords are found, it proceeds to deduplication and then structured extraction via the free-tier Groq API.

## 8. Deduplication
Multi-layer deduplication to avoid redundant API calls:
1. **Exact Text**: SHA-256 hash.
2. **Fuzzy Text**: RapidFuzz (>= 85%).
3. **Exact/Fuzzy Image**: SHA-256 and dHash (hamming distance).
4. **Job-Level**: Title + Company + Location matching.

## 9. LLM/Vision Strategy
* **Providers**: Groq for text, Gemini for vision.
* **Abstraction**: Simple Python protocol, NO heavy LiteLLM (to avoid 30-50+ transitive dependencies).
* **Extraction**: Direct SDK usage with Pydantic JSON validation.

## 10. Free-Tier Strategy
The system must operate at ~$0 cost. 
* **NO silent paid APIs**. 
* **NO automatic cross-provider fallback**.
* Rate limits trigger explicit queuing (`PENDING_AI` or `PENDING_VISION`) to retry later.

## 11. Scoring Model
Deterministic, rule-based Python logic (0-100 score).
* Role relevance: 30
* Technical skill alignment: 25
* Experience fit: 20
* Career trajectory: 15
* Practical factors: 10

## 12. APPLY / REVIEW / IGNORE Thresholds
Configurable via environment variables. Defaults:
* `MIN_SCORE_APPLY` = 75
* `MIN_SCORE_REVIEW` = 55
* `< 55` = IGNORE

## 13. Database Plan
Local SQLite with WAL mode. Tables:
* `sources`
* `messages`
* `jobs`
* `notifications`
* `schema_version`
* `jobs_fts` (FTS5 for full-text search)

## 14. Security Requirements
* All secrets (Telegram StringSession, Bot Token, API keys) must be in `.env`.
* `.env` MUST be in `.gitignore`.
* Use `chmod 600` for `.env`.
* Run `gitleaks` as a pre-commit hook.
* Telegram user session credentials must be treated as equivalent to full account credentials.

## 15. Current Implementation Status
**Planning Phase Complete. Application code has NOT been implemented yet.** Architecture Decision Record v1.1 has been drafted and mostly approved.

## 16. Decisions Already Made
* SQLite over external databases.
* Telethon over Pyrogram (abandoned).
* Free-first local and API processing over paid solutions.
* Direct Groq/Gemini SDKs over LiteLLM.
* Deterministic rule-based scoring over LLM-based scoring.

## 17. Decisions Still Unresolved
* Final list of specific Telegram channels/groups to monitor.
* Detailed regex dictionaries for Indonesian/English keyword detection.

## 18. Known Risks
* Telegram account ban (mitigated by passive listening and `flood_sleep_threshold`).
* Groq token limits on the free tier (mitigated by local filtering and queuing).

## 19. Exact Next Step
1. Finalize ADR v1.2 if needed (applying the last 3 corrections: Gemini 2.5 Flash, strict Job-Level Dedup with location/url, and static provider selection with NO cross-provider fallback).
2. Approve the final architecture.
3. Begin Phase 1 MVP implementation (setting up the project structure, `uv init`, database schema, and initial Telegram ingestion).

## 20. Instructions for the Next Antigravity Agent
Welcome! When you read this, do not rewrite the architecture. Start by examining the ADR, then propose the Phase 1 implementation plan based on the next steps above. **Do not implement code without user approval of the plan.**
