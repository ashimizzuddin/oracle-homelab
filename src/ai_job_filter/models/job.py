from typing import Any

from pydantic import BaseModel, Field, model_validator


class ContactInfo(BaseModel):
    emails: list[str] | None = Field(default_factory=list)
    phone_numbers: list[str] | None = Field(default_factory=list)
    whatsapp: list[str] | None = Field(default_factory=list)
    telegram_handles: list[str] | None = Field(default_factory=list)
    other: list[str] | None = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_null_lists(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for field in ["emails", "phone_numbers", "whatsapp", "telegram_handles", "other"]:
            if field in data and data[field] is None:
                data[field] = []
        return data


class JobExtractionResult(BaseModel):
    is_job_posting: bool
    title: str | None = None
    company: str | None = None
    location: str | None = None
    workplace_type: str | None = "unknown"
    employment_type: str | None = "unknown"
    experience_level: str | None = "not_specified"
    min_years_exp: int | None = None
    experience_required: str | None = None  # "required"|"preferred"|"plus"|null
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = "IDR"
    salary_period: str | None = "monthly"
    salary_raw: str | None = None
    skills_required: list[str] | None = Field(default_factory=list)
    skills_preferred: list[str] | None = Field(default_factory=list)
    requirements_raw: list[str] | None = Field(default_factory=list)
    contacts: ContactInfo | None = Field(default_factory=ContactInfo)
    application_url: str | None = None
    summary: str | None = None
    deadline: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_null_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        defaults = {
            "experience_level": "not_specified",
            "workplace_type": "unknown",
            "employment_type": "unknown",
            "salary_currency": "IDR",
            "salary_period": "monthly",
            "skills_required": [],
            "skills_preferred": [],
            "requirements_raw": [],
            "contacts": {},
        }

        for field, default_val in defaults.items():
            # If the field is explicitly provided as None, normalize it.
            if field in data and data[field] is None:
                data[field] = default_val

        return data

    @model_validator(mode="after")
    def validate_semantics(self) -> "JobExtractionResult":
        if not self.is_job_posting:
            return self

        if not self.title or not self.title.strip():
            raise ValueError("is_job_posting is True but title is empty")

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
