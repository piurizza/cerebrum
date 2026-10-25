# Troubleshooting

Most problems show up in the server's log. In the install folder:

```sh
docker compose ps
docker compose logs --tail 50 backend
```

## Installing and starting

### The install script says a port is in use

Another program uses 7811 or 7812. Run the installer again with two free
ports:

```sh
curl -fsSL https://github.com/piurizza/cerebrum/releases/latest/download/install.sh \
  | CEREBRUM_PORT=7821 CEREBRUM_HTTPS_PORT=7822 sh
```

On an existing install, change them in `.env` and run the installer again.

### "Permission denied" on the vault, or notes can't be saved

The vault folder belongs to root, usually because Docker created it when it was
missing. Give it back to your user, then restart:

```sh
sudo chown -R "$(id -u):$(id -g)" vault
docker compose restart backend
```

If `id -u` isn't 1000, also set `CEREBRUM_UID` and `CEREBRUM_GID` in `.env`.

### It refuses to start: the accounts database

If you set `CEREBRUM_AUTH_DB_PATH`, Cerebrum refuses to start while that file
is missing and an accounts database is still in the vault. Starting would
create an empty one and make the setup token work again. Move the file as
described in
[Move Cerebrum's state out of the vault](../running/read-only-and-second-instance.md#move-cerebrums-state-out-of-the-vault).

### It refuses to start in read-only mode

Read-only mode needs the index and the accounts database outside the vault.
Set `CEREBRUM_INDEX_PATH` and `CEREBRUM_AUTH_DB_PATH` as described in
[Read-only vault](../running/read-only-and-second-instance.md#turn-on-read-only-mode).

### The install script times out waiting for Cerebrum

It prints the backend's last log lines. A first start on a slow machine, or a
large vault being indexed, can take longer than the wait; run the installer
again. If the log shows an error, fix it, then run the installer again: it
keeps your `.env` and notes.

## Signing in

### I lost the setup token

It's `AUTH_SETUP_TOKEN` in `.env`, and it only works before the first account
exists.

### Locked out of the only admin account

After 5 wrong passwords, an account is locked for 15 minutes; wait and try
again. If the password is lost, there is no reset yet. You can start the
accounts over, which keeps every note but removes every account, session and
API token:

```sh
docker compose down
mv vault/.cerebrum/auth.sqlite3 vault/.cerebrum/auth.sqlite3.old
rm -f vault/.cerebrum/auth.sqlite3-wal vault/.cerebrum/auth.sqlite3-shm
docker compose up -d
```

If you moved Cerebrum's state out of the vault, the file is
`data/auth.sqlite3` instead: move that one aside, and create an empty
`data/auth.sqlite3` in its place (`touch data/auth.sqlite3`) before starting,
since Cerebrum refuses to start when that setting points at a missing file.

Then register again with the setup token from `.env`, and invite everyone
again.

### Signing in works, but I'm signed out on every reload

The session cookie isn't being kept. If `AUTH_COOKIE_SECURE=true`, sign in over
`https://`, not `http://`. Behind a reverse proxy, make sure it passes cookies
and the `/api/` path through unchanged.

### Sign-in with my identity provider fails

- **"redirect_uri" errors at the provider:** register the exact return
  address for every address you open Cerebrum on, port included:
  `https://<host>:<port>/api/auth/oidc/callback`.
- **Behind Tailscale serve or a reverse proxy,** provider sign-in doesn't work
  yet; see
  [Known limits](../running/identity-provider.md#known-limits).
- **An issuer mismatch** shows in the backend log with both values. Copy the
  issuer exactly as the provider shows it, including any trailing `/`.
- **The server can't reach the provider:** the Cerebrum server, not just your
  browser, must reach the issuer address.

## Phone and offline

### The phone doesn't offer to install the app

Phones install only from an address with a certificate they trust. Accepting a
"not secure" warning isn't enough. Use Tailscale or a domain with a real
certificate; see [HTTPS](../running/https.md).

### The app stopped working after I changed the port or address

The installed app belongs to its exact address, port included. Remove it and
install it again from the new address.

### Diagrams don't show offline

Diagrams are drawn by a component that's downloaded the first time you view
one. View a diagram once while online.

## Certificates

### The Tailscale certificate expired

Certificates from `tailscale cert` last 90 days. Fetch a new one and copy it in,
as in
[Tailscale certificate on the built-in HTTPS port](../running/https.md#tailscale-certificate-on-the-built-in-https-port).
`tailscale serve` renews on its own.

### The built-in certificate has the wrong address

The self-signed certificate is made once, at the first start. To make a new
one, see
[Built-in self-signed certificate](../running/https.md#built-in-self-signed-certificate).

## Notes and the index

### Changes made outside Cerebrum don't show up

- Reload the page, or switch back to the window: an open window refreshes its
  note list when it comes back into focus.
- On Docker Desktop for macOS or Windows, file change events don't reach the
  container reliably. Set `WATCHFILES_FORCE_POLLING=1` in `.env` and run
  `docker compose up -d`.
- A full rescan runs every 5 minutes regardless
  (`WATCHER_BACKSTOP_INTERVAL_SECONDS`).
- Files in folders whose name starts with a dot are ignored on purpose.

### Search or the graph looks wrong

The index is rebuilt from the notes on every start, so a restart fixes a stale
index: `docker compose restart backend`.

### A link or image doesn't work

If its file name contains spaces, see
[Links](../features/links.md#known-limits).

## Desktop app

### It can't find the server

Check the address under **Change server URL**, and that the server answers in
a browser on the same computer. The desktop app needs the address including
`http://` or `https://` and the port.
