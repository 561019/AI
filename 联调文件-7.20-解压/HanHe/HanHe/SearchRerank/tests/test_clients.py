from __future__ import annotations

import json
import unittest

import httpx

from search_rerank.embedding import SiliconFlowQueryEmbedder
from search_rerank.reranker import SiliconFlowReranker


class ClientTests(unittest.TestCase):
    def test_query_embedding_uses_instruction_and_dimension(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

        client = SiliconFlowQueryEmbedder(
            api_key="test-key",
            base_url="https://example.test/v1",
            model="Qwen/Qwen3-Embedding-8B",
            dimensions=2,
            timeout_seconds=1,
            max_retries=0,
            query_instruction="retrieve passages",
            transport=httpx.MockTransport(handler),
        )
        try:
            self.assertEqual(client.embed_query("test query"), [0.1, 0.2])
        finally:
            client.close()
        self.assertEqual(seen["model"], "Qwen/Qwen3-Embedding-8B")
        self.assertEqual(seen["dimensions"], 2)
        self.assertEqual(seen["input"], ["Instruct: retrieve passages\nQuery: test query"])

    def test_reranker_preserves_provider_order_and_indices(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"results": [
                {"index": 1, "relevance_score": 0.91},
                {"index": 0, "relevance_score": 0.35},
            ]})

        client = SiliconFlowReranker(
            api_key="test-key",
            base_url="https://example.test/v1",
            model="Qwen/Qwen3-Reranker-8B",
            instruction="rank by relevance",
            timeout_seconds=1,
            max_retries=0,
            transport=httpx.MockTransport(handler),
        )
        try:
            results = client.rerank("query", ["first", "second"], 2)
        finally:
            client.close()
        self.assertEqual([result.index for result in results], [1, 0])
        self.assertEqual(seen["instruction"], "rank by relevance")
        self.assertEqual(seen["return_documents"], False)
        self.assertNotIn("overlap_tokens", seen)


if __name__ == "__main__":
    unittest.main()
