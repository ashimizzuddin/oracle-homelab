---
name: ai-job-filter-deploy
description: Deploy AI Job Filter to the Oracle VPS production daemon (code sync via git bundle, .env update, systemd restart, verification). Use when asked to deploy, release, or sync this project to VPS.
---

# AI Job Filter — VPS Deploy

Production: Oracle VPS `vps-oracle`, path `/home/ubuntu/ai-job-filter`,
systemd user unit `ai-job-filter`, Python via `uv` (`.venv`).

## Hard rules (from GEMINI.md, never violate)

- **Free-first, Rp0**: never add paid APIs or billing. Rate limits → PENDING queue, never silent paid fallback.
- **No auto-apply**: human action is always required to apply to jobs.
- **Single daemon**: production runs ONLY on the VPS. Never run the daemon on laptop
  and VPS at the same time (Telegram Conflict / AuthKeyDuplicated).
- **Secrets**: `.env` is gitignored. Never print, commit, or paste secret values.
  Always `cp .env .env.bak-$(date +%Y%m%d)` before editing.

## Deploy flow

### A. On laptop (code travels via git bundle + scp, there is no git remote)

```bash
cd ~/tools/"AI JOB FILTER"
git status --short   # review every changed file first
git add <intended files only>
git commit -m "<concise message matching repo style>"
git bundle create /tmp/ai-job-filter.bundle main
scp /tmp/ai-job-filter.bundle vps-oracle:/tmp/
```

### B. On VPS (this session, via ssh vps-oracle)

1. Fetch first, merge only if clean:
   ```bash
   cd /home/ubuntu/ai-job-filter
   git status --short   # must be empty; if not, STOP and ask the user
   git fetch /tmp/ai-job-filter.bundle main && git merge --ff-only FETCH_HEAD
   ```
2. Sync deps + verify (expect 104 passed, ruff clean):
   ```bash
   uv sync
   uv run python -m pytest tests/ -m "not integration" -q
   uv run ruff check src/
   ```
3. `.env` changes if the deploy needs them (backup first, masked grep only):
   ```bash
   cp .env .env.bak-$(date +%Y%m%d)
   grep -E "^(VISION_MODEL|TEXT_MODEL)" .env
   ```
   Current pins: `VISION_MODEL=gemini-2.5-flash-lite` (10 RPM / 20 RPD free tier,
   reset midnight Pacific), `TEXT_MODEL=openai/gpt-oss-120b` (Groq).
4. Restart + verify:
   ```bash
   systemctl --user restart ai-job-filter
   systemctl --user status ai-job-filter --no-pager
   journalctl --user -u ai-job-filter --since "5 min ago" --no-pager | tail -30
   sqlite3 data/jobs.db "SELECT processing_status, COUNT(*) FROM messages GROUP BY 1;"
   ```
   Success = unit `active (running)`, no traceback in logs.
   Note: `PENDING_VISION` draining slowly is NORMAL (worker sleeps 5 min default,
   30 min on sustained 429 circuit breaker). Retry storms every 60s are a bug.

## Rollback

- Code: `git log --oneline -5`, then `git reset --hard <last-good-sha>` + restart daemon.
- `.env`: restore from `.env.bak-*` + restart daemon.
- Never `git reset --hard` blindly — show the user what will be discarded first.

## When to use me

Use this skill when the user asks to deploy, release, update production, or sync
code to the VPS. Ask clarifying questions if the working tree contains changes
outside the deploy scope.
