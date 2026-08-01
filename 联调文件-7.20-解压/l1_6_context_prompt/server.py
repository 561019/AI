from __future__ import annotations

from http.server import ThreadingHTTPServer

from app.db import init_db
from app.http_api import ApiHandler


HOST = "127.0.0.1"
PORT = 8765


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), ApiHandler)
    print(f"L1.6 Context & Prompt MVP running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()

