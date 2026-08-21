from dataclasses import dataclass

import structlog

from .db.repository import Repository
from .models.enums import ProcessingStatus
from .processing.extractor import ExtractorPipeline
from .processing.pipeline import score_and_update_job
from .providers.errors import TransientAPIError

logger = structlog.get_logger()


@dataclass
class RebuildResult:
    success: bool
    status_updated_to: str | None = None
    job_updated: bool = False
    new_score: float | None = None
    new_classification: str | None = None
    error_reason: str | None = None


class JobRebuilder:
    def __init__(self, db_repo: Repository, extractor: ExtractorPipeline, scorer, execute: bool):
        self.db_repo = db_repo
        self.extractor = extractor
        self.scorer = scorer
        self.execute = execute

    async def rebuild_message(self, message_id: int, force: bool = False) -> RebuildResult:
        message = await self.db_repo.get_message(message_id)
        if not message:
            return RebuildResult(success=False, error_reason="Message not found")

        msg_dict = dict(message)
        current_status = msg_dict["processing_status"]

        if current_status in ("NOT_JOB", "SKIPPED", "FAILED") and not force:
            return RebuildResult(
                success=False,
                error_reason=f"Message status is {current_status}. Use --force to rebuild.",
            )

        job = await self.db_repo.get_job_by_message_id(message_id)
        if not job:
            return RebuildResult(
                success=False,
                error_reason="No existing jobs row found. Use reprocess.py to ingest new jobs.",
            )

        job_dict = dict(job)
        job_id = job_dict["id"]

        logger.info(
            "rebuild_started",
            message_id=message_id,
            job_id=job_id,
            execute=self.execute,
            current_status=current_status,
        )

        try:
            job_result, _ = await self.extractor.process_message(msg_dict)
        except TransientAPIError as e:
            logger.error("rebuild_transient_error", error=str(e))
            if self.execute:
                await self.db_repo.update_message_status(
                    message_id, ProcessingStatus.EXTRACTION_FAILED.value, str(e)
                )
            return RebuildResult(
                success=False,
                error_reason="Transient API Error",
                status_updated_to=ProcessingStatus.EXTRACTION_FAILED.value
                if self.execute
                else None,
            )
        except Exception as e:
            logger.exception("rebuild_fatal_error", error=str(e))
            if self.execute:
                await self.db_repo.update_message_status(
                    message_id, ProcessingStatus.FAILED.value, str(e)
                )
            return RebuildResult(
                success=False,
                error_reason=f"Fatal error: {e}",
                status_updated_to=ProcessingStatus.FAILED.value if self.execute else None,
            )

        if not job_result.is_job_posting:
            logger.info("rebuild_not_job", message_id=message_id)
            if self.execute:
                await self.db_repo.update_message_status(message_id, ProcessingStatus.NOT_JOB.value)
                # Ensure retry_count is 0 when explicitly NOT_JOB (could update message row specifically if repo had it, but standard status update doesn't clear it. We will use update_message_status, and manual query for retry count if needed. Actually schema says we can just update retry_count manually)
                await self.db_repo.conn.execute(
                    "UPDATE messages SET retry_count = 0, skip_reason = NULL WHERE id = ?",
                    (message_id,),
                )
                await self.db_repo.conn.commit()
            return RebuildResult(
                success=True,
                status_updated_to=ProcessingStatus.NOT_JOB.value if self.execute else None,
            )

        # It's a job. We score and update.
        if self.execute:
            _, score, classification = await score_and_update_job(
                self.db_repo, self.scorer, job_id, job_result
            )
            await self.db_repo.update_message_status(message_id, ProcessingStatus.PROCESSED.value)
            await self.db_repo.conn.execute(
                "UPDATE messages SET retry_count = 0, skip_reason = NULL WHERE id = ?",
                (message_id,),
            )
            await self.db_repo.conn.commit()

            logger.info(
                "rebuild_completed", job_id=job_id, score=score, classification=classification.value
            )
            return RebuildResult(
                success=True,
                status_updated_to=ProcessingStatus.PROCESSED.value,
                job_updated=True,
                new_score=score,
                new_classification=classification.value,
            )
        else:
            # Dry run: calculate score, no update
            score, classification, _ = self.scorer.score_job(job_result)
            logger.info(
                "rebuild_dry_run_completed",
                job_id=job_id,
                score=score,
                classification=classification.value,
            )
            return RebuildResult(
                success=True,
                job_updated=False,
                new_score=score,
                new_classification=classification.value,
            )
