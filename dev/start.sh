#!/usr/bin/env bash
# Start the musical-radio-station mock Spotify server.
# Uses Podman if available; falls back to the project venv.
#
# Requires WSL2 mirrored networking so the server is reachable from LAN devices:
#   Add  networkingMode=mirrored  under [wsl2] in %USERPROFILE%\.wslconfig
#   then run  wsl --shutdown  and reopen.
#
# Usage:
#   dev/start.sh [PORT]
#   PORT defaults to 5000.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-5000}"

_win_ip() {
    powershell.exe -Command \
        "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { \$_.IPAddress -notlike '127.*' -and \$_.IPAddress -notlike '172.*' } | Sort-Object PrefixLength -Descending | Select-Object -First 1).IPAddress" \
        2>/dev/null | tr -d '\r'
}

_allow_inbound() {
    # Add a Windows Firewall rule so LAN devices (e.g. ESP32) can reach the
    # mock server. Silently skips if powershell.exe is unavailable.
    powershell.exe -Command "
        \$rule = Get-NetFirewallRule -DisplayName 'musical-radio-station' -ErrorAction SilentlyContinue
        if (-not \$rule) {
            New-NetFirewallRule -DisplayName 'musical-radio-station' \`
                -Direction Inbound -Action Allow -Protocol TCP -LocalPort $PORT | Out-Null
            Write-Host 'Firewall: added inbound rule for port $PORT'
        }
    " 2>/dev/null || true
}

_print_urls() {
    local host
    host=$(_win_ip)
    echo ""
    echo "musical-radio-station running on port $PORT"
    echo "  LAN address (for device):  $host:$PORT"
    echo ""
    echo "  Load playlist:  curl -X PUT \"http://localhost:$PORT/control/playlist?name=americana_hits\""
    echo "  Fast-forward:   curl -X POST http://localhost:$PORT/control/fast-forward"
    echo "  Status:         curl http://localhost:$PORT/control/status"
    echo "  Playlists:      curl http://localhost:$PORT/control/playlists"
}

if command -v podman &>/dev/null; then
    IMAGE="musical-radio-station"
    CONTAINER="musical-radio-station"
    if ! podman image exists "$IMAGE" 2>/dev/null; then
        echo "Building $IMAGE image..."
        podman build -t "$IMAGE" "$REPO_ROOT/src/musical-radio-station"
    fi
    podman rm -f "$CONTAINER" 2>/dev/null || true
    podman run -d \
        --name "$CONTAINER" \
        -p "0.0.0.0:${PORT}:5000" \
        -v "$REPO_ROOT/src/musical-radio-station/playlists:/app/playlists:ro,z" \
        "$IMAGE"
    _allow_inbound
    _print_urls

elif [[ -f "$REPO_ROOT/.venv/bin/python" ]]; then
    VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
    "$VENV_PYTHON" -m pip install -q flask
    LOG=/tmp/musical-radio-station.log
    PID=/tmp/musical-radio-station.pid
    "$VENV_PYTHON" "$REPO_ROOT/src/musical-radio-station/app.py" >"$LOG" 2>&1 &
    echo $! >"$PID"
    sleep 1
    _allow_inbound
    _print_urls
    echo "  Log: tail -f $LOG"

else
    echo "ERROR: neither Podman nor .venv found." >&2
    exit 1
fi
