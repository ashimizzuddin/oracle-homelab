from typing import Protocol


class TextProvider(Protocol):
    async def extract_job(self, text: str, schema: type) -> dict | None: ...


class VisionProvider(Protocol):
    async def extract_from_image(
        self, image_path: str, schema: type, caption: str | None = None
    ) -> dict | None: ...
