from __future__ import annotations

from pathlib import Path

import pytest

import check_no_third_party
from check_no_third_party import find_external_requests

SITE_URL = "https://example.github.io/cerebrum/"


def _site(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def _found(
    tmp_path: Path, files: dict[str, str], allowed: tuple[str, ...] = ()
) -> list[str]:
    site = _site(tmp_path, files)
    return [finding.url for finding in find_external_requests(site, SITE_URL, allowed)]


def test_flags_a_google_fonts_stylesheet(tmp_path: Path) -> None:
    page = (
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto">'
    )
    assert _found(tmp_path, {"index.html": page}) == [
        "https://fonts.googleapis.com/css?family=Roboto"
    ]


def test_flags_every_link_rel_not_only_stylesheets(tmp_path: Path) -> None:
    page = '<link rel="preconnect" href="https://fonts.gstatic.com">'
    assert _found(tmp_path, {"index.html": page}) == ["https://fonts.gstatic.com"]


def test_flags_scripts_images_srcset_and_protocol_relative(tmp_path: Path) -> None:
    page = (
        '<script src="https://cdn.example/x.js"></script>'
        '<img src="//img.example/a.png"'
        ' srcset="/local.png 1x, https://img.example/b.png 2x">'
    )
    assert sorted(_found(tmp_path, {"index.html": page})) == [
        "//img.example/a.png",
        "https://cdn.example/x.js",
        "https://img.example/b.png",
    ]


def test_flags_css_url_and_import(tmp_path: Path) -> None:
    css = (
        '@import url("https://fonts.example/f.css");'
        " .a { background: url(https://img.example/b.png) }"
    )
    assert sorted(_found(tmp_path, {"assets/main.css": css})) == [
        "https://fonts.example/f.css",
        "https://img.example/b.png",
    ]


def test_flags_inline_style_urls(tmp_path: Path) -> None:
    page = '<div style="background:url(https://img.example/c.png)"></div>'
    assert _found(tmp_path, {"index.html": page}) == ["https://img.example/c.png"]


def test_flags_unknown_urls_in_javascript_bundles(tmp_path: Path) -> None:
    js = 'fetch("https://api.github.com/repos/"+x)'
    assert _found(tmp_path, {"assets/bundle.js": js}) == [
        "https://api.github.com/repos/"
    ]


def _found_with_vendor_list(
    tmp_path: Path,
    files: dict[str, str],
    bundle: tuple[str, ...],
    vendor: tuple[str, ...],
) -> list[str]:
    site = _site(tmp_path, files)
    return [f.url for f in find_external_requests(site, SITE_URL, bundle, vendor)]


def test_vendored_libraries_use_their_own_allowlist(tmp_path: Path) -> None:
    # A reviewed licence link in a library the site serves itself passes;
    # the same text in the theme's bundle is not excused by that list.
    text = 'var x="https://example.org/license";'
    files = {
        "assets/javascripts/vendor/mermaid.min.js": text,
        "assets/javascripts/bundle.js": text,
    }
    found = _found_with_vendor_list(tmp_path, files, (), ("https://example.org/",))
    assert found == ["https://example.org/license"]


def test_flags_a_new_url_in_a_vendored_library(tmp_path: Path) -> None:
    # A library update that starts loading from a CDN fails the check, and
    # the theme's dormant-loader allowlist doesn't excuse it.
    files = {
        "assets/javascripts/vendor/mermaid.min.js": (
            'var a="https://example.org/license";'
            'load("https://unpkg.com/mermaid@12/dist/x.js");'
        ),
    }
    found = _found_with_vendor_list(
        tmp_path, files, ("https://unpkg.com/mermaid",), ("https://example.org/",)
    )
    assert found == ["https://unpkg.com/mermaid@12/dist/x.js"]


def test_reviewed_vendor_allowlist_covers_the_installed_mermaid() -> None:
    # The real list must cover the library `make docs-assets` installs; run
    # it first. Skipped when node_modules is absent.
    library = Path(__file__).parents[1] / "node_modules/mermaid/dist/mermaid.min.js"
    if not library.exists():
        pytest.skip("run `make docs-assets` to install the vendored libraries")
    allowed = check_no_third_party._load_allowlist(
        check_no_third_party._VENDOR_ALLOWLIST
    )
    text = library.read_text(encoding="utf-8", errors="replace")
    urls = [
        url
        for url in check_no_third_party._JS_URL.findall(text)
        if not url.startswith(check_no_third_party._JS_NAMESPACES)
        and not url.startswith(allowed)
    ]
    assert urls == []


def test_still_flags_html_loading_from_another_host(tmp_path: Path) -> None:
    page = '<script src="https://cdn.example.com/assets/javascripts/vendor/m.js">'
    assert _found(tmp_path, {"index.html": page}) == [
        "https://cdn.example.com/assets/javascripts/vendor/m.js"
    ]


def test_allows_reviewed_dormant_loader_urls(tmp_path: Path) -> None:
    js = 'load("https://unpkg.com/mermaid@11/dist/mermaid.min.js")'
    allowed = ("https://unpkg.com/mermaid",)
    assert _found(tmp_path, {"assets/bundle.js": js}, allowed) == []


def test_ignores_xml_namespaces_in_javascript(tmp_path: Path) -> None:
    js = 'createElementNS("http://www.w3.org/2000/svg","svg")'
    assert _found(tmp_path, {"assets/bundle.js": js}) == []


def test_ignores_hyperlinks_and_the_sites_own_host(tmp_path: Path) -> None:
    page = (
        '<a href="https://github.com/piurizza/cerebrum">source</a>'
        f'<link rel="canonical" href="{SITE_URL}">'
        '<img src="./assets/shot.webp">'
    )
    assert _found(tmp_path, {"index.html": page}) == []


def test_flags_urls_in_inline_scripts_without_the_bundle_allowlist(
    tmp_path: Path,
) -> None:
    page = (
        "<script>var s=document.createElement('script');"
        "s.src='https://www.googletagmanager.com/gtag/js';</script>"
        '<script type="application/ld+json">{"url": "https://schema.example/x"}</script>'
    )
    allowed = ("https://www.googletagmanager.com",)
    assert _found(tmp_path, {"index.html": page}, allowed) == [
        "https://www.googletagmanager.com/gtag/js"
    ]


def test_flags_svg_images_and_uses(tmp_path: Path) -> None:
    page = (
        '<svg><image href="https://img.example/a.png"/>'
        '<use xlink:href="https://img.example/sprite.svg#i"/>'
        '<a href="https://example.com/link">link</a></svg>'
    )
    assert sorted(_found(tmp_path, {"index.html": page})) == [
        "https://img.example/a.png",
        "https://img.example/sprite.svg#i",
    ]


def test_loads_the_allowlist_without_comments_or_blanks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowlist = tmp_path / "allowed.txt"
    allowlist.write_text("# a comment\n\nhttps://unpkg.com/mermaid\n", "utf-8")
    monkeypatch.setattr(check_no_third_party, "_ALLOWLIST", allowlist)
    assert check_no_third_party._load_allowlist() == ("https://unpkg.com/mermaid",)


def test_main_exits_nonzero_on_a_finding(tmp_path: Path) -> None:
    _site(tmp_path, {"index.html": '<script src="https://cdn.example/x.js"></script>'})
    assert check_no_third_party.main(["prog", str(tmp_path), SITE_URL]) == 1
    (tmp_path / "index.html").write_text("<p>clean</p>", encoding="utf-8")
    assert check_no_third_party.main(["prog", str(tmp_path), SITE_URL]) == 0
