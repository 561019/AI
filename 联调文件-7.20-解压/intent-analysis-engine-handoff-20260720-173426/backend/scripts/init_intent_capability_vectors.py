from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.intent_analysis_engine import FunctionRegistryCatalog  # noqa: E402
from app.services.semantic import (  # noqa: E402
    EmbeddingService,
    IntentCapabilityVectorRepository,
    build_intent_capability_records,
)


def initialize_intent_capability_vectors(
    *,
    registry: FunctionRegistryCatalog | None = None,
    embedding_service: EmbeddingService | None = None,
    vector_repository: IntentCapabilityVectorRepository | None = None,
) -> dict[str, Any]:
    registry = registry or FunctionRegistryCatalog()
    embedding_service = embedding_service or EmbeddingService()
    vector_repository = vector_repository or IntentCapabilityVectorRepository()
    embedding_dimension = getattr(embedding_service, "dimension", None) or settings.bge_embedding_dimension

    collection_result = vector_repository.ensure_collection(
        dimension=embedding_dimension,
        recreate=True,
    )
    records = build_intent_capability_records(
        registry=registry,
        embedding_service=embedding_service,
    )
    vector_repository.insert(records)

    return {
        **collection_result,
        "inserted": len(records),
        "embedding_model_name": getattr(embedding_service, "model_name", settings.embedding_model_name),
        "embedding_dimension": embedding_dimension,
    }


def main() -> None:
    result = initialize_intent_capability_vectors()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
