import os

import pytest
from bs4 import BeautifulSoup

from house_scrapers.config import SCRAPER_CONFIG
from house_scrapers.scrapers.spareroom import http_session, parse_metadata, scrape_new_today

pytestmark = pytest.mark.live


@pytest.mark.skipif(os.getenv("RUN_LIVE_SCRAPERS") != "1", reason="set RUN_LIVE_SCRAPERS=1")
def test_spareroom_new_today_and_description_contract():
    with http_session() as session:
        result = scrape_new_today(session, SCRAPER_CONFIG["spareroom"])
        assert result.offers
        assert result.stopped_at_older
        response = session.get(str(result.offers[0]["link"]), timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        assert soup.select_one(".detaildesc").get_text(strip=True)
        assert parse_metadata(soup)["source"] == "spareroom"
