from html import escape

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from ..config import Settings

logger = structlog.get_logger()


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
            # Do NOT log the token
            self.app = Application.builder().token(token).build()
            self.app.add_handler(CallbackQueryHandler(self._handle_callback))

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        chat_id = query.message.chat.id

        # Security Boundary: Reject unauthorized users/chats immediately
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

        # Update Database
        await self.db_repo.update_user_action(notif_id, db_action)

        # Edit message to remove buttons and show status
        # Note: query.message.text gives plain text (HTML tags stripped).
        # For simplicity, we just append the status.
        # Escape it just in case it contained < > that would now be interpreted.
        original_text = escape(query.message.text or "")
        new_text = f"{original_text}\n\n<b>Status:</b> {db_action}"
        await query.edit_message_text(text=new_text, parse_mode=ParseMode.HTML)
        logger.info("User action recorded", notif_id=notif_id, action=db_action)

    async def send_job_alert(self, job_dict: dict, notification_id: int):
        title = escape(job_dict.get("title", "Unknown Role"))
        company = escape(job_dict.get("company", "Unknown Company"))
        score = job_dict.get("match_score", 0)

        msg = f"🌟 <b>{score}/100 | {title}</b>\n"
        msg += f"🏢 {company}\n"

        location = escape(job_dict.get("location") or "N/A")
        msg += f"📍 {location}\n"

        salary_str = (
            f"{job_dict.get('salary_min')}-{job_dict.get('salary_max')}"
            if job_dict.get("salary_min")
            else "N/A"
        )
        msg += f"💰 {escape(salary_str)}\n\n"

        summary_raw = job_dict.get("summary", "")
        summary = escape(summary_raw[:200]) + "..." if summary_raw else ""
        msg += f"📝 {summary}\n\n"

        url = escape(job_dict.get("application_url") or "See contacts in raw message")
        msg += f"🔗 {url}"

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
            print("[DRY RUN] Would send notification (ParseMode: HTML):")
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
