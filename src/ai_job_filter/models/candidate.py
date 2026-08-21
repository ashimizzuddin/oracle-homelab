from dataclasses import dataclass, field

import yaml


@dataclass
class CandidateProfile:
    professional_years: int = 0
    certification: str = ""
    strong_technical_areas: list[str] = field(default_factory=list)
    career_direction: list[str] = field(default_factory=list)
    target_experience: list[str] = field(default_factory=list)
    target_roles: list[str] = field(default_factory=list)
    weaknesses_not_professional_strengths: list[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str) -> "CandidateProfile":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)
