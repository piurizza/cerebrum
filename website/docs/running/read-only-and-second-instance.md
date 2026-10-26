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

Only the accounts database moves: the index is rebuilt from the notes, but its
new path still has to be set in step 2. Back up `data/` from now on; see
[Backups](backups.md).

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
run a second Cerebrum over the same vault folder in read-only mode. It has its
own folder for state, its own ports, its own accounts and its **own secrets**:
with the same `AUTH_JWT_SECRET`, a sign-in on one instance would be accepted by
the other, as whichever account has the same number there.

1. Install it with the install script, in its own folder and on its own ports.
   Don't register an account yet.

    ```sh
    curl -fsSL https://github.com/piurizza/cerebrum/releases/latest/download/install.sh \
      | CEREBRUM_INSTALL_DIR=~/cerebrum-readonly CEREBRUM_PORT=7821 CEREBRUM_HTTPS_PORT=7822 sh
    ```

    The script generates new secrets for it. Never copy the main instance's
    `.env`.

2. Stop it and create its state folder:

    ```sh
    cd ~/cerebrum-readonly
    docker compose down
    mkdir -p data
    ```

3. If the main instance keeps its accounts database in the vault (the
   default), create this instance's as an empty file, or it refuses to start:

    ```sh
    touch data/auth.sqlite3
    ```

4. Add the data mount in `~/cerebrum-readonly/compose.override.yaml`, as in
   [Move Cerebrum's state out of the vault](#move-cerebrums-state-out-of-the-vault).

5. In `~/cerebrum-readonly/.env`, point it at the main vault and turn on
   read-only mode:

    ```sh
    CEREBRUM_VAULT_HOST_PATH=/home/<you>/cerebrum-server/vault
    CEREBRUM_INDEX_PATH=/data/cerebrum/index.sqlite3
    CEREBRUM_AUTH_DB_PATH=/data/cerebrum/auth.sqlite3
    CEREBRUM_VAULT_READ_ONLY=true
    ```

    Use the main vault's full path.

6. Start it with `docker compose up -d`, open it on its own port, and register
   with this instance's own `AUTH_SETUP_TOKEN` from its `.env`.

To upgrade it later, run the install command again with the same
`CEREBRUM_INSTALL_DIR=~/cerebrum-readonly` in front of `sh`.

Read-only access is per instance: there are no read-only accounts or API
tokens on a writable vault.
