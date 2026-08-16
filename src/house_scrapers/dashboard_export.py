from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit

from dotenv import load_dotenv

from house_scrapers.filtering import COUPLES_RESULTS_BLOB, SELF_CONTAINED_RESULTS_BLOB
from house_scrapers.storage import archived_timestamp, open_offer_store

R2_OBJECT_KEY = "current.json"
DASHBOARD_PROPERTY_FIELDS = frozenset(
    {
        "id",
        "address",
        "rent",
        "link",
        "description",
        "source",
        "bike_minutes",
        "bike_distance_km",
        "couples_supported",
        "self_contained",
        "first_qualified_at",
        "archived",
    }
)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Dashboard property requires non-empty {field}")
    return value.strip()


def _number(value: object, field: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Dashboard property requires numeric {field}")
    if value < 0:
        raise ValueError(f"Dashboard property requires non-negative {field}")
    return value


def stable_property_id(source: str, link: str) -> str:
    source = _text(source, "source").lower()
    if not re.fullmatch(r"[a-z0-9_-]+", source):
        raise ValueError("Dashboard property source is invalid")
    parsed = urlsplit(_text(link, "link"))
    path_parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not path_parts:
        raise ValueError("Dashboard property link is invalid")
    source_listing_id = path_parts[-1]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", source_listing_id):
        raise ValueError("Dashboard property link has no stable listing ID")
    return f"{source}:{source_listing_id}"


def _dashboard_property(listing: Mapping[str, object]) -> dict[str, object]:
    metadata = listing.get("metadata")
    enrichment = listing.get("enrichment")
    if not isinstance(metadata, Mapping) or not isinstance(enrichment, Mapping):
        raise ValueError("Dashboard property requires metadata and enrichment")
    classification = enrichment.get("classification")
    if not isinstance(classification, Mapping):
        raise ValueError("Dashboard property requires classification")
    couples_supported = classification.get("couples_allowed")
    self_contained = classification.get("self_contained")
    if not isinstance(couples_supported, bool) or not isinstance(self_contained, bool):
        raise ValueError("Dashboard property classifications must be boolean")

    route = enrichment.get("bike_route")
    bike_minutes: int | float | None = None
    bike_distance_km: int | float | None = None
    if route is not None:
        if not isinstance(route, Mapping):
            raise ValueError("Dashboard property bike route is invalid")
        bike_minutes = _number(route.get("duration_minutes"), "bike_minutes")
        bike_distance_km = _number(route.get("distance_km"), "bike_distance_km")

    source = _text(metadata.get("source"), "source").lower()
    link = _text(listing.get("link"), "link")
    rent = _number(listing.get("rent"), "rent")
    if rent == 0:
        raise ValueError("Dashboard property rent must be greater than zero")
    return {
        "id": stable_property_id(source, link),
        "address": _text(listing.get("address"), "address"),
        "rent": rent,
        "link": link,
        "description": _text(listing.get("description"), "description"),
        "source": source,
        "bike_minutes": bike_minutes,
        "bike_distance_km": bike_distance_km,
        "couples_supported": couples_supported,
        "self_contained": self_contained,
        "archived": _text(listing.get("archived"), "archived"),
        "first_qualified_at": _text(
            listing.get("first_qualified_at"), "first_qualified_at"
        ),
    }


def build_snapshot(
    couples_gold: Iterable[Mapping[str, object]],
    self_contained_gold: Iterable[Mapping[str, object]],
    generated_at: str,
) -> dict[str, object]:
    properties: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for listing in (*couples_gold, *self_contained_gold):
        if listing.get("currently_eligible") is not True:
            continue
        item = _dashboard_property(listing)
        property_id = str(item["id"])
        if property_id in seen_ids:
            raise ValueError(f"Duplicate dashboard property ID: {property_id}")
        seen_ids.add(property_id)
        properties.append(item)
    properties.sort(key=lambda item: (item["rent"], item["id"]))
    snapshot: dict[str, object] = {
        "generated_at": _text(generated_at, "generated_at"),
        "properties": properties,
    }
    validate_snapshot(snapshot)
    return snapshot


def validate_snapshot(snapshot: Mapping[str, object]) -> None:
    if set(snapshot) != {"generated_at", "properties"}:
        raise ValueError("Dashboard snapshot has unexpected fields")
    _text(snapshot.get("generated_at"), "generated_at")
    properties = snapshot.get("properties")
    if not isinstance(properties, list):
        raise ValueError("Dashboard snapshot properties must be a list")
    seen_ids: set[str] = set()
    for item in properties:
        if not isinstance(item, Mapping) or set(item) != DASHBOARD_PROPERTY_FIELDS:
            raise ValueError("Dashboard property has unexpected fields")
        property_id = _text(item.get("id"), "id")
        if property_id in seen_ids:
            raise ValueError(f"Duplicate dashboard property ID: {property_id}")
        seen_ids.add(property_id)


def upload_snapshot(snapshot: Mapping[str, object], client: object, bucket: str) -> None:
    validate_snapshot(snapshot)
    body = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    client.put_object(
        Bucket=_text(bucket, "R2_BUCKET"),
        Key=R2_OBJECT_KEY,
        Body=body,
        ContentType="application/json",
        CacheControl="no-store",
    )


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is required when R2 export is enabled")
    return value


def r2_client_from_environment() -> tuple[object, str]:
    import boto3

    account_id = _required_environment("R2_ACCOUNT_ID")
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=_required_environment("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_required_environment("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )
    return client, _required_environment("R2_BUCKET")


def export_enabled() -> bool:
    return os.getenv("R2_EXPORT_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def run() -> None:
    load_dotenv()
    if not export_enabled():
        print("Dashboard R2 export disabled")
        return
    couples = open_offer_store(COUPLES_RESULTS_BLOB).offers
    self_contained = open_offer_store(SELF_CONTAINED_RESULTS_BLOB).offers
    snapshot = build_snapshot(couples, self_contained, archived_timestamp())
    client, bucket = r2_client_from_environment()
    upload_snapshot(snapshot, client, bucket)
    print(
        f"Exported {len(snapshot['properties'])} dashboard properties to R2 {R2_OBJECT_KEY}"
    )
