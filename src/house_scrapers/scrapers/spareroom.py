from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from house_scrapers.config import SCRAPER_CONFIG, ScraperConfig, oxfordshire_location_allowed
from house_scrapers.storage import open_offer_store

SITE_URL = "https://www.spareroom.co.uk"
SEARCH_URL = f"{SITE_URL}/flatshare/oxfordshire"
STORAGE_BLOB = "spareroom/properties.json"
MODES = {"scrape_new_today", "scrape_all"}
TOTAL_PATTERN = re.compile(r"of\s+([\d,]+)\s+results", re.IGNORECASE)
COORDINATES_PATTERN = re.compile(
    r"advert\s*:\s*\{.*?location\s*:\s*\{\s*"
    r"latitude\s*:\s*[\"'](-?\d+(?:\.\d+)?)[\"']\s*,\s*"
    r"longitude\s*:\s*[\"'](-?\d+(?:\.\d+)?)[\"']",
    re.DOTALL,
)


@dataclass(frozen=True)
class Discovery:
    offers: list[dict[str, object]]
    seen_adverts: int
    total_adverts: int
    pages: int
    stopped_at_older: bool


def http_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; HouseScrapers/0.1)"
    return session


def monthly_rent(rate: str, period: str) -> int | None:
    match = re.search(r"£([\d,]+)", rate)
    if match is None:
        return None
    amount = int(match.group(1).replace(",", ""))
    return round(amount * 52 / 12) if period.lower() == "pw" else amount


def canonical_url(href: str) -> str:
    parts = urlsplit(urljoin(SITE_URL, href))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def parse_card(card: object, config: ScraperConfig) -> dict[str, object] | None:
    location_element = card.select_one(".listing-card__location")
    link = card.select_one("a.listing-card__link")
    if location_element is None or link is None:
        return None
    href = str(link.get("href") or "")
    if not href.startswith("/flatshare/"):
        return None
    location = location_element.get_text(" ", strip=True)
    title = str(card.get("data-listing-title") or "").strip()
    rent = monthly_rent(
        str(card.get("data-listing-ad-rate-normalised") or ""),
        str(card.get("data-listing-ad-rate-normalised-period") or ""),
    )
    if not title or rent is None or rent >= config.max_rent:
        return None
    if not oxfordshire_location_allowed(location, config):
        return None
    return {
        "address": f"{title} — {location}",
        "rent": rent,
        "link": canonical_url(href),
    }


SECTION_NAMES = {
    "availability": "availability",
    "extra-cost": "extra_cost",
    "amenities": "amenities",
    "current-household": "current_household",
    "household-preferences": "new_housemate_preferences",
}
KEY_NAMES = {
    "# flatmates": "current_housemates",
    "# housemates": "current_housemates",
    "total # rooms": "total_rooms",
    "couples ok?": "couples_allowed",
    "smoking ok?": "smoking_allowed",
    "pets suitable?": "pets_allowed",
    "references?": "references_required",
}


def metadata_key(label: str) -> str:
    normalized = " ".join(label.lower().split())
    if normalized in KEY_NAMES:
        return KEY_NAMES[normalized]
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return normalized


def metadata_value(key: str, value: str) -> object:
    normalized = value.strip()
    if normalized.lower() == "yes":
        return True
    if normalized.lower() == "no":
        return False
    if normalized.lower() == "none":
        return None
    if key in {"current_housemates", "total_rooms"} and normalized.isdigit():
        return int(normalized)
    return normalized


def parse_metadata(soup: BeautifulSoup) -> dict[str, object]:
    metadata: dict[str, object] = {"source": "spareroom"}
    for class_suffix, section_name in SECTION_NAMES.items():
        section = soup.select_one(f"section.feature--{class_suffix}")
        if section is None:
            continue
        values: dict[str, object] = {}
        for label in section.select("dt"):
            value = label.find_next_sibling("dd")
            if value is None:
                continue
            key = metadata_key(label.get_text(" ", strip=True))
            values[key] = metadata_value(key, value.get_text(" ", strip=True))
        if values:
            metadata[section_name] = values
    return metadata


def parse_coordinates(html: str) -> tuple[float, float] | None:
    match = COORDINATES_PATTERN.search(html)
    if match is None:
        return None
    return float(match.group(1)), float(match.group(2))


def discover_offers(
    session: requests.Session, config: ScraperConfig, mode: str
) -> Discovery:
    if mode not in MODES:
        raise ValueError(f"SPAREROOM_MODE must be one of: {', '.join(sorted(MODES))}")

    url = f"{SEARCH_URL}?sort_by=days_since_placed"
    seen_ids: set[str] = set()
    offers: list[dict[str, object]] = []
    total = 0
    pages = 0

    while url:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        pages += 1

        current = soup.select_one(".navcurrent")
        total_match = TOTAL_PATTERN.search(current.get_text(" ", strip=True) if current else "")
        if total_match:
            total = int(total_match.group(1).replace(",", ""))

        for card in soup.select("li.listing-result"):
            status = card.select_one(".listing-card__status")
            status_classes = set(status.get("class", ())) if status else set()
            if mode == "scrape_new_today" and "listing-card__status--new" in status_classes:
                return Discovery(offers, len(seen_ids), total, pages, True)

            advert_id = str(card.get("data-listing-id") or "")
            if not advert_id or advert_id in seen_ids:
                continue
            seen_ids.add(advert_id)
            offer = parse_card(card, config)
            if offer is not None:
                offers.append(offer)

        next_link = soup.select_one("#paginationNextPageLink")
        if next_link is None:
            url = ""
        else:
            url = f"{urljoin(SITE_URL, str(next_link.get('href')))}?sort_by=days_since_placed"

    if mode == "scrape_all" and total and len(seen_ids) < total:
        expected_pages = math.ceil(total / 10)
        raise RuntimeError(
            f"SpareRoom traversal incomplete: saw {len(seen_ids)} of {total} adverts "
            f"across {pages} of approximately {expected_pages} pages"
        )
    return Discovery(offers, len(seen_ids), total, pages, False)


def scrape_new_today(session: requests.Session, config: ScraperConfig) -> Discovery:
    return discover_offers(session, config, "scrape_new_today")


def scrape_all(session: requests.Session, config: ScraperConfig) -> Discovery:
    return discover_offers(session, config, "scrape_all")


def run() -> None:
    config = SCRAPER_CONFIG["spareroom"]
    mode = config.mode or "scrape_new_today"
    store = open_offer_store(STORAGE_BLOB)
    registered_offers = {str(offer.get("link")): offer for offer in store.offers}

    with http_session() as session:
        discovery = discover_offers(session, config, mode)
        print(
            f"Scanned {discovery.seen_adverts}/{discovery.total_adverts} unique adverts "
            f"across {discovery.pages} pages"
        )
        changed_offers: list[dict[str, object]] = []
        new_count = 0
        for index, offer in enumerate(discovery.offers, start=1):
            link = str(offer["link"])
            existing = registered_offers.get(link)
            existing_metadata = existing.get("metadata") if existing else None
            has_coordinates = (
                isinstance(existing_metadata, dict)
                and isinstance(existing_metadata.get("latitude"), (int, float))
                and isinstance(existing_metadata.get("longitude"), (int, float))
            )
            if (
                isinstance(existing_metadata, dict)
                and existing_metadata.get("source") == "spareroom"
                and has_coordinates
            ):
                continue
            response = session.get(link, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            description_element = soup.select_one(".detaildesc")
            if description_element is None:
                raise RuntimeError(f"Missing description for {offer[link]}")
            description = description_element.get_text(chr(10), strip=True)
            if not description:
                raise RuntimeError(f"Empty description for {offer[link]}")
            offer["description"] = description
            offer["metadata"] = parse_metadata(soup)
            coordinates = parse_coordinates(response.text)
            if coordinates is not None:
                offer["metadata"]["latitude"], offer["metadata"]["longitude"] = coordinates
            changed_offers.append(offer)
            if existing is None:
                new_count += 1
            print(f"Retrieved {index}/{len(discovery.offers)} candidate details")
        if changed_offers:
            store.upsert_many(changed_offers)
        store.update_activity(
            {str(offer["link"]) for offer in discovery.offers},
            complete=mode == "scrape_all",
        )
        print(
            f"Saved {new_count} new and enriched "
            f"{len(changed_offers) - new_count} existing listings"
        )
