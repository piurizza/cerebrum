# Testing

Use Node 22 for every frontend, desktop and documentation command: newer
versions break some frontend tests.

## Everything

```sh
make check    # lint, type checks and every test suite
```

CI runs the same checks on every pull request, plus a few more listed below.

## By part

| Part | Command | Covers |
|---|---|---|
| Backend | `make test-backend` | pytest: the API, MCP tools, indexing, the watcher, accounts. |
| Frontend | `make test-frontend` | vitest unit and component tests, and a production build. |
| Desktop | `make test-desktop` | vitest for the desktop app's own screen. |
| Documentation | `make test-website` | The site's scripts, and that every release has an upgrade page. |

Generated files have their own checks, which fail when the file no longer
matches its source:

```sh
make check-api-types   # frontend API types vs the backend's schema
make check-docs-api    # REST API reference page vs the backend's schema
```

When one fails, run the matching `generate-` target and commit the result.

## End-to-end tests

The Playwright tests in `frontend/e2e/` drive a real browser against a running
stack. They don't run in CI.

```sh
make up
cd frontend
E2E_USERNAME=<account> E2E_PASSWORD=<password> npm run test:e2e
```

Use a test account on a local stack, never a real one. `E2E_BASE_URL` points
them at another address than `http://localhost:7811`.

## In CI only

- **Installer:** runs the install script on x86_64 and arm64 against images
  built from the pull request: a fresh install, then a rerun.
- **Desktop smoke test:** installs and launches the Windows desktop app when it
  changes.
- **Dependency vulnerabilities:** checks every lockfile against known
  advisories, on pull requests and weekly. `make audit-deps` runs it locally.

## Documentation checks

```sh
make docs-check            # strict build, no third-party requests, local links
make docs-check-runtime    # loads every page in a browser; fails on any outside request
```

The site must never make a visitor's browser contact another host. The first
check reads the built files; the second watches what the pages actually load.
