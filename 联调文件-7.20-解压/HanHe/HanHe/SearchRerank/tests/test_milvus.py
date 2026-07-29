from __future__ import annotations

import unittest

from search_rerank.milvus import MilvusRetriever


class FakeMilvusClient:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def search(self, **kwargs: object) -> list[list[dict[str, object]]]:
        self.arguments = kwargs
        return [[
            {"id": "c1", "distance": 0.9, "entity": {
                "document_id": "doc1", "package_version": 1, "chunk_index": 0,
                "chunk_type": "text", "text": "authorized", "needs_review": False,
                "source_sha256": "sha", "metadata": {"business_tags": ["project:a", "tenant:1"]},
            }},
            {"id": "c2", "distance": 0.8, "entity": {
                "document_id": "doc2", "package_version": 1, "chunk_index": 0,
                "chunk_type": "text", "text": "wrong tag", "needs_review": False,
                "source_sha256": "sha", "metadata": {"business_tags": ["project:b"]},
            }},
        ]]


class MilvusTests(unittest.TestCase):
    def test_search_filters_all_business_tags_and_review_items(self) -> None:
        retriever = object.__new__(MilvusRetriever)
        retriever.client = FakeMilvusClient()
        retriever.collection_name = "chunks"
        hits = retriever.search(
            [0.1, 0.2], 5, ["doc1"], ["project:a", "tenant:1"], False, 200
        )
        self.assertEqual([hit.chunk_id for hit in hits], ["c1"])
        self.assertEqual(hits[0].vector_score, 0.9)
        self.assertIn('document_id in ["doc1"]', retriever.client.arguments["filter"])
        self.assertIn("needs_review == false", retriever.client.arguments["filter"])
        self.assertEqual(retriever.client.arguments["limit"], 15)


if __name__ == "__main__":
    unittest.main()
