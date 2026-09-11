"""Client-side guard for the Gemini free-tier quota.

Free tier on this account is small (Flash 5 RPM / 20 RPD, Flash-Lite
10 RPM / 20 RPD, reset at midnight Pacific). Hitting HTTP 429 repeatedly
stalls the whole vision queue, so every Gemini call must go through this
budget first:

- max 8 requests/minute and 18 requests/day (deliberately below the
  server limits to leave headroom),
- state persisted in ``data/gemini_budget.json`` so restarts don't lose
  the counters,
- server ``retry in Xs`` hints are honoured via :meth:`cooldown_from_error`.

Day boundaries use America/Los_Angeles (falls back to UTC when tzdata is
unavailable — the 18/20 margin absorbs the skew).
"""

import json
import os
import re
import tempfile
import time
from contextlib import suppress
from datetime import UTC, datetime

try:
    from zoneinfo import ZoneInfo

    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - missing tzdata
    _PACIFIC = None

DEFAULT_BUDGET_PATH = "data/gemini_budget.json"
MAX_RPM = 8
MAX_RPD = 18
DAY_SECONDS = 24 * 3600

_RETRY_IN_RE = re.compile(r"retry in (\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


def _pacific_today(now: datetime) -> str:
    if _PACIFIC is not None:
        return now.astimezone(_PACIFIC).date().isoformat()
    return now.astimezone(UTC).date().isoformat()


class GeminiBudget:
    """Tracks Gemini usage in a small JSON file. No network I/O."""

    def __init__(
        self,
        path: str = DEFAULT_BUDGET_PATH,
        max_rpm: int = MAX_RPM,
        max_rpd: int = MAX_RPD,
        time_fn=time.time,
    ):
        self.path = path
        self.max_rpm = max_rpm
        self.max_rpd = max_rpd
        self._time = time_fn

    # -- persistence --------------------------------------------------
    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                state = json.load(f)
            if not isinstance(state, dict):
                return {}
            return state
        except (OSError, ValueError):
            return {}

    def _save(self, state: dict) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory or ".", prefix=".gemini_budget-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f)
            os.replace(tmp, self.path)
        except BaseException:
            with suppress(OSError):
                os.unlink(tmp)
            raise

    def _pruned_calls(self, state: dict, now: float) -> list:
        calls = state.get("calls", [])
        if not isinstance(calls, list):
            return []
        cutoff = now - DAY_SECONDS
        return [t for t in calls if isinstance(t, (int, float)) and t >= cutoff]

    # -- public API ---------------------------------------------------
    def allow(self) -> tuple[bool, str | None]:
        """Return (ok, reason). ``reason`` is None when a call may proceed."""
        now = self._time()
        state = self._load()
        cooldown_until = state.get("cooldown_until", 0)
        if isinstance(cooldown_until, (int, float)) and cooldown_until > now:
            return False, f"cooldown {cooldown_until - now:.0f}s remaining"

        calls = self._pruned_calls(state, now)
        recent = [t for t in calls if t >= now - 60]
        if len(recent) >= self.max_rpm:
            return False, f"minute budget exhausted ({len(recent)}/{self.max_rpm})"

        today = _pacific_today(datetime.fromtimestamp(now, tz=UTC))
        # Counters reset on Pacific date change; the margin (18/20) absorbs
        # any skew when tzdata is unavailable (UTC fallback).
        if state.get("date") != today:
            daily_count = 0
        else:
            today_calls = state.get("today_calls", [])
            daily_count = len(today_calls) if isinstance(today_calls, list) else 0
        if daily_count >= self.max_rpd:
            return False, f"daily budget exhausted ({daily_count}/{self.max_rpd})"
        return True, None

    def record(self) -> None:
        """Record one issued Gemini request."""
        now = self._time()
        state = self._load()
        today = _pacific_today(datetime.fromtimestamp(now, tz=UTC))
        if state.get("date") != today:
            state["date"] = today
            state["today_calls"] = []
        today_calls = state.get("today_calls", [])
        if not isinstance(today_calls, list):
            today_calls = []
        today_calls.append(now)
        state["today_calls"] = today_calls
        calls = self._pruned_calls(state, now)
        calls.append(now)
        state["calls"] = calls
        self._save(state)

    def cooldown_from_error(self, message: str, default_seconds: float = 60.0) -> float:
        """Set cooldown from a server 429 message honouring ``retry in Xs``."""
        match = _RETRY_IN_RE.search(message or "")
        seconds = float(match.group(1)) if match else default_seconds
        seconds = max(1.0, seconds)
        state = self._load()
        state["cooldown_until"] = self._time() + seconds
        self._save(state)
        return seconds
