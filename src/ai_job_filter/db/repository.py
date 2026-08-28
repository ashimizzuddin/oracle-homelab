import asyncio

import aiosqlite


class Repository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn
        # Serialize DB writes across concurrent coroutines (listener,
        # retry worker) sharing one connection. Prevents
        # 'cannot commit transaction - SQL statements in progress'.
        self.write_lock = asyncio.Lock()

    async def insert_source(
        self,
        telegram_id: int,
        title: str,
        source_type: str = "CHANNEL",
        username: str | None = None,
    ) -> int:
        async with self.write_lock, self.conn.execute(
            """
                INSERT INTO sources (telegram_id, title, source_type, username)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    title=excluded.title,
                    username=excluded.username,
                    updated_at=datetime('now')
                RETURNING id
                """,
            (telegram_id, title, source_type, username),
        ) as cursor:
            row = await cursor.fetchone()
            await self.conn.commit()
            if row and row["id"]:
                return row["id"]

            # Fallback (should not happen, but be safe)
            async with self.conn.execute(
                "SELECT id FROM sources WHERE telegram_id = ?", (telegram_id,)
            ) as c:
                row = await c.fetchone()
                return row["id"]

    async def insert_message(
        self, source_id: int, telegram_msg_id: int, raw_text: str, posted_at: str, **kwargs
    ) -> int:
        async with self.write_lock:
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
        # Uses write_lock: called concurrently by listener + retry_worker sharing
        # one connection (prevents 'cannot commit transaction' race).
        async with self.write_lock:
            await self.conn.execute(
                "UPDATE messages SET processing_status = ?, skip_reason = ? WHERE id = ?",
                (status, skip_reason, msg_id),
            )
            await self.conn.commit()

    async def update_message_hashes(self, msg_id: int, **kwargs):
        """Persist media_sha256 / media_dhash / media_path / media_type (PRD F-DED-1)."""
        allowed = {"media_sha256", "media_dhash", "media_path", "media_type"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return
        async with self.write_lock:
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            values = [*updates.values(), msg_id]
            await self.conn.execute(f"UPDATE messages SET {set_clause} WHERE id = ?", values)
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
        async with self.write_lock:
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

    async def get_job(self, job_id: int) -> aiosqlite.Row | None:
        """Fetch a single job row by id (used for duplicate-notification guard)."""
        async with self.conn.execute(
            "SELECT id, is_duplicate, parent_job_id FROM jobs WHERE id = ? LIMIT 1", (job_id,)
        ) as cursor:
            return await cursor.fetchone()

    async def find_message_by_dhash(self, dhash: str, max_distance: int = 12) -> list[aiosqlite.Row]:
        """Fetch candidate rows for perceptual image dedup.

        Uses a coarse bit-prefix prefilter on the dhash hex string to avoid a
        full table scan, then callers refine with exact hamming distance.
        (dhash stored as 16-hex-char string = 64 bits; a low hamming distance
        implies at least the first hex char often matches.)
        """
        # Prefetch: same first char OR same second char narrows candidates
        # dramatically while still catching near-duplicates.
        prefix_a, prefix_b = dhash[:2], dhash[2:4]
        async with self.conn.execute(
            """
            SELECT * FROM messages
            WHERE media_dhash IS NOT NULL
              AND (media_dhash LIKE ? || '%' OR media_dhash LIKE ? || '%')
            """,
            (prefix_a, prefix_b),
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
        async with self.write_lock:
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
        async with self.write_lock:
            await self.conn.execute(
                "UPDATE notifications SET user_action = ?, user_notes = ?, action_at = datetime('now') WHERE id = ?",
                (action, notes, notif_id),
            )
            await self.conn.commit()

    async def get_message(self, message_id: int) -> aiosqlite.Row | None:
        async with self.write_lock, self.conn.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        ) as cursor:
            return await cursor.fetchone()

    async def get_job_by_message_id(self, message_id: int) -> aiosqlite.Row | None:
        async with self.conn.execute(
            "SELECT * FROM jobs WHERE message_id = ?", (message_id,)
        ) as cursor:
            return await cursor.fetchone()

    async def update_job(self, job_id: int, **kwargs) -> None:
        if not kwargs:
            return

        async with self.write_lock:

            protected = {"id", "message_id", "source_id", "content_hash"}
            update_cols = {k: v for k, v in kwargs.items() if k not in protected}

            if not update_cols:
                return

            cols = list(update_cols.keys())
            set_clause = ", ".join(f"{col} = ?" for col in cols)
            values = [update_cols[col] for col in cols]
            values.append(job_id)

            await self.conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
            await self.conn.commit()

    # ------------------------------------------------------------------
    # Fetcher state (PRD F-WEB-3) — DB-backed, replaces *_seen.json files
    # ------------------------------------------------------------------

    async def get_fetcher_state(self, source: str) -> tuple[list[str], str | None]:
        """Return (seen_slugs, last_run_at) for a fetcher source."""
        async with self.conn.execute(
            "SELECT seen_slugs, last_run_at FROM fetcher_state WHERE source = ?", (source,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return [], None
        try:
            import json

            slugs = json.loads(row["seen_slugs"] or "[]")
        except (ValueError, TypeError):
            slugs = []
        return slugs, row["last_run_at"]

    async def save_fetcher_state(
        self, source: str, seen_slugs: list[str], status: str = "ok", stats: dict | None = None
    ) -> None:
        import json

        async with self.write_lock:
            await self.conn.execute(
                """
                INSERT INTO fetcher_state (source, last_run_at, last_status, seen_slugs, stats)
                VALUES (?, datetime('now'), ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_run_at=excluded.last_run_at,
                    last_status=excluded.last_status,
                    seen_slugs=excluded.seen_slugs,
                    stats=excluded.stats
                """,
                (
                    source,
                    status,
                    json.dumps(sorted(seen_slugs)),
                    json.dumps(stats or {}),
                ),
            )
            await self.conn.commit()
