# Backup script for the Docker deployment (Windows PowerShell)
# Backs up ./data and the Postgres volume to ./backups/<timestamp>/
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$dest = Join-Path $root "backups\$ts"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# 1. File data (images, CSVs)
$data = Join-Path $root "data"
if (Test-Path $data) {
    Copy-Item -Recurse -Force $data (Join-Path $dest "data")
    Write-Host "Backed up data/ -> $dest\data"
}

# 2. Postgres dump
$pg = Join-Path $dest "postgres.sql"
docker compose -f (Join-Path $root "docker-compose.yml") exec -T db pg_dump -U spotify spotify > $pg
Write-Host "Backed up Postgres -> $pg"

Write-Host "Backup complete: $dest"
