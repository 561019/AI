# Intent Analysis Engine Handoff Runbook

This runbook is for integration partners who receive the project as a source package.

## 1. What This Module Does

Intent Analysis Engine converts user natural-language input into a standard `TaskList`.

It does not:

- execute business tasks
- query real business systems
- generate final business documents
- send real reminders
- orchestrate workflows

Primary API:

```text
POST /api/v1/intent/analyze
```

API documentation:

```text
docs/api/INTENT_ANALYSIS_API.md
```

External Context contract:

```text
docs/development/EXTERNAL_CONTEXT_CONTRACT.md
```

## 2. Package Contents

The handoff package should include:

```text
backend/
database/
docs/
evaluation/
frontend/
local-model-service/
offline-demo/
scripts/
tests/
.env.example
.env.local.example
docker-compose.yml
docker-compose.demo.yml
README.md
```

The package must not include:

```text
.git/
.codex/
.agents/
.venv/
frontend/node_modules/
.runtime/
__pycache__/
.pytest_cache/
.env
.env.local
*.log
```

Use the helper script:

```powershell
.\scripts\create-handoff-package.ps1
```

Preview package rules without creating a zip:

```powershell
.\scripts\create-handoff-package.ps1 -DryRun
```

If PowerShell execution policy blocks local scripts, use:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\create-handoff-package.ps1 -DryRun
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\create-handoff-package.ps1
```

## 3. Recommended Startup: Docker

Docker is the most reliable handoff mode because it avoids local Python, Node, and PostgreSQL differences.

Prerequisites:

- Docker Desktop
- Network access to pull base images

From the project root:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Check service status:

```powershell
docker compose ps
```

Check backend health:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Optional frontend:

```powershell
docker compose --profile frontend up -d --build
```

Optional full semantic stack with Milvus:

```powershell
docker compose --profile semantic --profile frontend up -d --build
```

Optional deterministic local demo LLM:

```powershell
docker compose --profile llm --profile frontend up -d --build
```

Stop:

```powershell
docker compose down
```

Reset Docker volumes only when a clean database/vector state is required:

```powershell
docker compose down -v
```

## 4. Native Windows Startup

Use this mode when the partner wants to run and debug source code directly.

Prerequisites:

- Python 3.12
- Node.js
- PostgreSQL 16 on `127.0.0.1:5432`
- PowerShell
- Optional: local Hugging Face cache for `BAAI/bge-base-zh-v1.5`

### 4.1 Create Environment Files

```powershell
Copy-Item .env.local.example .env.local
```

Default local LLM provider is mock:

```env
LLM_PROVIDER=mock
LLM_MODEL=mock-llm
LLM_TIMEOUT_SECONDS=120
```

Do not write real API keys into committed files or screenshots.

### 4.2 Install Backend Dependencies

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
```

### 4.3 Install Frontend Dependencies

```powershell
npm.cmd --prefix frontend install
```

### 4.4 Prepare PostgreSQL

If the database does not exist yet, create the role and database with a PostgreSQL admin user:

```powershell
psql -U postgres -c "CREATE USER intent WITH PASSWORD 'intent';"
psql -U postgres -c "CREATE DATABASE intent_analysis OWNER intent;"
```

Initialize schema and seed data:

```powershell
psql -U intent -d intent_analysis -f database/init/001_schema.sql
psql -U intent -d intent_analysis -f database/init/002_seed_data.sql
```

If the role or database already exists, skip the failing create command and continue with schema initialization.

### 4.5 Start Local Services

```powershell
.\scripts\start-local.ps1
```

Start backend only:

```powershell
.\scripts\start-local.ps1 -NoFrontend
```

Keep BGE worker warm for repeated semantic evaluation:

```powershell
.\scripts\start-local.ps1 -KeepBGEWarm
```

Start deterministic demo LLM:

```powershell
.\scripts\start-local.ps1 -WithDemoLLM
```

Stop:

```powershell
.\scripts\stop-local.ps1
```

## 5. Endpoints

```text
Backend:  http://127.0.0.1:8000/
Health:   http://127.0.0.1:8000/health
API docs: http://127.0.0.1:8000/docs
Frontend: http://127.0.0.1:5173/
API:      http://127.0.0.1:8000/api/v1/intent/analyze
Clarify:  http://127.0.0.1:8000/api/v1/intent/clarification/answer
History:  http://127.0.0.1:8000/api/v1/intent/history
```

Offline demo without backend or database:

```text
offline-demo/intent-offline-demo.html
```

## 6. Smoke Test

```powershell
$body = @{
  text = "计算2025年销售提成"
  user_id = "handoff-user"
  conversation_id = "handoff-conversation"
  project_id = "handoff-project"
  debug = $true
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/intent/analyze" `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

Expected response shape:

```json
{
  "success": true,
  "data": {
    "tasks": [],
    "clarification_required": true,
    "clarification_questions": []
  },
  "error": null
}
```

The exact task and clarification fields may vary with configuration and registered capabilities, but the response must use the standard TaskList contract.

Clarification recovery endpoint:

```text
POST /api/v1/intent/clarification/answer
```

It accepts `clarification_session_id` plus the user's answer, fills the original task inputs, and preserves the original `task_id`.

## 7. Verification Commands

Backend regression:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest tests\backend -q -p no:cacheprovider
```

Context Provider integration:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest tests\backend\test_context_provider_integration.py -q -p no:cacheprovider
```

Benchmark validation:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe evaluation\benchmark\benchmark_runner.py --split validation --semantic-mode local --llm-mode off
```

Do not use `blind_test` for development. It requires an explicit guard only for final reporting:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe evaluation\benchmark\benchmark_runner.py --split blind_test --allow-blind-test --semantic-mode local --llm-mode off
```

## 8. Integration Notes

### Context Provider

The engine consumes external context through:

```python
get_context(user_id, conversation_id, project_id)
```

Expected response:

```json
{
  "conversation_context": [],
  "project_context": [],
  "user_project_context": []
}
```

Mock context data:

```text
evaluation/mock_data/context_provider_call.json
```

### Model Gateway

Default local mode:

```env
LLM_PROVIDER=mock
```

Live providers require external credentials:

```env
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=...
LLM_MODEL=deepseek-chat
LLM_TIMEOUT_SECONDS=120
```

Never log or commit API keys.

## 9. Common Issues

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| `Project virtual environment was not found` | `.venv` has not been created | Run backend dependency installation commands. |
| `Frontend dependencies were not found` | `frontend/node_modules` missing | Run `npm.cmd --prefix frontend install`. |
| Backend cannot connect to database | PostgreSQL not running or database not initialized | Check `DATABASE_URL`, create database, run SQL init files. |
| Port 8000 or 5173 already in use | Another service is running | Stop the old service or change `BACKEND_PORT` / `FRONTEND_PORT`. |
| BGE model startup fails | Model not cached or network unavailable | Use Docker semantic stack, pre-cache model, or run with semantic mode off for basic tests. |
| LLM call fails | Missing provider config or network issue | Use `LLM_PROVIDER=mock` for local handoff. |
| Response contains no task | Input may be ambiguous or missing context | Check `clarification_required` and `debug.context_resolution`. |

## 10. Handoff Checklist

Before sending the package:

- Run `.\scripts\create-handoff-package.ps1 -DryRun`.
- If execution policy blocks scripts, run it through `powershell.exe -NoProfile -ExecutionPolicy Bypass -File`.
- Confirm `.env` and `.env.local` are not included.
- Confirm `.venv` and `frontend/node_modules` are not included.
- Include this runbook.
- Include `README.md`.
- Include API docs and Context Provider contract.
- Include benchmark dataset and mock data.
- Share any real API keys through a secure channel outside the package, only if live LLM testing is required.
