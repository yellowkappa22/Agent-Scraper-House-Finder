import pytest

from house_scrapers.pipeline import run, run_full


def test_pipeline_runs_scrapers_then_enrichment():
    calls = []
    steps = (
        ("dailyinfo", lambda: calls.append("dailyinfo")),
        ("finders", lambda: calls.append("finders")),
        ("onthemarket", lambda: calls.append("onthemarket")),
        ("spareroom", lambda: calls.append("spareroom")),
        ("enrichment", lambda: calls.append("enrichment")),
        ("filtering", lambda: calls.append("filtering")),
    )

    run(steps)

    assert calls == [
        "dailyinfo",
        "finders",
        "onthemarket",
        "spareroom",
        "enrichment",
        "filtering",
    ]


def test_pipeline_stops_before_enrichment_when_scraper_fails():
    calls = []

    def fail():
        calls.append("finders")
        raise RuntimeError("website unavailable")

    steps = (
        ("dailyinfo", lambda: calls.append("dailyinfo")),
        ("finders", fail),
        ("enrichment", lambda: calls.append("enrichment")),
    )

    with pytest.raises(RuntimeError, match="website unavailable"):
        run(steps)

    assert calls == ["dailyinfo", "finders"]


def test_full_refresh_sets_every_scraper_to_scrape_all(monkeypatch):
    calls = []
    monkeypatch.setattr("house_scrapers.pipeline.run", lambda: calls.append("run"))
    run_full()
    assert calls == ["run"]
    assert all(
        __import__("os").environ[f"{name}_MODE"] == "scrape_all"
        for name in ("DAILYINFO", "FINDERS", "ONTHEMARKET", "SPAREROOM")
    )
