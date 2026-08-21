from ai_job_filter.models.enums import Classification
from ai_job_filter.models.job import JobExtractionResult
from ai_job_filter.processing.scorer import Scorer


def test_fresh_graduate_entry_level(candidate_profile, sample_job_post):
    scorer = Scorer(candidate_profile)
    job = JobExtractionResult(**sample_job_post)
    score, classification, _ = scorer.score_job(job)
    assert score >= 75
    assert classification == Classification.APPLY


def test_experience_matching(candidate_profile, sample_job_post):
    scorer = Scorer(candidate_profile)
    job = JobExtractionResult(**sample_job_post)

    job.min_years_exp = 0
    score1, _, _ = scorer.score_job(job)

    job.min_years_exp = 2
    job.experience_required = "preferred"
    score2, _, _ = scorer.score_job(job)

    assert score1 > score2

    job.min_years_exp = 3
    job.experience_required = "required"
    score3, class3, reason = scorer.score_job(job)
    assert score3 == 0
    assert class3 == Classification.IGNORE
    assert "Requires 3+" in reason


def test_senior_lead_roles(candidate_profile, sample_job_post):
    scorer = Scorer(candidate_profile)
    job = JobExtractionResult(**sample_job_post)

    job.title = "Senior Linux Administrator"
    score, classification, reason = scorer.score_job(job)
    assert score == 0
    assert classification == Classification.IGNORE
    assert "Senior/Lead" in reason


def test_it_staff_role(candidate_profile, sample_job_post):
    scorer = Scorer(candidate_profile)
    job = JobExtractionResult(**sample_job_post)

    job.title = "IT Staff"
    _score, classification, _ = scorer.score_job(job)
    assert classification in [Classification.APPLY, Classification.REVIEW]


def test_certification_not_work_experience(candidate_profile, sample_job_post):
    scorer = Scorer(candidate_profile)
    job = JobExtractionResult(**sample_job_post)

    job.skills_required = ["RHCSA"]
    score, _, _ = scorer.score_job(job)
    assert score > 0
