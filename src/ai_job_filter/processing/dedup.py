import re

from rapidfuzz import fuzz

from .normalizer import normalize_text, normalize_url

GENERIC_URL_PATTERNS = [
    r"/careers/?$",
    r"/jobs/?$",
    r"/career/?$",
    r"/join-us/?$",
    r"/vacancies/?$",
    r"/lowongan/?$",
    r"/karir/?$",
]


def is_vacancy_specific_url(url: str | None) -> bool:
    if not url:
        return False
    normalized = normalize_url(url)
    for pattern in GENERIC_URL_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return False
    return True


def is_text_duplicate(new_text: str, existing_texts: list[str], threshold: float = 85.0) -> bool:
    norm_new = normalize_text(new_text)
    for text in existing_texts:
        if fuzz.token_set_ratio(norm_new, normalize_text(text)) >= threshold:
            return True
    return False


def check_job_level_duplicate(new_job: dict, existing_jobs: list[dict]) -> dict | None:
    new_title = normalize_text(new_job.get("title", ""))
    new_company = normalize_text(new_job.get("company", ""))
    new_location = normalize_text(new_job.get("location", ""))
    new_url = new_job.get("application_url")

    has_specific_url = is_vacancy_specific_url(new_url)

    for job in existing_jobs:
        job_url = job.get("application_url")
        if (
            has_specific_url
            and job_url
            and is_vacancy_specific_url(job_url)
            and normalize_url(new_url) == normalize_url(job_url)
        ):
            return job

        title_sim = fuzz.token_set_ratio(new_title, normalize_text(job.get("title", "")))
        company_sim = fuzz.token_set_ratio(new_company, normalize_text(job.get("company", "")))
        location_sim = fuzz.token_set_ratio(new_location, normalize_text(job.get("location", "")))

        if title_sim >= 85 and company_sim >= 80 and location_sim >= 75:
            return job

    return None
