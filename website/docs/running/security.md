# Security

This page describes what Cerebrum's security-related settings do, so you can
choose a setup that fits your network. Whether a setup is safe enough depends
on your network and on who can reach the server.

## Who can reach Cerebrum

| Setting | Effect |
|---|---|
| `CEREBRUM_BIND_ADDRESS=127.0.0.1` (default) | Both ports answer only on the server itself. Other devices need something in between, such as [Tailscale serve](https.md#tailscale-serve) or a reverse proxy. |
| `CEREBRUM_BIND_ADDRESS=0.0.0.0` | Both ports answer on every network the server is connected to. Anyone on those networks sees the sign-in page and the MCP endpoint. A host firewall such as ufw doesn't block ports Docker publishes; to narrow access, bind to one address instead. |
| `CEREBRUM_BIND_ADDRESS=<one address>` | The ports answer only on that address, for example the server's tailnet address. |
| A reverse proxy reachable from the internet | Cerebrum is on the internet too: its sign-in page, registration and MCP endpoint. Anyone who knows a username can keep that account locked by failing to sign in. |

Plain HTTP on port 7811 sends passwords and API tokens unencrypted. Use HTTPS
whenever Cerebrum is reached over a network; see [HTTPS](https.md).

## Accounts and sessions

- New accounts need an invite from an admin; the first account needs the setup
  token from `.env`. See [Accounts and invites](accounts.md).
- Passwords are stored as Argon2 hashes. After 5 wrong passwords in a row, an
  account is locked for 15 minutes.
- Signing in gives the browser a short-lived access token, kept in memory
  (10 minutes, `AUTH_ACCESS_TOKEN_TTL_MINUTES`), and a session cookie
  (30 days, `AUTH_REFRESH_TOKEN_TTL_DAYS`). The cookie is `HttpOnly` and
  replaced on each use; reusing an old one ends the whole session.
- `AUTH_COOKIE_SECURE=true` makes browsers send the session cookie only over
  HTTPS. Turn it on once every sign-in goes over HTTPS; with it on, signing in
  over plain `http://` stops working.
- Deactivating an account in **Settings** ends its sessions and API tokens at
  once.

## API tokens and MCP

- A personal API token can do anything its account can do through the API,
  except link a sign-in provider: read and change notes, create more tokens
  and, for an admin, create invites and deactivate accounts. Treat it like a
  password. Cerebrum stores only a hash of each.
- Give assistants a token from an account that isn't an admin, and create one
  token per assistant or script, so you can revoke them one at a time.
- If a token leaks, revoke it in **Settings**, then check **Personal API
  tokens** and the accounts list for anything it created.
- The MCP endpoint, `/api/mcp`, needs a bearer token: a personal API token,
  which is what assistants use, or a signed-in browser's short-lived access
  token. `MCP_ENABLED=false` turns it off.
- Anything that can write notes, an account or an AI assistant, can put any
  text in them. Cerebrum treats note content as untrusted when it shows it:
  diagrams are drawn in a restricted mode and cleaned before display.
- An assistant acts on what it reads, including instructions written into
  notes. For an assistant that only needs to read, connect it to a
  [read-only instance](read-only-and-second-instance.md), and keep
  [backups](backups.md).

## Secrets

- `AUTH_JWT_SECRET` signs access tokens. Anyone who has it can sign in as any
  account, so keep it long, random and private; the install script generates
  one.
- `AUTH_SETUP_TOKEN` creates the first account. It stops working once an
  account exists, but works again if the accounts database is ever lost.
- `.env` and the accounts database hold these secrets and the password
  hashes. Keep them, and their backups, readable only by you.
- By default the accounts database is inside the vault, in `.cerebrum/`. If
  another tool syncs or commits the vault, exclude `.cerebrum/` from it (for
  example in `.gitignore` or `.stignore`), or
  [move Cerebrum's state out of the vault](read-only-and-second-instance.md#move-cerebrums-state-out-of-the-vault).

### If a secret leaks

If `.env` or a backup gets out, replace `AUTH_JWT_SECRET` and
`AUTH_SETUP_TOKEN` with new random values (`openssl rand -hex 32`), and create
a new `OIDC_CLIENT_SECRET` at your identity provider if you use one. Restart
with `docker compose up -d`, then check each account's API tokens and the
accounts list.

## Images and the vault

The server only serves files inside a note's `.attachments/` folder, or images
elsewhere in the vault outside hidden folders. It never serves its own
databases, files in hidden folders, or anything outside the vault.

## Reporting a security problem

Please report security problems privately through
[GitHub's security advisories](https://github.com/piurizza/cerebrum/security/advisories/new),
not in a public issue.
