# Native Development

Native development is the default lightweight workflow. Docker remains available for production deployment and complete integration tests.

## Prerequisites

- Python 3.12 project virtual environment in `.venv`
- PostgreSQL 16 on `127.0.0.1:5432`
- Node.js with `frontend/node_modules` installed
- `BAAI/bge-base-zh-v1.5` present in the Hugging Face cache
- Local overrides in `.env.local`

## Start

```powershell
.\scripts\start-local.ps1
```

Endpoints:

```text
Frontend: http://127.0.0.1:5173/
Backend:  http://127.0.0.1:8000/
API:      http://127.0.0.1:8000/api/v1/intent/analyze
BGE:      http://127.0.0.1:8011/health (only while needed)
```

The first Level2 request starts the BGE worker and lazily creates `.runtime/intent_capability_vectors.npz` when the file does not exist. With the default `BGE_KEEP_WARM=false`, the worker exits after 60 idle seconds and Windows reclaims the model memory.

Keep BGE loaded for batch evaluation:

```powershell
.\scripts\stop-local.ps1
.\scripts\start-local.ps1 -KeepBGEWarm
```

Also start the deterministic Level3 demo service:

```powershell
.\scripts\start-local.ps1 -WithDemoLLM
```

Regenerate local capability vectors explicitly:

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe -m scripts.init_local_intent_capability_vectors
```

## Stop

```powershell
.\scripts\stop-local.ps1
```

## Docker Integration

Docker continues to use `VECTOR_BACKEND=milvus` and `EMBEDDING_RUNTIME=in_process`. Run it only for Milvus, container, migration, or deployment validation:

```powershell
docker compose --profile semantic --profile llm --profile frontend up -d --build
```
