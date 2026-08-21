from ai_job_filter.models.candidate import CandidateProfile
from ai_job_filter.models.job import JobExtractionResult


def test_job_extraction_result_validation(sample_job_post):
    job = JobExtractionResult(**sample_job_post)
    assert job.is_job_posting is True
    assert job.title == "Junior Linux Administrator"


def test_candidate_profile_loading(tmp_path):
    yaml_content = """
    professional_years: 0
    certification: "RHCSA"
    """
    yaml_path = tmp_path / "profile.yaml"
    yaml_path.write_text(yaml_content)

    profile = CandidateProfile.from_yaml(str(yaml_path))
    assert profile.professional_years == 0
    assert profile.certification == "RHCSA"
