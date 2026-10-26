# Upgrade

New releases are listed on the
[releases page](https://github.com/piurizza/cerebrum/releases). Before
upgrading, read the [upgrade notes](../upgrade/index.md) for every release
between yours and the new one: they list anything you need to change.

Your notes are never changed by an upgrade. The search index is rebuilt from
them when Cerebrum starts, so an upgrade can take a moment longer than a normal
restart on a large vault.

## Find your version

The images carry their release number. In the install folder, ask the running
backend:

```sh
docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' \
  "$(docker compose ps -q backend)"
```

## Upgrade an install-script install

Run the install command again:

```sh
curl -fsSL https://github.com/piurizza/cerebrum/releases/latest/download/install.sh | sh
```

It replaces `compose.yaml` with the new release's copy, pulls the images and
restarts. It never touches `.env` or your notes.

- If you installed into another folder, put the same
  `CEREBRUM_INSTALL_DIR=...` in front of `sh`.
- If `.env` has a `CEREBRUM_VERSION` line, for example after going back to an
  older release, delete it first. Otherwise Cerebrum stays on that version.

## Upgrade a hand install

In the folder with `docker-compose.yml`:

```sh
git pull
docker compose pull
docker compose up -d
```

`git pull` brings the new release's Compose file. If you set
`CEREBRUM_VERSION` in `.env`, change it to the new version first.

## Go back to an older release

Set `CEREBRUM_VERSION` in `.env` to the older version and run
`docker compose up -d`. Check that release's upgrade notes: a release that
moved where Cerebrum keeps its state needs that step undone too.

!!! warning "Going back to 0.4.0 or older"
    Releases before 0.5.0 don't know `CEREBRUM_AUTH_DB_PATH` or
    `CEREBRUM_VAULT_READ_ONLY`. If you moved Cerebrum's state out of the
    vault, move `data/auth.sqlite3` (with its `-wal` and `-shm` files) back to
    `vault/.cerebrum/` before going back, or the older release starts with no
    accounts. Don't go back on a read-only instance: an older release would
    write to the vault.

## Upgrade the apps

- **Phone app and browser:** pick up the new version on their own. When it's
  ready, Cerebrum shows "A new version is available" with a **Reload** button.
- **Desktop app:** install the new release's package; see
  [Desktop app](desktop.md).
