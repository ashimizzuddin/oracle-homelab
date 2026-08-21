import asyncio
import os

from ai_job_filter.models.candidate import CandidateProfile
from ai_job_filter.processing.extractor import ExtractorPipeline
from ai_job_filter.processing.scorer import Scorer
from ai_job_filter.providers.groq_provider import GroqProvider


async def evaluate(provider_key: str):
    if not provider_key:
        print("Error: Provide GROQ_API_KEY environment variable to test extraction.")
        return

    provider = GroqProvider(api_key=provider_key)
    pipeline = ExtractorPipeline(provider)

    # Generate mock profile
    profile = CandidateProfile(
        professional_years=0,
        certification="RHCSA",
        strong_technical_areas=["Linux", "Bash"],
        target_roles=["Linux Administrator", "IT Support", "Junior Developer"],
        career_direction=["Cybersecurity"],
    )
    scorer = Scorer(profile)

    samples = [
        "Dicari IT Support, Lulusan SMK, Gaji 4jt, Penempatan Bekasi.",
        "We need a Senior DevOps Engineer. 5+ years experience. Up to $120k.",
        "Urgent! Web Developer. Remote. Fresh grads welcome. React and Node.js.",
        "Hello guys, I am looking for a job as a Python developer. Please DM.",
    ]

    print("| Text Snippet | Extracted Title | Exp (Yrs) | Salary | Score | Classification |")
    print("|--------------|-----------------|-----------|--------|-------|----------------|")

    for text in samples:
        job_result, status = await pipeline.run(text)

        snippet = text[:40].replace("\n", " ") + "..."
        if status != "PROCESSED" or not job_result:
            print(f"| {snippet} | FAILED ({status}) | - | - | - | - |")
            continue

        if not job_result.is_job_posting:
            print(f"| {snippet} | NOT JOB POST | - | - | - | IGNORE |")
            continue

        score, classification, _ = scorer.score_job(job_result)

        title = job_result.title or "N/A"
        exp = job_result.min_years_exp if job_result.min_years_exp is not None else "N/A"
        salary = (
            f"{job_result.salary_min}-{job_result.salary_max}" if job_result.salary_min else "N/A"
        )

        print(f"| {snippet} | {title[:20]} | {exp} | {salary} | {score} | {classification.value} |")


if __name__ == "__main__":
    key = os.environ.get("GROQ_API_KEY")
    asyncio.run(evaluate(key))
