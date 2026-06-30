# tests/test_streams.py — backend test for per-lens stream-tier API
import importlib


class _FakeWorker:
    """Minimal stand-in for LensWorker: records set_stream calls."""
    def __init__(self, wid, mode="sub"):
        self.id = wid
        self._mode = mode

    def set_stream(self, mode):
        self._mode = mode

    @property
    def stream_mode(self):
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


def test_api_streams_sets_named_lens_to_main_others_sub(tmp_path, monkeypatch):
    c, w1, w2 = _setup(tmp_path, monkeypatch)
    rv = c.post("/api/streams", json={"main": ["lens1"]})
    assert rv.status_code == 200
    assert rv.get_json() == {"ok": True}
    assert w1.stream_mode == "main"
    assert w2.stream_mode == "sub"


def test_api_streams_empty_main_demotes_all(tmp_path, monkeypatch):
    c, w1, w2 = _setup(tmp_path, monkeypatch)
    # prime lens1 to main, then demote all
    c.post("/api/streams", json={"main": ["lens1"]})
    rv = c.post("/api/streams", json={"main": []})
    assert rv.status_code == 200
    assert w1.stream_mode == "sub"
    assert w2.stream_mode == "sub"


def test_api_streams_switches_main_between_lenses(tmp_path, monkeypatch):
    c, w1, w2 = _setup(tmp_path, monkeypatch)
    c.post("/api/streams", json={"main": ["lens1"]})
    c.post("/api/streams", json={"main": ["lens2"]})
    assert w1.stream_mode == "sub"
    assert w2.stream_mode == "main"


def test_old_set_stream_route_removed(tmp_path, monkeypatch):
    """The global /set_stream route must no longer exist."""
    c, _, _ = _setup(tmp_path, monkeypatch)
    rv = c.get("/set_stream?mode=main")
    assert rv.status_code == 404
