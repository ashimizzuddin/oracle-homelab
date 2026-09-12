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

✅ **SELESAI** — `.github/workflows/ci.yml`: ruff + pytest ARM, build image ARM64, push ke GHCR, badge di README.

## Housekeeping

Prune mingguan: `~/docker-prune.sh` (cron Minggu 03:30 UTC)
Log: `docker compose logs -f --tail=50`
Backup DB: `~/backups/` (snapshot pre-Docker + pre-refilter tersedia)

---

## 2026-09-12 — Pembersihan data non-IT

**Masalah:** 65% tabel `jobs` bukan lowongan IT. `dealls` dan `kitalulus` memakai
sitemap seluruh-situs tanpa dimensi kategori, dan kode mengambil 25 URL pertama
dari ~2496 URL — jadi yang masuk adalah 25 lowongan acak.

**Akar tambahan:** key `options.category_path`, `options.specialization`, dan
`options.keywords` di `config/web_fetchers.yaml` **tidak pernah dibaca kode mana pun** —
setting kategori itu hanya dekorasi.

**Perbaikan:**
- `src/ai_job_filter/web_fetcher/relevance.py` — classifier IT tanpa LLM (0 biaya kuota)
- `BaseFetcher.run()` menerapkan filter via flag `it_only` (default true)
- `max_items` sekarang batas kandidat DITERIMA, bukan jumlah fetch mentah
- `scripts/refilter_web_jobs.py` — bersihkan data lama, tidak menghapus apa pun
- kitalulus: jalan melalui 4 dari 148 sitemap per run dengan kursor rotasi

**Hasil di produksi:** 531 dari 579 baris web ditandai IGNORE. Sisa 48 lowongan IT.
Data 890 baris tetap utuh (bisa dibalik).

**Board dinonaktifkan** (diprobe live, semuanya menghasilkan 0):
`glints` (sitemap 404 + SPA), `kalibrr` (URL 404), `karircom` (shell JS 4.6 KB),
`topkarir` (timeout).

**Rollback:**
```bash
git revert <sha>
docker compose up -d --build
# DB: pakai snapshot di ~/ai-job-filter/backups/jobs-pre-refilter-*.db
```
