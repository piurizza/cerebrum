from __future__ import annotations

from fastapi import APIRouter, Response

from cerebrum.settings import get_settings

router = APIRouter()


@router.get("/health")
def health_check(response: Response) -> dict[str, str]:
    settings = get_settings()
    vault_ok = settings.cerebrum_vault_path.exists()
    if not vault_ok:
        response.status_code = 503
    return {
        "status": "ok" if vault_ok else "degraded",
        "app_name": settings.app_name,
    }
