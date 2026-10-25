# Features

Cerebrum keeps every note as a plain markdown file and builds everything else
from those files: links, backlinks, the graph, tags, search and the task list.

| Feature | What it does |
|---|---|
| [Notes and templates](notes-and-templates.md) | Write, preview, rename and organise notes; start new ones from a template. |
| [Daily notes](daily-notes.md) | One click opens today's note. |
| [Links](links.md) | Link notes with markdown links or `[[wikilinks]]`; renames keep links working. |
| [Tags and search](tags-and-search.md) | Full-text search with `#tag` filters. |
| [Tag front page](tag-front-page.md) | Browse the vault by tag. |
| [Graph](graph.md) | See how notes connect, and jump between them. |
| [Tasks](tasks.md) | Every open checkbox in the vault, in one list. |
| [Offline use](offline.md) | Read your notes without a connection. |
| [Read-only vault](read-only.md) | What changes when the vault can't be edited. |

## Your notes are files

Each note is a `.md` file in the vault folder on the server, with optional
frontmatter at the top:

```markdown
---
title: Garden shed
tags: [project/garden, diy]
---

# Garden shed

Plans for the shed. See [Tomatoes](../garden/tomatoes.md).
```

- `title` defaults to the file name.
- `tags` is a list; nested tags use `/`, as in `project/garden`.
- `created` and `updated` are filled in by Cerebrum.
- Any other key you add, for example `aliases`, is kept as it is.

A note's identity is its path in the vault, such as `projects/garden-shed.md`.
Cerebrum notices files you change outside it, with an editor or a sync tool,
within a second or two. A window that's already open shows them when you come
back to it, or after a reload.

Folders and files whose name starts with a dot (`.git/`, `.obsidian/`,
`.trash/`) are not notes: they never appear in lists, search or the graph.
