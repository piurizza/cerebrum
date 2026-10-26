"""Every release in CHANGELOG.md has an upgrade page (R14).

The release workflow runs this on the release tag before publishing, so a
release without its page never replaces the live site.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).parents[2]
_UPGRADE = _REPO / "website" / "docs" / "upgrade"

# Both heading styles release-please has written: `## 0.1.0 (date)` for the
# first release, `## [0.4.0](compare-url) (date)` after it.
_VERSION = re.compile(r"^## \[?(\d+\.\d+\.\d+)\]?", re.MULTILINE)


def changelog_versions(text: str) -> list[str]:
    return _VERSION.findall(text)


def missing_pages(versions: list[str], folder: Path) -> list[str]:
    return [v for v in versions if not (folder / f"{v}.md").is_file()]


def test_reads_both_heading_styles() -> None:
    text = (
        "# Changelog\n\n"
        "## [0.4.0](https://example.com/compare/v0.3.0...v0.4.0) (2026-10-21)\n\n"
        "### Features\n\n"
        "## 0.1.0 (2026-10-16)\n"
    )
    assert changelog_versions(text) == ["0.4.0", "0.1.0"]


def test_names_a_version_without_a_page(tmp_path: Path) -> None:
    (tmp_path / "0.1.0.md").write_text("# 0.1.0\n", encoding="utf-8")
    assert missing_pages(["0.2.0", "0.1.0"], tmp_path) == ["0.2.0"]


def test_every_release_has_an_upgrade_page() -> None:
    versions = changelog_versions((_REPO / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert versions, "found no versions in CHANGELOG.md"
    missing = missing_pages(versions, _UPGRADE)
    assert not missing, (
        f"no upgrade page for {', '.join(missing)}: add "
        "website/docs/upgrade/<version>.md and list it in zensical.toml"
    )
