from .base import TextProvider


class GroqProvider(TextProvider):
    def __init__(self, api_key: str | None = None, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key
        self.model = model

    async def extract_job(self, text: str, schema: type) -> dict | None:
        if not self.api_key:
            raise ValueError("Groq API key required but not configured.")
        raise NotImplementedError("Phase 2: Groq extraction")
