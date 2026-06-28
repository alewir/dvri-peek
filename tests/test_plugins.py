import textwrap
from plugins import PluginRegistry

def _mk(dirp, pid, manifest, backend=None, view="<p>hi</p>"):
    d = dirp / pid; d.mkdir(parents=True)
    (d / "manifest.yaml").write_text(manifest)
    (d / "view.html").write_text(view)
    if backend is not None:
        (d / "backend.py").write_text(textwrap.dedent(backend))
    return d

def test_discovers_valid_plugin(tmp_path):
    _mk(tmp_path, "clock", "id: clock\nname: Clock\ncontexts: [tile, main]\n")
    reg = PluginRegistry(str(tmp_path)); reg.discover()
    p = reg.get("clock")
    assert p is not None and p.name == "Clock" and "main" in p.contexts and p.backend is None

def test_missing_dir_is_empty(tmp_path):
    reg = PluginRegistry(str(tmp_path / "nope")); reg.discover()
    assert reg.list() == []

def test_invalid_manifest_skipped(tmp_path):
    d = tmp_path / "bad"; d.mkdir(); (d / "manifest.yaml").write_text(": : not yaml :")
    _mk(tmp_path, "ok", "id: ok\nname: OK\n")
    reg = PluginRegistry(str(tmp_path)); reg.discover()
    assert reg.get("ok") is not None and reg.get("bad") is None

def test_backend_data_with_cache(tmp_path):
    _mk(tmp_path, "w", "id: w\nname: W\nrefresh_seconds: 60\n",
        backend="""
        CALLS = {'n': 0}
        def fetch(config):
            CALLS['n'] += 1
            return {'count': CALLS['n'], 'cfg': config.get('k')}
        """)
    reg = PluginRegistry(str(tmp_path), secrets={"plugins": {"w": {"k": 7}}}); reg.discover()
    a = reg.data("w"); b = reg.data("w")
    assert a == b == {"count": 1, "cfg": 7}     # cached within TTL

def test_backend_error_becomes_payload(tmp_path):
    _mk(tmp_path, "boom", "id: boom\nname: B\nrefresh_seconds: 0\n",
        backend="def fetch(config):\n    raise RuntimeError('nope')\n")
    reg = PluginRegistry(str(tmp_path)); reg.discover()
    assert "error" in reg.data("boom")
