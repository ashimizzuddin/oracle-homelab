import os

import pytest

from ai_job_filter.config import Settings
from ai_job_filter.models.job import JobExtractionResult
from ai_job_filter.processing.extractor import ExtractorPipeline
from ai_job_filter.processing.vision import VisionPipeline
from ai_job_filter.providers.gemini_provider import GeminiProvider
from ai_job_filter.providers.groq_provider import GroqProvider

# To run these tests: uv run pytest tests/ -m integration -v (Requires GROQ_API_KEY and GEMINI_API_KEY)


def get_groq_key():
    return os.environ.get("GROQ_API_KEY")


def get_gemini_key():
    return os.environ.get("GEMINI_API_KEY")


@pytest.mark.integration
@pytest.mark.skipif(not get_groq_key(), reason="GROQ_API_KEY not set")
async def test_groq_extraction_real():
    settings = Settings()
    provider = GroqProvider(api_key=get_groq_key(), model=settings.text_model)

    # Verify we are using the correct model
    assert "120b" in provider.model

    sample_text = """
    Dibutuhkan Segera: Python Developer
    Lokasi: Jakarta Selatan (WFO)
    Pengalaman minimal 2 tahun.
    Gaji: Rp 10.000.000 - Rp 15.000.000
    Kirim CV ke hr@techindo.com
    """

    pipeline = ExtractorPipeline(provider)
    result_dict = await pipeline._extract_with_retry(sample_text)

    assert result_dict is not None

    job = JobExtractionResult(**result_dict)
    assert job.is_job_posting is True
    assert "Python" in job.title or "Developer" in job.title
    assert job.min_years_exp == 2
    assert job.salary_min == 10000000
    assert job.salary_max == 15000000

    # It must be string even if model produced null initially
    assert isinstance(job.experience_level, str)


@pytest.mark.integration
@pytest.mark.skipif(not get_gemini_key(), reason="GEMINI_API_KEY not set")
async def test_gemini_vision_extraction_real(tmp_path):
    from PIL import Image, ImageDraw

    image_path = str(tmp_path / "synthetic_job.jpg")
    img = Image.new("RGB", (400, 200), color=(255, 255, 255))
    d = ImageDraw.Draw(img)

    text = "We are hiring a DevOps Engineer!\nRemote work, 3 years experience required.\nSalary $5000/month."
    d.text((10, 10), text, fill=(0, 0, 0))
    img.save(image_path)

    settings = Settings()
    provider = GeminiProvider(api_key=get_gemini_key(), model=settings.vision_model)

    pipeline = VisionPipeline(provider)
    # This will apply the bounded exponential backoff. If it still fails,
    # the integration test will rightfully fail. No try-except masking.
    result_dict = await pipeline._extract_with_retry(image_path, None)

    assert result_dict is not None

    job = JobExtractionResult(**result_dict)
    assert job.is_job_posting is True
    assert "DevOps" in job.title
