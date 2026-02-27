#!/usr/bin/env bash
# build/reset.sh — Erase and reflash the HUZZAH32 with the latest MicroPython
#
# Usage:
#   ./build/reset.sh
#
# First-time WSL2 setup (one-off, already done if you followed the guide):
#   sudo apt install linux-tools-generic hwdata
#   echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE="0666", GROUP="dialout"' \
#       | sudo tee /etc/udev/rules.d/99-esp32.rules
#   sudo udevadm control --reload-rules && sudo udevadm trigger
#   # Add [boot] systemd=true to /etc/wsl.conf and run: wsl --shutdown

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHIP=esp32
PORT=/dev/ttyUSB0
FIRMWARE_DIR="$REPO_ROOT/build/firmware"

# ── Help ──────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: ./build/reset.sh [--help]"
    echo ""
    echo "Erases and reflashes the HUZZAH32 ESP32 with the latest stable MicroPython."
    echo ""
    echo "What it does:"
    echo "  1. Activates .venv and checks prerequisites (esptool, mpremote, curl)"
    echo "  2. Detects the board at $PORT — prompts for usbipd attach if not found"
    echo "  3. Fetches the latest MicroPython release from GitHub; downloads if not cached"
    echo "  4. Erases flash and writes the firmware"
    echo "  5. Verifies the board responds with the expected MicroPython version"
    echo ""
    echo "Firmware cache: build/firmware/  (gitignored)"
    echo ""
    echo "First-time WSL2 setup: see comments at the top of this file."
    exit 0
fi

# ── Activate .venv ─────────────────────────────────────────────────────────
VENV="$REPO_ROOT/.venv"
if [ -z "${VIRTUAL_ENV:-}" ] || [ "$VIRTUAL_ENV" != "$VENV" ]; then
    if [ ! -f "$VENV/bin/activate" ]; then
        echo "ERROR: .venv not found at $VENV"
        echo "       Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
        exit 1
    fi
    source "$VENV/bin/activate"
fi

# ── Prerequisite checks ────────────────────────────────────────────────────
check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        echo "ERROR: '$1' not found."
        case "$1" in
            esptool|mpremote) echo "       Run: pip install $1" ;;
            curl)             echo "       Run: sudo apt install curl" ;;
        esac
        exit 1
    fi
}
check_cmd esptool
check_cmd mpremote
check_cmd curl
check_cmd python3

# ── Board detection ────────────────────────────────────────────────────────
sudo modprobe cp210x 2>/dev/null || true

if [ ! -e "$PORT" ]; then
    echo ""
    echo "  ESP32 not found at $PORT."
    echo ""
    echo "  Attach the board from an Administrator PowerShell on Windows:"
    echo ""
    echo "    usbipd list"
    echo "    usbipd attach --wsl --busid <BUSID>   # look for CP210x / Silicon Labs"
    echo ""
    printf "  Press Enter once attached... "
    read -r
    echo "  Waiting for device to appear..."
    for _ in $(seq 1 15); do
        [ -e "$PORT" ] && break
        sleep 1
    done
    if [ ! -e "$PORT" ]; then
        echo ""
        echo "ERROR: $PORT still not found after 15 seconds."
        echo "       Check that usbipd attached successfully and the CP210x driver is loaded."
        exit 1
    fi
fi

echo "Board found at $PORT."

# ── MicroPython version check ──────────────────────────────────────────────
echo "Checking latest MicroPython release..."
LATEST_TAG=$(curl -s https://api.github.com/repos/micropython/micropython/releases/latest \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['tag_name'])")
LATEST_VERSION="${LATEST_TAG#v}"
echo "Latest stable: v${LATEST_VERSION}"

mkdir -p "$FIRMWARE_DIR"
FIRMWARE=$(ls "$FIRMWARE_DIR"/ESP32_GENERIC-*-v${LATEST_VERSION}.bin 2>/dev/null | head -1 || true)

if [ -n "$FIRMWARE" ]; then
    echo "Cached firmware: $(basename "$FIRMWARE")"
else
    echo "Downloading MicroPython v${LATEST_VERSION}..."
    DOWNLOAD_PATH=$(curl -s https://micropython.org/download/ESP32_GENERIC/ \
        | grep -o 'href="[^"]*ESP32_GENERIC[^"]*v'"${LATEST_VERSION}"'[^"]*\.bin"' \
        | grep -v preview \
        | head -1 \
        | sed 's/href="//;s/"//')

    if [ -z "$DOWNLOAD_PATH" ]; then
        echo "ERROR: Could not find download URL for v${LATEST_VERSION} on micropython.org"
        exit 1
    fi

    FILENAME=$(basename "$DOWNLOAD_PATH")
    curl -L --progress-bar -o "$FIRMWARE_DIR/$FILENAME" "https://micropython.org${DOWNLOAD_PATH}"
    FIRMWARE="$FIRMWARE_DIR/$FILENAME"
    echo "Downloaded: $FILENAME"
fi

# ── Flash ──────────────────────────────────────────────────────────────────
echo ""
echo "Erasing flash..."
esptool --chip "$CHIP" --port "$PORT" erase-flash

echo "Flashing $(basename "$FIRMWARE")..."
esptool --chip "$CHIP" --port "$PORT" --baud 460800 write-flash -z 0x1000 "$FIRMWARE"

# ── Verify ─────────────────────────────────────────────────────────────────
echo ""
echo "Verifying..."
sleep 2
mpremote connect "$PORT" exec "import sys; print('OK —', sys.version)"

echo ""
echo "Done. Board is ready."
