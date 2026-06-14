#!/usr/bin/env bash
# Configure a running device to use the musical-radio-station mock Spotify server.
#
# Finds the device automatically (mDNS / ARP), then POSTs:
#   - spotify_mock_host  → points firmware at the mock server
#   - spotify_refresh_token → fake token (mock server accepts anything)
#
# Usage:
#   dev/setup-device.sh [--mock-host HOST:PORT] [--device-ip IP]
#
#   --mock-host   IP:port of the mock server (default: auto-detect Windows LAN IP + 5000)
#   --device-ip   skip discovery, use this IP directly
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MOCK_HOST=""
DEVICE_IP=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mock-host)  MOCK_HOST="$2";  shift 2 ;;
        --device-ip)  DEVICE_IP="$2";  shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

# Detect device IP
if [[ -z "$DEVICE_IP" ]]; then
    echo "Locating device..."
    DEVICE_IP=$("$SCRIPT_DIR/find-device.sh")
    echo "Found device at $DEVICE_IP"
fi

# Detect mock server host (Windows LAN IP : 5000)
if [[ -z "$MOCK_HOST" ]]; then
    WIN_IP=$(powershell.exe -Command \
        "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { \$_.IPAddress -notlike '127.*' -and \$_.IPAddress -notlike '172.*' } | Sort-Object PrefixLength -Descending | Select-Object -First 1).IPAddress" \
        2>/dev/null | tr -d '\r')
    if [[ -z "$WIN_IP" ]]; then
        echo "ERROR: Could not detect Windows LAN IP. Pass --mock-host HOST:PORT explicitly." >&2
        exit 1
    fi
    MOCK_HOST="${WIN_IP}:5000"
    echo "Mock host: $MOCK_HOST"
fi

_curl() {
    powershell.exe -Command "curl.exe $*" 2>&1 | grep -v "^  % Total" | grep -v "^  0 " || true
}

echo ""
echo "Configuring $DEVICE_IP..."

_curl "-s -X POST http://$DEVICE_IP/config \
    -d 'spotify_mock_host=$MOCK_HOST' \
    -H 'Content-Type: application/x-www-form-urlencoded'"

_curl "-s -X POST http://$DEVICE_IP/spotify/token \
    -d 'refresh_token=mock' \
    -H 'Content-Type: application/x-www-form-urlencoded'"

echo ""
echo "Done. Device is configured to poll $MOCK_HOST."
echo "Load a playlist: curl -X PUT \"http://localhost:5000/control/playlist?name=americana_hits\""
