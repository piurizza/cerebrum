# Cerebrum

[![CI](https://github.com/piurizza/cerebrum/actions/workflows/ci.yml/badge.svg)](https://github.com/piurizza/cerebrum/actions/workflows/ci.yml)

A self-hosted second brain: notes are plain `.md` files on disk, cross-referenced
with standard markdown links (Obsidian `[[wikilinks]]` work too), with a visual
graph of how they connect.

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
[Install](#install)): Docker with the Compose v2 plugin
(`docker compose`), on x86_64 or arm64 (Apple Silicon Macs, Raspberry Pi
and other ARM machines). Nothing is compiled, so building needs no extra memory or disk. Ports
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
Engine 29.9.1, with the 51-note vault above. The arm64 images build and
run on Apple Silicon, and CI installs on arm64; a Raspberry Pi is untested.

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

## Install

On macOS or Linux, with Docker running:

    curl -fsSL https://github.com/piurizza/cerebrum/releases/latest/download/install.sh | sh

It installs into `~/cerebrum-server`, generates the secrets, starts
Cerebrum at http://localhost:7811 and prints a one-time token: open the
page, choose **Register** and paste it as the **Invite token** to create
your account. It writes nothing outside that folder and refuses to run as
root.

To read the script first, download it, check that this repository's
release workflow built it, then run it:

    curl -fsSLO https://github.com/piurizza/cerebrum/releases/latest/download/install.sh
    gh attestation verify install.sh --owner piurizza
    sh install.sh

**To update**, run the same command again. It fetches the new release's
`compose.yaml`, pulls the images and restarts; your notes and `.env` are
never touched.

**Options** for a fresh install, set in front of `sh`, e.g.
`curl -fsSL <url> | CEREBRUM_PORT=7821 CEREBRUM_HTTPS_PORT=7822 sh`:

| Variable | Default | Meaning |
|---|---|---|
| `CEREBRUM_INSTALL_DIR` | `~/cerebrum-server` | where to install |
| `CEREBRUM_PORT` / `CEREBRUM_HTTPS_PORT` | `7811` / `7812` | HTTP and HTTPS ports |
| `CEREBRUM_BIND_ADDRESS` | `127.0.0.1` | `127.0.0.1` means this machine only; `0.0.0.0` or a LAN address lets your phone and other computers reach it |
| `CEREBRUM_TLS_SAN` | *(empty)* | extra HTTPS certificate names, e.g. `IP:192.168.1.14`, needed for offline mode on another device |

**From your phone or other computers:** by default Cerebrum answers only
on the machine it runs on. Pass `CEREBRUM_BIND_ADDRESS=0.0.0.0` and
`CEREBRUM_TLS_SAN=IP:<this machine's LAN address>` on the first install
(the HTTPS certificate is made once, at first start), then see
[Install on a phone](#install-on-a-phone-pwa).

**Windows** has no install script yet: follow
[Install by hand](#install-by-hand) in a terminal, with Docker Desktop.

## Install by hand

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

**Upgrading from 0.2 or earlier:** two defaults changed, so check `.env`
before running `docker compose up -d`:

- The ports moved from 8080/8443 to 7811/7812. To keep your old address,
  set `CEREBRUM_PORT=8080` and `CEREBRUM_HTTPS_PORT=8443`. If you
  installed Cerebrum on a phone, keep the old HTTPS port: the installed
  app and its offline copy belong to that exact address, port included.
- The ports now listen on this machine only. If you open Cerebrum from
  other devices, set `CEREBRUM_BIND_ADDRESS=0.0.0.0`.

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

### Accounts and the index

Accounts, sessions, and personal API tokens live in their own SQLite
database (`auth.sqlite3`), stored by default alongside the search index
under `<vault>/.cerebrum/` -- i.e. inside the same bind-mounted vault
directory above, not a separate volume. Anyone already backing up the vault
is already backing up accounts/sessions/tokens.

To keep both out of the vault (for example when the vault is a checkout
another tool owns), set `CEREBRUM_INDEX_PATH` and `CEREBRUM_AUTH_DB_PATH`
to paths under `/data/cerebrum` and enable the data mount in
`docker-compose.yml`. Back up that folder too: it holds the accounts. On an
existing install, move the accounts database first. Cerebrum refuses to
start if the variable points at a missing file while the old one is still
in the vault, because starting would create an empty accounts database and
make `AUTH_SETUP_TOKEN` work again for anyone who has it. With the default
folders (adjust `vault` and `data` if you changed
`CEREBRUM_VAULT_HOST_PATH` or `CEREBRUM_DATA_HOST_PATH`):

    docker compose down
    mkdir -p data                    # as yourself, so the backend can write
    mv vault/.cerebrum/auth.sqlite3* data/   # with its -wal and -shm files
    # uncomment the data mount in docker-compose.yml, then in .env:
    #   CEREBRUM_INDEX_PATH=/data/cerebrum/index.sqlite3
    #   CEREBRUM_AUTH_DB_PATH=/data/cerebrum/auth.sqlite3
    docker compose up -d

The index needs no moving: it is rebuilt from the notes on startup.

### Serve a read-only vault

Cerebrum can serve a vault another tool owns without ever writing to it:
a git checkout a cron job keeps pulled, a folder Syncthing or iCloud
syncs, an Obsidian vault edited elsewhere. People browse, search and see
the graph, and MCP agents can read it, but nobody can change it through
Cerebrum, and Cerebrum itself leaves no files behind (so a `git pull` into
the checkout never fails on changes Cerebrum made).

1. Move the index and accounts database out of the vault, as in
   [Accounts and the index](#accounts-and-the-index). Read-only mode
   refuses to start otherwise.
2. Set `CEREBRUM_VAULT_READ_ONLY=true` in `.env`, and optionally mount the
   vault read-only by changing its line in `docker-compose.yml` to end in
   `:/data/vault:ro`.
3. `docker compose up -d`.

For example, a checkout that a cron job updates every five minutes:

    */5 * * * * git -C /srv/team-notes pull --ff-only --quiet

To give people read-only access to a vault another Cerebrum instance
already writes to, run a second instance with its own folder for state.
If the main instance still keeps its accounts database in the vault,
create the second one's as an empty file first
(`touch data/auth.sqlite3` with the default data folder); otherwise startup reads the in-vault
database as one you forgot to move, and refuses.

What changes: the web app shows "This vault is read-only" and hides
Today, New note, Edit, Rename and Delete; the note-writing routes answer
403; MCP lists only its read tools. A rename that arrives with a pull is
indexed as a delete plus a create, so links in other notes stay exactly as
the owning tool wrote them. Accounts, sign-in and API tokens work as
usual.

The frontend also serves HTTPS on `https://localhost:7812` (override via
`CEREBRUM_HTTPS_PORT`), using a self-signed cert nginx generates on first
start. Offline mode (see [SPEC.md](SPEC.md#7-tech-stack)) needs this --
a service worker only registers in a secure context, which plain HTTP
only satisfies for `localhost`, not a LAN IP. To use offline mode from a
phone or another device on your network: set `CEREBRUM_BIND_ADDRESS=0.0.0.0`
and set `CEREBRUM_TLS_SAN` in your `.env` to your LAN IP
(e.g. `IP:192.168.1.14`) before first start, then
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

  Set `CEREBRUM_BIND_ADDRESS=0.0.0.0` in `.env` (and `docker compose up -d`)
  so other devices can reach the ports at all, then open
  `https://<name>.ts.net:7812` on the phone (any tailnet
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
looks for a server on the same computer (`http://localhost:7811`, where the
installer puts it) and connects without asking if one answers; otherwise it
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

## Links between notes

Type `[[` in the editor to link to another note. By default Cerebrum writes
standard markdown links (`[My note](my-note.md)`), which any markdown
viewer understands. It also reads Obsidian-style `[[wikilinks]]` (including
`[[note|shown text]]`, `[[note#heading]]` and image embeds like
`![[photo.png]]`), so a vault imported from Obsidian shows up linked in the
graph, backlinks and preview, and its links survive renames.

Hidden folders are skipped: notes under `.obsidian/`, `.trash/`, `.git/` or
any other dot-prefixed folder never show up in lists, search or the graph.

To have the editor and MCP agents *write* wikilinks too, set
`CEREBRUM_LINK_FORMAT=wikilink` in `.env` and restart. Existing links are
never converted. See [SPEC.md](SPEC.md#wikilinks) for how a wikilink picks
between notes with the same name.

## Sign in with an identity provider

Cerebrum can let people sign in with an OpenID Connect provider you already
run (Keycloak, Authentik, Pocket ID, ...) or with Google. The provider only
proves who someone is: Cerebrum keeps its own accounts, sessions and API
tokens, so MCP clients and the apps work as before.

1. At the provider, create a **confidential** client (client id + secret)
   for Cerebrum. Register one redirect URI for every address you open
   Cerebrum on, exactly, with no wildcards:
   `https://<host>:<port>/api/auth/oidc/callback` (for example both
   `https://192.168.1.14:7812/...` and
   `https://cerebrum.tail1234.ts.net:8443/...`).
2. In `.env`, set `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` and
   optionally `OIDC_PROVIDER_NAME` (the button says "Sign in with
   <name>"), then `docker compose up -d`.
   - Copy the issuer exactly as the provider shows it. Authentik's ends in
     `/`. A mismatch shows up as a failed sign-in and a log line with both
     values.
   - Keycloak: `https://<keycloak>/realms/<realm>`.
     Authentik: `https://<authentik>/application/o/<app-slug>/`.
     Pocket ID: `https://<pocket-id>`.
   - The backend container must reach the issuer URL too, not just your
     browser.
3. People get in two ways, never by matching email addresses:
   - **New people:** create an invite in Settings as usual. On the
     Register page they pick a username, paste the invite and press
     "Sign up with <name>". Their account has no password.
   - **Existing accounts:** sign in with your password, open Settings, and
     press "Link" under "Sign-in provider".

Optional:

- `OIDC_ADMIN_GROUP=<group>` makes members of that provider group admins
  and removes admin from everyone else, each time they sign in with the
  provider. Your provider has to put the groups in the ID token
  (`OIDC_GROUPS_CLAIM`, default `groups`; in Keycloak add a "Group
  Membership" mapper). Removing someone from the group takes effect at
  their next provider sign-in; to remove someone right away, deactivate
  their account in Settings.
- `AUTH_PASSWORD_LOGIN=false` makes the provider the way in: invites can
  only be redeemed through it, and anyone who has linked can no longer use
  a password. Admins always keep their password, so a provider outage
  never locks you out. Ask everyone to link first: accounts that haven't
  linked yet can still sign in with their password, so they can.

Keep `OIDC_ISSUER` stable. If you change provider or remove these settings,
accounts created through the provider can't sign in any more: they have no
password, and there is no way to give them one yet.

Known limits: on an iPhone, sign-in from the home-screen app opens the
provider in Safari and finishes there, not in the app, so use the site in
Safari. Google refuses sign-in from embedded browsers, which includes the
desktop app; self-hosted providers work there.

## MCP server

An MCP server is mounted at `/api/mcp`, reachable through the same
frontend-published port and nginx proxy as the REST API (no separate port).
Remote clients (e.g. Claude Desktop) can read, search, create, update,
append to, edit, and delete notes over it. The note-writing tools tell the
agent which link form this vault uses (see
[Links between notes](#links-between-notes)).

Every call is authenticated. Generate a personal API token in
**Settings** (it starts with `cbm_pat_`) and give it to your MCP client
as a bearer token. Tokens can be revoked from the same page, and a
deactivated account's tokens stop working immediately.

**If you expose this beyond your own machine, use HTTPS** -- the bundled
`https://` port (see [Install by hand](#install-by-hand)) or a
Tailscale / reverse-proxy setup (see [Install on a phone](#install-on-a-phone-pwa)),
so the token never travels in plain text.

## License

[MIT](LICENSE)
