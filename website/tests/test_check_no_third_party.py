from __future__ import annotations

from pathlib import Path

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
