.PHONY: install install-backend install-frontend install-desktop \
        lint lint-backend lint-frontend lint-desktop \
        format format-backend format-frontend format-desktop \
        type-check test test-backend test-frontend test-desktop \
        check clean up down logs \
        generate-api-types check-api-types build-desktop audit-deps

UV ?= uv
NPM ?= npm

install: install-backend install-frontend install-desktop

install-backend:
	cd backend && $(UV) sync --all-groups
	cp -n backend/.env.example backend/.env
	@if [ -d .git ]; then $(UV) run --project backend pre-commit install; else echo "Skipping pre-commit install: not a git repository"; fi

install-frontend:
	cd frontend && $(NPM) install
	cp -n frontend/.env.example frontend/.env

install-desktop:
	cd desktop && $(NPM) install
	cp -n desktop/.env.example desktop/.env

lint: lint-backend lint-frontend lint-desktop

lint-backend:
	cd backend && $(UV) run ruff check src tests && $(UV) run pylint src tests

lint-frontend:
	cd frontend && $(NPM) run check

lint-desktop:
	cd desktop && $(NPM) run check

format: format-backend format-frontend format-desktop

format-backend:
	cd backend && $(UV) run ruff format src tests && $(UV) run ruff check --fix src tests

format-frontend:
	cd frontend && $(NPM) run format

format-desktop:
	cd desktop && $(NPM) run format

# Not split into -backend/-frontend/-desktop variants, unlike the other
# umbrella targets above -- this predates the desktop app and there's no
# need to retrofit the split just to add one more `cd && run` line.
type-check:
	cd backend && $(UV) run mypy
	cd frontend && $(NPM) run type-check
	cd desktop && $(NPM) run type-check

test: test-backend test-frontend test-desktop

test-backend:
	cd backend && $(UV) run pytest

test-frontend:
	cd frontend && $(NPM) run test:run
	cd frontend && $(NPM) run build

test-desktop:
	cd desktop && $(NPM) run test:run

check: lint type-check test

# Not part of `check` -- a Tauri build needs platform deps and produces real
# installers, not just a compile check. Linux builds the .deb and .rpm
# (needs WebKitGTK dev packages); macOS builds one universal .dmg (needs
# both Rust targets: rustup target add aarch64-apple-darwin x86_64-apple-darwin).
# The release workflow builds the same artifacts in CI.
build-desktop:
ifeq ($(shell uname -s),Darwin)
	cd desktop && CI=true $(NPM) run tauri build -- --target universal-apple-darwin --bundles dmg
else
	cd desktop && $(NPM) run tauri build
endif

# Regenerates frontend/src/api/generated/schema.ts from the backend's
# current OpenAPI schema. The intermediate schema JSON (/openapi.json,
# gitignored) is just a bridge between the two toolchains -- only the
# generated TS file is committed.
generate-api-types:
	cd backend && $(UV) run cerebrum-export-openapi-schema --output ../openapi.json
	cd frontend && $(NPM) run generate:api-types

# Fails if the committed generated types file doesn't match what
# regenerating it right now would produce -- run in CI to catch backend/
# frontend drift automatically instead of only at the next manual regen.
check-api-types: generate-api-types
	git diff --exit-code -- frontend/src/api/generated/schema.ts || \
		(echo "Generated API types are out of date -- run 'make generate-api-types' and commit the result." && exit 1)

# Checks every committed lockfile against the OSV vulnerability database
# (git-ignored folders such as node_modules are skipped). Advisories that
# can't be fixed here go in an osv-scanner.toml next to the lockfile.
OSV_SCANNER ?= ghcr.io/google/osv-scanner:v2.7.0@sha256:4f3b7e2c64b9d38a5febc5a7e4a3dfef1d1362f726dea7a2ef4762b46469fcd0

audit-deps:
	docker run --rm -v "$(CURDIR)":/src:ro $(OSV_SCANNER) scan source --recursive /src

clean:
	rm -rf backend/.mypy_cache backend/.pytest_cache backend/.ruff_cache backend/dist backend/build backend/*.egg-info
	find backend/src backend/tests -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf frontend/dist frontend/node_modules/.vite
	rm -rf desktop/dist desktop/node_modules/.vite desktop/src-tauri/target

up:
	@# The backend runs as CEREBRUM_UID, not root (docker-compose.yml). Native
	@# Docker creates a missing bind-mount source as root, which that user then
	@# can't write to -- so create the vault first, as you.
	@vault=$$(sed -n 's/^CEREBRUM_VAULT_HOST_PATH=//p' .env 2>/dev/null | tail -n 1); mkdir -p "$${vault:-./vault}"
	docker compose -f docker-compose.yml -f docker-compose.build.yml up --build

down:
	docker compose down

logs:
	docker compose logs -f
