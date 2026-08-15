from house_scrapers.__main__ import main


def test_list_scrapers(capsys):
    assert main(["--list"]) == 0
    assert capsys.readouterr().out == "dailyinfo\nfinders\nonthemarket\nspareroom\n"


def test_pipeline_command(monkeypatch):
    calls = []
    monkeypatch.setattr("house_scrapers.pipeline.run", lambda: calls.append("pipeline"))
    assert main(["pipeline"]) == 0
    assert calls == ["pipeline"]


def test_refresh_all_command(monkeypatch):
    calls = []
    monkeypatch.setattr("house_scrapers.pipeline.run_full", lambda: calls.append("full"))
    assert main(["refresh-all"]) == 0
    assert calls == ["full"]
