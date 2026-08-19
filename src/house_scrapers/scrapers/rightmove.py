from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from house_scrapers.config import SCRAPER_CONFIG, ScraperConfig, location_allowed
from house_scrapers.storage import open_offer_store

SITE_URL = "https://www.rightmove.co.uk"
SEARCH_URL = f"{SITE_URL}/property-to-rent/Oxfordshire.html"
STORAGE_BLOB = "rightmove/properties.json"
MODES = {"scrape_new_today", "scrape_all"}
CURRENT_STATUSES = {"Added today", "Reduced today"}
OLDER_PATTERN = re.compile(r"^(?:Added|Reduced) (?:yesterday|on )", re.I)
PAGE_MODEL_MARKER = "window.__PAGE_MODEL = "

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
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    return session

def canonical_url(href: str) -> str:
    parts = urlsplit(urljoin(SITE_URL, href))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

def search_url(max_rent: int, index: int = 0) -> str:
    query = {
        "sortType": 6, "maxPrice": max_rent, "index": index,
        "propertyTypes": "", "mustHave": "", "dontShow": "",
        "furnishTypes": "", "keywords": "",
    }
    return f"{SEARCH_URL}?{urlencode(query)}"

def parse_search_results(html: str) -> dict[str, object]:
    node = BeautifulSoup(html, "html.parser").select_one("#__NEXT_DATA__")
    if node is None or not node.string:
        raise RuntimeError("Rightmove search JSON was not found")
    try:
        results = json.loads(node.string)["props"]["pageProps"]["searchResults"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("Rightmove search JSON has an invalid contract") from error
    if not isinstance(results, dict):
        raise RuntimeError("Rightmove search results are invalid")
    return results

def candidate_offer(data: dict[str, object], config: ScraperConfig) -> dict[str, object] | None:
    price = data.get("price")
    address = str(data.get("displayAddress") or "").strip()
    href = str(data.get("propertyUrl") or "")
    if not isinstance(data.get("id"), int) or not isinstance(price, dict):
        return None
    rent = price.get("amount")
    if not isinstance(rent, int) or rent >= config.max_rent or not address or not href or not location_allowed(address, config):
        return None
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    location = data.get("location") if isinstance(data.get("location"), dict) else {}
    return {
        "id": data["id"], "address": address, "rent": rent,
        "link": canonical_url(href),
        "status": str(data.get("addedOrReduced") or "").strip() or None,
        "summary": str(data.get("summary") or "").strip(),
        "title": str(data.get("propertyTypeFullDescription") or data.get("propertySubType") or "Property"),
        "latitude": location.get("latitude"), "longitude": location.get("longitude"),
        "agent_name": customer.get("branchDisplayName"),
        "agent_phone": customer.get("contactTelephone"),
    }

def discover_offers(session: requests.Session, config: ScraperConfig, mode: str) -> Discovery:
    if mode not in MODES:
        raise ValueError(f"RIGHTMOVE_MODE must be one of: {', '.join(sorted(MODES))}")
    offers: list[dict[str, object]] = []
    seen: set[int] = set()
    total = index = pages = 0
    saw_current = stopped = False
    while True:
        response = session.get(search_url(config.max_rent, index), timeout=30)
        response.raise_for_status()
        results = parse_search_results(response.text)
        properties, pagination = results.get("properties"), results.get("pagination")
        if not isinstance(properties, list) or not isinstance(pagination, dict):
            raise RuntimeError("Rightmove search response has an invalid contract")
        pages += 1
        total = int(results.get("resultCount") or total)
        for item in properties:
            if not isinstance(item, dict) or not isinstance(item.get("id"), int) or item["id"] in seen:
                continue
            status = str(item.get("addedOrReduced") or "").strip()
            if mode == "scrape_new_today" and saw_current and OLDER_PATTERN.match(status):
                stopped = True
                break
            seen.add(item["id"])
            saw_current = saw_current or status in CURRENT_STATUSES
            offer = candidate_offer(item, config)
            if offer is not None:
                offers.append(offer)
        if stopped or mode == "scrape_new_today" or pagination.get("next") is None:
            break
        index = int(pagination["next"])
    return Discovery(offers, len(seen), total, pages, stopped)

def scrape_new_today(session: requests.Session, config: ScraperConfig) -> Discovery:
    return discover_offers(session, config, "scrape_new_today")

def scrape_all(session: requests.Session, config: ScraperConfig) -> Discovery:
    return discover_offers(session, config, "scrape_all")

def _decode_flattened(values: list[object]) -> object:
    memo: dict[int, object] = {}
    def resolve(reference: object) -> object:
        if not isinstance(reference, int) or isinstance(reference, bool):
            return reference
        if reference < 0 or reference >= len(values):
            raise RuntimeError("Rightmove detail JSON contains an invalid reference")
        if reference in memo:
            return memo[reference]
        value = values[reference]
        if isinstance(value, dict):
            decoded: dict[str, object] = {}
            memo[reference] = decoded
            decoded.update({key: resolve(item) for key, item in value.items()})
            return decoded
        if isinstance(value, list):
            decoded_list: list[object] = []
            memo[reference] = decoded_list
            decoded_list.extend(resolve(item) for item in value)
            return decoded_list
        return value
    return resolve(0)

def parse_detail_model(html: str) -> dict[str, object]:
    start = html.find(PAGE_MODEL_MARKER)
    if start < 0:
        raise RuntimeError("Rightmove detail JSON was not found")
    envelope, _ = json.JSONDecoder().raw_decode(html[start + len(PAGE_MODEL_MARKER):].lstrip())
    if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), str):
        raise RuntimeError("Rightmove detail JSON envelope is invalid")
    values = json.loads(envelope["data"])
    if not isinstance(values, list):
        raise RuntimeError("Rightmove detail JSON data is invalid")
    model = _decode_flattened(values)
    if not isinstance(model, dict) or not isinstance(model.get("propertyData"), dict):
        raise RuntimeError("Rightmove property detail contract is invalid")
    return model["propertyData"]

def detail_offer(session: requests.Session, candidate: dict[str, object], config: ScraperConfig) -> dict[str, object] | None:
    response = session.get(str(candidate["link"]), timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = parse_detail_model(response.text)
    text = data.get("text") if isinstance(data.get("text"), dict) else {}
    address_data = data.get("address") if isinstance(data.get("address"), dict) else {}
    address = str(address_data.get("displayAddress") or candidate["address"]).strip()
    description = BeautifulSoup(str(text.get("description") or candidate.get("summary") or ""), "html.parser").get_text("\n", strip=True)
    if not description:
        raise RuntimeError(f"Missing Rightmove description for {candidate['link']}")
    if not location_allowed(address, config):
        raise RuntimeError(f"Rightmove detail location is excluded: {candidate['link']}")
    location = data.get("location") if isinstance(data.get("location"), dict) else {}
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    contact = data.get("contactInfo") if isinstance(data.get("contactInfo"), dict) else {}
    phones = contact.get("telephoneNumbers") if isinstance(contact.get("telephoneNumbers"), dict) else {}
    metadata = {
        "source": "rightmove", "status": candidate.get("status"),
        "latitude": location.get("latitude", candidate.get("latitude")),
        "longitude": location.get("longitude", candidate.get("longitude")),
        "bedrooms": data.get("bedrooms"), "bathrooms": data.get("bathrooms"),
        "property_type": data.get("propertySubType"),
        "key_features": data.get("keyFeatures") or [],
        "lettings": data.get("lettings") if isinstance(data.get("lettings"), dict) else {},
        "agent": {
            "name": customer.get("branchDisplayName") or candidate.get("agent_name"),
            "address": customer.get("displayAddress"),
            "phone": phones.get("localNumber") or candidate.get("agent_phone"),
        },
    }
    title = str(text.get("propertyPhrase") or candidate.get("title") or "Property").strip()
    return {"address": f"{title} — {address}", "rent": candidate["rent"], "link": candidate["link"], "description": description, "metadata": metadata}

def run() -> None:
    config = SCRAPER_CONFIG["rightmove"]
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
            if isinstance(metadata, dict) and metadata.get("source") == "rightmove":
                continue
            offer = detail_offer(session, candidate, config)
            if offer is None:
                print(f"Skipped unavailable listing {candidate['link']}")
                continue
            changed.append(offer)
            new_count += existing is None
            print(f"Retrieved {index}/{len(discovery.offers)} candidate details")
        if changed:
            store.upsert_many(changed)
        store.update_activity({str(offer["link"]) for offer in discovery.offers}, complete=mode == "scrape_all")
        print(f"Saved {new_count} new and enriched {len(changed) - new_count} existing listings")
