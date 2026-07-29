from typing import Any

from app.core.config import settings


class VectorRepository:
    """Milvus access for function example vectors."""

    def __init__(
        self,
        *,
        collection: Any | None = None,
        collection_name: str | None = None,
        anns_field: str = "embedding",
    ) -> None:
        self.collection = collection
        self.collection_name = collection_name or settings.milvus_collection_name
        self.anns_field = anns_field

    def insert(self, records: list[dict]) -> Any:
        collection = self._get_collection()
        result = collection.insert(records)
        collection.flush()
        return result

    def search(
        self,
        vector: list[float],
        *,
        top_k: int = 5,
        filter_expr: str | None = None,
    ) -> list[dict]:
        collection = self._get_collection()
        search_results = collection.search(
            data=[vector],
            anns_field=self.anns_field,
            param={"metric_type": "COSINE", "params": {}},
            limit=top_k,
            expr=filter_expr,
            output_fields=[
                "function_code",
                "text",
                "metadata",
            ],
        )
        return self._serialize_search_results(search_results)

    def delete(self, filter_expr: str) -> Any:
        collection = self._get_collection()
        result = collection.delete(filter_expr)
        collection.flush()
        return result

    def _get_collection(self) -> Any:
        if self.collection is not None:
            return self.collection

        from pymilvus import Collection, connections

        connections.connect(
            alias="default",
            host=settings.milvus_host,
            port=str(settings.milvus_port),
        )
        self.collection = Collection(self.collection_name)
        return self.collection

    def _serialize_search_results(self, search_results: Any) -> list[dict]:
        if not search_results:
            return []

        first_result_set = search_results[0]
        serialized: list[dict] = []
        for hit in first_result_set:
            entity = getattr(hit, "entity", None)
            metadata = self._extract_entity_metadata(entity)
            score = self._extract_score(hit)
            serialized.append(
                {
                    **metadata,
                    "similarity_score": score,
                },
            )
        return serialized

    def _extract_entity_metadata(self, entity: Any) -> dict:
        if entity is None:
            return {}

        metadata = self._read_entity_field(entity, "metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        function_code = self._read_entity_field(entity, "function_code")
        text = self._read_entity_field(entity, "text")

        if function_code is not None:
            metadata.setdefault("function_code", function_code)
        if text is not None:
            metadata.setdefault("text", text)
            metadata.setdefault("source_text", text)

        for field_name in ["function_name", "intent_category", "target_engine", "source_text"]:
            value = self._read_entity_field(entity, field_name)
            if value is not None:
                metadata.setdefault(field_name, value)

        return metadata

    def _read_entity_field(self, entity: Any, field_name: str) -> Any:
        if isinstance(entity, dict):
            return entity.get(field_name)

        if hasattr(entity, "get"):
            return entity.get(field_name)

        if hasattr(entity, field_name):
            return getattr(entity, field_name)

        return None

    def _extract_score(self, hit: Any) -> float:
        raw_score = getattr(hit, "score", None)
        if raw_score is None:
            raw_score = getattr(hit, "distance", 0)
        return max(0, min(float(raw_score), 1))
