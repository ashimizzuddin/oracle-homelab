import groq
import httpx  # for transient network errors if using httpx underneath
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..models.job import JobExtractionResult
from ..providers.base import TextProvider
from ..providers.errors import ProviderExtractionError, ProviderRateLimitError

logger = structlog.get_logger()


class ExtractorPipeline:
    def __init__(self, provider: TextProvider):
        self.provider = provider

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(
            (httpx.RequestError, groq.APIConnectionError, groq.InternalServerError)
        ),
        reraise=True,
    )
    async def _extract_with_retry(self, text: str) -> dict | None:
        # Optimize very long text if needed here
        # We will trust the provider to handle it or we can trim redundant spaces
        return await self.provider.extract_job(text, JobExtractionResult)

    async def run(self, text: str) -> tuple[JobExtractionResult | None, str]:
        """
        Returns (result, status) where status can be 'PROCESSED', 'PENDING_AI', or 'EXTRACTION_FAILED'
        """
        try:
            # We will attempt to run extraction, catching validation/extraction errors manually for up to 2 retries
            # The tenacity retry above only handles transient network errors.
            for attempt in range(3):
                try:
                    result_dict = await self._extract_with_retry(text)
                    if result_dict:
                        return JobExtractionResult(**result_dict), "PROCESSED"
                    return None, "EXTRACTION_FAILED"
                except ProviderExtractionError as e:
                    logger.warning(f"Extraction attempt {attempt + 1} failed: {e}")
                    if attempt == 2:
                        return None, "EXTRACTION_FAILED"

            return None, "EXTRACTION_FAILED"

        except ProviderRateLimitError as e:
            logger.warning(f"Rate limited: {e}")
            return None, "PENDING_AI"
        except Exception as e:
            logger.error(f"Unexpected extraction error: {e}")
            return None, "EXTRACTION_FAILED"
