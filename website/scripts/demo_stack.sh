#!/usr/bin/env bash
# Starts and stops the throwaway Cerebrum stack the documentation's
# screenshots are taken from. It runs on a generated demo vault, never a
# real one, and never touches a real install:
#
#   - its own Compose project name, ports and volumes;
#   - an explicit --env-file it writes itself, so the repo's .env is never
#     read (Compose only reads .env when no --env-file is given), and a
#     minimal environment, so variables exported in your shell (which would
#     override the env file) never reach Compose;
#   - images built from this checkout and tagged :docs-demo, so the
#     :latest images a real install runs are never retagged;
#   - check_demo_compose.py vets the resolved config before anything starts
#     and refuses on any sign of the above going wrong.
#
# Usage:
#   demo_stack.sh up   <work-folder> [read-only]   # folder must not exist or be empty
#   demo_stack.sh down <work-folder>
#
# `up` leaves <work-folder>/credentials.json for screenshots.mjs. With
# `read-only`, the stack serves the demo vault in read-only mode, keeping its
# index and accounts database in <work-folder>/data.
set -euo pipefail

PROJECT=cerebrum-docs-demo
PORT=18861
HTTPS_PORT=18862
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPTS/../.." && pwd)"

usage() {
  echo "usage: $0 up <work-folder> [read-only] | down <work-folder>" >&2
  exit 2
}
[ $# -eq 2 ] || { [ $# -eq 3 ] && [ "$1" = up ] && [ "$3" = read-only ]; } || usage
command="$1"
work="$(realpath -m "$2")"
mode="${3:-}"

compose() {
  # Relative paths in the Compose files (the build contexts) resolve
  # against the repo; variables come only from the generated env file.
  local files=(-f "$REPO/docker-compose.yml" -f "$REPO/docker-compose.build.yml")
  if [ -f "$work/read-only.yml" ]; then
    files+=(-f "$work/read-only.yml")
  fi
  env -i PATH="$PATH" HOME="$HOME" \
    ${DOCKER_HOST:+DOCKER_HOST="$DOCKER_HOST"} \
    ${DOCKER_CONTEXT:+DOCKER_CONTEXT="$DOCKER_CONTEXT"} \
    ${DOCKER_CONFIG:+DOCKER_CONFIG="$DOCKER_CONFIG"} \
    ${XDG_RUNTIME_DIR:+XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR"} \
    docker compose -p "$PROJECT" --project-directory "$REPO" \
    --env-file "$work/demo.env" "${files[@]}" "$@"
}

up() {
  if [ -e "$work" ] && [ -n "$(ls -A "$work")" ]; then
    echo "refusing: $work is not empty" >&2
    exit 1
  fi
  mkdir -p "$work"
  chmod 700 "$work"

  (cd "$REPO/website" && uv run python scripts/make_demo_vault.py "$work/vault")

  local setup_token password
  setup_token="$(openssl rand -hex 32)"
  password="$(openssl rand -hex 16)"
  (
    umask 077
    cat >"$work/demo.env" <<EOF
CEREBRUM_VERSION=docs-demo
CEREBRUM_VAULT_HOST_PATH=$work/vault
CEREBRUM_BIND_ADDRESS=127.0.0.1
CEREBRUM_PORT=$PORT
CEREBRUM_HTTPS_PORT=$HTTPS_PORT
CEREBRUM_UID=$(id -u)
CEREBRUM_GID=$(id -g)
AUTH_JWT_SECRET=$(openssl rand -hex 32)
AUTH_SETUP_TOKEN=$setup_token
EOF
  )
  if [ "$mode" = read-only ]; then
    # Read-only mode needs the index and accounts database outside the
    # vault; docker-compose.yml ships the mount for them commented out.
    mkdir -p "$work/data"
    cat >>"$work/demo.env" <<EOF
CEREBRUM_VAULT_READ_ONLY=true
CEREBRUM_DATA_HOST_PATH=$work/data
CEREBRUM_INDEX_PATH=/data/cerebrum/index.sqlite3
CEREBRUM_AUTH_DB_PATH=/data/cerebrum/auth.sqlite3
EOF
    cat >"$work/read-only.yml" <<'EOF'
services:
  backend:
    volumes:
      - ${CEREBRUM_DATA_HOST_PATH}:/data/cerebrum
EOF
  fi

  compose config --format json |
    (cd "$REPO/website" && uv run python scripts/check_demo_compose.py "$work" "$PORT" "$HTTPS_PORT")

  compose up -d --build --wait

  # `--wait` covers the backend's health check; the frontend has none and
  # may still be generating its certificate, so wait until the proxy answers.
  local base="http://127.0.0.1:$PORT" tries=0
  until curl -fsS -o /dev/null --max-time 2 "$base/api/health"; do
    tries=$((tries + 1))
    if [ "$tries" -ge 60 ]; then
      echo "the demo stack did not become reachable at $base" >&2
      exit 1
    fi
    sleep 1
  done
  curl -fsS -o /dev/null --max-time 10 -H 'content-type: application/json' \
    -d "{\"username\":\"demo\",\"password\":\"$password\",\"token\":\"$setup_token\"}" \
    "$base/api/auth/register"
  (
    umask 077
    printf '{"base_url":"%s","username":"demo","password":"%s"}\n' "$base" "$password" \
      >"$work/credentials.json"
  )
  echo "Demo stack running at $base"
}

down() {
  # Always removes the work folder; stops containers only when `up` got far
  # enough to write the env file Compose needs.
  local status=0
  if [ -f "$work/demo.env" ]; then
    compose down --volumes --remove-orphans || status=$?
  fi
  rm -rf "$work"
  return "$status"
}

case "$command" in
up) up ;;
down) down ;;
*) usage ;;
esac
