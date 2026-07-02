# Plan — Boot dvri-peek Pi from the USB SATA SSD (reliability + speed)

Status: READY (green-lit) · Risk: HIGH (boot-device change; do with physical access to the Pi)

## Goal
Move the Pi's root filesystem from the microSD (`mmcblk0`, the #1 reliability risk on a
24/7 kiosk — wear + corruption) to the attached USB SATA SSD (`sda`, Goodram 120GB via an
OWC UAS adapter). Faster I/O + a far more durable 24/7 boot medium. Pi 5 supports USB boot.

## Green light
`sda` currently holds a **disposable Windows mining-rig OS** (`Windows/`, `Program Files/`,
`pagefile.sys`; mining shortcuts). Verified: **no crypto wallet keystore** (Coinomi/Exodus/
Electrum/Bitcoin/Ledger — none) and **no personal documents** (only empty Windows default
templates). User authorized reformat.

## Preconditions / facts
- Pi 5, Debian 13 (trixie); root now `mmcblk0p2` ext4 (7.7G/59G used). EEPROM `BOOT_ORDER=0xf41` (SD→USB).
- `sda`: 111.8G, NTFS ×3 partitions (will be wiped). UAS adapter works at runtime; **USB-boot compatibility of this OWC adapter must be confirmed** (some UAS bridges fail at the bootloader stage even if they work in-OS).
- Config lives in git-ignored files that MUST survive: `~/dvri-peek/cameras.yaml`, `secrets.local.yaml`, `state.local.json`, the `go2rtc` binary + `go2rtc.generated.yaml`. (Cloning preserves them; a fresh flash needs them restored.)

## Approach (recommended: live clone SD→SSD)
Clone the whole working system (incl. the 24/7 hardening, service, kiosk, config) SD→SSD, then
boot the SSD with SD as fallback. Preferred over a fresh flash (no reconfiguration).

## Steps
1. **Backup first** (belt-and-suspenders): copy the git-ignored config off-device
   (`scp alwi@pi:~/dvri-peek/{cameras.yaml,secrets.local.yaml,state.local.json} ./pi-backup/`),
   and note `go2rtc` is re-downloadable.
2. **Confirm SSD USB-boot capability** before committing: `sudo rpi-eeprom-config` (bootloader
   recent), and ideally test the adapter boots at all. If the adapter won't boot, STOP (keep SD root; use the SSD only for data/logs — a lesser win).
3. **Install rpi-clone** (`sudo apt install -y rpi-clone` or the github script).
4. **Clone SD → sda** (repartitions/wipes `sda` — the green-lit Windows data): `sudo rpi-clone sda -f`.
   Confirms + creates a bootable ext4 root + fat boot on the SSD.
5. **Set boot order to prefer USB, fall back to SD**: `sudo rpi-eeprom-config --edit` → `BOOT_ORDER=0xf14` (USB→SD→repeat). SD stays as automatic fallback if the SSD is absent/unbootable.
6. **Reboot; verify from the SSD**: `findmnt -n -o SOURCE /` → `/dev/sda2`; `systemctl is-active dvri-peek`; previews 4/4; kiosk up; WiFi/hardening intact (governor, power-save off).
7. **Enable periodic fstrim** for the SSD (`sudo systemctl enable fstrim.timer`).
8. Update `.meta/raspi-setup.md` (root now on SSD; SD is fallback) + note in README if relevant.

## Rollback
- Boot order `0xf14` auto-falls-back to the SD if the SSD fails → the Pi still boots the old SD system.
- Physically removing the SSD → boots SD. Keep the SD in place.

## Execution note
Boot-device changes can drop SSH (if the SSD fails to boot). **Run this with the user physically
at the Pi** (or a keyboard/console available) for recovery. Not a remote-only op.
