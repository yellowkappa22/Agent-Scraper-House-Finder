from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from house_scrapers.config import SCRAPER_CONFIG, ScraperConfig, location_allowed
from house_scrapers.storage import open_offer_store

SITE_URL = "https://www.scottfraser.co.uk"
STORAGE_BLOB = "scottfraser/properties.json"
MODES = {"scrape_new_today", "scrape_all"}


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
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    return session


def search_url(max_rent: int, page: int = 1) -> str:
    parts = ["properties", "to-rent", "in-oxfordshire", f"price-under-{max_rent}"]
    if page > 1:
        parts.append(f"page-{page}")
    return f"{SITE_URL}/{'/'.join(parts)}/"


def parse_next_payload(html: str, marker: str) -> dict[str, object]:
    chunks: list[str] = []
    for node in BeautifulSoup(html, "html.parser").find_all("script"):
        text = node.string or ""
        match = re.fullmatch(r"self\.__next_f\.push\((.*)\)", text, re.DOTALL)
        if match is None:
            continue
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(value, list) and len(value) > 1 and isinstance(value[1], str):
            chunks.append(value[1])
    data = "".join(chunks)
    start = data.find(marker)
    if start < 0:
        raise RuntimeError(f"Scott Fraser JSON marker not found: {marker}")
    value, _ = json.JSONDecoder().raw_decode(data[start + len(marker):])
    if not isinstance(value, dict):
        raise RuntimeError(f"Scott Fraser JSON marker is not an object: {marker}")
    return value


def candidate_offer(data: dict[str, object], config: ScraperConfig) -> dict[str, object] | None:
    rent = data.get("price")
    address = str(data.get("display_address") or "").strip()
    slug = str(data.get("slug") or "")
    property_id = str(data.get("crm_id") or "")
    if str(data.get("status") or "").lower() != "to let":
        return None
    if not isinstance(rent, int) or rent >= config.max_rent or not address or not slug or not property_id:
        return None
    if not location_allowed(address, config):
        return None
    return {
        "id": property_id, "title": str(data.get("title") or "Property to rent"),
        "address": address, "rent": rent,
        "link": urljoin(SITE_URL, f"/properties-to-rent/{slug}/{property_id.lower()}/"),
        "created_at": data.get("created"), "updated_at": data.get("updated"),
        "latitude": data.get("latitude"), "longitude": data.get("longitude"),
    }


def discover_offers(session: requests.Session, config: ScraperConfig, mode: str, now: datetime | None = None) -> Discovery:
    if mode not in MODES:
        raise ValueError(f"SCOTTFRASER_MODE must be one of: {', '.join(sorted(MODES))}")
    today = (now or datetime.now(ZoneInfo("Europe/London"))).astimezone(ZoneInfo("Europe/London")).date()
    offers: list[dict[str, object]] = []
    seen: set[str] = set()
    total = pages = 0
    stopped = False
    page = 1
    while True:
        response = session.get(search_url(config.max_rent, page), timeout=30)
        response.raise_for_status()
        results = parse_next_payload(response.text, '"searchResults":')
        hits = results.get("hits")
        if not isinstance(hits, list):
            raise RuntimeError("Scott Fraser search response has an invalid contract")
        pages += 1
        total = int(results.get("nbHits") or total)
        page_count = int(results.get("nbPages") or 1)
        for data in hits:
            if not isinstance(data, dict):
                continue
            property_id = str(data.get("crm_id") or "")
            if not property_id or property_id in seen:
                continue
            created_at = data.get("created")
            if mode == "scrape_new_today" and isinstance(created_at, str):
                created_date = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/London")).date()
                if created_date < today:
                    stopped = True
                    seen.add(property_id)
                    continue
            seen.add(property_id)
            offer = candidate_offer(data, config)
            if offer is not None:
                offers.append(offer)
        if page >= page_count:
            break
        page += 1
    if mode == "scrape_all" and total and len(seen) != total:
        raise RuntimeError(f"Scott Fraser traversal incomplete: saw {len(seen)} of {total} adverts")
    return Discovery(offers, len(seen), total, pages, stopped)


def scrape_new_today(session: requests.Session, config: ScraperConfig) -> Discovery:
    return discover_offers(session, config, "scrape_new_today")


def scrape_all(session: requests.Session, config: ScraperConfig) -> Discovery:
    return discover_offers(session, config, "scrape_all")


def detail_offer(session: requests.Session, candidate: dict[str, object], config: ScraperConfig) -> dict[str, object] | None:
    response = session.get(str(candidate["link"]), timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = parse_next_payload(response.text, '"propertyData":')
    description = BeautifulSoup(str(data.get("long_description") or data.get("description") or ""), "html.parser").get_text("\n", strip=True)
    if not description:
        raise RuntimeError(f"Missing Scott Fraser description for {candidate['link']}")
    address = str(data.get("display_address") or candidate["address"]).strip()
    if not location_allowed(address, config):
        raise RuntimeError(f"Scott Fraser detail location is excluded: {candidate['link']}")
    postcode = data.get("post_code")
    raw_address = data.get("address") if isinstance(data.get("address"), dict) else {}
    postcode = postcode or raw_address.get("postcode")
    negotiator = data.get("crm_negotiator_details") if isinstance(data.get("crm_negotiator_details"), dict) else {}
    metadata = {
        "source": "scottfraser", "listing_id": data.get("crm_id") or candidate.get("id"),
        "postcode": postcode, "latitude": data.get("latitude", candidate.get("latitude")),
        "longitude": data.get("longitude", candidate.get("longitude")),
        "created_at": data.get("created", candidate.get("created_at")),
        "updated_at": data.get("updated", candidate.get("updated_at")), "status": data.get("status"),
        "bedrooms": data.get("bedroom"), "bathrooms": data.get("bathroom"),
        "property_type": data.get("property_type"), "additional_info": data.get("additional_info") or {},
        "agent": {"name": negotiator.get("name"), "branch": data.get("office_mapping"), "email": negotiator.get("email"), "phone": negotiator.get("work_phone")},
    }
    title = str(data.get("title") or candidate.get("title") or "Property to rent")
    return {"address": f"{title} — {address}", "rent": candidate["rent"], "link": candidate["link"],
            "description": description, "metadata": metadata}


def run() -> None:
    config = SCRAPER_CONFIG["scottfraser"]
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
            metadata = existing.get("metadata") if existing else None
            if isinstance(metadata, dict) and metadata.get("source") == "scottfraser":
                continue
            offer = detail_offer(session, candidate, config)
            if offer is None:
                continue
            changed.append(offer)
            new_count += existing is None
            print(f"Retrieved {index}/{len(discovery.offers)} candidate details")
        if changed:
            store.upsert_many(changed)
        store.update_activity({str(offer["link"]) for offer in discovery.offers}, complete=mode == "scrape_all")
        print(f"Saved {new_count} new and enriched {len(changed) - new_count} existing listings")
