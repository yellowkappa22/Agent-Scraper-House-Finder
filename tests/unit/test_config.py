from house_scrapers.config import SCRAPER_CONFIG, location_allowed, oxfordshire_location_allowed


def test_location_exclusions_are_shared_by_all_scrapers():
    assert all(config.excluded_locations == ("banbury", "didcot") for config in SCRAPER_CONFIG.values())
    assert not location_allowed("Banbury, OX16", SCRAPER_CONFIG["finders"])
    assert location_allowed("Oxford, OX3", SCRAPER_CONFIG["finders"])


def test_oxfordshire_location_requires_ox_postcode():
    config = SCRAPER_CONFIG["dailyinfo"]
    assert oxfordshire_location_allowed("Finstock (OX7)", config)
    assert not oxfordshire_location_allowed("Aldershot GU12", config)
