from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

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


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "Cerebrum"
    log_level: str = "INFO"

    cerebrum_vault_path: Path = Path("./vault")
    # Where the derived index and the accounts database live. Unset means
    # `<vault>/.cerebrum/`. Setting them puts that state outside the vault,
    # e.g. when the vault is a checkout some other tool owns.
    cerebrum_index_path: Path | None = None
    cerebrum_auth_db_path: Path | None = None

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

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

    @field_validator("cerebrum_link_format", mode="before")
    @classmethod
    def _normalize_link_format(cls, value: object) -> object:
        """Ignore case and surrounding spaces; blank means the default.
        Anything else that isn't `markdown` or `wikilink` fails startup."""
        if isinstance(value, str):
            return value.strip().lower() or "markdown"
        return value

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
