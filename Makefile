.PHONY: install install-backend install-frontend \
        lint lint-backend lint-frontend \
        format format-backend format-frontend \
        type-check test test-backend test-frontend \
        check clean up down logs \
        generate-api-types check-api-types

UV ?= uv
NPM ?= npm

install: install-backend install-frontend

install-backend:
	cd backend && $(UV) sync --all-groups
	cp -n backend/.env.example backend/.env
	@if [ -d .git ]; then $(UV) run --project backend pre-commit install; else echo "Skipping pre-commit install: not a git repository"; fi

install-frontend:
	cd frontend && $(NPM) install
	cp -n frontend/.env.example frontend/.env

lint: lint-backend lint-frontend

lint-backend:
	cd backend && $(UV) run ruff check src tests && $(UV) run pylint src tests

lint-frontend:
	cd frontend && $(NPM) run check

format: format-backend format-frontend

format-backend:
	cd backend && $(UV) run ruff format src tests && $(UV) run ruff check --fix src tests

format-frontend:
	cd frontend && $(NPM) run format

type-check:
	cd backend && $(UV) run mypy
	cd frontend && $(NPM) run type-check

test: test-backend test-frontend

test-backend:
	cd backend && $(UV) run pytest

test-frontend:
	cd frontend && $(NPM) run test:run
	cd frontend && $(NPM) run build

check: lint type-check test

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

clean:
	rm -rf backend/.mypy_cache backend/.pytest_cache backend/.ruff_cache backend/dist backend/build backend/*.egg-info
	find backend/src backend/tests -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf frontend/dist frontend/node_modules/.vite

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f
