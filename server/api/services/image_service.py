"""
services/image_service.py
--------------------------
Downloads album cover art using a thread pool.
Checks a cancel flag between batches so it can be stopped mid-run.
"""

import csv
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import requests

INPUT_CSV   = os.getenv("INPUT_CSV",   "/data/spotify_albums.csv")
OUTPUT_CSV  = os.getenv("OUTPUT_CSV",  "/data/spotify_albums.csv")
IMAGES_DIR  = os.getenv("IMAGES_DIR",  "/data/images")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
WORKERS     = int(os.getenv("IMAGE_WORKERS", "8"))

_HEADERS = {"User-Agent": "spotify-album-art-downloader/1.0"}


def _safe_filename(album_id: str, url: str) -> str:
    ext = os.path.splitext(url.split("?")[0])[-1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", album_id) + ext


def _download_one(url: str, dest: str) -> bool:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=15, stream=True)
            if resp.status_code == 200:
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8_192):
                        f.write(chunk)
                return True
        except requests.RequestException:
            pass
        if attempt < MAX_RETRIES:
            time.sleep(2 ** attempt)
    return False


def run_image_download(
    csv_path: str = INPUT_CSV,
    out_path: str = OUTPUT_CSV,
    images_dir: str = IMAGES_DIR,
    workers: int = WORKERS,
    progress_cb: Callable | None = None,
    cancel_check: Callable | None = None,   # called with no args; return True to abort
) -> dict:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    os.makedirs(images_dir, exist_ok=True)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    if not rows:
        return {"total": 0, "downloaded": 0, "skipped": 0, "failed": 0}

    out_fields = list(fieldnames)
    if "image_file" not in out_fields:
        out_fields = out_fields + ["image_file"]

    total = len(rows)
    lock  = threading.Lock()
    counters = {"downloaded": 0, "skipped": 0, "failed": 0, "done": 0}

    work = []
    for i, row in enumerate(rows):
        album_id  = row.get("album_id", f"row_{i}")
        image_url = row.get("image_url", "").strip()
        existing  = row.get("image_file", "").strip()

        if existing and os.path.exists(os.path.join(images_dir, existing)):
            work.append((i, row, "skip", None, None))
        elif not image_url:
            work.append((i, row, "no_url", None, None))
        else:
            filename = _safe_filename(album_id, image_url)
            dest = os.path.join(images_dir, filename)
            work.append((i, row, "download", image_url, (dest, filename)))

    def process_item(item):
        # Check cancel flag before each item
        if cancel_check and cancel_check():
            return item[0], item[1], True   # (idx, row, was_cancelled)

        idx, row, task, url, dest_info = item
        name = row.get("name", "")

        if task == "skip":
            with lock:
                counters["skipped"] += 1
                counters["done"] += 1
                snap = dict(counters)
            result = "skipped"
        elif task == "no_url":
            row["image_file"] = ""
            with lock:
                counters["failed"] += 1
                counters["done"] += 1
                snap = dict(counters)
            result = "no_url"
        else:
            dest, filename = dest_info
            ok = _download_one(url, dest)
            with lock:
                if ok:
                    row["image_file"] = filename
                    counters["downloaded"] += 1
                else:
                    row["image_file"] = ""
                    counters["failed"] += 1
                counters["done"] += 1
                snap = dict(counters)
            result = "ok" if ok else "failed"

        if progress_cb:
            pct = int(snap["done"] / total * 100) if total else 0
            progress_cb(
                done=snap["done"], total=total, pct=pct,
                downloaded=snap["downloaded"], skipped=snap["skipped"],
                failed=snap["failed"], current_album=name, result=result,
            )

        return idx, row, False

    results = [None] * total
    cancelled = False

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_item, item): item for item in work}
        for future in as_completed(futures):
            idx, updated_row, was_cancelled = future.result()
            results[idx] = updated_row
            if was_cancelled:
                cancelled = True
                # Cancel remaining pending futures
                for f in futures:
                    f.cancel()

    # Write whatever we have so far (partial results on cancel)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(r for r in results if r is not None)

    return {
        "total":      total,
        "downloaded": counters["downloaded"],
        "skipped":    counters["skipped"],
        "failed":     counters["failed"],
        "cancelled":  cancelled,
    }
