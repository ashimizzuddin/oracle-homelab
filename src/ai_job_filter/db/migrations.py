import os

import aiosqlite


async def apply_migrations(conn: aiosqlite.Connection, migrations_dir: str = "migrations"):
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now')),
            description TEXT
        )
    """)
    await conn.commit()

    if not os.path.isdir(migrations_dir):
        return

    async with conn.execute("SELECT version FROM schema_version") as cursor:
        rows = await cursor.fetchall()
        applied = {row["version"] for row in rows}

    files = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
    for file in files:
        version_str = file.split("_")[0]
        try:
            version = int(version_str)
        except ValueError:
            continue

        if version not in applied:
            with open(os.path.join(migrations_dir, file)) as f:
                sql = f.read()
            await conn.executescript(sql)
            await conn.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)", (version, file)
            )
            await conn.commit()
