"""Tests for web_fetcher base + registry + IT relevance filter. No network."""

import pytest

from ai_job_filter.web_fetcher.base import (
    FILTERED_PREFIX,
    IT_FILTER_VERSION,
    BaseFetcher,
    FetcherConfig,
    RawCandidate,
    strip_html,
)
from ai_job_filter.web_fetcher.registry import FETCHER_CLASSES, build_fetchers, load_fetcher_configs
from ai_job_filter.web_fetcher.relevance import category_hint, classify_reason, is_it_job


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
        # Non-IT postings must not reach the DB by default.
        assert cfg.it_only is True
        assert cfg.attempt_multiplier == 3


class TestRegistry:
    def test_loads_default_yaml(self):
        configs = load_fetcher_configs()
        names = [c.name for c in configs]
        # 4 boards enabled as of 2026-09-12; the rest are disabled with a
        # documented reason in config/web_fetchers.yaml (JS SPA, 404, timeout).
        assert "dealls" in names
        assert "kitalulus" in names
        assert "techinasia" in names
        assert "talentics" in names
        assert len(names) >= 4

    def test_no_jobstreet_linkedin(self):
        configs = load_fetcher_configs()
        names = [c.name for c in configs]
        assert "jobstreet" not in names
        assert "linkedin" not in names

    def test_disabled_boards_excluded(self):
        configs = load_fetcher_configs()
        names = [c.name for c in configs]
        # Explicitly disabled in config (bot protection / stale sitemap /
        # JS-only listing pages that return no parseable links).
        for disabled in ("lokerid", "hiredtoday", "glints", "kalibrr", "karircom", "topkarir"):
            assert disabled not in names, f"{disabled} should be disabled"

    def test_it_only_defaults_on_for_whole_site_boards(self):
        configs = {c.name: c for c in load_fetcher_configs()}
        # These boards expose whole-site sitemaps, so the filter must stay on.
        assert configs["dealls"].it_only is True
        assert configs["kitalulus"].it_only is True

    def test_attempt_multiplier_parsed(self):
        configs = {c.name: c for c in load_fetcher_configs()}
        assert configs["dealls"].attempt_multiplier >= 3

    def test_build_fetchers(self, in_memory_db):
        fetchers = build_fetchers(db_repo=in_memory_db)
        assert len(fetchers) >= 4
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

    def test_it_only_can_be_disabled_per_board(self, tmp_path):
        cfg_file = tmp_path / "fetchers.yaml"
        cfg_file.write_text(
            "boards:\n"
            "  - name: dealls\n"
            "    base_url: https://x\n"
            "    it_only: false\n"
            "    attempt_multiplier: 7\n"
        )
        configs = load_fetcher_configs(cfg_file)
        assert configs[0].it_only is False
        assert configs[0].attempt_multiplier == 7


class TestITRelevance:
    """The classifier that keeps non-IT postings out of the jobs table."""

    @pytest.mark.parametrize(
        "title",
        [
            "DevOps Engineer",
            "DevSecOps Engineer",
            "Senior Site Reliability Engineer",
            "IT Support Staff",
            "IT Support Level 1",
            "IT Operation Support",
            "IT-Operation Support",
            "Staff IT",
            "Staf ICT",
            "IT Auditor",
            "IT Project Manager",
            "IT Business Analyst",
            "Admin IT (Intern)",
            "L1 Support",
            "L1 Network/Security",
            "Network Security Engineer",
            "Linux Administrator",
            "Junior SOC Analyst",
            "Cyber Security Specialist",
            "Cybersecurity",
            "Penetration Tester",
            "QA Automation Engineer",
            "Quality Assurance Intern",
            "Backend Engineer",
            "Full Stack Developer",
            "iOS Developer",
            "Data Engineer",
            "Database Administrator",
            "Cloud Architect",
            "SAP Functional Consultant",
            "ERP Consultant",
            "System Implementer",
            "Technical Support Engineer",
            "Helpdesk Technician",
            "NOC Analyst",
            "Infrastructure Engineer",
            "Monitoring Engineer",
            "Product QA",
        ],
    )
    def test_accepts_it_titles(self, title):
        assert is_it_job(title, ""), f"should accept: {title}"

    @pytest.mark.parametrize(
        "title",
        [
            "Housekeeping Staff",
            "Personal Trainer",
            "Medical Representative",
            "Account Executive",
            "Customer Service",
            "Customer Support Specialist",
            "Sales Support Intern",
            "Sales Executive (Digital & Web Services)",
            "Talent Acquisition Specialist",
            "Admin Online Shop",
            "Admin Ecommerce Support Staff",
            "Admin Data Entry",
            "Accounting Staff",
            "Tax Analyst",
            "Graphic Designer",
            "Content Writer",
            "Site Engineer (SPV Teknik)",
            "Project Engineer (Mandarin Officer)",
            "Mechanical Engineer",
            "Industrial Engineer",
            "Footwear Developer",
            "Solar Technician",
            "Quality Control Supervisor",
            "Business Development Specialist",
            "Security Guard",
            "Event Manager",
            "Barista",
            "Dosen",
        ],
    )
    def test_rejects_non_it_titles(self, title):
        assert not is_it_job(title, ""), f"should reject: {title}"

    def test_vague_title_needs_body_signals(self):
        # "Staff" alone tells us nothing, so the body decides.
        assert not is_it_job("Staff", "Kami mencari kandidat berpengalaman.")
        assert is_it_job(
            "Staff",
            "Mengelola server Linux, Docker, dan monitoring Prometheus/Grafana.",
        )

    def test_it_title_beats_noisy_body(self):
        # A short body must not veto an unambiguous IT title.
        assert is_it_job("Cybersecurity", "Apply now")

    def test_non_it_title_beats_it_body(self):
        # A recruiter posting mentions tech words but is not an IT role.
        assert not is_it_job("Technical Recruiter", "Docker Kubernetes AWS Python Linux")

    def test_case_sensitive_it_token(self):
        # Uppercase IT is the department; the lowercase English pronoun is not.
        assert is_it_job("IT Purchasing Officer", "")
        assert not is_it_job("it is a great place", "")

    def test_none_and_empty(self):
        assert not is_it_job(None, None)
        assert not is_it_job("", "")

    def test_classify_reason_is_descriptive(self):
        assert classify_reason("DevOps Engineer", "") == "IT title"
        assert classify_reason("Housekeeping Staff", "") == "non-IT title"
        assert "body signals" in classify_reason("Staff", "no signals here")

    def test_category_hint_reads_dead_config_keys(self):
        hint = category_hint(
            {
                "keywords": ["linux", "devops"],
                "category_path": "/en/jobs?category=information-technology",
                "specialization": "teknologi-informasi",
            }
        )
        assert "linux" in hint
        assert "devops" in hint
        assert "information" in hint
        # Separators are normalised so "teknologi-informasi" becomes two words.
        assert "teknologi" in hint

    def test_category_hint_empty(self):
        assert category_hint(None) == ""
        assert category_hint({}) == ""


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

    def _cfg(self, **kw):
        # it_only=False keeps these tests focused on the fetch/state loop.
        kw.setdefault("it_only", False)
        return FetcherConfig(name="dummy", base_url="https://x", **kw)

    @pytest.mark.asyncio
    async def test_run_dry_run_no_state_write(self, in_memory_db):
        f = self.DummyFetcher(self._cfg(), in_memory_db)
        stats = await f.run(dry_run=True)
        assert stats["found"] == 3
        assert stats["fetched"] == 2  # slug a fetched once, b failed (None)
        assert stats["new"] == 1
        assert stats["filtered"] == 0
        # state untouched in dry-run
        slugs, _ = await in_memory_db.get_fetcher_state("dummy")
        assert slugs == []

    @pytest.mark.asyncio
    async def test_run_execute_persists_state(self, in_memory_db):
        f = self.DummyFetcher(self._cfg(), in_memory_db)
        stats = await f.run(dry_run=False)
        assert stats["new"] == 1
        slugs, _ = await in_memory_db.get_fetcher_state("dummy")
        assert "a" in slugs  # only successful detail
        assert "b" not in slugs  # fetch_detail returned None

    @pytest.mark.asyncio
    async def test_run_skips_seen(self, in_memory_db):
        f = self.DummyFetcher(self._cfg(), in_memory_db)
        await f.run(dry_run=False)
        # Second run: slug a is seen, so only b attempted (and fails)
        stats2 = await f.run(dry_run=False)
        assert stats2["skipped"] >= 1
        assert stats2["fetched"] <= 1


class TestITFilteringInRun:
    """The filter runs inside BaseFetcher.run, before anything reaches the DB."""

    class MixedFetcher(BaseFetcher):
        source = "mixed"

        async def fetch_listing(self):
            return [
                {"slug": "it1", "url": "https://x/it1"},
                {"slug": "hr1", "url": "https://x/hr1"},
                {"slug": "it2", "url": "https://x/it2"},
            ]

        async def fetch_detail(self, url):
            slug = url.rsplit("/", 1)[-1]
            title = {
                "it1": "DevOps Engineer",
                "hr1": "Housekeeping Staff",
                "it2": "Network Administrator",
            }[slug]
            return RawCandidate(
                source="mixed",
                source_url=url,
                title=title,
                company="Co",
                location=None,
                description="desc",
                source_text=f"[Hiring] {title} @ Co",
                discovered_at="2026-08-28T00:00:00+00:00",
            )

    @pytest.mark.asyncio
    async def test_non_it_candidate_is_filtered(self, in_memory_db):
        f = self.MixedFetcher(FetcherConfig(name="mixed", base_url="https://x"), in_memory_db)
        stats = await f.run(dry_run=False)
        assert stats["fetched"] == 3
        assert stats["filtered"] == 1
        assert stats["new"] == 2
        titles = [c.title for c in f.last_candidates]
        assert "Housekeeping Staff" not in titles
        assert "DevOps Engineer" in titles

    @pytest.mark.asyncio
    async def test_filtered_slug_is_not_refetched(self, in_memory_db):
        f = self.MixedFetcher(FetcherConfig(name="mixed", base_url="https://x"), in_memory_db)
        await f.run(dry_run=False)
        stats2 = await f.run(dry_run=False)
        # Everything already handled: nothing fetched again.
        assert stats2["fetched"] == 0
        assert stats2["filtered"] == 0
        assert stats2["skipped"] == 3

    @pytest.mark.asyncio
    async def test_filtered_slug_stored_with_version_marker(self, in_memory_db):
        f = self.MixedFetcher(FetcherConfig(name="mixed", base_url="https://x"), in_memory_db)
        await f.run(dry_run=False)
        slugs, _ = await in_memory_db.get_fetcher_state("mixed")
        markers = [s for s in slugs if s.startswith(FILTERED_PREFIX)]
        assert len(markers) == 1
        assert IT_FILTER_VERSION in markers[0]
        # The raw rejected slug must NOT be stored, or a classifier bump
        # could never re-evaluate it.
        assert "hr1" not in slugs

    @pytest.mark.asyncio
    async def test_old_version_markers_are_pruned(self, in_memory_db):
        f = self.MixedFetcher(FetcherConfig(name="mixed", base_url="https://x"), in_memory_db)
        await in_memory_db.save_fetcher_state("mixed", [f"{FILTERED_PREFIX}it-v0:hr1"], "ok", {})
        await f.run(dry_run=False)
        slugs, _ = await in_memory_db.get_fetcher_state("mixed")
        # The stale marker is gone, so hr1 was re-evaluated and re-marked.
        assert f"{FILTERED_PREFIX}it-v0:hr1" not in slugs

    @pytest.mark.asyncio
    async def test_it_only_false_disables_filtering(self, in_memory_db):
        f = self.MixedFetcher(
            FetcherConfig(name="mixed", base_url="https://x", it_only=False), in_memory_db
        )
        stats = await f.run(dry_run=False)
        assert stats["filtered"] == 0
        assert stats["new"] == 3

    @pytest.mark.asyncio
    async def test_max_items_counts_accepted_not_fetched(self, in_memory_db):
        f = self.MixedFetcher(FetcherConfig(name="mixed", base_url="https://x"), in_memory_db)
        stats = await f.run(dry_run=False, limit=1)
        # limit=1 caps ACCEPTED candidates; the non-IT one is still examined.
        assert stats["new"] == 1
        assert stats["fetched"] == 1
