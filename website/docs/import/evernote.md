# Import from Evernote

Evernote doesn't export markdown. It exports `.enex` files, which a converter
turns into markdown.

## Export

In the Evernote desktop app (not the web version), export the notebooks you
want as `.enex` files: right-click a notebook or selected notes, choose
**Export**, then the ENEX format. Evernote exports up to 100 notes at a time,
or whole notebooks. Its help describes the steps in
[Export notes and notebooks as ENEX or HTML](https://help.evernote.com/hc/en-us/articles/209005557-Export-Notes-and-Notebooks-as-ENEX-or-HTML).

## Convert to markdown

Two ways:

- **Through Joplin.** Install the Joplin desktop app, import the `.enex`
  files with **File**, **Import**, **ENEX** (Joplin converts them to markdown),
  then follow [Import from Joplin](joplin.md). Tags come through, as
  frontmatter.
- **With a converter**, such as the open-source Yarle, which turns `.enex`
  files into markdown files with frontmatter. Choose frontmatter output, so
  titles and tags carry over.

## Copy into the vault

Copy the converted folder into the vault, for example as
`vault/imported/evernote/`.

## What carries over

- Notes, with their text, lists, checklists and tables, as far as the
  converter manages.
- Titles and tags, when the converter writes them as frontmatter.
- Images, as files linked from the notes.

## Fix by hand

- **Formatting** that markdown can't express, such as font colours and
  complex tables, comes out simplified.
- **Links between notes** depend on the converter; check a few, and replace
  broken ones with `[[wikilinks]]`. See [Import](index.md#what-doesnt-yet).

## Known gaps

Web clips may come out messy. Reminders, note history and shared-notebook
settings don't carry over.
