#!/usr/bin/env bash
# Print the device's current IP address.
# Tries mDNS first; falls back to Windows ARP table by MAC address.
#
# Usage:
#   dev/find-device.sh          → prints IP or exits 1 with a message
#   IP=$(dev/find-device.sh)    → capture for use in other scripts
set -euo pipefail

DEVICE_HOSTNAME="musical-mood-ring.local"
DEVICE_MAC="b0-a6-04-06-8b-24"

# mDNS
if ip=$(ping -c 1 -W 1 "$DEVICE_HOSTNAME" 2>/dev/null \
        | grep -oP '(?<=\()[\d.]+(?=\))' | head -1) && [[ -n "$ip" ]]; then
    echo "$ip"
    exit 0
fi

# ARP fallback (Windows ARP table via powershell.exe)
if ip=$(powershell.exe -Command "arp -a" 2>/dev/null \
        | grep -i "$DEVICE_MAC" | grep -oP '[\d]+\.[\d]+\.[\d]+\.[\d]+' | head -1) \
        && [[ -n "$ip" ]]; then
    echo "$ip"
    exit 0
fi

echo "Device not found (mDNS and ARP both failed). Is it on the network?" >&2
exit 1
