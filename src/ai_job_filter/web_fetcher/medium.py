"""Medium-tier fetchers (PRD F-WEB-5): Glints, Kalibrr, Karir.com, TopKarir.

Strategies (per feasibility study):
- Glints: HTML listing -> detail pages, parse __NEXT_DATA__/JSON-LD.
  robots.txt Disallows /api/* so we only fetch public HTML.
- Kalibrr: search page HTML only (detail pages may 403 datacenter IPs).
- Karir.com / TopKarir: simple HTML listing + detail JSON-LD.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from xml.etree import ElementTree

from .base import BaseFetcher, RawCandidate, strip_html
from .easy import NS, SitemapDetailFetcher


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class GlintsFetcher(SitemapDetailFetcher):
    """Glints: sitemap + detail JSON-LD/__NEXT_DATA__ (no /api/* per robots)."""

    source = "glints"
    detail_prefix = "/opportunities/jobs/"

    async def fetch_detail(self, url: str) -> RawCandidate | None:
        body = await self.http_get(url)
        if not body:
            return None

        jd = self._extract_jsonld(body)
        title = (jd.get("title") or "").strip()
        company = ""
        desc = ""

        if not title:
            # __NEXT_DATA__ fallback
            m = re.search(
                r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
                body,
                re.DOTALL,
            )
            if m:
                try:
                    nd = json.loads(m.group(1))
                    props = nd.get("props", {}).get("pageProps", {})
                    job = props.get("jobDetail") or props.get("opportunity") or {}
                    title = (job.get("title") or job.get("name") or "").strip()
                    company = (job.get("company") or {}).get("name", "") if isinstance(job.get("company"), dict) else ""
                    desc = strip_html(job.get("description") or "")
                except ValueError:
                    pass

        if not title:
            m = re.search(r"<title>([^<]+)</title>", body, re.IGNORECASE)
            title = m.group(1).strip() if m else ""
        if not title:
            return None

        org = jd.get("hiringOrganization") or {}
        if not company:
            company = org.get("name") if isinstance(org, dict) else (str(org) or "Glints")

        if not desc:
            desc_raw = jd.get("description") or ""
            desc = strip_html(desc_raw) if desc_raw else self._fallback_description(body)

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
            employment_type=str(jd.get("employmentType") or "unknown").lower(),
            discovery_query="glints.com lowongan teknologi",
        )

    def _extract_location(self, jd: dict) -> str | None:
        loc = jd.get("jobLocation")
        if isinstance(loc, dict):
            addr = loc.get("address") or {}
            return addr.get("addressLocality") or addr.get("addressRegion")
        return None


class KalibrrFetcher(BaseFetcher):
    """Kalibrr: search page HTML only — detail pages often 403 datacenter IPs.

    The search listing already contains title/company/location snippets, so we
    build candidates from the listing itself (PRD: detail = skip).
    """

    source = "kalibrr"

    async def fetch_listing(self) -> list[dict[str, str]]:
        path = self.config.options.get("search_path", "/c/teknologi-dan-startup/jobs")
        body = await self.http_get(f"{self.config.base_url}{path}")
        if not body:
            return []
        hrefs = re.findall(r'href="(/job-desks/[^"]+)"', body)
        seen: set[str] = set()
        out = []
        for href in hrefs:
            if href in seen:
                continue
            seen.add(href)
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            out.append({"slug": slug, "url": f"{self.config.base_url}{href}"})
        return out

    async def fetch_detail(self, url: str) -> RawCandidate | None:
        # Try detail; on failure fall back to listing-context data is not
        # available here, so return None (candidate skipped).
        body = await self.http_get(url)
        if not body:
            return None
        title_m = re.search(r"<title>([^<]+)</title>", body, re.IGNORECASE)
        title = title_m.group(1).strip() if title_m else ""
        title = re.sub(r"\s*[-|]\s*Kalibrr.*$", "", title, flags=re.IGNORECASE)
        if not title:
            return None
        text = strip_html(body)
        lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 40]
        desc = "\n".join(lines[:25])
        return RawCandidate(
            source=self.source,
            source_url=url,
            title=title,
            company="Kalibrr",
            location=None,
            description=desc[:4000],
            source_text=f"[Hiring] {title}\nURL: {url}\n\n{desc}"[:8000],
            discovered_at=_now_iso(),
            discovery_query="kalibrr.id teknologi-dan-startup",
        )


class KarirComFetcher(SitemapDetailFetcher):
    source = "karircom"
    detail_prefix = "/opportunities/"

    async def fetch_listing(self) -> list[dict[str, str]]:
        # robots.txt Crawl-delay: 1 -> keep delay >= 2s (base handles jitter)
        self.config.delay_seconds = max(self.config.delay_seconds, 2.0)
        path = self.config.options.get("search_path", "/search?q=teknologi")
        body = await self.http_get(f"{self.config.base_url}{path}")
        if not body:
            return []
        hrefs = re.findall(r'href="(/opportunities/[^"]+)"', body)
        seen: set[str] = set()
        out = []
        for href in hrefs:
            if href in seen:
                continue
            seen.add(href)
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            out.append({"slug": slug, "url": f"{self.config.base_url}{href}"})
        return out


class TopKarirFetcher(BaseFetcher):
    source = "topkarir"

    async def fetch_listing(self) -> list[dict[str, str]]:
        path = self.config.options.get("search_path", "/lowongan")
        body = await self.http_get(f"{self.config.base_url}{path}")
        if not body:
            return []
        hrefs = re.findall(r'href="(/lowongan/[a-z0-9-]+)"', body)
        seen: set[str] = set()
        out = []
        for href in hrefs:
            if href in seen:
                continue
            seen.add(href)
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            out.append({"slug": slug, "url": f"{self.config.base_url}{href}"})
        return out

    async def fetch_detail(self, url: str) -> RawCandidate | None:
        body = await self.http_get(url)
        if not body:
            return None
        title_m = re.search(r"<title>([^<]+)</title>", body, re.IGNORECASE)
        title = title_m.group(1).strip() if title_m else ""
        title = re.sub(r"\s*[-|]\s*TopKarir.*$", "", title, flags=re.IGNORECASE)
        if not title:
            return None
        text = strip_html(body)
        lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 40]
        desc = "\n".join(lines[:25])
        return RawCandidate(
            source=self.source,
            source_url=url,
            title=title,
            company="TopKarir",
            location=None,
            description=desc[:4000],
            source_text=f"[Hiring] {title}\nURL: {url}\n\n{desc}"[:8000],
            discovered_at=_now_iso(),
            discovery_query="topkarir.com lowongan",
        )


def parse_sitemap_urls(xml_body: str) -> list[str]:
    """Utility: extract <loc> URLs from a sitemap XML string."""
    try:
        root = ElementTree.fromstring(xml_body)
    except ElementTree.ParseError:
        return []
    return [(u.text or "").strip() for u in root.findall("sm:url/sm:loc", NS)]
