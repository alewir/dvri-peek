# Architecture — dvri-peek

System/module architecture and data flow. For the DVRIP/multi-lens **protocol**
(how the lenses are discovered + authenticated) see `.meta/rtsp.md`; this doc is
the **software** map (modules, runtime components, request/data flow, lifecycles).

---

## 1. Topology

```
 cameras.yaml ─┐                        secrets.local.yaml ─┐         state.local.json
 (devices,     │  build_go2rtc_config        (plugin cfg)   │         (layout, gitignored)
  lenses,creds)│        │                                   │              │
              ▼        ▼                                     ▼              ▼
        ┌──────────────────────────── player.py (Flask, threaded) ──────────────────────────┐
        │  go2rtc subprocess        LensWorker threads          blueprints                    │
        │  DVRIP→RTSP bridge   ┌─ WORKERS[lid]   (sub, always)  ┌ plugins  (plugins.py)        │
        │  127.0.0.1:8554  ───►├─ MAIN_WORKERS[lid] (on-demand) └ layout   (layout.py)         │
        │   <lid> / <lid>_main │   OpenCV decode → JPEG                                        │
        └───────┬──────────────┴───────────────┬───────────────────────┬─────────────────────┘
                │ /stream/<lid>[?tier=main]     │ /status /api/streams  │ /api/sources /api/layout
                │ (MJPEG)                       │ /api/layout (POST)    │ /plugin/<id>/view|data
                ▼                                                       ▼
        ┌────────────────────────── browser (one tab/device) ──────────────────────────┐
        │  spotlight: big pane + thumbnails  |  grid: cells   |  plugin iframes          │
        │  inline JS: loadState · applyAssignments · poll · promote · syncStreams         │
        └───────────────────────────────────────────────────────────────────────────────┘
```

Three external inputs (all git-ignored): `cameras.yaml` (cameras), `secrets.local.yaml`
(plugin config/secrets), `state.local.json` (UI layout, server-written). One spawned
subprocess (`go2rtc`). Everything else is in-process Flask + worker threads.

## 2. Modules

| File | Responsibility | Depends on | cv2? |
|---|---|---|---|
| `player.py` | Flask app, config→go2rtc gen, `LensWorker` decode threads, stream/status/streams routes, the entire client UI (server-rendered HTML + inline JS), `bootstrap()`/`main()`. Registers the two blueprints. | cv2, numpy, yaml, flask, layout, plugins | yes |
| `plugins.py` | `Plugin`, `PluginRegistry` (autodiscover `plugins/<id>/`, single-lock cached `data()`), `create_plugins_blueprint` (`/plugin/<id>/view`,`/data`,`/static`). | flask | no |
| `layout.py` | `LayoutStore` (atomic read/write + normalize of `state.local.json`), `create_layout_blueprint` (`/api/sources`, `/api/layout`). | flask, yaml | no |
| `plugins/<id>/backend.py` | optional `fetch(config)->dict`, served (cached) at `/plugin/<id>/data`. Stdlib-only. | stdlib | no |
| `plugins/<id>/view.html` | iframe UI, adapts to `?ctx=tile\|main\|filler`. | — | — |
| `deploy/`, `kiosk.sh`, `run.sh` | Pi systemd unit + kiosk autostart + dev launcher (all committed `+x`). | — | — |

`plugins.py` and `layout.py` are deliberately cv2-free so they (and their tests)
import without the heavy OpenCV dependency.

## 3. Stream model (tiers + lifecycle)

- go2rtc publishes **two** restreams per lens: `<lid>` (sub, low-res) and `<lid>_main` (HD).
- A `LensWorker` is **single-tier for life** (`tier ∈ {sub,main}`); changing tier = a
  different worker, never a reconnect (avoids blanking).
  - `WORKERS[lid]` — **sub**, started at boot, always running → feeds previews.
  - `MAIN_WORKERS[lid]` — **main**, started/stopped on demand for the selected lens by
    `POST /api/streams {main:[…]}` (guarded by `_MAIN_LOCK`).
- A worker `holds its last frame` across transient reconnects once `ready` (never blanks);
  the held-frame state surfaces as a `"reconnecting (tier)"` status (yellow dot client-side).
- **Progressive big-pane load:** the big `<img>` opens the sub stream instantly; `poll()`
  watches `/status.main_ready` and swaps the same `<img>` to `?tier=main` once the main
  worker has produced a frame → live low-res → live HD, no black gap.
- **Connection budget:** every MJPEG `<img>` is a persistent HTTP/1.1 connection (~6/host
  cap). Hidden device tabs pause their streams (`src='data:,'`, stashed in `dataset.psrc`);
  `setMedia` force-closes a replaced `<img>` before swapping. Steady state ≈ 1 main + (N−1)
  sub for the visible spotlight device.

## 4. HTTP surface

| Route | Owner | Purpose |
|---|---|---|
| `GET /` | player | server-rendered tabbed UI + inline JS |
| `GET /stream/<lid>[?tier=main]` | player | MJPEG (multipart/x-mixed-replace) from the sub or main worker; 404 if absent |
| `GET /snapshot/<lid>[?tier=main]` | player | single JPEG |
| `GET /status` | player | per-lens `{status,resolution,fps,tier,main_ready,main_resolution,main_fps}` |
| `POST /api/streams {main:[…]}` | player | start a main worker per listed lens, stop the rest |
| `GET /api/sources` | layout | assignable sources: lenses (`lensN`) + plugins (`plugin:<id>`) |
| `GET/POST /api/layout` | layout | read/write `state.local.json` (UI layout) |
| `GET /plugin/<id>/view?ctx=` | plugins | plugin iframe HTML |
| `GET /plugin/<id>/data` | plugins | cached `backend.fetch(config)` JSON |

Bind: `0.0.0.0`, **no auth** (LAN-trusted; see README "LAN-open by design").

## 5. Layout / state

`state.local.json` (server-owned, written only via `POST /api/layout`):
```
{ ui:{header_collapsed}, devices:{ <devId>:{ tiles:{<slot>:<srcId>}, filler:<srcId|null>,
                                              selected:<srcId>, split:"<flexBasis>" } } }
```
- Source id convention: lens = `lensN`; plugin = `plugin:<id>`.
- The client reconciles stale ids against `/api/sources` at render (a removed id falls back
  to the slot default; exactly one tile is ever active). Writes are gated on a successful
  layout load (`LAYOUT_LOADED`) so an unloaded default can't clobber disk.

## 6. Client (inline JS in `player.py`)

| Fn | Role |
|---|---|
| `loadState()` | `Promise.allSettled` of `/api/sources` + `/api/layout` (independent), then `applyAssignments()` + `initDivider()` + `pauseHiddenStreams()` |
| `applyAssignments()` | render tiles/cells/big pane from `LAYOUT`+`SOURCES`; compute the main-lens set; call `syncStreams()` |
| `setMedia(el,html)` | `dataset.mkey`-guarded write (no needless MJPEG teardown); force-closes old `<img>` before a real swap |
| `promote(dev,lid)` | set `selected`, persist, re-render (no-op in settings mode) |
| `syncStreams(main)` | `POST /api/streams` — the selected big-pane lens(es), by `plugin:`-prefix not a SOURCES lookup |
| `poll()` | 1.5 s `/status`: per-tile status dot + the one-time visible big-pane sub→main swap |
| `pauseHiddenStreams()` | release/restore hidden-tab MJPEG connections |
| `initDivider()` | pointer-events split resize (mouse+touch, `setPointerCapture`), width-aware clamp, server-persisted `split` |

Untrusted strings (source names, plugin titles) are HTML-encoded (`esc()` / server `html.escape`)
before innerHTML; `textContent` paths are never `esc()`-ed.

## 7. Plugin system

- Autodiscovered from `plugins/<id>/` (`manifest.yaml` + `view.html` + optional `backend.py`).
- Rendered in a sandboxed iframe at `/plugin/<id>/view?ctx=tile|main|filler`; the view adapts
  (e.g. calendar: small ctx = agenda, main ctx = month/week grid).
- `backend.fetch(config)` → JSON at `/plugin/<id>/data`, cached per `refresh_seconds`; `config`
  is the plugin's block from `secrets.local.yaml`.
- Calendar backend: stdlib ICS parse + recurrence expansion (DAILY/WEEKLY incl. BYDAY/COUNT/UNTIL,
  EXDATE, RECURRENCE-ID), TZID→UTC, multi-source merge, broad cached window.

## 8. Deployment (Pi kiosk)

`systemd dvri-peek.service` runs `python3 player.py` (system python + apt OpenCV/Flask, no venv).
labwc autostart `lwrespawn ~/dvri-peek/kiosk.sh` → `kiosk.sh` waits for `:8090` then launches
Chromium `--kiosk` with profile/cache in `/dev/shm` (RAM, SD-sparing). Deploy = `git reset --hard
origin/main` + `systemctl restart dvri-peek` + reload the kiosk. See `.meta/raspi-setup.md`
(git-ignored, host-specific) for the live runbook.

## 9. Key invariants / decisions

- One writer for layout state (server `LayoutStore`); the client is a renderer + intent source.
- Stream tier is a worker identity, not a mutable mode → no reconnect-blank on switch.
- RTP over **TCP** everywhere (NAT/WSL2 drops UDP RTP); set via `OPENCV_FFMPEG_CAPTURE_OPTIONS`.
- Secrets live only in git-ignored files (`cameras.yaml`, `secrets.local.yaml`); never committed.
- cv2 isolated to `player.py` + worker; framework modules (`plugins`,`layout`) stay importable
  without it. Tests are CWD-proof via `tests/conftest.py:ROOT`.
