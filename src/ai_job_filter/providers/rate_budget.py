"""Client-side budget guard for Gemini free tier.

Why this exists: Gemini 2.5 Flash-Lite on this account is limited to
~10 RPM / 20 RPD (see AI Studio rate-limit dashboard). One image = one
request, so blind retries burn the whole daily quota in minutes.

Policy (free-first, no paid fallback):
- RPM sliding window (default 8/min, buffer below the 10 limit).
- RPD daily counter (default 18/day, buffer below the 20 limit).
  RPD resets at midnight America/Los_Angeles (Google's documented reset).
- Cooldown after a 429: honor server RetryInfo when available.
- Persistence is best-effort JSON so the counter survives restarts.
  In-memory-only when budget_path is None (used by unit tests).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

from .errors import ProviderRateLimitError

PT_TZ = ZoneInfo("America/Los_Angeles")

# PENDING_* statuses share one vocabulary across worker + reprocess CLI.
PENDING_STATUSES = ("PENDING_AI", "PENDING_VISION", "RATE_LIMITED")

# Terminal failure statuses retried only via manual reprocess CLI.
FAILED_STATUSES = ("EXTRACTION_FAILED", "VISION_FAILED")


def parse_retry_delay_seconds(error_text: str, default: int = 60) -> int:
    """Extract `retry in Xs` from a Gemini 429 message.

    Example: "Please retry in 27.96s" -> 28. Falls back to default.
    """
    m = re.search(r"retry in ([\d.]+)s", error_text or "")
    if not m:
        return default
    try:
        return max(1, int(float(m.group(1))) + 1)
    except ValueError:
        return default


def pacific_today_str(now_ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(now_ts if now_ts is not None else time.time(), tz=PT_TZ)
    return dt.strftime("%Y-%m-%d")


class GeminiBudget:
    """Async-safe RPM + RPD guard with optional JSON persistence."""

    def __init__(
        self,
        max_rpm: int = 8,
        max_rpd: int = 18,
        budget_path: str | None = None,
    ):
        self.max_rpm = max_rpm
        self.max_rpd = max_rpd
        self.budget_path = budget_path
        self._lock = asyncio.Lock()
        self._minute_marks: deque[float] = deque()
        self._day_key = pacific_today_str()
        self._day_count = 0
        self.cooldown_until = 0.0
        self._loaded = False

    # -- persistence (best effort, never raise) --
    def _load(self) -> None:
        if self._loaded or not self.budget_path:
            self._loaded = True
            return
        self._loaded = True
        try:
            if not os.path.exists(self.budget_path):
                return
            with open(self.budget_path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date_pt") == self._day_key:
                self._day_count = int(data.get("count", 0))
        except Exception:
            return

    def _save(self) -> None:
        if not self.budget_path:
            return
        try:
            parent = os.path.dirname(self.budget_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = self.budget_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"date_pt": self._day_key, "count": self._day_count}, f)
            os.replace(tmp, self.budget_path)
        except Exception:
            return

    def _roll_day_if_needed(self) -> None:
        today = pacific_today_str()
        if today != self._day_key:
            self._day_key = today
            self._day_count = 0
            self._minute_marks.clear()

    def _prune_minute(self, now: float) -> None:
        cutoff = now - 60.0
        while self._minute_marks and self._minute_marks[0] <= cutoff:
            self._minute_marks.popleft()

    async def acquire(self) -> None:
        """Reserve one request slot or raise ProviderRateLimitError (no network)."""
        async with self._lock:
            self._load()
            self._roll_day_if_needed()
            now = time.time()
            self._prune_minute(now)

            if now < self.cooldown_until:
                wait = int(self.cooldown_until - now) + 1
                raise ProviderRateLimitError(
                    f"Gemini client cooldown active, retry in {wait}s "
                    f"(budget {self._day_count}/{self.max_rpd} today PT)."
                )
            if self._day_count >= self.max_rpd:
                raise ProviderRateLimitError(
                    f"Gemini daily budget exhausted ({self._day_count}/{self.max_rpd} PT). "
                    "Queued as PENDING_VISION until midnight Pacific."
                )
            if len(self._minute_marks) >= self.max_rpm:
                oldest = self._minute_marks[0]
                wait = int(oldest + 60 - now) + 1
                raise ProviderRateLimitError(
                    f"Gemini per-minute budget full ({len(self._minute_marks)}/{self.max_rpm}). "
                    f"Retry in {wait}s."
                )

            self._minute_marks.append(now)
            self._day_count += 1
            self._save()

    async def note_rate_limited(self, retry_after_seconds: int = 60) -> None:
        """Enter cooldown after a server 429 (called by provider)."""
        async with self._lock:
            self.cooldown_until = max(
                self.cooldown_until, time.time() + max(1, retry_after_seconds)
            )

    async def status(self) -> dict:
        async with self._lock:
            self._load()
            self._roll_day_if_needed()
            self._prune_minute(time.time())
            return {
                "date_pt": self._day_key,
                "used_today": self._day_count,
                "max_rpd": self.max_rpd,
                "used_minute": len(self._minute_marks),
                "max_rpm": self.max_rpm,
                "cooldown_seconds_left": max(0, int(self.cooldown_until - time.time())),
            }
