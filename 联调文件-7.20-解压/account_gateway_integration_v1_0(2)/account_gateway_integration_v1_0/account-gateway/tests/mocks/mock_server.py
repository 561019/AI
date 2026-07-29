#!/usr/bin/env python3
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


DEFAULT_PORTS = (9201, 9202, 9203)
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "data_ownership.json"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
STATIC_FIXTURES = {
    "/org/structure": FIXTURES_DIR / "org_structure.json",
    "/policy/seed": FIXTURES_DIR / "policy_seed.json",
    "/hr/source": FIXTURES_DIR / "hr_source.json",
}


def load_ownership_fixture(path=FIXTURE_PATH):
    with Path(path).open("r", encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def load_static_fixtures(paths=STATIC_FIXTURES):
    fixtures = {}
    for route, path in paths.items():
        with path.open("r", encoding="utf-8") as fixture_file:
            fixtures[route] = json.load(fixture_file)
    return fixtures


def make_handler(ownership, static_fixtures=None):
    static_fixtures = static_fixtures or {}

    class MockHandler(BaseHTTPRequestHandler):
        server_version = "L1MockHTTP/1.0"
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path in static_fixtures:
                self._send_json(200, static_fixtures[parsed.path])
                return

            parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]

            if len(parts) == 2 and parts[0] == "ownership":
                self._handle_ownership(parts[1])
                return

            if len(parts) == 3 and parts[0] == "ownership" and parts[1] == "by_user":
                self._handle_ownership_by_user(parts[2])
                return

            self._send_json(404, {"error": "not_found"})

        def do_POST(self):
            self._method_not_allowed()

        def do_PUT(self):
            self._method_not_allowed()

        def do_DELETE(self):
            self._method_not_allowed()

        def log_message(self, format, *args):
            return

        def _handle_ownership(self, resource_id):
            owner_id = ownership.get(resource_id)
            if owner_id is None:
                self._send_json(404, {"error": "resource_not_found", "resource_id": resource_id})
                return

            self._send_json(200, {"resource_id": resource_id, "owner_id": owner_id})

        def _handle_ownership_by_user(self, user_id):
            resources = [
                {"resource_id": resource_id, "owner_id": owner_id}
                for resource_id, owner_id in ownership.items()
                if owner_id == user_id
            ]
            self._send_json(200, {"user_id": user_id, "resources": resources})

        def _method_not_allowed(self):
            self._send_json(405, {"error": "method_not_allowed"})

        def _send_json(self, status_code, payload):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return MockHandler


def serve_ports(ports, fixture_path=FIXTURE_PATH):
    ownership = load_ownership_fixture(fixture_path)
    static_fixtures = load_static_fixtures()
    handler = make_handler(ownership, static_fixtures)
    servers = []

    for port in ports:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        print(f"mock listening on http://127.0.0.1:{port}", flush=True)

    return servers


def parse_args():
    parser = argparse.ArgumentParser(description="Start L1 mock HTTP servers.")
    parser.add_argument("--ports", nargs="+", type=int, default=list(DEFAULT_PORTS))
    parser.add_argument("--fixture", default=str(FIXTURE_PATH))
    return parser.parse_args()


def main():
    args = parse_args()
    servers = serve_ports(args.ports, args.fixture)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        for server in servers:
            server.shutdown()


if __name__ == "__main__":
    main()
