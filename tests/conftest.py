import json

import pytest

from ai_job_filter.config import Settings
from ai_job_filter.db.connection import get_connection
from ai_job_filter.db.migrations import apply_migrations
from ai_job_filter.models.candidate import CandidateProfile


@pytest.fixture
def mock_settings():
    return Settings(
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_session_string=None,
        telegram_bot_token=None,
        user_chat_id=None,
        groq_api_key=None,
        gemini_api_key=None,
        database_path=":memory:",
    )


@pytest.fixture
def sample_job_post():
    with open("tests/fixtures/sample_job_posts.json") as f:
        return json.load(f)[0]


@pytest.fixture
def candidate_profile():
    # Provide a mock profile for testing instead of requiring a real yaml file
    return CandidateProfile(
        professional_years=0,
        certification="RHCSA",
        strong_technical_areas=[
            "Linux",
            "System Administration",
            "RHEL",
            "Networking",
            "VMware",
            "Kali Linux",
            "Bash",
        ],
        career_direction=["Cybersecurity", "SOC", "Penetration Testing"],
        target_experience=["entry-level", "junior", "fresh graduate"],
        target_roles=["IT Staff", "Linux Administrator", "Junior SOC Analyst"],
        weaknesses_not_professional_strengths=["No professional development experience"],
    )


@pytest.fixture
async def in_memory_db():
    conn = await get_connection(":memory:")
    await apply_migrations(conn)
    yield conn
    await conn.close()
