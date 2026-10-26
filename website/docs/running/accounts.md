# Accounts and invites

Every person has their own account. Accounts, sessions and API tokens are
stored by Cerebrum itself, in its accounts database.

All accounts share one vault: everyone who can sign in reads and edits the
same notes. There are no private notes or per-folder permissions. For separate
notes, run a separate Cerebrum.

## The first account

The first account is created with the invite token in `AUTH_SETUP_TOKEN` in
`.env`; the install script prints it. Open Cerebrum, choose **Register**, and
paste it as the **Invite token**. That account is an admin.

That token only works while there are no accounts. Once the first one exists,
everyone else needs an invite from **Settings**.

## Inviting people

As an admin, open **Settings**, then **Generate invite** under **Accounts
(admin)**. Send the token to the person; they choose **Register**, pick a
username and password, and paste it. Each invite works once, for 7 days.

## Your account

In **Settings** you can:

- change your password;
- create and revoke **personal API tokens**, for
  [AI assistants over MCP](../agents/mcp-setup.md) and scripts. A token is
  shown once, when you create it, and starts with `cbm_pat_`.
- link your account to an [identity provider](identity-provider.md), when one
  is set up.

Sessions last 30 days (`AUTH_REFRESH_TOKEN_TTL_DAYS`) and survive closing the
browser. **Log out** ends the session on that device.

After 5 wrong passwords in a row, an account is locked for 15 minutes.

## Deactivating an account

An admin can **Deactivate** an account in **Settings**. Its sessions and API
tokens stop working at once. You can't deactivate your own account, or the
last active admin who has a password.

## Lost the admin password?

Cerebrum has no password reset. If you still have another admin account, use
it. Otherwise see [Troubleshooting](../help/troubleshooting.md#locked-out-of-the-only-admin-account).
