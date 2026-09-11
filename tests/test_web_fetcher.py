"""Tests for web_fetcher base + registry (PRD F-WEB-1/2/3). No network."""

import pytest

from ai_job_filter.web_fetcher.base import BaseFetcher, FetcherConfig, RawCandidate, strip_html
from ai_job_filter.web_fetcher.registry import FETCHER_CLASSES, build_fetchers, load_fetcher_configs


class TestStripHtml:
    def test_strips_tags(self):
        result = strip_html("<p>Hello <b>World</b></p>")
        assert "Hello" in result and "World" in result
        assert "<" not in result and ">" not in result

    def test_strips_script_style(self):
        html = "<div>Job</div><script>alert(1)</script><style>.x{}</style>"
        result = strip_html(html)
        assert "alert" not in result
        assert ".x{}" not in result
        assert "Job" in result

    def test_decodes_entities(self):
        assert "R&D" in strip_html("<p>R&amp;D</p>")

    def test_empty(self):
        assert strip_html("") == ""
        assert strip_html(None) == ""


class TestStripHtmlNone:
    def test_none_input(self):
        assert strip_html(None) == ""


class TestFetcherConfig:
    def test_defaults(self):
        cfg = FetcherConfig(name="x", base_url="https://example.com")
        assert cfg.enabled is True
        assert cfg.interval_hours == 24
        assert cfg.delay_seconds == 3.0
        assert cfg.max_items == 20
        assert cfg.use_playwright is False
        assert cfg.options == {}


class TestRegistry:
    def test_loads_default_yaml(self):
        configs = load_fetcher_configs()
        names = [c.name for c in configs]
        # 8 boards enabled (hiredtoday + lokerid disabled: 403/404 as of 2026-08-28)
        assert "talentics" in names
        assert "dealls" in names
        assert "glints" in names
        assert "karircom" in names
        assert len(names) >= 8

    def test_no_jobstreet_linkedin(self):
        configs = load_fetcher_configs()
        names = [c.name for c in configs]
        assert "jobstreet" not in names
        assert "linkedin" not in names

    def test_disabled_boards_excluded(self):
        configs = load_fetcher_configs()
        names = [c.name for c in configs]
        # Explicitly disabled in config (bot protection / stale sitemap)
        assert "lokerid" not in names
        assert "hiredtoday" not in names

    def test_build_fetchers(self, in_memory_db):
        fetchers = build_fetchers(db_repo=in_memory_db)
        assert len(fetchers) >= 8
        for f in fetchers:
            assert isinstance(f, BaseFetcher)
            assert f.db_repo is in_memory_db

    def test_unknown_board_skipped(self, tmp_path):
        cfg_file = tmp_path / "fetchers.yaml"
        cfg_file.write_text("boards:\n  - name: unknownboard\n    base_url: https://x\n")
        configs = load_fetcher_configs(cfg_file)
        assert configs == []

    def test_all_registry_names_valid(self):
        # Every class in FETCHER_CLASSES subclasses BaseFetcher
        for name, cls in FETCHER_CLASSES.items():
            assert issubclass(cls, BaseFetcher), f"{name} not a BaseFetcher"


class TestBaseFetcherRun:
    class DummyFetcher(BaseFetcher):
        source = "dummy"

        async def fetch_listing(self):
            return [
                {"slug": "a", "url": "https://x/a"},
                {"slug": "b", "url": "https://x/b"},
                {"slug": "a", "url": "https://x/a"},  # dup slug
            ]

        async def fetch_detail(self, url):
            if "a" in url:
                return RawCandidate(
                    source="dummy",
                    source_url=url,
                    title="Job A",
                    company="Co",
                    location=None,
                    description="d",
                    source_text="[Hiring] Job A @ Co\n\n" + "detail text",
                    discovered_at="2026-08-28T00:00:00+00:00",
                )
            return None

    @pytest.mark.asyncio
    async def test_run_dry_run_no_state_write(self, in_memory_db):
        f = self.DummyFetcher(FetcherConfig(name="dummy", base_url="https://x"), in_memory_db)
        stats = await f.run(dry_run=True)
        assert stats["found"] == 3
        assert stats["fetched"] == 2  # slug a fetched once, b failed (None)
        assert stats["new"] == 1
        # state untouched in dry-run
        slugs, _ = await in_memory_db.get_fetcher_state("dummy")
        assert slugs == []

    @pytest.mark.asyncio
    async def test_run_execute_persists_state(self, in_memory_db):
        f = self.DummyFetcher(FetcherConfig(name="dummy", base_url="https://x"), in_memory_db)
        stats = await f.run(dry_run=False)
        assert stats["new"] == 1
        slugs, _ = await in_memory_db.get_fetcher_state("dummy")
        assert "a" in slugs  # only successful detail
        assert "b" not in slugs  # fetch_detail returned None

    @pytest.mark.asyncio
    async def test_run_skips_seen(self, in_memory_db):
        f = self.DummyFetcher(FetcherConfig(name="dummy", base_url="https://x"), in_memory_db)
        await f.run(dry_run=False)
        # Second run: slug a is seen, so only b attempted (and fails)
        stats2 = await f.run(dry_run=False)
        assert stats2["skipped"] >= 1
        assert stats2["fetched"] <= 1
