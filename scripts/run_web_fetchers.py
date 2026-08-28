"""CLI: run all web fetchers once (manual/testing). PRD F-WEB-4.

Usage:
    uv run python scripts/run_web_fetchers.py              # dry-run all
    uv run python scripts/run_web_fetchers.py --execute    # real ingest
    uv run python scripts/run_web_fetchers.py --only glints # one board
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_job_filter.config import Settings
from ai_job_filter.db.connection import get_connection
from ai_job_filter.db.migrations import apply_migrations
from ai_job_filter.db.repository import Repository
from ai_job_filter.processing.extractor import ExtractorPipeline
from ai_job_filter.processing.scorer import Scorer
from ai_job_filter.providers.groq_provider import GroqProvider
from ai_job_filter.web_fetcher.registry import build_fetchers
from ai_job_filter.web_fetcher.scheduler import run_fetcher_once


async def main():
    parser = argparse.ArgumentParser(description="Run web fetchers once")
    parser.add_argument("--execute", action="store_true", help="Real ingest (default: dry-run)")
    parser.add_argument("--only", type=str, help="Run one board by name (e.g., glints)")
    parser.add_argument("--limit", type=int, help="Max detail fetches per board")
    args = parser.parse_args()

    config = Settings()
    conn = await get_connection(config.database_path)
    await apply_migrations(conn)
    db_repo = Repository(conn)

    groq = GroqProvider(
        api_key=config.groq_api_key.get_secret_value() if config.groq_api_key else None,
        model=config.text_model,
    )
    extractor = ExtractorPipeline(groq)

    from ai_job_filter.models.candidate import CandidateProfile

    profile = CandidateProfile.from_yaml("candidate_profile.yaml")
    scorer = Scorer(profile, min_apply=config.min_score_apply, min_review=config.min_score_review)

    fetchers = build_fetchers(db_repo)
    if args.only:
        fetchers = [f for f in fetchers if f.source == args.only]
        if not fetchers:
            print(f"No fetcher named '{args.only}'")
            return

    dry_run = not args.execute
    print(f"Running {len(fetchers)} fetchers (dry_run={dry_run})\n")

    total = 0
    for fetcher in fetchers:
        stats, ingested = await run_fetcher_once(
            db_repo, extractor, scorer, fetcher, dry_run=dry_run, limit=args.limit
        )
        total += ingested
        print(f"[{fetcher.source}] found={stats['found']} fetched={stats['fetched']} "
              f"new={stats['new']} ingested={ingested} failed={stats['failed']}")

    print(f"\nTotal ingested: {total}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
