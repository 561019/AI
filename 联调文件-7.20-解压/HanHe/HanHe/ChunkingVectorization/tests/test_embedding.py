from __future__ import annotations

import json
import unittest

import httpx

from chunk_vector_engine.embedding import SiliconFlowEmbeddingClient


class EmbeddingClientTests(unittest.TestCase):
    def test_batch_payload_order_and_query_instruction(self) -> None:
        requests: list[dict] = []

        def respond(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            requests.append(payload)
            data = [
                {"index": index, "embedding": [float(index), 1.0, 2.0, 3.0]}
                for index, _ in enumerate(payload["input"])
            ]
            return httpx.Response(200, json={"data": list(reversed(data))})

        client = SiliconFlowEmbeddingClient("test-key", dimensions=4, query_instruction="retrieve passages")
        client.client.close()
        client.client = httpx.Client(
            transport=httpx.MockTransport(respond),
            headers={"Authorization": "Bearer test-key"},
        )
        try:
            vectors = client.embed_documents(["first", "second"])
            query_vector = client.embed_query("payment terms")
        finally:
            client.close()

        self.assertEqual(vectors[0][0], 0.0)
        self.assertEqual(vectors[1][0], 1.0)
        self.assertEqual(requests[0]["model"], "Qwen/Qwen3-Embedding-8B")
        self.assertEqual(requests[0]["dimensions"], 4)
        self.assertEqual(requests[1]["input"], ["Instruct: retrieve passages\nQuery: payment terms"])
        self.assertEqual(len(query_vector), 4)


if __name__ == "__main__":
    unittest.main()

