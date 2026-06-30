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


# --- Bug-fix regression: tile label overlap (Bug 1) ---

def test_tile_label_no_overlap_css(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # .tname must flex-grow with overflow truncation so it never bleeds into meta
    compact = html.replace(' ', '').replace('\n', '')
    assert 'text-overflow:ellipsis' in compact
    assert '.tname' in html
    # .tmeta (right-side status) stays fixed-width via its own class
    assert 'class="tmeta"' in html


# --- Bug-fix regression: settings focus steal (Bug 2) ---

def test_settings_promote_guarded(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # promote() must bail out immediately when body.settings is active
    assert "classList.contains('settings')" in html


def test_picker_stops_propagation_and_is_labelled(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # picker <select> explicitly stops bubbling so tile's promote handler is never reached
    assert 'stopPropagation' in html
    # picker wrapper provides a visible label distinguishing content vs filler
    assert 'picker-wrap' in html
    assert 'class="picker-lbl"' in html
    # default label is "Show:" (content picker for non-active tiles)
    assert 'Show:' in html


# --- Chrome redesign: always-visible header strip (Bug 1, 2, 3) ---

def test_tilehead_is_always_visible_not_conditional(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # .tilehead base rule must use display:flex (always on), not display:none
    compact = html.replace(' ', '').replace('\n', '')
    assert '.tilehead{display:flex' in compact
    # old conditional "only show on active tile" rules must be gone
    assert '.tile.active .tilehead{display:block}' not in compact


def test_no_absolute_lbl_overlay_on_tiles(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # The position:absolute gradient overlay that caused overlap must be removed
    # from both tile and cell CSS rules
    assert '.tile .lbl' not in html
    assert '.cell .lbl' not in html


def test_grid_cell_has_tilehead_strip(tmp_path, monkeypatch):
    # render_grid() is pure (no global state); call it directly with a synthetic device
    _client(tmp_path, monkeypatch)  # bootstraps the player module
    import player
    dev = {'id': 'nvr', 'name': 'NVR',
           'lenses': [{'id': 'ch1', 'name': 'Ch 1', 'channel': 0},
                      {'id': 'ch2', 'name': 'Ch 2', 'channel': 1}]}
    out = player.render_grid(dev)
    assert 'class="tilehead"' in out
    assert 'class="tname"' in out
    assert 'class="tmeta"' in out
    # no absolute lbl overlay in grid cells
    assert 'class="lbl"' not in out


def test_poll_uses_data_src_not_meta_id(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # poll() must use dataset.src to resolve the currently-assigned source per tile
    assert 'dataset.src' in html
    # plugin sources must suppress status (content-aware)
    assert "startsWith('plugin:')" in html
    # old hard-coded meta-id lookup must be gone
    assert "getElementById('meta-'" not in html


def test_tile_header_strip_structure(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # Every spotlight tile has the unified tilehead containing tname + tmeta
    # (fixture has 2 lenses → 2 tiles → 2 tilehead divs minimum)
    assert html.count('class="tilehead"') >= 2
    # .tname and .tmeta live inside the strip (not in a separate .lbl overlay)
    assert 'class="tname"' in html
    assert 'class="tmeta"' in html
    # No standalone .lbl div in tile or cell HTML
    assert 'class="lbl"' not in html


# --- Active spotlight tile: 3-zone header strip (left / center / right) ---

def test_active_tile_header_has_three_zones(tmp_path, monkeypatch):
    import re
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    # Spotlight tile strip carries a CENTER preview zone (.tpreview) for the active
    # tile's currently-shown filler, between name (left) and status (right).
    assert 'class="tpreview"' in html
    # Ordering inside a spotlight tile strip: left (.tname) -> center (.tpreview) -> right (.tmeta)
    m = re.search(r'class="tilehead"[^>]*>(.*?)</div>', html)
    assert m, "tilehead strip not found"
    strip = m.group(1)
    assert strip.index('tname') < strip.index('tpreview') < strip.index('tmeta')


def test_active_center_zone_is_muted_and_collapses_when_empty(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    compact = html.replace(' ', '').replace('\n', '')
    # Empty center collapses (center omitted entirely when there is no filler / non-active tiles)
    assert '.tpreview:empty{display:none}' in compact
    # Center reads dimmer than the left (muted grey), distinct from the bright .tname
    assert '.tpreview{' in compact


def test_active_header_js_preview_label_and_filler_status(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    compact = html.replace(' ', '').replace('\n', '')
    # Center zone renders the bracketed, muted preview label for the current filler
    assert '[preview: ' in html
    # Active tile's status source (dataset.src) is the EFFECTIVE filler (filler unless
    # it equals the big-pane source) — drives the content-aware poll()
    assert 'dataset.src=isActive?(effFiller' in compact
    # poll() no longer skips the active tile: its right zone must show the filler's live status
    assert "contains('active'))return" not in compact


def test_stream_lifecycle_client_logic():
    H = open("player.py").read()
    assert "function pauseHiddenStreams" in H          # hidden-tab pause exists
    assert "dataset.psrc" in H                          # paused src is stashed/restored
    assert "pauseHiddenStreams()" in H                  # called (showTab/loadState)
    assert "?tier=main" in H                            # big-pane sub->main swap target
    assert "main_ready" in H                            # swap gated on main_ready
    # teardown: setMedia clears old <img> src before replacing
    assert "querySelectorAll('img')" in H and "i.src=''" in H
