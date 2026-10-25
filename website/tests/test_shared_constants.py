"""The demo-vault sentinel, project name and image tag are shared between
Python and the shell/JS scripts; these keep the copies in step."""

from __future__ import annotations

from pathlib import Path

from check_demo_compose import IMAGE_TAG, PROJECT
from make_demo_vault import SENTINEL_PATH

_SCRIPTS = Path(__file__).parents[1] / "scripts"


def test_screenshot_script_checks_the_generators_sentinel() -> None:
    script = (_SCRIPTS / "screenshots.mjs").read_text(encoding="utf-8")
    assert f'const SENTINEL = "{SENTINEL_PATH}";' in script


def test_stack_script_uses_the_validators_project_and_tag() -> None:
    script = (_SCRIPTS / "demo_stack.sh").read_text(encoding="utf-8")
    assert f"PROJECT={PROJECT}\n" in script
    assert f"CEREBRUM_VERSION={IMAGE_TAG.removeprefix(':')}\n" in script
