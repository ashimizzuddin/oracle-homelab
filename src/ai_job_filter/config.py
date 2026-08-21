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
    telegram_channels: str = ""

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
    def channel_list(self) -> list[str]:
        return [c.strip() for c in self.telegram_channels.split(",") if c.strip()]
