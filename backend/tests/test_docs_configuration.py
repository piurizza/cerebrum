"""The configuration docs page lists every user-facing environment variable
exactly once, and nothing else. Variables come from the backend `Settings`,
every `.env.example` (commented examples included), the Compose file, and
the options the install script documents."""

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
_TABLE_ROW = re.compile(r"^\| `([A-Z][A-Z0-9_]*)` \|", re.MULTILINE)


def _sources() -> set[str]:
    # pylint can't infer pydantic's class-level `model_fields` mapping.
    names = {f.upper() for f in Settings.model_fields}  # pylint: disable=not-an-iterable
    for example in _ENV_EXAMPLES:
        names |= set(_ENV_KEY.findall(example.read_text(encoding="utf-8")))
    compose = (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    names |= set(_COMPOSE_VAR.findall(compose))
    install = (_ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    names |= set(_INSTALL_OPTION.findall(install))
    return names - _TEST_HOOKS


def _documented() -> list[str]:
    return _TABLE_ROW.findall(_PAGE.read_text(encoding="utf-8"))


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
