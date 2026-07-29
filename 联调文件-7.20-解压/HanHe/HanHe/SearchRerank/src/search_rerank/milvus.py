from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    package_version: int
    chunk_index: int
    chunk_type: str
    text: str
    vector_score: float
    needs_review: bool
    source_sha256: str
    metadata: dict[str, Any]


class Retriever(Protocol):
    collection_name: str

    def ensure_collection(self, dimensions: int) -> None: ...

    def search(
        self,
        vector: list[float],
        candidate_k: int,
        document_ids: list[str],
        business_tags: list[str],
        include_review_required: bool,
        max_candidate_k: int,
    ) -> list[RetrievedChunk]: ...

    def close(self) -> None: ...


class MilvusRetriever:
    OUTPUT_FIELDS = [
        "chunk_id", "document_id", "package_version", "chunk_index", "chunk_type",
        "text", "needs_review", "source_sha256", "metadata",
    ]

    def __init__(self, uri: str, collection_name: str, token: str | None, database: str):
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:
            raise RuntimeError("Milvus retrieval requires pymilvus") from exc
        kwargs: dict[str, Any] = {"uri": uri, "db_name": database}
        if token:
            kwargs["token"] = token
        self.client = MilvusClient(**kwargs)
        self.collection_name = collection_name

    def close(self) -> None:
        self.client.close()

    def ensure_collection(self, dimensions: int) -> None:
        if not self.client.has_collection(collection_name=self.collection_name):
            raise ValueError(f"Milvus collection {self.collection_name!r} does not exist; run vectorization first")
        description = self.client.describe_collection(collection_name=self.collection_name)
        existing = self._vector_dimension(description)
        if existing is not None and existing != dimensions:
            raise ValueError(
                f"Milvus collection {self.collection_name!r} has dimension {existing}, expected {dimensions}"
            )
        self.client.load_collection(collection_name=self.collection_name)

    def search(
        self,
        vector: list[float],
        candidate_k: int,
        document_ids: list[str],
        business_tags: list[str],
        include_review_required: bool,
        max_candidate_k: int,
    ) -> list[RetrievedChunk]:
        # Business tags live inside the JSON metadata. Oversampling preserves recall
        # before the mandatory authorization filter is applied in Python.
        recall_limit = min(max(candidate_k * 3, candidate_k), max_candidate_k)
        result = self.client.search(
            collection_name=self.collection_name,
            data=[vector],
            anns_field="embedding",
            limit=recall_limit,
            filter=self._filter(document_ids, include_review_required),
            output_fields=self.OUTPUT_FIELDS,
            search_params={"metric_type": "COSINE", "params": {}},
        )
        hits = list(result[0]) if result else []
        authorized: list[RetrievedChunk] = []
        required_tags = set(business_tags)
        for hit in hits:
            values = self._hit_values(hit)
            metadata = self._metadata(values.get("metadata"))
            stored_tags = {str(value) for value in metadata.get("business_tags", [])}
            if not required_tags.issubset(stored_tags):
                continue
            authorized.append(RetrievedChunk(
                chunk_id=str(values.get("chunk_id", "")),
                document_id=str(values.get("document_id", "")),
                package_version=int(values.get("package_version", 1)),
                chunk_index=int(values.get("chunk_index", 0)),
                chunk_type=str(values.get("chunk_type", "text")),
                text=str(values.get("text", "")),
                vector_score=float(values.get("distance", values.get("score", 0.0))),
                needs_review=bool(values.get("needs_review", False)),
                source_sha256=str(values.get("source_sha256", "")),
                metadata=metadata,
            ))
            if len(authorized) >= candidate_k:
                break
        return authorized

    @staticmethod
    def _filter(document_ids: list[str], include_review_required: bool) -> str:
        clauses: list[str] = []
        if document_ids:
            quoted = ", ".join(json.dumps(value, ensure_ascii=False) for value in document_ids)
            clauses.append(f"document_id in [{quoted}]")
        if not include_review_required:
            clauses.append("needs_review == false")
        return " and ".join(clauses)

    @staticmethod
    def _hit_values(hit: Any) -> dict[str, Any]:
        raw = dict(hit) if not isinstance(hit, dict) else dict(hit)
        entity = raw.get("entity")
        if isinstance(entity, dict):
            values = dict(entity)
            values.setdefault("chunk_id", raw.get("id"))
            values["distance"] = raw.get("distance", raw.get("score", 0.0))
            return values
        return raw

    @staticmethod
    def _metadata(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _vector_dimension(description: dict[str, Any]) -> int | None:
        for field in description.get("fields", []):
            if (field.get("name") or field.get("field_name")) != "embedding":
                continue
            params = field.get("params") or field.get("type_params") or field.get("element_type_params") or {}
            value = params.get("dim") or params.get("dimension")
            return int(value) if value is not None else None
        return None
