#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
XVFB_WHD="${XVFB_WHD:-1440x960x24}"

Xvfb "$DISPLAY" -screen 0 "$XVFB_WHD" -ac +extension GLX +render -noreset &
XVFB_PID="$!"

cleanup() {
  kill "$XVFB_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

exec gunicorn app:app --bind "0.0.0.0:${PORT:-10000}" --workers 1 --threads 4 --timeout 180
