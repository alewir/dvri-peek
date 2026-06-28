# Design Spec — dvri-peek Pluggable Dashboard Tiles

- Date: 2026-06-28
- Status: approved (brainstorming) → ready for implementation plan
- Scope: a single implementation plan

## 1. Goal

Turn dvri-peek's spotlight panel into a configurable dashboard. Each side tile can
display a **camera lens** or a **plugin widget** (e.g. a merged Google Calendar
agenda). Selecting a tile promotes its content to the big main pane; the selected
tile then shows configurable **filler** content instead of going blank. Plugins are
**drop-in folders**, autodiscovered at startup. Tile/filler choices are configured
in an in-app **settings mode** and persisted **server-side**.

Non-goals: hot-reload (nice-to-have), drag-reorder, plugin marketplace, per-plugin
interactive auth wizards.

## 2. Terminology

| Term | Meaning |
|---|---|
| **Source** | A selectable content item: a **lens** (from `cameras.yaml`) or a **plugin** instance |
| **Tile** | A slot in the side panel (spotlight layout) or grid cell |
| **Main pane** | The big spotlight view showing the currently selected source |
| **Filler** | Content shown in the selected tile's slot while its real content is in the main pane |
| **Context** | Render size/role a plugin is shown in: `tile`, `main`, or `filler` |

## 3. Architecture

```
cameras.yaml ──► lenses ─┐
                         ├─► sources ──► tiles (side) + main pane
plugins/<id>/ ──► plugins ┘                 ▲
                                            │ assignment + filler
state.local.json ◄── POST /api/layout ◄── settings mode (UI)

plugin backend.py ──► /plugin/<id>/data (JSON, cached) ──► view.html (iframe) ──► tile/main/filler
secrets.local.yaml ──► plugin config/secrets (read server-side)
```

Decisions & rejected alternatives:
- **Hybrid folder plugin** (vs frontend-only): frontend-only cannot do Google
  Calendar securely (OAuth/CORS/secret exposure). Hybrid supports both pure-frontend
  (clock) and server-backed (calendar) plugins.
- **iframe rendering** (vs HTML-fragment injection): isolation — a plugin cannot
  break the player's CSS/JS; plugins are plain HTML/JS.
- **Server-side persistence** (vs per-browser localStorage): a kiosk must keep config
  across reboots and share it with a phone/PC used to configure it.

## 4. Tile / content model

- Each device (existing `cameras.yaml` device) renders in `spotlight` or `grid`.
- A tile references a **source id**: either a lens id (existing) or `plugin:<id>`
  (optionally with an instance key, future).
- Per **spotlight device**: one tile is "active" (selected → shown in main). The
  active tile renders its **filler** source, a highlight border, and an overlay with
  its **original title** (e.g. `Lens 1 · in main`), plus a small ⚙ to edit its filler.
- Lenses render as today (MJPEG `<img>`); plugins render as `<iframe>`.

## 5. Plugin contract

### 5.1 Folder layout
```
plugins/<id>/
  manifest.yaml      # required
  view.html          # required (frontend)
  backend.py         # optional (server-side data provider)
  static/            # optional assets, served at /plugin/<id>/static/...
```

### 5.2 manifest.yaml
```yaml
id: calendar                 # unique; matches folder name
name: "Calendar"             # label shown in dropdowns / overlays
refresh_seconds: 1800        # backend data cache TTL (0 = no backend / no cache)
contexts: [tile, main, filler]   # which render roles it supports
config: [refresh_minutes, max_events, sources]   # config keys it reads (documentation)
```

### 5.3 view.html
- Served at `GET /plugin/<id>/view?ctx=tile|main|filler` inside a sandboxed iframe.
- Receives `ctx` (query param) to adapt density (compact for tile/filler, full for main).
- If the plugin has a backend, `view.html` fetches `GET /plugin/<id>/data` (JSON) and
  renders client-side; it should poll on an interval ≥ a few seconds for live widgets.
- Pure-frontend plugins (clock) ignore `/data`.

### 5.4 backend.py (optional)
- Contract: `def fetch(config: dict) -> dict` — returns JSON-serializable data.
- Runs server-side; may read secrets from `secrets.local.yaml` (passed via `config`).
- Must be defensive (own try/except, network timeouts); exceptions are caught by the
  host and surfaced as an error payload, never crash the player.

### 5.5 Autodiscovery & data cache
- At startup the server scans `plugins/*/manifest.yaml`, validates, and imports
  `backend.py` if present (failures are logged and that plugin is marked unavailable).
- `GET /plugin/<id>/data` calls `fetch()` and caches the result for `refresh_seconds`
  (per plugin). A background refresh or lazy-on-expiry refresh is acceptable.
- Optional hot-reload: re-scan when a manifest mtime changes (nice-to-have).

## 6. Settings mode (UI)

- A corner **⚙** button toggles settings mode for the active device tab.
- In settings mode each side tile overlays a **dropdown** of all sources
  (lenses + plugins); the active tile additionally shows a **filler** dropdown.
- **Save** issues `POST /api/layout` and exits settings mode.
- **First run** (no `state.local.json`): the device opens in settings mode so tiles
  show dropdowns immediately.
- **Normal mode**: selecting a tile promotes it to main; the active tile shows filler
  + highlight + original-title overlay + a small ⚙ to edit just its filler.
- Selection of the active lens is not double-streamed (the active tile shows filler,
  not the live stream — that's in the main pane). Existing behavior preserved.
- **Collapsible top panel:** the header (title, tabs, stream toggle, ⚙) can be
  **minimized** to reclaim screen space on a wall kiosk. A toggle hides the header,
  leaving a slim always-present reveal affordance (a thin top strip / small floating
  button) to bring it back. The collapsed/expanded state is **persisted** (see §7).

## 7. Persistence & config

- **`state.local.json`** (gitignored) — layout state:
  ```json
  {
    "ui": { "header_collapsed": false },
    "devices": {
      "cam190": { "tiles": {"slot1":"lens1","slot2":"plugin:calendar","slot3":"lens3"},
                  "filler": "plugin:clock", "selected": "lens1" }
    }
  }
  ```
  Loaded at startup; written by `POST /api/layout`. Missing/!valid → first-run defaults
  (tiles = the device's lenses, no filler).
- **`cameras.yaml`** — unchanged (lenses/devices/layout).
- **`secrets.local.yaml`** (gitignored) — plugin config/secrets, e.g.:
  ```yaml
  plugins:
    calendar:
      refresh_minutes: 30
      max_events: 12
      sources:
        - { name: "Personal", color: "#4285f4", ics_url: "https://…/basic.ics" }
  ```

## 8. HTTP API additions

| Route | Method | Purpose |
|---|---|---|
| `/api/sources` | GET | list available sources (lenses + plugins) for dropdowns |
| `/api/layout` | GET/POST | read / persist device tile + filler + selection state |
| `/plugin/<id>/view` | GET | plugin frontend (iframe), `?ctx=tile\|main\|filler` |
| `/plugin/<id>/data` | GET | plugin backend JSON (cached per `refresh_seconds`) |
| `/plugin/<id>/static/<path>` | GET | plugin static assets |

Existing routes (`/`, `/stream/<lens>`, `/snapshot/<lens>`, `/status`, `/set_stream`)
are unchanged.

## 9. Calendar plugin (first real plugin)

- `plugins/calendar/` with `backend.py` + `view.html`, contexts `[tile, main, filler]`.
- `backend.py.fetch(cfg)`:
  - reads `cfg.sources` (list of `{name, color, ics_url}`), `max_events`, `refresh_minutes`.
  - fetches each `ics_url` (HTTPS, timeout), parses VEVENTs (stdlib parsing; a small
    dedicated parser to avoid a heavy dep — `icalendar` only if justified in the plan),
    expands near-term recurrences enough to fill `max_events`.
  - merges across sources, sorts by start, keeps the next `max_events`, tags each with
    its source `name`/`color`.
  - returns `{ "events": [{title, start, end, allday, source, color}], "generated": ts }`.
- `view.html`: agenda list — compact (next few, date+time+title, color dot) in
  `tile`/`filler`; fuller (grouped by day) in `main`.
- Multiple calendars merge into one color-coded agenda.

## 10. Clock plugin (trivial, proves frontend-only path)

- `plugins/clock/` with `manifest.yaml` (no backend) + `view.html` showing date/time,
  updating client-side. Demonstrates a plugin with zero server code.

## 11. Code organization

Split the growing `player.py` into focused units:
- `player.py` — Flask app, page render, existing stream routes.
- `plugins.py` — discovery, manifest validation, `/plugin/*` routes, data cache.
- `layout.py` — `state.local.json` load/save, `/api/layout`, `/api/sources`.

## 12. Error handling

- Plugin import/fetch failures → that source still appears but renders an error tile
  ("Calendar unavailable"); the player and other tiles keep working.
- Backend `fetch()` wrapped with try/except + network timeout; `/data` returns
  `{ "error": "..." }` on failure; `view.html` shows a graceful error state.
- Invalid `state.local.json` → fall back to first-run defaults (do not crash).

## 13. Security

- Plugins are the user's own trusted drop-ins (documented); `view.html` served in a
  sandboxed iframe to contain UI mistakes.
- Secrets only in gitignored `secrets.local.yaml`, read server-side, never sent to the
  client except as rendered data, never logged.

## 14. Testing

- ICS parse + multi-source merge/sort/limit (unit, fixed sample feeds).
- Autodiscovery: a dummy plugin folder is found, validated, and served.
- Backend error path: a failing `fetch()` yields an error payload, player stays up.
- Layout persistence round-trip: `POST /api/layout` then restart → state restored.
- Regression: with `plugins/` empty, the player serves lenses exactly as before.

## 15. Out of scope (future)

Hot-reload of plugins, drag-and-drop tile reordering, plugin marketplace/installer,
per-plugin OAuth wizards, multiple instances of the same plugin with distinct config.
