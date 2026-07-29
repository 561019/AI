from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app.core.config import settings
from app.services.embedding.bge_provider import BGEProvider


class BGEWorkerState:
    def __init__(self, *, provider: BGEProvider | None = None) -> None:
        self.provider = provider or BGEProvider()
        self.keep_warm = settings.bge_keep_warm
        self.idle_timeout_seconds = settings.bge_idle_timeout_seconds
        self.embedding_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.active_requests = 0
        self.model_loaded = False
        self.last_activity = time.monotonic()

    def embed(self, texts: list[str]) -> list[list[float]]:
        with self.state_lock:
            self.active_requests += 1
        try:
            with self.embedding_lock:
                embeddings = self.provider.embed(texts)
                self.model_loaded = True
                return embeddings
        finally:
            with self.state_lock:
                self.active_requests -= 1
                self.last_activity = time.monotonic()

    def should_shutdown(self) -> bool:
        if self.keep_warm:
            return False
        with self.state_lock:
            return (
                self.active_requests == 0
                and time.monotonic() - self.last_activity >= self.idle_timeout_seconds
            )


class BGEWorkerHandler(BaseHTTPRequestHandler):
    state: BGEWorkerState

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._write_json(404, {"error": "not_found"})
            return
        self._write_json(
            200,
            {
                "status": "ok",
                "model_name": self.state.provider.model_name,
                "model_loaded": self.state.model_loaded,
                "keep_warm": self.state.keep_warm,
                "idle_timeout_seconds": self.state.idle_timeout_seconds,
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/shutdown":
            self._write_json(200, {"status": "shutting_down"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path != "/embed":
            self._write_json(404, {"error": "not_found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            texts = payload.get("texts") if isinstance(payload, dict) else None
            if not isinstance(texts, list) or not texts or not all(isinstance(text, str) for text in texts):
                self._write_json(400, {"error": "texts_must_be_a_non_empty_string_list"})
                return
            embeddings = self.state.embed(texts)
            self._write_json(200, {"embeddings": embeddings})
        except Exception as error:
            self._write_json(500, {"error": type(error).__name__, "message": str(error)})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_worker(*, state: BGEWorkerState | None = None) -> None:
    worker_state = state or BGEWorkerState()
    handler = type("ConfiguredBGEWorkerHandler", (BGEWorkerHandler,), {"state": worker_state})
    server = ThreadingHTTPServer((settings.bge_worker_host, settings.bge_worker_port), handler)

    if not worker_state.keep_warm:
        def stop_when_idle() -> None:
            while not worker_state.should_shutdown():
                time.sleep(0.25)
            server.shutdown()

        threading.Thread(target=stop_when_idle, daemon=True).start()

    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()


if __name__ == "__main__":
    run_worker()
