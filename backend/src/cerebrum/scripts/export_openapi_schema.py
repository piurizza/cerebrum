"""Export the app's OpenAPI schema as JSON, with no running server, no
`.env`, and no vault required.

Building the FastAPI app is enough to get its route/schema definitions --
`create_app()`'s `lifespan` (which starts the watcher, connects the DB,
etc., see `main.py`) never runs unless something actually serves requests
through the app. The only real obstacle is `Settings` requiring
`AUTH_JWT_SECRET`/`AUTH_SETUP_TOKEN` with no defaults (by design -- see
`settings.py`); this script supplies build-time-only placeholders via
`os.environ.setdefault` *before* importing anything that constructs
`Settings`, so a bare environment (CI, a fresh clone) needs no setup. A
real `.env`'s values are never overwritten, since `setdefault` only fills
in a var that isn't already set.

Frontend codegen (`openapi-typescript`, see the Makefile's
`generate-api-types` target) consumes this script's output.
"""

from __future__ import annotations

import argparse
import json
import os

# Must run before any import that triggers `get_settings()` -- in
# particular before `from cerebrum.main import app` below, since that
# import itself builds `cerebrum.main`'s module-level `app = create_app()`
# (see that module's own comment on why). Importing the already-built
# `app` here -- rather than calling `create_app()` again -- avoids paying
# for a second full app (and, when MCP is enabled, a second MCP server)
# construction on every run of this script.
os.environ.setdefault("AUTH_JWT_SECRET", "0" * 32)
os.environ.setdefault("AUTH_SETUP_TOKEN", "1" * 32)

# pylint: disable=wrong-import-position
from cerebrum.main import app  # noqa: E402

# pylint: enable=wrong-import-position


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the schema JSON to this path instead of stdout.",
    )
    args = parser.parse_args(argv)

    schema = json.dumps(app.openapi(), indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(schema)
            f.write("\n")
    else:
        print(schema)


if __name__ == "__main__":
    main()
