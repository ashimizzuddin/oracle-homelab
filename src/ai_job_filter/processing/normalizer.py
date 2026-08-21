import hashlib
import re
from urllib.parse import urlparse


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    # Lowercase, replace newlines/tabs with space, collapse spaces, strip
    text = text.lower()
    text = re.sub(r"[\r\n\t]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compute_text_hash(normalized_text: str) -> str:
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def normalize_url(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url.lower().strip())
    # Strip scheme, trailing slashes, and query params (for dedup purposes)
    netloc = parsed.netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    return f"{netloc}{path}"
