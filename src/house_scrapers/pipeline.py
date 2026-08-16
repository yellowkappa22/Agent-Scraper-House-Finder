from __future__ import annotations

import os
from collections.abc import Callable, Iterable

Step = tuple[str, Callable[[], None]]


def default_steps() -> tuple[Step, ...]:
    from house_scrapers.dashboard_export import run as export_dashboard
    from house_scrapers.enrichment import run as enrich
    from house_scrapers.filtering import run as filter_results
    from house_scrapers.scrapers.dailyinfo import run as dailyinfo
    from house_scrapers.scrapers.finders import run as finders
    from house_scrapers.scrapers.onthemarket import run as onthemarket
    from house_scrapers.scrapers.spareroom import run as spareroom

    return (
        ("dailyinfo", dailyinfo),
        ("finders", finders),
        ("onthemarket", onthemarket),
        ("spareroom", spareroom),
        ("enrichment", enrich),
        ("filtering", filter_results),
        ("dashboard export", export_dashboard),
    )


def run(steps: Iterable[Step] | None = None) -> None:
    for name, step in steps if steps is not None else default_steps():
        print(f"Running {name}...")
        step()


def run_full() -> None:
    for scraper in ("DAILYINFO", "FINDERS", "ONTHEMARKET", "SPAREROOM"):
        os.environ[f"{scraper}_MODE"] = "scrape_all"
    run()
