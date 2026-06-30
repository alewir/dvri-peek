#!/bin/bash
# dvri-peek kiosk launcher (Wayland / labwc).
# Waits for the player to be serving, then opens Chromium fullscreen.
# Chromium's profile + cache live in /dev/shm (RAM tmpfs) so a 24/7 kiosk does
# NOT wear out the SD card. Profile is recreated each boot (fine for a kiosk).
set -u
URL="${DVRIPEEK_URL:-http://localhost:8090}"
PROFILE="${DVRIPEEK_CHROME_PROFILE:-/dev/shm/chromium-kiosk}"

# wait (up to ~90s) for the player service to answer
for _ in $(seq 1 90); do
  curl -sf -m2 -o /dev/null "$URL" && break
  sleep 1
done

rm -rf "$PROFILE"; mkdir -p "$PROFILE/cache"

# chromium vs chromium-browser depending on distro
CHROME="$(command -v chromium || command -v chromium-browser)"

exec "$CHROME" \
  --ozone-platform=wayland \
  --kiosk "$URL" \
  --user-data-dir="$PROFILE" \
  --disk-cache-dir="$PROFILE/cache" --disk-cache-size=33554432 \
  --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
  --disable-features=Translate --no-first-run --password-store=basic \
  --check-for-update-interval=604800 --overscroll-history-navigation=0
