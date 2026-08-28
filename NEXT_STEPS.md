# AI JOB FILTER — Status & Next Steps (2026-08-28, post-PRD v1.0)

## Status saat ini
- Daemon live via systemd user unit `ai-job-filter.service` (DRY_RUN=true)
- **104 tests passing** (89 lama + 15 baru: web_fetcher + notif threshold)
- PRD v1.0 approved: `docs/PRD-v1.0.md` (Fase A notif fix + Fase B web ingestion)
- Commit: Fase A (scorer/notifier/dedup/main fixes) + Fase B (web_fetcher/*)

## Yang sudah dikerjakan hari ini (28 Aug 2026)

### Fase A — Fix Notifikasi (PRD section 7.1-7.3)
- ✅ Notifier fallback: link `t.me/c/{src}/{msg}` saat `application_url` kosong,
  summary dari 3 baris raw_text, gaji kosong disembunyikan (F-NOT-1/2/3)
- ✅ Notifikasi HANYA jika skor ≥55 (F-NOT-4) — HP tidak spam lagi
- ✅ Scorer hard-gate lengkap (9 kata senior, F-SCO-1), `on-site`/`onsite`
  diterima (F-SCO-2), 3-tahun-preferred → +5 poin (F-SCO-3)
- ✅ dHash/SHA-256 gambar persist ke DB (F-DED-1) — dedup image tidak hilang lagi
  saat restart
- ✅ content_hash pakai `normalize_text()` (F-DED-2) — dedup text konsisten
- ✅ Retry worker pakai `score_and_save_job` (bukan `content_hash="retried"`)
- ✅ `candidate_profile.yaml` gagal load → error log jelas (bukan silent fallback)
- ✅ `update_message_status` pakai write_lock (SQLite race fix)
- ✅ Verifikasi: `NOC Engineer - Lima Menara Bintang` sekarang **55/REVIEW**
  (dulu 0/100)

### Fase B — Web Ingestion (PRD section 7.4)
- ✅ `src/ai_job_filter/web_fetcher/` — BaseFetcher + registry + scheduler
- ✅ State di SQLite `fetcher_state` (migration 002) — bukan file JSON
- ✅ 10 fetcher class dibuat; **Dealls & KitaLulus live-verified** (dry-run +
  execute 1 kandidat via Groq sukses: `Business Development` 36/IGNORE)
- ⚠️ Disabled sementara (live-check 28 Aug): `hiredtoday` (sitemap 404 stale),
  `lokerid` (403 bot protection), `talentics` (API butuh auth)
- ✅ Scheduler harian jam 07:00 terintegrasi daemon (`main.py` web_scheduler)
- ✅ CLI manual: `uv run python scripts/run_web_fetchers.py [--execute] [--only X]`
- ✅ Skip Jobstreet & LinkedIn sesuai keputusan (robots/ToS)

## Next steps
1. **Aktifkan daemon**: `DRY_RUN=false` → `systemctl --user restart ai-job-filter`
2. **Symlink fix** (spasi dirname merusak systemd): `ln -s ~/tools/"AI JOB FILTER" ~/tools/ai-job-filter`
3. Install unit baru: `cp docs/ai-job-filter.service ~/.config/systemd/user/ && systemctl --user daemon-reload`
4. **Oracle Cloud Always Free** (Batam/Singapore ARM 2c/12GB) sebagai VPS 24/7
   — fallback RackNerd BF (~$11/thn)
5. Migrasi VPS: rsync proyek + .env + data/jobs.db → pasang unit systemd sama
6. **Evaluasi 1 minggu**: kualitas alert, false positive, Groq quota (~131
   jobs/hari vs 100K TPD), Glints/Kalibrr/Karir/TopKarir live-check
7. Re-enable hiredtoday/lokerid/talentics jika proteksi longgar

## Catatan teknis
- SEVIMA fetcher butuh playwright: pakai /tmp/scraper-venv (sementara) atau
  buat venv permanen
- Web fetcher state sekarang di DB — tabel `fetcher_state`, aman race
- Dealls parsing via `__NEXT_DATA__ dehydratedState.queries[0].state.data`
  (fragile jika Next.js restructure — cek mingguan)
- KitaLulus: nested sitemap, hanya sitemap-jobs pertama per run (rotasi via
  state); pola title: "Info Lowongan {role} di {company} area {loc} | Kitalulus"
- Port 25 outbound diblokir ISP (tidak bisa kirim email langsung)

## Reminder
USER MINTA DIINGATKAN langkah-langkah di atas via Telegram saat buka laptop
berikutnya.

## Migrasi VPS — SELESAI (2026-08-28)

**VPS Oracle PAYG `ubuntu@129.225.13.217` sekarang SATU-SATUNYA daemon aktif (24/7, Rp 0).**

| Item | Status |
|---|---|
| Kode VPS | `10341a8` (Fase A + B ter-sync via git bundle) |
| Deps | `uv sync` ARM OK, 104 tests pass |
| `.env` | Session string BARU (session lama invalid oleh Telegram — AuthKeyDuplicated), channels di-trim ke 3 (@LowonganKerjaIT, @joinkerjatalenthub, @devopsindonesia); backup: `.env.bak-20260828` |
| Listener | ✅ connected, 0 Conflict |
| Web scheduler | ✅ 8 boards, jadwal harian 07:00 (server time UTC — cek `journalctl` bila perlu) |
| Notif test | ✅ sendMessage OK dari VPS |
| anti-idle cron | ✅ tetap jalan (jangan dihapus — jaga instance Oracle dari reclaim) |

### Konfigurasi penting VPS
- Unit: `~/.config/systemd/user/ai-job-filter.service` (WorkingDirectory=%h/ai-job-filter, tanpa symlink)
- Python: `.venv` 3.14 via uv aarch64
- Linger=yes (jalan tanpa login)

### Laptop lokal
- Daemon: `disabled` + tidak ada proses — JANGAN di-enable lagi kalau tidak mau Conflict
- Boleh dipakai untuk development; sync ke VPS via `git bundle` + scp (lihat pola migrasi)

### Rollback (darurat)
```bash
# VPS
cd ~/ai-job-filter && git reset --hard e3cc311 && systemctl --user restart ai-job-filter
# Lokal (balikin daemon ke laptop)
systemctl --user enable --now ai-job-filter
```
