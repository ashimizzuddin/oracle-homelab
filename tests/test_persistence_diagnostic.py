import json
from unittest.mock import MagicMock

import aiosqlite
import pytest

from ai_job_filter.db.repository import Repository
from ai_job_filter.models.enums import Classification
from ai_job_filter.models.job import JobExtractionResult
from ai_job_filter.processing.pipeline import score_and_save_job


@pytest.fixture
async def setup_db(tmp_path):
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        with open("migrations/001_initial_schema.sql") as f:
            await conn.executescript(f.read())
        await conn.execute("INSERT INTO sources (id, telegram_id, title) VALUES (1, 123, 'test')")
        await conn.execute(
            "INSERT INTO messages (id, source_id, telegram_msg_id, raw_text, processing_status, posted_at) VALUES (1, 1, 100, 'text', 'PROCESSED', '2026-01-01')"
        )
        await conn.commit()
        yield conn


@pytest.mark.asyncio
async def test_persistence_preserves_all_extracted_fields(setup_db):
    conn = setup_db
    repo = Repository(conn)

    mock_scorer = MagicMock()
    mock_scorer.score_job.return_value = (85, Classification.APPLY, "hard_fail_none")

    job_result = JobExtractionResult(
        is_job_posting=True,
        title="Network Security Engineer",
        company="TechCorp",
        location="Jakarta",
        min_years_exp=2,
        experience_required="required",
        workplace_type="remote",
        employment_type="full_time",
        experience_level="mid_level",
        salary_min=10000000,
        salary_max=20000000,
        salary_currency="IDR",
        salary_period="monthly",
        salary_raw="10-20jt",
        skills_required=["Fortinet", "IPsec VPN", "SD-WAN"],
        skills_preferred=["ZTNA"],
        requirements_raw=["Must have Fortinet cert", "3 years IT"],
        contacts={"emails": ["jobs@techcorp.com"]},
        deadline="2026-12-31",
        summary="A great security role.",
    )

    job_id, _score, _classification = await score_and_save_job(
        db_repo=repo,
        scorer=mock_scorer,
        msg_id=1,
        source_id=1,
        raw_text="Network Security Engineer ...",
        job_result=job_result,
    )

    async with conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cursor:
        row = dict(await cursor.fetchone())

    assert row["title"] == "Network Security Engineer"
    assert row["company"] == "TechCorp"
    assert row["location"] == "Jakarta"
    assert row["min_years_exp"] == 2
    assert row["experience_required"] == "required"
    assert row["workplace_type"] == "remote"
    assert row["employment_type"] == "full_time"
    assert row["experience_level"] == "mid_level"
    assert row["salary_min"] == 10000000
    assert row["salary_max"] == 20000000
    assert row["salary_currency"] == "IDR"
    assert row["salary_period"] == "monthly"
    assert row["salary_raw"] == "10-20jt"
    assert json.loads(row["skills_required"]) == ["Fortinet", "IPsec VPN", "SD-WAN"]
    assert json.loads(row["skills_preferred"]) == ["ZTNA"]
    assert json.loads(row["requirements_raw"]) == ["Must have Fortinet cert", "3 years IT"]
    assert json.loads(row["contacts"]) == {
        "emails": ["jobs@techcorp.com"],
        "phone_numbers": [],
        "whatsapp": [],
        "telegram_handles": [],
        "other": [],
    }
    assert row["deadline"] == "2026-12-31"
    assert row["summary"] == "A great security role."
    assert row["match_score"] == 85
    assert row["classification"] == "APPLY"
    assert row["hard_fail_reason"] == "hard_fail_none"
    assert row["score_breakdown"] == "{}"
