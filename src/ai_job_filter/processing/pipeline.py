import json

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

    score, classification, hard_fail_reason = scorer.score_job(job_result)

    job_id = await db_repo.insert_job(
        message_id=msg_id,
        source_id=source_id,
        title=job_result.title,
        content_hash=content_hash,
        match_score=score,
        classification=classification.value,
        company=job_result.company,
        location=job_result.location,
        workplace_type=job_result.workplace_type,
        employment_type=job_result.employment_type,
        experience_level=job_result.experience_level,
        min_years_exp=job_result.min_years_exp,
        experience_required=job_result.experience_required,
        salary_min=job_result.salary_min,
        salary_max=job_result.salary_max,
        salary_currency=job_result.salary_currency,
        salary_period=job_result.salary_period,
        salary_raw=job_result.salary_raw,
        skills_required=json.dumps(job_result.skills_required),
        skills_preferred=json.dumps(job_result.skills_preferred),
        requirements_raw=json.dumps(job_result.requirements_raw),
        contacts=json.dumps(job_result.contacts.model_dump()),
        application_url=job_result.application_url,
        summary=job_result.summary,
        deadline=job_result.deadline,
        hard_fail_reason=hard_fail_reason,
        is_duplicate=is_dup,
        parent_job_id=parent_id,
    )

    return job_id, score, classification
