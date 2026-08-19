import json
from datetime import datetime, timezone

import pytest
from house_scrapers.config import ScraperConfig
from house_scrapers.scrapers.taylors import (
    detail_offer, discover_offers, parse_embedded_json,
)

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
    return {"property_id": property_id, "createDate": created_at, "priceValue": rent, "url": f"/properties/{property_id}/lettings/P{property_id}", "addressWithCommas": address, "postcode": postcode, "bedrooms": 1, "type": "flat", "status": "To let"}

def test_new_today_stops_at_first_older_creation_date():
    payload = {"properties": [property_record(1, "2026-08-15T09:00:00+00:00"), property_record(2, "2026-08-14T21:30:00+00:00")], "pagination": {"total_count": 2, "has_next_page": False}}
    config = ScraperConfig(1200, True, ("banbury", "didcot"))
    result = discover_offers(SearchSession([SearchResponse(payload, True)]), config, "scrape_new_today", datetime(2026, 8, 15, 12, tzinfo=timezone.utc))
    assert [offer["link"] for offer in result.offers] == ["https://www.taylorsestateagents.co.uk/properties/1/lettings/P1"]
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
