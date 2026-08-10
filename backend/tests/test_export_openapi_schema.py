from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_script(*, env: dict[str, str], extra_args: list[str] | None = None) -> str:
    """Runs `cerebrum.scripts.export_openapi_schema` as a real subprocess
    with an explicitly controlled environment, rather than calling its
    `main()` in-process.

    This has to be out-of-process: `conftest.py` sets `AUTH_JWT_SECRET`/
    `AUTH_SETUP_TOKEN` as real, session-wide `os.environ.setdefault` calls
    (not per-test `monkeypatch`) so `cerebrum.main`'s module-level
    `app = create_app()` can construct at import time -- see conftest's
    own comment. Calling the script's `main()` directly from an in-process
    test would silently inherit those, making it impossible to actually
    exercise the "no secrets set" path R1 depends on.
    """
    result = subprocess.run(
        [sys.executable, "-m", "cerebrum.scripts.export_openapi_schema"]
        + (extra_args or []),
        cwd=Path(__file__).parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _base_env() -> dict[str, str]:
    # A deliberately minimal environment -- PATH so the interpreter itself
    # resolves, and nothing else. No AUTH_JWT_SECRET/AUTH_SETUP_TOKEN,
    # no .env file discovery surprises (pydantic-settings reads a real
    # `.env` from cwd by default, so if a developer's machine happens to
    # have `backend/.env` populated, this would silently pass without
    # testing the no-secrets path -- there is no `.env` in this repo
    # checkout's `backend/` by default, matching CI).
    return {"PATH": os.environ.get("PATH", "")}


@pytest.fixture(scope="module")
def base_schema() -> dict:
    """The `--output`-less, no-secrets-set schema, shared by every test
    below that just inspects its content -- `_base_env()`'s invocation is
    identical across those tests, so spawning it once here instead of
    once per test avoids 2 redundant interpreter-startup-plus-full-app-
    construction subprocess spawns."""
    return json.loads(_run_script(env=_base_env()))


def test_no_env_vars_set_produces_valid_schema_json(base_schema: dict) -> None:
    assert "openapi" in base_schema
    assert "/api/notes" in base_schema["paths"]
    assert "/api/graph" in base_schema["paths"]


def test_real_env_vars_already_set_does_not_raise() -> None:
    env = _base_env()
    env["AUTH_JWT_SECRET"] = "z" * 32
    env["AUTH_SETUP_TOKEN"] = "w" * 32
    stdout = _run_script(env=env)
    schema = json.loads(stdout)
    assert "openapi" in schema


def test_output_flag_writes_to_file(tmp_path: Path) -> None:
    output_path = tmp_path / "openapi.json"
    _run_script(env=_base_env(), extra_args=["--output", str(output_path)])
    schema = json.loads(output_path.read_text(encoding="utf-8"))
    assert "openapi" in schema


def test_attachment_upload_response_schema_names_path_field(
    base_schema: dict,
) -> None:
    upload_response = base_schema["components"]["schemas"]["AttachmentUploadResponse"]
    assert upload_response["properties"]["path"]["type"] == "string"


def test_upload_attachments_response_uses_named_schema_not_generic_object(
    base_schema: dict,
) -> None:
    responses = base_schema["paths"]["/api/attachments"]["post"]["responses"]
    content = responses["200"]["content"]["application/json"]["schema"]
    assert content["$ref"].endswith("AttachmentUploadResponse")


@pytest.mark.parametrize("bad_args", [["--output"], ["--bogus-flag"]])
def test_invalid_arguments_exit_nonzero(bad_args: list[str]) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        _run_script(env=_base_env(), extra_args=bad_args)
