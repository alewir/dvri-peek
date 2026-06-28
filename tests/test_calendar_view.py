from pathlib import Path

def test_view_fetches_data_and_handles_ctx():
    html = Path("plugins/calendar/view.html").read_text()
    assert "/plugin/calendar/data" in html        # fetches its backend
    assert "ctx" in html                            # adapts to tile/main/filler
    assert "events" in html                         # renders the events array
