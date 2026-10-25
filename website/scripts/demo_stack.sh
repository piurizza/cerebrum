#!/usr/bin/env bash
# Starts and stops the throwaway Cerebrum stack the documentation's
# screenshots are taken from. It runs on a generated demo vault, never a
# real one, and never touches a real install:
#
#   - its own Compose project name, ports and volumes;
#   - an explicit --env-file it writes itself, so the repo's .env is never
#     read (Compose only reads .env when no --env-file is given);
#   - images built from this checkout and tagged :docs-demo, so the
#     :latest images a real install runs are never retagged;
#   - check_demo_compose.py vets the resolved config before anything starts
#     and refuses on any sign of the above going wrong.
#
# Usage:
#   demo_stack.sh up   <work-folder>   # folder must not exist or be empty
#   demo_stack.sh down <work-folder>
#
# `up` leaves <work-folder>/credentials.json for screenshots.mjs.
set -euo pipefail

PROJECT=cerebrum-docs-demo
PORT=18861
HTTPS_PORT=18862
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPTS/../.." && pwd)"

usage() {
  echo "usage: $0 up|down <work-folder>" >&2
  exit 2
}
[ $# -eq 2 ] || usage
command="$1"
work="$(realpath -m "$2")"

compose() {
  # Relative paths in the Compose files (the build contexts) resolve
  # against the repo; variables come only from the generated env file.
  docker compose -p "$PROJECT" --project-directory "$REPO" \
    --env-file "$work/demo.env" \
    -f "$REPO/docker-compose.yml" -f "$REPO/docker-compose.build.yml" "$@"
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

  compose config --format json |
    (cd "$REPO/website" && uv run python scripts/check_demo_compose.py "$work" "$PORT" "$HTTPS_PORT")

  compose up -d --build --wait

  local base="http://127.0.0.1:$PORT"
  curl -fsS -o /dev/null -H 'content-type: application/json' \
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
  if [ ! -f "$work/demo.env" ]; then
    echo "nothing to stop: $work/demo.env not found" >&2
    exit 1
  fi
  compose down --volumes --remove-orphans
  rm -rf "$work"
}

case "$command" in
up) up ;;
down) down ;;
*) usage ;;
esac
