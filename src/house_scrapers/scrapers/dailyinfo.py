from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from house_scrapers.config import SCRAPER_CONFIG, ScraperConfig, oxfordshire_location_allowed
from house_scrapers.storage import open_offer_store

SITE_URL = "https://www.dailyinfo.co.uk"
SEARCH_URLS = (f"{SITE_URL}/rooms-to-let", f"{SITE_URL}/homes-to-let")
STORAGE_BLOB = "dailyinfo/properties.json"
MODES = {"scrape_new_today", "scrape_all"}
PRICE_PATTERN = re.compile(r"£([\d,.]+)\s*(PCM|PW)", re.IGNORECASE)
MAP_PATTERN = re.compile(r"L\.marker\(\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\]\).*?\.bindPopup\(([\x27\x22])(.*?)\3\)", re.DOTALL)

@dataclass(frozen=True)
class Discovery:
    offers: list[dict[str, object]]
    seen_adverts: int
    pages: int

def http_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; HouseScrapers/0.1)"
    return session

def monthly_rent(price: str) -> int | None:
    match = PRICE_PATTERN.search(price)
    if match is None:
        return None
    amount = float(match.group(1).replace(",", ""))
    return round(amount * 52 / 12) if match.group(2).upper() == "PW" else round(amount)

def canonical_url(href: str) -> str:
    parts = urlsplit(urljoin(SITE_URL, href))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

def ordinal_day(moment: datetime) -> str:
    day = moment.day
    suffix = "th" if 10 < day % 100 < 14 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{moment:%a} {day}{suffix}"

def parse_card(container: object, config: ScraperConfig) -> dict[str, object] | None:
    link = container.select_one("a.overlaid-link[href]")
    title_element = container.select_one(".a-text")
    rent_element = container.select_one(".a-rent")
    if link is None or title_element is None or rent_element is None:
        return None
    href = str(link.get("href") or "")
    if not re.fullmatch(r"/(?:rooms|homes)-to-let/\d+", href):
        return None
    title = title_element.get_text(" ", strip=True)
    location = " ".join(x.get_text(" ", strip=True) for x in container.select(".a-postcode"))
    rent = monthly_rent(rent_element.get_text(" ", strip=True))
    if not title or rent is None or rent >= config.max_rent:
        return None
    if not oxfordshire_location_allowed(f"{title} {location}", config):
        return None
    timestamp = container.select_one(".a-time-placed[data-timestamp]")
    return {"title": title, "card_location": location, "rent": rent, "link": canonical_url(href), "published_timestamp": int(timestamp["data-timestamp"]) if timestamp else None}

def discover_offers(session: requests.Session, config: ScraperConfig, mode: str, now: datetime | None = None) -> Discovery:
    if mode not in MODES:
        allowed = ", ".join(sorted(MODES))
        raise ValueError(f"DAILYINFO_MODE must be one of: {allowed}")
    today = ordinal_day(now or datetime.now(ZoneInfo("Europe/London")))
    seen: set[str] = set()
    offers: list[dict[str, object]] = []
    for search_url in SEARCH_URLS:
        response = session.get(search_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        active = mode == "scrape_all"
        encountered_header = False
        for element in soup.select(".aboard-day-separator, .a-container"):
            if "aboard-day-separator" in (element.get("class") or []):
                header = element.get_text(" ", strip=True)
                if mode == "scrape_new_today":
                    if header == today:
                        active = True
                    elif active or not encountered_header:
                        break
                encountered_header = True
                continue
            if mode == "scrape_new_today" and encountered_header and not active:
                continue
            link = element.select_one("a.overlaid-link[href]")
            if link is None:
                continue
            canonical = canonical_url(str(link.get("href") or ""))
            if canonical in seen:
                continue
            seen.add(canonical)
            offer = parse_card(element, config)
            if offer is not None:
                offers.append(offer)
    return Discovery(offers, len(seen), len(SEARCH_URLS))

def scrape_new_today(session: requests.Session, config: ScraperConfig) -> Discovery:
    return discover_offers(session, config, "scrape_new_today")

def scrape_all(session: requests.Session, config: ScraperConfig) -> Discovery:
    return discover_offers(session, config, "scrape_all")

def map_location(soup: BeautifulSoup) -> dict[str, object] | None:
    for script in soup.select("script"):
        match = MAP_PATTERN.search(script.string or script.get_text())
        if match is None:
            continue
        postcode = re.sub(r"\\u([0-9a-fA-F]{4})", lambda value: chr(int(value.group(1), 16)), match.group(4))
        return {"postcode": html.unescape(postcode).strip(), "latitude": float(match.group(1)), "longitude": float(match.group(2))}
    return None

def detail_offer(session: requests.Session, candidate: dict[str, object], config: ScraperConfig) -> dict[str, object]:
    response = session.get(str(candidate["link"]), timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    description_element = soup.select_one(".adPropertyDescription") or soup.select_one(".shortAvtHtml")
    if description_element is None or not description_element.get_text(" ", strip=True):
        raise RuntimeError("Missing description for {}".format(candidate["link"]))
    title_element = soup.select_one(".shortAvtHtml")
    title = title_element.get_text(" ", strip=True) if title_element else str(candidate["title"])
    values = soup.select(".a-attributes .value")
    detail_location = values[1].get_text(" ", strip=True) if len(values) > 1 else ""
    location = map_location(soup)
    address_location = str(location["postcode"]) if location else detail_location or str(candidate["card_location"])
    if not oxfordshire_location_allowed(f"{title} {address_location}", config):
        raise RuntimeError("DailyInfo detail location is outside configured area: {}".format(candidate["link"]))
    metadata: dict[str, object] = {"source": "dailyinfo", "published_timestamp": candidate.get("published_timestamp")}
    if location:
        metadata.update(location)
    return {"address": f"{title} — {address_location}", "rent": candidate["rent"], "link": candidate["link"], "description": description_element.get_text(chr(10), strip=True), "metadata": metadata}

def run() -> None:
    config = SCRAPER_CONFIG["dailyinfo"]
    mode = config.mode or "scrape_new_today"
    store = open_offer_store(STORAGE_BLOB)
    registered = {str(offer.get("link")): offer for offer in store.offers}
    with http_session() as session:
        discovery = discover_offers(session, config, mode)
        print(f"Scanned {discovery.seen_adverts} unique adverts across {discovery.pages} pages")
        changed: list[dict[str, object]] = []
        new_count = 0
        for index, candidate in enumerate(discovery.offers, start=1):
            existing = registered.get(str(candidate["link"]))
            existing_metadata = existing.get("metadata") if existing else None
            if isinstance(existing_metadata, dict) and existing_metadata.get("source") == "dailyinfo":
                continue
            offer = detail_offer(session, candidate, config)
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
