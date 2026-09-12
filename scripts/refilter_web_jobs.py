"""Re-filter web-sourced jobs with the IT relevance classifier.

Why this exists: before ``web_fetcher/relevance.py`` was wired into
BaseFetcher.run, whole-site boards (dealls, kitalulus) stored every category
they found. 65% of the jobs table ended up non-IT (housekeeping, personal
trainer, medical rep, ...), which polluted scoring and every statistic
derived from it.

This script re-runs the classifier over already-stored rows. It makes NO LLM
calls, so it costs no Groq/Gemini quota.

What "filtered" means here, per design decision:
  - the ``messages`` row is marked NOT_JOB with skip_reason ``not_it_role:*``
    so it leaves the retry queue and is never re-extracted;
  - the ``jobs`` row is marked IGNORE with a hard_fail_reason, and excluded
    from the FTS index so searches stop returning it.
  Nothing is deleted — every change is reversible.

Usage:
    python scripts/refilter_web_jobs.py                 # dry run (default)
    python scripts/refilter_web_jobs.py --execute
    python scripts/refilter_web_jobs.py --scope all --execute
    python scripts/refilter_web_jobs.py --scope web --execute --limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import aiosqlite
import structlog
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from ai_job_filter.config import Settings
from ai_job_filter.web_fetcher.base import IT_FILTER_VERSION
from ai_job_filter.web_fetcher.relevance import classify_reason, is_it_job

logger = structlog.get_logger()

SKIP_REASON_PREFIX = "not_it_role"

# Jobs already classified this way are skipped so a re-run is cheap and
# idempotent.
ALREADY_IGNORED = "IGNORE"


async def collect_rows(conn: aiosqlite.Connection, scope: str) -> list[dict]:
    """Load candidate jobs: title + the full text of their source message."""
    where = ""
    if scope == "web":
        where = "WHERE s.source_type = 'WEB'"
    elif scope == "telegram":
        where = "WHERE s.source_type IN ('CHANNEL', 'GROUP')"

    query = f"""
        SELECT j.id            AS job_id,
               j.message_id    AS message_id,
               j.title         AS title,
               j.classification AS classification,
               j.hard_fail_reason AS hard_fail_reason,
               s.source_type   AS source_type,
               s.username      AS source_username,
               m.raw_text      AS raw_text,
               m.caption       AS caption,
               m.vision_text   AS vision_text,
               m.processing_status AS processing_status
        FROM jobs j
        JOIN sources  s ON s.id = j.source_id
        LEFT JOIN messages m ON m.id = j.message_id
        {where}
        ORDER BY j.id
    """
    async with conn.execute(query) as cur:
        rows = [dict(r) for r in await cur.fetchall()]
    return rows


def full_text(row: dict) -> str:
    return "\n".join(
        p
        for p in (row.get("raw_text") or "", row.get("caption") or "", row.get("vision_text") or "")
        if p
    )


async def apply_filter(conn: aiosqlite.Connection, rows: list[dict], execute: bool) -> dict:
    """Mark non-IT rows. Returns counters."""
    counters = {"considered": 0, "keep": 0, "filter": 0, "already": 0, "messages_marked": 0}
    samples: list[str] = []

    for row in rows:
        counters["considered"] += 1
        title = row.get("title") or ""
        text = full_text(row)

        if is_it_job(title, text):
            counters["keep"] += 1
            continue

        reason = classify_reason(title, text)

        # Idempotency: skip rows already carrying our marker.
        existing = row.get("hard_fail_reason") or ""
        if existing.startswith(SKIP_REASON_PREFIX):
            counters["already"] += 1
            continue

        counters["filter"] += 1
        if len(samples) < 15:
            samples.append(f"[{reason}] {title[:60]}")

        if not execute:
            continue

        hard_fail = f"{SKIP_REASON_PREFIX}: {reason} ({IT_FILTER_VERSION})"

        # 1. Mark the job as IGNORE with a traceable reason.
        #    NB: the jobs_fts_au trigger re-syncs the FTS index on UPDATE, so
        #    no manual FTS write is needed (doing one would corrupt the index).
        await conn.execute(
            """
            UPDATE jobs
               SET classification = ?,
                   match_score    = 0,
                   hard_fail_reason = ?
             WHERE id = ?
            """,
            (ALREADY_IGNORED, hard_fail, row["job_id"]),
        )

        # 2. Mark the message NOT_JOB so it leaves the retry queue and is
        #    never re-extracted by the LLM.
        if row.get("message_id"):
            cur = await conn.execute(
                """
                UPDATE messages
                   SET processing_status = 'NOT_JOB',
                       skip_reason       = ?
                 WHERE id = ?
                   AND processing_status != 'NOT_JOB'
                """,
                (hard_fail, row["message_id"]),
            )
            counters["messages_marked"] += cur.rowcount or 0

    if execute:
        await conn.commit()

    return counters | {"samples": samples}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        choices=["web", "telegram", "all"],
        default="web",
        help="Which sources to re-filter (default: web — Telegram channels are "
        "already IT-focused, so filtering them mostly removes noise-free rows).",
    )
    parser.add_argument("--execute", action="store_true", help="Actually mutate the database")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N jobs")
    parser.add_argument("--db", default=None, help="Override DATABASE_PATH")
    args = parser.parse_args()

    settings = Settings()
    db_path = args.db or settings.database_path

    mode = "EXECUTE" if args.execute else "DRY RUN"
    print(f"=== refilter_web_jobs [{mode}] ===")
    print(f"db      : {db_path}")
    print(f"scope   : {args.scope}")
    print(f"filter  : {IT_FILTER_VERSION}")
    if not args.execute:
        print("No changes will be written. Re-run with --execute to apply.")
    print()

    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await collect_rows(conn, args.scope)
        if args.limit:
            rows = rows[: args.limit]

        print(f"jobs loaded: {len(rows)}")
        result = await apply_filter(conn, rows, args.execute)

    print()
    print(f"considered      : {result['considered']}")
    print(f"keep (IT)       : {result['keep']}")
    print(f"filter (non-IT) : {result['filter']}")
    print(f"already marked  : {result['already']}")
    if args.execute:
        print(f"messages marked : {result['messages_marked']}")
    print()
    if result["samples"]:
        print("sample filtered:")
        for s in result["samples"]:
            print(f"  {s}")

    logger.info(
        "refilter_complete",
        mode=mode,
        scope=args.scope,
        **{k: v for k, v in result.items() if k != "samples"},
    )


if __name__ == "__main__":
    load_dotenv()
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
    asyncio.run(main())
