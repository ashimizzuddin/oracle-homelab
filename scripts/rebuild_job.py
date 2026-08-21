import argparse
import asyncio
import sys

import aiosqlite
import structlog
from dotenv import load_dotenv

from ai_job_filter.config import Settings
from ai_job_filter.db.repository import Repository
from ai_job_filter.models.candidate import CandidateProfile
from ai_job_filter.processing.extractor import ExtractorPipeline
from ai_job_filter.processing.scorer import Scorer
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
    profile = CandidateProfile.from_yaml(settings.candidate_profile_path)

    async with aiosqlite.connect(settings.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        repo = Repository(conn)
        extractor = ExtractorPipeline(settings)
        scorer = Scorer(profile)

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
