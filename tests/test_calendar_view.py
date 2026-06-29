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
