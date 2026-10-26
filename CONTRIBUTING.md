# Contributing

Thanks for helping. Setting up, running the tests and how releases work are in
the [development docs](https://piurizza.github.io/cerebrum/development/)
(source: [`website/docs/development/`](website/docs/development/)). Design
decisions and their reasons are in [SPEC.md](SPEC.md): read it before changing
how something works, and update it in the same pull request when a decision
changes.

## Pull requests

- **Title:** a [Conventional Commits](https://www.conventionalcommits.org)
  summary, such as `feat: browse notes by tag` or `fix: keep links when a
  folder is renamed`. Pull requests are squash-merged, and the title becomes
  the changelog entry. Mark a breaking change with `!` (`feat!:`) and explain
  it in a `BREAKING CHANGE:` footer.
- **Checks:** `make check` passes locally (Node 22). CI runs it too, plus the
  installer tests and the dependency scan.
- **Review:** every pull request to `main` needs the maintainer's approval.

## Update the docs in the same pull request

A change people can see updates the documentation in the same pull request, so
the published site always matches the latest release:

- **Pages** in `website/docs/` that describe the changed behaviour.
- **Configuration:** a new or changed environment variable gets its row in
  `website/docs/reference/configuration.md`. A test fails if one is missing.
- **REST API:** run `make generate-docs-api` after changing a route. CI fails
  if the page is out of date.
- **Screenshots:** after a visible UI change, run `make docs-screenshots`
  (needs Docker and Node 22) and commit the images it changes. Screenshots only
  ever show the generated demo vault, never real notes.
- **Upgrade notes:** a change that needs action from people upgrading, such as
  a breaking change or a changed default, goes on the next release's page in
  `website/docs/upgrade/`.

To correct the published docs between releases, open a `fix(docs): ...` pull
request. Merging it produces a patch release, which republishes the site.

## Security

Please report security problems privately, through
[GitHub's security advisories](https://github.com/piurizza/cerebrum/security/advisories/new),
not in a public issue.
