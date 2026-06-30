# plugins/clock/backend.py — clock widget data: Open-Meteo weather (no API key) +
# aggregated RSS news (a derived local feed + explicit feeds). Stdlib only.
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# WMO weather code -> (short text, emoji)
_WMO = {
    0: ("Clear", "☀"), 1: ("Mainly clear", "🌤"), 2: ("Partly cloudy", "⛅"), 3: ("Overcast", "☁"),
    45: ("Fog", "🌫"), 48: ("Rime fog", "🌫"),
    51: ("Light drizzle", "🌦"), 53: ("Drizzle", "🌦"), 55: ("Dense drizzle", "🌦"),
    56: ("Freezing drizzle", "🌧"), 57: ("Freezing drizzle", "🌧"),
    61: ("Light rain", "🌧"), 63: ("Rain", "🌧"), 65: ("Heavy rain", "🌧"),
    66: ("Freezing rain", "🌧"), 67: ("Freezing rain", "🌧"),
    71: ("Light snow", "🌨"), 73: ("Snow", "🌨"), 75: ("Heavy snow", "❄"), 77: ("Snow grains", "🌨"),
    80: ("Showers", "🌦"), 81: ("Showers", "🌧"), 82: ("Violent showers", "⛈"),
    85: ("Snow showers", "🌨"), 86: ("Snow showers", "🌨"),
    95: ("Thunderstorm", "⛈"), 96: ("Thunderstorm", "⛈"), 99: ("Thunderstorm", "⛈"),
}

def _wmo(code):
    return _WMO.get(int(code), ("—", "🌡"))

def _pos_int(value, default):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default

def _http_get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read().decode("utf-8", "replace")

def _geocode(location):
    parts = location.split(",")
    if len(parts) == 2:
        try:
            return float(parts[0]), float(parts[1]), location
        except ValueError:
            pass
    url = "https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(location)
    res = (json.loads(_http_get(url)).get("results") or [None])[0]
    if not res:
        raise ValueError(f"location not found: {location}")
    return res["latitude"], res["longitude"], res.get("name", location)

def _weather(location):
    lat, lon, name = _geocode(location)
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat}&longitude={lon}&timezone=auto&temperature_unit=celsius"
           "&current=temperature_2m,weather_code"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min&forecast_days=4")
    d = json.loads(_http_get(url))
    cur, dy = d["current"], d["daily"]
    text, emoji = _wmo(cur["weather_code"])
    forecast = []
    for i in range(1, min(4, len(dy["time"]))):
        _, e2 = _wmo(dy["weather_code"][i])
        forecast.append({"day": datetime.fromisoformat(dy["time"][i]).strftime("%a"),
                         "hi": round(dy["temperature_2m_max"][i]),
                         "lo": round(dy["temperature_2m_min"][i]),
                         "code": dy["weather_code"][i], "emoji": e2})
    return {"location_name": name, "temp": round(cur["temperature_2m"]),
            "code": cur["weather_code"], "text": text, "emoji": emoji,
            "today": {"hi": round(dy["temperature_2m_max"][0]), "lo": round(dy["temperature_2m_min"][0])},
            "forecast": forecast, "units": "°C"}
