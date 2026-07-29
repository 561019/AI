from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.services.embedding import BGEProvider, EmbeddingService, ManagedBGEProvider
from app.services.intent_analysis_engine import FunctionRegistryCatalog
from app.services.semantic.local_vector_repository import LocalIntentCapabilityVectorRepository
from app.services.semantic.semantic_matcher import (
    IntentCapabilityVectorRepository,
    build_intent_capability_records,
)


@lru_cache(maxsize=1)
def get_runtime_embedding_service() -> EmbeddingService:
    if settings.embedding_runtime == "worker":
        provider = ManagedBGEProvider()
    else:
        provider = BGEProvider()
    return EmbeddingService(provider=provider)


@lru_cache(maxsize=1)
def get_runtime_vector_repository() -> Any:
    if settings.vector_backend == "local":
        repository = LocalIntentCapabilityVectorRepository()
        repository.ensure_collection(dimension=settings.bge_embedding_dimension)
        return repository
    return IntentCapabilityVectorRepository()


def configure_runtime_vector_repository(
    *,
    registry: FunctionRegistryCatalog,
    embedding_service: EmbeddingService,
) -> Any:
    repository = get_runtime_vector_repository()
    if isinstance(repository, LocalIntentCapabilityVectorRepository):
        repository.configure_initializer(
            lambda: build_intent_capability_records(
                registry=registry,
                embedding_service=embedding_service,
            )
        )
    return repository


def reset_runtime_services() -> None:
    get_runtime_embedding_service.cache_clear()
    get_runtime_vector_repository.cache_clear()
