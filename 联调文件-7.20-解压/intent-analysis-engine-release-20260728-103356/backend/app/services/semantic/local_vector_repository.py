from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any

import numpy as np

from app.core.config import settings


class LocalVectorRepositoryError(RuntimeError):
    """Raised when the local capability vector store is invalid."""


class LocalIntentCapabilityVectorRepository:
    """Small persistent float32 vector store for native development."""

    def __init__(self, *, path: Path | str | None = None) -> None:
        self.path = Path(path or settings.local_vector_store_path)
        self._embeddings: np.ndarray | None = None
        self._metadata: list[dict[str, Any]] = []
        self._initializer: Callable[[], list[dict[str, Any]]] | None = None
        self._lock = RLock()

    @property
    def count(self) -> int:
        with self._lock:
            self._load_if_needed()
            return len(self._metadata)

    def configure_initializer(self, initializer: Callable[[], list[dict[str, Any]]]) -> None:
        with self._lock:
            self._initializer = initializer

    def ensure_collection(self, *, dimension: int | None = None, recreate: bool = False) -> dict[str, Any]:
        with self._lock:
            if recreate and self.path.exists():
                self.path.unlink()
            if recreate:
                self._embeddings = None
                self._metadata = []
            self._load_if_needed()
            actual_dimension = (
                int(self._embeddings.shape[1])
                if self._embeddings is not None and self._embeddings.ndim == 2 and self._embeddings.size
                else dimension or settings.bge_embedding_dimension
            )
            return {
                "collection": str(self.path),
                "created": not self.path.exists(),
                "embedding_dimension": actual_dimension,
                "index_created": False,
                "loaded": self.path.exists(),
                "record_count": len(self._metadata),
            }

    def insert(self, records: list[dict[str, Any]]) -> dict[str, int]:
        with self._lock:
            self._write_records(records)
            return {"insert_count": len(records)}

    def search(self, vector: list[float], *, top_k: int = 5) -> list[dict[str, Any]]:
        if not vector:
            return []
        self._initialize_if_needed()
        with self._lock:
            self._load_if_needed()
            if self._embeddings is None or not len(self._metadata):
                return []

            query = np.asarray(vector, dtype=np.float32)
            if query.ndim != 1 or query.shape[0] != self._embeddings.shape[1]:
                raise LocalVectorRepositoryError("Query vector dimension does not match the local vector store.")
            query_norm = float(np.linalg.norm(query))
            row_norms = np.linalg.norm(self._embeddings, axis=1)
            denominator = row_norms * query_norm
            scores = np.divide(
                self._embeddings @ query,
                denominator,
                out=np.zeros_like(row_norms, dtype=np.float32),
                where=denominator != 0,
            )
            indexes = np.argsort(scores)[::-1][: max(0, top_k)]
            return [
                {**self._metadata[int(index)], "similarity_score": float(scores[int(index)])}
                for index in indexes
            ]

    def _initialize_if_needed(self) -> None:
        with self._lock:
            self._load_if_needed()
            if self._metadata or self._initializer is None:
                return
            records = self._initializer()
            self._write_records(records)

    def _load_if_needed(self) -> None:
        if self._embeddings is not None:
            return
        if not self.path.exists():
            self._embeddings = np.empty((0, settings.bge_embedding_dimension), dtype=np.float32)
            self._metadata = []
            return
        try:
            with np.load(self.path, allow_pickle=False) as payload:
                self._embeddings = np.asarray(payload["embeddings"], dtype=np.float32)
                metadata_bytes = np.asarray(payload["metadata"], dtype=np.uint8).tobytes()
            metadata = json.loads(metadata_bytes.decode("utf-8"))
        except Exception as error:
            raise LocalVectorRepositoryError(f"Failed to load local vector store: {self.path}") from error
        if not isinstance(metadata, list) or self._embeddings.ndim != 2:
            raise LocalVectorRepositoryError("Local vector store payload is invalid.")
        if len(metadata) != self._embeddings.shape[0]:
            raise LocalVectorRepositoryError("Local vector metadata count does not match embeddings.")
        self._metadata = metadata

    def _write_records(self, records: list[dict[str, Any]]) -> None:
        if not records:
            self._embeddings = np.empty((0, settings.bge_embedding_dimension), dtype=np.float32)
            self._metadata = []
            return
        try:
            embeddings = np.asarray([record["embedding_vector"] for record in records], dtype=np.float32)
        except (KeyError, TypeError, ValueError) as error:
            raise LocalVectorRepositoryError("Local vector records contain invalid embeddings.") from error
        if embeddings.ndim != 2:
            raise LocalVectorRepositoryError("Local vector records must contain equal-length vectors.")

        metadata = [
            {key: value for key, value in record.items() if key != "embedding_vector"}
            for record in records
        ]
        metadata_bytes = json.dumps(metadata, ensure_ascii=False).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with temporary_path.open("wb") as output:
            np.savez_compressed(
                output,
                embeddings=embeddings,
                metadata=np.frombuffer(metadata_bytes, dtype=np.uint8),
            )
        os.replace(temporary_path, self.path)
        self._embeddings = embeddings
        self._metadata = metadata
