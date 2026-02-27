#!/usr/bin/env python3
"""
import_misses.py

Pulls the miss log from a running musical-mood-ring device and imports any
novel track IDs into the gestalt pipeline as a new batch file.

How it works:
  1. Fetch the miss log (newline-separated Spotify track IDs) from the device
  2. Deduplicate against all track IDs already present in data/musical-gestalt/
  3. Write data/musical-gestalt/miss_imports_YYYYMMDD_HHMMSS.json with novel IDs
  4. Optionally clear the device miss log after a successful import (--clear)

After running, continue with the normal pipeline:
  python src/musical-cultivator/scripts/fetch_metadata.py --file miss_imports_*.json
  python src/musical-mash-bill/scripts/enrich_features.py  --file miss_imports_*.json --phase all
  python src/musical-distiller/distill.py
  python src/musical-bottler/bottle.py

Usage:
    # Pull from live device (default — requires device on local network):
    python import_misses.py [--host musical-mood-ring.local] [--clear]

    # Import from a previously-saved file:
    python import_misses.py --file /path/to/misses.txt [--clear]

    # Import from stdin (e.g. piped from curl):
    curl http://musical-mood-ring.local/misses | python import_misses.py --stdin [--clear]

Options:
    --host HOST    Device hostname or IP (default: musical-mood-ring.local)
    --file PATH    Read miss log from a local file instead of fetching from device
    --stdin        Read miss log from stdin instead of fetching from device
    --clear        After importing, wipe the device miss log via mpremote
    --port PORT    Device serial port for --clear (default: /dev/ttyUSB0)
    --dry-run      Show what would be imported without writing anything
"""

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_from_device(host: str) -> list[str]:
    """HTTP GET /misses from the device. Returns raw lines."""
    url = f"http://{host}/misses"
    print(f"Fetching {url} …")
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        print(f"ERROR: could not reach device: {exc}")
        sys.exit(1)
    return body.splitlines()


def read_lines(path: Path) -> list[str]:
    """Read newline-separated track IDs from a local file."""
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Deduplicate
# ---------------------------------------------------------------------------

def known_track_ids(gestalt_dir: Path) -> set[str]:
    """Collect every track ID already present across all gestalt JSONs."""
    known: set[str] = set()
    for path in gestalt_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        known.update(data.get("track_ids", []))
        # Also cover IDs only in metadata keys (partial imports)
        known.update(data.get("metadata", {}).keys())
    return known


def parse_track_ids(lines: list[str]) -> list[str]:
    """
    Extract valid Spotify track IDs (22-char alphanumeric) from raw lines.
    Strips whitespace; ignores blanks and obviously invalid entries.
    """
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        tid = line.strip()
        if not tid:
            continue
        # Spotify IDs are Base62 strings — roughly 22 chars, no slashes/dots
        if len(tid) < 10 or "/" in tid or "." in tid:
            continue
        if tid not in seen:
            seen.add(tid)
            result.append(tid)
    return result


# ---------------------------------------------------------------------------
# Clear device log
# ---------------------------------------------------------------------------

def clear_device_log(port: str) -> None:
    """Wipe the miss log on the device via mpremote exec."""
    cmd = [
        "mpremote", "connect", port,
        "exec", "import miss_log; miss_log.clear()",
    ]
    print(f"Clearing device miss log on {port} …")
    try:
        subprocess.run(cmd, check=True, timeout=30)
        print("  ✓ Device miss log cleared.")
    except FileNotFoundError:
        print("  WARNING: mpremote not found — device miss log not cleared.")
        print("           Run: pip install mpremote")
    except subprocess.CalledProcessError as exc:
        print(f"  WARNING: mpremote returned non-zero ({exc.returncode}) — log may not be cleared.")
    except subprocess.TimeoutExpired:
        print("  WARNING: mpremote timed out — device miss log not cleared.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Import device miss log into the gestalt enrichment pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--file", metavar="PATH",
        help="Read miss log from a local file instead of the device",
    )
    source.add_argument(
        "--stdin", action="store_true",
        help="Read miss log from stdin",
    )
    parser.add_argument(
        "--host", default="musical-mood-ring.local",
        help="Device hostname or IP (default: musical-mood-ring.local)",
    )
    parser.add_argument(
        "--clear", action="store_true",
        help="Wipe device miss log after a successful import (requires mpremote)",
    )
    parser.add_argument(
        "--port", default="/dev/ttyUSB0",
        help="Serial port for --clear (default: /dev/ttyUSB0)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be imported without writing anything",
    )
    args = parser.parse_args()

    root        = project_root()
    gestalt_dir = root / "data" / "musical-gestalt"

    if not gestalt_dir.exists():
        print(f"ERROR: gestalt directory not found: {gestalt_dir}")
        sys.exit(1)

    # ── Fetch raw lines ────────────────────────────────────────────────────────
    if args.file:
        lines = read_lines(Path(args.file))
    elif args.stdin:
        lines = sys.stdin.read().splitlines()
    else:
        lines = fetch_from_device(args.host)

    if not lines:
        print("Miss log is empty — nothing to import.")
        return

    # ── Parse + deduplicate ────────────────────────────────────────────────────
    raw_ids = parse_track_ids(lines)
    if not raw_ids:
        print("No valid track IDs found in miss log.")
        return

    print(f"  {len(raw_ids)} track IDs in miss log")

    known = known_track_ids(gestalt_dir)
    novel = [tid for tid in raw_ids if tid not in known]

    print(f"  {len(known)} already in gestalt — {len(novel)} novel")

    if not novel:
        print("All tracks already in the pipeline. Nothing to import.")
        if args.clear and not args.dry_run:
            clear_device_log(args.port)
        return

    # ── Write gestalt batch ────────────────────────────────────────────────────
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_name  = f"miss_imports_{timestamp}.json"
    out_path  = gestalt_dir / out_name

    record = {
        "playlist":    f"miss_imports_{timestamp}",
        "split":       "training",
        "track_count": len(novel),
        "track_ids":   novel,
    }

    if args.dry_run:
        print()
        print(f"  [dry-run] would write {out_path}")
        print(f"  [dry-run] {len(novel)} novel track IDs")
        return

    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    print()
    print(f"  ✓ {len(novel)} novel track IDs saved")
    print(f"    → {out_path}")
    print()
    print("  Next steps:")
    print(f"    python src/musical-cultivator/scripts/fetch_metadata.py --file {out_name}")
    print(f"    python src/musical-mash-bill/scripts/enrich_features.py  --file {out_name} --phase all")
    print( "    python src/musical-distiller/distill.py")
    print( "    python src/musical-bottler/bottle.py")

    if args.clear:
        print()
        clear_device_log(args.port)


if __name__ == "__main__":
    main()
