# Import from Joplin

## Export

In the Joplin desktop app, use **File**, **Export all**, and choose the
**Markdown + Front Matter** format. That variant puts each note's title and
tags into frontmatter, which Cerebrum reads. Joplin's help describes
importing and exporting in
[Import and export](https://joplinapp.org/help/apps/import_export/).

## Copy into the vault

Copy the exported folder into the vault, for example as
`vault/imported/joplin/`.

## What carries over

- Notebooks, as folders, and notes, with their text and checklists.
- Titles and tags, from the frontmatter.
- Images, which Joplin puts in one `_resources/` folder next to the notebook
  folders, linked from the notes. Copy that folder too.

## Fix by hand

- **Links between notes and to images.** Joplin writes them as relative
  markdown links. Those whose target has spaces in its name, encoded as `%20`,
  aren't followed yet; see [Import](index.md#what-doesnt-yet). Replace the
  ones you need with `[[wikilinks]]`.

## Known gaps

Attachments other than images are kept as files, not shown. Note history,
alarms and encryption don't carry over.
