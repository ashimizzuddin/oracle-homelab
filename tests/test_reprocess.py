from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from ai_job_filter.config import Settings
from ai_job_filter.models.job import JobExtractionResult
from ai_job_filter.providers.errors import TransientAPIError
from ai_job_filter.reprocess import reprocess_failed_messages


@pytest.fixture
async def setup_db(tmp_path):
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        with open("migrations/001_initial_schema.sql") as f:
            await conn.executescript(f.read())

        await conn.execute("INSERT INTO sources (telegram_id, title) VALUES (1, 'test')")

        # Insert test messages
        await conn.execute(
            "INSERT INTO messages (source_id, telegram_msg_id, raw_text, has_media, media_path, processing_status, posted_at) VALUES (1, 100, 'Test 1', 0, NULL, 'EXTRACTION_FAILED', '2023-01-01')"
        )
        await conn.execute(
            "INSERT INTO messages (source_id, telegram_msg_id, raw_text, has_media, media_path, processing_status, posted_at, retry_count) VALUES (1, 101, 'Test 2', 0, NULL, 'EXTRACTION_FAILED', '2023-01-02', 3)"
        )
        await conn.execute(
            "INSERT INTO messages (source_id, telegram_msg_id, raw_text, has_media, media_path, processing_status, posted_at) VALUES (1, 102, 'Test 3', 1, '/invalid/path.jpg', 'VISION_FAILED', '2023-01-03')"
        )

        await conn.commit()

        yield conn


@pytest.fixture
def mock_pipelines():
    extractor = AsyncMock()
    vision = AsyncMock()
    scorer = MagicMock()

    # Setup mock successful extraction
    job_res = JobExtractionResult(
        is_job_posting=True, title="Mock Job", min_years_exp=0, contacts={}
    )
    extractor.run.return_value = (job_res, "PROCESSED")

    # Setup mock scorer
    import enum

    class MockClass(enum.Enum):
        MATCH = "MATCH"

    scorer.score_job.return_value = (80.0, MockClass.MATCH, "none")

    return extractor, vision, scorer


@pytest.mark.asyncio
async def test_dry_run_no_mutations(setup_db, mock_pipelines):
    conn = setup_db
    extractor, vision, scorer = mock_pipelines

    stats = await reprocess_failed_messages(
        conn, Settings(), extractor, vision, scorer, execute=False
    )

    assert stats.mode == "DRY RUN"
    assert stats.candidates_found == 3
    assert stats.skipped_limit == 1
    assert stats.skipped_media == 1
    assert stats.eligible == 1
    assert stats.success == 1

    # Verify no DB changes
    async with conn.execute(
        "SELECT processing_status FROM messages WHERE telegram_msg_id = 100"
    ) as c:
        assert (await c.fetchone())[0] == "EXTRACTION_FAILED"


@pytest.mark.asyncio
async def test_execute_mutations(setup_db, mock_pipelines):
    conn = setup_db
    extractor, vision, scorer = mock_pipelines

    stats = await reprocess_failed_messages(
        conn, Settings(), extractor, vision, scorer, execute=True
    )

    assert stats.mode == "EXECUTE"
    assert stats.success == 1

    # Verify DB changes
    async with conn.execute(
        "SELECT processing_status FROM messages WHERE telegram_msg_id = 100"
    ) as c:
        assert (await c.fetchone())[0] == "PROCESSED"

    async with conn.execute("SELECT title FROM jobs WHERE message_id = 1") as c:
        assert (await c.fetchone())[0] == "Mock Job"

    # Verify skipped media
    async with conn.execute(
        "SELECT processing_status, skip_reason FROM messages WHERE telegram_msg_id = 102"
    ) as c:
        row = await c.fetchone()
        assert row[0] == "SKIPPED"
        assert row[1] == "media_unavailable_for_reprocess"


@pytest.mark.asyncio
async def test_force_flag(setup_db, mock_pipelines):
    conn = setup_db
    extractor, vision, scorer = mock_pipelines

    stats = await reprocess_failed_messages(
        conn, Settings(), extractor, vision, scorer, force=True, execute=True
    )

    assert stats.skipped_limit == 0
    assert stats.success == 2


@pytest.mark.asyncio
async def test_transient_failure_storage(setup_db, mock_pipelines):
    conn = setup_db
    extractor, vision, scorer = mock_pipelines

    # Make the extractor fail
    extractor.run.side_effect = TransientAPIError("API Down")

    stats = await reprocess_failed_messages(
        conn, Settings(), extractor, vision, scorer, execute=True
    )

    assert stats.success == 0
    assert stats.failed == 1

    async with conn.execute(
        "SELECT retry_count, skip_reason FROM messages WHERE telegram_msg_id = 100"
    ) as c:
        row = await c.fetchone()
        assert row[0] == 1  # Incremented
        assert row[1] == "provider_transient_error"  # Concise string


@pytest.mark.asyncio
async def test_not_job_tracking(setup_db, mock_pipelines):
    conn = setup_db
    extractor, vision, scorer = mock_pipelines

    # Make the extractor return NOT_JOB
    extractor.run.return_value = (None, "NOT_JOB")

    stats = await reprocess_failed_messages(
        conn, Settings(), extractor, vision, scorer, execute=True
    )

    assert stats.not_job == 1
    assert stats.success == 0
    assert stats.failed == 0

    # NOT_JOB must NOT increment retry_count
    async with conn.execute(
        "SELECT processing_status, retry_count FROM messages WHERE telegram_msg_id = 100"
    ) as c:
        row = await c.fetchone()
        assert row[0] == "NOT_JOB"
        assert row[1] == 0  # Unchanged

    # No jobs row created
    async with conn.execute("SELECT COUNT(*) FROM jobs") as c:
        assert (await c.fetchone())[0] == 0
