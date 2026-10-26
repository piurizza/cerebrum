# Configuration

Cerebrum is configured with environment variables. With Docker, set them in
the `.env` file next to the Compose file (`compose.yaml` for the install
script, `docker-compose.yml` for a hand install) and restart with
`docker compose up -d`. Running the backend by
hand, set them in `backend/.env`.

The **Docker `.env`** column says whether a variable takes effect from
Docker's `.env`. Variables marked *no* are not passed into the container by
`docker-compose.yml`; to change one there, add it under the backend's
`environment:` in a `docker-compose.override.yml`.

This is the one list of every variable.

## Vault and notes

| Variable | Default | Docker `.env` | What it does |
|---|---|---|---|
| `CEREBRUM_VAULT_PATH` | `./vault` (`/data/vault` in Docker) | no | Folder of `.md` notes, as the backend sees it. In Docker this is the mounted `/data/vault`; you set the host folder with `CEREBRUM_VAULT_HOST_PATH` instead. |
| `CEREBRUM_VAULT_HOST_PATH` | `./vault` | yes | Host folder mounted into the container as the vault. |
| `CEREBRUM_VAULT_READ_ONLY` | `false` | yes | `true` serves the vault without ever writing to it. See [Read-only vault](../running/read-only-and-second-instance.md). |
| `CEREBRUM_DAILY_NOTE_FOLDER` | `daily` | yes | Vault folder the **Today** button creates daily notes in. Applied on restart. |
| `CEREBRUM_TEMPLATES_FOLDER` | `templates` | yes | Vault folder that holds note templates. Applied on restart. |
| `CEREBRUM_LINK_FORMAT` | `markdown` | yes | `markdown` or `wikilink`: the link form the editor inserts and agents are asked to write. Both forms are always read. |
| `CEREBRUM_TIMEZONE` | *(unset)* | yes | IANA time zone, such as `Europe/Rome`, whose today the MCP task tools use when an agent gives no date. Unset means the server's zone, which is UTC in Docker. The web app uses the device's date. |
| `VITE_DAILY_NOTE_FOLDER` | *(unset)* | yes | Older name for `CEREBRUM_DAILY_NOTE_FOLDER`, still read as a fallback. |
| `VITE_TEMPLATES_FOLDER` | *(unset)* | yes | Older name for `CEREBRUM_TEMPLATES_FOLDER`, still read as a fallback. |
| `MAX_ATTACHMENT_SIZE_BYTES` | `10000000` | yes | Largest image, in bytes, that can be pasted into a note. In Docker, the bundled web server follows it. |

## State outside the vault

| Variable | Default | Docker `.env` | What it does |
|---|---|---|---|
| `CEREBRUM_INDEX_PATH` | `<vault>/.cerebrum/index.sqlite3` | yes | Where the search and link index lives. Blank means the default. Required outside the vault for a read-only vault. |
| `CEREBRUM_AUTH_DB_PATH` | `<vault>/.cerebrum/auth.sqlite3` | yes | Where the accounts database (accounts, sessions, API tokens) lives. Blank means the default. Move the existing file before changing it, or Cerebrum starts with an empty one. |
| `CEREBRUM_DATA_HOST_PATH` | `./data` | yes | Host folder for the optional `/data/cerebrum` mount that holds the two files above when they live outside the vault. |

## Accounts and sign-in

| Variable | Default | Docker `.env` | What it does |
|---|---|---|---|
| `AUTH_JWT_SECRET` | *(required)* | yes | Secret that signs session tokens. At least 32 characters; the install script generates one. |
| `AUTH_SETUP_TOKEN` | *(required)* | yes | One-time invite token for the first account, which becomes the admin. |
| `AUTH_ACCESS_TOKEN_TTL_MINUTES` | `10` | yes | How long an access token lasts, in minutes. |
| `AUTH_REFRESH_TOKEN_TTL_DAYS` | `30` | yes | How long a session lasts without signing in again, in days. |
| `AUTH_COOKIE_SECURE` | `false` | yes | Marks the session cookie as HTTPS-only. Turn on once Cerebrum is served only over HTTPS. |
| `AUTH_PASSWORD_LOGIN` | `true` | yes | `false` turns off password registration, and password sign-in for non-admins who have linked a provider. Admins always keep their password. Needs a provider configured. |
| `OIDC_ISSUER` | *(unset)* | yes | Issuer URL of an OpenID Connect provider. Set it with `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET` to turn on sign-in with the provider. |
| `OIDC_CLIENT_ID` | *(unset)* | yes | Client ID registered at the provider. |
| `OIDC_CLIENT_SECRET` | *(unset)* | yes | Client secret registered at the provider. |
| `OIDC_PROVIDER_NAME` | `SSO` | yes | Name on the sign-in button: "Sign in with *name*". |
| `OIDC_SCOPES` | `openid profile email` | yes | Scopes requested from the provider; `openid` is always added. |
| `OIDC_ADMIN_GROUP` | *(unset)* | yes | Provider group whose members are admins, updated at each provider sign-in. |
| `OIDC_GROUPS_CLAIM` | `groups` | yes | Token claim that lists the user's groups. |
| `OIDC_ALLOW_INSECURE_ISSUER` | `false` | yes | Accepts an `http://` issuer on any host. For test setups only. |

## Network and ports

| Variable | Default | Docker `.env` | What it does |
|---|---|---|---|
| `CEREBRUM_PORT` | `7811` | yes | Host port for the web app over HTTP. |
| `CEREBRUM_HTTPS_PORT` | `7812` | yes | Host port for the web app over HTTPS, with a self-signed certificate. |
| `CEREBRUM_BIND_ADDRESS` | `127.0.0.1` | yes | Network interface both ports listen on. The default is this machine only; `0.0.0.0` makes Cerebrum reachable by every device on your network, over plain HTTP too. |
| `CEREBRUM_TLS_SAN` | *(unset)* | yes | Extra names for the self-signed certificate, comma-separated, for example `IP:192.0.2.10,DNS:notes.example.lan`. |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | no | Web origins allowed to call the API from a browser. Only needed for development. |
| `MCP_ENABLED` | `true` | yes | Serves the MCP endpoint for agents at `/api/mcp`. |

## Index and file watching

| Variable | Default | Docker `.env` | What it does |
|---|---|---|---|
| `WATCHER_ENABLED` | `true` | yes | Watches the vault for changes made outside Cerebrum and keeps the index current. |
| `WATCHER_DEBOUNCE_MS` | `400` | yes | How long, in milliseconds, to collect file changes before indexing them. |
| `WATCHER_BACKSTOP_INTERVAL_SECONDS` | `300` | yes | How often, in seconds, a full rescan catches anything the watcher missed. |
| `WATCHER_RENAME_PAIRING_WINDOW_SECONDS` | `30` | yes | How long, in seconds, a deleted note is remembered so a later re-creation counts as a rename. |
| `WATCHFILES_FORCE_POLLING` | *(unset)* | yes | Polls the vault instead of using file system events. Turn on for Docker Desktop on macOS or Windows, and for network file systems. |

## Install and containers

| Variable | Default | Docker `.env` | What it does |
|---|---|---|---|
| `CEREBRUM_VERSION` | `latest` | yes | Image tag Compose runs. The install script pins it to the installed release. |
| `CEREBRUM_UID` | `1000` | yes | User ID the backend runs as, so files it writes in the vault belong to you. |
| `CEREBRUM_GID` | `1000` | yes | Group ID the backend runs as. |
| `CEREBRUM_INSTALL_DIR` | `~/cerebrum-server` | no | Install script only: the folder it installs into. |

## Application

| Variable | Default | Docker `.env` | What it does |
|---|---|---|---|
| `APP_ENV` | `development` (`production` in Docker) | no | Not used yet: the backend does not read it. |
| `APP_NAME` | `Cerebrum` | no | The name the server reports in its health check and to MCP clients. |
| `LOG_LEVEL` | `INFO` | yes | How much the backend logs: `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` (case is ignored). Anything else fails startup. |

## Build-time (developers)

These are read when the web or desktop app is built, not at runtime.

| Variable | Default | Docker `.env` | What it does |
|---|---|---|---|
| `VITE_API_BASE_URL` | *(unset)* | no | API address for a web build that is not served behind the bundled proxy. |
| `VITE_DEFAULT_SERVER_URL` | `http://localhost:7811` | no | Server the desktop app connects to on first launch. Users can change it in the app. |
