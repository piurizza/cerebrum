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


def test_vault_settings_returns_defaults(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/api/vault-settings")

    assert response.status_code == 200
    assert response.json() == {
        "daily_note_folder": "daily",
        "templates_folder": "templates",
    }


def test_vault_settings_follows_server_environment(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Read at request time, not at startup -- clearing the cached Settings
    # is enough for a new environment to take effect.
    monkeypatch.setenv("CEREBRUM_DAILY_NOTE_FOLDER", "/journal/daily/")
    monkeypatch.setenv("CEREBRUM_TEMPLATES_FOLDER", "meta/templates")
    get_settings.cache_clear()

    response = authenticated_client.get("/api/vault-settings")

    assert response.json() == {
        "daily_note_folder": "journal/daily",
        "templates_folder": "meta/templates",
    }


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
