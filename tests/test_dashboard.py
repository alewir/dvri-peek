# tests/test_dashboard.py — backend for the combined clock+calendar dashboard plugin.
# Covers weather (Open-Meteo), news (RSS merge), calendar (ICS parse/recurrence/merge),
# and the integrated fetch() that returns all three. Calendar behaviour is tested via the
# internal _calendar() helper so a stubbed _http_get does not entangle weather/news.
import importlib.util
from datetime import datetime, timezone, timedelta

from tests.conftest import ROOT

FX = ROOT / "tests" / "fixtures"

def _backend():
    spec = importlib.util.spec_from_file_location(
        "dash_backend", str(ROOT / "plugins" / "dashboard" / "backend.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

# ── weather ────────────────────────────────────────────────────────────────
def test_weather_parses_and_maps_code(monkeypatch):
    b = _backend()
    geo = (FX / "clock_geocode.json").read_text(); fc = (FX / "clock_forecast.json").read_text()
    monkeypatch.setattr(b, "_http_get", lambda url: geo if "geocoding-api" in url else fc)
    w = b._weather("Tychy")
    assert w["location_name"] == "Tychy"
    assert w["temp"] == 21 and w["units"] == "°C"
    assert w["text"] == "Clear" and w["emoji"] == "☀"     # WMO 0
    assert w["today"] == {"hi": 24, "lo": 13}
    assert len(w["forecast"]) == 5 and w["forecast"][0]["day"] == "Wed"  # today + next 5 days; [0]=2026-07-01

def test_geocode_latlon_bypasses_http(monkeypatch):
    b = _backend()
    calls = []
    monkeypatch.setattr(b, "_http_get", lambda url: calls.append(url) or "{}")
    lat, lon, name = b._geocode("50.13,18.99")
    assert (lat, lon) == (50.13, 18.99) and not any("geocoding" in c for c in calls)

# ── news ───────────────────────────────────────────────────────────────────
def test_parse_rss_and_merge_sort_cap(monkeypatch):
    b = _backend()
    xml = (FX / "clock_news.xml").read_text()
    monkeypatch.setattr(b, "_http_get", lambda url: xml)   # every feed returns the same 2 items
    errors = []
    items = b._news("Tychy", "pl-PL", ["http://a", "http://b"], 3, errors)
    assert errors == []
    assert [i["title"] for i in items] == ["Newer headline", "Newer headline", "Newer headline"]
    assert items[0]["source"] == "Test Feed"
    assert "T" in items[0]["published"]
    assert "_sort" not in items[0]

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
    items = b._news("50.1,19.0", "pl-PL", ["http://bad", "http://good"], 10, errors)
    assert any("bad" in e["feed"] for e in errors)
    assert len(items) == 4                                  # local(2) + good(2) survived

def test_local_feed_url_from_locale():
    b = _backend()
    url = b._local_feed("Tychy", "pl-PL")
    assert "news.google.com/rss/search" in url
    assert "q=Tychy" in url and "hl=pl" in url and "gl=PL" in url and "ceid=PL:pl" in url

# ── calendar parse / recurrence (pure) ──────────────────────────────────────
def test_parse_timed_and_allday():
    b = _backend()
    evs = b.parse_ics((FX / "cal_a.ics").read_text())
    s = {e["summary"]: e for e in evs}
    assert s["One Off"]["allday"] is False
    assert s["One Off"]["start"] == datetime(2026, 6, 29, 9, 0, tzinfo=timezone.utc)
    assert s["All Day"]["allday"] is True

def test_rrule_daily_count_expands():
    b = _backend()
    evs = b.parse_ics((FX / "cal_b.ics").read_text())
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    occ = [e for e in b.expand(evs, w0, w0 + timedelta(days=10)) if e["summary"] == "Daily Standup"]
    assert len(occ) == 3
    assert sorted(e["start"].date().isoformat() for e in occ) == \
        ["2026-06-29", "2026-06-30", "2026-07-01"]

def test_parse_tzid_converts_to_utc():
    b = _backend()
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:tz1\r\nSUMMARY:Warsaw Meeting\r\n"
           "DTSTART;TZID=Europe/Warsaw:20260629T090000\r\nDTEND;TZID=Europe/Warsaw:20260629T100000\r\n"
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
    evs = b.parse_ics(ics)
    assert len(evs) == 1
    assert evs[0]["start"] == datetime(2026, 6, 29, 7, 0, tzinfo=timezone.utc)  # UTC+2 summer

def test_rrule_weekly_byday():
    b = _backend()
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:wk1\r\nSUMMARY:Weekly\r\n"
           "DTSTART:20260629T090000Z\r\nDTEND:20260629T100000Z\r\n"
           "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    evs = b.parse_ics(ics)
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    occ = b.expand(evs, w0, w0 + timedelta(days=30))
    assert sorted(e["start"].date().isoformat() for e in occ) == \
        ["2026-06-29", "2026-07-01", "2026-07-06", "2026-07-08"]

def test_allday_multiday_exclusive_end():
    b = _backend()
    evs = b.parse_ics((FX / "cal_multiday.ics").read_text())
    assert len(evs) == 1 and evs[0]["allday"] is True
    assert evs[0]["start"] == datetime(2026, 7, 3, tzinfo=timezone.utc)
    assert evs[0]["end"] == datetime(2026, 7, 8, tzinfo=timezone.utc)   # exclusive

def test_rrule_daily_interval_zero_terminates():
    b = _backend()
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:d0\r\nSUMMARY:Z\r\n"
           "DTSTART:20260629T090000Z\r\nDTEND:20260629T093000Z\r\n"
           "RRULE:FREQ=DAILY;INTERVAL=0\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    occ = b.expand(b.parse_ics(ics), datetime(2026, 6, 28, tzinfo=timezone.utc),
                   datetime(2026, 7, 8, tzinfo=timezone.utc))
    assert 0 < len(occ) <= 12          # INTERVAL=0 -> 1: bounded, no infinite loop

def test_rrule_weekly_interval_zero_terminates():
    b = _backend()
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:w0\r\nSUMMARY:Z\r\n"
           "DTSTART:20260629T090000Z\r\nDTEND:20260629T093000Z\r\n"
           "RRULE:FREQ=WEEKLY;INTERVAL=0\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    occ = b.expand(b.parse_ics(ics), datetime(2026, 6, 28, tzinfo=timezone.utc),
                   datetime(2026, 7, 19, tzinfo=timezone.utc))
    assert 0 < len(occ) <= 6

def test_allday_endless_end_is_start_plus_one():
    b = _backend()
    evs = b.parse_ics((FX / "cal_endless_allday.ics").read_text())
    assert len(evs) == 1 and evs[0]["allday"] is True
    assert evs[0]["start"] == datetime(2026, 7, 4, tzinfo=timezone.utc)
    assert evs[0]["end"] == datetime(2026, 7, 5, tzinfo=timezone.utc)   # end-less -> +1 day

def test_exdate_suppresses_one_occurrence():
    b = _backend()
    occ = b.expand(b.parse_ics((FX / "cal_exdate.ics").read_text()),
                   datetime(2026, 6, 28, tzinfo=timezone.utc), datetime(2026, 7, 28, tzinfo=timezone.utc))
    assert sorted(e["start"].date().isoformat() for e in occ) == \
        ["2026-06-29", "2026-07-13", "2026-07-20"]    # Jul6 EXDATE'd

def test_exdate_parses_multiple_comma_values_with_tzid():
    b = _backend()
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:exm\r\nSUMMARY:M\r\n"
           "DTSTART:20260629T090000Z\r\nDTEND:20260629T093000Z\r\nRRULE:FREQ=DAILY\r\n"
           "EXDATE;TZID=Europe/Warsaw:20260630T110000,20260701T110000\r\n"
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
    evs = b.parse_ics(ics)
    assert evs[0]["exdate"] == {datetime(2026, 6, 30, 9, 0, tzinfo=timezone.utc),
                                datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)}
    occ = b.expand(evs, datetime(2026, 6, 28, tzinfo=timezone.utc), datetime(2026, 7, 3, tzinfo=timezone.utc))
    dates = sorted(e["start"].date().isoformat() for e in occ)
    assert "2026-06-30" not in dates and "2026-07-01" not in dates and "2026-06-29" in dates

def test_recurrence_id_override_replaces_occurrence():
    b = _backend()
    occ = [e for e in b.expand(b.parse_ics((FX / "cal_override.ics").read_text()),
                               datetime(2026, 6, 28, tzinfo=timezone.utc), datetime(2026, 7, 8, tzinfo=timezone.utc))
           if e["summary"] == "Daily Series"]
    assert sorted(e["start"] for e in occ) == [
        datetime(2026, 6, 29, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 30, 14, 0, tzinfo=timezone.utc),   # moved from 09:00
        datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)]

def test_daily_no_count_expands_only_within_window():
    b = _backend()
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:old\r\nSUMMARY:Old Daily\r\n"
           "DTSTART:20240630T090000Z\r\nDTEND:20240630T093000Z\r\nRRULE:FREQ=DAILY\r\n"
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
    occ = b.expand(b.parse_ics(ics), datetime(2026, 6, 28, tzinfo=timezone.utc),
                   datetime(2026, 7, 8, tzinfo=timezone.utc))
    assert len(occ) <= 12 and sorted(e["start"].date().isoformat() for e in occ)[0] == "2026-06-28"

def test_daily_count_counts_from_dtstart_not_window():
    b = _backend()
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:oc\r\nSUMMARY:Old Count\r\n"
           "DTSTART:20240630T090000Z\r\nDTEND:20240630T093000Z\r\nRRULE:FREQ=DAILY;COUNT=3\r\n"
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
    assert b.expand(b.parse_ics(ics), datetime(2026, 6, 28, tzinfo=timezone.utc),
                    datetime(2026, 7, 8, tzinfo=timezone.utc)) == []

def test_weekly_no_count_fast_forwards_to_window():
    b = _backend()
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:ow\r\nSUMMARY:Old Weekly\r\n"
           "DTSTART:20240701T090000Z\r\nDTEND:20240701T093000Z\r\nRRULE:FREQ=WEEKLY;BYDAY=MO\r\n"
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
    occ = b.expand(b.parse_ics(ics), datetime(2026, 6, 28, tzinfo=timezone.utc),
                   datetime(2026, 7, 19, tzinfo=timezone.utc))
    assert sorted(e["start"].date().isoformat() for e in occ) == \
        ["2026-06-29", "2026-07-06", "2026-07-13"]

# ── calendar merge (multiple ICS -> one view) via _calendar() ───────────────
def test_multiple_calendars_merge_into_one_view(monkeypatch):
    b = _backend()
    feeds = {"A": (FX / "cal_a.ics").read_text(), "B": (FX / "cal_b.ics").read_text()}
    monkeypatch.setattr(b, "_http_get", lambda url: feeds[url])
    errors = []
    events, trunc = b._calendar(
        {"lookahead_days": 30, "sources": [{"name": "A", "color": "#111", "ics_url": "A"},
                                           {"name": "B", "color": "#222", "ics_url": "B"}]},
        datetime(2026, 6, 28, tzinfo=timezone.utc), errors)
    assert errors == [] and trunc is False
    starts = [e["start"] for e in events]
    assert starts == sorted(starts)                                  # merged + chronological
    assert any(e["source"] == "A" and e["color"] == "#111" for e in events)   # source A retained + colored
    assert any(e["source"] == "B" and e["color"] == "#222" for e in events)   # source B retained + colored
    assert len(events) == 5                                          # cal_a(2) + cal_b DAILY COUNT=3

def test_calendar_bad_url_graceful(monkeypatch):
    b = _backend()
    def boom(url): raise OSError("dns")
    monkeypatch.setattr(b, "_http_get", boom)
    errors = []
    events, trunc = b._calendar({"sources": [{"name": "X", "color": "#000", "ics_url": "http://x"}]},
                                datetime(2026, 6, 28, tzinfo=timezone.utc), errors)
    assert events == [] and any(e.get("source") == "X" for e in errors)

def test_calendar_broad_window(monkeypatch):
    b = _backend()
    feed = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:near\r\nSUMMARY:Near\r\n"
            "DTSTART:20270623T090000Z\r\nDTEND:20270623T100000Z\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:far\r\nSUMMARY:Far\r\n"
            "DTSTART:20270703T090000Z\r\nDTEND:20270703T100000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    monkeypatch.setattr(b, "_http_get", lambda url: feed)
    events, _ = b._calendar({"sources": [{"name": "A", "color": "#111", "ics_url": "A"}]},
                            datetime(2026, 6, 28, tzinfo=timezone.utc), [])
    titles = {e["title"] for e in events}
    assert "Near" in titles and "Far" not in titles          # 365d default window, not unbounded

def test_calendar_caps_at_max_events_grid(monkeypatch):
    b = _backend()
    body = ["BEGIN:VCALENDAR"]
    for i in range(50):
        body += ["BEGIN:VEVENT", f"UID:e{i}", "SUMMARY:E", "DTSTART:20260701T090000Z",
                 "DTEND:20260701T093000Z", "RRULE:FREQ=DAILY;COUNT=20", "END:VEVENT"]
    body.append("END:VCALENDAR")
    monkeypatch.setattr(b, "_http_get", lambda url: "\r\n".join(body))
    events, trunc = b._calendar({"max_events_grid": 100, "sources": [{"name": "A", "color": "#1", "ics_url": "A"}]},
                                datetime(2026, 6, 28, tzinfo=timezone.utc), [])
    assert len(events) == 100 and trunc is True

def test_calendar_zero_config_falls_back_to_defaults(monkeypatch):
    b = _backend()
    far = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:f\r\nSUMMARY:Far\r\n"
           "DTSTART:20270115T090000Z\r\nDTEND:20270115T100000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    monkeypatch.setattr(b, "_http_get", lambda url: far)
    events, _ = b._calendar({"lookback_days": "0", "lookahead_days": "0", "max_events_grid": "0",
                             "sources": [{"name": "A", "color": "#111", "ics_url": "A"}]},
                            datetime(2026, 6, 28, tzinfo=timezone.utc), [])
    assert any(e["title"] == "Far" for e in events)           # lookahead "0" -> 365 default

# ── integrated fetch() (weather + news + calendar in one payload) ────────────
def _integration_http(geo, fc, rss, ics):
    def http(url):
        if "geocoding-api" in url:
            return geo
        if "open-meteo" in url:
            return fc
        if "news.google.com" in url or url.startswith("http://feed"):
            return rss
        return ics
    return http

def test_fetch_integrates_weather_news_calendar(monkeypatch):
    b = _backend()
    http = _integration_http((FX / "clock_geocode.json").read_text(),
                             (FX / "clock_forecast.json").read_text(),
                             (FX / "clock_news.xml").read_text(),
                             (FX / "cal_a.ics").read_text())
    monkeypatch.setattr(b, "_http_get", http)
    out = b.fetch({"location": "Tychy", "news_feeds": ["http://feed"],
                   "sources": [{"name": "A", "color": "#111", "ics_url": "A"}]},
                  now=datetime(2026, 6, 28, tzinfo=timezone.utc))
    assert set(out) >= {"weather", "news", "events", "max_events", "generated"}
    assert out["weather"]["location_name"] == "Tychy"        # weather present
    assert len(out["news"]) > 0                                # news present
    assert len(out["events"]) > 0                             # calendar present
    assert "errors" not in out                                # all three healthy

def test_fetch_partial_on_weather_failure(monkeypatch):
    b = _backend()
    xml = (FX / "clock_news.xml").read_text()
    ics = (FX / "cal_a.ics").read_text()
    def http(url):
        if "open-meteo" in url or "geocoding-api" in url:
            raise OSError("weather down")
        if "news.google.com" in url or url.startswith("http://feed"):
            return xml
        return ics
    monkeypatch.setattr(b, "_http_get", http)
    out = b.fetch({"location": "Tychy", "news_feeds": ["http://feed"],
                   "sources": [{"name": "A", "color": "#111", "ics_url": "A"}]},
                  now=datetime(2026, 6, 28, tzinfo=timezone.utc))
    assert out["weather"] is None and "errors" in out         # weather failed, isolated
    assert len(out["news"]) > 0 and len(out["events"]) > 0     # news + calendar unaffected

def test_fetch_reports_max_events(monkeypatch):
    b = _backend()
    http = _integration_http((FX / "clock_geocode.json").read_text(),
                             (FX / "clock_forecast.json").read_text(),
                             (FX / "clock_news.xml").read_text(),
                             (FX / "cal_a.ics").read_text())
    monkeypatch.setattr(b, "_http_get", http)
    base = {"location": "Tychy", "sources": [{"name": "A", "color": "#111", "ics_url": "A"}]}
    now = datetime(2026, 6, 28, tzinfo=timezone.utc)
    assert b.fetch(base, now=now)["max_events"] == 5                        # default 5
    assert b.fetch({**base, "max_events": 8}, now=now)["max_events"] == 8   # override honored
    assert b.fetch({**base, "max_events": "0"}, now=now)["max_events"] == 5  # invalid -> default
