"""Web fetcher package — PRD F-WEB-5, 11 boards (skip Jobstreet & LinkedIn)."""

from .base import BaseFetcher, FetcherConfig, RawCandidate, strip_html

__all__ = ["BaseFetcher", "FetcherConfig", "RawCandidate", "strip_html"]
