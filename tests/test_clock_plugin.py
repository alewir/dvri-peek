from plugins import PluginRegistry
from tests.conftest import ROOT

def test_clock_plugin_discovered():
    reg = PluginRegistry(str(ROOT / "plugins"))
    reg.discover()
    p = reg.get("clock")
    assert p is not None and p.backend is not None
    assert hasattr(p.backend, "fetch")
    assert {"tile", "main", "filler"} <= set(p.contexts)
    assert "CLOCK" in (p.path / "view.html").read_text().upper()

def test_clock_view_has_weather_and_news():
    from tests.conftest import ROOT
    H = (ROOT / "plugins" / "clock" / "view.html").read_text()
    assert "/plugin/clock/data" in H        # fetches backend data
    assert "renderWx" in H or "wx" in H      # weather render
    assert "news" in H                       # news render (main)
    assert "data-ctx" in H                   # ctx-adaptive
