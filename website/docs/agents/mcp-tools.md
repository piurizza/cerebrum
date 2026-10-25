# Tools

Paths are relative to the vault root, such as `projects/garden-shed.md`.

## Reading

| Tool | Arguments | What it does |
|---|---|---|
| `list-notes` | none | Every note's path, title, tags and last update. |
| `get-note` | `path` | One note's full markdown and its parsed metadata. |
| `search-notes` | `query` | Full-text search, with `#tag` filters; see below. |
| `get-graph` | none | The whole link graph, including links to notes that don't exist yet. |
| `get-backlinks` | `path` | The notes that link to a note. |

## Writing

These are hidden when the vault is [read-only](../features/read-only.md): an
assistant then sees only the reading tools.

| Tool | Arguments | What it does |
|---|---|---|
| `create-note` | `path`, `content` | Creates a note. Fails if one already exists at that path. |
| `update-note` | `path`, `content` | Replaces an existing note's whole content. |
| `append-to-note` | `path`, `content` | Adds text at the end of an existing note, keeping the rest. |
| `edit-note` | `path`, `old_text`, `new_text` | Replaces one passage. `old_text` must appear exactly once, frontmatter included. |
| `delete-note` | `path` | Deletes a note and its images. Links to it stay, as unresolved links. |

`append-to-note` and `edit-note` read and write the note in one step, so they
can't lose a change someone else saves at the same moment. Reading with
`get-note` and then writing with `update-note` has no such guarantee.

## Search syntax

`search-notes` takes the same queries as the search box:

| Query | Finds notes |
|---|---|
| `garden shed` | Containing both words, or words starting with them |
| `#reading` | Tagged `reading`, or a tag under it such as `reading/fiction` |
| `#reading -#fiction` | Tagged `reading` but not `fiction` |
| `bread #cooking` | Tagged `cooking` and containing "bread" |

More in [Tags and search](../features/tags-and-search.md).

## Timing

Reading tools answer from Cerebrum's index. A file changed on disk a moment
ago, outside Cerebrum, can take a second or two to show up. Changes made
through the tools themselves show up at once.
