from unittest.mock import MagicMock

import pytest

from ai_job_filter.config import Settings
from ai_job_filter.db.repository import Repository
from ai_job_filter.telegram.notifier import TelegramNotifier


@pytest.fixture
def mock_config():
    return Settings(
        telegram_api_id=123,
        telegram_bot_token="test:token",
        user_chat_id=999,
        authorized_user_id=111,
        dry_run=True,
        database_path=":memory:",
    )


@pytest.mark.asyncio
async def test_notifier_dry_run(mock_config, in_memory_db, capsys):
    repo = in_memory_db
    notifier = TelegramNotifier(mock_config, repo)

    job_dict = {
        "title": "Backend Developer",
        "company": "TestCorp",
        "match_score": 85,
        "location": "Remote",
        "salary_min": 1000,
        "salary_max": 2000,
        "summary": "Great job",
        "application_url": "http://test.com",
    }

    await notifier.send_job_alert(job_dict, notification_id=1)

    captured = capsys.readouterr()
    assert "[DRY RUN]" in captured.out
    assert "Backend Developer" in captured.out
    assert "TestCorp" in captured.out


@pytest.mark.asyncio
async def test_idempotent_notification(mock_config, in_memory_db):
    repo = in_memory_db

    await repo.conn.execute("""
        INSERT INTO sources (id, telegram_id, title, source_type) VALUES (1, 123, 'test', 'CHANNEL')
    """)
    await repo.conn.execute("""
        INSERT INTO messages (id, source_id, telegram_msg_id, raw_text, posted_at, has_media)
        VALUES (1, 1, 1, 'text', '2023', 0)
    """)
    await repo.conn.execute("""
        INSERT INTO jobs (id, message_id, source_id, title, content_hash, match_score, classification)
        VALUES (1, 1, 1, 'test', 'hash', 80, 'APPLY')
    """)
    await repo.conn.commit()

    # First notification should return > 0
    notif_id = await repo.insert_notification(1, 999)
    assert notif_id > 0

    # Second notification for same job should return 0
    notif_id2 = await repo.insert_notification(1, 999)
    assert notif_id2 == 0


@pytest.mark.asyncio
async def test_callback_authorization(mock_config, in_memory_db, capsys):
    repo = in_memory_db
    notifier = TelegramNotifier(mock_config, repo)

    # Mock update
    class MockUser:
        id = 222  # wrong user

    class MockChat:
        id = 999  # correct chat

    class MockMessage:
        chat = MockChat()
        text = "original"

    class MockQuery:
        from_user = MockUser()
        message = MockMessage()
        data = "act_a_1"

        async def answer(self, text=None, show_alert=False):
            pass

    class MockUpdate:
        callback_query = MockQuery()

    # Send unauthorized
    await notifier._handle_callback(MockUpdate(), None)
    assert "Unauthorized callback attempt" in capsys.readouterr().out

    # Send authorized
    MockQuery.from_user.id = 111  # correct user
    # we need to insert a fake notification
    # we need to insert a fake notification
    await repo.conn.execute(
        "INSERT INTO sources (id, telegram_id, title, source_type) VALUES (1, 123, 'test', 'CHANNEL')"
    )
    await repo.conn.execute(
        "INSERT INTO messages (id, source_id, telegram_msg_id, raw_text, posted_at, has_media) VALUES (1, 1, 1, 'text', '2023', 0)"
    )
    await repo.conn.execute(
        "INSERT INTO jobs (id, message_id, source_id, title, content_hash, match_score, classification) VALUES (1, 1, 1, 'test', 'hash', 80, 'APPLY')"
    )
    await repo.conn.execute("INSERT INTO notifications (id, job_id, chat_id) VALUES (1, 1, 999)")
    await repo.conn.commit()

    # Mock edit message
    MockQuery.edit_message_text = MagicMock()

    async def mock_edit(*args, **kwargs):
        pass

    MockQuery.edit_message_text = mock_edit

    await notifier._handle_callback(MockUpdate(), None)

    # verify DB updated
    async with repo.conn.execute("SELECT user_action FROM notifications WHERE id = 1") as cursor:
        row = await cursor.fetchone()
        assert row["user_action"] == "APPLIED"


@pytest.mark.asyncio
async def test_notifier_html_escaping(mock_config, in_memory_db, capsys):
    repo = in_memory_db
    notifier = TelegramNotifier(mock_config, repo)

    job_dict = {
        "title": "Backend <Developer> & Data_Engineer",
        "company": "Test*Corp* [Inc]",
        "match_score": 85,
        "location": "Remote `City`",
        "salary_min": 1000,
        "salary_max": 2000,
        "summary": "We need someone to write <b>bold</b> and `code`.",
        "application_url": "http://test.com/?q=1&b=2",
    }

    await notifier.send_job_alert(job_dict, notification_id=1)

    captured = capsys.readouterr()
    out = captured.out

    assert "&lt;Developer&gt; &amp; Data_Engineer" in out
    assert "Test*Corp* [Inc]" in out
    assert "Remote `City`" in out
    assert "&lt;b&gt;bold&lt;/b&gt;" in out
    assert "http://test.com/?q=1&amp;b=2" in out
    assert "<b>85/100 | Backend &lt;Developer&gt; &amp; Data_Engineer</b>" in out
