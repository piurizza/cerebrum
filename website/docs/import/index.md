# Import

Cerebrum reads a folder of markdown files, so moving notes over is mostly a
matter of exporting them as markdown from the other app and copying the files
into the vault. There is no import button and none is needed.

| Coming from | Export as | Main fix by hand | Effort |
|---|---|---|---|
| [Obsidian](obsidian.md) | Nothing to export: copy the vault folder | Tags written in the text | Low |
| [Joplin](joplin.md) | Markdown with front matter | Links to names with spaces | Low |
| [Bear](bear.md) | Markdown | Every tag, written in the text | Medium |
| [Logseq](logseq.md) | Nothing to export: copy the graph folder | Properties and outlines | Medium |
| [Notion](notion.md) | Markdown | File names and links | Medium |
| [Apple Notes](apple-notes.md) | Markdown, on recent versions | Tags and folders | Medium |
| [Evernote](evernote.md) | ENEX, then converted | The conversion | Medium |

## The steps, for every source

1. **Export** from the other app, following its guide here.
2. **Look at the export** before copying, in a file manager or editor.
3. **Copy it into the vault**, into a folder of its own, for example
   `vault/imported/notion/`. On a server, copy it with `scp`, `rsync` or a file
   share. Make sure the files belong to your user, not root.
4. **Open Cerebrum.** It notices new files on its own; reload the page to see
   them.
5. **Fix what didn't carry over**, using the list in the guide.

Try a small export first, so you know what to expect before moving everything.

## What carries over

- **Notes** and their text, as long as they're markdown.
- **Folders**, which stay folders.
- **Frontmatter**, the YAML block at the top: `title` and `tags` are read, and
  everything else is kept as it is.
- **Links** written as `[[wikilinks]]`, or as markdown links to file names
  without spaces.
- **Images** linked from notes.

## What doesn't carry over

- **Tags written in the text**, such as `#idea` in a sentence. Only tags in the
  frontmatter count. Many apps write tags in the text, so each guide says
  whether this affects you.
- **Markdown links and images whose file names contain spaces**, such as
  `[x](My%20Note.md)` or `![](Attachments/My%20Photo.png)`. Many exporters
  write links this way. Wikilinks and `![[My Photo.png]]` embeds are not
  affected. See [Links](../features/links.md#known-limits).
- **Attachments other than images,** such as PDFs, are kept as files but not
  shown in the preview.
- **App-specific features** such as databases, embeds of other notes'
  sections, block references or plugins.

Product names on these pages belong to their owners. Cerebrum is not
affiliated with any of them.
