import os

import pytest

from ai_job_filter.models.job import JobExtractionResult
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
    provider = GroqProvider(api_key=get_groq_key())

    sample_text = """
    Dibutuhkan Segera: Python Developer
    Lokasi: Jakarta Selatan (WFO)
    Pengalaman minimal 2 tahun.
    Gaji: Rp 10.000.000 - Rp 15.000.000
    Kirim CV ke hr@techindo.com
    """

    result_dict = await provider.extract_job(sample_text, JobExtractionResult)
    assert result_dict is not None

    job = JobExtractionResult(**result_dict)
    assert job.is_job_posting is True
    assert "Python" in job.title or "Developer" in job.title
    assert job.min_years_exp == 2
    assert job.salary_min == 10000000
    assert job.salary_max == 15000000
    assert job.workplace_type == "on-site"
    assert "hr@techindo.com" in str(job.contacts)


@pytest.mark.integration
@pytest.mark.skipif(not get_gemini_key(), reason="GEMINI_API_KEY not set")
async def test_gemini_vision_extraction_real(tmp_path):
    # We will create a very basic synthetic image with text using Pillow
    from PIL import Image, ImageDraw

    image_path = str(tmp_path / "synthetic_job.jpg")
    img = Image.new("RGB", (400, 200), color=(255, 255, 255))
    d = ImageDraw.Draw(img)

    # Just draw simple text
    text = "We are hiring a DevOps Engineer!\nRemote work, 3 years experience required.\nSalary $5000/month."
    d.text((10, 10), text, fill=(0, 0, 0))
    img.save(image_path)

    provider = GeminiProvider(api_key=get_gemini_key())

    result_dict = await provider.extract_from_image(image_path, JobExtractionResult)
    assert result_dict is not None

    job = JobExtractionResult(**result_dict)
    assert job.is_job_posting is True
    assert "DevOps" in job.title
    assert job.min_years_exp == 3
    assert job.workplace_type == "remote"
    assert job.salary_min == 5000
