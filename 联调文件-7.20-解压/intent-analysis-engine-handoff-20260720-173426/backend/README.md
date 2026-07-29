# Backend

FastAPI backend for Intent Analysis Engine.

The backend converts natural-language requests into a standard `TaskList`. It includes conversation understanding, long-context task extraction, rule matching, semantic matching, LLM fallback through Model Gateway, input validation, and external context consumption.

## Start

From the repository root:

```powershell
.\scripts\start-local.ps1
```

Backend endpoint:

```text
http://127.0.0.1:8000
```

API docs:

```text
http://127.0.0.1:8000/docs
```

## Main API

```text
POST /api/v1/intent/analyze
GET  /api/v1/intent/history
GET  /health
GET  /health/ready
```

Full API contract:

```text
docs/api/INTENT_ANALYSIS_API.md
```

## Tests

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest tests\backend -q -p no:cacheprovider
```

## External Context

The backend only calls and consumes external context. It does not implement Context & Prompt Management.

Contract:

```text
docs/development/EXTERNAL_CONTEXT_CONTRACT.md
```
