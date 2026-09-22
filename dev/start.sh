#!/usr/bin/env bash
# Start the musical-radio-station mock Spotify server.
# Uses Podman if available; falls back to the project venv.
#
# Requires WSL2 mirrored networking so the server is reachable from LAN devices:
#   Add  networkingMode=mirrored  under [wsl2] in %USERPROFILE%\.wslconfig
#   then run  wsl --shutdown  and reopen.
#
# Under mirrored networking, inbound traffic to WSL is governed by the Hyper-V
# firewall, NOT by the ordinary Windows Firewall — and its default inbound
# action is Block. A plain New-NetFirewallRule therefore changes nothing, which
# is how the mock+real-board quadrant came to look "untested" rather than
# "unreachable". Both rules need Administrator, so this script does not assume
# either worked: it probes the LAN address from the Windows side and reports
# what it actually finds.
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

# WSL's Hyper-V firewall VM id. Looked up live, because it is per-install in
# principle; this constant is the fallback every WSL2 install has used so far.
WSL_VM_ID_DEFAULT='{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'

_wsl_vm_id() {
    local id
    id=$(powershell.exe -NoProfile -Command \
        "(Get-NetFirewallHyperVVMSetting -PolicyStore ActiveStore -ErrorAction SilentlyContinue | Select-Object -First 1).Name" \
        2>/dev/null | tr -d '\r' | tr -d ' ')
    echo "${id:-$WSL_VM_ID_DEFAULT}"
}

_hyperv_rule_cmd() {
    # The command the user must run elevated. Printed verbatim when we are
    # blocked, so it can be pasted without reconstruction.
    printf 'New-NetFirewallHyperVRule -Name "musical-radio-station" -DisplayName "musical-radio-station" -Direction Inbound -VMCreatorId "%s" -Protocol TCP -LocalPorts %s -Action Allow' \
        "$(_wsl_vm_id)" "$PORT"
}

_allow_inbound() {
    # Try to open the port. Both calls need Administrator and both are
    # no-ops without it — so nothing here is treated as proof of anything.
    # _check_reachable below is what actually decides.
    powershell.exe -NoProfile -Command "
        if (-not (Get-NetFirewallRule -DisplayName 'musical-radio-station' -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName 'musical-radio-station' \`
                -Direction Inbound -Action Allow -Protocol TCP -LocalPort $PORT -ErrorAction SilentlyContinue | Out-Null
        }
        if (-not (Get-NetFirewallHyperVRule -Name 'musical-radio-station' -ErrorAction SilentlyContinue)) {
            New-NetFirewallHyperVRule -Name 'musical-radio-station' -DisplayName 'musical-radio-station' \`
                -Direction Inbound -VMCreatorId '$(_wsl_vm_id)' -Protocol TCP -LocalPorts $PORT \`
                -Action Allow -ErrorAction SilentlyContinue | Out-Null
        }
    " >/dev/null 2>&1 || true
}

_check_reachable() {
    # Ask Windows to reach the LAN address the device will use. If the host
    # cannot reach its own LAN IP on this port, no device on the LAN can
    # either — so this is the check that matters, not whether a rule exists.
    local host="$1"
    [[ -n "$host" ]] || return 1
    powershell.exe -NoProfile -Command \
        "try { \$r = curl.exe -s --max-time 4 http://${host}:${PORT}/control/status; if (\$r) { exit 0 } else { exit 1 } } catch { exit 1 }" \
        >/dev/null 2>&1
}

_print_urls() {
    local host
    host=$(_win_ip)
    echo ""
    echo "musical-radio-station running on port $PORT"
    if _check_reachable "$host"; then
        echo "  LAN address (for device):  $host:$PORT   [reachable]"
    else
        echo "  LAN address (for device):  $host:$PORT   ** NOT REACHABLE **"
        echo ""
        echo "  Windows cannot reach that address, so neither can the board."
        echo "  Under mirrored networking the Hyper-V firewall blocks inbound by"
        echo "  default. Run this in an ELEVATED PowerShell, then re-run this script:"
        echo ""
        echo "    $(_hyperv_rule_cmd)"
        echo ""
        echo "  (localhost still works, so dev/fake_board.py is unaffected.)"
    fi
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
