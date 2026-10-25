"""Fail when the built site would make a visitor's browser contact another
host (R19): fonts, scripts, stylesheets, images, preconnects, CSS
`url()`/`@import`, and URLs inside the JavaScript bundles.

Ordinary `<a href>` hyperlinks are fine -- they only load when clicked --
and so is the site's own host (its canonical and next/prev links).

The theme's bundle carries loaders for optional features (Mermaid, code
playgrounds, an image lightbox, repository stats) that would fetch from a
CDN or GitHub's API if switched on. Those URLs are listed in
`allowed_bundle_urls.txt` after review; any other URL in a bundle fails, so
a Zensical upgrade that adds a new outbound request is caught here.
`check_runtime_requests.mjs` then proves the listed loaders stay dormant.

Usage: check_no_third_party.py <site-dir> [<site-url>]
(the site URL defaults to `site_url` in zensical.toml)
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from site_config import site_url

_ALLOWLIST = Path(__file__).with_name("allowed_bundle_urls.txt")
_CSS_URL = re.compile(r"""url\(\s*['"]?([^'")\s]+)""")
_CSS_IMPORT = re.compile(r"""@import\s+['"]([^'"]+)""")
_JS_URL = re.compile(r"""https?://[A-Za-z0-9.-]+[A-Za-z0-9/._@%~+-]*""")
# XML namespace identifiers in DOM code, never fetched.
_JS_NAMESPACES = ("http://www.w3.org/",)
# Attributes that make the browser fetch something on page load.
_FETCH_ATTRIBUTES = {"src", "poster", "data"}
# SVG elements whose `href` loads a resource rather than being a link.
_SVG_FETCHING = {"image", "use", "feimage"}
# Inline script types that hold data, not code the browser runs.
_DATA_SCRIPT_TYPES = {"application/json", "application/ld+json", "importmap"}


@dataclass(frozen=True)
class Finding:
    file: str
    url: str


def _is_external(url: str, site_host: str) -> bool:
    if not (url.startswith(("http://", "https://")) or url.startswith("//")):
        return False
    return urlsplit(url if "://" in url else "https:" + url).netloc != site_host


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []
        self.styles: list[str] = []
        self.scripts: list[str] = []
        self._in_style = False
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        for name in _FETCH_ATTRIBUTES & values.keys():
            self.urls.append(values[name])
        if "srcset" in values:
            self.urls.extend(
                part.split()[0] for part in values["srcset"].split(",") if part.strip()
            )
        if tag == "link" and "href" in values:
            self.urls.append(values["href"])
        if tag in _SVG_FETCHING:
            self.urls.extend(values[k] for k in ("href", "xlink:href") if k in values)
        if "style" in values:
            self.styles.append(values["style"])
        self._in_style = tag == "style"
        self._in_script = (
            tag == "script"
            and "src" not in values
            and values.get("type", "").lower() not in _DATA_SCRIPT_TYPES
        )

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"}:
            self._in_style = self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.styles.append(data)
        if self._in_script:
            self.scripts.append(data)


def _css_urls(css: str) -> list[str]:
    return _CSS_URL.findall(css) + _CSS_IMPORT.findall(css)


def _load_allowlist() -> tuple[str, ...]:
    if not _ALLOWLIST.exists():
        return ()
    lines = _ALLOWLIST.read_text(encoding="utf-8").splitlines()
    return tuple(
        line.strip() for line in lines if line.strip() and not line.startswith("#")
    )


def find_external_requests(
    site: Path, site_url: str, allowed_bundle_urls: tuple[str, ...]
) -> list[Finding]:
    host = urlsplit(site_url).netloc
    findings: list[Finding] = []
    for path in sorted(site.rglob("*")):
        if not path.is_file():
            continue
        name = str(path.relative_to(site))
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".html":
            parser = _PageParser()
            parser.feed(text)
            urls = parser.urls + [u for css in parser.styles for u in _css_urls(css)]
            # Inline code is the site's own: no dormant-loader allowlist here.
            urls += [
                url
                for script in parser.scripts
                for url in _JS_URL.findall(script)
                if not url.startswith(_JS_NAMESPACES)
            ]
        elif path.suffix == ".css":
            urls = _css_urls(text)
        elif path.suffix in {".js", ".mjs"}:
            urls = [
                url
                for url in _JS_URL.findall(text)
                if not url.startswith(_JS_NAMESPACES)
                and not url.startswith(allowed_bundle_urls)
            ]
        else:
            continue
        findings.extend(Finding(name, url) for url in urls if _is_external(url, host))
    return findings


def main(argv: list[str]) -> int:
    if len(argv) not in {2, 3}:
        print(__doc__, file=sys.stderr)
        return 2
    url = argv[2] if len(argv) == 3 else site_url()
    findings = find_external_requests(Path(argv[1]), url, _load_allowlist())
    for finding in findings:
        print(f"{finding.file}: loads {finding.url}", file=sys.stderr)
    if findings:
        count = len(findings)
        print(f"{count} third-party request(s) in the built site.", file=sys.stderr)
        return 1
    print("No third-party requests in the built site.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
