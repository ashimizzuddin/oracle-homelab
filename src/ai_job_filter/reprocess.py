import os
from dataclasses import dataclass

import aiosqlite
import structlog

from .config import Settings
from .db.repository import Repository
from .models.enums import ProcessingStatus
from .processing.extractor import ExtractorPipeline
from .processing.pipeline import score_and_save_job
from .processing.vision import VisionPipeline
from .providers.errors import ProviderRateLimitError, TransientAPIError

logger = structlog.get_logger()


@dataclass
class ReprocessStats:
    candidates_found: int = 0
    eligible: int = 0
    skipped_limit: int = 0
    skipped_media: int = 0
    success: int = 0
    not_job: int = 0
    failed: int = 0
    mode: str = "DRY RUN"


async def reprocess_failed_messages(
    conn: aiosqlite.Connection,
    config: Settings,
    extractor: ExtractorPipeline,
    vision: VisionPipeline,
    scorer,
    limit: int | None = None,
    force: bool = False,
    execute: bool = False,
    message_id: int | None = None,
) -> ReprocessStats:
    stats = ReprocessStats(mode="EXECUTE" if execute else "DRY RUN")
    repo = Repository(conn)

    stale_minutes = getattr(config, "stale_pending_minutes", 15)
    max_attempts = getattr(config, "retry_max_attempts", 5)
    # Unified with retry_worker: rate-limit queue (PENDING_*) is retried by
    # both paths; terminal failures via CLI; stale PENDING via CLI only
    # (worker intentionally skips fresh PENDING to avoid racing the listener).
    query = (
        "SELECT * FROM messages "
        "WHERE processing_status IN ('EXTRACTION_FAILED', 'VISION_FAILED', "
        "'PENDING_AI', 'PENDING_VISION', 'RATE_LIMITED') "
        f"OR (processing_status = 'PENDING' AND scraped_at <= datetime('now', '-{stale_minutes} minutes'))"
    )
    params = []

    if message_id is not None:
        query = (
            "SELECT * FROM messages "
            "WHERE id = ? AND ("
            "processing_status IN ('EXTRACTION_FAILED', 'VISION_FAILED', "
            "'PENDING_AI', 'PENDING_VISION', 'RATE_LIMITED') "
            f"OR (processing_status = 'PENDING' AND scraped_at <= datetime('now', '-{stale_minutes} minutes'))"
            ")"
        )
        params.append(message_id)

    query += " ORDER BY posted_at ASC"

    async with conn.execute(query, params) as cursor:
        rows = await cursor.fetchall()

    stats.candidates_found = len(rows)

    processed = 0

    for row in rows:
        if limit is not None and processed >= limit:
            break

        msg_id = row["id"]
        source_id = row["source_id"]
        raw_text = row["raw_text"]
        has_media = row["has_media"]
        media_path = row["media_path"]
        retry_count = row["retry_count"]
        status = row["processing_status"]

        if retry_count >= max_attempts and not force:
            stats.skipped_limit += 1
            logger.info("Skipping due to retry limit", msg_id=msg_id, retry_count=retry_count)
            continue

        if (
            status in ("VISION_FAILED", "PENDING", "PENDING_VISION", "RATE_LIMITED")
            and has_media
            and (not media_path or not os.path.exists(media_path))
        ):
            stats.skipped_media += 1
            logger.info("Skipping due to missing media", msg_id=msg_id)
            if execute:
                await repo.update_message_status(
                    msg_id, ProcessingStatus.SKIPPED.value, "media_unavailable_for_reprocess"
                )
            continue

        stats.eligible += 1
        processed += 1

        logger.info("Reprocessing message", msg_id=msg_id, status=status)

        job_result = None
        new_status = status

        try:
            from .providers.rate_budget import PENDING_STATUSES

            needs_vision = status in ("VISION_FAILED", "PENDING_VISION", "RATE_LIMITED") or (
                status == "PENDING" and has_media
            )
            if needs_vision and media_path:
                job_result, new_status = await vision.run(media_path, raw_text)
            else:
                job_result, new_status = await extractor.run(raw_text)

            if new_status == "PROCESSED" and job_result:
                # Memory transformations
                if execute:
                    job_id, _score, _classification = await score_and_save_job(
                        repo, scorer, msg_id, source_id, raw_text or "", job_result
                    )
                    await conn.execute(
                        "UPDATE messages SET processing_status = ?, skip_reason = NULL, retry_count = 0 WHERE id = ?",
                        (ProcessingStatus.PROCESSED.value, msg_id),
                    )
                    await conn.commit()
                    logger.info("Successfully reprocessed", msg_id=msg_id, job_id=job_id)
                else:
                    logger.info(
                        "DRY RUN: Would have saved job", msg_id=msg_id, title=job_result.title
                    )

                stats.success += 1
            elif new_status == "NOT_JOB":
                stats.not_job += 1
                logger.info("Not a job posting", msg_id=msg_id)
                if execute:
                    await repo.update_message_status(msg_id, ProcessingStatus.NOT_JOB.value, None)
            elif new_status in PENDING_STATUSES:
                # Still quota-limited: keep queued, don't burn retry_count.
                stats.failed += 1
                logger.warning("Still rate limited, keeping PENDING", msg_id=msg_id)
                if execute:
                    await conn.execute(
                        "UPDATE messages SET processing_status = ?, skip_reason = ?, last_retry_at = datetime('now') WHERE id = ?",
                        (new_status, "provider_rate_limit", msg_id),
                    )
                    await conn.commit()
            else:
                # Still failed
                raise Exception(f"Pipeline returned {new_status}")

        except ProviderRateLimitError:
            stats.failed += 1
            logger.warning("Rate limited during reprocess, keeping PENDING", msg_id=msg_id)
            if execute:
                is_vision = status in ("VISION_FAILED", "PENDING_VISION", "RATE_LIMITED") or (
                    status == "PENDING" and has_media
                )
                await conn.execute(
                    "UPDATE messages SET processing_status = ?, skip_reason = ?, last_retry_at = datetime('now') WHERE id = ?",
                    (
                        "PENDING_VISION" if is_vision else "PENDING_AI",
                        "provider_rate_limit",
                        msg_id,
                    ),
                )
                await conn.commit()

        except TransientAPIError as e:
            stats.failed += 1
            logger.warning("Transient error during reprocess", msg_id=msg_id, error=str(e))
            if execute:
                status_to_set = (
                    "VISION_FAILED"
                    if status == "VISION_FAILED" or (status == "PENDING" and has_media)
                    else "EXTRACTION_FAILED"
                )
                await conn.execute(
                    "UPDATE messages SET processing_status = ?, retry_count = retry_count + 1, skip_reason = ?, last_retry_at = datetime('now') WHERE id = ?",
                    (
                        status_to_set,
                        "provider_rate_limit" if "429" in str(e) else "provider_transient_error",
                        msg_id,
                    ),
                )
                await conn.commit()

        except Exception as e:
            stats.failed += 1
            logger.warning("Failed to reprocess", msg_id=msg_id, error=str(e))
            if execute:
                reason = (
                    "provider_vision_failed"
                    if status == "VISION_FAILED" or (status == "PENDING" and has_media)
                    else "provider_extraction_failed"
                )
                await conn.execute(
                    "UPDATE messages SET processing_status = ?, retry_count = retry_count + 1, skip_reason = ?, last_retry_at = datetime('now') WHERE id = ?",
                    (
                        "VISION_FAILED"
                        if status == "VISION_FAILED" or (status == "PENDING" and has_media)
                        else "EXTRACTION_FAILED",
                        reason,
                        msg_id,
                    ),
                )
                await conn.commit()

    return stats
