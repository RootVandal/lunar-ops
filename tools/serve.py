"""Local static server for web/ with caching disabled (development only).

    python tools/serve.py 8801
"""
import functools
import http.server
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


class NoCache(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8801
    handler = functools.partial(NoCache, directory=str(WEB))
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
