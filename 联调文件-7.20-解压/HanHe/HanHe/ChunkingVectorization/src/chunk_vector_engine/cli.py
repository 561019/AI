from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .config import ChunkSettings, VectorSettings
from .embedding import SiliconFlowEmbeddingClient
from .milvus_store import MilvusVectorStore
from .pipeline import build_chunk_process, vectorize_process


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="standard-document/v1 chunking and vectorization")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="optional KEY=VALUE environment file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    chunk = subparsers.add_parser("chunk", help="build auditable chunk process files")
    chunk.add_argument("package", type=Path, help="expanded standard package directory or ZIP")
    chunk.add_argument("--output-dir", type=Path)

    index = subparsers.add_parser("index", help="embed an existing chunk process and upsert it into Milvus")
    index.add_argument("process_dir", type=Path)

    ingest = subparsers.add_parser("ingest", help="chunk, embed, and upsert a standard package")
    ingest.add_argument("package", type=Path)
    ingest.add_argument("--output-dir", type=Path)

    search = subparsers.add_parser("search", help="embed a query and search Milvus")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=10)
    search.add_argument("--document-id")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    _load_env(args.env_file)
    vector_settings = VectorSettings.from_env()
    chunk_settings = ChunkSettings.from_env()

    if args.command == "chunk":
        destination = build_chunk_process(
            args.package,
            args.output_dir or vector_settings.process_output_dir,
            chunk_settings,
        )
        _print({"status": "chunked", "process_dir": str(destination)})
        return

    if args.command == "ingest":
        process_dir = build_chunk_process(
            args.package,
            args.output_dir or vector_settings.process_output_dir,
            chunk_settings,
        )
        result = _vectorize(process_dir, vector_settings)
        _print({"status": "completed", "process_dir": str(process_dir), "vectorization": result})
        return

    if args.command == "index":
        result = _vectorize(args.process_dir.resolve(), vector_settings)
        _print({"status": "completed", "process_dir": str(args.process_dir.resolve()), "vectorization": result})
        return

    if args.top_k <= 0:
        raise SystemExit("--top-k must be positive")
    vector_settings.require_external_services()
    embedder = _embedder(vector_settings)
    store = _milvus(vector_settings)
    try:
        store.ensure_collection(vector_settings.embedding_dimensions)
        vector = embedder.embed_query(args.query)
        hits = store.search(vector, args.top_k, args.document_id)
        _print({"query": args.query, "items": [_jsonable_hit(hit) for hit in hits]})
    finally:
        embedder.close()
        store.close()


def _vectorize(process_dir: Path, settings: VectorSettings) -> dict[str, Any]:
    settings.require_external_services()
    embedder = _embedder(settings)
    store = _milvus(settings)
    try:
        return vectorize_process(
            process_dir,
            embedder,
            store,
            settings.embedding_batch_size,
            settings.milvus_batch_size,
        )
    finally:
        embedder.close()
        store.close()


def _embedder(settings: VectorSettings) -> SiliconFlowEmbeddingClient:
    return SiliconFlowEmbeddingClient(
        settings.siliconflow_api_key,
        settings.siliconflow_base_url,
        settings.embedding_model,
        settings.embedding_dimensions,
        settings.embedding_timeout_seconds,
        settings.embedding_max_retries,
        settings.query_instruction,
    )


def _milvus(settings: VectorSettings) -> MilvusVectorStore:
    return MilvusVectorStore(
        settings.milvus_uri,
        settings.milvus_collection,
        settings.milvus_token,
        settings.milvus_database,
    )


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _jsonable_hit(hit: Any) -> Any:
    if isinstance(hit, dict):
        return hit
    try:
        return dict(hit)
    except (TypeError, ValueError):
        return str(hit)


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
