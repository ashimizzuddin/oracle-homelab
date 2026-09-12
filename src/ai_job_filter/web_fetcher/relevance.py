"""IT-relevance classifier for web-sourced job candidates.

Problem this solves: several boards expose a *whole-site* sitemap with no
category filter. Dealls and KitaLulus were both pulling every category
(housekeeping, personal trainer, medical rep, account executive, ...) into
the DB, which polluted scoring and statistics: 65% of rows in Aug-Sep 2026
were non-IT.

Design notes:
- Pure-python, no LLM calls: it runs on every fetched candidate and on
  re-filter passes, so it must be free and fast.
- The ``options`` block in config/web_fetchers.yaml previously carried
  ``keywords`` / ``category_path`` / ``specialization`` values that no code
  ever read. ``category_hint()`` makes those values meaningful by deriving
  extra search terms from them.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

# Titles that unambiguously identify an IT/technical role.
# NOTE: a bare "engineer" is deliberately NOT accepted — it matches civil,
# site, mechanical and project engineers. Technical roles must pair a
# domain word with a role word, or use a role name that is IT-only.
_IT_DOMAIN = (
    r"software|systems?|system|application|apps?|platform|data|security|cyber|"
    r"devops|infrastructure|infra|cloud|backend|back[\s-]?end|frontend|front[\s-]?end|"
    r"web|mobile|android|ios|qa|test|testing|automation|integration|release|"
    r"network|networking|database|db|erp|sap|salesforce|odoo|netsuite|"
    r"it|ict|linux|windows|server|storage|virtualization|middleware|api|"
    r"technical|service\s+desk|help\s?desk|noc|soc|"
    r"computer|komputer|citrix|vmware|hyper[\s-]?v|proxmox|zimbra|"
    r"data\s+cent(?:er|re)|datacenter|etl|blockchain|"
    r"ai|ml|hris|cyber\s?security|monitoring|observability|telemetry|"
    r"backup|disaster\s+recovery"
)
_IT_ROLE = (
    r"engineer|engineering|developer|programmer|analyst|analytics|architect|administrator|"
    r"admin|specialist|consultant|manager|lead|intern|internship|officer|director|"
    r"support|tester|technician|operations|operation|ops|scientist|integrator|"
    r"owner|integration|implementer|implementor|supervisor|coordinator|"
    r"auditor|operator|assistant|freelancer|staff|arsitek\s+sistem"
)

# Case-sensitive token check: in a job title, uppercase "IT"/"ICT" is the
# department, never the English pronoun. Applied only to the title.
_IT_TOKEN = re.compile(r"\b(?:IT|ICT|I\.T\.)\b")

_IT_TITLE = re.compile(
    rf"""
    \b(?:
        devops|dev\s?ops|devsecops|dev\s?sec\s?ops|sre|site\s+reliability|platform\s+engineer
      | sysadmin|system\s+administrator|sys\s+admin|linux\s+(?:admin|administrator)
      | (?:{_IT_DOMAIN})[\s\-/]+(?:{_IT_ROLE})[\s\-/]*(?:{_IT_ROLE})?
      | developer|programmer
      | full[\s-]?stack(?:[\s-]+(?:{_IT_ROLE}))?
      | dba|database\s+administrator
      | sdet|quality\s+assurance(?:[\s-]+(?:{_IT_ROLE}))?
      | cybersecurity|cyber\s+security|cyber\s+defense|cyber\s+defence
      | penetration\s+tester|penetration\s+testing|pentest|ethical\s+hacker
      | help\s?desk|service\s+desk
      | noc|ict|sap|qa
      | staff\s+it|staf\s+it|staf\s+ict|staff\s+ict|admin\s+it
      | (?:l1|l2|l3)\b
      | scrum\s+master|tech\s+lead|technical\s+lead|agile\s+coach
      | erp|data\s+migration
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Titles that are explicitly NOT IT even if they mention a tech word
# (e.g. "Technical Sales", "Mechanical Engineer").
_NON_IT_TITLE = re.compile(
    r"""
    \b(?:
        housekeeping|cleaning|security\s+guard|satpam|driver|kurir|courier
      | sales\s+support|sales\s+admin|sales\s+representative|sales\s+executive
      | sales|marketing|telemarketing|telesales|canvasser|business\s+development
      | account\s+executive|account\s+management|account\s+officer
      | accountant|accounting|finance|tax|pajak|auditor\s+pajak|payroll
      | performance\s+management|quality\s+control|revenue\s+growth
      | hr\s|human\s+resource|recruiter|talent\s+acquisition|people\s+partner
      | admin(?:istrative)?\s+(?:staff|finance|sales|marketplace|online|project|ecommerce|e-commerce)
      | customer\s+service|customer\s+support|cs\s+online|call\s+center|client\s+partner
      | barista|chef|waiter|waitress|cook|kitchen
      | nurse|perawat|dokter|apoteker|medical\s+representative|pharmacist
      | teacher|guru|dosen|personal\s+trainer|fitness|gym|voice\s+acting
      | mechanical|electrical|civil\s+engineering|industrial\s+engineering|manufacturing
      | site\s+engineer|project\s+engineer|teknik|technik|sipil|arsitek
      | technician|solar|commissioning|footwear|textile|garment
      | graphic\s+design|content\s+writer|copywriter|video\s+editor|lyrics
      | legal|lawyer|notaris|compliance\s+officer
      | procurement|purchasing|logistics|warehouse|gudang|supply\s+chain
      | merchandiser|store\s+supervisor|retail|event\s+manager|fundraising
      | growth|partnership|community\s+manager|social\s+media|data\s+entry
      | dealer\s+relationship|executive|supervisor|strategist
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Body-text fallback signal, weighted: a body mentioning several of these
# is very likely an IT posting even when the title is vague ("Staff", "Engineer").
_IT_BODY_SIGNALS = (
    (re.compile(r"\b(linux|ubuntu|centos|rhel|debian|red\s?hat|unix)\b", re.I), 3),
    (re.compile(r"\b(docker|kubernetes|k8s|container|openshift)\b", re.I), 3),
    (
        re.compile(
            r"\b(ci\s?/\s?cd|jenkins|gitlab|github\s+actions|pipeline|terraform|ansible)\b", re.I
        ),
        3,
    ),
    (re.compile(r"\b(aws|azure|gcp|google\s+cloud|oci|oracle\s+cloud)\b", re.I), 2),
    (re.compile(r"\b(devops|sre|site\s+reliability|observability)\b", re.I), 3),
    (
        re.compile(
            r"\b(network|networking|tcp/?ip|vpn|firewall|mikrotik|cisco|vlan|routing|dns)\b", re.I
        ),
        2,
    ),
    (re.compile(r"\b(sql|mysql|postgres|mariadb|mongodb|redis|database|query)\b", re.I), 2),
    (
        re.compile(
            r"\b(python|bash|shell\s+script|golang|java\b|javascript|node\.?js|php)\b", re.I
        ),
        2,
    ),
    (
        re.compile(
            r"\b(monitoring|prometheus|grafana|zabbix|nagios|elk|kibana|log\s+analysis)\b", re.I
        ),
        3,
    ),
    (
        re.compile(
            r"\b(cyber\s?security|penetration\s+test|pentest|vulnerability|soc|siem|malware|incident\s+response)\b",
            re.I,
        ),
        3,
    ),
    (
        re.compile(
            r"\b(troubleshoot|server|infrastructure|deployment|backup|disaster\s+recovery)\b", re.I
        ),
        2,
    ),
    (
        re.compile(
            r"\b(helpdesk|help\s+desk|technical\s+support|user\s+support|it\s+support)\b", re.I
        ),
        2,
    ),
    (re.compile(r"\b(git\b|version\s+control|rest\s?api|api\s+integration)\b", re.I), 1),
    (re.compile(r"\b(erp|sap|oracle\s+ebs|salesforce|odoo|netsuite)\b", re.I), 1),
)

# Minimum weighted body score before the fallback accepts a candidate.
_DEFAULT_BODY_THRESHOLD = 5

_STOPWORDS = frozenset(
    {
        "jobs",
        "job",
        "loker",
        "lowongan",
        "detail",
        "en",
        "id",
        "www",
        "com",
        "https",
        "http",
        "information",
        "technology",
        "teknologi",
        "informasi",
        "category",
        "specialization",
        "search",
        "q",
        "kerja",
        "opportunities",
        "opportunity",
    }
)


def category_hint(options: dict | None) -> str:
    """Derive extra search terms from a board's ``options`` block.

    Reads the keys that were previously dead config (``keywords``,
    ``category_path``, ``specialization``, ``tag``, ``query``) so a board can
    express what it is looking for without any board-specific code.
    """
    if not options:
        return ""

    terms: list[str] = []

    keywords = options.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    for kw in keywords:
        terms.append(str(kw))

    for key in ("specialization", "category", "tag", "query", "keyword"):
        value = options.get(key)
        if isinstance(value, str) and value:
            terms.append(value)

    for key in ("category_path", "listing_path", "search_path", "path"):
        value = options.get(key)
        if not isinstance(value, str) or not value:
            continue
        for segment in urlparse(value).path.split("/"):
            terms.append(unquote(segment))
        for values in parse_qs(urlparse(value).query).values():
            terms.extend(values)

    # Normalise and dedupe, dropping separators and stopwords.
    out: list[str] = []
    for term in terms:
        cleaned = re.sub(r"[-_+~.]+", " ", str(term)).strip().lower()
        if not cleaned or cleaned in _STOPWORDS:
            continue
        if len(cleaned) < 3:
            continue
        if cleaned not in out:
            out.append(cleaned)
    return " ".join(out)


def _body_signal_score(text: str) -> int:
    if not text:
        return 0
    score = 0
    for pattern, weight in _IT_BODY_SIGNALS:
        if pattern.search(text):
            score += weight
    return score


def is_it_job(
    title: str | None,
    description: str | None = None,
    *,
    hint: str = "",
    body_threshold: int = _DEFAULT_BODY_THRESHOLD,
) -> bool:
    """Return True when a posting looks like an IT/technical role.

    Precedence:
    1. An IT title wins outright — it is the strongest signal, and a noisy
       body must not veto it (e.g. "Cybersecurity" with a short body).
    2. A non-IT title loses outright, unless the rest of the title still
       carries an IT role (e.g. "Technical Sales Engineer").
    3. Otherwise, fall back to weighted body-text signals.
    """
    title = (title or "").strip()
    description = description or ""
    combined = f"{description}\n{hint}" if hint else description

    title_is_it = bool(title and _IT_TITLE.search(title))
    title_is_non_it = bool(title and _NON_IT_TITLE.search(title))

    # Uppercase "IT"/"ICT" in a title is the department, not the pronoun:
    # "IT Purchasing Officer" and "IT, Cook, GSA, FDA" are IT roles even
    # though they contain non-IT words.
    if title and _IT_TOKEN.search(title):
        return True

    # A trailing "Developer" is software by default ("Footwear Developer"
    # and "Business Developer" are not), so reject known non-software sectors.
    if re.search(r"\bdeveloper\b", title, re.I) and re.search(
        r"\b(?:footwear|textile|garment|fashion|property|real\s+estate|food|"
        r"beverage|cosmetic|automotive|business|channel|market)\b",
        title,
        re.I,
    ):
        return False

    if title_is_it:
        # Strip the non-IT phrase and re-test: if an IT role remains in the
        # title, keep it ("technical sales engineer" -> "engineer" does not
        # match the IT pattern, so it is dropped).
        residue = _NON_IT_TITLE.sub(" ", title)
        return bool(_IT_TITLE.search(residue))

    if title_is_non_it:
        return False

    return _body_signal_score(f"{title}\n{combined}") >= body_threshold


def classify_reason(title: str | None, description: str | None = None, *, hint: str = "") -> str:
    """Human-readable reason, for logs and dry-run reporting."""
    t = (title or "").strip()
    if t and _IT_TITLE.search(t):
        residue = _NON_IT_TITLE.sub(" ", t)
        if _IT_TITLE.search(residue):
            return "IT title"
    if t and _NON_IT_TITLE.search(t):
        return "non-IT title"
    score = _body_signal_score(f"{t}\n{description or ''}\n{hint}")
    return f"body signals ({score})"
