from __future__ import annotations

import unittest

from search_rerank.milvus import RetrievedChunk
from search_rerank.models import SearchRequest
from search_rerank.reranker import RerankResult
from search_rerank.security import PermissionDenied, PermissionPolicy
from search_rerank.service import SearchService


class FakeEmbedder:
    model = "embedding-model"
    dimensions = 2

    def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2]

    def close(self) -> None:
        pass


class FakeRetriever:
    collection_name = "chunks"

    def search(self, **kwargs: object) -> list[RetrievedChunk]:
        return [
            RetrievedChunk("c1", "doc1", 1, 0, "text", "first", 0.9, False, "sha", {
                "business_tags": ["project:test"], "page_start": 1, "page_end": 1,
                "source_block_ids": ["b1"], "source_refs": [{"page": 1}],
            }),
            RetrievedChunk("c2", "doc1", 1, 1, "text", "second", 0.8, False, "sha", {
                "business_tags": ["project:test"], "page_start": 2,
            }),
        ]

    def close(self) -> None:
        pass


class FakeReranker:
    model = "rerank-model"

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankResult]:
        return [RerankResult(1, 0.95), RerankResult(0, 0.5)][:top_n]

    def close(self) -> None:
        pass


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SearchService(
            FakeEmbedder(), FakeRetriever(), FakeReranker(), PermissionPolicy(allow_demo_actor=True), 200
        )

    def test_search_returns_reranked_traceable_hits(self) -> None:
        response = self.service.search("demo-user", SearchRequest(
            query="what is second", candidate_k=10, top_n=2, business_tags=["project:test"]
        ))
        self.assertEqual([item.chunk_id for item in response.items], ["c2", "c1"])
        self.assertEqual(response.items[0].rank, 1)
        self.assertEqual(response.items[1].source_block_ids, ["b1"])
        self.assertEqual(response.items[0].references["original"], "/v1/jobs/doc1/original")

    def test_unknown_local_actor_is_denied(self) -> None:
        with self.assertRaises(PermissionDenied):
            self.service.search("unknown", SearchRequest(
                query="query", candidate_k=10, top_n=2, business_tags=["project:test"]
            ))


if __name__ == "__main__":
    unittest.main()
