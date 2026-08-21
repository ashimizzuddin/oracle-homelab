class ProviderRateLimitError(Exception):
    """Raised when a provider hits an HTTP 429 rate limit quota."""

    pass


class ProviderExtractionError(Exception):
    """Raised when extraction fails completely (e.g., malformed JSON after retries)."""

    pass
