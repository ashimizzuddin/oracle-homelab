from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Telegram (Optional for testing)
    telegram_api_id: int | None = None
    telegram_api_hash: SecretStr | None = None
    telegram_session_string: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    user_chat_id: int | None = None
    authorized_user_id: int | None = None
    telegram_channels: str = ""

    # Phase 3 Configuration
    history_lookback_hours: int = 24
    history_max_messages: int = 500
    max_media_size_mb: int = 10
    dry_run: bool = True

    # LLM Providers (Optional for testing)
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    # Application
    database_path: str = "data/jobs.db"

    # Model Configuration (static for MVP)
    text_model: str = "llama-3.3-70b-versatile"
    text_provider: str = "groq"
    vision_model: str = "gemini-2.5-flash"
    vision_provider: str = "gemini"

    # Scoring Thresholds
    min_score_apply: int = 75
    min_score_review: int = 55

    @property
    def channel_list(self) -> list[int | str]:
        channels = []
        for c in self.telegram_channels.split(","):
            c = c.strip()
            if not c:
                continue
            try:
                channels.append(int(c))
            except ValueError:
                channels.append(c)
        return channels
