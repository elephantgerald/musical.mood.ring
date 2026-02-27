# Developer Setup

Everything you need to get the pipeline running and the firmware flashing.

---

## Python environment

One virtualenv covers the pipeline, the calibration notebook, and the unit tests:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

All scripts resolve `data/` paths by walking up to the `.git` root, so they work
from any working directory with the venv active.

---

## External service credentials

### Spotify (pipeline + device)

Two separate uses:

| Use | Where | Keys needed |
|-----|-------|-------------|
| Pipeline Stage 1 (`mine_playlists.py`, `import_urls.py`, `fetch_metadata.py`) | `src/musical-cultivator/.env` | `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` |
| Device runtime (OAuth, recently-played polling) | Entered via the device's setup UI; saved to ESP32 flash | same `client_id` and `client_secret` |

The app registration is non-trivial — see
[`docs/SPOTIFY-APP-REGISTRATION.md`](SPOTIFY-APP-REGISTRATION.md) for the exact
steps, including the redirect URI, user allowlist, and the audio-features
endpoint caveat.

`src/musical-cultivator/.env.example` shows the required keys.

### Last.fm (pipeline Stage 3)

1. Create a free account at [last.fm](https://www.last.fm) if you don't have one.
2. Request an API key at
   [last.fm/api/account/create](https://www.last.fm/api/account/create).
   Fill in any app name and description.
3. Copy the **API key** (not the shared secret — that is not needed).

```
# src/musical-mash-bill/.env
LASTFM_API_KEY=your_key_here
```

`src/musical-mash-bill/.env.example` shows the required format.

### MusicBrainz (pipeline Stage 1 + 2)

No API key required. The enrich script sets a `User-Agent` header automatically.
MusicBrainz enforces a **1 request/second** rate limit; the script respects this.

### AcousticBrainz (pipeline Stage 2)

No API key required. Note that AcousticBrainz stopped accepting new submissions
in 2022. The enrichment script queries the existing archive for
mood/BPM features. Tracks not present in the archive fall through to Last.fm or
zone-anchor fallback in the distiller.

---

## Flashing the ESP32 (WSL2 + Adafruit HUZZAH32)

One-time prerequisites:

```bash
sudo apt install linux-tools-generic hwdata
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE="0666", GROUP="dialout"' \
    | sudo tee /etc/udev/rules.d/99-esp32.rules
sudo udevadm control --reload-rules
```

Ensure `/etc/wsl.conf` contains:
```ini
[boot]
systemd=true
```

To erase and reflash MicroPython:

```bash
./build/reset.sh          # auto-activates .venv; prompts for usbipd if board not found
./build/reset.sh --help   # full usage
```

To deploy firmware files to an already-flashed board, use `mpremote` (installed
by `requirements.txt`).

---

## Calibration notebook

```bash
source .venv/bin/activate
jupyter notebook src/mood-model/m0_calibration.ipynb
```

Run all cells, review the plots, edit the Final Parameters cell, then run the
Export cell. Output goes to `data/synaesthesia/synaesthesia-{name}.json`.
Flash this file to the device alongside the MMAR bundle.
