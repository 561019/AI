from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class CredentialBroker(BaseHTTPRequestHandler):
    credential_handle: str = ""
    secret: str = ""
    audit_events: list[dict[str, Any]] = []

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        handle = params.get("handle", [""])[0]
        if parsed.path == "/audit":
            self._json({"events": self.audit_events})
            return
        if parsed.path != "/use":
            self.send_response(404)
            self.end_headers()
            return

        allowed = handle == self.credential_handle
        record = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event": "credential_use",
            "handle_valid": allowed,
            "plaintext_secret_returned": False,
        }
        self.audit_events.append(record)
        if not allowed:
            self._json({"ok": False, "error": "invalid credential handle"}, status=403)
            return

        digest = hashlib.sha256(self.secret.encode("utf-8")).hexdigest()[:16]
        masked = self.secret[:3] + "***" + self.secret[-3:]
        self._json({
            "ok": True,
            "credential_result": "authorized",
            "secret_sha256_prefix": digest,
            "masked_secret": masked,
            "plaintext_secret": None,
        })

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        print(json.dumps({"status": status, **payload}, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--handle", required=True)
    parser.add_argument("--secret", required=True)
    args = parser.parse_args()
    CredentialBroker.credential_handle = args.handle
    CredentialBroker.secret = args.secret
    CredentialBroker.audit_events = []
    server = ThreadingHTTPServer((args.host, args.port), CredentialBroker)
    print(json.dumps({"event": "credential_broker_started", "handle": args.handle, "secret_loaded": True}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
