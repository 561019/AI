from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.schemas.semantic import SemanticCandidate, SemanticResult
from app.services.intent_analysis_engine.registry import FunctionRegistryCatalog, FunctionRegistryEntry
from app.services.embedding.embedding_service import EmbeddingService
from app.services.semantic.capability_config import SemanticCapability, SemanticCapabilityCatalog


class IntentCapabilityVectorRepository:
    """Milvus repository for intent capability vectors."""

    def __init__(
        self,
        *,
        collection: Any | None = None,
        collection_name: str | None = None,
        vector_field: str = "embedding_vector",
    ) -> None:
        self.collection = collection
        self.collection_name = collection_name or settings.intent_capability_collection_name
        self.vector_field = vector_field

    def ensure_collection(self, *, dimension: int | None = None, recreate: bool = False) -> dict[str, Any]:
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

        vector_dimension = dimension or settings.bge_embedding_dimension
        connections.connect(
            alias="default",
            host=settings.milvus_host,
            port=str(settings.milvus_port),
        )

        if recreate and utility.has_collection(self.collection_name):
            utility.drop_collection(self.collection_name)
            self.collection = None

        created = False
        if not utility.has_collection(self.collection_name):
            schema = CollectionSchema(
                fields=[
                    FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                    FieldSchema(name="engine_code", dtype=DataType.VARCHAR, max_length=128),
                    FieldSchema(name="task_type", dtype=DataType.VARCHAR, max_length=128),
                    FieldSchema(name="intent_description", dtype=DataType.VARCHAR, max_length=4096),
                    FieldSchema(name="examples", dtype=DataType.JSON),
                    FieldSchema(name="keywords", dtype=DataType.JSON),
                    FieldSchema(name=self.vector_field, dtype=DataType.FLOAT_VECTOR, dim=vector_dimension),
                ],
                description="BGE intent capability semantic matching vectors.",
                enable_dynamic_field=False,
            )
            self.collection = Collection(name=self.collection_name, schema=schema, using="default")
            created = True
        else:
            self.collection = Collection(self.collection_name, using="default")

        index_created = self._ensure_vector_index(self.collection)
        self.collection.load()
        return {
            "collection": self.collection_name,
            "created": created,
            "embedding_dimension": vector_dimension,
            "index_created": index_created,
            "loaded": True,
        }

    def insert(self, records: list[dict[str, Any]]) -> Any:
        if not records:
            return None
        collection = self._get_collection()
        result = collection.insert(records)
        collection.flush()
        return result

    def search(self, vector: list[float], *, top_k: int = 5) -> list[dict[str, Any]]:
        if not vector:
            return []

        collection = self._get_collection()
        search_results = collection.search(
            data=[vector],
            anns_field=self.vector_field,
            param={"metric_type": "COSINE", "params": {}},
            limit=top_k,
            output_fields=[
                "engine_code",
                "task_type",
                "intent_description",
                "examples",
                "keywords",
            ],
        )
        return self._serialize_search_results(search_results)

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

    def _ensure_vector_index(self, collection: Any) -> bool:
        for index in getattr(collection, "indexes", []) or []:
            index_dict = index.to_dict() if hasattr(index, "to_dict") else {}
            if getattr(index, "field_name", None) == self.vector_field or index_dict.get("field_name") == self.vector_field:
                return False

        collection.create_index(
            field_name=self.vector_field,
            index_params={
                "metric_type": "COSINE",
                "index_type": "AUTOINDEX",
                "params": {},
            },
        )
        return True

    def _serialize_search_results(self, search_results: Any) -> list[dict[str, Any]]:
        if not search_results:
            return []

        serialized: list[dict[str, Any]] = []
        for hit in search_results[0]:
            entity = getattr(hit, "entity", None)
            serialized.append(
                {
                    "engine_code": self._read_entity_field(entity, "engine_code"),
                    "task_type": self._read_entity_field(entity, "task_type"),
                    "intent_description": self._read_entity_field(entity, "intent_description"),
                    "examples": self._read_entity_field(entity, "examples") or [],
                    "keywords": self._read_entity_field(entity, "keywords") or [],
                    "similarity_score": self._extract_score(hit),
                },
            )
        return serialized

    def _read_entity_field(self, entity: Any, field_name: str) -> Any:
        if entity is None:
            return None
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
        return self._normalize_score(raw_score)

    def _normalize_score(self, value: float | int | str | None) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0
        return max(0, min(score, 1))


class SemanticMatcher:
    """Level 2 BGE semantic matcher for intent capabilities."""

    def __init__(
        self,
        *,
        embedding_service: EmbeddingService | None = None,
        vector_repository: IntentCapabilityVectorRepository | None = None,
        registry: FunctionRegistryCatalog | None = None,
        capability_catalog: SemanticCapabilityCatalog | None = None,
        top_k: int = 5,
        match_threshold: float = 0.50,
    ) -> None:
        self.embedding_service = embedding_service or EmbeddingService()
        self.vector_repository = vector_repository or IntentCapabilityVectorRepository()
        self.registry = registry or FunctionRegistryCatalog()
        self.capability_catalog = capability_catalog or SemanticCapabilityCatalog.from_default_file()
        self.top_k = top_k
        self.match_threshold = match_threshold

    def analyze(self, text: str | dict[str, Any]) -> SemanticResult:
        text = self._user_input(text)
        if not text or not text.strip():
            return SemanticResult.unmatched()

        embedding = self.embedding_service.embed_query(text)
        raw_candidates = self.vector_repository.search(embedding, top_k=self.top_k)
        candidates = self.rank_candidates(raw_candidates, query_text=text)

        if not candidates:
            return SemanticResult.unmatched()

        if candidates[0].confidence < self.match_threshold:
            return SemanticResult.unmatched(candidates=candidates)

        return SemanticResult.matched_result(candidates=candidates)

    def _user_input(self, text: str | dict[str, Any]) -> str:
        if isinstance(text, dict):
            return str(text.get("user_input") or "")
        return text

    def rank_candidates(self, raw_candidates: list[dict[str, Any]], *, query_text: str = "") -> list[SemanticCandidate]:
        best_by_task: dict[tuple[str, str], SemanticCandidate] = {}

        for raw_candidate in raw_candidates:
            engine_code = str(raw_candidate.get("engine_code") or "")
            task_type = str(raw_candidate.get("task_type") or "")
            if not engine_code or not task_type:
                continue

            try:
                registry_entry = self.registry.get_by_task_type(task_type)
            except KeyError:
                continue

            if registry_entry.engine_code != engine_code:
                continue

            capability = self.capability_catalog.get_by_task_type(task_type)
            similarity_score = self._normalize_score(raw_candidate.get("similarity_score", 0))
            confidence = self._confidence_with_example_boost(
                query_text=query_text,
                similarity_score=similarity_score,
                raw_candidate=raw_candidate,
            )
            examples = raw_candidate.get("examples")
            candidate = SemanticCandidate(
                function_code=engine_code,
                function_name=registry_entry.engine_name,
                intent_category=self._intent_category_for(registry_entry),
                target_engine=registry_entry.engine_name,
                engine_code=engine_code,
                task_type=task_type,
                task_name=capability.task_name if capability is not None else task_type,
                intent_description=raw_candidate.get("intent_description"),
                examples=examples if isinstance(examples, list) else [],
                confidence=confidence,
                similarity_score=similarity_score,
            )

            key = (engine_code, task_type)
            existing = best_by_task.get(key)
            if existing is None or candidate.confidence > existing.confidence:
                best_by_task[key] = candidate

        return sorted(
            best_by_task.values(),
            key=lambda candidate: (candidate.confidence, candidate.similarity_score),
            reverse=True,
        )[: self.top_k]

    def _intent_category_for(self, registry_entry: FunctionRegistryEntry) -> str:
        return registry_entry.supported_intents[0] if registry_entry.supported_intents else "智能问答型"

    def _confidence_with_example_boost(
        self,
        *,
        query_text: str,
        similarity_score: float,
        raw_candidate: dict[str, Any],
    ) -> float:
        normalized_query = self._normalize_text(query_text)
        if not normalized_query:
            return similarity_score

        examples = raw_candidate.get("examples")
        candidate_texts = list(examples) if isinstance(examples, list) else []
        keywords = raw_candidate.get("keywords")
        if isinstance(keywords, list):
            candidate_texts.extend(str(keyword) for keyword in keywords)
        description = raw_candidate.get("intent_description")
        if description:
            candidate_texts.append(str(description))

        boost = 0.0
        for candidate_text in candidate_texts:
            normalized_candidate = self._normalize_text(str(candidate_text))
            if not normalized_candidate:
                continue
            if normalized_candidate == normalized_query:
                boost = max(boost, 0.3)
            elif len(normalized_query) >= 4 and normalized_query in normalized_candidate:
                boost = max(boost, 0.2)
            elif len(normalized_candidate) >= 4 and normalized_candidate in normalized_query:
                boost = max(boost, 0.15)

        return self._normalize_score(similarity_score + boost)

    def _normalize_text(self, text: str) -> str:
        return "".join(str(text).lower().split())

    def _normalize_score(self, value: float | int | str | None) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0
        return max(0, min(score, 1))


def build_intent_capability_records(
    *,
    registry: FunctionRegistryCatalog,
    embedding_service: EmbeddingService,
    capability_catalog: SemanticCapabilityCatalog | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    catalog = capability_catalog or SemanticCapabilityCatalog.from_default_file()
    configured_task_types = set()

    for capability in catalog.list_capabilities():
        if not _is_registered_capability(registry, capability):
            continue
        records.append(_build_record(capability=capability, embedding_service=embedding_service))
        configured_task_types.add(capability.task_type)

    for entry in registry.entries:
        for task_type in entry.supported_tasks:
            if task_type == "GENERAL_TASK":
                continue
            if task_type in configured_task_types:
                continue
            capability = _fallback_capability(entry, task_type)
            records.append(_build_record(capability=capability, embedding_service=embedding_service))
    return records


def _is_registered_capability(registry: FunctionRegistryCatalog, capability: SemanticCapability) -> bool:
    try:
        entry = registry.get_by_task_type(capability.task_type)
    except KeyError:
        return False
    return entry.engine_code == capability.engine_code


def _build_record(*, capability: SemanticCapability, embedding_service: EmbeddingService) -> dict[str, Any]:
    semantic_text = _semantic_text_for_capability(capability)
    return {
        "engine_code": capability.engine_code,
        "task_type": capability.task_type,
        "intent_description": capability.description,
        "examples": capability.examples,
        "keywords": capability.keywords,
        "embedding_vector": embedding_service.embed_query(semantic_text),
    }


def _fallback_capability(entry: FunctionRegistryEntry, task_type: str) -> SemanticCapability:
    return SemanticCapability(
        engine_code=entry.engine_code,
        task_type=task_type,
        task_name=task_type,
        description=entry.description,
        examples=[task_type, entry.description],
        keywords=[],
        required_inputs=list(entry.required_inputs),
    )


def _semantic_text_for_capability(capability: SemanticCapability) -> str:
    examples = "\n".join(str(example) for example in capability.examples)
    keywords = "\n".join(str(keyword) for keyword in capability.keywords)
    return "\n".join(
        [
            f"engine_code: {capability.engine_code}",
            f"task_type: {capability.task_type}",
            f"task_name: {capability.task_name}",
            f"description: {capability.description}",
            f"examples:\n{examples}",
            f"keywords:\n{keywords}",
        ],
    )
