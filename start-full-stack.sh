#!/bin/bash
# start-full-stack.sh — Idempotent one-click launcher for the full stack.
#
# Safe to run repeatedly:
#   * keeps an existing .env (DB volumes keep their passwords);
#   * repairs nginx, the CA bundle and the Keycloak client secret;
#   * registers the reSpotIt MCP connection and starts a sync.
#
# Usage: ./start-full-stack.sh [bootstrap options]
#   --no-sync      do not start a library sync
#   --no-verify    skip the final checks
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

command -v python3 >/dev/null 2>&1 || {
    echo "[error] Python 3 is required but was not found on PATH."
    exit 1
}
command -v docker >/dev/null 2>&1 || {
    echo "[error] Docker is required but was not found on PATH."
    exit 1
}

echo "[..] Preparing full-stack files and settings..."
python3 scripts/prepare_full_stack.py

# Read the LAN origin that prepare just wrote, so every printed URL is
# reachable from a phone or a second PC (never localhost).
LAN_IP="$(grep -E '^LAN_IP=' .env | head -1 | cut -d= -f2-)"
PUBLIC_ORIGIN="$(grep -E '^PUBLIC_ORIGIN=' .env | head -1 | cut -d= -f2-)"
[ -n "$LAN_IP" ] || LAN_IP="localhost"
[ -n "$PUBLIC_ORIGIN" ] || PUBLIC_ORIGIN="https://localhost"

echo "[..] Starting containers..."
docker compose -f docker-compose.yml -f docker-compose.full.yml up -d --build

echo "[..] Bootstrapping services..."
set +e
python3 scripts/bootstrap_full_stack.py "$@"
BOOTSTRAP_RC=$?
set -e
if [ "$BOOTSTRAP_RC" -ne 0 ]; then
    echo "[warn] Bootstrap reported a problem. Containers are running; see above."
fi

echo ""
if [ "$BOOTSTRAP_RC" -eq 0 ]; then
    echo "[OK] Full stack started!"
else
    echo "[warn] Full stack started with warnings. See the bootstrap output above."
fi
echo "   reSpotIt frontend: http://$LAN_IP:8888"
echo "   reSpotIt API:      https://$LAN_IP:8000"
echo "   OpenWebUI:         $PUBLIC_ORIGIN/"
echo "   Keycloak Admin:    $PUBLIC_ORIGIN/authKeycloak/admin/"
echo "   MinIO Console:     http://$LAN_IP:9001"
echo "   Redis Insight:     http://$LAN_IP:5540"
echo ""
echo "First run: open $PUBLIC_ORIGIN/ and use the Keycloak Register link"
echo "to create your account. Then connect Spotify at http://$LAN_IP:8888"
echo "and re-run this script to sync the library."

exit "$BOOTSTRAP_RC"
