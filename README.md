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

## Requirements

**To run the prebuilt images** (the usual way; see
[Run with Docker](#run-with-docker)): Docker with the Compose v2 plugin
(`docker compose`), on x86_64 -- the published images are x86_64 only for
now. Nothing is compiled, so building needs no extra memory or disk. Ports
7811 (HTTP) and 7812 (HTTPS) must be free, or set other ones in `.env`.

| Resource | Requirement | Measured |
|---|---|---|
| RAM | 100 MB | 75 MB backend + 11 MB frontend (nginx), idle |
| CPU | Any | Under 1% of one core when idle |
| Disk, images | 470 MB | 349 MB backend + 114 MB frontend |
| Disk, your notes | Size of your notes + index | 2.8 MB for 51 notes, including the search index and accounts database |

**To build the images from source** (`make up`, or any architecture
without published images): Docker Engine 23.0 or newer, since the
Dockerfiles use BuildKit cache mounts and BuildKit is the default builder
from 23.0, plus:

| Resource | Requirement | Measured |
|---|---|---|
| RAM | 2 GB free | Frontend build passes with a 2 GB memory limit and is killed at 1.5 GB |
| Disk | 2.5 GB | Images + 2 GB of build cache; `docker builder prune` frees the cache afterwards |
| Time | — | 26 s with an empty build cache |

Measured on Fedora 44, x86_64 (Intel Core i7-10750H, 12 threads), Docker
Engine 29.9.1, with the 51-note vault above. arm64 (e.g. a Raspberry Pi)
is untested.

**On Linux, prefer Docker Engine over Docker Desktop.** Docker Desktop
runs containers inside a VM, and on Fedora 44 that VM (Docker Desktop
4.43.1 with QEMU 10.2.2) crashed repeatedly during image downloads and
builds. Docker Engine runs containers natively, with no VM and no memory
reservation of its own.

**Browsers:** the end-to-end tests run on Chrome with a Pixel 7 mobile
viewport; other current browsers are expected to work but aren't covered
by tests. Offline mode and installing to a phone need HTTPS (see
[Install on a phone](#install-on-a-phone-pwa)).

**Desktop app:** Linux x86_64, as a `.deb` (Debian, Ubuntu) or `.rpm`
(Fedora, openSUSE), and macOS, as one `.dmg` for Apple Silicon and Intel
(tested on macOS 26, Apple Silicon), and 64-bit Windows 10 or 11, as a
setup `.exe`, plus a running Cerebrum server to connect to; see
[Run desktop app](#run-desktop-app).

**Without Docker (development):** Python 3.12+ with
[uv](https://docs.astral.sh/uv/), and Node 22.

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

Each release publishes prebuilt images to GitHub's container registry
(`ghcr.io/piurizza/cerebrum-backend` and `-frontend`), so running
Cerebrum needs no Node or Python and no build:

    git clone https://github.com/piurizza/cerebrum.git && cd cerebrum
    cp .env.example .env    # then set AUTH_JWT_SECRET and AUTH_SETUP_TOKEN
    mkdir -p vault
    docker compose pull
    docker compose up -d    # http://localhost:7811

`docker compose pull && docker compose up -d` again updates to the latest
release. To stay on one release, set `CEREBRUM_VERSION=0.1.0` (for
example) in `.env`. Each image carries a GitHub build attestation, which
`gh attestation verify oci://ghcr.io/piurizza/cerebrum-backend:latest
--owner piurizza` checks.

To build the images from source instead:

    make up     # builds and starts backend + frontend, http://localhost:7811
    make down
    make logs

Notes are bind-mounted from `./vault` on the host (override via
`CEREBRUM_VAULT_HOST_PATH` in a root `.env`, copied from `.env.example`) so
they persist independently of the containers.

The backend runs as user and group 1000, not root, so notes it creates
belong to you on the host. If `id -u` doesn't print 1000, set
`CEREBRUM_UID` and `CEREBRUM_GID` in `.env`. `make up` creates the vault
directory first; with plain `docker compose up`, create it yourself, or
Docker creates it owned by root and the backend can't write to it. If an
older version already ran the backend as root on native Linux Docker,
hand the vault back to your user once:
`sudo chown -R "$(id -u):$(id -g)" vault`.

Accounts, sessions, and personal API tokens live in their own SQLite
database (`auth.sqlite3`), stored alongside the search index under
`<vault>/.cerebrum/` -- i.e. inside the same bind-mounted vault directory
above, not a separate volume. Anyone already backing up the vault is
already backing up accounts/sessions/tokens; no separate backup step is
needed as long as `auth.sqlite3` stays under that mount.

The frontend also serves HTTPS on `https://localhost:7812` (override via
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

- **Tailscale** (no domain, free):

      sudo dnf install tailscale               # or your distro's package
      sudo systemctl enable --now tailscaled
      sudo tailscale up                        # opens a browser login

  In the admin console (login.tailscale.com → **DNS**), enable
  **MagicDNS** and **HTTPS Certificates**. Install the Tailscale app on
  the phone too, signed into the same account — any device on the
  tailnet can then reach this machine, from anywhere, not just the LAN.

  Find this machine's tailnet name (`tailscale status` shows the short
  hostname; the full name is in `tailscale status --json` under
  `Self.DNSName`, or just run `tailscale cert` with no argument — it
  prints the exact domain to use). Then, **one time**, make yourself the
  Tailscale operator so `cert` doesn't need root on every renewal:

      sudo tailscale set --operator=$USER

  Now issue the cert:

      tailscale cert <machine>.<tailnet>.ts.net

  That writes `<name>.ts.net.crt` and `<name>.ts.net.key`. Drop them into
  the frontend's cert volume as `cerebrum.crt` / `cerebrum.key` — nginx
  already points there and the entrypoint only self-signs when they're
  absent, so no image change:

      docker compose cp <name>.ts.net.crt frontend:/etc/nginx/certs/cerebrum.crt
      docker compose cp <name>.ts.net.key frontend:/etc/nginx/certs/cerebrum.key
      docker compose restart frontend

  Then open `https://<name>.ts.net:7812` on the phone (any tailnet
  device, from anywhere). Tailscale certs last 90 days — re-run
  `tailscale cert` and re-copy to renew (a monthly cron is enough; the
  `--operator` step above means the cron doesn't need root either).

- **Reverse proxy + Let's Encrypt**: put Caddy or nginx with a real
  domain in front of `CEREBRUM_PORT`, terminating TLS there. More setup
  (a domain, a public entry point) but standard.

### Install

- **Android / Chrome:** browser menu → **Install app**, or
  **Settings → Install app** inside Cerebrum.
- **iOS / Safari:** **Share** → **Add to Home Screen**. Cerebrum shows a
  one-time hint after you open your first note.

## Run desktop app

Native window on Linux, macOS and Windows, no browser tab. On first launch it
asks for a server URL — point it at any running cerebrum deployment
(Docker or `make up` locally). No separate backend or account: it's a
thin client for a server that's already running, not a second copy of
the app. See [SPEC.md](SPEC.md#7-tech-stack) for why.

Each [release](https://github.com/piurizza/cerebrum/releases/latest)
attaches a `.deb` and an `.rpm` (Linux x86_64), a `.dmg` (macOS,
universal) and a setup `.exe` (Windows x64).

**Linux:** download a package and install it with your package manager,
which also pulls in WebKitGTK:

    sudo apt install ./Cerebrum_*_amd64.deb       # Debian, Ubuntu
    sudo dnf install ./Cerebrum-*.x86_64.rpm      # Fedora

**macOS:** open the `.dmg` and drag Cerebrum into Applications. The app
is not notarized by Apple (that needs a paid developer account), so the
first launch is blocked: open it once, then go to **System Settings →
Privacy & Security** and click **Open Anyway**. macOS remembers the
choice. If you'd rather not use the dialog, removing the download flag
has the same effect:

    xattr -dr com.apple.quarantine /Applications/Cerebrum.app

**Windows:** run the setup `.exe`; it installs for your user only, no
administrator rights needed. The installer is not code-signed (that needs
a paid certificate), so SmartScreen shows "Windows protected your PC":
click **More info**, then **Run anyway**. The app uses Microsoft's
WebView2, which Windows 11 includes; on Windows 10 the installer
downloads it if it's missing. Every pull request that touches the
desktop app installs and launches the Windows build in CI; it has not
been tried by hand on a Windows PC yet.

To run from source: `cd desktop && npm run tauri dev`. To build the
packages yourself: `make build-desktop`. On Linux it needs the
`webkit2gtk4.1-devel` and `librsvg2-devel` system packages (OS packages,
not installed by `make install-desktop`); on macOS it needs Xcode's
command line tools and both Rust targets
(`rustup target add aarch64-apple-darwin x86_64-apple-darwin`). On
Windows, run `npm run tauri build -- --bundles nsis` in `desktop/`
(needs the Visual Studio C++ build tools).

## MCP server

An MCP server is mounted at `/api/mcp`, reachable through the same
frontend-published port and nginx proxy as the REST API (no separate port).
Remote clients (e.g. Claude Desktop) can read, search, create, update,
append to, edit, and delete notes over it.

Every call is authenticated. Generate a personal API token in
**Settings** (it starts with `cbm_pat_`) and give it to your MCP client
as a bearer token. Tokens can be revoked from the same page, and a
deactivated account's tokens stop working immediately.

**If you expose this beyond your own machine, use HTTPS** -- the bundled
`https://` port (see [Run with Docker](#run-with-docker)) or a
Tailscale / reverse-proxy setup (see [Install on a phone](#install-on-a-phone-pwa)),
so the token never travels in plain text.

## License

[MIT](LICENSE)
