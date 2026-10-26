# Sign in with an identity provider

Cerebrum can let people sign in with an OpenID Connect provider you already
run, such as Keycloak, Authentik or Pocket ID, or with Google. The provider
only proves who someone is. Cerebrum keeps its own accounts, sessions and API
tokens, so AI assistants and the apps work as before.

One provider at a time is supported.

## Set it up

1. **At the provider,** create a **confidential** client, with a client id and
   secret, for Cerebrum. Register the return address for **every** address you
   open Cerebrum on, exactly, without wildcards:

    ```text
    https://<host>:<port>/api/auth/oidc/callback
    ```

    For example `https://192.0.2.10:7812/api/auth/oidc/callback` and
    `https://<machine>.<tailnet>.ts.net:7812/api/auth/oidc/callback`.

2. **In `.env`,** set:

    ```sh
    OIDC_ISSUER=https://auth.example.com/realms/home
    OIDC_CLIENT_ID=cerebrum
    OIDC_CLIENT_SECRET=<the client secret>
    OIDC_PROVIDER_NAME=Keycloak     # the button says "Sign in with Keycloak"
    ```

    then run `docker compose up -d`.

    - Copy the issuer exactly as the provider shows it. Authentik's ends in
      `/`. A mismatch shows up as a failed sign-in and a log line with both
      values.
    - Keycloak: `https://<keycloak>/realms/<realm>`.
      Authentik: `https://<authentik>/application/o/<app-slug>/`.
      Pocket ID: `https://<pocket-id>`.
    - The issuer must use `https://`, except on `localhost`.
    - The Cerebrum server must be able to reach the issuer address too, not
      just your browser.

## How people get in

Cerebrum never matches people by email address or username. An identity is
tied to an account in one of two ways:

- **New people:** create an invite in **Settings** as usual. On the
  **Register** page they pick a username, paste the invite and choose
  **Sign up with** your provider. Their account has no password.
- **Existing accounts:** sign in with your password, open **Settings**, and
  choose **Link** under **Sign-in provider**. Cerebrum asks for your current
  password first.

## Optional settings

- **Admins from a group.** `OIDC_ADMIN_GROUP=<group>` makes members of that
  provider group admins, and removes admin from everyone else, each time they
  sign in with the provider. The provider has to put groups in the ID token
  (claim `groups` by default, `OIDC_GROUPS_CLAIM` to change it; in Keycloak,
  add a "Group Membership" mapper). A change at the provider takes effect at
  the person's next provider sign-in; to remove someone at once, deactivate
  their account in **Settings**.
- **Provider only.** `AUTH_PASSWORD_LOGIN=false` makes the provider the way
  in: invites can only be redeemed through it, and anyone who has linked can
  no longer use a password. Admins always keep their password, so a provider
  outage never locks you out. Accounts that haven't linked yet can still use
  their password, so they can link: ask everyone to link first.

## Keep the issuer stable

If you change `OIDC_ISSUER` or remove these settings, accounts created through
the provider can't sign in any more: they have no password, and there is no
way to give them one.

## Known limits

- **Behind a proxy that handles HTTPS,** such as
  [Tailscale serve](https.md#tailscale-serve) or a reverse proxy, provider
  sign-in doesn't work: Cerebrum builds the return address with `http://`.
  Use Cerebrum's own HTTPS port with a trusted certificate instead, as in
  [Tailscale certificate on the built-in HTTPS port](https.md#tailscale-certificate-on-the-built-in-https-port).
- **iPhone home-screen app:** provider sign-in opens in Safari and finishes
  there, not in the app. Sign in from Safari instead.
- **Google** refuses sign-in from embedded browsers, which includes the
  desktop app. Self-hosted providers work there.
- Not supported: several providers at once, creating accounts at the first
  provider sign-in without an invite, and signing out at the provider.
