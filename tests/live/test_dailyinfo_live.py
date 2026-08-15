import os

import pytest
from bs4 import BeautifulSoup

from house_scrapers.config import SCRAPER_CONFIG
from house_scrapers.scrapers.dailyinfo import detail_offer, http_session, map_location, scrape_all, scrape_new_today

pytestmark = pytest.mark.live

@pytest.mark.skipif(os.getenv("RUN_LIVE_SCRAPERS") != "1", reason="set RUN_LIVE_SCRAPERS=1")
def test_dailyinfo_modes_map_and_output_contract():
    config = SCRAPER_CONFIG["dailyinfo"]
    with http_session() as session:
        today = scrape_new_today(session, config)
        assert today.seen_adverts
        all_results = scrape_all(session, config)
        assert all_results.seen_adverts >= today.seen_adverts
        mapped_candidate = None
        for candidate in all_results.offers[:20]:
            response = session.get(str(candidate["link"]), timeout=30)
            response.raise_for_status()
            if map_location(BeautifulSoup(response.text, "html.parser")):
                mapped_candidate = candidate
                break
        assert mapped_candidate is not None
        offer = detail_offer(session, mapped_candidate, config)
        assert offer["description"]
        assert offer["metadata"]["source"] == "dailyinfo"
        assert offer["metadata"]["postcode"]
        assert offer["address"].endswith(str(offer["metadata"]["postcode"]))
        assert " — " in str(offer["address"])
