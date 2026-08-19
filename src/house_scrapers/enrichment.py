from __future__ import annotations

import copy
import json
import os
import re
import time
from collections.abc import Mapping
from importlib.resources import files

import requests
from dotenv import load_dotenv

from house_scrapers.storage import open_offer_store

DESTINATION_ID = "mathematical_institute_oxford_v1"
DESTINATION = {"latitude": 51.760869, "longitude": -1.263844}
RAW_BLOBS = (
    "dailyinfo/properties.json",
    "finders/properties.json",
    "onthemarket/properties.json",
    "rightmove/properties.json",
    "scottfraser/properties.json",
    "taylors/properties.json",
    "spareroom/properties.json",
)
ENRICHED_BLOB = "enriched/properties.json"
POSTCODES_URL = "https://api.postcodes.io/postcodes"
OUTCODES_URL = "https://api.postcodes.io/outcodes"
OUTCODE_RE = re.compile(r"\b(OX\d{1,2}[A-Z]?)\b", re.IGNORECASE)
ROUTES_URL = "https://api.openrouteservice.org/v2/directions/cycling-regular/json"
POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.IGNORECASE)
ROUTE_INTERVAL_SECONDS = 1.6
KEYWORDS = json.loads(
    files("house_scrapers").joinpath("data/keywords.json").read_text(encoding="utf-8")
)


class RoutingSession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self._last_route_request = 0.0

    def post(self, url: str, **kwargs: object) -> requests.Response:
        for attempt in range(2):
            delay = ROUTE_INTERVAL_SECONDS - (time.monotonic() - self._last_route_request)
            if delay > 0:
                time.sleep(delay)
            response = super().post(url, **kwargs)
            self._last_route_request = time.monotonic()
            if response.status_code != 429 or attempt:
                return response
            time.sleep(60)
        raise AssertionError("unreachable")


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _nested_value(value: object, key: str) -> bool | None:
    if isinstance(value, Mapping):
        if key in value and isinstance(value[key], bool):
            return value[key]
        for nested in value.values():
            result = _nested_value(nested, key)
            if result is not None:
                return result
    if isinstance(value, list):
        for nested in value:
            result = _nested_value(nested, key)
            if result is not None:
                return result
    return None


def _searchable_text(listing: Mapping[str, object]) -> str:
    parts: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, Mapping):
            for key, nested in value.items():
                parts.append(str(key).replace("_", " "))
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    for field in ("title", "header", "address", "description", "metadata"):
        collect(listing.get(field))
    return " ".join(parts).casefold()


def _matching_term(text: str, terms: list[str]) -> str | None:
    for term in terms:
        pattern = rf"(?<!\w){re.escape(term.casefold())}(?!\w)"
        if re.search(pattern, text):
            return term
    return None


def _classify(
    text: str,
    name: str,
    structured: bool | None,
    output_name: str,
) -> tuple[bool, str]:
    terms = KEYWORDS[name]
    if structured is False:
        return False, f"metadata:{output_name}=false"
    if structured is True:
        return True, f"metadata:{output_name}=true"
    negative = _matching_term(text, terms["negative"])
    if negative:
        return False, f"negative:{negative}"
    positive = _matching_term(text, terms["positive"])
    if positive:
        return True, f"positive:{positive}"
    return False, "no_positive_match"


def classify_listing(listing: Mapping[str, object]) -> dict[str, object]:
    text = _searchable_text(listing)
    couples, couples_reason = _classify(
        text,
        "couples",
        _nested_value(listing.get("metadata"), "couples_allowed"),
        "couples_allowed",
    )
    self_contained, self_contained_reason = _classify(
        text,
        "self_contained",
        _nested_value(listing.get("metadata"), "self_contained"),
        "self_contained",
    )
    return {
        "couples_allowed": couples,
        "couples_reason": couples_reason,
        "self_contained": self_contained,
        "self_contained_reason": self_contained_reason,
    }


def complete_postcode(listing: Mapping[str, object]) -> str | None:
    metadata = listing.get("metadata")
    candidates = []
    if isinstance(metadata, Mapping):
        candidates.append(metadata.get("postcode"))
    candidates.append(listing.get("address"))
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        match = POSTCODE_RE.search(candidate)
        if match:
            compact = re.sub(r"\s+", "", match.group(1)).upper()
            return f"{compact[:-3]} {compact[-3:]}"
    return None


def outward_postcode(listing: Mapping[str, object]) -> str | None:
    metadata = listing.get("metadata")
    candidates = []
    if isinstance(metadata, Mapping):
        candidates.append(metadata.get("postcode"))
    candidates.extend((listing.get("address"), listing.get("description")))
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        match = OUTCODE_RE.search(candidate)
        if match:
            return match.group(1).upper()

    return None

def get_coordinates(
    listing: Mapping[str, object], session: requests.Session
) -> dict[str, object] | None:
    metadata = listing.get("metadata")
    if isinstance(metadata, Mapping):
        latitude = _number(metadata.get("latitude"))
        longitude = _number(metadata.get("longitude"))
        if latitude is not None and longitude is not None:
            return {
                "latitude": latitude,
                "longitude": longitude,
                "method": "source_metadata",
            }

    postcode = complete_postcode(listing)
    if postcode is None:
        metadata = listing.get("metadata")
        source = metadata.get("source") if isinstance(metadata, Mapping) else None
        postcode = outward_postcode(listing) if source == "onthemarket" else None
        if postcode is None:
            return None
        response = session.get(f"{OUTCODES_URL}/{postcode}", timeout=20)
        method = "postcode_outcode"
    else:
        response = session.get(
            f"{POSTCODES_URL}/{postcode.replace(' ', '')}", timeout=20
        )
        method = "postcode"
    response.raise_for_status()
    result = response.json().get("result")
    if not isinstance(result, Mapping):
        return None
    latitude = _number(result.get("latitude"))
    longitude = _number(result.get("longitude"))
    if latitude is None or longitude is None:
        return None
    return {
        "latitude": latitude,
        "longitude": longitude,
        "method": method,
        "postcode": postcode,
        **({"approximate": True} if method == "postcode_outcode" else {}),
    }


def get_bike_route(
    source: Mapping[str, object],
    destination: Mapping[str, object],
    session: requests.Session,
    api_key: str,
) -> dict[str, object]:
    response = session.post(
        ROUTES_URL,
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        json={
            "coordinates": [
                [source["longitude"], source["latitude"]],
                [destination["longitude"], destination["latitude"]],
            ]
        },
        timeout=30,
    )
    response.raise_for_status()
    summary = response.json()["routes"][0]["summary"]
    return {
        "duration_minutes": round(float(summary["duration"]) / 60, 1),
        "distance_km": round(float(summary["distance"]) / 1000, 2),
        "destination": DESTINATION_ID,
    }


def enrich_listing(
    listing: Mapping[str, object],
    previous: Mapping[str, object] | None,
    session: requests.Session,
    api_key: str,
    postcode_cache: dict[str, dict[str, object] | None],
    route_cache: dict[tuple[float, float, str], dict[str, object]] | None = None,
) -> dict[str, object]:
    item = copy.deepcopy(dict(listing))
    classification = classify_listing(listing)
    metadata = listing.get("metadata")
    source = metadata.get("source") if isinstance(metadata, Mapping) else None
    location_key = complete_postcode(listing)
    if location_key is None and source == "onthemarket":
        location_key = outward_postcode(listing)
    if location_key and location_key in postcode_cache:
        location = postcode_cache[location_key]
    else:
        location = get_coordinates(listing, session)
        if location_key:
            postcode_cache[location_key] = location

    if location is None:
        item["enrichment"] = {
            "location": {"method": "unavailable"},
            "classification": classification,
        }
        return item

    route_cache = route_cache if route_cache is not None else {}
    route_key = (
        float(location["latitude"]),
        float(location["longitude"]),
        DESTINATION_ID,
    )
    previous_enrichment = previous.get("enrichment") if previous else None
    if isinstance(previous_enrichment, Mapping):
        previous_location = previous_enrichment.get("location")
        previous_route = previous_enrichment.get("bike_route")
        if (
            previous_location == location
            and isinstance(previous_route, Mapping)
            and previous_route.get("destination") == DESTINATION_ID
        ):
            item["enrichment"] = {
                "location": location,
                "bike_route": copy.deepcopy(dict(previous_route)),
                "classification": classification,
            }
            route_cache[route_key] = copy.deepcopy(dict(previous_route))
            return item

    route = route_cache.get(route_key)
    if route is None:
        route = get_bike_route(location, DESTINATION, session, api_key)
        route_cache[route_key] = route
    item["enrichment"] = {
        "location": location,
        "bike_route": copy.deepcopy(route),
        "classification": classification,
    }
    return item


def run() -> None:
    load_dotenv()
    api_key = os.getenv("OPENROUTE_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTE_API_KEY is required")

    output = open_offer_store(ENRICHED_BLOB)
    previous_by_link = {
        str(item["link"]): item for item in output.offers if item.get("link")
    }
    session = RoutingSession()
    postcode_cache: dict[str, dict[str, object] | None] = {}
    route_cache: dict[tuple[float, float, str], dict[str, object]] = {}
    enriched = []
    for blob_name in RAW_BLOBS:
        source = open_offer_store(blob_name)
        for listing in source.offers:
            if listing.get("active") is False:
                continue
            link = str(listing.get("link") or "")
            enriched.append(
                enrich_listing(
                    listing,
                    previous_by_link.get(link),
                    session,
                    api_key,
                    postcode_cache,
                    route_cache,
                )
            )

    output.replace_all(enriched)
    routed = sum("bike_route" in item["enrichment"] for item in enriched)
    print(f"Enriched {len(enriched)} listings ({routed} with bike routes) -> {ENRICHED_BLOB}")
