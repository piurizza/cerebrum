# Cerebrum

[![CI](https://github.com/piurizza/cerebrum/actions/workflows/ci.yml/badge.svg)](https://github.com/piurizza/cerebrum/actions/workflows/ci.yml)

A self-hosted second brain. Your notes are plain markdown files in a folder on
your own server, linked into a graph, and you reach them from any browser, your
phone or a desktop app.

![A note in Cerebrum, with the folder tree and backlinks](website/docs/assets/screenshots/note.webp)

- **Plain files.** Every note is a `.md` file. Edit them anywhere; Cerebrum
  picks up the changes.
- **Links and a graph.** Markdown links or Obsidian-style `[[wikilinks]]`,
  backlinks, a graph view, and renames that keep links working.
- **Tags, search and tasks.** Full-text search with `#tag` filters, a tag
  front page, and every open checkbox in one list.
- **Phone and desktop.** Installs to your phone's home screen and reads
  offline; native desktop apps for Linux, macOS and Windows.
- **AI assistants.** A built-in MCP server lets Claude and other assistants
  read and write your notes with a token you control.

## Install

On Linux or macOS, with Docker:

```sh
curl -fsSL https://github.com/piurizza/cerebrum/releases/latest/download/install.sh | sh
```

It installs into `~/cerebrum-server`, starts Cerebrum at
`http://localhost:7811` and prints a token for your first account.

## Documentation

**[piurizza.github.io/cerebrum](https://piurizza.github.io/cerebrum/)**: the
quick start, from Docker on a home server to the app on your phone; install
options; every feature; HTTPS, backups and accounts; connecting AI assistants;
importing from Obsidian, Notion and others; and upgrade notes for every
release. The pages' source is in [`website/docs/`](website/docs/).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[development docs](https://piurizza.github.io/cerebrum/development/). Design
decisions and their reasons are in [SPEC.md](SPEC.md).

## License

[MIT](LICENSE)
