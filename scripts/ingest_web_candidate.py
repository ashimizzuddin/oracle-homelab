#!/usr/bin/env python3
"""
Web Candidate Ingestion Adapter for AI JOB FILTER.

This script ingests normalized web candidates and runs them through
the existing AI JOB FILTER extraction + scoring + dedup pipeline.

Usage:
    uv run python scripts/ingest_web_candidate.py --file candidate.json --dry-run
    uv run python scripts/ingest_web_candidate.py --file candidate.json --execute

Dry-run (default): runs full pipeline but does NOT insert into database.
Execute: inserts source, message, and job records (same as Telegram flow).
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add project src to path BEFORE importing ai_job_filter modules
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ai_job_filter.config import Settings  # noqa: E402
from ai_job_filter.db.connection import get_connection  # noqa: E402
from ai_job_filter.db.migrations import apply_migrations  # noqa: E402
from ai_job_filter.db.repository import Repository  # noqa: E402
from ai_job_filter.models.candidate import CandidateProfile  # noqa: E402
from ai_job_filter.models.enums import Classification, ProcessingStatus  # noqa: E402
from ai_job_filter.models.job import JobExtractionResult  # noqa: E402
from ai_job_filter.processing.dedup import check_job_level_duplicate  # noqa: E402
from ai_job_filter.processing.extractor import ExtractorPipeline  # noqa: E402
from ai_job_filter.processing.normalizer import compute_text_hash  # noqa: E402
from ai_job_filter.processing.scorer import Scorer  # noqa: E402
from ai_job_filter.providers.groq_provider import GroqProvider  # noqa: E402


def load_candidate(file_path: str) -> dict:
    """Load candidate from JSON file."""
    with open(file_path) as f:
        return json.load(f)


def validate_candidate(candidate: dict) -> list[str]:
    """Validate required fields. Returns list of errors (empty if valid)."""
    errors = []
    required = ["source", "source_url", "source_text", "discovery_query"]
    for field in required:
        if field not in candidate or not candidate[field]:
            errors.append(f"Missing required field: {field}")
    return errors


def create_virtual_source_id(source_url: str) -> int:
    """Create a deterministic virtual telegram_id from source URL."""
    return int(hashlib.md5(source_url.encode()).hexdigest()[:8], 16)


def create_virtual_message_id(discovered_at: str) -> int:
    """Create a deterministic virtual telegram_msg_id from discovery timestamp."""
    return int(hashlib.md5(discovered_at.encode()).hexdigest()[:8], 16)


async def run_dry_run(candidate: dict, config: Settings, db_repo: Repository) -> dict:
    """
    Run full pipeline in dry-run mode.
    Returns dict with all pipeline results.
    """
    source_text = candidate["source_text"]

    # Initialize pipeline components (same as main.py)
    groq_provider = GroqProvider(
        api_key=config.groq_api_key.get_secret_value() if config.groq_api_key else None,
        model=config.text_model,
    )
    extractor = ExtractorPipeline(groq_provider)

    profile = CandidateProfile(professional_years=0)
    try:
        profile = CandidateProfile.from_yaml(str(PROJECT_ROOT / "candidate_profile.yaml"))
    except Exception as e:
        print(f"Warning: Could not load candidate profile: {e}", file=sys.stderr)

    scorer = Scorer(profile, min_apply=config.min_score_apply, min_review=config.min_score_review)

    # Step 1: Extraction
    print(f"[1/6] Running extraction on {len(source_text)} chars...", file=sys.stderr)
    job_result, extract_status = await extractor.run(source_text)

    if extract_status != "PROCESSED" or not job_result:
        return {
            "success": False,
            "stage": "extraction",
            "status": extract_status,
            "job_result": job_result.model_dump() if job_result else None,
            "error": f"Extraction failed with status: {extract_status}",
        }

    # Step 2: Normalization (already done by extractor via JobExtractionResult validators)
    print(
        f"[2/6] Extraction successful: {job_result.title} @ {job_result.company}", file=sys.stderr
    )

    # Step 3: Duplicate detection (job-level)
    print("[3/6] Checking job-level duplicates...", file=sys.stderr)
    recent_jobs = [dict(row) for row in await db_repo.find_recent_jobs(30)]
    duplicate_parent = check_job_level_duplicate(job_result.model_dump(), recent_jobs)

    is_duplicate = duplicate_parent is not None
    parent_id = duplicate_parent["id"] if duplicate_parent else None
    duplicate_method = duplicate_parent.get("match_method") if duplicate_parent else None

    if is_duplicate:
        print(f"    → DUPLICATE of job #{parent_id} (method: {duplicate_method})", file=sys.stderr)
    else:
        print("    → No duplicate found", file=sys.stderr)

    # Step 4: Classification (already part of scoring, but let's show it)
    # Step 5: Scoring
    print("[4/6] Scoring...", file=sys.stderr)
    score, classification, hard_fail_reason = scorer.score_job(job_result)
    print(f"    → Score: {score}, Classification: {classification.value}", file=sys.stderr)
    if hard_fail_reason:
        print(f"    → Hard fail: {hard_fail_reason}", file=sys.stderr)

    # Step 6: Content hash (for message-level dedup)
    content_hash = compute_text_hash(source_text)
    print(f"[5/6] Content hash: {content_hash[:16]}...", file=sys.stderr)

    # Check message-level dedup (text hash)
    existing_by_hash = await db_repo.find_message_by_hash(content_hash)
    if existing_by_hash:
        print(
            f"    → Message-level duplicate (hash match with job #{existing_by_hash['id']})",
            file=sys.stderr,
        )
    else:
        print("    → No message-level duplicate", file=sys.stderr)

    # Prepare result
    result = {
        "success": True,
        "candidate": {
            "source": candidate["source"],
            "source_url": candidate["source_url"],
            "title": candidate.get("title"),
            "company": candidate.get("company"),
            "published_at": candidate.get("published_at"),
            "discovered_at": candidate.get("discovered_at"),
            "location": candidate.get("location"),
            "workplace_type": candidate.get("workplace_type"),
            "employment_type": candidate.get("employment_type"),
            "salary_raw": candidate.get("salary_raw"),
            "description": candidate.get("description"),
            "discovery_query": candidate["discovery_query"],
        },
        "extraction": {
            "status": extract_status,
            "title": job_result.title,
            "company": job_result.company,
            "location": job_result.location,
            "workplace_type": job_result.workplace_type,
            "employment_type": job_result.employment_type,
            "experience_level": job_result.experience_level,
            "min_years_exp": job_result.min_years_exp,
            "experience_required": job_result.experience_required,
            "salary_min": job_result.salary_min,
            "salary_max": job_result.salary_max,
            "salary_currency": job_result.salary_currency,
            "salary_period": job_result.salary_period,
            "salary_raw": job_result.salary_raw,
            "skills_required": job_result.skills_required,
            "skills_preferred": job_result.skills_preferred,
            "requirements_raw": job_result.requirements_raw,
            "contacts": job_result.contacts.model_dump() if job_result.contacts else {},
            "application_url": job_result.application_url,
            "summary": job_result.summary,
            "deadline": job_result.deadline,
            "is_job_posting": job_result.is_job_posting,
        },
        "scoring": {
            "score": score,
            "classification": classification.value,
            "hard_fail_reason": hard_fail_reason,
        },
        "deduplication": {
            "message_level_hash": content_hash,
            "message_level_duplicate": existing_by_hash is not None,
            "job_level_duplicate": is_duplicate,
            "duplicate_parent_id": parent_id,
            "duplicate_method": duplicate_method,
        },
        "pipeline_metadata": {
            "source_text_length": len(source_text),
            "source_text_preview": source_text[:200] + "..."
            if len(source_text) > 200
            else source_text,
        },
    }

    return result


async def run_execute(candidate: dict, config: Settings, db_repo: Repository) -> dict:
    """
    Run full pipeline in execute mode (inserts into DB).
    Same as dry-run but persists records.
    """
    # First run dry-run to get all results
    dry_result = await run_dry_run(candidate, config, db_repo)

    if not dry_result["success"]:
        return dry_result

    # Now persist: create source, message, job
    source_url = candidate["source_url"]
    source_name = candidate["source"]
    source_text = candidate["source_text"]
    published_at = (
        candidate.get("published_at")
        or candidate.get("discovered_at")
        or datetime.now(UTC).isoformat()
    )
    discovered_at = candidate.get("discovered_at") or datetime.now(UTC).isoformat()

    # Create virtual IDs
    virtual_telegram_id = create_virtual_source_id(source_url)
    virtual_msg_id = create_virtual_message_id(discovered_at)

    # Insert source (type WEB)
    print(f"[Execute] Inserting source: {source_name} ({source_url})", file=sys.stderr)
    source_id = await db_repo.insert_source(
        telegram_id=virtual_telegram_id,
        title=source_name,
        source_type="WEB",
        username=source_url,
    )

    # Insert message
    print(
        f"[Execute] Inserting message (virtual telegram_msg_id={virtual_msg_id})", file=sys.stderr
    )
    msg_id = await db_repo.insert_message(
        source_id=source_id,
        telegram_msg_id=virtual_msg_id,
        raw_text=source_text,
        posted_at=published_at,
        has_media=0,
        media_dhash=None,
        processing_status=ProcessingStatus.PROCESSED.value,
    )

    if msg_id == 0:
        return {
            "success": False,
            "stage": "message_insert",
            "error": "Message already exists (idempotent)",
        }

    # Score and save job (this inserts the job)
    job_result = JobExtractionResult(**dry_result["extraction"])
    score = dry_result["scoring"]["score"]
    classification = Classification(dry_result["scoring"]["classification"])
    hard_fail_reason = dry_result["scoring"]["hard_fail_reason"] or ""

    print(
        f"[Execute] Inserting job (score={score}, classification={classification.value})",
        file=sys.stderr,
    )
    job_id = await db_repo.insert_job(
        message_id=msg_id,
        source_id=source_id,
        title=job_result.title or "",
        content_hash=dry_result["deduplication"]["message_level_hash"],
        match_score=score,
        classification=classification.value,
        company=job_result.company,
        location=job_result.location,
        workplace_type=job_result.workplace_type,
        employment_type=job_result.employment_type,
        experience_level=job_result.experience_level,
        min_years_exp=job_result.min_years_exp,
        experience_required=job_result.experience_required,
        salary_min=job_result.salary_min,
        salary_max=job_result.salary_max,
        salary_currency=job_result.salary_currency,
        salary_period=job_result.salary_period,
        salary_raw=job_result.salary_raw,
        skills_required=json.dumps(job_result.skills_required),
        skills_preferred=json.dumps(job_result.skills_preferred),
        requirements_raw=json.dumps(job_result.requirements_raw),
        contacts=json.dumps(job_result.contacts.model_dump() if job_result.contacts else {}),
        application_url=job_result.application_url,
        summary=job_result.summary,
        deadline=job_result.deadline,
        hard_fail_reason=hard_fail_reason,
        is_duplicate=1 if dry_result["deduplication"]["job_level_duplicate"] else 0,
        parent_job_id=dry_result["deduplication"]["duplicate_parent_id"],
        duplicate_method=dry_result["deduplication"]["duplicate_method"],
    )

    dry_result["execute"] = {
        "source_id": source_id,
        "message_id": msg_id,
        "job_id": job_id,
        "inserted": True,
    }

    return dry_result


async def main():
    parser = argparse.ArgumentParser(description="Ingest web candidate into AI JOB FILTER pipeline")
    parser.add_argument("--file", required=True, help="Path to candidate JSON file")
    parser.add_argument(
        "--dry-run", action="store_true", default=True, help="Run without DB writes (default)"
    )
    parser.add_argument(
        "--execute", action="store_false", dest="dry_run", help="Actually insert into database"
    )
    parser.add_argument("--json-output", action="store_true", help="Output result as JSON")
    args = parser.parse_args()

    # Load candidate
    candidate = load_candidate(args.file)
    errors = validate_candidate(candidate)
    if errors:
        print("Validation errors:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading candidate: {candidate['source']} | {candidate['source_url']}", file=sys.stderr)
    print(f"Discovery query: {candidate['discovery_query']}", file=sys.stderr)
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'EXECUTE'}", file=sys.stderr)

    # Initialize config and DB
    config = Settings()
    conn = await get_connection(config.database_path)
    await apply_migrations(conn)
    db_repo = Repository(conn)

    try:
        if args.dry_run:
            result = await run_dry_run(candidate, config, db_repo)
        else:
            result = await run_execute(candidate, config, db_repo)

        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            # Human-readable summary
            if result["success"]:
                print("\n✅ Pipeline completed successfully")
                print(f"   Title: {result['extraction']['title']}")
                print(f"   Company: {result['extraction']['company']}")
                print(
                    f"   Score: {result['scoring']['score']} ({result['scoring']['classification']})"
                )
                if result["scoring"]["hard_fail_reason"]:
                    print(f"   Hard fail: {result['scoring']['hard_fail_reason']}")
                print(f"   Job-level duplicate: {result['deduplication']['job_level_duplicate']}")
                if result["deduplication"]["job_level_duplicate"]:
                    print(
                        f"   Duplicate of job #{result['deduplication']['duplicate_parent_id']} ({result['deduplication']['duplicate_method']})"
                    )
                print(
                    f"   Message-level duplicate: {result['deduplication']['message_level_duplicate']}"
                )
                if not args.dry_run and "execute" in result:
                    print(
                        f"   Inserted: source_id={result['execute']['source_id']}, message_id={result['execute']['message_id']}, job_id={result['execute']['job_id']}"
                    )
            else:
                print(
                    f"\n❌ Pipeline failed at {result.get('stage', 'unknown')}: {result.get('error', 'Unknown error')}"
                )
                sys.exit(1)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
