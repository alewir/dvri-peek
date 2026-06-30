# tests/test_streams.py — backend test for per-lens stream-tier API
import importlib


class _FakeWorker:
    """Minimal stand-in for LensWorker."""
    def __init__(self, wid, mode="sub"):
        self.id = wid
        self._mode = mode

    @property
    def stream_mode(self):
        return self._mode

    @property
    def tier(self):
        return self._mode


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cameras.yaml").write_text(
        "gateway: {}\nplayer: {}\n"
        "devices:\n  - id: cam\n    name: Cam\n    layout: spotlight\n    host: 1.2.3.4\n"
        "    lenses:\n      - {id: lens1, name: Lens 1, channel: 0}\n"
        "      - {id: lens2, name: Lens 2, channel: 1}\n")
    (tmp_path / "plugins").mkdir()
    import player
    importlib.reload(player)
    player.bootstrap(
        config_path="cameras.yaml",
        start_workers=False,
        start_gateway=False,
        plugins_dir=str(tmp_path / "plugins"),
        state_path=str(tmp_path / "state.local.json"),
        secrets_path=str(tmp_path / "secrets.local.yaml"),
    )
    w1 = _FakeWorker("lens1")
    w2 = _FakeWorker("lens2")
    player.WORKERS = {"lens1": w1, "lens2": w2}
    return player.app.test_client(), w1, w2


def test_old_set_stream_route_removed(tmp_path, monkeypatch):
    """The global /set_stream route must no longer exist."""
    c, _, _ = _setup(tmp_path, monkeypatch)
    rv = c.get("/set_stream?mode=main")
    assert rv.status_code == 404


def _boot_no_workers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cameras.yaml").write_text(
        "gateway: {}\nplayer: {}\ndevices:\n  - id: cam\n    name: Cam\n    layout: spotlight\n"
        "    host: 1.2.3.4\n    lenses:\n      - {id: lens1, name: L1, channel: 0}\n"
        "      - {id: lens2, name: L2, channel: 1}\n")
    (tmp_path / "plugins").mkdir()
    import importlib, player
    importlib.reload(player)
    player.bootstrap(config_path="cameras.yaml", start_workers=False, start_gateway=False,
                     plugins_dir=str(tmp_path / "plugins"),
                     state_path=str(tmp_path / "s.json"), secrets_path=str(tmp_path / "x.yaml"))
    return player


def test_api_streams_starts_and_stops_main(tmp_path, monkeypatch):
    player = _boot_no_workers(tmp_path, monkeypatch)
    class Fake:
        def __init__(s, lid, *a): s.id = lid; s.started = False; s.stopped = False; s.ready = False
        def start(s): s.started = True
        def stop(s): s.stopped = True
    monkeypatch.setattr(player, "LensWorker", Fake)
    player.WORKERS.clear(); player.MAIN_WORKERS.clear()
    player.WORKERS["lens1"] = Fake("lens1"); player.WORKERS["lens2"] = Fake("lens2")
    player.LENS_META.update({"lens1": {"name": "L1"}, "lens2": {"name": "L2"}})
    c = player.app.test_client()
    c.post("/api/streams", json={"main": ["lens1"]})
    assert "lens1" in player.MAIN_WORKERS and player.MAIN_WORKERS["lens1"].started
    assert "lens2" not in player.MAIN_WORKERS
    m1 = player.MAIN_WORKERS["lens1"]
    c.post("/api/streams", json={"main": []})
    assert "lens1" not in player.MAIN_WORKERS and m1.stopped


def test_api_streams_switches_main_between_lenses(tmp_path, monkeypatch):
    # switching the selected lens must start the new main AND stop the old one in one request
    player = _boot_no_workers(tmp_path, monkeypatch)
    class Fake:
        def __init__(s, lid, *a): s.id = lid; s.started = False; s.stopped = False; s.ready = False
        def start(s): s.started = True
        def stop(s): s.stopped = True
    monkeypatch.setattr(player, "LensWorker", Fake)
    player.WORKERS.clear(); player.MAIN_WORKERS.clear()
    player.WORKERS["lens1"] = Fake("lens1"); player.WORKERS["lens2"] = Fake("lens2")
    player.LENS_META.update({"lens1": {"name": "L1"}, "lens2": {"name": "L2"}})
    c = player.app.test_client()
    c.post("/api/streams", json={"main": ["lens1"]})
    m1 = player.MAIN_WORKERS["lens1"]
    c.post("/api/streams", json={"main": ["lens2"]})        # switch lens1 -> lens2
    assert "lens2" in player.MAIN_WORKERS and player.MAIN_WORKERS["lens2"].started
    assert "lens1" not in player.MAIN_WORKERS and m1.stopped


def test_snapshot_tier_routing_and_status_main_ready(tmp_path, monkeypatch):
    player = _boot_no_workers(tmp_path, monkeypatch)
    class FakeW:
        def __init__(s, lid, tier, ready, res): s.id=lid; s.name=lid.upper(); s.tier=tier
        s_ready = None
        def get_jpeg(s): return b"JPEGBYTES"
    class Sub(FakeW):
        def __init__(s): super().__init__("lens1","sub",True,"640x360"); s.status="online (sub)"; s.resolution="640x360"; s.fps=15.0; s.ready=True
    class Main:
        id="lens1"; name="L1"; tier="main"; status="online (main)"; resolution="1920x1080"; fps=12.0; ready=True
        def get_jpeg(self): return b"HDJPEG"
    player.WORKERS.clear(); player.MAIN_WORKERS.clear()
    player.WORKERS["lens1"] = Sub()
    c = player.app.test_client()
    # no main worker yet -> tier=main 404; status main_ready False
    assert c.get("/snapshot/lens1?tier=main").status_code == 404
    st = {x["id"]: x for x in c.get("/status").get_json()}
    assert st["lens1"]["main_ready"] is False and st["lens1"]["tier"] == "sub"
    # add main worker -> tier=main serves it; status main_ready True
    player.MAIN_WORKERS["lens1"] = Main()
    r = c.get("/snapshot/lens1?tier=main")
    assert r.status_code == 200 and r.data == b"HDJPEG"
    st = {x["id"]: x for x in c.get("/status").get_json()}
    assert st["lens1"]["main_ready"] is True and st["lens1"]["main_resolution"] == "1920x1080"
    # sub snapshot still works
    assert c.get("/snapshot/lens1").data == b"JPEGBYTES"


def test_lensworker_tier_url_and_ready():
    import importlib, player
    importlib.reload(player)
    gw = {"api_host": "127.0.0.1", "rtsp_port": 8554}
    main = player.LensWorker("lens1", "L1", gw, 75, 15, "main")
    assert main.tier == "main" and main.stream_mode == "main"
    assert main.url().endswith("/lens1_main")
    assert main.ready is False
    sub = player.LensWorker("lens1", "L1", gw, 75, 15, "sub")
    assert sub.tier == "sub" and sub.url().endswith("/lens1")
    assert not hasattr(sub, "set_stream")   # mode-switching removed
