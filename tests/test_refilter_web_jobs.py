"""Tests for scripts/refilter_web_jobs.py (no network, no LLM)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

import refilter_web_jobs as rf


@pytest.fixture
async def seeded_db(in_memory_db):
    """Two WEB jobs (one IT, one not) behind two messages."""
    repo = in_memory_db
    it_src = await repo.insert_source(telegram_id=111, title="dealls", source_type="WEB")
    hr_src = await repo.insert_source(telegram_id=222, title="kitalulus", source_type="WEB")

    it_msg = await repo.insert_message(
        source_id=it_src,
        telegram_msg_id=1,
        raw_text="[Hiring] DevOps Engineer\nWe run Linux, Docker and Kubernetes.",
        posted_at="2026-09-01T00:00:00+00:00",
        has_media=0,
    )
    hr_msg = await repo.insert_message(
        source_id=hr_src,
        telegram_msg_id=2,
        raw_text="[Hiring] Housekeeping Staff\nBersih-bersih kamar hotel.",
        posted_at="2026-09-01T00:00:00+00:00",
        has_media=0,
    )

    for msg_id, src_id, title in (
        (it_msg, it_src, "DevOps Engineer"),
        (hr_msg, hr_src, "Housekeeping Staff"),
    ):
        await repo.insert_job(
            message_id=msg_id,
            source_id=src_id,
            title=title,
            content_hash=f"hash-{msg_id}",
            match_score=50,
            classification="REVIEW",
        )
    return repo


class TestFullText:
    def test_joins_all_text_fields(self):
        row = {"raw_text": "a", "caption": "b", "vision_text": "c"}
        assert rf.full_text(row) == "a\nb\nc"

    def test_skips_empty(self):
        assert rf.full_text({"raw_text": "a", "caption": None, "vision_text": ""}) == "a"

    def test_missing_keys(self):
        assert rf.full_text({}) == ""


class TestCollectRows:
    @pytest.mark.asyncio
    async def test_scope_web_only(self, seeded_db):
        rows = await rf.collect_rows(seeded_db.conn, "web")
        assert len(rows) == 2
        assert all(r["source_type"] == "WEB" for r in rows)
        assert {r["title"] for r in rows} == {"DevOps Engineer", "Housekeeping Staff"}

    @pytest.mark.asyncio
    async def test_scope_all(self, seeded_db):
        rows = await rf.collect_rows(seeded_db.conn, "all")
        assert len(rows) == 2


class TestApplyFilter:
    @pytest.mark.asyncio
    async def test_dry_run_writes_nothing(self, seeded_db):
        rows = await rf.collect_rows(seeded_db.conn, "web")
        result = await rf.apply_filter(seeded_db.conn, rows, execute=False)
        assert result["considered"] == 2
        assert result["keep"] == 1
        assert result["filter"] == 1
        # nothing changed
        async with seeded_db.conn.execute(
            "SELECT classification FROM jobs WHERE title = 'Housekeeping Staff'"
        ) as cur:
            assert (await cur.fetchone())[0] == "REVIEW"

    @pytest.mark.asyncio
    async def test_execute_marks_job_and_message(self, seeded_db):
        rows = await rf.collect_rows(seeded_db.conn, "web")
        result = await rf.apply_filter(seeded_db.conn, rows, execute=True)
        assert result["filter"] == 1
        assert result["messages_marked"] == 1

        async with seeded_db.conn.execute(
            "SELECT classification, match_score, hard_fail_reason FROM jobs "
            "WHERE title = 'Housekeeping Staff'"
        ) as cur:
            cls, score, reason = await cur.fetchone()
        assert cls == "IGNORE"
        assert score == 0
        assert reason.startswith(rf.SKIP_REASON_PREFIX)

        async with seeded_db.conn.execute(
            "SELECT processing_status, skip_reason FROM messages WHERE telegram_msg_id = 2"
        ) as cur:
            status, skip = await cur.fetchone()
        assert status == "NOT_JOB"
        assert skip.startswith(rf.SKIP_REASON_PREFIX)

    @pytest.mark.asyncio
    async def test_it_job_is_untouched(self, seeded_db):
        rows = await rf.collect_rows(seeded_db.conn, "web")
        await rf.apply_filter(seeded_db.conn, rows, execute=True)
        async with seeded_db.conn.execute(
            "SELECT classification, match_score FROM jobs WHERE title = 'DevOps Engineer'"
        ) as cur:
            cls, score = await cur.fetchone()
        assert cls == "REVIEW"
        assert score == 50

    @pytest.mark.asyncio
    async def test_idempotent(self, seeded_db):
        rows = await rf.collect_rows(seeded_db.conn, "web")
        await rf.apply_filter(seeded_db.conn, rows, execute=True)
        rows2 = await rf.collect_rows(seeded_db.conn, "web")
        result2 = await rf.apply_filter(seeded_db.conn, rows2, execute=True)
        assert result2["already"] == 1
        assert result2["filter"] == 0

    @pytest.mark.asyncio
    async def test_fts_index_still_valid(self, seeded_db):
        rows = await rf.collect_rows(seeded_db.conn, "web")
        await rf.apply_filter(seeded_db.conn, rows, execute=True)
        # The jobs_fts_au trigger must keep the index consistent.
        async with seeded_db.conn.execute(
            "INSERT INTO jobs_fts(jobs_fts) VALUES('integrity-check')"
        ) as cur:
            await cur.fetchall()
        async with seeded_db.conn.execute("SELECT count(*) FROM jobs_fts") as cur:
            assert (await cur.fetchone())[0] == 2

    @pytest.mark.asyncio
    async def test_no_rows_is_safe(self, in_memory_db):
        result = await rf.apply_filter(in_memory_db.conn, [], execute=True)
        assert result["considered"] == 0
        assert result["filter"] == 0
