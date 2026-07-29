from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402


def build_collection_schema(*, dimension: int):
    from pymilvus import CollectionSchema, DataType, FieldSchema

    return CollectionSchema(
        fields=[
            FieldSchema(
                name="id",
                dtype=DataType.INT64,
                is_primary=True,
                auto_id=True,
            ),
            FieldSchema(
                name="function_code",
                dtype=DataType.VARCHAR,
                max_length=128,
            ),
            FieldSchema(
                name="text",
                dtype=DataType.VARCHAR,
                max_length=4096,
            ),
            FieldSchema(
                name="embedding",
                dtype=DataType.FLOAT_VECTOR,
                dim=dimension,
            ),
            FieldSchema(
                name="metadata",
                dtype=DataType.JSON,
            ),
        ],
        description="Intent semantic matching vectors.",
        enable_dynamic_field=False,
    )


def initialize_milvus_collection() -> dict[str, Any]:
    from pymilvus import Collection, connections, utility

    collection_name = settings.milvus_collection
    dimension = settings.embedding_dimension

    connections.connect(
        alias="default",
        host=settings.milvus_host,
        port=str(settings.milvus_port),
    )

    created = False
    if not utility.has_collection(collection_name):
        schema = build_collection_schema(dimension=dimension)
        collection = Collection(
            name=collection_name,
            schema=schema,
            using="default",
        )
        created = True
    else:
        collection = Collection(collection_name, using="default")

    index_created = ensure_embedding_index(collection)
    collection.load()

    return {
        "collection": collection_name,
        "created": created,
        "host": settings.milvus_host,
        "port": settings.milvus_port,
        "embedding_dimension": dimension,
        "index_created": index_created,
        "loaded": True,
        "schema": serialize_schema(collection.schema),
        "indexes": serialize_indexes(collection.indexes),
    }


def ensure_embedding_index(collection: Any) -> bool:
    if has_field_index(collection, "embedding"):
        return False

    collection.create_index(
        field_name="embedding",
        index_params={
            "metric_type": "COSINE",
            "index_type": "AUTOINDEX",
            "params": {},
        },
    )
    return True


def has_field_index(collection: Any, field_name: str) -> bool:
    for index in getattr(collection, "indexes", []) or []:
        if getattr(index, "field_name", None) == field_name:
            return True
        index_dict = index.to_dict() if hasattr(index, "to_dict") else {}
        if index_dict.get("field_name") == field_name:
            return True
    return False


def serialize_schema(schema: Any) -> dict[str, Any]:
    return {
        "description": getattr(schema, "description", ""),
        "enable_dynamic_field": bool(getattr(schema, "enable_dynamic_field", False)),
        "fields": [serialize_field(field) for field in getattr(schema, "fields", [])],
    }


def serialize_field(field: Any) -> dict[str, Any]:
    dtype = getattr(field, "dtype", "")
    dtype_name = getattr(dtype, "name", str(dtype))
    params = dict(getattr(field, "params", {}) or {})

    return {
        "name": getattr(field, "name", ""),
        "dtype": dtype_name,
        "is_primary": bool(getattr(field, "is_primary", False)),
        "auto_id": bool(getattr(field, "auto_id", False)),
        "params": params,
    }


def serialize_indexes(indexes: list[Any]) -> list[dict[str, Any]]:
    serialized = []
    for index in indexes or []:
        index_dict = index.to_dict() if hasattr(index, "to_dict") else {}
        serialized.append(
            {
                "field_name": getattr(index, "field_name", index_dict.get("field_name")),
                "index_name": getattr(index, "index_name", index_dict.get("index_name")),
                "params": getattr(index, "params", index_dict.get("params", {})),
            },
        )
    return serialized


def main() -> None:
    result = initialize_milvus_collection()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
