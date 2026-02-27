# Spotify App Registration

This document captures the exact steps needed to register a Spotify developer app
for musical.mood.ring. There are a few gotchas that are easy to get wrong.

---

## What you need and why

The device uses the **Authorization Code Flow** to get a refresh token. That token
is saved to flash and used at runtime to fetch recently-played tracks. You need:

- A Spotify developer app (free, takes ~2 minutes to create)
- The app's `client_id` and `client_secret`
- The device on your local network so it can handle the OAuth callback

**You do not need Spotify Premium.** The `recently-played` endpoint works on free
accounts.

---

## 1. Create the app

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
   and log in with your Spotify account.
2. Click **Create app**.
3. Fill in the fields:
   - **App name**: anything — `musical-mood-ring` works
   - **App description**: anything
   - **Redirect URIs**: `http://musical-mood-ring.local/callback` — **exact, no
     trailing slash**. This must match what the device sends during the OAuth flow.
   - **Which API/SDKs are you planning to use?**: tick **Web API**
4. Accept the terms and click **Save**.

---

## 2. Add yourself as a user (development mode)

New apps are in **development mode** by default and can only be used by accounts
explicitly added as users. If you skip this, the OAuth flow will fail with a
permission error.

1. In your app's dashboard, go to **User Management**.
2. Add the Spotify account email you actually listen with.

You can add up to 25 users in development mode. Applying for extended quota is
not needed for personal use.

---

## 3. Get client_id and client_secret

From the app's dashboard, click **Settings**. You'll find both values there. Copy
them — you'll paste them into the device's setup page.

---

## 4. Configure the device

After the device connects to WiFi (M2 setup), it brings up a web server on
`http://musical-mood-ring.local`. Visit it in a browser on the same network:

1. Enter **Client ID** and **Client Secret** → click **Save & Continue**.
2. Click **Authorize with Spotify**.
3. Spotify redirects to its own login/approval page — approve.
4. Spotify sends the browser back to `http://musical-mood-ring.local/callback`
   with an authorization code. The device exchanges it for a refresh token,
   saves it to flash, and starts the main loop.

If the redirect fails (browser says "site can't be reached"), the device's mDNS
advertisement hasn't propagated yet — wait a few seconds and try
`http://musical-mood-ring.local/callback` again, or use the device's IP address
directly.

---

## 5. Scope

The device requests exactly one scope: `user-read-recently-played`. It does not
request write permissions or access to private data.

---

## Known Spotify API limitations

### `/v1/audio-features` is permanently blocked

Spotify blocked this endpoint for all apps registered after 27 November 2024. It
is still documented but returns HTTP 403 with no path to re-enable it for
individual developers (the quota extension process was tightened in April 2025).

This is why the project uses an offline pipeline (MusicBrainz → AcousticBrainz →
Last.fm → zone anchor) to pre-compute `(valence, energy)` values and compile them
into a binary bundle that is flashed to the device. Do not attempt to call
`/v1/audio-features` at runtime.

### `/v1/playlists/{id}/tracks` returns 403

Also confirmed blocked for this app registration, cause unknown. Not on Spotify's
deprecated endpoints list. The pipeline does not use playlist tracks at runtime;
track IDs are collected offline via `src/musical-cultivator/`.

### `/v1/me/player/recently-played` works

This is the only Spotify endpoint called at runtime. It is unaffected by the
above restrictions.
