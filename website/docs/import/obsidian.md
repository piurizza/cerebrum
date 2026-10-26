# Import from Obsidian

An Obsidian vault is already a folder of markdown files, so there is nothing
to export.

## Export

Nothing to do. Find your vault folder: in Obsidian, open the vault switcher
and choose **Open folder** next to the vault, or check the path in
[Obsidian's help on vaults](https://help.obsidian.md/Files+and+folders/Manage+vaults).

## Copy into the vault

Copy the whole folder into Cerebrum's vault, or make it the vault itself by
pointing `CEREBRUM_VAULT_HOST_PATH` at it.

You can keep using Obsidian on the same folder, for example through a sync
tool: Cerebrum picks up changes made outside it. If Cerebrum should never
change the folder, use a [read-only vault](../running/read-only-and-second-instance.md).

## What carries over

- Notes, folders and frontmatter, including `tags`, `aliases` and your own
  properties.
- `[[wikilinks]]` in all their forms: `[[Note|text]]`, `[[Note#Heading]]`,
  `[[folder/Note]]` and image embeds such as `![[photo.png]]`. They show in
  the preview, the graph and backlinks, and survive renames.
- Images, found by name anywhere in the vault.
- The `.obsidian/` settings folder and `.trash/` are ignored, as are other
  folders whose name starts with a dot.

To keep writing wikilinks from Cerebrum, set
`CEREBRUM_LINK_FORMAT=wikilink`.

## Fix by hand

- **Tags in the text.** Obsidian reads `#tag` anywhere in a note; Cerebrum
  only reads tags in the frontmatter. Move the ones you filter by into the
  `tags:` list.
- **Markdown links to files with spaces in their names**, if you use markdown
  links rather than wikilinks. See [Import](index.md#what-doesnt-carry-over).

## Known gaps

Callouts render as plain quotes. Canvas files, Dataview queries, embedded
sections of other notes (`![[Note#Section]]`) and plugins have no equivalent.
