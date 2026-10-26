from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# JWTs and setup tokens are only as strong as the secret they're signed/
# compared against; 32 bytes (256 bits) matches the minimum HMAC-SHA256
# needs to be collision/brute-force resistant. Enforced below rather than
# left to deployers, since a short or missing secret fails silently at
# request time (any string "works") instead of loudly at startup.
_MIN_AUTH_SECRET_BYTES = 32

# Defaults for the vault folder settings below, also what a blank value
# falls back to.
_DEFAULT_DAILY_NOTE_FOLDER = "daily"
_DEFAULT_TEMPLATES_FOLDER = "templates"

# Defaults for the OpenID Connect settings below, also what a blank value
# falls back to.
_OIDC_DEFAULTS = {
    "oidc_provider_name": "SSO",
    "oidc_scopes": "openid profile email",
    "oidc_groups_claim": "groups",
}

# Hosts an `http://` issuer may use without `oidc_allow_insecure_issuer`:
# a provider on the same machine, where nothing crosses a network.
_LOOPBACK_ISSUER_HOSTS = ("localhost", "127.0.0.1")

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "Cerebrum"
    # How much Cerebrum's own code logs (uvicorn's request log is separate).
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    cerebrum_vault_path: Path = Path("./vault")
    # Where the derived index and the accounts database live. Unset means
    # `<vault>/.cerebrum/`. Setting them puts that state outside the vault,
    # e.g. when the vault is a checkout some other tool owns.
    cerebrum_index_path: Path | None = None
    cerebrum_auth_db_path: Path | None = None
    # Serve the vault without ever writing to it: note and attachment
    # writes are refused, MCP write tools aren't offered, and an external
    # rename is indexed without relinking. Requires both paths above to be
    # outside the vault.
    cerebrum_vault_read_only: bool = False

    cors_origins: list[str] = ["http://localhost:5173"]

    mcp_enabled: bool = True

    # No defaults, deliberately: unlike the rest of this class, these two
    # gate real authentication (JWT signing, the initial-admin setup flow)
    # -- a fallback default would mean every fresh install shares the same
    # guessable secret until someone remembers to override it.
    auth_jwt_secret: SecretStr
    auth_setup_token: SecretStr
    auth_access_token_ttl_minutes: int = 10
    auth_refresh_token_ttl_days: int = 30
    auth_cookie_secure: bool = False

    watcher_enabled: bool = True
    watcher_debounce_ms: int = 400
    watcher_backstop_interval_seconds: int = 300
    watcher_rename_pairing_window_seconds: int = 30

    max_attachment_size_bytes: int = 10_000_000

    # Vault-relative folders the web app uses: "Today" creates daily notes
    # in the first, the "+ New note" template picker lists notes under the
    # second. Served to clients by `GET /api/vault-settings` -- read at
    # runtime, not baked into the frontend build, so prebuilt images and
    # the desktop app (which bundles its own copy of the frontend) follow
    # whatever the server is configured with.
    cerebrum_daily_note_folder: str = _DEFAULT_DAILY_NOTE_FOLDER
    cerebrum_templates_folder: str = _DEFAULT_TEMPLATES_FOLDER

    # How this vault's notes link to each other: the form the editor's `[[`
    # picker inserts and MCP tools ask agents to write. Both forms are
    # always read; this only picks which one gets written.
    cerebrum_link_format: Literal["markdown", "wikilink"] = "markdown"

    # Sign-in through one OpenID Connect provider (Keycloak, Authentik,
    # Pocket ID, Google, ...). On when the issuer, client id and client
    # secret are all set, off when none are; anything in between fails
    # startup. A blank value counts as unset, so a compose `${VAR:-}`
    # passthrough can't half-enable it.
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    # The `<name>` in "Sign in with <name>".
    oidc_provider_name: str = _OIDC_DEFAULTS["oidc_provider_name"]
    oidc_scopes: str = _OIDC_DEFAULTS["oidc_scopes"]
    # Members of this provider group are admins; empty means the provider
    # never grants or removes admin.
    oidc_admin_group: str = ""
    oidc_groups_claim: str = _OIDC_DEFAULTS["oidc_groups_claim"]
    # Accept an `http://` issuer on any host, not just loopback. For test
    # stacks only: the ID token and client secret cross the network in the
    # clear.
    oidc_allow_insecure_issuer: bool = False
    # Off: only admins, and accounts not yet linked to the provider, may
    # sign in with a password, and invites are redeemed through the
    # provider. Needs a provider configured.
    auth_password_login: bool = True

    # `hide_input_in_errors`: a startup validation error would otherwise
    # print every raw input, secrets such as `oidc_client_secret` included.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", hide_input_in_errors=True
    )

    @field_validator("cerebrum_daily_note_folder", "cerebrum_templates_folder")
    @classmethod
    def _normalize_vault_folder(cls, value: str, info: ValidationInfo) -> str:
        """Trim whitespace and leading/trailing slashes, and fall back to
        the default when nothing is left -- a leading slash would otherwise
        make every path built from the folder absolute. `.` and `..`
        segments fail startup loudly instead of producing paths that every
        note write then rejects."""
        folder = value.strip().strip("/")
        if not folder:
            return (
                _DEFAULT_DAILY_NOTE_FOLDER
                if info.field_name == "cerebrum_daily_note_folder"
                else _DEFAULT_TEMPLATES_FOLDER
            )
        if any(segment in ("", ".", "..") for segment in folder.split("/")):
            raise ValueError(
                f"{info.field_name} must be a plain vault-relative folder like "
                f"'daily' or 'journal/daily', got {value!r}"
            )
        # Same rule as `notes/wikilinks.py`'s `is_hidden_path`.
        if any(segment.startswith(".") for segment in folder.split("/")):
            raise ValueError(
                f"{info.field_name} can't be inside a hidden folder, got "
                f"{value!r}: notes there are never indexed or listed"
            )
        return folder

    @field_validator("cerebrum_index_path", "cerebrum_auth_db_path", mode="before")
    @classmethod
    def _blank_path_means_default(cls, value: object) -> object:
        """A blank value means the default location. Compose passes an unset
        variable through as an empty string, which would otherwise become
        `Path(".")` and fail startup."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        """Ignore case and surrounding spaces; blank means the default.
        Anything else that isn't a standard level fails startup."""
        if isinstance(value, str):
            return value.strip().upper() or "INFO"
        return value

    @field_validator("cerebrum_link_format", mode="before")
    @classmethod
    def _normalize_link_format(cls, value: object) -> object:
        """Ignore case and surrounding spaces; blank means the default.
        Anything else that isn't `markdown` or `wikilink` fails startup."""
        if isinstance(value, str):
            return value.strip().lower() or "markdown"
        return value

    @field_validator(
        "oidc_issuer", "oidc_client_id", "oidc_client_secret", mode="before"
    )
    @classmethod
    def _blank_means_unset(cls, value: object) -> object:
        """Trim surrounding spaces; nothing left means unset."""
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator(
        "oidc_provider_name", "oidc_scopes", "oidc_groups_claim", "oidc_admin_group"
    )
    @classmethod
    def _blank_oidc_text_means_default(cls, value: str, info: ValidationInfo) -> str:
        """Trim surrounding spaces; nothing left means the default."""
        assert info.field_name is not None
        return value.strip() or _OIDC_DEFAULTS.get(info.field_name, "")

    @model_validator(mode="after")
    def _keep_index_and_accounts_apart(self) -> Settings:
        """The index is a disposable cache (deleting it is always safe);
        the accounts database is not. Sharing one file would make that
        advice delete every account."""
        if self.index_path.resolve() == self.auth_db_path.resolve():
            raise ValueError(
                "CEREBRUM_INDEX_PATH and CEREBRUM_AUTH_DB_PATH must be different "
                f"files, both are {self.index_path}"
            )
        return self

    @model_validator(mode="after")
    def _keep_state_out_of_a_read_only_vault(self) -> Settings:
        """A read-only vault must not hold the index or the accounts
        database: SQLite writes to them (and their -wal/-shm files) on
        every request, which would still be Cerebrum writing into it."""
        if not self.cerebrum_vault_read_only:
            return self
        vault = self.cerebrum_vault_path.resolve()
        for env_name, path in (
            ("CEREBRUM_INDEX_PATH", self.index_path),
            ("CEREBRUM_AUTH_DB_PATH", self.auth_db_path),
        ):
            if path.resolve().is_relative_to(vault):
                raise ValueError(
                    f"CEREBRUM_VAULT_READ_ONLY needs {env_name} outside the vault "
                    f"({vault}), got {path}"
                )
        return self

    @model_validator(mode="after")
    def _require_strong_auth_secrets(self) -> Settings:
        for field_name in ("auth_jwt_secret", "auth_setup_token"):
            secret: SecretStr = getattr(self, field_name)
            if len(secret.get_secret_value().encode("utf-8")) < _MIN_AUTH_SECRET_BYTES:
                raise ValueError(
                    f"{field_name} must be at least {_MIN_AUTH_SECRET_BYTES} bytes "
                    "-- generate one with `openssl rand -hex 32`"
                )
        return self

    @model_validator(mode="after")
    def _require_complete_oidc_provider(self) -> Settings:
        required = {
            "OIDC_ISSUER": self.oidc_issuer,
            "OIDC_CLIENT_ID": self.oidc_client_id,
            "OIDC_CLIENT_SECRET": self.oidc_client_secret,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing and len(missing) < len(required):
            raise ValueError(
                "an OpenID Connect provider needs OIDC_ISSUER, OIDC_CLIENT_ID and "
                f"OIDC_CLIENT_SECRET together -- missing: {', '.join(missing)}"
            )
        return self

    @model_validator(mode="after")
    def _require_secure_oidc_issuer(self) -> Settings:
        if self.oidc_allow_insecure_issuer:
            logger.warning(
                "OIDC_ALLOW_INSECURE_ISSUER is on: an http:// OpenID Connect "
                "issuer is accepted on any host. Use it for test stacks only."
            )
        if self.oidc_issuer is None:
            return self
        issuer = urlsplit(self.oidc_issuer)
        if issuer.scheme == "https" and issuer.hostname:
            return self
        if issuer.scheme == "http" and issuer.hostname:
            if issuer.hostname in _LOOPBACK_ISSUER_HOSTS:
                return self
            if self.oidc_allow_insecure_issuer:
                return self
        raise ValueError(
            f"OIDC_ISSUER must be an https:// URL, got {self.oidc_issuer!r} -- "
            "http:// is accepted only for localhost and 127.0.0.1, or on any host "
            "with OIDC_ALLOW_INSECURE_ISSUER=true (test stacks only)"
        )

    @model_validator(mode="after")
    def _require_provider_when_password_login_off(self) -> Settings:
        if not self.auth_password_login and not self.oidc_enabled:
            raise ValueError(
                "AUTH_PASSWORD_LOGIN=false needs an OpenID Connect provider "
                "(OIDC_ISSUER, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET) -- "
                "otherwise nobody but admins could sign in"
            )
        return self

    @property
    def oidc_enabled(self) -> bool:
        return (
            self.oidc_issuer is not None
            and self.oidc_client_id is not None
            and self.oidc_client_secret is not None
        )

    @property
    def index_path(self) -> Path:
        if self.cerebrum_index_path is not None:
            return self.cerebrum_index_path
        return self.cerebrum_vault_path / ".cerebrum" / "index.sqlite3"

    @property
    def auth_db_path(self) -> Path:
        if self.cerebrum_auth_db_path is not None:
            return self.cerebrum_auth_db_path
        return self.cerebrum_vault_path / ".cerebrum" / "auth.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
