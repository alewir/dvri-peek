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
