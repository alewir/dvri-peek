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
- 📌 **Persisted lens selection** (localStorage); the active lens streams only in the big pane.
- 🎚️ **Main HD / Sub** stream toggle.
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
