# callback 字段说明

## 一、适用范围

callback 用于内容产出引擎、多媒体生成引擎把子任务执行状态和结果回传给流程执行引擎。

它不负责能力路由、知识库取材、真人确认组织，也不替代流程执行引擎的状态机。流程执行引擎仍然是派发子任务、接收结果、组织确认和推进后续节点的责任方。

## 二、请求侧字段

两个模块的子任务接口都支持以下可选字段：

| 字段 | 含义 |
|---|---|
| `callback_url` | 简化回调地址，通常用于本地流程执行引擎 `POST /api/flow/callback` |
| `callback_envelope_url` | 平台信封回调地址，通常用于正式流程执行引擎的标准 callback 接口 |
| `callback_protocol` | 可填 `simple` 或 `platform_v1`；传 `callback_envelope_url` 时默认 `platform_v1` |
| `callback_timeout_seconds` | 回调请求超时时间，默认 8 秒 |
| `callback_headers` | 回调请求附加请求头 |

这些字段也可以放在 `expected_return`、`policy` 或 `caller` 中，顶层字段优先。

## 三、simple 回调载荷

```json
{
  "callback_id": "CB-MM-CB-12345678-2",
  "trace_id": "TRACE-001",
  "workflow_instance_id": "FLOW-001",
  "instance_id": "FLOW-001",
  "node_id": "multimedia-generation",
  "task_id": "MM-CB-12345678",
  "subtask_id": "FLOW-SUBTASK-001",
  "idempotency_key": "IDEM-001-callback-2",
  "source_service": "l2.multimedia_generation.local_v1_1",
  "status": "completed",
  "result": {},
  "error": null,
  "audit_ref": "AUDIT-MM-CB-12345678",
  "callback_sequence": 2,
  "completed_at": "2026-07-17T21:50:00+08:00"
}
```

## 四、platform_v1 回调载荷

`platform_v1` 会把结果包进平台标准信封：

```json
{
  "protocol_version": "1.0",
  "message_id": "msg_xxx",
  "trace_id": "TRACE-001",
  "request_id": "req_MM-CB-12345678_2",
  "occurred_at": "2026-07-17T21:50:00+08:00",
  "source": {
    "layer": "L2",
    "service_code": "l2.multimedia_generation.local_v1_1"
  },
  "target": {
    "layer": "L2",
    "service_code": "l2.workflow_execution"
  },
  "channel": "callback",
  "action": "flow.callback",
  "request_type": "execute",
  "actor": {
    "person_id": "U001"
  },
  "context": {
    "workflow_instance_id": "FLOW-001",
    "node_id": "multimedia-generation"
  },
  "idempotency_key": "IDEM-001-platform-callback-2",
  "deadline_at": "2026-07-17T22:00:00+08:00",
  "payload": {
    "callback_id": "CB-MM-CB-12345678-2",
    "instance_id": "FLOW-001",
    "subtask_id": "FLOW-SUBTASK-001",
    "status": "completed",
    "result": {},
    "error": null,
    "audit_ref": "AUDIT-MM-CB-12345678",
    "callback_sequence": 2
  }
}
```

## 五、状态口径

| 回调状态 | 含义 |
|---|---|
| `in_progress` | 子任务已接收并开始后台执行 |
| `waiting_human` | 子任务已生成结果，但需要真人确认后才能交付 |
| `completed` | 子任务完成，可由流程执行引擎继续后续节点 |
| `failed` | 子任务失败，流程执行引擎应进入失败依赖或无法处理出口 |

本地原型通常回调 `in_progress` 和终态。正式平台如需要更多过程状态，可在不改变主状态口径的前提下扩展 `result.events`。
