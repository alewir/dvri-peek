# dvri-peek — open items

_(no open items)_

## Done (recent)
- [x] **Kiosk reliability + stream latency** (2026-07-08) — FFmpeg low-latency capture opts +
  event-driven frame handoff + `display_max_height` downscale (NVR 2K→1080p; load 3.96→~2.0,
  temp 72→66°C); systemd watchdog (auto-reboot on hang, no more manual resets) + panic reboot +
  health heartbeat + faster journald flush. Deployed to Pi (HEAD 4eb7f11).
- [x] **Pi hang root-caused** — whole-Pi lockup was the USB-UAS SSD (hung + failed to reboot).
  Reverted to SD boot (`BOOT_ORDER=0xf41`); SSD dormant. SEE `.meta/history/done-ssd-boot.md`.
- [x] **NVR tab in HD** — per-device `grid_tier: main`; `display_max_height` caps the display.
- [x] **Combined clock+calendar plugin** (`dashboard`).
- [x] **Pi missing icons** — `fonts-noto-color-emoji`.
