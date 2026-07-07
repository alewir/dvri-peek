#!/bin/bash
# ============================================================================
#  dvri-peek — Raspberry Pi kiosk installer (portable)
#  Run on the Pi from the cloned repo:   bash deploy/setup-pi.sh
#
#  Sets up: apt deps, arch-correct go2rtc, a systemd service for the player,
#  a labwc kiosk autostart, screen-blanking off, SD-card-sparing settings
#  (Chromium profile/cache in RAM, journald capped), and 24/7 no-powersave
#  hardening (WiFi power-save off + infinite reconnect, USB autosuspend off,
#  suspend/sleep masked, CPU performance governor).
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
  chromium curl git \
  fonts-noto-color-emoji     # weather + UI emoji glyphs (else they render as tofu boxes)

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

# --- 7) 24/7 no-powersave hardening (WiFi/USB/suspend) + CPU performance -------
echo ">> applying 24/7 no-powersave hardening..."
# WiFi: disable radio power-save globally (portable, no connection-name dependency)
sudo mkdir -p /etc/NetworkManager/conf.d
printf "[connection]\nwifi.powersave = 2\n" | \
  sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf >/dev/null
# + never give up reconnecting on the active WiFi connection
WCON="$(nmcli -t -f NAME,TYPE connection show 2>/dev/null | awk -F: '/wireless/{print $1; exit}')"
[ -n "$WCON" ] && sudo nmcli connection modify "$WCON" \
  802-11-wireless.powersave 2 connection.autoconnect-retries 0 2>/dev/null || true
# USB autosuspend off (keeps an attached SSD / peripherals from spinning down/dropping)
printf 'ACTION=="add", SUBSYSTEM=="usb", TEST=="power/control", ATTR{power/control}="on"\n' | \
  sudo tee /etc/udev/rules.d/50-usb-no-autosuspend.rules >/dev/null
echo -1 | sudo tee /sys/module/usbcore/parameters/autosuspend >/dev/null 2>&1 || true
# never suspend/sleep/hibernate (a kiosk stays on)
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null 2>&1 || true
# CPU performance governor (lossless/consistent stream decode), persistent across reboots
printf '#!/bin/sh\nfor g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > "$g"; done\n' | \
  sudo tee /usr/local/bin/cpu-performance.sh >/dev/null
sudo chmod +x /usr/local/bin/cpu-performance.sh
printf '[Unit]\nDescription=Force CPU performance governor (24/7 kiosk)\n[Service]\nType=oneshot\nExecStart=/usr/local/bin/cpu-performance.sh\n[Install]\nWantedBy=multi-user.target\n' | \
  sudo tee /etc/systemd/system/cpu-performance.service >/dev/null
sudo systemctl daemon-reload && sudo systemctl enable --now cpu-performance.service >/dev/null 2>&1 || true

# --- 8) USB-SSD reliability: disable UAS on a USB root adapter (prevents hard hangs) ---
CMDLINE=/boot/firmware/cmdline.txt
ROOT_SRC="$(findmnt -n -o SOURCE / 2>/dev/null || true)"
case "$ROOT_SRC" in
  /dev/sd*)
    if [ -f "$CMDLINE" ] && ! grep -q "usb-storage.quirks=" "$CMDLINE"; then
      VID="$(udevadm info -q property -n "$ROOT_SRC" 2>/dev/null | sed -n 's/^ID_VENDOR_ID=//p')"
      PID="$(udevadm info -q property -n "$ROOT_SRC" 2>/dev/null | sed -n 's/^ID_MODEL_ID=//p')"
      if [ -n "$VID" ] && [ -n "$PID" ]; then
        sudo sed -i "1 s|\$| usb-storage.quirks=${VID}:${PID}:u|" "$CMDLINE"
        echo ">> disabled UAS for USB root adapter ${VID}:${PID} (reboot to apply)"
      fi
    fi ;;
esac

echo ">> done. Service: $(systemctl is-active dvri-peek.service). Reboot to start the kiosk:  sudo reboot"
