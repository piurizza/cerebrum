# Install by hand

Each release publishes prebuilt images to GitHub's container registry
(`ghcr.io/piurizza/cerebrum-backend` and `ghcr.io/piurizza/cerebrum-frontend`).
Running them needs only Docker with Compose: no Node, no Python and no build.
This works on Linux, macOS and Windows.

## Install

```sh
git clone https://github.com/piurizza/cerebrum.git
cd cerebrum
cp .env.example .env
```

Edit `.env` and set the two secrets, each to a long random string. One way to
make one: `openssl rand -hex 32`.

- `AUTH_JWT_SECRET` signs every sign-in.
- `AUTH_SETUP_TOKEN` is the invite token for the first account.

Then create the notes folder and start Cerebrum:

```sh
mkdir -p vault
docker compose pull
docker compose up -d
```

Open `http://localhost:7811`, choose **Register** and paste `AUTH_SETUP_TOKEN`
as the **Invite token**.

!!! warning "Create the `vault` folder yourself"
    If it's missing, Docker creates it owned by root, and Cerebrum can't write
    to it.

## Who owns the files

The backend runs as user and group 1000, not root, so notes it writes belong
to you on the host. If `id -u` prints something other than 1000, set
`CEREBRUM_UID` and `CEREBRUM_GID` in `.env`.

If an older version of Cerebrum ran as root on native Linux Docker, give the
vault back to your user once:

```sh
sudo chown -R "$(id -u):$(id -g)" vault
```

## Where things live

- Notes are a bind mount of `./vault`. To keep them elsewhere, set
  `CEREBRUM_VAULT_HOST_PATH` in `.env`.
- The search index and the accounts database live in `vault/.cerebrum/`.
  To keep them out of the notes folder, see
  [Read-only vault and a second instance](../running/read-only-and-second-instance.md#move-cerebrums-state-out-of-the-vault).
- The built-in HTTPS certificate lives in a Docker volume.

## Updating

```sh
docker compose pull
docker compose up -d
```

That moves to the latest release. To stay on one release, set
`CEREBRUM_VERSION=0.4.0` (for example) in `.env`. Read the
[upgrade notes](../upgrade/index.md) first.

## Verify the images

Each image carries a build attestation from this project's release workflow:

```sh
gh attestation verify oci://ghcr.io/piurizza/cerebrum-backend:latest --owner piurizza
gh attestation verify oci://ghcr.io/piurizza/cerebrum-frontend:latest --owner piurizza
```
