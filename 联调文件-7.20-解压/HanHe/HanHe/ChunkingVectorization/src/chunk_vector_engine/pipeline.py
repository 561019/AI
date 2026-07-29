from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .chunker import SemanticChunker
from .config import ChunkSettings
from .embedding import EmbeddingProvider
from .milvus_store import VectorStore
from .process_store import ProcessStore
from .standard_package import open_standard_package


def build_chunk_process(source: Path, output_root: Path, settings: ChunkSettings | None = None) -> Path:
    active_settings = settings or ChunkSettings()
    with open_standard_package(source) as package:
        chunks = SemanticChunker(active_settings).chunk(package)
        return ProcessStore(output_root).save_chunks(package, chunks, active_settings)


def vectorize_process(
    process_dir: Path,
    embedder: EmbeddingProvider,
    vector_store: VectorStore,
    embedding_batch_size: int = 16,
    milvus_batch_size: int = 100,
) -> dict[str, Any]:
    manifest, chunks = ProcessStore.load_chunks(process_dir)
    eligible = [chunk for chunk in chunks if chunk.get("eligible_for_embedding", True)]
    vector_store.ensure_collection(embedder.dimensions)
    records: list[dict[str, Any]] = []
    stored = 0
    for embed_start in range(0, len(eligible), embedding_batch_size):
        batch = eligible[embed_start : embed_start + embedding_batch_size]
        vectors = embedder.embed_documents([str(chunk["embedding_text"]) for chunk in batch])
        for store_start in range(0, len(batch), milvus_batch_size):
            store_chunks = batch[store_start : store_start + milvus_batch_size]
            store_vectors = vectors[store_start : store_start + milvus_batch_size]
            count = vector_store.upsert(store_chunks, store_vectors, embedding_model=embedder.model)
            stored += count
        records.extend({
            "chunk_id": chunk["chunk_id"],
            "status": "stored",
            "model": embedder.model,
            "dimensions": embedder.dimensions,
            "collection": vector_store.collection_name,
            "vector_saved_in_process_files": False,
        } for chunk in batch)

    process_store = ProcessStore(process_dir.parent.parent.parent)
    vectorization_path = process_dir / "vectorization.jsonl"
    process_store._write_jsonl(vectorization_path, records)
    result = {
        "schema": "vectorization-process/v1",
        "document_id": manifest["document_id"],
        "source_package_version": manifest["source_package"]["package_version"],
        "embedding": {"provider": "SiliconFlow", "model": embedder.model, "dimensions": embedder.dimensions},
        "vector_store": {"type": "Milvus", "collection": vector_store.collection_name},
        "statistics": {
            "chunks_total": len(chunks),
            "chunks_eligible": len(eligible),
            "chunks_skipped_review": len(chunks) - len(eligible),
            "vectors_stored": stored,
        },
        "artifacts": {"records": vectorization_path.name},
        "created_at": datetime.now(UTC).isoformat(),
    }
    process_store._write_json(process_dir / "vectorization-manifest.json", result)
    return result
