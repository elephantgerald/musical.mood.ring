#!/usr/bin/env bash
# tests/hardware/verify_introspection.sh — on-device check for #58's endpoints
#
# Host-side hardware-in-loop verification: curls the four read-only
# introspection endpoints on a running board and asserts the contract the
# unit tests can only mock — valid JSON, application/json, the redaction on
# /config, and the expected shapes. Turns issue #58's "Manual verification on
# real device" acceptance criterion into an objective pass/fail.
#
# Prerequisite: firmware deployed to a board that is on WiFi (STA mode), e.g.
#   ./build/deploy.sh --chip esp32c3 --firmware-only
#
# Usage:
#   ./tests/hardware/verify_introspection.sh [host]
#   ./tests/hardware/verify_introspection.sh 10.0.0.42   # if mDNS won't resolve
#   HOST=musical-mood-ring.local ./tests/hardware/verify_introspection.sh
#
# Exit code 0 = all checks passed; non-zero = at least one failed.

set -uo pipefail   # not -e: we want to run every check and tally, not abort early

HOST="${1:-${HOST:-musical-mood-ring.local}}"
BASE="http://${HOST}"
PASS=0
FAIL=0

# Resolve a python3 for JSON assertions (prefer the project venv if present).
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO_ROOT/.venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
    echo "FATAL: python3 not found (needed for JSON assertions)." >&2
    exit 2
fi

say()  { printf '%s\n' "$*"; }
ok()   { PASS=$((PASS+1)); printf '  \033[32mPASS\033[0m  %s\n' "$*"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m  %s\n' "$*"; }

# fetch PATH -> sets $code $ctype $ttime and writes the body to $BODY
BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT
fetch() {
    local meta
    meta="$(curl -s -o "$BODY" -w '%{http_code} %{content_type} %{time_total}' \
                 --max-time 8 "${BASE}$1" 2>/dev/null || echo '000 none 0')"
    code="${meta%% *}"; meta="${meta#* }"
    ctype="${meta%% *}"; ttime="${meta##* }"
}

# ── Reachability ─────────────────────────────────────────────────────────────
say "Verifying introspection endpoints on ${BASE}"
fetch "/state"
if [ "$code" = "000" ]; then
    echo "FATAL: ${BASE} unreachable. Is the board powered, on WiFi, and is" >&2
    echo "       mDNS resolving? Retry with the device IP: $0 <ip>" >&2
    exit 2
fi

# ── Per-endpoint contract checks (delegated to python for JSON parsing) ──────
check() {
    local ep="$1" path="$2"
    fetch "$path"
    if "$PY" - "$ep" "$BODY" "$code" "$ctype" <<'PY'
import sys, json
ep, body_path, code, ctype = sys.argv[1:5]
fails = []
if code != "200":
    fails.append(f"expected HTTP 200, got {code}")
if "application/json" not in (ctype or ""):
    fails.append(f"Content-Type not application/json (got {ctype!r})")
try:
    data = json.load(open(body_path))
except Exception as e:
    fails.append(f"body is not valid JSON: {e}")
    data = None

if data is not None and not fails:
    if ep == "state":
        need = {"engine", "animator", "error_mode",
                "wifi_connected", "uptime_ms", "free_mem"}
        missing = need - set(data)
        if missing:
            fails.append(f"/state missing keys: {sorted(missing)}")
    elif ep == "pixels":
        for k in ("pixels", "source_ve"):
            if k not in data:
                fails.append(f"/pixels missing {k}")
            elif not isinstance(data[k], list) or len(data[k]) != 3:
                fails.append(f"/pixels {k} should be a 3-element list")
    elif ep == "poll-log":
        if not isinstance(data, list):
            fails.append("/poll-log should be a JSON array")
        elif len(data) > 3:
            fails.append(f"/poll-log?n=3 returned {len(data)} records (>3)")
    elif ep == "config":
        for s in ("wifi_password", "spotify_client_secret", "spotify_refresh_token"):
            if data.get(s) not in ("***", ""):
                fails.append(f"/config {s}={data.get(s)!r} is NOT redacted")
        for p in ("wifi_ssid", "spotify_client_id"):
            if p not in data:
                fails.append(f"/config missing {p}")
if fails:
    print("; ".join(fails))
    sys.exit(1)
sys.exit(0)
PY
    then
        ok "GET ${path}  (${ctype}, ${ttime}s)"
    else
        bad "GET ${path}  (HTTP ${code})"
    fi
}

check state    "/state"
check pixels   "/pixels"
check poll-log "/poll-log?n=3"
check config   "/config"

# ── Negative case: malformed ?n= must be rejected (IMP-2), not silently full ──
fetch "/poll-log?n=ten"
if [ "$code" = "400" ]; then
    ok "GET /poll-log?n=ten  → 400 (rejects bad cap)"
else
    bad "GET /poll-log?n=ten  → expected 400, got ${code}"
fi

# ── Secret leak scan: no obvious credential material in any response ──────────
# Best-effort defense-in-depth on top of /config's field check above.
leak=0
for path in /state /pixels "/poll-log" /config; do
    fetch "$path"
    if grep -qiE 'BQ[A-Za-z0-9_-]{20,}|refresh_token"[: ]*"[^"*]{8,}' "$BODY"; then
        bad "possible secret material in ${path}"
        leak=1
    fi
done
[ "$leak" = 0 ] && ok "no credential material found in any response body"

# ── Summary ──────────────────────────────────────────────────────────────────
say ""
say "Result: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ] || exit 1
say "All #58 on-device acceptance checks passed."
