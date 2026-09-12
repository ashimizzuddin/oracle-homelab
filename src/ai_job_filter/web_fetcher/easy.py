"""Easy-tier fetchers (PRD F-WEB-5).

Live-verified strategies (2026-08-28):
- Dealls:     sitemap-dynamic.xml -> /loker/{slug} -> __NEXT_DATA__
              dehydratedState.queries[0].state.data  ✅ working
- KitaLulus:  sitemap.xml -> sitemap-jobs/job-detail-N.xml
              -> /lowongan/detail/{slug} -> <title> + h1 parse  ✅ working
- Talentics:  API requires auth (401) -> falls back to HTML listing,
              which is Vue-rendered (no static listing). Marked degraded;
              keeps trying /ajaxs/jobs shape in case of policy change.
- HiredToday: sitemap URLs currently 404 (stale sitemap) -> disabled by
              default in config until they fix it.
- Loker.id:   403 for our UA (bot protection) -> excluded from easy set.
- Tech in Asia: sitemap 403 for datacenter -> medium tier fallback only.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from xml.etree import ElementTree

from .base import BaseFetcher, RawCandidate, strip_html

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _fallback_body_lines(html: str, max_lines: int = 25) -> str:
    text = strip_html(html)
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 40]
    return "\n".join(lines[:max_lines])


class TalenticsFetcher(BaseFetcher):
    """Talentics: official API needs auth; HTML is Vue-rendered.

    Kept as a placeholder — stats will show found=0 unless they open the API.
    """

    source = "talentics"

    async def fetch_listing(self) -> list[dict[str, str]]:
        # Try the documented API path first (may become public again)
        body = await self.http_get(
            f"{self.config.base_url}{self.config.options.get('api_path', '/v2/jobs')}"
        )
        if body and not body.startswith('{"message":"Unauthorized"}'):
            try:
                data = json.loads(body)
            except ValueError:
                data = {}
            jobs = data.get("jobs") or data.get("data") or []
            out = []
            for j in jobs:
                slug = str(j.get("id") or j.get("slug") or "")
                if slug:
                    out.append(
                        {
                            "slug": slug,
                            "url": j.get("url") or f"https://jobs.talentics.id/jobs/{slug}",
                        }
                    )
            return out
        # Vue SPA: no static listing without a browser. Return empty politely.
        return []

    async def fetch_detail(self, url: str) -> RawCandidate | None:
        body = await self.http_get(url)
        if not body:
            return None
        m = re.search(r"<title>([^<]+)</title>", body, re.IGNORECASE)
        title = m.group(1).strip() if m else ""
        if not title:
            return None
        return RawCandidate(
            source=self.source,
            source_url=url,
            title=title,
            company="Talentics",
            location=None,
            description=_fallback_body_lines(body),
            source_text=f"[Hiring] {title} @ Talentics\nURL: {url}\n\n{_fallback_body_lines(body)}"[
                :8000
            ],
            discovered_at=_now_iso(),
            discovery_query="jobs.talentics.id",
        )


class SitemapDetailFetcher(BaseFetcher):
    """Shared pattern: sitemap (maybe nested index) -> filter detail URLs."""

    detail_prefix: str = ""

    async def fetch_listing(self) -> list[dict[str, str]]:
        sitemap_url = f"{self.config.base_url}{self.config.options['sitemap']}"
        urls = await self._sitemap_urls(sitemap_url, depth=0)
        out = []
        for url in urls:
            if self.detail_prefix and self.detail_prefix in url:
                slug = url.rstrip("/").rsplit("/", 1)[-1]
                out.append({"slug": slug, "url": url})
        return out

    async def _sitemap_urls(self, url: str, depth: int) -> list[str]:
        if depth > 2:
            return []
        body = await self.http_get(url)
        if not body:
            return []
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError:
            return []

        sitemap_tags = root.findall("sm:sitemap/sm:loc", NS)
        if sitemap_tags:  # sitemap index
            urls: list[str] = []
            for loc in sitemap_tags[:4]:
                urls.extend(await self._sitemap_urls((loc.text or "").strip(), depth + 1))
                if len(urls) > 5000:
                    break
            return urls
        return [(u.text or "").strip() for u in root.findall("sm:url/sm:loc", NS)]

    def _extract_jsonld(self, html: str) -> dict:
        for m in re.finditer(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL | re.IGNORECASE,
        ):
            try:
                data = json.loads(m.group(1).strip())
            except ValueError:
                continue
            graph = data.get("@graph") if isinstance(data, dict) else None
            candidates = graph if isinstance(graph, list) else [data]
            for node in candidates:
                if isinstance(node, dict) and node.get("@type") in ("JobPosting", "jobPosting"):
                    return node
        return {}

    async def fetch_detail(self, url: str) -> RawCandidate | None:
        body = await self.http_get(url)
        if not body:
            return None
        jd = self._extract_jsonld(body)
        title = (jd.get("title") or "").strip()
        if not title:
            m = re.search(r"<title>([^<]+)</title>", body, re.IGNORECASE)
            title = m.group(1).strip() if m else ""
        if not title:
            return None

        org = jd.get("hiringOrganization") or {}
        company = (org.get("name") if isinstance(org, dict) else str(org)) or self.config.name

        desc_raw = jd.get("description") or ""
        desc = strip_html(desc_raw) if desc_raw else _fallback_body_lines(body)

        return RawCandidate(
            source=self.source,
            source_url=url,
            title=title,
            company=str(company),
            location=self._extract_location(jd),
            description=desc[:4000],
            source_text=f"[Hiring] {title} @ {company}\nURL: {url}\n\n{desc}"[:8000],
            discovered_at=_now_iso(),
            published_at=jd.get("datePosted"),
            workplace_type="unknown",
            employment_type=str(jd.get("employmentType") or "unknown").lower().replace("_", "-"),
            discovery_query=f"sitemap:{self.config.options.get('sitemap', '')}",
        )

    def _extract_location(self, jd: dict) -> str | None:
        loc = jd.get("jobLocation")
        if isinstance(loc, dict):
            addr = loc.get("address") or {}
            if isinstance(addr, dict):
                return addr.get("addressLocality") or addr.get("addressRegion")
        return None


class DeallsFetcher(SitemapDetailFetcher):
    """Dealls: /loker/{slug} -> __NEXT_DATA__ dehydratedState (verified)."""

    source = "dealls"

    async def fetch_listing(self) -> list[dict[str, str]]:
        body = await self.http_get(f"{self.config.base_url}/sitemap-dynamic.xml")
        if not body:
            return []
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError:
            return []
        out = []
        for u in root.findall("sm:url/sm:loc", NS):
            url = (u.text or "").strip()
            if "/loker/" in url:
                slug = url.rstrip("/").rsplit("/", 1)[-1]
                out.append({"slug": slug, "url": url})
        return out

    async def fetch_detail(self, url: str) -> RawCandidate | None:
        body = await self.http_get(url)
        if not body:
            return None
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.DOTALL)
        if not m:
            return None
        try:
            nd = json.loads(m.group(1))
            queries = nd["props"]["pageProps"]["dehydratedState"]["queries"]
            job = next(
                (
                    q["state"]["data"]
                    for q in queries
                    if q.get("queryKey")
                    and "job" in str(q["queryKey"][0])
                    and isinstance(q.get("state", {}).get("data"), dict)
                ),
                {},
            )
        except (ValueError, KeyError, IndexError, TypeError):
            return None

        title = (job.get("title") or job.get("role") or "").strip()
        if not title:
            return None

        company = ""
        comp = job.get("company")
        if isinstance(comp, dict):
            company = comp.get("name") or ""
        elif isinstance(comp, str):
            company = comp

        loc = job.get("location") or {}
        location = None
        if isinstance(loc, dict):
            city = (loc.get("city") or {}).get("name")
            location = city or (loc.get("country") or {}).get("name")

        desc = strip_html(job.get("description") or "")
        return RawCandidate(
            source=self.source,
            source_url=url,
            title=title,
            company=company or "Dealls",
            location=location,
            description=desc[:4000],
            source_text=f"[Hiring] {title} @ {company or 'Dealls'}\nURL: {url}\n\n{desc}"[:8000],
            discovered_at=_now_iso(),
            published_at=job.get("publishedAt") or job.get("createdAt"),
            workplace_type="unknown",
            employment_type=str(
                job.get("employmentType") or job.get("workType") or "unknown"
            ).lower(),
            salary_raw=f"{job.get('salaryMin')}-{job.get('salaryMax')}"
            if job.get("salaryMin") and job.get("salaryMax")
            else None,
            discovery_query="dealls.com sitemap-dynamic /loker",
        )


class HiredTodayFetcher(SitemapDetailFetcher):
    """HiredToday: sitemap currently returns 404 pages (stale). Kept for
    monitoring; config can disable if still broken."""

    source = "hiredtoday"
    detail_prefix = "/en/jobs-detail/"


class TechInAsiaFetcher(SitemapDetailFetcher):
    """Tech in Asia: jobs sitemap (may 403 datacenter IPs; harmless if so)."""

    source = "techinasia"
    detail_prefix = "/jobs/"


class KitaLulusFetcher(SitemapDetailFetcher):
    """KitaLulus: nested sitemap -> /lowongan/detail/{slug}; detail pages are
    SSR HTML with title/h1 (no JSONLD JobPosting) -> parse via <title>."""

    source = "kitalulus"

    # How many job-detail sitemaps to walk per run. The index holds 148 of
    # them (~200 URLs each); reading only the first one capped this board at
    # a few hundred slugs and made "199 skipped" the normal outcome.
    SITEMAPS_PER_RUN = 4

    async def fetch_listing(self) -> list[dict[str, str]]:
        body = await self.http_get(f"{self.config.base_url}/sitemap.xml")
        if not body:
            return []
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError:
            return []
        job_sitemaps = [
            (u.text or "").strip()
            for u in root.findall("sm:sitemap/sm:loc", NS)
            if "sitemap-jobs" in (u.text or "")
        ]
        if not job_sitemaps:
            return []

        # Rotate through the index across runs so the whole board is covered
        # over time instead of re-reading the same first page every day.
        start = 0
        if self.db_repo:
            try:
                prev = await self.db_repo.get_fetcher_stats(self.source)
                start = int(prev.get("sitemap_index", 0)) % len(job_sitemaps)
            except Exception:
                start = 0

        ordered = job_sitemaps[start:] + job_sitemaps[:start]
        selected = ordered[: self.SITEMAPS_PER_RUN]

        urls: list[str] = []
        for sitemap in selected:
            urls.extend(await self._sitemap_urls(sitemap, depth=1))

        out = []
        seen_in_batch: set[str] = set()
        for url in urls:
            if "/lowongan/detail/" not in url:
                continue
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            if slug in seen_in_batch:
                continue
            seen_in_batch.add(slug)
            out.append({"slug": slug, "url": url})

        self.last_listing_cursor = (start + self.SITEMAPS_PER_RUN) % len(job_sitemaps)
        return out

    def listing_stats_extra(self) -> dict:
        return {"sitemap_index": getattr(self, "last_listing_cursor", 0)}

    async def fetch_detail(self, url: str) -> RawCandidate | None:
        body = await self.http_get(url)
        if not body:
            return None
        m = re.search(r"<title>([^<]+)</title>", body, re.IGNORECASE)
        raw_title = m.group(1).strip() if m else ""
        # "Info Lowongan {role} di {company} area {loc} | Kitalulus"
        tm = re.match(r"Info Lowongan (.+?) di (.+?) area ([^|]+?)\s*\|", raw_title)
        if tm:
            title, company, location = tm.group(1).strip(), tm.group(2).strip(), tm.group(3).strip()
        else:
            title = re.sub(r"\s*\|\s*Kitalulus\s*$", "", raw_title, flags=re.IGNORECASE)
            company, location = "KitaLulus", None
        if not title:
            return None
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.DOTALL)
        if h1 and len(h1.group(1)) < len(title):
            pass  # keep title from <title>, h1 is just the role
        desc = _fallback_body_lines(body, max_lines=30)
        return RawCandidate(
            source=self.source,
            source_url=url,
            title=title,
            company=company,
            location=location,
            description=desc[:4000],
            source_text=f"[Hiring] {title} @ {company}\nLocation: {location or 'N/A'}\n\n{desc}"[
                :8000
            ],
            discovered_at=_now_iso(),
            discovery_query="kitalulus.com sitemap-jobs",
        )


class LokerIdFetcher(BaseFetcher):
    """Loker.id: 403 for datacenter UA as of 2026-08-28. Kept as stub —
    will be re-enabled if protection relaxes."""

    source = "lokerid"

    async def fetch_listing(self) -> list[dict[str, str]]:
        path = self.config.options.get("listing_path", "/lowongan-kerja")
        body = await self.http_get(f"{self.config.base_url}{path}")
        if not body:
            return []
        hrefs = re.findall(r'href="(https?://www\.loker\.id/[a-z0-9-]+\.html)"', body)
        seen: set[str] = set()
        out = []
        for url in hrefs:
            if url in seen:
                continue
            seen.add(url)
            slug = url.rstrip("/").rsplit("/", 1)[-1].replace(".html", "")
            out.append({"slug": slug, "url": url})
        return out

    async def fetch_detail(self, url: str) -> RawCandidate | None:
        body = await self.http_get(url)
        if not body:
            return None
        m = re.search(r"<title>([^<]+)</title>", body, re.IGNORECASE)
        title = m.group(1).strip() if m else ""
        title = re.sub(r"\s*[-|]\s*Loker\.id\s*$", "", title, flags=re.IGNORECASE)
        if not title:
            return None
        desc = _fallback_body_lines(body)
        return RawCandidate(
            source=self.source,
            source_url=url,
            title=title,
            company="Loker.id",
            location=None,
            description=desc[:4000],
            source_text=f"[Hiring] {title}\nURL: {url}\n\n{desc}"[:8000],
            discovered_at=_now_iso(),
            discovery_query="loker.id lowongan-kerja",
        )
