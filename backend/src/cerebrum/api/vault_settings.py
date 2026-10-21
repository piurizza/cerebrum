from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from cerebrum.settings import get_settings

router = APIRouter()


class VaultSettings(BaseModel):
    daily_note_folder: str
    templates_folder: str
    link_format: Literal["markdown", "wikilink"]


@router.get("/vault-settings", response_model=VaultSettings)
def get_vault_settings() -> VaultSettings:
    """Server-side vault conventions the web app needs, already normalized
    by `Settings` (no leading/trailing slashes, never empty), and the link
    form the editor's `[[` picker inserts."""
    settings = get_settings()
    return VaultSettings(
        daily_note_folder=settings.cerebrum_daily_note_folder,
        templates_folder=settings.cerebrum_templates_folder,
        link_format=settings.cerebrum_link_format,
    )
