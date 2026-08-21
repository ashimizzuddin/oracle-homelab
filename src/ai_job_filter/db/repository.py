import aiosqlite


class Repository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def insert_source(
        self,
        telegram_id: int,
        title: str,
        source_type: str = "CHANNEL",
        username: str | None = None,
    ) -> int:
        async with self.conn.execute(
            """
            INSERT INTO sources (telegram_id, title, source_type, username)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                title=excluded.title,
                username=excluded.username,
                updated_at=datetime('now')
            """,
            (telegram_id, title, source_type, username),
        ) as cursor:
            await self.conn.commit()
            if cursor.lastrowid:
                return cursor.lastrowid

            async with self.conn.execute(
                "SELECT id FROM sources WHERE telegram_id = ?", (telegram_id,)
            ) as c:
                row = await c.fetchone()
                return row["id"]

    async def insert_message(
        self, source_id: int, telegram_msg_id: int, raw_text: str, posted_at: str, **kwargs
    ) -> int:
        columns = ["source_id", "telegram_msg_id", "raw_text", "posted_at"]
        values = [source_id, telegram_msg_id, raw_text, posted_at]
        for k, v in kwargs.items():
            columns.append(k)
            values.append(v)

        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(columns)

        async with self.conn.execute(
            f"INSERT OR IGNORE INTO messages ({col_names}) VALUES ({placeholders})", values
        ) as cursor:
            await self.conn.commit()
            return cursor.lastrowid or 0

    async def update_message_status(self, msg_id: int, status: str, skip_reason: str | None = None):
        await self.conn.execute(
            "UPDATE messages SET processing_status = ?, skip_reason = ? WHERE id = ?",
            (status, skip_reason, msg_id),
        )
        await self.conn.commit()

    async def insert_job(
        self,
        message_id: int,
        source_id: int,
        title: str,
        content_hash: str,
        match_score: float,
        classification: str,
        **kwargs,
    ) -> int:
        columns = [
            "message_id",
            "source_id",
            "title",
            "content_hash",
            "match_score",
            "classification",
        ]
        values = [message_id, source_id, title, content_hash, match_score, classification]
        for k, v in kwargs.items():
            columns.append(k)
            values.append(v)

        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(columns)

        async with self.conn.execute(
            f"INSERT INTO jobs ({col_names}) VALUES ({placeholders})", values
        ) as cursor:
            await self.conn.commit()
            return cursor.lastrowid or 0

    async def find_message_by_hash(self, content_hash: str) -> aiosqlite.Row | None:
        async with self.conn.execute(
            "SELECT * FROM jobs WHERE content_hash = ? LIMIT 1", (content_hash,)
        ) as cursor:
            return await cursor.fetchone()

    async def find_message_by_dhash(self, dhash: str) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM messages WHERE media_dhash IS NOT NULL"
        ) as cursor:
            return await cursor.fetchall()

    async def find_recent_jobs(self, days: int = 30) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM jobs WHERE created_at >= datetime('now', ?)", (f"-{days} days",)
        ) as cursor:
            return await cursor.fetchall()

    async def find_pending_messages(self) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT * FROM messages WHERE processing_status IN ('PENDING_AI', 'PENDING_VISION', 'RATE_LIMITED')"
        ) as cursor:
            return await cursor.fetchall()

    async def insert_notification(
        self, job_id: int, chat_id: int, bot_message_id: int | None = None
    ) -> int:
        async with self.conn.execute(
            "SELECT id FROM notifications WHERE job_id = ?", (job_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return 0  # Already notified

        async with self.conn.execute(
            "INSERT INTO notifications (job_id, chat_id, bot_message_id) VALUES (?, ?, ?)",
            (job_id, chat_id, bot_message_id),
        ) as cursor:
            await self.conn.commit()
            return cursor.lastrowid or 0

    async def update_user_action(self, notif_id: int, action: str, notes: str | None = None):
        await self.conn.execute(
            "UPDATE notifications SET user_action = ?, user_notes = ?, action_at = datetime('now') WHERE id = ?",
            (action, notes, notif_id),
        )
        await self.conn.commit()
