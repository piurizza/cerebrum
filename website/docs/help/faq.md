# FAQ

## Where are my notes?

In the vault folder on the server: `~/cerebrum-server/vault` with the install
script, or `./vault` next to `docker-compose.yml` for a hand install. Each note
is a `.md` file you can open in any editor.

## Can I edit notes outside Cerebrum?

Yes. Edit, add, rename or delete files in the vault with any editor or sync
tool, and Cerebrum picks up the change within a second or two. An open window
shows it when you come back to it or reload. On Docker Desktop for macOS or
Windows, set `WATCHFILES_FORCE_POLLING=1`; see
[Troubleshooting](troubleshooting.md#changes-made-outside-cerebrum-dont-show-up).

## Can I stop using Cerebrum?

Yes, with nothing to export: your notes are already markdown files, with
standard frontmatter and links that other tools understand. Cerebrum's own
files live in `vault/.cerebrum/` and can be deleted.

## Does it sync between devices?

Every device talks to the same server, so there is nothing to sync. Phones and
browsers keep a read-only copy for when the server can't be reached; see
[Offline use](../features/offline.md).

## Can I edit offline?

No. Offline you can read, but not edit. This keeps one copy of every note, on
the server, with no conflicts to resolve.

## Can several people share one Cerebrum?

Yes: invite them from **Settings**. Everyone with an account sees and edits
the same vault; there are no private notes or per-folder permissions. For
separate notes, run a separate Cerebrum, each with its own vault.

## Does it work with Obsidian?

Yes. Cerebrum reads Obsidian's `[[wikilinks]]` and embeds, ignores its
`.obsidian/` folder, and keeps frontmatter it doesn't know. Both can work on the
same folder. See [Import from Obsidian](../import/obsidian.md).

## Why can't I install it on my phone?

Phones install web apps only from an address with a certificate they trust.
`http://` addresses, and `https://` with a self-signed certificate, don't
count. See [HTTPS](../running/https.md).

## Does Cerebrum use AI, or send my notes anywhere?

No. Cerebrum has no AI features of its own, no analytics and no telemetry. It
contacts no outside service, except an
[identity provider](../running/identity-provider.md) if you set one up. If you
connect an AI assistant over
[MCP](../agents/index.md), that assistant reads what you let it read, and its
provider's terms apply to what it sends there.

## Can I use a different port?

Yes: set `CEREBRUM_PORT` and `CEREBRUM_HTTPS_PORT` in `.env` and run
`docker compose up -d`. If the phone app is installed, it belongs to the old
address; install it again from the new one.

## Is there a mobile app in the app stores?

No. The phone app installs from the browser; see
[Phone app](../install/phone.md).

## Which version am I running?

See [Upgrade](../install/upgrade.md#find-your-version).
