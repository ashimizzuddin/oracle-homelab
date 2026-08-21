import json
from typing import Any

from groq import APIConnectionError, AsyncGroq, InternalServerError, RateLimitError

from .base import TextProvider
from .errors import ProviderExtractionError, ProviderRateLimitError, TransientAPIError
from .prompts import SYSTEM_PROMPT


def make_schema_strict(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively enforce strict JSON schema rules for OpenAI/Groq."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            schema["additionalProperties"] = False
            # In strict mode, all properties must be required
            if "properties" in schema:
                schema["required"] = list(schema["properties"].keys())

        for key, value in schema.items():
            schema[key] = make_schema_strict(value)
    elif isinstance(schema, list):
        schema = [make_schema_strict(item) for item in schema]

    return schema


class GroqProvider(TextProvider):
    def __init__(self, model: str, api_key: str | None = None):
        self.api_key = api_key
        self.model = model
        self.client = AsyncGroq(api_key=api_key) if api_key else None

    async def extract_job(self, text: str, schema: type) -> dict | None:
        if not self.api_key or not self.client:
            raise ValueError("Groq API key required but not configured.")

        # Pydantic v2 JSON schema
        schema_json = schema.model_json_schema()

        # Enforce strict rules
        schema_json = make_schema_strict(schema_json)

        prompt = f"""{SYSTEM_PROMPT}

JOB POSTING:
{text}
"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that extracts information into the exact JSON schema provided.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "job_extraction",
                        "schema": schema_json,
                        "strict": True,
                    },
                },
                temperature=0.0,
            )
            content = response.choices[0].message.content or "{}"

            data = json.loads(content)

            # Validate through Pydantic (will raise ValidationError if bad)
            validated = schema.model_validate(data)
            return validated.model_dump()

        except RateLimitError as e:
            raise ProviderRateLimitError(f"Groq Rate Limit: {e}") from e
        except InternalServerError as e:
            raise TransientAPIError(f"Groq Transient Error: {e}") from e
        except APIConnectionError as e:
            raise TransientAPIError(f"Groq Connection Error: {e}") from e
        except Exception as e:
            raise ProviderExtractionError(f"Groq Extraction Failed: {e}") from e
