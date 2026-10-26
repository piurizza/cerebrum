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
| `list-tasks` | `status`, `days`, `tags`, `folder`, `text`, `limit`, all optional | Open tasks, or with `status` `done` the tasks ticked in the last `days` days (default 14). Each comes with its note's path, the task's line and its done date. |

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
| `add-task` | `text`, `date` (optional) | Adds a task at the end of that day's daily note, creating the note if needed. |
| `set-task-done` | `path`, `line`, `text`, `done`, `date` (optional) | Ticks a task, adding its done date, or unticks it. Changes only that line. |

`append-to-note` and `edit-note` read and write the note in one step, so they
can't lose a change someone else saves at the same moment. Reading with
`get-note` and then writing with `update-note` has no such guarantee.

## Tasks

The task tools write lines the same way the [Tasks page](../features/tasks.md)
does. `set-task-done` takes `path`, `line` and `text` exactly as `list-tasks`
returned them. If the note changed and that line no longer holds the task,
nothing is written and the assistant is told to list the tasks again.

`date` is a day written as `YYYY-MM-DD`. Without it, the tools use today in
the time zone set by `CEREBRUM_TIMEZONE`, or the server's when it's unset (UTC
in Docker); see the [configuration reference](../reference/configuration.md).
Set it so an assistant adding a task late in the evening doesn't file it under
tomorrow. A daily note created this way gets an English date heading, such as
"Monday, 26 October 2026".

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
