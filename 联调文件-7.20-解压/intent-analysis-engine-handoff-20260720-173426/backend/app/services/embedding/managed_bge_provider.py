from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any

import httpx

from app.core.config import BACKEND_ROOT, settings
from app.services.embedding.base import EmbeddingProviderError


class ManagedBGEProvider:
    """Calls a localhost BGE worker whose process can release model memory when idle."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        dimension: int | None = None,
        host: str | None = None,
        port: int | None = None,
        keep_warm: bool | None = None,
        idle_timeout_seconds: float | None = None,
        startup_timeout_seconds: float | None = None,
        request_timeout_seconds: float | None = None,
        client: Any | None = None,
        process_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.model_name = model_name or settings.embedding_model_name
        self._dimension = dimension or settings.bge_embedding_dimension
        self.host = host or settings.bge_worker_host
        self.port = port or settings.bge_worker_port
        self.keep_warm = settings.bge_keep_warm if keep_warm is None else keep_warm
        self.idle_timeout_seconds = (
            settings.bge_idle_timeout_seconds if idle_timeout_seconds is None else idle_timeout_seconds
        )
        self.startup_timeout_seconds = (
            settings.bge_worker_startup_timeout_seconds
            if startup_timeout_seconds is None
            else startup_timeout_seconds
        )
        self.request_timeout_seconds = (
            settings.bge_worker_request_timeout_seconds
            if request_timeout_seconds is None
            else request_timeout_seconds
        )
        self.base_url = f"http://{self.host}:{self.port}"
        self.client = client or httpx.Client()
        self._process_factory = process_factory or self._start_worker_process
        self._process: Any | None = None
        self._start_lock = Lock()

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        self._ensure_worker()
        try:
            response = self.client.post(
                f"{self.base_url}/embed",
                json={"texts": texts},
                timeout=self.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as error:
            raise EmbeddingProviderError("BGE worker failed to return embeddings.") from error

        embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbeddingProviderError("BGE worker returned an invalid embedding payload.")

        normalized: list[list[float]] = []
        for index, embedding in enumerate(embeddings):
            if not isinstance(embedding, list) or len(embedding) != self._dimension:
                raise EmbeddingProviderError(
                    f"BGE worker embedding {index} has an unexpected dimension."
                )
            try:
                normalized.append([float(value) for value in embedding])
            except (TypeError, ValueError) as error:
                raise EmbeddingProviderError("BGE worker returned non-numeric embeddings.") from error
        return normalized

    def _ensure_worker(self) -> None:
        if self._worker_is_healthy():
            return

        with self._start_lock:
            if self._worker_is_healthy():
                return
            if self._process is None or self._process.poll() is not None:
                self._process = self._process_factory()

            deadline = time.monotonic() + self.startup_timeout_seconds
            while time.monotonic() < deadline:
                if self._worker_is_healthy():
                    return
                if self._process.poll() is not None:
                    break
                time.sleep(0.1)

        raise EmbeddingProviderError("BGE worker did not become ready before the startup timeout.")

    def _worker_is_healthy(self) -> bool:
        try:
            response = self.client.get(f"{self.base_url}/health", timeout=1)
            return response.status_code == 200
        except Exception:
            return False

    def _start_worker_process(self) -> subprocess.Popen[Any]:
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONPATH": str(BACKEND_ROOT),
                "EMBEDDING_MODEL_NAME": self.model_name,
                "BGE_EMBEDDING_DIMENSION": str(self._dimension),
                "BGE_WORKER_HOST": self.host,
                "BGE_WORKER_PORT": str(self.port),
                "BGE_KEEP_WARM": str(self.keep_warm).lower(),
                "BGE_IDLE_TIMEOUT_SECONDS": str(self.idle_timeout_seconds),
            }
        )
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        return subprocess.Popen(
            [sys.executable, "-m", "app.services.embedding.bge_worker"],
            cwd=Path(BACKEND_ROOT),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
