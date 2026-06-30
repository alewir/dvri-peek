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
