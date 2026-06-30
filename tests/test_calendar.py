# tests/test_calendar.py
import importlib.util
from datetime import datetime, timezone, timedelta

from tests.conftest import ROOT

FIXTURES = ROOT / "tests" / "fixtures"

def _backend():
    spec = importlib.util.spec_from_file_location(
        "cal_backend", str(ROOT / "plugins" / "calendar" / "backend.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

def test_parse_timed_and_allday():
    b = _backend()
    evs = b.parse_ics((FIXTURES / "cal_a.ics").read_text())
    s = {e["summary"]: e for e in evs}
    assert s["One Off"]["allday"] is False
    assert s["One Off"]["start"] == datetime(2026, 6, 29, 9, 0, tzinfo=timezone.utc)
    assert s["All Day"]["allday"] is True

def test_rrule_daily_count_expands():
    b = _backend()
    evs = b.parse_ics((FIXTURES / "cal_b.ics").read_text())
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
    feeds = {"A": (FIXTURES / "cal_a.ics").read_text(),
             "B": (FIXTURES / "cal_b.ics").read_text()}
    monkeypatch.setattr(b, "_http_get", lambda url: feeds[url])
    out = b.fetch({"lookahead_days": 30,
                   "sources": [{"name": "A", "color": "#111", "ics_url": "A"},
                               {"name": "B", "color": "#222", "ics_url": "B"}]},
                  now=datetime(2026, 6, 28, tzinfo=timezone.utc))
    assert "errors" not in out                      # healthy fetch sets no errors key
    starts = [e["start"] for e in out["events"]]
    assert starts == sorted(starts)                 # merged + sorted
    assert any(e["source"] == "B" and e["color"] == "#222" for e in out["events"])
    assert len(out["events"]) == 5                  # cal_a(2) + cal_b DAILY COUNT=3 within 30d

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

def test_fetch_uses_broad_window(monkeypatch):
    b = _backend()
    # now=2026-06-28; default lookahead is 365d -> window ends 2027-06-28.
    # An event at ~360d (2027-06-23) is IN; one at ~370d (2027-07-03) is OUT.
    # This brackets the 365d default from both sides (locks it precisely).
    feed = ("BEGIN:VCALENDAR\r\n"
            "BEGIN:VEVENT\r\nUID:near\r\nSUMMARY:Near\r\n"
            "DTSTART:20270623T090000Z\r\nDTEND:20270623T100000Z\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:far\r\nSUMMARY:Far\r\n"
            "DTSTART:20270703T090000Z\r\nDTEND:20270703T100000Z\r\nEND:VEVENT\r\n"
            "END:VCALENDAR\r\n")
    monkeypatch.setattr(b, "_http_get", lambda url: feed)
    out = b.fetch({"sources": [{"name": "A", "color": "#111", "ics_url": "A"}]},
                  now=datetime(2026, 6, 28, tzinfo=timezone.utc))
    titles = {e["title"] for e in out["events"]}
    assert "Near" in titles        # ~360d out, inside the 365d default window
    assert "Far" not in titles     # ~370d out, beyond it -> default is 365, not unbounded
    assert "errors" not in out

def test_fetch_caps_at_max_events_grid(monkeypatch):
    b = _backend()
    body = ["BEGIN:VCALENDAR"]
    for i in range(50):
        body += ["BEGIN:VEVENT", f"UID:e{i}", "SUMMARY:E",
                 "DTSTART:20260701T090000Z", "DTEND:20260701T093000Z",
                 "RRULE:FREQ=DAILY;COUNT=20", "END:VEVENT"]  # 50*20 = 1000 occurrences
    body.append("END:VCALENDAR")
    monkeypatch.setattr(b, "_http_get", lambda url: "\r\n".join(body))
    out = b.fetch({"max_events_grid": 100, "sources": [{"name": "A", "color": "#1", "ics_url": "A"}]},
                  now=datetime(2026, 6, 28, tzinfo=timezone.utc))
    assert len(out["events"]) == 100
    assert out["truncated"] is True                 # cap flag is the spec-visible contract

def test_allday_multiday_exclusive_end():
    b = _backend()
    evs = b.parse_ics((FIXTURES / "cal_multiday.ics").read_text())
    assert len(evs) == 1 and evs[0]["allday"] is True
    # DTSTART 07-03, DTEND 07-08 (exclusive) -> covers 07-03..07-07
    assert evs[0]["start"] == datetime(2026, 7, 3, tzinfo=timezone.utc)
    assert evs[0]["end"] == datetime(2026, 7, 8, tzinfo=timezone.utc)

# ── BLOCKER 1: RRULE INTERVAL=0 must not infinite-loop (DoS) ──────────────────
# Causal: a zero step never advances `cur`/`base`, so a no-COUNT/no-UNTIL rule would
# loop forever. _pos_int coerces INTERVAL=0 -> 1, so expand() terminates with a
# small, finite count bounded by the window. (If the fix regresses, these HANG.)
def test_rrule_daily_interval_zero_terminates():
    b = _backend()
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:d0\r\nSUMMARY:Z\r\n"
           "DTSTART:20260629T090000Z\r\nDTEND:20260629T093000Z\r\n"
           "RRULE:FREQ=DAILY;INTERVAL=0\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    evs = b.parse_ics(ics)
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    occ = b.expand(evs, w0, w0 + timedelta(days=10))
    assert 0 < len(occ) <= 12          # INTERVAL=0 -> 1: daily, bounded by the window

def test_rrule_weekly_interval_zero_terminates():
    b = _backend()
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:w0\r\nSUMMARY:Z\r\n"
           "DTSTART:20260629T090000Z\r\nDTEND:20260629T093000Z\r\n"
           "RRULE:FREQ=WEEKLY;INTERVAL=0\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    evs = b.parse_ics(ics)
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    occ = b.expand(evs, w0, w0 + timedelta(days=21))
    assert 0 < len(occ) <= 6           # INTERVAL=0 -> 1: weekly, bounded by the window

# ── BLOCKER 2: end-less all-day event covers exactly one day (RFC 5545) ───────
def test_allday_endless_end_is_start_plus_one():
    b = _backend()
    evs = b.parse_ics((FIXTURES / "cal_endless_allday.ics").read_text())
    assert len(evs) == 1 and evs[0]["allday"] is True
    assert evs[0]["start"] == datetime(2026, 7, 4, tzinfo=timezone.utc)
    # no DTEND -> exclusive end is start + 1 day (so it never renders zero-width)
    assert evs[0]["end"] == datetime(2026, 7, 5, tzinfo=timezone.utc)

def test_fetch_includes_endless_allday(monkeypatch):
    b = _backend()
    feed = (FIXTURES / "cal_endless_allday.ics").read_text()
    monkeypatch.setattr(b, "_http_get", lambda url: feed)
    out = b.fetch({"sources": [{"name": "A", "color": "#111", "ics_url": "A"}]},
                  now=datetime(2026, 7, 1, tzinfo=timezone.utc))
    ev = [e for e in out["events"] if e["title"] == "Holiday"]
    assert len(ev) == 1 and ev[0]["allday"] is True
    assert ev[0]["end"] == datetime(2026, 7, 5, tzinfo=timezone.utc).isoformat()

# ── BLOCKER 1 / FOLLOW-UP B: config coercion via _pos_int ────────────────────
def test_fetch_zero_config_falls_back_to_defaults(monkeypatch):
    b = _backend()
    # ~200 days out: only included if lookahead_days "0" falls back to 365 (not 0)
    far = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:f\r\nSUMMARY:Far\r\n"
           "DTSTART:20270115T090000Z\r\nDTEND:20270115T100000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    monkeypatch.setattr(b, "_http_get", lambda url: far)
    out = b.fetch({"lookback_days": "0", "lookahead_days": "0", "max_events_grid": "0",
                   "sources": [{"name": "A", "color": "#111", "ics_url": "A"}]},
                  now=datetime(2026, 6, 28, tzinfo=timezone.utc))
    assert any(e["title"] == "Far" for e in out["events"])   # lookahead "0" -> 365 default

def test_fetch_reports_max_events(monkeypatch):
    b = _backend()
    feed = (FIXTURES / "cal_a.ics").read_text()
    monkeypatch.setattr(b, "_http_get", lambda url: feed)
    base = {"sources": [{"name": "A", "color": "#111", "ics_url": "A"}]}
    now = datetime(2026, 6, 28, tzinfo=timezone.utc)
    assert b.fetch(base, now=now)["max_events"] == 5                        # default 5
    assert b.fetch({**base, "max_events": 8}, now=now)["max_events"] == 8   # override honored
    assert b.fetch({**base, "max_events": "0"}, now=now)["max_events"] == 5  # invalid -> default

# ── EXDATE: cancelled instances are suppressed, others remain ─────────────────
def test_exdate_suppresses_one_occurrence():
    b = _backend()
    evs = b.parse_ics((FIXTURES / "cal_exdate.ics").read_text())
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    occ = b.expand(evs, w0, w0 + timedelta(days=30))
    dates = sorted(e["start"].date().isoformat() for e in occ)
    # Mondays Jun29, Jul6, Jul13, Jul20; EXDATE removes Jul6 (COUNT still counts it)
    assert dates == ["2026-06-29", "2026-07-13", "2026-07-20"]

def test_exdate_parses_multiple_comma_values_with_tzid():
    b = _backend()
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        "BEGIN:VEVENT\r\nUID:exm\r\nSUMMARY:M\r\n"
        "DTSTART:20260629T090000Z\r\nDTEND:20260629T093000Z\r\n"
        "RRULE:FREQ=DAILY\r\n"
        "EXDATE;TZID=Europe/Warsaw:20260630T110000,20260701T110000\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    evs = b.parse_ics(ics)
    # Warsaw 11:00 summer = 09:00 UTC -> both occurrences cancelled
    assert evs[0]["exdate"] == {
        datetime(2026, 6, 30, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
    }
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    occ = b.expand(evs, w0, w0 + timedelta(days=5))
    dates = sorted(e["start"].date().isoformat() for e in occ)
    assert "2026-06-30" not in dates and "2026-07-01" not in dates
    assert "2026-06-29" in dates

# ── RECURRENCE-ID override: moved instance replaces the original occurrence ────
def test_recurrence_id_override_replaces_occurrence():
    b = _backend()
    evs = b.parse_ics((FIXTURES / "cal_override.ics").read_text())
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    occ = [e for e in b.expand(evs, w0, w0 + timedelta(days=10))
           if e["summary"] == "Daily Series"]
    starts = sorted(e["start"] for e in occ)
    # original Jun30 09:00 suppressed; override at Jun30 14:00 emitted instead
    assert datetime(2026, 6, 30, 9, 0, tzinfo=timezone.utc) not in starts
    assert datetime(2026, 6, 30, 14, 0, tzinfo=timezone.utc) in starts
    assert starts == [
        datetime(2026, 6, 29, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 30, 14, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
    ]

# ── Expand from window_start: no-COUNT series fast-forwards; COUNT counts from DTSTART
def test_daily_no_count_expands_only_within_window():
    b = _backend()
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:old\r\nSUMMARY:Old Daily\r\n"
           "DTSTART:20240630T090000Z\r\nDTEND:20240630T093000Z\r\n"
           "RRULE:FREQ=DAILY\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    evs = b.parse_ics(ics)
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    occ = b.expand(evs, w0, w0 + timedelta(days=10))
    dates = sorted(e["start"].date().isoformat() for e in occ)
    # DTSTART 2 years ago, no COUNT -> only ~window occurrences, not hundreds
    assert len(occ) <= 12
    assert dates[0] == "2026-06-28"
    assert dates[-1] == "2026-07-07"

def test_daily_count_counts_from_dtstart_not_window():
    b = _backend()
    # COUNT=3 from 2024 -> all 3 occurrences are long before the 2026 window
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:oc\r\nSUMMARY:Old Count\r\n"
           "DTSTART:20240630T090000Z\r\nDTEND:20240630T093000Z\r\n"
           "RRULE:FREQ=DAILY;COUNT=3\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    evs = b.parse_ics(ics)
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    occ = b.expand(evs, w0, w0 + timedelta(days=10))
    assert occ == []

def test_weekly_no_count_fast_forwards_to_window():
    b = _backend()
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:ow\r\nSUMMARY:Old Weekly\r\n"
           "DTSTART:20240701T090000Z\r\nDTEND:20240701T093000Z\r\n"  # Mon 2024-07-01
           "RRULE:FREQ=WEEKLY;BYDAY=MO\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    evs = b.parse_ics(ics)
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    occ = b.expand(evs, w0, w0 + timedelta(days=21))
    dates = sorted(e["start"].date().isoformat() for e in occ)
    assert dates == ["2026-06-29", "2026-07-06", "2026-07-13"]  # Mondays in window
