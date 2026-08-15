from datetime import datetime, timezone

import pytest
from bs4 import BeautifulSoup

from house_scrapers.config import ScraperConfig
from house_scrapers.scrapers.dailyinfo import detail_offer, discover_offers, map_location, monthly_rent


@pytest.mark.parametrize(
    ("price", "expected"),
    [("£1,100 PCM", 1100), ("£200 PW", 867), ("price unknown", None)],
)
def test_monthly_rent(price, expected):
    assert monthly_rent(price) == expected


def test_map_location_reads_leaflet_source_without_javascript():
    soup = BeautifulSoup(
        r"""<div id="adMap"></div><script>
        L.marker([51.7212989, -1.2080022]).addTo(mymap).bindPopup("OX4\u00203BA")
        </script>""",
        "html.parser",
    )
    assert map_location(soup) == {
        "postcode": "OX4 3BA",
        "latitude": 51.7212989,
        "longitude": -1.2080022,
    }


class Response:
    def __init__(self, text):
        self.text = text
    def raise_for_status(self):
        pass

class Session:
    def __init__(self, pages):
        self.pages = iter(pages)
    def get(self, url, timeout):
        return Response(next(self.pages))

def card(advert_id, title="Room", location="OX4 Oxford", rent="£700 pcm"):
    return f"""<div class="a-container"><span class="a-text">{title}</span>
      <span class="a-postcode">{location}</span><span class="a-rent">{rent}</span>
      <span class="a-time-placed" data-timestamp="1"></span>
      <a class="overlaid-link" href="/rooms-to-let/{advert_id}">More details</a></div>"""

def test_new_today_processes_featured_and_stops_at_next_date():
    page = card("1", "Featured") + "<h4 class=" + chr(34) + "aboard-day-separator" + chr(34) + ">Sat 15th</h4>" + card("2", "Today") + "<h4 class=" + chr(34) + "aboard-day-separator" + chr(34) + ">Fri 14th</h4>" + card("3", "Older")
    config = ScraperConfig(1200, True, ("banbury", "didcot"))
    result = discover_offers(Session([page, page]), config, "scrape_new_today", datetime(2026, 8, 15, tzinfo=timezone.utc))
    assert [offer["title"] for offer in result.offers] == ["Featured", "Today"]

def test_scrape_all_processes_every_card_and_applies_filters():
    page = card("1") + "<h4 class=" + chr(34) + "aboard-day-separator" + chr(34) + ">Fri 14th</h4>" + card("2", "Too expensive", rent="£1200 pcm") + card("3", "Excluded", location="Didcot OX11")
    config = ScraperConfig(1200, True, ("banbury", "didcot"))
    result = discover_offers(Session([page, ""]), config, "scrape_all")
    assert result.seen_adverts == 3
    assert [offer["title"] for offer in result.offers] == ["Room"]


def test_detail_uses_header_when_extended_description_is_absent():
    page = """<div class="shortAvtHtml">Header-only advert</div>
      <div class="a-attributes"><span class="value">£700 PCM</span><span class="value">OX4</span></div>"""
    candidate = {"title": "Header-only advert", "card_location": "OX4", "rent": 700, "link": "https://example.test/1", "published_timestamp": 1}
    config = ScraperConfig(1200, True, ("banbury", "didcot"))
    assert detail_offer(Session([page]), candidate, config)["description"] == "Header-only advert"
