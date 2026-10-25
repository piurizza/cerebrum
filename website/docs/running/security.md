# Security

This page describes what Cerebrum's security-related settings do, so you can
choose a setup that fits your network. Whether a setup is safe enough depends
on your network and on who can reach the server.

## Who can reach Cerebrum

| Setting | Effect |
|---|---|
| `CEREBRUM_BIND_ADDRESS=127.0.0.1` (default) | Both ports answer only on the server itself. Other devices need something in between, such as [Tailscale serve](https.md#tailscale-serve) or a reverse proxy. |
| `CEREBRUM_BIND_ADDRESS=0.0.0.0` | Both ports answer on every network the server is connected to. Anyone on those networks sees the sign-in page and the MCP endpoint. |
| `CEREBRUM_BIND_ADDRESS=<one address>` | The ports answer only on that address, for example the server's tailnet address. |

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

- Personal API tokens give full access to the account's notes, like a
  password. Create one per assistant or script, so you can revoke them one at
  a time. Cerebrum stores only a hash of each.
- The MCP endpoint, `/api/mcp`, accepts API tokens only. `MCP_ENABLED=false`
  turns it off.
- Anything that can write notes, an account or an AI assistant, can put any
  text in them. Cerebrum treats note content as untrusted when it shows it:
  diagrams are drawn in a restricted mode and cleaned before display.

## Secrets

- `AUTH_JWT_SECRET` signs access tokens. Keep it long and random; the install
  script generates one. Changing it ends current access tokens, and browsers
  get new ones from their session cookie.
- `AUTH_SETUP_TOKEN` creates the first account. It stops working once an
  account exists, but works again if the accounts database is ever lost, so
  keep it secret too.
- `.env` and the accounts database hold these secrets and the password
  hashes. Keep them, and their backups, readable only by you.

## Images and the vault

The server only serves files inside a note's `.attachments/` folder, or images
elsewhere in the vault outside hidden folders. It never serves its own
databases, files in hidden folders, or anything outside the vault.

## Reporting a security problem

Please report security problems privately through
[GitHub's security advisories](https://github.com/piurizza/cerebrum/security/advisories/new),
not in a public issue.
