import asyncio
import contextlib
import os
import signal
import time

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
from .processing.vision import VisionPipeline
from .providers.gemini_provider import GeminiProvider
from .providers.groq_provider import GroqProvider
from .telegram.handlers import MessageHandler
from .telegram.listener import TelegramListener
from .telegram.notifier import TelegramNotifier
from .web_fetcher.scheduler import web_scheduler

logger = structlog.get_logger()


async def retry_worker(db_repo, handler, notifier, config=None):
    """Background task to retry PENDING_AI / PENDING_VISION / RATE_LIMITED.

    Quota-aware (Gemini free tier ~10 RPM / 20 RPD):
    - PENDING_* results do NOT consume retry_count; only last_retry_at is
      touched. retry_count is reserved for real terminal failures.
    - Per-message backoff (default 15 min) + per-item pacing (default 7s)
      + circuit breaker (30 min) after consecutive rate limits.
    - Missing media files are skipped without burning quota or retries.
    """
    from .providers.rate_budget import PENDING_STATUSES

    base_delay = getattr(config, "retry_base_delay_seconds", 300)
    per_item_delay = getattr(config, "retry_per_item_delay_seconds", 7)
    msg_backoff = getattr(config, "retry_per_message_backoff_seconds", 900)
    max_attempts = getattr(config, "retry_max_attempts", 5)

    consecutive_limited = 0

    while True:
        try:
            pending = await db_repo.find_pending_messages()
            processed_any = False

            for msg in pending:
                msg_id = msg["id"]

                if msg["retry_count"] >= max_attempts:
                    await db_repo.update_message_status(
                        msg_id, ProcessingStatus.EXTRACTION_FAILED, "Max retries reached"
                    )
                    continue

                # Per-message backoff: don't hammer the same row every loop.
                last_retry = msg["last_retry_at"]
                if last_retry:
                    try:
                        # SQLite datetime('now') -> 'YYYY-MM-DD HH:MM:SS' (UTC).
                        last_ts = time.mktime(
                            time.strptime(str(last_retry)[:19], "%Y-%m-%d %H:%M:%S")
                        )
                        if time.time() - last_ts < msg_backoff:
                            continue
                    except (ValueError, TypeError, OverflowError):
                        pass

                raw_text = msg["raw_text"]
                has_media = msg["has_media"]
                media_path = msg["media_path"]

                use_vision = bool(has_media and media_path)
                if use_vision and not os.path.exists(media_path):
                    # File was deleted after first attempt (handlers.py cleanup).
                    # Keep queued without burning quota/retries; manual
                    # reprocess CLI will mark it SKIPPED if truly unavailable.
                    logger.info("Retry skipped: media file gone", msg_id=msg_id)
                    async with db_repo.write_lock:
                        await db_repo.conn.execute(
                            "UPDATE messages SET last_retry_at = datetime('now') WHERE id = ?",
                            (msg_id,),
                        )
                        await db_repo.conn.commit()
                    continue

                logger.info(f"Retrying message {msg_id}")

                if use_vision:
                    job_result, status = await handler.vision.run(media_path, raw_text)
                else:
                    job_result, status = await handler.extractor.run(raw_text)

                if status in PENDING_STATUSES:
                    # Still quota-limited: touch timestamp only, keep retry_count.
                    consecutive_limited += 1
                    async with db_repo.write_lock:
                        await db_repo.conn.execute(
                            "UPDATE messages SET last_retry_at = datetime('now') WHERE id = ?",
                            (msg_id,),
                        )
                        await db_repo.conn.commit()
                    await db_repo.update_message_status(msg_id, status)
                    # Pace vision calls under the RPM budget.
                    if use_vision:
                        await asyncio.sleep(per_item_delay)
                    continue

                consecutive_limited = 0
                processed_any = True

                if status == "PROCESSED" and job_result:
                    async with db_repo.write_lock:
                        await db_repo.conn.execute(
                            "UPDATE messages SET retry_count = 0, last_retry_at = datetime('now') WHERE id = ?",
                            (msg_id,),
                        )
                        await db_repo.conn.commit()
                    await db_repo.update_message_status(msg_id, status)
                    # PRD F-DED-2: retry path must reuse the real pipeline so
                    # content_hash, dedup and score_breakdown stay consistent
                    # (was: content_hash="retried" hardcoded, broke dedup).
                    job_id, score, classification = await score_and_save_job(
                        db_repo, handler.scorer, msg_id, msg["source_id"], raw_text, job_result
                    )
                    if classification.value in ["APPLY", "REVIEW"]:
                        notif_id = await db_repo.insert_notification(job_id, notifier.user_chat_id)
                        if notif_id > 0:
                            payload = job_result.model_dump()
                            payload["match_score"] = score
                            payload["classification"] = classification.value
                            payload["raw_text"] = raw_text
                            payload["message_id"] = msg_id
                            payload["source_id"] = msg["source_id"]
                            await notifier.send_job_alert(payload, notif_id)
                else:
                    # Terminal failure for this attempt: count it.
                    async with db_repo.write_lock:
                        await db_repo.conn.execute(
                            "UPDATE messages SET retry_count = retry_count + 1, last_retry_at = datetime('now') WHERE id = ?",
                            (msg_id,),
                        )
                        await db_repo.conn.commit()
                    await db_repo.update_message_status(msg_id, status)

                if use_vision:
                    await asyncio.sleep(per_item_delay)

            # Circuit breaker: sustained 429s -> sleep 30 min (quota resets
            # at midnight Pacific; tight loops only burn RPD faster).
            if consecutive_limited >= 3:
                logger.warning(
                    "Retry worker circuit breaker: sustained rate limits, sleeping 30m",
                    consecutive=consecutive_limited,
                )
                consecutive_limited = 0
                await asyncio.sleep(1800)
            elif processed_any:
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(base_delay)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in retry worker", error=str(e))
            await asyncio.sleep(base_delay)


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
        max_rpm=config.gemini_max_rpm,
        max_rpd=config.gemini_max_rpd,
        budget_path=config.gemini_budget_path,
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
    worker_task = asyncio.create_task(retry_worker(db_repo, handler, notifier, config))

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
