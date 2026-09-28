"""Serve the browser build locally, with the headers it needs in production.

The same headers any real host must send, written down once so the local
server, the Android shell and the deployed site cannot quietly disagree:

* ``script-src 'wasm-unsafe-eval'`` -- compiling WebAssembly is an eval as far
  as CSP is concerned. Without it the page loads and Python never starts.
* ``application/wasm`` for ``.wasm``, or streaming compilation is refused.
* No third-party origin anywhere: the build fetches nothing from outside.

    python3.11 tools/web/serve.py [--port 8737] [--dir build/web]
"""

from __future__ import annotations

import argparse
import functools
import http.server
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CSP = (
    "default-src 'self'; "
    "script-src 'self' 'wasm-unsafe-eval'; "
    "worker-src 'self'; "
    "connect-src 'self'; "
    # Inline style *attributes* only (a computed font size, an animation
    # delay). Scripts stay 'self': no inline script exists to allow.
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data:; "
    "manifest-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)

HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}

TYPES = {
    ".wasm": "application/wasm",
    ".mjs": "text/javascript",
    ".js": "text/javascript",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".woff2": "font/woff2",
    ".zip": "application/zip",
    ".py": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **TYPES}

    def end_headers(self) -> None:
        for name, value in HEADERS.items():
            self.send_header(name, value)
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(format, *args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8737)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--dir", type=Path, default=ROOT / "build" / "web")
    args = parser.parse_args(argv)
    handler = functools.partial(Handler, directory=str(args.dir))
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as server:
        print(f"serving {args.dir} on http://{args.host}:{args.port}/")
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
