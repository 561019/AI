# Intent Analysis API

This document describes the public HTTP API for Intent Analysis Engine.

Base URL for local development:

```text
http://127.0.0.1:8000
```

Interactive OpenAPI UI:

```text
http://127.0.0.1:8000/docs
```

## 1. Analyze Intent

```text
POST /api/v1/intent/analyze
```

Converts user input into a standard task list. The endpoint does not execute business tasks.

### Request

```json
{
  "text": "帮我再算一遍",
  "user_id": "user-001",
  "conversation_id": "conversation-001",
  "project_id": "project-001",
  "history": [
    {
      "role": "user",
      "text": "计算2025年销售提成"
    }
  ],
  "debug": false
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `text` | string | Yes | Current user input. |
| `user_id` | string | No | User id. Defaults to `anonymous`. |
| `conversation_id` | string | No | Conversation id. Defaults to a generated UUID. |
| `project_id` | string or null | No | Current project id, used when calling external Context Provider. |
| `history` | array | No | Optional explicit conversation history. Items accept `text`, `content`, or `message`. |
| `debug` | boolean | No | Whether to include internal analysis debug payload. |

### Success Response

```json
{
  "success": true,
  "data": {
    "tasks": [
      {
        "task_id": "generated-id",
        "task_type": "RULE_CALCULATION_COMMISSION",
        "task_description": "计算销售提成",
        "action": "计算",
        "object": "销售提成",
        "required_inputs": [],
        "missing_inputs": [],
        "clarification_session_id": null,
        "clarification_required": false,
        "clarification_questions": [],
        "status": "ready",
        "blocked_reason": null,
        "dependencies": [],
        "confidence": 0.9
      }
    ],
    "clarification_required": false,
    "global_clarification_required": false,
    "clarification_questions": []
  },
  "error": null,
  "debug": null
}
```

### Clarification Response

When the engine cannot safely infer the task, it returns no task and asks for clarification.

```json
{
  "success": true,
  "data": {
    "tasks": [],
    "clarification_required": true,
    "clarification_questions": [
      "请明确需要处理的业务对象和具体动作。"
    ]
  },
  "error": null,
  "debug": null
}
```

### Error Response

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "intent_analysis_failed",
    "message": "error message",
    "details": null
  },
  "debug": null
}
```

### Debug Payload

Set `debug=true` in the request body or query string to include internal diagnostics.

Useful debug fields include:

| Field | Description |
| --- | --- |
| `external_context` | Context Provider call status and returned context. |
| `context_resolution` | Whether omitted expression was resolved by context. |
| `contextual_input` | Unified input passed to rule, semantic, and LLM analysis. |
| `conversation_understanding` | Parsed conversation request and segments. |
| `segment_analyses` | Per-segment rule, semantic, and LLM debug data. |
| `long_context_extraction` | Long-text chunking and task extraction debug data. |
| `final_tasklist` | Final TaskList payload. |

Debug data must not contain API keys.

### PowerShell Example

```powershell
$body = @{
  text = "计算2025年销售提成"
  user_id = "user-001"
  conversation_id = "conversation-001"
  project_id = "project-001"
  debug = $true
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/intent/analyze" `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

## 2. Answer Clarification

```text
POST /api/v1/intent/clarification/answer
```

Maps a user's clarification answer back to the original task. This endpoint does not create a new task and must preserve the original `task_id`.

### Request

```json
{
  "clarification_session_id": "CS-...",
  "answer": "使用2026规则，华东区域，ERP数据"
}
```

### Response

```json
{
  "task_id": "original-task-id",
  "status": "ready",
  "missing_inputs": [],
  "final_inputs": {
    "calculation_policy": "2026规则",
    "data_source": "ERP",
    "data_scope": "华东区域"
  },
  "clarification_questions": [],
  "clarification_session_id": "CS-...",
  "session_status": "COMPLETED"
}
```

## 3. Intent History

```text
GET /api/v1/intent/history
```

Returns saved intent analysis records.

Query parameters:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `user_id` | string | No | Filter by user id. |
| `analysis_level` | string or int | No | Filter by analysis level. |
| `limit` | int | No | Default `100`, maximum `500`. |
| `offset` | int | No | Default `0`. |

Example:

```text
GET /api/v1/intent/history?user_id=user-001&limit=20
```

## 4. Health

```text
GET /health
GET /health/ready
GET /api/health
GET /api/health/ready
```

`/health` returns service liveness. `/health/ready` additionally checks database and Milvus connectivity and may return HTTP 503 when dependencies are degraded.

## 5. Output Contract

The stable public output is:

```json
{
  "tasks": [
    {
      "task_id": "",
      "task_type": "",
      "task_description": "",
      "action": "",
      "object": "",
      "required_inputs": [],
      "missing_inputs": [],
      "clarification_session_id": null,
      "clarification_required": false,
      "clarification_questions": [],
      "status": "ready",
      "blocked_reason": null,
      "dependencies": [],
      "confidence": 0.0
    }
  ],
  "clarification_required": false,
  "global_clarification_required": false,
  "clarification_questions": []
}
```

Task status values:

- `ready`: task inputs are complete and the workflow engine may execute it.
- `needs_clarification`: task has missing, uncertain, or conflicting inputs.
- `waiting_dependency`: task must wait for an unresolved dependency task.

Old business execution fields must not appear in final `TaskList`.
