from html import escape

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from ..config import Settings

logger = structlog.get_logger()

# PRD F-NOT-1, F-NOT-2, F-NOT-3: notif always has link + summary + hidden empty salary
MIN_SCORE_TO_NOTIFY = 55


class TelegramNotifier:
    def __init__(self, config: Settings, db_repo):
        self.config = config
        self.db_repo = db_repo
        self.app = None
        self.user_chat_id = config.user_chat_id
        self.authorized_user_id = config.authorized_user_id
        self.dry_run = config.dry_run

        if config.telegram_bot_token and self.user_chat_id:
            token = config.telegram_bot_token.get_secret_value()
            self.app = Application.builder().token(token).build()
            self.app.add_handler(CallbackQueryHandler(self._handle_callback))

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        chat_id = query.message.chat.id

        if user_id != self.authorized_user_id or chat_id != self.user_chat_id:
            logger.warning(f"Unauthorized callback attempt. User: {user_id}, Chat: {chat_id}")
            await query.answer("Unauthorized.", show_alert=True)
            return

        await query.answer()
        data = query.data
        if not data.startswith("act_"):
            return

        parts = data.split("_")
        if len(parts) != 3:
            return

        action = parts[1]
        notif_id_str = parts[2]

        try:
            notif_id = int(notif_id_str)
        except ValueError:
            return

        action_map = {"a": "APPLIED", "s": "SAVED", "x": "SKIPPED"}
        db_action = action_map.get(action)
        if not db_action:
            return

        await self.db_repo.update_user_action(notif_id, db_action)

        original_text = escape(query.message.text or "")
        new_text = f"{original_text}\n\n<b>Status:</b> {db_action}"
        await query.edit_message_text(text=new_text, parse_mode=ParseMode.HTML)
        logger.info("User action recorded", notif_id=notif_id, action=db_action)

    @staticmethod
    def _build_telegram_link(source_id: int | None, message_id: int | None) -> str | None:
        """Build t.me deep link to the original Telegram message (F-NOT-1).

        Telegram supergroup channel IDs are negative and start with -100.
        Chat IDs for groups/channels follow pattern -100XXXXXXXXXX.
        """
        if source_id is None or message_id is None:
            return None
        try:
            sid = int(source_id)
        except (TypeError, ValueError):
            return None
        if sid < 0:
            stripped = str(-sid)
            if stripped.startswith("100"):
                stripped = stripped[3:]
            return f"https://t.me/c/{stripped}/{message_id}"
        return None

    async def send_job_alert(self, job_dict: dict, notification_id: int):
        score = job_dict.get("match_score", 0)

        # F-NOT-4: skip IGNORE classification
        classification = (job_dict.get("classification") or "").upper()
        if classification == "IGNORE" or score < MIN_SCORE_TO_NOTIFY:
            logger.info(
                "Skipping notification (below threshold)",
                score=score,
                classification=classification,
                title=job_dict.get("title"),
            )
            return

        # Header: F-NOT-5 emoji X/100 | title
        title = escape(job_dict.get("title", "Unknown Role"))
        company = escape(job_dict.get("company", "Unknown Company"))

        msg = f"🌟 <b>{score}/100 | {title}</b>\n"
        msg += f"🏢 {company}\n"

        location = escape(job_dict.get("location") or "N/A")
        msg += f"📍 {location}\n"

        # F-NOT-3: hide salary row when neither min nor max is present
        salary_min = job_dict.get("salary_min")
        salary_max = job_dict.get("salary_max")
        if salary_min is not None or salary_max is not None:
            sm = "" if salary_min is None else f"{salary_min}"
            smax = "" if salary_max is None else f"{salary_max}"
            salary_str = f"{sm}-{smax}" if sm and smax else (sm or smax)
            msg += f"💰 {escape(salary_str)}\n"

        msg += "\n"

        # F-NOT-2: fallback summary to first 3 lines of raw_text when missing
        summary_raw = (job_dict.get("summary") or "").strip()
        if summary_raw:
            summary = escape(summary_raw[:200]) + ("..." if len(summary_raw) > 200 else "")
            msg += f"📝 {summary}\n\n"
        else:
            raw_text = (job_dict.get("raw_text") or "").strip()
            if raw_text:
                lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()][:3]
                fallback = escape("\n".join(lines)[:300])
                msg += f"📝 {fallback}\n\n"
            else:
                msg += "\n"

        # F-NOT-1: application_url, else Telegram source link
        url = (job_dict.get("application_url") or "").strip()
        if not url:
            tg_link = self._build_telegram_link(
                job_dict.get("source_id"), job_dict.get("message_id")
            )
            url = tg_link or "See contacts in raw message"
        msg += f"🔗 {escape(url)}"

        keyboard = [
            [
                InlineKeyboardButton("✅ Apply", callback_data=f"act_a_{notification_id}"),
                InlineKeyboardButton("💾 Save", callback_data=f"act_s_{notification_id}"),
                InlineKeyboardButton("❌ Skip", callback_data=f"act_x_{notification_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if self.dry_run:
            print("\n" + "=" * 40)
            print(f"[DRY RUN] Would send notification (score={score}, class={classification}, ParseMode: HTML):")
            print(msg)
            print("Buttons: [Apply] [Save] [Skip]")
            print("=" * 40 + "\n")
            return

        if not self.app or not self.user_chat_id:
            logger.error("Bot not configured, cannot send alert.")
            return

        await self.app.bot.send_message(
            chat_id=self.user_chat_id,
            text=msg,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
