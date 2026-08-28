"""Web fetcher base classes and shared utilities (PRD F-WEB-1).

Design:
- ``BaseFetcher`` is an abstract template handling the common loop:
  list -> filter new -> fetch detail -> build candidate -> ingest -> save state.
- Board-specific subclasses implement ``fetch_listing`` and ``fetch_detail``.
- Politeness defaults: per-board delay + jitter, descriptive User-Agent,
  timeout, and tenacity-style bounded retries on transient errors.
"""

from __future__ import annotations

import asyncio
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 AI-JOB-FILTER/1.0 (personal; contact via repo)"
)

# Tags stripped from extracted text before building source_text
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class FetcherConfig:
    """Per-board settings (loaded from config/web_fetchers.yaml)."""

    name: str
    base_url: str
    enabled: bool = True
    interval_hours: int = 24
    delay_seconds: float = 3.0
    max_items: int = 20
    use_playwright: bool = False
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawCandidate:
    """Normalized candidate ready for ingest_web_candidate pipeline."""

    source: str
    source_url: str
    title: str
    company: str
    location: str | None
    description: str
    source_text: str
    discovered_at: str
    published_at: str | None = None
    workplace_type: str = "unknown"
    employment_type: str = "unknown"
    salary_raw: str | None = None
    discovery_query: str = ""


def strip_html(html: str) -> str:
    """Best-effort HTML -> plain text (no external deps)."""
    text = _SCRIPT_STYLE_RE.sub(" ", html or "")
    text = _TAG_RE.sub("\n", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class BaseFetcher(ABC):
    """Template for one job board.

    Subclasses set ``source`` and implement ``fetch_listing``/``fetch_detail``.
    The ``run`` loop dedups via Repository.fetcher_state so state survives
    restarts (PRD F-WEB-3).
    """

    source: str = "unknown"

    def __init__(self, config: FetcherConfig, db_repo=None):
        self.config = config
        self.db_repo = db_repo

    # -- shared HTTP ---------------------------------------------------

    async def http_get(self, url: str, timeout: int = 30) -> str | None:
        """GET with bounded retries. Returns text or None. No JS rendering."""
        import urllib.error
        import urllib.request

        for attempt in range(3):
            try:
                loop = asyncio.get_running_loop()

                def _fetch(target_url=url, t=timeout):
                    req = urllib.request.Request(target_url, headers={"User-Agent": USER_AGENT})
                    return urllib.request.urlopen(req, timeout=t)

                resp = await loop.run_in_executor(None, _fetch)
                body = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                return body.decode(charset, errors="replace")
            except urllib.error.HTTPError as e:
                if e.code in (403, 404, 410):
                    logger.warning("HTTP permanent error", url=url, code=e.code)
                    return None
                logger.warning("HTTP transient error", url=url, code=e.code, attempt=attempt + 1)
            except Exception as e:
                logger.warning("HTTP fetch failed", url=url, error=str(e), attempt=attempt + 1)
            await asyncio.sleep(2 * (attempt + 1))
        return None

    async def polite_delay(self):
        """Per-board delay + jitter (PRD F-WEB-4)."""
        jitter = random.uniform(0.5, 1.5)
        await asyncio.sleep(self.config.delay_seconds * jitter)

    # -- board-specific hooks -------------------------------------------

    @abstractmethod
    async def fetch_listing(self) -> list[dict[str, str]]:
        """Return list of {'slug': ..., 'url': ...} for current listings."""

    @abstractmethod
    async def fetch_detail(self, url: str) -> RawCandidate | None:
        """Fetch one job detail page and build a RawCandidate."""

    # -- orchestration ---------------------------------------------------

    async def run(self, dry_run: bool = True, limit: int | None = None) -> dict:
        """One daily pass: listing -> new only -> detail -> candidates."""
        stats = {"found": 0, "new": 0, "fetched": 0, "failed": 0, "skipped": 0}
        seen: set[str] = set()

        if self.db_repo:
            prev, _ = await self.db_repo.get_fetcher_state(self.source)
            seen = set(prev)

        try:
            listings = await self.fetch_listing()
        except Exception as e:
            logger.error("Listing fetch failed", source=self.source, error=str(e))
            stats["failed"] = 1
            if self.db_repo and not dry_run:
                await self.db_repo.save_fetcher_state(self.source, sorted(seen), "error", stats)
            return stats

        stats["found"] = len(listings)
        max_items = limit or self.config.max_items

        candidates: list[RawCandidate] = []
        for item in listings:
            slug = item.get("slug", "")
            url = item.get("url", "")
            if not url or slug in seen:
                stats["skipped"] += 1
                continue
            if stats["fetched"] >= max_items:
                break

            await self.polite_delay()
            try:
                candidate = await self.fetch_detail(url)
            except Exception as e:
                logger.warning("Detail fetch failed", source=self.source, url=url, error=str(e))
                stats["failed"] += 1
                continue

            stats["fetched"] += 1
            if candidate:
                candidates.append(candidate)
                seen.add(slug)
                stats["new"] += 1

        # Persist state even in dry_run so repeated dry-runs don't refetch?
        # No: dry_run must not mutate state (mirrors ingest semantics).
        if self.db_repo and not dry_run:
            await self.db_repo.save_fetcher_state(self.source, sorted(seen), "ok", stats)

        logger.info("Fetcher run complete", source=self.source, dry_run=dry_run, **stats)
        self.last_candidates = candidates
        return stats
