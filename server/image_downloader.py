"""
image_downloader.py
--------------------
Reads spotify_albums.csv, downloads each album cover from image_url,
and writes the local filename into an image_file column in the CSV.

Env vars:
  INPUT_CSV      (default: /data/spotify_albums.csv)
  OUTPUT_CSV     (default: same as INPUT_CSV — updates in place)
  IMAGES_DIR     (default: /data/images)
  DELAY_SECONDS  (default: 0.3)
  MAX_RETRIES    (default: 3)
"""

import csv
import os
import re
import time
import sys
import requests
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────
INPUT_CSV     = os.getenv("INPUT_CSV",  "/data/spotify_albums.csv")
OUTPUT_CSV    = os.getenv("OUTPUT_CSV", INPUT_CSV)
IMAGES_DIR    = os.getenv("IMAGES_DIR", "/data/images")
DELAY_SECONDS = float(os.getenv("DELAY_SECONDS", "0.3"))
MAX_RETRIES   = int(os.getenv("MAX_RETRIES", "3"))
# ───────────────────────────────────────────────────────────────────────────

HEADERS = {"User-Agent": "spotify-album-art-downloader/1.0"}


def safe_filename(album_id: str, url: str) -> str:
    """Derive a safe filename from the album_id + url extension."""
    ext = os.path.splitext(url.split("?")[0])[-1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", album_id) + ext


def download_image(url: str, dest: str) -> bool:
    """Download url to dest. Returns True on success."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15, stream=True)
            if resp.status_code == 200:
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
            else:
                print(f"    HTTP {resp.status_code} (attempt {attempt}/{MAX_RETRIES})")
        except requests.RequestException as e:
            print(f"    Error: {e} (attempt {attempt}/{MAX_RETRIES})")
        if attempt < MAX_RETRIES:
            time.sleep(2 ** attempt)   # exponential back-off: 2s, 4s
    return False


def bar(done: int, total: int, width: int = 20) -> str:
    pct    = int(done / total * 100) if total else 0
    filled = pct // (100 // width)
    return f"[{'#' * filled}{'-' * (width - filled)}] {pct:3d}%  {done}/{total}"


def main():
    print("-- Album Art Downloader ------------------------------------------")

    # ── Validate input ──────────────────────────────────────────────────────
    if not os.path.exists(INPUT_CSV):
        print(f"ERROR: CSV not found at {INPUT_CSV}")
        print("       Make sure the spotify-exporter container has run first.")
        sys.exit(1)

    os.makedirs(IMAGES_DIR, exist_ok=True)

    # ── Read CSV ────────────────────────────────────────────────────────────
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader  = csv.DictReader(f)
        rows    = list(reader)
        in_fields = reader.fieldnames or []

    if not rows:
        print("CSV is empty — nothing to do.")
        sys.exit(0)

    out_fields = in_fields if "image_file" in in_fields else in_fields + ["image_file"]

    total   = len(rows)
    done    = 0
    skipped = 0
    failed  = 0

    print(f"\n  Input  : {INPUT_CSV}  ({total} albums)")
    print(f"  Images : {IMAGES_DIR}")
    print(f"  Output : {OUTPUT_CSV}\n")

    # ── Process rows ────────────────────────────────────────────────────────
    for i, row in enumerate(rows, 1):
        name      = row.get("name", "?")[:40]
        album_id  = row.get("album_id", f"row_{i}")
        image_url = row.get("image_url", "").strip()

        # Already downloaded in a previous run
        existing = row.get("image_file", "").strip()
        if existing and os.path.exists(os.path.join(IMAGES_DIR, existing)):
            skipped += 1
            done    += 1
            print(f"  {bar(i, total)}  SKIP  {name}", flush=True)
            continue

        if not image_url:
            row["image_file"] = ""
            failed += 1
            done   += 1
            print(f"  {bar(i, total)}  NO URL  {name}", flush=True)
            continue

        filename = safe_filename(album_id, image_url)
        dest     = os.path.join(IMAGES_DIR, filename)

        success = download_image(image_url, dest)

        if success:
            row["image_file"] = filename
            done += 1
            print(f"  {bar(i, total)}  OK    {name}", flush=True)
        else:
            row["image_file"] = ""
            failed += 1
            done   += 1
            print(f"  {bar(i, total)}  FAIL  {name}", flush=True)

        time.sleep(DELAY_SECONDS)

    # ── Write updated CSV ───────────────────────────────────────────────────
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(rows)

    ok = total - failed - skipped
    print(f"""
-- Done ----------------------------------------------------------
  Timestamp  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  Total      : {total}
  Downloaded : {ok}
  Skipped    : {skipped}  (already on disk)
  Failed     : {failed}
  CSV saved  : {OUTPUT_CSV}
-----------------------------------------------------------------""")


if __name__ == "__main__":
    main()
