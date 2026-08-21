import httpx
import structlog
from google.genai.errors import APIError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..models.job import JobExtractionResult
from ..providers.base import VisionProvider
from ..providers.errors import ProviderExtractionError, ProviderRateLimitError

logger = structlog.get_logger()


# We consider a generic APIError as transient except 429 which we catch specifically in the provider
class VisionPipeline:
    def __init__(self, provider: VisionProvider):
        self.provider = provider

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.RequestError, APIError)),
        reraise=True,
    )
    async def _extract_with_retry(self, image_path: str, caption: str | None) -> dict | None:
        return await self.provider.extract_from_image(image_path, JobExtractionResult, caption)

    async def run(
        self, image_path: str, caption: str | None = None
    ) -> tuple[JobExtractionResult | None, str]:
        """
        Returns (result, status) where status can be 'PROCESSED', 'PENDING_VISION', or 'VISION_FAILED'
        """
        try:
            for attempt in range(3):
                try:
                    result_dict = await self._extract_with_retry(image_path, caption)
                    if result_dict:
                        return JobExtractionResult(**result_dict), "PROCESSED"
                    return None, "VISION_FAILED"
                except ProviderExtractionError as e:
                    logger.warning(f"Vision extraction attempt {attempt + 1} failed: {e}")
                    if attempt == 2:
                        return None, "VISION_FAILED"

            return None, "VISION_FAILED"

        except ProviderRateLimitError as e:
            logger.warning(f"Vision rate limited: {e}")
            return None, "PENDING_VISION"
        except Exception as e:
            logger.error(f"Unexpected vision error: {e}")
            return None, "VISION_FAILED"
