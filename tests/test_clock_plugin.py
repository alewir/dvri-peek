from plugins import PluginRegistry

def test_clock_plugin_discovered():
    reg = PluginRegistry("plugins")
    reg.discover()
    p = reg.get("clock")
    assert p is not None and p.backend is None
    assert {"tile", "main", "filler"} <= set(p.contexts)
    assert "CLOCK" in (p.path / "view.html").read_text().upper()
