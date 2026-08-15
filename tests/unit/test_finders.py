import json
from datetime import datetime
from datetime import datetime, timezone

import pytest

from house_scrapers.config import ScraperConfig
from house_scrapers.scrapers.finders import (
    absolute_url, detail_offer, discover_offers, parse_embedded_json, parse_listing_intro,
)
from house_scrapers.storage import BlobOfferStore


def test_parse_listing_intro_preserves_original_contract():
    assert parse_listing_intro("£1,095 pcm, 10 High Street, Oxford") == (1095, "10 High Street, Oxford")


@pytest.mark.parametrize("intro", ["POA", "£950 pw, Oxford", "No price shown"])
def test_parse_listing_intro_rejects_unexpected_formats(intro):
    assert parse_listing_intro(intro) is None



def test_absolute_url_supports_relative_and_absolute_links():
    assert absolute_url("/property/123") == "https://www.finders.co.uk/property/123"
    assert absolute_url("https://example.test/123") == "https://example.test/123"


class FakeDownload:
    def __init__(self, data):
        self.data = data

    def readall(self):
        return self.data


class FakeBlobClient:
    def __init__(self, data=None):
        self.data = data

    def exists(self):
        return self.data is not None

    def download_blob(self):
        return FakeDownload(self.data)

    def upload_blob(self, data, *, overwrite):
        assert overwrite is True
        self.data = data


def test_blob_store_round_trip():
    offer = {"link": "https://example.test/1", "address": "1 Test Road", "rent": 900}
    blob = FakeBlobClient()
    store = BlobOfferStore(blob)

    assert not store.address_exists("1 Test Road")
    store.save(offer)

    assert store.address_exists("1 Test Road")
    saved = json.loads(blob.data)
    saved[0].pop("archived")
    assert saved == [offer]


def test_blob_store_loads_existing_offers():
    blob = FakeBlobClient(b'[{"address": "Existing", "rent": 900, "link": "url"}]')
    assert BlobOfferStore(blob).address_exists("Existing")


def test_blob_store_saves_many_with_one_upload():
    blob = FakeBlobClient()
    store = BlobOfferStore(blob)
    store.save_many([
        {"address": "First", "rent": 800, "link": "one"},
        {"address": "Second", "rent": 900, "link": "two"},
    ])
    assert len(json.loads(blob.data)) == 2


def test_blob_store_upserts_by_link():
    blob = FakeBlobClient(b"[{\"address\": \"Old\", \"rent\": 900, \"link\": \"one\"}]")
    store = BlobOfferStore(blob)
    store.upsert_many([
        {"address": "New", "rent": 900, "link": "one", "metadata": {"source": "spareroom"}}
    ])
    saved = json.loads(blob.data)
    saved[0].pop("archived")
    assert saved == [
        {"address": "New", "rent": 900, "link": "one", "metadata": {"source": "spareroom"}}
    ]


def test_blob_store_replaces_all_offers():
    blob = FakeBlobClient(b'[{"address": "Old", "link": "old"}]')
    store = BlobOfferStore(blob)
    replacement = {"address": "Current", "link": "current", "archived": "existing"}
    store.replace_all([replacement])
    assert store.offers == [replacement]
    assert json.loads(blob.data) == [replacement]


def test_complete_activity_refresh_marks_unseen_offers_inactive():
    blob = FakeBlobClient(
        b'[{"link":"current","active":true},{"link":"gone","active":true}]'
    )
    store = BlobOfferStore(blob)
    store.update_activity({"current"}, complete=True)
    saved = {item["link"]: item for item in json.loads(blob.data)}
    assert saved["current"]["active"] is True
    assert "last_seen" in saved["current"]
    assert saved["gone"]["active"] is False
    assert "inactive_at" in saved["gone"]


def test_partial_activity_refresh_does_not_deactivate_unseen_offers():
    blob = FakeBlobClient(b'[{"link":"existing","active":true}]')
    store = BlobOfferStore(blob)
    store.update_activity(set(), complete=False)
    assert json.loads(blob.data)[0]["active"] is True


def test_parse_embedded_json_reads_homeflow_payload():
    html = "<script>var propertyData = {\"properties\":[{\"property_id\":1}],\"pagination\":{\"total_count\":1}}; Homeflow.set(\"properties\", propertyData.properties);</script>"
    assert parse_embedded_json(html, "var propertyData = ")["properties"][0]["property_id"] == 1


class SearchResponse:
    def __init__(self, payload, embedded=False):
        self.payload = payload
        self.text = "var propertyData = " + json.dumps(payload) + ";" if embedded else json.dumps(payload)
    def raise_for_status(self):
        pass
    def json(self):
        return self.payload

class SearchSession:
    def __init__(self, responses):
        self.responses = iter(responses)
    def get(self, url, timeout):
        return next(self.responses)

def property_record(property_id, created_at, rent=900, address="Oxford, OX1", postcode="OX1 1AA"):
    return {"property_id": property_id, "createDate": created_at, "priceValue": rent, "url": f"/properties/{property_id}/lettings/P{property_id}", "addressWithCommas": address, "postcode": postcode, "bedrooms": 1, "type": "flat"}

def test_new_today_stops_at_first_older_creation_date():
    payload = {"properties": [property_record(1, "2026-08-15T09:00:00+00:00"), property_record(2, "2026-08-14T21:30:00+00:00")], "pagination": {"total_count": 2, "has_next_page": False}}
    config = ScraperConfig(1200, True, ("banbury", "didcot"))
    result = discover_offers(SearchSession([SearchResponse(payload, True)]), config, "scrape_new_today", datetime(2026, 8, 15, 12, tzinfo=timezone.utc))
    assert [offer["link"] for offer in result.offers] == ["https://www.finders.co.uk/properties/1/lettings/P1"]
    assert result.stopped_at_older

def test_scrape_all_follows_json_pagination_and_verifies_total():
    first = {"properties": [property_record(1, "2026-08-15T09:00:00+00:00")], "pagination": {"total_count": 2, "has_next_page": True}}
    second = {"properties": [property_record(2, "2026-08-14T09:00:00+00:00")], "pagination": {"total_count": 2, "has_next_page": False}}
    config = ScraperConfig(1200, True, ("banbury", "didcot"))
    result = discover_offers(SearchSession([SearchResponse(first, True), SearchResponse(second)]), config, "scrape_all")
    assert result.seen_adverts == result.total_adverts == 2
    assert result.pages == 2


def test_detail_skips_stale_404_property():
    class MissingResponse:
        status_code = 404
        def raise_for_status(self):
            raise AssertionError("404 should be handled")
    config = ScraperConfig(1200, True, ())
    candidate = {"link": "https://example.test/missing", "address": "Oxford", "rent": 900}
    assert detail_offer(SearchSession([MissingResponse()]), candidate, config) is None


def test_blob_store_adds_utc_archived_timestamp():
    blob = FakeBlobClient()
    store = BlobOfferStore(blob)
    store.save({"address": "Timed", "rent": 900, "link": "timed"})
    archived = json.loads(blob.data)[0]["archived"]
    assert datetime.fromisoformat(archived.replace("Z", "+00:00")).utcoffset().total_seconds() == 0
