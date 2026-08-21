from ..models.job import JobExtractionResult
from ..providers.base import VisionProvider


class VisionPipeline:
    def __init__(self, provider: VisionProvider):
        self.provider = provider

    async def run(self, image_path: str, caption: str | None = None) -> JobExtractionResult | None:
        # Stub logic for Phase 1
        return None
