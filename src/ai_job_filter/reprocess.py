import os
from dataclasses import dataclass

import aiosqlite
import structlog

from .config import Settings
from .db.repository import Repository
from .models.enums import ProcessingStatus
from .processing.extractor import ExtractorPipeline
from .processing.pipeline import score_and_save_job
from .processing.vision import VisionPipeline, should_try_text_first
from .providers.errors import TransientAPIError

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
    # Unified retry queue: terminal failures, stale legacy PENDING, and the
    # quota-pending statuses (PENDING_AI / PENDING_VISION / RATE_LIMITED)
    # which retry_worker also drains.
    query = (
        "SELECT * FROM messages "
        "WHERE processing_status IN ("
        "'EXTRACTION_FAILED', 'VISION_FAILED', "
        "'PENDING_AI', 'PENDING_VISION', 'RATE_LIMITED') "
        f"OR (processing_status = 'PENDING' AND scraped_at <= datetime('now', '-{stale_minutes} minutes'))"
    )
    params = []

    if message_id is not None:
        query = (
            "SELECT * FROM messages "
            "WHERE id = ? AND ("
            "processing_status IN ("
            "'EXTRACTION_FAILED', 'VISION_FAILED', "
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

        if retry_count >= 3 and not force:
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
            use_vision = (
                status in ("VISION_FAILED", "PENDING_VISION", "RATE_LIMITED")
                or (status in ("PENDING", "PENDING_AI") and has_media)
            ) and media_path
            if use_vision and should_try_text_first(raw_text):
                # Long caption: spare vision quota, try Groq text first.
                job_result, new_status = await extractor.run(raw_text)
                if new_status not in ("PROCESSED", "NOT_JOB"):
                    job_result, new_status = await vision.run(media_path, raw_text)
            elif use_vision:
                job_result, new_status = await vision.run(media_path, raw_text)
            else:
                job_result, new_status = await extractor.run(raw_text)

            if new_status in ("PENDING_AI", "PENDING_VISION", "RATE_LIMITED"):
                # Still rate-limited: keep queued WITHOUT consuming retry_count.
                logger.info("Still rate limited, kept queued", msg_id=msg_id)
                if execute:
                    await conn.execute(
                        "UPDATE messages SET processing_status = ?, "
                        "last_retry_at = datetime('now') WHERE id = ?",
                        (new_status, msg_id),
                    )
                    await conn.commit()
                continue

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
            else:
                # Still failed
                raise Exception(f"Pipeline returned {new_status}")

        except TransientAPIError as e:
            stats.failed += 1
            logger.warning("Transient error during reprocess", msg_id=msg_id, error=str(e))
            if execute:
                vision_side = status in ("VISION_FAILED", "PENDING_VISION", "RATE_LIMITED") or (
                    status == "PENDING" and has_media
                )
                status_to_set = "VISION_FAILED" if vision_side else "EXTRACTION_FAILED"
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
                vision_side = status in ("VISION_FAILED", "PENDING_VISION", "RATE_LIMITED") or (
                    status == "PENDING" and has_media
                )
                reason = "provider_vision_failed" if vision_side else "provider_extraction_failed"
                await conn.execute(
                    "UPDATE messages SET processing_status = ?, retry_count = retry_count + 1, skip_reason = ?, last_retry_at = datetime('now') WHERE id = ?",
                    (
                        "VISION_FAILED" if vision_side else "EXTRACTION_FAILED",
                        reason,
                        msg_id,
                    ),
                )
                await conn.commit()

    return stats
