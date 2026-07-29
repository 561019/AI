from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol


class VectorStore(Protocol):
    collection_name: str

    def ensure_collection(self, dimensions: int) -> None: ...
    def upsert(
        self,
        chunks: list[dict[str, Any]],
        vectors: list[list[float]],
        embedding_model: str = "Qwen/Qwen3-Embedding-8B",
    ) -> int: ...


class MilvusVectorStore:
    def __init__(
        self,
        uri: str,
        collection_name: str = "document_chunks",
        token: str | None = None,
        database: str = "default",
    ):
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:
            raise RuntimeError("Milvus support requires pymilvus") from exc
        kwargs: dict[str, Any] = {"uri": uri, "db_name": database}
        if token:
            kwargs["token"] = token
        self.client = MilvusClient(**kwargs)
        self.collection_name = collection_name
        self.dimensions: int | None = None

    def close(self) -> None:
        self.client.close()

    def ensure_collection(self, dimensions: int) -> None:
        from pymilvus import DataType, MilvusClient

        if self.client.has_collection(collection_name=self.collection_name):
            description = self.client.describe_collection(collection_name=self.collection_name)
            existing = self._vector_dimension(description)
            if existing is not None and existing != dimensions:
                raise ValueError(
                    f"Milvus collection {self.collection_name!r} has dimension {existing}, expected {dimensions}"
                )
            self.dimensions = dimensions
            self.client.load_collection(collection_name=self.collection_name)
            return

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=256)
        schema.add_field(field_name="package_version", datatype=DataType.INT64)
        schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
        schema.add_field(field_name="chunk_type", datatype=DataType.VARCHAR, max_length=32)
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=dimensions)
        schema.add_field(field_name="needs_review", datatype=DataType.BOOL)
        schema.add_field(field_name="source_sha256", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="strategy_version", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="embedding_model", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=40)
        schema.add_field(field_name="metadata", datatype=DataType.JSON)

        indexes = self.client.prepare_index_params()
        indexes.add_index(field_name="embedding", index_type="AUTOINDEX", metric_type="COSINE")
        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=indexes,
            consistency_level="Session",
        )
        self.client.load_collection(collection_name=self.collection_name)
        self.dimensions = dimensions

    def upsert(
        self,
        chunks: list[dict[str, Any]],
        vectors: list[list[float]],
        embedding_model: str = "Qwen/Qwen3-Embedding-8B",
    ) -> int:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if self.dimensions is None:
            raise RuntimeError("ensure_collection must be called before upsert")
        now = datetime.now(UTC).isoformat()
        records = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            if len(vector) != self.dimensions:
                raise ValueError(f"vector dimension mismatch for chunk {chunk.get('chunk_id')}")
            records.append({
                "chunk_id": str(chunk["chunk_id"]),
                "document_id": str(chunk["document_id"])[:256],
                "package_version": int(chunk["package_version"]),
                "chunk_index": int(chunk["chunk_index"]),
                "chunk_type": str(chunk["chunk_type"])[:32],
                "text": str(chunk["text"])[:65535],
                "embedding": vector,
                "needs_review": bool(chunk.get("needs_review", False)),
                "source_sha256": str(chunk.get("source_sha256", ""))[:64],
                "strategy_version": str(chunk.get("strategy_version", ""))[:64],
                "embedding_model": embedding_model[:128],
                "created_at": now,
                "metadata": {
                    "token_count": chunk.get("token_count"),
                    "source_block_ids": chunk.get("source_block_ids", []),
                    "heading_path": chunk.get("heading_path", []),
                    "page_start": chunk.get("page_start"),
                    "page_end": chunk.get("page_end"),
                    "source_refs": chunk.get("source_refs", []),
                    "asset_refs": chunk.get("asset_refs", []),
                    "business_tags": chunk.get("business_tags", []),
                    "confidence": chunk.get("confidence"),
                    "table_row_start": chunk.get("table_row_start"),
                    "table_row_end": chunk.get("table_row_end"),
                },
            })
        if not records:
            return 0
        result = self.client.upsert(collection_name=self.collection_name, data=records)
        return int(result.get("upsert_count", result.get("insert_count", len(records)))) if isinstance(result, dict) else len(records)

    def search(self, vector: list[float], limit: int = 10, document_id: str | None = None) -> list[dict[str, Any]]:
        filter_expression = ""
        if document_id:
            escaped = document_id.replace("\\", "\\\\").replace('"', '\\"')
            filter_expression = f'document_id == "{escaped}"'
        result = self.client.search(
            collection_name=self.collection_name,
            data=[vector],
            anns_field="embedding",
            limit=limit,
            filter=filter_expression,
            output_fields=[
                "chunk_id", "document_id", "package_version", "chunk_index", "chunk_type",
                "text", "needs_review", "source_sha256", "strategy_version", "metadata",
            ],
            search_params={"metric_type": "COSINE", "params": {}},
        )
        return list(result[0]) if result else []

    @staticmethod
    def _vector_dimension(description: dict[str, Any]) -> int | None:
        for field in description.get("fields", []):
            if (field.get("name") or field.get("field_name")) != "embedding":
                continue
            params = field.get("params") or field.get("type_params") or field.get("element_type_params") or {}
            value = params.get("dim") or params.get("dimension")
            return int(value) if value is not None else None
        return None
