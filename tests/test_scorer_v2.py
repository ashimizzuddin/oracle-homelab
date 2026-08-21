"""Tests for Scoring V2 implementation.

Tests cover:
- Career trajectory: fuzzy title match + summary fallback
- Technical skills: min(25, matched * 6) formula
- Salary practical factor: salary_min OR salary_max
- Regression: hard fails, false positives, real-data fixtures
"""

import pytest

from ai_job_filter.models.candidate import CandidateProfile
from ai_job_filter.models.enums import Classification
from ai_job_filter.models.job import JobExtractionResult
from ai_job_filter.processing.scorer import Scorer


@pytest.fixture
def candidate_profile():
    return CandidateProfile(
        professional_years=0,
        certification="RHCSA",
        strong_technical_areas=[
            "Linux",
            "System Administration",
            "RHEL",
            "Networking",
            "VMware",
            "Virtualization",
            "Kali Linux",
            "Bash",
        ],
        career_direction=[
            "Cybersecurity",
            "Infrastructure Security",
            "SOC",
            "Penetration Testing",
            "Bug Bounty",
            "Security Engineering",
        ],
        target_experience=["entry_level", "junior", "fresh_graduate", "0-1 years"],
        target_roles=[
            "Junior System Administrator",
            "Linux Administrator",
            "IT Infrastructure",
            "IT Support",
            "NOC",
            "Junior SOC Analyst",
            "Junior Security Analyst",
            "Network Administrator",
            "Junior DevOps",
            "Technical Support",
        ],
    )


def _make_job(**kwargs):
    """Helper to build a JobExtractionResult with sensible defaults."""
    defaults = {
        "is_job_posting": True,
        "title": "Test Job",
        "skills_required": [],
        "skills_preferred": [],
        "requirements_raw": [],
    }
    defaults.update(kwargs)
    return JobExtractionResult(**defaults)


# ============================================================
# Career Trajectory Tests
# ============================================================


class TestCareerTrajectory:
    def test_exact_title_match(self, candidate_profile):
        """'SOC Analyst' contains exact substring 'soc' — caught by V1 path."""
        scorer = Scorer(candidate_profile)
        job = _make_job(title="SOC Analyst")
        score_val, classification, _ = scorer.score_job(job)
        # SOC Analyst: role ~30 + exp 20 + career 15 = ~65
        assert score_val >= 55
        assert classification in (Classification.REVIEW, Classification.APPLY)

    def test_fuzzy_title_match_network_security_engineer(self, candidate_profile):
        """'Network Security Engineer' matches 'Security Engineering' via
        token_set_ratio=80, above threshold 75."""
        scorer = Scorer(candidate_profile)
        job = _make_job(title="Network Security Engineer")
        score_val, _, _ = scorer.score_job(job)
        # Role ~20 + exp 20 + career 15 = 55
        assert score_val >= 55

    def test_exact_summary_match(self, candidate_profile):
        """Career term found in summary/requirements via V1 substring fallback."""
        scorer = Scorer(candidate_profile)
        job = _make_job(
            title="IT Specialist",
            requirements_raw=["Join our cybersecurity team"],
        )
        score_val, _, _ = scorer.score_job(job)
        # Career should contribute 15 points
        # IT Specialist role + exp 20 + career 15
        assert score_val >= 55

    def test_no_match(self, candidate_profile):
        """'Admin Project' has no career match — title tsr=38, no summary."""
        scorer = Scorer(candidate_profile)
        job = _make_job(title="Admin Project")
        _, classification, _ = scorer.score_job(job)
        assert classification == Classification.IGNORE

    def test_false_positive_security_guard(self, candidate_profile):
        """'Security Guard' has token_set_ratio=73 with 'Security Engineering',
        which is below threshold 75. Must NOT get career points."""
        scorer = Scorer(candidate_profile)
        job = _make_job(title="Security Guard")
        _, classification, _ = scorer.score_job(job)
        # Without career points, max is ~role + exp = ~41 + 20 = ~41
        assert classification == Classification.IGNORE

    def test_false_positive_office_security(self, candidate_profile):
        """'Office Security' has token_set_ratio=71 with 'Cybersecurity',
        which is below threshold 75. Must NOT get career points."""
        scorer = Scorer(candidate_profile)
        job = _make_job(title="Office Security")
        _, classification, _ = scorer.score_job(job)
        assert classification == Classification.IGNORE


# ============================================================
# Technical Skill Matching Tests
# ============================================================


class TestSkillMatching:
    def test_zero_matches(self, candidate_profile):
        """No profile skills match any job skill — skill_points = 0."""
        scorer = Scorer(candidate_profile)
        job = _make_job(
            title="L1 Support",
            skills_required=["Helpdesk", "Communication", "Coordination"],
        )
        score_val, _, _ = scorer.score_job(job)
        # Role ~28 + skills 0 + exp 20 = ~48, no career/practical
        assert score_val < 55

    def test_two_matches_from_sixteen_skills(self, candidate_profile):
        """2 matches out of 16 job skills — skill_points = min(25, 2*6) = 12."""
        scorer = Scorer(candidate_profile)
        job = _make_job(
            title="IT Support",
            skills_required=[
                "Linux",
                "Bash",
                "Communication",
                "English",
                "Teamwork",
                "Leadership",
                "Documentation",
                "Reporting",
                "Planning",
                "Coordination",
                "Problem Solving",
                "Time Management",
                "Customer Service",
                "Data Entry",
                "Excel",
                "Typing",
            ],
        )
        score_val, _, _ = scorer.score_job(job)
        # Role ~30 + skills 12 + exp 20 = ~62
        assert score_val >= 55

    def test_two_matches_from_two_skills(self, candidate_profile):
        """2 matches out of 2 job skills — skill_points = 12, same as 2/16.
        V2 is independent of job-list length."""
        scorer = Scorer(candidate_profile)
        job = _make_job(
            title="IT Support",
            skills_required=["Linux", "Bash"],
        )
        score_val, _, _ = scorer.score_job(job)
        # Same role + skills 12 + exp 20
        assert score_val >= 55

    def test_skill_independent_of_list_length(self, candidate_profile):
        """Same 2 matches produce identical scores regardless of total job skills."""
        scorer = Scorer(candidate_profile)
        job_small = _make_job(title="IT Support", skills_required=["Linux", "Bash"])
        job_large = _make_job(
            title="IT Support",
            skills_required=[
                "Linux",
                "Bash",
                "Communication",
                "English",
                "Teamwork",
                "Documentation",
                "Planning",
                "Coordination",
                "Problem Solving",
                "Time Management",
                "Customer Service",
                "Data Entry",
                "Excel",
                "Typing",
                "Filing",
                "Reporting",
            ],
        )
        score_small, _, _ = scorer.score_job(job_small)
        score_large, _, _ = scorer.score_job(job_large)
        assert score_small == score_large

    def test_full_eight_match(self, candidate_profile):
        """All 8 profile skills match — skill_points = min(25, 8*6) = 25 (capped)."""
        scorer = Scorer(candidate_profile)
        job = _make_job(
            title="Linux Administrator",
            skills_required=[
                "Linux",
                "System Administration",
                "RHEL",
                "Networking",
                "VMware",
                "Virtualization",
                "Kali Linux",
                "Bash",
            ],
        )
        score_val, classification, _ = scorer.score_job(job)
        # Role 30 + skills 25 + exp 20 = 75
        assert score_val >= 75
        assert classification == Classification.APPLY

    def test_empty_job_skills(self, candidate_profile):
        """No job skills listed — skill_points = 0 (guard clause)."""
        scorer = Scorer(candidate_profile)
        job = _make_job(title="IT Support")
        score_val, _, _ = scorer.score_job(job)
        # Role ~30 + skills 0 + exp 20 = ~50
        assert score_val < 55

    def test_exact_numeric_values(self, candidate_profile):
        """Verify min(25, matched * 6) produces exact expected values."""
        scorer = Scorer(candidate_profile)

        job1 = _make_job(title="xyz123", min_years_exp=5, skills_required=["VMware"])
        s1, _, _ = scorer.score_job(job1)

        job2 = _make_job(title="xyz123", min_years_exp=5, skills_required=["VMware", "Bash"])
        s2, _, _ = scorer.score_job(job2)

        job4 = _make_job(
            title="xyz123",
            min_years_exp=5,
            skills_required=["VMware", "Bash", "RHEL", "Networking"],
        )
        s4, _, _ = scorer.score_job(job4)

        base_score = s1 - 6
        assert s1 == base_score + 6
        assert s2 == base_score + 12
        assert s4 == base_score + 24


# ============================================================
# Salary Practical Factor Tests
# ============================================================


class TestSalaryFactor:
    def test_salary_both(self, candidate_profile):
        scorer = Scorer(candidate_profile)
        job = _make_job(title="IT Support", salary_min=5_000_000, salary_max=8_000_000)
        score_both, _, _ = scorer.score_job(job)

        job_none = _make_job(title="IT Support")
        score_none, _, _ = scorer.score_job(job_none)

        assert score_both - score_none == 5

    def test_salary_min_only(self, candidate_profile):
        scorer = Scorer(candidate_profile)
        job = _make_job(title="IT Support", salary_min=5_000_000)
        score_min, _, _ = scorer.score_job(job)

        job_none = _make_job(title="IT Support")
        score_none, _, _ = scorer.score_job(job_none)

        assert score_min - score_none == 5

    def test_salary_max_only(self, candidate_profile):
        scorer = Scorer(candidate_profile)
        job = _make_job(title="IT Support", salary_max=8_000_000)
        score_max, _, _ = scorer.score_job(job)

        job_none = _make_job(title="IT Support")
        score_none, _, _ = scorer.score_job(job_none)

        assert score_max - score_none == 5

    def test_salary_neither(self, candidate_profile):
        scorer = Scorer(candidate_profile)
        job = _make_job(title="IT Support")
        score_val, _, _ = scorer.score_job(job)

        # Baseline: no salary bonus
        job_with = _make_job(title="IT Support", salary_min=5_000_000)
        score_with, _, _ = scorer.score_job(job_with)

        assert score_with > score_val


# ============================================================
# Regression Tests
# ============================================================


class TestRegression:
    def test_hard_fail_senior_unchanged(self, candidate_profile):
        scorer = Scorer(candidate_profile)
        job = _make_job(title="Senior Linux Administrator")
        score_val, classification, reason = scorer.score_job(job)
        assert score_val == 0
        assert classification == Classification.IGNORE
        assert "Senior/Lead" in reason

    def test_hard_fail_3yr_unchanged(self, candidate_profile):
        scorer = Scorer(candidate_profile)
        job = _make_job(
            title="System Administrator",
            min_years_exp=3,
            experience_required="required",
        )
        score_val, classification, reason = scorer.score_job(job)
        assert score_val == 0
        assert classification == Classification.IGNORE
        assert "3+" in reason

    def test_security_guard_remains_ignore(self, candidate_profile):
        """Security Guard must remain IGNORE — no career match, no skill match."""
        scorer = Scorer(candidate_profile)
        job = _make_job(
            title="Security Guard",
            skills_required=["Physical Security", "CCTV Monitoring", "Communication"],
            workplace_type="on-site",
            salary_min=3_000_000,
        )
        score_val, classification, _ = scorer.score_job(job)
        assert classification == Classification.IGNORE
        # Max: role ~21 + skills 0 + exp 20 + career 0 + practical 10 = ~51
        assert score_val < 55


# ============================================================
# Real-Data Regression Tests (4 Audited Jobs)
# ============================================================


class TestRealDataRegression:
    """Tests using deterministic fixtures matching the actual database values
    for the 4 audited jobs. Jobs 1-3 have empty skills/requirements/summary
    due to the pre-fix persistence bug — these fixtures reflect that."""

    def test_admin_project(self, candidate_profile):
        """Admin Project: 36/IGNORE. Non-IT admin role, no relevant data."""
        scorer = Scorer(candidate_profile)
        job = _make_job(
            title="Admin Project",
            company="Staffinc Group",
            location="Jakarta Selatan",
            workplace_type="unknown",
            employment_type="unknown",
            experience_level="not_specified",
            application_url="https://loker.staffinc.co/HZR1B",
            # Pre-fix persistence: empty arrays
            skills_required=[],
            skills_preferred=[],
            requirements_raw=[],
        )
        score_val, classification, _ = scorer.score_job(job)
        assert score_val == 36
        assert classification == Classification.IGNORE

    def test_qa_engineer(self, candidate_profile):
        """QA Engineer: 33/IGNORE. No relevant skills/career match."""
        scorer = Scorer(candidate_profile)
        job = _make_job(
            title="QA Engineer",
            company="PT Hermes Solusi Integrasi",
            location="Grand Indonesia, Jakarta Pusat",
            workplace_type="unknown",
            employment_type="unknown",
            experience_level="not_specified",
            application_url="http://bit.ly/TalentPoolRava",
            # Pre-fix persistence: empty arrays
            skills_required=[],
            skills_preferred=[],
            requirements_raw=[],
        )
        score_val, classification, _ = scorer.score_job(job)
        assert score_val == 33
        assert classification == Classification.IGNORE

    def test_network_security_engineer(self, candidate_profile):
        """Network Security Engineer: 55/REVIEW. Career trajectory now matched
        via token_set_ratio('network security engineer', 'security engineering') = 80."""
        scorer = Scorer(candidate_profile)
        job = _make_job(
            title="Network Security Engineer",
            company="PT Nusa Network Prakarsa",
            workplace_type="unknown",
            employment_type="unknown",
            experience_level="not_specified",
            application_url="https://forms.gle/sdYGKDovQrpLeQ547",
            # Pre-fix persistence: empty arrays
            skills_required=[],
            skills_preferred=[],
            requirements_raw=[],
        )
        score_val, classification, _ = scorer.score_job(job)
        assert score_val == 55
        assert classification == Classification.REVIEW

    def test_l1_support(self, candidate_profile):
        """L1 Support: 58/REVIEW. Salary practical bonus now includes salary_max."""
        scorer = Scorer(candidate_profile)
        job = _make_job(
            title="L1 Support",
            workplace_type="remote",
            employment_type="unknown",
            experience_level="not_specified",
            min_years_exp=1,
            experience_required="required",
            salary_max=8_000_000,
            salary_currency="IDR",
            salary_period="monthly",
            salary_raw="IDR 8M/month (max)",
            skills_required=[
                "Helpdesk",
                "L1 Support",
                "Operations Support",
                "Logistics",
                "Freight forwarding",
                "Air cargo",
                "Operational support",
                "System support",
                "Troubleshooting",
                "Data processing",
                "Coordination",
                "Communication",
                "Fluent English",
            ],
            skills_preferred=["Logistics", "Freight forwarding", "Air cargo"],
            requirements_raw=[
                "Indonesian applicants only",
                "1+ year experience in Helpdesk / L1 Support or Operations Support",
                "Logistics / freight forwarding / air cargo experience is a plus",
                "Experience with operational or system support",
                "Basic troubleshooting & data processing",
                "Strong coordination & communication skills",
                "Fluent English (mandatory)",
            ],
            contacts={"emails": ["saputri@glints.com"]},
        )
        score_val, classification, _ = scorer.score_job(job)
        assert score_val == 58
        assert classification == Classification.REVIEW
