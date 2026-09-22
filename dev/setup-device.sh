#!/usr/bin/env bash
# Point a device at the musical-radio-station mock Spotify server.
#
# Writes spotify_mock_host into the device's config.json OVER SERIAL, because
# there is deliberately no HTTP write path for it. SPOTIFY_MOCK_HOST swaps
# Spotify's HTTPS endpoints for a plain-HTTP mock, so OAuth tokens would travel
# in cleartext; spotify.py honours the override only for loopback/RFC1918
# targets AND only from flashed config.json (see _mock_host_ok). An earlier
# version of this script POSTed it to /config — a route that does not exist,
# and must not, so the write failed silently.
#
# config.save() on-device MERGES, so seeding the mock host before first boot
# survives the AP-mode WiFi write. The normal order is:
#
#   1. ./build/reset.sh --chip esp32c3          erase + flash MicroPython
#   2. ./build/deploy.sh --chip esp32c3 --no-reset   firmware + bundles
#   3. dev/setup-device.sh                      this script — seed mock host
#   4. reset the board; with no wifi_ssid it comes up in AP mode
#   5. join the "musical.mood.ring" AP, enter WiFi credentials
#   6. dev/start.sh, then load a playlist
#
# Usage:
#   dev/setup-device.sh [--mock-host HOST:PORT] [--port /dev/ttyACM0]
#                       [--token VALUE] [--show]
#
#   --mock-host   IP:port of the mock (default: auto-detect Windows LAN IP:5000)
#   --port        serial device (default: /dev/ttyACM0)
#   --token       refresh token to seed (default: "mock"; the mock accepts any)
#   --show        print the device's current config.json and exit
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MPREMOTE="$REPO_ROOT/.venv/bin/mpremote"
[[ -x "$MPREMOTE" ]] || MPREMOTE="mpremote"

MOCK_HOST=""
PORT="/dev/ttyACM0"
TOKEN="mock"
SHOW_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mock-host) MOCK_HOST="$2"; shift 2 ;;
        --port)      PORT="$2";      shift 2 ;;
        --token)     TOKEN="$2";     shift 2 ;;
        --show)      SHOW_ONLY=1;    shift ;;
        -h|--help)   sed -n '2,29p' "$0"; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

if [[ ! -e "$PORT" ]]; then
    echo "ERROR: $PORT not found." >&2
    echo "  On WSL2, attach the board first:  usbipd.exe attach --wsl --busid <id>" >&2
    exit 1
fi

# Two very different failures look identical from mpremote, so separate them.
if command -v fuser >/dev/null 2>&1; then
    HOLDER="$(fuser "$PORT" 2>/dev/null | tr -d ' ' || true)"
    if [[ -n "$HOLDER" ]]; then
        echo "ERROR: $PORT is already open by PID $HOLDER" \
             "($(ps -o comm= -p "$HOLDER" 2>/dev/null || echo unknown))." >&2
        echo "  Close that session and retry — the board itself is probably fine." >&2
        exit 1
    fi
fi

if ! "$MPREMOTE" connect "$PORT" exec "pass" >/dev/null 2>&1; then
    echo "ERROR: cannot reach the MicroPython REPL on $PORT." >&2
    echo "  If the board is running firmware with the network stack up, the" >&2
    echo "  serial interrupt cannot break through it. Run ./build/reset.sh first." >&2
    exit 1
fi

if [[ "$SHOW_ONLY" == "1" ]]; then
    "$MPREMOTE" connect "$PORT" exec "
import json
try:
    cfg = json.load(open('config.json'))
except OSError:
    print('config.json: absent')
else:
    for k in sorted(cfg):
        v = cfg[k]
        if 'password' in k or 'token' in k or 'secret' in k:
            v = '<set, {} chars>'.format(len(str(v)))
        print('  {:<24} {}'.format(k, v))
"
    exit 0
fi

# Detect the mock server host (Windows LAN IP : 5000)
if [[ -z "$MOCK_HOST" ]]; then
    WIN_IP=$(powershell.exe -Command \
        "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { \$_.IPAddress -notlike '127.*' -and \$_.IPAddress -notlike '172.*' } | Sort-Object PrefixLength -Descending | Select-Object -First 1).IPAddress" \
        2>/dev/null | tr -d '\r')
    if [[ -z "$WIN_IP" ]]; then
        echo "ERROR: could not detect the Windows LAN IP. Pass --mock-host HOST:PORT." >&2
        exit 1
    fi
    MOCK_HOST="${WIN_IP}:5000"
fi

# Mirror spotify.py's _mock_host_ok locally, so a bad value fails here with a
# clear message instead of silently falling back to real HTTPS Spotify on boot.
HOST_ONLY="${MOCK_HOST%%:*}"
if ! [[ "$HOST_ONLY" == "localhost" \
     || "$HOST_ONLY" == 127.* \
     || "$HOST_ONLY" == 10.* \
     || "$HOST_ONLY" == 192.168.* \
     || "$HOST_ONLY" =~ ^172\.(1[6-9]|2[0-9]|3[01])\. ]]; then
    echo "ERROR: $HOST_ONLY is not loopback or RFC1918." >&2
    echo "  The firmware would ignore it and use real Spotify over HTTPS." >&2
    exit 1
fi

echo "Device : $PORT"
echo "Mock   : $MOCK_HOST"
echo ""

"$MPREMOTE" connect "$PORT" exec "
import json
try:
    cfg = json.load(open('config.json'))
except OSError:
    cfg = {}
cfg['spotify_mock_host']     = '$MOCK_HOST'
cfg['spotify_refresh_token'] = '$TOKEN'
with open('config.json', 'w') as f:
    json.dump(cfg, f)
print('config.json written. Keys now present:')
for k in sorted(cfg):
    print('  ' + k)
if 'wifi_ssid' not in cfg:
    print('')
    print('No wifi_ssid yet — on next reset the device comes up in AP mode.')
    print('Join \"musical.mood.ring\" and enter credentials; the mock host')
    print('survives that write because config.save() merges.')
"

echo ""
echo "Next:"
echo "  dev/start.sh"
echo "  curl -X PUT \"http://localhost:5000/control/playlist?name=americana_hits\""
