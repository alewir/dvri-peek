# tests/test_calendar.py
import importlib.util
from datetime import datetime, timezone, timedelta
from pathlib import Path

def _backend():
    spec = importlib.util.spec_from_file_location("cal_backend", "plugins/calendar/backend.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

def test_parse_timed_and_allday():
    b = _backend()
    evs = b.parse_ics(Path("tests/fixtures/cal_a.ics").read_text())
    s = {e["summary"]: e for e in evs}
    assert s["One Off"]["allday"] is False
    assert s["One Off"]["start"] == datetime(2026, 6, 29, 9, 0, tzinfo=timezone.utc)
    assert s["All Day"]["allday"] is True

def test_rrule_daily_count_expands():
    b = _backend()
    evs = b.parse_ics(Path("tests/fixtures/cal_b.ics").read_text())
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    w1 = w0 + timedelta(days=10)
    occ = [e for e in b.expand(evs, w0, w1) if e["summary"] == "Daily Standup"]
    assert len(occ) == 3
    # 3 daily occurrences spanning the month boundary: Jun 29, Jun 30, Jul 1
    assert {e["start"].day for e in occ} == {29, 30, 1}
    assert sorted(e["start"].date().isoformat() for e in occ) == \
        ["2026-06-29", "2026-06-30", "2026-07-01"]

def test_fetch_merges_sorts_colors(monkeypatch):
    b = _backend()
    feeds = {"A": Path("tests/fixtures/cal_a.ics").read_text(),
             "B": Path("tests/fixtures/cal_b.ics").read_text()}
    monkeypatch.setattr(b, "_http_get", lambda url: feeds[url])
    out = b.fetch({"max_events": 10, "lookahead_days": 30,
                   "sources": [{"name": "A", "color": "#111", "ics_url": "A"},
                               {"name": "B", "color": "#222", "ics_url": "B"}]},
                  now=datetime(2026, 6, 28, tzinfo=timezone.utc))
    assert "errors" not in out                      # healthy fetch sets no errors key
    starts = [e["start"] for e in out["events"]]
    assert starts == sorted(starts)                 # merged + sorted
    assert any(e["source"] == "B" and e["color"] == "#222" for e in out["events"])
    assert len(out["events"]) <= 10

def test_fetch_bad_url_is_graceful(monkeypatch):
    b = _backend()
    def boom(url): raise OSError("dns")
    monkeypatch.setattr(b, "_http_get", boom)
    out = b.fetch({"sources": [{"name": "X", "color": "#000", "ics_url": "http://x"}]})
    assert out["events"] == [] and "errors" in out

def test_parse_tzid_converts_to_utc():
    b = _backend()
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        "BEGIN:VEVENT\r\nUID:tz1\r\nSUMMARY:Warsaw Meeting\r\n"
        "DTSTART;TZID=Europe/Warsaw:20260629T090000\r\n"
        "DTEND;TZID=Europe/Warsaw:20260629T100000\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    evs = b.parse_ics(ics)
    assert len(evs) == 1
    # Warsaw is UTC+2 in summer, so 09:00 local = 07:00 UTC
    assert evs[0]["start"] == datetime(2026, 6, 29, 7, 0, tzinfo=timezone.utc)

def test_rrule_weekly_byday():
    b = _backend()
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        "BEGIN:VEVENT\r\nUID:wk1\r\nSUMMARY:Weekly\r\n"
        "DTSTART:20260629T090000Z\r\n"
        "DTEND:20260629T100000Z\r\n"
        "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    evs = b.parse_ics(ics)
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    w1 = w0 + timedelta(days=30)
    occ = b.expand(evs, w0, w1)
    dates = sorted(e["start"].date().isoformat() for e in occ)
    assert dates == ["2026-06-29", "2026-07-01", "2026-07-06", "2026-07-08"]

def test_fetch_uses_broad_window_and_cap(monkeypatch):
    b = _backend()
    # one event ~200 days out must be INCLUDED with the wide default lookahead
    far = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:f\r\nSUMMARY:Far\r\n" \
          "DTSTART:20270115T090000Z\r\nDTEND:20270115T100000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    monkeypatch.setattr(b, "_http_get", lambda url: far)
    out = b.fetch({"sources": [{"name": "A", "color": "#111", "ics_url": "A"}]},
                  now=datetime(2026, 6, 28, tzinfo=timezone.utc))
    assert any(e["title"] == "Far" for e in out["events"])     # 200d out, inside 365d window
    assert "errors" not in out

def test_fetch_caps_at_max_events_grid(monkeypatch):
    b = _backend()
    body = ["BEGIN:VCALENDAR"]
    for i in range(50):
        body += ["BEGIN:VEVENT", f"UID:e{i}", "SUMMARY:E",
                 "DTSTART:20260701T090000Z", "DTEND:20260701T093000Z",
                 f"RRULE:FREQ=DAILY;COUNT=20", "END:VEVENT"]  # 50*20 = 1000 occurrences
    body.append("END:VCALENDAR")
    monkeypatch.setattr(b, "_http_get", lambda url: "\r\n".join(body))
    out = b.fetch({"max_events_grid": 100, "sources": [{"name": "A", "color": "#1", "ics_url": "A"}]},
                  now=datetime(2026, 6, 28, tzinfo=timezone.utc))
    assert len(out["events"]) == 100

def test_allday_multiday_exclusive_end():
    b = _backend()
    evs = b.parse_ics(Path("tests/fixtures/cal_multiday.ics").read_text())
    assert len(evs) == 1 and evs[0]["allday"] is True
    # DTSTART 07-03, DTEND 07-08 (exclusive) -> covers 07-03..07-07
    assert evs[0]["start"] == datetime(2026, 7, 3, tzinfo=timezone.utc)
    assert evs[0]["end"] == datetime(2026, 7, 8, tzinfo=timezone.utc)
