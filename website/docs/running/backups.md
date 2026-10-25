# Backups

Back up two things: the **vault folder** and the **`.env` file**. With the
install script, both are in `~/cerebrum-server`.

| What | Where | Why |
|---|---|---|
| Your notes and images | `vault/` | They are the notes. |
| The accounts database | `vault/.cerebrum/auth.sqlite3` | Accounts, password hashes, sessions, API tokens and invites. It can't be rebuilt. |
| Settings and secrets | `.env` | Holds `AUTH_JWT_SECRET` and `AUTH_SETUP_TOKEN`. |
| The search index | `vault/.cerebrum/index.sqlite3` | Optional: Cerebrum rebuilds it from the notes on every start. |

If you moved Cerebrum's state out of the vault
(`CEREBRUM_AUTH_DB_PATH`), back up that folder too; by default it's `data/`.

!!! warning "Keep backups private"
    The accounts database and `.env` hold login secrets. Store copies where
    only you can read them.

## Taking a backup

The notes are plain files, so any backup tool works on them. For a consistent
copy of the accounts database, stop the backend for the moment of the copy.
For example, in the install folder:

```sh
docker compose stop backend
tar -czf ~/cerebrum-backup-$(date +%F).tar.gz .env vault
docker compose start backend
```

Copying while Cerebrum runs is usually fine for the notes, but the accounts
database may be caught mid-write.

## Restoring

1. Stop Cerebrum: `docker compose down`.
2. Put the vault folder back, **including** `vault/.cerebrum/auth.sqlite3`,
   and put `.env` back.
3. Start Cerebrum: `docker compose up -d`. It rebuilds the search index from
   the notes.

Restore the accounts database **before** starting. If Cerebrum starts with no
accounts database, it creates an empty one, and the setup token in `.env`
works again for whoever has it.

## Moving to another server

Install Cerebrum on the new server, stop it, copy the vault folder and `.env`
over the new ones, and start it.

- If your user id differs on the new server, update `CEREBRUM_UID` and
  `CEREBRUM_GID` in `.env` (`id -u` and `id -g` print them), so Cerebrum can
  write to the vault.
- Keep the same HTTPS address if you can: the phone app belongs to its
  address.
