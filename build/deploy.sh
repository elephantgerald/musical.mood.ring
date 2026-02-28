#!/usr/bin/env bash
# build/deploy.sh — Deploy firmware to the ESP32
#
# Usage:
#   ./build/deploy.sh [options]
#
# Options:
#   --project mood.ring   Full mood ring firmware + data bundles (default)
#   --project twinkle     Twinkle hardware test (overwrites boot.py + main.py)
#   --firmware-only       mood.ring only: copy .py files, skip bundles
#   --no-reset            Do not reset the board after deploying
#   --help                Show this message
#
# To redeploy when the board is stuck running mood ring firmware:
#   run ./build/reset.sh first (reflashes MicroPython, ~1 min), then deploy.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT=/dev/ttyUSB0
FIRMWARE_SRC="$REPO_ROOT/src/musical-mood-ring"
BUNDLE_DIR="$REPO_ROOT/data/musical-memory-bundle"
SYNTH_DIR="$REPO_ROOT/data/synaesthesia"

PROJECT=mood.ring
DO_FIRMWARE=true
DO_BUNDLES=true
DO_RESET=true

# ── Parse arguments ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            echo "Usage: ./build/deploy.sh [options]"
            echo ""
            echo "  --project mood.ring   Full mood ring: .py firmware + bundles (default)"
            echo "  --project twinkle     Hardware test: test_boot.py + twinkle_test.py"
            echo "  --firmware-only       mood.ring only: .py files only, skip bundles"
            echo "  --bundles-only        mood.ring only: bundles only, skip .py files"
            echo "  --no-reset            Skip board reset after deploying"
            echo ""
            echo "Deploys to the ESP32 at $PORT."
            echo "Run ./build/reset.sh first if the board is stuck or needs MicroPython reflashed."
            exit 0
            ;;
        --project)
            shift
            PROJECT="${1:-}"
            if [[ "$PROJECT" != "mood.ring" && "$PROJECT" != "twinkle" ]]; then
                echo "Unknown project: $PROJECT  (choose mood.ring or twinkle)"
                exit 1
            fi
            ;;
        --firmware-only)
            DO_BUNDLES=false
            ;;
        --bundles-only)
            DO_FIRMWARE=false
            ;;
        --no-reset)
            DO_RESET=false
            ;;
        *)
            echo "Unknown option: $1  (try --help)"
            exit 1
            ;;
    esac
    shift
done

# ── Activate .venv ───────────────────────────────────────────────────────────
VENV="$REPO_ROOT/.venv"
if [ -z "${VIRTUAL_ENV:-}" ] || [ "$VIRTUAL_ENV" != "$VENV" ]; then
    if [ ! -f "$VENV/bin/activate" ]; then
        echo "ERROR: .venv not found at $VENV"
        echo "       Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
        exit 1
    fi
    source "$VENV/bin/activate"
fi

# ── Prerequisite check ───────────────────────────────────────────────────────
if ! command -v mpremote &>/dev/null; then
    echo "ERROR: mpremote not found. Run: pip install mpremote"
    exit 1
fi

# ── Board detection ──────────────────────────────────────────────────────────
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
        exit 1
    fi
fi

echo "Board found at $PORT."
echo ""

# ── Build the mpremote command ───────────────────────────────────────────────
#
# All copies run in one session (mpremote connect PORT cp a + cp b + …)
# so the raw-REPL handshake happens only once — more reliable over WSL2/usbipd.

copy_cmd=(mpremote connect "$PORT")
copy_count=0

if [[ "$PROJECT" == "twinkle" ]]; then
    echo "Project: twinkle (hardware test)"
    echo "  test_boot.py  → /boot.py"
    echo "  twinkle_test.py → /main.py"
    echo ""
    copy_cmd+=(cp "$REPO_ROOT/tests/hardware/test_boot.py"    ":/boot.py")
    copy_cmd+=(+ cp "$REPO_ROOT/tests/hardware/twinkle_test.py" ":/main.py")
    copy_count=2

else
    echo "Project: mood.ring"

    if $DO_FIRMWARE; then
        echo "Firmware (.py files from src/musical-mood-ring/):"
        for f in "$FIRMWARE_SRC"/*.py; do
            name="$(basename "$f")"
            echo "  $name"
            [ $copy_count -gt 0 ] && copy_cmd+=(+)
            copy_cmd+=(cp "$f" ":/$name")
            copy_count=$((copy_count + 1))
        done
        echo ""
    fi

    if $DO_BUNDLES; then
        echo "Bundles:"

        TRACK_BUNDLE=$(ls "$BUNDLE_DIR"/memory-bundle-v1-*.bin 2>/dev/null | sort | tail -1 || true)
        if [ -n "$TRACK_BUNDLE" ]; then
            echo "  memory-bundle.bin  ($(basename "$TRACK_BUNDLE"))"
            [ $copy_count -gt 0 ] && copy_cmd+=(+)
            copy_cmd+=(cp "$TRACK_BUNDLE" ":/memory-bundle.bin")
            copy_count=$((copy_count + 1))
        else
            echo "  memory-bundle.bin  — not found (run bottle.py first)"
        fi

        ARTIST_BUNDLE=$(ls "$BUNDLE_DIR"/artist-bundle-v1-*.bin 2>/dev/null | sort | tail -1 || true)
        if [ -n "$ARTIST_BUNDLE" ]; then
            echo "  artist-bundle.bin  ($(basename "$ARTIST_BUNDLE"))"
            [ $copy_count -gt 0 ] && copy_cmd+=(+)
            copy_cmd+=(cp "$ARTIST_BUNDLE" ":/artist-bundle.bin")
            copy_count=$((copy_count + 1))
        else
            echo "  artist-bundle.bin  — not present (optional)"
        fi

        SYNTH=$(ls "$SYNTH_DIR"/synaesthesia-*.json 2>/dev/null | head -1 || true)
        if [ -n "$SYNTH" ]; then
            echo "  synaesthesia.json  ($(basename "$SYNTH"))"
            [ $copy_count -gt 0 ] && copy_cmd+=(+)
            copy_cmd+=(cp "$SYNTH" ":/synaesthesia.json")
            copy_count=$((copy_count + 1))
        else
            echo "  synaesthesia.json  — not present (device uses built-in defaults)"
        fi

        echo ""
    fi
fi

# ── Copy ─────────────────────────────────────────────────────────────────────
if [ $copy_count -gt 0 ]; then
    echo "Copying $copy_count file(s)…"
    "${copy_cmd[@]}"   # fail loudly — a TransportError means the board is not ready
    echo "  ✓ done"
    echo ""
fi

# ── Reset via RTS pin toggle (no raw REPL needed — works regardless of what's running) ──
if $DO_RESET; then
    python3 -c "
import serial, time
with serial.Serial('$PORT', 115200) as s:
    s.dtr = False; s.rts = True;  time.sleep(0.1)
    s.dtr = False; s.rts = False
"
    echo "  ✓ board reset"
fi

echo "Done."
