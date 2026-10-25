# Read-only vault and a second instance

Cerebrum can serve a vault that another tool owns without ever writing to it:
a git repository a cron job keeps up to date, a folder Syncthing or iCloud
syncs, an Obsidian vault edited elsewhere. People browse, search and see the
graph, and AI assistants can read it, but nobody can change it through
Cerebrum. Cerebrum leaves no files in the vault either, so a `git pull` into
it never fails on changes Cerebrum made.

## Move Cerebrum's state out of the vault

By default Cerebrum keeps its search index and accounts database in
`vault/.cerebrum/`. Read-only mode needs both outside the vault, and you may
want that anyway, for example when the vault is a git repository.

On an **existing** install, move the accounts database first, or Cerebrum
starts with an empty one. It refuses to start when the setting points at a
missing file while the old one is still in the vault. In the install folder:

```sh
docker compose down
mkdir -p data                               # as yourself, so Cerebrum can write
mv vault/.cerebrum/auth.sqlite3* data/      # with its -wal and -shm files
```

Then:

1. Add the data mount in an override file next to the Compose file, so
   updates don't overwrite it: `compose.override.yaml` for an install-script
   install, `docker-compose.override.yml` for a hand install.

    ```yaml
    services:
      backend:
        volumes:
          - ${CEREBRUM_DATA_HOST_PATH:-./data}:/data/cerebrum
    ```

    Docker Compose reads the override file on its own, and so does the
    install script when it updates.

2. In `.env`:

    ```sh
    CEREBRUM_INDEX_PATH=/data/cerebrum/index.sqlite3
    CEREBRUM_AUTH_DB_PATH=/data/cerebrum/auth.sqlite3
    ```

3. `docker compose up -d`.

The index needs no moving: it is rebuilt from the notes. Back up `data/` from
now on; see [Backups](backups.md).

## Turn on read-only mode

1. Move the state out of the vault, as above.
2. Set `CEREBRUM_VAULT_READ_ONLY=true` in `.env`.
3. Optionally, mount the vault read-only too. In the same override file,
   under the backend:

    ```yaml
        volumes:
          - ${CEREBRUM_DATA_HOST_PATH:-./data}:/data/cerebrum
          - ${CEREBRUM_VAULT_HOST_PATH:-./vault}:/data/vault:ro
    ```
4. `docker compose up -d`.

For example, a vault that a cron job updates from git every five minutes:

```sh
*/5 * * * * git -C /srv/team-notes pull --ff-only --quiet
```

What changes:

- the web app shows "This vault is read-only" and hides **Today**,
  **+ New note**, **Edit**, **Rename** and **Delete**;
- the note-writing parts of the API answer 403;
- [MCP](../agents/mcp-tools.md) offers only its reading tools;
- a rename that arrives with a pull is indexed as a delete plus a new note, so
  links in other notes stay exactly as the owning tool wrote them;
- accounts, sign-in and API tokens work as usual.

## A read-only second instance

To give people read-only access to a vault that your main Cerebrum writes to,
run a second instance over the same vault folder, in read-only mode, with its
own folder for state, its own ports and its own accounts.

If the main instance still keeps its accounts database in the vault, create
the second instance's as an empty file first, for example
`touch data/auth.sqlite3`. Otherwise it reads the database in the vault as one
you forgot to move, and refuses to start.

Read-only access is per instance: there are no read-only accounts or API
tokens on a writable vault yet.
