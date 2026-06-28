# Pluggable Dashboard Tiles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each dvri-peek side tile show a camera lens or a drop-in plugin widget (e.g. a merged Google-Calendar agenda); selecting a tile promotes it to the main pane and the freed tile shows configurable filler — all configured in an in-app settings mode and persisted server-side.

**Architecture:** Add two cv2-free modules — `plugins.py` (folder autodiscovery + iframe view + cached JSON data endpoint) and `layout.py` (server-side layout state + sources/layout API) — wired into the existing Flask app in `player.py`. Plugins live in `plugins/<id>/` (`manifest.yaml` + `view.html` + optional `backend.py`). The browser UI gains a settings mode, a collapsible header, and tile rendering that is an `<img>` for lenses and a sandboxed `<iframe>` for plugins.

**Tech Stack:** Python 3 (system `python3` on the Pi; venv on the dev box), Flask, PyYAML, OpenCV (existing, lens decode only), pytest (new, dev-only), vanilla JS/HTML for the UI and plugins. No new runtime deps on the Pi (ICS parsing is stdlib).

## Global Constraints

- Python ≥ 3.9 (uses `zoneinfo`); runs under **system `python3` on the Pi** — **no pip installs on the Pi**, stdlib only for runtime code (ICS parsing included). pytest is dev-only (dev venv `~/.venvs/rtsp`).
- New modules `plugins.py` and `layout.py` MUST NOT import `cv2`/`numpy` (keeps them unit-testable without OpenCV).
- Secrets live ONLY in git-ignored `secrets.local.yaml`; layout state in git-ignored `state.local.json`. Never log secret values. `*.local.yaml` / `*.local.json` are already in `.gitignore`.
- Existing routes/behaviour unchanged: `/`, `/stream/<lens>`, `/snapshot/<lens>`, `/status`, `/set_stream`. With an empty/missing `plugins/` dir, the app must behave exactly as today.
- Source id convention: a lens is its lens id (e.g. `lens1`); a plugin source is `plugin:<id>` (e.g. `plugin:calendar`).
- Commit after every task. Run tests from the dev venv: `~/.venvs/rtsp/bin/python -m pytest`.

---

## File structure

| File | Responsibility |
|---|---|
| `layout.py` (new) | `LayoutStore` (load/save `state.local.json`) + `create_layout_blueprint` (`/api/sources`, `/api/layout`). No cv2. |
| `plugins.py` (new) | `Plugin`, `PluginRegistry` (discover/cache), `create_plugins_blueprint` (`/plugin/<id>/view|data|static`). No cv2. |
| `player.py` (modify) | Load secrets + registry + store at startup; register blueprints; settings-mode UI, collapsible header, lens-`<img>`/plugin-`<iframe>` tile rendering, filler for active tile. |
| `plugins/clock/` (new) | `manifest.yaml` + `view.html` — frontend-only example. |
| `plugins/calendar/` (new) | `manifest.yaml` + `backend.py` (ICS fetch/parse/merge) + `view.html`. |
| `tests/` (new) | `test_layout.py`, `test_plugins.py`, `test_calendar.py`, `test_app_smoke.py`. |
| `requirements-dev.txt` (new) | `pytest` (+ `pyyaml` for test env). |
| `secrets.local.yaml` (exists, git-ignored) | per-plugin config/secrets. |

Dev test bootstrap (do once, before Task 1): `~/.venvs/rtsp/bin/pip install pytest pyyaml` and create `tests/__init__.py` (empty). Folded into Task 1 Step 0.

---

### Task 1: Layout store (server-side state persistence)

**Files:**
- Create: `layout.py`
- Create: `tests/test_layout.py`, `tests/__init__.py`, `requirements-dev.txt`
- Test: `tests/test_layout.py`

**Interfaces:**
- Produces: `DEFAULT_STATE: dict`; `class LayoutStore(path: str)` with `.get() -> dict`, `.save(state: dict) -> dict`. State shape: `{"ui": {"header_collapsed": bool}, "devices": {<deviceId>: {"tiles": {<slot>: <sourceId>}, "filler": <sourceId|None>, "selected": <sourceId|None>}}}`.

- [ ] **Step 0: Dev test bootstrap**

```bash
~/.venvs/rtsp/bin/pip install pytest pyyaml
printf 'pytest>=7\npyyaml>=6\n' > requirements-dev.txt
mkdir -p tests && touch tests/__init__.py
```

- [ ] **Step 1: Write failing tests**

```python
# tests/test_layout.py
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
```

- [ ] **Step 2: Run, verify failure**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_layout.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'layout'`).

- [ ] **Step 3: Implement `layout.py` (store only)**

```python
# layout.py  — server-side layout state (no cv2/numpy)
import json
import os
import threading

DEFAULT_STATE = {"ui": {"header_collapsed": False}, "devices": {}}

def _deep_copy(d):
    return json.loads(json.dumps(d))

class LayoutStore:
    """Loads/saves dashboard layout state to a JSON file (atomic writes)."""
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._state = self._read()

    def _read(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
            if not isinstance(data, dict) or "devices" not in data:
                return _deep_copy(DEFAULT_STATE)
            data.setdefault("ui", {})
            data["ui"].setdefault("header_collapsed", False)
            data.setdefault("devices", {})
            return data
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return _deep_copy(DEFAULT_STATE)

    def get(self):
        with self._lock:
            return _deep_copy(self._state)

    def save(self, state):
        state = state or {}
        merged = _deep_copy(DEFAULT_STATE)
        merged["ui"]["header_collapsed"] = bool(
            (state.get("ui") or {}).get("header_collapsed", False))
        merged["devices"] = state.get("devices") or {}
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(merged, f, indent=2)
            os.replace(tmp, self.path)
            self._state = merged
            return _deep_copy(merged)
```

- [ ] **Step 4: Run, verify pass**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_layout.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add layout.py tests/test_layout.py tests/__init__.py requirements-dev.txt
git commit -m "feat(layout): server-side dashboard state store"
```

---

### Task 2: Plugin registry (folder autodiscovery)

**Files:**
- Create: `plugins.py`
- Test: `tests/test_plugins.py`

**Interfaces:**
- Produces: `class Plugin` (attrs `.id, .path (pathlib.Path), .manifest, .backend, .name, .contexts (list), .refresh (int)`); `class PluginRegistry(plugins_dir: str, secrets: dict=None)` with `.discover() -> dict[str,Plugin]`, `.list() -> list[Plugin]`, `.get(pid) -> Plugin|None`, `.data(pid) -> dict`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_plugins.py
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
```

- [ ] **Step 2: Run, verify failure**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_plugins.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'plugins'`).

- [ ] **Step 3: Implement `plugins.py` (registry + cache; blueprint added in Task 3)**

```python
# plugins.py — drop-in plugin discovery + cached data (no cv2/numpy)
import importlib.util
import threading
import time
from pathlib import Path

import yaml

class Plugin:
    def __init__(self, pid, path, manifest, backend):
        self.id = pid
        self.path = Path(path)
        self.manifest = manifest or {}
        self.backend = backend
        self.name = self.manifest.get("name", pid)
        self.contexts = list(self.manifest.get("contexts", ["tile"]))
        try:
            self.refresh = int(self.manifest.get("refresh_seconds", 0) or 0)
        except (TypeError, ValueError):
            self.refresh = 0

class PluginRegistry:
    def __init__(self, plugins_dir, secrets=None):
        self.dir = Path(plugins_dir)
        self.secrets = secrets or {}
        self.plugins = {}
        self._cache = {}            # pid -> (ts, data)
        self._lock = threading.Lock()

    def discover(self):
        self.plugins = {}
        if not self.dir.is_dir():
            return self.plugins
        for child in sorted(self.dir.iterdir()):
            mf = child / "manifest.yaml"
            if not child.is_dir() or not mf.is_file():
                continue
            try:
                manifest = yaml.safe_load(mf.read_text()) or {}
                if not isinstance(manifest, dict):
                    raise ValueError("manifest is not a mapping")
                pid = manifest.get("id") or child.name
                backend = self._load_backend(child)
                self.plugins[pid] = Plugin(pid, child, manifest, backend)
            except Exception as e:                       # noqa: BLE001 - skip bad plugin
                print(f"[plugins] skipping {child.name}: {e}")
        return self.plugins

    def _load_backend(self, child):
        bp = child / "backend.py"
        if not bp.is_file():
            return None
        spec = importlib.util.spec_from_file_location(f"dvripeek_plugin_{child.name}", bp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod if hasattr(mod, "fetch") else None

    def list(self):
        return list(self.plugins.values())

    def get(self, pid):
        return self.plugins.get(pid)

    def data(self, pid):
        p = self.get(pid)
        if not p or not p.backend:
            return {"error": "no backend"}
        now = time.time()
        with self._lock:
            cached = self._cache.get(pid)
            if cached and p.refresh and (now - cached[0]) < p.refresh:
                return cached[1]
        cfg = (self.secrets.get("plugins", {}) or {}).get(pid, {}) or {}
        try:
            result = p.backend.fetch(cfg)
            if not isinstance(result, dict):
                result = {"error": "backend did not return a dict"}
        except Exception as e:                           # noqa: BLE001
            result = {"error": str(e)}
        with self._lock:
            self._cache[pid] = (now, result)
        return result
```

- [ ] **Step 4: Run, verify pass**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_plugins.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add plugins.py tests/test_plugins.py
git commit -m "feat(plugins): folder autodiscovery + cached backend data"
```

---

### Task 3: Flask blueprints (plugin routes + sources/layout API)

**Files:**
- Modify: `plugins.py` (append `create_plugins_blueprint`)
- Modify: `layout.py` (append `create_layout_blueprint`)
- Test: `tests/test_blueprints.py`

**Interfaces:**
- Consumes: `PluginRegistry`, `LayoutStore`, the player config dict (`{"devices": [{"id","lenses":[{"id","name"}]}]}`).
- Produces: `create_plugins_blueprint(registry) -> flask.Blueprint`; `create_layout_blueprint(config, registry, store) -> flask.Blueprint`. Routes: `GET /plugin/<pid>/view`, `GET /plugin/<pid>/data`, `GET /plugin/<pid>/static/<path>`, `GET /api/sources`, `GET|POST /api/layout`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_blueprints.py
from flask import Flask
from plugins import PluginRegistry, create_plugins_blueprint
from layout import LayoutStore, create_layout_blueprint

def _app(tmp_path):
    pdir = tmp_path / "plugins"; (pdir / "clock").mkdir(parents=True)
    (pdir / "clock" / "manifest.yaml").write_text("id: clock\nname: Clock\ncontexts: [tile]\n")
    (pdir / "clock" / "view.html").write_text("<b>CLOCK</b>")
    reg = PluginRegistry(str(pdir)); reg.discover()
    store = LayoutStore(str(tmp_path / "state.local.json"))
    cfg = {"devices": [{"id": "cam", "lenses": [{"id": "lens1", "name": "Lens 1"}]}]}
    app = Flask(__name__)
    app.register_blueprint(create_plugins_blueprint(reg))
    app.register_blueprint(create_layout_blueprint(cfg, reg, store))
    return app.test_client()

def test_view_served(tmp_path):
    assert b"CLOCK" in _app(tmp_path).get("/plugin/clock/view").data

def test_view_404(tmp_path):
    assert _app(tmp_path).get("/plugin/nope/view").status_code == 404

def test_sources_lists_lens_and_plugin(tmp_path):
    ids = {s["id"] for s in _app(tmp_path).get("/api/sources").get_json()}
    assert "lens1" in ids and "plugin:clock" in ids

def test_layout_roundtrip(tmp_path):
    c = _app(tmp_path)
    c.post("/api/layout", json={"ui": {"header_collapsed": True}, "devices": {"cam": {"tiles": {"s1": "lens1"}}}})
    got = c.get("/api/layout").get_json()
    assert got["ui"]["header_collapsed"] is True and got["devices"]["cam"]["tiles"]["s1"] == "lens1"
```

- [ ] **Step 2: Run, verify failure**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_blueprints.py -v`
Expected: FAIL (`ImportError: cannot import name 'create_plugins_blueprint'`).

- [ ] **Step 3: Append blueprint to `plugins.py`**

```python
# plugins.py  (append)
from flask import Blueprint, Response, jsonify, send_from_directory

def create_plugins_blueprint(registry):
    bp = Blueprint("plugins", __name__)

    @bp.route("/plugin/<pid>/view")
    def view(pid):
        p = registry.get(pid)
        if not p:
            return ("no such plugin", 404)
        return Response((p.path / "view.html").read_text(), mimetype="text/html")

    @bp.route("/plugin/<pid>/data")
    def data(pid):
        return jsonify(registry.data(pid))

    @bp.route("/plugin/<pid>/static/<path:fn>")
    def static_(pid, fn):
        p = registry.get(pid)
        if not p:
            return ("no such plugin", 404)
        return send_from_directory(str(p.path / "static"), fn)

    return bp
```

- [ ] **Step 4: Append blueprint to `layout.py`**

```python
# layout.py  (append)
from flask import Blueprint, jsonify, request

def create_layout_blueprint(config, registry, store):
    bp = Blueprint("layout", __name__)

    @bp.route("/api/sources")
    def sources():
        out = []
        for dev in config.get("devices", []):
            for lens in dev.get("lenses", []):
                out.append({"id": lens["id"], "name": lens.get("name", lens["id"]),
                            "type": "lens", "device": dev["id"]})
        for p in registry.list():
            out.append({"id": f"plugin:{p.id}", "name": p.name,
                        "type": "plugin", "contexts": p.contexts})
        return jsonify(out)

    @bp.route("/api/layout", methods=["GET", "POST"])
    def layout():
        if request.method == "POST":
            return jsonify(store.save(request.get_json(force=True, silent=True) or {}))
        return jsonify(store.get())

    return bp
```

- [ ] **Step 5: Run, verify pass**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_blueprints.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add plugins.py layout.py tests/test_blueprints.py
git commit -m "feat(api): plugin view/data/static + sources/layout blueprints"
```

---

### Task 4: Clock plugin (frontend-only example)

**Files:**
- Create: `plugins/clock/manifest.yaml`, `plugins/clock/view.html`
- Test: `tests/test_clock_plugin.py`

**Interfaces:**
- Consumes: `PluginRegistry.discover()` against the real `plugins/` dir.
- Produces: a discoverable plugin `clock` with contexts `[tile, main, filler]` and no backend.

- [ ] **Step 1: Write failing test**

```python
# tests/test_clock_plugin.py
from plugins import PluginRegistry

def test_clock_plugin_discovered():
    reg = PluginRegistry("plugins"); reg.discover()
    p = reg.get("clock")
    assert p is not None and p.backend is None
    assert {"tile", "main", "filler"} <= set(p.contexts)
    assert "CLOCK" in (p.path / "view.html").read_text().upper()
```

- [ ] **Step 2: Run, verify failure**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_clock_plugin.py -v`
Expected: FAIL (`assert None is not None`).

- [ ] **Step 3: Create the plugin files**

`plugins/clock/manifest.yaml`:
```yaml
id: clock
name: "Clock"
refresh_seconds: 0
contexts: [tile, main, filler]
config: []
```

`plugins/clock/view.html`:
```html
<!doctype html><html><head><meta charset="utf-8"><title>Clock</title>
<style>
 html,body{margin:0;height:100%;background:#0e0e10;color:#e4e4e7;
   font-family:system-ui,Segoe UI,Arial,sans-serif;display:flex;
   flex-direction:column;align-items:center;justify-content:center}
 #t{font-weight:700;line-height:1} #d{opacity:.7;margin-top:.3em}
 /* ctx=tile|filler are small, ctx=main is large */
 body[data-ctx="main"] #t{font-size:14vw} body[data-ctx="main"] #d{font-size:3vw}
 #t{font-size:7vw} #d{font-size:2.2vw}
</style></head><body>
<div id="t">--:--</div><div id="d"></div>
<script>
 const ctx=new URLSearchParams(location.search).get("ctx")||"tile";
 document.body.dataset.ctx=ctx;
 function tick(){const n=new Date();
   document.getElementById("t").textContent=n.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"});
   document.getElementById("d").textContent=n.toLocaleDateString([], {weekday:"short",day:"numeric",month:"short"});}
 tick(); setInterval(tick,1000);
</script></body></html>
```

- [ ] **Step 4: Run, verify pass**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_clock_plugin.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/clock/manifest.yaml plugins/clock/view.html tests/test_clock_plugin.py
git commit -m "feat(plugins): clock plugin (frontend-only)"
```

---

### Task 5: Calendar plugin backend (ICS parse + multi-source merge)

**Files:**
- Create: `plugins/calendar/manifest.yaml`, `plugins/calendar/backend.py`
- Create: `tests/fixtures/cal_a.ics`, `tests/fixtures/cal_b.ics`
- Test: `tests/test_calendar.py`

**Interfaces:**
- Produces: in `plugins/calendar/backend.py`: `parse_ics(text: str) -> list[dict]` (each `{summary,start(datetime aware UTC),end,allday(bool)}`), `expand(events, window_start, window_end) -> list[dict]` (applies simple RRULE), `fetch(config: dict) -> dict` returning `{"events":[{title,start(iso),end(iso),allday,source,color}], "generated": iso}`.
- Recurrence scope (v1): non-recurring events always; `RRULE` `FREQ=DAILY|WEEKLY` with `INTERVAL`, `COUNT`, `UNTIL`, and weekly `BYDAY` — expanded within the lookahead window. `MONTHLY`/`YEARLY`/`EXDATE` → emit only the original occurrence if in-window (documented limitation).

- [ ] **Step 1: Create test fixtures**

`tests/fixtures/cal_a.ics`:
```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:a1
SUMMARY:One Off
DTSTART:20260629T090000Z
DTEND:20260629T100000Z
END:VEVENT
BEGIN:VEVENT
UID:a2
SUMMARY:All Day
DTSTART;VALUE=DATE:20260630
DTEND;VALUE=DATE:20260701
END:VEVENT
END:VCALENDAR
```

`tests/fixtures/cal_b.ics`:
```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:b1
SUMMARY:Daily Standup
DTSTART:20260629T083000Z
DTEND:20260629T084500Z
RRULE:FREQ=DAILY;COUNT=3
END:VEVENT
END:VCALENDAR
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_calendar.py
import importlib.util
from datetime import datetime, timezone, timedelta
from pathlib import Path

def _backend():
    spec = importlib.util.spec_from_file_location("cal_backend", "plugins/calendar/backend.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

def test_parse_timed_and_allday():
    b = _backend()
    evs = b.parse_ics(Path("tests/fixtures/cal_a.ics").read_text())
    s = {e["summary"]: e for e in evs}
    assert s["One Off"]["allday"] is False
    assert s["One Off"]["start"] == datetime(2026, 6, 29, 9, 0, tzinfo=timezone.utc)
    assert s["All Day"]["allday"] is True

def test_rrule_daily_count_expands():
    b = _backend()
    evs = b.parse_ics(Path("tests/fixtures/cal_b.ics").read_text())
    w0 = datetime(2026, 6, 28, tzinfo=timezone.utc)
    w1 = w0 + timedelta(days=10)
    occ = [e for e in b.expand(evs, w0, w1) if e["summary"] == "Daily Standup"]
    assert len(occ) == 3
    days = sorted(e["start"].day for e in occ)
    assert days == [29, 30, 1]

def test_fetch_merges_sorts_colors(monkeypatch):
    b = _backend()
    feeds = {"A": Path("tests/fixtures/cal_a.ics").read_text(),
             "B": Path("tests/fixtures/cal_b.ics").read_text()}
    monkeypatch.setattr(b, "_http_get", lambda url: feeds[url])
    out = b.fetch({"max_events": 10, "lookahead_days": 30,
                   "sources": [{"name": "A", "color": "#111", "ics_url": "A"},
                               {"name": "B", "color": "#222", "ics_url": "B"}]})
    assert "error" not in out
    starts = [e["start"] for e in out["events"]]
    assert starts == sorted(starts)                 # merged + sorted
    assert any(e["source"] == "B" and e["color"] == "#222" for e in out["events"])
    assert len(out["events"]) <= 10

def test_fetch_bad_url_is_graceful(monkeypatch):
    b = _backend()
    def boom(url): raise OSError("dns")
    monkeypatch.setattr(b, "_http_get", boom)
    out = b.fetch({"sources": [{"name": "X", "color": "#000", "ics_url": "http://x"}]})
    assert out["events"] == [] and "errors" in out
```

- [ ] **Step 3: Run, verify failure**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_calendar.py -v`
Expected: FAIL (`No such file or directory: 'plugins/calendar/backend.py'`).

- [ ] **Step 4: Create `plugins/calendar/manifest.yaml`**

```yaml
id: calendar
name: "Calendar"
refresh_seconds: 1800
contexts: [tile, main, filler]
config: [sources, max_events, lookahead_days, refresh_minutes]
```

- [ ] **Step 5: Implement `plugins/calendar/backend.py`**

```python
# plugins/calendar/backend.py — merged multi-calendar agenda from secret ICS feeds.
# Stdlib only. Recurrence: non-recurring always; FREQ=DAILY|WEEKLY (INTERVAL,COUNT,
# UNTIL, weekly BYDAY) expanded in-window; MONTHLY/YEARLY -> original occurrence only.
import urllib.request
from datetime import datetime, timezone, timedelta, date

_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

def _http_get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read().decode("utf-8", "replace")

def _unfold(text):
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out

def _parse_dt(val, params):
    if params.get("VALUE") == "DATE" or (len(val) == 8 and "T" not in val):
        d = datetime.strptime(val, "%Y%m%d").replace(tzinfo=timezone.utc)
        return d, True
    if val.endswith("Z"):
        return datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc), False
    # naive / TZID: best-effort treat as UTC (kiosk-local display is acceptable v1)
    return datetime.strptime(val[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc), False

def parse_ics(text):
    events, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"summary": "", "start": None, "end": None, "allday": False, "rrule": None}
        elif line == "END:VEVENT":
            if cur and cur["start"] is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            name, _, value = line.partition(":")
            key, *parts = name.split(";")
            params = dict(p.split("=", 1) for p in parts if "=" in p)
            key = key.upper()
            if key == "SUMMARY":
                cur["summary"] = value
            elif key == "DTSTART":
                cur["start"], cur["allday"] = _parse_dt(value, params)
            elif key == "DTEND":
                cur["end"], _ = _parse_dt(value, params)
            elif key == "RRULE":
                cur["rrule"] = dict(kv.split("=", 1) for kv in value.split(";") if "=" in kv)
    return events

def _rrule_until(rule):
    if "UNTIL" in rule:
        u = rule["UNTIL"]
        try:
            return datetime.strptime(u, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.strptime(u[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
    return None

def expand(events, window_start, window_end):
    out = []
    for e in events:
        rule = e.get("rrule")
        dur = (e["end"] - e["start"]) if e.get("end") else timedelta(0)
        if not rule:
            if e["start"] <= window_end and (e.get("end") or e["start"]) >= window_start:
                out.append({**e, "end": e["start"] + dur})
            continue
        freq = rule.get("FREQ")
        interval = int(rule.get("INTERVAL", 1) or 1)
        count = int(rule["COUNT"]) if "COUNT" in rule else None
        until = _rrule_until(rule)
        emitted = 0
        if freq == "DAILY":
            cur = e["start"]; step = timedelta(days=interval)
            while cur <= window_end and (until is None or cur <= until):
                if cur >= window_start:
                    out.append({**e, "start": cur, "end": cur + dur, "rrule": None})
                emitted += 1
                if count and emitted >= count:
                    break
                cur += step
        elif freq == "WEEKLY":
            bydays = [_WEEKDAYS[d] for d in rule.get("BYDAY", "").split(",") if d in _WEEKDAYS]
            if not bydays:
                bydays = [e["start"].weekday()]
            week0 = e["start"] - timedelta(days=e["start"].weekday())
            wk = 0
            while True:
                base = week0 + timedelta(weeks=wk * interval)
                if base > window_end or (until and base > until):
                    break
                for wd in sorted(bydays):
                    occ = base.replace(hour=e["start"].hour, minute=e["start"].minute,
                                       second=e["start"].second) + timedelta(days=wd)
                    if occ < e["start"]:
                        continue
                    if until and occ > until:
                        continue
                    if occ > window_end:
                        continue
                    if occ >= window_start:
                        out.append({**e, "start": occ, "end": occ + dur, "rrule": None})
                    emitted += 1
                    if count and emitted >= count:
                        break
                if count and emitted >= count:
                    break
                wk += 1
        else:  # MONTHLY/YEARLY/unknown -> original occurrence only
            if window_start <= e["start"] <= window_end:
                out.append({**e, "end": e["start"] + dur, "rrule": None})
    return out

def fetch(config):
    max_events = int(config.get("max_events", 12) or 12)
    lookahead = int(config.get("lookahead_days", 30) or 30)
    sources = config.get("sources", []) or []
    now = datetime.now(timezone.utc)
    w0 = now - timedelta(hours=12)
    w1 = now + timedelta(days=lookahead)
    merged, errors = [], []
    for src in sources:
        try:
            text = _http_get(src["ics_url"])
            for ev in expand(parse_ics(text), w0, w1):
                merged.append({
                    "title": ev["summary"],
                    "start": ev["start"].isoformat(),
                    "end": (ev["end"] or ev["start"]).isoformat(),
                    "allday": ev["allday"],
                    "source": src.get("name", ""),
                    "color": src.get("color", "#888"),
                    "_sortkey": ev["start"],
                })
        except Exception as e:                           # noqa: BLE001
            errors.append({"source": src.get("name", ""), "error": str(e)})
    merged.sort(key=lambda e: e["_sortkey"])
    for e in merged:
        del e["_sortkey"]
    out = {"events": merged[:max_events], "generated": now.isoformat()}
    if errors:
        out["errors"] = errors
    return out
```

- [ ] **Step 6: Run, verify pass**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_calendar.py -v`
Expected: PASS (4 tests). (`test_parse_timed_and_allday` compares the parsed `start`; `expand`/`fetch` cover recurrence + merge.)

- [ ] **Step 7: Commit**

```bash
git add plugins/calendar/manifest.yaml plugins/calendar/backend.py tests/test_calendar.py tests/fixtures/cal_a.ics tests/fixtures/cal_b.ics
git commit -m "feat(plugins): calendar backend (multi-source ICS merge)"
```

---

### Task 6: Calendar plugin view

**Files:**
- Create: `plugins/calendar/view.html`
- Test: `tests/test_calendar_view.py`

**Interfaces:**
- Consumes: `GET /plugin/calendar/data` → `{events:[{title,start,end,allday,source,color}], generated, errors?}`.

- [ ] **Step 1: Write failing test (markup contract)**

```python
# tests/test_calendar_view.py
from pathlib import Path
def test_view_fetches_data_and_handles_ctx():
    html = Path("plugins/calendar/view.html").read_text()
    assert "/plugin/calendar/data" in html        # fetches its backend
    assert "ctx" in html                            # adapts to tile/main/filler
    assert "events" in html                         # renders the events array
```

- [ ] **Step 2: Run, verify failure**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_calendar_view.py -v`
Expected: FAIL (file missing).

- [ ] **Step 3: Create `plugins/calendar/view.html`**

```html
<!doctype html><html><head><meta charset="utf-8"><title>Calendar</title>
<style>
 html,body{margin:0;height:100%;background:#0e0e10;color:#e4e4e7;overflow:hidden;
   font-family:system-ui,Segoe UI,Arial,sans-serif}
 .wrap{height:100%;overflow:auto;padding:8px 10px}
 .ev{display:flex;gap:8px;align-items:baseline;padding:3px 0;border-bottom:1px solid #ffffff12}
 .dot{width:8px;height:8px;border-radius:50%;flex:0 0 8px;align-self:center}
 .when{opacity:.75;font-variant-numeric:tabular-nums;white-space:nowrap}
 .title{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .day{opacity:.6;margin:8px 0 2px;font-size:.8em;text-transform:uppercase;letter-spacing:.05em}
 .err{color:#fca5a5;padding:8px}
 body[data-ctx="tile"] .wrap,body[data-ctx="filler"] .wrap{font-size:12px}
 body[data-ctx="main"] .wrap{font-size:16px;padding:14px 18px}
</style></head><body>
<div class="wrap" id="wrap">…</div>
<script>
const ctx=new URLSearchParams(location.search).get("ctx")||"tile";
document.body.dataset.ctx=ctx;
const full = ctx==="main";
function fmtTime(e){
  if(e.allday) return "all day";
  const d=new Date(e.start);
  return d.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"});
}
function dayKey(iso){return new Date(iso).toLocaleDateString([], {weekday:"short",day:"numeric",month:"short"});}
async function load(){
  const wrap=document.getElementById("wrap");
  try{
    const d=await (await fetch("/plugin/calendar/data")).json();
    if(d.error){wrap.innerHTML='<div class="err">'+d.error+'</div>';return;}
    const evs=d.events||[];
    if(!evs.length){wrap.innerHTML='<div class="day">No upcoming events</div>';}
    else{
      let html="",lastDay=null;
      for(const e of evs){
        const dk=dayKey(e.start);
        if(full && dk!==lastDay){html+='<div class="day">'+dk+'</div>';lastDay=dk;}
        html+='<div class="ev"><span class="dot" style="background:'+e.color+'"></span>'+
              '<span class="when">'+(full?fmtTime(e):dk+" "+fmtTime(e))+'</span>'+
              '<span class="title">'+e.title.replace(/[<>&]/g,"")+'</span></div>';
      }
      wrap.innerHTML=html;
    }
    if(d.errors) wrap.insertAdjacentHTML("beforeend",'<div class="err">some feeds failed</div>');
  }catch(err){wrap.innerHTML='<div class="err">calendar offline</div>';}
}
load(); setInterval(load, 5*60*1000);
</script></body></html>
```

- [ ] **Step 4: Run, verify pass**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_calendar_view.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/calendar/view.html tests/test_calendar_view.py
git commit -m "feat(plugins): calendar agenda view"
```

---

### Task 7: Wire plugins + layout into `player.py` (startup + blueprints)

**Files:**
- Modify: `player.py` (imports, `main()` startup, `/status` unaffected)
- Test: `tests/test_app_smoke.py`

**Interfaces:**
- Consumes: `LayoutStore`, `PluginRegistry`, `create_plugins_blueprint`, `create_layout_blueprint`.
- Produces: module-level globals `REGISTRY`, `STORE`, and a helper `load_secrets(path) -> dict`; blueprints registered on `app`. App importable without starting go2rtc.

- [ ] **Step 1: Write failing smoke test**

```python
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
    player.bootstrap(config_path="cameras.yaml", start_workers=False, start_gateway=False)
    c = player.app.test_client()
    assert c.get("/api/sources").status_code == 200
    assert "lens1" in {s["id"] for s in c.get("/api/sources").get_json()}
    assert c.get("/api/layout").status_code == 200
```

- [ ] **Step 2: Run, verify failure**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_app_smoke.py -v`
Expected: FAIL (`AttributeError: module 'player' has no attribute 'bootstrap'`).

- [ ] **Step 3: Refactor `player.py` startup into `bootstrap()` + wire blueprints**

Add imports near the top of `player.py`:
```python
import layout as layout_mod
import plugins as plugins_mod
```
Add globals next to the existing `CFG`, `WORKERS`, `DEVICES`:
```python
REGISTRY = None
STORE = None

def load_secrets(path="secrets.local.yaml"):
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except (FileNotFoundError, OSError):
        return {}
```
Add a `bootstrap()` that does the config/registry/store/blueprint wiring (extracted from `main()`), with switches so tests can skip workers/gateway:
```python
def bootstrap(config_path=None, stream_mode=None, start_workers=True, start_gateway=True):
    global CFG, DEVICES, REGISTRY, STORE
    here = os.path.dirname(os.path.abspath(__file__))
    config_path = config_path or os.path.join(here, "cameras.yaml")
    CFG = load_config(config_path)
    DEVICES = CFG["devices"]
    pl = CFG.get("player", {})
    mode = stream_mode or pl.get("default_stream", "sub")

    secrets = load_secrets(os.path.join(here, "secrets.local.yaml"))
    REGISTRY = plugins_mod.PluginRegistry(os.path.join(here, "plugins"), secrets=secrets)
    REGISTRY.discover()
    STORE = layout_mod.LayoutStore(os.path.join(here, "state.local.json"))
    app.register_blueprint(plugins_mod.create_plugins_blueprint(REGISTRY))
    app.register_blueprint(layout_mod.create_layout_blueprint(CFG, REGISTRY, STORE))

    if start_gateway:
        g2_path = os.path.join(here, "go2rtc.generated.yaml")
        lens_index = build_go2rtc_config(CFG, g2_path)
        start_go2rtc(CFG, g2_path)
    else:
        lens_index = {ln["id"]: {"name": ln.get("name", ln["id"])}
                      for dev in DEVICES for ln in dev["lenses"]}
    if start_workers:
        gw = CFG.get("gateway", {})
        for lid, meta in lens_index.items():
            w = LensWorker(lid, meta["name"], gw, pl.get("jpeg_quality", 75),
                           pl.get("target_fps", 15), mode)
            WORKERS[lid] = w
            w.start()
    return mode
```
Then shrink `main()` to call `bootstrap()` and run the server:
```python
def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--config", default=os.path.join(here, "cameras.yaml"))
    ap.add_argument("--stream", choices=["sub", "main"], default=None)
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()
    mode = bootstrap(config_path=args.config, stream_mode=args.stream)
    port = args.port or CFG.get("player", {}).get("http_port", 8090)
    print(f"Player: http://localhost:{port}   (stream={mode})")
    try:
        app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
    finally:
        for w in WORKERS.values():
            w.stop()
        stop_go2rtc()
```
(Guard `app.register_blueprint` so a reload in tests doesn't double-register: wrap each in `try/except ValueError: pass`, or check `"plugins" not in app.blueprints`.)

- [ ] **Step 4: Run, verify pass**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_app_smoke.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

```bash
~/.venvs/rtsp/bin/python -m pytest -q
git add player.py tests/test_app_smoke.py
git commit -m "feat(player): bootstrap() wires plugins + layout blueprints"
```

---

### Task 8: UI — tile rendering for plugins, settings mode, filler, collapsible header

**Files:**
- Modify: `player.py` (the `PAGE_HEAD` CSS, `render_spotlight`/`render_grid`, `index()`, the inline `<script>`)
- Test: `tests/test_ui_markup.py` (server-rendered structure) + manual verification via the `verify`/`run` skills.

**Interfaces:**
- Consumes: `/api/sources`, `/api/layout`, `/plugin/<id>/view?ctx=...`.
- Produces: settings-mode + collapsible-header markup/JS; tiles render `<img>` (lens) or `<iframe>` (plugin); active tile shows filler + title overlay + highlight.

This task is UI-heavy; unit-test the server-rendered contract, verify interaction manually. Implement in small commits.

- [ ] **Step 1: Write failing markup test**

```python
# tests/test_ui_markup.py
import importlib
def _client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cameras.yaml").write_text(
        "gateway: {}\nplayer: {http_port: 8090}\n"
        "devices:\n  - id: cam\n    name: Cam\n    layout: spotlight\n    host: 1.2.3.4\n"
        "    lenses:\n      - {id: lens1, name: Lens 1, channel: 0}\n")
    (tmp_path / "plugins").mkdir()
    import player; importlib.reload(player)
    player.bootstrap(config_path="cameras.yaml", start_workers=False, start_gateway=False)
    return player.app.test_client()

def test_index_has_settings_and_collapse_controls(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/").get_data(as_text=True)
    assert 'id="gear"' in html or 'settings' in html.lower()   # settings toggle
    assert 'header-collapse' in html or 'collapse' in html.lower()  # collapse control
    assert '/api/layout' in html and '/api/sources' in html        # UI talks to API
```

- [ ] **Step 2: Run, verify failure**

Run: `~/.venvs/rtsp/bin/python -m pytest tests/test_ui_markup.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the UI changes**

In `player.py`:

(a) **Tile content helper** — render lens vs plugin. Add near `render_spotlight`:
```python
def _tile_media(source_id, ctx):
    """Return the inner media element for a source in a given context (tile/main/filler)."""
    if source_id and source_id.startswith("plugin:"):
        pid = source_id.split(":", 1)[1]
        return f'<iframe class="pluginframe" src="/plugin/{pid}/view?ctx={ctx}" frameborder="0"></iframe>'
    # lens
    return f'<img class="cam" data-id="{source_id}" src="/stream/{source_id}">'
```

(b) **render_spotlight / render_grid** — give every tile a stable slot id and a media container the JS can swap; render the big pane via `_tile_media(selected, "main")`; render the active tile's slot as a filler container with a title overlay. Keep the existing thumbnail/promote structure; add `data-source` to tiles and a `.fillerhost`/`.titleoverlay` in the active tile. (Lenses keep MJPEG; plugins use the iframe helper.)

(c) **CSS (`PAGE_HEAD`)** — add:
```css
 /* collapsible header */
 header.collapsed{display:none}
 #revealbar{position:fixed;top:0;left:0;right:0;height:6px;background:#2563eb55;cursor:pointer;z-index:20;display:none}
 body.headerhidden #revealbar{display:block}
 /* settings mode */
 .tile .picker{position:absolute;inset:auto 6px 6px 6px;z-index:5;display:none}
 body.settings .tile .picker{display:block}
 .tile .titleoverlay{position:absolute;top:0;left:0;right:0;padding:4px 8px;font-size:12px;
   font-weight:600;background:linear-gradient(#000b,#0000);z-index:3}
 .pluginframe{width:100%;height:100%;border:0;background:#000;display:block}
 .tile.active{outline:2px solid var(--accent);outline-offset:-2px}
```

(d) **Header controls** — in `index()` add a collapse button to the header and a `#revealbar`, plus a settings (gear) button:
```python
controls += ('<button class="sbtn" id="gear" onclick="toggleSettings()">⚙</button>'
             '<button class="sbtn" id="header-collapse" onclick="collapseHeader()">▾</button>')
# after </header>:
panes = '<div id="revealbar" onclick="showHeader()" title="Show menu"></div>' + panes
```

(e) **JS** — add to the inline `<script>`:
```javascript
// ---- collapsible header (persisted) ----
function applyHeader(c){document.body.classList.toggle('headerhidden',c);
  document.querySelector('header').classList.toggle('collapsed',c);}
function collapseHeader(){applyHeader(true); saveUI({header_collapsed:true});}
function showHeader(){applyHeader(false); saveUI({header_collapsed:false});}
// ---- server-side layout state ----
let LAYOUT={ui:{header_collapsed:false},devices:{}};
let SOURCES=[];
async function loadState(){
  SOURCES=await (await fetch('/api/sources')).json();
  LAYOUT=await (await fetch('/api/layout')).json();
  applyHeader(!!(LAYOUT.ui&&LAYOUT.ui.header_collapsed));
  applyAssignments();
}
function saveUI(ui){LAYOUT.ui=Object.assign({},LAYOUT.ui,ui);
  fetch('/api/layout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(LAYOUT)});}
function saveLayout(){fetch('/api/layout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(LAYOUT)});}
function toggleSettings(){document.body.classList.toggle('settings');
  if(!document.body.classList.contains('settings')) saveLayout();}
// applyAssignments(): for each device, set each tile's media from LAYOUT.devices[dev].tiles,
// the active tile's filler from .filler (rendered via /plugin/.. iframe or stream),
// build the per-tile <select class="picker"> from SOURCES (lenses + plugins), and a
// filler <select> on the active tile. On change -> update LAYOUT and call applyAssignments().
```
Provide `applyAssignments()` with the real DOM wiring: populate each `.picker` select with `SOURCES`, set `<img>`/`<iframe>` `src` per assignment, render the active tile as filler + `.titleoverlay` showing the original tile title, and a small ⚙ on the active tile to pick its filler. Call `loadState()` on page load (replacing the old localStorage init from the current build) and keep the existing `promote()` but have it update `LAYOUT.devices[dev].selected` and `saveLayout()`.

- [ ] **Step 4: Run markup test + full suite**

Run: `~/.venvs/rtsp/bin/python -m pytest -q`
Expected: PASS (all).

- [ ] **Step 5: Manual verification (record results)**

Start locally: `./run.sh --port 8091` (dev box) → open `http://localhost:8091`:
- Header **▾** collapses to the reveal bar; reload → still collapsed (persisted).
- **⚙** enters settings mode; each tile shows a dropdown of lenses + Calendar + Clock; pick Calendar for a slot, Save → tile shows the agenda iframe.
- Select a lens → it fills the main pane; its tile shows the configured **filler** with the original title overlaid + highlight; the active tile's ⚙ lets you change the filler.
- Reload → assignments, filler, selection, header state all restored from the server.

- [ ] **Step 6: Commit**

```bash
git add player.py tests/test_ui_markup.py
git commit -m "feat(ui): plugin tiles, settings mode, filler, collapsible header"
```

---

### Task 9: Regression + docs + deploy refresh

**Files:**
- Modify: `README.md` (Plugins section), `cameras.example.yaml`/`secrets` docs, `.meta/rtsp.md` (note plugin layer)
- Test: full suite green; manual on the Pi.

- [ ] **Step 1: Regression test — no plugins dir behaves as before**

```python
# tests/test_app_smoke.py  (add)
def test_no_plugins_dir_ok(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cameras.yaml").write_text(
        "gateway: {}\nplayer: {}\ndevices:\n  - id: cam\n    name: Cam\n    layout: spotlight\n"
        "    host: 1.2.3.4\n    lenses:\n      - {id: lens1, name: L1, channel: 0}\n")
    import importlib, player; importlib.reload(player)
    player.bootstrap(config_path="cameras.yaml", start_workers=False, start_gateway=False)
    assert player.app.test_client().get("/api/sources").status_code == 200
```

- [ ] **Step 2: Run full suite**

Run: `~/.venvs/rtsp/bin/python -m pytest -q`
Expected: PASS (all tasks).

- [ ] **Step 3: Docs** — add a **Plugins** section to `README.md`: folder layout, `manifest.yaml`/`view.html`/`backend.py` contract, the `?ctx=` convention, `/plugin/<id>/data` cache, secrets via `secrets.local.yaml` (with a commented `plugins.calendar.sources` example), and that tiles/filler/header are configured in the in-app settings (⚙) and stored in `state.local.json`. Note `pytest` dev workflow (`requirements-dev.txt`).

- [ ] **Step 4: Deploy to the Pi**

```bash
ssh homedash 'cd ~/dvri-peek && git stash -u 2>/dev/null; git pull && sudo systemctl restart dvri-peek'
# put the calendar secret on the Pi (git-ignored) if not already:
scp secrets.local.yaml homedash:dvri-peek/secrets.local.yaml
ssh homedash 'sudo systemctl restart dvri-peek; sleep 5; curl -s localhost:8090/api/sources | head'
```
Hard-refresh the kiosk (or `ssh homedash pkill -f chromium` — labwc relaunches it).

- [ ] **Step 5: Commit**

```bash
git add README.md .meta/rtsp.md tests/test_app_smoke.py
git commit -m "docs+test: plugin system docs and no-plugins regression"
git push origin main
```

---

## Self-Review

**Spec coverage:** §3 architecture → Tasks 2,3,7. §4 tile/content model → Tasks 3,8. §5 plugin contract (manifest/view/backend, autodiscovery, iframe, data cache) → Tasks 2,3,4,5,6. §6 settings mode + collapsible header → Task 8. §7 persistence/config (`state.local.json`, `cameras.yaml`, `secrets.local.yaml`) → Tasks 1,3,7. §8 API additions → Task 3. §9 calendar plugin (multi-source ICS merge) → Tasks 5,6. §10 clock → Task 4. §11 code organization (`player.py`/`plugins.py`/`layout.py`) → Tasks 1,2,3,7. §12 error handling → Tasks 2 (backend error payload), 5 (graceful feed failure), 8 (offline view), 1 (invalid state fallback). §13 security → git-ignored secrets (Global Constraints), iframe sandbox (Task 8). §14 testing → every task. §15 out-of-scope respected (no hot-reload/drag/marketplace).

**Placeholder scan:** all code steps contain complete code; the one intentionally descriptive step is Task 8 Step 3(b)/(e) `applyAssignments()` DOM wiring — bounded by an exact interface (consumes `/api/sources`,`/api/layout`,`/plugin/<id>/view?ctx=`; produces tile media swap + filler overlay) and verified by `tests/test_ui_markup.py` + manual Step 5. Acceptable for UI glue; the implementer has the data contracts and CSS hooks.

**Type consistency:** source id `plugin:<id>` used consistently (sources API, `_tile_media`, layout state). `fetch(config)->dict`, `parse_ics->list`, `expand(events,w0,w1)->list`, `registry.data->dict`, `LayoutStore.get/save->dict`, `create_*_blueprint(...)->Blueprint` consistent across tasks. State shape identical in Task 1 interface, Task 3 tests, Task 7/8 JS.
