# Upgrade

New releases are listed on the
[releases page](https://github.com/piurizza/cerebrum/releases). Before
upgrading, read the [upgrade notes](../upgrade/index.md) for every release
between yours and the new one: they list anything you need to change.

Your notes are never changed by an upgrade. The search index is rebuilt from
them when Cerebrum starts, so an upgrade can take a moment longer than a normal
restart on a large vault.

## Find your version

The images carry their release number:

```sh
docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' \
  ghcr.io/piurizza/cerebrum-backend:latest
```

If you pinned a release with `CEREBRUM_VERSION` in `.env`, that is your
version, and the image tag to use instead of `latest`.

## Upgrade an install-script install

Run the install command again:

```sh
curl -fsSL https://github.com/piurizza/cerebrum/releases/latest/download/install.sh | sh
```

It replaces `compose.yaml` with the new release's copy, pulls the images and
restarts. It never touches `.env` or your notes.

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

## Upgrade the apps

- **Phone app and browser:** pick up the new version on their own. When it's
  ready, Cerebrum shows "A new version is available" with a **Reload** button.
- **Desktop app:** install the new release's package; see
  [Desktop app](desktop.md).
