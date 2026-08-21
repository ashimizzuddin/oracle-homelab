from pydantic import BaseModel


class JobExtractionResult(BaseModel):
    is_job_posting: bool
    title: str = ""
    company: str | None = None
    location: str | None = None
    workplace_type: str = "unknown"
    employment_type: str = "unknown"
    experience_level: str = "not_specified"
    min_years_exp: int | None = None
    experience_required: str | None = None  # "required"|"preferred"|"plus"|null
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = "IDR"
    salary_period: str = "monthly"
    salary_raw: str | None = None
    skills_required: list[str] = []
    skills_preferred: list[str] = []
    requirements_raw: list[str] = []
    contacts: dict = {}
    application_url: str | None = None
    summary: str | None = None
    deadline: str | None = None
