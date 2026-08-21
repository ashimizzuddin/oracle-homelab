import os

import aiosqlite


async def get_connection(db_path: str) -> aiosqlite.Connection:
    """Create aiosqlite connection, ensuring parent directory exists."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA synchronous = NORMAL")
    await conn.execute("PRAGMA busy_timeout = 5000")
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA cache_size = -64000")
    conn.row_factory = aiosqlite.Row
    return conn
