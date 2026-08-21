from rapidfuzz import fuzz

from ..models.candidate import CandidateProfile
from ..models.enums import Classification
from ..models.job import JobExtractionResult


class Scorer:
    def __init__(self, profile: CandidateProfile, min_apply: int = 75, min_review: int = 55):
        self.profile = profile
        self.min_apply = min_apply
        self.min_review = min_review

    def score_job(self, job: JobExtractionResult) -> tuple[int, Classification, str | None]:
        # 1. Hard fail checks
        if (
            "senior" in job.title.lower()
            or "lead" in job.title.lower()
            or "manager" in job.title.lower()
        ):
            return 0, Classification.IGNORE, "Senior/Lead role"

        if (
            job.min_years_exp is not None
            and job.min_years_exp >= 3
            and job.experience_required == "required"
        ):
            return 0, Classification.IGNORE, "Requires 3+ years experience"

        score = 0

        # 2. Role relevance (0-30)
        # "Staff" is an entry-level designation, not a senior signal.
        best_role_score = 0
        job_title_norm = job.title.lower()
        for role in self.profile.target_roles:
            sim = fuzz.partial_ratio(job_title_norm, role.lower())
            best_role_score = max(best_role_score, sim)

        score += (best_role_score / 100.0) * 30

        # 3. Technical skill alignment (0-25)
        matched_skills = 0
        req_skills = [s.lower() for s in job.skills_required + job.skills_preferred]
        for skill in self.profile.strong_technical_areas:
            if any(skill.lower() in rs or rs in skill.lower() for rs in req_skills):
                matched_skills += 1

        if len(req_skills) > 0:
            skill_score = min(25, matched_skills * 6)
            score += skill_score

        # Certifications are not experience, but they are skills.
        if self.profile.certification and any(
            self.profile.certification.lower() in rs for rs in req_skills
        ):
            score = min(100, score + 10)

        # 4. Experience fit (0-20)
        if job.min_years_exp is None or job.min_years_exp <= 1:
            score += 20
        elif job.min_years_exp == 2:
            if job.experience_required == "preferred" or job.experience_required == "plus":
                score += 10
            else:
                score += 5  # 2 years required is a stretch for 0 years

        # 5. Career trajectory (0-15)
        traj_score = 0
        summary_norm = (job.summary or "").lower() + " " + " ".join(job.requirements_raw).lower()

        # V2: fuzzy match on title using token_set_ratio
        best_title_tsr = 0
        if self.profile.career_direction:
            best_title_tsr = max(
                fuzz.token_set_ratio(job_title_norm, cd.lower())
                for cd in self.profile.career_direction
            )

        # V1 fallback: exact substring match in summary/requirements
        summary_match = any(cd.lower() in summary_norm for cd in self.profile.career_direction)

        if best_title_tsr >= 75 or summary_match:
            traj_score = 15
        score += traj_score

        # 6. Practical factors (0-10) (workplace type, etc)
        if job.workplace_type in ["remote", "hybrid", "on-site"]:
            score += 5
        if job.salary_min is not None or job.salary_max is not None:
            score += 5

        final_score = min(100, int(score))

        if final_score >= self.min_apply:
            classification = Classification.APPLY
        elif final_score >= self.min_review:
            classification = Classification.REVIEW
        else:
            classification = Classification.IGNORE

        return final_score, classification, None
