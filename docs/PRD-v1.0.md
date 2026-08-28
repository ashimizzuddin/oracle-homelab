# AI JOB FILTER — PRD v1.0 (Lite)

**Version:** 1.0
**Date:** 2026-08-28
**Status:** APPROVED — Build Mode
**Owner:** Ashim (solo, RHCSA, target: IT entry-level)

---

## 1. Problem

Telegram job channels mengirim **70+ pesan/hari** campur iklan, repost, loker non-IT, dan loker **IT entry-level** yang relevan. Manual sort = 30 menit/hari. Quality saat ini:

*   Skor `0/100` muncul untuk `NOC Engineer` (harusnya `60-70`).
*   Notifikasi tanpa link klik atau deskripsi (G1, G3b dari 2026-08-24 s/d 28).
*   Hanya 1 board web (SEVIMA) dimonitor padahal `Glints/Tech in Asia/Dealls/KitaLulus` banyak loker IT.

## 2. Goals (dari user awam)

1.  HP hanya dapat notif yang **ada link klik + deskripsi**.
2.  Skor `NOC Engineer / DevOps / SOC` **tidak 0 lagi**.
3.  Cek **11 web IT Indonesia** 1x/hari, otomatis.

## 3. Non-Goals

*   Auto-apply (human apply sendiri).
*   Resume generator.
*   Multi-user / web dashboard (Telegram Bot adalah UI).
*   Paid API fallback (free-first, `GEMINI.md:16`).
*   Jobstreet Indonesia (GraphQL `Disallow`, fragile) & LinkedIn (ToS larang).

## 4. Personas

*   **Ashim** — solo, RHCSA, Linux kuat, target Junior SysAdmin/NOC/SOC, baca Telegram di HP.

## 5. Success Metrics

*   `≥99%` notif punya link klik (Telegram source minimum).
*   `≥80%` notif punya summary/deskripsi ≥50 char.
*   `0` notifikasi skor `<55` sampai ke HP (filter spam).
*   11 web ter-monitor, daily run sukses, tidak ada exception fatal.

---

## 6. User Stories (lite)

*   **US-1**: Ashim buka Telegram → tap notif → langsung ke loker / ke pesan sumber Telegram.
*   **US-2**: Notif `NOC Engineer - Jasnikom Jakarta` muncul skor `65/REVIEW` bukan `0/100`.
*   **US-3**: Pagi hari otomatis cek 11 web, hasil masuk DB, loker baru langsung diskor.

---

## 7. Functional Requirements

### 7.1 Notifikasi (Fase A)

| ID | Aturan | File:line target |
|:--|:------|:--|
| F-NOT-1 | `application_url` null → fallback `https://t.me/c/{source_id}/{msg_id}` | `telegram/notifier.py:73-125` |
| F-NOT-2 | `summary` null/kosong → tampilkan 3 baris pertama `raw_text` (escape HTML) | `telegram/notifier.py:73-125` |
| F-NOT-3 | Gaji `N/A` → sembunyikan baris `$` total | `telegram/notifier.py:73-125` |
| F-NOT-4 | Notif **HANYA** dikirim jika `match_score ≥ MIN_SCORE_REVIEW (55)` | `telegram/handlers.py:25-138`, `telegram/notifier.py:73-125` |
| F-NOT-5 | Header skor: `<emoji> X/100 \| <klasifikasi> \| <title>` | `telegram/notifier.py:73-125` |

### 7.2 Scorer (Fase A2)

| ID | Aturan | File:line target |
|:--|:------|:--|
| F-SCO-1 | Hard-gate: tambah `principal/director/head/vp/chief/cto/cio/ciso` (sudah ada `senior/lead/manager`) | `processing/scorer.py:16-28` |
| F-SCO-2 | `workplace_type` cocok: `["remote","hybrid","onsite","on-site","unknown"]` | `processing/scorer.py:88-91` |
| F-SCO-3 | `min_years_exp == 3, experience_required in {"preferred","plus"}` → +5 poin | `processing/scorer.py:60-66` |

### 7.3 Dedup Image (Fase A3)

| ID | Aturan | File:line target |
|:--|:------|:--|
| F-DED-1 | `media_sha256` & `media_dhash` persist ke DB setelah download | `telegram/handlers.py:79-95` |
| F-DED-2 | `compute_text_hash(normalize_text(raw_text))` bukan raw | `telegram/handlers.py:98`, `processing/pipeline.py:19` |

### 7.4 Web Ingestion (Fase B)

| ID | Aturan | File target |
|:--|:------|:--|
| F-WEB-1 | `BaseFetcher` Protocol di `src/ai_job_filter/web_fetcher/base.py` | new |
| F-WEB-2 | `config/web_fetchers.yaml` daftar 11 board, `enabled`, `interval_h=24`, `delay_seconds=3` | new |
| F-WEB-3 | State di SQLite `fetcher_state(source,last_run_at,seen_slugs_json)`, bukan 11 file JSON | new migration `002_fetcher_state.sql` |
| F-WEB-4 | Scheduler di `main.py`, jalan jam 07:00 daily, delay+jitter | `src/ai_job_filter/main.py` |
| F-WEB-5 | 11 board: Talentics, HiredToday, Dealls, Tech in Asia, KitaLulus, Loker.id (Easy); Glints, Kalibrr, Karir.com, TopKarir (Medium) | `src/ai_job_filter/web_fetcher/*.py` |
| F-WEB-6 | Skip Jobstreet Indonesia & LinkedIn Jobs | this PRD |

---

## 8. Non-Functional

*   **Cost**: Rp 0/bulan (Groq free + Gemini free + SQLite lokal).
*   **Latency**: Notifikasi ≤5 menit dari pesan Telegram. Web run daily jam 07:00 WIB, ≤30 menit.
*   **Reliability**: Crash-recover via `systemd Restart=on-failure`. Web run independen dari Telegram daemon.
*   **Security**: `.env` `chmod 600`, StringSession dirahasiakan, no logs leak API key (SecretStr).

---

## 9. Infra Diagram

```
┌────────────────────────────────────────────────────────────┐
│                        AI JOB FILTER                       │
│                                                            │
│  ┌─────────────────┐         ┌──────────────────────────┐  │
│  │ 11 Web Boards   │         │ Telegram Channels        │  │
│  │ (Easy+Medium)   │         │ (Telethon MTProto)       │  │
│  └────────┬────────┘         └────────────┬─────────────┘  │
│           │ HTTP/sitemap                   │ MTProto        │
│           ▼                                ▼                │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ BaseFetcher (Protocol) + per-board adapter          │  │
│  │ - http_get with tenacity retry                      │  │
│  │ - parse_listing / parse_detail                      │  │
│  │ - build source_text                                 │  │
│  └────────────────────┬────────────────────────────────┘  │
│                       │                                    │
│                       ▼                                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ SQLite (WAL)                                         │  │
│  │ - sources (telegram_id UNIQUE, source_url TEXT)      │  │
│  │ - messages (media_sha256, media_dhash)               │  │
│  │ - jobs (content_hash, score_breakdown)               │  │
│  │ - fetcher_state (source, last_run_at, seen_slugs)    │  │
│  └────────┬─────────────────────────────────────────────┘  │
│           │                                                │
│           ▼                                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Pipeline (existing)                                  │  │
│  │ detector ($0) → dedup ($0) → Groq free              │  │
│  │ → scorer 0-100 → classifier (APPLY≥75, REVIEW≥55)   │  │
│  └────────┬─────────────────────────────────────────────┘  │
│           │ match_score ≥ 55                               │
│           ▼                                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Notifier (Telegram Bot)                              │  │
│  │ - fallback link: t.me/c/{src}/{msg}                  │  │
│  │ - fallback summary: 3 baris raw_text                 │  │
│  │ - sembunyikan gaji kosong                            │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

---

## 10. Cost Sheet (Bulanan)

| Komponen | Penyedia | Tier | Biaya |
|:---------|:---------|:-----|:------|
| LLM Text | Groq Llama 3.3 70B | Free (100K TPD, 1K RPD) | Rp 0 |
| Vision | Gemini 2.5 Flash | Free (1.5K RPD) | Rp 0 |
| Telegram | MTProto + Bot API | Free | Rp 0 |
| Database | SQLite WAL (lokal) | Free | Rp 0 |
| HTTP fetch | Python `httpx` (reuse Groq dep) | Free | Rp 0 |
| Compute | VPS lokal / Oracle Cloud Always Free (opsional) | Free | Rp 0 |
| **Total** | | | **Rp 0** |

**Capacity check:**
*   Telegram 70 pesan/hari × 30% lolos dedup = ~21 jobs/hari via Telegram.
*   Web 11 board × 10 jobs/board/hari = ~110 jobs/hari (setelah dedup).
*   Total: ~131 jobs/hari < Groq 100K TPD ≈ ~90 jobs/hari pada 1.1K tokens/job.
*   **Mitigasi**: scheduler staggering per board, delay 3s+jitter, antrian `PENDING_AI` jika over.

---

## 11. Release Plan

| Tanggal | Hasil | Validasi |
|:--------|:------|:--------|
| **Hari 1** | Fase A: Notif + Scorer + Dedup fixes | `uv run pytest -m "not integration"` 89+ pass; manual test 4 notifikasi existing |
| **Hari 2** | Fase B1: BaseFetcher + fetcher_state + scheduler skeleton | dry-run 1 fetcher Talentics end-to-end |
| **Hari 3** | Fase B2: 6 Easy board wired | dry-run 6 board, cek DB `jobs` bertambah |
| **Hari 4** | Fase B3: 5 Medium board | dry-run semua 11, fix parser |
| **Hari 5** | Fase B4: systemd timer jam 07:00 + symlink + dokumentasi | `DRY_RUN=false` hidup 1 minggu, monitor kualitatif |

---

## 12. Risks & Mitigations

| Risiko | Probabilitas | Mitigasi |
|:-------|:-------------|:---------|
| Groq/Gemini rate limit | Medium | Antrian `PENDING_AI/VISION`, retry setiap jam |
| IP ban board target | Medium | robots.txt respect, delay 3s+jitter, polite UA |
| Board ganti layout HTML | Tinggi | Adapter terisolasi per board; scraper diuji mingguan |
| Web scraping vs ToS | Medium | Hindari Jobstreet/LinkedIn; hanya public listing |
| Cron tidak jalan (VPS mati) | Medium | systemd `Restart=on-failure`; alerting Telegram via Bot |

---

## 13. Open Questions (resolved)

*   ~~Apa yang harus dikirim jika `application_url` kosong?~~ → F-NOT-1: fallback ke `t.me/c/{src}/{msg_id}`.
*   ~~Score threshold minimum notifikasi?~~ → F-NOT-4: `≥55`.
*   ~~Jobstreet & LinkedIn?~~ → Skip, F-WEB-6 confirms.
