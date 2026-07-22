# 最小闭环接口示例

以下示例使用缩略 JSON，正式请求仍须满足对应 OpenAPI schema。

## 1. 自然语言请求与异步受理

```json
{
  "protocol_version": "1.0",
  "message_id": "10000000-0000-4000-8000-000000000001",
  "request_id": "20000000-0000-4000-8000-000000000001",
  "trace_id": "30000000-0000-4000-8000-000000000001",
  "source": {"layer": "business_application", "module": "web_console"},
  "target": {"layer": "business_engine", "module": "engine_gateway", "capability": "intent.analyze"},
  "actor": {"actor_id": "user-001", "tenant_id": "company-01", "position_ids": ["sales-manager"], "authenticated": true},
  "context": {"project_id": "project-001", "conversation_id": "conversation-001"},
  "request_type": "execute",
  "action": "intent.analyze",
  "payload": {"utterance": "按七月份销售额计算我的销售提成"},
  "expected_response": {"mode": "async"},
  "idempotency_key": "intent-user001-20260721-001",
  "callback_url": "https://engine-gateway/api/v1/callbacks",
  "deadline_at": "2026-07-21T18:00:00+08:00"
}
```

返回 HTTP `202`：

```json
{
  "status": "accepted",
  "trace_id": "30000000-0000-4000-8000-000000000001",
  "request_id": "20000000-0000-4000-8000-000000000001",
  "in_reply_to": "10000000-0000-4000-8000-000000000001",
  "task_id": "40000000-0000-4000-8000-000000000001",
  "progress": 0,
  "status_url": "https://engine-gateway/api/v1/tasks/40000000-0000-4000-8000-000000000001",
  "data": null,
  "error": null
}
```

## 2. 等待意图确认

意图分析完成后发送 `task.waiting_human` 回调，内容中给出 `confirmation_ref` 和任务清单摘要。前端只负责展示，确认提交必须回到服务端。

```json
{
  "actor": {"actor_id": "user-001", "tenant_id": "company-01", "authenticated": true},
  "trace_id": "30000000-0000-4000-8000-000000000001",
  "content_version": "intent-v1",
  "decision": "confirm"
}
```

服务端依次校验身份、`human.confirm` 权限、确认对象版本和任务状态，随后生成确定性任务清单交给流程执行引擎。

## 3. 权限拒绝

流程准备读取七月销售数据时调用权限接口：

```json
{
  "actor": {"actor_id": "user-001", "tenant_id": "company-01", "authenticated": true},
  "action": "data.read",
  "resource": {"type": "data", "id": "sales-202607", "version": "1", "tenant_id": "company-01"},
  "scope": {"employee_id": "user-001", "period": "2026-07"},
  "trace_id": "30000000-0000-4000-8000-000000000001"
}
```

若返回 `decision=deny`，流程直接进入 `failed`，错误码为 `PERMISSION_DENIED`，规则计算引擎不会收到数据引用。

## 4. 规则计算同步完成

权限通过后，数据模块只返回受控 `data_ref`；流程执行引擎将 `rule_ref` 和 `data_ref` 交给规则计算引擎。规则计算同步返回：

```json
{
  "trace_id": "30000000-0000-4000-8000-000000000001",
  "state": "completed",
  "value": 12680.50,
  "unit": "CNY",
  "formula_version": "commission-2026-v3",
  "evidence_refs": [
    {"type": "rule", "id": "commission-rule-2026", "version": "3", "tenant_id": "company-01"},
    {"type": "data", "id": "sales-202607", "version": "1", "tenant_id": "company-01"}
  ],
  "result_ref": {"type": "result", "id": "result-001", "version": "1", "tenant_id": "company-01"}
}
```

流程在最终返回前再次判定当前真人对 `result_ref` 的读取权限，再通过业务应用层信息分发机制送回原对话框。

## 5. 前置条件不足

规则或数据引用不完整时，规则计算不得猜测：

```json
{
  "trace_id": "30000000-0000-4000-8000-000000000001",
  "state": "precondition_query_required",
  "required_inputs": [
    {"kind": "formal_rule", "description": "缺少当前有效的销售提成规则"},
    {"kind": "authorized_data", "description": "缺少本人七月份已授权销售数据"}
  ]
}
```

流程进入 `waiting_dependency`，补齐引用后使用同一 `trace_id`、新的 `message_id` 和新的子请求 `idempotency_key` 继续执行。
