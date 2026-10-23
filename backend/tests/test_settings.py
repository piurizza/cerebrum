from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from cerebrum.settings import Settings, get_settings
from tests.oidc_fake import pin_oidc_env_off

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
    monkeypatch.delenv("WATCHER_RENAME_PAIRING_WINDOW_SECONDS", raising=False)
    _set_valid_auth_env(monkeypatch)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.watcher_enabled is True
        assert settings.watcher_debounce_ms == 400
        assert settings.watcher_backstop_interval_seconds == 300
        assert settings.watcher_rename_pairing_window_seconds == 30
    finally:
        get_settings.cache_clear()


def test_watcher_settings_read_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WATCHER_ENABLED", "false")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "200")
    monkeypatch.setenv("WATCHER_BACKSTOP_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("WATCHER_RENAME_PAIRING_WINDOW_SECONDS", "10")
    _set_valid_auth_env(monkeypatch)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.watcher_enabled is False
        assert settings.watcher_debounce_ms == 200
        assert settings.watcher_backstop_interval_seconds == 60
        assert settings.watcher_rename_pairing_window_seconds == 10
    finally:
        get_settings.cache_clear()


# --- OpenID Connect provider settings ---------------------------------------

_VALID_OIDC_ENV = {
    "OIDC_ISSUER": "https://idp.example/realms/home",
    "OIDC_CLIENT_ID": "cerebrum",
    "OIDC_CLIENT_SECRET": "s3cret",
}


def _set_oidc_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    """Start every OIDC test from a clean slate -- none of the OIDC
    variables set -- then apply `overrides` (keys as the env var names)."""
    _set_valid_auth_env(monkeypatch)
    pin_oidc_env_off(monkeypatch)
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)


def _build_settings() -> Settings:
    get_settings.cache_clear()
    try:
        return get_settings()
    finally:
        get_settings.cache_clear()


def _state_paths(monkeypatch: pytest.MonkeyPatch, **env: str) -> tuple[Path, Path]:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", "/notes")
    for name in ("CEREBRUM_INDEX_PATH", "CEREBRUM_AUTH_DB_PATH"):
        # Blank, not unset: an unset variable would let backend/.env decide.
        monkeypatch.setenv(name, "")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    _set_valid_auth_env(monkeypatch)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        return settings.index_path, settings.auth_db_path
    finally:
        get_settings.cache_clear()


def test_oidc_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_oidc_env(monkeypatch)

    settings = _build_settings()

    assert settings.oidc_enabled is False
    assert settings.oidc_issuer is None
    assert settings.oidc_client_id is None
    assert settings.oidc_client_secret is None
    assert settings.oidc_provider_name == "SSO"
    assert settings.oidc_scopes == "openid profile email"
    assert settings.oidc_admin_group == ""
    assert settings.oidc_groups_claim == "groups"
    assert settings.auth_password_login is True
    assert settings.oidc_allow_insecure_issuer is False


def test_oidc_enabled_when_issuer_client_id_and_secret_are_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_oidc_env(monkeypatch, **_VALID_OIDC_ENV, OIDC_PROVIDER_NAME="Keycloak")

    settings = _build_settings()

    assert settings.oidc_enabled is True
    assert settings.oidc_issuer == "https://idp.example/realms/home"
    assert settings.oidc_client_id == "cerebrum"
    assert settings.oidc_client_secret is not None
    assert settings.oidc_client_secret.get_secret_value() == "s3cret"
    assert "s3cret" not in repr(settings)
    assert settings.oidc_provider_name == "Keycloak"


@pytest.mark.parametrize(
    ("missing", "expected_names"),
    [
        (("OIDC_CLIENT_SECRET",), ["OIDC_CLIENT_SECRET"]),
        (("OIDC_CLIENT_ID",), ["OIDC_CLIENT_ID"]),
        (("OIDC_ISSUER", "OIDC_CLIENT_ID"), ["OIDC_ISSUER", "OIDC_CLIENT_ID"]),
    ],
)
def test_partial_oidc_configuration_fails_naming_the_missing_variables(
    monkeypatch: pytest.MonkeyPatch,
    missing: tuple[str, ...],
    expected_names: list[str],
) -> None:
    present = {k: v for k, v in _VALID_OIDC_ENV.items() if k not in missing}
    _set_oidc_env(monkeypatch, **present)

    with pytest.raises(ValidationError) as exc_info:
        _build_settings()

    message = str(exc_info.value)
    assert f"missing: {', '.join(expected_names)} " in message
    # The configured secret never ends up in the startup error.
    assert "s3cret" not in message


def test_partial_oidc_configuration_counts_a_blank_secret_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_oidc_env(monkeypatch, **{**_VALID_OIDC_ENV, "OIDC_CLIENT_SECRET": "  "})

    with pytest.raises(ValidationError, match="OIDC_CLIENT_SECRET"):
        _build_settings()


def test_blank_oidc_variables_mean_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # A compose `${VAR:-}` passthrough sets every variable to "" -- that
    # must read as "no provider", not as a half-configured one.
    _set_oidc_env(
        monkeypatch,
        OIDC_ISSUER="",
        OIDC_CLIENT_ID="",
        OIDC_CLIENT_SECRET="",
        OIDC_PROVIDER_NAME="",
        OIDC_SCOPES="",
        OIDC_ADMIN_GROUP="",
        OIDC_GROUPS_CLAIM="",
    )

    settings = _build_settings()

    assert settings.oidc_enabled is False
    assert settings.oidc_issuer is None
    assert settings.oidc_provider_name == "SSO"
    assert settings.oidc_scopes == "openid profile email"
    assert settings.oidc_admin_group == ""
    assert settings.oidc_groups_claim == "groups"


def test_blank_issuer_alone_counts_as_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_oidc_env(monkeypatch, OIDC_ISSUER="")

    assert _build_settings().oidc_enabled is False


@pytest.mark.parametrize(
    "issuer",
    [
        "http://idp.example",
        "http://192.168.1.10:8080/realms/x",
        "idp.example/realms/x",
        "ftp://idp.example",
        "https://",
    ],
)
def test_insecure_or_malformed_issuer_fails_startup(
    monkeypatch: pytest.MonkeyPatch, issuer: str
) -> None:
    _set_oidc_env(monkeypatch, **{**_VALID_OIDC_ENV, "OIDC_ISSUER": issuer})

    with pytest.raises(ValidationError, match="OIDC_ISSUER"):
        _build_settings()


@pytest.mark.parametrize(
    "issuer",
    [
        "https://idp.example/realms/x",
        "http://localhost:8080/realms/x",
        "http://127.0.0.1:9000/application/o/cerebrum/",
    ],
)
def test_https_or_loopback_issuer_is_accepted(
    monkeypatch: pytest.MonkeyPatch, issuer: str
) -> None:
    _set_oidc_env(monkeypatch, **{**_VALID_OIDC_ENV, "OIDC_ISSUER": issuer})

    assert _build_settings().oidc_issuer == issuer


def test_http_issuer_on_any_host_is_accepted_with_allow_insecure_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _set_oidc_env(
        monkeypatch,
        **{**_VALID_OIDC_ENV, "OIDC_ISSUER": "http://192.168.1.10:8080/realms/x"},
        OIDC_ALLOW_INSECURE_ISSUER="true",
    )

    with caplog.at_level(logging.WARNING, logger="cerebrum.settings"):
        settings = _build_settings()

    assert settings.oidc_issuer == "http://192.168.1.10:8080/realms/x"
    assert any(
        record.levelno == logging.WARNING
        and "OIDC_ALLOW_INSECURE_ISSUER" in record.getMessage()
        for record in caplog.records
    )


def test_allow_insecure_still_rejects_an_issuer_with_no_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_oidc_env(
        monkeypatch,
        **{**_VALID_OIDC_ENV, "OIDC_ISSUER": "idp.example/realms/x"},
        OIDC_ALLOW_INSECURE_ISSUER="true",
    )

    with pytest.raises(ValidationError, match="OIDC_ISSUER"):
        _build_settings()


def test_password_login_off_without_a_provider_fails_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_oidc_env(monkeypatch, AUTH_PASSWORD_LOGIN="false")

    with pytest.raises(ValidationError, match="AUTH_PASSWORD_LOGIN"):
        _build_settings()


def test_password_login_off_with_a_provider_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_oidc_env(monkeypatch, **_VALID_OIDC_ENV, AUTH_PASSWORD_LOGIN="false")

    settings = _build_settings()

    assert settings.auth_password_login is False
    assert settings.oidc_enabled is True


def test_index_and_accounts_db_default_to_inside_the_vault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _state_paths(monkeypatch) == (
        Path("/notes/.cerebrum/index.sqlite3"),
        Path("/notes/.cerebrum/auth.sqlite3"),
    )


def test_index_and_accounts_db_paths_read_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _state_paths(
        monkeypatch,
        CEREBRUM_INDEX_PATH="/state/index.sqlite3",
        CEREBRUM_AUTH_DB_PATH="/state/auth.sqlite3",
    ) == (Path("/state/index.sqlite3"), Path("/state/auth.sqlite3"))


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_index_and_accounts_db_paths_mean_the_default(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    # Compose passes an unset `${VAR:-}` through as an empty string.
    assert _state_paths(
        monkeypatch, CEREBRUM_INDEX_PATH=blank, CEREBRUM_AUTH_DB_PATH=blank
    ) == (
        Path("/notes/.cerebrum/index.sqlite3"),
        Path("/notes/.cerebrum/auth.sqlite3"),
    )


def test_index_and_accounts_db_must_be_different_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The index is safe to delete; the accounts database is not.
    with pytest.raises(ValidationError, match="must be different files"):
        _state_paths(
            monkeypatch,
            CEREBRUM_INDEX_PATH="/state/cerebrum.sqlite3",
            CEREBRUM_AUTH_DB_PATH="/state/cerebrum.sqlite3",
        )


def _read_only_settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> bool:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", "/notes")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    _set_valid_auth_env(monkeypatch)
    get_settings.cache_clear()
    try:
        return get_settings().cerebrum_vault_read_only
    finally:
        get_settings.cache_clear()


def test_vault_is_writable_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CEREBRUM_VAULT_READ_ONLY", raising=False)
    assert _read_only_settings(monkeypatch) is False


def test_read_only_vault_reads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        _read_only_settings(
            monkeypatch,
            CEREBRUM_VAULT_READ_ONLY="true",
            CEREBRUM_INDEX_PATH="/state/index.sqlite3",
            CEREBRUM_AUTH_DB_PATH="/state/auth.sqlite3",
        )
        is True
    )


@pytest.mark.parametrize(
    ("index_path", "auth_db_path", "named"),
    [
        # Unset means `<vault>/.cerebrum/`, inside the vault.
        ("", "", "CEREBRUM_INDEX_PATH"),
        ("/notes/state/index.sqlite3", "/state/auth.sqlite3", "CEREBRUM_INDEX_PATH"),
        ("/state/index.sqlite3", "", "CEREBRUM_AUTH_DB_PATH"),
        # Resolved before comparing, so `..` can't hide a path in the vault.
        ("/state/index.sqlite3", "/state/../notes/a.sqlite3", "CEREBRUM_AUTH_DB_PATH"),
    ],
)
def test_read_only_vault_refuses_state_inside_the_vault(
    monkeypatch: pytest.MonkeyPatch, index_path: str, auth_db_path: str, named: str
) -> None:
    # SQLite writes -wal/-shm files next to each database, so either one
    # inside the vault would still be Cerebrum writing into it.
    with pytest.raises(ValidationError, match=named):
        _read_only_settings(
            monkeypatch,
            CEREBRUM_VAULT_READ_ONLY="true",
            CEREBRUM_INDEX_PATH=index_path,
            CEREBRUM_AUTH_DB_PATH=auth_db_path,
        )


def test_read_only_vault_accepts_a_sibling_folder_sharing_a_name_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `/notes-state` starts with the string `/notes` but is not inside it.
    assert (
        _read_only_settings(
            monkeypatch,
            CEREBRUM_VAULT_READ_ONLY="true",
            CEREBRUM_INDEX_PATH="/notes-state/index.sqlite3",
            CEREBRUM_AUTH_DB_PATH="/notes-state/auth.sqlite3",
        )
        is True
    )
