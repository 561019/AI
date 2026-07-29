from app.db.session import SessionLocal
from app.core.config import settings
from app.integrations.models import ModelGateway
from app.integrations.models.base import BaseModelGateway
from app.repositories.function_registry_repository import FunctionRegistryRepository
from app.repositories.vector_repository import VectorRepository


def build_vector_records(
    *,
    model_gateway: BaseModelGateway,
    functions: list,
) -> list[dict]:
    records: list[dict] = []

    for function in functions:
        source_texts = [
            ("function_name", function.function_name),
            ("description", function.description),
        ]
        source_texts.extend(
            ("example_sentence", example)
            for example in (function.example_sentences or [])
        )

        for source_type, source_text in source_texts:
            if not source_text:
                continue

            records.append(
                {
                    "function_code": function.function_code,
                    "text": source_text,
                    "embedding": model_gateway.embedding([source_text])[0],
                    "metadata": {
                        "function_code": function.function_code,
                        "function_name": function.function_name,
                        "intent_category": function.intent_category,
                        "target_engine": function.target_engine,
                        "source_type": source_type,
                        "source_text": source_text,
                        "status": function.status,
                        "embedding_model": settings.embedding_model,
                    },
                },
            )

    return records


def initialize_semantic_vectors(
    *,
    model_gateway: BaseModelGateway | None = None,
    vector_repository: VectorRepository | None = None,
) -> int:
    model_gateway = model_gateway or ModelGateway()
    vector_repository = vector_repository or VectorRepository()

    with SessionLocal() as db:
        function_repository = FunctionRegistryRepository(db)
        functions = function_repository.list_functions(status="active", limit=10_000)
        records = build_vector_records(
            model_gateway=model_gateway,
            functions=functions,
        )

    if records:
        vector_repository.insert(records)

    return len(records)


if __name__ == "__main__":
    count = initialize_semantic_vectors()
    print(f"Inserted {count} semantic vectors.")
