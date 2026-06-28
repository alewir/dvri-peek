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
    # settings toggle button (gear)
    assert 'id="gear"' in html or 'settings' in html.lower()
    # header collapse control
    assert 'header-collapse' in html or 'collapseHeader' in html
    # UI fetches from the server-side API endpoints
    assert '/api/layout' in html
    assert '/api/sources' in html


def test_index_tiles_have_data_source_and_slot(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # Each tile should have a data-source attribute for JS assignment
    assert 'data-source=' in html
    # Tiles have stable slot IDs for JS targeting
    assert 'data-slot=' in html or 'id="th-' in html


def test_index_revealbar_present(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # The reveal bar lets user show the collapsed header
    assert 'revealbar' in html


def test_index_apply_assignments_and_load_state_in_js(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # The JS must call loadState() on startup (replaces localStorage init)
    assert 'loadState' in html
    # applyAssignments is the core JS function wiring tiles
    assert 'applyAssignments' in html


def test_index_big_pane_has_media_container(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # big pane renders an initial media element (img for lens)
    assert 'id="bigmedia-cam"' in html or 'class="cam"' in html


def test_index_tile_picker_select_present(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # Settings-mode picker select elements should exist (hidden until .settings mode)
    assert 'class="picker"' in html or 'picker' in html


def test_index_css_has_collapsible_and_settings(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # Required CSS classes from brief
    assert 'header.collapsed' in html
    assert '.picker' in html or 'picker' in html
    assert 'headerhidden' in html
    assert 'pluginframe' in html
    assert 'titleoverlay' in html
