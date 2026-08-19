import os

import pytest

from house_scrapers.config import SCRAPER_CONFIG
from house_scrapers.scrapers.rightmove import detail_offer, discover_offers, http_session

pytestmark = pytest.mark.live

@pytest.mark.skipif(os.getenv("RUN_LIVE_SCRAPERS") != "1", reason="set RUN_LIVE_SCRAPERS=1")
def test_rightmove_live_search_and_detail_without_browser():
    config = SCRAPER_CONFIG["rightmove"]
    with http_session() as session:
        discovery = discover_offers(session, config, "scrape_new_today")
        assert discovery.seen_adverts > 0
        assert discovery.offers
        offer = detail_offer(session, discovery.offers[0], config)
    assert offer is not None
    assert offer["description"]
    assert offer["metadata"]["source"] == "rightmove"
