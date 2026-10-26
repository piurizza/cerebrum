"""The configuration docs page lists every user-facing environment variable
exactly once, and nothing else. Variables come from the backend `Settings`,
every `.env.example` (commented examples included), the Compose file, the
options the install script documents, and the `import.meta.env.VITE_*`
values the web and desktop apps read. Its "Docker `.env`" column must match
what `docker-compose.yml` actually passes through."""

from __future__ import annotations

import re
from pathlib import Path

from cerebrum.settings import Settings

_ROOT = Path(__file__).parents[2]
_PAGE = _ROOT / "website" / "docs" / "reference" / "configuration.md"
_ENV_EXAMPLES = [
    _ROOT / ".env.example",
    _ROOT / "backend" / ".env.example",
    _ROOT / "frontend" / ".env.example",
    _ROOT / "desktop" / ".env.example",
]
# Hooks the installer's own tests use; not options for people.
_TEST_HOOKS = {"CEREBRUM_COMPOSE_SOURCE", "CEREBRUM_SKIP_PULL"}

_ENV_KEY = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)
_COMPOSE_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")
# The install script's header lists its options as `#   NAME  description`.
_INSTALL_OPTION = re.compile(r"^#\s{2,}(CEREBRUM_[A-Z_]+)\b", re.MULTILINE)
# `| `NAME` | default | yes/no | description |`
_TABLE_ROW = re.compile(
    r"^\| `([A-Z][A-Z0-9_]*)` \| [^|]* \| (yes|no) \|", re.MULTILINE
)
_VITE_READ = re.compile(r"import\.meta\.env\.(VITE_[A-Z0-9_]+)")
_APP_SOURCES = [_ROOT / "frontend" / "src", _ROOT / "desktop" / "src"]


def _compose_variables() -> set[str]:
    compose = (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    return set(_COMPOSE_VAR.findall(compose))


def _sources() -> set[str]:
    # pylint can't infer pydantic's class-level `model_fields` mapping.
    names = {f.upper() for f in Settings.model_fields}  # pylint: disable=not-an-iterable
    for example in _ENV_EXAMPLES:
        names |= set(_ENV_KEY.findall(example.read_text(encoding="utf-8")))
    names |= _compose_variables()
    install = (_ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    names |= set(_INSTALL_OPTION.findall(install))
    for source_dir in _APP_SOURCES:
        for source in source_dir.rglob("*.ts*"):
            names |= set(_VITE_READ.findall(source.read_text(encoding="utf-8")))
    return names - _TEST_HOOKS


def _rows() -> list[tuple[str, str]]:
    return _TABLE_ROW.findall(_PAGE.read_text(encoding="utf-8"))


def _documented() -> list[str]:
    return [name for name, _ in _rows()]


def test_every_variable_has_a_row() -> None:
    missing = sorted(_sources() - set(_documented()))
    assert not missing, f"add these to {_PAGE.relative_to(_ROOT)}: {missing}"


def test_no_row_for_a_variable_nothing_defines() -> None:
    stale = sorted(set(_documented()) - _sources())
    assert not stale, f"remove these from {_PAGE.relative_to(_ROOT)}: {stale}"


def test_each_variable_has_one_row() -> None:
    rows = _documented()
    duplicates = sorted({name for name in rows if rows.count(name) > 1})
    assert not duplicates, f"listed more than once: {duplicates}"


def test_sources_include_variables_outside_settings() -> None:
    sources = _sources()
    assert {
        "CEREBRUM_PORT",
        "VITE_DAILY_NOTE_FOLDER",
        "WATCHFILES_FORCE_POLLING",
        "CEREBRUM_INSTALL_DIR",
    } <= sources
    assert not _TEST_HOOKS & sources


def test_docker_column_matches_the_compose_file() -> None:
    compose = _compose_variables()
    wrong = sorted(
        name for name, docker in _rows() if (docker == "yes") != (name in compose)
    )
    assert not wrong, f"fix the Docker `.env` column for: {wrong}"


# `${NAME:-default}` with a plain default (no nested `${...}` fallback).
_COMPOSE_DEFAULT = re.compile(r"\$\{([A-Z][A-Z0-9_]*):-([^}$]*)\}")


def _as_env_text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def test_compose_defaults_match_the_backend() -> None:
    # Compose hands the container its default when `.env` leaves a variable
    # out, so a default that differs from the backend's own would quietly
    # change behaviour for Docker installs only.
    compose = (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    fields = Settings.model_fields
    wrong = [
        f"{name}: compose {default!r}, backend {_as_env_text(field.default)!r}"
        for name, default in _COMPOSE_DEFAULT.findall(compose)
        if default
        and (field := fields.get(name.lower())) is not None
        and default != _as_env_text(field.default)
    ]
    assert not wrong, wrong
