import pytest
from bs4 import BeautifulSoup

from house_scrapers.config import ScraperConfig
from house_scrapers.scrapers.onthemarket import discover_offers, parse_listing_card, parse_agent


def test_parse_listing_card():
    text = "Recently added\nTenancy info\n£1,075 pcm (£248 pw)\n22 Raymund Road, Marston OX3\nProperty"
    assert parse_listing_card(text) == (1075, "22 Raymund Road, Marston OX3")


@pytest.mark.parametrize("text", ["Price on application", "£900 pw\nOxford"])
def test_parse_listing_card_rejects_unexpected_prices(text):
    assert parse_listing_card(text) is None


def test_parse_agent_from_raw_detail_html():
    soup = BeautifulSoup("""<div class="block border"><img alt="College &amp; County - Oxford"><div><div class="text-sm font-bold">College &amp; County - Oxford</div><div class="text-xs text-slate">Bury Knowle Coach House, North Place, Headington, Oxfordshire OX3 9HY</div><a href="tel:01865 969473">01865 969473</a></div></div>""", "html.parser")
    assert parse_agent(soup) == {"name": "College & County - Oxford", "address": "Bury Knowle Coach House, North Place, Headington, Oxfordshire OX3 9HY", "phone": "01865 969473"}


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

def card(advert_id, status, address="Oxford OX1", rent="£900 pcm"):
    flag = f"<div>{status}</div>" if status else ""
    return f"""<article data-component="search-result-property-card">{flag}
      <a href="/details/{advert_id}/">{rent}</a>
      <address itemprop="address">{address}</address></article>"""

def test_new_today_stops_only_at_explicit_older_status():
    page = card("1", "") + card("2", "Added today") + card("3", "Added yesterday") + card("4", "")
    config = ScraperConfig(1200, True, ("banbury", "didcot"))
    result = discover_offers(Session([page]), config, "scrape_new_today")
    assert [offer["link"] for offer in result.offers] == ["https://www.onthemarket.com/details/1/", "https://www.onthemarket.com/details/2/"]
    assert result.stopped_at_older

def test_scrape_all_follows_all_reported_pages_and_filters():
    first = card("1", "Added today") + "<a href=" + chr(34) + "/to-rent/property/oxfordshire/?page=2" + chr(34) + ">2</a>"
    second = card("2", "Recently added", address="Didcot OX11") + card("3", "", address="Witney OX28")
    config = ScraperConfig(1200, True, ("banbury", "didcot"))
    result = discover_offers(Session([first, second]), config, "scrape_all")
    assert result.pages == 2
    assert result.seen_adverts == 3
    assert [offer["address"] for offer in result.offers] == ["Oxford OX1", "Witney OX28"]
