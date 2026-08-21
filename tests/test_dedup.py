from ai_job_filter.processing.dedup import (
    check_job_level_duplicate,
    is_text_duplicate,
    is_vacancy_specific_url,
)


def test_exact_and_fuzzy_text_dedup():
    existing = ["We are hiring a Python developer in Jakarta."]
    assert is_text_duplicate("we are hiring a python developer in jakarta", existing) is True
    assert is_text_duplicate("We are hiring Python developers in Jakarta!", existing) is True
    assert is_text_duplicate("Looking for a Java engineer in Bali", existing) is False


def test_vacancy_specific_url():
    assert is_vacancy_specific_url("https://company.com/careers") is False
    assert is_vacancy_specific_url("https://company.com/jobs/") is False
    assert is_vacancy_specific_url("https://company.com/vacancies/12345-python-dev") is True


def test_job_level_dedup():
    existing = [
        {
            "title": "Python Developer",
            "company": "TechCorp",
            "location": "Jakarta",
            "application_url": "https://company.com/vacancies/123",
        }
    ]

    # 1. Exact match
    new_job = {"title": "Python Developer", "company": "TechCorp", "location": "Jakarta"}
    assert check_job_level_duplicate(new_job, existing) is not None

    # 2. Same title/company, different location -> NOT duplicate
    new_job_diff_loc = {"title": "Python Developer", "company": "TechCorp", "location": "Surabaya"}
    assert check_job_level_duplicate(new_job_diff_loc, existing) is None

    # 3. Same vacancy URL -> duplicate
    new_job_url = {
        "title": "Backend Dev",
        "company": "TechCorp",
        "location": "Remote",
        "application_url": "https://company.com/vacancies/123",
    }
    assert check_job_level_duplicate(new_job_url, existing) is not None

    # 4. Same generic career URL -> NOT sufficient for duplicate (uses text match which fails here)
    existing_generic = [
        {
            "title": "Data Scientist",
            "company": "TechCorp",
            "location": "Jakarta",
            "application_url": "https://company.com/careers",
        }
    ]
    new_job_generic = {
        "title": "Backend Dev",
        "company": "TechCorp",
        "location": "Jakarta",
        "application_url": "https://company.com/careers",
    }
    assert check_job_level_duplicate(new_job_generic, existing_generic) is None
