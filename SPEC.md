# Cerebrum — Design Spec

This document is the reference for cerebrum's design decisions. Code should
conform to this spec; if the two disagree, update this file as part of the
change, not after.

## 1. Product vision

Cerebrum is a personal "second brain" — an Obsidian-style note-taking app
with three non-negotiable properties:

- **Every note is a plain `.md` file on disk.** The filesystem is the
  source of truth, not a database. You can always read, edit, back up, or
  migrate away from cerebrum with nothing more than a text editor.
- **Notes cross-reference each other with standard markdown links**
  (`[text](relative/path.md)`), not Obsidian's `[[wikilink]]` syntax. This
  keeps notes readable and portable in any plain markdown renderer, at the
  cost of slightly more verbose linking.
- **The graph of links between notes is visualized and traversable**, like
  Obsidian's graph view — nodes are notes, edges are links.

Cerebrum is a **self-hosted web app**: one backend + one web frontend,
deployed once and accessed from any device's browser. "Cross-device sync"
is achieved simply by every device pointing at the same server — there is
no CRDT, offline-first sync engine, or per-device local copy. This is a
deliberate simplification; see [Known Gaps](#10-known-gaps--future-work).

## 2. Storage model

- Notes live under a **vault directory**, configured via
  `CEREBRUM_VAULT_PATH` (default `./vault` in dev, `/data/vault` in Docker).
- The vault is a plain directory tree of `.md` files (and, in future,
  attachments). Nothing about its structure is proprietary.
- A derived, disposable **index** lives at `<vault>/.cerebrum/index.sqlite3`
  (configurable via `CEREBRUM_INDEX_PATH`). It exists purely for fast
  queries (listing, backlinks, graph, search) and can be deleted and
  rebuilt from the vault at any time with no data loss.

## 3. Note format

YAML frontmatter, all fields optional:

```markdown
---
title: My Note Title
tags: [project, idea]
created: 2026-07-31T10:00:00Z
updated: 2026-07-31T10:00:00Z
---

# Body in standard markdown

See [Related Note](../other-folder/related-note.md) for more.
```

- `title` — defaults to the filename (without `.md`) if absent.
- `tags` — list of strings, defaults to `[]`.
- `created` — ISO-8601 UTC, set once on first write if absent.
- `updated` — ISO-8601 UTC, **always set by the backend** on every `PUT`,
  overriding any client-supplied value (server-authoritative, to avoid
  clock skew across devices).
- No `id`/`uid` field — **the note's path, relative to the vault root, is
  its canonical identity.**

### Link resolution rule

Any inline markdown link `[text](target)` is a graph edge if `target`,
resolved relative to the *linking file's own directory*, points to a path
ending in `.md` inside the vault. Links to external URLs (`http://`,
`https://`, `mailto:`) or non-`.md` targets (images, attachments) are left
untouched in the file but ignored for graph purposes.

A link may point to a `.md` path that doesn't exist yet — this is a valid
"broken link" / unresolved reference, same as Obsidian, and is preserved
in the index (see below).

## 4. Index/cache architecture

SQLite, schema at `backend/src/cerebrum/index/schema.sql`:

```sql
CREATE TABLE notes (
    path         TEXT PRIMARY KEY,  -- relative path from vault root
    title        TEXT NOT NULL,
    tags         TEXT NOT NULL DEFAULT '[]',  -- JSON array
    created      TEXT,
    updated      TEXT,
    content_hash TEXT NOT NULL,     -- sha256 of file bytes
    mtime        REAL NOT NULL
);

CREATE TABLE links (
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL,      -- normalized relative path; need not exist
    link_text   TEXT,
    PRIMARY KEY (source_path, target_path, link_text)
);
CREATE INDEX idx_links_target ON links(target_path);
CREATE INDEX idx_links_source ON links(source_path);

CREATE VIRTUAL TABLE notes_fts USING fts5(
    path UNINDEXED, title, body, tokenize='porter'
);
```

- `target_path` has **no foreign key** — broken links are valid data,
  validated in application code, not the schema.
- `notes_fts` is scaffolded now; the search endpoint itself is future work.

**Rebuild strategy:** full vault rescan (walk, hash, upsert changed rows,
delete rows for removed files) on backend startup via a FastAPI lifespan
hook. Incremental single-file upsert on every `PUT`/`DELETE` note request.
The `.md` file is always written first; the index is best-effort and
self-heals via the next rescan if it ever drifts.

## 5. API surface

All endpoints under `/api`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness + vault-path reachability |
| GET | `/api/notes` | List notes (path, title, tags, updated) from the index |
| GET | `/api/notes/{path:path}` | Fetch one note: raw markdown + parsed metadata |
| PUT | `/api/notes/{path:path}` | Create or update a note (body = raw markdown) |
| DELETE | `/api/notes/{path:path}` | Delete a note file + its index rows |
| POST | `/api/notes/{path:path}/move` | Relocate a note and/or rename its title (`{"new_path": "...", "title": "..."}` body, `title` optional) and rewrite every note's markdown links that pointed at it; `new_path` may equal the current path for a title-only rename; 404 if source missing, 409 if destination exists |
| GET | `/api/graph` | `{ nodes: [{path, title}], edges: [{source, target}] }` |
| GET | `/api/notes/{path:path}/backlinks` | Notes that link to this note |
| GET | `/api/search?q=...` | Full-text search over title + body via `notes_fts`; each word in `q` is an AND-ed prefix term, ranked by `bm25`; empty/whitespace `q` returns `[]` |

`{path:path}` uses FastAPI's path converter since relative vault paths
contain `/`. Clients must URL-encode path segments appropriately — this is
an easy source of bugs and worth double-checking when writing frontend
API calls.

## 6. Graph data model

- Nodes = notes (from the `notes` table). Edges = rows in `links`.
- Backlinks for a note are just `links` rows where `target_path` equals
  that note's path — the same table drives both `/api/graph` and
  `/api/notes/{path}/backlinks`.
- A link to a nonexistent note is a valid edge to a "ghost" node
  (Obsidian-style unresolved reference), carrying `exists: false` on
  `GraphNode` so the frontend can render and behave differently for it
  (see [Feature roadmap](#9-feature-roadmap-user-stories)).

## 7. Tech stack

### Backend — Python, conventions matched from `interview-blueprint`

- **uv** for dependency management, `src/`-layout (`backend/src/cerebrum/`)
- **ruff** (line-length 88, target py312, rules `A,B,C4,E,F,I,N,SIM,UP,W`)
- **mypy --strict**
- **pylint**
- **pytest** (`testpaths=["tests"]`, `pythonpath=["src"]` — no install needed to test)
- **pre-commit**, hooks with `language: system` (shells out to `uv run ...`)
- **pydantic-settings** `BaseSettings` + `@lru_cache get_settings()`
- **hatchling** as the PEP 517 build backend
- New, not present in interview-blueprint: **FastAPI** + **uvicorn** (API
  layer), **python-frontmatter** (frontmatter parsing), **httpx** (for
  FastAPI's `TestClient` in tests)

### Frontend — React + TypeScript

- **Vite + React + TypeScript**, **react-router-dom** v6
- **CodeMirror 6** (`@uiw/react-codemirror` + `@codemirror/lang-markdown`)
  for the markdown editor — purpose-built for markdown, the same editing
  engine Obsidian itself uses, lighter than Monaco and far more capable
  than a bare `<textarea>`. Theme (`light`/`dark`) tracks the OS color
  scheme live via a shared `usePrefersDark()` hook, so editor text stays
  readable regardless of system theme.
- **react-markdown + remark-gfm** for the rendered preview mode (Edit /
  Preview toggle on the note editor). Frontmatter is stripped client-side
  before rendering (`lib/noteContent.ts`); inter-note links are resolved
  relative to the current note's directory with a JS port of the
  backend's `resolve_link_target` (same file) and rendered as in-app
  `react-router-dom` links, not full page loads — external links open
  normally in a new tab. A link-autocomplete picker while typing is still
  planned (see [Feature roadmap](#9-feature-roadmap-user-stories)).
- **react-force-graph** (2D canvas variant) for graph visualization —
  wraps d3-force physics with canvas rendering, zoom/pan, and node-click
  handling out of the box. Canvas rendering scales to hundreds of nodes
  far better than an SVG-per-node approach, where every node/edge is a DOM
  element.
- **Biome** for lint + format — one fast tool/config, mirroring ruff's
  role on the backend rather than combining ESLint + Prettier.
- A thin `fetch`-based API client; no data-fetching library yet (see
  Known Gaps).

## 8. Deployment

- `backend/Dockerfile`: `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
  base, `uv sync --frozen --no-dev`, runs `uvicorn cerebrum.main:app`.
- `frontend/Dockerfile`: multi-stage — `node:20-alpine` builds the static
  bundle, `nginx:alpine` serves it and reverse-proxies `/api/` to the
  `backend` service on the compose network.
- Root `docker-compose.yml` wires `backend` + `frontend`. The vault is
  **bind-mounted** from the host
  (`${CEREBRUM_VAULT_HOST_PATH:-./vault}:/data/vault`), not stored in an
  anonymous Docker volume, so notes persist on the host filesystem
  independent of the containers — consistent with "no vendor lock-in."

### Environment variables

| Variable | Where | Default | Purpose |
|---|---|---|---|
| `APP_ENV` | backend | `development` | environment name |
| `APP_NAME` | backend | `Cerebrum` | display name |
| `LOG_LEVEL` | backend | `INFO` | logging level |
| `CEREBRUM_VAULT_PATH` | backend | `./vault` | root dir of `.md` notes |
| `CEREBRUM_INDEX_PATH` | backend | `<vault>/.cerebrum/index.sqlite3` | SQLite index location |
| `CORS_ORIGINS` | backend | `["http://localhost:5173"]` | allowed frontend origins |
| `CEREBRUM_VAULT_HOST_PATH` | compose | `./vault` | host dir bind-mounted into backend |
| `CEREBRUM_PORT` | compose | `8080` | host port for the frontend |
| `VITE_API_BASE_URL` | frontend | (proxied) | override API origin if not proxying |

## 9. Feature roadmap (user stories)

Format: "the user should be able to...". Status reflects the scaffold as
of this writing — update statuses as features land, and add new stories
here as they're agreed, rather than letting them live only in chat/PR
history.

### Note management

- [x] view/read a note
- [x] edit a note's content and save changes
- [x] create a new note (pick a title/path, start writing) -- both note
      creation and rename/move use a shared folder-picker modal
      (`FolderPickerModal`) instead of a raw text path field: it lists
      the vault's existing folders, lets you descend into one, add a new
      one inline (just a path segment, no separate persisted "folder"
      entity -- see [Storage model](#2-storage-model)), and enter the
      file name, composing the final vault-relative path.
- [x] delete a note -- `DELETE /api/notes/{path}` already existed but
      had no UI. Adds a "Delete" action next to Copy path/Rename with an
      inline confirm step (no modal needed, unlike rename/create --
      there's nothing to navigate or type), then routes back to `/`.
      Other notes' links that pointed at the deleted note become broken
      links (ghost nodes) rather than being rewritten or removed --
      consistent with [Link resolution rule](#3-note-format), same as a
      manually-deleted file would behave.
- [x] rename or move a note to a different path/folder, **link-aware**:
      `POST /api/notes/{path}/move` physically relocates the file,
      preserves `created`, re-bases the moved note's own outgoing
      relative links so they still resolve to the same targets (they're
      relative to its folder, which just changed), and repoints every
      other note's links that targeted the old path so they resolve to
      the new one instead -- link text and any `#fragment` are rewritten
      in place, everything else in the linking note is left untouched. A
      note with unreadable content is skipped (logged) rather than
      aborting the whole move. Scans every note in the vault to find
      incoming links rather than trusting the (disposable, possibly
      stale) index, at O(n) cost per move -- fine at personal-vault
      scale, worth revisiting if that ever becomes the bottleneck. The
      same rename UI (and the same `move` endpoint, via an optional
      `title` field) also updates the note's frontmatter `title` --
      moving a note's path alone never changed its title before, which
      was surprising; now both can change together in one action, and
      the new title is reflected immediately in the sidebar and the
      graph (both read `title` from the index, refreshed as part of the
      same move/rename request).
- [x] see when a note was created/last updated, surfaced in the UI --
      `Note.created`/`.updated` (already returned by the API, previously
      unused by the frontend) rendered as a muted line below the path
      header, formatted with the browser's locale/timezone via
      `Intl.DateTimeFormat` (`lib/formatDate.ts`). Updates live after a
      save or a rename, since both return the new `updated` timestamp.
- [x] see the note's own vault-relative path, not just its title -- two
      notes can share a title (e.g. two different `CAD.md` notes in
      different folders), and the path is what you actually need to
      write a link to it. Shown read-only above the editor, with a copy
      button. Not written into the note's own frontmatter -- the path
      is derived from the file's location on disk, not stored data, so
      persisting it there would drift if the file were ever moved (see
      [Note format](#3-note-format)).

### Organization & discovery

- [x] browse all notes grouped in a collapsible folder tree mirroring
      their vault paths (folders sort before notes, alphabetical within
      each level; expand/collapse state is per-session, not persisted)
- [x] search notes by content (full-text, backed by the already-scaffolded
      `notes_fts` table — see [Index/cache architecture](#4-indexcache-architecture)).
      `notes_fts` was already kept in sync on every upsert/delete; this
      only needed `GET /api/search` (`index/db.py::search_notes`) plus a
      search box in the sidebar. Debounced (250ms) as-you-type, replacing
      the folder tree with a flat, relevance-ranked result list while a
      query is active; clearing the box restores the tree.
- [ ] filter notes by tag. **Scope decision: filtering only** — no
      dedicated tags-browser page. Revisit only if filtering proves
      insufficient in practice.
- [x] see backlinks for the current note
- [x] traverse the link graph visually
- [x] click a graph node to jump to that note
- [x] see broken/unresolved links distinctly in the graph (ghost nodes,
      via `GraphNode.exists`)

### Cross-referencing

- [x] see a rendered markdown preview with clickable links to other
      notes, not just raw text in the editor
- [ ] insert a link to another note while writing, via an
      autocomplete/picker triggered while typing. The trigger UX may be
      Obsidian-flavored (e.g. `[[`), but it must always insert a standard
      markdown link (`[title](path.md)`) — never wikilink syntax (see
      [Product vision](#1-product-vision)). Can be backed by the existing
      `GET /api/notes` listing, filtered client-side; upgrade to the
      full-text search endpoint once that exists.

### Access

- [x] access their vault from any device via a browser (self-hosted,
      single server)

### Editing experience

- [x] see whether they have unsaved changes
- [ ] save via a keyboard shortcut (e.g. Cmd/Ctrl+S)

### Attachments (later, unscheduled)

- [ ] embed an image in a note
- [ ] paste/upload an image into a note

### Reliability

- [x] notes stay valid plain markdown even if the app breaks (by design)
- [ ] see edits made outside the app (e.g. vim, a sync tool) reflected
      without restarting the server (tracked in
      [Known gaps](#10-known-gaps--future-work) as the filesystem-watcher gap)

## 10. Known gaps / future work

- **No filesystem watcher.** Edits made to `.md` files outside the API
  (e.g. directly with `vim`, or synced in by another tool) aren't picked
  up until the next backend startup rescan. Mitigated, not solved.
- **No auth / multi-user support.** A single trusted user per deployment
  is assumed.
- **No full-text search endpoint yet.** The `notes_fts` table is
  scaffolded but nothing populates or queries it yet.
- **No CRDT / offline-first sync.** Intentional: cerebrum is
  server-centralized by design, not a distributed local-first system.
- **No attachment/image handling** defined yet (only `.md` files).
- **No generated API types.** Frontend `types/note.ts` is hand-kept in
  sync with the backend's pydantic models; an OpenAPI-generated client is
  a reasonable future improvement.
- **No frontend test framework yet** (no Vitest/RTL); `make test-frontend`
  currently just runs the production build as a compile-correctness check.
- **`npm audit` flags a high-severity advisory in `react-router`** (RSC-mode
  CSRF bypass). Not applicable here — this app uses plain client-side
  routing, not React Router's RSC/framework mode. Revisit if that changes.
