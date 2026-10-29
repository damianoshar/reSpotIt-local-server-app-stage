"""
spotify_albums.py  (Docker edition)
-------------------------------------
Fetches all saved albums from your Spotify library and saves them to a CSV.

In Docker mode the script can't open a browser, so it prints the auth URL
and waits. Visit the URL on your host machine — the callback is forwarded
to the container via the exposed port 8888.

Env vars (set in .env or docker-compose.yml):
  SPOTIFY_CLIENT_ID
  SPOTIFY_CLIENT_SECRET
  REDIRECT_URI          (default: http://127.0.0.1:8888/callback)
  OUTPUT_CSV            (default: /data/spotify_albums.csv)
  DELAY_SECONDS         (default: 0.5)
"""

import csv
import os
import time
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import requests

# ── Config ────────────────────────────────────────────────────────────────────
CLIENT_ID     = os.environ["SPOTIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
REDIRECT_URI  = os.getenv("REDIRECT_URI", "http://127.0.0.1:8000/auth/callback")
9bffcb3889
ify_albums.csv")
DELAY_SECONDS = float(os.getenv("DELAY_SECONDS", "0.5"))
TOKEN_FILE    = "/data/.spotify_token.json"  # persisted on the mounted volume
PAGE_LIMIT    = 50
# ──────────────────────────────────────────────────────────────────────────────


# ── OAuth helpers ─────────────────────────────────────────────────────────────

_auth_code = None

class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _auth_code = params["code"][0]
            body = b"<h2>Auth complete! You can close this tab and check the terminal.</h2>"
        else:
            body = b"<h2>Auth failed - check the terminal for details.</h2>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # silence default request logs


def _get_auth_code():
    params = {
        "client_id":     CLIENT_ID,
        "response_type": "code",
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPE,
    }
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)

    print("\n" + "─" * 60)
    print("  OPEN THIS URL IN YOUR BROWSER TO AUTHORIZE:")
    print(f"\n  {url}\n")
    print("  Waiting for the OAuth callback on port 8888 …")
    print("─" * 60 + "\n")

    # Bind to 0.0.0.0 so the callback reaches the container from the host
    server = HTTPServer(("0.0.0.0", 8888), _CallbackHandler)
    server.handle_request()
    return _auth_code


def _exchange_code(code):
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  REDIRECT_URI,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )
    resp.raise_for_status()
    return resp.json()


def _refresh_token(refresh_tok):
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_tok,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data["access_token"], data.get("refresh_token", refresh_tok)


def get_access_token():
    """Returns a valid access token, refreshing from cache when possible."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            tok = json.load(f)
        try:
            access, refresh = _refresh_token(tok["refresh_token"])
            tok["access_token"]  = access
            tok["refresh_token"] = refresh
            with open(TOKEN_FILE, "w") as f:
                json.dump(tok, f)
            print("✓ Token refreshed from cache — skipping browser auth.")
            return access
        except Exception as e:
            print(f"Token refresh failed ({e}), starting full auth flow.")

    code = _get_auth_code()
    if not code:
        raise RuntimeError("Did not receive auth code from Spotify.")
    tok = _exchange_code(code)
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tok, f)
    print("✓ Authorized and token cached.")
    return tok["access_token"]


# ── Fetching ──────────────────────────────────────────────────────────────────

def fetch_all_saved_albums(access_token):
    albums  = []
    url     = "https://api.spotify.com/v1/me/albums"
    params  = {"limit": PAGE_LIMIT, "offset": 0}
    headers = {"Authorization": f"Bearer {access_token}"}

    print("\nFetching saved albums ...\n")
    page = 0
    while url:
        page += 1
        resp = requests.get(url, headers=headers, params=params)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            print(f"\n  Rate limited -- waiting {retry_after}s ...")
            time.sleep(retry_after)
            continue

        resp.raise_for_status()
        data  = resp.json()
        items = data.get("items", [])
        total = data.get("total", 0) or 0

        for item in items:
            album = item.get("album", {})
            albums.append({
                "added_at":     item.get("added_at", ""),
                "album_id":     album.get("id", ""),
                "name":         album.get("name", ""),
                "artists":      ", ".join(a["name"] for a in album.get("artists", [])),
                "release_date": album.get("release_date", ""),
                "total_tracks": album.get("total_tracks", ""),
                "album_type":   album.get("album_type", ""),
                "label":        album.get("label", ""),
                "popularity":   album.get("popularity", ""),
                "genres":       ", ".join(album.get("genres", [])),
                "spotify_url":  album.get("external_urls", {}).get("spotify", ""),
                "image_url":    album["images"][0]["url"] if album.get("images") else "",
            })

        fetched = len(albums)
        pct     = int(fetched / total * 100) if total else 0
        filled  = pct // 5                        # 20-char wide bar (1 block = 5%)
        bar     = "#" * filled + "-" * (20 - filled)
        last    = albums[-1]["name"][:35].ljust(35) if albums else ""
        print(f"  [{bar}] {pct:3d}%  {fetched:>4}/{total}  page {page}  |  {last}", flush=True)

        url    = data.get("next")
        params = {}
        if url:
            time.sleep(DELAY_SECONDS)

    print()
    return albums


# ── CSV export ────────────────────────────────────────────────────────────────

FIELDS = [
    "added_at", "name", "artists", "release_date",
    "total_tracks", "album_type", "label", "popularity",
    "genres", "album_id", "spotify_url", "image_url",
]

def save_to_csv(albums, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(albums)
    print(f"✓ Saved {len(albums)} albums → {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("── Spotify Library Exporter ──────────────────────────────")
    token  = get_access_token()
    albums = fetch_all_saved_albums(token)

    if not albums:
        print("No saved albums found in your library.")
        return

    save_to_csv(albums, OUTPUT_CSV)
    print(f"\n✓ Done! {len(albums)} albums exported.")
    print(f"  Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Output    : {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
