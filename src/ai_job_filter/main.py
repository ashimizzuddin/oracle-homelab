import asyncio
import contextlib
import signal
import time
from datetime import UTC, datetime

import structlog

from .config import Settings
from .db.connection import get_connection
from .db.migrations import apply_migrations
from .db.repository import Repository
from .models.candidate import CandidateProfile
from .models.enums import ProcessingStatus
from .processing.extractor import ExtractorPipeline
from .processing.pipeline import score_and_save_job
from .processing.scorer import Scorer
from .processing.vision import VisionPipeline, should_try_text_first
from .providers.gemini_provider import GeminiProvider
from .providers.groq_provider import GroqProvider
from .telegram.handlers import MessageHandler
from .telegram.listener import TelegramListener
from .telegram.notifier import TelegramNotifier
from .web_fetcher.scheduler import web_scheduler

logger = structlog.get_logger()


PENDING_STATUSES = {"PENDING_AI", "PENDING_VISION", "RATE_LIMITED"}
MAX_RETRIES = 3
# Quota tuning for the small Gemini free tier (resets midnight Pacific).
PER_MESSAGE_BACKOFF_SECONDS = 15 * 60  # each message retried at most every 15 min
VISION_PACING_SECONDS = 7  # minimum gap between vision calls
CIRCUIT_BREAKER_THRESHOLD = 3  # consecutive rate-limits before breaker opens
CIRCUIT_BREAKER_SLEEP_SECONDS = 30 * 60  # breaker sleep
RETRY_POLL_SECONDS = 60  # queue poll interval


def _backoff_expired(last_retry_at: str | None) -> bool:
    """True when a message is due for another attempt (15 min per-message backoff)."""
    if not last_retry_at:
        return True
    try:
        last = datetime.fromisoformat(last_retry_at)
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        elapsed = (datetime.now(UTC) - last).total_seconds()
        return elapsed >= PER_MESSAGE_BACKOFF_SECONDS
    except (ValueError, TypeError):
        return True


async def retry_worker(db_repo, handler, notifier):
    """Background task to retry PENDING_AI / PENDING_VISION / RATE_LIMITED messages.

    Quota-friendly: PENDING_* outcomes never consume retry_count, each
    message backs off 15 minutes between attempts, vision calls are paced
    7 seconds apart, and 3 consecutive rate-limits open a 30 minute
    circuit breaker.
    """
    consecutive_rate_limited = 0
    last_vision_monotonic = 0.0

    while True:
        try:
            if consecutive_rate_limited >= CIRCUIT_BREAKER_THRESHOLD:
                logger.warning("Circuit breaker open: sleeping after repeated rate limits")
                await asyncio.sleep(CIRCUIT_BREAKER_SLEEP_SECONDS)
                consecutive_rate_limited = 0
                continue

            pending = await db_repo.find_pending_messages()
            for msg in pending:
                msg_id = msg["id"]
                # Only hard failures consume retries; PENDING_* never increments
                # retry_count (see below), so this caps genuinely broken items.
                if msg["retry_count"] >= MAX_RETRIES:
                    await db_repo.update_message_status(
                        msg_id, ProcessingStatus.EXTRACTION_FAILED, "Max retries reached"
                    )
                    continue

                if not _backoff_expired(msg["last_retry_at"]):
                    continue

                logger.info(f"Retrying message {msg_id}")

                raw_text = msg["raw_text"]
                has_media = msg["has_media"]
                media_path = msg["media_path"]

                job_result, status = None, None
                if has_media and media_path:
                    # Long captions: try Groq text first to spare vision quota.
                    if should_try_text_first(raw_text):
                        job_result, status = await handler.extractor.run(raw_text)
                    if status not in ("PROCESSED", "NOT_JOB"):
                        wait = VISION_PACING_SECONDS - (time.monotonic() - last_vision_monotonic)
                        if wait > 0:
                            await asyncio.sleep(wait)
                        job_result, status = await handler.vision.run(media_path, raw_text)
                        last_vision_monotonic = time.monotonic()
                else:
                    job_result, status = await handler.extractor.run(raw_text)

                if status in PENDING_STATUSES:
                    # Still rate-limited: keep queued WITHOUT consuming
                    # retry_count; stamp last_retry_at for the backoff.
                    async with db_repo.write_lock:
                        await db_repo.conn.execute(
                            "UPDATE messages SET processing_status = ?, "
                            "last_retry_at = datetime('now') WHERE id = ?",
                            (status, msg_id),
                        )
                        await db_repo.conn.commit()
                    consecutive_rate_limited += 1
                    continue

                consecutive_rate_limited = 0

                if status == "NOT_JOB":
                    await db_repo.update_message_status(msg_id, status)
                    continue

                if status == "PROCESSED" and job_result:
                    # PRD F-DED-2: retry path must reuse the real pipeline so
                    # content_hash, dedup and score_breakdown stay consistent
                    # (was: content_hash="retried" hardcoded, broke dedup).
                    async with db_repo.write_lock:
                        await db_repo.conn.execute(
                            "UPDATE messages SET processing_status = ?, retry_count = 0, "
                            "last_retry_at = datetime('now') WHERE id = ?",
                            (ProcessingStatus.PROCESSED.value, msg_id),
                        )
                        await db_repo.conn.commit()
                    job_id, score, classification = await score_and_save_job(
                        db_repo, handler.scorer, msg_id, msg["source_id"], raw_text, job_result
                    )
                    if classification.value in ["APPLY", "REVIEW"]:
                        notif_id = await db_repo.insert_notification(job_id, notifier.user_chat_id)
                        if notif_id > 0:
                            # Fetch source metadata for t.me links (same as listener)
                            source_row = (
                                await db_repo.get_source(msg["source_id"])
                                if msg["source_id"]
                                else None
                            )
                            source_telegram_id = source_row["telegram_id"] if source_row else None
                            source_username = source_row["username"] if source_row else None
                            telegram_msg_id = msg["telegram_msg_id"]

                            payload = job_result.model_dump()
                            payload["match_score"] = score
                            payload["classification"] = classification.value
                            payload["raw_text"] = raw_text
                            payload["source_telegram_id"] = source_telegram_id
                            payload["source_username"] = source_username
                            payload["telegram_msg_id"] = telegram_msg_id
                            await notifier.send_job_alert(payload, notif_id)
                    continue

                # Hard failure (extraction/vision failed): consumes one retry.
                failed_status = (
                    ProcessingStatus.VISION_FAILED
                    if (has_media and media_path)
                    else ProcessingStatus.EXTRACTION_FAILED
                )
                async with db_repo.write_lock:
                    await db_repo.conn.execute(
                        "UPDATE messages SET retry_count = retry_count + 1, "
                        "last_retry_at = datetime('now') WHERE id = ?",
                        (msg_id,),
                    )
                    await db_repo.conn.commit()
                await db_repo.update_message_status(msg_id, failed_status)

            await asyncio.sleep(RETRY_POLL_SECONDS)  # Wait a minute before checking again
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in retry worker", error=str(e))
            await asyncio.sleep(RETRY_POLL_SECONDS)


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

    profile = CandidateProfile(professional_years=0)
    # Fail loud: a broken/missing profile silently degrades scoring to near-zero,
    # which was the root cause of "0/100" notifications (PRD section 1).
    try:
        profile = CandidateProfile.from_yaml("candidate_profile.yaml")
    except Exception as e:
        logger.error(
            "Failed to load candidate_profile.yaml — scoring will be degraded. "
            "Fix the file and restart.",
            error=str(e),
        )

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

    # Start Web Scheduler (PRD F-WEB-4: daily at 07:00, 11 boards)
    web_task = asyncio.create_task(web_scheduler(db_repo, extractor, scorer, config, notifier))

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
        web_task.cancel()
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
