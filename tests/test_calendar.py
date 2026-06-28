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
                               {"name": "B", "color": "#222", "ics_url": "B"}]})
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
