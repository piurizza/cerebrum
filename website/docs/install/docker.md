# Install with the script

On Linux or macOS, with Docker running, one command installs and starts
Cerebrum:

```sh
curl -fsSL https://github.com/piurizza/cerebrum/releases/latest/download/install.sh | sh
```

What it does:

- installs into `~/cerebrum-server`, and writes nothing outside that folder;
- refuses to run as root, and checks that Docker is running and the ports are
  free;
- writes `.env` with two generated secrets, readable only by you, and creates
  the `vault` folder for your notes;
- downloads the release's `compose.yaml`, pulls the images, starts Cerebrum
  and waits until it answers;
- prints a one-time **invite token** for the first account.

Then open `http://localhost:7811`, choose **Register** and paste the token as
the **Invite token**. That first account is the admin.

## Check the script before running it

Each release's install script carries a build attestation from this project's
release workflow. To read and verify it before running:

```sh
curl -fsSLO https://github.com/piurizza/cerebrum/releases/latest/download/install.sh
gh attestation verify install.sh --owner piurizza
sh install.sh
```

## Options

Set these in front of `sh` on the first install. For example:

```sh
curl -fsSL https://github.com/piurizza/cerebrum/releases/latest/download/install.sh \
  | CEREBRUM_PORT=7821 CEREBRUM_HTTPS_PORT=7822 sh
```

| Variable | Default | Meaning |
|---|---|---|
| `CEREBRUM_INSTALL_DIR` | `~/cerebrum-server` | Where to install. |
| `CEREBRUM_PORT` | `7811` | HTTP port. |
| `CEREBRUM_HTTPS_PORT` | `7812` | HTTPS port. |
| `CEREBRUM_BIND_ADDRESS` | `127.0.0.1` | `127.0.0.1` answers on this machine only. `0.0.0.0`, or one of the machine's addresses, lets phones and other computers connect directly. |
| `CEREBRUM_TLS_SAN` | empty | Extra names for the built-in HTTPS certificate, for example `IP:192.0.2.10`. See [HTTPS](../running/https.md). |

These go into `.env`. To change them later, edit
`~/cerebrum-server/.env` and run `docker compose up -d` in that folder. Every
other setting is listed in [Configuration](../reference/configuration.md).

## What's in the folder

| Path | What it is |
|---|---|
| `compose.yaml` | The release's Compose file. Replaced on every update; don't edit it. |
| `.env` | Your settings and secrets. Never touched by updates. |
| `vault/` | Your notes, as `.md` files. |
| `vault/.cerebrum/` | The search index and the accounts database. |

Back up `.env` and `vault/`; see [Backups](../running/backups.md).

## Reach it from other devices

By default Cerebrum answers only on the server itself. To use it from your
phone or another computer, either:

- put it behind HTTPS with Tailscale or a reverse proxy, keeping the default
  `127.0.0.1` (recommended; see [HTTPS](../running/https.md)), or
- open the ports to your network: set `CEREBRUM_BIND_ADDRESS=0.0.0.0` and
  `CEREBRUM_TLS_SAN=IP:<the server's address>` on the first install. The
  HTTPS certificate is made once, at the first start.

Anyone who can reach those ports sees the sign-in page and the MCP endpoint, so
open them only on networks you trust. See [Security](../running/security.md).

## Updating

Run the same command again. It downloads the new release's `compose.yaml`,
pulls the images and restarts. Your notes and `.env` are never touched. Read
the [upgrade notes](../upgrade/index.md) first.

## Windows

There is no install script for Windows yet. Follow
[Install by hand](by-hand.md) with Docker Desktop.
