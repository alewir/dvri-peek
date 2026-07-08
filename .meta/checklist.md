# dvri-peek — open items

## Follow-ups (surfaced by the 2026-07-08 blank-panels incident)
- [ ] **Worker stall-recovery.** A stalled upstream stream (connection alive but video not
  advancing → `cap.read()` returns the *same* frame, or blocks; `stimeout` doesn't fire) stays
  frozen forever until a restart. The old `/stream` masked this (re-sent the last frame 15×/s so a
  frozen lens looked live); the event-driven handoff now reveals it. Add a per-worker liveness
  check: no NEW unique frame for ~N s → force reconnect (release+reopen the capture). Makes any
  stall self-heal. Design carefully (threading; a blocked `read()` needs an out-of-band release).
- [ ] **Client-side MJPEG auto-reconnect.** After a `dvri-peek` service restart, the kiosk's
  `<img>` MJPEG streams drop and don't reconnect → blank panels until a manual kiosk reload.
  Add JS to detect a stalled/errored stream and re-set `img.src`. (Interim: deploys must
  `pkill chromium` to reload the kiosk — already the documented step.)

## Done (recent)
- [x] **Blank panels (2026-07-08)** — (1) stale kiosk MJPEG connections after a service restart →
  reloaded the kiosk; (2) lens1 frozen (0.2 fps) because its `rtsp_channel` RTSP-fallback producer
  served stale frames in go2rtc → removed the fallback (lens1 now DVRIP-only, 12.8 fps). All 4
  streams healthy.
- [x] **Kiosk reliability + stream latency** — FFmpeg low-latency + event-driven handoff +
  `display_max_height` downscale; watchdog + heartbeat. Root on SD (SSD unreliable as boot device).
