# AI JOB FILTER — Status (2026-09-11)

## Status Produksi

- **Daemon**: Docker container `ai-job-filter` di Oracle VPS (129.225.13.217)
  - Runtime: `docker compose up -d`, restart policy `unless-stopped`
  - Image: `ai-job-filter:latest` (python:3.12-slim + uv, 115MB)
  - Systemd unit `ai-job-filter.service` → DISABLED (fallback saja)
- **Repo**: https://github.com/ashimizzuddin/oracle-homelab (PUBLIC)
  - Laptop: `~/tools/AI JOB FILTER` | VPS: `~/ai-job-filter`
  - Deploy: laptop → commit → push → `git pull --ff-only` di VPS → `docker compose up -d --build`
- **Tests**: 104 passed, 2 skipped (ruff: All checks passed)
- **DB**: `data/jobs.db` — 1119 NOT_JOB, 554 PENDING, 338 DUPLICATE, 309 PROCESSED

## Fitur Live

- Telegram listener: @LowonganKerjaIT, @joinkerjatalenthub, @devopsindonesia
- Web scheduler: 8 board (talentics, dealls, techinasia, kitalulus, glints, kalibrr, karircom, topkarir) — tiap hari jam 07:00 UTC
- Scoring: MIN_SCORE_APPLY=65, MIN_SCORE_REVIEW=40 (tuned 10 Sep)
- Vision: Gemini gemini-3.5-flash-lite + text-first (caption ≥500 char pakai Groq)
- Retry worker: 15 min backoff, 7s pacing, 30 min circuit breaker

## Rollback

```bash
# Ke systemd (jika container bermasalah):
docker compose down
systemctl --user start ai-job-filter

# Ke commit lama:
git log --oneline -5
git reset --hard <sha>
docker compose up -d --build
```

## Next (Fase 3 — GitHub Actions CI/CD)

- [ ] `.github/workflows/ci.yml`: ruff + pytest ARM di setiap push
- [ ] Build image ARM via `docker buildx` di CI
- [ ] Badge status di README

## Housekeeping

- Prune mingguan: `~/docker-prune.sh` (cron Minggu 03:30 UTC)
- Log: `docker compose logs -f --tail=50`
- Backup DB: `~/backups/` (snapshot pre-Docker tersedia)
