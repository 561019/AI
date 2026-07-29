# Local Test Model Service

OpenAI-compatible test service for local demos.

It is not a real model service. It provides deterministic responses for:

- `GET /v1/models`
- `POST /v1/embeddings`
- `POST /v1/chat/completions`
- `POST /v1/rerank`

The embedding endpoint returns 1024-dimensional vectors so the intent engine can run Level2 semantic matching without downloading model weights.
