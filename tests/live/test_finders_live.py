import os

import pytest

from house_scrapers.config import SCRAPER_CONFIG
from house_scrapers.scrapers.finders import STORAGE_BLOB, detail_offer, http_session, scrape_all, scrape_new_today
from house_scrapers.storage import open_offer_store

pytestmark = pytest.mark.live

@pytest.mark.skipif(os.getenv("RUN_LIVE_SCRAPERS") != "1", reason="set RUN_LIVE_SCRAPERS=1")
def test_finders_json_modes_and_detail_contract():
    config = SCRAPER_CONFIG["finders"]
    with http_session() as session:
        today = scrape_new_today(session, config)
        assert today.stopped_at_older or today.offers
        all_results = scrape_all(session, config)
        assert all_results.seen_adverts == all_results.total_adverts
        assert all_results.offers
        offer = next((detail for candidate in all_results.offers[:10] if (detail := detail_offer(session, candidate, config)) is not None), None)
        assert offer is not None
        assert offer["description"]
        assert " — " in str(offer["address"])
        assert offer["metadata"]["source"] == "finders"
        assert offer["metadata"]["postcode"]
        assert offer["metadata"]["agent"]["branch"]

@pytest.mark.skipif(os.getenv("RUN_LIVE_SCRAPERS") != "1", reason="set RUN_LIVE_SCRAPERS=1")
def test_registered_listings_can_be_retrieved_from_blob():
    offers = open_offer_store(STORAGE_BLOB).offers
    assert offers
    for offer in offers:
        assert {"address", "rent", "link"} <= set(offer)
