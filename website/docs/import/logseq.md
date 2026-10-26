# Import from Logseq

These steps are for a Logseq graph stored as markdown files, the classic file
format. If your graph uses Logseq's newer database format, export it to
markdown files from Logseq first; check Logseq's documentation for how your
version does it.

## Export

Nothing to export: a file-based graph is a folder with `pages/` and
`journals/` inside. Logseq shows its location under **All graphs**.

## Copy into the vault

Copy the graph folder into the vault, for example as `vault/logseq/`. Leave
out `logseq/` (settings) and `logseq/bak/` (backups) inside it, or keep them:
Cerebrum doesn't treat them specially, so their markdown files would show up
as notes.

## What carries over

- Pages and journals, as notes. Journals keep their date names, such as
  `2026_10_26.md`.
- `[[Page links]]`, read as wikilinks, in the preview, the graph and
  backlinks.
- Images from `assets/`, when linked with standard markdown image syntax.

## Fix by hand

- **Everything is a bullet.** Logseq writes every line as a list item, so
  notes read as long outlines. They're still readable; tidy the ones you edit.
- **Properties.** Logseq writes page properties as `key:: value` lines, which
  Cerebrum shows as text. Move `tags::` and `title::` into frontmatter:

    ```markdown
    ---
    title: Garden plan
    tags: [garden, project]
    ---
    ```

- **Tags in the text,** such as `#garden`, aren't read; see
  [Import](index.md#what-doesnt-carry-over).
- **Namespaced pages** such as `project/garden` are stored with an encoded
  file name, such as `project___garden.md`. A `[[project/garden]]` link looks
  for `project/garden.md`, so rename those files or their links.
- **Journals** aren't Cerebrum [daily notes](../features/daily-notes.md),
  which are named `daily/2026-10-26.md`. Move and rename them if you want
  **Today** to find them.

## Known gaps

Block references (`((…))`), block embeds, queries, and task states other than
done and not done have no equivalent.
