from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.integrations.models import ModelGateway  # noqa: E402
from app.integrations.models.base import BaseModelGateway  # noqa: E402
from app.repositories.function_registry_repository import FunctionRegistryRepository  # noqa: E402
from app.repositories.vector_repository import VectorRepository  # noqa: E402


MAX_TEXT_LENGTH = 4096


def load_active_functions() -> list[Any]:
    with SessionLocal() as db:
        repository = FunctionRegistryRepository(db)
        return repository.list_functions(status="active", limit=10_000)


def build_semantic_text(function: Any) -> str:
    examples = [
        str(example).strip()
        for example in (getattr(function, "example_sentences", None) or [])
        if str(example).strip()
    ]

    parts = [
        f"功能名称：{getattr(function, 'function_name', '')}",
        f"功能描述：{getattr(function, 'description', '')}",
    ]
    if examples:
        parts.append(f"示例语句：{'；'.join(examples)}")

    return "\n".join(part for part in parts if part.strip())[:MAX_TEXT_LENGTH]


def build_vector_record(*, function: Any, text: str, embedding: list[float]) -> dict:
    return {
        "function_code": function.function_code,
        "text": text,
        "embedding": embedding,
        "metadata": {
            "function_code": function.function_code,
            "function_name": function.function_name,
            "intent_category": function.intent_category,
            "target_engine": function.target_engine,
            "description": function.description,
            "example_sentences": function.example_sentences or [],
            "embedding_model": settings.embedding_model,
            "embedding_dimension": settings.embedding_dimension,
            "status": function.status,
        },
    }


def upsert_function_vector(
    *,
    function: Any,
    model_gateway: BaseModelGateway,
    vector_repository: VectorRepository,
) -> dict:
    text = build_semantic_text(function)
    embeddings = model_gateway.embedding([text])
    if not embeddings or not embeddings[0]:
        raise ValueError(f"Embedding is empty for function_code={function.function_code}")

    record = build_vector_record(
        function=function,
        text=text,
        embedding=embeddings[0],
    )

    vector_repository.delete(build_function_code_filter(function.function_code))
    vector_repository.insert([record])
    return record


def build_function_code_filter(function_code: str) -> str:
    escaped = function_code.replace("\\", "\\\\").replace('"', '\\"')
    return f'function_code == "{escaped}"'


def initialize_semantic_vectors(
    *,
    functions: list[Any] | None = None,
    model_gateway: BaseModelGateway | None = None,
    vector_repository: VectorRepository | None = None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    model_gateway = model_gateway or ModelGateway()
    vector_repository = vector_repository or VectorRepository()
    resolved_functions = functions if functions is not None else load_active_functions()

    success_count = 0
    failure_count = 0
    failures: list[dict[str, str]] = []

    for function in resolved_functions:
        function_code = getattr(function, "function_code", "")
        try:
            upsert_function_vector(
                function=function,
                model_gateway=model_gateway,
                vector_repository=vector_repository,
            )
            success_count += 1
        except Exception as error:
            failure_count += 1
            failures.append(
                {
                    "function_code": function_code,
                    "error": str(error),
                },
            )

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    return {
        "collection": settings.milvus_collection,
        "processed_count": len(resolved_functions),
        "success_count": success_count,
        "failure_count": failure_count,
        "elapsed_ms": elapsed_ms,
        "failures": failures,
    }


def main() -> None:
    result = initialize_semantic_vectors()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
