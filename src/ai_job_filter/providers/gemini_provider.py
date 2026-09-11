import structlog
from google import genai
from google.genai import types
from google.genai.errors import APIError

from .base import TextProvider, VisionProvider
from .errors import ProviderExtractionError, ProviderRateLimitError, TransientAPIError
from .prompts import SYSTEM_PROMPT
from .rate_budget import GeminiBudget, parse_retry_delay_seconds

logger = structlog.get_logger()


class GeminiProvider(TextProvider, VisionProvider):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        max_rpm: int = 8,
        max_rpd: int = 18,
        budget_path: str | None = None,
        budget: GeminiBudget | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.client = genai.Client(api_key=api_key) if api_key else None
        # In-memory by default (tests); daemon passes a JSON path via Settings.
        self.budget = budget or GeminiBudget(
            max_rpm=max_rpm, max_rpd=max_rpd, budget_path=budget_path
        )

    async def _generate(self, contents: list, schema: type) -> dict | None:
        if not self.api_key or not self.client:
            raise ValueError("Gemini API key required but not configured.")

        # Client-side guard: fail fast as PENDING instead of burning quota.
        await self.budget.acquire()

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
            # Let pydantic validate the JSON response string directly
            validated = schema.model_validate_json(text_content)
            return validated.model_dump()

        except APIError as e:
            if e.code == 429:
                retry_after = parse_retry_delay_seconds(str(e))
                await self.budget.note_rate_limited(retry_after)
                logger.warning(
                    "Gemini 429 rate limited",
                    model=self.model,
                    retry_after_s=retry_after,
                    error=str(e)[:500],
                )
                raise ProviderRateLimitError(
                    f"Gemini Rate Limit (429, retry in {retry_after}s): {e}"
                ) from e
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

        image_bytes, mime_type = _load_image_bytes(image_path)

        image_part = types.Part.from_bytes(
            data=image_bytes,
            mime_type=mime_type,
        )

        contents = [image_part]
        if caption:
            contents.append(caption)

        return await self._generate(contents, schema)


def _load_image_bytes(image_path: str) -> tuple[bytes, str]:
    """Read image bytes, downscaling large posters to save TPM/latency.

    Best-effort: on any failure falls back to raw bytes. Never writes to disk.
    """
    lower = image_path.lower()
    mime_type = "image/jpeg" if lower.endswith((".jpg", ".jpeg")) else "image/png"

    with open(image_path, "rb") as f:
        raw = f.read()

    # Skip processing for small files (most posters are already <1.5MB).
    if len(raw) < 1_500_000:
        return raw, mime_type

    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        img.thumbnail((1600, 1600), Image.LANCZOS)
        buf = io.BytesIO()
        fmt = "JPEG" if mime_type == "image/jpeg" else "PNG"
        save_kwargs = {"optimize": True}
        if fmt == "JPEG":
            save_kwargs.update({"quality": 75})
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
        img.save(buf, format=fmt, **save_kwargs)
        return buf.getvalue(), mime_type
    except Exception:
        return raw, mime_type
