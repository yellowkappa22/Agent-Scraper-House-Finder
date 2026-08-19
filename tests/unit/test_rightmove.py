import json

from house_scrapers.config import ScraperConfig
from house_scrapers.scrapers.rightmove import (
    candidate_offer,
    detail_offer,
    discover_offers,
    parse_detail_model,
    parse_search_results,
)

CONFIG = ScraperConfig(max_rent=1200, headless=False, excluded_locations=("banbury", "didcot"), mode=None)

class Response:
    def __init__(self, *, text="", status_code=200):
        self.text = text
        self.status_code = status_code
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []
    def get(self, url, timeout):
        self.urls.append(url)
        return next(self.responses)

def search_html(properties, *, total=0, next_index=None):
    payload = {"props": {"pageProps": {"searchResults": {
        "properties": properties,
        "pagination": {"next": next_index},
        "resultCount": total,
    }}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'

def card(identifier, status, *, rent=900, address="Oxford, OX1"):
    return {
        "id": identifier,
        "addedOrReduced": status,
        "displayAddress": address,
        "propertyUrl": f"/properties/{identifier}#/?channel=RES_LET",
        "price": {"amount": rent, "frequency": "monthly"},
        "summary": "Full summary",
        "propertySubType": "Flat",
        "location": {"latitude": 51.75, "longitude": -1.25},
        "customer": {"branchDisplayName": "Example Agent", "contactTelephone": "01234"},
    }

def detail_html():
    values = [
        {"propertyData": 1},
        {"text": 2, "address": 5, "location": 8, "customer": 11, "contactInfo": 14,
         "lettings": 17, "bedrooms": 19, "bathrooms": 20, "propertySubType": 21, "keyFeatures": 22},
        {"description": 3, "propertyPhrase": 4},
        "A comfortable flat with a garden.", "1 bedroom flat",
        {"displayAddress": 6}, "Headington, Oxford, OX3",
        None,
        {"latitude": 9, "longitude": 10}, 51.76, -1.21,
        {"branchDisplayName": 12, "displayAddress": 13}, "Example Agent", "1 High Street, Oxford",
        {"telephoneNumbers": 15}, {"localNumber": 16}, "01865 000000",
        {"furnishType": 18}, "Furnished", 1, 1, "Flat", [23], "Garden",
    ]
    envelope = json.dumps({"data": json.dumps(values), "encoding": "devalue"})
    return f"<script>window.__PAGE_MODEL = {envelope};</script>"

def test_search_results_are_read_from_embedded_json():
    results = parse_search_results(search_html([card(1, "Added today")], total=1))
    assert results["resultCount"] == 1
    assert results["properties"][0]["id"] == 1

def test_candidate_applies_rent_and_excluded_location_filters():
    assert candidate_offer(card(1, "Added today", rent=1199), CONFIG)["link"] == "https://www.rightmove.co.uk/properties/1"
    assert candidate_offer(card(2, "Added today", rent=1200), CONFIG) is None
    assert candidate_offer(card(3, "Added today", address="Banbury, OX16"), CONFIG) is None

def test_new_today_ignores_old_promoted_entries_then_stops_after_current_boundary():
    properties = [
        card(1, "Added on 01/08/2026"),
        card(2, "Added today"),
        card(3, "Reduced today"),
        card(4, "Added yesterday"),
        card(5, "Added yesterday"),
    ]
    discovery = discover_offers(Session([Response(text=search_html(properties, total=5))]), CONFIG, "scrape_new_today")
    assert [offer["id"] for offer in discovery.offers] == [1, 2, 3]
    assert discovery.stopped_at_older is True

def test_scrape_all_follows_pagination_and_deduplicates_promoted_properties():
    session = Session([
        Response(text=search_html([card(1, "Added today"), card(2, "Added yesterday")], total=3, next_index="24")),
        Response(text=search_html([card(1, "Added today"), card(3, "Added on 01/08/2026")], total=3)),
    ])
    discovery = discover_offers(session, CONFIG, "scrape_all")
    assert [offer["id"] for offer in discovery.offers] == [1, 2, 3]
    assert discovery.pages == 2
    assert "index=24" in session.urls[1]

def test_detail_model_and_offer_preserve_description_address_and_agent_metadata():
    data = parse_detail_model(detail_html())
    assert data["text"]["description"].startswith("A comfortable")
    offer = detail_offer(Session([Response(text=detail_html())]), candidate_offer(card(1, "Added today"), CONFIG), CONFIG)
    assert offer["address"] == "1 bedroom flat — Headington, Oxford, OX3"
    assert offer["description"] == "A comfortable flat with a garden."
    assert offer["metadata"]["source"] == "rightmove"
    assert offer["metadata"]["agent"]["phone"] == "01865 000000"
