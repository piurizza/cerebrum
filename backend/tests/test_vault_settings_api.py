from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cerebrum.settings import Settings, get_settings

# Required settings with no default (see settings.py) -- Settings() can't be
# constructed without them, whatever field a test is about.
_VALID_AUTH = {"auth_jwt_secret": "x" * 32, "auth_setup_token": "y" * 32}


def _folders(**overrides: str) -> tuple[str, str]:
    settings = Settings(**_VALID_AUTH, **overrides)  # type: ignore[arg-type]
    return settings.cerebrum_daily_note_folder, settings.cerebrum_templates_folder


def _link_format(value: str) -> str:
    overrides = {"cerebrum_link_format": value}
    settings = Settings(**_VALID_AUTH, **overrides)  # type: ignore[arg-type]
    return settings.cerebrum_link_format


def test_vault_settings_returns_defaults(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/api/vault-settings")

    assert response.status_code == 200
    assert response.json() == {
        "daily_note_folder": "daily",
        "templates_folder": "templates",
        "link_format": "markdown",
        "read_only": False,
    }


def test_vault_settings_follows_server_environment(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Read at request time, not at startup -- clearing the cached Settings
    # is enough for a new environment to take effect.
    monkeypatch.setenv("CEREBRUM_DAILY_NOTE_FOLDER", "/journal/daily/")
    monkeypatch.setenv("CEREBRUM_TEMPLATES_FOLDER", "meta/templates")
    monkeypatch.setenv("CEREBRUM_LINK_FORMAT", "wikilink")
    get_settings.cache_clear()

    response = authenticated_client.get("/api/vault-settings")

    assert response.json() == {
        "daily_note_folder": "journal/daily",
        "templates_folder": "meta/templates",
        "link_format": "wikilink",
        "read_only": False,
    }


def test_vault_settings_reports_a_read_only_vault(
    authenticated_read_only_client: TestClient,
) -> None:
    response = authenticated_read_only_client.get("/api/vault-settings")

    assert response.json()["read_only"] is True


def test_vault_settings_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/vault-settings").status_code == 401


@pytest.mark.parametrize("blank", ["", "   ", "/", "///"])
def test_blank_folder_falls_back_to_default(blank: str) -> None:
    assert _folders(
        cerebrum_daily_note_folder=blank, cerebrum_templates_folder=blank
    ) == ("daily", "templates")


@pytest.mark.parametrize("bad", ["..", "../outside", "daily/../..", "a//b", "./daily"])
def test_folder_with_dot_or_empty_segments_fails_startup(bad: str) -> None:
    with pytest.raises(ValidationError, match="plain vault-relative folder"):
        _folders(cerebrum_daily_note_folder=bad)


@pytest.mark.parametrize(
    "hidden", [".templates", "notes/.daily", ".obsidian/templates"]
)
def test_folder_inside_a_hidden_folder_fails_startup(hidden: str) -> None:
    # Hidden folders are never indexed, so notes created there would vanish
    # from every list.
    with pytest.raises(ValidationError, match="hidden"):
        _folders(cerebrum_templates_folder=hidden)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("markdown", "markdown"), (" WikiLink ", "wikilink"), ("", "markdown")],
)
def test_link_format_ignores_case_and_blank_means_markdown(
    value: str, expected: str
) -> None:
    assert _link_format(value) == expected


def test_unknown_link_format_fails_startup() -> None:
    with pytest.raises(ValidationError, match="'markdown' or 'wikilink'"):
        _link_format("obsidian")
