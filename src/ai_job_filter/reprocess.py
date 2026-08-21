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
from .providers.errors import TransientAPIError

logger = structlog.get_logger()


@dataclass
class ReprocessStats:
    candidates_found: int = 0
    eligible: int = 0
    skipped_limit: int = 0
    skipped_media: int = 0
    success: int = 0
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
) -> ReprocessStats:
    stats = ReprocessStats(mode="EXECUTE" if execute else "DRY RUN")
    repo = Repository(conn)

    async with conn.execute(
        "SELECT * FROM messages WHERE processing_status IN ('EXTRACTION_FAILED', 'VISION_FAILED') ORDER BY posted_at ASC"
    ) as cursor:
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
            status == "VISION_FAILED"
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
            if status == "VISION_FAILED" and media_path:
                job_result, new_status = await vision.run(media_path, raw_text)
            else:
                job_result, new_status = await extractor.run(raw_text)

            if new_status == "PROCESSED" and job_result:
                # Memory transformations
                if execute:
                    job_id, _score, _classification = await score_and_save_job(
                        repo, scorer, msg_id, source_id, raw_text, job_result
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
            else:
                # Still failed
                raise Exception(f"Pipeline returned {new_status}")

        except TransientAPIError as e:
            stats.failed += 1
            logger.warning("Transient error during reprocess", msg_id=msg_id, error=str(e))
            if execute:
                await conn.execute(
                    "UPDATE messages SET retry_count = retry_count + 1, skip_reason = ?, last_retry_at = datetime('now') WHERE id = ?",
                    (
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
                    if status == "VISION_FAILED"
                    else "provider_extraction_failed"
                )
                await conn.execute(
                    "UPDATE messages SET retry_count = retry_count + 1, skip_reason = ?, last_retry_at = datetime('now') WHERE id = ?",
                    (reason, msg_id),
                )
                await conn.commit()

    return stats
