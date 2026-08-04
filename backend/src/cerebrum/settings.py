from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "Cerebrum"
    log_level: str = "INFO"

    cerebrum_vault_path: Path = Path("./vault")
    cerebrum_index_path: Path | None = None

    cors_origins: list[str] = ["http://localhost:5173"]

    mcp_enabled: bool = True
    mcp_allow_stub_auth: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def index_path(self) -> Path:
        if self.cerebrum_index_path is not None:
            return self.cerebrum_index_path
        return self.cerebrum_vault_path / ".cerebrum" / "index.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
