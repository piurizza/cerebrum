.PHONY: install install-backend install-frontend \
        lint lint-backend lint-frontend \
        format format-backend format-frontend \
        type-check test test-backend test-frontend \
        check clean up down logs

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
	cd frontend && $(NPM) run lint

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
