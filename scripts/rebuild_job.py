import argparse
import asyncio
import contextlib
import os
import sys

import aiosqlite
import structlog
from dotenv import load_dotenv

# Add src to path so we can import ai_job_filter
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from ai_job_filter.config import Settings
from ai_job_filter.db.repository import Repository
from ai_job_filter.models.candidate import CandidateProfile
from ai_job_filter.processing.extractor import ExtractorPipeline
from ai_job_filter.processing.scorer import Scorer
from ai_job_filter.providers.groq_provider import GroqProvider
from ai_job_filter.rebuild import JobRebuilder

logger = structlog.get_logger()


async def main():
    parser = argparse.ArgumentParser(description="Rebuild an existing job in place.")
    parser.add_argument("--message-id", type=int, required=True, help="Message ID to rebuild")
    parser.add_argument("--execute", action="store_true", help="Actually mutate the database")
    parser.add_argument(
        "--force", action="store_true", help="Rebuild even if status is NOT_JOB/SKIPPED/FAILED"
    )

    args = parser.parse_args()

    if args.execute:
        confirm = input(
            f"Ready to rebuild Message ID {args.message_id}. Proceed with UPDATE? [y/N]: "
        )
        if confirm.lower() != "y":
            print("Aborted.")
            sys.exit(0)
    else:
        print("DRY RUN MODE. No mutations will occur.")

    settings = Settings()

    # Load profile exactly like main.py and reprocess.py
    profile = CandidateProfile()
    with contextlib.suppress(Exception):
        profile = CandidateProfile.from_yaml("candidate_profile.yaml")

    # Initialize provider correctly
    groq_provider = GroqProvider(
        api_key=settings.groq_api_key.get_secret_value() if settings.groq_api_key else None,
        model=settings.text_model,
    )
    extractor = ExtractorPipeline(groq_provider)

    scorer = Scorer(
        profile, min_apply=settings.min_score_apply, min_review=settings.min_score_review
    )

    async with aiosqlite.connect(settings.database_path) as conn:
        conn.row_factory = aiosqlite.Row
        repo = Repository(conn)

        rebuilder = JobRebuilder(repo, extractor, scorer, args.execute)

        result = await rebuilder.rebuild_message(args.message_id, args.force)

        if result.success:
            print("Rebuild successful.")
            if result.job_updated:
                print(
                    f"Job updated! New score: {result.new_score}, Class: {result.new_classification}"
                )
            elif not args.execute:
                print(
                    f"[DRY RUN] Would update job. New score: {result.new_score}, Class: {result.new_classification}"
                )
            elif result.status_updated_to:
                print(f"Status updated to {result.status_updated_to}")
        else:
            print(f"Rebuild failed: {result.error_reason}")
            sys.exit(1)


if __name__ == "__main__":
    load_dotenv()
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
    asyncio.run(main())
