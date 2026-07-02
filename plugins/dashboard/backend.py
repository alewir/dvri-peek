# plugins/dashboard/backend.py — combined clock + calendar widget data.
# One fetch() returns: Open-Meteo weather (no API key) + aggregated RSS news
# (a derived local feed + explicit feeds) + a merged multi-calendar agenda from
# secret ICS feeds. Stdlib only.
#
# Calendar recurrence: non-recurring always; FREQ=DAILY|WEEKLY (INTERVAL, COUNT,
# UNTIL, weekly BYDAY) expanded in-window; MONTHLY/YEARLY -> original occurrence
# only. EXDATE (cancelled) and RECURRENCE-ID overrides (moved/modified) honored.
# No-COUNT DAILY/WEEKLY series fast-forward to window_start; COUNT counts from DTSTART.
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

_MAX_BYTES = 4 * 1024 * 1024   # cap untrusted feed size before XML/JSON/ICS parse (kiosk safety)

def _pos_int(value, default):
    # positive-int coercion: missing / non-numeric / <=0 -> default. Structurally
    # prevents zero/negative steps (RRULE INTERVAL=0 DoS) and zero/negative windows.
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default

def _http_get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read(_MAX_BYTES).decode("utf-8", "replace")

# ── weather (Open-Meteo) ──────────────────────────────────────────────────
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

# ── news (RSS) ────────────────────────────────────────────────────────────
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

# ── calendar (ICS) ────────────────────────────────────────────────────────
_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

def _unfold(text):
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out

def _parse_dt(val, params):
    if params.get("VALUE") == "DATE" or (len(val) == 8 and "T" not in val):
        d = datetime.strptime(val, "%Y%m%d").replace(tzinfo=timezone.utc)
        return d, True
    if val.endswith("Z"):
        return datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc), False
    naive = datetime.strptime(val[:15], "%Y%m%dT%H%M%S")
    tzid = params.get("TZID")
    if tzid:
        try:
            return naive.replace(tzinfo=ZoneInfo(tzid)).astimezone(timezone.utc), False
        except Exception:  # noqa: BLE001 — unknown zone: fall through to UTC
            pass
    return naive.replace(tzinfo=timezone.utc), False

def parse_ics(text):
    events, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"summary": "", "start": None, "end": None, "allday": False, "rrule": None,
                   "uid": "", "recurrence_id": None, "exdate": set()}
        elif line == "END:VEVENT":
            if cur and cur["start"] is not None:
                # RFC 5545: an all-day (DATE) event with no/zero-length DTEND covers
                # exactly one day. Set the exclusive end so it never renders zero-width.
                if cur["allday"] and (cur["end"] is None or cur["end"] == cur["start"]):
                    cur["end"] = cur["start"] + timedelta(days=1)
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            name, _, value = line.partition(":")
            key, *parts = name.split(";")
            params = dict(p.split("=", 1) for p in parts if "=" in p)
            key = key.upper()
            if key == "SUMMARY":
                cur["summary"] = value
            elif key == "DTSTART":
                cur["start"], cur["allday"] = _parse_dt(value, params)
            elif key == "DTEND":
                cur["end"], _ = _parse_dt(value, params)
            elif key == "RRULE":
                cur["rrule"] = dict(kv.split("=", 1) for kv in value.split(";") if "=" in kv)
            elif key == "UID":
                cur["uid"] = value
            elif key == "RECURRENCE-ID":
                cur["recurrence_id"], _ = _parse_dt(value, params)
            elif key == "EXDATE":
                for v in value.split(","):
                    if v:
                        cur["exdate"].add(_parse_dt(v, params)[0])
    return events

def _rrule_until(rule):
    if "UNTIL" in rule:
        u = rule["UNTIL"]
        try:
            return datetime.strptime(u, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.strptime(u[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
    return None

def expand(events, window_start, window_end):
    # (uid, recurrence_id) of every override VEVENT — the matching generated occurrence
    # of the recurring series is suppressed (the override itself rides the non-recurring path).
    overrides = {(e.get("uid", ""), e["recurrence_id"])
                 for e in events if e.get("recurrence_id") is not None}
    out = []
    for e in events:
        rule = e.get("rrule")
        dur = (e["end"] - e["start"]) if e.get("end") else timedelta(0)
        if not rule:
            if e["start"] <= window_end and (e.get("end") or e["start"]) >= window_start:
                out.append({**e, "end": e["start"] + dur})
            continue
        uid = e.get("uid", "")
        exdates = e.get("exdate") or ()
        freq = rule.get("FREQ")
        interval = _pos_int(rule.get("INTERVAL"), 1)
        count = int(rule["COUNT"]) if "COUNT" in rule else None
        until = _rrule_until(rule)
        emitted = 0

        def _keep(occ):
            return occ not in exdates and (uid, occ) not in overrides

        if freq == "DAILY":
            cur = e["start"]; step = timedelta(days=interval)
            # No COUNT: arithmetically jump to the first occurrence >= window_start so we
            # don't iterate across all history. COUNT must count from DTSTART -> no jump.
            if count is None and cur < window_start:
                cur += ((window_start - cur) // step) * step
                if cur < window_start:
                    cur += step
            while cur <= window_end and (until is None or cur <= until):
                if cur >= window_start and _keep(cur):
                    out.append({**e, "start": cur, "end": cur + dur, "rrule": None})
                emitted += 1
                if count and emitted >= count:
                    break
                cur += step
        elif freq == "WEEKLY":
            bydays = [_WEEKDAYS[d] for d in rule.get("BYDAY", "").split(",") if d in _WEEKDAYS]
            if not bydays:
                bydays = [e["start"].weekday()]
            week0 = e["start"] - timedelta(days=e["start"].weekday())
            wk = 0
            # No COUNT: skip whole weeks ending before window_start (last weekday = base+6d).
            if count is None:
                week_step = timedelta(weeks=interval)
                target = window_start - timedelta(days=6)
                if week0 < target:
                    wk = (target - week0) // week_step
                    if week0 + wk * week_step < target:
                        wk += 1
            while True:
                base = week0 + timedelta(weeks=wk * interval)
                if base > window_end or (until and base > until):
                    break
                for wd in sorted(bydays):
                    occ = base.replace(hour=e["start"].hour, minute=e["start"].minute,
                                       second=e["start"].second) + timedelta(days=wd)
                    if occ < e["start"]:
                        continue
                    if until and occ > until:
                        continue
                    if occ > window_end:
                        continue
                    if occ >= window_start and _keep(occ):
                        out.append({**e, "start": occ, "end": occ + dur, "rrule": None})
                    emitted += 1
                    if count and emitted >= count:
                        break
                if count and emitted >= count:
                    break
                wk += 1
        else:  # MONTHLY/YEARLY/unknown -> original occurrence only
            if window_start <= e["start"] <= window_end and _keep(e["start"]):
                out.append({**e, "end": e["start"] + dur, "rrule": None})
    return out

def _calendar(config, now, errors):
    lookback = _pos_int(config.get("lookback_days"), 90)
    lookahead = _pos_int(config.get("lookahead_days"), 365)
    cap = _pos_int(config.get("max_events_grid"), 2000)
    sources = config.get("sources", []) or []
    w0 = now - timedelta(days=lookback)
    w1 = now + timedelta(days=lookahead)
    merged = []
    for src in sources:
        try:
            text = _http_get(src["ics_url"])
            for ev in expand(parse_ics(text), w0, w1):
                merged.append({
                    "title": ev["summary"],
                    "start": ev["start"].isoformat(),
                    "end": (ev["end"] or ev["start"]).isoformat(),
                    "allday": ev["allday"],
                    "source": src.get("name", ""),
                    "color": src.get("color", "#888"),
                    "_sortkey": ev["start"],
                })
        except Exception as e:                           # noqa: BLE001
            errors.append({"source": src.get("name", ""), "error": str(e)})
    merged.sort(key=lambda e: e["_sortkey"])
    truncated = len(merged) > cap
    events = merged[:cap]
    for e in events:
        del e["_sortkey"]
    return events, truncated

# ── entry point ───────────────────────────────────────────────────────────
def fetch(config, now=None):
    cfg = config or {}
    location = (cfg.get("location") or "Warsaw").strip()
    news_locale = cfg.get("news_locale") or "pl-PL"
    news_feeds = cfg.get("news_feeds")
    if news_feeds is None:
        news_feeds = _DEFAULT_FEEDS
    news_cap = _pos_int(cfg.get("max_news"), 10)
    now = now or datetime.now(timezone.utc)

    errors, weather = [], None
    try:
        weather = _weather(location)
    except Exception as e:  # noqa: BLE001
        errors.append({"weather": str(e)})
    news = _news(location, news_locale, news_feeds, news_cap, errors)
    events, truncated = _calendar(cfg, now, errors)

    out = {"weather": weather, "news": news, "events": events,
           "max_events": _pos_int(cfg.get("max_events"), 5), "generated": now.isoformat()}
    if truncated:
        out["truncated"] = True
    if errors:
        out["errors"] = errors
    return out
