import asyncio
import contextlib
import signal

import structlog

from .config import Settings
from .db.connection import get_connection
from .db.migrations import apply_migrations
from .db.repository import Repository
from .models.candidate import CandidateProfile
from .models.enums import ProcessingStatus
from .processing.extractor import ExtractorPipeline
from .processing.scorer import Scorer
from .processing.vision import VisionPipeline
from .providers.gemini_provider import GeminiProvider
from .providers.groq_provider import GroqProvider
from .telegram.handlers import MessageHandler
from .telegram.listener import TelegramListener
from .telegram.notifier import TelegramNotifier

logger = structlog.get_logger()


async def retry_worker(db_repo, handler, notifier):
    """Background task to retry PENDING_AI / PENDING_VISION messages."""
    while True:
        try:
            pending = await db_repo.find_pending_messages()
            for msg in pending:
                msg_id = msg["id"]
                # Avoid infinite loops: check retry count
                if msg["retry_count"] >= 3:
                    await db_repo.update_message_status(
                        msg_id, ProcessingStatus.EXTRACTION_FAILED, "Max retries reached"
                    )
                    continue

                logger.info(f"Retrying message {msg_id}")

                # We need to route this to extraction.
                # Instead of duplicating handler logic, we could pull the raw text / media path and call extractor.
                # Since handler expects a Telethon Message, we can just extract from DB and do it here.
                # Actually, simpler: in Phase 3 we will mock a partial message or just extract directly.
                # Wait, handler._process handles the whole flow, but msg is already in DB.
                # Let's extract the core extraction logic out or just do it here:

                # Fetch data
                raw_text = msg["raw_text"]
                has_media = msg["has_media"]
                media_path = msg["media_path"]

                if has_media and media_path:
                    job_result, status = await handler.vision.run(media_path, raw_text)
                else:
                    job_result, status = await handler.extractor.run(raw_text)

                await db_repo.conn.execute(
                    "UPDATE messages SET retry_count = retry_count + 1, last_retry_at = datetime('now') WHERE id = ?",
                    (msg_id,),
                )
                await db_repo.conn.commit()

                await db_repo.update_message_status(msg_id, status)

                if status == "PROCESSED" and job_result:
                    score, classification, _ = handler.scorer.score_job(job_result)
                    job_id = await db_repo.insert_job(
                        message_id=msg_id,
                        source_id=msg["source_id"],
                        title=job_result.title,
                        content_hash="retried",  # simplified for retry
                        match_score=score,
                        classification=classification.value,
                        company=job_result.company,
                        location=job_result.location,
                        salary_min=job_result.salary_min,
                        salary_max=job_result.salary_max,
                        application_url=job_result.application_url,
                        summary=job_result.summary,
                        is_duplicate=0,
                        parent_job_id=None,
                    )
                    if classification.value in ["APPLY", "REVIEW"]:
                        notif_id = await db_repo.insert_notification(job_id, notifier.user_chat_id)
                        if notif_id > 0:
                            await notifier.send_job_alert(job_result.model_dump(), notif_id)

            await asyncio.sleep(60)  # Wait a minute before checking again
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in retry worker", error=str(e))
            await asyncio.sleep(60)


async def run():
    logger.info("ai-job-filter starting (Phase 3)")
    config = Settings()

    # DB
    conn = await get_connection(config.database_path)
    await apply_migrations(conn)
    db_repo = Repository(conn)

    # Providers
    groq_provider = GroqProvider(
        api_key=config.groq_api_key.get_secret_value() if config.groq_api_key else None,
        model=config.text_model,
    )
    gemini_provider = GeminiProvider(
        api_key=config.gemini_api_key.get_secret_value() if config.gemini_api_key else None,
        model=config.vision_model,
    )

    extractor = ExtractorPipeline(groq_provider)
    vision = VisionPipeline(gemini_provider)

    profile = CandidateProfile(
        professional_years=0
    )  # For Phase 3, we use default profile if not loaded from yaml
    with contextlib.suppress(Exception):
        profile = CandidateProfile.from_yaml("candidate_profile.yaml")

    scorer = Scorer(profile, min_apply=config.min_score_apply, min_review=config.min_score_review)

    # Telegram
    notifier = TelegramNotifier(config, db_repo)
    handler = MessageHandler(db_repo, config, extractor, vision, scorer)
    listener = TelegramListener(config, db_repo, handler, notifier)

    # Start Notifier (PTB)
    if notifier.app:
        await notifier.app.initialize()
        await notifier.app.start()
        if not config.dry_run:
            await notifier.app.updater.start_polling()

    # Start Background Retry Worker
    worker_task = asyncio.create_task(retry_worker(db_repo, handler, notifier))

    # Start Listener (Telethon)
    await listener.start()
    if listener.client:
        await listener.sync_history()
        # Keep running
        stop_event = asyncio.Event()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        await stop_event.wait()

        logger.info("Shutting down...")
        worker_task.cancel()
        await listener.disconnect()
        if notifier.app:
            if not config.dry_run:
                await notifier.app.updater.stop()
            await notifier.app.stop()
            await notifier.app.shutdown()

    await conn.close()


def main():
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()
