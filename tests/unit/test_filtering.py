from house_scrapers.filtering import filter_listings, update_gold


def listing(*, bike_minutes=None, couples=False, self_contained=False):
    enrichment = {
        "classification": {
            "couples_allowed": couples,
            "self_contained": self_contained,
        }
    }
    if bike_minutes is not None:
        enrichment["bike_route"] = {"duration_minutes": bike_minutes}
    return {"link": f"https://example.test/{bike_minutes}-{couples}-{self_contained}", "enrichment": enrichment}


def test_over_limit_is_excluded():
    couples, self_contained = filter_listings(
        [listing(bike_minutes=50.1, couples=True, self_contained=True)], 50
    )
    assert couples == []
    assert self_contained == []


def test_missing_and_boundary_duration_proceed():
    at_boundary = listing(bike_minutes=50, couples=True)
    missing = listing(self_contained=True)
    couples, self_contained = filter_listings([at_boundary, missing], 50)
    assert couples == [at_boundary]
    assert self_contained == [missing]


def test_couples_result_takes_precedence_over_self_contained():
    both = listing(bike_minutes=20, couples=True, self_contained=True)
    couples, self_contained = filter_listings([both], 50)
    assert couples == [both]
    assert self_contained == []


def test_unsupported_listing_is_excluded():
    assert filter_listings([listing(bike_minutes=20)], 50) == ([], [])


def test_inactive_listing_is_excluded():
    item = listing(bike_minutes=20, couples=True)
    item["active"] = False
    assert filter_listings([item], 50) == ([], [])


def test_gold_keeps_old_results_but_only_new_results_are_added_once():
    old = {
        "link": "old",
        "rent": 900,
        "first_qualified_at": "2026-01-01T00:00:00Z",
        "currently_eligible": True,
    }
    current_old = {"link": "old", "rent": 850}
    new = {"link": "new", "rent": 700}

    gold = update_gold([old], [current_old, new], "2026-08-15T15:00:00Z")

    assert [item["link"] for item in gold] == ["old", "new"]
    assert gold[0]["rent"] == 850
    assert gold[0]["first_qualified_at"] == "2026-01-01T00:00:00Z"
    assert gold[1]["first_qualified_at"] == "2026-08-15T15:00:00Z"
    assert all(item["currently_eligible"] for item in gold)


def test_gold_retains_results_that_no_longer_qualify():
    gold = update_gold(
        [{"link": "old", "first_qualified_at": "earlier"}],
        [],
        "now",
    )
    assert gold == [
        {
            "link": "old",
            "first_qualified_at": "earlier",
            "currently_eligible": False,
        }
    ]
