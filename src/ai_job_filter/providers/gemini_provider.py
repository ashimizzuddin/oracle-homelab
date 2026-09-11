from google import genai
from google.genai import types
from google.genai.errors import APIError

from .base import TextProvider, VisionProvider
from .errors import ProviderExtractionError, ProviderRateLimitError, TransientAPIError
from .prompts import SYSTEM_PROMPT
from .rate_budget import GeminiBudget


class GeminiProvider(TextProvider, VisionProvider):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        budget: GeminiBudget | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.client = genai.Client(api_key=api_key) if api_key else None
        # Client-side guard for the small free-tier quota (8 RPM / 18 RPD).
        # Budget file is only touched lazily on first real API call.
        self.budget = budget or GeminiBudget()

    async def _generate(self, contents: list, schema: type) -> dict | None:
        if not self.api_key or not self.client:
            raise ValueError("Gemini API key required but not configured.")

        allowed, reason = self.budget.allow()
        if not allowed:
            raise ProviderRateLimitError(f"Gemini client budget exhausted: {reason}")

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.0,
            system_instruction=SYSTEM_PROMPT,
        )

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            )

            text_content = response.text or "{}"
            # Count the call against the client-side budget only after the
            # server accepted it (server 429s are tracked via cooldown below).
            self.budget.record()
            # Let pydantic validate the JSON response string directly
            validated = schema.model_validate_json(text_content)
            return validated.model_dump()

        except APIError as e:
            if e.code == 429:
                self.budget.cooldown_from_error(str(e))
                raise ProviderRateLimitError(f"Gemini Rate Limit: {e}") from e
            elif e.code in [500, 502, 503, 504]:
                raise TransientAPIError(f"Gemini Transient Error ({e.code}): {e.message}") from e
            else:
                # 400, 401, 403, 404 etc
                raise ProviderExtractionError(f"Gemini API Error ({e.code}): {e.message}") from e
        except Exception as e:
            raise ProviderExtractionError(f"Gemini Extraction Failed: {e}") from e

    async def extract_job(self, text: str, schema: type) -> dict | None:
        return await self._generate([text], schema)

    async def extract_from_image(
        self, image_path: str, schema: type, caption: str | None = None
    ) -> dict | None:
        if not self.api_key or not self.client:
            raise ValueError("Gemini API key required but not configured.")

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        # Determine mime type simply by extension
        mime_type = "image/jpeg" if image_path.lower().endswith((".jpg", ".jpeg")) else "image/png"

        image_part = types.Part.from_bytes(
            data=image_bytes,
            mime_type=mime_type,
        )

        contents = [image_part]
        if caption:
            contents.append(caption)

        return await self._generate(contents, schema)
