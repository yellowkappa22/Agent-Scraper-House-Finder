import os

import pytest

from house_scrapers.config import SCRAPER_CONFIG
from house_scrapers.scrapers.onthemarket import detail_offer, http_session, scrape_new_today

pytestmark = pytest.mark.live

@pytest.mark.skipif(os.getenv("RUN_LIVE_SCRAPERS") != "1", reason="set RUN_LIVE_SCRAPERS=1")
def test_onthemarket_new_today_detail_and_agent_contract():
    config = SCRAPER_CONFIG["onthemarket"]
    with http_session() as session:
        result = scrape_new_today(session, config)
        assert result.offers
        assert result.stopped_at_older
        offer = detail_offer(session, result.offers[0], config)
        assert offer["description"]
        assert " — " in str(offer["address"])
        assert offer["metadata"]["source"] == "onthemarket"
        assert offer["metadata"]["agent"]["name"]
        assert offer["metadata"]["agent"]["address"]
        assert offer["metadata"]["agent"]["phone"]
