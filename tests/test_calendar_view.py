from tests.conftest import ROOT

H = (ROOT / "plugins" / "calendar" / "view.html").read_text()


def test_view_fetches_data_via_plugin_endpoint():
    # the view pulls events from the plugin data route (not a hardcoded/global one)
    assert 'fetch("/plugin/calendar/data")' in H


def test_view_persists_mode_in_localstorage():
    # mode survives reloads via the cal.viewmode key (read on load, written on toggle)
    assert 'localStorage.getItem("cal.viewmode")' in H
    assert 'localStorage.setItem("cal.viewmode"' in H


def test_small_agenda_does_not_scroll():
    # paired positive/negative: the small preview agenda clips overflow (fits the tile),
    # it must NOT auto-scroll (clickcatch owns the whole tile gesture)
    assert ".agenda{height:100%;overflow:hidden" in H
    assert ".agenda{height:100%;overflow:auto" not in H


def test_view_has_month_and_controls():
    assert "cal-month" in H                    # month grid container
    assert "cal-prev" in H and "cal-next" in H and "cal-today" in H and "cal-mode" in H
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
