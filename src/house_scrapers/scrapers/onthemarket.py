from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from house_scrapers.config import SCRAPER_CONFIG, ScraperConfig, location_allowed
from house_scrapers.storage import open_offer_store

SITE_URL = "https://www.onthemarket.com"
SEARCH_URL = f"{SITE_URL}/to-rent/property/oxfordshire/"
STORAGE_BLOB = "onthemarket/properties.json"
MODES = {"scrape_new_today", "scrape_all"}
PRICE_PATTERN = re.compile(r"£([\d,]+)\s+pcm", re.IGNORECASE)
CARD_PATTERN = re.compile(r"£([\d,]+)\s+pcm(?:[^\n]*)\n([^\n]+)")
STOP_STATUSES = {"Added yesterday", "Recently added", "Added < 7 days"}

@dataclass(frozen=True)
class Discovery:
    offers: list[dict[str, object]]
    seen_adverts: int
    pages: int
    stopped_at_older: bool

def http_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    return session

def parse_listing_card(text: str) -> tuple[int, str] | None:
    match = CARD_PATTERN.search(text)
    if match is None:
        return None
    return int(match.group(1).replace(",", "")), match.group(2).strip()

def canonical_url(href: str) -> str:
    parts = urlsplit(urljoin(SITE_URL, href))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

def search_url(max_rent: int, page: int) -> str:
    query = {"max-price": max_rent, "sort-field": "update_date"}
    if page > 1:
        query["page"] = page
    return f"{SEARCH_URL}?{urlencode(query)}"

def card_status(card: object) -> str | None:
    texts = {text.strip() for text in card.stripped_strings}
    for status in ("Added today", "Added yesterday", "Recently added", "Added < 7 days"):
        if status in texts:
            return status
    return None

def parse_card(card: object, config: ScraperConfig) -> dict[str, object] | None:
    address_element = card.select_one("address[itemprop=address]")
    if address_element is None:
        return None
    link = next((a for a in card.select("a[href*=\"/details/\"]") if PRICE_PATTERN.search(a.get_text(" ", strip=True))), None)
    if link is None:
        return None
    price_match = PRICE_PATTERN.search(link.get_text(" ", strip=True))
    href = str(link.get("href") or "")
    if price_match is None or not re.fullmatch(r"/details/\d+/", href):
        return None
    rent = int(price_match.group(1).replace(",", ""))
    address = address_element.get_text(" ", strip=True)
    if rent >= config.max_rent or not location_allowed(address, config):
        return None
    return {"address": address, "rent": rent, "link": canonical_url(href), "status": card_status(card)}

def discover_offers(session: requests.Session, config: ScraperConfig, mode: str) -> Discovery:
    if mode not in MODES:
        allowed = ", ".join(sorted(MODES))
        raise ValueError(f"ONTHEMARKET_MODE must be one of: {allowed}")
    seen: set[str] = set()
    offers: list[dict[str, object]] = []
    page_number = 1
    last_page = 1
    while page_number <= last_page:
        response = session.get(search_url(config.max_rent, page_number), timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        if page_number == 1:
            page_numbers = [int(match.group(1)) for a in soup.select("a[href]") if (match := re.search(r"[?&]page=(\d+)", str(a.get("href"))))]
            last_page = max(page_numbers, default=1)
        cards = soup.select("article[data-component=search-result-property-card]")
        if not cards and page_number == 1:
            raise RuntimeError("OnTheMarket returned no property cards")
        for card in cards:
            status = card_status(card)
            if mode == "scrape_new_today" and status in STOP_STATUSES:
                return Discovery(offers, len(seen), page_number, True)
            detail = card.select_one("a[href*=\"/details/\"]")
            if detail is None:
                continue
            link = canonical_url(str(detail.get("href") or ""))
            if link in seen:
                continue
            seen.add(link)
            offer = parse_card(card, config)
            if offer is not None:
                offers.append(offer)
        if mode == "scrape_new_today":
            break
        page_number += 1
    return Discovery(offers, len(seen), min(page_number, last_page), False)

def scrape_new_today(session: requests.Session, config: ScraperConfig) -> Discovery:
    return discover_offers(session, config, "scrape_new_today")

def scrape_all(session: requests.Session, config: ScraperConfig) -> Discovery:
    return discover_offers(session, config, "scrape_all")

def parse_agent(soup: BeautifulSoup) -> dict[str, str] | None:
    for phone in soup.select("a[href^=tel]"):
        block = phone.find_parent("div", class_=lambda value: value and "border" in value.split())
        if block is None:
            continue
        name = block.select_one(".text-sm.font-bold")
        address = block.select_one(".text-xs.text-slate")
        if name is None:
            continue
        return {
            "name": name.get_text(" ", strip=True),
            "address": address.get_text(" ", strip=True) if address else "",
            "phone": phone.get_text(" ", strip=True),
        }
    return None

def detail_offer(session: requests.Session, candidate: dict[str, object], config: ScraperConfig) -> dict[str, object]:
    response = session.get(str(candidate["link"]), timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title_element = soup.select_one("[data-test=property-title]")
    description_element = next((x for x in soup.select("[itemprop=description]") if x.name != "meta" and x.get_text(" ", strip=True)), None)
    if title_element is None or description_element is None:
        raise RuntimeError("Missing OnTheMarket detail contract for {}".format(candidate["link"]))
    address_element = title_element.find_next_sibling("div")
    detail_address = address_element.get_text(" ", strip=True) if address_element else str(candidate["address"])
    if not location_allowed(detail_address, config):
        raise RuntimeError("OnTheMarket detail location is excluded: {}".format(candidate["link"]))
    metadata: dict[str, object] = {"source": "onthemarket", "status": candidate.get("status")}
    agent = parse_agent(soup)
    if agent:
        metadata["agent"] = agent
    return {
        "address": "{} — {}".format(title_element.get_text(" ", strip=True), detail_address),
        "rent": candidate["rent"],
        "link": candidate["link"],
        "description": description_element.get_text(chr(10), strip=True),
        "metadata": metadata,
    }

def run() -> None:
    config = SCRAPER_CONFIG["onthemarket"]
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
            if isinstance(existing_metadata, dict) and existing_metadata.get("source") == "onthemarket":
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
