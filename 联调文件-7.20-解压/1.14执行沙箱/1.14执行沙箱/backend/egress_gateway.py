from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class AllowlistProxy(BaseHTTPRequestHandler):
    allowed_domains: set[str] = set()
    local_test_domains: set[str] = set()

    def do_GET(self) -> None:
        started = time.time()
        target = self.path
        parsed = urllib.parse.urlparse(target)
        host = parsed.hostname or self.headers.get("Host", "").split(":")[0]
        allowed = host in self.allowed_domains
        record = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "method": "GET",
            "url": target,
            "host": host,
            "allowed": allowed,
        }
        if not allowed:
            record["status"] = 403
            self._write_json(record)
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"blocked by sandbox egress allowlist")
            return

        if host in self.local_test_domains:
            body = (
                "<!doctype html><html><head><title>Sandbox Allowlist Probe</title></head>"
                "<body><h1>Sandbox Allowlist Probe</h1>"
                "<p>served by controlled sandbox egress gateway</p></body></html>"
            ).encode("utf-8")
            record["status"] = 200
            record["duration_ms"] = int((time.time() - started) * 1000)
            record["source"] = "local_test_page"
            self._write_json(record)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        try:
            request = urllib.request.Request(target, headers={"User-Agent": "agent-sandbox-egress-proxy"})
            with urllib.request.urlopen(request, timeout=8) as response:
                body = response.read(4096)
                status = response.getcode()
                record["status"] = status
                record["duration_ms"] = int((time.time() - started) * 1000)
                self._write_json(record)
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)
        except Exception as exc:
            record["status"] = 502
            record["error"] = str(exc)
            self._write_json(record)
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8", errors="replace"))

    def do_CONNECT(self) -> None:
        host = self.path.split(":")[0]
        record = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "method": "CONNECT",
            "url": self.path,
            "host": host,
            "allowed": False,
            "status": 403,
            "note": "CONNECT tunneling is intentionally disabled in this minimal validation proxy.",
        }
        self._write_json(record)
        self.send_response(403)
        self.end_headers()

    def do_POST(self) -> None:
        self._handle_body_request("POST")

    def do_PUT(self) -> None:
        self._handle_body_request("PUT")

    def do_PATCH(self) -> None:
        self._handle_body_request("PATCH")

    def _handle_body_request(self, method: str) -> None:
        started = time.time()
        target = self.path
        parsed = urllib.parse.urlparse(target)
        host = parsed.hostname or self.headers.get("Host", "").split(":")[0]
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        record = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"), "method": method, "url": target,
            "host": host, "allowed": host in self.allowed_domains,
            "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
            "content_type": self.headers.get("Content-Type", ""),
        }
        if not record["allowed"]:
            record["status"] = 403
            self._write_json(record)
            self.send_response(403); self.end_headers(); self.wfile.write(b"blocked by sandbox egress allowlist")
            return
        try:
            request = urllib.request.Request(target, data=body, method=method, headers={"Content-Type": record["content_type"], "User-Agent": "agent-sandbox-egress-proxy"})
            with urllib.request.urlopen(request, timeout=8) as response:
                response_body = response.read(4096)
                record["status"] = response.getcode(); record["duration_ms"] = int((time.time() - started) * 1000)
                self._write_json(record)
                self.send_response(response.getcode()); self.end_headers(); self.wfile.write(response_body)
        except Exception as exc:
            record["status"] = 502; record["error"] = str(exc); self._write_json(record)
            self.send_response(502); self.end_headers(); self.wfile.write(str(exc).encode("utf-8", errors="replace"))

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _write_json(self, record: dict[str, Any]) -> None:
        print(json.dumps(record, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--allow", action="append", default=[])
    parser.add_argument("--serve-local", action="append", default=[])
    args = parser.parse_args()
    AllowlistProxy.allowed_domains = set(args.allow)
    AllowlistProxy.local_test_domains = set(args.serve_local)
    server = ThreadingHTTPServer((args.host, args.port), AllowlistProxy)
    print(json.dumps({"event": "egress_proxy_started", "allowed_domains": sorted(AllowlistProxy.allowed_domains)}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
