"""Validators for job application methods (PRD F-NOT-1, Opsi B).

Ensures jobs have a valid way to apply: vacancy-specific URL, valid contacts,
or Telegram fallback link.
"""

import re
from urllib.parse import urlparse


def is_vacancy_specific_url(url: str | None) -> bool:
    """Check if URL is a vacancy-specific page (not generic /careers or domain root).

    Examples:
        ✓ https://glints.com/id/opportunities/jobs/12345
        ✓ https://example.com/apply/software-engineer
        ✗ https://example.com/careers
        ✗ https://example.com/
        ✗ null
    """
    if not url or not isinstance(url, str):
        return False

    # Basic URL validation
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return False

    try:
        parsed = urlparse(url)
        path = parsed.path.strip("/")

        # Generic paths that are NOT vacancy-specific
        generic_patterns = [
            r"^$",  # Root / homepage
            r"^careers?$",
            r"^jobs?$",
            r"^lowongan$",
            r"^recruitment$",
            r"^hiring$",
            r"^about(/us)?$",
            r"^contact$",
        ]

        path_lower = path.lower()
        for pattern in generic_patterns:
            if re.match(pattern, path_lower):
                return False

        # If path has depth (e.g. /jobs/12345 or /apply/engineer), assume specific
        return len(path) > 0

    except Exception:
        return False


def is_valid_email(email: str) -> bool:
    """Validate email address with basic regex.

    Filters out common LLM hallucinations like single-char 'd' or 'null'.
    """
    if not email or not isinstance(email, str) or len(email) < 5:
        return False

    # Basic email regex (RFC 5322 simplified)
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email.strip()))


def is_valid_phone(phone: str) -> bool:
    """Validate phone number (international or local Indonesian format).

    Examples:
        ✓ +628123456789
        ✓ 08123456789
        ✓ 021-12345678
        ✗ 123 (too short)
        ✗ null
    """
    if not phone or not isinstance(phone, str):
        return False

    # Normalize: remove spaces, dashes, parentheses
    normalized = re.sub(r"[\s\-()]+", "", phone.strip())

    # Must be 8-15 digits, optionally starting with +
    pattern = r"^\+?[0-9]{8,15}$"
    return bool(re.match(pattern, normalized))


def is_valid_telegram_handle(handle: str) -> bool:
    """Validate Telegram username/handle.

    Examples:
        ✓ @username
        ✓ username
        ✗ @ (empty)
        ✗ null
    """
    if not handle or not isinstance(handle, str):
        return False

    clean = handle.strip().lstrip("@")
    # Telegram usernames: 5-32 chars, alphanumeric + underscore
    pattern = r"^[a-zA-Z0-9_]{5,32}$"
    return bool(re.match(pattern, clean))


def has_valid_contacts(contacts: dict) -> bool:
    """Check if contacts dict has at least one valid email, phone, WhatsApp, or Telegram handle.

    Args:
        contacts: dict with keys 'emails', 'phone_numbers', 'whatsapp', 'telegram_handles', 'other'
                  (from JobExtractionResult.contacts.model_dump())

    Returns:
        True if at least one valid contact method exists.
    """
    if not contacts or not isinstance(contacts, dict):
        return False

    # Check emails
    emails = contacts.get("emails") or []
    if any(is_valid_email(e) for e in emails):
        return True

    # Check phone numbers
    phones = contacts.get("phone_numbers") or []
    if any(is_valid_phone(p) for p in phones):
        return True

    # Check WhatsApp (same validation as phone)
    whatsapp = contacts.get("whatsapp") or []
    if any(is_valid_phone(w) for w in whatsapp):
        return True

    # Check Telegram handles
    handles = contacts.get("telegram_handles") or []
    if any(is_valid_telegram_handle(h) for h in handles):
        return True

    return False


def has_valid_apply_method(
    application_url: str | None,
    contacts: dict | None,
    can_build_tg_link: bool = False,
) -> bool:
    """Determine if a job has at least one valid way to apply.

    Priority:
        1. Vacancy-specific URL
        2. Valid contacts (email/phone/WhatsApp/Telegram)
        3. Telegram fallback link (if can_build_tg_link=True)

    Args:
        application_url: Job's application_url field
        contacts: Job's contacts dict
        can_build_tg_link: Whether t.me link can be built (source has telegram_id)

    Returns:
        True if job has a valid apply method.
    """
    if is_vacancy_specific_url(application_url):
        return True

    if has_valid_contacts(contacts):
        return True

    if can_build_tg_link:
        return True

    return False
