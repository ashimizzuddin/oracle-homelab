import asyncio
import aiosqlite
from ai_job_filter.config import Settings
from ai_job_filter.reprocess import reprocess_failed_messages
from unittest.mock import MagicMock, AsyncMock
from ai_job_filter.db.repository import Repository

async def test_it():
    settings = Settings()
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        with open("migrations/001_initial_schema.sql") as f:
            await conn.executescript(f.read())
            
        repo = Repository(conn)
        src = await repo.insert_source(1, "Test")
        # Insert a 7 hours old message (simulating the user's thought process)
        msg_id = await repo.insert_message(src, 1, "test", "test")
        await conn.execute("UPDATE messages SET scraped_at = datetime('now', '-7 hours')")
        await conn.commit()
        
        mock_e = MagicMock()
        mock_e.run = AsyncMock(return_value=(None, "NOT_JOB"))
        mock_v = MagicMock()
        mock_s = MagicMock()
        
        stats = await reprocess_failed_messages(conn, settings, mock_e, mock_v, mock_s, message_id=msg_id)
        print(f"Candidates found: {stats.candidates_found}")

asyncio.run(test_it())
