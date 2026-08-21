from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from ai_job_filter.config import Settings
from ai_job_filter.db.repository import Repository
from ai_job_filter.models.enums import Classification
from ai_job_filter.models.job import JobExtractionResult
from ai_job_filter.reprocess import reprocess_failed_messages


@pytest.fixture
async def mem_db():
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        with open("migrations/001_initial_schema.sql") as f:
            await conn.executescript(f.read())
        yield conn


@pytest.fixture
def mock_extractor():
    extractor = MagicMock()
    extractor.run = AsyncMock()
    return extractor


@pytest.fixture
def mock_vision():
    vision = MagicMock()
    vision.run = AsyncMock()
    return vision


@pytest.fixture
def mock_scorer():
    scorer = MagicMock()
    scorer.score_job.return_value = (85.0, Classification.APPLY, None)
    return scorer


@pytest.fixture
def settings():
    s = Settings()
    s.stale_pending_minutes = 15
    return s


def get_job_result():
    return JobExtractionResult(is_job_posting=True, title="Software Engineer", company="Acme Corp")


async def setup_message(mem_db, processing_status, minutes_ago, has_media=0, media_path=None):
    repo = Repository(mem_db)
    source_id = await repo.insert_source(12345, "Test Group")
    msg_id = await repo.insert_message(
        source_id, 101, "Test", "2023-01-01T12:00:00Z", has_media=has_media, media_path=media_path
    )
    await mem_db.execute(
        f"UPDATE messages SET processing_status = '{processing_status}', scraped_at = datetime('now', '-{minutes_ago} minutes') WHERE id = ?",
        (msg_id,),
    )
    await mem_db.commit()
    return msg_id, source_id


@pytest.mark.asyncio
async def test_fresh_pending_not_eligible(
    mem_db, settings, mock_extractor, mock_vision, mock_scorer
):
    _msg_id, _ = await setup_message(mem_db, "PENDING", 5)  # 5 minutes ago (fresh)
    stats = await reprocess_failed_messages(
        mem_db, settings, mock_extractor, mock_vision, mock_scorer
    )
    assert stats.candidates_found == 0
    assert stats.eligible == 0


@pytest.mark.asyncio
async def test_stale_pending_eligible(mem_db, settings, mock_extractor, mock_vision, mock_scorer):
    _msg_id, _ = await setup_message(mem_db, "PENDING", 20)  # 20 minutes ago (stale)
    mock_extractor.run.return_value = (get_job_result(), "PROCESSED")
    stats = await reprocess_failed_messages(
        mem_db, settings, mock_extractor, mock_vision, mock_scorer, execute=True
    )
    assert stats.candidates_found == 1
    assert stats.eligible == 1
    assert stats.success == 1


@pytest.mark.asyncio
async def test_message_id_fresh_pending_remains_ineligible(
    mem_db, settings, mock_extractor, mock_vision, mock_scorer
):
    msg_id, _ = await setup_message(mem_db, "PENDING", 5)
    stats = await reprocess_failed_messages(
        mem_db, settings, mock_extractor, mock_vision, mock_scorer, message_id=msg_id
    )
    assert stats.candidates_found == 0
    assert stats.eligible == 0


@pytest.mark.asyncio
async def test_message_id_stale_pending_eligible(
    mem_db, settings, mock_extractor, mock_vision, mock_scorer
):
    msg_id, _ = await setup_message(mem_db, "PENDING", 20)
    mock_extractor.run.return_value = (get_job_result(), "PROCESSED")
    stats = await reprocess_failed_messages(
        mem_db, settings, mock_extractor, mock_vision, mock_scorer, message_id=msg_id, execute=True
    )
    assert stats.candidates_found == 1
    assert stats.eligible == 1


@pytest.mark.asyncio
async def test_force_cannot_bypass_stale_pending_age_gate(
    mem_db, settings, mock_extractor, mock_vision, mock_scorer
):
    _msg_id, _ = await setup_message(mem_db, "PENDING", 5)  # Fresh
    stats = await reprocess_failed_messages(
        mem_db, settings, mock_extractor, mock_vision, mock_scorer, force=True
    )
    assert stats.candidates_found == 0  # Query still excludes it


@pytest.mark.asyncio
async def test_stale_pending_successful_extraction(
    mem_db, settings, mock_extractor, mock_vision, mock_scorer
):
    msg_id, _ = await setup_message(mem_db, "PENDING", 20)
    mock_extractor.run.return_value = (get_job_result(), "PROCESSED")
    stats = await reprocess_failed_messages(
        mem_db, settings, mock_extractor, mock_vision, mock_scorer, execute=True
    )

    assert stats.success == 1
    repo = Repository(mem_db)
    msg = await repo.get_message(msg_id)
    assert dict(msg)["processing_status"] == "PROCESSED"

    job = await repo.get_job_by_message_id(msg_id)
    assert job is not None
    assert dict(job)["title"] == "Software Engineer"


@pytest.mark.asyncio
async def test_stale_pending_not_job(mem_db, settings, mock_extractor, mock_vision, mock_scorer):
    msg_id, _ = await setup_message(mem_db, "PENDING", 20)
    mock_extractor.run.return_value = (None, "NOT_JOB")
    stats = await reprocess_failed_messages(
        mem_db, settings, mock_extractor, mock_vision, mock_scorer, execute=True
    )

    assert stats.not_job == 1
    repo = Repository(mem_db)
    msg = await repo.get_message(msg_id)
    assert dict(msg)["processing_status"] == "NOT_JOB"

    job = await repo.get_job_by_message_id(msg_id)
    assert job is None  # zero jobs rows


@pytest.mark.asyncio
async def test_stale_pending_missing_media(
    mem_db, settings, mock_extractor, mock_vision, mock_scorer
):
    msg_id, _ = await setup_message(mem_db, "PENDING", 20, has_media=1, media_path=None)
    stats = await reprocess_failed_messages(
        mem_db, settings, mock_extractor, mock_vision, mock_scorer, execute=True
    )

    assert stats.skipped_media == 1
    repo = Repository(mem_db)
    msg = await repo.get_message(msg_id)
    assert dict(msg)["processing_status"] == "SKIPPED"
    assert dict(msg)["skip_reason"] == "media_unavailable_for_reprocess"


@pytest.mark.asyncio
async def test_dry_run_produces_zero_db_mutations(
    mem_db, settings, mock_extractor, mock_vision, mock_scorer
):
    msg_id, _ = await setup_message(mem_db, "PENDING", 20)
    mock_extractor.run.return_value = (get_job_result(), "PROCESSED")
    stats = await reprocess_failed_messages(
        mem_db, settings, mock_extractor, mock_vision, mock_scorer, execute=False
    )

    assert stats.candidates_found == 1
    assert stats.success == 1

    repo = Repository(mem_db)
    msg = await repo.get_message(msg_id)
    assert dict(msg)["processing_status"] == "PENDING"  # Untouched

    job = await repo.get_job_by_message_id(msg_id)
    assert job is None


@pytest.mark.asyncio
async def test_existing_failed_behavior_remains_unchanged(
    mem_db, settings, mock_extractor, mock_vision, mock_scorer
):
    msg_id, _ = await setup_message(mem_db, "EXTRACTION_FAILED", 5)  # Fresh but failed
    mock_extractor.run.return_value = (get_job_result(), "PROCESSED")
    stats = await reprocess_failed_messages(
        mem_db, settings, mock_extractor, mock_vision, mock_scorer, execute=True
    )

    assert stats.candidates_found == 1
    assert stats.success == 1
    repo = Repository(mem_db)
    msg = await repo.get_message(msg_id)
    assert dict(msg)["processing_status"] == "PROCESSED"
