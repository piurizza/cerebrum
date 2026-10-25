from __future__ import annotations

import tomllib
from pathlib import Path

import site_config

_CONFIG = Path(__file__).parents[1] / "zensical.toml"


def test_reads_the_site_url_from_the_config() -> None:
    assert site_config.site_url() == "https://piurizza.github.io/cerebrum/"
    assert site_config.site_prefix() == "/cerebrum/"


def test_never_sets_repo_url() -> None:
    # With a repo_url the theme fetches star and fork counts from GitHub's
    # API in every visitor's browser (R19); the bundle allowlist relies on
    # this staying unset.
    project = tomllib.loads(_CONFIG.read_text(encoding="utf-8"))["project"]
    assert "repo_url" not in project
    assert project["theme"]["font"] is False
