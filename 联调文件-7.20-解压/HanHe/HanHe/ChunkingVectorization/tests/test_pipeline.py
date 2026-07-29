from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chunk_vector_engine.config import ChunkSettings
from chunk_vector_engine.pipeline import build_chunk_process, vectorize_process

from helpers import write_package


class FakeEmbedder:
    model = "fake-embedding"
    dimensions = 4

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0, 0.0, 0.5] for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


class FakeStore:
    collection_name = "test_chunks"

    def __init__(self) -> None:
        self.dimensions = 0
        self.records: list[dict] = []

    def ensure_collection(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def upsert(self, chunks: list[dict], vectors: list[list[float]], embedding_model: str = "") -> int:
        self.records.extend({"chunk": chunk, "vector": vector} for chunk, vector in zip(chunks, vectors, strict=True))
        return len(chunks)


class PipelineTests(unittest.TestCase):
    def test_vectorization_excludes_review_chunks_and_writes_audit_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = write_package(root / "standard", [
                self._block("b-1", "approved text", False),
                self._block("b-2", "pending text", True),
            ])
            process_dir = build_chunk_process(
                package, root / "output",
                ChunkSettings(target_tokens=10, max_tokens=20, min_tokens=1, overlap_tokens=2),
            )
            store = FakeStore()
            result = vectorize_process(process_dir, FakeEmbedder(), store, embedding_batch_size=1)
            self.assertEqual(result["statistics"]["chunks_eligible"], 1)
            self.assertEqual(result["statistics"]["chunks_skipped_review"], 1)
            self.assertEqual(len(store.records), 1)
            self.assertTrue((process_dir / "vectorization.jsonl").is_file())
            self.assertTrue((process_dir / "vectorization-manifest.json").is_file())

    @staticmethod
    def _block(block_id: str, text: str, needs_review: bool) -> dict:
        return {
            "block_id": block_id, "type": "paragraph", "order": int(block_id[-1]), "text": text,
            "page": None, "bbox": None, "confidence": 0.5 if needs_review else 1.0,
            "needs_review": needs_review, "heading_path": [], "source_ref": {"file_name": "test.docx"},
        }


if __name__ == "__main__":
    unittest.main()

