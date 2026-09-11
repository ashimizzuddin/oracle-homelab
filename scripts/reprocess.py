import argparse
import asyncio
import os
import sys

import aiosqlite
import structlog
from dotenv import load_dotenv

# Add src to path so we can import ai_job_filter
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import contextlib

from ai_job_filter.config import Settings
from ai_job_filter.models.candidate import CandidateProfile
from ai_job_filter.processing.extractor import ExtractorPipeline
from ai_job_filter.processing.scorer import Scorer
from ai_job_filter.processing.vision import VisionPipeline
from ai_job_filter.providers.gemini_provider import GeminiProvider
from ai_job_filter.providers.groq_provider import GroqProvider
from ai_job_filter.reprocess import reprocess_failed_messages

logger = structlog.get_logger()


async def main():
    load_dotenv()
    settings = Settings()

    parser = argparse.ArgumentParser(description="Reprocess failed messages")
    parser.add_argument(
        "--execute", action="store_true", help="Execute database mutations (Default is DRY RUN)"
    )
    parser.add_argument("--force", action="store_true", help="Bypass retry_count limit")
    parser.add_argument("--limit", type=int, help="Maximum number of candidates to process")
    parser.add_argument("--message-id", type=int, help="Process only this specific message ID")
    args = parser.parse_args()

    if args.message_id is not None and args.limit is not None:
        parser.error("--message-id and --limit cannot be used together")

    if not args.execute:
        logger.info("DRY RUN: no database mutations. LLM/API calls may still occur.")

    groq_provider = GroqProvider(
        api_key=settings.groq_api_key.get_secret_value() if settings.groq_api_key else None,
        model=settings.text_model,
    )
    gemini_provider = GeminiProvider(
        api_key=settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None,
        model=settings.vision_model,
        max_rpm=settings.gemini_max_rpm,
        max_rpd=settings.gemini_max_rpd,
        budget_path=settings.gemini_budget_path,
    )

    extractor = ExtractorPipeline(groq_provider)
    vision = VisionPipeline(gemini_provider)
    profile = CandidateProfile()
    with contextlib.suppress(Exception):
        profile = CandidateProfile.from_yaml("candidate_profile.yaml")
    scorer = Scorer(
        profile, min_apply=settings.min_score_apply, min_review=settings.min_score_review
    )

    async with aiosqlite.connect(settings.database_path) as conn:
        conn.row_factory = aiosqlite.Row
        stats = await reprocess_failed_messages(
            conn=conn,
            config=settings,
            extractor=extractor,
            vision=vision,
            scorer=scorer,
            limit=args.limit,
            force=args.force,
            execute=args.execute,
            message_id=args.message_id,
        )

        logger.info(
            "Reprocess complete",
            mode=stats.mode,
            candidates_found=stats.candidates_found,
            eligible=stats.eligible,
            skipped_limit=stats.skipped_limit,
            skipped_media=stats.skipped_media,
            success=stats.success,
            not_job=stats.not_job,
            failed=stats.failed,
        )


if __name__ == "__main__":
    asyncio.run(main())
