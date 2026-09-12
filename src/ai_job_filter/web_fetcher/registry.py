"""Fetcher registry (PRD F-WEB-2) — loads config/web_fetchers.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from .base import BaseFetcher, FetcherConfig
from .easy import (
    DeallsFetcher,
    HiredTodayFetcher,
    KitaLulusFetcher,
    LokerIdFetcher,
    TalenticsFetcher,
    TechInAsiaFetcher,
)
from .medium import GlintsFetcher, KalibrrFetcher, KarirComFetcher, TopKarirFetcher

FETCHER_CLASSES: dict[str, type[BaseFetcher]] = {
    "talentics": TalenticsFetcher,
    "hiredtoday": HiredTodayFetcher,
    "dealls": DeallsFetcher,
    "techinasia": TechInAsiaFetcher,
    "kitalulus": KitaLulusFetcher,
    "lokerid": LokerIdFetcher,
    "glints": GlintsFetcher,
    "kalibrr": KalibrrFetcher,
    "karircom": KarirComFetcher,
    "topkarir": TopKarirFetcher,
}

DEFAULT_CONFIG_PATH = Path("config/web_fetchers.yaml")


def load_fetcher_configs(config_path: Path | None = None) -> list[FetcherConfig]:
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults") or {}

    configs: list[FetcherConfig] = []
    for board in raw.get("boards") or []:
        name = board.get("name")
        if not name or name not in FETCHER_CLASSES:
            continue
        if not board.get("enabled", True):
            continue
        cfg = FetcherConfig(
            name=name,
            base_url=board.get("base_url", ""),
            enabled=True,
            interval_hours=int(board.get("interval_hours", defaults.get("interval_hours", 24))),
            delay_seconds=float(board.get("delay_seconds", defaults.get("delay_seconds", 3.0))),
            max_items=int(board.get("max_items", defaults.get("max_items", 20))),
            use_playwright=bool(board.get("use_playwright", defaults.get("use_playwright", False))),
            options=board.get("options") or {},
            it_only=bool(board.get("it_only", defaults.get("it_only", True))),
            attempt_multiplier=int(
                board.get("attempt_multiplier", defaults.get("attempt_multiplier", 3))
            ),
        )
        configs.append(cfg)
    return configs


def build_fetchers(db_repo=None, config_path: Path | None = None) -> list[BaseFetcher]:
    """Instantiate all enabled fetchers, wired to the shared Repository."""
    fetchers: list[BaseFetcher] = []
    for cfg in load_fetcher_configs(config_path):
        cls = FETCHER_CLASSES[cfg.name]
        fetchers.append(cls(cfg, db_repo))
    return fetchers
