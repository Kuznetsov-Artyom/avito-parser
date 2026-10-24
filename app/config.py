"""Настройки приложения, читаются из .env (см. .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "avito_parser.db"
PROFILE_DIR = DATA_DIR / "browser_profile"  # персистентный профиль Chromium


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    default_city: str = os.environ.get("DEFAULT_CITY", "moskva")
    distance_radius_km: float = field(default_factory=lambda: _env_float("DISTANCE_RADIUS_KM", 50.0))
    page_delay_min: float = field(default_factory=lambda: _env_float("PAGE_DELAY_MIN", 2.0))
    page_delay_max: float = field(default_factory=lambda: _env_float("PAGE_DELAY_MAX", 5.0))
    max_items: int = field(default_factory=lambda: _env_int("MAX_ITEMS", 30))
    deep_scan: bool = field(default_factory=lambda: os.environ.get("DEEP_SCAN", "0") == "1")
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))


settings = Settings()
