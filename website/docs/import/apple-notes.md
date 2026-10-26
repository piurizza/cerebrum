# Import from Apple Notes

## Export

Notes on macOS 26 and iOS 26, or later, exports markdown. On a Mac, select
one or more notes (++cmd++-click to add more), then choose **File**,
**Export as**, **Markdown**. Each note becomes a `.md` file, and its images go
into an `Attachments` folder next to them. Apple's
[Notes User Guide](https://support.apple.com/guide/notes/welcome/mac) has the
details for your version.

Older versions only export PDF. For those, use a third-party exporter that
writes markdown files, or copy notes into new notes in Cerebrum by hand.

## Copy into the vault

Copy the exported files into the vault, for example as
`vault/imported/apple-notes/`.

## What carries over

- Note text, headings, lists and checklists.
- Images, from the `Attachments` folder. Copy it along with the notes. Images
  whose file names contain spaces don't show; see
  [Import](index.md#what-doesnt-carry-over).

## Fix by hand

- **Folders.** Recreate your Notes folders as folders in the vault.
- **Tags.** Notes' tags are written in the text, such as `#garden`, and
  Cerebrum only reads tags in frontmatter. Add a `tags:` list to the notes you
  filter by. See [Import](index.md#what-doesnt-carry-over).
- **Formatting** beyond headings, lists and links may come out simplified.

## Known gaps

Drawings, scanned documents, locked notes and links between notes don't carry
over.
