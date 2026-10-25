"""Fail when a link or asset inside the built site points at a file that
was not built: images, nav entries, and links in raw HTML blocks, which
Zensical's own validation (markdown links only) does not see.

Usage: check_local_links.py <site-dir> [<site-url>]
(the site URL defaults to `site_url` in zensical.toml)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from site_config import site_url

_SKIP_SCHEMES = ("mailto:", "tel:", "data:", "javascript:")
_LINK_ATTRIBUTES = {"href", "src"}


@dataclass(frozen=True)
class BrokenLink:
    file: str
    target: str


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.targets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in _LINK_ATTRIBUTES and value:
                self.targets.append(value)


def _resolve(site: Path, page: Path, target: str, site_url: str) -> Path | None:
    """The file `target` refers to, or None when it is not a local link."""
    if target.startswith(site_url):
        path = target[len(site_url) :]
        base = site
    elif target.startswith(("http://", "https://", "//", "#")) or target.startswith(
        _SKIP_SCHEMES
    ):
        return None
    elif target.startswith("/"):
        # Root-absolute, as on the 404 page: under the site's path prefix
        # (`/cerebrum/` on a project page; find_broken_links rejects others).
        path = target.removeprefix(urlsplit(site_url).path)
        base = site
    else:
        path = target
        base = page.parent
    path = unquote(urlsplit(path).path)
    resolved = (base / path) if path else base
    return resolved / "index.html" if path == "" or path.endswith("/") else resolved


def _outside_prefix(target: str, prefix: str) -> bool:
    """A root-absolute link without the site's path prefix resolves locally
    but 404s once published under that prefix."""
    is_root_absolute = target.startswith("/") and not target.startswith("//")
    return is_root_absolute and not target.startswith(prefix)


def find_broken_links(site: Path, site_url: str) -> list[BrokenLink]:
    prefix = urlsplit(site_url).path or "/"
    broken: list[BrokenLink] = []
    for page in sorted(site.rglob("*.html")):
        parser = _LinkParser()
        parser.feed(page.read_text(encoding="utf-8", errors="replace"))
        for target in parser.targets:
            if _outside_prefix(target, prefix):
                broken.append(BrokenLink(str(page.relative_to(site)), target))
                continue
            resolved = _resolve(site, page, target, site_url)
            if resolved is None:
                continue
            if not (resolved.is_file() or (resolved / "index.html").is_file()):
                broken.append(BrokenLink(str(page.relative_to(site)), target))
    return broken


def main(argv: list[str]) -> int:
    if len(argv) not in {2, 3}:
        print(__doc__, file=sys.stderr)
        return 2
    broken = find_broken_links(Path(argv[1]), argv[2] if len(argv) == 3 else site_url())
    for link in broken:
        print(f"{link.file}: broken link {link.target}", file=sys.stderr)
    if broken:
        print(f"{len(broken)} broken local link(s) in the built site.", file=sys.stderr)
        return 1
    print("Every local link and asset resolves.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
