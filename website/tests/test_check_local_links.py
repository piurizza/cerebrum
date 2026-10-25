from __future__ import annotations

from pathlib import Path

from check_local_links import find_broken_links

SITE_URL = "https://example.github.io/cerebrum/"


def _site(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def _broken(tmp_path: Path, files: dict[str, str]) -> list[str]:
    return [link.target for link in find_broken_links(_site(tmp_path, files), SITE_URL)]


def test_resolves_pages_directories_and_assets(tmp_path: Path) -> None:
    files = {
        "index.html": (
            '<a href="./quick-start/">qs</a><a href="features/#tags">f</a>'
            '<img src="assets/shot.webp"><a href="#top">top</a>'
            '<a href="https://github.com/x">ext</a><a href="mailto:a@b.c">m</a>'
        ),
        "quick-start/index.html": '<a href="../">home</a>',
        "features/index.html": "",
        "assets/shot.webp": "",
    }
    assert _broken(tmp_path, files) == []


def test_flags_a_missing_image(tmp_path: Path) -> None:
    assert _broken(tmp_path, {"index.html": '<img src="assets/missing.webp">'}) == [
        "assets/missing.webp"
    ]


def test_flags_a_nav_entry_whose_page_does_not_exist(tmp_path: Path) -> None:
    page = '<nav><a class="md-nav__link" href="./import/">Import</a></nav>'
    assert _broken(tmp_path, {"index.html": page}) == ["./import/"]


def test_flags_links_to_the_sites_own_url_that_do_not_resolve(tmp_path: Path) -> None:
    files = {
        "index.html": (
            f'<link rel="next" href="{SITE_URL}gone/"><a href="{SITE_URL}">home</a>'
        )
    }
    assert _broken(tmp_path, files) == [f"{SITE_URL}gone/"]


def test_flags_broken_links_in_raw_html_blocks(tmp_path: Path) -> None:
    page = '<div class="grid cards"><a href="../running/backups/">Backups</a></div>'
    assert _broken(tmp_path, {"help/index.html": page}) == ["../running/backups/"]


def test_resolves_root_absolute_links_under_the_site_prefix(tmp_path: Path) -> None:
    files = {
        "404.html": (
            '<a href="/cerebrum/quick-start/">qs</a><a href="/cerebrum/gone/">x</a>'
        ),
        "quick-start/index.html": "",
    }
    assert _broken(tmp_path, files) == ["/cerebrum/gone/"]
