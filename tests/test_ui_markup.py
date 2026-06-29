# tests/test_ui_markup.py — server-rendered HTML contract for task-8 UI
import importlib


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


def test_index_has_settings_and_collapse_controls(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # settings toggle button — specific id + handler (no permissive fallback:
    # the word "settings" leaks from a CSS comment and would never fail)
    assert 'id="gear"' in html
    assert 'toggleSettings()' in html
    # header collapse control — specific id + handler
    assert 'id="header-collapse"' in html
    assert 'collapseHeader()' in html
    # UI fetches from the server-side API endpoints
    assert '/api/layout' in html
    assert '/api/sources' in html


def test_index_tiles_have_data_source_and_slot(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # Each tile carries both attributes the JS uses to map slots -> sources
    assert 'data-source=' in html
    assert 'data-slot=' in html


def test_index_revealbar_present(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # The reveal bar lets the user restore a collapsed header
    assert 'id="revealbar"' in html
    assert 'showHeader()' in html


def test_index_apply_assignments_and_load_state_in_js(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # loadState() runs on startup (replaces the old localStorage init)
    assert 'loadState()' in html
    # applyAssignments is the core JS function wiring tiles
    assert 'function applyAssignments()' in html


def test_index_big_pane_has_media_container(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # big pane renders a stable, device-scoped media container the JS swaps
    assert 'id="bigmedia-cam"' in html


def test_index_tile_picker_select_present(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # Settings-mode picker <select> exists (hidden until body.settings)
    assert 'class="picker"' in html


def test_index_css_has_collapsible_and_settings(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # Required CSS hooks from the brief
    assert 'header.collapsed' in html
    assert '.picker' in html
    assert 'headerhidden' in html
    assert 'pluginframe' in html
    assert 'tilehead' in html


def test_active_tile_uses_header_strip_not_overlay(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    assert 'class="tilehead"' in html          # title strip element exists
    assert '.titleoverlay' not in html         # old overlapping overlay removed
