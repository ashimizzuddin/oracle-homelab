import structlog

from ..models.enums import Classification
from ..models.job import JobExtractionResult
from .dedup import check_job_level_duplicate
from .normalizer import compute_text_hash

logger = structlog.get_logger()


async def score_and_save_job(
    db_repo, scorer, msg_id: int, source_id: int, raw_text: str, job_result: JobExtractionResult
) -> tuple[int, float, Classification]:
    content_hash = compute_text_hash(raw_text)

    recent_jobs = [dict(row) for row in await db_repo.find_recent_jobs(30)]
    duplicate_parent = check_job_level_duplicate(job_result.model_dump(), recent_jobs)

    is_dup = 1 if duplicate_parent else 0
    parent_id = duplicate_parent["id"] if duplicate_parent else None

    score, classification, _ = scorer.score_job(job_result)

    job_id = await db_repo.insert_job(
        message_id=msg_id,
        source_id=source_id,
        title=job_result.title,
        content_hash=content_hash,
        match_score=score,
        classification=classification.value,
        company=job_result.company,
        location=job_result.location,
        salary_min=job_result.salary_min,
        salary_max=job_result.salary_max,
        application_url=job_result.application_url,
        summary=job_result.summary,
        is_duplicate=is_dup,
        parent_job_id=parent_id,
    )

    return job_id, score, classification
