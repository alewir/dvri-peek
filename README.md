# dvri-peek

**Peek at the camera lenses that RTSP and ONVIF hide.**

Many cheap Chinese multi-lens IP cameras (XiongMai / ICSee / "Sofia" / `H264DVR`)
only expose **lens 1** over RTSP and ONVIF. The other lenses exist — you can see
them in the ICSee/XMEye app — but they live *only* on the vendor's proprietary
**DVRIP protocol (TCP 34567)**, addressed as `channel = 0 / 1 / 2 …`.

dvri-peek bridges that protocol into a clean, self-hosted **web viewer**: a big
spotlight pane plus per-lens thumbnails, one tab per device, all decoded locally.

```
DVRIP (34567, ch 0/1/2)  ──[go2rtc]──►  RTSP (localhost)  ──[OpenCV]──►  MJPEG  ──►  your browser
```

---

## Why this exists

If you've tried the "standard" URLs on a 3-lens XiongMai/ICSee camera, you've hit this:

| Method | Result |
| --- | --- |
| `rtsp://…/…&channel=2&stream=0.sdp` | returns **lens 1** |
| `rtsp://…/onvif1`, `/onvif3`, `/onvif5` | returns **lens 1** |
| `rtsp://…/cam/realmonitor?channel=2` | returns **lens 1** |
| ONVIF `GetProfiles` | one profile (**lens 1**) |
| via the site **NVR** | NVR doesn't carry the extra lenses |
| **DVRIP `channel=1` / `channel=2`** | **lens 2 / lens 3** ✅ |

The lenses are real and separate — they're just behind DVRIP. dvri-peek finds and
serves all of them.

## Features

- 🔌 **DVRIP → RTSP** bridge via [go2rtc](https://github.com/AlexxIT/go2rtc) (handles the proprietary handshake).
- 🧩 **One tab per device**; **spotlight** layout (big pane + thumbnails) or **grid**.
- 🖱️ **Draggable split** between the big view and the thumbnails, with a **persisted** ratio.
- 📌 **Persisted lens selection** (server-side `state.local.json`); the active lens streams only in the big pane.
- 🎚️ **Automatic HD**: the selected (big-pane) stream runs main/HD; previews stay on low-res sub — no manual toggle.
- 🔁 Auto-reconnect; offline/unauthorized lenses show a clear status tile.
- 🧱 Decoding via OpenCV's bundled H.264/H.265 — **no system ffmpeg required**.
- 🔒 Credentials live in a **git-ignored** local config, never in the repo.

## Requirements

- Python 3.9+
- [`go2rtc`](https://github.com/AlexxIT/go2rtc/releases) binary (single static file)
- Network reachability to the camera/NVR (ports **554** and **34567**)

## Setup

```bash
git clone https://github.com/alewir/dvri-peek.git
cd dvri-peek

# 1) Python env + deps
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2) go2rtc binary (Linux x86-64 example; pick the build for your OS/arch)
curl -L -o go2rtc \
  https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_linux_amd64
chmod +x go2rtc

# 3) your config
cp cameras.example.yaml cameras.yaml
$EDITOR cameras.yaml          # fill in IPs + credentials
```

> **WSL2 note:** put the venv on the native Linux filesystem (e.g. `~/.venvs/dvri-peek`),
> not under `/mnt/...`, where pip is extremely slow. Point `run.sh` at it via `RTSP_VENV`.

## Finding the camera's DVRIP credentials

The DVRIP account is **not** `admin`/blank (that's RTSP-only) and **not** your NVR login.
It's the camera's **own device account**, often an auto-generated string. Open the
**ICSee / XMEye app → your camera → device / user settings** to read it. Put it in
`cameras.yaml` as `icsee_user` / `icsee_pass`.

A wrong account shows up as DVRIP `Ret: 205` ("user does not exist") and the lens
renders a **"needs credentials"** tile.

## Run

```bash
./run.sh                 # main/HD streams, http://localhost:8090
./run.sh --stream sub    # lighter low-res sub-streams
./run.sh --port 9000
```

Open **http://localhost:8090**. The player auto-starts and stops `go2rtc`.

## Configuration

`cameras.yaml` is the single source of truth (see `cameras.example.yaml` for the
full annotated template). Per device you set the host, ports, credentials, a
`layout` (`spotlight` | `grid`), and a list of `lenses` mapping a UI tile to a
DVRIP `channel`. A lens may add `rtsp_channel` for an RTSP fallback. The player
generates `go2rtc.generated.yaml` from this on every start.

## Plugins

dvri-peek supports **dashboard tile plugins** — iframe-embedded widgets that sit
alongside camera feeds as assignable tile or filler sources.

### Folder layout

Each plugin lives in its own subdirectory under `plugins/`:

```
plugins/
  clock/
    manifest.yaml   # required
    view.html       # required — rendered in an iframe
    backend.py      # optional — server-side data fetch
  calendar/
    manifest.yaml
    view.html
    backend.py
```

### `manifest.yaml` keys

| Key | Required | Description |
|-----|----------|-------------|
| `id` | no | Plugin id; defaults to folder name |
| `name` | no | Display name shown in the source picker |
| `refresh_seconds` | no | Backend cache TTL (0 = no cache) |
| `contexts` | no | List of `tile`, `main`, `filler` (default: `[tile]`) |

### `view.html`

The player serves `view.html` at `/plugin/<id>/view?ctx=<context>` inside an
iframe. The `ctx` query parameter is one of `tile` (thumbnail), `main` (big
pane), or `filler` (active-tile overlay). Use it to adapt the layout.

### `backend.py` (optional)

If present, the module must expose:

```python
def fetch(config: dict) -> dict: ...
```

The return value is served at `/plugin/<id>/data` (JSON). Results are cached for
`refresh_seconds`; if that is 0 the endpoint is called on every request.
`config` receives the plugin's block from `secrets.local.yaml` (see below).

### Plugin secrets / config

Plugin configuration that must not be committed (API keys, calendar URLs, etc.)
goes in the **git-ignored** `secrets.local.yaml`:

```yaml
# secrets.local.yaml  (git-ignored — never commit this file)
plugins:
  calendar:
    lookback_days: 90        # how far back the fetched window starts
    lookahead_days: 365      # how far ahead it reaches (big-view browsing is bounded to this window)
    max_events_grid: 2000    # safety cap on total expanded events in the dataset
    max_events: 5            # small-view agenda slice (next N upcoming); default 5 keeps it no-scroll in the tile
    sources:
      - name: "Personal"
        color: "#4285f4"     # source color for chips/bars/dots
        ics_url: "https://example.com/your-calendar.ics"   # <-- replace with real URL
      # - name: "Work"
      #   color: "#0b8043"
      #   ics_url: "https://example.com/work.ics"
```

The calendar's **big view** (when assigned to the main/spotlight pane) is a browsable
**Month** grid (multi-day events render as spanning bars) and an hourly **Week** grid —
toggle Month/Week, page with ‹ Prev / Today / Next ›. The **small view** (thumbnail/filler)
stays a compact agenda of the next `max_events`.

### Tile and filler assignment

Assign any source (camera lens or plugin) to a tile or filler slot via the
in-app settings panel (click **⚙** in the header). Assignments are persisted in
the git-ignored `state.local.json`.

### Bundled plugins

| Plugin | id | Description |
|--------|----|-------------|
| Clock | `clock` | Live clock widget (no backend) |
| Calendar | `calendar` | Multi-source ICS calendar merged into a day view |

### Dev workflow

```bash
pip install -r requirements-dev.txt   # adds pytest
pytest                                # run the full test suite
```

---

## Raspberry Pi kiosk deployment

Run dvri-peek on a wall-mounted Raspberry Pi that boots straight into a
fullscreen dashboard. Tested on a Pi 5 (Raspberry Pi OS / Debian 13, **labwc**
Wayland compositor), portable to other Pis.

### Quick (automated)

```bash
# on the Pi, with Desktop Autologin already enabled (raspi-config)
sudo raspi-config            # System Options -> Boot/Auto Login -> Desktop Autologin
git clone https://github.com/alewir/dvri-peek.git ~/dvri-peek
cd ~/dvri-peek
cp cameras.example.yaml cameras.yaml && nano cameras.yaml   # set IPs + credentials
bash deploy/setup-pi.sh
sudo reboot
```

`deploy/setup-pi.sh` installs deps, the arch-correct go2rtc, the systemd service,
the kiosk autostart, and all the SD-card-sparing tweaks below. After reboot the
Pi autologins and opens the dashboard fullscreen.

### Manual, step by step (every aspect)

1. **OS / autologin** — Raspberry Pi OS with desktop. Enable autologin to the
   desktop: `sudo raspi-config` → *System Options → Boot/Auto Login → Desktop
   Autologin*. Confirm: `/etc/lightdm/lightdm.conf` has `autologin-user=<you>`.

2. **Dependencies (apt, not pip)** — apt packages are prebuilt for ARM and avoid
   slow/fragile source builds (especially OpenCV on aarch64 + Python 3.13):
   ```bash
   sudo apt update
   sudo apt install -y python3-opencv python3-flask python3-numpy python3-yaml chromium curl git
   ```
   The player then runs under the system `python3` (no venv needed on the Pi).

3. **App + config**
   ```bash
   git clone https://github.com/alewir/dvri-peek.git ~/dvri-peek && cd ~/dvri-peek
   cp cameras.example.yaml cameras.yaml
   nano cameras.yaml          # hosts, channels, DVRIP/ICSee credentials
   ```

4. **go2rtc for your CPU** — pick the matching build:
   ```bash
   # Pi 3/4/5 64-bit OS -> arm64 ; 32-bit OS -> arm
   curl -L -o go2rtc https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_linux_arm64
   chmod +x go2rtc
   ```

5. **systemd service** (player auto-starts at boot, restarts on failure). Render
   `deploy/dvri-peek.service` with your user/path and install it:
   ```bash
   sed -e "s#__USER__#$(id -un)#g" -e "s#__DIR__#$HOME/dvri-peek#g" \
     deploy/dvri-peek.service | sudo tee /etc/systemd/system/dvri-peek.service
   sudo systemctl daemon-reload && sudo systemctl enable --now dvri-peek.service
   ```

6. **Kiosk autostart (labwc)** — keep the desktop defaults and add the kiosk
   launcher (`kiosk.sh` waits for the player, then opens Chromium fullscreen):
   ```bash
   chmod +x kiosk.sh
   mkdir -p ~/.config/labwc
   cp /etc/xdg/labwc/autostart ~/.config/labwc/autostart 2>/dev/null || true
   echo "/usr/bin/lwrespawn $HOME/dvri-peek/kiosk.sh &" >> ~/.config/labwc/autostart
   ```
   *Other compositors:* **wayfire** → add the command under `[autostart]` in
   `~/.config/wayfire.ini`; **X11/LXDE** → add it to
   `~/.config/lxsession/LXDE-pi/autostart` (prefix with `@`).

7. **SD-card protection** (important for 24/7) — the project avoids SD wear by
   design, but verify/enable:
   - Chromium profile **and** cache live in `/dev/shm` (RAM) — handled by
     `kiosk.sh`. This is the single biggest SD-writer on a kiosk.
   - go2rtc's log goes to `/tmp`, which is **tmpfs (RAM)** on Raspberry Pi OS.
   - Cap journald so logs can't grow unbounded:
     ```bash
     printf '[Journal]\nSystemMaxUse=50M\nRuntimeMaxUse=50M\n' | \
       sudo tee /etc/systemd/journald.conf.d/cap.conf
     sudo systemctl restart systemd-journald
     ```
   - The app records **no video** and writes only `go2rtc.generated.yaml` once
     per start.

8. **Disable screen blanking** so the wall display stays on:
   ```bash
   sudo raspi-config nonint do_blanking 1
   ```

9. **Reboot & verify**
   ```bash
   sudo reboot
   # after boot, from any machine:
   systemctl is-active dvri-peek            # -> active
   curl -s localhost:8090/status            # -> 4 streams "online"
   ```

### Performance

Software H.265 decode is the cost. A Pi 5 runs all streams in main/HD at ~1 of 4
cores. On a Pi 4/3, set `default_stream: sub` in `cameras.yaml`, or use the
sub-preview / HD-spotlight hybrid (previews on sub-streams, only the big pane on
main). Manage the service with `systemctl {status,restart} dvri-peek` and view
logs with `journalctl -u dvri-peek -f`.

## Troubleshooting

- **DVRIP `Ret: 205`** → wrong/unknown DVRIP account; get the device login from the ICSee app.
- **Lens stuck "connecting"** → 3 simultaneous HD DVRIP streams are heavy; first keyframe can take 10–20 s.
- **Black video / connects but no frames** → force RTP over TCP (the player already does this via `OPENCV_FFMPEG_CAPTURE_OPTIONS`); required behind NAT (e.g. WSL2).
- **`go2rtc` not found** → download the binary (see Setup) into the project dir.

## How it works

1. The player reads `cameras.yaml` and writes a `go2rtc` config: each lens becomes a
   `dvrip://…?channel=N&subtype=M` source (plus an optional RTSP fallback).
2. It launches `go2rtc`, which performs the DVRIP login + stream and **re-publishes
   each lens as plain RTSP** on `localhost`.
3. One OpenCV worker per lens pulls that RTSP, decodes H.264/H.265, and re-encodes
   to JPEG.
4. Flask serves an MJPEG stream per lens and the tabbed spotlight/grid UI.

## Credits

- [go2rtc](https://github.com/AlexxIT/go2rtc) by @AlexxIT — the DVRIP/RTSP/WebRTC engine that makes this possible.
- The Home Assistant community thread documenting DVRIP channel access on 3-lens ICSee cameras.

## License

MIT — see [LICENSE](LICENSE).

---

*Not affiliated with XiongMai, ICSee, or XMEye. Use only on cameras you own or are authorized to access.*
