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


def test_contact_info_validation():
    from ai_job_filter.models.job import JobExtractionResult

    # Missing contacts should default safely
    job = JobExtractionResult.model_validate({"is_job_posting": True, "title": "Dev"})
    assert job.contacts.emails == []
    assert job.contacts.phone_numbers == []

    # Extracting specific contacts
    job2 = JobExtractionResult.model_validate(
        {
            "is_job_posting": True,
            "title": "Dev",
            "contacts": {"emails": ["test@example.com"], "whatsapp": ["12345"]},
        }
    )
    assert job2.contacts.emails == ["test@example.com"]
    assert job2.contacts.whatsapp == ["12345"]
    assert job2.contacts.telegram_handles == []


def test_gemini_schema_compatibility():
    import pytest
    from google.genai import types

    from ai_job_filter.models.job import JobExtractionResult

    try:
        config = types.GenerateContentConfig(response_schema=JobExtractionResult)
        assert config.response_schema is JobExtractionResult

        schema_json = JobExtractionResult.model_json_schema()
        contacts_prop = schema_json.get("$defs", {}).get("ContactInfo", {})
        assert (
            "additionalProperties" not in contacts_prop
            or contacts_prop.get("additionalProperties") is False
        )
    except Exception as e:
        pytest.fail(f"Schema configuration failed: {e}")


def test_groq_schema_compatibility():
    from ai_job_filter.models.job import JobExtractionResult
    from ai_job_filter.providers.groq_provider import make_schema_strict

    schema_json = JobExtractionResult.model_json_schema()
    strict_schema = make_schema_strict(schema_json)

    assert strict_schema.get("additionalProperties") is False
    assert "required" in strict_schema
    assert "is_job_posting" in strict_schema["required"]
    assert "title" in strict_schema["required"]
    assert "contacts" in strict_schema["required"]

    contacts_def = strict_schema.get("$defs", {}).get("ContactInfo", {})
    assert contacts_def.get("additionalProperties") is False
    assert "required" in contacts_def
    assert "emails" in contacts_def["required"]


def test_null_normalization():
    from ai_job_filter.models.job import JobExtractionResult

    # Test that None values are normalized correctly to their semantic defaults
    data = {
        "is_job_posting": True,
        "title": "Engineer",
        "experience_level": None,
        "workplace_type": None,
        "employment_type": None,
        "salary_currency": None,
        "salary_period": None,
        # Genuine nullables
        "salary_min": None,
        "location": None,
    }

    job = JobExtractionResult.model_validate(data)

    assert job.experience_level == "not_specified"
    assert job.workplace_type == "unknown"
    assert job.employment_type == "unknown"
    assert job.salary_currency == "IDR"
    assert job.salary_period == "monthly"

    # Genuine nullables must remain None
    assert job.salary_min is None
    assert job.location is None


def test_title_validation_valid():
    """Valid job with non-empty title is accepted."""
    job = JobExtractionResult.model_validate({"is_job_posting": True, "title": "DevOps Engineer"})
    assert job.title == "DevOps Engineer"


def test_title_validation_null_rejected():
    """is_job_posting=True with title=None is rejected."""
    import pytest

    with pytest.raises(ValueError, match="title is empty"):
        JobExtractionResult.model_validate({"is_job_posting": True, "title": None})


def test_title_validation_empty_rejected():
    """is_job_posting=True with title='' is rejected."""
    import pytest

    with pytest.raises(ValueError, match="title is empty"):
        JobExtractionResult.model_validate({"is_job_posting": True, "title": ""})


def test_title_validation_whitespace_rejected():
    """is_job_posting=True with title='   ' is rejected."""
    import pytest

    with pytest.raises(ValueError, match="title is empty"):
        JobExtractionResult.model_validate({"is_job_posting": True, "title": "   "})


def test_title_validation_non_job_null_allowed():
    """is_job_posting=False with title=None is allowed."""
    job = JobExtractionResult.model_validate({"is_job_posting": False, "title": None})
    assert job.is_job_posting is False
    assert job.title is None


def test_title_validation_non_job_empty_allowed():
    """is_job_posting=False with empty title is allowed."""
    job = JobExtractionResult.model_validate({"is_job_posting": False, "title": ""})
    assert job.is_job_posting is False
    assert job.title == ""
