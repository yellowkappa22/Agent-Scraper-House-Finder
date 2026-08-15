from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from house_scrapers.config import SCRAPER_CONFIG, ScraperConfig, location_allowed
from house_scrapers.storage import open_offer_store

SITE_URL = "https://www.finders.co.uk"
SEARCH_URL = f"{SITE_URL}/oxfordshire/lettings/most-recent-first"
SEARCH_API = f"{SITE_URL}/search.ljson"
PLACE_ID = "51e7c62e73dadaf60fef5493"
STORAGE_BLOB = "finders/properties.json"
MODES = {"scrape_new_today", "scrape_all"}
INTRO_PATTERN = re.compile(r"£([\d,]+)\s*pcm,\s*(.+)")
POSTCODE_AREA_PATTERN = re.compile(r"\bOX\d{1,2}\b(?:\s+[0-9][A-Z]{2})?", re.IGNORECASE)

@dataclass(frozen=True)
class Discovery:
    offers: list[dict[str, object]]
    seen_adverts: int
    total_adverts: int
    pages: int
    stopped_at_older: bool

def http_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    return session

def parse_listing_intro(intro: str) -> tuple[int, str] | None:
    match = INTRO_PATTERN.search(intro)
    if match is None:
        return None
    return int(match.group(1).replace(",", "")), match.group(2)

def absolute_url(href: str) -> str:
    return urljoin(SITE_URL, href)

def parse_embedded_json(html: str, marker: str) -> dict[str, object]:
    start = html.find(marker)
    if start < 0:
        raise RuntimeError(f"Finders JSON marker not found: {marker}")
    value, _ = json.JSONDecoder().raw_decode(html[start + len(marker):].lstrip())
    if not isinstance(value, dict):
        raise RuntimeError(f"Finders JSON marker is not an object: {marker}")
    return value

def full_address(property_data: dict[str, object]) -> str:
    address = str(property_data.get("addressWithCommas") or property_data.get("displayAddress") or "").strip()
    postcode = str(property_data.get("postcode") or "").strip()
    if postcode and postcode.lower() not in address.lower():
        matches = list(POSTCODE_AREA_PATTERN.finditer(address))
        if matches:
            match = matches[-1]
            address = f"{address[:match.start()]}{postcode}{address[match.end():]}"
        else:
            address = f"{address}, {postcode}" if address else postcode
    return address

def candidate_offer(property_data: dict[str, object], config: ScraperConfig) -> dict[str, object] | None:
    rent = property_data.get("priceValue")
    link = str(property_data.get("url") or "")
    address = full_address(property_data)
    if not isinstance(rent, int) or rent >= config.max_rent or not link or not address:
        return None
    if not location_allowed(address, config):
        return None
    bedrooms = property_data.get("bedrooms")
    property_type = str(property_data.get("type") or "property")
    title = f"{bedrooms} bedroom {property_type} to rent" if bedrooms else f"{property_type} to rent"
    return {
        "title": title,
        "address": address,
        "rent": rent,
        "link": absolute_url(link),
        "created_at": property_data.get("createDate"),
        "postcode": property_data.get("postcode"),
        "latitude": property_data.get("lat"),
        "longitude": property_data.get("lng"),
        "agent_name": property_data.get("agency_name"),
        "agent_branch": property_data.get("branchName"),
        "agent_email": property_data.get("branchEmail"),
    }

def api_url(page: int) -> str:
    query = urlencode({
        "channel": "lettings",
        "place_id": PLACE_ID,
        "fragment": f"most-recent-first/status-available/page-{page}",
    }, safe="/")
    return f"{SEARCH_API}?{query}"

def discover_offers(session: requests.Session, config: ScraperConfig, mode: str, now: datetime | None = None) -> Discovery:
    if mode not in MODES:
        allowed = ", ".join(sorted(MODES))
        raise ValueError(f"FINDERS_MODE must be one of: {allowed}")
    today = (now or datetime.now(ZoneInfo("Europe/London"))).astimezone(ZoneInfo("Europe/London")).date()
    offers: list[dict[str, object]] = []
    seen: set[int] = set()
    total = 0
    page = 1
    while True:
        response = session.get(SEARCH_URL if page == 1 else api_url(page), timeout=30)
        response.raise_for_status()
        payload = parse_embedded_json(response.text, "var propertyData = ") if page == 1 else response.json()
        properties = payload.get("properties")
        pagination = payload.get("pagination")
        if not isinstance(properties, list) or not isinstance(pagination, dict):
            raise RuntimeError("Finders search response has an invalid contract")
        total = int(pagination.get("total_count") or total)
        for property_data in properties:
            if not isinstance(property_data, dict):
                continue
            property_id = property_data.get("property_id")
            if not isinstance(property_id, int) or property_id in seen:
                continue
            created_at = property_data.get("createDate")
            if mode == "scrape_new_today" and isinstance(created_at, str):
                created_date = datetime.fromisoformat(created_at).astimezone(ZoneInfo("Europe/London")).date()
                if created_date < today:
                    return Discovery(offers, len(seen), total, page, True)
            seen.add(property_id)
            offer = candidate_offer(property_data, config)
            if offer is not None:
                offers.append(offer)
        if mode == "scrape_new_today" or not pagination.get("has_next_page"):
            break
        page += 1
    if mode == "scrape_all" and total and len(seen) != total:
        raise RuntimeError(f"Finders traversal incomplete: saw {len(seen)} of {total} adverts")
    return Discovery(offers, len(seen), total, page, False)

def scrape_new_today(session: requests.Session, config: ScraperConfig) -> Discovery:
    return discover_offers(session, config, "scrape_new_today")

def scrape_all(session: requests.Session, config: ScraperConfig) -> Discovery:
    return discover_offers(session, config, "scrape_all")

def detail_offer(session: requests.Session, candidate: dict[str, object], config: ScraperConfig) -> dict[str, object] | None:
    response = session.get(str(candidate["link"]), timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    marker = "Homeflow.set(" + chr(39) + "property_data" + chr(39) + ", "
    details = parse_embedded_json(response.text, marker)
    raw_description = str(details.get("description") or "")
    description = BeautifulSoup(raw_description, "html.parser").get_text(chr(10), strip=True)
    if not description:
        raise RuntimeError("Missing Finders description for {}".format(candidate["link"]))
    address = str(candidate["address"])
    if not location_allowed(address, config):
        raise RuntimeError("Finders detail location is excluded: {}".format(candidate["link"]))
    branch_address = BeautifulSoup(str(details.get("branchAddressWithLineBreaks") or ""), "html.parser").get_text(", ", strip=True)
    metadata = {
        "source": "finders",
        "postcode": candidate.get("postcode"),
        "latitude": candidate.get("latitude"),
        "longitude": candidate.get("longitude"),
        "created_at": candidate.get("created_at"),
        "agent": {
            "name": candidate.get("agent_name"),
            "branch": details.get("branchName") or candidate.get("agent_branch"),
            "address": branch_address,
            "email": candidate.get("agent_email"),
            "phone": details.get("contactTelephone"),
        },
    }
    return {
        "address": "{} — {}".format(candidate["title"], address),
        "rent": candidate["rent"],
        "link": candidate["link"],
        "description": description,
        "metadata": metadata,
    }

def run() -> None:
    config = SCRAPER_CONFIG["finders"]
    mode = config.mode or "scrape_new_today"
    store = open_offer_store(STORAGE_BLOB)
    registered = {str(offer.get("link")): offer for offer in store.offers}
    with http_session() as session:
        discovery = discover_offers(session, config, mode)
        print(f"Scanned {discovery.seen_adverts}/{discovery.total_adverts} unique adverts across {discovery.pages} pages")
        changed: list[dict[str, object]] = []
        new_count = 0
        for index, candidate in enumerate(discovery.offers, start=1):
            existing = registered.get(str(candidate["link"]))
            existing_metadata = existing.get("metadata") if existing else None
            if isinstance(existing_metadata, dict) and existing_metadata.get("source") == "finders":
                continue
            offer = detail_offer(session, candidate, config)
            if offer is None:
                print(f"Skipped unavailable listing {candidate['link']}")
                continue
            changed.append(offer)
            if existing is None:
                new_count += 1
            print(f"Retrieved {index}/{len(discovery.offers)} candidate details")
        if changed:
            store.upsert_many(changed)
        store.update_activity(
            {str(offer["link"]) for offer in discovery.offers},
            complete=mode == "scrape_all",
        )
        print(f"Saved {new_count} new and enriched {len(changed) - new_count} existing listings")
