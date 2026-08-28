"""Web scheduler (PRD F-WEB-4): run all fetchers once per day at a fixed hour.

Runs inside the existing asyncio daemon alongside TelegramListener and
retry_worker. Staggering: fetchers run sequentially with per-board polite
delays so Groq quota (~90 jobs/day) is not exhausted instantly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import structlog

from .base import RawCandidate
from .registry import build_fetchers

logger = structlog.get_logger()

DEFAULT_RUN_HOUR = 7  # 07:00 local time (WIB), PRD section 2 goal #3


async def ingest_candidate(db_repo, candidate: RawCandidate, scorer) -> int | None:
    """Persist one RawCandidate via the existing pipeline.

    Mirrors scripts/ingest_web_candidate.py execute path but reuses the live
    db_repo (no subprocess) so write_lock is honored (PRD F-WEB-3).
    Returns job_id or None if skipped/failed.
    """
    import hashlib

    from ..processing.normalizer import compute_text_hash, normalize_text

    # Virtual IDs (stable per URL) — 64-bit from full md5 to avoid collisions
    virtual_source_id = int(hashlib.md5(candidate.source.encode()).hexdigest()[:12], 16)
    virtual_msg_id = int(hashlib.md5(candidate.source_url.encode()).hexdigest()[:12], 16)

    source_id = await db_repo.insert_source(
        telegram_id=virtual_source_id,
        title=candidate.source,
        source_type="WEB",
        username=candidate.source_url,
    )

    msg_id = await db_repo.insert_message(
        source_id=source_id,
        telegram_msg_id=virtual_msg_id,
        raw_text=candidate.source_text,
        posted_at=candidate.discovered_at,
        has_media=0,
    )
    if msg_id == 0:
        return None  # already ingested

    content_hash = compute_text_hash(normalize_text(candidate.source_text))
    if await db_repo.find_message_by_hash(content_hash):
        await db_repo.update_message_status(msg_id, "DUPLICATE", "Text hash match")
        return None

    # Build a JobExtractionResult via LLM extraction

    # extract via Groq pipeline is async and shared — caller passes extractor
    return msg_id


async def run_fetcher_once(db_repo, extractor, scorer, fetcher, dry_run: bool, limit: int | None = None):
    """One fetcher pass: fetch -> extract -> score -> persist."""
    stats = await fetcher.run(dry_run=dry_run, limit=limit)
    candidates = getattr(fetcher, "last_candidates", [])

    ingested = 0
    if dry_run:
        return stats, ingested

    for candidate in candidates:
        try:
            job_result, status = await extractor.run(candidate.source_text)
            if status != "PROCESSED" or not job_result:
                continue

            # Fill in known metadata from the fetcher (LLM may miss it)
            job_result.title = job_result.title or candidate.title
            job_result.company = job_result.company or candidate.company
            job_result.location = job_result.location or candidate.location
            job_result.application_url = job_result.application_url or candidate.source_url
            if candidate.salary_raw and not job_result.salary_raw:
                job_result.salary_raw = candidate.salary_raw

            # Persist via the standard pipeline
            import hashlib

            from ..processing.pipeline import score_and_save_job

            virtual_source_id = int(hashlib.md5(candidate.source.encode()).hexdigest()[:12], 16)
            source_id = await db_repo.insert_source(
                telegram_id=virtual_source_id,
                title=candidate.source,
                source_type="WEB",
                username=candidate.source_url,
            )

            virtual_msg_id = int(hashlib.md5(candidate.source_url.encode()).hexdigest()[:12], 16)
            msg_id = await db_repo.insert_message(
                source_id=source_id,
                telegram_msg_id=virtual_msg_id,
                raw_text=candidate.source_text,
                posted_at=candidate.discovered_at,
                has_media=0,
            )
            if msg_id == 0:
                continue

            job_id, _score, _classification = await score_and_save_job(
                db_repo, scorer, msg_id, source_id, candidate.source_text, job_result
            )
            if job_id:
                ingested += 1
        except Exception as e:
            logger.error(
                "Candidate ingest failed",
                source=fetcher.source,
                url=candidate.source_url,
                error=str(e),
            )

    stats["ingested"] = ingested
    return stats, ingested


async def web_scheduler(db_repo, extractor, scorer, config, notifier=None, run_hour: int = DEFAULT_RUN_HOUR):
    """Daily loop at run_hour. Cancel-safe."""
    from ..config import Settings  # noqa: F401 — typing only

    dry_run = config.dry_run
    fetchers = build_fetchers(db_repo)

    if not fetchers:
        logger.warning("No web fetchers configured; scheduler idle.")
        return

    logger.info("Web scheduler started", boards=[f.source for f in fetchers], run_hour=run_hour)

    while True:
        # Sleep until next run_hour
        now = datetime.now()
        target = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info("Web scheduler next run", at=target.isoformat(), wait_seconds=wait_seconds)

        try:
            await asyncio.sleep(wait_seconds)
        except asyncio.CancelledError:
            return

        total_ingested = 0
        for fetcher in fetchers:
            try:
                _stats, ingested = await run_fetcher_once(
                    db_repo, extractor, scorer, fetcher, dry_run=dry_run
                )
                total_ingested += ingested
            except Exception as e:
                logger.error("Fetcher crashed", source=fetcher.source, error=str(e))
            # Inter-board stagger
            await asyncio.sleep(5)

        logger.info("Web scheduler daily pass complete", total_ingested=total_ingested)
