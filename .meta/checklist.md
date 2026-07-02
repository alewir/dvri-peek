# dvri-peek — open items

## Features (planned)
- [ ] **Boot Pi from USB SSD** — SEE `.meta/plan-ssd-boot.md` (green-lit; user has KVM access).

## Done (recent)
- [x] **NVR tab in HD** — per-device `grid_tier: main` (cameras.yaml) makes a grid device's base
  workers stream main/HD; verified nvr_ch0 → tier=main 2560x1440, spotlight previews stay sub.
- [x] **Combined clock+calendar plugin** (`dashboard`) — main = instrument rail + browsable
  Month/Week calendar (multi-ICS merged) + slow news crawl; preview = clock + weather + next events.
- [x] **Pi missing icons** — `fonts-noto-color-emoji` installed + added to `setup-pi.sh`.
