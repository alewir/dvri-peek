# dvri-peek — open items

## Bugs
- [ ] **NVR tab shows sub (low-res).** NVR/grid layout should show HIGH-RES (main tier),
  configurable per-device in `cameras.yaml` (static). Grid cells stream `/stream/<lens>` (sub);
  need a per-device flag (e.g. `grid_tier: main`) → ensure a main worker for those lenses at
  bootstrap + grid cell uses `?tier=main`. SEE design in this file when planned.
- [ ] **Pi missing icons.** Weather emoji + title-bar "dvri-peek" icon render locally but not on
  the Pi. Likely no emoji font on Pi OS → install `fonts-noto-color-emoji` (add to setup-pi.sh
  apt deps). Confirm the title-bar icon isn't a separate missing asset/favicon.

## Features (planned)
- [ ] **Boot Pi from USB SSD** — SEE `.meta/plan-ssd-boot.md` (green-lit; do with physical access).
- [~] **Combined clock+calendar plugin** (main + preview) — IN PROGRESS (replaces separate
  clock + calendar plugins). frontend-design for the view.
