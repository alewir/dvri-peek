# Technical Specification — Multi-Lens XiongMai/ICSee Camera Access

Status: implemented · Scope: how dvri-peek discovers, authenticates, and streams
every lens of a XiongMai/ICSee ("Sofia" / `H264DVR`) multi-lens IP camera, and
how those streams reach a browser.

---

## 1. Problem statement

Budget multi-lens IP cameras (XiongMai OEM; apps ICSee / XMEye) advertise only
**one** lens over standard protocols. The remaining lenses are reachable solely
through the vendor's proprietary **DVRIP** protocol. Goal: enumerate and view
**all** lenses with open tooling.

## 2. Device fingerprint

| Signal | Value | Meaning |
|---|---|---|
| RTSP `Server:` header | `H264DVR 1.0` | XiongMai/Sofia RTSP stack |
| HTTP web UI | "Web Viewer" / `RSUI.css` | XiongMai web client |
| Open TCP ports | `554` (RTSP), `34567` (DVRIP), `80` (HTTP) | Sofia device |
| RTSP digest `realm` | 16-hex (e.g. `e0743359b5c18232`) | **device-unique** id; equal realms ⇒ same physical device |
| DVRIP login reply | `{"DeviceType":"IPC","ChannelNum":N,...}` | N = lens/channel count |

Port `34567` is the strongest tell — it is the Sofia/DVRIP "NetSurveillance"
port the mobile apps use.

## 3. Protocol analysis

### 3.1 RTSP (TCP 554) — exposes lens 1 only
Native scheme (credentials embedded in the path):
```
rtsp://HOST:554/user=USER&password=PASS&channel=C&stream=S.sdp?real_stream
   S = 0 (main) | 1 (sub)
```
Findings:
- `admin` + **blank** password is commonly accepted for RTSP.
- The `channel` value is **ignored** — `channel=1|2|3`, `/onvif1|3|5`,
  `/cam/realmonitor?channel=N` all return **lens 1**. Verified by frame content,
  not SPS (different lenses with identical encoder config share an SPS).
- Codecs observed: video H.265 (HEVC), audio G.711a (PCMA).

### 3.2 ONVIF (TCP 8899) — not the answer
Often disabled (port closed) or advertises a single video profile; the extra
lenses are not represented. WS-Discovery may not respond.

### 3.3 DVRIP / Sofia (TCP 34567) — the lenses live here
Binary protocol; one lens per `channel` index, **zero-based** (`0,1,2,…`).

Login:
- Password hash ("sofia hash"): take `md5(password)` (16 bytes); for i in 0..7,
  `out[i] = b62[(md5[2i] + md5[2i+1]) % 62]`, where
  `b62 = 0-9 A-Z a-z`. Empty password ⇒ `tlJwpbo6`.
- Login packet: 20-byte header `FF 00 00 00 | sid(4 LE) | seq(4 LE) | 00 00 |
  msgid(2 LE)=1000 | len(4 LE)` + JSON body + `\x00`:
  `{"EncryptType":"MD5","LoginType":"DVRIP-Web","UserName":U,"PassWord":hash}`.
- Reply JSON `Ret` codes: **100** = OK; **205** = user does not exist / bad
  account; 203 = wrong password. `SessionID` returned on success; `ChannelNum`
  gives the lens count.
- **Credentials are per-device**, often an auto-generated account from the ICSee
  app (e.g. `mnwb`/`t37c3x`) — **not** `admin`/blank and **not** the NVR login.

Stream URL (consumed by go2rtc):
```
dvrip://USER:PASS@HOST:34567?channel=C&subtype=S      C = 0..N-1 ; S = 0(main)|1(sub)
```

### 3.4 NVR relationship
A site NVR is a **separate device** (distinct RTSP realm, own login). It does not
necessarily carry the multi-lens camera's extra channels — those are direct on
the camera's DVRIP.

## 4. Discovery methodology (reproducible)
1. Subnet scan TCP `554` + `34567` → candidate Sofia devices.
2. RTSP `OPTIONS`/`DESCRIBE` → confirm `H264DVR`; capture digest `realm`.
3. Compare realms → collapse aliases (same device on multiple IPs / NVR vs cam).
4. DVRIP login (try device/ICSee account) → read `ChannelNum`.
5. Pull each `channel=0..N-1` and compare **decoded frames** to confirm distinct
   lenses (resolution and/or content differ).

## 5. Architecture

```
 camera (DVRIP 34567, ch 0..N)
        │  dvrip://…?channel=C&subtype=S
        ▼
   go2rtc  ── re-publishes each lens as RTSP on 127.0.0.1:8554/<name> ──►
        ▼
   OpenCV worker per lens  (decode H.264/H.265 → JPEG)
        ▼
   Flask  ── MJPEG per lens + tabbed spotlight/grid UI ──►  browser
```
- go2rtc handles the proprietary DVRIP handshake (OpenCV/ffmpeg cannot).
- DVRIP→RTSP is a **remux** (no transcode) → no ffmpeg dependency; OpenCV's
  bundled decoders do H.265.
- A lens may declare an RTSP fallback; go2rtc lists `[dvrip, rtsp]` and uses the
  first that connects.

## 6. Stream model
- Per lens go2rtc exposes `<id>` (sub) and `<id>_main` (main).
- Player config maps a UI tile → device → lens → DVRIP `channel` (+ optional
  `rtsp_channel`). See `cameras.example.yaml`.
- Performance lever: previews on sub, spotlight on main (≈1 main + N sub
  decodes).

## 7. Player surface (HTTP)
| Route | Purpose |
|---|---|
| `/` | tabbed UI (one tab/device; spotlight or grid) |
| `/stream/<lens>` | MJPEG (multipart/x-mixed-replace) |
| `/snapshot/<lens>` | single JPEG |
| `/status` | JSON: per-lens status, resolution, fps |
| `/set_stream?mode=sub\|main` | switch stream tier |

UI: spotlight = big pane + lens thumbnails; click promotes a lens (active lens
shown only in the big pane), draggable split + selection persisted (localStorage).

## 8. Deployment (summary)
Player runs as a systemd service; a labwc autostart opens Chromium fullscreen.
Full step-by-step in the project README. SD-card wear avoided: Chromium
profile/cache in tmpfs, go2rtc log in `/tmp` (tmpfs), journald capped, no video
recording.

## 9. Constraints & notes
- **NAT (e.g. WSL2):** force RTP over **TCP** — UDP RTP return packets are not
  routed back (`OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp`).
- **Decode cost:** software H.265; a Pi 5 handles several HD streams, weaker Pis
  should prefer sub-streams.
- **Security:** credentials live only in the git-ignored `cameras.yaml`.
- A `Ret:205` on DVRIP almost always means the *account* is wrong, not the host.

## 10. Pluggable dashboard-tile layer

Plugins autodiscovered from `plugins/<id>/` (manifest.yaml + view.html +
optional backend.py); iframe-rendered at `/plugin/<id>/view?ctx=tile|main|filler`;
data cached at `/plugin/<id>/data`. Server-side layout state in git-ignored
`state.local.json`; plugin secrets in `secrets.local.yaml`. Bundled: `clock`, `calendar`.
