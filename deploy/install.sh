#!/bin/sh
# Cerebrum installer: sets up and starts a Cerebrum server with Docker, with
# no clone and no file editing.
#
#   curl -fsSL https://github.com/piurizza/cerebrum/releases/latest/download/install.sh | sh
#
# Run it again to update: it replaces compose.yaml with its release's copy,
# pulls the images and restarts, and never touches .env or your notes. Until
# a run gets Cerebrum answering, every run shows the first account's invite
# token, so rerunning after a failed first install still shows it.
#
# Optional settings, read from the environment on a fresh install only:
#   CEREBRUM_INSTALL_DIR   where to install (default: ~/cerebrum-server)
#   CEREBRUM_PORT          HTTP port (default: 7811)
#   CEREBRUM_HTTPS_PORT    HTTPS port (default: 7812)
#   CEREBRUM_BIND_ADDRESS  127.0.0.1 = this machine only (default);
#                          0.0.0.0 or a LAN address = phone and other devices
#   CEREBRUM_TLS_SAN       extra HTTPS certificate names, e.g. IP:192.168.1.14
#
# Testing hooks (CI runs the installer against locally built images):
#   CEREBRUM_COMPOSE_SOURCE  copy this local compose file instead of downloading
#   CEREBRUM_SKIP_PULL=1     don't pull images
#   CEREBRUM_VERSION         image tag to pin in a fresh .env

set -eu

# Replaced with the release tag (e.g. v0.3.0) when the release publishes this
# file; left as-is, the installer follows the latest release.
RELEASE_TAG="__CEREBRUM_RELEASE_TAG__"
REPO="piurizza/cerebrum"
HEALTH_TIMEOUT_SECS=120
# Same defaults as docker-compose.yml.
DEFAULT_PORT=7811
DEFAULT_HTTPS_PORT=7812
DEFAULT_BIND_ADDRESS=127.0.0.1

say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
fail() {
	printf '\nError: %s\n' "$*" >&2
	exit 1
}

check_not_root() {
	if [ "$(id -u)" -eq 0 ]; then
		fail "don't run the installer as root or with sudo: your notes would end up owned by root. Run it as your own user."
	fi
}

check_tools() {
	command -v docker >/dev/null 2>&1 || fail "Docker isn't installed. Install Docker Desktop (macOS, Windows) or Docker Engine (Linux): https://docs.docker.com/get-docker/"
	if ! docker_info=$(docker info 2>&1); then
		case "$docker_info" in
		*"permission denied"*)
			fail "your user can't talk to Docker yet. On Linux, add yourself to the docker group, then log out and back in:
    sudo usermod -aG docker \"\$USER\"
Being in that group is equivalent to root access on this machine; see https://docs.docker.com/engine/install/linux-postinstall/"
			;;
		*)
			fail "Docker is installed but not running. Start Docker Desktop, or on Linux: sudo systemctl start docker"
			;;
		esac
	fi
	docker compose version >/dev/null 2>&1 || fail "the Docker Compose v2 plugin (docker compose) is missing: https://docs.docker.com/compose/install/"
	if command -v curl >/dev/null 2>&1; then
		HTTP_GET="curl -fsSL"
	elif command -v wget >/dev/null 2>&1; then
		HTTP_GET="wget -qO-"
	else
		fail "neither curl nor wget is installed; install one and run the installer again."
	fi
}

random_hex() {
	if command -v openssl >/dev/null 2>&1; then
		openssl rand -hex 32
	else
		od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
	fi
}

# Value of KEY in .env, or empty. Last assignment wins, like Compose.
env_value() {
	sed -n "s/^$1=//p" .env | tail -n 1
}

compose_default_version() {
	sed -n 's/.*CEREBRUM_VERSION:-\([^}]*\)}.*/\1/p' "$1" 2>/dev/null | head -n 1
}

fetch_compose_file() {
	if [ -n "${CEREBRUM_COMPOSE_SOURCE:-}" ]; then
		cp "$CEREBRUM_COMPOSE_SOURCE" compose.yaml.tmp
	else
		if [ "$RELEASE_TAG" = "__CEREBRUM_RELEASE_TAG__" ]; then
			url="https://github.com/$REPO/releases/latest/download/compose.yaml"
		else
			url="https://github.com/$REPO/releases/download/$RELEASE_TAG/compose.yaml"
		fi
		$HTTP_GET "$url" >compose.yaml.tmp || fail "couldn't download $url"
	fi
	mv compose.yaml.tmp compose.yaml
}

write_env() {
	jwt_secret=$(random_hex)
	setup_token=$(random_hex)
	# Only the owner may read it: the JWT secret signs every login.
	(
		umask 077
		{
			say "# Written by the Cerebrum installer on $(date -u +%Y-%m-%d). Keep it private:"
			say "# AUTH_JWT_SECRET signs every login. See .env.example in the repo for all settings."
			say "AUTH_JWT_SECRET=$jwt_secret"
			say "AUTH_SETUP_TOKEN=$setup_token"
			say "CEREBRUM_UID=$(id -u)"
			say "CEREBRUM_GID=$(id -g)"
			say "CEREBRUM_PORT=${CEREBRUM_PORT:-$DEFAULT_PORT}"
			say "CEREBRUM_HTTPS_PORT=${CEREBRUM_HTTPS_PORT:-$DEFAULT_HTTPS_PORT}"
			say "CEREBRUM_BIND_ADDRESS=${CEREBRUM_BIND_ADDRESS:-$DEFAULT_BIND_ADDRESS}"
			say "CEREBRUM_TLS_SAN=${CEREBRUM_TLS_SAN:-}"
			if [ "$(uname -s)" = "Darwin" ]; then
				# Docker Desktop's file sharing doesn't deliver change events
				# reliably, so notes edited outside Cerebrum need polling.
				say "WATCHFILES_FORCE_POLLING=1"
			fi
			if [ -n "${CEREBRUM_VERSION:-}" ]; then
				say "CEREBRUM_VERSION=$CEREBRUM_VERSION"
			fi
		} >.env.tmp
		mkdir -p vault
	)
	mv .env.tmp .env
}

port_in_use() {
	command -v nc >/dev/null 2>&1 || return 1
	nc -z "$1" "$2" >/dev/null 2>&1
}

probe_host() {
	case "$1" in
	"" | 0.0.0.0) say 127.0.0.1 ;;
	*) say "$1" ;;
	esac
}

# Fresh install: check the ports it is about to write, before writing
# anything, so a conflict is fixed by rerunning with another port.
check_fresh_ports_free() {
	host=$(probe_host "${CEREBRUM_BIND_ADDRESS:-$DEFAULT_BIND_ADDRESS}")
	for port in "${CEREBRUM_PORT:-$DEFAULT_PORT}" "${CEREBRUM_HTTPS_PORT:-$DEFAULT_HTTPS_PORT}"; do
		if port_in_use "$host" "$port"; then
			fail "port $port is already in use by another program. Run the installer again with two free ports, for example:
    CEREBRUM_PORT=7821 CEREBRUM_HTTPS_PORT=7822 sh install.sh"
		fi
	done
}

# Existing install: its own running stack holds the ports, which is fine.
check_existing_ports_free() {
	if [ -n "$(docker compose ps -q 2>/dev/null)" ]; then
		return 0
	fi
	for var in CEREBRUM_PORT CEREBRUM_HTTPS_PORT; do
		port=$(env_value "$var")
		if port_in_use "$PROBE_HOST" "$port"; then
			fail "port $port is already in use by another program. Choose a free one in $INSTALL_DIR/.env ($var=...) and run the installer again."
		fi
	done
}

fail_with_logs() {
	say ""
	say "Last backend log lines:"
	docker compose logs --no-color --tail 20 backend || true
	token_hint=""
	if [ "$installed" = false ]; then
		token_hint=" The invite token is saved in $INSTALL_DIR/.env (AUTH_SETUP_TOKEN) and will be shown again after a successful run."
	fi
	fail "$1 Your install is in $INSTALL_DIR; fix the problem above, then run the installer again.$token_hint"
}

start_stack() {
	# `up` itself fails when the backend never turns healthy (the frontend
	# waits for it), so its failure needs the logs as much as a timeout does.
	if ! docker compose up -d --remove-orphans; then
		fail_with_logs "Cerebrum didn't start."
	fi
}

wait_until_healthy() {
	url="http://$PROBE_HOST:$(env_value CEREBRUM_PORT)/api/health"
	elapsed=0
	while [ "$elapsed" -lt "$HEALTH_TIMEOUT_SECS" ]; do
		if $HTTP_GET "$url" >/dev/null 2>&1; then
			return 0
		fi
		sleep 3
		elapsed=$((elapsed + 3))
	done
	fail_with_logs "Cerebrum didn't answer on $url within $HEALTH_TIMEOUT_SECS seconds."
}

# "0.3.0", or "0.3.0 (pinned)" when .env pins a version; empty for "latest".
version_label() {
	pinned=$(env_value CEREBRUM_VERSION)
	if [ -n "$pinned" ]; then
		say "$pinned (pinned in .env)"
	elif [ "$1" != "latest" ]; then
		say "$1"
	fi
}

main() {
	check_not_root
	check_tools

	# Docker Compose names the project after this folder, so each install is
	# its own project: two installs, or an install next to a source checkout
	# (usually a folder named cerebrum), never control each other's containers.
	INSTALL_DIR=${CEREBRUM_INSTALL_DIR:-$HOME/cerebrum-server}
	if [ -d "$INSTALL_DIR/.git" ] || [ -f "$INSTALL_DIR/docker-compose.build.yml" ]; then
		fail "$INSTALL_DIR is a copy of the Cerebrum source code. Install somewhere else, e.g.: CEREBRUM_INSTALL_DIR=\$HOME/cerebrum-notes sh install.sh"
	fi
	mkdir -p "$INSTALL_DIR"
	cd "$INSTALL_DIR"

	fresh=false
	[ -f .env ] || fresh=true
	# Written once a run gets Cerebrum answering: until then the invite token
	# has never been shown, so every run shows it.
	installed=false
	[ -f .installed ] && installed=true
	if [ "$fresh" = true ]; then
		check_fresh_ports_free
	fi
	previous=$(compose_default_version compose.yaml)

	step "Downloading the Cerebrum configuration"
	fetch_compose_file
	current=$(compose_default_version compose.yaml)

	if [ "$fresh" = true ]; then
		step "Creating secrets and the notes folder in $INSTALL_DIR"
		write_env
		# New secrets mean a new invite token, which has never been shown.
		rm -f .installed
		installed=false
	fi

	# Compose prefers shell variables over .env, while this script reads only
	# .env: without these the stack could bind a port the health check never
	# probes. A fresh .env has already taken the settings above.
	unset CEREBRUM_VERSION CEREBRUM_UID CEREBRUM_GID AUTH_JWT_SECRET AUTH_SETUP_TOKEN \
		WATCHFILES_FORCE_POLLING CEREBRUM_DAILY_NOTE_FOLDER VITE_DAILY_NOTE_FOLDER \
		CEREBRUM_TEMPLATES_FOLDER VITE_TEMPLATES_FOLDER CEREBRUM_VAULT_HOST_PATH \
		CEREBRUM_TLS_SAN CEREBRUM_BIND_ADDRESS CEREBRUM_PORT CEREBRUM_HTTPS_PORT \
		CEREBRUM_LINK_FORMAT

	PROBE_HOST=$(probe_host "$(env_value CEREBRUM_BIND_ADDRESS)")
	if [ "$fresh" = false ]; then
		check_existing_ports_free
	fi

	if [ "${CEREBRUM_SKIP_PULL:-}" != "1" ]; then
		step "Downloading the Cerebrum images (the first time takes a few minutes)"
		docker compose pull
	fi

	step "Starting Cerebrum"
	start_stack

	step "Waiting for Cerebrum to answer"
	wait_until_healthy

	url_host=$PROBE_HOST
	[ "$url_host" != 127.0.0.1 ] || url_host=localhost
	url="http://$url_host:$(env_value CEREBRUM_PORT)"
	label=$(version_label "${current:-latest}")
	say ""
	if [ "$installed" = false ]; then
		say "Cerebrum ${label:+$label }is running at $url"
		say ""
		say "Open it, choose Register, and paste this as the Invite token:"
		say "    $(env_value AUTH_SETUP_TOKEN)"
		say "The token only works for the first account, so create yours now."
		say ""
		say "To use Cerebrum from your phone or other computers, set CEREBRUM_BIND_ADDRESS"
		say "and CEREBRUM_TLS_SAN in $INSTALL_DIR/.env (see the README), then run the installer again."
	elif [ -z "$(env_value CEREBRUM_VERSION)" ] && [ -n "$previous" ] && [ "$previous" != "$current" ]; then
		say "Cerebrum updated from $previous to $current and running at $url"
	else
		say "Cerebrum ${label:+$label }restarted and running at $url"
	fi
	: >.installed
}

main "$@"
