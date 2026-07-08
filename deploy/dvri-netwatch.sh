#!/bin/sh
# dvri-peek network watchdog — reboot if the LAN gateway is unreachable for ~5 minutes.
# Rationale: on the Pi 5 the on-board BCM43455 (brcmfmac) WiFi can wedge into a state where
# only a reboot recovers — driver reload / NetworkManager restart fail (see raspberrypi/linux
# #3849, openwrt #23069). A sustained-loss reboot is the one reliable software recovery, and it
# also covers any wired-Ethernet drop. Ping the GATEWAY (local) so an internet-only outage
# never triggers a reboot. Run every 60s by dvri-netwatch.timer.
set -u

# grace period: never act in the first 5 min after boot (network still coming up)
up=$(cut -d. -f1 /proc/uptime)
[ "$up" -lt 300 ] && exit 0

STATE=/run/dvri-netwatch.fails
set -- $(ip route show default 2>/dev/null)
GW=${3:-}

if [ -n "$GW" ] && ping -c 2 -W 3 "$GW" >/dev/null 2>&1; then
  rm -f "$STATE"                      # healthy → reset the failure counter
  exit 0
fi

N=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$N" > "$STATE"
logger -t dvri-netwatch "gateway [${GW:-none}] unreachable (fail $N/5)"

if [ "$N" -ge 5 ]; then               # ~5 consecutive 60s checks → sustained outage
  logger -t dvri-netwatch "network down ${N}x — rebooting to recover"
  rm -f "$STATE"
  systemctl reboot
fi
exit 0
