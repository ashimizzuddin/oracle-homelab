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
