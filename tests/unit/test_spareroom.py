from bs4 import BeautifulSoup

from house_scrapers.config import ScraperConfig
from house_scrapers.scrapers.spareroom import (
    discover_offers,
    monthly_rent,
    parse_coordinates,
    parse_metadata,
)


CONFIG = ScraperConfig(max_rent=1200, headless=True, excluded_locations=("banbury", "didcot"))


class Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class Session:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.requests = 0

    def get(self, url, timeout):
        self.requests += 1
        return Response(next(self.pages))


def page(cards, current="Showing 1-3 of 3 results", next_href=None):
    next_link = f'<a id="paginationNextPageLink" href="{next_href}">Next</a>' if next_href else ""
    return f'<ul class="listing-results">{"".join(cards)}</ul><p class="navcurrent">{current}</p>{next_link}'


def card(advert_id, status_class, title, location, rate="£800", period="pcm"):
    return f'''<li class="listing-result" data-listing-id="{advert_id}"
        data-listing-title="{title}" data-listing-ad-rate-normalised="{rate}"
        data-listing-ad-rate-normalised-period="{period}">
        <article class="listing-card">
          <a class="listing-card__link" href="/flatshare/oxfordshire/oxford/{advert_id}?tracking=1">
            <div class="listing-card__status {status_class}">status</div>
            <span class="listing-card__location">{location}</span>
          </a>
        </article>
      </li>'''


def test_monthly_rent_normalizes_weekly_prices():
    assert monthly_rent("£1,100", "pcm") == 1100
    assert monthly_rent("£200", "pw") == 867


def test_new_today_stops_at_new_but_processes_unflagged_featured():
    session = Session([
        page([
            card("1", "", "Featured", "Oxford (OX1)"),
            card("2", "listing-card__status--new-today", "Today", "Oxford (OX2)"),
            card("3", "listing-card__status--new", "Older", "Oxford (OX3)"),
        ])
    ])
    result = discover_offers(session, CONFIG, "scrape_new_today")
    assert [offer["address"] for offer in result.offers] == [
        "Featured — Oxford (OX1)", "Today — Oxford (OX2)"
    ]
    assert result.stopped_at_older


def test_scrape_all_follows_every_page_and_applies_filters():
    session = Session([
        page([
            card("1", "listing-card__status--new-today", "Oxford room", "Oxford (OX1)"),
            card("2", "listing-card__status--new", "Too expensive", "Oxford (OX2)", "£1,200"),
        ], "Showing 1-2 of 4 results", "/flatshare/oxfordshire/page2"),
        page([
            card("3", "listing-card__status--new", "Excluded", "Didcot (OX11)"),
            card("4", "listing-card__status--new", "Allowed", "Witney (OX28)"),
        ], "Showing 3-4 of 4 results"),
    ])
    result = discover_offers(session, CONFIG, "scrape_all")
    assert result.seen_adverts == result.total_adverts == 4
    assert result.pages == 2
    assert [offer["address"] for offer in result.offers] == [
        "Oxford room — Oxford (OX1)", "Allowed — Witney (OX28)"
    ]


def test_duplicate_featured_advert_is_processed_once():
    duplicate = card("1", "", "Featured", "Oxford (OX1)")
    result = discover_offers(Session([page([duplicate, duplicate], "Showing 1-1 of 1 results")]), CONFIG, "scrape_all")
    assert len(result.offers) == 1


def test_unavailable_javascript_card_is_not_a_candidate():
    unavailable = card("1", "listing-card__status--new", "Gone", "Oxford (OX1)").replace(
        '/flatshare/oxfordshire/oxford/1?tracking=1',
        "javascript:alert('Sorry, this room is no longer available');",
    )
    result = discover_offers(
        Session([page([unavailable], "Showing 1-1 of 1 results")]), CONFIG, "scrape_all"
    )
    assert result.offers == []


def test_metadata_has_source_and_normalized_sections():
    soup = BeautifulSoup(
        """<section class="feature feature--availability"><dl>
          <dt>Available</dt><dd>Available now</dd>
          <dt>Minimum term</dt><dd>6 months</dd>
        </dl></section>
        <section class="feature feature--extra-cost"><dl>
          <dt>Deposit <small>(Room 1)</small></dt><dd>£865.38</dd>
          <dt>Bills included?</dt><dd><span class="tick">Yes</span></dd>
        </dl></section>
        <section class="feature feature--household-preferences"><dl>
          <dt>Couples OK?</dt><dd><span class="cross">No</span></dd>
          <dt>Occupation</dt><dd>Not suitable for students</dd>
        </dl></section>""",
        "html.parser",
    )
    assert parse_metadata(soup) == {
        "source": "spareroom",
        "availability": {"available": "Available now", "minimum_term": "6 months"},
        "extra_cost": {"deposit_room_1": "£865.38", "bills_included": True},
        "new_housemate_preferences": {
            "couples_allowed": False,
            "occupation": "Not suitable for students",
        },
    }


def test_coordinates_are_read_from_embedded_advert_location():
    html = """
    <script>
    _sr.page = {
      advert: {
        id: "15282368",
        location: {
          latitude: "51.7257818694657",
          longitude: "-1.2348532380479",
        },
      },
    };
    </script>
    <div id="map"><canvas class="syrup-canvas"></canvas></div>
    """
    assert parse_coordinates(html) == (51.7257818694657, -1.2348532380479)


def test_coordinates_are_absent_when_advert_location_is_not_published():
    assert parse_coordinates('<div id="map"></div>') is None
