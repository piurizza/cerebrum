"""The site's own URL, read from zensical.toml so the checks and the
Makefile never carry a second copy of it.

Usage: site_config.py url|prefix
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

_CONFIG = Path(__file__).parents[1] / "zensical.toml"


def site_url() -> str:
    config = tomllib.loads(_CONFIG.read_text(encoding="utf-8"))
    return str(config["project"]["site_url"])


def site_prefix() -> str:
    """The path the site is served under, e.g. `/cerebrum/`."""
    return urlsplit(site_url()).path or "/"


if __name__ == "__main__":
    if sys.argv[1:] == ["url"]:
        print(site_url())
    elif sys.argv[1:] == ["prefix"]:
        print(site_prefix())
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
