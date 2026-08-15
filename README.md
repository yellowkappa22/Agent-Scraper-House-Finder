# House Scrapers

A minimal Python repository for independent, website-specific housing scrapers. The Finders, OnTheMarket, Daily Info, and SpareRoom scrapers collect Oxfordshire rentals below a configured monthly rent and record their full descriptions in Azure Blob Storage.

## Structure

```text
src/house_scrapers/
  __main__.py             # shared command-line dispatcher
  config.py               # all scraper filters and runtime options
  storage.py              # shared managed-identity Blob persistence
  enrichment.py           # coordinate and bicycle-route enrichment
  filtering.py            # Filter II result selection
  pipeline.py             # scrapers followed by enrichment
  data/keywords.json      # versioned classification vocabulary
  scrapers/dailyinfo.py   # Daily Info-specific implementation
  scrapers/finders.py     # Finders-specific implementation
  scrapers/onthemarket.py # OnTheMarket-specific implementation
  scrapers/spareroom.py   # SpareRoom-specific implementation
tests/unit/               # deterministic tests; no network/browser
tests/live/               # opt-in website smoke tests
```

Website selectors and behavior remain in each scraper module so changes to one website do not disturb another.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m playwright install firefox
```

On Linux, Playwright may need system packages. If absent, run `python -m playwright install --with-deps firefox` with suitable permissions.

## Configuration

The scraper uses `DefaultAzureCredential` to access each scraper's JSON blob in the `scraping-results` container of the `ykhousingstorage` account. On the Azure VM this uses its system-assigned managed identity. No account keys, SAS tokens, connection strings, or client secrets are supported. The identity needs the Storage Blob Data Contributor role.

All scraper filters and runtime options are indexed in `src/house_scrapers/config.py`. Local values are read automatically from the ignored `.env` file. Each scraper has `<NAME>_MAX_RENT` and `<NAME>_HEADLESS` settings. `EXCLUDED_LOCATIONS` is a shared comma-separated list. `DAILYINFO_MODE`, `FINDERS_MODE`, `ONTHEMARKET_MODE`, and `SPAREROOM_MODE` accept `scrape_new_today` or `scrape_all`. All rent limits default to `1200`; the comparison is strict, so a £1,200 listing is not saved. Weekly prices are converted with `weekly × 52 ÷ 12`. Variables already exported by the process take precedence over `.env`.

Bicycle-route enrichment requires `OPENROUTE_API_KEY=your-key` in
`.env`. Hyphens are valid inside the value and do not require quotes;
environment-variable names should use underscores. Listings use source
coordinates when available, otherwise a complete UK postcode is resolved with
Postcodes.io. Imprecise locations are marked unavailable rather than guessed.

Filter II reads `MAX_BIKE_DURATION_MINUTES` from `.env` and defaults to
`50`. Listings above the limit are rejected; listings exactly at the limit or
without a bicycle duration continue to classification.

The intake stage deliberately does not filter house shares, couples, or eligibility. Results must have an Oxfordshire `OX` postcode where the source is not already geographically constrained, must not match an excluded location, and must have a non-empty full description.

## Running

```bash
python -m house_scrapers finders
python -m house_scrapers onthemarket
python -m house_scrapers dailyinfo
python -m house_scrapers spareroom
python -m house_scrapers enrich-bike
python -m house_scrapers filter-results
python -m house_scrapers pipeline
python -m house_scrapers refresh-all
```

The enrichment command reads active records from all four Bronze property blobs
without deleting their history and replaces the Silver snapshot at
`enriched/properties.json`. Its `enrichment`
object contains the coordinate source plus cycling distance and duration to the
Mathematical Institute, University of Oxford. An unchanged
coordinate/destination pair reuses its stored route.

The same step classifies `couples_allowed` and `self_contained` using
structured metadata and the versioned keyword vocabulary. An explicit
structured boolean is authoritative. Otherwise both default to `false`; a
positive match changes the value to `true`, while any negative match overrides
a positive match. A short `*_reason` records the decisive metadata field or
phrase. This is deterministic and does not use an LLM or a paid classification
API.

`pipeline` runs all four scrapers sequentially, followed by Silver enrichment
and Gold filtering. If any stage fails, the command exits non-zero and later
stages do not publish partial data. This is the command intended for the hourly
systemd service and timer.

`refresh-all` runs the same pipeline with every scraper in `scrape_all` mode.
Use it periodically (for example daily) to reconcile dead listings; the hourly
pipeline remains on the cheaper `scrape_new_today` modes.

`filter-results` maintains two append-only Gold registries:
`gold/couples_results.json` contains every listing that has qualified as
couples-supported, including those also classified as self-contained.
`gold/self_contained_results.json` contains listings that qualified as
self-contained without couples support. Canonical links are registered once,
`first_qualified_at` is preserved, and `currently_eligible` controls whether
the website displays an old result.

Use `python -m house_scrapers --list` to list scrapers. Accepted properties are written to the Bronze blobs at `<scraper>/properties.json`; existing registered listings are skipped. Every stored record has an `archived` UTC ISO-8601 timestamp. A complete `scrape_all` refresh also maintains `active`, `last_seen`, and `inactive_at` without deleting historical records. Partial `scrape_new_today` runs never deactivate unseen records.

DailyInfo, Finders, OnTheMarket, and SpareRoom use Requests rather than a browser. Finders reads Homeflow JSON embedded in the initial page and follows its JSON search endpoint. Their default `scrape_new_today` mode checks featured cards and the current date group; run a complete active-results import with `<NAME>_MODE=scrape_all`. DailyInfo prefers the full postcode embedded in its Leaflet script and formats addresses as `header — postcode`, falling back to the displayed area when no map was supplied.

Every saved Finders offer includes `metadata.source: "finders"`, full postcode and coordinates, creation time, and responsible branch contact details. Its addresses use `property title — full address`.

Every saved OnTheMarket offer includes `metadata.source: "onthemarket"` and, when published, nested responsible-agent `name`, `address`, and `phone` fields. Addresses use `property title — advertised address`.

Every saved DailyInfo offer includes `metadata.source: "dailyinfo"`; map-enabled adverts also include `postcode`, `latitude`, and `longitude`.

Every saved SpareRoom offer includes a structured `metadata` object with `source: "spareroom"`. Available detail-page fields are grouped under `availability`, `extra_cost`, `amenities`, `current_household`, and `new_housemate_preferences`; unavailable fields are omitted rather than guessed.
SpareRoom latitude and longitude are read from the advert configuration already
embedded in each detail page; opening its JavaScript map is not required.

## Testing

```bash
python -m pytest
RUN_LIVE_SCRAPERS=1 python -m pytest -m live
```

The default suite is deterministic. The opt-in live tests require network access; browser-based scrapers also require Firefox, and never writes data or sends email.
