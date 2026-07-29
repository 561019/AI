# Intent Analysis Engine

Intent Analysis Engine converts natural-language user requests into a standard `TaskList`. It understands single-turn input, multi-turn omitted expressions, long-text task extraction, task dependencies, required inputs, missing inputs, and clarification needs.

The module only performs intent understanding and task structuring. It does not execute business tasks, query business systems, generate final business documents, send reminders, or orchestrate workflow execution.

## Current Deliverables

| Requirement | Status | Location |
| --- | --- | --- |
| Independent startup | Ready | `scripts/start-local.ps1`, `scripts/stop-local.ps1`, `offline-demo/intent-offline-demo.html` |
| Test data | Ready | `evaluation/conversation_dataset.json`, `evaluation/long_text_dataset.json`, `evaluation/llm_regression/`, `evaluation/benchmark/datasets/` |
| Test result screenshot | Ready after verification run | `docs/reports/screenshots/` |
| API documentation | Ready | `docs/api/INTENT_ANALYSIS_API.md` |
| Mock data | Ready | `evaluation/mock_data/context_provider_call.json`, mock providers in `backend/app/services/` |
| README | Ready | this file, plus `offline-demo/README.md` |

## Quick Start

Native local development is the default workflow.

```powershell
cd D:\AIProjects\intent-analysis-engine
.\scripts\start-local.ps1
```

Default local endpoints:

```text
Frontend: http://127.0.0.1:5173/
Backend:  http://127.0.0.1:8000/
API:      http://127.0.0.1:8000/api/v1/intent/analyze
Docs:     http://127.0.0.1:8000/docs
```

Stop local services:

```powershell
.\scripts\stop-local.ps1
```

Offline demonstration without backend, database, model service, or network:

```text
offline-demo/intent-offline-demo.html
```

For external handoff and joint integration, use:

```text
docs/delivery/HANDOFF_RUNBOOK.md
```

Create a clean source package:

```powershell
.\scripts\create-handoff-package.ps1
```

## Configuration

Local configuration is loaded from `.env` and `.env.local`.

Daily development should use the mock LLM provider unless a live model regression is being run:

```env
LLM_PROVIDER=mock
LLM_MODEL=mock-llm
LLM_TIMEOUT_SECONDS=120
```

DeepSeek/OpenAI API keys must not be committed, printed, or written into logs.

## API

Main endpoint:

```text
POST /api/v1/intent/analyze
```

Example request:

```json
{
  "text": "计算2025年销售提成",
  "user_id": "user-001",
  "conversation_id": "conversation-001",
  "project_id": "project-001",
  "debug": false
}
```

Example response data shape:

```json
{
  "tasks": [
    {
      "task_id": "generated-id",
      "task_type": "RULE_CALCULATION_COMMISSION",
      "task_description": "计算销售提成",
      "action": "计算",
      "object": "销售提成",
      "required_inputs": [],
      "missing_inputs": [],
      "dependencies": [],
      "confidence": 0.9
    }
  ],
  "clarification_required": false,
  "clarification_questions": []
}
```

Full API contract: `docs/api/INTENT_ANALYSIS_API.md`.

## External Context Integration

The engine treats Context as an external dependency. It only calls and consumes context; it does not implement Context & Prompt Management.

Provider interface:

```python
get_context(user_id: str, conversation_id: str, project_id: str | None = None)
```

Expected provider response:

```json
{
  "conversation_context": [],
  "project_context": [],
  "user_project_context": []
}
```

Full contract: `docs/development/EXTERNAL_CONTEXT_CONTRACT.md`.

## Tests

Run backend regression:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest tests\backend -q -p no:cacheprovider
```

Run context provider integration tests:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest tests\backend\test_context_provider_integration.py -q -p no:cacheprovider
```

Run evaluation datasets:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe conversation_evaluation_runner.py --semantic-mode local --llm-mode off
.\.venv\Scripts\python.exe long_text_evaluation_runner.py --semantic-mode local --llm-mode off
```

Run production-style benchmark validation:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe evaluation\benchmark\benchmark_runner.py --split validation --semantic-mode local --llm-mode off
```

Benchmark failure analysis:

```text
evaluation/error_analysis/failure_report.json
evaluation/error_analysis/optimization_report.json
```

Blind benchmark requires an explicit guard:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe evaluation\benchmark\benchmark_runner.py --split blind_test --allow-blind-test --semantic-mode local --llm-mode off
```

## Mock Data

Context provider mock call:

```text
evaluation/mock_data/context_provider_call.json
```

Relevant mock providers:

```text
backend/app/services/context_provider/mock_provider.py
backend/app/services/model_gateway/providers/mock_provider.py
```

The mock LLM fallback output is explicit and must not pretend to be a real model result:

```json
{
  "fallback": true,
  "provider": "mock"
}
```

## Important Boundaries

- Final output is the standard `TaskList` only.
- Function Registry is only a task type registry.
- LLM is only used for understanding, not business execution.
- All LLM output must pass code-level validation before it enters `TaskList`.
- Context is consumed as an external dependency; the engine does not own context storage or prompt management.
