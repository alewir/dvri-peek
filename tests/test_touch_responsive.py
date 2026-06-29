# tests/test_touch_responsive.py — regression contract for the TOUCH / RESPONSIVE /
# INTERACTION spotlight fixes. Assertions are written to FAIL on the pre-fix code
# (causality): pointer-event divider, width-aware clamp, server-persisted split,
# taller reveal-bar touch target, and the no-scrollbar small agenda.
import importlib
from pathlib import Path

from layout import LayoutStore


def _client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cameras.yaml").write_text(
        "gateway: {}\nplayer: {http_port: 8090}\n"
        "devices:\n  - id: cam\n    name: Cam\n    layout: spotlight\n    host: 1.2.3.4\n"
        "    lenses:\n      - {id: lens1, name: Lens 1, channel: 0}\n"
        "      - {id: lens2, name: Lens 2, channel: 1}\n")
    (tmp_path / "plugins").mkdir()
    import player
    importlib.reload(player)
    player.bootstrap(config_path="cameras.yaml", start_workers=False, start_gateway=False,
                     plugins_dir=str(tmp_path / "plugins"),
                     state_path=str(tmp_path / "state.local.json"),
                     secrets_path=str(tmp_path / "secrets.local.yaml"))
    return player.app.test_client()


def _html(tmp_path, monkeypatch):
    return _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)


def _compact(html):
    return html.replace(' ', '').replace('\n', '')


# --- Fix 1: divider uses Pointer Events; #dragshield + body.dragging removed ---

def test_divider_uses_pointer_events(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    assert "div.addEventListener('pointerdown'" in html
    assert "div.addEventListener('pointermove'" in html
    assert "div.addEventListener('pointerup'" in html
    # pointer capture routes move/up to the divider even over the iframe
    assert 'div.setPointerCapture(e.pointerId)' in html
    # the old window-level mouse drag is gone
    assert "window.addEventListener('mousemove'" not in html
    assert "window.addEventListener('mouseup'" not in html


def test_dragshield_and_dragging_class_removed(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    # no shield element and no shield CSS
    assert 'dragshield' not in html
    # no body.dragging CSS hook and no toggling of it
    assert 'body.dragging' not in html
    assert "classList.add('dragging')" not in html
    assert "classList.remove('dragging')" not in html


def test_divider_has_touch_action_none(tmp_path, monkeypatch):
    compact = _compact(_html(tmp_path, monkeypatch))
    # touch-action:none lets the divider own touch gestures (no browser pan/scroll)
    assert '.divider{' in compact and 'touch-action:none' in compact


# --- Fix 2: width-aware divider clamp (thumb column never clipped) ---

def test_divider_width_aware_clamp(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    # max ceiling derived from panel width (150 thumbs min + 26 divider box)
    assert '(r.width-150-26)/r.width*100' in html
    assert 'Math.min(Math.min(85,maxPct),pct)' in html
    # the old fixed 85% ceiling must be gone
    assert 'Math.min(85,pct)' not in html


# --- Fix 5: split persisted in SERVER layout state, not localStorage ---

def test_split_persisted_server_side_not_localstorage(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    # write split into device state + save it
    assert 'LAYOUT.devices[dev].split=big.style.flexBasis' in html
    # read it back on init
    assert 'LAYOUT.devices[dev]&&LAYOUT.devices[dev].split' in html
    # the localStorage split path is dropped entirely (no localStorage on the player page)
    assert 'localStorage' not in html


def test_layout_store_preserves_split(tmp_path):
    p = tmp_path / "state.local.json"
    s = LayoutStore(str(p))
    out = s.save({"devices": {"cam": {"split": "70.0%", "selected": "lens1"}}})
    assert out["devices"]["cam"]["split"] == "70.0%"
    # survives a reload from disk
    assert LayoutStore(str(p)).get()["devices"]["cam"]["split"] == "70.0%"


# --- Fix 4: reveal bar — thin accent inside a taller touch target ---

def test_revealbar_taller_touch_target_with_accent(tmp_path, monkeypatch):
    compact = _compact(_html(tmp_path, monkeypatch))
    # transparent ~24px clickable strip (pre-fix was a 6px-tall bar)
    assert '#revealbar{position:fixed;top:0;left:0;right:0;height:24px' in compact
    # 6px colored accent kept as a top inset pseudo-element
    assert '#revealbar::before{' in compact
    assert 'height:6px;background:#2563eb55' in compact


# --- Fix 3: small agenda fits the tile (no scrollbar vs clickcatch) ---

def test_small_agenda_overflow_hidden_and_fixed_count():
    h = Path("plugins/calendar/view.html").read_text()
    compact = h.replace(' ', '').replace('\n', '')
    # the small preview agenda no longer scrolls (clickcatch owns the whole tile)
    assert '.agenda{height:100%;overflow:hidden' in compact
    assert '.agenda{height:100%;overflow:auto' not in compact
    # renderAgenda shows a fixed few upcoming items that fit the tile
    assert 'const max=5,' in h
    assert 'const max=12,' not in h
