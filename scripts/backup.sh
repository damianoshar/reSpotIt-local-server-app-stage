#!/usr/bin/env bash
# Backup script for the Docker deployment (Linux/macOS)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TS="$(date +%Y%m%d-%H%M%S)"
DEST="$ROOT/backups/$TS"
mkdir -p "$DEST"

if [ -d "$ROOT/data" ]; then
    cp -r "$ROOT/data" "$DEST/data"
    echo "Backed up data/ -> $DEST/data"
fi

docker compose -f "$ROOT/docker-compose.yml" exec -T db pg_dump -U spotify spotify > "$DEST/postgres.sql"
echo "Backed up Postgres -> $DEST/postgres.sql"
echo "Backup complete: $DEST"
