# tests/test_spotlight_fixes.py — regression contract for the STATE/RESILIENCE/LABELS
# spotlight fixes. Markup/JS assertions are written to FAIL on the pre-fix code
# (causality), plus pure server-side esc() tests on render_spotlight/render_grid.
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


def _html(tmp_path, monkeypatch):
    return _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)


def _compact(html):
    return html.replace(' ', '').replace('\n', '')


# --- Fix 1: loadState resilience + LAYOUT_LOADED save gate ---

def test_loadstate_fetches_independently(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    # independent settle, not all-or-nothing Promise.all
    assert 'Promise.allSettled' in html
    assert 'Promise.all([' not in html


def test_layout_loaded_flag_gates_saves(tmp_path, monkeypatch):
    compact = _compact(_html(tmp_path, monkeypatch))
    assert 'letLAYOUT_LOADED=false;' in compact
    # flag flips true ONLY on a successful /api/layout resolve
    assert 'LAYOUT=d;LAYOUT_LOADED=true;' in compact
    # both saveUI() and saveLayout() no-op until loaded → 2 guard sites
    assert compact.count('if(!LAYOUT_LOADED)return;') >= 2


# --- Fix 2: tier classification by prefix, not SOURCES lookup ---

def test_tier_by_prefix_not_sources_type(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    assert "!selSrc.startsWith('plugin:')" in html
    # old SOURCES-type gate must be gone (a failed /api/sources must not drop big lens to sub)
    assert "type==='lens'" not in html


# --- Fix 3: stale/removed id reconciliation + single active tile ---

def test_reconcile_helpers_present(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    assert 'function srcKnown(id)' in html
    assert 'function resolveSrc(id,def)' in html
    # overrides resolved against SOURCES with slot-default fallback
    compact = _compact(html)
    assert 'resolveSrc(tiles[slot],defaultSrc)' in compact
    assert 'resolveSrc(tiles[slot],cell.dataset.source)' in compact


def test_selection_pinned_to_real_tile(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    # stale selected dropped, then pinned to the resolved thumb → exactly one active
    assert 'if(selected&&!srcKnown(selected)) selected=null;' in html
    assert 'selected=selThumb.dataset.source;' in html


# --- Fix 4: filler (none) option + mode-aware picker signature ---

def test_filler_none_option_present(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    assert '(none — live in main)' in html


def test_active_filler_picker_requests_none_option(tmp_path, monkeypatch):
    compact = _compact(_html(tmp_path, monkeypatch))
    # active tile passes withNone=isActive so the option list rebuilds on mode toggle
    assert ":assignedSrc,isActive)" in compact
    # withNone is folded into the cached signature
    assert "(withNone?'none|':'')" in compact


# --- Fix 5: save on EVERY picker change (Show: x2 + Filler:) ---

def test_every_picker_onchange_saves(tmp_path, monkeypatch):
    compact = _compact(_html(tmp_path, monkeypatch))
    assert compact.count('applyAssignments();saveLayout();') >= 3


def test_filler_onchange_maps_empty_to_null(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    assert 'filler=picker.value||null' in html


# --- Fix 6: filler === big-pane source → treated as no-filler ---

def test_filler_equals_selsrc_guard(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    assert 'filler!==selSrc' in html


# --- Fix 7: bigcap resolves un-suffixed name, never the decorated .tname ---

def test_bigcap_no_tname_suffix_fallback(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    assert 'meta?meta.name:selSrc' in html
    # the old fallback that leaked the " · in main" decoration must be gone
    assert ".tname')||{}).textContent" not in html


# --- Fix 8: content-aware active placeholder (plugin vs camera) ---

def test_active_placeholder_content_aware(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    assert "(plg?'in main'" in html          # plugin big-pane → generic wording
    assert 'Live in main view' in html       # camera big-pane → live wording retained


# --- Fix 9: esc() encoder on PLAYER side + escaped interpolations ---

def test_player_esc_helper_and_escaped_options(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    assert 'function esc(' in html
    assert 'esc(s.id)' in html and 'esc(s.name)' in html
    # media helper escapes the source id too
    assert 'esc(srcId)' in html


def test_render_grid_escapes_lens_name(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)  # bootstraps player
    import player
    dev = {'id': 'nvr', 'name': 'NVR',
           'lenses': [{'id': 'ch1', 'name': '<x>&"q', 'channel': 0}]}
    out = player.render_grid(dev)
    assert '&lt;x&gt;&amp;&quot;q' in out
    assert '<x>&"q' not in out


def test_render_spotlight_escapes_names(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    import player
    dev = {'id': 'cam2', 'name': 'Cam2', 'layout': 'spotlight',
           'lenses': [{'id': 'l1', 'name': '<b>"hi"', 'channel': 0}]}
    out = player.render_spotlight(dev)
    # appears escaped in both the thumb name strip and the big-pane caption
    assert '&lt;b&gt;&quot;hi&quot;' in out
    assert '<b>"hi"' not in out


# --- Fix 10: dead .sbtn.active CSS removed ---

def test_dead_sbtn_active_css_removed(tmp_path, monkeypatch):
    html = _html(tmp_path, monkeypatch)
    assert '.sbtn.active' not in html
