#!/usr/bin/env python3
"""
SEVIMA Career Page Fetcher for AI JOB FILTER.

Scrapes https://career.sevima.com/jobs (robots.txt permits), extracts each
posting into the normalized candidate JSON format, and optionally feeds it
into ingest_web_candidate.py / the pipeline.

Strategy:
  1. GET /jobs                -> collect posting slugs (cheap, httpx/urllib)
  2. Skip already-seen slugs   (state file: sevima_seen.json)
  3. For new slugs: Playwright headless renders the Livewire detail page
     -> full description text
  4. Emit candidate JSON matching fixtures format
  5. Optionally invoke ingest_web_candidate.py --execute per candidate

Usage:
    python sevima_fetcher.py --dry-run        # fetch + emit candidates only
    python sevim_fetcher.py --execute         # also insert into DB via pipeline
    python sevima_fetcher.py --limit 3        # cap new postings processed

Etiquette:
    - robots.txt of career.sevima.com allows crawling (no Disallow).
    - Polite delay between requests (default 3s).
    - Only public job pages are accessed; no auth bypass.
"""

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

BASE_URL = "https://career.sevima.com"
LIST_URL = f"{BASE_URL}/jobs"
STATE_FILE = Path(__file__).parent / "sevima_seen.json"
DELAY_SECONDS = 3  # polite delay between page fetches

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "(AI-JOB-FILTER personal job hunter; contact via GitHub)"
)


def http_get(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_slugs(list_html: str) -> list[dict]:
    """Extract job slugs + titles from the /jobs listing page."""
    # Pattern: href="https://career.sevima.com/jobs/{slug}" — exclude /apply
    links = sorted(set(re.findall(r'href="(https://career\.sevima\.com/jobs/[a-z0-9-]+)"', list_html)))
    out = []
    for url in links:
        slug = url.rsplit("/", 1)[-1]
        if slug == "apply" or slug.endswith("/apply"):
            continue
        out.append({"slug": slug, "url": url})
    return out


def load_state() -> set:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except json.JSONDecodeError:
            pass
    return set()


def save_state(seen: set) -> None:
    STATE_FILE.write_text(json.dumps(sorted(seen), indent=1))


async def render_detail(url: str) -> str | None:
    """Render a job detail page with headless Chromium; returns description text."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=USER_AGENT)
        try:
            await page.goto(url, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3500)  # let Livewire hydrate
            text = await page.evaluate("() => document.body.innerText")
            return text
        finally:
            await browser.close()


def parse_detail(text: str) -> dict:
    """Parse rendered detail text into structured fields."""
    out = {
        "employment_type": "unknown",
        "location": None,
        "salary_raw": None,
        "description": "",
    }

    m = re.search(r"(Fulltime|Part[- ]?time|Contract|Internship|Freelance)", text, re.I)
    if m:
        t = m.group(1).lower().replace(" ", "-")
        out["employment_type"] = {"fulltime": "full-time", "part-time": "part-time"}.get(t, t)

    salary = re.search(r"Rp\s?[\d.,]+\s*-\s*Rps?\s?[\d.,]+", text)

    if salary:
        out["salary_raw"] = salary.group(0).strip()

    # Description: from "Deskripsi Pekerjaan" until "Lamar Pekerjaan"/"Waspada"
    start = text.find("Deskripsi Pekerjaan")
    end_candidates = [i for i in (text.find("Lamar Pekerjaan"), text.find("Waspada Penipuan")) if i > start]
    if start >= 0:
        end = min(end_candidates) if end_candidates else start + 6000
        desc_block = text[start:end]
        lines = [
            line.strip()
            for line in desc_block.splitlines()
            if line.strip()
            and not line.strip().startswith(("await ", "const ", "fetch(", "if (!", "})()", "{"))
            and "copyToClipboard" not in line
        ]
        # drop header line & meta lines already extracted
        skip = {"Deskripsi Pekerjaan", "Lamar Pekerjaan"}
        cleaned = []
        for line in lines:
            if line in skip:
                continue
            if out["employment_type"] != "unknown" and line.lower() == out["employment_type"].replace("-", ""):
                continue
            if out["location"] is None and re.match(r"^[A-Z][a-zA-Z]+, Jawa", line):
                out["location"] = line
                continue
            if out["salary_raw"] and line.replace(" ", "").startswith("Rp"):
                continue
            cleaned.append(line)
        out["description"] = "\n".join(cleaned)

    return out


def build_candidate(slug_data: dict, detail: dict, title: str) -> dict:
    now = datetime.now(UTC).isoformat()
    desc = detail.get("description", "")
    source_text = (
        f"[Hiring] {title} @ SEVIMA\n"
        f"Location: {detail.get('location') or 'Indonesia'}\n"
        f"Type: {detail.get('employment_type')}\n"
        f"Salary: {detail.get('salary_raw') or 'unspecified'}\n\n"
        f"{desc}"
    )
    return {
        "source": "career_sevima",
        "source_url": slug_data["url"],
        "title": title,
        "company": "SEVIMA",
        "published_at": now,
        "discovered_at": now,
        "location": detail.get("location"),
        "workplace_type": "on-site",
        "employment_type": detail.get("employment_type", "unknown"),
        "salary_raw": detail.get("salary_raw") or "unspecified",
        "description": desc,
        "source_text": source_text,
        "discovery_query": "site:career.sevima.com security engineer linux",
    }


async def main():
    parser = argparse.ArgumentParser(description="SEVIMA career page fetcher")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Emit candidate JSONs without ingesting (default)")
    parser.add_argument("--execute", action="store_false", dest="dry_run",
                        help="Feed candidates into ingest_web_candidate.py --execute")
    parser.add_argument("--limit", type=int, default=0, help="Max new postings to process (0=all)")
    args = parser.parse_args()

    print("[1] Fetch listing page...")
    list_html = http_get(LIST_URL)
    jobs = extract_slugs(list_html)
    print(f"    {len(jobs)} total postings on career.sevima.com")

    seen = load_state()
    fresh = [j for j in jobs if j["slug"] not in seen]
    print(f"[2] {len(fresh)} new postings (vs state file)")

    if args.limit > 0:
        fresh = fresh[: args.limit]
        print(f"    limited to {len(fresh)}")

    results = []
    for idx, job in enumerate(fresh, 1):
        slug = job["slug"]
        title = slug.replace("-", " ").title()
        print(f"\n[{idx}/{len(fresh)}] {slug}")
        try:
            detail_html = await render_detail(job["url"])
            if not detail_html:
                print("    ! render failed, skipping")
                continue
            detail = parse_detail(detail_html)

            cand = build_candidate(job, detail, title)

            out_file = Path(f"/tmp/sevima_{slug}.json")
            out_file.write_text(json.dumps(cand, indent=2, ensure_ascii=False))
            print(f"    → candidate written: {out_file}")

            if not args.dry_run:
                cmd = [
                    sys.executable,
                    str(Path(__file__).parent / "ingest_web_candidate.py"),
                    "--file", str(out_file),
                    "--execute", "--json-output",
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                tail = proc.stdout.strip().splitlines()[-1:] or ["(no output)"]
                print(f"    → ingest: {tail[0][:120]}")

            results.append({"slug": slug, "ok": True})
            seen.add(slug)

            if idx < len(fresh):
                time.sleep(DELAY_SECONDS)

        except Exception as e:
            print(f"    ! error: {e}")
            results.append({"slug": slug, "ok": False, "error": str(e)})
            time.sleep(DELAY_SECONDS)

    save_state(seen)
    ok_count = sum(1 for r in results if r["ok"])
    print(f"\n[DONE] {ok_count}/{len(results)} fetched successfully")


if __name__ == "__main__":
    asyncio.run(main())
