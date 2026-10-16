"""Stand-in Cerebrum server for the desktop smoke test.

Answers the two requests the desktop app makes on launch -- the health
check, then loading the app -- and appends every request line to a log
file the test reads. Standard library only, so it runs on any CI runner.

Usage: python smoke_server.py <port> <log-file>
"""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = b"<!doctype html><title>Cerebrum smoke test</title><h1>smoke-test-page</h1>"


def main() -> None:
    port, log_path = int(sys.argv[1]), Path(sys.argv[2])

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 -- http.server naming
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"GET {self.path}\n")
            if self.path.rstrip("/").endswith("/api/health"):
                body, content_type = b'{"status":"ok"}', "application/json"
            else:
                body, content_type = PAGE, "text/html"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
