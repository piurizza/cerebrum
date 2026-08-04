# Cerebrum

A self-hosted second brain: notes are plain `.md` files on disk, cross-referenced
with standard markdown links, with a visual graph of how they connect.

See [SPEC.md](SPEC.md) for the full design — storage model, note/frontmatter
format, API surface, graph data model, and tech stack rationale. Read it before
making architectural changes.

## Layout

- `backend/` — FastAPI + SQLite index, serves the notes API (Python, `uv`)
- `frontend/` — React + Vite + TypeScript web client (markdown editor + graph view)
- `vault/` — default local dev directory for `.md` notes (gitignored)

## Setup

    make install

Copies `.env.example` → `.env` for both backend and frontend, installs
dependencies, and (in a git repo) installs pre-commit hooks.

## Common Commands

    make format       # ruff (backend) + biome (frontend)
    make lint         # ruff + pylint (backend), biome (frontend)
    make type-check   # mypy --strict (backend), tsc (frontend)
    make test         # pytest (backend), production build (frontend)
    make check        # lint + type-check + test

## Run locally (without Docker)

    cd backend && uv run cerebrum        # http://localhost:8000
    cd frontend && npm run dev           # http://localhost:5173 (proxies /api to :8000)

## Run with Docker

    make up     # builds and starts backend + frontend, http://localhost:8080
    make down
    make logs

Notes are bind-mounted from `./vault` on the host (override via
`CEREBRUM_VAULT_HOST_PATH` in a root `.env`, copied from `.env.example`) so
they persist independently of the containers.

## MCP server

An MCP server is mounted at `/api/mcp`, reachable through the same
frontend-published port and nginx proxy as the REST API (no separate port).
Remote clients (e.g. Claude Desktop) can read, search, create, and update
notes over it. Every call requires the same credential as the rest of the
backend; until the backend-authentication feature ships, that check is a
fail-closed stub (`mcp_allow_stub_auth`, off by default) rather than a real
one.

**If you expose this beyond `localhost`, put TLS in front of it** (a
reverse proxy or tunnel) -- this is the same pre-existing gap the rest of
Cerebrum's remote access already has, not something specific to MCP, and
this project does not terminate TLS itself.
