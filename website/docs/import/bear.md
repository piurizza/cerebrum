# Import from Bear

## Export

In Bear, select the notes to export (select all for everything), then
choose **File**, **Export notes…**, and the **Markdown** format. Bear's help
covers the formats in
[Export Notes in Different Formats](https://bear.app/faq/export-your-notes/).

Check that the export includes your images. If it doesn't, export the notes
that have images separately, or add the images back by pasting them into the
note in Cerebrum.

## Copy into the vault

Copy the exported folder into the vault, for example as
`vault/imported/bear/`.

## What carries over

- Notes and their text. File names are the note titles.
- `[[Note title]]` links between notes, read as wikilinks, as long as the
  file name matches the title.
- Images, when the export includes them.

## Fix by hand

- **Tags.** Bear's tags are written in the text, such as `#garden` or
  `#garden/shed`, and Cerebrum only reads tags in frontmatter. Add a `tags:`
  list to the notes you filter by:

    ```markdown
    ---
    tags: [garden/shed]
    ---
    ```

- **Folders.** Bear organises with tags, not folders, so the export is one
  flat folder. Move notes into folders if you like; wikilinks keep working
  because they find notes by name.
- **Markdown links to notes or images with spaces in their names**; see
  [Import](index.md#what-doesnt-yet).

## Known gaps

Bear-specific formatting, such as highlighting, may come out as plain text or
markup. Note pins and archive state don't carry over.
