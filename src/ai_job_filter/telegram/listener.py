from datetime import UTC, datetime, timedelta

import structlog
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from ..config import Settings

logger = structlog.get_logger()


class TelegramListener:
    def __init__(self, config: Settings, db_repo, handler, notifier):
        self.config = config
        self.db_repo = db_repo
        self.handler = handler
        self.notifier = notifier
        self.client = None

        session_str = (
            config.telegram_session_string.get_secret_value()
            if config.telegram_session_string
            else None
        )

        if config.telegram_api_id and config.telegram_api_hash and session_str:
            self.client = TelegramClient(
                StringSession(session_str),
                config.telegram_api_id,
                config.telegram_api_hash.get_secret_value(),
            )

    async def start(self):
        if not self.client:
            logger.error("Telethon not configured.")
            return

        await self.client.connect()
        if not await self.client.is_user_authorized():
            logger.error("Telegram session is unauthorized.")
            return

        logger.info("Telegram listener connected.")

    async def sync_history(self):
        if not self.client:
            return

        lookback = datetime.now(UTC) - timedelta(hours=self.config.history_lookback_hours)
        max_msgs = self.config.history_max_messages

        for identifier in self.config.channel_list:
            try:
                entity = await self.client.get_entity(identifier)
                source_id = await self.db_repo.insert_source(
                    telegram_id=entity.id,
                    title=getattr(entity, "title", str(identifier)),
                    username=getattr(entity, "username", None),
                )

                count = 0
                async for message in self.client.iter_messages(
                    entity, offset_date=lookback, limit=max_msgs
                ):
                    count += 1
                    result = await self.handler.handle_new_message(message, source_id)
                    await self._handle_notification(
                        result,
                        raw_text=message.text or "",
                        source_id=source_id,
                        msg_id=message.id,
                    )
                logger.info(f"Synced {count} historical messages for {identifier}")

            except Exception as e:
                logger.error(f"Failed to sync history for {identifier}", error=str(e))

        # Register real-time event listener
        @self.client.on(events.NewMessage(chats=self.config.channel_list))
        async def new_message_handler(event):
            try:
                entity = await self.client.get_entity(event.chat_id)
                source_id = await self.db_repo.insert_source(
                    telegram_id=entity.id,
                    title=getattr(entity, "title", str(event.chat_id)),
                    username=getattr(entity, "username", None),
                )
                result = await self.handler.handle_new_message(event.message, source_id)
                await self._handle_notification(
                    result,
                    raw_text=event.message.text or "",
                    source_id=source_id,
                    msg_id=event.message.id,
                )
            except Exception as e:
                logger.error("Error in real-time handler", error=str(e))

    async def _handle_notification(
        self, result, raw_text: str = "", source_id: int | None = None, msg_id: int | None = None
    ):
        if not result:
            return
        job_id, job_dict, classification = result
        # Duplicate safety: never send Telegram alerts for job-level duplicates.
        # The duplicate job row is kept as audit trail; only notification is suppressed.
        job = await self.db_repo.get_job(job_id)
        if job and job["is_duplicate"]:
            logger.info(
                "Skipping notification for duplicate job",
                job_id=job_id,
                parent=job["parent_job_id"],
            )
            return
        if classification.value in ["APPLY", "REVIEW"]:
            # Check if notification already exists for this job to prevent duplicates
            notif_id = await self.db_repo.insert_notification(job_id, self.config.user_chat_id)
            if notif_id > 0:
                # Enrich payload so notifier can render score, fallback link
                # (t.me/c/{source}/{msg}) and fallback summary (PRD F-NOT-1/2).
                # Use the already-fetched job row for accurate score (get_job_by_message_id
                # was broken: it expects internal messages.id but received telegram message.id)
                if job:
                    # job row now contains full job data (SELECT *) including match_score
                    job_dict["match_score"] = job["match_score"]
                    job_dict["application_url"] = (
                        job_dict.get("application_url") or job["application_url"]
                    )
                    job_dict["summary"] = job_dict.get("summary") or job["summary"]
                else:
                    # Fallback: try fetching by job_id again
                    job_row = await self.db_repo.get_job(job_id)
                    if job_row:
                        job_dict["match_score"] = job_row["match_score"]
                        job_dict["application_url"] = (
                            job_dict.get("application_url") or job_row["application_url"]
                        )
                        job_dict["summary"] = job_dict.get("summary") or job_row["summary"]

                # Fetch source metadata for building t.me links (F-NOT-1 fix)
                source_row = await self.db_repo.get_source(source_id) if source_id else None
                source_telegram_id = source_row["telegram_id"] if source_row else None
                source_username = source_row["username"] if source_row else None

                # Fetch message to get telegram_msg_id (not internal messages.id)
                message_row = await self.db_repo.get_message(job["message_id"]) if job else None
                telegram_msg_id = message_row["telegram_msg_id"] if message_row else None

                job_dict["raw_text"] = raw_text
                job_dict["source_telegram_id"] = source_telegram_id
                job_dict["source_username"] = source_username
                job_dict["telegram_msg_id"] = telegram_msg_id
                job_dict.setdefault("classification", classification.value)
                await self.notifier.send_job_alert(job_dict, notif_id)

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
