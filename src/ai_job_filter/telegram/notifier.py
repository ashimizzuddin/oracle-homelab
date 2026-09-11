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
        # PRD F-NOT-1, F-NOT-2, F-NOT-3: notif always has link + summary + hidden empty salary
        self.min_score_to_notify = config.min_score_review

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
    def _build_telegram_link(
        telegram_id: int | None, username: str | None, message_id: int | None
    ) -> str | None:
        """Build t.me deep link to the original Telegram message (F-NOT-1).

        Args:
            telegram_id: Telegram's raw ID (negative for supergroups/channels)
            username: Channel/group username (e.g. "LowonganKerjaIT")
            message_id: Telegram message ID

        Returns:
            https://t.me/c/{stripped_id}/{msg_id} for negative IDs,
            https://t.me/{username}/{msg_id} for usernames,
            None if unable to build.
        """
        if message_id is None:
            return None

        # Priority 1: Use username if available (more user-friendly)
        if username and isinstance(username, str):
            clean_username = username.strip().lstrip("@")
            if clean_username:
                return f"https://t.me/{clean_username}/{message_id}"

        # Priority 2: Use negative telegram_id for supergroups/channels
        if telegram_id is not None:
            try:
                tid = int(telegram_id)
                if tid < 0:
                    stripped = str(-tid)
                    if stripped.startswith("100"):
                        stripped = stripped[3:]
                    return f"https://t.me/c/{stripped}/{message_id}"
            except (TypeError, ValueError):
                pass

        return None

    @staticmethod
    def _render_contacts(contacts: dict | None) -> list[str]:
        """Render valid contacts as clickable HTML links (Opsi B).

        Returns list of formatted contact strings with mailto:, tel:, wa.me, t.me links.
        """
        from ..processing.apply_method import (
            is_valid_email,
            is_valid_phone,
            is_valid_telegram_handle,
        )

        if not contacts or not isinstance(contacts, dict):
            return []

        rendered = []

        # Emails -> mailto:
        emails = contacts.get("emails") or []
        for email in emails:
            if is_valid_email(email):
                rendered.append(f'<a href="mailto:{escape(email)}">📧 {escape(email)}</a>')

        # Phone numbers -> tel:
        phones = contacts.get("phone_numbers") or []
        for phone in phones:
            if is_valid_phone(phone):
                normalized = phone.strip()
                rendered.append(f'<a href="tel:{escape(normalized)}">📱 {escape(normalized)}</a>')

        # WhatsApp -> wa.me
        whatsapp = contacts.get("whatsapp") or []
        for wa in whatsapp:
            if is_valid_phone(wa):
                # wa.me expects international format without + or spaces
                normalized = wa.strip().lstrip("+").replace(" ", "").replace("-", "")
                rendered.append(f'<a href="https://wa.me/{normalized}">💬 WA: {escape(wa)}</a>')

        # Telegram handles -> t.me
        handles = contacts.get("telegram_handles") or []
        for handle in handles:
            if is_valid_telegram_handle(handle):
                clean = handle.strip().lstrip("@")
                rendered.append(f'<a href="https://t.me/{clean}">✈️ @{escape(clean)}</a>')

        return rendered

    async def send_job_alert(self, job_dict: dict, notification_id: int):
        score = job_dict.get("match_score", 0)

        # F-NOT-4: skip IGNORE classification
        classification = (job_dict.get("classification") or "").upper()
        if classification == "IGNORE" or score < self.min_score_to_notify:
            logger.info(
                "Skipping notification (below threshold)",
                score=score,
                classification=classification,
                title=job_dict.get("title"),
            )
            return

        # Header: F-NOT-5 emoji X/100 | title
        title = escape(job_dict.get("title") or "Unknown Role")
        company = escape(job_dict.get("company") or "Unknown Company")

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

        # F-NOT-1 + Opsi B: application_url, else t.me link, else render contacts
        url = (job_dict.get("application_url") or "").strip()
        if url:
            msg += f'🔗 <a href="{escape(url)}">{escape(url)}</a>\n'
        else:
            # Try building Telegram link (needs telegram_id + username from source)
            tg_link = self._build_telegram_link(
                job_dict.get("source_telegram_id"),
                job_dict.get("source_username"),
                job_dict.get("telegram_msg_id"),
            )
            if tg_link:
                msg += f'🔗 <a href="{tg_link}">View in Telegram</a>\n'
            else:
                msg += "🔗 No direct link\n"

            # Render contacts as clickable links (Opsi B)
            contacts = job_dict.get("contacts")
            contact_links = self._render_contacts(contacts)
            if contact_links:
                for link in contact_links:
                    msg += f"{link}\n"
            else:
                msg += "📝 Check raw message for contact info\n"

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
