---
name: ai-job-filter-deploy
description: Deploy AI Job Filter to the Oracle VPS production daemon (git push/pull via GitHub, .env update, Docker or systemd restart, verification). Use when asked to deploy, release, or sync this project to VPS.
---

# AI Job Filter — VPS Deploy

Production: Oracle VPS `vps-oracle` (129.225.13.217, Ubuntu 24.04 ARM),
path `/home/ubuntu/ai-job-filter`.

**Canonical remote: https://github.com/ashimizzuddin/oracle-homelab.git** (PUBLIC).
Both laptop (`~/tools/AI JOB FILTER`) and VPS have `origin` pointing there.
Git bundle transfer is no longer needed.

Runtime: Docker (`compose.yaml`) — systemd unit `ai-job-filter` kept as fallback only.

## Hard rules (from GEMINI.md, never violate)

- **Free-first, Rp0**: never add paid APIs or billing. Rate limits → PENDING queue, never silent paid fallback.
- **No auto-apply**: human action is always required to apply to jobs.
- **Single daemon**: production runs ONLY on the VPS. Never run the daemon on laptop
  and VPS at the same time (Telegram Conflict / AuthKeyDuplicated).
- **Secrets**: `.env` is gitignored. Never print, commit, or paste secret values.
  Always `cp .env .env.bak-$(date +%Y%m%d)` before editing.
- **Never edit code directly on the VPS.** The repo diverged once this way (Sep 2026):
  laptop and VPS both grew different implementations of the same feature, and
  reconciling them took a full merge session. Edit on the laptop, commit, push, pull.

## Deploy flow

### A. On laptop

```bash
cd ~/tools/"AI JOB FILTER"
git status --short          # review every changed file first
git pull --ff-only          # in case the VPS pushed something
git add <intended files only>
git commit -m "<concise message matching repo style>"
.venv/bin/python -m pytest tests/ -q     # expect 104 passed, 2 skipped
.venv/bin/python -m ruff check src/ scripts/   # expect All checks passed
git push origin main
```

### B. On VPS

```bash
ssh vps-oracle
cd /home/ubuntu/ai-job-filter
git status --short          # must be empty; if not, STOP and ask the user
git pull --ff-only origin main
```

Then pick the runtime:

**Docker (primary):**

```bash
docker compose build            # ARM-native build
docker compose up -d
docker compose logs -f --tail=50
```

**systemd fallback (only if Docker is broken):**

```bash
systemctl --user stop ai-job-filter 2>/dev/null
.venv/bin/python -m pytest tests/ -m "not integration" -q   # expect 104 passed
systemctl --user start ai-job-filter
systemctl --user status ai-job-filter --no-pager
```

### C. Verify (both runtimes)

```bash
docker compose ps               # or: systemctl --user status ai-job-filter
docker compose logs --tail=30   # or: journalctl --user -u ai-job-filter --since "5 min ago"
sqlite3 data/jobs.db "SELECT processing_status, COUNT(*) FROM messages GROUP BY 1;"
```

Success = container/unit up, no traceback in logs, Telegram notification arrives.
`PENDING_VISION` draining slowly is NORMAL (worker backoff 15 min, 30 min on sustained
429 circuit breaker). Retry storms every 60s are a bug.

### D. Runtime notes

- `.env` is injected via `env_file` — never baked into the image.
- Volumes: `./data` (jobs.db + gemini_budget.json), `./downloads` (media),
  `./candidate_profile.yaml` and `./config/web_fetchers.yaml` mounted `:ro` so
  they can be edited without a rebuild.
- Container `restart: unless-stopped` replaces systemd `Restart=on-failure`.
- Log rotation is capped in `compose.yaml` (`max-size: 10m`, `max-file: 3`).

## Rollback

- Code: `git log --oneline -5`, then `git reset --hard <last-good-sha>` + restart.
- `.env`: restore from `.env.bak-*` + restart.
- Docker image: `docker compose down && docker compose up -d` after checking out the old SHA and rebuilding.
- Never `git reset --hard` blindly — show the user what will be discarded first.

## Housekeeping (disk hygiene)

Docker accumulates layers. Keep this cron on the VPS:

```bash
docker system prune -af --volumes    # careful: removes all unused images/volumes
```

## When to use me

Use this skill when the user asks to deploy, release, update production, or sync
code to the VPS. Ask clarifying questions if the working tree contains changes
outside the deploy scope.
