#!/usr/bin/env bash
# Stop the musical-radio-station mock Spotify server.
set -euo pipefail

PID=/tmp/musical-radio-station.pid

podman rm -f musical-radio-station 2>/dev/null || true

if [[ -f "$PID" ]]; then
    kill "$(cat "$PID")" 2>/dev/null || true
    rm -f "$PID"
fi

echo "Stopped."
