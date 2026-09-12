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

from .relevance import category_hint as _category_hint
from .relevance import classify_reason, is_it_job

logger = structlog.get_logger()

# Bump when the IT classifier changes: filtered slugs are keyed by version,
# so a bump re-evaluates everything the previous version rejected.
IT_FILTER_VERSION = "it-v1"
FILTERED_PREFIX = "__filtered__:"

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
    # Boards whose sitemap covers the whole site must not store non-IT rows:
    # before this flag existed, Dealls and KitaLulus were storing every
    # category (housekeeping, personal trainer, ...) into the jobs table.
    it_only: bool = True
    # Hard cap on detail fetches as a multiple of max_items. Needed because
    # ``max_items`` counts ACCEPTED candidates, while a whole-site sitemap
    # may need many attempts before finding enough IT postings.
    attempt_multiplier: int = 3


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

    # -- relevance filtering ----------------------------------------------

    def category_hint(self) -> str:
        """Extra search terms from this board's ``options`` block.

        Makes the previously-dead ``keywords`` / ``category_path`` /
        ``specialization`` keys meaningful.
        """
        return _category_hint(self.config.options)

    def listing_stats_extra(self) -> dict:
        """Extra stats keys a board wants persisted in ``fetcher_state.stats``.

        Overridden by boards that keep a cross-run cursor.
        """
        return {}

    @staticmethod
    def it_filter_version() -> str:
        """Marker stored alongside filtered slugs.

        Bump when the classifier changes so previously-filtered postings are
        re-evaluated instead of being skipped forever.
        """
        return IT_FILTER_VERSION

    @classmethod
    def _filtered_key(cls, slug: str) -> str:
        """Key for a slug rejected by the IT filter at the CURRENT version.

        The version is part of the key, so bumping ``IT_FILTER_VERSION``
        makes every previously-filtered slug eligible again.
        """
        return f"{FILTERED_PREFIX}{IT_FILTER_VERSION}:{slug}"

    @staticmethod
    def _is_filtered_key(slug: str) -> bool:
        return slug.startswith(FILTERED_PREFIX)

    @classmethod
    def _prune_old_filtered_keys(cls, slugs: list[str]) -> list[str]:
        """Drop filtered markers from previous versions (they are stale)."""
        prefix = f"{FILTERED_PREFIX}{IT_FILTER_VERSION}:"
        out = []
        for s in slugs:
            if cls._is_filtered_key(s) and not s.startswith(prefix):
                continue
            out.append(s)
        return out

    # -- board-specific hooks -------------------------------------------

    @abstractmethod
    async def fetch_listing(self) -> list[dict[str, str]]:
        """Return list of {'slug': ..., 'url': ...} for current listings."""

    @abstractmethod
    async def fetch_detail(self, url: str) -> RawCandidate | None:
        """Fetch one job detail page and build a RawCandidate."""

    # -- orchestration ---------------------------------------------------

    async def run(self, dry_run: bool = True, limit: int | None = None) -> dict:
        """One daily pass: listing -> new only -> detail -> candidates.

        ``max_items`` bounds ACCEPTED candidates (IT-relevant ones after
        filtering), not raw fetches, so a whole-site sitemap still yields a
        useful batch. ``attempt_multiplier`` bounds total detail fetches so
        the run cannot crawl all day.
        """
        stats = {"found": 0, "new": 0, "fetched": 0, "failed": 0, "skipped": 0, "filtered": 0}
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
        # Boards with their own cross-run cursor (e.g. which sitemap page to
        # resume from) contribute extra keys here.
        stats.update(self.listing_stats_extra())
        max_items = limit or self.config.max_items
        max_attempts = max(max_items, max_items * max(1, self.config.attempt_multiplier))
        hint = self.category_hint() if self.config.it_only else ""
        it_only = bool(self.config.it_only)
        marker = self.it_filter_version() if it_only else ""

        candidates: list[RawCandidate] = []
        attempts = 0
        for item in listings:
            slug = item.get("slug", "")
            url = item.get("url", "")
            # Skip already-ingested slugs and slugs the CURRENT filter version
            # already rejected (older-version markers are pruned, so they get
            # re-evaluated).
            if not url or slug in seen or self._filtered_key(slug) in seen:
                stats["skipped"] += 1
                continue
            if len(candidates) >= max_items or attempts >= max_attempts:
                break

            await self.polite_delay()
            attempts += 1
            try:
                candidate = await self.fetch_detail(url)
            except Exception as e:
                logger.warning("Detail fetch failed", source=self.source, url=url, error=str(e))
                stats["failed"] += 1
                continue

            stats["fetched"] += 1
            if not candidate:
                continue

            if it_only and not is_it_job(candidate.title, candidate.description, hint=hint):
                reason = classify_reason(candidate.title, candidate.description, hint=hint)
                seen.add(self._filtered_key(slug))
                stats["filtered"] += 1
                logger.info(
                    "Filtered non-IT candidate",
                    source=self.source,
                    title=candidate.title,
                    reason=f"{marker}: {reason}",
                )
                continue

            candidates.append(candidate)
            seen.add(slug)
            stats["new"] += 1

        # Persist state even in dry_run so repeated dry-runs don't refetch?
        # No: dry_run must not mutate state (mirrors ingest semantics).
        if self.db_repo and not dry_run:
            await self.db_repo.save_fetcher_state(
                self.source, sorted(self._prune_old_filtered_keys(sorted(seen))), "ok", stats
            )

        logger.info("Fetcher run complete", source=self.source, dry_run=dry_run, **stats)
        self.last_candidates = candidates
        return stats
