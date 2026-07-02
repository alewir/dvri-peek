# dvri-peek — open items

## Bugs
- [ ] **NVR tab shows sub (low-res).** NVR/grid layout should show HIGH-RES (main tier),
  configurable per-device in `cameras.yaml` (static). Grid cells stream `/stream/<lens>` (sub);
  need a per-device flag (e.g. `grid_tier: main`) → ensure a main worker for those lenses at
  bootstrap + grid cell uses `?tier=main`.

## Features (planned)
- [ ] **Boot Pi from USB SSD** — SEE `.meta/plan-ssd-boot.md` (green-lit; do with physical access).

## Done (recent)
- [x] **Combined clock+calendar plugin** (`dashboard`) — replaces separate clock + calendar; main
  = instrument rail + browsable Month/Week calendar (multi-ICS merged) + slow news crawl; preview
  = clock + weather + next events. Deployed to Pi (HEAD 9d1d8ec).
- [x] **Pi missing icons** — `fonts-noto-color-emoji` installed + added to `setup-pi.sh` apt deps.
