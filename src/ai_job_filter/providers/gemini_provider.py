from .base import TextProvider, VisionProvider


class GeminiProvider(TextProvider, VisionProvider):
    def __init__(self, api_key: str | None = None, model: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model

    async def extract_job(self, text: str, schema: type) -> dict | None:
        if not self.api_key:
            raise ValueError("Gemini API key required but not configured.")
        raise NotImplementedError("Phase 2: Gemini text extraction")

    async def extract_from_image(
        self, image_path: str, schema: type, caption: str | None = None
    ) -> dict | None:
        if not self.api_key:
            raise ValueError("Gemini API key required but not configured.")
        raise NotImplementedError("Phase 2: Gemini vision extraction")
