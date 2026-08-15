from __future__ import annotations

import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ScraperConfig:
    max_rent: int
    headless: bool
    excluded_locations: tuple[str, ...]
    mode: str | None = None


def _boolean(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes"}


def _locations() -> tuple[str, ...]:
    return tuple(
        location.strip().lower()
        for location in os.getenv("EXCLUDED_LOCATIONS", "Banbury,Didcot").split(",")
        if location.strip()
    )


def location_allowed(location: str, config: ScraperConfig) -> bool:
    normalized = location.lower()
    return not any(excluded in normalized for excluded in config.excluded_locations)


def oxfordshire_location_allowed(location: str, config: ScraperConfig) -> bool:
    return bool(re.search(r"\bOX\d{1,2}\b", location, re.IGNORECASE)) and location_allowed(
        location, config
    )


SCRAPER_CONFIG = {
    "finders": ScraperConfig(
        max_rent=int(os.getenv("FINDERS_MAX_RENT", "1200")),
        headless=_boolean("FINDERS_HEADLESS"),
        excluded_locations=_locations(),
        mode=os.getenv("FINDERS_MODE", "scrape_new_today"),
    ),
    "onthemarket": ScraperConfig(
        max_rent=int(os.getenv("ONTHEMARKET_MAX_RENT", "1200")),
        headless=_boolean("ONTHEMARKET_HEADLESS"),
        excluded_locations=_locations(),
        mode=os.getenv("ONTHEMARKET_MODE", "scrape_new_today"),
    ),
    "dailyinfo": ScraperConfig(
        max_rent=int(os.getenv("DAILYINFO_MAX_RENT", "1200")),
        headless=_boolean("DAILYINFO_HEADLESS"),
        excluded_locations=_locations(),
        mode=os.getenv("DAILYINFO_MODE", "scrape_new_today"),
    ),
    "spareroom": ScraperConfig(
        max_rent=int(os.getenv("SPAREROOM_MAX_RENT", "1200")),
        headless=_boolean("SPAREROOM_HEADLESS"),
        excluded_locations=_locations(),
        mode=os.getenv("SPAREROOM_MODE", "scrape_new_today"),
    ),
}
