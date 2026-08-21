from ai_job_filter.config import Settings
from ai_job_filter.providers.groq_provider import GroqProvider


def test_configured_text_model_reaches_provider():
    settings = Settings(text_model="openai/gpt-oss-120b")
    provider = GroqProvider(api_key="dummy", model=settings.text_model)
    assert provider.model == "openai/gpt-oss-120b"
