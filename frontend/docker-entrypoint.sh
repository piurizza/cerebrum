#!/bin/sh
set -eu

# Offline mode (docs/plans/2026-08-14-001-feat-desktop-offline-mode-plan.md,
# KD4/U1) needs a secure context for the browser to register a service
# worker at all -- plain HTTP only qualifies for the literal "localhost"
# hostname, never a LAN IP, which is exactly how this app is normally
# reached from a phone. Rather than require every self-hosted deployment to
# bring its own certificate, generate a self-signed one on first start if
# none exists yet -- acceptable for this app's personal-use, single-admin
# deployment model (same reasoning as the desktop app's own personal-use
# scope). Persisted in the mounted certs volume so it survives container
# restarts and isn't re-generated (and doesn't need re-trusting) every time.
CERT_DIR="/etc/nginx/certs"
CERT_FILE="$CERT_DIR/cerebrum.crt"
KEY_FILE="$CERT_DIR/cerebrum.key"

if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
  mkdir -p "$CERT_DIR"
  # CEREBRUM_TLS_SAN: extra Subject Alternative Names for LAN/phone access
  # (e.g. "IP:192.168.1.14" or "DNS:cerebrum.local"), comma-separated.
  # Left for the operator to set -- like WATCHFILES_FORCE_POLLING elsewhere
  # in this repo, this isn't something to auto-detect and guess at.
  SAN="DNS:localhost,IP:127.0.0.1"
  if [ -n "${CEREBRUM_TLS_SAN:-}" ]; then
    SAN="$SAN,$CEREBRUM_TLS_SAN"
  fi
  openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout "$KEY_FILE" -out "$CERT_FILE" \
    -days 3650 \
    -subj "/CN=cerebrum" \
    -addext "subjectAltName=$SAN"
  chmod 600 "$KEY_FILE"
fi

exec /docker-entrypoint.sh "$@"
