"""Refuse to start the screenshot stack unless it is fully isolated.

Reads `docker compose config --format json` on stdin and fails unless the
stack uses its own project name, mounts only folders inside its work
folder, runs the `docs-demo` image tags (never retagging the `latest`
images a real install runs), keeps its volumes to itself, and listens only
on this machine on the expected ports. Ports open on 0.0.0.0, or on the
ports a real `.env` sets, would mean a real `.env` was read.

Usage: docker compose ... config --format json |
       check_demo_compose.py <work-folder> <port> [<port> ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT = "cerebrum-docs-demo"
IMAGE_TAG = ":docs-demo"


def validate(config: dict[str, Any], workdir: Path, ports: set[str]) -> list[str]:
    errors: list[str] = []
    root = workdir.resolve()
    if config.get("name") != PROJECT:
        errors.append(f"project name is {config.get('name')!r}, expected {PROJECT!r}")
    for name, service in config.get("services", {}).items():
        image = service.get("image", "")
        if not image.endswith(IMAGE_TAG):
            errors.append(f"{name}: image {image!r} does not use the {IMAGE_TAG} tag")
        for mount in service.get("volumes", []):
            if mount.get("type") != "bind":
                continue
            source = Path(mount.get("source", "")).resolve()
            if not source.is_relative_to(root):
                errors.append(f"{name}: bind mount {source} is outside {root}")
        for port in service.get("ports", []):
            if (
                port.get("host_ip") != "127.0.0.1"
                or str(port.get("published")) not in ports
            ):
                errors.append(
                    f"{name}: port {port} is not 127.0.0.1 on {sorted(ports)}"
                )
    for key, volume in config.get("volumes", {}).items():
        if not str(volume.get("name", "")).startswith(f"{PROJECT}_"):
            errors.append(f"volume {key} resolves to {volume.get('name')!r}")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    config = json.load(sys.stdin)
    errors = validate(config, Path(argv[1]), set(argv[2:]))
    for error in errors:
        print(f"refusing to start: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
