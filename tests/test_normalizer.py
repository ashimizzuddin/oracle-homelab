from ai_job_filter.processing.normalizer import compute_text_hash, normalize_text, normalize_url


def test_text_normalization():
    assert normalize_text(" Hello \n World \t ") == "hello world"
    assert normalize_text(None) == ""


def test_sha256_hashing():
    text = "hello world"
    hash_val = compute_text_hash(text)
    assert len(hash_val) == 64
    assert hash_val == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_url_normalization():
    assert normalize_url("https://www.example.com/jobs/") == "example.com/jobs"
    assert normalize_url("http://Example.com/jobs?source=linkedin") == "example.com/jobs"
    assert normalize_url(None) == ""
