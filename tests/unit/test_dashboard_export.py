import json

import pytest

from house_scrapers.dashboard_export import (
    DASHBOARD_PROPERTY_FIELDS,
    build_snapshot,
    run,
    stable_property_id,
    upload_snapshot,
)


def gold_listing(source, link, *, couples=True, self_contained=False, rent=900):
    return {
        "address": "Example property",
        "rent": rent,
        "link": link,
        "description": "Public description",
        "currently_eligible": True,
        "first_qualified_at": "2026-08-15T15:00:00Z",
        "archived": "2026-08-16T09:30:00Z",
        "metadata": {
            "source": source,
            "secret": "must-not-leak",
            "debug": {"raw": "must-not-leak"},
        },
        "enrichment": {
            "bike_route": {"duration_minutes": 15.0, "distance_km": 4.2},
            "classification": {
                "couples_allowed": couples,
                "self_contained": self_contained,
                "couples_reason": "internal",
            },
        },
    }


@pytest.mark.parametrize(
    ("source", "link", "expected"),
    [
        ("dailyinfo", "https://www.dailyinfo.co.uk/rooms-to-let/2999865", "dailyinfo:2999865"),
        ("finders", "https://www.finders.co.uk/properties/21962858/lettings/P150315", "finders:P150315"),
        ("onthemarket", "https://www.onthemarket.com/details/20124345/", "onthemarket:20124345"),
        ("spareroom", "https://www.spareroom.co.uk/flatshare/oxfordshire/oxford/15282368", "spareroom:15282368"),
    ],
)
def test_stable_property_ids_use_source_listing_ids(source, link, expected):
    assert stable_property_id(source, link) == expected


def test_snapshot_combines_all_sources_with_public_schema_only():
    listings = [
        gold_listing("dailyinfo", "https://example.test/1", rent=800),
        gold_listing("finders", "https://example.test/2", rent=700),
        gold_listing("onthemarket", "https://example.test/3", rent=1000),
        gold_listing("spareroom", "https://example.test/4", rent=600),
    ]
    snapshot = build_snapshot(listings, [], "2026-08-16T10:00:00Z")
    assert snapshot["generated_at"] == "2026-08-16T10:00:00Z"
    assert [item["source"] for item in snapshot["properties"]] == [
        "spareroom",
        "finders",
        "dailyinfo",
        "onthemarket",
    ]
    assert all(set(item) == DASHBOARD_PROPERTY_FIELDS for item in snapshot["properties"])
    serialized = json.dumps(snapshot)
    assert "must-not-leak" not in serialized
    assert "secret" not in serialized
    assert "debug" not in serialized
    assert "couples_reason" not in serialized


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item.pop("link"),
        lambda item: item.update(rent="invalid"),
        lambda item: item.update(metadata={}),
        lambda item: item.update(enrichment={}),
    ],
)
def test_malformed_current_gold_records_are_rejected(mutation):
    item = gold_listing("spareroom", "https://example.test/123")
    mutation(item)
    with pytest.raises(ValueError):
        build_snapshot([item], [], "2026-08-16T10:00:00Z")


def test_ineligible_historical_gold_records_are_not_exported():
    item = {"currently_eligible": False, "internal": "history"}
    assert build_snapshot([item], [], "2026-08-16T10:00:00Z")["properties"] == []


class FakeR2:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


def test_upload_writes_one_fully_constructed_current_json_object():
    snapshot = build_snapshot(
        [gold_listing("spareroom", "https://example.test/123")],
        [],
        "2026-08-16T10:00:00Z",
    )
    client = FakeR2()
    upload_snapshot(snapshot, client, "housing-gold")
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["Bucket"] == "housing-gold"
    assert call["Key"] == "current.json"
    assert call["ContentType"] == "application/json"
    assert json.loads(call["Body"]) == snapshot


def test_disabled_run_does_not_open_gold_or_r2(monkeypatch, capsys):
    monkeypatch.delenv("R2_EXPORT_ENABLED", raising=False)
    monkeypatch.setattr(
        "house_scrapers.dashboard_export.open_offer_store",
        lambda name: pytest.fail(f"unexpected Gold access: {name}"),
    )
    run()
