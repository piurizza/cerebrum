from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# JWTs and setup tokens are only as strong as the secret they're signed/
# compared against; 32 bytes (256 bits) matches the minimum HMAC-SHA256
# needs to be collision/brute-force resistant. Enforced below rather than
# left to deployers, since a short or missing secret fails silently at
# request time (any string "works") instead of loudly at startup.
_MIN_AUTH_SECRET_BYTES = 32


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "Cerebrum"
    log_level: str = "INFO"

    cerebrum_vault_path: Path = Path("./vault")
    cerebrum_index_path: Path | None = None

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

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
        return self.cerebrum_vault_path / ".cerebrum" / "auth.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
