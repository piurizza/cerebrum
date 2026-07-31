from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_degraded_when_vault_missing(client: TestClient, vault: Path) -> None:
    shutil.rmtree(vault)

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
