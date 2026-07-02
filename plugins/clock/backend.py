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

_MAX_BYTES = 4 * 1024 * 1024   # cap untrusted feed size before XML/JSON parse (kiosk safety)

def _http_get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read(_MAX_BYTES).decode("utf-8", "replace")

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
           "&daily=weather_code,temperature_2m_max,temperature_2m_min&forecast_days=6")
    d = json.loads(_http_get(url))
    cur, dy = d["current"], d["daily"]
    text, emoji = _wmo(cur["weather_code"])
    forecast = []
    for i in range(1, min(6, len(dy["time"]))):   # today + next 5 days
        _, e2 = _wmo(dy["weather_code"][i])
        forecast.append({"day": datetime.fromisoformat(dy["time"][i]).strftime("%a"),
                         "hi": round(dy["temperature_2m_max"][i]),
                         "lo": round(dy["temperature_2m_min"][i]),
                         "code": dy["weather_code"][i], "emoji": e2})
    return {"location_name": name, "temp": round(cur["temperature_2m"]),
            "code": cur["weather_code"], "text": text, "emoji": emoji,
            "today": {"hi": round(dy["temperature_2m_max"][0]), "lo": round(dy["temperature_2m_min"][0])},
            "forecast": forecast, "units": "°C"}

def _parse_locale(loc):
    parts = (loc or "pl-PL").replace("_", "-").split("-")
    lang = parts[0] or "pl"
    region = (parts[1] if len(parts) > 1 else lang).upper()
    return lang, region

def _local_feed(location, news_locale):
    lang, region = _parse_locale(news_locale)
    return ("https://news.google.com/rss/search?q=" + urllib.parse.quote(location)
            + f"&hl={lang}&gl={region}&ceid={region}:{lang}")

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)

def _parse_rss(text, default_source):
    out = []
    chan = ET.fromstring(text).find("channel")
    if chan is None:
        return out
    ctitle = (chan.findtext("title") or default_source).strip()
    for it in chan.findall("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        src = it.find("source")
        source = src.text.strip() if (src is not None and src.text) else ctitle
        when = None
        pub = it.findtext("pubDate")
        if pub:
            try:
                when = parsedate_to_datetime(pub)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                when = None
        out.append({"title": title, "source": source,
                    "link": (it.findtext("link") or "").strip(),
                    "published": when.astimezone(timezone.utc).isoformat() if when else None,
                    "_sort": when or _EPOCH})
    return out

def _news(location, news_locale, news_feeds, cap, errors):
    feeds = [(_local_feed(location, news_locale), "Local")] + [(u, "News") for u in (news_feeds or [])]
    items = []
    for url, label in feeds:
        try:
            items += _parse_rss(_http_get(url), label)
        except Exception as e:  # noqa: BLE001
            errors.append({"feed": url, "error": str(e)})
    items.sort(key=lambda x: x["_sort"], reverse=True)
    items = items[:cap]
    for x in items:
        del x["_sort"]
    return items

_DEFAULT_FEEDS = [
    "https://news.google.com/rss/search?q=US%20stock%20market&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=GPW%20gie%C5%82da&hl=pl&gl=PL&ceid=PL:pl",
]

def fetch(config, now=None):
    cfg = config or {}
    location = (cfg.get("location") or "Warsaw").strip()
    news_locale = cfg.get("news_locale") or "pl-PL"
    news_feeds = cfg.get("news_feeds")
    if news_feeds is None:
        news_feeds = _DEFAULT_FEEDS
    cap = _pos_int(cfg.get("max_news"), 10)
    now = now or datetime.now(timezone.utc)
    errors, weather = [], None
    try:
        weather = _weather(location)
    except Exception as e:  # noqa: BLE001
        errors.append({"weather": str(e)})
    news = _news(location, news_locale, news_feeds, cap, errors)
    out = {"weather": weather, "news": news, "generated": now.isoformat()}
    if errors:
        out["errors"] = errors
    return out
