# AI JOB FILTER - Antigravity Project Instructions

## Project Purpose
A personal Telegram job filtering system that monitors groups/channels, extracts job postings (text and image-based), matches them against a specific candidate profile, and notifies the user of relevant opportunities based on a 0-100 scoring system.

## Candidate Profile
* **Experience**: 0 years formal professional IT experience.
* **Certifications**: RHCSA.
* **Strongest Area**: Linux / System Administration.
* **Career Direction**: Cybersecurity (long-term).
* **Focus**: Entry-level / Junior / Fresh Graduate.
* **Weaknesses**: No professional frontend, backend, or web-development experience.
* **CRITICAL RULE**: Never fabricate experience. Never treat certification or personal learning as professional work experience.

## Architecture & Rules
* **Free-first architecture**: Rely on local processing, open-source software, and free-tier APIs (Groq, Gemini).
* **No silent paid APIs**: Never fall back to a paid provider automatically. Rate limits should trigger a PENDING queue.
* **Image Processing**: Image-only Telegram posts MUST be processed (branch on media presence, not just text keywords).
* **No Auto-Apply**: Human action is always required to apply to jobs.
* **Security**: Secrets (API keys, Telegram session strings) must NEVER be committed. Use `.env` and `chmod 600`.
* **Simplicity**: Keep the MVP simple. Do not over-engineer. No Kubernetes, Redis, or microservices. Follow the approved Architecture Decision Record.
