import json
import re

from groq import APIConnectionError, AsyncGroq, RateLimitError

from .base import TextProvider
from .errors import ProviderExtractionError, ProviderRateLimitError
from .prompts import SYSTEM_PROMPT


class GroqProvider(TextProvider):
    def __init__(self, api_key: str | None = None, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key
        self.model = model
        self.client = AsyncGroq(api_key=api_key) if api_key else None

    async def extract_job(self, text: str, schema: type) -> dict | None:
        if not self.api_key or not self.client:
            raise ValueError("Groq API key required but not configured.")

        schema_json = schema.model_json_schema()

        prompt = f"""{SYSTEM_PROMPT}

TARGET SCHEMA:
{json.dumps(schema_json, indent=2)}

JOB POSTING:
{text}
"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            content = response.choices[0].message.content or "{}"

            # Clean up markdown code blocks if the model hallucinates them
            content = re.sub(r"^```json\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

            data = json.loads(content)

            # Validate through Pydantic (will raise ValidationError if bad)
            validated = schema.model_validate(data)
            return validated.model_dump()

        except RateLimitError as e:
            raise ProviderRateLimitError(f"Groq Rate Limit: {e}") from e
        except APIConnectionError as e:
            raise e  # Let Tenacity catch this as Transient
        except Exception as e:
            raise ProviderExtractionError(f"Groq Extraction Failed: {e}") from e
