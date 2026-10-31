#!/bin/sh
# Serves the FastAPI app over HTTP or HTTPS based on SSL_ENABLED (default true).
# Auto-generates self-signed certs on first run if missing.
set -e

CERT_DIR="/app/certs"
CERT_KEY="${CERT_DIR}/server-key.pem"
CERT_FILE="${CERT_DIR}/server.pem"

generate_certs() {
    echo "[entrypoint] Generating self-signed TLS certificates..."
    mkdir -p "${CERT_DIR}"
    openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
        -keyout "${CERT_KEY}" \
        -out "${CERT_FILE}" \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,DNS:api,IP:127.0.0.1" \
        2>/dev/null
    chmod 600 "${CERT_KEY}"
    chmod 644 "${CERT_FILE}"
    echo "[entrypoint] Certificates generated at ${CERT_DIR}/"
}

if [ "${SSL_ENABLED:-true}" = "true" ]; then
    if [ ! -f "${CERT_KEY}" ] || [ ! -f "${CERT_FILE}" ]; then
        generate_certs
    else
        echo "[entrypoint] Using existing certificates from ${CERT_DIR}/"
    fi
    exec uvicorn api.main:app --host 0.0.0.0 --port 8000 \
        --ssl-keyfile "${CERT_KEY}" \
        --ssl-certfile "${CERT_FILE}"
else
    exec uvicorn api.main:app --host 0.0.0.0 --port 8000
fi