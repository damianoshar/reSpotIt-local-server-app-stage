#!/bin/sh
# Issue the API's TLS certificate from the local development CA.
#
# Why a CA instead of a self-signed leaf: the Android clients trust the CA, so
# when the PC gets a new LAN IP only the leaf is reissued here. Nothing has to be
# rebuilt or reinstalled on the phone.
#
# The CA is the mkcert one already in certs/ca/ (rootCA.pem + rootCA-key.pem) ???
# the same root the phone has installed. If it is missing, a local CA is created.
#
# Usage:
#   ./scripts/local-certs.sh                    # localhost, api, 127.0.0.1
#   ./scripts/local-certs.sh 192.168.1.11       # plus a LAN IP
#   ./scripts/local-certs.sh 192.168.1.11 10.0.0.5
#
# Output (all gitignored): certs/server.pem, certs/server-key.pem,
#                          certs/ca/rootCA.pem, certs/ca/rootCA-key.pem
#
# Requires Docker (uses alpine/openssl so no host OpenSSL is needed).
set -eu
# Avoid MSYS path conversion on Windows (harmless elsewhere).
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

CERTS_DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
mkdir -p "$CERTS_DIR"

SAN="DNS:localhost,DNS:api,IP:127.0.0.1"
for ip in "$@"; do
  case "$ip" in
    *[!0-9.]*) echo "[certs] ignoring non-IPv4 argument: $ip" >&2 ;;
    *) SAN="$SAN,IP:$ip" ;;
  esac
done

docker run --rm --entrypoint sh -e SAN="$SAN" -v "$CERTS_DIR:/certs" -w /certs alpine/openssl -eu -c '
  mkdir -p ca
  if [ ! -f ca/rootCA.pem ] || [ ! -f ca/rootCA-key.pem ]; then
    echo "[certs] no local CA found - creating one (10 years)"
    openssl req -x509 -newkey rsa:4096 -nodes -days 3650 \
      -keyout ca/rootCA-key.pem -out ca/rootCA.pem \
      -subj "/CN=reSpotIt Local CA/O=reSpotIt" \
      -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
      -addext "keyUsage=critical,keyCertSign,cRLSign" \
      -addext "subjectKeyIdentifier=hash" 2>/dev/null
    chmod 600 ca/rootCA-key.pem
  else
    echo "[certs] reusing the existing local CA"
  fi

  echo "[certs] issuing server certificate"
  openssl req -newkey rsa:2048 -nodes -keyout server-key.pem -out /tmp/server.csr \
    -subj "/CN=reSpotIt/O=reSpotIt" 2>/dev/null
  cat > /tmp/server.ext <<EOF
subjectAltName=$SAN
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
  openssl x509 -req -in /tmp/server.csr -CA ca/rootCA.pem -CAkey ca/rootCA-key.pem \
    -CAcreateserial -days 825 -out server.pem -extfile /tmp/server.ext 2>/dev/null
  chmod 600 server-key.pem
  chmod 644 server.pem ca/rootCA.pem
  rm -f /tmp/server.csr /tmp/server.ext
  echo "[certs] SANs: $SAN"
  openssl verify -CAfile ca/rootCA.pem server.pem
  echo "[certs] CA SHA-256:"
  openssl x509 -in ca/rootCA.pem -noout -fingerprint -sha256 | sed "s/^/  /"
'

echo
echo "CA certificate : $CERTS_DIR/ca/rootCA.pem"
echo "Server cert    : $CERTS_DIR/server.pem"
echo "Restart the API container so it picks up the new certificate:"
echo "  docker compose -f docker-compose.yml -f docker-compose.full.yml restart api"
