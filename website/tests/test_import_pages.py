"""The import guides show no images of other products (R21): no logos, no
screenshots of their apps. Cerebrum's own screenshots are fine."""

from __future__ import annotations

import re
from pathlib import Path

_IMPORT = Path(__file__).parents[1] / "docs" / "import"
_OWN = "../assets/screenshots/"

_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")
_HTML_IMAGE = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)", re.IGNORECASE)


def foreign_images(text: str) -> list[str]:
    # Examples of image syntax inside code are text, not images.
    text = _CODE.sub("", text)
    sources = _MARKDOWN_IMAGE.findall(text) + _HTML_IMAGE.findall(text)
    return [source for source in sources if not source.startswith(_OWN)]


def test_finds_markdown_and_html_images() -> None:
    text = '![logo](https://example.com/logo.png)\n<img src="other.png">\n'
    assert foreign_images(text) == ["https://example.com/logo.png", "other.png"]


def test_ignores_examples_in_code() -> None:
    assert foreign_images("Write `![](photo.png)` to embed one.") == []


def test_allows_cerebrums_own_screenshots() -> None:
    assert foreign_images("![note](../assets/screenshots/note.webp)") == []


def test_import_pages_show_no_other_products_images() -> None:
    pages = sorted(_IMPORT.glob("*.md"))
    assert pages, "found no import pages"
    found = {
        page.name: images
        for page in pages
        if (images := foreign_images(page.read_text(encoding="utf-8")))
    }
    assert not found, f"images of other products in import guides: {found}"
