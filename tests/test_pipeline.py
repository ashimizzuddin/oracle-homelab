from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_job_filter.models.enums import Classification
from ai_job_filter.models.job import JobExtractionResult
from ai_job_filter.processing.pipeline import score_and_save_job


@pytest.mark.asyncio
async def test_score_and_save_job_returns_numeric_score():
    db_repo = AsyncMock()
    db_repo.find_recent_jobs.return_value = []
    db_repo.insert_job.return_value = 42

    scorer = MagicMock()
    # Scorer returns: score, classification, breakdown
    scorer.score_job.return_value = (85.5, Classification.APPLY, {})

    job_result = JobExtractionResult(
        is_job_posting=True, title="Senior Python Dev", min_years_exp=5
    )

    job_id, score, classification = await score_and_save_job(
        db_repo=db_repo,
        scorer=scorer,
        msg_id=100,
        source_id=1,
        raw_text="Test Job",
        job_result=job_result,
    )

    assert job_id == 42
    assert score == 85.5
    assert isinstance(score, float)
    assert classification == Classification.APPLY

    # Verify the mock was called with the float score
    db_repo.insert_job.assert_called_once()
    kwargs = db_repo.insert_job.call_args.kwargs
    assert kwargs["match_score"] == 85.5


def test_empty_title_job_posting_rejected_at_model_boundary():
    """is_job_posting=True with title='' must raise ValidationError."""
    with pytest.raises(Exception, match="title is empty"):
        JobExtractionResult(is_job_posting=True, title="")


@pytest.mark.asyncio
async def test_extractor_returns_not_job_for_non_posting():
    """When the LLM says is_job_posting=False, pipeline must return NOT_JOB, not PROCESSED."""
    from ai_job_filter.processing.extractor import ExtractorPipeline

    provider = AsyncMock()
    # Provider returns a valid dict where LLM determined it's not a job
    provider.extract_job.return_value = {
        "is_job_posting": False,
        "title": "",
    }

    pipeline = ExtractorPipeline(provider)
    result, status = await pipeline.run("some random text")

    assert result is None
    assert status == "NOT_JOB"


@pytest.mark.asyncio
async def test_extractor_rejects_empty_title_job_posting():
    """When the LLM returns is_job_posting=True with title='', Pydantic validation
    fires, the pipeline catches the error, and it must NOT return PROCESSED."""
    from ai_job_filter.processing.extractor import ExtractorPipeline

    provider = AsyncMock()
    # Provider returns a raw dict that bypasses provider-level validation
    # (simulating a case where the provider returns model_dump without re-validation)
    provider.extract_job.return_value = {
        "is_job_posting": True,
        "title": "",
    }

    pipeline = ExtractorPipeline(provider)
    result, status = await pipeline.run("job posting text")

    assert result is None
    assert status == "EXTRACTION_FAILED"


@pytest.mark.asyncio
async def test_extractor_returns_not_job_for_null_title_non_posting():
    """When the LLM returns is_job_posting=False with title=None, pipeline must return NOT_JOB."""
    from ai_job_filter.processing.extractor import ExtractorPipeline

    provider = AsyncMock()
    provider.extract_job.return_value = {
        "is_job_posting": False,
        "title": None,
    }

    pipeline = ExtractorPipeline(provider)
    result, status = await pipeline.run("some text")

    assert result is None
    assert status == "NOT_JOB"


@pytest.mark.asyncio
async def test_extractor_rejects_null_title_job_posting():
    """When the LLM returns is_job_posting=True with title=None, validation rejects it."""
    from ai_job_filter.processing.extractor import ExtractorPipeline

    provider = AsyncMock()
    provider.extract_job.return_value = {
        "is_job_posting": True,
        "title": None,
    }

    pipeline = ExtractorPipeline(provider)
    result, status = await pipeline.run("job posting text")

    assert result is None
    assert status == "EXTRACTION_FAILED"
