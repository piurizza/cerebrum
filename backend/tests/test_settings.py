from __future__ import annotations

import pytest
from pydantic import ValidationError

from cerebrum.settings import get_settings

# auth_jwt_secret/auth_setup_token are required settings with no default
# (see settings.py) -- every test below that constructs Settings() for an
# unrelated field must still supply both, or construction fails before
# reaching the field under test.
_VALID_AUTH_ENV = {"AUTH_JWT_SECRET": "x" * 32, "AUTH_SETUP_TOKEN": "y" * 32}


def _set_valid_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _VALID_AUTH_ENV.items():
        monkeypatch.setenv(key, value)


def test_mcp_enabled_defaults_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_ENABLED", raising=False)
    _set_valid_auth_env(monkeypatch)
    get_settings.cache_clear()
    try:
        assert get_settings().mcp_enabled is True
    finally:
        get_settings.cache_clear()


def test_mcp_enabled_reads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "false")
    _set_valid_auth_env(monkeypatch)
    get_settings.cache_clear()
    try:
        assert get_settings().mcp_enabled is False
    finally:
        get_settings.cache_clear()


def test_auth_secrets_are_secret_str(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_auth_env(monkeypatch)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert "x" * 32 not in str(settings.auth_jwt_secret)
        assert "x" * 32 not in repr(settings.auth_jwt_secret)
        assert settings.auth_jwt_secret.get_secret_value() == "x" * 32
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("missing_key", ["AUTH_JWT_SECRET", "AUTH_SETUP_TOKEN"])
def test_construction_fails_when_auth_secret_unset(
    monkeypatch: pytest.MonkeyPatch, missing_key: str
) -> None:
    _set_valid_auth_env(monkeypatch)
    monkeypatch.delenv(missing_key, raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("target_key", ["AUTH_JWT_SECRET", "AUTH_SETUP_TOKEN"])
@pytest.mark.parametrize("value", ["", "x" * 31])
def test_construction_fails_when_auth_secret_too_short(
    monkeypatch: pytest.MonkeyPatch, target_key: str, value: str
) -> None:
    _set_valid_auth_env(monkeypatch)
    monkeypatch.setenv(target_key, value)
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_construction_succeeds_with_32_byte_auth_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_valid_auth_env(monkeypatch)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.auth_jwt_secret.get_secret_value() == "x" * 32
        assert settings.auth_setup_token.get_secret_value() == "y" * 32
    finally:
        get_settings.cache_clear()


def test_watcher_settings_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WATCHER_ENABLED", raising=False)
    monkeypatch.delenv("WATCHER_DEBOUNCE_MS", raising=False)
    monkeypatch.delenv("WATCHER_BACKSTOP_INTERVAL_SECONDS", raising=False)
    _set_valid_auth_env(monkeypatch)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.watcher_enabled is True
        assert settings.watcher_debounce_ms == 400
        assert settings.watcher_backstop_interval_seconds == 300
    finally:
        get_settings.cache_clear()


def test_watcher_settings_read_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WATCHER_ENABLED", "false")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "200")
    monkeypatch.setenv("WATCHER_BACKSTOP_INTERVAL_SECONDS", "60")
    _set_valid_auth_env(monkeypatch)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.watcher_enabled is False
        assert settings.watcher_debounce_ms == 200
        assert settings.watcher_backstop_interval_seconds == 60
    finally:
        get_settings.cache_clear()
