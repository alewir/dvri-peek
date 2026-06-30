#!/usr/bin/env bash
# Launch the RTSP live preview web grid.
# The venv lives on the native Linux filesystem (~/.venvs/rtsp) because pip on the
# /mnt/e Windows DrvFs mount is pathologically slow. Project code stays on /mnt/e.
set -e
cd "$(dirname "$0")"
# Find a usable venv: $RTSP_VENV, then ./.venv, then ~/.venvs/{dvri-peek,rtsp}
VENV=""
for cand in "${RTSP_VENV:-}" .venv "$HOME/.venvs/dvri-peek" "$HOME/.venvs/rtsp"; do
  [ -n "$cand" ] && [ -x "$cand/bin/python" ] && { VENV="$cand"; break; }
done
if [ -z "$VENV" ]; then
  echo "venv not found — create it with:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi
PY="$VENV/bin/python"
if [ ! -x ./go2rtc ]; then
  echo "go2rtc binary missing — download with:" >&2
  echo "  curl -L -o go2rtc https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_linux_amd64 && chmod +x go2rtc" >&2
  exit 1
fi
exec "$PY" player.py "$@"
