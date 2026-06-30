import importlib.util, json
from datetime import datetime, timezone
from tests.conftest import ROOT

def _backend():
    spec = importlib.util.spec_from_file_location("clock_backend", str(ROOT / "plugins" / "clock" / "backend.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

FX = ROOT / "tests" / "fixtures"

def test_weather_parses_and_maps_code(monkeypatch):
    b = _backend()
    geo = (FX / "clock_geocode.json").read_text(); fc = (FX / "clock_forecast.json").read_text()
    def http(url):
        return geo if "geocoding-api" in url else fc
    monkeypatch.setattr(b, "_http_get", http)
    w = b._weather("Tychy")
    assert w["location_name"] == "Tychy"
    assert w["temp"] == 21 and w["units"] == "°C"
    assert w["text"] == "Clear" and w["emoji"] == "☀"     # WMO 0
    assert w["today"] == {"hi": 24, "lo": 13}
    assert len(w["forecast"]) == 3 and w["forecast"][0]["day"] == "Wed"  # 2026-07-01

def test_geocode_latlon_bypasses_http(monkeypatch):
    b = _backend()
    calls = []
    monkeypatch.setattr(b, "_http_get", lambda url: calls.append(url) or "{}")
    lat, lon, name = b._geocode("50.13,18.99")
    assert (lat, lon) == (50.13, 18.99) and not any("geocoding" in c for c in calls)

def test_parse_rss_and_merge_sort_cap(monkeypatch):
    b = _backend()
    xml = (FX / "clock_news.xml").read_text()
    monkeypatch.setattr(b, "_http_get", lambda url: xml)   # every feed returns the same 2 items
    errors = []
    items = b._news("Tychy", "pl-PL", ["http://a", "http://b"], 3, errors)
    assert errors == []
    assert [i["title"] for i in items] == ["Newer headline", "Newer headline", "Newer headline"]  # newest first, capped at 3
    # source falls back to channel title when item <source> absent; uses <source> when present
    assert items[0]["source"] == "Test Feed"
    assert "T" in items[0]["published"]                    # ISO datetime
    assert "_sort" not in items[0]                         # internal sort key stripped from output

def test_parse_rss_source_present_and_fallback():
    b = _backend()
    items = b._parse_rss((FX / "clock_news.xml").read_text(), "Local")
    by = {i["title"]: i for i in items}
    assert by["Older headline"]["source"] == "Reuters"     # item <source> used when present
    assert by["Newer headline"]["source"] == "Test Feed"   # falls back to channel <title>

def test_news_feed_failure_isolated(monkeypatch):
    b = _backend()
    xml = (FX / "clock_news.xml").read_text()
    def http(url):
        if "bad" in url:
            raise OSError("feed down")
        return xml
    monkeypatch.setattr(b, "_http_get", http)
    errors = []
    # derived local feed (google news) + http://good return xml; http://bad raises
    items = b._news("50.1,19.0", "pl-PL", ["http://bad", "http://good"], 10, errors)
    assert any("bad" in e["feed"] for e in errors)         # failed feed recorded, not raised
    assert len(items) == 4                                  # local(2) + good(2) survived past the failing feed

def test_local_feed_url_from_locale():
    b = _backend()
    url = b._local_feed("Tychy", "pl-PL")
    assert "news.google.com/rss/search" in url
    assert "q=Tychy" in url and "hl=pl" in url and "gl=PL" in url and "ceid=PL:pl" in url

def test_fetch_partial_on_weather_failure(monkeypatch):
    b = _backend()
    xml = (FX / "clock_news.xml").read_text()
    def http(url):
        if "open-meteo" in url:
            raise OSError("weather down")
        return xml
    monkeypatch.setattr(b, "_http_get", http)
    out = b.fetch({"location": "50.1,19.0", "news_feeds": ["http://a"]},
                  now=datetime(2026, 6, 30, tzinfo=timezone.utc))
    assert out["weather"] is None and "errors" in out      # weather failed, isolated
    assert len(out["news"]) == 4                            # local(2) + http://a(2); news unaffected by weather failure
