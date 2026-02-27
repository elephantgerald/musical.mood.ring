#!/usr/bin/env bash
# build/deploy.sh — Deploy firmware and data bundles to the ESP32
#
# Copies all MicroPython firmware files, the latest MMAR bundles, and the
# synaesthesia profile to the connected board, then resets it.
#
# Usage:
#   ./build/deploy.sh [options]
#
# Options:
#   --firmware-only   Copy .py files only; skip bundles and synaesthesia profile
#   --bundles-only    Copy bundles and synaesthesia profile only; skip .py files
#   --no-reset        Do not reset the board after deploying
#   --help            Show this message

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT=/dev/ttyUSB0
FIRMWARE_SRC="$REPO_ROOT/src/musical-mood-ring"
BUNDLE_DIR="$REPO_ROOT/data/musical-memory-bundle"
SYNTH_DIR="$REPO_ROOT/data/synaesthesia"

DO_FIRMWARE=true
DO_BUNDLES=true
DO_RESET=true

# ── Help ───────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: ./build/deploy.sh [--firmware-only] [--bundles-only] [--no-reset]"
    echo ""
    echo "Deploys to the ESP32 at $PORT."
    echo ""
    echo "What it copies:"
    echo "  Firmware  : all .py files from src/musical-mood-ring/"
    echo "  Bundles   : latest memory-bundle-v1-*.bin → /memory-bundle.bin"
    echo "              latest artist-bundle-v1-*.bin → /artist-bundle.bin (if present)"
    echo "  Profile   : synaesthesia-*.json → /synaesthesia.json (if present)"
    echo ""
    echo "After copying, resets the board unless --no-reset is passed."
    echo ""
    echo "Run ./build/reset.sh first if the board needs MicroPython reflashed."
    exit 0
fi

for arg in "$@"; do
    case "$arg" in
        --firmware-only) DO_BUNDLES=false ;;
        --bundles-only)  DO_FIRMWARE=false ;;
        --no-reset)      DO_RESET=false ;;
        *) echo "Unknown option: $arg  (try --help)"; exit 1 ;;
    esac
done

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

# ── Prerequisite check ─────────────────────────────────────────────────────
if ! command -v mpremote &>/dev/null; then
    echo "ERROR: mpremote not found. Run: pip install mpremote"
    exit 1
fi

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
        exit 1
    fi
fi

echo "Board found at $PORT."
echo ""

# ── Deploy firmware (.py files) ────────────────────────────────────────────
if $DO_FIRMWARE; then
    echo "Deploying firmware…"
    count=0
    for f in "$FIRMWARE_SRC"/*.py; do
        name="$(basename "$f")"
        printf "  %-30s" "$name"
        mpremote connect "$PORT" cp "$f" ":/$name"
        echo "✓"
        count=$((count + 1))
    done
    echo "  $count files copied."
    echo ""
fi

# ── Deploy bundles + synaesthesia profile ──────────────────────────────────
if $DO_BUNDLES; then
    echo "Deploying bundles…"

    TRACK_BUNDLE=$(ls "$BUNDLE_DIR"/memory-bundle-v1-*.bin 2>/dev/null | sort | tail -1 || true)
    if [ -n "$TRACK_BUNDLE" ]; then
        printf "  %-30s" "memory-bundle.bin"
        mpremote connect "$PORT" cp "$TRACK_BUNDLE" ":/memory-bundle.bin"
        echo "✓  ($(basename "$TRACK_BUNDLE"))"
    else
        echo "  memory-bundle.bin       — not found (run bottle.py first)"
    fi

    ARTIST_BUNDLE=$(ls "$BUNDLE_DIR"/artist-bundle-v1-*.bin 2>/dev/null | sort | tail -1 || true)
    if [ -n "$ARTIST_BUNDLE" ]; then
        printf "  %-30s" "artist-bundle.bin"
        mpremote connect "$PORT" cp "$ARTIST_BUNDLE" ":/artist-bundle.bin"
        echo "✓  ($(basename "$ARTIST_BUNDLE"))"
    else
        echo "  artist-bundle.bin       — not present (optional; run fetch_artist_ids.py + bottle.py)"
    fi

    SYNTH=$(ls "$SYNTH_DIR"/synaesthesia-*.json 2>/dev/null | head -1 || true)
    if [ -n "$SYNTH" ]; then
        printf "  %-30s" "synaesthesia.json"
        mpremote connect "$PORT" cp "$SYNTH" ":/synaesthesia.json"
        echo "✓  ($(basename "$SYNTH"))"
    else
        echo "  synaesthesia.json       — not present (device uses built-in defaults)"
    fi

    echo ""
fi

# ── Reset ──────────────────────────────────────────────────────────────────
if $DO_RESET; then
    echo "Resetting board…"
    mpremote connect "$PORT" reset
    echo "Done. Board is running."
else
    echo "Skipping reset (--no-reset)."
fi
