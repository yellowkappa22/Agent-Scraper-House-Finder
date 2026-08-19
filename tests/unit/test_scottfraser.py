import json
from datetime import datetime, timezone

from house_scrapers.config import ScraperConfig
from house_scrapers.scrapers.scottfraser import (
    detail_offer,
    discover_offers,
    parse_next_payload,
    search_url,
)


def rsc_html(marker, payload):
    chunk = f'0:{{{marker}{json.dumps(payload, separators=(",", ":"))}}}'
    return f'<script>self.__next_f.push({json.dumps([1, chunk])})</script>'


class Response:
    status_code = 200
    def __init__(self, html):
        self.text = html
    def raise_for_status(self):
        pass


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
    def get(self, url, timeout):
        return next(self.responses)


def record(identifier, created, status="To Let", rent=900):
    return {
        "crm_id": identifier, "created": created, "updated": created,
        "price": rent, "status": status, "display_address": "Oxford, OX1",
        "slug": f"flat-{identifier.lower()}", "title": "1 bedroom flat to rent",
        "latitude": 51.75, "longitude": -1.25,
    }


def results_html(records, total=None, page=0, pages=1):
    payload = {"hits": records, "nbHits": total if total is not None else len(records), "page": page, "nbPages": pages}
    return rsc_html('"searchResults":', payload)


def test_parse_next_payload_decodes_embedded_json():
    parsed = parse_next_payload(results_html([record("ABC1", "2026-08-19T08:00:00Z")]), '"searchResults":')
    assert parsed["hits"][0]["crm_id"] == "ABC1"


def test_search_url_uses_rent_cap_and_pagination():
    assert search_url(1200, 1).endswith("/price-under-1200/")
    assert search_url(1200, 3).endswith("/price-under-1200/page-3/")


def test_new_today_scans_every_page_and_filters_by_creation_date():
    first = results_html([record("OLD", "2026-08-18T20:00:00Z")], total=2, page=0, pages=2)
    second = results_html([record("NEW", "2026-08-19T08:00:00Z")], total=2, page=1, pages=2)
    config = ScraperConfig(1200, False, ())
    result = discover_offers(Session([Response(first), Response(second)]), config, "scrape_new_today", datetime(2026, 8, 19, 12, tzinfo=timezone.utc))
    assert [item["id"] for item in result.offers] == ["NEW"]
    assert result.pages == 2


def test_scrape_all_filters_unavailable_and_verifies_total():
    records = [record("ONE", "2026-08-19T08:00:00Z"), record("TWO", "2026-08-18T08:00:00Z", status="Let Agreed")]
    config = ScraperConfig(1200, False, ())
    result = discover_offers(Session([Response(results_html(records))]), config, "scrape_all")
    assert result.seen_adverts == result.total_adverts == 2
    assert [item["id"] for item in result.offers] == ["ONE"]


def test_detail_contract_includes_full_description_and_source():
    data = record("ONE", "2026-08-19T08:00:00Z") | {
        "long_description": "First paragraph.<br><br>Second paragraph.",
        "post_code": "OX1 1AA", "bedroom": 1, "bathroom": 1,
        "property_type": "Apartment", "crm_negotiator_details": {"name": "Agent"},
    }
    candidate = {"id": "ONE", "title": data["title"], "address": data["display_address"], "rent": 900,
                 "link": "https://example.test/one", "latitude": 51.75, "longitude": -1.25}
    offer = detail_offer(Session([Response(rsc_html('"propertyData":', data))]), candidate, ScraperConfig(1200, False, ()))
    assert offer["description"] == "First paragraph.\nSecond paragraph."
    assert offer["metadata"]["source"] == "scottfraser"
    assert offer["metadata"]["listing_id"] == "ONE"
