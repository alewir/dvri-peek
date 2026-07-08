# dvri-peek — open items

## Pending deploy (Pi was offline — deploy when back)
- [ ] **Deploy + verify network watchdog** — `git pull` + `bash deploy/setup-pi.sh` on the Pi
  applies section 11 (`dvri-netwatch.timer`); verify `systemctl is-active dvri-netwatch.timer` +
  a `journalctl -t dvri-netwatch` line. Then re-confirm the **wired-Ethernet vs WiFi** decision.
- [ ] **WiFi wedged again (2026-07-08 incident #2)** — Pi 100% unreachable, kiosk stuck on
  "waiting for camera credentials" (go2rtc couldn't reach cameras over dead WiFi). Root: Pi 5
  BCM43455 brcmfmac wedge (only a reboot recovers). Watchdog built (auto-reboot on gateway loss);
  **recommend wired Ethernet** as the durable fix. SEE `.meta/raspi-setup.md`.

## Camera limitation (3-lens cam .190) — needs a decision, not more software
- [ ] **3-lens cam can't serve all 3 substreams reliably.** Whichever way lens1 is configured, a
  lens ends up stale (`online` via RTSP fallback but frozen) or disconnected (`no signal` DVRIP-only),
  and the struggling lens *migrates* (lens1→lens2…). This is a camera hardware/firmware limit, not a
  software bug — confirmed after 2 config attempts + worker stall-recovery couldn't fix it (staleness
  is in go2rtc's producer, upstream of the OpenCV worker). Options: accept (RTSP fallback keeps lens1
  `online` showing the scene); reduce load (drop a lens, or don't pull all 3 subs); camera firmware;
  or the cam may be degrading. lens1 `rtsp_channel: 1` fallback RESTORED on the Pi (DVRIP-only was worse).

## Follow-ups (surfaced by the 2026-07-08 blank-panels incident)
- [x] **Worker stall-recovery** — DONE (commit a86bdd3): per-worker liveness check, byte-identical
  frames > `STALL_TIMEOUT`=12s → force reconnect. Correct + helps genuine OpenCV-worker stalls; does
  NOT fix go2rtc-producer-level staleness from the flaky camera (that's the item above).
- [ ] **Client-side MJPEG auto-reconnect.** After a `dvri-peek` service restart, the kiosk's
  `<img>` MJPEG streams drop and don't reconnect → blank panels until a manual kiosk reload.
  Add JS to detect a stalled/errored stream and re-set `img.src`. (Interim: deploys must
  `pkill chromium` to reload the kiosk — already the documented step.)

## Done (recent)
- [x] **Display freeze ("hanging") — 2026-07-08.** Root cause: Chromium wedges the Pi 5 **vc4 GPU**,
  freezing the WHOLE display (compositor stops presenting) while system/network/streams stay healthy
  — so the hang-watchdog never fires. Proof: `grim` screencopy hung during the freeze, worked the
  instant Chromium was killed. `--disable-gpu` (software render) prevents it but SATURATED the CPU
  (chromium ~150% + player ~150% → load ~7) so it was reverted. Fix: **dvri-dispwatch** watchdog —
  probes a 1px `grim` screencopy every 30s; 2 consecutive timeouts → `pkill chromium` (lwrespawn
  relaunches). GPU kept on. Now **4 watchdogs**: hang(15s)/network/display/heartbeat. Steady load
  ~5/4cores rendering 4 streams (inherent; temp ~73°C, no throttle) — a candidate for later trimming.

- [x] **Blank panels (2026-07-08)** — (1) stale kiosk MJPEG connections after a service restart →
  reloaded the kiosk; (2) lens1 frozen (0.2 fps) because its `rtsp_channel` RTSP-fallback producer
  served stale frames in go2rtc → removed the fallback (lens1 now DVRIP-only, 12.8 fps). All 4
  streams healthy.
- [x] **Kiosk reliability + stream latency** — FFmpeg low-latency + event-driven handoff +
  `display_max_height` downscale; watchdog + heartbeat. Root on SD (SSD unreliable as boot device).
