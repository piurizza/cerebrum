from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from check_demo_compose import PROJECT, validate


def _config(workdir: Path) -> dict[str, Any]:
    """A resolved `docker compose config` for a correctly isolated stack."""
    return {
        "name": PROJECT,
        "services": {
            "backend": {
                "image": "ghcr.io/piurizza/cerebrum-backend:docs-demo",
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(workdir / "vault"),
                        "target": "/data/vault",
                    }
                ],
            },
            "frontend": {
                "image": "ghcr.io/piurizza/cerebrum-frontend:docs-demo",
                "ports": [
                    {"host_ip": "127.0.0.1", "published": "18861", "target": 80},
                    {"host_ip": "127.0.0.1", "published": "18862", "target": 443},
                ],
                "volumes": [
                    {"type": "volume", "source": "cerebrum_tls_certs", "target": "/c"}
                ],
            },
        },
        "volumes": {"cerebrum_tls_certs": {"name": f"{PROJECT}_cerebrum_tls_certs"}},
    }


def _errors(config: dict[str, Any], workdir: Path) -> list[str]:
    return validate(config, workdir, {"18861", "18862"})


def test_accepts_an_isolated_stack(tmp_path: Path) -> None:
    assert _errors(_config(tmp_path), tmp_path) == []


def test_refuses_another_project_name(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config["name"] = "cerebrum"
    assert any("project" in error for error in _errors(config, tmp_path))


def test_refuses_the_repos_vault_folder(tmp_path: Path) -> None:
    # What a missing CEREBRUM_VAULT_HOST_PATH falls back to: ./vault.
    config = _config(tmp_path)
    mount = config["services"]["backend"]["volumes"][0]
    mount["source"] = "/home/someone/projects/cerebrum/vault"
    assert any("bind mount" in error for error in _errors(config, tmp_path))


def test_refuses_the_published_image_tags(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config["services"]["backend"]["image"] = "ghcr.io/piurizza/cerebrum-backend:latest"
    assert any("image" in error for error in _errors(config, tmp_path))


def test_refuses_ports_open_beyond_this_machine(tmp_path: Path) -> None:
    # The live .env opens 0.0.0.0 on 8080: a sign it was read.
    config = _config(tmp_path)
    config["services"]["frontend"]["ports"][0] = {
        "host_ip": "0.0.0.0",
        "published": "8080",
        "target": 80,
    }
    errors = _errors(config, tmp_path)
    assert any("port" in error for error in errors)


def test_refuses_a_volume_shared_with_another_project(tmp_path: Path) -> None:
    config = copy.deepcopy(_config(tmp_path))
    config["volumes"]["cerebrum_tls_certs"]["name"] = "cerebrum_cerebrum_tls_certs"
    assert any("volume" in error for error in _errors(config, tmp_path))
