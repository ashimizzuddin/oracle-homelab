from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from ai_job_filter.db.repository import Repository
from ai_job_filter.models.enums import Classification
from ai_job_filter.models.job import ContactInfo, JobExtractionResult
from ai_job_filter.rebuild import JobRebuilder


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
    scorer.score_job.return_value = (85, Classification.APPLY, None)
    return scorer


def get_job_result():
    return JobExtractionResult(
        is_job_posting=True,
        title="Software Engineer",
        company="Acme Corp",
        location="Remote",
        workplace_type="remote",
        employment_type="full_time",
        experience_level="mid",
        min_years_exp=3,
        experience_required="required",
        salary_min=1000,
        salary_max=2000,
        salary_currency="USD",
        salary_period="monthly",
        salary_raw="$1000-$2000",
        skills_required=["Python", "SQL"],
        skills_preferred=["AWS"],
        requirements_raw=["3+ years Python"],
        contacts=ContactInfo(emails=["hr@acme.com"]),
        application_url="https://acme.com/apply",
        summary="A great job",
        deadline="2023-12-31",
    )


@pytest.mark.asyncio
async def test_duplicate_relation_safety(mem_db, mock_extractor, mock_vision, mock_scorer):
    # Setup repo and initial data
    repo = Repository(mem_db)

    source_id = await repo.insert_source(12345, "Test Group")
    msg1_id = await repo.insert_message(source_id, 101, "First Job", "2023-01-01T12:00:00Z")
    msg2_id = await repo.insert_message(source_id, 102, "Duplicate Job", "2023-01-01T12:05:00Z")

    await repo.update_message_status(msg1_id, "PROCESSED")
    await repo.update_message_status(msg2_id, "PROCESSED")

    job1_id = await repo.insert_job(msg1_id, source_id, "Original", "hash1", 80.0, "APPLY")
    await repo.insert_job(
        msg2_id,
        source_id,
        "Dup",
        "hash2",
        80.0,
        "APPLY",
        is_duplicate=1,
        parent_job_id=job1_id,
        duplicate_method="text_hash",
    )

    # Rebuild job 2 so it is NO LONGER a duplicate
    mock_extractor.run.return_value = (get_job_result(), "PROCESSED")
    rebuilder = JobRebuilder(repo, mock_extractor, mock_vision, mock_scorer, execute=True)

    res = await rebuilder.rebuild_message(msg2_id)
    assert res.success is True

    # Verify Job 2 is no longer a duplicate
    j2 = await repo.get_job_by_message_id(msg2_id)
    assert dict(j2)["is_duplicate"] == 0
    assert dict(j2)["parent_job_id"] is None

    # Verify Job 1 is completely untouched
    j1 = await repo.get_job_by_message_id(msg1_id)
    assert dict(j1)["is_duplicate"] == 0
    assert dict(j1)["parent_job_id"] is None


@pytest.mark.asyncio
async def test_score_breakdown_persisted_as_empty_dict(
    mem_db, mock_extractor, mock_vision, mock_scorer
):
    repo = Repository(mem_db)
    source_id = await repo.insert_source(12345, "Test Group")
    msg_id = await repo.insert_message(source_id, 101, "Job", "2023-01-01T12:00:00Z")
    await repo.update_message_status(msg_id, "PROCESSED")
    await repo.insert_job(msg_id, source_id, "Original", "hash", 0.0, "IGNORE")

    mock_extractor.run.return_value = (get_job_result(), "PROCESSED")
    rebuilder = JobRebuilder(repo, mock_extractor, mock_vision, mock_scorer, execute=True)

    await rebuilder.rebuild_message(msg_id)
    job = await repo.get_job_by_message_id(msg_id)

    # Verify score_breakdown is '{}'
    assert dict(job)["score_breakdown"] == "{}"


@pytest.mark.asyncio
async def test_message_status_after_rebuild_success(
    mem_db, mock_extractor, mock_vision, mock_scorer
):
    repo = Repository(mem_db)
    source_id = await repo.insert_source(12345, "Test Group")
    msg_id = await repo.insert_message(source_id, 101, "Job", "2023-01-01T12:00:00Z")
    # Simulate some retries before it was processed
    await mem_db.execute(
        "UPDATE messages SET retry_count = 2, skip_reason = 'temp_fail' WHERE id = ?", (msg_id,)
    )
    await repo.insert_job(msg_id, source_id, "Job", "hash", 0.0, "IGNORE")

    mock_extractor.run.return_value = (get_job_result(), "PROCESSED")
    rebuilder = JobRebuilder(repo, mock_extractor, mock_vision, mock_scorer, execute=True)

    await rebuilder.rebuild_message(msg_id, force=True)
    msg = await repo.get_message(msg_id)

    assert dict(msg)["processing_status"] == "PROCESSED"
    assert dict(msg)["retry_count"] == 0
    assert dict(msg)["skip_reason"] is None


@pytest.mark.asyncio
async def test_message_status_after_rebuild_not_job(
    mem_db, mock_extractor, mock_vision, mock_scorer
):
    repo = Repository(mem_db)
    source_id = await repo.insert_source(12345, "Test Group")
    msg_id = await repo.insert_message(source_id, 101, "Job", "2023-01-01T12:00:00Z")
    await repo.update_message_status(msg_id, "PROCESSED")
    await repo.insert_job(msg_id, source_id, "Job", "hash", 0.0, "IGNORE")

    mock_extractor.run.return_value = (None, "NOT_JOB")
    rebuilder = JobRebuilder(repo, mock_extractor, mock_vision, mock_scorer, execute=True)

    await rebuilder.rebuild_message(msg_id)
    msg = await repo.get_message(msg_id)

    assert dict(msg)["processing_status"] == "NOT_JOB"
    assert dict(msg)["retry_count"] == 0
    assert dict(msg)["skip_reason"] is None

    # The job row should not be mutated or deleted (we didn't implement deletion,
    # and instructions say "do not create/update a jobs row beyond the explicit rebuild semantics")
    job = await repo.get_job_by_message_id(msg_id)
    assert dict(job)["title"] == "Job"  # Unchanged


@pytest.mark.asyncio
async def test_rebuild_dry_run_reaches_pipeline_no_mutation(
    mem_db, mock_extractor, mock_vision, mock_scorer
):
    repo = Repository(mem_db)
    source_id = await repo.insert_source(12345, "Test Group")
    msg_id = await repo.insert_message(source_id, 101, "Test dry run text", "2023-01-01T12:00:00Z")
    await repo.update_message_status(msg_id, "PROCESSED")
    await repo.insert_job(msg_id, source_id, "Old Title", "hash", 0.0, "IGNORE")

    # Setup mock
    mock_extractor.run.return_value = (get_job_result(), "PROCESSED")

    rebuilder = JobRebuilder(repo, mock_extractor, mock_vision, mock_scorer, execute=False)
    res = await rebuilder.rebuild_message(msg_id)

    assert res.success is True
    assert res.job_updated is False

    # Assert extractor was called with the message text
    mock_extractor.run.assert_called_once_with("Test dry run text")

    # Assert scorer was called with the mocked extracted job result
    mock_scorer.score_job.assert_called_once()

    # Assert zero DB mutations happened
    job = await repo.get_job_by_message_id(msg_id)
    assert dict(job)["title"] == "Old Title"
