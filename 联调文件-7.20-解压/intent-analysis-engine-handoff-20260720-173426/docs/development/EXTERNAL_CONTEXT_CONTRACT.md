# External Context Provider Contract

Intent Analysis Engine consumes Context as an external dependency. The engine does not implement Context & Prompt Management, does not persist long-term context, and does not own prompt assembly for other systems.

## 1. Responsibility Boundary

Context module provides:

- Current conversation context.
- Current project context.
- Historical user-project context.
- Context items ordered enough for the engine to choose the nearest relevant item.

Intent Analysis Engine provides:

- A call boundary through `BaseContextProvider`.
- Context normalization into `ContextInput`.
- Context-aware omitted expression resolution.
- Passing context to rule, semantic, and LLM analysis.
- Clarification when context is insufficient.

The engine must not:

- Build a Context & Prompt Management system.
- Store or rank external project memory beyond the current request flow.
- Invent tasks from context alone without support from current input.

## 2. Python Interface

The external module should be adapted to this interface:

```python
class BaseContextProvider:
    def get_context(
        self,
        user_id: str,
        conversation_id: str,
        project_id: str | None = None,
    ) -> ContextProviderResponse:
        ...
```

Current adapter entry point:

```text
backend/app/services/context_provider/client.py
```

Mock implementation for tests:

```text
backend/app/services/context_provider/mock_provider.py
```

## 3. Request Parameters

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `user_id` | string | Yes | Current user id. |
| `conversation_id` | string | Yes | Current conversation id. |
| `project_id` | string or null | No | Current project id. |

The engine calls the provider once per analysis request.

## 4. Provider Response

```json
{
  "conversation_context": [],
  "project_context": [],
  "user_project_context": []
}
```

| Field | Meaning | Priority |
| --- | --- | --- |
| `conversation_context` | Current conversation context. | 1 |
| `project_context` | Current project context. | 2 |
| `user_project_context` | User historical project context. | 3 |

Priority rule:

```text
conversation > project > historical_projects
```

Within the same scope, nearer context overrides older context. Providers should return items from oldest to newest, because the engine inspects each scope from the end.

## 5. Recommended Context Item Shape

Context items are dictionaries. The engine accepts flexible item payloads, but the following shape is recommended:

```json
{
  "task_type": "RULE_CALCULATION_COMMISSION",
  "task_description": "计算销售提成",
  "source_text": "计算2025年销售提成",
  "action": "计算",
  "object": "销售提成",
  "created_at": "2026-07-17T08:00:00Z",
  "metadata": {
    "source": "context-service",
    "turn_id": "turn-001"
  }
}
```

Important fields:

| Field | Description |
| --- | --- |
| `task_type` | Standard registered task type when available. |
| `task_description` | Human-readable task description. |
| `source_text` | Original user text that produced the context item. |
| `action` | Task action, such as `计算`, `分析`, `生成`. |
| `object` | Business object, such as `销售提成`, `经营分析报告`. |

If a context item contains nested `tasks` or `result`, the engine can inspect the latest task-like item inside it.

## 6. Normalized Engine Input

The provider response is normalized into the unified input used by rule, semantic, and LLM analysis:

```json
{
  "user_input": "帮我再算一遍",
  "context": {
    "current_conversation": {
      "items": []
    },
    "current_project": {
      "items": []
    },
    "historical_projects": {
      "items": []
    }
  }
}
```

Provider field mapping:

| Provider field | Engine field |
| --- | --- |
| `conversation_context` | `context.current_conversation.items` |
| `project_context` | `context.current_project.items` |
| `user_project_context` | `context.historical_projects.items` |

## 7. Omitted Expression Behavior

The engine uses context for omitted expressions such as:

| Current input | Expected context family |
| --- | --- |
| `帮我再算一遍` / `重新计算` | calculation task |
| `接着改` | report or document generation task |
| `换个维度看看` | analysis task |

Example:

Provider returns:

```json
{
  "conversation_context": [
    {
      "task_type": "RULE_CALCULATION_COMMISSION",
      "task_description": "计算销售提成",
      "source_text": "计算2025年销售提成",
      "action": "计算",
      "object": "销售提成"
    }
  ],
  "project_context": [],
  "user_project_context": []
}
```

Current input:

```text
帮我再算一遍
```

Engine resolves it as:

```text
重新计算2025年销售提成
```

## 8. Insufficient Context

If the input requires context but the provider returns no relevant item, the engine must not guess.

Expected behavior:

```json
{
  "tasks": [],
  "clarification_required": true,
  "clarification_questions": [
    "请明确要继续处理的上一轮任务或业务对象。"
  ]
}
```

## 9. Error Handling

If the provider call fails, the engine catches the error, continues with empty context, and records the error in debug output.

Debug shape:

```json
{
  "external_context": {
    "enabled": true,
    "project_id": "project-001",
    "error": "provider error message",
    "context": {
      "conversation_context": [],
      "project_context": [],
      "user_project_context": []
    }
  }
}
```

Provider implementations should avoid returning sensitive fields that are not needed for intent analysis.

## 10. Mock Verification

Mock data:

```text
evaluation/mock_data/context_provider_call.json
```

Regression test:

```text
tests/backend/test_context_provider_integration.py::test_engine_calls_mock_external_context_module_and_consumes_context
```

Run:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest tests\backend\test_context_provider_integration.py -q -p no:cacheprovider
```

