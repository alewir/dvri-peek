from pathlib import Path
H = Path("plugins/calendar/view.html").read_text()

def test_view_fetches_data_and_ctx():
    assert "/plugin/calendar/data" in H and "ctx" in H

def test_view_has_agenda_and_month_and_controls():
    assert "agenda" in H                       # small view
    assert "cal-month" in H                    # month grid container
    assert "cal-prev" in H and "cal-next" in H and "cal-today" in H and "cal-mode" in H
    assert "cal.viewmode" in H                 # mode persisted in localStorage
    assert "splitSpanByWeek" in H and "assignLanes" in H   # spanning helpers present

def test_view_has_week_grid():
    assert "cal-week" in H and "renderWeek" in H and "cal-allday" in H

def test_view_wires_polish_followups():
    # FOLLOW-UP A: month cells built via calendar-date overflow (DST-safe), not ms math
    assert "getDate()+idx" in H and "gridStart.getTime()+idx*MS_DAY" not in H
    # FOLLOW-UP B: small-agenda size driven by backend max_events (was hardcoded 5)
    assert "MAXAG=d.max_events||5" in H and "const max=MAXAG" in H
    # FOLLOW-UP C: week scroll-to-07:00 gated to first-paint / nav (preserve on refresh)
    assert "lastWeekKey" in H and "prevScroll" in H
    # BLOCKER 2 belt-and-suspenders: all-day exclusive end clamped to >= start+1
    assert "Math.max(eend,s+1)" in H and "Math.max(dnum(new Date(e.end||e.start)),s+1)" in H
