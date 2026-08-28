import os
from datetime import UTC, datetime

import structlog
from telethon.tl.types import Message

from ..models.enums import ProcessingStatus
from ..processing.detector import is_potential_job
from ..processing.image_hash import compute_dhash, compute_sha256, hamming_distance
from ..processing.normalizer import compute_text_hash, normalize_text
from ..processing.pipeline import score_and_save_job

logger = structlog.get_logger()


class MessageHandler:
    def __init__(self, db_repo, config, extractor_pipeline, vision_pipeline, scorer):
        self.db_repo = db_repo
        self.config = config
        self.extractor = extractor_pipeline
        self.vision = vision_pipeline
        self.scorer = scorer
        self.max_media_bytes = config.max_media_size_mb * 1024 * 1024

    async def handle_new_message(self, message: Message, source_id: int):
        try:
            return await self._process(message, source_id)
        except Exception as e:
            logger.error("Error in handler", error=str(e), msg_id=message.id)

    async def _process(self, message: Message, source_id: int):
        telegram_msg_id = message.id
        raw_text = message.text or ""
        posted_at = message.date.isoformat() if message.date else datetime.now(UTC).isoformat()
        has_media = bool(message.media)

        # 1. Database Insertion (Idempotency)
        msg_id = await self.db_repo.insert_message(
            source_id=source_id,
            telegram_msg_id=telegram_msg_id,
            raw_text=raw_text,
            posted_at=posted_at,
            has_media=1 if has_media else 0,
        )

        if msg_id == 0:
            return

        # 2. Local Detection
        if not is_potential_job(raw_text, has_media):
            await self.db_repo.update_message_status(
                msg_id, ProcessingStatus.NOT_JOB, "Failed regex/media check"
            )
            return

        # 3. Media Handling
        media_path = None
        media_dhash = None
        if has_media:
            # Check size using Telethon's file.size abstraction
            file_size = getattr(message.file, "size", None)
            if file_size is not None and file_size > self.max_media_bytes:
                await self.db_repo.update_message_status(
                    msg_id, ProcessingStatus.SKIPPED, "media_too_large"
                )
                return

            os.makedirs("downloads", exist_ok=True)
            try:
                media_path = await message.download_media(file="downloads/")
            except Exception as e:
                logger.error("Failed to download media", error=str(e))
                await self.db_repo.update_message_status(
                    msg_id, ProcessingStatus.SKIPPED, "download_failed"
                )
                return

            if media_path:
                media_sha = compute_sha256(media_path)
                media_dhash = compute_dhash(media_path)

                # PRD F-DED-1: persist hashes to DB so dedup survives restarts
                await self.db_repo.update_message_hashes(
                    msg_id, media_sha256=media_sha, media_dhash=media_dhash
                )

                # Check dHash Dedup (Tier 1)
                existing_dhashes = await self.db_repo.find_message_by_dhash(media_dhash)
                for existing in existing_dhashes:
                    if (
                        existing["media_dhash"]
                        and hamming_distance(media_dhash, existing["media_dhash"]) <= 5
                    ):
                        await self.db_repo.update_message_status(
                            msg_id,
                            ProcessingStatus.DUPLICATE,
                            f"dHash match with msg {existing['id']}",
                        )
                        self._safe_delete(media_path)
                        return

        # 4. Text Dedup (Tier 2)
        # PRD F-DED-2: hash the normalized text, not raw, so case/whitespace
        # variants dedup correctly
        content_hash = compute_text_hash(normalize_text(raw_text))
        if await self.db_repo.find_message_by_hash(content_hash):
            await self.db_repo.update_message_status(
                msg_id, ProcessingStatus.DUPLICATE, "Text hash match"
            )
            self._safe_delete(media_path)
            return

        # 5. Extraction
        job_result = None
        status = ProcessingStatus.EXTRACTION_FAILED

        if has_media and media_path:
            job_result, status_str = await self.vision.run(media_path, raw_text)
            status = status_str
        else:
            job_result, status_str = await self.extractor.run(raw_text)
            status = status_str

        # Cleanup media immediately
        self._safe_delete(media_path)

        await self.db_repo.update_message_status(msg_id, status)

        if status != "PROCESSED" or not job_result:
            return

        # 6. Score and Save Job
        job_id, score, classification = await score_and_save_job(
            self.db_repo, self.scorer, msg_id, source_id, raw_text, job_result
        )

        logger.info(
            "Processed job",
            msg_id=msg_id,
            score=score,
            classification=classification.value,
        )

        return job_id, job_result.model_dump(), classification

    def _safe_delete(self, path: str | None):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                logger.debug("Failed to delete media", error=str(e))
