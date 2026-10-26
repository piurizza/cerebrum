# Development

How to work on Cerebrum itself. To contribute, also read
[CONTRIBUTING.md](https://github.com/piurizza/cerebrum/blob/main/CONTRIBUTING.md).

## Layout

| Folder | What it is |
|---|---|
| `backend/` | The API server: FastAPI with SQLite, Python 3.12, managed with uv. |
| `frontend/` | The web app: React, Vite and TypeScript. Served by nginx in Docker. |
| `desktop/` | The desktop app: a Tauri v2 window onto a running server. |
| `website/` | This documentation site, built with Zensical. |
| `deploy/` | The install script. |
| `fixtures/` | Test cases shared by the backend and the frontend. |
| `vault/` | Default notes folder for local development; not committed. |

Design decisions, and the reasons for them, are in
[SPEC.md](https://github.com/piurizza/cerebrum/blob/main/SPEC.md). Read it before
changing how something works.

## Requirements

- Python 3.12 or newer, with [uv](https://docs.astral.sh/uv/).
- Node 22. Newer versions break some frontend tests.
- Docker, for `make up` and the documentation screenshots.
- For the desktop app: Rust, plus on Linux the `webkit2gtk4.1-devel` and
  `librsvg2-devel` packages (names vary by distribution).

## Set up

```sh
make install
```

This copies the `.env.example` files to `.env` for the backend, frontend and
desktop app, installs dependencies, and installs the pre-commit hooks.

Then set `AUTH_JWT_SECRET` and `AUTH_SETUP_TOKEN` in `backend/.env` to long
random strings (`openssl rand -hex 32` makes one). For `make up`, also copy the
root `.env.example` to `.env` and set the same two values there.

## Run it

Without Docker, in two terminals:

```sh
cd backend && uv run cerebrum      # API at http://localhost:8000
cd frontend && npm run dev         # app at http://localhost:5173, /api proxied to :8000
```

With Docker, building the images from your checkout:

```sh
make up       # http://localhost:7811
make logs
make down
```

The desktop app: `cd desktop && npm run tauri dev`. To build its installers,
run `make build-desktop`:

- **Linux** builds a `.deb` and an `.rpm`; it needs the WebKitGTK and librsvg
  development packages listed above.
- **macOS** builds one universal `.dmg`; it needs Xcode's command line tools
  and both Rust targets:
  `rustup target add aarch64-apple-darwin x86_64-apple-darwin`.
- **Windows:** run `npm run tauri build -- --bundles nsis` in `desktop/`; it
  needs the Visual Studio C++ build tools.

Building the server's images needs Docker Engine 23 or newer, about 2 GB of
free memory and 2.5 GB of disk for the build cache;
`docker builder prune` frees the cache afterwards.

## Everyday commands

```sh
make format       # ruff for Python, Biome for TypeScript
make lint         # ruff and pylint, Biome
make type-check   # mypy --strict, tsc
make test         # pytest, vitest, website tests
make check        # all of the above
```

More in [Testing](testing.md).

## The documentation

The site's pages are in `website/docs/`. Building it needs uv and Node 22: the
site serves its own copy of Mermaid for diagrams, installed from
`website/package-lock.json`.

```sh
make docs-serve        # preview at http://localhost:8001, reloads on change
make docs-check        # strict build, no third-party requests, links resolve
make docs-screenshots  # retake the screenshots from a demo vault (Docker, Node 22)
```

A change to what users see updates the docs in the same pull request; see
[CONTRIBUTING.md](https://github.com/piurizza/cerebrum/blob/main/CONTRIBUTING.md).
