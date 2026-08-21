from pydantic import BaseModel, model_validator


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

    @model_validator(mode="after")
    def validate_semantics(self) -> "JobExtractionResult":
        if not self.is_job_posting:
            return self

        if self.min_years_exp is not None and self.min_years_exp < 0:
            raise ValueError("min_years_exp must be >= 0")

        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min cannot be greater than salary_max")

        if self.experience_required not in [None, "required", "preferred", "plus"]:
            raise ValueError(f"Invalid experience_required: {self.experience_required}")

        # Clean up common hallucinations
        for field in [
            "company",
            "location",
            "salary_raw",
            "application_url",
            "summary",
            "deadline",
        ]:
            val = getattr(self, field)
            if isinstance(val, str) and val.strip().lower() in [
                "null",
                "not specified",
                "n/a",
                "unknown",
                "none",
                "not stated",
            ]:
                setattr(self, field, None)

        return self
