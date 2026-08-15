from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

from dotenv import load_dotenv

from house_scrapers.enrichment import ENRICHED_BLOB
from house_scrapers.storage import archived_timestamp, open_offer_store

COUPLES_RESULTS_BLOB = "gold/couples_results.json"
SELF_CONTAINED_RESULTS_BLOB = "gold/self_contained_results.json"


def filter_listings(
    listings: Iterable[Mapping[str, object]], max_bike_minutes: float
) -> tuple[list[Mapping[str, object]], list[Mapping[str, object]]]:
    couples_results = []
    self_contained_results = []
    for listing in listings:
        if listing.get("active") is False:
            continue
        enrichment = listing.get("enrichment")
        if not isinstance(enrichment, Mapping):
            continue
        route = enrichment.get("bike_route")
        duration = route.get("duration_minutes") if isinstance(route, Mapping) else None
        if isinstance(duration, (int, float)) and duration > max_bike_minutes:
            continue

        classification = enrichment.get("classification")
        if not isinstance(classification, Mapping):
            continue
        if classification.get("couples_allowed") is True:
            couples_results.append(listing)
        elif classification.get("self_contained") is True:
            self_contained_results.append(listing)
    return couples_results, self_contained_results


def update_gold(
    existing: Iterable[Mapping[str, object]],
    current: Iterable[Mapping[str, object]],
    timestamp: str,
) -> list[dict[str, object]]:
    gold = []
    positions: dict[str, int] = {}
    for listing in existing:
        item = dict(listing)
        item["currently_eligible"] = False
        link = str(item.get("link") or "")
        if link and link not in positions:
            positions[link] = len(gold)
            gold.append(item)

    for listing in current:
        item = dict(listing)
        link = str(item.get("link") or "")
        if not link:
            continue
        previous = gold[positions[link]] if link in positions else None
        item["first_qualified_at"] = (
            previous.get("first_qualified_at") if previous else timestamp
        )
        item["currently_eligible"] = True
        if previous is None:
            positions[link] = len(gold)
            gold.append(item)
        else:
            gold[positions[link]] = item
    return gold


def run() -> None:
    load_dotenv()
    max_bike_minutes = float(os.getenv("MAX_BIKE_DURATION_MINUTES", "50"))
    if max_bike_minutes <= 0:
        raise ValueError("MAX_BIKE_DURATION_MINUTES must be greater than zero")

    source = open_offer_store(ENRICHED_BLOB)
    couples, self_contained = filter_listings(source.offers, max_bike_minutes)
    timestamp = archived_timestamp()
    couples_store = open_offer_store(COUPLES_RESULTS_BLOB)
    self_contained_store = open_offer_store(SELF_CONTAINED_RESULTS_BLOB)
    couples_gold = update_gold(couples_store.offers, couples, timestamp)
    self_contained_gold = update_gold(
        self_contained_store.offers, self_contained, timestamp
    )
    couples_store.replace_all(couples_gold)
    self_contained_store.replace_all(self_contained_gold)
    print(
        f"Filtered {len(source.offers)} listings -> "
        f"{len(couples)} couples, {len(self_contained)} self-contained "
        f"({len(couples_gold) + len(self_contained_gold)} registered in Gold)"
    )
