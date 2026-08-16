from house_scrapers.enrichment import (
    classify_listing,
    enrich_listing,
    get_bike_route,
    get_coordinates,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, timeout):
        self.calls.append(("GET", url))
        return Response(next(self.responses))

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return Response(next(self.responses))


def test_classification_defaults_to_not_supported():
    assert classify_listing({"address": "Room in Oxford", "description": ""}) == {
        "couples_allowed": False,
        "couples_reason": "no_positive_match",
        "self_contained": False,
        "self_contained_reason": "no_positive_match",
    }


def test_positive_keywords_enable_both_classifications():
    result = classify_listing(
        {
            "address": "Self-contained studio for a couple",
            "description": "Couples welcome.",
        }
    )
    assert result["couples_allowed"] is True
    assert result["self_contained"] is True


def test_negative_context_overrides_positive_keywords():
    result = classify_listing(
        {
            "address": "Studio for couples",
            "description": "Single occupancy only. Shared kitchen.",
        }
    )
    assert result["couples_allowed"] is False
    assert result["couples_reason"].startswith("negative:")
    assert result["self_contained"] is False
    assert result["self_contained_reason"].startswith("negative:")


def test_structured_couples_metadata_is_authoritative():
    listing = {
        "description": "A couple currently lives here.",
        "metadata": {
            "new_housemate_preferences": {"couples_allowed": False},
        },
    }
    result = classify_listing(listing)
    assert result["couples_allowed"] is False
    assert result["couples_reason"] == "metadata:couples_allowed=false"


def test_structured_couples_yes_overrides_negative_description_text():
    listing = {
        "description": "The current room was previously advertised as no couples.",
        "metadata": {
            "new_housemate_preferences": {"couples_allowed": True},
        },
    }
    result = classify_listing(listing)
    assert result["couples_allowed"] is True
    assert result["couples_reason"] == "metadata:couples_allowed=true"

def test_coordinates_use_approximate_outcode_when_full_postcode_is_missing():
    listing = {
        "address": "Two bedroom flat — Headington, Oxford",
        "description": "The property is situated near London Road, OX3.",
        "metadata": {"source": "onthemarket"},
    }
    session = Session(
        [{"status": 200, "result": {"latitude": 51.761, "longitude": -1.21}}]
    )

    assert get_coordinates(listing, session) == {
        "latitude": 51.761,
        "longitude": -1.21,
        "method": "postcode_outcode",
        "postcode": "OX3",
        "approximate": True,
    }
    assert session.calls == [("GET", "https://api.postcodes.io/outcodes/OX3")]

def test_coordinates_prefer_source_metadata_without_network():
    listing = {"metadata": {"latitude": 51.7, "longitude": -1.2}}
    session = Session([])
    assert get_coordinates(listing, session) == {
        "latitude": 51.7,
        "longitude": -1.2,
        "method": "source_metadata",
    }
    assert session.calls == []


def test_coordinates_use_complete_postcode():
    listing = {"address": "Room — Oxford OX2 6GG", "metadata": {}}
    session = Session([{"status": 200, "result": {"latitude": 51.760869, "longitude": -1.263844}}])
    assert get_coordinates(listing, session)["method"] == "postcode"


def test_bike_route_uses_longitude_latitude_order():
    session = Session([{"routes": [{"summary": {"distance": 4200.0, "duration": 900.0}}]}])
    route = get_bike_route(
        {"latitude": 51.7, "longitude": -1.2},
        {"latitude": 51.760869, "longitude": -1.263844},
        session,
        "secret",
    )
    assert route == {
        "duration_minutes": 15.0,
        "distance_km": 4.2,
        "destination": "mathematical_institute_oxford_v1",
    }
    assert session.calls[0][2]["json"]["coordinates"] == [
        [-1.2, 51.7],
        [-1.263844, 51.760869],
    ]


def test_unchanged_route_is_reused_without_network():
    location = {
        "latitude": 51.7,
        "longitude": -1.2,
        "method": "source_metadata",
    }
    previous = {
        "enrichment": {
            "location": location,
            "bike_route": {
                "duration_minutes": 15.0,
                "distance_km": 4.2,
                "destination": "mathematical_institute_oxford_v1",
            },
        }
    }
    session = Session([])

    result = enrich_listing(
        {"link": "https://example.test/1", "metadata": location},
        previous,
        session,
        "secret",
        {},
    )

    assert result["enrichment"]["location"] == previous["enrichment"]["location"]
    assert result["enrichment"]["bike_route"] == previous["enrichment"]["bike_route"]
    assert result["enrichment"]["classification"]["couples_allowed"] is False
    assert session.calls == []
