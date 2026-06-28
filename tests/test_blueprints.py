from flask import Flask
from plugins import PluginRegistry, create_plugins_blueprint
from layout import LayoutStore, create_layout_blueprint

def _app(tmp_path):
    pdir = tmp_path / "plugins"; (pdir / "clock").mkdir(parents=True)
    (pdir / "clock" / "manifest.yaml").write_text("id: clock\nname: Clock\ncontexts: [tile]\n")
    (pdir / "clock" / "view.html").write_text("<b>CLOCK</b>")
    reg = PluginRegistry(str(pdir)); reg.discover()
    store = LayoutStore(str(tmp_path / "state.local.json"))
    cfg = {"devices": [{"id": "cam", "lenses": [{"id": "lens1", "name": "Lens 1"}]}]}
    app = Flask(__name__)
    app.register_blueprint(create_plugins_blueprint(reg))
    app.register_blueprint(create_layout_blueprint(cfg, reg, store))
    return app.test_client()

def test_view_served(tmp_path):
    assert b"CLOCK" in _app(tmp_path).get("/plugin/clock/view").data

def test_view_404(tmp_path):
    assert _app(tmp_path).get("/plugin/nope/view").status_code == 404

def test_sources_lists_lens_and_plugin(tmp_path):
    ids = {s["id"] for s in _app(tmp_path).get("/api/sources").get_json()}
    assert "lens1" in ids and "plugin:clock" in ids

def test_layout_roundtrip(tmp_path):
    c = _app(tmp_path)
    c.post("/api/layout", json={"ui": {"header_collapsed": True}, "devices": {"cam": {"tiles": {"s1": "lens1"}}}})
    got = c.get("/api/layout").get_json()
    assert got["ui"]["header_collapsed"] is True and got["devices"]["cam"]["tiles"]["s1"] == "lens1"
