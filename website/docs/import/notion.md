# Import from Notion

## Export

In Notion, export your workspace, or a page and its subpages, as
**Markdown & CSV**, including subpages and files. Notion's help describes the
steps in
[Export your content](https://www.notion.com/help/export-your-content).

Notion gives you a zip file. Unzip it; large exports may contain more zips
inside.

## Copy into the vault

Copy the unzipped folder into the vault, for example as
`vault/imported/notion/`.

## What carries over

- Pages, as notes, with their text, headings, lists, tables and checkboxes.
- Subpages, as folders next to their parent page.
- Images, in folders next to their page.

## Fix by hand

- **File names.** Notion adds an id to each file name, such as
  `Garden plan 1a2b3c….md`. The title shown in Cerebrum comes from the file
  name, so rename the notes you use most in Cerebrum, or add a `title:` to
  their frontmatter.
- **Links between pages.** Notion's export writes links with spaces encoded
  as `%20`, which Cerebrum doesn't follow (see
  [Import](index.md#what-doesnt-carry-over)). Replace the links you need with
  `[[wikilinks]]`, such as `[[Garden plan 1a2b3c…]]`, or with links to
  renamed files.
- **Page properties** come out as plain text lines at the top of the page.
  Move the ones you want, such as tags, into frontmatter.

## Known gaps

Databases are exported as CSV files, which Cerebrum keeps but doesn't show;
each database row that is a page comes over as a note. Synced blocks, embeds,
comments and page icons don't carry over.
