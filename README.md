# Cerebrum

[![CI](https://github.com/piurizza/cerebrum/actions/workflows/ci.yml/badge.svg)](https://github.com/piurizza/cerebrum/actions/workflows/ci.yml)

A self-hosted second brain: notes are plain `.md` files on disk, cross-referenced
with standard markdown links, with a visual graph of how they connect.

See [SPEC.md](SPEC.md) for the full design — storage model, note/frontmatter
format, API surface, graph data model, and tech stack rationale. Read it before
making architectural changes.

## Layout

- `backend/` — FastAPI + SQLite index, serves the notes API (Python, `uv`)
- `frontend/` — React + Vite + TypeScript web client (markdown editor + graph view)
- `desktop/` — Tauri v2 native client, Linux (points at a running backend/frontend deployment; see [Run desktop app](#run-desktop-app))
- `vault/` — default local dev directory for `.md` notes (gitignored)

## Setup

    make install

Copies `.env.example` → `.env` for both backend and frontend, installs
dependencies, and (in a git repo) installs pre-commit hooks.

## Common Commands

    make format       # ruff (backend) + biome (frontend)
    make lint         # ruff + pylint (backend), biome (frontend)
    make type-check   # mypy --strict (backend), tsc (frontend)
    make test         # pytest (backend), vitest + production build (frontend)
    make check        # lint + type-check + test

## Run locally (without Docker)

    cd backend && uv run cerebrum        # http://localhost:8000
    cd frontend && npm run dev           # http://localhost:5173 (proxies /api to :8000)

## Run with Docker

    make up     # builds and starts backend + frontend, http://localhost:8080
    make down
    make logs

Notes are bind-mounted from `./vault` on the host (override via
`CEREBRUM_VAULT_HOST_PATH` in a root `.env`, copied from `.env.example`) so
they persist independently of the containers.

Accounts, sessions, and personal API tokens live in their own SQLite
database (`auth.sqlite3`), stored alongside the search index under
`<vault>/.cerebrum/` -- i.e. inside the same bind-mounted vault directory
above, not a separate volume. Anyone already backing up the vault is
already backing up accounts/sessions/tokens; no separate backup step is
needed as long as `auth.sqlite3` stays under that mount.

The frontend also serves HTTPS on `https://localhost:8443` (override via
`CEREBRUM_HTTPS_PORT`), using a self-signed cert nginx generates on first
start. Offline mode (see [SPEC.md](SPEC.md#7-tech-stack)) needs this --
a service worker only registers in a secure context, which plain HTTP
only satisfies for `localhost`, not a LAN IP. To use offline mode from a
phone or another device on your network: set `CEREBRUM_TLS_SAN` in your
`.env` to your LAN IP (e.g. `IP:192.168.1.14`) before first start, then
visit the `https://` URL on that device once and accept the one-time
"not trusted" browser warning -- expected for a self-signed cert,
click through it ("Advanced" / "Proceed anyway", wording varies by
browser). Plain HTTP on `CEREBRUM_PORT` keeps working unchanged for
everything except offline mode.

## Install on a phone (PWA)

Cerebrum is an installable PWA — add it to a phone's home screen and it
launches full-screen, no browser chrome, with the shell and last-synced
vault cached for offline **reading**. (Offline editing on mobile is out
of scope; it stays a thin client to one server — see
[SPEC.md](SPEC.md#10-known-gaps--future-work).)

### You need a browser-trusted HTTPS origin

Phones only register a service worker over a genuinely trusted
certificate. Clicking through a self-signed-cert warning is **not
enough** on Chrome / Android WebView — the SW silently refuses to
register, so the app won't install. `localhost` is the only plaintext
exception and doesn't help a real device. Two ways to get a trusted
origin for a self-hosted deployment:

- **Tailscale** (no domain, free): join the machine and the phone to a
  tailnet, enable **HTTPS Certificates** in the admin console
  (login.tailscale.com → DNS), then:

      tailscale cert <machine>.<tailnet>.ts.net

  That writes `<name>.ts.net.crt` and `<name>.ts.net.key`. Drop them into
  the frontend's cert volume as `cerebrum.crt` / `cerebrum.key` — nginx
  already points there and the entrypoint only self-signs when they're
  absent, so no image change:

      docker compose cp <name>.ts.net.crt frontend:/etc/nginx/certs/cerebrum.crt
      docker compose cp <name>.ts.net.key frontend:/etc/nginx/certs/cerebrum.key
      docker compose restart frontend

  Then open `https://<name>.ts.net:8443` on the phone (any tailnet
  device, from anywhere). Tailscale certs last 90 days — re-run
  `tailscale cert` and re-copy to renew (a monthly cron is enough).

- **Reverse proxy + Let's Encrypt**: put Caddy or nginx with a real
  domain in front of `CEREBRUM_PORT`, terminating TLS there. More setup
  (a domain, a public entry point) but standard.

### Install

- **Android / Chrome:** browser menu → **Install app**, or
  **Settings → Install app** inside Cerebrum.
- **iOS / Safari:** **Share** → **Add to Home Screen**. Cerebrum shows a
  one-time hint after you open your first note.

## Run desktop app

    cd desktop && npm run tauri dev

Native window (Linux only for now), no browser tab. On first launch it
asks for a server URL — point it at any running cerebrum deployment
(Docker or `make up` locally). No separate backend or account: it's a
thin client for a server that's already running, not a second copy of
the app. See [SPEC.md](SPEC.md#7-tech-stack) for why.

To build a `.deb`: `make build-desktop` (needs `webkit2gtk4.1-devel` and
`librsvg2-devel` system packages on the build machine — not installed by
`make install-desktop`, since they're OS packages, not npm ones).

## MCP server

An MCP server is mounted at `/api/mcp`, reachable through the same
frontend-published port and nginx proxy as the REST API (no separate port).
Remote clients (e.g. Claude Desktop) can read, search, create, and update
notes over it. Every call requires the same credential as the rest of the
backend; until the backend-authentication feature ships, that check is a
fail-closed stub (`mcp_allow_stub_auth`, off by default) rather than a real
one.

**If you expose this beyond `localhost`, put TLS in front of it** (a
reverse proxy or tunnel) -- this is the same pre-existing gap the rest of
Cerebrum's remote access already has, not something specific to MCP, and
this project does not terminate TLS itself.
