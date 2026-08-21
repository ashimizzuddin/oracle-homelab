from ..models.job import JobExtractionResult
from ..providers.base import TextProvider


class ExtractorPipeline:
    def __init__(self, provider: TextProvider):
        self.provider = provider

    async def run(self, text: str) -> JobExtractionResult | None:
        # Stub logic for Phase 1
        return None
