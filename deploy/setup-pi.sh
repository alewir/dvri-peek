#!/bin/bash
# ============================================================================
#  dvri-peek — Raspberry Pi kiosk installer (portable)
#  Run on the Pi from the cloned repo:   bash deploy/setup-pi.sh
#
#  Sets up: apt deps, arch-correct go2rtc, a systemd service for the player,
#  a labwc kiosk autostart, screen-blanking off, and SD-card-sparing settings
#  (Chromium profile/cache in RAM, journald capped).
#  Assumes Raspberry Pi OS (desktop) with autologin already enabled
#  (raspi-config -> System Options -> Boot/Auto Login -> Desktop Autologin).
# ============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"      # repo root
USER_NAME="$(id -un)"
echo ">> dvri-peek install for user '$USER_NAME' from '$DIR'"

# --- 1) system packages (apt = reliable on aarch64/armhf, no pip builds) -----
echo ">> installing apt dependencies..."
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3-opencv python3-flask python3-numpy python3-yaml \
  chromium curl git

# --- 2) go2rtc binary for this CPU architecture ------------------------------
if [ ! -x "$DIR/go2rtc" ]; then
  case "$(uname -m)" in
    aarch64|arm64) GOARCH=arm64 ;;
    armv7l|armhf)  GOARCH=arm ;;
    x86_64|amd64)  GOARCH=amd64 ;;
    *) echo "!! unknown arch $(uname -m); set go2rtc manually"; GOARCH=arm64 ;;
  esac
  echo ">> downloading go2rtc ($GOARCH)..."
  curl -fsSL -o "$DIR/go2rtc" \
    "https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_linux_${GOARCH}"
  chmod +x "$DIR/go2rtc"
fi

# --- 3) config ---------------------------------------------------------------
if [ ! -f "$DIR/cameras.yaml" ]; then
  cp "$DIR/cameras.example.yaml" "$DIR/cameras.yaml"
  echo "!! created cameras.yaml from template — EDIT it with your cameras/credentials, then re-run or restart the service."
fi
chmod +x "$DIR/kiosk.sh"

# --- 4) systemd service (player auto-starts at boot, restarts on failure) ----
echo ">> installing systemd service..."
sed -e "s#__USER__#$USER_NAME#g" -e "s#__DIR__#$DIR#g" \
  "$DIR/deploy/dvri-peek.service" | sudo tee /etc/systemd/system/dvri-peek.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now dvri-peek.service

# --- 5) kiosk autostart (labwc). Keeps desktop defaults + adds the kiosk. -----
echo ">> configuring labwc kiosk autostart..."
mkdir -p "$HOME/.config/labwc"
AUTO="$HOME/.config/labwc/autostart"
if [ ! -f "$AUTO" ]; then
  # seed from the system default so the panel/desktop still load
  cp /etc/xdg/labwc/autostart "$AUTO" 2>/dev/null || true
fi
LINE="/usr/bin/lwrespawn $DIR/kiosk.sh &"
grep -qF "$DIR/kiosk.sh" "$AUTO" 2>/dev/null || echo "$LINE" >> "$AUTO"

# --- 6) SD-card protection + screen blanking ---------------------------------
echo ">> disabling screen blanking + capping journald..."
sudo raspi-config nonint do_blanking 1 2>/dev/null || true
sudo mkdir -p /etc/systemd/journald.conf.d
printf "[Journal]\nSystemMaxUse=50M\nRuntimeMaxUse=50M\n" | \
  sudo tee /etc/systemd/journald.conf.d/cap.conf >/dev/null
sudo systemctl restart systemd-journald || true

echo ">> done. Service: $(systemctl is-active dvri-peek.service). Reboot to start the kiosk:  sudo reboot"
