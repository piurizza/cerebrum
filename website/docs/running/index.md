# Running Cerebrum

Everything about operating a Cerebrum server once it's installed.

| Page | Covers |
|---|---|
| [Accounts and invites](accounts.md) | The first account, inviting people, API tokens, deactivating accounts. |
| [HTTPS](https.md) | Reaching Cerebrum from a phone or other devices, with a trusted certificate. |
| [Backups](backups.md) | What to back up, and how to restore. |
| [Sign in with an identity provider](identity-provider.md) | Keycloak, Authentik, Pocket ID, Google and other OpenID Connect providers. |
| [Read-only vault and a second instance](read-only-and-second-instance.md) | Serving a vault another tool owns; keeping Cerebrum's state out of the vault. |
| [Security](security.md) | The settings that affect who can reach Cerebrum and how sessions work. |

All settings are in [Configuration](../reference/configuration.md). After
changing `.env`, apply it with `docker compose up -d` in the install folder.

## Day to day

In the install folder (`~/cerebrum-server` for the install script):

```sh
docker compose ps              # is it running?
docker compose logs backend    # what did the server say?
docker compose restart         # restart both containers
docker compose down            # stop; your notes stay where they are
docker compose up -d           # start again
```
