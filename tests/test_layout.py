import json
from layout import LayoutStore, DEFAULT_STATE

def test_missing_file_returns_default(tmp_path):
    s = LayoutStore(str(tmp_path / "state.local.json"))
    assert s.get() == DEFAULT_STATE
    assert s.get()["ui"]["header_collapsed"] is False

def test_save_roundtrip_persists_to_disk(tmp_path):
    p = tmp_path / "state.local.json"
    s = LayoutStore(str(p))
    s.save({"ui": {"header_collapsed": True},
            "devices": {"cam": {"tiles": {"s1": "lens1"}, "filler": "plugin:clock", "selected": "lens1"}}})
    again = LayoutStore(str(p))
    assert again.get()["ui"]["header_collapsed"] is True
    assert again.get()["devices"]["cam"]["tiles"]["s1"] == "lens1"
    assert json.loads(p.read_text())["devices"]["cam"]["filler"] == "plugin:clock"

def test_invalid_json_falls_back_to_default(tmp_path):
    p = tmp_path / "state.local.json"; p.write_text("{not json")
    assert LayoutStore(str(p)).get() == DEFAULT_STATE

def test_save_normalizes_unknown_keys(tmp_path):
    s = LayoutStore(str(tmp_path / "s.json"))
    out = s.save({"devices": {}, "junk": 1})
    assert "junk" not in out and out["ui"]["header_collapsed"] is False
