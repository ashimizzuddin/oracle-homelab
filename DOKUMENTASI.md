# DOKUMENTASI LENGKAP — AI JOB FILTER

```
┌─────────────────────────────────────────────────────────────────┐
│ Lokasi          : /home/ashim/tools/AI JOB FILTER               │
│ Mirror produksi : VPS Oracle ubuntu@129.225.13.217              │
│                   (~/ai-job-filter, daemon systemd 24/7)        │
│ Asal            : Dibuat dari nol oleh Ashim, dibantu AI agent  │
│                   (Antigravity/Gemini + opencode)               │
│ Pembuat         : Ashim — pemilik akun Telegram & pembayar kuota│
│ Versi           : 0.1.0 (29 commit, semua bulan Agustus 2026)   │
│ Tanggal analisis: 28 Agustus 2026                               │
│ Bahasa          : Python 3.14 (lokal) / 3.12 (VPS)              │
│ Ukuran kode     : 6.516 baris Python (src+scripts+tests)        │
│ Lisensi         : tidak ada file LICENSE                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 1. PERINGATAN DI DEPAN

Ada tiga hal yang perlu Anda tahu sebelum membaca lebih jauh.

**Satu — ada file berisi kunci akun Telegram di folder ini.**
File `.env` memegang `TELEGRAM_SESSION_STRING`. Orang yang memegang
teks itu bisa masuk akun Telegram pemilik tanpa perlu password atau kode
verifikasi. File ini tidak ikut ke git (sudah diverifikasi), tapi tetap
berada sebagai teks biasa di dua mesin: laptop dan VPS. Risikonya adalah
siapa pun yang bisa membaca file di salah satu mesin itu, menguasai akun
Telegram.

**Dua — bot ini sedang hidup di VPS dan memakai jatah gratis layanan AI.**
Ekstraksi lowongan memakai akun gratis Groq dan Gemini. Syarat layanan
Gratis Gemini menyebut data yang dikirim bisa dipakai untuk melatih model.
Data yang dikirim berisi teks lowongan kerja dari kanal publik, jadi
tingkat kepekatannya rendah, tapi ini tetap perlu diketahui.

**Tiga — ada satu temuan waktu yang salah.**
Jadwal pemantauan web diset "jam 7". VPS memakai zona waktu UTC.
Jam 7 UTC = jam 14:00 WIB (sore). Dokumentasi internal menulis
"07:00" seolah pagi. Ini tidak merusak apa pun, tapi kalau pemilik
berharap notif pagi, dia akan kecewa. Rincian di bagian 8.

---

## 2. RINGKASAN SATU PARAGRAF

Bayangkan Anda menyewa seorang asisten pribadi yang duduk di depan
Telegram 24 jam sehari. Tugasnya satu: membaca setiap pesan di beberapa
grup lowongan kerja, memilah mana lowongan sungguhan dan mana sampah
(iklan, repost, lowongan senior yang tidak relevan), lalu mengetuk bahu
Anda lewat bot Telegram hanya kalau lowongannya layak dilamar. Asisten
ini tidak dibayar uang — dia dibayar dengan "jatah gratis" dari dua
perusahaan AI (Groq dan Google Gemini) yang memberi kuota harian tanpa
biaya. Otak asisten ini bukan AI yang menilai "bagus atau tidak" —
penilaiannya kaku dan bisa dijelaskan (sistem poin 0–100 dengan aturan
tetap), AI hanya dipakai untuk membaca teks lowongan yang berantakan dan
mengubahnya jadi data rapi. Semuanya berjalan di dua tempat: laptop
(tempat kode dibuat) dan sebuah VPS Oracle gratis yang hidup terus
(tempat kode bekerja setiap hari).

---

## 3. KAMUS ISTILAH

| Istilah | Artinya (versi awam) |
|---|---|
| **Telegram Bot API** | Jalur resmi untuk membuat "robot" yang bisa kirim/baca pesan Telegram atas nama bot, bukan akun manusia |
| **MTProto / Telethon** | Jalur lain untuk masuk Telegram *sebagai akun manusia*. Telethon = pustaka Python untuk ini |
| **StringSession** | Teks panjang yang mewakili "sesi login" akun Telegram. Sama nilainya dengan password |
| **Groq** | Perusahaan yang menyewakan model AI (Llama) dengan kuota gratis besar. Dipakai untuk membaca teks |
| **Gemini Flash** | Model AI dari Google yang bisa membaca *gambar*. Dipakai untuk poster lowongan berupa gambar |
| **SQLite** | Database dalam satu file. Semua data lowongan tersimpan di `data/jobs.db` |
| **WAL mode** | Mode SQLite yang membolehkan baca & tulis bersamaan tanpa saling menunggu |
| **Pydantic** | Pustaka yang mengecek "apakah data ini bentuknya benar" sebelum dipakai |
| **dHash** | Sidik jari visual gambar. Gambar yang mirip = sidik jari yang mirip, walau ukuran beda |
| **RapidFuzz** | Pustaka penghitung kemiripan dua teks (misal "Loker IT" vs "loker it" = mirip) |
| **systemd user unit** | Pengatur "program jalan otomatis" di Linux, punya user biasa, tidak perlu root |
| **Linger** | Pengatur systemd agar program user tetap hidup walau pemiliknya tidak login |
| **VPS** | Virtual Private Server — komputer sewaan yang menyala 24 jam, di sini punya Oracle |
| **Oracle PAYG / anti-idle** | Oracle Cloud "Pay As You Go" bisa di-reclaim kalau CPU+RAM terlalu diam. Script `anti_idle.py` sengaja memanaskan CPU tiap 6 jam supaya tidak diambil |
| **Free tier** | Jatah pemakaian gratis dengan batas. Kalau habis, tidak menagih — hanya menolak sementara |
| **429** | Kode HTTP "terlalu banyak permintaan" — tanda kuota gratis kena batas |
| **Dead code** | Kode yang ditulis lengkap tapi tidak pernah dipakai di mana pun |
| **UV** | Pengelola paket Python yang cepat, pengganti pip |

---

## 4. ISI FOLDER — FILE PER FILE

### 4.1 Pohon direktori

```
AI JOB FILTER/
├── .env                          ← KREDENSIAL (tidak ikut git, chmod 600)
├── .env.example                  ← template .env tanpa nilai (ikut git)
├── .gitignore                    ← daftar file yang disembunyikan dari git
├── .pre-commit-config.yaml       ← pemeriksa otomatis sebelum commit
├── .python-version               ← "3.14"
├── pyproject.toml                ← konfigurasi project & dependensi
├── uv.lock                       ← kunci versi paket (deterministik)
├── README.md                     ← ringkasan resmi
├── GEMINI.md                     ← aturan untuk AI agent (bukan dok teknis)
├── NEXT_STEPS.md                 ← jurnal status + catatan migrasi VPS
├── candidate_profile.yaml        ← PROFIL PENCARI KERJA (inti penilaian)
├── ai_job_filter.db              ← FILE KOSONG 0 byte (sisa eksperimen)
├── config/
│   └── web_fetchers.yaml         ← daftar 10 situs lowongan dipantau
├── data/
│   └── jobs.db                   ← DATABASE UTAMA (lokal: 56 job, 208 msg)
├── docs/
│   ├── PRD-v1.0.md               ← dokumen kebutuhan (approved)
│   ├── architecture-decision-record-v1.1.md  ← ADR draft (1392 baris)
│   ├── architecture-decision-record-v1.2.md  ← ADR approved (1460 baris)
│   ├── HANDOFF.md                ← ❌ KADALUWARSA (bilang "belum diimplement")
│   └── ai-job-filter.service     ← unit systemd (untuk VPS)
├── migrations/
│   ├── 001_initial_schema.sql    ← 175 baris, skema lengkap + trigger + index
│   └── 002_fetcher_state.sql     ← 9 baris, tabel status web fetcher
├── scripts/
│   ├── evaluate_extraction.py    ← 65 baris, uji manual Groq (4 contoh)
│   ├── generate_session.py       ← 38 baris, buat StringSession (interaktif)
│   ├── ingest_web_candidate.py   ← 388 baris, adapter "candidate JSON → DB"
│   ├── rebuild_job.py            ← 104 baris, CLI rebuild 1 job
│   ├── reprocess.py              ← 92 baris, CLI ulangi pesan gagal
│   ├── run_web_fetchers.py       ← 74 baris, CLI jalankan web fetcher
│   ├── sevima_fetcher.py         ← 245 baris, fetcher career.sevima.com
│   └── sevima_seen.json          ← status slugs terlihat (3 slugs)
├── src/ai_job_filter/            ← 3.297 baris kode inti
│   ├── main.py                   ← 183, titik masuk + retry_worker + scheduler
│   ├── config.py                 ← 52, baca .env via pydantic-settings
│   ├── rebuild.py                ← 160, logika rebuild job
│   ├── reprocess.py              ← 182, logika reprocess pesan gagal
│   ├── models/                   ← job.py 113, candidate.py 20, enums.py 34
│   ├── db/                       ← connection 17, repository 266, migrations 38
│   ├── processing/               ← pipeline inti (6 modul, 412 baris)
│   ├── providers/                ← Groq 85 + Gemini 72 + base/errors/prompts
│   ├── telegram/                 ← listener 131, handlers 151, notifier 174
│   └── web_fetcher/              ← base 193, easy 379, medium 221,
│                                    registry 70, scheduler 169
├── test_fixtures/                ← 21 JSON contoh lowongan nyata
│                                    (Stripe, Bugcrowd, Supabase, dll —
│                                     SEMUA dari luar negeri, 0 Indonesia)
├── tests/                        ← 17 file test, 2.424 baris, 104 test
├── downloads/                    ← 3 foto dari Telegram (sisa uji coba)
└── .venv/                        ← lingkungan Python (tidak ikut git)
```

### 4.2 Bedah file penting

**`candidate_profile.yaml` (38 baris) — "siapa yang mencari kerja"**
Isinya: 0 tahun pengalaman profesional, sertifikasi RHCSA, kuat di
Linux/System Administration/RHEL/Networking/VMware/Kali/Bash, arah karir
Cybersecurity/SOC/Pentest, target posisi junior (Junior Sysadmin, NOC,
IT Support, Junior SOC Analyst, dll). File ini dibaca scorer untuk
menghitung skor kecocokan. Mengubah file ini langsung mengubah hasil
rekomendasi.

**`src/ai_job_filter/processing/scorer.py` (126 baris) — "otak penilaian"**
Ada dua bagian: (1) gerbang tegas — kalau judul mengandung kata senior
(senior/lead/principal/manager/director/head of/vp/chief/cto/cio/ciso),
langsung skor 0 dan tidak dinotif; kalau minta 3+ tahun "required", juga
0. (2) skor berbobot 100 poin: kecocokan judul 30, kesesuaian skill 25,
kecocokan pengalaman 20, arah karir 15, faktor praktis 10. Skor ≥75 =
APPLY, 55–74 = REVIEW, <55 = IGNORE (tidak dinotif).

**`src/ai_job_filter/telegram/listener.py` (131 baris) — "telinga"**
Pakai Telethon masuk sebagai akun manusia. Fungsi `sync_history` membaca
riwayat pesan lama (24 jam ke belakang, maksimal 500). Setelah itu
mendaftarkan handler pesan baru secara realtime. Setiap pesan diteruskan
ke `handlers.py`.

**`src/ai_job_filter/telegram/handlers.py` (151 baris) — "otak kecil per pesan"**
Alur: masukkan pesan ke DB (idempoten — pesan sama tidak diproses dua
kali) → cek apakah "berbau lowongan" → kalau ada gambar, unduh, hitung
dHash & SHA-256, simpan ke DB, cek duplikat → cek duplikat teks →
kirim ke Groq (teks) atau Gemini (gambar) untuk ekstraksi → kirim ke
scorer → simpan job → trigger notif kalau layak.

**`src/ai_job_filter/db/repository.py` (266 baris) — "pintu satu-satunya ke database"**
Semua tulisan DB lewat sini. Ada `asyncio.Lock` (`write_lock`) yang
menjadikan tulisan serial. Ini hasil bugfix nyata: sebelumnya dua
koroutine menulis bersamaan menyebabkan error "cannot commit transaction
- SQL statements in progress".

**`src/ai_job_filter/web_fetcher/` (1.032 baris) — "kaki yang jalan ke web"**
`base.py` = template abstrak (HTTP + delay + jitter + state di DB).
`easy.py` = 6 fetcher (Talentics, HiredToday, Dealls, TechInAsia,
KitaLulus, LokerId). `medium.py` = 4 fetcher (Glints, Kalibrr, Karir.com,
TopKarir). `registry.py` = baca `config/web_fetchers.yaml`. `scheduler.py`
= loop harian. Konfigurasi membolehkan 10 board, 2 di antaranya
dimatikan (loker.id dan hiredtoday) karena situsnya memblokir/maty.

**`scripts/ingest_web_candidate.py` (388 baris) — "penerjemah JSON ke DB"**
Menerima satu file JSON berisi lowongan (dari fetcher), mengecek bentuknya,
lalu memasukkan lewat jalur yang sama seperti pesan Telegram. Memiliki
mode dry-run (tidak menulis DB) sebagai default.

**`scripts/sevima_fetcher.py` (245 baris) — "pionir web fetcher"**
Fetch career.sevima.com (lowongan di perusahaan SEVIMA). Butuh Playwright
(browser headless) karena halamannya dirender JavaScript. Tersimpan state
di `scripts/sevima_seen.json`. Ini sebelum ada `web_fetcher/`, jadi
arsitekturnya tidak seragam — jadi catatan di bagian 8.

**`migrations/001_initial_schema.sql` (175 baris) — "denah database"**
4 tabel: `sources` (kanal dipantau), `messages` (pesan mentah),
`jobs` (lowongan terstruktur + skor), `notifications` (notif terkirim +
aksi user). Plus 1 tabel virtual FTS5 (`jobs_fts`) untuk pencarian teks
penuh, 3 trigger yang menjaga FTS5 tetap sinkron, dan 8 index.

**`config/web_fetchers.yaml` — "daftar situs yang dipantau"**
10 board dengan tier easy/medium. Talentics punya API tapi ternyata
butuh auth (temuan, lihat bagian 8). HiredToday & LokerId di-comment
`enabled: false` dengan alasan (sitemap stale, bot protection).

**`GEMINI.md` — "aturan untuk AI agent"**
Bukan dokumentasi teknis untuk manusia. Ini diberikan ke AI agent
(Antigravity/Gemini) sebagai konteks: jangan pakai API berbayar diam-diam,
jangan auto-apply, jangan invent pengalaman. Menarik karena file ini
adalah cara pemilik "melatih" AI agent untuk mengerjakan project.

**`docs/HANDOFF.md` — ❌ KADALUWARSA**
Baris kedua masih menulis *"Application code has NOT been implemented
yet"*. Kenyataannya aplikasi sudah jalan di produksi VPS selama berminggu-
minggu. Dokumen ini menyesatkan siapa pun yang membacanya pertama kali.

**`.env` — kredensial, tidak di-commit**
20 key, semuanya penting:
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` — identitas aplikasi Telegram
- `TELEGRAM_SESSION_STRING` — **kunci akun penuh** (setara password)
- `TELEGRAM_BOT_TOKEN` — kunci bot waktunyokerjabot
- `USER_CHAT_ID`, `AUTHORIZED_USER_ID` — tujuan notif + otorisasi tombol
- `GROQ_API_KEY`, `GEMINI_API_KEY` — kunci free tier AI
- sisanya konfigurasi (model, threshold, channels, dll)

Diverifikasi: tidak ada satu pun nilai ini di git (`git ls-files |
grep .env` = kosong), `chmod 600` diterapkan di kedua mesin.

---

## 5. DIAGRAM 1 — PETA HUBUNGAN

```
                         ┌──────────────────────┐
                         │   Telegram Cloud     │
                         └──────────┬───────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼ MTProto             ▼ Bot API             ▼ Bot API
     ┌─────────────────┐    ┌───────────────┐    ┌───────────────┐
     │ 3 channel grup  │    │ bot           │    │ HP Ashim      │
     │ lowongan kerja  │    │ waktunyokerjab│    │ (target akhir)│
     │ (publik)        │    │ (pengirim)    │    │               │
     └────────┬────────┘    └───────▲───────┘    └───────▲───────┘
              │                     │                    │
              │ pesan mentah        │ notif              │ notif + tombol
              ▼                     │                    │
   ╔════════════════════════════════╧════════════════════╧════╗
   ║           AI JOB FILTER (VPS Oracle, 24/7)                ║
   ║  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  ║
   ║  │ Telethon     │   │ Pipeline     │   │ Notifier     │  ║
   ║  │ listener     │──►│ deteksi/dedup│──►│ skor ≥55     │  ║
   ║  └──────────────┘   │ ekstraksi    │   └──────────────┘  ║
   ║  ┌──────────────┐   │ scoring      │   ┌──────────────┐  ║
   ║  │ Web fetcher  │──►│              │   │ SQLite       │  ║
   ║  │ 8 situs      │   └──────┬───────┘   │ data/jobs.db │  ║
   ║  └──────┬───────┘          │           └──────────────┘  ║
   ╚═════════╪══════════════════╪═════════════════════════════╝
             │                  │
             │ HTTP (scrape)    │ HTTPS (API call)
             ▼                  ▼
   ┌──────────────────┐  ┌─────────────────────────────┐
   │ Situs lowongan:  │  │ Groq API (teks → JSON)      │ ← korban kuota
   │ Dealls ✅        │  │ Gemini API (gambar → JSON)  │ ← korban kuota
   │ KitaLulus ✅     │  └─────────────────────────────┘
   │ Glints ✅        │
   │ Karir.com ✅     │       Korban = pihak yang memberi
   │ TopKarir ✅      │       sumber data / jatah gratis.
   │ TechInAsia ✅    │       Situs lowongan "dikeruk" isinya.
   │ Talentics ⚠️     │       Groq/Gemini memberi kuota gratis
   │ HiredToday ⛔    │       dengan syarat data bisa dipakai
   │ Loker.id ⛔      │       melatih model (Gemini free tier).
   └──────────────────┘
```

Legend: ✅ aktif, ⚠️ aktif tapi bermasalah, ⛔ dimatikan.

---

## 6. DIAGRAM 2 — ALUR SATU PESAN DARI AWAL SAMPAI SELESAI

```
MULAI
  │
  ▼
┌──────────────────────────────────────────────────────────┐
│ (1) Pesan baru masuk dari channel Telegram               │
│     listener.py:75-86 (event handler realtime)           │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ (2) Masukkan pesan ke DB (idempoten)                     │
│     handlers.py:38-44 → repository.insert_message        │
│     Kalau sudah ada → stop (return)                      │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ (3) Deteksi "berbau lowongan?"                           │
│     detector.py:31-43 (regex kata kunci ID/EN, $0)       │
│     Kalau ada gambar → LANGSUNG lanjut (tidak cek teks)  │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ (4) Kalau ada gambar: unduh + hitung dHash               │
│     handlers.py:57-95                                    │
│     Simpan hash ke DB (biar restart tidak kehilangan)    │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ (5) Cek duplikat gambar (dHash ≤5 bit beda)              │
│     handlers.py:97-107 + repository.find_message_by_dhash│
│     Duplikat → status DUPLICATE → stop                   │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ (6) Cek duplikat teks (SHA-256 teks ternormalisasi)      │
│     handlers.py:110-116                                  │
│     Duplikat → status DUPLICATE → stop                   │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ (7) EKSTRAKSI AI ◄── LANGKAH PALING KRUSIAL              │
│     Teks   → Groq Llama 3.3 70B   (extractor.py)         │
│     Gambar → Gemini 2.5 Flash     (vision.py)            │
│     Output: JSON terstruktur (judul, gaji, skill, dll)   │
│     Kalau kena 429 (kuota) → PENDING_AI (diulang nanti)  │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ (8) Dedup level-job (judul+perusahaan+lokasi ≥85/80/75)  │
│     pipeline.py:18-23 + dedup.py:36-60                   │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ (9) HITUNG SKOR 0-100                                    │
│     scorer.py:34-118 (gerbang tegas + 5 komponen)        │
│     ≥75 = APPLY │ 55-74 = REVIEW │ <55 = IGNORE          │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ (10) Simpan job ke DB                                    │
│      pipeline.py:26-55 (semua kolom + score breakdown)   │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│ (11) Kalau APPLY/REVIEW → kirim notif Telegram ke HP     │
│      notifier.py:113-125 (dengan fallback link+summary)  │
│      + tombol [Apply][Save][Skip]                        │
└────────────────────────┬─────────────────────────────────┘
                         ▼
                       SELESAI
```

---

## 7. BEDAH TEKNIS PALING MENARIK

### 7.1 Cara menghitung "kemiripan dua gambar" tanpa AI

Dua poster lowongan yang sama sering dikirim ulang di banyak grup dengan
ukuran/kualitas berbeda. Mencocokkan byte-per-byte tidak akan pernah
cocok. Solusinya dHash (difference hash):

1.  Ubah gambar jadi hitam-putih, perkecil jadi 9×8 piksel.
2.  Bandingkan tiap piksel dengan tetangga kanannya. Lebih terang = 1,
    lebih gelap = 0. Hasilnya 64 bit.
3.  Dua gambar mirip = bit-nya hanya beda sedikit (hitung hamming
    distance, ≤5 dianggap sama).

Ini murah (mikrodetik), tidak butuh AI, dan berhasil menangkap poster
yang dikompres ulang. Kode di `src/ai_job_filter/processing/image_hash.py`
(44 baris, hanya pakai Pillow).

### 7.2 Cara "menyewa otak" tanpa bayar

Groq memberi kuota gratis 1.000 request/hari dan 100.000 token/hari untuk
model Llama 3.3 70B. Gemini memberi 1.500 request/hari untuk vision.
Sistem ini menahan diri supaya tidak melebihi:

-   Filter lokal dulu (regex) — 60-80% pesan dibuang tanpa menyentuh AI.
-   Dedup 4 lapis sebelum AI — pesan sama tidak dihitung dua kali.
-   Kalau tetap kena 429 → pesan masuk status `PENDING_AI`, sebuah
    loop di `main.py:25-94` mengulanginya tiap menit sampai kuota reset.

Hasilnya biaya bulanan tetap Rp 0.

### 7.3 Cara menilai lowongan tanpa "pendapat AI"

Skor tidak dihitung AI. AI hanya mengubah teks berantakan jadi data
terstruktur. Penilaian murni Python deterministik:
-   fuzzy match (RapidFuzz) judul lowongan vs daftar `target_roles`
-   substring match skill lowongan vs `strong_technical_areas`
-   logika if-else untuk pengalaman (0 th = 20 poin, 3 th "preferred" = 5)
-   kata kunci cybersecurity untuk arah karir

Kenapa penting: kalau AI yang menilai, hasilnya bisa berubah-ubah
(nondeterministik) dan sulit dijelaskan. Dengan cara ini, kenapa sebuah
lowongan dapat skor 62 bisa dibedah komponen per komponen.

### 7.4 Cara database SQLite tetap aman dari dua penulis

Satu koneksi SQLite dipakai bersama oleh listener realtime dan retry
worker background. SQLite sendiri tidak boleh punya dua transaksi
bersamaan di satu koneksi. Solusinya: semua metode tulis membungkus
dirinya dengan `asyncio.Lock`. Ini hasil bug nyata (commit `4390696`),
bukan rekayasa di atas kertas.

---

## 8. TEMUAN YANG TIDAK TERLIHAT DARI README

1.  **Jadwal web fetcher sebenarnya jam 14:00 WIB, bukan 07:00.**
    `scheduler.py:11` set `DEFAULT_RUN_HOUR = 7`. VPS `timedatectl`
    menunjukkan `Time zone: Etc/UTC`. Jam 7 UTC = 14:00 WIB. Log VPS
    mengonfirmasi: `next run at=2026-08-29T07:00:00` dihitung pakai
    `datetime.now()` server yang UTC. Dokumentasi internal (`NEXT_STEPS.md`,
    `PRD-v1.0.md`) menulis "07:00 WIB" — itu tidak akurat.

2.  **Talentics "official API" ternyata butuh login.**
    `config/web_fetchers.yaml` dan PRD menulis Talentics punya API
    publik `GET https://api.talentics.id/v2/jobs`. Diuji langsung:
    response `401 Unauthorized` dengan body
    `{"message":"Unauthorized"}`. Fetcher tetap ada tapi praktis
    selalu return 0 lowongan. Halaman `jobs.talentics.id/jobs` adalah
    Vue SPA — tanpa API, tanpa data statis, tidak bisa di-scrape.

3.  **Sitemap HiredToday berisi URL yang semua 404.**
    Sitemap masih terdaftar di robots.txt dan berisi ratusan
    `jobs-detail` URL. Semua URL diuji: `404 Not Found`. Sitemap
    basi. Fetcher `hiredtoday` sebenarnya sudah `enabled: false`
    di config dengan komentar yang benar — jadi tidak memakan sumber
    daya, tapi tetap menyesatkan pembaca config.

4.  **Loker.id memblokir bot secara eksplisit (403).**
    robots.txt bilang `Allow: all`, tapi halaman listing membalas
    `403` untuk User-Agent bot ini. Fetcher juga `enabled: false`.

5.  **Semua 21 test fixture berasal dari luar negeri.**
    File di `test_fixtures/` berisi lowongan Stripe, Bugcrowd, Supabase,
    runZero, dll — semua remote jobs internasional dari remotive.com.
    Tidak ada satu pun contoh lowongan Indonesia. Padahal target sistem
    ini lowongan Indonesia. Test fixture tidak mewakili pemakaian nyata.

6.  **`docs/HANDOFF.md` bohong (kadaluwarsa parah).**
    Baris kedua dokumen itu: *"Application code has NOT been implemented
    yet"*. Padahal 29 commit, 104 test, dan daemon produksi di VPS.
    Dokumen ini adalah sisa dari fase perencanaan dan tidak pernah
    diperbarui. Siapa pun yang onboarding dari file ini akan mengira
    project kosong.

7.  **`docs/architecture-decision-record-v1.1.md` masih DRAFT.**
    Statusnya "Awaiting Approval" padahal v1.2 yang lebih baru sudah
    APPROVED. v1.1 tidak pernah ditandai superseded.

8.  **`ai_job_filter.db` di root adalah file 0 byte.**
    Bukan database sungguhan. Kemungkinan sisa eksperimen awal sebelum
    path DB dipindah ke `data/jobs.db`. Tidak berbahaya, tapi membingungkan
    siapa pun yang melihatnya.

9.  **Dead code terkonfirmasi (9 temuan).**
    Setiap nama fungsi/kelas dicari di seluruh folder. Hasil:
    - `JobStatus` dan `UserAction` di `models/enums.py:23,31` — didefinisikan
      tapi tidak pernah direferensikan di kode (nilai enum-nya dipakai
      sebagai string literal, bukan lewat enum ini)
    - `is_text_duplicate` di `processing/dedup.py:28` — ADR menyebut fuzzy
      dedup ≥85% sebagai Layer 2, tapi implementasi handler hanya pakai
      exact hash. Fungsi fuzzy ini jadi tidak pernah dipanggil
    - `ingest_candidate` di `web_fetcher/scheduler.py:23` — sisa rancangan
      awal scheduler, sudah digantikan logika inline di `run_fetcher_once`
    - `parse_sitemap_urls` di `web_fetcher/medium.py:215` — helper yang
      tidak pernah diimpor
    - `normalize_null_lists`, `normalize_null_defaults`, `validate_semantics`
      di `models/job.py` — SEMUA ini ternyata BUKAN dead code: ketiganya
      adalah dekorator `@model_validator` Pydantic yang dipanggil otomatis
      oleh framework. Skrip scan AST tidak mendeteksi pemanggilan via
      dekorator — ini keterbatasan metode, bukan temuan.
      (Diverifikasi manual: ada `@model_validator(mode="before"/"after")`
      di atas masing-masing.)
    - `new_message_handler` di `telegram/listener.py:80` — juga bukan dead
      code: itu closure yang didaftarkan sebagai callback via
      `@self.client.on(events.NewMessage(...))`.

10. **Bug kecil: `notifications.bot_message_id` selalu NULL.**
    Di VPS ada 7 baris notifikasi, semua `bot_message_id` kosong.
    Penyebabnya di `listener.py:114`: `insert_notification` dipanggil
    SEBELUM `send_job_alert`, sehingga ID pesan bot yang sebenarnya
    tidak pernah diketahui dan tidak pernah di-update ke DB. Tidak
    merusak fungsi notif, tapi membuat fitur "edit pesan setelah user
    menekan tombol" menjadi rapuh (mengandalkan teks, bukan ID).

11. **pre-commit hook tidak terpasang.**
    `.pre-commit-config.yaml` lengkap (gitleaks + detect-private-key +
    ruff) tapi `.git/hooks/pre-commit` tidak ada di mesin lokal. Artinya
    pemeriksaan kebocoran kredensial TIDAK berjalan otomatis saat commit.
    Keamanan bertumpu pada disiplin manual + `.gitignore` (yang selama
    ini cukup — `.env` terverifikasi tidak pernah masuk git).

12. **`downloads/` memegang 3 foto pribadi dari Telegram.**
    Foto diunduh saat pemrosesan dan seharusnya dihapus setelah ekstraksi.
    Tiga foto tertinggal (kemungkinan dari sesi uji coba saat
    `DRY_RUN=true` atau proses terputus). Berisi poster lowongan, bukan
    data pribadi, tapi ini menunjukkan path cleanup tidak 100%.

13. **Lokal vs VPS sudah diverifikasi sinkron.**
    Fingerprint SHA-256 dari 19 dari 20 key `.env` identik antara laptop
    dan VPS. Satu yang beda adalah `TELEGRAM_CHANNELS` (VPS 6 channel,
    lokal 3) — sudah diselesaikan dengan trim ke 3 di VPS pada 28 Agustus.

14. **Free-tier Gemini memakai data untuk training.**
    Tercatat di ADR sendiri (bagian I). Data yang dikirim = teks poster
    lowongan publik. Risiko rendah, tapi kebijakan ini bisa berubah
    kapan saja dari sisi Google.

---

## 9. DAFTAR PERINTAH / MENU

| Perintah | Fungsi | Butuh API key? |
|---|---|---|
| `uv run python -m pytest tests/ -m "not integration" -q` | Jalankan 104 test (tanpa network) | Tidak |
| `uv run python -m pytest tests/ -m integration -v` | Test dengan API nyata | Ya |
| `uv run python -m ai_job_filter.main` | Jalankan daemon (Telegram + web) | Ya |
| `uv run python scripts/run_web_fetchers.py` | Web fetcher sekali (dry-run) | Ya (Groq) |
| `uv run python scripts/run_web_fetchers.py --execute` | Web fetcher + tulis DB | Ya |
| `uv run python scripts/run_web_fetchers.py --only dealls --limit 2` | Satu board saja | Ya |
| `uv run python scripts/ingest_web_candidate.py --file X.json --dry-run` | Uji 1 lowongan JSON tanpa tulis DB | Ya |
| `uv run python scripts/ingest_web_candidate.py --file X.json --execute` | Masukkan 1 lowongan JSON ke DB | Ya |
| `uv run python scripts/reprocess.py --execute` | Ulangi pesan yang gagal ekstraksi | Ya |
| `uv run python scripts/rebuild_job.py --message-id N --execute` | Rebuild 1 job (skor ulang) | Ya |
| `uv run python scripts/generate_session.py` | Buat StringSession Telegram (interaktif) | Tidak (tapi butuh kode login HP) |
| `uv run python scripts/evaluate_extraction.py` | Uji manual kualitas ekstraksi Groq (4 sampel) | Ya |
| `systemctl --user start ai-job-filter` (VPS) | Nyalakan daemon produksi | - |
| `journalctl --user -u ai-job-filter -f` (VPS) | Lihat log real-time | - |

---

## 10. DATA YANG TERSIMPAN DAN RISIKONYA

### Lokasi data

| Data | Lokasi | Isi | Risiko kalau bocor |
|---|---|---|---|
| Kredensial semua | `.env` (laptop + VPS) | Session string, bot token, API key | **KRITIS** — akun Telegram bisa diambil alih |
| Database lowongan | `data/jobs.db` (laptop: 56 job/208 msg; VPS: 161 job/7 notif) | Judul, perusahaan, gaji, kontak HR, link lamaran | RENDAH — semua data dari kanal publik |
| Riwayat notif + aksi user | tabel `notifications` | Lowongan mana yang dilihat/dilamar user | RENDAH-SEDANG — profil minat kerja pemilik bisa dibaca orang lain |
| Status web fetcher | tabel `fetcher_state` | Daftar slug yang sudah diproses | TIDAK ADA — tidak sensitif |
| Foto dari Telegram | `downloads/` (3 file) | Poster lowongan | RENDAH |
| Session `anti_idle` log | VPS `~/anti-idle/anti_idle.log` | Timestamp saja | TIDAK ADA |
| Test fixtures | `test_fixtures/*.json` | 21 lowongan publik luar negeri | TIDAK ADA |

### Pihak ketiga yang menerima data

| Pihak | Data yang diterima | Tujuan |
|---|---|---|
| Telegram | Semua aktivitas baca/kirim pesan | Layanan inti |
| Groq | Teks lowongan (yang lolos filter) | Ekstraksi |
| Google Gemini | Gambar poster lowongan | Ekstraksi vision |
| Situs lowongan (8) | Request HTTP + User-Agent | Scraping |

Tidak ada data yang dikirim ke pihak ketiga yang tidak diperlukan.
Tidak ada telemetri, tidak ada analytics.

### Kebocoran yang paling merugikan

Kalau laptop ATAU VPS dikuasai orang lain, file `.env` membuka akun
Telegram penuh. Dari akun itu, penyerang bisa membaca semua pesan
pribadi pemilik, mengirim pesan sebagai pemilik, dan mengakses grup
rahasia. Ini jauh lebih berbahaya daripada bocornya database lowongan.

---

## 11. STATUS NYATA DI MESIN INI

**Tool ini PERNAH DIPAKAI dan SEDANG DIPAKAI.** Bukan "kemungkinan".
Bukti:

**Di laptop:**
- `data/jobs.db` ada, 761KB → 56 job, 208 message, 4 source, 3 notif
- `downloads/` berisi 3 foto hasil unduhan Telegram (19-24 Agustus)
- `scripts/sevima_seen.json` berisi 3 slug yang sudah diproses
- `fetcher_state` tabel ada dengan 1 baris (dealls, status ok)
- git history 29 commit dalam rentang 21–28 Agustus 2026

**Di VPS (129.225.13.217):**
- `systemctl --user status ai-job-filter` = active (running)
- `data/jobs.db` = 161 job tersebar 21-28 Agustus, 7 notifikasi terkirim,
  5 di antaranya mendapat aksi user (`SAVED`)
- Log menunjukkan pesan diproses real-time: `Processed job score=55`
- `anti_idle.log` terisi tiap 6 jam (cron hidup)

**Perbandingan klaim vs kenyataan:**

| Fitur diklaim | Status nyata |
|---|---|
| Monitoring Telegram text + image | ✅ Jalan di produksi |
| Dedup 4 lapis | ✅ 3 lapis jalan (SHA, dHash, job-level). Fuzzy text dedup terdaftar tapi tidak terhubung (lihat dead code) |
| Groq text extraction | ✅ Jalan, kadang 429 → antrian |
| Gemini vision | ✅ Jalan |
| Scoring 0-100 | ✅ Jalan setelah bugfix 28 Agustus (sebelumnya NOC Engineer = 0, seharusnya 55) |
| Telegram bot notif + tombol | ✅ Jalan (7 notif di VPS, 5 di-save user) |
| Web fetcher 8 board aktif | ⚠️ 6 board benar-benar aktif. Talentics butuh auth, HiredToday sitemap stale, Loker.id 403 |
| SEVIMA fetcher | ⚠️ Ada kodenya, butuh playwright terpisah, belum jalan di VPS |
| "Daemon 24/7" | ✅ VPS Oracle + systemd + linger |

---

## 12. DIAGRAM 3 — PETA RISIKO

```
RISIKO RENDAH ◄─────────────────────────────────────► RISIKO TINGGI

  ┌───────────────┬──────────────────┬────────────────┬──────────────┐
  │ AMAN          │ RENDAH           │ SEDANG         │ TINGGI       │
  ├───────────────┼──────────────────┼────────────────┼──────────────┤
  │ Membaca kode  │ Menjalankan test │ Menjalankan    │ Membagikan   │
  │ (read-only)   │ offline          │ daemon lokal   │ file .env    │
  │               │                  │                │              │
  │ Membaca DB    │ Dry-run web      │ Menjalankan    │ Commit .env  │
  │ (sqlite3)     │ fetcher          │ daemon di 2    │ ke git       │
  │               │                  │ mesin bersamaan│              │
  │               │                  │                │              │
  │ Melihat log   │ Reprocess 1      │ Mengubah       │ Menempelkan  │
  │ journalctl    │ job              │ candidate_     │ session      │
  │               │                  │ profile.yaml   │ string ke    │
  │               │                  │                │ chat manapun │
  └───────────────┴──────────────────┴────────────────┴──────────────┘

  Alasan per zona:
  - AMAN    : tidak menyentuh kode yang jalan, tidak menyentuh network
  - RENDAH  : menyentuh API gratis tapi tidak menulis DB, reversible
  - SEDANG  : mengubah data permanen atau bisa memicu perilaku tak terduga
  - TINGGI  : satu file = akun Telegram orang lain bisa diambil alih

  Risiko spesifik yang perlu diketahui pemilik:
  ┌──────────────────────────────────────────────────────────────┐
  │ 1. `.env` di dua mesin = dua permukaan serangan              │
  │ 2. VPS di internet publik; SSH key-based auth = baik, tapi   │
  │    satu kunci = satu titik gagal                             │
  │ 3. pre-commit gitleaks TIDAK terpasang → guard kebocoran     │
  │    manual saja                                               │
  │ 4. Gemini free tier boleh pakai data untuk training          │
  │ 5. Scraping 6 situs lowongan bisa melanggar ToS masing-      │
  │    masing; saat ini politeness (delay 3s+jitter) sudah       │
  │    ada, tapi tidak ada perjanjian resmi                      │
  └──────────────────────────────────────────────────────────────┘
```

---

## 13. ALTERNATIF YANG SAH (kalau ada masalah ToS scraping)

Kalau salah satu situs lowongan merasa diganggu atau melarang scraping:

1.  **RSS resmi** — beberapa board menyediakan RSS. Sudah dipakai untuk
    Indeed (yang akhirnya dibuang karena robots melarang). Bisa ditambah
    untuk board lain yang menyediakan.
2.  **API resmi** — Talentics punya API tapi butuh registrasi. Mendaftar
    resmi lebih aman daripada scraping.
3.  **Google Jobs / LinkedIn via integrasi pihak ketiga** — ada layanan
    seperti SerpAPI yang menjual hasil scraping secara legal (mereka yang
    menanggung risiko). Berbayar.
4.  **Webhook Telegram resmi** — banyak grup lowongan punya bot resmi
    yang bisa di-subscribe langsung, tidak perlu membaca grup seperti
    manusia.
5.  **Berhenti memantau board tertentu** — config `web_fetchers.yaml`
    sudah dirancang supaya 1 board bisa dimatikan 1 baris tanpa menyentuh
    kode.

Khusus Groq/Gemini: kalau suatu saat kebijakan free tier berubah, kode
sudah punya abstraksi `TextProvider`/`VisionProvider` — mengganti provider
berarti menambah satu file implementasi, bukan menulis ulang.

---

## 14. NILAI EDUKATIF

Teknik yang bisa dipelajari dari codebase ini, diurut dari paling
berharga:

1.  **Pipeline multi-stage dengan cost gate** — cara mendesain sistem
    yang "mahal" (API call) jadi murah: filter murah dulu, dedup
    berlapis, baru API. Ini pola yang berlaku di semua sistem
    berbasis LLM.
2.  **Asyncio di dunia nyata** — bukan demo hello-world, tapi kasus
    nyata: dua sumber event (Telegram + web scheduler) + worker
    background, satu koneksi DB, satu lock. Termasuk bug nyata
    (SQL statements in progress) dan solusinya.
3.  **SQLite sebagai database produksi** — WAL mode, FTS5 full-text
    search, trigger, partial index. Banyak orang mengira SQLite hanya
    untuk mainan; di sini dia melayani daemon 24/7.
4.  **Pydantic sebagai "pintu gerbang data"** — semua data dari AI
    (yang pasti kadang mengarang) lewat validasi Pydantic dulu,
    termasuk pembersihan nilai hallucination ("null", "n/a" → None).
5.  **Perceptual hashing (dHash)** — cara mengenali gambar mirip tanpa AI.
6.  **Testing pydantic + async** — 104 test yang benar-benar jalan,
    termasuk cara mock provider tanpa network.
7.  **Dokumentasi keputusan (ADR)** — dua ADR panjang yang mencatat
    kenapa LiteLLM dibuang, kenapa "Staff" bukan kata senior di
    Indonesia, dll. Pola dokumentasi yang jarang dilakukan developer
    solo.
8.  **Migrasi lokal → VPS** — pola git bundle + scp + systemd user unit
    + linger, termasuk penanganan kasus khusus Telegram
    (AuthKeyDuplicated karena dua IP).

---

## 15. RINGKASAN AKHIR (TANYA-JAWAB)

**Q: Apa ini?**
Sistem yang membaca grup lowongan kerja Telegram dan 6-8 situs web,
memilah yang relevan (Linux/DevOps/SOC junior), lalu mengirim notif ke
Telegram pemilik dengan skor 0-100.

**Q: Sudah jalan atau baru rencana?**
Sudah jalan produksi di VPS Oracle sejak akhir Agustus 2026. 161
lowongan sudah diproses di VPS, 7 notif terkirim, 5 di-save user.

**Q: Bayar berapa per bulan?**
Rp 0. Groq dan Gemini free tier, VPS Oracle PAYG (dijaga anti-idle),
SQLite lokal.

**Q: Apakah aman?**
Data lowongan aman (semua publik). Risiko utamanya adalah file `.env`
yang setara password akun Telegram. File ini tidak di-commit ke git
(terverifikasi), tapi ada di dua mesin sebagai plaintext.

**Q: Apakah semua yang tertulis di README benar?**
Sebagian besar benar. Tiga pengecualian: (1) `HANDOFF.md` mengklaim
aplikasi belum diimplementasi — salah, sudah di produksi; (2) jadwal
web harian tertulis "07:00" tanpa menyebut ini UTC (= 14:00 WIB);
(3) ADR menyebut fuzzy text dedup sebagai bagian dari pipeline —
fungsinya ada tapi tidak pernah dipanggil.

**Q: Apakah ada bagian yang bohong atau pura-pura?**
Tidak ada niat menipu. Yang ada adalah dokumentasi yang tertinggal dari
kode (HANDOFF.md) dan asumsi yang belum diverifikasi (Talentics "free API").
Semua klaim fitur yang aktif bisa dibuktikan dari log dan database.

**Q: Kalau saya ingin memakai tool ini, apa yang harus saya lakukan?**
Dokumen ini bukan tutorial (sesuai aturan pembuatan). Mulai dari
`README.md` dan `docs/PRD-v1.0.md`. Tapi ketahui dulu: sistem ini
sangat personal — profil pencari kerja di `candidate_profile.yaml`
adalah profil Ashim (Linux/SOC junior), bukan template umum.

---

**Catatan penutup tentang metode analisis.**

Analisis ini dilakukan dengan cara: (1) membaca seluruh 47 file kode
dan konfigurasi di folder project, termasuk file tersembunyi; (2) membaca
29 commit git history untuk memahami urutan perubahan; (3) memeriksa
langsung isi database SQLite di laptop (`data/jobs.db`) dan di VPS
(melalui SSH, hanya SELECT, tidak ada perubahan); (4) menjalankan skrip
AST untuk mencari dead code, lalu memverifikasi manual setiap temuan
untuk membedakan dead code sungguhan vs callback framework (Pydantic
validator, Telethon event handler); (5) menguji langsung endpoint
eksternal yang diklaim (Talentics API, HiredToday sitemap) dengan curl
hanya untuk membaca response, tidak melakukan scraping massal; (6)
membandingkan fingerprint SHA-256 file `.env` di dua mesin tanpa
menampilkan nilainya. **Tidak ada satu baris pun kode project yang
dieksekusi** dalam proses analisis ini, kecuali skrip AST read-only dan
pytest collect-only yang tidak menyentuh API eksternal. Semua angka
(56 job, 161 job, 104 test, 7 notif) adalah hasil query langsung, bukan
perkiraan.
