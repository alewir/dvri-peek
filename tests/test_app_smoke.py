# tests/test_app_smoke.py  — app wiring without go2rtc/cameras
import importlib, os

def test_app_serves_sources_and_layout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cameras.yaml").write_text(
        "gateway: {}\nplayer: {http_port: 8090}\n"
        "devices:\n  - id: cam\n    name: Cam\n    layout: spotlight\n    host: 1.2.3.4\n"
        "    lenses:\n      - {id: lens1, name: Lens 1, channel: 0}\n")
    (tmp_path / "plugins").mkdir()
    import player
    importlib.reload(player)
    # point plugins/state at the isolated tmp dir so this exercises the real
    # injected env (empty plugins dir), not the repo's actual plugins/
    player.bootstrap(config_path="cameras.yaml", start_workers=False, start_gateway=False,
                     plugins_dir=str(tmp_path / "plugins"),
                     state_path=str(tmp_path / "state.local.json"),
                     secrets_path=str(tmp_path / "secrets.local.yaml"))
    c = player.app.test_client()
    srcs = c.get("/api/sources").get_json()
    assert c.get("/api/sources").status_code == 200
    ids = {s["id"] for s in srcs}
    assert "lens1" in ids
    assert not any(s["type"] == "plugin" for s in srcs)   # empty plugins dir -> no plugin sources
    assert c.get("/api/layout").status_code == 200
