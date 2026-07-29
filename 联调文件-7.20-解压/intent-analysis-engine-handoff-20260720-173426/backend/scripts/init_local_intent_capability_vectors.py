from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.intent_analysis_engine import FunctionRegistryCatalog  # noqa: E402
from app.services.semantic import LocalIntentCapabilityVectorRepository, build_intent_capability_records  # noqa: E402
from app.services.semantic.runtime import get_runtime_embedding_service  # noqa: E402


def main() -> None:
    embedding_service = get_runtime_embedding_service()
    repository = LocalIntentCapabilityVectorRepository(path=settings.local_vector_store_path)
    collection = repository.ensure_collection(
        dimension=embedding_service.dimension,
        recreate=True,
    )
    records = build_intent_capability_records(
        registry=FunctionRegistryCatalog(),
        embedding_service=embedding_service,
    )
    insert_result = repository.insert(records)
    print(
        json.dumps(
            {
                **collection,
                **insert_result,
                "record_count": repository.count,
                "embedding_model_name": embedding_service.model_name,
                "embedding_dimension": embedding_service.dimension,
                "file_size_bytes": repository.path.stat().st_size,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
