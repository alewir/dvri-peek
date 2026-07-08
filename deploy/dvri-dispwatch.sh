#!/bin/sh
# dvri-peek display watchdog — recover a frozen Wayland/vc4 display.
# The Pi 5 vc4 GPU can wedge under Chromium and freeze the WHOLE display (the compositor
# stops presenting frames) while the system, network, and camera streams stay healthy — so
# the systemd hardware watchdog never fires and it needs a manual kiosk restart. Detection
# (validated during the incident): a wlr-screencopy of a single pixel returns instantly on a
# healthy compositor but BLOCKS on a wedged one. On two consecutive timeouts, restart the
# kiosk browser — labwc's lwrespawn relaunches kiosk.sh. Runs as root (system timer); probes
# as the graphical-session user. GPU stays on (software render saturated the CPU).
up=$(cut -d. -f1 /proc/uptime); [ "$up" -lt 180 ] && exit 0   # boot grace

KUSER=$(ps -o user= -C labwc 2>/dev/null | head -1 | tr -d ' ')
[ -z "$KUSER" ] && exit 0
KUID=$(id -u "$KUSER" 2>/dev/null) || exit 0
WD=$(ls "/run/user/$KUID/" 2>/dev/null | grep -E '^wayland-[0-9]+$' | head -1)
[ -z "$WD" ] && exit 0
STATE=/run/dvri-dispwatch.fails

if timeout 8 runuser -u "$KUSER" -- env "XDG_RUNTIME_DIR=/run/user/$KUID" "WAYLAND_DISPLAY=$WD" \
     grim -g "0,0 1x1" /tmp/.dispprobe.png >/dev/null 2>&1; then
  rm -f "$STATE"                       # display live → reset
  exit 0
fi

N=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$N" > "$STATE"
logger -t dvri-dispwatch "display screencopy probe failed ($N/2)"
if [ "$N" -ge 2 ]; then               # ~2 consecutive misses → wedged, not a transient
  logger -t dvri-dispwatch "display frozen — restarting kiosk browser"
  rm -f "$STATE"
  pkill chromium
fi
exit 0
