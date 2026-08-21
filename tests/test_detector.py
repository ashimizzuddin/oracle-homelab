from ai_job_filter.processing.detector import is_potential_job


def test_indonesian_job_detection():
    assert is_potential_job("Dibutuhkan IT Staff di Jakarta", has_media=False) is True
    assert is_potential_job("Loker Programmer", has_media=False) is True


def test_english_job_detection():
    assert is_potential_job("We are hiring a DevOps Engineer", has_media=False) is True
    assert is_potential_job("New job vacancy available", has_media=False) is True


def test_non_job_message():
    assert is_potential_job("Selamat pagi teman-teman", has_media=False) is False
    assert is_potential_job("Is anyone familiar with Docker?", has_media=False) is False
    assert is_potential_job(None, has_media=False) is False


def test_image_media_routing():
    # If media is present, it MUST route to vision regardless of caption text
    assert is_potential_job("Selamat pagi teman-teman", has_media=True) is True
    assert is_potential_job(None, has_media=True) is True
    assert is_potential_job("", has_media=True) is True
